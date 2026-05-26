@echo off
echo ==============================================
echo Building Smart Zones Pro (Desktop App)
echo ==============================================

echo [1/3] Installing dependencies...
pip install pystray pywebview pyinstaller Pillow pandas termcolor

echo [2/3] Compiling SmartZonesPro executable...
pyinstaller --noconfirm --onedir --windowed --name "SmartZonesPro" --add-data "d:\smart-zones-pro\python_core\brokers.json;." --add-data "d:\smart-zones-pro\data_bridge\footprint_1h.html;data_bridge" --add-data "d:\smart-zones-pro\data_bridge\footprint_4h.html;data_bridge" --add-data "d:\smart-zones-pro\data_bridge\footprint_1d.html;data_bridge" d:\smart-zones-pro\python_core\smart_zones_tray.py

echo [3/3] Compiling Inno Setup...
echo Make sure you have Inno Setup installed!
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" d:\smart-zones-pro\setup.iss

echo ==============================================
echo DONE! Check 'Output' folder for SmartZonesPro_Setup.exe
pause
