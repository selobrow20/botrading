# Auto Git Pull Script for Master Server
# Digunakan untuk cron job / scheduler tiap 5 menit
$repoPath = "d:\bot saham"
Set-Location -Path $repoPath

try {
    # 1. Fetch remote updates
    git fetch origin main 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [WARNING] Gagal menghubungi GitHub origin/main." -ForegroundColor Yellow
        exit 1
    }

    # 2. Bandingkan commit hash lokal vs remote
    $localHash = (git rev-parse HEAD).Trim()
    $remoteHash = (git rev-parse origin/main).Trim()

    if ($localHash -ne $remoteHash) {
        Write-Host "[(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [UPDATE] Terdeteksi kodingan baru di GitHub ($($localHash.Substring(0,7)) -> $($remoteHash.Substring(0,7)))!" -ForegroundColor Green
        git pull origin main
        $latestCommit = (git log -1 --pretty=format:"%h - %s (%an)").Trim()
        Write-Host "[(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [SUCCESS] Berhasil pull: $latestCommit" -ForegroundColor Green
    } else {
        Write-Host "[(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [OK] Repo up-to-date ($($localHash.Substring(0,7))). Tidak ada kodingan baru." -ForegroundColor Gray
    }
} catch {
    Write-Host "Error pada auto pull: $_" -ForegroundColor Red
}
