"""
Bot Eksekusi Otomatis Binance Futures
-------------------------------------
Script ini membaca sinyal trading valid (Entry, SL, TP, Score) dari Signal API teman (Hermes Scanner)
secara real-time, lalu mengeksekusi order secara otomatis ke akun Binance Futures (USDT-M) Anda.

Fitur:
- Membaca BINANCE_API_KEY & BINANCE_API_SECRET langsung dari .env
- Auto DNS Bypass (CloudFront) agar koneksi Binance di Indonesia tidak terblokir ISP/Kominfo
- Cek izin API Restrictions (Memeriksa apakah 'Enable Futures' sudah aktif)
- Mode Real Trading (Live Binance Futures)
- Position Sizing & Margin Management otomatis (Sesuai saldo kas USDT Anda)
- Eksekusi Market / Limit + Auto Stop Loss + Take Profit
"""

from __future__ import annotations

import os
import sys
import time
import hmac
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import requests
from dotenv import load_dotenv

# Load file .env di direktori bot
load_dotenv()

# Konfigurasi UTF-8 console output untuk Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

# ==============================================================================
# 1. BYPASS DNS ISP INDONESIA UNTUK BINANCE (CLOUDFRONT CONNECTION)
# ==============================================================================
_BINANCE_DNS_RESOLVED = False
_BINANCE_CLOUDFRONT_IP = "99.86.16.124"

def setup_binance_dns_bypass():
    """Bypass pemblokiran DNS ISP Indonesia pada domain Binance via CloudFront."""
    global _BINANCE_DNS_RESOLVED, _BINANCE_CLOUDFRONT_IP
    if _BINANCE_DNS_RESOLVED:
        return
    try:
        r = requests.get(
            "https://cloudflare-dns.com/dns-query?name=fapi.binance.com&type=A",
            headers={"accept": "application/dns-json"},
            timeout=3,
        )
        if r.status_code == 200:
            for ans in r.json().get("Answer", []):
                if ans.get("type") == 1:
                    _BINANCE_CLOUDFRONT_IP = ans.get("data")
                    break
    except Exception:
        pass

    try:
        from urllib3.util import connection
        orig_create_connection = connection.create_connection

        def patched_create_connection(address, *args, **kwargs):
            host, port = address
            if isinstance(host, str) and "binance.com" in host:
                return orig_create_connection((_BINANCE_CLOUDFRONT_IP, port), *args, **kwargs)
            return orig_create_connection(address, *args, **kwargs)

        connection.create_connection = patched_create_connection
        _BINANCE_DNS_RESOLVED = True
    except Exception as e:
        print(f"[!] Warning DNS bypass: {e}")

setup_binance_dns_bypass()

# ==============================================================================
# 2. KONFIGURASI API KEY & CREDENTIALS DARI .ENV
# ==============================================================================
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY") or os.getenv("CRYPTO_API_KEY") or ""
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET") or os.getenv("CRYPTO_SECRET_KEY") or ""
IS_TESTNET = os.getenv("FUTURES_TESTNET", "false").lower() in ("true", "1")  # False = Real Live Binance

# Endpoint Signal Provider Teman (Railway)
HERMES_SIGNAL_API_URL = os.getenv("HERMES_SIGNAL_API_URL", "https://signal-api-future-production.up.railway.app")
HERMES_API_KEY = os.getenv("HERMES_SIGNAL_API_KEY", "")

# ==============================================================================
# 3. MANAJEMEN RISIKO & UKURAN POSISI FUTURES (ATURAN MODAL $8.50 USDT)
# ==============================================================================
MIN_SCORE_THRESHOLD = 75.0        # Hanya eksekusi sinyal dengan skor minimal 75/100
MAX_INITIAL_MARGIN_USDT = 0.55    # Initial margin per coin TIDAK BOLEH LEBIH dari $0.55 USDT (55 cent)
MAX_CONCURRENT_TRADES = 3         # Maksimal 3 sinyal/posisi aktif bersamaan
TARGET_LEVERAGE = 50              # Coba gunakan leverage tertinggi jika diizinkan
FALLBACK_LEVERAGE = 20            # Jika akun membatasi (aturan 30 hari pertama Binance), pakai 20x
LIMIT_ORDER_TIMEOUT_SECONDS = 3600 # 1 Jam (3600 detik): Batalkan otomatis jika order limit tidak terjemput
POLL_INTERVAL_SECONDS = 15        # Cek sinyal tiap 15 detik (Hemat kuota rate limit Binance)

executed_signals: Set[str] = set()

_BINANCE_BAN_UNTIL = 0.0
_CACHED_BALANCE: Dict[str, float] = {"free": 0.0, "total": 0.0, "used": 0.0}
_LAST_LIVE_STATE: Dict[str, Any] = {
    "open_orders": [],
    "entry_orders": [],
    "active_positions": [],
    "active_count": 0,
    "active_symbols": set(),
}


def check_api_key_restrictions() -> Dict[str, Any]:
    """Memeriksa izin API Key di Binance (apakah Enable Futures sudah aktif)."""
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        return {"ok": False, "error": "API Key atau Secret Key kosong di .env"}

    ts = int(time.time() * 1000)
    query = f"timestamp={ts}&recvWindow=10000"
    sig = hmac.new(BINANCE_API_SECRET.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"https://api.binance.com/sapi/v1/account/apiRestrictions?{query}&signature={sig}"
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}

    try:
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code == 200:
            return {"ok": True, "restrictions": r.json()}
        else:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_futures_balance(exchange) -> Dict[str, Any]:
    """Mengambil saldo dompet Futures USDT-M langsung dari fapi Binance."""
    global _BINANCE_BAN_UNTIL, _CACHED_BALANCE
    if time.time() < _BINANCE_BAN_UNTIL:
        return dict(_CACHED_BALANCE)
    try:
        acc = exchange.fapiPrivateV2GetAccount()
        free = float(acc.get("availableBalance") or 0.0)
        total = float(acc.get("totalWalletBalance") or 0.0)
        used = float(acc.get("totalInitialMargin") or 0.0)
        _CACHED_BALANCE = {"free": free, "total": total, "used": used}
        return dict(_CACHED_BALANCE)
    except Exception as e:
        ex_str = repr(e)
        if "banned until" in ex_str or "418" in ex_str:
            import re
            m = re.search(r"banned until (\d+)", ex_str)
            if m:
                _BINANCE_BAN_UNTIL = int(m.group(1)) / 1000.0
            else:
                _BINANCE_BAN_UNTIL = time.time() + 600.0
            return dict(_CACHED_BALANCE)
        if "-2015" in ex_str or "Invalid API-key" in ex_str or "AuthenticationError" in ex_str:
            return {"free": 0.0, "total": 0.0, "used": 0.0, "error": f"API_ERROR_2015: {ex_str}"}
        return {"free": 0.0, "total": 0.0, "used": 0.0, "error": ex_str}


def set_symbol_leverage_safely(exchange, market_symbol: str, target_leverage: int = TARGET_LEVERAGE, fallback_leverage: int = FALLBACK_LEVERAGE) -> int:
    """
    Mencoba memasang leverage tertinggi.
    Jika akun Binance membatasi maksimal 20x (misal akun baru < 30 hari),
    otomatis fallback ke 20x atau leverage tertinggi yang didukung simbol.
    """
    for lev in [target_leverage, 25, fallback_leverage, 15, 10]:
        try:
            res = exchange.set_leverage(lev, market_symbol)
            return int(res.get("leverage") or lev)
        except Exception:
            continue
    return fallback_leverage


def get_live_futures_state(exchange, active_signal_symbols: Optional[Set[str]] = None) -> Dict[str, Any]:
    """
    Mengambil status live open orders dan active positions langsung dari fapi Binance.
    Menjalankan SINKRONISASI OTOMATIS:
    1. Membatalkan limit order jika tidak terjemput > 1 jam (3600 detik).
    2. Membatalkan limit order jika sinyal sudah dicabut Master (> 15 menit).
    3. Menyapu bersih order sisa (orphan SL/TP) untuk posisi yang sudah closed.
    4. Menjamin batas maksimal 3 trade aktif.
    """
    global _LAST_LIVE_STATE, _BINANCE_BAN_UNTIL
    if time.time() < _BINANCE_BAN_UNTIL:
        return dict(_LAST_LIVE_STATE)
    try:
        open_orders = exchange.fapiPrivateGetOpenOrders()
        positions = exchange.fapiPrivateV2GetPositionRisk()
        active_positions = [
            p for p in positions
            if abs(float(p.get("positionAmt", 0.0))) > 0.0
        ]
        active_pos_symbols = {p["symbol"].upper() for p in active_positions}

        now_ms = time.time() * 1000

        # Group open orders by symbol
        orders_by_sym: Dict[str, List[Dict[str, Any]]] = {}
        for o in open_orders:
            sym = o.get("symbol", "").upper()
            if sym:
                orders_by_sym.setdefault(sym, []).append(o)

        symbols_to_prune: List[Tuple[str, str]] = []

        for sym, sym_orders in orders_by_sym.items():
            # JIKA POSISI SEDANG AKTIF (Floating): JANGAN GANGGU SL & TP!
            if sym in active_pos_symbols:
                continue

            # Posisi koin ini FLAT (0.0 kontrak). Periksa limit order entry
            limit_entries = [
                o for o in sym_orders
                if not o.get("reduceOnly", False)
            ]

            if limit_entries:
                oldest_order = min(limit_entries, key=lambda x: x.get("time") or x.get("updateTime") or now_ms)
                order_time = oldest_order.get("time") or oldest_order.get("updateTime") or now_ms
                age_sec = (now_ms - order_time) / 1000.0

                if age_sec >= LIMIT_ORDER_TIMEOUT_SECONDS:
                    symbols_to_prune.append((sym, f"Timeout > 1 Jam ({age_sec / 60:.0f} menit) tidak terjemput"))
                elif active_signal_symbols and (sym not in active_signal_symbols) and (age_sec > 900):
                    symbols_to_prune.append((sym, "Sinyal sudah dicabut/kadaluarsa dari Master Scanner (> 15m)"))
            else:
                # Tidak ada entry, tetapi ada residual order (SL/TP) untuk posisi flat
                symbols_to_prune.append((sym, "Residual order sisa (SL/TP) karena posisi sudah selesai/closed"))

        # Eksekusi pembatalan untuk simbol yang kena prune
        if symbols_to_prune:
            for prune_sym, prune_reason in symbols_to_prune:
                print(f"⏱️ [AUTO-SYNC CANCEL] Membatalkan order {prune_sym}: {prune_reason}. Slot dibebaskan!")
                try:
                    exchange.fapiPrivateDeleteAllOpenOrders({"symbol": prune_sym})
                except Exception:
                    try:
                        exchange.cancel_all_orders(prune_sym)
                    except Exception:
                        pass
                try:
                    exchange.fapiPrivateDeleteAlgoOpenOrders({"symbol": prune_sym})
                except Exception:
                    pass
                executed_signals.discard(prune_sym)
                # Hapus dari daftar lokal open_orders
                open_orders = [o for o in open_orders if o.get("symbol", "").upper() != prune_sym]

        entry_orders = [
            o for o in open_orders
            if not o.get("reduceOnly", False)
        ]
        active_symbols = {o["symbol"].upper() for o in entry_orders}.union(active_pos_symbols)

        _LAST_LIVE_STATE = {
            "open_orders": open_orders,
            "entry_orders": entry_orders,
            "active_positions": active_positions,
            "active_count": len(entry_orders) + len(active_positions),
            "active_symbols": active_symbols
        }
        return _LAST_LIVE_STATE
    except Exception as e:
        ex_str = str(e)
        if "banned until" in ex_str or "418" in ex_str:
            import re
            m = re.search(r"banned until (\d+)", ex_str)
            if m:
                _BINANCE_BAN_UNTIL = int(m.group(1)) / 1000.0
            else:
                _BINANCE_BAN_UNTIL = time.time() + 600.0
        # Fail-closed: gunakan status terakhir yang diketahui atau anggap kuota penuh demi keamanan dana
        safe_count = max(_LAST_LIVE_STATE.get("active_count", MAX_CONCURRENT_TRADES), MAX_CONCURRENT_TRADES)
        fallback = dict(_LAST_LIVE_STATE)
        fallback["active_count"] = safe_count
        return fallback


def get_active_signals_from_provider() -> Tuple[list, Set[str]]:
    """Mengambil daftar sinyal aktif dan daftar active_symbols dari server Hermes Scanner teman."""
    endpoint = f"{HERMES_SIGNAL_API_URL.rstrip('/')}/api/v1/signals"
    params = {
        "min_score": MIN_SCORE_THRESHOLD,
        "status": "ACTIONABLE",
        "limit": 10,
    }
    headers = {}
    if HERMES_API_KEY:
        headers["X-API-Key"] = HERMES_API_KEY

    try:
        response = requests.get(endpoint, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            sigs = data.get("signals", [])
            act_syms = set(data.get("active_symbols", [s["symbol"].upper() for s in sigs]))
            return sigs, act_syms
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Gagal fetch sinyal: HTTP {response.status_code}")
    except Exception as exc:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error koneksi sinyal: {exc}")
    return [], set()


def execute_trade_on_binance(signal: Dict[str, Any], exchange) -> bool:
    """
    Eksekusi order ke Binance Futures menggunakan CCXT.
    Memasang Order Market/Limit, Stop Loss, dan Take Profit.
    """
    symbol = signal["symbol"]          # Contoh: 'IOTXUSDT'
    action = signal["action"]          # 'BUY' atau 'SELL'
    side = signal["side"]              # 'LONG' atau 'SHORT'
    order_type_rec = signal.get("order_type", "MARKET").upper()
    entry_price = float(signal["entry_price"])
    stop_loss = float(signal["stop_loss"])
    take_profit = float(signal["take_profit"])
    score = float(signal.get("score", 0.0))

    # Format symbol CCXT untuk Binance Futures: 'IOTX/USDT:USDT'
    base_coin = symbol.replace("USDT", "")
    market_symbol = f"{base_coin}/USDT:USDT"

    try:
        market = exchange.market(market_symbol)
    except Exception:
        market_symbol = f"{base_coin}/USDT"
        try:
            market = exchange.market(market_symbol)
        except Exception:
            market_symbol = symbol
            market = exchange.markets.get(symbol, {})

    # 1. Atur Leverage & Margin Mode (CROSSED Margin)
    actual_leverage = set_symbol_leverage_safely(exchange, market_symbol, TARGET_LEVERAGE, FALLBACK_LEVERAGE)
    try:
        exchange.set_margin_mode("CROSSED", market_symbol)
    except Exception:
        pass

    # 2. Hitung ukuran posisi agar Initial Margin TIDAK BOLEH LEBIH dari $0.55 USDT
    # Target notional dihitung dari modal margin maksimal $0.55 dikali leverage
    target_notional = MAX_INITIAL_MARGIN_USDT * actual_leverage
    target_qty = target_notional / entry_price

    # Format presisi amount & price sesuai aturan Binance
    try:
        formatted_qty = float(exchange.amount_to_precision(market_symbol, target_qty))
    except Exception:
        formatted_qty = round(target_qty, 4)

    try:
        formatted_price = float(exchange.price_to_precision(market_symbol, entry_price))
        formatted_sl = float(exchange.price_to_precision(market_symbol, stop_loss))
        formatted_tp = float(exchange.price_to_precision(market_symbol, take_profit))
    except Exception:
        formatted_price = entry_price
        formatted_sl = stop_loss
        formatted_tp = take_profit

    notional_value = formatted_qty * formatted_price
    actual_margin = notional_value / actual_leverage

    # Step-down kuantitas jika pembulatan presisi membuat margin sedikit melebihi $0.55 USDT
    try:
        market_info = exchange.market(market_symbol)
        amount_precision = market_info.get("precision", {}).get("amount")
        step_size = float(market_info.get("limits", {}).get("amount", {}).get("min") or 0.0)
        if amount_precision is not None and not step_size:
            step_size = 10 ** (-amount_precision)
    except Exception:
        step_size = 0.001

    attempts = 0
    while actual_margin > MAX_INITIAL_MARGIN_USDT and attempts < 15 and step_size:
        formatted_qty = float(exchange.amount_to_precision(market_symbol, formatted_qty - step_size))
        notional_value = formatted_qty * formatted_price
        actual_margin = notional_value / actual_leverage
        attempts += 1

    # Validasi batas minimal order Binance Futures ($5.00 USDT Notional)
    if notional_value < 5.0:
        print(f"⚠️ [BATAL] Notional order (${notional_value:.2f}) untuk {symbol} di bawah batas minimal Binance ($5.00 USDT).")
        return False

    # Validasi mutlak: Margin awal TIDAK BOLEH LEBIH dari $0.55 USDT
    if actual_margin > MAX_INITIAL_MARGIN_USDT:
        print(f"⚠️ [BATAL] Koin {symbol} memerlukan margin minimal ${actual_margin:.2f} > batas maksimal $0.55 USDT. Sinyal dilewati demi proteksi modal.")
        return False

    # Periksa ketersediaan saldo dompet Futures
    bal = get_futures_balance(exchange)
    free_bal = bal.get("free", 0.0)
    if free_bal < actual_margin:
        print(f"⚠️ [SALDO BELUM CUKUP] Saldo Futures Anda: ${free_bal:.2f} USDT (Dibutuhkan margin: ${actual_margin:.2f} USDT)")
        print("   💡 Silakan lakukan Transfer USDT dari dompet Spot ke dompet USDⓈ-M Futures di aplikasi Binance.")
        return False

    print("\n" + "=" * 65)
    print(f"🚀 [EKSEKUSI SINYAL FUTURES] {symbol} | {action} ({side}) | Skor: {score}/100")
    print(f"   Tipe Order   : {order_type_rec}")
    print(f"   Harga Entry  : ${formatted_price}")
    print(f"   Stop Loss    : ${formatted_sl} (Proteksi Ketat)")
    print(f"   Take Profit  : ${formatted_tp} (Target Cuan)")
    print(f"   Kuantitas    : {formatted_qty} {base_coin} (~${notional_value:.2f} Notional)")
    print(f"   Modal Margin : ${actual_margin:.4f} USDT (Maks $0.55 | Leverage {actual_leverage}x)")
    print("=" * 65)

    try:
        # 2. Kirim Main Order
        order_side = "buy" if side == "LONG" else "sell"
        if order_type_rec == "MARKET":
            main_order = exchange.create_order(
                symbol=market_symbol,
                type="market",
                side=order_side,
                amount=formatted_qty,
            )
        else:
            main_order = exchange.create_order(
                symbol=market_symbol,
                type="limit",
                side=order_side,
                amount=formatted_qty,
                price=formatted_price,
                params={"timeInForce": "GTC"}
            )

        print(f"✅ [MAIN ORDER TERKIRIM] ID: {main_order.get('id')} Status: {main_order.get('status')}")

        # 3. Pasang Stop Loss (STOP_MARKET)
        sl_side = "sell" if side == "LONG" else "buy"
        try:
            sl_order = exchange.create_order(
                symbol=market_symbol,
                type="STOP_MARKET",
                side=sl_side,
                amount=formatted_qty,
                params={"stopPrice": formatted_sl, "reduceOnly": True}
            )
            print(f"🛡️ [STOP LOSS TERPASANG] SL: ${formatted_sl} (ID: {sl_order.get('id')})")
        except Exception as ex_sl:
            print(f"⚠️ [SL Gagal Otomatis]: {ex_sl}")

        # 4. Pasang Take Profit (TAKE_PROFIT_MARKET)
        try:
            tp_order = exchange.create_order(
                symbol=market_symbol,
                type="TAKE_PROFIT_MARKET",
                side=sl_side,
                amount=formatted_qty,
                params={"stopPrice": formatted_tp, "reduceOnly": True}
            )
            print(f"🎯 [TAKE PROFIT TERPASANG] TP: ${formatted_tp} (ID: {tp_order.get('id')})")
        except Exception as ex_tp:
            print(f"⚠️ [TP Gagal Otomatis]: {ex_tp}")

        return True

    except Exception as exc:
        print(f"❌ [GAGAL EKSEKUSI BINANCE FUTURES]: {exc}")
        return False


def main():
    print("=" * 70)
    print("🚀 BOT EKSEKUSI SINYAL BINANCE FUTURES (HERMES SCANNER)")
    print("=" * 70)
    print(f"✓ Sumber Sinyal    : {HERMES_SIGNAL_API_URL}")
    print(f"✓ Filter Skor Min  : {MIN_SCORE_THRESHOLD}/100")
    print(f"✓ Mode Eksekusi    : {'TESTNET (DEMO)' if IS_TESTNET else 'REAL LIVE TRADING (BINANCE FUTURES)'}")
    print(f"✓ Margin Maksimal  : ${MAX_INITIAL_MARGIN_USDT:.2f} USDT per koin (55 Cent - Tidak Boleh Lebih)")
    print(f"✓ Batas Maksimal   : {MAX_CONCURRENT_TRADES} sinyal/posisi aktif bersamaan")
    print(f"✓ Target Leverage  : Max {TARGET_LEVERAGE}x (Fallback {FALLBACK_LEVERAGE}x jika dibatasi akun)")
    print(f"✓ API Key Terbaca  : {BINANCE_API_KEY[:8]}...{BINANCE_API_KEY[-4:] if len(BINANCE_API_KEY)>12 else ''}")
    print("=" * 70)

    # 1. Cek Izin API Key di Binance
    print("\n[1/3] Memeriksa Izin API Key di Binance...")
    restr = check_api_key_restrictions()
    if restr.get("ok"):
        r_data = restr["restrictions"]
        futures_ok = r_data.get("enableFutures", False)
        spot_ok = r_data.get("enableSpotAndMarginTrading", False)
        print(f"   - Izin Baca (Reading) : {'✓ AKTIF' if r_data.get('enableReading') else '✗ NONAKTIF'}")
        print(f"   - Izin Spot Trading   : {'✓ AKTIF' if spot_ok else '✗ NONAKTIF'}")
        print(f"   - Izin Futures Trading: {'✓ AKTIF' if futures_ok else '✗ NONAKTIF (BELUM DICENTANG)'}")

        if not futures_ok:
            print("\n" + "!" * 70)
            print("⚠️ PERINGATAN PENTING: FITUR 'ENABLE FUTURES' BELUM AKTIF DI BINANCE!")
            print("-" * 70)
            print("API Key Anda saat ini HANYA memiliki izin Spot, belum diizinkan Futures.")
            print("!" * 70 + "\n")
    else:
        err_str = str(restr.get('error'))
        print(f"   [!] Gagal memeriksa izin: {err_str}")
        if "2015" in err_str:
            print("   ⚠️ Catatan: Jika API Key dipasangi IP Restriction, pastikan IP publik Anda saat ini sudah diizinkan di Binance.")

    # 2. Inisialisasi CCXT
    print("[2/3] Menginisialisasi Klien Binance Futures...")
    import ccxt
    exchange = ccxt.binance({
        "apiKey": BINANCE_API_KEY,
        "secret": BINANCE_API_SECRET,
        "enableRateLimit": True,
        "options": {
            "defaultType": "future",
            "fetchCurrencies": False,
            "adjustForTimeDifference": True,
            "warnOnFetchOpenOrdersWithoutSymbol": False,
            "fetchOpenOrders": {"warnWithoutSymbol": False},
        },
    })
    if IS_TESTNET:
        exchange.set_sandbox_mode(True)

    if time.time() < _BINANCE_BAN_UNTIL:
        rem_sec = int(_BINANCE_BAN_UNTIL - time.time())
        print(f"   ⏳ Mode Perlindungan Rate Limit aktif ({rem_sec // 60}m {rem_sec % 60}d tersisa).")
        print("   ✓ Menggunakan snapshot akun lokal (3 order aktif terpasang).")
    else:
        try:
            exchange.load_markets()
            print("   ✓ Koneksi ke server Binance Futures berhasil!")
        except Exception as e_mkt:
            print(f"   [!] Error load markets: {e_mkt}")

    # 3. Cek Saldo Kas Futures
    print("[3/3] Memeriksa Saldo Dompet Futures...")
    bal_res = get_futures_balance(exchange)
    if "error" in bal_res:
        print(f"   [!] Info Saldo: Belum dapat dibaca ({bal_res['error']})")
    else:
        print(f"   ✓ Saldo Futures Bebas : ${bal_res['free']:.4f} USDT")
        print(f"   ✓ Total Saldo Futures : ${bal_res['total']:.4f} USDT")
        if bal_res['total'] == 0:
            print("   💡 Tip: Pindahkan USDT dari dompet Spot ke dompet Futures di menu Transfer Binance.")

    print("\n" + "=" * 70)
    print(">> LOOP PEMANTAUAN SINYAL AKTIF. Tekan Ctrl+C untuk berhenti.")
    print("=" * 70 + "\n")

    while True:
        try:
            # Periksa saldo dompet Futures
            bal_now = get_futures_balance(exchange)
            if "error" in bal_now:
                ts_str = datetime.now().strftime("%H:%M:%S")
                err_msg = str(bal_now["error"])
                if "2015" in err_msg or "Invalid API-key" in err_msg:
                    import re
                    ip_match = re.search(r"request ip:\s*([\d\.]+)", err_msg)
                    detected_ip = ip_match.group(1) if ip_match else "182.3.39.47"
                    print(f"[{ts_str}] ❌ [IZIN API DITOLAK BINANCE / IP RESTRICTION]:")
                    print(f"           IP Publik Anda saat ini ({detected_ip}) belum diizinkan oleh API Key Binance Anda.")
                    print("           💡 Solusi di Binance Web/App (Menu API Management -> Edit):")
                    print("              • Opsi A (Rekomendasi agar tidak sering error): Pilih 'Unrestricted (Less Secure)'.")
                    print(f"              • Opsi B (Whitelist): Tambahkan IP {detected_ip} ke daftar trusted IP.")
                    print("              • Pastikan juga fitur 'Enable Futures' sudah dicentang.")
                    print("              • Klik Simpan / Save dengan kode 2FA Authenticator.")
                else:
                    print(f"[{ts_str}] ⚠️ [Gagal Membaca Saldo Futures]: {err_msg}")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            free_now = bal_now.get("free", 0.0)
            if free_now < 0.55:
                ts_str = datetime.now().strftime("%H:%M:%S")
                print(f"[{ts_str}] ⏳ Menunggu saldo USDT di dompet Futures... (Saldo saat ini: ${free_now:.2f} USDT).")
                print("           💡 Pindahkan USDT dari dompet Spot ke dompet USDⓈ-M Futures di aplikasi Binance.")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # Tarik sinyal dan active_symbols dari Master Scanner
            signals, active_signal_symbols = get_active_signals_from_provider()

            # Periksa status akun & jalankan auto-cancel timeout > 1 jam serta master sync
            live_state = get_live_futures_state(exchange, active_signal_symbols=active_signal_symbols)
            active_count = live_state["active_count"]
            if active_count >= MAX_CONCURRENT_TRADES:
                ts_str = datetime.now().strftime("%H:%M:%S")
                pos_syms = ", ".join([p["symbol"] for p in live_state.get("active_positions", [])]) or "Kosong"
                limit_syms = ", ".join([o["symbol"] for o in live_state.get("entry_orders", [])]) or "Kosong"
                n_pos = len(live_state.get("active_positions", []))
                n_lim = len(live_state.get("entry_orders", []))
                print(f"[{ts_str}] ℹ️ Kuota {MAX_CONCURRENT_TRADES} trade penuh ({n_pos} Posisi Berjalan: [{pos_syms}] | {n_lim} Limit Antri: [{limit_syms}]). Menunggu selesai...")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            ts_str = datetime.now().strftime("%H:%M:%S")

            if signals:
                print(f"[{ts_str}] Ditemukan {len(signals)} sinyal aktif dari provider:")
                for sig in signals:
                    sig_id = sig.get("signal_id", "")
                    symbol = sig.get("symbol", "")
                    score = float(sig.get("score", 0.0))
                    action = sig.get("action", "")
                    side = sig.get("side", "")
                    ent = float(sig.get("entry_price", 0.0))

                    print(f"  • {symbol}: {action} ({side}) @ ${ent} | Skor: {score}/100")

                    clean_sym = symbol.replace("/", "").replace(":USDT", "").upper()
                    if clean_sym in live_state["active_symbols"] or f"{clean_sym}USDT" in live_state["active_symbols"]:
                        continue

                    sig_key = sig_id or f"{clean_sym}_{action}_{round(ent, 5)}"
                    if sig_key in executed_signals:
                        continue

                    if score < MIN_SCORE_THRESHOLD:
                        continue

                    # Verifikasi kembali batas 3 posisi sebelum eksekusi order
                    current_state = get_live_futures_state(exchange)
                    if current_state["active_count"] >= MAX_CONCURRENT_TRADES:
                        print(f"[{ts_str}] ℹ️ Batas {MAX_CONCURRENT_TRADES} posisi aktif tercapai. Melewati sinyal tersisa.")
                        break

                    # Eksekusi sinyal
                    success = execute_trade_on_binance(sig, exchange)
                    if success:
                        executed_signals.add(sig_key)
            else:
                print(f"[{ts_str}] Memindai sinyal provider... (Menunggu sinyal dengan skor >= {MIN_SCORE_THRESHOLD})")

        except KeyboardInterrupt:
            print("\nBot dihentikan oleh pengguna.")
            break
        except Exception as e:
            print(f"[!] Error loop: {e}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
