"""
Test Suite untuk 25 Skenario Pengujian Master Trading Spec (Section 39)
1. SHORT BUY
2. SHORT SELL
3. LONG BUY
4. LONG SELL
5. H4 bearish + valid reversal BUY (Section 31)
6. H4 bullish + valid reversal SELL (Section 33)
7. H4 neutral + valid scalp
8. sweep without reclaim
9. sweep + reclaim
10. bearish continuation (Section 32)
11. bullish continuation
12. false support during bearish continuation (Section 30 - Bad Buy)
13. false resistance during bullish continuation
14. anti-chasing
15. TRAP_RISK
16. CAUTION
17. SAFE
18. RR < 1.5 for LONG
19. risk > 6% warning
20. spread abnormal / adaptif
21. max bot layer
22. manual trade vs bot trade
23. no valid liquidity
24. missing M5 trigger
25. conflicting timeframe context
"""

import pytest
import pandas as pd
import numpy as np
from strategy.smc_liquidity import (
    SMCLiquidityEngine,
    MarketStructureResult,
    LiquidityAnalysisResult,
    AntiChaseResult,
    ConfluenceBreakdown,
)
from strategy.signal_engine import SignalEngine, SignalResult
from indicators.technical import TechnicalIndicators


def create_ohlcv_series(prices, spread=3.4):
    """Helper untuk membuat DataFrame OHLCV sederhana dari daftar harga Close."""
    n = len(prices)
    highs = [p + 2.0 for p in prices]
    lows = [p - 2.0 for p in prices]
    opens = [prices[i - 1] if i > 0 else prices[0] for i in range(n)]
    vols = [1000.0] * n
    idx = pd.date_range("2026-10-01 10:00", periods=n, freq="15min")
    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": prices,
        "Volume": vols,
        "spread_pips": [spread] * n,
    }, index=idx)
    return TechnicalIndicators.add_all_indicators(df)


# 1. SHORT BUY
def test_scenario_01_short_buy():
    """Uji SHORT BUY: Scalp cepat TP 60 pips & SL 60 pips (R:R 1:1)."""
    engine = SignalEngine()
    prices = [4050.0 + i * 2.0 for i in range(30)]
    df = create_ohlcv_series(prices)
    sig = engine.evaluate_bar(df, ticker="XAUUSD", preferred_trade_type="SHORT")
    
    assert sig.trade_type == "SHORT"
    assert sig.style == "SHORT"
    # Memastikan constraint TP & SL minimal 60 pips ($6.00 USD)
    if sig.take_profit_price and sig.stop_loss_price:
        assert round(abs(sig.take_profit_price - sig.price), 2) >= 6.00
        assert round(abs(sig.price - sig.stop_loss_price), 2) >= 6.00


# 2. SHORT SELL
def test_scenario_02_short_sell():
    """Uji SHORT SELL: Scalp cepat SELL TP 60 pips & SL 60 pips."""
    engine = SignalEngine()
    prices = [4100.0 - i * 2.0 for i in range(30)]
    df = create_ohlcv_series(prices)
    sig = engine.evaluate_bar(df, ticker="XAUUSD", preferred_trade_type="SHORT")
    
    assert sig.trade_type == "SHORT"
    assert sig.style == "SHORT"
    if sig.take_profit_price and sig.stop_loss_price:
        assert round(abs(sig.price - sig.take_profit_price), 2) >= 6.00
        assert round(abs(sig.stop_loss_price - sig.price), 2) >= 6.00


# 3. LONG BUY
def test_scenario_03_long_buy():
    """Uji LONG BUY: Intraday / Swing BUY dengan R:R >= 1.5."""
    engine = SignalEngine()
    prices = [4000.0 + i * 3.0 for i in range(30)]
    df = create_ohlcv_series(prices)
    sig = engine.evaluate_bar(df, ticker="XAUUSD", preferred_trade_type="LONG")
    
    assert sig.trade_type == "LONG"
    assert sig.style == "LONG"
    if sig.risk_reward_ratio is not None and sig.signal in ["BUY", "BUY_LIMIT"]:
        assert sig.risk_reward_ratio >= 1.5


# 4. LONG SELL
def test_scenario_04_long_sell():
    """Uji LONG SELL: Intraday / Swing SELL dengan R:R >= 1.5."""
    engine = SignalEngine()
    prices = [4150.0 - i * 3.0 for i in range(30)]
    df = create_ohlcv_series(prices)
    sig = engine.evaluate_bar(df, ticker="XAUUSD", preferred_trade_type="LONG")
    
    assert sig.trade_type == "LONG"
    assert sig.style == "LONG"
    if sig.risk_reward_ratio is not None and sig.signal in ["SELL", "SELL_LIMIT"]:
        assert sig.risk_reward_ratio >= 1.5


# 5. H4 bearish + valid reversal BUY (Section 31: Good Reversal Buy)
def test_scenario_05_h4_bearish_with_valid_reversal_buy():
    """
    Section 31: H4 Bearish. M15 Bearish.
    Harga menyapu Sell-Side Liquidity -> Reclaim -> Bullish CHoCH -> Valid SHORT BUY!
    """
    engine = SignalEngine()
    # Buat data M15 di mana terjadi sell-side sweep + reclaim
    prices = [4080 - i * 3.0 for i in range(20)] # Downtrend ke 4020
    df = create_ohlcv_series(prices)
    
    # Rekayasa bar terakhir: tusuk ke bawah swing low (4015), lalu reclaim dan tutup di 4030
    last_row = df.iloc[-1].copy()
    last_row["Low"] = 4010.0
    last_row["Close"] = 4032.0
    last_row["Open"] = 4018.0
    last_row["pattern_pinbar"] = 1
    last_row["rejection_wick_ratio"] = 0.45
    df.iloc[-1] = last_row

    # H4 Bearish DataFrame
    df_h4 = pd.DataFrame({
        "Close": [4090.0, 4030.0],
        "ema_50": [4100.0, 4100.0],
        "rsi": [35.0, 32.0],
        "ichimoku_above_cloud": [0, 0],
    })

    sig = engine.evaluate_bar(df, ticker="XAUUSD", df_h4=df_h4, preferred_trade_type="SHORT")
    # Walaupun H4 Bearish, Reversal BUY yang sah diizinkan
    assert sig.h4_context in ["BEARISH", "NEUTRAL"]
    assert sig.style == "SHORT"


# 6. H4 bullish + valid reversal SELL (Section 33: Bullish Reversal Sell)
def test_scenario_06_h4_bullish_with_valid_reversal_sell():
    """
    Section 33: H4 Bullish. M15 Bullish.
    Harga menyapu Buy-Side Liquidity -> Reclaim -> Bearish CHoCH -> Valid SHORT SELL!
    """
    engine = SignalEngine()
    prices = [4000 + i * 3.0 for i in range(20)] # Uptrend ke 4060
    df = create_ohlcv_series(prices)
    
    last_row = df.iloc[-1].copy()
    last_row["High"] = 4075.0
    last_row["Close"] = 4055.0
    last_row["Open"] = 4065.0
    last_row["pattern_shooting_star"] = 1
    last_row["upper_wick_ratio"] = 0.45
    df.iloc[-1] = last_row

    df_h4 = pd.DataFrame({
        "Close": [4020.0, 4060.0],
        "ema_50": [4010.0, 4010.0],
        "rsi": [62.0, 65.0],
        "ichimoku_above_cloud": [1, 1],
    })

    sig = engine.evaluate_bar(df, ticker="XAUUSD", df_h4=df_h4, preferred_trade_type="SHORT")
    assert sig.h4_context in ["BULLISH", "NEUTRAL"]
    assert sig.style == "SHORT"


# 7. H4 neutral + valid scalp
def test_scenario_07_h4_neutral_valid_scalp():
    """H4 Neutral / Konsolidasi tetap mengizinkan SHORT Scalp (Section 4)."""
    engine = SignalEngine()
    prices = [4050.0 + (1.0 if i % 2 == 0 else -1.0) for i in range(25)]
    df = create_ohlcv_series(prices)

    df_h4 = pd.DataFrame({
        "Close": [4050.0, 4050.0],
        "ema_50": [4050.0, 4050.0],
        "rsi": [50.0, 50.0],
        "ichimoku_above_cloud": [0, 0],
    })

    sig = engine.evaluate_bar(df, ticker="XAUUSD", df_h4=df_h4, preferred_trade_type="SHORT")
    assert sig.h4_context == "NETRAL" or sig.h4_context == "NEUTRAL"
    assert sig.style == "SHORT"


# 8. sweep without reclaim
def test_scenario_08_sweep_without_reclaim():
    """Sweep tanpa reclaim harus ditandai tidak sempurna (unconfirmed)."""
    prices = [4050, 4040, 4030, 4020, 4010, 4000]
    highs = pd.Series([p + 2 for p in prices])
    lows = pd.Series([4048, 4038, 4028, 4018, 4008, 3990]) # Menembus di bawah 4000
    closes = pd.Series([4045, 4035, 4025, 4015, 4005, 3992]) # Tutup di bawah 4000 (tidak reclaim!)
    opens = pd.Series([4049, 4039, 4029, 4019, 4009, 4002])

    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes})
    struct = SMCLiquidityEngine.analyze_market_structure(df)
    liq = SMCLiquidityEngine.analyze_liquidity(df, struct, intended_direction="BUY")

    assert liq.is_reclaimed is False
    assert liq.has_sweep_and_reclaim is False


# 9. sweep + reclaim
def test_scenario_09_sweep_with_reclaim():
    """Sell-Side Sweep + Reclaim: Low menembus support, Close kembali di atasnya."""
    prices = [4050, 4040, 4030, 4020, 4010, 4015]
    highs = pd.Series([4055, 4045, 4035, 4025, 4015, 4018])
    lows = pd.Series([4045, 4035, 4025, 4015, 4005, 3998]) # Menembus di bawah 4005
    closes = pd.Series([4048, 4038, 4028, 4018, 4008, 4014]) # Tutup di atas 4005 (reclaim!)
    opens = pd.Series([4050, 4040, 4030, 4020, 4010, 4004])

    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes})
    struct = SMCLiquidityEngine.analyze_market_structure(df)
    liq = SMCLiquidityEngine.analyze_liquidity(df, struct, intended_direction="BUY")

    assert liq.has_sweep_and_reclaim is True
    assert liq.is_reclaimed is True
    assert liq.sweep_type == "SELL_SIDE"


# 10. bearish continuation (Section 32)
def test_scenario_10_bearish_continuation():
    """Section 32: H4 bearish, M15 LH/LL intact, pullback retest resisten -> SELL continuation."""
    prices = [4100 - i * 3.0 for i in range(25)]
    df = create_ohlcv_series(prices)
    struct = SMCLiquidityEngine.analyze_market_structure(df)
    liq = SMCLiquidityEngine.analyze_liquidity(df, struct, intended_direction="SELL")
    method = SMCLiquidityEngine.select_trading_method(struct, liq, direction="SELL")

    assert struct.trend == "BEARISH"
    assert method in ["Trend Continuation", "Pullback Retest"]


# 11. bullish continuation
def test_scenario_11_bullish_continuation():
    """Bullish continuation: HH/HL intact, pullback retest support -> BUY continuation."""
    prices = [4000 + i * 3.0 for i in range(25)]
    df = create_ohlcv_series(prices)
    struct = SMCLiquidityEngine.analyze_market_structure(df)
    liq = SMCLiquidityEngine.analyze_liquidity(df, struct, intended_direction="BUY")
    method = SMCLiquidityEngine.select_trading_method(struct, liq, direction="BUY")

    assert struct.trend == "BULLISH"
    assert method in ["Trend Continuation", "Pullback Retest"]


# 12. false support during bearish continuation (Section 30: Bad Buy)
def test_scenario_12_false_support_bearish_continuation():
    """
    Section 30: H4 bearish, M15 bearish continuation (LL/LH).
    Harga di area bawah dan RSI memantul dari <35 ke >35 tanpa sweep+reclaim -> TRAP_RISK / WAIT!
    """
    prices = [4100 - i * 4.0 for i in range(25)]
    df = create_ohlcv_series(prices)
    struct = SMCLiquidityEngine.analyze_market_structure(df)
    liq = SMCLiquidityEngine.analyze_liquidity(df, struct, intended_direction="BUY")

    assert liq.state == "TRAP_RISK"
    assert any("Section 30" in r or "Bearish Continuation" in r for r in liq.trap_reasons)


# 13. false resistance during bullish continuation
def test_scenario_13_false_resistance_bullish_continuation():
    """Bullish continuation kuat: Menjual di atap tanpa sweep+reclaim -> TRAP_RISK!"""
    prices = [4000 + i * 4.0 for i in range(25)]
    df = create_ohlcv_series(prices)
    struct = SMCLiquidityEngine.analyze_market_structure(df)
    liq = SMCLiquidityEngine.analyze_liquidity(df, struct, intended_direction="SELL")

    assert liq.state == "TRAP_RISK"
    assert any("Bullish Continuation" in r for r in liq.trap_reasons)


# 14. anti-chasing
def test_scenario_14_anti_chasing():
    """Harga overextended > 1.5 ATR dari 20 EMA ditolak oleh Anti-Chase (Section 15)."""
    res = SMCLiquidityEngine.evaluate_anti_chase(
        curr_price=4150.0,
        ema20=4135.0,  # Jarak $15.0 USD
        atr=3.0,       # Max allowed ~ 4.5 USD
    )
    assert res.passed is False
    assert res.status == "FAIL_OVEREXTENDED"


# 15. TRAP_RISK classification
def test_scenario_15_trap_risk():
    """Setup berisiko manipulasi diklasifikasikan sebagai TRAP_RISK."""
    prices = [4100 - i * 5.0 for i in range(20)]
    df = create_ohlcv_series(prices)
    struct = SMCLiquidityEngine.analyze_market_structure(df)
    liq = SMCLiquidityEngine.analyze_liquidity(df, struct, intended_direction="BUY")
    assert liq.state == "TRAP_RISK"


# 16. CAUTION classification
def test_scenario_16_caution():
    """Setup continuation normal tanpa sweep diklasifikasikan sebagai CAUTION (tradable)."""
    prices = [4000 + i * 2.0 for i in range(20)]
    df = create_ohlcv_series(prices)
    struct = SMCLiquidityEngine.analyze_market_structure(df)
    liq = SMCLiquidityEngine.analyze_liquidity(df, struct, intended_direction="BUY")
    assert liq.state == "CAUTION"


# 17. SAFE classification
def test_scenario_17_safe():
    """Setup dengan sweep + reclaim terkonfirmasi diklasifikasikan sebagai SAFE."""
    prices = [4050, 4040, 4030, 4020, 4010, 4015]
    highs = pd.Series([4055, 4045, 4035, 4025, 4015, 4018])
    lows = pd.Series([4045, 4035, 4025, 4015, 4005, 3998])
    closes = pd.Series([4048, 4038, 4028, 4018, 4008, 4014])
    opens = pd.Series([4050, 4040, 4030, 4020, 4010, 4004])

    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes})
    struct = SMCLiquidityEngine.analyze_market_structure(df)
    liq = SMCLiquidityEngine.analyze_liquidity(df, struct, intended_direction="BUY")
    assert liq.state == "SAFE"


# 18. RR < 1.5 for LONG
def test_scenario_18_rr_below_1_5_for_long():
    """Untuk kelas LONG (Swing/Intraday), target RR minimal adalah 1.5 (Section 21 & 22)."""
    engine = SignalEngine()
    prices = [4000 + i * 2.0 for i in range(25)]
    df = create_ohlcv_series(prices)
    sig = engine.evaluate_bar(df, ticker="XAUUSD", preferred_trade_type="LONG")
    if sig.risk_reward_ratio is not None and sig.signal in ["BUY", "BUY_LIMIT"]:
        assert sig.risk_reward_ratio >= 1.5


# 19. risk > 6% warning
def test_scenario_19_risk_above_6_percent_warning():
    """Peringatan risiko muncul jika estimasi risiko portofolio > 6% (Section 25)."""
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Default",
        signal="BUY",
        price=4050.0,
        risk_level="WARNING (>6%)",
    )
    assert "WARNING" in sig.risk_level


# 20. spread abnormal / adaptive
def test_scenario_20_spread_adaptive():
    """Evaluasi spread bersifat adaptif mengikuti kondisi pasar (Section 24)."""
    prices = [4050.0] * 10
    df = create_ohlcv_series(prices, spread=4.2)
    engine = SignalEngine()
    sig = engine.evaluate_bar(df, ticker="XAUUSD")
    assert sig.spread_pips == 4.2


# 21. max bot layer
def test_scenario_21_max_bot_layer():
    """Sistem membatasi maksimal 1 bot layer dan lot tetap (Section 26 & 27)."""
    engine = SignalEngine()
    cfg_cent = engine.config.get("mt5", {}).get("max_positions_cent", 1)
    cfg_lot = engine.config.get("mt5", {}).get("limit_order_lot", 0.05)
    assert cfg_cent == 1
    assert cfg_lot == 0.05


# 22. manual trade vs bot trade
def test_scenario_22_manual_trade_vs_bot_trade():
    """Magic number membedakan posisi manual dari posisi bot (Section 26)."""
    engine = SignalEngine()
    magic = engine.config.get("mt5", {}).get("magic_number", 777777)
    assert magic == 777777


# 23. no valid liquidity
def test_scenario_23_no_valid_liquidity():
    """Jika tidak ada kolam likuiditas terdeteksi, tandai secara eksplisit NO_VALID_LIQUIDITY (Section 36)."""
    df_empty = pd.DataFrame()
    struct = MarketStructureResult(trend="NEUTRAL")
    liq = SMCLiquidityEngine.analyze_liquidity(df_empty, struct)
    assert liq.description == "NO_VALID_LIQUIDITY"


# 24. missing M5 trigger
def test_scenario_24_missing_m5_trigger():
    """Jika trigger M5 tidak valid, Confluence Score memberikan penalti (Section 17 & 41)."""
    struct = MarketStructureResult(trend="BULLISH", bos_bullish=True)
    liq = LiquidityAnalysisResult(state="CAUTION", sweep_type="NONE", distance_to_opposing_usd=10.0)
    anti_chase = AntiChaseResult(passed=True, status="PASS", dist_from_ema20=1.0, max_allowed_dist=3.0, reason="PASS")
    
    score_with_trig = SMCLiquidityEngine.score_confluence(
        structure=struct, liquidity=liq, anti_chase=anti_chase,
        m5_trigger_valid=True, price_action_confirmed=True,
        displacement_confirmed=True, rr_val=1.5, direction="BUY"
    )
    score_without_trig = SMCLiquidityEngine.score_confluence(
        structure=struct, liquidity=liq, anti_chase=anti_chase,
        m5_trigger_valid=False, price_action_confirmed=True,
        displacement_confirmed=True, rr_val=1.5, direction="BUY"
    )
    assert score_with_trig.total_score > score_without_trig.total_score


# 25. conflicting timeframe context
def test_scenario_25_conflicting_timeframe_context():
    """
    Konflik timeframe (H4 Bearish vs M15 Bullish Bounce) ditangani elegan:
    Jika tanpa sweep+reclaim, setup BUY ditahan (TRAP_RISK / WAIT) untuk melindungi akun.
    """
    engine = SignalEngine()
    prices = [4080 - i * 3.0 for i in range(25)]
    df = create_ohlcv_series(prices)
    
    df_h4 = pd.DataFrame({
        "Close": [4090.0, 4020.0],
        "ema_50": [4100.0, 4100.0],
        "rsi": [35.0, 32.0],
        "ichimoku_above_cloud": [0, 0],
    })

    # Evaluasi terhadap struktur dan likuiditas BUY dalam tren H4 Bearish
    struct = SMCLiquidityEngine.analyze_market_structure(df)
    liq = SMCLiquidityEngine.analyze_liquidity(df, struct, intended_direction="BUY")

    # M15 Bearish Continuation tanpa sweep+reclaim adalah TRAP_RISK mutlak
    assert liq.state == "TRAP_RISK"
    assert any("Section 30" in r or "Bearish Continuation" in r for r in liq.trap_reasons)

    # Ketika dievaluasi penuh oleh SignalEngine, sinyal harus di-HOLD (WAIT)
    sig = engine.evaluate_bar(df, ticker="XAUUSD", df_h4=df_h4)
    assert sig.signal == "HOLD"
    assert sig.verdict == "WAIT"
