[Setup]
AppName=SA-CMS-Pro
AppVersion=0.1.0
DefaultDirName={pf}\SA-CMS-Pro
OutputBaseFilename=SA-CMS-Pro-Setup

[Files]
Source: "..\dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\SA-CMS-Pro"; Filename: "{app}\SA-CMS-Pro.exe"
