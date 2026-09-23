import time
from typing import Optional
import pandas as pd
import yfinance as yf
from config.settings import load_config, setup_logger
from data.storage import StockStorage

logger = setup_logger("fetcher")


class DataFetcher:
    """Fetcher data saham IDX dari Yahoo Finance dengan mekanisme retry backoff dan caching SQLite."""

    def __init__(self, storage: Optional[StockStorage] = None):
        self.config = load_config()
        self.data_cfg = self.config.get("data", {})
        self.retry_attempts = self.data_cfg.get("retry_attempts", 3)
        self.backoff_factor = self.data_cfg.get("retry_backoff_factor", 2.0)
        self.storage = storage or StockStorage()

    @staticmethod
    def normalize_ticker(ticker: str) -> str:
        """Menambahkan suffix .JK untuk saham Indonesia jika belum ada."""
        ticker_clean = ticker.strip().upper()
        if not ticker_clean.endswith(".JK") and not "." in ticker_clean:
            return f"{ticker_clean}.JK"
        return ticker_clean

    def fetch_ohlcv(
        self,
        ticker: str,
        interval: str = "1d",
        period: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Mengambil data OHLCV dari yfinance dengan toleransi error dan retry backoff.
        
        Args:
            ticker: Kode saham (misal BBCA atau BBCA.JK)
            interval: Interval candle ('1d', '15m', '30m', '1h', dll)
            period: Periode data ('1mo', '3mo', '6mo', '1y', '2y', '60d', dll)
            start: Tanggal mulai format 'YYYY-MM-DD' (opsional)
            end: Tanggal akhir format 'YYYY-MM-DD' (opsional)
        
        Returns:
            pd.DataFrame dengan kolom standar ['Open', 'High', 'Low', 'Close', 'Volume']
        """
        normalized_ticker = self.normalize_ticker(ticker)
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
