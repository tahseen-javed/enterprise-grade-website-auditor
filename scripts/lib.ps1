# =============================================================================
# Shared helpers for the launcher scripts.
#
# PROCESS SAFETY (spec 37) - this is the important part of this file.
# A recorded PID is NEVER trusted on its own, and a process is NEVER matched by
# a generic name like python.exe / node.exe / uvicorn / vite. Before this script
# will stop anything, it confirms the live process's executable path or command
# line contains THIS project's directory. If that check fails, the PID is
# treated as stale and left completely alone, so other projects running their
# own Python or Node servers can never be touched.
# =============================================================================

$ErrorActionPreference = 'Stop'

$script:ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:BackendDir  = Join-Path $script:ProjectRoot 'backend'
$script:FrontendDir = Join-Path $script:ProjectRoot 'frontend'
$script:DataDir     = Join-Path $script:ProjectRoot 'data'
$script:RunDir      = Join-Path $script:DataDir 'run'
$script:LogDir      = Join-Path $script:DataDir 'logs'

$script:VenvPython    = Join-Path $script:BackendDir '.venv\Scripts\python.exe'
$script:ViteBin       = Join-Path $script:FrontendDir 'node_modules\vite\bin\vite.js'
$script:FrontendDist  = Join-Path $script:FrontendDir 'dist'
$script:FrontendIndex = Join-Path $script:FrontendDist 'index.html'

foreach ($d in @($script:DataDir, $script:RunDir, $script:LogDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}

# ---- configuration -----------------------------------------------------------

function Get-ProjectConfig {
    $cfg = @{ BackendPort = 8001; FrontendPort = 5174; BackendHost = '127.0.0.1' }

    $envFile = Join-Path $script:ProjectRoot '.env'
    if (Test-Path $envFile) {
        foreach ($line in (Get-Content $envFile)) {
            if ($line -match '^\s*#') { continue }
            if ($line -match '^\s*([A-Za-z0-9_]+)\s*=\s*(.+?)\s*$') {
                $key = $Matches[1]; $val = $Matches[2].Trim('"').Trim("'")
                switch ($key) {
                    'WAE_BACKEND_PORT'  { $cfg.BackendPort = [int]$val }
                    'WAE_FRONTEND_PORT' { $cfg.FrontendPort = [int]$val }
                    'WAE_BACKEND_HOST'  { $cfg.BackendHost = $val }
                }
            }
        }
    }
    if ($env:WAE_BACKEND_PORT)  { $cfg.BackendPort  = [int]$env:WAE_BACKEND_PORT }
    if ($env:WAE_FRONTEND_PORT) { $cfg.FrontendPort = [int]$env:WAE_FRONTEND_PORT }
    return $cfg
}

# ---- output ------------------------------------------------------------------

function Write-Head($text) {
    Write-Host ''
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host "  $('-' * $text.Length)" -ForegroundColor DarkGray
}
function Write-Ok($t)    { Write-Host "  [ OK ]   $t" -ForegroundColor Green }
function Write-Warn($t)  { Write-Host "  [WARN]   $t" -ForegroundColor Yellow }
function Write-Err($t)   { Write-Host "  [FAIL]   $t" -ForegroundColor Red }
function Write-Info($t)  { Write-Host "           $t" -ForegroundColor Gray }

# ---- pid files ---------------------------------------------------------------

function Get-PidFile([string]$name) { Join-Path $script:RunDir "$name.pid" }

function Save-ProcessId([string]$name, [int]$processId) {
    Set-Content -Path (Get-PidFile $name) -Value $processId -Encoding ascii
}

function Remove-ProcessIdFile([string]$name) {
    $f = Get-PidFile $name
    if (Test-Path $f) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
}

function Read-ProcessId([string]$name) {
    $f = Get-PidFile $name
    if (-not (Test-Path $f)) { return $null }
    $raw = (Get-Content $f -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($raw -match '^\d+$') { return [int]$raw }
    return $null
}

# ---- port files ----------------------------------------------------------
#
# The .env file holds the *preferred* ports. What a running process actually
# bound to (which can differ, if start.ps1 had to fall back because the
# preferred port was taken by something else) is recorded here, alongside the
# PID file, so status.ps1 / stop.ps1 stay accurate without guessing.

function Get-PortFile([string]$name) { Join-Path $script:RunDir "$name.port" }

function Save-ProcessPort([string]$name, [int]$port) {
    Set-Content -Path (Get-PortFile $name) -Value $port -Encoding ascii
}

function Remove-PortFile([string]$name) {
    $f = Get-PortFile $name
    if (Test-Path $f) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
}

function Read-ProcessPort([string]$name) {
    $f = Get-PortFile $name
    if (-not (Test-Path $f)) { return $null }
    $raw = (Get-Content $f -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($raw -match '^\d+$') { return [int]$raw }
    return $null
}

<#
The port a live, owned service is actually bound to, or the configured
default when nothing of ours is currently running. This is what status.ps1
and stop.ps1 read, so they report correctly even after start.ps1 fell back
to a non-default port.
#>
function Get-EffectivePort([string]$name, [int]$configuredDefault) {
    if (Test-ProcessRunning $name) {
        $p = Read-ProcessPort $name
        if ($p) { return $p }
    }
    return $configuredDefault
}

<#
Scans forward from $preferred for a port nothing is listening on. Used only
as a same-run fallback when the configured port is already held by a
program outside this project - never persisted to .env, so the preference
in .env is not silently overwritten.
#>
function Find-AvailablePort([int]$preferred, [int]$span = 20) {
    for ($p = $preferred; $p -lt ($preferred + $span); $p++) {
        if (-not (Test-PortInUse $p)) { return $p }
    }
    return $null
}

# ---- THE ownership check -----------------------------------------------------

<#
Returns the live process only if it verifiably belongs to this project.
Everything else - missing process, reused PID, a different project's server -
returns $null, which callers treat as "nothing of mine is running".
#>
function Get-OwnedProcess([int]$processId) {
    if (-not $processId) { return $null }

    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    if (-not $proc) { return $null }

    $root = $script:ProjectRoot
    $exe = [string]$proc.ExecutablePath
    $cmd = [string]$proc.CommandLine

    # Either the binary itself lives inside this project (the backend venv), or
    # the command line names this project's directory (the frontend's vite.js).
    $ownedByExe = $exe -and $exe.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)
    $ownedByCmd = $cmd -and $cmd.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0

    if ($ownedByExe -or $ownedByCmd) { return $proc }
    return $null
}

function Test-ProcessRunning([string]$name) {
    $processId = Read-ProcessId $name
    if (-not $processId) { return $false }
    return $null -ne (Get-OwnedProcess $processId)
}

# ---- ports -------------------------------------------------------------------

function Test-PortInUse([int]$port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync('127.0.0.1', $port)
        if ($task.Wait(400)) { return $true }
        return $false
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

<#
Identifies who holds a port, and whether it is ours. Used to give an honest
message instead of blindly killing whatever is listening.
#>
function Get-PortOwner([int]$port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
                Select-Object -First 1
    } catch {
        return $null
    }
    if (-not $conn) { return $null }

    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
    if (-not $proc) { return @{ ProcessId = $conn.OwningProcess; Name = 'unknown'; IsOurs = $false } }

    return @{
        ProcessId = [int]$proc.ProcessId
        Name      = [string]$proc.Name
        Command   = [string]$proc.CommandLine
        IsOurs    = ($null -ne (Get-OwnedProcess ([int]$proc.ProcessId)))
    }
}

# ---- http --------------------------------------------------------------------

function Test-HttpOk([string]$url, [int]$timeoutSec = 3) {
    try {
        $r = Invoke-WebRequest -Uri $url -TimeoutSec $timeoutSec -UseBasicParsing
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
    } catch {
        return $false
    }
}

function Wait-ForHttp([string]$url, [int]$timeoutSec = 45) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpOk $url 2) { return $true }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

# ---- stopping ----------------------------------------------------------------

<#
Stops a recorded process, but only after Get-OwnedProcess confirms it is ours.
Children are stopped first (vite spawns workers), then the process itself,
politely before forcefully.
#>
function Stop-OwnedProcess([string]$name, [string]$label) {
    $processId = Read-ProcessId $name
    if (-not $processId) {
        Write-Info "$label was not running (no PID recorded)."
        return $true
    }

    $proc = Get-OwnedProcess $processId
    if (-not $proc) {
        Write-Warn "$label PID $processId is stale or belongs to another program - not touching it."
        Write-Info 'Only processes verified as part of this project are ever stopped.'
        Remove-ProcessIdFile $name
        Remove-PortFile $name
        return $true
    }

    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$processId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        try { Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
    }

    try {
        Stop-Process -Id $processId -ErrorAction Stop
    } catch {
        try { Stop-Process -Id $processId -Force -ErrorAction Stop } catch {}
    }

    for ($i = 0; $i -lt 20; $i++) {
        if (-not (Get-OwnedProcess $processId)) { break }
        Start-Sleep -Milliseconds 250
    }

    if (Get-OwnedProcess $processId) {
        try { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue } catch {}
        Start-Sleep -Milliseconds 500
    }

    if (Get-OwnedProcess $processId) {
        Write-Err "$label (PID $processId) would not stop."
        return $false
    }

    Write-Ok "$label stopped (PID $processId)."
    Remove-ProcessIdFile $name
    Remove-PortFile $name
    return $true
}

# ---- prerequisites -----------------------------------------------------------

<#
The packaged app is a single process: the backend serves the built frontend
(frontend\dist), so only the Python venv and that build are required to run
it. Node.js/npm are only needed again if setup.bat is re-run (e.g. after
pulling frontend source changes) - never at start.ps1 time.
#>
function Test-Prerequisites {
    $ok = $true
    if (-not (Test-Path $script:VenvPython)) {
        Write-Err 'Python environment missing: backend\.venv'
        Write-Info 'Run setup.bat once to create it.'
        $ok = $false
    }
    if (-not (Test-Path $script:FrontendIndex)) {
        Write-Err 'Frontend build missing: frontend\dist'
        Write-Info 'Run setup.bat once to build it.'
        $ok = $false
    }
    return $ok
}
