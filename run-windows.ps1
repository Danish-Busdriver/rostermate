$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$VenvConfig = Join-Path $ProjectDir ".venv\pyvenv.cfg"

function Test-RosterMateVenv {
    if (-not (Test-Path $VenvConfig) -or -not (Test-Path $Python)) { return $false }
    try {
        & $Python -c "import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

if (-not (Test-RosterMateVenv)) {
    Write-Host "RosterMates Python-miljø mangler eller er beskadiget. Reparerer automatisk..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectDir "install-windows.ps1")
    if ($LASTEXITCODE -ne 0 -or -not (Test-RosterMateVenv)) {
        throw "RosterMates Python-miljø kunne ikke repareres automatisk."
    }
}

& $Python (Join-Path $ProjectDir "windows_launcher.py")
if ($LASTEXITCODE -ne 0) {
    throw "RosterMate-starten fejlede. Se launcher.log under %LOCALAPPDATA%\RosterMate\logs."
}
