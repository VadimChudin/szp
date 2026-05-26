@echo off
chcp 65001 >nul
title Smart Zones Pro — Build Installer
color 0E

echo ╔══════════════════════════════════════════════════╗
echo ║       Smart Zones Pro — Build Pipeline           ║
echo ║   Сборка инсталлятора для клиента                ║
echo ╚══════════════════════════════════════════════════╝
echo.

:: Шаг 1: Собираем Python в .exe через PyInstaller
echo [1/3] Упаковываю Python Core в .exe...
set REPO=%~dp0
if "%REPO:~-1%"=="\" set REPO=%REPO:~0,-1%
cd /d "%REPO%\python_core"

python -m PyInstaller --noconfirm --onedir --console ^
    --name "SmartZonesBridge" ^
    --add-data "splash.gif;." ^
    --hidden-import pandas ^
    --hidden-import numpy ^
    --hidden-import yfinance ^
    --hidden-import requests ^
    --hidden-import mplfinance ^
    --hidden-import matplotlib ^
    --collect-all yfinance ^
    --collect-all mplfinance ^
    --exclude-module torch ^
    --exclude-module tensorflow ^
    --exclude-module scipy ^
    --exclude-module sympy ^
    --exclude-module numba ^
    --exclude-module llvmlite ^
    --exclude-module psycopg2 ^
    --exclude-module sqlalchemy ^
    --exclude-module botocore ^
    --exclude-module boto3 ^
    --exclude-module cryptography ^
    --exclude-module bcrypt ^
    --exclude-module PIL ^
    --exclude-module lxml ^
    "app_entry.py"

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller failed!
    pause
    exit /b 1
)

echo [OK] Python упакован в SmartZonesBridge.exe
echo.

:: Шаг 2: Копируем артефакты в папку сборки
echo [2/3] Подготавливаю файлы для инсталлятора...
set BUILD_DIR=%REPO%\installer\files
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
mkdir "%BUILD_DIR%"
mkdir "%BUILD_DIR%\bridge"
mkdir "%BUILD_DIR%\mql4"
mkdir "%BUILD_DIR%\mql5"
mkdir "%BUILD_DIR%\data"

:: Копируем скомпилированный мост
xcopy /E /Y "%REPO%\python_core\dist\SmartZonesBridge\*" "%BUILD_DIR%\bridge\" >nul

:: Копируем MQL4 индикатор + EA
copy /Y "%REPO%\mql\MT4\Indicators\StrongZones.mq4" "%BUILD_DIR%\mql4\" >nul
copy /Y "%REPO%\mql\MT4\Experts\SmartZonesCollector.mq4" "%BUILD_DIR%\mql4\" >nul

:: Копируем MQL5 индикатор + EA
copy /Y "%REPO%\mql\MT5\Indicators\StrongZones.mq5" "%BUILD_DIR%\mql5\" >nul
if exist "%REPO%\mql\MT5\Experts\SmartZonesCollector.mq5" copy /Y "%REPO%\mql\MT5\Experts\SmartZonesCollector.mq5" "%BUILD_DIR%\mql5\" >nul

:: Копируем CSV данные (начальный набор)
copy /Y "%REPO%\python_core\data\*.csv" "%BUILD_DIR%\data\" >nul

echo [OK] Файлы подготовлены в %BUILD_DIR%
echo.

:: Шаг 3: Инструкция для Inno Setup
echo [3/3] Готово к сборке инсталлятора!
echo.
echo Дальше нужно:
echo   1. Установить Inno Setup: https://jrsoftware.org/isdl.php
echo   2. Открыть файл: %REPO%\installer\setup.iss
echo   3. Нажать Ctrl+F9 (Build) в Inno Setup
echo   4. Готовый SmartZonesPro_Setup.exe появится в %REPO%\installer\output\
echo.
pause
