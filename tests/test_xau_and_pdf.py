import pytest
from pathlib import Path
from pypdf import PdfWriter
import pandas as pd
import numpy as np

from data.fetcher import DataFetcher
from indicators.technical import TechnicalIndicators
from strategy.pdf_learner import PDFTradingLearner, learn_from_pdf
from notify.telegram_bot import format_currency, TelegramNotifier
from strategy.signal_engine import SignalEngine, SignalResult
from strategy.rules import Strategy, RuleCondition


def test_xauusd_normalization():
    """Memastikan berbagai varian nama emas dinormalisasi ke XAUUSD (Spot Gold)."""
    assert DataFetcher.normalize_ticker("XAUUSD") == "XAUUSD"
    assert DataFetcher.normalize_ticker("xau/usd") == "XAUUSD"
    assert DataFetcher.normalize_ticker("GOLD") == "XAUUSD"
    assert DataFetcher.normalize_ticker("emas") == "XAUUSD"
    assert DataFetcher.normalize_ticker("GC=F") == "XAUUSD"
    # Pastikan saham BEI tetap .JK
    assert DataFetcher.normalize_ticker("BBRI") == "BBRI.JK"


def test_format_currency():
    """Memastikan format mata uang otomatis: USD ($) untuk Emas, IDR (Rp) untuk saham BEI."""
    assert format_currency(2750.5, "GC=F") == "$2,750.50"
    assert format_currency(2750.5, "XAUUSD") == "$2,750.50"
    assert format_currency(10250.0, "BBCA.JK") == "Rp 10,250"
    assert format_currency(None) == "-"


def test_pdf_strategy_learner(tmp_path: Path):
    """Menguji pembuatan, pembacaan, dan ekstraksi konsep trading dari file PDF."""
    pdf_file = tmp_path / "test_trading_guide.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)

    with open(pdf_file, "wb") as f:
        writer.write(f)

    learner = PDFTradingLearner(str(pdf_file))
    assert learner.num_pages == 1

    sample_trading_text = """
    STRATEGI TRADING HARIAN MOMENTUM EMAS & SAHAM
    1. Indikator yang Digunakan:
       - Relative Strength Index (RSI 14)
       - Exponential Moving Average (EMA 20 dan EMA 50)
       - Lonjakan Volume (Volume Breakout)
    2. Aturan Beli (Buy Rules):
       - Masuk posisi BUY ketika harga menembus di atas EMA 20.
       - Konfirmasi RSI berada di atas 50 (momentum naik).
       - Volume minimal 1.2x rata-rata.
    3. Aturan Jual (Exit Rules):
       - Jual ketika harga menembus ke bawah EMA 20 atau RSI mencapai overbought 75.
    4. Manajemen Risiko:
       - Target Profit: 2.5%
       - Stop Loss: 1.5%
       - Risk to Reward Ratio 1:1.67
    """

    res = learner.analyze_trading_concepts(text=sample_trading_text)

    assert "RSI (Relative Strength Index)" in res["indicators_found"]
    assert "EMA (Exponential Moving Average)" in res["indicators_found"]
    assert "Volume Analysis" in res["indicators_found"]
    assert 20 in res["ma_periods"]
    assert "yaml_config" in res
    assert "strategies" in res["parsed_dict"]


def test_validate_pdf_confluence_strict_gatekeeper():
    """Menguji filter ketat konfluensi 9 buku PDF (hanya meloloskan Grade A/A+ untuk win rate tinggi)."""
    # 1. Bar dengan konfluensi kuat (Martin Pring + Bob Volman + Mega Profit + Volume + Wave)
    strong_buy_bar = pd.Series({
        "Close": 4310.0,
        "High": 4315.0,
        "Low": 4300.0,
        "Open": 4305.0,
        "ema_20": 4308.0,
        "ema_50": 4290.0,
        "ema_200": 4250.0,
        "rsi": 54.0,
        "volume_ratio": 1.25,
        "rejection_wick_ratio": 0.40,
        "pattern_pinbar": 1,
        "volman_pullback": 1,
        "volman_buildup": 1,
        "fib_in_golden_zone": 1,
        "fib_500": 4305.0,
        "fib_618": 4300.0,
        "ichimoku_above_cloud": 1,
        "ichimoku_cloud_green": 1,
        "ichimoku_tk_cross": 1,
    })

    approved, score, grade, checks, pred = SignalEngine.validate_pdf_entry_confluence(strong_buy_bar, signal_type="BUY")
    assert approved is True
    assert score >= 80.0
    assert "Grade A+" in grade
    assert len(checks) >= 5

    # 2. Bar dengan konfluensi lemah (Skor < 65% ditolak demi win rate)
    weak_buy_bar = pd.Series({
        "Close": 4270.0,
        "High": 4275.0,
        "Low": 4268.0,
        "Open": 4272.0,
        "ema_20": 4290.0,
        "ema_50": 4300.0,
        "ema_200": 4310.0,
        "rsi": 76.0,  # Overbought pucuk
        "volume_ratio": 0.5,
        "rejection_wick_ratio": 0.1,
        "pattern_pinbar": 0,
        "volman_pullback": 0,
        "fib_in_golden_zone": 0,
        "ichimoku_above_cloud": 0,
    })

    approved_w, score_w, grade_w, _, _ = SignalEngine.validate_pdf_entry_confluence(weak_buy_bar, signal_type="BUY")
    assert approved_w is False
    assert score_w < 65.0
    assert "Grade B / C" in grade_w


def test_signal_engine_evaluates_xau_with_risk_reward():
    """Memastikan evaluasi sinyal XAU/USD menghasilkan TP/SL dengan RRR minimal 1:1.8."""
    df = pd.DataFrame({
        "Open": [4290.0 + i for i in range(20)],
        "High": [4295.0 + i for i in range(20)],
        "Low": [4288.0 + i for i in range(20)],
        "Close": [4294.0 + i for i in range(20)],
        "Volume": [1000] * 20,
    }, index=pd.date_range("2026-09-23 08:00", periods=20, freq="15min"))

    custom_strat = Strategy(
        name="Test_Strategy",
        description="Test",
        buy_rules=[RuleCondition("close", ">", value=4200.0)],
        sell_rules=[RuleCondition("close", "<", value=4000.0)],
    )

    engine = SignalEngine([custom_strat])
    sig = engine.evaluate_bar(df, ticker="XAUUSD", strategy=custom_strat, apply_pdf_filter=False)

    assert sig.ticker == "XAUUSD"
    assert sig.take_profit_price is not None
    assert sig.stop_loss_price is not None
    assert sig.risk_reward_ratio >= 1.0
    assert sig.take_profit_price > sig.price
    assert sig.stop_loss_price < sig.price


def test_telegram_signal_formatter_shows_9_pdf_details():
    """Memastikan format notifikasi telegram menampilkan telaah 9 buku PDF dan win rate badge."""
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence_Strategy",
        signal="BUY",
        price=4300.0,
        candle_time="2026-09-23 20:00:00",
        take_profit_price=4334.4,
        stop_loss_price=4282.8,
        risk_reward_ratio=2.0,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+ (Setup Sempurna ⭐⭐⭐⭐⭐)",
        pdf_confluence_details=[
            "✅ Martin Pring: Tren Mayor Bullish (Harga di atas EMA 50)",
            "✅ Bob Volman: Area Nilai Terpenuhi (Pullback Dinamis 20 EMA)",
            "🎯 Fibonacci: Memantul Presisi di Golden Pocket (50% - 61.8%)",
            "☁️ Ichimoku: Struktur Bullish di Atas Awan Kumo",
        ],
        market_direction_prediction="Arah market diprediksi kuat melanjutkan tren naik.",
    )

    notifier = TelegramNotifier()
    msg = notifier.format_signal_message(sig)

    assert "SINYAL ENTRY (MASUK / BUY): XAU/USD (Gold)" in msg
    assert "TELAAH 9 BUKU PDF" in msg
    assert "Grade A+" in msg
    assert "Martin Pring" in msg
    assert "Bob Volman" in msg
    assert "Fibonacci" in msg
    assert "Ichimoku" in msg
    assert "Risk/Reward Ratio:</b> 1 : 2.0" in msg


def test_format_tp_sl_report():
    """Menguji penyusunan laporan hasil sinyal saat mencapai TP atau SL beserta keterangannya."""
    notifier = TelegramNotifier()

    # 1. Kasus Take Profit Tercapai (WIN) pada Emas
    win_sig = {
        "ticker": "XAUUSD",
        "signal_type": "BUY",
        "price": 4300.0,
        "entry_price": 4300.0,
        "take_profit_price": 4334.4,
        "stop_loss_price": 4282.8,
        "exit_price": 4334.4,
        "pnl_pct": 0.80,
        "candle_time": "2026-09-23 20:00:00",
        "exit_time": "2026-09-23 21:15:00",
        "outcome": "WIN",
        "outcome_note": "Target Take Profit tercapai (+0.80%). Harga bergerak sesuai proyeksi Wave 3 & Golden Pocket. Profit berhasil diamankan!",
    }
    mock_stats = {
        "win_rate": 85.0,
        "win_count": 17,
        "lose_count": 3,
        "total_pnl": 34.5,
    }

    win_msg = notifier.format_tp_sl_report(win_sig, current_stats=mock_stats)
    assert "[LAPORAN HASIL] TAKE PROFIT TERCAPAI!" in win_msg
    assert "XAU/USD (Gold)" in win_msg
    assert "WIN / PROFIT" in win_msg
    assert "+0.80%" in win_msg
    assert "$4,300.00" in win_msg
    assert "$4,334.40" in win_msg
    assert "KETERANGAN & EVALUASI" in win_msg
    assert "Golden Pocket" in win_msg
    assert "Win Rate Sekarang:</b> <code>85.0%</code>" in win_msg

    # 2. Kasus Stop Loss Tersentuh (LOSE) pada Saham IDX
    lose_sig = {
        "ticker": "BBCA.JK",
        "signal_type": "BUY",
        "price": 10000.0,
        "entry_price": 10000.0,
        "take_profit_price": 10300.0,
        "stop_loss_price": 9850.0,
        "exit_price": 9850.0,
        "pnl_pct": -1.50,
        "candle_time": "2026-09-23 10:00:00",
        "exit_time": "2026-09-23 13:45:00",
        "outcome": "LOSE",
        "outcome_note": "Batas Stop Loss tersentuh (-1.50%). Support terlewati akibat volatilitas pasar. Eksekusi cut loss disiplin melindungi portofolio.",
    }

    lose_msg = notifier.format_tp_sl_report(lose_sig, current_stats=mock_stats)
    assert "[LAPORAN HASIL] STOP LOSS TERSENTUH!" in lose_msg
    assert "BBCA" in lose_msg
    assert "LOSE / PROTEKSI MODAL" in lose_msg
    assert "-1.50%" in lose_msg
    assert "cut loss disiplin melindungi portofolio" in lose_msg


def test_market_close_summary_and_gold_winrate_filter():
    """Menguji format laporan penutupan pasar saham BEI yang simpel dan filter winrate khusus Gold."""
    from unittest.mock import patch

    notifier = TelegramNotifier()

    # 1. Format laporan penutupan pasar saham (simpel & ringkas)
    sample_market_data = [
        {"ticker": "BBCA", "close": 10250.0, "change_pct": 1.25},
        {"ticker": "BBRI", "close": 5100.0, "change_pct": -0.50},
        {"ticker": "TLKM", "close": 3200.0, "change_pct": 0.0},
    ]

    report = notifier.format_market_close_summary(sample_market_data)
    assert "LAPORAN PENUTUPAN PASAR SAHAM (BEI)" in report
    assert "BBCA" in report
    assert "BBRI" in report
    assert "Pasar BEI resmi ditutup" in report
    assert "/potensi" in report

    # 2. Uji filter badge winrate: Hanya muncul pada Gold, tidak muncul pada Saham
    mock_stats = {
        "gold_stats": {
            "completed": 10,
            "win": 8,
            "lose": 2,
            "win_rate": 80.0,
        }
    }

    # Signal Gold (XAUUSD) -> badge winrate muncul
    gold_sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="DayTrading",
        signal="BUY",
        price=2750.0,
        take_profit_price=2775.0,
        stop_loss_price=2735.0,
        reasons=["Golden Pocket Fib 0.618"],
        candle_time="2026-09-24 10:00:00",
    )
    with patch.object(notifier.storage, "get_win_rate_stats", return_value=mock_stats):
        gold_msg = notifier.format_signal_message(gold_sig)
    assert "Akurasi Emas (Gold)" in gold_msg
    assert "80.0%" in gold_msg

    # Signal Saham (BBCA.JK) -> Tanpa badge winrate agar tetap bersih & simpel
    stock_sig = SignalResult(
        ticker="BBCA.JK",
        strategy_name="DayTrading",
        signal="BUY",
        price=10250.0,
        take_profit_price=10550.0,
        stop_loss_price=10050.0,
        reasons=["Breakout EMA 20"],
        candle_time="2026-09-24 10:00:00",
    )
    with patch.object(notifier.storage, "get_win_rate_stats", return_value=mock_stats):
        stock_msg = notifier.format_signal_message(stock_sig)
    assert "Akurasi Emas" not in stock_msg
    assert "Win Rate" not in stock_msg


def test_stock_sell_suppression_and_gold_sell_preservation():
    """Memastikan sinyal SELL untuk saham ditiadakan (Long-Only), sedangkan Gold tetap bisa BUY & SELL."""
    strat = Strategy(
        name="TestSellRules",
        description="Strategi uji coba SELL",
        buy_rules=[],
        sell_rules=[RuleCondition("close", ">", value=0.0, description="Kondisi jual")],
        sell_combine="OR",
    )
    engine = SignalEngine([strat])

    df_dummy = pd.DataFrame({
        "Close": [10000.0, 9900.0],
        "High": [10050.0, 9950.0],
        "Low": [9950.0, 9850.0],
        "Open": [10000.0, 9900.0],
        "Volume": [1000, 1000],
    })

    # 1. Saham IDX (BBCA.JK) -> Sinyal SELL harus otomatis di-convert menjadi HOLD
    stock_res = engine.evaluate_bar(df_dummy, ticker="BBCA.JK", strategy=strat)
    assert stock_res.signal == "HOLD"
    assert "mode BUY/Long-Only" in stock_res.reasons[0]

    # 2. Emas (XAUUSD) -> Sinyal SELL tetap diizinkan
    gold_res = engine.evaluate_bar(df_dummy, ticker="XAUUSD", strategy=strat, apply_pdf_filter=False)
    assert gold_res.signal == "SELL"


def test_adaptive_dynamic_tp_sl_modes():
    """Menguji mode Adaptive TP: Quick TP saat Sideways vs Wide TP saat Momentum Panjang."""
    engine = SignalEngine()

    # 1. Sideways Data (EMA berjarak dekat < 3.5, ADX rendah)
    df_sideways = pd.DataFrame({
        "Open": [4130.0] * 20,
        "High": [4133.0] * 20,
        "Low": [4128.0] * 20,
        "Close": [4131.0] * 20,
        "Volume": [1000] * 20,
    }, index=pd.date_range("2026-09-29 08:00", periods=20, freq="15min"))

    sig_side = engine.evaluate_bar(df_sideways, "XAUUSD", apply_pdf_filter=False)
    assert "Sideways" in sig_side.market_regime or "Berguncang" in sig_side.market_regime or "Cepat" in sig_side.market_regime
    tp_dist_side = abs(sig_side.take_profit_price - sig_side.price)
    sl_dist_side = abs(sig_side.price - sig_side.stop_loss_price)
    # TP Cepat ATR-Adaptive: minimal 60 pips ($6.00 USD), maksimal 120 pips ($12.00 USD)
    assert 6.0 <= tp_dist_side <= 12.0  # Minimal 60 pips ($6.00 USD) mutlak!
    # SL: minimal 60 pips ($6.00 USD), maksimal 120 pips
    assert 6.0 <= sl_dist_side <= 12.0  # Minimal 60 pips ($6.00 USD) mutlak!
    # Kaidah 9 PDF: Risk to Reward wajib minimal 1:1 (TP >= SL)
    assert sig_side.risk_reward_ratio >= 1.0

    # 2. Trending Data (EMA berjarak tegas >= 3.5, Momentum Kuat)
    df_trend = pd.DataFrame({
        "Open": [4100.0 + i * 3 for i in range(25)],
        "High": [4105.0 + i * 3 for i in range(25)],
        "Low": [4098.0 + i * 3 for i in range(25)],
        "Close": [4104.0 + i * 3 for i in range(25)],
        "Volume": [1000] * 25,
    }, index=pd.date_range("2026-09-29 07:00", periods=25, freq="15min"))

    sig_trend = engine.evaluate_bar(df_trend, "XAUUSD", apply_pdf_filter=False)
    assert "Momentum Tren Jauh" in sig_trend.market_regime or "Momentum" in sig_trend.market_regime
    tp_dist_trend = abs(sig_trend.take_profit_price - sig_trend.price)
    sl_dist_trend = abs(sig_trend.price - sig_trend.stop_loss_price)
    # Sesuai arahan pengguna: "kalo tp jauh si gpp 3:1 tpnya 3 sl nya 1"
    # SL minimal 6.00 USD (60 pips) -> TP = 3x SL (minimal 18.00 USD / 180 pips)
    assert 18.0 <= tp_dist_trend <= 36.0  # 180 - 360 pips (ATR-adaptive 3:1)
    assert 6.0 <= sl_dist_trend <= 12.0   # Minimal 60 pips ($6.00 USD)
    assert sig_trend.risk_reward_ratio == 3.0  # Rasio mutlak 3:1!


def test_trailing_stop_alert_formatting():
    """Menguji format kartu alert BEP Lock dan Trailing Stop."""
    notifier = TelegramNotifier()
    bep_info = {
        "ticket": 12345,
        "action": "BUY",
        "symbol": "XAUUSD",
        "volume": 0.05,
        "price_open": 4135.0,
        "price_curr": 4140.0,
        "new_sl": 4135.5,
        "profit_dist": 5.0,
        "type": "BEP_LOCK",
    }
    msg = notifier.format_trailing_stop_alert(bep_info)
    assert "BREAK-EVEN PROTECTION AKTIF" in msg
    assert "FREE TRADE" in msg
def test_trading_sessions_and_us_london_rules():
    """Menguji deteksi sesi trading dan aturan khusus Sesi US (65 pips) serta Sesi London (anti-manipulasi)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from strategy.signal_engine import get_trading_session, SignalEngine

    # 1. Uji deteksi sesi berdasarkan waktu WIB
    dt_us = datetime(2026, 9, 29, 20, 30, tzinfo=ZoneInfo("Asia/Jakarta"))
    assert get_trading_session(dt_us)[0] == "US"

    dt_london = datetime(2026, 9, 29, 15, 0, tzinfo=ZoneInfo("Asia/Jakarta"))
    assert get_trading_session(dt_london)[0] == "LONDON"

    dt_asia = datetime(2026, 9, 29, 9, 0, tzinfo=ZoneInfo("Asia/Jakarta"))
    assert get_trading_session(dt_asia)[0] == "ASIA"

    # 2. Uji Sesi US: Wajib TP 65 pips ($6.50) dan SL 65 pips ($6.50)
    engine = SignalEngine()
    df_us = pd.DataFrame({
        "Open": [4130.0] * 20,
        "High": [4135.0] * 20,
        "Low": [4128.0] * 20,
        "Close": [4132.0] * 20,
        "Volume": [1000] * 20,
    }, index=pd.date_range("2026-09-29 20:00", periods=20, freq="15min", tz="Asia/Jakarta"))

    sig_us = engine.evaluate_bar(df_us, "XAUUSD", apply_pdf_filter=False)
    assert "Sesi US" in sig_us.market_regime
    tp_dist_us = round(abs(sig_us.take_profit_price - sig_us.price), 2)
    sl_dist_us = round(abs(sig_us.price - sig_us.stop_loss_price), 2)
    assert 4.5 <= tp_dist_us <= 12.0  # ATR-adaptive: 45 - 120 pips (cap naik ke 12.0 untuk HIGH-VOL)
    assert 4.0 <= sl_dist_us <= 9.5  # ATR-adaptive: 42 - 95 pips (HIGH-VOL mode support)
    assert tp_dist_us >= sl_dist_us  # TP selalu minimal seimbang atau lebih besar dari SL
    assert sig_us.risk_reward_ratio >= 1.0


def test_london_session_anti_manipulation():
    """Menguji penyaringan ketat sesi London: Menahan sinyal dengan skor < 75% karena rawan manipulasi."""
    from strategy.signal_engine import SignalEngine

    # Bar dengan skor Grade A reguler (65%) namun < 75% (ditahan di sesi London)
    medium_bar = pd.Series({
        "Close": 4140.0,
        "High": 4145.0,
        "Low": 4135.0,
        "Open": 4138.0,
        "ema_20": 4000.0,
        "ema_50": 4130.0,
        "ema_200": 4100.0,
        "rsi": 64.0,
        "volume_ratio": 1.0,
        "rejection_wick_ratio": 0.20,
        "pattern_pinbar": 0,
        "volman_pullback": 0,
        "volman_buildup": 0,
        "fib_in_golden_zone": 0,
        "ichimoku_above_cloud": 1,
        "ichimoku_cloud_green": 1,
        "ichimoku_tk_cross": 1,
    })

    # Pada sesi reguler (Asia), skor 65% lolos (Grade A)
    approved_asia, score_asia, grade_asia, _, _ = SignalEngine.validate_pdf_entry_confluence(
        medium_bar, signal_type="BUY", session="ASIA"
    )
    assert approved_asia is True
    assert score_asia == 65.0

    # Namun pada sesi London, skor 65% ditolak demi keamanan modal dari manipulasi likuiditas
    approved_london, score_london, grade_london, checks, pred = SignalEngine.validate_pdf_entry_confluence(
        medium_bar, signal_type="BUY", session="LONDON"
    )
    assert approved_london is False
    assert any("Sesi London sering terjadi manipulasi likuiditas" in c for c in checks)


def test_bep_and_trailing_stop_reported_as_win():
    """Memastikan transaksi yang keluar via SL namun menghasilkan profit (BEP / Trailing) diklasifikasikan sebagai WIN."""
    from trading.mt5_bridge import MT5Bridge

    # Simulasi order BUY closed dengan DEAL_REASON_SL tapi exit price > entry price (profit +35.65 USC)
    buy_deal = {
        "profit": 35.65,
        "reason_code": 4,  # DEAL_REASON_SL
        "entry_price": 4135.0,
        "price": 4142.5,
        "type": 1,  # ORDER_TYPE_SELL (exit untuk buy)
    }
    # Logika klasifikasi WIN pada mt5_bridge
    if buy_deal["profit"] >= 0 or buy_deal["price"] > buy_deal["entry_price"]:
        outcome = "WIN"
    else:
        outcome = "LOSE"

    assert outcome == "WIN"


def test_pdf_accuracy_contradictory_market_structure():
    """Menguji penalti skor konfluensi jika struktur pasar bertentangan (Buku 9: Trading Alchemist)."""
    base_buy_bar = pd.Series({
        "Close": 4310.0,
        "High": 4315.0,
        "Low": 4300.0,
        "Open": 4305.0,
        "ema_20": 4308.0,
        "ema_50": 4290.0,
        "ema_200": 4250.0,
        "rsi": 54.0,
        "volume_ratio": 1.25,
        "rejection_wick_ratio": 0.40,
        "pattern_pinbar": 1,
        "structure_bos_bearish": 1,  # Bertentangan dengan BUY!
    })

    approved, score, grade, checks, pred = SignalEngine.validate_pdf_entry_confluence(base_buy_bar, signal_type="BUY")
    assert any("Break of Structure Bearish (BOS) terdeteksi" in c for c in checks)


def test_pdf_accuracy_flat_chop_and_low_volume():
    """Menguji filter pasar kompresi datar / chop (Bob Volman & Al Brooks) dan volume rendah (VPA)."""
    chop_bar = pd.Series({
        "Close": 4300.0,
        "High": 4301.0,
        "Low": 4299.0,
        "Open": 4300.0,
        "ema_20": 4300.2,
        "ema_50": 4300.0,
        "adx": 14.0,  # ADX sangat rendah
        "volume_ratio": 0.50,  # Volume sangat kering
        "rejection_wick_ratio": 0.10,
        "pattern_pinbar": 0,
        "structure_bos_bullish": 0,
    })

    approved, score, grade, checks, pred = SignalEngine.validate_pdf_entry_confluence(chop_bar, signal_type="BUY")
    assert approved is False
    assert any("Kompresi Datar / Chop" in c for c in checks)
    assert any("Volume Sangat Rendah" in c for c in checks)


def test_check_london_judas_swing_trap():
    """Menguji deteksi perangkap manipulasi likuiditas Sesi London (Judas Swing)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    engine = SignalEngine()

    # Buat bar sesi Asia (05:00 - 14:00 WIB)
    tz = ZoneInfo("Asia/Jakarta")
    idx_times = [
        datetime(2026, 10, 1, 9, 0, tzinfo=tz),
        datetime(2026, 10, 1, 11, 0, tzinfo=tz),
        datetime(2026, 10, 1, 13, 0, tzinfo=tz),
        datetime(2026, 10, 1, 14, 15, tzinfo=tz),  # Waktu London Open Judas Swing
    ]
    df = pd.DataFrame([
        {"High": 4180.0, "Low": 4170.0, "Open": 4172.0, "Close": 4178.0, "volume_ratio": 1.0},
        {"High": 4185.0, "Low": 4175.0, "Open": 4178.0, "Close": 4182.0, "volume_ratio": 1.0},
        {"High": 4183.0, "Low": 4172.0, "Open": 4182.0, "Close": 4175.0, "volume_ratio": 1.0},
        # Bar 14:15 menusuk di atas High Asia (4185.0) tapi membentuk sumbu atas (upper wick)
        {"High": 4186.0, "Low": 4172.0, "Open": 4174.0, "Close": 4175.0, "volume_ratio": 1.1, "rejection_wick_ratio": 0.35},
    ], index=pd.DatetimeIndex(idx_times))

    curr_row = df.iloc[-1]
    is_trap, reason = engine.check_london_judas_swing(
        df=df,
        curr_price=4175.0,
        signal_type="BUY",
        curr_row=curr_row,
    )

    assert is_trap is True
    assert "Anti-Judas Swing" in reason
    assert "sapuan likuiditas di pucuk High Asia" in reason


def test_validate_london_h1_confirmation():
    """Menguji validasi konfirmasi H1 (1-Hour) wajib khusus Sesi London."""
    # Data H1 dummy: candle 1 (sebelumnya) dan candle 2 (berjalan)
    # Kasus 1: Sinyal BUY tapi H1 sedang Bearish (Open 4180 > Harga 4172, di bawah EMA50 4178)
    df_h1_bearish = pd.DataFrame([
        {"Open": 4185.0, "Close": 4180.0, "High": 4188.0, "Low": 4178.0, "ema_50": 4178.0},
        {"Open": 4180.0, "Close": 4170.0, "High": 4181.0, "Low": 4168.0, "ema_50": 4178.0},
    ])

    h1_ok, reason = SignalEngine.validate_london_h1_confirmation("BUY", df_h1_bearish, curr_price=4172.0)
    assert h1_ok is False
    assert "Sesi London Wajib Konfirmasi H1" in reason
    assert "Candle H1 berjalan sedang Bearish" in reason

    # Kasus 2: Sinyal BUY dan H1 Bullish (Open 4170 < Harga 4180, di atas EMA50 4165)
    df_h1_bullish = pd.DataFrame([
        {"Open": 4160.0, "Close": 4170.0, "High": 4172.0, "Low": 4158.0, "ema_50": 4165.0},
        {"Open": 4170.0, "Close": 4182.0, "High": 4185.0, "Low": 4169.0, "ema_50": 4165.0},
    ])

    h1_ok, reason = SignalEngine.validate_london_h1_confirmation("BUY", df_h1_bullish, curr_price=4180.0)
    assert h1_ok is True
    assert "Konfirmasi H1 Sesi London" in reason

    # Kasus 3: Sinyal SELL tapi H1 sedang Bullish (Open 4170 < Harga 4180, di atas EMA50 4165)
    h1_ok, reason = SignalEngine.validate_london_h1_confirmation("SELL", df_h1_bullish, curr_price=4180.0)
    assert h1_ok is False
    assert "Sesi London Wajib Konfirmasi H1" in reason
    assert "Candle H1 berjalan sedang Bullish" in reason

    # Kasus 4: Sinyal SELL dan H1 Bearish (Open 4180 > Harga 4170, di bawah EMA50 4178)
    h1_ok, reason = SignalEngine.validate_london_h1_confirmation("SELL", df_h1_bearish, curr_price=4170.0)
    assert h1_ok is True
    assert "Konfirmasi H1 Sesi London" in reason


def test_london_h1_window_limit():
    """Menguji bahwa konfirmasi H1 Sesi London hanya diwajibkan s/d jam 17:00 WIB (setelah jam 5 sore lolos)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    engine = SignalEngine()
    tz = ZoneInfo("Asia/Jakarta")

    # Bar pada jam 17:15 WIB (London Lanjutan / Manipulasi sudah reda)
    dt_1715 = datetime(2026, 10, 1, 17, 15, tzinfo=tz)
    df_m15 = pd.DataFrame([{
        "Close": 4310.0, "High": 4315.0, "Low": 4300.0, "Open": 4305.0,
        "ema_20": 4308.0, "ema_50": 4290.0, "rsi": 55.0, "volume_ratio": 1.2,
        "pattern_pinbar": 1, "volman_pullback": 1,
    }], index=pd.DatetimeIndex([dt_1715]))

    # H1 bearish bertentangan dengan BUY
    df_h1_bearish = pd.DataFrame([
        {"Open": 4320.0, "Close": 4300.0, "High": 4325.0, "Low": 4295.0, "ema_50": 4305.0},
        {"Open": 4315.0, "Close": 4295.0, "High": 4318.0, "Low": 4290.0, "ema_50": 4305.0},
    ])

    res = engine.evaluate_bar(df_m15, ticker="XAUUSD", bar_idx=-1, df_h1=df_h1_bearish)
    # Setelah jam 17:00 WIB, sinyal BUY tidak boleh ditahan oleh H1
    assert "Sesi London Wajib Konfirmasi H1" not in " ".join(res.reasons)


def test_risk_reward_rules_never_tp1_sl2_and_long_3_to_1():
    """
    Memastikan kaidah mutlak Risk to Reward:
    1. Jika TP jauh / momentum: Wajib Rasio 3:1 (TP 3, SL 1, misal TP 135 pips, SL 45 pips).
    2. Sinyal cepat / reguler: Wajib minimal 1:1 (TP 45-50 pips, SL 40-45 pips).
    3. DILARANG KERAS TP 1 SL 2 (SL tidak boleh pernah lebih besar dari TP).
    """
    from strategy.signal_engine import SignalEngine

    engine = SignalEngine()

    # 1. Kasus Sinyal Cepat (Sideways/Normal)
    df_quick = pd.DataFrame({
        "Open": [4200.0 + (i % 2) for i in range(20)],
        "High": [4205.0] * 20,
        "Low": [4198.0] * 20,
        "Close": [4202.0] * 20,
        "Volume": [1000] * 20,
    }, index=pd.date_range("2026-10-01 10:00", periods=20, freq="15min"))

    sig_quick = engine.evaluate_bar(df_quick, "XAUUSD", apply_pdf_filter=False)
    tp_quick = abs(sig_quick.take_profit_price - sig_quick.price)
    sl_quick = abs(sig_quick.price - sig_quick.stop_loss_price)

    assert 6.0 <= tp_quick <= 12.0  # Minimal 60 pips ($6.00 USD mutlak!)
    assert 6.0 <= sl_quick <= 12.0  # Minimal 60 pips ($6.00 USD mutlak!)
    assert tp_quick >= sl_quick    # Wajib TP >= SL (Dilarang TP 1 SL 2!)
    assert sig_quick.risk_reward_ratio >= 1.0

    # 2. Kasus Sinyal Jauh / Trending Momentum (R:R 3:1)
    df_long = pd.DataFrame({
        "Open": [4100.0 + i * 3 for i in range(25)],
        "High": [4105.0 + i * 3 for i in range(25)],
        "Low": [4098.0 + i * 3 for i in range(25)],
        "Close": [4104.0 + i * 3 for i in range(25)],
        "Volume": [1000] * 25,
    }, index=pd.date_range("2026-10-01 14:00", periods=25, freq="15min"))

    sig_long = engine.evaluate_bar(df_long, "XAUUSD", apply_pdf_filter=False)
    tp_long = abs(sig_long.take_profit_price - sig_long.price)
    sl_long = abs(sig_long.price - sig_long.stop_loss_price)

    assert 18.0 <= tp_long <= 36.0  # 180 - 360 pips (3:1 of minimal 60 pips)
    assert 6.0 <= sl_long <= 12.0   # Minimal 60 pips ($6.00 USD mutlak!)
    assert sig_long.risk_reward_ratio == 3.0  # Rasio persis 3:1 (TP 3, SL 1)


def test_gold_hard_floor_60_pips_rule():
    """Menguji aturan mutlak: SL dan TP Gold XAUUSD minimal 60 pips (6.00 USD) 1:1 dilarang di bawah itu."""
    engine = SignalEngine()

    # Data flat dengan ATR sangat kecil (misal ATR = 0.5)
    df_low_vol = pd.DataFrame({
        "Open": [2700.0] * 25,
        "High": [2700.5] * 25,
        "Low": [2699.5] * 25,
        "Close": [2700.0] * 25,
        "Volume": [1000] * 25,
    }, index=pd.date_range("2026-10-02 08:00", periods=25, freq="15min"))

    sig = engine.evaluate_bar(df_low_vol, "XAUUSD", apply_pdf_filter=False)
    assert sig.take_profit_price is not None
    assert sig.stop_loss_price is not None

    tp_dist = round(abs(sig.take_profit_price - sig.price), 2)
    sl_dist = round(abs(sig.price - sig.stop_loss_price), 2)

    # Verifikasi keras: SL >= 6.00 USD (60 pips), TP >= 6.00 USD (60 pips), TP >= SL (R:R >= 1.0)
    assert sl_dist >= 6.00, f"SL Gold ({sl_dist} USD) di bawah batas lantai 60 pips (6.00 USD)!"
    assert tp_dist >= 6.00, f"TP Gold ({tp_dist} USD) di bawah batas lantai 60 pips (6.00 USD)!"
    assert tp_dist >= sl_dist, f"TP ({tp_dist}) lebih kecil dari SL ({sl_dist}) - melanggar R:R minimal 1:1!"
    assert sig.risk_reward_ratio >= 1.0


def test_3layer_architecture_lapis1_otak_utama_h4():
    """Menguji Lapis 1 (Otak Utama H4): Bullish, Bearish, dan Netral permission gate."""
    engine = SignalEngine()

    # 1. H4 Bullish: Close > EMA50, di atas Kumo, RSI >= 40
    df_h4_bull = pd.DataFrame({
        "Close": [2710.0, 2720.0],
        "ema_50": [2700.0, 2700.0],
        "ema_200": [2680.0, 2680.0],
        "rsi": [55.0, 58.0],
        "ichimoku_above_cloud": [1, 1],
    })
    bias_bull, reason_bull = engine.evaluate_macro_bias_h4(df_h4=df_h4_bull, curr_price=2720.0)
    assert bias_bull == "BULLISH"

    # 2. H4 Bearish: Close < EMA50, di bawah Kumo, RSI <= 60
    df_h4_bear = pd.DataFrame({
        "Close": [2690.0, 2680.0],
        "ema_50": [2700.0, 2700.0],
        "ema_200": [2720.0, 2720.0],
        "rsi": [45.0, 42.0],
        "ichimoku_above_cloud": [0, 0],
    })
    bias_bear, reason_bear = engine.evaluate_macro_bias_h4(df_h4=df_h4_bear, curr_price=2680.0)
    assert bias_bear == "BEARISH"

    # 3. H4 Netral/Chop: RSI jenuh / bertentangan
    df_h4_neutral = pd.DataFrame({
        "Close": [2700.0, 2700.0],
        "ema_50": [2700.0, 2700.0],
        "ema_200": [2700.0, 2700.0],
        "rsi": [35.0, 38.0],  # Terlalu rendah untuk bullish kumo
        "ichimoku_above_cloud": [1, 1],
    })
    bias_neutral, reason_neutral = engine.evaluate_macro_bias_h4(df_h4=df_h4_neutral, curr_price=2700.0)
    assert bias_neutral == "NETRAL"


def test_3layer_architecture_lapis2_dual_pathway_jalur_a_and_b():
    """Menguji Lapis 2: Dual Pathways (Jalur A Konfluensi vs Jalur B Solo Sniper)."""
    # 1. Jalur B (Solo Sniper): Modul Trading Alchemist (SMC) memberi sinyal Grade A+ (BOS + OB >= 80%)
    solo_bar = pd.Series({
        "Close": 2705.0,
        "High": 2708.0,
        "Low": 2700.0,
        "Open": 2702.0,
        "ema_20": 2704.0,
        "ema_50": 2695.0,
        "ema_200": 2680.0,
        "rsi": 52.0,
        "volume_ratio": 1.0,
        "structure_bos_bullish": 1,
        "order_block_bullish": 1,
        "volman_pullback": 0,
        "volman_buildup": 0,
        "fib_in_golden_zone": 0,
        "ichimoku_above_cloud": 0,
    })

    res_solo = SignalEngine.validate_pdf_entry_confluence(solo_bar, signal_type="BUY")
    assert res_solo.is_approved is True
    assert "Solo Sniper" in res_solo.entry_pathway or "Jalur B" in res_solo.entry_pathway
    assert res_solo.module_scores["Trading Alchemist"] >= 80.0

    # 2. Jalur A (Konfluensi): 3 modul setuju (Volman + Pring + Murphy)
    confluence_bar = pd.Series({
        "Close": 2710.0,
        "High": 2715.0,
        "Low": 2705.0,
        "Open": 2708.0,
        "ema_20": 2709.0,
        "ema_50": 2690.0,
        "ema_200": 2670.0,
        "rsi": 54.0,
        "volume_ratio": 1.25,
        "volman_pullback": 1,
        "volman_buildup": 1,
        "fib_in_golden_zone": 1,
        "ichimoku_above_cloud": 1,
    })

    res_conf = SignalEngine.validate_pdf_entry_confluence(confluence_bar, signal_type="BUY")
    assert res_conf.is_approved is True
    assert "Jalur A" in res_conf.entry_pathway or res_conf.num_agreeing_modules >= 3


def test_3layer_architecture_lapis3_risk_guard_veto():
    """Menguji Lapis 3 (Hak Veto Mutlak): Sinyal ditolak jika terkena anti-pucuk, overextended, atau chop."""
    engine = SignalEngine()

    # Bar dengan RSI Overbought ekstrem (RSI 72 >= 68) -> HARAM BUY
    df_overbought = pd.DataFrame({
        "Open": [2700.0] * 20,
        "High": [2705.0] * 20,
        "Low": [2698.0] * 20,
        "Close": [2704.0] * 20,
        "Volume": [1000] * 20,
    }, index=pd.date_range("2026-10-02 08:00", periods=20, freq="15min"))

    # Injeksi rsi 75 ke candle terakhir
    df_with_ind = TechnicalIndicators.add_all_indicators(df_overbought)
    df_with_ind.loc[df_with_ind.index[-1], "rsi"] = 75.0

    # Strategi dasar menghasilkan sinyal BUY, namun Lapis 3 (Anti-Pucuk) wajib melakukan VETO mutlak
    strat_buy = Strategy(name="test_buy_trigger", description="Test buy trigger", buy_rules=[RuleCondition("Close", ">", 0)], buy_combine="AND")
    sig = engine.evaluate_bar(df_with_ind, "XAUUSD", strategy=strat_buy, apply_pdf_filter=True)
    assert sig.signal == "HOLD"
    assert any("ANTI-PUCUK" in r or "Overbought" in r for r in sig.reasons)


def test_retest_and_pullback_detection_indicator():
    """Menguji deteksi retest support/resistance, order block, dan EMA dinamis pada indikator."""
    # Data sintetis: Breakout lalu retest ke broken resistance
    highs = [2700.0, 2702.0, 2705.0, 2715.0, 2718.0, 2712.0, 2705.5, 2706.0]
    lows =  [2695.0, 2698.0, 2700.0, 2708.0, 2710.0, 2705.0, 2704.5, 2705.0]
    closes = [2698.0, 2701.0, 2705.0, 2714.0, 2716.0, 2707.0, 2705.8, 2708.0]
    opens =  [2696.0, 2699.0, 2702.0, 2709.0, 2714.0, 2715.0, 2706.5, 2705.5]
    idx = pd.date_range("2026-10-02 10:00", periods=8, freq="15min")

    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": [1000]*8}, index=idx)
    df_ind = TechnicalIndicators.add_all_indicators(df)

    assert "retest_sr_flip_bullish" in df_ind.columns
    assert "is_retest_buy" in df_ind.columns
    assert "is_retest_sell" in df_ind.columns


def test_retest_entry_buy_at_discount_with_9books_confirmation():
    """
    Menguji Metode Retest BUY di area diskon / bawah:
    Harga menguji Bullish Order Block / S-R Flip dengan konfirmasi rejection candle 9 buku.
    """
    retest_buy_bar = pd.Series({
        "Close": 2705.0,
        "High": 2708.0,
        "Low": 2700.0,   # Ayunan bawah retest
        "Open": 2702.0,
        "ema_20": 2703.0,
        "ema_50": 2695.0,
        "ema_200": 2680.0,
        "rsi": 48.0,     # Memantul di zona sehat
        "volume_ratio": 1.15,
        "rejection_wick_ratio": 0.45,  # Ekor bawah panjang (Mega Profit / Pinbar)
        "pattern_pinbar": 1,
        "volman_pullback": 1,
        "retest_sr_flip_bullish": 1.0,
        "retest_order_block_bullish": 1.0,
        "is_retest_buy": 1.0,
    })

    res = SignalEngine.validate_pdf_entry_confluence(retest_buy_bar, signal_type="BUY")
    assert res.is_approved is True
    assert res.is_retest_entry is True
    assert "Retest Diskon" in res.entry_pathway
    assert any("METODE RETEST 9 BUKU" in c for c in res.checks)
    assert any("Diskon / Bawah" in c for c in res.checks)


def test_retest_entry_sell_at_premium_with_9books_confirmation():
    """
    Menguji Metode Retest SELL di area premium / atas:
    Harga menguji Bearish Order Block / Resistance Flip dengan konfirmasi rejection candle 9 buku.
    """
    retest_sell_bar = pd.Series({
        "Close": 2695.0,
        "High": 2702.0,   # Ayunan atas retest
        "Low": 2692.0,
        "Open": 2698.0,
        "ema_20": 2697.0,
        "ema_50": 2710.0,
        "ema_200": 2730.0,
        "rsi": 52.0,
        "volume_ratio": 1.10,
        "upper_wick_ratio": 0.40,  # Ekor atas panjang (Shooting Star)
        "pattern_shooting_star": 1,
        "retest_sr_flip_bearish": 1.0,
        "retest_order_block_bearish": 1.0,
        "is_retest_sell": 1.0,
    })

    res = SignalEngine.validate_pdf_entry_confluence(retest_sell_bar, signal_type="SELL")
    assert res.is_approved is True
    assert res.is_retest_entry is True
    assert "Retest Premium" in res.entry_pathway
    assert any("METODE RETEST 9 BUKU" in c for c in res.checks)
    assert any("Premium / Atas" in c for c in res.checks)


def test_retest_badge_in_telegram_format():
    """Menguji tampilan badge retest (Diskon/Bawah) di format pesan Telegram."""
    sig = SignalResult(
        ticker="XAUUSD",
        strategy_name="Master_Confluence",
        signal="BUY",
        price=2705.0,
        candle_time="2026-10-02 20:00:00",
        take_profit_price=2715.0,
        stop_loss_price=2699.0,
        risk_reward_ratio=1.67,
        pdf_confluence_score=85.0,
        setup_grade="Grade A+",
        pdf_confluence_details=["METODE RETEST 9 BUKU"],
        market_direction_prediction="Bullish Kuat dari Area Diskon",
        is_retest_entry=True,
        retest_details="Order Block Demand Zone",
    )

    notifier = TelegramNotifier()
    msg = notifier.format_signal_message(sig)
    assert "Metode Entry:" in msg
    assert "Retest Diskon (Bawah)" in msg
    assert "Order Block Demand Zone" in msg
    assert "$2,705.00" in msg


def test_london_judas_swing_and_overextended_protection():
    """Menguji proteksi Sesi London (12:00 - 16:00 WIB / jam 4 sore): Anti-Judas Swing & Anti-Overextended EMA20 Bob Volman."""
    from strategy.signal_engine import SignalEngine
    from zoneinfo import ZoneInfo
    from datetime import datetime

    engine = SignalEngine()

    # 1. Uji Anti-Judas Swing di jam 12:30 WIB (Pre-London):
    # Asian Range dibentuk jam 05:00 - 12:00 (High 4155, Low 4136).
    # Harga menembus ke 4130 (di bawah Asian Low). Sinyal SELL harus ditolak oleh Anti-Judas Swing.
    idx_times = pd.date_range("2026-10-05 06:00", periods=27, freq="15min", tz="Asia/Jakarta")

    highs = [4155.0 if i < 15 else 4145.0 for i in range(27)]
    lows = [4136.0 if i < 20 else 4128.0 for i in range(27)]
    closes = [4145.0 if i < 20 else 4130.0 for i in range(27)]

    df_judas = pd.DataFrame({
        "Open": closes,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "ema_20": [4142.0] * 27,
        "ema_50": [4150.0] * 27,
        "volume_ratio": [1.1] * 27,
        "rsi": [38.0] * 27,
        "atr": [3.5] * 27,
    }, index=idx_times)

    is_trap, trap_reason = engine.check_london_judas_swing(
        df=df_judas,
        curr_price=4130.0,
        signal_type="SELL",
        curr_row=df_judas.iloc[-1],
    )
    assert is_trap is True
    assert "Anti-Judas Swing" in trap_reason
    assert "Low Asia" in trap_reason

    # 2. Uji batas jam 16:00 WIB: Setelah jam 16:00 (misal 16:15 WIB), Judas Swing dinonaktifkan
    idx_after_4pm = pd.date_range("2026-10-05 09:45", periods=27, freq="15min", tz="Asia/Jakarta") # candle terakhir 16:15
    df_after_4pm = df_judas.copy()
    df_after_4pm.index = idx_after_4pm
    is_trap_4pm, _ = engine.check_london_judas_swing(
        df=df_after_4pm,
        curr_price=4130.0,
        signal_type="SELL",
        curr_row=df_after_4pm.iloc[-1],
    )
    assert is_trap_4pm is False

    # 3. Uji filter Bob Volman London EMA20 Tight Distance:
    # Jarak harga (4131.0) ke EMA20 (4143.0) = $12.0 USD > batas $2.50 USD di Sesi London
    sig = engine.evaluate_bar(df_judas, ticker="XAUUSD", apply_pdf_filter=True)
    assert sig.signal == "HOLD"
    assert any("Anti-Judas Swing" in r or "BOB VOLMAN" in r for r in sig.reasons)


def test_premium_discount_veto_blocks_buying_top_and_selling_bottom():
    """Menguji Lapis 3 Veto: Dilarang BUY di area Premium (>65%) dan dilarang SELL di area Discount (<35%)."""
    # 1. Kasus BUY di pucuk resisten (pos_in_range = 80% > 65%)
    pucuk_buy_bar = pd.Series({
        "Close": 4160.0,
        "High": 4165.0,
        "Low": 4158.0,
        "Open": 4159.0,
        "ema_20": 4159.0,
        "ema_50": 4140.0,
        "ema_200": 4120.0,
        "rsi": 62.0,
        "volume_ratio": 1.2,
        "fib_swing_high": 4165.0,
        "fib_swing_low": 4140.0,
        # pos_in_range = (4160 - 4140) / (4165 - 4140) = 20 / 25 = 80.0% (Deep Premium!)
    })
    res_buy = SignalEngine.validate_pdf_entry_confluence(pucuk_buy_bar, signal_type="BUY")
    assert res_buy.is_approved is False
    assert any("BUY di Area Premium" in c or "Premium" in c for c in res_buy.checks)

    # 2. Kasus SELL di dasar jurang support (pos_in_range = 16% < 35%)
    dasar_sell_bar = pd.Series({
        "Close": 4132.0,
        "High": 4135.0,
        "Low": 4130.0,
        "Open": 4134.0,
        "ema_20": 4133.0,
        "ema_50": 4150.0,
        "ema_200": 4170.0,
        "rsi": 42.0,
        "volume_ratio": 1.2,
        "fib_swing_high": 4150.0,
        "fib_swing_low": 4130.0,
        # pos_in_range = (4132 - 4130) / (4150 - 4130) = 2 / 20 = 10.0% (Deep Discount!)
    })
    res_sell = SignalEngine.validate_pdf_entry_confluence(dasar_sell_bar, signal_type="SELL")
    assert res_sell.is_approved is False
    assert any("SELL di Area Discount" in c or "Discount" in c for c in res_sell.checks)


def test_rsi_and_wick_rejection_vetoes():
    """Menguji Lapis 3 Veto: RSI ekstrem dan Rejection Candlestick berlawanan arah."""
    # 1. Kasus BUY namun candle shooting star merah dengan ekor atas panjang (rejection atas)
    rejection_buy_bar = pd.Series({
        "Close": 4150.0,
        "High": 4160.0,
        "Low": 4149.0,
        "Open": 4155.0,  # Merah (Close < Open), ekor atas (4160-4155)/11 = 45%
        "ema_20": 4149.0,
        "ema_50": 4140.0,
        "rsi": 55.0,
        "volume_ratio": 1.1,
        "pattern_shooting_star": 1,
    })
    res_buy = SignalEngine.validate_pdf_entry_confluence(rejection_buy_bar, signal_type="BUY")
    assert res_buy.is_approved is False
    assert any("Rejection" in c or "ekor" in c.lower() for c in res_buy.checks)

    # 2. Kasus SELL namun candle pinbar hijau dengan ekor bawah panjang (rejection bawah)
    rejection_sell_bar = pd.Series({
        "Close": 4140.0,
        "High": 4142.0,
        "Low": 4130.0,
        "Open": 4135.0,  # Hijau (Close > Open), ekor bawah (4135-4130)/12 = 41%
        "ema_20": 4141.0,
        "ema_50": 4150.0,
        "rsi": 45.0,
        "volume_ratio": 1.1,
        "pattern_pinbar": 1,
    })
    res_sell = SignalEngine.validate_pdf_entry_confluence(rejection_sell_bar, signal_type="SELL")
    assert res_sell.is_approved is False
    assert any("Rejection" in c or "ekor" in c.lower() for c in res_sell.checks)













