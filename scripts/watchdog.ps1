# =============================================================================
# Crash recovery supervisor.
#
# Runs detached in the background after the app starts. Every few seconds it
# confirms the app process is still alive AND still answering HTTP. If it has
# died, the watchdog restarts it and records why in data\logs\watchdog.log.
#
# Deliberate conservatism:
#   - It only ever restarts a process it can verify belongs to THIS project
#     (Get-OwnedProcess), so it can never resurrect or interfere with another
#     application on the machine.
#   - A clean stop through stop.bat removes the PID file, which the watchdog
#     reads as "the user wanted this off" and exits instead of fighting them.
#   - Restarts are rate limited. A crash loop stops after a few attempts and
#     leaves a clear explanation rather than hammering the machine forever.
# =============================================================================

param(
    [Parameter(Mandatory = $true)][int]$Port,
    [int]$IntervalSeconds = 10,
    [int]$MaxRestarts = 5,
    [int]$WindowMinutes = 10
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$logFile = Join-Path $LogDir 'watchdog.log'

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    try { Add-Content -Path $logFile -Value $line -Encoding utf8 } catch {}
}

# Only one supervisor per project copy.
$selfPidFile = Join-Path $RunDir 'watchdog.pid'
$existing = Read-ProcessId 'watchdog'
if ($existing -and (Get-OwnedProcess $existing) -and $existing -ne $PID) {
    Write-Log "Another watchdog (PID $existing) is already running - exiting."
    exit 0
}
Save-ProcessId 'watchdog' $PID

Write-Log "Watchdog started (PID $PID), supervising port $Port every ${IntervalSeconds}s."

$restartTimes = @()
$healthUrl = "http://127.0.0.1:$Port/api/health"

try {
    while ($true) {
        Start-Sleep -Seconds $IntervalSeconds

        # The user stopped the app on purpose - stand down.
        $trackedPid = Read-ProcessId 'backend'
        if (-not $trackedPid) {
            Write-Log 'No backend PID recorded (clean stop). Watchdog exiting.'
            break
        }

        $alive = $null -ne (Get-OwnedProcess $trackedPid)
        $healthy = $false
        if ($alive) {
            # A live but wedged process is still a failure from the user's point
            # of view, so health is checked too - with a generous retry, because
            # a long audit can briefly make the API slow to answer.
            $healthy = Test-HttpOk $healthUrl 5
            if (-not $healthy) {
                Start-Sleep -Seconds 5
                $healthy = Test-HttpOk $healthUrl 8
            }
        }

        if ($alive -and $healthy) { continue }

        $reason = if (-not $alive) { "process $trackedPid is gone" } else { "process $trackedPid stopped answering $healthUrl" }
        Write-Log "PROBLEM: $reason."

        # Rate limit.
        $cutoff = (Get-Date).AddMinutes(-$WindowMinutes)
        $restartTimes = @($restartTimes | Where-Object { $_ -gt $cutoff })
        if ($restartTimes.Count -ge $MaxRestarts) {
            Write-Log "Giving up: $MaxRestarts restarts already attempted in the last $WindowMinutes minutes."
            Write-Log 'Something is wrong that restarting cannot fix. See backend.err.log.'
            break
        }

        # If it is wedged rather than dead, clear it out before relaunching so
        # the port is free and we never leave two copies behind.
        if ($alive) {
            Write-Log 'Stopping the unresponsive process before restarting it.'
            Stop-OwnedProcess 'backend' 'App' | Out-Null
        } else {
            Remove-ProcessIdFile 'backend'
            Remove-PortFile 'backend'
        }

        $restartTimes += (Get-Date)
        Write-Log "Restarting (attempt $($restartTimes.Count) of $MaxRestarts in this window)..."

        # -NoBrowser: a recovery restart must not steal focus by opening tabs.
        # -NoWatchdog: this supervisor keeps running; do not spawn another.
        & (Join-Path $PSScriptRoot 'start.ps1') -NoBrowser -NoWatchdog -Quiet 2>&1 |
            ForEach-Object { Write-Log "  start: $_" }

        if (Wait-ForHttp $healthUrl 45) {
            $newPid = Read-ProcessId 'backend'
            Write-Log "Recovered. App is answering again (PID $newPid)."
        } else {
            Write-Log 'Restart did not become healthy within 45s; will assess again next cycle.'
        }
    }
} finally {
    if ((Read-ProcessId 'watchdog') -eq $PID) { Remove-ProcessIdFile 'watchdog' }
    Write-Log "Watchdog (PID $PID) exiting."
}
