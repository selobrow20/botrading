@echo off
setlocal enabledelayedexpansion
set "REPO_DIR=%~dp0.."
if exist "%REPO_DIR%\.git" (
    cd /d "%REPO_DIR%"
) else if exist "d:\bot saham\.git" (
    cd /d "d:\bot saham"
) else if exist "c:\Projects\botrading\.git" (
    cd /d "c:\Projects\botrading"
)

git fetch origin main >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Gagal menghubungi GitHub.
    exit /b 1
)

for /f %%a in ('git rev-parse HEAD') do set LOCAL_HASH=%%a
for /f %%a in ('git rev-parse origin/main') do set REMOTE_HASH=%%a

if "!LOCAL_HASH!" neq "!REMOTE_HASH!" (
    echo [UPDATE] Ada commit baru di remote. Menjalankan git pull...
    git pull origin main
    echo [SUCCESS] Git pull selesai.
) else (
    echo [OK] Repository sudah up to date.
)
