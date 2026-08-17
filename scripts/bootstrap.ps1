# =============================================================================
# First-run setup, made automatic and repeatable.
#
# This is what turns a freshly copied project folder into a running app with no
# technical knowledge required. It is called automatically by START.bat (and by
# start.ps1 when something is missing), and can also be run on its own.
#
# It is INCREMENTAL. Each expensive step is fingerprinted from the files that
# determine its result, so a second launch does no work at all. Nothing is
# reinstalled or rebuilt "just in case".
#
# It is NON-DESTRUCTIVE. It only ever creates what is missing. The database,
# reports, exports, uploads, logs and data\config are never deleted, reset or
# overwritten - re-running this on a machine with existing audit history is
# always safe.
#
# Exit codes:  0 = ready to start   1 = a prerequisite genuinely needs a human
# =============================================================================

param(
    [switch]$Force,      # redo the dependency/build steps even if fingerprints match
    [switch]$NoInstall,  # never attempt to install a runtime; only report what is missing
    [switch]$Quiet
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$didWork = $false

function Show-ManualStep([string]$what, [string]$url, [string]$why) {
    Write-Host ''
    Write-Err "$what could not be installed automatically."
    Write-Info ''
    Write-Info "  What to do (one time, about 3 minutes):"
    Write-Info "    1. Open this page:  $url"
    Write-Info "    2. Download the Windows installer and run it."
    Write-Info "    3. Tick 'Add to PATH' if the installer offers it."
    Write-Info "    4. Double-click START.bat again - it will carry on from here."
    Write-Info ''
    Write-Info "  Why this is needed: $why"
    Write-Host ''
}

if (-not $Quiet) {
    Write-Host ''
    Write-Host '  Advanced Website Auditor - preparing' -ForegroundColor White
    Write-Host "  $ProjectRoot" -ForegroundColor DarkGray
}

# -----------------------------------------------------------------------------
# 1. Operating system
# -----------------------------------------------------------------------------
Write-Head 'System'

if (-not ($IsWindows -or $env:OS -eq 'Windows_NT')) {
    Write-Err 'These launcher scripts target Windows.'
    Write-Info 'On macOS or Linux, run the commands in README.md instead.'
    exit 1
}
$osName = try { (Get-CimInstance Win32_OperatingSystem).Caption } catch { 'Windows' }
# Windows PowerShell 5.1 has no ternary operator - keep this 5.1-compatible,
# because that is what ships with Windows and what the .bat wrappers invoke.
$arch = if ([System.Environment]::Is64BitOperatingSystem) { '64-bit' } else { '32-bit' }
Write-Ok "$osName ($arch), PowerShell $($PSVersionTable.PSVersion)"

# Free disk space - a failed install halfway through is much harder to explain
# than a clear message up front.
try {
    $drive = (Get-Item $ProjectRoot).PSDrive
    if ($drive.Free -and $drive.Free -lt 1GB) {
        Write-Warn "Only $([math]::Round($drive.Free / 1MB)) MB free on drive $($drive.Name): - setup needs roughly 1 GB."
    }
} catch {}

# -----------------------------------------------------------------------------
# 2. Folders, configuration
# -----------------------------------------------------------------------------
Write-Head 'Project files'

foreach ($d in @(
    $DataDir, $RunDir, $LogDir,
    (Join-Path $DataDir 'config'), (Join-Path $DataDir 'uploads'),
    (Join-Path $DataDir 'exports'), (Join-Path $DataDir 'reports')
)) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Force -Path $d | Out-Null
        Write-Info "created $($d.Substring($ProjectRoot.Length).TrimStart('\'))"
        $didWork = $true
    }
}
Write-Ok 'Data folders ready (existing data left untouched).'

$envResult = Ensure-EnvFile
if ($envResult.Created) {
    Write-Ok 'Created .env from .env.example.'
    $didWork = $true
} else {
    Write-Ok 'Configuration file .env found.'
}

$cfg = Get-ProjectConfig
$configProblems = Test-ProjectConfig $cfg
if ($configProblems.Count -gt 0) {
    foreach ($p in $configProblems) { Write-Err $p }
    Write-Info "Edit: $(Join-Path $ProjectRoot '.env')"
    Write-Host ''
    exit 1
}
Write-Ok "Configuration valid (port $($cfg.BackendPort), host $($cfg.BackendHost))."

# -----------------------------------------------------------------------------
# 3. Python
# -----------------------------------------------------------------------------
Write-Head 'Python'

$python = Find-PythonExe
if (-not $python -and -not $NoInstall) {
    Write-Warn 'Python 3.10+ was not found on this computer.'
    if (Test-WingetAvailable) {
        $r = Install-Runtime 'Python.Python.3.12' 'Python 3.12'
        if ($r.Ok) { $python = Find-PythonExe }
    } else {
        Write-Warn 'winget (the Windows package installer) is not available on this system.'
    }
}
if (-not $python) {
    Show-ManualStep 'Python 3.10 or newer' 'https://www.python.org/downloads/windows/' `
        'the audit engine, the web API and the report generator all run on Python.'
    exit 1
}
Write-Ok "Python $($python.Version) at $($python.Path)"

# ---- virtual environment ----
if (-not (Test-Path $VenvPython)) {
    Write-Info 'Creating the private Python environment (backend\.venv)...'
    & $python.Path -m venv (Join-Path $BackendDir '.venv')
    if (-not (Test-Path $VenvPython)) {
        Write-Err 'The Python virtual environment could not be created.'
        Write-Info "Tried: $($python.Path) -m venv `"$(Join-Path $BackendDir '.venv')`""
        Write-Info 'This usually means the Python install is missing the "venv" module, or the'
        Write-Info 'project folder is read-only. Reinstall Python from python.org and try again.'
        Write-Host ''
        exit 1
    }
    Write-Ok 'Private Python environment created.'
    $didWork = $true
} else {
    Write-Ok 'Private Python environment already exists.'
}

# ---- backend packages (fingerprinted) ----
$stamp = Read-SetupStamp
$reqFile = Join-Path $BackendDir 'requirements.txt'
$reqHash = Get-PathsHash @($reqFile)

# Confirm the venv is actually usable, not just present - an interrupted first
# run can leave the folder there with nothing installed into it.
$venvHealthy = $false
if (Test-Path $VenvPython) {
    try {
        & $VenvPython -c "import fastapi, uvicorn, sqlalchemy, jinja2" 2>&1 | Out-Null
        $venvHealthy = ($LASTEXITCODE -eq 0)
    } catch { $venvHealthy = $false }
}

if ($Force -or -not $venvHealthy -or $stamp['requirements'] -ne $reqHash) {
    if (-not $venvHealthy) {
        Write-Info 'Backend packages are missing or incomplete - installing...'
    } else {
        Write-Info 'requirements.txt changed - updating backend packages...'
    }
    & $VenvPython -m pip install --upgrade pip --quiet 2>&1 | Out-Null
    & $VenvPython -m pip install -r $reqFile --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Err 'Installing the Python packages failed.'
        Write-Info 'The most common cause is no internet connection, or a company firewall'
        Write-Info 'blocking pypi.org. Connect to the internet and double-click START.bat again.'
        Write-Host ''
        exit 1
    }
    # Re-verify rather than trusting the exit code alone.
    & $VenvPython -c "import fastapi, uvicorn, sqlalchemy, jinja2" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Err 'The Python packages installed but could not be imported.'
        Write-Info "Try deleting this folder and running START.bat again: $(Join-Path $BackendDir '.venv')"
        Write-Host ''
        exit 1
    }
    $stamp['requirements'] = $reqHash
    Save-SetupStamp $stamp
    Write-Ok 'Backend packages installed.'
    $didWork = $true
} else {
    Write-Ok 'Backend packages already up to date.'
}

# -----------------------------------------------------------------------------
# 4. Frontend  (only when the built dashboard is missing or its source changed)
# -----------------------------------------------------------------------------
Write-Head 'Dashboard'

$frontSrc = @(
    (Join-Path $FrontendDir 'src'),
    (Join-Path $FrontendDir 'index.html'),
    (Join-Path $FrontendDir 'vite.config.js'),
    (Join-Path $FrontendDir 'package.json')
)
$srcHash  = Get-PathsHash $frontSrc
$lockHash = Get-PathsHash @((Join-Path $FrontendDir 'package-lock.json'), (Join-Path $FrontendDir 'package.json'))

$needBuild   = $Force -or (-not (Test-Path $FrontendIndex)) -or ($stamp['frontend_src'] -ne $srcHash)
$needModules = $needBuild -and ((-not (Test-Path $ViteBin)) -or $Force -or ($stamp['frontend_lock'] -ne $lockHash))

if (-not $needBuild) {
    Write-Ok 'Dashboard already built and up to date.'
} else {
    # Node is required ONLY to build the dashboard. Once frontend\dist exists,
    # the backend serves it directly and Node is never needed again at runtime.
    $node = Find-NodeExe
    if (-not $node -and -not $NoInstall) {
        Write-Warn 'Node.js 18+ was not found, and the dashboard needs building.'
        if (Test-WingetAvailable) {
            $r = Install-Runtime 'OpenJS.NodeJS.LTS' 'Node.js LTS'
            if ($r.Ok) { $node = Find-NodeExe }
        } else {
            Write-Warn 'winget (the Windows package installer) is not available on this system.'
        }
    }
    if (-not $node -or -not $node.Npm) {
        Show-ManualStep 'Node.js 18 or newer' 'https://nodejs.org/en/download' `
            'it compiles the dashboard once. After that it is never used again.'
        exit 1
    }
    Write-Ok "Node $($node.Version) at $($node.Path)"

    if ($needModules) {
        Write-Info 'Installing dashboard build tools (one time, a few minutes)...'
        Push-Location $FrontendDir
        try {
            & $node.Npm install --no-fund --no-audit --loglevel=error
            $npmExit = $LASTEXITCODE
        } finally { Pop-Location }

        if ($npmExit -ne 0 -or -not (Test-Path $ViteBin)) {
            # A partially written node_modules is the usual cause and is safe to
            # discard: it is build scratch space, never user data.
            Write-Warn 'The first attempt failed. Clearing the download cache and retrying once...'
            $nm = Join-Path $FrontendDir 'node_modules'
            if (Test-Path $nm) { Remove-Item $nm -Recurse -Force -ErrorAction SilentlyContinue }
            Push-Location $FrontendDir
            try {
                & $node.Npm install --no-fund --no-audit --loglevel=error
                $npmExit = $LASTEXITCODE
            } finally { Pop-Location }
        }
        if ($npmExit -ne 0 -or -not (Test-Path $ViteBin)) {
            Write-Err 'Installing the dashboard build tools failed.'
            Write-Info 'This is almost always no internet connection, or a firewall blocking'
            Write-Info 'registry.npmjs.org. Connect to the internet and run START.bat again.'
            Write-Host ''
            exit 1
        }
        $stamp['frontend_lock'] = $lockHash
        Save-SetupStamp $stamp
        Write-Ok 'Dashboard build tools installed.'
    } else {
        Write-Ok 'Dashboard build tools already installed.'
    }

    Write-Info 'Building the dashboard...'
    Push-Location $FrontendDir
    try {
        & $node.Npm run build --silent
        $buildExit = $LASTEXITCODE
    } finally { Pop-Location }

    if ($buildExit -ne 0 -or -not (Test-Path $FrontendIndex)) {
        Write-Err 'Building the dashboard failed.'
        Write-Info "Expected to produce: $FrontendIndex"
        Write-Info 'Run START.bat again. If it keeps failing, delete this folder and retry:'
        Write-Info "  $(Join-Path $FrontendDir 'node_modules')"
        Write-Host ''
        exit 1
    }
    # Fingerprint the sources only after a build that actually produced output.
    $stamp['frontend_src'] = Get-PathsHash $frontSrc
    Save-SetupStamp $stamp
    Write-Ok 'Dashboard built.'
    $didWork = $true
}

# -----------------------------------------------------------------------------
# 5. Database  (created if absent; an existing one is opened, never reset)
# -----------------------------------------------------------------------------
Write-Head 'Database'

$dbPath = Join-Path $DataDir 'app.db'
$existed = Test-Path $dbPath

Push-Location $BackendDir
try {
    & $VenvPython -c "from app.db import init_db; init_db()" 2>&1 | Out-Null
    $dbExit = $LASTEXITCODE
} finally { Pop-Location }

if ($dbExit -ne 0) {
    Write-Err 'The database could not be prepared.'
    Write-Info "Location: $dbPath"
    Write-Info 'Check that the data folder is writable and not synced by OneDrive while locked.'
    Write-Host ''
    exit 1
}
if ($existed) {
    $sizeKb = [math]::Round((Get-Item $dbPath).Length / 1KB)
    Write-Ok "Existing database opened and preserved ($sizeKb KB) - no data was reset."
} else {
    Write-Ok 'New empty database created.'
    $didWork = $true
}

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
Write-Head 'Ready'
if ($didWork) {
    Write-Ok 'Setup finished. This only happens when something is missing.'
} else {
    Write-Ok 'Everything was already in place - nothing to install.'
}
exit 0
