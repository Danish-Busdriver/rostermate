#ifndef AppVersion
  #define AppVersion "1.7.1"
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
Source: "..\..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs; Excludes: ".venv\*;data\*;output\*;backups\*;.pytest_cache\*;.env;*.pyc;__pycache__\*;dist\*;.git\*;.github\*;tests\*;installer\*;RosterMate.app\*;install.command;run.command;uninstall.command;build-macos-pkg.command;docs\INSTALL_MACOS.md;AGENTS.md"

[Icons]
Name: "{autoprograms}\RosterMate"; Filename: "{app}\run-windows.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\assets\RosterMate.ico"
Name: "{autoprograms}\Afinstaller RosterMate"; Filename: "{uninstallexe}"
Name: "{userdesktop}\RosterMate"; Filename: "{app}\run-windows.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\assets\RosterMate.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Opret en genvej på skrivebordet"; GroupDescription: "Ekstra genveje:"; Flags: unchecked

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install-windows.ps1"""; WorkingDir: "{app}"; StatusMsg: "Installerer RosterMate og browserkomponenter..."; Flags: waituntilterminated
Filename: "{app}\run-windows.cmd"; Description: "Start RosterMate"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall-windows.ps1"""; WorkingDir: "{app}"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: files; Name: "{app}\.env"
