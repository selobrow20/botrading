import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

from tabulate import tabulate
from scheduler.run_scheduler import is_idx_market_open, PipelineRunner
from data.storage import StockStorage
from strategy.signal_engine import SignalResult


def test_stage_6():
    print("=" * 75)
    print("TEST TAHAP 6: SCHEDULER, JAM BURSA IDX & DEDUPLIKASI SINYAL")
    print("=" * 75)

    tz = ZoneInfo("Asia/Jakarta")

    # 1. Verifikasi Filter Jam Bursa Efek Indonesia (IDX)
    print("\n[1/3] Menguji Logika Filter Jam Bursa IDX (WIB)...")
    simulated_times = [
        (datetime(2026, 9, 21, 10, 0, tzinfo=tz), True, "Senin 10:00 (Sesi 1)"),
        (datetime(2026, 9, 21, 12, 15, tzinfo=tz), False, "Senin 12:15 (Istirahat Siang)"),
        (datetime(2026, 9, 21, 14, 30, tzinfo=tz), True, "Senin 14:30 (Sesi 2)"),
        (datetime(2026, 9, 25, 12, 30, tzinfo=tz), False, "Jumat 12:30 (Jeda Sholat Jumat)"),
        (datetime(2026, 9, 25, 14, 15, tzinfo=tz), True, "Jumat 14:15 (Sesi 2 Jumat)"),
        (datetime(2026, 9, 26, 10, 0, tzinfo=tz), False, "Sabtu 10:00 (Akhir Pekan)"),
    ]

    for dt_sim, expected_open, desc in simulated_times:
        is_open, reason = is_idx_market_open(dt=dt_sim, config={"scheduler": {"check_market_hours": True}})
        assert is_open == expected_open, f"Gagal pada uji {desc}! Diharapkan {expected_open}, didapat {is_open}."
        print(f"  ✓ {desc}: {'BUKA' if is_open else 'TUTUP'} [{reason}]")

    # 2. Uji Deduplikasi Sinyal
    print("\n[2/3] Menguji Logika Pencegahan Sinyal Duplikat (Deduplikasi)...")
    storage = StockStorage()
    runner = PipelineRunner(storage=storage)

    import time
    unique_ticker = f"DUMMY_{int(time.time() * 1000)}.JK"

    # Simulasikan Sinyal Baru
    sig_test = SignalResult(
        ticker=unique_ticker,
        strategy_name="Test_Strategy",
        signal="BUY",
        price=1000.0,
        candle_time="2026-09-23 10:00:00",
        reasons=["Test Buy Trigger"],
    )

    # Pengecekan awal: harus terdeteksi sebagai sinyal baru
    is_dup1, reason1 = runner._check_duplicate(sig_test)
    assert not is_dup1, "Sinyal pertama tidak boleh dianggap duplikat!"
    print(f"  ✓ Sinyal Pertama: {reason1} (Notifikasi diizinkan)")

    # Simpan sebagai sudah dinotifikasi
    storage.save_signal(
        ticker=sig_test.ticker,
        strategy_name=sig_test.strategy_name,
        signal_type=sig_test.signal,
        price=sig_test.price,
        reasons=sig_test.reasons,
        candle_time=sig_test.candle_time,
        is_notified=True,
    )

    # Pengecekan kedua dengan candle_time yang sama: harus terdeteksi DUPLIKAT
    is_dup2, reason2 = runner._check_duplicate(sig_test)
    assert is_dup2, "Sinyal yang sama pada candle yang sama harus dicegah (duplikat)!"
    print(f"  ✓ Pengecekan Sinyal Ulang: DUPLIKAT TERDETEKSI [{reason2}] (Spam notifikasi dicegah)")

    # 3. Uji Eksekusi Penuh Pipeline
    print("\n[3/3] Menjalankan 1 Siklus Penuh Pipeline untuk Watchlist...")
    # Batasi watchlist uji ke BBCA.JK dan BBRI.JK agar cepat
    runner.config["watchlist"] = ["BBCA.JK", "BBRI.JK"]
    pipeline_res = runner.run_pipeline(force_run=True)

    print("\nHasil Eksekusi Pipeline:")
    print(f"  • Waktu Eksekusi    : {pipeline_res['timestamp']}")
    print(f"  • Saham Diproses    : {pipeline_res['processed']}")
    print(f"  • Sinyal Terpicu    : {pipeline_res['signals_triggered']}")
    print(f"  • Notifikasi Baru   : {pipeline_res['signals_notified']}")

    details = pipeline_res["details"]
    table_rows = []
    for d in details:
        table_rows.append([
            d["ticker"],
            d["signal"],
            f"Rp {d['price']:,.0f}",
            d["candle_time"],
            "YA" if d["notified"] else "TIDAK (Deduplikasi / HOLD)",
        ])

    print("\nTabel Pemrosesan Watchlist:")
    print(tabulate(table_rows, headers=["Ticker", "Sinyal", "Harga", "Waktu Candle", "Kirim Notifikasi"], tablefmt="pretty"))

    print("\n" + "=" * 75)
    print("✅ TAHAP 6 BERHASIL TERVERIFIKASI PENUH!")
    print("=" * 75)


if __name__ == "__main__":
    test_stage_6()
