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

    # 1. Fresh candle (5 minutes old) for Gold
    fresh_time = (now_wib - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    fresh_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="DayTrading",
        signal="BUY",
        price=4135.0,
        candle_time=fresh_time,
        reasons=["Test"],
    )
    is_fresh, _ = runner._is_candle_fresh(fresh_sig, interval="15m")
    assert is_fresh is True

    # 2. Stale candle (25 minutes old > 18 min limit for 15m)
    stale_time = (now_wib - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S")
    stale_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="DayTrading",
        signal="BUY",
        price=4135.0,
        candle_time=stale_time,
        reasons=["Test"],
    )
    is_fresh, reason = runner._is_candle_fresh(stale_sig, interval="15m")
    assert is_fresh is False
    assert "telat" in reason.lower() or "kedaluwarsa" in reason.lower()

    # 3. Yesterday candle is strictly rejected as stale
    yesterday_time = (now_wib - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    yesterday_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="DayTrading",
        signal="BUY",
        price=4135.0,
        candle_time=yesterday_time,
        reasons=["Test"],
    )
    is_fresh_yest, reason_yest = runner._is_candle_fresh(yesterday_sig, interval="1d")
    assert is_fresh_yest is False
    assert "lampau" in reason_yest.lower() or "telat" in reason_yest.lower()

    # 4. Price Drift Guard: Live price has already run > $3.0 away from entry
    is_fresh_drift, reason_drift = runner._is_candle_fresh(fresh_sig, interval="15m", current_live_price=4140.0)
    assert is_fresh_drift is False
    assert "sudah lari" in reason_drift.lower() or "telat" in reason_drift.lower()


def test_copier_license_protocol(tmp_path):
    """Menguji protokol lisensi anti-share & auto-stop untuk member copier."""
    db_file = tmp_path / "test_lic.db"
    storage = StockStorage(db_path=str(db_file))

    # 1. Member resmi disetujui 1 hari
    storage.register_or_get_user("member_cctv", "cctv", "Cctv")
    storage.approve_user("member_cctv", "1d")

    # Simulasi logika handler bot
    def generate_license_response(uid: str) -> str:
        auth = storage.is_user_authorized(uid, admin_id="8754997836")
        all_u = {u["chat_id"]: u for u in storage.list_all_users()}
        u = all_u.get(uid)
        exp = u.get("expires_at") if u else ""
        rem = u.get("remaining_label", "") if u else "Expired"
        status_flag = "VALID" if auth else "EXPIRED"
        return f"LIC_INFO|{uid}|{status_flag}|{exp or 'LIFETIME'}|{rem}"

    # Cek member resmi
    resp = generate_license_response("member_cctv")
    parts = resp.split("|")
    assert parts[1] == "member_cctv"
    assert parts[2] == "VALID"
    assert "Sisa" in parts[4]

    # Cek stranger / anti-share (akun telegram orang lain yg ga disetujui)
    resp_stranger = generate_license_response("stranger_id")
    parts_stranger = resp_stranger.split("|")
    assert parts_stranger[1] == "stranger_id"
    assert parts_stranger[2] == "EXPIRED"

    # Cek setelah expired
    import sqlite3
    with sqlite3.connect(storage.db_path) as conn:
        conn.execute("UPDATE authorized_users SET expires_at = '2020-01-01 00:00:00' WHERE chat_id = 'member_cctv'")

    resp_exp = generate_license_response("member_cctv")
    parts_exp = resp_exp.split("|")
    assert parts_exp[2] == "EXPIRED"


def test_copier_broadcast_and_document_sending(tmp_path):
    from notify.telegram_bot import TelegramNotifier
    from notify.chat_agent import ChatAgent

    db_file = tmp_path / "test_copier.db"
    storage = StockStorage(db_path=str(db_file))
    storage.register_or_get_user("member_vip1", "vip1", "VIP Trader 1")
    storage.approve_user("member_vip1", "30d")

    # Create dummy member_copier.zip for testing
    dummy_zip = tmp_path / "member_copier.zip"
    dummy_zip.write_bytes(b"PK\x05\x06" + b"\x00" * 18)  # minimal empty zip file

    notifier = TelegramNotifier(token="mock_token", chat_id="8754997836", storage=storage)
    res = notifier.broadcast_copier_update(zip_path=str(dummy_zip))
    assert res["success"] is True
    assert res["sent_count"] >= 1
    assert "8754997836" in res["recipients"]

    # Test send_document single
    ok = notifier.send_document(str(dummy_zip), caption="Test", target_chat_id="member_vip1")
    assert ok is True

    # Test ChatAgent intent classification for copier
    cls_res = ChatAgent.classify_intent("bor kirim zip copier dong")
    assert cls_res["intent"] == "COPIER"
    cls_res2 = ChatAgent.classify_intent("minta file copier")
    assert cls_res2["intent"] == "COPIER"


def test_tp_sl_dedup_and_stale_suppression(tmp_path):
    import pandas as pd
    from data.storage import StockStorage
    from notify.telegram_bot import TelegramNotifier

    db_file = tmp_path / "test_dedup.db"
    storage = StockStorage(db_path=str(db_file))

    # 1. Test database notification flag
    sig_id = storage.save_signal(
        ticker="XAUUSD",
        strategy_name="9 Buku",
        signal_type="SELL",
        price=4133.76,
        reasons=["Test reasons"],
        candle_time="2026-10-05 11:45:00",
        is_notified=True,
        take_profit_price=4106.25,
        stop_loss_price=4142.93,
    )
    assert not storage.is_signal_outcome_notified(sig_id)

    # 2. Test resolve_open_signals with old candle data (stale > 30 minutes)
    df_old = pd.DataFrame(
        [
            {"datetime": "2026-10-05 13:00:00", "Open": 4140.0, "High": 4145.0, "Low": 4135.0, "Close": 4143.0, "Volume": 1000},
        ]
    ).set_index("datetime")
    resolved = storage.resolve_open_signals("XAUUSD", df_old)
    assert len(resolved) == 1
    res0 = resolved[0]
    assert res0["outcome"] == "LOSE"
    assert res0["exit_price"] == 4142.93
    assert res0["is_stale"] is True  # Verified stale!
    assert storage.is_signal_outcome_notified(sig_id) is True  # Automatically marked notified so never pushed!

    # 3. Test TelegramNotifier deduplication
    notifier = TelegramNotifier(token="mock_tok", chat_id="12345", storage=storage)
    async def mock_send(*args, **kwargs):
        return True
    notifier._async_send_text = mock_send

    # Since is_signal_outcome_notified is True, send_tp_sl_report should suppress it
    assert notifier.send_tp_sl_report(res0) is True

    # Test fresh signal in notifier cache
    fresh_sig = {
        "id": 99999,
        "ticker": "XAUUSD",
        "signal_type": "BUY",
        "price": 4150.0,
        "exit_price": 4160.0,
        "take_profit_price": 4160.0,
        "stop_loss_price": 4140.0,
        "outcome": "WIN",
        "pnl_pct": 0.24,
        "candle_time": "2026-10-06 09:00:00",
        "exit_time": "2026-10-06 09:15:00",
        "outcome_note": "Test profit",
    }
    # First send: passes through
    ok1 = notifier.send_tp_sl_report(fresh_sig)
    assert ok1 is True
    # Second send: caught by in-memory deduplication cache
    dedup_key = f"99999_XAUUSD_WIN_{round(4160.0, 2)}"
    assert dedup_key in notifier._reported_outcomes_cache
    ok2 = notifier.send_tp_sl_report(fresh_sig)
    assert ok2 is True

