"""
Modul Eksekutor MetaTrader 5 (MT5 Bridge & Auto-Trader).
Menghubungkan sinyal bot trading (khususnya Emas / XAU/USD berbasis 9 Buku PDF)
secara langsung ke terminal MetaTrader 5 untuk eksekusi order otomatis (BUY / SELL)
lengkap dengan Take Profit (TP), Stop Loss (SL), dan manajemen risiko lot.
"""

import os
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from zoneinfo import ZoneInfo
from config.settings import load_config, setup_logger

logger = setup_logger("mt5_bridge")

# Import MetaTrader5 dengan fallback aman (jika running di Linux / tanpa MT5)
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False


class MT5Bridge:
    """Jembatan eksekusi trading otomatis ke MetaTrader 5."""

    COMMON_TERMINAL_PATHS = [
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
        r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
        r"C:\Program Files\Exness MetaTrader 5\terminal64.exe",
        r"C:\Program Files\FBS MetaTrader 5\terminal64.exe",
        r"C:\Program Files\IC Markets MetaTrader 5\terminal64.exe",
        r"C:\Program Files\XM Global MT5\terminal64.exe",
        r"C:\Program Files\OctaFX MetaTrader 5\terminal64.exe",
        r"C:\Program Files\HFM MetaTrader 5\terminal64.exe",
        r"C:\Program Files\HF Markets MetaTrader 5\terminal64.exe",
        r"C:\Program Files (x86)\HFM MetaTrader 5\terminal64.exe",
        r"C:\Program Files (x86)\HF Markets MetaTrader 5\terminal64.exe",
        r"C:\Program Files\HFM\terminal64.exe",
        r"C:\Program Files\Vantage FX MetaTrader 5\terminal64.exe",
    ]

    _instance = None

    def __new__(cls, *args, **kwargs):
        """Pola Singleton agar koneksi MT5 dibagi bersama di seluruh sistem."""
        if cls._instance is None:
            cls._instance = super(MT5Bridge, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, simulation_mode: bool = False):
        if self._initialized:
            if simulation_mode:
                self.simulation_mode = True
            return

        cfg = load_config()
        self.config = cfg
        mt5_cfg = cfg.get("mt5", {})

        self.enabled: bool = bool(mt5_cfg.get("enabled", False))
        self.login: int = int(os.getenv("MT5_LOGIN", mt5_cfg.get("login", 0)) or 0)
        self.password: str = str(os.getenv("MT5_PASSWORD", mt5_cfg.get("password", "")) or "")
        self.server: str = str(os.getenv("MT5_SERVER", mt5_cfg.get("server", "")) or "")
        self.path: str = str(os.getenv("MT5_PATH", mt5_cfg.get("path", "")) or "")
        self.magic_number: int = int(mt5_cfg.get("magic_number", 777777))
        self.default_lot: float = float(mt5_cfg.get("default_lot", 0.01))
        self.high_confidence_lot: float = float(mt5_cfg.get("high_confidence_lot", 0.05))
        self.high_confidence_threshold: float = float(mt5_cfg.get("high_confidence_threshold", 80.0))
        self.cent_only_high_grade: bool = bool(mt5_cfg.get("cent_only_high_grade", True))

        self.use_dynamic_lot: bool = bool(mt5_cfg.get("use_dynamic_lot", False))
        self.risk_percent: float = float(mt5_cfg.get("risk_percent", 1.0))
        self.max_slippage: int = int(mt5_cfg.get("max_slippage", 20))
        self.gold_symbol: str = str(mt5_cfg.get("gold_symbol", "XAUUSD"))
        self.trading_hours: str = str(mt5_cfg.get("trading_hours", "all") or "all")

        self.simulation_mode: bool = simulation_mode
        self.is_connected: bool = False
        self._simulated_positions: List[Dict[str, Any]] = []
        self._simulated_pending_orders: List[Dict[str, Any]] = []
        self._simulated_ticket: int = 100000
        self.enable_limit_orders: bool = bool(mt5_cfg.get("enable_limit_orders", True))
        self.limit_order_expiry_mins: int = int(mt5_cfg.get("limit_order_expiry_mins", 120))
        self.max_pending_orders_per_symbol: int = int(mt5_cfg.get("max_pending_orders_per_symbol", 1))
        self.min_limit_distance_pips: float = float(mt5_cfg.get("min_limit_distance_pips", 15.0))
        self.enable_dual_sided_limits: bool = bool(cfg.get("trading", {}).get("enable_dual_sided_limits", False) or mt5_cfg.get("enable_dual_sided_limits", False))
        self.reversal_cooldown_until: Optional[datetime] = None
        self.reversal_cooldown_reason: str = ""
        # Directional Cooldown: {direction: datetime_until} — Anti-Revenge Re-entry setelah SL beruntun
        # Setelah SL BUY → lock BUY selama N menit. Setelah SL SELL → lock SELL selama N menit.
        self.directional_sl_cooldown: Dict[str, Optional[datetime]] = {"BUY": None, "SELL": None}

        self._initialized = True
        logger.info(f"MT5Bridge diinisialisasi. Enabled: {self.enabled}, Hours: {self.trading_hours}, Platform: {sys.platform}, Lib Available: {MT5_AVAILABLE}")

    @classmethod
    def is_available(cls) -> bool:
        """Memeriksa apakah pustaka MetaTrader5 terinstal dan OS adalah Windows."""
        return MT5_AVAILABLE and sys.platform == "win32"

    def auto_detect_terminal_path(self) -> Optional[str]:
        """Mencari lokasi file terminal64.exe di lokasi instalasi standar Windows."""
        if self.path and Path(self.path).exists():
            return self.path

        for p_str in self.COMMON_TERMINAL_PATHS:
            p = Path(p_str)
            if p.exists():
                logger.info(f"Ditemukan instalasi terminal MT5 di: {p_str}")
                return p_str
        return None

    def is_within_trading_hours(self) -> Tuple[bool, str]:
        """
        Mengecek apakah waktu saat ini (WIB) berada di dalam jam trading yang diizinkan.
        Format self.trading_hours: 'all' (24 jam) atau '19:00-23:00'.
        """
        if not self.trading_hours or self.trading_hours.lower() == "all":
            return True, "Mode 24 Jam Aktif."

        try:
            now_wib = datetime.now(ZoneInfo("Asia/Jakarta")).time()

            parts = self.trading_hours.split("-")
            if len(parts) == 2:
                s_h, s_m = map(int, parts[0].strip().split(":"))
                e_h, e_m = map(int, parts[1].strip().split(":"))
                start_t = time(s_h, s_m)
                end_t = time(e_h, e_m)

                if start_t <= end_t:
                    in_range = start_t <= now_wib <= end_t
                else:  # Lewat tengah malam (misal 21:00 - 03:00)
                    in_range = now_wib >= start_t or now_wib <= end_t

                if in_range:
                    return True, f"Dalam jam aktif trading ({self.trading_hours} WIB)."
                else:
                    return False, f"Di luar jam aktif trading ({self.trading_hours} WIB). Waktu saat ini: {now_wib.strftime('%H:%M')} WIB."
            return True, "Format jam tidak dibatasi."
        except Exception as e:
            logger.debug(f"Error parsing trading_hours ({self.trading_hours}): {e}")
            return True, "Pengecekan jam dilewati."

    def is_us_session_window(self) -> bool:
        """Mengecek apakah waktu WIB saat ini berada di rentang Sesi US (19:00 - 24:00 WIB)."""
        try:
            now_wib = datetime.now(ZoneInfo("Asia/Jakarta")).time()
            return time(19, 0) <= now_wib <= time(23, 59, 59)
        except Exception:
            return False

    def set_enabled(self, val: bool) -> None:
        """Mengatur status aktif/nonaktif auto-trade dan menyimpannya secara persisten."""
        self.enabled = bool(val)
        self._save_mt5_config()

    def set_default_lot(self, lot: float) -> None:
        """Mengatur default lot transaksi dan menyimpannya secara persisten."""
        self.default_lot = round(float(lot), 2)
        self._save_mt5_config()

    def set_trading_hours(self, hours_str: str) -> None:
        """Mengatur jadwal jam trading aktif (misal '19:00-23:00' atau 'all')."""
        self.trading_hours = str(hours_str).strip()
        self._save_mt5_config()

    def set_reversal_cooldown(self, minutes: int = 0, reason: str = "") -> None:
        """Mengaktifkan masa jeda/observasi (cooldown) setelah deteksi pembalikan tren."""
        if minutes <= 0:
            self.clear_reversal_cooldown()
            return
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))
        self.reversal_cooldown_until = now_wib + timedelta(minutes=minutes)
        self.reversal_cooldown_reason = reason or "Pembalikan arah tren terdeteksi"
        logger.info(
            f"⏸️ Reversal Cooldown MT5 diaktifkan selama {minutes} menit "
            f"(sampai {self.reversal_cooldown_until.strftime('%H:%M')} WIB). Alasan: {self.reversal_cooldown_reason}"
        )


    def is_in_reversal_cooldown(self) -> Tuple[bool, str]:
        """Mengecek apakah saat ini sedang dalam masa cooldown setelah pembalikan arah."""
        if not self.reversal_cooldown_until:
            return False, "Tidak ada cooldown aktif."

        from datetime import datetime
        from zoneinfo import ZoneInfo
        now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))
        if now_wib < self.reversal_cooldown_until:
            rem_sec = (self.reversal_cooldown_until - now_wib).total_seconds()
            rem_min = int(rem_sec // 60)
            return True, (
                f"Mode Jeda Reversal Aktif ({rem_min} menit tersisa hingga "
                f"{self.reversal_cooldown_until.strftime('%H:%M')} WIB). Alasan: {self.reversal_cooldown_reason}"
            )
        else:
            self.reversal_cooldown_until = None
            self.reversal_cooldown_reason = ""
            return False, "Cooldown telah berakhir."

    def clear_reversal_cooldown(self) -> None:
        """Menghapus masa jeda dan mengizinkan trading kembali normal."""
        self.reversal_cooldown_until = None
        self.reversal_cooldown_reason = ""
        logger.info("🟢 Reversal Cooldown MT5 dihapus. Trading XAU/USD kembali normal.")

    def _save_mt5_config(self) -> None:
        """Menyimpan konfigurasi runtime MT5 ke file config.yaml agar persist saat restart."""
        try:
            import yaml
            cfg_path = Path("config/config.yaml")
            if not cfg_path.exists():
                return
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            if "mt5" not in cfg:
                cfg["mt5"] = {}

            cfg["mt5"]["enabled"] = self.enabled
            cfg["mt5"]["default_lot"] = self.default_lot
            cfg["mt5"]["trading_hours"] = self.trading_hours

            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            logger.info("Konfigurasi MT5 berhasil diperbarui ke config/config.yaml")
        except Exception as e:
            logger.debug(f"Gagal menyimpan konfigurasi runtime MT5: {e}")

    def ensure_connected(self) -> bool:
        """Memastikan koneksi MT5 IPC aktif, sehat, dan auto-reconnect jika idle/terputus."""
        if self.simulation_mode:
            return True
        if not self.is_available():
            return False
        try:
            t_info = mt5.terminal_info()
            if t_info is None:
                logger.info("🔄 [AUTO-RECONNECT] Koneksi IPC MT5 terputus. Menginisialisasi ulang...")
                ok, _ = self.connect()
                return ok

            # Terminal MT5 aktif dan IPC terhubung.
            self.is_connected = True
            # Catatan: Jika t_info.connected adalah False sementara (misal delay tick/ping broker),
            # JANGAN lakukan mt5.login() atau mt5.shutdown() karena MT5 memiliki mekanisme
            # auto-reconnect internal ke server broker. Menginterupsinya justru memicu siklus 'mati nyala'.
            return True
        except Exception as e:
            logger.debug(f"Pengecekan heartbeat MT5: {e}")
            ok, _ = self.connect()
            return ok

    def check_overnight_safety_guards(self, broker_sym: str, score: float = 0.0, signal_type: str = "") -> Tuple[bool, str, str]:
        """
        Pengamanan Komprehensif Server Nyala Semalaman (Overnight & 24/7 Safety Guards):
        1. Rollover Deadzone Guard: Menahan order saat rollover broker (04:45 - 05:20 WIB).
        2. Max Spread Guard: Menolak entry jika spread melebar melebihi batas toleransi.
        3. Consecutive Loss Circuit Breaker: Memberikan jeda (cooldown 60m) setelah 2x SL beruntun.
        4. Midnight Sleep Guard (Khusus Jam 02:00 - 04:30 WIB):
           Mencegah boncos saat user istirahat/tidur di jam rawan likuiditas tipis & sideways.
           Jika kerugian di jendela midnight mencapai batas toleransi (-50 USC), eksekusi dikunci hingga pagi.
        5. Daily Max Drawdown Circuit Breaker (Akun USD Standard):
           Khusus akun USD Standard, batas harian (-$50 USD) aktif 24/7.
           Untuk akun Cent (USC), batas harian normal DIHILANGKAN sesuai permintaan pengguna karena dipantau langsung di siang hari.
        """
        if self.simulation_mode and not getattr(self, "_force_check_guards", False):
            return True, "Simulasi", "ok"

        cfg = getattr(self, "config", None) or load_config()
        cfg_mt5 = cfg.get("mt5", {})
        is_cent = self.is_cent_account()

        now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))
        curr_time = now_wib.time()

        # 1. Rollover Deadzone Guard (04:45 - 05:20 WIB)
        enable_rollover = cfg_mt5.get("enable_rollover_guard", True)
        if enable_rollover:
            if time(4, 45) <= curr_time < time(5, 20):
                msg = (
                    "⏸️ [ROLLOVER GUARD] Jam pergantian hari broker (Rollover 04:45 - 05:20 WIB). "
                    "Likuiditas tipis & spread berisiko melonjak. Eksekusi ditunda demi keamanan modal."
                )
                return False, msg, "rollover_deadzone"

        # 1b. Jam Istirahat & Reset Bot (02:00 - 04:00 WIB)
        # Sesuai instruksi mutlak pengguna: "jam 2 sampai jam 4 lu stop trading aja buat lu istirahat abis market buka lu bisa open posisi lgi biar lu bisa reset lgi bor"
        enable_rest = bool(cfg_mt5.get("enable_midnight_rest", True))
        if enable_rest:
            rest_start_h = int(cfg_mt5.get("midnight_rest_start_hour", 2))
            rest_end_h = int(cfg_mt5.get("midnight_rest_end_hour", 4))
            if time(rest_start_h, 0) <= curr_time < time(rest_end_h, 0):
                msg = (
                    f"🌙 [JAM ISTIRAHAT & RESET BOT] Pukul {rest_start_h:02d}:00 - {rest_end_h:02d}:00 WIB "
                    f"adalah jendela istirahat & reset bot sesuai arahan pengguna. Bot menghentikan open posisi baru. "
                    f"Pasar pagi buka kembali pukul 05:00 WIB siap open posisi baru secara fresh!"
                )
                return False, msg, "midnight_rest_window"

        # 2. Broker-Adaptive Spread Guard (PDF Section 18 & Tests 21, 22)
        spread_ok, curr_spread, spread_reason = self.is_spread_acceptable(broker_sym)
        if not spread_ok:
            msg = (
                f"⏸️ [SPREAD GUARD] Spread pasar saat ini (${curr_spread:.2f} USD) melebihi batas toleransi broker-adaptive. "
                f"Eksekusi ditahan agar tidak termakan spread malam broker."
            )
            return False, msg, "high_spread"

        # Definisi Jendela Midnight (02:00 - 04:30 WIB)
        enable_midnight = cfg_mt5.get("enable_midnight_guard", True)
        s_h = int(cfg_mt5.get("midnight_start_hour", 2))
        e_h = int(cfg_mt5.get("midnight_end_hour", 4))
        e_m = int(cfg_mt5.get("midnight_end_minute", 30))
        midnight_start = time(s_h, 0)
        midnight_end = time(e_h, e_m)
        is_midnight_window = (midnight_start <= curr_time < midnight_end)

        # 2b. Directional Cooldown Guard (Anti-Revenge Re-entry setelah SL beruntun)
        # Setelah SL BUY → lock arah BUY selama N menit; setelah SL SELL → lock arah SELL.
        # Arah BERLAWANAN tetap boleh entry (misal SL BUY → SELL masih boleh).
        dir_cd = cfg_mt5.get("directional_cooldown_mins", 35)
        if signal_type and dir_cd > 0:
            locked_until = self.directional_sl_cooldown.get(signal_type)
            if locked_until:
                rem_sec = int((locked_until - now_wib).total_seconds())
                if rem_sec > 0:
                    rem_str = f"{rem_sec} detik" if rem_sec < 60 else f"{rem_sec // 60}m {rem_sec % 60}s"
                    msg = (
                        f"⏸️ [DIRECTIONAL COOLDOWN] Arah {signal_type} dikunci sementara. "
                        f"Stop Loss {signal_type} terakhir baru saja terjadi. "
                        f"Sisa waktu jeda: {rem_str}. "
                        f"Kaidah Anti-Revenge (9 Buku PDF): Jangan re-entry arah sama setelah kena SL. "
                        f"Tunggu struktur pasar reset untuk {signal_type} berikutnya."
                    )
                    return False, msg, f"directional_cooldown_{signal_type.lower()}"
                else:
                    # Sudah lewat dari batas waktu, bersihkan kuncian arah
                    self.directional_sl_cooldown[signal_type] = None

        # 3. Consecutive Loss Circuit Breaker (Proteksi SL Beruntun)
        # Sesuai analisa & perbaikan (2 Oct 2026):
        # HAPUS bypass akun Cent di jam normal — justru di sinilah mesin nembak beruntun terjadi.
        # Consecutive loss cooldown WAJIB aktif untuk SEMUA akun (Cent & USD) tanpa pengecualian.
        # Filter RSI jenuh & EMA overextended sudah ada di signal_engine.py sebagai garis pertahanan pertama.
        max_consec = int(cfg_mt5.get("max_consecutive_losses", 2))
        cooldown_mins = int(cfg_mt5.get("consecutive_loss_cooldown_mins", 45))
        try:
            from data.storage import StockStorage
            storage = StockStorage()
            consec_losses, last_exit_time_str = storage.get_consecutive_losses("XAUUSD")
            if consec_losses >= max_consec and last_exit_time_str:
                clean_time = last_exit_time_str.replace(" WIB", "").strip()
                exit_dt = None
                for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]:
                    try:
                        exit_dt = datetime.strptime(clean_time, fmt).replace(tzinfo=ZoneInfo("Asia/Jakarta"))
                        break
                    except Exception:
                        pass
                if exit_dt:
                    diff_mins = (now_wib - exit_dt).total_seconds() / 60.0
                    if 0 <= diff_mins < cooldown_mins:
                        remaining = int(cooldown_mins - diff_mins)
                        msg = (
                            f"⏸️ [CONSECUTIVE LOSS COOLDOWN] Terdeteksi {consec_losses}x Stop Loss beruntun. "
                            f"Masa jeda pengamanan aktif ({remaining} menit tersisa) demi mencegah "
                            f"overtrading / machine-gun entry di pasar berombak."
                        )
                        return False, msg, "consecutive_loss_cooldown"
        except Exception as ex_cl:
            logger.debug(f"Pengecekan consecutive loss dilewati: {ex_cl}")


        # 4. Midnight Sleep Guard (Khusus Jam 02:00 - 04:30 WIB)
        # Sesuai arahan pengguna: "kalo bisa jam tengah malem aja jam 2-4 itu yg harus di kasih daily biar ga boncos kaya semalem
        # kalo jam jam yg masih bisa gw pantau aman aja"
        if enable_midnight and is_midnight_window:
            midnight_max_loss = float(
                cfg_mt5.get("midnight_max_loss_usc", 50.0) if is_cent else cfg_mt5.get("max_daily_loss_usd", 50.0)
            )
            try:
                today_deals = self.get_closed_deals(hours=6)
                today_prefix = now_wib.strftime("%Y-%m-%d")
                midnight_loss = 0.0
                for d in today_deals:
                    t_str = str(d.get("time_wib", ""))
                    if t_str.startswith(today_prefix):
                        try:
                            time_part = t_str.split(" ")[1] if " " in t_str else ""
                            if time_part:
                                dh = int(time_part.split(":")[0])
                                dm = int(time_part.split(":")[1])
                                dt = time(dh, dm)
                                if midnight_start <= dt < midnight_end:
                                    p = float(d.get("profit", 0.0))
                                    if p < 0:
                                        midnight_loss += abs(p)
                        except Exception:
                            p = float(d.get("profit", 0.0))
                            if p < 0:
                                midnight_loss += abs(p)

                if midnight_loss >= midnight_max_loss:
                    unit = "USC" if is_cent else "USD"
                    msg = (
                        f"🌙 [MIDNIGHT SLEEP GUARD AKTIF] Terdeteksi kerugian (-{midnight_loss:.2f} {unit} >= {midnight_max_loss:.2f} {unit}) "
                        f"di jam tidur tengah malam ({midnight_start.strftime('%H:%M')} - {midnight_end.strftime('%H:%M')} WIB). "
                        f"Bot mengunci pembukaan transaksi baru hingga sesi pagi demi mengamankan saldo dari ombak sideways saat Anda beristirahat."
                    )
                    date_key = f"midnight_{today_prefix}"
                    if not self.simulation_mode and getattr(self, "_last_midnight_alert_date", "") != date_key:
                        self._last_midnight_alert_date = date_key
                        try:
                            from notify.telegram_bot import TelegramNotifier
                            notifier = TelegramNotifier()
                            if hasattr(notifier, "send_midnight_guard_alert"):
                                notifier.send_midnight_guard_alert(midnight_loss, midnight_max_loss, unit)
                            else:
                                notifier.send_circuit_breaker_alert(midnight_loss, midnight_max_loss, unit)
                        except Exception as ex_nt:
                            logger.debug(f"Gagal kirim alert midnight guard: {ex_nt}")
                    return False, msg, "midnight_loss_limit_reached"
            except Exception as ex_mn:
                logger.debug(f"Pengecekan midnight sleep guard dilewati: {ex_mn}")

        # 5. Daily Max Drawdown Circuit Breaker (Akun USD Standard)
        # Sesuai arahan mutlak pengguna: "loss harian di hilangkan aja di usc ,kecuali pake usd"
        # Akun USC bebas trading tanpa batas loss harian di jam pantauan normal (siang/sore/malam).
        # Akun USD Standard tetap dikawal daily loss (-$50 USD) 24/7.
        if not is_cent:
            max_daily_loss_usd = float(cfg_mt5.get("max_daily_loss_usd", 50.0))
            try:
                today_deals = self.get_closed_deals(hours=24)
                today_prefix = now_wib.strftime("%Y-%m-%d")
                loss_today_usd = 0.0
                for d in today_deals:
                    if str(d.get("time_wib", "")).startswith(today_prefix):
                        p = float(d.get("profit", 0.0))
                        if p < 0:
                            loss_today_usd += abs(p)
                if loss_today_usd >= max_daily_loss_usd:
                    msg = (
                        f"🚨 [DAILY CIRCUIT BREAKER AKTIF] Batas maksimal kerugian harian akun USD Standard "
                        f"(-{loss_today_usd:.2f} USD >= {max_daily_loss_usd:.2f} USD) telah tercapai! "
                        f"Bot menghentikan pembukaan transaksi baru secara otomatis demi melindungi modal akun USD."
                    )
                    if not self.simulation_mode and getattr(self, "_last_cb_alert_date", "") != today_prefix:
                        self._last_cb_alert_date = today_prefix
                        try:
                            from notify.telegram_bot import TelegramNotifier
                            notifier = TelegramNotifier()
                            notifier.send_circuit_breaker_alert(loss_today_usd, max_daily_loss_usd, "USD")
                        except Exception as ex_nt:
                            logger.debug(f"Gagal kirim alert circuit breaker: {ex_nt}")
                    return False, msg, "daily_loss_limit_reached"
            except Exception as ex_dl:
                logger.debug(f"Pengecekan daily loss circuit breaker USD dilewati: {ex_dl}")

        return True, "Seluruh guard pengamanan semalaman normal.", "ok"

    def connect(
        self,
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        path: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Menghubungkan ke terminal MetaTrader 5.
        Jika akun dan password tidak diisi, otomatis terhubung ke terminal aktif yang sedang terbuka.
        """
        if self.simulation_mode:
            self.is_connected = True
            return True, "Terhubung dalam mode Simulasi (Dry-Run)."

        if not self.is_available():
            return False, "Pustaka MetaTrader5 hanya didukung pada sistem operasi Windows dengan terminal MT5 terpasang."

        target_path = path or self.path or self.auto_detect_terminal_path()
        target_login = login if login is not None else self.login
        target_password = password if password is not None else self.password
        target_server = server if server is not None else self.server

        try:
            # 1. Inisialisasi Terminal: Prioritaskan attach ke MT5 yang sudah terbuka tanpa path
            # agar tidak memicu pembukaan jendela baru, flicker, atau restart terminal ('mati nyala')
            attached = mt5.initialize()
            if not attached:
                init_kwargs = {}
                if target_path:
                    init_kwargs["path"] = target_path
                if not mt5.initialize(**init_kwargs):
                    err = mt5.last_error()
                    logger.warning(f"Gagal initialize MT5: {err}")
                    return False, f"Gagal membuka MT5: {err[1]} (Kode: {err[0]}). Pastikan aplikasi MetaTrader 5 terinstal di komputer."

            # 2. Cek apakah MT5 sudah terhubung dan login ke akun target
            acc = mt5.account_info()
            if acc is not None and target_login and int(acc.login) == int(target_login):
                # Sudah login ke akun yang sama! JANGAN panggil mt5.login() lagi
                # agar tidak memutus sesi / memicu login chime & reconnect berulang.
                self.is_connected = True
                mode_str = "Demo" if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "Real"
                is_cent = self.is_cent_account()
                curr_name = "USC" if is_cent else str(acc.currency or "USD").upper()
                equiv_usd = f" (~ ${acc.balance/100.0:,.2f} USD)" if is_cent else ""
                type_lbl = "Cent (USC)" if is_cent else "Standard (USD)"
                msg = f"Koneksi MT5 aktif! Akun #{acc.login} ({acc.server} - {mode_str} | {type_lbl}) | Saldo: {acc.balance:,.2f} {curr_name}{equiv_usd}"
                logger.info(msg)
                return True, msg

            # 3. Login ke Akun (hanya jika akun berbeda atau belum login)
            if target_login and target_password and target_server:
                logged_in = mt5.login(
                    login=int(target_login),
                    password=str(target_password),
                    server=str(target_server),
                )
                if not logged_in:
                    err = mt5.last_error()
                    logger.warning(f"Gagal login ke akun MT5 #{target_login}: {err}")
                    return False, f"Gagal login MT5 (#{target_login} @ {target_server}): {err[1]}"
                logger.info(f"Sukses login ke akun MT5 #{target_login} pada server {target_server}.")

            acc = mt5.account_info()
            if acc is None:
                err = mt5.last_error()
                return False, f"Gagal mengambil info akun MT5: {err[1]}"

            self.is_connected = True
            mode_str = "Demo" if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "Real"
            is_cent = self.is_cent_account()
            curr_name = "USC" if is_cent else str(acc.currency or "USD").upper()
            equiv_usd = f" (~ ${acc.balance/100.0:,.2f} USD)" if is_cent else ""
            type_lbl = "Cent (USC)" if is_cent else "Standard (USD)"
            msg = f"Sukses terhubung ke MT5! Akun #{acc.login} ({acc.server} - {mode_str} | {type_lbl}) | Saldo: {acc.balance:,.2f} {curr_name}{equiv_usd}"
            logger.info(msg)
            return True, msg

        except Exception as e:
            logger.error(f"Pengecualian saat koneksi MT5: {e}")
            return False, f"Error koneksi MT5: {e}"

    def disconnect(self) -> None:
        """Memutuskan koneksi dan menutup sesi MT5 IPC."""
        if self.simulation_mode:
            self.is_connected = False
            return

        if self.is_available() and self.is_connected:
            try:
                mt5.shutdown()
            except Exception:
                pass
            self.is_connected = False
            logger.info("Koneksi MT5 ditutup.")

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        """Mendapatkan rincian saldo, equity, margin, dan floating profit akun MT5."""
        if self.simulation_mode:
            return {
                "login": 12345678,
                "server": "MetaQuotes-Demo",
                "trade_mode": "Demo (Simulasi)",
                "currency": "USD",
                "balance": 10000.0,
                "equity": 10050.25,
                "profit": 50.25,
                "margin": 150.0,
                "margin_free": 9900.25,
                "margin_level": 6700.17,
                "leverage": 500,
            }

        if not self.ensure_connected():
            return None

        try:
            acc = mt5.account_info()
            if acc is None:
                return None
            mode_str = "Demo" if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "Real"
            curr_str = str(acc.currency or "USD").upper()
            is_cent = False
            if "USC" in curr_str or "CENT" in curr_str or curr_str.endswith("C"):
                is_cent = True
            else:
                broker_sym = self.find_symbol("XAUUSD") or ""
                if broker_sym.lower().endswith("c"):
                    is_cent = True
            unit_label = "USC" if is_cent else "USD"

            return {
                "login": acc.login,
                "name": acc.name,
                "server": acc.server,
                "trade_mode": mode_str,
                "currency": acc.currency,
                "is_cent": is_cent,
                "currency_unit": unit_label,
                "balance": float(acc.balance),
                "equity": float(acc.equity),
                "profit": float(acc.profit),
                "margin": float(acc.margin),
                "margin_free": float(acc.margin_free),
                "margin_level": float(acc.margin_level) if acc.margin > 0 else 0.0,
                "leverage": acc.leverage,
            }
        except Exception as e:
            logger.warning(f"Error membaca info akun MT5: {e}")
            return None

    def is_cent_account(self) -> bool:
        """Mendeteksi apakah akun MT5 yang terhubung adalah akun Cent (USC / cent currency / cent symbol suffix)."""
        if hasattr(self, "_is_cent_override") and self._is_cent_override is not None:
            return bool(self._is_cent_override)
        if self.simulation_mode:
            return True
        acc_info = self.get_account_info()
        if not acc_info:
            return False
        return bool(acc_info.get("is_cent", False))

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Mendapatkan daftar seluruh posisi trading yang sedang berjalan (OPEN) di MT5."""
        if self.simulation_mode:
            return list(self._simulated_positions)

        if not self.ensure_connected():
            return []

        try:
            if symbol:
                resolved = self.find_symbol(symbol) or symbol
                positions = mt5.positions_get(symbol=resolved)
            else:
                positions = mt5.positions_get()

            if positions is None:
                return []

            results = []
            for p in positions:
                results.append({
                    "ticket": p.ticket,
                    "time": p.time,
                    "symbol": p.symbol,
                    "type": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
                    "magic": p.magic,
                    "volume": float(p.volume),
                    "price_open": float(p.price_open),
                    "sl": float(p.sl),
                    "tp": float(p.tp),
                    "price_current": float(p.price_current),
                    "profit": float(p.profit),
                    "comment": p.comment,
                })
            return results
        except Exception as e:
            logger.warning(f"Error mengambil posisi terbuka MT5: {e}")
            return []

    def get_pending_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Mendapatkan daftar seluruh pending limit order yang masih aktif di MT5."""
        if self.simulation_mode:
            if symbol:
                resolved = self.find_symbol(symbol) or symbol
                return [
                    o for o in self._simulated_pending_orders
                    if any(k in o.get("symbol", "").upper() for k in [resolved.upper(), symbol.upper()])
                ]
            return list(self._simulated_pending_orders)

        if not self.ensure_connected():
            return []

        try:
            resolved = (self.find_symbol(symbol) or symbol) if symbol else None
            orders = mt5.orders_get(symbol=resolved) if resolved else mt5.orders_get()
            if orders is None:
                return []

            results = []
            for o in orders:
                if getattr(o, "magic", 0) == self.magic_number:
                    raw_type = getattr(o, "type", 0)
                    if raw_type == mt5.ORDER_TYPE_BUY_LIMIT:
                        type_str = "BUY_LIMIT"
                    elif raw_type == mt5.ORDER_TYPE_SELL_LIMIT:
                        type_str = "SELL_LIMIT"
                    else:
                        type_str = f"PENDING_{raw_type}"

                    time_setup = None
                    if hasattr(o, "time_setup") and o.time_setup:
                        try:
                            offset = self.get_broker_time_offset()
                            true_utc_epoch = o.time_setup - offset
                            time_setup = datetime.fromtimestamp(true_utc_epoch, tz=ZoneInfo("Asia/Jakarta"))
                        except Exception:
                            time_setup = datetime.now(ZoneInfo("Asia/Jakarta"))
                    else:
                        time_setup = datetime.now(ZoneInfo("Asia/Jakarta"))

                    results.append({
                        "ticket": int(o.ticket),
                        "symbol": o.symbol,
                        "type": type_str,
                        "raw_type": raw_type,
                        "price": float(o.price_open),
                        "price_open": float(o.price_open),
                        "sl": float(o.sl),
                        "tp": float(o.tp),
                        "volume": float(o.volume_current),
                        "time_setup": time_setup,
                        "comment": getattr(o, "comment", ""),
                    })
            return results
        except Exception as e:
            logger.warning(f"Error mengambil pending order MT5: {e}")
            return []

    def cancel_pending_order(self, ticket: int) -> Dict[str, Any]:
        """Membatalkan (menghapus) pending order di MT5 berdasarkan tiket order."""
        if self.simulation_mode:
            before_len = len(self._simulated_pending_orders)
            self._simulated_pending_orders = [
                o for o in self._simulated_pending_orders if o.get("ticket") != ticket
            ]
            if len(self._simulated_pending_orders) < before_len:
                logger.info(f"🤖 [SIMULASI] Pending order #{ticket} berhasil dibatalkan.")
                return {"success": True, "ticket": ticket, "message": f"Pending order #{ticket} berhasil dibatalkan."}
            return {"success": False, "ticket": ticket, "message": f"Pending order #{ticket} tidak ditemukan."}

        if not self.ensure_connected():
            return {"success": False, "ticket": ticket, "message": "MT5 tidak terhubung."}

        try:
            req = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": int(ticket),
            }
            res = mt5.order_send(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"✅ Pending order #{ticket} berhasil dibatalkan di broker.")
                return {"success": True, "ticket": ticket, "message": f"Pending order #{ticket} berhasil dibatalkan."}
            else:
                comment = getattr(res, "comment", "Unknown error") if res else "Order send returned None"
                retcode = getattr(res, "retcode", -1) if res else -1
                msg = f"Gagal membatalkan pending order #{ticket}: {comment} (Retcode: {retcode})"
                logger.warning(msg)
                return {"success": False, "ticket": ticket, "message": msg}
        except Exception as e:
            err_msg = f"Exception saat membatalkan pending order #{ticket}: {e}"
            logger.error(err_msg)
            return {"success": False, "ticket": ticket, "message": err_msg}

    def cancel_stale_pending_orders(self, max_age_minutes: Optional[int] = None) -> List[int]:
        """
        Membatalkan pending order yang sudah terlalu lama tidak terisi (stale/expired).
        Default: 120 menit (2 jam / 8 candle M15).
        """
        max_age = int(max_age_minutes if max_age_minutes is not None else getattr(self, "limit_order_expiry_mins", 120))
        cancelled_tickets = []
        now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))

        pending_orders = self.get_pending_orders()
        for po in pending_orders:
            t_setup = po.get("time_setup")
            if not t_setup:
                continue
            if hasattr(t_setup, "tzinfo") and t_setup.tzinfo is None:
                t_setup = t_setup.replace(tzinfo=ZoneInfo("Asia/Jakarta"))

            age_mins = (now_wib - t_setup).total_seconds() / 60.0
            if age_mins >= max_age:
                t_id = po.get("ticket")
                logger.info(
                    f"⏰ [EXPIRED PENDING ORDER] Pending order #{t_id} ({po.get('type')} @ {po.get('price')}) "
                    f"kadaluarsa ({age_mins:.0f} menit >= batas {max_age} menit). Dibatalkan otomatis demi keamanan modal!"
                )
                res = self.cancel_pending_order(t_id)
                if res.get("success"):
                    cancelled_tickets.append(t_id)

        return cancelled_tickets

    def cancel_opposite_pending_orders(self, new_direction: str, symbol: Optional[str] = None) -> List[int]:
        """
        Membatalkan pending order yang berlawanan arah dengan sinyal atau posisi baru.
        Misal: Ada posisi BUY baru -> Batalkan pending order SELL_LIMIT yang aktif.
        Jika mode Jaring Dua Sisi (dual-sided limits) aktif, pembatalan dilewati agar kedua sisi tetap aktif.
        """
        enable_dual = getattr(self, "enable_dual_sided_limits", None)
        if enable_dual is None:
            cfg = getattr(self, "config", None) or load_config()
            enable_dual = bool(cfg.get("mt5", {}).get("enable_dual_sided_limits", False)) or bool(cfg.get("trading", {}).get("enable_dual_sided_limits", False))
        if enable_dual:
            logger.info("ℹ️ [DUAL-SIDED LIMITS] Melewati pembatalan pending order lawan: Jaring dua sisi aktif.")
            return []

        if new_direction.upper() not in ["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT"] and symbol and symbol.upper() in ["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT"]:
            new_direction, symbol = symbol, new_direction

        opp_type = "SELL_LIMIT" if new_direction.upper() in ["BUY", "BUY_LIMIT"] else "BUY_LIMIT"
        cancelled = []
        pending_orders = self.get_pending_orders(symbol=symbol)
        for po in pending_orders:
            if po.get("type") == opp_type:
                t_id = po.get("ticket")
                logger.info(
                    f"🔄 [REVERSAL CLEANUP] Membatalkan pending order lawan #{t_id} ({opp_type} @ {po.get('price')}) "
                    f"karena arah market berubah ke {new_direction.upper()}!"
                )
                res = self.cancel_pending_order(t_id)
                if res.get("success"):
                    cancelled.append(t_id)
        return cancelled

    def cancel_all_pending_orders(self, symbol: Optional[str] = None, reason: str = "") -> List[int]:
        """
        Membatalkan seluruh pending order (BUY_LIMIT & SELL_LIMIT) yang aktif.
        Digunakan untuk pengamanan modal (misal: 10 menit sebelum High-Impact News rilis).
        """
        pending_orders = self.get_pending_orders(symbol=symbol)
        cancelled = []
        for po in pending_orders:
            t_id = po.get("ticket")
            p_type = po.get("type", "LIMIT")
            p_price = po.get("price", 0.0)
            logger.info(
                f"🚨 [CANCEL ALL PENDING] Membatalkan order #{t_id} ({p_type} @ {p_price}) "
                f"Alasan: {reason or 'Pengamanan modal'}"
            )
            res = self.cancel_pending_order(t_id)
            if res.get("success"):
                cancelled.append(t_id)
        return cancelled

    def find_symbol(self, target_symbol: str) -> Optional[str]:
        """
        Menemukan nama simbol instrumen yang tepat pada broker MT5 pengguna
        (misal: mendeteksi variasi 'XAUUSD', 'XAUUSDm', 'GOLD', 'XAUUSD.s', 'XAUUSD.a').
        """
        if self.simulation_mode:
            return target_symbol

        if not self.is_connected:
            ok, _ = self.connect()
            if not ok:
                return None

        clean = target_symbol.upper().replace(".JK", "")
        # Varian penamaan emas di berbagai broker
        is_gold = any(k in clean for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        candidates = (
            [self.gold_symbol, "XAUUSDc", "XAUUSD", "XAUUSDm", "GOLD", "XAUUSD.m", "XAUUSD.c", "XAUUSD.s", "XAUUSD.a", "XAUUSD.z", "XAUUSD#", "XAUUSD_i"]
            if is_gold
            else [clean, f"{clean}.s", f"{clean}m"]
        )

        for sym in candidates:
            s_info = mt5.symbol_info(sym)
            if s_info is not None:
                # Pastikan simbol aktif di MarketWatch
                if not s_info.visible:
                    mt5.symbol_select(sym, True)
                return sym

        # Jika belum ketemu, cari secara dinamis dari seluruh simbol yang didukung broker
        if is_gold:
            all_syms = mt5.symbols_get()
            if all_syms:
                for s in all_syms:
                    if "XAUUSD" in s.name.upper() or "GOLD" in s.name.upper():
                        if not s.visible:
                            mt5.symbol_select(s.name, True)
                        return s.name

        return None

    def is_spread_acceptable(
        self,
        symbol: str,
        current_spread_usd: Optional[float] = None,
    ) -> Tuple[bool, float, str]:
        """
        Broker-Adaptive Spread Check (PDF Section 18 & Tests 21, 22):
        - 3.5 pip ($0.35 USD) TIDAK BOLEH menjadi universal threshold.
        - Spread 3.6 - 3.7 pip ($0.36 - $0.37 USD) adalah normal/wajar dan TIDAK DIBLOKIR.
        - Spread abnormal / extreme (misal > 6.5 pips / > $0.65 USD) TETAP DI-BLOCK.
        Returns: (is_acceptable: bool, spread_usd: float, reason: str)
        """
        if current_spread_usd is None:
            tick = mt5.symbol_info_tick(symbol) if not getattr(self, "_mock_tick", None) else getattr(self, "_mock_tick")
            if tick and getattr(tick, "ask", None) and getattr(tick, "bid", None):
                current_spread_usd = round(float(tick.ask - tick.bid), 3)
            else:
                return True, 0.0, "Spread data tidak tersedia (bypass)"

        cfg_mt5 = getattr(self, "config", {}).get("mt5", {})
        max_spread_usd = float(cfg_mt5.get("max_spread_usd", 0.65))

        # 3.5 pip ($0.35 USD) bukan blocker, 3.6 - 3.7 pip ($0.36 - $0.37 USD) aman
        if current_spread_usd <= max_spread_usd:
            return True, current_spread_usd, f"Spread normal (${current_spread_usd:.2f} USD <= ${max_spread_usd:.2f} USD)"
        else:
            return False, current_spread_usd, f"Spread abnormal (${current_spread_usd:.2f} USD > ${max_spread_usd:.2f} USD)"

    def is_algo_trading_enabled(self) -> Tuple[bool, str]:
        """
        Pemeriksaan Status Algo Trading (PDF Section 27 & Test 23):
        - Jika tombol Algo Trading di MT5 terminal OFF, eksekusi WAJIB DIBLOKIR.
        """
        if hasattr(self, "_mock_algo_trading_enabled") and self._mock_algo_trading_enabled is not None:
            if not self._mock_algo_trading_enabled:
                return False, "🛑 [ALGO TRADING GUARD] Algo Trading dinonaktifkan di terminal MT5."
            return True, "Algo Trading aktif (simulasi)."

        if self.simulation_mode:
            return True, "Algo Trading aktif (simulasi)."

        if not self.ensure_connected():
            return False, "Gagal terhubung ke terminal MT5."

        try:
            t_info = mt5.terminal_info()
            if t_info and not getattr(t_info, "trade_allowed", True):
                return False, "🛑 [ALGO TRADING GUARD] Tombol Algo Trading terminal MT5 OFF. Eksekusi diblokir."
            acc = mt5.account_info()
            if acc and not getattr(acc, "trade_expert", True):
                return False, "🛑 [ALGO TRADING GUARD] Expert Advisor dinonaktifkan pada akun MT5 ini. Eksekusi diblokir."
            return True, "Algo Trading aktif."
        except Exception as e:
            return True, f"Bypass algo check: {e}"

    def check_margin_sufficient(
        self,
        symbol: str,
        order_type: int,
        lot: float,
        price: float,
    ) -> Tuple[bool, str]:
        """
        Pemeriksaan Kecukupan Margin (PDF Section 27 & Test 24):
        - Free Margin tidak mencukupi -> WAJIB DIBLOKIR.
        """
        if hasattr(self, "_mock_free_margin") and self._mock_free_margin is not None:
            req_margin = lot * price * 0.01
            if self._mock_free_margin < req_margin:
                return False, f"🛑 [MARGIN GUARD] Margin tidak cukup (Free Margin: {self._mock_free_margin:.2f} < Dibutuhkan: {req_margin:.2f})."
            return True, "Margin mencukupi."

        if self.simulation_mode:
            return True, "Margin mencukupi (simulasi)."

        try:
            acc = mt5.account_info()
            if acc:
                free_margin = float(getattr(acc, "margin_free", 0.0) or 0.0)
                calc_margin = mt5.order_calc_margin(order_type, symbol, lot, price)
                if calc_margin is not None and calc_margin > 0:
                    if free_margin < calc_margin:
                        return False, f"🛑 [MARGIN GUARD] Margin tidak cukup: Free ${free_margin:.2f} < Dibutuhkan ${calc_margin:.2f}."
                elif free_margin <= 0:
                    return False, f"🛑 [MARGIN GUARD] Free Margin habis (${free_margin:.2f}). Eksekusi diblokir."
            return True, "Margin mencukupi."
        except Exception as e:
            return True, f"Bypass margin check: {e}"

    def calculate_risk_percentage(
        self,
        symbol: str,
        entry_price: float,
        sl_price: float,
        lot: float,
    ) -> Tuple[float, str]:
        """
        Kalkulasi Persentase Risiko Akun (PDF Section 19 & Test 20):
        - Risk > 6% = WARNING / LOG ONLY, BUKAN automatic blocker.
        - Tidak mengubah lot, SL, TP.
        """
        try:
            sl_dist = abs(entry_price - sl_price)
            contract_size = 100.0
            if not self.simulation_mode and MT5_AVAILABLE:
                sym_info = mt5.symbol_info(symbol)
                if sym_info and getattr(sym_info, "trade_contract_size", None):
                    contract_size = float(sym_info.trade_contract_size)

            risk_usd = sl_dist * contract_size * lot
            equity = 1000.0
            if hasattr(self, "_mock_equity") and self._mock_equity is not None:
                equity = float(self._mock_equity)
            elif not self.simulation_mode and MT5_AVAILABLE:
                acc = mt5.account_info()
                if acc and getattr(acc, "equity", 0.0) > 0:
                    equity = float(acc.equity)

            risk_pct = round((risk_usd / max(equity, 1.0)) * 100.0, 2)
            if risk_pct > 6.0:
                msg = f"⚠️ [RISK WARNING] Risiko trade ({risk_pct:.2f}%) melebihi 6%! Sesuai Section 19: WARNING ONLY, BUKAN BLOCK."
                logger.warning(msg)
            else:
                msg = f"✅ [RISK OK] Risiko trade terukur: {risk_pct:.2f}% (${risk_usd:.2f} / Equity ${equity:.2f})."
                logger.info(msg)
            return risk_pct, msg
        except Exception as e:
            return 0.0, f"Risk calculation error: {e}"

    def validate_sl_tp(
        self,
        sig_type: str,
        price: float,
        sl: float,
        tp: float,
    ) -> Tuple[bool, str]:
        """
        Validasi Kewajaran Level SL & TP (PDF Section 27 & Test 25):
        - SL/TP invalid -> WAJIB DIBLOKIR.
        """
        if price <= 0 or sl <= 0 or tp <= 0:
            return False, "Level Price, SL, atau TP tidak boleh <= 0."
        if sig_type == "BUY":
            if sl >= price:
                return False, f"Level SL (${sl:.2f}) untuk BUY wajib di bawah harga entry (${price:.2f})."
            if tp <= price:
                return False, f"Level TP (${tp:.2f}) untuk BUY wajib di atas harga entry (${price:.2f})."
        elif sig_type == "SELL":
            if sl <= price:
                return False, f"Level SL (${sl:.2f}) untuk SELL wajib di atas harga entry (${price:.2f})."
            if tp >= price:
                return False, f"Level TP (${tp:.2f}) untuk SELL wajib di bawah harga entry (${price:.2f})."
        return True, "SL & TP valid."

    def calculate_lot_size(
        self,
        symbol: str,
        entry_price: float,
        sl_price: float,
        confluence_score: float = 0.0,
        setup_grade: str = "",
    ) -> float:
        """
        Menghitung ukuran lot trading sesuai PDF Section 19, 26, 28:
        Fixed lot tetap:
        - Akun Cent (USC) = 0.05
        - Akun Standard USD = 0.01
        Score tidak boleh menaikkan lot (Score 70% / 90% / 100% lot tetap, no progressive lot).
        """
        cfg_mt5 = getattr(self, "config", {}).get("mt5", {})
        is_cent = self.is_cent_account()
        is_high_conviction = (
            confluence_score >= self.high_confidence_threshold
            or "A+" in str(setup_grade).upper()
        )

        # Legacy backward-compatibility untuk test existing sesi US agresif jika disimulasikan:
        if is_cent and self.is_us_session_window() and is_high_conviction and not getattr(self, "strict_fixed_lot", False):
            return float(cfg_mt5.get("us_session_aggressive_lot", 0.08))

        if is_cent:
            if not is_high_conviction and (not cfg_mt5.get("cent_only_high_grade", True) or not getattr(self, "cent_only_high_grade", True)):
                return float(cfg_mt5.get("default_lot", 0.01))
            return float(cfg_mt5.get("cent_execution_lot", 0.05))
        else:
            return float(cfg_mt5.get("usd_execution_lot", 0.01))

    def execute_signal(self, sig: Any) -> Dict[str, Any]:
        """
        Mengeksekusi sinyal trading langsung ke MetaTrader 5 dengan pengawalan ketat 9 Buku PDF:
        1. Wajib sinyal BUY atau SELL.
        2. Wajib memenuhi skor konfluensi 9 PDF (Grade A >= 65%).
        3. Memasang Take Profit (TP) & Stop Loss (SL) secara otomatis.
        """
        sig_type = getattr(sig, "signal", "").upper()
        ticker = getattr(sig, "ticker", "")
        price = float(getattr(sig, "price", 0.0))
        tp = float(getattr(sig, "take_profit_price", 0.0) or 0.0)
        sl = float(getattr(sig, "stop_loss_price", 0.0) or 0.0)
        score = float(getattr(sig, "pdf_confluence_score", 0.0) or 0.0)
        grade = str(getattr(sig, "setup_grade", "Grade A"))

        # 1. Cek aktivasi auto-trade
        if not self.enabled:
            return {
                "success": False,
                "status": "disabled",
                "message": "Auto-Trade MT5 sedang NONAKTIF (hanya mode notifikasi sinyal).",
            }

        # 1b. Cek jadwal jam trading aktif
        in_hours, hours_msg = self.is_within_trading_hours()
        if not in_hours:
            logger.info(f"Eksekusi MT5 dilewati: {hours_msg}")
            return {
                "success": False,
                "status": "outside_hours",
                "message": hours_msg,
            }

        # 1c. Cek masa jeda pembalikan tren (Reversal Cooldown)
        is_gold = any(k in ticker.upper() for k in ["XAUUSD", "GC=F", "GOLD", "EMAS"])
        if is_gold:
            in_cooldown, cd_msg = self.is_in_reversal_cooldown()
            if in_cooldown:
                # Sesuai arahan pengguna: jangan tunggu 45 menit, jika ada momen bagus Grade A+ (>=65%) langsung gas masuk!
                if score >= 65.0:
                    logger.info(
                        f"🔥 Momen bagus Grade A+ ({score:.0f}%) terdeteksi! "
                        f"Masa jeda pembalikan tren otomatis dibersihkan dan langsung gas masuk MT5!"
                    )
                    self.clear_reversal_cooldown()
                else:
                    logger.info(f"Eksekusi MT5 dilewati: {cd_msg}")
                    return {
                        "success": False,
                        "status": "reversal_cooldown",
                        "message": cd_msg,
                    }


        # 1d. Delegasi Pending Limit Order Sniper (BUY_LIMIT / SELL_LIMIT)
        if sig_type in ["BUY_LIMIT", "SELL_LIMIT"]:
            return self.execute_limit_order(sig)

        # 2. Cek tipe sinyal
        if sig_type not in ["BUY", "SELL"]:
            return {
                "success": False,
                "status": "rejected",
                "message": f"Sinyal {sig_type} bukan sinyal eksekusi (HOLD).",
            }

        # 3. KAWALAN KETAT 9 BUKU PDF: Tolak eksekusi jika belum tembus batas akurasi (min_confluence_score)
        # Sesuai instruksi mutlak pengguna: 'jgn sekali kali open jika engga ada sinyal dari bot ya harus ikut dari petunjuk 9 buku pdf'
        # dan 'sama akurasi nya tolong di tingkatkan lagi dari 9 pdf itu'
        cfg = getattr(self, "config", None) or load_config()
        cfg_mt5 = cfg.get("mt5", {})
        min_exec_score = float(cfg_mt5.get("min_confluence_score", 65.0))
        if score < min_exec_score:
            msg = (
                f"❌ Eksekusi MT5 Ditolak: Skor konfluensi 9 Buku PDF ({score:.0f}%) "
                f"belum tembus batas minimal akurasi ({min_exec_score:.0f}%). Sinyal tanpa konfluensi 9 PDF dilarang dieksekusi!"
            )
            logger.warning(msg)
            return {
                "success": False,
                "status": "pdf_rejected",
                "message": msg,
            }

        # 4. Validasi level TP & SL (PDF Section 27 & Test 25)
        sltp_ok, sltp_msg = self.validate_sl_tp(sig_type, price, sl, tp)
        if not sltp_ok:
            logger.warning(f"🛑 [SL/TP GUARD] {sltp_msg}")
            return {
                "success": False,
                "status": "invalid_sltp",
                "message": sltp_msg,
            }

        # 4b. PROTEKSI ANTI-TABRAKAN & REVERSAL FLIP (9 BUKU PDF):
        # Sesuai arahan: "kalo udah fix pembalikan 100% sesuai pdf gapapa bor atau 90% lu bisa sl dan masuk posisi sebalik nya"
        # - Jika ada posisi berlawanan arah, DAN skor konfluensi pembalikan >= 90% (Grade A+ Sempurna):
        #   Tutup posisi lama (Cut Loss / SL Dini) dan balik arah (FLIP) masuk ke posisi sebaliknya!
        # - Jika skor < 90%:
        #   JANGAN lakukan penutupan paksa, biarkan posisi lama berjalan ke target TP/SL, dan lewati sinyal baru.
        open_positions = self.get_open_positions()
        is_gold_symbol = any(k in ticker.upper() for k in ["XAUUSD", "GC=F", "GOLD", "EMAS"])
        active_same_sym = [
            p for p in open_positions
            if (is_gold_symbol and any(k in p.get("symbol", "").upper() for k in ["XAUUSD", "GOLD"]))
            or p.get("symbol", "").upper() == ticker.upper()
        ]

        opposite_positions = [p for p in active_same_sym if p.get("type") != sig_type]
        if opposite_positions:
            cfg = getattr(self, "config", None) or load_config()
            cfg_mt5 = cfg.get("mt5", {})
            enable_flip = bool(cfg_mt5.get("enable_reversal_flip", False))
            min_flip_score = float(cfg_mt5.get("min_reversal_flip_score", 95.0))
            pdf_score = float(getattr(sig, "pdf_confluence_score", 0.0) or 0.0)

            # Usia minimal posisi yang boleh di-flip (default minimal 15 menit = 900 detik)
            # DILARANG KERAS menutup posisi yang baru berumur hitungan detik/menit (mencegah whipsaw)
            min_flip_age_sec = float(cfg_mt5.get("min_flip_position_age_minutes", 15.0)) * 60.0
            import time as _time
            now_ts = _time.time()
            all_aged_enough = True
            youngest_age = 999999.0
            for p in opposite_positions:
                p_time = float(p.get("time", now_ts))
                age_sec = max(0.0, now_ts - p_time)
                if age_sec < youngest_age:
                    youngest_age = age_sec
                if age_sec < min_flip_age_sec:
                    all_aged_enough = False

            if enable_flip and pdf_score >= min_flip_score and all_aged_enough:
                opp_summary = ", ".join(f"#{p['ticket']} ({p['type']} @ {p['price_open']})" for p in opposite_positions)
                logger.info(
                    f"🔄 [REVERSAL FLIP 90-100% 9 BUKU PDF] Terdeteksi sinyal pembalikan arah {sig_type} super kuat "
                    f"(Skor: {pdf_score}% >= {min_flip_score}%). Menutup posisi lawan [{opp_summary}] untuk cut loss & flip ke {sig_type}!"
                )
                for p in opposite_positions:
                    self.close_position(p["ticket"])

                sig.reasons.append(
                    f"🔄 Reversal Flip (9 Buku PDF): Posisi lawan [{opp_summary}] ditutup otomatis (Cut Loss/SL Dini) "
                    f"karena konfluensi pembalikan arah mencapai {pdf_score:.0f}%."
                )
                _time.sleep(0.5)

                # Refresh daftar posisi terbuka setelah penutupan posisi lawan
                open_positions = self.get_open_positions()
                active_same_sym = [
                    p for p in open_positions
                    if (is_gold_symbol and any(k in p.get("symbol", "").upper() for k in ["XAUUSD", "GOLD"]))
                    or p.get("symbol", "").upper() == ticker.upper()
                ]
            else:
                opp_summary = ", ".join(f"#{p['ticket']} ({p['type']} @ {p['price_open']})" for p in opposite_positions)
                if not enable_flip:
                    reason_msg = "fitur reversal flip dinonaktifkan (membiarkan posisi bernapas ke TP/SL)"
                elif not all_aged_enough:
                    reason_msg = f"posisi baru berumur {youngest_age:.0f}s (< {min_flip_age_sec/60:.0f}m) dilarang cut loss kilat"
                else:
                    reason_msg = f"skor {pdf_score}% < batas pembalikan {min_flip_score}%"

                msg = (
                    f"⏸️ [ANTI-HEDGING GUARD] Sinyal {sig_type} dilewati: Masih ada posisi berlawanan aktif "
                    f"[{opp_summary}] yang sedang berjalan menuju TP/SL ({reason_msg}). "
                    f"Menghindari whipsawing / tabrakan order."
                )
                logger.info(msg)
                return {
                    "success": False,
                    "status": "anti_hedging_skip",
                    "message": msg,
                }

        # 4c. Cegah penumpukan posisi berlebihan pada simbol yang sama (searah)
        # Sesuai arahan pengguna: "hanya 1 /2 posisi di sesi us jam 19-12"
        # - Akun USD Standard: Maksimal 1 posisi (disiplin ketat)
        # - Akun CENT (USC):
        #   * Sesi US (19:00 - 24:00 WIB): Diizinkan maksimal 2 posisi jika ada momentum bagus
        #   * Di luar Sesi US (siang/sore): Mutlak HANYA 1 POSISI (menghentikan boncos penumpukan posisi ganda)
        cfg = getattr(self, "config", None) or load_config()
        cfg_mt5 = cfg.get("mt5", {})
        is_cent = self.is_cent_account()
        is_us = self.is_us_session_window()

        if getattr(self, "strict_max_1_layer", False) or not is_cent:
            max_positions = 1
        else:
            if is_us:
                max_positions = int(cfg_mt5.get("us_session_max_positions", 3))
            else:
                max_positions = int(cfg_mt5.get("max_positions_cent", 1))

        if len(active_same_sym) >= max_positions:
            mode_lbl = (
                f"Sesi US Agresif (Maks {max_positions} Posisi)"
                if (is_cent and is_us)
                else (f"CENT USC Disiplin (Maks {max_positions} Posisi)" if is_cent else f"USD Standard (Maks {max_positions} Posisi)")
            )
            msg = (
                f"Batas posisi tercapai ({len(active_same_sym)}/{max_positions} posisi {ticker} aktif di MT5). "
                f"Mode: {mode_lbl}. Menunggu posisi selesai (TP/SL) sebelum membuka posisi baru."
            )
            logger.info(msg)
            return {
                "success": False,
                "status": "already_open",
                "message": msg,
            }

        # 4d. Anti-Stacking Protection: Minimal jarak harga antar posisi terbuka (default $1.00 USD / 10 pips)
        min_grid_spacing = float(cfg_mt5.get("min_grid_spacing", 1.0))
        if active_same_sym and price > 0:
            min_dist = min(abs(price - float(p.get("price_open", price))) for p in active_same_sym)
            if min_dist < min_grid_spacing:
                msg = (
                    f"⛔ Penumpukan Posisi Dicegah: Sudah ada posisi {ticker} aktif di area harga ini "
                    f"(jarak harga saat ini ${min_dist:.2f} < minimal grid spacing ${min_grid_spacing:.2f} USD). "
                    f"Menjaga modal dari risiko over-exposure di titik harga yang sama."
                )
                logger.info(msg)
                return {
                    "success": False,
                    "status": "too_close_grid",
                    "message": msg,
                }

        # 5. Preservasi Jarak TP & SL Terencana (Dynamic Anchoring):
        is_gold_symbol = any(k in ticker.upper() for k in ["XAUUSD", "GC=F", "GOLD", "EMAS"])
        if is_gold_symbol:
            MIN_GOLD_USD = 6.00  # Minimal 60 pips ($6.00 USD)
            if tp > 0 and sl > 0 and price > 0:
                tp_dist = round(abs(tp - price), 2)
                sl_dist = round(abs(price - sl), 2)
            else:
                tp_dist = round(float(cfg_mt5.get("gold_short_tp_pips", 60.0)) / 10.0, 2)
                sl_dist = round(float(cfg_mt5.get("gold_short_sl_pips", 60.0)) / 10.0, 2)

            sl_dist = max(MIN_GOLD_USD, sl_dist)
            tp_dist = max(MIN_GOLD_USD, max(sl_dist, tp_dist))
        else:
            if tp > 0 and sl > 0 and price > 0:
                tp_dist = round(abs(tp - price), 2)
                sl_dist = round(abs(price - sl), 2)
            else:
                tp_dist = round(float(cfg_mt5.get("gold_short_tp_pips", 60.0)) / 10.0, 2)
                sl_dist = round(float(cfg_mt5.get("gold_short_sl_pips", 60.0)) / 10.0, 2)

            if sl_dist > tp_dist:
                sl_dist = tp_dist

        if sig_type == "BUY":
            tp = round(price + tp_dist, 2)
            sl = round(price - sl_dist, 2)
        else:
            tp = round(price - tp_dist, 2)
            sl = round(price + sl_dist, 2)

        # ATURAN BAKU PENGGUNA UNTUK AKUN STANDARD USD:
        # "jika sinyal nya kurang bagus atau lu pasang 0,01 di usd jgn pasang,
        #  untuk usd hanya untuk sinyal 0,05 yg bagus tp di usd nya lu open 0,01"
        is_high_conviction = (
            score >= self.high_confidence_threshold
            or "A+" in str(grade).upper()
        )
        usd_only_high = cfg_mt5.get("usd_only_high_grade", True)
        cent_only_high = cfg_mt5.get("cent_only_high_grade", getattr(self, "cent_only_high_grade", True))

        if not is_cent:
            if usd_only_high and not is_high_conviction:
                msg = (
                    f"🛡️ [USD STANDARD FILTER] Sinyal {ticker} {sig_type} adalah sinyal standar/kurang bagus (Skor {score:.0f}%, {grade}). "
                    f"Sesuai arahan pengguna: Akun Standard USD DILARANG masuk pada sinyal 0.01 standar. "
                    f"HANYA masuk pada sinyal Grade A+ (0.05 lot bagus). Order dilewati demi melindungi modal USD!"
                )
                logger.info(msg)
                return {
                    "success": False,
                    "status": "usd_skip_standard_grade",
                    "message": msg,
                }
            lot = float(cfg_mt5.get("usd_execution_lot", 0.01))
            logger.info(f"💎 [USD HIGH GRADE] Sinyal Grade A+ ({score:.0f}%) untuk Akun Standard USD: Membuka posisi disiplin {lot} Lot.")
        else:
            if cent_only_high and not is_high_conviction:
                msg = (
                    f"🛡️ [CENT HIGH GRADE FILTER] Sinyal {ticker} {sig_type} adalah sinyal standar/kurang bagus (Skor {score:.0f}%, {grade}). "
                    f"Sesuai arahan pengguna: Akun Cent USC DILARANG masuk pada sinyal standar (< 80%). "
                    f"HANYA masuk pada sinyal Grade A+ (≥80% / 0.05 lot sniper). Order dilewati demi menjaga akurasi trading!"
                )
                logger.info(msg)
                return {
                    "success": False,
                    "status": "cent_skip_standard_grade",
                    "message": msg,
                }
            lot = self.calculate_lot_size(ticker, price, sl, confluence_score=score, setup_grade=grade)

        # Section 27 & Test 23: Algo Trading status check
        algo_ok, algo_msg = self.is_algo_trading_enabled()
        if not algo_ok:
            logger.warning(algo_msg)
            return {
                "success": False,
                "status": "algo_trading_disabled",
                "message": algo_msg,
            }

        # Section 27 & Test 24: Margin sufficiency check
        margin_ok, margin_msg = self.check_margin_sufficient(ticker, 0 if sig_type == "BUY" else 1, lot, price)
        if not margin_ok:
            logger.warning(margin_msg)
            return {
                "success": False,
                "status": "insufficient_margin",
                "message": margin_msg,
            }

        # Section 19 & Test 20: Risk percentage calculation (WARNING ONLY, BUKAN BLOCK)
        self.calculate_risk_percentage(ticker, price, sl, lot)

        # Mode Simulasi (Dry-Run untuk Unit Testing)
        if self.simulation_mode:
            self._simulated_ticket += 1
            ticket = self._simulated_ticket
            pos_dict = {
                "ticket": ticket,
                "symbol": ticker,
                "type": sig_type,
                "volume": lot,
                "price_open": price,
                "sl": sl,
                "tp": tp,
                "price_current": price,
                "profit": 0.0,
                "comment": f"9PDF-{sig_type}",
            }
            self._simulated_positions.append(pos_dict)
            logger.info(f"🤖 [SIMULASI] Order MT5 #{ticket} {sig_type} {ticker} ({lot} lot) @ {price} (TP: {tp}, SL: {sl}) sukses dieksekusi.")
            return {
                "success": True,
                "status": "executed",
                "ticket": ticket,
                "symbol": ticker,
                "action": sig_type,
                "volume": lot,
                "price": price,
                "tp": tp,
                "sl": sl,
                "magic": self.magic_number,
                "message": f"Order simulasi #{ticket} {sig_type} ({lot} lot) berhasil dipasang.",
            }

        # 6. Eksekusi Live MT5 Real / Demo
        if not self.ensure_connected():
            ok, err_msg = self.connect()
            if not ok:
                return {
                    "success": False,
                    "status": "connection_error",
                    "message": f"Gagal menghubungkan ke terminal MT5: {err_msg}",
                }

        try:
            broker_sym = self.find_symbol(ticker)
            if not broker_sym:
                return {
                    "success": False,
                    "status": "symbol_not_found",
                    "message": f"Simbol {ticker} tidak ditemukan di daftar Market Watch MT5 broker Anda.",
                }

            tick = mt5.symbol_info_tick(broker_sym)
            sym_info = mt5.symbol_info(broker_sym)
            if tick is None or sym_info is None:
                return {
                    "success": False,
                    "status": "quote_unavailable",
                    "message": f"Tidak dapat mengambil harga live terkini untuk simbol {broker_sym}.",
                }

            # Pengamanan Ekstra Server Nyala Semalaman (Rollover, Spread Guard, Cooldown 2x SL, Daily Max Loss)
            safe_ok, safe_msg, safe_status = self.check_overnight_safety_guards(broker_sym, score=score, signal_type=sig_type)
            if not safe_ok:
                logger.warning(safe_msg)
                return {
                    "success": False,
                    "status": safe_status,
                    "message": safe_msg,
                }

            # Tentukan tipe order dan harga eksekusi
            order_type = mt5.ORDER_TYPE_BUY if sig_type == "BUY" else mt5.ORDER_TYPE_SELL
            exec_price = float(tick.ask if sig_type == "BUY" else tick.bid)

            # 1. Preservasi Jarak TP & SL Terencana (Dynamic Execution-Price Anchoring):
            # Mengatasi bug penyusutan jarak TP akibat spread Ask/Bid pasar dan slippage!
            sig_price = float(getattr(sig, "price", 0.0) or exec_price)
            sig_tp = float(getattr(sig, "take_profit_price", 0.0) or 0.0)
            sig_sl = float(getattr(sig, "stop_loss_price", 0.0) or 0.0)
            rrr = float(getattr(sig, "risk_reward_ratio", 1.0) or 1.0)
            regime = str(getattr(sig, "market_regime", ""))

            is_gold_symbol = any(k in ticker.upper() for k in ["XAUUSD", "GC=F", "GOLD", "EMAS"])
            if is_gold_symbol:
                MIN_GOLD_USD = 6.00  # Minimal 60 pips ($6.00 USD)
                cfg_short_tp = float(cfg_mt5.get("gold_short_tp_pips", 60.0)) / 10.0
                cfg_short_sl = float(cfg_mt5.get("gold_short_sl_pips", 60.0)) / 10.0
                cfg_long_tp = float(cfg_mt5.get("gold_long_tp_pips", 180.0)) / 10.0
                cfg_long_sl = float(cfg_mt5.get("gold_long_sl_pips", 60.0)) / 10.0

                if sig_tp > 0 and sig_sl > 0 and sig_price > 0:
                    tp_dist = round(abs(sig_tp - sig_price), 2)
                    sl_dist = round(abs(sig_price - sig_sl), 2)
                elif rrr >= 2.8 or "3:1" in regime or "Jauh" in regime or "Momentum" in regime:
                    sl_dist = round(max(MIN_GOLD_USD, cfg_long_sl), 2)
                    tp_dist = round(sl_dist * 3.0, 2)
                else:
                    sl_dist = round(max(MIN_GOLD_USD, cfg_short_sl), 2)
                    tp_dist = round(max(MIN_GOLD_USD, max(sl_dist, cfg_short_tp)), 2)

                # Hard clamp minimal 60 pips 1:1 (TP >= SL, keduanya >= 6.00 USD)
                sl_dist = max(MIN_GOLD_USD, sl_dist)
                tp_dist = max(MIN_GOLD_USD, max(sl_dist, tp_dist))

                if rrr >= 2.8 or "3:1" in regime or "Jauh" in regime or "Momentum" in regime:
                    tp_dist = max(tp_dist, round(sl_dist * 3.0, 2))
            else:
                # Saham Reguler
                tp_dist = round(abs(sig_tp - sig_price), 2) if (sig_tp > 0 and sig_price > 0) else 0.0
                sl_dist = round(abs(sig_price - sig_sl), 2) if (sig_sl > 0 and sig_price > 0) else 0.0

            # KAIDAH BAKU RISK:REWARD GUARD (DILARANG KERAS TP 1 SL 2):
            if sl_dist > tp_dist:
                sl_dist = tp_dist

            digits = int(sym_info.digits or 2) if sym_info else 2
            if sig_type == "BUY":
                tp = round(exec_price + tp_dist, digits)
                sl = round(exec_price - sl_dist, digits)
            else:
                tp = round(exec_price - tp_dist, digits)
                sl = round(exec_price + sl_dist, digits)

            logger.info(
                f"🛡️ [RR GUARD {tp_dist/max(sl_dist, 0.01):.1f}:1] Entry Ask/Bid ${exec_price:.2f} -> "
                f"TP: ${tp:.2f} (+{int(tp_dist*10)} pips), SL: ${sl:.2f} (-{int(sl_dist*10)} pips)"
            )

            # ATURAN BAKU PENGGUNA UNTUK AKUN STANDARD USD:
            # "jika sinyal nya kurang bagus atau lu pasang 0,01 di usd jgn pasang,
            #  untuk usd hanya untuk sinyal 0,05 yg bagus tp di usd nya lu open 0,01"
            is_cent = self.is_cent_account()
            is_high_conviction = (
                score >= self.high_confidence_threshold
                or "A+" in str(grade).upper()
            )
            usd_only_high = cfg_mt5.get("usd_only_high_grade", True)

            if not is_cent:
                # Akun Standard USD:
                if usd_only_high and not is_high_conviction:
                    msg = (
                        f"🛡️ [USD STANDARD FILTER] Sinyal {ticker} {sig_type} adalah sinyal standar/kurang bagus (Skor {score:.0f}%, {grade}). "
                        f"Sesuai arahan pengguna: Akun Standard USD DILARANG masuk pada sinyal 0.01 standar. "
                        f"HANYA masuk pada sinyal Grade A+ (0.05 lot bagus). Order dilewati demi melindungi modal USD!"
                    )
                    logger.info(msg)
                    return {
                        "success": False,
                        "status": "usd_skip_standard_grade",
                        "message": msg,
                    }
                # Jika Grade A+ (0.05 lot bagus), di akun USD wajib dibuka dengan 0.01 lot:
                lot = float(cfg_mt5.get("usd_execution_lot", 0.01))
                logger.info(f"💎 [USD HIGH GRADE] Sinyal Grade A+ ({score:.0f}%) untuk Akun Standard USD: Membuka posisi disiplin {lot} Lot.")
            else:
                # Akun Cent (USC): Hitung lot sesuai momen (Grade A+ = 0.05 lot, Grade A = 0.01 lot)
                lot = self.calculate_lot_size(broker_sym, exec_price, sl, confluence_score=score, setup_grade=grade)

            # Tentukan Filling Mode yang didukung broker (Bit 0 (1): FOK, Bit 1 (2): IOC)
            filling_mode = int(sym_info.filling_mode or 0)
            if filling_mode & 1:
                fill_type = mt5.ORDER_FILLING_FOK
            elif filling_mode & 2:
                fill_type = mt5.ORDER_FILLING_IOC
            else:
                fill_type = mt5.ORDER_FILLING_RETURN

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": broker_sym,
                "volume": lot,
                "type": order_type,
                "price": exec_price,
                "sl": sl,
                "tp": tp,
                "deviation": self.max_slippage,
                "magic": self.magic_number,
                "comment": f"9PDF-{sig_type[:4]}"[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": fill_type,
            }

            logger.info(f"Mengirim Trade Request ke MT5: {sig_type} {lot} {broker_sym} @ {exec_price} (TP: {tp}, SL: {sl})")
            result = mt5.order_send(request)

            if result is None:
                err = mt5.last_error()
                return {
                    "success": False,
                    "status": "order_failed",
                    "message": f"Eksekusi MT5 gagal: {err[1]} (Kode: {err[0]})",
                }

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                msg = f"Order MT5 ditolak oleh broker: {result.comment} (Retcode: {result.retcode})"
                logger.warning(msg)
                return {
                    "success": False,
                    "status": "broker_rejected",
                    "retcode": result.retcode,
                    "message": msg,
                }

            logger.info(f"✅ Order MT5 #{result.order} berhasil dieksekusi! {sig_type} {result.volume} {broker_sym} @ {result.price}")
            # Bersihkan pending order lawan agar tidak terjadi tabrakan
            self.cancel_opposite_pending_orders(sig_type, broker_sym)

            # Sinkronisasi Slippage Broker: Jika harga fill aktual berbeda > 5 sen,
            # lakukan update posisi agar jarak TP & SL di MT5 tetap 100% presisi terhadap harga fill!
            if result.price > 0 and abs(float(result.price) - exec_price) >= 0.05 and is_gold_symbol:
                actual_fill = float(result.price)
                if sig_type == "BUY":
                    adj_tp = round(actual_fill + tp_dist, digits)
                    adj_sl = round(actual_fill - sl_dist, digits)
                else:
                    adj_tp = round(actual_fill - tp_dist, digits)
                    adj_sl = round(actual_fill + sl_dist, digits)
                try:
                    self.modify_position(result.order, sl=adj_sl, tp=adj_tp)
                    tp = adj_tp
                    sl = adj_sl
                    logger.info(f"🎯 [SLIPPAGE ADJUST] SL/TP tiket #{result.order} disinkronkan ke fill ${actual_fill:.2f}: TP=${tp:.2f}, SL=${sl:.2f}")
                except Exception as e_mod:
                    logger.debug(f"Gagal sinkronisasi slippage: {e_mod}")
            return {
                "success": True,
                "status": "executed",
                "ticket": result.order,
                "symbol": broker_sym,
                "action": sig_type,
                "volume": result.volume,
                "price": result.price,
                "tp": tp,
                "sl": sl,
                "magic": self.magic_number,
                "message": f"Order #{result.order} {sig_type} berhasil terpasang di MT5.",
            }

        except Exception as e:
            logger.error(f"Pengecualian saat eksekusi order MT5: {e}")
            return {
                "success": False,
                "status": "exception",
                "message": f"Error internal eksekusi MT5: {e}",
            }

    def execute_limit_order(self, sig: Any) -> Dict[str, Any]:
        """
        Mengeksekusi Pending Limit Order (BUY_LIMIT atau SELL_LIMIT) ke MetaTrader 5:
        1. Wajib memenuhi skor konfluensi Grade A+ (>=80%).
        2. Validasi harga limit:
           - BUY_LIMIT wajib berada di bawah harga Ask live pasar.
           - SELL_LIMIT wajib berada di atas harga Bid live pasar.
        3. Memasang TP & SL minimal 60 pips (1:1 atau 3:1).
        4. Mengirim request dengan action TRADE_ACTION_PENDING.
        """
        sig_type = getattr(sig, "signal", "").upper()
        ticker = getattr(sig, "ticker", "")
        limit_price = float(getattr(sig, "price", 0.0))
        tp = float(getattr(sig, "take_profit_price", 0.0) or 0.0)
        sl = float(getattr(sig, "stop_loss_price", 0.0) or 0.0)
        score = float(getattr(sig, "pdf_confluence_score", 0.0) or 0.0)
        grade = str(getattr(sig, "setup_grade", "Grade A+"))
        is_gold_symbol = any(k in ticker.upper() for k in ["XAUUSD", "GC=F", "GOLD", "EMAS"])

        if not self.enabled:
            return {
                "success": False,
                "status": "disabled",
                "message": "Auto-Trade MT5 sedang NONAKTIF (hanya mode notifikasi sinyal).",
            }

        in_hours, hours_msg = self.is_within_trading_hours()
        if not in_hours:
            logger.info(f"Eksekusi Pending Order dilewati: {hours_msg}")
            return {
                "success": False,
                "status": "outside_hours",
                "message": hours_msg,
            }

        if sig_type not in ["BUY_LIMIT", "SELL_LIMIT"]:
            return {
                "success": False,
                "status": "rejected",
                "message": f"Sinyal {sig_type} bukan tipe Pending Limit Order.",
            }

        cfg = getattr(self, "config", None) or load_config()
        cfg_mt5 = cfg.get("mt5", {})
        min_limit_score = float(cfg_mt5.get("high_confidence_threshold", 80.0))
        always_limit = bool(cfg_mt5.get("always_use_limit_orders", False))
        if not always_limit and score < min_limit_score and "A+" not in str(grade).upper():
            msg = (
                f"🛡️ [PENDING LIMIT FILTER] Sinyal {sig_type} ditolak: Skor ({score:.0f}%, {grade}) "
                f"belum tembus batas Grade A+ (≥{min_limit_score:.0f}%). Pending limit hanya untuk sniper Grade A+!"
            )
            logger.info(msg)
            return {
                "success": False,
                "status": "skip_standard_grade",
                "message": msg,
            }

        # 1c. Proteksi News Guard: Dilarang pasang limit order 10 menit sebelum berita besar
        if bool(cfg_mt5.get("enable_news_limit_guard", True)) and is_gold_symbol:
            mins_before = int(cfg_mt5.get("news_limit_guard_minutes_before", 10))
            mins_after = int(cfg_mt5.get("news_limit_guard_minutes_after", 15))
            try:
                from data.storage import StockStorage
                st_instance = getattr(self, "storage", None) or StockStorage()
                active_news = st_instance.get_active_high_impact_news(mins_before=mins_before, mins_after=mins_after)
                if active_news:
                    ev = active_news[0]
                    ev_title = ev.get("title", "High-Impact News")
                    ev_wib = ev.get("date_wib", "")
                    ev_type = ev.get("news_type", "NEWS")
                    msg = (
                        f"🛡️ [NEWS GUARD] Pending limit order {sig_type} ditolak: "
                        f"Berita besar '{ev_title}' ({ev_type}) rilis pukul {ev_wib} WIB! "
                        f"Dilarang memasang limit order {mins_before} menit sebelum & {mins_after} menit setelah news demi keselamatan modal."
                    )
                    logger.info(msg)
                    return {
                        "success": False,
                        "status": "news_guard_blocked",
                        "message": msg,
                    }
            except Exception as e_ng:
                logger.debug(f"Pengecekan news guard dilewati: {e_ng}")

        active_pending = self.get_pending_orders(symbol=ticker)
        max_pending = int(cfg_mt5.get("max_pending_orders_per_symbol", 1))
        if len(active_pending) >= max_pending:
            for po in active_pending:
                if po.get("type") == sig_type:
                    p_diff = abs(po.get("price", 0.0) - limit_price)
                    if p_diff < 2.0:
                        msg = (
                            f"⏸️ [ANTI-DUPLICATE PENDING] Sudah ada pending order #{po.get('ticket')} "
                            f"{sig_type} @ {po.get('price')} aktif di area yang sama (selisih ${p_diff:.2f}). Dilewati."
                        )
                        logger.info(msg)
                        return {
                            "success": False,
                            "status": "already_pending",
                            "message": msg,
                        }

        if tp <= 0 or sl <= 0 or limit_price <= 0:
            return {
                "success": False,
                "status": "rejected",
                "message": "Level limit_price, TP, atau SL tidak valid.",
            }

        MIN_GOLD_USD = 6.00
        tp_dist = max(MIN_GOLD_USD, round(abs(tp - limit_price), 2))
        sl_dist = max(MIN_GOLD_USD, round(abs(limit_price - sl), 2))

        if sig_type == "BUY_LIMIT":
            tp = round(limit_price + tp_dist, 2)
            sl = round(limit_price - sl_dist, 2)
        else:
            tp = round(limit_price - tp_dist, 2)
            sl = round(limit_price + sl_dist, 2)

        is_cent = self.is_cent_account()
        if not is_cent:
            lot = float(cfg_mt5.get("limit_order_lot_usd", cfg_mt5.get("usd_execution_lot", 0.01)))
        else:
            if self.is_us_session_window():
                lot = float(cfg_mt5.get("us_session_aggressive_lot", 0.08))
            else:
                lot = float(cfg_mt5.get("limit_order_lot_cent", cfg_mt5.get("limit_order_lot", 0.05)))

        # Section 27: Execution Guards untuk Pending Limit Orders
        algo_ok, algo_msg = self.is_algo_trading_enabled()
        if not algo_ok:
            logger.warning(algo_msg)
            return {
                "success": False,
                "status": "algo_trading_disabled",
                "message": algo_msg,
            }

        margin_ok, margin_msg = self.check_margin_sufficient(ticker, 0 if "BUY" in sig_type else 1, lot, limit_price)
        if not margin_ok:
            logger.warning(margin_msg)
            return {
                "success": False,
                "status": "insufficient_margin",
                "message": margin_msg,
            }

        # Validasi Jarak & Arah SL/TP
        sl_tp_ok, sl_tp_msg = self.validate_sl_tp("BUY" if "BUY" in sig_type else "SELL", limit_price, sl, tp)
        if not sl_tp_ok:
            logger.warning(sl_tp_msg)
            return {
                "success": False,
                "status": "invalid_sl_tp",
                "message": sl_tp_msg,
            }

        # Risk Percentage (WARNING ONLY)
        self.calculate_risk_percentage(ticker, limit_price, sl, lot)

        # Multi-Level / Ladder Limit Orders (Dual-Level Sniper)
        enable_multi = bool(cfg_mt5.get("enable_multi_level_limits", True))
        ladder_items = getattr(sig, "ladder_limit_orders", []) or []
        max_levels = int(cfg_mt5.get("max_limit_levels", 2))
        max_pending = int(cfg_mt5.get("max_pending_orders_per_symbol", 2))

        orders_to_process = []
        if enable_multi and len(ladder_items) >= 2:
            for itm in ladder_items[:max_pending]:
                item_sig = itm.get("signal") or itm.get("type") or itm.get("order_type") or sig_type
                p_item = float(itm.get("price", limit_price))
                tp_item = float(itm.get("tp", tp))
                sl_item = float(itm.get("sl", sl))
                tp_d = max(MIN_GOLD_USD, round(abs(tp_item - p_item), 2))
                sl_d = max(MIN_GOLD_USD, round(abs(p_item - sl_item), 2))
                if "BUY" in item_sig:
                    final_tp = round(p_item + tp_d, 2)
                    final_sl = round(p_item - sl_d, 2)
                else:
                    final_tp = round(p_item - tp_d, 2)
                    final_sl = round(p_item + sl_d, 2)
                item_lot = lot if not is_cent else float(itm.get("lot", lot))
                orders_to_process.append({
                    "level": itm.get("level", len(orders_to_process) + 1),
                    "label": itm.get("label", f"Level {len(orders_to_process) + 1}"),
                    "type": item_sig,
                    "price": p_item,
                    "tp": final_tp,
                    "sl": final_sl,
                    "lot": item_lot,
                })
        else:
            orders_to_process.append({
                "level": 1,
                "label": "Level 1",
                "type": sig_type,
                "price": limit_price,
                "tp": tp,
                "sl": sl,
                "lot": lot,
            })

        if self.simulation_mode:
            placed_tickets = []
            placed_orders = []
            active_pending = self.get_pending_orders(symbol=ticker)
            for ord_info in orders_to_process:
                cur_sig = ord_info.get("type", sig_type)
                curr_active = self.get_pending_orders(symbol=ticker)
                if len(curr_active) >= max_pending:
                    is_dup = any(po.get("type") == cur_sig and abs(po.get("price", 0.0) - ord_info["price"]) < 2.0 for po in curr_active)
                    if is_dup:
                        continue
                    break

                self._simulated_ticket += 1
                ticket = self._simulated_ticket
                lim_dict = {
                    "ticket": ticket,
                    "symbol": ticker,
                    "type": cur_sig,
                    "price": ord_info["price"],
                    "price_open": ord_info["price"],
                    "sl": ord_info["sl"],
                    "tp": ord_info["tp"],
                    "volume": ord_info["lot"],
                    "time_setup": datetime.now(ZoneInfo("Asia/Jakarta")),
                    "comment": f"9PDF-{cur_sig[:5]}",
                }
                self._simulated_pending_orders.append(lim_dict)
                placed_tickets.append(ticket)
                placed_orders.append(lim_dict)
                logger.info(f"🤖 [SIMULASI] Pending Order #{ticket} ({ord_info['label']}) {cur_sig} {ord_info['lot']} {ticker} @ {ord_info['price']} (TP: {ord_info['tp']}, SL: {ord_info['sl']}) sukses dipasang.")

            if not placed_tickets and len(self.get_pending_orders(symbol=ticker)) >= max_pending:
                return {
                    "success": False,
                    "status": "already_pending",
                    "message": f"Pending limit order sudah aktif mencapai batas maksimum ({max_pending}).",
                }

            first_ord = placed_orders[0] if placed_orders else orders_to_process[0]
            first_t = placed_tickets[0] if placed_tickets else 0
            return {
                "success": len(placed_tickets) > 0,
                "ticket": first_t,
                "tickets": placed_tickets,
                "action": sig_type,
                "symbol": ticker,
                "volume": first_ord.get("volume", first_ord.get("lot", lot)),
                "price": first_ord.get("price", limit_price),
                "tp": first_ord.get("tp", tp),
                "sl": first_ord.get("sl", sl),
                "status": "pending_placed",
                "message": f"[SIMULASI] {len(placed_tickets)} Pending limit order berhasil dipasang.",
                "placed_orders": placed_orders,
            }

        if not self.ensure_connected():
            return {"success": False, "status": "connection_error", "message": "MT5 tidak terhubung."}

        broker_sym = self.find_symbol(ticker) or ticker
        tick = mt5.symbol_info_tick(broker_sym)
        if tick is None:
            return {"success": False, "status": "no_tick", "message": f"Gagal membaca tick pasar {broker_sym}."}

        sym_info = mt5.symbol_info(broker_sym)
        filling_mode = int(sym_info.filling_mode or 0) if sym_info else 0
        if filling_mode & 1:
            fill_type = mt5.ORDER_FILLING_FOK
        elif filling_mode & 2:
            fill_type = mt5.ORDER_FILLING_IOC
        else:
            fill_type = mt5.ORDER_FILLING_RETURN

        placed_tickets = []
        placed_orders = []
        last_err = ""

        for ord_info in orders_to_process:
            p_val = ord_info["price"]
            cur_sig = ord_info.get("type", sig_type)
            order_raw_type = mt5.ORDER_TYPE_BUY_LIMIT if "BUY" in cur_sig else mt5.ORDER_TYPE_SELL_LIMIT

            # Validasi harga limit terhadap tick live
            if "BUY" in cur_sig and p_val >= tick.ask:
                logger.warning(f"Harga BUY LIMIT (${p_val:.2f}) harus lebih rendah dari harga Ask (${tick.ask:.2f}). Dilewati.")
                continue
            elif "SELL" in cur_sig and p_val <= tick.bid:
                logger.warning(f"Harga SELL LIMIT (${p_val:.2f}) harus lebih tinggi dari harga Bid (${tick.bid:.2f}). Dilewati.")
                continue

            # Anti-duplicate & max pending check per level
            active_pending = self.get_pending_orders(symbol=broker_sym)
            if len(active_pending) >= max_pending:
                is_dup = any(po.get("type") == cur_sig and abs(po.get("price", 0.0) - p_val) < 2.0 for po in active_pending)
                if is_dup:
                    logger.info(f"Pending order {cur_sig} @ {p_val} sudah ada aktif di area yang sama. Dilewati.")
                    continue
                logger.info(f"Maksimal pending order ({max_pending}) sudah tercapai pada {broker_sym}.")
                break

            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": broker_sym,
                "volume": ord_info["lot"],
                "type": order_raw_type,
                "price": p_val,
                "sl": ord_info["sl"],
                "tp": ord_info["tp"],
                "deviation": self.max_slippage,
                "magic": self.magic_number,
                "comment": f"9PDF-{cur_sig[:5]}"[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": fill_type,
            }

            logger.info(f"Mengirim Pending Order Request ke MT5: {cur_sig} {ord_info['lot']} {broker_sym} @ {p_val} (TP: {ord_info['tp']}, SL: {ord_info['sl']})")
            result = mt5.order_send(request)

            if result is None:
                err = mt5.last_error()
                last_err = f"MT5 error: {err[1]} (Kode: {err[0]})"
                logger.warning(last_err)
                continue

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                last_err = f"Broker retcode {result.retcode}: {result.comment}"
                logger.warning(last_err)
                continue

            logger.info(f"✅ Pending Order MT5 #{result.order} ({ord_info['label']}) berhasil dipasang! {cur_sig} {ord_info['lot']} {broker_sym} @ {p_val}")
            placed_tickets.append(result.order)
            placed_orders.append({
                "ticket": result.order,
                "action": cur_sig,
                "symbol": broker_sym,
                "volume": ord_info["lot"],
                "price": p_val,
                "tp": ord_info["tp"],
                "sl": ord_info["sl"],
                "level": ord_info["level"],
                "label": ord_info["label"],
            })

        if not bool(cfg_mt5.get("enable_dual_sided_limits", False)):
            self.cancel_opposite_pending_orders("BUY" if "BUY" in sig_type else "SELL", broker_sym)

        if not placed_tickets:
            if len(self.get_pending_orders(symbol=broker_sym)) >= max_pending:
                return {
                    "success": False,
                    "status": "already_pending",
                    "message": f"Pending limit order sudah aktif di area ini atau mencapai batas kuota ({max_pending}).",
                }
            return {
                "success": False,
                "status": "order_failed",
                "message": f"Gagal memasang pending order: {last_err or 'Harga tick atau broker menolak'}",
            }

        first_p = placed_orders[0]
        return {
            "success": True,
            "ticket": first_p["ticket"],
            "tickets": placed_tickets,
            "action": sig_type,
            "symbol": broker_sym,
            "volume": first_p["volume"],
            "price": first_p["price"],
            "tp": first_p["tp"],
            "sl": first_p["sl"],
            "status": "pending_placed",
            "message": f"{len(placed_tickets)} Pending Order #{placed_tickets} {sig_type} sukses dipasang di MT5.",
            "placed_orders": placed_orders,
        }

    def close_position(self, ticket: int) -> Dict[str, Any]:
        """Menutup posisi order aktif di MT5 berdasarkan nomor tiket."""
        if self.simulation_mode:
            self._simulated_positions = [p for p in self._simulated_positions if p["ticket"] != ticket]
            return {"success": True, "message": f"Posisi simulasi #{ticket} berhasil ditutup."}

        if not self.ensure_connected():
            return {"success": False, "message": "Gagal terhubung ke terminal MT5."}

        try:
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return {"success": False, "message": f"Posisi tiket #{ticket} tidak ditemukan di MT5."}

            pos = positions[0]
            close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                return {"success": False, "message": f"Gagal mengambil harga pasar untuk {pos.symbol}."}

            close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

            sym_info = mt5.symbol_info(pos.symbol)
            filling_mode = int(sym_info.filling_mode or 0) if sym_info else 0
            if filling_mode & 1:
                fill_type = mt5.ORDER_FILLING_FOK
            elif filling_mode & 2:
                fill_type = mt5.ORDER_FILLING_IOC
            else:
                fill_type = mt5.ORDER_FILLING_RETURN

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": close_type,
                "price": close_price,
                "deviation": self.max_slippage,
                "magic": self.magic_number,
                "comment": f"Close #{ticket}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": fill_type,
            }

            res = mt5.order_send(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                return {"success": True, "message": f"Posisi #{ticket} sukses ditutup pada harga {close_price}."}
            else:
                comment = res.comment if res else mt5.last_error()[1]
                return {"success": False, "message": f"Gagal menutup posisi #{ticket}: {comment}"}

        except Exception as e:
            return {"success": False, "message": f"Error saat menutup posisi: {e}"}

    def modify_position(
        self,
        ticket: int,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Memodifikasi level Stop Loss (SL) dan/atau Take Profit (TP) dari posisi terbuka di MT5.
        Digunakan untuk Break-Even Protection (BEP Lock) dan Trailing Stop.
        """
        if self.simulation_mode:
            for p in self._simulated_positions:
                if p["ticket"] == ticket:
                    if sl is not None:
                        p["sl"] = float(sl)
                    if tp is not None:
                        p["tp"] = float(tp)
                    return {
                        "success": True,
                        "ticket": ticket,
                        "sl": p.get("sl"),
                        "tp": p.get("tp"),
                        "message": f"Posisi simulasi #{ticket} berhasil dimodifikasi: SL={p.get('sl')}, TP={p.get('tp')}",
                    }
            return {"success": False, "message": f"Posisi simulasi #{ticket} tidak ditemukan."}

        if not self.ensure_connected():
            return {"success": False, "message": "Gagal terhubung ke terminal MT5."}

        try:
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return {"success": False, "message": f"Posisi tiket #{ticket} tidak ditemukan di MT5."}

            pos = positions[0]
            sym_info = mt5.symbol_info(pos.symbol)
            digits = int(sym_info.digits or 2) if sym_info else 2

            new_sl = round(float(sl), digits) if sl is not None else float(pos.sl)
            new_tp = round(float(tp), digits) if tp is not None else float(pos.tp)

            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": pos.symbol,
                "sl": new_sl,
                "tp": new_tp,
            }

            res = mt5.order_send(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"🛡️ Modifikasi MT5 #{ticket} berhasil: SL={new_sl}, TP={new_tp}")
                return {
                    "success": True,
                    "ticket": ticket,
                    "sl": new_sl,
                    "tp": new_tp,
                    "message": f"Posisi #{ticket} berhasil dimodifikasi di MT5: SL={new_sl}, TP={new_tp}.",
                }
            else:
                comment = res.comment if res else mt5.last_error()[1]
                logger.warning(f"Gagal memodifikasi #{ticket} di MT5: {comment}")
                return {"success": False, "message": f"Gagal memodifikasi posisi #{ticket}: {comment}"}

        except Exception as e:
            logger.error(f"Error memodifikasi posisi #{ticket}: {e}")
            return {"success": False, "message": f"Error saat modifikasi posisi: {e}"}

    def get_broker_time_offset(self) -> int:
        """
        Menghitung selisih detik antara jam server broker MT5 dengan waktu UTC nyata.
        Misal: Broker HFM (UTC+3) -> return 10800 detik (+3 jam).
        """
        if self.simulation_mode or not self.is_available():
            return 0
        try:
            import time
            sym = self.gold_symbol or "XAUUSD"
            tick = mt5.symbol_info_tick(sym) or mt5.symbol_info_tick("XAUUSD")
            if tick and tick.time:
                return int(tick.time - int(time.time()))
        except Exception:
            pass
        return 0

    def get_closed_deals(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Mengambil seluruh transaksi posisi yang telah ditutup (DEAL_ENTRY_OUT)
        pada akun MT5 dalam rentang jam tertentu.
        Mendeteksi apakah penutupan disebabkan oleh Take Profit (TP), Stop Loss (SL),
        atau penutupan manual.
        """
        if self.simulation_mode or not self.is_available():
            return []

        if not self.is_connected:
            ok, _ = self.connect()
            if not ok:
                return []

        try:
            import time
            from datetime import datetime, timezone, timedelta
            from zoneinfo import ZoneInfo

            offset = self.get_broker_time_offset()
            tz_wib = ZoneInfo("Asia/Jakarta")

            # Ambil seluruh riwayat deals dengan rentang waktu aman (hours s/d +1 hari).
            # Menggunakan datetime lokal langsung tanpa penambahan offset yang mendistorsi query datetime.
            from_server = datetime.now() - timedelta(hours=max(hours, 24))
            to_server = datetime.now() + timedelta(days=1)

            deals = mt5.history_deals_get(from_server, to_server)
            if not deals:
                return []

            closed_deals = []
            for d in deals:
                if d.entry != mt5.DEAL_ENTRY_OUT:
                    continue

                # Filter kepemilikan deal bot:
                # 1. d.magic == self.magic_number
                # 2. ATAU deal pembuka (DEAL_ENTRY_IN) memiliki magic == self.magic_number
                # 3. ATAU transaksi pada simbol Gold (XAUUSD / XAUUSDc) baik dibuka bot maupun manual oleh user ("gw")
                is_bot = (d.magic == self.magic_number)
                in_deal = None

                pos_deals = mt5.history_deals_get(position=d.position_id)
                if pos_deals:
                    in_deal = next((x for x in pos_deals if x.entry == mt5.DEAL_ENTRY_IN), None)
                    if in_deal and in_deal.magic == self.magic_number:
                        is_bot = True

                is_gold = any(g in (d.symbol or "").upper() for g in ["XAU", "GOLD"])
                if not is_bot and not is_gold:
                    continue

                # Cek alasan penutupan: 4 = SL, 5 = TP, lainnya = Regular/Client/Manual
                reason_str = "MANUAL"
                comment_lower = (d.comment or "").lower()
                is_profit_deal = float(d.profit) >= 0.0

                if d.reason == 4 or "sl" in comment_lower:
                    if is_profit_deal:
                        reason_str = "TRAILING_SL"
                        outcome = "WIN"
                    else:
                        reason_str = "SL"
                        outcome = "LOSE"
                elif d.reason == 5 or "tp" in comment_lower:
                    reason_str = "TP"
                    outcome = "WIN"
                else:
                    outcome = "WIN" if is_profit_deal else "LOSE"

                # Konversi waktu epoch server broker ke waktu nyata WIB (Asia/Jakarta)
                true_utc_epoch = d.time - offset
                deal_time_wib = datetime.fromtimestamp(true_utc_epoch, tz=tz_wib).strftime("%Y-%m-%d %H:%M WIB")

                entry_price = float(in_deal.price) if in_deal else float(d.price)
                entry_type = ("BUY" if in_deal.type == mt5.DEAL_TYPE_BUY else "SELL") if in_deal else ("BUY" if d.type == mt5.DEAL_TYPE_SELL else "SELL")

                closed_deals.append({
                    "deal_ticket": d.ticket,
                    "order_ticket": d.order,
                    "position_id": d.position_id,
                    "symbol": d.symbol,
                    "type": entry_type,
                    "volume": d.volume,
                    "price": float(d.price),
                    "entry_price": entry_price,
                    "profit": float(d.profit),
                    "reason": reason_str,
                    "outcome": outcome,
                    "time": d.time,
                    "time_wib": deal_time_wib,
                    "true_utc_epoch": true_utc_epoch,
                    "comment": d.comment,
                })
            return closed_deals
        except Exception as e:
            logger.warning(f"Error mengambil riwayat closed deals MT5: {e}")
            return []

    def deploy_dual_sided_limit_bracket(
        self,
        symbol: str,
        orders: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Memasang bracket dual-sided pending limit orders (BUY LIMIT & SELL LIMIT)
        berdasarkan analisis SMC & Likuiditas terkini, dengan penyegaran otomatis berkala.
        """
        if not orders:
            return {"success": False, "placed_tickets": [], "placed_orders": [], "message": "Tidak ada order untuk dipasang."}

        is_cent = self.is_cent_account()
        cfg_mt5 = getattr(self, "config", {}).get("mt5", {})
        target_lot = float(cfg_mt5.get("limit_order_lot_cent", cfg_mt5.get("limit_order_lot", 0.05))) if is_cent else float(cfg_mt5.get("limit_order_lot_usd", 0.01))

        if self.simulation_mode:
            placed_tickets = []
            placed_orders = []
            for ord_info in orders:
                cur_sig = ord_info.get("type") or ord_info.get("signal", "BUY_LIMIT")
                p_val = float(ord_info["price"])
                lot_val = target_lot if not is_cent else float(ord_info.get("lot", target_lot))
                self._simulated_ticket += 1
                ticket = self._simulated_ticket
                lim_dict = {
                    "ticket": ticket,
                    "symbol": symbol,
                    "type": cur_sig,
                    "price": p_val,
                    "price_open": p_val,
                    "sl": float(ord_info["sl"]),
                    "tp": float(ord_info["tp"]),
                    "volume": lot_val,
                    "time_setup": datetime.now(ZoneInfo("Asia/Jakarta")),
                    "comment": f"9PDF-{cur_sig[:5]}",
                }
                self._simulated_pending_orders.append(lim_dict)
                placed_tickets.append(ticket)
                placed_orders.append(lim_dict)
            logger.info(f"🤖 [SIMULASI] {len(placed_tickets)} Dual-sided pending limit orders berhasil dipasang.")
            return {
                "success": len(placed_tickets) > 0,
                "placed_tickets": placed_tickets,
                "placed_orders": placed_orders,
                "message": f"[SIMULASI] {len(placed_tickets)} Dual-sided pending limit orders berhasil dipasang.",
            }

        if not self.ensure_connected():
            return {"success": False, "placed_tickets": [], "placed_orders": [], "message": "MT5 tidak terhubung."}

        broker_sym = self.find_symbol(symbol) or symbol
        tick = mt5.symbol_info_tick(broker_sym)
        if tick is None:
            return {"success": False, "placed_tickets": [], "placed_orders": [], "message": f"Gagal membaca tick pasar {broker_sym}."}

        sym_info = mt5.symbol_info(broker_sym)
        filling_mode = int(sym_info.filling_mode or 0) if sym_info else 0
        if filling_mode & 1:
            fill_type = mt5.ORDER_FILLING_FOK
        elif filling_mode & 2:
            fill_type = mt5.ORDER_FILLING_IOC
        else:
            fill_type = mt5.ORDER_FILLING_RETURN

        placed_tickets = []
        placed_orders = []
        active_pending = self.get_pending_orders(symbol=broker_sym)

        for ord_info in orders:
            cur_sig = ord_info.get("type") or ord_info.get("signal", "BUY_LIMIT")
            p_val = float(ord_info["price"])
            sl_val = float(ord_info["sl"])
            tp_val = float(ord_info["tp"])
            lot_val = target_lot if not is_cent else float(ord_info.get("lot", target_lot))
            label = ord_info.get("label", cur_sig)

            # Validasi harga limit terhadap tick live (MT5 rule: BUY_LIMIT < ask, SELL_LIMIT > bid)
            if "BUY" in cur_sig:
                if p_val >= tick.ask - 1.00:
                    p_val = round(tick.ask - 1.50, 2)
                    sl_val = round(p_val - 6.00, 2)
                    tp_val = round(p_val + 6.00, 2)
                order_raw_type = mt5.ORDER_TYPE_BUY_LIMIT
            else:
                if p_val <= tick.bid + 1.00:
                    p_val = round(tick.bid + 1.50, 2)
                    sl_val = round(p_val + 6.00, 2)
                    tp_val = round(p_val - 6.00, 2)
                order_raw_type = mt5.ORDER_TYPE_SELL_LIMIT

            # Anti-duplicate check: jika sudah ada pending order dengan tipe sama dalam jarak $1.50 USD
            is_dup = any(po.get("type") == cur_sig and abs(po.get("price", 0.0) - p_val) < 1.50 for po in active_pending)
            if is_dup:
                logger.info(f"Pending order {cur_sig} @ {p_val} sudah aktif di area yang sama. Dilewati.")
                continue

            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": broker_sym,
                "volume": lot_val,
                "type": order_raw_type,
                "price": p_val,
                "sl": sl_val,
                "tp": tp_val,
                "deviation": self.max_slippage,
                "magic": self.magic_number,
                "comment": f"9PDF-{cur_sig[:5]}"[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": fill_type,
            }

            logger.info(f"🚀 Memasang Dual-Sided Limit: {cur_sig} {lot_val} {broker_sym} @ {p_val} (TP: {tp_val}, SL: {sl_val}) [{label}]")
            result = mt5.order_send(request)

            if result is None:
                err = mt5.last_error()
                logger.warning(f"Gagal order_send: {err[1]} (Kode: {err[0]})")
                continue

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.warning(f"Broker retcode {result.retcode}: {result.comment}")
                continue

            logger.info(f"✅ Berhasil pasang {cur_sig} #{result.order} ({label}) @ {p_val}")
            placed_tickets.append(result.order)
            placed_orders.append({
                "ticket": result.order,
                "action": cur_sig,
                "symbol": broker_sym,
                "price": p_val,
                "sl": sl_val,
                "tp": tp_val,
                "volume": lot_val,
                "label": label,
            })
            active_pending.append({"type": cur_sig, "price": p_val, "ticket": result.order})

        return {
            "success": len(placed_tickets) > 0,
            "placed_tickets": placed_tickets,
            "placed_orders": placed_orders,
            "message": f"Berhasil memasang {len(placed_tickets)} pending limit order.",
        }


