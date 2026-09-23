import pytest
import pandas as pd
import numpy as np
from indicators.technical import TechnicalIndicators


@pytest.fixture
def sample_ohlcv():
    """Membuat data sintetis OHLCV untuk pengujian unit."""
    dates = pd.date_range("2026-01-01", periods=100, freq="D")
    np.random.seed(42)
    close = 5000 + np.cumsum(np.random.randn(100) * 50)
    high = close + np.random.rand(100) * 30
    low = close - np.random.rand(100) * 30
    open_p = close + np.random.randn(100) * 10
    volume = np.random.randint(1_000_000, 10_000_000, size=100)

    df = pd.DataFrame(
        {
            "Open": open_p,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )
    return df


def test_sma_calculation(sample_ohlcv):
    sma20 = TechnicalIndicators.sma(sample_ohlcv["Close"], 20)
    assert len(sma20) == 100
    assert pd.isna(sma20.iloc[0])
    assert not pd.isna(sma20.iloc[19])
    # Nilai baris ke-20 harus sama dengan rata-rata 20 baris pertama
    expected = sample_ohlcv["Close"].iloc[:20].mean()
    assert np.isclose(sma20.iloc[19], expected)


def test_ema_calculation(sample_ohlcv):
    ema20 = TechnicalIndicators.ema(sample_ohlcv["Close"], 20)
    assert len(ema20) == 100
    assert not pd.isna(ema20.iloc[0])
    # EMA harus bergerak mendekati harga close
    assert ema20.min() >= sample_ohlcv["Close"].min() * 0.9
    assert ema20.max() <= sample_ohlcv["Close"].max() * 1.1


def test_rsi_bounds(sample_ohlcv):
    rsi = TechnicalIndicators.rsi(sample_ohlcv["Close"], 14)
    assert len(rsi) == 100
    valid_rsi = rsi.dropna()
    assert (valid_rsi >= 0.0).all()
    assert (valid_rsi <= 100.0).all()


def test_macd_formula(sample_ohlcv):
    macd, signal, hist = TechnicalIndicators.macd(sample_ohlcv["Close"], 12, 26, 9)
    # Histogram harus selalu sama dengan (MACD - Signal)
    diff = (macd - signal) - hist
    assert np.allclose(diff.dropna(), 0.0)


def test_bollinger_bands_ordering(sample_ohlcv):
    upper, middle, lower, width = TechnicalIndicators.bollinger_bands(sample_ohlcv["Close"], 20, 2.0)
    valid_df = pd.DataFrame({"up": upper, "mid": middle, "low": lower}).dropna()
    assert (valid_df["up"] >= valid_df["mid"]).all()
    assert (valid_df["mid"] >= valid_df["low"]).all()
