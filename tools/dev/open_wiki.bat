@echo off
setlocal

cd /d "%~dp0..\..\app"

set "PORT=4173"
set "URL=http://127.0.0.1:%PORT%/wiki/"
set "PYTHON_CMD="
set "FIREFOX_EXE="
set "WIKI_PID="

echo ========================================
echo Opening Nucleus Melee Wiki
echo ========================================
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%PORT% ^| findstr LISTENING') do (
    if not defined WIKI_PID set "WIKI_PID=%%a"
)

if defined WIKI_PID (
    echo Wiki server already running on port %PORT% ^(PID %WIKI_PID%^).
) else (
    if exist "%CD%\venv\Scripts\python.exe" (
        set "PYTHON_CMD=""%CD%\venv\Scripts\python.exe"""
    )

    if not defined PYTHON_CMD (
        where py >nul 2>nul
        if not errorlevel 1 set "PYTHON_CMD=py -3"
    )

    if not defined PYTHON_CMD (
        where python >nul 2>nul
        if not errorlevel 1 set "PYTHON_CMD=python"
    )

    if not defined PYTHON_CMD (
        echo Python was not found. Install Python or create the project venv first.
        pause
        exit /b 1
    )

    echo Starting wiki server on port %PORT%...
    start "Nucleus Wiki Server" cmd /k "cd /d ""%CD%"" && %PYTHON_CMD% ..\tools\wiki\serve.py --port %PORT%"
    timeout /t 2 /nobreak >nul
)

if exist "%ProgramFiles%\Mozilla Firefox\firefox.exe" (
    set "FIREFOX_EXE=%ProgramFiles%\Mozilla Firefox\firefox.exe"
)

if not defined FIREFOX_EXE if exist "%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe" (
    set "FIREFOX_EXE=%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"
)

if not defined FIREFOX_EXE (
    for /f "delims=" %%i in ('where firefox 2^>nul') do (
        if not defined FIREFOX_EXE set "FIREFOX_EXE=%%i"
    )
)

if defined FIREFOX_EXE (
    echo Opening wiki in Firefox...
    start "Firefox Wiki" "%FIREFOX_EXE%" "%URL%"
) else (
    echo Firefox was not found. Opening wiki in the default browser instead...
    start "" "%URL%"
)

echo.
echo Wiki URL: %URL%
exit /b 0
