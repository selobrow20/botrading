import time
from typing import Optional
import pandas as pd
import requests
import yfinance as yf
from config.settings import load_config, setup_logger
from data.storage import StockStorage

logger = setup_logger("fetcher")


class DataFetcher:
    """Fetcher data saham IDX dari Yahoo Finance & Spot Gold XAU/USD dengan mekanisme retry backoff dan caching SQLite."""

    def __init__(self, storage: Optional[StockStorage] = None):
        self.config = load_config()
        self.data_cfg = self.config.get("data", {})
        self.retry_attempts = self.data_cfg.get("retry_attempts", 3)
        self.backoff_factor = self.data_cfg.get("retry_backoff_factor", 2.0)
        self.storage = storage or StockStorage()

    @staticmethod
    def normalize_ticker(ticker: str) -> str:
        """
        Menormalisasi kode ticker saham atau komoditas global.
        - Memetakan XAUUSD, XAU/USD, GOLD, EMAS, GC=F ke XAUUSD (Spot Gold TradingView).
        - Menambahkan suffix .JK untuk saham Indonesia jika belum memiliki suffix bursa.
        """
        ticker_clean = ticker.strip().upper().replace(" ", "")
        
        # Mapping khusus untuk Emas Spot (XAU/USD)
        if ticker_clean in ["XAUUSD", "XAU/USD", "XAU-USD", "XAUUSD=X", "GOLD", "EMAS", "GC=F"]:
            return "XAUUSD"

        # Jika sudah memiliki suffix bursa (.JK, .US dll) atau simbol futures/forex (=F, =X, ^)
        if any(char in ticker_clean for char in [".", "=", "^", "-"]):
            return ticker_clean

        # Default saham Indonesia Bursa Efek Indonesia (BEI)
        return f"{ticker_clean}.JK"

    def fetch_spot_gold(self, interval: str = "15m", limit: int = 100) -> pd.DataFrame:
        """
        Mengambil data real-time Spot Gold (XAU/USD) dari data feed OTC/Forex (identik dengan TradingView OANDA:XAUUSD).
        """
        try:
            iv_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "30m": "30m",
                "1h": "1h",
                "60m": "1h",
                "4h": "4h",
                "1d": "1d",
            }
            mapped_iv = iv_map.get(interval, "15m")
            url = f"https://biquote.io/api/XAUUSD/ohlc?interval={mapped_iv}&limit={limit}"
            resp = requests.get(url, timeout=6)
            if resp.status_code == 200:
                data = resp.json().get("bars", [])
                if data and len(data) >= 10:
                    rows = []
                    for b in reversed(data):  # Urutkan kronologis tertua ke terbaru
                        rows.append({
                            "Date": pd.to_datetime(b["openTime"]),
                            "Open": float(b["open"]),
                            "High": float(b["high"]),
                            "Low": float(b["low"]),
                            "Close": float(b["close"]),
                            "Volume": float(b.get("tickVolume", 0) or b.get("volume", 0)),
                        })
                    df = pd.DataFrame(rows).set_index("Date")
                    if df.index.tz is not None:
                        df.index = df.index.tz_convert("Asia/Jakarta").tz_localize(None)
                    clean_df = self._clean_dataframe(df)
                    if not clean_df.empty:
                        logger.info(
                            f"Sukses mengambil {len(clean_df)} bar Spot Gold (XAU/USD) dari direct spot feed "
                            f"({clean_df.index[0].strftime('%Y-%m-%d %H:%M')} s/d {clean_df.index[-1].strftime('%Y-%m-%d %H:%M')})"
                        )
                        return clean_df
        except Exception as e:
            logger.warning(f"Gagal mengambil data Spot Gold dari primary feed: {e}")
        return pd.DataFrame()

    def fetch_from_mt5(self, symbol: str = "XAUUSDc", interval: str = "15m", limit: int = 100) -> pd.DataFrame:
        """
        Mengambil data candlestick langsung dari terminal MetaTrader 5 lokal (HFM Live Broker).
        Paling cepat, 0 latency, dan 100% identik dengan harga akun trading.
        """
        try:
            import MetaTrader5 as mt5
            from trading.mt5_bridge import MT5Bridge
            bridge = MT5Bridge()
            if not bridge.is_connected:
                bridge.connect()
            if not bridge.is_connected:
                return pd.DataFrame()

            target_symbol = symbol or bridge.gold_symbol or "XAUUSDc"
            mt5.symbol_select(target_symbol, True)

            tf_map = {
                "1m": mt5.TIMEFRAME_M1,
                "5m": mt5.TIMEFRAME_M5,
                "15m": mt5.TIMEFRAME_M15,
                "30m": mt5.TIMEFRAME_M30,
                "1h": mt5.TIMEFRAME_H1,
                "4h": mt5.TIMEFRAME_H4,
                "1d": mt5.TIMEFRAME_D1,
            }
            tf = tf_map.get(interval, mt5.TIMEFRAME_M15)
            rates = mt5.copy_rates_from_pos(target_symbol, tf, 0, limit)
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df["Date"] = pd.to_datetime(df["time"], unit="s")
                df.rename(columns={
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "tick_volume": "Volume"
                }, inplace=True)
                df.set_index("Date", inplace=True)
                clean_df = self._clean_dataframe(df[["Open", "High", "Low", "Close", "Volume"]])
                if not clean_df.empty:
                    logger.info(f"Sukses mengambil {len(clean_df)} bar Spot Gold langsung dari terminal MT5 ({target_symbol}).")
                    return clean_df
        except Exception as e:
            logger.debug(f"Gagal mengambil data dari MT5: {e}")
        return pd.DataFrame()

    def fetch_ohlcv(
        self,
        ticker: str,
        interval: str = "1d",
        period: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Mengambil data OHLCV dari MT5, direct spot feed, atau yfinance dengan toleransi error dan retry backoff.
        
        Args:
            ticker: Kode saham (misal BBCA atau BBCA.JK) atau instrumen global (XAUUSD)
            interval: Interval candle ('1d', '15m', '30m', '1h', dll)
            period: Periode data ('1mo', '3mo', '6mo', '1y', '2y', '60d', dll)
            start: Tanggal mulai format 'YYYY-MM-DD' (opsional)
            end: Tanggal akhir format 'YYYY-MM-DD' (opsional)
        
        Returns:
            pd.DataFrame dengan kolom standar ['Open', 'High', 'Low', 'Close', 'Volume']
        """
        normalized_ticker = self.normalize_ticker(ticker)

        # Jika instrumen adalah Emas Spot (XAUUSD):
        # 1. Utamakan direct Spot Gold feed (TradingView)
        # 2. Jika ada kendala jaringan, fallback langsung ke terminal MT5 HFM
        # 3. Terakhir fallback ke COMEX Gold Futures (GC=F)
        if normalized_ticker == "XAUUSD":
            spot_df = self.fetch_spot_gold(interval=interval, limit=100)
            if not spot_df.empty and len(spot_df) >= 15:
                return spot_df

            mt5_df = self.fetch_from_mt5(interval=interval, limit=100)
            if not mt5_df.empty and len(mt5_df) >= 15:
                return mt5_df

            logger.warning("Gagal fetch dari direct Spot Gold feed dan MT5, fallback ke COMEX Gold Futures (GC=F)...")
            normalized_ticker = "GC=F"

        if period is None and start is None:
            # Gunakan default dari config
            if "m" in interval or "h" in interval:
                period = self.data_cfg.get("intraday_period", "60d")
            else:
                period = self.data_cfg.get("default_period", "2y")

        attempt = 0
        current_delay = 1.0

        while attempt < self.retry_attempts:
            attempt += 1
            try:
                logger.info(
                    f"Mengambil data {normalized_ticker} (interval={interval}, "
                    f"period={period}, start={start}, end={end}) - Percobaan {attempt}/{self.retry_attempts}"
                )

                stock = yf.Ticker(normalized_ticker)
                if start or end:
                    df = stock.history(interval=interval, start=start, end=end, auto_adjust=True)
                else:
                    df = stock.history(interval=interval, period=period, auto_adjust=True)

                if df is None or df.empty:
                    logger.warning(
                        f"Data kosong diterima untuk {normalized_ticker} pada percobaan {attempt}."
                    )
                else:
                    # Bersihkan DataFrame
                    df = self._clean_dataframe(df)
                    if not df.empty:
                        logger.info(
                            f"Sukses mengambil {len(df)} bar data untuk {normalized_ticker} "
                            f"({df.index[0].strftime('%Y-%m-%d')} s/d {df.index[-1].strftime('%Y-%m-%d %H:%M')})"
                        )
                        return df

            except Exception as e:
                logger.error(
                    f"Error saat mengambil data {normalized_ticker} pada percobaan {attempt}: {str(e)}"
                )

            if attempt < self.retry_attempts:
                sleep_time = current_delay * (self.backoff_factor ** (attempt - 1))
                logger.info(f"Menunggu {sleep_time:.1f} detik sebelum retry...")
                time.sleep(sleep_time)

        logger.error(f"Gagal mengambil data {normalized_ticker} setelah {self.retry_attempts} percobaan.")
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardisasi index, penamaan kolom, dan tipe data."""
        clean_df = df.copy()

        # Handle Datetime/Date index
        if not isinstance(clean_df.index, pd.DatetimeIndex):
            clean_df.index = pd.to_datetime(clean_df.index)

        # Hapus timezone offset agar konsisten disimpan di SQLite
        if clean_df.index.tz is not None:
            clean_df.index = clean_df.index.tz_convert("Asia/Jakarta").tz_localize(None)

        # Standardisasi nama kolom
        cols_needed = ["Open", "High", "Low", "Close", "Volume"]
        for col in cols_needed:
            if col not in clean_df.columns:
                # Coba cari nama kolom case-insensitive
                found = False
                for c in clean_df.columns:
                    if str(c).lower() == col.lower():
                        clean_df.rename(columns={c: col}, inplace=True)
                        found = True
                        break
                if not found:
                    raise KeyError(f"Kolom {col} tidak ditemukan dalam data.")

        # Filter hanya kolom standar dan pastikan tipe numerik
        clean_df = clean_df[cols_needed].astype(float)
        # Hapus baris dengan nilai NaN pada OHLC
        clean_df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
        # Hapus baris hari libur / placeholder di mana Volume == 0
        clean_df = clean_df[clean_df["Volume"] > 0]
        clean_df.sort_index(ascending=True, inplace=True)
        return clean_df

    def fetch_and_store(
        self,
        ticker: str,
        interval: str = "1d",
        period: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Mengambil data dari yfinance dan langsung menyimpannya ke database SQLite."""
        normalized_ticker = self.normalize_ticker(ticker)
        df = self.fetch_ohlcv(normalized_ticker, interval=interval, period=period, start=start, end=end)
        if not df.empty:
            self.storage.save_ohlcv(normalized_ticker, interval=interval, df=df)
        return df

    def get_data(
        self,
        ticker: str,
        interval: str = "1d",
        period: Optional[str] = None,
        force_fetch: bool = False,
    ) -> pd.DataFrame:
        """
        Membaca data dari SQLite jika ada, atau fetch dari yfinance jika belum ada atau force_fetch=True.
        """
        normalized_ticker = self.normalize_ticker(ticker)
        if not force_fetch:
            df = self.storage.load_ohlcv(normalized_ticker, interval=interval)
            if not df.empty:
                logger.debug(f"Memuat {len(df)} bar data untuk {normalized_ticker} dari SQLite cache.")
                return df

        # Jika belum ada atau force_fetch
        return self.fetch_and_store(normalized_ticker, interval=interval, period=period)
