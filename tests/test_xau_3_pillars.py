import pytest
import pandas as pd
from strategy.signal_engine import SignalEngine


def test_xau_3_pillars_all_satisfied_buy():
    """Menguji kondisi ideal di mana seluruh 3 Pilar Inti terpenuhi 100% menghasilkan BUY Grade A+."""
    engine = SignalEngine()

    idx = pd.date_range("2026-10-13 14:00", periods=15, freq="15min")
    # Lilin sehat di atas EMA 20, ekor atas pendek (< 38%), volume buyer tinggi
    opens = [4180.0 + i * 0.5 for i in range(15)]
    closes = [4181.5 + i * 0.5 for i in range(15)]
    highs = [c + 0.3 for c in closes]  # Ekor atas sangat pendek
    lows = [o - 0.5 for o in opens]
    volumes = [1000.0] * 14 + [1200.0]  # Volume candle terakhir 1.2x

    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
        "ema_20": [4180.0] * 15,
        "atr": [3.5] * 15,
    }, index=idx)

    res = engine.evaluate_bar(df, ticker="XAUUSD", apply_pdf_filter=True)
    assert res.signal in ["BUY", "BUY_LIMIT"]
    assert res.setup_grade == "Grade A+"
    assert res.pdf_confluence_score == 100.0
    assert "3_Pilar_Inti_Zero_Bentrok" in res.strategy_name
    assert res.take_profit_price >= res.price + 6.00  # Minimal 60 pips
    assert res.stop_loss_price <= res.price - 6.00    # Minimal 60 pips
    assert any("Bob Volman" in r for r in res.reasons)
    assert any("Mega Profit" in r for r in res.reasons)
    assert any("John Murphy" in r for r in res.reasons)


def test_xau_3_pillars_veto_trend_bob_volman():
    """Menguji Veto Pilar 1 (Bob Volman): Harga ambles di bawah EMA 20 -> HOLD."""
    engine = SignalEngine()

    idx = pd.date_range("2026-10-13 14:00", periods=20, freq="15min")
    # Awalnya harga di 4195, lalu candle terakhir jatuh ke 4170 (ambles di bawah EMA 20 ~ 4185)
    opens = [4195.0] * 15 + [4175.0] * 5
    closes = [4195.0] * 15 + [4170.0] * 5
    highs = [4196.0] * 15 + [4176.0] * 5
    lows = [4194.0] * 15 + [4168.0] * 5
    volumes = [1000.0] * 20

    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
        "rsi": [50.0] * 20,
    }, index=idx)

    res = engine.evaluate_bar(df, ticker="XAUUSD", apply_pdf_filter=True)
    assert res.signal == "HOLD"
    assert any("BOB VOLMAN" in r and "ANTI NYUNGSEP" in r for r in res.reasons)


def test_xau_3_pillars_veto_wick_mega_profit():
    """Menguji Veto Pilar 2 (Mega Profit): Ekor atas panjang jarum suntik (> 38%) -> HOLD."""
    engine = SignalEngine()

    idx = pd.date_range("2026-10-13 14:00", periods=15, freq="15min")
    opens = [4185.0] * 14 + [4185.0]
    closes = [4186.0] * 14 + [4186.0]
    # Candle terakhir: High 4195 (ekor atas 9 / 11 = 81% > 38%)
    highs = [4187.0] * 14 + [4195.0]
    lows = [4184.0] * 14 + [4184.0]
    volumes = [1000.0] * 15

    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
        "ema_20": [4180.0] * 15,
    }, index=idx)

    res = engine.evaluate_bar(df, ticker="XAUUSD", apply_pdf_filter=True)
    assert res.signal == "HOLD"
    assert any("MEGA PROFIT" in r and "ANTI JARUM SUNTIK" in r for r in res.reasons)


def test_xau_3_pillars_veto_volume_john_murphy():
    """Menguji Veto Pilar 3 (John Murphy): Volume sepi (< 0.75x SMA 10) -> HOLD."""
    engine = SignalEngine()

    idx = pd.date_range("2026-10-13 14:00", periods=15, freq="15min")
    opens = [4185.0] * 15
    closes = [4188.0] * 15  # Di atas EMA 20
    highs = [4188.5] * 15   # Ekor pendek
    lows = [4184.0] * 15
    # Volume lilin terakhir hanya 200 vs rata-rata 1000 (0.2x < 0.75x)
    volumes = [1000.0] * 14 + [200.0]

    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
        "ema_20": [4180.0] * 15,
    }, index=idx)

    # Uji dengan prev bar juga volume rendah
    df.loc[df.index[-2], "Volume"] = 300.0

    res = engine.evaluate_bar(df, ticker="XAUUSD", apply_pdf_filter=True)
    assert res.signal == "HOLD"
    assert any("JOHN MURPHY" in r and "VOLUME RIIL" in r for r in res.reasons)


def test_xau_veto_rsi_overbought():
    """Menguji Veto Pilar 4 (Martin Pring): RSI > 68 (Overbought di pucuk) -> HOLD."""
    engine = SignalEngine()

    idx = pd.date_range("2026-10-13 14:00", periods=15, freq="15min")
    df = pd.DataFrame({
        "Open": [4185.0] * 15,
        "High": [4188.5] * 15,
        "Low": [4184.0] * 15,
        "Close": [4188.0] * 15,
        "Volume": [1000.0] * 15,
        "ema_20": [4180.0] * 15,
        "rsi": [75.0] * 15,  # Overbought pucuk
    }, index=idx)

    res = engine.evaluate_bar(df, ticker="XAUUSD", apply_pdf_filter=True)
    assert res.signal == "HOLD"
    assert any("ANTI BELI DI PUCUK" in r for r in res.reasons)


def test_xau_veto_rsi_weak_momentum():
    """Menguji Veto Pilar 4 (Martin Pring): RSI < 42 (Momentum buyer lemah) -> HOLD."""
    engine = SignalEngine()

    idx = pd.date_range("2026-10-13 14:00", periods=15, freq="15min")
    df = pd.DataFrame({
        "Open": [4185.0] * 15,
        "High": [4188.5] * 15,
        "Low": [4184.0] * 15,
        "Close": [4188.0] * 15,
        "Volume": [1000.0] * 15,
        "ema_20": [4180.0] * 15,
        "rsi": [38.0] * 15,  # Momentum lemah
    }, index=idx)

    res = engine.evaluate_bar(df, ticker="XAUUSD", apply_pdf_filter=True)
    assert res.signal == "HOLD"
    assert any("MOMENTUM LEMAH" in r for r in res.reasons)


def test_xau_veto_snr_resistance_ceiling():
    """Menguji Veto Pilar 5 (Key SNR): Harga menempel Resistance mayor (< 15 pips) -> HOLD."""
    engine = SignalEngine()

    idx = pd.date_range("2026-10-13 14:00", periods=15, freq="15min")
    highs = [4188.5] * 15
    highs[5] = 4189.2  # Resistance atap di 4189.20 (jarak cuma 0.70 USD dari Close 4188.50)
    df = pd.DataFrame({
        "Open": [4185.0] * 15,
        "High": highs,
        "Low": [4184.0] * 15,
        "Close": [4188.5] * 15,
        "Volume": [1000.0] * 15,
        "ema_20": [4180.0] * 15,
        "rsi": [55.0] * 15,
    }, index=idx)

    res = engine.evaluate_bar(df, ticker="XAUUSD", apply_pdf_filter=True)
    assert res.signal == "HOLD"
    assert any("ANTI TABRAK ATAP" in r for r in res.reasons)


def test_xau_3_pillars_all_satisfied_sell():
    """Menguji kondisi ideal di mana seluruh 5 Pilar Inti terpenuhi 100% menghasilkan SELL Grade A+."""
    engine = SignalEngine()

    idx = pd.date_range("2026-10-13 14:00", periods=15, freq="15min")
    opens = [4185.0 - i * 0.5 for i in range(15)]
    closes = [4183.5 - i * 0.5 for i in range(15)]
    lows = [c - 0.3 for c in closes]  # Ekor bawah sangat pendek
    highs = [o + 0.5 for o in opens]
    volumes = [1000.0] * 14 + [1200.0]  # Volume candle terakhir 1.2x

    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
        "ema_20": [4190.0] * 15,  # Di bawah EMA 20
        "rsi": [45.0] * 15,       # RSI 45 (32 <= RSI <= 58)
        "atr": [3.5] * 15,
    }, index=idx)

    res = engine.evaluate_bar(df, ticker="XAUUSD", apply_pdf_filter=True)
    assert res.signal in ["SELL", "SELL_LIMIT"]
    assert res.setup_grade == "Grade A+"
    assert res.pdf_confluence_score == 100.0
    assert "3_Pilar" in res.strategy_name
    assert res.take_profit_price <= res.price - 6.00  # Minimal 60 pips target bawah
    assert res.stop_loss_price >= res.price + 6.00    # Minimal 60 pips batas atas
    assert any("Bob Volman" in r for r in res.reasons)
    assert any("Mega Profit" in r for r in res.reasons)
    assert any("John Murphy" in r for r in res.reasons)
    assert any("Martin Pring" in r for r in res.reasons)


