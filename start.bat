@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python scripts\mediasensei_launcher.py start %*
) else (
  py -3 scripts\mediasensei_launcher.py start %*
)
if errorlevel 1 pause
