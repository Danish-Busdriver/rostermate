$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$AppUrl = "http://127.0.0.1:8080"
$WizardUrl = "http://localhost:8080/wizard/"

if (-not (Test-Path $Python)) {
    throw "Det virtuelle miljø mangler. Kør install-windows.cmd først."
}

$ExpectedVersion = & $Python -c "import app; print(app.APP_VERSION)"

function Start-RosterMateTray([int]$ServerPid) {
    $Pythonw = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"
    Start-Process -FilePath $Pythonw -ArgumentList @("tray.py", "--server-pid", $ServerPid) -WorkingDirectory $ProjectDir
}

try {
    $Health = Invoke-WebRequest -UseBasicParsing -Uri "$AppUrl/health" -TimeoutSec 2
    $HealthData = $Health.Content | ConvertFrom-Json
    if ($Health.StatusCode -eq 200 -and $HealthData.version -eq $ExpectedVersion) {
        $ExistingPid = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty OwningProcess
        Start-RosterMateTray ([int]$ExistingPid)
        Start-Process $WizardUrl
        exit 0
    }
    if ($Health.StatusCode -eq 200 -and $HealthData.status -eq "ok") {
        Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 500
    }
} catch {
    # Serveren kører ikke endnu.
}

& $Python auto_update.py

$DataRoot = Join-Path $env:LOCALAPPDATA "RosterMate"
$LogDir = Join-Path $DataRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$StdoutLog = Join-Path $LogDir "rostermate.stdout.log"
$StderrLog = Join-Path $LogDir "rostermate.stderr.log"

$ServerProcess = Start-Process -FilePath $Python -ArgumentList "app.py" -WorkingDirectory $ProjectDir -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog -PassThru

for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $Health = Invoke-WebRequest -UseBasicParsing -Uri "$AppUrl/health" -TimeoutSec 2
        $HealthData = $Health.Content | ConvertFrom-Json
        if ($Health.StatusCode -eq 200 -and $HealthData.version -eq $ExpectedVersion) {
            Start-RosterMateTray $ServerProcess.Id
            Start-Process $WizardUrl
            exit 0
        }
    } catch {
        # Vent på at Flask starter.
    }
}

throw "RosterMate kunne ikke starte. Se logfilerne i $LogDir"
