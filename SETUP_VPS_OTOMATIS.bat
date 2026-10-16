@echo off
chcp 65001 >nul
title SETUP OTOMATIS BOT TRADING DI VPS WINDOWS
color 0B
cd /d "%~dp0"

echo ============================================================================
echo   🚀 INSTALASI OTOMATIS BOT TRADING (MT5 + BINANCE FUTURES + DASHBOARD)
echo ============================================================================
echo.

echo [1/4] Membuka Port 8080 di Windows Firewall (Agar Dashboard bisa dibuka dari HP/Laptop)...
netsh advfirewall firewall delete rule name="Botrading Dashboard 8080" >nul 2>&1
netsh advfirewall firewall add rule name="Botrading Dashboard 8080" dir=in action=allow protocol=TCP localport=8080 >nul 2>&1
echo       ✓ Port 8080 berhasil dibuka!

echo.
echo [2/4] Memeriksa instalasi Python / UV...
where python >nul 2>&1
if %errorlevel% equ 0 (
    echo       ✓ Python sudah terdeteksi di sistem.
    goto :setup_venv
)

echo       [i] Python belum terpasang. Mengunduh installer Python otomatis...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile 'python_setup.exe'"
if exist "python_setup.exe" (
    echo       [+] Menginstall Python 3.11 secara otomatis (Mohon tunggu 1-2 menit)...
    python_setup.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
    del /f /q python_setup.exe >nul 2>&1
    set "PATH=%ProgramFiles%\Python311;%ProgramFiles%\Python311\Scripts;%PATH%"
)

:setup_venv
echo.
echo [3/4] Membuat Virtual Environment (.venv) baru khusus VPS...
if exist ".venv" (
    echo       [i] Menghapus .venv lama dari laptop agar bersih...
    rmdir /s /q ".venv"
)

python -m venv .venv
if not exist ".venv\Scripts\python.exe" (
    if exist "%ProgramFiles%\Python311\python.exe" (
        "%ProgramFiles%\Python311\python.exe" -m venv .venv
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo       [!] Gagal membuat .venv otomatis. Pastikan Python 3.10/3.11/3.12 sudah terinstall dan dicentang 'Add Python to PATH'.
    pause
    exit /b 1
)

echo.
echo [4/4] Menginstall seluruh library Bot Trading (CCXT, MT5, Pandas, Telegram, Dashboard)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo.
echo ============================================================================
echo   ✅ INSTALASI SELESAI! BOT SIAP DIJALANKAN 24 JAM NON-STOP!
echo ============================================================================
echo   Cara Menjalankan:
echo   - Klik 2x 'JALANKAN_SEMUA_DI_VPS.bat' untuk menyalakan seluruh sistem.
echo ============================================================================
echo.
pause
