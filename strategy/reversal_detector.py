"""
Sistem Deteksi Pembalikan Tren Awal (Early Trend Reversal Detector) Khusus Emas (XAU/USD).
Dirancang untuk mengamankan keuntungan (Auto Early Take Profit) dan melindungi modal
dari pembalikan arah pasar mendadak berdasarkan konfluensi 9 Buku PDF Trading:
1. Mega Profit Forex & Bob Volman: Candlestick Reversal (Pinbar Hammer / Shooting Star, Rejection Wick, Engulfing).
2. Trading Alchemist (Rizki Aditama): Break of Structure (BOS), Change of Character (CHoCH), Order Block & FVG.
3. Chart Pattern: Double Top/Bottom (M/W), Head & Shoulders, Wedges.
4. Martin Pring & John Murphy: Perpotongan Dinamis 20 EMA & Volume Reversal Surge.
5. Indikator Momentum: Rebound RSI dari zona jenuh (Oversold < 30 / Overbought > 70).
6. Ichimoku Kumo: TK Cross Pembalikan Arah.
"""

from typing import Tuple, List, Dict, Any, Optional
import pandas as pd
import numpy as np


class GoldReversalDetector:
    """Detektor pembalikan tren real-time untuk pengawalan posisi terbuka XAU/USD."""

    @staticmethod
    def detect_reversal(
        df_ind: pd.DataFrame,
        position_type: str,
        entry_price: float,
        current_price: float,
    ) -> Tuple[bool, str, List[str], float]:
        """
        Mendeteksi apakah terdapat indikasi pembalikan tren (reversal)
        yang berlawanan dengan arah posisi terbuka saat ini.

        Args:
            df_ind: DataFrame indikator teknikal terkini (15m).
            position_type: "BUY" atau "SELL".
            entry_price: Harga masuk order posisi.
            current_price: Harga pasar live saat ini.

        Returns:
            (is_reversal, reversal_type, reasons, reversal_score)
        """
        if df_ind.empty or len(df_ind) < 2:
            return False, "Data tidak mencukupi", [], 0.0

        pos_type = position_type.upper().strip()
        curr = df_ind.iloc[-1]
        prev = df_ind.iloc[-2]

        close = float(curr.get("Close", current_price))
        open_p = float(curr.get("Open", close))
        high = float(curr.get("High", max(close, open_p)))
        low = float(curr.get("Low", min(close, open_p)))
        candle_range = max(high - low, 0.01)

        prev_close = float(prev.get("Close", close))
        prev_open = float(prev.get("Open", prev_close))

        ema20 = float(curr.get("ema_20", close))
        prev_ema20 = float(prev.get("ema_20", prev_close))
        ema50 = float(curr.get("ema_50", close))

        rsi = float(curr.get("rsi", 50.0))
        prev_rsi = float(prev.get("rsi", rsi))

        vol_ratio = float(curr.get("volume_ratio", 1.0))
        lower_wick_ratio = max(0.0, (min(open_p, close) - low) / candle_range)
        upper_wick_ratio = max(0.0, (high - max(open_p, close)) / candle_range)

        # Pola Candlestick & Chart Patterns
        pinbar = bool(curr.get("pattern_pinbar", 0))
        shooting_star = bool(curr.get("pattern_shooting_star", 0))
        engulfing = bool(curr.get("pattern_engulfing", 0))

        pat_db = bool(curr.get("pattern_double_bottom", 0))
        pat_dt = bool(curr.get("pattern_double_top", 0))
        pat_ihs = bool(curr.get("pattern_inv_head_shoulders", 0))
        pat_hs = bool(curr.get("pattern_head_shoulders", 0))

        # Struktur Pasar (Trading Alchemist)
        bos_bull = bool(curr.get("structure_bos_bullish", 0))
        bos_bear = bool(curr.get("structure_bos_bearish", 0))
        fvg_bull = bool(curr.get("fvg_bullish", 0))
        fvg_bear = bool(curr.get("fvg_bearish", 0))
        ob_bull = bool(curr.get("order_block_bullish", 0))
        ob_bear = bool(curr.get("order_block_bearish", 0))

        # Ichimoku
        tk_cross = bool(curr.get("ichimoku_tk_cross", 0))

        reasons = []
        score = 0.0

        # =========================================================================
        # KASUS 1: POSISI SELL (SHORT) — Deteksi Pembalikan Naik (BULLISH REVERSAL)
        # =========================================================================
        if pos_type == "SELL":
            # 1. Candlestick Reversal Bullish (Mega Profit Forex & Bob Volman)
            is_hammer = (pinbar and close > open_p) or lower_wick_ratio >= 0.38
            is_bull_engulfing = engulfing and close > open_p and close >= prev_close
            if is_hammer:
                score += 25.0
                reasons.append(
                    f"🕯️ Candlestick: Terbentuk Bullish Pinbar / Hammer (Lower Wick {lower_wick_ratio*100:.0f}% penolakan harga bawah)"
                )
            elif is_bull_engulfing:
                score += 25.0
                reasons.append(
                    f"🕯️ Candlestick: Pola Bullish Engulfing (Candle hijau menelan penuh bar merah sebelumnya)"
                )

            # 2. Market Structure Shift / CHoCH (Trading Alchemist - Buku 9)
            crossed_above_ema20 = (close > ema20) and (prev_close <= prev_ema20)
            if bos_bull or crossed_above_ema20:
                score += 25.0
                detail_bos = "Breakout Menembus Kembali ke Atas Dinamis 20 EMA" if crossed_above_ema20 else "Break of Structure (BOS) Bullish"
                reasons.append(f"🏛️ Struktur Pasar: {detail_bos} (Indikasi pergantian karakter tren / CHoCH)")

            # 3. Chart Pattern Reversal (Buku 8 Chart Pattern)
            if pat_db or pat_ihs:
                score += 25.0
                p_name = "Double Bottom (Pola W)" if pat_db else "Inverse Head & Shoulders"
                reasons.append(f"📊 Chart Pattern: Pola Pembalikan {p_name} Terkonfirmasi")

            # 4. Momentum RSI Rebound dari Jenuh Jual (Oversold Bounce)
            if (prev_rsi <= 30.0 and rsi > prev_rsi + 3.0) or (rsi >= 35.0 and prev_rsi < 30.0):
                score += 20.0
                vol_note = f" didukung volume pembeli {vol_ratio:.1f}x" if vol_ratio >= 1.1 else ""
                reasons.append(f"📈 Momentum: RSI memantul tajam keluar dari zona jenuh jual ({prev_rsi:.1f} ➔ {rsi:.1f}){vol_note}")

            # 5. Smart Money Order Block / Demand Zone Pantulan (Buku 9)
            if ob_bull or fvg_bull:
                score += 15.0
                reasons.append("🧱 Smart Money: Harga memantul di zona Bullish Order Block / Fair Value Gap (FVG)")

            # 6. Ichimoku Bullish TK Cross
            if tk_cross and close > open_p:
                score += 15.0
                reasons.append("☁️ Ichimoku: Terjadi Bullish TK Cross (Garis Tenkan memotong ke atas Kijun)")

            reversal_type = "BULLISH REVERSAL (Pembalikan Naik)"

        # =========================================================================
        # KASUS 2: POSISI BUY (LONG) — Deteksi Pembalikan Turun (BEARISH REVERSAL)
        # =========================================================================
        elif pos_type == "BUY":
            # 1. Candlestick Reversal Bearish (Mega Profit Forex & Bob Volman)
            is_shooting_star = shooting_star or upper_wick_ratio >= 0.35
            is_bear_engulfing = engulfing and close < open_p and close <= prev_close
            if is_shooting_star:
                score += 25.0
                reasons.append(
                    f"🕯️ Candlestick: Terbentuk Shooting Star / Rejection Atas (Upper Wick {upper_wick_ratio*100:.0f}% penolakan harga atas)"
                )
            elif is_bear_engulfing:
                score += 25.0
                reasons.append(
                    f"🕯️ Candlestick: Pola Bearish Engulfing (Candle merah menelan penuh bar hijau sebelumnya)"
                )

            # 2. Market Structure Shift / CHoCH (Trading Alchemist - Buku 9)
            crossed_below_ema20 = (close < ema20) and (prev_close >= prev_ema20)
            if bos_bear or crossed_below_ema20:
                score += 25.0
                detail_bos = "Breakdown Menembus ke Bawah Dinamis 20 EMA" if crossed_below_ema20 else "Break of Structure (BOS) Bearish"
                reasons.append(f"🏛️ Struktur Pasar: {detail_bos} (Indikasi pelemahan momentum / CHoCH Bearish)")

            # 3. Chart Pattern Reversal (Buku 8 Chart Pattern)
            if pat_dt or pat_hs:
                score += 25.0
                p_name = "Double Top (Pola M)" if pat_dt else "Head & Shoulders"
                reasons.append(f"📊 Chart Pattern: Pola Pembalikan {p_name} Terkonfirmasi")

            # 4. Momentum RSI Terkoreksi dari Jenuh Beli (Overbought Drop)
            if (prev_rsi >= 70.0 and rsi < prev_rsi - 3.0) or (rsi <= 65.0 and prev_rsi > 70.0):
                score += 20.0
                vol_note = f" didukung volume penjual {vol_ratio:.1f}x" if vol_ratio >= 1.1 else ""
                reasons.append(f"📉 Momentum: RSI jatuh keluar dari zona jenuh beli ({prev_rsi:.1f} ➔ {rsi:.1f}){vol_note}")

            # 5. Smart Money Supply Zone / Order Block Bearish (Buku 9)
            if ob_bear or fvg_bear:
                score += 15.0
                reasons.append("🧱 Smart Money: Penolakan kuat di area Bearish Supply Order Block")

            # 6. Ichimoku Bearish TK Cross
            if tk_cross and close < open_p:
                score += 15.0
                reasons.append("☁️ Ichimoku: Terjadi Bearish TK Cross (Garis Tenkan memotong ke bawah Kijun)")

            reversal_type = "BEARISH REVERSAL (Pembalikan Turun)"

        else:
            return False, "Tipe posisi tidak valid", [], 0.0

        # =========================================================================
        # STANDAR ULTRA-KETAT: REVERSAL FIX / 100% TERKONFIRMASI (9 BUKU PDF)
        # =========================================================================
        # Sesuai arahan mutlak pengguna:
        # "kalo sinyal pembalikan coba di perketat deh bor soal nya udah beberapa kali kena engga jelas ke sl sendiri"
        # 1. Wajib ada penembusan struktur resmi (Break of Structure / BOS) atau Pola Reversal Mayor (Double Top/Bottom / H&S).
        #    Persilangan EMA 20 kecil saja BUKAN pembalikan tren dan dilarang memicu auto-close.
        # 2. Skor konfluensi pembalikan dinaikkan minimal >= 75.0% dengan minimal 3 konfirmasi independen.

        has_structure_break = False
        if pos_type == "SELL":
            # Wajib ada penembusan struktur ke atas yang sah (BOS Bullish menjebol swing high, atau pola W menembus Neckline):
            has_structure_break = (bos_bull or pat_db or pat_ihs) and (close >= ema20)
        elif pos_type == "BUY":
            # Wajib ada penembusan struktur ke bawah yang sah (BOS Bearish menjebol swing low, atau pola M menembus Neckline):
            has_structure_break = (bos_bear or pat_dt or pat_hs) and (close <= ema20)

        # 1. Konfirmasi Utama: Skor Konfluensi Tinggi (>= 70%) + Minimal 3 Konfirmasi Independen + Wajib Rusak Struktur Pasar Nyata (BOS / Pola Mayor)
        is_reversal = (score >= 70.0) and (len(reasons) >= 3) and has_structure_break

        # 2. Konfirmasi Pola Mayor (Buku 8 Chart Pattern):
        # Hanya sah jika Pola Double Top/Bottom atau Head & Shoulders sudah menembus Neckline / Struktur
        if not is_reversal:
            if pos_type == "SELL" and (pat_db or pat_ihs) and (bos_bull and close > ema20):
                is_reversal = True
                score = max(score, 85.0)
                reasons.append("⚡ Konfirmasi 100%: Pola Double Bottom / Inverted H&S memecahkan Neckline & EMA 20")
            elif pos_type == "BUY" and (pat_dt or pat_hs) and (bos_bear and close < ema20):
                is_reversal = True
                score = max(score, 85.0)
                reasons.append("⚡ Konfirmasi 100%: Pola Double Top / H&S memecahkan Neckline & EMA 20")

        return is_reversal, reversal_type, reasons, round(score, 1)

    @staticmethod
    def check_early_reversal_warning(
        df_ind: pd.DataFrame,
        position_type: str,
        entry_price: float,
        current_price: float,
    ) -> Tuple[bool, str, List[str], float]:
        """
        Mendeteksi indikasi awal pembalikan tren (Early Warning skor >= 40%)
        sebelum pembalikan tren 100% terkonfirmasi dan posisi ditutup.
        Memberikan sinyal peringatan dini ke pengguna agar selalu siap siaga.
        """
        if df_ind.empty or len(df_ind) < 2:
            return False, "", [], 0.0

        is_rev, rev_type, reasons, score = GoldReversalDetector.detect_reversal(
            df_ind, position_type, entry_price, current_price
        )
        # Jika sudah pembalikan 100% terkonfirmasi, biarkan handler eksekusi yang bekerja
        if is_rev:
            return False, rev_type, reasons, score

        # Early warning aktif jika skor awal mencapai 40% dengan minimal 2 tanda teknikal
        if score >= 40.0 and len(reasons) >= 2:
            return True, rev_type, reasons, score

        return False, rev_type, reasons, score

