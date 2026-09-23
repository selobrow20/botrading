# Folder Materi Pembelajaran Trading (PDF)

Letakkan file-file buku atau modul PDF pembelajaran trading Anda di folder ini:
`d:\bot saham\materials\`

Contoh:
- `materials/buku_price_action.pdf`
- `materials/panduan_smc_orderblock.pdf`
- `materials/indikator_rsi_macd.pdf`

### Cara Menjalankan Ekstraksi Strategi dari PDF:
Gunakan perintah di terminal:
```bash
python main.py learn-pdf materials/nama_file.pdf
```

Sistem akan otomatis mengekstrak:
1. Indikator teknikal yang digunakan (RSI, Moving Average, Bollinger Bands, Volume, dll).
2. Aturan Beli (*Buy / Entry Rules*).
3. Aturan Jual (*Sell / Exit Rules*).
4. Rekomendasi Target Profit (TP) & Stop Loss (SL).
5. Menghasilkan definisi strategi YAML yang langsung dapat diuji dengan backtesting dan dijalankan oleh bot!

Anda juga bisa langsung melampirkan file PDF ke obrolan chat Antigravity kapan saja.
