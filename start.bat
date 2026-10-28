@echo off
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if /I "%~1"=="--check" goto :check
if not exist .runtime mkdir .runtime
if not exist .venv\Scripts\python.exe (
  where uv >nul 2>nul
  if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
      python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)"
      if errorlevel 1 goto :error
      python -m venv .venv
    ) else (
      py -3.11 -m venv .venv
    )
  ) else (
    uv venv --python 3.11 .venv
  )
  if errorlevel 1 goto :error
)
.venv\Scripts\python.exe scripts\bootstrap.py
if errorlevel 1 goto :error
.venv\Scripts\python.exe scripts\serve.py %*
if errorlevel 1 goto :error
exit /b 0
:check
if not exist .venv\Scripts\python.exe (
  echo Project environment is missing. Run start.bat to install it first.
  exit /b 1
)
.venv\Scripts\python.exe scripts\doctor.py
exit /b %ERRORLEVEL%
:error
 echo Setup failed. Check Python 3.11, Node.js and network access.
 pause
 exit /b 1
