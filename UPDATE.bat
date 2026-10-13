@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0UPDATE.ps1"
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (echo Update en eerste scan bevestigd.) else (echo Controle vereist. Uitkomstcode: %RESULT%)
pause
exit /b %RESULT%
