import os
import sys
import time
from datetime import datetime, time as dtime
from typing import Optional, Tuple, Dict, Any, List
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
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


def is_gold_market_open(
    dt: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    Memeriksa apakah pasar Emas global (COMEX / CME) sedang buka.
    Jadwal (WIB - Asia/Jakarta):
    - Buka: Senin 05:00 WIB s/d Sabtu 04:00 WIB (23 jam sehari).
    - Jeda harian: 04:00 - 05:00 WIB (Selasa - Jumat).
    - Tutup: Sabtu 04:00 WIB s/d Senin 05:00 WIB.
    """
    cfg = config or load_config()
    sched_cfg = cfg.get("scheduler", {})
    if not sched_cfg.get("check_market_hours", True):
        return True, "Filter jam komoditas dinonaktifkan."

    tz_name = sched_cfg.get("timezone", "Asia/Jakarta")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Jakarta")

    now = dt or datetime.now(tz)
    weekday = now.weekday()  # 0: Senin, ..., 5: Sabtu, 6: Minggu
    curr_time = now.time()

    # Sabtu setelah 04:00 WIB s/d Minggu
    if weekday == 5 and curr_time >= dtime(4, 0):
        return False, "Pasar Emas Libur Akhir Pekan (Sabtu > 04:00 WIB)."
    if weekday == 6:
        return False, "Pasar Emas Libur Akhir Pekan (Minggu)."
    # Senin sebelum 05:00 WIB
    if weekday == 0 and curr_time < dtime(5, 0):
        return False, "Pasar Emas Belum Buka (Mulai Senin 05:00 WIB)."

    # Jeda harian CME/COMEX 04:00 - 05:00 WIB
    if dtime(4, 0) <= curr_time < dtime(5, 0):
        return False, "Pasar Emas Jeda Harian (04:00 - 05:00 WIB)."

    return True, f"Pasar Emas Buka ({now.strftime('%A')} {curr_time.strftime('%H:%M')} WIB)."


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
        1. Validasi jam bursa IDX & jam pasar Emas global.
        2. Ambil data terbaru untuk seluruh saham & komoditas di watchlist.
        3. Hitung indikator teknikal.
        4. Jalankan rule engine & evaluasi sinyal.
        5. Filter deduplikasi sinyal.
        6. Kirim notifikasi Telegram instan jika ada sinyal baru.
        """
        logger.info("=== Memulai Siklus Pipeline Analisis Saham & Komoditas ===")

        # 1. Cek Jam Pasar (IDX & Emas)
        idx_open, idx_reason = is_idx_market_open(config=self.config)
        gold_open, gold_reason = is_gold_market_open(config=self.config)
        logger.info(f"Status Pasar: IDX={'BUKA' if idx_open else 'TUTUP'} | GOLD={'BUKA' if gold_open else 'TUTUP'}")

        if not idx_open and not gold_open and not force_run:
            logger.info("Melewatkan pipeline karena seluruh pasar sedang tutup.")
            return {"status": "skipped", "reason": f"IDX: {idx_reason} | Gold: {gold_reason}"}

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
            f"Mode Trading: {trading_mode.upper()} (Interval: {interval}, Watchlist: {len(watchlist)})"
        )

        results = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "processed": 0,
            "signals_triggered": 0,
            "signals_notified": 0,
            "details": [],
        }

        # 3. Iterasi setiap saham/komoditas dalam watchlist
        for ticker in watchlist:
            is_gold = any(k in ticker.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])

            # Cek jam operasional pasar per instrumen
            if not force_run:
                if is_gold and not gold_open:
                    logger.debug(f"Melewatkan {ticker}: {gold_reason}")
                    continue
                elif not is_gold and not idx_open:
                    logger.debug(f"Melewatkan {ticker}: {idx_reason}")
                    continue

            try:
                results["processed"] += 1
                logger.info(f"Memproses {ticker}...")

                # Konfigurasi data per instrumen
                if is_gold:
                    item_interval = "15m"
                    item_period = "5d"
                else:
                    item_interval = interval
                    item_period = period

                # Ambil data candle terbaru
                df = self.fetcher.fetch_and_store(ticker, interval=item_interval, period=item_period)
                if df.empty or len(df) < 15:
                    logger.warning(f"Data tidak mencukupi untuk {ticker}, dilewati.")
                    continue

                # Evaluasi penyelesaian sinyal terbuka (TP / SL hit check & laporan evaluasi)
                resolved_signals = self.storage.resolve_open_signals(ticker, df)
                for res_sig in resolved_signals:
                    logger.info(
                        f"🎯 Laporan TP/SL: {res_sig['ticker']} {res_sig['signal_type']} "
                        f"-> {res_sig['outcome']} ({res_sig['pnl_pct']:+.2f}%)"
                    )
                    try:
                        self.notifier.send_tp_sl_report(res_sig)
                    except Exception as e:
                        logger.error(f"Gagal mengirim laporan TP/SL {res_sig['ticker']} ke Telegram: {e}")

                # Hitung Indikator
                df_ind = TechnicalIndicators.add_all_indicators(df)

                # Evaluasi Sinyal (candle terakhir)
                sig_result = self.signal_engine.evaluate_bar(df_ind, ticker=ticker, bar_idx=-1)

                is_duplicate, dup_reason = self._check_duplicate(sig_result)
                is_fresh, fresh_reason = self._is_candle_fresh(sig_result, item_interval)
                should_notify = (sig_result.signal in ["BUY", "SELL"]) and (not is_duplicate) and is_fresh

                if sig_result.signal in ["BUY", "SELL"]:
                    results["signals_triggered"] += 1

                # Simpan ke Database lengkap dengan target TP & SL
                self.storage.save_signal(
                    ticker=sig_result.ticker,
                    strategy_name=sig_result.strategy_name,
                    signal_type=sig_result.signal,
                    price=sig_result.price,
                    reasons=sig_result.reasons,
                    candle_time=sig_result.candle_time,
                    is_notified=should_notify,
                    take_profit_price=sig_result.take_profit_price,
                    stop_loss_price=sig_result.stop_loss_price,
                )

                # Kirim Notifikasi jika sinyal valid, bukan duplikat, dan candle segar
                if should_notify:
                    logger.info(f"🚨 Sinyal Baru Terdeteksi: {sig_result.signal} {sig_result.ticker} @ {sig_result.price}")
                    chart_path = None
                    try:
                        from notify.chart_generator import ChartGenerator
                        chart_path = ChartGenerator.generate_chart(
                            df=df_ind,
                            ticker_symbol=sig_result.ticker,
                            interval=item_interval,
                            signal_type=sig_result.signal,
                            entry_price=sig_result.price,
                            tp_price=sig_result.take_profit_price,
                            sl_price=sig_result.stop_loss_price,
                            setup_grade=sig_result.setup_grade,
                            pdf_confluence_score=sig_result.pdf_confluence_score,
                        )
                    except Exception as e:
                        logger.warning(f"Gagal membuat visual chart untuk {sig_result.ticker}: {e}")

                    self.notifier.send_signal(sig_result, photo_path=chart_path)
                    results["signals_notified"] += 1
                elif not is_fresh and (sig_result.signal in ["BUY", "SELL"]):
                    logger.info(f"Sinyal {sig_result.signal} untuk {ticker} tidak dinotifikasikan ({fresh_reason}).")
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

        # Periksa apakah ada berita besar (FOMC, CPI, NFP) dalam 10-15 menit ke depan
        self.check_upcoming_news_job()

        logger.info(
            f"=== Pipeline Selesai: {results['processed']} saham diproses, "
            f"{results['signals_triggered']} sinyal aktif, {results['signals_notified']} notifikasi terkirim ==="
        )
        return results

    def check_upcoming_news_job(self) -> int:
        """
        Memeriksa apakah ada berita besar (FOMC, CPI, NFP) yang akan rilis
        dalam waktu 10-15 menit ke depan. Jika ada dan belum dinotifikasikan:
        1. Lakukan analisis pre-news XAU/USD.
        2. Buat visual grafik pre-news setup.
        3. Kirim notifikasi prioritas tinggi ke Telegram.
        4. Tandai alert_sent = 1 di database.
        """
        try:
            from data.economic_calendar import EconomicCalendar
            from strategy.news_predictor import NewsPredictor

            cal = EconomicCalendar(storage=self.storage)
            upcoming = cal.get_upcoming_high_impact_news(within_minutes=15)
            if not upcoming:
                return 0

            df_gold = self.fetcher.get_data("XAUUSD", interval="15m", period="5d", force_fetch=True)
            live_price = float(df_gold["Close"].iloc[-1]) if not df_gold.empty else None

            notified_count = 0
            for event in upcoming:
                ev_id = event.get("id")
                news_type = event.get("news_type", "OTHER")
                logger.info(f"🚨 Terdeteksi High-Impact News {news_type} rilis sebentar lagi ({event.get('date_wib')} WIB)!")

                analysis = NewsPredictor.analyze_pre_news(
                    news_event=event,
                    live_gold_price=live_price,
                    df_gold=df_gold,
                )

                chart_path = NewsPredictor.generate_pre_news_chart(
                    analysis=analysis,
                    df=df_gold,
                )

                self.notifier.send_news_alert(analysis, photo_path=chart_path)
                if ev_id:
                    self.storage.mark_news_alert_sent(ev_id)
                notified_count += 1

            return notified_count
        except Exception as e:
            logger.error(f"Error pada check_upcoming_news_job: {e}")
            return 0

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

    def _is_candle_fresh(self, sig: SignalResult, interval: str) -> Tuple[bool, str]:
        """
        Memeriksa apakah candle sinyal cukup segar untuk dinotifikasikan secara live.
        Mencegah pengiriman sinyal lama (stale) saat bot baru direstart di luar jam aktif.
        """
        if interval == "1d":
            return True, "Candle harian valid."

        try:
            ts = pd.to_datetime(sig.candle_time)
            tz_wib = ZoneInfo("Asia/Jakarta")
            now_wib = datetime.now(tz_wib)

            if ts.tzinfo is not None:
                ts_wib = ts.tz_convert(tz_wib)
            else:
                ts_wib = ts.tz_localize(tz_wib)

            age_seconds = (now_wib - ts_wib).total_seconds()
            if age_seconds < 0:
                return True, "Candle waktu berjalan."

            # Batas toleransi: 45 menit untuk 15m/30m, 75 menit untuk 1h
            max_age = 75 * 60 if interval == "1h" else 45 * 60
            if age_seconds > max_age:
                age_mins = int(age_seconds // 60)
                return False, f"Candle kedaluwarsa ({age_mins}m lalu > batas {max_age // 60}m)"

            return True, "Candle segar."
        except Exception as e:
            logger.debug(f"Gagal memeriksa kesegaran candle {sig.candle_time}: {e}")
            return True, "Pengecekan kesegaran dilewati."


def start_scheduler() -> None:
    """Menjalankan background scheduler secara berkala sesuai konfigurasi."""
    cfg = load_config()
    sched_cfg = cfg.get("scheduler", {})
    interval_mins = int(sched_cfg.get("interval_minutes", 15))

    logger.info(f"Inisialisasi APScheduler dengan interval {interval_mins} menit...")
    runner = PipelineRunner()

    scheduler = BlockingScheduler()
    # Jadwalkan eksekusi berkala analisa saham & gold
    scheduler.add_job(
        runner.run_pipeline,
        trigger=IntervalTrigger(minutes=interval_mins),
        id="idx_stock_analysis_job",
        name="Analisis Saham Berkala IDX",
        replace_existing=True,
    )

    # Jadwalkan pengecekan berita besar (FOMC, CPI, NFP) tiap 1 menit untuk alert T-10 menit
    scheduler.add_job(
        runner.check_upcoming_news_job,
        trigger=IntervalTrigger(minutes=1),
        id="pre_news_checker_job",
        name="Pengecekan High-Impact News 10 Menit",
        replace_existing=True,
    )

    # Jalankan 1 kali saat startup jika jam pasar buka
    logger.info("Menjalankan pipeline inisial pertama kali saat startup...")
    runner.run_pipeline(force_run=False)

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
