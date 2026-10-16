@echo off
chcp 65001 >nul
title Botrading - Command Center & Live Web Dashboard
cls
echo ======================================================================
echo  🚀 BOTRADING UNIFIED COMMAND CENTER & WEB DASHBOARD (v2.0)
echo ======================================================================
echo.
echo  [+] Menghubungkan ke Mesin Bot (main.py)...
echo  [+] Menghubungkan ke MetaTrader 5 (MT5) Lokal...
echo  [+] Menghubungkan ke Auto-Pump Sniper Binance & SQLite...
echo  [+] Membuka Dashboard di Browser Otomatis...
echo.
echo  📍 URL Akses di PC Lokal   : http://127.0.0.1:8080
echo  📱 URL Akses dari HP/WiFi  : http://192.168.1.4:8080
echo.
echo  Tutup jendela ini atau tekan Ctrl+C jika ingin mematikan dashboard.
echo ======================================================================
echo.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" dashboard_server.py
) else (
    python dashboard_server.py
)

pause
