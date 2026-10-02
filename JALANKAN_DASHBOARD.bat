@echo off
chcp 65001 >nul
title Botrading - 3D Isometric Trading Office Dashboard
cls
echo ======================================================================
echo  🏢 BOTRADING 3D ISOMETRIC OFFICE & COPIER MONITOR
echo ======================================================================
echo.
echo  [+] Memulai server dashboard lokal...
echo  [+] Menghubungkan ke MetaTrader 5 (MT5)...
echo  [+] Membuka dashboard 3D di browser otomatis...
echo.
echo  URL: http://127.0.0.1:8080
echo.
echo  Tutup jendela ini atau tekan Ctrl+C jika ingin mematikan dashboard.
echo ======================================================================
echo.
python dashboard_server.py
pause
