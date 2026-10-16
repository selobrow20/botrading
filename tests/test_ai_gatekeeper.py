import pytest
from strategy.ai_gatekeeper import AIGatekeeper


def test_ai_gatekeeper_singleton():
    g1 = AIGatekeeper.get_instance()
    g2 = AIGatekeeper.get_instance()
    assert g1 is g2


def test_ai_gatekeeper_fallback_without_key():
    gate = AIGatekeeper(api_key="")
    assert gate.has_brain() is False
    
    # Evaluasi gold fallback
    res_gold = gate.evaluate_gold_trade("BUY", 2650.0, {"score": 85})
    assert res_gold["approved"] is True
    assert res_gold["ai_active"] is False

    # Evaluasi crypto pump fallback
    res_crypto = gate.evaluate_crypto_pump("PEPEUSDT", 0.000004, 5.0, 10000000, 90, "SUPER PUMP")
    assert res_crypto["approved"] is True
    assert res_crypto["ai_active"] is False

    # Evaluasi reversal flip fallback
    res_reversal = gate.evaluate_reversal_exit_or_flip(
        current_positions=[{"ticket": 123, "type": "BUY", "price_open": 2650.0, "profit": -10.0}],
        new_signal={"type": "SELL", "price": 2645.0},
        indicators={"ema50": 2648.0, "rsi": 35.0},
    )
    assert res_reversal["should_cut_loss"] is False
    assert res_reversal["should_flip"] is False
    assert res_reversal["ai_active"] is False

    # Evaluasi post-mortem fallback
    res_post_mortem = gate.evaluate_sl_post_mortem(
        trade_details={"ticket": 123, "type": "BUY", "loss": -12.5},
        market_snapshot={"price": 2640.0, "trend": "BEARISH"},
    )
    assert "diagnosa" in res_post_mortem
    assert res_post_mortem["ai_active"] is False
    assert res_post_mortem["cooldown_mins"] == 35


def test_ai_gatekeeper_mocked_gemini(monkeypatch):
    gate = AIGatekeeper(api_key="mock_test_key")
    assert gate.has_brain() is True

    # Test mocked reversal flip
    def mock_call_reversal(user_prompt, sys_prompt):
        return {
            "should_cut_loss": True,
            "should_flip": True,
            "score": 95,
            "verdict": "CUT_LOSS_AND_FLIP",
            "reason": "Breakdown struktural valid.",
            "warning": "Waspada slippage.",
        }

    monkeypatch.setattr(gate, "_call_gemini", mock_call_reversal)
    rev_res = gate.evaluate_reversal_exit_or_flip(
        current_positions=[{"ticket": 999, "type": "BUY", "price_open": 4200.0, "profit": -50.0}],
        new_signal={"type": "SELL", "price": 4180.0},
        indicators={"ema50": 4195.0},
    )
    assert rev_res["should_cut_loss"] is True
    assert rev_res["should_flip"] is True
    assert rev_res["ai_active"] is True
    assert rev_res["verdict"] == "CUT_LOSS_AND_FLIP"

    # Test mocked post-mortem
    def mock_call_pm(user_prompt, sys_prompt):
        return {
            "diagnosa": "Breakdown EMA 50 & likuiditas tersapu.",
            "market_condition": "Bearish agresif.",
            "action_plan": "Tunggu pullback ke 4190 sebelum sell.",
            "cooldown_mins": 45,
            "bot_posture": "DEFENSIVE: Kunci BUY 45 menit.",
        }

    monkeypatch.setattr(gate, "_call_gemini", mock_call_pm)
    pm_res = gate.evaluate_sl_post_mortem(
        trade_details={"ticket": 999, "type": "BUY", "loss": -50.0},
        market_snapshot={"price": 4180.0, "trend": "BEARISH"},
    )
    assert pm_res["ai_active"] is True
    assert pm_res["cooldown_mins"] == 45
    assert "Breakdown EMA 50" in pm_res["diagnosa"]


def test_ai_gatekeeper_timeout_veto_counter_trend(monkeypatch):
    gate = AIGatekeeper(api_key="mock_key")
    # Simulate Gemini timeout returning None
    monkeypatch.setattr(gate, "_call_gemini", lambda *args, **kwargs: None)

    # 1. Counter-trend BUY in BEARISH H1
    res_buy = gate.evaluate_gold_trade(
        signal_type="BUY",
        price=4160.0,
        indicators={"h1_trend": "BEARISH", "score": 85},
    )
    assert res_buy["approved"] is False
    assert res_buy["verdict"] == "VETO_COUNTER_TREND_FALLBACK"
    assert "melawan arah tren" in res_buy["reason"]

    # 2. Counter-trend SELL in BULLISH H4
    res_sell = gate.evaluate_gold_trade(
        signal_type="SELL",
        price=4200.0,
        indicators={"h4_trend": "BULLISH", "score": 90},
    )
    assert res_sell["approved"] is False
    assert res_sell["verdict"] == "VETO_COUNTER_TREND_FALLBACK"

    # 3. Trend aligned BUY in BULLISH H1 with good score
    res_trend_ok = gate.evaluate_gold_trade(
        signal_type="BUY",
        price=4200.0,
        indicators={"h1_trend": "BULLISH", "score": 85},
    )
    assert res_trend_ok["approved"] is True
    assert res_trend_ok["verdict"] == "APPROVED_QUANT_FALLBACK"


