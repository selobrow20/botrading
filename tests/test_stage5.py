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

from data.storage import StockStorage
from strategy.signal_engine import SignalResult
from notify.telegram_bot import TelegramNotifier, TelegramBotCommands


def test_stage_5():
    print("=" * 75)
    print("TEST TAHAP 5: MODUL NOTIFIKASI & COMMAND BOT TELEGRAM")
    print("=" * 75)

    storage = StockStorage()
    notifier = TelegramNotifier(storage=storage)

    # 1. Simulasikan Sinyal BUY Baru
    print("\n[1/3] Menguji Pembuatan Kartu Notifikasi Sinyal BUY...")
    buy_signal = SignalResult(
        ticker="BBCA.JK",
        strategy_name="Default_RSI_EMA_Volume",
        signal="BUY",
        price=6275.0,
        candle_time="2026-09-23 14:30:00",
        reasons=[
            "RSI Oversold (28.4 < 30)",
            "Harga Close (Rp 6,275) > EMA 50 (Rp 6,100)",
            "Volume Surge: 1.82x rata-rata 20 periode (> 1.5x)",
        ],
        indicators_snapshot={
            "rsi": 28.4,
            "ema_50": 6100.0,
            "volume_ratio": 1.82,
        },
    )

    formatted_msg = notifier.format_signal_message(buy_signal)
    print("Tampilan Pesan Kartu Telegram:")
    print("-" * 50)
    print(formatted_msg)
    print("-" * 50)

    # Simpan sinyal ke database agar tercatat di history
    sig_id_1 = storage.save_signal(
        ticker=buy_signal.ticker,
        strategy_name=buy_signal.strategy_name,
        signal_type=buy_signal.signal,
        price=buy_signal.price,
        reasons=buy_signal.reasons,
        candle_time=buy_signal.candle_time,
        is_notified=True,
    )
    print(f"✓ Sinyal BUY berhasil dicatat ke SQLite (ID: {sig_id_1})")

    # 2. Simulasikan Sinyal SELL
    print("\n[2/3] Menguji Pembuatan Kartu Notifikasi Sinyal SELL...")
    sell_signal = SignalResult(
        ticker="BBRI.JK",
        strategy_name="Default_RSI_EMA_Volume",
        signal="SELL",
        price=4850.0,
        candle_time="2026-09-23 14:45:00",
        reasons=[
            "RSI Overbought (73.5 > 70)",
            "Harga menembus ke bawah EMA 20 (Rp 4,890)",
        ],
        indicators_snapshot={
            "rsi": 73.5,
            "ema_20": 4890.0,
            "volume_ratio": 1.15,
        },
    )

    sig_id_2 = storage.save_signal(
        ticker=sell_signal.ticker,
        strategy_name=sell_signal.strategy_name,
        signal_type=sell_signal.signal,
        price=sell_signal.price,
        reasons=sell_signal.reasons,
        candle_time=sell_signal.candle_time,
        is_notified=True,
    )
    print(f"✓ Sinyal SELL berhasil dicatat ke SQLite (ID: {sig_id_2})")

    # Test pengiriman sinyal (dalam mode simulasi karena token dummy di development)
    send_success = notifier.send_signal(buy_signal)
    assert send_success is True, "Pengiriman sinyal (mode mock) harus bernilai True!"
    print("✓ Fungsi send_signal() berjalan lancar tanpa error.")

    # 3. Uji Handler Command Riwayat (/lasthistory)
    print("\n[3/3] Menguji Ekstraksi Riwayat untuk Command /lasthistory...")
    recent_signals = storage.get_recent_signals(limit=5)
    assert len(recent_signals) >= 2, "Database harus memuat minimal 2 sinyal yang baru ditambahkan!"
    print(f"✓ Berhasil mengambil {len(recent_signals)} riwayat sinyal dari SQLite:")
    for s in recent_signals:
        print(f"  - [{s['signal_type']}] {s['ticker']} @ Rp {s['price']:,.0f} ({s['candle_time']})")

    print("\n" + "=" * 75)
    print("✅ TAHAP 5 BERHASIL TERVERIFIKASI PENUH!")
    print("=" * 75)


if __name__ == "__main__":
    test_stage_5()
