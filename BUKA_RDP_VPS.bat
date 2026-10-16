@echo off
title KONEKSI RDP KE VPS TRADING (45.149.187.231:3390)
color 0B
echo ========================================================
echo   MENYIMPAN LOGIN OTOMATIS RDP VPS (45.149.187.231:3390)
echo ========================================================
cmdkey /generic:TERMSRV/45.149.187.231 /user:Administrator /pass:Selobrow123.
echo.
echo Membuka Remote Desktop Connection ke 45.149.187.231:3390...
echo Jika muncul peringatan sertifikat kuning, klik "Yes" / "Don't ask me again".
start mstsc /v:45.149.187.231:3390
