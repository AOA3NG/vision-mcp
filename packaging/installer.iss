#define MyAppName "Vision MCP"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "AOA3NG"
#define MyAppExeName "Vision MCP 管理器.exe"

[Setup]
AppId={{E68854F7-50B5-4CD3-97D6-98642A7F61D8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\VisionMCP
DisableDirPage=no
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist-installer
OutputBaseFilename=VisionMCP-Setup-{#MyAppVersion}-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=vision-mcp.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
; WebView2 and stdio processes may not respond to Restart Manager's graceful
; shutdown request. Force-close only processes locking files in this install,
; then let our [Run] entry launch the newly installed manager if requested.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Files]
Source: "..\dist\VisionMCP\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Vision MCP 管理器"; Filename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\Vision MCP 管理器"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "正在准备 Microsoft Edge WebView2 运行环境…"; Flags: runhidden waituntilterminated; Check: not WebView2Installed
Filename: "{app}\{#MyAppExeName}"; Description: "打开 Vision MCP 管理器"; Flags: nowait postinstall skipifsilent

[Code]
var
  DeletePersonalData: Boolean;
  ResultCode: Integer;

function WebView2Installed(): Boolean;
var
  Version: String;
  ClientKey: String;
begin
  ClientKey := 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result :=
    RegQueryStringValue(HKLM32, ClientKey, 'pv', Version) or
    RegQueryStringValue(HKCU, ClientKey, 'pv', Version);
  Result := Result and (Version <> '') and (Version <> '0.0.0.0');
end;

function PowerShellLiteral(Value: String): String;
begin
  Result := Value;
  StringChangeEx(Result, '''', '''''', True);
  Result := '''' + Result + '''';
end;

function StopInstalledVisionProcesses(): Boolean;
var
  PowerShellExe: String;
  ManagerPath: String;
  ServerPath: String;
  Script: String;
  Params: String;
  ExitCode: Integer;
begin
  PowerShellExe := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  ManagerPath := ExpandConstant('{app}\{#MyAppExeName}');
  ServerPath := ExpandConstant('{app}\vision-mcp-server.exe');
  Script :=
    '$targets=@(' + PowerShellLiteral(ManagerPath) + ',' + PowerShellLiteral(ServerPath) + ');' +
    '$running=@(Get-CimInstance Win32_Process | Where-Object {' +
      '$_.ExecutablePath -and ($targets -contains $_.ExecutablePath)});' +
    '$running | ForEach-Object {' +
      'Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue};' +
    'Start-Sleep -Milliseconds 300;' +
    '$remaining=@(Get-CimInstance Win32_Process | Where-Object {' +
      '$_.ExecutablePath -and ($targets -contains $_.ExecutablePath)});' +
    'if ($remaining.Count -gt 0) { exit 1 } else { exit 0 }';
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' + Script + '"';
  Result :=
    Exec(PowerShellExe, Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) and
    (ExitCode = 0);
end;

function RemoveInstalledAgentEntries(): Boolean;
var
  ExitCode: Integer;
begin
  Result :=
    Exec(
      ExpandConstant('{app}\{#MyAppExeName}'),
      '--maintenance agent remove all --server "' + ExpandConstant('{app}\vision-mcp-server.exe') + '"',
      '', SW_HIDE, ewWaitUntilTerminated, ExitCode
    ) and (ExitCode = 0);
end;

function PrepareUninstallCleanup(): Boolean;
var
  AgentEntriesRemoved: Boolean;
  ProcessesStopped: Boolean;
begin
  { Remove commands first so a running Agent cannot immediately restart the
    stdio server while the uninstaller is trying to delete it. }
  AgentEntriesRemoved := RemoveInstalledAgentEntries();
  ProcessesStopped := StopInstalledVisionProcesses();
  Result := AgentEntriesRemoved and ProcessesStopped;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  WizardForm.StatusLabel.Caption := '正在关闭运行中的 Vision MCP…';
  if not StopInstalledVisionProcesses() then
    Result := '无法关闭正在运行的 Vision MCP。请先关闭管理器和正在调用 Vision MCP 的 Agent，然后重试。';
end;

function InitializeUninstall(): Boolean;
var
  ConfirmForm: TSetupForm;
  BrandLabel: TNewStaticText;
  TitleLabel: TNewStaticText;
  InfoLabel: TNewStaticText;
  DeleteDataCheck: TNewCheckBox;
  DeleteDataNote: TNewStaticText;
  ContinueButton: TNewButton;
  CancelButton: TNewButton;
begin
  Result := False;
  DeletePersonalData := False;
  if UninstallSilent() then
  begin
    Result := PrepareUninstallCleanup();
    exit;
  end;
  ConfirmForm := CreateCustomForm(ScaleX(520), ScaleY(220), False, True);
  try
    ConfirmForm.Caption := '卸载 Vision MCP';
    ConfirmForm.Color := $00FCFBFA;
    ConfirmForm.Font.Name := 'Microsoft YaHei UI';
    ConfirmForm.Font.Size := 9;

    BrandLabel := TNewStaticText.Create(ConfirmForm);
    BrandLabel.Parent := ConfirmForm;
    BrandLabel.Left := ScaleX(20);
    BrandLabel.Top := ScaleY(18);
    BrandLabel.Width := ScaleX(28);
    BrandLabel.Height := ScaleY(28);
    BrandLabel.AutoSize := False;
    BrandLabel.Alignment := taCenter;
    BrandLabel.Caption := 'X';
    BrandLabel.Font.Name := 'Microsoft YaHei UI';
    BrandLabel.Font.Size := 15;
    BrandLabel.Font.Style := [fsBold];
    BrandLabel.Font.Color := $003E5AB5;

    TitleLabel := TNewStaticText.Create(ConfirmForm);
    TitleLabel.Parent := ConfirmForm;
    TitleLabel.Left := ScaleX(56);
    TitleLabel.Top := ScaleY(18);
    TitleLabel.Width := ScaleX(440);
    TitleLabel.Caption := '卸载 Vision MCP';
    TitleLabel.Font.Name := 'Microsoft YaHei UI';
    TitleLabel.Font.Size := 13;
    TitleLabel.Font.Style := [fsBold];
    TitleLabel.Font.Color := $002B2927;

    InfoLabel := TNewStaticText.Create(ConfirmForm);
    InfoLabel.Parent := ConfirmForm;
    InfoLabel.Left := ScaleX(56);
    InfoLabel.Top := ScaleY(48);
    InfoLabel.Width := ScaleX(440);
    InfoLabel.AutoSize := False;
    InfoLabel.WordWrap := True;
    InfoLabel.Caption := '继续卸载后，将移除程序以及由本次安装创建的 Agent 配置。';
    InfoLabel.Font.Color := $006A625C;

    DeleteDataCheck := TNewCheckBox.Create(ConfirmForm);
    DeleteDataCheck.Parent := ConfirmForm;
    DeleteDataCheck.Left := ScaleX(56);
    DeleteDataCheck.Top := ScaleY(88);
    DeleteDataCheck.Width := ScaleX(440);
    DeleteDataCheck.Height := ScaleY(24);
    DeleteDataCheck.Caption := '同时删除个人数据';
    DeleteDataCheck.Checked := False;

    DeleteDataNote := TNewStaticText.Create(ConfirmForm);
    DeleteDataNote.Parent := ConfirmForm;
    DeleteDataNote.Left := ScaleX(78);
    DeleteDataNote.Top := ScaleY(115);
    DeleteDataNote.Width := ScaleX(418);
    DeleteDataNote.Height := ScaleY(34);
    DeleteDataNote.AutoSize := False;
    DeleteDataNote.WordWrap := True;
    DeleteDataNote.Caption := '包括模型配置、Windows 凭据、迁移文件和 Agent 配置备份。默认保留这些内容。';
    DeleteDataNote.Font.Size := 8;
    DeleteDataNote.Font.Color := $00857C75;

    ContinueButton := TNewButton.Create(ConfirmForm);
    ContinueButton.Parent := ConfirmForm;
    ContinueButton.Caption := '继续卸载';
    ContinueButton.Left := ScaleX(394);
    ContinueButton.Top := ScaleY(170);
    ContinueButton.Width := ScaleX(102);
    ContinueButton.Height := ScaleY(32);
    ContinueButton.ModalResult := mrOk;
    ContinueButton.Default := True;
    ContinueButton.Font.Style := [fsBold];

    CancelButton := TNewButton.Create(ConfirmForm);
    CancelButton.Parent := ConfirmForm;
    CancelButton.Caption := '取消';
    CancelButton.Left := ScaleX(302);
    CancelButton.Top := ScaleY(170);
    CancelButton.Width := ScaleX(82);
    CancelButton.Height := ScaleY(32);
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;

    if ConfirmForm.ShowModal = mrOk then
    begin
      DeletePersonalData := DeleteDataCheck.Checked;
      Result := PrepareUninstallCleanup();
      if not Result then
        MsgBox(
          '无法安全停止正在运行的 Vision MCP，或无法移除 Agent 配置。' + #13#10 +
          '请关闭正在使用 Vision MCP 的 Agent 后重试。',
          mbError, MB_OK
        );
    end;
  finally
    ConfirmForm.Free;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usUninstall) and DeletePersonalData then
    Exec(ExpandConstant('{app}\{#MyAppExeName}'), '--maintenance purge-data', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if (CurUninstallStep = usPostUninstall) and DeletePersonalData then
  begin
    DelTree(ExpandConstant('{userappdata}\VisionMCP'), True, True, True);
    DelTree(ExpandConstant('{localappdata}\VisionMCP'), True, True, True);
  end;
end;
