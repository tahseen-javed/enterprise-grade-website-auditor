# Reports whether the app is running, on which port, and whether it responds.

. (Join-Path $PSScriptRoot 'lib.ps1')

$cfg = Get-ProjectConfig
# A running app may be bound to a fallback port start.ps1 chose because the
# preferred one (from .env) was taken - this reflects what's actually live.
$cfg.BackendPort = Get-EffectivePort 'backend' $cfg.BackendPort

Write-Host ''
Write-Host '  Advanced Website Auditor - status' -ForegroundColor White
Write-Host "  $ProjectRoot" -ForegroundColor DarkGray

Write-Head 'App'

function Show-Service([string]$name, [string]$label, [int]$port, [string]$healthUrl) {
    $processId = Read-ProcessId $name
    $proc = if ($processId) { Get-OwnedProcess $processId } else { $null }

    if (-not $processId) {
        Write-Info "$label : not started (no PID file)."
    } elseif (-not $proc) {
        Write-Warn "$label : PID $processId is not a live process of this project (stale PID file)."
    } else {
        $started = try { $proc.CreationDate } catch { $null }
        $uptime = if ($started) { [int]((Get-Date) - $started).TotalMinutes } else { $null }
        $mem = try { [math]::Round($proc.WorkingSetSize / 1MB) } catch { $null }
        $detail = "PID $processId"
        if ($null -ne $uptime) { $detail += ", up $uptime min" }
        if ($null -ne $mem) { $detail += ", $mem MB" }
        Write-Ok "$label : running ($detail)."
    }

    if (Test-PortInUse $port) {
        $owner = Get-PortOwner $port
        if ($owner -and -not $owner.IsOurs) {
            Write-Warn "  port $port is held by $($owner.Name) (PID $($owner.ProcessId)) - not this project."
        } else {
            Write-Info "  port $port listening."
        }
    } else {
        Write-Info "  port $port not listening."
    }

    if ($healthUrl) {
        if (Test-HttpOk $healthUrl 4) {
            Write-Info "  responding: $healthUrl"
        } else {
            Write-Warn "  no HTTP response from $healthUrl"
        }
    }
}

Show-Service 'backend' 'App' $cfg.BackendPort "http://127.0.0.1:$($cfg.BackendPort)/api/health"

if (Read-ProcessId 'frontend') {
    Write-Info ''
    Write-Warn 'A legacy separate frontend process is still tracked from an older version of this app.'
    Write-Info 'Run stop.bat then start.bat to switch it over to the single-process model.'
}

if (-not (Test-Path $FrontendIndex)) {
    Write-Warn 'frontend\dist is missing - run setup.bat to build it.'
}

# ---- backend detail ----------------------------------------------------------
$healthUrl = "http://127.0.0.1:$($cfg.BackendPort)/api/system/health"
try {
    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 12
    Write-Head 'Component health'
    switch ($health.overall) {
        'healthy' { Write-Ok 'Overall: healthy' }
        'warning' { Write-Warn 'Overall: running with warnings' }
        default   { Write-Err "Overall: $($health.overall)" }
    }
    foreach ($prop in $health.components.PSObject.Properties) {
        $c = $prop.Value
        $line = "{0,-20} {1}" -f $prop.Name, $c.detail
        switch ($c.status) {
            'healthy'  { Write-Info $line }
            'warning'  { Write-Warn $line }
            'error'    { Write-Err  $line }
            'disabled' { Write-Info $line }
            default    { Write-Info $line }
        }
    }
} catch {
    Write-Head 'Component health'
    Write-Info 'The app is not reachable, so component health could not be read.'
}

# ---- jobs --------------------------------------------------------------------
try {
    $jobs = Invoke-RestMethod -Uri "http://127.0.0.1:$($cfg.BackendPort)/api/jobs?limit=8" -TimeoutSec 12
    if ($jobs.jobs.Count -gt 0) {
        Write-Head 'Recent jobs'
        foreach ($j in $jobs.jobs) {
            $state = if ($j.is_running) { 'RUNNING' } else { $j.status.ToUpper() }
            $left = $j.counts.pending + $j.counts.failed
            $line = "#{0} {1,-9} {2,5}/{3,-5} {4,5}%  {5}" -f `
                $j.id, $state, $j.processed, $j.total, $j.percent, $j.name
            if ($j.is_running) { Write-Ok $line } else { Write-Info $line }
            if (-not $j.is_running -and $left -gt 0) {
                Write-Info "     $left lead(s) unfinished - resumable from the Jobs page."
            }
        }
    }
} catch {}

Write-Head 'Links'
Write-Info "Dashboard : http://localhost:$($cfg.BackendPort)"
Write-Info "API docs  : http://127.0.0.1:$($cfg.BackendPort)/api/docs"
Write-Info "Logs      : $LogDir"
Write-Host ''
