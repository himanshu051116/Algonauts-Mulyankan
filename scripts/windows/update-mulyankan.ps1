$ErrorActionPreference = "Stop"

$ScriptPath = $PSScriptRoot
. (Join-Path $ScriptPath "common.ps1")
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path -Path $ScriptPath -ChildPath "..\.."))
$StartScript = Join-Path -Path $ScriptPath -ChildPath "start-mulyankan.ps1"
Set-Location -LiteralPath $RepoRoot

Write-Host "=== Mulyankan Update ==="
Write-Host ""
Write-Host "Step 1: Building application images..."
docker compose build frontend backend worker

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Build failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Step 2: Starting updated stack..."
docker compose up -d --remove-orphans

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: docker compose up failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Step 3: Waiting for services..."
Start-Sleep -Seconds 15

for ($i = 0; $i -lt 24; $i++) {
    try {
        $Response = Invoke-WebRequest -Uri ($FrontendUrl + "/healthz") -UseBasicParsing -TimeoutSec 3
        if ($Response.StatusCode -eq 200) {
            Write-Host "Frontend is healthy."
            break
        }
    } catch {}
    Write-Host "  Waiting for frontend..."
    Start-Sleep -Seconds 5
}

for ($i = 0; $i -lt 24; $i++) {
    try {
        $Response = Invoke-WebRequest -Uri ($FrontendUrl + "/health") -UseBasicParsing -TimeoutSec 3
        if ($Response.StatusCode -eq 200) {
            Write-Host "Backend is healthy."
            break
        }
    } catch {}
    Write-Host "  Waiting for backend..."
    Start-Sleep -Seconds 5
}

Write-Host ""
Write-Host "Update complete."
Write-Host "Application URL: $FrontendUrl"
Write-Host ""
Write-Host "Note: All data volumes are preserved (PostgreSQL, MinIO, Redis)."
Write-Host "Run 'status-mulyankan.ps1' to verify all services."
