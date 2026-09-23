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
    """Mendapatkan strategi berdasarkan nama."""
    return _STRATEGY_REGISTRY.get(name)


def list_registered_strategies() -> List[str]:
    """Daftar nama strategi yang terdaftar."""
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
