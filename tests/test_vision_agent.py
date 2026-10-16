"""
Unit Test untuk VisionAgent: OCR, Klasifikasi Konten Gambar, Analisis Berita IHK/CPI & Chart.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from notify.vision_agent import VisionAgent


def test_classify_image_content_calendar():
    # Test OCR mendeteksi IHK/CPI
    ocr_text = "19:30 US IHK Inti (MoM) 0.2% 0.3%\nIHK (MoM) 0.6% 0.4%"
    caption = "tpi datanya gini bor ? yakin lau?"
    cls = VisionAgent.classify_image_content(ocr_text, caption)
    assert cls == "CALENDAR_NEWS"


def test_classify_image_content_chart():
    ocr_text = "XAUUSD M15 TradingView 4180.50 EMA 50"
    caption = "analisa chart ini dong bor"
    cls = VisionAgent.classify_image_content(ocr_text, caption)
    assert cls == "CHART"


def test_classify_image_content_mt5():
    ocr_text = "Balance: 10000.00 Equity: 10250.00 Buy Limit 0.10"
    caption = "posisi akun gue aman ga"
    cls = VisionAgent.classify_image_content(ocr_text, caption)
    assert cls == "MT5_ORDER"


def test_analyze_cpi_news_explanation():
    ocr_text = "19:30 US IHK Inti (MoM) 0.2% 0.3%\nIHK (MoM) 0.6% 0.4%"
    caption = "tpi datanya gini bor ? yakin lau?"
    reply = VisionAgent.analyze_news_calendar(ocr_text, caption, user_name="Budi")
    assert "IHK = CPI" in reply
    assert "IHK Inti (MoM)" in reply
    assert "0.2%" in reply
    assert "0.6%" in reply
    assert "Waspada SPIKE 2 ARAH" in reply
    assert "Budi" in reply


def test_vision_agent_general():
    ocr_text = "Kopi Kenangan Mantap"
    caption = "lagi santai ngopi bor"
    reply = VisionAgent.analyze_general_image(ocr_text, caption, user_name="Budi")
    assert "GAMBAR DITERIMA" in reply
    assert "Kopi Kenangan Mantap" in reply
