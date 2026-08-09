$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
Set-Location -LiteralPath $RepoRoot

Write-Host "Applying MinIO server-level CORS and ensuring the storage bucket exists..."

docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Compose configuration is invalid." }

docker compose up -d --no-deps --force-recreate minio
if ($LASTEXITCODE -ne 0) { throw "MinIO recreation failed." }

$ready = $false
for ($i = 0; $i -lt 36; $i++) {
    docker compose exec -T minio mc ready local 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $ready) { throw "MinIO did not become healthy." }

docker compose up --no-deps minio-init
if ($LASTEXITCODE -ne 0) { throw "MinIO bucket initialization failed." }

Write-Host "MinIO server-level CORS and bucket initialization completed successfully."
Write-Host "No bucket-level PutBucketCors call was used."
