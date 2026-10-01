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
        self.use_dynamic_lot: bool = bool(mt5_cfg.get("use_dynamic_lot", False))
        self.risk_percent: float = float(mt5_cfg.get("risk_percent", 1.0))
        self.max_slippage: int = int(mt5_cfg.get("max_slippage", 20))
        self.gold_symbol: str = str(mt5_cfg.get("gold_symbol", "XAUUSD"))
        self.trading_hours: str = str(mt5_cfg.get("trading_hours", "all") or "all")

        self.simulation_mode: bool = simulation_mode
        self.is_connected: bool = False
        self._simulated_positions: List[Dict[str, Any]] = []
        self._simulated_ticket: int = 100000
        self.reversal_cooldown_until: Optional[datetime] = None
        self.reversal_cooldown_reason: str = ""

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

    def check_overnight_safety_guards(self, broker_sym: str, score: float = 0.0) -> Tuple[bool, str, str]:
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

        # 2. Max Spread Guard
        tick = mt5.symbol_info_tick(broker_sym) if not getattr(self, "_mock_tick", None) else getattr(self, "_mock_tick")
        if tick and tick.ask and tick.bid:
            spread = float(tick.ask - tick.bid)
            max_spread = float(cfg_mt5.get("max_spread_usd", 0.65))
            if spread > max_spread:
                msg = (
                    f"⏸️ [SPREAD GUARD] Spread pasar saat ini (${spread:.2f} USD) melebihi batas toleransi "
                    f"(${max_spread:.2f} USD). Eksekusi ditahan agar tidak termakan spread malam broker."
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

        # 3. Consecutive Loss Circuit Breaker (Proteksi SL Beruntun)
        # Sesuai instruksi mutlak pengguna:
        # "kalo bisa jam tengah malem aja jam 2-4 itu yg harus di kasih daily biar ga boncos kaya semalem
        #  kalo jam jam yg masih bisa gw pantau aman aja... sama loss harian di hilangkan aja di usc ,kecuali pake usd"
        # 1. Akun Cent (USC) di jam pantau normal (di luar jam 02:00 - 04:30 WIB) TIDAK diblokir oleh cooldown SL beruntun.
        # 2. Sinyal Grade A / A+ (score >= 65.0%) dari 9 Buku PDF selalu melewati cooldown (override) agar momen valid tidak terlewat.
        max_consec = int(cfg_mt5.get("max_consecutive_losses", 2))
        cooldown_mins = int(cfg_mt5.get("consecutive_loss_cooldown_mins", 60))
        if is_cent and not is_midnight_window:
            logger.debug("Akun Cent (USC) di jam pantau aktif: Consecutive loss cooldown dilewati.")
        elif score >= 65.0:
            logger.info(
                f"🔥 [GRADE A OVERRIDE] Sinyal konfluensi 9 PDF ({score:.0f}%) terdeteksi! "
                f"Consecutive loss cooldown otomatis dilewati agar momen trading berkualitas langsung dieksekusi MT5!"
            )
        else:
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
                                f"Masa jeda pengamanan aktif ({remaining} menit tersisa) demi mencegah overtrading di pasar berombak."
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
        if self.simulation_mode:
            return False
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

    def calculate_lot_size(
        self,
        symbol: str,
        entry_price: float,
        sl_price: float,
        confluence_score: float = 0.0,
        setup_grade: str = "",
    ) -> float:
        """
        Menghitung ukuran lot trading:
        - Momen Bagus Banget (Grade A+ / Skor Konfluensi >= 80%): 0.05 lot (sesuai arahan pengguna).
        - Momen Standar / Masih Riskan (Grade A / Skor 65% - 79%): 0.01 lot pengaman.
        """
        is_high_conviction = (
            confluence_score >= self.high_confidence_threshold
            or "A+" in str(setup_grade).upper()
        )
        base_lot = self.high_confidence_lot if is_high_conviction else self.default_lot

        if self.simulation_mode or not self.use_dynamic_lot:
            return round(base_lot, 2)

        if self.risk_percent <= 0:
            return round(base_lot, 2)

        try:
            acc = mt5.account_info()
            sym_info = mt5.symbol_info(symbol)
            if acc is None or sym_info is None:
                return self.default_lot

            equity = float(acc.equity)
            risk_amount = equity * (self.risk_percent / 100.0)
            sl_distance = abs(entry_price - sl_price)

            if sl_distance <= 0:
                return self.default_lot

            # Nilai kontrak (Contract Size) emas biasanya 100 troy oz
            contract_size = float(sym_info.trade_contract_size or 100.0)
            loss_per_lot = sl_distance * contract_size

            if loss_per_lot <= 0:
                return self.default_lot

            calculated_lot = risk_amount / loss_per_lot

            # Sesuaikan dengan batasan broker (min lot, max lot, step lot)
            step = float(sym_info.volume_step or 0.01)
            min_lot = float(sym_info.volume_min or 0.01)
            max_lot = float(sym_info.volume_max or 100.0)

            # Bulatkan ke kelipatan step terdekat
            lot = round(calculated_lot / step) * step
            lot = max(min_lot, min(max_lot, lot))
            return round(lot, 2)

        except Exception as e:
            logger.debug(f"Gagal hitung lot dinamis, gunakan default lot {self.default_lot}: {e}")
            return self.default_lot

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

        # 4. Validasi level TP & SL
        if tp <= 0 or sl <= 0:
            return {
                "success": False,
                "status": "rejected",
                "message": "Target TP atau SL tidak valid (wajib memiliki level TP & SL pengaman).",
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
            enable_flip = bool(cfg_mt5.get("enable_reversal_flip", True))
            min_flip_score = float(cfg_mt5.get("min_reversal_flip_score", 90.0))
            pdf_score = float(getattr(sig, "pdf_confluence_score", 0.0) or 0.0)

            if enable_flip and pdf_score >= min_flip_score:
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
                import time
                time.sleep(0.5)

                # Refresh daftar posisi terbuka setelah penutupan posisi lawan
                open_positions = self.get_open_positions()
                active_same_sym = [
                    p for p in open_positions
                    if (is_gold_symbol and any(k in p.get("symbol", "").upper() for k in ["XAUUSD", "GOLD"]))
                    or p.get("symbol", "").upper() == ticker.upper()
                ]
            else:
                opp_summary = ", ".join(f"#{p['ticket']} ({p['type']} @ {p['price_open']})" for p in opposite_positions)
                msg = (
                    f"⏸️ [ANTI-HEDGING GUARD] Sinyal {sig_type} dilewati: Masih ada posisi berlawanan aktif "
                    f"[{opp_summary}] yang sedang berjalan menuju TP/SL (Skor {pdf_score}% < batas pembalikan 90%). "
                    f"Menghindari whipsawing / tabrakan order."
                )
                logger.info(msg)
                return {
                    "success": False,
                    "status": "anti_hedging_skip",
                    "message": msg,
                }

        # 4c. Cegah penumpukan posisi berlebihan pada simbol yang sama (searah)
        # Sesuai aturan:
        # - Akun USD Standard: Maksimal 1 posisi (disiplin ketat, hold jika ada posisi aktif)
        # - Akun CENT (USC): Maksimal 3 posisi, DENGAN SYARAT:
        #   1. Pasar dalam kondisi Trending / Momentum Panjang (bukan Sideways/Guncangan).
        #      Jika pasar Sideways / Berguncang, MAKSIMAL HANYA 1 POSISI (Quick Scalp).
        #   2. Jarak harga antar-posisi (Grid Spacing) minimal $4.0 USD agar tidak menumpuk di harga yang sama.
        cfg = getattr(self, "config", None) or load_config()
        cfg_mt5 = cfg.get("mt5", {})
        is_cent = self.is_cent_account()
        market_regime = getattr(sig, "market_regime", "")
        is_sideways_regime = (
            "BERGUNCANG" in market_regime.upper()
            or "SIDEWAYS" in market_regime.upper()
        )

        if not is_cent and is_sideways_regime:
            max_positions = 1
        else:
            max_positions = int(cfg_mt5.get("max_positions_cent", 3) if is_cent else cfg_mt5.get("max_positions_usd", 1))

        if len(active_same_sym) >= max_positions:
            mode_lbl = (
                f"USD Standard Sideways (Disiplin 1 Posisi Quick TP)"
                if (not is_cent and is_sideways_regime)
                else (f"CENT USC (Maks {max_positions} Posisi)" if is_cent else f"USD Standard (Maks {max_positions} Posisi)")
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

        # 5. Hitung Lot Sesuai Kualitas Momen (0.05 lot momen bagus banget, 0.01 lot standar/riskan)
        lot = self.calculate_lot_size(ticker, price, sl, confluence_score=score, setup_grade=grade)

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
            safe_ok, safe_msg, safe_status = self.check_overnight_safety_guards(broker_sym, score=score)
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

            # KAIDAH BAKU RISK:REWARD GUARD (Minimal 1:1, Dilarang Keras SL Lebih Besar dari TP):
            if tp > 0 and sl > 0 and exec_price > 0:
                tp_dist = abs(tp - exec_price)
                sl_dist = abs(sl - exec_price)
                if sl_dist > tp_dist:
                    if sig_type == "BUY":
                        sl = round(exec_price - tp_dist, 2)
                    else:
                        sl = round(exec_price + tp_dist, 2)
                    logger.info(f"🛡️ [RR GUARD 1:1] SL disesuaikan ke ${sl:.2f} agar R:R minimal 1:1 dengan TP!")

            # Hitung lot dengan pertimbangan momen (Grade A+ = 0.05 lot, Grade A = 0.01 lot)
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

            # MT5 history_deals_get membandingkan datetime terhadap jam server broker.
            # Berikan buffer ke depan (+24 jam) agar transaksi real-time yang baru saja terjadi
            # tidak terpotong oleh perbedaan zona waktu broker vs mesin lokal / UTC.
            now_server = datetime.now() + timedelta(seconds=offset)
            from_server = now_server - timedelta(hours=hours)
            to_server = now_server + timedelta(hours=24)

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
                #    (Penting karena closing manual MT5 atau broker cent sering menyetel magic = 0 pada DEAL_ENTRY_OUT)
                is_bot = (d.magic == self.magic_number)
                in_deal = None

                pos_deals = mt5.history_deals_get(position=d.position_id)
                if pos_deals:
                    in_deal = next((x for x in pos_deals if x.entry == mt5.DEAL_ENTRY_IN), None)
                    if in_deal and in_deal.magic == self.magic_number:
                        is_bot = True

                if not is_bot:
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

