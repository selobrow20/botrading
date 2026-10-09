import pytest
import pandas as pd
import numpy as np
from strategy.mtf_engine import (
    check_h1_snr,
    check_m30_trendline,
    get_m15_direction,
    trigger_m5_entry,
    run_top_down_mtf_pipeline,
)


def _create_synthetic_ohlcv(base_price: float, count: int = 50, trend: str = "bullish") -> pd.DataFrame:
    """Helper membuat DataFrame OHLCV sintetis."""
    rows = []
    price = base_price
    for i in range(count):
        if trend == "bullish":
            price += 0.50
            o = price - 0.20
            h = price + 0.60
            l = price - 0.40
            c = price + 0.30
        elif trend == "bearish":
            price -= 0.50
            o = price + 0.20
            h = price + 0.40
            l = price - 0.60
            c = price - 0.30
        else:  # sideways
            o = price
            h = price + 0.80
            l = price - 0.80
            c = price + (0.10 if i % 2 == 0 else -0.10)
        rows.append({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1000})
    return pd.DataFrame(rows)


def test_check_h1_snr_blocks_buy_near_resistance():
    """Memastikan harga dalam 15 pips dari Resistance H1 memblokir BUY."""
    # Resistance ada di 4120.0, Support di 4080.0
    df_h1 = pd.DataFrame({
        "Open": [4100.0] * 30,
        "High": [4105.0] * 20 + [4120.0] + [4105.0] * 9,
        "Low": [4095.0] * 20 + [4080.0] + [4095.0] * 9,
        "Close": [4102.0] * 30,
        "Volume": [1000] * 30,
    })

    # Harga 4119.0 (jarak 1.00 USD <= 1.50 USD / 15 pips dari Resistance 4120.0)
    res = check_h1_snr(df_h1, curr_price=4119.0, pip_buffer=1.50)
    assert res["can_buy"] is False
    assert res["can_sell"] is True
    assert "BLOKIR BUY H1" in res["reason"]
    assert res["dist_to_resistance"] <= 1.50


def test_check_h1_snr_blocks_sell_near_support():
    """Memastikan harga dalam 15 pips dari Support H1 memblokir SELL."""
    df_h1 = pd.DataFrame({
        "Open": [4100.0] * 30,
        "High": [4110.0] * 20 + [4120.0] + [4110.0] * 9,
        "Low": [4095.0] * 20 + [4080.0] + [4095.0] * 9,
        "Close": [4102.0] * 30,
        "Volume": [1000] * 30,
    })

    # Harga 4081.0 (jarak 1.00 USD <= 1.50 USD / 15 pips dari Support 4080.0)
    res = check_h1_snr(df_h1, curr_price=4081.0, pip_buffer=1.50)
    assert res["can_buy"] is True
    assert res["can_sell"] is False
    assert "BLOKIR SELL H1" in res["reason"]
    assert res["dist_to_support"] <= 1.50


def test_check_h1_snr_clear_in_middle():
    """Memastikan harga di area tengah bebas eksekusi BUY dan SELL."""
    df_h1 = pd.DataFrame({
        "Open": [4100.0] * 30,
        "High": [4105.0] * 20 + [4130.0] + [4105.0] * 9,
        "Low": [4095.0] * 20 + [4070.0] + [4095.0] * 9,
        "Close": [4100.0] * 30,
        "Volume": [1000] * 30,
    })

    # Harga 4100.0 (jauh dari 4130 dan 4070)
    res = check_h1_snr(df_h1, curr_price=4100.0, pip_buffer=1.50)
    assert res["can_buy"] is True
    assert res["can_sell"] is True
    assert res["status"] == "CLEAR"


def test_check_m30_trendline_breakout():
    """Memastikan deteksi breakout dan bounce pada trendline M30."""
    highs = [4100.0] * 35
    lows = [4090.0] * 35
    closes = [4095.0] * 35
    opens = [4095.0] * 35

    # Pivot high 1 di bar 10 & pivot high 2 di bar 25
    highs[10] = 4105.0
    highs[25] = 4108.0
    # Pivot low 1 di bar 5 & pivot low 2 di bar 20
    lows[5] = 4085.0
    lows[20] = 4088.0

    # Candle breakout di bar terakhir (Close & High menembus ke atas)
    highs[-1] = 4120.0
    closes[-1] = 4119.0

    df_m30 = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": [1000] * 35})
    res_bo = check_m30_trendline(df_m30, curr_price=4120.0)
    assert res_bo["trendline_bias"] == "BUY"
    assert "BREAKOUT" in res_bo["condition"]


def test_get_m15_direction_bullish_and_bearish():
    """Memastikan penentuan arah tren M15 dan penguncian arah eksekusi."""
    # Data M15 Bullish
    df_bull = _create_synthetic_ohlcv(base_price=4100.0, count=45, trend="bullish")
    curr_bull_p = float(df_bull["Close"].iloc[-1])
    res_bull = get_m15_direction(df_bull, curr_price=curr_bull_p)
    assert res_bull["direction"] == "BUY"
    assert res_bull["locked_direction"] == "BUY"

    # Data M15 Bearish
    df_bear = _create_synthetic_ohlcv(base_price=4150.0, count=45, trend="bearish")
    curr_bear_p = float(df_bear["Close"].iloc[-1])
    res_bear = get_m15_direction(df_bear, curr_price=curr_bear_p)
    assert res_bear["direction"] == "SELL"
    assert res_bear["locked_direction"] == "SELL"


def test_trigger_m5_entry_veto_lacks_rejection_wick():
    """Memastikan M5 gatekeeper membatalkan order jika rejection wick < 30%."""
    h1_ok = {"can_buy": True, "can_sell": True, "h1_resistance": 4150.0, "h1_support": 4050.0}
    m30_ok = {"trendline_bias": "BUY", "condition": "UPTREND_CHANNEL"}
    m15_ok = {"direction": "BUY", "structure": "BULLISH_HH_HL"}

    # Candle M5 marubozu / tanpa ekor bawah (High 4105, Low 4100, Open 4100, Close 4105 -> lower wick 0)
    df_m5_no_wick = pd.DataFrame([{
        "Open": 4100.0,
        "High": 4105.0,
        "Low": 4100.0,
        "Close": 4105.0,
        "Volume": 1000,
    }] * 15)

    res = trigger_m5_entry(
        df_m5=df_m5_no_wick,
        h1_res=h1_ok,
        m30_res=m30_ok,
        m15_res=m15_ok,
        curr_price=4105.0,
        min_wick_ratio=0.30,
        min_rr_ratio=2.0,
    )
    assert res["can_execute"] is False
    assert "VETO REJECTION M5" in res["reason"]
    assert res["rejection_wick_pct"] < 30.0


def test_trigger_m5_entry_success_with_rr_at_least_1_to_2():
    """Memastikan M5 berhasil mengeksekusi BUY jika wick >= 30% dan RR >= 1:2."""
    h1_ok = {"can_buy": True, "can_sell": True, "h1_resistance": 4150.0, "h1_support": 4050.0}
    m30_ok = {"trendline_bias": "BUY", "condition": "BOUNCE_SUPPORT"}
    m15_ok = {"direction": "BUY", "structure": "BULLISH_HH_HL"}

    # Candle M5 Pinbar / Hammer Rejection:
    # High: 4105.0, Low: 4095.0 (Range = 10.0)
    # Open: 4103.0, Close: 4104.0
    # Lower wick: min(4103, 4104) - 4095 = 8.0 -> 8.0 / 10.0 = 80% wick (>= 30%!)
    df_m5_pinbar = pd.DataFrame([
        {"Open": 4100.0, "High": 4102.0, "Low": 4098.0, "Close": 4101.0, "Volume": 1000}
    ] * 14 + [
        {"Open": 4103.0, "High": 4105.0, "Low": 4095.0, "Close": 4104.0, "Volume": 1000}
    ])

    res = trigger_m5_entry(
        df_m5=df_m5_pinbar,
        h1_res=h1_ok,
        m30_res=m30_ok,
        m15_res=m15_ok,
        curr_price=4104.0,
        min_wick_ratio=0.30,
        min_rr_ratio=2.0,
    )
    assert res["can_execute"] is True
    assert res["action"] == "BUY"
    assert res["rejection_wick_pct"] >= 30.0
    assert res["risk_reward_ratio"] >= 2.0
    assert res["stop_loss"] < 4104.0
    assert res["take_profit"] > 4104.0


def test_run_top_down_mtf_pipeline_end_to_end():
    """Memastikan orchestrator run_top_down_mtf_pipeline berjalan utuh."""
    df_h1 = _create_synthetic_ohlcv(4100.0, 50, "bullish")
    df_m30 = _create_synthetic_ohlcv(4100.0, 50, "bullish")
    df_m15 = _create_synthetic_ohlcv(4100.0, 50, "bullish")
    curr_p = float(df_m15["Close"].iloc[-1])
    df_m5 = _create_synthetic_ohlcv(curr_p - 10.0, 45, "bullish")
    # M5 pinbar (ekor bawah panjang)
    last_m5 = {"Open": curr_p - 1.0, "High": curr_p + 1.0, "Low": curr_p - 8.0, "Close": curr_p, "Volume": 1000}
    df_m5 = pd.concat([df_m5, pd.DataFrame([last_m5])], ignore_index=True)

    mtf_mock = {
        "H1": df_h1,
        "M30": df_m30,
        "M15": df_m15,
        "M5": df_m5,
    }

    pipeline_res = run_top_down_mtf_pipeline(
        symbol="XAUUSD",
        curr_price=curr_p,
        is_cent=True,
        mtf_data=mtf_mock,
    )
    assert "step_1_h1" in pipeline_res
    assert "step_2_m30" in pipeline_res
    assert "step_3_m15" in pipeline_res
    assert "step_4_m5" in pipeline_res
    assert pipeline_res["step_3_m15"]["direction"] == "BUY"
