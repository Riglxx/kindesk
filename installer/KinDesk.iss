#ifndef AppVer
  #define AppVer "0.0"
#endif
[Setup]
AppId={{8F3C5E1A-4B7D-4C2E-9A61-5D0B1C7E2F43}
AppName=KinDesk
AppVersion={#AppVer}
AppPublisher=KinDesk
DefaultDirName={autopf}\KinDesk
DefaultGroupName=KinDesk
PrivilegesRequired=lowest
OutputBaseFilename=KinDesk_Setup_v{#AppVer}
OutputDir=Output
SetupIconFile=..\KinDesk.ico
UninstallDisplayIcon={app}\KinDesk.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; Flags: unchecked
Name: "autostart"; Description: "Запускать вместе с Windows"

[Files]
Source: "..\dist\KinDesk.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\KinDesk"; Filename: "{app}\KinDesk.exe"
Name: "{autodesktop}\KinDesk"; Filename: "{app}\KinDesk.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "KinDesk"; ValueData: """{app}\KinDesk.exe"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\KinDesk.exe"; Description: "Запустить KinDesk"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\KinDesk.exe"; Parameters: "--restore"; Flags: runhidden skipifdoesntexist; RunOnceId: "KinDeskRestore"
