#define MyAppName "EchoBridge"
#define MyAppVersion "0.5.2"
#define MyAppExeName "EchoBridge.exe"

[Setup]
AppId={{B5B97084-EE26-4AE4-9998-1233BAF43024}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=EchoBridge
DefaultDirName={localappdata}\Programs\EchoBridge
DefaultGroupName=EchoBridge
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
OutputDir=..\releases
OutputBaseFilename=EchoBridge-Setup-{#MyAppVersion}
SetupIconFile=echobridge.ico
CloseApplications=yes
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional options:"
Name: "autostart"; Description: "Start EchoBridge automatically when I sign in to Windows"; GroupDescription: "Additional options:"; Flags: unchecked

[Files]
Source: "..\dist\EchoBridge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\EchoBridge\EchoBridge"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\EchoBridge"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch EchoBridge"; Flags: nowait postinstall skipifsilent

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  RunValue = 'EchoBridge';

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExeCommand: String;
begin
  if CurStep = ssPostInstall then
  begin
    ExeCommand := '"' + ExpandConstant('{app}\{#MyAppExeName}') + '"';
    if IsTaskSelected('autostart') then
    begin
      if not RegWriteStringValue(HKCU, RunKey, RunValue, ExeCommand) then
        MsgBox('EchoBridge installed, but Windows startup could not be enabled. You can try again from Settings.', mbInformation, MB_OK);
    end
    else
      RegDeleteValue(HKCU, RunKey, RunValue);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  CurrentValue, ExeCommand: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    ExeCommand := '"' + ExpandConstant('{app}\{#MyAppExeName}') + '"';
    if RegQueryStringValue(HKCU, RunKey, RunValue, CurrentValue) then
      if CompareText(CurrentValue, ExeCommand) = 0 then
        RegDeleteValue(HKCU, RunKey, RunValue);
  end;
end;
