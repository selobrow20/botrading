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
import numpy as np
from tabulate import tabulate
from data.storage import StockStorage
from indicators.technical import TechnicalIndicators


def test_stage_2():
    print("=" * 75)
    print("TEST TAHAP 2: KALKULASI & VERIFIKASI INDIKATOR TEKNIKAL (BBCA.JK)")
    print("=" * 75)

    storage = StockStorage()
    ticker = "BBCA.JK"
    df = storage.load_ohlcv(ticker, interval="1d")

    assert not df.empty, f"Data {ticker} tidak ditemukan di database SQLite!"
    print(f"Data mentah dimuat: {len(df)} baris (Rentang: {df.index[0].date()} s/d {df.index[-1].date()})")

    # 1. Hitung seluruh indikator
    df_ind = TechnicalIndicators.add_all_indicators(df)
    assert not df_ind.empty

    # 2. Verifikasi Indikator Individual
    print("\n[Verifikasi Integritas Matematika Indikator]")

    # Check SMA & EMA
    for p in [20, 50, 200]:
        assert f"SMA_{p}" in df_ind.columns
        assert f"EMA_{p}" in df_ind.columns
        # Cek nilai tidak semuanya NaN
        valid_sma = df_ind[f"SMA_{p}"].dropna()
        valid_ema = df_ind[f"EMA_{p}"].dropna()
        assert len(valid_sma) > 0, f"SMA_{p} tidak boleh kosong!"
        assert len(valid_ema) > 0, f"EMA_{p} tidak boleh kosong!"
    print("✓ SMA & EMA (20, 50, 200) terverifikasi.")

    # Check RSI
    assert "RSI_14" in df_ind.columns
    valid_rsi = df_ind["RSI_14"].dropna()
    assert (valid_rsi >= 0.0).all() and (valid_rsi <= 100.0).all(), "RSI harus dalam rentang [0, 100]!"
    print(f"✓ RSI (14) terverifikasi (Nilai Min: {valid_rsi.min():.2f}, Max: {valid_rsi.max():.2f}, Terkini: {valid_rsi.iloc[-1]:.2f}).")

    # Check MACD
    assert "MACD" in df_ind.columns and "MACD_Signal" in df_ind.columns and "MACD_Hist" in df_ind.columns
    # Cek rumus histogram = macd - signal
    diff = (df_ind["MACD"] - df_ind["MACD_Signal"]) - df_ind["MACD_Hist"]
    assert np.allclose(diff.dropna(), 0.0), "MACD Histogram harus sama persis dengan (MACD - Signal)!"
    print(f"✓ MACD (12, 26, 9) terverifikasi konsisten dengan selisih EMA.")

    # Check Bollinger Bands
    assert "BB_Upper" in df_ind.columns and "BB_Middle" in df_ind.columns and "BB_Lower" in df_ind.columns
    valid_bb = df_ind[["BB_Upper", "BB_Middle", "BB_Lower"]].dropna()
    assert (valid_bb["BB_Upper"] >= valid_bb["BB_Middle"]).all(), "Upper Band harus >= Middle Band!"
    assert (valid_bb["BB_Middle"] >= valid_bb["BB_Lower"]).all(), "Middle Band harus >= Lower Band!"
    print("✓ Bollinger Bands (20, 2.0) terverifikasi (Lower <= Middle <= Upper).")

    # Check Volume Ratio
    assert "Volume_SMA_20" in df_ind.columns and "Volume_Ratio" in df_ind.columns
    valid_vol = df_ind["Volume_Ratio"].dropna()
    assert (valid_vol >= 0.0).all(), "Volume ratio harus non-negatif!"
    print(f"✓ Analisis Volume terverifikasi (Rasio Terkini: {valid_vol.iloc[-1]:.2f}x rata-rata).")

    # 3. Tampilkan Cuplikan Indikator 7 Hari Perdagangan Terakhir
    print("\n" + "=" * 75)
    print("TABEL HASIL INDIKATOR TEKNIKAL TERKINI (7 HARI TERAKHIR):")
    print("=" * 75)

    display_cols = [
        "Close", "EMA_20", "EMA_50", "EMA_200", 
        "RSI_14", "MACD", "MACD_Signal", "BB_Upper", "BB_Lower", "Volume_Ratio"
    ]
    
    summary_table = df_ind[display_cols].tail(7).round(2).copy()
    summary_table.index = summary_table.index.strftime("%Y-%m-%d")

    print(tabulate(
        summary_table,
        headers=[
            "Tanggal", "Close", "EMA 20", "EMA 50", "EMA 200", 
            "RSI 14", "MACD", "Signal", "BB Up", "BB Low", "Vol Ratio"
        ],
        tablefmt="pretty",
        floatfmt=".2f"
    ))

    print("\n" + "=" * 75)
    print("✅ TAHAP 2 BERHASIL TERVERIFIKASI PENUH!")
    print("=" * 75)


if __name__ == "__main__":
    test_stage_2()
