param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$ScriptPath = $PSScriptRoot
. (Join-Path $ScriptPath "common.ps1")
$StartScript = Join-Path -Path $ScriptPath -ChildPath "start-mulyankan.ps1"

function Test-Health {
    try {
        $Response = Invoke-WebRequest -Uri ($FrontendUrl + "/healthz") -UseBasicParsing -TimeoutSec 3
        return $Response.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (-not (Test-Health)) {
    Write-Host "Mulyankan is not running. Starting the stack..."
    if ($NoBrowser) {
        & $StartScript -NoBrowser
    } else {
        & $StartScript -OpenBrowser
    }
} else {
    Write-Host "Mulyankan is already running."
    Write-Host "Opening $FrontendUrl"
    if (-not $NoBrowser) {
        Start-Process $FrontendUrl
    }
}
