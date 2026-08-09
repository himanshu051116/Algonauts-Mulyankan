$ErrorActionPreference = "Stop"

$ScriptPath = $PSScriptRoot
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path -Path $ScriptPath -ChildPath "..\.."))
Set-Location -LiteralPath $RepoRoot

Write-Host "Stopping Mulyankan services (preserving containers and volumes)..."
docker compose stop

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Mulyankan stopped."
    Write-Host "All service data (PostgreSQL, MinIO, Redis) is preserved."
    Write-Host "Run 'start-mulyankan.ps1' to resume, or restart your computer for auto-start."
} else {
    Write-Host "WARNING: docker compose stop completed with exit code $LASTEXITCODE"
}
