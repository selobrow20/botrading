import os
from pathlib import Path
import pandas as pd
import numpy as np
import pytest

from notify.chart_generator import ChartGenerator, CHARTS_DIR
from strategy.signal_engine import SignalResult


def test_chart_generator_gold_and_stock():
    dates = pd.date_range("2026-09-23 09:00", periods=40, freq="15min")
    df_dummy = pd.DataFrame(
        {
            "Open": np.linspace(4300, 4320, 40),
            "High": np.linspace(4305, 4325, 40),
            "Low": np.linspace(4295, 4315, 40),
            "Close": np.linspace(4302, 4322, 40),
            "Volume": np.random.randint(100, 1000, 40),
        },
        index=dates,
    )

    # 1. Test Gold Chart
    chart_gold = ChartGenerator.generate_chart(
        df=df_dummy,
        ticker_symbol="XAUUSD",
        interval="15m",
        signal_type="BUY",
        entry_price=4306.0,
        tp_price=4331.8,
        sl_price=4290.9,
        setup_grade="A+",
        pdf_confluence_score=0.85,
    )
    assert chart_gold is not None
    assert Path(chart_gold).exists()
    assert os.path.getsize(chart_gold) > 10000

    # 2. Test Stock Chart (IDX)
    df_stock = pd.DataFrame(
        {
            "Open": np.linspace(9000, 9300, 40),
            "High": np.linspace(9050, 9350, 40),
            "Low": np.linspace(8950, 9250, 40),
            "Close": np.linspace(9020, 9320, 40),
            "Volume": np.random.randint(50000, 200000, 40),
        },
        index=dates,
    )
    chart_stock = ChartGenerator.generate_chart(
        df=df_stock,
        ticker_symbol="BBCA.JK",
        interval="1d",
        signal_type="BUY",
        entry_price=9000.0,
        tp_price=9350.0,
        sl_price=8850.0,
        setup_grade="A",
        pdf_confluence_score=0.65,
    )
    assert chart_stock is not None
    assert Path(chart_stock).exists()
    assert os.path.getsize(chart_stock) > 10000


def test_evaluate_asset_potential():
    dates = pd.date_range("2026-09-23 09:00", periods=20, freq="15min")
    df = pd.DataFrame(
        {
            "Open": [100.0] * 20,
            "High": [101.0] * 20,
            "Low": [99.0] * 20,
            "Close": [100.5] * 20,
            "Volume": [1000] * 20,
            "volman_pullback": [0] * 19 + [1],
            "rejection_wick_ratio": [0.1] * 19 + [0.45],
            "RSI": [50.0] * 20,
        },
        index=dates,
    )

    # Potential due to Volman Pullback + Rejection Wick
    sig_hold = SignalResult(
        ticker="BBCA.JK",
        strategy_name="SmartMoney",
        signal="HOLD",
        price=100.5,
        reasons=[],
        candle_time="2026-09-23 10:00:00",
    )
    is_pot, badge, desc = ChartGenerator.evaluate_asset_potential(sig_hold, df)
    assert is_pot is True
    assert "Volman" in badge

    # Potential due to Signal BUY Grade A+
    sig_buy = SignalResult(
        ticker="XAUUSD",
        strategy_name="PDFConfluence",
        signal="BUY",
        price=4306.0,
        reasons=["Pola Pinbar"],
        candle_time="2026-09-23 10:00:00",
        setup_grade="A+",
        pdf_confluence_score=0.85,
    )
    is_pot_buy, badge_buy, _ = ChartGenerator.evaluate_asset_potential(sig_buy, df)
    assert is_pot_buy is True
    assert "BUY" in badge_buy

    # Neutral / Not potential
    df_flat = pd.DataFrame(
        {
            "Open": [100.0] * 20,
            "High": [100.5] * 20,
            "Low": [99.5] * 20,
            "Close": [100.0] * 20,
            "Volume": [1000] * 20,
            "volman_pullback": [0] * 20,
            "rejection_wick_ratio": [0.0] * 20,
            "RSI": [50.0] * 20,
        },
        index=dates,
    )
    is_pot_neutral, _, _ = ChartGenerator.evaluate_asset_potential(sig_hold, df_flat)
    assert is_pot_neutral is False


def test_chart_cleanup():
    # Calling cleanup should run without errors
    ChartGenerator.cleanup_old_charts(max_age_hours=0)
