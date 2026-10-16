@echo off
cd /d "%LOCALAPPDATA%\EE-ReliabilityAgent\app"
if errorlevel 1 exit /b 1
"%LOCALAPPDATA%\EE-ReliabilityAgent\venv\Scripts\python.exe" -m agent.cli trigger
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
