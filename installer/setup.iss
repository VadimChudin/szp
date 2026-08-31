; ──────────────────────────────────────────────────────────────────────
;  Smart Zones Pro v1.0 — Inno Setup Installer
;  Профессиональный инсталлятор. 1 кнопка = всё работает.
; ──────────────────────────────────────────────────────────────────────

#define MyAppName "Smart Zones Pro"
#define MyAppVersion "1.0"
#define MyAppPublisher "Smart Zones Trading"
#define MyAppURL "https://smartzonespro.com"
#define MyAppExeName "SmartZonesPro.exe"
; Корень репо относительно этого .iss (работает из любой папки).
#define RepoDir SourcePath + "..\"

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
WizardImageFile={#RepoDir}splash_image.bmp
; WizardSmallImageFile=wizard_icon.bmp
; SetupIconFile=app_icon.ico
OutputDir={#SourcePath}output
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
Source: "{#SourcePath}build\dist\SmartZonesPro\*"; DestDir: "{app}"; Components: core; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoDir}.env.example"; DestDir: "{app}"; Components: core; Flags: ignoreversion

; MQL4 файлы (будут установлены в MT4 автоматически при первом запуске)
Source: "{#RepoDir}mql\MT4\Indicators\StrongZones.mq4"; DestDir: "{app}\mql\MT4\Indicators"; Components: mt4; Flags: ignoreversion
Source: "{#RepoDir}mql\MT4\Experts\SmartZonesCollector.mq4"; DestDir: "{app}\mql\MT4\Experts"; Components: mt4; Flags: ignoreversion

; MQL5 файлы
Source: "{#RepoDir}mql\MT5\Indicators\StrongZones.mq5"; DestDir: "{app}\mql\MT5\Indicators"; Components: mt5; Flags: ignoreversion
Source: "{#RepoDir}mql\MT5\Experts\SmartZonesCollector.mq5"; DestDir: "{app}\mql\MT5\Experts"; Components: mt5; Flags: ignoreversion skipifsourcedoesntexist
; Скомпилированные бинарники из CI: с .ex5 индикатор появляется в Навигаторе
; сразу, без ожидания авто-компиляции терминалом (которая на части машин
; молча не срабатывает — клиент видел пустой Навигатор после установки).
Source: "{#RepoDir}mql\MT5\Indicators\StrongZones.ex5"; DestDir: "{app}\mql\MT5\Indicators"; Components: mt5; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#RepoDir}mql\MT5\Experts\SmartZonesCollector.ex5"; DestDir: "{app}\mql\MT5\Experts"; Components: mt5; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#RepoDir}mql\MT4\Indicators\StrongZones.ex4"; DestDir: "{app}\mql\MT4\Indicators"; Components: mt4; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#RepoDir}mql\MT4\Experts\SmartZonesCollector.ex4"; DestDir: "{app}\mql\MT4\Experts"; Components: mt4; Flags: ignoreversion skipifsourcedoesntexist

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
  SourceDir, DestDir: String;
  Found: Boolean;
  Failed: Integer;

  // Копирует индикатор/EA в папку терминала: и исходник (.mq5 — для
  // перекомпиляции в MetaEditor), и бинарник (.ex5 — чтобы индикатор был в
  // Навигаторе сразу, не дожидаясь авто-компиляции терминала).
  procedure InstallPair(const DestDir, Base, SrcExt, BinExt: String);
  begin
    // Папки могут ещё не существовать (терминал ни разу не запускали) —
    // создаём сами, иначе файлы молча не копировались.
    if not DirExists(DestDir) then
      ForceDirectories(DestDir);
    // FileCopy при ЗАПУЩЕННОМ терминале может молча не заменить занятый
    // .ex4/.ex5 — и клиент навсегда остаётся на старом бинарнике (реальный
    // кейс: новая версия установлена, а терминал показывает старое).
    // Считаем провалы и покажем их в конце установки.
    if FileExists(SourceDir + '\' + Base + SrcExt) then
      if not FileCopy(SourceDir + '\' + Base + SrcExt, DestDir + '\' + Base + SrcExt, False) then
        Failed := Failed + 1;
    if FileExists(SourceDir + '\' + Base + BinExt) then
      if not FileCopy(SourceDir + '\' + Base + BinExt, DestDir + '\' + Base + BinExt, False) then
        Failed := Failed + 1;
    Log('Installed ' + Base + ' to: ' + DestDir);
  end;

begin
  TerminalBase := ExpandConstant('{userappdata}') + '\MetaQuotes\Terminal';
  SourceDir := ExpandConstant('{app}') + '\mql';
  Found := False;
  Failed := 0;

  if not DirExists(TerminalBase) then
  begin
    Log('MetaTrader terminal directory not found');
  end
  else if FindFirst(TerminalBase + '\*', SearchRec) then
  begin
    try
      repeat
        if ((SearchRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0)
           and (SearchRec.Name <> '.') and (SearchRec.Name <> '..') then
        begin
          if IsComponentSelected('mt4') then
          begin
            DestDir := TerminalBase + '\' + SearchRec.Name + '\MQL4\Indicators';
            if DirExists(TerminalBase + '\' + SearchRec.Name + '\MQL4') then
            begin
              InstallPair(DestDir, 'StrongZones', '.mq4', '.ex4');
              InstallPair(TerminalBase + '\' + SearchRec.Name + '\MQL4\Experts',
                          'SmartZonesCollector', '.mq4', '.ex4');
              Found := True;
            end;
          end;

          if IsComponentSelected('mt5') then
          begin
            if DirExists(TerminalBase + '\' + SearchRec.Name + '\MQL5') then
            begin
              InstallPair(TerminalBase + '\' + SearchRec.Name + '\MQL5\Indicators',
                          'StrongZones', '.mq5', '.ex5');
              InstallPair(TerminalBase + '\' + SearchRec.Name + '\MQL5\Experts',
                          'SmartZonesCollector', '.mq5', '.ex5');
              Found := True;
            end;
          end;
        end;
      until not FindNext(SearchRec);
    finally
      FindClose(SearchRec);
    end;
  end;

  if Failed > 0 then
    MsgBox('Не удалось заменить ' + IntToStr(Failed) + ' файл(ов) индикатора — они заняты РАБОТАЮЩИМ терминалом.' + #13#10#13#10 +
           'Сделайте так: 1) полностью закройте MetaTrader, 2) запустите установку ещё раз.' + #13#10 +
           'Иначе терминал продолжит показывать СТАРУЮ версию.',
           mbCriticalError, MB_OK);

  if not Found then
    // Раньше установка молча завершалась без индикаторов, и клиент не
    // понимал, почему Навигатор пуст. Теперь говорим прямо.
    MsgBox('MetaTrader 4/5 не найден на этом компьютере (нет папки данных в %APPDATA%\MetaQuotes\Terminal).' + #13#10#13#10 +
           'Индикаторы НЕ установлены. Установите/запустите терминал, затем:' + #13#10 +
           '1. Переустановите Smart Zones Pro, ИЛИ' + #13#10 +
           '2. Скопируйте вручную из папки установки Smart Zones Pro\mql\... в ' +
           'каталог данных терминала (Файл → Открыть каталог данных) → MQL5\Indicators и MQL5\Experts,' + #13#10 +
           '3. В терминале: Навигатор → Обновить (F5).',
           mbInformation, MB_OK);
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
