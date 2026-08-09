#ifndef AppVersion
  #define AppVersion "1.15.0"
#endif

#define AppName "RosterMate"
#define AppPublisher "Daniel Pullen"
#define AppURL "https://github.com/Danish-Busdriver/rostermate"

[Setup]
AppId={{B0270A8E-5458-4C81-936E-309868E15B31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases/latest
DefaultDirName={localappdata}\Programs\RosterMate
DefaultGroupName=RosterMate
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=..\..\dist\windows
OutputBaseFilename=RosterMate-{#AppVersion}-Windows-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=RosterMate installation
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
SetupIconFile=..\..\assets\RosterMate.ico

[Languages]
Name: "danish"; MessagesFile: "compiler:Languages\Danish.isl"

[Files]
Source: "..\..\*.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\telemetry-config.example.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\*-windows.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\*-windows.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\.env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\static\*"; DestDir: "{app}\static"; Flags: ignoreversion recursesubdirs
Source: "..\..\assets\RosterMate.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "..\..\docs\INSTALL_WINDOWS.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\RosterMate"; Filename: "{app}\run-windows.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\assets\RosterMate.ico"
Name: "{autoprograms}\Afinstaller RosterMate"; Filename: "{uninstallexe}"
Name: "{userdesktop}\RosterMate"; Filename: "{app}\run-windows.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\assets\RosterMate.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Opret en genvej på skrivebordet"; GroupDescription: "Ekstra genveje:"; Flags: unchecked

[Run]
Filename: "{app}\run-windows.cmd"; Description: "Start RosterMate"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall-windows.ps1"""; WorkingDir: "{app}"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: files; Name: "{app}\.env"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := 'Installerer RosterMate og browserkomponenter...';
    if not Exec(
      ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      ExpandConstant('-NoProfile -ExecutionPolicy Bypass -File "{app}\install-windows.ps1"'),
      ExpandConstant('{app}'),
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    ) then
      RaiseException('RosterMate-installationsscriptet kunne ikke startes.');
    if ResultCode <> 0 then
      RaiseException(Format('RosterMate-installationen fejlede med kode %d.', [ResultCode]));
  end;
end;
