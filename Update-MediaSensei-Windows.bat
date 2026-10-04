@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
  py -3 scripts\mediasensei_launcher.py update
  if errorlevel 1 pause
  exit /b %errorlevel%
)

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.12 or newer is required. Download it from https://www.python.org/downloads/
  pause
  exit /b 1
)
python scripts\mediasensei_launcher.py update
if errorlevel 1 pause
