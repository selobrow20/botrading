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
    assert ChatAgent.extract_ticker("saham adro bagus ga") == "ADRO.JK"
    assert ChatAgent.extract_ticker("saham cuan hari ini") == "CUAN.JK"


def test_stopwords_not_extracted_as_ticker():
    # Words like 'yang', 'bisa', 'pada', 'dong', 'sama' shouldn't be treated as tickers
    assert ChatAgent.extract_ticker("yang mana yang bisa naik dong") is None
    assert ChatAgent.extract_ticker("kalo hari ini bisa cuan sama kita") is None
    assert ChatAgent.extract_ticker("kapan waktu santai buat kita") is None


def test_classify_intent_existing():
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


def test_classify_intent_candlestick():
    res_c1 = ChatAgent.classify_intent("bor cek pola candle xauusd dong")
    assert res_c1["intent"] == "CANDLE"
    assert res_c1["ticker"] == "XAUUSD"

    res_c2 = ChatAgent.classify_intent("ada pola pinbar atau engulfing di bbri ga")
    assert res_c2["intent"] == "CANDLE"
    assert res_c2["ticker"] == "BBRI.JK"

    res_c3 = ChatAgent.classify_intent("candle bbca gimana bor")
    assert res_c3["intent"] == "CANDLE"
    assert res_c3["ticker"] == "BBCA.JK"


def test_classify_intent_mt5_and_scan():
    res_mt5_1 = ChatAgent.classify_intent("gimana posisi akun mt5 sekarang bor")
    assert res_mt5_1["intent"] == "MT5"

    res_mt5_2 = ChatAgent.classify_intent("autotrade mt5 aktif ga")
    assert res_mt5_2["intent"] == "MT5"

    res_mt5_3 = ChatAgent.classify_intent("saldo mt5 berapa sekarang")
    assert res_mt5_3["intent"] == "MT5"

    res_scan = ChatAgent.classify_intent("scan semua saham dong bor")
    assert res_scan["intent"] == "SCAN"


def test_classify_intent_analysis_and_history():
    res_a1 = ChatAgent.classify_intent("gimana analisa bbca sekarang")
    assert res_a1["intent"] == "ANALYSIS"
    assert res_a1["ticker"] == "BBCA.JK"

    res_a2 = ChatAgent.classify_intent("prospek saham bmri hari ini")
    assert res_a2["intent"] == "ANALYSIS"
    assert res_a2["ticker"] == "BMRI.JK"

    res_hist = ChatAgent.classify_intent("rekap riwayat trading sinyal kemarin")
    assert res_hist["intent"] == "HISTORY"

    res_tutup = ChatAgent.classify_intent("laporan tutup saham hari ini")
    assert res_tutup["intent"] == "TUTUP"


def test_classify_intent_copier_license_menu():
    res_copier = ChatAgent.classify_intent("gimana cara pasang copier mt5 bor")
    assert res_copier["intent"] == "COPIER"

    res_lic = ChatAgent.classify_intent("cek sisa lisensi masa aktif saya")
    assert res_lic["intent"] == "LICENSE"

    res_menu = ChatAgent.classify_intent("kamu bisa bantu apa aja bor? ada fitur apa?")
    assert res_menu["intent"] == "MENU"


def test_classify_intent_education():
    res_edu1 = ChatAgent.classify_intent("apa itu 9 buku pdf yang dipake bot")
    assert res_edu1["intent"] == "EDUCATION"
    assert res_edu1["subtopic"] == "9_pdf"

    res_edu2 = ChatAgent.classify_intent("jelasin fibonacci golden pocket dong")
    assert res_edu2["intent"] == "EDUCATION"
    assert res_edu2["subtopic"] == "fibo"

    res_edu3 = ChatAgent.classify_intent("apa itu bob volman pullback dan buildup")
    assert res_edu3["intent"] == "EDUCATION"
    assert res_edu3["subtopic"] == "volman"

    res_edu4 = ChatAgent.classify_intent("awan ichimoku kumo cara bacanya gimana")
    assert res_edu4["intent"] == "EDUCATION"
    assert res_edu4["subtopic"] == "ichimoku"

    res_edu5 = ChatAgent.classify_intent("jelasin konsep smart money order block dan fair value gap")
    assert res_edu5["intent"] == "EDUCATION"
    assert res_edu5["subtopic"] == "smc"

    res_edu6 = ChatAgent.classify_intent("apa bedanya setup grade a+ sama grade b")
    assert res_edu6["intent"] == "EDUCATION"
    assert res_edu6["subtopic"] == "grade"

    res_edu7 = ChatAgent.classify_intent("kenapa kita harus selalu pasang stop loss dan atur rrr")
    assert res_edu7["intent"] == "EDUCATION"
    assert res_edu7["subtopic"] == "risk_management"


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


def test_generate_ticker_analysis_response():
    resp = ChatAgent.generate_ticker_analysis_response(
        ticker="BBCA.JK",
        price=10250.0,
        signal="BUY",
        change_pct=1.45,
        setup_grade="A+",
        pdf_confluence_score=0.80,
        indicators={"rsi": 56.4, "ema_20": 10100.0, "ema_50": 9950.0, "volume_ratio": 1.45},
        tp_price=10500.0,
        sl_price=10100.0,
        rrr=1.67,
        prediction="Bullish Momentum di atas EMA 20",
        reasons=["RSI Oversold Rebound", "Bob Volman Buildup"],
        user_name="Bro",
    )
    assert "BBCA" in resp
    assert "Rp 10,250" in resp
    assert "+1.45%" in resp
    assert "BUY" in resp
    assert "Grade A+" in resp
    assert "80% Konfluensi" in resp
    assert "RSI (14):" in resp
    assert "Target TP:" in resp
    assert "Batas SL:" in resp
    assert "1 : 1.67" in resp


def test_generate_education_response():
    resp_pdf = ChatAgent.generate_education_response("9_pdf", user_name="Budi")
    assert "Budi" in resp_pdf
    assert "Bob Volman" in resp_pdf
    assert "Smart Money Concepts" in resp_pdf

    resp_fibo = ChatAgent.generate_education_response("fibo")
    assert "61.8%" in resp_fibo
    assert "Golden Pocket" in resp_fibo

    resp_mm = ChatAgent.generate_education_response("risk_management")
    assert "Stop Loss" in resp_mm
    assert "1-2%" in resp_mm


def test_generate_copier_and_menu_response():
    resp_copier = ChatAgent.generate_copier_guide_response(user_name="Andi", is_admin=True)
    assert "Andi" in resp_copier
    assert "TelegramSignalReceiver.mq5" in resp_copier
    assert "/sendcopier" in resp_copier

    resp_menu = ChatAgent.generate_menu_response(user_name="Andi")
    assert "Andi" in resp_menu
    assert "Live Chart" in resp_menu
    assert "Analisa Kilat" in resp_menu
    assert "Auto-Trade MT5" in resp_menu


def test_generate_chat_response():
    resp_greet = ChatAgent.generate_chat_response("GREETING", user_name="Nabil")
    assert "Nabil" in resp_greet
    assert "Lagi mantau market apa nih" in resp_greet

    resp_thanks = ChatAgent.generate_chat_response("THANKS", user_name="Nabil")
    assert "Sama-sama bor" in resp_thanks

    resp_status = ChatAgent.generate_chat_response("STATUS")
    assert "Aman terkendali" in resp_status

    resp_loss = ChatAgent.generate_chat_response("CURHAT_LOSS")
    assert "Kena SL itu bukan tanda lu gagal" in resp_loss

    resp_profit = ChatAgent.generate_chat_response("CURHAT_PROFIT")
    assert "Alhamdulillah" in resp_profit

    resp_id = ChatAgent.generate_chat_response("IDENTITY")
    assert "Selobrow AI Trader" in resp_id


def test_classify_intent_human_conversation():
    # 1. Stance: "lu buy or sell" (seperti yang ditanyakan user pada screenshot)
    res1 = ChatAgent.classify_intent("lu buy or sell")
    assert res1["intent"] == "STANCE"
    assert res1["ticker"] == "XAUUSD"

    res2 = ChatAgent.classify_intent("buy or sell")
    assert res2["intent"] == "STANCE"

    res3 = ChatAgent.classify_intent("buy apa sell bor sekarang")
    assert res3["intent"] == "STANCE"

    res4 = ChatAgent.classify_intent("posisi lu apa sekarang")
    assert res4["intent"] == "STANCE"

    res5 = ChatAgent.classify_intent("lu buy or sell di bbca")
    assert res5["intent"] == "STANCE"
    assert res5["ticker"] == "BBCA.JK"

    # 2. Timing entry
    res_entry = ChatAgent.classify_intent("bisa masuk sekarang ga bor")
    assert res_entry["intent"] == "ENTRY_ADVICE"

    res_entry2 = ChatAgent.classify_intent("telat ga kalau buy sekarang")
    assert res_entry2["intent"] == "ENTRY_ADVICE"

    # 3. Price check
    res_price = ChatAgent.classify_intent("harga emas sekarang berapa")
    assert res_price["intent"] == "PRICE_CHECK"

    # 4. Curhat & Identity
    assert ChatAgent.classify_intent("aduh kena sl nih bor")["intent"] == "CURHAT_LOSS"
    assert ChatAgent.classify_intent("alhamdulillah cuan gede gue bor")["intent"] == "CURHAT_PROFIT"
    assert ChatAgent.classify_intent("lu siapa sih bor?")["intent"] == "IDENTITY"


def test_generate_stance_and_entry_advice_response():
    resp_buy = ChatAgent.generate_stance_response(
        ticker="XAUUSD",
        price=4306.50,
        signal="BUY",
        setup_grade="A",
        pdf_confluence_score=0.85,
        indicators={"rsi": 56.4, "ema_20": 4295.0},
        tp_price=4331.0,
        sl_price=4290.0,
        prediction="Bullish continuation",
        reasons=["Pantulan EMA 20 & NFP momentum"],
        user_name="Bro",
    )
    assert "BUY" in resp_buy
    assert "$4,306.50" in resp_buy
    assert "Target TP" in resp_buy
    assert "Batas Stop Loss" in resp_buy
    assert "Bullish continuation" in resp_buy

    resp_advice = ChatAgent.generate_entry_advice_response(
        ticker="XAUUSD",
        price=4306.50,
        signal="BUY",
        indicators={"rsi": 56.4, "ema_20": 4305.0},
        tp_price=4331.0,
        sl_price=4290.0,
    )
    assert "aman dan layak masuk" in resp_advice
    assert "Stop Loss" in resp_advice


def test_classify_intent_news_stance_and_update():
    # 1. News Stance: Nfp sell
    res_nfp_sell = ChatAgent.classify_intent("Nfp sell")
    assert res_nfp_sell["intent"] == "NEWS_STANCE"
    assert res_nfp_sell["news_type"] == "NFP"
    assert res_nfp_sell["user_stance"] == "SELL"

    # 2. News Stance: nfp buy
    res_nfp_buy = ChatAgent.classify_intent("nfp buy")
    assert res_nfp_buy["intent"] == "NEWS_STANCE"
    assert res_nfp_buy["news_type"] == "NFP"
    assert res_nfp_buy["user_stance"] == "BUY"

    # 3. News Stance: nfp buy apa sell
    res_nfp_dir = ChatAgent.classify_intent("nfp buy apa sell bor")
    assert res_nfp_dir["intent"] == "NEWS_STANCE"
    assert res_nfp_dir["news_type"] == "NFP"

    # 4. News Stance: fomc sell
    res_fomc_sell = ChatAgent.classify_intent("fomc sell")
    assert res_fomc_sell["intent"] == "NEWS_STANCE"
    assert res_fomc_sell["news_type"] == "FOMC"
    assert res_fomc_sell["user_stance"] == "SELL"

    # 5. Update Intent
    assert ChatAgent.classify_intent("update bot")["intent"] == "UPDATE"
    assert ChatAgent.classify_intent("git pull dong")["intent"] == "UPDATE"
    assert ChatAgent.classify_intent("tarik update sekarang")["intent"] == "UPDATE"


def test_generate_news_stance_response():
    # Case: User says SELL, system says STRONG BUY
    resp_contrary = ChatAgent.generate_news_stance_response(
        news_type="NFP",
        user_stance="SELL",
        prediction="STRONG BUY",
        confidence=86,
        live_price=4188.40,
        entry=4188.40,
        tp1=4221.91,
        sl=4175.84,
        user_name="Bro",
    )
    assert "Jangan buru-buru SELL" in resp_contrary
    assert "STRONG BUY (86% Confidence)" in resp_contrary
    assert "$4,188.40" in resp_contrary
    assert "$4,221.91" in resp_contrary

    # Case: User says BUY, system says BUY
    resp_aligned = ChatAgent.generate_news_stance_response(
        news_type="NFP",
        user_stance="BUY",
        prediction="STRONG BUY",
        confidence=86,
        live_price=4188.40,
        entry=4188.40,
        tp1=4221.91,
        sl=4175.84,
        user_name="Bro",
    )
    assert "Klop banget" in resp_aligned
    assert "STRONG BUY" in resp_aligned
