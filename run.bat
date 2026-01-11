@echo off
setlocal

cd /d "%~dp0"

if not exist venv (
    echo Error: venv not found. Please run setup_env.bat first.
    pause
    exit /b 1
)

echo Activating venv and running application...
call venv\Scripts\activate

start "" pythonw main.py

echo Application finished.
