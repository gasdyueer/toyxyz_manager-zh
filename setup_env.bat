@echo off
setlocal

cd /d "%~dp0"

echo [1/3] Checking for venv...
if exist venv (
    echo venv already exists.
) else (
    echo Creating venv...
    python -m venv venv
)

echo [2/3] Activating venv...
call venv\Scripts\activate

echo [3/3] Installing dependencies...
python -m pip install --upgrade pip
python -m pip install setuptools wheel
pip install -r requirements.txt

echo.
echo ==========================================
echo Setup Complete!
echo You can now run the application using run.bat
echo ==========================================
pause
