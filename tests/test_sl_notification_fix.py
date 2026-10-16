import pytest
import sqlite3
import pandas as pd
from unittest.mock import MagicMock
from notify.telegram_bot import TelegramNotifier
from data.storage import StockStorage

def test_telegram_sl_never_reported_as_tp():
    """Memastikan kesepakatan rugi (SL/loss) tidak akan pernah dilaporkan sebagai TP."""
    notifier = TelegramNotifier()
    notifier.storage = MagicMock()
    notifier.storage.get_win_rate_stats.return_value = {
        "win_rate": 80.0,
        "win_count": 8,
        "lose_count": 2,
        "total_pnl": 15.0,
        "gold_stats": {"win_rate": 80.0, "win": 8, "lose": 2, "total_pnl": 15.0}
    }

    # Kasus 1: BUY_LIMIT yang kena SL (Entry 4174.55, Exit 4162.66, rugi cash -45 USC)
    deal_report = {
        "ticker": "XAUUSDm",
        "signal_type": "BUY_LIMIT",
        "price": 4174.55,
        "exit_price": 4162.66,
        "pnl_cash": -45.0,
        "outcome": "LOSE",
        "pnl_pct": 0.29, # Sengaja diberi positif untuk menguji override proteksi
        "take_profit_price": 4200.0,
        "stop_loss_price": 4162.66,
        "from_mt5": True,
        "currency": "USC"
    }

    msg = notifier.format_tp_sl_report(deal_report)
    assert "STOP LOSS TERSENTUH" in msg
    assert "TAKE PROFIT TERCAPAI" not in msg
    assert "HASIL: LOSE / PROTEKSI MODAL" in msg
    assert "BUY / LONG" in msg
    assert "-$" in msg or "-0.29%" in msg or "Total Kerugian" in msg

def test_telegram_sl_with_zero_or_negative_cash():
    """Kasus deal dengan pnl_cash negatif murni."""
    notifier = TelegramNotifier()
    notifier.storage = MagicMock()
    notifier.storage.get_win_rate_stats.return_value = {"win_rate": 50.0, "win_count": 1, "lose_count": 1}

    deal_report = {
        "ticker": "XAUUSD",
        "signal_type": "BUY",
        "price": 2000.0,
        "exit_price": 1990.0,
        "pnl_cash": -100.0,
        "outcome": "LOSE",
        "pnl_pct": -0.5,
    }

    msg = notifier.format_tp_sl_report(deal_report)
    assert "STOP LOSS TERSENTUH" in msg
    assert "TAKE PROFIT TERCAPAI" not in msg

def test_find_signal_by_mt5_ticket_matches_limit_types(tmp_path):
    """Memastikan find_signal_by_mt5_ticket mencocokkan BUY dengan BUY_LIMIT."""
    db_file = tmp_path / "test_trading.db"
    storage = StockStorage(db_path=str(db_file))

    # Insert sinyal BUY_LIMIT
    storage.save_signal(
        ticker="XAUUSD",
        strategy_name="SmartLimitStrategy",
        signal_type="BUY_LIMIT",
        price=4174.55,
        reasons=["Fibonacci 61.8%"],
        candle_time="2026-10-16 12:00:00",
        take_profit_price=4200.0,
        stop_loss_price=4160.0
    )

    # MT5 deal entry adalah BUY, bukan BUY_LIMIT
    sig = storage.find_signal_by_mt5_ticket(ticket=12345, ticker="XAUUSD", signal_type="BUY")
    assert sig is not None
    assert sig["signal_type"] == "BUY_LIMIT"
    assert sig["price"] == 4174.55

def test_resolve_open_signals_with_limit_orders(tmp_path):
    """Memastikan resolve_open_signals mengenali BUY_LIMIT dan menghitung SL secara tepat."""
    db_file = tmp_path / "test_trading.db"
    storage = StockStorage(db_path=str(db_file))

    storage.save_signal(
        ticker="XAUUSD",
        strategy_name="SmartLimitStrategy",
        signal_type="BUY_LIMIT",
        price=4174.55,
        reasons=["Test"],
        candle_time="2026-10-16 10:00:00",
        take_profit_price=4200.0,
        stop_loss_price=4162.66
    )

    # Bar harga menembus SL (Low <= 4162.66)
    df = pd.DataFrame([
        {"High": 4175.0, "Low": 4160.0, "Close": 4161.0, "Open": 4174.0}
    ], index=pd.to_datetime(["2026-10-16 10:05:00"]))

    resolved = storage.resolve_open_signals("XAUUSD", df)
    assert len(resolved) == 1
    res = resolved[0]
    assert res["outcome"] == "LOSE"
    assert res["pnl_pct"] < 0
    assert "Stop Loss" in res["outcome_note"]
