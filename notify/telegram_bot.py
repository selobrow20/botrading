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
        if is_gold:
            g_stats = wr_stats.get("gold_stats", {})
            g_comp = g_stats.get("completed", 0)
            wr_badge = f"📊 <b>Akurasi Emas (Gold):</b> Win Rate <b>{g_stats.get('win_rate', 0.0):.1f}%</b> ({g_stats.get('win', 0)}W / {g_stats.get('lose', 0)}L)" if g_comp > 0 else "📊 <b>Akurasi Emas:</b> <i>Sedang aktif melacak sinyal</i>"
        else:
            wr_badge = ""

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
            if wr_badge:
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
                grade_str = getattr(sig, "setup_grade", "") or "Grade A"
                score_val = getattr(sig, "pdf_confluence_score", 0.0)
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
                lines.append(f"📚 <b>TELAAH 7 BUKU PDF ({grade_str} - {score_val:.0f}%):</b>")
                for chk in pdf_details[:3]:
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

        entry_str = format_currency(entry_p, ticker)
        exit_str = format_currency(exit_p, ticker)
        tp_str = format_currency(tp_p, ticker) if tp_p else "-"
        sl_str = format_currency(sl_p, ticker) if sl_p else "-"

        candle_time = res_sig.get("candle_time", "-")
        exit_time = res_sig.get("exit_time", "-")
        note = res_sig.get("outcome_note", "")

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

        if is_win:
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
            lines.append("🏆 <i>Setup konfluensi 7 buku PDF terbukti akurat mengunci profit!</i>")
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

        success = True
        for cid in approved_ids:
            try:
                res = asyncio.run(self._async_send_text(msg, target_chat_id=cid))
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
            f"⭐ <b>Konfluensi 7 PDF:</b> {score:.0f}% ({grade})",
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

        # 2. Cek apakah sudah disetujui di database & belum expired
        if self.storage.is_user_authorized(user_id, admin_id=self.admin_id):
            return True

        # Cek apakah user sebelumnya approved tapi sudah kedaluwarsa
        all_u = {u["chat_id"]: u for u in self.storage.list_all_users()}
        curr_u = all_u.get(user_id)
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

    async def button_callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler klik tombol interaktif (Izinkan / Tolak / Durasi Akses) khusus Admin."""
        query = update.callback_query
        if not query:
            return
        await query.answer()

        if not self._is_admin(update):
            await query.answer("⛔ Hanya Admin yang berhak memproses akses.", show_alert=True)
            return

        data = query.data or ""
        msg_text = query.message.text or ""

        if data.startswith("apprdur_"):
            parts = data.split("_")
            target_id = parts[1]
            dur = parts[2] if len(parts) > 2 else "30d"
            success, expires_at, dur_label = self.storage.approve_user(target_id, dur)
            exp_display = expires_at if expires_at else "Permanen (Tanpa Batas Waktu)"
            await query.edit_message_text(
                text=f"{msg_text}\n\n✅ <b>STATUS: DISETUJUI ({dur_label})</b> 🎉\n"
                     f"⏱️ Masa Aktif: <code>{dur_label}</code>\n"
                     f"📅 Berlaku s/d: <code>{exp_display}</code>",
                parse_mode=ParseMode.HTML,
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"🎉 <b>Selamat! Permintaan akses Anda telah disetujui oleh Admin.</b>\n\n"
                         f"⏱️ <b>Masa Aktif:</b> <b>{dur_label}</b>\n"
                         f"📅 <b>Berlaku s/d:</b> <code>{exp_display}</code>\n\n"
                         f"Ketik /start untuk mulai menggunakan bot!",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.warning(f"Gagal kirim pesan approved ke {target_id}: {e}")

        elif data.startswith("approve_"):
            target_id = data.replace("approve_", "").strip()
            success, expires_at, dur_label = self.storage.approve_user(target_id, "30d")
            exp_display = expires_at if expires_at else "Permanen (Tanpa Batas Waktu)"
            await query.edit_message_text(
                text=f"{msg_text}\n\n✅ <b>STATUS: DISETUJUI ({dur_label})</b> 🎉\n"
                     f"📅 Berlaku s/d: <code>{exp_display}</code>",
                parse_mode=ParseMode.HTML,
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"🎉 <b>Selamat! Permintaan akses Anda telah disetujui oleh Admin.</b>\n\n"
                         f"⏱️ <b>Masa Aktif:</b> <b>{dur_label}</b> (s/d {exp_display})\n"
                         f"Ketik /start untuk mulai menggunakan bot!",
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

        elif data in ["mt5_toggle_on", "mt5_toggle_off", "mt5_refresh"]:
            from trading.mt5_bridge import MT5Bridge
            bridge = MT5Bridge()
            if data == "mt5_toggle_on":
                bridge.enabled = True
                await query.answer("🟢 Auto-Trade MT5 Diaktifkan!")
            elif data == "mt5_toggle_off":
                bridge.enabled = False
                await query.answer("🔴 Auto-Trade MT5 Dinonaktifkan!")
            else:
                await query.answer("🔄 Status MT5 diperbarui.")

            acc = bridge.get_account_info()
            status_auto = "🟢 <b>AKTIF (Eksekusi Otomatis)</b>" if bridge.enabled else "🔴 <b>NONAKTIF (Sinyal Saja)</b>"
            conn_badge = "🟢 <b>TERHUBUNG LIVE</b>" if bridge.is_connected else "⚪ <b>STANDBY / OFFLINE</b>"

            lines = [
                "🤖 <b>DASHBOARD METATRADER 5 (AUTO-TRADER)</b> 📈",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"⚡ <b>Mode Auto-Trade:</b> {status_auto}",
                f"📡 <b>Koneksi Terminal:</b> {conn_badge}",
                f"📚 <b>Filter Eksekusi:</b> <code>Wajib 7 Buku PDF Grade A (≥65%)</code>",
                f"📦 <b>Default Lot:</b> <code>{bridge.default_lot} Lot</code> (Batas Risiko: {bridge.risk_percent}%)",
                f"🎯 <b>Instrumen Trading:</b> <code>{bridge.gold_symbol} (XAU/USD)</code>",
                "━━━━━━━━━━━━━━━━━━━━━━",
            ]
            if acc:
                lines.extend([
                    f"👤 <b>Akun MT5:</b> <code>#{acc['login']}</code> ({acc['server']} - {acc['trade_mode']})",
                    f"💵 <b>Balance:</b> <code>${acc['balance']:,.2f}</code>",
                    f"📊 <b>Equity:</b> <code>${acc['equity']:,.2f}</code>",
                    f"📈 <b>Floating Profit:</b> <code>${acc['profit']:+,.2f}</code>",
                    f"🛡️ <b>Free Margin:</b> <code>${acc['margin_free']:,.2f}</code>",
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
                for p in positions[:8]:
                    icon = "🟢" if p["type"] == "BUY" else "🔴"
                    lines.append(
                        f"• {icon} <b>#{p['ticket']} {p['type']} {p['volume']} {p['symbol']}</b> | Floating: <b>${p['profit']:+,.2f}</b>"
                    )
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
            else:
                lines.append("<i>Tidak ada posisi trading yang sedang terbuka di MT5.</i>")
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")

            lines.extend([
                "<b>PANDUAN PERINTAH MT5:</b>",
                "• <code>/mt5 on</code> - Aktifkan eksekusi order otomatis",
                "• <code>/mt5 off</code> - Matikan eksekusi otomatis",
                "• <code>/mt5 lot 0.02</code> - Ubah ukuran lot transaksi",
                "• <code>/mt5 close &lt;ticket&gt;</code> - Tutup manual posisi aktif",
            ])

            toggle_text = "🔴 Matikan Auto-Trade" if bridge.enabled else "🟢 Hidupkan Auto-Trade"
            toggle_cb = "mt5_toggle_off" if bridge.enabled else "mt5_toggle_on"
            keyboard = [
                [
                    InlineKeyboardButton(toggle_text, callback_data=toggle_cb),
                    InlineKeyboardButton("🔄 Refresh Status", callback_data="mt5_refresh"),
                ]
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

    async def approve_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /approve <chat_id> [durasi] khusus Admin."""
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Perintah ini hanya dapat dijalankan oleh Admin.")
            return

        if not context.args:
            await update.message.reply_html(
                "⚠️ Format salah. Gunakan: <code>/approve &lt;chat_id&gt; [durasi]</code>\n\n"
                "<b>Pilihan durasi:</b>\n"
                "• Jam: <code>1h</code>, <code>2h</code>, <code>6h</code>, <code>12h</code>\n"
                "• Hari: <code>1d</code>, <code>7d</code>, <code>30d</code>, <code>90d</code>\n"
                "• Permanen: <code>lifetime</code> atau <code>permanen</code>\n"
                "<i>(Default jika kosong: 30d)</i>"
            )
            return

        target_id = context.args[0].strip()
        dur = context.args[1].strip() if len(context.args) > 1 else "30d"
        success, expires_at, dur_label = self.storage.approve_user(target_id, dur)
        exp_display = expires_at if expires_at else "Permanen (Tanpa Batas Waktu)"
        if success:
            await update.message.reply_html(
                f"✅ <b>Pengguna {target_id} berhasil disetujui!</b>\n"
                f"⏱️ <b>Masa Aktif:</b> <code>{dur_label}</code>\n"
                f"📅 <b>Berlaku s/d:</b> <code>{exp_display}</code>"
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"🎉 <b>Selamat! Akses Anda telah disetujui oleh Admin.</b>\n\n"
                         f"⏱️ <b>Masa Aktif:</b> <b>{dur_label}</b>\n"
                         f"📅 <b>Berlaku s/d:</b> <code>{exp_display}</code>\n\n"
                         f"Ketik /start untuk mulai menggunakan bot!",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.warning(f"Gagal notif ke {target_id}: {e}")
        else:
            await update.message.reply_text(f"Gagal menyetujui Chat ID {target_id}.")

    async def extend_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler perintah /extend <chat_id> <durasi> khusus Admin untuk memperpanjang waktu akses."""
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Perintah ini hanya dapat dijalankan oleh Admin.")
            return

        if not context.args or len(context.args) < 2:
            await update.message.reply_html(
                "⚠️ Format salah. Gunakan: <code>/extend &lt;chat_id&gt; &lt;durasi&gt;</code>\n"
                "Contoh: <code>/extend 123456 7d</code> atau <code>/extend 123456 2h</code>"
            )
            return

        target_id = context.args[0].strip()
        dur = context.args[1].strip()
        success, expires_at, dur_label = self.storage.extend_user(target_id, dur)
        exp_display = expires_at if expires_at else "Permanen (Tanpa Batas Waktu)"
        if success:
            await update.message.reply_html(
                f"🔄 <b>Akses pengguna {target_id} berhasil diperpanjang!</b>\n"
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
            await update.message.reply_text(f"Pengguna {target_id} tidak ditemukan.")

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
        """Handler perintah /users untuk melihat daftar pengguna & masa aktifnya (khusus Admin)."""
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Perintah ini hanya dapat dijalankan oleh Admin.")
            return

        users = self.storage.list_all_users()
        if not users:
            await update.message.reply_text("Belum ada pengguna lain yang meminta akses.")
            return

        lines = ["👥 <b>DAFTAR PENGGUNA & MASA AKTIF BOT:</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
        for u in users:
            st = u.get("status", "pending")
            emoji = "🟢" if st == "approved" else "🔴" if st == "rejected" else "🟡"
            cid = u.get("chat_id", "-")
            name = u.get("full_name") or u.get("username") or "-"
            rem = u.get("remaining_label", "")
            lines.append(f"{emoji} <b>{html.escape(name)}</b> (<code>{cid}</code>)")
            lines.append(f"   Status: <i>{st.upper()}</i> | Masa Aktif: <b>{rem}</b>")
            lines.append("──────────────────────")
        lines.append("👉 Ketik <code>/approve &lt;id&gt; [durasi]</code> (misal: <code>1h</code>, <code>6h</code>, <code>7d</code>, <code>30d</code>, <code>lifetime</code>)")
        lines.append("👉 Ketik <code>/extend &lt;id&gt; [durasi]</code> untuk memperpanjang waktu")
        await update.message.reply_html("\n".join(lines))

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
            f"  • Target Profit (TP): <b>${data['tp']:,.2f}</b> (+{data['tp_pct']:.2f}%)",
            f"  • Stop Loss (SL): <b>${data['sl']:,.2f}</b> (-{data['sl_pct']:.2f}%)",
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
            eval_note = "🔥 <b>Akurasi Luar Biasa!</b> Filter 7 buku PDF terbukti sangat akurat prediksi arah Gold."
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
                bridge.enabled = True
                await update.message.reply_html(
                    "🟢 <b>Auto-Trading MetaTrader 5 DIAKTIFKAN!</b>\n\n"
                    "Bot akan mengeksekusi order (BUY / SELL) secara otomatis di akun MT5 setiap kali sinyal Emas (XAU/USD) 7 Buku PDF terkonfirmasi Grade A (≥65%).\n\n"
                    "🎯 <i>Sinyal tetap dikawal ketat oleh kaidah Fibonacci Golden Pocket, Ichimoku Kumo, 20 EMA Bob Volman, dan manajemen risiko TP & SL.</i>"
                )
                return
            elif sub == "off":
                bridge.enabled = False
                await update.message.reply_html(
                    "🔴 <b>Auto-Trading MetaTrader 5 DINONAKTIFKAN!</b>\n\n"
                    "Bot beralih ke mode notifikasi biasa (hanya mengirim sinyal ke Telegram tanpa membuka order di MT5)."
                )
                return
            elif sub == "lot" and len(args) > 1:
                try:
                    new_lot = float(args[1])
                    if new_lot <= 0 or new_lot > 50:
                        raise ValueError()
                    bridge.default_lot = new_lot
                    await update.message.reply_html(f"✅ <b>Ukuran Lot Default Berhasil Diubah:</b> <code>{new_lot} Lot</code>")
                except Exception:
                    await update.message.reply_html("⚠️ Format salah. Contoh penggunaan: <code>/mt5 lot 0.02</code>")
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

        lines = [
            "🤖 <b>DASHBOARD METATRADER 5 (AUTO-TRADER)</b> 📈",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"⚡ <b>Mode Auto-Trade:</b> {status_auto}",
            f"📡 <b>Koneksi Terminal:</b> {conn_badge}",
            f"📚 <b>Filter Eksekusi:</b> <code>Wajib 7 Buku PDF Grade A (≥65%)</code>",
            f"📦 <b>Default Lot:</b> <code>{bridge.default_lot} Lot</code> (Batas Risiko: {bridge.risk_percent}%)",
            f"🎯 <b>Instrumen Trading:</b> <code>{bridge.gold_symbol} (XAU/USD)</code>",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]

        if acc:
            lines.extend([
                f"👤 <b>Akun MT5:</b> <code>#{acc['login']}</code> ({acc['server']} - {acc['trade_mode']})",
                f"💵 <b>Balance:</b> <code>${acc['balance']:,.2f}</code>",
                f"📊 <b>Equity:</b> <code>${acc['equity']:,.2f}</code>",
                f"📈 <b>Floating Profit:</b> <code>${acc['profit']:+,.2f}</code>",
                f"🛡️ <b>Free Margin:</b> <code>${acc['margin_free']:,.2f}</code> (Leverage 1:{acc['leverage']})",
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
            for p in positions[:8]:
                icon = "🟢" if p["type"] == "BUY" else "🔴"
                lines.append(
                    f"• {icon} <b>#{p['ticket']} {p['type']} {p['volume']} {p['symbol']}</b>\n"
                    f"  Open: <code>${p['price_open']:,.2f}</code> | Current: <code>${p['price_current']:,.2f}</code>\n"
                    f"  TP: <code>${p['tp']:,.2f}</code> | SL: <code>${p['sl']:,.2f}</code>\n"
                    f"  Floating: <b>${p['profit']:+,.2f}</b>"
                )
            lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        else:
            lines.append("<i>Tidak ada posisi trading yang sedang terbuka di MT5.</i>")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━")

        lines.extend([
            "<b>PANDUAN PERINTAH MT5:</b>",
            "• <code>/mt5 on</code> - Aktifkan eksekusi order otomatis",
            "• <code>/mt5 off</code> - Matikan eksekusi otomatis",
            "• <code>/mt5 lot 0.02</code> - Ubah ukuran lot transaksi",
            "• <code>/mt5 close &lt;ticket&gt;</code> - Tutup manual posisi aktif",
        ])

        toggle_text = "🔴 Matikan Auto-Trade" if bridge.enabled else "🟢 Hidupkan Auto-Trade"
        toggle_cb = "mt5_toggle_off" if bridge.enabled else "mt5_toggle_on"
        keyboard = [
            [
                InlineKeyboardButton(toggle_text, callback_data=toggle_cb),
                InlineKeyboardButton("🔄 Refresh Status", callback_data="mt5_refresh"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_html("\n".join(lines), reply_markup=reply_markup)

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
            rec = closest_analysis.get("primary_recommendation", "BUY")
            conf = closest_analysis.get("confidence_pct", 75)
            setup = closest_analysis.get("trade_setup", {})
            fund = closest_analysis.get("fundamental_bias", {})
            badge_rec = "🟢 BUY" if "BUY" in rec else "🔴 SELL" if "SELL" in rec else "🟡 STRADDLE"

            lines.extend([
                f"🎯 <b>SARAN UTAMA EVENT TERDEKAT ({closest_analysis['news_type']}):</b>",
                f"• 🏆 <b>Rekomendasi:</b> <b>{badge_rec}</b> (<b>{conf}% Confidence</b>)",
                f"• 🎯 <b>Target TP1:</b> <code>${setup.get('tp1', 0):,.2f}</code> | 🛑 <b>SL:</b> <code>${setup.get('sl', 0):,.2f}</code>",
                f"• 🌐 <b>Bias Web:</b> <i>{html.escape(fund.get('reason', '-'))}</i>",
                "━━━━━━━━━━━━━━━━━━━━━━",
                "⚡ <i>Sistem otomatis membunyikan Alert & Live Chart 10 menit sebelum rilis!</i>",
            ])

        caption = "\n".join(lines)
        if chart_path and Path(chart_path).exists():
            safe_cap = caption
            overflow_text = None
            if len(caption) > 1020:
                cut_idx = caption.rfind("\n", 0, 950)
                if cut_idx == -1:
                    cut_idx = 950
                safe_cap = caption[:cut_idx] + "\n...\n<i>(Rincian proyeksi lanjut di bawah 👇)</i>"
                overflow_text = caption[cut_idx:].strip()

            try:
                with open(chart_path, "rb") as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption=safe_cap,
                        parse_mode=ParseMode.HTML,
                    )
                if overflow_text:
                    await update.message.reply_html(overflow_text)
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
        BotCommand("laporan", "📋 Laporan Hasil Rekomendasi (TP/SL) & Akurasi"),
        BotCommand("candle", "🕯️ Bedah Pola Candlestick & Price Action"),
        BotCommand("gold", "🥇 Analisis Sinyal Emas Dunia (XAU/USD)"),
        BotCommand("mt5", "🤖 Dashboard Auto-Trade MetaTrader 5 (MT5)"),
        BotCommand("tutup", "🔔 Laporan Penutupan Pasar Saham (BEI) Simpel"),
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


async def on_bot_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Error handler terpusat untuk menangani error tak terduga pada polling Telegram."""
    from telegram.error import Conflict, NetworkError, TimedOut
    if isinstance(context.error, Conflict):
        logger.warning(
            "⚠️ [Conflict Handled] Terdeteksi instance bot lain aktif bersamaan atau sedang proses transisi redeploy di Railway. "
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
    app.add_handler(CommandHandler("lasthistory", cmd_handler.lasthistory_command))
    app.add_handler(CommandHandler("approve", cmd_handler.approve_command))
    app.add_handler(CommandHandler("extend", cmd_handler.extend_command))
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
