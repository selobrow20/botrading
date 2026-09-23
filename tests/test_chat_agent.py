import pytest
from notify.chat_agent import ChatAgent


def test_extract_ticker_gold():
    assert ChatAgent.extract_ticker("bor minta chart xau/usd live ya") == "XAUUSD"
    assert ChatAgent.extract_ticker("tampilin chart gold dong") == "XAUUSD"
    assert ChatAgent.extract_ticker("gimana candle emas hari ini") == "XAUUSD"
    assert ChatAgent.extract_ticker("xauusd mau naik apa turun") == "XAUUSD"
    assert ChatAgent.extract_ticker("analisa xau bor") == "XAUUSD"


def test_extract_ticker_idx_stocks():
    assert ChatAgent.extract_ticker("chart bbca dong bor") == "BBCA.JK"
    assert ChatAgent.extract_ticker("tampilin live chart bbri.jk") == "BBRI.JK"
    assert ChatAgent.extract_ticker("gimana chart tlkm sekarang") == "TLKM.JK"
    assert ChatAgent.extract_ticker("bmri prospeknya gimana") == "BMRI.JK"


def test_stopwords_not_extracted_as_ticker():
    # Words like 'yang', 'bisa', 'pada', 'dong', 'sama' shouldn't be treated as tickers
    assert ChatAgent.extract_ticker("yang mana yang bisa naik dong") is None
    assert ChatAgent.extract_ticker("kalo hari ini bisa cuan sama kita") is None


def test_classify_intent():
    # 1. Chart intent with explicit ticker
    res_chart = ChatAgent.classify_intent("bor, minta chart xau/usd lgsung tampilin yg live ya")
    assert res_chart["intent"] == "CHART"
    assert res_chart["ticker"] == "XAUUSD"
    assert res_chart["is_gold"] is True

    # 2. Chart intent for stock
    res_stock = ChatAgent.classify_intent("chart bbca dong bor")
    assert res_stock["intent"] == "CHART"
    assert res_stock["ticker"] == "BBCA.JK"

    # 3. Chart intent without ticker defaults to XAUUSD
    res_default = ChatAgent.classify_intent("bor minta chart live dong")
    assert res_default["intent"] == "CHART"
    assert res_default["ticker"] == "XAUUSD"

    # 4. Potensi / radar intent
    res_pot = ChatAgent.classify_intent("ada saham yang berpotensi ga bor hari ini")
    assert res_pot["intent"] == "POTENSI"

    # 5. Gold intent (not requesting chart)
    res_gold = ChatAgent.classify_intent("emas gimana bor arahnya mau naik apa turun")
    assert res_gold["intent"] == "GOLD"

    # 6. Winrate intent
    res_wr = ChatAgent.classify_intent("winrate lu berapa sekarang bor")
    assert res_wr["intent"] == "WINRATE"

    # 7. Greeting intent
    res_greet = ChatAgent.classify_intent("halo bor lagi ngapain lu")
    assert res_greet["intent"] == "GREETING"

    # 8. Thanks intent
    res_thanks = ChatAgent.classify_intent("makasih banyak bor keren lu")
    assert res_thanks["intent"] == "THANKS"


def test_generate_chart_caption():
    caption = ChatAgent.generate_chart_caption(
        ticker="XAUUSD",
        price=4306.0,
        tp_price=4331.8,
        sl_price=4290.9,
        setup_grade="A+",
        pdf_confluence_score=0.85,
        prediction="Bullish continuation",
    )
    assert "XAU/USD" in caption
    assert "pesenan lu udah siap" in caption
    assert "$4,306.00" in caption
    assert "Target TP" in caption
    assert "Batas SL" in caption
    assert "Grade A+" in caption


def test_generate_chat_response():
    resp_greet = ChatAgent.generate_chat_response("GREETING", user_name="Nabil")
    assert "Nabil" in resp_greet
    assert "standby" in resp_greet

    resp_thanks = ChatAgent.generate_chat_response("THANKS")
    assert "Sama-sama bor" in resp_thanks

    resp_status = ChatAgent.generate_chat_response("STATUS")
    assert "Aman terkendali" in resp_status
