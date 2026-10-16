"""Entry point utama untuk Bot Analisis & Sinyal Trading Saham (IDX).

Perintah CLI:
  python main.py scan               # Jalankan 1x pemindaian watchlist terkini
  python main.py live               # Jalankan scheduler otomatis berkala (jam bursa)
  python main.py backtest           # Uji strategi ke data historis & cetak metrik
  python main.py sweep              # Jalankan parameter sweep untuk optimasi
  python main.py fetch              # Perbarui data pasar lokal dari yfinance
  python main.py telegram           # Jalankan bot Telegram polling listener
  python main.py run-all            # Jalankan scheduler & bot Telegram bersamaan
"""

import os
import sys
import argparse
import threading
from pathlib import Path
from tabulate import tabulate

# Ensure UTF-8 output on Windows console
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

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config.settings import load_config, setup_logger
from data.fetcher import DataFetcher
from data.storage import StockStorage
from strategy.rules import get_strategy, DEFAULT_STRATEGY, list_registered_strategies
from strategy.signal_engine import SignalEngine
from backtest.backtester import Backtester
from notify.telegram_bot import TelegramNotifier, run_telegram_bot_polling
from scheduler.run_scheduler import PipelineRunner, start_scheduler

logger = setup_logger("main")


def cmd_scan(args: argparse.Namespace) -> None:
    """Pemindaian manual satu kali untuk seluruh watchlist atau aset spesifik."""
    print("\n🔍 Memulai Pemindaian Watchlist Terkini...")
    runner = PipelineRunner()
    target_wl = None
    if getattr(args, "ticker", None):
        target_wl = [DataFetcher.normalize_ticker(args.ticker)]
    res = runner.run_pipeline(force_run=True, watchlist=target_wl)

    details = res.get("details", [])
    if not details:
        print("Tidak ada saham yang diproses.")
        return

    table_rows = []
    for d in details:
        is_gold = any(k in d["ticker"].upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        price_str = f"${d['price']:,.2f}" if is_gold else f"Rp {d['price']:,.0f}"
        table_rows.append([
            d["ticker"],
            d["signal"],
            price_str,
            d["candle_time"],
            "YA" if d["notified"] else "TIDAK",
        ])

    print("\n" + "=" * 70)
    print("HASIL PEMINDAIAN PASAR (LIVE SCAN):")
    print("=" * 70)
    print(tabulate(table_rows, headers=["Ticker", "Sinyal", "Harga", "Waktu Candle", "Notifikasi"], tablefmt="pretty"))


def cmd_fetch(args: argparse.Namespace) -> None:
    """Mengambil dan memperbarui data saham ke database lokal."""
    cfg = load_config()
    watchlist = [args.ticker] if args.ticker else cfg.get("watchlist", ["BBCA.JK"])
    interval = args.interval or cfg.get("data", {}).get("default_interval", "1d")
    period = args.period or cfg.get("data", {}).get("default_period", "2y")

    fetcher = DataFetcher()
    print(f"\n📥 Mengunduh data untuk {len(watchlist)} saham (Interval: {interval}, Period: {period})...")

    for ticker in watchlist:
        df = fetcher.fetch_and_store(ticker, interval=interval, period=period)
        if not df.empty:
            print(f"  ✓ {fetcher.normalize_ticker(ticker)}: {len(df)} bar ({df.index[0].date()} s/d {df.index[-1].date()})")
        else:
            print(f"  ✗ {ticker}: Gagal mengambil data.")
    print("Pengambilan data selesai.")


def cmd_backtest(args: argparse.Namespace) -> None:
    """Menjalankan simulasi backtest ke data historis."""
    storage = StockStorage()
    fetcher = DataFetcher(storage=storage)
    cfg = load_config()

    ticker = fetcher.normalize_ticker(args.ticker or "BBCA.JK")
    interval = args.interval or "1d"
    period = args.period or "2y"
    capital = float(args.capital or 100_000_000.0)

    print(f"\n📊 Memulai Backtest: {ticker} (Interval: {interval}, Modal: Rp {capital:,.0f})...")
    df = fetcher.get_data(ticker, interval=interval, period=period, force_fetch=args.force_fetch)
    if df.empty:
        print(f"Data tidak tersedia untuk {ticker}.")
        return

    # Pilih strategi
    strat_name = args.strategy or cfg.get("strategies", {}).get("active", DEFAULT_STRATEGY.name)
    strategy = get_strategy(strat_name) or DEFAULT_STRATEGY

    trading_cfg = cfg.get("trading", {})
    mode = "intraday" if "m" in interval or "h" in interval else "daily"
    mode_cfg = trading_cfg.get(mode, {})
    tp_pct = float(args.tp) if args.tp else float(mode_cfg.get("take_profit_pct", 5.0))
    sl_pct = float(args.sl) if args.sl else float(mode_cfg.get("stop_loss_pct", 3.0))

    backtester = Backtester(
        initial_capital=capital,
        take_profit_pct=tp_pct,
        stop_loss_pct=sl_pct,
        storage=storage,
    )

    result = backtester.run(df, strategy=strategy, ticker=ticker, save_chart=True)

    print("\n" + "=" * 70)
    print(f"HASIL BACKTEST: {ticker} ({strategy.name})")
    print("=" * 70)
    summary_data = [[k, v] for k, v in result.summary_dict().items()]
    print(tabulate(summary_data, headers=["Metrik", "Nilai"], tablefmt="pretty"))

    if result.trades:
        print(f"\nRiwayat 10 Trade Terakhir (Total: {len(result.trades)} trades):")
        t_rows = []
        for t in result.trades[-10:]:
            t_rows.append([
                t.entry_time.strftime("%Y-%m-%d" if interval == "1d" else "%d/%m %H:%M"),
                f"Rp {t.entry_price:,.0f}",
                t.exit_time.strftime("%Y-%m-%d" if interval == "1d" else "%d/%m %H:%M"),
                f"Rp {t.exit_price:,.0f}",
                f"{t.pnl_pct:+.2f}%",
                f"Rp {t.pnl:+,.0f}",
                f"{t.holding_bars} bar",
                t.exit_reason,
            ])
        print(tabulate(t_rows, headers=["In", "Price In", "Out", "Price Out", "P&L %", "Net P&L", "Durasi", "Exit Reason"], tablefmt="pretty"))

    if result.chart_path:
        print(f"\n📈 Grafik Equity Curve tersimpan di: {result.chart_path}")


def cmd_sweep(args: argparse.Namespace) -> None:
    """Menjalankan parameter sweep untuk membandingkan kombinasi parameter."""
    storage = StockStorage()
    fetcher = DataFetcher(storage=storage)
    ticker = fetcher.normalize_ticker(args.ticker or "BBCA.JK")
    interval = args.interval or "1d"
    period = args.period or "2y"

    print(f"\n🔬 Menjalankan Parameter Sweep untuk {ticker}...")
    df = fetcher.get_data(ticker, interval=interval, period=period)
    if df.empty:
        print(f"Data tidak tersedia untuk {ticker}.")
        return

    backtester = Backtester(storage=storage)
    sweep_df = backtester.parameter_sweep(
        df,
        ticker=ticker,
        rsi_oversold_range=[25.0, 30.0, 35.0, 40.0],
        rsi_overbought_range=[65.0, 70.0, 75.0],
        volume_multipliers=[1.0, 1.2, 1.5],
    )

    if sweep_df.empty:
        print("Tidak ada kombinasi yang berhasil dihitung.")
        return

    print("\n" + "=" * 70)
    print(f"TOP 10 KOMBINASI PARAMETER ({ticker}):")
    print("=" * 70)
    top_10 = sweep_df.head(10).copy()
    print(tabulate(top_10, headers="keys", tablefmt="pretty", floatfmt=(".0f", ".1f", ".1f", ".1f", ".0f", ".1f", ".2f", ".2f", ".2f")))


def cmd_live(args: argparse.Namespace) -> None:
    """Menjalankan scheduler otomatis berkala saat jam bursa IDX."""
    start_scheduler()


def cmd_telegram(args: argparse.Namespace) -> None:
    """Menjalankan bot Telegram polling listener."""
    run_telegram_bot_polling()


def ensure_single_instance() -> None:
    """
    Memastikan hanya ada 1 instance 'main.py run-all' yang aktif di sistem.
    Jika terdeteksi instance lama yang masih berjalan (misal dari sesi terminal lain),
    instance lama otomatis dihentikan agar tidak terjadi tabrakan koneksi Telegram (HTTP 409 Conflict).
    """
    import os
    try:
        import psutil
        curr_pid = os.getpid()
        parent_pid = os.getppid()

        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                pid = proc.info["pid"]
                if pid in (curr_pid, parent_pid):
                    continue

                cmdline = proc.info.get("cmdline") or []
                cmd_str = " ".join(cmdline).lower()
                if "python" in proc.info.get("name", "").lower() and "main.py" in cmd_str and "run-all" in cmd_str:
                    logger.info(f"🔄 Terdeteksi instance bot lama (PID {pid}). Menutup instance lama agar proses baru mengambil alih...")
                    p = psutil.Process(pid)
                    p.terminate()
                    try:
                        p.wait(timeout=3)
                    except Exception:
                        p.kill()
            except Exception:
                pass
    except Exception:
        pass


def cmd_run_all(args: argparse.Namespace) -> None:
    """Menjalankan Scheduler dan Bot Telegram bersamaan secara optimal."""
    ensure_single_instance()
    import time
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger
    from zoneinfo import ZoneInfo
    from notify.telegram_bot import build_telegram_application
    from scheduler.run_scheduler import PipelineRunner, is_gold_market_open

    print("🚀 Menjalankan Scheduler & Bot Telegram secara paralel...")
    cfg = load_config()
    sched_cfg = cfg.get("scheduler", {})
    interval_mins = int(sched_cfg.get("interval_minutes", 15))

    runner = PipelineRunner()
    scheduler = BackgroundScheduler()
    # Redam spam peringatan skipped internal APScheduler agar console tetap bersih
    import logging
    logging.getLogger("apscheduler.executors.default").setLevel(logging.ERROR)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.ERROR)

    scheduler.add_job(
        runner.run_pipeline,
        trigger=IntervalTrigger(minutes=interval_mins),
        id="idx_stock_analysis_job",
        name="Analisis Saham Berkala IDX",
        replace_existing=True,
    )

    # Jadwalkan pemindaian khusus Gold XAU/USD real-time kilat (Konfigurasi Agresif)
    gold_scan_sec = int(sched_cfg.get("gold_scan_interval_seconds", 5))
    gold_scan_us_sec = int(sched_cfg.get("gold_scan_us_session_seconds", 2))
    enable_adaptive = bool(sched_cfg.get("enable_adaptive_gold_scan", True))
    deal_watcher_sec = int(sched_cfg.get("mt5_deal_watcher_seconds", 1))

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

    scheduler.add_job(
        runner.check_upcoming_news_job,
        trigger=IntervalTrigger(minutes=1),
        id="upcoming_news_check_job",
        name="Pengecekan News XAU T-10 Menit",
        replace_existing=True,
    )
    scheduler.add_job(
        runner.check_and_report_mt5_deals,
        trigger=IntervalTrigger(seconds=deal_watcher_sec),
        id="mt5_deal_watcher_job",
        name=f"Pemantauan Real-Time TP/SL MT5 ({deal_watcher_sec} Detik)",
        replace_existing=True,
    )

    # Sistem Auto-Repair & Self-Healing Mandiri (Audit Tiap 10 Detik)
    scheduler.add_job(
        runner.run_auto_repair_job,
        trigger=IntervalTrigger(seconds=10),
        id="auto_repair_watchdog_job",
        name="Auto-Repair & Self-Healing Guardian (10s)",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # Jadwalkan laporan penutupan pasar saham IDX simpel (16:05 WIB, Senin-Jumat)
    scheduler.add_job(
        runner.run_market_close_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone=ZoneInfo("Asia/Jakarta")),
        id="idx_market_close_report_job",
        name="Laporan Penutupan Pasar Saham IDX Simpel",
        replace_existing=True,
    )

    # Auto-Pull Git Updates berkala (tiap 5 menit) untuk auto-sync dari GitHub Collab
    git_cfg = cfg.get("git_sync", {})
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

    scheduler.start()
    logger.info(f"BackgroundScheduler aktif (idx: {interval_mins}m, gold: {gold_scan_sec}s ULTRA-FAST, auto-repair: 10s, news: 1m, MT5 watcher: {deal_watcher_sec}s INSTANT, git auto-pull: 5m).")

    # Jalankan initial run & sync kalender di thread terpisah agar tidak menahan startup listener Telegram
    def _initial_startup_tasks():
        try:
            from data.economic_calendar import EconomicCalendar
            cal = EconomicCalendar(storage=runner.storage)
            cal.sync_calendar()
        except Exception as e:
            logger.warning(f"Gagal sinkronisasi kalender ekonomi di startup: {e}")
        # Warmup scan saat startup: hanya ambil data & catat baseline candle, DILARANG eksekusi order MT5 langsung
        runner.run_pipeline(force_run=False, is_startup_warmup=True)

    t_init = threading.Thread(
        target=_initial_startup_tasks,
        daemon=True,
        name="InitialScanThread",
    )
    t_init.start()

    # Inisialisasi Auto-Pump Sniper Binance jika diaktifkan
    try:
        from crypto.auto_pump import AutoPumpSniper
        crypto_sniper = AutoPumpSniper.get_instance()
        crypto_sniper.telegram_notifier = runner.notifier
        cfg = load_config()
        crypto_cfg = cfg.get("crypto", {})
        if crypto_cfg.get("enabled", False) or os.getenv("AUTOPUMP_AUTO_START", "false").lower() in ("true", "1"):
            crypto_sniper.set_enabled(True)
            logger.info(f"AutoPumpSniper Binance aktif (Mode: {crypto_sniper.mode.upper()}, Modal: ${crypto_sniper.capital_per_coin} USDT).")
    except Exception as e:
        logger.warning(f"Inisialisasi AutoPumpSniper di cmd_run_all: {e}")

    # Jalankan Telegram Bot Polling di main thread
    has_telegram = bool(build_telegram_application())
    if has_telegram:
        import asyncio
        logger.info("Telegram Bot Polling listener berjalan di main thread...")
        while True:
            try:
                # Pastikan event loop selalu baru dan bersih agar tidak terjadi 'Event loop is closed'
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                except Exception:
                    pass

                app = build_telegram_application()
                if not app:
                    break
                app.run_polling(
                    drop_pending_updates=True,
                    stop_signals=None,
                    bootstrap_retries=-1,
                )
                break
            except (KeyboardInterrupt, SystemExit):
                logger.info("Mematikan bot...")
                break
            except Exception as e:
                logger.error(f"Error pada polling Telegram: {e}. Mencoba reconnect dalam 5 detik...")
                time.sleep(5)
        scheduler.shutdown()
    else:
        logger.warning("Token Telegram belum terkonfigurasi. Scheduler berjalan di background.")
        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()


def cmd_learn_pdf(args: argparse.Namespace) -> None:
    """Mengekstrak konsep dan menghasilkan konfigurasi strategi dari materi PDF."""
    from strategy.pdf_learner import learn_from_pdf
    pdf_path = args.path
    print(f"\n📖 Membaca materi strategi trading dari PDF: {pdf_path}...")
    try:
        res = learn_from_pdf(pdf_path)
        print("=" * 65)
        print(f"📄 File: {res['filename']} ({res['total_pages']} halaman)")
        print(f"🔍 Indikator Terdeteksi: {', '.join(res['indicators_found']) if res['indicators_found'] else '-'}")
        print(f"⚙️ Nama Strategi: {res['strategy_name']}")
        print("=" * 65)
        print("\nKonfigurasi YAML yang Dihasilkan (Siap Dipakai di config.yaml):")
        print(res["yaml_config"])
        print("=" * 65)
        print("💡 Tips: Anda dapat menyalin konfigurasi di atas ke config/config.yaml untuk di-backtest!")
    except Exception as e:
        print(f"❌ Error saat memproses PDF: {e}")


def cmd_send_copier(args: argparse.Namespace) -> None:
    """Kirim file member_copier.zip ke target chat atau broadcast ke seluruh member."""
    notifier = TelegramNotifier()
    zip_path = Path(args.path) if args.path else BASE_DIR / "member_copier.zip"
    if not zip_path.exists():
        print(f"❌ File {zip_path} tidak ditemukan!")
        return

    if args.target:
        print(f"📤 Mengirim {zip_path.name} ke target {args.target}...")
        ok = notifier.send_document(str(zip_path), caption=args.caption or "", target_chat_id=args.target)
        if ok:
            print("✅ File berhasil dikirim!")
        else:
            print("❌ Gagal mengirim file.")
    else:
        print(f"📤 Menyiarkan {zip_path.name} ke seluruh member aktif & server utama...")
        res = notifier.broadcast_copier_update(zip_path=str(zip_path), custom_caption=args.caption)
        print(f"Hasil broadcast: {res}")


def cmd_autopump(args: argparse.Namespace) -> None:
    """Kontrol dan eksekusi Auto-Pump Sniper Bot di Binance Spot."""
    import time
    from crypto.auto_pump import AutoPumpSniper
    sniper = AutoPumpSniper.get_instance()

    if getattr(args, "mode", None):
        sniper.set_mode(args.mode)
    if getattr(args, "capital", None):
        sniper.capital_per_coin = float(args.capital)
    if getattr(args, "max_pos", None):
        sniper.max_positions = int(args.max_pos)
    if getattr(args, "min_score", None):
        sniper.min_score = int(args.min_score)

    if getattr(args, "panic_close", False):
        print("\n🚨 Menjalankan Panic Close All untuk Posisi Crypto...")
        res = sniper.close_all_positions(reason="Manual CLI Panic Close")
        print(f"Hasil: {res['message']}")
        return

    if getattr(args, "status", False):
        print("\n" + sniper.format_status_report())
        return

    if getattr(args, "once", False):
        print(f"\n🎯 Menjalankan 1x Scan & Snipe Binance Spot (Mode: {sniper.mode.upper()}, Capital: ${sniper.capital_per_coin} USDT)...")
        sniper.set_enabled(True)
        res = sniper.scan_and_snipe()
        if res:
            print(f"✅ Berhasil eksekusi order: {res['symbol']} @ ${res['entry_price']} (Skor: {res['pump_score']})")
        else:
            print("ℹ️ Tidak ada koin yang memenuhi kriteria snipe saat ini atau slot posisi penuh.")
        return

    # Loop / Live runner mode
    print("=" * 70)
    print("🚀 MEMULAI AUTO-PUMP SNIPER BINANCE SPOT")
    print(f"• Mode: {sniper.mode.upper()}")
    print(f"• Modal per Koin: ${sniper.capital_per_coin} USDT")
    print(f"• Maks Posisi: {sniper.max_positions} Koin")
    print(f"• Min Skor: {sniper.min_score}/100")
    print("• Tekan Ctrl + C untuk berhenti.")
    print("=" * 70)
    sniper.set_enabled(True)
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Menghentikan Auto-Pump Sniper...")
        sniper.set_enabled(False)
        print("Sniper berhasil dihentikan.")


def main():
    parser = argparse.ArgumentParser(
        description="Bot Analisis & Sinyal Trading Saham Indonesia (IDX)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Perintah yang tersedia")

    # Command: scan
    p_scan = subparsers.add_parser("scan", help="Pemindaian watchlist secara manual satu kali")
    p_scan.add_argument("--ticker", "-t", type=str, help="Kode saham atau komoditas spesifik untuk dipindai (contoh: XAUUSD, BBCA)")

    # Command: fetch
    p_fetch = subparsers.add_parser("fetch", help="Ambil & perbarui data pasar dari yfinance")
    p_fetch.add_argument("--ticker", "-t", type=str, help="Kode saham (contoh: BBCA.JK)")
    p_fetch.add_argument("--interval", "-i", type=str, help="Interval (1d, 15m, 30m, 1h)")
    p_fetch.add_argument("--period", "-p", type=str, help="Periode (60d, 1y, 2y)")

    # Command: backtest
    p_backtest = subparsers.add_parser("backtest", help="Uji strategi ke data historis")
    p_backtest.add_argument("--ticker", "-t", type=str, default="BBCA.JK", help="Kode saham")
    p_backtest.add_argument("--strategy", "-s", type=str, help="Nama strategi")
    p_backtest.add_argument("--interval", "-i", type=str, default="1d", help="Interval candle (1d, 15m)")
    p_backtest.add_argument("--period", "-p", type=str, default="2y", help="Periode data (1y, 2y)")
    p_backtest.add_argument("--capital", "-c", type=float, default=100_000_000, help="Modal awal (IDR)")
    p_backtest.add_argument("--tp", type=float, help="Target Profit (%%)")
    p_backtest.add_argument("--sl", type=float, help="Stop Loss (%%)")
    p_backtest.add_argument("--force-fetch", action="store_true", help="Paksa ambil data baru dari yfinance")

    # Command: sweep
    p_sweep = subparsers.add_parser("sweep", help="Parameter sweep untuk mencari kombinasi parameter optimal")
    p_sweep.add_argument("--ticker", "-t", type=str, default="BBCA.JK", help="Kode saham")
    p_sweep.add_argument("--interval", "-i", type=str, default="1d", help="Interval candle")
    p_sweep.add_argument("--period", "-p", type=str, default="2y", help="Periode data")

    # Command: live
    subparsers.add_parser("live", help="Jalankan scheduler pemantauan berkala saat jam bursa")

    # Command: telegram
    subparsers.add_parser("telegram", help="Jalankan bot listener Telegram (/status, /watchlist, /lasthistory)")

    # Command: run-all
    subparsers.add_parser("run-all", help="Jalankan scheduler dan Telegram bot secara paralel")

    # Command: learn-pdf
    p_pdf = subparsers.add_parser("learn-pdf", help="Ekstrak aturan trading dari materi/buku PDF")
    p_pdf.add_argument("path", type=str, help="Lokasi file PDF (contoh: materials/buku_trading.pdf)")

    # Command: send-copier
    p_copier = subparsers.add_parser("send-copier", help="Kirim/broadcast file member_copier.zip via Telegram")
    p_copier.add_argument("--target", "-t", type=str, help="Target Chat ID (opsional, jika kosong broadcast ke seluruh member & admin)")
    p_copier.add_argument("--path", "-p", type=str, help="Lokasi file ZIP (default: member_copier.zip)")
    # Command: autopump / crypto
    p_pump = subparsers.add_parser("autopump", aliases=["crypto"], help="Jalankan Auto-Pump Sniper trading otomatis di Binance Spot")
    p_pump.add_argument("--mode", "-m", type=str, choices=["real", "paper"], help="Pilih mode eksekusi ('real' untuk Binance Live, 'paper' untuk simulasi)")
    p_pump.add_argument("--capital", "-c", type=float, help="Modal per koin dalam USDT (minimal 5.0 untuk Binance Spot)")
    p_pump.add_argument("--max-pos", type=int, help="Maksimal koin posisi terbuka secara bersamaan (default: 3)")
    p_pump.add_argument("--min-score", type=int, help="Skor minimal pump scanner (0-100, default: 85)")
    p_pump.add_argument("--once", action="store_true", help="Jalankan pemindaian & eksekusi 1x saja lalu selesai")
    p_pump.add_argument("--status", "-s", action="store_true", help="Lihat status saldo, mode, dan posisi terbuka saat ini")
    p_pump.add_argument("--panic-close", action="store_true", help="Tutup dan jual seluruh posisi crypto seketika")

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "sweep":
        cmd_sweep(args)
    elif args.command == "live":
        cmd_live(args)
    elif args.command == "telegram":
        cmd_telegram(args)
    elif args.command == "run-all":
        cmd_run_all(args)
    elif args.command == "learn-pdf":
        cmd_learn_pdf(args)
    elif args.command == "send-copier":
        cmd_send_copier(args)
    elif args.command in ("autopump", "crypto"):
        cmd_autopump(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
