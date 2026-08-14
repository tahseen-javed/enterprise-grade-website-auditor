# Removes the optional auto-start scheduled task. Leaves the app itself alone.

. (Join-Path $PSScriptRoot 'lib.ps1')

$taskName = 'AdvancedWebsiteAuditor-AutoStart'

Write-Host ''
Write-Host '  Advanced Website Auditor - remove auto-start' -ForegroundColor White
Write-Head 'Result'

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Info "No scheduled task named '$taskName' exists. Nothing to remove."
    Write-Host ''
    exit 0
}

try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Ok "Scheduled task '$taskName' removed."
    Write-Info 'The app is unaffected - start.bat and stop.bat still work as before.'
    Write-Host ''
    exit 0
} catch {
    Write-Err "Could not remove the task: $($_.Exception.Message)"
    Write-Host ''
    exit 1
}
