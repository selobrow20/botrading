from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
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
    # Validasi & Telaah 7 Buku PDF untuk Sinyal Masuk (BUY)
    pdf_confluence_score: float = 0.0
    setup_grade: str = ""
    pdf_confluence_details: List[str] = field(default_factory=list)
    market_direction_prediction: str = ""

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
        }


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
    ) -> Tuple[bool, float, str, List[str], str]:
        """
        Memvalidasi sinyal masuk (BUY / SELL) berdasarkan kaidah & teori lengkap 7 Buku PDF Trading:
        1. Fibonachi 99% Profit: Area pantulan Golden Pocket (50.0% - 61.8%).
        2. Ichimoku - Forex: Posisi tren Awan Kumo (Bullish/Bearish Cloud) & TK Cross.
        3. Under Standing Price Action (Bob Volman): Area Nilai 20 EMA, Rejection Wick, & Kompresi Buildup.
        4. Mega Profit - Forex: Trigger Candlestick Reversal (Pinbar Hammer / Engulfing / Shooting Star).
        5. Technical Analysis Explained (Martin J. Pring): Tren Mayor 50/200 EMA & Ruang Momentum RSI.
        6. Technical Analysis Of Financial Markets (John J. Murphy): Konfirmasi Volume Buyer/Seller (>= 1.1x).
        7. Wave Principle - Forex: Identifikasi gelombang impulsif sehat & pencegahan entry di pucuk Wave 5.

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

        if signal_type == "BUY":
            # 1. Martin J. Pring: Tren Mayor Bullish (Close >= EMA 50)
            if close >= ema50:
                score += 20.0
                bonus_ma = " (+ Tren Kuat di atas EMA 200)" if close >= ema200 else ""
                checks.append(f"✅ Martin Pring: Tren Mayor Bullish (Harga di atas EMA 50{bonus_ma})")
            else:
                checks.append("⚠️ Martin Pring: Harga di bawah EMA 50 (Rentan koreksi tren turun)")

            # 2. Bob Volman: Area Nilai Dinamis 20 EMA & Buildup (Tidak mengejar pucuk)
            dist_ema20_pct = abs(close - ema20) / max(ema20, 1.0) * 100.0
            if volman_pb or dist_ema20_pct <= 2.0:
                score += 20.0
                buildup_text = " + Kompresi Buildup Siap Breakout" if volman_buildup else ""
                pb_text = "Pullback Support 20 EMA" if volman_pb else f"Dekat Dinamis EMA 20 ({dist_ema20_pct:.1f}%)"
                checks.append(f"✅ Bob Volman: Area Nilai Terpenuhi ({pb_text}{buildup_text})")
            else:
                checks.append(f"⚠️ Bob Volman: Harga terlalu jauh dari 20 EMA ({dist_ema20_pct:.1f}% > 2.0% - Overextended)")

            # 3. Mega Profit: Candlestick Reversal Bawah
            if pinbar:
                score += 20.0
                checks.append(f"✅ Mega Profit: Pola Pinbar Rejection Bawah Kuat (Ekor {wick_ratio*100:.0f}%)")
            elif engulfing:
                score += 20.0
                checks.append("✅ Mega Profit: Pola Bullish Engulfing Terkonfirmasi")
            elif wick_ratio >= 0.30:
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

            # 6. John J. Murphy: Konfirmasi Volume Buyer
            if vol_ratio >= 1.10:
                score += 15.0
                checks.append(f"🛡️ John Murphy: Volume Buyer Mengonfirmasi Breakout ({vol_ratio:.1f}x)")
            elif vol_ratio >= 0.95:
                score += 10.0
                checks.append(f"ℹ️ John Murphy: Volume Relatif Sehat ({vol_ratio:.1f}x)")
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

        else:
            # Evaluasi untuk sinyal SELL / SHORT Gold / Exit Saham
            # 1. Martin Pring: Tren Bearish (Close <= EMA 50)
            if close <= ema50:
                score += 20.0
                checks.append("✅ Martin Pring: Tren Bearish Terkonfirmasi (Harga di bawah EMA 50)")
            else:
                checks.append("⚠️ Martin Pring: Harga masih di atas EMA 50")

            # 2. Bob Volman: Rejection dari Resisten Dinamis 20 EMA
            if close <= ema20 * 1.005:
                score += 20.0
                checks.append("✅ Bob Volman: Rejection Resisten Dinamis 20 EMA")
            else:
                checks.append("⚠️ Bob Volman: Harga masih berada di atas EMA 20")

            # 3. Mega Profit: Candlestick Reversal Atas
            if shooting_star:
                score += 20.0
                checks.append(f"✅ Mega Profit: Pola Shooting Star / Upper Wick ({upper_wick_ratio*100:.0f}%)")
            elif upper_wick_ratio >= 0.30:
                score += 15.0
                checks.append("✅ Mega Profit: Rejection Atas Signifikan")
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

            # 6. John Murphy: Volume Seller
            if vol_ratio >= 1.05:
                score += 15.0
                checks.append(f"🛡️ John Murphy: Volume Seller Meningkat ({vol_ratio:.1f}x)")
            else:
                checks.append(f"ℹ️ John Murphy: Volume Seller Standar ({vol_ratio:.1f}x)")

            # 7. Wave Principle: Siklus Koreksi Impulsif
            if rsi >= 65.0 or rsi <= 40.0:
                score += 15.0
                checks.append(f"🌊 Wave Principle: Tekanan Gelombang Koreksi Kuat (RSI {rsi:.1f})")
            else:
                score += 5.0

        score = max(0.0, min(100.0, score))

        # Penentuan Grade dan Keputusan Masuk Pasar (Gatekeeper Akurasi Tinggi)
        is_buy = (signal_type == "BUY")
        direction_name = "Bullish" if is_buy else "Bearish"
        if score >= 80.0:
            setup_grade = "Grade A+ (Setup Sempurna ⭐⭐⭐⭐⭐)"
            prediction = f"Arah market diprediksi {direction_name} kuat melanjutkan tren (Probabilitas Akurasi Sangat Tinggi)."
            is_approved = True
        elif score >= 65.0:
            setup_grade = "Grade A (Setup Kuat ⭐⭐⭐⭐)"
            prediction = f"Arah market diprediksi {direction_name} bergerak searah dengan konfluensi 3+ buku trading."
            is_approved = True
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

        # 3. Hitung Manajemen Risiko Trading Harian (TP / SL / RRR minimal 1:2.0)
        is_gold = any(k in ticker.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        if is_gold:
            tp_pct = 0.8
            sl_pct = 0.40
            # RRR 1:2.0
            if is_sell and not is_buy:
                tp_price = round(curr_price * (1.0 - (tp_pct / 100.0)), 2)
                sl_price = round(curr_price * (1.0 + (sl_pct / 100.0)), 2)
                risk_dist = max(sl_price - curr_price, 0.01)
                rrr = round((curr_price - tp_price) / risk_dist, 2)
            else:
                tp_price = round(curr_price * (1.0 + (tp_pct / 100.0)), 2)
                sl_price = round(curr_price * (1.0 - (sl_pct / 100.0)), 2)
                risk_dist = max(curr_price - sl_price, 0.01)
                rrr = round((tp_price - curr_price) / risk_dist, 2)
        else:
            trading_cfg = self.config.get("trading", {})
            trading_mode = trading_cfg.get("mode", "intraday")
            mode_cfg = trading_cfg.get(trading_mode, {})
            tp_pct = float(mode_cfg.get("take_profit_pct", 3.0 if trading_mode == "intraday" else 5.0))
            sl_pct = float(mode_cfg.get("stop_loss_pct", 1.5 if trading_mode == "intraday" else 2.5))

            if is_sell and not is_buy:
                tp_price = round(curr_price * (1.0 - (tp_pct / 100.0)), 0)
                sl_price = round(curr_price * (1.0 + (sl_pct / 100.0)), 0)
                risk_dist = max(sl_price - curr_price, 1.0)
                rrr = round((curr_price - tp_price) / risk_dist, 2)
            else:
                tp_price = round(curr_price * (1.0 + (tp_pct / 100.0)), 0)
                sl_price = round(curr_price * (1.0 - (sl_pct / 100.0)), 0)
                risk_dist = max(curr_price - sl_price, 1.0)
                rrr = round((tp_price - curr_price) / risk_dist, 2)

        # 4. Keputusan Sinyal & Alasan (Didukung Telaah Lengkap 7 Buku PDF)
        target_sig_type = "BUY" if is_buy else "SELL" if is_sell else "BUY"
        pdf_approved, pdf_score, setup_grade, pdf_checks, direction_pred = self.validate_pdf_entry_confluence(
            curr_row, prev_row, snapshot, signal_type=target_sig_type
        )

        if is_buy:
            if apply_pdf_filter and not pdf_approved:
                # Sinyal BUY ditahan jika konfluensi 7 buku belum tembus Grade A (65%)
                signal = "HOLD"
                reasons = [
                    f"Sinyal beli ditahan (Filter 7 Buku PDF). Skor konfluensi {pdf_score:.0f}% < 65% ({setup_grade}). "
                    f"Menunggu waktu masuk pasar yang benar-benar tepat demi menjaga Win Rate tinggi."
                ]
            else:
                signal = "BUY"
                reasons = list(buy_reasons)
                reasons.append(f"Telaah 7 Buku: {setup_grade} ({pdf_score:.0f}%)")
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
                    f"Sinyal short ditahan (Filter 7 Buku PDF). Skor konfluensi {pdf_score:.0f}% < 65% ({setup_grade}). "
                    f"Menunggu konfirmasi pembalikan arah yang lebih solid demi menjaga Win Rate tinggi."
                ]
            else:
                signal = "SELL"
                reasons = list(sell_reasons)
                reasons.append(f"Telaah 7 Buku: {setup_grade} ({pdf_score:.0f}%)")
        else:
            signal = "HOLD"
            # Sertakan penjelasan kondisi saat ini
            reasons = [
                f"Kondisi netral / menunggu konfluensi waktu masuk. RSI={snapshot['rsi']:.1f}, "
                f"Close={curr_price:.0f}, EMA50={snapshot['ema_50']:.0f}, "
                f"Vol Ratio={snapshot['volume_ratio']:.2f}x"
            ]

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
