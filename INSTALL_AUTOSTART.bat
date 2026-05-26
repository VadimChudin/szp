@echo off
chcp 65001 >nul

echo ╔══════════════════════════════════════════════════╗
echo ║   Установка автозапуска Smart Zones Pro          ║
echo ╚══════════════════════════════════════════════════╝
echo.

:: Создаём ярлык в папке автозагрузки Windows
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT=%STARTUP%\SmartZonesBridge.lnk
set TARGET=d:\smart-zones-pro\START_BRIDGE.bat

:: Используем PowerShell для создания ярлыка
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%TARGET%'; $s.WorkingDirectory = 'd:\smart-zones-pro'; $s.WindowStyle = 7; $s.Save()"

if exist "%SHORTCUT%" (
    echo [OK] Автозапуск установлен!
    echo [OK] Bridge Server будет запускаться при каждом включении Windows.
    echo [OK] Ярлык: %SHORTCUT%
    echo.
    echo Для удаления автозапуска просто удалите файл:
    echo   %SHORTCUT%
) else (
    echo [ERROR] Не удалось создать ярлык автозапуска.
    echo Вы можете вручную скопировать START_BRIDGE.bat в:
    echo   %STARTUP%
)

echo.
pause
