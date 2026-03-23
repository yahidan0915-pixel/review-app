@echo off
chcp 65001 > nul
title Review.AI Setup

echo ========================================
echo   Review.AI - Auto Setup
echo ========================================
echo.

set TARGET=%USERPROFILE%\Desktop\review-app
echo [1/5] Creating folder...
if not exist "%TARGET%" mkdir "%TARGET%"

echo [2/5] Downloading files from GitHub...
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/yahidan0915-pixel/review-app/main/main.py' -OutFile '%TARGET%\main.py' -UseBasicParsing"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/yahidan0915-pixel/review-app/main/scraper.py' -OutFile '%TARGET%\scraper.py' -UseBasicParsing"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/yahidan0915-pixel/review-app/main/index.html' -OutFile '%TARGET%\index.html' -UseBasicParsing"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/yahidan0915-pixel/review-app/main/requirements.txt' -OutFile '%TARGET%\requirements.txt' -UseBasicParsing"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/yahidan0915-pixel/review-app/main/.env.example' -OutFile '%TARGET%\.env.example' -UseBasicParsing"

echo [3/5] Checking Python...
python --version > nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found!
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

cd /d "%TARGET%"

echo [4/5] Setting up virtual environment...
if not exist "venv" python -m venv venv
call venv\Scripts\activate.bat

python -c "import uvicorn" > nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [5/5] Installing packages (first time only)...
    pip install --upgrade pip -q
    pip install fastapi uvicorn anthropic python-dotenv -q
    pip install playwright -q
    playwright install chromium
) else (
    echo [5/5] Packages already installed
)

if not exist ".env" copy ".env.example" ".env" > nul

echo.
echo ========================================
echo   Launching! Chrome will open shortly.
echo   Press Ctrl+C to stop.
echo ========================================
echo.

powershell -Command "Start-Sleep 3; Start-Process 'chrome' 'http://localhost:8000' -ErrorAction SilentlyContinue" &
python -m uvicorn main:app --host 0.0.0.0 --port 8000
pause