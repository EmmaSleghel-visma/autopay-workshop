@echo off
rem Fraud Detection MVP - double-click to start. The first start sets everything up.
cd /d "%~dp0"

rem Use the py launcher if present (python.org installs it), otherwise python on PATH.
rem Each candidate is actually run, so the Microsoft Store "python" placeholder (present on
rem Windows even without Python) and Pythons older than 3.10 are skipped.
set "PY="
set "CHECK=import sys; sys.exit(sys.version_info < (3, 10))"
py -3 -c "%CHECK%" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "%CHECK%" >nul 2>nul && set "PY=python"
if not defined PY (
    echo Python 3.10 or newer was not found.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/
    echo and keep the default options in the installer. Then start this file again.
    pause
    exit /b 1
)

rem setup-ok.txt is written only after a complete setup, so an interrupted or failed
rem first start (no internet, window closed) is redone instead of leaving a broken app.
rem Setup is also redone when the app's Python is missing (e.g. removed by antivirus).
set "NEED_SETUP="
if not exist ".venv\setup-ok.txt" set "NEED_SETUP=1"
if not exist ".venv\Scripts\python.exe" set "NEED_SETUP=1"
if defined NEED_SETUP (
    echo Setting up the app. This takes 1-2 minutes and needs internet...
    rem A running app locks its python.exe: probe that first, so we never half-delete a running install.
    if exist ".venv\Scripts\python.exe" del ".venv\Scripts\python.exe" 2>nul
    if exist ".venv\Scripts\python.exe" goto :running
    if exist ".venv" rmdir /s /q ".venv"
    if exist ".venv" goto :running
    %PY% -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --retries 1 --timeout 15 -r requirements.txt || goto :error
    echo ok> ".venv\setup-ok.txt"
)

echo.
echo Fraud Detection is starting. Your browser opens in a few seconds.
echo Keep this window open while you use the app. Close it to stop the app.
echo.
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:5000"
".venv\Scripts\python.exe" -m flask --app "fraud_detection.web:create_app()" run
rem Flask exits 0 when stopped with Ctrl+C and 1 when it cannot start (e.g. port 5000 in use).
if errorlevel 1 goto :notstarted
pause
exit /b 0

:notstarted
echo.
echo The app could not start. Another program may be using port 5000 - close it and start again.
echo If this keeps happening, send a screenshot of this window to your Autopay contact.
pause
exit /b 1

:running
echo.
echo The app seems to be already running. Close its other black window first, then start this file again.
pause
exit /b 1

:error
echo.
echo Setup failed. Please send a screenshot of this window to your Autopay contact.
pause
exit /b 1
