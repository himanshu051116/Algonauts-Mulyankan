$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path -Path $PSScriptRoot -ChildPath "..\.."))

function Get-MulyankanEnv {
    param([string]$Root = $RepoRoot)
    $values = @{}
    $path = Join-Path $Root ".env"
    if (-not (Test-Path -LiteralPath $path)) { return $values }
    foreach ($line in [System.IO.File]::ReadAllLines($path)) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $parts = $line.Split('=', 2)
        $values[$parts[0].Trim()] = $parts[1].Trim().Trim('"').Trim("'")
    }
    return $values
}

function Get-MulyankanPort {
    param([hashtable]$EnvValues, [string]$Name, [int]$Default)
    $raw = $EnvValues[$Name]
    $parsed = 0
    if ($raw -and [int]::TryParse($raw, [ref]$parsed) -and $parsed -ge 1 -and $parsed -le 65535) { return $parsed }
    return $Default
}

$MulyankanEnv = Get-MulyankanEnv
$FrontendPort = Get-MulyankanPort $MulyankanEnv "FRONTEND_HOST_PORT" 3000
$BackendPort = Get-MulyankanPort $MulyankanEnv "BACKEND_HOST_PORT" 8000
$MinioConsolePort = Get-MulyankanPort $MulyankanEnv "MINIO_CONSOLE_HOST_PORT" 9001
$FrontendUrl = "http://localhost:$FrontendPort"
$BackendUrl = "http://localhost:$BackendPort"
$MinioConsoleUrl = "http://localhost:$MinioConsolePort"
