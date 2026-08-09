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

function Get-PackagedModelHash {
    param([Parameter(Mandatory = $true)][string]$Service)
    $output = docker compose run --rm --no-deps -T $Service `
        sh -lc "cd /app && PYTHONPATH=/app/backend python -c 'from app.services.model_registry import brochure_ml_artifact_hash; print(brochure_ml_artifact_hash())'"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not calculate the packaged model hash in service '$Service'."
    }
    $hash = ($output | Select-Object -Last 1).Trim()
    if ($hash -notmatch '^[0-9a-f]{64}$') {
        throw "Service '$Service' returned an invalid model hash: $hash"
    }
    return $hash
}

Write-Host "Mulyankan 0.7.0.3 registry-consistency hotfix" -ForegroundColor Green
if (-not (Test-Path (Join-Path $RepoRoot ".env"))) {
    throw ".env is missing. Copy the working 0.7.0.2 .env into this source folder."
}

Invoke-Checked "Docker Engine check" { docker info --format '{{.ServerVersion}}' }
Invoke-Checked "Compose configuration validation" { docker compose config --quiet }
Invoke-Checked "Start infrastructure" { docker compose up -d postgres redis minio minio-init }

Write-Host "`n=== Build all evaluator-bearing images ===" -ForegroundColor Cyan
docker compose build migration backend worker frontend
if ($LASTEXITCODE -ne 0) { throw "Image build failed." }

Write-Host "`n=== Compare packaged evaluator identities ===" -ForegroundColor Cyan
$backendHash = Get-PackagedModelHash -Service "backend"
$workerHash = Get-PackagedModelHash -Service "worker"
$migrationHash = Get-PackagedModelHash -Service "migration"
Write-Host "backend:   $backendHash"
Write-Host "worker:    $workerHash"
Write-Host "migration: $migrationHash"
if ($backendHash -ne $workerHash -or $backendHash -ne $migrationHash) {
    throw "Backend, worker, and migration images do not contain the same evaluator artifact."
}

# The migration service is the authoritative idempotent path for both schema
# state and registry seeding. Running it after every evaluator-bearing build
# prevents a stale artifact hash from surviving a hotfix.
Invoke-Checked "Run migrations and refresh reference/model registry" {
    docker compose run --rm --no-deps -T migration
}

Invoke-Checked "Verify registry from worker image before startup" {
    docker compose run --rm --no-deps -T worker sh -lc `
        "cd /app && PYTHONPATH=/app/backend python -m backend.scripts.verify_model_registry"
}
Invoke-Checked "Verify registry from backend image before startup" {
    docker compose run --rm --no-deps -T backend sh -lc `
        "cd /app && PYTHONPATH=/app/backend python -m backend.scripts.verify_model_registry"
}

Write-Host "`n=== Recreate application services ===" -ForegroundColor Cyan
docker compose up -d --no-deps --force-recreate backend worker frontend
if ($LASTEXITCODE -ne 0) {
    docker compose ps -a
    docker compose logs backend --tail 200
    docker compose logs worker --tail 200
    throw "Application service recreation failed."
}

$ready = $false
for ($attempt = 1; $attempt -le 60; $attempt++) {
    try {
        $health = Invoke-RestMethod "http://localhost:8000/health" -TimeoutSec 5
        $readiness = Invoke-RestMethod "http://localhost:8000/health/ready" -TimeoutSec 5
        if ($health.version -eq "0.7.0.3" -and $readiness.status -eq "ready") {
            $ready = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    docker compose ps -a
    docker compose logs backend --tail 200
    docker compose logs worker --tail 200
    throw "The hotfix services did not become ready with version 0.7.0.3."
}

Invoke-Checked "Verify live worker registry after startup" {
    docker compose exec -T worker sh -lc `
        "cd /app && PYTHONPATH=/app/backend python -m backend.scripts.verify_model_registry"
}
Invoke-Checked "Verify live backend registry after startup" {
    docker compose exec -T backend sh -lc `
        "cd /app && PYTHONPATH=/app/backend python -m backend.scripts.verify_model_registry"
}

docker compose ps -a
Write-Host "`nHotfix verification passed." -ForegroundColor Green
Write-Host "Version: 0.7.0.3"
Write-Host "The active registry hash now matches backend, worker, and migration images."
Write-Host "Fresh preflight failures are displayed as Evaluation failed, never Legacy Unverified."
