@echo off
title Skoda Logistics - Python Backend
setlocal enabledelayedexpansion

echo ==================================================
echo   Skoda Logistics Routing Platform: Local Backend
echo ==================================================
echo.

:: 1. Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your PATH.
    echo Please install Python 3.8+ and try again.
    pause
    exit /b
)

:: 2. Setup Virtual Environment (if missing)
if not exist venv (
    echo [1/3] Creating virtual environment...
    python -m venv venv
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b
    )
)

:: 3. Install Requirements
echo [2/3] Activating venv and updating dependencies...
call venv\Scripts\activate
pip install -r requirements.txt --quiet
if !errorlevel! neq 0 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b
)

:: 4. Start Server
echo [3/3] Starting Python Flask Server...
echo.
echo --------------------------------------------------
echo   Main UI:      http://localhost:5000
echo   GraphHopper:  http://localhost:8989 (Must be running)
echo --------------------------------------------------
echo.

:: Set environment variables for development
set FLASK_ENV=development
set PYTHONUNBUFFERED=1

:: Open browser after a short delay
start /b cmd /c "timeout /t 3 >nul && start http://localhost:5000"

:: Start the app
python server.py

pause
