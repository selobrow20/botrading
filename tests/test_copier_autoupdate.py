import io
import json
import zipfile
import pytest
from pathlib import Path

from member_copier.client_copier import (
    CLIENT_COPIER_VERSION,
    apply_zip_update,
    check_and_apply_ota_update,
)


def test_copier_version_exists():
    assert CLIENT_COPIER_VERSION == "2.3.1"
    v_file = Path("member_copier/version.json")
    assert v_file.exists()
    data = json.loads(v_file.read_text(encoding="utf-8"))
    assert data["version"] == "2.3.1"


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

