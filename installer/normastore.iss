#define AppName "NormaStore"
#define AppVersion "0.1.0"
#define AppPublisher "NormaStore"
#define AppExeName "NormaStore.exe"

[Setup]
AppId={{F431C4B3-7C2F-4E23-A965-3A9D698CDAB2}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist\installer
OutputBaseFilename=NormaStore-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\NormaStore\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng ngoài Desktop"; GroupDescription: "Biểu tượng bổ sung:"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Mở NormaStore"; Flags: nowait postinstall skipifsilent
