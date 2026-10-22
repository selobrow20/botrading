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
from apscheduler.triggers.cron import CronTrigger

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
        self._reported_early_warnings: set = set()
        self._startup_baseline_candles: dict = {}
        self._last_chart_alert_time: dict = {}
        from trading.auto_repair import AutoRepairGuardian
        self.guardian = AutoRepairGuardian.get_instance(notifier=self.notifier)

    def run_pipeline(
        self,
        force_run: bool = False,
        watchlist: Optional[List[str]] = None,
        is_startup_warmup: bool = False,
    ) -> Dict[str, Any]:
        """
        Menjalankan 1 siklus penuh pipeline:
        1. Validasi jam bursa IDX & jam pasar Emas global.
        2. Ambil data terbaru untuk seluruh saham & komoditas di watchlist.
        3. Hitung indikator teknikal.
        4. Jalankan rule engine & evaluasi sinyal.
        5. Filter deduplikasi sinyal.
        6. Kirim notifikasi Telegram instan jika ada sinyal baru.
        """
        is_fast_gold = (watchlist == ["XAUUSD"] and not force_run)
        if not is_fast_gold:
            logger.info("=== Memulai Siklus Pipeline Analisis Saham & Komoditas ===")
        else:
            logger.debug("=== Memulai Siklus Pemindaian Kilat Gold XAU/USD ===")

        # 0. Cek transaksi deal tertutup MT5 secara instan (laporan TP / SL hit)
        self.check_and_report_mt5_deals()

        # 1. Cek Jam Pasar (IDX & Emas)
        idx_open, idx_reason = is_idx_market_open(config=self.config)
        gold_open, gold_reason = is_gold_market_open(config=self.config)
        if not is_fast_gold:
            logger.info(f"Status Pasar: IDX={'BUKA' if idx_open else 'TUTUP'} | GOLD={'BUKA' if gold_open else 'TUTUP'}")
        else:
            logger.debug(f"Status Pasar: IDX={'BUKA' if idx_open else 'TUTUP'} | GOLD={'BUKA' if gold_open else 'TUTUP'}")

        if not idx_open and not gold_open and not force_run:
            if not is_fast_gold:
                logger.info("Melewatkan pipeline karena seluruh pasar sedang tutup.")
            return {"status": "skipped", "reason": f"IDX: {idx_reason} | Gold: {gold_reason}"}

        # Bersihkan pending order MT5 yang sudah kadaluarsa (> 120 menit / 2 jam)
        if gold_open or force_run:
            try:
                from trading.mt5_bridge import MT5Bridge
                _bridge = MT5Bridge()
                if _bridge.enabled:
                    _bridge.cancel_stale_pending_orders(max_age_minutes=120)
            except Exception as _ex_stale:
                logger.debug(f"Pembersihan pending order kadaluarsa: {_ex_stale}")

        # 2. Baca Konfigurasi Trading & Watchlist
        if watchlist is None:
            watchlist = self.config.get("watchlist", ["BBCA.JK"])
        # Utamakan XAUUSD / Gold di urutan teratas agar eksekusi order MT5 0-delay tanpa menunggu antrean saham IDX
        watchlist = sorted(watchlist, key=lambda t: 0 if any(k in t.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"]) else 1)
        trading_cfg = self.config.get("trading", {})
        trading_mode = trading_cfg.get("mode", "intraday")

        if trading_mode == "intraday":
            interval = trading_cfg.get("intraday", {}).get("interval", "15m")
            period = self.config.get("data", {}).get("intraday_period", "60d")
        else:
            interval = trading_cfg.get("daily", {}).get("interval", "1d")
            period = self.config.get("data", {}).get("default_period", "2y")

        if not is_fast_gold:
            logger.info(
                f"Mode Trading: {trading_mode.upper()} (Interval: {interval}, Watchlist: {len(watchlist)})"
            )
        else:
            logger.debug(
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

                if is_gold:
                    from trading.mt5_bridge import MT5Bridge
                    _br = MT5Bridge()
                    in_cd, cd_msg = _br.is_in_reversal_cooldown()
                    if in_cd:
                        logger.info(f"ℹ️ {cd_msg} (Gold tetap dipindai agar momen Grade A+ langsung dieksekusi).")


            try:
                results["processed"] += 1
                if not is_fast_gold:
                    logger.info(f"Memproses {ticker}...")
                else:
                    logger.debug(f"Memproses {ticker}...")

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
                    # Validasi ketat: Jangan pernah kirim laporan TP/SL jika sinyal entry tidak pernah dinotifikasikan ke user!
                    if not res_sig.get("is_notified", 1):
                        logger.info(f"Melewatkan laporan TP/SL #{res_sig.get('id')} karena sinyal entry tidak dinotifikasikan.")
                        continue

                    logger.info(
                        f"🎯 Laporan TP/SL: {res_sig['ticker']} {res_sig['signal_type']} "
                        f"-> {res_sig['outcome']} ({res_sig['pnl_pct']:+.2f}%)"
                    )
                    # Sesuai preferensi user: Alert real-time TP/SL hanya untuk Gold (XAU/USD).
                    # Saham dicatat di DB & disajikan simpel saat tutup pasar agar tidak bising.
                    # PENTING: Jika MT5 Auto-Trade aktif, laporan hasil transaksi Gold murni dikirim oleh check_and_report_mt5_deals
                    # dari data riil broker MT5 untuk mencegah laporan palsu/phantom loss jika ada posisi yang tidak dieksekusi di MT5.
                    from trading.mt5_bridge import MT5Bridge
                    mt5_bridge_active = False
                    try:
                        b = MT5Bridge()
                        mt5_bridge_active = b.enabled and b.is_available()
                    except Exception:
                        pass

                    if (is_gold or res_sig.get("is_gold")) and mt5_bridge_active:
                        logger.info(
                            f"ℹ️ TP/SL Gold #{res_sig.get('id')} disinkronkan ke DB; "
                            f"broadcast Telegram dikawal oleh MT5 real deal watcher."
                        )
                        continue

                    if res_sig.get("is_stale"):
                        logger.info(
                            f"🚫 [DELAY SUPPRESSED] Laporan TP/SL #{res_sig.get('id')} ({res_sig.get('ticker')}) "
                            f"sudah lewat ({res_sig.get('age_seconds', 0) // 60}m lalu > batas 30 menit). Push Telegram dilewati."
                        )
                        continue

                    if is_gold or res_sig.get("is_gold"):
                        try:
                            self.notifier.send_tp_sl_report(res_sig)
                        except Exception as e:
                            logger.error(f"Gagal mengirim laporan TP/SL {res_sig['ticker']} ke Telegram: {e}")

                # Hitung Indikator
                df_ind = TechnicalIndicators.add_all_indicators(df)

                # Multi-Timeframe Hierarchy untuk Gold (H4 Context, H1 SNR, M30 Trendline, M15 Bias, M5 Sniper)
                df_h1_ind = None
                df_h4_ind = None
                df_m30_ind = None
                df_m5_ind = None
                if is_gold:
                    try:
                        df_h1 = self.fetcher.fetch_ohlcv(ticker, interval="1h", period="7d")
                        if not df_h1.empty and len(df_h1) >= 2:
                            df_h1_ind = TechnicalIndicators.add_all_indicators(df_h1)
                    except Exception as ex_h1:
                        logger.debug(f"Gagal mengambil data H1 {ticker}: {ex_h1}")

                    try:
                        df_m30 = self.fetcher.fetch_ohlcv(ticker, interval="30m", period="5d")
                        if not df_m30.empty and len(df_m30) >= 2:
                            df_m30_ind = TechnicalIndicators.add_all_indicators(df_m30)
                    except Exception as ex_m30:
                        logger.debug(f"Gagal mengambil data M30 {ticker}: {ex_m30}")

                    try:
                        df_h4 = self.fetcher.fetch_ohlcv(ticker, interval="4h", period="14d")
                        if not df_h4.empty and len(df_h4) >= 2:
                            df_h4_ind = TechnicalIndicators.add_all_indicators(df_h4)
                    except Exception as ex_h4:
                        logger.debug(f"Gagal mengambil data H4 {ticker}: {ex_h4}")

                    try:
                        df_m5 = self.fetcher.fetch_ohlcv(ticker, interval="5m", period="2d")
                        if not df_m5.empty and len(df_m5) >= 2:
                            df_m5_ind = TechnicalIndicators.add_all_indicators(df_m5)
                    except Exception as ex_m5:
                        logger.debug(f"Gagal mengambil data M5 {ticker}: {ex_m5}")

                # Evaluasi Sinyal (candle terakhir)
                sig_result = self.signal_engine.evaluate_bar(
                    df_ind,
                    ticker=ticker,
                    bar_idx=-1,
                    df_h1=df_h1_ind,
                    df_h4=df_h4_ind,
                    df_m5=df_m5_ind,
                    df_m30=df_m30_ind,
                )

                # Sesuai arahan pengguna: Saham IDX khusus mode BUY (Long-Only), sinyal SELL ditiadakan
                if not is_gold and sig_result.signal == "SELL":
                    sig_result.signal = "HOLD"
                    sig_result.reasons = ["Sinyal jual saham dilewati (Saham IDX khusus mode BUY/Long-Only)."]

                is_duplicate, dup_reason = self._check_duplicate(sig_result)
                curr_live_p = float(df["Close"].iloc[-1]) if not df.empty else sig_result.price
                is_fresh, fresh_reason = self._is_candle_fresh(sig_result, item_interval, current_live_price=curr_live_p)

                # Deteksi tren makro H1 / H4 secara objektif untuk semua jalur:
                real_macro_trend = ""
                if is_gold and df_h1_ind is not None and not df_h1_ind.empty:
                    c_h1 = float(df_h1_ind["Close"].iloc[-1])
                    e50_h1 = float(df_h1_ind["EMA_50"].iloc[-1]) if "EMA_50" in df_h1_ind.columns else float(df_h1_ind["Close"].ewm(span=50).mean().iloc[-1])
                    e20_h1 = float(df_h1_ind["EMA_20"].iloc[-1]) if "EMA_20" in df_h1_ind.columns else float(df_h1_ind["Close"].ewm(span=20).mean().iloc[-1])
                    if c_h1 < e50_h1 or (c_h1 < e20_h1 and e20_h1 <= e50_h1):
                        real_macro_trend = "BEARISH"
                    elif c_h1 > e50_h1 or (c_h1 > e20_h1 and e20_h1 >= e50_h1):
                        real_macro_trend = "BULLISH"
                elif is_gold and df_h4_ind is not None and not df_h4_ind.empty:
                    c_h4 = float(df_h4_ind["Close"].iloc[-1])
                    e50_h4 = float(df_h4_ind["EMA_50"].iloc[-1]) if "EMA_50" in df_h4_ind.columns else c_h4
                    real_macro_trend = "BEARISH" if c_h4 < e50_h4 else "BULLISH"

                # PROTEKSI STARTUP & WARMUP:
                # 1. Saat bot baru diaktifkan (warmup), catat candle saat ini sebagai baseline dan DILARANG buka posisi/kirim notif
                # 2. Pada siklus berikutnya, candle yang terbentuk sebelum/saat bot aktif ditolak sampai ada candle baru yang selesai (close)
                if is_startup_warmup:
                    self._startup_baseline_candles[ticker] = str(sig_result.candle_time)
                    is_duplicate = True
                    dup_reason = f"Warmup startup ({sig_result.candle_time}). Menunggu candle baru berikutnya."
                    should_notify = False
                elif sig_result.candle_time and sig_result.candle_time <= self._startup_baseline_candles.get(ticker, ""):
                    is_duplicate = True
                    dup_reason = f"Candle {sig_result.candle_time} adalah baseline saat bot baru aktif. Menunggu candle baru berikutnya selesai."
                    should_notify = False
                else:
                    # Filter Anti-Melawan Tren Makro H1:
                    # Jika tren makro BEARISH, dilarang keras BUY / BUY_LIMIT!
                    # Jika tren makro BULLISH, dilarang keras SELL / SELL_LIMIT!
                    if is_gold and real_macro_trend:
                        if ("BEAR" in real_macro_trend and "BUY" in sig_result.signal) or ("BULL" in real_macro_trend and "SELL" in sig_result.signal):
                            logger.info(f"🚫 [VETO TREN MAKRO H1] Sinyal {sig_result.signal} {ticker} dibatalkan karena melawan tren makro ({real_macro_trend})!")
                            sig_result.signal = "HOLD"
                            sig_result.reasons = [f"Dibatalkan: Sinyal {sig_result.signal} melawan tren makro H1 ({real_macro_trend})."]

                    should_notify = (sig_result.signal in ["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT"]) and (not is_duplicate) and is_fresh

                if sig_result.signal in ["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT"]:
                    results["signals_triggered"] += 1

                # Simpan ke Database HANYA jika sinyal segar, bukan duplikat, dan valid dinotifikasikan
                sig_db_id = None
                if should_notify:
                    sig_db_id = self.storage.save_signal(
                        ticker=sig_result.ticker,
                        strategy_name=sig_result.strategy_name,
                        signal_type=sig_result.signal,
                        price=sig_result.price,
                        reasons=sig_result.reasons,
                        candle_time=sig_result.candle_time,
                        is_notified=True,
                        take_profit_price=sig_result.take_profit_price,
                        stop_loss_price=sig_result.stop_loss_price,
                    )


                # Kirim Notifikasi jika sinyal valid, bukan duplikat, dan candle segar
                if should_notify:
                    logger.info(f"🚨 Sinyal Baru Terdeteksi: {sig_result.signal} {sig_result.ticker} @ {sig_result.price}")
                    # 1. INSTANT 0-DELAY MT5 AUTO-TRADE EXECUTION
                    # Eksekusi instan ke broker MT5 terlebih dahulu sebelum render chart untuk menghilangkan delay eksekusi
                    skip_broadcast = False
                    skip_reason = ""
                    order_ticket = None
                    if is_gold:
                        try:
                            from trading.mt5_bridge import MT5Bridge
                            mt5_bridge = MT5Bridge()
                            if mt5_bridge.enabled:
                                mt5_res = mt5_bridge.execute_signal(sig_result)
                                if mt5_res.get("success"):
                                    order_ticket = mt5_res.get("ticket")
                                    logger.info(
                                        f"🤖 MT5 Auto-Trade Sukses: #{order_ticket} "
                                        f"{mt5_res.get('action')} {mt5_res.get('volume')} lot @ {mt5_res.get('price')}"
                                    )
                                    sig_result.reasons.append(
                                        f"🤖 Auto-Trade MT5: Ticket #{order_ticket} ({mt5_res.get('volume')} lot @ ${mt5_res.get('price'):,.2f})"
                                    )
                                    if sig_db_id and order_ticket:
                                        try:
                                            with self.storage._get_connection() as conn:
                                                conn.cursor().execute(
                                                    "UPDATE signals SET mt5_ticket = ? WHERE id = ?",
                                                    (int(order_ticket), sig_db_id),
                                                )
                                                conn.commit()
                                        except Exception as ex_db:
                                            logger.warning(f"Gagal mengaitkan mt5_ticket ke sinyal DB: {ex_db}")
                                    try:
                                        self.notifier.send_mt5_execution_report({
                                            "ticket": order_ticket,
                                            "action": mt5_res.get("action"),
                                            "symbol": mt5_res.get("symbol"),
                                            "volume": mt5_res.get("volume"),
                                            "price": mt5_res.get("price"),
                                            "tp": mt5_res.get("tp"),
                                            "sl": mt5_res.get("sl"),
                                            "score": getattr(sig_result, "pdf_confluence_score", 0.0),
                                            "grade": getattr(sig_result, "setup_grade", "Grade A"),
                                        })
                                    except Exception as ex_rep:
                                        logger.warning(f"Gagal kirim kartu laporan eksekusi MT5: {ex_rep}")
                                else:
                                    err_msg = mt5_res.get('message', 'Ditolak filter MT5')
                                    err_status = mt5_res.get('status', '')
                                    logger.warning(f"MT5 Auto-Trade tidak tereksekusi: {err_msg}")

                                    # JIKA DITOLAK KARENA GUARD MT5 (Anti-Hedging, Anti-Stacking, Max Positions):
                                    # BATALKAN broadcast ke Telegram agar sinyal tidak bentrok dan tidak membingungkan member!
                                    if err_status in ["anti_hedging_skip", "max_positions_reached", "anti_stacking_skip"]:
                                        skip_broadcast = True
                                        skip_reason = err_msg
                                        if sig_db_id:
                                            try:
                                                with self.storage._get_connection() as conn:
                                                    conn.cursor().execute(
                                                        "UPDATE signals SET is_notified = 0 WHERE id = ?",
                                                        (sig_db_id,),
                                                    )
                                                    conn.commit()
                                            except Exception:
                                                pass
                        except Exception as e_mt5:
                            logger.error(f"Error eksekusi MT5 Auto-Trade: {e_mt5}")

                    # 2. GENERATE VISUAL CHART SETELAH EKSEKUSI MT5 (NON-BLOCKING UNTUK EKSEKUSI)
                    chart_path = None
                    is_pending_sig = bool(
                        getattr(sig_result, "is_limit_order", False)
                        or str(getattr(sig_result, "signal", "")).endswith("_LIMIT")
                        or (getattr(sig_result, "ladder_limit_orders", None) and len(sig_result.ladder_limit_orders) > 0)
                    )
                    cfg_mt5_chk = getattr(self, "config", {}).get("mt5", {}) if hasattr(self, "config") else load_config().get("mt5", {})
                    if is_pending_sig and not bool(cfg_mt5_chk.get("notify_pending_limit_signals", True)):
                        skip_broadcast = True
                        skip_reason = "Sinyal pending ditiadakan dari Telegram sesuai instruksi pengguna (menunggu order terjemput)"

                    if not skip_broadcast:
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

                    if skip_broadcast:
                        logger.info(f"🚫 Sinyal {sig_result.signal} {sig_result.ticker} DIBATALKAN broadcast ke Telegram: {skip_reason}")
                    else:
                        self.notifier.send_signal(sig_result, photo_path=chart_path)
                        results["signals_notified"] += 1
                elif not is_fresh and (sig_result.signal in ["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT"]):
                    logger.info(f"Sinyal {sig_result.signal} untuk {ticker} tidak dinotifikasikan ({fresh_reason}).")
                elif is_duplicate:
                    logger.debug(f"Sinyal {sig_result.signal} untuk {ticker} dilewati (Duplikat: {dup_reason}).")

                # JALUR 2: SINYAL MOMEN SANGAT BAGUS GRADE A+ (Auto-Open Langsung Tanpa Perlu Konfirmasi Manual)
                # Sesuai arahan pengguna: "kemarin kan gw ada update buat confirm dlu, itu kalo bisa di hilangkan aja
                # lu lgsung open posisi aja kalo memang moment nya sudah sangat bagus"
                # Jika sinyal awal tertahan (misal HOLD di dasar jurang), tetapi telaah chart membuktikan momen
                # Grade A+ (≥80% winrate / arah Bearish atau Bullish kuat), LANGSUNG eksekusi open posisi ke MT5!
                if not should_notify and is_gold and not is_startup_warmup and not is_duplicate:
                    try:
                        cfg_mt5 = getattr(self, "config", {}).get("mt5", {})
                        c_grade = str(getattr(sig_result, "setup_grade", "") or "")
                        c_score = float(getattr(sig_result, "pdf_confluence_score", 0.0) or 0.0)
                        c_pred = str(getattr(sig_result, "market_direction_prediction", "") or "")

                        if not c_grade and hasattr(sig_result, "meta"):
                            c_grade = str(sig_result.meta.get("setup_grade", ""))
                        if c_score <= 0.0 and hasattr(sig_result, "meta"):
                            c_score = float(sig_result.meta.get("setup_confluence_score", 0.0) or 0.0)
                        if not c_pred and hasattr(sig_result, "meta"):
                            c_pred = str(sig_result.meta.get("prediction_summary", ""))

                        r_text = " ".join(str(r) for r in (sig_result.reasons or []))
                        all_desc = (c_grade + " " + r_text).upper()
                        is_weak_or_no_wick = any(
                            k in all_desc for k in [
                                "GRADE B",
                                "GRADE C",
                                "KETIADAAN REJECTION WICK",
                            ]
                        )
                        is_a_plus = ("Grade A+" in c_grade or (c_score >= 80.0 and "Grade A" in c_grade)) and not is_weak_or_no_wick

                        # DISIPLIN 9 BUKU & HARD RULES VETO:
                        # Haram memaksakan auto-open jika ada veto mutlak, ketiadaan rejection wick, grade rendah, atau kontradiksi H4
                        macro_context_str = real_macro_trend or str(
                            getattr(sig_result, "macro_bias_h4", "")
                            or getattr(sig_result, "h4_context", "")
                            or ""
                        ).upper()
                        if not macro_context_str and df_h1_ind is not None and not df_h1_ind.empty:
                            c_h1 = float(df_h1_ind["Close"].iloc[-1])
                            e50_h1 = float(df_h1_ind["EMA_50"].iloc[-1]) if "EMA_50" in df_h1_ind.columns else float(df_h1_ind["Close"].ewm(span=50).mean().iloc[-1])
                            macro_context_str = "BEARISH" if c_h1 < e50_h1 else "BULLISH"
                        elif not macro_context_str and df_h4_ind is not None and not df_h4_ind.empty:
                            c_h4 = float(df_h4_ind["Close"].iloc[-1])
                            e50_h4 = float(df_h4_ind["EMA_50"].iloc[-1]) if "EMA_50" in df_h4_ind.columns else c_h4
                            macro_context_str = "BEARISH" if c_h4 < e50_h4 else "BULLISH"

                        is_hard_veto = is_weak_or_no_wick or any(
                            k in r_text for k in [
                                "FILTER ANTI-KEJAR LILIN BOB VOLMAN",
                                "Overextended",
                                "overextended",
                                "Veto Lapis 3",
                                "Judas",
                                "Manipulasi",
                            ]
                        )
                        # Filter Anti-Chop & Squeeze Konsolidasi Sempit:
                        enable_chop = bool(cfg_mt5.get("enable_chop_filter", True))
                        if enable_chop and is_gold:
                            adx_val = float(df_ind["ADX"].iloc[-1]) if "ADX" in df_ind.columns else (float(df_ind["adx"].iloc[-1]) if "adx" in df_ind.columns else 25.0)
                            chop_adx_th = float(cfg_mt5.get("chop_adx_threshold", 18.0))
                            chop_rng_th = float(cfg_mt5.get("chop_range_threshold_usd", 3.5))
                            recent_bars = df_ind.tail(10)
                            range_10 = float(recent_bars["High"].max() - recent_bars["Low"].min()) if len(recent_bars) >= 5 else 10.0
                            if adx_val < chop_adx_th and range_10 < chop_rng_th:
                                logger.info(f"⏸️ [ANTI-CHOP GUARD] Auto-open {c_pred} ditahan: Pasar Flat Chop (ADX {adx_val:.1f} < {chop_adx_th}, Range 10-bar ${range_10:.2f} < ${chop_rng_th:.2f}).")
                                continue

                        if is_a_plus and not is_hard_veto and ("Bearish" in c_pred or "Bullish" in c_pred):
                            c_action = "SELL" if "Bearish" in c_pred else "BUY"

                            # Keselarasan Tren Intraday H1/M15 (Anti-Melawan Tren):
                            # Jika tren makro BEARISH, HARAM auto-open BUY. Jika BULLISH, HARAM auto-open SELL.
                            if ("BEAR" in macro_context_str and "BUY" in c_action) or ("BULL" in macro_context_str and "SELL" in c_action):
                                logger.info(f"🚫 [INTRADAY TREND GUARD] Auto-open {c_action} dibatalkan mutlak karena berlawanan arah dengan tren makro ({macro_context_str}). Dilarang melawan arus tren!")
                                continue

                            c_time_key = f"{ticker}_{sig_result.candle_time}_{c_action}"

                            # Deduplikasi agar tidak spam setiap siklus pada candle yang sama
                            if self._last_chart_alert_time.get(ticker) != c_time_key:
                                # Hitung TP & SL dinamis berbasis struktur swing & ATR (RR minimal 1:1.5)
                                entry_p = float(sig_result.price)
                                atr_val = float(df_ind["ATR"].iloc[-1]) if "ATR" in df_ind.columns else 4.0
                                buffer_usd = max(1.50, round(atr_val * 0.4, 2))
                                recent_slice = df_ind.tail(20) if len(df_ind) >= 20 else df_ind

                                if getattr(sig_result, "take_profit_price", 0.0) and getattr(sig_result, "stop_loss_price", 0.0):
                                    c_tp = float(sig_result.take_profit_price)
                                    c_sl = float(sig_result.stop_loss_price)
                                    sl_dist = abs(entry_p - c_sl)
                                    tp_dist = abs(c_tp - entry_p)
                                    min_rr = float(cfg_mt5.get("min_risk_reward_ratio", 1.0))
                                    if sl_dist > 0 and (tp_dist / sl_dist) < (min_rr - 0.05):
                                        tp_dist = round(sl_dist * min_rr, 2)
                                        c_tp = round(entry_p + tp_dist if c_action == "BUY" else entry_p - tp_dist, 2)
                                else:
                                    if c_action == "BUY":
                                        swing_low = float(recent_slice["Low"].min()) if "Low" in recent_slice.columns else (entry_p - 4.0)
                                        c_sl = round(swing_low - buffer_usd, 2)
                                        sl_dist = max(round(entry_p - c_sl, 2), max(4.0, round(atr_val * 1.5, 2)))
                                        c_sl = round(entry_p - sl_dist, 2)
                                        tp_dist = round(sl_dist * 1.5, 2)
                                        c_tp = round(entry_p + tp_dist, 2)
                                    else:
                                        swing_high = float(recent_slice["High"].max()) if "High" in recent_slice.columns else (entry_p + 4.0)
                                        c_sl = round(swing_high + buffer_usd, 2)
                                        sl_dist = max(round(c_sl - entry_p, 2), max(4.0, round(atr_val * 1.5, 2)))
                                        c_sl = round(entry_p + sl_dist, 2)
                                        tp_dist = round(sl_dist * 1.5, 2)
                                        c_tp = round(entry_p - tp_dist, 2)

                                # Periksa Mode Limit Order (Sniper Pending Limit vs Eksekusi Langsung)
                                always_limit = bool(cfg_mt5.get("always_use_limit_orders", False)) and is_gold
                                if always_limit:
                                    min_limit_pips = float(cfg_mt5.get("min_limit_distance_pips", 15.0))
                                    min_dist = max(1.50, min_limit_pips / 10.0)
                                    ema20_lvl = float(df_ind["EMA_20"].iloc[-1]) if "EMA_20" in df_ind.columns else (float(df_ind["ema_20"].iloc[-1]) if "ema_20" in df_ind.columns else entry_p)
                                    if "BUY" in c_action:
                                        c_action = "BUY_LIMIT"
                                        entry_p = min(round(entry_p - min_dist, 2), round(ema20_lvl, 2))
                                        c_sl = round(entry_p - sl_dist, 2)
                                        c_tp = round(entry_p + tp_dist, 2)
                                    else:
                                        c_action = "SELL_LIMIT"
                                        entry_p = max(round(entry_p + min_dist, 2), round(ema20_lvl, 2))
                                        c_sl = round(entry_p + sl_dist, 2)
                                        c_tp = round(entry_p - tp_dist, 2)

                                # Bentuk Sinyal Eksekusi Otomatis (Pending Limit Order Sniper / Eksekusi Langsung)
                                from strategy.signal_engine import SignalResult
                                auto_exec_sig = SignalResult(
                                    ticker=ticker,
                                    strategy_name="Momen_Grade_A_Plus_Direct",
                                    signal=c_action,
                                    price=entry_p,
                                    candle_time=sig_result.candle_time,
                                    reasons=[
                                        f"🟡 [PENDING ORDER SNIPER] {c_action} dipasang di ${entry_p:,.2f} ({c_grade}, Skor {c_score:.0f}%)" if always_limit else f"🚀 Eksekusi Otomatis Momen Sangat Bagus ({c_grade}, Skor {c_score:.0f}%)",
                                        f"🎯 Prediksi Arah: {c_pred}",
                                        f"⚖️ Target TP ${c_tp:.2f} & SL ${c_sl:.2f} (Struktural Dynamic R:R {tp_dist/max(sl_dist, 0.01):.1f}:1)",
                                    ] + (sig_result.reasons or []),
                                    take_profit_price=c_tp,
                                    stop_loss_price=c_sl,
                                    risk_reward_ratio=round(tp_dist / max(sl_dist, 0.01), 2),
                                    pdf_confluence_score=c_score,
                                    setup_grade=c_grade,
                                    market_direction_prediction=c_pred,
                                    is_limit_order=always_limit,
                                    limit_order_type=c_action if always_limit else None,
                                )

                                # 1. INSTANT / SNIPER LIMIT MT5 EXECUTION
                                from trading.mt5_bridge import MT5Bridge
                                mt5_bridge = MT5Bridge()
                                if mt5_bridge.enabled:
                                    mt5_res = mt5_bridge.execute_signal(auto_exec_sig)
                                    if mt5_res.get("success"):
                                        order_ticket = mt5_res.get("ticket")
                                        self._last_chart_alert_time[ticker] = c_time_key
                                        log_tag = "🟡 [PENDING ORDER A+]" if always_limit else "🚀 [AUTO-EXECUTE A+]"
                                        logger.info(
                                            f"{log_tag} MT5 Order Sukses: #{order_ticket} "
                                            f"{c_action} {mt5_res.get('volume')} lot @ ${entry_p:,.2f}"
                                        )

                                        # Buat visual grafik chart konfirmasi setelah eksekusi order MT5 sukses
                                        chart_img = None
                                        try:
                                            from notify.chart_generator import ChartGenerator
                                            chart_img = ChartGenerator.generate_chart(
                                                df=df_ind,
                                                ticker_symbol=sig_result.ticker,
                                                interval=item_interval,
                                                signal_type=c_action,
                                                entry_price=entry_p,
                                                tp_price=c_tp,
                                                sl_price=c_sl,
                                                setup_grade=c_grade,
                                                pdf_confluence_score=c_score,
                                            )
                                        except Exception as ex_cg:
                                            logger.warning(f"Gagal generate chart konfirmasi: {ex_cg}")

                                        # Simpan ke Database
                                        sig_db_id = self.storage.save_signal(
                                            ticker=ticker,
                                            strategy_name="Momen_Grade_A_Plus_Direct",
                                            signal_type=c_action,
                                            price=entry_p,
                                            reasons=auto_exec_sig.reasons,
                                            candle_time=auto_exec_sig.candle_time,
                                            is_notified=True,
                                            take_profit_price=c_tp,
                                            stop_loss_price=c_sl,
                                        )
                                        if sig_db_id and order_ticket:
                                            try:
                                                with self.storage._get_connection() as conn:
                                                    conn.cursor().execute(
                                                        "UPDATE signals SET mt5_ticket = ? WHERE id = ?",
                                                        (int(order_ticket), sig_db_id),
                                                    )
                                                    conn.commit()
                                            except Exception:
                                                pass

                                        # Kirim kartu laporan eksekusi MT5 ke Master
                                        try:
                                            self.notifier.send_mt5_execution_report({
                                                "ticket": order_ticket,
                                                "action": c_action,
                                                "symbol": mt5_res.get("symbol", ticker),
                                                "volume": mt5_res.get("volume"),
                                                "price": mt5_res.get("price", entry_p),
                                                "tp": c_tp,
                                                "sl": c_sl,
                                                "score": c_score,
                                                "grade": c_grade,
                                            })
                                        except Exception as ex_rep:
                                            logger.warning(f"Gagal kirim laporan eksekusi MT5: {ex_rep}")

                                        # Kirim sinyal resmi ke Telegram & broadcast otomatis ke Auto-Copier Member
                                        try:
                                            self.notifier.send_signal(auto_exec_sig, photo_path=chart_img)
                                            results["signals_notified"] += 1
                                        except Exception as ex_ns:
                                            logger.warning(f"Gagal kirim notifikasi sinyal A+: {ex_ns}")
                                    else:
                                        err_msg = mt5_res.get("message", "")
                                        logger.info(f"ℹ️ [AUTO-EXECUTE A+ DITAHAN MT5 GUARD] {err_msg}")
                                        self._last_chart_alert_time[ticker] = c_time_key
                                else:
                                    # Mode simulasi / MT5 nonaktif: langsung kirim sinyal ke Telegram
                                    self._last_chart_alert_time[ticker] = c_time_key
                                    self.notifier.send_signal(auto_exec_sig, photo_path=chart_img)
                                    results["signals_notified"] += 1
                    except Exception as ex_chart_alert:
                        logger.error(f"Error memproses eksekusi sinyal chart A+: {ex_chart_alert}")

                # JALUR 3: PENGELOLAAN JARING DUA SISI PENDING LIMIT ORDER (BUY & SELL LIMIT) SETIAP 2 JAM
                if is_gold:
                    try:
                        self.maintain_dual_sided_pending_limits(
                            ticker=ticker,
                            sig_result=sig_result,
                            df_ind=df_ind,
                            df_h1_ind=df_h1_ind,
                            df_h4_ind=df_h4_ind,
                        )
                    except Exception as ex_lim:
                        logger.error(f"Error pada pengelolaan dual-sided pending limits {ticker}: {ex_lim}")

                results["details"].append({
                    "ticker": ticker,
                    "signal": sig_result.signal,
                    "price": sig_result.price,
                    "candle_time": sig_result.candle_time,
                    "notified": should_notify,
                })

            except Exception as e:
                logger.error(f"Error memproses pipeline untuk {ticker}: {e}")
                self.guardian.record_error(f"pipeline_{ticker}", str(e))

        # Periksa apakah ada berita besar (FOMC, CPI, NFP) dalam 10-15 menit ke depan (hanya di scan berkala, fast loop sudah ada job 1m)
        if not is_fast_gold:
            self.check_upcoming_news_job()

        summary_msg = (
            f"=== Pipeline Selesai: {results['processed']} saham diproses, "
            f"{results['signals_triggered']} sinyal aktif, {results['signals_notified']} notifikasi terkirim ==="
        )
        if is_fast_gold and results['signals_triggered'] == 0:
            logger.debug(summary_msg)
        else:
            logger.info(summary_msg)

        self.guardian.record_heartbeat()
        return results

    def run_auto_repair_job(self) -> Dict[str, Any]:
        """
        Pekerjaan latar belakang pemulihan mandiri (Auto-Repair & Watchdog Sentinel).
        Mengecek anomali posisi naked tanpa SL/TP, pending order usang, dan detak jantung freeze.
        """
        try:
            # 1. Periksa watchdog freeze
            is_frozen = self.guardian.audit_heartbeat(max_idle_sec=120)
            if is_frozen:
                self.run_pipeline(force_run=True, watchlist=["XAUUSD"])

            # 2. Jalankan siklus audit posisi & pending order
            return self.guardian.run_full_repair_cycle()
        except Exception as ex:
            logger.debug(f"Pengecekan siklus auto-repair guardian: {ex}")
            return {"status": "ERROR", "message": str(ex)}

    def maintain_dual_sided_pending_limits(
        self,
        ticker: str,
        sig_result: Any,
        df_ind: pd.DataFrame,
        df_h1_ind: Optional[pd.DataFrame] = None,
        df_h4_ind: Optional[pd.DataFrame] = None,
    ) -> None:
        """
        Memelihara siklus hidup jaring dua sisi pending limit orders (BUY LIMIT & SELL LIMIT)
        untuk instrumen Gold (XAUUSD):
        1. Menghapus pending order kadaluarsa (setiap 2 jam / 120 menit).
        2. Memeriksa News Guard (10 menit sebelum berita besar -> batalkan & jeda).
        3. Memeriksa ketersediaan pending order aktif. Jika kosong atau kadaluarsa,
           lakukan analisis ulang kondisi pasar terkini (SMC, 20 EMA, 50 EMA, Likuiditas, Support/Resistance)
           dan pasang jaring baru (BUY LIMIT & SELL LIMIT) secara otomatis!
        """
        cfg_mt5 = getattr(self, "config", {}).get("mt5", {})
        if not bool(cfg_mt5.get("enable_limit_orders", True)):
            return

        # Jeda percobaan deploy limit order (minimal 60 detik antar percobaan)
        now_ts = time.time()
        if not hasattr(self, "_last_limit_attempt_time"):
            self._last_limit_attempt_time = {}
        if (now_ts - self._last_limit_attempt_time.get(ticker, 0.0)) < 60.0:
            return
        self._last_limit_attempt_time[ticker] = now_ts

        # 0. HARD GATEKEEPER MUTLAK SEBELUM MEMPROSES JARING PENDING LIMIT
        # Hanya batalkan jika sinyal aktif memiliki veto keras atau berita besar aktif (News Guard)
        if sig_result is not None and getattr(sig_result, "signal", "") not in ["HOLD", ""]:
            from trading.mt5_bridge import can_place_order
            # Notifier disetel None & silent=True agar pengecekan rutin latar belakang tidak membombardir Telegram
            allowed, gate_reason = can_place_order(
                sig=sig_result,
                order_type="BUY_LIMIT",
                active_pending_orders=None,
                notifier=None,
                min_confluence_score=80.0,
                symbol=ticker,
                silent=True,
            )
            if not allowed:
                logger.info(f"🛑 [SCHEDULER GATEKEEPER VETO] Pemeliharaan jaring limit dibatalkan untuk {ticker}: {gate_reason}")
                return

        # 1. News Guard Check
        if bool(cfg_mt5.get("enable_news_limit_guard", True)):
            nb_mins = int(cfg_mt5.get("news_limit_guard_minutes_before", 10))
            na_mins = int(cfg_mt5.get("news_limit_guard_minutes_after", 15))
            try:
                from data.economic_calendar import EconomicCalendar
                cal = EconomicCalendar(storage=self.storage)
                active_guard_news = cal.get_active_high_impact_news(mins_before=nb_mins, mins_after=na_mins)
                if active_guard_news:
                    logger.info(f"🚫 [NEWS GUARD] Jeda pasang limit order: Berita {active_guard_news[0].get('title')} sedang aktif.")
                    return
            except Exception as ex_cal:
                logger.debug(f"Pengecekan news calendar guard: {ex_cal}")

        from trading.mt5_bridge import MT5Bridge
        b = MT5Bridge()
        if not b.enabled and not b.simulation_mode:
            return

        # 2. Batalkan order kadaluarsa sesuai Dynamic Session Expiry (US: 30m, UK: 45m, Asia: 90m) & Clean Slate 19:00 WIB
        cancelled = b.cancel_stale_pending_orders()
        if cancelled:
            logger.info(f"⏰ [DYNAMIC SESSION REFRESH] {len(cancelled)} Pending order kadaluarsa / lintas sesi ({cancelled}) berhasil dibatalkan. Menyiapkan jaring baru!")

        # 3. Periksa pending order yang masih aktif di MT5
        is_cent = b.is_cent_account()
        target_limit_lot = float(cfg_mt5.get("limit_order_lot_cent", cfg_mt5.get("limit_order_lot", 0.05))) if is_cent else float(cfg_mt5.get("limit_order_lot_usd", 0.01))

        active_pending = b.get_pending_orders(symbol=ticker)
        buy_limits = [o for o in active_pending if "BUY" in str(o.get("type", "")).upper()]
        sell_limits = [o for o in active_pending if "SELL" in str(o.get("type", "")).upper()]

        # ANTI-WATERFALL CRASH GUARD (24 Jam di Semua Sesi):
        # Jika M15 sedang longsor tajam di bawah EMA 20 (Close < EMA 20 dan body candle merah besar),
        # segera batalkan seluruh BUY_LIMIT yang menggantung dan kunci penempatan BUY_LIMIT baru!
        is_waterfall_dump = False
        try:
            last_c = float(df_ind["Close"].iloc[-1])
            last_o = float(df_ind["Open"].iloc[-1])
            last_e20 = float(df_ind["EMA_20"].iloc[-1]) if "EMA_20" in df_ind.columns else last_c
            last_atr = float(df_ind["ATR"].iloc[-1]) if "ATR" in df_ind.columns else 2.5
            if last_c < last_e20 and (last_o - last_c) >= max(1.50, last_atr * 0.8):
                is_waterfall_dump = True
                if buy_limits:
                    for bo in buy_limits:
                        b.cancel_pending_order(bo["ticket"])
                        logger.warning(f"🚨 [ANTI-WATERFALL GUARD] Membatalkan BUY LIMIT #{bo['ticket']} karena M15 sedang terjun bebas di bawah EMA 20!")
                    buy_limits = []
                    try:
                        self.notifier.send_pending_limit_cancellation_alert("BUY_LIMIT", reason="Anti-Waterfall Guard (M15 terjun bebas di bawah EMA 20)")
                    except Exception:
                        pass
        except Exception:
            pass

        # CEGAH SPAMMING ORDER BERULANG & DOUBLE EXPOSURE (PDF Section 20 - Strict 1 Layer):
        # 1. Periksa posisi MARKET aktif di MT5 untuk mencegah staking / penumpukan lot di titik yang sama
        open_positions = b.get_open_positions(symbol=ticker)
        active_buys = [p for p in open_positions if "BUY" in str(p.get("type", "")).upper()]
        active_sells = [p for p in open_positions if "SELL" in str(p.get("type", "")).upper()]

        # PROTOKOL PATEN SESI US (19:00 - 24:00 WIB): HARD CAP MAKSIMAL 4 LAYER (ANTI-MARTINGALE / ANTI-10 LAYER)
        # Sesuai arahan mutlak pengguna: "maax 4 layer oke lah zona us"
        now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))
        is_us_time = (19 <= now_wib.hour <= 23)
        us_max_cap = int(cfg_mt5.get("us_session_max_positions", 4))
        if is_us_time and (len(open_positions) + len(active_pending) >= us_max_cap):
            logger.info(
                f"🛑 [US SESSION {us_max_cap}-LAYER CAP] Sesi US dibatasi MAKSIMAL {us_max_cap} ORDER aktif/pending "
                f"({len(open_positions)} posisi + {len(active_pending)} pending di MT5). "
                f"Menolak penambahan layer baru demi mencegah MC saat market US anjlok!"
            )
            return

        # Jika sudah ada posisi MARKET aktif atau pending order aktif, DILARANG pasang order baru searah
        # ANTI-HEDGING: Jika ada posisi market berlawanan yang sedang aktif, DILARANG pasang limit order yang memicu tabrakan
        needs_buy = (not is_waterfall_dump) and (len(buy_limits) == 0 and len(active_buys) == 0 and len(active_sells) == 0)
        needs_sell = (len(sell_limits) == 0 and len(active_sells) == 0 and len(active_buys) == 0)

        curr_p = float(sig_result.price) if sig_result and getattr(sig_result, "price", 0.0) else float(df_ind["Close"].iloc[-1])

        # HARD RULE 1: Manajemen Arah Limit Orders (Single-Sided Sniper Momen Bagus)
        # Sesuai instruksi mutlak pengguna: "lu kasih sell limit sama buy limmit pas ada moment bagus aja bor di salah satu"
        sig_action = str(getattr(sig_result, "signal", "") or "").upper()
        sig_score = float(getattr(sig_result, "pdf_confluence_score", 0.0) or getattr(sig_result, "confluence_score", 0.0) or 0.0)
        sig_grade = str(getattr(sig_result, "setup_grade", "") or "").upper()
        is_good_moment = ("A" in sig_grade or sig_score >= 80.0) and sig_action in ["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT"]

        enable_dual = bool(cfg_mt5.get("enable_dual_sided_limits", False))
        if enable_dual:
            # Mode Jaring Dua Sisi (Khusus Pengujian Bracket Dua Sisi)
            needs_buy = (not is_waterfall_dump) and (len(buy_limits) == 0 and len(active_buys) == 0 and len(active_sells) == 0)
            needs_sell = (len(sell_limits) == 0 and len(active_sells) == 0 and len(active_buys) == 0)
        elif not is_good_moment:
            # Tidak ada momen bagus terkonfirmasi (Status HOLD / Netral) -> DILARANG pasang order baru!
            logger.debug(f"[LIMIT SNIPER] Menunggu momen bagus (Skor {sig_score:.0f}%, Grade {sig_grade}, Aksi: {sig_action}). Tidak ada order dipasang.")
            return
        elif "BUY" in sig_action:
            if is_waterfall_dump:
                logger.warning("🚨 [ANTI-WATERFALL GUARD] Menahan pemasangan BUY LIMIT baru karena M15 sedang crash tajam di bawah EMA 20!")
                return
            # Sinyal Momen Bagus BUY -> Hanya pasang BUY LIMIT di salah satu sisi (Retest Diskon Support / EMA 20)
            if sell_limits:
                for so in sell_limits:
                    b.cancel_pending_order(so["ticket"])
                    logger.info(f"🛑 [MOMEN SYNC] Membatalkan SELL LIMIT #{so['ticket']} karena momen terkonfirmasi BUY.")
                sell_limits = []
                try:
                    self.notifier.send_pending_limit_cancellation_alert("SELL_LIMIT", reason="Momen terkonfirmasi BUY")
                except Exception:
                    pass
            if is_us_time:
                needs_buy = ((len(active_buys) + len(buy_limits)) < us_max_cap) and len(active_sells) == 0
            else:
                needs_buy = (len(buy_limits) == 0 and len(active_buys) == 0 and len(active_sells) == 0)
            needs_sell = False
        elif "SELL" in sig_action:
            # Sinyal Momen Bagus SELL -> Hanya pasang SELL LIMIT di salah satu sisi (Retest Premium Resisten / EMA 20)
            if buy_limits:
                for bo in buy_limits:
                    b.cancel_pending_order(bo["ticket"])
                    logger.info(f"🛑 [MOMEN SYNC] Membatalkan BUY LIMIT #{bo['ticket']} karena momen terkonfirmasi SELL.")
                buy_limits = []
                try:
                    self.notifier.send_pending_limit_cancellation_alert("BUY_LIMIT", reason="Momen terkonfirmasi SELL")
                except Exception:
                    pass
            needs_buy = False
            if is_us_time:
                needs_sell = ((len(active_sells) + len(sell_limits)) < us_max_cap) and len(active_buys) == 0
            else:
                needs_sell = (len(sell_limits) == 0 and len(active_sells) == 0 and len(active_buys) == 0)
        else:
            return

        # 4. Analisis pasar terkini untuk mendapatkan level baru
        ladder_orders = getattr(sig_result, "ladder_limit_orders", [])
        if not ladder_orders:
            snapshot = getattr(sig_result, "indicators_snapshot", None)
            if not snapshot:
                row = df_ind.iloc[-1] if not df_ind.empty else {}
                snapshot = {
                    "atr": float(row.get("atr", 3.0) or 3.0),
                    "ema_20": float(row.get("EMA_20", row.get("ema_20", curr_p)) or curr_p),
                    "ema_50": float(row.get("EMA_50", row.get("ema_50", curr_p)) or curr_p),
                }
            trade_type = getattr(sig_result, "trade_type", "SHORT") if sig_result else "SHORT"
            ladder_orders = self.signal_engine.generate_dual_sided_limit_orders(
                df=df_ind,
                ticker=ticker,
                curr_price=curr_p,
                snapshot=snapshot,
                trade_type=trade_type,
                df_h1=df_h1_ind,
                df_h4=df_h4_ind,
                is_cent=is_cent,
            )

        if not ladder_orders:
            return

        # Filter order yang benar-benar dibutuhkan (Maksimal 1 order per arah yang belum antre)
        orders_to_deploy = []
        if needs_buy:
            for o in [ord for ord in ladder_orders if "BUY" in ord.get("type", "")][:1]:
                o["lot"] = target_limit_lot
                orders_to_deploy.append(o)
        if needs_sell:
            for o in [ord for ord in ladder_orders if "SELL" in ord.get("type", "")][:1]:
                o["lot"] = target_limit_lot
                orders_to_deploy.append(o)

        if not orders_to_deploy:
            return

        acc_type_lbl = "Cent (USC)" if is_cent else "Standard (USD)"
        logger.info(f"🔄 [2-HOUR REFRESH] Memasang pending limit order baru ({len(orders_to_deploy)} order @ {target_limit_lot} lot | {acc_type_lbl}) untuk {ticker}...")
        deploy_res = b.deploy_dual_sided_limit_bracket(symbol=ticker, orders=orders_to_deploy, sig=sig_result)
        if deploy_res.get("success"):
            placed_orders = deploy_res.get("placed_orders", [])
            logger.info(f"✅ [2-HOUR REFRESH] {len(placed_orders)} Pending limit order ({target_limit_lot} lot) berhasil terpasang di MT5!")
            for po in placed_orders:
                try:
                    self.notifier.send_mt5_execution_report({
                        "ticket": po.get("ticket"),
                        "action": po.get("action", po.get("type")),
                        "symbol": po.get("symbol", ticker),
                        "volume": po.get("volume", target_limit_lot),
                        "price": po.get("price"),
                        "tp": po.get("tp"),
                        "sl": po.get("sl"),
                        "score": getattr(sig_result, "pdf_confluence_score", 90.0) if sig_result else 90.0,
                        "grade": getattr(sig_result, "setup_grade", "Grade A+") if sig_result else "Grade A+",
                    }, admin_only=False)
                except Exception as ex_tg:
                    logger.debug(f"Gagal kirim kartu laporan limit order ke Telegram: {ex_tg}")

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

            # Ambil data candle live gold terbaru
            df_gold = self.fetcher.get_data("XAUUSD", interval="15m", period="5d", force_fetch=True)
            live_price = float(df_gold["Close"].iloc[-1]) if not df_gold.empty else None

            # Evaluasi berkala TP/SL posisi Gold yang sedang OPEN tiap 1 menit
            # PENTING: Jika MT5 Auto-Trade aktif, laporan hasil transaksi Gold murni dikirim oleh check_and_report_mt5_deals
            # dari data riil broker MT5 untuk mencegah laporan palsu/phantom loss jika ada posisi yang tidak dieksekusi di MT5.
            from trading.mt5_bridge import MT5Bridge
            mt5_active = False
            try:
                b = MT5Bridge()
                mt5_active = b.enabled and b.is_available()
            except Exception:
                pass

            if not df_gold.empty:
                resolved_gold = self.storage.resolve_open_signals("XAUUSD", df_gold)
                for res_sig in resolved_gold:
                    # Validasi ketat: Hanya kirim laporan TP/SL jika sinyal entry pernah dinotifikasikan ke user
                    if not res_sig.get("is_notified", 1):
                        continue

                    if mt5_active:
                        # Jika MT5 aktif, laporan hasil transaksi Gold murni dikawal oleh check_and_report_mt5_deals
                        continue

                    if res_sig.get("is_stale"):
                        logger.info(
                            f"🚫 [DELAY SUPPRESSED] Laporan TP/SL Gold #{res_sig.get('id')} sudah lewat > 30 menit. Push Telegram dilewati."
                        )
                        continue

                    logger.info(
                        f"🎯 Laporan TP/SL Gold (1m check): {res_sig['ticker']} {res_sig['signal_type']} "
                        f"-> {res_sig['outcome']} ({res_sig['pnl_pct']:+.2f}%)"
                    )
                    try:
                        self.notifier.send_tp_sl_report(res_sig)
                    except Exception as e:
                        logger.error(f"Gagal mengirim laporan TP/SL Gold ke Telegram: {e}")

            # ─── NEWS GUARD: BATALKAN SELURUH LIMIT ORDER 10 MENIT SEBELUM BERITA BESAR ───
            cfg_mt5 = getattr(self, "config", {}).get("mt5", {})
            if bool(cfg_mt5.get("enable_news_limit_guard", True)):
                nb_mins = int(cfg_mt5.get("news_limit_guard_minutes_before", 10))
                na_mins = int(cfg_mt5.get("news_limit_guard_minutes_after", 15))
                active_guard_news = cal.get_active_high_impact_news(mins_before=nb_mins, mins_after=na_mins)
                if active_guard_news and mt5_active:
                    try:
                        b = MT5Bridge()
                        po_list = b.get_pending_orders(symbol="XAUUSD")
                        if po_list:
                            main_ev = active_guard_news[0]
                            cancelled_tickets = b.cancel_all_pending_orders(
                                symbol="XAUUSD",
                                reason=f"10 menit sebelum High-Impact News: {main_ev.get('title')} ({main_ev.get('date_wib')} WIB)"
                            )
                            if cancelled_tickets:
                                logger.info(
                                    f"🚨 [NEWS GUARD] Berhasil membatalkan {len(cancelled_tickets)} pending order "
                                    f"({cancelled_tickets}) 10 menit sebelum {main_ev.get('title')} ({main_ev.get('date_wib')} WIB)!"
                                )
                                self.notifier.send_news_limit_cancellation_alert(main_ev, cancelled_tickets)
                    except Exception as ex_ng:
                        logger.error(f"Error pada eksekusi News Guard pembatalan pending limit order: {ex_ng}")

            # Cek berita besar yang akan rilis ~10 menit ke depan (sesuai arahan user)
            upcoming = cal.get_upcoming_high_impact_news(within_minutes=10)
            if not upcoming:
                return 0

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

                # Simpan rekomendasi trading ke database agar masuk sebagai posisi OPEN & terlacak di Win Rate
                setup = analysis.get("trade_setup", {})
                action = setup.get("action")
                if action in ["BUY", "SELL"]:
                    entry_p = float(setup.get("entry_price", analysis.get("current_price", 0.0)))
                    tp_p = float(setup.get("tp1", 0.0))
                    sl_p = float(setup.get("sl", 0.0))
                    title = analysis.get("news_title", "Pre-News")
                    conf = analysis.get("confidence_pct", 70)
                    now_str = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S")

                    sig_id = self.storage.save_signal(
                        ticker="XAUUSD",
                        strategy_name=f"PreNews_{news_type}",
                        signal_type=action,
                        price=entry_p,
                        reasons=[
                            f"Pre-News {news_type}: {title}",
                            f"Probabilitas: {conf}% High Confidence",
                            f"Bias: {analysis.get('recommendation_bias', 'NEUTRAL')}",
                        ],
                        candle_time=now_str,
                        is_notified=True,
                        take_profit_price=tp_p,
                        stop_loss_price=sl_p,
                    )
                    logger.info(f"💾 Sinyal Pre-News {action} XAUUSD tersimpan ke DB (ID: {sig_id}) sebagai posisi OPEN.")

                    # Eksekusi Auto-Trade MT5 untuk Pre-News (jika MT5 diaktifkan)
                    try:
                        from trading.mt5_bridge import MT5Bridge
                        mt5_bridge = MT5Bridge()
                        if mt5_bridge.enabled:
                            from strategy.signal_engine import SignalResult
                            dummy_sig = SignalResult(
                                ticker="XAUUSD",
                                strategy_name=f"PreNews_{news_type}",
                                signal=action,
                                price=entry_p,
                                candle_time=now_str,
                                take_profit_price=tp_p,
                                stop_loss_price=sl_p,
                                pdf_confluence_score=float(analysis.get("confluence_score", 75.0) or 75.0),
                                setup_grade="Grade A",
                            )
                            mt5_res = mt5_bridge.execute_signal(dummy_sig)
                            if mt5_res.get("success"):
                                order_ticket = mt5_res.get("ticket")
                                logger.info(
                                    f"🤖 MT5 Pre-News Auto-Trade Sukses: #{order_ticket} "
                                    f"{mt5_res.get('action')} {mt5_res.get('volume')} lot @ {mt5_res.get('price')}"
                                )
                                if sig_id and order_ticket:
                                    try:
                                        with self.storage._get_connection() as conn:
                                            conn.cursor().execute(
                                                "UPDATE signals SET mt5_ticket = ? WHERE id = ?",
                                                (int(order_ticket), sig_id),
                                            )
                                            conn.commit()
                                    except Exception as ex_db:
                                        logger.warning(f"Gagal mengaitkan mt5_ticket Pre-News ke sinyal DB: {ex_db}")
                                try:
                                    self.notifier.send_mt5_execution_report({
                                        "ticket": mt5_res.get("ticket"),
                                        "action": mt5_res.get("action"),
                                        "symbol": mt5_res.get("symbol"),
                                        "volume": mt5_res.get("volume"),
                                        "price": mt5_res.get("price"),
                                        "tp": mt5_res.get("tp"),
                                        "sl": mt5_res.get("sl"),
                                        "score": float(analysis.get("confluence_score", 75.0) or 75.0),
                                        "grade": "Grade A",
                                    })
                                except Exception as ex_rep:
                                    logger.warning(f"Gagal kirim kartu laporan eksekusi MT5 pre-news: {ex_rep}")
                    except Exception as e:
                        logger.error(f"Error eksekusi MT5 pre-news: {e}")

            return notified_count
        except Exception as e:
            logger.error(f"Error pada check_upcoming_news_job: {e}")
            return 0

    def run_market_close_job(self) -> None:
        """
        Job otomatis penutupan pasar saham (BEI) tiap pukul 16:05 WIB (Senin - Jumat).
        Mengirim ringkasan pergerakan harga saham utama yang simpel dan ringkas ke Telegram.
        """
        try:
            logger.info("Menjalankan laporan penutupan pasar saham BEI...")
            cfg = load_config()
            watchlist = cfg.get("watchlist", ["BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK"])
            stock_tickers = [t for t in watchlist if not any(k in t.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])]

            summary_data = []
            for ticker in stock_tickers[:8]:
                try:
                    clean_t = ticker.replace(".JK", "")
                    df = self.fetcher.get_data(ticker, interval="1d", period="5d")
                    if not df.empty and len(df) >= 1:
                        curr_c = float(df.iloc[-1]["Close"])
                        prev_c = float(df.iloc[-2]["Close"]) if len(df) >= 2 else curr_c
                        chg_pct = ((curr_c - prev_c) / prev_c) * 100.0 if prev_c > 0 else 0.0
                        summary_data.append({
                            "ticker": clean_t,
                            "close": curr_c,
                            "change_pct": chg_pct,
                        })
                except Exception as e:
                    logger.debug(f"Gagal mengambil ringkasan tutup pasar {ticker}: {e}")

            if summary_data:
                self.notifier.send_market_close_report(summary_data)
                logger.info(f"Laporan penutupan pasar saham berhasil dikirim ({len(summary_data)} emiten).")
        except Exception as e:
            logger.error(f"Error pada run_market_close_job: {e}")

    def send_daily_performance_recap_job(self) -> None:
        """
        Laporan Rekap Performa Harian Otomatis pukul 22:00 WIB:
        Merangkum hasil trading MT5 Gold (USC) dan Crypto Pump Scanner ke Telegram.
        """
        try:
            logger.info("Menjalankan rekap performa harian 22:00 WIB...")
            from trading.mt5_bridge import MT5Bridge
            from crypto.auto_pump import AutoPumpSniper
            from strategy.ai_gatekeeper import AIGatekeeper

            today_str = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%A, %d %B %Y")
            
            # 1. MT5 Gold Stats
            bridge = MT5Bridge.get_instance()
            is_cent = bridge.is_cent_account()
            curr_unit = "USC" if is_cent else "USD"
            deals_today = bridge.get_closed_deals(hours=24)
            wins_mt5 = len([d for d in deals_today if d.get("outcome") == "WIN"])
            losses_mt5 = len([d for d in deals_today if d.get("outcome") == "LOSE"])
            total_mt5 = len(deals_today)
            pnl_mt5 = sum([d.get("profit", 0.0) for d in deals_today])
            wr_mt5 = (wins_mt5 / total_mt5 * 100.0) if total_mt5 > 0 else 0.0
            acc_info = bridge.get_account_info()
            bal_mt5 = acc_info.get("balance", 0.0)
            eq_mt5 = acc_info.get("equity", 0.0)

            # 2. Crypto Pump Stats
            crypto_s = AutoPumpSniper.get_instance()
            crypto_stats = crypto_s.get_daily_pnl_summary()
            total_crypto = crypto_stats.get("total_trades", 0)
            wins_crypto = crypto_stats.get("wins", 0)
            losses_crypto = crypto_stats.get("losses", 0)
            pnl_crypto = crypto_stats.get("net_pnl_usdt", 0.0)
            wr_crypto = crypto_stats.get("win_rate", 0.0)

            # 3. AI Gatekeeper Status
            ai_brain = AIGatekeeper.get_instance()
            ai_status = "🟢 AKTIF (Gemini AI)" if ai_brain.has_brain() else "🟡 Mode Rule-Based"

            sign_mt5 = "+" if pnl_mt5 >= 0 else ""
            sign_crypto = "+" if pnl_crypto >= 0 else ""

            recap_msg = (
                f"🌙 <b>REKAP PERFORMA HARIAN (22:00 WIB)</b>\n"
                f"📅 <i>{today_str}</i>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"🥇 <b>METATRADER 5 (GOLD XAU/USD):</b>\n"
                f"• <b>Tipe Akun:</b> {'Cent (USC)' if is_cent else 'Standard (USD)'}\n"
                f"• <b>Saldo / Equity:</b> <code>{bal_mt5:,.2f} / {eq_mt5:,.2f} {curr_unit}</code>\n"
                f"• <b>Total Eksekusi Hari Ini:</b> <code>{total_mt5} Trade</code>\n"
                f"• <b>Hasil:</b> 🟢 {wins_mt5} WIN | 🔴 {losses_mt5} LOSE\n"
                f"• <b>Win Rate:</b> <code>{wr_mt5:.1f}%</code>\n"
                f"• <b>Net PnL MT5:</b> <code>{sign_mt5}{pnl_mt5:,.2f} {curr_unit}</code>\n\n"
                f"🪙 <b>CRYPTO PUMP (BINANCE SPOT):</b>\n"
                f"• <b>Mode:</b> {crypto_s.mode.upper()}\n"
                f"• <b>Total Selesai:</b> <code>{total_crypto} Trade</code>\n"
                f"• <b>Hasil:</b> 🟢 {wins_crypto} WIN | 🔴 {losses_crypto} LOSE\n"
                f"• <b>Win Rate:</b> <code>{wr_crypto:.1f}%</code>\n"
                f"• <b>Net PnL Crypto:</b> <code>{sign_crypto}${pnl_crypto:.2f} USDT</code>\n\n"
                f"🧠 <b>SISTEM PENGAWALAN:</b>\n"
                f"• <b>Otak AI Decision:</b> {ai_status}\n"
                f"• <b>Akun USC MT5:</b> <i>Bebas batas (Unrestricted Backtest)</i>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⚡ <i>Bot standby 24/7 memantau peluang pasar berikutnya.</i>"
            )

            if self.notifier:
                self.notifier.broadcast_text(recap_msg)
                logger.info("Rekap performa harian berhasil dikirim ke Telegram.")
        except Exception as e:
            logger.error(f"Error saat mengirim rekap performa harian: {e}")

    def check_and_report_mt5_limit_fills(self) -> None:
        """
        Memeriksa pending limit orders (BUY LIMIT & SELL LIMIT) di MT5 yang berhasil terjemput (FILLED)
        secara real-time kilat (0 delay).
        Begitu pending limit order tersentuh harga dan berubah menjadi posisi aktif berjalan di broker,
        langsung kirim kartu notifikasi konfirmasi ke Telegram!
        """
        try:
            from trading.mt5_bridge import MT5Bridge
            bridge = MT5Bridge()
            if not bridge.enabled and not bridge.simulation_mode:
                return

            filled_limits = bridge.get_filled_limit_orders(hours=24)
            if not filled_limits:
                return

            import time
            now_ts = time.time()

            for fl in filled_limits:
                ticket = fl["ticket"]
                pos_id = fl.get("position_id", ticket)

                # 1. Cek apakah limit fill ini sudah pernah dilaporkan
                if self.storage.is_mt5_limit_fill_reported(ticket):
                    continue

                # In-memory deduplication set
                if not hasattr(self, "_reported_limit_fill_tickets"):
                    self._reported_limit_fill_tickets = set()
                if ticket in self._reported_limit_fill_tickets:
                    continue

                true_epoch = fl.get("true_utc_epoch") or fl.get("time") or int(now_ts)
                age_seconds = max(0, int(now_ts) - true_epoch)

                # Saring notifikasi Telegram jika limit fill sudah lewat (> 1800s / 30 menit),
                # KECUALI posisi tersebut masih terbuka LIVE di MT5 saat ini (toleransi s/d 4 jam = 14400s)
                is_live_open = bool(fl.get("is_live_open", False))
                max_fill_age = 14400 if is_live_open else 1800
                if age_seconds > max_fill_age:
                    self.storage.mark_mt5_limit_fill_reported(
                        order_ticket=ticket,
                        position_id=pos_id,
                        symbol=fl.get("symbol", "XAUUSD"),
                        order_type=fl.get("type", "LIMIT"),
                        price=fl.get("price", 0.0),
                        volume=fl.get("volume", 0.0),
                        sl=fl.get("sl", 0.0),
                        tp=fl.get("tp", 0.0),
                    )
                    self._reported_limit_fill_tickets.add(ticket)
                    continue

                # 2. Catat atau sinkronkan ke database signals (agar TP/SL tracking bekerja sempurna saat selesai)
                try:
                    entry_sig = self.storage.find_signal_by_mt5_ticket(ticket, ticker="XAUUSD", signal_type=fl.get("action"))
                    if entry_sig and entry_sig.get("id"):
                        with self.storage._get_connection() as conn:
                            conn.cursor().execute("""
                                UPDATE signals
                                SET price = ?, mt5_ticket = ?, outcome = 'OPEN', is_notified = 1
                                WHERE id = ?
                            """, (fl.get("price", 0.0), pos_id, entry_sig["id"]))
                            conn.commit()
                    else:
                        from zoneinfo import ZoneInfo
                        now_wib_str = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S")
                        self.storage.save_signal(
                            ticker=fl.get("symbol", "XAUUSD"),
                            strategy_name="Pending_Limit_Sniper",
                            signal_type=fl.get("action", "BUY"),
                            price=fl.get("price", 0.0),
                            reasons=[f"Order Limit Terjemput #{ticket}", "Konfluensi Grade A+ 3 Pilar"],
                            candle_time=now_wib_str,
                            is_notified=True,
                            take_profit_price=fl.get("tp", 0.0),
                            stop_loss_price=fl.get("sl", 0.0),
                        )
                except Exception as ex_sig:
                    logger.debug(f"Sinkronisasi sinyal DB untuk limit fill #{ticket}: {ex_sig}")

                # 3. Kirim notifikasi Telegram kilat (0 delay)
                logger.info(
                    f"⚡ [LIMIT TERJEMPUT] Order #{ticket} ({fl.get('type')}) terisi @ ${fl.get('price', 0.0):,.2f}! "
                    f"Mengirim notifikasi ke Telegram (0 delay)..."
                )
                try:
                    self.notifier.send_limit_order_filled_alert(fl)
                except Exception as ex_notif:
                    logger.warning(f"Gagal kirim notifikasi limit fill #{ticket} ke Telegram: {ex_notif}")

                # 4. Tandai sudah dilaporkan di storage & in-memory cache
                self.storage.mark_mt5_limit_fill_reported(
                    order_ticket=ticket,
                    position_id=pos_id,
                    symbol=fl.get("symbol", "XAUUSD"),
                    order_type=fl.get("type", "LIMIT"),
                    price=fl.get("price", 0.0),
                    volume=fl.get("volume", 0.0),
                    sl=fl.get("sl", 0.0),
                    tp=fl.get("tp", 0.0),
                )
                self._reported_limit_fill_tickets.add(ticket)

        except Exception as e:
            logger.debug(f"Pengecekan MT5 limit fills dilewati: {e}")

    def check_and_report_mt5_deals(self) -> None:
        """
        Memeriksa riwayat penutupan transaksi live di MT5 (TP / SL hit)
        dan penjemputan pending limit order (0 delay).
        Jika limit order terisi atau posisi ditutup oleh TP/SL, langsung kirim kartu laporan ke Telegram.
        """
        # Pengecekan penjemputan pending limit order kilat (0 Delay)
        self.check_and_report_mt5_limit_fills()

        try:
            from trading.mt5_bridge import MT5Bridge
            bridge = MT5Bridge()
            if not bridge.enabled or not bridge.is_available():
                return

            closed_deals = bridge.get_closed_deals(hours=24)
            if not closed_deals:
                return

            for deal in closed_deals:
                deal_ticket = deal["deal_ticket"]
                pos_id = deal["position_id"]

                # Cek apakah deal ini sudah pernah dilaporkan
                if self.storage.is_mt5_deal_reported(deal_ticket):
                    continue

                outcome = deal["outcome"]  # "WIN" atau "LOSE"
                reason_str = deal["reason"]  # "TP", "SL", "MANUAL"
                exit_price = deal["price"]
                pnl_cash = deal["profit"]
                symbol = deal["symbol"]

                # Hitung umur deal dalam detik untuk menjamin pelaporan benar-benar LIVE real-time
                import time
                true_epoch = deal.get("true_utc_epoch") or deal.get("time") or int(time.time())
                age_seconds = max(0, int(time.time()) - true_epoch)

                # Cari sinyal awal di database berdasarkan mt5_ticket atau sinyal OPEN yang sesuai
                sig_type = deal.get("type", "BUY")
                entry_sig = self.storage.find_signal_by_mt5_ticket(pos_id, ticker="XAUUSD", signal_type=sig_type)
                
                # Gunakan entry_price presisi dari MT5 atau DB
                entry_price = float(deal.get("entry_price") or (entry_sig["price"] if entry_sig and entry_sig.get("price") else exit_price))
                if entry_sig and entry_sig.get("signal_type"):
                    sig_type = str(entry_sig["signal_type"])

                tp_price = float(entry_sig.get("take_profit_price")) if entry_sig and entry_sig.get("take_profit_price") else None
                sl_price = float(entry_sig.get("stop_loss_price")) if entry_sig and entry_sig.get("stop_loss_price") else None

                # Kalibrasi arah posisi mutlak berbasis level TP/SL matematis
                if tp_price and entry_price and tp_price > entry_price:
                    sig_type = "BUY"
                elif sl_price and entry_price and sl_price < entry_price:
                    sig_type = "BUY"
                elif tp_price and entry_price and tp_price < entry_price:
                    sig_type = "SELL"
                elif sl_price and entry_price and sl_price > entry_price:
                    sig_type = "SELL"

                is_buy_type = "BUY" in str(sig_type).upper()
                if entry_price > 0:
                    if is_buy_type:
                        pnl_pct = round(((exit_price - entry_price) / entry_price) * 100.0, 2)
                    else:
                        pnl_pct = round(((entry_price - exit_price) / entry_price) * 100.0, 2)
                else:
                    pnl_pct = 0.0

                # Sinkronkan tanda PnL % dan outcome dengan hasil riil MT5:
                # Jika profit MT5 bernilai minus atau pergerakan harga rugi, MUTLAK LOSE (Stop Loss/Cut Loss)!
                is_math_loss = (is_buy_type and exit_price < entry_price) or ((not is_buy_type) and exit_price > entry_price)
                if (pnl_cash is not None and float(pnl_cash) < 0) or outcome == "LOSE" or is_math_loss:
                    outcome = "LOSE"
                    pnl_pct = -abs(pnl_pct)
                    if pnl_cash is not None:
                        pnl_cash = -abs(float(pnl_cash))
                elif (pnl_cash is not None and float(pnl_cash) > 0) or outcome == "WIN":
                    outcome = "WIN"
                    pnl_pct = abs(pnl_pct)
                    if pnl_cash is not None:
                        pnl_cash = abs(float(pnl_cash))

                from zoneinfo import ZoneInfo
                tz_wib = ZoneInfo("Asia/Jakarta")
                exit_time_wib = deal.get("time_wib") or datetime.now(tz_wib).strftime("%Y-%m-%d %H:%M WIB")

                unit_curr = "USC" if bridge.is_cent_account() else "USD"
                if outcome == "WIN":
                    if reason_str == "TRAILING_SL":
                        note = f"🎯 Transaksi MT5 #{pos_id} sukses mengunci keuntungan via Trailing Stop / BEP di ${exit_price:,.2f} ({pnl_cash:+.2f} {unit_curr})!"
                    elif reason_str == "TP":
                        note = f"🎯 Transaksi MT5 #{pos_id} sukses menyentuh Take Profit di ${exit_price:,.2f} ({pnl_cash:+.2f} {unit_curr}). Target keuntungan 9 Buku PDF berhasil dicapai!"
                    else:
                        note = f"🛡️ Transaksi MT5 #{pos_id} ditutup (Take Profit Manual oleh Trader) di ${exit_price:,.2f} ({pnl_cash:+.2f} {unit_curr}) untuk mengamankan keuntungan!"
                elif reason_str == "SL":
                    note = f"🛑 Transaksi MT5 #{pos_id} menyentuh Stop Loss di ${exit_price:,.2f} ({pnl_cash:+.2f} {unit_curr}). Batas toleransi risiko berhasil mengamankan modal trading Anda."
                else:
                    note = f"🛑 Transaksi MT5 #{pos_id} ditutup (Cut Loss Manual oleh Trader) di ${exit_price:,.2f} ({pnl_cash:+.2f} {unit_curr}). Disiplin proteksi modal berhasil mengamankan portofolio."

                rep_dict = {
                    "id": entry_sig.get("id") if entry_sig else deal_ticket,
                    "ticker": "XAUUSD",
                    "strategy_name": "9 Buku PDF Confluence",
                    "signal_type": sig_type,
                    "price": entry_price,
                    "exit_price": exit_price,
                    "take_profit_price": tp_price,
                    "stop_loss_price": sl_price,
                    "pnl_pct": pnl_pct,
                    "pnl_cash": pnl_cash,
                    "currency": unit_curr,
                    "outcome": outcome,
                    "candle_time": entry_sig.get("candle_time", "-") if entry_sig else "-",
                    "exit_time": exit_time_wib,
                    "outcome_note": note,
                    "is_gold": True,
                }

                # 1. Update status sinyal di database (WAJIB agar riwayat /lasthistory & /winrate selalu 100% akurat)
                if entry_sig and entry_sig.get("id"):
                    try:
                        with self.storage._get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                                UPDATE signals
                                SET outcome = ?, exit_price = ?, exit_time = ?, pnl_pct = ?, outcome_note = ?
                                WHERE id = ?
                            """, (outcome, exit_price, exit_time_wib, pnl_pct, note, entry_sig["id"]))
                            conn.commit()
                    except Exception as ex_u:
                        logger.warning(f"Gagal update sinyal #{entry_sig.get('id')} di DB: {ex_u}")

                # 2. Tandai deal MT5 sudah dicatat di database
                self.storage.mark_mt5_deal_reported(deal_ticket, pos_id, outcome, pnl_pct)

                # 2b. Set Directional Cooldown & Evaluasi Pasca-SL (Gemini AI Post-Mortem)
                ai_post_mortem = None
                if reason_str == "SL" and outcome == "LOSE":
                    # PANGGIL OTAK GEMINI UNTUK EVALUASI PASCA-SL INSTAN (POST-MORTEM)
                    try:
                        from strategy.ai_gatekeeper import AIGatekeeper
                        ai_brain = AIGatekeeper.get_instance()
                        if ai_brain.has_brain():
                            # Ambil data snapshot pasar live
                            df_live = self.fetcher.get_data("XAUUSD", interval="15m", period="3d", force_fetch=False)
                            mkt_snap = {}
                            if not df_live.empty:
                                c_p = float(df_live["Close"].iloc[-1])
                                ema50_v = float(df_live["EMA_50"].iloc[-1]) if "EMA_50" in df_live.columns else (float(df_live["ema_50"].iloc[-1]) if "ema_50" in df_live.columns else c_p)
                                rsi_v = float(df_live["RSI"].iloc[-1]) if "RSI" in df_live.columns else (float(df_live["rsi"].iloc[-1]) if "rsi" in df_live.columns else 50.0)
                                mkt_snap = {
                                    "current_price": c_p,
                                    "ema_50": ema50_v,
                                    "rsi": rsi_v,
                                    "macro_h4": str(getattr(entry_sig, "macro_bias_h4", "UNKNOWN")),
                                }

                            trade_info = {
                                "ticket": pos_id,
                                "type": sig_type,
                                "entry_price": entry_price,
                                "exit_price": exit_price,
                                "pnl_cash": f"{pnl_cash} {unit_curr}",
                                "pnl_pct": f"{pnl_pct}%",
                                "candle_time": entry_sig.get("candle_time", "-") if entry_sig else "-",
                            }

                            ai_post_mortem = ai_brain.evaluate_sl_post_mortem(
                                trade_details=trade_info,
                                market_snapshot=mkt_snap
                            )
                            rep_dict["ai_post_mortem"] = ai_post_mortem
                    except Exception as ex_pm:
                        logger.debug(f"Pengecekan Gemini Post-Mortem SL: {ex_pm}")

                    try:
                        cfg_mt5_dc = self.config.get("mt5", {}) if hasattr(self, "config") else load_config().get("mt5", {})
                        dir_cd_mins = int(cfg_mt5_dc.get("directional_cooldown_mins", 35))
                        if ai_post_mortem and ai_post_mortem.get("cooldown_mins"):
                            dir_cd_mins = int(ai_post_mortem["cooldown_mins"])

                        if dir_cd_mins > 0 and sig_type in ("BUY", "SELL"):
                            from datetime import timedelta
                            tz_wib = ZoneInfo("Asia/Jakarta")
                            lock_until = datetime.now(tz_wib) + timedelta(minutes=dir_cd_mins)
                            bridge.directional_sl_cooldown[sig_type] = lock_until
                            logger.info(
                                f"🔒 [DIRECTIONAL COOLDOWN SET] Arah {sig_type} dikunci {dir_cd_mins} menit "
                                f"setelah SL (posisi #{pos_id}) via Gemini AI Evaluation. Lock berlaku sampai {lock_until.strftime('%H:%M')} WIB. "
                                f"Anti-revenge re-entry aktif."
                            )
                    except Exception as dc_err:
                        logger.debug(f"Gagal set directional cooldown: {dc_err}")

                # 3. STRICT REAL-TIME GUARD: Saring notifikasi Telegram jika deal sudah lewat (> 1800s / 30 menit)
                # Menghindari spam kartu sangat basi saat bot baru dinyalakan, namun tidak memotong laporan yang baru saja terjadi
                if age_seconds > 1800:
                    logger.info(
                        f"🚫 [DELAY SUPPRESSED] Deal #{deal_ticket} (Posisi #{pos_id}) sudah lewat "
                        f"({age_seconds}s / {age_seconds // 60}m lalu > batas 30 menit). Database tersinkronisasi ({outcome} {pnl_cash:+.2f} USC), push Telegram dilewati."
                    )
                    continue

                # 4. Kirim notifikasi kartu LIVE ke Telegram (Hanya ke Master Admin, tidak ke member)
                logger.info(f"📢 Mengirim kartu hasil TP/SL MT5 #{pos_id} ({reason_str}) ke Telegram Master...")
                rep_dict["force_send"] = True
                rep_dict["from_mt5"] = True
                try:
                    # NOTIFIKASI DEAL PRIBADI AKUN MASTER: HANYA KE MASTER ADMIN
                    target_ids = [self.notifier.chat_id] if getattr(self.notifier, "chat_id", None) else None
                    if self.notifier.send_tp_sl_report(rep_dict, target_chat_ids=target_ids):
                        if entry_sig and entry_sig.get("id"):
                            self.storage.mark_signal_outcome_notified(entry_sig["id"])
                except Exception as ex_nt:
                    logger.warning(f"Gagal kirim kartu TP/SL MT5 ke Telegram: {ex_nt}")

        except Exception as e:
            logger.warning(f"Error pengecekan MT5 closed deals: {e}")

        # -------------------------------------------------------------
        # 1B. EVALUASI REAL-TIME SINYAL EMAS TERBUKA DI DATABASE (LIVE TICK)
        # -------------------------------------------------------------
        # Menjamin SEMUA sinyal (baik dieksekusi di Master MT5 maupun yang
        # hanya dicopy member / dieksekusi terpisah) diselesaikan secara LIVE (0-delay).
        # Begitu harga tick menyentuh TP atau SL, langsung kirim kartu hasil ke Telegram!
        try:
            if bridge.is_available():
                gold_sym = bridge.gold_symbol or "XAUUSD"
                tick = bridge.mt5.symbol_info_tick(gold_sym)
                if tick and getattr(tick, "bid", 0) > 0 and getattr(tick, "ask", 0) > 0:
                    bid_p = float(tick.bid)
                    ask_p = float(tick.ask)

                    # Ambil tiket posisi aktif di Master MT5 saat ini
                    open_mt5_pos = bridge.mt5.positions_get(symbol=gold_sym) or []
                    open_mt5_tickets = {int(p.ticket) for p in open_mt5_pos}

                    open_signals = []
                    with self.storage._get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT id, ticker, strategy_name, signal_type, price, reasons, candle_time,
                                   take_profit_price, stop_loss_price, outcome, is_notified, mt5_ticket
                            FROM signals
                            WHERE outcome = 'OPEN' AND (ticker LIKE '%XAU%' OR ticker LIKE '%GOLD%' OR ticker LIKE '%GC=F%')
                            ORDER BY id ASC
                        """)
                        open_signals = [dict(r) for r in cursor.fetchall()]

                    from zoneinfo import ZoneInfo
                    tz_wib = ZoneInfo("Asia/Jakarta")
                    now_wib_str = datetime.now(tz_wib).strftime("%Y-%m-%d %H:%M WIB")

                    for osig in open_signals:
                        sig_id = osig["id"]
                        sig_tkt = osig.get("mt5_ticket")

                        # Jika posisi ini aktif terbuka di Master MT5, biarkan MT5 yang menutupnya via deal broker
                        if sig_tkt and int(sig_tkt) in open_mt5_tickets:
                            continue

                        s_type = str(osig["signal_type"]).upper()
                        entry_p = float(osig.get("price") or 0.0)
                        tp_p = float(osig.get("take_profit_price") or 0.0)
                        sl_p = float(osig.get("stop_loss_price") or 0.0)

                        if entry_p <= 0 or (tp_p <= 0 and sl_p <= 0):
                            continue

                        hit_outcome = None
                        hit_exit_price = 0.0
                        hit_reason = None
                        hit_note = ""

                        if "BUY" in s_type:
                            # Order BUY: exit saat bid menyentuh SL (bid <= sl) atau TP (bid >= tp)
                            if sl_p > 0 and bid_p <= sl_p:
                                hit_outcome = "LOSE"
                                hit_exit_price = bid_p
                                hit_reason = "SL"
                                pnl_pct = -abs(round(((entry_p - hit_exit_price) / entry_p) * 100.0, 2))
                                hit_note = f"🛑 Sinyal XAU/USD #{sig_id} menyentuh Stop Loss di ${hit_exit_price:,.2f}. Batas toleransi risiko berhasil mengamankan modal trading Anda."
                            elif tp_p > 0 and bid_p >= tp_p:
                                hit_outcome = "WIN"
                                hit_exit_price = bid_p
                                hit_reason = "TP"
                                pnl_pct = abs(round(((hit_exit_price - entry_p) / entry_p) * 100.0, 2))
                                hit_note = f"🎯 Sinyal XAU/USD #{sig_id} sukses menyentuh Take Profit di ${hit_exit_price:,.2f}. Target keuntungan 9 Buku PDF berhasil dicapai!"
                        elif "SELL" in s_type:
                            # Order SELL: exit saat ask menyentuh SL (ask >= sl) atau TP (ask <= tp)
                            if sl_p > 0 and ask_p >= sl_p:
                                hit_outcome = "LOSE"
                                hit_exit_price = ask_p
                                hit_reason = "SL"
                                pnl_pct = -abs(round(((hit_exit_price - entry_p) / entry_p) * 100.0, 2))
                                hit_note = f"🛑 Sinyal XAU/USD #{sig_id} menyentuh Stop Loss di ${hit_exit_price:,.2f}. Batas toleransi risiko berhasil mengamankan modal trading Anda."
                            elif tp_p > 0 and ask_p <= tp_p:
                                hit_outcome = "WIN"
                                hit_exit_price = ask_p
                                hit_reason = "TP"
                                pnl_pct = abs(round(((entry_p - hit_exit_price) / entry_p) * 100.0, 2))
                                hit_note = f"🎯 Sinyal XAU/USD #{sig_id} sukses menyentuh Take Profit di ${hit_exit_price:,.2f}. Target keuntungan 9 Buku PDF berhasil dicapai!"

                        if hit_outcome:
                            # 1. Update database seketika
                            with self.storage._get_connection() as conn:
                                c = conn.cursor()
                                c.execute("""
                                    UPDATE signals
                                    SET outcome = ?, exit_price = ?, exit_time = ?, pnl_pct = ?, outcome_note = ?
                                    WHERE id = ?
                                """, (hit_outcome, hit_exit_price, now_wib_str, pnl_pct, hit_note, sig_id))
                                conn.commit()

                            logger.info(
                                f"⚡ [LIVE TICK RESOLVED] Sinyal #{sig_id} {s_type} terselesaikan LIVE: "
                                f"{hit_outcome} @ ${hit_exit_price:,.2f} ({pnl_pct:+.2f}%) - {hit_reason}"
                            )

                            # 2. Set Directional Cooldown jika SL
                            if hit_reason == "SL" and hit_outcome == "LOSE":
                                try:
                                    cfg_mt5_dc = self.config.get("mt5", {}) if hasattr(self, "config") else load_config().get("mt5", {})
                                    dir_cd_mins = int(cfg_mt5_dc.get("directional_cooldown_mins", 35))
                                    if dir_cd_mins > 0 and s_type in ("BUY", "SELL"):
                                        from datetime import timedelta
                                        lock_until = datetime.now(tz_wib) + timedelta(minutes=dir_cd_mins)
                                        bridge.directional_sl_cooldown[s_type] = lock_until
                                        logger.info(
                                            f"🔒 [DIRECTIONAL COOLDOWN SET] Arah {s_type} dikunci {dir_cd_mins} menit "
                                            f"setelah SL sinyal #{sig_id}. Berlaku sampai {lock_until.strftime('%H:%M')} WIB."
                                        )
                                except Exception as dc_err:
                                    logger.debug(f"Gagal set directional cooldown live tick: {dc_err}")

                            # 3. Broadcast kartu laporan hasil LIVE ke Telegram (hanya jika sinyal pernah dinotifikasikan)
                            if osig.get("is_notified", 1):
                                rep_dict = {
                                    "id": sig_id,
                                    "ticker": "XAUUSD",
                                    "strategy_name": osig.get("strategy_name") or "9 Buku PDF Confluence",
                                    "signal_type": s_type,
                                    "price": entry_p,
                                    "exit_price": hit_exit_price,
                                    "take_profit_price": tp_p if tp_p > 0 else None,
                                    "stop_loss_price": sl_p if sl_p > 0 else None,
                                    "pnl_pct": pnl_pct,
                                    "outcome": hit_outcome,
                                    "candle_time": osig.get("candle_time", "-"),
                                    "exit_time": now_wib_str,
                                    "outcome_note": hit_note,
                                    "is_gold": True,
                                    "force_send": True,
                                }
                                try:
                                    if self.notifier.send_tp_sl_report(rep_dict):
                                        self.storage.mark_signal_outcome_notified(sig_id)
                                except Exception as ex_nt:
                                    logger.warning(f"Gagal broadcast laporan live tick #{sig_id} ke Telegram: {ex_nt}")
        except Exception as ex_tick_res:
            logger.debug(f"Pengecekan live tick sinyal terbuka dilewati: {ex_tick_res}")

        # Trailing stop & Break-Even Protection (BEP) XAU/USD
        try:
            cfg = load_config()
            cfg_mt5 = cfg.get("mt5", {})
            if cfg_mt5.get("enable_break_even", True) or cfg_mt5.get("use_trailing_stop", False):
                self.check_and_update_trailing_bep()
        except Exception as e:
            logger.debug(f"Pengawalan trailing/BEP MT5 dilewati: {e}")

        # Jalankan pengecekan Reversal Guard untuk mengamankan posisi terbuka XAU/USD
        try:
            self.check_gold_reversal_guard()
        except Exception as e:
            logger.debug(f"Pengecekan Reversal Guard dilewati: {e}")

    def check_and_update_trailing_bep(self) -> None:
        """
        Sistem Pengawalan Modal & Kunci Profit Otomatis (Break-Even Protection & Trailing Stop) XAU/USD.
        - Sinyal Long / TP Jauh (TP >= 85 pips / Open Target): Saat floating profit mencapai +100 pips ($10.00 USD),
          SL otomatis digeser ke Break-Even (BEP) + buffer pengaman 3 pips ($0.30 USD) di atas/bawah entry.
        - Sinyal Short / Scalp (TP 60 pips & SL 60 pips): Berjalan disiplin sesuai TP 60 & SL 60 tanpa intervensi.
        - Trailing stop dinamis hanya aktif jika use_trailing_stop = True.
        """
        try:
            cfg = load_config()
            cfg_mt5 = cfg.get("mt5", {})
            enable_bep = bool(cfg_mt5.get("enable_break_even", True))
            use_trailing = bool(cfg_mt5.get("use_trailing_stop", False))

            if not enable_bep and not use_trailing:
                return

            from trading.mt5_bridge import MT5Bridge
            from strategy.signal_engine import get_trading_session
            bridge = MT5Bridge()
            if not bridge.enabled or not bridge.is_available():
                return

            open_positions = bridge.get_open_positions()
            gold_positions = [
                p for p in open_positions
                if any(k in p.get("symbol", "").upper() for k in ["XAUUSD", "GOLD", "GC=F"])
            ]
            if not gold_positions:
                return

            # Konfigurasi parameter BEP:
            # - Sinyal Cepat: Otomatis BEP saat floating profit +20 pips ($2.00 USD)
            # - Sinyal Long / TP Jauh (PDF Section 11): Otomatis BEP saat floating profit +60 pips ($6.00 USD)
            bep_long_threshold = float(cfg_mt5.get("break_even_long_pips", 60.0)) / 10.0
            bep_quick_threshold = float(cfg_mt5.get("break_even_quick_pips", 20.0)) / 10.0
            bep_offset = float(cfg_mt5.get("break_even_buffer_pips", 2.0)) / 10.0          # 2 pips = $0.20 USD

            # Konfigurasi Trailing Stop adaptif per sesi pasar (hanya jika use_trailing_stop = True)
            session_code, session_name = get_trading_session()
            if session_code == "LONDON":
                trail_threshold = 3.50   # +35 pips ($3.50 USD)
                trail_distance = 2.50    # SL di belakang harga $2.50 USD (25 pips)
            elif session_code == "US":
                trail_threshold = 4.50   # +45 pips ($4.50 USD)
                trail_distance = 3.00    # SL di belakang harga $3.00 USD (30 pips)
            else:  # ASIA / DEFAULT
                trail_threshold = 5.00   # +50 pips ($5.00 USD)
                trail_distance = 3.50    # SL di belakang harga $3.50 USD

            for pos in gold_positions:
                ticket = pos["ticket"]
                pos_type = pos["type"]  # "BUY" atau "SELL"
                price_open = float(pos["price_open"])
                price_curr = float(pos["price_current"])
                sl_curr = float(pos.get("sl", 0.0) or 0.0)
                tp_curr = float(pos.get("tp", 0.0) or 0.0)
                volume = float(pos["volume"])
                symbol = pos.get("symbol", "XAUUSDc")

                if price_open <= 0 or price_curr <= 0:
                    continue

                if pos_type == "BUY":
                    profit_dist = price_curr - price_open
                    tp_dist = (tp_curr - price_open) if tp_curr > 0 else 999.0
                    is_tp_jauh = (tp_dist >= 8.5 or tp_curr == 0.0)

                    # Stage 2: Trailing Stop dinamis (Hanya jika use_trailing_stop = True)
                    if use_trailing and profit_dist >= trail_threshold:
                        target_sl = round(price_curr - trail_distance, 2)
                        if target_sl > sl_curr + 0.30:
                            m_res = bridge.modify_position(ticket, sl=target_sl)
                            if m_res.get("success"):
                                logger.info(
                                    f"📈 [TRAILING STOP NAIK - {session_name}] XAUUSD #{ticket} BUY: SL dinaikkan ke ${target_sl:.2f} "
                                    f"(Floating: +${profit_dist:.2f} USD). Profit terkunci: ~${target_sl - price_open:+.2f} USD."
                                )
                                try:
                                    self.notifier.send_trailing_stop_alert({
                                        "ticket": ticket,
                                        "action": "BUY",
                                        "symbol": symbol,
                                        "volume": volume,
                                        "price_open": price_open,
                                        "price_curr": price_curr,
                                        "new_sl": target_sl,
                                        "profit_dist": profit_dist,
                                        "type": "TRAILING_STOP",
                                    })
                                except Exception as ex_t:
                                    logger.debug(f"Error kirim trailing stop alert: {ex_t}")

                    # Stage 1: Break-Even Protection (BEP Lock) universal
                    # Posisi Long: aktif saat +35 pips. Posisi Cepat: aktif saat +20 pips!
                    req_bep_threshold = bep_long_threshold if is_tp_jauh else bep_quick_threshold
                    if enable_bep and profit_dist >= req_bep_threshold:
                        bep_sl = round(price_open + bep_offset, 2)
                        if sl_curr < bep_sl:
                            m_res = bridge.modify_position(ticket, sl=bep_sl)
                            if m_res.get("success"):
                                mode_tag = "LONG/TP JAUH" if is_tp_jauh else "QUICK SCALP"
                                logger.info(
                                    f"🛡️ [BEP LOCK AKTIF - {mode_tag} - {session_name}] XAUUSD #{ticket} BUY: SL digeser ke ${bep_sl:.2f} "
                                    f"(Floating: +${profit_dist:.2f} USD / +{int(profit_dist*10)} pips). Transaksi kini BEBAS RISIKO (Risk-Free)!"
                                )
                                try:
                                    self.notifier.send_trailing_stop_alert({
                                        "ticket": ticket,
                                        "action": "BUY",
                                        "symbol": symbol,
                                        "volume": volume,
                                        "price_open": price_open,
                                        "price_curr": price_curr,
                                        "new_sl": bep_sl,
                                        "profit_dist": profit_dist,
                                        "type": "BEP_LOCK",
                                    })
                                except Exception as ex_b:
                                    logger.debug(f"Error kirim BEP alert: {ex_b}")

                elif pos_type == "SELL":
                    profit_dist = price_open - price_curr
                    tp_dist = (price_open - tp_curr) if tp_curr > 0 else 999.0
                    is_tp_jauh = (tp_dist >= 8.5 or tp_curr == 0.0)

                    # Stage 2: Trailing Stop dinamis (Hanya jika use_trailing_stop = True)
                    if use_trailing and profit_dist >= trail_threshold:
                        target_sl = round(price_curr + trail_distance, 2)
                        if sl_curr == 0.0 or target_sl < sl_curr - 0.30:
                            m_res = bridge.modify_position(ticket, sl=target_sl)
                            if m_res.get("success"):
                                logger.info(
                                    f"📈 [TRAILING STOP TURUN - {session_name}] XAUUSD #{ticket} SELL: SL diturunkan ke ${target_sl:.2f} "
                                    f"(Floating: +${profit_dist:.2f} USD). Profit terkunci: ~${price_open - target_sl:+.2f} USD."
                                )
                                try:
                                    self.notifier.send_trailing_stop_alert({
                                        "ticket": ticket,
                                        "action": "SELL",
                                        "symbol": symbol,
                                        "volume": volume,
                                        "price_open": price_open,
                                        "price_curr": price_curr,
                                        "new_sl": target_sl,
                                        "profit_dist": profit_dist,
                                        "type": "TRAILING_STOP",
                                    })
                                except Exception as ex_t:
                                    logger.debug(f"Error kirim trailing stop alert: {ex_t}")

                    # Stage 1: Break-Even Protection (BEP Lock) universal
                    req_bep_threshold = bep_long_threshold if is_tp_jauh else bep_quick_threshold
                    if enable_bep and profit_dist >= req_bep_threshold:
                        bep_sl = round(price_open - bep_offset, 2)
                        if sl_curr == 0.0 or sl_curr > bep_sl:
                            m_res = bridge.modify_position(ticket, sl=bep_sl)
                            if m_res.get("success"):
                                mode_tag = "LONG/TP JAUH" if is_tp_jauh else "QUICK SCALP"
                                logger.info(
                                    f"🛡️ [BEP LOCK AKTIF - {mode_tag} - {session_name}] XAUUSD #{ticket} SELL: SL digeser ke ${bep_sl:.2f} "
                                    f"(Floating: +${profit_dist:.2f} USD / +{int(profit_dist*10)} pips). Transaksi kini BEBAS RISIKO (Risk-Free)!"
                                )
                                try:
                                    self.notifier.send_trailing_stop_alert({
                                        "ticket": ticket,
                                        "action": "SELL",
                                        "symbol": symbol,
                                        "volume": volume,
                                        "price_open": price_open,
                                        "price_curr": price_curr,
                                        "new_sl": bep_sl,
                                        "profit_dist": profit_dist,
                                        "type": "BEP_LOCK",
                                    })
                                except Exception as ex_b:
                                    logger.debug(f"Error kirim BEP alert: {ex_b}")

        except Exception as e:
            logger.debug(f"Pengecekan trailing/BEP MT5 dilewati: {e}")

    def check_gold_reversal_guard(self) -> List[Dict[str, Any]]:
        """
        Sistem Deteksi Pembalikan Tren & Ambil Untung Otomatis (Early Take Profit) XAU/USD.
        Memeriksa seluruh posisi terbuka XAU/USD di MetaTrader 5:
        1. Jika terdeteksi tanda-tanda pembalikan tren (9 Buku PDF Reversal),
        2. Segera tutup posisi di MT5 untuk mengamankan keuntungan (atau membatasi risiko),
        3. Kirim kartu alert Ambil Untung Otomatis ke Telegram,
        4. Aktifkan mode jeda (cooldown) agar bot tidak langsung gegabah buka posisi baru.
        """
        try:
            from trading.mt5_bridge import MT5Bridge
            from strategy.reversal_detector import GoldReversalDetector

            bridge = MT5Bridge()
            if not bridge.enabled or not bridge.is_available():
                return []

            open_positions = bridge.get_open_positions()
            gold_positions = [
                p for p in open_positions
                if any(k in p.get("symbol", "").upper() for k in ["XAUUSD", "GOLD", "GC=F"])
            ]
            if not gold_positions:
                return []

            # Ambil data candle 15m live terkini untuk Gold
            df_gold = self.fetcher.get_data("XAUUSD", interval="15m", period="3d", force_fetch=True)
            if df_gold.empty or len(df_gold) < 15:
                return []

            # PENTING (Prinsip Price Action 9 Buku PDF):
            # Bar paling terakhir (iloc[-1]) adalah candle yang sedang berjalan (unclosed bar).
            # Candlestick pattern & structure break (Shooting Star, Engulfing, BOS) HANYA sah di candle yang CLOSED (iloc[:-1]).
            # Menguji unclosed bar menyebabkan false close di detik ke-40 candle baru.
            df_closed = df_gold.iloc[:-1].copy() if len(df_gold) >= 3 else df_gold
            df_ind = TechnicalIndicators.add_all_indicators(df_closed)
            closed_reversals = []

            cfg = getattr(self, "config", None) or load_config()
            cfg_mt5 = cfg.get("mt5", {})
            enable_auto_close = cfg_mt5.get("enable_reversal_auto_close", False)

            import time
            now_epoch = time.time()
            active_tickets = {p["ticket"] for p in gold_positions}
            # Bersihkan cache peringatan dini untuk tiket yang sudah tertutup
            if hasattr(self, "_reported_early_warnings"):
                self._reported_early_warnings = {
                    k for k in self._reported_early_warnings if any(str(t) in k for t in active_tickets)
                }
            else:
                self._reported_early_warnings = set()

            for pos in gold_positions:
                ticket = pos["ticket"]
                pos_type = pos["type"]  # "BUY" atau "SELL"
                price_open = float(pos["price_open"])
                price_curr = float(pos["price_current"])
                profit_usd = float(pos["profit"])
                volume = float(pos["volume"])
                pos_time = float(pos.get("time", 0))

                # Hitung persentase pergerakan & floating pips
                if price_open > 0:
                    if pos_type == "BUY":
                        pnl_pct = round(((price_curr - price_open) / price_open) * 100.0, 2)
                        adverse_pips = round((price_open - price_curr) * 10.0, 1)
                    else:
                        pnl_pct = round(((price_open - price_curr) / price_open) * 100.0, 2)
                        adverse_pips = round((price_curr - price_open) * 10.0, 1)
                else:
                    pnl_pct = 0.0
                    adverse_pips = 0.0

                # 1. Pengecekan Fast Impulsive Plunge / Pump (Deteksi Junam Cepat TF 1m/5m & Judas/Asian Open Dump)
                # Dijalankan PERTAMA kali sebelum grace period agar modal terlindungi dari flash waterfall
                fast_rev = False
                fast_type = ""
                fast_reasons = []
                fast_score = 0.0

                enable_fast_guard = bool(cfg_mt5.get("enable_fast_reversal_guard", True))
                fast_threshold = float(cfg_mt5.get("fast_reversal_pips_threshold", 22.0))
                if enable_fast_guard:
                    try:
                        from strategy.signal_engine import get_trading_session
                        s_code, s_name = get_trading_session()
                        df_m5 = self.fetcher.get_data("XAUUSD", interval="5m", period="1d", force_fetch=False)

                        fast_rev, fast_type, fast_reasons, fast_score = GoldReversalDetector.detect_fast_impulsive_reversal(
                            position_type=pos_type,
                            entry_price=price_open,
                            current_price=price_curr,
                            df_m5=df_m5,
                            threshold_pips=fast_threshold,
                            session_code=s_code,
                        )
                    except Exception as ex_fast:
                        logger.debug(f"Pengecekan fast reversal #{ticket}: {ex_fast}")

                # Jika TIDAK terdeteksi fast plunge dan posisi masih muda (< 15 menit) dengan minus wajar, beri ruang bernapas normal
                pos_age_sec = (now_epoch - pos_time) if pos_time > 0 else 9999
                if not fast_rev and pos_age_sec < 900 and adverse_pips < fast_threshold:
                    logger.debug(f"Posisi #{ticket} baru berjalan {int(pos_age_sec)} detik (< 15 menit). Dalam masa observasi / bernapas ke TP/SL.")
                    continue

                # 2. Peringatan Dini Pembalikan Arah (Early Warning Alert) sebelum posisi ditutup
                try:
                    is_warn, w_type, w_reasons, w_score = GoldReversalDetector.check_early_reversal_warning(
                        df_ind=df_ind,
                        position_type=pos_type,
                        entry_price=price_open,
                        current_price=price_curr,
                    )
                    warn_key = f"{ticket}_{w_type}"
                    if is_warn and warn_key not in self._reported_early_warnings:
                        self._reported_early_warnings.add(warn_key)
                        logger.info(
                            f"⚠️ [EARLY REVERSAL WARNING] Posisi #{ticket} ({pos_type}) ada indikasi awal pembalikan arah: "
                            f"{w_type} (Skor: {w_score}%). Mengirim sinyal peringatan dini ke Telegram..."
                        )
                        self.notifier.send_early_reversal_warning({
                            "ticket": ticket,
                            "action": pos_type,
                            "symbol": pos.get("symbol", "XAUUSD"),
                            "volume": volume,
                            "entry_price": price_open,
                            "current_price": price_curr,
                            "score": w_score,
                            "reasons": w_reasons,
                            "reversal_type": w_type,
                        })
                except Exception as ex_warn:
                    logger.warning(f"Error pengecekan early reversal warning #{ticket}: {ex_warn}")

                # 3. Pengecekan Reversal Terkonfirmasi (100% Confirmation - Candle 15m)
                is_rev, rev_type, rev_reasons, rev_score = GoldReversalDetector.detect_reversal(
                    df_ind=df_ind,
                    position_type=pos_type,
                    entry_price=price_open,
                    current_price=price_curr,
                )

                # Filter Ketat 9 Buku PDF & Preferensi Pengguna:
                should_auto_close = False
                if fast_rev and enable_auto_close:
                    should_auto_close = True
                    rev_score = fast_score
                    rev_type = fast_type
                    rev_reasons = fast_reasons
                    logger.info(
                        f"🚨 [FAST IMPULSIVE REVERSAL TRIGGERED] Posisi #{ticket} ({pos_type}) mengalami pergerakan impulsif berlawanan arah! "
                        f"Floating: {pnl_pct}%. Tipe: {rev_type}. Melakukan Cut Loss Dini & Auto-Flip!"
                    )
                elif is_rev:
                    ema20_val = float(df_ind["ema_20"].iloc[-1]) if ("ema_20" in df_ind.columns and not df_ind.empty) else price_open
                    ema50_val = float(df_ind["ema_50"].iloc[-1]) if ("ema_50" in df_ind.columns and not df_ind.empty) else price_open
                    is_trend_broken = (price_curr < ema20_val or price_curr < ema50_val) if pos_type == "BUY" else (price_curr > ema20_val or price_curr > ema50_val)
                    rev_threshold = float(cfg_mt5.get("reversal_auto_close_min_score", 75.0))

                    # Konsultasikan dengan Otak AI Gemini jika tersedia:
                    gemini_cut_ok = False
                    gemini_cut_reason = ""
                    try:
                        from strategy.ai_gatekeeper import AIGatekeeper
                        ai_brain = AIGatekeeper.get_instance()
                        if ai_brain.has_brain():
                            eval_ai = ai_brain.evaluate_reversal_exit_or_flip(
                                current_positions=[pos],
                                new_signal={"type": "SELL" if pos_type == "BUY" else "BUY", "price": price_curr, "reversal_type": rev_type},
                                indicators={"price": price_curr, "ema_50": ema50_val, "reversal_score": rev_score}
                            )
                            if eval_ai.get("should_cut_loss", False):
                                gemini_cut_ok = True
                                gemini_cut_reason = eval_ai.get("reason", "")
                    except Exception as ex_ai:
                        logger.debug(f"Pemeriksaan Gemini auto close: {ex_ai}")

                    has_smc_reversal = any("SMC" in r or "CHoCH" in r or "BOS" in r for r in rev_reasons)
                    quant_cut_ok = (rev_score >= rev_threshold and len(rev_reasons) >= 2 and is_trend_broken) or \
                                   (has_smc_reversal and rev_score >= 65.0)

                    if enable_auto_close and (gemini_cut_ok or quant_cut_ok):
                        should_auto_close = True
                        close_tag = "🧠 [GEMINI VERIFIED CUT LOSS]" if gemini_cut_ok else ("🏛️ [SMC CHoCH AUTO CUT LOSS]" if has_smc_reversal else "🚨 [REVERSAL AUTO-CLOSE]")
                        logger.info(
                            f"{close_tag} Posisi #{ticket} ({pos_type}) ditutup otomatis (Cut Loss/SL Dini) "
                            f"Alasan: {gemini_cut_reason or f'Konfirmasi pembalikan SMC & 9 Buku PDF {rev_score}% ({len(rev_reasons)} alasan)'}"
                        )
                    else:
                        logger.info(
                            f"ℹ️ [REVERSAL ALERT ONLY] Posisi #{ticket} ({pos_type}) mendeteksi pembalikan (Skor: {rev_score}%). "
                            f"Auto-close {'nonaktif' if not enable_auto_close else f'ditahan (skor {rev_score}% < {rev_threshold}% dan Otak AI belum merekomendasikan cut loss)'}. Posisi tetap berjalan menuju hard TP/SL."
                        )

                if should_auto_close:
                    logger.info(
                        f"🚨 [REVERSAL GUARD FIX 100%] Terdeteksi pembalikan tren pasti untuk XAUUSD #{ticket} ({pos_type})! "
                        f"Skor: {rev_score}%. Konfirmasi: {len(rev_reasons)} indikator. Menutup posisi otomatis di MT5..."
                    )
                    close_res = bridge.close_position(ticket)
                    if close_res.get("success"):

                        # Sesuai arahan pengguna: jangan jeda 45 menit, jika ada momen Grade A+ baru langsung gas masuk lagi!
                        cooldown_mins = 0
                        bridge.clear_reversal_cooldown()

                        # Sesuai arahan pengguna: "kalo udah fix pembalikan 100% sesuai pdf gapapa bor atau 90% lu bisa sl dan masuk posisi sebalik nya"
                        # Langsung eksekusi order balik arah (Flip) seketika ke MT5!
                        flip_action = "SELL" if pos_type == "BUY" else "BUY"
                        # Batalkan seluruh pending limit order yang searah posisi lama agar tidak terjemput lagi
                        try:
                            sym_target = pos.get("symbol", "XAUUSD")
                            bridge.cancel_all_pending_orders(symbol=sym_target)
                            old_side = "BUY_LIMIT" if pos_type == "BUY" else "SELL_LIMIT"
                            self.notifier.send_pending_limit_cancellation_alert(old_side, reason=f"Pembalikan Tren ({rev_type})")
                        except Exception as ex_c:
                            logger.debug(f"Gagal batalkan pending order lama saat reversal: {ex_c}")

                        enable_flip = bool(cfg_mt5.get("enable_reversal_flip", True))
                        if enable_flip:
                            logger.info(
                                f"🔄 [REVERSAL AUTO-FLIP] Posisi #{ticket} ({pos_type}) ditutup cut loss. "
                                f"Mengeksekusi order balik arah {flip_action} seketika ke MT5!"
                            )
                            try:
                                from strategy.signal_engine import SignalResult
                                short_tp_usd = float(cfg_mt5.get("gold_short_tp_pips", 48.0)) / 10.0
                                short_sl_usd = float(cfg_mt5.get("gold_short_sl_pips", 42.0)) / 10.0
                                if short_sl_usd > short_tp_usd:
                                    short_sl_usd = short_tp_usd
                                if flip_action == "SELL":
                                    f_tp = round(price_curr - short_tp_usd, 2)
                                    f_sl = round(price_curr + short_sl_usd, 2)
                                else:
                                    f_tp = round(price_curr + short_tp_usd, 2)
                                    f_sl = round(price_curr - short_sl_usd, 2)

                                sym_target = pos.get("symbol", "XAUUSD")
                                flip_sig = SignalResult(
                                    ticker=sym_target,
                                    strategy_name="Reversal_Auto_Flip",
                                    signal=flip_action,
                                    price=price_curr,
                                    candle_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    reasons=[f"⚡ REVERSAL FLIP 100%: Membalik {pos_type} ke {flip_action} ({rev_type})"],
                                    take_profit_price=f_tp,
                                    stop_loss_price=f_sl,
                                    pdf_confluence_score=90.0,
                                    setup_grade="Grade A+ Reversal Flip",
                                )
                                flip_sig.volume = volume
                                flip_res = bridge.execute_signal(flip_sig)
                                if flip_res.get("success"):
                                    logger.info(f"✅ Order Balik Arah {flip_action} MT5 #{flip_res.get('ticket')} sukses dipasang!")
                                    try:
                                        self.notifier.send_mt5_execution_report({
                                            "ticket": flip_res.get("ticket"),
                                            "action": flip_action,
                                            "symbol": sym_target,
                                            "volume": volume,
                                            "price": price_curr,
                                            "tp": f_tp,
                                            "sl": f_sl,
                                            "score": 90.0,
                                            "grade": "Grade A+ Reversal Flip",
                                        }, admin_only=False)
                                    except Exception:
                                        pass
                                else:
                                    logger.warning(f"Order Balik Arah MT5: {flip_res.get('message')}")
                            except Exception as ex_flip:
                                logger.error(f"Gagal eksekusi order flip MT5: {ex_flip}")

                            import threading
                            threading.Thread(target=self.run_pipeline, kwargs={"force_run": True, "watchlist": ["XAUUSD"]}, daemon=True).start()

                        alert_payload = {
                            "ticket": ticket,
                            "action": pos_type,
                            "symbol": pos.get("symbol", "XAUUSD"),
                            "volume": volume,
                            "entry_price": price_open,
                            "exit_price": price_curr,
                            "profit_usd": profit_usd,
                            "pnl_pct": pnl_pct,
                            "reversal_type": f"{rev_type} (Skor Konfluensi: {rev_score:.0f}%)",
                            "reasons": rev_reasons,
                            "cooldown_mins": cooldown_mins,
                        }
                        try:
                            self.notifier.send_gold_reversal_alert(alert_payload)
                        except Exception as ex_nt:
                            logger.error(f"Gagal mengirim alert reversal XAUUSD ke Telegram: {ex_nt}")

                        # Update sinyal di database
                        try:
                            entry_sig = self.storage.find_signal_by_mt5_ticket(ticket)
                            if entry_sig and entry_sig.get("id"):
                                outcome_val = "WIN" if profit_usd >= 0 else "LOSE"
                                note_val = f"Posisi #{ticket} diamankan lebih awal oleh Reversal Guard ({rev_type}). Realisasi: {profit_usd:+.2f} USD."
                                with self.storage._get_connection() as conn:
                                    conn.cursor().execute("""
                                        UPDATE signals
                                        SET outcome = ?, exit_price = ?, pnl_pct = ?, outcome_note = ?
                                        WHERE id = ?
                                    """, (outcome_val, price_curr, pnl_pct, note_val, entry_sig["id"]))
                                    conn.commit()
                        except Exception as ex_db:
                            logger.debug(f"Gagal update status reversal di database: {ex_db}")

                        closed_reversals.append(alert_payload)

            return closed_reversals
        except Exception as e:
            logger.error(f"Error pada check_gold_reversal_guard: {e}")
            return []

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

        is_gold = any(k in sig.ticker.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])

        # 1. CEK LANGSUNG KE BROKER MT5 (Ground Truth Live Execution):
        # Proteksi Anti-Hedging & Anti-Tabrakan Order real-time di terminal MT5
        try:
            from trading.mt5_bridge import MT5Bridge
            _br = MT5Bridge()
            if _br.enabled and _br.is_available():
                open_pos = _br.get_open_positions()
                is_cent = _br.is_cent_account()
                cfg_mt5 = getattr(self, "config", {}).get("mt5", {})
                max_allowed = int(cfg_mt5.get("max_positions_cent", 3) if is_cent else cfg_mt5.get("max_positions_usd", 1))

                # ANTI-HEDGING GUARD: Cek apakah ada posisi BERLAWANAN arah yang masih aktif di MT5
                # Jika masih ada SELL aktif, tolak sinyal BUY. Jika masih ada BUY aktif, tolak sinyal SELL.
                opposite_pos = [
                    p for p in open_pos
                    if ((is_gold and any(k in p.get("symbol", "").upper() for k in ["XAUUSD", "GOLD"]))
                        or p.get("symbol", "").upper() == sig.ticker.upper())
                    and p.get("type") != sig.signal
                ]
                if opposite_pos:
                    pdf_score = float(getattr(sig, "pdf_confluence_score", 0.0) or 0.0)
                    enable_flip = bool(cfg_mt5.get("enable_reversal_flip", True))
                    min_flip_score = float(cfg_mt5.get("min_reversal_flip_score", 85.0))
                    total_opp_profit = sum(float(p.get("profit", 0.0)) for p in opposite_pos)
                    is_opp_profit = total_opp_profit > 0.0

                    if enable_flip and (is_opp_profit or pdf_score >= min_flip_score):
                        action_label = f"Amankan Cuan TP (+{total_opp_profit:.2f} USC)" if is_opp_profit else f"Cut Loss Dini ({total_opp_profit:.2f} USC)"
                        logger.info(
                            f"🔄 [HYBRID FLIP AUTHORIZED] Sinyal pembalikan {sig.signal} {sig.ticker} "
                            f"(Skor: {pdf_score}%, Aksi Lawan: {action_label}) "
                            f"diizinkan melewati Anti-Hedging Guard untuk pembalikan arah (Tutup posisi lawan & Masuk {sig.signal})!"
                        )
                        # Diizinkan untuk Reversal Flip
                    else:
                        opp_summary = ", ".join(f"#{p['ticket']} ({p['type']} @ {p['price_open']}, PnL: {p.get('profit', 0):+.2f} USC)" for p in opposite_pos)
                        return True, (
                            f"Posisi berlawanan [{opp_summary}] masih aktif di MT5. "
                            f"Skor sinyal {pdf_score}% < batas pembalikan {min_flip_score:.0f}%. Mencegah tabrakan order {sig.signal} (Anti-Hedging Guard)."
                        )

                same_dir_pos = [
                    p for p in open_pos
                    if ((is_gold and any(k in p.get("symbol", "").upper() for k in ["XAUUSD", "GOLD"]))
                        or p.get("symbol", "").upper() == sig.ticker.upper())
                    and p.get("type") == sig.signal
                ]
                if len(same_dir_pos) >= max_allowed:
                    mode_lbl = f"CENT USC (Maks {max_allowed} Posisi)" if is_cent else f"USD Standard (Maks {max_allowed} Posisi)"
                    return True, f"Batas posisi {sig.signal} {sig.ticker} tercapai ({len(same_dir_pos)}/{max_allowed} aktif di MT5). Mode: {mode_lbl}."
        except Exception as ex_chk:
            logger.debug(f"Pengecekan MT5 open positions: {ex_chk}")

        # 2. CEK RIWAYAT DATABASE
        last_sig = self.storage.get_last_signal(sig.ticker, sig.strategy_name)
        if last_sig is None:
            return False, "Sinyal pertama kali tercatat."

        # Cek kesamaan candle time dan tipe sinyal
        last_type = last_sig.get("signal_type", "")
        last_time = last_sig.get("candle_time", "")
        is_notified = bool(last_sig.get("is_notified", 0))
        last_outcome = str(last_sig.get("outcome") or "").strip().upper()

        if last_type == sig.signal and last_time == sig.candle_time and is_notified:
            return True, f"Sinyal {sig.signal} sudah dinotifikasikan pada candle {sig.candle_time}."

        if last_type and is_notified and (last_outcome in ["OPEN", "", "NONE"]):
            if last_type != sig.signal:
                pdf_score = float(getattr(sig, "pdf_confluence_score", 0.0) or 0.0)
                cfg_mt5 = getattr(self, "config", {}).get("mt5", {})
                enable_flip = bool(cfg_mt5.get("enable_reversal_flip", True))
                min_flip_score = float(cfg_mt5.get("min_reversal_flip_score", 90.0))
                if enable_flip and pdf_score >= min_flip_score:
                    pass  # Izinkan Reversal Flip 90%+
                else:
                    return True, (
                        f"Posisi berlawanan #{last_sig.get('id')} ({last_type} @ {last_sig.get('price')}) "
                        f"masih OPEN di database. Skor {pdf_score}% < 90%. Mencegah sinyal bentrok {sig.signal}."
                    )
            elif not is_gold:
                return True, f"Posisi {sig.signal} {sig.ticker} sudah aktif di database (OPEN). Mencegah spam/duplikasi sinyal saham."

        return False, "Sinyal baru / perubahan status sinyal."

    def _is_candle_fresh(
        self,
        sig: SignalResult,
        interval: str,
        current_live_price: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Memeriksa apakah candle sinyal BENAR-BENAR SEGAR (Real-Time) untuk dinotifikasikan ke user & member.
        Menolak keras sinyal telat/stale saat bot restart, saat candle lama, atau saat harga sudah lari jauh.
        """
        is_gold = any(k in sig.ticker.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])

        try:
            ts = pd.to_datetime(sig.candle_time)
            tz_wib = ZoneInfo("Asia/Jakarta")
            now_wib = datetime.now(tz_wib)

            if ts.tzinfo is not None:
                ts_wib = ts.tz_convert(tz_wib)
            else:
                ts_wib = ts.tz_localize(tz_wib)

            # 1. Validasi Tanggal: Sinyal WAJIB berasal dari tanggal hari ini (tidak boleh tanggal kemarin/lampau)
            if ts_wib.date() < now_wib.date():
                return False, f"Candle lampau/telat ({ts_wib.strftime('%Y-%m-%d')} < hari ini {now_wib.strftime('%Y-%m-%d')})"

            # 2. Validasi Jam Bursa untuk Saham IDX
            if not is_gold:
                idx_open, idx_msg = is_idx_market_open(now_wib, config=self.config)
                if not idx_open:
                    return False, f"Bursa IDX sedang tutup ({idx_msg}). Sinyal saham ditahan agar tidak telat."

            # 3. Validasi Usia Candle (Maksimal toleransi ketat)
            age_seconds = (now_wib - ts_wib).total_seconds()
            if age_seconds < 0:
                age_seconds = 0

            if interval == "1d":
                pass
            else:
                # Intraday: Batas toleransi ketat agar member tidak telat entry
                # 15m: Maksimal 16 menit (1 bar + 1 menit batas pengambilan data)
                # 5m: Maksimal 6 menit
                # 30m: Maksimal 31 menit
                # 1h: Maksimal 62 menit
                if interval == "5m":
                    max_age = 6 * 60
                elif interval in ["15m", "15min"]:
                    max_age = 16 * 60
                elif interval in ["30m", "30min"]:
                    max_age = 31 * 60
                elif interval in ["1h", "60m"]:
                    max_age = 62 * 60
                else:
                    max_age = 16 * 60

                if age_seconds > max_age:
                    age_mins = int(age_seconds // 60)
                    return False, f"Candle kedaluwarsa/telat ({age_mins}m lalu > batas {max_age // 60}m)"

            # 4. Validasi Pergeseran Harga (Price Drift / Slip Guard)
            # Khusus MARKET ORDER (BUY / SELL): jika harga running sudah melar > 2.50 USD dari candle close,
            # sinyal dianggap telat/slipping demi melindungi user & member dari entry pucuk/dasar.
            # UNTUK PENDING LIMIT ORDER (BUY_LIMIT / SELL_LIMIT):
            # Harga limit memang dirancang berjarak dari harga live (menjemput retest 20 EMA di level diskon/premium).
            is_limit_order = sig.signal in ["BUY_LIMIT", "SELL_LIMIT"] or getattr(sig, "is_limit_order", False)
            check_price = current_live_price or sig.price
            if is_limit_order and check_price and check_price > 0:
                lim_p = float(getattr(sig, "limit_price", 0.0) or sig.price)
                if sig.signal == "BUY_LIMIT" and check_price <= lim_p:
                    return False, f"Harga live (${check_price:.2f}) sudah menembus di bawah harga limit (${lim_p:.2f}). Pending BUY LIMIT terlewat."
                elif sig.signal == "SELL_LIMIT" and check_price >= lim_p:
                    return False, f"Harga live (${check_price:.2f}) sudah menembus di atas harga limit (${lim_p:.2f}). Pending SELL LIMIT terlewat."
            elif not is_limit_order and check_price and sig.price and check_price > 0 and sig.price > 0:
                diff_pct = abs(check_price - sig.price) / sig.price
                if is_gold:
                    diff_usd = abs(check_price - sig.price)
                    # Di Gold: Jika harga sudah lari > $2.50 USD (25 pips) dari entry, sinyal market telat dibatalkan
                    if diff_usd > 2.50:
                        return False, f"Harga Gold sudah lari terlalu jauh (${diff_usd:.2f} USD > batas $2.50 USD / 25 pips). Sinyal telat dibatalkan."
                else:
                    # Di Saham IDX: Jika harga sudah lari > 1.2% dari entry, sinyal telat dibatalkan
                    if diff_pct > 0.012:
                        return False, f"Harga Saham sudah lari terlalu jauh ({diff_pct*100:.2f}% > batas 1.20%). Sinyal telat dibatalkan."

            return True, "Candle segar real-time."
        except Exception as e:
            logger.debug(f"Gagal memeriksa kesegaran candle {sig.candle_time}: {e}")
            return False, f"Error validasi kesegaran: {e}"


def start_scheduler() -> None:
    """Menjalankan background scheduler secara berkala sesuai konfigurasi."""
    cfg = load_config()
    sched_cfg = cfg.get("scheduler", {})
    interval_mins = int(sched_cfg.get("interval_minutes", 15))

    logger.info(f"Inisialisasi APScheduler dengan interval {interval_mins} menit...")
    runner = PipelineRunner()

    # Redam spam peringatan skipped internal APScheduler agar console tetap bersih
    import logging
    logging.getLogger("apscheduler.executors.default").setLevel(logging.ERROR)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.ERROR)

    scheduler = BlockingScheduler()
    # Jadwalkan eksekusi berkala analisa saham & gold (IDX 15m)
    scheduler.add_job(
        runner.run_pipeline,
        trigger=IntervalTrigger(minutes=interval_mins),
        id="idx_stock_analysis_job",
        name="Analisis Saham Berkala IDX",
        replace_existing=True,
    )

    gold_scan_sec = int(sched_cfg.get("gold_scan_interval_seconds", 5))
    gold_scan_us_sec = int(sched_cfg.get("gold_scan_us_session_seconds", 2))
    enable_adaptive = bool(sched_cfg.get("enable_adaptive_gold_scan", True))
    deal_watcher_sec = int(sched_cfg.get("mt5_deal_watcher_seconds", 1))

    # Jadwalkan pemindaian khusus Gold XAU/USD real-time kilat
    # Mendukung Adaptive US Session Turbo: 1-2 detik saat Sesi US, 5 detik saat Sesi Asia/London
    _last_gold_scan_time = 0.0

    def scan_gold_job():
        nonlocal _last_gold_scan_time
        now_ts = time.time()

        is_us = False
        if enable_adaptive:
            try:
                from trading.mt5_bridge import MT5Bridge
                is_us = MT5Bridge().is_us_session_window()
            except Exception:
                pass

        target_interval = gold_scan_us_sec if is_us else gold_scan_sec
        if target_interval > 1 and (now_ts - _last_gold_scan_time < (target_interval - 0.2)):
            return

        _last_gold_scan_time = now_ts
        try:
            gold_open, _ = is_gold_market_open(config=runner.config)
            if gold_open:
                runner.run_pipeline(watchlist=["XAUUSD"], force_run=False)
        except Exception as ex_g:
            logger.debug(f"Pengecekan real-time Gold: {ex_g}")

    job_label = (
        f"Pemindaian Real-Time Gold XAU/USD (Adaptive: {gold_scan_us_sec}s US / {gold_scan_sec}s Normal)"
        if enable_adaptive and gold_scan_sec != gold_scan_us_sec
        else f"Pemindaian Real-Time Gold XAU/USD ({gold_scan_sec} Detik Semua Sesi)"
    )

    scan_trigger_sec = max(2, min(gold_scan_sec, gold_scan_us_sec) if enable_adaptive else gold_scan_sec)
    scheduler.add_job(
        scan_gold_job,
        trigger=IntervalTrigger(seconds=scan_trigger_sec),
        id="gold_realtime_job",
        name=job_label,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # Jadwalkan pengecekan berita besar (FOMC, CPI, NFP) tiap 1 menit untuk alert T-10 menit
    scheduler.add_job(
        runner.check_upcoming_news_job,
        trigger=IntervalTrigger(minutes=1),
        id="pre_news_checker_job",
        name="Pengecekan High-Impact News 10 Menit",
        replace_existing=True,
    )

    # Jadwalkan pengecekan deal penutupan posisi MT5 (TP/SL hit) tiap 1 detik (LIVE INSTANT)
    scheduler.add_job(
        runner.check_and_report_mt5_deals,
        trigger=IntervalTrigger(seconds=deal_watcher_sec),
        id="mt5_deal_watcher_job",
        name=f"Pemantauan Real-Time TP/SL MT5 ({deal_watcher_sec} Detik)",
        replace_existing=True,
    )

    # Jadwalkan Pemulihan Mandiri Proaktif (Auto-Repair & Self-Healing Watchdog) tiap 30 detik
    scheduler.add_job(
        runner.run_auto_repair_job,
        trigger=IntervalTrigger(seconds=30),
        id="auto_repair_watchdog_job",
        name="Pemulihan Mandiri & Audit Posisi MT5 (30 Detik)",
        replace_existing=True,
    )

    # Jadwalkan laporan penutupan pasar saham IDX simpel (16:05 WIB, Senin-Jumat)
    scheduler.add_job(
        runner.run_market_close_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone=ZoneInfo("Asia/Jakarta")),
        id="idx_market_close_report_job",
        name="Laporan Penutupan Pasar Saham IDX Simpel",
        replace_existing=True,
    )

    # Jadwalkan Rekap Performa Harian MT5 (USC) & Crypto (22:00 WIB Setiap Hari)
    scheduler.add_job(
        runner.send_daily_performance_recap_job,
        trigger=CronTrigger(hour=22, minute=0, timezone=ZoneInfo("Asia/Jakarta")),
        id="daily_2200_recap_job",
        name="Laporan Rekap Performa Harian 22:00 WIB (MT5 & Crypto)",
        replace_existing=True,
    )

    # Auto-Pull Git Updates berkala (tiap 5 menit) untuk auto-sync dari GitHub Collab
    git_cfg = runner.config.get("git_sync", {})
    if git_cfg.get("enabled", True):
        from scheduler.auto_updater import GitAutoUpdater
        git_updater = GitAutoUpdater(
            base_dir=BASE_DIR,
            branch=git_cfg.get("branch", "main"),
            auto_restart=git_cfg.get("auto_restart", True),
            notifier=runner.notifier if git_cfg.get("notify_telegram", True) else None,
        )
        pull_interval_mins = int(git_cfg.get("interval_minutes", 5))
        scheduler.add_job(
            git_updater.check_and_pull,
            trigger=IntervalTrigger(minutes=pull_interval_mins),
            id="git_auto_pull_job",
            name=f"Auto-Pull Git Updates ({pull_interval_mins} Menit)",
            replace_existing=True,
        )
        logger.info(f"Git Auto-Puller aktif: memeriksa commit origin/{git_cfg.get('branch', 'main')} tiap {pull_interval_mins} menit.")

    # Inisialisasi Auto-Pump Sniper Binance jika diaktifkan
    crypto_cfg = runner.config.get("crypto", {})
    if crypto_cfg.get("enabled", False) or os.getenv("AUTOPUMP_AUTO_START", "false").lower() in ("true", "1"):
        try:
            from crypto.auto_pump import AutoPumpSniper
            crypto_sniper = AutoPumpSniper.get_instance()
            crypto_sniper.telegram_notifier = runner.notifier
            crypto_sniper.set_enabled(True)
            logger.info(f"AutoPumpSniper Binance aktif (Mode: {crypto_sniper.mode.upper()}, Modal: ${crypto_sniper.capital_per_coin} USDT).")
        except Exception as e:
            logger.warning(f"Gagal mengaktifkan AutoPumpSniper di start_scheduler: {e}")

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
