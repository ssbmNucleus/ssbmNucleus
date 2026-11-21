@echo off
setlocal DisableDelayedExpansion
REM Git Bash may put Unix utilities on PATH. No shell-based launch or cleanup.
where.exe node.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js 20.19+ or 22.12+ is required on PATH.
    exit /b 1
)
node.exe "%~dp0launch.cjs" %*
exit /b %errorlevel%
