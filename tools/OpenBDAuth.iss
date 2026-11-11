; tools/OpenBDAuth.iss
; Windows-Installer (Inno Setup 6) für das fertige Paket aus dist/OpenBDAuth/. tools/build_release.py ruft ihn auf:
;   ISCC /DAppVersion=<Version> tools\OpenBDAuth.iss   →   dist\OpenBDAuth-Setup-<Version>.exe
; Installiert ohne Admin-Rechte nach %LOCALAPPDATA%\Programs\OpenBDAuth; wer will, wählt „für alle Benutzer“
; (dann Programme). Einstellungen liegen in der Registry (QSettings) und bleiben beim Deinstallieren erhalten.

#ifndef AppVersion
  #error AppVersion fehlt: ISCC /DAppVersion=<Version> tools\OpenBDAuth.iss
#endif

[Setup]
; AppId nie ändern: daran erkennt Windows frühere Installationen für Update und Deinstallation
AppId={{7AEB80DE-D80C-4903-BC49-0BB96FAA41E4}
AppName=OpenBDAuth
AppVersion={#AppVersion}
AppVerName=OpenBDAuth {#AppVersion}
AppPublisher=OpenBDAuth
DefaultDirName={autopf}\OpenBDAuth
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=OpenBDAuth-Setup-{#AppVersion}
SetupIconFile=..\assets\icon\openbdauth.ico
UninstallDisplayIcon={app}\OpenBDAuth.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=auto
CloseApplications=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Bei einem Update die alte Laufzeit entfernen, damit keine Qt- oder Python-Dateien der Vorversion liegen bleiben
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\OpenBDAuth\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\OpenBDAuth"; Filename: "{app}\OpenBDAuth.exe"
Name: "{autodesktop}\OpenBDAuth"; Filename: "{app}\OpenBDAuth.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OpenBDAuth.exe"; Description: "{cm:LaunchProgram,OpenBDAuth}"; Flags: nowait postinstall skipifsilent
