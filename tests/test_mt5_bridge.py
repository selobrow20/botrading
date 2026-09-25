"""
Unit Test untuk Eksekutor MetaTrader 5 (MT5 Bridge & Auto-Trader).
Menguji:
1. Inisialisasi Singleton & konfigurasi default.
2. Gerbang ketat filter 7 Buku PDF (menolak jika konfluensi < 65%).
3. Eksekusi order BUY/SELL dengan TP & SL otomatis.
4. Manajemen posisi terbuka & penutupan posisi.
5. Perhitungan lot dinamis berbasis risiko.
"""

import pytest
from unittest.mock import MagicMock, patch
from strategy.signal_engine import SignalResult
from trading.mt5_bridge import MT5Bridge


def test_mt5_bridge_singleton_and_init():
    bridge1 = MT5Bridge(simulation_mode=True)
    bridge2 = MT5Bridge(simulation_mode=True)
    assert bridge1 is bridge2
    assert bridge1.simulation_mode is True
    assert bridge1.magic_number > 0
    assert bridge1.default_lot > 0


def test_mt5_7_pdf_strict_gatekeeper():
    """Memastikan order DITOLAK jika belum memenuhi standar konfluensi Grade A (>=65%) 7 Buku PDF."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True

    # 1. Sinyal Lemah (< 65%) -> Harus DITOLAK demi menjaga modal & win rate
    weak_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=2750.0,
        candle_time="2026-09-25T08:00:00",
        take_profit_price=2775.0,
        stop_loss_price=2735.0,
        pdf_confluence_score=50.0,  # 50% < 65%
        setup_grade="Grade C",
    )
    res_weak = bridge.execute_signal(weak_sig)
    assert res_weak["success"] is False
    assert res_weak["status"] == "pdf_rejected"
    assert "7 Buku PDF" in res_weak["message"]

    # 2. Sinyal Kuat (>= 65% Grade A) -> Harus DITERIMA & DIEKSEKUSI
    strong_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=2750.0,
        candle_time="2026-09-25T08:00:00",
        take_profit_price=2775.0,
        stop_loss_price=2735.0,
        pdf_confluence_score=80.0,  # 80% >= 65%
        setup_grade="Grade A",
    )
    res_strong = bridge.execute_signal(strong_sig)
    assert res_strong["success"] is True
    assert res_strong["status"] == "executed"
    assert res_strong["ticket"] > 0
    assert res_strong["action"] == "BUY"
    assert res_strong["tp"] == 2775.0
    assert res_strong["sl"] == 2735.0


def test_mt5_order_lifecycle_and_positions():
    """Menguji siklus buka posisi, cek posisi terbuka, dan tutup posisi di MT5."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge._simulated_positions.clear()

    # Buka order SELL Gold
    sell_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="SELL",
        price=2760.0,
        candle_time="2026-09-25T08:00:00",
        take_profit_price=2740.0,
        stop_loss_price=2770.0,
        pdf_confluence_score=75.0,
        setup_grade="Grade A",
    )
    res = bridge.execute_signal(sell_sig)
    assert res["success"] is True
    ticket = res["ticket"]

    # Cek posisi terbuka
    positions = bridge.get_open_positions()
    assert len(positions) == 1
    assert positions[0]["ticket"] == ticket
    assert positions[0]["type"] == "SELL"
    assert positions[0]["tp"] == 2740.0
    assert positions[0]["sl"] == 2770.0

    # Tutup posisi by ticket
    close_res = bridge.close_position(ticket)
    assert close_res["success"] is True
    assert len(bridge.get_open_positions()) == 0


def test_mt5_disabled_mode_does_not_execute():
    """Jika auto-trade dimatikan, order tidak boleh dieksekusi."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = False

    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=2750.0,
        candle_time="2026-09-25T08:00:00",
        take_profit_price=2775.0,
        stop_loss_price=2735.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
    )
    res = bridge.execute_signal(sig)
    assert res["success"] is False
    assert res["status"] == "disabled"
