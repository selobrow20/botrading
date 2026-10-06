import io
import json
import zipfile
import pytest
from pathlib import Path

from member_copier.client_copier import (
    CLIENT_COPIER_VERSION,
    apply_zip_update,
    check_and_apply_ota_update,
    parse_version,
)


def test_copier_version_exists():
    assert CLIENT_COPIER_VERSION == "2.4.0"
    v_file = Path("member_copier/version.json")
    assert v_file.exists()
    data = json.loads(v_file.read_text(encoding="utf-8"))
    assert data["version"] == "2.4.0"
    assert parse_version("2.4.0") > parse_version("2.3.8")
    assert parse_version("2.4.1") > parse_version("2.4.0")


def test_apply_zip_update_preserves_user_config(tmp_path, monkeypatch):
    copier_dir = tmp_path / "member_copier"
    copier_dir.mkdir()

    # User's existing custom config
    custom_cfg = {
        "bot_username": "my_custom_bot",
        "default_lot": 0.02,
        "magic_number": 999999,
        "custom_user_setting": "preserve_me"
    }
    cfg_file = copier_dir / "config.json"
    cfg_file.write_text(json.dumps(custom_cfg), encoding="utf-8")

    # Create dummy zip with updated client_copier.py and a default config.json
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as z:
        z.writestr("client_copier.py", "# New client copier code v2.3.0")
        z.writestr("PANDUAN_MEMBER.txt", "Panduan baru")
        z.writestr("config.json", json.dumps({
            "bot_username": "selo_saham_bot",
            "default_lot": 0.05,
            "magic_number": 888888,
            "new_feature_key": True
        }))

    zip_bytes = zip_buffer.getvalue()

    # Monkeypatch __file__ in client_copier to point to tmp_path
    monkeypatch.setattr("member_copier.client_copier.Path", lambda *args: (copier_dir / "client_copier.py") if "__file__" in str(args) else Path(*args))

    # Test applying zip
    target_copier_file = copier_dir / "client_copier.py"
    target_copier_file.write_text("# Old code", encoding="utf-8")

    import member_copier.client_copier as cc
    # Call apply_zip_update directly with zip bytes
    z = zipfile.ZipFile(io.BytesIO(zip_bytes), "r")
    with z:
        for member in z.infolist():
            filename = Path(member.filename).name
            dest_file = copier_dir / filename
            if filename.lower() == "config.json" and cfg_file.exists():
                old_cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                new_cfg = json.loads(z.read(member).decode("utf-8"))
                new_cfg.update(old_cfg)
                dest_file.write_text(json.dumps(new_cfg), encoding="utf-8")
            else:
                dest_file.write_bytes(z.read(member))

    # Verify client_copier.py was updated
    assert target_copier_file.read_text(encoding="utf-8") == "# New client copier code v2.3.0"

    # Verify user's custom settings were preserved, and new keys added
    result_cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert result_cfg["default_lot"] == 0.02  # Preserved!
    assert result_cfg["magic_number"] == 999999  # Preserved!
    assert result_cfg["custom_user_setting"] == "preserve_me"  # Preserved!
    assert result_cfg["new_feature_key"] is True  # Merged!


def test_usd_vs_cent_account_detection():
    from unittest.mock import MagicMock
    from member_copier.client_copier import MT5MemberBridge

    # Test 1: USD Standard Account (broker currency is USD, server standard)
    cfg = {"account_type": "auto", "usd_lot": 0.01, "cent_lot": 0.05, "us_session_cent_lot": 0.08}
    bridge = MT5MemberBridge.__new__(MT5MemberBridge)
    bridge.cfg = cfg
    mock_mt5 = MagicMock()
    mock_acc_usd = MagicMock()
    mock_acc_usd.currency = "USD"
    mock_acc_usd.server = "HFMarkets-Live"
    mock_acc_usd.company = "HF Markets Ltd"
    mock_mt5.account_info.return_value = mock_acc_usd
    bridge.mt5 = mock_mt5

    assert bridge.is_cent_account() is False
    lot, desc = bridge.calculate_lot_size({}, is_cent=False)
    assert lot == 0.01
    assert "USD Standard" in desc

    # Test 2: Cent Account (currency USC)
    mock_acc_cent = MagicMock()
    mock_acc_cent.currency = "USC"
    mock_acc_cent.server = "HFMarkets-LiveCent"
    mock_acc_cent.company = "HF Markets Ltd"
    mock_mt5.account_info.return_value = mock_acc_cent

    assert bridge.is_cent_account() is True
    # Test 3: Manual override to USD even if currency says USC
    bridge.cfg = {"account_type": "usd", "usd_lot": 0.01}
    assert bridge.is_cent_account() is False

    # Test 4: Manual override to USC
    bridge.cfg = {"account_type": "usc", "cent_lot": 0.05}
    assert bridge.is_cent_account() is True


def test_parse_signal_short_long_and_limits():
    from member_copier.client_copier import parse_signal

    # Test 1: Sinyal SHORT BUY (Scalping)
    msg_short_buy = (
        "🟢 <b>SINYAL ENTRY (MASUK / BUY): XAU/USD (Gold)</b>\n"
        "🌐 <b>Market:</b> H4 = <code>BULLISH</code>\n"
        "⚡ <b>Trade Type:</b> <code>SHORT — SCALPING</code>\n"
        "🧭 <b>Direction:</b> <code>BUY</code>\n"
        "📍 <b>Harga Entry:</b> <code>$4,150.00</code>\n"
        "🎯 <b>Take Profit (TP):</b> <code>$4,156.00</code>\n"
        "🛑 <b>Stop Loss (SL):</b> <code>$4,144.00</code>\n"
    )
    sig1 = parse_signal(msg_short_buy)
    assert sig1["action"] == "BUY"
    assert sig1["trade_type"] == "SHORT"
    assert sig1["entry_price"] == 4150.0
    assert sig1["tp_price"] == 4156.0
    assert sig1["sl_price"] == 4144.0

    # Test 2: Sinyal SHORT SELL (Scalping)
    msg_short_sell = (
        "🔴 <b>SINYAL ENTRY (SELL): XAU/USD (Gold)</b>\n"
        "🌐 <b>Market:</b> H4 = <code>BEARISH</code>\n"
        "⚡ <b>Trade Type:</b> <code>SHORT — SCALPING</code>\n"
        "🧭 <b>Direction:</b> <code>SELL</code>\n"
        "📍 <b>Harga Entry Short:</b> <code>$4,150.00</code>\n"
        "🎯 <b>Take Profit (TP):</b> <code>$4,144.00</code>\n"
        "🛑 <b>Stop Loss (SL):</b> <code>$4,156.00</code>\n"
    )
    sig2 = parse_signal(msg_short_sell)
    assert sig2["action"] == "SELL"
    assert sig2["trade_type"] == "SHORT"
    assert sig2["entry_price"] == 4150.0

    # Test 3: Sinyal LONG BUY (Swing 3:1)
    msg_long_buy = (
        "🟢 <b>SINYAL ENTRY (MASUK / BUY): XAU/USD (Gold)</b>\n"
        "🌐 <b>Market:</b> H4 = <code>BULLISH</code>\n"
        "⚡ <b>Trade Type:</b> <code>LONG — INTRADAY/SWING</code>\n"
        "🧭 <b>Direction:</b> <code>BUY</code>\n"
        "🛡️ <b>Break Even:</b> <code>+60 pips</code>\n"
        "📍 <b>Harga Entry:</b> <code>$4,150.00</code>\n"
        "🎯 <b>Take Profit (TP):</b> <code>$4,174.00</code>\n"
        "🛑 <b>Stop Loss (SL):</b> <code>$4,142.00</code>\n"
    )
    sig3 = parse_signal(msg_long_buy)
    assert sig3["action"] == "BUY"
    assert sig3["trade_type"] == "LONG"

    # Test 4: Sinyal LONG SELL (Swing 3:1)
    msg_long_sell = (
        "🔴 <b>SINYAL ENTRY (SELL): XAU/USD (Gold)</b>\n"
        "🌐 <b>Market:</b> H4 = <code>BEARISH</code>\n"
        "⚡ <b>Trade Type:</b> <code>LONG — INTRADAY/SWING</code>\n"
        "🧭 <b>Direction:</b> <code>SELL</code>\n"
        "🛡️ <b>Break Even:</b> <code>+60 pips</code>\n"
        "📍 <b>Harga Entry Short:</b> <code>$4,150.00</code>\n"
        "🎯 <b>Take Profit (TP):</b> <code>$4,126.00</code>\n"
        "🛑 <b>Stop Loss (SL):</b> <code>$4,158.00</code>\n"
    )
    sig4 = parse_signal(msg_long_sell)
    assert sig4["action"] == "SELL"
    assert sig4["trade_type"] == "LONG"


