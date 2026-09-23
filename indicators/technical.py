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

    @staticmethod
    def candlestick_patterns(
        open_s: pd.Series,
        high_s: pd.Series,
        low_s: pd.Series,
        close_s: pd.Series,
    ) -> Dict[str, pd.Series]:
        """
        Deteksi pola Candlestick Reversal (Bob Volman & Mega Profit Forex).
        - Pinbar / Hammer: Ekor bawah panjang (rejection) >= 1.8x body, penutupan di area atas.
        - Bullish Engulfing: Candle hijau menutupi penuh body candle merah sebelumnya.
        """
        body = (close_s - open_s).abs()
        range_val = (high_s - low_s).replace(0, np.nan)
        lower_wick = np.where(close_s >= open_s, open_s - low_s, close_s - low_s)
        lower_wick_s = pd.Series(lower_wick, index=close_s.index)

        # Pinbar Rejection: ekor bawah panjang
        pinbar_cond = (
            (lower_wick_s >= 1.8 * body)
            & (lower_wick_s >= 0.45 * range_val)
            & (close_s >= low_s + (0.45 * range_val))
        )
        pinbar = pinbar_cond.astype(float)

        # Bullish Engulfing
        prev_red = open_s.shift(1) > close_s.shift(1)
        curr_green = close_s > open_s
        engulfing_body = (open_s <= close_s.shift(1)) & (close_s >= open_s.shift(1))
        engulfing = (prev_red & curr_green & engulfing_body).astype(float)

        rejection_ratio = (lower_wick_s / range_val).fillna(0.0)

        return {
            "pattern_pinbar": pinbar,
            "pattern_engulfing": engulfing,
            "rejection_wick_ratio": rejection_ratio,
        }

    @staticmethod
    def ichimoku(
        high_s: pd.Series,
        low_s: pd.Series,
        close_s: pd.Series,
    ) -> Dict[str, pd.Series]:
        """
        Ichimoku Kinko Hyo (Tenkan 9, Kijun 26, Senkou A & B 52).
        """
        tenkan = (high_s.rolling(9, min_periods=5).max() + low_s.rolling(9, min_periods=5).min()) / 2.0
        kijun = (high_s.rolling(26, min_periods=10).max() + low_s.rolling(26, min_periods=10).min()) / 2.0

        senkou_a_calc = (tenkan + kijun) / 2.0
        senkou_b_calc = (high_s.rolling(52, min_periods=15).max() + low_s.rolling(52, min_periods=15).min()) / 2.0

        senkou_a = senkou_a_calc.shift(26).fillna(senkou_a_calc)
        senkou_b = senkou_b_calc.shift(26).fillna(senkou_b_calc)

        cloud_top = np.maximum(senkou_a, senkou_b)
        cloud_bottom = np.minimum(senkou_a, senkou_b)

        above_cloud = (close_s > cloud_top).astype(float)
        tk_cross = ((tenkan >= kijun) & (tenkan.shift(1) < kijun.shift(1))).astype(float)
        cloud_green = (senkou_a >= senkou_b).astype(float)

        return {
            "ichimoku_tenkan": tenkan,
            "ichimoku_kijun": kijun,
            "ichimoku_senkou_a": senkou_a,
            "ichimoku_senkou_b": senkou_b,
            "ichimoku_cloud_top": cloud_top,
            "ichimoku_above_cloud": above_cloud,
            "ichimoku_tk_cross": tk_cross,
            "ichimoku_cloud_green": cloud_green,
        }

    @staticmethod
    def fibonacci_levels(
        high_s: pd.Series,
        low_s: pd.Series,
        close_s: pd.Series,
        period: int = 30,
    ) -> Dict[str, pd.Series]:
        """
        Fibonacci Retracement (Golden Pocket: 50% - 61.8%).
        """
        swing_high = high_s.rolling(period, min_periods=10).max()
        swing_low = low_s.rolling(period, min_periods=10).min()
        diff = (swing_high - swing_low).replace(0, np.nan)

        fib_382 = swing_high - (0.382 * diff)
        fib_500 = swing_high - (0.500 * diff)
        fib_618 = swing_high - (0.618 * diff)

        # Golden zone: harga menguji area antara 50% dan 61.8%
        in_golden_zone = (
            (low_s <= fib_500 * 1.002)
            & (close_s >= fib_618 * 0.995)
        ).astype(float)

        return {
            "fib_swing_high": swing_high,
            "fib_swing_low": swing_low,
            "fib_382": fib_382,
            "fib_500": fib_500,
            "fib_618": fib_618,
            "fib_in_golden_zone": in_golden_zone,
        }

    @staticmethod
    def bob_volman_price_action(
        high_s: pd.Series,
        low_s: pd.Series,
        close_s: pd.Series,
        ema20: pd.Series,
        ema50: pd.Series,
    ) -> Dict[str, pd.Series]:
        """
        Konsep Price Action Bob Volman (Under Standing Price Action):
        - Pullback Reversal di area 20 EMA saat tren naik.
        - Buildup: kompresi range candle sebelum breakout.
        """
        uptrend = (ema20 >= ema50) | (close_s >= ema50)
        pullback_cond = (
            uptrend
            & (low_s <= ema20 * 1.004)
            & (close_s >= ema20 * 0.996)
        )
        volman_pullback = pullback_cond.astype(float)

        candle_range = (high_s - low_s)
        avg_range_20 = candle_range.rolling(20, min_periods=5).mean().replace(0, np.nan)
        recent_range_3 = candle_range.rolling(3, min_periods=2).mean()
        buildup_ratio = (recent_range_3 / avg_range_20).fillna(1.0)
        volman_buildup = (buildup_ratio < 0.75).astype(float)

        return {
            "volman_pullback": volman_pullback,
            "volman_buildup": volman_buildup,
            "volman_buildup_ratio": buildup_ratio,
        }

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

        # 6. Pola Candlestick Reversal (Bob Volman & Mega Profit)
        cand_dict = cls.candlestick_patterns(res["Open"], res["High"], res["Low"], res["Close"])
        for k, v in cand_dict.items():
            res[k] = v

        # 7. Ichimoku Kinko Hyo
        ichi_dict = cls.ichimoku(res["High"], res["Low"], res["Close"])
        for k, v in ichi_dict.items():
            res[k] = v

        # 8. Fibonacci Retracement Levels (Golden Pocket)
        fib_dict = cls.fibonacci_levels(res["High"], res["Low"], res["Close"])
        for k, v in fib_dict.items():
            res[k] = v

        # 9. Bob Volman Price Action (20 EMA Pullback & Buildup)
        ema20_col = res["EMA_20"] if "EMA_20" in res.columns else res["Close"]
        ema50_col = res["EMA_50"] if "EMA_50" in res.columns else res["Close"]
        volman_dict = cls.bob_volman_price_action(
            res["High"], res["Low"], res["Close"], ema20_col, ema50_col
        )
        for k, v in volman_dict.items():
            res[k] = v

        # Tambahkan lowercase alias untuk harga dasar
        res["close"] = res["Close"]
        res["open"] = res["Open"]
        res["high"] = res["High"]
        res["low"] = res["Low"]
        res["volume"] = res["Volume"]

        logger.debug(f"Kalkulasi seluruh indikator teknikal selesai ({len(res.columns)} kolom).")
        return res
