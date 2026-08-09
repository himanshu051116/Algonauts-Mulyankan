$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $RepoRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    Write-Host "`n=== $Description ===" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Get-ContainerEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $output = docker compose exec -T $Service printenv $Name
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read $Name from service '$Service'."
    }

    $value = ($output | Select-Object -Last 1).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Service '$Service' returned an empty value for $Name."
    }

    return $value
}

function Get-PackagedModelHash {
    param([Parameter(Mandatory = $true)][string]$Service)

    $pythonCode = "from app.services.model_registry import brochure_ml_artifact_hash; print(brochure_ml_artifact_hash())"

    $output = docker compose run --rm --no-deps -T `
        --workdir /app `
        -e PYTHONPATH=/app/backend `
        $Service `
        python -c $pythonCode

    if ($LASTEXITCODE -ne 0) {
        throw "Could not calculate the packaged model hash in service '$Service'."
    }

    $hash = ($output | Select-Object -Last 1).Trim()
    if ($hash -notmatch '^[0-9a-f]{64}$') {
        throw "Service '$Service' returned an invalid model hash: $hash"
    }

    return $hash
}

function Get-CoreRecordCounts {
    $query = @"
SELECT
    (SELECT count(*) FROM proposals),
    (SELECT count(*) FROM proposal_versions),
    (SELECT count(*) FROM proposal_documents),
    (SELECT count(*) FROM model_runs),
    (SELECT count(*) FROM expert_reviews);
"@

    $output = docker compose exec -T postgres `
        psql `
        -U $script:PostgresUser `
        -d $script:PostgresDatabase `
        --tuples-only `
        --no-align `
        '--field-separator=|' `
        --command $query

    if ($LASTEXITCODE -ne 0) {
        throw "Could not read pre-existing core record counts."
    }

    $line = (
        $output |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -match '^\d+\|\d+\|\d+\|\d+\|\d+$' } |
        Select-Object -Last 1
    )

    if (-not $line) {
        throw "Core record count output was not parseable."
    }

    return $line
}

function Invoke-PythonModuleInRunContainer {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string]$Module
    )

    docker compose run --rm --no-deps -T `
        --workdir /app `
        -e PYTHONPATH=/app/backend `
        $Service `
        python -m $Module
}

function Invoke-PythonModuleInLiveContainer {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string]$Module
    )

    docker compose exec -T `
        --workdir /app `
        -e PYTHONPATH=/app/backend `
        $Service `
        python -m $Module
}

Write-Host "Mulyankan 0.8.0 - Expert-Grounded Validation and Shadow Pilot" -ForegroundColor Green
Write-Host "This upgrade is additive and does not change the existing advisory scoring model."

if (-not (Test-Path (Join-Path $RepoRoot ".env"))) {
    throw ".env is missing. Copy the working 0.7.0.3 .env into this source folder before upgrading."
}

Invoke-Checked "Docker Engine check" {
    docker info --format '{{.ServerVersion}}'
}

Invoke-Checked "Compose configuration validation" {
    docker compose config --quiet
}

Invoke-Checked "Start infrastructure" {
    docker compose up -d postgres redis minio minio-init
}

Write-Host "`n=== Resolve PostgreSQL container settings ===" -ForegroundColor Cyan
$script:PostgresUser = Get-ContainerEnvironmentValue -Service "postgres" -Name "POSTGRES_USER"
$script:PostgresDatabase = Get-ContainerEnvironmentValue -Service "postgres" -Name "POSTGRES_DB"
Write-Host "PostgreSQL user: $script:PostgresUser"
Write-Host "PostgreSQL database: $script:PostgresDatabase"

Write-Host "`n=== Wait for PostgreSQL readiness ===" -ForegroundColor Cyan
$postgresReady = $false
for ($attempt = 1; $attempt -le 45; $attempt++) {
    docker compose exec -T postgres `
        pg_isready `
        -U $script:PostgresUser `
        -d $script:PostgresDatabase *> $null

    if ($LASTEXITCODE -eq 0) {
        $postgresReady = $true
        break
    }

    Start-Sleep -Seconds 2
}

if (-not $postgresReady) {
    docker compose ps -a
    docker compose logs postgres --tail 150
    throw "PostgreSQL did not become ready."
}

Invoke-Checked "Stop application services for a consistent backup" {
    docker compose stop frontend backend worker
}

$preUpgradeCounts = Get-CoreRecordCounts
Write-Host "Pre-upgrade core counts: $preUpgradeCounts"

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $RepoRoot "backups\upgrade-0.8.0-$timestamp"
$null = New-Item -ItemType Directory -Path $backupDir -Force

$databaseBackup = Join-Path $backupDir "postgres-before-0.8.0.sql"
$configBackup = Join-Path $backupDir ".env-backup.txt"
$composeBackup = Join-Path $backupDir "docker-compose.yml"
$temporaryDumpPath = "/tmp/mulyankan-before-0.8.0-$timestamp.sql"

Write-Host "`n=== Create pre-migration backup ===" -ForegroundColor Cyan

docker compose exec -T postgres `
    pg_dump `
    -U $script:PostgresUser `
    -d $script:PostgresDatabase `
    --clean `
    --if-exists `
    --no-owner `
    --file $temporaryDumpPath

if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL backup creation failed inside the container."
}

$postgresContainerId = (docker compose ps -q postgres | Select-Object -Last 1).Trim()
if ([string]::IsNullOrWhiteSpace($postgresContainerId)) {
    throw "Could not resolve the PostgreSQL container ID."
}

docker cp "${postgresContainerId}:$temporaryDumpPath" $databaseBackup
if ($LASTEXITCODE -ne 0) {
    throw "Could not copy the PostgreSQL backup to the host."
}

docker compose exec -T postgres rm -f $temporaryDumpPath
if ($LASTEXITCODE -ne 0) {
    Write-Warning "The temporary PostgreSQL dump could not be removed from the container."
}

if (
    -not (Test-Path -LiteralPath $databaseBackup) -or
    (Get-Item -LiteralPath $databaseBackup).Length -lt 100
) {
    throw "PostgreSQL backup produced an invalid host file."
}

Copy-Item -LiteralPath (Join-Path $RepoRoot ".env") -Destination $configBackup -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "docker-compose.yml") -Destination $composeBackup -Force

@{
    version = "0.8.0"
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    core_record_counts = $preUpgradeCounts
    postgres_user = $script:PostgresUser
    postgres_database = $script:PostgresDatabase
    compose_project_name = (
        (
            Select-String `
                -Path (Join-Path $RepoRoot ".env") `
                -Pattern '^COMPOSE_PROJECT_NAME=' |
            Select-Object -First 1
        ).Line
    )
} |
    ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $backupDir "backup-manifest.json") -Encoding UTF8

Write-Host "Backup: $backupDir" -ForegroundColor Green

Write-Host "`n=== Build application and migration images ===" -ForegroundColor Cyan
docker compose build migration backend worker frontend
if ($LASTEXITCODE -ne 0) {
    throw "Image build failed. The pre-upgrade backup is at $backupDir."
}

Write-Host "`n=== Verify evaluator identity across images ===" -ForegroundColor Cyan
$backendHash = Get-PackagedModelHash -Service "backend"
$workerHash = Get-PackagedModelHash -Service "worker"
$migrationHash = Get-PackagedModelHash -Service "migration"

Write-Host "backend:   $backendHash"
Write-Host "worker:    $workerHash"
Write-Host "migration: $migrationHash"

if ($backendHash -ne $workerHash -or $backendHash -ne $migrationHash) {
    throw "Backend, worker, and migration images do not contain the same evaluator artifact."
}

Invoke-Checked "Run additive migration and refresh reference/model registry" {
    docker compose run --rm --no-deps -T migration
}

Invoke-Checked "Verify model registry from migration image" {
    Invoke-PythonModuleInRunContainer `
        -Service "migration" `
        -Module "backend.scripts.verify_model_registry"
}

Invoke-Checked "Verify 0.8 validation schema from migration image" {
    Invoke-PythonModuleInRunContainer `
        -Service "migration" `
        -Module "backend.scripts.verify_validation_pilot"
}

$postMigrationCounts = Get-CoreRecordCounts
Write-Host "Post-migration core counts: $postMigrationCounts"

if ($preUpgradeCounts -ne $postMigrationCounts) {
    throw "Core record counts changed during the additive migration. Restore from $databaseBackup before retrying."
}

Write-Host "`n=== Recreate application services ===" -ForegroundColor Cyan
docker compose up -d --no-deps --force-recreate backend worker frontend

if ($LASTEXITCODE -ne 0) {
    docker compose ps -a
    docker compose logs backend --tail 250
    docker compose logs worker --tail 250
    throw "Application service recreation failed. The database backup is at $databaseBackup."
}

$ready = $false
for ($attempt = 1; $attempt -le 75; $attempt++) {
    try {
        $health = Invoke-RestMethod "http://localhost:8000/health" -TimeoutSec 5
        $readiness = Invoke-RestMethod "http://localhost:8000/health/ready" -TimeoutSec 5

        if ($health.version -eq "0.8.0" -and $readiness.status -eq "ready") {
            $ready = $true
            break
        }
    }
    catch {
        # Continue waiting while containers initialise.
    }

    Start-Sleep -Seconds 2
}

if (-not $ready) {
    docker compose ps -a
    docker compose logs backend --tail 250
    docker compose logs worker --tail 250
    throw "Mulyankan did not become ready with version 0.8.0. The database backup is at $databaseBackup."
}

Invoke-Checked "Verify live backend model registry" {
    Invoke-PythonModuleInLiveContainer `
        -Service "backend" `
        -Module "backend.scripts.verify_model_registry"
}

Invoke-Checked "Verify live worker model registry" {
    Invoke-PythonModuleInLiveContainer `
        -Service "worker" `
        -Module "backend.scripts.verify_model_registry"
}

Invoke-Checked "Verify live 0.8 validation schema" {
    Invoke-PythonModuleInLiveContainer `
        -Service "backend" `
        -Module "backend.scripts.verify_validation_pilot"
}

$finalCounts = Get-CoreRecordCounts
if ($preUpgradeCounts -ne $finalCounts) {
    throw "Core record counts changed after service startup. Investigate before using the pilot."
}

docker compose ps -a

Write-Host "`nUpgrade verification passed." -ForegroundColor Green
Write-Host "Version: 0.8.0"
Write-Host "Backup: $backupDir"
Write-Host "Existing proposals, documents, evaluations, reviews and model runs were preserved."
Write-Host "Expert-grounded validation operates in shadow mode and does not alter proposal decisions."
Write-Host "Do not delete the 0.7.0.3 source or this backup until a pilot study and rollback rehearsal pass."
