@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Script to run (morning.cmd / close.cmd pass it in)
set "SCRIPT=%~1"
if "%SCRIPT%"=="" set "SCRIPT=main.py"

rem Create the virtual environment if it does not exist
if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    python -m venv .venv || goto :error
)

call ".venv\Scripts\activate.bat" || goto :error

rem Install packages (already-installed ones are skipped)
echo [setup] 패키지 설치 중입니다...
python -m pip install -q --disable-pip-version-check -r requirements.txt || goto :error
echo [setup] 패키지 설치 완료

rem Chrome is started by the Python script (chrome.py)
python "%SCRIPT%"
set EXITCODE=%ERRORLEVEL%
pause
exit /b %EXITCODE%

:error
echo [error] Setup failed.
pause
exit /b 1
