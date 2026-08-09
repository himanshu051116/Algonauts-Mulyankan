$ErrorActionPreference = "Continue"

$ScriptPath = $PSScriptRoot
. (Join-Path $ScriptPath "common.ps1")
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path -Path $ScriptPath -ChildPath "..\.."))
Set-Location -LiteralPath $RepoRoot

Write-Host "=== Mulyankan Status ==="
Write-Host ""

# Docker Engine
Write-Host "--- Docker Engine ---"
$DockerInfo = docker info 2>&1 | Out-String
if ($DockerInfo -match "Server Version") {
    Write-Host "Status: Running" -ForegroundColor Green
} else {
    Write-Host "Status: NOT RUNNING" -ForegroundColor Red
    Write-Host "Start Docker Desktop manually or run start-mulyankan.ps1"
    exit 1
}
Write-Host ""

# Compose services
Write-Host "--- Compose Services ---"
docker compose ps

Write-Host ""
Write-Host "--- Service Health ---"
$Services = @("frontend", "backend", "postgres", "redis", "minio", "worker")
foreach ($svc in $Services) {
    $StatusLine = docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" $svc 2>&1 | Select-String -Pattern $svc
    if (-not $StatusLine) {
        Write-Host "$svc`: not found in compose" -ForegroundColor Yellow
        continue
    }
    if ($StatusLine -match "(healthy|Up)") {
        if ($StatusLine -match "healthy") {
            Write-Host "$svc`: healthy" -ForegroundColor Green
        } else {
            Write-Host "$svc`: up (no health check)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "$svc`: $StatusLine" -ForegroundColor Red
        Write-Host "--- Recent logs for $svc ---"
        docker compose logs --tail=5 $svc 2>&1 | ForEach-Object { "  $_" }
        Write-Host ""
    }
}

Write-Host ""
Write-Host "--- HTTP Status ---"
try {
    $FrontendHealth = Invoke-WebRequest -Uri ($FrontendUrl + "/healthz") -UseBasicParsing -TimeoutSec 3
    Write-Host "Frontend ($FrontendUrl/healthz): $($FrontendHealth.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "Frontend ($FrontendUrl): FAILED ($($_.Exception.Message))" -ForegroundColor Red
}

try {
    $BackendHealth = Invoke-WebRequest -Uri ($FrontendUrl + "/health") -UseBasicParsing -TimeoutSec 3
    Write-Host "Backend  ($FrontendUrl/health): $($BackendHealth.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "Backend  ($FrontendUrl/health): FAILED ($($_.Exception.Message))" -ForegroundColor Red
}

Write-Host ""
Write-Host "--- Volumes ---"
docker volume ls | Select-String "mulyankan"
