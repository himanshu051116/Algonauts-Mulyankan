$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptPath = $PSScriptRoot
. (Join-Path $ScriptPath "common.ps1")
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $ScriptPath "..\.."))
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

function Wait-HttpOk {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [int]$TimeoutSeconds = 180
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) { return $response }
        } catch {}
        Start-Sleep -Seconds 5
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for $Uri"
}

Write-Host "Mulyankan 0.7.0 governed submission-package upgrade" -ForegroundColor Green
Write-Host "Source: $RepoRoot"

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".env"))) {
    throw ".env is missing. Copy the working 0.6.3 .env into this new 0.7.0 source folder before upgrading."
}

Invoke-Checked "Docker Engine check" { docker info --format '{{.ServerVersion}}' }
Invoke-Checked "Compose configuration validation" { docker compose config --quiet }

# Start only infrastructure so a consistent logical backup can be created.
Invoke-Checked "Start infrastructure" { docker compose up -d postgres redis minio minio-init }

$postgresReady = $false
for ($i = 0; $i -lt 36; $i++) {
    docker compose exec -T postgres sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $postgresReady = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $postgresReady) { throw "PostgreSQL did not become ready." }

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $RepoRoot "backups\upgrade-0.7.0-$timestamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$dumpPath = Join-Path $backupDir "postgres-pre-0.7.0.dump"

Invoke-Checked "Create PostgreSQL custom-format backup" {
    docker compose exec -T postgres sh -lc 'rm -f /tmp/postgres-pre-0.7.0.dump && pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/postgres-pre-0.7.0.dump'
}
Invoke-Checked "Copy PostgreSQL backup to host" {
    docker compose cp "postgres:/tmp/postgres-pre-0.7.0.dump" $dumpPath
}
if (-not (Test-Path -LiteralPath $dumpPath) -or (Get-Item -LiteralPath $dumpPath).Length -lt 1024) {
    throw "The PostgreSQL backup was not created correctly. Upgrade stopped before migration."
}
Copy-Item -LiteralPath (Join-Path $RepoRoot ".env") -Destination (Join-Path $backupDir ".env.pre-0.7.0") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "docker-compose.yml") -Destination (Join-Path $backupDir "docker-compose.pre-0.7.0.yml") -Force
Write-Host "Backup created at: $backupDir" -ForegroundColor Green

Invoke-Checked "Build migration, backend, worker, and frontend images" {
    docker compose build migration backend worker frontend
}

# Running twice proves that migrations and reference-data seeding are idempotent.
Invoke-Checked "Migration and seed pass 1" { docker compose run --rm migration }
Invoke-Checked "Migration and seed pass 2" { docker compose run --rm migration }

try {
    Invoke-Checked "Start upgraded stack" { docker compose up -d --remove-orphans }
} catch {
    Write-Host "`n=== Failed stack status ===" -ForegroundColor Yellow
    docker compose ps -a
    Write-Host "`n=== Backend logs ===" -ForegroundColor Yellow
    docker compose logs backend --tail 200
    throw
}

$backendReady = Wait-HttpOk -Uri ($BackendUrl + "/health/ready") -TimeoutSeconds 240
$frontendReady = Wait-HttpOk -Uri ($FrontendUrl + "/healthz") -TimeoutSeconds 180
$health = Invoke-RestMethod -Uri ($BackendUrl + "/health") -TimeoutSec 10
if ($health.version -ne "0.7.0") {
    throw "Backend reported version '$($health.version)' instead of 0.7.0."
}

$invariantSql = @'
SELECT 'migration_head' AS check_name, version_num::text AS result FROM alembic_version;
SELECT 'nonreleased_runs_with_official_total' AS check_name, COUNT(*)::text AS result
FROM model_runs
WHERE scoring_status <> 'released' AND total_score IS NOT NULL;
SELECT 'released_criteria_without_evidence' AS check_name, COUNT(*)::text AS result
FROM criterion_predictions
WHERE released IS TRUE AND (awarded_score IS NULL OR evidence_count < 1);
SELECT 'active_model_count' AS check_name, COUNT(*)::text AS result
FROM model_versions
WHERE is_active IS TRUE;
SELECT 'duplicate_active_requirements' AS check_name, COUNT(*)::text AS result
FROM (
    SELECT proposal_version_id, requirement_id
    FROM proposal_documents
    WHERE requirement_id IS NOT NULL AND superseded_at IS NULL
    GROUP BY proposal_version_id, requirement_id
    HAVING COUNT(*) > 1
) AS duplicates;
SELECT 'confirmed_packages_without_hash' AS check_name, COUNT(*)::text AS result
FROM proposal_versions
WHERE package_status = 'confirmed'
  AND (package_hash IS NULL OR package_policy_version IS NULL OR package_manifest = '{}'::jsonb);
'@
Write-Host "`n=== Database scoring-safety invariants ===" -ForegroundColor Cyan
$invariantOutput = $invariantSql | docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -q -A -t -F "," -P pager=off'
if ($LASTEXITCODE -ne 0) { throw "Database invariant query failed." }
$invariantOutput | ForEach-Object { Write-Host $_ }

$values = @{}
foreach ($line in $invariantOutput) {
    if ($line -match '^([^,]+),(.+)$') { $values[$matches[1]] = $matches[2] }
}
if ($values["migration_head"] -ne "20260708_packages") {
    throw "Unexpected migration head: $($values['migration_head'])"
}
if ($values["nonreleased_runs_with_official_total"] -ne "0") {
    throw "Scoring invariant failed: a non-released run has an official total."
}
if ($values["released_criteria_without_evidence"] -ne "0") {
    throw "Scoring invariant failed: a released criterion lacks verified evidence."
}
if ($values["active_model_count"] -ne "1") {
    throw "Expected exactly one active model, found $($values['active_model_count'])."
}
if ($values["duplicate_active_requirements"] -ne "0") {
    throw "Package invariant failed: duplicate active requirement assignments exist."
}
if ($values["confirmed_packages_without_hash"] -ne "0") {
    throw "Package invariant failed: a confirmed package lacks its manifest identity."
}

Write-Host "`n=== Final container status ===" -ForegroundColor Cyan
docker compose ps -a
if ($LASTEXITCODE -ne 0) { throw "Could not read final container status." }

Write-Host "`nUpgrade verification passed." -ForegroundColor Green
Write-Host "Frontend: $FrontendUrl"
Write-Host "Backend:  $BackendUrl"
Write-Host "Backup:   $backupDir"
Write-Host "Do not delete the 0.6.3 source or this backup until governed package and end-to-end evaluation tests pass."
