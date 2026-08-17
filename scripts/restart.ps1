# Stops this project's services, then starts them again.
#
# -Watchdog is passed through so a restart keeps the same crash-recovery
# behaviour START.bat sets up. Without it, restart.bat would quietly leave the
# app unsupervised - working, but no longer self-healing.

param(
    [switch]$NoBrowser,
    [switch]$NoWatchdog   # restart without crash recovery, if that is deliberately wanted
)

$here = $PSScriptRoot

& (Join-Path $here 'stop.ps1')

Start-Sleep -Seconds 2

# Explicit -Switch:$bool binding rather than splatting an array of strings:
# array splatting does not reliably bind switch parameters, which silently
# dropped -Watchdog and left the app running without crash recovery.
& (Join-Path $here 'start.ps1') -NoBrowser:$NoBrowser -Watchdog:(-not $NoWatchdog)
exit $LASTEXITCODE
