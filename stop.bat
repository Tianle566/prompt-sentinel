@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Project Python environment was not found. No processes were stopped.
  pause
  exit /b 1
)
.venv\Scripts\python.exe scripts\stop.py %*
set "STOP_EXIT=%ERRORLEVEL%"
if /I not "%~1"=="--no-pause" pause
exit /b %STOP_EXIT%
