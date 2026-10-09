from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, time
from zoneinfo import ZoneInfo
import pandas as pd
from config.settings import load_config, setup_logger
from indicators.technical import TechnicalIndicators
from strategy.rules import Strategy, RuleCondition, DEFAULT_STRATEGY, get_strategy, register_strategy
from strategy.smc_liquidity import SMCLiquidityEngine
from strategy.mtf_engine import (
    check_h1_snr,
    check_m30_trendline,
    get_m15_direction,
    trigger_m5_entry,
    run_top_down_mtf_pipeline,
)

logger = setup_logger("signal_engine")


@dataclass
class SignalResult:
    """Hasil evaluasi sinyal trading untuk satu saham / komoditas (Arsitektur Hermes 3D & SMC Liquidity Engine)."""
    ticker: str
    strategy_name: str
    signal: str           # 'BUY', 'SELL', 'HOLD' (arah eksekusi / kompatibilitas backward)
    price: float
    candle_time: str = ""
    trade_type: str = "SHORT"  # 'SHORT' (Scalping / Short-term) atau 'LONG' (Intraday / Swing)
    direction: str = "HOLD"    # 'BUY', 'SELL', atau 'HOLD' (Arah posisi terpisah dari trade_type)
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
    # Arsitektur 3 Lapis
    macro_bias_h4: str = ""       # 'BULLISH', 'BEARISH', 'NETRAL'
    entry_pathway: str = ""       # 'Jalur A (Konfluensi)' atau 'Jalur B (Solo Sniper: <Modul>)'
    module_scores: Dict[str, float] = field(default_factory=dict)
    # Metode Retest & Pullback Terkonfirmasi 9 Buku
    is_retest_entry: bool = False
    retest_details: str = ""
    # Fitur Pending Limit Order Sniper (Buy Limit & Sell Limit)
    is_limit_order: bool = False
    limit_order_type: Optional[str] = None  # 'BUY_LIMIT' atau 'SELL_LIMIT'
    limit_price: Optional[float] = None
    limit_expiry_minutes: int = 120
    ladder_limit_orders: List[Dict[str, Any]] = field(default_factory=list)

    # Master Trading Spec 43-Section Extensions:
    style: str = "SHORT"                  # 'SHORT' or 'LONG'
    method: str = "Trend Continuation"    # 'Liquidity Reversal', 'Trend Continuation', 'Pullback Retest', 'Breakout Reclaim', 'SMC Range Edge'
    h4_context: str = "NEUTRAL"           # 'BULLISH', 'BEARISH', 'NEUTRAL'
    h1_context: str = "NEUTRAL"           # 'BULLISH', 'BEARISH', 'NEUTRAL'
    m15_setup: str = "NORMAL"             # 'SELL-SIDE LIQUIDITY SWEEP', 'BUY-SIDE LIQUIDITY SWEEP', 'BEARISH CONTINUATION', 'BULLISH CONTINUATION', etc.
    m5_trigger: str = "NO_TRIGGER"        # 'BULLISH CHoCH + DISPLACEMENT + RETEST', 'BEARISH BOS', etc.
    structure_desc: str = "STRUCTURE_UNCLEAR"
    liquidity_desc: str = "NO_VALID_LIQUIDITY"
    liquidity_state: str = "CAUTION"      # 'SAFE', 'CAUTION', 'TRAP_RISK'
    anti_chase: str = "PASS"              # 'PASS', 'FAIL_OVEREXTENDED', 'FAIL_CHASING'
    trap_risk: str = "LOW"                # 'LOW', 'MEDIUM', 'HIGH'
    confluence_score: float = 0.0         # 0 - 100
    spread_pips: float = 3.5              # Spread dalam pips
    risk_level: str = "NORMAL"            # 'NORMAL' or 'WARNING (>6%)'
    verdict: str = "WAIT"                 # 'EXECUTE SHORT BUY', 'EXECUTE SHORT SELL', 'EXECUTE LONG BUY', 'EXECUTE LONG SELL', 'WAIT'
    verdict_reason: str = ""
    spec_report: str = ""

    def __post_init__(self):
        # Sinkronisasi direction dan signal agar selalu konsisten namun terpisah dari trade_type
        if self.direction == "HOLD" and self.signal in ["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT"]:
            self.direction = "BUY" if "BUY" in self.signal else "SELL"
        elif self.direction in ["BUY", "SELL"] and self.signal not in ["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT"]:
            self.signal = self.direction

        # Sinkronisasi style dengan trade_type
        if self.style == "SHORT" and self.trade_type != "SHORT":
            self.style = self.trade_type
        elif self.trade_type == "SHORT" and self.style != "SHORT":
            self.trade_type = self.style

        # Sinkronisasi verdict jika belum disetel
        if not self.verdict or self.verdict == "WAIT":
            if self.signal in ["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT"]:
                self.verdict = f"EXECUTE {self.style} {self.direction}"
            else:
                self.verdict = "WAIT"

    def format_master_report(self) -> str:
        reason_txt = self.verdict_reason or (self.reasons[0] if self.reasons else "Analisis pasar selesai.")
        return SMCLiquidityEngine.format_master_trading_spec_report(
            style=self.style,
            direction=self.direction if self.signal != "HOLD" else "WAIT",
            method=self.method,
            h4=self.h4_context or self.macro_bias_h4 or "NEUTRAL",
            h1=self.h1_context or "NEUTRAL",
            m15=self.m15_setup,
            m5=self.m5_trigger,
            structure=self.structure_desc,
            liquidity=self.liquidity_desc,
            liquidity_state=self.liquidity_state,
            anti_chase=self.anti_chase,
            trap_risk=self.trap_risk,
            confluence_score=self.confluence_score or self.pdf_confluence_score,
            spread=self.spread_pips,
            risk=self.risk_level,
            sl=self.stop_loss_price,
            tp=self.take_profit_price,
            rr=self.risk_reward_ratio,
            verdict=self.verdict,
            reason=reason_txt,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "strategy_name": self.strategy_name,
            "signal": self.signal,
            "trade_type": self.trade_type,
            "direction": self.direction,
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
            "macro_bias_h4": self.macro_bias_h4,
            "entry_pathway": self.entry_pathway,
            "module_scores": self.module_scores,
            "is_retest_entry": self.is_retest_entry,
            "retest_details": self.retest_details,
            "is_limit_order": self.is_limit_order,
            "limit_order_type": self.limit_order_type,
            "limit_price": self.limit_price,
            "limit_expiry_minutes": self.limit_expiry_minutes,
            "ladder_limit_orders": self.ladder_limit_orders,
            # Master Trading Spec fields:
            "style": self.style,
            "method": self.method,
            "h4_context": self.h4_context,
            "h1_context": self.h1_context,
            "m15_setup": self.m15_setup,
            "m5_trigger": self.m5_trigger,
            "structure": self.structure_desc,
            "liquidity": self.liquidity_desc,
            "liquidity_state": self.liquidity_state,
            "anti_chase": self.anti_chase,
            "trap_risk": self.trap_risk,
            "confluence_score": self.confluence_score,
            "spread": self.spread_pips,
            "risk": self.risk_level,
            "verdict": self.verdict,
            "verdict_reason": self.verdict_reason,
            "spec_report": self.spec_report,
        }


class ConfluenceResult(tuple):
    """
    Subclass tuple (is_approved, score, setup_grade, checks, prediction)
    yang mempertahankan kompatibilitas 5-item unpacking untuk kode lama,
    sekaligus menyediakan atribut Arsitektur 3 Lapis:
    - entry_pathway
    - module_scores
    - num_agreeing_modules
    - solo_sniper_module
    - is_retest_entry
    - retest_details
    """
    is_approved: bool
    score: float
    setup_grade: str
    checks: List[str]
    prediction: str
    entry_pathway: str
    module_scores: Dict[str, float]
    num_agreeing_modules: int
    solo_sniper_module: Optional[str]
    is_retest_entry: bool
    retest_details: str

    def __new__(
        cls,
        is_approved: bool,
        score: float,
        setup_grade: str,
        checks: List[str],
        prediction: str,
        entry_pathway: str = "",
        module_scores: Optional[Dict[str, float]] = None,
        num_agreeing_modules: int = 0,
        solo_sniper_module: Optional[str] = None,
        is_retest_entry: bool = False,
        retest_details: str = "",
    ):
        instance = super().__new__(cls, (is_approved, score, setup_grade, checks, prediction))
        instance.is_approved = is_approved
        instance.score = score
        instance.setup_grade = setup_grade
        instance.checks = checks
        instance.prediction = prediction
        instance.entry_pathway = entry_pathway
        instance.module_scores = module_scores or {}
        instance.num_agreeing_modules = num_agreeing_modules
        instance.solo_sniper_module = solo_sniper_module
        instance.is_retest_entry = is_retest_entry
        instance.retest_details = retest_details
        return instance


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
    elif time(12, 0) <= t < time(19, 0):
        return "LONDON", "Sesi London (Eropa)"
    else:
        return "ASIA", "Sesi Asia (Tokyo/Sydney)"


def _notify_veto(reason: str, notifier: Optional[Any] = None) -> None:
    """Mengirim pesan notifikasi pembatalan trade (veto) ke Telegram."""
    alert_text = f"⚠️ <b>Trade Dibatalkan (Veto):</b> {reason}"
    logger.warning(f"🛑 [TRADE VETO] {reason}")
    try:
        if notifier is not None and hasattr(notifier, "send_message"):
            notifier.send_message(alert_text)
        else:
            from notify.telegram_bot import TelegramNotifier
            tb = TelegramNotifier()
            tb.send_message(alert_text)
    except Exception as e:
        logger.debug(f"Pemberitahuan veto ke Telegram dilewati/gagal: {e}")


def filter_and_validate_signal(
    sig: Any,
    df: Optional[pd.DataFrame] = None,
    h4_trend: Optional[str] = None,
    notifier: Optional[Any] = None,
) -> Tuple[bool, str]:
    """
    Validasi Ketat Kondisi Trading (Hard Rules Veto Engine).
    Mencegah eksekusi posisi janggal, kontradiksi tren H4, sinyal lemah, dan SL konyol.

    Hard Rules Wajib:
    1. Kunci Satu Arah Sesuai Tren H4:
       - H4 = BEARISH: Nonaktifkan total BUY / BUY LIMIT. Hanya izinkan SELL / SELL LIMIT.
       - H4 = BULLISH: Nonaktifkan total SELL / SELL LIMIT. Hanya izinkan BUY / BUY LIMIT.
    2. Hard Veto untuk Ketiadaan Rejection & Sinyal Lemah:
       - Jika candle belum mencetak ekor penolakan valid (muncul status 'Ketiadaan Rejection Wick')
         ATAU grade sinyal bernilai GRADE B atau GRADE C, eksekusi fungsi order_send() ke MT5 WAJIB dibatalkan total.
    3. Validasi Rasio Risk-to-Reward (RR Minimal 1:1.5):
       - R:R wajib >= 1.5.

    Returns:
        (is_valid: bool, veto_reason: str)
    """
    if sig is None:
        return False, "Sinyal kosong (None)."

    action = str(getattr(sig, "signal", "") or getattr(sig, "direction", "")).upper()
    if action in ["HOLD", ""]:
        return False, "Sinyal berstatus HOLD atau kosong."

    grade = str(getattr(sig, "setup_grade", "") or "").upper()
    reasons = [str(r) for r in getattr(sig, "reasons", [])]
    details = [str(d) for d in getattr(sig, "pdf_confluence_details", [])]
    all_reasons_text = " ".join(reasons + details).upper()
    snapshot = getattr(sig, "indicators_snapshot", {}) or {}

    # ─────────────────────────────────────────────────────────────────
    # ATURAN 1: Kunci Satu Arah Sesuai Tren H4 (Anti-Kontradiksi Tren)
    # ─────────────────────────────────────────────────────────────────
    h4 = str(
        h4_trend
        or getattr(sig, "macro_bias_h4", "")
        or getattr(sig, "h4_context", "")
        or ""
    ).upper()

    if "BEAR" in h4:
        if "BUY" in action:
            msg = "Kontradiksi Tren: Tren H4 = BEARISH melarang keras posisi/order BUY (Anti-Pisau Jatuh)."
            _notify_veto(msg, notifier)
            return False, msg
    elif "BULL" in h4:
        if "SELL" in action:
            msg = "Kontradiksi Tren: Tren H4 = BULLISH melarang keras posisi/order SELL (Anti-Hadang Kereta)."
            _notify_veto(msg, notifier)
            return False, msg

    # ─────────────────────────────────────────────────────────────────
    # ATURAN 2: Hard Veto untuk Ketiadaan Rejection Wick & Sinyal Lemah
    # ─────────────────────────────────────────────────────────────────
    # Veto jika grade bernilai Grade B atau Grade C
    if any(g in grade for g in ["GRADE B", "GRADE C"]):
        msg = f"Tidak ada konfirmasi candle rejection yang valid (Grade Rendah: {grade})."
        _notify_veto(msg, notifier)
        return False, msg

    # Veto jika terdeteksi status 'Ketiadaan Rejection Wick'
    if "KETIADAAN REJECTION WICK" in all_reasons_text or "KETIADAAN REJECTION WICK" in grade:
        msg = "Tidak ada konfirmasi candle rejection yang valid (Ketiadaan Rejection Wick)."
        _notify_veto(msg, notifier)
        return False, msg

    # Pengecekan ekor rejection pada candle aktual jika bukan limit order
    is_limit = bool(getattr(sig, "is_limit_order", False) or "LIMIT" in action)
    if not is_limit and snapshot:
        wick_ratio = float(snapshot.get("rejection_wick_ratio", 0.0) or 0.0)
        upper_wick_ratio = float(snapshot.get("upper_wick_ratio", 0.0) or 0.0)
        pinbar = bool(snapshot.get("pattern_pinbar", 0))
        shooting_star = bool(snapshot.get("pattern_shooting_star", 0))
        engulfing = bool(snapshot.get("pattern_engulfing", 0))

        if "BUY" in action and not pinbar and not engulfing and wick_ratio < 0.25:
            msg = f"Tidak ada konfirmasi candle rejection yang valid (Ekor bawah {wick_ratio*100:.0f}% < 25%)."
            _notify_veto(msg, notifier)
            return False, msg
        elif "SELL" in action and not shooting_star and upper_wick_ratio < 0.25:
            msg = f"Tidak ada konfirmasi candle rejection yang valid (Ekor atas {upper_wick_ratio*100:.0f}% < 25%)."
            _notify_veto(msg, notifier)
            return False, msg

    # ─────────────────────────────────────────────────────────────────
    # ATURAN 3: Validasi Rasio Risk-to-Reward Dinamis (RR Minimal 1:1.5)
    # ─────────────────────────────────────────────────────────────────
    entry_p = float(getattr(sig, "price", 0.0) or 0.0)
    sl_p = float(getattr(sig, "stop_loss_price", 0.0) or 0.0)
    tp_p = float(getattr(sig, "take_profit_price", 0.0) or 0.0)

    if entry_p > 0 and sl_p > 0 and tp_p > 0:
        if "BUY" in action:
            sl_dist = entry_p - sl_p
            tp_dist = tp_p - entry_p
        else:
            sl_dist = sl_p - entry_p
            tp_dist = entry_p - tp_p

        if sl_dist <= 0:
            msg = f"Level Stop Loss tidak valid ({sl_p} vs Entry {entry_p})."
            _notify_veto(msg, notifier)
            return False, msg

        calculated_rr = round(tp_dist / sl_dist, 2)
        if calculated_rr < 1.45:
            msg = f"Rasio Risk-to-Reward tidak memadai ({calculated_rr:.2f} < 1.50). Minimal R:R adalah 1:1.5."
            _notify_veto(msg, notifier)
            return False, msg

    return True, "Validasi lolos. Sinyal memenuhi seluruh Hard Rules."


class SignalEngine:
    """Engine evaluasi aturan strategi untuk menghasilkan sinyal BUY/SELL/HOLD."""
    filter_and_validate_signal = staticmethod(filter_and_validate_signal)
    check_h1_snr = staticmethod(check_h1_snr)
    check_m30_trendline = staticmethod(check_m30_trendline)
    get_m15_direction = staticmethod(get_m15_direction)
    trigger_m5_entry = staticmethod(trigger_m5_entry)
    run_top_down_mtf_pipeline = staticmethod(run_top_down_mtf_pipeline)

    def __init__(self, strategies: Optional[List[Strategy]] = None, config: Optional[Dict[str, Any]] = None):
        self.config = config if config is not None else load_config()
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
    def evaluate_macro_bias_h4(
        df_h4: Optional[pd.DataFrame] = None,
        curr_row: Optional[pd.Series] = None,
        curr_price: float = 0.0,
    ) -> Tuple[str, str]:
        """
        Lapis 1: Otak Utama (H4 Bias & Izin)
        Diisi oleh John Murphy, Ichimoku, dan Martin Pring.
        - Tren H4: EMA 50/200 dan posisi harga terhadap awan Ichimoku
        - Regime momentum: RSI di zona tren naik (di atas 40) atau tren turun (di bawah 60)
        Output: (bias, reason) -> 'BULLISH', 'BEARISH', atau 'NETRAL'.
        """
        if df_h4 is not None and not df_h4.empty and len(df_h4) >= 2:
            row_h4 = df_h4.iloc[-1]
            close_h4 = float(row_h4.get("Close", curr_price))
            ema50_h4 = float(row_h4.get("ema_50", 0.0))
            ema200_h4 = float(row_h4.get("ema_200", 0.0))
            rsi_h4 = float(row_h4.get("rsi", 50.0))
            kumo_above = bool(row_h4.get("ichimoku_above_cloud", 0))

            if abs(close_h4 - ema50_h4) <= 1.0 and 40.0 <= rsi_h4 <= 60.0:
                return "NETRAL", f"H4 Netral/Konsolidasi (RSI {rsi_h4:.1f}, EMA50 ${ema50_h4:.2f})"

            is_bull_trend = (close_h4 > ema50_h4 + 0.5) if ema50_h4 > 0 else True
            is_bull_kumo = kumo_above
            is_bull_rsi = rsi_h4 >= 42.0
            is_bear_trend = (close_h4 < ema50_h4 - 0.5) if ema50_h4 > 0 else True
            is_bear_kumo = not kumo_above
            is_bear_rsi = rsi_h4 <= 58.0

            if is_bull_trend and is_bull_kumo and is_bull_rsi:
                return "BULLISH", f"H4 Bullish (Close ${close_h4:.2f} > EMA50 ${ema50_h4:.2f}, di atas Awan Kumo, RSI {rsi_h4:.1f} >= 40)"
            elif is_bear_trend and is_bear_kumo and is_bear_rsi:
                return "BEARISH", f"H4 Bearish (Close ${close_h4:.2f} < EMA50 ${ema50_h4:.2f}, di bawah Awan Kumo, RSI {rsi_h4:.1f} <= 60)"
            else:
                return "NETRAL", f"H4 Netral/Konsolidasi (RSI {rsi_h4:.1f}, EMA50 ${ema50_h4:.2f})"

        # Fallback menggunakan bar berjalan jika df_h4 tidak disediakan (misal unit test M15 atau data offline)
        if curr_row is not None:
            close = float(curr_row.get("Close", curr_price))
            ema50 = float(curr_row.get("ema_50", close))
            ema200 = float(curr_row.get("ema_200", close))
            rsi = float(curr_row.get("rsi", 50.0))
            kumo_above = bool(curr_row.get("ichimoku_above_cloud", 0))

            is_bull = (close >= ema50) and rsi >= 40.0 and (close >= ema200 or kumo_above or abs(close - ema50) <= 2.0)
            is_bear = (close <= ema50) and rsi <= 60.0 and (close <= ema200 or not kumo_above or abs(close - ema50) <= 2.0)

            if is_bull and not is_bear:
                return "BULLISH", f"Struktur Tren Bullish (Close >= EMA50 ${ema50:.2f}, RSI {rsi:.1f} >= 40)"
            elif is_bear and not is_bull:
                return "BEARISH", f"Struktur Tren Bearish (Close <= EMA50 ${ema50:.2f}, RSI {rsi:.1f} <= 60)"
            else:
                return "NETRAL", f"Struktur Tren Netral/Chop (RSI {rsi:.1f}, EMA50 ${ema50:.2f})"

        return "NETRAL", "Data tren belum memadai."

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

        # Metode Retest & Pullback (Best Price Entry: Bawah/Diskon utk BUY, Atas/Premium utk SELL)
        retest_sr_bull = bool(curr_row.get("retest_sr_flip_bullish", 0))
        retest_sr_bear = bool(curr_row.get("retest_sr_flip_bearish", 0))
        retest_ob_bull = bool(curr_row.get("retest_order_block_bullish", 0))
        retest_ob_bear = bool(curr_row.get("retest_order_block_bearish", 0))
        retest_ema_bull = bool(curr_row.get("retest_ema20_bullish", 0))
        retest_ema_bear = bool(curr_row.get("retest_ema20_bearish", 0))
        retest_fib_bull = bool(curr_row.get("retest_fib_bullish", 0))
        is_retest_buy_ind = bool(curr_row.get("is_retest_buy", 0))
        is_retest_sell_ind = bool(curr_row.get("is_retest_sell", 0))
        is_retest_confirmed_buy = False
        retest_zone_buy = ""
        is_retest_confirmed_sell = False
        retest_zone_sell = ""

        # Deteksi Aset: Gold vs Saham/Forex
        is_gold = (close > 500.0) or any(k in str(curr_row.get("symbol", "")).upper() for k in ["XAU", "GOLD"])

        # Bob Volman: Jarak Dinamis ke 20 EMA (Gold dihitung dalam USD absolut, bukan % saham)
        if is_gold:
            dist_ema20_usd = abs(close - ema20)
            dist_ema20_pct = dist_ema20_usd
            volman_near = (dist_ema20_usd <= 2.50)
            volman_moderate = (dist_ema20_usd <= 4.00)
            dist_ema20_str = f"${dist_ema20_usd:.2f} USD"
        else:
            dist_ema20_pct = abs(close - ema20) / max(ema20, 1.0) * 100.0
            dist_ema20_usd = dist_ema20_pct
            volman_near = (dist_ema20_pct <= 2.0)
            volman_moderate = (dist_ema20_pct <= 3.5)
            dist_ema20_str = f"{dist_ema20_pct:.1f}%"

        # Penentuan Posisi Premium vs Discount (Trading Alchemist - Rizki Aditama & Fibonacci)
        fib_sh = float(curr_row.get("fib_swing_high", 0.0) or 0.0)
        fib_sl = float(curr_row.get("fib_swing_low", 0.0) or 0.0)
        has_swing = (fib_sh > fib_sl > 0.0) and ((fib_sh - fib_sl) >= (1.50 if is_gold else 0.002))
        pos_in_range = ((close - fib_sl) / (fib_sh - fib_sl)) if has_swing else 0.50

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
            if volman_pb or volman_near:
                score += 20.0
                buildup_text = " + Kompresi Buildup Siap Breakout" if volman_buildup else ""
                pb_text = "Pullback Support 20 EMA" if volman_pb else f"Dekat Dinamis EMA 20 ({dist_ema20_str})"
                checks.append(f"✅ Bob Volman: Area Nilai Terpenuhi ({pb_text}{buildup_text})")
            else:
                checks.append(f"⚠️ Bob Volman: Harga terlalu jauh dari 20 EMA ({dist_ema20_str} - Overextended)")

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
            is_buyer_candle = (close >= open_p) or (wick_ratio >= 0.35)
            is_seller_dump = (close < open_p) and (wick_ratio < 0.25)
            if is_buyer_candle:
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
            elif is_seller_dump:
                if vol_ratio >= 1.10:
                    score -= 15.0
                    checks.append(f"⚠️ VPA (Anna Coulling & Murphy): Volume Seller Tinggi ({vol_ratio:.1f}x) pada Lilin Merah Dump! Distribusi institusi, dilarang beli pisau jatuh.")
                else:
                    score -= 5.0
                    checks.append(f"⚠️ John Murphy: Tekanan Jual Dominan ({vol_ratio:.1f}x) pada Lilin Merah.")
            else:
                score += 5.0
                checks.append(f"ℹ️ John Murphy: Volume Moderat ({vol_ratio:.1f}x)")

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

            # 10. METODE RETEST ENTRY TERKONFIRMASI 9 BUKU (Posisi Diskon / Bawah)
            is_retest_buy = (
                retest_sr_bull
                or retest_ob_bull
                or retest_ema_bull
                or retest_fib_bull
                or is_retest_buy_ind
                or (volman_pb and wick_ratio >= 0.25)
                or (fib_gz and wick_ratio >= 0.25)
            )
            is_retest_confirmed_buy = is_retest_buy and (pinbar or engulfing or wick_ratio >= 0.25)
            if is_retest_confirmed_buy:
                if retest_ob_bull or ob_bull:
                    retest_zone_buy = "Order Block Demand Zone"
                elif retest_sr_bull:
                    retest_zone_buy = "S/R Role Reversal (Broken Resistance -> Support)"
                elif fib_gz or retest_fib_bull:
                    retest_zone_buy = "Fibonacci Golden Pocket 61.8%"
                elif volman_pb or retest_ema_bull:
                    retest_zone_buy = "Dynamic 20 EMA Support"
                else:
                    retest_zone_buy = "Support Area Diskon"
                score += 15.0
                checks.append(f"🎯 METODE RETEST 9 BUKU: Rebound presisi di {retest_zone_buy} dengan rejection terkonfirmasi ({wick_ratio*100:.0f}% ekor bawah) -> Posisi Masuk Diskon / Bawah!")

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
            if close <= ema20 * 1.005:
                if volman_near:
                    score += 20.0
                    checks.append(f"✅ Bob Volman: Rejection Resisten Dinamis 20 EMA ({dist_ema20_str})")
                elif volman_moderate:
                    score += 10.0
                    checks.append(f"ℹ️ Bob Volman: Jarak Moderat di bawah EMA 20 ({dist_ema20_str})")
                else:
                    checks.append(f"⚠️ Bob Volman: Harga terlalu jauh di bawah EMA 20 ({dist_ema20_str} - Overextended Sell)")
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
            is_seller_candle = (close <= open_p) or (upper_wick_ratio >= 0.35)
            is_buyer_rally = (close > open_p) and (upper_wick_ratio < 0.25)
            if is_seller_candle:
                if vol_ratio >= 1.05:
                    score += 15.0
                    checks.append(f"🛡️ John Murphy & Anna Coulling: Volume Seller Meningkat ({vol_ratio:.1f}x)")
                elif vol_ratio < 0.70:
                    score -= 10.0
                    checks.append(f"⚠️ VPA (Anna Coulling): Volume Sell Sangat Rendah ({vol_ratio:.1f}x), Dorongan Seller Rapuh")
                else:
                    checks.append(f"ℹ️ John Murphy: Volume Seller Standar ({vol_ratio:.1f}x)")
            elif is_buyer_rally:
                if vol_ratio >= 1.10:
                    score -= 15.0
                    checks.append(f"⚠️ VPA (Anna Coulling & Murphy): Volume Buyer Sangat Tinggi ({vol_ratio:.1f}x) pada Lilin Hijau Naik! Melawan roket buyer rawan tersapu.")
                else:
                    score -= 5.0
                    checks.append(f"⚠️ John Murphy: Dorongan Beli Dominan ({vol_ratio:.1f}x) pada Lilin Hijau.")
            else:
                score += 5.0
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

            # 10. METODE RETEST ENTRY TERKONFIRMASI 9 BUKU (Posisi Premium / Atas)
            is_retest_sell = (
                retest_sr_bear
                or retest_ob_bear
                or retest_ema_bear
                or is_retest_sell_ind
                or (shooting_star and dist_ema20_pct <= 2.0)
            )
            is_retest_confirmed_sell = is_retest_sell and (shooting_star or upper_wick_ratio >= 0.25)
            if is_retest_confirmed_sell:
                if retest_ob_bear or ob_bear:
                    retest_zone_sell = "Order Block Supply Zone"
                elif retest_sr_bear:
                    retest_zone_sell = "S/R Role Reversal (Broken Support -> Resistance)"
                elif retest_ema_bear:
                    retest_zone_sell = "Dynamic 20 EMA Resistance"
                else:
                    retest_zone_sell = "Resistance Area Premium"
                score += 15.0
                checks.append(f"🎯 METODE RETEST 9 BUKU: Rejection presisi di {retest_zone_sell} dengan rejection terkonfirmasi ({upper_wick_ratio*100:.0f}% ekor atas) -> Posisi Masuk Premium / Atas!")

            # Filter Pasar Chop / Sideways Tanpa Konfirmasi (Bob Volman & Al Brooks)
            if is_flat_chop and not shooting_star and upper_wick_ratio < 0.35 and not bos_bear:
                score -= 15.0
                checks.append("⚠️ Al Brooks & Bob Volman: Kompresi Datar / Chop (ADX < 20 & EMA menyempit) tanpa shooting star/BOS.")

        score = max(0.0, min(100.0, score))

        # ═══════════════════════════════════════════════════════════════════════
        # LAPIS 2: SEMBILAN MODUL PEMICU & DUA JALUR ENTRY (JALUR A & JALUR B)
        # ═══════════════════════════════════════════════════════════════════════
        module_scores: Dict[str, float] = {}
        is_buy = (signal_type == "BUY")
        direction_name = "Bullish" if is_buy else "Bearish"
        is_counter_trend = (is_buy and close < ema50) or (not is_buy and close > ema50)
        is_retest_confirmed = is_retest_confirmed_buy if is_buy else is_retest_confirmed_sell
        retest_details = retest_zone_buy if is_buy else retest_zone_sell

        if is_buy:
            # 1. Volman (Bob Volman - Price Action)
            if volman_pb and volman_buildup:
                module_scores["Volman"] = 95.0
            elif volman_pb or volman_near:
                module_scores["Volman"] = 85.0
            elif volman_moderate:
                module_scores["Volman"] = 65.0
            else:
                module_scores["Volman"] = 25.0

            # 2. Pring (Martin J. Pring)
            if close >= ema50 and close >= ema200 and 40.0 <= rsi <= 65.0:
                module_scores["Pring"] = 95.0
            elif close >= ema50 and 40.0 <= rsi <= 68.0:
                module_scores["Pring"] = 85.0
            elif close >= ema50:
                module_scores["Pring"] = 70.0
            else:
                module_scores["Pring"] = 30.0

            # 3. Murphy (John J. Murphy)
            is_buyer_candle = (close >= open_p) or (wick_ratio >= 0.35)
            is_seller_dump = (close < open_p) and (wick_ratio < 0.25)
            if is_buyer_candle:
                if vol_ratio >= 1.20 and close >= ema50:
                    module_scores["Murphy"] = 90.0
                elif vol_ratio >= 1.10:
                    module_scores["Murphy"] = 80.0
                elif vol_ratio >= 0.95:
                    module_scores["Murphy"] = 65.0
                else:
                    module_scores["Murphy"] = 35.0
            elif is_seller_dump:
                module_scores["Murphy"] = 20.0
            else:
                module_scores["Murphy"] = 40.0

            # 4. Trading Alchemist (Rizki Aditama - SMC)
            if bos_bull and ob_bull:
                module_scores["Trading Alchemist"] = 95.0
            elif bos_bull:
                module_scores["Trading Alchemist"] = 85.0
            elif ob_bull:
                module_scores["Trading Alchemist"] = 80.0
            elif struct_bull:
                module_scores["Trading Alchemist"] = 70.0
            elif fvg_bull:
                module_scores["Trading Alchemist"] = 65.0
            else:
                module_scores["Trading Alchemist"] = 35.0

            # 5. Ichimoku (Ichimoku Kinko Hyo)
            if ichi_cloud and ichi_tk and ichi_green:
                module_scores["Ichimoku"] = 95.0
            elif ichi_cloud and ichi_tk:
                module_scores["Ichimoku"] = 85.0
            elif ichi_cloud:
                module_scores["Ichimoku"] = 70.0
            else:
                module_scores["Ichimoku"] = 30.0

            # 6. Fibonacci (Golden Pocket)
            if fib_gz or (close >= min(fib_500, fib_618) * 0.998 and close <= max(fib_500, fib_618) * 1.008):
                module_scores["Fibonacci"] = 90.0
            elif close >= max(fib_500, fib_618):
                module_scores["Fibonacci"] = 70.0
            else:
                module_scores["Fibonacci"] = 35.0

            # 7. Chart Pattern
            if pat_db or pat_ihs:
                module_scores["Chart Pattern"] = 90.0
            elif pat_fwedge:
                module_scores["Chart Pattern"] = 80.0
            else:
                module_scores["Chart Pattern"] = 45.0

            # 8. Wave Principle
            if 40.0 <= rsi <= 62.0:
                module_scores["Wave Principle"] = 85.0
            elif rsi < 40.0:
                module_scores["Wave Principle"] = 65.0
            elif rsi > 70.0:
                module_scores["Wave Principle"] = 25.0
            else:
                module_scores["Wave Principle"] = 50.0

            # 9. VPA (Volume Price Analysis)
            if (pinbar or engulfing) and vol_ratio >= 1.10:
                module_scores["VPA"] = 95.0
            elif pinbar or engulfing:
                module_scores["VPA"] = 85.0
            elif wick_ratio >= 0.40 and vol_ratio >= 1.0:
                module_scores["VPA"] = 80.0
            elif wick_ratio >= 0.40:
                module_scores["VPA"] = 70.0
            else:
                module_scores["VPA"] = 45.0

        else:  # SELL
            # 1. Volman (Bob Volman - Price Action)
            if close <= ema20 * 1.005 and volman_near:
                module_scores["Volman"] = 85.0
            elif close <= ema20 * 1.005 and volman_moderate:
                module_scores["Volman"] = 65.0
            else:
                module_scores["Volman"] = 25.0

            # 2. Pring (Martin J. Pring)
            if close <= ema50 and close <= ema200 and 35.0 <= rsi <= 60.0:
                module_scores["Pring"] = 95.0
            elif close <= ema50 and 32.0 <= rsi <= 60.0:
                module_scores["Pring"] = 85.0
            elif close <= ema50:
                module_scores["Pring"] = 70.0
            else:
                module_scores["Pring"] = 30.0

            # 3. Murphy (John J. Murphy)
            is_seller_candle = (close <= open_p) or (upper_wick_ratio >= 0.35)
            is_buyer_rally = (close > open_p) and (upper_wick_ratio < 0.25)
            if is_seller_candle:
                if vol_ratio >= 1.15 and close <= ema50:
                    module_scores["Murphy"] = 90.0
                elif vol_ratio >= 1.05:
                    module_scores["Murphy"] = 80.0
                elif vol_ratio >= 0.95:
                    module_scores["Murphy"] = 65.0
                else:
                    module_scores["Murphy"] = 35.0
            elif is_buyer_rally:
                module_scores["Murphy"] = 20.0
            else:
                module_scores["Murphy"] = 40.0

            # 4. Trading Alchemist (Rizki Aditama - SMC)
            if bos_bear and ob_bear:
                module_scores["Trading Alchemist"] = 95.0
            elif bos_bear:
                module_scores["Trading Alchemist"] = 85.0
            elif ob_bear:
                module_scores["Trading Alchemist"] = 80.0
            elif struct_bear:
                module_scores["Trading Alchemist"] = 70.0
            elif fvg_bear:
                module_scores["Trading Alchemist"] = 65.0
            else:
                module_scores["Trading Alchemist"] = 35.0

            # 5. Ichimoku (Ichimoku Kinko Hyo)
            if not ichi_cloud and ichi_tk:
                module_scores["Ichimoku"] = 90.0
            elif not ichi_cloud:
                module_scores["Ichimoku"] = 70.0
            else:
                module_scores["Ichimoku"] = 30.0

            # 6. Fibonacci (Golden Pocket)
            if close < min(fib_500, fib_618):
                module_scores["Fibonacci"] = 85.0
            else:
                module_scores["Fibonacci"] = 35.0

            # 7. Chart Pattern
            if pat_dt or pat_hs:
                module_scores["Chart Pattern"] = 90.0
            elif pat_rwedge:
                module_scores["Chart Pattern"] = 80.0
            else:
                module_scores["Chart Pattern"] = 45.0

            # 8. Wave Principle
            if rsi >= 65.0 or (35.0 <= rsi <= 55.0):
                module_scores["Wave Principle"] = 85.0
            elif rsi <= 30.0:
                module_scores["Wave Principle"] = 25.0
            else:
                module_scores["Wave Principle"] = 50.0

            # 9. VPA (Volume Price Analysis)
            if shooting_star and vol_ratio >= 1.05:
                module_scores["VPA"] = 95.0
            elif shooting_star:
                module_scores["VPA"] = 85.0
            elif upper_wick_ratio >= 0.40:
                module_scores["VPA"] = 75.0
            else:
                module_scores["VPA"] = 45.0

        # Hitung jumlah modul yang setuju (skor >= 60%)
        num_agreeing = sum(1 for m, s in module_scores.items() if s >= 60.0)

        # Cek hak eksekusi Jalur B (Solo Sniper - Modul Objektif Nilai A+ >= 80%)
        SOLO_MODULES = ["Trading Alchemist", "Volman", "Murphy", "Fibonacci", "Ichimoku"]
        solo_candidate = None
        max_solo_score = 0.0
        for mod in SOLO_MODULES:
            s = module_scores.get(mod, 0.0)
            if s >= 80.0 and s > max_solo_score:
                max_solo_score = s
                solo_candidate = mod

        # Solo sniper wajib didukung minimal 2 modul searah agar tidak ada modul tunggal keliru
        is_solo_sniper = (not is_counter_trend) and (solo_candidate is not None) and (max_solo_score >= 80.0) and (num_agreeing >= 2)
        min_score = 75.0 if (session == "LONDON" or is_counter_trend) else 65.0

        # Penentuan Hak Veto Lapis 3 (Risk Guard Mutlak):
        # 0a. Veto Mutlak Break of Structure (Trading Alchemist / Smart Money Concept)
        # Jika Smart Money baru saja memecah Swing Low (BOS Bearish), DILARANG KERAS BUY!
        # Jika Smart Money baru saja memecah Swing High (BOS Bullish), DILARANG KERAS SELL!
        is_bos_veto = (is_buy and bos_bear) or ((not is_buy) and bos_bull)

        # 0b. Veto Anti-Pisau Jatuh & Anti-Hadang Roket (Bob Volman & Mega Profit)
        # Dilarang BUY lilin merah dump tanpa penolakan (wick_ratio < 0.30)
        # Dilarang SELL lilin hijau meroket tanpa penolakan (upper_wick_ratio < 0.30)
        is_knife_rocket_veto = (is_buy and (close < open_p) and wick_ratio < 0.30) or (
            (not is_buy) and (close > open_p) and upper_wick_ratio < 0.30
        )

        # 1. Veto Premium vs Discount (Trading Alchemist & Fibonacci)
        is_pos_veto = (is_buy and has_swing and pos_in_range > 0.65) or ((not is_buy) and has_swing and pos_in_range < 0.35)
        # 2. Veto RSI Ekstrem (Martin Pring & Wave Principle)
        is_rsi_veto = (is_buy and rsi >= 68.0) or ((not is_buy) and rsi <= 32.0)
        # 3. Veto Candlestick Rejection Berlawanan (Mega Profit)
        is_wick_veto = (is_buy and ((shooting_star and close <= open_p) or (upper_wick_ratio >= 0.40 and close <= open_p))) or (
            (not is_buy) and ((pinbar and close >= open_p) or (wick_ratio >= 0.40 and close >= open_p))
        )
        # 4. Veto Kompresi Datar / Chop (Bob Volman & Al Brooks)
        is_chop_veto = (is_flat_chop and not pinbar and not engulfing and not (bos_bull if is_buy else bos_bear))
        # 5. Veto Sesi London (Anti-Judas Swing)
        is_london_veto = (session == "LONDON" and 65.0 <= score < 75.0)
        # 6. Veto Reversal Melawan Tren
        is_reversal_veto = (is_counter_trend and 65.0 <= score < 75.0)

        if is_bos_veto:
            struct_dir = "BOS Bearish (Breakdown Support)" if is_buy else "BOS Bullish (Breakout Resistance)"
            action_desc = "BUY saat Smart Money Menjebol ke Bawah" if is_buy else "SELL saat Smart Money Menjebol ke Atas"
            entry_pathway = f"Tertahan (Veto Lapis 3: Smart Money {struct_dir})"
            setup_grade = "Grade B / C (Melawan Break of Structure ⚠️)"
            prediction = f"Struktur institusi baru saja tertembus ({struct_dir}). Veto Lapis 3 melarang {action_desc} demi mencegah terseret arus Smart Money."
            checks.append(f"🛡️ Veto Lapis 3 (Trading Alchemist): Dilarang {action_desc}! Smart money baru saja menembus level struktural.")
            is_approved = False
        elif is_knife_rocket_veto:
            action_desc = "BUY Lilin Merah Dump (Anti-Pisau Jatuh)" if is_buy else "SELL Lilin Hijau Meroket (Anti-Hadang Kereta)"
            entry_pathway = f"Tertahan (Veto Lapis 3: {action_desc})"
            setup_grade = "Grade B / C (Ketiadaan Rejection Wick ⚠️)"
            prediction = "Candlestick belum menunjukkan bukti penolakan harga (rejection). Veto Lapis 3 menahan entry sampai ada bukti penyerapan likuiditas."
            checks.append(f"🛡️ Veto Lapis 3 (Bob Volman & Mega Profit): Dilarang {action_desc}! Ekor penolakan ({wick_ratio*100:.0f}% < 30%) belum cukup kuat.")
            is_approved = False
        elif is_pos_veto:
            zone_desc = "Premium (Pucuk Resisten > 65%)" if is_buy else "Discount (Dasar Support < 35%)"
            action_desc = "BUY di Area Premium" if is_buy else "SELL di Area Discount"
            entry_pathway = f"Tertahan (Veto Lapis 3: Dilarang {action_desc})"
            setup_grade = "Grade B / C (Area Bahaya Ekstrem ⚠️)"
            prediction = f"Harga berada di area {zone_desc} ({pos_in_range*100:.0f}% rentang swing). Veto Lapis 3 menahan entry demi mencegah beli pucuk / jual dasar."
            checks.append(f"🛡️ Veto Lapis 3 (Trading Alchemist): Dilarang {action_desc}. Smart money mencari likuiditas lawan!")
            is_approved = False
        elif is_rsi_veto:
            entry_pathway = "Tertahan (Veto Lapis 3: RSI Momentum Ekstrem)"
            setup_grade = "Grade B / C (RSI Overbought/Oversold ⚠️)"
            prediction = f"RSI berada pada tingkat jenuh ekstrem ({rsi:.1f}). Veto Lapis 3 menahan entry demi keamanan modal."
            checks.append(f"🛡️ Veto Lapis 3 (Wave Principle & Martin Pring): RSI {rsi:.1f} jenuh ekstrem - rawan pembalikan keras.")
            is_approved = False
        elif is_wick_veto:
            entry_pathway = "Tertahan (Veto Lapis 3: Rejection Candlestick Berlawanan Arah)"
            setup_grade = "Grade B / C (Rejection Melawan Arah ⚠️)"
            prediction = "Candlestick ditolak keras oleh pelaku pasar berlawanan arah. Veto Lapis 3 menahan entry."
            checks.append(f"🛡️ Veto Lapis 3 (Mega Profit): Candlestick tertolak keras berlawanan arah ({'Ekor Atas' if is_buy else 'Ekor Bawah'} >= 40%).")
            is_approved = False
        elif is_chop_veto:
            entry_pathway = "Tertahan (Veto Lapis 3: Flat Chop / Kompresi Datar)"
            setup_grade = "Grade B / C (Chop / Sideways Berbahaya ⚠️)"
            prediction = f"Arah market datar/chop (ADX < 20 & EMA menyempit). Veto Lapis 3 menahan entry demi keamanan modal."
            checks.append("⚠️ Veto Lapis 3: Kompresi Datar / Chop tanpa candlestick pinbar/BOS.")
            is_approved = False
        elif is_london_veto:
            entry_pathway = "Tertahan (Veto Lapis 3: Filter Manipulasi Sesi London)"
            setup_grade = "Grade A (Tertahan Sesi London < 75%)"
            prediction = f"Arah market rentan manipulasi likuiditas Sesi London. Setup {score:.0f}% < 75% ditahan demi keamanan modal."
            checks.append(f"🛡️ Sesi London: Sesi London sering terjadi manipulasi likuiditas / Judas swing, hanya sinyal Grade A+ kuat (>=75%) yang diizinkan (Skor: {score:.0f}%).")
            is_approved = False
        elif is_reversal_veto:
            entry_pathway = "Tertahan (Veto Lapis 3: Reversal Melawan Tren Mayor)"
            setup_grade = "Grade A (Tertahan Reversal Melawan Tren < 75%)"
            prediction = f"Sinyal pembalikan melawan tren mayor tertahan. Setup {score:.0f}% < 75% ditahan demi mencegah false reversal / kena SL konyol."
            checks.append(f"🛡️ Reversal Guard: Melawan tren mayor EMA 50 wajib skor Grade A+ (>= 75%), saat ini {score:.0f}%. Sinyal ditahan demi mengamankan modal.")
            is_approved = False
        elif is_solo_sniper and score < min_score:
            # Jalur B Promosi: Satu modul objektif sangat bagus A+ boleh langsung buka posisi
            score = max(score, max_solo_score)
            entry_pathway = f"Jalur B (Solo Sniper: {solo_candidate} {max_solo_score:.0f}%)"
            setup_grade = f"Grade A+ (Solo Sniper: {solo_candidate} ⭐⭐⭐⭐⭐)"
            prediction = f"Arah market diprediksi {direction_name} kuat via Solo Sniper {solo_candidate} (Akurasi A+)."
            checks.append(f"🎯 Lapis 2 Jalur B (Solo Sniper): Modul {solo_candidate} mencapai nilai A+ ({max_solo_score:.0f}%) searah tren utama!")
            is_approved = True
        elif score >= 80.0:
            if is_solo_sniper:
                entry_pathway = f"Jalur B (Solo Sniper: {solo_candidate} {max_solo_score:.0f}%) & Jalur A"
            else:
                entry_pathway = f"Jalur A (Konfluensi {num_agreeing}/9 Modul)"
            setup_grade = "Grade A+ (Setup Sempurna ⭐⭐⭐⭐⭐)"
            prediction = f"Arah market diprediksi {direction_name} kuat melanjutkan tren (Probabilitas Akurasi Sangat Tinggi)."
            is_approved = True
        elif score >= min_score or (num_agreeing >= 3 and not is_counter_trend and session != "LONDON"):
            entry_pathway = f"Jalur A (Konfluensi {num_agreeing}/9 Modul)"
            setup_grade = "Grade A (Setup Kuat ⭐⭐⭐⭐)"
            prediction = f"Arah market diprediksi {direction_name} bergerak searah dengan konfluensi 9 buku trading."
            is_approved = True
        else:
            entry_pathway = "Tertahan (Belum Memenuhi Syarat Jalur A maupun Jalur B)"
            setup_grade = "Grade B / C (Konfluensi Belum Matang ⭐⭐)"
            prediction = f"Arah market masih konsolidasi / belum memenuhi syarat konfluensi ketat ({direction_name} tertahan)."
            is_approved = False

        if is_approved and is_retest_confirmed:
            retest_tag = f"Retest Diskon ({retest_details})" if is_buy else f"Retest Premium ({retest_details})"
            entry_pathway = f"{retest_tag} & {entry_pathway}"
            prediction += f" Masuk presisi di ayunan {'bawah (Diskon)' if is_buy else 'atas (Premium)'}."

        return ConfluenceResult(
            is_approved=is_approved,
            score=score,
            setup_grade=setup_grade,
            checks=checks,
            prediction=prediction,
            entry_pathway=entry_pathway,
            module_scores=module_scores,
            num_agreeing_modules=num_agreeing,
            solo_sniper_module=solo_candidate if is_solo_sniper else None,
            is_retest_entry=is_retest_confirmed,
            retest_details=retest_details,
        )

    def check_london_judas_swing(
        self,
        df: pd.DataFrame,
        curr_price: float,
        signal_type: str,
        curr_row: pd.Series,
    ) -> Tuple[bool, str]:
        """
        Mendeteksi potensi perangkap manipulasi likuiditas Sesi London (Judas Swing / Liquidity Trap).
        Jendela Waktu: 14:00 - 15:30 WIB (London Open & Pre-London).
        Mekanisme: Institusi mendorong harga menembus High/Low Sesi Asia untuk memancing
        breakout retail sebelum membanting harga secara ekstrem ke arah sejati (dump/pump).
        """
        try:
            from zoneinfo import ZoneInfo
            from datetime import time, datetime
            import pandas as pd

            # Dapatkan waktu candle dalam WIB (Asia/Jakarta)
            candle_idx = curr_row.name
            if isinstance(candle_idx, pd.Timestamp):
                ts_wib = candle_idx.tz_convert(ZoneInfo("Asia/Jakarta")) if candle_idx.tzinfo else candle_idx.tz_localize(ZoneInfo("Asia/Jakarta"))
            elif isinstance(candle_idx, str):
                try:
                    dt_parsed = pd.to_datetime(candle_idx)
                    ts_wib = dt_parsed.tz_convert(ZoneInfo("Asia/Jakarta")) if dt_parsed.tzinfo else dt_parsed.tz_localize(ZoneInfo("Asia/Jakarta"))
                except Exception:
                    ts_wib = datetime.now(ZoneInfo("Asia/Jakarta"))
            else:
                ts_wib = datetime.now(ZoneInfo("Asia/Jakarta"))

            t = ts_wib.time()
            # Jendela utama manipulasi pre-London & pembukaan London: 12:00 s/d 16:00 WIB (jam 4 sore)
            # Pasar Eropa (Frankfurt/London) mulai beroperasi & memburu likuiditas Asian Range
            if not (time(12, 0) <= t <= time(16, 0)):
                return False, ""

            # Cari data sesi Asia hari ini (05:00 - 12:00 WIB)
            recent_bars = df.tail(40)
            asia_highs = []
            asia_lows = []

            for idx_val, row in recent_bars.iterrows():
                try:
                    if isinstance(idx_val, pd.Timestamp):
                        b_ts = idx_val.tz_convert(ZoneInfo("Asia/Jakarta")) if idx_val.tzinfo else idx_val.tz_localize(ZoneInfo("Asia/Jakarta"))
                    else:
                        b_ts = pd.to_datetime(idx_val).tz_localize(ZoneInfo("Asia/Jakarta"))
                    if b_ts.date() == ts_wib.date() and time(5, 0) <= b_ts.time() < time(12, 0):
                        asia_highs.append(float(row.get("High", row.get("high", 0.0))))
                        asia_lows.append(float(row.get("Low", row.get("low", 999999.0))))
                except Exception:
                    pass

            if len(asia_highs) < 3:
                prev_bars = df.iloc[-25:-1] if len(df) >= 25 else df.iloc[:-1]
                asian_high = float(prev_bars["High"].max()) if not prev_bars.empty else curr_price
                asian_low = float(prev_bars["Low"].min()) if not prev_bars.empty else curr_price
            else:
                asian_high = max(asia_highs)
                asian_low = min(asia_lows)

            high_c = float(curr_row.get("High", curr_price))
            low_c = float(curr_row.get("Low", curr_price))
            close_c = float(curr_row.get("Close", curr_price))
            open_c = float(curr_row.get("Open", curr_price))
            c_range = max(high_c - low_c, 0.01)
            upper_wick = max(0.0, (high_c - max(open_c, close_c)) / c_range)
            lower_wick = max(0.0, (min(open_c, close_c) - low_c) / c_range)
            vol_ratio = float(curr_row.get("volume_ratio", 1.0))

            # 1. Kasus BUY Trap (Bullish Judas Swing di Pucuk Asia High - ICT & Bob Volman):
            # Harga menyentuh/menembus di atas High Asia, atau memicu Buy Stop retail di pucuk
            if signal_type == "BUY":
                is_at_or_above_high = (curr_price >= asian_high - 1.0) or (high_c >= asian_high - 0.50)
                if is_at_or_above_high:
                    return True, (
                        f"🛑 Filter Anti-Judas Swing 9 Buku (Sesi London): Terdeteksi sapuan likuiditas di pucuk High Asia (${asian_high:.2f}). "
                        f"Harga (${curr_price:.2f}) berada di zona jebakan Buy-Side Liquidity. "
                        f"Kaidah ICT & Bob Volman: Dilarang BUY di pucuk range Asia saat London Open tanpa retest valid ke EMA 20."
                    )

            # 2. Kasus SELL Trap (Bearish Judas Swing di Lembah Asia Low - ICT & Bob Volman):
            # Harga menyentuh/menembus di bawah Low Asia, memicu Sell Stop retail di dasar jurang
            elif signal_type == "SELL":
                is_at_or_below_low = (curr_price <= asian_low + 1.0) or (low_c <= asian_low + 0.50)
                if is_at_or_below_low:
                    return True, (
                        f"🛑 Filter Anti-Judas Swing 9 Buku (Sesi London): Terdeteksi sapuan likuiditas di bawah Low Asia (${asian_low:.2f}). "
                        f"Harga (${curr_price:.2f}) berada di zona jebakan Sell-Side Liquidity. "
                        f"Kaidah ICT & Bob Volman: Dilarang SELL di dasar jurang / extension breakdown saat London Open karena rentan V-Shape reversal!"
                    )

            return False, ""
        except Exception as ex:
            logger.debug(f"Pengecekan judas swing trap: {ex}")
            return False, ""

    @staticmethod
    def validate_london_h1_confirmation(
        sig_type: str,
        df_h1: pd.DataFrame,
        curr_price: float,
    ) -> Tuple[bool, str]:
        """
        Validasi Konfirmasi Wajib Timeframe H1 (1-Hour) Khusus Sesi London (14:00 - 19:00 WIB).
        Sesuai kaidah trader profesional & instruksi pengguna:
        Di Sesi London yang sarat volatilitas & manipulasi likuiditas, open posisi HANYA diizinkan
        jika arah sinyal telah terkonfirmasi sejalan 100% dengan tren & struktur candle H1 (1-Hour).
        """
        if df_h1 is None or df_h1.empty or len(df_h1) < 2:
            return True, ""  # Data tidak cukup, loloskan default

        curr_h1 = df_h1.iloc[-1]
        prev_h1 = df_h1.iloc[-2]

        open_h1 = float(curr_h1.get("Open", curr_h1.get("open", curr_price)))
        close_h1 = float(curr_h1.get("Close", curr_h1.get("close", curr_price)))
        high_h1 = float(curr_h1.get("High", curr_h1.get("high", curr_price)))
        low_h1 = float(curr_h1.get("Low", curr_h1.get("low", curr_price)))

        ema20_h1 = float(curr_h1.get("ema_20", 0.0))
        ema50_h1 = float(curr_h1.get("ema_50", 0.0))

        prev_close_h1 = float(prev_h1.get("Close", prev_h1.get("close", open_h1)))
        prev_open_h1 = float(prev_h1.get("Open", prev_h1.get("open", prev_close_h1)))

        if sig_type == "BUY":
            # Syarat BUY di Sesi London:
            # 1. Candle H1 berjalan tidak boleh sedang bearish tajam (Close < Open)
            is_candle_bearish = (curr_price < open_h1 - 1.0) or (close_h1 < open_h1 - 1.0)
            # 2. Jika prev H1 dan curr H1 dua-duanya candle merah tebal
            is_double_red = (prev_close_h1 < prev_open_h1) and (curr_price < open_h1)
            # 3. Jika harga di bawah EMA 50 H1
            is_below_ema50 = (ema50_h1 > 0 and curr_price < ema50_h1 - 1.50)

            if is_candle_bearish or is_double_red or is_below_ema50:
                reasons = []
                if is_candle_bearish:
                    reasons.append(f"Candle H1 berjalan sedang Bearish (Open ${open_h1:.2f} ➔ Harga ${curr_price:.2f})")
                if is_double_red:
                    reasons.append("Candle H1 sebelumnya juga ditutup Bearish")
                if is_below_ema50:
                    reasons.append(f"Harga berada di bawah Tren Mayor EMA 50 H1 (${ema50_h1:.2f})")
                detail = "; ".join(reasons)
                return False, f"🛑 Sesi London Wajib Konfirmasi H1: Sinyal BUY ditolak karena H1 Bearish ({detail}). Menghindari terjebak manipulasi intraday."

            return True, "✅ Konfirmasi H1 Sesi London: Struktur & Tren H1 Bullish sejalan dengan sinyal BUY."

        elif sig_type == "SELL":
            # Syarat SELL di Sesi London:
            # 1. Candle H1 berjalan tidak boleh sedang bullish tajam (Close > Open)
            is_candle_bullish = (curr_price > open_h1 + 1.0) or (close_h1 > open_h1 + 1.0)
            # 2. Jika prev H1 dan curr H1 dua-duanya candle hijau tebal
            is_double_green = (prev_close_h1 > prev_open_h1) and (curr_price > open_h1)
            # 3. Jika harga di atas EMA 50 H1
            is_above_ema50 = (ema50_h1 > 0 and curr_price > ema50_h1 + 1.50)

            if is_candle_bullish or is_double_green or is_above_ema50:
                reasons = []
                if is_candle_bullish:
                    reasons.append(f"Candle H1 berjalan sedang Bullish (Open ${open_h1:.2f} ➔ Harga ${curr_price:.2f})")
                if is_double_green:
                    reasons.append("Candle H1 sebelumnya juga ditutup Bullish")
                if is_above_ema50:
                    reasons.append(f"Harga berada di atas Tren Mayor EMA 50 H1 (${ema50_h1:.2f})")
                detail = "; ".join(reasons)
                return False, f"🛑 Sesi London Wajib Konfirmasi H1: Sinyal SELL ditolak karena H1 Bullish ({detail}). Menghindari terjebak manipulasi intraday."

            return True, "✅ Konfirmasi H1 Sesi London: Struktur & Tren H1 Bearish sejalan dengan sinyal SELL."

        return True, ""

    def generate_dual_sided_limit_orders(
        self,
        df: pd.DataFrame,
        ticker: str,
        curr_price: float,
        snapshot: Dict[str, Any],
        trade_type: str = "SHORT",
        df_h1: Optional[pd.DataFrame] = None,
        df_h4: Optional[pd.DataFrame] = None,
        is_cent: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        Menghasilkan jaring dua sisi pending limit orders (BUY LIMIT & SELL LIMIT)
        berdasarkan analisis pasar terkini (20 EMA, 50 EMA, Support Demand & Resistance Supply)
        sesuai kaidah 9 Buku PDF & SMC Spec.
        Lot:
        - Akun Cent (USC): 0.05 Lot
        - Akun Standard (USD): 0.01 Lot
        """
        cfg_mt5 = self.config.get("mt5", {})
        min_limit_pips = float(cfg_mt5.get("min_limit_distance_pips", 15.0))
        min_dist = max(1.50, min_limit_pips / 10.0)
        min_spacing_usd = max(2.00, float(cfg_mt5.get("min_level_spacing_pips", 20.0)) / 10.0)

        # Penentuan Lot: Akun Standard USD = 0.01 Lot, Akun Cent (USC) = 0.05 Lot
        if is_cent is False:
            order_lot = float(cfg_mt5.get("limit_order_lot_usd", 0.01))
        elif is_cent is True:
            order_lot = float(cfg_mt5.get("limit_order_lot_cent", cfg_mt5.get("limit_order_lot", 0.05)))
        else:
            try:
                from trading.mt5_bridge import MT5Bridge
                b = MT5Bridge()
                order_lot = float(cfg_mt5.get("limit_order_lot_cent", 0.05)) if b.is_cent_account() else float(cfg_mt5.get("limit_order_lot_usd", 0.01))
            except Exception:
                order_lot = float(cfg_mt5.get("limit_order_lot", 0.05))

        atr_val = float(snapshot.get("atr", 3.0) or (df["atr"].iloc[-1] if "atr" in df.columns else 3.0) or 3.0)
        buffer_usd = max(1.50, round(atr_val * 0.4, 2))

        ema20_raw = float(snapshot.get("ema_20", curr_price) or curr_price)
        ema50_raw = float(snapshot.get("ema_50", curr_price) or curr_price)

        recent_slice = df.tail(30) if len(df) >= 30 else df
        recent_low = float(recent_slice["Low"].min()) if "Low" in recent_slice.columns else (curr_price - 10.0)
        recent_high = float(recent_slice["High"].max()) if "High" in recent_slice.columns else (curr_price + 10.0)

        # ─── 1. SISI BUY LIMIT (Lantai Support / Diskon) ───
        max_buy1 = round(curr_price - min_dist, 2)
        if ema20_raw <= max_buy1:
            buy1_p = round(ema20_raw, 2)
            buy1_lbl = "BUY LIMIT L1 (Retest 20 EMA Support)"
        else:
            buy1_p = round(min(max_buy1, recent_low + 1.00), 2)
            if buy1_p >= max_buy1:
                buy1_p = max_buy1
            buy1_lbl = "BUY LIMIT L1 (Demand Rebound / Diskon)"

        # Stop Loss Dinamis Berbasis Struktur Swing Low (Bukan Statis $6)
        base_buy_sl = round(recent_low - buffer_usd, 2)
        sl_dist1_buy = max(round(buy1_p - base_buy_sl, 2), max(4.0, round(atr_val * 1.5, 2)))
        buy1_sl = round(buy1_p - sl_dist1_buy, 2)
        tp_dist1_buy = round(sl_dist1_buy * (3.0 if trade_type == "LONG" else 1.5), 2)
        buy1_tp = round(buy1_p + tp_dist1_buy, 2)
        buy1_rrr = round(tp_dist1_buy / max(sl_dist1_buy, 0.01), 2)

        max_buy2 = round(buy1_p - min_spacing_usd, 2)
        if ema50_raw <= max_buy2:
            buy2_p = round(ema50_raw, 2)
            buy2_lbl = "BUY LIMIT L2 (Retest 50 EMA Support)"
        else:
            buy2_p = max_buy2
            buy2_lbl = "BUY LIMIT L2 (Deep Floor S2 / Demand)"

        sl_dist2_buy = max(round(buy2_p - base_buy_sl, 2), max(4.0, round(atr_val * 1.5, 2)))
        buy2_sl = round(buy2_p - sl_dist2_buy, 2)
        tp_dist2_buy = round(sl_dist2_buy * (3.0 if trade_type == "LONG" else 1.5), 2)
        buy2_tp = round(buy2_p + tp_dist2_buy, 2)
        buy2_rrr = round(tp_dist2_buy / max(sl_dist2_buy, 0.01), 2)

        # ─── 2. SISI SELL LIMIT (Atap Resisten / Premium) ───
        min_sell1 = round(curr_price + min_dist, 2)
        if ema20_raw >= min_sell1:
            sell1_p = round(ema20_raw, 2)
            sell1_lbl = "SELL LIMIT L1 (Retest 20 EMA Resistance)"
        else:
            sell1_p = round(max(min_sell1, recent_high - 1.00), 2)
            if sell1_p <= min_sell1:
                sell1_p = min_sell1
            sell1_lbl = "SELL LIMIT L1 (Supply Pullback / Premium)"

        # Stop Loss Dinamis Berbasis Struktur Swing High (Bukan Statis $6)
        base_sell_sl = round(recent_high + buffer_usd, 2)
        sl_dist1_sell = max(round(base_sell_sl - sell1_p, 2), max(4.0, round(atr_val * 1.5, 2)))
        sell1_sl = round(sell1_p + sl_dist1_sell, 2)
        tp_dist1_sell = round(sl_dist1_sell * (3.0 if trade_type == "LONG" else 1.5), 2)
        sell1_tp = round(sell1_p - tp_dist1_sell, 2)
        sell1_rrr = round(tp_dist1_sell / max(sl_dist1_sell, 0.01), 2)

        min_sell2 = round(sell1_p + min_spacing_usd, 2)
        if ema50_raw >= min_sell2:
            sell2_p = round(ema50_raw, 2)
            sell2_lbl = "SELL LIMIT L2 (Retest 50 EMA Resistance)"
        else:
            sell2_p = min_sell2
            sell2_lbl = "SELL LIMIT L2 (Deep Ceiling R2 / Supply)"

        sl_dist2_sell = max(round(base_sell_sl - sell2_p, 2), max(4.0, round(atr_val * 1.5, 2)))
        sell2_sl = round(sell2_p + sl_dist2_sell, 2)
        tp_dist2_sell = round(sl_dist2_sell * (3.0 if trade_type == "LONG" else 1.5), 2)
        sell2_tp = round(sell2_p - tp_dist2_sell, 2)
        sell2_rrr = round(tp_dist2_sell / max(sl_dist2_sell, 0.01), 2)

        # ─── HARD RULE 1: Kunci Satu Arah Sesuai Tren H4 ───
        # H4 = BEARISH -> Nonaktifkan total BUY LIMIT (Anti-Pisau Jatuh). Hanya SELL LIMIT.
        # H4 = BULLISH -> Nonaktifkan total SELL LIMIT (Anti-Hadang Kereta). Hanya BUY LIMIT.
        # Dilarang memasang Buy Limit dan Sell Limit secara bersamaan di rentang swing yang sama.
        curr_row = df.iloc[-1] if not df.empty else pd.Series()
        macro_bias, _ = self.evaluate_macro_bias_h4(df_h4=df_h4, curr_row=curr_row, curr_price=curr_price)
        allow_buy = True
        allow_sell = True

        force_dual = bool(cfg_mt5.get("force_dual_bracket_test", False))
        if not force_dual:
            if macro_bias == "BEARISH":
                allow_buy = False
                allow_sell = True
                logger.info("🔒 [TREND LOCK H4] H4 = BEARISH: BUY LIMIT dinonaktifkan total (Anti-Pisau Jatuh). Hanya SELL LIMIT diizinkan.")
            elif macro_bias == "BULLISH":
                allow_buy = True
                allow_sell = False
                logger.info("🔒 [TREND LOCK H4] H4 = BULLISH: SELL LIMIT dinonaktifkan total (Anti-Hadang Kereta). Hanya BUY LIMIT diizinkan.")
            else:
                # H4 Netral: Cek H1 atau arah harga terhadap EMA50
                h1_bias = "NETRAL"
                if df_h1 is not None and not df_h1.empty:
                    h1_bias, _ = self.evaluate_macro_bias_h4(df_h4=df_h1, curr_row=curr_row, curr_price=curr_price)
                if h1_bias == "BEARISH":
                    allow_buy = False
                    allow_sell = True
                elif h1_bias == "BULLISH":
                    allow_buy = True
                    allow_sell = False
                else:
                    if curr_price >= ema50_raw:
                        allow_buy = True
                        allow_sell = False
                    else:
                        allow_buy = False
                        allow_sell = True

        orders = []
        if allow_buy:
            orders.append({
                "level": 1,
                "label": buy1_lbl,
                "signal": "BUY_LIMIT",
                "type": "BUY_LIMIT",
                "price": buy1_p,
                "tp": buy1_tp,
                "sl": buy1_sl,
                "rrr": buy1_rrr,
                "lot": order_lot,
            })
            orders.append({
                "level": 2,
                "label": buy2_lbl,
                "signal": "BUY_LIMIT",
                "type": "BUY_LIMIT",
                "price": buy2_p,
                "tp": buy2_tp,
                "sl": buy2_sl,
                "rrr": buy2_rrr,
                "lot": order_lot,
            })
        if allow_sell:
            orders.append({
                "level": 1 if not allow_buy else 3,
                "label": sell1_lbl,
                "signal": "SELL_LIMIT",
                "type": "SELL_LIMIT",
                "price": sell1_p,
                "tp": sell1_tp,
                "sl": sell1_sl,
                "rrr": sell1_rrr,
                "lot": order_lot,
            })
            orders.append({
                "level": 2 if not allow_buy else 4,
                "label": sell2_lbl,
                "signal": "SELL_LIMIT",
                "type": "SELL_LIMIT",
                "price": sell2_p,
                "tp": sell2_tp,
                "sl": sell2_sl,
                "rrr": sell2_rrr,
                "lot": order_lot,
            })
        return orders

    def evaluate_bar(
        self,
        df: pd.DataFrame,
        ticker: str,
        strategy: Optional[Strategy] = None,
        bar_idx: int = -1,
        apply_pdf_filter: bool = True,
        df_h1: Optional[pd.DataFrame] = None,
        df_h4: Optional[pd.DataFrame] = None,
        df_m5: Optional[pd.DataFrame] = None,
        df_m30: Optional[pd.DataFrame] = None,
        preferred_trade_type: Optional[str] = None,
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

        # ─── SMC & LIQUIDITY ENGINE (Master Trading Spec) ──────────────────
        smc_struct = SMCLiquidityEngine.analyze_market_structure(df_with_ind)
        smc_liq_buy = SMCLiquidityEngine.analyze_liquidity(df_with_ind, smc_struct, intended_direction="BUY")
        smc_liq_sell = SMCLiquidityEngine.analyze_liquidity(df_with_ind, smc_struct, intended_direction="SELL")

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
        # Untuk Gold vs Saham IDX:
        is_idx_stock = ticker.endswith(".JK") or any(k in ticker.upper() for k in ["BBCA", "BBRI", "TLKM", "ASII", "BMRI", "BBNI"])
        is_gold = (not is_idx_stock) and (any(k in ticker.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"]) or (curr_price > 500.0 and "." not in ticker))
        upper_wick_ratio = float(curr_row.get("upper_wick_ratio", 0.0))
        shooting_star_val = bool(curr_row.get("pattern_shooting_star", 0)) or (upper_wick_ratio >= 0.35)

        if is_buy:
            target_sig_type = "BUY"
        elif is_sell:
            target_sig_type = "SELL"
        elif is_gold:
            # Kaidah Section 31 & 33 (Reversal vs Continuation):
            # Jika ada Sell-Side Sweep + Reclaim + konfirmasi Bullish CHoCH/Rejection, validasi Reversal BUY
            if smc_liq_buy.has_sweep_and_reclaim and (smc_struct.choch_bullish or snapshot["pinbar"] or snapshot["engulfing"] or snapshot["rejection_wick"] >= 0.35):
                target_sig_type = "BUY"
            # Jika ada Buy-Side Sweep + Reclaim + konfirmasi Bearish CHoCH/Rejection, validasi Reversal SELL
            elif smc_liq_sell.has_sweep_and_reclaim and (smc_struct.choch_bearish or shooting_star_val):
                target_sig_type = "SELL"
            else:
                # Biarkan 9 Buku PDF yang menentukan arah berdasarkan posisi harga terhadap EMA 50
                target_sig_type = "BUY" if curr_price >= snapshot.get("ema_50", curr_price) else "SELL"
        else:
            target_sig_type = "BUY"

        active_smc_liq = smc_liq_buy if target_sig_type == "BUY" else smc_liq_sell

        # 4. Evaluasi Sesi Pasar Global (WIB) & 9 Buku PDF
        bar_dt = curr_row.name if isinstance(curr_row.name, (pd.Timestamp, datetime)) else None
        session_code, session_name = get_trading_session(bar_dt)

        # ─── LAPIS 1: OTAK UTAMA (H4 BIAS & IZIN) ───────────────────────────
        macro_bias, macro_reason = self.evaluate_macro_bias_h4(df_h4=df_h4, curr_row=curr_row, curr_price=curr_price)

        pdf_res = self.validate_pdf_entry_confluence(
            curr_row, prev_row, snapshot, signal_type=target_sig_type, session=session_code if is_gold else None
        )
        pdf_approved, pdf_score, setup_grade, pdf_checks, direction_pred = pdf_res
        entry_pathway = getattr(pdf_res, "entry_pathway", "Jalur A (Konfluensi)")
        module_scores = getattr(pdf_res, "module_scores", {})
        is_retest_sig = getattr(pdf_res, "is_retest_entry", False)
        retest_details_sig = getattr(pdf_res, "retest_details", "")
        limit_price_val: Optional[float] = None
        is_limit_order_sig: bool = False
        limit_order_type_val: Optional[str] = None

        # ─── MULTI-TIMEFRAME ANALYSIS (MTF) TOP-DOWN (H1 -> M30 -> M15 -> M5) ───
        if is_gold and target_sig_type in ["BUY", "SELL"]:
            # 1. H1 SNR Key Support & Resistance (Jarak 15 pips)
            if df_h1 is not None and not df_h1.empty:
                h1_chk = check_h1_snr(df_h1, curr_price=curr_price, pip_buffer=1.50)
                if target_sig_type == "BUY" and not h1_chk.get("can_buy", True):
                    pdf_approved = False
                    pdf_checks.append(h1_chk.get("reason", "Veto H1 SNR: Terlalu dekat resisten."))
                elif target_sig_type == "SELL" and not h1_chk.get("can_sell", True):
                    pdf_approved = False
                    pdf_checks.append(h1_chk.get("reason", "Veto H1 SNR: Terlalu dekat support."))

            # 2. M30 Dynamic Trendline
            if df_m30 is not None and not df_m30.empty:
                m30_chk = check_m30_trendline(df_m30, curr_price=curr_price)
                if target_sig_type == "BUY" and m30_chk.get("trendline_bias") == "SELL" and m30_chk.get("condition") in ["BOUNCE_RESISTANCE", "BREAKOUT_DOWN"]:
                    pdf_approved = False
                    pdf_checks.append(f"Veto M30 Trendline: {m30_chk.get('status')}")
                elif target_sig_type == "SELL" and m30_chk.get("trendline_bias") == "BUY" and m30_chk.get("condition") in ["BOUNCE_SUPPORT", "BREAKOUT_UP"]:
                    pdf_approved = False
                    pdf_checks.append(f"Veto M30 Trendline: {m30_chk.get('status')}")

            # 3. M15 Trend Direction Lock
            m15_chk = get_m15_direction(df_with_ind, curr_price=curr_price)
            if m15_chk.get("direction") == "BUY" and target_sig_type == "SELL":
                pdf_approved = False
                pdf_checks.append(f"Veto M15 Lock: Tren M15 terkunci BUY ({m15_chk.get('status')}).")
            elif m15_chk.get("direction") == "SELL" and target_sig_type == "BUY":
                pdf_approved = False
                pdf_checks.append(f"Veto M15 Lock: Tren M15 terkunci SELL ({m15_chk.get('status')}).")

            # 4. M5 Rejection Gatekeeper (Wick >= 30%)
            if df_m5 is not None and not df_m5.empty and pdf_approved:
                m5_chk = trigger_m5_entry(
                    df_m5=df_m5,
                    h1_res=h1_chk if 'h1_chk' in locals() else {"can_buy": True, "can_sell": True},
                    m30_res=m30_chk if 'm30_chk' in locals() else {"trendline_bias": "NEUTRAL", "condition": "INSIDE_CHANNEL"},
                    m15_res=m15_chk,
                    curr_price=curr_price,
                    min_wick_ratio=0.30,
                    min_rr_ratio=2.0,
                )
                if not m5_chk.get("can_execute", False):
                    pdf_approved = False
                    pdf_checks.append(m5_chk.get("reason", "Veto M5 Rejection Wick."))

        # 5. Hitung Manajemen Risiko Trading Harian (TP / SL / RRR)
        # Sesuai Arahan Mutlak Pengguna:
        # "sl tp minimal 1:1 60 pips, di mix aja kalo yang bagus di sebelumnya gpp dipakai tapi sl tp minimal 60 pips 1:1 dilarang dibawah itu"
        market_regime = ""
        trade_type = preferred_trade_type or "SHORT"

        if is_gold:
            MIN_GOLD_SL_USD = 6.00  # 60 pips mutlak ($6.00 USD)
            MIN_GOLD_TP_USD = 6.00  # 60 pips mutlak ($6.00 USD)

            ema20_val = float(snapshot.get("ema_20", curr_price))
            ema50_val = float(snapshot.get("ema_50", curr_price))
            ema_diff = abs(ema20_val - ema50_val)
            adx_val = float(curr_row.get("adx", 20.0))
            atr_val = float(curr_row.get("atr", 3.0))
            rsi_val = float(curr_row.get("rsi", 50.0))

            mt5_cfg = self.config.get("mt5", {})
            short_tp_usd = max(MIN_GOLD_TP_USD, float(mt5_cfg.get("gold_short_tp_pips", 60.0)) / 10.0)
            short_sl_usd = max(MIN_GOLD_SL_USD, float(mt5_cfg.get("gold_short_sl_pips", 60.0)) / 10.0)
            long_tp_usd = max(18.00, float(mt5_cfg.get("gold_long_tp_pips", 180.0)) / 10.0)
            long_sl_usd = max(MIN_GOLD_SL_USD, float(mt5_cfg.get("gold_long_sl_pips", 60.0)) / 10.0)

            # ============================================================
            # SISTEM ATR-ADAPTIVE TP/SL ANTI-FAKEOUT (9 BUKU PDF TRADING)
            # ============================================================
            atr_safe = max(atr_val, 2.5)  # Minimal 25 pips agar SL tidak kena sweep tipis
            atr_safe = min(atr_safe, 8.0)  # Maksimal 80 pips
            is_high_vol = atr_val > 5.5

            # Multiplier SL berdasarkan kondisi pasar + volatilitas (anti-fakeout & anti-sweep):
            vol_ratio_now = float(curr_row.get("volume_ratio", 1.0))
            if is_high_vol and (vol_ratio_now < 0.80 or session_code == "LONDON"):
                sl_atr_mult = 1.6
            elif vol_ratio_now < 0.80 or session_code == "LONDON":
                sl_atr_mult = 1.5
            elif is_high_vol:
                sl_atr_mult = 1.5
            elif adx_val >= 22.0:
                sl_atr_mult = 1.2
            else:
                sl_atr_mult = 1.4

            is_good_long_momentum = (ema_diff >= 3.5) and (adx_val >= 22.0 or pdf_score >= 80.0)
            if target_sig_type == "BUY" and not (curr_price >= ema50_val):
                is_good_long_momentum = False
            elif target_sig_type == "SELL" and not (curr_price <= ema50_val):
                is_good_long_momentum = False

            # ─────────────────────────────────────────────────────────────
            # RESTRUCTURE LOGIKA DUA TIPE TRADE (BoTrading / Hermes 3D):
            # 1. SHORT = SCALPING / SHORT-TERM TRADE (Quick in/quick out, SL/TP ~60 pips)
            # 2. LONG  = INTRADAY / SWING TRADE (Dynamic SL/TP, R:R 3:1, BE trigger +60 pips)
            # !!! JANGAN SALAH ARTIKAN: SHORT != SELL, LONG != BUY !!!
            # SHORT dan LONG adalah KLASIFIKASI DURASI / KARAKTER TRADE, BUKAN ARAH!
            # ─────────────────────────────────────────────────────────────
            if preferred_trade_type in ["SHORT", "LONG"]:
                trade_type = preferred_trade_type
            elif is_good_long_momentum and macro_bias in ["BULLISH", "BEARISH"] and (
                (macro_bias == "BULLISH" and target_sig_type == "BUY") or
                (macro_bias == "BEARISH" and target_sig_type == "SELL")
            ):
                trade_type = "LONG"
            elif is_good_long_momentum and pdf_score >= 90.0:
                trade_type = "LONG"
            else:
                trade_type = "SHORT"

            # ─────────────────────────────────────────────────────────────
            # PERHITUNGAN STOP LOSS DINAMIS BERBASIS STRUKTUR (9 BUKU PDF & SMC):
            # Hapus penggunaan jarak SL statis $6 (60 pips).
            # - Untuk posisi SELL: Letakkan SL di atas swing high candle rejection / swing resistance.
            # - Untuk posisi BUY: Letakkan SL di bawah swing low terdekat.
            # - Rasio Risk-to-Reward (RR) minimal 1:1.5 mutlak!
            # ─────────────────────────────────────────────────────────────
            n_rows = len(df_with_ind)
            curr_pos = bar_idx if bar_idx >= 0 else (n_rows + bar_idx)
            start_pos = max(0, curr_pos - 15)
            recent_slice = df_with_ind.iloc[start_pos:curr_pos] if n_rows > 0 else pd.DataFrame()

            buffer_pips_usd = max(1.50, round(atr_safe * 0.4, 2))  # Buffer 15 - 25 pips di luar swing

            if target_sig_type == "SELL":
                if not recent_slice.empty and "High" in recent_slice.columns:
                    swing_high = float(recent_slice["High"].max())
                else:
                    swing_high = float(curr_row.get("High", curr_price))
                curr_high = float(curr_row.get("High", curr_price))
                structural_resistance = max(swing_high, curr_high)
                sl_dist_structural = round((structural_resistance + buffer_pips_usd) - curr_price, 2)
                sl_distance = max(sl_dist_structural, round(atr_safe * 1.5, 2), 4.00)
                sl_price = round(curr_price + sl_distance, 2)
            else:  # BUY
                if not recent_slice.empty and "Low" in recent_slice.columns:
                    swing_low = float(recent_slice["Low"].min())
                else:
                    swing_low = float(curr_row.get("Low", curr_price))
                curr_low = float(curr_row.get("Low", curr_price))
                structural_support = min(swing_low, curr_low)
                sl_dist_structural = round(curr_price - (structural_support - buffer_pips_usd), 2)
                sl_distance = max(sl_dist_structural, round(atr_safe * 1.5, 2), 4.00)
                sl_price = round(curr_price - sl_distance, 2)

            # Target Take Profit dengan rasio Risk-to-Reward (RR) minimal 1:1.5
            rr_target = 3.0 if trade_type == "LONG" else 1.5
            tp_distance = round(sl_distance * rr_target, 2)

            if target_sig_type == "SELL":
                tp_price = round(curr_price - tp_distance, 2)
                risk_dist = max(sl_price - curr_price, 0.01)
                rrr = round((curr_price - tp_price) / risk_dist, 2)
            else:
                tp_price = round(curr_price + tp_distance, 2)
                risk_dist = max(curr_price - sl_price, 0.01)
                rrr = round((tp_price - curr_price) / risk_dist, 2)

            market_regime = (
                f"{session_name} {trade_type} Struktural (TP {int(tp_distance*10)}p & SL {int(sl_distance*10)}p, R:R {rrr:.1f}:1)"
                + (" [HIGH-VOL]" if is_high_vol else "")
            )

            if is_retest_sig:
                retest_badge = "[RETEST DISKON] " if target_sig_type == "BUY" else "[RETEST PREMIUM] "
                market_regime = f"{retest_badge}{market_regime}"
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

        # Filter Deteksi Jebakan Likuiditas Sesi London (Anti-Judas Swing)
        judas_trap = False
        judas_reason = ""
        enable_judas = self.config.get("mt5", {}).get("enable_judas_swing_filter", True)
        if is_london_session and enable_judas and apply_pdf_filter:
            judas_trap, judas_reason = self.check_london_judas_swing(
                df=df_with_ind,
                curr_price=curr_price,
                signal_type=target_sig_type,
                curr_row=curr_row,
            )

        # ═══════════════════════════════════════════════════════════════════════
        # FILTER ANTI-PUCUK & ANTI-DASAR JURANG (Martin Pring + Bob Volman)
        # ═══════════════════════════════════════════════════════════════════════
        # Sumber Teori:
        #   Buku 5 (Martin J. Pring): BUY saat RSI jenuh beli (≥68) = BELI DI PUCUK.
        #     Distribusi institusi sedang berlangsung. Potensi reversal tinggi.
        #   Buku 3 (Bob Volman): Harga yang terlalu jauh dari EMA20 (overextended)
        #     akan revert ke mean. Entry saat overextended = masuk saat momentum sudah habis.
        # ═══════════════════════════════════════════════════════════════════════
        rsi_extreme_reject = False
        rsi_extreme_reason = ""
        ema_overextended_reject = False
        ema_overextended_reason = ""

        if is_gold and apply_pdf_filter:
            mt5_cfg_filt = self.config.get("mt5", {})
            rsi_ob_block = float(mt5_cfg_filt.get("rsi_overbought_block", 68.0))
            rsi_os_block = float(mt5_cfg_filt.get("rsi_oversold_block", 32.0))
            max_ema_dist_mult = float(mt5_cfg_filt.get("max_ema_distance_atr_mult", 1.5))

            rsi_now = float(curr_row.get("rsi", 50.0) or 50.0)
            ema20_now = float(curr_row.get("ema_20", curr_price) or curr_price)
            # Gunakan atr_safe jika sudah dihitung (is_gold branch pasti sudah), fallback atr_val
            atr_now = float(curr_row.get("atr", 3.0) or 3.0)
            # Sinkronkan clamp ATR dengan nilai yang sama pada kalkulasi SL/TP di atas (8.0 max)
            atr_clamp = max(min(atr_now, 8.0), 2.5)

            # FILTER 1: Anti-Beli di Pucuk / Anti-Jual di Dasar Jurang (Martin Pring)
            if target_sig_type == "BUY" and rsi_now >= rsi_ob_block:
                rsi_extreme_reject = True
                rsi_extreme_reason = (
                    f"🚫 [FILTER ANTI-PUCUK] BUY ditolak. RSI={rsi_now:.1f} ≥ {rsi_ob_block:.0f} "
                    f"(Zona Overbought Jenuh Beli). Kaidah Martin Pring: Beli di pucuk saat RSI jenuh "
                    f"= kena giliran distribusi institusi. Wajib tunggu RSI turun ke zona sehat (<65)."
                )
            elif target_sig_type == "SELL" and rsi_now <= rsi_os_block:
                rsi_extreme_reject = True
                rsi_extreme_reason = (
                    f"🚫 [FILTER ANTI-DASAR JURANG] SELL ditolak. RSI={rsi_now:.1f} ≤ {rsi_os_block:.0f} "
                    f"(Zona Oversold Jenuh Jual). Kaidah Martin Pring: Jual di dasar saat RSI jenuh "
                    f"= kena giliran akumulasi/bounce institusi. Wajib tunggu RSI naik ke zona sehat (>35)."
                )

            # FILTER 2: Anti-Kejar Harga Overextended dari EMA20 (Bob Volman)
            if not rsi_extreme_reject:
                price_dist_ema = abs(curr_price - ema20_now)
                # Di Sesi London (12:00 - 17:00 WIB), toleransi diperketat menjadi maksimal 2.50 USD (25 pips)
                # Kaidah Bob Volman: Masuk di sesi London wajib di dekat 20 EMA, dilarang entry saat harga overextended!
                if is_london_session:
                    max_allowed_dist = min(atr_clamp * max_ema_dist_mult, 2.50)
                else:
                    max_allowed_dist = atr_clamp * max_ema_dist_mult

                if price_dist_ema > max_allowed_dist:
                    ema_overextended_reject = True
                    ema_overextended_reason = (
                        f"🚫 [FILTER ANTI-KEJAR LILIN BOB VOLMAN] {target_sig_type} ditolak. "
                        f"Harga (${curr_price:.2f}) terlalu jauh dari EMA20 (${ema20_now:.2f}): "
                        f"jarak ${price_dist_ema:.2f} > batas aman ${max_allowed_dist:.2f} (Kaidah Sesi London). "
                        f"Kaidah Bob Volman: Dilarang entry saat harga overextended meninggalkan 20 EMA. "
                        f"Wajib tunggu pullback retest ke 20 EMA!"
                    )

        # Filter Khusus Sesi London: Wajib konfirmasi H1 (1-Hour) searah tren (Jam 12:00 - 17:00 WIB)
        # Sesuai arahan pengguna: Menghentikan manipulasi pembukaan Eropa & London
        h1_ok = True
        h1_reason = ""
        enable_h1_london = self.config.get("mt5", {}).get("london_h1_confirmation", True)
        london_h1_max_hour = int(self.config.get("mt5", {}).get("london_h1_max_hour", 17))
        is_london_h1_time = False

        if is_london_session:
            from zoneinfo import ZoneInfo
            from datetime import time as dtime
            if isinstance(bar_dt, pd.Timestamp):
                ts_wib = bar_dt.tz_convert(ZoneInfo("Asia/Jakarta")) if bar_dt.tzinfo else bar_dt.tz_localize(ZoneInfo("Asia/Jakarta"))
            elif isinstance(bar_dt, datetime):
                ts_wib = bar_dt.astimezone(ZoneInfo("Asia/Jakarta")) if bar_dt.tzinfo else bar_dt.replace(tzinfo=ZoneInfo("Asia/Jakarta"))
            else:
                ts_wib = datetime.now(ZoneInfo("Asia/Jakarta"))

            # Wajib H1 berlaku mulai jam 12:00 (Pre-London) sampai maksimal jam 16:00 WIB (jam 4 sore)
            is_london_h1_time = dtime(12, 0) <= ts_wib.time() < dtime(london_h1_max_hour, 0)

        if is_london_session and is_london_h1_time and enable_h1_london and df_h1 is not None and apply_pdf_filter:
            h1_ok, h1_reason = self.validate_london_h1_confirmation(
                sig_type=target_sig_type,
                df_h1=df_h1,
                curr_price=curr_price,
            )

        # ═══════════════════════════════════════════════════════════════════════
        # LAPIS 1: OTAK UTAMA (BIAS DAN IZIN H4) - Murphy, Ichimoku, Pring
        # Kaidah PDF Section 2, 3, 4, 5, 25:
        # H4 adalah CONTEXT, BUKAN penentu langsung arah BUY/SELL.
        # - SHORT (Scalping): Selalu diizinkan mencari setup BUY maupun SELL
        #   baik saat H4 Bullish, Bearish, maupun Neutral / Sideways.
        # - LONG (Intraday/Swing): Boleh mencari BUY maupun SELL jika setup valid.
        #   Namun pada H4 Neutral / Sideways, LONG DEFAULT WAITING sampai
        #   terdapat setup yang sangat kuat (score >= 90).
        # ═══════════════════════════════════════════════════════════════════════
        macro_blocked = False
        macro_block_reason = ""
        if is_gold and apply_pdf_filter:
            if trade_type == "LONG":
                if macro_bias == "NETRAL":
                    if pdf_score < 90.0:
                        macro_blocked = True
                        macro_block_reason = (
                            f"🛑 [LAPIS 1: OTAK UTAMA H4] LONG Setup WAITING: Bias Makro NETRAL/SIDEWAYS ({macro_reason}). "
                            f"Kaidah Section 5: H4 Neutral membuat LONG default WAITING sampai terdapat setup memadai."
                        )
            elif trade_type == "SHORT":
                # SHORT scalping diizinkan di H4 Bullish, Bearish, maupun Neutral
                macro_blocked = False

        # TRAP_RISK Filter (Section 11, 30: Pisau jatuh / Jebakan likuiditas dilarang eksekusi)
        trap_blocked = False
        trap_block_reason = ""
        if is_gold and apply_pdf_filter:
            if active_smc_liq.state == "TRAP_RISK":
                trap_blocked = True
                trap_reasons_str = "; ".join(active_smc_liq.trap_reasons) if active_smc_liq.trap_reasons else "Jebakan likuiditas"
                trap_block_reason = (
                    f"🛑 [LIQUIDITY TRAP_RISK] {target_sig_type} ditolak: {trap_reasons_str}. "
                    f"Kaidah Section 11 & 30: Pisau jatuh tanpa sweep + reclaim dilarang dieksekusi."
                )

        if is_buy:
            active_vetoes = []
            if macro_blocked:
                active_vetoes.append(macro_block_reason)
            if trap_blocked:
                active_vetoes.append(trap_block_reason)
            if rsi_extreme_reject:
                active_vetoes.append(rsi_extreme_reason)
            if judas_trap:
                active_vetoes.append(judas_reason)
            if not h1_ok:
                active_vetoes.append(h1_reason)

            if active_vetoes:
                signal = "HOLD"
                reasons = active_vetoes
            elif ema_overextended_reject:
                enable_limit_orders = bool(self.config.get("mt5", {}).get("enable_limit_orders", True))
                always_limit = bool(self.config.get("mt5", {}).get("always_use_limit_orders", False))
                min_limit_pips = float(self.config.get("mt5", {}).get("min_limit_distance_pips", 15.0))
                min_limit_dist = min_limit_pips / 10.0
                can_place_buy_limit = (
                    enable_limit_orders
                    and is_gold
                    and apply_pdf_filter
                    and (pdf_approved or (always_limit and pdf_score >= 65.0) or pdf_score >= 80.0)
                )
                ema20_lvl = round(float(curr_row.get("ema_20", curr_price) or curr_price), 2)
                if can_place_buy_limit and ema20_lvl <= round(curr_price - min_limit_dist, 2):
                    signal = "BUY_LIMIT"
                    limit_price_val = ema20_lvl
                    is_limit_order_sig = True
                    limit_order_type_val = "BUY_LIMIT"
                    sl_dist_lim = max(6.00, sl_distance)
                    tp_dist_lim = max(6.00, max(sl_dist_lim, tp_distance))
                    sl_price = round(limit_price_val - sl_dist_lim, 2)
                    tp_price = round(limit_price_val + tp_dist_lim, 2)
                    rrr = round(tp_dist_lim / sl_dist_lim, 2)
                    reasons = [
                        f"🟡 [PENDING ORDER SNIPER] BUY LIMIT dipasang di ${limit_price_val:,.2f} (Retest 20 EMA Support)",
                        f"🛡️ Kaidah Anti-Kejar Lilin Bob Volman: Harga live (${curr_price:,.2f}) overextended. Order limit dipasang di bawah menjemput pullback retest!",
                        f"Lapis 1 (Otak Utama H4): {macro_bias}",
                        f"Lapis 2 ({entry_pathway}): {setup_grade} ({pdf_score:.0f}%)",
                    ]
                else:
                    signal = "HOLD"
                    reasons = [ema_overextended_reason]
            elif apply_pdf_filter and not pdf_approved:
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
                reasons.append(f"Lapis 1 (Otak Utama H4): {macro_bias}")
                reasons.append(f"Lapis 2 ({entry_pathway}): {setup_grade} ({pdf_score:.0f}%)")
                if is_london_session:
                    reasons.append(f"🛡️ Sesi London: Terkonfirmasi Kuat ({pdf_score:.0f}% >= 75%) Lolos Filter Anti-Manipulasi")
                    if h1_reason:
                        reasons.append(h1_reason)
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
            else:
                active_vetoes = []
                if macro_blocked:
                    active_vetoes.append(macro_block_reason)
                if trap_blocked:
                    active_vetoes.append(trap_block_reason)
                if rsi_extreme_reject:
                    active_vetoes.append(rsi_extreme_reason)
                if judas_trap:
                    active_vetoes.append(judas_reason)
                if not h1_ok:
                    active_vetoes.append(h1_reason)

                if active_vetoes:
                    signal = "HOLD"
                    reasons = active_vetoes
                elif ema_overextended_reject:
                    enable_limit_orders = bool(self.config.get("mt5", {}).get("enable_limit_orders", True))
                    always_limit = bool(self.config.get("mt5", {}).get("always_use_limit_orders", False))
                    min_limit_pips = float(self.config.get("mt5", {}).get("min_limit_distance_pips", 15.0))
                    min_limit_dist = min_limit_pips / 10.0
                    can_place_sell_limit = (
                        enable_limit_orders
                        and is_gold
                        and apply_pdf_filter
                        and (pdf_approved or (always_limit and pdf_score >= 65.0) or pdf_score >= 80.0)
                    )
                    ema20_lvl = round(float(curr_row.get("ema_20", curr_price) or curr_price), 2)
                    if can_place_sell_limit and ema20_lvl >= round(curr_price + min_limit_dist, 2):
                        signal = "SELL_LIMIT"
                        limit_price_val = ema20_lvl
                        is_limit_order_sig = True
                        limit_order_type_val = "SELL_LIMIT"
                        sl_dist_lim = max(6.00, sl_distance)
                        tp_dist_lim = max(6.00, max(sl_dist_lim, tp_distance))
                        sl_price = round(limit_price_val + sl_dist_lim, 2)
                        tp_price = round(limit_price_val - tp_dist_lim, 2)
                        rrr = round(tp_dist_lim / sl_dist_lim, 2)
                        reasons = [
                            f"🟡 [PENDING ORDER SNIPER] SELL LIMIT dipasang di ${limit_price_val:,.2f} (Retest 20 EMA Resistance)",
                            f"🛡️ Kaidah Anti-Kejar Lilin Bob Volman: Harga live (${curr_price:,.2f}) overextended. Order limit dipasang di atas menjemput pullback retest!",
                            f"Lapis 1 (Otak Utama H4): {macro_bias}",
                            f"Lapis 2 ({entry_pathway}): {setup_grade} ({pdf_score:.0f}%)",
                        ]
                    else:
                        signal = "HOLD"
                        reasons = [ema_overextended_reason]
                elif apply_pdf_filter and not pdf_approved:
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
                    reasons.append(f"Lapis 1 (Otak Utama H4): {macro_bias}")
                    reasons.append(f"Lapis 2 ({entry_pathway}): {setup_grade} ({pdf_score:.0f}%)")
                    if is_london_session:
                        reasons.append(f"🛡️ Sesi London: Terkonfirmasi Kuat ({pdf_score:.0f}% >= 75%) Lolos Filter Anti-Manipulasi")
                        if h1_reason:
                            reasons.append(h1_reason)
        else:
            # Jika sinyal dasar masih netral namun telaah 9 Buku PDF membuktikan Grade A (>=65% atau >=75% di London)
            min_promo_score = london_min_score if is_london_session else 65.0
            active_vetoes = []
            if macro_blocked:
                active_vetoes.append(macro_block_reason)
            if trap_blocked:
                active_vetoes.append(trap_block_reason)
            if rsi_extreme_reject:
                active_vetoes.append(rsi_extreme_reason)
            if judas_trap:
                active_vetoes.append(judas_reason)
            if not h1_ok:
                active_vetoes.append(h1_reason)

            if active_vetoes:
                signal = "HOLD"
                reasons = active_vetoes
            elif apply_pdf_filter and pdf_approved and pdf_score >= min_promo_score and is_gold and not ema_overextended_reject:
                if target_sig_type == "BUY" and curr_price >= snapshot.get("ema_50", 0.0):
                    signal = "BUY"
                    reasons = [
                        f"Lapis 1 (Otak Utama H4): {macro_bias}",
                        f"Lapis 2 ({entry_pathway}): {setup_grade} ({pdf_score:.0f}%)",
                        f"Tren Bullish di atas EMA 50 ({snapshot.get('ema_50', 0):.2f})",
                    ]
                    if is_london_session:
                        reasons.append(f"🛡️ Sesi London: Terkonfirmasi Kuat ({pdf_score:.0f}% >= 75%) Lolos Filter Anti-Manipulasi")
                        if h1_reason:
                            reasons.append(h1_reason)
                    if patterns_detected:
                        reasons.append(f"Pola: {', '.join(patterns_detected[:2])}")
                elif target_sig_type == "SELL" and curr_price <= snapshot.get("ema_50", 0.0):
                    signal = "SELL"
                    reasons = [
                        f"Lapis 1 (Otak Utama H4): {macro_bias}",
                        f"Lapis 2 ({entry_pathway}): {setup_grade} ({pdf_score:.0f}%)",
                        f"Tren Bearish di bawah EMA 50 ({snapshot.get('ema_50', 0):.2f})",
                    ]
                    if is_london_session:
                        reasons.append(f"🛡️ Sesi London: Terkonfirmasi Kuat ({pdf_score:.0f}% >= 75%) Lolos Filter Anti-Manipulasi")
                        if h1_reason:
                            reasons.append(h1_reason)
                    if patterns_detected:
                        reasons.append(f"Pola: {', '.join(patterns_detected[:2])}")
                else:
                    signal = "HOLD"
                    reasons = [
                        f"Kondisi netral / menunggu konfluensi waktu masuk. RSI={snapshot['rsi']:.1f}, "
                        f"Close={curr_price:.0f}, EMA50={snapshot['ema_50']:.0f}, "
                        f"Vol Ratio={snapshot['volume_ratio']:.2f}x"
                    ]
            elif ema_overextended_reject and is_gold and bool(self.config.get("mt5", {}).get("enable_limit_orders", True)) and apply_pdf_filter and (pdf_approved or (bool(self.config.get("mt5", {}).get("always_use_limit_orders", False)) and pdf_score >= 65.0) or pdf_score >= 80.0):
                min_limit_pips = float(self.config.get("mt5", {}).get("min_limit_distance_pips", 15.0))
                min_limit_dist = min_limit_pips / 10.0
                ema20_lvl = round(float(curr_row.get("ema_20", curr_price) or curr_price), 2)
                if target_sig_type == "SELL" and ema20_lvl >= round(curr_price + min_limit_dist, 2):
                    signal = "SELL_LIMIT"
                    limit_price_val = ema20_lvl
                    is_limit_order_sig = True
                    limit_order_type_val = "SELL_LIMIT"
                    sl_dist_lim = max(6.00, sl_distance)
                    tp_dist_lim = max(6.00, max(sl_dist_lim, tp_distance))
                    sl_price = round(limit_price_val + sl_dist_lim, 2)
                    tp_price = round(limit_price_val - tp_dist_lim, 2)
                    rrr = round(tp_dist_lim / sl_dist_lim, 2)
                    reasons = [
                        f"🟡 [PENDING ORDER SNIPER] SELL LIMIT dipasang di ${limit_price_val:,.2f} (Retest 20 EMA Resistance)",
                        f"🛡️ Kaidah Anti-Kejar Lilin Bob Volman: Harga live (${curr_price:,.2f}) overextended. Order limit dipasang di atas menjemput pullback retest!",
                        f"Lapis 1 (Otak Utama H4): {macro_bias}",
                        f"Lapis 2 ({entry_pathway}): {setup_grade} ({pdf_score:.0f}%)",
                    ]
                elif target_sig_type == "BUY" and ema20_lvl <= round(curr_price - min_limit_dist, 2):
                    signal = "BUY_LIMIT"
                    limit_price_val = ema20_lvl
                    is_limit_order_sig = True
                    limit_order_type_val = "BUY_LIMIT"
                    sl_dist_lim = max(6.00, sl_distance)
                    tp_dist_lim = max(6.00, max(sl_dist_lim, tp_distance))
                    sl_price = round(limit_price_val - sl_dist_lim, 2)
                    tp_price = round(limit_price_val + tp_dist_lim, 2)
                    rrr = round(tp_dist_lim / sl_dist_lim, 2)
                    reasons = [
                        f"🟡 [PENDING ORDER SNIPER] BUY LIMIT dipasang di ${limit_price_val:,.2f} (Retest 20 EMA Support)",
                        f"🛡️ Kaidah Anti-Kejar Lilin Bob Volman: Harga live (${curr_price:,.2f}) overextended. Order limit dipasang di bawah menjemput pullback retest!",
                        f"Lapis 1 (Otak Utama H4): {macro_bias}",
                        f"Lapis 2 ({entry_pathway}): {setup_grade} ({pdf_score:.0f}%)",
                    ]
                else:
                    signal = "HOLD"
                    reasons = [ema_overextended_reason]
            else:
                signal = "HOLD"
                reasons = [
                    ema_overextended_reason if ema_overextended_reject else (
                        f"Kondisi netral / menunggu konfluensi waktu masuk. RSI={snapshot['rsi']:.1f}, "
                        f"Close={curr_price:.0f}, EMA50={snapshot['ema_50']:.0f}, "
                        f"Vol Ratio={snapshot['volume_ratio']:.2f}x"
                    )
                ]

        # OPSI 2 (Murni Sniper Limit): 100% Selalu Pasang Pending Limit Order (BUY LIMIT & SELL LIMIT)
        always_limit = (
            bool(self.config.get("mt5", {}).get("always_use_limit_orders", False))
            and is_gold
            and apply_pdf_filter
            and signal in ["BUY", "SELL"]
        )
        if always_limit:
            min_limit_pips = float(self.config.get("mt5", {}).get("min_limit_distance_pips", 15.0))
            min_limit_dist = min_limit_pips / 10.0
            ema20_lvl = round(float(curr_row.get("ema_20", curr_price) or curr_price), 2)

            if signal == "BUY":
                signal = "BUY_LIMIT"
                is_limit_order_sig = True
                limit_order_type_val = "BUY_LIMIT"
                # Tempatkan di 20 EMA atau minimal 15 pips di bawah harga pasar live (diskon)
                if ema20_lvl <= round(curr_price - min_limit_dist, 2):
                    limit_price_val = ema20_lvl
                else:
                    limit_price_val = round(curr_price - min_limit_dist, 2)

                sl_dist_lim = max(6.00, sl_distance)
                if trade_type == "LONG":
                    tp_dist_lim = max(18.00, round(sl_dist_lim * 3.0, 2))
                    rrr = 3.0
                else:
                    tp_dist_lim = max(6.00, sl_dist_lim)
                    rrr = 1.0
                sl_price = round(limit_price_val - sl_dist_lim, 2)
                tp_price = round(limit_price_val + tp_dist_lim, 2)
                reasons.insert(0, f"🟡 [SNIPER LIMIT ORDER] BUY LIMIT dipasang di ${limit_price_val:,.2f} (Retest Diskon Support / 20 EMA)")

            elif signal == "SELL":
                signal = "SELL_LIMIT"
                is_limit_order_sig = True
                limit_order_type_val = "SELL_LIMIT"
                # Tempatkan di 20 EMA atau minimal 15 pips di atas harga pasar live (premium)
                if ema20_lvl >= round(curr_price + min_limit_dist, 2):
                    limit_price_val = ema20_lvl
                else:
                    limit_price_val = round(curr_price + min_limit_dist, 2)

                sl_dist_lim = max(6.00, sl_distance)
                if trade_type == "LONG":
                    tp_dist_lim = max(18.00, round(sl_dist_lim * 3.0, 2))
                    rrr = 3.0
                else:
                    tp_dist_lim = max(6.00, sl_dist_lim)
                    rrr = 1.0
                sl_price = round(limit_price_val + sl_dist_lim, 2)
                tp_price = round(limit_price_val - tp_dist_lim, 2)
                reasons.insert(0, f"🟡 [SNIPER LIMIT ORDER] SELL LIMIT dipasang di ${limit_price_val:,.2f} (Retest Premium Resistance / 20 EMA)")

        is_limit_type = signal in ["BUY_LIMIT", "SELL_LIMIT"]
        if is_limit_type and is_gold and bool(self.config.get("mt5", {}).get("enable_news_limit_guard", True)):
            try:
                from data.storage import StockStorage
                st = getattr(self, "storage", None) or StockStorage()
                nb_mins = int(self.config.get("mt5", {}).get("news_limit_guard_minutes_before", 10))
                na_mins = int(self.config.get("mt5", {}).get("news_limit_guard_minutes_after", 15))
                active_news = st.get_active_high_impact_news(mins_before=nb_mins, mins_after=na_mins)
                if active_news:
                    ev = active_news[0]
                    ev_title = ev.get("title", "High-Impact News")
                    ev_wib = ev.get("date_wib", "")
                    signal = "HOLD"
                    is_limit_type = False
                    is_limit_order_sig = False
                    reasons = [
                        f"🛡️ [NEWS GUARD] Dilarang pasang Pending Limit Order 10 menit sebelum & 15 menit setelah High-Impact News ({ev_title} pukul {ev_wib} WIB)!"
                    ]
            except Exception as e_sng:
                pass

        is_actionable = signal in ["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT"]
        final_price = limit_price_val if is_limit_type and limit_price_val is not None else curr_price

        # Multi-Level / Ladder Limit Orders (Dual-Sided Jaring: BUY LIMIT & SELL LIMIT)
        ladder_orders: List[Dict[str, Any]] = []
        if is_gold and bool(self.config.get("mt5", {}).get("enable_limit_orders", True)):
            ladder_orders = self.generate_dual_sided_limit_orders(
                df=df_with_ind,
                ticker=ticker,
                curr_price=curr_price,
                snapshot=snapshot,
                trade_type=trade_type,
                df_h1=df_h1,
                df_h4=df_h4,
            )

        if is_actionable and market_regime:
            reasons.append(f"Regime Pasar: {market_regime}")

        # ─── RANGKUMAN MASTER TRADING SPEC 43 BAGIAN ─────────────────────────
        selected_method = SMCLiquidityEngine.select_trading_method(
            structure=smc_struct,
            liquidity=active_smc_liq,
            direction=target_sig_type,
            is_retest=is_retest_sig,
        )

        h1_ctx = "NEUTRAL"
        if df_h1 is not None and not df_h1.empty:
            h1_struct_res = SMCLiquidityEngine.analyze_market_structure(df_h1)
            h1_ctx = h1_struct_res.trend
        else:
            h1_ctx = macro_bias

        if active_smc_liq.has_sweep_and_reclaim and active_smc_liq.sweep_type == "SELL_SIDE":
            m15_setup_desc = "SELL-SIDE LIQUIDITY SWEEP"
        elif active_smc_liq.has_sweep_and_reclaim and active_smc_liq.sweep_type == "BUY_SIDE":
            m15_setup_desc = "BUY-SIDE LIQUIDITY SWEEP"
        elif smc_struct.trend == "BEARISH":
            m15_setup_desc = "BEARISH CONTINUATION"
        elif smc_struct.trend == "BULLISH":
            m15_setup_desc = "BULLISH CONTINUATION"
        elif smc_struct.trend == "RANGE":
            m15_setup_desc = "RANGE EDGE"
        else:
            m15_setup_desc = "NORMAL"

        m5_trig_desc = "NO_TRIGGER"
        if df_m5 is not None and not df_m5.empty:
            m5_struct_res = SMCLiquidityEngine.analyze_market_structure(df_m5)
            if target_sig_type == "BUY" and (m5_struct_res.choch_bullish or m5_struct_res.bos_bullish):
                m5_trig_desc = "BULLISH CHoCH + DISPLACEMENT + RETEST" if m5_struct_res.choch_bullish else "BULLISH BOS"
            elif target_sig_type == "SELL" and (m5_struct_res.choch_bearish or m5_struct_res.bos_bearish):
                m5_trig_desc = "BEARISH CHoCH + DISPLACEMENT + RETEST" if m5_struct_res.choch_bearish else "BEARISH BOS"
        elif active_smc_liq.has_sweep_and_reclaim and smc_struct.choch_bullish:
            m5_trig_desc = "BULLISH CHoCH + DISPLACEMENT + RETEST"
        elif active_smc_liq.has_sweep_and_reclaim and smc_struct.choch_bearish:
            m5_trig_desc = "BEARISH CHoCH + DISPLACEMENT + RETEST"
        elif target_sig_type == "BUY" and smc_struct.bos_bullish:
            m5_trig_desc = "BULLISH BOS + RETEST"
        elif target_sig_type == "SELL" and smc_struct.bos_bearish:
            m5_trig_desc = "BEARISH BOS + RETEST"
        elif snapshot["pinbar"] or snapshot["rejection_wick"] >= 0.35:
            m5_trig_desc = "MOMENTUM REJECTION WICK"

        anti_chase_eval = SMCLiquidityEngine.evaluate_anti_chase(
            curr_price=curr_price,
            ema20=float(snapshot.get("ema_20", curr_price)),
            atr=float(curr_row.get("atr", 3.0)),
            is_london=is_london_session,
        )

        anti_chase_status = "PASS" if anti_chase_eval.passed else anti_chase_eval.status
        trap_risk_val = "HIGH" if active_smc_liq.state == "TRAP_RISK" else ("MEDIUM" if active_smc_liq.state == "CAUTION" else "LOW")
        spread_val = float(curr_row.get("spread_pips", 3.4) or 3.4)
        risk_lvl = "NORMAL"

        # Hitung skor konfluensi komprehensif SMC
        smc_conf = SMCLiquidityEngine.score_confluence(
            structure=smc_struct,
            liquidity=active_smc_liq,
            anti_chase=anti_chase_eval,
            m5_trigger_valid=(m5_trig_desc != "NO_TRIGGER"),
            price_action_confirmed=bool(snapshot["pinbar"] or snapshot["engulfing"] or snapshot["rejection_wick"] >= 0.35),
            displacement_confirmed=bool(float(snapshot.get("volume_ratio", 1.0)) >= 1.15),
            rr_val=rrr if is_actionable else 1.0,
            direction=target_sig_type,
            macro_bias_h4=macro_bias,
        )

        final_verdict = f"EXECUTE {trade_type} {target_sig_type}" if is_actionable else "WAIT"
        final_reason = reasons[0] if reasons else ("Setup valid terkonfirmasi konfluensi SMC." if is_actionable else "Menunggu konfirmasi setup pasar yang valid.")

        spec_report_txt = SMCLiquidityEngine.format_master_trading_spec_report(
            style=trade_type,
            direction=target_sig_type if is_actionable else "WAIT",
            method=selected_method,
            h4=macro_bias,
            h1=h1_ctx,
            m15=m15_setup_desc,
            m5=m5_trig_desc,
            structure=smc_struct.description,
            liquidity=active_smc_liq.description,
            liquidity_state=active_smc_liq.state,
            anti_chase=anti_chase_status,
            trap_risk=trap_risk_val,
            confluence_score=pdf_score if pdf_score > 0 else smc_conf.total_score,
            spread=spread_val,
            risk=risk_lvl,
            sl=sl_price if is_actionable else None,
            tp=tp_price if is_actionable else None,
            rr=rrr if is_actionable else None,
            verdict=final_verdict,
            reason=final_reason,
        )

        logger.debug(
            f"Evaluasi {ticker} ({target_strategy.name}) @ {candle_time}: "
            f"Signal={signal}, Price={final_price}, Reasons={reasons}"
        )

        return SignalResult(
            ticker=ticker,
            strategy_name=target_strategy.name,
            signal=signal,
            trade_type=trade_type,
            direction=target_sig_type if is_actionable else "HOLD",
            price=final_price,
            candle_time=candle_time,
            reasons=reasons,
            indicators_snapshot=snapshot,
            take_profit_price=tp_price if is_actionable else None,
            stop_loss_price=sl_price if is_actionable else None,
            risk_reward_ratio=rrr if is_actionable else None,
            pdf_confluence_score=pdf_score,
            setup_grade=setup_grade,
            pdf_confluence_details=pdf_checks,
            market_direction_prediction=direction_pred,
            market_regime=market_regime,
            macro_bias_h4=macro_bias,
            entry_pathway=entry_pathway,
            module_scores=module_scores,
            is_retest_entry=is_retest_sig,
            retest_details=retest_details_sig,
            is_limit_order=is_limit_type,
            limit_order_type=signal if is_limit_type else None,
            limit_price=limit_price_val if is_limit_type else None,
            limit_expiry_minutes=int(self.config.get("mt5", {}).get("limit_order_expiry_mins", 120)),
            ladder_limit_orders=ladder_orders,
            style=trade_type,
            method=selected_method,
            h4_context=macro_bias,
            h1_context=h1_ctx,
            m15_setup=m15_setup_desc,
            m5_trigger=m5_trig_desc,
            structure_desc=smc_struct.description,
            liquidity_desc=active_smc_liq.description,
            liquidity_state=active_smc_liq.state,
            anti_chase=anti_chase_status,
            trap_risk=trap_risk_val,
            confluence_score=pdf_score if pdf_score > 0 else smc_conf.total_score,
            spread_pips=spread_val,
            risk_level=risk_lvl,
            verdict=final_verdict,
            verdict_reason=final_reason,
            spec_report=spec_report_txt,
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
