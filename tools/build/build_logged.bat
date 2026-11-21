@echo off
setlocal

REM Keep this name distinct from build.bat (same folder), which intentionally
REM sets PROJECT_ROOT in the caller's environment when invoked with CALL.
REM This wrapper lives in tools\build\ at the repo root; the app is app\ beside tools\.
set "WRAPPER_BUILD_DIR=%~dp0"
set "WRAPPER_PROJECT_ROOT=%~dp0..\..\app\"

REM The public entry point re-launches itself through PowerShell so the complete
REM build is shown in the console and saved to a timestamped log.  The private
REM --logged switch prevents that child invocation from recursively re-launching.
if /i "%~1"=="--logged" goto :run_build

set "LOG_DIR=%WRAPPER_PROJECT_ROOT%logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f %%I in ('powershell.exe -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "BUILD_TIMESTAMP=%%I"
if not defined BUILD_TIMESTAMP (
    echo ERROR: Unable to create a timestamp for the build log.
    endlocal & exit /b 1
)

set "BUILD_LOG=%LOG_DIR%\build_%BUILD_TIMESTAMP%.log"
echo Logging full build output to:
echo   %BUILD_LOG%
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WRAPPER_BUILD_DIR%run_logged_build.ps1" -BuildScript "%~f0" -LogFile "%BUILD_LOG%"
set "BUILD_EXIT=%ERRORLEVEL%"

echo.
if not "%BUILD_EXIT%"=="0" (
    echo Build failed with exit code %BUILD_EXIT%. Full log:
    echo   %BUILD_LOG%
) else (
    echo Build log saved to:
    echo   %BUILD_LOG%
)

endlocal & exit /b %BUILD_EXIT%

:run_build

pushd "%WRAPPER_PROJECT_ROOT%" >nul

REM This child runs with stdout redirected into the logger's pipe, so any
REM `pause` in build.bat would block forever with its prompt buffered out of
REM sight. Tell build.bat it is unattended.
set "NUCLEUS_BUILD_NONINTERACTIVE=1"

echo ========================================
echo SSBM Nucleus Root Build
echo ========================================
echo.
echo Running build.bat...
echo.

call "%WRAPPER_BUILD_DIR%build.bat"
set "BUILD_EXIT=%ERRORLEVEL%"

if not "%BUILD_EXIT%"=="0" (
    echo.
    echo Root build wrapper detected a failure. Exit code: %BUILD_EXIT%
    popd >nul
    endlocal & exit /b %BUILD_EXIT%
)

echo.
echo Installers copied to project root:
REM Read the manifest build.bat wrote for THIS run. Listing *.exe in the
REM project root instead would report stale installers from older versions
REM (e.g. a leftover 0.7.2 setup) as if this build had produced them.
set "INSTALLER_MANIFEST=%WRAPPER_PROJECT_ROOT%build\last_installers.txt"
set "FOUND_INSTALLER="
if exist "%INSTALLER_MANIFEST%" (
    for /f "usebackq eol=| delims=" %%F in ("%INSTALLER_MANIFEST%") do (
        if exist "%%~F" (
            echo   %%~F
            set "FOUND_INSTALLER=1"
        )
    )
)

if not defined FOUND_INSTALLER (
    echo ERROR: Build completed, but it produced no installer of its own.
    echo Existing project-root .exe files do not count as build output.
    popd >nul
    endlocal & exit /b 1
)

popd >nul
endlocal & exit /b 0
