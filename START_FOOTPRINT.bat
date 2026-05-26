@echo off
title Smart Zones Pro - Footprint Chart
color 0B

echo =============================================
echo   Smart Zones Pro - Footprint Chart
echo =============================================
echo.

python --version >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found!
    pause
    exit /b 1
)

echo [OK] Python found
echo [INFO] Starting Footprint Window...
echo.

cd /d "%~dp0python_core"
python footprint_window.py

echo.
echo [INFO] Footprint closed.
pause
