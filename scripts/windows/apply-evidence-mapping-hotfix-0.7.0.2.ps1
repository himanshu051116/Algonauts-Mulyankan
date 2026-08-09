$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $RepoRoot

Write-Host "Mulyankan 0.7.0.2 evidence-mapping hotfix" -ForegroundColor Green
if (-not (Test-Path (Join-Path $RepoRoot ".env"))) {
    throw ".env is missing. Copy the working 0.7.0.1 .env into this hotfix source folder."
}

docker info | Out-Null
docker compose config --quiet

Write-Host "Building backend, worker and frontend..." -ForegroundColor Cyan
docker compose build backend worker frontend

Write-Host "Recreating application services without changing data volumes..." -ForegroundColor Cyan
docker compose up -d --no-deps --force-recreate backend worker frontend

Write-Host "Waiting for backend readiness..." -ForegroundColor Cyan
$ready = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod "http://localhost:8000/health" -TimeoutSec 5
        $readiness = Invoke-RestMethod "http://localhost:8000/health/ready" -TimeoutSec 5
        if ($health.version -eq "0.7.0.2" -and $readiness.status -eq "ready") {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $ready) {
    docker compose ps -a
    throw "The hotfix services did not become ready with version 0.7.0.2."
}

docker compose ps -a
Write-Host "Hotfix verification passed." -ForegroundColor Green
Write-Host "Create one new governed-package evaluation; historical records remain unchanged for audit."
