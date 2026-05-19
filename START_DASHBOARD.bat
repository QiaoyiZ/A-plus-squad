@echo off
setlocal

cd /d "%~dp0"
title MH6822 Compliance Dashboard

echo ============================================================
echo  MH6822 Compliance Dashboard
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found.
    echo Please install Python 3, then double-click this file again.
    echo.
    pause
    exit /b 1
)

echo Step 1 of 3: Installing required Python package(s)...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Package installation failed. Please check your Python/pip setup.
    echo.
    pause
    exit /b 1
)

echo.
echo Step 2 of 3: Regenerating the 33-trade compliance report...
python run_compliance_check.py --input trades.json --regimes CFTC,EMIR
if errorlevel 1 (
    echo.
    echo Compliance report generation failed.
    echo.
    pause
    exit /b 1
)

echo.
echo Step 3 of 3: Starting the browser dashboard...
echo.
echo The dashboard will open in your browser.
echo Keep this window open while presenting.
echo.
python dashboard.py
if errorlevel 1 (
    echo.
    echo Dashboard startup failed.
    echo.
    pause
    exit /b 1
)

echo.
echo Dashboard server stopped.
echo.
pause
