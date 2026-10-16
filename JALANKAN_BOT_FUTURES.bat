@echo off
chcp 65001 >nul
title Bot Eksekusi Binance Futures (Hermes Signals)
cd /d "%~dp0"
echo ========================================================
echo   MENJALANKAN BOT EKSEKUSI SINYAL BINANCE FUTURES
echo ========================================================
echo.
.\.venv\Scripts\python.exe friend_bot_executor_example.py
pause
