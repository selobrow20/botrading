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
    """Pemindaian manual satu kali untuk seluruh watchlist."""
    print("\n🔍 Memulai Pemindaian Watchlist Terkini...")
    runner = PipelineRunner()
    res = runner.run_pipeline(force_run=True)

    details = res.get("details", [])
    if not details:
        print("Tidak ada saham yang diproses.")
        return

    table_rows = []
    for d in details:
        table_rows.append([
            d["ticker"],
            d["signal"],
            f"Rp {d['price']:,.0f}",
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


def cmd_run_all(args: argparse.Namespace) -> None:
    """Menjalankan Scheduler dan Bot Telegram bersamaan secara optimal."""
    import time
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from notify.telegram_bot import build_telegram_application
    from scheduler.run_scheduler import PipelineRunner

    print("🚀 Menjalankan Scheduler & Bot Telegram secara paralel...")
    cfg = load_config()
    sched_cfg = cfg.get("scheduler", {})
    interval_mins = int(sched_cfg.get("interval_minutes", 15))

    runner = PipelineRunner()
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        runner.run_pipeline,
        trigger=IntervalTrigger(minutes=interval_mins),
        id="idx_stock_analysis_job",
        name="Analisis Saham Berkala IDX",
        replace_existing=True,
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
        trigger=IntervalTrigger(seconds=30),
        id="mt5_deal_watcher_job",
        name="Pemantauan Real-Time TP/SL MT5",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"BackgroundScheduler aktif (interval: {interval_mins}m, news: 1m, MT5 watcher: 30s).")

    # Jalankan initial run & sync kalender di thread terpisah agar tidak menahan startup listener Telegram
    def _initial_startup_tasks():
        try:
            from data.economic_calendar import EconomicCalendar
            cal = EconomicCalendar(storage=runner.storage)
            cal.sync_calendar()
        except Exception as e:
            logger.warning(f"Gagal sinkronisasi kalender ekonomi di startup: {e}")
        runner.run_pipeline(force_run=False)

    t_init = threading.Thread(
        target=_initial_startup_tasks,
        daemon=True,
        name="InitialScanThread",
    )
    t_init.start()

    # Jalankan Telegram Bot Polling di main thread
    app = build_telegram_application()
    if app:
        logger.info("Telegram Bot Polling listener berjalan di main thread...")
        while True:
            try:
                app.run_polling(drop_pending_updates=True, stop_signals=None)
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


def main():
    parser = argparse.ArgumentParser(
        description="Bot Analisis & Sinyal Trading Saham Indonesia (IDX)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Perintah yang tersedia")

    # Command: scan
    subparsers.add_parser("scan", help="Pemindaian watchlist secara manual satu kali")

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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
