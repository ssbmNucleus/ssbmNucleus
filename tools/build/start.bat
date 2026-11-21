@echo off
echo ========================================
echo Starting MEX Manager (Electron)
echo ========================================
echo.

REM Stop this checkout's stale backend, Vite and Electron by PID (stop_stale_dev.ps1
REM checks each owner first). Never by image name: node.exe/python.exe/mex_backend.exe
REM also run unrelated apps on this machine, including the host the agents run in.
echo Cleaning up existing Nucleus processes...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_stale_dev.ps1"
taskkill /F /FI "WINDOWTITLE eq MEX Manager*" 2>nul
timeout /t 2 /nobreak >nul

echo.
echo Starting Backend (Flask)...
start "MEX Backend" cmd /k "%~dp0..\dev\run_backend.bat"

echo Waiting for backend to start...
timeout /t 3 /nobreak >nul

echo.
echo Starting Vite Dev Server...
start "Vite Dev Server" cmd /k "cd /d "%~dp0..\..\app\frontend" && npm run dev"

echo Waiting for Vite to start...
timeout /t 3 /nobreak >nul

echo.
echo Starting Electron App...
start "MEX Manager" cmd /k "cd /d "%~dp0..\..\app" && npm run electron"

echo.
echo ========================================
echo MEX Manager is starting!
echo ========================================
echo.
echo Backend:  Port assigned dynamically
echo Frontend: http://localhost:3000 (Vite Dev Server)
echo Electron: Desktop app window
echo.
echo To stop, close all terminal windows. The next start.bat stops this checkout's stale ones.
echo.
