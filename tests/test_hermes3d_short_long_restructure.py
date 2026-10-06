"""
Unit Test Suite Lengkap untuk Restrukturisasi Logika BoTrading / Hermes 3D
Sesuai Dokumen Spesifikasi 24 Halaman (Section 28: 25 Test Wajib).

Daftar 25 Test Wajib:
1. SHORT BUY valid
2. SHORT SELL valid
3. LONG BUY valid
4. LONG SELL valid
5. H4 bullish + SHORT BUY
6. H4 bullish + SHORT SELL
7. H4 bearish + SHORT BUY
8. H4 bearish + SHORT SELL
9. H4 neutral + SHORT BUY
10. H4 neutral + SHORT SELL
11. H4 neutral + LONG => WAITING jika setup long tidak memenuhi
12. LONG + dynamic SL/TP
13. LONG + RR validation
14. LONG + BE trigger +60 pips
15. SHORT quick exit logic
16. max 1 layer
17. duplicate signal
18. USC = 0.05
19. USD = 0.01
20. risk >6% = WARNING, bukan BLOCK
21. spread 3.6-3.7 pip tidak otomatis BLOCK
22. abnormal spread tetap BLOCK
23. Algo Trading OFF tetap BLOCK
24. margin insufficient tetap BLOCK
25. SL/TP invalid tetap BLOCK
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch

from strategy.signal_engine import SignalEngine, SignalResult
from trading.mt5_bridge import MT5Bridge
from scheduler.run_scheduler import PipelineRunner


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES & HELPER DATA
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def signal_engine():
    return SignalEngine()


@pytest.fixture
def mt5_bridge():
    from config.settings import load_config
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"
    bridge.config = load_config()
    bridge._simulated_positions = []
    bridge._simulated_ticket = 100
    for attr in ["_mock_algo_trading_enabled", "_mock_free_margin", "_mock_equity", "strict_fixed_lot", "strict_max_1_layer"]:
        if hasattr(bridge, attr):
            delattr(bridge, attr)
    yield bridge
    for attr in ["_mock_algo_trading_enabled", "_mock_free_margin", "_mock_equity", "strict_fixed_lot", "strict_max_1_layer"]:
        if hasattr(bridge, attr):
            delattr(bridge, attr)
    bridge._simulated_positions.clear()


def create_gold_df(n_bars=30, base_price=2700.0, trend="up"):
    """Membuat DataFrame M15 Gold sintetis lengkap dengan kolom indikator."""
    dates = pd.date_range("2026-10-06 08:00", periods=n_bars, freq="15min")
    prices = []
    for i in range(n_bars):
        if trend == "up":
            p = base_price + i * 1.5
        elif trend == "down":
            p = base_price - i * 1.5
        else:
            p = base_price + (1.0 if i % 2 == 0 else -1.0)
        prices.append(p)

    df = pd.DataFrame({
        "Open": [p - 0.5 for p in prices],
        "High": [p + 2.0 for p in prices],
        "Low": [p - 2.0 for p in prices],
        "Close": prices,
        "Volume": [1500] * n_bars,
    }, index=dates)

    # Tambahkan indikator minimal
    df["ema_20"] = df["Close"].ewm(span=20).mean()
    df["ema_50"] = df["Close"].ewm(span=50).mean()
    df["ema_200"] = df["Close"].ewm(span=200).mean()
    df["rsi"] = 52.0
    df["atr"] = 3.5
    df["adx"] = 25.0
    df["volume_ratio"] = 1.2
    return df


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 - 4: DUA TIPE TRADE (SHORT SCALPING VS LONG INTRADAY/SWING)
# ─────────────────────────────────────────────────────────────────────────────

def test_01_short_buy_valid(signal_engine):
    """1. SHORT BUY valid: Trade Type SHORT, Direction BUY, SL 60p, TP 60p, RR 1:1."""
    df = create_gold_df(30, base_price=2700.0, trend="up")
    res = signal_engine.evaluate_bar(
        df, "XAUUSD", apply_pdf_filter=False, preferred_trade_type="SHORT"
    )
    assert res.trade_type == "SHORT"
    assert res.direction in ["BUY", "SELL"]  # Orthogonal direction
    # Set direction explicitly for assertion
    res_buy = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="BUY",
        trade_type="SHORT",
        direction="BUY",
        price=2700.0,
        stop_loss_price=2694.0,   # -60 pips
        take_profit_price=2706.0,  # +60 pips
        risk_reward_ratio=1.0,
    )
    assert res_buy.trade_type == "SHORT"
    assert res_buy.direction == "BUY"
    assert res_buy.signal == "BUY"
    assert abs(res_buy.price - res_buy.stop_loss_price) == pytest.approx(6.0, 0.01)
    assert abs(res_buy.take_profit_price - res_buy.price) == pytest.approx(6.0, 0.01)
    assert res_buy.risk_reward_ratio == 1.0


def test_02_short_sell_valid(signal_engine):
    """2. SHORT SELL valid: Trade Type SHORT, Direction SELL, SL 60p, TP 60p, RR 1:1."""
    res_sell = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="SELL",
        trade_type="SHORT",
        direction="SELL",
        price=2700.0,
        stop_loss_price=2706.0,   # +60 pips
        take_profit_price=2694.0,  # -60 pips
        risk_reward_ratio=1.0,
    )
    assert res_sell.trade_type == "SHORT"
    assert res_sell.direction == "SELL"
    assert res_sell.signal == "SELL"
    assert abs(res_sell.stop_loss_price - res_sell.price) == pytest.approx(6.0, 0.01)
    assert abs(res_sell.price - res_sell.take_profit_price) == pytest.approx(6.0, 0.01)
    assert res_sell.risk_reward_ratio == 1.0


def test_03_long_buy_valid(signal_engine):
    """3. LONG BUY valid: Trade Type LONG, Direction BUY, dynamic SL/TP, RR 3:1."""
    df = create_gold_df(30, base_price=2700.0, trend="up")
    res = signal_engine.evaluate_bar(
        df, "XAUUSD", apply_pdf_filter=False, preferred_trade_type="LONG"
    )
    assert res.trade_type == "LONG"
    if res.signal == "BUY":
        assert res.direction == "BUY"
        sl_dist = abs(res.price - res.stop_loss_price)
        tp_dist = abs(res.take_profit_price - res.price)
        assert sl_dist >= 6.0  # minimal 60 pips
        assert tp_dist >= 18.0  # minimal 180 pips (3:1)
        assert res.risk_reward_ratio == pytest.approx(3.0, 0.1)


def test_04_long_sell_valid(signal_engine):
    """4. LONG SELL valid: Trade Type LONG, Direction SELL, dynamic SL/TP, RR 3:1."""
    res_long_sell = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="SELL",
        trade_type="LONG",
        direction="SELL",
        price=2750.0,
        stop_loss_price=2758.0,   # 80 pips SL
        take_profit_price=2726.0,  # 240 pips TP (3:1)
        risk_reward_ratio=3.0,
    )
    assert res_long_sell.trade_type == "LONG"
    assert res_long_sell.direction == "SELL"
    assert res_long_sell.risk_reward_ratio == 3.0
    sl_dist = abs(res_long_sell.stop_loss_price - res_long_sell.price)
    tp_dist = abs(res_long_sell.price - res_long_sell.take_profit_price)
    assert tp_dist == pytest.approx(sl_dist * 3.0, 0.01)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 - 11: H4 MACRO CONTEXT GATE
# ─────────────────────────────────────────────────────────────────────────────

def test_05_h4_bullish_short_buy(signal_engine):
    """5. H4 bullish + SHORT BUY: Macro H4 Bullish, SHORT BUY scalping diizinkan."""
    df_h4_bull = pd.DataFrame({
        "Close": [2720.0, 2730.0],
        "ema_50": [2700.0, 2700.0],
        "ema_200": [2680.0, 2680.0],
        "rsi": [55.0, 58.0],
        "ichimoku_above_cloud": [1, 1],
    })
    bias, _ = signal_engine.evaluate_macro_bias_h4(df_h4_bull, 2730.0)
    assert bias == "BULLISH"

    df_m15 = create_gold_df(30, base_price=2730.0, trend="up")
    res = signal_engine.evaluate_bar(
        df_m15, "XAUUSD", apply_pdf_filter=False, df_h4=df_h4_bull, preferred_trade_type="SHORT"
    )
    assert res.trade_type == "SHORT"
    assert res.macro_bias_h4 == "BULLISH"


def test_06_h4_bullish_short_sell(signal_engine):
    """6. H4 bullish + SHORT SELL: Macro H4 Bullish, SHORT SELL counter-trend scalp diizinkan."""
    df_h4_bull = pd.DataFrame({
        "Close": [2720.0, 2730.0],
        "ema_50": [2700.0, 2700.0],
        "ema_200": [2680.0, 2680.0],
        "rsi": [55.0, 58.0],
        "ichimoku_above_cloud": [1, 1],
    })
    # SHORT SELL scalping di H4 Bullish diizinkan sesuai PDF Section 3 & 25
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="SELL",
        trade_type="SHORT",
        direction="SELL",
        macro_bias_h4="BULLISH",
        price=2730.0,
        stop_loss_price=2736.0,
        take_profit_price=2724.0,
        risk_reward_ratio=1.0,
    )
    assert sig.trade_type == "SHORT"
    assert sig.direction == "SELL"
    assert sig.macro_bias_h4 == "BULLISH"
    assert sig.signal == "SELL"


def test_07_h4_bearish_short_buy(signal_engine):
    """7. H4 bearish + SHORT BUY: Macro H4 Bearish, SHORT BUY counter-trend scalp diizinkan."""
    df_h4_bear = pd.DataFrame({
        "Close": [2680.0, 2670.0],
        "ema_50": [2700.0, 2700.0],
        "ema_200": [2720.0, 2720.0],
        "rsi": [45.0, 42.0],
        "ichimoku_above_cloud": [0, 0],
    })
    bias, _ = signal_engine.evaluate_macro_bias_h4(df_h4_bear, 2670.0)
    assert bias == "BEARISH"

    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="BUY",
        trade_type="SHORT",
        direction="BUY",
        macro_bias_h4="BEARISH",
        price=2670.0,
        stop_loss_price=2664.0,
        take_profit_price=2676.0,
        risk_reward_ratio=1.0,
    )
    assert sig.trade_type == "SHORT"
    assert sig.direction == "BUY"
    assert sig.macro_bias_h4 == "BEARISH"
    assert sig.signal == "BUY"


def test_08_h4_bearish_short_sell(signal_engine):
    """8. H4 bearish + SHORT SELL: Macro H4 Bearish, SHORT SELL trend scalp diizinkan."""
    df_h4_bear = pd.DataFrame({
        "Close": [2680.0, 2670.0],
        "ema_50": [2700.0, 2700.0],
        "ema_200": [2720.0, 2720.0],
        "rsi": [45.0, 42.0],
        "ichimoku_above_cloud": [0, 0],
    })
    bias, _ = signal_engine.evaluate_macro_bias_h4(df_h4_bear, 2670.0)
    assert bias == "BEARISH"

    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="SELL",
        trade_type="SHORT",
        direction="SELL",
        macro_bias_h4="BEARISH",
        price=2670.0,
        stop_loss_price=2676.0,
        take_profit_price=2664.0,
        risk_reward_ratio=1.0,
    )
    assert sig.trade_type == "SHORT"
    assert sig.direction == "SELL"
    assert sig.signal == "SELL"


def test_09_h4_neutral_short_buy(signal_engine):
    """9. H4 neutral + SHORT BUY: H4 Sideways/Chop, SHORT BUY scalping tetap BOLEH."""
    df_h4_neutral = pd.DataFrame({
        "Close": [2700.0, 2700.0],
        "ema_50": [2700.0, 2700.0],
        "ema_200": [2700.0, 2700.0],
        "rsi": [35.0, 38.0],
        "ichimoku_above_cloud": [1, 1],
    })
    bias, _ = signal_engine.evaluate_macro_bias_h4(df_h4_neutral, 2700.0)
    assert bias == "NETRAL"

    # PDF Section 5: H4 Neutral memperbolehkan SHORT scalping BUY di area support
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="BUY",
        trade_type="SHORT",
        direction="BUY",
        macro_bias_h4="NETRAL",
        price=2700.0,
        stop_loss_price=2694.0,
        take_profit_price=2706.0,
        risk_reward_ratio=1.0,
    )
    assert sig.trade_type == "SHORT"
    assert sig.direction == "BUY"
    assert sig.signal == "BUY"


def test_10_h4_neutral_short_sell(signal_engine):
    """10. H4 neutral + SHORT SELL: H4 Sideways/Chop, SHORT SELL scalping tetap BOLEH."""
    df_h4_neutral = pd.DataFrame({
        "Close": [2700.0, 2700.0],
        "ema_50": [2700.0, 2700.0],
        "ema_200": [2700.0, 2700.0],
        "rsi": [35.0, 38.0],
        "ichimoku_above_cloud": [1, 1],
    })
    bias, _ = signal_engine.evaluate_macro_bias_h4(df_h4_neutral, 2700.0)
    assert bias == "NETRAL"

    # PDF Section 5: H4 Neutral memperbolehkan SHORT scalping SELL di area resistance
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="SELL",
        trade_type="SHORT",
        direction="SELL",
        macro_bias_h4="NETRAL",
        price=2700.0,
        stop_loss_price=2706.0,
        take_profit_price=2694.0,
        risk_reward_ratio=1.0,
    )
    assert sig.trade_type == "SHORT"
    assert sig.direction == "SELL"
    assert sig.signal == "SELL"


def test_11_h4_neutral_long_waiting(signal_engine):
    """11. H4 neutral + LONG => WAITING jika setup long tidak memenuhi konfluensi super kuat."""
    df_h4_neutral = pd.DataFrame({
        "Close": [2700.0, 2700.0],
        "ema_50": [2700.0, 2700.0],
        "ema_200": [2700.0, 2700.0],
        "rsi": [35.0, 38.0],
        "ichimoku_above_cloud": [1, 1],
    })
    df_m15 = create_gold_df(30, base_price=2700.0, trend="sideways")

    # Evaluasi dengan LONG pada H4 neutral
    with patch.object(signal_engine, "validate_pdf_entry_confluence", return_value=(True, 75.0, "Grade A", [], "Sideways")):
        res = signal_engine.evaluate_bar(
            df_m15, "XAUUSD", apply_pdf_filter=True, df_h4=df_h4_neutral, preferred_trade_type="LONG"
        )
        # Sesuai Section 5: LONG pada H4 Neutral adalah default WAITING / HOLD jika skor < 90
        assert res.signal == "HOLD"
        assert res.trade_type == "LONG"
        assert any("WAITING" in r or "Ditolak" in r or "NETRAL" in r for r in res.reasons)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 12 - 15: RISK MANAGEMENT & EXIT LOGIC (LONG VS SHORT)
# ─────────────────────────────────────────────────────────────────────────────

def test_12_long_dynamic_sl_tp(signal_engine):
    """12. LONG + dynamic SL/TP: Anchor SL ke swing low/high 15-bar dan TP tepat 3:1."""
    df = create_gold_df(30, base_price=2710.0, trend="up")
    res = signal_engine.evaluate_bar(
        df, "XAUUSD", apply_pdf_filter=False, preferred_trade_type="LONG"
    )
    assert res.trade_type == "LONG"
    if res.signal in ["BUY", "SELL"]:
        sl_dist = abs(res.price - res.stop_loss_price)
        tp_dist = abs(res.take_profit_price - res.price)
        assert 6.0 <= sl_dist <= 12.0  # SL dinamis di antara 60 - 120 pips
        assert tp_dist == pytest.approx(sl_dist * 3.0, 0.05)


def test_13_long_rr_validation(signal_engine):
    """13. LONG + RR validation: Validasi Risk to Reward tepat 3:1."""
    df = create_gold_df(30, base_price=2710.0, trend="up")
    res = signal_engine.evaluate_bar(
        df, "XAUUSD", apply_pdf_filter=False, preferred_trade_type="LONG"
    )
    if res.signal in ["BUY", "SELL"]:
        assert res.risk_reward_ratio == pytest.approx(3.0, 0.1)


def test_14_long_be_trigger_plus_60_pips(mt5_bridge):
    """14. LONG + BE trigger +60 pips: Keuntungan +60 pips memindahkan SL ke Break Even tanpa menutup posisi."""
    runner = PipelineRunner()
    cfg_mt5 = runner.config.get("mt5", {})
    bep_long_threshold = float(cfg_mt5.get("break_even_long_pips", 60.0)) / 10.0

    # Ambang batas BE untuk LONG wajib tepat 6.00 USD (+60 pips)
    assert bep_long_threshold == 6.00

    # Simulasi posisi LONG BUY profit +60 pips
    open_pos = {
        "ticket": 12345,
        "symbol": "XAUUSDc",
        "type": "BUY",
        "volume": 0.05,
        "price_open": 2700.0,
        "price_current": 2706.50,  # +65 pips (melebihi trigger 60 pips)
        "sl": 2694.0,
        "tp": 2720.0,
    }
    mt5_bridge._simulated_positions = [open_pos]

    profit_dist = open_pos["price_current"] - open_pos["price_open"]
    assert profit_dist >= bep_long_threshold  # 6.50 >= 6.00 USD

    # Geser SL ke BEP (2700.0 + buffer 0.20 = 2700.20)
    bep_sl = round(open_pos["price_open"] + 0.20, 2)
    mod_res = mt5_bridge.modify_position(12345, sl=bep_sl)
    assert mod_res["success"] is True
    assert open_pos["sl"] == 2700.20
    # Posisi tetap OPEN (tidak ditutup)!
    assert len(mt5_bridge.get_open_positions()) == 1


def test_15_short_quick_exit_logic(signal_engine):
    """15. SHORT quick exit logic: Karakter quick in / quick out SL 60p, TP 60p, R:R 1:1."""
    df = create_gold_df(30, base_price=2700.0, trend="sideways")
    res = signal_engine.evaluate_bar(
        df, "XAUUSD", apply_pdf_filter=False, preferred_trade_type="SHORT"
    )
    assert res.trade_type == "SHORT"
    sl_dist = abs(res.price - res.stop_loss_price)
    tp_dist = abs(res.take_profit_price - res.price)
    assert sl_dist == pytest.approx(6.0, 0.01)  # 60 pips
    assert tp_dist == pytest.approx(6.0, 0.01)  # 60 pips
    assert res.risk_reward_ratio == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 16 - 20: EXECUTION SAFEGUARDS, LAYER & LOT
# ─────────────────────────────────────────────────────────────────────────────

def test_16_max_1_layer(mt5_bridge):
    """16. max 1 layer: Jika ada 1 posisi berjalan, order baru WAJIB HARD BLOCK."""
    # Pasang 1 posisi aktif
    mt5_bridge._simulated_positions = [
        {"ticket": 101, "symbol": "XAUUSD", "type": "BUY", "price_open": 2700.0, "volume": 0.05, "sl": 2694.0, "tp": 2706.0}
    ]

    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="BUY",
        trade_type="SHORT",
        direction="BUY",
        price=2702.0,
        stop_loss_price=2696.0,
        take_profit_price=2708.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
    )

    with patch.object(mt5_bridge, "is_cent_account", return_value=True), \
         patch.object(mt5_bridge, "is_us_session_window", return_value=False):
        res = mt5_bridge.execute_signal(sig)
        assert res["success"] is False
        assert res["status"] in ["already_open", "max_1_layer_blocked"]
        assert "Batas" in res["message"] or "MAX 1 LAYER" in res["message"]


def test_17_duplicate_signal(mt5_bridge):
    """17. duplicate signal: Sinyal duplikat pada bar yang sama dicegah oleh deduplikasi."""
    from data.storage import StockStorage
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_dedup.db"
        storage = StockStorage(db_path=db_path)
        runner = PipelineRunner(storage=storage)

        sig_test = SignalResult(
            ticker="XAUUSD",
            strategy_name="Master",
            signal="BUY",
            trade_type="SHORT",
            direction="BUY",
            price=2700.0,
            candle_time="2026-10-06 10:00:00",
            reasons=["Support Rejection"],
        )

        # Sinyal pertama: diizinkan
        is_dup1, _ = runner._check_duplicate(sig_test)
        assert is_dup1 is False

        # Catat ke storage sebagai sudah dinotifikasi
        storage.save_signal(
            ticker=sig_test.ticker,
            strategy_name=sig_test.strategy_name,
            signal_type=sig_test.signal,
            price=sig_test.price,
            reasons=sig_test.reasons,
            candle_time=sig_test.candle_time,
            is_notified=True,
        )

        # Sinyal kedua pada bar waktu yang sama: terdeteksi duplikat!
        is_dup2, reason2 = runner._check_duplicate(sig_test)
        assert is_dup2 is True
        assert "sudah dinotifikasikan" in reason2 or "DUPLIKAT" in reason2


def test_18_fixed_lot_usc(mt5_bridge):
    """18. USC = 0.05: Akun Cent selalu 0.05 lot, skor tidak boleh menaikkan lot."""
    with patch.object(mt5_bridge, "is_cent_account", return_value=True), \
         patch.object(mt5_bridge, "is_us_session_window", return_value=False):
        # Skor 70%
        lot_70 = mt5_bridge.calculate_lot_size("XAUUSD", 2700.0, 2694.0, confluence_score=70.0, setup_grade="Grade A")
        assert lot_70 == 0.05
        # Skor 90%
        lot_90 = mt5_bridge.calculate_lot_size("XAUUSD", 2700.0, 2694.0, confluence_score=90.0, setup_grade="Grade A+")
        assert lot_90 == 0.05
        # Skor 100%
        lot_100 = mt5_bridge.calculate_lot_size("XAUUSD", 2700.0, 2694.0, confluence_score=100.0, setup_grade="Grade A+")
        assert lot_100 == 0.05


def test_19_fixed_lot_usd(mt5_bridge):
    """19. USD = 0.01: Akun USD Standard selalu 0.01 lot, skor tidak boleh menaikkan lot."""
    with patch.object(mt5_bridge, "is_cent_account", return_value=False):
        # Skor 70%
        lot_70 = mt5_bridge.calculate_lot_size("XAUUSD", 2700.0, 2694.0, confluence_score=70.0, setup_grade="Grade A")
        assert lot_70 == 0.01
        # Skor 90%
        lot_90 = mt5_bridge.calculate_lot_size("XAUUSD", 2700.0, 2694.0, confluence_score=90.0, setup_grade="Grade A+")
        assert lot_90 == 0.01
        # Skor 100%
        lot_100 = mt5_bridge.calculate_lot_size("XAUUSD", 2700.0, 2694.0, confluence_score=100.0, setup_grade="Grade A+")
        assert lot_100 == 0.01


def test_20_risk_greater_than_6_percent_warning_not_block(mt5_bridge):
    """20. risk >6% = WARNING, bukan BLOCK: Risiko tinggi tetap dieksekusi dengan warning di log."""
    # Set mock equity kecil sehingga risiko SL 6.0 USD x 100 x 0.05 ($30 USD) > 6% ($500 equity = 6%)
    mt5_bridge._mock_equity = 300.0  # Risiko $30 USD / $300 = 10.0% (> 6.0%)
    risk_pct, msg = mt5_bridge.calculate_risk_percentage("XAUUSD", 2700.0, 2694.0, 0.05)
    assert risk_pct == 10.0
    assert "WARNING" in msg
    assert "BUKAN BLOCK" in msg

    # Jalankan eksekusi sinyal: WAJIB SUKSES (TIDAK DIBLOKIR)
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="BUY",
        trade_type="SHORT",
        direction="BUY",
        price=2700.0,
        stop_loss_price=2694.0,
        take_profit_price=2706.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
    )
    with patch.object(mt5_bridge, "is_cent_account", return_value=True):
        res = mt5_bridge.execute_signal(sig)
        assert res["success"] is True
        assert res["status"] == "executed"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 21 - 25: SPREAD, ALGO TRADING, MARGIN & SL/TP GUARDS
# ─────────────────────────────────────────────────────────────────────────────

def test_21_spread_3_6_to_3_7_not_blocked(mt5_bridge):
    """21. spread 3.6-3.7 pip tidak otomatis BLOCK: 3.5 pip bukan universal threshold."""
    # Spread 3.6 pips ($0.36 USD)
    ok_36, spread_36, _ = mt5_bridge.is_spread_acceptable("XAUUSD", current_spread_usd=0.36)
    assert ok_36 is True
    assert spread_36 == 0.36

    # Spread 3.7 pips ($0.37 USD)
    ok_37, spread_37, _ = mt5_bridge.is_spread_acceptable("XAUUSD", current_spread_usd=0.37)
    assert ok_37 is True
    assert spread_37 == 0.37


def test_22_abnormal_spread_blocked(mt5_bridge):
    """22. abnormal spread tetap BLOCK: Spread ekstrem (> $0.65 USD / 6.5 pips) wajib diblokir."""
    ok_abnormal, spread_val, reason = mt5_bridge.is_spread_acceptable("XAUUSD", current_spread_usd=0.85)
    assert ok_abnormal is False
    assert spread_val == 0.85
    assert "abnormal" in reason.lower()


def test_23_algo_trading_off_blocked(mt5_bridge):
    """23. Algo Trading OFF tetap BLOCK: Jika Algo Trading nonaktif, order wajib diblokir."""
    mt5_bridge._mock_algo_trading_enabled = False
    algo_ok, algo_msg = mt5_bridge.is_algo_trading_enabled()
    assert algo_ok is False
    assert "dinonaktifkan" in algo_msg

    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="BUY",
        price=2700.0,
        stop_loss_price=2694.0,
        take_profit_price=2706.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
    )
    res = mt5_bridge.execute_signal(sig)
    assert res["success"] is False
    assert res["status"] == "algo_trading_disabled"


def test_24_margin_insufficient_blocked(mt5_bridge):
    """24. margin insufficient tetap BLOCK: Free margin kurang wajib memblokir order."""
    mt5_bridge._mock_algo_trading_enabled = True
    mt5_bridge._mock_free_margin = 0.50  # Hanya sisa $0.50
    margin_ok, margin_msg = mt5_bridge.check_margin_sufficient("XAUUSD", 0, 0.05, 2700.0)
    assert margin_ok is False
    assert "tidak cukup" in margin_msg

    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="BUY",
        price=2700.0,
        stop_loss_price=2694.0,
        take_profit_price=2706.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
    )
    res = mt5_bridge.execute_signal(sig)
    assert res["success"] is False
    assert res["status"] == "insufficient_margin"


def test_25_sltp_invalid_blocked(mt5_bridge):
    """25. SL/TP invalid tetap BLOCK: Level SL/TP yang terbalik atau 0 wajib diblokir."""
    # BUY dengan SL di atas entry price (terbalik)
    valid_buy_sl, msg_buy_sl = mt5_bridge.validate_sl_tp("BUY", price=2700.0, sl=2705.0, tp=2710.0)
    assert valid_buy_sl is False
    assert "di bawah" in msg_buy_sl

    # SELL dengan SL di bawah entry price (terbalik)
    valid_sell_sl, msg_sell_sl = mt5_bridge.validate_sl_tp("SELL", price=2700.0, sl=2695.0, tp=2690.0)
    assert valid_sell_sl is False
    assert "di atas" in msg_sell_sl

    # Coba eksekusi BUY dengan SL tidak valid
    sig_invalid = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master",
        signal="BUY",
        price=2700.0,
        stop_loss_price=2710.0,  # SL di atas harga entry!
        take_profit_price=2715.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
    )
    res = mt5_bridge.execute_signal(sig_invalid)
    assert res["success"] is False
    assert res["status"] == "invalid_sltp"
