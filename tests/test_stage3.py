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
from data.storage import StockStorage
from indicators.technical import TechnicalIndicators
from strategy.rules import RuleCondition, Strategy, DEFAULT_STRATEGY
from strategy.signal_engine import SignalEngine, SignalResult


def test_stage_3():
    print("=" * 75)
    print("TEST TAHAP 3: RULE ENGINE & STRATEGI DEKLARATIF")
    print("=" * 75)

    storage = StockStorage()
    ticker = "BBCA.JK"
    df = storage.load_ohlcv(ticker, interval="1d")
    assert not df.empty, f"Data {ticker} tidak boleh kosong!"
    df_ind = TechnicalIndicators.add_all_indicators(df)

    # 1. Verifikasi Evaluasi Kondisi Individu (RuleCondition)
    print("\n[1/3] Menguji Evaluasi Kondisi Deklaratif...")
    row_curr = df_ind.iloc[-1]
    row_prev = df_ind.iloc[-2]

    # Test Rule 1: RSI < 30
    rc1 = RuleCondition("rsi", "<", value=30.0, description="RSI Oversold")
    sat1, reason1 = rc1.evaluate_bar(row_curr, row_prev)
    print(f"  - Aturan 1: {reason1} -> Terpenuhi: {sat1}")

    # Test Rule 2: Close > EMA 50
    rc2 = RuleCondition("close", ">", target="ema_50", description="Close > EMA50")
    sat2, reason2 = rc2.evaluate_bar(row_curr, row_prev)
    print(f"  - Aturan 2: {reason2} -> Terpenuhi: {sat2}")

    # Test Rule 3: Volume > 1.5x Volume SMA 20
    rc3 = RuleCondition("volume", ">", target="volume_sma_20", multiplier=1.5, description="Volume Surge")
    sat3, reason3 = rc3.evaluate_bar(row_curr, row_prev)
    print(f"  - Aturan 3: {reason3} -> Terpenuhi: {sat3}")

    # 2. Inisialisasi SignalEngine dengan Strategi Default
    print("\n[2/3] Mengevaluasi Strategi Default (RSI_EMA_Volume) pada Candle Terkini...")
    engine = SignalEngine([DEFAULT_STRATEGY])
    result: SignalResult = engine.evaluate_bar(df_ind, ticker=ticker, strategy=DEFAULT_STRATEGY)

    print(f"  Ticker       : {result.ticker}")
    print(f"  Strategi     : {result.strategy_name}")
    print(f"  Waktu Candle : {result.candle_time}")
    print(f"  Harga        : Rp {result.price:,.0f}")
    print(f"  SINYAL       : {result.signal}")
    print(f"  Alasan / Detail:")
    for r in result.reasons:
        print(f"    * {r}")

    assert result.signal in ["BUY", "SELL", "HOLD"]
    assert len(result.reasons) > 0

    # 3. Uji Multi-Strategi Sekaligus
    print("\n[3/3] Menguji Eksekusi Multi-Strategi Secara Bersamaan...")
    # Buat strategi kedua: MACD Crossover Trend
    macd_trend_strategy = Strategy(
        name="MACD_Trend_Follower",
        description="Strategi Mengikuti Tren dengan Konfirmasi MACD Crossover & EMA 200",
        buy_rules=[
            RuleCondition("macd", "cross_above", target="macd_signal", description="MACD Golden Cross"),
            RuleCondition("close", ">", target="ema_200", description="Harga di atas EMA 200 (Uptrend Jangka Panjang)"),
        ],
        buy_combine="AND",
        sell_rules=[
            RuleCondition("macd", "cross_under", target="macd_signal", description="MACD Death Cross"),
        ],
        sell_combine="OR",
    )

    multi_engine = SignalEngine([DEFAULT_STRATEGY, macd_trend_strategy])
    multi_results = multi_engine.evaluate_all_strategies(df_ind, ticker=ticker)

    table_data = []
    for res in multi_results:
        table_data.append([
            res.strategy_name,
            res.signal,
            f"Rp {res.price:,.0f}",
            "; ".join(res.reasons)[:60] + "..." if len("; ".join(res.reasons)) > 60 else "; ".join(res.reasons)
        ])

    print("\n" + "=" * 75)
    print(f"HASIL MULTI-STRATEGI UNTUK {ticker} (CANDLE TERKINI):")
    print("=" * 75)
    print(tabulate(
        table_data,
        headers=["Nama Strategi", "Sinyal", "Harga", "Alasan Pemicu"],
        tablefmt="pretty"
    ))

    # 4. Uji Deret Historis Sinyal (Vectorized untuk Backtesting)
    signals_series_df = SignalEngine.generate_signals_series(df_ind, DEFAULT_STRATEGY)
    signal_counts = signals_series_df["Signal"].value_counts().to_dict()
    print(f"\nDistribusi Sinyal Historis 1 Tahun ({ticker}):")
    print(f"  - HOLD : {signal_counts.get('HOLD', 0)}")
    print(f"  - BUY  : {signal_counts.get('BUY', 0)}")
    print(f"  - SELL : {signal_counts.get('SELL', 0)}")

    print("\n" + "=" * 75)
    print("✅ TAHAP 3 BERHASIL TERVERIFIKASI PENUH!")
    print("=" * 75)


if __name__ == "__main__":
    test_stage_3()
