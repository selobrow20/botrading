"""
Unit Test untuk Fitur Pending Limit Orders (Buy Limit & Sell Limit).
Menguji:
1. Struktur dataclass SignalResult untuk pending limit order.
2. Eksekusi pending limit order di MT5 Bridge (BUY_LIMIT & SELL_LIMIT).
3. Manajemen pending orders (get, cancel, auto-cancel stale, cancel opposite).
4. Format kartu pesan Telegram untuk pending limit orders.
5. Parser sinyal Telegram di sisi Member Copier (client_copier.py).
"""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock

from strategy.signal_engine import SignalResult
from trading.mt5_bridge import MT5Bridge
from notify.telegram_bot import TelegramNotifier
from member_copier.client_copier import parse_signal, MT5MemberBridge


def test_signal_result_limit_order_fields():
    """Memastikan SignalResult menyimpan dan mengonversi field limit order ke dictionary dengan benar."""
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=2645.50,
        candle_time="2026-10-06T15:00:00",
        take_profit_price=2655.50,
        stop_loss_price=2639.50,
        risk_reward_ratio=1.67,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
        is_limit_order=True,
        limit_order_type="BUY_LIMIT",
        limit_price=2645.50,
        limit_expiry_minutes=120,
    )
    d = sig.to_dict()
    assert d["is_limit_order"] is True
    assert d["limit_order_type"] == "BUY_LIMIT"
    assert d["limit_price"] == 2645.50
    assert d["limit_expiry_minutes"] == 120
    assert d["signal"] == "BUY_LIMIT"


def test_mt5_bridge_execute_limit_order_success():
    """Menguji eksekusi pending limit order di MT5 Bridge dalam mode simulasi."""
    from unittest.mock import patch
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"
    bridge._simulated_pending_orders.clear()

    # 1. Buy Limit Grade A+ (>= 80%) di luar Sesi US -> Lot 0.05
    buy_lim_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=2640.0,
        candle_time="2026-10-06T15:00:00",
        take_profit_price=2650.0,
        stop_loss_price=2634.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
        is_limit_order=True,
        limit_price=2640.0,
    )

    with patch.object(bridge, "is_us_session_window", return_value=False):
        res = bridge.execute_signal(buy_lim_sig)
        assert res["success"] is True
        assert res["status"] == "pending_placed"
        assert res["action"] == "BUY_LIMIT"
        assert res["price"] == 2640.0
        assert res["volume"] == 0.05
        assert len(bridge.get_pending_orders()) == 1

    # 2. Sell Limit Grade A+ (>= 80%) di dalam Sesi US -> Lot 0.08
    sell_lim_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="SELL_LIMIT",
        price=2660.0,
        candle_time="2026-10-06T15:00:00",
        take_profit_price=2650.0,
        stop_loss_price=2666.0,
        pdf_confluence_score=88.0,
        setup_grade="Grade A+",
        is_limit_order=True,
        limit_price=2660.0,
    )

    with patch.object(bridge, "is_us_session_window", return_value=True):
        res_sell = bridge.execute_limit_order(sell_lim_sig)
        assert res_sell["success"] is True
        assert res_sell["action"] == "SELL_LIMIT"
        assert res_sell["price"] == 2660.0
        assert res_sell["volume"] == 0.08


def test_mt5_bridge_reject_low_grade_limit():
    """Memastikan Pending Limit Order DITOLAK jika belum memenuhi standar Grade A+ (>= 80%)."""
    from unittest.mock import patch
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"
    bridge._simulated_pending_orders.clear()

    low_score_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=2640.0,
        candle_time="2026-10-06T15:00:00",
        take_profit_price=2650.0,
        stop_loss_price=2634.0,
        pdf_confluence_score=70.0,  # 70% < 80% Grade A+
        setup_grade="Grade A",
        is_limit_order=True,
    )
    with patch.dict(bridge.config["mt5"], {"always_use_limit_orders": False}):
        res = bridge.execute_limit_order(low_score_sig)
        assert res["success"] is False
        assert res["status"] == "skip_standard_grade"


def test_mt5_bridge_pending_orders_lifecycle():
    """Menguji pembatalan pending order, pembatalan order basi (stale), dan pembatalan order berlawanan arah."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge._simulated_pending_orders.clear()

    # Tambahkan order aktif sekarang
    now_dt = datetime.now(ZoneInfo("Asia/Jakarta"))
    bridge._simulated_pending_orders.append({
        "ticket": 1001,
        "symbol": "XAUUSD",
        "type": "BUY_LIMIT",
        "price": 2640.0,
        "time_setup": now_dt,
    })

    # Tambahkan order basi (dibuat 150 menit lalu > batas 120 menit)
    stale_dt = now_dt - timedelta(minutes=150)
    bridge._simulated_pending_orders.append({
        "ticket": 1002,
        "symbol": "XAUUSD",
        "type": "BUY_LIMIT",
        "price": 2635.0,
        "time_setup": stale_dt,
    })

    assert len(bridge.get_pending_orders()) == 2

    # Jalankan cancel stale pending orders (120 menit)
    cancelled_stale = bridge.cancel_stale_pending_orders(max_age_minutes=120)
    assert 1002 in cancelled_stale
    assert len(bridge.get_pending_orders()) == 1
    assert bridge.get_pending_orders()[0]["ticket"] == 1001

    # Tambahkan SELL_LIMIT
    bridge._simulated_pending_orders.append({
        "ticket": 1003,
        "symbol": "XAUUSD",
        "type": "SELL_LIMIT",
        "price": 2665.0,
        "time_setup": now_dt,
    })
    assert len(bridge.get_pending_orders()) == 2

    # Ketika ada sinyal/arah BUY baru dan dual-sided nonaktif, pending SELL_LIMIT lawan harus dibatalkan
    bridge.enable_dual_sided_limits = False
    cancelled_opp = bridge.cancel_opposite_pending_orders("XAUUSD", "BUY")
    assert 1003 in cancelled_opp
    assert len(bridge.get_pending_orders()) == 1
    assert bridge.get_pending_orders()[0]["ticket"] == 1001

    # Batalkan order secara manual
    cancel_res = bridge.cancel_pending_order(1001)
    assert cancel_res["success"] is True
    assert len(bridge.get_pending_orders()) == 0


def test_telegram_formatting_limit_order():
    """Menguji tampilan kartu notifikasi sinyal dan laporan eksekusi Telegram untuk BUY_LIMIT & SELL_LIMIT."""
    notifier = TelegramNotifier()

    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY_LIMIT",
        price=2642.50,
        candle_time="2026-10-06T15:00:00",
        take_profit_price=2652.50,
        stop_loss_price=2636.50,
        risk_reward_ratio=1.67,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
        is_limit_order=True,
    )

    msg = notifier.format_signal_message(sig)
    assert "SINYAL PENDING ORDER SNIPER: BUY LIMIT" in msg
    assert "Pending Limit Anti-Kejar Lilin (Bob Volman)" in msg
    assert "Harga Pasang Limit" in msg
    assert "2642.50" in msg or "2,642.50" in msg
    assert "Masa Berlaku" in msg

    # Format laporan eksekusi MT5
    report = notifier.format_mt5_execution_report({
        "ticket": 998877,
        "action": "BUY_LIMIT",
        "symbol": "XAUUSDc",
        "volume": 0.05,
        "price": 2642.50,
        "tp": 2652.50,
        "sl": 2636.50,
        "score": 85.0,
        "grade": "Grade A+",
    })
    assert "[PENDING ORDER] LIMIT ORDER MT5 TERPASANG!" in report
    assert "BUY LIMIT (Retest 20 EMA)" in report
    assert "#998877" in report
    assert "Harga Pasang Limit" in report


def test_member_copier_parse_pending_signal():
    """Menguji kemampuan parser client_copier mengekstrak sinyal pending order dari pesan Telegram."""
    msg_text = """
🟡 <b>SINYAL PENDING ORDER SNIPER: BUY LIMIT (XAU/USD (Gold))</b>
🎯 <b>Metode Entry:</b> 🛡️ <b>Pending Limit Anti-Kejar Lilin (Bob Volman)</b>
📍 <b>Harga Pasang Limit:</b> <code>$2,645.20</code> (Retest 20 EMA)
🎯 <b>Take Profit (TP):</b> <code>$2,655.20</code>
🛑 <b>Stop Loss (SL):</b> <code>$2,639.20</code>
⚖️ <b>Risk/Reward Ratio:</b> 1 : 1.67
⏳ <b>Masa Berlaku:</b> <code>2 Jam</code> (Auto-Cancel jika tidak terjemput)
⏱️ <b>15:30 WIB</b> | RSI: <b>52.4</b> | Vol: <b>1.8x</b>
━━━━━━━━━━━━━━━━━━━━━━
📚 <b>TELAAH 9 BUKU PDF (Grade A+ - 85%):</b>
• 20 EMA Pullback Confluence
    """

    parsed = parse_signal(msg_text)
    assert parsed["action"] == "BUY_LIMIT"
    assert parsed["is_limit_order"] is True
    assert parsed["is_high_grade"] is True
    assert parsed["entry_price"] == 2645.20
    assert parsed["tp_price"] == 2655.20
    assert parsed["sl_price"] == 2639.20


def test_member_copier_bridge_pending_execution():
    """Menguji jembatan MT5MemberBridge untuk eksekusi limit order dengan mock mt5."""
    cfg = {
        "enable_limit_orders": True,
        "limit_order_expiry_mins": 120,
        "account_type": "usc",
        "default_lot": 0.05,
        "gold_symbol": "XAUUSD",
    }
    bridge = MT5MemberBridge(cfg)

    # Mock mt5 module
    mock_mt5 = MagicMock()
    mock_mt5.ORDER_TYPE_BUY_LIMIT = 2
    mock_mt5.ORDER_TYPE_SELL_LIMIT = 3
    mock_mt5.TRADE_ACTION_PENDING = 5
    mock_mt5.TRADE_ACTION_REMOVE = 8
    mock_mt5.TRADE_RETCODE_DONE = 10009
    mock_mt5.ORDER_TIME_GTC = 0
    mock_mt5.ORDER_FILLING_FOK = 0

    s_info = MagicMock()
    s_info.digits = 2
    s_info.volume_step = 0.01
    s_info.volume_min = 0.01
    s_info.volume_max = 100.0
    s_info.filling_mode = 1
    mock_mt5.symbol_info.return_value = s_info

    tick = MagicMock()
    tick.ask = 2650.0  # Ask live > limit_price 2642.0 (Valid BUY_LIMIT)
    tick.bid = 2649.5
    mock_mt5.symbol_info_tick.return_value = tick

    mock_res = MagicMock()
    mock_res.retcode = 10009
    mock_res.order = 554433
    mock_mt5.order_send.return_value = mock_res
    mock_mt5.orders_get.return_value = []

    bridge.mt5 = mock_mt5
    bridge.ensure_connected = MagicMock(return_value=True)

    sig = {
        "action": "BUY_LIMIT",
        "symbol": "XAUUSD",
        "entry_price": 2642.0,
        "tp_price": 2652.0,
        "sl_price": 2636.0,
        "is_limit_order": True,
        "is_high_grade": True,
    }

    res = bridge.execute_order(sig)
    assert res["success"] is True
    assert res["ticket"] == 554433
    assert res["action"] == "BUY_LIMIT"
    assert res["price"] == 2642.0


def test_multi_level_signal_result_ladder_orders():
    """Menguji field ladder_limit_orders pada SignalResult dan serialisasinya."""
    ladder = [
        {"level": 1, "label": "Level 1 (Entry Cepat - 20 EMA)", "price": 4127.11, "tp": 4091.11, "sl": 4139.11, "lot": 0.05},
        {"level": 2, "label": "Level 2 (Deep Retest - 50 EMA)", "price": 4137.84, "tp": 4101.84, "sl": 4149.84, "lot": 0.05},
    ]
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="SELL_LIMIT",
        price=4127.11,
        candle_time="2026-10-07T16:00:00",
        take_profit_price=4091.11,
        stop_loss_price=4139.11,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
        is_limit_order=True,
        ladder_limit_orders=ladder,
    )
    d = sig.to_dict()
    assert len(d["ladder_limit_orders"]) == 2
    assert d["ladder_limit_orders"][0]["price"] == 4127.11
    assert d["ladder_limit_orders"][1]["price"] == 4137.84


def test_mt5_bridge_execute_multi_level_limits():
    """Menguji eksekusi bertingkat (Dual-Level Sniper) pada MT5Bridge dalam mode simulasi."""
    from unittest.mock import patch
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"
    bridge._simulated_pending_orders.clear()

    ladder = [
        {"level": 1, "label": "Level 1 (20 EMA)", "price": 4127.11, "tp": 4091.11, "sl": 4139.11, "lot": 0.05},
        {"level": 2, "label": "Level 2 (50 EMA)", "price": 4137.84, "tp": 4101.84, "sl": 4149.84, "lot": 0.05},
    ]
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="SELL_LIMIT",
        price=4127.11,
        candle_time="2026-10-07T16:00:00",
        take_profit_price=4091.11,
        stop_loss_price=4139.11,
        pdf_confluence_score=88.0,
        setup_grade="Grade A+",
        is_limit_order=True,
        ladder_limit_orders=ladder,
    )

    with patch.dict(bridge.config["mt5"], {
        "enable_multi_level_limits": True,
        "max_limit_levels": 2,
        "max_pending_orders_per_symbol": 2,
    }):
        res = bridge.execute_limit_order(sig)
        assert res["success"] is True
        assert res["status"] == "pending_placed"
        assert len(res["tickets"]) == 2
        orders = bridge.get_pending_orders("XAUUSD")
        assert len(orders) == 2
        prices = [o["price"] for o in orders]
        assert 4127.11 in prices
        assert 4137.84 in prices


def test_format_signal_message_dual_level():
    """Menguji format kartu Telegram untuk Dual-Level Limit Order."""
    from unittest.mock import MagicMock
    storage_mock = MagicMock()
    storage_mock.get_win_rate_stats.return_value = {}
    notifier = TelegramNotifier(storage=storage_mock)

    ladder = [
        {"level": 1, "label": "Level 1 (Entry Cepat - 20 EMA)", "price": 4127.11, "tp": 4091.11, "sl": 4139.11, "lot": 0.05},
        {"level": 2, "label": "Level 2 (Deep Retest - 50 EMA)", "price": 4137.84, "tp": 4101.84, "sl": 4149.84, "lot": 0.05},
    ]
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="SELL_LIMIT",
        price=4127.11,
        candle_time="2026-10-07T16:00:00",
        take_profit_price=4091.11,
        stop_loss_price=4139.11,
        pdf_confluence_score=88.0,
        setup_grade="Grade A+",
        is_limit_order=True,
        ladder_limit_orders=ladder,
    )

    msg = notifier.format_signal_message(sig)
    assert "DUAL-LEVEL" in msg
    assert "Level 1 (Entry Cepat - 20 EMA)" in msg
    assert "4,127.11" in msg
    assert "Level 2 (Deep Retest - 50 EMA)" in msg
    assert "4,137.84" in msg


def test_member_copier_parse_dual_level_and_execute():
    """Menguji parsing dan eksekusi pesan Telegram Dual-Level di sisi Member Copier."""
    msg = """
🟡 SINYAL PENDING ORDER SNIPER (DUAL-LEVEL): SELL LIMIT (XAU/USD (Gold))
🌐 Market: H4 = BEARISH
⚡ Trade Type: SHORT — SCALPING
🧭 Direction: SELL
🎯 Metode Entry: 🛡️ Dual-Level Ladder Sniper (Bob Volman & Martin Pring)

📍 Level 1 (Entry Cepat - 20 EMA):
   • Limit : $4,127.11
   • TP    : $4,091.11
   • SL    : $4,139.11
📍 Level 2 (Deep Retest - 50 EMA):
   • Limit : $4,137.84
   • TP    : $4,101.84
   • SL    : $4,149.84
⏳ Masa Berlaku: 2 Jam (Auto-Cancel jika tidak terjemput)
    """

    parsed = parse_signal(msg)
    assert parsed["action"] == "SELL_LIMIT"
    assert parsed["is_limit_order"] is True
    assert len(parsed["ladder_limit_orders"]) == 2
    assert parsed["ladder_limit_orders"][0]["price"] == 4127.11
    assert parsed["ladder_limit_orders"][1]["price"] == 4137.84

    # Uji eksekusi MT5MemberBridge
    cfg = {
        "enable_limit_orders": True,
        "enable_multi_level_limits": True,
        "max_limit_levels": 2,
        "max_pending_orders_per_symbol": 2,
        "limit_order_expiry_mins": 120,
        "account_type": "usc",
        "default_lot": 0.05,
        "gold_symbol": "XAUUSD",
    }
    bridge = MT5MemberBridge(cfg)
    mock_mt5 = MagicMock()
    mock_mt5.ORDER_TYPE_SELL_LIMIT = 3
    mock_mt5.TRADE_ACTION_PENDING = 5
    mock_mt5.TRADE_RETCODE_DONE = 10009
    mock_mt5.ORDER_TIME_GTC = 0
    mock_mt5.ORDER_FILLING_FOK = 0

    s_info = MagicMock()
    s_info.digits = 2
    s_info.volume_step = 0.01
    s_info.volume_min = 0.01
    s_info.volume_max = 100.0
    s_info.filling_mode = 1
    mock_mt5.symbol_info.return_value = s_info

    tick = MagicMock()
    tick.bid = 4115.0  # Bid live < limit price (Valid SELL_LIMIT)
    tick.ask = 4115.5
    mock_mt5.symbol_info_tick.return_value = tick

    mock_res = MagicMock()
    mock_res.retcode = 10009
    mock_res.order = 778899
    mock_mt5.order_send.return_value = mock_res
    mock_mt5.orders_get.return_value = []

    bridge.mt5 = mock_mt5
    bridge.ensure_connected = MagicMock(return_value=True)

    res = bridge.execute_order(parsed)
    assert res["success"] is True
    assert len(res["tickets"]) == 2
    assert mock_mt5.order_send.call_count == 2


def test_dual_sided_bracket_limits_execution():
    """Menguji eksekusi Dual-Sided Bracket Limits (BUY LIMIT dan SELL LIMIT bersamaan) di MT5Bridge."""
    from unittest.mock import patch
    bridge = MT5Bridge(simulation_mode=True)
    bridge.enabled = True
    bridge.trading_hours = "all"
    bridge._simulated_pending_orders.clear()

    ladder = [
        {"level": 1, "label": "Atap Resisten 1 (20 EMA)", "signal": "SELL_LIMIT", "price": 4115.00, "tp": 4085.00, "sl": 4127.00, "lot": 0.05},
        {"level": 2, "label": "Atap Resisten 2 (50 EMA)", "signal": "SELL_LIMIT", "price": 4129.00, "tp": 4099.00, "sl": 4141.00, "lot": 0.05},
        {"level": 3, "label": "Lantai Support 1 (Demand)", "signal": "BUY_LIMIT", "price": 4070.00, "tp": 4090.00, "sl": 4062.00, "lot": 0.05},
        {"level": 4, "label": "Lantai Support 2 (Deep S2)", "signal": "BUY_LIMIT", "price": 4060.00, "tp": 4080.00, "sl": 4052.00, "lot": 0.05},
    ]
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="SELL_LIMIT",
        price=4115.00,
        candle_time="2026-10-07T18:00:00",
        take_profit_price=4085.00,
        stop_loss_price=4127.00,
        pdf_confluence_score=90.0,
        setup_grade="Grade A+",
        is_limit_order=True,
        ladder_limit_orders=ladder,
    )

    with patch.dict(bridge.config["mt5"], {
        "enable_multi_level_limits": True,
        "enable_dual_sided_limits": True,
        "max_limit_levels": 2,
        "max_pending_orders_per_symbol": 4,
    }):
        res = bridge.execute_limit_order(sig)
        assert res["success"] is True
        assert len(res["tickets"]) == 4
        orders = bridge.get_pending_orders("XAUUSD")
        assert len(orders) == 4
        order_types = [o["type"] for o in orders]
        assert order_types.count("SELL_LIMIT") == 2
        assert order_types.count("BUY_LIMIT") == 2
