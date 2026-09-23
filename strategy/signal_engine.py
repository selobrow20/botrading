from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import pandas as pd
from config.settings import load_config, setup_logger
from indicators.technical import TechnicalIndicators
from strategy.rules import Strategy, RuleCondition, DEFAULT_STRATEGY, get_strategy, register_strategy

logger = setup_logger("signal_engine")


@dataclass
class SignalResult:
    """Hasil evaluasi sinyal trading untuk satu saham."""
    ticker: str
    strategy_name: str
    signal: str           # 'BUY', 'SELL', 'HOLD'
    price: float
    candle_time: str
    reasons: List[str] = field(default_factory=list)
    indicators_snapshot: Dict[str, float] = field(default_factory=dict)
    # Target Profit & Stop Loss untuk Trading Harian
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    risk_reward_ratio: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "strategy_name": self.strategy_name,
            "signal": self.signal,
            "price": self.price,
            "candle_time": self.candle_time,
            "reasons": self.reasons,
            "indicators": self.indicators_snapshot,
            "take_profit_price": self.take_profit_price,
            "stop_loss_price": self.stop_loss_price,
            "risk_reward_ratio": self.risk_reward_ratio,
        }


class SignalEngine:
    """Engine evaluasi aturan strategi untuk menghasilkan sinyal BUY/SELL/HOLD."""

    def __init__(self, strategies: Optional[List[Strategy]] = None):
        self.config = load_config()
        if strategies is not None:
            self.strategies = strategies
        else:
            self.strategies = self._load_strategies_from_config()

    def _load_strategies_from_config(self) -> List[Strategy]:
        """Memuat strategi aktif dari config.yaml."""
        strat_cfg = self.config.get("strategies", {})
        definitions = strat_cfg.get("definitions", {})

        loaded_strategies = []
        for name, data in definitions.items():
            strat = Strategy.from_dict(name, data)
            register_strategy(strat)
            loaded_strategies.append(strat)

        if not loaded_strategies:
            loaded_strategies = [DEFAULT_STRATEGY]

        return loaded_strategies

    def evaluate_bar(
        self,
        df: pd.DataFrame,
        ticker: str,
        strategy: Optional[Strategy] = None,
        bar_idx: int = -1,
    ) -> SignalResult:
        """
        Mengevaluasi bar/candle tertentu (default candle terkini -1) terhadap strategi.
        
        Args:
            df: DataFrame yang sudah dihitung indikator teknikalnya (atau OHLCV murni)
            ticker: Kode saham (misal 'BBCA.JK')
            strategy: Strategi yang ingin dievaluasi (default strategi pertama)
            bar_idx: Index bar yang dievaluasi (default -1 untuk candle terakhir)
        """
        target_strategy = strategy or self.strategies[0]

        # Pastikan indikator sudah terhitung
        if "rsi" not in [c.lower() for c in df.columns]:
            df_with_ind = TechnicalIndicators.add_all_indicators(df)
        else:
            df_with_ind = df

        if len(df_with_ind) < 2:
            return SignalResult(
                ticker=ticker,
                strategy_name=target_strategy.name,
                signal="HOLD",
                price=float(df_with_ind["Close"].iloc[-1]) if not df_with_ind.empty else 0.0,
                candle_time=str(df_with_ind.index[-1]) if not df_with_ind.empty else "",
                reasons=["Data tidak cukup untuk evaluasi strategi (< 2 bar)."],
            )

        curr_row = df_with_ind.iloc[bar_idx]
        prev_row = df_with_ind.iloc[bar_idx - 1] if abs(bar_idx) < len(df_with_ind) else None

        candle_time = (
            curr_row.name.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(curr_row.name, pd.Timestamp)
            else str(curr_row.name)
        )
        curr_price = float(curr_row["Close"])

        # Snapshot indikator utama
        snapshot = {
            "close": curr_price,
            "rsi": float(curr_row.get("rsi", 0.0)),
            "ema_20": float(curr_row.get("ema_20", 0.0)),
            "ema_50": float(curr_row.get("ema_50", 0.0)),
            "volume_ratio": float(curr_row.get("volume_ratio", 0.0)),
        }

        # 1. Evaluasi Aturan BUY
        buy_results = [r.evaluate_bar(curr_row, prev_row) for r in target_strategy.buy_rules]
        buy_satisfied_list = [res[0] for res in buy_results]
        buy_reasons = [res[1] for res in buy_results if res[0]]

        if target_strategy.buy_combine == "AND":
            is_buy = all(buy_satisfied_list) and len(buy_satisfied_list) > 0
        else:  # OR
            is_buy = any(buy_satisfied_list) and len(buy_satisfied_list) > 0

        # 2. Evaluasi Aturan SELL
        sell_results = [r.evaluate_bar(curr_row, prev_row) for r in target_strategy.sell_rules]
        sell_satisfied_list = [res[0] for res in sell_results]
        sell_reasons = [res[1] for res in sell_results if res[0]]

        if target_strategy.sell_combine == "AND":
            is_sell = all(sell_satisfied_list) and len(sell_satisfied_list) > 0
        else:  # OR
            is_sell = any(sell_satisfied_list) and len(sell_satisfied_list) > 0

        # 3. Hitung Manajemen Risiko Trading Harian (TP / SL / RRR)
        trading_cfg = self.config.get("trading", {})
        trading_mode = trading_cfg.get("mode", "intraday")
        mode_cfg = trading_cfg.get(trading_mode, {})
        tp_pct = float(mode_cfg.get("take_profit_pct", 2.5 if trading_mode == "intraday" else 5.0))
        sl_pct = float(mode_cfg.get("stop_loss_pct", 1.5 if trading_mode == "intraday" else 3.0))

        tp_price = round(curr_price * (1.0 + (tp_pct / 100.0)), 0)
        sl_price = round(curr_price * (1.0 - (sl_pct / 100.0)), 0)
        risk_dist = max(curr_price - sl_price, 1.0)
        rrr = round((tp_price - curr_price) / risk_dist, 2)

        # 4. Keputusan Sinyal & Alasan
        if is_buy:
            signal = "BUY"
            reasons = list(buy_reasons)
            reasons.append(
                f"🎯 Level Trading Harian: TP = Rp {tp_price:,.0f} (+{tp_pct:.1f}%), "
                f"SL = Rp {sl_price:,.0f} (-{sl_pct:.1f}%), RRR = 1:{rrr}"
            )
        elif is_sell:
            signal = "SELL"
            reasons = sell_reasons
        else:
            signal = "HOLD"
            # Sertakan penjelasan kondisi saat ini
            reasons = [
                f"Kondisi netral / belum terpenuhi. RSI={snapshot['rsi']:.1f}, "
                f"Close={curr_price:.0f}, EMA50={snapshot['ema_50']:.0f}, "
                f"Vol Ratio={snapshot['volume_ratio']:.2f}x"
            ]

        logger.debug(
            f"Evaluasi {ticker} ({target_strategy.name}) @ {candle_time}: "
            f"Signal={signal}, Price={curr_price}, Reasons={reasons}"
        )

        return SignalResult(
            ticker=ticker,
            strategy_name=target_strategy.name,
            signal=signal,
            price=curr_price,
            candle_time=candle_time,
            reasons=reasons,
            indicators_snapshot=snapshot,
            take_profit_price=tp_price if signal == "BUY" else None,
            stop_loss_price=sl_price if signal == "BUY" else None,
            risk_reward_ratio=rrr if signal == "BUY" else None,
        )

    def evaluate_all_strategies(
        self,
        df: pd.DataFrame,
        ticker: str,
        bar_idx: int = -1,
    ) -> List[SignalResult]:
        """Mengevaluasi semua strategi yang terdaftar secara bersamaan untuk suatu saham."""
        results = []
        for strat in self.strategies:
            res = self.evaluate_bar(df, ticker, strategy=strat, bar_idx=bar_idx)
            results.append(res)
        return results

    @staticmethod
    def generate_signals_series(df: pd.DataFrame, strategy: Strategy) -> pd.DataFrame:
        """
        Menghasilkan deret sinyal ('BUY', 'SELL', 'HOLD') untuk seluruh bar historis DataFrame.
        Digunakan oleh backtester untuk memastikan logika identik 100% tanpa duplikasi kode.
        """
        # Pastikan indikator sudah ada
        if "rsi" not in [c.lower() for c in df.columns]:
            df_ind = TechnicalIndicators.add_all_indicators(df)
        else:
            df_ind = df.copy()

        # Evaluasi BUY series
        buy_series_list = [r.evaluate_series(df_ind) for r in strategy.buy_rules]
        if strategy.buy_combine == "AND":
            buy_mask = pd.Series(True, index=df_ind.index)
            for s in buy_series_list:
                buy_mask = buy_mask & s
        else:  # OR
            buy_mask = pd.Series(False, index=df_ind.index)
            for s in buy_series_list:
                buy_mask = buy_mask | s

        # Evaluasi SELL series
        sell_series_list = [r.evaluate_series(df_ind) for r in strategy.sell_rules]
        if strategy.sell_combine == "AND":
            sell_mask = pd.Series(True, index=df_ind.index)
            for s in sell_series_list:
                sell_mask = sell_mask & s
        else:  # OR
            sell_mask = pd.Series(False, index=df_ind.index)
            for s in sell_series_list:
                sell_mask = sell_mask | s

        # Buat kolom Signal
        signals = pd.Series("HOLD", index=df_ind.index)
        signals[buy_mask] = "BUY"
        # Jika ada konflik pada bar yang sama, sell mendominasi atau buy mendominasi sesuai rule
        signals[sell_mask] = "SELL"
        # Bar yang memenuhi keduanya diberi status BUY jika buy dicek belakangan, tapi di pasar biasanya eksklusif

        out_df = df_ind.copy()
        out_df["Signal"] = signals
        out_df["Buy_Signal"] = buy_mask
        out_df["Sell_Signal"] = sell_mask
        return out_df
