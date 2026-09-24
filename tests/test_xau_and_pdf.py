import pytest
from pathlib import Path
from pypdf import PdfWriter
import pandas as pd
import numpy as np

from data.fetcher import DataFetcher
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
    """Menguji filter ketat konfluensi 7 buku PDF (hanya meloloskan Grade A/A+ untuk win rate tinggi)."""
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
    }, index=pd.date_range("2026-09-23 10:00", periods=20, freq="15min"))

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
    assert sig.risk_reward_ratio >= 1.8
    assert sig.take_profit_price > sig.price
    assert sig.stop_loss_price < sig.price


def test_telegram_signal_formatter_shows_7_pdf_details():
    """Memastikan format notifikasi telegram menampilkan telaah 7 buku PDF dan win rate badge."""
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
    assert "TELAAH 7 BUKU PDF" in msg
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



