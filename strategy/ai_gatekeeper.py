"""
Modul Otak AI Trading (Gemini AI Decision Gatekeeper):
- Berfungsi sebagai "Chief Risk Officer / Supreme Analyst" sebelum order eksekusi.
- Menganalisis konteks multi-dimensi (Market Structure, Volume, Sentimen Berita, Smart Money Trap).
- Mencegah jebakan likuiditas (Bull Trap, Bear Trap, Fakeout) pada XAU/USD dan Crypto Pump.
- Menggunakan Google Gemini 2.0 / 1.5 Flash API (0 ms lag, respons kilat, efisien).
"""

import os
import json
import time
import requests
from typing import Dict, Any, Optional, Tuple
from config.settings import load_config, setup_logger

logger = setup_logger("ai_gatekeeper")

# Urutan model Gemini: mengutamakan model flash 3 preview / 3.5 yang aktif dan responsif
GEMINI_MODELS = [
    os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
]



class AIGatekeeper:
    """Evaluator keputusan trading berbasis Google Gemini AI."""

    _instance = None

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "").strip()
        self.enabled = bool(self.api_key)
        self.min_approval_score = int(os.getenv("AI_MIN_SCORE", "80"))  # Skor kelayakan 1-100
        self.active_model = None

    @classmethod
    def get_instance(cls) -> "AIGatekeeper":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def has_brain(self) -> bool:
        """Memeriksa apakah API Key Gemini sudah terpasang dan aktif."""
        return bool(self.api_key)

    def _call_gemini(self, prompt: str, system_instruction: str) -> Optional[Dict[str, Any]]:
        """Memanggil REST API Gemini secara aman dan cepat."""
        if not self.has_brain():
            return None

        payload = {
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,  # Konservatif & analitis
                "response_mime_type": "application/json",
                "maxOutputTokens": 350,
                "thinkingConfig": {"thinkingBudget": 0},
            }
        }

        # Anti-Stall: Jika baru saja terkena batas kuota 429, gunakan filter quant bawaan selama 60 detik tanpa jeda
        if time.time() - getattr(self, "_last_429_time", 0.0) < 60.0:
            return None

        # Coba model berurutan dengan timeout 6.0 detik agar AI memiliki waktu analisis yang cukup
        tried_models = []
        for model in GEMINI_MODELS:
            if not model or model in tried_models:
                continue
            tried_models.append(model)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            try:
                r = requests.post(url, json=payload, timeout=10.0)
                if r.status_code == 200:
                    data = r.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text_content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        clean_text = text_content.strip()
                        if clean_text.startswith("```json"):
                            clean_text = clean_text[7:]
                        elif clean_text.startswith("```"):
                            clean_text = clean_text[3:]
                        if clean_text.endswith("```"):
                            clean_text = clean_text[:-3]
                        clean_text = clean_text.strip()
                        self.active_model = model
                        return json.loads(clean_text)
                elif r.status_code in (503, 500, 404):
                    logger.debug(f"Gemini {model} merespons {r.status_code}. Beralih ke model cadangan berikutnya...")
                    continue
                elif r.status_code == 429:
                    logger.debug(f"Gemini {model} mencapai batas kuota (429).")
                    self._last_429_time = time.time()
                    return None
                elif r.status_code == 400 and "API_KEY_INVALID" in r.text:
                    logger.error("Gemini API Key tidak valid!")
                    return None
            except Exception as e:
                logger.debug(f"Panggilan Gemini ({model}) dilewati/timeout: {e}")

        return None

    def evaluate_gold_trade(
        self,
        signal_type: str,
        price: float,
        indicators: Dict[str, Any],
        news_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Mengevaluasi sinyal XAU/USD sebelum order MT5 ditembakkan.
        Mencegah entry saat ada bull/bear trap, fakeout, atau melawan arah tren utama.
        """
        if not self.has_brain():
            # Fallback tanpa AI: izinkan jika skor rule-based normal
            return {
                "approved": True,
                "score": 80,
                "verdict": "RULE_BASED_FALLBACK",
                "reason": "Otak AI belum diisi API Key. Eksekusi menggunakan filter aturan quant bawaan.",
                "ai_active": False,
            }

        sys_prompt = (
            "You are an elite Institutional Quantitative Risk Manager specializing in Gold (XAU/USD) Spot trading. "
            "Your critical mission is to protect capital: strictly filter out false breakouts, liquidity traps, and counter-trend entries. "
            "ABSOLUTE RULE: NEVER approve a BUY signal if H1 or H4 trend is BEARISH / DOWNTREND. "
            "NEVER approve a SELL signal if H1 or H4 trend is BULLISH / UPTREND. "
            "Trading against the dominant macro trend is strictly forbidden and must be REJECTED. "
            "You must return ONLY a valid JSON object with keys: "
            "'approved' (boolean), 'score' (integer 1-100), 'verdict' (string: 'APPROVED' or 'REJECTED'), "
            "'reason' (string in Indonesian), 'warning' (string in Indonesian)."
        )

        user_prompt = f"""
Evaluasi Sinyal Trading XAU/USD berikut:
- Tipe Sinyal: {signal_type}
- Harga Saat Ini: {price}
- Indikator & Validasi: {json.dumps(indicators)}
- Konteks Berita / Kalender Ekonomi: {news_context or 'Tidak ada rilis berita berdampak tinggi'}

Aturan Ketat:
1. Validasi Arah Tren (Rule Mutlak Anti-Melawan Tren):
   - Jika sinyal BUY tetapi tren H1 atau H4 adalah BEARISH/DOWNTREND, TOLAK MUTLAK (approved=false, score < 50)!
   - Jika sinyal SELL tetapi tren H1 atau H4 adalah BULLISH/UPTREND, TOLAK MUTLAK (approved=false, score < 50)!
2. Validasi 5 Pilar Konfluensi (Zero-Bentrok): Sinyal ini berbasis 3 Pilar Inti (Bob Volman Trend EMA20, Mega Profit Anti-Jarum Suntik Wick <= 38%, John Murphy Active Volume >= 0.75x) ditambah EMA+RSI Momentum Sehat (Martin Pring) dan Key SNR Mayor Horizontal. Jika 5 Pilar ini valid dan SEARAH DENGAN TREN H1/H4, SETUJUI (approved=true) dengan skor >= 85.
3. Jika ada berita Red Folder USD dalam 30 menit ke depan, REJECT.
4. Berikan skor >= {self.min_approval_score} hanya jika struktur momentum sehat dan searah tren.
"""
        eval_res = self._call_gemini(user_prompt, sys_prompt)
        if eval_res:
            eval_res["ai_active"] = True
            is_approved = eval_res.get("approved", False) and eval_res.get("score", 0) >= self.min_approval_score
            eval_res["approved"] = is_approved
            logger.info(f"AI Brain XAU/USD Verdict: {eval_res.get('verdict')} | Skor: {eval_res.get('score')} | Alasan: {eval_res.get('reason')}")
            return eval_res

        # Fallback proteksi modal jika Gemini timeout atau tidak dapat dihubungi
        h1_trend = str(indicators.get("h1_trend", "")).upper()
        h4_trend = str(indicators.get("h4_trend", "")).upper()
        is_counter = (signal_type == "BUY" and ("BEAR" in h1_trend or "BEAR" in h4_trend)) or \
                     (signal_type == "SELL" and ("BULL" in h1_trend or "BULL" in h4_trend))
        if is_counter:
            logger.warning(f"🛑 [AI TIMEOUT FALLBACK VETO] Sinyal {signal_type} ditolak karena melawan tren H1={h1_trend}/H4={h4_trend}.")
            return {
                "approved": False,
                "score": 35,
                "verdict": "VETO_COUNTER_TREND_FALLBACK",
                "reason": f"AI timeout & sinyal {signal_type} melawan arah tren utama (H1: {h1_trend}, H4: {h4_trend}). Demi proteksi modal, transaksi ditolak.",
                "ai_active": False,
            }

        quant_score = float(indicators.get("score", 75))
        is_ok = quant_score >= self.min_approval_score
        return {
            "approved": is_ok,
            "score": int(quant_score),
            "verdict": "APPROVED_QUANT_FALLBACK" if is_ok else "REJECTED_QUANT_FALLBACK",
            "reason": "AI timeout, transaksi disetujui berdasarkan konfluensi quant 9 buku PDF." if is_ok else "AI timeout dan skor quant belum mencapai batas minimum kelayakan.",
            "ai_active": False,
        }

    def evaluate_crypto_pump(
        self,
        symbol: str,
        price: float,
        chg_24h: float,
        volume_usdt: float,
        pump_score: int,
        status_label: str,
        pdf_confluence: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Mengevaluasi koin pump Binance sebelum bot menembak Auto-Buy.
        Mencegah beli koin yang sudah pucuk (FOMO dump) atau koin likuiditas bodong.
        Mempertimbangkan hasil telaah teknikal 9 Buku PDF Trading.
        """
        if not self.has_brain():
            return {
                "approved": True,
                "score": pump_score,
                "verdict": "RULE_BASED_FALLBACK",
                "reason": "Otak AI belum diisi API Key. Eksekusi menggunakan skor scanner bawaan.",
                "ai_active": False,
            }

        sys_prompt = (
            "You are a Senior Crypto Quantitative Analyst on Binance Spot. "
            "You protect the bot from buying exhausted pumps (buying the top), rug pulls, and fake volume. "
            "You consider 3 Core Pillars: Bob Volman EMA20 Trend, Mega Profit Anti-Whale Dump Wick, and John Murphy Active Volume. "
            "Return ONLY a JSON object with keys: "
            "'approved' (boolean), 'score' (integer 1-100), 'verdict' (string: 'APPROVED' or 'REJECTED'), "
            "'reason' (string in Indonesian), 'risk_assessment' (string in Indonesian)."
        )

        pdf_info = ""
        if pdf_confluence:
            pdf_info = f"""- Validasi 3 Pilar Inti: {pdf_confluence.get('grade')} (Skor: {pdf_confluence.get('score')}/100)
  Pilar Terpenuhi: {', '.join(pdf_confluence.get('checks', []))}
"""

        user_prompt = f"""
Evaluasi Kandidat Koin Pump Binance Spot:
- Simbol: {symbol}
- Harga: {price}
- Kenaikan 24 Jam: {chg_24h}%
- Volume Transaksi 24 Jam: ${volume_usdt:,.0f} USDT
- Skor Scanner Bawaan: {pump_score}/100 ({status_label})
{pdf_info}
Aturan Ketat:
1. Jika koin sudah naik > 35%, kemungkinan besar sudah di pucuk (fomo dump), tolak (REJECT)!
2. Koin terbaik adalah koin pre-pump (+3% s/d +15%) dengan volume transaksi masif (> $1,000,000 USDT) dan struktur lilin sehat.
3. Setujui (approved=true) hanya jika probabilitas pump sehat dan skor >= {self.min_approval_score}.
"""
        eval_res = self._call_gemini(user_prompt, sys_prompt)
        if eval_res:
            eval_res["ai_active"] = True
            is_approved = eval_res.get("approved", False) and eval_res.get("score", 0) >= self.min_approval_score
            eval_res["approved"] = is_approved
            logger.info(f"AI Brain Crypto Verdict: {symbol} | {eval_res.get('verdict')} | Skor: {eval_res.get('score')} | Alasan: {eval_res.get('reason')}")
            return eval_res

        is_pump_ok = pump_score >= self.min_approval_score and chg_24h <= 35.0
        return {
            "approved": is_pump_ok,
            "score": pump_score,
            "verdict": "APPROVED_SCANNER_FALLBACK" if is_pump_ok else "REJECTED_RISK_FALLBACK",
            "reason": "AI timeout, transaksi disetujui berdasarkan scanner bawaan." if is_pump_ok else f"AI timeout & koin berisiko tinggi (skor: {pump_score}, naik: {chg_24h:.1f}%).",
            "ai_active": False,
        }

    def evaluate_reversal_exit_or_flip(
        self,
        current_positions: list,
        new_signal: dict,
        indicators: dict,
    ) -> dict:
        """
        Mengevaluasi keputusan Cut Loss Dini dan Balik Arah (Reversal Flip) XAU/USD berbasis penalaran Gemini.
        Mencegah posisi terseret floating minus sampai hard SL saat tren struktural telah rusak.
        """
        if not self.has_brain():
            return {
                "should_cut_loss": False,
                "should_flip": False,
                "score": 50,
                "verdict": "RULE_BASED_FALLBACK",
                "reason": "Otak AI belum aktif, ikuti aturan ketat hard TP/SL bawaan.",
                "ai_active": False,
            }

        sys_prompt = (
            "You are an elite Institutional Chief Risk Officer and Head of Quantitative Trading specializing in Gold (XAU/USD). "
            "A trader is currently holding open positions, but a strong opposing signal / structural breakout has occurred. "
            "Your critical mission: Decide whether to: "
            "1. 'CUT_LOSS_AND_FLIP': Exit the losing position immediately to preserve capital AND flip into the new trend. "
            "2. 'CUT_LOSS_ONLY': Exit the losing position now without entering the new trade. "
            "3. 'HOLD_ORIGINAL': Do NOT cut loss; this opposing move is merely a temporary pullback / liquidity sweep / stop hunt. "
            "Return ONLY a valid JSON object with keys: "
            "'should_cut_loss' (boolean), 'should_flip' (boolean), 'score' (integer 1-100), "
            "'verdict' (string: 'CUT_LOSS_AND_FLIP', 'CUT_LOSS_ONLY', or 'HOLD_ORIGINAL'), "
            "'reason' (string in Indonesian), 'warning' (string in Indonesian)."
        )

        pos_summary = [
            f"Tiket #{p.get('ticket')}: {p.get('type')} @ {p.get('price_open')} (Profit: {p.get('profit')})"
            for p in current_positions
        ]

        user_prompt = f"""
Evaluasi Pembalikan Arah & Keputusan Cut Loss XAU/USD:
- Posisi Terbuka Saat Ini: {json.dumps(pos_summary)}
- Sinyal Baru Berlawanan: {json.dumps(new_signal)}
- Indikator & Konteks: {json.dumps(indicators)}

Aturan Analisis Ketat:
1. Jika struktur pasar jelas telah berbalik (breakdown EMA 50/200 dengan lilin impulsif) dan sinyal berlawanan kuat, setujui CUT_LOSS_AND_FLIP (skor >= 85).
2. Jika ada tanda fakeout / sweep likuiditas biasa dan tren makro masih mendukung posisi lama, sarankan HOLD_ORIGINAL (should_cut_loss=false).
3. Berikan penalaran tajam dan profesional dalam Bahasa Indonesia.
"""
        eval_res = self._call_gemini(user_prompt, sys_prompt)
        if eval_res:
            eval_res["ai_active"] = True
            is_valid = eval_res.get("score", 0) >= self.min_approval_score
            if not is_valid and eval_res.get("verdict") == "CUT_LOSS_AND_FLIP":
                eval_res["should_flip"] = False
            logger.info(
                f"🧠 [GEMINI REVERSAL EVAL] Verdict: {eval_res.get('verdict')} | Skor: {eval_res.get('score')} | Alasan: {eval_res.get('reason')}"
            )
            return eval_res

        return {
            "should_cut_loss": False,
            "should_flip": False,
            "score": 50,
            "verdict": "TIMEOUT_FALLBACK",
            "reason": "AI timeout, pertahankan posisi sesuai hard TP/SL bawaan.",
            "ai_active": False,
        }

    def evaluate_sl_post_mortem(
        self,
        trade_details: dict,
        market_snapshot: dict,
    ) -> dict:
        """
        Melakukan evaluasi pasca-SL (AI Post-Mortem) secara instan saat transaksi menyentuh Stop Loss.
        Mendiagnosis penyebab harga tembus SL, memetakan kondisi pasar terkini,
        dan merekomendasikan tindakan preventif (directional lockout, cooldown, persiapan arah baru).
        """
        if not self.has_brain():
            return {
                "diagnosa": "Harga menyentuh batas toleransi risiko stop loss teknikal.",
                "market_condition": "Volatilitas pasar menembus level proteksi.",
                "action_plan": "Tunggu konfirmasi struktur baru sebelum entry.",
                "cooldown_mins": 35,
                "bot_posture": "DEFENSIVE (Arah posisi dikunci 35 menit)",
                "ai_active": False,
            }

        sys_prompt = (
            "You are an elite Institutional Quantitative Risk Manager and Trading Psychologist for Gold (XAU/USD). "
            "A trade has just been stopped out (Hit Stop Loss). The trader needs an immediate, brutal, objective Post-Mortem. "
            "Analyze the failure, assess the current market state, and determine the exact defensive posture for the bot. "
            "Return ONLY a valid JSON object with keys: "
            "'diagnosa' (string in Indonesian, why SL was hit), "
            "'market_condition' (string in Indonesian, current market trend/structure post-SL), "
            "'action_plan' (string in Indonesian, what to look for next), "
            "'cooldown_mins' (integer between 20 and 60), "
            "'bot_posture' (string in Indonesian, e.g. 'DEFENSIVE: Kunci arah BUY, persiapkan setup SELL saat retest')."
        )

        user_prompt = f"""
Evaluasi Pasca-SL (Post-Mortem) XAU/USD:
- Rincian Trade yang Kena SL: {json.dumps(trade_details)}
- Kondisi Pasar Terkini Pasca-SL: {json.dumps(market_snapshot)}

Berikan analisis objektif:
1. Diagnosa utama: Kenapa harga menembus level SL (misal: false breakout, likuiditas disapu, tren H4 berubah, sentimen USD)?
2. Kondisi struktur pasar saat ini (Bullish, Bearish kuat, atau Sideways agresif)?
3. Rencana tindakan terbaik dan rekomendasi masa jeda/cooldown (dalam menit).
"""
        eval_res = self._call_gemini(user_prompt, sys_prompt)
        if eval_res:
            eval_res["ai_active"] = True
            eval_res["cooldown_mins"] = int(eval_res.get("cooldown_mins", 35))
            logger.info(
                f"🧠 [GEMINI POST-MORTEM] SL Diagnosa: {eval_res.get('diagnosa')} | Next: {eval_res.get('action_plan')}"
            )
            return eval_res

        return {
            "diagnosa": "Harga menembus batas risiko stop loss teknikal pasar.",
            "market_condition": "Volatilitas tinggi menembus support/resistance.",
            "action_plan": "Disiplin jeda sampai struktur pasar kembali tenang.",
            "cooldown_mins": 35,
            "bot_posture": "DEFENSIVE (Arah posisi dikunci 35 menit)",
            "ai_active": False,
        }


