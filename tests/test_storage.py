import os
import tempfile
from pathlib import Path
import pandas as pd
from data.storage import StockStorage


def test_storage_crud():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_stock.db"
        storage = StockStorage(db_path=db_path)

        # 1. Test save OHLCV
        dates = pd.date_range("2026-01-01", periods=5, freq="D")
        df = pd.DataFrame(
            {
                "Open": [100.0, 102.0, 101.0, 103.0, 105.0],
                "High": [105.0, 106.0, 104.0, 107.0, 108.0],
                "Low": [99.0, 100.0, 98.0, 101.0, 102.0],
                "Close": [102.0, 101.0, 103.0, 105.0, 107.0],
                "Volume": [1000.0, 1200.0, 1100.0, 1500.0, 2000.0],
            },
            index=dates,
        )

        saved_count = storage.save_ohlcv("BBCA.JK", interval="1d", df=df)
        assert saved_count == 5

        # 2. Test load OHLCV
        df_loaded = storage.load_ohlcv("BBCA.JK", interval="1d")
        assert len(df_loaded) == 5
        assert float(df_loaded["Close"].iloc[-1]) == 107.0

        # 3. Test save and get signal
        sig_id = storage.save_signal(
            ticker="BBCA.JK",
            strategy_name="TestStrategy",
            signal_type="BUY",
            price=107.0,
            reasons=["RSI Oversold"],
            candle_time="2026-01-05",
            is_notified=True,
        )
        assert sig_id is not None

        last_sig = storage.get_last_signal("BBCA.JK", "TestStrategy")
        assert last_sig is not None
        assert last_sig["signal_type"] == "BUY"
        assert last_sig["price"] == 107.0
