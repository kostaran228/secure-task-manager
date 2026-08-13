#define AppName "Task Manager"
#define AppVersion "1.0.0"
#define AppPublisher "kostaran"

[Setup]
AppId={{3B3901F4-6451-4EC0-92F9-E0697AD9AD44}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=output
OutputBaseFilename=TaskManagerSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "staging\TaskManager.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docker-compose.yml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Dockerfile"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.env.example"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*;*.pyc"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\TaskManager.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\TaskManager.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Run]
Filename: "{app}\TaskManager.exe"; Description: "Открыть Task Manager"; Flags: nowait postinstall skipifsilent
