import pytest
from pathlib import Path
from pypdf import PdfWriter
from data.fetcher import DataFetcher
from strategy.pdf_learner import PDFTradingLearner, learn_from_pdf
from notify.telegram_bot import format_currency


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
    # Buat PDF dummy untuk pengujian
    pdf_file = tmp_path / "test_trading_guide.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)

    # Tambahkan metadata teks jika memungkinkan atau tulis file valid
    with open(pdf_file, "wb") as f:
        writer.write(f)

    learner = PDFTradingLearner(str(pdf_file))
    assert learner.num_pages == 1

    # Uji ekstraksi konsep dari teks simulasi materi trading
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
    print("\n✓ Ekstraksi konsep strategi PDF berhasil diverifikasi!")
