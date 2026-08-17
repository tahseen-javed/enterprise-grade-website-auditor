@echo off
REM ===========================================================================
REM  Advanced Website Auditor - ONE-CLICK LAUNCHER
REM
REM  This is the only file you need. Double-click it.
REM
REM  On the very first run it sets everything up by itself (Python environment,
REM  packages, dashboard build, database). That takes a few minutes and only
REM  happens once. Every run after that starts in a couple of seconds.
REM
REM  When it is ready your web browser opens automatically.
REM
REM  Works from any folder, on any Windows PC, with spaces in the path.
REM  Nothing here depends on where this project happens to live: %~dp0 is
REM  always the folder this file is sitting in.
REM ===========================================================================

setlocal
title Advanced Website Auditor

cd /d "%~dp0"

echo.
echo   ============================================
echo     ADVANCED WEBSITE AUDITOR
echo   ============================================
echo.
echo   Starting up. The first run takes a few
echo   minutes while it installs what it needs.
echo   Later runs take only a few seconds.
echo.
echo   Your browser will open automatically.
echo.

REM PowerShell ships with every supported version of Windows. If it is genuinely
REM missing, say so plainly rather than failing with an unreadable error.
where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo   [PROBLEM] Windows PowerShell was not found on this computer.
  echo.
  echo   This is very unusual. It normally means Windows is damaged or
  echo   heavily restricted by a company policy.
  echo.
  echo   Ask whoever manages this computer to enable Windows PowerShell.
  echo.
  pause
  exit /b 1
)

REM -ExecutionPolicy Bypass applies to THIS run only - it does not change any
REM setting on the computer. -Watchdog turns on automatic restart-on-crash.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -Watchdog %*
set EXITCODE=%ERRORLEVEL%

if %EXITCODE% NEQ 0 (
  echo.
  echo   ============================================
  echo     IT COULD NOT START
  echo   ============================================
  echo.
  echo   The reason is printed above - it usually says
  echo   exactly what to do next.
  echo.
  echo   The two most common causes:
  echo     * No internet connection on the first run.
  echo     * Python or Node.js needs installing once,
  echo       from the official link shown above.
  echo.
  echo   After fixing it, just double-click this file again.
  echo.
  pause
  exit /b %EXITCODE%
)

echo.
echo   The app is running and will stay running after
echo   this window closes.
echo.
echo     stop.bat     stop the app
echo     status.bat   check it is healthy
echo     restart.bat  stop and start again
echo.
REM A brief pause so a double-click user can read the result before the window
REM closes. Nothing is waiting on it - the app is already running detached.
REM 'ping' is used rather than 'timeout' because timeout aborts when stdin is
REM redirected, which happens whenever this file is run from another script.
ping -n 9 127.0.0.1 >nul 2>&1
endlocal & exit /b 0
