$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) {
    throw "Python Launcher (py.exe) blev ikke fundet. Installer Python 3.12 eller nyere fra python.org og markér 'Add Python to PATH'."
}

$PythonVersion = & py.exe -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$PythonVersion -lt [version]"3.12") {
    throw "RosterMate kræver Python 3.12 eller nyere. Fundet version: $PythonVersion"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Opretter virtuelt Python-miljø..."
    & py.exe -3 -m venv .venv
}

$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
Write-Host "Installerer Python-afhængigheder..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt
& $VenvPython -m playwright install chromium

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Oprettede lokal .env-fil."
}

$DataRoot = Join-Path $env:LOCALAPPDATA "RosterMate"
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null

$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$ShortcutPath = Join-Path $StartMenu "RosterMate.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $ProjectDir "run-windows.cmd"
$Shortcut.WorkingDirectory = $ProjectDir
$Shortcut.Description = "Start RosterMate"
$Shortcut.Save()

Write-Host ""
Write-Host "RosterMate er installeret til Windows."
Write-Host "Lokale data gemmes i: $DataRoot"
Write-Host "En RosterMate-genvej er oprettet i Start-menuen."
Write-Host "Start appen med run-windows.cmd"
