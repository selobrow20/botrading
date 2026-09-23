"""
Generator visualisasi Candlestick Chart real-time bertema gelap (TradingView style)
untuk Saham IDX dan Komoditas Emas Dunia (XAU/USD).
Menampilkan Candlestick, EMA 20, EMA 50, Volume, RSI, serta garis level Entry, TP, dan SL.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
import pandas as pd
import numpy as np

import matplotlib
matplotlib.use("Agg")  # Headless mode agar aman di server Linux/Windows tanpa display
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.patches import Rectangle

from config.settings import setup_logger

logger = setup_logger("chart_generator")

# Direktori penyimpanan cache chart
CHARTS_DIR = Path("data/charts")
CHARTS_DIR.mkdir(parents=True, exist_ok=True)


class ChartGenerator:
    """Pembuat visual chart candlestick multi-panel beresolusi tinggi."""

    @staticmethod
    def cleanup_old_charts(max_age_hours: int = 12) -> None:
        """Membersihkan file chart lama agar disk tidak membengkak."""
        try:
            now = datetime.now().timestamp()
            cutoff = now - (max_age_hours * 3600)
            for file in CHARTS_DIR.glob("*.png"):
                if file.stat().st_mtime < cutoff:
                    try:
                        file.unlink()
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Gagal membersihkan cache chart: {e}")

    @classmethod
    def generate_chart(
        cls,
        df: pd.DataFrame,
        ticker_symbol: str,
        interval: str = "15m",
        signal_type: Optional[str] = None,
        entry_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        setup_grade: Optional[str] = None,
        pdf_confluence_score: Optional[float] = None,
        num_candles: int = 50,
    ) -> Optional[str]:
        """
        Menghasilkan file gambar PNG candlestick chart dengan indikator teknikal:
        - Panel Atas: Candlestick + EMA 20 + EMA 50 + Garis Entry/TP/SL
        - Panel Tengah: Volume Bar + Volume MA 20
        - Panel Bawah: RSI 14 (Overbought/Oversold Zone)

        Mengembalikan path absolut file gambar yang dihasilkan.
        """
        if df.empty or len(df) < 10:
            logger.warning(f"Data tidak mencukupi untuk membuat chart {ticker_symbol} (len={len(df)})")
            return None

        cls.cleanup_old_charts()

        # Gunakan N candle terakhir agar lilin tampak proporsional dan jelas di layar HP
        df_plot = df.copy().tail(min(num_candles, len(df)))
        n_bars = len(df_plot)

        # Hitung EMA dan RSI jika belum tersedia di DataFrame
        close_series = df_plot["Close"]
        if "EMA_20" not in df_plot.columns:
            df_plot["EMA_20"] = close_series.ewm(span=20, adjust=False).mean()
        if "EMA_50" not in df_plot.columns:
            df_plot["EMA_50"] = close_series.ewm(span=50, adjust=False).mean()
        if "Volume_SMA_20" not in df_plot.columns and "Volume" in df_plot.columns:
            df_plot["Volume_SMA_20"] = df_plot["Volume"].rolling(window=min(20, n_bars), min_periods=1).mean()

        # Deteksi format harga (Gold vs Saham IDX)
        clean_ticker = ticker_symbol.upper()
        is_gold = any(k in clean_ticker for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        currency_prefix = "$" if is_gold else "Rp "
        price_format = "{:,.2f}" if is_gold else "{:,.0f}"

        # Konfigurasi Palet Warna Gelap TradingView Modern
        bg_color = "#0f172a"      # Slate 900 (Background gambar)
        canvas_color = "#1e293b"  # Slate 800 (Background canvas grafik)
        grid_color = "#334155"    # Slate 700 (Garis grid)
        text_color = "#f8fafc"    # Slate 50 (Teks)
        subtext_color = "#94a3b8" # Slate 400 (Subteks)
        bullish_color = "#10b981" # Hijau Emerald
        bearish_color = "#ef4444" # Merah Rose
        ema20_color = "#f59e0b"   # Amber (Bob Volman)
        ema50_color = "#06b6d4"   # Cyan (Martin Pring)

        # Buat Figure dengan 3 Baris Subplot (Price 65%, Volume 15%, RSI 20%)
        fig, (ax_main, ax_vol, ax_rsi) = plt.subplots(
            nrows=3,
            ncols=1,
            figsize=(12, 8.5),
            dpi=120,
            sharex=True,
            gridspec_kw={"height_ratios": [3.5, 0.9, 1.1], "hspace": 0.08},
        )

        fig.patch.set_facecolor(bg_color)
        for ax in (ax_main, ax_vol, ax_rsi):
            ax.set_facecolor(canvas_color)
            ax.grid(True, linestyle="--", linewidth=0.5, color=grid_color, alpha=0.6)
            ax.tick_params(colors=subtext_color, labelsize=9)
            for spine in ax.spines.values():
                spine.set_color(grid_color)

        x_coords = np.arange(n_bars)
        body_width = 0.65
        wick_width = 1.2

        # 1. Gambar Candlestick pada Panel Utama
        for i in range(n_bars):
            row = df_plot.iloc[i]
            c_open = float(row["Open"])
            c_high = float(row["High"])
            c_low = float(row["Low"])
            c_close = float(row["Close"])

            is_up = c_close >= c_open
            color = bullish_color if is_up else bearish_color

            # Garis Sumbu / Ekor (Wick)
            ax_main.vlines(
                x=i,
                ymin=c_low,
                ymax=c_high,
                color=color,
                linewidth=wick_width,
                zorder=2,
            )

            # Badan Candle (Body)
            body_bottom = min(c_open, c_close)
            body_height = max(abs(c_close - c_open), (c_high - c_low) * 0.01)  # Hindari doji 0-height
            rect = Rectangle(
                (i - body_width / 2.0, body_bottom),
                body_width,
                body_height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.8,
                zorder=3,
            )
            ax_main.add_patch(rect)

        # Plot Garis EMA
        ax_main.plot(x_coords, df_plot["EMA_20"], color=ema20_color, linewidth=1.5, label="EMA 20 (Support Dinamis)", zorder=4)
        ax_main.plot(x_coords, df_plot["EMA_50"], color=ema50_color, linewidth=1.5, label="EMA 50 (Tren Mayor)", zorder=4)

        # Garis Entry, Take Profit, dan Stop Loss
        last_close = float(df_plot["Close"].iloc[-1])
        ref_entry = entry_price if (entry_price and entry_price > 0) else last_close

        if entry_price and entry_price > 0:
            ax_main.axhline(
                y=entry_price,
                color="#fbbf24",
                linestyle="--",
                linewidth=1.3,
                label=f"Entry: {currency_prefix}{price_format.format(entry_price)}",
                zorder=5,
            )
            ax_main.text(
                n_bars - 1,
                entry_price,
                f"  ENTRY {currency_prefix}{price_format.format(entry_price)}",
                color="#fbbf24",
                fontsize=8.5,
                weight="bold",
                va="center",
            )

        if tp_price and tp_price > 0:
            tp_diff = ((tp_price - ref_entry) / ref_entry) * 100.0
            tp_sign = "+" if tp_diff > 0 else ""
            ax_main.axhline(
                y=tp_price,
                color="#34d399",
                linestyle="--",
                linewidth=1.3,
                label=f"TP Target: {currency_prefix}{price_format.format(tp_price)} ({tp_sign}{tp_diff:.2f}%)",
                zorder=5,
            )
            ax_main.text(
                n_bars - 1,
                tp_price,
                f"  TP {currency_prefix}{price_format.format(tp_price)} ({tp_sign}{tp_diff:.1f}%)",
                color="#34d399",
                fontsize=8.5,
                weight="bold",
                va="center",
            )

        if sl_price and sl_price > 0:
            sl_diff = ((sl_price - ref_entry) / ref_entry) * 100.0
            sl_sign = "+" if sl_diff > 0 else ""
            ax_main.axhline(
                y=sl_price,
                color="#f87171",
                linestyle="--",
                linewidth=1.3,
                label=f"SL Batas: {currency_prefix}{price_format.format(sl_price)} ({sl_sign}{sl_diff:.2f}%)",
                zorder=5,
            )
            ax_main.text(
                n_bars - 1,
                sl_price,
                f"  SL {currency_prefix}{price_format.format(sl_price)} ({sl_sign}{sl_diff:.1f}%)",
                color="#f87171",
                fontsize=8.5,
                weight="bold",
                va="center",
            )

        # Highlight Harga Terakhir di Y-Axis
        ax_main.text(
            0.015,
            0.93,
            f"LIVE: {currency_prefix}{price_format.format(last_close)}",
            transform=ax_main.transAxes,
            color="#38bdf8",
            fontsize=12,
            weight="bold",
            bbox=dict(facecolor="#0284c7", edgecolor="none", boxstyle="round,pad=0.3", alpha=0.3),
        )

        ax_main.legend(
            loc="upper left",
            bbox_to_anchor=(0.01, 0.88),
            facecolor="#0f172a",
            edgecolor=grid_color,
            fontsize=8,
            labelcolor=text_color,
        )

        # Format Y-Axis Panel Utama
        if is_gold:
            ax_main.yaxis.set_major_formatter(ticker.FormatStrFormatter("$%.2f"))
        else:
            ax_main.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"Rp {x:,.0f}"))

        # 2. Gambar Panel Volume
        vol_colors = [bullish_color if df_plot["Close"].iloc[j] >= df_plot["Open"].iloc[j] else bearish_color for j in range(n_bars)]
        ax_vol.bar(x_coords, df_plot["Volume"], color=vol_colors, width=body_width, alpha=0.75, zorder=2)
        if "Volume_SMA_20" in df_plot.columns:
            ax_vol.plot(x_coords, df_plot["Volume_SMA_20"], color="#f1f5f9", linewidth=1.0, linestyle=":", label="Vol MA20")
        ax_vol.set_ylabel("Volume", color=subtext_color, fontsize=8)
        ax_vol.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"{x/1e6:.1f}M" if x >= 1e6 else f"{x/1e3:.0f}K" if x >= 1e3 else f"{x:.0f}"))

        # 3. Gambar Panel RSI
        rsi_series = df_plot.get("RSI")
        if rsi_series is None or rsi_series.isna().all():
            # Hitung RSI 14 sederhana jika belum ada
            delta = df_plot["Close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=1).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=1).mean()
            rs = gain / (loss.replace(0, 1e-9))
            rsi_series = 100 - (100 / (1 + rs))

        ax_rsi.plot(x_coords, rsi_series, color="#a855f7", linewidth=1.4, label="RSI 14")
        ax_rsi.axhline(70, color="#f87171", linestyle="--", linewidth=0.8, alpha=0.8)
        ax_rsi.axhline(30, color="#34d399", linestyle="--", linewidth=0.8, alpha=0.8)
        ax_rsi.fill_between(x_coords, 30, 70, color="#334155", alpha=0.25)
        ax_rsi.set_ylim(10, 90)
        ax_rsi.set_ylabel("RSI (14)", color=subtext_color, fontsize=8)

        # Label Tanggal / Waktu pada Sumbu X
        date_indices = np.linspace(0, n_bars - 1, min(7, n_bars), dtype=int)
        time_labels = []
        for idx in date_indices:
            dt = df_plot.index[idx]
            dt_str = str(dt)
            # Format: 'DD/MM HH:MM' atau 'HH:MM'
            if len(dt_str) >= 16:
                time_labels.append(dt_str[5:16].replace("-", "/"))
            else:
                time_labels.append(dt_str)

        ax_rsi.set_xticks(date_indices)
        ax_rsi.set_xticklabels(time_labels, rotation=0, ha="center", fontsize=8.5, color=subtext_color)
        ax_main.set_xlim(-1, n_bars + 4)  # Ruang kosong di kanan untuk label harga

        # Judul & Badge Potensi Header
        display_name = "XAU/USD (Gold Spot)" if is_gold else clean_ticker.replace(".JK", "")
        grade_badge = f" [GRADE {setup_grade}]" if setup_grade else ""
        confluence_badge = f" (Konfluensi: {int(pdf_confluence_score * 100)}%)" if pdf_confluence_score else ""
        sig_badge = f" • {signal_type.upper()}" if signal_type in ["BUY", "SELL"] else ""

        title_text = f"{display_name} • {interval.upper()} Live Chart{sig_badge}{grade_badge}{confluence_badge}"
        fig.suptitle(
            title_text,
            fontsize=13,
            weight="bold",
            color=text_color,
            x=0.03,
            y=0.975,
            ha="left",
        )

        # Simpan Gambar ke Direktori Charts
        timestamp_slug = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:18]
        safe_ticker = clean_ticker.replace("=", "").replace("^", "").replace(".", "_")
        filename = f"chart_{safe_ticker}_{interval}_{timestamp_slug}.png"
        output_path = str(CHARTS_DIR / filename)

        try:
            plt.savefig(
                output_path,
                facecolor=fig.get_facecolor(),
                edgecolor="none",
                bbox_inches="tight",
                pad_inches=0.2,
                dpi=120,
            )
            logger.info(f"Berhasil membuat chart visual: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Gagal menyimpan chart gambar: {e}")
            return None
        finally:
            plt.close(fig)

    @classmethod
    def evaluate_asset_potential(
        cls,
        sig: Any,
        df: pd.DataFrame,
    ) -> Tuple[bool, str, str]:
        """
        Mengevaluasi apakah suatu aset layak dikategorikan 'BERPOTENSI' untuk ditampilkan chartnya.
        
        Kriteria:
        1. Sinyal BUY / SELL dengan skor konfluensi >= 50% atau Grade A/A+.
        2. Mendekati pantulan Support Dinamis 20 EMA (Volman Pullback) dengan Rejection Wick.
        3. Berada di Fibonacci Golden Zone (50%-61.8%) dengan momentum RSI sehat.
        4. Volman Buildup (kompresi harga) siap breakout dengan kenaikan volume.
        """
        if df.empty or len(df) < 5:
            return False, "Data tidak cukup", ""

        last_row = df.iloc[-1]
        setup_grade = getattr(sig, "setup_grade", None)
        conf_score = getattr(sig, "pdf_confluence_score", 0.0) or 0.0
        signal = getattr(sig, "signal", "HOLD")

        # 1. Sinyal BUY / SELL resmi yang lolos telaah PDF
        if signal in ["BUY", "SELL"] and (conf_score >= 0.50 or setup_grade in ["A+", "A"]):
            grade_str = f"Grade {setup_grade}" if setup_grade else f"{int(conf_score*100)}%"
            return True, f"Sinyal {signal} ({grade_str})", f"Sinyal {signal} terkonfirmasi dengan konfluensi 7 buku PDF."

        # 2. Pola Pullback Bob Volman + Penolakan Support
        volman_pb = bool(last_row.get("volman_pullback", 0))
        wick_ratio = float(last_row.get("rejection_wick_ratio", 0.0))
        if volman_pb and wick_ratio >= 0.25:
            return True, "Volman Pullback Support 20 EMA", "Harga memantul sempurna di Support Dinamis 20 EMA dengan rejection wick tebal."

        # 3. Fibonacci Golden Pocket Rebound
        fib_gz = bool(last_row.get("fib_in_golden_zone", 0))
        rsi_val = float(last_row.get("RSI", last_row.get("rsi", 50.0)))
        if fib_gz and 38.0 <= rsi_val <= 62.0:
            return True, "Fibonacci Golden Pocket Rebound", "Pantulan terdeteksi di area diskon Golden Pocket (50%-61.8%) dengan RSI prima."

        # 4. Volman Buildup Kompresi Breakout
        volman_bd = bool(last_row.get("volman_buildup", 0))
        vol_ratio = float(last_row.get("volume_ratio", 1.0))
        if volman_bd and vol_ratio >= 1.1:
            return True, "Volman Buildup Breakout", "Konsolidasi ketat (kompresi) disertai peningkatan volume pembeli, siap meledak."

        # 5. Khusus Sinyal BUY biasa
        if signal == "BUY":
            return True, "Setup Sinyal BUY", "Indikator momentum dan tren memberikan sinyal beli aktif."

        return False, "Netral / Tidak Ada Setup", "Pergerakan harga saat ini sideways / belum memenuhi konfluensi 7 buku."
