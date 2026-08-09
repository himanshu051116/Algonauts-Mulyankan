param(
    [switch]$RemoveShortcut
)

$ErrorActionPreference = "Stop"

$TaskName = "Mulyankan Auto Start"

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Scheduled task '$TaskName' removed."
} else {
    Write-Host "No scheduled task named '$TaskName' found."
}

if ($RemoveShortcut) {
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    $ShortcutPath = Join-Path -Path $DesktopPath -ChildPath "Mulyankan.lnk"
    if (Test-Path -LiteralPath $ShortcutPath) {
        Remove-Item -LiteralPath $ShortcutPath -Force
        Write-Host "Desktop shortcut removed."
    } else {
        Write-Host "No desktop shortcut found."
    }
} else {
    Write-Host ""
    Write-Host "Desktop shortcut was not removed. To remove it, run:"
    Write-Host "  .\scripts\windows\uninstall-autostart.ps1 -RemoveShortcut"
}

Write-Host ""
Write-Host "Docker, Mulyankan containers, volumes, and application data are preserved."
Write-Host "To stop the running stack: .\scripts\windows\stop-mulyankan.ps1"
