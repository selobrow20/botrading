"""
==============================================================================
BOTRADING UNIFIED WEB DASHBOARD SERVER (v2.0)
==============================================================================
Menyediakan REST API & Server Web Real-Time untuk memantau SEMUA aktifitas bot:
1. Saham IDX Watchlist & Live Scanner
2. Forex / Gold (XAUUSD) & Terminal MetaTrader 5 (MT5)
3. Crypto Auto-Pump Sniper (Binance Spot & Paper Trading)
4. Database Riwayat Sinyal & Statistik Win Rate
5. Live Stream Terminal Log (stock_bot.log)
6. Kalender Berita Ekonomi & News Guard
7. 3D Isometric Trading Office & Copier Monitor
==============================================================================
"""

import os
import sys
import json
import time
import socket
import sqlite3
import threading
import subprocess
import webbrowser
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import requests

# Konfigurasi Encoding Windows Console
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Direktori Proyek
BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = BASE_DIR / "dashboard"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"
DB_PATH = DATA_DIR / "stock_data.db"
LOG_PATH = LOGS_DIR / "stock_bot.log"
CONFIG_PATH = CONFIG_DIR / "config.yaml"
MEMBER_COPIER_DIR = BASE_DIR / "member_copier"
STATE_FILE = MEMBER_COPIER_DIR / "copier_live_state.json"

# Inisialisasi Cache Global untuk mencegah load berlebihan
_CACHE_LOCK = threading.Lock()
_MT5_LOCK = threading.Lock()
_MT5_INITIALIZED = False
_CACHE = {
    "mt5": {"data": None, "ts": 0},
    "crypto_balance": {"data": None, "ts": 0},
    "bot_process": {"data": None, "ts": 0},
    "market_hours": {"data": None, "ts": 0},
}

# State Global Master
GLOBAL_STATE = {
    "vps_master": {
        "status": "ONLINE",
        "username": "selo_saham_bot",
        "provider": "Selo Brow (Strategy 9 Buku PDF)",
        "server": "Ubuntu VPS Cloud / Windows Runner",
        "latency_ms": 18,
        "last_signal": {
            "action": "BUY",
            "symbol": "XAUUSD",
            "entry": 4187.22,
            "tp": 4201.05,
            "sl": 4178.00,
            "time": "12:30:00"
        }
    },
    "gold_price": 4185.00,
    "recent_logs": [],
    "last_update": time.time(),
    "scan_in_progress": False
}

# State Live Real-Time Crypto Prices (Updated every 1s directly from Binance)
_LIVE_CRYPTO_LOCK = threading.Lock()
_LIVE_CRYPTO_DATA = {
    "prices": {
        "AVAXUSDT": 11.025,
        "PEPEUSDT": 0.00000426,
        "ZKUSDT": 0.01579,
        "BTCUSDT": 65000.0,
        "ETHUSDT": 2600.0,
        "SOLUSDT": 145.0
    },
    "last_update": 0
}


def _crypto_live_worker():
    """Background worker yang mengambil harga live Binance setiap 1.0 detik secara konsisten."""
    try:
        from crypto.exchange_client import setup_binance_dns_bypass
        setup_binance_dns_bypass()
    except Exception:
        pass

    session = requests.Session()
    session.headers.update({"User-Agent": "AntiGravity-LiveTicker/2.0"})

    endpoints = [
        "https://data-api.binance.vision",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
        "https://api.binance.com"
    ]

    last_balance_poll = 0.0

    while True:
        now_ts = time.time()
        # 1. Update Saldo & Portofolio Dompet Binance secara Live (Setiap 2.0 Detik)
        if now_ts - last_balance_poll >= 2.0:
            last_balance_poll = now_ts
            try:
                from crypto.exchange_client import CryptoExchangeClient
                ex_client = CryptoExchangeClient()
                if ex_client.is_authenticated():
                    bal = ex_client.get_balance()
                    if bal.get("authenticated"):
                        holdings = bal.get("holdings", {})
                        free_usdt = float(bal.get("free_usdt", 0.0))

                        with _LIVE_CRYPTO_LOCK:
                            p_snap = dict(_LIVE_CRYPTO_DATA["prices"])

                        assets_list = []
                        total_est = free_usdt
                        invested = 0.0
                        for asset, hdata in holdings.items():
                            amt = float(hdata.get("total", 0.0))
                            if amt <= 0.00000001:
                                continue
                            if asset == "USDT":
                                p = 1.0
                                val = amt
                            else:
                                sym = f"{asset}USDT"
                                p = p_snap.get(sym, 0.0)
                                val = amt * p
                                invested += val
                                total_est += val
                            assets_list.append({
                                "asset": asset,
                                "symbol": f"{asset}USDT" if asset != "USDT" else "USDT",
                                "amount": amt,
                                "free": float(hdata.get("free", 0.0)),
                                "locked": float(hdata.get("locked", 0.0)),
                                "price": p,
                                "value_usdt": round(val, 4)
                            })
                        assets_list.sort(key=lambda x: x["value_usdt"], reverse=True)
                        for a in assets_list:
                            a["pct_share"] = round((a["value_usdt"] / total_est * 100), 1) if total_est > 0 else 0.0

                        bal_info = {
                            "authenticated": True,
                            "total_est_usdt": round(total_est, 4),
                            "free_usdt": round(free_usdt, 4),
                            "invested_usdt": round(invested, 4),
                            "holdings": holdings,
                            "assets": assets_list
                        }
                        with _CACHE_LOCK:
                            _CACHE["crypto_balance"] = {"data": bal_info, "prices": p_snap, "ts": now_ts}

                        # 2-WAY RECONCILIATION: Pastikan database open positions 100% sama dengan Binance
                        if DB_PATH.exists():
                            try:
                                with get_db_connection() as conn:
                                    cur = conn.cursor()
                                    cur.execute("SELECT id, symbol, quantity, entry_price FROM crypto_pump_positions WHERE status IN ('OPEN', 'TP1_HIT')")
                                    active_rows = cur.fetchall()
                                    for row in active_rows:
                                        r_sym = row["symbol"]
                                        r_asset = r_sym.replace("USDT", "")
                                        live_h = holdings.get(r_asset, {})
                                        live_free = float(live_h.get("free", 0.0))
                                        if live_free <= 0.000001:
                                            now_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            cur.execute("""
                                                UPDATE crypto_pump_positions 
                                                SET status = 'CLOSED_MANUAL_EXTERNAL', close_time = ?, 
                                                    exit_reason = 'Terdeteksi dijual habis di Binance' 
                                                WHERE id = ?
                                            """, (now_dt, row["id"]))
                                            conn.commit()

                                    active_symbols = {r["symbol"] for r in active_rows}
                                    for asset, hdata in holdings.items():
                                        if asset in ["USDT", "FDUSD", "USDC"]:
                                            continue
                                        h_free = float(hdata.get("free", 0.0))
                                        sym = f"{asset}USDT"
                                        if sym not in active_symbols:
                                            curr_p = p_snap.get(sym, 0.0)
                                            if (h_free * curr_p) >= 0.40:
                                                cur.execute("SELECT entry_price, status FROM crypto_pump_positions WHERE symbol = ? ORDER BY id DESC LIMIT 1", (sym,))
                                                prev = cur.fetchone()
                                                if not (prev and prev["status"] and str(prev["status"]).startswith("CLOSED_")):
                                                    e_p = float(prev["entry_price"]) if prev and prev["entry_price"] else curr_p
                                                    sl_p = e_p * 0.945
                                                    tp1_p = e_p * 1.11
                                                    tp2_p = e_p * 1.25
                                                    cost = h_free * e_p
                                                    now_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                                    cur.execute("""
                                                        INSERT INTO crypto_pump_positions (
                                                            symbol, mode, status, entry_price, quantity, cost_usdt,
                                                            entry_time, sl_price, tp1_price, tp2_price, tp1_hit
                                                        ) VALUES (?, 'real', 'OPEN', ?, ?, ?, ?, ?, ?, ?, 0)
                                                    """, (sym, e_p, h_free, cost, now_dt, sl_p, tp1_p, tp2_p))
                                                    conn.commit()
                            except Exception:
                                pass
            except Exception:
                pass

        # 2. Update Harga Ticker Binance (Setiap 1.0 Detik)
        try:
            symbols = ["DOGEUSDT", "PEPEUSDT", "AVAXUSDT", "ZKUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"]
            if DB_PATH.exists():
                try:
                    with get_db_connection() as conn:
                        c = conn.cursor()
                        c.execute("SELECT DISTINCT symbol FROM crypto_pump_positions WHERE status IN ('OPEN', 'TP1_HIT')")
                        for row in c.fetchall():
                            s = row["symbol"]
                            if s and s not in symbols:
                                symbols.append(s)
                except Exception:
                    pass

            with _CACHE_LOCK:
                cb = _CACHE["crypto_balance"].get("data")
                if cb and "holdings" in cb:
                    for asset in cb["holdings"].keys():
                        if asset not in ["USDT", "FDUSD", "USDC"]:
                            sym = f"{asset}USDT"
                            if sym not in symbols:
                                symbols.append(sym)

            symbols_json = json.dumps(symbols, separators=(',', ':'))
            for base_url in endpoints:
                try:
                    url = f"{base_url}/api/v3/ticker/price?symbols={symbols_json}"
                    r = session.get(url, timeout=2.5)
                    if r.status_code == 200:
                        items = r.json()
                        with _LIVE_CRYPTO_LOCK:
                            for item in items:
                                sym = item.get("symbol")
                                p = float(item.get("price") or 0.0)
                                if sym and p > 0:
                                    _LIVE_CRYPTO_DATA["prices"][sym] = p
                            _LIVE_CRYPTO_DATA["last_update"] = time.time()
                        break
                except Exception:
                    continue
        except Exception:
            pass
        time.sleep(1.0)


def get_crypto_live_feed() -> dict:
    """Mengembalikan feed harga real-time 1 detik, valuasi open positions, dan portofolio holding."""
    with _LIVE_CRYPTO_LOCK:
        prices = dict(_LIVE_CRYPTO_DATA["prices"])
        last_up = _LIVE_CRYPTO_DATA["last_update"]

    cached_bal = None
    cached_prices = {}
    with _CACHE_LOCK:
        cached_bal = _CACHE["crypto_balance"].get("data")
        cached_prices = _CACHE["crypto_balance"].get("prices", {})

    open_positions = []
    if DB_PATH.exists():
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT id, symbol, mode, status, entry_price, quantity, cost_usdt, 
                           sl_price, tp1_price, tp2_price, tp1_hit, entry_time
                    FROM crypto_pump_positions 
                    WHERE status IN ('OPEN', 'TP1_HIT') 
                    ORDER BY id DESC
                """)
                for r in c.fetchall():
                    d = dict(r)
                    sym = d["symbol"]
                    cur_p = prices.get(sym, 0.0)
                    if cur_p <= 0:
                        cur_p = float(cached_prices.get(sym, 0.0)) or float(d.get("entry_price") or 0.0)
                    entry_p = float(d.get("entry_price") or 1.0)
                    qty = float(d.get("quantity") or 0.0)
                    pnl_pct = ((cur_p - entry_p) / entry_p) * 100.0 if entry_p > 0 else 0.0
                    pnl_usdt = (cur_p - entry_p) * qty
                    d["current_price"] = cur_p
                    d["pnl_pct"] = round(pnl_pct, 2)
                    d["pnl_usdt"] = round(pnl_usdt, 4)
                    d["market_val_usdt"] = round(cur_p * qty, 4)
                    open_positions.append(d)
        except Exception:
            pass

    assets = []
    total_est_usdt = 0.0
    invested_usdt = 0.0
    free_usdt = 0.0

    if cached_bal:
        free_usdt = float(cached_bal.get("free_usdt", 0.0))
        holdings = cached_bal.get("holdings", {})
        for asset, hdata in holdings.items():
            amt = float(hdata.get("total", 0.0))
            if amt <= 0.00000001:
                continue
            if asset == "USDT":
                p = 1.0
                val = amt
            else:
                sym = asset + "USDT"
                p = prices.get(sym, 0.0)
                if p <= 0:
                    p = float(cached_prices.get(sym, 0.0))
                val = amt * p
                invested_usdt += val
            total_est_usdt += val
            assets.append({
                "asset": asset,
                "amount": amt,
                "free": float(hdata.get("free", 0.0)),
                "locked": float(hdata.get("locked", 0.0)),
                "price": p,
                "value_usdt": round(val, 4)
            })

        assets.sort(key=lambda x: x["value_usdt"], reverse=True)
        for a in assets:
            a["pct_share"] = round((a["value_usdt"] / total_est_usdt * 100), 1) if total_est_usdt > 0 else 0.0

    return {
        "prices": prices,
        "open_positions": open_positions,
        "assets": assets,
        "total_est_usdt": round(total_est_usdt, 4),
        "invested_usdt": round(invested_usdt, 4),
        "free_usdt": round(free_usdt, 4),
        "timestamp": last_up or time.time()
    }


_KLINES_CACHE = {}
_KLINES_CACHE_LOCK = threading.Lock()

def get_crypto_klines(symbol: str = "DOGEUSDT", interval: str = "1m", limit: int = 50) -> dict:
    """Mengambil riwayat candlestick Binance resmi secara real-time untuk chart HUD ATS MATRIX."""
    sym = (symbol or "DOGEUSDT").upper().strip()
    if not sym.endswith("USDT") and not sym.endswith("FDUSD"):
        sym += "USDT"

    interval = interval if interval in ["1m", "3m", "5m", "15m", "1h", "4h", "1d"] else "1m"
    limit = min(max(int(limit or 50), 10), 120)
    cache_key = f"{sym}_{interval}_{limit}"
    now = time.time()

    with _KLINES_CACHE_LOCK:
        if cache_key in _KLINES_CACHE:
            cached_data, cached_ts = _KLINES_CACHE[cache_key]
            if now - cached_ts < 2.0:
                return cached_data

    endpoints = [
        "https://data-api.binance.vision",
        "https://api1.binance.com",
        "https://api.binance.com",
        "https://api2.binance.com",
    ]
    raw_candles = []
    session = requests.Session()

    for base_url in endpoints:
        try:
            url = f"{base_url}/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}"
            r = session.get(url, timeout=3.0)
            if r.status_code == 200:
                raw_candles = r.json()
                if isinstance(raw_candles, list) and raw_candles:
                    break
        except Exception:
            continue

    candles = []
    for k in raw_candles:
        try:
            candles.append({
                "time": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            })
        except Exception:
            continue

    # Ambil data posisi aktif jika koin sedang open
    pos_meta = None
    if DB_PATH.exists():
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT entry_price, sl_price, tp1_price, tp2_price, quantity, cost_usdt, entry_time 
                    FROM crypto_pump_positions 
                    WHERE symbol = ? AND status IN ('OPEN', 'TP1_HIT') 
                    ORDER BY id DESC LIMIT 1
                """, (sym,))
                row = c.fetchone()
                if row:
                    pos_meta = {
                        "entry_price": float(row["entry_price"] or 0),
                        "sl_price": float(row["sl_price"] or 0),
                        "tp1_price": float(row["tp1_price"] or 0),
                        "tp2_price": float(row["tp2_price"] or 0),
                        "quantity": float(row["quantity"] or 0),
                        "cost_usdt": float(row["cost_usdt"] or 0),
                        "entry_time": row["entry_time"],
                    }
        except Exception:
            pass

    # Ambil harga live stream terkini
    curr_px = 0.0
    with _LIVE_CRYPTO_LOCK:
        curr_px = _LIVE_CRYPTO_DATA["prices"].get(sym, 0.0)
    if curr_px <= 0 and candles:
        curr_px = candles[-1]["close"]

    result = {
        "symbol": sym,
        "interval": interval,
        "candles": candles,
        "current_price": curr_px,
        "position": pos_meta,
        "server_time": int(now * 1000)
    }

    with _KLINES_CACHE_LOCK:
        _KLINES_CACHE[cache_key] = (result, now)

    return result


def get_local_ip() -> str:
    """Mendeteksi alamat IP LAN lokal (misal: 192.168.1.4) untuk akses via HP/WiFi."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_db_connection() -> sqlite3.Connection:
    """Membuka koneksi SQLite dengan row_factory dictionary dan WAL mode untuk konkurensi tinggi."""
    conn = sqlite3.connect(str(DB_PATH), timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
    except Exception:
        pass
    return conn


def get_bot_process_info() -> dict:
    """Memeriksa apakah proses bot utama (main.py) sedang berjalan di OS secara cepat & hemat resource."""
    now = time.time()
    with _CACHE_LOCK:
        if _CACHE["bot_process"]["data"] and (now - _CACHE["bot_process"]["ts"] < 8.0):
            return _CACHE["bot_process"]["data"]

    info = {
        "running": False,
        "pid": None,
        "uptime_seconds": 0,
        "uptime_str": "-",
        "memory_mb": 0.0,
        "command": "-"
    }

    try:
        import psutil
        for p in psutil.process_iter(['pid', 'name']):
            p_name = (p.info.get('name') or '').lower()
            if 'python' in p_name:
                try:
                    cmd = p.cmdline()
                    if any('main.py' in str(arg) for arg in cmd):
                        info["running"] = True
                        info["pid"] = p.pid
                        c_time = p.create_time()
                        uptime = int(time.time() - c_time)
                        info["uptime_seconds"] = uptime
                        h = uptime // 3600
                        m = (uptime % 3600) // 60
                        s = uptime % 60
                        info["uptime_str"] = f"{h}j {m}m {s}d" if h > 0 else f"{m}m {s}d"
                        try:
                            info["memory_mb"] = round(p.memory_info().rss / (1024 * 1024), 1)
                        except Exception:
                            info["memory_mb"] = 0.0
                        info["command"] = " ".join(cmd)
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
    except Exception:
        pass

    with _CACHE_LOCK:
        _CACHE["bot_process"] = {"data": info, "ts": now}
    return info


def get_market_sessions() -> dict:
    """Menghitung status jam buka bursa saham IDX, Forex/Gold, dan Crypto saat ini (WIB)."""
    now = time.time()
    with _CACHE_LOCK:
        if _CACHE["market_hours"]["data"] and (now - _CACHE["market_hours"]["ts"] < 10.0):
            return _CACHE["market_hours"]["data"]

    # Waktu Jakarta (WIB = UTC+7)
    utc_now = datetime.now(timezone.utc)
    wib_now = utc_now + timedelta(hours=7)
    weekday = wib_now.weekday() # 0: Senin, 4: Jumat, 5: Sabtu, 6: Minggu
    curr_time = wib_now.time()

    # 1. IDX
    idx_open = False
    idx_desc = "Tutup (Di luar jam bursa)"
    if weekday < 5: # Senin s/d Jumat
        s1_start = datetime.strptime("09:00", "%H:%M").time()
        s1_end = datetime.strptime("11:30", "%H:%M").time()
        s2_start = datetime.strptime("14:00" if weekday == 4 else "13:30", "%H:%M").time()
        s2_end = datetime.strptime("15:50", "%H:%M").time()

        if s1_start <= curr_time <= s1_end:
            idx_open = True
            idx_desc = "Buka (Sesi 1: 09:00 - 11:30 WIB)"
        elif s1_end < curr_time < s2_start:
            idx_open = False
            idx_desc = f"Istirahat Siang (Sesi 2 mulai {s2_start.strftime('%H:%M')} WIB)"
        elif s2_start <= curr_time <= s2_end:
            idx_open = True
            idx_desc = f"Buka (Sesi 2: {s2_start.strftime('%H:%M')} - 15:50 WIB)"
        elif curr_time < s1_start:
            idx_desc = "Belum Buka (Mulai 09:00 WIB)"
        else:
            idx_desc = "Selesai (Tutup 15:50 WIB)"
    else:
        idx_desc = "Tutup (Akhir Pekan)"

    # 2. Forex / Gold XAUUSD (Senin 05:00 - Sabtu 04:00 WIB)
    gold_open = False
    if weekday == 0 and curr_time < datetime.strptime("05:00", "%H:%M").time():
        gold_open = False
        gold_desc = "Tutup (Buka Senin 05:00 WIB)"
    elif weekday == 5 and curr_time >= datetime.strptime("04:00", "%H:%M").time():
        gold_open = False
        gold_desc = "Tutup Akhir Pekan (Sabtu - Minggu)"
    elif weekday == 6:
        gold_open = False
        gold_desc = "Tutup Akhir Pekan (Sabtu - Minggu)"
    else:
        gold_open = True
        gold_desc = "Buka (Perdagangan 24 Jam Aktif)"

    # 3. Sesi Dunia
    # London: 14:00 - 23:00 WIB
    london_active = (14 <= wib_now.hour < 23) and (weekday < 5)
    # New York: 19:00 - 04:00 WIB
    ny_active = (wib_now.hour >= 19 or wib_now.hour < 4) and (weekday < 6)

    res = {
        "wib_time": wib_now.strftime("%Y-%m-%d %H:%M:%S WIB"),
        "idx": {"open": idx_open, "desc": idx_desc},
        "gold": {"open": gold_open, "desc": gold_desc},
        "crypto": {"open": True, "desc": "24/7 Selalu Aktif Non-Stop"},
        "sessions": {
            "london": {"active": london_active, "name": "London Session (14:00-23:00 WIB)"},
            "new_york": {"active": ny_active, "name": "New York Session (19:00-04:00 WIB)"}
        }
    }

    with _CACHE_LOCK:
        _CACHE["market_hours"] = {"data": res, "ts": now}
    return res


def get_mt5_data() -> dict:
    """Mengambil data live dari terminal MetaTrader 5 lokal."""
    global _MT5_INITIALIZED
    now = time.time()
    with _CACHE_LOCK:
        if _CACHE["mt5"]["data"] and (now - _CACHE["mt5"]["ts"] < 3.0):
            return _CACHE["mt5"]["data"]

    data = {
        "connected": False,
        "login": 0,
        "server": "Offline / MT5 Standby",
        "balance": 0.0,
        "equity": 0.0,
        "margin": 0.0,
        "free_margin": 0.0,
        "currency": "USC",
        "positions": [],
        "gold_price": GLOBAL_STATE["gold_price"],
        "error": None
    }

    try:
        import MetaTrader5 as mt5
        with _MT5_LOCK:
            if not _MT5_INITIALIZED:
                if mt5.initialize():
                    _MT5_INITIALIZED = True

            if _MT5_INITIALIZED:
                acc = mt5.account_info()
                if acc:
                    data["connected"] = True
                    data["login"] = acc.login
                    data["server"] = acc.server
                    data["balance"] = float(acc.balance)
                    data["equity"] = float(acc.equity)
                    data["margin"] = float(acc.margin)
                    data["free_margin"] = float(acc.margin_free)
                    data["currency"] = acc.currency
                else:
                    _MT5_INITIALIZED = False

                positions = mt5.positions_get()
                pos_list = []
                if positions:
                    for p in positions:
                        pos_list.append({
                            "ticket": p.ticket,
                            "symbol": p.symbol,
                            "type": "BUY" if p.type == 0 else "SELL",
                            "lot": p.volume,
                            "openPrice": round(float(p.price_open), 2),
                            "currentPrice": round(float(p.price_current), 2),
                            "sl": round(float(p.sl), 2),
                            "tp": round(float(p.tp), 2),
                            "profit": round(float(p.profit), 2)
                        })
                data["positions"] = pos_list

                for sym in ["XAUUSDc", "XAUUSD", "GOLD"]:
                    tick = mt5.symbol_info_tick(sym)
                    if tick:
                        price = round((tick.bid + tick.ask) / 2.0, 2)
                        data["gold_price"] = price
                        GLOBAL_STATE["gold_price"] = price
                        break
            else:
                data["error"] = "mt5.initialize() gagal"
    except Exception as e:
        data["error"] = str(e)

    with _CACHE_LOCK:
        _CACHE["mt5"] = {"data": data, "ts": now}
    return data


def get_crypto_data() -> dict:
    """Mengambil status posisi, order, dan saldo Binance Crypto."""
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            import yaml
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            pass

    crypto_cfg = cfg.get("crypto", {})
    mode = os.getenv("AUTOPUMP_MODE", crypto_cfg.get("mode", "real")).lower()
    capital = float(os.getenv("AUTOPUMP_CAPITAL_PER_COIN", crypto_cfg.get("capital_per_coin", 1.0)))
    max_positions = int(os.getenv("AUTOPUMP_MAX_POSITIONS", crypto_cfg.get("max_positions", 3)))
    min_score = int(os.getenv("AUTOPUMP_MIN_SCORE", crypto_cfg.get("min_score", 85)))

    open_positions = []
    closed_history = []
    mode_stats = {
        "real": {"wins": 0, "losses": 0, "bep": 0, "total": 0, "profit": 0.0, "loss": 0.0, "net_pnl": 0.0, "win_rate": 0.0},
        "paper": {"wins": 0, "losses": 0, "bep": 0, "total": 0, "profit": 0.0, "loss": 0.0, "net_pnl": 0.0, "win_rate": 0.0},
    }

    if DB_PATH.exists():
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                
                # Cek tabel crypto_pump_positions
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='crypto_pump_positions'")
                if c.fetchone():
                    # Posisi Terbuka
                    c.execute("""
                        SELECT id, symbol, mode, status, entry_price, quantity, cost_usdt, 
                               entry_time, sl_price, tp1_price, tp2_price, tp1_hit, 
                               current_price, pnl_usdt, pnl_pct 
                        FROM crypto_pump_positions 
                        WHERE status IN ('OPEN', 'TP1_HIT') 
                        ORDER BY id DESC
                    """)
                    for r in c.fetchall():
                        open_positions.append(dict(r))

                    # Agregasi Total Statistik Database per Mode (Semua Trade)
                    c.execute("""
                        SELECT 
                            mode,
                            COUNT(*) as total_count,
                            COALESCE(SUM(CASE WHEN pnl_usdt > 0.00001 THEN pnl_usdt ELSE 0 END), 0.0) as total_profit,
                            COALESCE(SUM(CASE WHEN pnl_usdt < -0.00001 THEN pnl_usdt ELSE 0 END), 0.0) as total_loss,
                            COALESCE(SUM(pnl_usdt), 0.0) as net_pnl,
                            COUNT(CASE WHEN pnl_usdt > 0.00001 THEN 1 END) as win_count,
                            COUNT(CASE WHEN pnl_usdt < -0.00001 THEN 1 END) as lose_count,
                            COUNT(CASE WHEN ABS(pnl_usdt) <= 0.00001 THEN 1 END) as bep_count
                        FROM crypto_pump_positions 
                        WHERE status NOT IN ('OPEN', 'TP1_HIT')
                        GROUP BY mode
                    """)
                    for row in c.fetchall():
                        m = str(row["mode"]).lower()
                        w = int(row["win_count"] or 0)
                        l = int(row["lose_count"] or 0)
                        b = int(row["bep_count"] or 0)
                        tot = int(row["total_count"] or 0)
                        prof = float(row["total_profit"] or 0.0)
                        loss = float(row["total_loss"] or 0.0)
                        net = float(row["net_pnl"] or 0.0)
                        decided = w + l
                        wr = round((w / decided * 100), 1) if decided > 0 else 0.0
                        mode_stats[m] = {
                            "wins": w,
                            "losses": l,
                            "bep": b,
                            "total": tot,
                            "profit": round(prof, 4),
                            "loss": round(loss, 4),
                            "net_pnl": round(net, 4),
                            "win_rate": wr
                        }

                    # Riwayat Closed Lengkap dengan Durasi Hold & Outcome
                    c.execute("""
                        SELECT id, symbol, mode, status, entry_price, quantity, cost_usdt, 
                               entry_time, close_price, close_time, pnl_usdt, pnl_pct, exit_reason 
                        FROM crypto_pump_positions 
                        WHERE status NOT IN ('OPEN', 'TP1_HIT') 
                        ORDER BY id DESC LIMIT 300
                    """)
                    for r in c.fetchall():
                        d = dict(r)
                        pnl = float(d.get("pnl_usdt") or 0.0)
                        d["outcome"] = "PROFIT" if pnl > 0.00001 else ("LOSS" if pnl < -0.00001 else "BEP")
                        try:
                            if d.get("entry_time") and d.get("close_time"):
                                dt1 = datetime.strptime(str(d["entry_time"]), "%Y-%m-%d %H:%M:%S")
                                dt2 = datetime.strptime(str(d["close_time"]), "%Y-%m-%d %H:%M:%S")
                                diff_sec = max(0, int((dt2 - dt1).total_seconds()))
                                if diff_sec < 60:
                                    d["hold_duration"] = f"{diff_sec}d"
                                elif diff_sec < 3600:
                                    d["hold_duration"] = f"{diff_sec // 60}m"
                                else:
                                    hours = diff_sec // 3600
                                    mins = (diff_sec % 3600) // 60
                                    d["hold_duration"] = f"{hours}j {mins}m"
                            else:
                                d["hold_duration"] = "-"
                        except Exception:
                            d["hold_duration"] = "-"
                        closed_history.append(d)
        except Exception:
            pass

    # Ambil Saldo Binance & Portofolio jika terkoneksi
    now = time.time()
    balance_info = None
    cached_prices = {}
    with _CACHE_LOCK:
        if _CACHE["crypto_balance"]["data"] and (now - _CACHE["crypto_balance"]["ts"] < 15.0):
            balance_info = _CACHE["crypto_balance"]["data"]
            cached_prices = _CACHE["crypto_balance"].get("prices", {})

    if balance_info is None:
        symbol_prices = {}
        try:
            from crypto.exchange_client import CryptoExchangeClient
            client = CryptoExchangeClient()
            if client.is_authenticated():
                bal = client.get_balance()
                holdings = bal.get("holdings", {})
                free_usdt = float(bal.get("free_usdt", 0.0))
                invested_usdt = 0.0
                total_est_usdt = 0.0
                assets = []

                # Salin snapshot harga live saat ini
                with _LIVE_CRYPTO_LOCK:
                    live_prices_snapshot = dict(_LIVE_CRYPTO_DATA["prices"])

                for asset, hdata in holdings.items():
                    amt = float(hdata.get("total", 0.0))
                    if amt <= 0.00000001:
                        continue
                    if asset == "USDT":
                        price = 1.0
                        val = amt
                    else:
                        sym = asset + "USDT"
                        price = live_prices_snapshot.get(sym, 0.0)
                        if price <= 0:
                            try:
                                tick = client.fetch_ticker(sym)
                                price = float(tick.get("last_price") or tick.get("last") or 0.0)
                            except Exception:
                                price = 0.0
                        symbol_prices[sym] = price
                        val = amt * price
                        invested_usdt += val

                    total_est_usdt += val
                    assets.append({
                        "asset": asset,
                        "symbol": asset + "USDT" if asset != "USDT" else "USDT",
                        "free": float(hdata.get("free", 0.0)),
                        "locked": float(hdata.get("locked", 0.0)),
                        "amount": amt,
                        "price": price,
                        "value_usdt": round(val, 4)
                    })

                assets.sort(key=lambda x: x["value_usdt"], reverse=True)
                for item in assets:
                    item["pct_share"] = round((item["value_usdt"] / total_est_usdt * 100), 1) if total_est_usdt > 0 else 0.0

                balance_info = {
                    "authenticated": True,
                    "total_est_usdt": round(total_est_usdt, 4),
                    "free_usdt": round(free_usdt, 4),
                    "invested_usdt": round(invested_usdt, 4),
                    "holdings": holdings,
                    "assets": assets
                }
            else:
                balance_info = {
                    "authenticated": False,
                    "total_est_usdt": 100.0,
                    "free_usdt": 100.0,
                    "invested_usdt": 0.0,
                    "holdings": {},
                    "assets": []
                }
        except Exception:
            balance_info = {
                "authenticated": False,
                "total_est_usdt": 100.0,
                "free_usdt": 100.0,
                "invested_usdt": 0.0,
                "holdings": {},
                "assets": []
            }

        cached_prices = symbol_prices
        with _CACHE_LOCK:
            _CACHE["crypto_balance"] = {"data": balance_info, "prices": symbol_prices, "ts": now}

    # Perkaya posisi terbuka dengan harga live & floating PnL
    for pos in open_positions:
        sym = pos.get("symbol")
        cur_p = cached_prices.get(sym)
        if not cur_p:
            try:
                from crypto.exchange_client import CryptoExchangeClient
                client = CryptoExchangeClient()
                tick = client.fetch_ticker(sym)
                cur_p = float(tick.get("last_price") or tick.get("last") or 0.0)
                cached_prices[sym] = cur_p
            except Exception:
                cur_p = float(pos.get("current_price") or pos.get("entry_price") or 0.0)

        entry_p = float(pos.get("entry_price") or 1.0)
        qty = float(pos.get("quantity") or 0.0)
        if cur_p and entry_p > 0:
            pos["current_price"] = cur_p
            pnl_pct = ((cur_p - entry_p) / entry_p) * 100.0
            pnl_usdt = (cur_p - entry_p) * qty
            pos["pnl_pct"] = round(pnl_pct, 2)
            pos["pnl_usdt"] = round(pnl_usdt, 4)
            pos["market_val_usdt"] = round(cur_p * qty, 4)

    real_stat = mode_stats.get("real", {"wins": 0, "losses": 0, "bep": 0, "total": 0, "profit": 0.0, "loss": 0.0, "net_pnl": 0.0, "win_rate": 0.0})
    paper_stat = mode_stats.get("paper", {"wins": 0, "losses": 0, "bep": 0, "total": 0, "profit": 0.0, "loss": 0.0, "net_pnl": 0.0, "win_rate": 0.0})

    # Total agregasi keseluruhan (Real + Paper)
    total_wins = real_stat["wins"] + paper_stat["wins"]
    total_losses = real_stat["losses"] + paper_stat["losses"]
    total_bep = real_stat["bep"] + paper_stat["bep"]
    total_closed = real_stat["total"] + paper_stat["total"]
    total_profit = round(real_stat["profit"] + paper_stat["profit"], 4)
    total_loss = round(real_stat["loss"] + paper_stat["loss"], 4)
    total_realized_pnl = round(real_stat["net_pnl"] + paper_stat["net_pnl"], 4)
    overall_decided = total_wins + total_losses
    overall_win_rate = round((total_wins / overall_decided * 100), 1) if overall_decided > 0 else 0.0

    # Statistik mode aktif bot (misal: "real" atau "paper")
    curr_mode_stat = real_stat if mode == "real" else paper_stat

    return {
        "mode": mode,
        "capital_per_coin": capital,
        "max_positions": max_positions,
        "min_score": min_score,
        "balance": balance_info,
        "open_positions": open_positions,
        "closed_history": closed_history,
        "stats": {
            "open_count": len(open_positions),
            "closed_count": total_closed,
            "win_count": total_wins,
            "lose_count": total_losses,
            "bep_count": total_bep,
            "win_rate": overall_win_rate,
            "total_realized_pnl_usdt": total_realized_pnl,
            "total_profit_usdt": total_profit,
            "total_loss_usdt": total_loss,
            "active_mode": mode,
            "active_mode_pnl": curr_mode_stat["net_pnl"],
            "active_profit": curr_mode_stat["profit"],
            "active_loss": curr_mode_stat["loss"],
            "active_wins": curr_mode_stat["wins"],
            "active_losses": curr_mode_stat["losses"],
            "active_bep": curr_mode_stat["bep"],
            "active_total": curr_mode_stat["total"],
            "active_win_rate": curr_mode_stat["win_rate"],
            "real": real_stat,
            "paper": paper_stat,
        }
    }


_GLOBAL_FUTURES_EXCHANGE = None
_FUTURES_LIVE_PRICES_LOCK = threading.Lock()
_FUTURES_LIVE_PRICES = {
    "NOTUSDT": 0.0004408,
    "GOATUSDT": 0.015512,
    "AKTUSDT": 0.6811,
}

def fetch_futures_live_prices(symbols: list) -> dict:
    """Mengambil harga real-time live futures via Gate.io (CORS open, no-ban, 150ms) + CoinGecko fallback."""
    if not symbols:
        with _FUTURES_LIVE_PRICES_LOCK:
            return dict(_FUTURES_LIVE_PRICES)

    from concurrent.futures import ThreadPoolExecutor

    def get_single(s: str):
        base = s.replace("USDT", "")
        # 1. Gate.io USDT Perpetual Tickers (Identik dengan Binance Futures, tanpa limit/blokir)
        try:
            url = f"https://api.gateio.ws/api/v4/futures/usdt/tickers?contract={base}_USDT"
            r = requests.get(url, timeout=1.8)
            if r.status_code == 200:
                data = r.json()
                if data and isinstance(data, list) and "last" in data[0]:
                    p = float(data[0]["last"])
                    if p > 0:
                        return s, p
        except Exception:
            pass

        # 2. CoinGecko simple price fallback
        try:
            cg_map = {"NOTUSDT": "notcoin", "GOATUSDT": "goatseus-maximus", "AKTUSDT": "akash-network"}
            cg_id = cg_map.get(s)
            if cg_id:
                r_cg = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd", timeout=2)
                if r_cg.status_code == 200:
                    val = r_cg.json().get(cg_id, {}).get("usd")
                    if val:
                        return s, float(val)
        except Exception:
            pass

        return s, None

    with ThreadPoolExecutor(max_workers=min(len(symbols), 5)) as pool:
        for sym, px in pool.map(get_single, symbols):
            if px is not None:
                with _FUTURES_LIVE_PRICES_LOCK:
                    _FUTURES_LIVE_PRICES[sym] = px

    with _FUTURES_LIVE_PRICES_LOCK:
        return dict(_FUTURES_LIVE_PRICES)

_BINANCE_BAN_UNTIL = 1792005219138 / 1000.0  # 2026-10-15 02:13:39 WIB Cooldown protector
_FUTURES_ACCOUNT_LOCK = threading.Lock()
_FUTURES_ACCOUNT_CACHE = {
    "last_poll": 0.0,
    "wallet": {"free_usdt": 6.9233, "used_margin": 1.6473, "total_usdt": 8.5723, "unrealized_pnl": 0.0},
    "positions": [],
    "open_orders": [
        {"order_id": 8260474370, "symbol": "NOTUSDT", "side": "SHORT", "type": "LIMIT", "limit_price": 0.000447, "qty": 24608.0, "notional": 11.0, "initial_margin": 0.55, "stop_loss": 0.000453, "take_profit": 0.000432, "time": "16:45:29"},
        {"order_id": 3634677686, "symbol": "GOATUSDT", "side": "SHORT", "type": "LIMIT", "limit_price": 0.01568, "qty": 701.0, "notional": 10.99, "initial_margin": 0.5496, "stop_loss": 0.01586, "take_profit": 0.01518, "time": "16:49:13"},
        {"order_id": 935302797, "symbol": "AKTUSDT", "side": "SHORT", "type": "LIMIT", "limit_price": 0.6846, "qty": 16.0, "notional": 10.95, "initial_margin": 0.5477, "stop_loss": 0.6987, "take_profit": 0.6595, "time": "17:01:59"}
    ]
}

def get_futures_dashboard_data() -> dict:
    """
    Mengambil status live Binance Futures:
    - Saldo & Open Orders dipoll setiap 30 detik (agar aman dari rate limit Binance).
    - Harga Live Pasar (Live Ticker) & Jarak % diupdate setiap 1 detik via multi-source engine.
    """
    global _GLOBAL_FUTURES_EXCHANGE, _BINANCE_BAN_UNTIL
    now_ts = time.time()

    # 1. Update data akun dari Binance (Hanya setiap 30 detik & jika cooldown sudah lewat)
    if now_ts >= _BINANCE_BAN_UNTIL and (now_ts - _FUTURES_ACCOUNT_CACHE["last_poll"] > 30.0):
        try:
            import friend_bot_executor_example as fbot
            import ccxt
            fbot.setup_binance_dns_bypass()
            if fbot.BINANCE_API_KEY and fbot.BINANCE_API_SECRET:
                if _GLOBAL_FUTURES_EXCHANGE is None:
                    _GLOBAL_FUTURES_EXCHANGE = ccxt.binance({
                        "apiKey": fbot.BINANCE_API_KEY,
                        "secret": fbot.BINANCE_API_SECRET,
                        "enableRateLimit": True,
                        "options": {"defaultType": "future", "fetchCurrencies": False, "warnOnFetchOpenOrdersWithoutSymbol": False}
                    })
                exchange = _GLOBAL_FUTURES_EXCHANGE
                acc = exchange.fapiPrivateV2GetAccount()
                free_usdt = float(acc.get("availableBalance") or 0.0)
                total_usdt = float(acc.get("totalWalletBalance") or 0.0)
                used_margin = float(acc.get("totalInitialMargin") or 0.0)

                open_orders = exchange.fapiPrivateGetOpenOrders()
                algo_orders = exchange.fapiPrivateGetOpenAlgoOrders()
                positions = exchange.fapiPrivateV2GetPositionRisk()

                sl_map = {}
                tp_map = {}
                for a in algo_orders:
                    sym = a.get("symbol", "")
                    o_type = a.get("orderType", "")
                    trig = float(a.get("triggerPrice") or 0.0)
                    if o_type == "STOP_MARKET":
                        sl_map[sym] = trig
                    elif o_type == "TAKE_PROFIT_MARKET":
                        tp_map[sym] = trig

                pos_list = []
                total_unrealized = 0.0
                for p in positions:
                    amt = float(p.get("positionAmt") or 0.0)
                    if abs(amt) <= 0.0:
                        continue
                    sym = p.get("symbol", "")
                    entry_p = float(p.get("entryPrice") or 0.0)
                    unrealized = float(p.get("unRealizedProfit") or 0.0)
                    total_unrealized += unrealized
                    lev = int(p.get("leverage") or 20)
                    notional = abs(amt) * entry_p
                    init_margin = float(p.get("initialMargin") or (notional / lev if lev > 0 else 0.0))
                    side = "LONG" if amt > 0 else "SHORT"
                    pos_list.append({
                        "symbol": sym,
                        "side": side,
                        "amount": abs(amt),
                        "leverage": lev,
                        "entry_price": entry_p,
                        "mark_price": float(p.get("markPrice") or entry_p),
                        "initial_margin": round(init_margin, 4),
                        "unrealized_pnl": round(unrealized, 4),
                        "pnl_pct": round((unrealized / init_margin * 100) if init_margin > 0 else 0.0, 2),
                        "stop_loss": sl_map.get(sym),
                        "take_profit": tp_map.get(sym),
                    })

                ord_list = []
                for o in open_orders:
                    if o.get("reduceOnly", False):
                        continue
                    sym = o.get("symbol", "")
                    p_order = float(o.get("price") or 0.0)
                    qty = float(o.get("origQty") or 0.0)
                    notional = qty * p_order
                    ord_list.append({
                        "order_id": o.get("orderId"),
                        "symbol": sym,
                        "side": "SHORT" if o.get("side", "").upper() == "SELL" else "LONG",
                        "type": o.get("type", "LIMIT"),
                        "limit_price": p_order,
                        "qty": qty,
                        "notional": round(notional, 2),
                        "initial_margin": round(notional / 20.0, 4),
                        "stop_loss": sl_map.get(sym),
                        "take_profit": tp_map.get(sym),
                        "time": datetime.fromtimestamp(int(o.get("time", 0)) / 1000).strftime("%H:%M:%S") if o.get("time") else "-"
                    })

                with _FUTURES_ACCOUNT_LOCK:
                    _FUTURES_ACCOUNT_CACHE["last_poll"] = now_ts
                    _FUTURES_ACCOUNT_CACHE["wallet"] = {
                        "free_usdt": round(free_usdt, 4),
                        "used_margin": round(used_margin, 4),
                        "total_usdt": round(total_usdt, 4),
                        "unrealized_pnl": round(total_unrealized, 4)
                    }
                    _FUTURES_ACCOUNT_CACHE["positions"] = pos_list
                    _FUTURES_ACCOUNT_CACHE["open_orders"] = ord_list
        except Exception as ex:
            ex_str = str(ex)
            if "banned until" in ex_str or "418" in ex_str or "429" in ex_str:
                import re
                m = re.search(r"banned until (\d+)", ex_str)
                if m:
                    _BINANCE_BAN_UNTIL = int(m.group(1)) / 1000.0
                else:
                    _BINANCE_BAN_UNTIL = now_ts + 600.0

    # 2. Ambil data akun dari memori thread-safe
    with _FUTURES_ACCOUNT_LOCK:
        acc_wallet = dict(_FUTURES_ACCOUNT_CACHE["wallet"])
        acc_positions = [dict(p) for p in _FUTURES_ACCOUNT_CACHE["positions"]]
        acc_orders = [dict(o) for o in _FUTURES_ACCOUNT_CACHE["open_orders"]]

    needed_syms = list({o.get("symbol") for o in acc_orders}.union({p.get("symbol") for p in acc_positions}))
    if not needed_syms:
        needed_syms = ["NOTUSDT", "GOATUSDT", "AKTUSDT"]

    # 3. Update Harga Live Pasar Secara Real-Time (Gate.io / Multi-source Engine)
    live_prices = fetch_futures_live_prices(needed_syms)

    # 4. Hitung Jarak % ke Entry Limit & Update Kolom Live
    dyn_orders = []
    for o in acc_orders:
        sym = o.get("symbol")
        p_lim = float(o.get("limit_price") or 0.0)
        cur_p = live_prices.get(sym) or p_lim
        diff_pct = ((p_lim - cur_p) / cur_p * 100) if cur_p > 0 else 0.0
        o["current_price"] = cur_p
        o["diff_pct"] = round(diff_pct, 2)
        dyn_orders.append(o)

    dyn_positions = []
    total_live_pnl = 0.0
    for p in acc_positions:
        sym = p.get("symbol")
        entry_p = float(p.get("entry_price") or 0.0)
        mark_p = live_prices.get(sym) or p.get("mark_price") or entry_p
        amt = float(p.get("amount") or 0.0)
        is_long = p.get("side") == "LONG"
        pnl = (mark_p - entry_p) * amt if is_long else (entry_p - mark_p) * amt
        init_m = float(p.get("initial_margin") or 1.0)
        p["mark_price"] = mark_p
        p["unrealized_pnl"] = round(pnl, 4)
        p["pnl_pct"] = round((pnl / init_m * 100) if init_m > 0 else 0.0, 2)
        total_live_pnl += pnl
        dyn_positions.append(p)

    if dyn_positions:
        acc_wallet["unrealized_pnl"] = round(total_live_pnl, 4)

    return {
        "status": "ok",
        "wallet": acc_wallet,
        "rules": {"max_initial_margin": 0.55, "max_concurrent_trades": 3},
        "active_count": len(dyn_positions) + len(dyn_orders),
        "positions": dyn_positions,
        "open_orders": dyn_orders,
        "live_prices": live_prices,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }


def get_stock_data() -> dict:
    """Mengambil data watchlist saham Indonesia (IDX), bar terakhir, dan sinyal terkini."""
    watchlist = []
    if CONFIG_PATH.exists():
        try:
            import yaml
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
                raw_wl = cfg.get("watchlist", [])
                watchlist = [w for w in raw_wl if not any(k in w.upper() for k in ["XAU", "GC="])]
        except Exception:
            pass

    if not watchlist:
        watchlist = ["BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "TLKM.JK", "ASII.JK", "ANTM.JK", "ADRO.JK"]

    stock_items = []
    recent_signals = []

    if DB_PATH.exists():
        try:
            with get_db_connection() as conn:
                c = conn.cursor()

                # Ambil sinyal saham IDX terbaru
                c.execute("""
                    SELECT id, ticker, strategy_name, signal_type, price, 
                           take_profit_price, stop_loss_price, candle_time, 
                           outcome, pnl_pct, is_notified, reasons
                    FROM signals 
                    WHERE ticker NOT LIKE '%XAU%' AND ticker NOT LIKE '%GC=%'
                    ORDER BY id DESC LIMIT 50
                """)
                for r in c.fetchall():
                    recent_signals.append(dict(r))

                # Ambil bar harga terakhir per saham dari ohlcv_data
                for ticker in watchlist:
                    c.execute("""
                        SELECT close, datetime, open, high, low, volume 
                        FROM ohlcv_data 
                        WHERE ticker = ? 
                        ORDER BY datetime DESC LIMIT 1
                    """, (ticker,))
                    row = c.fetchone()
                    
                    # Cari sinyal terakhir untuk saham ini
                    c.execute("""
                        SELECT signal_type, price, candle_time, take_profit_price, stop_loss_price, outcome 
                        FROM signals 
                        WHERE ticker = ? 
                        ORDER BY id DESC LIMIT 1
                    """, (ticker,))
                    sig_row = c.fetchone()

                    stock_items.append({
                        "ticker": ticker,
                        "last_price": row["close"] if row else None,
                        "candle_time": row["datetime"] if row else "-",
                        "last_signal": sig_row["signal_type"] if sig_row else "WAIT",
                        "signal_price": sig_row["price"] if sig_row else None,
                        "tp": sig_row["take_profit_price"] if sig_row else None,
                        "sl": sig_row["stop_loss_price"] if sig_row else None,
                        "outcome": sig_row["outcome"] if sig_row else "-"
                    })
        except Exception:
            pass

    return {
        "watchlist": watchlist,
        "stocks": stock_items,
        "recent_signals": recent_signals,
        "scan_in_progress": GLOBAL_STATE["scan_in_progress"]
    }


def get_signals_history(category="all", outcome_filter="all", limit=100) -> dict:
    """Mengambil riwayat sinyal komprehensif dari database SQLite dengan filter."""
    signals = []
    stats = {
        "total": 0,
        "wins": 0,
        "losses": 0,
        "open": 0,
        "win_rate": 0.0
    }

    if not DB_PATH.exists():
        return {"signals": [], "stats": stats}

    try:
        with get_db_connection() as conn:
            c = conn.cursor()

            # Hitung statistik keseluruhan
            c.execute("SELECT count(*) FROM signals")
            stats["total"] = c.fetchone()[0]

            c.execute("SELECT count(*) FROM signals WHERE outcome = 'WIN'")
            stats["wins"] = c.fetchone()[0]

            c.execute("SELECT count(*) FROM signals WHERE outcome = 'LOSE'")
            stats["losses"] = c.fetchone()[0]

            c.execute("SELECT count(*) FROM signals WHERE outcome = 'OPEN'")
            stats["open"] = c.fetchone()[0]

            total_closed = stats["wins"] + stats["losses"]
            stats["win_rate"] = round((stats["wins"] / total_closed * 100), 1) if total_closed > 0 else 0.0

            # Bangun query dinamis berdasarkan filter
            where_clauses = []
            params = []

            if category == "idx":
                where_clauses.append("ticker NOT LIKE '%XAU%' AND ticker NOT LIKE '%GC=%'")
            elif category == "gold":
                where_clauses.append("(ticker LIKE '%XAU%' OR ticker LIKE '%GC=%')")

            if outcome_filter != "all":
                where_clauses.append("outcome = ?")
                params.append(outcome_filter.upper())

            where_str = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            query = f"""
                SELECT id, ticker, strategy_name, signal_type, price, 
                       take_profit_price, stop_loss_price, candle_time, 
                       outcome, exit_price, exit_time, pnl_pct, outcome_note, reasons 
                FROM signals 
                {where_str} 
                ORDER BY id DESC LIMIT ?
            """
            params.append(limit)
            c.execute(query, tuple(params))
            for r in c.fetchall():
                signals.append(dict(r))

    except Exception:
        pass

    return {"signals": signals, "stats": stats}


def get_calendar_events() -> list:
    """Mengambil daftar berita ekonomi berdampak tinggi dari database."""
    events = []
    if DB_PATH.exists():
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT id, title, country, date_utc, date_wib, impact, 
                           forecast, previous, news_type, alert_sent 
                    FROM economic_calendar 
                    ORDER BY date_utc DESC LIMIT 40
                """)
                for r in c.fetchall():
                    events.append(dict(r))
        except Exception:
            pass
    return events


def get_live_logs(lines_count=150, filter_level=None) -> list:
    """Membaca baris terbaru langsung dari stock_bot.log."""
    if not LOG_PATH.exists():
        return []

    results = []
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-lines_count:]

        import re
        log_pattern = re.compile(r"^\[(.*?)\] \[(.*?)\] \[(.*?)\] - (.*)$")

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            m = log_pattern.match(line_str)
            if m:
                ts, level, comp, msg = m.groups()
                if filter_level and filter_level.upper() != "ALL" and level.upper() != filter_level.upper():
                    continue
                results.append({
                    "timestamp": ts,
                    "level": level,
                    "component": comp,
                    "message": msg,
                    "raw": line_str
                })
            else:
                results.append({
                    "timestamp": "-",
                    "level": "INFO",
                    "component": "system",
                    "message": line_str,
                    "raw": line_str
                })
    except Exception as e:
        results.append({
            "timestamp": "-",
            "level": "ERROR",
            "component": "log_reader",
            "message": f"Gagal membaca log: {e}",
            "raw": str(e)
        })

    return results


def run_background_scan():
    """Menjalankan scan watchlist di background thread."""
    if GLOBAL_STATE["scan_in_progress"]:
        return
    GLOBAL_STATE["scan_in_progress"] = True
    
    def worker():
        try:
            print("\n🔍 [DASHBOARD ACTION] Menjalankan Scan Watchlist Manual...")
            # Panggil python main.py scan
            python_bin = sys.executable
            venv_python = BASE_DIR / ".venv" / "Scripts" / "python.exe"
            if venv_python.exists():
                python_bin = str(venv_python)
            
            subprocess.run([python_bin, "main.py", "scan"], cwd=str(BASE_DIR), capture_output=True, text=True, encoding="utf-8", errors="replace")
            print("✅ [DASHBOARD ACTION] Scan Watchlist Selesai!")
        except Exception as e:
            print(f"❌ [DASHBOARD ACTION] Scan gagal: {e}")
        finally:
            GLOBAL_STATE["scan_in_progress"] = False

    t = threading.Thread(target=worker, daemon=True)
    t.start()


# ==============================================================================
# HTTP REQUEST HANDLER (REST API & STATIC SERVER)
# ==============================================================================
class DashboardRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format, *args):
        # Redam log static asset agar console tidak berisik
        return

    def send_json(self, data, status_code=200):
        try:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception:
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # 1. API: OVERVIEW SUMMARY (COMMAND CENTER)
        if path == "/api/overview":
            bot_info = get_bot_process_info()
            markets = get_market_sessions()
            mt5_data = get_mt5_data()
            crypto_data = get_crypto_data()
            signals_data = get_signals_history(limit=10)
            
            response = {
                "bot": bot_info,
                "markets": markets,
                "mt5": {
                    "connected": mt5_data.get("connected", False),
                    "login": mt5_data.get("login", 0),
                    "balance": mt5_data.get("balance", 0.0),
                    "equity": mt5_data.get("equity", 0.0),
                    "currency": mt5_data.get("currency", "USC"),
                    "open_positions_count": len(mt5_data.get("positions", [])),
                    "gold_price": mt5_data.get("gold_price", GLOBAL_STATE["gold_price"])
                },
                "crypto": {
                    "mode": crypto_data.get("mode", "real"),
                    "open_positions_count": len(crypto_data.get("open_positions", [])),
                    "total_est_usdt": crypto_data.get("balance", {}).get("total_est_usdt", 0.0),
                    "free_usdt": crypto_data.get("balance", {}).get("free_usdt", 0.0),
                    "invested_usdt": crypto_data.get("balance", {}).get("invested_usdt", 0.0),
                    "stats": crypto_data.get("stats", {}),
                    "recent_closed": crypto_data.get("closed_history", [])[:6]
                },
                "signals_stats": signals_data.get("stats", {}),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.send_json(response)
            return

        # 2. API: STATUS (BACKWARD COMPATIBILITY DENGAN OFFICE 3D)
        elif path == "/api/status":
            mt5_info = get_mt5_data()
            if STATE_FILE.exists():
                try:
                    with open(STATE_FILE, "r", encoding="utf-8") as f:
                        file_state = json.load(f)
                        if "last_signal" in file_state:
                            GLOBAL_STATE["vps_master"]["last_signal"] = file_state["last_signal"]
                except Exception:
                    pass

            response_data = {
                "status": "ok",
                "account": mt5_info,
                "positions": mt5_info.get("positions", []),
                "master": GLOBAL_STATE["vps_master"],
                "gold_price": GLOBAL_STATE["gold_price"],
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.send_json(response_data)
            return

        # 3. API: SAHAM IDX
        elif path == "/api/stocks":
            self.send_json(get_stock_data())
            return

        # 4. API: FOREX & MT5
        elif path == "/api/forex":
            mt5_info = get_mt5_data()
            gold_signals = get_signals_history(category="gold", limit=20)
            self.send_json({
                "account": mt5_info,
                "positions": mt5_info.get("positions", []),
                "signals": gold_signals.get("signals", []),
                "master": GLOBAL_STATE["vps_master"],
                "gold_price": mt5_info.get("gold_price", GLOBAL_STATE["gold_price"])
            })
            return

        # 5. API: CRYPTO AUTO-PUMP SNIPER
        elif path == "/api/crypto":
            self.send_json(get_crypto_data())
            return

        # 5b. API: CRYPTO LIVE REAL-TIME FEED (0ms MEMORY)
        elif path == "/api/crypto/live":
            self.send_json(get_crypto_live_feed())
            return

        # 5c. API: CRYPTO REAL-TIME KLINES CANDLESTICK DATA FOR CHART
        elif path == "/api/crypto/klines":
            symbol = qs.get("symbol", ["DOGEUSDT"])[0]
            interval = qs.get("interval", ["1m"])[0]
            limit = int(qs.get("limit", [50])[0])
            self.send_json(get_crypto_klines(symbol=symbol, interval=interval, limit=limit))
            return

        # 5d. API: BINANCE FUTURES LIVE DATA (Saldo, Posisi, Order Limit, SL/TP)
        elif path in ("/api/futures", "/api/futures/live"):
            self.send_json(get_futures_dashboard_data())
            return

        # 5e. API ACTION: CANCEL FUTURES LIMIT ORDER
        elif path == "/api/action/futures/cancel":
            sym = qs.get("symbol", [""])[0]
            oid = qs.get("orderId", [""])[0]
            if sym and oid:
                try:
                    import friend_bot_executor_example as fbot, ccxt
                    fbot.setup_binance_dns_bypass()
                    ex = ccxt.binance({"apiKey": fbot.BINANCE_API_KEY, "secret": fbot.BINANCE_API_SECRET, "options": {"defaultType": "future"}})
                    ex.fapiPrivateDeleteOrder({"symbol": sym, "orderId": oid})
                    # Bersihkan juga SL/TP algo order terkait
                    algos = ex.fapiPrivateGetOpenAlgoOrders()
                    for a in algos:
                        if a.get("symbol") == sym:
                            try:
                                ex.fapiPrivateDeleteAlgoOrder({"algoId": a["algoId"]})
                            except Exception:
                                pass
                    with _CACHE_LOCK:
                        _CACHE.pop("futures_dashboard", None)
                    self.send_json({"success": True, "message": f"Order {sym} berhasil dibatalkan"})
                    return
                except Exception as e_cancel:
                    self.send_json({"success": False, "error": str(e_cancel)})
                    return
            self.send_json({"success": False, "error": "Parameter symbol atau orderId kurang"})
            return

        # 6. API: RIWAYAT SINYAL LENGKAP & STATISTIK
        elif path == "/api/signals":
            cat = qs.get("category", ["all"])[0]
            outcome = qs.get("outcome", ["all"])[0]
            limit = int(qs.get("limit", [100])[0])
            self.send_json(get_signals_history(category=cat, outcome_filter=outcome, limit=limit))
            return

        # 7. API: KALENDER EKONOMI
        elif path == "/api/calendar":
            events = get_calendar_events()
            self.send_json({"events": events, "count": len(events)})
            return

        # 8. API: LIVE LOGS
        elif path == "/api/logs":
            lines_cnt = int(qs.get("lines", [150])[0])
            level = qs.get("level", ["ALL"])[0]
            logs = get_live_logs(lines_count=lines_cnt, filter_level=level)
            self.send_json({"logs": logs, "count": len(logs)})
            return

        # 8b. API: NETWORK INFO (UNTUK BUKA DI HP & QR CODE)
        elif path == "/api/network_info":
            s_ip = get_local_ip()
            srv_port = self.server.server_address[1]
            self.send_json({
                "local_ip": s_ip,
                "port": srv_port,
                "local_url": f"http://127.0.0.1:{srv_port}",
                "network_url": f"http://{s_ip}:{srv_port}"
            })
            return

        # 9. Default: Layani file statis (HTML/CSS/JS)
        try:
            super().do_GET()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception:
            pass

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. TRIGGER SCAN MANUAL
        if path == "/api/action/scan":
            run_background_scan()
            self.send_json({"success": True, "message": "Pemindaian watchlist IDX berhasil dijalankan di background!"})
            return

        # 2. TOGGLE / CONFIG CRYPTO
        elif path == "/api/action/crypto_toggle":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body) if body else {}
                new_mode = data.get("mode")
                if new_mode:
                    os.environ["AUTOPUMP_MODE"] = new_mode
                self.send_json({"success": True, "mode": os.getenv("AUTOPUMP_MODE", "real")})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 400)
            return

        # 3. BROADCAST SINYAL UJI (MT5 TEST)
        elif path == "/api/signal":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                sig = json.loads(body)
                now_str = datetime.now().strftime("%H:%M:%S")
                sig["time"] = now_str
                GLOBAL_STATE["vps_master"]["last_signal"] = sig

                if STATE_FILE.parent.exists():
                    with open(STATE_FILE, "w", encoding="utf-8") as f:
                        json.dump({"last_signal": sig, "timestamp": time.time()}, f, indent=2)

                print(f"\n⚡ [BROADCAST TEST] Sinyal Terkirim: {sig.get('action')} {sig.get('symbol')} @ ${sig.get('entry')}")
                self.send_json({"success": True, "signal": sig})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 400)
            return

        # 4. EVENT LOGGING DARI BROWSER
        elif path == "/api/event":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                event = json.loads(body)
                GLOBAL_STATE["recent_logs"].append(event)
                if len(GLOBAL_STATE["recent_logs"]) > 100:
                    GLOBAL_STATE["recent_logs"].pop(0)
                self.send_json({"success": True})
            except Exception:
                self.send_json({"success": False}, 400)
            return

        self.send_response(404)
        self.end_headers()


def kill_process_by_pid(pid: int):
    """Matikan proses lama beserta pohon proses turunannya secara bersih & tuntas."""
    if not pid or pid == os.getpid():
        return
    try:
        import psutil
        p = psutil.Process(pid)
        for child in p.children(recursive=True):
            try:
                child.kill()
            except Exception:
                pass
        p.kill()
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            import subprocess
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=3)
        except Exception:
            pass


def get_pids_listening_on_port(port: int) -> set:
    """Deteksi semua PID yang sedang menduduki port target (via psutil + netstat Windows)."""
    pids = set()
    try:
        import psutil
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                if conn.pid:
                    pids.add(conn.pid)
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            import subprocess
            out = subprocess.check_output(f'netstat -ano | findstr :{port}', shell=True, text=True, stderr=subprocess.DEVNULL)
            for line in out.strip().splitlines():
                parts = line.split()
                if len(parts) >= 5 and "LISTENING" in parts[3].upper() and parts[1].endswith(f":{port}"):
                    try:
                        pids.add(int(parts[4]))
                    except (ValueError, IndexError):
                        pass
        except Exception:
            pass
    return pids


def ensure_port_available(port: int = 8080):
    """
    Pastikan port 8080 benar-benar bebas dari proses zombie/lama sebelum server baru bind.
    Jika ada instance python/dashboard_server lama yang masih nyangkut, matikan otomatis.
    """
    curr_pid = os.getpid()
    parent_pid = None
    try:
        import psutil
        parent_pid = psutil.Process(curr_pid).ppid()
    except Exception:
        pass

    pids = get_pids_listening_on_port(port)
    for pid in pids:
        if pid != curr_pid and pid != parent_pid:
            print(f"[*] Menutup proses server lama di port {port} (PID: {pid})...")
            kill_process_by_pid(pid)
    time.sleep(0.3)


class RobustThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        exc_type, _, _ = sys.exc_info()
        if exc_type in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        super().handle_error(request, client_address)


def bind_server_socket(port: int = 8080, max_retries: int = 10) -> tuple:
    """
    Koneksikan RobustThreadingHTTPServer ke port yang ditentukan secara konsisten.
    Menjamin port 8080 TIDAK PERNAH drift/berpindah ke 8081/8082 meskipun server baru saja dimatikan.
    """
    curr_pid = os.getpid()
    parent_pid = None
    try:
        import psutil
        parent_pid = psutil.Process(curr_pid).ppid()
    except Exception:
        pass

    for attempt in range(1, max_retries + 1):
        # 1. Bersihkan proses lain yang menduduki port jika ada
        pids = get_pids_listening_on_port(port)
        for pid in pids:
            if pid != curr_pid and pid != parent_pid:
                print(f"[*] Menutup proses zombie di port {port} (PID: {pid}) [Percobaan {attempt}/{max_retries}]...")
                kill_process_by_pid(pid)

        # 2. Coba bind ke 0.0.0.0, lalu fallback 127.0.0.1
        for host in ["0.0.0.0", "127.0.0.1"]:
            try:
                httpd = RobustThreadingHTTPServer((host, port), DashboardRequestHandler)
                return httpd, port
            except OSError:
                continue

        # Beri jeda agar Windows TCP stack melepas socket TIME_WAIT
        time.sleep(0.5)

    # Upaya terakhir dengan jeda 1 detik
    time.sleep(1.0)
    httpd = RobustThreadingHTTPServer(("0.0.0.0", port), DashboardRequestHandler)
    return httpd, port


def run_server():
    # Jalankan live crypto ticker thread (1.0s interval)
    t_ticker = threading.Thread(target=_crypto_live_worker, daemon=True)
    t_ticker.start()

    # Otomatis aktifkan AutoPumpSniper HANYA jika main.py TIDAK sedang berjalan
    try:
        if os.getenv("AUTOPUMP_AUTO_START", "false").lower() in ("true", "1"):
            import psutil
            curr_pid = os.getpid()
            main_bot_running = False
            for p in psutil.process_iter(["name", "cmdline", "pid"]):
                if p.info["pid"] != curr_pid:
                    cmd = p.info.get("cmdline") or []
                    if any("main.py" in str(arg) for arg in cmd):
                        main_bot_running = True
                        break
            if not main_bot_running:
                from crypto.auto_pump import AutoPumpSniper
                crypto_sniper = AutoPumpSniper.get_instance()
                crypto_sniper.set_enabled(True)
                print(f"✓ Live Crypto Sniper   : Otomatis Aktif di Background ({crypto_sniper.mode.upper()} Mode)")
            else:
                print("✓ Live Crypto Sniper   : Dikelola oleh main.py Engine (Standalone Dashboard)")
    except Exception as ex_pump:
        print(f"⚠ Gagal start AutoPumpSniper di dashboard: {ex_pump}")

    env_port = os.getenv("PORT")
    target_port = int(env_port) if env_port and env_port.isdigit() else 8080
    local_ip = get_local_ip()

    httpd, port = bind_server_socket(target_port)

    local_url = f"http://127.0.0.1:{port}"
    network_url = f"http://{local_ip}:{port}"

    print("=" * 76)
    print("🚀 BOTRADING UNIFIED WEB DASHBOARD SERVER (v2.0)")
    print("=" * 76)
    print(f"✓ Akses di PC Lokal    : {local_url}")
    print(f"✓ Akses via HP / WiFi  : {network_url}")
    print(f"✓ Direktori Aset Web   : {DASHBOARD_DIR}")
    print(f"✓ Live MT5 Bridge      : Otomatis Terhubung ke MetaTrader 5")
    print(f"✓ Live Crypto Sniper   : Terhubung ke Binance Spot & SQLite Tracker")
    print(f"✓ Live IDX Stock Scan  : Terhubung ke Database SQLite & Watchlist")
    print("=" * 76)
    print("Tekan Ctrl + C di jendela ini untuk mematikan dashboard server.\n")

    # Buka browser otomatis di PC
    threading.Timer(1.2, lambda: webbrowser.open(local_url)).start()

    while True:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[!] Dashboard server dihentikan.")
            try:
                httpd.server_close()
            except Exception:
                pass
            break
        except Exception as e:
            print(f"[!] Server serve_forever exception: {e}")
            time.sleep(1.0)


if __name__ == "__main__":
    try:
        run_server()
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            with open("server_crash.log", "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now()}] CRASH: {e}\n{traceback.format_exc()}\n")
        except Exception:
            pass
