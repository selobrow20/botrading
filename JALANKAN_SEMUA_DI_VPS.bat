@echo off
chcp 65001 >nul
title LAUNCHER UTAMA BOT TRADING 24/7 (VPS)
color 0A
cd /d "%~dp0"

echo ============================================================================
echo   🚀 MENYALAKAN SELURUH SISTEM BOT TRADING 24/7
echo ============================================================================
echo.
echo   [1/3] Menyalakan Web Dashboard Server (Port 8080)...
start "1. Web Dashboard (Port 8080)" cmd /k "JALANKAN_DASHBOARD.bat"
timeout /t 2 /nobreak >nul

echo   [2/3] Menyalakan Bot Eksekusi Binance Futures (Hermes Scanner)...
start "2. Bot Binance Futures" cmd /k "JALANKAN_BOT_FUTURES.bat"
timeout /t 2 /nobreak >nul

echo   [3/3] Menyalakan Bot Utama MT5 Gold (XAUUSD) & Saham IDX...
start "3. Bot Utama MT5 & IDX" cmd /k "JALANKAN_BOT.bat"

echo.
echo ============================================================================
echo   ✅ KETIGA SISTEM TELAH BERJALAN DI JENDELA MASING-MASING!
echo ============================================================================
echo   💡 Tips di VPS:
echo   - Biarkan ketiga jendela hitam tetap terbuka (jangan di-close).
echo   - Anda bebas menutup aplikasi Remote Desktop (klik X di atas RDP),
echo     bot di dalam VPS akan tetap hidup 24 jam penuh!
echo ============================================================================
echo.
timeout /t 5
