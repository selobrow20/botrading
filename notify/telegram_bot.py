import os
import asyncio
import html
from typing import Optional, List, Dict, Any
from pathlib import Path
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config.settings import load_config, setup_logger
from data.storage import StockStorage
from strategy.signal_engine import SignalResult

logger = setup_logger("telegram_bot")


def format_currency(price: Optional[float], ticker: str = "") -> str:
    """Helper untuk memformat harga mata uang (USD untuk Emas, Rp untuk IDX)."""
    if price is None:
        return "-"
    ticker_upper = (ticker or "").upper()
    if any(k in ticker_upper for k in ["GC=F", "XAUUSD", "XAU/USD", "GOLD", "EMAS"]):
        return f"${price:,.2f}"
    return f"Rp {price:,.0f}"


class TelegramNotifier:
    """Modul pengirim notifikasi sinyal ke Telegram via Bot API."""

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        storage: Optional[StockStorage] = None,
    ):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.storage = storage or StockStorage()
        self.config = load_config()

        # Cek apakah kredensial valid
        is_placeholder = (
            not self.token
            or "your_telegram" in self.token
            or not self.chat_id
            or "your_telegram" in self.chat_id
        )
        self.is_configured = not is_placeholder

        if not self.is_configured:
            logger.warning(
                "Kredensial Telegram (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) belum disetel di .env. "
                "Berjalan dalam mode Simulasi (Mock Mode) - pesan akan dicetak ke log."
            )
        else:
            logger.info("Telegram Notifier siap dalam mode Live.")

    def format_signal_message(self, sig: SignalResult) -> str:
        """Membuat template pesan sinyal ringkas, padat, dan hemat token."""
        action_emoji = "🟢" if sig.signal == "BUY" else "🔴" if sig.signal == "SELL" else "⚪"

        # Tampilan instrumen
        ticker_upper = sig.ticker.upper()
        if any(k in ticker_upper for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"]):
            display_ticker = "XAU/USD (Gold)"
        else:
            display_ticker = sig.ticker.replace(".JK", "")

        price_str = format_currency(sig.price, sig.ticker)

        # Waktu candle WIB
        t_str = str(sig.candle_time or "")
        if len(t_str) >= 16:
            time_wib = f"{t_str[11:16]} WIB"
        else:
            time_wib = f"{t_str} WIB" if t_str else "WIB"

        snap = sig.indicators_snapshot or {}
        rsi_val = f"{snap.get('rsi', 0.0):.1f}"
        vol_ratio = f"{snap.get('volume_ratio', 1.0):.1f}x"

        lines = [f"{action_emoji} <b>{sig.signal}: {display_ticker}</b> @ <b>{price_str}</b>"]

        if sig.take_profit_price and sig.stop_loss_price:
            tp_str = format_currency(sig.take_profit_price, sig.ticker)
            sl_str = format_currency(sig.stop_loss_price, sig.ticker)
            rrr = sig.risk_reward_ratio or 1.5
            lines.append(f"🎯 TP: <b>{tp_str}</b> | 🛑 SL: <b>{sl_str}</b> (RRR 1:{rrr})")

        lines.append(f"⏱️ <b>{time_wib}</b> | RSI: <b>{rsi_val}</b> | Vol: <b>{vol_ratio}</b>")

        if sig.reasons:
            clean_reason = sig.reasons[0].split("(")[0].strip()
            lines.append(f"💡 <i>{html.escape(clean_reason)}</i>")

        return "\n".join(lines)

    async def _async_send_text(self, text: str) -> bool:
        """Mengirim pesan teks secara asinkron."""
        if not self.is_configured:
            logger.info(f"[SIMULASI TELEGRAM]\n{text}")
            return True

        bot = Bot(token=self.token)
        try:
            await bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
            logger.info("Pesan berhasil terkirim ke Telegram.")
            return True
        except Exception as e:
            logger.error(f"Gagal mengirim pesan ke Telegram: {e}")
            return False

    async def _async_send_photo(self, photo_path: str, caption: str) -> bool:
        """Mengirim file foto beserta caption ke Telegram."""
        if not self.is_configured:
            logger.info(f"[SIMULASI TELEGRAM PHOTO] {photo_path}\n{caption}")
            return True

        bot = Bot(token=self.token)
        try:
            with open(photo_path, "rb") as photo:
                await bot.send_photo(
                    chat_id=self.chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )
            logger.info(f"Foto {photo_path} berhasil terkirim ke Telegram.")
            return True
        except Exception as e:
            logger.error(f"Gagal mengirim foto ke Telegram: {e}")
            return False

    def send_signal(self, sig: SignalResult, photo_path: Optional[str] = None) -> bool:
        """
        Wrapper sinkron untuk mengirim kartu sinyal (bisa dipanggil dari scheduler / synchronous code).
        """
        msg = self.format_signal_message(sig)
        try:
            if photo_path and Path(photo_path).exists():
                return asyncio.run(self._async_send_photo(photo_path, msg))
            else:
                return asyncio.run(self._async_send_text(msg))
        except Exception as e:
            logger.error(f"Error saat mengeksekusi send_signal: {e}")
            return False

    def send_message(self, text: str) -> bool:
        """Mengirim pesan teks biasa ke Telegram."""
        try:
            return asyncio.run(self._async_send_text(text))
        except Exception as e:
            logger.error(f"Error saat mengeksekusi send_message: {e}")
            return False


class TelegramBotCommands:
    """Handler perintah interaktif bot Telegram (/status, /watchlist, /lasthistory)."""

    def __init__(self, storage: Optional[StockStorage] = None):
        self.storage = storage or StockStorage()
        self.config = load_config()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /start dan /help"""
        user_name = update.effective_user.first_name if update.effective_user else "Trader"
        welcome_text = (
            f"👋 Halo <b>{html.escape(user_name)}</b>!\n\n"
            f"Selamat datang di <b>IDX Stock Signal Bot</b> 🇮🇩\n\n"
            f"<b>Perintah yang tersedia:</b>\n"
            f"🎯 /harian - Rekomendasi sinyal trading harian (Entry, TP & SL)\n"
            f"🥇 /gold - Analisis & sinyal emas dunia XAU/USD (24 Jam)\n"
            f"🔍 /scan - Pindai seluruh saham potensial sekarang juga (On-Demand)\n"
            f"📋 /watchlist - Lihat daftar saham potensial cuan & harga terkini\n"
            f"⚙️ /status - Cek status kesehatan & info sistem bot\n"
            f"📜 /lasthistory - Tampilkan 5 riwayat sinyal terakhir\n"
            f"ℹ️ /help - Bantuan & panduan bot\n\n"
            f"<i>Bot ini berjalan otomatis untuk saham IDX & komoditas global.</i>"
        )
        await update.message.reply_html(welcome_text)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /status untuk cek kondisi bot."""
        cfg = load_config()
        strat_active = cfg.get("strategies", {}).get("active", "Default")
        interval = cfg.get("scheduler", {}).get("interval_minutes", 15)
        watchlist = cfg.get("watchlist", [])

        status_text = (
            f"🟢 <b>STATUS SISTEM: RUNNING / AKTIF</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ <b>Strategi Aktif:</b> <code>{html.escape(strat_active)}</code>\n"
            f"⏱️ <b>Interval Pengecekan:</b> Tiap {interval} Menit\n"
            f"📊 <b>Total Saham Dipantau:</b> {len(watchlist)} Saham\n"
            f"💾 <b>Database:</b> SQLite (Terkoneksi)\n"
            f"⏰ <b>Zona Waktu:</b> Asia/Jakarta (WIB)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Gunakan /watchlist untuk melihat daftar saham lengkap.</i>"
        )
        await update.message.reply_html(status_text)

    async def watchlist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /watchlist untuk melihat daftar saham."""
        cfg = load_config()
        watchlist = cfg.get("watchlist", [])

        if not watchlist:
            await update.message.reply_text("Watchlist masih kosong di config.yaml.")
            return

        lines = ["📋 <b>DAFTAR SAHAM POTENSIAL CUAN (WATCHLIST):</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
        for idx, ticker in enumerate(watchlist, 1):
            row = self.storage.get_latest_price_any_interval(ticker)
            if row:
                last_price = f"Rp {float(row['close']):,.0f}"
                dt_str = str(row["datetime"])
                # Format: DD/MM HH:MM
                last_date = dt_str[5:16] if len(dt_str) >= 16 else dt_str
                lines.append(f"<b>{idx}.</b> <code>{ticker}</code>: <b>{last_price}</b> ({last_date})")
            else:
                lines.append(f"<b>{idx}.</b> <code>{ticker}</code>: (Sedang dianalisis...)")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("<i>Diperbarui otomatis tiap 15 menit saat jam bursa BEI.</i>")
        await update.message.reply_html("\n".join(lines))

    async def lasthistory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /lasthistory untuk melihat 5 riwayat sinyal terakhir."""
        signals = self.storage.get_recent_signals(limit=5)

        if not signals:
            await update.message.reply_text("Belum ada riwayat sinyal yang tercatat di database.")
            return

        lines = ["📜 <b>5 RIWAYAT SINYAL TERAKHIR:</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
        for s in signals:
            sig_type = s.get("signal_type", "HOLD")
            emoji = "🟢" if sig_type == "BUY" else "🔴" if sig_type == "SELL" else "⚪"
            ticker = s.get("ticker", "-")
            price = f"Rp {float(s.get('price', 0)):,.0f}"
            t_candle = s.get("candle_time", "-")
            reasons = s.get("reasons", [])
            reason_str = reasons[0] if reasons else "-"

            lines.append(f"{emoji} <b>{sig_type}</b> - <code>{ticker}</code> @ {price}")
            lines.append(f"   <i>Waktu: {t_candle}</i>")
            lines.append(f"   <i>Pemicu: {html.escape(reason_str)}</i>")
            lines.append("──────────────────────")

        await update.message.reply_html("\n".join(lines))

    async def scan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /scan untuk menjalankan pemindaian on-demand."""
        await update.message.reply_html("🔍 <i>Sedang memindai saham potensial di watchlist, mohon tunggu sebentar...</i>")
        import asyncio
        from scheduler.run_scheduler import PipelineRunner

        runner = PipelineRunner(storage=self.storage)
        res = await asyncio.to_thread(runner.run_pipeline, force_run=True)
        signals_triggered = res.get("signals_triggered", 0)
        processed = res.get("processed", 0)

        reply_lines = [
            f"✅ <b>Pemindaian Selesai!</b>",
            f"• Saham Diproses: <b>{processed}</b>",
            f"• Sinyal Aktif: <b>{signals_triggered}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for d in res.get("details", []):
            if d.get("signal") in ["BUY", "SELL"]:
                emoji = "🟢" if d.get("signal") == "BUY" else "🔴"
                reply_lines.append(f"{emoji} <b>{d.get('signal')}</b>: <code>{d.get('ticker')}</code> @ Rp {float(d.get('price', 0)):,.0f}")

        if signals_triggered == 0:
            reply_lines.append("<i>Semua saham saat ini dalam status netral (HOLD).</i>")

        await update.message.reply_html("\n".join(reply_lines))

    async def harian_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /harian untuk melihat rekomendasi sinyal trading harian lengkap dengan TP & SL."""
        await update.message.reply_html("⏳ <i>Menganalisis saham potensial untuk Trading Harian (Day Trading & Swing)...</i>")

        from data.fetcher import DataFetcher
        from indicators.technical import TechnicalIndicators
        from strategy.rules import get_strategy, DEFAULT_STRATEGY
        from strategy.signal_engine import SignalEngine

        cfg = load_config()
        trading_cfg = cfg.get("trading", {})
        mode = trading_cfg.get("mode", "intraday")
        strat_name = cfg.get("strategies", {}).get("active", "DayTrading_Intraday_Momentum")
        strategy = get_strategy(strat_name) or DEFAULT_STRATEGY

        fetcher = DataFetcher(storage=self.storage)
        engine = SignalEngine([strategy])

        watchlist = cfg.get("watchlist", [])
        # Batasi ke 10 saham teratas untuk respon cepat di Telegram
        sample_watchlist = watchlist[:10]

        buy_signals = []
        radar_stocks = []

        for ticker in sample_watchlist:
            try:
                # Ambil data terbaru
                df = fetcher.get_data(ticker, interval="15m" if mode == "intraday" else "1d", period="5d")
                if df.empty or len(df) < 15:
                    continue

                df_ind = TechnicalIndicators.add_all_indicators(df)
                sig = engine.evaluate_bar(df_ind, ticker=ticker, strategy=strategy)

                snap = sig.indicators_snapshot or {}
                rsi = snap.get("rsi", 50.0)
                vol_ratio = snap.get("volume_ratio", 1.0)

                if sig.signal == "BUY":
                    buy_signals.append(sig)
                elif rsi >= 45.0 and rsi <= 65.0:
                    # Saham di zona momentum sehat (radar pantauan)
                    radar_stocks.append({
                        "ticker": ticker,
                        "price": sig.price,
                        "rsi": rsi,
                        "vol_ratio": vol_ratio,
                    })
            except Exception as e:
                logger.debug(f"Error analisa {ticker}: {e}")

        # Susun Pesan Rekomendasi
        lines = [
            f"🎯 <b>REKOMENDASI TRADING HARIAN IDX</b> 🇮🇩",
            f"⚙️ Mode: <b>{mode.upper()}</b> | Strategi: <i>{strategy.name}</i>",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]

        if buy_signals:
            lines.append("🟢 <b>SINYAL BELI SIAP EKSEKUSI (ENTRY):</b>")
            for b in buy_signals:
                lines.append(f"• <code>{b.ticker}</code> @ <b>Rp {b.price:,.0f}</b>")
                lines.append(f"  🎯 Target Profit (TP): <b>Rp {b.take_profit_price:,.0f}</b>")
                lines.append(f"  🛑 Stop Loss (SL): <b>Rp {b.stop_loss_price:,.0f}</b>")
                lines.append(f"  ⚖️ Risk/Reward: <b>1 : {b.risk_reward_ratio or 1.67}</b>")
                lines.append("──────────────────────")
        else:
            lines.append("<i>Belum ada sinyal BUY yang terkonfirmasi penuh pada candle saat ini.</i>")
            lines.append("──────────────────────")

        if radar_stocks:
            lines.append("👀 <b>RADAR PANTAUAN (Mendekati Momentum Beli):</b>")
            for r in radar_stocks[:5]:
                lines.append(
                    f"• <code>{r['ticker']}</code>: Rp {r['price']:,.0f} "
                    f"(RSI: {r['rsi']:.1f}, Vol: {r['vol_ratio']:.1f}x)"
                )
            lines.append("━━━━━━━━━━━━━━━━━━━━━━")

        lines.append("💡 <i>Ketik /scan untuk memindai ulang pasar secara langsung.</i>")
        await update.message.reply_html("\n".join(lines))

    async def gold_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /gold dan /xau untuk analisis teknikal & sinyal Emas Dunia (XAU/USD)."""
        await update.message.reply_html("⏳ <i>Menganalisis pergerakan harga emas dunia XAU/USD (COMEX Gold)...</i>")
        import asyncio
        from data.fetcher import DataFetcher
        from indicators.technical import TechnicalIndicators
        from strategy.rules import get_strategy, DEFAULT_STRATEGY
        from strategy.signal_engine import SignalEngine

        def _compute_gold():
            fetcher = DataFetcher(storage=self.storage)
            df = fetcher.get_data("GC=F", interval="15m", period="5d")
            if df.empty or len(df) < 15:
                df = fetcher.get_data("GC=F", interval="1h", period="1mo")
            if df.empty or len(df) < 15:
                return None

            df_ind = TechnicalIndicators.add_all_indicators(df)
            strategy = get_strategy("DayTrading_Intraday_Momentum") or DEFAULT_STRATEGY
            engine = SignalEngine([strategy])
            sig = engine.evaluate_bar(df_ind, ticker="GC=F", strategy=strategy)

            last_row = df_ind.iloc[-1]
            last_close = float(last_row["Close"])
            dt_str = str(df_ind.index[-1])
            time_str = dt_str[5:16] if len(dt_str) >= 16 else dt_str

            tail_bars = df_ind.tail(min(96, len(df_ind)))
            high_24h = float(tail_bars["High"].max())
            low_24h = float(tail_bars["Low"].min())

            snap = sig.indicators_snapshot or {}
            rsi = snap.get("rsi", 50.0)
            ema20 = snap.get("ema_20", last_close)
            ema50 = snap.get("ema_50", last_close)
            vol_ratio = snap.get("volume_ratio", 1.0)
            bb_upper = float(last_row.get("BB_Upper", last_close * 1.01))
            bb_lower = float(last_row.get("BB_Lower", last_close * 0.99))

            # TP +0.6% & SL -0.35% untuk Gold Intraday
            tp_calc = last_close * 1.006
            sl_calc = last_close * 0.9965
            rrr = round((tp_calc - last_close) / (last_close - sl_calc), 2)

            return {
                "close": last_close,
                "time": time_str,
                "high_24h": high_24h,
                "low_24h": low_24h,
                "rsi": rsi,
                "ema20": ema20,
                "ema50": ema50,
                "bb_upper": bb_upper,
                "bb_lower": bb_lower,
                "vol_ratio": vol_ratio,
                "signal": sig.signal,
                "reasons": sig.reasons,
                "tp": tp_calc,
                "sl": sl_calc,
                "rrr": rrr,
            }

        data = await asyncio.to_thread(_compute_gold)
        if not data:
            await update.message.reply_text("Maaf, data pasar XAU/USD (Gold) saat ini sedang tidak dapat diakses dari feed. Coba beberapa saat lagi.")
            return

        rsi = data["rsi"]
        if rsi < 30:
            rsi_desc = "Oversold / Jenuh Jual 🟢 Potensi Rebound"
        elif rsi > 70:
            rsi_desc = "Overbought / Jenuh Beli 🔴 Rawan Koreksi"
        elif rsi >= 50:
            rsi_desc = "Netral Bullish 🟢"
        else:
            rsi_desc = "Netral Bearish ⚪"

        close = data["close"]
        ema20 = data["ema20"]
        ema50 = data["ema50"]
        if close > ema20 > ema50:
            trend_desc = "🟢 Kuat Naik (Strong Uptrend)"
        elif close > ema20:
            trend_desc = "🟢 Bullish (Di atas EMA 20)"
        elif close < ema20 < ema50:
            trend_desc = "🔴 Kuat Turun (Strong Downtrend)"
        else:
            trend_desc = "⚪ Sideways / Konsolidasi"

        sig_type = data["signal"]
        if sig_type == "BUY":
            sig_badge = "🟢 <b>BUY (SIAP ENTRY)</b>"
        elif sig_type == "SELL":
            sig_badge = "🔴 <b>SELL / EXIT</b>"
        elif rsi < 35:
            sig_badge = "👀 <b>RADAR PANTAUAN (Dekat Titik Pantul)</b>"
        else:
            sig_badge = "⚪ <b>WAIT / WAIT & SEE (Netral)</b>"

        msg_lines = [
            "🥇 <b>ANALISIS PASAR XAU/USD (GOLD)</b> 🌎",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>Harga Terkini:</b> <code>${close:,.2f}</code>",
            f"⏰ <b>Waktu Candle:</b> {data['time']}",
            f"📊 <b>Rentang 24 Jam:</b> ${data['low_24h']:,.2f} - ${data['high_24h']:,.2f}",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📈 <b>INDIKATOR TEKNIKAL (15m):</b>",
            f"• <b>RSI (14):</b> {rsi:.1f} ({rsi_desc})",
            f"• <b>EMA 20:</b> ${ema20:,.2f}",
            f"• <b>EMA 50:</b> ${ema50:,.2f}",
            f"• <b>Tren MA:</b> {trend_desc}",
            f"• <b>Bollinger Bands:</b> Upper ${data['bb_upper']:,.2f} | Lower ${data['bb_lower']:,.2f}",
            f"• <b>Volume 15m:</b> {data['vol_ratio']:.1f}x rata-rata",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🎯 <b>STATUS SINYAL:</b> {sig_badge}",
            f"  • Entry Ref: <b>${close:,.2f}</b>",
            f"  • Target Profit (TP): <b>${data['tp']:,.2f}</b> (+0.6%)",
            f"  • Stop Loss (SL): <b>${data['sl']:,.2f}</b> (-0.35%)",
            f"  • Risk/Reward Ratio: <b>1 : {data['rrr']}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "💡 <i>Pasar emas global aktif 23 jam sehari (Senin-Jumat). Kelola leverage secara bijak!</i>",
        ]

        await update.message.reply_html("\n".join(msg_lines))


async def set_menu_commands(application: Application) -> None:
    """Mendaftarkan tombol Menu perintah interaktif di aplikasi Telegram."""
    from telegram import BotCommand
    commands = [
        BotCommand("harian", "🎯 Rekomendasi Sinyal Trading Harian (TP & SL)"),
        BotCommand("gold", "🥇 Analisis Sinyal Emas Dunia (XAU/USD)"),
        BotCommand("scan", "🔍 Pindai Sinyal Pasar Sekarang"),
        BotCommand("watchlist", "📋 Saham Potensial Cuan & Harga"),
        BotCommand("status", "⚙️ Status Bot & Strategi Aktif"),
        BotCommand("lasthistory", "📜 Riwayat Sinyal Terakhir"),
        BotCommand("help", "ℹ️ Panduan Penggunaan Bot"),
    ]
    try:
        await application.bot.set_my_commands(commands)
    except Exception as e:
        logger.debug(f"Gagal mengatur menu perintah bot: {e}")


def build_telegram_application() -> Optional[Application]:
    """Membuat dan mengonfigurasi aplikasi bot Telegram dengan seluruh CommandHandler."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or "your_telegram" in token:
        logger.warning("Token Telegram belum disetel, bot listener tidak dapat dijalankan.")
        return None

    app = Application.builder().token(token).post_init(set_menu_commands).build()
    cmd_handler = TelegramBotCommands()

    app.add_handler(CommandHandler(["start", "help"], cmd_handler.start_command))
    app.add_handler(CommandHandler(["harian", "tradingharian", "daytrade"], cmd_handler.harian_command))
    app.add_handler(CommandHandler(["gold", "xau", "emas"], cmd_handler.gold_command))
    app.add_handler(CommandHandler("status", cmd_handler.status_command))
    app.add_handler(CommandHandler("scan", cmd_handler.scan_command))
    app.add_handler(CommandHandler("watchlist", cmd_handler.watchlist_command))
    app.add_handler(CommandHandler("lasthistory", cmd_handler.lasthistory_command))

    return app


def run_telegram_bot_polling() -> None:
    """Menjalankan bot polling listener secara independen."""
    app = build_telegram_application()
    if app:
        logger.info("Memulai Telegram bot polling listener...")
        try:
            app.run_polling(stop_signals=None)
        except Exception:
            app.run_polling()
    else:
        logger.error("Gagal menjalankan bot: Token Telegram tidak valid.")
