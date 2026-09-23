"""
Modul Mesin Prediksi Pergerakan XAU/USD (Gold) 10 Menit Sebelum High-Impact News:
1. FOMC (Suku Bunga The Fed & Konferensi Pers)
2. CPI (Consumer Price Index / Data Inflasi AS)
3. NFP (Non-Farm Payrolls & Unemployment Rate)

Dilengkapi Mesin Konfluensi Rekomendasi Arah (BUY / SELL):
- Fundamental Bias dari Web (Forex Factory & Investing.com: Forecast vs Previous)
- Teknikal Bias dari Materi PDF (Fibonacci 99% Golden Pocket, Ichimoku Cloud, & Bob Volman Price Action)
"""

import os
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path

import pandas as pd
import numpy as np
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


def _parse_num(val_str: Optional[str]) -> Optional[float]:
    """Mengekstrak nilai numerik desimal dari representasi string forecast/previous."""
    if not val_str:
        return None
    s = str(val_str).strip()
    mult = 1.0
    if "k" in s.lower():
        mult = 1000.0
    elif "m" in s.lower():
        mult = 1000000.0
    cleaned = re.sub(r"[^\d.-]", "", s)
    try:
        return float(cleaned) * mult
    except Exception:
        return None


class NewsPredictor:
    """Mesin peramal arah dampak berita ekonomi terhadap harga Emas (XAU/USD)."""

    VOLATILITY_PROFILES = {
        "NFP": {
            "name": "Non-Farm Payrolls & Unemployment Rate",
            "volatility_pct": 1.5,
            "tp1_pct": 0.8,
            "tp2_pct": 1.8,
            "breakout_offset_pct": 0.35,
            "sl_offset_pct": 0.30,
            "description": "Data tenaga kerja AS. NFP rendah / pengangguran tinggi = USD anjlok & Gold terbang. NFP tinggi = USD menguat & Gold tertekan.",
        },
        "CPI": {
            "name": "Consumer Price Index (Inflasi AS)",
            "volatility_pct": 2.0,
            "tp1_pct": 1.0,
            "tp2_pct": 2.2,
            "breakout_offset_pct": 0.40,
            "sl_offset_pct": 0.35,
            "description": "Indikator utama inflasi The Fed. CPI rendah = Peluang cut rate naik (Gold Bullish). CPI tinggi = Inflasi panas (Gold Bearish).",
        },
        "FOMC": {
            "name": "FOMC Statement & Fed Rate Decision",
            "volatility_pct": 2.5,
            "tp1_pct": 1.2,
            "tp2_pct": 2.8,
            "breakout_offset_pct": 0.45,
            "sl_offset_pct": 0.40,
            "description": "Kebijakan moneter bank sentral AS. Pernyataan dovish / cut rate = Gold reli kencang. Pernyataan hawkish = Gold terkoreksi tajam.",
        },
    }

    @classmethod
    def calculate_fundamental_bias(
        cls,
        news_type: str,
        title: str = "",
        forecast_str: str = "",
        previous_str: str = "",
    ) -> Dict[str, Any]:
        """
        Menganalisis deviasi konsensus analis (Forecast vs Previous) dari Forex Factory / Investing.com.
        Menghasilkan skor fundamental (-40 s/d +40) terhadap pergerakan Gold (XAU/USD).
        """
        fc = _parse_num(forecast_str)
        pv = _parse_num(previous_str)
        t_lower = (title or "").lower()

        # 1. CPI (Data Inflasi AS)
        if news_type == "CPI":
            if fc is not None and pv is not None:
                if fc < pv:
                    return {
                        "score": 35,
                        "sentiment": "BULLISH",
                        "reason": f"Konsensus CPI ({forecast_str}) melambat dibanding rilis lalu ({previous_str}). Inflasi mendingin -> Ekspektasi pemangkasan suku bunga Fed meningkat -> USD melemah -> Gold Bullish.",
                    }
                elif fc > pv:
                    return {
                        "score": -35,
                        "sentiment": "BEARISH",
                        "reason": f"Konsensus CPI ({forecast_str}) naik dari periode lalu ({previous_str}). Inflasi masih memanas -> The Fed berpotensi hawkish -> USD menguat -> Gold Bearish.",
                    }
                else:
                    return {
                        "score": 0,
                        "sentiment": "NEUTRAL",
                        "reason": f"Konsensus CPI ({forecast_str}) setara dengan periode sebelumnya ({previous_str}). Pasar menunggu kejutan data aktual.",
                    }
            return {
                "score": 10,
                "sentiment": "SLIGHTLY_BULLISH",
                "reason": "Tren inflasi jangka menengah AS condong melandai, memberi angin segar bagi Emas.",
            }

        # 2. NFP & Unemployment Rate (Tenaga Kerja AS)
        elif news_type == "NFP":
            is_unemployment = "unemployment" in t_lower
            if fc is not None and pv is not None:
                if is_unemployment:
                    # Tingkat pengangguran tinggi = ekonomi lesu = USD lemah = Gold naik
                    if fc > pv:
                        return {
                            "score": 35,
                            "sentiment": "BULLISH",
                            "reason": f"Proyeksi Unemployment Rate naik ke {forecast_str} (prev {previous_str}). Sinyal pelemahan ekonomi AS -> USD tertekan -> Gold Bullish.",
                        }
                    elif fc < pv:
                        return {
                            "score": -35,
                            "sentiment": "BEARISH",
                            "reason": f"Proyeksi Unemployment Rate membaik ke {forecast_str} (prev {previous_str}). Pasar tenaga kerja kuat -> USD menguat -> Gold Bearish.",
                        }
                else:
                    # Standar NFP (penambahan tenaga kerja)
                    if fc < pv:
                        return {
                            "score": 35,
                            "sentiment": "BULLISH",
                            "reason": f"Proyeksi penambahan lapangan kerja NFP ({forecast_str}) melambat dari periode lalu ({previous_str}) -> USD melemah -> Gold Bullish.",
                        }
                    elif fc > pv:
                        return {
                            "score": -35,
                            "sentiment": "BEARISH",
                            "reason": f"Proyeksi NFP ({forecast_str}) melampaui rilis sebelumnya ({previous_str}) -> Pasar tenaga kerja solid -> USD rally -> Gold Bearish.",
                        }
            return {
                "score": 0,
                "sentiment": "NEUTRAL",
                "reason": "Konsensus tenaga kerja NFP seimbang, pergerakan awal akan sangat reaktif terhadap rilis data aktual.",
            }

        # 3. FOMC (Suku Bunga & Kebijakan The Fed)
        elif news_type == "FOMC":
            if fc is not None and pv is not None:
                if fc < pv:
                    return {
                        "score": 40,
                        "sentiment": "STRONG_BULLISH",
                        "reason": f"Ekspektasi pemotongan suku bunga Fed (Rate Cut) dari {previous_str} ke {forecast_str} -> Likuiditas melimpah & yield obligasi AS anjlok -> Strong Gold BUY.",
                    }
                elif fc > pv:
                    return {
                        "score": -40,
                        "sentiment": "STRONG_BEARISH",
                        "reason": f"Ekspektasi kenaikan suku bunga Fed (Rate Hike) ke {forecast_str} -> Dolar AS melonjak tinggi -> Strong Gold SELL.",
                    }
            return {
                "score": 15,
                "sentiment": "BULLISH",
                "reason": "The Fed berada dalam fase siklus pemangkasan/dovish, sentimen makro global condong menguntungkan Emas.",
            }

        return {"score": 0, "sentiment": "NEUTRAL", "reason": "Data fundamental netral."}

    @classmethod
    def calculate_pdf_technical_confluence(cls, df: Any) -> Dict[str, Any]:
        """
        Menganalisis live feed Gold dengan aturan teknikal dari materi PDF:
        - Fibonacci 99% Retracement (Golden Pocket: 50% - 61.8%)
        - Ichimoku Cloud (Awan Kumo, Tenkan/Kijun cross)
        - Price Action Bob Volman (20 EMA Pullback & Volatility Buildup)
        - RSI Momentum & Trend EMA
        """
        if df is None or len(df) < 15:
            return {
                "score": 0,
                "sentiment": "NEUTRAL",
                "reasons": ["Data candle teknikal tidak mencukupi untuk evaluasi PDF."],
                "fib_levels": {},
            }

        df_ind = TechnicalIndicators.add_all_indicators(df)
        last = df_ind.iloc[-1]
        close = float(last["Close"])
        score = 0
        reasons: List[str] = []

        # 1. Fibonacci 99% Profit (Golden Pocket 50% - 61.8%)
        fib_500 = float(last.get("fib_500", close))
        fib_618 = float(last.get("fib_618", close))
        fib_382 = float(last.get("fib_382", close))
        fib_levels = {"382": round(fib_382, 2), "500": round(fib_500, 2), "618": round(fib_618, 2)}

        # Cek apakah harga di atas Golden Pocket atau sedang mengujinya
        if close >= fib_500 and close >= fib_618:
            score += 20
            reasons.append(f"Fibonacci 99%: Harga (${close:,.2f}) bertahan kokoh di atas Golden Pocket 50%-61.8% (${min(fib_500, fib_618):,.2f}-${max(fib_500, fib_618):,.2f}) (Bullish Confluence).")
        elif last.get("fib_in_golden_zone", 0) == 1.0 or (close >= min(fib_500, fib_618) * 0.998):
            score += 25
            reasons.append(f"Fibonacci 99%: Harga sedang menguji area pantulan kuat Golden Pocket (${min(fib_500, fib_618):,.2f}-${max(fib_500, fib_618):,.2f}), zona pantulan beli ideal.")
        else:
            score -= 20
            reasons.append(f"Fibonacci 99%: Harga tertekan di bawah batas kritis 61.8% (${fib_618:,.2f}), struktur teknikal rentan breakdown.")

        # 2. Ichimoku Cloud (Ichimoku - Forex.pdf)
        above_cloud = int(last.get("ichimoku_above_cloud", 0))
        cloud_green = int(last.get("ichimoku_cloud_green", 0))
        tk_cross = int(last.get("ichimoku_tk_cross", 0))

        if above_cloud == 1:
            bonus = 5 if cloud_green == 1 else 0
            score += 20 + bonus
            reasons.append(f"Ichimoku Kumo: Candlestick berada di atas Awan Kumo {'(Awan Hijau)' if cloud_green else ''}, tren mayoritas Bullish.")
        else:
            score -= 20
            reasons.append("Ichimoku Kumo: Candlestick berada di bawah Awan Kumo, resisten awan membatasi kenaikan.")

        if tk_cross == 1:
            score += 5
            reasons.append("Ichimoku: Tenkan-sen berada di atas Kijun-sen (Golden Cross aktif).")

        # 3. Bob Volman Price Action (Under Standing Price Action.pdf)
        volman_pullback = int(last.get("volman_pullback", 0))
        volman_buildup = int(last.get("volman_buildup", 0))

        if volman_pullback == 1:
            score += 15
            reasons.append("Price Action Bob Volman: Pullback teruji di area 20 EMA terkonfirmasi.")
        if volman_buildup == 1:
            score += 10
            reasons.append("Price Action Bob Volman: Terdeteksi kompresi candle (buildup), energi breakout siap meledak.")

        # 4. RSI Momentum
        rsi = float(last.get("RSI_14", 50.0))
        if 45.0 <= rsi <= 65.0:
            score += 10
            reasons.append(f"RSI Momentum ({rsi:.1f}): Berada di zona ekspansi sehat.")
        elif rsi < 35.0:
            score += 15
            reasons.append(f"RSI Oversold ({rsi:.1f}): Berada di area jenuh jual, peluang technical bounce tinggi.")
        elif rsi > 70.0:
            score -= 10
            reasons.append(f"RSI Overbought ({rsi:.1f}): Jenuh beli, waspada koreksi sebelum rilis news.")

        # Tentukan sentimen teknikal
        if score >= 30:
            sentiment = "STRONG_BULLISH"
        elif score >= 10:
            sentiment = "BULLISH"
        elif score <= -30:
            sentiment = "STRONG_BEARISH"
        elif score <= -10:
            sentiment = "BEARISH"
        else:
            sentiment = "NEUTRAL"

        return {
            "score": score,
            "sentiment": sentiment,
            "reasons": reasons,
            "fib_levels": fib_levels,
            "rsi": rsi,
            "above_cloud": above_cloud,
        }

    @classmethod
    def analyze_pre_news(
        cls,
        news_event: Dict[str, Any],
        live_gold_price: Optional[float] = None,
        df_gold: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Melakukan sintesis komprehensif prediksi arah (BUY / SELL):
        1. Analisis Fundamental Bias dari konsensus Web (Forex Factory / Investing.com)
        2. Analisis Teknikal Bias dari materi PDF (Fibonacci 99%, Ichimoku, Bob Volman)
        3. Menentukan Rekomendasi Utama (BUY / SELL) beserta skor probabilitas % dan setup level eksekusi.
        """
        news_type = news_event.get("news_type", "OTHER")
        profile = cls.VOLATILITY_PROFILES.get(news_type, cls.VOLATILITY_PROFILES["CPI"])
        title = news_event.get("title", profile["name"])
        forecast = news_event.get("forecast", "-")
        previous = news_event.get("previous", "-")

        # Ambil live data emas jika belum di-supply
        price = live_gold_price
        if df_gold is None:
            try:
                fetcher = DataFetcher()
                df_fetch = fetcher.get_data("XAUUSD", interval="15m", period="5d", force_fetch=False)
                if not df_fetch.empty:
                    df_gold = df_fetch
                    if not price or price <= 0:
                        price = float(df_fetch["Close"].iloc[-1])
            except Exception:
                pass

        if not price or price <= 0:
            price = 4300.0

        # 1. Hitung Pilar Fundamental (Web Data)
        fund_bias = cls.calculate_fundamental_bias(
            news_type=news_type,
            title=title,
            forecast_str=forecast,
            previous_str=previous,
        )

        # 2. Hitung Pilar Teknikal (Materi PDF)
        tech_bias = cls.calculate_pdf_technical_confluence(df_gold)

        # 3. Hitung Skor Konfluensi Gabungan (-100 s/d +100)
        total_confluence = fund_bias["score"] + tech_bias["score"]
        total_confluence = max(-100, min(100, total_confluence))

        # Tentukan Rekomendasi Utama & Keyakinan
        if total_confluence >= 40:
            rec = "STRONG BUY"
            bias = "BULLISH"
            conf = min(92, 50 + int(abs(total_confluence) * 0.45))
        elif total_confluence >= 15:
            rec = "BUY"
            bias = "BULLISH"
            conf = min(82, 50 + int(abs(total_confluence) * 0.45))
        elif total_confluence <= -40:
            rec = "STRONG SELL"
            bias = "BEARISH"
            conf = min(92, 50 + int(abs(total_confluence) * 0.45))
        elif total_confluence <= -15:
            rec = "SELL"
            bias = "BEARISH"
            conf = min(82, 50 + int(abs(total_confluence) * 0.45))
        else:
            rec = "WAIT / STRADDLE"
            bias = "NEUTRAL"
            conf = 55

        # Level Skenario Bullish (USD Lemah -> Gold Terbang)
        bullish_tp1 = round(price * (1.0 + (profile["tp1_pct"] / 100.0)), 2)
        bullish_tp2 = round(price * (1.0 + (profile["tp2_pct"] / 100.0)), 2)
        bullish_sl = round(price * (1.0 - (profile["sl_offset_pct"] / 100.0)), 2)

        # Level Skenario Bearish (USD Kuat -> Gold Anjlok)
        bearish_tp1 = round(price * (1.0 - (profile["tp1_pct"] / 100.0)), 2)
        bearish_tp2 = round(price * (1.0 - (profile["tp2_pct"] / 100.0)), 2)
        bearish_sl = round(price * (1.0 + (profile["sl_offset_pct"] / 100.0)), 2)

        # Pending Order Straddle (Breakout Range Pre-News)
        buy_stop_entry = round(price * (1.0 + (profile["breakout_offset_pct"] / 100.0)), 2)
        buy_stop_sl = round(price * (1.0 - (profile["sl_offset_pct"] / 100.0)), 2)
        sell_stop_entry = round(price * (1.0 - (profile["breakout_offset_pct"] / 100.0)), 2)
        sell_stop_sl = round(price * (1.0 + (profile["sl_offset_pct"] / 100.0)), 2)

        # Setup Eksekusi Trading Rekomendasi Utama
        if "BUY" in rec:
            trade_action = "BUY"
            trade_entry = price
            trade_tp1 = bullish_tp1
            trade_tp2 = bullish_tp2
            trade_sl = bullish_sl
            risk = abs(trade_entry - trade_sl)
            reward = abs(trade_tp1 - trade_entry)
            rrr = round(reward / risk, 1) if risk > 0 else 2.0
        elif "SELL" in rec:
            trade_action = "SELL"
            trade_entry = price
            trade_tp1 = bearish_tp1
            trade_tp2 = bearish_tp2
            trade_sl = bearish_sl
            risk = abs(trade_sl - trade_entry)
            reward = abs(trade_entry - trade_tp1)
            rrr = round(reward / risk, 1) if risk > 0 else 2.0
        else:
            trade_action = "STRADDLE"
            trade_entry = price
            trade_tp1 = bullish_tp1
            trade_tp2 = bearish_tp1
            trade_sl = buy_stop_sl
            rrr = 1.5

        expected_vol_dollars = round(price * (profile["volatility_pct"] / 100.0), 2)

        return {
            "news_title": title,
            "news_type": news_type,
            "date_wib": news_event.get("date_wib", "-"),
            "forecast": forecast,
            "previous": previous,
            "current_price": price,
            "expected_volatility_pct": profile["volatility_pct"],
            "expected_volatility_dollars": expected_vol_dollars,
            "description": profile["description"],
            "primary_recommendation": rec,
            "recommendation_bias": bias,
            "confidence_pct": conf,
            "confluence_score": total_confluence,
            "fundamental_bias": fund_bias,
            "technical_bias": tech_bias,
            "trade_setup": {
                "action": trade_action,
                "entry_price": trade_entry,
                "tp1": trade_tp1,
                "tp2": trade_tp2,
                "sl": trade_sl,
                "risk_reward_ratio": rrr,
            },
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
        Membuat grafik candlestick pre-news bertema gelap dengan penanda:
        - Fibonacci Golden Pocket (50% - 61.8%)
        - Banner Rekomendasi Utama (BUY / SELL) beserta Target TP1/TP2 & SL
        - Zona Breakout / Breakdown
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
        rec = analysis.get("primary_recommendation", "BUY")
        conf = analysis.get("confidence_pct", 75)
        setup = analysis.get("trade_setup", {})
        fibs = analysis.get("technical_bias", {}).get("fib_levels", {})

        fig, ax = plt.subplots(figsize=(11.5, 7.2), dpi=120)
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

        # Plot Fibonacci Golden Pocket (50% - 61.8%) jika tersedia
        fib_500 = fibs.get("500")
        fib_618 = fibs.get("618")
        if fib_500 and fib_618:
            low_fib = min(fib_500, fib_618)
            high_fib = max(fib_500, fib_618)
            ax.axhspan(low_fib, high_fib, color="#d97706", alpha=0.18, zorder=1, label=f"Fib Golden Pocket 50%-61.8% (${low_fib:,.1f}-${high_fib:,.1f})")
            ax.axhline(fib_618, color="#f59e0b", linestyle="--", linewidth=1.0, alpha=0.7)

        # Garis Harga Terkini (Pivot Pre-News)
        ax.axhline(price, color="#fbbf24", linestyle="-", linewidth=1.5, label=f"Live Pivot: ${price:,.2f}", zorder=4)

        # Garis Rekomendasi Utama (BUY atau SELL)
        if "BUY" in rec:
            ax.axhline(setup.get("tp1", bull["target_tp1"]), color="#10b981", linestyle="--", linewidth=1.4, label=f"Target TP1: ${setup.get('tp1', bull['target_tp1']):,.2f} (+{bull['gain_tp1_pct']}%)", zorder=4)
            ax.axhline(setup.get("tp2", bull["target_tp2"]), color="#059669", linestyle=":", linewidth=1.4, label=f"Target TP2 (Runner): ${setup.get('tp2', bull['target_tp2']):,.2f} (+{bull['gain_tp2_pct']}%)", zorder=4)
            ax.axhline(setup.get("sl", bull["target_tp1"]), color="#ef4444", linestyle="-.", linewidth=1.2, label=f"Stop Loss: ${setup.get('sl', price*0.997):,.2f}", zorder=4)
        else:
            ax.axhline(setup.get("tp1", bear["target_tp1"]), color="#f87171", linestyle="--", linewidth=1.4, label=f"Target TP1: ${setup.get('tp1', bear['target_tp1']):,.2f} (-{bear['loss_tp1_pct']}%)", zorder=4)
            ax.axhline(setup.get("tp2", bear["target_tp2"]), color="#dc2626", linestyle=":", linewidth=1.4, label=f"Target TP2 (Runner): ${setup.get('tp2', bear['target_tp2']):,.2f} (-{bear['loss_tp2_pct']}%)", zorder=4)
            ax.axhline(setup.get("sl", bear["target_tp1"]), color="#ef4444", linestyle="-.", linewidth=1.2, label=f"Stop Loss: ${setup.get('sl', price*1.003):,.2f}", zorder=4)

        # Shaded Pre-News Straddle Range
        ax.axhspan(plan["sell_stop"], plan["buy_stop"], color="#475569", alpha=0.20, label=f"Straddle Range (±${round(price*0.0035,1)})")

        ax.set_xlim(-1, n_bars + 3)
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("$%.2f"))
        ax.legend(loc="upper left", facecolor="#0f172a", edgecolor="#334155", fontsize=8, labelcolor="#f8fafc")

        # Judul Utama & Banner Rekomendasi
        badge_color = "#10b981" if "BUY" in rec else "#ef4444"
        title = f"XAU/USD PRE-NEWS PREDIKSI: {news_type} (T-10 MENIT)"
        rec_banner = f"SARAN UTAMA: {rec} (Probabilitas {conf}%) | Entry: ${setup.get('entry_price', price):,.2f} | TP1: ${setup.get('tp1', 0):,.2f} | SL: ${setup.get('sl', 0):,.2f}"

        fig.suptitle(title, fontsize=12.5, weight="bold", color="#f8fafc", x=0.03, y=0.97, ha="left")
        ax.text(
            0.03, 0.91, rec_banner,
            transform=fig.transFigure,
            fontsize=10.0,
            weight="bold",
            color=badge_color,
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#1e293b", edgecolor=badge_color, linewidth=1.2)
        )

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
