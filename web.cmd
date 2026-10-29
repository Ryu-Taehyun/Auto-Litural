@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating Python environment...
    python -m venv .venv || goto :error
)
echo [setup] Checking required packages...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :error
".venv\Scripts\python.exe" web_ui\server.py %*
if errorlevel 1 goto :error
exit /b 0
:error
echo [error] Startup failed. Check the error above and WEB_UI.md.
pause
exit /b 1
