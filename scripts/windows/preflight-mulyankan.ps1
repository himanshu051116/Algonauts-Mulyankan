$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
Set-Location -LiteralPath $RepoRoot

if (-not (Test-Path -LiteralPath ".env")) { throw ".env is missing. Copy .env.example to .env and configure it first." }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker CLI was not found." }
docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Engine is not running." }

$lock = [System.IO.File]::ReadAllText((Join-Path $RepoRoot "package-lock.json"))
if ($lock -match 'internal\.api\.openai\.org|applied-caas') { throw "package-lock.json contains a non-public package registry." }

$ports = @(
    @{ Name = "Frontend"; Port = $FrontendPort },
    @{ Name = "Backend"; Port = $BackendPort },
    @{ Name = "PostgreSQL"; Port = (Get-MulyankanPort $MulyankanEnv "POSTGRES_HOST_PORT" 5432) },
    @{ Name = "Redis"; Port = (Get-MulyankanPort $MulyankanEnv "REDIS_HOST_PORT" 6379) },
    @{ Name = "MinIO API"; Port = (Get-MulyankanPort $MulyankanEnv "MINIO_API_HOST_PORT" 9000) },
    @{ Name = "MinIO Console"; Port = $MinioConsolePort }
)

$projectName = if ($MulyankanEnv["COMPOSE_PROJECT_NAME"]) { $MulyankanEnv["COMPOSE_PROJECT_NAME"] } else { "" }
foreach ($item in $ports) {
    $listeners = Get-NetTCPConnection -State Listen -LocalPort $item.Port -ErrorAction SilentlyContinue
    if ($listeners) {
        Write-Warning "$($item.Name) host port $($item.Port) is already in use. Confirm it belongs to this Compose project before starting."
    }
}

docker compose config -q
if ($LASTEXITCODE -ne 0) { throw "docker compose configuration validation failed." }
Write-Host "Mulyankan preflight checks passed."
Write-Host "Frontend: $FrontendUrl"
Write-Host "Backend:  $BackendUrl"
Write-Host "MinIO:    $MinioConsoleUrl"
