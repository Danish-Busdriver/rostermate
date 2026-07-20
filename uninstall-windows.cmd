@echo off
setlocal
set "UNINSTALLER=%~dp0unins000.exe"

if exist "%UNINSTALLER%" (
    start "RosterMate afinstallation" /wait "%UNINSTALLER%"
    exit /b %errorlevel%
)

echo RosterMate blev ikke installeret med Setup.exe, saa Windows-uninstalleren findes ikke.
echo Luk RosterMate via ikonet i systembakken, og slet derefter denne kildemappe manuelt.
echo Brugerdata under %%LOCALAPPDATA%%\RosterMate bevares.
pause
exit /b 1
