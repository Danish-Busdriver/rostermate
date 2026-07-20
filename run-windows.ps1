$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Det virtuelle miljø mangler. Kør install-windows.cmd først."
}

& $Python (Join-Path $ProjectDir "windows_launcher.py")
if ($LASTEXITCODE -ne 0) {
    throw "RosterMate-starten fejlede. Se launcher.log under %LOCALAPPDATA%\RosterMate\logs."
}
