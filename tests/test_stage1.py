import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

from tabulate import tabulate
from data.fetcher import DataFetcher
from data.storage import StockStorage


def test_stage_1():
    print("=" * 70)
    print("TEST TAHAP 1: DATA FETCHER & SQLITE STORAGE (BBCA.JK)")
    print("=" * 70)

    # 1. Inisialisasi Storage dan Fetcher
    storage = StockStorage()
    fetcher = DataFetcher(storage=storage)

    # Test auto normalize ticker
    assert fetcher.normalize_ticker("bbca") == "BBCA.JK"
    assert fetcher.normalize_ticker("BBCA.JK") == "BBCA.JK"
    print("✓ Normalisasi Ticker sukses ('bbca' -> 'BBCA.JK')")

    # 2. Ambil data harian (1d) untuk 1 tahun
    ticker = "BBCA.JK"
    print(f"\n[1/3] Mengambil data harian (1d) untuk {ticker}...")
    df_daily = fetcher.fetch_and_store(ticker, interval="1d", period="1y")

    assert not df_daily.empty, "Data harian tidak boleh kosong!"
    print(f"✓ Data harian berhasil diambil: {len(df_daily)} baris.")

    # 3. Baca kembali dari SQLite
    print(f"\n[2/3] Membaca data {ticker} dari database SQLite lokal...")
    df_loaded = storage.load_ohlcv(ticker, interval="1d")
    assert len(df_loaded) >= len(df_daily), "Jumlah data di database harus minimal sama dengan data yang diambil!"
    print(f"✓ Data di SQLite terverifikasi: {len(df_loaded)} baris.")
    print(f"  Rentang Waktu: {df_loaded.index[0].strftime('%Y-%m-%d')} s/d {df_loaded.index[-1].strftime('%Y-%m-%d')}")

    # Tampilkan 5 baris terakhir
    print("\nPreview 5 Baris Terakhir Data Harian:")
    preview_df = df_loaded.tail(5).copy()
    preview_df.index = preview_df.index.strftime("%Y-%m-%d")
    print(tabulate(preview_df, headers="keys", tablefmt="pretty", floatfmt=".1f"))

    # 4. Ambil data intraday (15m)
    print(f"\n[3/3] Mengambil data intraday (15m) untuk {ticker}...")
    df_intraday = fetcher.fetch_and_store(ticker, interval="15m", period="5d")
    assert not df_intraday.empty, "Data intraday tidak boleh kosong!"
    print(f"✓ Data intraday (15m) berhasil disimpan ke SQLite: {len(df_intraday)} baris.")
    
    preview_intra = df_intraday.tail(5).copy()
    preview_intra.index = preview_intra.index.strftime("%Y-%m-%d %H:%M")
    print("\nPreview 5 Baris Terakhir Data Intraday (15m):")
    print(tabulate(preview_intra, headers="keys", tablefmt="pretty", floatfmt=".1f"))

    print("\n" + "=" * 70)
    print("✅ TAHAP 1 BERHASIL TERVERIFIKASI PENUH!")
    print("=" * 70)


if __name__ == "__main__":
    test_stage_1()
