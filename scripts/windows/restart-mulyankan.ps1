param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"

$ScriptPath = $PSScriptRoot
. (Join-Path $ScriptPath "common.ps1")
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path -Path $ScriptPath -ChildPath "..\.."))
Set-Location -LiteralPath $RepoRoot

Write-Host "Restarting Mulyankan..."
$ComposeArgs = @("up", "-d", "--remove-orphans")
if ($Build) { $ComposeArgs += "--build" }

docker compose @ComposeArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host "Waiting for services to become healthy..."
    Start-Sleep -Seconds 10

    $FrontendHealthy = $false
    for ($i = 0; $i -lt 24; $i++) {
        try {
            $Response = Invoke-WebRequest -Uri ($FrontendUrl + "/healthz") -UseBasicParsing -TimeoutSec 3
            if ($Response.StatusCode -eq 200) {
                $FrontendHealthy = $true
                break
            }
        } catch {}
        Start-Sleep -Seconds 5
    }

    if ($FrontendHealthy) {
        Write-Host "Mulyankan is running at $FrontendUrl"
    } else {
        Write-Host "WARNING: Frontend did not become healthy. Check 'docker compose ps' and 'status-mulyankan.ps1'"
    }
} else {
    Write-Host "ERROR: Restart failed with exit code $LASTEXITCODE"
    exit 1
}
