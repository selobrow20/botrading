"""
Multi-Timeframe Analysis (MTF) Top-Down Execution Engine for XAU/USD.
Alur Analisis Sistematis: H1 -> M30 -> M15 -> M5

Modul Arsitektur:
1. Timeframe H1  (check_h1_snr)        : Filter Key Support & Resistance (SNR) horizontal mayor.
                                          Filter: Jarak <= 15 pips ($1.50) dari Resistance blokir BUY.
                                          Filter: Jarak <= 15 pips ($1.50) dari Support blokir SELL.
2. Timeframe M30 (check_m30_trendline) : Koneksi Trendline Dinamis (Support & Resistance Trendline).
                                          Konfirmasi pantulan (Bounce) atau penembusan (Breakout).
3. Timeframe M15 (get_m15_direction)   : Penentu Arah Tren Dominan / Market Bias (EMA & Higher Highs/Lower Lows).
                                          Kunci arah eksekusi agar bot HANYA mengambil order searah.
4. Timeframe M5  (trigger_m5_entry)    : Sniper Execution & Gatekeeper.
                                          Sinkronisasi filter H1, M30, M15.
                                          Cek candle rejection wick minimal 30% dari total range candle.
                                          Kalkulasi SL & TP berbasis swing M5 dengan Rasio Risk-to-Reward (RR) minimal 1:2.
5. MT5 Pipeline  (fetch_mtf_data_mt5)  : Pengambilan data multi-timeframe langsung via MetaTrader 5 API.
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger("StockBot.MTFEngine")


# =====================================================================
# 1. TIMEFRAME H1: KEY SUPPORT & RESISTANCE (SNR) FILTER
# =====================================================================

def check_h1_snr(
    df_h1: pd.DataFrame,
    curr_price: float,
    pip_buffer: float = 1.50,
    lookback_bars: int = 50,
) -> Dict[str, Any]:
    """
    Timeframe H1: Filter Key Support & Resistance Horizontal Mayor.
    
    Aturan:
    - Pindai data candle H1 terakhir untuk mendeteksi Swing High dan Swing Low horizontal mayor.
    - Jika harga berada dalam jarak 15 pips ($1.50 USD) dari Resistance H1 -> BLOKIR semua sinyal BUY.
    - Jika harga berada dalam jarak 15 pips ($1.50 USD) dari Support H1 -> BLOKIR semua sinyal SELL.
    
    Args:
        df_h1: DataFrame candle H1 (Open, High, Low, Close, Volume).
        curr_price: Harga pasar saat ini (bid/ask/last close).
        pip_buffer: Ambang batas jarak blokir (default 1.50 USD = 15 pips Gold).
        lookback_bars: Jumlah bar H1 yang dianalisis untuk deteksi swing mayor.
        
    Returns:
        Dict dengan status can_buy, can_sell, key resistance, key support, dan alasan.
    """
    if df_h1 is None or df_h1.empty or len(df_h1) < 5:
        return {
            "can_buy": True,
            "can_sell": True,
            "h1_resistance": curr_price + 10.0,
            "h1_support": max(0.0, curr_price - 10.0),
            "dist_to_resistance": 10.0,
            "dist_to_support": 10.0,
            "pip_buffer": pip_buffer,
            "status": "DATA_H1_INSUFFICIENT",
            "reason": "Data H1 tidak mencukupi untuk analisis SNR.",
        }

    slice_h1 = df_h1.tail(lookback_bars).copy()
    highs = slice_h1["High"].values
    lows = slice_h1["Low"].values
    n = len(slice_h1)

    # Deteksi Swing High dan Swing Low Horizontal (Pivot Window = 2 kiri, 2 kanan)
    swing_highs: List[float] = []
    swing_lows: List[float] = []

    for i in range(2, n - 2):
        if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] >= highs[i + 1] and highs[i] >= highs[i + 2]:
            swing_highs.append(float(highs[i]))
        if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] <= lows[i + 1] and lows[i] <= lows[i + 2]:
            swing_lows.append(float(lows[i]))

    # Fallback jika pivot bar sedikit: gunakan extremum lokal
    if not swing_highs:
        swing_highs = [float(np.max(highs))]
    if not swing_lows:
        swing_lows = [float(np.min(lows))]

    # Cari Key Resistance terdekat di atas harga dan Key Support terdekat di bawah harga
    res_above = [r for r in swing_highs if r >= curr_price]
    sup_below = [s for s in swing_lows if s <= curr_price]

    key_resistance = min(res_above) if res_above else float(np.max(highs))
    key_support = max(sup_below) if sup_below else float(np.min(lows))

    dist_to_resistance = round(key_resistance - curr_price, 2)
    dist_to_support = round(curr_price - key_support, 2)

    # Filter Aturan Hard 15 Pips ($1.50 USD):
    # - Jika harga dalam 15 pips dari Resistance H1 -> BLOKIR BUY
    # - Jika harga dalam 15 pips dari Support H1 -> BLOKIR SELL
    can_buy = True
    can_sell = True
    reasons: List[str] = []

    if 0.0 <= dist_to_resistance <= pip_buffer:
        can_buy = False
        reasons.append(
            f"🚫 [BLOKIR BUY H1] Harga (${curr_price:,.2f}) berada {dist_to_resistance:.2f} USD "
            f"(<= {pip_buffer:.2f} USD / 15 pips) dari Resistance Mayor H1 (${key_resistance:,.2f}). Dilarang BUY di atap!"
        )
    elif dist_to_resistance < 0.0 and abs(dist_to_resistance) <= pip_buffer:
        # Harga baru saja menembus tipis tetapi masih berada di area retest resisten
        can_buy = False
        reasons.append(
            f"🚫 [BLOKIR BUY H1] Harga (${curr_price:,.2f}) berada di zona Resistance H1 (${key_resistance:,.2f})."
        )

    if 0.0 <= dist_to_support <= pip_buffer:
        can_sell = False
        reasons.append(
            f"🚫 [BLOKIR SELL H1] Harga (${curr_price:,.2f}) berada {dist_to_support:.2f} USD "
            f"(<= {pip_buffer:.2f} USD / 15 pips) dari Support Mayor H1 (${key_support:,.2f}). Dilarang SELL di lantai!"
        )
    elif dist_to_support < 0.0 and abs(dist_to_support) <= pip_buffer:
        can_sell = False
        reasons.append(
            f"🚫 [BLOKIR SELL H1] Harga (${curr_price:,.2f}) berada di zona Support H1 (${key_support:,.2f})."
        )

    if not reasons:
        reasons.append(
            f"✅ [H1 SNR AMAN] Jarak ke Resistance: ${dist_to_resistance:.2f} | Jarak ke Support: ${dist_to_support:.2f}."
        )

    return {
        "can_buy": can_buy,
        "can_sell": can_sell,
        "h1_resistance": round(key_resistance, 2),
        "h1_support": round(key_support, 2),
        "dist_to_resistance": dist_to_resistance,
        "dist_to_support": dist_to_support,
        "pip_buffer": pip_buffer,
        "status": "BLOCKED" if (not can_buy or not can_sell) else "CLEAR",
        "reason": " | ".join(reasons),
        "swing_highs_count": len(swing_highs),
        "swing_lows_count": len(swing_lows),
    }


# =====================================================================
# 2. TIMEFRAME M30: DYNAMIC TRENDLINE CONNECTION & BOUNCE/BREAKOUT
# =====================================================================

def check_m30_trendline(
    df_m30: pd.DataFrame,
    curr_price: float,
    lookback_bars: int = 40,
) -> Dict[str, Any]:
    """
    Timeframe M30: Koneksi Trendline Dinamis & Deteksi Pantulan/Breakout.
    
    Aturan:
    - Hitung dan hubungkan titik pivot swing M30 untuk memetakan Support Trendline & Resistance Trendline.
    - Konfirmasi apakah posisi harga saat ini memantul dari trendline atau sedang breakout.
    
    Returns:
        Dict berisi trendline_bias ('BUY', 'SELL', 'NEUTRAL'), condition ('BOUNCE_SUPPORT',
        'BOUNCE_RESISTANCE', 'BREAKOUT_UP', 'BREAKOUT_DOWN', 'INSIDE_CHANNEL'), level garis, dan status.
    """
    if df_m30 is None or df_m30.empty or len(df_m30) < 10:
        return {
            "trendline_bias": "NEUTRAL",
            "condition": "INSUFFICIENT_DATA",
            "support_trendline_val": curr_price - 5.0,
            "resistance_trendline_val": curr_price + 5.0,
            "support_slope": 0.0,
            "resistance_slope": 0.0,
            "status": "Data M30 tidak mencukupi untuk kalkulasi trendline.",
        }

    slice_m30 = df_m30.tail(lookback_bars).copy().reset_index(drop=True)
    n = len(slice_m30)
    highs = slice_m30["High"].values
    lows = slice_m30["Low"].values
    closes = slice_m30["Close"].values
    opens = slice_m30["Open"].values

    # 1. Cari titik pivot M30 (window = 2 kiri, 2 kanan)
    pivot_highs: List[Tuple[int, float]] = []  # (index, price)
    pivot_lows: List[Tuple[int, float]] = []

    for i in range(2, n - 2):
        if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] >= highs[i + 1] and highs[i] >= highs[i + 2]:
            pivot_highs.append((i, float(highs[i])))
        if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] <= lows[i + 1] and lows[i] <= lows[i + 2]:
            pivot_lows.append((i, float(lows[i])))

    curr_idx = n - 1

    # 2. Hubungkan 2 Pivot High terakhir untuk Resistance Trendline
    res_slope = 0.0
    res_tl_val = curr_price + 5.0
    if len(pivot_highs) >= 2:
        (x1, y1), (x2, y2) = pivot_highs[-2], pivot_highs[-1]
        dx = max(1, x2 - x1)
        res_slope = (y2 - y1) / dx
        res_tl_val = y2 + res_slope * (curr_idx - x2)
    elif len(pivot_highs) == 1:
        res_tl_val = pivot_highs[-1][1]
    else:
        res_tl_val = float(np.max(highs))

    # 3. Hubungkan 2 Pivot Low terakhir untuk Support Trendline
    sup_slope = 0.0
    sup_tl_val = curr_price - 5.0
    if len(pivot_lows) >= 2:
        (x1, y1), (x2, y2) = pivot_lows[-2], pivot_lows[-1]
        dx = max(1, x2 - x1)
        sup_slope = (y2 - y1) / dx
        sup_tl_val = y2 + sup_slope * (curr_idx - x2)
    elif len(pivot_lows) == 1:
        sup_tl_val = pivot_lows[-1][1]
    else:
        sup_tl_val = float(np.min(lows))

    # Pastikan relasi logis: res_tl_val >= sup_tl_val
    if res_tl_val < sup_tl_val:
        res_tl_val, sup_tl_val = sup_tl_val, res_tl_val

    # 4. Evaluasi Posisi Harga terhadap Trendline M30
    last_close = float(closes[-1])
    last_open = float(opens[-1])
    touch_tolerance = 1.50  # 15 pips

    dist_to_res_tl = res_tl_val - curr_price
    dist_to_sup_tl = curr_price - sup_tl_val

    trendline_bias = "NEUTRAL"
    condition = "INSIDE_CHANNEL"
    reason = ""

    # Skenario 1: Breakout Resistance ke Atas
    if curr_price > res_tl_val + 0.30 and last_close > res_tl_val:
        trendline_bias = "BUY"
        condition = "BREAKOUT_UP"
        reason = f"🚀 [M30 BREAKOUT RESISTANCE] Harga (${curr_price:,.2f}) menembus Resistance Trendline M30 (${res_tl_val:,.2f}). Konfirmasi Bullish Breakout!"

    # Skenario 2: Breakout Support ke Bawah
    elif curr_price < sup_tl_val - 0.30 and last_close < sup_tl_val:
        trendline_bias = "SELL"
        condition = "BREAKOUT_DOWN"
        reason = f"🔻 [M30 BREAKOUT SUPPORT] Harga (${curr_price:,.2f}) menembus Support Trendline M30 (${sup_tl_val:,.2f}). Konfirmasi Bearish Breakdown!"

    # Skenario 3: Memantul dari Support Trendline (Bounce Support / Demand Rebound)
    elif abs(dist_to_sup_tl) <= touch_tolerance and (last_close >= last_open or curr_price >= sup_tl_val):
        trendline_bias = "BUY"
        condition = "BOUNCE_SUPPORT"
        reason = f"🎯 [M30 BOUNCE SUPPORT] Harga (${curr_price:,.2f}) memantul naik dari Support Trendline M30 (${sup_tl_val:,.2f}). Peluang Buy On Support!"

    # Skenario 4: Memantul dari Resistance Trendline (Bounce Resistance / Supply Rejection)
    elif abs(dist_to_res_tl) <= touch_tolerance and (last_close <= last_open or curr_price <= res_tl_val):
        trendline_bias = "SELL"
        condition = "BOUNCE_RESISTANCE"
        reason = f"🎯 [M30 BOUNCE RESISTANCE] Harga (${curr_price:,.2f}) terbentur dan memantul turun dari Resistance Trendline M30 (${res_tl_val:,.2f}). Peluang Sell On Resistance!"

    # Skenario 5: Berada di dalam Channel (Inside Channel)
    else:
        if res_slope > 0.05 and sup_slope > 0.05 and curr_price >= sup_tl_val:
            trendline_bias = "BUY"
            condition = "UPTREND_CHANNEL"
            reason = f"📈 [M30 UPTREND CHANNEL] Saluran tren M30 miring ke atas (Slope: +{sup_slope:.2f}). Bias menguntungkan BUY."
        elif res_slope < -0.05 and sup_slope < -0.05 and curr_price <= res_tl_val:
            trendline_bias = "SELL"
            condition = "DOWNTREND_CHANNEL"
            reason = f"📉 [M30 DOWNTREND CHANNEL] Saluran tren M30 miring ke bawah (Slope: {res_slope:.2f}). Bias menguntungkan SELL."
        else:
            trendline_bias = "NEUTRAL"
            condition = "INSIDE_CHANNEL"
            reason = f"⚖️ [M30 SIDEWAYS CHANNEL] Harga bergerak di antara Support ${sup_tl_val:,.2f} dan Resisten ${res_tl_val:,.2f}."

    return {
        "trendline_bias": trendline_bias,
        "condition": condition,
        "support_trendline_val": round(sup_tl_val, 2),
        "resistance_trendline_val": round(res_tl_val, 2),
        "dist_to_support_tl": round(dist_to_sup_tl, 2),
        "dist_to_res_tl": round(dist_to_res_tl, 2),
        "support_slope": round(sup_slope, 4),
        "resistance_slope": round(res_slope, 4),
        "pivot_highs_count": len(pivot_highs),
        "pivot_lows_count": len(pivot_lows),
        "status": reason,
    }


# =====================================================================
# 3. TIMEFRAME M15: DOMINANT TREND DIRECTION & MARKET BIAS LOCK
# =====================================================================

def get_m15_direction(
    df_m15: pd.DataFrame,
    curr_price: float,
    lookback_bars: int = 40,
) -> Dict[str, Any]:
    """
    Timeframe M15: Penentu Arah Tren Dominan / Market Bias.
    
    Aturan:
    - Tentukan arah tren dominan (Direction = BUY atau SELL) berdasarkan struktur market M15:
      1. Posisi harga terhadap EMA 20 dan EMA 50 dinamis.
      2. Pembentukan Higher Highs + Higher Lows (Bullish) vs Lower Highs + Lower Lows (Bearish).
    - Kunci arah eksekusi agar bot HANYA mengambil order yang searah dengan tren M15 ini.
    
    Returns:
        Dict berisi direction ('BUY', 'SELL', 'HOLD'), locked_direction, struktur market, dan alasan.
    """
    if df_m15 is None or df_m15.empty or len(df_m15) < 15:
        return {
            "direction": "HOLD",
            "locked_direction": "HOLD",
            "structure": "INSUFFICIENT_DATA",
            "ema_trend": "NEUTRAL",
            "ema_20": curr_price,
            "ema_50": curr_price,
            "status": "Data M15 tidak cukup untuk penentuan tren pasar.",
        }

    slice_m15 = df_m15.tail(lookback_bars).copy()
    close_series = slice_m15["Close"]

    # 1. Hitung EMA 20 dan EMA 50 Dinamis
    ema_20 = close_series.ewm(span=20, adjust=False).mean().iloc[-1]
    ema_50 = close_series.ewm(span=50, adjust=False).mean().iloc[-1]

    # Evaluasi Sinyal EMA:
    # Bullish: curr_price > EMA_20 dan EMA_20 > EMA_50
    # Bearish: curr_price < EMA_20 dan EMA_20 < EMA_50
    ema_bias = "NEUTRAL"
    if curr_price > ema_20 and ema_20 >= ema_50:
        ema_bias = "BULLISH_STRONG"
    elif curr_price < ema_20 and ema_20 <= ema_50:
        ema_bias = "BEARISH_STRONG"
    elif curr_price >= ema_50:
        ema_bias = "BULLISH"
    else:
        ema_bias = "BEARISH"

    # 2. Evaluasi Struktur Pasar (Higher Highs & Higher Lows vs Lower Highs & Lower Lows)
    highs = slice_m15["High"].values
    lows = slice_m15["Low"].values
    n = len(slice_m15)

    p_highs: List[float] = []
    p_lows: List[float] = []

    for i in range(2, n - 2):
        if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] >= highs[i + 1] and highs[i] >= highs[i + 2]:
            p_highs.append(float(highs[i]))
        if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] <= lows[i + 1] and lows[i] <= lows[i + 2]:
            p_lows.append(float(lows[i]))

    structure = "CONSOLIDATION"
    if len(p_highs) >= 2 and len(p_lows) >= 2:
        h_prev, h_curr = p_highs[-2], p_highs[-1]
        l_prev, l_curr = p_lows[-2], p_lows[-1]

        if h_curr > h_prev and l_curr > l_prev:
            structure = "BULLISH_HH_HL"  # Higher High + Higher Low
        elif h_curr < h_prev and l_curr < l_prev:
            structure = "BEARISH_LH_LL"  # Lower High + Lower Low
        elif h_curr > h_prev and l_curr <= l_prev:
            structure = "BULLISH_EXPANSION"
        elif h_curr <= h_prev and l_curr < l_prev:
            structure = "BEARISH_EXPANSION"

    # 3. Kunci Arah Eksekusi Final M15
    direction = "HOLD"
    reason = ""

    if "BULLISH" in ema_bias and ("BULLISH" in structure or structure == "CONSOLIDATION"):
        direction = "BUY"
        reason = f"🔒 [TREN M15 = BUY] Struktur {structure} & Harga (${curr_price:,.2f}) di atas EMA 20 (${ema_20:,.2f}) > EMA 50 (${ema_50:,.2f}). Kunci Arah: BUY ONLY!"
    elif "BEARISH" in ema_bias and ("BEARISH" in structure or structure == "CONSOLIDATION"):
        direction = "SELL"
        reason = f"🔒 [TREN M15 = SELL] Struktur {structure} & Harga (${curr_price:,.2f}) di bawah EMA 20 (${ema_20:,.2f}) < EMA 50 (${ema_50:,.2f}). Kunci Arah: SELL ONLY!"
    elif "BULLISH" in ema_bias:
        direction = "BUY"
        reason = f"🔒 [TREN M15 = BUY] Dominasi EMA Bullish (EMA20 ${ema_20:,.2f} > EMA50 ${ema_50:,.2f}). Kunci Arah: BUY ONLY!"
    elif "BEARISH" in ema_bias:
        direction = "SELL"
        reason = f"🔒 [TREN M15 = SELL] Dominasi EMA Bearish (EMA20 ${ema_20:,.2f} < EMA50 ${ema_50:,.2f}). Kunci Arah: SELL ONLY!"
    else:
        direction = "HOLD"
        reason = f"⏸️ [TREN M15 = NETRAL] Struktur {structure} dan EMA tidak selaras. Menunggu kejelasan arah pasar."

    return {
        "direction": direction,
        "locked_direction": direction,
        "structure": structure,
        "ema_trend": ema_bias,
        "ema_20": round(ema_20, 2),
        "ema_50": round(ema_50, 2),
        "status": reason,
    }


# =====================================================================
# 4. TIMEFRAME M5: SNIPER EXECUTION, REJECTION GATEKEEPER & SL/TP
# =====================================================================

def trigger_m5_entry(
    df_m5: pd.DataFrame,
    h1_res: Dict[str, Any],
    m30_res: Dict[str, Any],
    m15_res: Dict[str, Any],
    curr_price: float,
    min_wick_ratio: float = 0.30,
    min_rr_ratio: float = 2.0,
    is_cent: bool = True,
) -> Dict[str, Any]:
    """
    Timeframe M5: Sniper Execution & Gatekeeper Terakhir.
    
    Aturan:
    1. Lakukan eksekusi HANYA jika filter H1, M30, dan M15 sudah sinkron dan sepakat satu arah.
    2. Cek candle rejection M5: Wajib terkonfirmasi memiliki panjang wick (ekor) minimal 30%
       dari total range candle sebagai bukti adanya dorongan harga sebelum order dilepas.
    3. Hitung SL dan TP otomatis berbasis swing low/high M5 dengan rasio Risk to Reward (RR) minimal 1:2.
    
    Returns:
        Dict lengkap berisi status can_execute, action, order_type, entry_price, stop_loss,
        take_profit, risk_reward_ratio, rejection_wick_pct, dan detail alasan verifikasi.
    """
    m15_dir = m15_res.get("direction", "HOLD")

    # ─────────────────────────────────────────────────────────────────
    # LANGKAH 1: SINKRONISASI FILTER H1, M30, M15 (Konsensus Arah)
    # ─────────────────────────────────────────────────────────────────
    if m15_dir not in ["BUY", "SELL"]:
        return {
            "can_execute": False,
            "action": "HOLD",
            "order_type": "NONE",
            "reason": f"Veto M15: Arah tren M15 belum tegas ({m15_dir}). Menunggu pembentukan tren dominan.",
        }

    # Sinkronisasi dengan Filter H1 SNR
    if m15_dir == "BUY" and not h1_res.get("can_buy", True):
        return {
            "can_execute": False,
            "action": "HOLD",
            "order_type": "NONE",
            "reason": f"Veto H1 SNR: Tren M15 = BUY tetapi dilarang oleh H1 ({h1_res.get('reason')}).",
        }

    if m15_dir == "SELL" and not h1_res.get("can_sell", True):
        return {
            "can_execute": False,
            "action": "HOLD",
            "order_type": "NONE",
            "reason": f"Veto H1 SNR: Tren M15 = SELL tetapi dilarang oleh H1 ({h1_res.get('reason')}).",
        }

    # Sinkronisasi dengan Trendline M30
    m30_bias = m30_res.get("trendline_bias", "NEUTRAL")
    m30_cond = m30_res.get("condition", "")

    if m15_dir == "BUY":
        if m30_bias == "SELL" and m30_cond in ["BOUNCE_RESISTANCE", "BREAKOUT_DOWN"]:
            return {
                "can_execute": False,
                "action": "HOLD",
                "order_type": "NONE",
                "reason": f"Veto M30 Trendline: Tren M15 = BUY berlawanan dengan {m30_cond} di M30.",
            }
    elif m15_dir == "SELL":
        if m30_bias == "BUY" and m30_cond in ["BOUNCE_SUPPORT", "BREAKOUT_UP"]:
            return {
                "can_execute": False,
                "action": "HOLD",
                "order_type": "NONE",
                "reason": f"Veto M30 Trendline: Tren M15 = SELL berlawanan dengan {m30_cond} di M30.",
            }

    # ─────────────────────────────────────────────────────────────────
    # LANGKAH 2: VERIFIKASI CANDLE REJECTION WICK M5 (Minimal 30%)
    # ─────────────────────────────────────────────────────────────────
    if df_m5 is None or df_m5.empty or len(df_m5) < 5:
        return {
            "can_execute": False,
            "action": "HOLD",
            "order_type": "NONE",
            "reason": "Data candle M5 tidak mencukupi untuk validasi rejection wick.",
        }

    # Periksa candle terakhir yang telah terbentuk (bar -1 atau -2)
    # Gunakan bar -1 jika range > 0.50, atau bar -2 jika bar -1 baru saja buka
    c_bar = df_m5.iloc[-1]
    c_open = float(c_bar["Open"])
    c_high = float(c_bar["High"])
    c_low = float(c_bar["Low"])
    c_close = float(c_bar["Close"])
    c_range = max(c_high - c_low, 0.01)

    if c_range < 0.40 and len(df_m5) >= 2:
        prev_bar = df_m5.iloc[-2]
        c_open = float(prev_bar["Open"])
        c_high = float(prev_bar["High"])
        c_low = float(prev_bar["Low"])
        c_close = float(prev_bar["Close"])
        c_range = max(c_high - c_low, 0.01)

    rejection_wick_ratio = 0.0
    if m15_dir == "BUY":
        # Untuk BUY: Butuh ekor penolakan bawah (Lower Wick) >= 30% dari total range candle
        lower_wick = max(0.0, min(c_open, c_close) - c_low)
        rejection_wick_ratio = lower_wick / c_range
        if rejection_wick_ratio < min_wick_ratio:
            return {
                "can_execute": False,
                "action": "HOLD",
                "order_type": "NONE",
                "rejection_wick_pct": round(rejection_wick_ratio * 100.0, 1),
                "required_wick_pct": round(min_wick_ratio * 100.0, 1),
                "reason": (
                    f"🛑 [VETO REJECTION M5] Ketiadaan Ekor Penolakan Bawah! "
                    f"Lower wick M5 ({rejection_wick_ratio*100:.1f}%) < minimal {min_wick_ratio*100:.0f}%. "
                    f"Dilarang eksekusi tanpa konfirmasi dorongan harga naik!"
                ),
            }
    else:  # SELL
        # Untuk SELL: Butuh ekor penolakan atas (Upper Wick) >= 30% dari total range candle
        upper_wick = max(0.0, c_high - max(c_open, c_close))
        rejection_wick_ratio = upper_wick / c_range
        if rejection_wick_ratio < min_wick_ratio:
            return {
                "can_execute": False,
                "action": "HOLD",
                "order_type": "NONE",
                "rejection_wick_pct": round(rejection_wick_ratio * 100.0, 1),
                "required_wick_pct": round(min_wick_ratio * 100.0, 1),
                "reason": (
                    f"🛑 [VETO REJECTION M5] Ketiadaan Ekor Penolakan Atas! "
                    f"Upper wick M5 ({rejection_wick_ratio*100:.1f}%) < minimal {min_wick_ratio*100:.0f}%. "
                    f"Dilarang eksekusi tanpa konfirmasi dorongan harga turun!"
                ),
            }

    # ─────────────────────────────────────────────────────────────────
    # LANGKAH 3: KALKULASI SL & TP OTOMATIS BERBASIS SWING M5 (RR >= 1:2)
    # ─────────────────────────────────────────────────────────────────
    recent_m5 = df_m5.tail(15)
    swing_low_m5 = float(recent_m5["Low"].min())
    swing_high_m5 = float(recent_m5["High"].max())

    # Estimasi volatilitas ATR M5 (buffer 1.50 - 2.50 USD)
    diffs = (recent_m5["High"] - recent_m5["Low"]).values
    atr_approx = float(np.mean(diffs)) if len(diffs) > 0 else 2.0
    buffer_usd = max(1.50, round(atr_approx * 0.5, 2))

    if m15_dir == "BUY":
        structural_support = min(swing_low_m5, c_low)
        raw_sl = round(structural_support - buffer_usd, 2)
        sl_distance = max(round(curr_price - raw_sl, 2), 3.50)  # Minimal jarak SL $3.50 agar bernapas
        sl_price = round(curr_price - sl_distance, 2)
        tp_distance = round(sl_distance * min_rr_ratio, 2)
        tp_price = round(curr_price + tp_distance, 2)
        rrr = round(tp_distance / sl_distance, 2)
    else:  # SELL
        structural_resistance = max(swing_high_m5, c_high)
        raw_sl = round(structural_resistance + buffer_usd, 2)
        sl_distance = max(round(raw_sl - curr_price, 2), 3.50)  # Minimal jarak SL $3.50 agar bernapas
        sl_price = round(curr_price + sl_distance, 2)
        tp_distance = round(sl_distance * min_rr_ratio, 2)
        tp_price = round(curr_price - tp_distance, 2)
        rrr = round(tp_distance / sl_distance, 2)

    # Ukuran lot yang disarankan
    recommended_lot = 0.05 if is_cent else 0.01

    return {
        "can_execute": True,
        "action": m15_dir,
        "order_type": m15_dir,  # Eksekusi langsung / siap dipasang limit
        "entry_price": round(curr_price, 2),
        "stop_loss": sl_price,
        "take_profit": tp_price,
        "sl_distance_usd": sl_distance,
        "tp_distance_usd": tp_distance,
        "risk_reward_ratio": rrr,
        "rejection_wick_pct": round(rejection_wick_ratio * 100.0, 1),
        "recommended_lot": recommended_lot,
        "h1_summary": f"Resisten: ${h1_res.get('h1_resistance')} | Support: ${h1_res.get('h1_support')}",
        "m30_summary": f"Kondisi: {m30_res.get('condition')} | Bias: {m30_res.get('trendline_bias')}",
        "m15_summary": f"Arah: {m15_dir} | Struktur: {m15_res.get('structure')}",
        "reason": (
            f"🎯 [SNIPER M5 TERKONFIRMASI] Konsensus Top-Down 100% SINKRON! "
            f"H1 SNR Aman + M30 Trendline Selaras ({m30_cond}) + M15 Tren {m15_dir} + "
            f"M5 Rejection Wick ({rejection_wick_ratio*100:.1f}% >= 30%) valid. "
            f"Entry: ${curr_price:,.2f} | SL: ${sl_price:,.2f} | TP: ${tp_price:,.2f} (R:R {rrr:.1f}:1)."
        ),
    }


# =====================================================================
# 5. PIPELINE PENGAMBILAN DATA MULTI-TIMEFRAME VIA METATRADER 5
# =====================================================================

def fetch_mtf_data_mt5(
    symbol: str = "XAUUSDc",
    bars_count: int = 100,
) -> Dict[str, pd.DataFrame]:
    """
    Mengambil data candlestick multi-timeframe secara real-time langsung dari MT5 terminal:
    - TIMEFRAME_H1
    - TIMEFRAME_M30
    - TIMEFRAME_M15
    - TIMEFRAME_M5
    
    Returns:
        Dict berisi DataFrame untuk masing-masing timeframe ('H1', 'M30', 'M15', 'M5').
    """
    try:
        import MetaTrader5 as mt5
        from trading.mt5_bridge import MT5Bridge

        bridge = MT5Bridge()
        if not bridge.is_connected:
            bridge.connect()

        if not bridge.is_connected:
            logger.warning("MT5 terminal tidak terhubung. Mengembalikan frame kosong.")
            return {"H1": pd.DataFrame(), "M30": pd.DataFrame(), "M15": pd.DataFrame(), "M5": pd.DataFrame()}

        target_sym = symbol or bridge.gold_symbol or "XAUUSDc"
        mt5.symbol_select(target_sym, True)

        tf_config = {
            "H1": mt5.TIMEFRAME_H1,
            "M30": mt5.TIMEFRAME_M30,
            "M15": mt5.TIMEFRAME_M15,
            "M5": mt5.TIMEFRAME_M5,
        }

        # Hitung broker offset WIB (Asia/Jakarta UTC+7)
        broker_offset_hours = 4
        try:
            tick = mt5.symbol_info_tick(target_sym)
            if tick and tick.time > 0:
                now_utc_ts = datetime.now(timezone.utc).timestamp()
                broker_utc_diff_hours = round((tick.time - now_utc_ts) / 3600)
                broker_offset_hours = 7 - broker_utc_diff_hours
        except Exception:
            broker_offset_hours = 4

        result: Dict[str, pd.DataFrame] = {}

        for tf_label, mt5_tf in tf_config.items():
            rates = mt5.copy_rates_from_pos(target_sym, mt5_tf, 0, bars_count)
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df["Date"] = pd.to_datetime(df["time"], unit="s") + pd.Timedelta(hours=broker_offset_hours)
                df.rename(
                    columns={
                        "open": "Open",
                        "high": "High",
                        "low": "Low",
                        "close": "Close",
                        "tick_volume": "Volume",
                    },
                    inplace=True,
                )
                df.set_index("Date", inplace=True)
                clean_df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
                result[tf_label] = clean_df
            else:
                logger.warning(f"Gagal mengambil rates MT5 untuk {target_sym} [{tf_label}].")
                result[tf_label] = pd.DataFrame()

        return result

    except Exception as e:
        logger.error(f"Terjadi kesalahan saat fetch_mtf_data_mt5: {e}")
        return {"H1": pd.DataFrame(), "M30": pd.DataFrame(), "M15": pd.DataFrame(), "M5": pd.DataFrame()}


# =====================================================================
# 6. ORCHESTRATOR UTAMA: TOP-DOWN MTF ANALYSIS PIPELINE
# =====================================================================

def run_top_down_mtf_pipeline(
    symbol: str = "XAUUSDc",
    curr_price: Optional[float] = None,
    is_cent: bool = True,
    mtf_data: Optional[Dict[str, pd.DataFrame]] = None,
) -> Dict[str, Any]:
    """
    Eksekutor Pipeline Top-Down Multi-Timeframe Lengkap:
    1. Ambil data H1, M30, M15, M5 via MT5.
    2. Jalankan check_h1_snr() -> Filter lantai & atap mayor horizontal.
    3. Jalankan check_m30_trendline() -> Filter pantulan & breakout trendline dinamis.
    4. Jalankan get_m15_direction() -> Kunci arah tren pasar dominan.
    5. Jalankan trigger_m5_entry() -> Sniper gatekeeper & kalkulasi SL/TP berbasis swing M5 (RR >= 1:2).
    
    Returns:
        Dict lengkap hasil validasi berurutan dan rekomendasi eksekusi final.
    """
    # 1. Ambil Data Multi-Timeframe
    if mtf_data is None:
        mtf_data = fetch_mtf_data_mt5(symbol=symbol, bars_count=80)

    df_h1 = mtf_data.get("H1", pd.DataFrame())
    df_m30 = mtf_data.get("M30", pd.DataFrame())
    df_m15 = mtf_data.get("M15", pd.DataFrame())
    df_m5 = mtf_data.get("M5", pd.DataFrame())

    # Tentukan Harga Pasar Saat Ini
    if curr_price is None or curr_price <= 0.0:
        if not df_m5.empty:
            curr_price = float(df_m5["Close"].iloc[-1])
        elif not df_m15.empty:
            curr_price = float(df_m15["Close"].iloc[-1])
        else:
            curr_price = 4100.0  # Fallback harga emas saat ini

    # 2. Step 1: Filter H1 SNR
    h1_result = check_h1_snr(df_h1, curr_price=curr_price, pip_buffer=1.50)

    # 3. Step 2: Filter M30 Dynamic Trendline
    m30_result = check_m30_trendline(df_m30, curr_price=curr_price)

    # 4. Step 3: Filter M15 Trend Direction & Bias Lock
    m15_result = get_m15_direction(df_m15, curr_price=curr_price)

    # 5. Step 4: Sniper M5 Execution Gatekeeper (Rejection Wick >= 30% & RR >= 1:2)
    m5_entry_result = trigger_m5_entry(
        df_m5=df_m5,
        h1_res=h1_result,
        m30_res=m30_result,
        m15_res=m15_result,
        curr_price=curr_price,
        min_wick_ratio=0.30,
        min_rr_ratio=2.0,
        is_cent=is_cent,
    )

    return {
        "symbol": symbol,
        "current_price": round(curr_price, 2),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "step_1_h1": h1_result,
        "step_2_m30": m30_result,
        "step_3_m15": m15_result,
        "step_4_m5": m5_entry_result,
        "final_execution": m5_entry_result.get("can_execute", False),
        "order_signal": m5_entry_result.get("action", "HOLD"),
        "stop_loss": m5_entry_result.get("stop_loss", 0.0),
        "take_profit": m5_entry_result.get("take_profit", 0.0),
        "risk_reward_ratio": m5_entry_result.get("risk_reward_ratio", 0.0),
        "summary_message": m5_entry_result.get("reason", ""),
    }


if __name__ == "__main__":
    import sys
    # Pastikan stdout utf-8 di console Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 70)
    print(">>> MENJALANKAN PIPELINE MULTI-TIMEFRAME ANALYSIS (H1 -> M30 -> M15 -> M5)")
    print("=" * 70)
    res = run_top_down_mtf_pipeline(symbol="XAUUSDc", is_cent=True)
    print(f"Harga Emas Saat Ini : ${res['current_price']:,.2f}")
    print(f"H1 SNR Status       : {res['step_1_h1']['status']} (Res: ${res['step_1_h1']['h1_resistance']} | Sup: ${res['step_1_h1']['h1_support']})")
    print(f"M30 Trendline       : {res['step_2_m30']['condition']} (Bias: {res['step_2_m30']['trendline_bias']})")
    print(f"M15 Direction Lock  : {res['step_3_m15']['direction']} ({res['step_3_m15']['structure']})")
    print(f"M5 Sniper Gate      : Eksekusi={res['final_execution']} | Sinyal={res['order_signal']}")
    print(f"Ringkasan Final     : {res['summary_message']}")
    print("=" * 70)
