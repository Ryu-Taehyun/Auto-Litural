@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto :install
echo [setup] Creating a separate Python environment...
where py >nul 2>&1
if errorlevel 1 (
    python -m venv .venv || goto :error
) else (
    py -3 -m venv .venv || goto :error
)
:install
echo [setup] Checking required packages...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :error
".venv\Scripts\python.exe" terminal.py %*
if errorlevel 1 goto :error
exit /b 0
:error
echo [error] Startup failed. See the message above and README.md.
pause
exit /b 1
