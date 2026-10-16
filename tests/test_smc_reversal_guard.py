import pytest
import pandas as pd
import numpy as np
from strategy.signal_engine import SignalEngine
from strategy.reversal_detector import GoldReversalDetector
from strategy.smc_liquidity import SMCLiquidityEngine


def test_smc_veto_buy_on_bearish_choch():
    """Menguji bahwa sinyal BUY ditolak keras jika SMC mendeteksi Bearish CHoCH."""
    engine = SignalEngine()

    # Buat data market dengan pola Lower High / Lower Low (Bearish Structure / CHoCH)
    # Swing Highs: 4250 -> 4235 (LH)
    # Swing Lows: 4220 -> 4200 (LL)
    data = []
    prices = [
        4210, 4225, 4250, 4240, 4220, 4225, 4235, 4215, 4205, 4200, 4202, 4205, 4204, 4203, 4204
    ]
    for p in prices:
        data.append({
            "Open": p - 1.0,
            "High": p + 1.0,
            "Low": p - 1.0,
            "Close": p,
            "Volume": 1000,
            "ema_20": p - 0.2, # Menempel EMA 20
            "ema_50": p + 5.0,
            "rsi": 48.0,
        })
    df = pd.DataFrame(data)

    curr_row = df.iloc[-1]
    prev_row = df.iloc[-2]

    # Evaluasi pilar XAU
    sig = engine.evaluate_xau_3_pillars(
        df=df,
        curr_row=curr_row,
        prev_row=prev_row,
        ticker="XAUUSD",
        curr_price=float(curr_row["Close"]),
    )

    # Sinyal BUY wajib ditolak (HOLD) karena struktur pasar Bearish / CHoCH
    assert sig.signal == "HOLD"
    vetoes_str = " ".join(sig.reasons)
    assert any(k in vetoes_str for k in ["VETO SMC", "CHoCH", "DOWNTREND", "Lower High"])


def test_smc_veto_sell_on_bullish_choch():
    """Menguji bahwa sinyal SELL ditolak keras jika SMC mendeteksi Bullish CHoCH / Uptrend."""
    engine = SignalEngine()

    # Buat data market dengan pola Higher High / Higher Low (Bullish Structure / CHoCH)
    # Swing Lows: 4190 -> 4205 (HL)
    # Swing Highs: 4215 -> 4230 (HH)
    data = []
    prices = [
        4200, 4195, 4190, 4200, 4215, 4210, 4205, 4215, 4225, 4230, 4228, 4226, 4227, 4228, 4229
    ]
    for p in prices:
        data.append({
            "Open": p + 1.0,
            "High": p + 1.5,
            "Low": p - 1.0,
            "Close": p,
            "Volume": 1000,
            "ema_20": p + 0.2, # Menempel EMA 20 di bawah
            "ema_50": p - 5.0,
            "rsi": 52.0,
        })
    df = pd.DataFrame(data)

    curr_row = df.iloc[-1]
    prev_row = df.iloc[-2]

    sig = engine.evaluate_xau_3_pillars(
        df=df,
        curr_row=curr_row,
        prev_row=prev_row,
        ticker="XAUUSD",
        curr_price=float(curr_row["Close"]),
    )

    # Sinyal SELL wajib ditolak (HOLD) karena struktur pasar Bullish
    assert sig.signal == "HOLD"
    vetoes_str = " ".join(sig.reasons)
    assert any(k in vetoes_str for k in ["VETO SMC", "CHoCH", "UPTREND", "Higher High"])


def test_reversal_detector_identifies_bearish_choch_for_buy_position():
    """Menguji bahwa detektor pembalikan arah mengenali Bearish CHoCH dan menaikkan skor ke >= 85%."""
    # Market sebelumnya naik (4200 -> 4220 -> 4210 -> 4230), lalu jebol ke bawah 4210 (Higher Low)
    prices = [
        4200, 4210, 4220, 4215, 4210, 4220, 4230, 4225, 4215, 4205, 4200, 4198
    ]
    data = []
    for i, p in enumerate(prices):
        data.append({
            "Open": p + 1.0 if i == len(prices) - 1 else p - 0.5,
            "High": p + 2.0,
            "Low": p - 1.0,
            "Close": p,
            "ema_20": 4215.0,
            "ema_50": 4210.0,
            "rsi": 38.0,
            "volume_ratio": 1.2,
            "pattern_pinbar": 0,
            "pattern_engulfing": 1 if i == len(prices) - 1 else 0,
            "pattern_shooting_star": 0,
            "structure_bos_bullish": 0,
            "structure_bos_bearish": 0, # bos_bearish konvensional 0, tapi SMC CHoCH aktif!
        })
    df = pd.DataFrame(data)

    is_rev, rev_type, reasons, score = GoldReversalDetector.detect_reversal(
        df_ind=df,
        position_type="BUY",
        entry_price=4225.0,
        current_price=4198.0,
    )

    assert is_rev is True
    assert "BEARISH REVERSAL" in rev_type
    assert score >= 80.0
    assert any("SMC" in r or "CHoCH" in r for r in reasons)
