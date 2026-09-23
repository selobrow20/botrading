from typing import Optional, Dict, Any, List, Tuple
import pandas as pd
import numpy as np
from config.settings import load_config, setup_logger

logger = setup_logger("indicators")


class TechnicalIndicators:
    """Koleksi kalkulator indikator teknikal berbasis Pandas & NumPy vectorized."""

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        """Simple Moving Average (SMA)."""
        return series.rolling(window=period, min_periods=period).mean()

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average (EMA)."""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """
        Relative Strength Index (RSI) dengan Wilder's smoothing (standar industri).
        """
        delta = series.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)

        # Wilder's exponential moving average: alpha = 1 / period
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # Handle edge cases (misal loss selalu 0 -> RSI = 100)
        rsi = rsi.fillna(50.0)
        return rsi

    @staticmethod
    def macd(
        series: pd.Series,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Moving Average Convergence Divergence (MACD).
        Returns: (macd_line, signal_line, histogram)
        """
        ema_fast = series.ewm(span=fast_period, adjust=False).mean()
        ema_slow = series.ewm(span=slow_period, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def bollinger_bands(
        series: pd.Series,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        """
        Bollinger Bands.
        Returns: (upper_band, middle_band, lower_band, bandwidth_pct)
        """
        middle_band = series.rolling(window=period, min_periods=period).mean()
        std = series.rolling(window=period, min_periods=period).std()
        upper_band = middle_band + (std_dev * std)
        lower_band = middle_band - (std_dev * std)
        bandwidth_pct = ((upper_band - lower_band) / middle_band) * 100.0
        return upper_band, middle_band, lower_band, bandwidth_pct

    @staticmethod
    def volume_ratio(volume_series: pd.Series, period: int = 20) -> Tuple[pd.Series, pd.Series]:
        """
        Volume Analysis: Rata-rata volume N-periode dan rasio volume terkini terhadap rata-rata.
        Returns: (volume_sma, volume_ratio)
        """
        volume_sma = volume_series.rolling(window=period, min_periods=period).mean()
        ratio = volume_series / volume_sma.replace(0, np.nan)
        return volume_sma, ratio

    @classmethod
    def add_all_indicators(
        cls,
        df: pd.DataFrame,
        config: Optional[Dict[str, Any]] = None,
    ) -> pd.DataFrame:
        """
        Menghitung dan menambahkan seluruh indikator teknikal ke DataFrame OHLCV
        berdasarkan konfigurasi yang diberikan (atau config.yaml).
        """
        if df.empty:
            return df.copy()

        cfg = config or load_config().get("indicators", {})
        res = df.copy()

        # 1. Moving Averages (SMA & EMA)
        ma_cfg = cfg.get("moving_averages", {})
        periods = ma_cfg.get("periods", [20, 50, 200])
        for p in periods:
            res[f"SMA_{p}"] = cls.sma(res["Close"], p)
            res[f"EMA_{p}"] = cls.ema(res["Close"], p)
            # Tambahkan alias lowercase agar mudah diakses di rule engine
            res[f"sma_{p}"] = res[f"SMA_{p}"]
            res[f"ema_{p}"] = res[f"EMA_{p}"]

        # 2. RSI
        rsi_cfg = cfg.get("rsi", {})
        rsi_period = rsi_cfg.get("period", 14)
        res[f"RSI_{rsi_period}"] = cls.rsi(res["Close"], rsi_period)
        res["rsi"] = res[f"RSI_{rsi_period}"]

        # 3. MACD
        macd_cfg = cfg.get("macd", {})
        fast_p = macd_cfg.get("fast_period", 12)
        slow_p = macd_cfg.get("slow_period", 26)
        sig_p = macd_cfg.get("signal_period", 9)
        macd_line, sig_line, hist = cls.macd(res["Close"], fast_p, slow_p, sig_p)
        res["MACD"] = macd_line
        res["MACD_Signal"] = sig_line
        res["MACD_Hist"] = hist
        res["macd"] = macd_line
        res["macd_signal"] = sig_line
        res["macd_hist"] = hist

        # 4. Bollinger Bands
        bb_cfg = cfg.get("bollinger_bands", {})
        bb_period = bb_cfg.get("period", 20)
        bb_std = bb_cfg.get("std_dev", 2.0)
        upper, middle, lower, width = cls.bollinger_bands(res["Close"], bb_period, bb_std)
        res["BB_Upper"] = upper
        res["BB_Middle"] = middle
        res["BB_Lower"] = lower
        res["BB_Width"] = width
        res["bb_upper"] = upper
        res["bb_middle"] = middle
        res["bb_lower"] = lower

        # 5. Volume Analysis
        vol_cfg = cfg.get("volume", {})
        vol_period = vol_cfg.get("avg_period", 20)
        vol_sma, vol_ratio = cls.volume_ratio(res["Volume"], vol_period)
        res[f"Volume_SMA_{vol_period}"] = vol_sma
        res["Volume_Ratio"] = vol_ratio
        res["volume_sma_20"] = vol_sma
        res["volume_ratio"] = vol_ratio

        # Tambahkan lowercase alias untuk harga dasar
        res["close"] = res["Close"]
        res["open"] = res["Open"]
        res["high"] = res["High"]
        res["low"] = res["Low"]
        res["volume"] = res["Volume"]

        logger.debug(f"Kalkulasi seluruh indikator teknikal selesai ({len(res.columns)} kolom).")
        return res
