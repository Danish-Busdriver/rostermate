@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1"
if errorlevel 1 (
  echo.
  echo Installationen fejlede. Se fejlbeskeden ovenfor.
  pause
  exit /b 1
)
pause
