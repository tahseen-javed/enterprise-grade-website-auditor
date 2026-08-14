# Starts the backend as a detached process and waits until it actually
# answers HTTP. Does not require VS Code, and does not hold this window.
#
# The backend serves the built frontend directly (frontend\dist), so this is
# the only process the packaged app needs at runtime - one process, one port.

param(
    [switch]$NoBrowser,
    [switch]$Quiet
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$cfg = Get-ProjectConfig

Write-Host ''
Write-Host '  Advanced Website Auditor' -ForegroundColor White
Write-Host "  $ProjectRoot" -ForegroundColor DarkGray

Write-Head 'Checks'
if (-not (Test-Prerequisites)) { Write-Host ''; exit 1 }
Write-Ok 'Python environment and frontend build found.'

# --- already running? ---------------------------------------------------------
if (Test-ProcessRunning 'backend') {
    $port = Get-EffectivePort 'backend' $cfg.BackendPort
    Write-Ok 'The app is already running for this project.'
    Write-Info "Open it at: http://localhost:$port"
    if (-not $NoBrowser) { Start-Process "http://localhost:$port" | Out-Null }
    Write-Host ''
    exit 0
}

# --- port: use the preferred one, or fall back to a free one -------------------
#
# A port already held by another program no longer stops the app outright.
# The next free port is used for this run instead, and the preference in
# .env is never rewritten - it's only a same-run fallback.
Write-Head 'Port'

function Resolve-ServicePort([string]$name, [string]$label, [int]$preferred) {
    if (-not (Test-PortInUse $preferred)) {
        Write-Ok "Port $preferred is free ($label)."
        return @{ Port = $preferred; Problem = $false }
    }
    # By the time this runs, Test-ProcessRunning has already confirmed (via the
    # PID file) that nothing WE started is tracked as alive - so whatever is
    # listening on $preferred right now is not this run's own process, no
    # matter whose path a live scan's command-line heuristic might resemble.
    # A brand-new process is about to be launched either way, so it always
    # needs a port nothing else is already bound to.
    $owner = Get-PortOwner $preferred
    $who = if ($owner) { "$($owner.Name) (PID $($owner.ProcessId))" } else { 'another program' }
    Write-Warn "Port $preferred ($label) is already in use by $who."
    $fallback = Find-AvailablePort ($preferred + 1) 40
    if ($fallback) {
        Write-Info "  using port $fallback for $label instead, for this run."
        Write-Info "  to make that permanent, set WAE_BACKEND_PORT in .env."
        return @{ Port = $fallback; Problem = $false }
    }
    Write-Err "No free fallback port found near $preferred for $label."
    return @{ Port = $null; Problem = $true }
}

$resolved = Resolve-ServicePort 'backend' 'App' $cfg.BackendPort
if ($resolved.Problem) {
    Write-Info 'Close the program holding the port, or set a different one in .env, and try again.'
    Write-Host ''
    exit 1
}
$port = $resolved.Port

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

# --- launch ---------------------------------------------------------------------
Write-Head 'Starting the app'

$backendOut = Join-Path $LogDir 'backend.out.log'
$backendErr = Join-Path $LogDir 'backend.err.log'
Add-Content -Path $backendOut -Value "`n=== start $stamp ===" -Encoding utf8

# The child process inherits these, so Python's own config (CORS origins, the
# ports shown on System Health) matches the port actually bound - including
# when that differs from .env because of a port fallback above.
$env:WAE_BACKEND_PORT  = "$port"
$env:WAE_BACKEND_HOST  = $cfg.BackendHost

# --app-dir carries the absolute project path, which is what makes this
# process identifiable as ours later (see Get-OwnedProcess). Start-Process
# does not quote arguments itself, and this project's path can contain
# spaces, so the path argument is quoted explicitly.
$backendArgs = @(
    '-m', 'uvicorn', 'app.main:app',
    '--host', $cfg.BackendHost,
    '--port', "$port",
    '--app-dir', ('"' + $BackendDir + '"'),
    '--log-level', 'info'
)

$proc = Start-Process -FilePath $VenvPython -ArgumentList $backendArgs `
    -WorkingDirectory $BackendDir `
    -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr `
    -WindowStyle Hidden -PassThru

Save-ProcessId 'backend' $proc.Id
Save-ProcessPort 'backend' $port
Write-Info "App launched (PID $($proc.Id)), waiting for it to answer..."

if (Wait-ForHttp "http://127.0.0.1:$port/api/health" 45) {
    Write-Ok "Healthy on http://127.0.0.1:$port"
} else {
    Write-Err 'The app did not become healthy in 45 seconds.'
    Write-Info "Check the log: $backendErr"
    if (Test-Path $backendErr) {
        Get-Content $backendErr -Tail 20 | ForEach-Object { Write-Host "           $_" -ForegroundColor DarkRed }
    }
    Write-Host ''
    exit 1
}

Write-Head 'Ready'
Write-Host "  Open the dashboard:  " -NoNewline
Write-Host "http://localhost:$port" -ForegroundColor Cyan
if ($port -ne $cfg.BackendPort) {
    Write-Info "(preferred port $($cfg.BackendPort) was busy - this run is using $port instead)"
}
Write-Info "API documentation:   http://127.0.0.1:$port/api/docs"
Write-Info "Logs:                $LogDir"
Write-Host ''
Write-Info 'The app keeps running after this window closes.'
Write-Info 'Use stop.bat to stop it, or status.bat to check on it.'
Write-Host ''

if (-not $NoBrowser) {
    Start-Sleep -Milliseconds 400
    Start-Process "http://localhost:$port" | Out-Null
}
exit 0
