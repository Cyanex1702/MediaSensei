@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python scripts\mediasensei_launcher.py dev %*
) else (
  py -3 scripts\mediasensei_launcher.py dev %*
)
if errorlevel 1 pause
