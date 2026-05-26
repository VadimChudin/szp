; ──────────────────────────────────────────────────────────────────────
;  Smart Zones Pro v1.0 — Inno Setup Installer
;  Профессиональный инсталлятор. 1 кнопка = всё работает.
; ──────────────────────────────────────────────────────────────────────

#define MyAppName "Smart Zones Pro"
#define MyAppVersion "1.0"
#define MyAppPublisher "Smart Zones Trading"
#define MyAppURL "https://smartzonespro.com"
#define MyAppExeName "SmartZonesPro.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; Визуальный стиль
WizardStyle=modern
WizardSizePercent=120
; Картинки инсталлятора (164x314 px для большой, 55x58 для маленькой)
WizardImageFile=d:\smart-zones-pro\splash_image.bmp
; WizardSmallImageFile=wizard_icon.bmp
; SetupIconFile=app_icon.ico
OutputDir=d:\smart-zones-pro\installer\output
OutputBaseFilename=SmartZonesPro_Setup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
LicenseFile=
MinVersion=10.0

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
russian.WelcomeLabel2=Это установит {#MyAppName} v{#MyAppVersion} на ваш компьютер.%n%nSmart Zones Pro — профессиональный индикатор для MetaTrader 4/5, который автоматически определяет сильные зоны поддержки и сопротивления на XAU/USD.%n%nПосле установки на рабочем столе появится ярлык SZP.%nВсе подсистемы запускаются по 1 кнопке в фоновом режиме.%n%nРекомендуется закрыть MetaTrader перед установкой.

[Types]
Name: "full"; Description: "Полная установка (рекомендуется)"
Name: "custom"; Description: "Выборочная установка"; Flags: iscustom

[Components]
Name: "core"; Description: "Smart Zones Pro (ядро + мост + футпринт)"; Types: full custom; Flags: fixed
Name: "mt4"; Description: "Индикатор и EA для MetaTrader 4"; Types: full custom
Name: "mt5"; Description: "Индикатор для MetaTrader 5"; Types: full custom
Name: "autostart"; Description: "Автозапуск при включении Windows"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе (SZP)"; GroupDescription: "Дополнительно:"

[Files]
; Ядро (Python, упакованное PyInstaller — БЕЗ консоли)
Source: "d:\smart-zones-pro\installer\build\dist\SmartZonesPro\*"; DestDir: "{app}"; Components: core; Flags: ignoreversion recursesubdirs createallsubdirs

; MQL4 файлы (будут установлены в MT4 автоматически при первом запуске)
Source: "d:\smart-zones-pro\mql\MT4\Indicators\StrongZones.mq4"; DestDir: "{app}\mql\MT4\Indicators"; Components: mt4; Flags: ignoreversion
Source: "d:\smart-zones-pro\mql\MT4\Experts\SmartZonesCollector.mq4"; DestDir: "{app}\mql\MT4\Experts"; Components: mt4; Flags: ignoreversion

; MQL5 файлы
Source: "d:\smart-zones-pro\mql\MT5\Indicators\StrongZones.mq5"; DestDir: "{app}\mql\MT5\Indicators"; Components: mt5; Flags: ignoreversion

[Icons]
; Ярлык на рабочем столе — "SZP"
Name: "{autodesktop}\SZP"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "Smart Zones Pro"
; Меню Пуск
Name: "{group}\Smart Zones Pro"; Filename: "{app}\{#MyAppExeName}"; Comment: "Запустить Smart Zones Pro"
Name: "{group}\Удалить Smart Zones Pro"; Filename: "{uninstallexe}"
; Автозапуск
Name: "{userstartup}\Smart Zones Pro"; Filename: "{app}\{#MyAppExeName}"; Components: autostart; Comment: "Smart Zones Pro автозапуск"

[Run]
; После установки — предложить запустить
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить Smart Zones Pro сейчас"; Flags: nowait postinstall skipifsilent

[Code]
// ── Автоматическая установка индикаторов в MT4/MT5 ────────────────
procedure PatchTerminals();
var
  TerminalBase: String;
  SearchRec: TFindRec;
  SourceMQ4Ind, SourceMQ4EA, SourceMQ5Ind: String;
  DestDir: String;
begin
  TerminalBase := ExpandConstant('{userappdata}') + '\MetaQuotes\Terminal';
  SourceMQ4Ind := ExpandConstant('{app}') + '\mql\MT4\Indicators\StrongZones.mq4';
  SourceMQ4EA := ExpandConstant('{app}') + '\mql\MT4\Experts\SmartZonesCollector.mq4';
  SourceMQ5Ind := ExpandConstant('{app}') + '\mql\MT5\Indicators\StrongZones.mq5';
  
  if not DirExists(TerminalBase) then
  begin
    Log('MetaTrader terminal directory not found');
    Exit;
  end;
  
  if FindFirst(TerminalBase + '\*', SearchRec) then
  begin
    try
      repeat
        if (SearchRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
        begin
          if (SearchRec.Name <> '.') and (SearchRec.Name <> '..') then
          begin
            // MT4
            DestDir := TerminalBase + '\' + SearchRec.Name + '\MQL4\Indicators';
            if DirExists(DestDir) and IsComponentSelected('mt4') then
            begin
              FileCopy(SourceMQ4Ind, DestDir + '\StrongZones.mq4', False);
              Log('MT4 Indicator installed to: ' + DestDir);
            end;
            
            DestDir := TerminalBase + '\' + SearchRec.Name + '\MQL4\Experts';
            if DirExists(DestDir) and IsComponentSelected('mt4') then
            begin
              FileCopy(SourceMQ4EA, DestDir + '\SmartZonesCollector.mq4', False);
              Log('MT4 EA installed to: ' + DestDir);
            end;
            
            // MT5
            DestDir := TerminalBase + '\' + SearchRec.Name + '\MQL5\Indicators';
            if DirExists(DestDir) and IsComponentSelected('mt5') then
            begin
              FileCopy(SourceMQ5Ind, DestDir + '\StrongZones.mq5', False);
              Log('MT5 Indicator installed to: ' + DestDir);
            end;
          end;
        end;
      until not FindNext(SearchRec);
    finally
      FindClose(SearchRec);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    PatchTerminals();
end;

[UninstallDelete]
Type: filesandordirs; Name: "{app}\mql"
Type: filesandordirs; Name: "{app}\data"
Type: files; Name: "{app}\*.log"
