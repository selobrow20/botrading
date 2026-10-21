import pytest
import pandas as pd
from strategy.signal_engine import SignalEngine


def test_extract_active_ob_and_fvg():
    """Menguji deteksi unmitigated Order Block dan Fair Value Gap."""
    dates = pd.date_range("2026-10-20 08:00", periods=25, freq="15min")
    df = pd.DataFrame({
        "Open": [2750.0 + i for i in range(25)],
        "High": [2752.0 + i for i in range(25)],
        "Low": [2749.0 + i for i in range(25)],
        "Close": [2751.0 + i for i in range(25)],
        "order_block_bullish": [0.0] * 25,
        "order_block_bearish": [0.0] * 25,
        "fvg_bullish": [0.0] * 25,
        "fvg_bearish": [0.0] * 25,
    }, index=dates)

    # Bullish OB di bar 9 (terdeteksi saat rally bar 10)
    df.loc[dates[10], "order_block_bullish"] = 1.0
    df.loc[dates[9], "High"] = 2760.0
    df.loc[dates[9], "Low"] = 2755.0

    # Bullish FVG di bar 12 (antara High bar 10 dan Low bar 12)
    df.loc[dates[12], "fvg_bullish"] = 1.0
    df.loc[dates[10], "High"] = 2762.0  # Candle 1 High
    df.loc[dates[12], "Low"] = 2768.0   # Candle 3 Low (Gap 2762 - 2768)

    zones = SignalEngine.extract_active_ob_and_fvg(df, curr_price=2775.0)

    assert zones["bullish_ob"] is not None
    assert zones["bullish_ob"]["entry"] == 2760.0
    assert zones["bullish_ob"]["sl"] == 2755.0

    assert zones["bullish_fvg"] is not None
    assert zones["bullish_fvg"]["top"] == 2768.0
    assert zones["bullish_fvg"]["bottom"] == 2762.0
    assert zones["bullish_fvg"]["mid"] == 2765.0


def test_generate_limit_orders_snaps_to_ob_and_fvg():
    """Menguji bahwa limit order otomatis memilih harga entry di area FVG dan OB."""
    dates = pd.date_range("2026-10-20 08:00", periods=25, freq="15min")
    df = pd.DataFrame({
        "Open": [2750.0 + i for i in range(25)],
        "High": [2752.0 + i for i in range(25)],
        "Low": [2749.0 + i for i in range(25)],
        "Close": [2751.0 + i for i in range(25)],
        "order_block_bullish": [0.0] * 25,
        "order_block_bearish": [0.0] * 25,
        "fvg_bullish": [0.0] * 25,
        "fvg_bearish": [0.0] * 25,
    }, index=dates)

    # Bullish OB di bar 9
    df.loc[dates[10], "order_block_bullish"] = 1.0
    df.loc[dates[9], "High"] = 2760.0
    df.loc[dates[9], "Low"] = 2755.0

    # Bullish FVG di bar 12
    df.loc[dates[12], "fvg_bullish"] = 1.0
    df.loc[dates[10], "High"] = 2762.0
    df.loc[dates[12], "Low"] = 2768.0

    engine = SignalEngine()
    snapshot = {"ema_20": 2772.0, "ema_50": 2765.0, "atr": 3.0}

    orders = engine.generate_dual_sided_limit_orders(
        df=df,
        ticker="XAUUSD",
        curr_price=2775.0,
        snapshot=snapshot,
        trade_type="LONG",
        is_cent=True,
    )

    buy_orders = [o for o in orders if "BUY" in o["type"]]
    assert len(buy_orders) >= 2

    # Level 1 harus membidik FVG
    assert buy_orders[0]["price"] == 2768.0
    assert "FVG" in buy_orders[0]["label"]

    # Level 2 harus membidik OB
    assert buy_orders[1]["price"] == 2760.0
    assert "Order Block" in buy_orders[1]["label"]

    # SL harus berada di bawah Low OB (2755.0 - buffer)
    assert buy_orders[0]["sl"] < 2755.0
    assert buy_orders[1]["sl"] < 2755.0
