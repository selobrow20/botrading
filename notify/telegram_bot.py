import os
import re
import asyncio
import html
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
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


def get_tradingview_url(ticker: str) -> str:
    """Mengembalikan URL interaktif TradingView resmi untuk simbol terkait."""
    t_clean = (ticker or "").upper().replace(".JK", "").strip()
    if any(k in t_clean for k in ["XAU", "GOLD", "EMAS", "GC=F"]):
        return "https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD"
    if t_clean.isalpha() and len(t_clean) <= 5:
        return f"https://www.tradingview.com/chart/?symbol=IDX%3A{t_clean}"
    return f"https://www.tradingview.com/chart/?symbol={t_clean}"


class TelegramNotifier:
    """Modul pengirim notifikasi sinyal ke Telegram via Bot API."""

    get_tradingview_url = staticmethod(get_tradingview_url)

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
        if is_gold:
            g_stats = wr_stats.get("gold_stats", {})
            g_comp = g_stats.get("completed", 0)
            wr_badge = f"📊 <b>Akurasi Emas (Gold):</b> Win Rate <b>{g_stats.get('win_rate', 0.0):.1f}%</b> ({g_stats.get('win', 0)}W / {g_stats.get('lose', 0)}L)" if g_comp > 0 else "📊 <b>Akurasi Emas:</b> <i>Sedang aktif melacak sinyal</i>"
        else:
            wr_badge = ""

        def _get_grade_and_score():
            raw_grade = getattr(sig, "setup_grade", "") or "Grade A"
            clean_g = re.sub(r"^(Grade\s*)+", "", str(raw_grade).strip(), flags=re.IGNORECASE).strip()
            g_str = f"Grade {clean_g}" if clean_g else "Grade A"
            raw_s = float(getattr(sig, "pdf_confluence_score", 0.0) or 0.0)
            if raw_s > 100.0:
                raw_s /= 100.0
            s_val = min(100, max(0, int(round(raw_s if raw_s > 1.0 else raw_s * 100.0))))
            return g_str, s_val

        lines = []

        if sig.signal == "BUY":
            lines.append(f"🟢 <b>SINYAL ENTRY (MASUK / BUY): {display_ticker}</b>")
            if getattr(sig, "is_retest_entry", False):
                r_det = getattr(sig, "retest_details", "") or "Area Support"
                lines.append(f"🎯 <b>Metode Entry:</b> 🔄 <b>Retest Diskon (Bawah)</b> - <code>{html.escape(r_det)}</code>")
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
            if wr_badge:
                lines.append(wr_badge)

            # Telaah 9 Buku PDF untuk Sinyal Masuk
            pdf_details = getattr(sig, "pdf_confluence_details", [])
            if pdf_details:
                grade_str, score_val = _get_grade_and_score()
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
                lines.append(f"📚 <b>TELAAH 9 BUKU PDF ({grade_str} - {score_val}%):</b>")
                for chk in pdf_details[:5]:
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
            if getattr(sig, "is_retest_entry", False):
                r_det = getattr(sig, "retest_details", "") or "Area Resisten"
                lines.append(f"🎯 <b>Metode Entry:</b> 🔄 <b>Retest Premium (Atas)</b> - <code>{html.escape(r_det)}</code>")
            lines.append(f"📍 <b>Harga Entry Short:</b> <code>{price_str}</code>")
            if sig.take_profit_price and sig.stop_loss_price:
                tp_str = format_currency(sig.take_profit_price, sig.ticker)
                sl_str = format_currency(sig.stop_loss_price, sig.ticker)
                rrr = sig.risk_reward_ratio or 2.0
                pct_tp = ((sig.price - sig.take_profit_price) / max(sig.price, 0.01)) * 100.0
                pct_sl = ((sig.stop_loss_price - sig.price) / max(sig.price, 0.01)) * 100.0
                lines.append(f"🎯 <b>Take Profit (TP):</b> <code>{tp_str}</code> (-{pct_tp:.2f}% Target Bawah)")
                lines.append(f"🛑 <b>Stop Loss (SL):</b> <code>{sl_str}</code> (+{pct_sl:.2f}% Batas Atas)")
                lines.append(f"⚖️ <b>Risk/Reward Ratio:</b> 1 : {rrr}")

            lines.append(f"⏱️ <b>{time_wib}</b> | RSI: <b>{rsi_val}</b> | Vol: <b>{vol_ratio}</b>")
            if wr_badge:
                lines.append(wr_badge)

            pdf_details = getattr(sig, "pdf_confluence_details", [])
            if pdf_details:
                grade_str, score_val = _get_grade_and_score()
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
                lines.append(f"📚 <b>TELAAH 9 BUKU PDF ({grade_str} - {score_val}%):</b>")
                for chk in pdf_details[:5]:
                    lines.append(f"• {html.escape(chk)}")
                pred = getattr(sig, "market_direction_prediction", "")
                if pred:
                    lines.append(f"🎯 <b>Prediksi Arah:</b> <i>{html.escape(pred)}</i>")
            elif sig.reasons:
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
            if wr_badge:
                lines.append(wr_badge)

            pdf_details = getattr(sig, "pdf_confluence_details", [])
            if pdf_details:
                grade_str, score_val = _get_grade_and_score()
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
                lines.append(f"📚 <b>TELAAH 9 BUKU PDF ({grade_str} - {score_val}%):</b>")
                for chk in pdf_details[:4]:
                    lines.append(f"• {html.escape(chk)}")
            elif sig.reasons:
                clean_reason = sig.reasons[0].split("(")[0].strip()
                lines.append(f"💡 <i>{html.escape(clean_reason)}</i>")

        # Tampilkan status eksekusi Auto-Trade MT5 jika ada
        mt5_notes = [r for r in (sig.reasons or []) if "Auto-Trade MT5" in r]
        if mt5_notes:
            lines.append("━━━━━━━━━━━━━━━━━━━━━━")
            for mn in mt5_notes:
                lines.append(f"<b>{html.escape(mn)}</b>")

        return "\n".join(lines)

    async def _async_send_text(
        self,
        text: str,
        target_chat_id: Optional[str] = None,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> bool:
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
                reply_markup=reply_markup,
            )
            logger.info(f"Pesan berhasil terkirim ke Telegram ({cid}).")
            return True
        except Exception as e:
            logger.error(f"Gagal mengirim pesan ke Telegram ({cid}): {e}")
            return False

    async def _async_send_photo(
        self,
        photo_path: str,
        caption: str,
        target_chat_id: Optional[str] = None,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> bool:
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
                cut_idx = caption.rfind("\n", 0, 950)
                if cut_idx == -1:
                    cut_idx = 950
                safe_caption = caption[:cut_idx] + "...\n<i>(Rincian lanjut di bawah)</i>"
                overflow_text = caption[cut_idx:].strip()

            with open(photo_path, "rb") as photo:
                await bot.send_photo(
                    chat_id=cid,
                    photo=photo,
                    caption=safe_caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )
            if overflow_text:
                await bot.send_message(
                    chat_id=cid,
                    text=overflow_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
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
                    reply_markup=reply_markup,
                )
                return True
            except Exception as e2:
                logger.error(f"Fallback teks juga gagal: {e2}")
                return False

    async def _async_send_document(
        self,
        doc_path: str,
        caption: str = "",
        target_chat_id: Optional[str] = None,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> bool:
        """Mengirim file dokumen (misal .zip copier) ke chat target via Telegram Bot API."""
        if not self.is_configured:
            logger.info(f"[SIMULASI TELEGRAM DOC] {doc_path}\n{caption}")
            return True

        bot = Bot(token=self.token)
        cid = str(target_chat_id or self.chat_id).strip()
        try:
            safe_caption = caption
            overflow_text = None
            if len(caption) > 1020:
                cut_idx = caption.rfind("\n", 0, 950)
                if cut_idx == -1:
                    cut_idx = 950
                safe_caption = caption[:cut_idx] + "...\n<i>(Rincian lanjut di bawah)</i>"
                overflow_text = caption[cut_idx:].strip()

            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    with open(doc_path, "rb") as doc_file:
                        await bot.send_document(
                            chat_id=cid,
                            document=doc_file,
                            filename=Path(doc_path).name,
                            caption=safe_caption,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup,
                            read_timeout=30.0,
                            write_timeout=30.0,
                            connect_timeout=20.0,
                        )
                    if overflow_text:
                        await bot.send_message(
                            chat_id=cid,
                            text=overflow_text,
                            parse_mode=ParseMode.HTML,
                            read_timeout=20.0,
                        )
                    logger.info(f"Dokumen {doc_path} berhasil terkirim ke Telegram ({cid}).")
                    return True
                except Exception as ex_attempt:
                    if attempt < max_retries:
                        logger.warning(f"Percobaan {attempt+1} kirim dokumen ke {cid} gagal ({ex_attempt}). Mencoba lagi...")
                        await asyncio.sleep(2)
                    else:
                        raise ex_attempt
        except Exception as e:
            logger.error(f"Gagal mengirim dokumen ke Telegram ({cid}): {e}")
            return False

    def send_document(
        self,
        doc_path: str,
        caption: str = "",
        target_chat_id: Optional[str] = None,
    ) -> bool:
        """Mengirim file dokumen (misal .zip copier) ke chat target via Telegram Bot API."""
        try:
            return asyncio.run(self._async_send_document(doc_path, caption=caption, target_chat_id=target_chat_id))
        except Exception as e:
            logger.error(f"Error saat mengeksekusi send_document: {e}")
            return False

    def broadcast_copier_update(
        self,
        zip_path: str = "member_copier.zip",
        custom_caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Mengirim file zip auto-copier terbaru ke seluruh member aktif (approved & belum expired).
        """
        p = Path(zip_path)
        if not p.is_absolute():
            from config.settings import BASE_DIR
            p = BASE_DIR / zip_path

        if not p.exists():
            logger.error(f"File zip copier tidak ditemukan di {p}")
            return {"success": False, "sent_count": 0, "recipients": [], "error": f"File {p} tidak ditemukan."}

        caption = custom_caption or (
            "📦 <b>UPDATE AUTO-COPIER MT5 (VIP 9 BUKU PDF)</b> 🚀\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Halo Trader VIP! Master merilis pembaruan Auto-Copier MT5.\n\n"
            "✨ <b>FITUR & LOGIKA BARU:</b>\n"
            "1. 🎯 <b>Retest Entry (Diskon/Premium):</b> Entry posisi terbaik di ayunan bawah/atas S/R & Order Block.\n"
            "2. ⚖️ <b>Min TP/SL 60 Pips (1:1):</b> Target terkunci minimal 60 pips ($6.00 USD), TP >= SL.\n"
            "3. 🏛️ <b>Konfirmasi H1 London & Anti-Judas Swing:</b> Filter manipulasi likuiditas sesi London.\n"
            "4. ⚡ <b>Fast Impulsive Reversal & Auto-Flip:</b> Cut loss dini & membalik arah instan.\n"
            "5. 🛡️ <b>Anti-Hedging & Auto Filling Mode:</b> Kompatibel FOK/IOC/RETURN (bebas error 10030).\n\n"
            "🔄 <b>FITUR AUTO-UPDATE OTOMATIS:</b>\n"
            "Bagi member yang aplikasinya sedang berjalan, sistem otomatis mengunduh & me-restart sendiri (bebas repot timpa ZIP)!\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )

        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        try:
            with self.storage._get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT chat_id FROM authorized_users WHERE status = 'approved'")
                db_ids = [str(r["chat_id"]).strip() for r in c.fetchall()]
        except Exception:
            db_ids = []

        target_ids = list(dict.fromkeys(approved_ids + db_ids + [self.chat_id, SUPERADMIN_CHAT_ID]))

        sent_recipients = []
        failed_recipients = []

        for cid in target_ids:
            try:
                res = asyncio.run(self._async_send_document(str(p), caption=caption, target_chat_id=cid))
                if res:
                    sent_recipients.append(cid)
                else:
                    failed_recipients.append(cid)
            except Exception as e:
                logger.error(f"Error saat mengirim file copier ke {cid}: {e}")
                failed_recipients.append(cid)

        return {
            "success": len(sent_recipients) > 0,
            "sent_count": len(sent_recipients),
            "failed_count": len(failed_recipients),
            "recipients": sent_recipients,
            "failed": failed_recipients,
        }

    def send_signal(self, sig: SignalResult, photo_path: Optional[str] = None) -> bool:
        """
        Mengirim kartu sinyal ke seluruh pengguna yang telah disetujui (Admin + Whitelist).
        Dilengkapi tombol interaktif langsung menuju live chart TradingView.
        """
        msg = self.format_signal_message(sig)
        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        tv_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Buka di TradingView", url=get_tradingview_url(sig.ticker))
        ]])

        success = True
        for cid in approved_ids:
            try:
                if photo_path and Path(photo_path).exists():
                    res = asyncio.run(self._async_send_photo(photo_path, msg, target_chat_id=cid, reply_markup=tv_markup))
                else:
                    res = asyncio.run(self._async_send_text(msg, target_chat_id=cid, reply_markup=tv_markup))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Error saat broadcast sinyal ke {cid}: {e}")
                success = False
        return success

    def format_tp_sl_report(
        self, res_sig: Dict[str, Any], current_stats: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Menyusun pesan laporan Telegram ketika sinyal menyentuh Take Profit (TP) atau Stop Loss (SL),
        lengkap dengan evaluasi, rincian PnL, dan statistik akurasi Win Rate terkini.
        """
        ticker = res_sig.get("ticker", "UNKNOWN")
        is_gold = any(k in ticker.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        display_ticker = "XAU/USD (Gold)" if is_gold else ticker.replace(".JK", "")

        outcome = res_sig.get("outcome", "WIN")
        is_win = (outcome == "WIN")
        sig_type = res_sig.get("signal_type", "BUY")

        entry_p = float(res_sig.get("price") or res_sig.get("entry_price") or 0.0)
        exit_p = float(res_sig.get("exit_price") or 0.0)
        tp_p = float(res_sig.get("take_profit_price") or 0.0)
        sl_p = float(res_sig.get("stop_loss_price") or 0.0)
        pnl_pct = float(res_sig.get("pnl_pct") or 0.0)

        # Koreksi otomatis: Jika harga keluar menguntungkan atau PnL positif, status MUTLAK WIN (bukan LOSE!)
        if (sig_type == "BUY" and exit_p > entry_p) or (sig_type == "SELL" and exit_p < entry_p) or pnl_pct > 0:
            is_win = True
            outcome = "WIN"

        entry_str = format_currency(entry_p, ticker)
        exit_str = format_currency(exit_p, ticker)
        tp_str = format_currency(tp_p, ticker) if tp_p else "-"
        sl_str = format_currency(sl_p, ticker) if sl_p else "-"

        candle_time = res_sig.get("candle_time", "-")
        exit_time = res_sig.get("exit_time", "-")
        note = res_sig.get("outcome_note", "")
        note_upper = (note or "").upper()
        is_trailing_win = is_win and ("TRAILING" in note_upper or "BEP" in note_upper)

        stats = current_stats or self.storage.get_win_rate_stats()
        # Selaras dengan instruksi pengguna: Win rate hanya khusus XAU/USD (Gold).
        # Seluruh tampilan win rate disatukan menjadi 1 versi konsisten berbasis performa Gold.
        if is_gold and "gold_stats" in stats:
            g_stats = stats.get("gold_stats", {})
            wr = g_stats.get("win_rate", 0.0)
            win_c = g_stats.get("win", 0)
            lose_c = g_stats.get("lose", 0)
            total_pnl = g_stats.get("total_pnl", 0.0)
        else:
            wr = stats.get("win_rate", 0.0)
            win_c = stats.get("win_count", 0)
            lose_c = stats.get("lose_count", 0)
            total_pnl = stats.get("total_pnl", 0.0)

        is_early_close = is_win and ("DIAMANKAN LEBIH AWAL" in note_upper or "SEBELUM TARGET" in note_upper or "REVERSAL GUARD" in note_upper or "EARLY TP" in note_upper)

        if is_win:
            if is_trailing_win:
                header = "🎯 <b>[LAPORAN HASIL] PROFIT TERKUNCI (TRAILING STOP / BEP)!</b> 🛡️"
                outcome_badge = "🟢 <b>HASIL: WIN / PROFIT TERKUNCI</b>"
            elif is_early_close:
                header = "🛡️ <b>[LAPORAN HASIL] PROFIT DIAMANKAN LEBIH AWAL!</b> 💰"
                outcome_badge = "🟢 <b>HASIL: WIN / DIAMANKAN LEBIH AWAL</b>"
            else:
                header = "🎯 <b>[LAPORAN HASIL] TAKE PROFIT TERCAPAI!</b> 🚀"
                outcome_badge = "🟢 <b>HASIL: WIN / PROFIT MAKSIMAL</b>"
            pnl_badge = f"💰 <b>Keuntungan (PnL):</b> <code>+{abs(pnl_pct):.2f}%</code>"
        else:
            header = "🛑 <b>[LAPORAN HASIL] STOP LOSS TERSENTUH!</b> ⚠️"
            outcome_badge = "🔴 <b>HASIL: LOSE / PROTEKSI MODAL</b>"
            pnl_badge = f"📉 <b>Kerugian (PnL):</b> <code>-{abs(pnl_pct):.2f}%</code>"

        action_label = "BUY / LONG" if sig_type == "BUY" else "SELL / SHORT" if is_gold else "SELL / EXIT"

        lines = [
            header,
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 <b>Instrumen:</b> <code>{display_ticker}</code>",
            f"⚡ <b>Aksi Sinyal:</b> <b>{action_label}</b>",
            outcome_badge,
            pnl_badge,
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📌 <b>RINCIAN LEVEL HARGA:</b>",
            f"• <b>Harga Entry:</b> <code>{entry_str}</code>",
            f"• <b>Harga Keluar / Hit:</b> <code>{exit_str}</code>",
            f"• <b>Target TP:</b> <code>{tp_str}</code>",
            f"• <b>Stop Loss:</b> <code>{sl_str}</code>",
            f"• <b>Waktu Entry:</b> {candle_time}",
            f"• <b>Waktu Tercapai:</b> {exit_time}",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📝 <b>KETERANGAN & EVALUASI:</b>",
            f"<i>{html.escape(note)}</i>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📊 <b>UPDATE STATISTIK AKURASI (WIN RATE):</b>",
            f"🎯 <b>Win Rate Sekarang:</b> <code>{wr:.1f}%</code> ({win_c}W / {lose_c}L)",
            f"💰 <b>Total Akumulasi PnL:</b> <code>{total_pnl:+.2f}%</code>",
        ]

        if is_win:
            lines.append("🏆 <i>Setup konfluensi 9 buku PDF terbukti akurat mengunci profit!</i>")
        else:
            lines.append("🛡️ <i>Disiplin Stop Loss berhasil mencegah risiko kerugian lebih besar. Modal tetap aman!</i>")

        return "\n".join(lines)

    def send_tp_sl_report(self, res_sig: Dict[str, Any]) -> bool:
        """
        Mengirimkan kartu laporan hasil TP/SL ke seluruh pengguna Telegram yang disetujui.
        """
        msg = self.format_tp_sl_report(res_sig)
        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        tv_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Buka di TradingView", url=get_tradingview_url(res_sig.get("ticker", "XAUUSD")))
        ]])

        success = True
        for cid in approved_ids:
            try:
                res = asyncio.run(self._async_send_text(msg, target_chat_id=cid, reply_markup=tv_markup))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Error saat broadcast laporan TP/SL ke {cid}: {e}")
                success = False
        return success

    def format_mt5_execution_report(self, order_info: Dict[str, Any]) -> str:
        """
        Menyusun kartu laporan resmi Telegram saat order MT5 berhasil dieksekusi real-time.
        """
        ticket = order_info.get("ticket", "-")
        action = order_info.get("action", "BUY")
        symbol = order_info.get("symbol", "XAUUSDc")
        volume = float(order_info.get("volume", 0.01))
        price = float(order_info.get("price", 0.0))
        tp = float(order_info.get("tp", 0.0))
        sl = float(order_info.get("sl", 0.0))
        score = float(order_info.get("score", 0.0))
        grade = str(order_info.get("grade", "Grade A"))
        lot_badge = "🔥 <b>MOMEN BAGUS BANGET (0.05 LOT)</b>" if volume >= 0.05 else "🛡️ <b>STANDAR / PENGAMAN (0.01 LOT)</b>"
        action_icon = "🟢" if action == "BUY" else "🔴"
        action_label = "BUY / LONG" if action == "BUY" else "SELL / SHORT"

        lines = [
            "🤖 <b>[LAPORAN EKSEKUSI] ORDER MT5 TERPASANG!</b> ⚡",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🎫 <b>Ticket ID:</b> <code>#{ticket}</code>",
            f"📊 <b>Instrumen:</b> <code>{symbol} (Gold)</code>",
            f"{action_icon} <b>Aksi Order:</b> <b>{action_label}</b>",
            f"📦 <b>Volume:</b> <code>{volume:.2f} Lot</code> ({lot_badge})",
            f"💵 <b>Harga Masuk:</b> <code>${price:,.2f}</code>",
            f"🎯 <b>Take Profit (TP):</b> <code>${tp:,.2f}</code>",
            f"🛑 <b>Stop Loss (SL):</b> <code>${sl:,.2f}</code>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"⭐ <b>Konfluensi 9 PDF:</b> {score:.0f}% ({grade})",
            "🛡️ <i>Order diproteksi SL & TP otomatis. Terhubung langsung ke MT5 akun Anda!</i>",
        ]
        return "\n".join(lines)

    def send_mt5_execution_report(self, order_info: Dict[str, Any]) -> bool:
        """
        Mengirim kartu konfirmasi eksekusi order MT5 ke seluruh pengguna Telegram.
        """
        msg = self.format_mt5_execution_report(order_info)
        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        success = True
        for cid in approved_ids:
            try:
                res = asyncio.run(self._async_send_text(msg, target_chat_id=cid))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Error kirim laporan eksekusi MT5 ke {cid}: {e}")
                success = False
        return success

    def format_gold_reversal_alert(self, info: Dict[str, Any]) -> str:
        """
        Menyusun kartu alert saat terdeteksi pembalikan tren XAU/USD
        dan sistem melakukan Ambil Untung Otomatis (Early Take Profit) di MT5.
        """
        ticket = info.get("ticket", "-")
        action = info.get("action", "SELL")
        symbol = info.get("symbol", "XAUUSD")
        volume = float(info.get("volume", 0.05))
        entry_p = float(info.get("entry_price", 0.0))
        exit_p = float(info.get("exit_price", 0.0))
        profit_usd = float(info.get("profit_usd", 0.0))
        pnl_pct = float(info.get("pnl_pct", 0.0))
        reversal_type = info.get("reversal_type", "Pembalikan Tren Terdeteksi")
        reasons = info.get("reasons", [])
        cooldown_mins = int(info.get("cooldown_mins", 45))
        is_profit = profit_usd >= 0

        title_icon = "🎯 [AMBIL UNTUNG OTOMATIS]" if is_profit else "🛡️ [PENGAMANAN AWAL]"
        pnl_icon = "🟢 PROFIT DIKUNCI" if is_profit else "🔴 CUT LOSS DINI"
        pnl_sign = "+" if profit_usd >= 0 else ""
        action_icon = "🔴 SELL" if action == "SELL" else "🟢 BUY"

        lines = [
            f"⚡ <b>{title_icon} XAU/USD REVERSAL GUARD!</b> ⚡",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🎫 <b>Ticket ID:</b> <code>#{ticket}</code>",
            f"📊 <b>Instrumen:</b> <code>{symbol} (Gold Spot)</code>",
            f"📦 <b>Posisi Ditutup:</b> <b>{action_icon} {volume:.2f} Lot</b>",
            f"💵 <b>Harga Masuk:</b> <code>${entry_p:,.2f}</code> ➔ <b>Keluar:</b> <code>${exit_p:,.2f}</code>",
            f"💰 <b>Hasil Realisasi:</b> <code>{pnl_sign}${profit_usd:,.2f} USD ({pnl_sign}{pnl_pct:+.2f}%)</code> [{pnl_icon}]",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "⚠️ <b>100% PEMBALIKAN TREN TERKONFIRMASI:</b>",
            f"<i>{reversal_type}</i>",

        ]
        for r in reasons[:4]:
            lines.append(f"• {r}")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        if cooldown_mins > 0:
            lines.extend([
                f"⏸️ <b>Proteksi Trading:</b> Bot masuk mode <b>JEDA / OBSERVASI ({cooldown_mins} Menit)</b> agar keuntungan tidak tergerus pembalikan pasar.",
                "💡 <i>Ketik /mt5 untuk melihat ringkasan atau /mt5 resume untuk melanjutkan trading.</i>",
            ])
        else:
            lines.extend([
                "⚡ <b>Status Auto-Trader:</b> <b>STANDBY REAL-TIME (Tanpa Jeda)</b>",
                "🎯 <i>Momen berikutnya siap dieksekusi: Begitu muncul sinyal Grade A+ baru dari 9 Buku PDF, bot langsung GAS masuk lagi!</i>",
            ])
        return "\n".join(lines)


    def send_gold_reversal_alert(self, info: Dict[str, Any]) -> bool:
        """
        Mengirimkan notifikasi Ambil Untung Otomatis karena pembalikan tren ke Telegram.
        """
        msg = self.format_gold_reversal_alert(info)
        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        tv_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Buka Live Chart TradingView", url=get_tradingview_url("XAUUSD"))
        ]])

        success = True
        for cid in approved_ids:
            try:
                res = asyncio.run(self._async_send_text(msg, target_chat_id=cid, reply_markup=tv_markup))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Error kirim alert reversal XAUUSD ke {cid}: {e}")
                success = False
        return success

    def format_early_reversal_warning(self, info: Dict[str, Any]) -> str:
        ticket = info.get("ticket", "-")
        action = info.get("action", "BUY")
        symbol = info.get("symbol", "XAUUSD")
        volume = float(info.get("volume", 0.05))
        entry_p = float(info.get("entry_price", 0.0))
        curr_p = float(info.get("current_price", 0.0))
        score = float(info.get("score", 45.0))
        reasons = info.get("reasons", [])
        action_icon = "🟢 BUY" if action == "BUY" else "🔴 SELL"
        target_dir = "SELL / SHORT 📉" if action == "BUY" else "BUY / LONG 🚀"

        lines = [
            "⚠️ <b>PERINGATAN DINI PEMBALIKAN ARAH TREN (XAU/USD)!</b> ⚠️",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🎫 <b>Posisi Aktif:</b> <code>#{ticket}</code> ({action_icon} {volume:.2f} Lot)",
            f"💵 <b>Harga Masuk:</b> <code>${entry_p:,.2f}</code> ➔ <b>Live:</b> <code>${curr_p:,.2f}</code>",
            f"🔄 <b>Potensi Berbalik Arah Ke:</b> <b>{target_dir}</b>",
            f"📊 <b>Skor Indikasi Awal:</b> <b>{score:.0f}%</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "🔍 <b>Sinyal Awal Terdeteksi (9 Buku PDF):</b>",
        ]
        for r in reasons[:4]:
            lines.append(f"• {r}")

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━",
            "💡 <b>Status Tindakan Sistem:</b>",
            "• Posisi saat ini <b>MASIH DIBIARKAN BERJALAN</b>.",
            "• Bot dalam status <b>SIAGA PENGAWALAN</b> memantau candle berikutnya.",
            "• Jika pembalikan arah <b>100% TERKONFIRMASI</b>, bot baru akan otomatis mengamankan posisi / switch arah.",
        ])
        return "\n".join(lines)

    def send_early_reversal_warning(self, info: Dict[str, Any]) -> bool:
        """Mengirimkan notifikasi peringatan dini pembalikan tren ke Telegram."""
        msg = self.format_early_reversal_warning(info)
        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        tv_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Buka Live Chart TradingView", url=get_tradingview_url("XAUUSD"))
        ]])

        success = True
        for cid in approved_ids:
            try:
                res = asyncio.run(self._async_send_text(msg, target_chat_id=cid, reply_markup=tv_markup))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Error kirim early reversal warning ke {cid}: {e}")
                success = False
        return success

    def format_trailing_stop_alert(self, info: Dict[str, Any]) -> str:
        ticket = info.get("ticket", "-")
        action = info.get("action", "BUY")
        symbol = info.get("symbol", "XAUUSD")
        volume = float(info.get("volume", 0.05))
        price_open = float(info.get("price_open", 0.0))
        price_curr = float(info.get("price_curr", 0.0))
        new_sl = float(info.get("new_sl", 0.0))
        profit_dist = float(info.get("profit_dist", 0.0))
        alert_type = info.get("type", "BEP_LOCK")

        is_bep = alert_type == "BEP_LOCK"
        title_icon = "🛡️ [BREAK-EVEN PROTECTION AKTIF]" if is_bep else "📈 [TRAILING STOP NAIK - PROFIT TERKUNCI]"
        action_icon = "🟢 BUY" if action == "BUY" else "🔴 SELL"

        if is_bep:
            badge = "FREE TRADE (TRANSAKSI BEBAS RISIKO)"
            desc = (
                f"Harga telah bergerak menguntungkan <b>+{profit_dist:,.2f} USD</b> (+{int(profit_dist*10)} pips) dari harga masuk.\n"
                f"Stop Loss berhasil digeser ke <b>${new_sl:,.2f}</b> (di atas entry).\n"
                f"✅ <b>Modal Anda 100% terlindungi. Transaksi tidak akan pernah rugi!</b>"
            )
        else:
            badge = "PROFIT DIKUNCI SECARA DINAMIS"
            desc = (
                f"Harga terus melesat menguntungkan <b>+{profit_dist:,.2f} USD</b> (+{int(profit_dist*10)} pips)!\n"
                f"Stop Loss dinaikkan mengikuti tren ke <b>${new_sl:,.2f}</b>.\n"
                f"💰 <b>Akumulasi profit telah aman terkunci mengawal lari harga menuju TP!</b>"
            )

        lines = [
            f"⚡ <b>{title_icon}</b> ⚡",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🎫 <b>Ticket ID:</b> <code>#{ticket}</code>",
            f"📊 <b>Instrumen:</b> <code>{symbol} (Gold Spot)</code>",
            f"📦 <b>Posisi:</b> <b>{action_icon} {volume:.2f} Lot</b>",
            f"💵 <b>Harga Entry:</b> <code>${price_open:,.2f}</code> ➔ <b>Harga Live:</b> <code>${price_curr:,.2f}</code>",
            f"🛡️ <b>SL Pengaman Baru:</b> <code>${new_sl:,.2f}</code>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🎖️ <b>Status Proteksi:</b> <b>{badge}</b>",
            desc,
        ]
        return "\n".join(lines)

    def send_trailing_stop_alert(self, info: Dict[str, Any]) -> bool:
        """Mengirimkan notifikasi BEP Lock / Trailing Stop ke Telegram."""
        msg = self.format_trailing_stop_alert(info)
        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        tv_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Buka Live Chart TradingView", url=get_tradingview_url("XAUUSD"))
        ]])

        success = True
        for cid in approved_ids:
            try:
                res = asyncio.run(self._async_send_text(msg, target_chat_id=cid, reply_markup=tv_markup))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Error kirim trailing stop alert ke {cid}: {e}")
                success = False
        return success

    def send_circuit_breaker_alert(self, loss_today: float, max_loss: float, unit: str = "USC") -> bool:
        """Mengirimkan peringatan darurat saat batas maksimal kerugian harian tercapai."""
        msg = (
            f"🚨 <b>PERINGATAN PENGAMANAN: CIRCUIT BREAKER AKTIF!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ <b>Total Kerugian Hari Ini:</b> <code>-{loss_today:.2f} {unit}</code>\n"
            f"🛑 <b>Batas Maksimal Toleransi:</b> <code>{max_loss:.2f} {unit}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>Tindakan Otomatis Bot:</b>\n"
            f"• Seluruh eksekusi order baru <b>DIHENTIKAN SEMENTARA</b> demi melindungi sisa modal trading Anda saat server aktif semalaman.\n"
            f"• Posisi aktif yang sedang berjalan tetap dikawal disiplin oleh TP & SL.\n"
            f"• Bot akan otomatis mereset batas risiko pada awal sesi perdagangan berikutnya.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>Kaidah 9 Buku PDF: Melindungi modal adalah prioritas nomor satu. Istirahat sejenak adalah bagian dari disiplin trading.</i>"
        )
        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        success = True
        for cid in approved_ids:
            try:
                res = asyncio.run(self._async_send_text(msg, target_chat_id=cid))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Error kirim circuit breaker alert ke {cid}: {e}")
                success = False
        return success

    def send_midnight_guard_alert(self, loss_midnight: float, max_loss: float, unit: str = "USC") -> bool:
        """Mengirimkan peringatan saat batas kerugian jam tidur tengah malam (02:00 - 04:30 WIB) tercapai."""
        msg = (
            f"🌙 <b>PENGAMANAN TIDUR MALAM: MIDNIGHT SLEEP GUARD AKTIF!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ <b>Kerugian Sesi Tengah Malam:</b> <code>-{loss_midnight:.2f} {unit}</code>\n"
            f"🛑 <b>Batas Maksimal Jam Tidur (02:00 - 04:30 WIB):</b> <code>{max_loss:.2f} {unit}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>Tindakan Otomatis Bot:</b>\n"
            f"• Eksekusi transaksi baru <b>DIKUNCI SEMENTARA</b> hingga sesi pagi.\n"
            f"• Melindungi saldo dari ombak sideways & likuiditas tipis dini hari saat Anda beristirahat.\n"
            f"• Saat Anda bangun dan memantau di siang hari, batas harian USC otomatis bebas kembali.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>Kaidah 9 Buku PDF: Di jam sepi likuiditas malam, lebih baik tidur tenang menjaga modal daripada memaksakan trading di pasar berombak.</i>"
        )
        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        success = True
        for cid in approved_ids:
            try:
                res = asyncio.run(self._async_send_text(msg, target_chat_id=cid))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Error kirim midnight guard alert ke {cid}: {e}")
                success = False
        return success

    def format_market_close_summary(
        self,
        watchlist_data: List[Dict[str, Any]],
        date_str: Optional[str] = None,
    ) -> str:
        """
        Menyusun Laporan Penutupan Pasar Saham (BEI) yang ringkas, simpel, dan padat.
        """
        now = datetime.now()
        day_names = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
        day_wib = day_names[now.weekday()]
        date_wib = date_str or f"{day_wib}, {now.strftime('%d/%m/%Y')}"

        lines = [
            "🔔 <b>LAPORAN PENUTUPAN PASAR SAHAM (BEI)</b> 🇮🇩",
            f"📅 <b>{date_wib} | Sesi 2 Selesai (16:00 WIB)</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📊 <b>Performa Watchlist Hari Ini:</b>",
        ]

        if not watchlist_data:
            lines.append("• <i>Data ringkasan saham hari ini belum tersedia.</i>")
        else:
            for item in watchlist_data[:8]:
                t = item.get("ticker", "").replace(".JK", "")
                price = float(item.get("close") or item.get("price") or 0.0)
                chg = float(item.get("change_pct") or 0.0)
                icon = "🟢" if chg > 0 else "🔴" if chg < 0 else "⚪"
                chg_str = f"+{chg:.1f}%" if chg > 0 else f"{chg:.1f}%"
                lines.append(f"{icon} <b>{t}:</b> Rp {price:,.0f} (<code>{chg_str}</code>)")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📌 <b>Status:</b> Pasar BEI resmi ditutup. Posisi terpantau aman.")
        lines.append("💡 <i>Ketik /potensi untuk memantau radar saham besok pagi.</i>")

        return "\n".join(lines)

    def send_market_close_report(self, watchlist_data: List[Dict[str, Any]]) -> bool:
        """Mengirimkan laporan penutupan pasar saham ringkas ke seluruh pengguna terdaftar."""
        msg = self.format_market_close_summary(watchlist_data)
        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        success = True
        for cid in approved_ids:
            try:
                res = asyncio.run(self._async_send_text(msg, target_chat_id=cid))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Gagal kirim laporan penutupan saham ke {cid}: {e}")
                success = False
        return success

    def format_news_alert_message(self, analysis: Dict[str, Any]) -> str:
        """Menyusun pesan notifikasi 10 menit sebelum berita rilis dengan rekomendasi BUY/SELL berbasis PDF & Web."""
        bull = analysis["bullish_scenario"]
        bear = analysis["bearish_scenario"]
        plan = analysis["straddle_plan"]
        news_type = analysis["news_type"]
        rec = analysis.get("primary_recommendation", "BUY")
        conf = analysis.get("confidence_pct", 75)
        setup = analysis.get("trade_setup", {})
        fund = analysis.get("fundamental_bias", {})
        tech = analysis.get("technical_bias", {})

        badge_emoji = "🟢" if "BUY" in rec else "🔴" if "SELL" in rec else "🟡"
        action_name = "BUY / LONG 🚀" if "BUY" in rec else "SELL / SHORT 📉" if "SELL" in rec else "STRADDLE BREAKOUT ⚡"
        # Hitung estimasi menit tersisa secara dinamis
        try:
            now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))
            clean_date = analysis['date_wib'].split("+")[0].strip()
            ev_dt = datetime.strptime(clean_date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Jakarta"))
            diff_secs = (ev_dt - now_wib).total_seconds()
            diff_mins = max(1, int(round(diff_secs / 60.0)))
            time_badge = f"(<b>~{diff_mins} Menit Lagi!</b>)"
        except Exception:
            time_badge = "(<b>~10 Menit Lagi!</b>)"

        lines = [
            f"🚨 <b>ALERT PRE-NEWS: REKOMENDASI TRADING XAU/USD (GOLD)</b> ⚠️",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"📢 <b>Event:</b> {html.escape(analysis['news_title'])} (<b>{news_type}</b>)",
            f"⏰ <b>Waktu Rilis:</b> <code>{analysis['date_wib']} WIB</code> {time_badge}",
            f"💵 <b>Harga Emas Saat Ini:</b> <code>${analysis['current_price']:,.2f}</code>",
            f"💥 <b>Estimasi Volatilitas:</b> ±{analysis['expected_volatility_pct']}% (±${analysis['expected_volatility_dollars']})",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🎯 <b>SARAN UTAMA BOT (PDF & WEB DATA):</b>",
            f"{badge_emoji} <b>REKOMENDASI: {html.escape(rec)}</b>",
            f"📊 <b>Probabilitas Keberhasilan:</b> <code>{conf}% High Confidence</code>",
            "",
            f"📍 <b>RENCANA EKSEKUSI TRADING:</b>",
            f"• 🎯 <b>Aksi:</b> <code>{action_name}</code>",
            f"• 📌 <b>Area Entry:</b> <code>${setup.get('entry_price', analysis['current_price']):,.2f}</code>",
            f"• 🎯 <b>Take Profit 1:</b> <code>${setup.get('tp1', 0):,.2f}</code>",
            f"• 🎯 <b>Take Profit 2 (Runner):</b> <code>${setup.get('tp2', 0):,.2f}</code>",
            f"• 🛑 <b>Stop Loss Pengaman:</b> <code>${setup.get('sl', 0):,.2f}</code>",
            f"• ⚖️ <b>Risk to Reward:</b> <code>1:{setup.get('risk_reward_ratio', 2.0)}</code>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🧠 <b>DASAR ANALISIS & KONFLUENSI:</b>",
            f"🌐 <b>1. Data Kalender Web (Forex Factory):</b>",
            f"• <i>Forecast: {analysis['forecast']} | Prev: {analysis['previous']}</i>",
            f"• <i>{html.escape(fund.get('reason', '-'))}</i>",
            "",
            f"📚 <b>2. Analisis Teknikal Buku PDF:</b>",
        ]

        tech_reasons = tech.get("reasons", [])
        if tech_reasons:
            for r in tech_reasons[:3]:
                lines.append(f"• <i>{html.escape(r)}</i>")
        else:
            lines.append("• <i>Teknikal Fibonacci Golden Pocket & Ichimoku Kumo Cloud selaras.</i>")

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"⚡ <b>OPSI CADANGAN PENDING ORDER (STRADDLE):</b>",
            f"• 🟢 <b>Buy Stop:</b> <code>${plan['buy_stop']:,.2f}</code> (SL: ${plan['buy_sl']:,.2f})",
            f"• 🔴 <b>Sell Stop:</b> <code>${plan['sell_stop']:,.2f}</code> (SL: ${plan['sell_sl']:,.2f})",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💡 <i>Tips: Gunakan lot 50% lebih kecil untuk mengantisipasi lonjakan spread saat detik-detik rilis news!</i>",
        ])
        return "\n".join(lines)

    def send_news_alert(self, analysis: Dict[str, Any], photo_path: Optional[str] = None) -> bool:
        """Mengirimkan alert 10 menit sebelum berita rilis ke seluruh pengguna terotorisasi."""
        msg = self.format_news_alert_message(analysis)
        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        tv_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Buka di TradingView", url=get_tradingview_url("XAUUSD"))
        ]])

        success = True
        for cid in approved_ids:
            try:
                if photo_path and Path(photo_path).exists():
                    res = asyncio.run(self._async_send_photo(photo_path, msg, target_chat_id=cid, reply_markup=tv_markup))
                else:
                    res = asyncio.run(self._async_send_text(msg, target_chat_id=cid, reply_markup=tv_markup))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Error saat broadcast news alert ke {cid}: {e}")
                success = False
        return success

    def format_chart_confirmation_message(self, info: Dict[str, Any]) -> str:
        """
        Menyusun pesan Sinyal Konfirmasi Chart A+ (Win Rate Tinggi / 100% Confluence 9 Buku PDF).
        Dilengkapi rincian entry, TP, SL minimal 60 pips 1:1, skor konfluensi, dan tombol interaktif eksekusi MT5.
        """
        ticker = info.get("ticker", "XAUUSD")
        action = info.get("action", "SELL").upper()
        price = float(info.get("price", 0.0))
        tp = float(info.get("tp", 0.0))
        sl = float(info.get("sl", 0.0))
        score = float(info.get("score", 100.0))
        grade = str(info.get("grade", "Grade A+ (Setup Sempurna ⭐⭐⭐⭐⭐)"))
        pred = str(info.get("prediction", ""))
        reasons = info.get("reasons", [])

        action_icon = "🟢" if action == "BUY" else "🔴"
        action_label = "BUY / LONG 🚀" if action == "BUY" else "SELL / SHORT 📉"
        action_badge = f"{action_icon} <b>{action_label}</b>"

        is_gold = any(k in ticker.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        display_ticker = "XAU/USD (Gold Spot)" if is_gold else ticker.replace(".JK", "")

        try:
            tz = ZoneInfo("Asia/Jakarta")
            time_wib = datetime.now(tz).strftime("%H:%M WIB")
        except Exception:
            time_wib = "WIB"

        lines = [
            f"⚡ <b>SINYAL KONFIRMASI CHART {action} (GRADE A+ ⭐⭐⭐⭐⭐)</b> ⚡",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 <b>Instrumen:</b> <code>{display_ticker}</code>",
            f"⏰ <b>Waktu Deteksi:</b> <code>{time_wib}</code>",
            f"💵 <b>Harga Live Saat Ini:</b> <code>${price:,.2f}</code>" if is_gold else f"💵 <b>Harga:</b> <code>Rp {price:,.0f}</code>",
            f"🎯 <b>Arah Prediksi Chart:</b> {action_badge}",
            f"🔥 <b>Win Rate / Skor Konfluensi:</b> <b>{score:.0f}%</b> (<code>{grade}</code>)",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📍 <b>Rencana Setup Posisi:</b>",
            f"• 🎯 <b>Take Profit (TP):</b> <code>${tp:,.2f}</code> (Minimal 60 Pips / 1:1)" if is_gold else f"• 🎯 <b>Take Profit:</b> <code>Rp {tp:,.0f}</code>",
            f"• 🛑 <b>Stop Loss (SL):</b> <code>${sl:,.2f}</code> (Minimal 60 Pips / 1:1)" if is_gold else f"• 🛑 <b>Stop Loss:</b> <code>Rp {sl:,.0f}</code>",
            f"• ⚖️ <b>Risk to Reward:</b> <code>1 : 1.0</code>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "🧠 <b>Telaah Analisis 9 Buku PDF:</b>",
        ]
        if pred:
            lines.append(f"• <i>{html.escape(pred)}</i>")
        if reasons:
            for r in reasons[:3]:
                lines.append(f"• <i>{html.escape(str(r))}</i>")
        else:
            lines.append("• <i>Konfluensi multi-timeframe 9 Buku PDF selaras sempurna.</i>")

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━",
            "💬 <i>Mau open posisi sekarang bor? Klik tombol di bawah buat langsung eksekusi di MT5!</i>",
        ])
        return "\n".join(lines)

    def send_chart_confirmation_alert(self, info: Dict[str, Any], photo_path: Optional[str] = None) -> bool:
        """
        Mengirimkan sinyal konfirmasi Chart A+ ke Telegram dengan inline keyboard eksekusi MT5.
        """
        msg = self.format_chart_confirmation_message(info)
        ticker = info.get("ticker", "XAUUSD")
        action = info.get("action", "SELL").upper()
        price = float(info.get("price", 0.0))
        tp = float(info.get("tp", 0.0))
        sl = float(info.get("sl", 0.0))

        # Inline Keyboard: Tombol Eksekusi MT5 + Tombol Buka TradingView
        btn_action = "BUY" if action == "BUY" else "SELL"
        exec_cb = f"exec_chart_{btn_action}_{ticker}_{price:.2f}_{tp:.2f}_{sl:.2f}"
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"⚡ Eksekusi {btn_action} di MT5 Sekarang", callback_data=exec_cb),
            ],
            [
                InlineKeyboardButton("📊 Buka Live Chart TradingView", url=get_tradingview_url(ticker)),
            ]
        ])

        approved_ids = self.storage.get_approved_chat_ids(admin_id=self.chat_id)
        if not approved_ids:
            approved_ids = [self.chat_id]

        success = True
        for cid in approved_ids:
            try:
                if photo_path and Path(photo_path).exists():
                    res = asyncio.run(self._async_send_photo(photo_path, msg, target_chat_id=cid, reply_markup=reply_markup))
                else:
                    res = asyncio.run(self._async_send_text(msg, target_chat_id=cid, reply_markup=reply_markup))
                if not res:
                    success = False
            except Exception as e:
                logger.error(f"Error kirim chart confirmation alert ke {cid}: {e}")
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
        self.notifier = TelegramNotifier(storage=self.storage)

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
            self.storage.approve_user(user_id, duration="lifetime")
            return True

        # 2. Cek apakah pengguna telah diblokir / dicabut aksesnya oleh Admin (SILENT DROP TOTAL)
        all_u = {u["chat_id"]: u for u in self.storage.list_all_users()}
        curr_u = all_u.get(user_id)
        if curr_u and curr_u.get("status") == "rejected":
            logger.info(f"🚫 [BLOKIR TOTAL] Pesan/perintah dari user rejected {user_id} ({full_name}) diabaikan total tanpa balasan.")
            return False

        # 3. Cek apakah sudah disetujui di database & belum expired
        if self.storage.is_user_authorized(user_id, admin_id=self.admin_id):
            return True

        # Cek apakah user sebelumnya approved tapi sudah kedaluwarsa
        if curr_u and curr_u.get("status") == "approved":
            exp_str = curr_u.get("expires_at", "")
            await update.message.reply_html(
                f"⏳ <b>Masa Aktif Akses Bot Anda Telah Berakhir</b>\n\n"
                f"Akses Anda berakhir pada: <code>{exp_str} WIB</code>.\n"
                f"Silakan hubungi <b>Admin (@selobrow)</b> untuk perpanjangan masa aktif bot! 🙏"
            )
            return False


        # 3. User belum terdaftar / berstatus pending
        status = self.storage.register_or_get_user(
            chat_id=user_id,
            username=user_name,
            full_name=full_name,
        )

        if status == "rejected":
            logger.info(f"🚫 [BLOKIR TOTAL] User terblokir {user_id} ({full_name}) diabaikan total tanpa balasan.")
            return False

        # Status 'pending'
        await update.message.reply_html(
            "🔒 <b>Akses Bot Dibatasi (Privat)</b>\n\n"
            "Halo! Bot ini memerlukan persetujuan dari Admin sebelum dapat digunakan.\n"
            "Permintaan akses Anda telah dikirimkan ke <b>Admin (@selobrow)</b>.\n\n"
            "⏳ <i>Mohon tunggu hingga Admin menyetujui akses Anda.</i>"
        )

        # Kirim alert izin ke Admin beserta pilihan tombol durasi (jam & hari)
        target_admin = self.admin_id or SUPERADMIN_CHAT_ID
        if target_admin:
            admin_msg = (
                f"🔔 <b>PERMINTAAN AKSES PENGGUNA BARU:</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Nama:</b> {html.escape(full_name)}\n"
                f"💬 <b>Username:</b> @{html.escape(user_name)}\n"
                f"🆔 <b>Chat ID:</b> <code>{user_id}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<i>Pilih durasi akses untuk pengguna ini:</i>"
            )
            keyboard = [
                [
                    InlineKeyboardButton("⏱️ 1 Jam (Trial)", callback_data=f"apprdur_{user_id}_1h"),
                    InlineKeyboardButton("⏱️ 6 Jam", callback_data=f"apprdur_{user_id}_6h"),
                ],
                [
                    InlineKeyboardButton("📅 1 Hari", callback_data=f"apprdur_{user_id}_1d"),
                    InlineKeyboardButton("📅 7 Hari", callback_data=f"apprdur_{user_id}_7d"),
                ],
                [
                    InlineKeyboardButton("📅 30 Hari", callback_data=f"apprdur_{user_id}_30d"),
                    InlineKeyboardButton("♾️ Permanen", callback_data=f"apprdur_{user_id}_lifetime"),
                ],
                [
                    InlineKeyboardButton("🚫 Tolak Akses", callback_data=f"reject_{user_id}"),
                ],
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

    async def _send_approved_welcome_and_copier(
        self, bot, target_id: str, dur_label: str, exp_display: str
    ) -> None:
        """Mengirim pesan ucapan selamat dan otomatis melampirkan file member_copier.zip terbaru."""
        from pathlib import Path

        welcome_text = (
            f"🎉 <b>Selamat! Permintaan akses Anda telah disetujui oleh Admin (@selobrow).</b>\n\n"
            f"⏱️ <b>Masa Aktif Lisensi:</b> <b>{dur_label}</b>\n"
            f"📅 <b>Berlaku s/d:</b> <code>{exp_display}</code>\n\n"
            f"Ketik /start untuk mulai menggunakan bot sinyal!"
        )
        try:
            await bot.send_message(
                chat_id=target_id,
                text=welcome_text,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(f"Gagal kirim pesan approved ke {target_id}: {e}")

        # Otomatis kirim file copier terbaru ke member agar langsung bisa trading tanpa error
        zip_path = Path(__file__).resolve().parent.parent / "member_copier.zip"
        if zip_path.exists():
            try:
                caption_text = (
                    "🚀 <b>FILE RESMI MT5 AUTO-COPIER (VIP 9 BUKU PDF)</b>\n\n"
                    "✅ <b>Fitur & Proteksi Terpasang:</b>\n"
                    "• Auto-Detect Filling Mode (FOK / IOC / RETURN - Bebas Error 10030)\n"
                    "• Handshake Lisensi Otomatis & Bersih (Bebas Spam Chat)\n"
                    "• Terkunci Resmi ke Akun Telegram Anda\n\n"
                    "<b>Petunjuk Menjalankan Copier:</b>\n"
                    "1. Unduh dan <b>Ekstrak</b> file ZIP ini di folder laptop/PC Anda.\n"
                    "2. Pastikan aplikasi <b>MetaTrader 5</b> Anda sudah login & terbuka.\n"
                    "3. Klik 2x file <b>START_COPIER.bat</b>.\n"
                    "4. Masukkan nomor HP Telegram Anda (awalan +62) & kode OTP (hanya 1x di awal).\n\n"
                    "<i>Copier otomatis standby dan siap menduplikasi sinyal 9 Buku PDF ke akun MT5 Anda!</i>"
                )
                with open(zip_path, "rb") as doc:
                    await bot.send_document(
                        chat_id=target_id,
                        document=doc,
                        caption=caption_text,
                        parse_mode=ParseMode.HTML,
                    )
                logger.info(f"Auto-dispatch member_copier.zip sukses dikirim ke member {target_id}")
            except Exception as e:
                logger.error(f"Gagal auto-dispatch member_copier.zip ke {target_id}: {e}")

    async def button_callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler klik tombol interaktif (Izinkan / Tolak / Durasi Akses) khusus Admin."""
        query = update.callback_query
        if not query:
            return
        data = query.data or ""
        msg_text = query.message.text or ""

        # Blokir total user yang telah di-kick / rejected
        cb_uid = str(query.from_user.id).strip() if query.from_user else ""
        if cb_uid:
            all_u = {u["chat_id"]: u for u in self.storage.list_all_users()}
            curr_u = all_u.get(cb_uid)
            if curr_u and curr_u.get("status") == "rejected":
                await query.answer("🚫 Akses Anda telah diblokir total oleh Admin.", show_alert=True)
                return

        # Chart style switching, candlestick, copier, dan eksekusi chart dapat diakses oleh semua pengguna yang terdaftar
        if not data.startswith(("chart_", "candle_", "copier_", "download_copier", "exec_chart_")) and not self._is_admin(update):
            await query.answer("⛔ Hanya Admin yang berhak memproses tindakan ini.", show_alert=True)
            return

        if data.startswith("apprdur_"):
            parts = data.split("_")
            target_id = parts[1]
            dur = parts[2] if len(parts) > 2 else "30d"
            success, expires_at, dur_label = self.storage.approve_user(target_id, dur)
            exp_display = expires_at if expires_at else "Permanen (Tanpa Batas Waktu)"

            manage_kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("➕ Tambah 30 Hari", callback_data=f"apprdur_{target_id}_30d"),
                    InlineKeyboardButton("♾️ Jadikan Permanen", callback_data=f"apprdur_{target_id}_lifetime"),
                ],
                [
                    InlineKeyboardButton("🛑 Cabut Akses (Kick)", callback_data=f"reject_{target_id}"),
                    InlineKeyboardButton("📦 Kirim Copier Zip", callback_data=f"sendzip_{target_id}"),
                ],
                [
                    InlineKeyboardButton("👥 Lihat Daftar Semua Member", callback_data="listusers"),
                ]
            ])

            base_txt = msg_text.split("✅ STATUS:")[0].split("🚫 STATUS:")[0].strip()
            await query.edit_message_text(
                text=f"{base_txt}\n\n✅ <b>STATUS: DISETUJUI ({dur_label})</b> 🎉\n"
                     f"⏱️ Masa Aktif: <code>{dur_label}</code>\n"
                     f"📅 Berlaku s/d: <code>{exp_display}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=manage_kb,
            )
            await self._send_approved_welcome_and_copier(context.bot, target_id, dur_label, exp_display)

        elif data.startswith("approve_"):
            target_id = data.replace("approve_", "").strip()
            success, expires_at, dur_label = self.storage.approve_user(target_id, "30d")
            exp_display = expires_at if expires_at else "Permanen (Tanpa Batas Waktu)"

            manage_kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("➕ Tambah 30 Hari", callback_data=f"apprdur_{target_id}_30d"),
                    InlineKeyboardButton("♾️ Jadikan Permanen", callback_data=f"apprdur_{target_id}_lifetime"),
                ],
                [
                    InlineKeyboardButton("🛑 Cabut Akses (Kick)", callback_data=f"reject_{target_id}"),
                    InlineKeyboardButton("📦 Kirim Copier Zip", callback_data=f"sendzip_{target_id}"),
                ]
            ])

            base_txt = msg_text.split("✅ STATUS:")[0].split("🚫 STATUS:")[0].strip()
            await query.edit_message_text(
                text=f"{base_txt}\n\n✅ <b>STATUS: DISETUJUI ({dur_label})</b> 🎉\n"
                     f"📅 Berlaku s/d: <code>{exp_display}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=manage_kb,
            )
            await self._send_approved_welcome_and_copier(context.bot, target_id, dur_label, exp_display)

        elif data.startswith("reject_"):
            target_id = data.replace("reject_", "").strip()
            self.storage.reject_user(target_id)
            restore_kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("♻️ Pulihkan Akses (30 Hari)", callback_data=f"apprdur_{target_id}_30d"),
                    InlineKeyboardButton("♾️ Pulihkan Permanen", callback_data=f"apprdur_{target_id}_lifetime"),
                ],
                [
                    InlineKeyboardButton("👥 Lihat Daftar Member", callback_data="listusers"),
                ]
            ])
            base_txt = msg_text.split("✅ STATUS:")[0].split("🚫 STATUS:")[0].strip()
            await query.edit_message_text(
                text=f"{base_txt}\n\n🚫 <b>STATUS: AKSES DICABUT / DITOLAK</b>\nAkses pengguna ini telah dinonaktifkan.",
                parse_mode=ParseMode.HTML,
                reply_markup=restore_kb,
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="🚫 <b>Akses Dicabut</b>\nMaaf, akses Anda ke bot ini telah dinonaktifkan oleh Admin.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=ReplyKeyboardRemove(),
                )
            except Exception:
                pass

        elif data.startswith("sendzip_"):
            target_id = data.replace("sendzip_", "").strip()
            from pathlib import Path
            zip_path = Path(__file__).resolve().parent.parent / "member_copier.zip"
            if zip_path.exists():
                try:
                    caption_text = (
                        "📦 <b>Halo! Berikut file VIP MT5 Auto-Copier untuk Anda.</b>\n\n"
                        "Ekstrak file ZIP ini di laptop/PC Anda, buka file <code>PANDUAN_MEMBER.txt</code>, "
                        "dan jalankan <code>START_COPIER.bat</code> untuk mulai copy trading otomatis!"
                    )
                    with open(zip_path, "rb") as doc:
                        await context.bot.send_document(
                            chat_id=target_id,
                            document=doc,
                            caption=caption_text,
                            parse_mode=ParseMode.HTML,
                        )
                    await query.answer("📦 File member_copier.zip berhasil dikirim ke member!", show_alert=True)
                except Exception as e:
                    await query.answer(f"❌ Gagal kirim file: {e}", show_alert=True)
            else:
                await query.answer("❌ File member_copier.zip tidak ditemukan di server.", show_alert=True)
            return

        elif data in ["copier_download", "download_copier_direct"]:
            from pathlib import Path
            zip_path = Path(__file__).resolve().parent.parent / "member_copier.zip"
            if not zip_path.exists():
                await query.answer("❌ File member_copier.zip belum tersedia di server.", show_alert=True)
                return
            await query.answer("📦 Mengirim paket Auto-Copier MT5...")
            caption_text = (
                "🚀 <b>PAKET AUTO-COPIER MT5 RESMI (VIP 9 BUKU PDF)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "✨ <b>Fitur Utama:</b> Retest Entry (Harga Diskon/Premium), SL/TP Minimal 60 Pips 1:1, Anti-Hedging, Auto-Flip.\n\n"
                "🛠️ <b>Petunjuk Cepat:</b> Ekstrak file ZIP ini di PC/Laptop/VPS Anda, jalankan <code>START_COPIER.bat</code>, "
                "dan pastikan MT5 sudah terbuka untuk mulai copy trading otomatis!"
            )
            try:
                with open(zip_path, "rb") as doc:
                    await query.message.reply_document(
                        document=doc,
                        filename="member_copier.zip",
                        caption=caption_text,
                        parse_mode=ParseMode.HTML,
                    )
            except Exception as e:
                logger.error(f"Gagal kirim dokumen via callback: {e}. Mencoba fallback...")
                try:
                    with open(zip_path, "rb") as doc:
                        await query.message.reply_document(
                            document=doc,
                            filename="member_copier.zip",
                            caption="📦 <b>member_copier.zip (VIP 9 Buku PDF)</b>",
                            parse_mode=ParseMode.HTML,
                        )
                    await query.message.reply_html(caption_text)
                except Exception as e2:
                    logger.error(f"Fallback callback juga gagal: {e2}")
                    await query.message.reply_html(f"❌ Gagal mengirim file: {e2}")
            return

        elif data == "sendcopier_all":
            if not self._is_admin(update):
                await query.answer("⛔ Hanya Admin yang berhak memproses tindakan ini.", show_alert=True)
                return
            await query.answer("⏳ Mengirim file Auto-Copier MT5 ke seluruh member...")
            res = self.notifier.broadcast_copier_update()
            if res.get("success"):
                await query.message.reply_html(
                    f"✅ <b>File Auto-Copier MT5 Berhasil Dikirim!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📤 <b>Terkirim ke:</b> <b>{res.get('sent_count')} Member Aktif</b>\n"
                    f"⚠️ <b>Gagal:</b> {res.get('failed_count')}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"<i>Seluruh member aktif telah menerima file member_copier.zip terbaru beserta panduan update.</i>"
                )
            else:
                await query.message.reply_html(f"❌ <b>Gagal mengirim:</b> {res.get('error', 'Terjadi kesalahan')}")
            return

        elif data.startswith("deleteuser_"):
            target_id = data.replace("deleteuser_", "").strip()
            self.storage.delete_user(target_id)
            await query.answer("Pengguna berhasil dihapus total dari database!", show_alert=True)
            await query.edit_message_text(
                text=f"🗑️ <b>PENGGUNA DIHAPUS TOTAL</b>\nUser ID <code>{target_id}</code> telah dibersihkan sepenuhnya dari sistem bot.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👥 Kembali ke Daftar Member", callback_data="listusers")]])
            )
            return

        elif data.startswith("manageuser_"):

            target_id = data.replace("manageuser_", "").strip()
            all_u = {u["chat_id"]: u for u in self.storage.list_all_users()}
            u = all_u.get(target_id)
            if not u:
                await query.answer("Pengguna tidak ditemukan.", show_alert=True)
                return

            st = u.get("status", "pending")
            name = u.get("full_name") or u.get("username") or f"User #{target_id[-4:]}"
            uname = f"@{u['username']}" if u.get("username") and u['username'] != "-" else "-"
            rem = u.get("remaining_label", "")
            exp = u.get("expires_at") or "Permanen"

            card_lines = [
                f"👤 <b>KONTROL MEMBER: {html.escape(name)}</b>",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"🆔 <b>Chat ID:</b> <code>{target_id}</code>",
                f"💬 <b>Username:</b> {uname}",
                f"📊 <b>Status:</b> <b>{st.upper()}</b>",
                f"⏱️ <b>Masa Aktif:</b> <code>{rem}</code> (s/d {exp})",
                "━━━━━━━━━━━━━━━━━━━━━━",
                "<i>Pilih tindakan 1-klik di bawah ini tanpa perlu ketik ID manual:</i>"
            ]

            card_kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("➕ Tambah 7 Hari", callback_data=f"apprdur_{target_id}_7d"),
                    InlineKeyboardButton("➕ Tambah 30 Hari", callback_data=f"apprdur_{target_id}_30d"),
                ],
                [
                    InlineKeyboardButton("♾️ Jadikan Permanen", callback_data=f"apprdur_{target_id}_lifetime"),
                    InlineKeyboardButton("🛑 Cabut / Kick", callback_data=f"reject_{target_id}"),
                ],
                [
                    InlineKeyboardButton("📦 Kirim member_copier.zip", callback_data=f"sendzip_{target_id}"),
                    InlineKeyboardButton("🗑️ Hapus Total dari DB", callback_data=f"deleteuser_{target_id}"),
                ],
                [
                    InlineKeyboardButton("🔙 Kembali ke Daftar Member", callback_data="listusers"),
                ]
            ])


            try:
                await query.edit_message_text(
                    text="\n".join(card_lines),
                    parse_mode=ParseMode.HTML,
                    reply_markup=card_kb,
                )
            except Exception:
                await query.message.reply_html(
                    text="\n".join(card_lines),
                    reply_markup=card_kb,
                )
            return

        elif data == "listusers":
            text, reply_markup = self._build_users_list_view()
            try:
                await query.edit_message_text(
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )
            except Exception:
                await query.message.reply_html(
                    text=text,
                    reply_markup=reply_markup,
                )
            return

        elif data.startswith("chart_"):
            parts = data.split("_")
            if len(parts) >= 3:
                c_ticker = parts[1]
                c_style = parts[2]
                await query.answer(f"📊 Menyiapkan chart mode {c_style}...")
                from data.fetcher import DataFetcher
                from indicators.technical import TechnicalIndicators
                from strategy.rules import get_strategy, DEFAULT_STRATEGY
                from strategy.signal_engine import SignalEngine
                from notify.chart_generator import ChartGenerator

                fetcher = DataFetcher(storage=self.storage)
                clean_t = fetcher.normalize_ticker(c_ticker)
                is_gold = any(k in clean_t for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
                df = fetcher.get_data(clean_t, interval="15m", period="5d" if is_gold else "60d", force_fetch=True if is_gold else False)
                if not df.empty:
                    df_ind = TechnicalIndicators.add_all_indicators(df)
                    strategy = get_strategy("DayTrading_Intraday_Momentum") or DEFAULT_STRATEGY
                    engine = SignalEngine([strategy])
                    sig = engine.evaluate_bar(df_ind, ticker=clean_t, strategy=strategy)
                    c_path = ChartGenerator.generate_chart(
                        df=df_ind,
                        ticker_symbol=clean_t,
                        interval="15m",
                        chart_style="area" if c_style == "area" else "candlestick",
                        signal_type=sig.signal,
                        entry_price=sig.price,
                        tp_price=sig.take_profit_price,
                        sl_price=sig.stop_loss_price,
                        setup_grade=sig.setup_grade,
                        pdf_confluence_score=sig.pdf_confluence_score,
                    )
                    if c_path and Path(c_path).exists():
                        other_style = "candles" if c_style == "area" else "area"
                        other_label = "🕯️ Mode Candles" if c_style == "area" else "📈 Mode Area"
                        tv_btn = InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton(other_label, callback_data=f"chart_{clean_t}_{other_style}"),
                                InlineKeyboardButton("📊 Buka di TradingView", url=get_tradingview_url(clean_t)),
                            ]
                        ])
                        price_display = f"${sig.price:,.3f}" if is_gold else f"Rp {sig.price:,.0f}"
                        with open(c_path, "rb") as photo:
                            await query.message.reply_photo(
                                photo=photo,
                                caption=f"📊 <b>LIVE {c_style.upper()} CHART: {clean_t}</b>\n💵 <b>Harga:</b> <code>{price_display}</code>",
                                parse_mode=ParseMode.HTML,
                                reply_markup=tv_btn,
                            )
            return

        elif data.startswith("candle_"):
            parts = data.split("_")
            c_ticker = parts[1] if len(parts) > 1 else "XAUUSD"
            await query.answer("🕯️ Menyiapkan analisa pola candlestick...")
            context.args = [c_ticker]
            await self.candle_command(update, context)
            return

        elif data in ["mt5_toggle_on", "mt5_toggle_off", "mt5_refresh", "mt5_mode_24h", "mt5_mode_night"]:
            from trading.mt5_bridge import MT5Bridge
            bridge = MT5Bridge()
            if data == "mt5_toggle_on":
                bridge.set_enabled(True)
                await query.answer("🟢 Auto-Trade MT5 Diaktifkan!")
            elif data == "mt5_toggle_off":
                bridge.set_enabled(False)
                await query.answer("🔴 Auto-Trade MT5 Dinonaktifkan!")
            elif data == "mt5_mode_24h":
                bridge.set_enabled(True)
                bridge.set_trading_hours("all")
                await query.answer("🟢 Mode 24 Jam Nonstop Diaktifkan!")
            elif data == "mt5_mode_night":
                bridge.set_enabled(True)
                bridge.set_trading_hours("19:00-23:00")
                await query.answer("🌙 Mode Sesi Malam (19:00-23:00 WIB) Diaktifkan!")
            else:
                await query.answer("🔄 Status MT5 diperbarui.")

            acc = bridge.get_account_info()
            status_auto = "🟢 <b>AKTIF (Eksekusi Otomatis)</b>" if bridge.enabled else "🔴 <b>NONAKTIF (Sinyal Saja)</b>"
            conn_badge = "🟢 <b>TERHUBUNG LIVE</b>" if bridge.is_connected else "⚪ <b>STANDBY / OFFLINE</b>"

            hours_badge = "24 Jam Nonstop" if bridge.trading_hours == "all" else f"{bridge.trading_hours} WIB"
            in_hours, _ = bridge.is_within_trading_hours()
            hours_status = "🟢 <b>SESI AKTIF</b>" if in_hours else "⚪ <b>STANDBY (DILUAR JAM)</b>"

            lines = [
                "🤖 <b>DASHBOARD METATRADER 5 (AUTO-TRADER)</b> 📈",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"⚡ <b>Mode Auto-Trade:</b> {status_auto}",
                f"🕒 <b>Jadwal Trading:</b> <code>{hours_badge}</code> ({hours_status})",
                f"📡 <b>Koneksi Terminal:</b> {conn_badge}",
                f"📚 <b>Filter Eksekusi:</b> <code>Wajib 9 Buku PDF Grade A (≥65%)</code>",
                f"📦 <b>Default Lot:</b> <code>{bridge.default_lot} Lot</code> (Batas Risiko: {bridge.risk_percent}%)",
                f"🎯 <b>Instrumen Trading:</b> <code>{bridge.gold_symbol} (XAU/USD)</code>",
                "━━━━━━━━━━━━━━━━━━━━━━",
            ]
            if acc:
                curr = str(acc.get("currency", "USD")).upper()
                is_cent = bridge.is_cent_account() or "USC" in curr or "CENT" in curr
                type_badge = "Cent (USC)" if is_cent else "Standard (USD)"
                unit_label = "USC" if is_cent else "USD"
                equiv_usd = f" (~ ${acc['balance']/100.0:,.2f} USD)" if is_cent else ""
                lines.extend([
                    f"👤 <b>Akun MT5:</b> <code>#{acc['login']}</code> ({acc['server']} - {acc['trade_mode']} | <b>{type_badge}</b>)",
                    f"💵 <b>Balance:</b> <code>{acc['balance']:,.2f} {unit_label}</code>{equiv_usd}",
                    f"📊 <b>Equity:</b> <code>{acc['equity']:,.2f} {unit_label}</code>",
                    f"📈 <b>Floating Profit:</b> <code>{acc['profit']:+,.2f} {unit_label}</code>",
                    f"🛡️ <b>Free Margin:</b> <code>{acc['margin_free']:,.2f} {unit_label}</code>",
                    "━━━━━━━━━━━━━━━━━━━━━━",
                ])
            else:
                lines.extend([
                    "ℹ️ <i>Terminal MT5 belum terhubung ke sesi live.</i>",
                    "💡 <i>Pastikan aplikasi MetaTrader 5 dibuka di komputer/VPS Windows Anda.</i>",
                    "━━━━━━━━━━━━━━━━━━━━━━",
                ])

            positions = bridge.get_open_positions()
            if positions:
                lines.append("📋 <b>POSISI TERBUKA SAAT INI (MT5):</b>")
                pos_unit = "USC" if (bridge.is_cent_account() or (acc and ("USC" in str(acc.get("currency", "")).upper() or "CENT" in str(acc.get("currency", "")).upper()))) else "USD"
                for p in positions[:8]:
                    icon = "🟢" if p["type"] == "BUY" else "🔴"
                    lines.append(
                        f"• {icon} <b>#{p['ticket']} {p['type']} {p['volume']} {p['symbol']}</b> | Floating: <b>{p['profit']:+,.2f} {pos_unit}</b>"
                    )
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
            else:
                lines.append("<i>Tidak ada posisi trading yang sedang terbuka di MT5.</i>")
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")

            lines.extend([
                "<b>PANDUAN KENDALI MT5 DARI HP:</b>",
                "• <code>/mt5 on</code> - Aktifkan eksekusi otomatis",
                "• <code>/mt5 off</code> - Matikan eksekusi otomatis (Standby)",
                "• <code>/mt5 jam 19:00-23:00</code> - Atur jadwal trading aktif",
                "• <code>/mt5 jam all</code> - Kembalikan ke mode 24 jam nonstop",
                "• <code>/mt5 lot 0.02</code> - Ubah ukuran lot transaksi",
                "• <code>/mt5 close &lt;ticket&gt;</code> - Tutup manual posisi aktif",
            ])

            keyboard = [
                [
                    InlineKeyboardButton("🟢 24 Jam Nonstop", callback_data="mt5_mode_24h"),
                    InlineKeyboardButton("🌙 Malam (19-23 WIB)", callback_data="mt5_mode_night"),
                ],
                [
                    InlineKeyboardButton("🔴 Matikan Auto-Trade", callback_data="mt5_toggle_off"),
                    InlineKeyboardButton("🔄 Refresh Status", callback_data="mt5_refresh"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await query.edit_message_text(
                    text="\n".join(lines),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )
            except Exception:
                pass
            return

        elif data.startswith("exec_chart_"):
            if not self._is_admin(update):
                await query.answer(
                    "⚡ Eksekusi sinyal dikendalikan oleh Master Admin. Begitu Admin klik eksekusi di MT5 Master, posisi otomatis tersalin ke akun MT5 Anda!",
                    show_alert=True
                )
                return

            parts = data.split("_")
            if len(parts) >= 7:
                c_action = parts[2].upper()
                c_ticker = parts[3]
                try:
                    c_price = float(parts[4])
                    c_tp = float(parts[5])
                    c_sl = float(parts[6])
                except Exception:
                    await query.answer("❌ Parameter sinyal tidak valid.", show_alert=True)
                    return

                from trading.mt5_bridge import MT5Bridge
                bridge = MT5Bridge()
                open_pos = [p for p in bridge.get_open_positions() if "XAUUSD" in p.get("symbol", "").upper()]
                if open_pos:
                    await query.answer("⚠️ Sudah ada posisi XAU/USD aktif di MT5! Tidak membuka order duplikat.", show_alert=True)
                    return

                # Pastikan auto-trade aktif untuk eksekusi manual ini
                if not bridge.enabled:
                    bridge.set_enabled(True)

                sig_payload = {
                    "ticker": c_ticker,
                    "signal": c_action,
                    "price": c_price,
                    "take_profit_price": c_tp,
                    "stop_loss_price": c_sl,
                    "setup_grade": "Grade A+",
                    "pdf_confluence_score": 100.0,
                }
                res = bridge.execute_signal(sig_payload)
                if res.get("success"):
                    ticket_id = res.get("ticket", "-")
                    exec_vol = float(res.get("volume", bridge.default_lot))
                    exec_p = float(res.get("price", c_price))
                    exec_tp = float(res.get("tp", c_tp))
                    exec_sl = float(res.get("sl", c_sl))
                    await query.answer(f"⚡ Sukses! Order #{ticket_id} {c_action} berhasil dibuka di MT5!", show_alert=True)
                    await query.message.reply_html(
                        f"🤖 <b>EKSEKUSI MT5 INSTAN BERHASIL!</b> 🚀\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🎫 <b>Ticket ID:</b> <code>#{ticket_id}</code>\n"
                        f"📦 <b>Posisi:</b> <b>{c_action} {exec_vol:.2f} Lot</b> {bridge.gold_symbol}\n"
                        f"💵 <b>Harga Masuk:</b> <code>${exec_p:,.2f}</code>\n"
                        f"🎯 <b>Take Profit:</b> <code>${exec_tp:,.2f}</code>\n"
                        f"🛑 <b>Stop Loss:</b> <code>${exec_sl:,.2f}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📡 <i>Order berhasil terpasang di Master MT5 dan tersalin otomatis ke seluruh member VIP via Copier!</i>"
                    )
                    try:
                        self.notifier.send_mt5_execution_report({
                            "ticket": ticket_id,
                            "action": c_action,
                            "symbol": bridge.gold_symbol,
                            "volume": exec_vol,
                            "price": exec_p,
                            "tp": exec_tp,
                            "sl": exec_sl,
                            "score": 100.0,
                            "grade": "Grade A+ (Setup Sempurna ⭐⭐⭐⭐⭐)",
                        })
                    except Exception as ex_rep:
                        logger.warning(f"Gagal broadcast laporan eksekusi manual: {ex_rep}")
                else:
                    err_msg = res.get("message", "Gagal eksekusi order.")
                    await query.answer(f"❌ Gagal: {err_msg}", show_alert=True)
            return

        elif data.startswith("close_pos_"):
            ticket_str = data.replace("close_pos_", "").strip()
            if ticket_str.isdigit():
                t_id = int(ticket_str)
                from trading.mt5_bridge import MT5Bridge
                bridge = MT5Bridge()
                res = bridge.close_position(t_id)
                if res.get("success"):
                    await query.answer(f"✅ Posisi #{t_id} berhasil ditutup di MT5!", show_alert=True)
                    await query.message.reply_html(
                        f"🛑 <b>ORDER MT5 BERHASIL DITUTUP!</b>\n"
                        f"🎫 Posisi <code>#{t_id}</code> telah ditutup dari terminal MT5."
                    )
                else:
                    await query.answer(f"❌ Gagal menutup posisi: {res.get('message', 'Error')}", show_alert=True)
            return

    def _resolve_target_user(self, target_input: str) -> Optional[Dict[str, Any]]:
        """Mencari user berdasarkan chat_id, username, atau nama panggilan."""
        target_str = target_input.strip().lstrip("@").lower()
        all_users = self.storage.list_all_users()
        for u in all_users:
            if str(u.get("chat_id", "")).strip() == target_str:
                return u
        for u in all_users:
            if (u.get("username") or "").lower().lstrip("@") == target_str:
                return u
        for u in all_users:
            fn = (u.get("full_name") or "").lower()
            if target_str in fn or target_str in fn.split():
                return u
        return None

    async def approve_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /approve <nama/username/id> [durasi] khusus Admin."""
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Perintah ini hanya dapat dijalankan oleh Admin.")
            return

        if not context.args:
            await self.users_command(update, context)
            return

        target_arg = context.args[0].strip()
        matched = self._resolve_target_user(target_arg)
        target_id = matched["chat_id"] if matched else target_arg
        target_name = matched.get("full_name") or matched.get("username") or target_id if matched else target_id

        dur = context.args[1].strip() if len(context.args) > 1 else "30d"
        success, expires_at, dur_label = self.storage.approve_user(target_id, dur)
        exp_display = expires_at if expires_at else "Permanen (Tanpa Batas Waktu)"
        if success:
            quick_kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("➕ +30 Hari", callback_data=f"apprdur_{target_id}_30d"),
                    InlineKeyboardButton("♾️ Permanen", callback_data=f"apprdur_{target_id}_lifetime"),
                ],
                [
                    InlineKeyboardButton("🛑 Cabut / Kick", callback_data=f"reject_{target_id}"),
                    InlineKeyboardButton("📦 Kirim Copier Zip", callback_data=f"sendzip_{target_id}"),
                ]
            ])
            await update.message.reply_html(
                f"✅ <b>Akses {html.escape(target_name)} berhasil diaktifkan!</b>\n"
                f"⏱️ <b>Masa Aktif:</b> <code>{dur_label}</code>\n"
                f"📅 <b>Berlaku s/d:</b> <code>{exp_display}</code>",
                reply_markup=quick_kb,
            )
            await self._send_approved_welcome_and_copier(context.bot, target_id, dur_label, exp_display)
        else:
            await update.message.reply_text(f"Gagal menyetujui user '{target_arg}'.")

    async def extend_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /extend <nama/id> [durasi] khusus Admin."""
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Perintah ini hanya dapat dijalankan oleh Admin.")
            return

        if not context.args:
            await self.users_command(update, context)
            return

        target_arg = context.args[0].strip()
        matched = self._resolve_target_user(target_arg)
        target_id = matched["chat_id"] if matched else target_arg
        target_name = matched.get("full_name") or matched.get("username") or target_id if matched else target_id

        dur = context.args[1].strip() if len(context.args) > 1 else "30d"
        success, expires_at, dur_label = self.storage.extend_user(target_id, dur)
        exp_display = expires_at if expires_at else "Permanen (Tanpa Batas Waktu)"
        if success:
            await update.message.reply_html(
                f"🔄 <b>Akses {html.escape(target_name)} berhasil diperpanjang!</b>\n"
                f"➕ <b>Tambahan:</b> <code>{dur_label}</code>\n"
                f"📅 <b>Masa Aktif Baru s/d:</b> <code>{exp_display}</code>"
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"🔄 <b>Masa aktif bot Anda telah diperpanjang oleh Admin!</b>\n\n"
                         f"➕ <b>Tambahan:</b> <b>{dur_label}</b>\n"
                         f"📅 <b>Aktif hingga:</b> <code>{exp_display}</code>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.warning(f"Gagal notif perpanjangan ke {target_id}: {e}")
        else:
            await update.message.reply_text(f"Pengguna '{target_arg}' tidak ditemukan.")

    async def reject_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /reject atau /kick <nama/id> khusus Admin."""
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Perintah ini hanya dapat dijalankan oleh Admin.")
            return

        if not context.args:
            await self.users_command(update, context)
            return

        target_arg = context.args[0].strip()
        matched = self._resolve_target_user(target_arg)
        target_id = matched["chat_id"] if matched else target_arg
        target_name = matched.get("full_name") or matched.get("username") or target_id if matched else target_id

        self.storage.reject_user(target_id)
        restore_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("♻️ Pulihkan Akses (30 Hari)", callback_data=f"apprdur_{target_id}_30d"),
                InlineKeyboardButton("♾️ Pulihkan Permanen", callback_data=f"apprdur_{target_id}_lifetime"),
            ]
        ])
        await update.message.reply_html(
            f"🚫 <b>Akses {html.escape(target_name)} telah dicabut / diblokir.</b>",
            reply_markup=restore_kb,
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🚫 <b>Akses Dicabut</b>\nAdmin telah menonaktifkan akses Anda ke bot ini.",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception:
            pass

    async def delete_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /delete atau /hapus <nama/id> khusus Admin untuk menghapus member total dari database."""
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Perintah ini hanya dapat dijalankan oleh Admin.")
            return

        if not context.args:
            await update.message.reply_html("⚠️ Format salah. Contoh penggunaan: <code>/delete Dipan</code> atau <code>/hapus 7393485645</code>")
            return

        target_arg = context.args[0].strip()
        matched = self._resolve_target_user(target_arg)
        target_id = matched["chat_id"] if matched else target_arg
        target_name = matched.get("full_name") or matched.get("username") or target_id if matched else target_id

        self.storage.delete_user(target_id)
        await update.message.reply_html(
            f"🗑️ <b>Pengguna {html.escape(target_name)} (ID: <code>{target_id}</code>) telah DIHAPUS TOTAL dari database bot.</b>\n"
            f"Data pengguna dan riwayat izinnya telah dibersihkan sepenuhnya dari sistem."
        )

    async def sendcopier_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /sendcopier khusus Admin untuk broadcast file zip copier ke seluruh member aktif."""
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Perintah ini hanya dapat dijalankan oleh Admin.")
            return

        status_msg = await update.message.reply_html("⏳ <b>Mengirim file update Auto-Copier MT5 ke seluruh member aktif...</b>")
        res = self.notifier.broadcast_copier_update()
        if res.get("success"):
            await status_msg.edit_text(
                f"✅ <b>File Auto-Copier MT5 Berhasil Dikirim!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📤 <b>Terkirim ke:</b> <b>{res.get('sent_count')} Member Aktif</b>\n"
                f"⚠️ <b>Gagal:</b> {res.get('failed_count')}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<i>Seluruh member aktif telah menerima file member_copier.zip terbaru beserta panduan update.</i>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await status_msg.edit_text(f"❌ <b>Gagal mengirim:</b> {res.get('error', 'Terjadi kesalahan')}")

    async def copier_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /copier bagi member aktif atau admin untuk mengunduh paket Auto-Copier MT5 & panduan."""
        if not await self.check_user_access(update, context):
            return

        from pathlib import Path
        zip_path = Path(__file__).resolve().parent.parent / "member_copier.zip"
        if not zip_path.exists():
            await update.message.reply_html("❌ File <code>member_copier.zip</code> belum tersedia di server. Silakan hubungi Admin (@selobrow).")
            return

        status_msg = await update.message.reply_html("⏳ <b>Menyiapkan dan mengirim file paket Auto-Copier MT5 (VIP 9 Buku PDF)...</b>")
        caption_text = (
            "🚀 <b>PAKET AUTO-COPIER MT5 (VIP 9 BUKU PDF)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "✨ <b>FITUR & LOGIKA TERBARU:</b>\n"
            "• 🎯 <b>Retest Entry Diskon/Premium:</b> Posisi presisi di ayunan terbaik S/R & Order Block.\n"
            "• ⚖️ <b>Min SL/TP 60 Pips (1:1):</b> Target proporsional Kaidah 9 Buku (TP >= SL).\n"
            "• 🛡️ <b>Anti-Hedging & Auto-Flip:</b> Proteksi tabrakan order & eksekusi cepat.\n"
            "• ⚡ <b>Auto Filling Mode:</b> Kompatibel FOK/IOC/RETURN (Bebas Error 10030).\n\n"
            "🛠️ <b>PETUNJUK CEPAT:</b>\n"
            "1. Ekstrak ZIP ini di PC/Laptop/VPS Anda.\n"
            "2. Buka MetaTrader 5 (pastikan Algo Trading aktif).\n"
            "3. Jalankan <b>START_COPIER.bat</b>.\n"
            "4. Masukkan no HP Telegram & kode OTP (hanya 1x di awal).\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Copier otomatis menduplikasi sinyal resmi ke MT5!</i>"
        )
        safe_caption = caption_text if len(caption_text) <= 950 else caption_text[:950] + "..."
        try:
            with open(zip_path, "rb") as doc:
                await update.message.reply_document(
                    document=doc,
                    filename="member_copier.zip",
                    caption=safe_caption,
                    parse_mode=ParseMode.HTML,
                )
            await status_msg.delete()
        except Exception as e:
            logger.error(f"Percobaan kirim dokumen dengan caption gagal: {e}. Mencoba fallback...")
            try:
                with open(zip_path, "rb") as doc:
                    await update.message.reply_document(
                        document=doc,
                        filename="member_copier.zip",
                        caption="📦 <b>member_copier.zip (VIP 9 Buku PDF)</b>",
                        parse_mode=ParseMode.HTML,
                    )
                await update.message.reply_html(caption_text)
                await status_msg.delete()
            except Exception as e2:
                logger.error(f"Fallback juga gagal: {e2}")
                await status_msg.edit_text(f"❌ Terjadi kesalahan saat mengirim file: {e2}")


    def _build_users_list_view(self) -> Tuple[str, InlineKeyboardMarkup]:
        """Menyusun tampilan daftar pengguna terbagi rapi: VIP Aktif, Menunggu Persetujuan, dan Diblokir."""
        users = self.storage.list_all_users()
        if not users:
            return "Belum ada pengguna lain yang meminta akses.", InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh Daftar Member", callback_data="listusers")]])

        approved_users = [u for u in users if u.get("status") == "approved"]
        pending_users = [u for u in users if u.get("status") == "pending"]
        rejected_users = [u for u in users if u.get("status") == "rejected"]

        lines = [
            "👥 <b>PANEL KONTROL MEMBER VIP (@Selobrow_bot):</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]
        keyboard = []

        # 1. Member Aktif VIP
        lines.append(f"🟢 <b>MEMBER VIP AKTIF ({len(approved_users)} Orang):</b>")
        if approved_users:
            for i, u in enumerate(approved_users, 1):
                cid = u.get("chat_id", "-")
                name = u.get("full_name") or u.get("username") or f"User #{cid[-4:]}"
                rem = u.get("remaining_label", "")
                uname_str = f" (@{u['username']})" if u.get("username") and u['username'] != "-" else ""
                lines.append(f"  {i}. <b>{html.escape(name)}</b>{uname_str}")
                lines.append(f"     Sisa Masa Aktif: <code>{rem}</code>")
                if cid != str(self.admin_id) and cid != SUPERADMIN_CHAT_ID and cid != "8754997836":
                    keyboard.append([InlineKeyboardButton(f"⚙️ Kelola: {name[:14]}", callback_data=f"manageuser_{cid}")])
        else:
            lines.append("  <i>Belum ada member aktif selain Admin.</i>")

        # 2. Menunggu Persetujuan (Pending)
        if pending_users:
            lines.append("\n🟡 <b>MENUNGGU PERSETUJUAN:</b>")
            for u in pending_users:
                cid = u.get("chat_id", "-")
                name = u.get("full_name") or u.get("username") or f"User #{cid[-4:]}"
                uname_str = f" (@{u['username']})" if u.get("username") and u['username'] != "-" else ""
                lines.append(f"  ⏳ <b>{html.escape(name)}</b>{uname_str} (ID: <code>{cid}</code>)")
                keyboard.append([
                    InlineKeyboardButton(f"✅ Setujui {name[:10]}", callback_data=f"approve_{cid}"),
                    InlineKeyboardButton(f"❌ Tolak", callback_data=f"reject_{cid}")
                ])

        # 3. Member Diblokir / Kicked
        if rejected_users:
            lines.append("\n🚫 <b>MEMBER DIBLOKIR / KICKED:</b>")
            for u in rejected_users:
                cid = u.get("chat_id", "-")
                name = u.get("full_name") or u.get("username") or f"User #{cid[-4:]}"
                uname_str = f" (@{u['username']})" if u.get("username") and u['username'] != "-" else ""
                lines.append(f"  🔴 <b>{html.escape(name)}</b>{uname_str} — <i>Akses Terputus & Di-ghosting</i>")
                keyboard.append([
                    InlineKeyboardButton(f"♻️ Pulihkan {name[:10]}", callback_data=f"apprdur_{cid}_30d"),
                    InlineKeyboardButton(f"🗑️ Hapus Total", callback_data=f"deleteuser_{cid}"),
                ])

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━",
            "💡 <i>Pilih tombol di bawah untuk perpanjang, cabut akses, atau hapus total.</i>"
        ])
        keyboard.append([InlineKeyboardButton("🔄 Refresh Daftar Member", callback_data="listusers")])
        return "\n".join(lines), InlineKeyboardMarkup(keyboard)

    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /users untuk melihat daftar pengguna & tombol kontrol 1-klik (khusus Admin)."""
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Perintah ini hanya dapat dijalankan oleh Admin.")
            return

        text, reply_markup = self._build_users_list_view()
        await update.message.reply_html(text, reply_markup=reply_markup)

    async def license_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /license untuk memverifikasi status izin copier member."""
        if not update.effective_user or not update.message:
            return
        user_id = str(update.effective_user.id).strip()
        auth = self.storage.is_user_authorized(user_id, admin_id=self.admin_id)
        all_u = {u["chat_id"]: u for u in self.storage.list_all_users()}
        u = all_u.get(user_id)
        exp = u.get("expires_at") if u else ""
        rem = u.get("remaining_label", "") if u else "Expired"
        status_flag = "VALID" if auth else "EXPIRED"
        resp = f"LIC_INFO|{user_id}|{status_flag}|{exp or 'LIFETIME'}|{rem}"
        reply_msg = await update.message.reply_text(resp)

        # Hapus otomatis pesan handshake setelah 4 detik agar chat Telegram member tetap bersih
        async def _cleanup_handshake():
            await asyncio.sleep(4)
            try:
                await reply_msg.delete()
                await update.message.delete()
            except Exception:
                pass
        asyncio.create_task(_cleanup_handshake())

    async def tutup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /tutup untuk melihat laporan penutupan pasar saham BEI yang simpel."""
        if not await self.check_user_access(update, context):
            return

        from data.fetcher import DataFetcher
        cfg = load_config()
        watchlist = cfg.get("watchlist", ["BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK"])
        fetcher = DataFetcher(storage=self.storage)

        summary_data = []
        for ticker in watchlist[:8]:
            try:
                clean_t = ticker.replace(".JK", "")
                df = fetcher.get_data(ticker, interval="1d", period="5d")
                if not df.empty and len(df) >= 1:
                    last_row = df.iloc[-1]
                    curr_c = float(last_row["Close"])
                    prev_c = float(df.iloc[-2]["Close"]) if len(df) >= 2 else curr_c
                    chg_pct = ((curr_c - prev_c) / prev_c) * 100.0 if prev_c > 0 else 0.0
                    summary_data.append({
                        "ticker": clean_t,
                        "close": curr_c,
                        "change_pct": chg_pct,
                    })
            except Exception as e:
                logger.debug(f"Gagal memuat ringkasan saham {ticker}: {e}")

        summary_text = self.notifier.format_market_close_summary(summary_data)
        await update.message.reply_html(summary_text)

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
            "• /candle - Bedah pola candlestick & price action (9 buku)",
            "• /gold - Analisis & sinyal emas dunia XAU/USD (24 Jam)",
            "• /scan - Pindai seluruh saham potensial sekarang juga (On-Demand)",
            "• /watchlist - Lihat daftar saham potensial cuan & harga terkini",
            "• /status - Cek status bot & strategi aktif",
            "• /lasthistory - Tampilkan 5 riwayat sinyal terakhir",
            "• /copier - Unduh paket zip Auto-Copier MT5 & panduan (Member VIP)",
            "• /help - Bantuan & panduan penggunaan bot",
            "",
            "💬 <b>Fitur Ngobrol Santai (AI Natural Chat):</b>",
            "Anda juga bisa langsung chat santai dengan bot tanpa garis miring (/):",
            "• <i>'bor minta chart xauusd'</i> (Live Chart Visual)",
            "• <i>'gimana analisa bbca hari ini?'</i> (Analisa Saham Kilat)",
            "• <i>'cek posisi akun mt5'</i> (Status Akun & Posisi Terbuka)",
            "• <i>'jelasin apa itu fibonacci golden pocket'</i> (Edukasi 9 Buku PDF)",
            "• <i>'ada saham apa yang berpotensi?'</i> (Radar Sinyal Cuan)",
        ]

        if self._is_admin(update):
            welcome_lines.extend([
                "",
                "👑 <b>Menu Khusus Pemilik / Super Admin:</b>",
                "• /users - Lihat daftar seluruh pengguna & status izin",
                "• /approve &lt;id&gt; - Izinkan akses pengguna baru",
                "• /reject &lt;id&gt; - Tolak / cabut akses pengguna",
                "• /sendcopier - Kirim update member_copier.zip ke seluruh member aktif",
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
        """Handler perintah /lasthistory dan /history untuk transparansi penuh riwayat sinyal & transaksi MT5 (Win & Lose)."""
        if not await self.check_user_access(update, context):
            return

        from trading.mt5_bridge import MT5Bridge
        bridge = MT5Bridge()

        # Ambil info akun MT5 & deals 24 jam terakhir
        acct_info = bridge.get_account_info() if (bridge.enabled and bridge.is_available()) else None
        closed_deals = bridge.get_closed_deals(hours=24) if (bridge.enabled and bridge.is_available()) else []
        open_positions = bridge.get_open_positions() if (bridge.enabled and bridge.is_available()) else []

        lines = ["📜 <b>REKAP & RIWAYAT TRANSAKSI LENGKAP</b>", "━━━━━━━━━━━━━━━━━━━━━━"]

        # Ringkasan Akun MT5 Live
        if acct_info:
            bal = float(acct_info.get("balance", 0.0))
            eq = float(acct_info.get("equity", 0.0))
            raw_curr = str(acct_info.get("currency", "USC")).upper()
            is_cent = "USC" in raw_curr or "CENT" in raw_curr or raw_curr.endswith("C") or bridge.is_cent_account()
            curr = "USC" if is_cent else raw_curr
            type_badge = "Cent (USC)" if is_cent else "Standard (USD)"
            equiv_usd = f" (~ ${bal/100.0:,.2f} USD)" if is_cent else ""
            lines.append(f"💼 <b>Status Akun MT5 ({type_badge}):</b>")
            lines.append(f"• Saldo (Balance): <code>{bal:,.2f} {curr}</code>{equiv_usd}")
            lines.append(f"• Ekuitas (Equity): <code>{eq:,.2f} {curr}</code>")
            lines.append(f"• Posisi Aktif: <b>{len(open_positions)} posisi terbuka</b>")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━")

        # Riwayat Closed Deals Real MT5 (Win & Lose)
        if closed_deals:
            lines.append(f"📊 <b>TRANSAKSI MT5 TERAKHIR (24 JAM):</b>")
            deal_unit = "USC" if (bridge.is_cent_account() or (acct_info and ("USC" in str(acct_info.get("currency", "")).upper() or "CENT" in str(acct_info.get("currency", "")).upper()))) else "USD"
            # Urutkan deal paling baru di atas
            sorted_deals = sorted(closed_deals, key=lambda x: x.get("time", 0), reverse=True)[:8]
            for d in sorted_deals:
                pnl = float(d.get("profit", 0.0))
                is_win = pnl >= 0
                icon = "🟢 [TP/WIN]" if is_win else "🔴 [SL/LOSE]"
                t_type = d.get("type", "TRADE")
                pos_id = d.get("position_id", "-")
                vol = d.get("volume", 0.05)
                p_exit = float(d.get("price", 0.0))
                p_entry = float(d.get("entry_price", 0.0))
                t_wib = d.get("time_wib", "-")
                reason = d.get("reason", "MANUAL")
                sym = d.get("symbol", "XAUUSD")

                price_flow = f"${p_entry:,.2f} ➔ ${p_exit:,.2f}" if p_entry > 0 and p_entry != p_exit else f"${p_exit:,.2f}"
                lines.append(
                    f"{icon} <b>{sym} {t_type} #{pos_id}</b> ({vol} lot)\n"
                    f"   💰 Hasil: <b>{pnl:+.2f} {deal_unit}</b> ({reason})\n"
                    f"   📍 Harga: <code>{price_flow}</code>\n"
                    f"   🕒 Waktu: <i>{t_wib}</i>"
                )
                lines.append("──────────────────────")
        else:
            lines.append("<i>Belum ada transaksi tertutup dalam 24 jam terakhir di MT5.</i>")
            lines.append("──────────────────────")

        # Riwayat Sinyal Strategi di Database
        signals = self.storage.get_recent_signals(limit=5)
        if signals:
            lines.append("🎯 <b>5 SINYAL STRATEGI TERAKHIR:</b>")
            for s in signals:
                sig_type = s.get("signal_type", "HOLD")
                outcome = s.get("outcome", "OPEN")
                ticker = s.get("ticker", "-")
                is_gold = any(k in ticker.upper() for k in ["XAUUSD", "GC=F", "GOLD", "EMAS"])
                p_entry = float(s.get("price", 0.0))
                p_exit = float(s.get("exit_price") or 0.0)
                pnl_pct = float(s.get("pnl_pct") or 0.0)

                if outcome == "WIN":
                    status_lbl = f"🟢 <b>TP HIT (+{pnl_pct:.2f}%)</b>"
                elif outcome == "LOSE":
                    status_lbl = f"🔴 <b>SL HIT ({pnl_pct:.2f}%)</b>"
                elif outcome == "CLOSED_MANUAL":
                    status_lbl = f"⚠️ <b>CLOSED ({pnl_pct:.2f}%)</b>"
                else:
                    status_lbl = "⏳ <b>SEDANG BERJALAN (OPEN)</b>"

                p_str = f"${p_entry:,.2f}" if is_gold else f"Rp {p_entry:,.0f}"
                flow_str = f" ➔ ${p_exit:,.2f}" if (is_gold and p_exit > 0) else ""
                t_candle = s.get("candle_time", "-")
                note = s.get("outcome_note") or ""

                lines.append(f"• <b>{sig_type} {ticker}</b> @ {p_str}{flow_str}")
                lines.append(f"  Status: {status_lbl}")
                if note:
                    lines.append(f"  📝 <i>{html.escape(note[:70])}</i>")
                lines.append(f"  🕒 <i>{t_candle}</i>")

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

        fresh_signals = [d for d in res.get("details", []) if d.get("signal") in ["BUY", "SELL"] and d.get("notified")]

        reply_lines = [
            f"✅ <b>Pemindaian Selesai!</b>",
            f"• Instrumen Diproses: <b>{processed}</b>",
            f"• Sinyal Baru Siap Entry: <b>{len(fresh_signals)}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for d in fresh_signals:
            emoji = "🟢" if d.get("signal") == "BUY" else "🔴"
            is_gold = any(k in d.get("ticker", "").upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
            p_str = f"${float(d.get('price', 0)):,.2f}" if is_gold else f"Rp {float(d.get('price', 0)):,.0f}"
            reply_lines.append(f"{emoji} <b>{d.get('signal')}</b>: <code>{d.get('ticker')}</code> @ {p_str}")

        if not fresh_signals:
            reply_lines.append("<i>Semua instrumen saat ini dalam status netral atau sinyal lama telah disaring demi mencegah salah entry / telat.</i>")

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

                # Validasi kesegaran ketat: Buang sinyal telat / candle hari kemarin
                is_fresh_signal = False
                try:
                    c_ts = pd.to_datetime(sig.candle_time)
                    tz_w = ZoneInfo("Asia/Jakarta")
                    n_w = datetime.now(tz_w)
                    if c_ts.tzinfo is not None:
                        c_ts_w = c_ts.tz_convert(tz_w)
                    else:
                        c_ts_w = c_ts.tz_localize(tz_w)

                    # Hanya candle hari ini
                    if c_ts_w.date() == n_w.date():
                        if mode == "intraday":
                            # Maksimal 30 menit usia candle untuk intraday
                            if (n_w - c_ts_w).total_seconds() <= 30 * 60:
                                is_fresh_signal = True
                        else:
                            is_fresh_signal = True
                except Exception:
                    is_fresh_signal = False

                if sig.signal == "BUY" and is_fresh_signal:
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
            lines.append("🟢 <b>SINYAL BELI SIAP EKSEKUSI (ENTRY FRESH):</b>")
            for b in buy_signals:
                lines.append(f"• <code>{b.ticker}</code> @ <b>Rp {b.price:,.0f}</b>")
                lines.append(f"  🎯 Target Profit (TP): <b>Rp {b.take_profit_price:,.0f}</b>")
                lines.append(f"  🛑 Stop Loss (SL): <b>Rp {b.stop_loss_price:,.0f}</b>")
                lines.append(f"  ⚖️ Risk/Reward: <b>1 : {b.risk_reward_ratio or 1.67}</b>")
                lines.append("──────────────────────")
        else:
            lines.append("<i>Belum ada sinyal BUY baru yang segar saat ini. Bot menyaring ketat agar tidak menampilkan sinyal yang sudah telat entry.</i>")
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

            # Ambil level TP & SL dari sinyal engine jika ada, atau hitung sesuai arah BUY/SELL
            if sig.take_profit_price and sig.stop_loss_price:
                tp_calc = float(sig.take_profit_price)
                sl_calc = float(sig.stop_loss_price)
                rrr = sig.risk_reward_ratio or round(abs(tp_calc - last_close) / max(abs(last_close - sl_calc), 0.01), 2)
            else:
                if sig.signal == "SELL":
                    tp_calc = round(last_close * (1.0 - 0.008), 2)
                    sl_calc = round(last_close * (1.0 + 0.004), 2)
                    risk_dist = max(sl_calc - last_close, 0.01)
                    rrr = round((last_close - tp_calc) / risk_dist, 2)
                else:
                    tp_calc = round(last_close * (1.0 + 0.008), 2)
                    sl_calc = round(last_close * (1.0 - 0.004), 2)
                    risk_dist = max(last_close - sl_calc, 0.01)
                    rrr = round((tp_calc - last_close) / risk_dist, 2)

            if sig.signal == "SELL":
                tp_pct_val = abs((last_close - tp_calc) / last_close) * 100.0
                sl_pct_val = abs((sl_calc - last_close) / last_close) * 100.0
            else:
                tp_pct_val = abs((tp_calc - last_close) / last_close) * 100.0
                sl_pct_val = abs((last_close - sl_calc) / last_close) * 100.0

            tv_quote = df.attrs.get("tradingview_quote") or {}
            prev_close = tv_quote.get("prev_close")
            chg_pct = float(tv_quote.get("change", 0.0))
            chg_val = (last_close - prev_close) if prev_close else 0.0
            chg_sign = "+" if chg_val >= 0 else ""

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
                "prev_close": prev_close,
                "chg_pct": chg_pct,
                "chg_val": chg_val,
                "chg_sign": chg_sign,
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
                "tp_pct": tp_pct_val,
                "sl_pct": sl_pct_val,
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

        prev_close_line = ""
        if data.get("prev_close"):
            pc = data["prev_close"]
            cs = data["chg_sign"]
            cv = data["chg_val"]
            cp = data["chg_pct"]
            prev_close_line = f"📉 <b>Prev Close (TradingView):</b> <code>${pc:,.3f}</code> ({cs}${cv:,.3f} / {cs}{cp:.2f}%)"

        msg_lines = [
            "🥇 <b>ANALISIS PASAR XAU/USD (GOLD)</b> 🌎",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>Harga Terkini:</b> <code>${close:,.3f}</code>",
            f"⏰ <b>Waktu Candle:</b> {data['time']}",
            f"📊 <b>Rentang 24 Jam:</b> ${data['low_24h']:,.3f} - ${data['high_24h']:,.3f}",
        ]
        if prev_close_line:
            msg_lines.append(prev_close_line)
        msg_lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📈 <b>INDIKATOR TEKNIKAL (15m):</b>",
            f"• <b>RSI (14):</b> {rsi:.1f} ({rsi_desc})",
            f"• <b>EMA 20:</b> ${ema20:,.3f}",
            f"• <b>EMA 50:</b> ${ema50:,.3f}",
            f"• <b>Tren MA:</b> {trend_desc}",
            f"• <b>Bollinger Bands:</b> Upper ${data['bb_upper']:,.3f} | Lower ${data['bb_lower']:,.3f}",
            f"• <b>Volume 15m:</b> {data['vol_ratio']:.1f}x rata-rata",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🎯 <b>STATUS SINYAL:</b> {sig_badge}",
            f"  • Entry Ref: <b>${close:,.3f}</b>",
            f"  • Target Profit (TP): <b>${data['tp']:,.3f}</b> (+{data['tp_pct']:.2f}%)",
            f"  • Stop Loss (SL): <b>${data['sl']:,.3f}</b> (-{data['sl_pct']:.2f}%)",
            f"  • Risk/Reward Ratio: <b>1 : {data['rrr']}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "💡 <i>Pasar emas global aktif 23 jam sehari (Senin-Jumat). Kelola leverage secara bijak!</i>",
        ])

        caption_text = "\n".join(msg_lines)
        chart_path = data.get("chart_path")
        tv_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📈 Mode Area", callback_data="chart_XAUUSD_area"),
                InlineKeyboardButton("🕯️ Mode Candles", callback_data="chart_XAUUSD_candles"),
            ],
            [
                InlineKeyboardButton("📊 Buka di TradingView", url=get_tradingview_url("XAUUSD")),
            ]
        ])

        if chart_path and Path(chart_path).exists():
            safe_cap = caption_text if len(caption_text) <= 1020 else caption_text[:1000] + "..."
            try:
                with open(chart_path, "rb") as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption=safe_cap,
                        parse_mode=ParseMode.HTML,
                        reply_markup=tv_markup,
                    )
                return
            except Exception as e:
                logger.warning(f"Gagal kirim foto gold: {e}")

        await update.message.reply_html(caption_text, reply_markup=tv_markup)

    async def candle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /candle <ticker> untuk analisis pola candlestick & price action dari 9 buku."""
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

        msg = update.message or (update.callback_query.message if update.callback_query else None)
        if not msg:
            return
        await msg.reply_html(f"🕯️ <i>Menganalisis pola candlestick & price action untuk <b>{disp_ticker}</b>...</i>")

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

            db_bottom = bool(last_row.get("pattern_double_bottom", 0))
            db_top = bool(last_row.get("pattern_double_top", 0))
            f_wedge = bool(last_row.get("pattern_falling_wedge", 0))
            r_wedge = bool(last_row.get("pattern_rising_wedge", 0))
            hs_inv = bool(last_row.get("pattern_inv_head_shoulders", 0))
            hs_top = bool(last_row.get("pattern_head_shoulders", 0))

            bos_bull = bool(last_row.get("structure_bos_bullish", 0))
            bos_bear = bool(last_row.get("structure_bos_bearish", 0))
            ob_bull = bool(last_row.get("order_block_bullish", 0))
            ob_bear = bool(last_row.get("order_block_bearish", 0))
            fvg_bull = bool(last_row.get("fvg_bullish", 0))
            fvg_bear = bool(last_row.get("fvg_bearish", 0))

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
                "db_bottom": db_bottom,
                "db_top": db_top,
                "f_wedge": f_wedge,
                "r_wedge": r_wedge,
                "hs_inv": hs_inv,
                "hs_top": hs_top,
                "bos_bull": bos_bull,
                "bos_bear": bos_bear,
                "ob_bull": ob_bull,
                "ob_bear": ob_bear,
                "fvg_bull": fvg_bull,
                "fvg_bear": fvg_bear,
            }

        res = await asyncio.to_thread(_fetch_and_eval)
        if not res:
            await msg.reply_text(f"Data tidak ditemukan atau feed sedang offline untuk {ticker_arg}.")
            return

        price_fmt = f"${res['close']:,.2f}" if res["is_gold"] else f"Rp {res['close']:,.0f}"

        # Status pola buku 8 (Chart Patterns)
        if res.get("db_bottom") or res.get("f_wedge") or res.get("hs_inv"):
            pattern_status = "🟢 Bullish Reversal (Double Bottom / Wedge / Inv H&S)"
        elif res.get("db_top") or res.get("r_wedge") or res.get("hs_top"):
            pattern_status = "🔴 Bearish Reversal (Double Top / Wedge / H&S)"
        else:
            pattern_status = "⚪ Pola Normal / Konsolidasi"

        # Status pola buku 9 (Smart Money / Market Structure)
        if res.get("bos_bull") or res.get("ob_bull"):
            smc_status = "🟢 Bullish BOS / Demand Order Block"
        elif res.get("bos_bear") or res.get("ob_bear"):
            smc_status = "🔴 Bearish BOS / Supply Order Block"
        else:
            smc_status = "⚪ Struktur Terjaga"

        lines = [
            f"🕯️ <b>BEDAH CANDLESTICK & PRICE ACTION: {res['ticker']}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>Harga Terkini:</b> <code>{price_fmt}</code> ({res['time']} WIB)",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📖 <b>TELAAH 9 BUKU TRADING:</b>",
            f"• <b>Pinbar Rejection:</b> {'🟢 YA (Ekor Penolakan Kuat)' if res['pinbar'] else f'⚪ Tidak (Ekor: {res['wick_ratio']:.0f}%)'}",
            f"• <b>Bullish Engulfing:</b> {'🟢 YA (Candle Menelan Penuh)' if res['engulfing'] else '⚪ Tidak'}",
            f"• <b>Bob Volman 20 EMA:</b> {'🟢 Pullback Reversal Terkonfirmasi' if res['volman_pb'] else '⚪ Normal'}",
            f"• <b>Bob Volman Buildup:</b> {'🔥 Kompresi Siap Breakout' if res['volman_bd'] else '⚪ Volatilitas Reguler'}",
            f"• <b>Fibonacci Golden Pocket:</b> {'🎯 Rebound di Area 50%-61.8%' if res['fib_gz'] else '⚪ Di luar Golden Zone'}",
            f"• <b>Ichimoku Kumo Cloud:</b> {'⛅ Bullish di Atas Awan' if res['ichi_cloud'] else '☁️ Di Bawah / Dalam Awan'}",
            f"• <b>Chart Pattern (Buku 8):</b> {pattern_status}",
            f"• <b>Market Structure (Buku 9):</b> {smc_status}",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 <b>Konfirmasi Volume:</b> {res['vol_ratio']:.1f}x rata-rata | <b>RSI:</b> {res['rsi']:.1f}",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "💡 <i>Gunakan: <code>/candle BBCA</code>, <code>/candle BBRI</code>, atau <code>/candle GOLD</code></i>",
        ]

        tv_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Buka di TradingView", url=get_tradingview_url(clean_ticker))
        ]])
        await msg.reply_html("\n".join(lines), reply_markup=tv_markup)

    async def winrate_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /winrate dan /performance untuk rekam jejak akurasi Win/Lose bot khusus Gold (XAU/USD)."""
        if not await self.check_user_access(update, context):
            return

        stats = self.storage.get_win_rate_stats()
        g_stats = stats.get("gold_stats", {})

        # Gunakan data Gold sebagai angka utama
        g_comp  = g_stats.get("completed", 0)
        g_win   = g_stats.get("win", 0)
        g_lose  = g_stats.get("lose", 0)
        g_open  = g_stats.get("open", stats.get("open_count", 0))
        g_wr    = g_stats.get("win_rate", 0.0)
        g_lr    = 100.0 - g_wr if g_comp > 0 else 0.0
        g_pnl   = g_stats.get("total_pnl", stats.get("total_pnl", 0.0))

        # Bintang akurasi
        stars = "⭐" * min(5, max(1, int(g_wr / 20))) if g_comp > 0 else ""

        # Evaluasi otomatis
        if g_comp >= 5 and g_wr >= 75.0:
            eval_note = "🔥 <b>Akurasi Luar Biasa!</b> Filter 9 buku PDF terbukti sangat akurat prediksi arah Gold."
        elif g_comp >= 5 and g_wr >= 60.0:
            eval_note = "🟢 <b>Akurasi Sehat & Profitable.</b> Risk:Reward XAU/USD terjaga dengan baik."
        elif g_comp == 0:
            eval_note = f"⏳ Sinyal Gold masih berjalan ({g_open} posisi OPEN). Menunggu candle mencapai TP / SL."
        else:
            eval_note = "⚠️ <b>Perlu Penyesuaian.</b> Kami terus memperketat filter konfluensi Gold untuk menekan loss."

        # Hanya ambil riwayat trade Gold saja
        recent_trades = self.storage.get_recent_completed_signals(limit=10)
        gold_trades = [
            rt for rt in recent_trades
            if any(k in rt.get("ticker", "").upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        ]

        lines = [
            "🥇 <b>STATISTIK WIN RATE — EMAS (XAU/USD)</b> 🏆",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🎯 <b>Win Rate Gold:</b> <code>{g_wr:.1f}%</code> {stars}",
            f"🛑 <b>Lose Rate:</b>     <code>{g_lr:.1f}%</code>",
            f"💰 <b>Total PnL Gold:</b> <code>{g_pnl:+.2f}%</code>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📈 <b>REKAM JEJAK GOLD:</b>",
            f"• <b>Trade Selesai:</b> {g_comp} trade  (🟢 {g_win} Win | 🔴 {g_lose} Lose)",
            f"• <b>Posisi OPEN:</b>   {g_open} sinyal aktif sedang berjalan",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💡 <i>{eval_note}</i>",
        ]

        if gold_trades:
            lines.append("━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("📋 <b>RIWAYAT HASIL TERAKHIR (XAU/USD):</b>")
            for rt in gold_trades:
                c_out  = rt.get("outcome", "WIN")
                c_icon = "🟢 TP HIT" if c_out == "WIN" else "🔴 SL HIT"
                c_type = rt.get("signal_type", "BUY")
                c_pnl  = float(rt.get("pnl_pct") or 0.0)
                c_note = rt.get("outcome_note") or "Selesai mencapai level target."
                c_time = rt.get("exit_time") or rt.get("candle_time") or "-"
                lines.append(f"• <b>[{c_icon}] XAU/USD ({c_type}):</b> <code>{c_pnl:+.2f}%</code>  <i>({c_time})</i>")
                lines.append(f"  📝 <i>{html.escape(c_note[:80])}</i>")
        else:
            lines.append("━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("📋 <i>Belum ada trade Gold yang selesai. Posisi aktif sedang dipantau real-time.</i>")
            lines.append("💡 <i>Setiap kali TP/SL Gold tercapai, laporan otomatis dikirim ke chat ini.</i>")

        await update.message.reply_html("\n".join(lines))

    async def mt5_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /mt5 untuk memantau status, akun, posisi terbuka, dan mengendalikan Auto-Trade MT5."""
        if not await self.check_user_access(update, context):
            return

        from trading.mt5_bridge import MT5Bridge
        bridge = MT5Bridge()

        args = context.args or []
        if args:
            sub = args[0].lower()
            if sub == "on":
                bridge.set_enabled(True)
                await update.message.reply_html(
                    "🟢 <b>Auto-Trading MetaTrader 5 DIAKTIFKAN!</b>\n\n"
                    "Bot akan mengeksekusi order (BUY / SELL) secara otomatis di akun MT5 setiap kali sinyal Emas (XAU/USD) 9 Buku PDF terkonfirmasi Grade A (≥65%).\n\n"
                    "🎯 <i>Sinyal tetap dikawal ketat oleh kaidah Fibonacci Golden Pocket, Ichimoku Kumo, 20 EMA Bob Volman, dan manajemen risiko TP & SL.</i>"
                )
                return
            elif sub == "off":
                bridge.set_enabled(False)
                await update.message.reply_html(
                    "🔴 <b>Auto-Trading MetaTrader 5 DINONAKTIFKAN!</b>\n\n"
                    "Bot beralih ke mode notifikasi biasa (hanya mengirim sinyal ke Telegram tanpa membuka order di MT5)."
                )
                return
            elif sub in ["jam", "jadwal", "hours", "schedule"] and len(args) > 1:
                val = args[1].lower()
                if val in ["all", "24", "24h", "24jam", "nonstop"]:
                    bridge.set_enabled(True)
                    bridge.set_trading_hours("all")
                    await update.message.reply_html(
                        "🟢 <b>Jadwal MT5 Diatur ke Mode 24 Jam Nonstop!</b>\n\n"
                        "Bot akan mengeksekusi order otomatis kapan pun sinyal Grade A (≥65%) muncul selama pasar buka."
                    )
                else:
                    parts = val.split("-")
                    if len(parts) == 2 and ":" in parts[0] and ":" in parts[1]:
                        bridge.set_enabled(True)
                        bridge.set_trading_hours(val)
                        await update.message.reply_html(
                            f"🌙 <b>Jadwal Trading Aktif Diatur: <code>{val} WIB</code></b>\n\n"
                            f"Bot hanya akan mengeksekusi order otomatis pada rentang jam tersebut. Di luar jam tersebut bot berada dalam status STANDBY (hanya kirim sinyal analisa)."
                        )
                    else:
                        await update.message.reply_html("⚠️ Format jadwal salah. Contoh: <code>/mt5 jam 19:00-23:00</code> atau <code>/mt5 jam all</code>")
                return
            elif sub == "lot" and len(args) > 1:
                try:
                    new_lot = float(args[1])
                    if new_lot <= 0 or new_lot > 50:
                        raise ValueError()
                    bridge.set_default_lot(new_lot)
                    await update.message.reply_html(f"✅ <b>Ukuran Lot Default Berhasil Diubah:</b> <code>{new_lot} Lot</code>")
                except Exception:
                    await update.message.reply_html("⚠️ Format salah. Contoh penggunaan: <code>/mt5 lot 0.02</code>")
                return
            elif sub in ["resume", "lanjut", "reset", "clear"]:
                bridge.clear_reversal_cooldown()
                await update.message.reply_html(
                    "🟢 <b>Mode Jeda Reversal Berhasil Direset!</b>\n\n"
                    "Bot siap kembali mengeksekusi order XAU/USD secara otomatis jika terkonfirmasi setup Grade A (≥65%)."
                )
                return
            elif sub == "close" and len(args) > 1:
                try:
                    ticket = int(args[1])
                    res = bridge.close_position(ticket)
                    if res.get("success"):
                        await update.message.reply_html(f"✅ <b>Posisi #{ticket} Ditutup:</b> {res.get('message')}")
                    else:
                        await update.message.reply_html(f"❌ <b>Gagal:</b> {res.get('message')}")
                except Exception as e:
                    await update.message.reply_html(f"⚠️ Format tiket salah: {e}")
                return

        acc = bridge.get_account_info()
        is_conn = bridge.is_connected
        status_auto = "🟢 <b>AKTIF (Eksekusi Otomatis)</b>" if bridge.enabled else "🔴 <b>NONAKTIF (Sinyal Saja)</b>"
        conn_badge = "🟢 <b>TERHUBUNG LIVE</b>" if is_conn else "⚪ <b>STANDBY / OFFLINE</b>"

        hours_badge = "24 Jam Nonstop" if bridge.trading_hours == "all" else f"{bridge.trading_hours} WIB"
        in_hours, _ = bridge.is_within_trading_hours()
        hours_status = "🟢 <b>SESI AKTIF</b>" if in_hours else "⚪ <b>STANDBY (DILUAR JAM)</b>"

        in_cd, cd_msg = bridge.is_in_reversal_cooldown()
        rg_badge = f"⏸️ <b>JEDA OBSERVASI</b> (Cooldown aktif)" if in_cd else "🟢 <b>AKTIF & MEMANTAU REAL-TIME</b>"

        lines = [
            "🤖 <b>DASHBOARD METATRADER 5 (AUTO-TRADER)</b> 📈",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"⚡ <b>Mode Auto-Trade:</b> {status_auto}",
            f"🕒 <b>Jadwal Trading:</b> <code>{hours_badge}</code> ({hours_status})",
            f"📡 <b>Koneksi Terminal:</b> {conn_badge}",
            f"🛡️ <b>Reversal Guard (Ambil Untung):</b> {rg_badge}",
            f"📚 <b>Filter Eksekusi:</b> <code>Wajib 9 Buku PDF Grade A (≥65%)</code>",
            f"📦 <b>Default Lot:</b> <code>{bridge.default_lot} Lot</code> (Batas Risiko: {bridge.risk_percent}%)",
            f"🎯 <b>Instrumen Trading:</b> <code>{bridge.gold_symbol} (XAU/USD)</code>",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]

        if acc:
            curr = str(acc.get("currency", "USD")).upper()
            is_cent = bridge.is_cent_account() or "USC" in curr or "CENT" in curr
            type_badge = "Cent (USC)" if is_cent else "Standard (USD)"
            unit_label = "USC" if is_cent else "USD"
            equiv_usd = f" (~ ${acc['balance']/100.0:,.2f} USD)" if is_cent else ""
            lines.extend([
                f"👤 <b>Akun MT5:</b> <code>#{acc['login']}</code> ({acc['server']} - {acc['trade_mode']} | <b>{type_badge}</b>)",
                f"💵 <b>Balance:</b> <code>{acc['balance']:,.2f} {unit_label}</code>{equiv_usd}",
                f"📊 <b>Equity:</b> <code>{acc['equity']:,.2f} {unit_label}</code>",
                f"📈 <b>Floating Profit:</b> <code>{acc['profit']:+,.2f} {unit_label}</code>",
                f"🛡️ <b>Free Margin:</b> <code>{acc['margin_free']:,.2f} {unit_label}</code> (Leverage 1:{acc['leverage']})",
                "━━━━━━━━━━━━━━━━━━━━━━",
            ])
        else:
            lines.extend([
                "ℹ️ <i>Terminal MT5 belum terhubung ke sesi live.</i>",
                "💡 <i>Pastikan aplikasi MetaTrader 5 dibuka di komputer/VPS Windows Anda.</i>",
                "━━━━━━━━━━━━━━━━━━━━━━",
            ])

        positions = bridge.get_open_positions()
        if positions:
            lines.append("📋 <b>POSISI TERBUKA SAAT INI (MT5):</b>")
            pos_unit = "USC" if (bridge.is_cent_account() or (acc and ("USC" in str(acc.get("currency", "")).upper() or "CENT" in str(acc.get("currency", "")).upper()))) else "USD"
            for p in positions[:8]:
                icon = "🟢" if p["type"] == "BUY" else "🔴"
                lines.append(
                    f"• {icon} <b>#{p['ticket']} {p['type']} {p['volume']} {p['symbol']}</b>\n"
                    f"  Open: <code>${p['price_open']:,.2f}</code> | Current: <code>${p['price_current']:,.2f}</code>\n"
                    f"  TP: <code>${p['tp']:,.2f}</code> | SL: <code>${p['sl']:,.2f}</code>\n"
                    f"  Floating: <b>{p['profit']:+,.2f} {pos_unit}</b>"
                )
            lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        else:
            lines.append("<i>Tidak ada posisi trading yang sedang terbuka di MT5.</i>")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━")

        lines.extend([
            "<b>PANDUAN KENDALI MT5 DARI HP:</b>",
            "• <code>/mt5 on</code> - Aktifkan eksekusi otomatis",
            "• <code>/mt5 off</code> - Matikan eksekusi otomatis (Standby)",
            "• <code>/mt5 jam 19:00-23:00</code> - Atur jadwal trading aktif",
            "• <code>/mt5 jam all</code> - Kembalikan ke mode 24 jam nonstop",
            "• <code>/mt5 lot 0.02</code> - Ubah ukuran lot transaksi",
            "• <code>/mt5 close &lt;ticket&gt;</code> - Tutup manual posisi aktif",
        ])

        keyboard = [
            [
                InlineKeyboardButton("🟢 24 Jam Nonstop", callback_data="mt5_mode_24h"),
                InlineKeyboardButton("🌙 Malam (19-23 WIB)", callback_data="mt5_mode_night"),
            ],
            [
                InlineKeyboardButton("🔴 Matikan Auto-Trade", callback_data="mt5_toggle_off"),
                InlineKeyboardButton("🔄 Refresh Status", callback_data="mt5_refresh"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_html("\n".join(lines), reply_markup=reply_markup)

    async def chart_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /chart <ticker> [area|candles] untuk menampilkan live chart (TradingView style)."""
        if not await self.check_user_access(update, context):
            return

        raw_args = context.args or []
        args_lower = [a.lower() for a in raw_args]
        req_style = "area" if "area" in args_lower else "candlestick"
        filtered_args = [a for a in raw_args if a.lower() not in ["area", "candle", "candles", "candlestick"]]
        ticker_arg = filtered_args[0].upper().strip() if filtered_args else "XAUUSD"

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

        await update.message.reply_html(f"📈 <i>Menyiapkan visual live chart ({req_style.upper()}) untuk <b>{disp_ticker}</b>...</i>")

        def _generate():
            interval = "15m"
            period = "5d" if is_gold else "60d"
            df = fetcher.get_data(clean_ticker, interval=interval, period=period, force_fetch=True if is_gold else False)
            if df.empty or len(df) < 15:
                df = fetcher.get_data(clean_ticker, interval="1d", period="1y", force_fetch=True if is_gold else False)
            if df.empty or len(df) < 15:
                return None, None, None, None, None

            df_ind = TechnicalIndicators.add_all_indicators(df)
            strategy = get_strategy("DayTrading_Intraday_Momentum") or DEFAULT_STRATEGY
            engine = SignalEngine([strategy])
            sig = engine.evaluate_bar(df_ind, ticker=clean_ticker, strategy=strategy)

            # Hitung level TP & SL acuan jika belum ada (misal status HOLD / Konsolidasi)
            tp_val = sig.take_profit_price
            sl_val = sig.stop_loss_price
            is_bearish = "bearish" in (sig.market_direction_prediction or "").lower() or sig.signal == "SELL"

            if not tp_val or not sl_val:
                if is_gold:
                    if is_bearish:
                        tp_val = round(sig.price * (1.0 - 0.008), 3)
                        sl_val = round(sig.price * (1.0 + 0.004), 3)
                    else:
                        tp_val = round(sig.price * (1.0 + 0.008), 3)
                        sl_val = round(sig.price * (1.0 - 0.004), 3)
                else:
                    tp_val = round(sig.price * 1.03, 0)
                    sl_val = round(sig.price * 0.98, 0)

            chart_path = ChartGenerator.generate_chart(
                df=df_ind,
                ticker_symbol=clean_ticker,
                interval=interval,
                chart_style=req_style,
                signal_type=sig.signal if sig.signal in ["BUY", "SELL"] else ("SELL" if is_bearish else "BUY"),
                entry_price=sig.price,
                tp_price=tp_val,
                sl_price=sl_val,
                setup_grade=sig.setup_grade,
                pdf_confluence_score=sig.pdf_confluence_score,
            )
            tv_quote = df.attrs.get("tradingview_quote") or {}
            return chart_path, sig, tp_val, sl_val, tv_quote

        chart_path, sig, tp_val, sl_val, tv_quote = await asyncio.to_thread(_generate)
        if not chart_path or not Path(chart_path).exists():
            await update.message.reply_text(f"Gagal mengambil data pasar atau membuat chart untuk {ticker_arg}.")
            return

        price_fmt = f"${sig.price:,.3f}" if is_gold else f"Rp {sig.price:,.0f}"

        # Hitung persentase TP & SL acuan
        is_sell_dir = tp_val < sig.price
        if is_sell_dir:
            tp_pct = abs((sig.price - tp_val) / sig.price) * 100.0
            sl_pct = abs((sl_val - sig.price) / sig.price) * 100.0
        else:
            tp_pct = abs((tp_val - sig.price) / sig.price) * 100.0
            sl_pct = abs((sig.price - sl_val) / sig.price) * 100.0

        tp_str = f"${tp_val:,.3f} (+{tp_pct:.2f}%)" if is_gold else f"Rp {tp_val:,.0f} (+{tp_pct:.1f}%)"
        sl_str = f"${sl_val:,.3f} (-{sl_pct:.2f}%)" if is_gold else f"Rp {sl_val:,.0f} (-{sl_pct:.1f}%)"

        prev_close_line = ""
        if tv_quote and "prev_close" in tv_quote:
            pc = float(tv_quote["prev_close"])
            cp = float(tv_quote.get("change", 0.0))
            cv = sig.price - pc
            cs = "+" if cv >= 0 else ""
            prev_close_line = f"📉 <b>Prev Close (TradingView):</b> <code>${pc:,.3f}</code> ({cs}${cv:,.3f} / {cs}{cp:.2f}%)\n"

        style_title = "AREA" if req_style == "area" else "CANDLESTICK"
        caption_lines = [
            f"📈 <b>LIVE {style_title} CHART: {disp_ticker}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>Harga Terkini:</b> <code>{price_fmt}</code>",
        ]
        if prev_close_line:
            caption_lines.append(prev_close_line.strip())
        caption_lines.extend([
            f"🎯 <b>Target TP:</b> <code>{tp_str}</code>",
            f"🛑 <b>Batas SL:</b> <code>{sl_str}</code>",
        ])
        if sig.setup_grade:
            clean_g = re.sub(r"^(Grade\s*)+", "", str(sig.setup_grade).strip(), flags=re.IGNORECASE).strip()
            grade_str = f"Grade {clean_g}" if clean_g else ""
            score_num = float(sig.pdf_confluence_score or 0.0)
            if score_num > 100.0:
                score_num /= 100.0
            score_clean = min(100, max(0, int(round(score_num if score_num > 1.0 else score_num * 100.0))))
            caption_lines.append(f"⭐ <b>Kualitas Setup:</b> {grade_str} ({score_clean}%)")
        if sig.market_direction_prediction:
            caption_lines.append(f"🎯 <b>Prediksi Arah:</b> <i>{html.escape(sig.market_direction_prediction)}</i>")

        if is_gold:
            try:
                from trading.mt5_bridge import MT5Bridge
                _bridge = MT5Bridge()
                _open_pos = [p for p in _bridge.get_open_positions() if "XAUUSD" in p.get("symbol", "").upper()]
                if _open_pos:
                    p = _open_pos[0]
                    p_pnl = p.get('profit', 0.0)
                    p_sign = "+" if p_pnl >= 0 else ""
                    caption_lines.append(
                        f"🤖 <b>MT5 Active Order:</b> <code>#{p['ticket']} {p['type']} {p['volume']} lot @ ${p['price_open']:,.2f} ({p_sign}${p_pnl:,.2f})</code>"
                    )
                else:
                    status_text = "Aktif (24 Jam Nonstop)" if _bridge.enabled and _bridge.trading_hours == "all" else ("Aktif" if _bridge.enabled else "Standby")
                    caption_lines.append(f"🤖 <b>MT5 Auto-Trade:</b> <code>{status_text}</code>")
            except Exception:
                pass

        caption_lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        caption_lines.append("💡 <i>Ketik /potensi untuk melihat chart saham & emas yang paling berpotensi.</i>")

        caption = "\n".join(caption_lines)
        if len(caption) > 1020:
            caption = caption[:1020]

        other_style = "candles" if req_style == "area" else "area"
        other_label = "🕯️ Mode Candles" if req_style == "area" else "📈 Mode Area"
        tv_buttons = [
            [
                InlineKeyboardButton(other_label, callback_data=f"chart_{clean_ticker}_{other_style}"),
                InlineKeyboardButton("📊 Buka di TradingView", url=get_tradingview_url(clean_ticker)),
            ]
        ]

        if is_gold:
            try:
                from trading.mt5_bridge import MT5Bridge
                _bridge = MT5Bridge()
                _open_pos = [p for p in _bridge.get_open_positions() if "XAUUSD" in p.get("symbol", "").upper()]
                if _open_pos:
                    p = _open_pos[0]
                    tv_buttons.append([
                        InlineKeyboardButton(
                            f"🛑 Tutup Order MT5 #{p['ticket']} Sekarang",
                            callback_data=f"close_pos_{p['ticket']}"
                        )
                    ])
                else:
                    action_cmd = sig.signal if sig.signal in ["BUY", "SELL"] else ("SELL" if is_bearish else "BUY")
                    tv_buttons.append([
                        InlineKeyboardButton(
                            f"⚡ Eksekusi {action_cmd} di MT5 Sekarang ({_bridge.default_lot:.2f} Lot)",
                            callback_data=f"exec_chart_{action_cmd}_{clean_ticker}_{sig.price}_{tp_val}_{sl_val}"
                        )
                    ])
            except Exception:
                pass

        tv_markup = InlineKeyboardMarkup(tv_buttons)

        try:
            with open(chart_path, "rb") as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=tv_markup,
                )
        except Exception as e:
            logger.error(f"Gagal kirim chart photo: {e}")
            await update.message.reply_html(caption, reply_markup=tv_markup)

    async def potensi_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /potensi dan /radar untuk menyaring dan memunculkan live chart aset paling berpotensi."""
        if not await self.check_user_access(update, context):
            return

        await update.message.reply_html("🔍 <i>Memindai seluruh watchlist saham IDX & Gold untuk mencari setup paling berpotensi (9 Buku PDF)...</i>")

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

                    # Filter kesegaran candle: Tolak jika data candle dari hari kemarin / lampau
                    try:
                        c_ts = pd.to_datetime(sig.candle_time)
                        tz_w = ZoneInfo("Asia/Jakarta")
                        n_w = datetime.now(tz_w)
                        if c_ts.tzinfo is not None:
                            c_ts_w = c_ts.tz_convert(tz_w)
                        else:
                            c_ts_w = c_ts.tz_localize(tz_w)
                        if c_ts_w.date() < n_w.date():
                            continue
                    except Exception:
                        continue

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
                "Saat ini pergerakan harga saham & emas dunia sedang berada di fase konsolidasi / netral (belum memenuhi syarat Grade A/A+ dari 9 buku PDF).\n\n"
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

            tv_item_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("📊 Buka di TradingView", url=get_tradingview_url(t))
            ]])

            c_path = item["chart_path"]
            if c_path and Path(c_path).exists():
                try:
                    with open(c_path, "rb") as photo:
                        await update.message.reply_photo(
                            photo=photo,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            reply_markup=tv_item_markup,
                        )
                except Exception as e:
                    logger.error(f"Gagal kirim foto potensi {t}: {e}")
                    await update.message.reply_html(caption, reply_markup=tv_item_markup)
            else:
                await update.message.reply_html(caption, reply_markup=tv_item_markup)

    async def handle_ticker_chat_analysis(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_ticker: str,
        user_name: str,
    ) -> None:
        """Handler analisis kilat saham / emas natural language chat."""
        from data.fetcher import DataFetcher
        from indicators.technical import TechnicalIndicators
        from strategy.rules import get_strategy, DEFAULT_STRATEGY
        from strategy.signal_engine import SignalEngine
        from notify.chat_agent import ChatAgent
        import asyncio

        fetcher = DataFetcher(storage=self.storage)
        clean_ticker = fetcher.normalize_ticker(target_ticker)
        is_gold = any(k in clean_ticker for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        disp_ticker = "XAU/USD (Gold Spot)" if is_gold else clean_ticker.replace(".JK", "")

        wait_msg = await update.message.reply_html(f"🔍 <i>Menganalisa pergerakan data real-time & sinyal untuk <b>{disp_ticker}</b>...</i>")

        def _compute():
            interval = "15m"
            period = "5d" if is_gold else "60d"
            df = fetcher.get_data(clean_ticker, interval=interval, period=period, force_fetch=True if is_gold else False)
            if df.empty or len(df) < 15:
                df = fetcher.get_data(clean_ticker, interval="1d", period="1y", force_fetch=True if is_gold else False)
            if df.empty or len(df) < 15:
                return None

            df_ind = TechnicalIndicators.add_all_indicators(df)
            strategy = get_strategy("DayTrading_Intraday_Momentum") or DEFAULT_STRATEGY
            engine = SignalEngine([strategy])
            sig = engine.evaluate_bar(df_ind, ticker=clean_ticker, strategy=strategy)

            # Hitung persentase perubahan harga
            last_close = float(df_ind.iloc[-1]["Close"])
            prev_close = float(df_ind.iloc[-2]["Close"]) if len(df_ind) >= 2 else last_close
            change_pct = ((last_close - prev_close) / max(prev_close, 0.01)) * 100.0

            # Level acuan TP & SL
            is_bearish = "bearish" in (sig.market_direction_prediction or "").lower() or sig.signal == "SELL"
            tp_val = sig.take_profit_price
            sl_val = sig.stop_loss_price
            if not tp_val or not sl_val:
                if is_gold:
                    if is_bearish:
                        tp_val = round(sig.price * (1.0 - 0.008), 2)
                        sl_val = round(sig.price * (1.0 + 0.004), 2)
                    else:
                        tp_val = round(sig.price * (1.0 + 0.008), 2)
                        sl_val = round(sig.price * (1.0 - 0.004), 2)
                else:
                    tp_val = round(sig.price * 1.03, 0)
                    sl_val = round(sig.price * 0.98, 0)

            rrr_val = sig.risk_reward_ratio
            if not rrr_val and tp_val and sl_val:
                dist_tp = abs(tp_val - sig.price)
                dist_sl = abs(sig.price - sl_val)
                rrr_val = round(dist_tp / max(dist_sl, 0.01), 2)

            return {
                "sig": sig,
                "change_pct": change_pct,
                "tp_val": tp_val,
                "sl_val": sl_val,
                "rrr_val": rrr_val,
            }

        res = await asyncio.to_thread(_compute)
        if not res:
            await wait_msg.edit_text(f"Waduh bor, data untuk {disp_ticker} lagi ga bisa diakses dari feed bursa. Coba beberapa saat lagi ya!")
            return

        sig = res["sig"]
        analysis_text = ChatAgent.generate_ticker_analysis_response(
            ticker=clean_ticker,
            price=sig.price,
            signal=sig.signal,
            change_pct=res["change_pct"],
            setup_grade=sig.setup_grade,
            pdf_confluence_score=sig.pdf_confluence_score,
            indicators=sig.indicators_snapshot,
            tp_price=res["tp_val"],
            sl_price=res["sl_val"],
            rrr=res["rrr_val"],
            prediction=sig.market_direction_prediction,
            reasons=sig.reasons,
            user_name=user_name,
        )

        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Buka Live Chart", callback_data=f"chart_{clean_ticker}_candles"),
                InlineKeyboardButton("🕯️ Pola Candlestick", callback_data=f"candle_{clean_ticker}"),
            ],
            [
                InlineKeyboardButton("📈 Buka di TradingView", url=get_tradingview_url(clean_ticker)),
            ]
        ])

        try:
            await wait_msg.edit_text(analysis_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        except Exception:
            await update.message.reply_html(analysis_text, reply_markup=reply_markup)

    async def handle_stance_chat(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_ticker: str,
        user_name: str,
    ) -> None:
        """Handler pertanyaan 'lu buy or sell' / posisi terkini bot."""
        from data.fetcher import DataFetcher
        from indicators.technical import TechnicalIndicators
        from strategy.rules import get_strategy, DEFAULT_STRATEGY
        from strategy.signal_engine import SignalEngine
        from notify.chat_agent import ChatAgent
        import asyncio

        fetcher = DataFetcher(storage=self.storage)
        clean_ticker = fetcher.normalize_ticker(target_ticker)
        is_gold = any(k in clean_ticker for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        disp_ticker = "XAU/USD (Gold Spot)" if is_gold else clean_ticker.replace(".JK", "")

        def _eval():
            interval = "15m"
            period = "5d" if is_gold else "60d"
            df = fetcher.get_data(clean_ticker, interval=interval, period=period, force_fetch=True if is_gold else False)
            if df.empty or len(df) < 15:
                df = fetcher.get_data(clean_ticker, interval="1d", period="1y", force_fetch=True if is_gold else False)
            if df.empty or len(df) < 15:
                return None
            df_ind = TechnicalIndicators.add_all_indicators(df)
            strategy = get_strategy("DayTrading_Intraday_Momentum") or DEFAULT_STRATEGY
            engine = SignalEngine([strategy])
            sig = engine.evaluate_bar(df_ind, ticker=clean_ticker, strategy=strategy)
            return sig

        sig = await asyncio.to_thread(_eval)
        if not sig:
            await update.message.reply_text(f"Waduh bor, feed data untuk {disp_ticker} lagi ga bisa diakses nih. Coba sebentar lagi ya!")
            return

        tp_val = sig.take_profit_price
        sl_val = sig.stop_loss_price
        if not tp_val or not sl_val:
            is_bearish = "bearish" in (sig.market_direction_prediction or "").lower() or sig.signal == "SELL"
            if is_gold:
                if is_bearish:
                    tp_val = round(sig.price * (1.0 - 0.008), 2)
                    sl_val = round(sig.price * (1.0 + 0.004), 2)
                else:
                    tp_val = round(sig.price * (1.0 + 0.008), 2)
                    sl_val = round(sig.price * (1.0 - 0.004), 2)
            else:
                tp_val = round(sig.price * 1.03, 0)
                sl_val = round(sig.price * 0.98, 0)

        stance_text = ChatAgent.generate_stance_response(
            ticker=clean_ticker,
            price=sig.price,
            signal=sig.signal,
            setup_grade=sig.setup_grade,
            pdf_confluence_score=sig.pdf_confluence_score,
            indicators=sig.indicators_snapshot,
            tp_price=tp_val,
            sl_price=sl_val,
            prediction=sig.market_direction_prediction,
            reasons=sig.reasons,
            user_name=user_name,
        )

        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Buka Live Chart", callback_data=f"chart_{clean_ticker}_candles"),
                InlineKeyboardButton("🕯️ Pola Candlestick", callback_data=f"candle_{clean_ticker}"),
            ],
            [
                InlineKeyboardButton("📈 Buka di TradingView", url=get_tradingview_url(clean_ticker)),
            ]
        ])
        await update.message.reply_html(stance_text, reply_markup=reply_markup)

    async def handle_entry_advice_chat(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_ticker: str,
        user_name: str,
    ) -> None:
        """Handler pertanyaan timing masuk posisi (boleh masuk sekarang ga)."""
        from data.fetcher import DataFetcher
        from indicators.technical import TechnicalIndicators
        from strategy.rules import get_strategy, DEFAULT_STRATEGY
        from strategy.signal_engine import SignalEngine
        from notify.chat_agent import ChatAgent
        import asyncio

        fetcher = DataFetcher(storage=self.storage)
        clean_ticker = fetcher.normalize_ticker(target_ticker)
        is_gold = any(k in clean_ticker for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        disp_ticker = "XAU/USD (Gold Spot)" if is_gold else clean_ticker.replace(".JK", "")

        def _eval():
            interval = "15m"
            period = "5d" if is_gold else "60d"
            df = fetcher.get_data(clean_ticker, interval=interval, period=period, force_fetch=True if is_gold else False)
            if df.empty or len(df) < 15:
                df = fetcher.get_data(clean_ticker, interval="1d", period="1y", force_fetch=True if is_gold else False)
            if df.empty or len(df) < 15:
                return None
            df_ind = TechnicalIndicators.add_all_indicators(df)
            strategy = get_strategy("DayTrading_Intraday_Momentum") or DEFAULT_STRATEGY
            engine = SignalEngine([strategy])
            sig = engine.evaluate_bar(df_ind, ticker=clean_ticker, strategy=strategy)
            return sig

        sig = await asyncio.to_thread(_eval)
        if not sig:
            await update.message.reply_text(f"Waduh bor, feed data untuk {disp_ticker} lagi ga bisa diakses nih.")
            return

        tp_val = sig.take_profit_price
        sl_val = sig.stop_loss_price
        advice_text = ChatAgent.generate_entry_advice_response(
            ticker=clean_ticker,
            price=sig.price,
            signal=sig.signal,
            indicators=sig.indicators_snapshot,
            tp_price=tp_val,
            sl_price=sl_val,
            user_name=user_name,
        )

        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Buka Live Chart", callback_data=f"chart_{clean_ticker}_candles"),
                InlineKeyboardButton("🕯️ Pola Candlestick", callback_data=f"candle_{clean_ticker}"),
            ]
        ])
        await update.message.reply_html(advice_text, reply_markup=reply_markup)

    async def handle_price_check_chat(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_ticker: str,
        user_name: str,
    ) -> None:
        """Handler pertanyaan cek harga live."""
        from data.fetcher import DataFetcher
        from notify.chat_agent import ChatAgent
        import asyncio

        fetcher = DataFetcher(storage=self.storage)
        clean_ticker = fetcher.normalize_ticker(target_ticker)

        def _eval():
            interval = "15m"
            is_gold = any(k in clean_ticker for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
            period = "5d" if is_gold else "60d"
            df = fetcher.get_data(clean_ticker, interval=interval, period=period, force_fetch=True if is_gold else False)
            if df.empty or len(df) < 5:
                df = fetcher.get_data(clean_ticker, interval="1d", period="1y", force_fetch=True if is_gold else False)
            if df.empty or len(df) < 2:
                return None
            last_close = float(df.iloc[-1]["Close"])
            prev_close = float(df.iloc[-2]["Close"])
            chg = ((last_close - prev_close) / max(prev_close, 0.01)) * 100.0
            return last_close, chg

        res = await asyncio.to_thread(_eval)
        if not res:
            await update.message.reply_text("Waduh bor, harga terkini lagi ga bisa diambil dari feed bursa.")
            return

        price, chg = res
        price_text = ChatAgent.generate_price_response(
            ticker=clean_ticker,
            price=price,
            change_pct=chg,
            signal="HOLD",
            user_name=user_name,
        )
        await update.message.reply_html(price_text)

    async def update_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /update atau /gitpull untuk menarik kodingan terbaru dari GitHub & reload otomatis."""
        if not await self.check_user_access(update, context):
            return

        if not self._is_admin(update):
            await update.message.reply_html("⛔ <i>Perintah /update hanya dapat dijalankan oleh Admin/Owner bot.</i>")
            return

        from scheduler.auto_updater import GitAutoUpdater
        BASE_DIR = Path(__file__).resolve().parent.parent
        updater = GitAutoUpdater(base_dir=BASE_DIR, branch="main", auto_restart=True, notifier=self)

        is_force = bool(context.args and context.args[0].lower() in ["force", "f", "paksa"])
        status_msg = await update.message.reply_html("🔄 <i>Memeriksa pembaruan kodingan dari GitHub origin/main...</i>")

        def _do_update():
            return updater.manual_update(force=is_force)

        import asyncio
        success, message, restarted = await asyncio.to_thread(_do_update)

        if success and restarted:
            await status_msg.edit_text(
                f"✅ <b>Pembaruan Berhasil Ditarik!</b>\n\n"
                f"📝 <b>Commit Terbaru:</b>\n<code>{html.escape(message)}</code>\n\n"
                f"🚀 <i>Me-restart proses bot secara mulus sekarang... Bot akan aktif kembali dengan fitur baru dalam 2-3 detik!</i>",
                parse_mode=ParseMode.HTML,
            )
        elif success and not restarted:
            await status_msg.edit_text(
                f"ℹ️ <b>Repository Sudah Up-to-Date!</b>\n\n"
                f"📝 <b>Commit Terakhir:</b>\n<code>{html.escape(message)}</code>\n\n"
                f"💡 <i>Tidak ada kodingan baru di remote. Gunakan <code>/update force</code> jika ingin memaksa git pull ulang.</i>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await status_msg.edit_text(
                f"❌ <b>Gagal Menarik Pembaruan:</b>\n\n"
                f"<code>{html.escape(message)}</code>",
                parse_mode=ParseMode.HTML,
            )

    async def handle_news_stance_chat(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        news_type: str,
        user_stance: Optional[str],
        user_name: str,
    ) -> None:
        """Handler pertanyaan arah / posisi news ('Nfp sell', 'nfp buy', 'arah nfp kemana')."""
        from data.economic_calendar import EconomicCalendar
        from strategy.news_predictor import NewsPredictor
        from data.fetcher import DataFetcher
        from notify.chat_agent import ChatAgent
        import asyncio

        await update.message.reply_html(f"Sebentar ya {user_name}! 🔍 Gue lagi cek data kalender, konsensus & analisa teknikal pre-news buat <b>{news_type}</b>...")

        def _fetch_stance_data():
            cal = EconomicCalendar(storage=self.storage)
            cal.sync_calendar()
            events = cal.get_this_week_schedule()

            fetcher = DataFetcher(storage=self.storage)
            df_gold = fetcher.get_data("XAUUSD", interval="15m", period="5d", force_fetch=True)
            live_price = float(df_gold["Close"].iloc[-1]) if not df_gold.empty else 4300.0

            target_ev = None
            if events:
                nt_lower = news_type.lower()
                for ev in events:
                    ev_title = str(ev.get("title", "")).lower()
                    ev_type = str(ev.get("news_type", "")).lower()
                    if nt_lower in ev_type or nt_lower in ev_title:
                        target_ev = ev
                        break
                if not target_ev:
                    target_ev = events[0]

            closest_analysis = None
            chart_path = None
            if target_ev:
                closest_analysis = NewsPredictor.analyze_pre_news(target_ev, live_gold_price=live_price, df_gold=df_gold)
                chart_path = NewsPredictor.generate_pre_news_chart(closest_analysis, df=df_gold)

            return target_ev, closest_analysis, chart_path, live_price

        target_ev, closest_analysis, chart_path, live_price = await asyncio.to_thread(_fetch_stance_data)

        if not closest_analysis:
            await update.message.reply_html(
                f"Waduh {user_name}, belum ada data rilis ekonomi untuk <b>{news_type}</b> dalam waktu dekat. "
                "Untuk saat ini XAU/USD lebih dipengaruhi oleh level support/resisten teknikal murni bor!"
            )
            return

        rec = closest_analysis.get("primary_recommendation", "BUY")
        conf = int(closest_analysis.get("confidence_pct", 80))
        setup = closest_analysis.get("trade_setup", {})
        ev_title = target_ev.get("title", news_type) if target_ev else news_type
        ev_wib = target_ev.get("date_wib", "") if target_ev else ""

        stance_reply = ChatAgent.generate_news_stance_response(
            news_type=news_type,
            user_stance=user_stance,
            prediction=rec,
            confidence=conf,
            live_price=live_price,
            entry=setup.get("entry", live_price),
            tp1=setup.get("tp1", live_price + 20),
            sl=setup.get("sl", live_price - 15),
            news_title=ev_title,
            release_wib=ev_wib,
            user_name=user_name,
        )

        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Buka Live Chart", callback_data="chart_XAUUSD_candles"),
                InlineKeyboardButton("🕯️ Pola Candlestick", callback_data="candle_XAUUSD"),
            ],
            [
                InlineKeyboardButton("📈 Buka di TradingView", url=get_tradingview_url("XAUUSD")),
            ],
        ])

        if chart_path and Path(chart_path).exists():
            safe_cap = stance_reply
            overflow_text = None
            if len(stance_reply) > 1020:
                cut_idx = stance_reply.rfind("\n", 0, 950)
                if cut_idx == -1:
                    cut_idx = 950
                safe_cap = stance_reply[:cut_idx] + "\n...\n<i>(Lanjutan penjelasan di bawah 👇)</i>"
                overflow_text = stance_reply[cut_idx:].strip()

            try:
                with open(chart_path, "rb") as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption=safe_cap,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup,
                    )
                if overflow_text:
                    await update.message.reply_html(overflow_text)
                return
            except Exception as e:
                logger.error(f"Gagal kirim photo pre-news chart di chat: {e}")

        await update.message.reply_html(stance_reply, reply_markup=reply_markup)

    async def chat_message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler pesan teks percakapan natural (bahasa gaul) & interaksi seluruh fitur bot."""
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

            tv_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("📊 Buka di TradingView", url=get_tradingview_url(clean_ticker))
            ]])

            try:
                with open(chart_path, "rb") as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption=caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=tv_markup,
                    )
            except Exception as e:
                logger.error(f"Gagal kirim chart photo via chat: {e}")
                await update.message.reply_html(caption, reply_markup=tv_markup)
            return

        # 2. Intent CANDLE: Pengguna meminta analisis pola candlestick & price action
        if intent == "CANDLE":
            context.args = [target_ticker or "XAUUSD"]
            await self.candle_command(update, context)
            return

        # 3. Intent STANCE: Pengguna bertanya "lu buy or sell?", "buy apa sell?", "posisi lu apa?"
        if intent == "STANCE":
            target_ticker = target_ticker or "XAUUSD"
            await self.handle_stance_chat(update, context, target_ticker, user_name)
            return

        # 4. Intent ENTRY_ADVICE: Pengguna bertanya "bisa masuk sekarang ga?", "aman buy ga?"
        if intent == "ENTRY_ADVICE":
            target_ticker = target_ticker or "XAUUSD"
            await self.handle_entry_advice_chat(update, context, target_ticker, user_name)
            return

        # 5. Intent PRICE_CHECK: Pengguna bertanya harga live instrumen
        if intent == "PRICE_CHECK":
            target_ticker = target_ticker or "XAUUSD"
            await self.handle_price_check_chat(update, context, target_ticker, user_name)
            return

        # 6. Intent CURHAT_LOSS, CURHAT_PROFIT, IDENTITY
        if intent in ["CURHAT_LOSS", "CURHAT_PROFIT", "IDENTITY"]:
            reply_text = ChatAgent.generate_chat_response(intent=intent, user_name=user_name, raw_text=user_text)
            await update.message.reply_html(reply_text)
            return

        # 7. Intent ANALYSIS: Pengguna menanyakan kondisi / analisa saham atau emas tertentu
        if intent == "ANALYSIS":
            target_ticker = target_ticker or "XAUUSD"
            await self.handle_ticker_chat_analysis(update, context, target_ticker, user_name)
            return

        # 8. Intent MT5: Pengguna menanyakan status akun / autotrade MT5
        if intent == "MT5":
            await self.mt5_command(update, context)
            return

        # 5. Intent SCAN: Pengguna meminta scan pasar
        if intent == "SCAN":
            await self.scan_command(update, context)
            return

        # 6. Intent POTENSI: Pengguna meminta info saham/emas yang sedang berpotensi
        if intent == "POTENSI":
            await self.potensi_command(update, context)
            return

        # 7. Intent GOLD: Pengguna menanyakan seputar emas
        if intent == "GOLD":
            await self.gold_command(update, context)
            return

        # 8. Intent WINRATE: Pengguna menanyakan winrate / akurasi
        if intent == "WINRATE":
            await self.winrate_command(update, context)
            return

        # 9. Intent HARIAN: Pengguna menanyakan rekomendasi harian
        if intent == "HARIAN":
            await self.harian_command(update, context)
            return

        # 10. Intent HISTORY: Pengguna menanyakan riwayat sinyal
        if intent == "HISTORY":
            await self.lasthistory_command(update, context)
            return

        # 11. Intent WATCHLIST: Pengguna menanyakan daftar watchlist
        if intent == "WATCHLIST":
            await self.watchlist_command(update, context)
            return

        # 12. Intent TUTUP: Pengguna menanyakan laporan tutup saham
        if intent == "TUTUP":
            await self.tutup_command(update, context)
            return

        # 13. Intent NEWS_STANCE: Pengguna menanyakan arah / sikap terhadap news ("Nfp sell", "nfp buy", "arah nfp kemana")
        if intent == "NEWS_STANCE":
            news_type = classification.get("news_type", "NFP")
            user_stance = classification.get("user_stance")
            await self.handle_news_stance_chat(update, context, news_type, user_stance, user_name)
            return

        # 14. Intent UPDATE: Pengguna meminta update kodingan / git pull via chat ("update bot", "git pull", "tarik update")
        if intent == "UPDATE":
            await self.update_command(update, context)
            return

        # 15. Intent NEWS: Pengguna menanyakan jadwal news atau prediksi FOMC/CPI/NFP
        if intent == "NEWS":
            await self.news_command(update, context)
            return

        # 14. Intent COPIER: Pengguna menanyakan cara pasang copier / copy trade
        if intent == "COPIER":
            user_text_low = user_text.lower()
            direct_request_words = ["minta", "kirim", "download", "unduh", "ambil", "file", "zip", "dapatkan", "bagi"]
            if any(w in user_text_low for w in direct_request_words):
                await self.copier_command(update, context)
                return

            is_adm = self._is_admin(update)
            reply_text = ChatAgent.generate_copier_guide_response(user_name=user_name, is_admin=is_adm)
            kb = [
                [InlineKeyboardButton("📥 Unduh member_copier.zip Sekarang", callback_data="copier_download")]
            ]
            if is_adm:
                kb.append([InlineKeyboardButton("📦 Broadcast File Copier VIP", callback_data="sendcopier_all")])
            await update.message.reply_html(reply_text, reply_markup=InlineKeyboardMarkup(kb))
            return

        # 15. Intent LICENSE: Pengguna menanyakan status lisensi / masa aktif
        if intent == "LICENSE":
            await self.license_command(update, context)
            return

        # 16. Intent EDUCATION: Edukasi strategi trading 9 buku PDF & Money Management
        if intent == "EDUCATION":
            subtopic = classification.get("subtopic", "9_pdf")
            reply_text = ChatAgent.generate_education_response(topic=subtopic, user_name=user_name)
            await update.message.reply_html(reply_text)
            return

        # 17. Intent MENU: Pengguna menanyakan menu / panduan fitur obrolan
        if intent == "MENU":
            reply_text = ChatAgent.generate_menu_response(user_name=user_name)
            await update.message.reply_html(reply_text)
            return

        # 18. Intent STATUS: Pengguna menanyakan status bot
        if intent == "STATUS":
            reply_text = ChatAgent.generate_chat_response(intent="STATUS", user_name=user_name, raw_text=user_text)
            await update.message.reply_html(reply_text)
            return

        # 19. Default: GREETING, THANKS, CHITCHAT
        reply_text = ChatAgent.generate_chat_response(intent=intent, user_name=user_name, raw_text=user_text)
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
            comp_analysis = None
            chart_path = None
            closest_ev = None
            if events:
                now_utc = datetime.now(timezone.utc)
                now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")
                upcoming_events = [e for e in events if e.get("date_utc", "") >= now_str]
                nfp_candidates = [
                    e for e in (upcoming_events or events)
                    if "non-farm employment change" in str(e.get("title", "")).lower()
                ]
                major_events = [
                    e for e in (upcoming_events or events)
                    if e.get("impact") == "High" or e.get("news_type") in ["NFP", "CPI", "FOMC", "PCE"]
                ]
                closest_ev = nfp_candidates[0] if nfp_candidates else (major_events[0] if major_events else (upcoming_events[0] if upcoming_events else events[0]))
                closest_analysis = NewsPredictor.analyze_pre_news(closest_ev, live_gold_price=live_price, df_gold=df_gold)
                comp_analysis = NewsPredictor.comprehensive_news_analysis(
                    news_event=closest_ev,
                    live_gold_price=live_price,
                    calendar_events=events,
                )
                chart_path = NewsPredictor.generate_pre_news_chart(closest_analysis, df=df_gold)

            return events, closest_analysis, comp_analysis, chart_path, live_price, closest_ev

        events, closest_analysis, comp_analysis, chart_path, live_price, closest_ev = await asyncio.to_thread(_fetch_news)

        if not events:
            await update.message.reply_html(
                "📅 <b>JADWAL HIGH-IMPACT NEWS:</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Tidak ada jadwal berita High Impact (FOMC, CPI, NFP) dalam beberapa hari ke depan.\n"
                "Pasar cenderung bergerak dengan dominasi analisa teknikal murni."
            )
            return

        tv_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Buka di TradingView", url=get_tradingview_url("XAUUSD")),
            InlineKeyboardButton("🕯️ Pola Candlestick", callback_data="candle_XAUUSD"),
        ]])

        if comp_analysis:
            main_text = comp_analysis["formatted_output"]
            if chart_path and Path(chart_path).exists():
                try:
                    with open(chart_path, "rb") as photo:
                        await update.message.reply_photo(
                            photo=photo,
                            caption=f"📈 <b>Live Pre-News Chart: {html.escape(closest_ev.get('title', 'NFP'))}</b>",
                            parse_mode=ParseMode.HTML,
                        )
                except Exception as e:
                    logger.error(f"Gagal kirim chart photo: {e}")
            await update.message.reply_html(main_text, reply_markup=tv_markup)
            return

        # Fallback format jika analisis belum tersedia
        lines = [
            "📅 <b>JADWAL HIGH-IMPACT NEWS (FOMC / CPI / PCE / NFP / TRUMP / OIL)</b> 🌎",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>Harga Live XAU/USD:</b> <code>${live_price:,.2f}</code>",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for idx, ev in enumerate(events[:5], 1):
            t_wib = ev.get("date_wib", "-")
            fc = ev.get("forecast") or "-"
            pv = ev.get("previous") or "-"
            lines.append(f"<b>{idx}. {ev.get('news_type', 'NEWS')}</b>: <b>{html.escape(ev.get('title', ''))}</b>")
            lines.append(f"   ⏰ Waktu: <code>{t_wib} WIB</code>")
            lines.append(f"   📊 Forecast: <code>{fc}</code> | Prev: <code>{pv}</code>")
            lines.append("──────────────────────")
        await update.message.reply_html("\n".join(lines), reply_markup=tv_markup)


async def set_menu_commands(application: Application) -> None:
    """Mendaftarkan tombol Menu perintah interaktif di aplikasi Telegram."""
    from telegram import BotCommand
    commands = [
        BotCommand("chart", "📈 Live Candlestick Chart (Gold / Saham)"),
        BotCommand("potensi", "🔥 Radar Live Chart Paling Berpotensi"),
        BotCommand("news", "📰 Jadwal & Prediksi Pre-News (FOMC/CPI/NFP)"),
        BotCommand("harian", "🎯 Rekomendasi Sinyal Trading Harian (TP & SL)"),
        BotCommand("winrate", "📊 Statistik Akurasi Win / Lose Rate Bot"),
        BotCommand("laporan", "📋 Laporan Hasil Rekomendasi (TP/SL) & Akurasi"),
        BotCommand("candle", "🕯️ Bedah Pola Candlestick & Price Action"),
        BotCommand("gold", "🥇 Analisis Sinyal Emas Dunia (XAU/USD)"),
        BotCommand("mt5", "🤖 Dashboard Auto-Trade MetaTrader 5 (MT5)"),
        BotCommand("tutup", "🔔 Laporan Penutupan Pasar Saham (BEI) Simpel"),
        BotCommand("scan", "🔍 Pindai Sinyal Pasar Sekarang"),
        BotCommand("watchlist", "📋 Saham Potensial Cuan & Harga"),
        BotCommand("status", "⚙️ Status Bot & Strategi Aktif"),
        BotCommand("lasthistory", "📜 Riwayat Sinyal & Transaksi MT5"),
        BotCommand("history", "📊 Rekap Transaksi Real MT5 & Hasil Sinyal"),
        BotCommand("copier", "📦 Unduh Auto-Copier MT5 & Panduan Member"),
        BotCommand("update", "🔄 Auto Git Pull & Reload Kodingan Terbaru"),
        BotCommand("help", "ℹ️ Panduan Penggunaan Bot"),
    ]
    try:
        await application.bot.set_my_commands(commands)
    except Exception as e:
        logger.debug(f"Gagal mengatur menu perintah bot: {e}")


async def on_bot_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Error handler terpusat untuk menangani error tak terduga pada polling Telegram."""
    from telegram.error import Conflict, NetworkError, TimedOut
    if isinstance(context.error, Conflict):
        logger.warning(
            "⚠️ [Conflict Handled] Terdeteksi ada lebih dari 1 proses bot aktif bersamaan (multi-instance). "
            "Bot otomatis menyinkronkan koneksi..."
        )
        return
    if isinstance(context.error, (NetworkError, TimedOut)):
        logger.warning(f"⚠️ [Network Handled] Masalah koneksi sementara ke Telegram API: {context.error}")
        return
    logger.error(f"Telegram Bot Error: {context.error}")


def build_telegram_application() -> Optional[Application]:
    """Membuat dan mengonfigurasi aplikasi bot Telegram dengan seluruh CommandHandler."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or "your_telegram" in token:
        logger.warning("Token Telegram belum disetel, bot listener tidak dapat dijalankan.")
        return None

    app = Application.builder().token(token).post_init(set_menu_commands).build()
    app.add_error_handler(on_bot_error)
    cmd_handler = TelegramBotCommands()

    app.add_handler(CommandHandler(["start", "help"], cmd_handler.start_command))
    app.add_handler(CommandHandler(["copier", "downloadcopier", "unduhcopier", "getcopier", "zip", "filecopier", "download"], cmd_handler.copier_command))
    app.add_handler(CommandHandler(["chart", "grafik", "livechart"], cmd_handler.chart_command))
    app.add_handler(CommandHandler(["potensi", "radar", "topsetup"], cmd_handler.potensi_command))
    app.add_handler(CommandHandler(["news", "fomc", "cpi", "nfp", "kalender"], cmd_handler.news_command))
    app.add_handler(CommandHandler(["harian", "tradingharian", "daytrade"], cmd_handler.harian_command))
    app.add_handler(CommandHandler(["winrate", "performance", "akurasi", "laporan", "evaluasi"], cmd_handler.winrate_command))
    app.add_handler(CommandHandler(["candle", "candlestick", "pola"], cmd_handler.candle_command))
    app.add_handler(CommandHandler(["gold", "xau", "emas"], cmd_handler.gold_command))
    app.add_handler(CommandHandler(["mt5", "autotrade", "akun", "account"], cmd_handler.mt5_command))
    app.add_handler(CommandHandler(["tutup", "closesaham", "laporansaham"], cmd_handler.tutup_command))
    app.add_handler(CommandHandler("status", cmd_handler.status_command))
    app.add_handler(CommandHandler("scan", cmd_handler.scan_command))
    app.add_handler(CommandHandler("watchlist", cmd_handler.watchlist_command))
    app.add_handler(CommandHandler(["lasthistory", "history", "riwayat", "rekap"], cmd_handler.lasthistory_command))
    app.add_handler(CommandHandler(["approve", "izinkan", "setujui"], cmd_handler.approve_command))
    app.add_handler(CommandHandler(["extend", "perpanjang", "tambah"], cmd_handler.extend_command))
    app.add_handler(CommandHandler(["reject", "kick", "cabut", "blokir"], cmd_handler.reject_command))
    app.add_handler(CommandHandler(["delete", "hapus", "purge"], cmd_handler.delete_command))
    app.add_handler(CommandHandler(["users", "member", "members", "kelola"], cmd_handler.users_command))
    app.add_handler(CommandHandler(["sendcopier", "broadcastcopier", "kirimcopier"], cmd_handler.sendcopier_command))
    app.add_handler(CommandHandler(["update", "gitpull", "pull", "sync"], cmd_handler.update_command))

    app.add_handler(CommandHandler(["license", "lisensi", "auth_check"], cmd_handler.license_command))
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
            app.run_polling(stop_signals=None, bootstrap_retries=-1)
        except Exception:
            app.run_polling(bootstrap_retries=-1)
    else:
        logger.error("Gagal menjalankan bot: Token Telegram tidak valid.")
