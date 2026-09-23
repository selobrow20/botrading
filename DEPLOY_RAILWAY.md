# 🚂 Panduan Lengkap Deploy ke Railway (24/7 Cloud Bot)

Panduan ini menjelaskan langkah demi langkah cara men-deploy **Bot Analisis & Sinyal Trading Saham IDX** ke platform cloud [Railway](https://railway.app) agar bot berjalan otomatis 24 jam nonstop tanpa perlu komputer lokal Anda menyala.

---

## 📋 Ringkasan File Konfigurasi Railway yang Sudah Disediakan
Project ini sudah dilengkapi dengan file siap pakai untuk Railway:
- [`Dockerfile`](file:///d:/bot%20saham/Dockerfile): Container Python 3.12 dengan zona waktu otomatis `Asia/Jakarta` (WIB).
- [`Procfile`](file:///d:/bot%20saham/Procfile): Menjalankan proses worker `python main.py run-all`.
- [`railway.json`](file:///d:/bot%20saham/railway.json): Konfigurasi build otomatis & auto-restart jika terjadi error jaringan.

---

## 🛠 Langkah 1: Push Project ke GitHub

1. Inisialisasi git di folder project (jika belum):
   ```bash
   git init
   git add .
   git commit -m "Initial commit bot saham IDX"
   ```
2. Buat repository baru di [GitHub](https://github.com/new) (disarankan **Private** agar token dan strategi Anda aman).
3. Hubungkan dan push kode ke GitHub:
   ```bash
   git branch -M main
   git remote add origin https://github.com/USERNAME/NAMA-REPO.git
   git push -u origin main
   ```

---

## 🚀 Langkah 2: Deploy di Dashboard Railway

1. Buka [railway.app](https://railway.app) dan login menggunakan akun GitHub Anda.
2. Klik tombol **"+ New Project"**.
3. Pilih opsi **"Deploy from GitHub repo"**.
4. Cari dan pilih repository GitHub bot saham Anda yang tadi baru di-push.
5. Railway akan mendeteksi [`Dockerfile`](file:///d:/bot%20saham/Dockerfile) dan langsung memulai proses build secara otomatis.

---

## 🔑 Langkah 3: Setting Environment Variables (Wajib)

Di dashboard project Railway Anda:
1. Klik service bot Anda, lalu pilih tab **"Variables"**.
2. Klik **"+ New Variable"** dan masukkan variabel-variabel penting berikut:

| Nama Variabel | Contoh Nilai | Penjelasan |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | `123456789:ABCdefGhIJK...` | Token dari @BotFather |
| `TELEGRAM_CHAT_ID` | `987654321` | Chat ID Anda dari @userinfobot |
| `TZ` | `Asia/Jakarta` | Memastikan jam bursa WIB akurat |
| `APP_ENV` | `production` | Mode produksi |
| `DATABASE_PATH` | `/app/data/stock_data.db` | Lokasi database SQLite |

3. Klik **"Deploy"** atau **"Save"** agar variabel diterapkan.

---

## 💾 Langkah 4: Menambahkan Persistent Volume (Sangat Disarankan)

Secara default, container cloud bersifat *ephemeral* (data file SQLite akan ter-reset saat ada update kode). Agar data histori candle dan histori sinyal tersimpan permanen:
1. Di dashboard Railway, klik kanan atau pilih menu **"+ New"** di canvas project Anda.
2. Pilih **"Volume"**.
3. Hubungkan Volume tersebut ke service bot Anda.
4. Set **Mount Path** ke:
   ```
   /app/data
   ```
*Dengan cara ini, file database `stock_data.db` tidak akan pernah hilang meskipun bot di-restart atau di-update berkali-kali.*

---

## 🔍 Langkah 5: Memeriksa Log & Menguji Bot

1. Buka tab **"Deployments"** di Railway, lalu klik deployment yang sedang berjalan dan buka **"View Logs"**.
2. Anda akan melihat log seperti berikut:
   ```text
   [INFO] Inisialisasi APScheduler dengan interval 15 menit...
   [INFO] Status Pasar IDX: Bursa Buka (Sesi 1: 09:00 - 11:30 WIB)
   [INFO] Memulai Telegram bot polling listener...
   🚀 SCHEDULER BOT AKTIF! Memantau tiap 15 menit.
   ```
3. Buka aplikasi **Telegram** di smartphone Anda, lalu chat ke bot Anda:
   - Ketik `/status` $\to$ Bot akan merespons dengan status running & strategi aktif.
   - Ketik `/watchlist` $\to$ Bot akan menampilkan daftar saham yang sedang dipantau.
   - Ketik `/lasthistory` $\to$ Bot akan menampilkan sinyal terakhir dari database.

---

## 🔄 Cara Memperbarui Strategi di Railway

Jika di kemudian hari Anda ingin mengubah daftar saham atau menambahkan aturan strategi baru:
1. Edit file [`config/config.yaml`](file:///d:/bot%20saham/config/config.yaml) di komputer Anda.
2. Lakukan commit dan push ke GitHub:
   ```bash
   git add config/config.yaml
   git commit -m "Update strategi trading"
   git push origin main
   ```
3. Railway akan otomatis mendeteksi perubahan tersebut dan melakukan **redeploy otomatis** dalam hitungan detik tanpa downtime!
