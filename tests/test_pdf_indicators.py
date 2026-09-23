import pytest
import pandas as pd
import numpy as np
from indicators.technical import TechnicalIndicators
from strategy.rules import get_strategy, Strategy
from strategy.signal_engine import SignalEngine

def test_candlestick_patterns():
    # Buat data sintetis untuk Pinbar dan Engulfing
    # Bar 1: Normal red bar
    # Bar 2: Bullish Pinbar (long lower shadow)
    # Bar 3: Normal red bar
    # Bar 4: Bullish Engulfing bar
    dates = pd.date_range("2026-01-01", periods=5, freq="15min")
    df = pd.DataFrame({
        "Open": [100.0, 95.0, 98.0, 94.0, 102.0],
        "High": [102.0, 96.0, 99.0, 101.0, 103.0],
        "Low":  [98.0,  88.0, 96.0, 93.0, 100.0],
        "Close":[99.0,  95.0, 96.0, 100.0, 101.0],
        "Volume": [1000, 2000, 1200, 3000, 1500],
    }, index=dates)

    patterns = TechnicalIndicators.candlestick_patterns(
        df["Open"], df["High"], df["Low"], df["Close"]
    )
    
    # Bar 2 (index 1): Low=88, Open=95, Close=95, High=96
    # Lower wick = 7, body = 0, range = 8 -> Ekor = 7/8 = 87.5% -> Pinbar!
    assert patterns["pattern_pinbar"].iloc[1] == 1.0

    # Bar 4 (index 3): Prev bar Open=98, Close=96 (Red, body 2)
    # Current bar Open=94, Close=100 (Green, body 6, engulfs 96-98) -> Engulfing!
    assert patterns["pattern_engulfing"].iloc[3] == 1.0


def test_ichimoku_calculations():
    # 60 bar data
    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=60, freq="15min")
    prices = 100.0 + np.cumsum(np.random.randn(60) * 0.5)
    df = pd.DataFrame({
        "Open": prices,
        "High": prices + 1.0,
        "Low": prices - 1.0,
        "Close": prices + 0.2,
        "Volume": 1000,
    }, index=dates)

    res = TechnicalIndicators.ichimoku(df["High"], df["Low"], df["Close"])
    assert "ichimoku_tenkan" in res
    assert "ichimoku_kijun" in res
    assert "ichimoku_senkou_a" in res
    assert "ichimoku_senkou_b" in res
    assert len(res["ichimoku_above_cloud"]) == 60


def test_fibonacci_and_volman():
    dates = pd.date_range("2026-01-01", periods=40, freq="15min")
    prices = np.linspace(100, 150, 40)
    df = pd.DataFrame({
        "Open": prices,
        "High": prices + 2.0,
        "Low": prices - 2.0,
        "Close": prices + 1.0,
        "Volume": 1500,
    }, index=dates)

    fib = TechnicalIndicators.fibonacci_levels(df["High"], df["Low"], df["Close"], period=30)
    assert "fib_500" in fib
    assert "fib_618" in fib
    assert fib["fib_swing_high"].iloc[-1] >= fib["fib_swing_low"].iloc[-1]

    ema20 = df["Close"].ewm(span=20).mean()
    ema50 = df["Close"].ewm(span=50).mean()
    volman = TechnicalIndicators.bob_volman_price_action(df["High"], df["Low"], df["Close"], ema20, ema50)
    assert "volman_pullback" in volman
    assert "volman_buildup" in volman


def test_master_confluence_strategy():
    strat = get_strategy("Master_Confluence_Strategy")
    assert strat is not None
    assert len(strat.buy_rules) >= 3

    # Test evaluasi bar
    dates = pd.date_range("2026-01-01", periods=40, freq="15min")
    df = pd.DataFrame({
        "Open": [100.0] * 40,
        "High": [105.0] * 40,
        "Low": [95.0] * 40,
        "Close": [102.0] * 40,
        "Volume": [2000] * 40,
    }, index=dates)

    df_ind = TechnicalIndicators.add_all_indicators(df)
    engine = SignalEngine([strat])
    sig = engine.evaluate_bar(df_ind, ticker="TEST.JK", strategy=strat)
    assert sig is not None
    assert sig.signal in ["BUY", "SELL", "HOLD"]
