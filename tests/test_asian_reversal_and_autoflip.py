import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from strategy.reversal_detector import GoldReversalDetector
from strategy.signal_engine import SignalEngine
from scheduler.run_scheduler import PipelineRunner


def test_fast_impulsive_reversal_asian_session_buy():
    """Menguji deteksi junam cepat (flash drop) pada posisi BUY di Sesi Asia."""
    entry_price = 4159.0
    current_price = 4135.0  # Floating minus 24.0 USD = 240 pips
    
    # Buat dummy DataFrame M5 dengan candle merah tebal
    df_m5 = pd.DataFrame([
        {"Open": 4145.0, "High": 4145.5, "Low": 4138.0, "Close": 4139.0, "ema_20": 4148.0},
        {"Open": 4139.0, "High": 4139.5, "Low": 4134.5, "Close": 4135.0, "ema_20": 4146.0},
    ])
    
    is_rev, rev_type, reasons, score = GoldReversalDetector.detect_fast_impulsive_reversal(
        position_type="BUY",
        entry_price=entry_price,
        current_price=current_price,
        df_m5=df_m5,
        threshold_pips=22.0,
        session_code="ASIA",
    )
    
    assert is_rev is True
    assert "FAST BEARISH PLUNGE" in rev_type
    assert "Asian" in rev_type or any("Asia" in r for r in reasons)
    assert score >= 85.0
    assert any("Junam Impulsif" in r for r in reasons)


def test_fast_impulsive_reversal_asian_session_sell():
    """Menguji deteksi lonjakan cepat (flash pump) pada posisi SELL di Sesi Asia."""
    entry_price = 4125.0
    current_price = 4150.0  # Floating minus 25.0 USD = 250 pips
    
    df_m5 = pd.DataFrame([
        {"Open": 4135.0, "High": 4142.0, "Low": 4134.5, "Close": 4141.0, "ema_20": 4132.0},
        {"Open": 4141.0, "High": 4151.0, "Low": 4140.5, "Close": 4150.0, "ema_20": 4135.0},
    ])
    
    is_rev, rev_type, reasons, score = GoldReversalDetector.detect_fast_impulsive_reversal(
        position_type="SELL",
        entry_price=entry_price,
        current_price=current_price,
        df_m5=df_m5,
        threshold_pips=22.0,
        session_code="TOKYO",
    )
    
    assert is_rev is True
    assert "FAST BULLISH PUMP" in rev_type
    assert score >= 85.0


def test_signal_engine_anti_knife_asian_session():
    """Memastikan Signal Engine menolak BUY LIMIT mutlak saat M15 breakdown di Sesi Asia."""
    engine = SignalEngine()
    
    # Buat DataFrame M15 dengan tren breakdown ke bawah EMA 20 & 50
    candles = []
    base_p = 4160.0
    for i in range(20):
        p = base_p - (i * 1.5)
        candles.append({
            "Open": p + 1.0,
            "High": p + 1.5,
            "Low": p - 0.5,
            "Close": p,
            "EMA_20": p + 4.0,
            "ema_20": p + 4.0,
            "EMA_50": p + 8.0,
            "ema_50": p + 8.0,
            "atr": 3.5,
        })
    df = pd.DataFrame(candles)
    curr_price = df["Close"].iloc[-1]
    
    snapshot = {
        "atr": 3.5,
        "ema_20": df["EMA_20"].iloc[-1],
        "ema_50": df["EMA_50"].iloc[-1],
    }
    
    with patch("strategy.signal_engine.get_trading_session", return_value=("ASIA", "Sesi Asia")):
        orders = engine.generate_dual_sided_limit_orders(
            df=df,
            ticker="XAUUSD",
            curr_price=curr_price,
            snapshot=snapshot,
            trade_type="AUTO",
            is_cent=True,
        )
    
    # Mutlak TIDAK boleh ada order BUY_LIMIT saat breakdown!
    buy_orders = [o for o in orders if "BUY" in o["type"]]
    sell_orders = [o for o in orders if "SELL" in o["type"]]
    assert len(buy_orders) == 0, "BUY LIMIT tidak boleh ada saat M15 breakdown!"
    assert len(sell_orders) > 0, "SELL LIMIT wajib dipasang untuk mengikuti tren turun!"


def test_scheduler_reversal_guard_fast_cut_loss_and_flip():
    """Memastikan check_gold_reversal_guard menutup posisi tanpa menunggu 15 menit saat fast plunge."""
    runner = PipelineRunner()
    
    # Mock MT5 Bridge
    mock_bridge = MagicMock()
    mock_bridge.enabled = True
    mock_bridge.is_available.return_value = True
    
    # Posisi baru buka 120 detik yang lalu (< 900 detik) tapi floating minus 25 pips
    mock_bridge.get_open_positions.return_value = [
        {
            "ticket": 778811,
            "symbol": "XAUUSD",
            "type": "BUY",
            "price_open": 4159.0,
            "price_current": 4134.0,  # Minus 25.0 USD (250 pips)
            "profit": -12.5,
            "volume": 0.05,
            "time": 1000.0,
        }
    ]
    mock_bridge.close_position.return_value = {"success": True}
    mock_bridge.execute_signal.return_value = {"success": True, "ticket": 990011}
    
    # Mock fetcher dengan minimal 15 bar agar lolos validasi data historis
    mock_df_gold = pd.DataFrame([
        {
            "Open": 4160.0 - i,
            "High": 4164.0 - i,
            "Low": 4155.0 - i,
            "Close": 4156.0 - i,
            "Volume": 100.0,
            "ema_20": 4152.0 - i,
            "ema_50": 4150.0 - i,
        }
        for i in range(20)
    ])
    runner.fetcher = MagicMock()
    runner.fetcher.get_data.return_value = mock_df_gold
    runner.notifier = MagicMock()
    runner.storage = MagicMock()
    
    with patch("time.time", return_value=1120.0), \
         patch("trading.mt5_bridge.MT5Bridge", return_value=mock_bridge), \
         patch("strategy.signal_engine.get_trading_session", return_value=("ASIA", "Sesi Asia")), \
         patch.object(runner, "config", {
             "mt5": {
                 "enable_reversal_auto_close": True,
                 "enable_fast_reversal_guard": True,
                 "fast_reversal_pips_threshold": 22.0,
                 "enable_reversal_flip": True,
             }
         }):
        closed = runner.check_gold_reversal_guard()
        
        assert len(closed) == 1
        assert closed[0]["ticket"] == 778811
        # Memastikan bridge.close_position dipanggil seketika tanpa tertahan grace period 15m!
        mock_bridge.close_position.assert_called_once_with(778811)
        # Memastikan pending order dibatalkan & flip dieksekusi
        mock_bridge.cancel_all_pending_orders.assert_called_once()
        mock_bridge.execute_signal.assert_called_once()
        flip_sig = mock_bridge.execute_signal.call_args[0][0]
        assert flip_sig.signal == "SELL", "Auto-flip harus membalik posisi BUY ke SELL!"
