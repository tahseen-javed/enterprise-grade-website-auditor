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
    # Fallbacks only - used when there is no .env yet (a freshly copied project).
    # Ensure-EnvFile creates one from .env.example on first run, and start.ps1
    # falls back to the next free port anyway if these are taken.
    $cfg = @{ BackendPort = 8021; FrontendPort = 5185; BackendHost = '127.0.0.1' }

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
function Stop-OwnedProcess {
    param(
        [string]$name,
        [string]$label,
        # The watchdog launches the app as its own child. Killing its children
        # would force-kill the app before we get the chance to stop it politely,
        # losing the clean shutdown that checkpoints a running audit.
        [switch]$SkipChildren
    )

    $processId = Read-ProcessId $name
    if (-not $processId) {
        Write-Info "$label was not running (no PID recorded)."
        return $true
    }

    $proc = Get-OwnedProcess $processId
    if (-not $proc) {
        # Distinguish "already gone" from "alive but not ours". Reporting an
        # exited process as if it belonged to another program is alarming and
        # simply untrue.
        $stillAlive = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
        if ($stillAlive) {
            Write-Warn "$label PID $processId belongs to another program - not touching it."
            Write-Info 'Only processes verified as part of this project are ever stopped.'
        } else {
            Write-Info "$label had already stopped."
        }
        Remove-ProcessIdFile $name
        Remove-PortFile $name
        return $true
    }

    if (-not $SkipChildren) {
        $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$processId" -ErrorAction SilentlyContinue)
        foreach ($child in $children) {
            try { Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
        }
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

# =============================================================================
# FIRST-RUN BOOTSTRAP SUPPORT
#
# Everything below exists so a non-technical user can double-click one file on
# a machine that has never seen this project. It discovers the runtimes, can
# install them from official sources when they are genuinely absent, and
# records fingerprints of the dependency manifests so a second launch skips
# straight to starting the app instead of reinstalling anything.
#
# Nothing here ever deletes user data. Setup only ever creates what is missing.
# =============================================================================

# ---- environment file --------------------------------------------------------

<#
.env is deliberately git-ignored (it is machine configuration), so a freshly
cloned or unzipped copy will not have one. Create it from .env.example so the
project has an explicit, editable port configuration on every machine.
Never overwrites an existing .env.
#>
function Ensure-EnvFile {
    $envFile = Join-Path $script:ProjectRoot '.env'
    if (Test-Path $envFile) { return @{ Created = $false; Path = $envFile } }

    $example = Join-Path $script:ProjectRoot '.env.example'
    if (Test-Path $example) {
        Copy-Item $example $envFile -Force
    } else {
        @(
            '# Created automatically on first run.',
            'WAE_BACKEND_PORT=8021',
            'WAE_BACKEND_HOST=127.0.0.1',
            'WAE_FRONTEND_PORT=5185'
        ) | Set-Content -Path $envFile -Encoding utf8
    }
    return @{ Created = $true; Path = $envFile }
}

<#
Validates the resolved configuration and returns a list of human-readable
problems (empty when everything is usable). Bad values are a setup error the
user can act on, not something to fail silently on later.
#>
function Test-ProjectConfig($cfg) {
    $problems = @()
    foreach ($pair in @(@{n = 'WAE_BACKEND_PORT'; v = $cfg.BackendPort })) {
        $p = $pair.v
        if ($null -eq $p -or $p -lt 1 -or $p -gt 65535) {
            $problems += "$($pair.n) is '$p', which is not a valid TCP port (1-65535). Edit .env."
        } elseif ($p -lt 1024) {
            $problems += "$($pair.n) is $p. Ports below 1024 usually need administrator rights. Use something like 8021."
        }
    }
    if ($cfg.BackendHost -notin @('127.0.0.1', 'localhost', '0.0.0.0')) {
        $problems += "WAE_BACKEND_HOST is '$($cfg.BackendHost)'. Use 127.0.0.1 unless you deliberately want to expose the app on the network."
    }
    return $problems
}

# ---- PATH refresh ------------------------------------------------------------

<#
A runtime installed during this session is on disk but not in this process's
PATH, because PATH is only inherited at process start. Re-read it from the
registry so the very same run can use what it just installed, with no reboot
and no "close and reopen the window" instruction to the user.
#>
function Update-SessionPath {
    try {
        $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
        $merged  = @($machine, $user) | Where-Object { $_ }
        $env:Path = ($merged -join ';')
        return $true
    } catch {
        return $false
    }
}

# ---- runtime discovery -------------------------------------------------------

<#
Finds a usable Python 3.10+ without assuming any particular install location.
Search order: the launcher (py), PATH, then the standard per-user and
machine-wide install directories. Returns the interpreter path, or $null.
#>
function Find-PythonExe {
    $candidates = @()

    foreach ($name in @('py', 'python', 'python3')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { $candidates += $cmd.Source }
    }

    # Standard install roots, resolved from environment variables rather than
    # hardcoded drive letters or user names.
    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        (Join-Path $env:ProgramFiles 'Python'),
        ${env:ProgramFiles(x86)}
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($root in $roots) {
        Get-ChildItem -Path $root -Filter 'Python3*' -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | ForEach-Object {
                $exe = Join-Path $_.FullName 'python.exe'
                if (Test-Path $exe) { $candidates += $exe }
            }
    }

    foreach ($exe in ($candidates | Select-Object -Unique)) {
        try {
            # 'py' without arguments can launch the newest installed version;
            # asking for the version string is the reliable capability probe.
            $ver = & $exe --version 2>&1
            if ($ver -match 'Python (\d+)\.(\d+)') {
                $maj = [int]$Matches[1]; $min = [int]$Matches[2]
                if ($maj -eq 3 -and $min -ge 10) {
                    return @{ Path = $exe; Version = "$maj.$min" }
                }
            }
        } catch { continue }
    }
    return $null
}

<#
Finds Node.js 18+ the same way - PATH first, then the standard install
directory. npm is resolved next to the node binary so a shell alias or a
half-configured PATH cannot pick a mismatched pair.
#>
function Find-NodeExe {
    $candidates = @()
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $candidates += $cmd.Source }

    foreach ($root in @((Join-Path $env:ProgramFiles 'nodejs'), (Join-Path ${env:ProgramFiles(x86)} 'nodejs'), (Join-Path $env:LOCALAPPDATA 'Programs\nodejs'))) {
        if ($root -and (Test-Path $root)) {
            $exe = Join-Path $root 'node.exe'
            if (Test-Path $exe) { $candidates += $exe }
        }
    }

    foreach ($exe in ($candidates | Select-Object -Unique)) {
        try {
            $ver = & $exe --version 2>&1
            if ($ver -match 'v(\d+)\.') {
                $maj = [int]$Matches[1]
                if ($maj -ge 18) {
                    $npm = Join-Path (Split-Path $exe -Parent) 'npm.cmd'
                    if (-not (Test-Path $npm)) {
                        $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
                        $npm = if ($npmCmd) { $npmCmd.Source } else { $null }
                    }
                    return @{ Path = $exe; Npm = $npm; Version = "$ver" }
                }
            }
        } catch { continue }
    }
    return $null
}

# ---- runtime installation (official sources only) ----------------------------

function Test-WingetAvailable {
    $w = Get-Command winget -ErrorAction SilentlyContinue
    return ($null -ne $w)
}

<#
Installs a runtime through winget - the package manager Microsoft ships with
Windows, using its official 'winget' source. Nothing is downloaded from a
third-party mirror and no executable is fetched by URL.

User scope is attempted first so no administrator prompt is needed; if the
package does not support it, the default scope is tried once.
#>
function Install-Runtime([string]$wingetId, [string]$label) {
    if (-not (Test-WingetAvailable)) { return @{ Ok = $false; Reason = 'winget-missing' } }

    $common = @(
        'install', '--id', $wingetId, '--exact',
        '--source', 'winget',
        '--accept-package-agreements', '--accept-source-agreements',
        '--disable-interactivity'
    )

    Write-Info "Installing $label with winget (official Microsoft package source)..."
    Write-Info 'This runs once and can take a few minutes.'

    & winget @common '--scope' 'user' 2>&1 | ForEach-Object { Write-Host "           $_" -ForegroundColor DarkGray }
    if ($LASTEXITCODE -eq 0) { Update-SessionPath | Out-Null; return @{ Ok = $true } }

    Write-Info 'Per-user install was not available for this package; trying the default scope...'
    & winget @common 2>&1 | ForEach-Object { Write-Host "           $_" -ForegroundColor DarkGray }
    if ($LASTEXITCODE -eq 0) { Update-SessionPath | Out-Null; return @{ Ok = $true } }

    return @{ Ok = $false; Reason = "winget-exit-$LASTEXITCODE" }
}

# ---- setup fingerprints (so a second launch is fast) -------------------------
#
# Dependency installation and the frontend build are the slow steps. Each one
# is fingerprinted from the files that actually determine its output, so it is
# repeated only when one of those files changes - not on every launch.

function Get-PathsHash([string[]]$paths) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $sb = New-Object System.Text.StringBuilder
        foreach ($p in ($paths | Sort-Object)) {
            if (-not (Test-Path $p)) { continue }
            $item = Get-Item $p -ErrorAction SilentlyContinue
            if (-not $item) { continue }
            if ($item.PSIsContainer) {
                Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue |
                    Sort-Object FullName | ForEach-Object {
                        [void]$sb.Append($_.FullName.Substring($script:ProjectRoot.Length))
                        [void]$sb.Append('|').Append($_.Length).Append('|').Append($_.LastWriteTimeUtc.Ticks).Append("`n")
                    }
            } else {
                [void]$sb.Append($item.FullName.Substring($script:ProjectRoot.Length))
                [void]$sb.Append('|').Append($item.Length).Append('|').Append($item.LastWriteTimeUtc.Ticks).Append("`n")
            }
        }
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($sb.ToString())
        return [System.BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '')
    } finally {
        $sha.Dispose()
    }
}

function Get-StampFile { Join-Path $script:RunDir 'setup.stamp.json' }

function Read-SetupStamp {
    $f = Get-StampFile
    if (-not (Test-Path $f)) { return @{} }
    try {
        $raw = Get-Content $f -Raw -ErrorAction Stop
        $obj = $raw | ConvertFrom-Json -ErrorAction Stop
        $h = @{}
        foreach ($p in $obj.PSObject.Properties) { $h[$p.Name] = $p.Value }
        return $h
    } catch {
        # A corrupt stamp must only cost time (a redundant reinstall), never
        # correctness - treat it as "nothing is known" rather than failing.
        return @{}
    }
}

function Save-SetupStamp([hashtable]$stamp) {
    try {
        ($stamp | ConvertTo-Json -Depth 5) | Set-Content -Path (Get-StampFile) -Encoding utf8
    } catch {
        Write-Warn "Could not write the setup fingerprint file; the next launch may redo setup steps."
    }
}

# ---- prerequisites -----------------------------------------------------------

<#
The packaged app is a single process: the backend serves the built frontend
(frontend\dist), so only the Python venv and that build are required to run
it. Node.js/npm are only needed again if setup.bat is re-run (e.g. after
pulling frontend source changes) - never at start.ps1 time.
#>
function Test-Prerequisites {
    param([switch]$Quiet)   # probe silently, so start.ps1 can self-heal instead of scolding

    $ok = $true
    if (-not (Test-Path $script:VenvPython)) {
        if (-not $Quiet) {
            Write-Err 'Python environment missing: backend\.venv'
            Write-Info 'Run START.bat once to create it.'
        }
        $ok = $false
    }
    if (-not (Test-Path $script:FrontendIndex)) {
        if (-not $Quiet) {
            Write-Err 'Dashboard build missing: frontend\dist'
            Write-Info 'Run START.bat once to build it.'
        }
        $ok = $false
    }
    if (-not (Test-Path (Join-Path $script:ProjectRoot '.env'))) { $ok = $false }
    return $ok
}
