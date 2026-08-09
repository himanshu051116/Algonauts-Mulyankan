param(
    [switch]$DesktopShortcut,
    [switch]$NoDesktopShortcut
)

$ErrorActionPreference = "Stop"

$ScriptPath = $PSScriptRoot
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path -Path $ScriptPath -ChildPath "..\.."))
$StartScriptPath = Join-Path -Path $ScriptPath -ChildPath "start-mulyankan.ps1"

$TaskName = "Mulyankan Auto Start"
$TaskDescription = "Starts the Mulyankan local application stack on Windows logon"

# --- Scheduled Task ---
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument @"
-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "$StartScriptPath" -NoBrowser
"@

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Trigger.Delay = "PT1M"

$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($Existing) {
    Write-Host "Updating existing scheduled task '$TaskName'..."
    Set-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal
} else {
    Write-Host "Creating scheduled task '$TaskName'..."
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description $TaskDescription
}

Write-Host "Scheduled task '$TaskName' installed."
Write-Host "  Trigger: At logon of $env:USERNAME (with 1 minute delay)"
Write-Host "  Action: powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$StartScriptPath`" -NoBrowser"
Write-Host ""

# --- Desktop Shortcut ---
$CreateShortcut = $DesktopShortcut
if (-not $DesktopShortcut -and -not $NoDesktopShortcut) {
    $Response = Read-Host "Create a desktop shortcut for Mulyankan? (Y/n)"
    $CreateShortcut = $Response -ne "n" -and $Response -ne "N"
}

if ($CreateShortcut) {
    $OpenScriptPath = Join-Path -Path $ScriptPath -ChildPath "open-mulyankan.ps1"
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    $ShortcutPath = Join-Path -Path $DesktopPath -ChildPath "Mulyankan.lnk"

    $WScriptShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WScriptShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = "powershell.exe"
    $Shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$OpenScriptPath`""
    $Shortcut.Description = "Open Mulyankan proposal scrutiny system"
    $Shortcut.WorkingDirectory = $RepoRoot
    $Shortcut.Save()

    Write-Host "Desktop shortcut created: $ShortcutPath"
    Write-Host "  Double-click to open Mulyankan at http://localhost:3000"
}

Write-Host ""
Write-Host "Installation complete."
Write-Host ""
Write-Host "To verify:"
Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | fl"
Write-Host ""
Write-Host "To remove:"
Write-Host "  .\scripts\windows\uninstall-autostart.ps1"
Write-Host ""
Write-Host "Note: Docker Desktop should also be configured to start at login."
Write-Host "  Docker Desktop → Settings → General → 'Start Docker Desktop when you sign in'"
