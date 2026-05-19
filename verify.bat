@echo off
setlocal

cd /d "%~dp0"
title MH6822 Verify

echo ============================================================
echo  MH6822 Verify - install + tests + engine
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.11+ and try again.
    exit /b 1
)

echo Step 1 of 3: Installing dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency install failed.
    exit /b 1
)

echo.
echo Step 2 of 3: Running unit tests...
python -m unittest discover -s tests -v
if errorlevel 1 (
    echo Unit tests failed.
    exit /b 1
)

echo.
echo Step 3 of 3: Running the compliance engine on trades.json...
python run_compliance_check.py --input trades.json --regimes CFTC,EMIR
if errorlevel 1 (
    echo Compliance engine run failed.
    exit /b 1
)

echo.
echo Verify completed successfully. See output\compliance_report.json.
endlocal
