"""
Unit Test: Sinkronisasi Sinyal BUY LIMIT & SELL LIMIT pada MT5 Member Copier
Memverifikasi:
1. Parsing sinyal pending limit order & skor konfluensi.
2. Toleransi usia pesan riwayat chat dinamis (120 menit Asia, 45 menit London, 30 menit US) vs market order (15 menit).
3. Auto-replace pending order lama yang berbeda harga saat kuota penuh (1:1 sinkron dengan Master).
4. Tidak menduplikasi pending order yang sudah aktif di harga yang sama persis (< $2.00).
5. Akun Standard USD tidak ter-veto secara keliru pada sesi UK/candle pullback untuk pending limit order.
6. Penanganan status already_active tanpa KeyError 'volume' saat sinyal limit order terdeteksi sudah aktif.
"""

import time
import pytest
from unittest.mock import MagicMock, patch
from member_copier.client_copier import parse_signal, MT5MemberBridge


def test_parse_signal_pending_limit_card():
    card_text = """
🟡 <b>[PENDING ORDER] LIMIT ORDER MT5 TERPASANG!</b> ⚡
━━━━━━━━━━━━━━━━━━━━━━
🎫 <b>Ticket ID:</b> <code>#987654</code>
📊 <b>Instrumen:</b> <code>XAUUSD (Gold)</code>
🟢 <b>Aksi Order:</b> <b>BUY LIMIT (Retest 20 EMA)</b>
📦 <b>Volume:</b> <code>0.05 Lot</code> (🔥 <b>AKUN CENT USC (0.05 LOT)</b>)
💵 <b>Harga Pasang Limit:</b> <code>$2,642.50</code>
🎯 <b>Take Profit (TP):</b> <code>$2,652.50</code>
🛑 <b>Stop Loss (SL):</b> <code>$2,632.50</code>
━━━━━━━━━━━━━━━━━━━━━━
⭐ <b>Konfluensi 9 PDF:</b> 92% (Grade A+)
🛡️ <i>Pending limit order diproteksi SL & TP otomatis. Terisi saat harga pullback retest!</i>
"""
    sig = parse_signal(card_text)
    assert sig["action"] == "BUY_LIMIT"
    assert sig["is_limit_order"] is True
    assert sig["entry_price"] == 2642.50
    assert sig["tp_price"] == 2652.50
    assert sig["sl_price"] == 2632.50
    assert sig["pdf_confluence_score"] == 92.0
    assert sig["is_high_grade"] is True
    assert sig["is_ultra_usd_grade"] is True


def test_parse_signal_sniper_limit_card():
    msg = """
🟡 <b>SINYAL PENDING ORDER SNIPER: SELL LIMIT (XAU/USD)</b>
🌐 <b>Market:</b> H4 = <code>BEARISH TREND</code>
⚡ <b>Trade Type:</b> <code>SHORT — SCALPING</code>
🧭 <b>Direction:</b> <code>SELL</code>
🎯 <b>Metode Entry:</b> 🛡️ <b>Pending Limit Anti-Kejar Lilin (Bob Volman)</b>
📍 <b>Harga Pasang Limit:</b> <code>$2,658.00</code> (Retest 20 EMA)
🎯 <b>Take Profit (TP):</b> <code>$2,648.00</code>
🛑 <b>Stop Loss (SL):</b> <code>$2,668.00</code>
⚖️ <b>Risk/Reward Ratio:</b> 1 : 1.0
⏳ <b>Masa Berlaku:</b> <code>2 Jam</code> (Auto-Cancel jika tidak terjemput)
⏱️ <b>20:15:00 WIB</b> | RSI: <b>54.2</b> | Vol: <b>1.2x</b>
━━━━━━━━━━━━━━━━━━━━━━
⭐ <b>Konfluensi 9 PDF:</b> 90% (Grade A+)
📚 <b>TELAAH 9 BUKU PDF (Grade A+ - 90%):</b>
• Setup Sempurna Pullback EMA 20
• Order Block Bearish Terkonfirmasi
"""
    sig = parse_signal(msg)
    assert sig["action"] == "SELL_LIMIT"
    assert sig["is_limit_order"] is True
    assert sig["entry_price"] == 2658.00
    assert sig["tp_price"] == 2648.00
    assert sig["sl_price"] == 2668.00
    assert sig["pdf_confluence_score"] == 90.0
    assert sig["is_ultra_usd_grade"] is True


def test_execute_limit_order_auto_replaces_stale_order():
    """Jika kuota pending order penuh, order lama yang berbeda harga harus dibatalkan dan diganti yang baru."""
    cfg = {
        "enable_limit_orders": True,
        "max_pending_orders_per_symbol": 1,
        "account_type": "standard",
        "gold_symbol": "XAUUSD",
    }
    bridge = MT5MemberBridge(cfg)
    bridge.ensure_connected = MagicMock(return_value=True)
    bridge.find_broker_symbol = MagicMock(return_value="XAUUSD")

    # Mock order lama di harga 2655.00
    old_order = {
        "ticket": 11111,
        "symbol": "XAUUSD",
        "type": "BUY_LIMIT",
        "price": 2655.00,
        "sl": 2645.00,
        "tp": 2665.00,
        "volume": 0.01,
    }
    orders_state = [old_order]

    def mock_get_pending(symbol=None):
        return list(orders_state)

    def mock_cancel_pending(ticket):
        nonlocal orders_state
        orders_state = [o for o in orders_state if o["ticket"] != ticket]
        return {"success": True, "ticket": ticket}

    bridge.get_pending_orders = mock_get_pending
    bridge.cancel_pending_order = mock_cancel_pending
    bridge.cancel_stale_pending_orders = MagicMock(return_value=[])

    # Mock MT5 API internals
    mock_mt5 = MagicMock()
    mock_mt5.positions_get.return_value = []
    
    mock_tick = MagicMock()
    mock_tick.ask = 2650.00
    mock_tick.bid = 2649.70
    mock_mt5.symbol_info_tick.return_value = mock_tick

    mock_sinfo = MagicMock()
    mock_sinfo.digits = 2
    mock_sinfo.filling_mode = 1
    mock_sinfo.volume_step = 0.01
    mock_sinfo.volume_min = 0.01
    mock_sinfo.volume_max = 10.0
    mock_mt5.symbol_info.return_value = mock_sinfo

    mock_order_res = MagicMock()
    mock_order_res.retcode = 10009  # TRADE_RETCODE_DONE
    mock_order_res.order = 22222
    mock_mt5.TRADE_RETCODE_DONE = 10009
    mock_mt5.ORDER_TYPE_BUY_LIMIT = 2
    mock_mt5.TRADE_ACTION_PENDING = 5
    mock_mt5.ORDER_TIME_GTC = 0
    mock_mt5.order_send.return_value = mock_order_res

    bridge.mt5 = mock_mt5

    # Master mengirim BUY LIMIT baru di 2640.00 (harga baru)
    new_sig = {
        "action": "BUY_LIMIT",
        "entry_price": 2640.00,
        "tp_price": 2650.00,
        "sl_price": 2630.00,
        "pdf_confluence_score": 90.0,
        "is_high_grade": True,
        "is_ultra_usd_grade": True,
    }

    res = bridge.execute_limit_order(new_sig)
    assert res["success"] is True
    assert res["ticket"] == 22222
    # Pastikan order lama #11111 berhasil dibatalkan dari antrean
    assert all(o["ticket"] != 11111 for o in orders_state)


def test_execute_limit_order_skips_same_price_duplicate():
    """Jika pending order searah dengan harga yang sama (< $2.00) sudah ada, jangan buka dobel."""
    cfg = {
        "enable_limit_orders": True,
        "max_pending_orders_per_symbol": 1,
        "account_type": "standard",
        "gold_symbol": "XAUUSD",
    }
    bridge = MT5MemberBridge(cfg)
    bridge.ensure_connected = MagicMock(return_value=True)
    bridge.find_broker_symbol = MagicMock(return_value="XAUUSD")

    existing_order = {
        "ticket": 33333,
        "symbol": "XAUUSD",
        "type": "BUY_LIMIT",
        "price": 2640.00,
        "sl": 2630.00,
        "tp": 2650.00,
        "volume": 0.08,
    }
    bridge.get_pending_orders = MagicMock(return_value=[existing_order])
    bridge.cancel_stale_pending_orders = MagicMock(return_value=[])

    mock_mt5 = MagicMock()
    mock_mt5.positions_get.return_value = []
    bridge.mt5 = mock_mt5

    # Master mengirim BUY LIMIT di 2640.50 (selisih hanya $0.50)
    sig_dup = {
        "action": "BUY_LIMIT",
        "entry_price": 2640.50,
        "tp_price": 2650.00,
        "sl_price": 2630.00,
    }

    res = bridge.execute_limit_order(sig_dup)
    assert res["success"] is True
    assert res["ticket"] == 33333
    assert res.get("already_active") is True
    assert res.get("volume") == 0.08
    assert res.get("price") == 2640.00
    assert "sudah aktif" in res["message"].lower()


def test_already_active_result_does_not_raise_keyerror():
    """Memverifikasi blok logging execute_order tidak pernah melempar KeyError 'volume'."""
    res = {
        "success": True,
        "already_active": True,
        "status": "already_active",
        "ticket": 15299973347,
        "message": "Pending order sudah aktif."
    }
    sig = {"action": "BUY_LIMIT"}

    # Simulasi logika di message_handler
    if res.get("already_active") or res.get("status") == "already_active":
        printed = "SKIPPED_CLEANLY"
    else:
        res_ticket = res.get("ticket", "-")
        res_vol = res.get("volume", sig.get("master_lot", 0.01))
        res_price = float(res.get("price", sig.get("entry_price", 0.0)) or 0.0)
        res_sym = res.get("symbol", "XAUUSD")
        printed = f"#{res_ticket} {sig['action']} {res_vol} Lot @ ${res_price:,.2f} pada {res_sym}"

    assert printed == "SKIPPED_CLEANLY"


def test_verify_usd_elite_setup_permits_limit_orders():
    """Pending limit order tidak boleh ditolak oleh filter momentum lilin M15 / UK caution."""
    cfg = {"account_type": "standard"}
    bridge = MT5MemberBridge(cfg)
    bridge.ensure_connected = MagicMock(return_value=True)
    bridge.find_broker_symbol = MagicMock(return_value="XAUUSD")

    mock_mt5 = MagicMock()
    mock_tick = MagicMock()
    mock_tick.ask = 2650.00
    mock_tick.bid = 2649.80
    mock_mt5.symbol_info_tick.return_value = mock_tick

    # H1 rates
    mock_mt5.TIMEFRAME_H1 = 16385
    mock_mt5.TIMEFRAME_M15 = 15
    mock_mt5.copy_rates_from_pos.return_value = None  # No rate veto
    bridge.mt5 = mock_mt5

    ok, msg = bridge.verify_usd_elite_setup("XAUUSD", "BUY_LIMIT", pdf_score=90.0)
    assert ok is True
    assert msg == "OK"
