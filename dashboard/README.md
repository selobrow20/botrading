# 🏢 Botrading 3D Isometric Office & Copier Dashboard

Dashboard visual interaktif berbasis **HTML5, CSS3, JavaScript (Three.js), dan Python** untuk memantau aktivitas bot trading Telegram & copy trading MT5 secara real-time dengan tampilan **Isometric Virtual Office Floor Plan** (mirip simulasi kantor trading 3D).

---

## 🌟 Fitur Utama

1. **Tampilan 3D Isometric Office (Sesuai Referensi UI)**:
   - **Ruang Server Master VPS**: Terletak di sayap kiri dengan 2 lemari rack server hitam dan LED indikator berkedip, memvisualisasikan Master Bot (`@selo_saham_bot`) yang berjalan di cloud/VPS.
   - **Meja Kerja Member Copier**: Meja-meja kayu dengan laptop/monitor berpendar dan karakter 3D (avatar) yang sedang mengetik di depan laptop.
   - **Karakter Member & Tag Nama**:
     - 👑 **Master Bot (VPS)**: Server provider sinyal 9 Buku PDF.
     - 💻 **Deden (You - Local MT5)**: Akun cent lokal MT5 Anda (HFMarkets #114201000).
     - 🧑‍💼 **Luke, Allan, Ben, Cory, Susie, Andrew**: Anggota copier lain di trading floor.
   - **Fasilitas Kantor**: Meja rapat bundar (conference table), meja diskusi, meja manajer L-shaped dengan rak buku, sofa santai (lounge), meja ping pong hijau, dan tanaman hias.

2. **Visual Efek Distribusi Sinyal (Signal Wave Broadcast FX)**:
   - Saat Master Bot mengirimkan sinyal (misal: `BUY XAUUSD`), gelombang pulsa energi neon memancar dari Ruang Server VPS ke seluruh meja laptop member.
   - Layar laptop member menyala hijau (BUY) atau merah (SELL).
   - Muncul balon obrolan (*speech bubble*) di atas kepala tiap member berisi tiket order MT5 dan status eksekusi.
   - Efek suara interaktif (*audio FX synthesizer*) Web Audio API.

3. **Terminal PowerShell Real-Time (Persis Screenshot Console)**:
   - Drawer terminal bergaya Windows PowerShell gelap.
   - Menampilkan riwayat log persis seperti di console:
     - `⚡ [HH:MM:SS] SINYAL DITERIMA DARI MASTER BOT:`
     - `   Aksi  : BUY XAUUSD`
     - `   Entry : $4,168.92 | TP: $4,173.49 | SL: $4,164.49`
     - `   ✅ [ORDER MT5 SUKSES] #15247953082 BUY 0.05 Lot @ $4,169.26 pada XAUUSDc`
     - `   ❌ [ORDER GAGAL] RetCode: 10016 - Invalid stops`

4. **Integrasi Langsung ke MetaTrader 5 (MT5)**:
   - Otomatis membaca status akun MT5 Windows Anda: Login, Server, Balance, Equity, Margin, dan posisi terbuka secara live.
   - Terhubung dengan `member_copier/client_copier.py`.

5. **Panel Interaktif**:
   - **Broadcast Sinyal Uji**: Kirim sinyal test (BUY/SELL, Entry, TP, SL) untuk melihat reaksi visual kantor dan eksekusi MT5.
   - **Profil Member**: Klik meja mana saja di 3D untuk melihat info broker, balance, lot, dan posisi terbuka.
   - **Kontrol Kamera**: Pilihan sudut pandang Isometric, Fokus Meja Deden, Ruang Server, dan Top-Down.
   - **Tema & Audio**: Ganti tema Cyber Night / Daylight Office dan tombol mute/unmute audio.

---

## 🚀 Cara Menjalankan

### Cara 1: Menggunakan Batch File (Paling Cepat & Mudah)
Cukup **klik ganda (double-click)** file:
```
JALANKAN_DASHBOARD.bat
```
Server Python otomatis aktif dan membuka browser ke `http://127.0.0.1:8080`.

### Cara 2: Melalui Terminal PowerShell / CMD
```powershell
python dashboard_server.py
```
Lalu buka browser di `http://127.0.0.1:8080`.

### Cara 3: Mode Standalone Langsung (Tanpa Server)
Buka langsung file [dashboard/index.html](file:///c:/Projects/botrading/dashboard/index.html) di browser Anda (Google Chrome / Edge). Dashboard akan otomatis berjalan dalam mode simulasi interaktif penuh.
