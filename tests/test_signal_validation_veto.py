import pytest
import pandas as pd
from unittest.mock import MagicMock
from strategy.signal_engine import SignalEngine, SignalResult, filter_and_validate_signal
from trading.mt5_bridge import MT5Bridge


def test_hard_rule_1_trend_lock_h4():
    """
    Hard Rule 1:
    - Jika tren H4 = BEARISH, nonaktifkan total BUY & BUY LIMIT (Anti-Pisau Jatuh).
    - Jika tren H4 = BULLISH, nonaktifkan total SELL & SELL LIMIT (Anti-Hadang Kereta).
    """
    # 1. H4 BEARISH mencoba BUY -> VETO
    sig_buy = SignalResult(
        ticker="XAUUSD",
        strategy_name="Test",
        signal="BUY",
        price=4100.0,
        stop_loss_price=4090.0,
        take_profit_price=4120.0,
        setup_grade="Grade A+",
        macro_bias_h4="BEARISH",
        pdf_confluence_score=85.0,
    )
    is_valid, msg = filter_and_validate_signal(sig_buy, h4_trend="BEARISH")
    assert is_valid is False
    assert "BEARISH" in msg or "Anti-Pisau Jatuh" in msg

    # 2. H4 BEARISH mencoba SELL -> DIIZINKAN
    sig_sell = SignalResult(
        ticker="XAUUSD",
        strategy_name="Test",
        signal="SELL",
        price=4100.0,
        stop_loss_price=4110.0,
        take_profit_price=4080.0,
        setup_grade="Grade A+",
        macro_bias_h4="BEARISH",
        pdf_confluence_score=85.0,
    )
    is_valid, msg = filter_and_validate_signal(sig_sell, h4_trend="BEARISH")
    assert is_valid is True

    # 3. H4 BULLISH mencoba SELL LIMIT -> VETO
    sig_sell_limit = SignalResult(
        ticker="XAUUSD",
        strategy_name="Test",
        signal="SELL_LIMIT",
        price=4120.0,
        stop_loss_price=4130.0,
        take_profit_price=4100.0,
        setup_grade="Grade A+",
        macro_bias_h4="BULLISH",
        pdf_confluence_score=85.0,
    )
    is_valid, msg = filter_and_validate_signal(sig_sell_limit, h4_trend="BULLISH")
    assert is_valid is False
    assert "BULLISH" in msg or "Anti-Hadang Kereta" in msg

    # 4. H4 BULLISH mencoba BUY LIMIT -> DIIZINKAN
    sig_buy_limit = SignalResult(
        ticker="XAUUSD",
        strategy_name="Test",
        signal="BUY_LIMIT",
        price=4090.0,
        stop_loss_price=4080.0,
        take_profit_price=4110.0,
        setup_grade="Grade A+",
        macro_bias_h4="BULLISH",
        pdf_confluence_score=85.0,
    )
    is_valid, msg = filter_and_validate_signal(sig_buy_limit, h4_trend="BULLISH")
    assert is_valid is True


def test_hard_rule_2_veto_weak_signals_and_no_rejection():
    """
    Hard Rule 2:
    - Sinyal Grade B atau Grade C WAJIB diveto total (return False).
    - Status 'Ketiadaan Rejection Wick' WAJIB diveto total.
    - Notifikasi dikirimkan ke Telegram.
    """
    mock_notifier = MagicMock()

    # 1. Grade C -> Veto
    sig_c = SignalResult(
        ticker="XAUUSD",
        strategy_name="Test",
        signal="SELL",
        price=4110.0,
        stop_loss_price=4120.0,
        take_profit_price=4090.0,
        setup_grade="Grade C",
        pdf_confluence_score=75.0,
    )
    is_valid, msg = filter_and_validate_signal(sig_c, notifier=mock_notifier)
    assert is_valid is False
    assert "Grade Rendah" in msg
    mock_notifier.send_message.assert_called_once()
    assert "⚠️ <b>Trade Dibatalkan (Veto):</b>" in mock_notifier.send_message.call_args[0][0]

    mock_notifier.reset_mock()

    # 2. Grade B -> Veto
    sig_b = SignalResult(
        ticker="XAUUSD",
        strategy_name="Test",
        signal="BUY",
        price=4110.0,
        stop_loss_price=4100.0,
        take_profit_price=4130.0,
        setup_grade="Grade B",
        pdf_confluence_score=78.0,
    )
    is_valid, msg = filter_and_validate_signal(sig_b, notifier=mock_notifier)
    assert is_valid is False
    assert "Grade Rendah" in msg
    mock_notifier.send_message.assert_called_once()

    mock_notifier.reset_mock()

    # 3. Ketiadaan Rejection Wick dalam reasons -> Veto
    sig_no_wick = SignalResult(
        ticker="XAUUSD",
        strategy_name="Test",
        signal="SELL",
        price=4110.0,
        stop_loss_price=4120.0,
        take_profit_price=4090.0,
        setup_grade="Grade A+",
        pdf_confluence_score=85.0,
        reasons=["Deteksi Momentum Kuat", "Ketiadaan Rejection Wick pada level resistance"],
    )
    is_valid, msg = filter_and_validate_signal(sig_no_wick, notifier=mock_notifier)
    assert is_valid is False
    assert "Ketiadaan Rejection Wick" in msg
    mock_notifier.send_message.assert_called_once()


def test_hard_rule_3_dynamic_sl_and_rr_ratio():
    """
    Hard Rule 3:
    - Rasio Risk-to-Reward (RR) minimal 1:1.5 mutlak.
    - Stop Loss statis sempit ($6) dengan RR 1:1 wajib diveto atau disesuaikan.
    """
    # RR 1:1 (SL $10, TP $10 -> R:R 1.0) -> VETO karena < 1.5
    sig_bad_rr = SignalResult(
        ticker="XAUUSD",
        strategy_name="Test",
        signal="SELL",
        price=4110.0,
        stop_loss_price=4120.0,  # SL $10
        take_profit_price=4100.0,  # TP $10
        setup_grade="Grade A+",
        pdf_confluence_score=90.0,
    )
    is_valid, msg = filter_and_validate_signal(sig_bad_rr)
    assert is_valid is False
    assert "Rasio Risk-to-Reward tidak memadai" in msg

    # RR 1:1.5 (SL $10, TP $15 -> R:R 1.5) -> VALID
    sig_good_rr = SignalResult(
        ticker="XAUUSD",
        strategy_name="Test",
        signal="SELL",
        price=4110.0,
        stop_loss_price=4120.0,  # SL $10
        take_profit_price=4095.0,  # TP $15 (1.5x SL)
        setup_grade="Grade A+",
        pdf_confluence_score=90.0,
    )
    is_valid, msg = filter_and_validate_signal(sig_good_rr)
    assert is_valid is True


def test_mt5_bridge_rejects_vetoed_signal():
    """
    Memastikan MT5Bridge membatalkan eksekusi order MT5 (return success=False, status='veto_rejected')
    jika sinyal melanggar salah satu Hard Rule.
    """
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"

    # Sinyal Grade B dengan skor 85% lolos skor PDF tapi WAJIB kena veto Hard Rule!
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Test",
        signal="SELL",
        price=4110.0,
        stop_loss_price=4125.0,
        take_profit_price=4085.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade B",
    )
    res = bridge.execute_signal(sig)
    assert res["success"] is False
    assert res["status"] == "veto_rejected"
    assert "Grade Rendah" in res["message"]


def test_generate_limit_orders_h4_one_direction():
    """
    Memastikan SignalEngine.generate_dual_sided_limit_orders hanya menghasilkan
    satu arah sesuai tren H4 (tidak ada bracket dua arah yang berlawanan tren).
    """
    engine = SignalEngine()
    df_dummy = pd.DataFrame({
        "Open": [4100.0] * 35,
        "High": [4115.0] * 35,
        "Low": [4090.0] * 35,
        "Close": [4105.0] * 35,
        "Volume": [1000] * 35,
    })
    snapshot = {"ema_20": 4110.0, "ema_50": 4120.0, "atr": 4.0}

    # Dummy H4 BEARISH (Close < EMA50)
    df_h4_bear = pd.DataFrame({
        "Open": [4150.0] * 30,
        "High": [4160.0] * 30,
        "Low": [4080.0] * 30,
        "Close": [4090.0] * 30,
        "EMA_20": [4110.0] * 30,
        "EMA_50": [4130.0] * 30,
        "Volume": [1000] * 30,
    })

    orders = engine.generate_dual_sided_limit_orders(
        df=df_dummy,
        ticker="XAUUSD",
        curr_price=4100.0,
        snapshot=snapshot,
        df_h4=df_h4_bear,
        is_cent=False,
    )
    # Wajib HANYA SELL LIMIT, nol BUY LIMIT
    assert len(orders) > 0
    assert all("SELL" in o["type"] for o in orders)
    assert not any("BUY" in o["type"] for o in orders)
    # Periksa SL di atas harga limit dan RR >= 1.5
    for o in orders:
        assert o["sl"] > o["price"]
        sl_dist = o["sl"] - o["price"]
        tp_dist = o["price"] - o["tp"]
        assert round(tp_dist / sl_dist, 2) >= 1.45
