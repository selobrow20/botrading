"""
Unit tests untuk Hard Circuit Breaker / Gatekeeper Pending Limit Orders:
1. Validasi can_place_order() dan place_pending_order().
2. Blokir Grade B & C, Area Bahaya Ekstrem, dan Konfluensi < 80%.
3. Notifikasi Telegram Veto: ⛔ ORDER DIBATALKAN (VETO).
4. Pencegahan spamming order tiket aktif berulang di waktu berdekatan.
"""

import pytest
from unittest.mock import MagicMock, patch
from trading.mt5_bridge import MT5Bridge, can_place_order, send_telegram_alert
from strategy.signal_engine import SignalResult


def test_gatekeeper_rejects_grade_b_and_c():
    """Memastikan Grade B dan Grade C diveto total oleh can_place_order dan place_pending_order."""
    mock_notifier = MagicMock()
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge._simulated_pending_orders.clear()

    # Sinyal Grade B (82% confluence tetap ditolak karena Grade B)
    sig_b = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=4180.0,
        stop_loss_price=4170.0,
        take_profit_price=4200.0,
        setup_grade="Grade B",
        pdf_confluence_score=82.0,
    )

    allowed, reason = can_place_order(sig=sig_b, order_type="BUY_LIMIT", notifier=mock_notifier)
    assert allowed is False
    assert "⛔ ORDER DIBATALKAN (VETO)" in reason
    assert "Grade: Grade B" in reason
    mock_notifier.send_message.assert_called_once()
    assert "⛔ ORDER DIBATALKAN (VETO)" in mock_notifier.send_message.call_args[0][0]

    # Eksekusi via place_pending_order wajib dibatalkan dan tidak menambah order
    mock_notifier.reset_mock()
    with patch("trading.mt5_bridge.send_telegram_alert") as mock_alert:
        res = bridge.place_pending_order(sig=sig_b)
        assert res["success"] is False
        assert len(bridge._simulated_pending_orders) == 0
        mock_alert.assert_called_once()

    # Sinyal Grade C (50% confluence)
    mock_notifier.reset_mock()
    sig_c = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="SELL_LIMIT",
        price=4190.0,
        stop_loss_price=4200.0,
        take_profit_price=4170.0,
        setup_grade="Grade C",
        pdf_confluence_score=50.0,
    )
    allowed_c, reason_c = can_place_order(sig=sig_c, order_type="SELL_LIMIT", notifier=mock_notifier)
    assert allowed_c is False
    assert "Grade: Grade C" in reason_c
    assert "Konfluensi: 50%" in reason_c
    mock_notifier.send_message.assert_called_once()


def test_gatekeeper_rejects_extreme_danger_and_low_confluence():
    """Memastikan Sinyal dengan flag Bahaya Ekstrem atau Konfluensi < 80% diveto."""
    mock_notifier = MagicMock()
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge._simulated_pending_orders.clear()

    # Grade A tapi terindikasi Area Bahaya Ekstrem (misal TRAP_RISK / CHOP)
    sig_danger = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=4180.0,
        stop_loss_price=4170.0,
        take_profit_price=4200.0,
        setup_grade="Grade A",
        pdf_confluence_score=85.0,
        reasons=["Area Bahaya Ekstrem ⚠️", "CHOP / SIDEWAYS BERBAHAYA"],
    )

    allowed, reason = can_place_order(sig=sig_danger, order_type="BUY_LIMIT", notifier=mock_notifier)
    assert allowed is False
    assert "⛔ ORDER DIBATALKAN (VETO)" in reason
    mock_notifier.send_message.assert_called_once()

    # Konfluensi belum matang (50% score) walaupun label Grade A
    mock_notifier.reset_mock()
    sig_immature = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=4180.0,
        stop_loss_price=4170.0,
        take_profit_price=4200.0,
        setup_grade="Grade A",
        pdf_confluence_score=50.0,
        reasons=["Konfluensi Belum Matang"],
    )
    allowed_im, reason_im = can_place_order(sig=sig_immature, order_type="BUY_LIMIT", notifier=mock_notifier)
    assert allowed_im is False
    assert "Konfluensi: 50%" in reason_im
    mock_notifier.send_message.assert_called_once()


def test_gatekeeper_allows_grade_a_high_confluence():
    """Memastikan Sinyal Grade A+ dengan konfluensi >= 80% dan tanpa bahaya ekstrem diizinkan."""
    mock_notifier = MagicMock()
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge._simulated_pending_orders.clear()

    sig_valid = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=4180.0,
        stop_loss_price=4168.0,
        take_profit_price=4204.0,
        setup_grade="Grade A+",
        pdf_confluence_score=85.0,
        reasons=["Valid Rejection Wick 45%", "Discount Area"],
    )

    allowed, msg = can_place_order(sig=sig_valid, order_type="BUY_LIMIT", notifier=mock_notifier)
    assert allowed is True
    mock_notifier.send_message.assert_not_called()

    # Eksekusi via place_pending_order sukses memasang tiket
    res = bridge.place_pending_order(sig=sig_valid, price=4180.0, sl=4168.0, tp=4204.0, volume=0.01)
    assert res["success"] is True
    assert res["action"] == "BUY_LIMIT"
    assert len(bridge._simulated_pending_orders) == 1
    assert bridge._simulated_pending_orders[0]["ticket"] == res["ticket"]


def test_anti_spam_prevents_duplicate_active_pending_orders():
    """
    Pencegahan Spamming Order Berulang:
    Jika sudah ada pending order BUY_LIMIT yang masih antre di MT5,
    dilarang memasang pending order baru untuk instrumen yang sama sampai terisi atau dibatalkan.
    """
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge._simulated_pending_orders.clear()

    sig_1 = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=4180.0,
        stop_loss_price=4168.0,
        take_profit_price=4204.0,
        setup_grade="Grade A+",
        pdf_confluence_score=85.0,
    )
    # Order 1: Pasang pertama kali di level $4180 -> Sukses
    res_1 = bridge.place_pending_order(sig=sig_1, price=4180.0, sl=4168.0, tp=4204.0, volume=0.01)
    assert res_1["success"] is True
    assert len(bridge.get_pending_orders("XAUUSD")) == 1

    # Order 2: Sinyal baru beberapa saat kemudian di level $4189 -> WAJIB DITOLAK
    sig_2 = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=4189.0,
        stop_loss_price=4177.0,
        take_profit_price=4213.0,
        setup_grade="Grade A+",
        pdf_confluence_score=90.0,
    )
    res_2 = bridge.place_pending_order(sig=sig_2, price=4189.0, sl=4177.0, tp=4213.0, volume=0.01)
    assert res_2["success"] is False
    assert "Sudah ada pending order BUY_LIMIT aktif" in res_2["message"]
    # Total tiket di MT5 tetap hanya 1 (tidak ter-spamming)
    assert len(bridge.get_pending_orders("XAUUSD")) == 1

    # Order 3: Sinyal baru lagi di level $4162 -> WAJIB DITOLAK
    sig_3 = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=4162.0,
        stop_loss_price=4150.0,
        take_profit_price=4186.0,
        setup_grade="Grade A+",
        pdf_confluence_score=88.0,
    )
    res_3 = bridge.place_pending_order(sig=sig_3, price=4162.0, sl=4150.0, tp=4186.0, volume=0.01)
    assert res_3["success"] is False
    assert len(bridge.get_pending_orders("XAUUSD")) == 1

    # Setelah order lama dibatalkan / terisi, pending order baru baru boleh dipasang
    bridge.cancel_pending_order(res_1["ticket"])
    assert len(bridge.get_pending_orders("XAUUSD")) == 0

    res_retry = bridge.place_pending_order(sig=sig_3, price=4162.0, sl=4150.0, tp=4186.0, volume=0.01)
    assert res_retry["success"] is True
    assert len(bridge.get_pending_orders("XAUUSD")) == 1


def test_anti_spam_veto_telegram_notification_deduplication():
    """
    Memastikan notifikasi veto tidak membombardir Telegram setiap 30 detik
    pada candle yang sama ketika kondisi Grade B/C menetap.
    """
    from trading.mt5_bridge import clear_veto_alerts_cache
    clear_veto_alerts_cache()

    mock_notifier = MagicMock()
    sig_danger = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=4180.0,
        stop_loss_price=4170.0,
        take_profit_price=4200.0,
        setup_grade="Grade B",
        pdf_confluence_score=75.0,
        candle_time="2026-10-09T17:30:00",
        reasons=["Melawan Break of Structure ⚠️"],
    )

    # Siklus 1 (detik ke-0): pesan pertama terkirim
    allowed1, _ = can_place_order(sig=sig_danger, order_type="BUY_LIMIT", notifier=mock_notifier, symbol="XAUUSD")
    assert allowed1 is False
    assert mock_notifier.send_message.call_count == 1

    # Siklus 2 (detik ke-30 pada candle yang sama): pesan wajib DILEWATI (tidak spam)
    allowed2, _ = can_place_order(sig=sig_danger, order_type="BUY_LIMIT", notifier=mock_notifier, symbol="XAUUSD")
    assert allowed2 is False
    assert mock_notifier.send_message.call_count == 1  # Tetap 1, tidak bertambah!

    # Siklus 3 (detik ke-60 pada candle yang sama): tetap dilewati
    allowed3, _ = can_place_order(sig=sig_danger, order_type="BUY_LIMIT", notifier=mock_notifier, symbol="XAUUSD")
    assert allowed3 is False
    assert mock_notifier.send_message.call_count == 1  # Tetap 1!

    # Siklus 4: Pergantian candle baru (17:45:00)
    sig_new_bar = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=4182.0,
        stop_loss_price=4172.0,
        take_profit_price=4202.0,
        setup_grade="Grade B",
        pdf_confluence_score=75.0,
        candle_time="2026-10-09T17:45:00",
        reasons=["Melawan Break of Structure ⚠️"],
    )
    allowed4, _ = can_place_order(sig=sig_new_bar, order_type="BUY_LIMIT", notifier=mock_notifier, symbol="XAUUSD")
    assert allowed4 is False
    assert mock_notifier.send_message.call_count == 2  # Bertambah tepat 1 kali pada candle baru!

