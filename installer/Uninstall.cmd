@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   Agro-Radar uninstaller
echo   =====================
echo   Removes: %LOCALAPPDATA%\AgroRadar and shortcuts
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Uninstall %*
if errorlevel 1 (
    echo.
    echo Uninstall failed. See messages above.
    pause
)
