; SPDX-License-Identifier: GPL-3.0-or-later
; Installateur Windows de montar (Inno Setup 6). Le dossier autonome est préparé par
; scripts/windows/bundle.sh ; compilation :
;   ISCC /DAppVersion=1.3.1 /DBundleDir=build\windows\montar /DOutputDir=dist montar.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef BundleDir
  #define BundleDir "..\..\build\windows\montar"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif
#ifndef IconFile
  #define IconFile "..\..\build\windows\montar.ico"
#endif
#define AppId "appsdoc.montar"

[Setup]
AppId={{6F0B7C55-3E7A-4C1D-9A54-6D2E1B0C4A31}
AppName=montar
AppVersion={#AppVersion}
AppVerName=montar {#AppVersion}
AppPublisher=Fabien (appsdoc.fr)
AppPublisherURL=https://github.com/fabtmt31-lang/montar
AppSupportURL=https://github.com/fabtmt31-lang/montar/issues
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\montar
DefaultGroupName=montar
DisableProgramGroupPage=yes
; pour soi seul sans droits d'administrateur, ou pour tous les utilisateurs
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#BundleDir}\LICENSE
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\montar.ico
OutputDir={#OutputDir}
OutputBaseFilename=montar-{#AppVersion}-windows-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
CloseApplications=yes

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
fr.AssocTask=Ouvrir les projets .montar avec montar
en.AssocTask=Open .montar projects with montar
fr.ProjectType=Projet montar
en.ProjectType=montar project

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assoc"; Description: "{cm:AssocTask}"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#IconFile}"; DestDir: "{app}"; DestName: "montar.ico"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\montar"; Filename: "{app}\bin\pythonw.exe"; Parameters: "-X utf8 -I -m montar"; \
    WorkingDir: "{userdocs}"; IconFilename: "{app}\montar.ico"; AppUserModelID: "{#AppId}"; \
    Comment: "Montage vidéo simple et local"
Name: "{autodesktop}\montar"; Filename: "{app}\bin\pythonw.exe"; Parameters: "-X utf8 -I -m montar"; \
    WorkingDir: "{userdocs}"; IconFilename: "{app}\montar.ico"; AppUserModelID: "{#AppId}"; \
    Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.montar"; ValueType: string; ValueName: ""; \
    ValueData: "montar.projet"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\montar.projet"; ValueType: string; ValueName: ""; \
    ValueData: "{cm:ProjectType}"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\montar.projet\DefaultIcon"; ValueType: string; \
    ValueName: ""; ValueData: "{app}\montar.ico"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\montar.projet\shell\open\command"; ValueType: string; \
    ValueName: ""; ValueData: """{app}\bin\pythonw.exe"" -X utf8 -I -m montar ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\bin\pythonw.exe"; Parameters: "-X utf8 -I -m montar"; WorkingDir: "{userdocs}"; \
    Description: "{cm:LaunchProgram,montar}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; fichiers compilés par Python après l'installation
Type: filesandordirs; Name: "{app}"
