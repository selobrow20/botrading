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


def test_update_open_signals_outcome_and_winrate():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_winrate.db"
        storage = StockStorage(db_path=db_path)

        # 1. Save BUY signal on BBCA.JK: Entry=100, TP=105, SL=95
        sig_id_buy = storage.save_signal(
            ticker="BBCA.JK",
            strategy_name="SmartMoney",
            signal_type="BUY",
            price=100.0,
            reasons=["OrderBlock retest"],
            candle_time="2026-01-01 10:00:00",
            take_profit_price=105.0,
            stop_loss_price=95.0,
        )

        # 2. Save SELL signal on GC=F (Gold): Entry=2700, TP=2680, SL=2710
        sig_id_sell = storage.save_signal(
            ticker="GC=F",
            strategy_name="LiquiditySweep",
            signal_type="SELL",
            price=2700.0,
            reasons=["Liquidity grab"],
            candle_time="2026-01-01 10:00:00",
            take_profit_price=2680.0,
            stop_loss_price=2710.0,
        )

        # Check initial win rate (0 completed)
        initial_stats = storage.get_win_rate_stats()
        assert initial_stats["total_signals"] == 2
        assert initial_stats["open_count"] == 2
        assert initial_stats["completed"] == 0

        # Create future candles for BBCA.JK hitting TP (High >= 105)
        bbca_dates = pd.date_range("2026-01-01 11:00:00", periods=2, freq="h")
        bbca_df = pd.DataFrame(
            {
                "Open": [100.0, 103.0],
                "High": [102.0, 106.0],  # Bar 2 hits TP 105
                "Low": [99.0, 102.0],
                "Close": [101.0, 105.5],
                "Volume": [1000.0, 1500.0],
            },
            index=bbca_dates,
        )

        resolved_bbca = storage.update_open_signals_outcome("BBCA.JK", bbca_df)
        assert resolved_bbca == 1

        # Create future candles for GC=F hitting TP (Low <= 2680)
        gold_dates = pd.date_range("2026-01-01 11:00:00", periods=2, freq="h")
        gold_df = pd.DataFrame(
            {
                "Open": [2700.0, 2690.0],
                "High": [2705.0, 2695.0],
                "Low": [2692.0, 2675.0],  # Bar 2 hits TP 2680
                "Close": [2695.0, 2678.0],
                "Volume": [500.0, 800.0],
            },
            index=gold_dates,
        )

        resolved_gold = storage.update_open_signals_outcome("GC=F", gold_df)
        assert resolved_gold == 1

        # Check stats after both hit TP (100% win rate)
        stats = storage.get_win_rate_stats()
        assert stats["total_signals"] == 2
        assert stats["completed"] == 2
        assert stats["win_count"] == 2
        assert stats["lose_count"] == 0
        assert stats["win_rate_pct"] == 100.0
        assert stats["open_count"] == 0

        # Verify completed signals with outcome_note (keterangan evaluasi)
        comp_sigs = storage.get_recent_completed_signals(limit=5)
        assert len(comp_sigs) == 2
        for cs in comp_sigs:
            assert cs["outcome"] == "WIN"
            assert cs["outcome_note"] is not None
            assert len(cs["outcome_note"]) > 10
            assert "Take Profit" in cs["outcome_note"]

