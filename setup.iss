; Smart Zones Pro — Inno Setup script
; Paths are resolved relative to this .iss file via {#SourcePath}, so the repo
; can live anywhere on the build machine (no more hardcoded D:\smart-zones-pro).

#define RepoDir SourcePath

[Setup]
AppName=Smart Zones Pro
AppVersion=1.0
DefaultDirName={autopf}\SmartZonesPro
DefaultGroupName=Smart Zones Pro
UninstallDisplayIcon={app}\SmartZonesPro.exe
Compression=lzma2
SolidCompression=yes
OutputDir={#RepoDir}Output
OutputBaseFilename=SmartZonesPro_Setup

[Files]
; IMPORTANT: place your splash image as "splash_image.bmp" in the repo root.
Source: "{#RepoDir}splash_image.bmp"; DestDir: "{tmp}"; Flags: dontcopy
Source: "{#RepoDir}dist\SmartZonesPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoDir}.env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoDir}mql\MT4\Experts\*"; DestDir: "{app}\mql\MT4\Experts"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoDir}mql\MT4\Indicators\*"; DestDir: "{app}\mql\MT4\Indicators"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoDir}mql\MT5\Experts\*"; DestDir: "{app}\mql\MT5\Experts"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#RepoDir}mql\MT5\Indicators\*"; DestDir: "{app}\mql\MT5\Indicators"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\Smart Zones Pro"; Filename: "{app}\SmartZonesPro.exe"
Name: "{autodesktop}\Smart Zones Pro"; Filename: "{app}\SmartZonesPro.exe"
Name: "{userstartup}\Smart Zones Pro"; Filename: "{app}\SmartZonesPro.exe"; Tasks: autostart

[Tasks]
Name: "autostart"; Description: "Start Smart Zones Pro automatically with Windows"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\SmartZonesPro.exe"; Description: "Launch Smart Zones Pro"; Flags: nowait postinstall skipifsilent

[Code]
var
  SplashForm: TSetupForm;
  SplashImage: TBitmapImage;
  SplashLabel: TLabel;

procedure ShowSplashScreen;
begin
  // Извлекаем картинку
  ExtractTemporaryFile('splash_image.bmp');
  
  // Создаем невидимое окно без рамок
  SplashForm := CreateCustomForm;
  SplashForm.BorderStyle := bsNone;
  SplashForm.Position := poScreenCenter;
  SplashForm.ClientWidth := 600;
  SplashForm.ClientHeight := 400;
  SplashForm.Color := clBlack;
  
  // Растягиваем нужную картинку
  SplashImage := TBitmapImage.Create(SplashForm);
  SplashImage.Parent := SplashForm;
  try
    SplashImage.Bitmap.LoadFromFile(ExpandConstant('{tmp}\splash_image.bmp'));
  except
    // Если картинки нет, форма просто будет черной
  end;
  SplashImage.SetBounds(0, 0, SplashForm.ClientWidth, SplashForm.ClientHeight);
  SplashImage.Stretch := True;
  
  // Пишем текст "for Yerassyl Uzakhbayev"
  SplashLabel := TLabel.Create(SplashForm);
  SplashLabel.Parent := SplashForm;
  SplashLabel.Caption := 'for Yerassyl Uzakhbayev';
  SplashLabel.Font.Size := 16;
  SplashLabel.Font.Style := [fsBold];
  SplashLabel.Font.Color := clWhite;
  SplashLabel.Transparent := True;
  // Центрируем внизу
  SplashLabel.Left := (SplashForm.ClientWidth - 250) / 2;
  SplashLabel.Top := SplashForm.ClientHeight - 50;
  
  SplashForm.Show;
  SplashForm.Repaint;
  
  // Показываем сравнительно коротко (прежние 5с выглядят как зависание)
  Sleep(2000);
  
  SplashForm.Close;
  SplashForm.Free;
end;

procedure InitializeWizard;
begin
  ShowSplashScreen;
end;
