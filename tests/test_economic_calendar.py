import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import pytest

from data.storage import StockStorage
from data.economic_calendar import EconomicCalendar
from strategy.news_predictor import NewsPredictor
from notify.telegram_bot import TelegramNotifier
from notify.chat_agent import ChatAgent


def test_categorize_news_type():
    assert EconomicCalendar.categorize_news_type("FOMC Statement", "USD") == "FOMC"
    assert EconomicCalendar.categorize_news_type("Federal Funds Rate Decision", "USD") == "FOMC"
    assert EconomicCalendar.categorize_news_type("Core CPI m/m", "USD") == "CPI"
    assert EconomicCalendar.categorize_news_type("Consumer Price Index y/y", "USD") == "CPI"
    assert EconomicCalendar.categorize_news_type("Non-Farm Employment Change", "USD") == "NFP"
    assert EconomicCalendar.categorize_news_type("Unemployment Rate", "USD") == "NFP"
    assert EconomicCalendar.categorize_news_type("Trade Balance", "USD") == "OTHER"
    assert EconomicCalendar.categorize_news_type("CPI", "EUR") == "OTHER"


def test_economic_calendar_storage_and_schedule():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_calendar.db"
        storage = StockStorage(db_path=db_path)
        calendar = EconomicCalendar(storage=storage)

        # 1. Test official schedule generation
        events = calendar.generate_official_schedule_events(2026)
        assert len(events) >= 30
        assert any(e["news_type"] == "FOMC" for e in events)
        assert any(e["news_type"] == "CPI" for e in events)
        assert any(e["news_type"] == "NFP" for e in events)

        # 2. Save events to storage
        saved = storage.save_economic_events(events)
        assert saved >= 30

        # 3. Test upcoming news within 15 minutes
        # Insert a mock event 10 minutes in the future
        now_utc = datetime.now(timezone.utc)
        ev_time = now_utc + timedelta(minutes=10)
        time_str = ev_time.strftime("%Y-%m-%d %H:%M:%S")

        mock_event = [{
            "title": "Core CPI m/m (Inflasi AS)",
            "country": "USD",
            "date_utc": time_str,
            "date_wib": (ev_time + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S"),
            "impact": "High",
            "forecast": "0.3%",
            "previous": "0.2%",
            "news_type": "CPI",
        }]
        storage.save_economic_events(mock_event)

        upcoming = storage.get_upcoming_news(within_minutes=15)
        assert len(upcoming) >= 1
        found_ev = [e for e in upcoming if e["news_type"] == "CPI"][0]
        assert found_ev["news_type"] == "CPI"
        assert found_ev["alert_sent"] == 0

        # 4. Mark alert sent
        storage.mark_news_alert_sent(found_ev["id"])
        upcoming_after = storage.get_upcoming_news(within_minutes=15)
        assert not any(e["id"] == found_ev["id"] for e in upcoming_after)


def test_news_predictor_calculations():
    mock_event = {
        "title": "FOMC Statement & Fed Funds Rate",
        "news_type": "FOMC",
        "date_wib": "2026-09-24 01:00:00 WIB",
        "forecast": "4.50%",
        "previous": "4.75%",
    }
    analysis = NewsPredictor.analyze_pre_news(mock_event, live_gold_price=4300.0)
    assert analysis["news_type"] == "FOMC"
    assert analysis["current_price"] == 4300.0

    # Bullish scenario TP > current price
    bull = analysis["bullish_scenario"]
    assert bull["target_tp1"] > 4300.0
    assert bull["target_tp2"] > bull["target_tp1"]

    # Bearish scenario TP < current price
    bear = analysis["bearish_scenario"]
    assert bear["target_tp1"] < 4300.0
    assert bear["target_tp2"] < bear["target_tp1"]

    # Straddle plan
    plan = analysis["straddle_plan"]
    assert plan["buy_stop"] > 4300.0
    assert plan["sell_stop"] < 4300.0
    assert plan["buy_sl"] < plan["buy_stop"]
    assert plan["sell_sl"] > plan["sell_stop"]


def test_telegram_news_alert_formatter():
    mock_event = {
        "title": "Non-Farm Employment Change & Unemployment Rate",
        "news_type": "NFP",
        "date_wib": "2026-10-02 19:30:00 WIB",
        "forecast": "160K",
        "previous": "142K",
    }
    analysis = NewsPredictor.analyze_pre_news(mock_event, live_gold_price=4300.0)
    notifier = TelegramNotifier()
    msg = notifier.format_news_alert_message(analysis)

    assert "ALERT 10 MENIT SEBELUM HIGH-IMPACT NEWS" in msg
    assert "NFP" in msg
    assert "SKENARIO PUMP" in msg
    assert "SKENARIO DUMP" in msg
    assert "STRADDLE BREAKOUT" in msg
    assert "$4,300.00" in msg


def test_chat_agent_news_intent():
    assert ChatAgent.classify_intent("bor ada news apa hari ini")["intent"] == "NEWS"
    assert ChatAgent.classify_intent("jadwal cpi kapan bor")["intent"] == "NEWS"
    assert ChatAgent.classify_intent("prediksi nfp dong bor")["intent"] == "NEWS"
    assert ChatAgent.classify_intent("fomc jam berapa bor")["intent"] == "NEWS"
    assert ChatAgent.classify_intent("berita ekonomi emas apa aja")["intent"] == "NEWS"
