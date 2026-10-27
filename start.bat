@echo off
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist .runtime mkdir .runtime
if not exist .venv\Scripts\python.exe (
  where uv >nul 2>nul
  if errorlevel 1 (
    py -3.11 -m venv .venv
    if errorlevel 1 goto :error
    .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
  ) else (
    uv venv --python 3.11 .venv
    uv pip install --python .venv\Scripts\python.exe -r backend\requirements.txt
  )
  if errorlevel 1 goto :error
)
.venv\Scripts\python.exe scripts\serve.py %*
if exist .runtime\stop.request exit /b 0
if errorlevel 1 goto :error
exit /b 0
:error
 echo Setup failed. Check Python 3.11, Node.js and network access.
 pause
 exit /b 1
