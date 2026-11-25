; Streamer Censoring Multitool (SCM) — Created by Intzevidis7
; GitHub: https://github.com/Intzevidis7
#define MyAppName "Streamer Censoring Multitool"
#define MyAppShortName "SCM"
#define MyAppExeName "SCM.exe"
#define MyAppModelsExeName "SCM-Models.exe"
#define MyAppVersion "0.4.0"

[Setup]
AppId={{BFF6E520-69C9-4986-85EE-7D00F111C69D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Intzevidis7
AppPublisherURL=https://github.com/Intzevidis7
DefaultDirName={localappdata}\{#MyAppShortName}
SetupIconFile=app.ico
DefaultGroupName={#MyAppName}
OutputDir=release
OutputBaseFilename={#MyAppShortName}-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "dist\{#MyAppShortName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName} ({#MyAppShortName})"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\{#MyAppModelsExeName}"; Description: "Download Greek and English Vosk models (internet required; several GB of free disk space recommended)"; Flags: postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Description: "Open {#MyAppName} ({#MyAppShortName})"; Flags: postinstall nowait skipifsilent unchecked