"""
CLIENT MT5 AUTO-COPIER (SISI MEMBER) - ANTI-SHARE & AUTO-EXPIRY EDITION
Membaca Sinyal Eksklusif 9 Buku PDF dari Master Bot Telegram & Mengeksekusi Otomatis ke MT5.

PERINGATAN HAK CIPTA & KEAMANAN:
File ini adalah modul penerima (Client Receiver) dengan proteksi lisensi terpusat.
- Lisensi terkunci ke akun Telegram resmi yang disetujui oleh Master Admin (@selobrow).
- File ini TIDAK DAPAT DIBAGIKAN ke orang lain (otomatis terkunci & menolak jalan).
- Copier otomatis berhenti sendiri begitu masa aktif lisensi berakhir.
- Rumus strategi 9 Buku PDF 100% aman dan tetap berada di server Master Provider.
"""

import os
import re
import sys
import json
import time
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Pastikan UTF-8 di Windows Console
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

CLIENT_COPIER_VERSION = "2.3.5"
OTA_VERSION_URL = "https://raw.githubusercontent.com/selobrow20/botrading/main/member_copier/version.json"
OTA_SCRIPT_URL = "https://raw.githubusercontent.com/selobrow20/botrading/main/member_copier/client_copier.py"

def parse_version(v_str: str) -> tuple:
    """Parse string versi '2.3.5' menjadi tuple (2, 3, 5) untuk perbandingan semver akurat."""
    try:
        nums = re.findall(r"\d+", str(v_str))
        return tuple(map(int, nums)) if nums else (0, 0, 0)
    except Exception:
        return (0, 0, 0)

def restart_copier():
    """
    Me-restart copier secara otomatis dan MEMBUKA KEMBALI jendela aplikasi seketika.
    Member TIDAK PERLU lagi buka-tutup manual!
    """
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

    try:
        import subprocess
        script_file = Path(__file__).resolve()
        copier_dir = script_file.parent
        bat_file = copier_dir / "START_COPIER.bat"

        # Spawn jendela copier baru secara independen agar otomatis terbuka kembali
        if sys.platform == "win32":
            if bat_file.exists():
                try:
                    os.startfile(str(bat_file))
                except Exception:
                    subprocess.Popen(f'start "" "{bat_file}"', cwd=str(copier_dir), shell=True)
            else:
                subprocess.Popen(
                    [sys.executable, str(script_file)],
                    cwd=str(copier_dir),
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )
        else:
            subprocess.Popen([sys.executable, str(script_file)], cwd=str(copier_dir))
    except Exception as e:
        print(f"⚠️ Gagal spawn jendela baru: {e}")

    # Beri jeda 0.5s agar proses baru berhasil di-spawn oleh OS sebelum proses lama keluar
    time.sleep(0.5)
    os._exit(0)

def apply_zip_update(zip_path_or_bytes, preserve_config: bool = True):
    """
    Mengekstrak file update zip tanpa menimpa pengaturan kustom user (lot, server, suffix, dll).
    """
    import zipfile
    import io
    target_dir = Path(__file__).resolve().parent
    old_cfg = {}
    cfg_file = target_dir / "config.json"
    if preserve_config and cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                old_cfg = json.load(f)
        except Exception:
            pass

    if isinstance(zip_path_or_bytes, (str, Path)):
        z = zipfile.ZipFile(zip_path_or_bytes, "r")
    else:
        z = zipfile.ZipFile(io.BytesIO(zip_path_or_bytes), "r")

    with z:
        for member in z.infolist():
            filename = Path(member.filename).name
            if not filename or filename.startswith("__MACOSX") or filename.endswith(".pyc"):
                continue
            dest_file = target_dir / filename
            if filename.lower() == "config.json" and old_cfg:
                try:
                    new_cfg_data = json.loads(z.read(member).decode("utf-8", errors="ignore"))
                    new_cfg_data.update(old_cfg)
                    with open(dest_file, "w", encoding="utf-8") as f:
                        json.dump(new_cfg_data, f, indent=2)
                    continue
                except Exception:
                    continue
            with open(dest_file, "wb") as f_out:
                f_out.write(z.read(member))

def check_and_apply_ota_update(silent: bool = False) -> bool:
    """
    Memeriksa pembaruan Over-The-Air (OTA) langsung dari GitHub Cloud.
    Jika ada versi baru, unduh otomatis dan reload langsung tanpa perlu download/timpa zip manual!
    """
    import urllib.request
    try:
        cache_buster = f"?t={int(time.time())}"
        req = urllib.request.Request(
            OTA_VERSION_URL + cache_buster,
            headers={
                "User-Agent": "MT5-VIP-Copier-AutoUpdater",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            remote_ver = data.get("version", "").strip()
            changelog = data.get("changelog", "Peningkatan stabilitas dan akurasi.")

        if remote_ver and parse_version(remote_ver) > parse_version(CLIENT_COPIER_VERSION):
            print("\n" + "=" * 70)
            print(f"🔔 [NOTIFIKASI UPDATE OTOMATIS] Versi Baru v{remote_ver} Tersedia!")
            print(f"📝 Info: {changelog}")
            print(f"📥 Mengunduh pembaruan otomatis langsung dari Cloud (Tanpa Perlu Timpa ZIP)...")
            req_script = urllib.request.Request(
                OTA_SCRIPT_URL + cache_buster,
                headers={
                    "User-Agent": "MT5-VIP-Copier-AutoUpdater",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
            with urllib.request.urlopen(req_script, timeout=20) as s_resp:
                new_code = s_resp.read().decode("utf-8")

            if len(new_code) > 1000 and "CLIENT MT5 AUTO-COPIER" in new_code:
                cur_file = Path(__file__).resolve()
                backup_file = cur_file.with_suffix(".py.bak")
                try:
                    cur_file.replace(backup_file)
                except Exception:
                    pass
                with open(cur_file, "w", encoding="utf-8") as f:
                    f.write(new_code)
                print("✅ [PEMBARUAN BERHASIL DITERAPKAN OTOMATIS]")
                print("🛡️ Pengaturan Akun & Lot Anda tetap aman.")
                print("🔄 Memuat ulang Copier ke versi terbaru tanpa perlu buka-tutup...")
                print("=" * 70 + "\n")
                time.sleep(1.0)
                restart_copier()
                return True
        elif not silent:
            print(f"ℹ️ [VERSI SISTEM] v{CLIENT_COPIER_VERSION} (Terbaru & Tersinkronisasi)")
    except Exception:
        pass
    return False


CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
DASHBOARD_STATE_PATH = Path(__file__).resolve().parent / "copier_live_state.json"

def sync_event_to_dashboard(sig: dict, res: dict = None):
    """Kirim pembaruan sinyal & eksekusi ke Dashboard 3D tanpa memblokir copier."""
    try:
        now_str = datetime.now().strftime("%H:%M:%S")
        payload = {
            "time": now_str,
            "last_signal": sig,
            "execution": res,
            "timestamp": time.time()
        }
        with open(DASHBOARD_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        def _bg_post():
            try:
                import urllib.request
                req = urllib.request.Request(
                    "http://127.0.0.1:8080/api/event",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                urllib.request.urlopen(req, timeout=0.2)
            except Exception:
                pass
        import threading
        threading.Thread(target=_bg_post, daemon=True).start()
    except Exception:
        pass


def load_config() -> dict:
    cfg = {
        "bot_username": "selo_saham_bot",
        "account_type": "auto",       # Pilihan: "auto" (deteksi otomatis), "usd" (Standard USD), "usc" (Cent)
        "usd_lot": 0.01,              # Lot khusus Akun Standard USD (Kaidah disiplin: 0.01 lot)
        "cent_lot": 0.05,             # Lot khusus Akun Cent USC (0.05 lot luar Sesi US)
        "us_session_cent_lot": 0.08,  # Lot Akun Cent USC di Sesi US (19:00 - 24:00 WIB)
        "default_lot": 0.01,          # Fallback
        "usd_only_high_grade": True,  # Filter Akun USD hanya masuk pada Sinyal Grade A+
        "max_positions_cent": 3,      # Maksimal posisi akun Cent di luar US (minimal 3 posisi)
        "us_session_max_positions": 3,# Maksimal posisi akun Cent di Sesi US (minimal 3 posisi)
        "max_positions_standard": 1,  # Maks 1 posisi USD Standard
        "gold_symbol": "XAUUSD",
        "symbol_suffix": "",
        "min_grid_spacing": 1.0,
        "max_price_drift": 8.0,
        "max_slippage": 20,
        "magic_number": 888888,
        "auto_tp_sl": True,
        "enable_reversal_auto_close": True,
        "enable_break_even": True,
        "break_even_long_pips": 100.0,
        "break_even_buffer_pips": 3.0,
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                cfg.update(loaded)
        except Exception:
            pass

    # Otomatis koreksi tanpa perlu user mengedit file manual
    b_user = (cfg.get("bot_username") or "").strip().lstrip("@")
    if b_user.lower() in ["selobrow_bot", "selobrow", "selo_bot", ""]:
        cfg["bot_username"] = "selo_saham_bot"
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    return cfg


def parse_signal(text: str) -> dict:
    """Mengekstrak data sinyal (Aksi, Simbol, Entry, TP, SL, Ticket) dari format kartu Master Bot."""
    if not text:
        return {}

    # Bersihkan tag HTML agar regex dapat mencocokkan teks polos maupun bertag (<b>, <code>, dll)
    clean_text = re.sub(r"<[^>]+>", " ", text)
    text_upper = clean_text.upper()

    # Abaikan jika ini adalah laporan hasil / deal / penutupan posisi / pengumuman
    ignore_keywords = [
        "LAPORAN PENUTUPAN",
        "TRANSAKSI SELESAI",
        "HASIL TRANSAKSI",
        "DEAL #",
        "POSISI DITUTUP",
        "RINGKASAN PORTOFOLIO",
        "WIN RATE",
        "AKURASI EMAS",
        "LIC_INFO|",
        "/START",
        "/HELP",
        "/USERS",
        "/STATUS",
        "/LICENSE",
    ]
    if any(k in text_upper for k in ignore_keywords):
        return {}

    is_gold = any(k in text_upper for k in ["XAUUSD", "XAU/USD", "XAU", "GOLD", "EMAS"])
    if not is_gold:
        return {}

    action = None
    if any(k in text_upper for k in ["SINYAL ENTRY (MASUK / BUY)", "SINYAL ENTRY BUY", "BUY (LONG)", "BUY / LONG", "AKSI SINYAL: BUY", "AKSI ORDER: BUY"]):
        action = "BUY"
    elif any(k in text_upper for k in ["SINYAL ENTRY SHORT", "SINYAL ENTRY (MASUK / SELL)", "SINYAL ENTRY SELL", "SELL (SHORT)", "SELL / SHORT", "AKSI SINYAL: SELL", "AKSI ORDER: SELL"]):
        action = "SELL"
    else:
        # Hanya cocokkan kata BUY/SELL mandiri jika ada kata "ENTRY" atau "HARGA" di dalam pesan
        if "ENTRY" in text_upper or "MASUK" in text_upper:
            if re.search(r"\bBUY\b", text_upper):
                action = "BUY"
            elif re.search(r"\bSELL\b", text_upper):
                action = "SELL"

    if not action:
        return {}

    def _clean_num(raw_str: str) -> float:
        cleaned = re.sub(r"[^\d.]", "", raw_str)
        try:
            return float(cleaned)
        except Exception:
            return 0.0

    entry_price = 0.0
    tp_price = 0.0
    sl_price = 0.0

    m_entry = re.search(
        r"(?:Harga Entry(?: Short)?|Harga Masuk|Area Entry|\bEntry\b|Harga)\s*[:=]?\s*\$?([\d,]+(?:\.\d+)?)",
        clean_text,
        re.IGNORECASE,
    )
    if m_entry:
        entry_price = _clean_num(m_entry.group(1))

    m_tp = re.search(
        r"(?:Take Profit(?:\s*(?:\(TP\)|1|2))?|\bTP\s*(?:1|2)?\b)\s*[:=]?\s*\$?([\d,]+(?:\.\d+)?)",
        clean_text,
        re.IGNORECASE,
    )
    if m_tp:
        tp_price = _clean_num(m_tp.group(1))

    m_sl = re.search(
        r"(?:Stop Loss(?:\s*\(SL\))?|\bSL\b)\s*[:=]?\s*\$?([\d,]+(?:\.\d+)?)",
        clean_text,
        re.IGNORECASE,
    )
    if m_sl:
        sl_price = _clean_num(m_sl.group(1))

    # Proteksi sanitasi harga emas: jika angka di bawah $100, berarti salah tangkap label (misal TP 1:)
    if is_gold:
        if tp_price < 100.0:
            tp_price = 0.0
        if sl_price < 100.0:
            sl_price = 0.0
        if entry_price < 100.0:
            entry_price = 0.0

    # Jika bukan sinyal berparameter (tidak ada entry, TP, ataupun SL), abaikan
    if entry_price <= 0 and tp_price <= 0 and sl_price <= 0:
        return {}

    m_ticket = re.search(r"(?:Ticket ID|Ticket|Order ID)\s*[:=]?\s*#?(\d+)", clean_text, re.IGNORECASE)
    ticket_id = m_ticket.group(1) if m_ticket else None

    m_score = re.search(r"Konfluensi 9 PDF.*?(\d+)%", clean_text, re.IGNORECASE)
    pdf_score = float(m_score.group(1)) if m_score else 0.0

    # Ekstrak Volume / Lot Master
    master_lot = 0.0
    m_lot = re.search(r"(?:Volume|Lot)\s*[:=]?\s*([\d.]+)\s*(?:Lot)?", clean_text, re.IGNORECASE)
    if m_lot:
        master_lot = _clean_num(m_lot.group(1))

    # Deteksi Sinyal Grade A+ (0.05 lot bagus) vs Standar (0.01 lot)
    is_high_grade = False
    if any(k in text_upper for k in ["MOMEN BAGUS BANGET", "0.05 LOT", "0,05 LOT", "GRADE A+", "GRADE: A+"]):
        is_high_grade = True
    elif pdf_score >= 80.0:
        is_high_grade = True
    elif master_lot >= 0.05:
        is_high_grade = True

    return {
        "symbol": "XAUUSD",
        "action": action,
        "entry_price": entry_price,
        "tp_price": tp_price,
        "sl_price": sl_price,
        "ticket": ticket_id,
        "pdf_confluence_score": pdf_score,
        "master_lot": master_lot,
        "is_high_grade": is_high_grade,
        "raw_text": text,
    }


class MT5MemberBridge:
    """Jembatan eksekusi order ke aplikasi MetaTrader 5 lokal milik member."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.magic = int(cfg.get("magic_number", 888888))
        self.slippage = int(cfg.get("max_slippage", 20))
        self.symbol_override = cfg.get("gold_symbol", "XAUUSD")
        self.suffix = cfg.get("symbol_suffix", "")
        self.mt5 = None
        self._detect_mt5()

    @property
    def lot(self) -> float:
        val, _ = self.calculate_lot_size({}, self.is_cent_account())
        return val

    def calculate_lot_size(self, sig: dict, is_cent: bool) -> tuple[float, str]:
        """
        Menghitung ukuran lot trading dengan kaidah baku pemisahan Akun USD Standard vs Akun Cent USC:
        - Akun Standard USD:
          * Strictly 0.01 lot (usd_lot) untuk melindungi modal USD.
        - Akun Cent (USC):
          * Sesi US (19:00 - 24:00 WIB): 0.08 lot (us_session_cent_lot)
          * Di luar Sesi US: 0.05 lot (cent_lot / default_lot)
        """
        if not is_cent:
            lot = float(self.cfg.get("usd_lot", 0.01))
            return lot, "USD Standard Disiplin"

        # Cek Sesi US untuk Akun Cent
        is_us = False
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime, time
            now_wib = datetime.now(ZoneInfo("Asia/Jakarta")).time()
            is_us = time(19, 0) <= now_wib <= time(23, 59, 59)
        except Exception:
            pass

        if is_us:
            lot = float(self.cfg.get("us_session_cent_lot", 0.08))
            return lot, "Cent USC Sesi US"
        else:
            lot = float(self.cfg.get("cent_lot", self.cfg.get("default_lot", 0.05)))
            return lot, "Cent USC Standar"

    def is_cent_account(self) -> bool:
        """
        Mendeteksi dengan akurat 100% apakah akun MT5 adalah akun Cent (USC) atau Standard (USD).
        Mencegah akun Standard USD salah terdeteksi sebagai Cent pada broker seperti HFMarkets,
        Exness, RoboForex, FBS, XM, IC Markets, dll.
        """
        # 1. Cek konfigurasi manual override jika disetel user (auto / usd / usc)
        cfg_acc = str(self.cfg.get("account_type", "auto")).lower().strip()
        if cfg_acc in ["usd", "standard", "std"]:
            return False
        if cfg_acc in ["usc", "cent", "micro"]:
            return True

        if not self.mt5:
            return False
        try:
            acc = self.mt5.account_info()
            if not acc:
                return False

            curr = str(getattr(acc, "currency", "") or "").upper().strip()
            server = str(getattr(acc, "server", "") or "").lower()
            company = str(getattr(acc, "company", "") or "").lower()

            # 2. Cek mata uang akun secara eksplisit
            # Jika mata uang adalah USC, CENT, EUX, GBX, USCENT -> pasti Cent!
            if curr in ["USC", "CENT", "EUX", "GBX", "USCENT"]:
                return True
            if curr.endswith("C") and curr not in ["USDC", "TUSD", "BUSD", "USDT"]:
                return True

            # 3. Jika mata uang adalah mata uang fiat standar (USD, EUR, GBP, dll)
            # Sangat krusial: Jika mata uang 'USD', hanya anggap Cent jika server/company secara
            # eksplisit bertuliskan "cent", "procent", atau "micro".
            if curr in ["USD", "EUR", "GBP", "AUD", "CAD", "JPY", "CHF", "NZD", "SGD", "IDR"]:
                if any(k in server for k in ["cent", "procent", "micro"]) or any(k in company for k in ["cent", "procent", "micro"]):
                    return True
                return False  # Pasti Standard (USD)!

            # 4. Cek petunjuk nama server / company untuk broker yang mata uangnya tidak standar
            if any(k in server for k in ["cent", "procent", "micro"]) or any(k in company for k in ["cent", "procent", "micro"]):
                return True

            # Default aman: perlakukan sebagai Standard USD (0.01 lot) agar modal member terjaga
            return False
        except Exception:
            return False

    def _detect_mt5(self):
        try:
            import MetaTrader5 as mt5
            self.mt5 = mt5
            if not self.mt5.initialize():
                print(f"[!] Gagal inisialisasi MT5: {self.mt5.last_error()}")
            else:
                acc = self.mt5.account_info()
                if acc:
                    is_cent = self.is_cent_account()
                    sym = self.find_broker_symbol()
                    curr_name = "USC" if is_cent else str(getattr(acc, "currency", "USD") or "USD").upper()
                    equiv_usd = f" (~ ${acc.balance/100.0:,.2f} USD)" if is_cent else ""
                    type_lbl = "Cent (USC)" if is_cent else "Standard (USD)"
                    max_pos = int(self.cfg.get("max_positions_cent", 3)) if is_cent else int(self.cfg.get("max_positions_standard", 1))
                    def_lot, lot_lbl = self.calculate_lot_size({}, is_cent)

                    print("\n" + "=" * 65)
                    print(f"✅ [MT5 TERHUBUNG] Akun #{acc.login} ({acc.server})")
                    print(f"   👤 Tipe Akun    : {type_lbl}")
                    print(f"   💰 Saldo MT5    : {acc.balance:,.2f} {curr_name}{equiv_usd}")
                    print(f"   🏷️ Simbol Gold  : {sym}")
                    print(f"   📦 Maks Posisi  : {max_pos} Posisi Serentak")
                    print(f"   🎯 Lot Eksekusi : {def_lot} Lot ({lot_lbl})")

                    # Peringatan Algo Trading
                    t_info = self.mt5.terminal_info()
                    if t_info and not getattr(t_info, "trade_allowed", True):
                        print("   ⚠️ PERINGATAN: Tombol 'Algo Trading' di toolbar atas MT5 belum AKTIF!")
                        print("      Silakan klik tombol 'Algo Trading' (menjadi hijau) di MT5 agar order dapat dieksekusi.")
                    print("=" * 65 + "\n")
                else:
                    print("[✓] MT5 Berhasil diinisialisasi.")
        except ImportError:
            print("[!] Library MetaTrader5 belum terpasang. Jalankan: pip install MetaTrader5")

    def find_broker_symbol(self) -> str:
        """
        Mencari simbol trading Gold yang valid & tradeable di MT5 member.
        Secara cerdas membedakan akun Cent (XAUUSDc, GOLDc) vs Standard USD (XAUUSD, GOLD).
        """
        if not self.mt5:
            return self.symbol_override or "XAUUSD"

        # Cek apakah akun Cent (tanpa loop rekursif)
        is_cent = self.is_cent_account()

        # Daftar kandidat simbol berdasarkan tipe akun
        if is_cent:
            candidates = [
                f"{self.symbol_override}{self.suffix}" if self.suffix else None,
                "XAUUSDc", "XAUUSD.c", "GOLDc", "XAUUSDm", "XAUUSD.m",
                "XAUUSD", "GOLD", "XAUUSD.raw"
            ]
        else:
            candidates = [
                f"{self.symbol_override}{self.suffix}" if self.suffix else None,
                "XAUUSD", "GOLD", "XAUUSD.raw", "XAUUSD.pro", "XAUUSD.m", "XAUUSDm"
            ]

        # Filter candidate yang None / kosong
        seen = set()
        clean_candidates = [c for c in candidates if c and not (c in seen or seen.add(c))]

        for c in clean_candidates:
            s_info = self.mt5.symbol_info(c)
            if s_info is not None:
                # Pastikan simbol ini tradeable (bukan disabled / trade_mode == 0)
                trade_mode = getattr(s_info, "trade_mode", 4)
                if trade_mode != 0:  # SYMBOL_TRADE_MODE_DISABLED = 0
                    if not s_info.visible:
                        self.mt5.symbol_select(c, True)
                    return c

        # Fallback dinamis: scan seluruh daftar simbol di MT5
        try:
            all_symbols = self.mt5.symbols_get()
            if all_symbols:
                if is_cent:
                    for s in all_symbols:
                        s_name = s.name
                        s_up = s_name.upper()
                        if ("XAU" in s_up or "GOLD" in s_up) and (s_name.endswith("c") or ".c" in s_name.lower()):
                            if getattr(s, "trade_mode", 4) != 0:
                                self.mt5.symbol_select(s_name, True)
                                return s_name
                for s in all_symbols:
                    s_up = s.name.upper()
                    if ("XAU" in s_up or "GOLD" in s_up) and getattr(s, "trade_mode", 4) != 0:
                        if not is_cent and (s.name.endswith("c") or ".c" in s.name.lower()):
                            continue
                        self.mt5.symbol_select(s.name, True)
                        return s.name
        except Exception:
            pass

        return "XAUUSDc" if is_cent else "XAUUSD"

    def ensure_connected(self) -> bool:
        """Memastikan koneksi MT5 member aktif dan auto-reconnect jika idle atau terputus."""
        if not self.mt5:
            self._detect_mt5()
            return bool(self.mt5)
        try:
            t_info = self.mt5.terminal_info()
            if t_info is None:
                # IPC terputus, hubungkan ulang secara halus tanpa shutdown paksa
                return bool(self.mt5.initialize())
            return True
        except Exception:
            return False

    def close_position(self, ticket: int) -> dict:
        if not self.ensure_connected():
            return {"success": False, "message": "MetaTrader 5 tidak aktif atau gagal terhubung."}
        try:
            positions = self.mt5.positions_get(ticket=ticket)
            if not positions:
                return {"success": False, "message": f"Posisi #{ticket} tidak ditemukan."}
            pos = positions[0]
            close_type = self.mt5.ORDER_TYPE_SELL if pos.type == self.mt5.ORDER_TYPE_BUY else self.mt5.ORDER_TYPE_BUY
            tick = self.mt5.symbol_info_tick(pos.symbol)
            if not tick:
                return {"success": False, "message": "Gagal membaca tick pasar."}
            close_price = tick.bid if pos.type == self.mt5.ORDER_TYPE_BUY else tick.ask

            s_info = self.mt5.symbol_info(pos.symbol)
            filling_mode = int(s_info.filling_mode or 0) if s_info else 0
            candidates = []
            if filling_mode & 1:
                candidates.append(self.mt5.ORDER_FILLING_FOK)
            if filling_mode & 2:
                candidates.append(self.mt5.ORDER_FILLING_IOC)
            candidates.extend([self.mt5.ORDER_FILLING_FOK, self.mt5.ORDER_FILLING_IOC, self.mt5.ORDER_FILLING_RETURN])
            seen = set()
            fill_types = [f for f in candidates if not (f in seen or seen.add(f))]

            req = {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": close_type,
                "price": close_price,
                "deviation": self.slippage,
                "magic": self.magic,
                "comment": "VIP-Close-Opposite",
            }
            res = None
            for ft in fill_types:
                req["type_filling"] = ft
                res = self.mt5.order_send(req)
                if res and res.retcode == self.mt5.TRADE_RETCODE_DONE:
                    return {"success": True, "message": f"Posisi #{ticket} berhasil ditutup."}
                if res and res.retcode != 10030:
                    break
            err = res.comment if res else "Gagal"
            return {"success": False, "message": err}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def close_all_positions(self, symbol: str = None, action: str = None) -> list:
        """Menutup seluruh posisi terbuka pada simbol tertentu (opsional berdasarkan tipe BUY/SELL)."""
        if not self.ensure_connected():
            return []
        sym = symbol or self.find_broker_symbol()
        open_pos = self.mt5.positions_get(symbol=sym) or []
        closed = []
        for p in open_pos:
            pos_act = "BUY" if p.type == 0 else "SELL"
            if action is None or pos_act == action:
                res = self.close_position(p.ticket)
                closed.append({"ticket": p.ticket, "action": pos_act, "success": res.get("success")})
        return closed

    def modify_open_positions_sl(self, symbol: str = None, action: str = None, new_sl: float = 0.0) -> list:
        """Menggeser SL seluruh posisi terbuka (untuk BEP Lock & Trailing Stop dari Master)."""
        if not self.ensure_connected() or new_sl <= 0:
            return []
        sym = symbol or self.find_broker_symbol()
        open_pos = self.mt5.positions_get(symbol=sym) or []
        modified = []
        for p in open_pos:
            pos_act = "BUY" if p.type == 0 else "SELL"
            if action is None or pos_act == action:
                should_mod = False
                if pos_act == "BUY" and new_sl > p.sl:
                    should_mod = True
                elif pos_act == "SELL" and (p.sl == 0.0 or new_sl < p.sl):
                    should_mod = True

                if should_mod:
                    req = {
                        "action": self.mt5.TRADE_ACTION_SLTP,
                        "position": p.ticket,
                        "symbol": p.symbol,
                        "sl": round(float(new_sl), 2),
                        "tp": float(p.tp),
                    }
                    res = self.mt5.order_send(req)
                    if res and res.retcode == self.mt5.TRADE_RETCODE_DONE:
                        modified.append({"ticket": p.ticket, "action": pos_act, "new_sl": new_sl, "success": True})
                    else:
                        err_msg = res.comment if res else "Gagal modifikasi"
                        modified.append({"ticket": p.ticket, "action": pos_act, "success": False, "err": err_msg})
        return modified

    def execute_order(self, sig: dict) -> dict:
        if not self.ensure_connected():
            return {"success": False, "message": "MetaTrader 5 tidak aktif atau gagal terhubung."}

        action = sig.get("action", "BUY")
        sym = self.find_broker_symbol()

        # Proteksi Anti-Tabrakan & Anti-Hedging Disiplin (Kaidah 9 Buku PDF):
        # Jika ada posisi yang berlawanan arah (misal ada BUY aktif, lalu muncul sinyal SELL):
        # JANGAN lakukan penutupan paksa di harga pasar yang memicu whipsawing / kerugian bolak-balik!
        # Biarkan posisi yang sedang berjalan menyelesaikan target TP atau pengaman SL-nya secara terukur.
        # Lewati (skip) sinyal baru yang berlawanan arah agar terhindar dari hedging liar dan overtrading.
        open_pos = self.mt5.positions_get(symbol=sym) or []
        opposite_pos = [p for p in open_pos if (p.type == 0 and action == "SELL") or (p.type == 1 and action == "BUY")]
        if opposite_pos:
            # Cek apakah sinyal ini merupakan REVERSAL FLIP 90%+ dari Master:
            sig_reasons = str(sig.get("reasons", "")) + " " + str(sig.get("raw_text", ""))
            pdf_score = float(sig.get("pdf_confluence_score", 0.0) or 0.0)
            is_flip = (
                pdf_score >= 90.0 or
                any(k in sig_reasons.upper() for k in ["REVERSAL FLIP", "PEMBALIKAN ARAH", "GRADE A+ (SETUP SEMPURNA", "95%"]) or
                "REVERSAL" in str(sig.get("strategy_name", "")).upper()
            )

            if is_flip:
                opp_summary = ", ".join(f"#{p.ticket} ({'BUY' if p.type==0 else 'SELL'} @ {p.price_open})" for p in opposite_pos)
                print(f"\n🔄 [REVERSAL FLIP 90%+ 9 BUKU PDF] Menutup posisi lawan [{opp_summary}] di MT5 Member untuk cut loss & flip ke {action}...")
                for p in opposite_pos:
                    self.close_position(p.ticket)
                import time
                time.sleep(0.5)
                open_pos = self.mt5.positions_get(symbol=sym) or []
            else:
                opp_summary = ", ".join(f"#{p.ticket} ({'BUY' if p.type==0 else 'SELL'} @ {p.price_open})" for p in opposite_pos)
                msg_opp = (
                    f"⏸️ [ANTI-HEDGING GUARD] Sinyal {action} dilewati: Masih ada posisi berlawanan aktif "
                    f"[{opp_summary}] yang sedang berjalan menuju TP/SL. Menghindari whipsawing / tabrakan order."
                )
                print(f"\n{msg_opp}\n")
                return {"success": False, "message": msg_opp}

        # Batasan posisi terbuka berdasarkan tipe akun & sesi pasar:
        # Sesuai arahan pengguna: "hanya 1 /2 posisi di sesi us jam 19-12"
        # - Akun USD Standard: Maksimal 1 posisi (disiplin ketat)
        # - Akun CENT (USC):
        #   * Sesi US (19:00 - 24:00 WIB): Diizinkan maksimal 2 posisi jika ada momentum bagus
        #   * Di luar Sesi US (siang/sore): Mutlak HANYA 1 POSISI (menghentikan boncos penumpukan posisi ganda)
        is_cent = self.is_cent_account()
        is_us = False
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime, time
            now_wib = datetime.now(ZoneInfo("Asia/Jakarta")).time()
            is_us = time(19, 0) <= now_wib <= time(23, 59, 59)
        except Exception:
            pass

        if not is_cent:
            max_positions = int(self.cfg.get("max_positions_standard", 1))
        else:
            cent_base = int(self.cfg.get("max_positions_cent", 3))
            if is_us:
                max_positions = max(cent_base, int(self.cfg.get("us_session_max_positions", 3)))
            else:
                max_positions = cent_base

        if len(open_pos) >= max_positions:
            mode_lbl = (
                f"Sesi US Agresif (Maks {max_positions} Posisi)"
                if (is_cent and is_us)
                else (f"CENT USC Disiplin (Maks {max_positions} Posisi)" if is_cent else f"USD Standard (Maks {max_positions} Posisi)")
            )
            return {
                "success": False,
                "message": f"Batas posisi tercapai ({len(open_pos)}/{max_positions} posisi {sym} aktif di MT5). Mode: {mode_lbl}. Menunggu posisi selesai sebelum open baru."
            }

        s_info = self.mt5.symbol_info(sym)
        if not s_info:
            return {"success": False, "message": f"Simbol {sym} tidak ditemukan di MT5 member."}

        tick = self.mt5.symbol_info_tick(sym)
        if not tick:
            return {"success": False, "message": f"Gagal mendapatkan tick pasar {sym}."}

        order_type = self.mt5.ORDER_TYPE_BUY if action == "BUY" else self.mt5.ORDER_TYPE_SELL
        curr_price = tick.ask if action == "BUY" else tick.bid

        # Anti-Stacking Protection: Minimal jarak harga antar posisi terbuka searah (default $1.00 USD)
        min_grid_spacing = float(self.cfg.get("min_grid_spacing", 1.0))
        same_side_pos = [p for p in open_pos if (p.type == 0 and action == "BUY") or (p.type == 1 and action == "SELL")]
        if same_side_pos and curr_price > 0:
            min_dist = min(abs(curr_price - float(p.price_open)) for p in same_side_pos)
            if min_dist < min_grid_spacing:
                msg_stack = (
                    f"⛔ Penumpukan Posisi Dicegah: Sudah ada posisi {action} aktif di area harga ini "
                    f"(jarak harga live ${curr_price:,.2f} vs posisi terbuka hanya ${min_dist:.2f} < minimal grid ${min_grid_spacing:.2f} USD). "
                    f"Menjaga akun dari risiko over-exposure di titik harga yang sama."
                )
                print(f"\n{msg_stack}\n")
                return {"success": False, "message": msg_stack}

        # Proteksi Sinyal Telat (Price Drift Guard):
        # Jika harga live pasar sudah lari lebih dari batas toleransi (default $8.00 USD) dari harga sinyal Master,
        # tolak order seketika agar member tidak terjebak entry telat / di pucuk!
        sig_entry = float(sig.get("entry_price", 0.0))
        max_drift = float(self.cfg.get("max_price_drift", 8.0))
        if sig_entry > 0:
            price_drift = abs(curr_price - sig_entry)
            if price_drift > max_drift:
                msg_drift = (
                    f"⚠️ [SINYAL TELAT DITOLAK] Harga live (${curr_price:,.2f}) sudah lari "
                    f"${price_drift:.2f} USD dari harga sinyal (${sig_entry:,.2f}). "
                    f"Batas toleransi: ${max_drift:.2f} USD. Order dibatalkan demi melindungi modal trading member."
                )
                print(f"\n{msg_drift}\n")
                return {"success": False, "message": msg_drift}
        else:
            sig["entry_price"] = curr_price

        # Preservasi Jarak TP & SL Terencana (Dynamic Execution-Price Anchoring):
        tp_raw = float(sig.get("tp_price", 0.0) or 0.0)
        sl_raw = float(sig.get("sl_price", 0.0) or 0.0)
        ref_price = float(sig.get("entry_price", curr_price) or curr_price)
        digits = int(getattr(s_info, "digits", 2) or 2)

        if tp_raw > 0 and sl_raw > 0 and ref_price > 0:
            tp_dist = round(abs(tp_raw - ref_price), 2)
            sl_dist = round(abs(ref_price - sl_raw), 2)
            # KAIDAH BAKU RISK:REWARD GUARD (DILARANG KERAS TP 1 SL 2):
            if sl_dist > tp_dist:
                sl_dist = tp_dist
            
            if action == "BUY":
                tp_val = round(curr_price + tp_dist, digits)
                sl_val = round(curr_price - sl_dist, digits)
            else:
                tp_val = round(curr_price - tp_dist, digits)
                sl_val = round(curr_price + sl_dist, digits)
        else:
            tp_val = round(tp_raw, digits) if tp_raw > 0 else 0.0
            sl_val = round(sl_raw, digits) if sl_raw > 0 else 0.0

        # Money Management & Normalisasi Ukuran Lot
        # ATURAN BAKU PENGGUNA UNTUK AKUN STANDARD USD:
        # "jika sinyal nya kurang bagus atau lu pasang 0,01 di usd jgn pasang,
        #  untuk usd hanya untuk sinyal 0,05 yg bagus tp di usd nya lu open 0,01"
        is_high_grade = sig.get("is_high_grade", False)
        master_lot = float(sig.get("master_lot", 0.0) or 0.0)
        usd_only_high = self.cfg.get("usd_only_high_grade", True)

        if not is_cent:
            # Akun Standard USD:
            if usd_only_high and not is_high_grade and master_lot < 0.05:
                skip_msg = (
                    f"🛡️ [USD STANDARD FILTER] Sinyal ini adalah sinyal standar/kurang bagus (0.01 lot master). "
                    f"Sesuai arahan pengguna: Akun Standard USD DILARANG masuk pada sinyal 0.01 standar. "
                    f"HANYA masuk pada sinyal Grade A+ (0.05 lot bagus). Order dilewati demi melindungi modal USD!"
                )
                print(f"\n{skip_msg}\n")
                return {
                    "success": False,
                    "status": "usd_skip_standard_grade",
                    "message": skip_msg,
                }
            trade_lot, lot_lbl = self.calculate_lot_size(sig, is_cent=False)
            print(f"   💎 [USD HIGH GRADE] Sinyal Grade A+ (Momen Bagus 0.05 Lot). Membuka posisi disiplin {trade_lot} Lot di Akun Standard USD ({lot_lbl}).")
        else:
            # Akun Cent (USC): Sesuai sesi pasar & pengaturan lot member (0.05 lot / 0.08 lot Sesi US)
            trade_lot, lot_lbl = self.calculate_lot_size(sig, is_cent=True)
            print(f"   🎯 [CENT USC ORDER] Membuka posisi {trade_lot} Lot ({lot_lbl}).")

        vol_step = float(getattr(s_info, "volume_step", 0.01) or 0.01)
        if vol_step > 0:
            trade_lot = round(round(trade_lot / vol_step) * vol_step, 2)
        vol_min = float(getattr(s_info, "volume_min", 0.01) or 0.01)
        vol_max = float(getattr(s_info, "volume_max", 100.0) or 100.0)
        if trade_lot < vol_min:
            trade_lot = vol_min
        if trade_lot > vol_max:
            trade_lot = vol_max

        req = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": trade_lot,
            "type": order_type,
            "price": curr_price,
            "deviation": self.slippage,
            "magic": self.magic,
            "comment": "VIP-9PDF-Copy",
            "type_time": self.mt5.ORDER_TIME_GTC,
        }
        if tp_val > 0:
            req["tp"] = tp_val
        if sl_val > 0:
            req["sl"] = sl_val

        # Deteksi Filling Mode yang didukung broker (HFM, Exness, IC Markets, dll)
        filling_mode = int(s_info.filling_mode or 0)
        candidates = []
        if filling_mode & 1:  # FOK (misal broker HFM)
            candidates.append(self.mt5.ORDER_FILLING_FOK)
        if filling_mode & 2:  # IOC
            candidates.append(self.mt5.ORDER_FILLING_IOC)
        candidates.extend([self.mt5.ORDER_FILLING_FOK, self.mt5.ORDER_FILLING_IOC, self.mt5.ORDER_FILLING_RETURN])

        seen = set()
        fill_types = [f for f in candidates if not (f in seen or seen.add(f))]

        last_res = None
        for ft in fill_types:
            req["type_filling"] = ft
            res = self.mt5.order_send(req)
            last_res = res
            if res and res.retcode == self.mt5.TRADE_RETCODE_DONE:
                return {
                    "success": True,
                    "ticket": res.order,
                    "price": res.price,
                    "volume": res.volume,
                    "symbol": sym,
                }
            # Jika errornya bukan masalah filling mode (10030), jangan loop filling lagi
            if res and res.retcode != 10030:
                break

        res = last_res
        err_code = res.retcode if res else "No response"
        err_comment = res.comment if res else self.mt5.last_error()[1]
        return {"success": False, "message": f"RetCode: {err_code} - {err_comment}"}


async def run_telethon_listener(cfg: dict, bridge: MT5MemberBridge):
    """Mendengarkan sinyal dari Master Bot dengan verifikasi lisensi anti-share & auto-stop."""
    try:
        import logging
        from telethon import TelegramClient, events, functions

        # Redam log socket error raw dari Telethon agar tidak mencemari layar console member (Anti [WinError 64])
        logging.getLogger("telethon.network.mtprotosender").setLevel(logging.CRITICAL)
        logging.getLogger("telethon.network.connection").setLevel(logging.CRITICAL)
        logging.getLogger("telethon").setLevel(logging.ERROR)
    except ImportError:
        print("[!] Modul 'telethon' belum terpasang. Jalankan: pip install telethon")
        return

    API_ID = int(cfg.get("telegram_api_id") or os.getenv("TELEGRAM_API_ID", "2040"))
    API_HASH = str(cfg.get("telegram_api_hash") or os.getenv("TELEGRAM_API_HASH", "b18441a1ff607e10a989891a5462e627"))
    cfg_bot = cfg.get("bot_username", "selo_saham_bot").lstrip("@")
    target_bots = list(dict.fromkeys([cfg_bot, "selo_saham_bot", "Selobrow_bot"]))
    target_bot = target_bots[0]

    session_name = "member_copier_session"
    client = TelegramClient(
        session_name,
        API_ID,
        API_HASH,
        device_model="Windows PC Desktop",
        system_version="Windows 10/11",
        app_version="4.16.8 x64",
        connection_retries=None,  # Retry tak terbatas jika jaringan drop
        retry_delay=2,            # Sambung ulang cepat dalam 2 detik
        auto_reconnect=True,
        timeout=20,
        request_retries=10,
    )

    print(f"\n[+] Menghubungkan ke jaringan Telegram...")
    await client.connect()

    def clean_phone_number(phone_str: str) -> str:
        raw = re.sub(r"[^\d+]", "", phone_str.strip())
        if raw.startswith("0"):
            raw = "+62" + raw[1:]
        elif raw.startswith("62") and not raw.startswith("+"):
            raw = "+" + raw
        elif raw.startswith("+620"):
            raw = "+62" + raw[4:]
        elif not raw.startswith("+"):
            raw = "+" + raw
        return raw

    if not await client.is_user_authorized():
        from telethon.errors import (
            PhoneNumberInvalidError,
            FloodWaitError,
            PhoneCodeInvalidError,
            PhoneCodeExpiredError,
            PhoneCodeEmptyError,
            SessionPasswordNeededError,
            PasswordHashInvalidError,
        )
        import getpass

        clean_p = ""
        while True:
            print("\n" + "=" * 65)
            print("📲 LOGIN TELEGRAM MEMBER (HANYA SEKALI DI AWAL)")
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print("Ketik NOMOR HP Telegram Anda:")
            print("• Contoh: 081234567890 atau +6281234567890")
            print("")
            print("⚠️ PERHATIAN: BUKAN TOKEN BOT! Masukkan nomor HP Telegram Anda")
            print("agar copier terhubung ke akun VIP yang sudah di-approve Admin.")
            print("=" * 65)
            phone_input = input("\nNomor HP Telegram: ").strip()
            clean_p = clean_phone_number(phone_input)

            if len(clean_p) < 10:
                print(f"❌ Format nomor '{phone_input}' tidak valid. Silakan coba lagi.")
                continue

            print(f"\n[+] Mengirim permintaan kode OTP ke nomor: {clean_p} ...")
            try:
                await client.send_code_request(clean_p)
                break
            except PhoneNumberInvalidError:
                print(f"❌ Nomor {clean_p} tidak terdaftar di Telegram atau format salah. Periksa kembali nomor Anda.")
            except FloodWaitError as e:
                print(f"⚠️ Telegram membatasi pengiriman kode karena terlalu sering mencoba. Harap tunggu {e.seconds} detik.")
                await client.disconnect()
                return
            except Exception as ex:
                print(f"❌ Gagal mengirim kode OTP: {ex}")
                ulang = input("Apakah ingin mencoba nomor lain? (y/n): ").strip().lower()
                if ulang != "y":
                    await client.disconnect()
                    return

        print("\n" + "=" * 65)
        print("📩 KODE OTP 5-DIGIT TELAH DIKIRIM OLEH TELEGRAM! 🚀")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("⚠️ PERHATIAN PENTING - BACA BAIK-BAIK:")
        print("1. Kode OTP TIDAK DIKIRIM KE SMS PULSA HP!")
        print("2. Buka APLIKASI TELEGRAM di HP atau PC Anda sekarang juga.")
        print("3. Cari chat resmi dari 'Telegram' (dengan centang biru verified).")
        print("   Pesan berisi: 'Login code: XXXXX. Do not give this code...'")
        print("=============================================================\n")

        for attempt in range(3):
            otp_input = input("👉 Masukkan 5-Digit Kode OTP Telegram: ").strip()
            clean_otp = re.sub(r"\D", "", otp_input)
            if not clean_otp:
                print("❌ Kode OTP tidak boleh kosong.")
                continue

            try:
                await client.sign_in(clean_p, code=clean_otp)
                print("✅ Verifikasi kode OTP berhasil!")
                break
            except SessionPasswordNeededError:
                print("\n🔒 Akun Anda mengaktifkan Verifikasi 2 Langkah (Two-Step Verification).")
                try:
                    pwd = getpass.getpass("Password 2FA Telegram Anda: ")
                except Exception:
                    pwd = input("Password 2FA Telegram Anda: ").strip()
                try:
                    await client.sign_in(password=pwd)
                    print("✅ Verifikasi password 2FA berhasil!")
                    break
                except PasswordHashInvalidError:
                    print("❌ Password 2FA salah!")
                    await client.disconnect()
                    return
            except (PhoneCodeInvalidError, PhoneCodeEmptyError):
                print(f"❌ Kode OTP salah! Sisa percobaan: {2 - attempt}")
                if attempt == 2:
                    await client.disconnect()
                    return
            except PhoneCodeExpiredError:
                print("❌ Kode OTP sudah kedaluwarsa. Silakan jalankan ulang copier untuk meminta kode baru.")
                await client.disconnect()
                return
            except Exception as ex_sign:
                print(f"❌ Gagal verifikasi login: {ex_sign}")
                await client.disconnect()
                return


    me = await client.get_me()
    user_id = str(me.id)
    user_display = f"@{me.username}" if me.username else (me.first_name or f"User #{user_id}")

    print(f"[+] Akun Telegram login: {user_display} (ID: {user_id})")
    print(f"[+] Memvalidasi lisensi ke Master Bot (@{target_bot})...")

    # 1. Handshake Verifikasi Lisensi ke Master Bot
    license_data = {"valid": False, "expires_at": "", "remaining": ""}
    auth_received = asyncio.Event()

    @client.on(events.NewMessage)
    async def temp_license_listener(event):
        sender = await event.get_sender()
        s_uname = (getattr(sender, "username", "") or "").lower()
        txt = event.raw_text or ""
        is_bot = any(b.lower() in s_uname for b in target_bots) or "selo" in s_uname or "saham" in s_uname
        if is_bot and "LIC_INFO|" in txt:
            parts = txt.strip().split("|")
            if len(parts) >= 5 and parts[1] == user_id:
                license_data["valid"] = (parts[2].upper() == "VALID")
                license_data["expires_at"] = parts[3]
                license_data["remaining"] = parts[4]
                auth_received.set()
                try:
                    await event.delete()
                except Exception:
                    pass

    # Kirim ping verifikasi lisensi ke Master Bot (hanya 1x saat buka copier)
    sent_msgs = []
    for b in target_bots:
        try:
            sm = await client.send_message(b, "/license")
            if sm:
                sent_msgs.append(sm)
        except Exception:
            pass

    try:
        await asyncio.wait_for(auth_received.wait(), timeout=7.0)
    except Exception:
        pass

    for sm in sent_msgs:
        try:
            await sm.delete()
        except Exception:
            pass

    client.remove_event_handler(temp_license_listener)

    # 2. Cek Hasil Verifikasi Lisensi (Anti-Share)
    if not license_data["valid"]:
        print("\n" + "=" * 65)
        print("❌ [AKSES DITOLAK / LISENSI TIDAK VALID]")
        print(f"Akun Telegram: {user_display} (ID: {user_id})")
        print("Akun ini BELUM DISETUJUI atau MASA AKTIF TELAH HABIS.")
        print("")
        print("🔒 PROTEKSI ANTI-SHARE AKTIF:")
        print("File copier ini terkunci dan TIDAK BISA DIBAGIKAN ke orang lain.")
        print("Silakan hubungi Master Admin (@selobrow) untuk aktivasi lisensi resmi!")
        print("=" * 65 + "\n")
        await client.disconnect()
        return

    exp_str = license_data["expires_at"]
    rem_str = license_data["remaining"]

    print("\n" + "=" * 65)
    print("✅ [LISENSI TERVERIFIKASI RESMI DARI MASTER ADMIN] 🎉")
    print(f"👤 Pengguna Terdaftar : {user_display} (Chat ID: {user_id})")
    print(f"⏱️ Masa Aktif Lisensi : {rem_str} (Berlaku s/d: {exp_str})")
    active_lot, lot_lbl = bridge.calculate_lot_size({}, bridge.is_cent_account())
    print(f"📦 Ukuran Lot MT5     : {active_lot} Lot ({lot_lbl})")
    print(f"📡 Status             : Standby menerima sinyal 9 Buku PDF...")
    print("=" * 65 + "\n")

    copier_start_time = datetime.now(timezone.utc)

    # 3. Pengatur Waktu Auto-Shutdown (Auto-Stop saat Expired)
    expiry_dt = None
    if exp_str and exp_str.upper() != "LIFETIME":
        try:
            tz_wib = ZoneInfo("Asia/Jakarta")
            # Parse YYYY-MM-DD HH:MM:SS
            raw_dt_str = exp_str[:19].strip()
            expiry_dt = datetime.strptime(raw_dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz_wib)
        except Exception:
            pass

    async def expiry_auto_stopper():
        """Memantau sisa waktu lisensi dan otomatis mematikan copier saat waktu habis atau dicabut Admin."""
        while True:
            await asyncio.sleep(15)
            if expiry_dt:
                tz_wib = ZoneInfo("Asia/Jakarta")
                now_wib = datetime.now(tz_wib)
                if now_wib >= expiry_dt:
                    print("\n" + "=" * 65)
                    print("⏳ [MASA AKTIF LISENSI TELAH BERAKHIR]")
                    print(f"Batas waktu akses Anda ({exp_str}) telah habis.")
                    print("Copier otomatis BERHENTI beroperasi demi keamanan akun Anda.")
                    print("Silakan hubungi Master Admin (@selobrow) untuk perpanjangan!")
                    print("=" * 65 + "\n")
                    await client.disconnect()
                    os._exit(0)


    asyncio.create_task(expiry_auto_stopper())

    # Keep-Alive Heartbeat Task: Mencegah ISP/Router me-reset socket TCP [WinError 64] saat idle
    async def telegram_keepalive_daemon():
        """Mengirim ping heartbeat berkala ke Telegram agar NAT table router tidak memutus socket [WinError 64]."""
        while True:
            await asyncio.sleep(20)
            try:
                if client.is_connected():
                    await client(functions.PingRequest(ping_id=int(time.time())))
            except Exception:
                pass

    asyncio.create_task(telegram_keepalive_daemon())

    # Live In-App OTA Poller: Memeriksa dan menerapkan update otomatis saat aplikasi SEDANG BERJALAN AKTIF
    async def live_ota_checker_daemon():
        """
        Memeriksa update sistem di Cloud setiap 30 detik saat copier aktif berjalan.
        Jika versi baru dirilis, copier otomatis memperbarui file dan me-reload tanpa perlu ditutup manual!
        """
        while True:
            await asyncio.sleep(30)
            try:
                updated = await asyncio.to_thread(check_and_apply_ota_update, silent=True)
                if updated:
                    break
            except Exception:
                pass

    asyncio.create_task(live_ota_checker_daemon())

    # 4. Listener Sinyal Masuk & Kontrol Lisensi Real-Time
    recent_executed_signals = {}

    @client.on(events.NewMessage)
    async def message_handler(event):
        sender = await event.get_sender()
        sender_username = (getattr(sender, "username", "") or "").lower()

        # Hanya terima pesan dari Master Bot resmi
        is_valid_bot = any(b.lower() in sender_username for b in target_bots) or "selo" in sender_username
        if not is_valid_bot:
            return

        # 0a. DETEKSI PERINTAH UPDATE INSTAN DARI MASTER BOT (BROADCAST / UPDATE)
        msg_raw_test = (event.raw_text or "").upper()
        if any(cmd in msg_raw_test for cmd in ["[UPDATE_COPIER]", "UPDATE_COPIER", "/UPDATE_COPIER", "/UPDATE_CLIENT", "UPDATE AUTO-COPIER", "AUTO-UPDATE"]):
            print("\n" + "=" * 70)
            print("🔔 [PERINTAH PEMBARUAN MASTER BOT DITERIMA SECARA LANGSUNG]")
            print("🚀 Memeriksa dan menerapkan update terbaru dari Cloud tanpa perlu menutup aplikasi...")
            print("=" * 70 + "\n")
            updated = await asyncio.to_thread(check_and_apply_ota_update, silent=False)
            if updated:
                return

        # 0b. DETEKSI DOKUMEN / ZIP PEMBARUAN OTOMATIS DARI MASTER BOT (IN-APP AUTO-UPDATE)
        # Member tidak perlu lagi unduh atau timpa ZIP manual!
        if getattr(event.message, "file", None) is not None:
            doc_name = (getattr(event.message.file, "name", "") or "").lower()
            caption_text = (event.raw_text or "").lower()
            if "copier" in doc_name or "member_copier" in caption_text or "update auto-copier" in caption_text or "update resmi" in caption_text:
                print("\n" + "=" * 70)
                print("🔔 [NOTIFIKASI RESMI MASTER BOT] PEMBARUAN AUTO-COPIER TERBARU DITERIMA!")
                print("📥 Mengunduh file pembaruan otomatis langsung dari Telegram (Tanpa Timpa ZIP)...")
                try:
                    temp_zip = Path(__file__).resolve().parent / "_update_temp.zip"
                    await event.message.download_media(file=str(temp_zip))
                    if temp_zip.exists() and temp_zip.stat().st_size > 500:
                        print("📦 Menerapkan pembaruan sistem (Pengaturan Akun & Lot Anda Tetap Aman)...")
                        apply_zip_update(temp_zip, preserve_config=True)
                        try:
                            temp_zip.unlink()
                        except Exception:
                            pass
                        print("✅ [PEMBARUAN BERHASIL DITERAPKAN OTOMATIS]")
                        print("🔄 Memuat ulang Copier ke versi terbaru tanpa perlu buka-tutup...")
                        print("=" * 70 + "\n")
                        try:
                            if client.is_connected():
                                asyncio.create_task(client.disconnect())
                        except Exception:
                            pass
                        time.sleep(1.0)
                        restart_copier()
                        return
                    else:
                        print("⚠️ File unduhan update tidak valid, melewati update.")
                except Exception as ex_dl:
                    print(f"⚠️ Gagal auto-update dari Telegram: {ex_dl}")

        msg_text = event.raw_text or ""
        msg_date = getattr(getattr(event, "message", None), "date", None)
        now_utc = datetime.now(timezone.utc)
        age_sec = (now_utc - msg_date).total_seconds() if msg_date else 0.0

        # Proteksi Pesan Lampau / Riwayat Chat (Backlog saat baru buka copier):
        # Jika pesan dikirim sebelum copier dijalankan atau usia pesan > 120 detik (2 menit),
        # lewati pesan ini agar tidak mengeksekusi sinyal lama & tidak memicu false alarm price drift!
        if msg_date and (msg_date < copier_start_time - timedelta(seconds=15) or age_sec > 120.0):
            mins_ago = int(age_sec // 60)
            sec_rem = int(age_sec % 60)
            time_lbl = f"{mins_ago}m {sec_rem}s" if mins_ago > 0 else f"{sec_rem}s"
            if any(k in msg_text.upper() for k in ["BUY", "SELL", "XAUUSD", "GOLD", "ENTRY"]):
                print(f"\nℹ️ [{datetime.now().strftime('%H:%M:%S')}] [SINYAL LAMPAU DILEWATI] Sinyal dari riwayat chat "
                      f"(diterbitkan {time_lbl} yang lalu saat copier belum aktif / offline). Dilewati demi menjaga keamanan modal member.")
            return

        # Deteksi respons lisensi real-time
        if "LIC_INFO|" in msg_text:
            parts = msg_text.strip().split("|")
            if len(parts) >= 5 and parts[1] == user_id:
                if parts[2].upper() != "VALID":
                    print("\n" + "=" * 65)
                    print("🚫 [AKSES LISENSI TELAH DICABUT OLEH ADMIN / KADALUWARSA]")
                    print(f"Akun Anda ({user_display}) telah dinonaktifkan oleh Master Admin.")
                    print("Copier otomatis BERHENTI beroperasi seketika.")
                    print("=" * 65 + "\n")
                    await client.disconnect()
                    os._exit(0)
            return

        # Deteksi notifikasi pencabutan akses langsung dari Admin
        msg_lower = msg_text.lower()
        if "akses dicabut" in msg_lower or "akses ditolak" in msg_lower or "dinonaktifkan oleh admin" in msg_lower:
            print("\n" + "=" * 65)
            print("🚫 [AKSES ANDA TELAH DICABUT OLEH ADMIN]")
            print("Master Admin (@selobrow) telah menonaktifkan izin akses akun ini.")
            print("Copier otomatis BERHENTI seketika.")
            print("=" * 65 + "\n")
            await client.disconnect()
            os._exit(0)

        # Cek apakah lisensi masih berlaku sebelum open posisi
        if expiry_dt:
            tz_wib = ZoneInfo("Asia/Jakarta")
            if datetime.now(tz_wib) >= expiry_dt:
                print("\n[!] Sinyal diabaikan: Masa aktif lisensi telah habis.")
                return

        msg_upper = msg_text.upper()

        # Deteksi Reversal Guard (Ambil Untung Otomatis dari Master Bot)
        if "REVERSAL GUARD" in msg_upper or "AMBIL UNTUNG OTOMATIS" in msg_upper:
            enable_rev_close = bool(cfg.get("enable_reversal_auto_close", False))
            if enable_rev_close:
                print(f"\n🛡️ [{datetime.now().strftime('%H:%M:%S')}] ALERT REVERSAL GUARD DITERIMA DARI MASTER BOT!")
                sym = bridge.find_broker_symbol()
                target_act = None
                if "POSISI DITUTUP: BUY" in msg_upper or "🟢 BUY" in msg_upper:
                    target_act = "BUY"
                elif "POSISI DITUTUP: SELL" in msg_upper or "🔴 SELL" in msg_upper:
                    target_act = "SELL"

                closed_list = bridge.close_all_positions(sym, action=target_act)
                if closed_list:
                    for c in closed_list:
                        status_lbl = "BERHASIL" if c["success"] else "GAGAL"
                        print(f"   🔒 [AUTO-CLOSE REVERSAL] Posisi {c['action']} #{c['ticket']} {status_lbl} ditutup untuk mengamankan profit!")
                else:
                    print(f"   ℹ️ Tidak ada posisi terbuka {target_act or ''} pada {sym} di MT5 Anda.")
            else:
                print(f"\nℹ️ [{datetime.now().strftime('%H:%M:%S')}] PERINGATAN REVERSAL MASTER (INFO):")
                print("   Master mendeteksi indikasi pembalikan pasar. Sesuai setting, posisi Anda tetap dibiarkan berjalan menuju target TP/SL.")
            return

        # Deteksi Proteksi Modal (BEP Lock & Trailing Stop dari Master Bot)
        if "BREAK-EVEN PROTECTION" in msg_upper or "TRAILING STOP NAIK" in msg_upper or "TRAILING STOP TURUN" in msg_upper:
            print(f"\n🛡️ [{datetime.now().strftime('%H:%M:%S')}] ALERT KUNCI PROFIT DITERIMA DARI MASTER BOT!")
            sym = bridge.find_broker_symbol()
            target_act = "BUY" if "BUY" in msg_upper else ("SELL" if "SELL" in msg_upper else None)
            m_sl = re.search(r"SL Pengaman Baru.*?[:=]?\s*\$?([\d.,]+)", msg_text, re.IGNORECASE)
            if m_sl:
                cleaned_sl = re.sub(r"[^\d.]", "", m_sl.group(1))
                try:
                    new_sl_val = float(cleaned_sl)
                    mod_list = bridge.modify_open_positions_sl(sym, action=target_act, new_sl=new_sl_val)
                    if mod_list:
                        for m in mod_list:
                            status_lbl = "SUKSES" if m["success"] else "GAGAL"
                            print(f"   🔒 [BEP/TRAILING MT5] Posisi {m['action']} #{m['ticket']} {status_lbl} digeser SL-nya ke ${new_sl_val:.2f}!")
                    else:
                        print(f"   ℹ️ Posisi Anda pada {sym} sudah aman atau SL sudah lebih baik.")
                except Exception as ex:
                    print(f"   ⚠️ Gagal memproses SL baru: {ex}")
            return

        # Deteksi Peringatan Dini Pembalikan Arah (Early Warning Alert)
        if "PERINGATAN DINI PEMBALIKAN ARAH TREN" in msg_upper:
            print(f"\n⚠️ [{datetime.now().strftime('%H:%M:%S')}] PERINGATAN DINI DARI MASTER BOT:")
            print("   Indikasi awal pembalikan arah XAU/USD terdeteksi. Posisi MT5 Anda tetap berjalan dalam siaga.")
            return

        sig = parse_signal(msg_text)
        if not sig:
            return

        # Deduplikasi Cerdas: Cegah double execution dari kartu laporan eksekusi & kartu sinyal beruntun
        now_ts = time.time()
        sig_ticket = sig.get("ticket")
        sig_tp = sig.get("tp_price", 0.0)
        sig_sl = sig.get("sl_price", 0.0)
        sig_act = sig.get("action")
        sig_sym = sig.get("symbol", "XAUUSD")

        # Bersihkan riwayat eksekusi lama (> 1800 detik / 30 menit)
        for k in list(recent_executed_signals.keys()):
            if now_ts - recent_executed_signals[k] > 1800:
                del recent_executed_signals[k]

        is_duplicate = False
        if sig_ticket and f"ticket_{sig_ticket}" in recent_executed_signals:
            is_duplicate = True
        elif sig_tp > 0 and sig_sl > 0:
            param_key = f"{sig_act}_{sig_tp:.1f}_{sig_sl:.1f}"
            if param_key in recent_executed_signals:
                if now_ts - recent_executed_signals[param_key] < 900:  # 15 menit
                    is_duplicate = True

        if is_duplicate:
            print(f"\nℹ️ [{datetime.now().strftime('%H:%M:%S')}] [DUPLIKAT DIABAIKAN] Sinyal {sig_act} {sig_sym} "
                  f"(TP: ${sig_tp:,.2f}, SL: ${sig_sl:,.2f}) sudah pernah dieksekusi sebelumnya.")
            return

        # Fallback entry_price jika belum terdeteksi agar tidak tampil $0.00
        if sig.get("entry_price", 0.0) <= 0:
            if bridge.mt5:
                tick_now = bridge.mt5.symbol_info_tick(bridge.find_broker_symbol())
                if tick_now:
                    sig["entry_price"] = tick_now.ask if sig_act == "BUY" else tick_now.bid

        print(f"\n⚡ [{datetime.now().strftime('%H:%M:%S')}] SINYAL DITERIMA DARI MASTER BOT:")
        print(f"   Aksi  : {sig['action']} {sig['symbol']}")
        print(f"   Entry : ${sig['entry_price']:,.2f}")
        print(f"   TP    : ${sig['tp_price']:,.2f}")
        print(f"   SL    : ${sig['sl_price']:,.2f}")

        # Eksekusi ke terminal MT5 member
        res = bridge.execute_order(sig)
        sync_event_to_dashboard(sig, res)

        if res.get("success"):
            # Catat ke riwayat deduplikasi agar kartu duplikat diabaikan
            if sig_ticket:
                recent_executed_signals[f"ticket_{sig_ticket}"] = now_ts
            if sig_tp > 0 and sig_sl > 0:
                recent_executed_signals[f"{sig_act}_{sig_tp:.1f}_{sig_sl:.1f}"] = now_ts

            print(f"   ✅ [ORDER MT5 SUKSES] #{res['ticket']} {sig['action']} {res['volume']} Lot @ ${res['price']:,.2f} pada {res['symbol']}\n")
        else:
            err_msg = str(res.get("message", ""))
            print(f"   ❌ [ORDER GAGAL] {err_msg}")
            if "10027" in err_msg or "AutoTrading disabled" in err_msg:
                print("   ┌─────────────────────────────────────────────────────────────┐")
                print("   │ 💡 SOLUSI MUDAH (ERROR 10027 - ALGO TRADING MT5 MATI):      │")
                print("   │ 1. Buka aplikasi MetaTrader 5 kamu sekarang juga.           │")
                print("   │ 2. Klik tombol 'Algo Trading' di toolbar atas sampai HIJAU  │")
                print("   │    (atau tekan tombol keyboard: Ctrl + E).                  │")
                print("   │ 3. Menu Tools -> Options -> Expert Advisors -> centang      │")
                print("   │    'Allow Algo Trading' lalu klik OK.                       │")
                print("   └─────────────────────────────────────────────────────────────┘\n")
            else:
                print()

    async def local_bep_watcher():
        """
        Background Watcher Mandiri di MT5 Member:
        Jika terdeteksi posisi sinyal Long / TP Jauh (target TP >= 85 pips atau open target),
        dan floating profit telah mencapai +100 pips ($10.00 USD),
        otomatis geser SL ke Break-Even (BEP) + buffer pengaman 3 pips ($0.30 USD) di atas/bawah entry.
        Berfungsi sebagai proteksi berlapis seandainya notifikasi Telegram delay atau terputus.
        """
        if not cfg.get("enable_break_even", True):
            return

        bep_pips = float(cfg.get("break_even_long_pips", 100.0))
        buffer_pips = float(cfg.get("break_even_buffer_pips", 3.0))
        bep_dist = bep_pips / 10.0      # 100 pips = $10.00 USD
        bep_offset = buffer_pips / 10.0  # 3 pips = $0.30 USD

        while True:
            try:
                await asyncio.sleep(5)
                if not bridge.ensure_connected():
                    continue

                sym = bridge.find_broker_symbol()
                open_pos = bridge.mt5.positions_get(symbol=sym) or []
                for p in open_pos:
                    ticket = p.ticket
                    pos_type = "BUY" if p.type == 0 else "SELL"
                    price_open = float(p.price_open)
                    price_curr = float(p.price_current)
                    sl_curr = float(p.sl or 0.0)
                    tp_curr = float(p.tp or 0.0)

                    if price_open <= 0 or price_curr <= 0:
                        continue

                    if pos_type == "BUY":
                        profit_dist = price_curr - price_open
                        tp_dist = (tp_curr - price_open) if tp_curr > 0 else 999.0
                        if (tp_dist >= 8.5 or tp_curr == 0.0) and profit_dist >= bep_dist:
                            target_bep = round(price_open + bep_offset, 2)
                            if sl_curr < target_bep:
                                req = {
                                    "action": bridge.mt5.TRADE_ACTION_SLTP,
                                    "position": ticket,
                                    "symbol": p.symbol,
                                    "sl": target_bep,
                                    "tp": tp_curr,
                                }
                                res = bridge.mt5.order_send(req)
                                if res and res.retcode == bridge.mt5.TRADE_RETCODE_DONE:
                                    print(
                                        f"\n🛡️ [LOCAL AUTO-BEP MEMBER] Posisi BUY #{ticket} floating +${profit_dist:.2f} USD "
                                        f"(+{int(profit_dist*10)} pips). SL digeser ke ${target_bep:.2f} (FREE TRADE)!"
                                    )
                    elif pos_type == "SELL":
                        profit_dist = price_open - price_curr
                        tp_dist = (price_open - tp_curr) if tp_curr > 0 else 999.0
                        if (tp_dist >= 8.5 or tp_curr == 0.0) and profit_dist >= bep_dist:
                            target_bep = round(price_open - bep_offset, 2)
                            if sl_curr == 0.0 or sl_curr > target_bep:
                                req = {
                                    "action": bridge.mt5.TRADE_ACTION_SLTP,
                                    "position": ticket,
                                    "symbol": p.symbol,
                                    "sl": target_bep,
                                    "tp": tp_curr,
                                }
                                res = bridge.mt5.order_send(req)
                                if res and res.retcode == bridge.mt5.TRADE_RETCODE_DONE:
                                    print(
                                        f"\n🛡️ [LOCAL AUTO-BEP MEMBER] Posisi SELL #{ticket} floating +${profit_dist:.2f} USD "
                                        f"(+{int(profit_dist*10)} pips). SL digeser ke ${target_bep:.2f} (FREE TRADE)!"
                                    )
            except Exception:
                pass

    # Jalankan background watcher otomatis untuk Break-Even Protection (BEP) di MT5 Member
    asyncio.create_task(local_bep_watcher())

    # Jalankan background task pemeriksaan pembaruan OTA Cloud berkala (tiap 30 menit)
    async def periodic_ota_checker():
        while True:
            await asyncio.sleep(1800)
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: check_and_apply_ota_update(silent=True))
            except Exception:
                pass

    asyncio.create_task(periodic_ota_checker())

    # Loop pemulihan koneksi Telegram (Anti-Crash & Auto-Reconnect)
    while True:
        try:
            await client.run_until_disconnected()
            break
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception:
            await asyncio.sleep(2)
            if not client.is_connected():
                try:
                    await client.connect()
                except Exception:
                    pass


def main():
    print("=" * 65)
    print("    AUTO-COPIER MT5 MEMBER (VIP 9 BUKU PDF CONFLUENCE)")
    print("=" * 65)

    # Cek pembaruan Over-The-Air (OTA) saat startup (Tanpa Perlu Timpa ZIP Manual!)
    if "--no-update" not in sys.argv and "--test" not in sys.argv:
        check_and_apply_ota_update(silent=False)

    cfg = load_config()
    bridge = MT5MemberBridge(cfg)

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("\n[TEST MODE] Menguji parser dan koneksi...")
        sample_signal = (
            "🔴 SINYAL ENTRY SHORT (SELL): XAU/USD (Gold Spot)\n"
            "📍 Harga Entry Short: $4,161.73\n"
            "🎯 Take Profit (TP): $4,128.80 (-0.79% Target Bawah)\n"
            "🛑 Stop Loss (SL): $4,178.75 (+0.41% Batas Atas)\n"
        )
        parsed = parse_signal(sample_signal)
        print(f"Hasil Parser: {parsed}")
        sym = bridge.find_broker_symbol()
        print(f"Simbol broker terdeteksi: {sym}")
        return

    try:
        asyncio.run(run_telethon_listener(cfg, bridge))
    except KeyboardInterrupt:
        print("\nCopier dihentikan oleh pengguna.")


if __name__ == "__main__":
    import subprocess
    # Supervisor loop otomatis: Memastikan copier selalu reload di jendela console yang SAMA
    # baik dijalankan via START_COPIER.bat, terminal CMD, PowerShell, maupun klik langsung.
    # Member tidak perlu lagi menutup dan membuka ulang aplikasi saat ada update!
    if os.environ.get("COPIER_SUPERVISED") != "1" and "--test" not in sys.argv and "--no-supervise" not in sys.argv:
        os.environ["COPIER_SUPERVISED"] = "1"
        while True:
            exit_code = subprocess.call([sys.executable, str(Path(__file__).resolve())] + sys.argv[1:])
            if exit_code in (42, 100):
                print("\n" + "=" * 65)
                print("🔄 [HOT RELOAD] Memuat ulang Copier ke versi terbaru tanpa perlu buka-tutup...")
                print("=" * 65 + "\n")
                time.sleep(1.0)
                continue
            else:
                sys.exit(exit_code)
    else:
        main()
