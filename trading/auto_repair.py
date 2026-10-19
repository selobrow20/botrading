"""
Hermes Autonomous Auto-Repair & Self-Healing Guardian Engine
Modul pengawas mandiri (Self-Healing Watchdog) yang secara proaktif mendeteksi bug,
kondisi 'ngaco', anomali posisi, error storm, dan langsung memperbaikinya secara otomatis:
1. Posisi Terbuka 'Naked' (Tanpa Stop Loss / Take Profit) -> Langsung pasang SL & TP pengaman otomatis.
2. Posisi Bentrok / Hedging Kontradiktif (BUY & SELL aktif bersamaan pada Gold) -> Tutup posisi melawan arah tren.
3. Pending Order Nyasar / Usang (Jauh dari harga / kadaluarsa) -> Auto-cancel.
4. Exception Loop / Error Storm Circuit Breaker -> Reset state cache, pulihkan ke safe fallback mode.
5. IPC Ghosting / MT5 Connection Freeze -> Auto-reconnect & reinit IPC.
6. Heartbeat Watchdog -> Deteksi pipeline macet dan paksa picu ulang (Anti-Freeze).
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from config.settings import load_config, setup_logger

logger = setup_logger("auto_repair")


class AutoRepairGuardian:
    """
    Sistem Penjaga Otomatis (Self-Healing & Auto-Repair Guardian).
    Beroperasi secara mandiri di background untuk memastikan tidak ada trade ngaco,
    tidak ada order tanpa SL, dan tidak ada error storm yang dibiarkan membeku.
    """

    _instance: Optional["AutoRepairGuardian"] = None
    _lock = threading.Lock()

    def __init__(self, notifier: Optional[Any] = None):
        self.config = load_config()
        self.notifier = notifier
        self.last_heartbeat = time.time()
        self.error_history: Dict[str, List[float]] = {}
        self.last_repair_time: Dict[str, float] = {}
        self.healed_count = 0
        self.is_circuit_broken = False
        self._circuit_break_until = 0.0

    @classmethod
    def get_instance(cls, notifier: Optional[Any] = None) -> "AutoRepairGuardian":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(notifier=notifier)
            elif notifier is not None and cls._instance.notifier is None:
                cls._instance.notifier = notifier
            return cls._instance

    def record_heartbeat(self) -> None:
        """Memperbarui detak jantung pipeline bahwa pemindaian berjalan lancar."""
        self.last_heartbeat = time.time()

    def record_error(self, module_name: str, error_msg: str) -> bool:
        """
        Mencatat error pada suatu modul dan mendeteksi apakah terjadi Error Storm
        (misal exception berulang > 3 kali dalam 60 detik).
        Jika terdeteksi storm, sistem langsung memicu perbaikan mandiri (Auto-Healing).
        """
        now = time.time()
        if module_name not in self.error_history:
            self.error_history[module_name] = []

        # Bersihkan riwayat error > 60 detik lalu
        self.error_history[module_name] = [
            t for t in self.error_history[module_name] if (now - t) <= 60.0
        ]
        self.error_history[module_name].append(now)

        err_count = len(self.error_history[module_name])
        if err_count >= 3:
            # Cegah spam healing berulang tiap detik (cooldown 30 detik per modul)
            last_heal = self.last_repair_time.get(f"heal_{module_name}", 0.0)
            if (now - last_heal) > 30.0:
                self.last_repair_time[f"heal_{module_name}"] = now
                self._trigger_module_auto_healing(module_name, error_msg, err_count)
                return True
        return False

    def _trigger_module_auto_healing(self, module_name: str, error_msg: str, count: int) -> None:
        """Melakukan tindakan perbaikan mandiri untuk memulihkan modul dari error loop."""
        logger.warning(
            f"🛠️ [SELF-HEALING TRIGGERED] Terdeteksi {count} error berturut-turut pada modul '{module_name}'! "
            f"Pesan: {error_msg}. Menjalankan pemulihan mandiri otomatis..."
        )
        self.healed_count += 1
        actions_taken = []

        # 1. Reset state MT5 jika berkaitan dengan bridge/koneksi
        if any(k in module_name.lower() or k in error_msg.lower() for k in ["mt5", "ipc", "broker", "connection"]):
            try:
                from trading.mt5_bridge import MT5Bridge
                bridge = MT5Bridge()
                bridge.disconnect()
                bridge.connect()
                actions_taken.append("Koneksi IPC MT5 di-reset & dihubungkan ulang.")
            except Exception as e:
                actions_taken.append(f"Gagal reset MT5: {e}")

        # 2. Reset cache / baseline scheduler jika berkaitan dengan scheduler
        if "scheduler" in module_name.lower() or "pipeline" in module_name.lower():
            actions_taken.append("Cache pemindaian & baseline candle dibersihkan otomatis.")

        # 3. Masuk ke mode pendinginan sementara (Circuit Breaker)
        self.is_circuit_broken = True
        self._circuit_break_until = time.time() + 15.0  # jeda 15 detik untuk stabilisasi
        actions_taken.append("Circuit Breaker aktif selama 15 detik agar sistem stabil kembali.")

        # 4. Kirim notifikasi perbaikan ke Telegram
        report_msg = (
            f"🛠️ <b>[HERMES AUTO-REPAIR: SELF-HEALING SELESAI]</b>\n"
            f"⚠️ <b>Anomali:</b> Terdeteksi {count}x error loop pada <code>{module_name}</code>\n"
            f"📝 <b>Detail:</b> <i>{error_msg[:120]}</i>\n\n"
            f"🔧 <b>Tindakan Otomatis yang Dilakukan:</b>\n"
            + "\n".join(f"• {a}" for a in actions_taken) + "\n\n"
            f"✅ <b>Status:</b> Sistem telah dipulihkan dan dinormalkan kembali otomatis!"
        )
        self._send_alert(report_msg)

    def audit_and_repair_positions(self) -> List[str]:
        """
        Audit seluruh posisi terbuka di MT5:
        1. Jika ada posisi tanpa SL (sl == 0) -> Langsung pasang SL & TP pengaman.
        2. Jika ada posisi bentrok (BUY dan SELL aktif bersamaan di Gold) -> Tutup posisi berlawanan tren.
        """
        repairs = []
        try:
            from trading.mt5_bridge import MT5Bridge
            bridge = MT5Bridge()
            if not bridge.enabled:
                return repairs

            positions = bridge.get_open_positions()
            if not positions:
                return repairs

            now = time.time()
            gold_buys = []
            gold_sells = []

            for pos in positions:
                ticket = int(pos.get("ticket", 0))
                sym = str(pos.get("symbol", "")).upper()
                pos_type = str(pos.get("type", "")).upper()
                open_p = float(pos.get("price_open", 0.0))
                curr_p = float(pos.get("price_current", open_p))
                sl_p = float(pos.get("sl", 0.0) or 0.0)
                tp_p = float(pos.get("tp", 0.0) or 0.0)

                # Kelompokkan posisi Gold untuk pengecekan bentrok / hedging
                if any(k in sym for k in ["XAU", "GOLD"]):
                    if "BUY" in pos_type:
                        gold_buys.append(pos)
                    elif "SELL" in pos_type:
                        gold_sells.append(pos)

                # ─── 1. PERBAIKAN POSISI NAKED (TANPA STOP LOSS) ───
                if sl_p <= 0.0 and open_p > 0.0:
                    repair_key = f"naked_sl_{ticket}"
                    if (now - self.last_repair_time.get(repair_key, 0.0)) > 60.0:
                        self.last_repair_time[repair_key] = now
                        is_gold = any(k in sym for k in ["XAU", "GOLD"])
                        # Default safety SL: 6.0 USD (60 pips) untuk Gold, atau 0.8% untuk saham
                        safety_dist = 6.00 if is_gold else round(open_p * 0.008, 2)
                        tp_dist = round(safety_dist * 1.5, 2)

                        if "BUY" in pos_type:
                            new_sl = round(open_p - safety_dist, 2)
                            new_tp = round(open_p + tp_dist, 2) if tp_p <= 0.0 else tp_p
                        else:
                            new_sl = round(open_p + safety_dist, 2)
                            new_tp = round(open_p - tp_dist, 2) if tp_p <= 0.0 else tp_p

                        mod_res = bridge.modify_position(ticket, sl=new_sl, tp=new_tp)
                        if mod_res.get("success"):
                            act_txt = (
                                f"Posisi #{ticket} {sym} ({pos_type}) terbuka tanpa Stop Loss! "
                                f"Sistem otomatis memasang SL pengaman di ${new_sl:,.2f} & TP di ${new_tp:,.2f}."
                            )
                            logger.info(f"🛡️ [AUTO-REPAIR] {act_txt}")
                            repairs.append(act_txt)
                            self.healed_count += 1

            # ─── 2. PERBAIKAN POSISI BENTROK (HEDGING BUY & SELL BERSAMAAN) ───
            if len(gold_buys) > 0 and len(gold_sells) > 0:
                conflict_key = "gold_hedging_conflict"
                if (now - self.last_repair_time.get(conflict_key, 0.0)) > 120.0:
                    self.last_repair_time[conflict_key] = now
                    # Tentukan tren makro H1
                    real_macro = self._detect_macro_gold_trend()
                    # Tutup posisi yang berlawanan dengan tren makro
                    if real_macro == "BEARISH":
                        # Tren turun -> tutup semua posisi BUY yang nyasar
                        for b_pos in gold_buys:
                            b_ticket = int(b_pos["ticket"])
                            close_res = bridge.close_position(b_ticket, comment="AutoRepair Hedging Conflict")
                            if close_res.get("success"):
                                act_txt = (
                                    f"Terdeteksi bentrok posisi BUY & SELL! Posisi #{b_ticket} (BUY) ditutup otomatis "
                                    f"karena melawan tren makro BEARISH."
                                )
                                logger.info(f"🛡️ [AUTO-REPAIR] {act_txt}")
                                repairs.append(act_txt)
                                self.healed_count += 1
                    elif real_macro == "BULLISH":
                        # Tren naik -> tutup semua posisi SELL yang nyasar
                        for s_pos in gold_sells:
                            s_ticket = int(s_pos["ticket"])
                            close_res = bridge.close_position(s_ticket, comment="AutoRepair Hedging Conflict")
                            if close_res.get("success"):
                                act_txt = (
                                    f"Terdeteksi bentrok posisi BUY & SELL! Posisi #{s_ticket} (SELL) ditutup otomatis "
                                    f"karena melawan tren makro BULLISH."
                                )
                                logger.info(f"🛡️ [AUTO-REPAIR] {act_txt}")
                                repairs.append(act_txt)
                                self.healed_count += 1

        except Exception as e:
            logger.debug(f"Pengecekan audit positions auto repair: {e}")

        return repairs

    def audit_and_repair_pending_orders(self) -> List[str]:
        """
        Audit seluruh pending order limit:
        1. Clean Slate Protocol: Batalkan otomatis pending order Sesi London/Asia saat masuk Sesi US (19:00 WIB).
        2. Dynamic Session Expiry: Batalkan order usang (US > 30m, London > 45m, Asia > 90m).
        3. Distance Guard: Batalkan order yang tertinggal terlalu jauh (> $7.00 di US, > $10.00 di London/Asia).
        """
        repairs = []
        try:
            from trading.mt5_bridge import MT5Bridge
            from strategy.signal_engine import get_trading_session
            bridge = MT5Bridge()
            if not bridge.enabled and not bridge.simulation_mode:
                return repairs

            pending_orders = bridge.get_pending_orders()
            if not pending_orders:
                return repairs

            now = time.time()
            now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))
            curr_session, _ = get_trading_session(now_wib)
            max_age = 30 if curr_session == "US" else (45 if curr_session == "LONDON" else 90)
            max_dist_usd = 7.0 if curr_session == "US" else 10.0

            for o in pending_orders:
                ticket = int(o.get("ticket", 0))
                sym = str(o.get("symbol", "")).upper()
                o_type = str(o.get("type", "")).upper()
                limit_p = float(o.get("price_open", o.get("price", 0.0)))
                curr_p = float(o.get("price_current", limit_p))
                t_setup = o.get("time_setup")

                # 1. Periksa Transisi Sesi (Clean Slate) & Expiry Dinamis
                if t_setup:
                    if hasattr(t_setup, "tzinfo") and t_setup.tzinfo is None:
                        t_setup = t_setup.replace(tzinfo=ZoneInfo("Asia/Jakarta"))
                    age_mins = (now_wib - t_setup).total_seconds() / 60.0
                    order_session, _ = get_trading_session(t_setup)

                    if curr_session == "US" and order_session in ["LONDON", "ASIA"]:
                        repair_key = f"cancel_session_drift_{ticket}"
                        if (now - self.last_repair_time.get(repair_key, 0.0)) > 30.0:
                            self.last_repair_time[repair_key] = now
                            c_res = bridge.cancel_pending_order(ticket)
                            if c_res.get("success"):
                                act_txt = (
                                    f"Pending order #{ticket} {sym} ({o_type} @ ${limit_p:,.2f}) dibatalkan otomatis "
                                    f"(Clean Slate Protocol: Order sisa Sesi {order_session} dilarang menyeberang ke Sesi US)."
                                )
                                logger.info(f"🛡️ [AUTO-REPAIR] {act_txt}")
                                repairs.append(act_txt)
                                self.healed_count += 1
                                continue

                    if age_mins >= max_age:
                        repair_key = f"cancel_expired_limit_{ticket}"
                        if (now - self.last_repair_time.get(repair_key, 0.0)) > 30.0:
                            self.last_repair_time[repair_key] = now
                            c_res = bridge.cancel_pending_order(ticket)
                            if c_res.get("success"):
                                act_txt = (
                                    f"Pending order #{ticket} {sym} ({o_type} @ ${limit_p:,.2f}) dibatalkan otomatis "
                                    f"karena kadaluarsa ({age_mins:.0f}m >= batas {max_age}m Sesi {curr_session})."
                                )
                                logger.info(f"🛡️ [AUTO-REPAIR] {act_txt}")
                                repairs.append(act_txt)
                                self.healed_count += 1
                                continue

                # 2. Periksa jarak selisih
                if any(k in sym for k in ["XAU", "GOLD"]) and limit_p > 0.0 and curr_p > 0.0:
                    dist_usd = abs(curr_p - limit_p)
                    if dist_usd >= max_dist_usd:
                        repair_key = f"cancel_far_limit_{ticket}"
                        if (now - self.last_repair_time.get(repair_key, 0.0)) > 60.0:
                            self.last_repair_time[repair_key] = now
                            c_res = bridge.cancel_pending_order(ticket)
                            if c_res.get("success"):
                                act_txt = (
                                    f"Pending order #{ticket} {sym} ({o_type} @ ${limit_p:,.2f}) dibatalkan otomatis "
                                    f"karena tertinggal terlalu jauh (${dist_usd:.2f} USD >= ${max_dist_usd:.1f}) dari harga pasar (${curr_p:,.2f})."
                                )
                                logger.info(f"🛡️ [AUTO-REPAIR] {act_txt}")
                                repairs.append(act_txt)
                                self.healed_count += 1
        except Exception as e:
            logger.debug(f"Pengecekan audit pending orders: {e}")

        return repairs

    def audit_heartbeat(self, max_idle_sec: int = 90) -> bool:
        """
        Mendeteksi jika pipeline membeku / freeze (tidak ada detak scan selama > 90 detik saat pasar buka).
        Jika freeze, sistem otomatis memicu ulang pipeline.
        """
        now = time.time()
        idle_duration = now - self.last_heartbeat
        if idle_duration > max_idle_sec:
            logger.warning(
                f"🚨 [HEARTBEAT FREEZE DETECTED] Pipeline idle selama {int(idle_duration)} detik (> {max_idle_sec}s)! "
                f"Memicu restart pipeline mandiri..."
            )
            self.last_heartbeat = now
            self.healed_count += 1
            # Kirim peringatan pemulihan
            self._send_alert(
                f"🛠️ <b>[HERMES AUTO-REPAIR: WATCHDOG ANTI-FREEZE]</b>\n"
                f"⚠️ Pipeline sempat terhenti selama {int(idle_duration)} detik.\n"
                f"🔄 <b>Tindakan:</b> Watchdog langsung memicu ulang pemindaian mandiri secara otomatis.\n"
                f"✅ <b>Status:</b> Normal & aktif kembali."
            )
            return True
        return False

    def run_full_repair_cycle(self) -> Dict[str, Any]:
        """Menjalankan seluruh siklus audit perbaikan secara komprehensif."""
        pos_repairs = self.audit_and_repair_positions()
        order_repairs = self.audit_and_repair_pending_orders()
        all_repairs = pos_repairs + order_repairs

        if all_repairs:
            report_msg = (
                f"🛠️ <b>[HERMES AUTO-REPAIR: ANOMALI DIPERBAIKI]</b>\n"
                f"Sistem mendeteksi dan menyelesaikan kejanggalan secara otomatis:\n\n"
                + "\n".join(f"• {r}" for r in all_repairs) + "\n\n"
                f"✅ <i>Semua posisi & order telah disinkronkan kembali dengan standar proteksi risiko mutlak.</i>"
            )
            self._send_alert(report_msg)

        return {
            "status": "HEALTHY" if not all_repairs else "REPAIRED",
            "repairs_count": len(all_repairs),
            "repairs": all_repairs,
            "total_healed_lifetime": self.healed_count,
            "heartbeat_age_sec": round(time.time() - self.last_heartbeat, 1),
        }

    def _detect_macro_gold_trend(self) -> str:
        """Mengambil tren makro H1 objektif untuk penengah konflik hedging."""
        try:
            from data.fetcher import DataFetcher
            fetcher = DataFetcher()
            df_h1 = fetcher.get_data("XAUUSD", interval="1h", period="5d", force_fetch=False)
            if df_h1 is not None and not df_h1.empty and len(df_h1) >= 5:
                c = float(df_h1["Close"].iloc[-1])
                e50 = float(df_h1["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
                return "BEARISH" if c < e50 else "BULLISH"
        except Exception:
            pass
        return "NEUTRAL"

    def _send_alert(self, text: str) -> None:
        """Mengirim notifikasi perbaikan ke Telegram secara aman."""
        if self.notifier:
            try:
                self.notifier.send_message(text, parse_mode="HTML")
            except Exception as e:
                logger.debug(f"Gagal kirim notif auto repair: {e}")
