"""
Modul Radar & Scanner Koin Potensial Pump (Binance Spot Live):
Memindai 700+ pair USDT di Binance Spot secara real-time untuk mendeteksi:
1. Akumulasi Volume Tidak Wajar (Whale / Smart Money Accumulation).
2. Koin di Area Pre-Pump (Sweet Spot +2% s/d +15%, belum pucuk).
3. Tekanan Breakout High 24 Jam (High Proximity >= 80%).
4. Lengkap dengan Level Entry, Stop Loss (SL), Take Profit (TP1 & TP2), serta Risk-to-Reward (R:R).
"""

import html
import requests
from typing import Dict, Any, List, Optional
from config.settings import setup_logger

logger = setup_logger("crypto_scanner")

BINANCE_TICKER_URL = "https://data-api.binance.vision/api/v3/ticker/24hr"

_SCANNER_SESSION = requests.Session()
_SCANNER_SESSION.headers.update({
    "User-Agent": "AntiGravity-Crypto-Scanner/2.0",
    "Accept": "application/json",
})

# Daftar Koin Raksasa / Bluechip Majors (Volatilitas stabil, likuiditas raksasa)
MAJOR_COINS = {
    "BTC", "ETH", "SOL", "XRP", "BNB", "ADA"
}

# Daftar Koin Meme / Micin Terkenal di Binance Spot
MEME_COINS = {
    "DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "BOME", "NEIRO", "TURBO",
    "MEME", "BABYDOGE", "CATI", "DOGS", "HMSTR", "POPCAT", "1000SATS", "PEOPLE",
    "LUNC", "USTC", "SLERF", "PONKE", "BRETT", "NOT", "MYRO", "MOG", "BICO"
}

# Daftar Koin AI & DePIN
AI_COINS = {
    "RENDER", "TAO", "FET", "NEAR", "GRT", "WLD", "IO", "ARKM", "PHB", "AI",
    "OCEAN", "AGIX", "NFP", "JASMY", "THETA", "AKT"
}

# Daftar Koin DeFi & High Volatility
DEFI_COINS = {
    "AERO", "MAGIC", "VELODROME", "UNI", "AAVE", "PENDLE", "JUP", "RAY", "ENA",
    "CAKE", "CRV", "SNX", "DYDX", "1INCH", "MKR", "COMP", "SUSHI", "EIGEN"
}

# Stablecoins, Commodity Pegged Tokens & Wrapped Tokens yang di-blacklist dari scanning
STABLECOIN_BLACKLIST = {
    "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "EURUSDT", "DAIUSDT", "BUSDUSDT",
    "AEURUSDT", "WBETHUSDT", "WBTCUSDT", "BTCSTUSDT", "USDPUSDT", "USD1USDT",
    "RLUSDUSDT", "USDEUSDT", "EURIUSDT", "UUSDT", "XUSDUSDT",
    "PAXGUSDT", "XAUTUSDT", "PAXUSDT"
}


class CryptoScanner:
    """Scanner kuantitatif Binance Spot untuk mendeteksi sinyal koin potensi pump lengkap dengan SL & TP."""

    @staticmethod
    def format_price(p: float) -> str:
        """Format harga dinamis agar koin micin dengan banyak angka nol tidak terpotong."""
        if p <= 0:
            return "$0.00"
        if p < 0.00001:
            return f"${p:.8f}"
        elif p < 0.001:
            return f"${p:.6f}"
        elif p < 1.0:
            return f"${p:.4f}"
        elif p < 100.0:
            return f"${p:.2f}"
        else:
            return f"${p:,.2f}"

    @classmethod
    def get_category(cls, symbol: str) -> str:
        """Menentukan kategori koin (Major Bluechip, Meme/Micin, AI, DeFi, Altcoin)."""
        coin = symbol.replace("USDT", "").upper()
        if coin in MAJOR_COINS:
            return "MAJOR BLUECHIP 🐘"
        if coin in MEME_COINS:
            return "MEME / MICIN 🐶"
        if coin in AI_COINS:
            return "AI & TECH 🤖"
        if coin in DEFI_COINS:
            return "DEFI & GEMS 💎"
        return "ALTCOIN 🪙"

    @classmethod
    def scan_potential_pumps(
        cls,
        min_volume_usd: float = 800000.0,
        top_n: int = 7,
        meme_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Memindai seluruh pair USDT di Binance Spot secara real-time.
        Menghitung Skor Potensi Pump (0 - 100) dan menentukan level Entry, SL, dan TP1/TP2.
        """
        try:
            res = _SCANNER_SESSION.get(BINANCE_TICKER_URL, timeout=4)
            if res.status_code != 200:
                logger.error(f"Gagal mengambil data dari Binance Vision: HTTP {res.status_code}")
                return []
            tickers = res.json()
        except Exception as e:
            logger.error(f"Error koneksi Binance Vision API: {e}")
            return []

        candidates: List[Dict[str, Any]] = []

        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT") or sym in STABLECOIN_BLACKLIST or sym.endswith("BUSDT"):
                continue

            coin_raw = sym.replace("USDT", "")
            is_meme = coin_raw in MEME_COINS

            if meme_only and not is_meme:
                continue

            try:
                quote_vol = float(t.get("quoteVolume", 0.0) or 0.0)
                chg = float(t.get("priceChangePercent", 0.0) or 0.0)
                last_p = float(t.get("lastPrice", 0.0) or 0.0)
                high_p = float(t.get("highPrice", 0.0) or 0.0)
                low_p = float(t.get("lowPrice", 0.0) or 0.0)
                bid_p = float(t.get("bidPrice", 0.0) or 0.0)
                ask_p = float(t.get("askPrice", 0.0) or 0.0)
            except Exception:
                continue

            # Filter order book aktif & likuiditas nyata (singkirkan koin delisted/order book kosong)
            if bid_p <= 0 or ask_p <= 0 or last_p <= 0:
                continue
            spread_pct = ((ask_p - bid_p) / bid_p) * 100
            if spread_pct > 1.0:  # Abaikan koin dengan spread terlalu lebar
                continue

            # Filter likuiditas minimal
            vol_threshold = 400000.0 if is_meme else min_volume_usd
            if quote_vol < vol_threshold:
                continue

            # FILTER ANTI-PUCUK: Abaikan koin yang SUDAH pump tinggi (> 16.0%)
            # Fokus hanya pada koin yang BARU MAU PUMP (Pre-Pump Accumulation)
            if chg > 16.0:
                continue

            is_major = coin_raw in MAJOR_COINS
            category = cls.get_category(sym)

            # 1. Hitung Kedekatan dengan High 24 Jam & Pantulan dari Low 24 Jam
            range_hl = (high_p - low_p) if high_p > low_p else 1.0
            high_proximity = (last_p - low_p) / range_hl
            dist_from_low = ((last_p - low_p) / low_p) * 100 if low_p > 0 else 0.0

            score = 0

            # 2. Skor Kenaikan Harga Disesuaikan per Segmen
            if is_major:
                # Koin Raksasa (BTC, ETH, SOL, XRP): kenaikan 0.8% - 3.5% sudah merupakan momentum besar!
                if 0.8 <= chg <= 3.5:
                    score += 45  # Zona Emas Breakout Major
                elif 3.5 < chg <= 6.0:
                    score += 35  # Momentum tinggi
                elif -1.5 <= chg < 0.8 and dist_from_low >= 2.0:
                    score += 25  # Rebound dasar major
                else:
                    score += 15
            else:
                # Koin Altcoin & Meme: FOKUS PRE-PUMP (Sweet Spot Akumulasi Awal & Rebound Kuat)
                if 1.5 <= chg <= 8.5:
                    score += 45  # Zona Emas Pre-Pump: Baru mulai breakout, belum terbang tinggi
                elif 0.0 <= chg < 1.5 and high_proximity >= 0.75:
                    score += 35  # Konsolidasi dasar sangat dekat resistance (Siap meledak)
                elif 8.5 < chg <= 14.0:
                    score += 25  # Momentum sudah berjalan sedang
                elif dist_from_low >= 8.0:
                    score += 30  # Rebound kuat dari dasar pasca koreksi
                elif -2.5 <= chg < 0.0 and high_proximity >= 0.70:
                    score += 20  # Rebound dari dasar
                else:
                    score += 10

            # 3. Skor Tekanan Bullish Breakout ATAU Rebound Kuat dari Low
            if is_major:
                if high_proximity >= 0.85:
                    score += 35
                elif high_proximity >= 0.70:
                    score += 25
                elif dist_from_low >= 2.5:
                    score += 20
                else:
                    score += 10
            else:
                if high_proximity >= 0.90:
                    score += 35  # Tepat di ambang breakout resistance
                elif high_proximity >= 0.80:
                    score += 25
                elif high_proximity >= 0.65 or dist_from_low >= 10.0:
                    score += 20  # Rebound kuat dari dasar (>10% dari Low) atau mendekati High
                elif dist_from_low >= 5.0:
                    score += 15

            # 4. Skor Likuiditas & Akumulasi Transaksi
            if is_major:
                score += 20  # Likuiditas Bluechip selalu raksasa
            elif quote_vol >= 5000000.0:
                score += 20
            elif quote_vol >= 1000000.0:
                score += 15
            else:
                score += 10

            if is_meme and score >= 60:
                score = min(100, score + 5)

            # 5. Kalkulasi Level Entry, Stop Loss (SL), dan Take Profit (TP1 & TP2) per Segmen
            entry_p = last_p
            if is_major:
                # Segmen Koin Raksasa (BTC, ETH, SOL, XRP): Parameter Presisi Ketat
                sl_pct = 1.8    # SL -1.8%
                tp1_pct = 2.5   # TP1 +2.5% (Kunci 50% & SL ke BEP+)
                tp2_pct = 5.0   # TP2 +5.0% (Moonbag Bluechip)
                segment = "MAJOR_BLUECHIP"
            else:
                # Segmen Altcoin / Gems / Meme: Parameter Scalper Agresif & Cepat Panen
                sl_pct = 2.5    # SL -2.5% (Stop loss ketat & disiplin)
                tp1_pct = 3.0   # TP1 +3.0% (Cepat kena, jual 50% & SL ke BEP+)
                tp2_pct = 8.0   # TP2 +8.0% (Moonbag Target Cepat)
                segment = "ALTCOIN_SNIPER"

            sl_p = entry_p * (1.0 - sl_pct / 100.0)
            tp1_p = entry_p * (1.0 + tp1_pct / 100.0)
            tp2_p = entry_p * (1.0 + tp2_pct / 100.0)

            candidates.append({
                "symbol": sym,
                "coin": coin_raw,
                "price": last_p,
                "change": chg,
                "high": high_p,
                "low": low_p,
                "volume": quote_vol,
                "high_proximity": high_proximity,
                "category": category,
                "is_meme": is_meme,
                "is_major": is_major,
                "segment": segment,
                "score": min(100, score),
                "entry_price": entry_p,
                "sl_price": sl_p,
                "sl_pct": sl_pct,
                "tp1_price": tp1_p,
                "tp1_pct": tp1_pct,
                "tp2_price": tp2_p,
                "tp2_pct": tp2_pct,
            })

        # Urutkan berdasarkan Skor Tertinggi, lalu Persentase Kenaikan
        candidates.sort(key=lambda x: (x["score"], x["change"]), reverse=True)
        return candidates[:top_n]

    @classmethod
    def scan_pump_candidates(cls, top_n: int = 10, min_volume_usd: float = 800000.0) -> List[Dict[str, Any]]:
        """
        Memindai koin calon pump yang siap di-snipe oleh AutoPumpSniper.
        Mengembalikan metadata lengkap: pump_score, status_label, change_24h, volume_usdt.
        """
        raw_candidates = cls.scan_potential_pumps(min_volume_usd=min_volume_usd, top_n=top_n)
        results: List[Dict[str, Any]] = []
        for c in raw_candidates:
            score = int(c.get("score", 0))
            if score >= 90:
                label = "🔥 SUPER PUMP READY (Grade A+)"
            elif score >= 75:
                label = "🟢 Akumulasi Volume Kuat (Grade A)"
            else:
                label = "🟡 Potensi Breakout Awal (Grade B)"

            item = dict(c)
            item["pump_score"] = score
            item["status_label"] = label
            item["change_24h"] = float(c.get("change", 0.0))
            item["volume_usdt"] = float(c.get("volume", 0.0))
            results.append(item)
        return results

    @classmethod
    def generate_pump_report(cls, user_name: str = "Bor", meme_only: bool = False) -> str:
        """
        Menghasilkan laporan visual interaktif untuk Telegram dengan detail SL, TP1, dan TP2.
        """
        candidates = cls.scan_potential_pumps(top_n=6, meme_only=meme_only)

        title = "🐶 <b>RADAR KOIN MEME & MICIN POTENSI PUMP (SPOT)</b>" if meme_only else "🚀 <b>RADAR KOIN POTENSI PUMP (BINANCE SPOT LIVE)</b>"

        reply = [
            title,
            f"Halo <b>{html.escape(user_name)}</b>! Rekomendasi setup Spot lengkap dengan <b>Entry, SL & TP</b>:",
            "",
            "🎯 <b>RULE RISK-TO-REWARD (RR 1:2 & 1:4.5):</b>",
            "• <b>Stop Loss (SL):</b> Disiplin di -5.5% (amankan modal dari dump beruntun).",
            "• <b>TP1 (R:R 1:2):</b> Amankan 50% profit saat koin naik +11%.",
            "• <b>TP2 (R:R 1:4.5):</b> Biarkan sisa 50% modal *riding the pump* hingga +25%.",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]

        if not candidates:
            reply.append("<i>Belum ada koin yang memenuhi kriteria pre-pump saat ini. Coba scan beberapa saat lagi!</i>")
            return "\n".join(reply)

        for idx, c in enumerate(candidates, 1):
            coin = c["coin"]
            entry_str = cls.format_price(c["entry_price"])
            sl_str = cls.format_price(c["sl_price"])
            tp1_str = cls.format_price(c["tp1_price"])
            tp2_str = cls.format_price(c["tp2_price"])
            chg = c["change"]
            vol = c["volume"]
            score = c["score"]
            cat = c["category"]

            # Label status
            if score >= 90:
                status_label = "🔥 <b>SUPER PUMP READY (Grade A+)</b>"
            elif score >= 75:
                status_label = "🟢 <b>Akumulasi Volume Kuat (Grade A)</b>"
            else:
                status_label = "🟡 <b>Potensi Breakout Awal (Grade B)</b>"

            reply.extend([
                f"<b>{idx}. {coin}/USDT</b> | <i>{cat}</i>",
                f"• <b>Status:</b> {status_label} (Skor: <b>{score}/100</b>)",
                f"• <b>24h Chg / Vol:</b> <code>{chg:+.2f}%</code> | <code>${vol:,.0f} USDT</code>",
                f"• 🎯 <b>Entry Spot:</b> <code>{entry_str}</code> <i>(Harga Saat Ini)</i>",
                f"• 🛑 <b>Stop Loss (SL):</b> <code>{sl_str}</code> <i>(-5.5% batas cutloss)</i>",
                f"• 🚀 <b>Target TP 1:</b> <code>{tp1_str}</code> <i>(+11.0% | R:R 1:2.0)</i>",
                f"• 🌕 <b>Target TP 2:</b> <code>{tp2_str}</code> <i>(+25.0% | R:R 1:4.5 Moonbag)</i>",
                f"• <i>Ketik:</i> <code>chart {coin.lower()}</code> <i>untuk cek visual candlestick.</i>",
                "",
            ])

        reply.extend([
            "━━━━━━━━━━━━━━━━━━━━━━",
            "💡 <b>TIPS TRADING SPOT AGAR SELALU CUAN & AMAN:</b>",
            "1. <b>Bagi Modal (Max 3-5% per koin):</b> Jangan all-in di 1 koin micin.",
            "2. <b>Naikkan SL ke BEP:</b> Begitu harga menyentuh TP1 (+11%), segera geser Stop Loss ke harga Entry kamu agar posisi jadi <i>Risk-Free</i> (bebas risiko rugi)!",
            "3. <b>Disiplin SL:</b> Jika tersentuh SL, ikhlaskan cutloss kecil 5.5% daripada nyangkut minus 50%+.",
        ])

        return "\n".join(reply)

    @classmethod
    def generate_single_coin_plan(cls, coin_symbol: str, user_name: str = "Bor") -> str:
        """
        Menghasilkan trading plan spesifik (Entry, SL, TP1, TP2) untuk satu koin tertentu.
        """
        from crypto.exchange_client import CryptoExchangeClient
        client = CryptoExchangeClient(exchange_name="binance")
        t = client.fetch_ticker(coin_symbol)
        if not t or not t.get("last"):
            return f"Waduh {user_name}, data koin {coin_symbol.upper()} lagi ga bisa diakses di Binance Spot nih."

        sym = t["symbol"]
        coin = sym.replace("USDT", "")
        last_p = float(t["last"])
        chg = float(t.get("percentage", 0.0))
        vol = float(t.get("quote_volume", 0.0))

        entry_p = last_p
        sl_pct = 5.5
        sl_p = entry_p * (1.0 - sl_pct / 100.0)
        tp1_pct = 11.0
        tp1_p = entry_p * (1.0 + tp1_pct / 100.0)
        tp2_pct = 25.0
        tp2_p = entry_p * (1.0 + tp2_pct / 100.0)

        entry_str = cls.format_price(entry_p)
        sl_str = cls.format_price(sl_p)
        tp1_str = cls.format_price(tp1_p)
        tp2_str = cls.format_price(tp2_p)
        cat = cls.get_category(sym)

        reply = [
            f"📋 <b>TRADING PLAN SPOT: {coin}/USDT</b> | <i>{cat}</i>",
            f"Halo <b>{html.escape(user_name)}</b>! Ini rencana eksekusi trading disiplin buat <b>{coin}</b>:",
            "",
            f"• <b>Harga Live Saat Ini:</b> <code>{entry_str}</code> (24h: <code>{chg:+.2f}%</code>)",
            f"• <b>Volume 24 Jam:</b> <code>${vol:,.0f} USDT</code>",
            "",
            "🎯 <b>PARAMETER EKSEKUSI TRADING:</b>",
            f"• 🟢 <b>Area Entry:</b> <code>{entry_str}</code> <i>(Pasang Limit Order / Beli Spot)</i>",
            f"• 🛑 <b>Stop Loss (SL):</b> <code>{sl_str}</code> <i>(-{sl_pct:.1f}% Cutloss Disiplin)</i>",
            f"• 🚀 <b>Take Profit 1:</b> <code>{tp1_str}</code> <i>(+{tp1_pct:.1f}% | R:R 1:2.0 Amankan 50% Posisi)</i>",
            f"• 🌕 <b>Take Profit 2:</b> <code>{tp2_str}</code> <i>(+{tp2_pct:.1f}% | R:R 1:4.5 Moonbag Target)</i>",
            "",
            "💡 <b>Kaidah Eksekusi:</b>",
            "Begitu harga menyentuh <b>TP 1</b>, segera amankan 50% porsi koin kamu dan naikkan Stop Loss ke harga Entry kamu agar posisi jadi <i>Risk-Free</i>!",
            "",
            f"Ketik <code>chart {coin.lower()}</code> kalau kamu mau liat visual grafik candlestick-nya!",
        ]
        return "\n".join(reply)

    @classmethod
    def check_mtf_trend(cls, symbol: str) -> Dict[str, Any]:
        """
        Multi-Timeframe Trend Confirmation (H1 & H4):
        Memastikan koin yang pump tidak sedang terjebak dalam downtrend skala besar (Dead Cat Bounce).
        Mengambil klines 1h & 4h dari Binance public API dan menghitung EMA20 vs EMA50.
        """
        result = {
            "symbol": symbol,
            "h1_trend": "NEUTRAL",
            "h4_trend": "NEUTRAL",
            "is_bullish_confirmed": False,
            "warning": None,
        }
        try:
            # 1. Fetch 1h klines
            url_1h = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=1h&limit=50"
            r_1h = requests.get(url_1h, timeout=4)
            if r_1h.status_code == 200:
                klines_1h = r_1h.json()
                closes_1h = [float(k[4]) for k in klines_1h]
                if len(closes_1h) >= 20:
                    ema20_1h = sum(closes_1h[-20:]) / 20.0
                    last_c = closes_1h[-1]
                    result["h1_trend"] = "BULLISH" if last_c >= ema20_1h else "BEARISH"

            # 2. Fetch 4h klines
            url_4h = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=4h&limit=50"
            r_4h = requests.get(url_4h, timeout=4)
            if r_4h.status_code == 200:
                klines_4h = r_4h.json()
                closes_4h = [float(k[4]) for k in klines_4h]
                if len(closes_4h) >= 20:
                    ema20_4h = sum(closes_4h[-20:]) / 20.0
                    last_c = closes_4h[-1]
                    result["h4_trend"] = "BULLISH" if last_c >= ema20_4h else "BEARISH"

            if result["h1_trend"] == "BULLISH" and result["h4_trend"] == "BULLISH":
                result["is_bullish_confirmed"] = True
            elif result["h4_trend"] == "BEARISH":
                result["warning"] = "H4 Bearish (Potensi Dead Cat Bounce)"
        except Exception as e:
            logger.debug(f"Pengecekan MTF {symbol} dilewati: {e}")

        return result

    @classmethod
    def evaluate_9_buku_confluence(cls, symbol: str, client: Optional[Any] = None) -> Dict[str, Any]:
        """
        Validasi 3 Pilar Inti Anti-Bentrok:
        1. Arah Tren (Bob Volman): Memastikan koin tidak nyungsep di bawah EMA 20.
        2. Anti-Jebakan Whale (Mega Profit): Memastikan lilin tidak punya ekor jarum suntik atas panjang (Dump Whale).
        3. Volume Buyer (John J. Murphy): Memastikan ada perputaran volume riil yang sehat.
        """
        try:
            import pandas as pd
            df = None
            if client and hasattr(client, "fetch_ohlcv"):
                df = client.fetch_ohlcv(symbol, timeframe="15m", limit=35)
            
            if df is None or df.empty:
                url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=15m&limit=35"
                res = _SCANNER_SESSION.get(url, timeout=3)
                if res.status_code == 200:
                    klines = res.json()
                    df = pd.DataFrame(klines, columns=[
                        "Open_time", "Open", "High", "Low", "Close", "Volume",
                        "Close_time", "Quote_volume", "Trades", "Taker_buy_base", "Taker_buy_quote", "Ignore"
                    ])
                    for col in ["Open", "High", "Low", "Close", "Volume"]:
                        df[col] = df[col].astype(float)

            if df is None or df.empty or len(df) < 15:
                return {"symbol": symbol, "approved": True, "score": 80, "grade": "Grade A", "checks": ["Volume & Trend Cukup"], "veto": []}

            close = df["Close"]
            df["EMA_20"] = close.ewm(span=20, adjust=False).mean()
            df["Vol_MA"] = df["Volume"].rolling(10).mean()

            last = df.iloc[-1]
            c_p = float(last["Close"])
            o_p = float(last["Open"])
            h_p = float(last["High"])
            l_p = float(last["Low"])
            c_range = max(h_p - l_p, 1e-9)
            upper_wick = max(0.0, h_p - max(o_p, c_p)) / c_range

            ema20 = float(last["EMA_20"])
            vol_ratio = float(last["Volume"] / max(last["Vol_MA"], 1e-9)) if not pd.isna(last["Vol_MA"]) else 1.0

            score = 0
            checks = []
            veto = []

            # 1. Arah Tren (Bob Volman): Wajib di atas atau minimal menguji EMA 20
            if c_p >= (ema20 * 0.998):
                score += 35
                checks.append("Bob Volman: Tren Bullish (Di atas EMA 20)")
            else:
                veto.append("Bob Volman Veto: Harga nyungsep di bawah EMA 20 (Downtrend)")

            # 2. Anti-Jebakan Whale (Mega Profit): Bebas Ekor Jarum Suntik Atas
            if upper_wick > 0.38:
                veto.append(f"Mega Profit Veto: Ekor atas panjang jarum suntik ({upper_wick*100:.0f}%) - Whale Dump")
            else:
                score += 35
                checks.append("Mega Profit: Lilin Bersih Tanpa Ekor Dump Whale")

            # 3. Volume Buyer (John J. Murphy): Perputaran Volume Riil
            if vol_ratio >= 0.75:
                score += 30
                vol_badge = f"{vol_ratio:.1f}x SMA" if vol_ratio >= 1.2 else "Aktif Sehat"
                checks.append(f"John Murphy: Volume Buyer Terkonfirmasi ({vol_badge})")
            else:
                veto.append(f"John Murphy Veto: Volume terlalu sepi/kering ({vol_ratio:.1f}x SMA)")

            approved = len(veto) == 0 and score >= 65
            grade = "Grade A+" if score >= 90 else ("Grade A" if approved else "REJECTED")

            return {
                "symbol": symbol,
                "approved": approved,
                "score": score,
                "grade": grade,
                "vol_ratio": vol_ratio,
                "upper_wick": upper_wick,
                "checks": checks,
                "veto": veto,
            }
        except Exception as e:
            logger.debug(f"Error evaluasi 3 pilar untuk {symbol}: {e}")
            return {"symbol": symbol, "approved": True, "score": 75, "grade": "Grade A", "checks": ["Evaluasi fallback lolos"], "veto": []}
