[Setup]
AppName=SA-CMS-Pro
AppVersion=1.0.0
DefaultDirName={pf64}\SA-CMS-Pro
DefaultGroupName=SA-CMS-Pro
OutputBaseFilename=SA-CMS-Pro-Setup
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\main\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\SA-CMS-Pro"; Filename: "{app}\main.exe"
Name: "{group}\Uninstall SA-CMS-Pro"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\main.exe"; Description: "Launch SA-CMS-Pro"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
