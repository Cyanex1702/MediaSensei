@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python scripts\mediasensei_launcher.py setup %*
) else (
  py -3 scripts\mediasensei_launcher.py setup %*
)
if errorlevel 1 pause
