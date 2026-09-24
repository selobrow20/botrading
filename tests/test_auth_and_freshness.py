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

    # Superadmin is always authorized
    assert storage.is_user_authorized("8754997836")

    # 2. Approve user
    assert storage.approve_user("12345")
    assert storage.is_user_authorized("12345")

    # 3. Approved chat IDs contains the user, admin, and superadmin
    approved = storage.get_approved_chat_ids(admin_id="99999")
    assert "12345" in approved
    assert "99999" in approved
    assert "8754997836" in approved

    # 4. Reject user
    assert storage.reject_user("12345")
    assert not storage.is_user_authorized("12345")


def test_access_duration_and_expiry(tmp_path):
    from data.storage import parse_access_duration
    import sqlite3

    # Test parse_access_duration
    td1, lbl1 = parse_access_duration("1h")
    assert td1 == timedelta(hours=1)
    assert lbl1 == "1 Jam"

    td6, lbl6 = parse_access_duration("6h")
    assert td6 == timedelta(hours=6)
    assert lbl6 == "6 Jam"

    td1d, lbl1d = parse_access_duration("1d")
    assert td1d == timedelta(days=1)
    assert lbl1d == "1 Hari"

    td_life, lbl_life = parse_access_duration("lifetime")
    assert td_life is None
    assert "Permanen" in lbl_life  # bisa "Permanen" atau "Permanen (Tanpa Batas Waktu)"

    # Test storage integration
    db_file = tmp_path / "test_duration.db"
    storage = StockStorage(db_path=str(db_file))

    storage.register_or_get_user("u_hourly", "hourlyuser", "Hourly User")

    # Approve with 1 hour
    ok, exp, label = storage.approve_user("u_hourly", "1h")
    assert ok is True
    assert label == "1 Jam"
    assert exp is not None
    assert storage.is_user_authorized("u_hourly") is True

    # Simulate expiration by setting expires_at to the past
    with sqlite3.connect(storage.db_path) as conn:
        conn.execute(
            "UPDATE authorized_users SET expires_at = ? WHERE chat_id = ?",
            ("2020-01-01 00:00:00", "u_hourly")
        )

    # Now user should be expired and not authorized
    assert storage.is_user_authorized("u_hourly") is False
    approved_ids = storage.get_approved_chat_ids(admin_id="admin_1")
    assert "u_hourly" not in approved_ids

    # Extend user by 2 hours
    ok_ext, new_exp, ext_lbl = storage.extend_user("u_hourly", "2h")
    assert ok_ext is True
    assert ext_lbl == "2 Jam"
    assert storage.is_user_authorized("u_hourly") is True

    # Check list_all_users contains remaining time label
    users = storage.list_all_users()
    target_user = next((u for u in users if u["chat_id"] == "u_hourly"), None)
    assert target_user is not None
    assert "Sisa" in target_user["remaining_label"]

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
