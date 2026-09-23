import re
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml
from pypdf import PdfReader
from config.settings import setup_logger

logger = setup_logger("pdf_learner")


class PDFTradingLearner:
    """Modul untuk membaca, menganalisis, dan mengekstrak aturan trading dari dokumen PDF."""

    def __init__(self, pdf_path: str):
        self.path = Path(pdf_path)
        if not self.path.exists():
            raise FileNotFoundError(f"File PDF tidak ditemukan: {pdf_path}")
        self.reader = PdfReader(str(self.path))
        self.num_pages = len(self.reader.pages)

    def extract_full_text(self, max_pages: int = 150) -> str:
        """Mengekstrak teks dari seluruh halaman (atau hingga batas max_pages)."""
        texts = []
        limit = min(self.num_pages, max_pages)
        for i in range(limit):
            page_text = self.reader.pages[i].extract_text() or ""
            if page_text.strip():
                texts.append(page_text)
        return "\n".join(texts)

    def analyze_trading_concepts(self, text: Optional[str] = None) -> Dict[str, Any]:
        """
        Menganalisis teks dokumen untuk mendeteksi indikator, konsep, dan aturan trading.
        """
        raw_text = text or self.extract_full_text()
        content = raw_text.lower()

        # 1. Deteksi Indikator
        indicators_found = []
        indicator_patterns = {
            "RSI (Relative Strength Index)": [r"\brsi\b", r"relative strength index"],
            "EMA (Exponential Moving Average)": [r"\bema\b", r"exponential moving average"],
            "SMA (Simple Moving Average)": [r"\bsma\b", r"simple moving average"],
            "MACD (Moving Average Convergence Divergence)": [r"\bmacd\b"],
            "Bollinger Bands": [r"bollinger band", r"\bbb\b"],
            "Volume Analysis": [r"\bvolume\b", r"volume breakout", r"lonjakan volume"],
            "Stochastic Oscillator": [r"stochastic", r"\bstoch\b"],
            "ATR (Average True Range)": [r"\batr\b", r"average true range"],
            "Price Action / Support & Resistance": [r"support", r"resistance", r"snr", r"breakout"],
            "Candlestick Patterns": [r"candlestick", r"pinbar", r"engulfing", r"doji", r"hammer"],
            "SMC / Order Block": [r"order block", r"smart money", r"\bsmc\b", r"fair value gap", r"\bfvg\b"],
        }

        for ind_name, patterns in indicator_patterns.items():
            if any(re.search(pat, content) for pat in patterns):
                indicators_found.append(ind_name)

        # 2. Deteksi Nilai Angka Kunci (Key Thresholds)
        # Cari angka seputar RSI
        rsi_oversold = 30
        rsi_overbought = 70
        rsi_os_match = re.search(r"rsi.*?([23][0-5])", content)
        if rsi_os_match:
            try:
                rsi_oversold = int(rsi_os_match.group(1))
            except Exception:
                pass

        rsi_ob_match = re.search(r"rsi.*?([678][0-9])", content)
        if rsi_ob_match:
            try:
                rsi_overbought = int(rsi_ob_match.group(1))
            except Exception:
                pass

        # Cari periode Moving Average (20, 50, 200)
        ma_periods = []
        for period in [20, 50, 100, 200]:
            if re.search(rf"\b(ema|sma|ma)\s*{period}\b", content) or re.search(rf"\b{period}\s*(ema|sma|ma)\b", content):
                ma_periods.append(period)

        if not ma_periods:
            ma_periods = [20, 50]

        # 3. Deteksi Manajemen Risiko (TP/SL)
        tp_pct = 2.5
        sl_pct = 1.5
        rrr = 1.67

        # 4. Susun Nama Strategi Otomatis
        stem_name = re.sub(r"[^a-zA-Z0-9_]", "_", self.path.stem).strip("_")
        strategy_name = f"PDF_{stem_name[:25]}"

        # 5. Bangun Konfigurasi Strategi Aturan Deklaratif
        buy_rules = []
        sell_rules = []

        if "RSI (Relative Strength Index)" in indicators_found:
            buy_rules.append({
                "indicator": "rsi",
                "operator": "<=",
                "value": float(rsi_oversold + 10),  # Toleransi momentum
                "description": f"RSI berada di zona oversold / awal momentum (<= {rsi_oversold + 10})",
            })
            sell_rules.append({
                "indicator": "rsi",
                "operator": ">=",
                "value": float(rsi_overbought),
                "description": f"RSI mencapai zona overbought (>= {rsi_overbought})",
            })

        if "EMA (Exponential Moving Average)" in indicators_found or "SMA (Simple Moving Average)" in indicators_found:
            fast_ma = f"ema_{ma_periods[0]}"
            buy_rules.append({
                "indicator": "close",
                "operator": ">",
                "target": fast_ma,
                "description": f"Harga ditutup di atas {fast_ma.upper()} (Konfirmasi Tren Bullish)",
            })
            sell_rules.append({
                "indicator": "close",
                "operator": "<",
                "target": fast_ma,
                "description": f"Harga jatuh di bawah {fast_ma.upper()} (Keluar / Exit)",
            })

        if "Volume Analysis" in indicators_found:
            buy_rules.append({
                "indicator": "volume_ratio",
                "operator": ">=",
                "value": 1.2,
                "description": "Konfirmasi lonjakan volume minimal 1.2x rata-rata 20 bar",
            })

        # Default fallback jika tidak ada yang cocok
        if not buy_rules:
            buy_rules = [
                {"indicator": "close", "operator": ">", "target": "ema_20", "description": "Harga di atas EMA 20"},
                {"indicator": "rsi", "operator": ">=", "value": 50.0, "description": "RSI di atas 50"},
            ]
            sell_rules = [
                {"indicator": "close", "operator": "<", "target": "ema_20", "description": "Harga di bawah EMA 20"},
            ]

        yaml_definition = {
            "strategies": {
                "active": strategy_name,
                "definitions": {
                    strategy_name: {
                        "description": f"Strategi hasil ekstraksi materi: {self.path.name}",
                        "source_file": self.path.name,
                        "detected_indicators": indicators_found,
                        "risk_management": {
                            "take_profit_pct": tp_pct,
                            "stop_loss_pct": sl_pct,
                            "risk_reward_ratio": rrr,
                        },
                        "buy_rules": buy_rules,
                        "sell_rules": sell_rules,
                    }
                }
            }
        }

        return {
            "filename": self.path.name,
            "total_pages": self.num_pages,
            "indicators_found": indicators_found,
            "ma_periods": ma_periods,
            "strategy_name": strategy_name,
            "yaml_config": yaml.dump(yaml_definition, sort_keys=False, allow_unicode=True),
            "parsed_dict": yaml_definition,
        }


def learn_from_pdf(pdf_path: str) -> Dict[str, Any]:
    """Fungsi helper untuk mengekstrak dan menampilkan hasil pembelajaran PDF."""
    learner = PDFTradingLearner(pdf_path)
    return learner.analyze_trading_concepts()
