@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0CONTROL.ps1" -Action Uninstall
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
