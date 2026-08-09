<#
.SYNOPSIS
  Create timestamped backups of PostgreSQL and MinIO data.
.DESCRIPTION
  Runs pg_dump inside the postgres container and copies to a timestamped
  directory under BACKUP_DIR (default: ../backups relative to the project).
  MinIO objects should be backed up via mc mirror.
  Backups do not stop running containers.
#>
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent -LiteralPath $PSCommandPath
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$BackupRoot = Join-Path $ProjectRoot "backups"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupDir = Join-Path $BackupRoot $Timestamp
$null = New-Item -ItemType Directory -Path $BackupDir -Force

Write-Host "=== Mulyankan Backup [$Timestamp] ===" -ForegroundColor Cyan

# 1. PostgreSQL logical backup
Write-Host "Backing up PostgreSQL..." -ForegroundColor Yellow
$PGUser = docker compose exec -T postgres printenv POSTGRES_USER 2>$null
if (-not $PGUser) { $PGUser = "mulyankan" }
$BackupFile = Join-Path $BackupDir "mulyankan-pg.sql"
docker compose exec -T postgres pg_dump -U $PGUser --clean --if-exists --no-owner mulyankan > $BackupFile 2>&1
if ($LASTEXITCODE -eq 0) {
    $size = (Get-Item $BackupFile).Length
    Write-Host "  PostgreSQL backup: $BackupFile ($($size / 1KB -as [int]) KB)" -ForegroundColor Green
} else {
    Write-Host "  PostgreSQL backup FAILED" -ForegroundColor Red
}

# 2. MinIO object listing (reference backup)
Write-Host "Listing MinIO objects..." -ForegroundColor Yellow
$MinioList = Join-Path $BackupDir "minio-objects.txt"
docker compose exec -T minio mc ls --recursive local/mulyankan-proposals 2>$null | Out-File -FilePath $MinioList -Encoding utf8
if ($LASTEXITCODE -eq 0) {
    $lines = (Get-Content $MinioList | Measure-Object -Line).Lines
    Write-Host "  MinIO object list: $MinioList ($lines objects)" -ForegroundColor Green
} else {
    Write-Host "  MinIO listing skipped (minio-init may not have created alias)" -ForegroundColor Yellow
}

# 3. Compose file backup (configuration snapshot)
Copy-Item (Join-Path $ProjectRoot "docker-compose.yml") (Join-Path $BackupDir "docker-compose.yml")
Copy-Item (Join-Path $ProjectRoot ".env") (Join-Path $BackupDir ".env-backup.txt")
Write-Host "  Configuration backed up" -ForegroundColor Green

Write-Host "Backup complete: $BackupDir" -ForegroundColor Cyan
