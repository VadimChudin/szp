@echo off
echo ==============================================
echo Building Smart Zones Pro (Desktop App)
echo ==============================================

set REPO=%~dp0
if "%REPO:~-1%"=="\" set REPO=%REPO:~0,-1%

echo [1/3] Installing dependencies...
pip install -r "%REPO%\python_core\requirements.txt"
pip install pystray Pillow termcolor pyinstaller

echo [2/3] Compiling SmartZonesPro executable...
cd /d "%REPO%\python_core"
pyinstaller --noconfirm --onedir --windowed --name "SmartZonesPro" ^
  --add-data "%REPO%\python_core\brokers.json;." ^
  --add-data "%REPO%\data_bridge\footprint_1h.html;data_bridge" ^
  --add-data "%REPO%\data_bridge\footprint_4h.html;data_bridge" ^
  --add-data "%REPO%\data_bridge\footprint_1d.html;data_bridge" ^
  "%REPO%\python_core\smart_zones_tray.py"

echo [3/3] Compiling Inno Setup...
echo Make sure you have Inno Setup installed!
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "%REPO%\setup.iss"

echo ==============================================
echo DONE! Check 'Output' folder for SmartZonesPro_Setup.exe
pause
