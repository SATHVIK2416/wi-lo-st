@echo off
setlocal
title SonicSync Lossless Multi-Room Audio Host
color 0B

echo ======================================================================
echo    SonicSync - Lossless Multi-Room Wireless Audio System
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

:: Prefer the project virtual environment; create it on first run
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    echo [*] Using virtual environment .venv
) else (
    echo [*] No .venv found - creating one ^(first run only^)...
    python -m venv .venv
    if errorlevel 1 (
        color 0C
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
    if errorlevel 1 (
        color 0C
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
    set "PYTHON=.venv\Scripts\python.exe"
)

echo [*] Starting SonicSync Host Engine...
echo [*] Launching Dashboard and streaming servers...
echo.

:: Run host with default 48kHz stereo configuration
%PYTHON% run.py --mode host --source test

if errorlevel 1 (
    color 0C
    echo.
    echo [!] Server exited with an error.
    pause
)
