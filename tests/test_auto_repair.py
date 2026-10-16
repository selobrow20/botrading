import pytest
import time
from unittest.mock import MagicMock, patch
from trading.auto_repair import AutoRepairGuardian


def test_auto_repair_naked_position():
    """Menguji bahwa posisi terbuka tanpa Stop Loss (sl == 0) otomatis dipasangkan SL & TP pengaman."""
    guardian = AutoRepairGuardian()

    # Mock open positions: 1 posisi BUY tanpa SL
    fake_positions = [
        {
            "ticket": 123456,
            "symbol": "XAUUSD",
            "type": "BUY",
            "price_open": 4200.0,
            "price_current": 4202.0,
            "sl": 0.0,  # Naked!
            "tp": 0.0,  # Naked!
        }
    ]

    mock_bridge = MagicMock()
    mock_bridge.enabled = True
    mock_bridge.get_open_positions.return_value = fake_positions
    mock_bridge.modify_position.return_value = {"success": True, "ticket": 123456}

    with patch("trading.mt5_bridge.MT5Bridge", return_value=mock_bridge):
        repairs = guardian.audit_and_repair_positions()

    assert len(repairs) >= 1
    assert "tanpa Stop Loss" in repairs[0]
    assert mock_bridge.modify_position.called
    call_args = mock_bridge.modify_position.call_args[1]
    assert call_args["sl"] == 4194.0  # 4200 - 6.0 USD SL pengaman
    assert call_args["tp"] == 4209.0  # 4200 + 9.0 USD TP pengaman (1:1.5)


def test_auto_repair_hedging_conflict():
    """Menguji bahwa posisi berlawanan arah (BUY dan SELL aktif bersamaan) langsung diselesaikan otomatis."""
    guardian = AutoRepairGuardian()

    fake_positions = [
        {"ticket": 111, "symbol": "XAUUSD", "type": "BUY", "price_open": 4210.0, "sl": 4204.0, "tp": 4220.0},
        {"ticket": 222, "symbol": "XAUUSD", "type": "SELL", "price_open": 4205.0, "sl": 4211.0, "tp": 4195.0},
    ]

    mock_bridge = MagicMock()
    mock_bridge.enabled = True
    mock_bridge.get_open_positions.return_value = fake_positions
    mock_bridge.close_position.return_value = {"success": True, "ticket": 222}

    # Asumsikan tren makro BULLISH -> posisi SELL #222 harus ditutup
    with patch("trading.mt5_bridge.MT5Bridge", return_value=mock_bridge), \
         patch.object(guardian, "_detect_macro_gold_trend", return_value="BULLISH"):
        repairs = guardian.audit_and_repair_positions()

    assert len(repairs) >= 1
    assert "Terdeteksi bentrok posisi" in repairs[0]
    assert mock_bridge.close_position.called
    assert mock_bridge.close_position.call_args[0][0] == 222  # Tiket SELL ditutup


def test_auto_repair_zombie_pending_order():
    """Menguji bahwa pending order yang tertinggal terlalu jauh dari harga pasar langsung dibatalkan otomatis."""
    guardian = AutoRepairGuardian()

    fake_orders = [
        {
            "ticket": 999,
            "symbol": "XAUUSD",
            "type": "BUY_LIMIT",
            "price_open": 4150.0,
            "price_current": 4220.0,  # Selisih $70 USD (700 pips!)
        }
    ]

    mock_bridge = MagicMock()
    mock_bridge.enabled = True
    mock_bridge.get_pending_orders.return_value = fake_orders
    mock_bridge.cancel_pending_order.return_value = {"success": True, "ticket": 999}

    with patch("trading.mt5_bridge.MT5Bridge", return_value=mock_bridge):
        repairs = guardian.audit_and_repair_pending_orders()

    assert len(repairs) >= 1
    assert "Pending order #999" in repairs[0]
    assert mock_bridge.cancel_pending_order.called
    assert mock_bridge.cancel_pending_order.call_args[0][0] == 999


def test_auto_repair_error_storm_healing():
    """Menguji bahwa exception loop (> 3x dalam 60s) memicu self-healing otomatis."""
    guardian = AutoRepairGuardian()
    guardian.error_history.clear()
    initial_healed = guardian.healed_count

    # Catat error 3 kali berturut-turut
    guardian.record_error("test_module", "UnboundLocalError: test_var")
    guardian.record_error("test_module", "UnboundLocalError: test_var")
    healed = guardian.record_error("test_module", "UnboundLocalError: test_var")

    assert healed is True
    assert guardian.healed_count == initial_healed + 1
    assert guardian.is_circuit_broken is True


def test_auto_repair_heartbeat_freeze_detection():
    """Menguji deteksi pipeline freeze saat idle melebihi batas waktu."""
    guardian = AutoRepairGuardian()
    # Set heartbeat 150 detik lalu
    guardian.last_heartbeat = time.time() - 150.0

    is_frozen = guardian.audit_heartbeat(max_idle_sec=90)
    assert is_frozen is True
    assert time.time() - guardian.last_heartbeat < 2.0  # Heartbeat direset
