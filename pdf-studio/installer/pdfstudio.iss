; Inno Setup - instalator pentru PDF Studio.
; Produce PDF-Studio-Setup.exe: instalează aplicația și pune scurtături
; pe desktop și în meniul Start, exact ca orice program Windows.
; Se compilează cu Inno Setup (ISCC.exe) - vezi build_installer.bat.

#define AppName "PDF Studio"
#define AppVer "1.0.0"
#define AppPublisher "Carpatica Feroviar"
#define ExeName "PDF-Studio.exe"

[Setup]
AppId={{A1C2F3D4-5E6F-47A8-9B0C-PDFSTUDIO0001}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\PDF Studio
DefaultGroupName=PDF Studio
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#ExeName}
OutputDir=Output
OutputBaseFilename=PDF-Studio-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Instalare fără drepturi de administrator (per utilizator).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ro"; MessagesFile: "compiler:Languages\Romanian.isl"

[Tasks]
Name: "desktopicon"; Description: "Creează o scurtătură pe desktop"; GroupDescription: "Scurtături:"

[Files]
Source: "..\dist\{#ExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\PDF Studio"; Filename: "{app}\{#ExeName}"
Name: "{group}\Dezinstalează PDF Studio"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PDF Studio"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExeName}"; Description: "Pornește PDF Studio acum"; Flags: nowait postinstall skipifsilent
