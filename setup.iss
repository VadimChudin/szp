; Smart Zones Pro — Inno Setup script
; Paths are resolved relative to this .iss file via {#SourcePath}, so the repo
; can live anywhere on the build machine (no more hardcoded D:\smart-zones-pro).

#define RepoDir SourcePath

[Setup]
AppId={{7B4C9E2A-3F1D-4A6B-9C2E-5D8F0A1B2C3D}
AppName=Smart Zones Pro
AppVersion=1.1
DefaultDirName={autopf}\SmartZonesPro
DefaultGroupName=Smart Zones Pro
UninstallDisplayIcon={app}\SmartZonesPro.exe
Compression=lzma2
SolidCompression=yes
OutputDir={#RepoDir}Output
OutputBaseFilename=SmartZonesPro_Setup

[Files]
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

; Сплэш с подписью "NoName Trader" показывает само приложение при
; запуске (см. show_splash в app_entry.py). В установщике своя форма-сплэш
; убрана: её API ломался на новых версиях Inno Setup ("Invalid number of
; parameters"), а персонализация всё равно дублировалась.

[Code]
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
    { Сносим старые версии: новая (с AppId) и старая (по имени, без AppId). }
    RunUninstaller('{7B4C9E2A-3F1D-4A6B-9C2E-5D8F0A1B2C3D}_is1');
    RunUninstaller('Smart Zones Pro_is1');
  end;
end;
