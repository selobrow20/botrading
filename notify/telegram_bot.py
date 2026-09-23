import os
import asyncio
import html
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any
from pathlib import Path
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

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


SUPERADMIN_CHAT_ID = "8754997836"
SUPERADMIN_USERNAMES = {"selobrow", "selobrow20"}


def get_admin_id() -> str:
    """Mengambil Chat ID admin dengan fallback aman ke SuperAdmin."""
    env_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip().strip('"').strip("'")
    if env_id and env_id.isdigit() and env_id not in ["123456789", "987654321", "0"]:
        return env_id
    return SUPERADMIN_CHAT_ID


class TelegramNotifier:
    """Modul pengirim notifikasi sinyal ke Telegram via Bot API."""

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        storage: Optional[StockStorage] = None,
    ):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = chat_id or get_admin_id()
        self.storage = storage or StockStorage()
        self.config = load_config()

        # Cek apakah kredensial valid
        is_placeholder = (
            not self.token
            or "your_telegram" in self.token
            or "mock" in self.token.lower()
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

        # Waktu pengiriman sinyal real-time WIB (sama persis dengan jam handphone/komputer)
        try:
            tz = ZoneInfo("Asia/Jakarta")
            time_wib = datetime.now(tz).strftime("%H:%M WIB")
        except Exception:
            time_wib = "WIB"

        snap = sig.indicators_snapshot or {}
        rsi_val = f"{snap.get('rsi', 0.0):.1f}"
        vol_ratio = f"{snap.get('volume_ratio', 1.0):.1f}x"

        is_gold = any(k in ticker_upper for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        wr_stats = self.storage.get_win_rate_stats()
        comp = wr_stats.get("completed", 0)
        wr_badge = f"📊 <b>Akurasi Bot:</b> Win Rate <b>{wr_stats['win_rate']:.1f}%</b> ({wr_stats['win_count']}W / {wr_stats['lose_count']}L)" if comp > 0 else "📊 <b>Akurasi Bot:</b> <i>Sedang aktif melacak sinyal</i>"

        lines = []

        if sig.signal == "BUY":
            lines.append(f"🟢 <b>SINYAL ENTRY (MASUK / BUY): {display_ticker}</b>")
            lines.append(f"📍 <b>Harga Entry:</b> <code>{price_str}</code>")
            if sig.take_profit_price and sig.stop_loss_price:
                tp_str = format_currency(sig.take_profit_price, sig.ticker)
                sl_str = format_currency(sig.stop_loss_price, sig.ticker)
                rrr = sig.risk_reward_ratio or 1.5
                pct_tp = ((sig.take_profit_price - sig.price) / max(sig.price, 0.01)) * 100.0
                pct_sl = ((sig.price - sig.stop_loss_price) / max(sig.price, 0.01)) * 100.0
                lines.append(f"🎯 <b>Take Profit (TP):</b> <code>{tp_str}</code> (+{pct_tp:.2f}%)")
                lines.append(f"🛑 <b>Stop Loss (SL):</b> <code>{sl_str}</code> (-{pct_sl:.2f}%)")
                lines.append(f"⚖️ <b>Risk/Reward Ratio:</b> 1 : {rrr}")

            lines.append(f"⏱️ <b>{time_wib}</b> | RSI: <b>{rsi_val}</b> | Vol: <b>{vol_ratio}</b>")
            lines.append(wr_badge)

            # Telaah 7 Buku PDF untuk Sinyal Masuk
            pdf_details = getattr(sig, "pdf_confluence_details", [])
            if pdf_details:
                grade_str = getattr(sig, "setup_grade", "") or "Grade A"
                score_val = getattr(sig, "pdf_confluence_score", 0.0)
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
                lines.append(f"📚 <b>TELAAH 7 BUKU PDF ({grade_str} - {score_val:.0f}%):</b>")
                for chk in pdf_details[:4]:
                    lines.append(f"• {html.escape(chk)}")

                pred = getattr(sig, "market_direction_prediction", "")
                if pred:
                    lines.append(f"🎯 <b>Prediksi Arah:</b> <i>{html.escape(pred)}</i>")
            elif sig.reasons:
                clean_reason = sig.reasons[0].split("(")[0].strip()
                lines.append(f"💡 <i>{html.escape(clean_reason)}</i>")

        elif sig.signal == "SELL" and is_gold:
            # Short Gold
            lines.append(f"🔴 <b>SINYAL ENTRY SHORT (SELL): {display_ticker}</b>")
            lines.append(f"📍 <b>Harga Entry Short:</b> <code>{price_str}</code>")
            if sig.take_profit_price and sig.stop_loss_price:
                tp_str = format_currency(sig.take_profit_price, sig.ticker)
                sl_str = format_currency(sig.stop_loss_price, sig.ticker)
                rrr = sig.risk_reward_ratio or 1.5
                pct_tp = ((sig.price - sig.take_profit_price) / max(sig.price, 0.01)) * 100.0
                pct_sl = ((sig.stop_loss_price - sig.price) / max(sig.price, 0.01)) * 100.0
                lines.append(f"🎯 <b>Take Profit (TP):</b> <code>{tp_str}</code> (-{pct_tp:.2f}% Target Bawah)")
                lines.append(f"🛑 <b>Stop Loss (SL):</b> <code>{sl_str}</code> (+{pct_sl:.2f}% Batas Atas)")
                lines.append(f"⚖️ <b>Risk/Reward Ratio:</b> 1 : {rrr}")

            lines.append(f"⏱️ <b>{time_wib}</b> | RSI: <b>{rsi_val}</b> | Vol: <b>{vol_ratio}</b>")
            lines.append(wr_badge)
            if sig.reasons:
                clean_reason = sig.reasons[0].split("(")[0].strip()
                lines.append(f"💡 <i>{html.escape(clean_reason)}</i>")

        else:
            # SELL Saham IDX / Exit
            lines.append(f"🔴 <b>SINYAL EXIT / JUAL: {display_ticker}</b> @ <b>{price_str}</b>")
            lines.append(f"📍 <b>Area Jual:</b> <code>{price_str}</code>")
            if sig.take_profit_price and sig.stop_loss_price:
                tp_str = format_currency(sig.take_profit_price, sig.ticker)
                sl_str = format_currency(sig.stop_loss_price, sig.ticker)
                rrr = sig.risk_reward_ratio or 1.5
                lines.append(f"🎯 TP Pengaman: <b>{tp_str}</b> | 🛑 SL: <b>{sl_str}</b> (RRR 1:{rrr})")

            lines.append(f"⏱️ <b>{time_wib}</b> | RSI: <b>{rsi_val}</b> | Vol: <b>{vol_ratio}</b>")
            lines.append(wr_badge)
            if sig.reasons:
                clean_reason = sig.reasons[0].split("(")[0].strip()
                lines.append(f"💡 <i>{html.escape(clean_reason)}</i>")

        return "\n".join(lines)

    async def _async_send_text(self, text: str, target_chat_id: Optional[str] = None) -> bool:
        """Mengirim pesan teks secara asinkron ke chat ID target atau default."""
        if not self.is_configured:
            logger.info(f"[SIMULASI TELEGRAM]\n{text}")
            return True

        bot = Bot(token=self.token)
        cid = str(target_chat_id or self.chat_id).strip()
        try:
            await bot.send_message(
                chat_id=cid,
                text=text,
                parse_mode=ParseMode.HTML,
            )
            logger.info(f"Pesan berhasil terkirim ke Telegram ({cid}).")
            return True
        except Exception as e:
            logger.error(f"Gagal mengirim pesan ke Telegram ({cid}): {e}")
            return False

    async def _async_send_photo(self, photo_path: str, caption: str, target_chat_id: Optional[str] = None) -> bool:
        """Mengirim file foto beserta caption ke Telegram dengan proteksi batas karakter caption."""
        if not self.is_configured:
            logger.info(f"[SIMULASI TELEGRAM PHOTO] {photo_path}\n{caption}")
            return True

        bot = Bot(token=self.token)
        cid = str(target_chat_id or self.chat_id).strip()
        try:
            safe_caption = caption
            overflow_text = None
            if len(caption) > 1020:
                safe_caption = caption[:1000] + "...\n<i>(Rincian lanjut di bawah)</i>"
                overflow_text = caption

            with open(photo_path, "rb") as photo:
                await bot.send_photo(
                    chat_id=cid,
                    photo=photo,
                    caption=safe_caption,
                    parse_mode=ParseMode.HTML,
                )
            if overflow_text:
                await bot.send_message(
                    chat_id=cid,
                    text=overflow_text,
                    parse_mode=ParseMode.HTML,
                )
            logger.info(f"Foto {photo_path} berhasil terkirim ke Telegram ({cid}).")
            return True
        except Exception as e:
            logger.error(f"Gagal mengirim foto ke Telegram ({cid}): {e}. Mencoba fallback ke pesan teks...")
            try:
                await bot.send_message(
                    chat_id=cid,
                    text=caption,
                    parse_mode=ParseMode.HTML,
                )
                return True
            except Exception as e2:
                logger.error(f"Fallback teks juga gagal: {e2}")
                return False

    def send_signal(self, sig: SignalResult, photo_path: Optional[str] = None) -> bool:
        """
        Mengirim kartu sinyal ke seluruh pengguna yang telah disetujui (Admin + Whitelist).
        """
        msg = self.format_signal_message(sig)
        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        success = True
        for cid in approved_ids:
            try:
                if photo_path and Path(photo_path).exists():
                    res = asyncio.run(self._async_send_photo(photo_path, msg, target_chat_id=cid))
                else:
                    res = asyncio.run(self._async_send_text(msg, target_chat_id=cid))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Error saat broadcast sinyal ke {cid}: {e}")
                success = False
        return success

    def format_news_alert_message(self, analysis: Dict[str, Any]) -> str:
        """Menyusun pesan notifikasi 10 menit sebelum berita rilis."""
        bull = analysis["bullish_scenario"]
        bear = analysis["bearish_scenario"]
        plan = analysis["straddle_plan"]
        news_type = analysis["news_type"]

        lines = [
            f"🚨 <b>ALERT 10 MENIT SEBELUM HIGH-IMPACT NEWS!</b> ⚠️",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"📢 <b>Event:</b> {html.escape(analysis['news_title'])} (<b>{news_type}</b>)",
            f"⏰ <b>Waktu Rilis:</b> <code>{analysis['date_wib']} WIB</code> (<b>~10 Menit Lagi!</b>)",
            f"📊 <b>Konsensus:</b> Forecast: <code>{analysis['forecast']}</code> | Prev: <code>{analysis['previous']}</code>",
            f"💵 <b>Harga Emas Saat Ini:</b> <code>${analysis['current_price']:,.2f}</code>",
            f"💥 <b>Estimasi Volatilitas:</b> ±{analysis['expected_volatility_pct']}% (±${analysis['expected_volatility_dollars']})",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🎯 <b>PROYEKSI 2 SKENARIO XAU/USD (GOLD):</b>",
            "",
            f"🟢 <b>1. SKENARIO PUMP (USD DROP):</b>",
            f"• <i>Kondisi:</i> {bull['condition']}",
            f"• 🎯 Target TP1: <code>${bull['target_tp1']:,.2f}</code> (+{bull['gain_tp1_pct']}%)",
            f"• 🎯 Target TP2: <code>${bull['target_tp2']:,.2f}</code> (+{bull['gain_tp2_pct']}%)",
            "",
            f"🔴 <b>2. SKENARIO DUMP (USD PUMP):</b>",
            f"• <i>Kondisi:</i> {bear['condition']}",
            f"• 🎯 Target TP1: <code>${bear['target_tp1']:,.2f}</code> (-{bear['loss_tp1_pct']}%)",
            f"• 🎯 Target TP2: <code>${bear['target_tp2']:,.2f}</code> (-{bear['loss_tp2_pct']}%)",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"⚡ <b>PANDUAN STRADDLE BREAKOUT PRE-NEWS:</b>",
            f"• 🟢 <b>Buy Stop:</b> <code>${plan['buy_stop']:,.2f}</code> (SL: ${plan['buy_sl']:,.2f})",
            f"• 🔴 <b>Sell Stop:</b> <code>${plan['sell_stop']:,.2f}</code> (SL: ${plan['sell_sl']:,.2f})",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💡 <i>Gunakan lot 50% lebih kecil karena spread berpotensi melebar saat rilis news!</i>",
        ]
        return "\n".join(lines)

    def send_news_alert(self, analysis: Dict[str, Any], photo_path: Optional[str] = None) -> bool:
        """Mengirimkan alert 10 menit sebelum berita rilis ke seluruh pengguna terotorisasi."""
        msg = self.format_news_alert_message(analysis)
        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        success = True
        for cid in approved_ids:
            try:
                if photo_path and Path(photo_path).exists():
                    res = asyncio.run(self._async_send_photo(photo_path, msg, target_chat_id=cid))
                else:
                    res = asyncio.run(self._async_send_text(msg, target_chat_id=cid))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Error saat broadcast news alert ke {cid}: {e}")
                success = False
        return success

    def send_message(self, text: str) -> bool:
        """Mengirim pesan teks biasa ke Telegram."""
        try:
            return asyncio.run(self._async_send_text(text))
        except Exception as e:
            logger.error(f"Error saat mengeksekusi send_message: {e}")
            return False


class TelegramBotCommands:
    """Handler perintah interaktif bot Telegram (/status, /watchlist, /lasthistory, dll)."""

    def __init__(self, storage: Optional[StockStorage] = None):
        self.storage = storage or StockStorage()
        self.config = load_config()
        self.admin_id = get_admin_id()

    def _is_admin(self, update: Update) -> bool:
        """Memeriksa apakah pengirim adalah Super Admin (berdasarkan Chat ID atau Username)."""
        if not update.effective_user:
            return False
        uid = str(update.effective_user.id).strip()
        uname = (update.effective_user.username or "").lower().lstrip("@")
        return (
            uid in [SUPERADMIN_CHAT_ID, "8754997836", self.admin_id]
            or uname in SUPERADMIN_USERNAMES
        )

    async def check_user_access(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """
        Memeriksa hak akses pengguna.
        Jika belum diizinkan, catat sebagai pending dan kirim notifikasi izin ke Admin.
        """
        if not update.effective_user or not update.message:
            return False

        user_id = str(update.effective_user.id).strip()
        user_name = update.effective_user.username or "-"
        full_name = update.effective_user.full_name or "Trader"

        # 1. Super Admin otomatis lolos (berdasarkan Chat ID 8754997836 atau username @selobrow)
        if self._is_admin(update):
            self.storage.approve_user(user_id)
            return True

        # 2. Cek apakah sudah disetujui di database
        if self.storage.is_user_authorized(user_id, admin_id=self.admin_id):
            return True

        # 3. User belum terdaftar / berstatus pending
        status = self.storage.register_or_get_user(
            chat_id=user_id,
            username=user_name,
            full_name=full_name,
        )

        if status == "rejected":
            await update.message.reply_html(
                "🚫 <b>Akses Ditolak</b>\n\n"
                "Maaf, akses Anda ke bot ini telah ditolak oleh Admin."
            )
            return False

        # Status 'pending'
        await update.message.reply_html(
            "🔒 <b>Akses Bot Dibatasi (Privat)</b>\n\n"
            "Halo! Bot ini memerlukan persetujuan dari Admin sebelum dapat digunakan.\n"
            "Permintaan akses Anda telah dikirimkan ke <b>Admin (@selobrow)</b>.\n\n"
            "⏳ <i>Mohon tunggu hingga Admin menyetujui akses Anda.</i>"
        )

        # Kirim alert izin ke Admin beserta tombol klik langsung
        target_admin = self.admin_id or SUPERADMIN_CHAT_ID
        if target_admin:
            admin_msg = (
                f"🔔 <b>PERMINTAAN AKSES PENGGUNA BARU:</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Nama:</b> {html.escape(full_name)}\n"
                f"💬 <b>Username:</b> @{html.escape(user_name)}\n"
                f"🆔 <b>Chat ID:</b> <code>{user_id}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<i>Klik salah satu tombol di bawah:</i>"
            )
            keyboard = [
                [
                    InlineKeyboardButton("✅ Izinkan (Approve)", callback_data=f"approve_{user_id}"),
                    InlineKeyboardButton("🚫 Tolak (Reject)", callback_data=f"reject_{user_id}"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await context.bot.send_message(
                    chat_id=target_admin,
                    text=admin_msg,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )
            except Exception as e:
                logger.error(f"Gagal kirim notif izin ke Admin: {e}")

        return False

    async def button_callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler klik tombol interaktif (Izinkan / Tolak) khusus Admin."""
        query = update.callback_query
        if not query:
            return
        await query.answer()

        if not self._is_admin(update):
            await query.answer("⛔ Hanya Admin yang berhak memproses akses.", show_alert=True)
            return

        data = query.data or ""
        msg_text = query.message.text or ""

        if data.startswith("approve_"):
            target_id = data.replace("approve_", "").strip()
            self.storage.approve_user(target_id)
            await query.edit_message_text(
                text=f"{msg_text}\n\n✅ <b>STATUS: DISETUJUI OLEH ADMIN</b> 🎉\nPengguna sekarang memiliki akses penuh ke bot.",
                parse_mode=ParseMode.HTML,
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="🎉 <b>Selamat! Permintaan akses Anda telah disetujui oleh Admin.</b>\nKetik /start untuk mulai menggunakan bot!",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.warning(f"Gagal kirim pesan approved ke {target_id}: {e}")

        elif data.startswith("reject_"):
            target_id = data.replace("reject_", "").strip()
            self.storage.reject_user(target_id)
            await query.edit_message_text(
                text=f"{msg_text}\n\n🚫 <b>STATUS: DITOLAK OLEH ADMIN</b>\nAkses pengguna ini telah diblokir.",
                parse_mode=ParseMode.HTML,
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="🚫 <b>Akses Ditolak</b>\nMaaf, permintaan akses Anda ke bot ini ditolak oleh Admin.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

    async def approve_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /approve <chat_id> khusus Admin."""
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Perintah ini hanya dapat dijalankan oleh Admin.")
            return

        if not context.args:
            await update.message.reply_html("⚠️ Format salah. Gunakan: <code>/approve &lt;chat_id&gt;</code>")
            return

        target_id = context.args[0].strip()
        success = self.storage.approve_user(target_id)
        if success:
            await update.message.reply_html(f"✅ <b>Pengguna {target_id} berhasil disetujui!</b>")
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="🎉 <b>Selamat! Akses Anda telah disetujui oleh Admin.</b>\nKetik /start untuk mulai menggunakan bot!",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.warning(f"Gagal notif ke {target_id}: {e}")
        else:
            await update.message.reply_text(f"Gagal menyetujui Chat ID {target_id}.")

    async def reject_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /reject <chat_id> khusus Admin."""
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Perintah ini hanya dapat dijalankan oleh Admin.")
            return

        if not context.args:
            await update.message.reply_html("⚠️ Format salah. Gunakan: <code>/reject &lt;chat_id&gt;</code>")
            return

        target_id = context.args[0].strip()
        self.storage.reject_user(target_id)
        await update.message.reply_html(f"🚫 <b>Pengguna {target_id} telah ditolak/dicabut.</b>")
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🚫 <b>Akses Ditolak</b>\nAdmin telah menolak atau mencabut akses Anda ke bot ini.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /users untuk melihat daftar pengguna (khusus Admin)."""
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Perintah ini hanya dapat dijalankan oleh Admin.")
            return

        users = self.storage.list_all_users()
        if not users:
            await update.message.reply_text("Belum ada pengguna lain yang meminta akses.")
            return

        lines = ["👥 <b>DAFTAR PENGGUNA BOT:</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
        for u in users:
            st = u.get("status", "pending")
            emoji = "🟢" if st == "approved" else "🔴" if st == "rejected" else "🟡"
            cid = u.get("chat_id", "-")
            name = u.get("full_name") or u.get("username") or "-"
            lines.append(f"{emoji} <b>{html.escape(name)}</b> (<code>{cid}</code>) - <i>{st.upper()}</i>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("👉 Ketik <code>/approve &lt;id&gt;</code> atau <code>/reject &lt;id&gt;</code>")
        await update.message.reply_html("\n".join(lines))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /start dan /help"""
        if not await self.check_user_access(update, context):
            return
        user_name = update.effective_user.first_name if update.effective_user else "Trader"
        welcome_lines = [
            f"👋 Halo <b>{html.escape(user_name)}</b>!",
            "",
            "Selamat datang di <b>IDX Stock & Gold Signal Bot</b> 🇮🇩🥇",
            "",
            "<b>🎯 Fitur & Perintah yang Dapat Anda Gunakan:</b>",
            "• /chart - Tampilkan live chart candlestick (Gold / Saham)",
            "• /potensi - Radar live chart saham & gold paling berpotensi",
            "• /harian - Rekomendasi sinyal trading harian (Entry, TP & SL)",
            "• /winrate - Statistik akurasi win & lose rate sinyal bot",
            "• /candle - Bedah pola candlestick & price action (7 buku)",
            "• /gold - Analisis & sinyal emas dunia XAU/USD (24 Jam)",
            "• /scan - Pindai seluruh saham potensial sekarang juga (On-Demand)",
            "• /watchlist - Lihat daftar saham potensial cuan & harga terkini",
            "• /status - Cek status bot & strategi aktif",
            "• /lasthistory - Tampilkan 5 riwayat sinyal terakhir",
            "• /help - Bantuan & panduan penggunaan bot",
        ]

        if self._is_admin(update):
            welcome_lines.extend([
                "",
                "👑 <b>Menu Khusus Pemilik / Super Admin:</b>",
                "• /users - Lihat daftar seluruh pengguna & status izin",
                "• /approve &lt;id&gt; - Izinkan akses pengguna baru",
                "• /reject &lt;id&gt; - Tolak / cabut akses pengguna",
            ])

        welcome_lines.extend([
            "",
            "<i>Bot ini berjalan otomatis memantau saham IDX dan komoditas emas dunia.</i>",
        ])
        await update.message.reply_html("\n".join(welcome_lines))

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /status untuk cek kondisi bot."""
        if not await self.check_user_access(update, context):
            return
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
        if not await self.check_user_access(update, context):
            return
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
        if not await self.check_user_access(update, context):
            return
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
        if not await self.check_user_access(update, context):
            return
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
        if not await self.check_user_access(update, context):
            return
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
        if not await self.check_user_access(update, context):
            return
        await update.message.reply_html("⏳ <i>Menganalisis pergerakan harga emas dunia Spot XAU/USD (TradingView / OANDA)...</i>")
        import asyncio
        from data.fetcher import DataFetcher
        from indicators.technical import TechnicalIndicators
        from strategy.rules import get_strategy, DEFAULT_STRATEGY
        from strategy.signal_engine import SignalEngine

        def _compute_gold():
            fetcher = DataFetcher(storage=self.storage)
            df = fetcher.get_data("XAUUSD", interval="15m", period="5d", force_fetch=True)
            if df.empty or len(df) < 15:
                df = fetcher.get_data("XAUUSD", interval="1h", period="1mo", force_fetch=True)
            if df.empty or len(df) < 15:
                return None

            df_ind = TechnicalIndicators.add_all_indicators(df)
            strategy = get_strategy("DayTrading_Intraday_Momentum") or DEFAULT_STRATEGY
            engine = SignalEngine([strategy])
            sig = engine.evaluate_bar(df_ind, ticker="XAUUSD", strategy=strategy)

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

            chart_path = None
            try:
                from notify.chart_generator import ChartGenerator
                chart_path = ChartGenerator.generate_chart(
                    df=df_ind,
                    ticker_symbol="XAUUSD",
                    interval="15m",
                    signal_type=sig.signal,
                    entry_price=last_close,
                    tp_price=tp_calc,
                    sl_price=sl_calc,
                    setup_grade=sig.setup_grade,
                    pdf_confluence_score=sig.pdf_confluence_score,
                )
            except Exception as e:
                logger.warning(f"Gagal generate chart di /gold: {e}")

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
                "chart_path": chart_path,
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

        caption_text = "\n".join(msg_lines)
        chart_path = data.get("chart_path")
        if chart_path and Path(chart_path).exists():
            safe_cap = caption_text if len(caption_text) <= 1020 else caption_text[:1000] + "..."
            try:
                with open(chart_path, "rb") as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption=safe_cap,
                        parse_mode=ParseMode.HTML,
                    )
                return
            except Exception as e:
                logger.warning(f"Gagal kirim foto gold: {e}")

        await update.message.reply_html(caption_text)

    async def candle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /candle <ticker> untuk analisis pola candlestick & price action dari 7 buku."""
        if not await self.check_user_access(update, context):
            return

        ticker_arg = context.args[0].upper().strip() if context.args else "XAUUSD"
        from data.fetcher import DataFetcher
        from indicators.technical import TechnicalIndicators
        import asyncio

        fetcher = DataFetcher(storage=self.storage)
        clean_ticker = fetcher.normalize_ticker(ticker_arg)
        is_gold = any(k in clean_ticker for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        disp_ticker = "XAU/USD (Gold)" if is_gold else clean_ticker.replace(".JK", "")

        await update.message.reply_html(f"🕯️ <i>Menganalisis pola candlestick & price action untuk <b>{disp_ticker}</b>...</i>")

        def _fetch_and_eval():
            interval = "15m"
            period = "5d" if is_gold else "60d"
            df = fetcher.get_data(clean_ticker, interval=interval, period=period, force_fetch=True if is_gold else False)
            if df.empty or len(df) < 15:
                df = fetcher.get_data(clean_ticker, interval="1d", period="1y", force_fetch=True if is_gold else False)
            if df.empty or len(df) < 15:
                return None
            df_ind = TechnicalIndicators.add_all_indicators(df)
            last_row = df_ind.iloc[-1]

            c_close = float(last_row["Close"])
            c_time = str(df_ind.index[-1])[5:16]

            pinbar = bool(last_row.get("pattern_pinbar", 0))
            engulfing = bool(last_row.get("pattern_engulfing", 0))
            wick_ratio = float(last_row.get("rejection_wick_ratio", 0.0)) * 100.0
            volman_pb = bool(last_row.get("volman_pullback", 0))
            volman_bd = bool(last_row.get("volman_buildup", 0))
            fib_gz = bool(last_row.get("fib_in_golden_zone", 0))
            ichi_cloud = bool(last_row.get("ichimoku_above_cloud", 0))
            rsi_val = float(last_row.get("rsi", 50.0))
            vol_ratio = float(last_row.get("volume_ratio", 1.0))

            return {
                "ticker": disp_ticker,
                "is_gold": is_gold,
                "close": c_close,
                "time": c_time,
                "pinbar": pinbar,
                "engulfing": engulfing,
                "wick_ratio": wick_ratio,
                "volman_pb": volman_pb,
                "volman_bd": volman_bd,
                "fib_gz": fib_gz,
                "ichi_cloud": ichi_cloud,
                "rsi": rsi_val,
                "vol_ratio": vol_ratio,
            }

        res = await asyncio.to_thread(_fetch_and_eval)
        if not res:
            await update.message.reply_text(f"Data tidak ditemukan atau feed sedang offline untuk {ticker_arg}.")
            return

        price_fmt = f"${res['close']:,.2f}" if res["is_gold"] else f"Rp {res['close']:,.0f}"
        lines = [
            f"🕯️ <b>BEDAH CANDLESTICK & PRICE ACTION: {res['ticker']}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>Harga Terkini:</b> <code>{price_fmt}</code> ({res['time']} WIB)",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📖 <b>POLA BUKU YANG TERDETEKSI:</b>",
            f"• <b>Pinbar Rejection:</b> {'🟢 YA (Ekor Penolakan Kuat)' if res['pinbar'] else f'⚪ Tidak (Ekor: {res['wick_ratio']:.0f}%)'}",
            f"• <b>Bullish Engulfing:</b> {'🟢 YA (Candle Menelan Penuh)' if res['engulfing'] else '⚪ Tidak'}",
            f"• <b>Bob Volman 20 EMA:</b> {'🟢 Pullback Reversal Terkonfirmasi' if res['volman_pb'] else '⚪ Normal'}",
            f"• <b>Bob Volman Buildup:</b> {'🔥 Kompresi Siap Breakout' if res['volman_bd'] else '⚪ Volatilitas Reguler'}",
            f"• <b>Fibonacci Golden Pocket:</b> {'🎯 Rebound di Area 50%-61.8%' if res['fib_gz'] else '⚪ Di luar Golden Zone'}",
            f"• <b>Ichimoku Kumo Cloud:</b> {'⛅ Bullish di Atas Awan' if res['ichi_cloud'] else '☁️ Di Bawah / Dalam Awan'}",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 <b>Konfirmasi Volume:</b> {res['vol_ratio']:.1f}x rata-rata | <b>RSI:</b> {res['rsi']:.1f}",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "💡 <i>Gunakan: <code>/candle BBCA</code>, <code>/candle BBRI</code>, atau <code>/candle GOLD</code></i>",
        ]
        await update.message.reply_html("\n".join(lines))

    async def winrate_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /winrate dan /performance untuk rekam jejak akurasi Win/Lose bot."""
        if not await self.check_user_access(update, context):
            return

        stats = self.storage.get_win_rate_stats()
        tot = stats["total_signals"]
        comp = stats["completed"]
        win = stats["win_count"]
        lose = stats["lose_count"]
        opn = stats["open_count"]
        wr = stats["win_rate"]
        lr = stats["lose_rate"]
        pnl = stats["total_pnl"]

        if comp >= 5 and wr >= 75.0:
            eval_note = "🔥 <b>Akurasi Luar Biasa!</b> Filter 7 buku PDF terbukti sangat akurat memprediksi market."
        elif comp >= 5 and wr >= 60.0:
            eval_note = "🟢 <b>Akurasi Sehat & Profitable.</b> Risk:Reward terjaga dengan baik."
        elif comp == 0:
            eval_note = f"⏳ Sinyal masih berjalan ({opn} posisi OPEN). Menunggu candle mencapai target TP / SL."
        else:
            eval_note = "⚠️ <b>Perlu Penyesuaian.</b> Kami terus memperketat filter konfluensi untuk menekan loss."

        g_stats = stats.get("gold_stats", {})
        idx_stats = stats.get("idx_stats", {})
        stars = "⭐" * min(5, max(1, int(wr / 20))) if comp > 0 else ""

        lines = [
            "📊 <b>STATISTIK AKURASI SINYAL (WIN / LOSE RATE)</b> 🏆",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🎯 <b>Win Rate Akurasi:</b> <code>{wr:.1f}%</code> {stars}",
            f"🛑 <b>Lose Rate:</b> <code>{lr:.1f}%</code>",
            f"💰 <b>Total Akumulasi PnL:</b> <code>{pnl:+.2f}%</code>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📈 <b>RINCIAN REKAM JEJAK:</b>",
            f"• <b>Total Sinyal:</b> {tot} sinyal",
            f"• <b>Sinyal Selesai:</b> {comp} trade (🟢 {win} Win | 🔴 {lose} Lose)",
            f"• <b>Posisi Berjalan (OPEN):</b> {opn} sinyal aktif",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "🥇 <b>Khusus Emas Dunia (XAU/USD):</b>",
            f"• Selesai: {g_stats.get('completed', 0)} trade (🟢 {g_stats.get('win', 0)}W | 🔴 {g_stats.get('lose', 0)}L)",
            f"• Win Rate Gold: <b>{g_stats.get('win_rate', 0.0):.1f}%</b>",
            "",
            "🇮🇩 <b>Khusus Saham Indonesia (IDX):</b>",
            f"• Selesai: {idx_stats.get('completed', 0)} trade (🟢 {idx_stats.get('win', 0)}W | 🔴 {idx_stats.get('lose', 0)}L)",
            f"• Win Rate Saham: <b>{idx_stats.get('win_rate', 0.0):.1f}%</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💡 <i>{eval_note}</i>",
        ]
        await update.message.reply_html("\n".join(lines))

    async def chart_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /chart <ticker> untuk menampilkan live candlestick chart (TradingView style)."""
        if not await self.check_user_access(update, context):
            return

        ticker_arg = context.args[0].upper().strip() if context.args else "XAUUSD"
        from data.fetcher import DataFetcher
        from indicators.technical import TechnicalIndicators
        from strategy.rules import get_strategy, DEFAULT_STRATEGY
        from strategy.signal_engine import SignalEngine
        from notify.chart_generator import ChartGenerator
        import asyncio

        fetcher = DataFetcher(storage=self.storage)
        clean_ticker = fetcher.normalize_ticker(ticker_arg)
        is_gold = any(k in clean_ticker for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        disp_ticker = "XAU/USD (Gold Spot)" if is_gold else clean_ticker.replace(".JK", "")

        await update.message.reply_html(f"📈 <i>Menyiapkan visual live chart untuk <b>{disp_ticker}</b>...</i>")

        def _generate():
            interval = "15m"
            period = "5d" if is_gold else "60d"
            df = fetcher.get_data(clean_ticker, interval=interval, period=period, force_fetch=True if is_gold else False)
            if df.empty or len(df) < 15:
                df = fetcher.get_data(clean_ticker, interval="1d", period="1y", force_fetch=True if is_gold else False)
            if df.empty or len(df) < 15:
                return None, None

            df_ind = TechnicalIndicators.add_all_indicators(df)
            strategy = get_strategy("DayTrading_Intraday_Momentum") or DEFAULT_STRATEGY
            engine = SignalEngine([strategy])
            sig = engine.evaluate_bar(df_ind, ticker=clean_ticker, strategy=strategy)

            chart_path = ChartGenerator.generate_chart(
                df=df_ind,
                ticker_symbol=clean_ticker,
                interval=interval,
                signal_type=sig.signal,
                entry_price=sig.price,
                tp_price=sig.take_profit_price,
                sl_price=sig.stop_loss_price,
                setup_grade=sig.setup_grade,
                pdf_confluence_score=sig.pdf_confluence_score,
            )
            return chart_path, sig

        chart_path, sig = await asyncio.to_thread(_generate)
        if not chart_path or not Path(chart_path).exists():
            await update.message.reply_text(f"Gagal mengambil data pasar atau membuat chart untuk {ticker_arg}.")
            return

        price_fmt = f"${sig.price:,.2f}" if is_gold else f"Rp {sig.price:,.0f}"
        tp_str = f"${sig.take_profit_price:,.2f}" if is_gold and sig.take_profit_price else f"Rp {sig.take_profit_price:,.0f}" if sig.take_profit_price else "-"
        sl_str = f"${sig.stop_loss_price:,.2f}" if is_gold and sig.stop_loss_price else f"Rp {sig.stop_loss_price:,.0f}" if sig.stop_loss_price else "-"

        caption_lines = [
            f"📈 <b>LIVE CANDLESTICK CHART: {disp_ticker}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>Harga Terkini:</b> <code>{price_fmt}</code>",
            f"🎯 <b>Target TP:</b> <code>{tp_str}</code> | 🛑 <b>Batas SL:</b> <code>{sl_str}</code>",
        ]
        if sig.setup_grade:
            caption_lines.append(f"⭐ <b>Kualitas Setup:</b> Grade {sig.setup_grade} ({int((sig.pdf_confluence_score or 0)*100)}%)")
        if sig.market_direction_prediction:
            caption_lines.append(f"🎯 <b>Prediksi Arah:</b> <i>{html.escape(sig.market_direction_prediction)}</i>")

        caption_lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        caption_lines.append("💡 <i>Ketik /potensi untuk melihat chart saham & emas yang paling berpotensi.</i>")

        caption = "\n".join(caption_lines)
        if len(caption) > 1020:
            caption = caption[:1020]

        try:
            with open(chart_path, "rb") as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )
        except Exception as e:
            logger.error(f"Gagal kirim chart photo: {e}")
            await update.message.reply_html(caption)

    async def potensi_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /potensi dan /radar untuk menyaring dan memunculkan live chart aset paling berpotensi."""
        if not await self.check_user_access(update, context):
            return

        await update.message.reply_html("🔍 <i>Memindai seluruh watchlist saham IDX & Gold untuk mencari setup paling berpotensi (7 Buku PDF)...</i>")

        from data.fetcher import DataFetcher
        from indicators.technical import TechnicalIndicators
        from strategy.rules import get_strategy, DEFAULT_STRATEGY
        from strategy.signal_engine import SignalEngine
        from notify.chart_generator import ChartGenerator
        import asyncio

        def _scan_potentials():
            cfg = load_config()
            watchlist = cfg.get("watchlist", ["XAUUSD", "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "ASII.JK", "TLKM.JK"])
            fetcher = DataFetcher(storage=self.storage)
            strategy = get_strategy("DayTrading_Intraday_Momentum") or DEFAULT_STRATEGY
            engine = SignalEngine([strategy])

            potential_items = []
            for ticker in watchlist:
                is_gold = any(k in ticker.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
                interval = "15m"
                period = "5d" if is_gold else "60d"
                try:
                    df = fetcher.get_data(ticker, interval=interval, period=period, force_fetch=True if is_gold else False)
                    if df.empty or len(df) < 15:
                        df = fetcher.get_data(ticker, interval="1d", period="1y", force_fetch=True if is_gold else False)
                    if df.empty or len(df) < 15:
                        continue

                    df_ind = TechnicalIndicators.add_all_indicators(df)
                    sig = engine.evaluate_bar(df_ind, ticker=ticker, strategy=strategy)
                    is_pot, reason_badge, reason_desc = ChartGenerator.evaluate_asset_potential(sig, df_ind)
                    if is_pot:
                        chart_path = ChartGenerator.generate_chart(
                            df=df_ind,
                            ticker_symbol=ticker,
                            interval=interval,
                            signal_type=sig.signal,
                            entry_price=sig.price,
                            tp_price=sig.take_profit_price,
                            sl_price=sig.stop_loss_price,
                            setup_grade=sig.setup_grade,
                            pdf_confluence_score=sig.pdf_confluence_score,
                        )
                        potential_items.append({
                            "ticker": ticker,
                            "is_gold": is_gold,
                            "signal": sig,
                            "badge": reason_badge,
                            "desc": reason_desc,
                            "chart_path": chart_path,
                        })
                except Exception as e:
                    logger.debug(f"Error scan potensi {ticker}: {e}")

            return potential_items

        results = await asyncio.to_thread(_scan_potentials)
        if not results:
            await update.message.reply_html(
                "⚪ <b>HASIL RADAR: BELUM ADA SETUP BERPOTENSI TINGGI</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Saat ini pergerakan harga saham & emas dunia sedang berada di fase konsolidasi / netral (belum memenuhi syarat Grade A/A+ dari 7 buku PDF).\n\n"
                "🛡️ <i>Sistem sengaja menahan agar Anda tidak entry di momen tanpa edge. Bot memantau setiap 15 menit.</i>"
            )
            return

        # Kirim notifikasi ringkasan
        await update.message.reply_html(
            f"🔥 <b>RADAR POTENSI: DITEMUKAN {len(results)} INSTRUMEN BERPOTENSI!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Mengirimkan visual live chart lengkap dengan target Entry, TP & SL...</i>"
        )

        for item in results[:3]:
            sig = item["signal"]
            t = item["ticker"]
            is_gold = item["is_gold"]
            disp_ticker = "XAU/USD (Gold Spot)" if is_gold else t.replace(".JK", "")
            price_fmt = f"${sig.price:,.2f}" if is_gold else f"Rp {sig.price:,.0f}"
            tp_fmt = f"${sig.take_profit_price:,.2f}" if is_gold and sig.take_profit_price else f"Rp {sig.take_profit_price:,.0f}" if sig.take_profit_price else "-"
            sl_fmt = f"${sig.stop_loss_price:,.2f}" if is_gold and sig.stop_loss_price else f"Rp {sig.stop_loss_price:,.0f}" if sig.stop_loss_price else "-"

            caption = (
                f"🎯 <b>POTENSI: {disp_ticker}</b>\n"
                f"📌 <b>Setup:</b> {item['badge']}\n"
                f"💵 <b>Entry:</b> <code>{price_fmt}</code> | 🎯 <b>TP:</b> <code>{tp_fmt}</code> | 🛑 <b>SL:</b> <code>{sl_fmt}</code>\n"
                f"💡 <i>{html.escape(item['desc'])}</i>"
            )
            if len(caption) > 1020:
                caption = caption[:1020]

            c_path = item["chart_path"]
            if c_path and Path(c_path).exists():
                try:
                    with open(c_path, "rb") as photo:
                        await update.message.reply_photo(
                            photo=photo,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                        )
                except Exception as e:
                    logger.error(f"Gagal kirim foto potensi {t}: {e}")
                    await update.message.reply_html(caption)
            else:
                await update.message.reply_html(caption)

    async def chat_message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler pesan teks percakapan natural (bahasa gaul) & permintaan live chart instan."""
        if not await self.check_user_access(update, context):
            return

        if not update.message or not update.message.text:
            return

        user_text = update.message.text.strip()
        user_name = update.effective_user.first_name if update.effective_user else "Bor"

        from notify.chat_agent import ChatAgent
        classification = ChatAgent.classify_intent(user_text)
        intent = classification.get("intent", "CHITCHAT")
        target_ticker = classification.get("ticker")

        # 1. Intent CHART: Pengguna meminta live chart suatu instrumen
        if intent == "CHART":
            target_ticker = target_ticker or "XAUUSD"
            from data.fetcher import DataFetcher
            from indicators.technical import TechnicalIndicators
            from strategy.rules import get_strategy, DEFAULT_STRATEGY
            from strategy.signal_engine import SignalEngine
            from notify.chart_generator import ChartGenerator
            import asyncio

            fetcher = DataFetcher(storage=self.storage)
            clean_ticker = fetcher.normalize_ticker(target_ticker)
            is_gold = any(k in clean_ticker for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
            disp_ticker = "XAU/USD (Gold Spot)" if is_gold else clean_ticker.replace(".JK", "")

            await update.message.reply_html(f"Siap {user_name}! 🚀 Tunggu bentar, gue lagi ambilin live candle & bikinin chart buat <b>{disp_ticker}</b>...")

            def _generate():
                interval = "15m"
                period = "5d" if is_gold else "60d"
                df = fetcher.get_data(clean_ticker, interval=interval, period=period, force_fetch=True if is_gold else False)
                if df.empty or len(df) < 15:
                    df = fetcher.get_data(clean_ticker, interval="1d", period="1y", force_fetch=True if is_gold else False)
                if df.empty or len(df) < 15:
                    return None, None

                df_ind = TechnicalIndicators.add_all_indicators(df)
                strategy = get_strategy("DayTrading_Intraday_Momentum") or DEFAULT_STRATEGY
                engine = SignalEngine([strategy])
                sig = engine.evaluate_bar(df_ind, ticker=clean_ticker, strategy=strategy)

                chart_path = ChartGenerator.generate_chart(
                    df=df_ind,
                    ticker_symbol=clean_ticker,
                    interval=interval,
                    signal_type=sig.signal,
                    entry_price=sig.price,
                    tp_price=sig.take_profit_price,
                    sl_price=sig.stop_loss_price,
                    setup_grade=sig.setup_grade,
                    pdf_confluence_score=sig.pdf_confluence_score,
                )
                return chart_path, sig

            chart_path, sig = await asyncio.to_thread(_generate)
            if not chart_path or not Path(chart_path).exists():
                await update.message.reply_text(f"Waduh bor, data chart untuk {disp_ticker} lagi ga bisa diakses nih dari bursa/feed. Coba beberapa saat lagi ya!")
                return

            caption = ChatAgent.generate_chart_caption(
                ticker=clean_ticker,
                price=sig.price,
                tp_price=sig.take_profit_price,
                sl_price=sig.stop_loss_price,
                setup_grade=sig.setup_grade,
                pdf_confluence_score=sig.pdf_confluence_score,
                prediction=sig.market_direction_prediction,
            )
            if len(caption) > 1020:
                caption = caption[:1020]

            try:
                with open(chart_path, "rb") as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption=caption,
                        parse_mode=ParseMode.HTML,
                    )
            except Exception as e:
                logger.error(f"Gagal kirim chart photo via chat: {e}")
                await update.message.reply_html(caption)
            return

        # 2. Intent POTENSI: Pengguna meminta info saham/emas yang sedang berpotensi
        if intent == "POTENSI":
            await self.potensi_command(update, context)
            return

        # 3. Intent GOLD: Pengguna menanyakan seputar emas
        if intent == "GOLD":
            await self.gold_command(update, context)
            return

        # 4. Intent WINRATE: Pengguna menanyakan winrate / akurasi
        if intent == "WINRATE":
            await self.winrate_command(update, context)
            return

        # 5. Intent HARIAN: Pengguna menanyakan rekomendasi harian
        if intent == "HARIAN":
            await self.harian_command(update, context)
            return

        # 6. Intent WATCHLIST: Pengguna menanyakan daftar watchlist
        if intent == "WATCHLIST":
            await self.watchlist_command(update, context)
            return

        # 7. Intent NEWS: Pengguna menanyakan jadwal news atau prediksi FOMC/CPI/NFP
        if intent == "NEWS":
            await self.news_command(update, context)
            return

        # 8. Intent STATUS, GREETING, THANKS, CHITCHAT
        reply_text = ChatAgent.generate_chat_response(intent=intent, user_name=user_name)
        await update.message.reply_html(reply_text)

    async def news_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /news untuk melihat jadwal berita besar (FOMC, CPI, NFP) & proyeksi XAU/USD."""
        if not await self.check_user_access(update, context):
            return

        from data.economic_calendar import EconomicCalendar
        from strategy.news_predictor import NewsPredictor
        from data.fetcher import DataFetcher
        import asyncio

        await update.message.reply_html("📅 <i>Memeriksa kalender ekonomi & jadwal rilis FOMC, CPI, NFP...</i>")

        def _fetch_news():
            cal = EconomicCalendar(storage=self.storage)
            cal.sync_calendar()
            events = cal.get_this_week_schedule()

            fetcher = DataFetcher(storage=self.storage)
            df_gold = fetcher.get_data("XAUUSD", interval="15m", period="5d", force_fetch=True)
            live_price = float(df_gold["Close"].iloc[-1]) if not df_gold.empty else 4300.0

            closest_analysis = None
            chart_path = None
            if events:
                closest_ev = events[0]
                closest_analysis = NewsPredictor.analyze_pre_news(closest_ev, live_gold_price=live_price, df_gold=df_gold)
                chart_path = NewsPredictor.generate_pre_news_chart(closest_analysis, df=df_gold)

            return events, closest_analysis, chart_path, live_price

        events, closest_analysis, chart_path, live_price = await asyncio.to_thread(_fetch_news)

        if not events:
            await update.message.reply_html(
                "📅 <b>JADWAL HIGH-IMPACT NEWS:</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Tidak ada jadwal berita High Impact (FOMC, CPI, NFP) dalam beberapa hari ke depan.\n"
                "Pasar cenderung bergerak dengan dominasi analisa teknikal murni."
            )
            return

        lines = [
            "📅 <b>JADWAL 3 BERITA BESAR BULANAN (FOMC / CPI / NFP)</b> 🌎",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>Harga Live XAU/USD:</b> <code>${live_price:,.2f}</code>",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]

        for idx, ev in enumerate(events[:5], 1):
            ntype = ev.get("news_type", "NEWS")
            badge = "🔴 FOMC" if ntype == "FOMC" else "🟠 CPI" if ntype == "CPI" else "🟣 NFP" if ntype == "NFP" else "⚪ NEWS"
            t_wib = ev.get("date_wib", "-")
            fc = ev.get("forecast") or "-"
            pv = ev.get("previous") or "-"
            lines.append(f"<b>{idx}. {badge}</b>: <b>{html.escape(ev.get('title', ''))}</b>")
            lines.append(f"   ⏰ Waktu: <code>{t_wib} WIB</code>")
            lines.append(f"   📊 Forecast: <code>{fc}</code> | Prev: <code>{pv}</code>")
            lines.append("──────────────────────")

        if closest_analysis:
            bull = closest_analysis["bullish_scenario"]
            bear = closest_analysis["bearish_scenario"]
            lines.extend([
                f"🎯 <b>PROYEKSI EVENT TERDEKAT ({closest_analysis['news_type']}):</b>",
                f"• 🟢 <b>Bullish Gold:</b> Target ${bull['target_tp1']:,.2f} s/d ${bull['target_tp2']:,.2f}",
                f"• 🔴 <b>Bearish Gold:</b> Target ${bear['target_tp1']:,.2f} s/d ${bear['target_tp2']:,.2f}",
                "━━━━━━━━━━━━━━━━━━━━━━",
                "⚡ <i>Sistem otomatis membunyikan Alert & Live Chart 10 menit sebelum rilis!</i>",
            ])

        caption = "\n".join(lines)
        if chart_path and Path(chart_path).exists():
            safe_cap = caption if len(caption) <= 1020 else caption[:1000] + "..."
            try:
                with open(chart_path, "rb") as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption=safe_cap,
                        parse_mode=ParseMode.HTML,
                    )
                return
            except Exception as e:
                logger.error(f"Gagal kirim chart news: {e}")

        await update.message.reply_html(caption)


async def set_menu_commands(application: Application) -> None:
    """Mendaftarkan tombol Menu perintah interaktif di aplikasi Telegram."""
    from telegram import BotCommand
    commands = [
        BotCommand("chart", "📈 Live Candlestick Chart (Gold / Saham)"),
        BotCommand("potensi", "🔥 Radar Live Chart Paling Berpotensi"),
        BotCommand("news", "📰 Jadwal & Prediksi Pre-News (FOMC/CPI/NFP)"),
        BotCommand("harian", "🎯 Rekomendasi Sinyal Trading Harian (TP & SL)"),
        BotCommand("winrate", "📊 Statistik Akurasi Win / Lose Rate Bot"),
        BotCommand("candle", "🕯️ Bedah Pola Candlestick & Price Action"),
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
    app.add_handler(CommandHandler(["chart", "grafik", "livechart"], cmd_handler.chart_command))
    app.add_handler(CommandHandler(["potensi", "radar", "topsetup"], cmd_handler.potensi_command))
    app.add_handler(CommandHandler(["news", "fomc", "cpi", "nfp", "kalender"], cmd_handler.news_command))
    app.add_handler(CommandHandler(["harian", "tradingharian", "daytrade"], cmd_handler.harian_command))
    app.add_handler(CommandHandler(["winrate", "performance", "akurasi"], cmd_handler.winrate_command))
    app.add_handler(CommandHandler(["candle", "candlestick", "pola"], cmd_handler.candle_command))
    app.add_handler(CommandHandler(["gold", "xau", "emas"], cmd_handler.gold_command))
    app.add_handler(CommandHandler("status", cmd_handler.status_command))
    app.add_handler(CommandHandler("scan", cmd_handler.scan_command))
    app.add_handler(CommandHandler("watchlist", cmd_handler.watchlist_command))
    app.add_handler(CommandHandler("lasthistory", cmd_handler.lasthistory_command))
    app.add_handler(CommandHandler("approve", cmd_handler.approve_command))
    app.add_handler(CommandHandler("reject", cmd_handler.reject_command))
    app.add_handler(CommandHandler("users", cmd_handler.users_command))
    app.add_handler(CallbackQueryHandler(cmd_handler.button_callback_handler))
    # Handler pesan teks bebas (ngobrol santai & permintaan live chart otomatis)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_handler.chat_message_handler))

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
