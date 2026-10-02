import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from notify.telegram_bot import TelegramNotifier, TelegramBotCommands
from scheduler.run_scheduler import PipelineRunner
from strategy.signal_engine import SignalResult
import pandas as pd


def test_format_chart_confirmation_message():
    notifier = TelegramNotifier()
    info = {
        "ticker": "XAUUSD",
        "action": "SELL",
        "price": 3045.50,
        "tp": 3039.50,
        "sl": 3051.50,
        "score": 100.0,
        "grade": "Grade A+ (Setup Sempurna ⭐⭐⭐⭐⭐)",
        "prediction": "Arah market diprediksi Bearish kuat melanjutkan tren",
        "reasons": ["Breakout Support valid", "MACD Histogram Bearish"],
    }
    msg = notifier.format_chart_confirmation_message(info)
    assert "SINYAL KONFIRMASI CHART SELL" in msg
    assert "XAU/USD (Gold Spot)" in msg
    assert "$3,045.50" in msg
    assert "$3,039.50" in msg
    assert "$3,051.50" in msg
    assert "100%" in msg
    assert "Grade A+" in msg
    assert "Minimal 60 Pips" in msg
    assert "Mau open posisi sekarang bor?" in msg


def test_send_chart_confirmation_alert():
    notifier = TelegramNotifier()
    info = {
        "ticker": "XAUUSD",
        "action": "SELL",
        "price": 3045.50,
        "tp": 3039.50,
        "sl": 3051.50,
        "score": 100.0,
        "grade": "Grade A+",
    }
    with patch.object(notifier, "_async_send_text", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        res = notifier.send_chart_confirmation_alert(info)
        assert res is True
        assert mock_send.called
        call_args = mock_send.call_args
        reply_markup = call_args[1].get("reply_markup")
        assert reply_markup is not None
        # Check callback_data in inline keyboard
        buttons = reply_markup.inline_keyboard
        assert any("exec_chart_SELL_XAUUSD_3045.50_3039.50_3051.50" in btn.callback_data for row in buttons for btn in row if btn.callback_data)


def test_button_callback_exec_chart_member_vs_admin():
    async def _run():
        storage = MagicMock()
        storage.list_all_users.return_value = []
        bot_cmds = TelegramBotCommands(storage=storage)

        # 1. Non-admin user click
        update_member = MagicMock()
        update_member.effective_user.id = 12345678
        update_member.effective_user.username = "member_vip"
        query_member = MagicMock()
        query_member.data = "exec_chart_SELL_XAUUSD_3045.50_3039.50_3051.50"
        query_member.from_user.id = 12345678
        query_member.answer = AsyncMock()
        update_member.callback_query = query_member

        context = MagicMock()
        with patch.object(bot_cmds, "_is_admin", return_value=False):
            await bot_cmds.button_callback_handler(update_member, context)
            assert query_member.answer.called
            answer_text = query_member.answer.call_args[0][0]
            assert "Master Admin" in answer_text

        # 2. Admin user click
        update_admin = MagicMock()
        update_admin.effective_user.id = 8754997836
        update_admin.effective_user.username = "selobrow"
        query_admin = MagicMock()
        query_admin.data = "exec_chart_SELL_XAUUSD_3045.50_3039.50_3051.50"
        query_admin.from_user.id = 8754997836
        query_admin.answer = AsyncMock()
        query_admin.message.reply_html = AsyncMock()
        update_admin.callback_query = query_admin

        with patch.object(bot_cmds, "_is_admin", return_value=True), \
             patch("trading.mt5_bridge.MT5Bridge") as MockBridge, \
             patch.object(bot_cmds.notifier, "send_mt5_execution_report") as mock_report:
            bridge_inst = MockBridge.return_value
            bridge_inst.get_open_positions.return_value = []
            bridge_inst.enabled = True
            bridge_inst.default_lot = 0.05
            bridge_inst.gold_symbol = "XAUUSD"
            bridge_inst.execute_signal.return_value = {
                "success": True,
                "ticket": 998877,
                "volume": 0.05,
                "price": 3045.50,
                "tp": 3039.50,
                "sl": 3051.50,
            }

            await bot_cmds.button_callback_handler(update_admin, context)
            assert query_admin.answer.called
            assert query_admin.message.reply_html.called
            assert mock_report.called
            report_data = mock_report.call_args[0][0]
            assert report_data["ticket"] == 998877
            assert report_data["action"] == "SELL"

    asyncio.run(_run())


def test_pipeline_runner_chart_a_plus_trigger():
    storage = MagicMock()
    fetcher = MagicMock()
    notifier = MagicMock()

    runner = PipelineRunner(storage=storage, fetcher=fetcher, notifier=notifier)

    # Mock market open
    with patch("scheduler.run_scheduler.is_idx_market_open", return_value=(False, "Tutup")), \
         patch("scheduler.run_scheduler.is_gold_market_open", return_value=(True, "Buka")), \
         patch.object(runner, "check_and_report_mt5_deals"), \
         patch.object(runner, "check_upcoming_news_job"), \
         patch("trading.mt5_bridge.MT5Bridge") as MockBridge:
        mock_b = MockBridge.return_value
        mock_b.enabled = False
        mock_b.is_available.return_value = False
        mock_b.is_in_reversal_cooldown.return_value = (False, "")
        mock_b.get_open_positions.return_value = []

        # Create dummy df for gold with 100 bars
        dates = pd.date_range("2026-10-02 10:00", periods=100, freq="15min")
        df_gold = pd.DataFrame({
            "Open": [3040.0] * 100,
            "High": [3050.0] * 100,
            "Low": [3035.0] * 100,
            "Close": [3045.50] * 100,
            "Volume": [1000] * 100,
        }, index=dates)

        fetcher.get_data.return_value = df_gold
        fetcher.fetch_and_store.return_value = df_gold
        fetcher.normalize_ticker.side_effect = lambda t: t

        # Mock signal_engine to return HOLD but Grade A+ 100% confluence Bearish
        sig_hold = SignalResult(
            signal="HOLD",
            ticker="XAUUSD",
            strategy_name="DayTrading_Intraday_Momentum",
            price=3045.50,
            reasons=["RSI Oversold blocking direct SELL"],
            candle_time=str(dates[-1]),
            pdf_confluence_score=100.0,
            setup_grade="Grade A+ (Setup Sempurna ⭐⭐⭐⭐⭐)",
            market_direction_prediction="Arah market diprediksi Bearish kuat melanjutkan tren",
        )
        runner.signal_engine.evaluate_bar = MagicMock(return_value=sig_hold)
        notifier.send_chart_confirmation_alert.return_value = True

        res = runner.run_pipeline(watchlist=["XAUUSD"])

        # send_signal (Auto-Open) should NOT be called because signal is HOLD
        assert not notifier.send_signal.called
        # send_chart_confirmation_alert SHOULD be called!
        assert notifier.send_chart_confirmation_alert.called
        call_info = notifier.send_chart_confirmation_alert.call_args[0][0]
        assert call_info["ticker"] == "XAUUSD"
        assert call_info["action"] == "SELL"
        assert call_info["score"] == 100.0
        # Check min 60 pips 1:1 floor
        assert abs(call_info["price"] - call_info["sl"]) >= 6.00
        assert abs(call_info["tp"] - call_info["price"]) >= 6.00

        # Second run on the same candle: deduplication should prevent sending again!
        notifier.send_chart_confirmation_alert.reset_mock()
        res2 = runner.run_pipeline(watchlist=["XAUUSD"])
        assert not notifier.send_chart_confirmation_alert.called
