@echo off
echo ========================================
echo SSBM Nucleus - Development Setup
echo ========================================
echo.

cd /d "%~dp0..\..\app"

REM Check for Node.js
echo [1/6] Checking Node.js...
where node >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Node.js not found. Installing via winget...
    winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: Failed to install Node.js. Please install manually from https://nodejs.org
        pause
        exit /b 1
    )
    echo.
    echo ========================================
    echo Node.js installed! Please restart this script.
    echo ========================================
    pause
    exit /b 0
) else (
    for /f "tokens=*" %%i in ('node --version') do echo Found Node.js %%i
)

REM Check for Python
echo.
echo [2/6] Checking Python...
set "PYTHON_CMD="
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PYTHON_CMD=python"
) else (
    if exist "C:\Users\%USERNAME%\AppData\Local\Python\bin\python3.exe" (
        set "PYTHON_CMD=C:\Users\%USERNAME%\AppData\Local\Python\bin\python3.exe"
    )
)

if defined NUCLEUS_SETUP_PYTHON set "PYTHON_CMD=%NUCLEUS_SETUP_PYTHON%"

if "%PYTHON_CMD%"=="" (
    echo ERROR: Python not found. Please install Python 3.13.17 or newer 3.13.x from https://python.org
    pause
    exit /b 1
)
"%PYTHON_CMD%" -c "import sys; sys.path.insert(0, 'backend'); from core.runtime_versions import check_windows_python; check_windows_python(); print(sys.version)"
if errorlevel 1 exit /b 1

REM Check for .NET SDK
echo.
echo [3/6] Checking .NET SDK (dev-only: the stage-parser smoke test and the 3.1 test oracle)...
set "DOTNET_CMD="
where dotnet >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "DOTNET_CMD=dotnet"
) else (
    if exist "C:\Program Files\dotnet\dotnet.exe" (
        set "DOTNET_CMD=C:\Program Files\dotnet\dotnet.exe"
    ) else if exist "C:\Program Files (x86)\dotnet\dotnet.exe" (
        set "DOTNET_CMD=C:\Program Files (x86)\dotnet\dotnet.exe"
    )
)

if "%DOTNET_CMD%"=="" (
    echo .NET SDK not found. Installing via winget...
    winget install Microsoft.DotNet.SDK.6 --accept-package-agreements --accept-source-agreements
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: Failed to install .NET SDK. Please install manually from https://dotnet.microsoft.com/download/dotnet/6.0
        pause
        exit /b 1
    )
    echo.
    echo ========================================
    echo .NET SDK installed! Please restart this script.
    echo ========================================
    pause
    exit /b 0
) else (
    for /f "tokens=*" %%i in ('"%DOTNET_CMD%" --version') do echo Found .NET SDK %%i
)

REM Check for .NET Core 3.1 Runtime -- DEV ONLY, and optional.
REM Slippi costume validation is pure Python now (costume_validator.py) and
REM needs no runtime at all. The retired SlippiCostumeValidator.exe survives
REM solely as the oracle for the differential test in
REM tests/backend/test_costume_validator.py, which needs 3.1 to run and skips
REM itself without it. Nothing shipped to users depends on this.
REM
REM Note this check is why the exe's missing runtime never showed up in dev:
REM setup.bat quietly installed 3.1 on every dev box, while the packaged
REM installer shipped the exe with no runtime and validation failed for users.
echo.
echo [3.5/6] Checking .NET Core 3.1 Runtime (optional, test oracle only)...
"%DOTNET_CMD%" --list-runtimes 2>nul | findstr /C:"Microsoft.NETCore.App 3.1" >nul
if %ERRORLEVEL% NEQ 0 (
    echo .NET Core 3.1 Runtime not found. Installing via winget...
    winget install Microsoft.DotNet.Runtime.3_1 --accept-package-agreements --accept-source-agreements
    if %ERRORLEVEL% NEQ 0 (
        echo Note: could not install .NET Core 3.1 Runtime.
        echo This is fine -- it only skips the validator differential test.
    ) else (
        echo .NET Core 3.1 Runtime installed!
    )
) else (
    echo Found .NET Core 3.1 Runtime
)

REM Create Python virtual environment
echo.
echo [4/6] Setting up Python virtual environment...
if not exist "venv" (
    echo Creating venv...
    "%PYTHON_CMD%" -m venv venv
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
) else (
    echo venv already exists
)

"venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, 'backend'); from core.runtime_versions import check_windows_python; check_windows_python()"
if errorlevel 1 exit /b 1

echo Installing Python dependencies...
call venv\Scripts\activate
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to install Python dependencies
    pause
    exit /b 1
)

REM Install npm dependencies
echo.
echo [5/6] Installing npm dependencies...
echo Installing root dependencies...
call npm install
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to install root npm dependencies
    pause
    exit /b 1
)

echo Installing frontend dependencies...
cd frontend
call npm install
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to install viewer npm dependencies
    pause
    exit /b 1
)
cd ..

REM Fetch the pinned prebuilt MexCLI + HSDRawViewer (forks' GitHub Releases)
echo.
echo [6/6] Fetching MexCLI + HSDRawViewer...
"venv\Scripts\python.exe" "%~dp0fetch_native.py" all --platform win-x64
if %ERRORLEVEL% NEQ 0 (
    echo WARNING: could not fetch the native toolchain. MEX export and CSP generation will not work.
    echo          A private fork needs "gh auth login" or NUCLEUS_FETCH_TOKEN. Then re-run
    echo          venv\Scripts\python.exe tools\build\fetch_native.py all
)

echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo To start the app, run: start.bat
echo.
pause
