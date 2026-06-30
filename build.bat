@echo off
echo ==============================================
echo Building Smart Zones Pro (Desktop App)
echo ==============================================

set REPO=%~dp0
if "%REPO:~-1%"=="\" set REPO=%REPO:~0,-1%

echo [1/3] Installing dependencies...
python -m pip install -r "%REPO%\python_core\requirements.txt"
python -m pip install pystray Pillow termcolor pyinstaller

echo [2/3] Compiling SmartZonesPro executable...
cd /d "%REPO%\python_core"
REM brokers.json в .gitignore и на чистом клоне отсутствует. Создаём дефолтный,
REM иначе PyInstaller падает на --add-data. В рантайме приложение его перезапишет.
if not exist "%REPO%\python_core\brokers.json" (
  echo {"active_broker": 0, "brokers": [{"name": "Broker 1", "server": "", "login": 0, "password": "", "path": ""}, {"name": "Broker 2", "server": "", "login": 0, "password": "", "path": ""}, {"name": "Broker 3", "server": "", "login": 0, "password": "", "path": ""}]}> "%REPO%\python_core\brokers.json"
)
REM Вызов через "python -m PyInstaller" не зависит от PATH (Scripts может быть не в PATH).
python -m PyInstaller --noconfirm --onedir --windowed --name "SmartZonesPro" ^
  --hidden-import settings_window ^
  --hidden-import pystray ^
  --hidden-import PIL ^
  --add-data "%REPO%\python_core\brokers.json;." ^
  --add-data "%REPO%\data_bridge\footprint_1h.html;data_bridge" ^
  --add-data "%REPO%\data_bridge\footprint_4h.html;data_bridge" ^
  --add-data "%REPO%\data_bridge\footprint_1d.html;data_bridge" ^
  "%REPO%\python_core\app_entry.py"
if errorlevel 1 (
  echo ERROR: PyInstaller failed. Aborting.
  pause
  exit /b 1
)

echo [3/3] Compiling Inno Setup...
REM Ищем ISCC.exe в стандартных путях Inno Setup 6 (x86 и x64).
set "ISCC="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"

if "%ISCC%"=="" (
  echo ERROR: Inno Setup 6 not found.
  echo Install it first: run "%REPO%\installer\innosetup6.exe", then re-run build.bat.
  pause
  exit /b 1
)

"%ISCC%" "%REPO%\setup.iss"

echo ==============================================
echo DONE! Check 'Output' folder for SmartZonesPro_Setup.exe
pause
