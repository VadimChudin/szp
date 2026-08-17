; Smart Zones Pro — Inno Setup script
; Paths are resolved relative to this .iss file via {#SourcePath}, so the repo
; can live anywhere on the build machine (no more hardcoded D:\smart-zones-pro).

#define RepoDir SourcePath

; Версия сборки: CI передаёт её как /DAppVer=1.5. Раньше номер был захардкожен
; и все установщики выглядели как 1.1 — клиент не мог отличить новую сборку от
; старой, а мы не могли проверить, что у него стоит.
#ifndef AppVer
  #define AppVer "dev"
#endif
#ifndef AppChannel
  #define AppChannel "Stable"
#endif
#if AppChannel == "Experimental"
  #define ChannelAppId "{{A1B2C3D4-5E6F-47A8-9B0C-1D2E3F4A5B6C}"
#else
  #define ChannelAppId "{{7B4C9E2A-3F1D-4A6B-9C2E-5D8F0A1B2C3D}"
#endif

[Setup]
AppId={#ChannelAppId}
AppName=Smart Zones Pro {#AppChannel}
AppVersion={#AppVer}
AppVerName=Smart Zones Pro {#AppChannel} {#AppVer}
DefaultDirName={autopf}\SmartZonesPro\{#AppChannel}
DefaultGroupName=Smart Zones Pro {#AppChannel}
UninstallDisplayIcon={app}\SmartZonesPro.exe
Compression=lzma2
SolidCompression=yes
OutputDir={#RepoDir}Output
OutputBaseFilename=SmartZonesPro_Setup_{#AppChannel}_v{#AppVer}

[Files]
Source: "{#RepoDir}dist\SmartZonesPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoDir}.env.example"; DestDir: "{app}"; Flags: ignoreversion
; Исходники сохраняем для аудита, а исполняемые ex4/ex5 ставим в терминал.
Source: "{#RepoDir}mql\MT4\Experts\*.mq4"; DestDir: "{app}\mql\MT4\Experts"; Flags: ignoreversion
Source: "{#RepoDir}mql\MT4\Indicators\*.mq4"; DestDir: "{app}\mql\MT4\Indicators"; Flags: ignoreversion
Source: "{#RepoDir}mql\MT5\Experts\*.mq5"; DestDir: "{app}\mql\MT5\Experts"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#RepoDir}mql\MT5\Indicators\*.mq5"; DestDir: "{app}\mql\MT5\Indicators"; Flags: ignoreversion skipifsourcedoesntexist
; Эти артефакты создаются CI до запуска ISCC; без них обновление не считается валидным.
Source: "{#RepoDir}mql\MT4\Experts\*.ex4"; DestDir: "{app}\mql\MT4\Experts"; Flags: ignoreversion
Source: "{#RepoDir}mql\MT4\Indicators\*.ex4"; DestDir: "{app}\mql\MT4\Indicators"; Flags: ignoreversion
Source: "{#RepoDir}mql\MT5\Experts\*.ex5"; DestDir: "{app}\mql\MT5\Experts"; Flags: ignoreversion
Source: "{#RepoDir}mql\MT5\Indicators\*.ex5"; DestDir: "{app}\mql\MT5\Indicators"; Flags: ignoreversion

[Icons]
Name: "{group}\Smart Zones Pro {#AppChannel}"; Filename: "{app}\SmartZonesPro.exe"
Name: "{autodesktop}\Smart Zones Pro {#AppChannel}"; Filename: "{app}\SmartZonesPro.exe"
Name: "{userstartup}\Smart Zones Pro"; Filename: "{app}\SmartZonesPro.exe"; Tasks: autostart

[Tasks]
Name: "autostart"; Description: "Start Smart Zones Pro automatically with Windows"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\SmartZonesPro.exe"; Description: "Launch Smart Zones Pro"; Flags: nowait postinstall skipifsilent

; Сплэш с подписью "NoName Trader" показывает само приложение при
; запуске (см. show_splash в app_entry.py). В установщике своя форма-сплэш
; убрана: её API ломался на новых версиях Inno Setup ("Invalid number of
; parameters"), а персонализация всё равно дублировалась.

[Code]
{ ── Доставка скомпилированных MQL-компонентов в терминалы ───────────────
   Папка канала преднамеренно входит в путь. Так Experimental не перезаписывает
   Stable, а терминал не может молча продолжить выполнять старый StrongZones.ex?. }
procedure CopyCompiledMql(const SourceFile, DestDir, DestName: String);
begin
  if not FileExists(SourceFile) then
  begin
    Log('Compiled MQL payload is missing: ' + SourceFile);
    Exit;
  end;

  if not ForceDirectories(DestDir) then
  begin
    Log('Cannot create MetaTrader destination: ' + DestDir);
    Exit;
  end;

  if FileCopy(SourceFile, AddBackslash(DestDir) + DestName, False) then
    Log('Installed compiled MQL: ' + AddBackslash(DestDir) + DestName)
  else
    Log('Failed to install compiled MQL: ' + AddBackslash(DestDir) + DestName);
end;

procedure InstallCompiledMqlToTerminals();
var
  TerminalBase, TerminalDir: String;
  SearchRec: TFindRec;
  MT4Indicator, MT4Expert, MT5Indicator, MT5Expert: String;
begin
  TerminalBase := ExpandConstant('{userappdata}') + '\MetaQuotes\Terminal';
  if not DirExists(TerminalBase) then
  begin
    Log('MetaTrader terminal directory not found: ' + TerminalBase);
    Exit;
  end;

  MT4Indicator := ExpandConstant('{app}') + '\mql\MT4\Indicators\StrongZones.ex4';
  MT4Expert    := ExpandConstant('{app}') + '\mql\MT4\Experts\SmartZonesCollector.ex4';
  MT5Indicator := ExpandConstant('{app}') + '\mql\MT5\Indicators\StrongZones.ex5';
  MT5Expert    := ExpandConstant('{app}') + '\mql\MT5\Experts\SmartZonesCollector.ex5';

  if FindFirst(TerminalBase + '\*', SearchRec) then
  begin
    try
      repeat
        if ((SearchRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and
           (SearchRec.Name <> '.') and (SearchRec.Name <> '..') then
        begin
          TerminalDir := TerminalBase + '\' + SearchRec.Name;
          if DirExists(TerminalDir + '\MQL4') then
          begin
            CopyCompiledMql(MT4Indicator, TerminalDir + '\MQL4\Indicators\SmartZonesPro\{#AppChannel}', 'StrongZones.ex4');
            CopyCompiledMql(MT4Expert, TerminalDir + '\MQL4\Experts\SmartZonesPro\{#AppChannel}', 'SmartZonesCollector.ex4');
          end;
          if DirExists(TerminalDir + '\MQL5') then
          begin
            CopyCompiledMql(MT5Indicator, TerminalDir + '\MQL5\Indicators\SmartZonesPro\{#AppChannel}', 'StrongZones.ex5');
            CopyCompiledMql(MT5Expert, TerminalDir + '\MQL5\Experts\SmartZonesPro\{#AppChannel}', 'SmartZonesCollector.ex5');
          end;
        end;
      until not FindNext(SearchRec);
    finally
      FindClose(SearchRec);
    end;
  end;
end;

{ ── Удаление предыдущих версий перед установкой ─────────────────────────
  Клиент мог поставить старую версию в нестандартный путь. Ищем её
  деинсталлятор в реестре (по AppId новой версии и по имени старой, у которой
  AppId ещё не было) и запускаем в тихом режиме. Также закрываем запущенное
  приложение, иначе файлы заблокированы и обновление не встанет. }

function GetUninstallString(const SubKey: String): String;
var
  S: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + SubKey, 'UninstallString', S) then
    Result := S
  else if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + SubKey, 'UninstallString', S) then
    Result := S
  else if RegQueryStringValue(HKLM, 'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\' + SubKey, 'UninstallString', S) then
    Result := S;
end;

procedure RunUninstaller(const SubKey: String);
var
  UninstStr: String;
  ResultCode: Integer;
begin
  UninstStr := GetUninstallString(SubKey);
  if UninstStr <> '' then
  begin
    UninstStr := RemoveQuotes(UninstStr);
    Exec(UninstStr, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '',
         SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(1500);
  end;
end;

{ ── Проверка/установка системных зависимостей ───────────────────────────
  На «чистых» ПК приложение может не стартовать, т.к. не хватает:
    1) Microsoft Visual C++ Redistributable (нужен рантайму Python/PyInstaller);
    2) Microsoft Edge WebView2 Runtime (нужен окну футпринта на pywebview).
  Проверяем реестр и, если чего-то нет, тихо докачиваем и ставим. Ошибки
  не фатальны — установка приложения продолжается в любом случае. }

function VCRedistInstalled(): Boolean;
var
  Installed: Cardinal;
begin
  Result := False;
  if RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) then
    Result := (Installed = 1)
  else if RegQueryDWordValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) then
    Result := (Installed = 1);
end;

function WebView2Installed(): Boolean;
var
  S: String;
begin
  Result := False;
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', S) then
    Result := (S <> '') and (S <> '0.0.0.0')
  else if RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', S) then
    Result := (S <> '') and (S <> '0.0.0.0')
  else if RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', S) then
    Result := (S <> '') and (S <> '0.0.0.0');
end;

procedure DownloadAndRun(const Url, FileName, Args: String);
var
  Dest: String;
  ResultCode: Integer;
begin
  Dest := ExpandConstant('{tmp}\') + FileName;
  try
    DownloadTemporaryFile(Url, FileName, '', nil);
    if FileExists(Dest) then
      Exec(Dest, Args, '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
  except
    { Нет интернета / сбой загрузки — не блокируем установку приложения. }
  end;
end;

procedure EnsurePrerequisites();
begin
  if not VCRedistInstalled() then
    DownloadAndRun('https://aka.ms/vs/17/release/vc_redist.x64.exe',
                   'vc_redist.x64.exe', '/install /quiet /norestart');
  if not WebView2Installed() then
    DownloadAndRun('https://go.microsoft.com/fwlink/p/?LinkId=2124703',
                   'MicrosoftEdgeWebview2Setup.exe', '/silent /install');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    { Закрываем запущенное приложение (автозапуск/трей). }
    Exec(ExpandConstant('{cmd}'), '/C taskkill /IM SmartZonesPro.exe /F', '',
         SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(800);
    { Сносим только предыдущую версию текущего канала. }
#if AppChannel == "Experimental"
    RunUninstaller('{A1B2C3D4-5E6F-47A8-9B0C-1D2E3F4A5B6C}_is1');
#else
    RunUninstaller('{7B4C9E2A-3F1D-4A6B-9C2E-5D8F0A1B2C3D}_is1');
#endif
#if AppChannel == "Stable"
    { Однократно удаляем старую версию до введения каналов. }
    RunUninstaller('Smart Zones Pro_is1');
#endif
  end
  else if CurStep = ssPostInstall then
  begin
    { Ставим недостающие системные зависимости (VC++ / WebView2) и
      разворачиваем именно CI-скомпилированные ex4/ex5 в изолированный
      каталог канала внутри каждого найденного терминала. }
    EnsurePrerequisites();
    InstallCompiledMqlToTerminals();
  end;
end;
