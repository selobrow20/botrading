import pytest
from trading.mt5_bridge import MT5Bridge
from crypto.auto_pump import AutoPumpSniper
from notify.chat_agent import ChatAgent


def test_mt5_bridge_panic_close_all():
    bridge = MT5Bridge(simulation_mode=True)
    bridge._simulated_positions = [
        {"ticket": 1001, "symbol": "XAUUSD", "type": "BUY", "volume": 0.01, "price_open": 2700.0, "sl": 2694.0, "tp": 2712.0},
        {"ticket": 1002, "symbol": "XAUUSD", "type": "BUY", "volume": 0.01, "price_open": 2702.0, "sl": 2696.0, "tp": 2714.0},
    ]
    res = bridge.close_all_positions(reason="Test Panic Close")
    assert res["success"] is True
    assert res["closed_count"] == 2
    assert len(bridge._simulated_positions) == 0


def test_crypto_auto_pump_panic_close_all():
    from unittest.mock import patch
    sniper = AutoPumpSniper.get_instance()
    with patch.object(sniper, "get_open_positions", return_value=[]), \
         patch.object(sniper.client, "create_order", return_value={"success": True}):
        res = sniper.close_all_positions(reason="Mock Test Panic Close")
        assert res["success"] is True
        assert isinstance(res["closed_count"], int)


def test_chat_agent_panic_intent():
    intent = ChatAgent.classify_intent("bor tutup semua posisi sekarang")
    assert intent["intent"] == "PANIC_CLOSE"

    intent2 = ChatAgent.classify_intent("panic close dong bahaya")
    assert intent2["intent"] == "PANIC_CLOSE"

    resp = ChatAgent.generate_chat_response("PANIC_CLOSE")
    assert "/panic" in resp
    assert "/closeall" in resp
