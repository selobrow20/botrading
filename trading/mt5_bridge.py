"""
Modul Eksekutor MetaTrader 5 (MT5 Bridge & Auto-Trader).
Menghubungkan sinyal bot trading (khususnya Emas / XAU/USD berbasis 7 Buku PDF)
secara langsung ke terminal MetaTrader 5 untuk eksekusi order otomatis (BUY / SELL)
lengkap dengan Take Profit (TP), Stop Loss (SL), dan manajemen risiko lot.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
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
        mt5_cfg = cfg.get("mt5", {})

        self.enabled: bool = bool(mt5_cfg.get("enabled", False))
        self.login: int = int(os.getenv("MT5_LOGIN", mt5_cfg.get("login", 0)) or 0)
        self.password: str = str(os.getenv("MT5_PASSWORD", mt5_cfg.get("password", "")) or "")
        self.server: str = str(os.getenv("MT5_SERVER", mt5_cfg.get("server", "")) or "")
        self.path: str = str(os.getenv("MT5_PATH", mt5_cfg.get("path", "")) or "")
        self.magic_number: int = int(mt5_cfg.get("magic_number", 777777))
        self.default_lot: float = float(mt5_cfg.get("default_lot", 0.01))
        self.risk_percent: float = float(mt5_cfg.get("risk_percent", 1.0))
        self.max_slippage: int = int(mt5_cfg.get("max_slippage", 20))
        self.gold_symbol: str = str(mt5_cfg.get("gold_symbol", "XAUUSD"))

        self.simulation_mode: bool = simulation_mode
        self.is_connected: bool = False
        self._simulated_positions: List[Dict[str, Any]] = []
        self._simulated_ticket: int = 100000

        self._initialized = True
        logger.info(f"MT5Bridge diinisialisasi. Enabled: {self.enabled}, Platform: {sys.platform}, Lib Available: {MT5_AVAILABLE}")

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
            # 1. Inisialisasi Terminal
            init_kwargs = {}
            if target_path:
                init_kwargs["path"] = target_path

            if not mt5.initialize(**init_kwargs):
                err = mt5.last_error()
                logger.warning(f"Gagal initialize MT5: {err}")
                return False, f"Gagal membuka MT5: {err[1]} (Kode: {err[0]}). Pastikan aplikasi MetaTrader 5 terinstal di komputer."

            # 2. Login ke Akun (jika kredensial diberikan)
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
            msg = f"Sukses terhubung ke MT5! Akun #{acc.login} ({acc.server} - {mode_str}) | Saldo: ${acc.balance:,.2f}"
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

        if not self.is_connected:
            ok, _ = self.connect()
            if not ok:
                return None

        try:
            acc = mt5.account_info()
            if acc is None:
                return None
            mode_str = "Demo" if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "Real"
            return {
                "login": acc.login,
                "name": acc.name,
                "server": acc.server,
                "trade_mode": mode_str,
                "currency": acc.currency,
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

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Mendapatkan daftar seluruh posisi trading yang sedang berjalan (OPEN) di MT5."""
        if self.simulation_mode:
            return list(self._simulated_positions)

        if not self.is_connected:
            ok, _ = self.connect()
            if not ok:
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
            [self.gold_symbol, "XAUUSD", "XAUUSDm", "GOLD", "XAUUSD.s", "XAUUSD.a", "XAUUSD.c", "XAUUSD#", "XAUUSD_i"]
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

        return None

    def calculate_lot_size(
        self,
        symbol: str,
        entry_price: float,
        sl_price: float,
    ) -> float:
        """
        Menghitung ukuran lot optimal berdasarkan manajemen risiko modal (% Equity)
        dan jarak Stop Loss.
        """
        if self.simulation_mode:
            return self.default_lot

        if self.risk_percent <= 0:
            return self.default_lot

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
        Mengeksekusi sinyal trading langsung ke MetaTrader 5 dengan pengawalan ketat 7 Buku PDF:
        1. Wajib sinyal BUY atau SELL.
        2. Wajib memenuhi skor konfluensi 7 PDF (Grade A >= 65%).
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

        # 2. Cek tipe sinyal
        if sig_type not in ["BUY", "SELL"]:
            return {
                "success": False,
                "status": "rejected",
                "message": f"Sinyal {sig_type} bukan sinyal eksekusi (HOLD).",
            }

        # 3. KAWALAN KETAT 7 BUKU PDF: Tolak eksekusi jika belum tembus Grade A (65%)
        # Sesuai instruksi mutlak pengguna: 'jgn sekali kali open jika engga ada sinyal dari bot ya harus ikut dari pentujuk pdf'
        if score < 65.0:
            msg = (
                f"❌ Eksekusi MT5 Ditolak: Skor konfluensi 7 Buku PDF ({score:.0f}%) "
                f"belum tembus batas minimal Grade A (65%). Sinyal tanpa konfluensi 7 PDF dilarang dieksekusi!"
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

        # 5. Mode Simulasi (Dry-Run untuk Unit Testing)
        if self.simulation_mode:
            self._simulated_ticket += 1
            ticket = self._simulated_ticket
            pos_dict = {
                "ticket": ticket,
                "symbol": ticker,
                "type": sig_type,
                "volume": self.default_lot,
                "price_open": price,
                "sl": sl,
                "tp": tp,
                "price_current": price,
                "profit": 0.0,
                "comment": f"7PDF-{sig_type}",
            }
            self._simulated_positions.append(pos_dict)
            logger.info(f"🤖 [SIMULASI] Order MT5 #{ticket} {sig_type} {ticker} @ {price} (TP: {tp}, SL: {sl}) sukses dieksekusi.")
            return {
                "success": True,
                "status": "executed",
                "ticket": ticket,
                "symbol": ticker,
                "action": sig_type,
                "volume": self.default_lot,
                "price": price,
                "tp": tp,
                "sl": sl,
                "magic": self.magic_number,
                "message": f"Order simulasi #{ticket} {sig_type} berhasil dipasang.",
            }

        # 6. Eksekusi Live MT5 Real / Demo
        if not self.is_connected:
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

            # Tentukan tipe order dan harga eksekusi
            order_type = mt5.ORDER_TYPE_BUY if sig_type == "BUY" else mt5.ORDER_TYPE_SELL
            exec_price = float(tick.ask if sig_type == "BUY" else tick.bid)

            # Hitung lot
            lot = self.calculate_lot_size(broker_sym, exec_price, sl)

            # Tentukan Filling Mode yang didukung broker
            filling_mode = sym_info.filling_mode
            if filling_mode & mt5.ORDER_FILLING_IOC:
                fill_type = mt5.ORDER_FILLING_IOC
            elif filling_mode & mt5.ORDER_FILLING_FOK:
                fill_type = mt5.ORDER_FILLING_FOK
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
                "comment": f"7PDF-{sig_type[:4]}"[:31],
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

        if not self.is_connected:
            ok, err_msg = self.connect()
            if not ok:
                return {"success": False, "message": err_msg}

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
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            res = mt5.order_send(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                return {"success": True, "message": f"Posisi #{ticket} sukses ditutup pada harga {close_price}."}
            else:
                comment = res.comment if res else mt5.last_error()[1]
                return {"success": False, "message": f"Gagal menutup posisi #{ticket}: {comment}"}

        except Exception as e:
            return {"success": False, "message": f"Error saat menutup posisi: {e}"}
