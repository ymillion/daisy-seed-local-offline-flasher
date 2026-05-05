@echo off
echo Daisy Seed Offline Flasher
echo =======================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed or not in PATH.
    echo Please install Python 3.7 or later from https://python.org
    pause
    exit /b 1
)

:: Run the flasher
cd /d "%~dp0"
python daisy_seed_flasher.py

if errorlevel 1 (
    echo.
    echo An error occurred. Press any key to exit.
    pause >nul
)
