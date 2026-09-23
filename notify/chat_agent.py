"""
Modul Percakapan Gaul (Chat Agent) untuk Bot Trading Telegram.
Mendukung interaksi bahasa santai / gaul ("bor", "bro", santai, akrab)
serta deteksi otomatis permintaan live chart dan analisis pasar secara natural.
"""

import re
import html
from typing import Dict, Any, Optional, Tuple, List
from config.settings import setup_logger

logger = setup_logger("chat_agent")

# Stopwords 4 huruf bahasa Indonesia agar tidak salah dideteksi sebagai kode saham IDX
STOPWORDS_4 = {
    "yang", "dari", "pada", "bisa", "kamu", "dong", "juga", "sama", "buat", "biar",
    "kalo", "udah", "lagi", "mau", "akan", "tapi", "gini", "gitu", "saya", "kita",
    "sini", "sana", "mana", "hari", "pagi", "sore", "siap", "oke", "bro", "bor",
    "live", "view", "plot", "oleh", "atau", "para", "saja", "kini", "tiap",
    "pake", "coba", "baru", "naik", "turun", "sell", "hold", "exit", "arah",
    "buku", "skor", "loss", "open", "post", "read", "send", "chat", "look", "show",
    "cuan",  # Cuan diperlakukan sebagai slang profit kecuali jika eksplisit 'saham cuan'
}

# Daftar ticker saham IDX populer
KNOWN_IDX_TICKERS = {
    "BBCA", "BBRI", "BMRI", "BBNI", "TLKM", "ASII", "ICBP", "UNVR", "ADRO", "PTBA",
    "PGAS", "ANTM", "INCO", "MEDC", "BREN", "GOTO", "AMMN", "BRPT", "TPIA",
    "KLBF", "CPIN", "UNTR", "AKRA", "ACES", "MIKA", "MYOR", "SIDO", "INKP", "TKIM",
    "ESSA", "MBMA", "HRUM", "MDKA", "TOWR", "TBIG", "SMGR", "INTP", "EXCL", "ISAT",
}


class ChatAgent:
    """Agen percakapan bahasa gaul dengan kemampuan NLU (Natural Language Understanding)."""

    @classmethod
    def extract_ticker(cls, text: str) -> Optional[str]:
        """
        Mengekstrak simbol ticker dari teks percakapan pengguna.
        Mendukung Gold (XAUUSD) dan kode saham IDX 4 huruf.
        """
        text_lower = text.lower()

        # 1. Cek Komoditas Emas Dunia (XAU/USD)
        gold_patterns = [
            r"\bxau\s*/\s*usd\b",
            r"\bxauusd\b",
            r"\bxau\b",
            r"\bgold\b",
            r"\bemas\b",
            r"\bgc\s*=\s*f\b",
        ]
        for pat in gold_patterns:
            if re.search(pat, text_lower):
                return "XAUUSD"

        # 2. Cek Saham IDX Berformat .JK eksplisit (misal BBCA.JK atau CUAN.JK)
        explicit_jk = re.search(r"\b([a-zA-Z]{4})\.jk\b", text_lower)
        if explicit_jk:
            return f"{explicit_jk.group(1).upper()}.JK"

        # 3. Khusus CUAN jika ada konteks saham atau chart
        if re.search(r"\b(saham|chart|grafik)\s+cuan\b|\bcuan\s+(saham|chart|grafik)\b", text_lower):
            return "CUAN.JK"

        # 4. Cek Saham IDX yang Cocok dengan Daftar Ticker Dikenal
        words = re.findall(r"\b[a-zA-Z]{4}\b", text_lower)
        for w in words:
            w_upper = w.upper()
            if w_upper in KNOWN_IDX_TICKERS:
                return f"{w_upper}.JK"

        # 5. Cek Kata 4 Huruf Apapun yang Bukan Stopwords Bahasa Indonesia
        for w in words:
            if w not in STOPWORDS_4:
                return f"{w.upper()}.JK"

        return None

    @classmethod
    def classify_intent(cls, text: str) -> Dict[str, Any]:
        """
        Mengklasifikasikan maksud (intent) dari kalimat pengguna.
        """
        text_lower = text.lower()
        extracted_ticker = cls.extract_ticker(text)

        # 1. Deteksi Permintaan Chart (Prioritas Tertinggi jika ada kata kunci chart/grafik)
        chart_keywords = [
            "chart", "grafik", "candle", "candlestick", "minta chart",
            "tampilin chart", "tampilkan chart", "liat chart", "kirim chart",
            "view chart", "plot", "gambarin", "mana chart", "cek chart",
        ]
        is_chart_request = any(k in text_lower for k in chart_keywords)

        if is_chart_request:
            # Jika user minta chart tapi tidak sebut ticker -> default ke XAUUSD (Gold)
            target_ticker = extracted_ticker or "XAUUSD"
            return {
                "intent": "CHART",
                "ticker": target_ticker,
                "is_gold": "XAU" in target_ticker or "GOLD" in target_ticker,
            }

        # 2. Deteksi Ucapan Terima Kasih / Pujian (Sebelum greeting/chitchat)
        thanks_keywords = [
            "makasih", "terima kasih", "tengkyu", "mantap", "keren",
            "gokil", "jago", "top", "nice", "sip", "jos", "juara",
        ]
        if any(k in text_lower for k in thanks_keywords):
            return {
                "intent": "THANKS",
                "ticker": None,
            }

        # 3. Deteksi Permintaan Potensi / Radar
        potensi_keywords = [
            "potensi", "berpotensi", "radar", "saham apa yang bagus", "ada sinyal",
            "ada setup", "rekomendasi cuan", "yang cakep apa", "setup hari ini",
            "cariin saham", "saham mana yang naik", "ada peluang", "pantauan bagus",
        ]
        if any(k in text_lower for k in potensi_keywords):
            return {
                "intent": "POTENSI",
                "ticker": None,
            }

        # 4. Deteksi Pertanyaan High-Impact News (FOMC, CPI, NFP, Berita Ekonomi)
        news_keywords = [
            "news", "fomc", "cpi", "nfp", "inflasi", "suku bunga", "the fed",
            "non farm", "nonfarm", "unemployment", "kalender", "berita ekonomi",
            "jadwal news", "prediksi news", "kapan news", "berita",
        ]
        if any(k in text_lower for k in news_keywords):
            return {
                "intent": "NEWS",
                "ticker": "XAUUSD",
            }

        # 5. Deteksi Pertanyaan Khusus Gold / Emas
        gold_keywords = ["emas", "gold", "xau", "xauusd", "xau/usd"]
        if any(k in text_lower for k in gold_keywords):
            return {
                "intent": "GOLD",
                "ticker": "XAUUSD",
            }

        # 6. Deteksi Pertanyaan Win Rate / Akurasi
        winrate_keywords = [
            "winrate", "win rate", "akurasi", "banyak win apa lose",
            "performa", "rekam jejak", "win lose", "lose rate",
        ]
        if any(k in text_lower for k in winrate_keywords):
            return {
                "intent": "WINRATE",
                "ticker": None,
            }

        # 6. Deteksi Pertanyaan Trading Harian / Day Trade
        harian_keywords = [
            "trading harian", "sinyal hari ini", "day trade", "scalping",
            "rekomendasi harian", "masuk apa hari ini", "buy apa hari ini",
        ]
        if any(k in text_lower for k in harian_keywords):
            return {
                "intent": "HARIAN",
                "ticker": None,
            }

        # 7. Deteksi Watchlist
        watchlist_keywords = ["watchlist", "daftar saham", "pantauan saham", "saham apa aja", "list saham"]
        if any(k in text_lower for k in watchlist_keywords):
            return {
                "intent": "WATCHLIST",
                "ticker": None,
            }

        # 8. Deteksi Status Bot
        status_keywords = ["status", "jalan ga", "aktif ga", "masih hidup", "lagi nyala"]
        if any(k in text_lower for k in status_keywords):
            return {
                "intent": "STATUS",
                "ticker": None,
            }

        # 9. Deteksi Sapaan Murni (Greeting)
        greeting_keywords = [
            "halo", "hai", "hei", "pagi", "siang", "sore", "malam",
            "assalamualaikum", "oy", "oi",
        ]
        if any(re.search(rf"\b{k}\b", text_lower) for k in greeting_keywords):
            return {
                "intent": "GREETING",
                "ticker": None,
            }

        # 9. Deteksi Ucapan Terima Kasih / Pujian
        thanks_keywords = [
            "makasih", "terima kasih", "tengkyu", "mantap", "keren",
            "gokil", "jago", "top", "nice", "sip", "jos", "juara",
        ]
        if any(k in text_lower for k in thanks_keywords):
            return {
                "intent": "THANKS",
                "ticker": None,
            }

        # 10. Default: Obrolan Umum (Chitchat)
        return {
            "intent": "CHITCHAT",
            "ticker": extracted_ticker,
        }

    @classmethod
    def generate_chart_caption(
        cls,
        ticker: str,
        price: float,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        setup_grade: Optional[str] = None,
        pdf_confluence_score: Optional[float] = None,
        prediction: Optional[str] = None,
    ) -> str:
        """Menghasilkan caption gambar chart dalam gaya bahasa gaul yang ramah dan keren."""
        is_gold = any(k in ticker.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        disp_name = "XAU/USD (Gold Spot)" if is_gold else ticker.replace(".JK", "")
        price_fmt = f"${price:,.2f}" if is_gold else f"Rp {price:,.0f}"

        lines = [
            f"Nih bor, live chart <b>{disp_name}</b> pesenan lu udah siap! 🚀",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>Harga Sekarang:</b> <code>{price_fmt}</code>",
        ]

        if tp_price and sl_price:
            tp_fmt = f"${tp_price:,.2f}" if is_gold else f"Rp {tp_price:,.0f}"
            sl_fmt = f"${sl_price:,.2f}" if is_gold else f"Rp {sl_price:,.0f}"
            pct_tp = ((tp_price - price) / max(price, 0.01)) * 100.0
            pct_sl = ((price - sl_price) / max(price, 0.01)) * 100.0
            sign_tp = "+" if pct_tp > 0 else ""
            sign_sl = "-" if pct_sl > 0 else "+"

            lines.append(f"🎯 <b>Target TP:</b> <code>{tp_fmt}</code> ({sign_tp}{pct_tp:.2f}%)")
            lines.append(f"🛑 <b>Batas SL:</b> <code>{sl_fmt}</code> ({sign_sl}{abs(pct_sl):.2f}%)")

        if setup_grade:
            conf_pct = int((pdf_confluence_score or 0) * 100)
            lines.append(f"⭐ <b>Kualitas Setup:</b> Grade {setup_grade} ({conf_pct}% Konfluensi)")

        if prediction:
            lines.append(f"🎯 <b>Arah Market:</b> <i>{html.escape(prediction)}</i>")

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━",
            "💡 <i>Garis kuning EMA 20 & RSI udah gue plot di chart ya bor. Disiplin pasang SL biar trading lu tetap aman! Gaskeun! 🔥</i>",
        ])
        return "\n".join(lines)

    @classmethod
    def generate_chat_response(cls, intent: str, user_name: str = "Bor", extra: Optional[Dict[str, Any]] = None) -> str:
        """Menghasilkan teks balasan percakapan santai berbahasa gaul sesuai intent."""
        extra = extra or {}

        if intent == "GREETING":
            return (
                f"Yo halo {user_name}! 😎\n\n"
                f"Gue standby 24 jam nih mantau pergerakan Gold sama saham-saham IDX.\n"
                f"Ada yang mau lu cek bor? Misalnya:\n"
                f"• <i>'bor minta chart xau/usd'</i>\n"
                f"• <i>'tampilin chart bbca dong'</i>\n"
                f"• <i>'ada saham yang berpotensi ga hari ini?'</i>\n\n"
                f"Tinggal ngomong aja santai bor, gue siap bantu! 🚀"
            )

        elif intent == "THANKS":
            return (
                f"Sama-sama bor! Santai aja, kita cari cuan bareng-bareng. 🤝🔥\n"
                f"Kalau butuh cek chart atau mau tanya setup yang lagi cakep, tinggal colek gue aja ya bor!"
            )

        elif intent == "STATUS":
            return (
                f"Aman terkendali bor! Sistem bot lagi jalan normal, koneksi database SQLite aktif, "
                f"dan pipeline analisa jalan rutin setiap 15 menit. Siap berburu sinyal Grade A+ buat lu! 🛡️⚡"
            )

        else:
            # Chitchat default
            return (
                f"Siap bor! 😎 Mau cek chart apa nih hari ini?\n\n"
                f"Lu bisa ketik langsung kayak:\n"
                f"👉 <i>'minta chart xau/usd'</i> (buat liat live emas)\n"
                f"👉 <i>'chart bbri live bor'</i> (buat liat saham)\n"
                f"👉 <i>'ada yang berpotensi ga bor'</i> (buat scan setup terbaik)\n\n"
                f"Gue pantauin terus marketnya buat lu bor!"
            )
