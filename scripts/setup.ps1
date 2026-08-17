# Explicit setup entry point, kept for anyone who prefers to prepare the
# project before starting it (and for existing habits / documentation).
#
# It is no longer required: START.bat performs exactly the same preparation
# automatically when anything is missing. There is deliberately only ONE
# implementation of setup - bootstrap.ps1 - so the manual and automatic paths
# can never drift apart.
#
#   setup.bat              prepare anything missing (fast if already done)
#   setup.bat -Force       redo the dependency install and dashboard build

param(
    [switch]$Force,
    [switch]$NoInstall
)

$bootstrap = Join-Path $PSScriptRoot 'bootstrap.ps1'
& $bootstrap -Force:$Force -NoInstall:$NoInstall
$code = $LASTEXITCODE

if ($code -eq 0) {
    . (Join-Path $PSScriptRoot 'lib.ps1')
    $cfg = Get-ProjectConfig
    Write-Head 'Next step'
    Write-Info 'Double-click START.bat - the dashboard opens automatically at'
    Write-Info "http://localhost:$($cfg.BackendPort)"
    Write-Host ''
}
exit $code
