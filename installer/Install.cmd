@echo off
setlocal
cd /d "%~dp0"
echo.
echo   Agro-Radar installer
echo   ===================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if errorlevel 1 (
    echo.
    echo Install failed. See messages above.
    pause
)
