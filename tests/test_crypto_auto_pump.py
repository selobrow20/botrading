import pytest
from crypto.auto_pump import AutoPumpSniper


def test_auto_pump_initialization():
    sniper = AutoPumpSniper.get_instance()
    assert sniper is not None
    assert sniper.mode in ["paper", "real"]
    assert sniper.max_positions >= 1
    assert sniper.capital_per_coin > 0


def test_auto_pump_mode_switching():
    sniper = AutoPumpSniper.get_instance()
    orig_mode = sniper.mode
    try:
        assert sniper.set_mode("paper") == "paper"
        assert sniper.mode == "paper"
        assert sniper.set_mode("real") == "real"
        assert sniper.mode == "real"
    finally:
        sniper.set_mode(orig_mode)


def test_auto_pump_status_report():
    sniper = AutoPumpSniper.get_instance()
    report = sniper.format_status_report()
    assert "DASHBOARD AUTO-PUMP SNIPER" in report
    assert "Alokasi per Koin" in report
    assert "/autopump on" in report


def test_auto_pump_panic_close_and_circuit_breaker():
    from unittest.mock import patch
    sniper = AutoPumpSniper.get_instance()
    with patch.object(sniper, "get_open_positions", return_value=[]):
        res = sniper.close_all_positions()
        assert res["success"] is True
        assert res["closed_count"] == 0

    # Test circuit breaker check
    tripped, pnl, msg = sniper.check_circuit_breaker()
    assert isinstance(tripped, bool)
    assert isinstance(pnl, float)

    # Test daily pnl summary
    summary = sniper.get_daily_pnl_summary()
    assert "total_trades" in summary
    assert "win_rate" in summary
    assert "net_pnl_usdt" in summary
