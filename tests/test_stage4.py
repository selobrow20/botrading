import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

import pandas as pd
from tabulate import tabulate
from data.fetcher import DataFetcher
from data.storage import StockStorage
from strategy.rules import Strategy, RuleCondition, DEFAULT_STRATEGY
from backtest.backtester import Backtester


def test_stage_4():
    print("=" * 75)
    print("TEST TAHAP 4: MODUL BACKTESTING, METRIK & EQUITY CURVE")
    print("=" * 75)

    storage = StockStorage()
    fetcher = DataFetcher(storage=storage)
    ticker = "BBCA.JK"

    # Ambil 2 tahun data agar memiliki sampel candle yang representatif
    print(f"\n[1/4] Memuat data historis 2 tahun untuk {ticker}...")
    df = fetcher.get_data(ticker, interval="1d", period="2y", force_fetch=True)
    assert not df.empty, f"Data historis {ticker} tidak boleh kosong!"
    print(f"Data siap: {len(df)} candle harian ({df.index[0].date()} s/d {df.index[-1].date()}).")

    backtester = Backtester(
        initial_capital=100_000_000.0,  # Rp 100 Juta
        commission_pct=0.0015,         # Fee 0.15%
        slippage_pct=0.001,            # Slippage 0.1%
        storage=storage,
    )

    # 1. Uji Backtest Strategi Default
    print("\n[2/4] Menjalankan Backtest Strategi Default (RSI < 30 & Close > EMA50 & Vol > 1.5x)...")
    res_default = backtester.run(df, DEFAULT_STRATEGY, ticker=ticker, save_chart=True)
    
    print("\nRingkasan Kinerja Strategi Default:")
    summary_default = [[k, v] for k, v in res_default.summary_dict().items()]
    print(tabulate(summary_default, headers=["Metrik", "Nilai"], tablefmt="pretty"))

    # 2. Uji Backtest Strategi EMA Golden Cross (Trend Following)
    print("\n[3/4] Menjalankan Backtest Strategi Trend: 'EMA_Golden_Cross' (EMA 20 x EMA 50)...")
    golden_cross_strat = Strategy(
        name="EMA_Golden_Cross",
        description="Beli saat EMA 20 cross above EMA 50, Jual saat EMA 20 cross under EMA 50",
        buy_rules=[
            RuleCondition("ema_20", "cross_above", target="ema_50", description="EMA 20 menembus ke atas EMA 50"),
        ],
        buy_combine="AND",
        sell_rules=[
            RuleCondition("ema_20", "cross_under", target="ema_50", description="EMA 20 menembus ke bawah EMA 50"),
        ],
        sell_combine="OR",
    )

    res_trend = backtester.run(df, golden_cross_strat, ticker=ticker, save_chart=True)
    summary_trend = [[k, v] for k, v in res_trend.summary_dict().items()]
    print(tabulate(summary_trend, headers=["Metrik", "Nilai"], tablefmt="pretty"))

    # Pastikan chart equity curve berhasil disimpan ke disk
    assert res_trend.chart_path is not None, "File grafik harus dihasilkan!"
    assert Path(res_trend.chart_path).exists(), f"File {res_trend.chart_path} tidak ditemukan!"
    print(f"\n✓ File grafik Equity Curve terverifikasi ada di: {res_trend.chart_path}")

    # Tampilkan rincian trades jika ada
    if res_trend.trades:
        print(f"\nRiwayat Transaksi (Trade Log) untuk {golden_cross_strat.name} (Total: {len(res_trend.trades)} trades):")
        trade_rows = []
        for t in res_trend.trades[:8]:  # Tampilkan hingga 8 trade pertama
            trade_rows.append([
                t.entry_time.strftime("%Y-%m-%d"),
                f"Rp {t.entry_price:,.0f}",
                t.exit_time.strftime("%Y-%m-%d"),
                f"Rp {t.exit_price:,.0f}",
                f"{t.pnl_pct:+.2f}%",
                f"Rp {t.pnl:+,.0f}",
                f"{t.holding_bars} hari",
                t.exit_reason,
            ])
        print(tabulate(
            trade_rows,
            headers=["Tgl Masuk", "Harga Masuk", "Tgl Keluar", "Harga Keluar", "P&L %", "Net P&L", "Holding", "Alasan Exit"],
            tablefmt="pretty"
        ))

    # 3. Uji Parameter Sweep Sederhana
    print("\n[4/4] Menjalankan Parameter Sweep untuk Mencari Kombinasi Threshold Optimal...")
    sweep_df = backtester.parameter_sweep(
        df,
        ticker=ticker,
        rsi_oversold_range=[30.0, 35.0, 40.0, 45.0],
        rsi_overbought_range=[65.0, 70.0],
        volume_multipliers=[1.0, 1.2, 1.5],
    )

    print("\nTop 5 Kombinasi Parameter Berdasarkan Total Return & Profit Factor:")
    top_5 = sweep_df.head(5).copy()
    print(tabulate(top_5, headers="keys", tablefmt="pretty", floatfmt=(".0f", ".1f", ".1f", ".1f", ".0f", ".1f", ".2f", ".2f", ".2f")))

    print("\n" + "=" * 75)
    print("✅ TAHAP 4 BERHASIL TERVERIFIKASI PENUH!")
    print("=" * 75)


if __name__ == "__main__":
    test_stage_4()
