$ErrorActionPreference = "SilentlyContinue"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$DataRoot = Join-Path $env:LOCALAPPDATA "RosterMate"
$Port = 8080

if ((Test-Path $Python) -and (Test-Path (Join-Path $ProjectDir "port_config.py"))) {
    $ConfiguredPort = & $Python (Join-Path $ProjectDir "port_config.py") configured
    if ($ConfiguredPort) { $Port = [int]$ConfiguredPort }
}

try {
    $Health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
    $HealthData = $Health.Content | ConvertFrom-Json
    if ($HealthData.status -eq "ok") {
        Get-NetTCPConnection -LocalPort $Port -State Listen |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { Stop-Process -Id $_ -Force }
    }
} catch {}

$TrayPidFile = Join-Path $DataRoot "rostermate-tray.pid"
if (Test-Path $TrayPidFile) {
    $TrayPid = [int]((Get-Content $TrayPidFile -Raw).Split(",")[0])
    if ($TrayPid) { Stop-Process -Id $TrayPid -Force }
    Remove-Item $TrayPidFile -Force
}

$ProfilesDir = Join-Path $DataRoot "data"
if (Test-Path $ProfilesDir) {
    Get-ChildItem $ProfilesDir -Directory | Where-Object { $_.Name -match '^\d+$' } | ForEach-Object {
        schtasks.exe /Delete /TN "RosterMate-$($_.Name)" /F | Out-Null
    }
}
