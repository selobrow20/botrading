"""
Modul Mesin Prediksi Pergerakan XAU/USD (Gold) 10 Menit Sebelum High-Impact News:
1. FOMC (Suku Bunga The Fed & Konferensi Pers)
2. CPI (Consumer Price Index / Data Inflasi AS)
3. NFP (Non-Farm Payrolls & Unemployment Rate)
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.patches import Rectangle

from config.settings import setup_logger
from data.fetcher import DataFetcher
from indicators.technical import TechnicalIndicators

logger = setup_logger("news_predictor")

CHARTS_DIR = Path("data/charts")
CHARTS_DIR.mkdir(parents=True, exist_ok=True)


class NewsPredictor:
    """Mesin peramal skenario dampak berita ekonomi terhadap harga Emas (XAU/USD)."""

    VOLATILITY_PROFILES = {
        "NFP": {
            "name": "Non-Farm Payrolls & Unemployment Rate",
            "volatility_pct": 1.5,
            "tp1_pct": 0.8,
            "tp2_pct": 1.8,
            "breakout_offset_pct": 0.35,
            "sl_offset_pct": 0.25,
            "description": "Data tenaga kerja AS. NFP rendah = USD anjlok & Gold terbang. NFP tinggi = USD menguat & Gold jatuh.",
        },
        "CPI": {
            "name": "Consumer Price Index (Inflasi AS)",
            "volatility_pct": 2.0,
            "tp1_pct": 1.0,
            "tp2_pct": 2.2,
            "breakout_offset_pct": 0.40,
            "sl_offset_pct": 0.30,
            "description": "Indikator utama inflasi The Fed. CPI rendah = Peluang cut rate naik (Gold Bullish). CPI tinggi = Inflasi panas (Gold Bearish).",
        },
        "FOMC": {
            "name": "FOMC Statement & Fed Rate Decision",
            "volatility_pct": 2.5,
            "tp1_pct": 1.2,
            "tp2_pct": 2.8,
            "breakout_offset_pct": 0.45,
            "sl_offset_pct": 0.35,
            "description": "Kebijakan moneter bank sentral AS. Pernyataan dovish = Gold reli kencang. Pernyataan hawkish = Gold terkoreksi tajam.",
        },
    }

    @classmethod
    def analyze_pre_news(
        cls,
        news_event: Dict[str, Any],
        live_gold_price: Optional[float] = None,
        df_gold: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Melakukan kalkulasi skenario 2 arah dan level teknikal 10 menit sebelum news dirilis.
        """
        news_type = news_event.get("news_type", "OTHER")
        profile = cls.VOLATILITY_PROFILES.get(news_type, cls.VOLATILITY_PROFILES["CPI"])

        # Ambil harga terkini emas jika belum di-supply
        price = live_gold_price
        if not price or price <= 0:
            try:
                fetcher = DataFetcher()
                df_fetch = fetcher.get_data("XAUUSD", interval="15m", period="5d", force_fetch=True)
                if not df_fetch.empty:
                    price = float(df_fetch["Close"].iloc[-1])
                    df_gold = df_fetch
            except Exception:
                price = 4300.0  # Fallback harga nominal

        # Kalkulasi Level Skenario Bullish (USD Lemah -> Gold Terbang)
        bullish_tp1 = round(price * (1.0 + (profile["tp1_pct"] / 100.0)), 2)
        bullish_tp2 = round(price * (1.0 + (profile["tp2_pct"] / 100.0)), 2)

        # Kalkulasi Level Skenario Bearish (USD Kuat -> Gold Anjlok)
        bearish_tp1 = round(price * (1.0 - (profile["tp1_pct"] / 100.0)), 2)
        bearish_tp2 = round(price * (1.0 - (profile["tp2_pct"] / 100.0)), 2)

        # Kalkulasi Pending Order Straddle (Breakout Range Pre-News)
        buy_stop_entry = round(price * (1.0 + (profile["breakout_offset_pct"] / 100.0)), 2)
        buy_stop_sl = round(price * (1.0 - (profile["sl_offset_pct"] / 100.0)), 2)

        sell_stop_entry = round(price * (1.0 - (profile["breakout_offset_pct"] / 100.0)), 2)
        sell_stop_sl = round(price * (1.0 + (profile["sl_offset_pct"] / 100.0)), 2)

        expected_vol_dollars = round(price * (profile["volatility_pct"] / 100.0), 2)

        return {
            "news_title": news_event.get("title", profile["name"]),
            "news_type": news_type,
            "date_wib": news_event.get("date_wib", "-"),
            "forecast": news_event.get("forecast", "-"),
            "previous": news_event.get("previous", "-"),
            "current_price": price,
            "expected_volatility_pct": profile["volatility_pct"],
            "expected_volatility_dollars": expected_vol_dollars,
            "description": profile["description"],
            "bullish_scenario": {
                "label": "Bullish Pump (USD Melemah)",
                "condition": "Jika data actual < forecast (Inflasi/NFP melambat)",
                "target_tp1": bullish_tp1,
                "target_tp2": bullish_tp2,
                "gain_tp1_pct": profile["tp1_pct"],
                "gain_tp2_pct": profile["tp2_pct"],
            },
            "bearish_scenario": {
                "label": "Bearish Dump (USD Menguat)",
                "condition": "Jika data actual > forecast (Ekonomi AS terlalu panas)",
                "target_tp1": bearish_tp1,
                "target_tp2": bearish_tp2,
                "loss_tp1_pct": profile["tp1_pct"],
                "loss_tp2_pct": profile["tp2_pct"],
            },
            "straddle_plan": {
                "buy_stop": buy_stop_entry,
                "buy_sl": buy_stop_sl,
                "sell_stop": sell_stop_entry,
                "sell_sl": sell_stop_sl,
            },
        }

    @classmethod
    def generate_pre_news_chart(
        cls,
        analysis: Dict[str, Any],
        df: Any,
        num_candles: int = 40,
    ) -> Optional[str]:
        """
        Membuat grafik candlestick pre-news bertema gelap dengan penanda zona Breakout & Breakdown.
        """
        if df is None or len(df) < 10:
            return None

        df_plot = df.copy().tail(min(num_candles, len(df)))
        n_bars = len(df_plot)
        price = analysis["current_price"]
        plan = analysis["straddle_plan"]
        bull = analysis["bullish_scenario"]
        bear = analysis["bearish_scenario"]
        news_type = analysis["news_type"]

        fig, ax = plt.subplots(figsize=(11, 7), dpi=120)
        fig.patch.set_facecolor("#0f172a")
        ax.set_facecolor("#1e293b")
        ax.grid(True, linestyle="--", linewidth=0.5, color="#334155", alpha=0.6)
        ax.tick_params(colors="#94a3b8", labelsize=9)
        for spine in ax.spines.values():
            spine.set_color("#334155")

        # Gambar Candle Lilin
        body_width = 0.65
        for i in range(n_bars):
            row = df_plot.iloc[i]
            c_open = float(row["Open"])
            c_high = float(row["High"])
            c_low = float(row["Low"])
            c_close = float(row["Close"])
            is_up = c_close >= c_open
            color = "#10b981" if is_up else "#ef4444"

            ax.vlines(x=i, ymin=c_low, ymax=c_high, color=color, linewidth=1.2, zorder=2)
            b_bottom = min(c_open, c_close)
            b_height = max(abs(c_close - c_open), (c_high - c_low) * 0.01)
            rect = Rectangle((i - body_width/2.0, b_bottom), body_width, b_height, facecolor=color, edgecolor=color, zorder=3)
            ax.add_patch(rect)

        # Garis Harga Terkini (Pivot Pre-News)
        ax.axhline(price, color="#fbbf24", linestyle="-", linewidth=1.5, label=f"Pre-News Price: ${price:,.2f}", zorder=4)

        # Zona Bullish Pump Target (Hijau)
        ax.axhline(bull["target_tp1"], color="#34d399", linestyle="--", linewidth=1.2, label=f"Bullish TP1: ${bull['target_tp1']:,.2f} (+{bull['gain_tp1_pct']}%)", zorder=4)
        ax.axhline(bull["target_tp2"], color="#059669", linestyle=":", linewidth=1.2, label=f"Bullish TP2 (Max): ${bull['target_tp2']:,.2f} (+{bull['gain_tp2_pct']}%)", zorder=4)

        # Zona Bearish Dump Target (Merah)
        ax.axhline(bear["target_tp1"], color="#f87171", linestyle="--", linewidth=1.2, label=f"Bearish TP1: ${bear['target_tp1']:,.2f} (-{bear['loss_tp1_pct']}%)", zorder=4)
        ax.axhline(bear["target_tp2"], color="#dc2626", linestyle=":", linewidth=1.2, label=f"Bearish TP2 (Max): ${bear['target_tp2']:,.2f} (-{bear['loss_tp2_pct']}%)", zorder=4)

        # Shaded Pre-News Range
        ax.axhspan(plan["sell_stop"], plan["buy_stop"], color="#475569", alpha=0.25, label=f"Straddle Range (±${round(price*0.0035,1)})")

        ax.set_xlim(-1, n_bars + 3)
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("$%.2f"))
        ax.legend(loc="upper left", facecolor="#0f172a", edgecolor="#334155", fontsize=8, labelcolor="#f8fafc")

        title = f"XAU/USD PRE-NEWS SETUP: {news_type} (10 MENIT SEBELUM RILIS)"
        fig.suptitle(title, fontsize=12.5, weight="bold", color="#f8fafc", x=0.03, y=0.97, ha="left")

        ts_slug = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"pre_news_{news_type}_{ts_slug}.png"
        output_path = str(CHARTS_DIR / filename)

        try:
            plt.savefig(output_path, facecolor=fig.get_facecolor(), edgecolor="none", bbox_inches="tight", dpi=120)
            return output_path
        except Exception as e:
            logger.error(f"Gagal simpan pre-news chart: {e}")
            return None
        finally:
            plt.close(fig)
