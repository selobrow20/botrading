import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from data.storage import StockStorage
from scheduler.run_scheduler import PipelineRunner
from strategy.signal_engine import SignalResult

def test_user_authorization(tmp_path):
    db_file = tmp_path / "test_auth.db"
    storage = StockStorage(db_path=str(db_file))

    # 1. New user registration returns pending
    status = storage.register_or_get_user("12345", "testuser", "Test User")
    assert status == "pending"
    assert not storage.is_user_authorized("12345")

    # 2. Approve user
    assert storage.approve_user("12345")
    assert storage.is_user_authorized("12345")

    # 3. Approved chat IDs contains the user and admin
    approved = storage.get_approved_chat_ids(admin_id="99999")
    assert "12345" in approved
    assert "99999" in approved

    # 4. Reject user
    assert storage.reject_user("12345")
    assert not storage.is_user_authorized("12345")

def test_candle_freshness():
    runner = PipelineRunner()
    tz_wib = ZoneInfo("Asia/Jakarta")
    now_wib = datetime.now(tz_wib)

    # 1. Fresh candle (5 minutes old)
    fresh_time = (now_wib - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    fresh_sig = SignalResult(
        ticker="BBCA.JK",
        strategy_name="DayTrading",
        signal="BUY",
        price=10000,
        candle_time=fresh_time,
        reasons=["Test"],
    )
    is_fresh, _ = runner._is_candle_fresh(fresh_sig, interval="15m")
    assert is_fresh is True

    # 2. Stale candle (90 minutes old)
    stale_time = (now_wib - timedelta(minutes=90)).strftime("%Y-%m-%d %H:%M:%S")
    stale_sig = SignalResult(
        ticker="BBCA.JK",
        strategy_name="DayTrading",
        signal="BUY",
        price=10000,
        candle_time=stale_time,
        reasons=["Test"],
    )
    is_fresh, reason = runner._is_candle_fresh(stale_sig, interval="15m")
    assert is_fresh is False
    assert "kedaluwarsa" in reason.lower()

    # 3. Daily candle is always treated as fresh
    is_fresh_1d, _ = runner._is_candle_fresh(stale_sig, interval="1d")
    assert is_fresh_1d is True
