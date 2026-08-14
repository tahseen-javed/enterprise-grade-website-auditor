# Stops only this project's app process.
#
# The PID is stopped strictly after Get-OwnedProcess confirms it belongs to
# this project directory. An unverified PID is reported and left running, so
# another project's python.exe is never affected.

. (Join-Path $PSScriptRoot 'lib.ps1')

$cfg = Get-ProjectConfig
# Captured before stopping - once the process is gone, Get-EffectivePort can
# no longer tell a fallback port apart from the .env default.
$cfg.BackendPort = Get-EffectivePort 'backend' $cfg.BackendPort

Write-Head 'Stopping this project'

$ok = Stop-OwnedProcess 'backend' 'App'

# Compatibility cleanup: earlier versions ran the frontend as its own Vite
# dev-server process, tracked under the 'frontend' name. The backend now
# serves the built frontend itself, so nothing starts that process anymore -
# but if one is still running from before this change, stop it too rather
# than leaving it orphaned.
if (Read-ProcessId 'frontend') {
    Stop-OwnedProcess 'frontend' 'Frontend (legacy dev server)' | Out-Null
}

Write-Head 'Port'
if (-not (Test-PortInUse $cfg.BackendPort)) {
    Write-Ok "Port $($cfg.BackendPort) released."
} else {
    $owner = Get-PortOwner $cfg.BackendPort
    if ($owner -and $owner.IsOurs) {
        Write-Warn "Port $($cfg.BackendPort) is still held by a process from this project (PID $($owner.ProcessId))."
        Write-Info 'Run status.bat, or stop.bat again in a moment.'
    } else {
        $who = if ($owner) { "$($owner.Name) (PID $($owner.ProcessId))" } else { 'another program' }
        Write-Info "Port $($cfg.BackendPort) is in use by $who, which is not part of this project - left alone."
    }
}

Write-Host ''
if ($ok) {
    Write-Ok 'Done. Any running job was checkpointed and can be resumed from the Jobs page.'
    Write-Host ''
    exit 0
}
Write-Err 'The app could not be stopped. Run status.bat for details.'
Write-Host ''
exit 1
