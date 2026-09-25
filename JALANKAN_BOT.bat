@echo off
title BOT TRADING AUTO-TRADER MT5 (XAU/USD HFM)
color 0A
cd /d "%~dp0"

echo ======================================================================
echo    MEMULAI BOT TRADING AUTO-TRADER (MT5 HFM + TELEGRAM NOTIFIER)
echo ======================================================================
echo.
echo [1/2] Memeriksa virtual environment...
if not exist ".\.venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment .venv tidak ditemukan!
    pause
    exit /b
)

echo [2/2] Menjalankan Bot Sinyal 7 PDF Confluence & MT5 Auto-Trader...
echo.
echo Tips:
echo - Pastikan aplikasi MetaTrader 5 HFM tetap terbuka di latar belakang.
echo - Tekan Ctrl + C di jendela ini jika ingin mematikan bot secara aman.
echo.
echo ======================================================================
echo.

.\.venv\Scripts\python.exe main.py run-all

echo.
echo Bot telah berhenti.
pause
