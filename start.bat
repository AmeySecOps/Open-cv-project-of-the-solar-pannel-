@echo off
title SolarGuard AI - Intelligent Solar Panel Dust Detection System
color 0A

:: Ensure working directory is the script folder
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"

echo ==============================================================================
echo        SOLARGUARD AI - INDUSTRIAL SOLAR PANEL MONITORING SYSTEM
echo                 Computer Vision & ESP32 Wi-Fi Node
echo ==============================================================================
echo.

:: Check Python installation
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to your system PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

:: Virtual environment detection / setup
if not exist ".venv" (
    echo [*] Initializing Python virtual environment in .venv...
    python -m venv .venv
)

if exist ".venv\Scripts\python.exe" (
    set "PY_EXEC=%~dp0.venv\Scripts\python.exe"
) else (
    set "PY_EXEC=python"
)

:: Install/verify dependencies
echo [*] Checking dependencies from requirements.txt...
"%PY_EXEC%" -m pip install -r requirements.txt --quiet

:: Ensure critical folders exist
if not exist "logs" mkdir logs
if not exist "data" mkdir data
if not exist "reference_images" mkdir reference_images

echo.
echo ==============================================================================
echo  Server is launching on:
echo  >>> http://localhost:5000 <<<
echo.
echo  Press Ctrl+C in this console to stop the monitoring server.
echo ==============================================================================
echo.

:: Open default browser after launching
start "" http://localhost:5000

:: Start the Python backend application
"%PY_EXEC%" app.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application terminated with an error code.
    pause
)
