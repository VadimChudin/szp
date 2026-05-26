[Setup]
AppName=Smart Zones Pro
AppVersion=1.0
DefaultDirName={autopf}\SmartZonesPro
DefaultGroupName=Smart Zones Pro
UninstallDisplayIcon={app}\SmartZonesPro.exe
Compression=lzma2
SolidCompression=yes
OutputDir=d:\smart-zones-pro\Output
OutputBaseFilename=SmartZonesPro_Setup

[Files]
; IMPORTANT: User must place their specific image as "splash_image.bmp" in the project root!
Source: "d:\smart-zones-pro\splash_image.bmp"; DestDir: "{tmp}"; Flags: dontcopy
Source: "d:\smart-zones-pro\dist\SmartZonesPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "d:\smart-zones-pro\mql\MT4\Experts\*"; DestDir: "{app}\mql\MT4\Experts"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "d:\smart-zones-pro\mql\MT4\Indicators\*"; DestDir: "{app}\mql\MT4\Indicators"; Flags: ignoreversion recursesubdirs createallsubdirs

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
  
  // Держим картинку 5 секунд
  Sleep(5000);
  
  SplashForm.Close;
  SplashForm.Free;
end;

procedure InitializeWizard;
begin
  ShowSplashScreen;
end;
