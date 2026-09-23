from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd
import numpy as np


@dataclass
class RuleCondition:
    """
    Kondisi aturan deklaratif untuk sinyal teknikal.
    
    Contoh:
    - RuleCondition("rsi", "<", value=30, description="RSI Oversold (< 30)")
    - RuleCondition("close", ">", target="ema_50", description="Harga di atas EMA 50")
    - RuleCondition("volume", ">", target="volume_sma_20", multiplier=1.5, description="Volume > 1.5x SMA 20")
    - RuleCondition("close", "cross_under", target="ema_20", description="Harga tembus ke bawah EMA 20")
    """
    indicator: str
    operator: str
    value: Optional[float] = None
    target: Optional[str] = None
    multiplier: float = 1.0
    description: Optional[str] = None

    def evaluate_bar(
        self,
        current_row: pd.Series,
        prev_row: Optional[pd.Series] = None,
    ) -> Tuple[bool, str]:
        """
        Mengevaluasi kondisi pada satu bar/candle.
        Mengembalikan: (is_satisfied, detailed_reason)
        """
        # Normalisasi nama kolom (lowercase)
        ind_col = self._resolve_column(current_row, self.indicator)
        if ind_col is None:
            return False, f"Indikator '{self.indicator}' tidak ditemukan."

        curr_val = current_row[ind_col]
        if pd.isna(curr_val):
            return False, f"{ind_col} bernilai NaN."

        # Dapatkan nilai pembanding
        if self.target is not None:
            tgt_col = self._resolve_column(current_row, self.target)
            if tgt_col is None:
                return False, f"Target '{self.target}' tidak ditemukan."
            tgt_val = current_row[tgt_col] * self.multiplier
            prev_tgt_val = (
                (prev_row[tgt_col] * self.multiplier)
                if prev_row is not None and tgt_col in prev_row and not pd.isna(prev_row[tgt_col])
                else None
            )
            tgt_label = f"{self.target}" + (f" x {self.multiplier}" if self.multiplier != 1.0 else "")
        elif self.value is not None:
            tgt_val = float(self.value)
            prev_tgt_val = float(self.value)
            tgt_label = f"{self.value}"
        else:
            return False, "Kondisi harus memiliki 'value' atau 'target'."

        prev_val = (
            prev_row[ind_col]
            if prev_row is not None and ind_col in prev_row and not pd.isna(prev_row[ind_col])
            else None
        )

        op = self.operator.lower().strip()
        satisfied = False
        reason = ""

        if op in ["<", "lt"]:
            satisfied = curr_val < tgt_val
            reason = f"{ind_col} ({curr_val:.2f}) < {tgt_label} ({tgt_val:.2f})"
        elif op in ["<=", "lte"]:
            satisfied = curr_val <= tgt_val
            reason = f"{ind_col} ({curr_val:.2f}) <= {tgt_label} ({tgt_val:.2f})"
        elif op in [">", "gt"]:
            satisfied = curr_val > tgt_val
            reason = f"{ind_col} ({curr_val:.2f}) > {tgt_label} ({tgt_val:.2f})"
        elif op in [">=", "gte"]:
            satisfied = curr_val >= tgt_val
            reason = f"{ind_col} ({curr_val:.2f}) >= {tgt_label} ({tgt_val:.2f})"
        elif op in ["==", "eq"]:
            satisfied = abs(curr_val - tgt_val) < 1e-6
            reason = f"{ind_col} ({curr_val:.2f}) == {tgt_label} ({tgt_val:.2f})"
        elif op in ["cross_above", "crossover"]:
            if prev_val is not None and prev_tgt_val is not None:
                satisfied = prev_val <= prev_tgt_val and curr_val > tgt_val
                reason = f"{ind_col} menembus ke atas {tgt_label} ({prev_val:.2f} -> {curr_val:.2f})"
            else:
                satisfied = False
                reason = f"Data bar sebelumnya tidak cukup untuk cross_above"
        elif op in ["cross_under", "crossunder"]:
            if prev_val is not None and prev_tgt_val is not None:
                satisfied = prev_val >= prev_tgt_val and curr_val < tgt_val
                reason = f"{ind_col} menembus ke bawah {tgt_label} ({prev_val:.2f} -> {curr_val:.2f})"
            else:
                satisfied = False
                reason = f"Data bar sebelumnya tidak cukup untuk cross_under"
        else:
            return False, f"Operator '{self.operator}' tidak dikenali."

        # Tambahkan deskripsi khusus jika ada
        if self.description:
            reason = f"{self.description} [{reason}]" if satisfied else f"Belum terpenuhi: {self.description} [{reason}]"

        return bool(satisfied), reason

    def evaluate_series(self, df: pd.DataFrame) -> pd.Series:
        """
        Mengevaluasi kondisi secara vectorized di seluruh baris DataFrame (untuk backtesting berkecepatan tinggi).
        """
        ind_col = self._resolve_column(df, self.indicator)
        if ind_col is None:
            return pd.Series(False, index=df.index)

        s_curr = df[ind_col]

        if self.target is not None:
            tgt_col = self._resolve_column(df, self.target)
            if tgt_col is None:
                return pd.Series(False, index=df.index)
            s_tgt = df[tgt_col] * self.multiplier
        elif self.value is not None:
            s_tgt = float(self.value)
        else:
            return pd.Series(False, index=df.index)

        op = self.operator.lower().strip()
        if op in ["<", "lt"]:
            return s_curr < s_tgt
        elif op in ["<=", "lte"]:
            return s_curr <= s_tgt
        elif op in [">", "gt"]:
            return s_curr > s_tgt
        elif op in [">=", "gte"]:
            return s_curr >= s_tgt
        elif op in ["==", "eq"]:
            return (s_curr - s_tgt).abs() < 1e-6
        elif op in ["cross_above", "crossover"]:
            prev_curr = s_curr.shift(1)
            prev_tgt = s_tgt.shift(1) if isinstance(s_tgt, pd.Series) else s_tgt
            return (prev_curr <= prev_tgt) & (s_curr > s_tgt)
        elif op in ["cross_under", "crossunder"]:
            prev_curr = s_curr.shift(1)
            prev_tgt = s_tgt.shift(1) if isinstance(s_tgt, pd.Series) else s_tgt
            return (prev_curr >= prev_tgt) & (s_curr < s_tgt)
        else:
            return pd.Series(False, index=df.index)

    @staticmethod
    def _resolve_column(container: pd.Series | pd.DataFrame, name: str) -> Optional[str]:
        """Mencari nama kolom secara case-insensitive."""
        name_clean = name.strip()
        cols = container.index if isinstance(container, pd.Series) else container.columns
        for c in cols:
            if str(c).lower() == name_clean.lower():
                return str(c)
        return None


@dataclass
class Strategy:
    """Definisi strategi trading berbasis aturan deklaratif."""
    name: str
    description: str
    buy_rules: List[RuleCondition] = field(default_factory=list)
    buy_combine: str = "AND"  # 'AND' atau 'OR'
    sell_rules: List[RuleCondition] = field(default_factory=list)
    sell_combine: str = "OR"   # 'AND' atau 'OR'

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "Strategy":
        """Instansiasi strategi dari dictionary atau config.yaml."""
        desc = data.get("description", f"Strategi {name}")
        buy_combine = data.get("buy_combine", "AND").upper()
        sell_combine = data.get("sell_combine", "OR").upper()

        buy_rules = []
        for r in data.get("buy_rules", []):
            buy_rules.append(
                RuleCondition(
                    indicator=r["indicator"],
                    operator=r["operator"],
                    value=r.get("value"),
                    target=r.get("target"),
                    multiplier=float(r.get("multiplier", 1.0)),
                    description=r.get("description"),
                )
            )

        sell_rules = []
        for r in data.get("sell_rules", []):
            sell_rules.append(
                RuleCondition(
                    indicator=r["indicator"],
                    operator=r["operator"],
                    value=r.get("value"),
                    target=r.get("target"),
                    multiplier=float(r.get("multiplier", 1.0)),
                    description=r.get("description"),
                )
            )

        return cls(
            name=name,
            description=desc,
            buy_rules=buy_rules,
            buy_combine=buy_combine,
            sell_rules=sell_rules,
            sell_combine=sell_combine,
        )


# Registry strategi bawaan
_STRATEGY_REGISTRY: Dict[str, Strategy] = {}


def register_strategy(strategy: Strategy) -> None:
    """Mendaftarkan strategi ke global registry."""
    _STRATEGY_REGISTRY[strategy.name] = strategy


def get_strategy(name: str) -> Optional[Strategy]:
    """Mendapatkan strategi berdasarkan nama (otomatis memuat dari config.yaml jika belum ada)."""
    if name in _STRATEGY_REGISTRY:
        return _STRATEGY_REGISTRY[name]

    try:
        from config.settings import load_config
        cfg = load_config()
        strat_cfg = cfg.get("strategies", {}).get("definitions", {})
        if name in strat_cfg:
            strat = Strategy.from_dict(name, strat_cfg[name])
            register_strategy(strat)
            return strat
    except Exception:
        pass

    return None


def list_registered_strategies() -> List[str]:
    """Daftar nama strategi yang terdaftar."""
    try:
        from config.settings import load_config
        cfg = load_config()
        strat_cfg = cfg.get("strategies", {}).get("definitions", {})
        for k, v in strat_cfg.items():
            if k not in _STRATEGY_REGISTRY:
                _STRATEGY_REGISTRY[k] = Strategy.from_dict(k, v)
    except Exception:
        pass
    return list(_STRATEGY_REGISTRY.keys())


# Default Strategy dari Prompt
DEFAULT_STRATEGY = Strategy(
    name="Default_RSI_EMA_Volume",
    description="Reversal Momentum & Volume Confirmation Strategy",
    buy_rules=[
        RuleCondition(
            indicator="rsi",
            operator="<",
            value=30.0,
            description="RSI Oversold (< 30)",
        ),
        RuleCondition(
            indicator="close",
            operator=">",
            target="ema_50",
            description="Harga Close di atas EMA 50",
        ),
        RuleCondition(
            indicator="volume",
            operator=">",
            target="volume_sma_20",
            multiplier=1.5,
            description="Volume > 1.5x Rata-rata 20 Periode",
        ),
    ],
    buy_combine="AND",
    sell_rules=[
        RuleCondition(
            indicator="rsi",
            operator=">",
            value=70.0,
            description="RSI Overbought (> 70)",
        ),
        RuleCondition(
            indicator="close",
            operator="cross_under",
            target="ema_20",
            description="Harga tembus ke bawah EMA 20 setelah sebelumnya di atas",
        ),
    ],
    sell_combine="OR",
)
register_strategy(DEFAULT_STRATEGY)

# 1. Strategi Bob Volman Price Action (Under Standing Price Action)
BOB_VOLMAN_STRATEGY = Strategy(
    name="PriceAction_BobVolman",
    description="Bob Volman 20 EMA Pullback Reversal dengan Candle Rejection & Volume",
    buy_rules=[
        RuleCondition(
            indicator="volman_pullback",
            operator=">=",
            value=1.0,
            description="Bob Volman Pullback: Uji Dinamis Support 20 EMA",
        ),
        RuleCondition(
            indicator="rejection_wick_ratio",
            operator=">=",
            value=0.35,
            description="Candle Rejection Wick (Ekor Bawah >= 35% Rentang Candle)",
        ),
        RuleCondition(
            indicator="volume_ratio",
            operator=">=",
            value=1.1,
            description="Konfirmasi Volume Buyer (>= 1.1x SMA 20)",
        ),
    ],
    buy_combine="AND",
    sell_rules=[
        RuleCondition(
            indicator="close",
            operator="cross_under",
            target="ema_20",
            description="Harga Breakdown Tembus Bawah 20 EMA",
        ),
        RuleCondition(
            indicator="rsi",
            operator=">",
            value=72.0,
            description="RSI Overbought (> 72)",
        ),
    ],
    sell_combine="OR",
)
register_strategy(BOB_VOLMAN_STRATEGY)

# 2. Strategi Ichimoku Kinko Hyo Cloud Breakout
ICHIMOKU_STRATEGY = Strategy(
    name="Ichimoku_Cloud_Breakout",
    description="Ichimoku Kinko Hyo: Breakout Awan Kumo & Bullish TK Alignment",
    buy_rules=[
        RuleCondition(
            indicator="ichimoku_above_cloud",
            operator=">=",
            value=1.0,
            description="Harga Berada di Atas Awan Kumo (Bullish Cloud)",
        ),
        RuleCondition(
            indicator="ichimoku_tenkan",
            operator=">=",
            target="ichimoku_kijun",
            description="Tenkan-sen di Atas Kijun-sen (Bullish Momentum)",
        ),
        RuleCondition(
            indicator="rsi",
            operator=">",
            value=45.0,
            description="RSI Momentum Positif (> 45)",
        ),
    ],
    buy_combine="AND",
    sell_rules=[
        RuleCondition(
            indicator="close",
            operator="<",
            target="ichimoku_kijun",
            description="Harga Jatuh Menembus Kijun-sen",
        ),
        RuleCondition(
            indicator="rsi",
            operator=">",
            value=75.0,
            description="RSI Overbought (> 75)",
        ),
    ],
    sell_combine="OR",
)
register_strategy(ICHIMOKU_STRATEGY)

# 3. Strategi Fibonacci Golden Pocket (50% - 61.8%)
FIBONACCI_STRATEGY = Strategy(
    name="Fibonacci_GoldenPocket",
    description="Fibonacci Retracement: Rebound Akurat di Zona Emas 50% - 61.8%",
    buy_rules=[
        RuleCondition(
            indicator="fib_in_golden_zone",
            operator=">=",
            value=1.0,
            description="Harga Menguji Area Golden Pocket (50.0% - 61.8%)",
        ),
        RuleCondition(
            indicator="close",
            operator=">=",
            target="ema_50",
            description="Filter Tren Mayor: Harga di Atas EMA 50",
        ),
        RuleCondition(
            indicator="rejection_wick_ratio",
            operator=">=",
            value=0.30,
            description="Rebound Pinbar / Ekor Rejection di Golden Pocket",
        ),
    ],
    buy_combine="AND",
    sell_rules=[
        RuleCondition(
            indicator="close",
            operator="cross_under",
            target="ema_20",
            description="Harga Tembus Bawah EMA 20",
        ),
        RuleCondition(
            indicator="rsi",
            operator=">",
            value=70.0,
            description="RSI Overbought (> 70)",
        ),
    ],
    sell_combine="OR",
)
register_strategy(FIBONACCI_STRATEGY)

# 4. Master Confluence Strategy (Gabungan Multi-Buku Terbaik)
MASTER_CONFLUENCE_STRATEGY = Strategy(
    name="Master_Confluence_Strategy",
    description="Konfluensi Utama: Trend EMA50 + Area Bob Volman/Fibonacci + Candlestick Rejection + Volume",
    buy_rules=[
        RuleCondition(
            indicator="close",
            operator=">=",
            target="ema_50",
            description="Tren Mayor Bullish (Close >= EMA 50)",
        ),
        RuleCondition(
            indicator="rejection_wick_ratio",
            operator=">=",
            value=0.35,
            description="Candle Rejection Wick (Buyer Membeli di Bawah)",
        ),
        RuleCondition(
            indicator="volume_ratio",
            operator=">=",
            value=1.1,
            description="Volume Buyer Menguat (>= 1.1x)",
        ),
        RuleCondition(
            indicator="rsi",
            operator="<=",
            value=60.0,
            description="RSI Belum Jenuh Beli (RSI <= 60)",
        ),
    ],
    buy_combine="AND",
    sell_rules=[
        RuleCondition(
            indicator="rsi",
            operator=">",
            value=72.0,
            description="RSI Overbought (> 72)",
        ),
        RuleCondition(
            indicator="close",
            operator="cross_under",
            target="ema_20",
            description="Harga Tembus ke Bawah EMA 20",
        ),
    ],
    sell_combine="OR",
)
register_strategy(MASTER_CONFLUENCE_STRATEGY)
