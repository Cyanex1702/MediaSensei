@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Run MediaSensei-Windows.bat first.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" scripts\workspace_backup.py backup
pause
