@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-windows.ps1"
if errorlevel 1 (
    echo.
    echo RosterMate kunne ikke starte. Se launcher.log under %%LOCALAPPDATA%%\RosterMate\logs.
    pause
    exit /b 1
)
