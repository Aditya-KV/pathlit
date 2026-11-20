@echo off
rem Pathlit launcher. Double-click it, or type "pathlit" in this folder. "pathlit help" lists every command.
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo First run: creating the Python environment. This takes a minute or two...
    where py >nul 2>nul && (py -3 -m venv "%ROOT%.venv") || (python -m venv "%ROOT%.venv")
    if not exist "%PY%" (
        echo Could not create the environment. Install Python 3.11 or newer from python.org and try again.
        pause
        exit /b 1
    )
    "%PY%" -m pip install --quiet --upgrade pip
    "%PY%" -m pip install --quiet -r "%ROOT%requirements.txt"
    if errorlevel 1 (
        echo Installing the packages failed. Check your internet connection and try again.
        pause
        exit /b 1
    )
)

set "PYTHONPATH=%ROOT%src"
"%PY%" -u -m pathlit %*
set "CODE=%ERRORLEVEL%"

rem if it was double-clicked (no arguments) keep the window open so any message can be read
if "%~1"=="" if not "%CODE%"=="0" pause
exit /b %CODE%
