# Registers a Windows Task Scheduler job that runs a headless daily check for
# new RouterOS releases (equivalent to `watch --once`), so new firmware is
# picked up automatically without the GUI ever being open.
#
# Usage (run as Administrator):
#   .\install_daily_task.ps1 -ArchiveDir "D:\mikrotik_archive" -Time "03:00"
#
# Uses the built exe if present (dist\mikrotik-grabber.exe), otherwise falls
# back to `python run.py` from the repo, so this also works straight from a
# source checkout without building first.

param(
    [string]$ArchiveDir = "$PSScriptRoot\..\..\mikrotik_archive",
    [string]$Time = "03:00",
    [string]$TaskName = "MikroTikCdnGrabber-DailyWatch"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$exePath = Join-Path $repoRoot "dist\mikrotik-grabber.exe"

if (Test-Path $exePath) {
    $action = New-ScheduledTaskAction -Execute $exePath -Argument "watch --once --output `"$ArchiveDir`""
} else {
    $python = (Get-Command python).Source
    $runPy = Join-Path $repoRoot "run.py"
    $action = New-ScheduledTaskAction -Execute $python -Argument "`"$runPy`" watch --once --output `"$ArchiveDir`"" -WorkingDirectory $repoRoot
}

$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Daily check for new MikroTik RouterOS releases" -Force

Write-Host "Installed scheduled task '$TaskName', running daily at $Time against $ArchiveDir"
Write-Host "Inspect with: Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "Remove with:  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
