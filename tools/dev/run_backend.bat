@echo off
echo ============================================
echo Starting MEX Backend with Virtual Environment
echo ============================================
cd /d "%~dp0..\..\app"
echo Current directory: %cd%
echo.

REM Create logs directory if it doesn't exist
if not exist logs mkdir logs

REM Generate log filename with timestamp using PowerShell
for /f %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd_HHmmss'"') do set datetime=%%i
set LOG_FILE=logs\backend_%datetime%.log

echo Using venv Python...
echo Logging to: %LOG_FILE%
echo.
echo ============================================ >> %LOG_FILE%
echo MEX Backend Log - %date% %time% >> %LOG_FILE%
echo ============================================ >> %LOG_FILE%
echo. >> %LOG_FILE%

REM Run backend with output to both console and log
(venv\Scripts\python.exe backend\app.py 2>&1) | (findstr "^" > CON & findstr "^" >> %LOG_FILE%)

echo.
echo Backend stopped.
pause
