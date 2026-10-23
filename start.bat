@echo off
rem Fraud Detection MVP - double-click to start. The first start sets everything up.
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python is not installed.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" in the installer. Then start this file again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo First start: setting up the app. This takes a minute and needs internet once...
    py -3 -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :error
)

echo.
echo Fraud Detection is starting. Your browser opens in a few seconds.
echo Keep this window open while you use the app. Close it to stop the app.
echo.
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:5000"
".venv\Scripts\python.exe" -m flask --app "fraud_detection.web:create_app()" run
pause
exit /b 0

:error
echo.
echo Setup failed. Please send a screenshot of this window to your Autopay contact.
pause
exit /b 1
