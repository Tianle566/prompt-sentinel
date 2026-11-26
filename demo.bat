@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start.bat to set up Prompt Sentinel first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -X utf8 scripts\demo_defense.py %*
set "DEMO_EXIT=%ERRORLEVEL%"
pause
exit /b %DEMO_EXIT%
