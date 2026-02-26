#ifexist "app_meta.iss"
  #include "app_meta.iss"
#else
  #define AppName "Cheating Mommy"
  #define AppVersion "1.2.1"
#endif

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={commonpf}\{#AppName}
DefaultGroupName={#AppName}
OutputBaseFilename={#AppName}_{#AppVersion}_installer
Compression=lzma
SolidCompression=yes

[Files]
; Main app folder
Source: "dist\{#AppName}.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\{#AppName}_console.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: "config_guide.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "crop_region.exe"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "update_credentials.exe"; DestDir: "{app}\tools"; Flags: ignoreversion

; Tesseract to AppData
Source: "tesseract\*"; DestDir: "{code:GetDataDir}\tesseract"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "credentials_template.txt"; DestDir: "{code:GetDataDir}"; DestName: "credentials.txt"; Flags: ignoreversion onlyifdoesntexist

[Tasks]
Name: "desktop_main"; Description: "Create Desktop shortcut for {#AppName}"
Name: "desktop_update"; Description: "Create Desktop shortcut for Update Credentials(used for login)"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{group}\{#AppName} Console"; Filename: "{app}\{#AppName}_console.exe"
Name: "{group}\Update Credentials"; Filename: "{app}\tools\update_credentials.exe"
Name: "{group}\Crop Region"; Filename: "{app}\tools\crop_region.exe"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktop_main
Name: "{commondesktop}\Update Credentials"; Filename: "{app}\tools\update_credentials.exe"; Tasks: desktop_update

[Run]
; Optional: launch app after install
; Filename: "{app}\{#AppName}.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  ModePage: TWizardPage;
  DefaultRadio: TRadioButton;
  AdvancedRadio: TRadioButton;
  ModeInfoLabel: TLabel;
  DataDirPage: TInputDirWizardPage;
  ChosenDataDir: string;

function IsAdvancedInstall: Boolean;
begin
  Result := Assigned(AdvancedRadio) and AdvancedRadio.Checked;
end;

function GetDataDir(Param: string): string;
begin
  if ChosenDataDir = '' then
    Result := ExpandConstant('{userappdata}\{#AppName}')
  else
    Result := ChosenDataDir;
end;

procedure InitializeWizard;
begin
  ModePage := CreateCustomPage(
    wpWelcome,
    'Install Mode',
    'Choose how you want to install {#AppName}.'
  );

  DefaultRadio := TRadioButton.Create(ModePage);
  DefaultRadio.Parent := ModePage.Surface;
  DefaultRadio.Left := ScaleX(0);
  DefaultRadio.Top := ScaleY(8);
  DefaultRadio.Width := ModePage.SurfaceWidth;
  DefaultRadio.Caption := 'Default (Recommended)';
  DefaultRadio.Checked := True;

  AdvancedRadio := TRadioButton.Create(ModePage);
  AdvancedRadio.Parent := ModePage.Surface;
  AdvancedRadio.Left := ScaleX(0);
  AdvancedRadio.Top := ScaleY(32);
  AdvancedRadio.Width := ModePage.SurfaceWidth;
  AdvancedRadio.Caption := 'Advanced';

  ModeInfoLabel := TLabel.Create(ModePage);
  ModeInfoLabel.Parent := ModePage.Surface;
  ModeInfoLabel.Left := ScaleX(0);
  ModeInfoLabel.Top := ScaleY(62);
  ModeInfoLabel.Width := ModePage.SurfaceWidth;
  ModeInfoLabel.Height := ScaleY(70);
  ModeInfoLabel.WordWrap := True;
  ModeInfoLabel.Caption :=
    'Default installs in default directories.' + #13#10 +
    'Advanced lets you choose directories.';

  DataDirPage := CreateInputDirPage(
    wpSelectDir,
    'Data Location',
    'Choose where app data will be stored',
    'Select the directory for credentials and bundled tesseract files.',
    False,
    ''
  );
  DataDirPage.Add('');
  DataDirPage.Values[0] := ExpandConstant('{userappdata}\{#AppName}');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = wpSelectDir then
    Result := not IsAdvancedInstall
  else if Assigned(DataDirPage) and (PageID = DataDirPage.ID) then
    Result := not IsAdvancedInstall;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = ModePage.ID then
  begin
    if not IsAdvancedInstall then
    begin
      WizardForm.DirEdit.Text := ExpandConstant('{commonpf}\{#AppName}');
      ChosenDataDir := ExpandConstant('{userappdata}\{#AppName}');
    end;
  end
  else if Assigned(DataDirPage) and (CurPageID = DataDirPage.ID) then
  begin
    ChosenDataDir := DataDirPage.Values[0];
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  DataDirFile: string;
begin
  if CurStep = ssPostInstall then
  begin
    DataDirFile := ExpandConstant('{app}\data_dir.txt');
    SaveStringToFile(DataDirFile, GetDataDir('') + #13#10, False);
  end;
end;
