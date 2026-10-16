@echo off
echo ========================================================
echo   MEMBUAT SHORTCUT BOTRADING DI DESKTOP WINDOWS...
echo ========================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Buat_Shortcut.ps1"

echo.
echo Selesai!
pause
