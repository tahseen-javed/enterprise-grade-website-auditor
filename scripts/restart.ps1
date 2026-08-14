# Stops this project's services, then starts them again.

param([switch]$NoBrowser)

$here = $PSScriptRoot

& (Join-Path $here 'stop.ps1')

Start-Sleep -Seconds 2

if ($NoBrowser) {
    & (Join-Path $here 'start.ps1') -NoBrowser
} else {
    & (Join-Path $here 'start.ps1')
}
exit $LASTEXITCODE
