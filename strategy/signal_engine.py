from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, time
from zoneinfo import ZoneInfo
import pandas as pd
from config.settings import load_config, setup_logger
from indicators.technical import TechnicalIndicators
from strategy.rules import Strategy, RuleCondition, DEFAULT_STRATEGY, get_strategy, register_strategy

logger = setup_logger("signal_engine")


@dataclass
class SignalResult:
    """Hasil evaluasi sinyal trading untuk satu saham."""
    ticker: str
    strategy_name: str
    signal: str           # 'BUY', 'SELL', 'HOLD'
    price: float
    candle_time: str
    reasons: List[str] = field(default_factory=list)
    indicators_snapshot: Dict[str, float] = field(default_factory=dict)
    # Target Profit & Stop Loss untuk Trading Harian
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    # Validasi & Telaah 9 Buku PDF untuk Sinyal Masuk (BUY / SELL)
    pdf_confluence_score: float = 0.0
    setup_grade: str = ""
    pdf_confluence_details: List[str] = field(default_factory=list)
    market_direction_prediction: str = ""
    market_regime: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "strategy_name": self.strategy_name,
            "signal": self.signal,
            "price": self.price,
            "candle_time": self.candle_time,
            "reasons": self.reasons,
            "indicators": self.indicators_snapshot,
            "take_profit_price": self.take_profit_price,
            "stop_loss_price": self.stop_loss_price,
            "risk_reward_ratio": self.risk_reward_ratio,
            "pdf_confluence_score": self.pdf_confluence_score,
            "setup_grade": self.setup_grade,
            "pdf_confluence_details": self.pdf_confluence_details,
            "market_direction_prediction": self.market_direction_prediction,
            "market_regime": self.market_regime,
        }


def get_trading_session(dt: Optional[Any] = None) -> Tuple[str, str]:
    """
    Mengidentifikasi sesi perdagangan pasar global aktif (WIB - Asia/Jakarta):
    - Sesi US (New York): 19:00 - 04:00 WIB (Volatilitas Tinggi, Target Khusus TP 65 pips & SL 65 pips)
    - Sesi London (Eropa): 14:00 - 19:00 WIB (Rawan Manipulasi / Judas Swing, Filter Ketat >= 75%)
    - Sesi Asia (Tokyo/Sydney): 05:00 - 14:00 WIB (Konsolidasi / Range-bound)
    Returns: (session_code, session_name)
    """
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    if dt is not None:
        if isinstance(dt, pd.Timestamp):
            if dt.tzinfo is not None:
                now_wib = dt.tz_convert(ZoneInfo("Asia/Jakarta"))
            else:
                now_wib = dt.tz_localize(ZoneInfo("Asia/Jakarta"))
        elif isinstance(dt, datetime):
            if dt.tzinfo is not None:
                now_wib = dt.astimezone(ZoneInfo("Asia/Jakarta"))
            else:
                now_wib = dt.replace(tzinfo=ZoneInfo("Asia/Jakarta"))
        else:
            now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))
    else:
        now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))

    t = now_wib.time()

    if t >= time(19, 0) or t < time(4, 0):
        return "US", "Sesi US (New York)"
    elif time(14, 0) <= t < time(19, 0):
        return "LONDON", "Sesi London (Eropa)"
    else:
        return "ASIA", "Sesi Asia (Tokyo/Sydney)"


class SignalEngine:
    """Engine evaluasi aturan strategi untuk menghasilkan sinyal BUY/SELL/HOLD."""

    def __init__(self, strategies: Optional[List[Strategy]] = None):
        self.config = load_config()
        if strategies is not None:
            self.strategies = strategies
        else:
            self.strategies = self._load_strategies_from_config()

    def _load_strategies_from_config(self) -> List[Strategy]:
        """Memuat strategi aktif dari config.yaml."""
        strat_cfg = self.config.get("strategies", {})
        definitions = strat_cfg.get("definitions", {})

        loaded_strategies = []
        for name, data in definitions.items():
            strat = Strategy.from_dict(name, data)
            register_strategy(strat)
            loaded_strategies.append(strat)

        if not loaded_strategies:
            loaded_strategies = [DEFAULT_STRATEGY]

        return loaded_strategies

    @staticmethod
    def validate_pdf_entry_confluence(
        curr_row: pd.Series,
        prev_row: Optional[pd.Series] = None,
        snapshot: Optional[Dict[str, Any]] = None,
        signal_type: str = "BUY",
        session: Optional[str] = None,
    ) -> Tuple[bool, float, str, List[str], str]:
        """
        Memvalidasi sinyal masuk (BUY / SELL) berdasarkan kaidah & teori lengkap 9 Buku PDF Trading:
        1. Fibonachi 99% Profit: Area pantulan Golden Pocket (50.0% - 61.8%).
        2. Ichimoku - Forex: Posisi tren Awan Kumo (Bullish/Bearish Cloud) & TK Cross.
        3. Under Standing Price Action (Bob Volman): Area Nilai 20 EMA, Rejection Wick, & Kompresi Buildup.
        4. Mega Profit - Forex: Trigger Candlestick Reversal (Pinbar Hammer / Engulfing / Shooting Star).
        5. Technical Analysis Explained (Martin J. Pring): Tren Mayor 50/200 EMA & Ruang Momentum RSI.
        6. Technical Analysis Of Financial Markets (John J. Murphy): Konfirmasi Volume Buyer/Seller (>= 1.1x).
        7. Wave Principle - Forex: Identifikasi gelombang impulsif sehat & pencegahan entry di pucuk Wave 5.
        8. CHART PATTERN: Pola Grafik Reversal & Continuation (Double Top/Bottom, H&S, Wedges, Triangles).
        9. Trading Alchemist (Rizki Aditama): Struktur Pasar HH/HL vs LH/LL, BOS, Order Block, & FVG Imbalance.

        Returns:
            (is_approved, score_pct, setup_grade, validation_checks, market_direction_prediction)
        """
        score = 0.0
        checks = []

        close = float(curr_row.get("Close", 0.0))
        high = float(curr_row.get("High", close))
        low = float(curr_row.get("Low", close))
        open_p = float(curr_row.get("Open", close))
        ema20 = float(curr_row.get("ema_20", close))
        ema50 = float(curr_row.get("ema_50", close))
        ema200 = float(curr_row.get("ema_200", close))
        rsi = float(curr_row.get("rsi", 50.0))
        vol_ratio = float(curr_row.get("volume_ratio", 1.0))
        wick_ratio = float(curr_row.get("rejection_wick_ratio", 0.0))
        candle_range = max(high - low, 0.001)
        upper_wick_ratio = max(0.0, (high - max(open_p, close)) / candle_range)

        pinbar = bool(curr_row.get("pattern_pinbar", 0))
        engulfing = bool(curr_row.get("pattern_engulfing", 0))
        shooting_star = bool(curr_row.get("pattern_shooting_star", 0)) or upper_wick_ratio >= 0.35
        volman_pb = bool(curr_row.get("volman_pullback", 0))
        volman_buildup = bool(curr_row.get("volman_buildup", 0))
        fib_gz = bool(curr_row.get("fib_in_golden_zone", 0))
        fib_500 = float(curr_row.get("fib_500", close))
        fib_618 = float(curr_row.get("fib_618", close))
        ichi_cloud = bool(curr_row.get("ichimoku_above_cloud", 0))
        ichi_green = bool(curr_row.get("ichimoku_cloud_green", 0))
        ichi_tk = bool(curr_row.get("ichimoku_tk_cross", 0))

        # Buku 8: CHART PATTERN
        pat_db = bool(curr_row.get("pattern_double_bottom", 0))
        pat_dt = bool(curr_row.get("pattern_double_top", 0))
        pat_fwedge = bool(curr_row.get("pattern_falling_wedge", 0))
        pat_rwedge = bool(curr_row.get("pattern_rising_wedge", 0))
        pat_ihs = bool(curr_row.get("pattern_inv_head_shoulders", 0))
        pat_hs = bool(curr_row.get("pattern_head_shoulders", 0))

        # Buku 9: Trading Alchemist - Rizki Aditama (Market Structure & Smart Money)
        struct_bull = bool(curr_row.get("structure_bullish", 0))
        struct_bear = bool(curr_row.get("structure_bearish", 0))
        bos_bull = bool(curr_row.get("structure_bos_bullish", 0))
        bos_bear = bool(curr_row.get("structure_bos_bearish", 0))
        ob_bull = bool(curr_row.get("order_block_bullish", 0))
        ob_bear = bool(curr_row.get("order_block_bearish", 0))
        fvg_bull = bool(curr_row.get("fvg_bullish", 0))
        fvg_bear = bool(curr_row.get("fvg_bearish", 0))

        # ADX & Volatilitas untuk deteksi Sideways / Flat Chop (Bob Volman & Al Brooks)
        adx_val = float(curr_row.get("adx", curr_row.get("ADX_14", 25.0)))
        ema_diff = abs(ema20 - ema50)
        has_adx = ("adx" in curr_row or "ADX_14" in curr_row)
        is_flat_chop = has_adx and (ema_diff < 1.8) and (adx_val < 20.0)

        if signal_type == "BUY":
            # 1. Martin J. Pring & Trading Alchemist: Tren Mayor Bullish (Close >= EMA 50)
            if close >= ema50:
                score += 20.0
                bonus_ma = " (+ Tren Kuat di atas EMA 200)" if close >= ema200 else ""
                checks.append(f"✅ Martin Pring: Tren Mayor Bullish (Harga di atas EMA 50{bonus_ma})")
            else:
                # Harga di bawah EMA 50 (Sinyal Reversal Melawan Tren Turun)
                # Kaidah 9 Buku PDF: Dilarang menangkap pisau jatuh tanpa konfirmasi struktur institusi
                has_reversal_structure = bos_bull or ob_bull or pat_db or pat_ihs
                if has_reversal_structure:
                    score += 10.0
                    checks.append("🛡️ Martin Pring & Alchemist: Reversal Bawah Terkonfirmasi Struktur (BOS/Order Block)")
                else:
                    score -= 15.0
                    checks.append("❌ Martin Pring & Alchemist: Dilarang Buy di Bawah EMA 50 Tanpa Konfirmasi BOS / Demand Zone Institusi")

            # 2. Bob Volman: Area Nilai Dinamis 20 EMA & Buildup (Tidak mengejar pucuk)
            dist_ema20_pct = abs(close - ema20) / max(ema20, 1.0) * 100.0
            if volman_pb or dist_ema20_pct <= 2.0:
                score += 20.0
                buildup_text = " + Kompresi Buildup Siap Breakout" if volman_buildup else ""
                pb_text = "Pullback Support 20 EMA" if volman_pb else f"Dekat Dinamis EMA 20 ({dist_ema20_pct:.1f}%)"
                checks.append(f"✅ Bob Volman: Area Nilai Terpenuhi ({pb_text}{buildup_text})")
            else:
                checks.append(f"⚠️ Bob Volman: Harga terlalu jauh dari 20 EMA ({dist_ema20_pct:.1f}% > 2.0% - Overextended)")

            # 3. Mega Profit & Bob Volman: Candlestick Reversal Bawah
            if pinbar:
                score += 20.0
                checks.append(f"✅ Mega Profit: Pola Pinbar Rejection Bawah Kuat (Ekor {wick_ratio*100:.0f}%)")
            elif engulfing:
                score += 20.0
                checks.append("✅ Mega Profit: Pola Bullish Engulfing Terkonfirmasi")
            elif wick_ratio >= 0.40:
                score += 15.0
                checks.append(f"✅ Mega Profit: Ekor Rejection Bawah Signifikan ({wick_ratio*100:.0f}%)")
            else:
                checks.append("⚠️ Candlestick: Belum ada ekor rejection / pinbar yang meyakinkan")

            # 4. Fibonacci 99% Profit: Golden Pocket (50% - 61.8%)
            if fib_gz or (close >= min(fib_500, fib_618) * 0.998 and close <= max(fib_500, fib_618) * 1.008):
                score += 15.0
                checks.append("🎯 Fibonacci: Memantul Presisi di Golden Pocket (50% - 61.8%)")
            elif close >= max(fib_500, fib_618):
                score += 10.0
                checks.append("ℹ️ Fibonacci: Struktur di Atas Area Golden Pocket")
            else:
                checks.append("⚠️ Fibonacci: Harga tertekan di bawah batas Golden Pocket 61.8%")

            # 5. Ichimoku - Forex: Awan Kumo & TK Cross
            if ichi_cloud:
                score += 15.0
                tk_note = " + Tenkan/Kijun Golden Cross" if ichi_tk else ""
                cloud_note = " (Awan Hijau)" if ichi_green else ""
                checks.append(f"☁️ Ichimoku: Struktur Bullish di Atas Awan Kumo{cloud_note}{tk_note}")
            else:
                checks.append("⚠️ Ichimoku: Candlestick masih berada di bawah Awan Kumo")

            # 6. John J. Murphy & Anna Coulling: Konfirmasi Volume Buyer (VPA)
            if vol_ratio >= 1.10:
                score += 15.0
                checks.append(f"🛡️ John Murphy & Anna Coulling: Volume Buyer Mengonfirmasi Breakout ({vol_ratio:.1f}x)")
            elif vol_ratio >= 0.95:
                score += 10.0
                checks.append(f"ℹ️ John Murphy: Volume Relatif Sehat ({vol_ratio:.1f}x)")
            elif vol_ratio < 0.70:
                score -= 10.0
                checks.append(f"⚠️ VPA (Anna Coulling): Volume Sangat Rendah ({vol_ratio:.1f}x), Waspada Fakeout Smart Money")
            else:
                checks.append(f"⚠️ John Murphy: Volume Rendah ({vol_ratio:.1f}x), Waspada Fakeout")

            # 7. Wave Principle & RSI Momentum
            if 40.0 <= rsi <= 62.0:
                score += 15.0
                checks.append(f"🌊 Wave Principle: Momentum Sehat ({rsi:.1f}) - Awal Gelombang Impulsif 3")
            elif rsi < 40.0:
                score += 10.0
                checks.append(f"ℹ️ RSI Rendah ({rsi:.1f}) - Potensi Rebound dari Oversold")
            elif rsi > 70.0:
                score -= 15.0
                checks.append(f"⚠️ Wave Principle: RSI Overbought ({rsi:.1f}) - Pucuk Wave 5 / Rawan Koreksi")
            else:
                score += 5.0
                checks.append(f"ℹ️ RSI Moderat ({rsi:.1f})")

            # 8. CHART PATTERN (Pola Grafik Reversal & Continuation)
            if pat_db:
                score += 15.0
                checks.append("📐 Chart Pattern: Pola Pembalikan Double Bottom (W Pattern) Terkonfirmasi")
            elif pat_ihs:
                score += 15.0
                checks.append("📐 Chart Pattern: Pola Inverse Head & Shoulders Bullish Breakout")
            elif pat_fwedge:
                score += 12.0
                checks.append("📐 Chart Pattern: Pola Falling Wedge (Penyempitan Rentang Bullish)")
            else:
                checks.append("ℹ️ Chart Pattern: Pola grafik mayor dalam pembentukan lanjutan")

            # 9. Trading Alchemist - Rizki Aditama (Struktur Pasar & Smart Money)
            if bos_bull:
                score += 15.0
                checks.append("🏛️ Trading Alchemist: Break of Structure (BOS Bullish) Menembus Swing High")
            elif ob_bull:
                score += 15.0
                checks.append("🏛️ Trading Alchemist: Rebound di Area Bullish Order Block (Demand Zone)")
            elif struct_bull:
                score += 12.0
                checks.append("🏛️ Trading Alchemist: Struktur Pasar Bullish (Higher High & Higher Low)")
            elif fvg_bull:
                score += 10.0
                checks.append("🏛️ Trading Alchemist: Imbalance / Fair Value Gap (FVG) Bullish Mengisi Likuiditas")
            else:
                checks.append("ℹ️ Trading Alchemist: Struktur harga sehat / menunggu konfirmasi BOS lanjutan")

            # Proteksi Tambahan Struktur Pasar Kontradiktif:
            if bos_bear:
                score -= 15.0
                checks.append("⚠️ Trading Alchemist: Break of Structure Bearish (BOS) terdeteksi, melawan tren turun rawan tersapu.")
            elif struct_bear and not struct_bull:
                score -= 10.0
                checks.append("⚠️ Trading Alchemist: Struktur Pasar Bearish (Lower High / Lower Low) membayangi.")

            # Filter Pasar Chop / Sideways Tanpa Konfirmasi (Bob Volman & Al Brooks)
            if is_flat_chop and not pinbar and not engulfing and not bos_bull:
                score -= 15.0
                checks.append("⚠️ Al Brooks & Bob Volman: Kompresi Datar / Chop (ADX < 20 & EMA menyempit) tanpa pinbar/BOS.")

        else:
            # Evaluasi untuk sinyal SELL / SHORT Gold / Exit Saham
            # 1. Martin Pring & Trading Alchemist: Tren Bearish (Close <= EMA 50)
            if close <= ema50:
                score += 20.0
                checks.append("✅ Martin Pring: Tren Bearish Terkonfirmasi (Harga di bawah EMA 50)")
            else:
                # Harga di atas EMA 50 (Sinyal Reversal Melawan Tren Naik)
                # Kaidah 9 Buku PDF: Dilarang short di pucuk tren naik tanpa konfirmasi struktur institusi
                has_reversal_structure = bos_bear or ob_bear or pat_dt or pat_hs
                if has_reversal_structure:
                    score += 10.0
                    checks.append("🛡️ Martin Pring & Alchemist: Reversal Atas Terkonfirmasi Struktur (BOS/Order Block)")
                else:
                    score -= 15.0
                    checks.append("❌ Martin Pring & Alchemist: Dilarang Sell di Atas EMA 50 Tanpa Konfirmasi BOS / Supply Zone Institusi")

            # 2. Bob Volman: Rejection dari Resisten Dinamis 20 EMA
            dist_ema20_pct = abs(close - ema20) / max(ema20, 1.0) * 100.0
            if close <= ema20 * 1.005:
                if dist_ema20_pct <= 2.0:
                    score += 20.0
                    checks.append(f"✅ Bob Volman: Rejection Resisten Dinamis 20 EMA ({dist_ema20_pct:.1f}%)")
                else:
                    score += 10.0
                    checks.append(f"⚠️ Bob Volman: Harga terlalu jauh di bawah EMA 20 ({dist_ema20_pct:.1f}% > 2.0% - Overextended Sell)")
            else:
                checks.append("⚠️ Bob Volman: Harga masih berada di atas EMA 20")

            # 3. Mega Profit & Bob Volman: Candlestick Reversal Atas
            if shooting_star:
                score += 20.0
                checks.append(f"✅ Mega Profit: Pola Shooting Star / Upper Wick ({upper_wick_ratio*100:.0f}%)")
            elif upper_wick_ratio >= 0.40:
                score += 15.0
                checks.append(f"✅ Mega Profit: Rejection Atas Signifikan ({upper_wick_ratio*100:.0f}%)")
            else:
                checks.append("⚠️ Candlestick: Belum ada sinyal rejection atas kuat")

            # 4. Fibonacci: Breakdown Golden Pocket
            if close < min(fib_500, fib_618):
                score += 15.0
                checks.append("🎯 Fibonacci: Breakdown di Bawah Level Kritis 61.8%")
            else:
                checks.append("⚠️ Fibonacci: Harga masih bertahan di atas Golden Pocket")

            # 5. Ichimoku: Di bawah Awan Kumo
            if not ichi_cloud:
                score += 15.0
                checks.append("☁️ Ichimoku: Struktur Bearish di Bawah Awan Kumo")
            else:
                checks.append("⚠️ Ichimoku: Candlestick masih berada di atas Awan Kumo")

            # 6. John Murphy & Anna Coulling: Volume Seller (VPA)
            if vol_ratio >= 1.05:
                score += 15.0
                checks.append(f"🛡️ John Murphy & Anna Coulling: Volume Seller Meningkat ({vol_ratio:.1f}x)")
            elif vol_ratio < 0.70:
                score -= 10.0
                checks.append(f"⚠️ VPA (Anna Coulling): Volume Sell Sangat Rendah ({vol_ratio:.1f}x), Dorongan Seller Rapuh")
            else:
                checks.append(f"ℹ️ John Murphy: Volume Seller Standar ({vol_ratio:.1f}x)")

            # 7. Wave Principle: Siklus Koreksi Impulsif
            if rsi >= 65.0:
                score += 15.0
                checks.append(f"🌊 Wave Principle: Tekanan Gelombang Koreksi Kuat (RSI {rsi:.1f})")
            elif rsi <= 30.0:
                score -= 15.0
                checks.append(f"⚠️ Wave Principle: RSI Sangat Oversold ({rsi:.1f}) - Pucuk Bawah / Rawan Rebound Keras")
            elif rsi <= 40.0:
                score += 15.0
                checks.append(f"🌊 Wave Principle: Momentum Bearish Lanjutan (RSI {rsi:.1f})")
            else:
                score += 5.0

            # 8. CHART PATTERN (Pola Grafik Reversal & Continuation)
            if pat_dt:
                score += 15.0
                checks.append("📐 Chart Pattern: Pola Pembalikan Double Top (M Pattern) Terkonfirmasi")
            elif pat_hs:
                score += 15.0
                checks.append("📐 Chart Pattern: Pola Head & Shoulders Bearish Breakdown")
            elif pat_rwedge:
                score += 12.0
                checks.append("📐 Chart Pattern: Pola Rising Wedge (Penyempitan Rentang Bearish)")
            else:
                checks.append("ℹ️ Chart Pattern: Pola grafik mayor dalam pembentukan lanjutan")

            # 9. Trading Alchemist - Rizki Aditama (Struktur Pasar & Smart Money)
            if bos_bear:
                score += 15.0
                checks.append("🏛️ Trading Alchemist: Break of Structure (BOS Bearish) Menembus Swing Low")
            elif ob_bear:
                score += 15.0
                checks.append("🏛️ Trading Alchemist: Penolakan di Area Bearish Order Block (Supply Zone)")
            elif struct_bear:
                score += 12.0
                checks.append("🏛️ Trading Alchemist: Struktur Pasar Bearish (Lower High & Lower Low)")
            elif fvg_bear:
                score += 10.0
                checks.append("🏛️ Trading Alchemist: Imbalance / Fair Value Gap (FVG) Bearish Mengisi Likuiditas")
            else:
                checks.append("ℹ️ Trading Alchemist: Struktur harga tertekan / menunggu konfirmasi BOS lanjutan")

            # Proteksi Tambahan Struktur Pasar Kontradiktif:
            if bos_bull:
                score -= 15.0
                checks.append("⚠️ Trading Alchemist: Break of Structure Bullish (BOS) terdeteksi, melawan tren naik rawan tersapu.")
            elif struct_bull and not struct_bear:
                score -= 10.0
                checks.append("⚠️ Trading Alchemist: Struktur Pasar Bullish (Higher High / Higher Low) membayangi.")

            # Filter Pasar Chop / Sideways Tanpa Konfirmasi (Bob Volman & Al Brooks)
            if is_flat_chop and not shooting_star and upper_wick_ratio < 0.35 and not bos_bear:
                score -= 15.0
                checks.append("⚠️ Al Brooks & Bob Volman: Kompresi Datar / Chop (ADX < 20 & EMA menyempit) tanpa shooting star/BOS.")

        score = max(0.0, min(100.0, score))

        # Penentuan Grade dan Keputusan Masuk Pasar (Gatekeeper Akurasi Tinggi)
        is_buy = (signal_type == "BUY")
        direction_name = "Bullish" if is_buy else "Bearish"

        # Filter Reversal Melawan Tren Mayor (Martin Pring & Trading Alchemist):
        # Sinyal pembalikan melawan EMA 50 wajib memiliki konfluensi Grade A+ (>= 75%)
        is_counter_trend = (is_buy and close < ema50) or (not is_buy and close > ema50)
        min_score = 75.0 if (session == "LONDON" or is_counter_trend) else 65.0

        if score >= 80.0:
            setup_grade = "Grade A+ (Setup Sempurna ⭐⭐⭐⭐⭐)"
            prediction = f"Arah market diprediksi {direction_name} kuat melanjutkan tren (Probabilitas Akurasi Sangat Tinggi)."
            is_approved = True
        elif score >= min_score:
            setup_grade = "Grade A (Setup Kuat ⭐⭐⭐⭐)"
            prediction = f"Arah market diprediksi {direction_name} bergerak searah dengan konfluensi 9 buku trading."
            is_approved = True
        else:
            if session == "LONDON" and score >= 65.0:
                setup_grade = "Grade A (Tertahan Sesi London < 75%)"
                prediction = f"Arah market rentan manipulasi likuiditas Sesi London. Setup {score:.0f}% < 75% ditahan demi keamanan modal."
                checks.append(f"🛡️ Sesi London: Sesi London sering terjadi manipulasi likuiditas / Judas swing, hanya sinyal Grade A+ kuat (>=75%) yang diizinkan (Skor: {score:.0f}%).")
            elif is_counter_trend and score >= 65.0:
                setup_grade = "Grade A (Tertahan Reversal Melawan Tren < 75%)"
                prediction = f"Sinyal pembalikan melawan tren mayor tertahan. Setup {score:.0f}% < 75% ditahan demi mencegah false reversal / kena SL konyol."
                checks.append(f"🛡️ Reversal Guard: Melawan tren mayor EMA 50 wajib skor Grade A+ (>= 75%), saat ini {score:.0f}%. Sinyal ditahan demi mengamankan modal.")
            else:
                setup_grade = "Grade B / C (Konfluensi Belum Matang ⭐⭐)"
                prediction = f"Arah market masih konsolidasi / belum memenuhi syarat konfluensi ketat ({direction_name} tertahan)."
            is_approved = False

        return is_approved, score, setup_grade, checks, prediction

    def evaluate_bar(
        self,
        df: pd.DataFrame,
        ticker: str,
        strategy: Optional[Strategy] = None,
        bar_idx: int = -1,
        apply_pdf_filter: bool = True,
    ) -> SignalResult:
        """
        Mengevaluasi bar/candle tertentu (default candle terkini -1) terhadap strategi.
        
        Args:
            df: DataFrame yang sudah dihitung indikator teknikalnya (atau OHLCV murni)
            ticker: Kode saham (misal 'BBCA.JK')
            strategy: Strategi yang ingin dievaluasi (default strategi pertama)
            bar_idx: Index bar yang dievaluasi (default -1 untuk candle terakhir)
        """
        target_strategy = strategy or self.strategies[0]

        # Pastikan indikator sudah terhitung
        if "rsi" not in [c.lower() for c in df.columns]:
            df_with_ind = TechnicalIndicators.add_all_indicators(df)
        else:
            df_with_ind = df

        if len(df_with_ind) < 2:
            return SignalResult(
                ticker=ticker,
                strategy_name=target_strategy.name,
                signal="HOLD",
                price=float(df_with_ind["Close"].iloc[-1]) if not df_with_ind.empty else 0.0,
                candle_time=str(df_with_ind.index[-1]) if not df_with_ind.empty else "",
                reasons=["Data tidak cukup untuk evaluasi strategi (< 2 bar)."],
            )

        curr_row = df_with_ind.iloc[bar_idx]
        prev_row = df_with_ind.iloc[bar_idx - 1] if abs(bar_idx) < len(df_with_ind) else None

        candle_time = (
            curr_row.name.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(curr_row.name, pd.Timestamp)
            else str(curr_row.name)
        )
        curr_price = float(curr_row["Close"])

        # Snapshot indikator utama
        snapshot = {
            "close": curr_price,
            "rsi": float(curr_row.get("rsi", 0.0)),
            "ema_20": float(curr_row.get("ema_20", 0.0)),
            "ema_50": float(curr_row.get("ema_50", 0.0)),
            "volume_ratio": float(curr_row.get("volume_ratio", 0.0)),
            "pinbar": bool(curr_row.get("pattern_pinbar", 0)),
            "engulfing": bool(curr_row.get("pattern_engulfing", 0)),
            "rejection_wick": float(curr_row.get("rejection_wick_ratio", 0.0)),
            "volman_pullback": bool(curr_row.get("volman_pullback", 0)),
            "ichimoku_above_cloud": bool(curr_row.get("ichimoku_above_cloud", 0)),
            "fib_golden_zone": bool(curr_row.get("fib_in_golden_zone", 0)),
        }

        # 1. Evaluasi Aturan BUY
        buy_results = [r.evaluate_bar(curr_row, prev_row) for r in target_strategy.buy_rules]
        buy_satisfied_list = [res[0] for res in buy_results]
        buy_reasons = [res[1] for res in buy_results if res[0]]

        if target_strategy.buy_combine == "AND":
            is_buy = all(buy_satisfied_list) and len(buy_satisfied_list) > 0
        else:  # OR
            is_buy = any(buy_satisfied_list) and len(buy_satisfied_list) > 0

        # 2. Evaluasi Aturan SELL
        sell_results = [r.evaluate_bar(curr_row, prev_row) for r in target_strategy.sell_rules]
        sell_satisfied_list = [res[0] for res in sell_results]
        sell_reasons = [res[1] for res in sell_results if res[0]]

        if target_strategy.sell_combine == "AND":
            is_sell = all(sell_satisfied_list) and len(sell_satisfied_list) > 0
        else:  # OR
            is_sell = any(sell_satisfied_list) and len(sell_satisfied_list) > 0

        # Deteksi pola candlestick & konfirmasi buku
        patterns_detected = []
        if snapshot["pinbar"]:
            patterns_detected.append("Pinbar Rejection (Bob Volman)")
        if snapshot["engulfing"]:
            patterns_detected.append("Bullish Engulfing")
        if snapshot["volman_pullback"]:
            patterns_detected.append("20 EMA Pullback")
        if snapshot["fib_golden_zone"]:
            patterns_detected.append("Fibonacci Golden Pocket")
        if snapshot["ichimoku_above_cloud"]:
            patterns_detected.append("Ichimoku Kumo Cloud")

        # 3. Tentukan arah sinyal TERLEBIH DAHULU agar TP/SL dihitung dengan benar
        # Untuk Gold: jika strategi dasar belum tegas, tentukan arah dari posisi harga vs EMA50
        is_gold = any(k in ticker.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        if is_buy:
            target_sig_type = "BUY"
        elif is_sell:
            target_sig_type = "SELL"
        elif is_gold:
            # Biarkan 9 Buku PDF yang menentukan arah berdasarkan posisi harga terhadap EMA 50
            target_sig_type = "BUY" if curr_price >= snapshot.get("ema_50", curr_price) else "SELL"
        else:
            target_sig_type = "BUY"

        # 4. Evaluasi Sesi Pasar Global (WIB) & 9 Buku PDF
        bar_dt = curr_row.name if isinstance(curr_row.name, (pd.Timestamp, datetime)) else None
        session_code, session_name = get_trading_session(bar_dt)

        pdf_approved, pdf_score, setup_grade, pdf_checks, direction_pred = self.validate_pdf_entry_confluence(
            curr_row, prev_row, snapshot, signal_type=target_sig_type, session=session_code if is_gold else None
        )

        # 5. Hitung Manajemen Risiko Trading Harian (TP / SL / RRR)
        # Sesuai Arahan Mutlak Pengguna:
        # "semua sama kan saja kalo misal lgi panjang bagus, gapapa entry panjang tp kalo moment nya short, shortt aja untuk semua jam"
        # - Semua jam (Pagi/Asia, London, US) disamakan aturannya.
        # - Momen Tren Panjang Bagus (Grade A+ Strong Trend Confluence): Boleh ambil target panjang terukur (120 - 150 pips, SL 65 pips).
        # - Momen Short / Scalping / Sideways / Normal: Gunakan target SHORT (TP 65 pips & SL 65 pips seimbang 1:1) untuk SEMUA JAM.
        market_regime = ""

        if is_gold:
            ema20_val = float(snapshot.get("ema_20", curr_price))
            ema50_val = float(snapshot.get("ema_50", curr_price))
            ema_diff = abs(ema20_val - ema50_val)
            adx_val = float(curr_row.get("adx", 20.0))
            atr_val = float(curr_row.get("atr", 3.0))
            rsi_val = float(curr_row.get("rsi", 50.0))

            mt5_cfg = self.config.get("mt5", {})
            short_tp_usd = float(mt5_cfg.get("gold_short_tp_pips", 65.0)) / 10.0  # 6.50 USD (65 pips)
            short_sl_usd = float(mt5_cfg.get("gold_short_sl_pips", 65.0)) / 10.0  # 6.50 USD (65 pips)
            long_tp_usd = float(mt5_cfg.get("gold_long_tp_pips", 140.0)) / 10.0   # 14.00 USD (140 pips)
            long_sl_usd = float(mt5_cfg.get("gold_long_sl_pips", 65.0)) / 10.0    # 6.50 USD (65 pips)

            # Deteksi Kualitas Momen Tren Panjang Bagus (Kaidah 9 Buku PDF Trading):
            # 1. EMA 20 dan EMA 50 menyebar tegas (ema_diff >= 3.5)
            # 2. ADX bertenaga (>= 22.0) ATAU konfluensi 9 Buku PDF Grade A+ (>= 80.0%)
            # 3. Penataan harga selaras dengan arah tren (BUY di atas EMA 50, SELL di bawah EMA 50)
            is_good_long_momentum = (ema_diff >= 3.5) and (adx_val >= 22.0 or pdf_score >= 80.0)
            if target_sig_type == "BUY" and not (curr_price >= ema50_val):
                is_good_long_momentum = False
            elif target_sig_type == "SELL" and not (curr_price <= ema50_val):
                is_good_long_momentum = False

            if is_good_long_momentum:
                # Sesuai arahan pengguna: "kalo misal lgi panjang bagus, gapapa entry panjang"
                # Target Lebar / Swing Run terukur (R:R 1:1.8 s/d 1:2.4+):
                tp_distance = round(max(22.0, min(35.0, curr_price * 0.0075)), 2)
                sl_distance = round(max(6.50, min(14.0, tp_distance / 2.2)), 2)
                market_regime = f"{session_name} Momentum Panjang (Trending Run R:R 1:2+)"
            else:
                # Sesuai arahan pengguna: "tp kalo moment nya short, shortt aja untuk semua jam"
                # Momen Short / Sideways / Normal untuk SEMUA JAM (Pagi/Asia, London, US):
                # Target Seimbang TP 65 Pips & SL 65 Pips ($6.50 USD):
                tp_distance = short_tp_usd  # 65 pips ($6.50 USD)
                sl_distance = short_sl_usd  # 65 pips ($6.50 USD)
                market_regime = f"{session_name} Momen Short/Sideways (Quick TP 65 Pips & SL 65 Pips)"

            # KAIDAH BAKU 9 BUKU PDF TRADING (Risk:Reward Ratio Guard):
            # DILARANG KERAS SL LEBIH BESAR DARI TP!
            # TP Wajib minimal SEIMBANG (R:R 1:1) atau LEBIH BESAR (R:R >= 1.0) demi menjaga modal tumbuh konsisten.
            if tp_distance < sl_distance:
                tp_distance = sl_distance

            if target_sig_type == "SELL":
                tp_price = round(curr_price - tp_distance, 2)
                sl_price = round(curr_price + sl_distance, 2)
                risk_dist = max(sl_price - curr_price, 0.01)
                rrr = round((curr_price - tp_price) / risk_dist, 2)
            else:
                tp_price = round(curr_price + tp_distance, 2)
                sl_price = round(curr_price - sl_distance, 2)
                risk_dist = max(curr_price - sl_price, 0.01)
                rrr = round((tp_price - curr_price) / risk_dist, 2)
        else:
            market_regime = "Saham Reguler"
            trading_cfg = self.config.get("trading", {})
            trading_mode = trading_cfg.get("mode", "intraday")
            mode_cfg = trading_cfg.get(trading_mode, {})
            tp_pct = float(mode_cfg.get("take_profit_pct", 3.0 if trading_mode == "intraday" else 5.0))
            sl_pct = float(mode_cfg.get("stop_loss_pct", 1.5 if trading_mode == "intraday" else 2.5))

            if target_sig_type == "SELL":
                tp_price = round(curr_price * (1.0 - (tp_pct / 100.0)), 0)
                sl_price = round(curr_price * (1.0 + (sl_pct / 100.0)), 0)
                risk_dist = max(sl_price - curr_price, 1.0)
                rrr = round((curr_price - tp_price) / risk_dist, 2)
            else:
                tp_price = round(curr_price * (1.0 + (tp_pct / 100.0)), 0)
                sl_price = round(curr_price * (1.0 - (sl_pct / 100.0)), 0)
                risk_dist = max(curr_price - sl_price, 1.0)
                rrr = round((tp_price - curr_price) / risk_dist, 2)

        # Filter Khusus Sesi London: Wajib skor konfluensi >= 75% demi menghindari manipulasi / Judas swing
        is_london_session = is_gold and (session_code == "LONDON")
        london_min_score = 75.0
        london_rejected = is_london_session and apply_pdf_filter and (pdf_score < london_min_score)

        if is_buy:
            if apply_pdf_filter and not pdf_approved:
                # Sinyal BUY ditahan jika konfluensi 9 buku belum tembus Grade A (65%)
                signal = "HOLD"
                reasons = [
                    f"Sinyal beli ditahan (Filter 9 Buku PDF). Skor konfluensi {pdf_score:.0f}% < 65% ({setup_grade}). "
                    f"Menunggu waktu masuk pasar yang benar-benar tepat demi menjaga Win Rate tinggi."
                ]
            elif london_rejected:
                signal = "HOLD"
                reasons = [
                    f"Sinyal beli ditahan (Mode Hati-Hati Sesi London). Skor konfluensi {pdf_score:.0f}% < {london_min_score:.0f}% ({setup_grade}). "
                    f"Sesi London sering terjadi manipulasi likuiditas / Judas swing, hanya sinyal Grade A+ kuat (>=75%) yang diizinkan."
                ]
            else:
                signal = "BUY"
                reasons = list(buy_reasons)
                reasons.append(f"Telaah 9 Buku: {setup_grade} ({pdf_score:.0f}%)")
                if is_london_session:
                    reasons.append(f"🛡️ Sesi London: Terkonfirmasi Kuat ({pdf_score:.0f}% >= 75%) Lolos Filter Anti-Manipulasi")
                if patterns_detected:
                    reasons.append(f"Pola: {', '.join(patterns_detected[:2])}")
        elif is_sell:
            if not is_gold:
                # Sesuai arahan pengguna: Saham IDX khusus BUY/Long-Only (sinyal SELL ditiadakan)
                signal = "HOLD"
                reasons = [
                    f"Sinyal jual saham dilewati (Saham IDX khusus mode BUY/Long-Only). "
                    f"RSI={snapshot['rsi']:.1f}, EMA50={snapshot['ema_50']:.0f}"
                ]
            elif apply_pdf_filter and not pdf_approved and is_gold:
                # Sinyal Short Gold ditahan jika konfluensi sell belum tembus Grade A (65%)
                signal = "HOLD"
                reasons = [
                    f"Sinyal short ditahan (Filter 9 Buku PDF). Skor konfluensi {pdf_score:.0f}% < 65% ({setup_grade}). "
                    f"Menunggu konfirmasi pembalikan arah yang lebih solid demi menjaga Win Rate tinggi."
                ]
            elif london_rejected:
                signal = "HOLD"
                reasons = [
                    f"Sinyal short ditahan (Mode Hati-Hati Sesi London). Skor konfluensi {pdf_score:.0f}% < {london_min_score:.0f}% ({setup_grade}). "
                    f"Sesi London sering terjadi manipulasi likuiditas / Judas swing, hanya sinyal Grade A+ kuat (>=75%) yang diizinkan."
                ]
            else:
                signal = "SELL"
                reasons = list(sell_reasons)
                reasons.append(f"Telaah 9 Buku: {setup_grade} ({pdf_score:.0f}%)")
                if is_london_session:
                    reasons.append(f"🛡️ Sesi London: Terkonfirmasi Kuat ({pdf_score:.0f}% >= 75%) Lolos Filter Anti-Manipulasi")
        else:
            # Jika sinyal dasar masih netral namun telaah 9 Buku PDF membuktikan Grade A (>=65% atau >=75% di London)
            min_promo_score = london_min_score if is_london_session else 65.0
            if apply_pdf_filter and pdf_score >= min_promo_score and is_gold:
                if target_sig_type == "BUY" and curr_price >= snapshot.get("ema_50", 0.0):
                    signal = "BUY"
                    reasons = [
                        f"Konfluensi 9 Buku PDF: {setup_grade} ({pdf_score:.0f}%)",
                        f"Tren Bullish di atas EMA 50 ({snapshot.get('ema_50', 0):.2f})",
                    ]
                    if is_london_session:
                        reasons.append(f"🛡️ Sesi London: Terkonfirmasi Kuat ({pdf_score:.0f}% >= 75%) Lolos Filter Anti-Manipulasi")
                    if patterns_detected:
                        reasons.append(f"Pola: {', '.join(patterns_detected[:2])}")
                elif target_sig_type == "SELL" and curr_price <= snapshot.get("ema_50", 0.0):
                    signal = "SELL"
                    reasons = [
                        f"Konfluensi 9 Buku PDF: {setup_grade} ({pdf_score:.0f}%)",
                        f"Tren Bearish di bawah EMA 50 ({snapshot.get('ema_50', 0):.2f})",
                    ]
                    if is_london_session:
                        reasons.append(f"🛡️ Sesi London: Terkonfirmasi Kuat ({pdf_score:.0f}% >= 75%) Lolos Filter Anti-Manipulasi")
                    if patterns_detected:
                        reasons.append(f"Pola: {', '.join(patterns_detected[:2])}")
                else:
                    signal = "HOLD"
                    reasons = [
                        f"Kondisi netral / menunggu konfluensi waktu masuk. RSI={snapshot['rsi']:.1f}, "
                        f"Close={curr_price:.0f}, EMA50={snapshot['ema_50']:.0f}, "
                        f"Vol Ratio={snapshot['volume_ratio']:.2f}x"
                    ]
            else:
                signal = "HOLD"
                reasons = [
                    f"Kondisi netral / menunggu konfluensi waktu masuk. RSI={snapshot['rsi']:.1f}, "
                    f"Close={curr_price:.0f}, EMA50={snapshot['ema_50']:.0f}, "
                    f"Vol Ratio={snapshot['volume_ratio']:.2f}x"
                ]

        if signal in ["BUY", "SELL"] and market_regime:
            reasons.append(f"Regime Pasar: {market_regime}")

        logger.debug(
            f"Evaluasi {ticker} ({target_strategy.name}) @ {candle_time}: "
            f"Signal={signal}, Price={curr_price}, Reasons={reasons}"
        )

        return SignalResult(
            ticker=ticker,
            strategy_name=target_strategy.name,
            signal=signal,
            price=curr_price,
            candle_time=candle_time,
            reasons=reasons,
            indicators_snapshot=snapshot,
            take_profit_price=tp_price if signal in ["BUY", "SELL"] else None,
            stop_loss_price=sl_price if signal in ["BUY", "SELL"] else None,
            risk_reward_ratio=rrr if signal in ["BUY", "SELL"] else None,
            pdf_confluence_score=pdf_score,
            setup_grade=setup_grade,
            pdf_confluence_details=pdf_checks,
            market_direction_prediction=direction_pred,
            market_regime=market_regime,
        )

    def evaluate_all_strategies(
        self,
        df: pd.DataFrame,
        ticker: str,
        bar_idx: int = -1,
    ) -> List[SignalResult]:
        """Mengevaluasi semua strategi yang terdaftar secara bersamaan untuk suatu saham."""
        results = []
        for strat in self.strategies:
            res = self.evaluate_bar(df, ticker, strategy=strat, bar_idx=bar_idx)
            results.append(res)
        return results

    @staticmethod
    def generate_signals_series(df: pd.DataFrame, strategy: Strategy) -> pd.DataFrame:
        """
        Menghasilkan deret sinyal ('BUY', 'SELL', 'HOLD') untuk seluruh bar historis DataFrame.
        Digunakan oleh backtester untuk memastikan logika identik 100% tanpa duplikasi kode.
        """
        # Pastikan indikator sudah ada
        if "rsi" not in [c.lower() for c in df.columns]:
            df_ind = TechnicalIndicators.add_all_indicators(df)
        else:
            df_ind = df.copy()

        # Evaluasi BUY series
        buy_series_list = [r.evaluate_series(df_ind) for r in strategy.buy_rules]
        if strategy.buy_combine == "AND":
            buy_mask = pd.Series(True, index=df_ind.index)
            for s in buy_series_list:
                buy_mask = buy_mask & s
        else:  # OR
            buy_mask = pd.Series(False, index=df_ind.index)
            for s in buy_series_list:
                buy_mask = buy_mask | s

        # Evaluasi SELL series
        sell_series_list = [r.evaluate_series(df_ind) for r in strategy.sell_rules]
        if strategy.sell_combine == "AND":
            sell_mask = pd.Series(True, index=df_ind.index)
            for s in sell_series_list:
                sell_mask = sell_mask & s
        else:  # OR
            sell_mask = pd.Series(False, index=df_ind.index)
            for s in sell_series_list:
                sell_mask = sell_mask | s

        # Buat kolom Signal
        signals = pd.Series("HOLD", index=df_ind.index)
        signals[buy_mask] = "BUY"
        # Jika ada konflik pada bar yang sama, sell mendominasi atau buy mendominasi sesuai rule
        signals[sell_mask] = "SELL"
        # Bar yang memenuhi keduanya diberi status BUY jika buy dicek belakangan, tapi di pasar biasanya eksklusif

        out_df = df_ind.copy()
        out_df["Signal"] = signals
        out_df["Buy_Signal"] = buy_mask
        out_df["Sell_Signal"] = sell_mask
        return out_df
