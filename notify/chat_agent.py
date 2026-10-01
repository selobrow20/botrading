"""
Modul Percakapan Gaul (Chat Agent) untuk Bot Trading Telegram.
Mendukung interaksi bahasa santai / gaul ("bor", "bro", santai, akrab)
serta deteksi otomatis seluruh fitur bot: live chart, analisa saham/emas kilat,
pola candlestick 9 buku, autotrade MT5, radar potensi, trading harian, news, winrate,
rekap history, edukasi strategi PDF, dan copier.
"""

import re
import html
from typing import Dict, Any, Optional, Tuple, List
from config.settings import setup_logger

logger = setup_logger("chat_agent")

# Stopwords bahasa Indonesia (termasuk kata 4 huruf umum) agar tidak salah dideteksi sebagai ticker saham IDX
STOPWORDS_4 = {
    "yang", "dari", "pada", "bisa", "kamu", "dong", "juga", "sama", "buat", "biar",
    "kalo", "udah", "lagi", "mau", "akan", "tapi", "gini", "gitu", "saya", "kita",
    "sini", "sana", "mana", "hari", "pagi", "sore", "siap", "oke", "bro", "bor",
    "live", "view", "plot", "oleh", "atau", "para", "saja", "kini", "tiap",
    "pake", "coba", "baru", "naik", "turun", "sell", "hold", "exit", "arah",
    "buku", "skor", "loss", "open", "post", "read", "send", "chat", "look", "show",
    "cuan", "akun", "fibo", "baca", "luar", "bela", "bawa", "kaya", "beda", "cara",
    "tahu", "jika", "kian", "asal", "usah", "peta", "bagi", "lalu", "rasa", "agar",
    "baik", "pula", "mari", "maka", "jadi", "ikut", "kali", "luas", "pasti", "kapan",
    "nanti", "punya", "bikin", "lama", "lewat", "dulu", "minta", "order", "pola",
    "kumo", "zona", "atas", "area", "rent", "kaki", "ekor", "body", "stop", "time",
    "rate", "gain", "info", "link", "help", "menu", "rule", "save", "real", "auto",
    "feed", "sync", "data", "pipe", "line", "risk", "free", "demo", "step", "news",
    "fomc", "nfp", "brent", "pce", "cpe", "wti", "opec", "bank", "duit", "user",
    "gitu", "bagi", "kalo", "ajah", "ajah", "tuh", "deh", "nih", "kok", "kan",
}

# Daftar ticker saham IDX populer & watchlist sistem
KNOWN_IDX_TICKERS = {
    "BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "TLKM", "ASII", "ICBP", "UNVR", "ADRO",
    "PTBA", "PGAS", "ANTM", "INCO", "MEDC", "BREN", "GOTO", "AMMN", "BRPT", "TPIA",
    "KLBF", "CPIN", "UNTR", "AKRA", "ACES", "MIKA", "MYOR", "SIDO", "INKP", "TKIM",
    "ESSA", "MBMA", "HRUM", "MDKA", "TOWR", "TBIG", "SMGR", "INTP", "EXCL", "ISAT",
    "ARTO", "TINS", "BRMS", "AMRT", "BUKA", "ELSA", "DOID", "RAJA", "PBSA",
}


class ChatAgent:
    """Agen percakapan bahasa gaul dengan integrasi seluruh fitur sistem trading."""

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
        if re.search(r"\b(saham|chart|grafik|analisa|prospek|sinyal|rekomendasi)\s+cuan\b|\bcuan\s+(saham|chart|grafik|analisa)\b", text_lower):
            return "CUAN.JK"

        # 4. Cek Saham dengan prefix eksplisit (misal "saham abcd" atau "emiten bbca")
        prefix_match = re.search(r"\b(?:saham|emiten|kode|ticker)\s+([a-zA-Z]{4})\b", text_lower)
        if prefix_match:
            candidate = prefix_match.group(1).upper()
            if candidate.lower() not in STOPWORDS_4 or candidate in KNOWN_IDX_TICKERS:
                return f"{candidate}.JK"

        # 5. Cek Saham IDX yang Cocok dengan Daftar Ticker Dikenal
        words = re.findall(r"\b[a-zA-Z]{4}\b", text_lower)
        for w in words:
            w_upper = w.upper()
            if w_upper in KNOWN_IDX_TICKERS:
                return f"{w_upper}.JK"

        # 6. Cek Kata 4 Huruf Apapun yang Bukan Stopwords Bahasa Indonesia
        for w in words:
            if w not in STOPWORDS_4:
                return f"{w.upper()}.JK"

        return None

    @classmethod
    def classify_intent(cls, text: str) -> Dict[str, Any]:
        """
        Mengklasifikasikan maksud (intent) dari kalimat pengguna ke dalam seluruh fitur bot.
        """
        text_lower = text.lower()
        extracted_ticker = cls.extract_ticker(text)

        # 1. Deteksi Permintaan Chart (Prioritas Tertinggi jika ada kata kunci chart/grafik/plot)
        chart_keywords = [
            "chart", "grafik", "candlestick chart", "minta chart",
            "tampilin chart", "tampilkan chart", "liat chart", "kirim chart",
            "view chart", "plot", "gambarin", "mana chart", "cek chart",
            "foto chart", "gambar chart", "tampil chart",
        ]
        if any(k in text_lower for k in chart_keywords):
            target_ticker = extracted_ticker or "XAUUSD"
            return {
                "intent": "CHART",
                "ticker": target_ticker,
                "is_gold": "XAU" in target_ticker or "GOLD" in target_ticker,
            }

        # 2. Deteksi Permintaan Analisis Pola Candlestick & Price Action (9 Buku)
        candle_keywords = [
            "pola candle", "candlestick", "ada pinbar", "engulfing", "pola rejection",
            "wick ratio", "cek candle", "baca candle", "rejection candle", "pola doji",
            "hammer", "shooting star", "order block candle", "fvg candle", "pola candlestick",
        ]
        is_candle_phrase = any(k in text_lower for k in candle_keywords)
        # Atau konteks "candle <ticker>" misal "candle bbca" / "candle xau"
        is_candle_with_ticker = bool(re.search(r"\bcandle\s+[a-zA-Z]{3,7}\b", text_lower))
        if is_candle_phrase or is_candle_with_ticker:
            target_ticker = extracted_ticker or "XAUUSD"
            return {
                "intent": "CANDLE",
                "ticker": target_ticker,
                "is_gold": "XAU" in target_ticker or "GOLD" in target_ticker,
            }

        # 3. Deteksi Pertanyaan High-Impact News & Kalender Ekonomi
        news_keywords = [
            "news", "fomc", "cpi", "pce", "cpe", "nfp", "inflasi", "suku bunga", "the fed",
            "non farm", "nonfarm", "unemployment", "kalender", "berita ekonomi",
            "jadwal news", "prediksi news", "kapan news", "berita",
            "trump", "trump spike", "tarif", "trade war", "oil", "minyak", "wti", "brent", "opec",
        ]
        if any(k in text_lower for k in news_keywords):
            return {
                "intent": "NEWS",
                "ticker": "XAUUSD",
            }

        # 4. Deteksi Copier / Copy Trade MT5 (Sebelum deteksi MT5 umum)
        copier_keywords = [
            "copier", "copy trade", "copytrade", "ea copier", "client copier",
            "cara pasang copier", "script copier", "minta copier", "telegramsignalreceiver",
            "cara copy", "panduan copier", "download copier",
        ]
        if any(k in text_lower for k in copier_keywords):
            return {
                "intent": "COPIER",
                "ticker": None,
            }

        # 5. Deteksi MT5 / Auto-Trading / Posisi Akun
        mt5_keywords = [
            "mt5", "autotrade", "auto trade", "autotrading", "auto-trade",
            "akun mt5", "posisi mt5", "posisi terbuka", "open position", "floating",
            "saldo mt5", "equity mt5", "margin mt5", "lot mt5", "robot mt5",
            "auto trading", "eksekusi mt5",
        ]
        if any(k in text_lower for k in mt5_keywords):
            return {
                "intent": "MT5",
                "ticker": None,
            }

        # 6. Deteksi Permintaan Potensi / Radar
        potensi_keywords = [
            "potensi", "berpotensi", "radar", "saham apa yang bagus", "ada sinyal",
            "ada setup", "rekomendasi cuan", "yang cakep apa", "setup hari ini",
            "cariin saham", "saham mana yang naik", "ada peluang", "pantauan bagus",
            "top setup", "screening",
        ]
        if any(k in text_lower for k in potensi_keywords):
            return {
                "intent": "POTENSI",
                "ticker": None,
            }

        # 7. Deteksi Pertanyaan Trading Harian / Day Trade
        harian_keywords = [
            "trading harian", "sinyal hari ini", "day trade", "scalping",
            "rekomendasi harian", "masuk apa hari ini", "buy apa hari ini", "setup harian",
        ]
        if any(k in text_lower for k in harian_keywords):
            return {
                "intent": "HARIAN",
                "ticker": None,
            }

        # 8. Deteksi Scan On-Demand Pasar / Watchlist
        scan_keywords = [
            "scan pasar", "scan saham", "pindai pasar", "pindai saham",
            "cek semua saham", "scan semua", "running scan", "skrining saham",
        ]
        if any(k in text_lower for k in scan_keywords) or re.search(r"\bscan\b", text_lower):
            return {
                "intent": "SCAN",
                "ticker": None,
            }

        # 9. Deteksi Pertanyaan Khusus Gold / Emas
        gold_keywords = ["emas", "gold", "xau", "xauusd", "xau/usd", "harga emas", "arah emas", "prospek emas"]
        if any(re.search(rf"\b{re.escape(k)}\b", text_lower) for k in gold_keywords):
            return {
                "intent": "GOLD",
                "ticker": "XAUUSD",
            }

        # 10. Deteksi Tutup Saham / Laporan Posisi Ditutup (Sebelum winrate / laporan umum)
        tutup_keywords = ["tutup saham", "closesaham", "posisi saham ditutup", "laporan penutupan", "rekap tutup"]
        if any(k in text_lower for k in tutup_keywords):
            return {
                "intent": "TUTUP",
                "ticker": None,
            }

        # 11. Deteksi Pertanyaan Win Rate / Akurasi / Laporan Hasil TP/SL
        winrate_keywords = [
            "winrate", "win rate", "akurasi", "banyak win apa lose",
            "performa", "rekam jejak", "win lose", "lose rate",
            "laporan", "evaluasi", "hasil rekomendasi", "pantau hasil", "hasil sinyal",
            "udah tp", "udah sl", "kena tp", "kena sl", "riwayat tp", "riwayat sl",
            "performa bot",
        ]
        if any(k in text_lower for k in winrate_keywords):
            return {
                "intent": "WINRATE",
                "ticker": None,
            }

        # 12. Deteksi Riwayat Transaksi / Rekap Sinyal (Last History)
        history_keywords = [
            "riwayat", "history", "rekap sinyal", "lasthistory", "catatan sinyal",
            "sinyal kemarin", "rekap trading", "hasil trade kemarin", "rekap kemarin",
        ]
        if any(k in text_lower for k in history_keywords):
            return {
                "intent": "HISTORY",
                "ticker": None,
            }

        # 13. Deteksi Watchlist
        watchlist_keywords = ["watchlist", "daftar saham", "pantauan saham", "saham apa aja", "list saham", "saham pantauan"]
        if any(k in text_lower for k in watchlist_keywords):
            return {
                "intent": "WATCHLIST",
                "ticker": None,
            }

        # 14. Deteksi Lisensi / Status Akun Member
        license_keywords = [
            "lisensi", "masa aktif", "cek akun", "sisa waktu", "expired",
            "kapan habis", "status member", "cek lisensi", "masa berlaku",
        ]
        if any(k in text_lower for k in license_keywords):
            return {
                "intent": "LICENSE",
                "ticker": None,
            }

        # 15. Deteksi Edukasi / Konsep 9 Buku PDF Trading & Money Management
        edu_fibo = ["fibonacci", "fibo", "golden pocket", "golden zone", "0.618"]
        edu_volman = ["volman", "bob volman", "price action volman", "buildup"]
        edu_ichi = ["ichimoku", "kumo", "awan ichimoku", "tenkan", "kijun"]
        edu_smc = ["smart money", "order block", "fair value gap", "fvg", "bos", "break of structure"]
        edu_grade = ["grade a+", "grade a", "grade b", "apa itu grade", "konfluensi", "confluence score"]
        edu_mm = ["money management", "hitung lot", "manajemen risiko", "kenapa sl", "stop loss", "risk reward", "rrr"]
        edu_pdf = ["9 buku", "9 pdf", "sembilan buku", "buku trading", "metode 9 buku", "pdf trading", "buku apa aja"]

        if any(k in text_lower for k in edu_pdf):
            return {"intent": "EDUCATION", "subtopic": "9_pdf", "ticker": None}
        if any(k in text_lower for k in edu_fibo):
            return {"intent": "EDUCATION", "subtopic": "fibo", "ticker": None}
        if any(k in text_lower for k in edu_volman):
            return {"intent": "EDUCATION", "subtopic": "volman", "ticker": None}
        if any(k in text_lower for k in edu_ichi):
            return {"intent": "EDUCATION", "subtopic": "ichimoku", "ticker": None}
        if any(k in text_lower for k in edu_smc):
            return {"intent": "EDUCATION", "subtopic": "smc", "ticker": None}
        if any(k in text_lower for k in edu_grade):
            return {"intent": "EDUCATION", "subtopic": "grade", "ticker": None}
        if any(k in text_lower for k in edu_mm):
            return {"intent": "EDUCATION", "subtopic": "risk_management", "ticker": None}

        # 16. Deteksi Menu / Bantuan / Pertanyaan Kemampuan Bot
        menu_keywords = [
            "fitur", "kamu bisa apa", "bisa bantu apa", "bisa ngapain",
            "menu", "help", "bantuan", "panduan", "command apa aja",
            "cara pakai", "apa aja fiturnya", "perintah",
        ]
        if any(k in text_lower for k in menu_keywords):
            return {
                "intent": "MENU",
                "ticker": None,
            }

        # 17. Deteksi Status Bot
        status_keywords = ["status", "jalan ga", "aktif ga", "masih hidup", "lagi nyala", "kesehatan bot", "server bot"]
        if any(k in text_lower for k in status_keywords):
            return {
                "intent": "STATUS",
                "ticker": None,
            }

        # 18. Deteksi Ucapan Terima Kasih / Pujian
        thanks_keywords = [
            "makasih", "terima kasih", "tengkyu", "mantap", "keren",
            "gokil", "jago", "top", "nice", "sip", "jos", "juara",
        ]
        if any(k in text_lower for k in thanks_keywords):
            return {
                "intent": "THANKS",
                "ticker": None,
            }

        # 19. Deteksi Sapaan Murni (Greeting)
        greeting_keywords = [
            "halo", "hai", "hei", "pagi", "siang", "sore", "malam",
            "assalamualaikum", "oy", "oi",
        ]
        if any(re.search(rf"\b{k}\b", text_lower) for k in greeting_keywords):
            return {
                "intent": "GREETING",
                "ticker": None,
            }

        # 20. Deteksi Permintaan Analisis Saham Tertentu
        # Jika ada ticker terdeteksi dalam kalimat tanya/percakapan
        if extracted_ticker:
            return {
                "intent": "ANALYSIS",
                "ticker": extracted_ticker,
                "is_gold": "XAU" in extracted_ticker or "GOLD" in extracted_ticker,
            }

        # 21. Default: Obrolan Umum (Chitchat)
        return {
            "intent": "CHITCHAT",
            "ticker": None,
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
    def generate_ticker_analysis_response(
        cls,
        ticker: str,
        price: float,
        signal: str,
        change_pct: float = 0.0,
        setup_grade: str = "",
        pdf_confluence_score: float = 0.0,
        indicators: Optional[Dict[str, float]] = None,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        rrr: Optional[float] = None,
        prediction: Optional[str] = None,
        reasons: Optional[List[str]] = None,
        user_name: str = "Bor",
    ) -> str:
        """Menghasilkan teks analisa kilat instrumen (saham / emas) dalam gaya gaul yang informatif."""
        indicators = indicators or {}
        reasons = reasons or []
        is_gold = any(k in ticker.upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])
        disp_name = "XAU/USD (Gold Spot)" if is_gold else ticker.replace(".JK", "")

        price_fmt = f"${price:,.2f}" if is_gold else f"Rp {price:,.0f}"
        sign_change = "+" if change_pct >= 0 else ""
        chg_fmt = f"({sign_change}{change_pct:.2f}%)"

        # Badge Sinyal
        if signal == "BUY":
            sig_badge = "🟢 <b>REKOMENDASI: BUY (Akumulasi / Momentum)</b>"
        elif signal == "SELL":
            sig_badge = "🔴 <b>REKOMENDASI: SELL (Distribusi / Reversal)</b>"
        else:
            sig_badge = "⏳ <b>REKOMENDASI: WAIT / HOLD (Tunggu Setup Konfirmasi)</b>"

        lines = [
            f"Nih bor {user_name}, hasil analisa kilat buat <b>{disp_name}</b>: 🔍⚡",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>Harga Sekarang:</b> <code>{price_fmt}</code> {chg_fmt}",
            f"🚦 {sig_badge}",
        ]

        if setup_grade:
            conf_pct = int(pdf_confluence_score * 100)
            lines.append(f"⭐ <b>Kualitas Setup:</b> <b>Grade {setup_grade}</b> ({conf_pct}% Konfluensi 9 Buku)")

        if prediction:
            lines.append(f"🎯 <b>Proyeksi Arah:</b> <i>{html.escape(prediction)}</i>")

        # Indikator Teknikal
        rsi_val = indicators.get("rsi", 50.0)
        ema20 = indicators.get("ema_20", price)
        ema50 = indicators.get("ema_50", price)
        vol_ratio = indicators.get("volume_ratio", 1.0)

        if rsi_val < 30:
            rsi_desc = "Oversold (Potensi Rebound)"
        elif rsi_val > 70:
            rsi_desc = "Overbought (Waspada Koreksi)"
        else:
            rsi_desc = "Zona Sehat / Netral"

        trend_desc = "Tren Bullish (Di atas EMA 20)" if price >= ema20 else "Tren Bearish / Koreksi (Di bawah EMA 20)"

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📊 <b>Kondisi Indikator Kunci:</b>",
            f"• <b>RSI (14):</b> <code>{rsi_val:.1f}</code> — <i>{rsi_desc}</i>",
            f"• <b>EMA 20 & 50:</b> <i>{trend_desc}</i>",
            f"• <b>Volume Ratio:</b> <code>{vol_ratio:.2f}x</code> rata-rata 20 periode",
        ])

        # Trading Plan (TP / SL / RRR)
        if tp_price and sl_price:
            tp_fmt = f"${tp_price:,.2f}" if is_gold else f"Rp {tp_price:,.0f}"
            sl_fmt = f"${sl_price:,.2f}" if is_gold else f"Rp {sl_price:,.0f}"
            pct_tp = abs((tp_price - price) / max(price, 0.01)) * 100.0
            pct_sl = abs((price - sl_price) / max(price, 0.01)) * 100.0
            rrr_val = rrr if rrr else (pct_tp / max(pct_sl, 0.01))

            lines.extend([
                "━━━━━━━━━━━━━━━━━━━━━━",
                "🎯 <b>Rencana Trading (Trading Plan):</b>",
                f"• <b>Target TP:</b> <code>{tp_fmt}</code> (+{pct_tp:.2f}%)",
                f"• <b>Batas SL:</b> <code>{sl_fmt}</code> (-{pct_sl:.2f}%)",
                f"• <b>Risk/Reward Ratio (RRR):</b> <code>1 : {rrr_val:.2f}</code>",
            ])

        if reasons:
            top_reasons = reasons[:2]
            lines.append("💡 <b>Pemicu Sinyal:</b> " + "; ".join(html.escape(r) for r in top_reasons))

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━",
            "💡 <i>Gimana bor? Kalau mau liat bentuk chart visual atau pola candlestick-nya, klik tombol di bawah ya! Selalu disiplin pasang SL! 🔥</i>",
        ])
        return "\n".join(lines)

    @classmethod
    def generate_education_response(cls, topic: str = "9_pdf", user_name: str = "Bor") -> str:
        """Menghasilkan materi edukasi & filosofi trading 9 buku PDF dalam bahasa santai."""
        if topic == "9_pdf":
            return (
                f"Yo {user_name}! 📚 Sistem bot trading kita ini bukan pake tebak-tebakan atau dukun ya bor, "
                f"tapi mengintegrasikan kaidah dari <b>9 Buku Trading Legendaris Dunia</b>:\n\n"
                f"1. <b>Bob Volman</b> — Price Action Scalping (20 EMA & Buildup Breakout)\n"
                f"2. <b>Al Brooks</b> — Reading Price Charts Bar by Bar (Market Structure)\n"
                f"3. <b>Steve Nison</b> — Japanese Candlestick Techniques (Pinbar Rejection & Engulfing)\n"
                f"4. <b>Manesh Patel</b> — Trading with Ichimoku Clouds (Awan Kumo Support/Resistance)\n"
                f"5. <b>Inner Circle Trader (SMC)</b> — Smart Money Concepts (Order Block & Fair Value Gap)\n"
                f"6. <b>Robert Miner</b> — Dynamic Trading (Fibonacci Golden Pocket 0.618 - 0.65)\n"
                f"7. <b>John Murphy</b> — Technical Analysis of Financial Markets (Trend & Momentum)\n"
                f"8. <b>Thomas Bulkowski</b> — Encyclopedia of Chart Patterns (Double Bottom & Wedges)\n"
                f"9. <b>Mark Douglas</b> — Trading in the Zone (Disiplin Eksekusi & Manajemen Risiko)\n\n"
                f"🎯 <b>Prinsip Konfluensi:</b> Semakin banyak kaidah dari 9 buku di atas yang sepakat pada 1 titik harga, "
                f"skor konfluensi makin tinggi dan sinyal naik level jadi <b>Grade A+ (Bintang 5)</b>! 🔥"
            )

        elif topic == "fibo":
            return (
                f"Nih bor jurus rahasia <b>Fibonacci Golden Pocket (0.618 - 0.65)</b>: 📐✨\n\n"
                f"• Ketika market lagi trending kuat (misal harga Gold melesat naik), jangan kejar harga di pucuk bor!\n"
                f"• Tunggu harga koreksi (pullback) ke area rasio emas <b>61.8% s/d 65%</b> dari swing terakhir.\n"
                f"• Area ini dinamakan <i>Golden Pocket</i> karena di situlah algoritma institusi besar dan bank dunia biasanya meletakkan limit order beli.\n"
                f"• Bot kita otomatis mendeteksi pantulan di Golden Zone ini buat konfirmasi sinyal Grade A+! 🚀"
            )

        elif topic == "volman":
            return (
                f"Ini dia teknik legendaris dari master scalping <b>Bob Volman</b> bor: ⚡📈\n\n"
                f"1. <b>EMA 20 sebagai Dinamo Tren:</b> Selama candle berada di atas EMA 20, kita cuma cari setup BUY. Jangan sekali-kali lawan arus!\n"
                f"2. <b>Pullback Reversal:</b> Menunggu harga mendekati EMA 20 dengan tenang, lalu memantul membentuk candle rejection.\n"
                f"3. <b>Buildup (Kompresi Rapat):</b> Sebelum harga meledak breakout, biasanya ada candle-candle kecil yang merapat di garis EMA 20. Ini sinyal kompresi siap melesat!\n\n"
                f"💡 <i>Di bot kita, jika terdeteksi 'Bob Volman Buildup', itu artinya siap-siap pasang posisi karena momentum besar akan segera rilis!</i>"
            )

        elif topic == "ichimoku":
            return (
                f"Kaidah <b>Ichimoku Kumo Cloud</b> dari Jepang nih bor: ⛅🎌\n\n"
                f"• <b>Di Atas Awan Kumo:</b> Market berada dalam rezim Super Bullish. Fokus cari posisi Buy.\n"
                f"• <b>Di Bawah Awan Kumo:</b> Market berada dalam rezim Bearish. Hati-hati jebakan buy!\n"
                f"• <b>Di Dalam Awan Kumo:</b> Market lagi sideways / berkabut. Bot bakal otomatis menaikkan filter agar tidak kena cut-loss sia-sia.\n"
                f"• Awan Kumo juga bertindak sebagai support & resistance dinamis paling tebal di timeframe 15 menit. 🛡️"
            )

        elif topic == "smc":
            return (
                f"Pahami cara kerja bandar lewat <b>Smart Money Concepts (SMC)</b> bor: 🏦💼\n\n"
                f"1. <b>Order Block (OB):</b> Area candle terakhir sebelum ledakan harga besar, tempat jejak order akumulasi institusi tersimpan.\n"
                f"2. <b>Fair Value Gap (FVG):</b> Ketidakseimbangan harga (*imbalance*) karena lonjakan volume tiba-tiba. Harga punya magnet alami buat nutup gap ini.\n"
                f"3. <b>Break of Structure (BOS):</b> Ketika harga berhasil menembus High/Low struktur sebelumnya, menandakan tren resmi berlanjut.\n\n"
                f"🎯 Bot kita menyaring sinyal trading agar searah dengan arah flow Smart Money, bukan melawan arus bandar! 🌊"
            )

        elif topic == "grade":
            return (
                f"Gini sistem <b>Grading Kualitas Setup (A+, A, B)</b> di bot kita bor: ⭐🎯\n\n"
                f"🌟 <b>Grade A+ (≥75% Konfluensi):</b>\n"
                f"Sinyal kasta tertinggi! Minimal 4 sampai 5 kaidah 9 buku sepakat bersamaan (misal: Fibo Golden Pocket + SMC Order Block + EMA 20 Pullback + Pinbar Rejection). Probabilitas tertinggi!\n\n"
                f"⭐ <b>Grade A (65% - 74% Konfluensi):</b>\n"
                f"Setup solid yang memenuhi syarat eksekusi otomatis MT5 Auto-Trader dan day trade harian.\n\n"
                f"⚡ <b>Grade B (&lt;65% Konfluensi):</b>\n"
                f"Setup biasa / momentum awal. Cocok untuk pantauan watchlist atau tunggu konfirmasi konfluensi tambahan."
            )

        else:
            # risk_management
            return (
                f"Dengerin ini baik-baik bor, ini <b>Kunci Sukses Trader Konsisten (Money Management & SL)</b>: 🛡️💰\n\n"
                f"1. <b>Risk per Trade Maksimal 1-2%:</b> Jangan pernah pertaruhkan lebih dari 2% total modal lu dalam 1 posisi trading.\n"
                f"2. <b>Wajib Pasang Stop Loss (SL):</b> SL itu helm pengaman lu. Trader pro itu bukan yang ga pernah salah, tapi yang kerugiannya selalu terukur saat salah!\n"
                f"3. <b>Risk/Reward Ratio (RRR) Minimal 1:1.5 s/d 1:2:</b> Kalau risiko lu Rp 100 ribu, target profit lu minimal harus Rp 150 - 200 ribu. Dengan RRR ini, win rate 50% aja portofolio lu udah cuan konsisten!\n"
                f"4. <b>Ukuran Lot di MT5:</b> Hitung lot berdasarkan jarak pips ke Stop Loss, bukan asal pencet lot gede demi cepat kaya ya bor! 🧘‍♂️"
            )

    @classmethod
    def generate_copier_guide_response(cls, user_name: str = "Bor", is_admin: bool = False) -> str:
        """Menghasilkan panduan penggunaan MT5 Auto-Copier dalam gaya santai."""
        admin_note = (
            "\n👑 <b>Menu Admin:</b> Karena lu Admin, lu bisa ketik <code>/sendcopier</code> "
            "untuk langsung broadcast file update ke seluruh member aktif!"
            if is_admin else ""
        )
        return (
            f"Halo {user_name}! 🚀 Ini panduan lengkap tentang fitur <b>VIP MT5 Auto-Copier</b>:\n\n"
            f"📦 <b>Apa itu VIP Copier?</b>\n"
            f"Fitur canggih yang bikin laptop/PC/VPS lu otomatis mengeksekusi order buy/sell di MetaTrader 5 "
            f"setiap kali bot mendeteksi sinyal Grade A+ di Telegram secara instan (hitungan milidetik)!\n\n"
            f"⚙️ <b>Cara Pasang Cepat:</b>\n"
            f"1. Pastikan Chat ID Telegram lu sudah terdaftar dan di-approve di bot.\n"
            f"2. Buka folder <code>member_copier</code> atau minta file <code>member_copier.zip</code> ke Admin.\n"
            f"3. Pasang EA <code>TelegramSignalReceiver.mq5</code> di MetaTrader 5 lu & centang <i>'Allow Algo Trading'</i>.\n"
            f"4. Buka file <code>config.json</code>, isi Chat ID lu.\n"
            f"5. Klik dua kali file <code>START_COPIER.bat</code>. Selesai! Bot akan menduplikasi sinyal otomatis ke MT5 lu.{admin_note}\n\n"
            f"Tidur nyenyak, biarkan algoritma yang bekerja buat lu bor! 🤝🔥"
        )

    @classmethod
    def generate_menu_response(cls, user_name: str = "Bor") -> str:
        """Menghasilkan daftar fitur bot yang bisa diajak ngobrol secara natural."""
        return (
            f"Yo {user_name}! 😎 Gue adalah AI Assistant Trading serba bisa. "
            f"Lu bisa ngobrol santai sama gue pake bahasa sehari-hari tanpa harus hafal kode perintah!\n\n"
            f"🔥 <b>CONTOH OBROLAN YANG BISA LU TANYA KE GUE:</b>\n\n"
            f"📊 <b>1. Minta Live Chart Visual:</b>\n"
            f"• <i>'bor minta chart xauusd'</i>\n"
            f"• <i>'tampilin chart bbca dong'</i>\n"
            f"• <i>'kirim live chart bbri'</i>\n\n"
            f"🔍 <b>2. Analisa Kilat Saham & Emas:</b>\n"
            f"• <i>'gimana analisa bbca sekarang?'</i>\n"
            f"• <i>'prospek saham bmri hari ini'</i>\n"
            f"• <i>'menurut lu antm bagus ga bor?'</i>\n"
            f"• <i>'kondisi emas gimana sekarang?'</i>\n\n"
            f"🕯️ <b>3. Bedah Pola Candlestick (9 Buku):</b>\n"
            f"• <i>'cek pola candle xauusd dong'</i>\n"
            f"• <i>'ada pola pinbar atau engulfing di bbri?'</i>\n\n"
            f"🎯 <b>4. Berburu Sinyal & Radar Potensi:</b>\n"
            f"• <i>'ada saham yang berpotensi hari ini?'</i>\n"
            f"• <i>'rekomendasi trading harian apa bor?'</i>\n"
            f"• <i>'scan semua saham dong'</i>\n\n"
            f"🤖 <b>5. Pantau Auto-Trade MT5:</b>\n"
            f"• <i>'gimana posisi akun mt5?'</i>\n"
            f"• <i>'saldo mt5 berapa sekarang?'</i>\n"
            f"• <i>'autotrade mt5 aktif ga bor?'</i>\n\n"
            f"📅 <b>6. Jadwal News & Berita High-Impact:</b>\n"
            f"• <i>'kapan rilis data fomc atau cpi?'</i>\n"
            f"• <i>'ada berita ekonomi apa hari ini?'</i>\n\n"
            f"🏆 <b>7. Akurasi & Rekam Jejak Bot:</b>\n"
            f"• <i>'winrate lu berapa bor?'</i>\n"
            f"• <i>'rekap riwayat trading kemarin'</i>\n\n"
            f"📚 <b>8. Belajar Konsep Trading 9 PDF:</b>\n"
            f"• <i>'apa itu 9 buku pdf?'</i>\n"
            f"• <i>'jelasin fibonacci golden pocket'</i>\n"
            f"• <i>'apa itu smart money dan order block?'</i>\n"
            f"• <i>'kenapa harus selalu pasang stop loss?'</i>\n\n"
            f"📦 <b>9. Fitur Member & Copier:</b>\n"
            f"• <i>'cara pasang copier mt5'</i>\n"
            f"• <i>'cek sisa lisensi saya'</i>\n\n"
            f"Tinggal ketik santai aja bor, gue siap respons 24 jam! 🚀🔥"
        )

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
                f"• <i>'gimana analisa bbca hari ini?'</i>\n"
                f"• <i>'ada saham yang berpotensi ga?'</i>\n"
                f"• <i>'cek posisi akun mt5'</i>\n\n"
                f"Tinggal ngomong aja santai bor, gue siap bantu! 🚀"
            )

        elif intent == "THANKS":
            return (
                f"Sama-sama bor {user_name}! Santai aja, kita cari cuan bareng-bareng. 🤝🔥\n"
                f"Kalau butuh cek chart, tanya analisa saham, atau mau liat setup yang lagi cakep, tinggal colek gue aja ya bor!"
            )

        elif intent == "STATUS":
            return (
                f"Aman terkendali bor! Sistem bot lagi jalan normal, koneksi database SQLite aktif, "
                f"dan pipeline analisa jalan rutin memantau market. Siap berburu sinyal Grade A+ buat lu! 🛡️⚡"
            )

        else:
            # Chitchat default
            return (
                f"Siap bor {user_name}! 😎 Mau ngobrolin trading apa nih hari ini?\n\n"
                f"Lu bisa ketik langsung pertanyaan santai kayak:\n"
                f"👉 <i>'minta chart xau/usd'</i> (buat liat live emas)\n"
                f"👉 <i>'gimana analisa bbca?'</i> (buat analisa saham kilat)\n"
                f"👉 <i>'cek candle gold'</i> (buat bedah pola candlestick)\n"
                f"👉 <i>'ada saham berpotensi ga?'</i> (buat scan setup terbaik)\n"
                f"👉 <i>'gimana posisi mt5?'</i> (buat cek status akun)\n"
                f"👉 <i>'fitur kamu apa aja?'</i> (buat liat daftar lengkap)\n\n"
                f"Gue pantauin terus marketnya buat lu bor! 🚀"
            )
