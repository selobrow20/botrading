"""
Unit Test untuk Sistem Deteksi Pembalikan Tren Awal & Ambil Untung Otomatis (Reversal Guard) XAU/USD.
Menguji:
1. Deteksi Bullish Reversal saat posisi SELL aktif (Candlestick Hammer + CHoCH Breakout EMA 20).
2. Deteksi Bearish Reversal saat posisi BUY aktif (Shooting Star + Breakdown EMA 20).
3. Penolakan sinyal palsu saat tren sehat berlanjut (tidak ada reversal).
4. Siklus Cooldown Reversal pada MT5Bridge.
5. Format notifikasi Telegram Reversal Guard.
"""

import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from strategy.reversal_detector import GoldReversalDetector
from trading.mt5_bridge import MT5Bridge
from notify.telegram_bot import TelegramNotifier


def test_detect_bullish_reversal_for_sell_position():
    """Menguji deteksi pembalikan naik (Bullish Reversal) saat posisi SELL sedang berjalan."""
    # Data bar candle menunjukkan harga menyentuh support dan memantul kuat (Hammer + menembus EMA 20)
    df = pd.DataFrame([
        {
            "Close": 4200.0, "Open": 4210.0, "High": 4212.0, "Low": 4195.0,
            "ema_20": 4208.0, "ema_50": 4230.0, "rsi": 25.0, "volume_ratio": 1.0,
            "pattern_pinbar": 0, "pattern_engulfing": 0, "pattern_shooting_star": 0,
            "structure_bos_bullish": 0, "structure_bos_bearish": 0,
        },
        {
            "Close": 4215.0, "Open": 4195.0, "High": 4218.0, "Low": 4180.0,
            "ema_20": 4209.0, "ema_50": 4228.0, "rsi": 38.0, "volume_ratio": 1.5,
            "pattern_pinbar": 1, "pattern_engulfing": 1, "pattern_shooting_star": 0,
            "structure_bos_bullish": 1, "structure_bos_bearish": 0,
            "rejection_wick_ratio": 0.40,
        },
    ])

    is_rev, rev_type, reasons, score = GoldReversalDetector.detect_reversal(
        df_ind=df,
        position_type="SELL",
        entry_price=4220.0,
        current_price=4215.0,
    )

    assert is_rev is True
    assert "BULLISH REVERSAL" in rev_type
    assert score >= 45.0
    assert len(reasons) >= 2


def test_detect_bearish_reversal_for_buy_position():
    """Menguji deteksi pembalikan turun (Bearish Reversal) saat posisi BUY sedang berjalan."""
    # Data bar candle menunjukkan penolakan tajam di puncak resisten (Shooting Star + breakdown EMA 20)
    df = pd.DataFrame([
        {
            "Close": 4250.0, "Open": 4240.0, "High": 4255.0, "Low": 4238.0,
            "ema_20": 4242.0, "ema_50": 4220.0, "rsi": 75.0, "volume_ratio": 1.0,
            "pattern_pinbar": 0, "pattern_engulfing": 0, "pattern_shooting_star": 0,
            "structure_bos_bullish": 0, "structure_bos_bearish": 0,
        },
        {
            "Close": 4235.0, "Open": 4252.0, "High": 4270.0, "Low": 4232.0,
            "ema_20": 4240.0, "ema_50": 4222.0, "rsi": 62.0, "volume_ratio": 1.4,
            "pattern_pinbar": 0, "pattern_engulfing": 1, "pattern_shooting_star": 1,
            "structure_bos_bullish": 0, "structure_bos_bearish": 1,
            "rejection_wick_ratio": 0.1,
        },
    ])

    is_rev, rev_type, reasons, score = GoldReversalDetector.detect_reversal(
        df_ind=df,
        position_type="BUY",
        entry_price=4230.0,
        current_price=4235.0,
    )

    assert is_rev is True
    assert "BEARISH REVERSAL" in rev_type
    assert score >= 45.0
    assert len(reasons) >= 2


def test_no_false_alarm_on_healthy_trend():
    """Memastikan tren yang sehat dan searah tidak memicu sinyal pembalikan palsu."""
    # Posisi SELL dengan harga terus turun teratur di bawah EMA 20 & 50
    df = pd.DataFrame([
        {
            "Close": 4210.0, "Open": 4215.0, "High": 4218.0, "Low": 4208.0,
            "ema_20": 4225.0, "ema_50": 4240.0, "rsi": 40.0, "volume_ratio": 0.8,
            "pattern_pinbar": 0, "pattern_engulfing": 0, "pattern_shooting_star": 0,
            "structure_bos_bullish": 0, "structure_bos_bearish": 0,
        },
        {
            "Close": 4202.0, "Open": 4210.0, "High": 4211.0, "Low": 4200.0,
            "ema_20": 4220.0, "ema_50": 4238.0, "rsi": 32.0, "volume_ratio": 0.9,
            "pattern_pinbar": 0, "pattern_engulfing": 0, "pattern_shooting_star": 0,
            "structure_bos_bullish": 0, "structure_bos_bearish": 0,
            "rejection_wick_ratio": 0.15,
        },
    ])

    is_rev, _, _, score = GoldReversalDetector.detect_reversal(
        df_ind=df,
        position_type="SELL",
        entry_price=4220.0,
        current_price=4202.0,
    )

    assert is_rev is False
    assert score < 40.0


def test_mt5_bridge_reversal_cooldown():
    """Menguji aktivasi, pengecekan, dan pembersihan mode cooldown reversal di MT5Bridge."""
    bridge = MT5Bridge(simulation_mode=True)
    bridge.clear_reversal_cooldown()

    # Awalnya tidak ada cooldown
    in_cd, msg = bridge.is_in_reversal_cooldown()
    assert in_cd is False

    # Aktifkan cooldown 30 menit
    bridge.set_reversal_cooldown(minutes=30, reason="Uji Coba Reversal")
    in_cd, msg = bridge.is_in_reversal_cooldown()
    assert in_cd is True
    assert "Mode Jeda Reversal Aktif" in msg
    assert "Uji Coba Reversal" in msg

    # Bersihkan cooldown manual
    bridge.clear_reversal_cooldown()
    in_cd, _ = bridge.is_in_reversal_cooldown()
    assert in_cd is False


def test_format_gold_reversal_telegram_alert():
    """Memastikan format kartu alert Telegram Reversal Guard lengkap dan valid."""
    notifier = TelegramNotifier()
    info = {
        "ticket": 15241647246,
        "action": "SELL",
        "symbol": "XAUUSDc",
        "volume": 0.05,
        "entry_price": 4214.64,
        "exit_price": 4196.50,
        "profit_usd": 90.70,
        "pnl_pct": 0.43,
        "reversal_type": "BULLISH REVERSAL (Skor Konfluensi: 75%)",
        "reasons": [
            "🕯️ Candlestick: Terbentuk Bullish Pinbar / Hammer",
            "🏛️ Struktur Pasar: Breakout Menembus Kembali ke Atas Dinamis 20 EMA",
        ],
        "cooldown_mins": 45,
    }

    msg = notifier.format_gold_reversal_alert(info)
    assert "REVERSAL GUARD" in msg
    assert "AMBIL UNTUNG OTOMATIS" in msg
    assert "#15241647246" in msg
    assert "$90.70 USD" in msg
    assert "BULLISH REVERSAL" in msg
    assert "Bullish Pinbar" in msg
    assert "45 Menit" in msg


def test_reject_weak_or_unconfirmed_reversal():
    """Memastikan koreksi kecil (pullback) tanpa konfirmasi struktur pasar TIDAK memicu penutupan dini."""
    # Posisi SELL: Terjadi candle hijau engulfing minor, tapi harga masih di bawah EMA 20 dan tidak ada BOS
    df = pd.DataFrame([
        {
            "Close": 4210.0, "Open": 4215.0, "High": 4218.0, "Low": 4208.0,
            "ema_20": 4225.0, "ema_50": 4240.0, "rsi": 40.0, "volume_ratio": 0.9,
            "pattern_pinbar": 0, "pattern_engulfing": 0, "pattern_shooting_star": 0,
            "structure_bos_bullish": 0, "structure_bos_bearish": 0,
        },
        {
            "Close": 4212.0, "Open": 4209.0, "High": 4213.0, "Low": 4208.0,
            "ema_20": 4224.0, "ema_50": 4239.0, "rsi": 42.0, "volume_ratio": 1.0,
            "pattern_pinbar": 0, "pattern_engulfing": 1, "pattern_shooting_star": 0,
            "structure_bos_bullish": 0, "structure_bos_bearish": 0,
            "rejection_wick_ratio": 0.1,
        },
    ])

    is_rev, _, reasons, score = GoldReversalDetector.detect_reversal(
        df_ind=df,
        position_type="SELL",
        entry_price=4220.0,
        current_price=4212.0,
    )

    # Karena pembalikan belum pasti/fix (hanya 1 pola minor, belum break structure EMA 20), posisi WAJIB dibiarkan jalan!
    assert is_rev is False
    assert score < 70.0


def test_early_reversal_warning_detection_and_formatting():
    """Menguji deteksi peringatan dini (Early Warning) saat gejala pembalikan awal mulai muncul."""
    df = pd.DataFrame([
        {
            "Close": 4200.0, "Open": 4210.0, "High": 4212.0, "Low": 4195.0,
            "ema_20": 4215.0, "ema_50": 4230.0, "rsi": 25.0, "volume_ratio": 1.0,
            "pattern_pinbar": 0, "pattern_engulfing": 0, "pattern_shooting_star": 0,
            "structure_bos_bullish": 0, "structure_bos_bearish": 0,
        },
        {
            "Close": 4208.0, "Open": 4195.0, "High": 4210.0, "Low": 4180.0,
            "ema_20": 4214.0, "ema_50": 4228.0, "rsi": 36.0, "volume_ratio": 1.3,
            "pattern_pinbar": 1, "pattern_engulfing": 0, "pattern_shooting_star": 0,
            "structure_bos_bullish": 0, "structure_bos_bearish": 0,
            "rejection_wick_ratio": 0.40,
        },
    ])

    is_warn, w_type, reasons, score = GoldReversalDetector.check_early_reversal_warning(
        df_ind=df,
        position_type="SELL",
        entry_price=4220.0,
        current_price=4208.0,
    )

    assert is_warn is True
    assert "BULLISH REVERSAL" in w_type
    assert score >= 40.0
    assert len(reasons) >= 2

    notifier = TelegramNotifier()
    info = {
        "ticket": 15243811670,
        "action": "SELL",
        "symbol": "XAUUSD",
        "volume": 0.05,
        "entry_price": 4220.0,
        "current_price": 4208.0,
        "score": score,
        "reasons": reasons,
        "reversal_type": w_type,
    }
    msg = notifier.format_early_reversal_warning(info)
    assert "PERINGATAN DINI PEMBALIKAN ARAH TREN" in msg
    assert "#15243811670" in msg
    assert "MASIH DIBIARKAN BERJALAN" in msg
    assert "SIAGA PENGAWALAN" in msg


def test_detect_fast_impulsive_reversal_buy():
    """Menguji deteksi junam kilat (Fast Impulsive Reversal) saat posisi BUY aktif."""
    df_m5 = pd.DataFrame([
        {"Open": 4175.0, "High": 4176.0, "Low": 4170.0, "Close": 4171.0, "ema_20": 4174.0},
        {"Open": 4171.0, "High": 4171.5, "Low": 4165.0, "Close": 4166.0, "ema_20": 4172.0},
    ])
    # Harga entry 4174.5, harga saat ini 4166.0 (turun 8.5 USD = 85 pips > 22 pips)
    is_fast, r_type, reasons, score = GoldReversalDetector.detect_fast_impulsive_reversal(
        position_type="BUY",
        entry_price=4174.5,
        current_price=4166.0,
        df_m5=df_m5,
        threshold_pips=22.0,
        session_code="LONDON",
    )
    assert is_fast is True
    assert "FAST BEARISH PLUNGE" in r_type
    assert score >= 90.0
    assert len(reasons) >= 2


def test_detect_fast_impulsive_reversal_sell():
    """Menguji deteksi lonjakan kilat (Fast Impulsive Reversal) saat posisi SELL aktif."""
    df_m5 = pd.DataFrame([
        {"Open": 4160.0, "High": 4166.0, "Low": 4159.0, "Close": 4165.0, "ema_20": 4161.0},
        {"Open": 4165.0, "High": 4172.0, "Low": 4164.0, "Close": 4171.0, "ema_20": 4163.0},
    ])
    # Harga entry 4162.0, harga saat ini 4171.0 (naik 9.0 USD = 90 pips > 22 pips)
    is_fast, r_type, reasons, score = GoldReversalDetector.detect_fast_impulsive_reversal(
        position_type="SELL",
        entry_price=4162.0,
        current_price=4171.0,
        df_m5=df_m5,
        threshold_pips=22.0,
        session_code="LONDON",
    )
    assert is_fast is True
    assert "FAST BULLISH PUMP" in r_type
    assert score >= 90.0
    assert len(reasons) >= 2


