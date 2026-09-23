import os
import sys
import time
from datetime import datetime, time as dtime
from typing import Optional, Tuple, Dict, Any, List
from pathlib import Path
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Add base directory to path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config.settings import load_config, setup_logger
from data.fetcher import DataFetcher
from data.storage import StockStorage
from indicators.technical import TechnicalIndicators
from strategy.rules import get_strategy, DEFAULT_STRATEGY
from strategy.signal_engine import SignalEngine, SignalResult
from notify.telegram_bot import TelegramNotifier

logger = setup_logger("scheduler")


def is_idx_market_open(
    dt: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    Memeriksa apakah saat ini berada dalam jam perdagangan aktif Bursa Efek Indonesia (IDX).
    
    Jadwal Perdagangan IDX (WIB - Asia/Jakarta):
    - Senin s/d Kamis:
      Sesi 1: 09:00 - 11:30 WIB
      Sesi 2: 13:30 - 15:50 WIB
    - Jumat:
      Sesi 1: 09:00 - 11:30 WIB
      Sesi 2: 14:00 - 15:50 WIB
    - Sabtu & Minggu: Tutup
    """
    cfg = config or load_config()
    sched_cfg = cfg.get("scheduler", {})

    # Opsi bypass filter jam bursa (misal untuk testing / development)
    if not sched_cfg.get("check_market_hours", True):
        return True, "Filter jam bursa dinonaktifkan di konfigurasi (mode dev/testing)."

    tz_name = sched_cfg.get("timezone", "Asia/Jakarta")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Jakarta")

    now = dt or datetime.now(tz)
    weekday = now.weekday()  # 0: Senin, 4: Jumat, 5: Sabtu, 6: Minggu
    curr_time = now.time()

    # Cek Hari Libur Akhir Pekan
    if weekday >= 5:
        return False, f"Bursa Tutup (Akhir Pekan: {now.strftime('%A')})."

    # Waktu Sesi 1 (Semua Hari Senin-Jumat)
    s1_start = dtime(9, 0)
    s1_end = dtime(11, 30)

    # Waktu Sesi 2
    if weekday == 4:  # Jumat
        s2_start = dtime(14, 0)
        s2_end = dtime(15, 50)
        session_name = "Jumat"
    else:  # Senin - Kamis
        s2_start = dtime(13, 30)
        s2_end = dtime(15, 50)
        session_name = "Senin-Kamis"

    # Evaluasi Sesi 1
    if s1_start <= curr_time <= s1_end:
        return True, f"Bursa Buka (Sesi 1 {session_name}: 09:00 - 11:30 WIB)."

    # Evaluasi Jeda Siang
    if s1_end < curr_time < s2_start:
        return False, f"Bursa Istirahat Siang (Sesi 1 Selesai, Sesi 2 mulai pukul {s2_start.strftime('%H:%M')} WIB)."

    # Evaluasi Sesi 2
    if s2_start <= curr_time <= s2_end:
        return True, f"Bursa Buka (Sesi 2 {session_name}: {s2_start.strftime('%H:%M')} - 15:50 WIB)."

    # Di luar jam tersebut
    if curr_time < s1_start:
        return False, f"Bursa Belum Buka (Perdagangan dimulai pukul 09:00 WIB)."
    else:
        return False, f"Bursa Sudah Tutup (Perdagangan berakhir pukul 15:50 WIB)."


class PipelineRunner:
    """Eksekutor pipeline analisis pasar, evaluasi sinyal, dan pengiriman notifikasi."""

    def __init__(
        self,
        storage: Optional[StockStorage] = None,
        fetcher: Optional[DataFetcher] = None,
        notifier: Optional[TelegramNotifier] = None,
    ):
        self.config = load_config()
        self.storage = storage or StockStorage()
        self.fetcher = fetcher or DataFetcher(storage=self.storage)
        self.notifier = notifier or TelegramNotifier(storage=self.storage)
        self.signal_engine = SignalEngine()

    def run_pipeline(self, force_run: bool = False) -> Dict[str, Any]:
        """
        Menjalankan 1 siklus penuh pipeline:
        1. Validasi jam bursa IDX.
        2. Ambil data terbaru untuk seluruh saham di watchlist.
        3. Hitung indikator teknikal.
        4. Jalankan rule engine & evaluasi sinyal.
        5. Filter deduplikasi sinyal.
        6. Kirim notifikasi Telegram jika ada sinyal baru.
        """
        logger.info("=== Memulai Siklus Pipeline Analisis Saham ===")

        # 1. Cek Jam Bursa
        is_open, reason = is_idx_market_open(config=self.config)
        logger.info(f"Status Pasar IDX: {reason}")

        if not is_open and not force_run:
            logger.info("Melewatkan pipeline karena bursa sedang tidak aktif.")
            return {"status": "skipped", "reason": reason}

        # 2. Baca Konfigurasi Trading & Watchlist
        watchlist = self.config.get("watchlist", ["BBCA.JK"])
        trading_cfg = self.config.get("trading", {})
        trading_mode = trading_cfg.get("mode", "intraday")

        if trading_mode == "intraday":
            interval = trading_cfg.get("intraday", {}).get("interval", "15m")
            period = self.config.get("data", {}).get("intraday_period", "60d")
        else:
            interval = trading_cfg.get("daily", {}).get("interval", "1d")
            period = self.config.get("data", {}).get("default_period", "2y")

        logger.info(
            f"Mode Trading: {trading_mode.upper()} (Interval: {interval}, Saham: {len(watchlist)})"
        )

        results = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "processed": 0,
            "signals_triggered": 0,
            "signals_notified": 0,
            "details": [],
        }

        # 3. Iterasi setiap saham dalam watchlist
        for ticker in watchlist:
            try:
                results["processed"] += 1
                logger.info(f"Memproses {ticker}...")

                # Ambil data candle terbaru
                df = self.fetcher.fetch_and_store(ticker, interval=interval, period=period)
                if df.empty or len(df) < 20:
                    logger.warning(f"Data tidak mencukupi untuk {ticker}, dilewati.")
                    continue

                # Hitung Indikator
                df_ind = TechnicalIndicators.add_all_indicators(df)

                # Evaluasi Sinyal (candle terakhir)
                sig_result = self.signal_engine.evaluate_bar(df_ind, ticker=ticker, bar_idx=-1)

                is_duplicate, dup_reason = self._check_duplicate(sig_result)
                should_notify = (sig_result.signal in ["BUY", "SELL"]) and (not is_duplicate)

                if sig_result.signal in ["BUY", "SELL"]:
                    results["signals_triggered"] += 1

                # Simpan ke Database
                self.storage.save_signal(
                    ticker=sig_result.ticker,
                    strategy_name=sig_result.strategy_name,
                    signal_type=sig_result.signal,
                    price=sig_result.price,
                    reasons=sig_result.reasons,
                    candle_time=sig_result.candle_time,
                    is_notified=should_notify,
                )

                # Kirim Notifikasi jika sinyal valid dan bukan duplikat
                if should_notify:
                    logger.info(f"🚨 Sinyal Baru Terdeteksi: {sig_result.signal} {sig_result.ticker} @ {sig_result.price}")
                    self.notifier.send_signal(sig_result)
                    results["signals_notified"] += 1
                elif is_duplicate:
                    logger.debug(f"Sinyal {sig_result.signal} untuk {ticker} dilewati (Duplikat: {dup_reason}).")

                results["details"].append({
                    "ticker": ticker,
                    "signal": sig_result.signal,
                    "price": sig_result.price,
                    "candle_time": sig_result.candle_time,
                    "notified": should_notify,
                })

            except Exception as e:
                logger.error(f"Error memproses pipeline untuk {ticker}: {e}")

        logger.info(
            f"=== Pipeline Selesai: {results['processed']} saham diproses, "
            f"{results['signals_triggered']} sinyal aktif, {results['signals_notified']} notifikasi terkirim ==="
        )
        return results

    def _check_duplicate(self, sig: SignalResult) -> Tuple[bool, str]:
        """
        Mencegah spam notifikasi berulang untuk kondisi sinyal yang sama.
        
        Aturan Deduplikasi:
        1. Sinyal HOLD tidak pernah dinotifikasikan.
        2. Jika sinyal BUY/SELL sama dengan sinyal terakhir pada candle_time yang sama -> DUPLIKAT.
        3. Jika sinyal terakhir bertipe sama (misal BUY) dan sudah dinotifikasikan dalam siklus sebelumnya -> DUPLIKAT
           (hanya kirim BUY baru jika sebelumnya statusnya HOLD/SELL atau ada perubahan status).
        """
        if sig.signal == "HOLD":
            return True, "Sinyal HOLD tidak memerlukan notifikasi."

        last_sig = self.storage.get_last_signal(sig.ticker, sig.strategy_name)
        if last_sig is None:
            return False, "Sinyal pertama kali tercatat."

        # Cek kesamaan candle time dan tipe sinyal
        last_type = last_sig.get("signal_type", "")
        last_time = last_sig.get("candle_time", "")
        is_notified = bool(last_sig.get("is_notified", 0))

        if last_type == sig.signal and last_time == sig.candle_time and is_notified:
            return True, f"Sinyal {sig.signal} sudah dinotifikasikan pada candle {sig.candle_time}."

        # Jika tipe sinyal sama persis dan masih aktif
        if last_type == sig.signal and is_notified:
            return True, f"Posisi {sig.signal} masih berlangsung sejak {last_time}."

        return False, "Sinyal baru / perubahan status sinyal."


def start_scheduler() -> None:
    """Menjalankan background scheduler secara berkala sesuai konfigurasi."""
    cfg = load_config()
    sched_cfg = cfg.get("scheduler", {})
    interval_mins = int(sched_cfg.get("interval_minutes", 15))

    logger.info(f"Inisialisasi APScheduler dengan interval {interval_mins} menit...")
    runner = PipelineRunner()

    scheduler = BlockingScheduler()
    # Jadwalkan eksekusi berkala
    scheduler.add_job(
        runner.run_pipeline,
        trigger=IntervalTrigger(minutes=interval_mins),
        id="idx_stock_analysis_job",
        name="Analisis Saham Berkala IDX",
        replace_existing=True,
    )

    # Jalankan 1 kali secara instan saat bot pertama dinyalakan
    logger.info("Menjalankan pipeline inisial pertama kali saat startup...")
    runner.run_pipeline(force_run=True)

    print("\n" + "=" * 75)
    print(f"🚀 SCHEDULER BOT AKTIF! Memantau tiap {interval_mins} menit.")
    print("Tekan Ctrl+C untuk menghentikan bot.")
    print("=" * 75 + "\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler dimatikan oleh pengguna.")
        scheduler.shutdown()
        print("\nScheduler berhasil dimatikan dengan aman.")


if __name__ == "__main__":
    start_scheduler()
