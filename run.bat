@echo off
setlocal
cd /d "%~dp0"
title Unipus Helper

if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 goto :error
)

echo [2/2] Checking dependencies...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Starting Unipus Helper...
echo Press Ctrl+C to stop the server.
echo.
".venv\Scripts\python.exe" -m unipus_web %*

echo.
echo Program exited.
pause
goto :eof

:error
echo.
echo Failed to start. Make sure Python 3.12 or newer is installed and on PATH.
echo Download: https://www.python.org/downloads/
pause
exit /b 1
