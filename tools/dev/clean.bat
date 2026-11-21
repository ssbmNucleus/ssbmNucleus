@echo off
set "PY=python"
if exist "%~dp0..\..\app\venv\Scripts\python.exe" set "PY=%~dp0..\..\app\venv\Scripts\python.exe"
"%PY%" "%~dp0..\clean.py" %*
