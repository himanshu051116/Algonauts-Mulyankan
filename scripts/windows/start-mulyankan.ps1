param(
    [switch]$OpenBrowser,
    [switch]$Build,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$ScriptPath = $PSScriptRoot
. (Join-Path $ScriptPath "common.ps1")
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path -Path $ScriptPath -ChildPath "..\.."))
$LogDir = Join-Path -Path $RepoRoot -ChildPath "logs"
$LogFile = Join-Path -Path $LogDir -ChildPath "startup.log"

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Write-Log {
    param([string]$Message)
    $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$Timestamp $Message" | Out-File -FilePath $LogFile -Append
    Write-Host "$Timestamp $Message"
}

Write-Log "Starting Mulyankan from $RepoRoot"

# ---- Step 1: Check Docker Engine ----
$DockerReady = $false
if (docker info 2>&1 | Select-String -Quiet "Server Version") {
    $DockerReady = $true
    Write-Log "Docker Engine is already running."
} else {
    Write-Log "Docker Engine not detected. Starting Docker Desktop..."

    $DockerDesktopPaths = @(
        "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe",
        "$env:LOCALAPPDATA\Docker\Docker Desktop.exe"
    )
    $DockerDesktopExe = $null
    foreach ($p in $DockerDesktopPaths) {
        if (Test-Path -LiteralPath $p) {
            $DockerDesktopExe = $p
            break
        }
    }

    if (-not $DockerDesktopExe) {
        Write-Log "ERROR: Docker Desktop not found. Install Docker Desktop from https://docs.docker.com/desktop/setup/install/windows-install/"
        exit 1
    }

    $Existing = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
    if (-not $Existing) {
        Start-Process -FilePath $DockerDesktopExe
        Write-Log "Docker Desktop launched. Waiting for engine..."
    } else {
        Write-Log "Docker Desktop process already running. Waiting for engine..."
    }

    $PollEnd = [datetime]::UtcNow.AddMinutes(3)
    while ([datetime]::UtcNow -lt $PollEnd) {
        if (docker info 2>&1 | Select-String -Quiet "Server Version") {
            $DockerReady = $true
            Write-Log "Docker Engine is ready."
            break
        }
        Write-Log "  Waiting for Docker Engine..."
        Start-Sleep -Seconds 5
    }
}

if (-not $DockerReady) {
    Write-Log "ERROR: Docker Engine did not become ready within 3 minutes."
    exit 1
}

# ---- Step 2: Change to repo root ----
Set-Location -LiteralPath $RepoRoot

# ---- Step 3: Start Compose stack ----
$ComposeArgs = @("up", "-d", "--remove-orphans")
if ($Build) { $ComposeArgs += "--build" }
Write-Log "Starting Compose stack..."
$ComposeResult = docker compose @ComposeArgs 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Log "ERROR: docker compose up failed: $ComposeResult"
    exit 1
}
Write-Log "Compose stack started."

# ---- Step 4: Wait for health ----
Write-Log "Waiting for frontend health..."
$FrontendHealthy = $false
$PollEnd = [datetime]::UtcNow.AddMinutes(2)
while ([datetime]::UtcNow -lt $PollEnd) {
    try {
        $Response = Invoke-WebRequest -Uri $FrontendUrl -UseBasicParsing -TimeoutSec 3
        if ($Response.StatusCode -eq 200) {
            $FrontendHealthy = $true
            Write-Log "Frontend is healthy."
            break
        }
    } catch {}
    Start-Sleep -Seconds 5
}

if (-not $FrontendHealthy) {
    Write-Log "WARNING: Frontend did not become healthy within 2 minutes. Check docker compose ps and logs."
}

Write-Log "Waiting for backend health..."
$BackendHealthy = $false
$PollEnd = [datetime]::UtcNow.AddMinutes(2)
while ([datetime]::UtcNow -lt $PollEnd) {
    try {
        $Response = Invoke-WebRequest -Uri ($BackendUrl + "/health") -UseBasicParsing -TimeoutSec 3
        if ($Response.StatusCode -eq 200) {
            $BackendHealthy = $true
            Write-Log "Backend is healthy."
            break
        }
    } catch {}
    Start-Sleep -Seconds 5
}

if (-not $BackendHealthy) {
    Write-Log "WARNING: Backend did not become healthy within 2 minutes."
}

# ---- Step 5: Show status ----
Write-Log ""
Write-Log "============================================"
Write-Log " Mulyankan status:"
$PsOutput = docker compose ps 2>&1 | Out-String
Write-Log $PsOutput.Trim()
Write-Log "============================================"
 Write-Log " Application URL: $FrontendUrl"
 if ($BackendHealthy) {
     Write-Log " API docs:       $BackendUrl/docs"
 }
Write-Log " MinIO console:   $MinioConsoleUrl"
Write-Log "============================================"

if ($OpenBrowser -or (-not $NoBrowser)) {
    Start-Process $FrontendUrl
}
