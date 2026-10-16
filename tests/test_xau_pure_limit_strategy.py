import pytest
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from strategy.signal_engine import SignalEngine, SignalResult
from trading.mt5_bridge import MT5Bridge, can_place_order


def test_pure_limit_strategy_buy_limit_conversion():
    """Memastikan bahwa saat always_use_limit_orders aktif, sinyal BUY dikonversi menjadi BUY_LIMIT."""
    engine = SignalEngine()
    engine.config["mt5"]["always_use_limit_orders"] = True
    engine.config["mt5"]["min_limit_distance_pips"] = 15.0

    idx = pd.date_range("2026-10-14 14:00", periods=15, freq="15min")
    opens = [4180.0 + i * 0.5 for i in range(15)]
    closes = [4181.5 + i * 0.5 for i in range(15)]
    highs = [c + 0.3 for c in closes]
    lows = [o - 0.5 for o in opens]
    volumes = [1000.0] * 14 + [1200.0]

    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
        "ema_20": [4180.0] * 15,
        "atr": [3.5] * 15,
    }, index=idx)

    curr_p = closes[-1]
    res = engine.evaluate_bar(df, ticker="XAUUSD", apply_pdf_filter=True)
    assert res.signal == "BUY_LIMIT"
    assert res.is_limit_order is True
    assert res.limit_order_type == "BUY_LIMIT"
    assert res.price <= curr_p - 1.50  # Harus di bawah harga pasar live (diskon)
    assert res.take_profit_price >= res.price + 6.00  # TP minimal 60 pips
    assert res.stop_loss_price <= res.price - 6.00    # SL minimal 60 pips
    assert any("PENDING ORDER SNIPER" in r for r in res.reasons)


def test_pure_limit_strategy_sell_limit_conversion():
    """Memastikan bahwa saat always_use_limit_orders aktif, sinyal SELL dikonversi menjadi SELL_LIMIT."""
    engine = SignalEngine()
    engine.config["mt5"]["always_use_limit_orders"] = True
    engine.config["mt5"]["min_limit_distance_pips"] = 15.0

    idx = pd.date_range("2026-10-14 14:00", periods=15, freq="15min")
    opens = [4185.0 - i * 0.5 for i in range(15)]
    closes = [4183.5 - i * 0.5 for i in range(15)]
    lows = [c - 0.3 for c in closes]
    highs = [o + 0.5 for o in opens]
    volumes = [1000.0] * 14 + [1200.0]

    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
        "ema_20": [4190.0] * 15,
        "rsi": [45.0] * 15,
        "atr": [3.5] * 15,
    }, index=idx)

    curr_p = closes[-1]
    res = engine.evaluate_bar(df, ticker="XAUUSD", apply_pdf_filter=True)
    assert res.signal == "SELL_LIMIT"
    assert res.is_limit_order is True
    assert res.limit_order_type == "SELL_LIMIT"
    assert res.price >= curr_p + 1.50  # Harus di atas harga pasar live (premium)
    assert res.take_profit_price <= res.price - 6.00  # TP minimal 60 pips
    assert res.stop_loss_price >= res.price + 6.00    # SL minimal 60 pips
    assert any("PENDING ORDER SNIPER" in r for r in res.reasons)


def test_can_place_order_allows_pending_limits_during_hold():
    """Memastikan can_place_order tidak memveto order_type BUY_LIMIT atau SELL_LIMIT saat sinyal pasar berstatus HOLD."""
    hold_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="3_Pilar_Inti_Zero_Bentrok_Plus_EMA_RSI_SNR",
        signal="HOLD",
        price=4180.0,
        candle_time="2026-10-14 15:00:00",
        take_profit_price=4186.0,
        stop_loss_price=4174.0,
        pdf_confluence_score=40.0,
        setup_grade="HOLD",
    )

    allowed_buy, msg_buy = can_place_order(
        sig=hold_sig,
        order_type="BUY_LIMIT",
        active_pending_orders=[],
        symbol="XAUUSD",
    )
    assert allowed_buy is True

    allowed_sell, msg_sell = can_place_order(
        sig=hold_sig,
        order_type="SELL_LIMIT",
        active_pending_orders=[],
        symbol="XAUUSD",
    )
    assert allowed_sell is True


def test_mt5_bridge_execute_signal_redirects_to_limit_order():
    """Memastikan bahwa pemanggilan mt5_bridge.execute_signal dengan sinyal BUY otomatis dialihkan ke execute_limit_order."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"
    bridge.config["mt5"]["always_use_limit_orders"] = True
    bridge._simulated_pending_orders.clear()

    instant_buy_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Momen_Grade_A_Plus_Direct",
        signal="BUY",
        price=4180.0,
        candle_time="2026-10-14 15:00:00",
        take_profit_price=4190.0,
        stop_loss_price=4170.0,
        pdf_confluence_score=95.0,
        setup_grade="Grade A+",
    )

    res = bridge.execute_signal(instant_buy_sig)
    assert res["success"] is True
    assert res["action"] == "BUY_LIMIT"
    assert res["price"] <= 4180.0 - 1.50
    assert len(bridge._simulated_pending_orders) == 1
    assert bridge._simulated_pending_orders[0]["type"] == "BUY_LIMIT"


def test_maintain_limits_does_nothing_on_hold():
    """Memastikan bahwa maintain_dual_sided_pending_limits TIDAK memasang limit order saat sinyal HOLD (tidak ada momen bagus)."""
    from unittest.mock import MagicMock
    from scheduler.run_scheduler import PipelineRunner

    storage_mock = MagicMock()
    scheduler = PipelineRunner(storage=storage_mock)
    scheduler.config["mt5"]["enable_limit_orders"] = True
    scheduler.config["mt5"]["enable_dual_sided_limits"] = False

    df = pd.DataFrame({
        "Open": [4180.0] * 10,
        "High": [4185.0] * 10,
        "Low": [4175.0] * 10,
        "Close": [4180.0] * 10,
        "Volume": [1000.0] * 10,
        "EMA_20": [4180.0] * 10,
        "EMA_50": [4180.0] * 10,
        "ATR": [3.0] * 10,
    })

    hold_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="3_Pilar_Inti_Zero_Bentrok_Plus_EMA_RSI_SNR",
        signal="HOLD",
        price=4180.0,
        candle_time="2026-10-14 15:00:00",
        pdf_confluence_score=40.0,
        setup_grade="HOLD",
    )

    from trading.mt5_bridge import MT5Bridge
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge._simulated_pending_orders.clear()

    scheduler.maintain_dual_sided_pending_limits(
        ticker="XAUUSD",
        sig_result=hold_sig,
        df_ind=df,
    )
    # Tidak boleh ada pending order yang terpasang saat HOLD
    assert len(bridge.get_pending_orders("XAUUSD")) == 0


def test_maintain_limits_only_one_side_on_good_moment():
    """Memastikan bahwa saat ada momen bagus SELL, hanya SELL_LIMIT yang dipasang (bukan dual-sided)."""
    from unittest.mock import MagicMock
    from scheduler.run_scheduler import PipelineRunner

    storage_mock = MagicMock()
    storage_mock.get_active_high_impact_news.return_value = []
    scheduler = PipelineRunner(storage=storage_mock)
    scheduler.config["mt5"]["enable_limit_orders"] = True
    scheduler.config["mt5"]["enable_dual_sided_limits"] = False
    scheduler.config["mt5"]["enable_news_limit_guard"] = False

    df = pd.DataFrame({
        "Open": [4185.0] * 10,
        "High": [4190.0] * 10,
        "Low": [4180.0] * 10,
        "Close": [4183.0] * 10,
        "Volume": [1500.0] * 10,
        "EMA_20": [4190.0] * 10,
        "EMA_50": [4195.0] * 10,
        "ATR": [3.0] * 10,
    })

    sell_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="3_Pilar_Inti_Zero_Bentrok_Plus_EMA_RSI_SNR",
        signal="SELL_LIMIT",
        price=4183.0,
        candle_time="2026-10-14 15:00:00",
        take_profit_price=4150.0,
        stop_loss_price=4200.0,
        pdf_confluence_score=100.0,
        setup_grade="Grade A+",
    )

    from trading.mt5_bridge import MT5Bridge
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge._simulated_pending_orders.clear()
    bridge._simulated_positions.clear()

    # Pre-populate dummy BUY_LIMIT yang berlawanan arah
    bridge._simulated_pending_orders.append({
        "ticket": 99991,
        "symbol": "XAUUSD",
        "type": "BUY_LIMIT",
        "price": 4080.0,
        "sl": 4060.0,
        "tp": 4100.0,
        "volume": 0.05,
        "time_setup": datetime.now(ZoneInfo("Asia/Jakarta")),
    })

    scheduler.maintain_dual_sided_pending_limits(
        ticker="XAUUSD",
        sig_result=sell_sig,
        df_ind=df,
    )

    orders = bridge.get_pending_orders("XAUUSD")
    # Hanya boleh ada SELL_LIMIT (BUY_LIMIT lama harus dibatalkan)
    types = [o["type"] for o in orders]
    assert "BUY_LIMIT" not in types
    assert "SELL_LIMIT" in types
    assert len(orders) == 1

