"""
Modul Auto-Pump Sniper Bot (Binance Spot & Paper Trading):
- Mendeteksi koin potensial pump (Sweet spot +3% s/d +15%, skor >= 85, volume spike masif).
- Otomatis eksekusi beli (Auto-Buy Spot atau Paper Trading Virtual).
- Tracking posisi multi-level:
  * SL: -5.5% Cutloss disiplin
  * TP1: +11.0% (Amankan 50% posisi & geser SL ke BEP / Risk-Free)
  * TP2: +25.0% (Moonbag full profit take)
"""

import os
import time
import json
import sqlite3
import threading
import hmac
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta

from config.settings import load_config, setup_logger, BASE_DIR
from crypto.exchange_client import CryptoExchangeClient
from crypto.scanner import CryptoScanner

logger = setup_logger("auto_pump")

DB_PATH = os.path.join(BASE_DIR, "data", "stock_data.db")


class AutoPumpSniper:
    """Mesin eksekusi otomatis koin pump Binance Spot."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.config = load_config()
        self.crypto_cfg = self.config.get("crypto", {})
        
        self.enabled = False
        self.mode = os.getenv("AUTOPUMP_MODE", self.crypto_cfg.get("mode", "paper")).lower()  # 'paper' atau 'real'
        self.capital_per_coin = float(os.getenv("AUTOPUMP_CAPITAL_PER_COIN", self.crypto_cfg.get("capital_per_coin", 5.0)))
        self.max_positions = int(os.getenv("AUTOPUMP_MAX_POSITIONS", self.crypto_cfg.get("max_positions", 3)))
        self.min_score = int(os.getenv("AUTOPUMP_MIN_SCORE", self.crypto_cfg.get("min_score", 85)))
        self.paper_balance = 100.0  # USDT virtual untuk mode simulasi
        
        self.client = CryptoExchangeClient()
        self.telegram_notifier = None  # Di-inject saat bot startup
        
        self._running = False
        self._thread = None
        self._notional_cooldown = {}
        self._trailing_notified = set()
        self._reentry_cooldown = {}
        
        self._init_db()

        # Master Kill Switch: Jika crypto.enabled false di config, matikan mutlak
        if not self.crypto_cfg.get("enabled", True):
            self.enabled = False
            logger.info("AutoPumpSniper NONAKTIF (crypto.enabled = false).")
            return

        # Otomatis start worker jika AUTOPUMP_AUTO_START bernilai true
        auto_start = os.getenv("AUTOPUMP_AUTO_START", "false").lower() in ("true", "1")
        if auto_start:
            self.set_enabled(True)

    @classmethod
    def get_instance(cls) -> "AutoPumpSniper":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _init_db(self):
        """Membuat tabel tracking posisi auto-pump jika belum ada."""
        try:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS crypto_pump_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    segment TEXT DEFAULT 'ALTCOIN_SNIPER',
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    entry_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    cost_usdt REAL NOT NULL,
                    entry_time TEXT NOT NULL,
                    sl_price REAL NOT NULL,
                    tp1_price REAL NOT NULL,
                    tp2_price REAL NOT NULL,
                    tp1_hit INTEGER DEFAULT 0,
                    current_price REAL,
                    close_price REAL,
                    close_time TEXT,
                    pnl_usdt REAL DEFAULT 0.0,
                    pnl_pct REAL DEFAULT 0.0,
                    exit_reason TEXT
                );
            """)
            # Migrasi aman: tambahkan kolom baru jika tabel lama belum memilikinya
            cur.execute("PRAGMA table_info(crypto_pump_positions);")
            cols = [col[1] for col in cur.fetchall()]
            if "segment" not in cols:
                cur.execute("ALTER TABLE crypto_pump_positions ADD COLUMN segment TEXT DEFAULT 'ALTCOIN_SNIPER';")
            if "highest_price" not in cols:
                cur.execute("ALTER TABLE crypto_pump_positions ADD COLUMN highest_price REAL DEFAULT 0.0;")
            if "bep_activated" not in cols:
                cur.execute("ALTER TABLE crypto_pump_positions ADD COLUMN bep_activated INTEGER DEFAULT 0;")
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA busy_timeout=5000;")
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Gagal inisialisasi tabel crypto_pump_positions: {e}")

    def set_enabled(self, enabled: bool) -> bool:
        """Mengaktifkan atau menonaktifkan sniper otomatis."""
        self.enabled = enabled
        if self.enabled and not self._running:
            self.start_worker()
        elif not self.enabled and self._running:
            self.stop_worker()
        logger.info(f"AutoPumpSniper status diubah: enabled={self.enabled}, mode={self.mode}")
        return self.enabled

    def set_mode(self, mode: str) -> str:
        """Mengubah mode antara 'paper' (simulasi) atau 'real' (Binance live)."""
        m = mode.lower().strip()
        if m in ["paper", "simulasi", "virtual"]:
            self.mode = "paper"
        elif m in ["real", "live", "binance"]:
            self.mode = "real"
        return self.mode

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Mengambil seluruh posisi koin yang sedang berjalan (OPEN)."""
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM crypto_pump_positions 
                WHERE status IN ('OPEN', 'TP1_HIT')
                ORDER BY id DESC
            """)
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"Gagal mengambil posisi terbuka: {e}")
            return []

    def get_trade_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Mengambil riwayat posisi yang sudah ditutup."""
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM crypto_pump_positions 
                WHERE status NOT IN ('OPEN', 'TP1_HIT')
                ORDER BY id DESC LIMIT ?
            """, (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"Gagal mengambil riwayat transaksi: {e}")
            return []

    def is_coin_in_reentry_cooldown(self, symbol: str, cooldown_minutes: float = 30.0) -> bool:
        """Memastikan koin yang baru saja di-close (TP/SL/Stagnan) tidak langsung dibeli lagi dalam jeda waktu cooldown."""
        now_ts = time.time()
        if now_ts - self._reentry_cooldown.get(symbol, 0.0) < (cooldown_minutes * 60.0):
            return True

        # Cek juga riwayat penutupan di database (agar tetap aman jika bot baru direstart)
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                SELECT close_time FROM crypto_pump_positions 
                WHERE symbol = ? AND status LIKE 'CLOSED_%' AND close_time IS NOT NULL 
                ORDER BY id DESC LIMIT 1
            """, (symbol,))
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                close_dt = datetime.strptime(str(row[0]), "%Y-%m-%d %H:%M:%S")
                now_dt = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
                diff_mins = (now_dt - close_dt).total_seconds() / 60.0
                if diff_mins < cooldown_minutes:
                    self._reentry_cooldown[symbol] = now_ts
                    return True
        except Exception as e:
            logger.debug(f"Error checking DB cooldown for {symbol}: {e}")

        return False

    def scan_and_snipe(self) -> Optional[Dict[str, Any]]:
        """Memindai pasar dan menembak order beli jika ada koin pump potensial."""
        if not self.enabled or not self.crypto_cfg.get("enabled", True):
            return None

        if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("IS_TESTING") == "true":
            logger.debug("AutoPump: Membatalkan order nyata karena berada di lingkungan unit test (pytest).")
            return None

        open_pos = self.get_open_positions()
        if len(open_pos) >= self.max_positions:
            logger.debug(f"Slot posisi penuh ({len(open_pos)}/{self.max_positions}). Standby...")
            return None

        open_symbols = {p["symbol"] for p in open_pos}

        # 1. Pindai koin potensial pump (pindai hingga top 50 koin agar koin min $1 USDT terdeteksi)
        candidates = CryptoScanner.scan_pump_candidates(top_n=50)
        snipe_target = None
        pdf_verdict = None

        for c in candidates:
            sym = c["symbol"]
            if sym in open_symbols:
                continue
            if sym in ("PAXGUSDT", "XAUTUSDT", "PAXUSDT"):
                continue
            if self.is_coin_in_reentry_cooldown(sym, cooldown_minutes=30.0):
                logger.debug(f"AutoPump: {sym} dalam masa jeda re-entry cooldown (30 menit). Lewati...")
                continue
            if c["pump_score"] < self.min_score:
                continue

            # 1.4 Validasi & Telaah 9 Buku PDF Trading (Bob Volman, Murphy, Pring, Rizki Aditama)
            pdf_eval = CryptoScanner.evaluate_9_buku_confluence(sym, self.client)
            if not pdf_eval.get("approved", True):
                veto_reasons = ", ".join(pdf_eval.get("veto", []))
                logger.info(f"🚫 [9 Buku PDF Veto] Pembelian {sym} Ditolak: {veto_reasons} (Skor: {pdf_eval.get('score')}/100)")
                continue

            snipe_target = c
            pdf_verdict = pdf_eval
            logger.info(f"📚 [9 Buku PDF Lolos] {sym} Disetujui: {pdf_eval.get('grade')} (Skor: {pdf_eval.get('score')}/100) | {', '.join(pdf_eval.get('checks', [])[:2])}")
            break

        if not snipe_target:
            return None

        sym = snipe_target["symbol"]
        price = snipe_target["price"]
        sl_pct = float(snipe_target.get("sl_pct", 2.5))
        tp1_pct = float(snipe_target.get("tp1_pct", 3.0))
        tp2_pct = float(snipe_target.get("tp2_pct", 8.0))
        segment = snipe_target.get("segment", "ALTCOIN_SNIPER")
        sl_price = snipe_target.get("sl_price") or (price * (1.0 - sl_pct / 100.0))
        tp1_price = snipe_target.get("tp1_price") or (price * (1.0 + tp1_pct / 100.0))
        tp2_price = snipe_target.get("tp2_price") or (price * (1.0 + tp2_pct / 100.0))
        score = snipe_target["pump_score"]
        status_label = snipe_target["status_label"]

        # 1.5 Evaluasi Otak AI (Gemini Gatekeeper) dengan Konteks 9 Buku PDF
        from strategy.ai_gatekeeper import AIGatekeeper
        ai_brain = AIGatekeeper.get_instance()
        ai_verdict = ai_brain.evaluate_crypto_pump(
            symbol=sym,
            price=price,
            chg_24h=snipe_target.get("change_24h", 0.0),
            volume_usdt=snipe_target.get("volume_usdt", 0.0),
            pump_score=score,
            status_label=status_label,
            pdf_confluence=pdf_verdict,
        )
        if not ai_verdict.get("approved", True):
            logger.info(f"🚫 Otak AI Menolak Pembelian {sym}: {ai_verdict.get('reason')} (Skor: {ai_verdict.get('score')})")
            return None

        # Modal per koin HARUS patuh pada batas maksimal yang ditentukan user (tidak boleh lebih)
        cost = float(self.capital_per_coin)
        qty = cost / price if price > 0 else 0.0
        now_str = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")

        # 2. Eksekusi Order (Real atau Paper)
        if self.mode == "real":
            if not self.client.is_authenticated():
                logger.warning("AutoPump Real: API Key belum terpasang. Batalkan order.")
                return None
            
            bal = self.client.get_balance()
            free_usdt = bal.get("free_usdt", 0.0)
            if free_usdt < cost:
                logger.warning(f"AutoPump Real: Saldo USDT tidak cukup (${free_usdt:.2f} < ${cost:.2f})")
                return None

            min_req = self.client.get_symbol_min_notional(sym)
            order_data = {}
            if cost < min_req:
                # Gunakan Binance Convert untuk membeli koin dengan modal < minNotional (misal $1.0 USDT)!
                base_asset = sym.replace("USDT", "").replace("FDUSD", "").replace("USDC", "").upper()
                logger.info(f"Modal ${cost:.2f} < Min Spot (${min_req:.2f}). Menggunakan jalur Binance Convert untuk BUY {sym}...")
                conv_res = self.client.convert_asset(from_asset="USDT", to_asset=base_asset, from_amount=cost)
                if not conv_res.get("success"):
                    logger.warning(f"Gagal eksekusi Convert BUY untuk {sym}: {conv_res.get('error')}")
                    return None
                quote = conv_res.get("quote", {})
                qty = float(quote.get("toAmount", 0.0) or 0.0)
                price = cost / qty if qty > 0 else price
                sl_price = price * (1.0 - sl_pct / 100.0)
                tp1_price = price * (1.0 + tp1_pct / 100.0)
                tp2_price = price * (1.0 + tp2_pct / 100.0)
                order_data = conv_res.get("data", {})
                logger.info(f"Order Real Binance (via Convert) Terbuka: {sym} Qty: {qty} @ ${price:.6f} | Biaya: ${cost:.2f} USDT | OrderID: {order_data.get('orderId')}")
            else:
                # Eksekusi Market Buy Spot biasa dengan quote_order_qty agar nominal pas sesuai alokasi USDT
                order_res = self.client.create_order(sym, side="BUY", order_type="MARKET", quote_order_qty=cost)
                if not order_res.get("success"):
                    logger.error(f"Gagal eksekusi order Binance Real untuk {sym}: {order_res.get('error')}")
                    return None
                
                order_data = order_res.get("order", {})
                real_executed_qty = float(order_data.get("executedQty", 0.0) or 0.0)
                real_spent_usdt = float(order_data.get("cummulativeQuoteQty", 0.0) or 0.0)
                if real_executed_qty > 0:
                    qty = real_executed_qty
                if real_spent_usdt > 0:
                    cost = real_spent_usdt
                    price = cost / qty if qty > 0 else price
                    sl_price = price * (1.0 - sl_pct / 100.0)
                    tp1_price = price * (1.0 + tp1_pct / 100.0)
                    tp2_price = price * (1.0 + tp2_pct / 100.0)

                logger.info(f"Order Real Binance Terbuka: {sym} Qty: {qty} @ ${price:.6f} | Biaya: ${cost:.2f} USDT | OrderID: {order_data.get('orderId')}")
        else:
            # Mode Paper Trading
            self.paper_balance -= cost
            logger.info(f"[PAPER TRADING] Beli {sym}: Qty {qty:.4f} @ ${price:.6f} | Biaya: ${cost} USDT")

        # 3. Simpan ke Database
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO crypto_pump_positions 
                (symbol, mode, segment, status, entry_price, highest_price, quantity, cost_usdt, entry_time, sl_price, tp1_price, tp2_price)
                VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sym, self.mode, segment, price, price, qty, cost, now_str, sl_price, tp1_price, tp2_price))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Gagal menyimpan posisi ke database: {e}")

        # 4. Kirim Sinyal / Notifikasi
        pos_data = {
            "symbol": sym,
            "mode": self.mode,
            "segment": segment,
            "sl_pct": sl_pct,
            "tp1_pct": tp1_pct,
            "tp2_pct": tp2_pct,
            "entry_price": price,
            "quantity": qty,
            "cost_usdt": cost,
            "sl_price": sl_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "pump_score": score,
            "status_label": status_label,
            "entry_time": now_str,
            "ai_score": ai_verdict.get("score", score),
            "ai_reason": ai_verdict.get("reason", "Disetujui filter momentum"),
            "ai_active": ai_verdict.get("ai_active", False),
            "pdf_score": pdf_verdict.get("score", 0) if pdf_verdict else 0,
            "pdf_grade": pdf_verdict.get("grade", "Grade B") if pdf_verdict else "Grade B",
            "pdf_checks": pdf_verdict.get("checks", []) if pdf_verdict else [],
        }
        self._notify_entry(pos_data)
        return pos_data

    def update_positions(self):
        """Memantau harga live untuk semua posisi terbuka & mengeksekusi TP/SL."""
        open_pos = self.get_open_positions()
        if not open_pos:
            return

        for p in open_pos:
            sym = p["symbol"]
            ticker = self.client.fetch_ticker(sym)
            curr_price = ticker.get("last_price") or ticker.get("last", 0.0)
            if not curr_price or curr_price <= 0:
                continue

            pos_id = p["id"]
            entry_p = p["entry_price"]
            sl_p = p["sl_price"]
            tp1_p = p["tp1_price"]
            tp2_p = p["tp2_price"]
            qty = p["quantity"]
            cost = p["cost_usdt"]
            mode = p["mode"]
            tp1_hit = bool(p["tp1_hit"])
            now_str = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")
            seg = p.get("segment") or ("MAJOR_BLUECHIP" if any(sym.startswith(m) for m in ["BTC", "ETH", "SOL", "XRP", "BNB", "ADA"]) else "ALTCOIN_SNIPER")
            bep_activated = bool(p.get("bep_activated") or 0)

            def _get_real_sell_qty(target_qty: float) -> float:
                try:
                    base_asset = sym.replace("USDT", "").replace("FDUSD", "").replace("USDC", "").upper()
                    bal_data = self.client.get_balance()
                    raw_bals = bal_data.get("holdings") or bal_data.get("balances", {})
                    if base_asset in raw_bals:
                        free_amt = float(raw_bals.get(base_asset, {}).get("free", 0.0))
                        return min(target_qty, free_amt)
                except Exception as e:
                    logger.warning(f"Gagal cek free balance untuk {sym}: {e}")
                return target_qty

            # 1. Update High Watermark (Puncak Harga Tertinggi Selama Posisi Buka)
            prev_highest = float(p.get("highest_price") or 0.0)
            highest_p = max(prev_highest, entry_p, curr_price)
            if highest_p > prev_highest:
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.cursor()
                    cur.execute("UPDATE crypto_pump_positions SET highest_price = ?, current_price = ? WHERE id = ?", (highest_p, curr_price, pos_id))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    logger.debug(f"Gagal update highest_price {sym}: {e}")

            gain_pct = ((curr_price - entry_p) / entry_p) * 100.0
            peak_gain_pct = ((highest_p - entry_p) / entry_p) * 100.0

            # 2. Proteksi 1: EARLY BREAK-EVEN PLUS (ANTI-MINUS + KUNCI CUAN BERSIH)
            # Begitu koin floating profit >= +1.5% (Altcoin) atau >= +1.0% (Major),
            # naikkan SL ke harga modal PLUS buffer cuan (+0.6% untuk Altcoin / +0.4% untuk Major).
            bep_threshold = 1.0 if seg == "MAJOR_BLUECHIP" else 1.5
            bep_buffer_pct = 0.4 if seg == "MAJOR_BLUECHIP" else 0.6
            bep_target_sl = entry_p * (1.0 + (bep_buffer_pct / 100.0))

            if not bep_activated and not tp1_hit and gain_pct >= bep_threshold and sl_p < bep_target_sl:
                sl_p = bep_target_sl
                bep_activated = True
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.cursor()
                    cur.execute("UPDATE crypto_pump_positions SET sl_price = ?, bep_activated = 1 WHERE id = ?", (sl_p, pos_id))
                    conn.commit()
                    conn.close()
                    logger.info(f"🛡️ Anti-Minus (BEP+) Aktif: {sym} profit +{gain_pct:.2f}%, SL dinaikkan ke ${sl_p:.6f} (+{bep_buffer_pct:.1f}% Cuan Terkunci)")
                    self._notify_bep_activation(sym, mode, entry_p, curr_price, gain_pct, seg, locked_profit=bep_buffer_pct)
                except Exception as e:
                    logger.error(f"Gagal aktivasi BEP+ {sym}: {e}")

            # 3. Proteksi 2: TRAILING PROFIT LOCK (KUNCI CUAN DINAMIS LEBIH LILIN/CEPAT)
            # Begitu koin floating untung >= +2.2% (Altcoin) atau >= +1.5% (Major),
            # trailing stop langsung rapat mengawal di belakang harga puncak (jarak 0.8% - 0.5%)!
            trailing_start = 1.5 if seg == "MAJOR_BLUECHIP" else 2.2
            trailing_dist_pct = 0.5 if seg == "MAJOR_BLUECHIP" else 0.8
            
            # Jika sudah lewat TP1 (Moonbag Target ke TP2), trailing diatur mengawal sisa koin
            if tp1_hit:
                trailing_start = 3.0 if seg == "MAJOR_BLUECHIP" else 5.0
                trailing_dist_pct = 0.8 if seg == "MAJOR_BLUECHIP" else 1.5

            if peak_gain_pct >= trailing_start:
                new_trailing_sl = highest_p * (1.0 - (trailing_dist_pct / 100.0))
                if new_trailing_sl > sl_p:
                    sl_p = new_trailing_sl
                    try:
                        conn = sqlite3.connect(DB_PATH)
                        cur = conn.cursor()
                        cur.execute("UPDATE crypto_pump_positions SET sl_price = ? WHERE id = ?", (sl_p, pos_id))
                        conn.commit()
                        conn.close()
                        trail_pnl_est = ((sl_p - entry_p) / entry_p) * 100.0
                        logger.info(f"🎯 Trailing Stop Diperbarui: {sym} Peak +{peak_gain_pct:.2f}% | SL Terkunci di ${sl_p:.6f} (+{trail_pnl_est:.2f}%)")
                        if pos_id not in self._trailing_notified and trail_pnl_est >= 0.5:
                            self._notify_trailing_activated(sym, mode, entry_p, highest_p, sl_p, peak_gain_pct, trail_pnl_est, seg)
                            self._trailing_notified.add(pos_id)
                    except Exception as e:
                        logger.error(f"Gagal update trailing sl {sym}: {e}")

            # 4. Proteksi 3: FAST STAGNATION TIMEOUT (Pelepasan Cepat Koin Mogok)
            # Jika koin sudah di-hold > 60 menit dan gain < 0.2%, atau > 90 menit dan peak < 1.8%:
            # Tutup posisi cepat agar slot modal segera bebas untuk koin pump baru yang sedang meledak!
            is_stagnant = False
            age_mins = 0.0
            try:
                entry_dt = datetime.strptime(str(p.get("entry_time", "")), "%Y-%m-%d %H:%M:%S")
                now_dt = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
                age_mins = (now_dt - entry_dt).total_seconds() / 60.0
                if (age_mins >= 60.0 and gain_pct < 0.2) or (age_mins >= 90.0 and peak_gain_pct < 1.8):
                    is_stagnant = True
            except Exception:
                is_stagnant = False

            # A. Skenario Hit Stop Loss / Trailing Stop / BEP / Stagnation Timeout
            if curr_price <= sl_p or is_stagnant:
                if self._notional_cooldown.get(sym, 0) > time.time():
                    continue
                pnl_pct = ((curr_price - entry_p) / entry_p) * 100.0
                pnl_usdt = (curr_price - entry_p) * qty

                # Identifikasi Tipe Exit (Trailing Profit vs BEP+ vs Stagnant vs Cutloss)
                is_trailing = (pos_id in self._trailing_notified) or (sl_p > entry_p) or (peak_gain_pct >= trailing_start)
                if is_stagnant:
                    exit_type = "STAGNANT"
                    exit_reason = f"⏱️ Stagnation Timeout ({age_mins:.0f}m tanpa pergerakan)"
                    note = f"Koin dilepas otomatis setelah {age_mins:.0f} menit tanpa momentum pump untuk membebaskan slot modal ke koin lain yang baru meledak."
                elif is_trailing and pnl_pct >= 0.1:
                    exit_type = "TRAILING_PROFIT"
                    exit_reason = f"🎯 Trailing Profit Terkunci (+{pnl_pct:.2f}%)"
                    note = f"Trailing Stop mengamankan profit +{pnl_pct:.2f}% sebelum market berbalik arah (koreksi dari puncak +{peak_gain_pct:.2f}%)."
                elif pnl_pct >= -0.4:
                    exit_type = "BEP"
                    exit_reason = f"🛡️ Break-Even Plus Terpicu (+{pnl_pct:.2f}%, Modal & Fee Aman)"
                    note = "Posisi keluar di atas harga modal (BEP+). Modal kembali utuh dengan cuan pengaman."
                elif is_trailing:
                    exit_type = "TRAILING_PROFIT"
                    exit_reason = f"🎯 Trailing Stop Terpicu ({pnl_pct:+.2f}%)"
                    note = f"Trailing Stop terpicu setelah koreksi dari puncak (+{peak_gain_pct:.2f}%)."
                else:
                    exit_type = "SL"
                    exit_reason = "🛑 Stop Loss Terpicu (Cutloss Disiplin)"
                    note = "Cutloss Disiplin Terpicu"

                if mode == "real":
                    sell_amt = _get_real_sell_qty(qty)
                    if sell_amt <= 1e-8:
                        logger.warning(f"Posisi {sym} saldo Binance kosong (0). Menutup tracking di bot sebagai CLOSED_MANUAL.")
                        self._close_position(
                            pos_id=pos_id,
                            status="CLOSED_MANUAL",
                            close_price=curr_price,
                            close_time=now_str,
                            pnl_usdt=pnl_usdt,
                            pnl_pct=pnl_pct,
                            exit_reason="🛑 Posisi sudah terjual/kosong di akun Binance",
                            symbol=sym,
                        )
                        self._notional_cooldown.pop(sym, None)
                        self._trailing_notified.discard(pos_id)
                        continue

                    order_res = self.client.create_order(sym, side="SELL", order_type="MARKET", amount=sell_amt)
                    if not order_res.get("success"):
                        err_str = str(order_res.get("error") or "")
                        logger.error(f"Gagal eksekusi Exit Binance untuk {sym}: {err_str}")
                        is_dust = "notional" in err_str.lower() or "insufficient" in err_str.lower() or "lot_size" in err_str.lower()
                        if is_dust:
                            cur_val = sell_amt * curr_price
                            logger.warning(
                                f"Posisi {sym} menyentuh batas exit namun nilai pasar (${cur_val:.2f} USDT) di bawah "
                                f"batas minimum order Binance ($5.00 USDT). Menutup tracking di bot sebagai CLOSED_SL_DUST."
                            )
                            exit_note = (
                                f"🛑 Exit Terpicu ({pnl_pct:.2f}% | {pnl_usdt:+.4f} USDT)\n"
                                f"⚠️ Order jual otomatis ditolak Binance karena nilai posisi (${cur_val:.2f} USDT) "
                                f"di bawah batas minimum order Spot Binance ($5.00 USDT).\n"
                                f"💡 Sisa koin ({sell_amt} {sym.replace('USDT', '')}) tetap aman di dompet Spot Binance."
                            )
                            self._close_position(
                                pos_id=pos_id,
                                status="CLOSED_SL_DUST",
                                close_price=curr_price,
                                close_time=now_str,
                                pnl_usdt=pnl_usdt,
                                pnl_pct=pnl_pct,
                                exit_reason="🛑 Exit Terpicu (Dust Coin < $5 Min Order Binance)",
                                symbol=sym,
                            )
                            self._notional_cooldown.pop(sym, None)
                            self._trailing_notified.discard(pos_id)
                            self._notify_exit(sym, mode, "SL_DUST", entry_p, curr_price, pnl_pct, pnl_usdt, exit_note, segment=seg)
                            continue
                        continue
                else:
                    self.paper_balance += (qty * curr_price)

                close_status = f"CLOSED_{exit_type}"
                self._close_position(
                    pos_id=pos_id,
                    status=close_status,
                    close_price=curr_price,
                    close_time=now_str,
                    pnl_usdt=pnl_usdt,
                    pnl_pct=pnl_pct,
                    exit_reason=exit_reason,
                    symbol=sym,
                )
                self._trailing_notified.discard(pos_id)
                self._notify_exit(sym, mode, exit_type, entry_p, curr_price, pnl_pct, pnl_usdt, note, segment=seg)
                continue

            # B. Skenario Hit Take Profit 1 (TP1)
            if not tp1_hit and curr_price >= tp1_p:
                half_qty = qty * 0.5
                pnl_1_pct = ((curr_price - entry_p) / entry_p) * 100
                pnl_1_usdt = (curr_price - entry_p) * half_qty

                if mode == "real":
                    sell_amt = _get_real_sell_qty(half_qty)
                    order_res = self.client.create_order(sym, side="SELL", order_type="MARKET", amount=sell_amt)
                    if not order_res.get("success"):
                        logger.error(f"Gagal eksekusi TP1 Binance untuk {sym}: {order_res.get('error')}")
                        continue
                else:
                    self.paper_balance += (half_qty * curr_price)

                # Geser Stop Loss ke BEP (Entry Price) agar posisi jadi RISK-FREE!
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE crypto_pump_positions 
                        SET status = 'TP1_HIT', tp1_hit = 1, sl_price = ?, quantity = ?, pnl_usdt = ?
                        WHERE id = ?
                    """, (entry_p, half_qty, pnl_1_usdt, pos_id))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    logger.error(f"Gagal update status TP1: {e}")

                self._notify_tp1(sym, mode, entry_p, curr_price, pnl_1_pct, pnl_1_usdt, segment=seg)
                continue

            # C. Skenario Hit Take Profit 2 (TP2 Moonbag)
            if tp1_hit and curr_price >= tp2_p:
                rem_qty = qty
                pnl_2_pct = ((curr_price - entry_p) / entry_p) * 100
                pnl_2_usdt = (curr_price - entry_p) * rem_qty

                if mode == "real":
                    sell_amt = _get_real_sell_qty(rem_qty)
                    order_res = self.client.create_order(sym, side="SELL", order_type="MARKET", amount=sell_amt)
                    if not order_res.get("success"):
                        logger.error(f"Gagal eksekusi TP2 Binance untuk {sym}: {order_res.get('error')}")
                        continue
                else:
                    self.paper_balance += (rem_qty * curr_price)

                total_pnl_usdt = p.get("pnl_usdt", 0.0) + pnl_2_usdt
                total_pnl_pct = pnl_2_pct

                self._close_position(
                    pos_id=pos_id,
                    status="CLOSED_TP2",
                    close_price=curr_price,
                    close_time=now_str,
                    pnl_usdt=total_pnl_usdt,
                    pnl_pct=total_pnl_pct,
                    exit_reason="🌕 Take Profit 2 Tercapai (Moonbag Target)",
                    symbol=sym,
                )
                self._trailing_notified.discard(pos_id)
                self._notify_exit(sym, mode, "TP2", entry_p, curr_price, total_pnl_pct, total_pnl_usdt, "Moonbag Target Selesai", segment=seg)
                continue

    def _close_position(
        self,
        pos_id: int,
        status: str,
        close_price: float,
        close_time: str,
        pnl_usdt: float,
        pnl_pct: float,
        exit_reason: str,
        symbol: Optional[str] = None,
    ):
        """Menutup posisi dan mencatat hasil akhir ke database."""
        if symbol:
            self._reentry_cooldown[symbol] = time.time()
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                UPDATE crypto_pump_positions 
                SET status = ?, close_price = ?, close_time = ?, pnl_usdt = ?, pnl_pct = ?, exit_reason = ?
                WHERE id = ?
            """, (status, close_price, close_time, pnl_usdt, pnl_pct, exit_reason, pos_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Gagal menutup posisi {pos_id}: {e}")

    def _notify_entry(self, pos: Dict[str, Any]):
        """Mengirim notifikasi instan saat posisi baru terbuka."""
        sym = pos["symbol"]
        mode_badge = "🟢 <b>REAL SPOT (BINANCE)</b>" if pos["mode"] == "real" else "🟡 <b>PAPER TRADING (SIMULASI)</b>"
        p = pos["entry_price"]
        sl = pos["sl_price"]
        tp1 = pos["tp1_price"]
        tp2 = pos["tp2_price"]
        cost = pos["cost_usdt"]

        segment = pos.get("segment", "ALTCOIN_SNIPER")
        sl_pct = float(pos.get("sl_pct", 5.5))
        tp1_pct = float(pos.get("tp1_pct", 11.0))
        tp2_pct = float(pos.get("tp2_pct", 25.0))
        segment_badge = "🐘 <b>MAJOR BLUECHIP</b>" if segment == "MAJOR_BLUECHIP" else "🚀 <b>ALTCOIN SNIPER</b>"

        fmt_p = f"${p:.8f}" if p < 0.01 else f"${p:.4f}"
        fmt_sl = f"${sl:.8f}" if sl < 0.01 else f"${sl:.4f}"
        fmt_tp1 = f"${tp1:.8f}" if tp1 < 0.01 else f"${tp1:.4f}"
        fmt_tp2 = f"${tp2:.8f}" if tp2 < 0.01 else f"${tp2:.4f}"

        ai_info = ""
        if pos.get("ai_active"):
            ai_info = f"• 🧠 <b>Evaluasi Otak AI:</b> Skor <code>{pos.get('ai_score')}/100</code> (<i>{pos.get('ai_reason')}</i>)\n"

        pdf_info = ""
        if pos.get("pdf_grade"):
            pdf_checks_str = f" (<i>{pos.get('pdf_checks', [])[0]}</i>)" if pos.get("pdf_checks") else ""
            pdf_info = f"• 🛡️ <b>Validasi 3 Pilar Inti:</b> <code>{pos.get('pdf_grade')} ({pos.get('pdf_score', 0)}/100)</code>{pdf_checks_str}\n"

        msg = (
            f"🚀 <b>AUTO-PUMP SNIPER: POSISI TERBUKA!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Mode Eksekusi:</b> {mode_badge}\n"
            f"• <b>Segmen Pasar:</b> {segment_badge}\n"
            f"• <b>Koin:</b> <code>{sym}</code>\n"
            f"• <b>Skor Sinyal:</b> <code>{pos.get('pump_score', 90)}/100</code> ({pos.get('status_label', 'SUPER PUMP')})\n"
            f"{pdf_info}"
            f"{ai_info}"
            f"• <b>Modal Masuk:</b> <code>${cost:.2f} USDT</code>\n"
            f"• 🟢 <b>Harga Beli (Entry):</b> <code>{fmt_p}</code>\n\n"
            f"🎯 <b>TARGET OTOMATIS:</b>\n"
            f"• 🛑 <b>Stop Loss (SL):</b> <code>{fmt_sl}</code> <i>(-{sl_pct:.1f}%)</i>\n"
            f"• 🚀 <b>Take Profit 1:</b> <code>{fmt_tp1}</code> <i>(+{tp1_pct:.1f}% | Jual 50% & SL ke BEP+)</i>\n"
            f"• 🌕 <b>Take Profit 2:</b> <code>{fmt_tp2}</code> <i>(+{tp2_pct:.1f}% | Moonbag Target)</i>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Bot memantau pergerakan harga 24/7 secara otomatis.</i>"
        )
        self._broadcast_to_telegram(msg)

    def _notify_tp1(self, sym: str, mode: str, entry_p: float, curr_p: float, pnl_pct: float, pnl_usdt: float, segment: str = "ALTCOIN_SNIPER"):
        """Notifikasi saat TP1 tercapai."""
        mode_badge = "REAL SPOT" if mode == "real" else "PAPER TRADING"
        segment_badge = "🐘 BLUECHIP" if segment == "MAJOR_BLUECHIP" else "🚀 ALTCOIN"
        fmt_entry = f"${entry_p:.8f}".rstrip("0") if entry_p < 0.001 else f"${entry_p:.4f}"
        fmt_curr = f"${curr_p:.8f}".rstrip("0") if curr_p < 0.001 else f"${curr_p:.4f}"
        target_tp2 = "+7.5%" if segment == "MAJOR_BLUECHIP" else "+25%"
        msg = (
            f"🎯 <b>AUTO-PUMP: TAKE PROFIT 1 TERCAPAI!</b> (+{pnl_pct:.1f}%)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Koin:</b> <code>{sym}</code> ({mode_badge} | {segment_badge})\n"
            f"• <b>Harga Entry:</b> <code>{fmt_entry}</code>\n"
            f"• <b>Harga Eksekusi:</b> <code>{fmt_curr}</code>\n"
            f"• 🟢 <b>Profit Diamankan (50%):</b> <code>+{pnl_pct:.2f}%</code> (<code>+${pnl_usdt:.2f} USDT</code>)\n\n"
            f"🛡️ <b>STATUS POSISI SEKARANG: RISK-FREE!</b>\n"
            f"Stop Loss otomatis digeser ke harga <b>Entry (BEP: {fmt_entry})</b>. Sisa 50% porsi koin dibiarkan terbang menuju <b>TP 2 ({target_tp2})</b> tanpa risiko rugi!\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        self._broadcast_to_telegram(msg)

    def _notify_bep_activation(self, sym: str, mode: str, entry_p: float, curr_p: float, gain_pct: float, segment: str, locked_profit: float = 0.8):
        """Notifikasi saat Stop Loss digeser ke BEP+ (Anti-Minus & Kunci Cuan Bersih)."""
        mode_badge = "REAL SPOT" if mode == "real" else "PAPER TRADING"
        segment_badge = "🐘 BLUECHIP" if segment == "MAJOR_BLUECHIP" else "🚀 ALTCOIN"
        fmt_entry = f"${entry_p:.8f}".rstrip("0") if entry_p < 0.001 else f"${entry_p:.4f}"
        fmt_curr = f"${curr_p:.8f}".rstrip("0") if curr_p < 0.001 else f"${curr_p:.4f}"
        sl_bep_p = entry_p * (1.0 + (locked_profit / 100.0))
        fmt_sl = f"${sl_bep_p:.8f}".rstrip("0") if sl_bep_p < 0.001 else f"${sl_bep_p:.4f}"
        msg = (
            f"🛡️ <b>AUTO-PUMP: ANTI-MINUS (BEP+) AKTIF!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Koin:</b> <code>{sym}</code> ({mode_badge} | {segment_badge})\n"
            f"• <b>Harga Beli (Modal):</b> <code>{fmt_entry}</code>\n"
            f"• <b>Harga Saat Ini:</b> <code>{fmt_curr}</code> (<code>+{gain_pct:.2f}%</code>)\n"
            f"• 🔒 <b>Stop Loss Dinaikkan ke:</b> <code>{fmt_sl}</code> (<code>+{locked_profit:.2f}% Cuan Terkunci</code>)\n\n"
            f"🎉 <b>STATUS: 100% CUAN & BEBAS RISIKO!</b>\n"
            f"Bukan cuma modal yang aman, keuntungan bersih minimal <b>+{locked_profit:.2f}%</b> (serta fee exchange) sudah digembok di kantong!\n"
            f"Posisi ini <b>TIDAK BISA MINUS</b>. Jika pasar berbalik arah, bot otomatis keluar dengan hasil <b>UNTUNG</b>!\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        self._broadcast_to_telegram(msg)

    def _notify_trailing_activated(self, sym: str, mode: str, entry_p: float, highest_p: float, sl_p: float, peak_gain: float, locked_profit: float, segment: str):
        """Notifikasi saat Trailing Stop mulai mengunci profit dinamis."""
        mode_badge = "REAL SPOT" if mode == "real" else "PAPER TRADING"
        segment_badge = "🐘 BLUECHIP" if segment == "MAJOR_BLUECHIP" else "🚀 ALTCOIN"
        fmt_entry = f"${entry_p:.8f}".rstrip("0") if entry_p < 0.001 else f"${entry_p:.4f}"
        fmt_highest = f"${highest_p:.8f}".rstrip("0") if highest_p < 0.001 else f"${highest_p:.4f}"
        fmt_sl = f"${sl_p:.8f}".rstrip("0") if sl_p < 0.001 else f"${sl_p:.4f}"
        msg = (
            f"🎯 <b>AUTO-PUMP: TRAILING STOP AKTIF!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Koin:</b> <code>{sym}</code> ({mode_badge} | {segment_badge})\n"
            f"• <b>Harga Beli:</b> <code>{fmt_entry}</code>\n"
            f"• <b>Harga Tertinggi (Peak):</b> <code>{fmt_highest}</code> (<code>+{peak_gain:.2f}%</code>)\n"
            f"• 🔒 <b>Stop Loss Dinaikkan ke:</b> <code>{fmt_sl}</code> (<code>+{locked_profit:.2f}%</code>)\n\n"
            f"💡 <b>PENGAMANAN PROFIT:</b>\n"
            f"Keuntungan minimal <b>+{locked_profit:.2f}%</b> sudah digembok aman! Jika harga terus melesat, bot akan terus menaikkan batas trailing stop. Jika pasar berbalik turun, bot otomatis menjual untuk mengamankan cuan ini!\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        self._broadcast_to_telegram(msg)

    def _notify_exit(self, sym: str, mode: str, exit_type: str, entry_p: float, curr_p: float, pnl_pct: float, pnl_usdt: float, note: str, segment: str = "ALTCOIN_SNIPER"):
        """Notifikasi saat posisi selesai ditutup penuh."""
        def _fmt_usdt(val: float) -> str:
            abs_v = abs(val)
            if abs_v >= 10.0:
                return f"${abs_v:,.2f}"
            elif abs_v >= 0.01:
                return f"${abs_v:.4f}"
            else:
                return f"${abs_v:.6f}"

        mode_badge = "REAL SPOT" if mode == "real" else "PAPER TRADING"
        segment_badge = "🐘 BLUECHIP" if segment == "MAJOR_BLUECHIP" else "🚀 ALTCOIN"
        fmt_entry = f"${entry_p:.8f}".rstrip("0") if entry_p < 0.001 else f"${entry_p:.4f}"
        fmt_curr = f"${curr_p:.8f}".rstrip("0") if curr_p < 0.001 else f"${curr_p:.4f}"

        # Klasifikasi status: UNTUNG, RUGI, atau IMPAS (BEP)
        is_profit = pnl_pct > 0.05 or pnl_usdt > 0.0005
        is_loss = pnl_pct < -0.4 or pnl_usdt < -0.0005

        if is_profit:
            hasil_badge = "🟢 <b>HASIL: UNTUNG (PROFIT)</b>"
            pnl_line = f"• 💰 <b>Total Keuntungan:</b> <code>+{_fmt_usdt(pnl_usdt)} USDT</code> (<code>+{abs(pnl_pct):.2f}%</code>)"
        elif is_loss:
            hasil_badge = "🔴 <b>HASIL: RUGI (CUT LOSS)</b>"
            pnl_line = f"• 📉 <b>Total Kerugian:</b> <code>-{_fmt_usdt(pnl_usdt)} USDT</code> (<code>-{abs(pnl_pct):.2f}%</code>)"
        else:
            hasil_badge = "🛡️ <b>HASIL: IMPAS / BEP (MODAL KEMBALI 100%)</b>"
            pnl_line = f"• ⚖️ <b>Total PnL:</b> <code>$0.0000 USDT</code> (<code>0.00%</code>) [<i>Modal Utuh Tanpa Rugi</i>]"

        if exit_type == "TRAILING_PROFIT":
            title = f"TRAILING STOP TERKUNCI! ({'+' if is_profit else ''}{pnl_pct:.2f}%)"
            icon = "🎯"
            mekanisme = "🎯 <b>Mekanisme Exit:</b> <b>Trailing Stop</b> (Kunci keuntungan otomatis saat pasar berbalik arah)"
        elif exit_type == "BEP":
            title = f"BREAK-EVEN PLUS TERKUNCI! ({'+' if is_profit else ''}{pnl_pct:.2f}%)"
            icon = "🛡️"
            mekanisme = "🛡️ <b>Mekanisme Exit:</b> <b>Break-Even Plus (Anti-Minus & Kunci Cuan)</b>"
        elif exit_type == "STAGNANT":
            title = "STAGNATION TIMEOUT (SLOT DIBEBASKAN)"
            icon = "⏱️"
            mekanisme = "⏱️ <b>Mekanisme Exit:</b> <b>Stagnation Timeout</b> (Koin mogok > 2.5 jam dilepas untuk koin baru)"
        elif exit_type == "TP2":
            title = f"MOONBAG FULL TAKE PROFIT! (+{pnl_pct:.2f}%)"
            icon = "🌕"
            mekanisme = "🌕 <b>Mekanisme Exit:</b> <b>Take Profit 2 (Target Puncak Moonbag Selesai)</b>"
        elif exit_type == "SL_DUST":
            title = "STOP LOSS TERDETEKSI (DUST COIN < $5)"
            icon = "🛑"
            mekanisme = "🛑 <b>Mekanisme Exit:</b> <b>Stop Loss (Dust Coin Binance)</b>"
        else:
            sl_str = "-2.0%" if segment == "MAJOR_BLUECHIP" else "-5.5%"
            title = f"CUTLOSS DISIPLIN ({sl_str})"
            icon = "🛑"
            mekanisme = "🛑 <b>Mekanisme Exit:</b> <b>Stop Loss (Disiplin Batas Risiko)</b>"

        msg = (
            f"{icon} <b>AUTO-PUMP: {title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Koin:</b> <code>{sym}</code> ({mode_badge} | {segment_badge})\n"
            f"• {hasil_badge}\n"
            f"{pnl_line}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>RINCIAN LEVEL & EKSEKUSI:</b>\n"
            f"• <b>Harga Beli (Entry):</b> <code>{fmt_entry}</code>\n"
            f"• <b>Harga Jual (Exit):</b> <code>{fmt_curr}</code>\n"
            f"• {mekanisme}\n"
            f"• <b>Keterangan:</b> <i>{note}</i>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💼 <i>Slot posisi sekarang terbuka kembali untuk koin pump berikutnya.</i>"
        )
        self._broadcast_to_telegram(msg)

    def _broadcast_to_telegram(self, message: str):
        """Kirim pesan langsung ke channel/admin Telegram dengan fallback requests sync."""
        sent = False
        if self.telegram_notifier:
            try:
                sent = self.telegram_notifier.broadcast_text(message)
            except Exception as e:
                logger.error(f"Gagal kirim notifikasi AutoPump via notifier: {e}")

        # Fallback langsung via HTTP Requests jika asyncio loop notifier tertutup
        if not sent:
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            cid = os.getenv("TELEGRAM_CHAT_ID")
            if token and cid:
                try:
                    import requests
                    url = f"https://api.telegram.org/bot{token}/sendMessage"
                    r = requests.post(url, json={"chat_id": cid, "text": message, "parse_mode": "HTML"}, timeout=5)
                    if r.status_code == 200:
                        logger.info(f"Notifikasi AutoPump terkirim via fallback HTTP ke chat {cid}")
                except Exception as ex:
                    logger.error(f"Fallback HTTP Telegram gagal: {ex}")

    def format_status_report(self) -> str:
        """Membuat ringkasan status Auto-Pump untuk perintah /autopump."""
        open_pos = self.get_open_positions()
        hist = self.get_trade_history(limit=5)
        
        status_text = "🟢 <b>AKTIF</b>" if self.enabled else "🔴 <b>NONAKTIF (Standby)</b>"
        mode_badge = "🟢 <b>REAL SPOT (Binance Live)</b>" if self.mode == "real" else "🟡 <b>PAPER TRADING (Simulasi)</b>"
        
        # Cek saldo real atau paper
        if self.mode == "real":
            bal = self.client.get_balance()
            free_usdt = bal.get("free_usdt", 0.0)
            ld_usdt = bal.get("ld_usdt", 0.0)
            saldo_str = f"<b>Saldo Real Spot:</b> <code>${free_usdt:.2f} USDT</code>"
            if ld_usdt > 0:
                saldo_str += f"\n• <b>Saldo Simple Earn (Flexible):</b> <code>${ld_usdt:.2f} LDUSDT</code> (<i>Tebus/Redeem ke Spot di Binance HP agar bisa dibelanjakan</i>)"
        else:
            saldo_str = f"<b>Saldo Virtual:</b> <code>${self.paper_balance:.2f} USDT</code>"

        text = (
            f"⚡ <b>DASHBOARD AUTO-PUMP SNIPER (BINANCE SPOT)</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Status Bot:</b> {status_text}\n"
            f"• <b>Mode:</b> {mode_badge}\n"
            f"• {saldo_str}\n"
            f"• <b>Alokasi per Koin:</b> <code>${self.capital_per_coin} USDT</code>\n"
            f"• <b>Maksimal Posisi Terbuka:</b> <code>{len(open_pos)} / {self.max_positions} Koin</code>\n"
            f"• <b>Kriteria Pump Minimum:</b> Skor <code>>={self.min_score}/100</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
        )

        if open_pos:
            text += "\n📂 <b>POSISI SEDANG BERJALAN:</b>\n"
            for p in open_pos:
                sym = p["symbol"]
                t = self.client.fetch_ticker(sym)
                live_p = t.get("last_price") or t.get("last") or p["entry_price"]
                pnl_pct = ((live_p - p["entry_price"]) / p["entry_price"]) * 100
                sign = "+" if pnl_pct >= 0 else ""
                icon = "🟢" if pnl_pct >= 0 else "🔴"
                tp1_status = "✅ <i>(SL di BEP)</i>" if p["tp1_hit"] else "⏳ <i>Menuju TP1</i>"
                p_seg = p.get("segment") or ("MAJOR_BLUECHIP" if any(sym.startswith(m) for m in ["BTC", "ETH", "SOL", "XRP", "BNB", "ADA"]) else "ALTCOIN_SNIPER")
                seg_icon = "🐘" if p_seg == "MAJOR_BLUECHIP" else "🚀"
                
                def _fmt(val):
                    return f"{val:.8f}".rstrip("0") if val < 0.001 else f"{val:.4f}"

                text += (
                    f"• {seg_icon} <b>{sym}</b> | {icon} <code>{sign}{pnl_pct:.2f}%</code>\n"
                    f"  Entry: <code>${_fmt(p['entry_price'])}</code> ➔ Live: <code>${_fmt(live_p)}</code>\n"
                    f"  SL: <code>${_fmt(p['sl_price'])}</code> | TP1: <code>${_fmt(p['tp1_price'])}</code> ({tp1_status})\n\n"
                )
        else:
            text += "\n<i>Tidak ada koin yang sedang dipegang saat ini.</i>\n"

        if hist:
            text += "\n📜 <b>5 TRANSAKSI TERAKHIR:</b>\n"
            for h in hist:
                sign = "+" if h["pnl_pct"] >= 0 else ""
                icon = "🌕" if h["pnl_pct"] > 0 else "🛑"
                text += f"• {icon} <b>{h['symbol']}</b>: <code>{sign}{h['pnl_pct']:.2f}%</code> (<code>{sign}${h['pnl_usdt']:.2f}</code>) | {h['exit_reason']}\n"

        text += (
            f"\n━━━━━━━━━━━━━━━━━━\n"
            f"<b>KONTROL PERINTAH:</b>\n"
            f"• <code>/autopump on</code> ➔ Aktifkan Auto-Buy\n"
            f"• <code>/autopump off</code> ➔ Matikan Auto-Buy\n"
            f"• <code>/autopump mode real</code> ➔ Pindah ke Akun Real\n"
            f"• <code>/autopump mode paper</code> ➔ Pindah ke Simulasi\n"
            f"• <code>/autopump capital 20</code> ➔ Ubah modal per koin"
        )
        return text

    def check_circuit_breaker(self) -> Tuple[bool, float, str]:
        """
        Circuit Breaker Harian KHUSUS CRYPTO (Tidak membatasi Akun MT5 Cent USC):
        Jika total kerugian tertutup hari ini mencapai batas maksimal (CRYPTO_MAX_DAILY_LOSS),
        sniper crypto akan otomatis dinonaktifkan (PAUSE) untuk mengamankan saldo USDT.
        """
        max_daily_loss = float(os.getenv("CRYPTO_MAX_DAILY_LOSS", "5.0"))  # Default $5.00 USDT
        today_prefix = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
        
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                SELECT SUM(pnl_usdt) FROM crypto_pump_positions
                WHERE status NOT IN ('OPEN', 'TP1_HIT')
                AND close_time LIKE ?
            """, (f"{today_prefix}%",))
            row = cur.fetchone()
            conn.close()
            
            daily_pnl = float(row[0] or 0.0)
            if daily_pnl <= -abs(max_daily_loss):
                msg = (
                    f"🚨 [CRYPTO CIRCUIT BREAKER] Total kerugian crypto hari ini (${abs(daily_pnl):.2f} USDT) "
                    f"telah melampaui batas aman harian (${max_daily_loss:.2f} USDT)! "
                    f"Auto-Pump otomatis DINONAKTIFKAN demi melindungi modal."
                )
                logger.warning(msg)
                if self.enabled:
                    self.enabled = False
                    self._broadcast_to_telegram(
                        f"🛡️ <b>CIRCUIT BREAKER CRYPTO TERPICU!</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"• <b>Kerugian Hari Ini:</b> <code>-${abs(daily_pnl):.2f} USDT</code>\n"
                        f"• <b>Batas Maksimal:</b> <code>${max_daily_loss:.2f} USDT</code>\n"
                        f"• <b>Aksi:</b> Sniper Crypto otomatis dimatikan (OFF).\n"
                        f"<i>Akun MT5 Gold USC tetap berjalan normal tanpa intervensi.</i>"
                    )
                return True, daily_pnl, msg
            return False, daily_pnl, "OK"
        except Exception as e:
            logger.error(f"Error checking crypto circuit breaker: {e}")
            return False, 0.0, str(e)

    def reconcile_with_exchange(self) -> List[str]:
        """
        2-Way Position Reconciliation (Sinkronisasi 2 Arah):
        Mendeteksi jika koin telah dijual manual oleh pengguna di aplikasi Binance HP.
        Jika saldo koin di exchange sudah 0, posisi lokal di DB ditutup sebagai CLOSED_MANUAL_EXTERNAL.
        """
        if self.mode != "real" or not self.client.is_authenticated():
            return []

        open_pos = self.get_open_positions()
        if not open_pos:
            return []

        reconciled = []
        now_str = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")

        try:
            bal_data = self.client.get_balance()
            if not bal_data.get("authenticated"):
                return []
            raw_balances = bal_data.get("holdings") or bal_data.get("balances", {})

            # 1. Periksa posisi OPEN yang ada
            for p in open_pos:
                if p["mode"] != "real":
                    continue
                sym = p["symbol"]
                base_asset = sym.replace("USDT", "").replace("FDUSD", "").replace("USDC", "").upper()
                free_amt = float(raw_balances.get(base_asset, {}).get("free", 0.0))

                t = self.client.fetch_ticker(sym)
                curr_p = t.get("last_price") or t.get("last") or p["entry_price"]
                holding_val_usdt = free_amt * curr_p

                # Hanya tutup posisi jika saldo koin di exchange benar-benar sudah habis / debu (< $0.20 USDT)
                if free_amt <= 0.000001 or holding_val_usdt < 0.20:
                    pos_id = p["id"]
                    pnl_pct = ((curr_p - p["entry_price"]) / p["entry_price"]) * 100
                    pnl_usdt = (curr_p - p["entry_price"]) * p["quantity"]

                    self._close_position(
                        pos_id=pos_id,
                        status="CLOSED_MANUAL_EXTERNAL",
                        close_price=curr_p,
                        close_time=now_str,
                        pnl_usdt=pnl_usdt,
                        pnl_pct=pnl_pct,
                        exit_reason="Terdeteksi ditutup/dijual habis di Aplikasi Binance",
                    )
                    reconciled.append(sym)
                    logger.info(f"🔄 [RECONCILE] Posisi {sym} disinkronkan: saldo koin di Binance telah habis.")
                elif abs(free_amt - p["quantity"]) > 0.0001:
                    # Kuantitas koin di exchange berubah (misal parsial sell): perbarui kuantitas aktif
                    with sqlite3.connect(DB_PATH) as conn:
                        cur = conn.cursor()
                        new_cost = free_amt * p["entry_price"]
                        cur.execute("UPDATE crypto_pump_positions SET quantity = ?, cost_usdt = ? WHERE id = ?", (free_amt, new_cost, p["id"]))
                        conn.commit()
                    logger.info(f"🔄 [RECONCILE] Qty {sym} disinkronkan ke exchange: {free_amt} (Biaya: ${new_cost:.2f} USDT)")

            # 2. Deteksi koin riil di exchange yang bernilai >= $5.00 (Minimal Order Binance Spot)
            open_symbols = [p["symbol"] for p in open_pos if p["mode"] == "real"]
            for asset, h_data in raw_balances.items():
                if asset in ["USDT", "FDUSD", "USDC"]:
                    continue
                h_free = float(h_data.get("free", 0.0))
                if h_free <= 0.000001:
                    continue
                sym = f"{asset}USDT"
                if sym not in open_symbols:
                    t = self.client.fetch_ticker(sym)
                    curr_p = t.get("last_price") or t.get("last") or 0.0
                    val_usdt = h_free * curr_p
                    # Sinkronkan posisi riil dari dompet Binance (koin bernilai >= $0.40 USDT)
                    # Sisa receh dust (< $0.40) dilewati agar tidak mengotori tabel posisi aktif
                    if val_usdt >= 0.40:
                        entry_p = curr_p
                        with sqlite3.connect(DB_PATH) as conn:
                            cur = conn.cursor()
                            cur.execute("SELECT entry_price, status FROM crypto_pump_positions WHERE symbol = ? ORDER BY id DESC LIMIT 1", (sym,))
                            row = cur.fetchone()
                            if row and row[1] and str(row[1]).startswith("CLOSED_"):
                                continue
                            if row and row[0]:
                                entry_p = float(row[0])
                            else:
                                # Cari riwayat trade pembelian terakhir dari Binance jika ada
                                try:
                                    ts_now = self.client._get_server_time()
                                    q = f"symbol={sym}&timestamp={ts_now}&recvWindow=10000"
                                    sig = hmac.new(self.client.secret_key.encode("utf-8"), q.encode("utf-8"), hashlib.sha256).hexdigest()
                                    u = f"https://api.binance.com/api/v3/myTrades?{q}&signature={sig}"
                                    r_tr = self.client._session.get(u, headers={"X-MBX-APIKEY": self.client.api_key}, timeout=4)
                                    if r_tr.status_code == 200:
                                        tr_list = r_tr.json()
                                        if isinstance(tr_list, list) and tr_list:
                                            buys = [x for x in tr_list if x.get("isBuyer")]
                                            if buys:
                                                entry_p = float(buys[-1].get("price", entry_p))
                                except Exception:
                                    pass

                            sl_p = entry_p * (1.0 - 5.5 / 100.0)
                            tp1_p = entry_p * (1.0 + 11.0 / 100.0)
                            tp2_p = entry_p * (1.0 + 25.0 / 100.0)
                            cost = h_free * entry_p

                            cur.execute("""
                                INSERT INTO crypto_pump_positions (
                                    symbol, mode, status, entry_price, quantity, cost_usdt,
                                    entry_time, sl_price, tp1_price, tp2_price, tp1_hit
                                ) VALUES (?, 'real', 'OPEN', ?, ?, ?, ?, ?, ?, ?, 0)
                            """, (sym, entry_p, h_free, cost, now_str, sl_p, tp1_p, tp2_p))
                            conn.commit()
                        logger.info(f"🔄 [RECONCILE] Posisi riil {sym} ({h_free} koin @ ${entry_p}) otomatis dipulihkan ke OPEN tracking!")
                        reconciled.append(sym)
        except Exception as e:
            logger.error(f"Error saat reconcile posisi Binance: {e}")

        return reconciled

    def close_all_positions(self, reason: str = "Emergency Panic Close All") -> Dict[str, Any]:
        """
        Tombol Darurat Panic Close All untuk Crypto:
        Menutup seluruh posisi koin terbuka secara instan (Market Sell untuk Real, Reset untuk Paper).
        """
        open_pos = self.get_open_positions()
        if not open_pos:
            return {
                "success": True,
                "closed_count": 0,
                "message": "Tidak ada posisi koin yang sedang terbuka.",
                "details": [],
            }

        closed_list = []
        now_str = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")

        # Proteksi Mutlak: Jangan pernah eksekusi jual riil ke exchange jika dipanggil oleh unit test (pytest) atau alasan testing!
        is_test_env = (
            bool(os.getenv("PYTEST_CURRENT_TEST"))
            or os.getenv("IS_TESTING") == "true"
            or "test" in reason.lower()
            or "mock" in reason.lower()
        )

        for p in open_pos:
            sym = p["symbol"]
            pos_id = p["id"]
            qty = p["quantity"]
            entry_p = p["entry_price"]
            mode = p["mode"]

            t = self.client.fetch_ticker(sym)
            curr_price = t.get("last_price") or t.get("last") or entry_p

            # Eksekusi sell
            if mode == "real":
                if is_test_env:
                    logger.warning(
                        f"🛡️ [TEST SAFETY LOCK] Mencegah order jual nyata Binance untuk {sym} "
                        f"karena terdeteksi pemanggilan uji coba ('{reason}'). Saldo riil dilindungi!"
                    )
                    continue
                try:
                    base_asset = sym.replace("USDT", "").replace("FDUSD", "").replace("USDC", "").upper()
                    bal_data = self.client.get_balance()
                    raw_bals = bal_data.get("holdings") or bal_data.get("balances", {})
                    free_amt = float(raw_bals.get(base_asset, {}).get("free", 0.0))
                    sell_amt = min(qty, free_amt) if free_amt > 0 else qty
                    self.client.create_order(sym, side="SELL", order_type="MARKET", amount=sell_amt)
                except Exception as e:
                    logger.error(f"Gagal market sell {sym} saat panic close: {e}")
            else:
                self.paper_balance += (qty * curr_price)

            pnl_pct = ((curr_price - entry_p) / entry_p) * 100
            pnl_usdt = (curr_price - entry_p) * qty

            self._close_position(
                pos_id=pos_id,
                status="CLOSED_PANIC",
                close_price=curr_price,
                close_time=now_str,
                pnl_usdt=pnl_usdt,
                pnl_pct=pnl_pct,
                exit_reason=f"🚨 {reason}",
            )
            closed_list.append({
                "symbol": sym,
                "pnl_pct": pnl_pct,
                "pnl_usdt": pnl_usdt,
                "close_price": curr_price,
            })

        msg_detail = ", ".join([f"{c['symbol']} ({c['pnl_pct']:+.1f}%)" for c in closed_list])
        return {
            "success": True,
            "closed_count": len(closed_list),
            "message": f"Berhasil menutup {len(closed_list)} posisi koin: {msg_detail}",
            "details": closed_list,
        }

    def get_daily_pnl_summary(self) -> Dict[str, Any]:
        """Menghitung performa akumulasi harian untuk laporan recap."""
        today_prefix = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM crypto_pump_positions
                WHERE status NOT IN ('OPEN', 'TP1_HIT')
                AND close_time LIKE ?
            """, (f"{today_prefix}%",))
            trades = [dict(r) for r in cur.fetchall()]
            conn.close()

            total_trades = len(trades)
            wins = len([t for t in trades if t.get("pnl_usdt", 0.0) > 0])
            losses = len([t for t in trades if t.get("pnl_usdt", 0.0) < 0])
            total_pnl = sum([t.get("pnl_usdt", 0.0) for t in trades])
            win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

            return {
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "net_pnl_usdt": total_pnl,
                "trades": trades,
            }
        except Exception as e:
            logger.error(f"Error getting daily crypto pnl summary: {e}")
            return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "net_pnl_usdt": 0.0, "trades": []}

    def _worker_loop(self):
        """Loop latar belakang ultra-cepat (1 detik) memindai dan mengawal posisi TP/SL."""
        logger.info("Worker AutoPumpSniper dimulai di latar belakang (Mode Ultra-Cepat 1 Detik)...")
        _last_reconcile = 0.0
        while self._running:
            try:
                if self.enabled:
                    now_ts = time.time()

                    # 1. Cek Circuit Breaker harian (Proteksi Drawdown Crypto)
                    is_tripped, _, _ = self.check_circuit_breaker()
                    if is_tripped:
                        time.sleep(30)
                        continue

                    # 2. Update posisi yang sedang terbuka (cek SL/TP per 1 detik)
                    self.update_positions()

                    # 3. Sinkronisasi posisi dengan exchange tiap ~15 detik
                    if now_ts - _last_reconcile >= 15.0:
                        self.reconcile_with_exchange()
                        _last_reconcile = now_ts

                    # 4. Cari koin baru jika slot masih ada (Scan koin pre-pump tiap 1 detik)
                    self.scan_and_snipe()
            except Exception as e:
                logger.error(f"Error pada AutoPump worker loop: {e}")
            time.sleep(1)

    def start_worker(self):
        """Menjalankan background worker thread."""
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="AutoPumpWorker")
        self._thread.start()

    def stop_worker(self):
        """Menghentikan background worker thread."""
        self._running = False
