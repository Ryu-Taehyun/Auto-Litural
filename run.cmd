@echo off
setlocal
cd /d "%~dp0"

rem Create the virtual environment if it does not exist
if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    python -m venv .venv || goto :error
)

call ".venv\Scripts\activate.bat" || goto :error

rem Install packages (already-installed ones are skipped)
python -m pip install -q --disable-pip-version-check -r requirements.txt || goto :error

rem Start Chrome in debugging mode if port 9222 is not already open
set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
curl -s -o nul http://127.0.0.1:9222/json/version && goto :run
if not exist "%CHROME%" (
    echo [error] Chrome not found: %CHROME%
    goto :error
)
echo [setup] Starting Chrome in debugging mode...
start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\ChromeDebug"

rem Wait up to 15 seconds for the debugging port
set /a TRIES=0
:wait_chrome
curl -s -o nul http://127.0.0.1:9222/json/version && goto :run
set /a TRIES+=1
if %TRIES% geq 15 (
    echo [error] Chrome debugging port 9222 did not open.
    goto :error
)
ping -n 2 127.0.0.1 >nul
goto :wait_chrome

:run
python main.py %*
set EXITCODE=%ERRORLEVEL%
pause
exit /b %EXITCODE%

:error
echo [error] Setup failed.
pause
exit /b 1
