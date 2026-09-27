"""
Generator visualisasi Candlestick Chart real-time bertema gelap (Authentic TradingView Dark Mode)
untuk Saham IDX dan Komoditas Emas Dunia (XAU/USD).
Menampilkan Candlestick, EMA 20, EMA 50, Volume, RSI, serta garis level Entry, TP, dan SL
dengan skala harga di sisi kanan dan badge pill harga resmi standar TradingView.
"""

import os
import re
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
    """Pembuat visual chart candlestick multi-panel beresolusi tinggi dengan tema TradingView."""

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
        chart_style: str = "candlestick",
    ) -> Optional[str]:
        """
        Menghasilkan file gambar PNG chart dengan tata letak & palet TradingView Dark Theme:
        - Mendukung gaya 'candlestick' (TradingView Pro) dan 'area' (TradingView Mini/Area).
        - Skala harga berada di sisi KANAN (Right-aligned) standar TradingView.
        - Panel Atas: Candlestick/Area + EMA 20 + EMA 50 + Garis Prev Close + Badge Pill Entry/TP/SL.
        - Panel Tengah: Volume Bar + Volume SMA 20.
        - Panel Bawah: RSI 14 dengan area overbought/oversold TradingView.
        - Watermark TradingView di background chart.

        Mengembalikan path absolut file gambar yang dihasilkan.
        """
        if df.empty or len(df) < 10:
            logger.warning(f"Data tidak mencukupi untuk membuat chart {ticker_symbol} (len={len(df)})")
            return None

        cls.cleanup_old_charts()

        # Gunakan N candle terakhir agar lilin tampak proporsional dan jelas di layar HP/Desktop
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
        price_format = "{:,.3f}" if is_gold else "{:,.0f}"
        exchange_name = "OANDA" if is_gold else "IDX"
        display_ticker = "XAUUSD" if is_gold else clean_ticker.replace(".JK", "")

        # Konfigurasi Palet Warna Gelap TradingView Pro (Dark Theme #131722)
        bg_color = "#131722"       # TradingView Canvas Background
        canvas_color = "#131722"   # TradingView Subplot Background
        grid_color = "#242832"     # TradingView Subtle Grid
        text_color = "#d1d4dc"     # TradingView Primary Text
        subtext_color = "#787b86"  # TradingView Secondary Subtext
        tv_green = "#089981"       # TradingView Up Candle (Emerald)
        tv_red = "#f23645"         # TradingView Down Candle (Rose Red)
        tv_blue = "#2962ff"        # TradingView Active Blue Accent
        ema20_color = "#f59e0b"    # Amber
        ema50_color = "#00bcd4"    # Cyan
        rsi_color = "#7e57c2"      # TradingView Purple

        is_area = (str(chart_style).lower() == "area")

        # Buat Figure: jika mode Area gunakan 1 panel bersih persis TradingView Mobile/Widget;
        # jika mode Candlestick gunakan 3 Baris Subplot (Price 68%, Volume 15%, RSI 17%)
        if is_area:
            fig, ax_main = plt.subplots(figsize=(11.5, 6.8), dpi=130)
            ax_vol = None
            ax_rsi = None
            all_axes = [ax_main]
        else:
            fig, (ax_main, ax_vol, ax_rsi) = plt.subplots(
                nrows=3,
                ncols=1,
                figsize=(13, 8.8),
                dpi=130,
                sharex=True,
                gridspec_kw={"height_ratios": [3.6, 0.85, 1.0], "hspace": 0.04},
            )
            all_axes = [ax_main, ax_vol, ax_rsi]

        fig.patch.set_facecolor(bg_color)

        for ax in all_axes:
            ax.set_facecolor(canvas_color)
            # Skala Y di sisi KANAN persis seperti TradingView asli
            ax.yaxis.tick_right()
            ax.yaxis.set_label_position("right")
            ax.grid(True, linestyle="--", linewidth=0.5, color=grid_color, alpha=0.45)
            ax.tick_params(colors=subtext_color, labelsize=8.5, right=True, left=False)
            for spine in ax.spines.values():
                spine.set_color(grid_color)
            ax.spines["left"].set_visible(False)

        x_coords = np.arange(n_bars)
        body_width = 0.68
        wick_width = 1.15

        # Watermark TradingView di background tengah chart
        ax_main.text(
            0.5, 0.50,
            f"{display_ticker}  {interval.upper()}",
            transform=ax_main.transAxes,
            color="#181c26",
            fontsize=34,
            weight="heavy",
            ha="center",
            va="center",
            zorder=0,
        )
        ax_main.text(
            0.5, 0.36,
            "TradingView",
            transform=ax_main.transAxes,
            color="#141722",
            fontsize=18,
            weight="bold",
            ha="center",
            va="center",
            zorder=0,
        )

        # Status Harga Terakhir (TradingView Status Bar di pojok kiri atas chart)
        last_close = float(df_plot["Close"].iloc[-1])
        last_open = float(df_plot["Open"].iloc[-1])
        last_high = float(df_plot["High"].iloc[-1])
        last_low = float(df_plot["Low"].iloc[-1])

        tv_quote = df.attrs.get("tradingview_quote") or {}
        if tv_quote and "prev_close" in tv_quote:
            prev_close = float(tv_quote["prev_close"])
            chg_pct = float(tv_quote.get("change", 0.0))
            chg_val = last_close - prev_close
        else:
            prev_close = float(df_plot["Close"].iloc[-2]) if n_bars > 1 else last_close
            chg_val = last_close - prev_close
            chg_pct = (chg_val / max(prev_close, 0.01)) * 100.0

        chg_color = tv_green if chg_val >= 0 else tv_red
        chg_sign = "+" if chg_val >= 0 else ""

        # 1. Gambar Panel Utama (Candlestick atau Area Chart standar TradingView)
        if is_area:
            # TradingView Area / Mountain Chart
            ax_main.plot(x_coords, df_plot["Close"], color=tv_green, linewidth=2.0, zorder=4)
            y_area_min = float(df_plot["Low"].min()) * (0.9985 if is_gold else 0.98)
            ax_main.fill_between(x_coords, df_plot["Close"], y_area_min, color=tv_green, alpha=0.18, zorder=2)
            # Tombol TradingView Pro Widget di kanan atas
            fig.text(0.915, 0.965, "[ Snap ]  [ </> ]  [ Full chart ]", color="#787b86", fontsize=8.0, ha="right", weight="bold")
        else:
            # TradingView Candlestick Chart
            for i in range(n_bars):
                row = df_plot.iloc[i]
                c_open = float(row["Open"])
                c_high = float(row["High"])
                c_low = float(row["Low"])
                c_close = float(row["Close"])

                is_up = c_close >= c_open
                color = tv_green if is_up else tv_red

                # Sumbu / Ekor Candle (Wick)
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
                body_height = max(abs(c_close - c_open), (c_high - c_low) * 0.015)
                rect = Rectangle(
                    (i - body_width / 2.0, body_bottom),
                    body_width,
                    body_height,
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.6,
                    zorder=3,
                )
                ax_main.add_patch(rect)

            # Plot Garis EMA
            ax_main.plot(x_coords, df_plot["EMA_20"], color=ema20_color, linewidth=1.3, label="EMA 20", zorder=4)
            ax_main.plot(x_coords, df_plot["EMA_50"], color=ema50_color, linewidth=1.3, label="EMA 50", zorder=4)

        ax_main.text(
            0.015, 0.94,
            f"{display_ticker} · {interval.upper()} · {exchange_name} · TradingView",
            transform=ax_main.transAxes,
            color=text_color,
            fontsize=10.5,
            weight="bold",
            zorder=6,
        )
        ax_main.text(
            0.015, 0.88,
            f"O {price_format.format(last_open)}  H {price_format.format(last_high)}  L {price_format.format(last_low)}  C {price_format.format(last_close)}  {chg_sign}{price_format.format(chg_val)} ({chg_sign}{chg_pct:.2f}%)",
            transform=ax_main.transAxes,
            color=chg_color,
            fontsize=9.0,
            weight="bold",
            zorder=6,
        )

        if not is_area:
            ema20_last = float(df_plot["EMA_20"].iloc[-1])
            ema50_last = float(df_plot["EMA_50"].iloc[-1])
            ax_main.text(
                0.015, 0.82,
                f"EMA 20 {price_format.format(ema20_last)}    EMA 50 {price_format.format(ema50_last)}",
                transform=ax_main.transAxes,
                color=subtext_color,
                fontsize=8.5,
                zorder=6,
            )

        # Garis Prev close (TradingView Dotted Line & Gray Badge di Sisi Kanan Skala Y)
        if prev_close and prev_close > 0:
            ax_main.axhline(y=prev_close, color="#50535e", linestyle=":", linewidth=1.1, alpha=0.85, zorder=4)
            prev_badge_text = f"Prev close  {price_format.format(prev_close)}"
            ax_main.text(
                1.008,
                prev_close,
                f" {prev_badge_text} ",
                transform=ax_main.get_yaxis_transform(),
                color="#ffffff",
                fontsize=8.0,
                weight="bold",
                va="center",
                ha="left",
                bbox=dict(facecolor="#50535e", edgecolor="none", boxstyle="round,pad=0.25"),
                zorder=8,
                clip_on=False,
            )

        # Garis Entry, Take Profit, dan Stop Loss (Ditempatkan di dalam area chart sisi kanan)
        ref_entry = entry_price if (entry_price and entry_price > 0) else last_close
        is_sell_action = bool(signal_type and signal_type.upper() == "SELL")

        # Tampilkan garis ENTRY hanya jika berbeda signifikan dari live price agar tidak tumpang tindih
        if entry_price and entry_price > 0 and abs(entry_price - last_close) >= (last_close * 0.0008):
            ax_main.axhline(y=entry_price, color=tv_blue, linestyle="--", linewidth=1.1, alpha=0.9, zorder=5)
            ax_main.text(
                0.97,
                entry_price,
                f" ENTRY {currency_prefix}{price_format.format(entry_price)} ",
                transform=ax_main.get_yaxis_transform(),
                color="#ffffff",
                fontsize=8,
                weight="bold",
                va="center",
                ha="right",
                bbox=dict(facecolor=tv_blue, edgecolor="none", boxstyle="round,pad=0.25"),
                zorder=7,
            )

        if tp_price and tp_price > 0:
            if is_sell_action:
                tp_diff = ((ref_entry - tp_price) / ref_entry) * 100.0
            else:
                tp_diff = ((tp_price - ref_entry) / ref_entry) * 100.0
            tp_sign = "+" if tp_diff > 0 else ""
            ax_main.axhline(y=tp_price, color=tv_green, linestyle="--", linewidth=1.1, alpha=0.9, zorder=5)
            ax_main.text(
                0.97,
                tp_price,
                f" TP {currency_prefix}{price_format.format(tp_price)} ({tp_sign}{tp_diff:.1f}%) ",
                transform=ax_main.get_yaxis_transform(),
                color="#ffffff",
                fontsize=8,
                weight="bold",
                va="center",
                ha="right",
                bbox=dict(facecolor=tv_green, edgecolor="none", boxstyle="round,pad=0.25"),
                zorder=7,
            )

        if sl_price and sl_price > 0:
            if is_sell_action:
                sl_diff = -((sl_price - ref_entry) / ref_entry) * 100.0
            else:
                sl_diff = ((sl_price - ref_entry) / ref_entry) * 100.0
            sl_sign = "+" if sl_diff > 0 else ""
            ax_main.axhline(y=sl_price, color=tv_red, linestyle="--", linewidth=1.1, alpha=0.9, zorder=5)
            ax_main.text(
                0.97,
                sl_price,
                f" SL {currency_prefix}{price_format.format(sl_price)} ({sl_sign}{sl_diff:.1f}%) ",
                transform=ax_main.get_yaxis_transform(),
                color="#ffffff",
                fontsize=8,
                weight="bold",
                va="center",
                ha="right",
                bbox=dict(facecolor=tv_red, edgecolor="none", boxstyle="round,pad=0.25"),
                zorder=7,
            )

        # Badge Pill Harga Terakhir pada Sisi Kanan Skala Y (TradingView Live Price Pill)
        live_pill_color = tv_green if chg_val >= 0 else tv_red
        ax_main.text(
            1.008,
            last_close,
            f" {price_format.format(last_close)} ",
            transform=ax_main.get_yaxis_transform(),
            color="#ffffff",
            fontsize=8.5,
            weight="bold",
            va="center",
            ha="left",
            bbox=dict(facecolor=live_pill_color, edgecolor="none", boxstyle="round,pad=0.25"),
            zorder=9,
            clip_on=False,
        )

        # Hitung rentang Y dengan margin aman agar tidak menabrak status bar di atas
        all_y = [df_plot["High"].max(), df_plot["Low"].min(), last_close]
        if prev_close and prev_close > 0:
            all_y.append(prev_close)
        if entry_price and entry_price > 0:
            all_y.append(entry_price)
        if tp_price and tp_price > 0:
            all_y.append(tp_price)
        if sl_price and sl_price > 0:
            all_y.append(sl_price)
        raw_max = max(all_y)
        raw_min = min(all_y)
        y_span = max(raw_max - raw_min, 1.0)
        ax_main.set_ylim(raw_min - (y_span * 0.06), raw_max + (y_span * 0.18))

        # Format Label Sumbu Y Panel Utama (TradingView 3 Desimal untuk Gold)
        if is_gold:
            ax_main.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"{x:,.3f}"))
        else:
            ax_main.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"Rp {x:,.0f}"))

        # 2. Gambar Panel Volume & RSI jika mode Candlestick
        if not is_area and ax_vol is not None and ax_rsi is not None:
            vol_colors = [tv_green if df_plot["Close"].iloc[j] >= df_plot["Open"].iloc[j] else tv_red for j in range(n_bars)]
            ax_vol.bar(x_coords, df_plot["Volume"], color=vol_colors, width=body_width, alpha=0.55, zorder=2)
            if "Volume_SMA_20" in df_plot.columns:
                ax_vol.plot(x_coords, df_plot["Volume_SMA_20"], color=tv_blue, linewidth=1.0, linestyle="-", label="Vol MA20", zorder=3)
            vol_last = float(df_plot["Volume"].iloc[-1])
            vol_ma_last = float(df_plot.get("Volume_SMA_20", df_plot["Volume"]).iloc[-1])
            ax_vol.text(
                0.015, 0.76,
                f"Vol {vol_last:,.0f}   Vol MA20 {vol_ma_last:,.0f}",
                transform=ax_vol.transAxes,
                color=subtext_color,
                fontsize=8,
                zorder=4,
            )
            ax_vol.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"{x/1e6:.1f}M" if x >= 1e6 else f"{x/1e3:.0f}K" if x >= 1e3 else f"{x:.0f}"))

            # 3. Gambar Panel RSI (TradingView Purple Style)
            rsi_series = df_plot.get("RSI")
            if rsi_series is None or rsi_series.isna().all():
                delta = df_plot["Close"].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=1).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=1).mean()
                rs = gain / (loss.replace(0, 1e-9))
                rsi_series = 100 - (100 / (1 + rs))

            ax_rsi.plot(x_coords, rsi_series, color=rsi_color, linewidth=1.3, zorder=3)
            ax_rsi.axhline(70, color="#787b86", linestyle="--", linewidth=0.7, alpha=0.5)
            ax_rsi.axhline(30, color="#787b86", linestyle="--", linewidth=0.7, alpha=0.5)
            ax_rsi.fill_between(x_coords, 30, 70, color=rsi_color, alpha=0.08)
            ax_rsi.set_ylim(10, 90)
            rsi_last_val = float(rsi_series.iloc[-1])
            ax_rsi.text(
                0.015, 0.76,
                f"RSI 14 close {rsi_last_val:.1f}",
                transform=ax_rsi.transAxes,
                color=subtext_color,
                fontsize=8,
                zorder=4,
            )

        # Label Tanggal / Waktu pada Sumbu X
        date_indices = np.linspace(0, n_bars - 1, min(7, n_bars), dtype=int)
        time_labels = []
        for idx in date_indices:
            dt = df_plot.index[idx]
            dt_str = str(dt)
            if len(dt_str) >= 16:
                time_labels.append(dt_str[5:16].replace("-", "/"))
            else:
                time_labels.append(dt_str)

        target_x_ax = ax_main if is_area else ax_rsi
        target_x_ax.set_xticks(date_indices)
        target_x_ax.set_xticklabels(time_labels, rotation=0, ha="center", fontsize=8.0, color=subtext_color)
        ax_main.set_xlim(-1, n_bars + (7 if is_gold else 5))  # Berikan ruang kosong di kanan untuk badge pill harga

        # Judul & Header Chart (Dibersihkan dari karakter emoji untuk mencegah missing glyph DejaVu Sans)
        raw_grade = str(setup_grade or "").replace("GRADE ", "").replace("Grade ", "").strip()
        clean_grade = re.sub(r"[^\x20-\x7E]+", "", raw_grade).strip()
        grade_badge = f" [GRADE {clean_grade}]" if clean_grade else ""
        if pdf_confluence_score:
            score_num = pdf_confluence_score if pdf_confluence_score > 1.0 else pdf_confluence_score * 100.0
            confluence_badge = f" (Konfluensi: {int(score_num)}%)"
        else:
            confluence_badge = ""
        sig_badge = f" • {signal_type.upper()}" if signal_type in ["BUY", "SELL"] else ""

        title_text = f"{display_ticker} • {interval.upper()} Live Chart{sig_badge}{grade_badge}{confluence_badge}"
        fig.suptitle(
            title_text,
            fontsize=12.5,
            weight="bold",
            color=text_color,
            x=0.03,
            y=0.98,
            ha="left",
        )

        # TradingView Engine Watermark di pojok kanan bawah
        fig.text(0.985, 0.012, "TradingView Style Pro Engine", color="#363a45", fontsize=8, ha="right", weight="bold")

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
                pad_inches=0.15,
                dpi=130,
            )
            logger.info(f"Berhasil membuat chart visual TradingView: {output_path}")
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
        5. Terkonfirmasi pola Chart Pattern (Buku 8) atau Break of Structure Trading Alchemist (Buku 9).
        """
        if df.empty or len(df) < 5:
            return False, "Data tidak cukup", ""

        last_row = df.iloc[-1]
        setup_grade = getattr(sig, "setup_grade", None)
        conf_score = getattr(sig, "pdf_confluence_score", 0.0) or 0.0
        signal = getattr(sig, "signal", "HOLD")

        # 1. Sinyal BUY / SELL resmi yang lolos telaah 9 Buku PDF
        if signal in ["BUY", "SELL"] and (conf_score >= 0.50 or setup_grade in ["A+", "A"]):
            grade_str = f"Grade {setup_grade}" if setup_grade else f"{int(conf_score*100)}%"
            return True, f"Sinyal {signal} ({grade_str})", f"Sinyal {signal} terkonfirmasi dengan konfluensi 9 buku PDF."

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

        # 5. Break of Structure (Trading Alchemist) / Chart Pattern
        bos_bull = bool(last_row.get("structure_bos_bullish", 0))
        pat_db = bool(last_row.get("pattern_double_bottom", 0))
        if bos_bull or pat_db:
            return True, "BOS / Chart Pattern Breakout", "Break of structure atau pola grafik pembalikan terdeteksi siap melanjutkan tren."

        # 6. Khusus Sinyal BUY biasa
        if signal == "BUY":
            return True, "Setup Sinyal BUY", "Indikator momentum dan tren memberikan sinyal beli aktif."

        return False, "Netral / Tidak Ada Setup", "Pergerakan harga saat ini sideways / belum memenuhi konfluensi 9 buku."
