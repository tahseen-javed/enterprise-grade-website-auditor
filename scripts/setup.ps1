# One-time setup: creates the backend virtual environment and installs both
# dependency sets. Safe to re-run.
#
# The Python packages go into backend\.venv - never into your global Python -
# so this project cannot disturb the versions other projects rely on.

. (Join-Path $PSScriptRoot 'lib.ps1')

Write-Host ''
Write-Host '  Advanced Website Auditor - setup' -ForegroundColor White
Write-Host "  $ProjectRoot" -ForegroundColor DarkGray

# ---- python ------------------------------------------------------------------
Write-Head 'Python'

$py = $null
foreach ($candidate in @('py', 'python')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        $ver = & $cmd.Source --version 2>&1
        if ($ver -match 'Python (\d+)\.(\d+)') {
            if ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 10) {
                $py = $cmd.Source
                Write-Ok "Found $ver at $($cmd.Source)"
                break
            } else {
                Write-Warn "$ver is too old (3.10 or newer is required)."
            }
        }
    }
}
if (-not $py) {
    Write-Err 'Python 3.10+ was not found. Install it from python.org and re-run setup.bat.'
    Write-Host ''
    exit 1
}

if (Test-Path $VenvPython) {
    Write-Ok 'Virtual environment already exists (backend\.venv).'
} else {
    Write-Info 'Creating the virtual environment...'
    & $py -m venv (Join-Path $BackendDir '.venv')
    if (-not (Test-Path $VenvPython)) {
        Write-Err 'Could not create backend\.venv.'
        Write-Host ''
        exit 1
    }
    Write-Ok 'Virtual environment created.'
}

Write-Info 'Installing Python packages (this can take a minute)...'
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r (Join-Path $BackendDir 'requirements.txt') --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Err 'Python package installation failed. Scroll up for the reason.'
    Write-Host ''
    exit 1
}
Write-Ok 'Python packages installed into backend\.venv.'

# ---- node --------------------------------------------------------------------
Write-Head 'Node.js'

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Err 'Node.js was not found. Install Node 18 or newer from nodejs.org and re-run setup.bat.'
    Write-Host ''
    exit 1
}
$nodeVer = & node --version
Write-Ok "Found Node $nodeVer"

$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm) {
    Write-Err 'npm was not found alongside Node.js.'
    Write-Host ''
    exit 1
}

Write-Info 'Installing frontend packages...'
Push-Location $FrontendDir
try {
    & $npm.Source install --no-fund --no-audit
    $npmExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($npmExit -ne 0 -or -not (Test-Path $ViteBin)) {
    Write-Err 'Frontend package installation failed.'
    Write-Host ''
    exit 1
}
Write-Ok 'Frontend packages installed.'

Write-Info 'Building the production frontend (frontend\dist)...'
Push-Location $FrontendDir
try {
    & $npm.Source run build --silent
    $buildExit = $LASTEXITCODE
} finally {
    Pop-Location
}
$indexHtml = Join-Path $FrontendDir 'dist\index.html'
if ($buildExit -ne 0 -or -not (Test-Path $indexHtml)) {
    Write-Err 'Frontend production build failed.'
    Write-Host ''
    exit 1
}
Write-Ok 'Frontend built into frontend\dist.'
Write-Info 'The backend serves this build directly - one process, one port, no Node needed at runtime.'

# ---- database ----------------------------------------------------------------
Write-Head 'Database'
Push-Location $BackendDir
try {
    & $VenvPython -c "from app.db import init_db; init_db(); print('ready')" | Out-Null
    $dbExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($dbExit -eq 0) {
    Write-Ok 'SQLite database initialised in data\app.db'
} else {
    Write-Warn 'Could not initialise the database now; it will be created on first start.'
}

$cfg = Get-ProjectConfig
Write-Head 'Setup complete'
Write-Info '1. Run start.bat'
Write-Info "2. The dashboard opens at http://localhost:$($cfg.BackendPort)"
Write-Info '3. New audit -> enter a website URL'
Write-Host ''
Write-Info 'VS Code is not needed for any of this. Node.js is only needed again if you'
Write-Info 're-run setup.bat (for example after pulling frontend changes).'
Write-Host ''
exit 0
