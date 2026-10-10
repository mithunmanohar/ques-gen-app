@echo off
REM Start Question Set Studio on Windows: double-click this file.
REM   run.bat --debug       very detailed logs
REM   run.bat --help        all options
REM All the real work happens in start.py; this script just finds a suitable Python.
setlocal
cd /d "%~dp0"
chcp 65001 >nul 2>&1
title Question Set Studio

set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
if not defined PY (
  echo ----------------------------------------------------------------
  echo   PROBLEM: Python 3.10 or newer was not found on this computer.
  echo.
  echo   1. Download it from https://www.python.org/downloads/
  echo   2. In the installer, TICK "Add python.exe to PATH".
  echo   3. Then double-click run.bat again.
  echo ----------------------------------------------------------------
  pause
  exit /b 1
)

%PY% start.py %*
if errorlevel 1 (
  echo.
  echo The app did not start - see the messages above.
  pause
  exit /b 1
)
endlocal
