$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir
$PythonVersion = "3.13.9"

function Find-RosterMatePython {
    $Candidates = @()
    $Launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($Launcher) {
        try {
            $PathFromLauncher = & py.exe -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0) { $Candidates += $PathFromLauncher }
        } catch {}
    }
    $Candidates += @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:ProgramFiles "Python313\python.exe")
    )
    foreach ($Candidate in $Candidates) {
        if ($Candidate -and (Test-Path $Candidate)) {
            & $Candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
            if ($LASTEXITCODE -eq 0) { return $Candidate }
        }
    }
    return $null
}

$SystemPython = Find-RosterMatePython
if (-not $SystemPython) {
    $InstallerPath = Join-Path $env:TEMP "rostermate-python-$PythonVersion-amd64.exe"
    $DownloadUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
    Write-Host "Henter Python $PythonVersion fra python.org..."
    Invoke-WebRequest -UseBasicParsing -Uri $DownloadUrl -OutFile $InstallerPath
    $Process = Start-Process -FilePath $InstallerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0" -Wait -PassThru
    Remove-Item $InstallerPath -Force -ErrorAction SilentlyContinue
    if ($Process.ExitCode -ne 0) { throw "Python-installationen fejlede med kode $($Process.ExitCode)." }
    $SystemPython = Find-RosterMatePython
    if (-not $SystemPython) { throw "Python blev installeret, men kunne ikke findes bagefter." }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Opretter virtuelt Python-miljø..."
    & $SystemPython -m venv .venv
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
$Shortcut.IconLocation = Join-Path $ProjectDir "assets\RosterMate.ico"
$Shortcut.Save()

Write-Host ""
Write-Host "RosterMate er installeret til Windows."
Write-Host "Lokale data gemmes i: $DataRoot"
Write-Host "En RosterMate-genvej er oprettet i Start-menuen."
Write-Host "Start appen med run-windows.cmd"
