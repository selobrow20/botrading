@echo off
title MT5 VIP AUTO-COPIER (9 BUKU PDF CONFLUENCE)
color 0B
cd /d "%~dp0"
set COPIER_IN_LOOP=1

echo ======================================================================
echo    MEMULAI AUTO-COPIER MT5 MEMBER (VIP 9 BUKU PDF)
echo ======================================================================
echo.
echo Petunjuk:
echo 1. Pastikan aplikasi MetaTrader 5 kamu sudah dalam keadaan LOGIN ^& TERBUKA.
echo 2. Tombol 'Algo Trading' di toolbar atas MT5 WAJIB AKTIF (Warna Hijau).
echo 3. Sinyal trading hanya akan aktif jika akun Telegram kamu sudah
echo    DISETUJUI (APPROVED) oleh Master Admin (@selobrow).
echo 4. Fitur Live Auto-Update AKTIF: Copier akan otomatis memperbarui diri
echo    di latar belakang tanpa perlu menutup aplikasi!
echo ======================================================================
echo.

python -m pip install telethon MetaTrader5 >nul 2>&1

:run_loop
python client_copier.py
if errorlevel 42 (
    echo.
    echo ======================================================================
    echo 🔄 [LIVE AUTO-UPDATE] Memuat ulang Copier ke versi terbaru...
    echo ======================================================================
    timeout /t 2 /nobreak >nul
    goto run_loop
)

echo.
pause
