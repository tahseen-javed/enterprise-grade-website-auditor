@echo off
REM Thin wrapper so the app can be launched by double-click, with no
REM VS Code and no terminal knowledge required.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\status.ps1" %*
set EXITCODE=%ERRORLEVEL%
if %EXITCODE% NEQ 0 (
  echo.
  echo Something went wrong ^(exit code %EXITCODE%^).
)
pause
endlocal & exit /b %EXITCODE%
