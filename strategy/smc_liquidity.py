"""
Hermes 3D SMC & Liquidity Engine
Berdasarkan Master Trading Spec 43 Bagian:
- Multi-Timeframe Context (H4 / H1 / M15 / M5)
- Market Structure (HH, HL, LH, LL, BOS, CHoCH)
- Liquidity Engine (Swings, EQH, EQL, PDH, PDL, Asian High/Low, Sweep + Reclaim)
- Liquidity State Classification (SAFE, CAUTION, TRAP_RISK)
- Anti-Chase / Anti-FOMO Protection
- Method Selection & Confluence Scoring (0-100)
- Explainable Verdict & Formatting
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd
import numpy as np


@dataclass
class LiquidityLevel:
    level_type: str  # 'SWING_HIGH', 'SWING_LOW', 'EQH', 'EQL', 'PDH', 'PDL', 'ASIAN_HIGH', 'ASIAN_LOW'
    price: float
    description: str
    is_swept: bool = False
    is_reclaimed: bool = False


@dataclass
class MarketStructureResult:
    trend: str  # 'BULLISH', 'BEARISH', 'RANGE', 'NEUTRAL'
    swing_highs: List[float] = field(default_factory=list)
    swing_lows: List[float] = field(default_factory=list)
    has_hh_hl: bool = False
    has_lh_ll: bool = False
    bos_bullish: bool = False
    bos_bearish: bool = False
    choch_bullish: bool = False  # Bearish -> Bullish shift (broken last LH)
    choch_bearish: bool = False  # Bullish -> Bearish shift (broken last HL)
    recent_lh: Optional[float] = None
    recent_hl: Optional[float] = None
    description: str = "STRUCTURE_UNCLEAR"


@dataclass
class LiquidityAnalysisResult:
    state: str  # 'SAFE', 'CAUTION', 'TRAP_RISK'
    sweep_type: str  # 'NONE', 'SELL_SIDE', 'BUY_SIDE'
    swept_level: Optional[float] = None
    is_reclaimed: bool = False
    has_sweep_and_reclaim: bool = False
    nearest_opposing_liquidity: Optional[float] = None
    distance_to_opposing_usd: float = 999.0
    active_levels: List[LiquidityLevel] = field(default_factory=list)
    description: str = "NO_VALID_LIQUIDITY"
    trap_reasons: List[str] = field(default_factory=list)


@dataclass
class AntiChaseResult:
    passed: bool
    status: str  # 'PASS', 'FAIL_OVEREXTENDED', 'FAIL_CHASING'
    dist_from_ema20: float
    max_allowed_dist: float
    reason: str


@dataclass
class ConfluenceBreakdown:
    total_score: float  # 0 - 100
    market_structure_score: float  # 0 - 20
    liquidity_score: float  # 0 - 20
    trigger_score: float  # 0 - 20
    price_action_score: float  # 0 - 15
    displacement_score: float  # 0 - 15
    rr_and_room_score: float  # 0 - 10
    details: List[str] = field(default_factory=list)


class SMCLiquidityEngine:
    """
    Otak Analisis Smart Money Concepts, Struktur Pasar & Mesin Likuiditas.
    Mengikuti Master Trading Spec Section 4 s/d 43 secara ketat.
    """

    @staticmethod
    def detect_swing_points(
        highs: pd.Series,
        lows: pd.Series,
        window: int = 3,
    ) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
        """
        Mendeteksi swing highs dan swing lows lokal (Fractal logic).
        Returns: (swing_highs, swing_lows) sebagai list of (index, price)
        """
        sh_list: List[Tuple[int, float]] = []
        sl_list: List[Tuple[int, float]] = []
        n = len(highs)
        if n < window * 2 + 1:
            return sh_list, sl_list

        h_vals = highs.values
        l_vals = lows.values

        for i in range(window, n - window):
            # Swing High
            if all(h_vals[i] >= h_vals[i - k] for k in range(1, window + 1)) and \
               all(h_vals[i] >= h_vals[i + k] for k in range(1, window + 1)):
                sh_list.append((i, float(h_vals[i])))

            # Swing Low
            if all(l_vals[i] <= l_vals[i - k] for k in range(1, window + 1)) and \
               all(l_vals[i] <= l_vals[i + k] for k in range(1, window + 1)):
                sl_list.append((i, float(l_vals[i])))

        return sh_list, sl_list

    @classmethod
    def analyze_market_structure(
        cls,
        df: pd.DataFrame,
        window: int = 3,
    ) -> MarketStructureResult:
        """
        Analisis Struktur Pasar SMC:
        - Higher High (HH) & Higher Low (HL)
        - Lower High (LH) & Lower Low (LL)
        - BOS (Break of Structure - kelanjutan)
        - CHoCH (Change of Character - pembalikan awal)
        """
        if df.empty or len(df) < 6:
            return MarketStructureResult(trend="NEUTRAL", description="STRUCTURE_UNCLEAR")

        highs = df["High"] if "High" in df.columns else df["high"]
        lows = df["Low"] if "Low" in df.columns else df["low"]
        closes = df["Close"] if "Close" in df.columns else df["close"]

        curr_close = float(closes.iloc[-1])
        curr_high = float(highs.iloc[-1])
        curr_low = float(lows.iloc[-1])

        sh_pts, sl_pts = cls.detect_swing_points(highs, lows, window=window)

        # Jika swing points sedikit, gunakan min/max rolling sebagai fallback
        sh_prices = [p for _, p in sh_pts]
        sl_prices = [p for _, p in sl_pts]

        if len(sh_prices) < 2 or len(sl_prices) < 2:
            # Fallback swing
            p1_high = float(highs.iloc[-15:-7].max()) if len(df) >= 15 else float(highs.max())
            p2_high = float(highs.iloc[-7:-1].max()) if len(df) >= 7 else float(highs.max())
            p1_low = float(lows.iloc[-15:-7].min()) if len(df) >= 15 else float(lows.min())
            p2_low = float(lows.iloc[-7:-1].min()) if len(df) >= 7 else float(lows.min())
            sh_prices = [p1_high, p2_high]
            sl_prices = [p1_low, p2_low]

        # Evaluasi urutan Swing
        has_hh = sh_prices[-1] > sh_prices[-2] if len(sh_prices) >= 2 else False
        has_hl = sl_prices[-1] > sl_prices[-2] if len(sl_prices) >= 2 else False
        has_lh = sh_prices[-1] < sh_prices[-2] if len(sh_prices) >= 2 else False
        has_ll = sl_prices[-1] < sl_prices[-2] if len(sl_prices) >= 2 else False

        has_hh_hl = has_hh and has_hl
        has_lh_ll = has_lh and has_ll

        # Tentukan Tren Dasar
        if has_hh_hl:
            trend = "BULLISH"
        elif has_lh_ll:
            trend = "BEARISH"
        elif has_ll or has_lh:
            trend = "BEARISH"
        elif has_hh or has_hl:
            trend = "BULLISH"
        else:
            trend = "RANGE"

        # BOS (Break of Structure):
        # Bullish BOS: Close > Swing High terakhir dalam tren Bullish
        recent_sh = max(sh_prices[-1], sh_prices[-2]) if len(sh_prices) >= 2 else sh_prices[-1]
        recent_sl = min(sl_prices[-1], sl_prices[-2]) if len(sl_prices) >= 2 else sl_prices[-1]

        bos_bullish = curr_close > sh_prices[-1] and trend == "BULLISH"
        bos_bearish = curr_close < sl_prices[-1] and trend == "BEARISH"

        # CHoCH (Change of Character):
        # Bullish CHoCH: Dalam struktur Bearish (LH/LL), harga menembus ke atas Lower High (LH) terakhir!
        # Bearish CHoCH: Dalam struktur Bullish (HH/HL), harga menembus ke bawah Higher Low (HL) terakhir!
        choch_bullish = False
        choch_bearish = False
        recent_lh = None
        recent_hl = None

        if trend == "BEARISH" or has_lh or has_ll:
            recent_lh = sh_prices[-1]
            if curr_close > recent_lh or curr_high > recent_lh:
                choch_bullish = True

        if trend == "BULLISH" or has_hh or has_hl:
            recent_hl = sl_prices[-1]
            if curr_close < recent_hl or curr_low < recent_hl:
                choch_bearish = True

        # Rangkum deskripsi
        if choch_bullish:
            desc = f"Bullish CHoCH (Break di atas LH ${recent_lh:.2f})"
        elif choch_bearish:
            desc = f"Bearish CHoCH (Break di bawah HL ${recent_hl:.2f})"
        elif bos_bullish:
            desc = f"Bullish BOS (Continuation di atas ${sh_prices[-1]:.2f})"
        elif bos_bearish:
            desc = f"Bearish BOS (Continuation di bawah ${sl_prices[-1]:.2f})"
        elif has_lh_ll:
            desc = "Bearish LH/LL Intact"
        elif has_hh_hl:
            desc = "Bullish HH/HL Intact"
        else:
            desc = "Range / Konsolidasi"

        return MarketStructureResult(
            trend=trend,
            swing_highs=sh_prices,
            swing_lows=sl_prices,
            has_hh_hl=has_hh_hl,
            has_lh_ll=has_lh_ll,
            bos_bullish=bos_bullish,
            bos_bearish=bos_bearish,
            choch_bullish=choch_bullish,
            choch_bearish=choch_bearish,
            recent_lh=recent_lh,
            recent_hl=recent_hl,
            description=desc,
        )

    @classmethod
    def analyze_liquidity(
        cls,
        df: pd.DataFrame,
        structure: MarketStructureResult,
        intended_direction: str = "BUY",
        lookback_bars: int = 30,
        eq_tolerance_usd: float = 1.0,
    ) -> LiquidityAnalysisResult:
        """
        Mesin Likuiditas SMC (Section 9 s/d 12):
        - Mengidentifikasi kolam likuiditas (Swing High/Low, EQH, EQL, PDH, PDL)
        - Memeriksa Liquidity Sweep (Sell-side vs Buy-side)
        - Memeriksa Reclaim (tutup candle kembali melewati level yang disapu)
        - Mengklasifikasikan Liquidity State: SAFE, CAUTION, atau TRAP_RISK
        """
        if df.empty:
            return LiquidityAnalysisResult(
                state="TRAP_RISK",
                sweep_type="NONE",
                description="NO_VALID_LIQUIDITY",
                trap_reasons=["Data pasar kosong"],
            )

        highs = df["High"] if "High" in df.columns else df["high"]
        lows = df["Low"] if "Low" in df.columns else df["low"]
        closes = df["Close"] if "Close" in df.columns else df["close"]
        opens = df["Open"] if "Open" in df.columns else df["open"]

        curr_close = float(closes.iloc[-1])
        curr_open = float(opens.iloc[-1])
        curr_high = float(highs.iloc[-1])
        curr_low = float(lows.iloc[-1])

        # Candle sebelumnya untuk memeriksa sweep dalam 1-3 bar terakhir
        slice_df = df.tail(lookback_bars)
        recent_sh = structure.swing_highs
        recent_sl = structure.swing_lows

        levels: List[LiquidityLevel] = []

        # 1. Swing Highs & Lows
        for sh in recent_sh[-3:]:
            levels.append(LiquidityLevel(
                level_type="SWING_HIGH",
                price=sh,
                description=f"Buy-Side Liquidity (Swing High ${sh:.2f})",
            ))

        for sl in recent_sl[-3:]:
            levels.append(LiquidityLevel(
                level_type="SWING_LOW",
                price=sl,
                description=f"Sell-Side Liquidity (Swing Low ${sl:.2f})",
            ))

        # Tambahkan level terendah/tertinggi sebelum bar terakhir (prior extremes)
        prior_lows = lows.iloc[:-1] if len(lows) > 1 else lows
        prior_highs = highs.iloc[:-1] if len(highs) > 1 else highs
        if len(prior_lows) >= 2:
            prior_min_l = float(prior_lows.min())
            if not any(abs(lvl.price - prior_min_l) < 0.2 for lvl in levels if lvl.level_type == "SWING_LOW"):
                levels.append(LiquidityLevel(
                    level_type="SWING_LOW",
                    price=prior_min_l,
                    description=f"Sell-Side Liquidity (Prior Min Low ${prior_min_l:.2f})",
                ))

        if len(prior_highs) >= 2:
            prior_max_h = float(prior_highs.max())
            if not any(abs(lvl.price - prior_max_h) < 0.2 for lvl in levels if lvl.level_type == "SWING_HIGH"):
                levels.append(LiquidityLevel(
                    level_type="SWING_HIGH",
                    price=prior_max_h,
                    description=f"Buy-Side Liquidity (Prior Max High ${prior_max_h:.2f})",
                ))

        # 2. Equal Highs (EQH) & Equal Lows (EQL)
        if len(recent_sh) >= 2:
            if abs(recent_sh[-1] - recent_sh[-2]) <= eq_tolerance_usd:
                eqh_val = max(recent_sh[-1], recent_sh[-2])
                levels.append(LiquidityLevel(
                    level_type="EQH",
                    price=eqh_val,
                    description=f"Equal Highs (EQH ${eqh_val:.2f})",
                ))

        if len(recent_sl) >= 2:
            if abs(recent_sl[-1] - recent_sl[-2]) <= eq_tolerance_usd:
                eql_val = min(recent_sl[-1], recent_sl[-2])
                levels.append(LiquidityLevel(
                    level_type="EQL",
                    price=eql_val,
                    description=f"Equal Lows (EQL ${eql_val:.2f})",
                ))

        # 3. Previous Day / Session High/Low (jika ada data multi-day)
        if len(df) >= 24:  # ~6 jam M15
            prior_slice = df.iloc[-40:-10] if len(df) >= 40 else df.iloc[:-5]
            if not prior_slice.empty:
                pdh = float(prior_slice["High"].max()) if "High" in prior_slice.columns else float(prior_slice["high"].max())
                pdl = float(prior_slice["Low"].min()) if "Low" in prior_slice.columns else float(prior_slice["low"].min())
                levels.append(LiquidityLevel(level_type="PDH", price=pdh, description=f"PDH / Session High (${pdh:.2f})"))
                levels.append(LiquidityLevel(level_type="PDL", price=pdl, description=f"PDL / Session Low (${pdl:.2f})"))

        # 4. Deteksi Sweep & Reclaim dalam 5 candle terakhir
        sweep_type = "NONE"
        swept_level_val: Optional[float] = None
        is_reclaimed = False
        has_sweep_and_reclaim = False

        # Periksa Sell-Side Sweep (Low menembus level bawah, tapi Reclaim di atas level)
        sell_levels = [lvl for lvl in levels if lvl.level_type in ["SWING_LOW", "EQL", "PDL", "ASIAN_LOW"]]
        for sl_lvl in sell_levels:
            # Cari apakah ada candle di 5 bar terakhir yang menusuk di bawah sl_lvl.price
            for idx in range(-min(5, len(df)), 0):
                bar_low = float(lows.iloc[idx])
                bar_close = float(closes.iloc[idx])
                if bar_low < sl_lvl.price:
                    # Low menembus -> SWEEP!
                    sweep_type = "SELL_SIDE"
                    swept_level_val = sl_lvl.price
                    sl_lvl.is_swept = True
                    # Reclaim jika candle tersebut atau candle sekarang ditutup kembali di atas level
                    if curr_close > sl_lvl.price or bar_close > sl_lvl.price:
                        is_reclaimed = True
                        sl_lvl.is_reclaimed = True
                        has_sweep_and_reclaim = True
                    break
            if has_sweep_and_reclaim:
                break

        # Periksa Buy-Side Sweep (High menembus level atas, tapi Reclaim di bawah level)
        if sweep_type == "NONE":
            buy_levels = [lvl for lvl in levels if lvl.level_type in ["SWING_HIGH", "EQH", "PDH", "ASIAN_HIGH"]]
            for sh_lvl in buy_levels:
                for idx in range(-min(5, len(df)), 0):
                    bar_high = float(highs.iloc[idx])
                    bar_close = float(closes.iloc[idx])
                    if bar_high > sh_lvl.price:
                        sweep_type = "BUY_SIDE"
                        swept_level_val = sh_lvl.price
                        sh_lvl.is_swept = True
                        if curr_close < sh_lvl.price or bar_close < sh_lvl.price:
                            is_reclaimed = True
                            sh_lvl.is_reclaimed = True
                            has_sweep_and_reclaim = True
                        break
                if has_sweep_and_reclaim:
                    break

        # 5. Hitung Jarak ke Opposing Liquidity (Target / Invalidation)
        opposing_levels = []
        if intended_direction == "BUY":
            opposing_levels = [lvl.price for lvl in levels if lvl.price > curr_close and lvl.level_type in ["EQH", "PDH", "ASIAN_HIGH"]]
            nearest_opposing = min(opposing_levels) if opposing_levels else (curr_close + 20.0)
            dist_to_opposing = max(0.0, nearest_opposing - curr_close)
        else:  # SELL
            opposing_levels = [lvl.price for lvl in levels if lvl.price < curr_close and lvl.level_type in ["EQL", "PDL", "ASIAN_LOW"]]
            nearest_opposing = max(opposing_levels) if opposing_levels else (curr_close - 20.0)
            dist_to_opposing = max(0.0, curr_close - nearest_opposing)

        # 6. Klasifikasi Liquidity State (Section 11): SAFE, CAUTION, TRAP_RISK
        trap_reasons: List[str] = []

        # Aturan TRAP_RISK (Section 11, 30):
        # 1. BUY saat downtrend kuat (LH/LL) tanpa sweep + reclaim (falling knife!)
        if intended_direction == "BUY":
            if structure.has_lh_ll and not has_sweep_and_reclaim and not structure.choch_bullish:
                trap_reasons.append(
                    "BUY dalam Bearish Continuation kuat tanpa Sell-Side Sweep + Reclaim "
                    "(Kaidah Section 30: Pisau Jatuh / Jebakan Pantulan Semu)."
                )
            if dist_to_opposing < 1.00 and opposing_levels:
                trap_reasons.append(
                    f"Entry BUY langsung menabrak Kolam Likuiditas Mayor (${nearest_opposing:.2f}, "
                    f"jarak hanya ${dist_to_opposing:.2f} < $1.00 USD)."
                )
            if sweep_type == "SELL_SIDE" and not is_reclaimed:
                trap_reasons.append("Sell-Side Sweep terjadi tapi BELUM direclaim (Breakdown lanjutan tanpa pantulan).")

        elif intended_direction == "SELL":
            if structure.has_hh_hl and not has_sweep_and_reclaim and not structure.choch_bearish:
                trap_reasons.append(
                    "SELL dalam Bullish Continuation kuat tanpa Buy-Side Sweep + Reclaim "
                    "(Jebakan Jual Melawan Tren Naik Tanpa Konfirmasi)."
                )
            if dist_to_opposing < 1.00 and opposing_levels:
                trap_reasons.append(
                    f"Entry SELL langsung menabrak Kolam Likuiditas Mayor (${nearest_opposing:.2f}, "
                    f"jarak hanya ${dist_to_opposing:.2f} < $1.00 USD)."
                )
            if sweep_type == "BUY_SIDE" and not is_reclaimed:
                trap_reasons.append("Buy-Side Sweep terjadi tapi BELUM direclaim (Breakout lanjutan tanpa penolakan).")

        # Tentukan State
        if trap_reasons:
            state = "TRAP_RISK"
        elif has_sweep_and_reclaim and ((intended_direction == "BUY" and sweep_type == "SELL_SIDE") or
                                        (intended_direction == "SELL" and sweep_type == "BUY_SIDE")):
            state = "SAFE"
        else:
            # Section 10: Normal continuation setup without sweep is CAUTION, not blocked!
            state = "CAUTION"

        # Deskripsi Likuiditas
        if has_sweep_and_reclaim:
            desc = f"{'Sell-Side' if sweep_type == 'SELL_SIDE' else 'Buy-Side'} Sweep + Reclaim (${swept_level_val:.2f})"
        elif sweep_type != "NONE":
            desc = f"{'Sell-Side' if sweep_type == 'SELL_SIDE' else 'Buy-Side'} Sweep (${swept_level_val:.2f}) Tanpa Reclaim"
        else:
            desc = "NO_VALID_LIQUIDITY"

        return LiquidityAnalysisResult(
            state=state,
            sweep_type=sweep_type,
            swept_level=swept_level_val,
            is_reclaimed=is_reclaimed,
            has_sweep_and_reclaim=has_sweep_and_reclaim,
            nearest_opposing_liquidity=nearest_opposing,
            distance_to_opposing_usd=dist_to_opposing,
            active_levels=levels,
            description=desc,
            trap_reasons=trap_reasons,
        )

    @staticmethod
    def evaluate_anti_chase(
        curr_price: float,
        ema20: float,
        atr: float,
        is_london: bool = False,
        mult: float = 1.5,
    ) -> AntiChaseResult:
        """
        Anti-FOMO / Anti-Chasing Evaluator (Section 15):
        Menolak entry jika harga sudah bergerak terlalu jauh meninggalkan 20 EMA / batas aman.
        """
        dist = abs(curr_price - ema20)
        atr_clamp = max(min(atr, 8.0), 2.5)
        max_dist = min(atr_clamp * mult, 2.50) if is_london else (atr_clamp * mult)

        if dist > max_dist:
            return AntiChaseResult(
                passed=False,
                status="FAIL_OVEREXTENDED",
                dist_from_ema20=dist,
                max_allowed_dist=max_dist,
                reason=f"Harga overextended (${dist:.2f} > batas ${max_dist:.2f}). Dilarang mengejar lilin!",
            )

        return AntiChaseResult(
            passed=True,
            status="PASS",
            dist_from_ema20=dist,
            max_allowed_dist=max_dist,
            reason="Posisi harga dekat dengan area nilai 20 EMA (Anti-Chase PASS).",
        )

    @staticmethod
    def select_trading_method(
        structure: MarketStructureResult,
        liquidity: LiquidityAnalysisResult,
        direction: str,
        is_retest: bool = False,
    ) -> str:
        """
        Method Selection (Section 18):
        - Liquidity Reversal
        - Trend Continuation
        - Pullback Retest
        - Breakout Reclaim
        - SMC Range Edge
        """
        if liquidity.has_sweep_and_reclaim:
            return "Liquidity Reversal"

        if is_retest:
            return "Pullback Retest"

        if (direction == "BUY" and structure.bos_bullish) or (direction == "SELL" and structure.bos_bearish):
            return "Trend Continuation"

        if structure.trend == "RANGE":
            return "SMC Range Edge"

        if liquidity.sweep_type != "NONE" and liquidity.is_reclaimed:
            return "Breakout Reclaim"

        return "Trend Continuation"

    @classmethod
    def score_confluence(
        cls,
        structure: MarketStructureResult,
        liquidity: LiquidityAnalysisResult,
        anti_chase: AntiChaseResult,
        m5_trigger_valid: bool,
        price_action_confirmed: bool,
        displacement_confirmed: bool,
        rr_val: float,
        direction: str,
        macro_bias_h4: str = "NEUTRAL",
    ) -> ConfluenceBreakdown:
        """
        Confluence Score 0 - 100 berdasarkan 6 faktor nyata (Section 17):
        1. Market structure (0-20)
        2. Liquidity context (0-20)
        3. Entry trigger quality (0-20)
        4. Price-action confirmation (0-15)
        5. Displacement / momentum (0-15)
        6. Risk/reward and room to liquidity (0-10)
        """
        details: List[str] = []

        # 1. Market Structure (0-20)
        struct_score = 0.0
        if direction == "BUY":
            if structure.choch_bullish:
                struct_score = 20.0
                details.append("Struktur: Bullish CHoCH pembalikan terkonfirmasi (+20)")
            elif structure.bos_bullish:
                struct_score = 18.0
                details.append("Struktur: Bullish BOS kelanjutan tren (+18)")
            elif structure.trend == "BULLISH":
                struct_score = 15.0
                details.append("Struktur: Tren Bullish HH/HL (+15)")
            elif structure.trend == "RANGE":
                struct_score = 10.0
                details.append("Struktur: Konsolidasi / Range (+10)")
            else:
                struct_score = 5.0
                details.append("Struktur: Melawan tren Bearish (+5)")
        else:  # SELL
            if structure.choch_bearish:
                struct_score = 20.0
                details.append("Struktur: Bearish CHoCH pembalikan terkonfirmasi (+20)")
            elif structure.bos_bearish:
                struct_score = 18.0
                details.append("Struktur: Bearish BOS kelanjutan tren (+18)")
            elif structure.trend == "BEARISH":
                struct_score = 15.0
                details.append("Struktur: Tren Bearish LH/LL (+15)")
            elif structure.trend == "RANGE":
                struct_score = 10.0
                details.append("Struktur: Konsolidasi / Range (+10)")
            else:
                struct_score = 5.0
                details.append("Struktur: Melawan tren Bullish (+5)")

        # 2. Liquidity Context (0-20)
        liq_score = 0.0
        if liquidity.state == "SAFE" and liquidity.has_sweep_and_reclaim:
            liq_score = 20.0
            details.append(f"Likuiditas: Sweep + Reclaim terkonfirmasi ({liquidity.description}) (+20)")
        elif liquidity.state == "CAUTION":
            liq_score = 12.0
            details.append("Likuiditas: Setup kelanjutan wajar tanpa jebakan (+12)")
        else:  # TRAP_RISK
            liq_score = 0.0
            details.append("Likuiditas: Potensi jebakan / TRAP_RISK (+0)")

        # 3. Entry Trigger Quality (0-20)
        trig_score = 0.0
        if m5_trigger_valid:
            trig_score = 20.0
            details.append("Trigger M5: Terkonfirmasi valid (CHoCH / BOS / Rejection) (+20)")
        else:
            trig_score = 5.0
            details.append("Trigger M5: Belum ada konfirmasi tegas (+5)")

        # 4. Price-Action Confirmation (0-15)
        pa_score = 0.0
        if price_action_confirmed:
            pa_score = 15.0
            details.append("Price Action: Candlestick Rejection / Pinbar / Engulfing (+15)")
        else:
            pa_score = 5.0
            details.append("Price Action: Candlestick biasa (+5)")

        # 5. Displacement / Momentum (0-15)
        disp_score = 0.0
        if displacement_confirmed:
            disp_score = 15.0
            details.append("Displacement: Momentum lilin institusional / FVG kuat (+15)")
        else:
            disp_score = 7.0
            details.append("Displacement: Momentum standar (+7)")

        # 6. Risk / Reward and Room to Liquidity (0-10)
        rr_score = 0.0
        if anti_chase.passed and liquidity.distance_to_opposing_usd >= 4.0 and rr_val >= 1.5:
            rr_score = 10.0
            details.append(f"Risk/Reward: R:R {rr_val:.1f} & Ruang ke target aman (+10)")
        elif anti_chase.passed and rr_val >= 1.0:
            rr_score = 7.0
            details.append(f"Risk/Reward: R:R {rr_val:.1f} cukup (+7)")
        else:
            rr_score = 2.0
            details.append("Risk/Reward: Ruang sempit / overextended (+2)")

        total = round(struct_score + liq_score + trig_score + pa_score + disp_score + rr_score, 1)
        total = min(100.0, max(0.0, total))

        return ConfluenceBreakdown(
            total_score=total,
            market_structure_score=struct_score,
            liquidity_score=liq_score,
            trigger_score=trig_score,
            price_action_score=pa_score,
            displacement_score=disp_score,
            rr_and_room_score=rr_score,
            details=details,
        )

    @staticmethod
    def format_master_trading_spec_report(
        style: str,
        direction: str,
        method: str,
        h4: str,
        h1: str,
        m15: str,
        m5: str,
        structure: str,
        liquidity: str,
        liquidity_state: str,
        anti_chase: str,
        trap_risk: str,
        confluence_score: float,
        spread: float,
        risk: str,
        sl: Optional[float],
        tp: Optional[float],
        rr: Optional[float],
        verdict: str,
        reason: str,
    ) -> str:
        """
        Format laporan Master Trading Spec sesuai Section 42 secara presisi.
        """
        sl_str = f"${sl:,.2f}" if sl is not None else "-"
        tp_str = f"${tp:,.2f}" if tp is not None else "-"
        rr_str = f"1 : {rr:.1f}" if rr is not None else "-"

        return (
            f"STYLE: {style}\n"
            f"DIRECTION: {direction}\n\n"
            f"METHOD:\n{method}\n\n"
            f"H4:\n{h4}\n\n"
            f"H1:\n{h1}\n\n"
            f"M15:\n{m15}\n\n"
            f"M5:\n{m5}\n\n"
            f"STRUCTURE:\n{structure}\n\n"
            f"LIQUIDITY:\n{liquidity}\n\n"
            f"LIQUIDITY STATE:\n{liquidity_state}\n\n"
            f"ANTI-CHASE:\n{anti_chase}\n\n"
            f"TRAP RISK:\n{trap_risk}\n\n"
            f"CONFLUENCE:\n{int(round(confluence_score))}/100\n\n"
            f"RISK:\n{risk}\n\n"
            f"SPREAD:\n{spread:.1f} pips\n\n"
            f"SL:\n{sl_str}\n\n"
            f"TP:\n{tp_str}\n\n"
            f"RR:\n{rr_str}\n\n"
            f"VERDICT:\n{verdict}\n\n"
            f"REASON:\n\"{reason}\""
        )
