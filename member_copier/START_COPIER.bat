@echo off
title MT5 VIP AUTO-COPIER (9 BUKU PDF CONFLUENCE)
color 0B
cd /d "%~dp0"

echo ======================================================================
echo    MEMULAI AUTO-COPIER MT5 MEMBER (VIP 9 BUKU PDF)
echo ======================================================================
echo.
echo Petunjuk:
echo 1. Pastikan aplikasi MetaTrader 5 kamu sudah dalam keadaan LOGIN ^& TERBUKA.
echo 2. Ukuran lot default: 0.05 lot (sama persis dengan akun Master).
echo 3. Sinyal trading hanya akan aktif jika akun Telegram kamu sudah
echo    DISETUJUI (APPROVED) oleh Master Admin (@selobrow).
echo ======================================================================
echo.

python -m pip install telethon MetaTrader5 >nul 2>&1
python client_copier.py

echo.
pause
