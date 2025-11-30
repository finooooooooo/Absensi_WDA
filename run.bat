@echo off
title Wine Dental App - Auto Launcher
color 0A

echo ==================================================
echo   WINE DENTAL ATTENDANCE APP - AUTO LAUNCHER
echo ==================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your PATH.
    echo Please install Python 3.10+ from python.org and try again.
    pause
    exit
)
echo [OK] Python found.

:: 2. Install Dependencies
echo.
echo [STEP 1/3] Installing Dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit
)

:: 3. Initialize Database
echo.
echo [STEP 2/3] Initializing Database...
python seed_db.py
if %errorlevel% neq 0 (
    echo [WARNING] Database seed script encountered an issue.
    echo It might be because the database is already set up. Continuing...
)

:: 4. Start Server
echo.
echo [STEP 3/3] Starting Application Server...
echo.
echo The app is running! Open your browser and go to: http://localhost:5000
echo (Press CTRL+C to stop the server)
echo.

python app.py

:: Keep window open if app crashes
pause
