@echo off
title Pasang Bot Saham Auto-Start Windows
echo ======================================================================
echo    MEMASANG BOT SAHAM & CRYPTO AUTO-START SAAT WINDOWS BOOTING
echo ======================================================================
echo.

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET_VBS=D:\bot saham\scripts\start_bot_silent.vbs"

if not exist "%TARGET_VBS%" (
    echo [ERROR] File %TARGET_VBS% tidak ditemukan!
    echo Pastikan path file benar.
    pause
    exit /b 1
)

copy "%TARGET_VBS%" "%STARTUP_DIR%\start_bot_silent.vbs" /Y >nul
if %ERRORLEVEL% equ 0 (
    echo [BERHASIL] Bot telah dipasang ke Windows Startup:
    echo "%STARTUP_DIR%\start_bot_silent.vbs"
    echo.
    echo Bot akan otomatis berjalan senyap di background setiap PC/Laptop nyala!
) else (
    echo [GAGAL] Tidak dapat menyalin file ke Startup folder.
)

echo.
echo ======================================================================
pause
