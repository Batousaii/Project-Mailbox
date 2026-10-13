@echo off
cd /d "%LOCALAPPDATA%\EE-ReliabilityAgent\app"
if errorlevel 1 goto missing
"%LOCALAPPDATA%\EE-ReliabilityAgent\venv\Scripts\python.exe" -m agent.cli status
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
:missing
echo Bestaande installatie ontbreekt.
pause
exit /b 1
