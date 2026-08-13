@echo off
setlocal
title SonicSync Lossless Multi-Room Audio Host
color 0B

echo ======================================================================
echo    🎵  SonicSync — Lossless Multi-Room Wireless Audio System
echo ======================================================================
echo.

:: Check for Python installation
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [ERROR] Python is not found in your PATH!
    echo Please install Python 3.10+ from https://www.python.org and check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo [*] Starting SonicSync Host Engine...
echo [*] Launching Dashboard and streaming servers...
echo.

:: Run host with default 48kHz stereo configuration
python run.py --mode host --source test

if errorlevel 1 (
    color 0C
    echo.
    echo [!] Server exited with an error.
    pause
)
