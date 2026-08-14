# Optional: start the app automatically when you log in to Windows.
#
# Spec 38 - nothing here runs on its own. Task Scheduler is only touched when
# you deliberately run this script, and it asks for confirmation first unless
# you pass -Force. Remove it any time with uninstall-autostart.ps1.

param(
    [switch]$Force,
    [int]$DelaySeconds = 25
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$taskName = 'AdvancedWebsiteAuditor-AutoStart'
$startScript = Join-Path $PSScriptRoot 'start.ps1'

Write-Host ''
Write-Host '  Advanced Website Auditor - install auto-start' -ForegroundColor White

Write-Head 'What this will do'
Write-Info "Create a Windows scheduled task named: $taskName"
Write-Info "It runs, as you ($env:USERNAME), at log on:"
Write-Info "  powershell -File `"$startScript`" -NoBrowser"
Write-Info "Delayed by $DelaySeconds seconds so the network is up first."
Write-Info 'Nothing else on your system is modified.'

if (-not (Test-Path $startScript)) {
    Write-Err "start.ps1 not found at $startScript"
    Write-Host ''
    exit 1
}

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Warn 'That task already exists and will be replaced.'
}

if (-not $Force) {
    Write-Host ''
    $answer = Read-Host '  Create this scheduled task? (yes/no)'
    if ($answer -notmatch '^(y|yes)$') {
        Write-Host ''
        Write-Info 'Cancelled. Nothing was changed.'
        Write-Host ''
        exit 0
    }
}

try {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`" -NoBrowser" `
        -WorkingDirectory $ProjectRoot

    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $trigger.Delay = "PT$($DelaySeconds)S"

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew

    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal `
        -Description 'Starts the Advanced Website Auditor (backend + dashboard) at log on.' `
        -Force | Out-Null

    Write-Head 'Done'
    Write-Ok "Scheduled task '$taskName' created."
    Write-Info 'It will start the app the next time you log in.'
    Write-Info 'Remove it with: powershell -File scripts\uninstall-autostart.ps1'
    Write-Host ''
    exit 0
} catch {
    Write-Err "Could not create the scheduled task: $($_.Exception.Message)"
    Write-Info 'If this is a permissions error, run the script from an elevated PowerShell window.'
    Write-Host ''
    exit 1
}
