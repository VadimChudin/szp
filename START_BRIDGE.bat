@echo off
title Smart Zones Pro - Bridge Server
color 0A

echo ==================================================
echo         Smart Zones Pro - Auto Bridge
echo ==================================================
echo.

python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found! Install Python 3.10+
    pause
    exit /b 1
)

echo [OK] Python found
echo [INFO] Starting Bridge Server...
echo [INFO] Zones will update automatically
echo [INFO] Press Ctrl+C to stop
echo.
echo --------------------------------------------------

cd /d "d:\smart-zones-pro\python_core"
python bridge_server.py

echo.
echo [INFO] Bridge Server stopped.
pause
