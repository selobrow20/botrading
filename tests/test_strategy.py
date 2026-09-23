import pytest
import pandas as pd
from strategy.rules import RuleCondition, Strategy
from strategy.signal_engine import SignalEngine


def test_rule_condition_operators():
    row_curr = pd.Series({"rsi": 25.0, "close": 5000.0, "ema_50": 4800.0})
    row_prev = pd.Series({"rsi": 32.0, "close": 4790.0, "ema_50": 4800.0})

    # Test less than
    rc_lt = RuleCondition("rsi", "<", value=30.0)
    sat, reason = rc_lt.evaluate_bar(row_curr, row_prev)
    assert sat is True

    # Test greater than
    rc_gt = RuleCondition("close", ">", target="ema_50")
    sat, reason = rc_gt.evaluate_bar(row_curr, row_prev)
    assert sat is True

    # Test crossover
    rc_cross = RuleCondition("close", "cross_above", target="ema_50")
    sat, reason = rc_cross.evaluate_bar(row_curr, row_prev)
    assert sat is True


def test_strategy_and_or_combination():
    strat_and = Strategy(
        name="TestAND",
        description="Test AND",
        buy_rules=[
            RuleCondition("rsi", "<", value=30.0),
            RuleCondition("close", ">", target="ema_50"),
        ],
        buy_combine="AND",
    )

    row_curr = pd.Series({"rsi": 28.0, "close": 5000.0, "ema_50": 4800.0, "volume": 1000.0})
    row_prev = pd.Series({"rsi": 35.0, "close": 4900.0, "ema_50": 4800.0, "volume": 1000.0})

    res = [r.evaluate_bar(row_curr, row_prev)[0] for r in strat_and.buy_rules]
    assert all(res) is True


def test_signal_engine_evaluation():
    dates = pd.date_range("2026-01-01", periods=60, freq="D")
    df = pd.DataFrame(
        {
            "Open": [5000.0] * 60,
            "High": [5100.0] * 60,
            "Low": [4900.0] * 60,
            "Close": [5050.0] * 60,
            "Volume": [2_000_000.0] * 60,
        },
        index=dates,
    )

    engine = SignalEngine()
    sig = engine.evaluate_bar(df, ticker="TEST.JK")
    assert sig.signal in ["BUY", "SELL", "HOLD"]
    assert sig.price == 5050.0
