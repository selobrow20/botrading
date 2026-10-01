"""
Unit Test untuk Eksekutor MetaTrader 5 (MT5 Bridge & Auto-Trader).
Menguji:
1. Inisialisasi Singleton & konfigurasi default.
2. Gerbang ketat filter 9 Buku PDF (menolak jika konfluensi < 65%).
3. Eksekusi order BUY/SELL dengan TP & SL otomatis.
4. Manajemen posisi terbuka & penutupan posisi.
5. Perhitungan lot dinamis berbasis risiko.
"""

import pytest
from unittest.mock import MagicMock, patch
from strategy.signal_engine import SignalResult
from trading.mt5_bridge import MT5Bridge


def test_mt5_bridge_singleton_and_init():
    bridge1 = MT5Bridge(simulation_mode=True)
    bridge2 = MT5Bridge(simulation_mode=True)
    assert bridge1 is bridge2
    assert bridge1.simulation_mode is True
    assert bridge1.magic_number > 0
    assert bridge1.default_lot > 0


def test_mt5_9_pdf_strict_gatekeeper():
    """Memastikan order DITOLAK jika belum memenuhi standar konfluensi Grade A (>=65%) 9 Buku PDF."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"

    # 1. Sinyal Lemah (< 65%) -> Harus DITOLAK demi menjaga modal & win rate
    weak_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=2750.0,
        candle_time="2026-09-25T08:00:00",
        take_profit_price=2775.0,
        stop_loss_price=2735.0,
        pdf_confluence_score=50.0,  # 50% < 65%
        setup_grade="Grade C",
    )
    res_weak = bridge.execute_signal(weak_sig)
    assert res_weak["success"] is False
    assert res_weak["status"] == "pdf_rejected"
    assert "9 Buku PDF" in res_weak["message"] or "Buku PDF" in res_weak["message"]

    # 2. Sinyal Kuat (>= 65% Grade A) -> Harus DITERIMA & DIEKSEKUSI
    strong_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=2750.0,
        candle_time="2026-09-25T08:00:00",
        take_profit_price=2775.0,
        stop_loss_price=2735.0,
        pdf_confluence_score=80.0,  # 80% >= 65%
        setup_grade="Grade A",
    )
    res_strong = bridge.execute_signal(strong_sig)
    assert res_strong["success"] is True
    assert res_strong["status"] == "executed"
    assert res_strong["ticket"] > 0
    assert res_strong["action"] == "BUY"
    assert res_strong["tp"] == 2775.0
    assert res_strong["sl"] == 2735.0


def test_mt5_order_lifecycle_and_positions():
    """Menguji siklus buka posisi, cek posisi terbuka, dan tutup posisi di MT5."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"
    bridge._simulated_positions.clear()

    # Buka order SELL Gold
    sell_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="SELL",
        price=2760.0,
        candle_time="2026-09-25T08:00:00",
        take_profit_price=2740.0,
        stop_loss_price=2770.0,
        pdf_confluence_score=75.0,
        setup_grade="Grade A",
    )
    res = bridge.execute_signal(sell_sig)
    assert res["success"] is True
    ticket = res["ticket"]

    # Cek posisi terbuka
    positions = bridge.get_open_positions()
    assert len(positions) == 1
    assert positions[0]["ticket"] == ticket
    assert positions[0]["type"] == "SELL"
    assert positions[0]["tp"] == 2740.0
    assert positions[0]["sl"] == 2770.0

    # Tutup posisi by ticket
    close_res = bridge.close_position(ticket)
    assert close_res["success"] is True
    assert len(bridge.get_open_positions()) == 0


def test_mt5_disabled_mode_does_not_execute():
    """Jika auto-trade dimatikan, order tidak boleh dieksekusi."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = False

    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=2750.0,
        candle_time="2026-09-25T08:00:00",
        take_profit_price=2775.0,
        stop_loss_price=2735.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
    )
    res = bridge.execute_signal(sig)
    assert res["success"] is False
    assert res["status"] == "disabled"


def test_mt5_dynamic_lot_sizing_by_confluence():
    """Menguji penentuan ukuran lot: 0.05 lot untuk momen super bagus (Grade A+), 0.01 lot untuk standar/riskan."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"

    # 1. Momen Super Bagus (Grade A+ >= 80%) -> 0.05 lot
    super_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=2750.0,
        candle_time="2026-09-25T08:00:00",
        take_profit_price=2775.0,
        stop_loss_price=2735.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
    )
    bridge._simulated_positions.clear()
    res_super = bridge.execute_signal(super_sig)
    assert res_super["success"] is True
    assert res_super["volume"] == 0.05

    # 2. Momen Standar / Masih Riskan (Grade A 65% - 79%) -> 0.01 lot
    bridge._simulated_positions.clear()
    standard_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=2750.0,
        candle_time="2026-09-25T08:00:00",
        take_profit_price=2775.0,
        stop_loss_price=2735.0,
        pdf_confluence_score=70.0,
        setup_grade="Grade A",
    )
    res_standard = bridge.execute_signal(standard_sig)
    assert res_standard["success"] is True
    assert res_standard["volume"] == 0.01


def test_mt5_trading_hours_restriction():
    """Menguji pembatasan jam aktif trading (misal sesi malam 19:00 - 23:00 WIB)."""
    from datetime import time
    from unittest.mock import patch
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge._simulated_positions.clear()

    # Mode 24 jam nonstop -> selalu True
    bridge.trading_hours = "all"
    in_range, msg = bridge.is_within_trading_hours()
    assert in_range is True

    # Mode malam 19:00 - 23:00 WIB
    bridge.trading_hours = "19:00-23:00"

    strong_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=2750.0,
        candle_time="2026-09-25T08:00:00",
        take_profit_price=2775.0,
        stop_loss_price=2735.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
    )

    # Mock waktu siang jam 12:00 WIB (di luar jam)
    with patch("trading.mt5_bridge.datetime") as mock_dt:
        mock_now = MagicMock()
        mock_now.time.return_value = time(12, 0)
        mock_dt.now.return_value = mock_now

        in_range, msg = bridge.is_within_trading_hours()
        assert in_range is False
        assert "Di luar jam aktif trading" in msg

        res = bridge.execute_signal(strong_sig)
        assert res["success"] is False
        assert res["status"] == "outside_hours"

    # Mock waktu malam jam 20:30 WIB (dalam jam aktif)
    with patch("trading.mt5_bridge.datetime") as mock_dt:
        mock_now = MagicMock()
        mock_now.time.return_value = time(20, 30)
        mock_dt.now.return_value = mock_now

        in_range, msg = bridge.is_within_trading_hours()
        assert in_range is True
        assert "Dalam jam aktif trading" in msg

        res = bridge.execute_signal(strong_sig)
        assert res["success"] is True
        assert res["status"] == "executed"

    # Kembalikan ke all
    bridge.trading_hours = "all"


def test_mt5_double_entry_prevention():
    """Memastikan sistem menolak membuka posisi baru jika posisi untuk simbol yang sama masih aktif."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"
    bridge._simulated_positions.clear()

    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=2750.0,
        candle_time="2026-09-25T08:00:00",
        take_profit_price=2775.0,
        stop_loss_price=2735.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
    )

    # Entry pertama sukses
    res1 = bridge.execute_signal(sig)
    assert res1["success"] is True
    assert res1["status"] == "executed"

    # Entry kedua ditolak karena posisi masih berjalan / harga terlalu dekat
    res2 = bridge.execute_signal(sig)
    assert res2["success"] is False
    assert res2["status"] in ("already_open", "too_close_grid")
    assert ("aktif di MT5" in res2["message"]) or ("Penumpukan Posisi Dicegah" in res2["message"])


def test_mt5_modify_position_and_trailing():
    """Menguji modifikasi posisi (Trailing Stop & BEP Lock)."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge._simulated_positions = [
        {"ticket": 999, "symbol": "XAUUSD", "sl": 4120.0, "tp": 4170.0}
    ]

    res = bridge.modify_position(999, sl=4135.5, tp=4145.0)
    assert res["success"] is True
    assert res["sl"] == 4135.5
    assert res["tp"] == 4145.0
    assert bridge._simulated_positions[0]["sl"] == 4135.5
    assert bridge._simulated_positions[0]["tp"] == 4145.0


def test_mt5_grid_spacing_prevention():
    """Menguji penolakan order jika jarak harga dengan posisi aktif terlalu dekat (< $4.0 USD)."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"
    bridge._simulated_positions = [
        {"ticket": 100, "symbol": "XAUUSD", "type": "BUY", "price_open": 4135.0, "volume": 0.05}
    ]

    # Mock is_cent_account True dan max_positions_cent=3 agar mengizinkan multi-posisi untuk menguji grid spacing
    with patch.object(bridge, "is_cent_account", return_value=True), \
         patch.dict(bridge.config.get("mt5", {}), {"max_positions_cent": 3}):
        sig_too_close = SignalResult(
            ticker="XAUUSD",
            strategy_name="Master_Confluence",
            signal="BUY",
            price=4135.5,  # Hanya selisih $0.5 (< $1.0 min grid spacing)
            candle_time="2026-09-29T10:00:00",
            take_profit_price=4170.0,
            stop_loss_price=4125.0,
            pdf_confluence_score=85.0,
            setup_grade="Grade A+",
            market_regime="Momentum Panjang",
        )
        res = bridge.execute_signal(sig_too_close)
        assert res["success"] is False
        assert res["status"] == "too_close_grid"
        assert "Penumpukan Posisi Dicegah" in res["message"]


def test_mt5_midnight_sleep_guard_and_daytime_usc_unlimited():
    """
    Menguji aturan:
    1. Akun USC di jam siang/normal (pantauan user) BEBAS dari blokir daily loss.
    2. Akun USC di jam tidur malam (02:00 - 04:30 WIB) dikawal Midnight Sleep Guard (-50 USC).
    3. Akun USD Standard tetap dikawal Daily Loss 24/7 (-$50 USD).
    """
    from datetime import datetime, time
    from zoneinfo import ZoneInfo
    bridge = MT5Bridge(simulation_mode=True)
    bridge._force_check_guards = True

    # 1. Akun USC di Jam Siang (10:00 WIB) walau ada loss hari ini -> Tetap LOLOS (tidak diblokir)
    fake_deals = [
        {"profit": -80.0, "time_wib": "2026-09-30 09:30:00"}
    ]
    with patch.object(bridge, "is_cent_account", return_value=True), \
         patch.object(bridge, "get_closed_deals", return_value=fake_deals), \
         patch("trading.mt5_bridge.datetime") as mock_dt, \
         patch("trading.mt5_bridge.mt5.symbol_info_tick", return_value=None), \
         patch("notify.telegram_bot.TelegramNotifier"):
        mock_now = MagicMock()
        mock_now.time.return_value = time(10, 0)
        mock_now.strftime.return_value = "2026-09-30"
        mock_dt.now.return_value = mock_now

        ok, msg, status = bridge.check_overnight_safety_guards("XAUUSDc", score=80.0)
        assert ok is True
        assert status == "ok"

    # 2. Akun USC di Jam Tengah Malam (03:00 WIB) dengan loss midnight >= 50 USC -> DIBLOKIR Midnight Sleep Guard
    midnight_deals = [
        {"profit": -55.0, "time_wib": "2026-09-30 02:45:00"}
    ]
    with patch.object(bridge, "is_cent_account", return_value=True), \
         patch.object(bridge, "get_closed_deals", return_value=midnight_deals), \
         patch("trading.mt5_bridge.datetime") as mock_dt, \
         patch("trading.mt5_bridge.mt5.symbol_info_tick", return_value=None), \
         patch("notify.telegram_bot.TelegramNotifier"):
        mock_now = MagicMock()
        mock_now.time.return_value = time(3, 0)
        mock_now.strftime.return_value = "2026-09-30"
        mock_dt.now.return_value = mock_now

        ok, msg, status = bridge.check_overnight_safety_guards("XAUUSDc", score=80.0)
        assert ok is False
        assert status == "midnight_loss_limit_reached"
        assert "MIDNIGHT SLEEP GUARD AKTIF" in msg

    # 3. Akun USD Standard (is_cent = False) di Jam Siang (14:00 WIB) dengan loss >= $50 USD -> DIBLOKIR 24/7 Daily Loss
    usd_deals = [
        {"profit": -60.0, "time_wib": "2026-09-30 13:00:00"}
    ]
    with patch.object(bridge, "is_cent_account", return_value=False), \
         patch.object(bridge, "get_closed_deals", return_value=usd_deals), \
         patch("trading.mt5_bridge.datetime") as mock_dt, \
         patch("trading.mt5_bridge.mt5.symbol_info_tick", return_value=None), \
         patch("notify.telegram_bot.TelegramNotifier"):
        mock_now = MagicMock()
        mock_now.time.return_value = time(14, 0)
        mock_now.strftime.return_value = "2026-09-30"
        mock_dt.now.return_value = mock_now

        ok, msg, status = bridge.check_overnight_safety_guards("XAUUSD", score=80.0)
        assert ok is False
        assert status == "daily_loss_limit_reached"
        assert "DAILY CIRCUIT BREAKER AKTIF" in msg

    # 4. Akun USC di Jam Siang dengan riwayat 5x Consecutive Loss -> Tetap LOLOS (tidak diblokir)
    with patch.object(bridge, "is_cent_account", return_value=True), \
         patch("trading.mt5_bridge.datetime") as mock_dt, \
         patch("trading.mt5_bridge.mt5.symbol_info_tick", return_value=None), \
         patch("data.storage.StockStorage.get_consecutive_losses", return_value=(5, "2026-09-30 09:30")):
        mock_now = MagicMock()
        mock_now.time.return_value = time(10, 0)
        mock_now.strftime.return_value = "2026-09-30"
        mock_dt.now.return_value = mock_now

        ok, msg, status = bridge.check_overnight_safety_guards("XAUUSDc", score=60.0)
        assert ok is True
        assert status == "ok"

    # 5. Akun USD Standard dengan 3x Consecutive Loss tetapi Sinyal Grade A (score >= 65%) -> LOLOS (Grade A Override)
    with patch.object(bridge, "is_cent_account", return_value=False), \
         patch.object(bridge, "get_closed_deals", return_value=[]), \
         patch("trading.mt5_bridge.datetime") as mock_dt, \
         patch("trading.mt5_bridge.mt5.symbol_info_tick", return_value=None), \
         patch("data.storage.StockStorage.get_consecutive_losses", return_value=(3, "2026-09-30 11:30")):
        mock_now = MagicMock()
        mock_now.time.return_value = time(12, 0)
        mock_now.strftime.return_value = "2026-09-30"
        mock_dt.now.return_value = mock_now

        ok, msg, status = bridge.check_overnight_safety_guards("XAUUSD", score=75.0)
        assert ok is True
        assert status == "ok"


def test_anti_hedging_blocks_duplicate_and_cancels_broadcast():
    """
    Memastikan sinyal baru yang berlawanan arah dengan posisi aktif di MT5
    otomatis ditolak di _check_duplicate dan dibatalkan broadcast-nya di pipeline.
    """
    from scheduler.run_scheduler import PipelineRunner
    from trading.mt5_bridge import MT5Bridge

    bridge = MT5Bridge()
    bridge.enabled = True
    runner = PipelineRunner()
    
    # Sinyal BUY baru saat ada posisi SELL aktif di MT5
    buy_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=4160.0,
        candle_time="2026-10-01 08:52:00",
        take_profit_price=4190.0,
        stop_loss_price=4145.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
    )

    fake_positions = [
        {"ticket": 15246722135, "type": "SELL", "price_open": 4152.97, "symbol": "XAUUSDc"}
    ]

    with patch("trading.mt5_bridge.MT5Bridge.get_open_positions", return_value=fake_positions), \
         patch("trading.mt5_bridge.MT5Bridge.is_available", return_value=True):
        
        is_dup, dup_reason = runner._check_duplicate(buy_sig)
        assert is_dup is True
        assert "Anti-Hedging Guard" in dup_reason or "Posisi berlawanan" in dup_reason

        # Sinyal BUY baru dengan konfluensi 90%+ (Reversal Flip terkonfirmasi 9 Buku PDF)
        flip_sig = SignalResult(
            ticker="XAUUSD",
            strategy_name="Master_Confluence",
            signal="BUY",
            price=4160.0,
            candle_time="2026-10-01 08:52:00",
            take_profit_price=4190.0,
            stop_loss_price=4145.0,
            pdf_confluence_score=95.0,
            setup_grade="Grade A+",
        )
        is_dup_flip, dup_reason_flip = runner._check_duplicate(flip_sig)
        assert is_dup_flip is False


def test_reversal_flip_in_execute_signal():
    """Menguji bahwa sinyal pembalikan 90%+ menutup posisi lawan dan mengeksekusi order baru."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"
    bridge._simulated_positions = [
        {"ticket": 99999, "type": "SELL", "price_open": 2750.0, "symbol": "XAUUSDc", "volume": 0.05, "tp": 2720.0, "sl": 2770.0}
    ]

    flip_buy = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=2755.0,
        candle_time="2026-10-01 08:52:00",
        take_profit_price=2780.0,
        stop_loss_price=2740.0,
        pdf_confluence_score=95.0,
        setup_grade="Grade A+",
    )

    res = bridge.execute_signal(flip_buy)
    assert res["success"] is True
    assert res["action"] == "BUY"
    assert len(bridge._simulated_positions) == 1
    assert bridge._simulated_positions[0]["type"] == "BUY"


def test_usd_account_filter_and_lot_sizing():
    """
    Menguji aturan mutlak Akun Standard USD:
    - Sinyal standar/kurang bagus (Grade A / skor < 80% / 0.01 lot master) -> DITOLAK / DILEWATI di Akun USD.
    - Sinyal Grade A+ (0.05 lot bagus / skor >= 80%) -> DIEKSEKUSI di Akun USD dengan lot 0.01.
    """
    from unittest.mock import patch

    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"
    bridge.config["mt5"]["usd_only_high_grade"] = True
    bridge.config["mt5"]["usd_execution_lot"] = 0.01
    bridge._simulated_positions.clear()

    # Mock is_cent_account() agar selalu return False (Akun Standard USD)
    with patch.object(bridge, "is_cent_account", return_value=False):
        # 1. Sinyal Standar (Grade A, Skor 70%) -> Harus DITOLAK di USD
        standard_sig = SignalResult(
            ticker="XAUUSD",
            strategy_name="Master_Confluence",
            signal="BUY",
            price=2750.0,
            candle_time="2026-10-01 10:00:00",
            take_profit_price=2775.0,
            stop_loss_price=2735.0,
            pdf_confluence_score=70.0,
            setup_grade="Grade A",
        )
        res_std = bridge.execute_signal(standard_sig)
        assert res_std["success"] is False
        assert res_std["status"] == "usd_skip_standard_grade"
        assert "DILARANG" in res_std["message"] or "dilewati" in res_std["message"]

        # 2. Sinyal Grade A+ (Momen Bagus, Skor 85%) -> Harus DIEKSEKUSI dengan 0.01 Lot di USD
        high_sig = SignalResult(
            ticker="XAUUSD",
            strategy_name="Master_Confluence",
            signal="BUY",
            price=2750.0,
            candle_time="2026-10-01 10:15:00",
            take_profit_price=2775.0,
            stop_loss_price=2735.0,
            pdf_confluence_score=85.0,
            setup_grade="Grade A+",
        )
        res_high = bridge.execute_signal(high_sig)
        assert res_high["success"] is True
        assert res_high["volume"] == 0.01
        assert res_high["status"] == "executed"







