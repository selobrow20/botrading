import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")  # Mode headless agar aman dijalankan tanpa antarmuka grafis
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from config.settings import BASE_DIR, setup_logger
from indicators.technical import TechnicalIndicators
from strategy.rules import Strategy, RuleCondition
from strategy.signal_engine import SignalEngine
from data.storage import StockStorage

logger = setup_logger("backtester")


@dataclass
class Trade:
    """Catatan riwayat transaksi satu trade (Entry hingga Exit)."""
    ticker: str
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float
    holding_bars: int
    exit_reason: str


@dataclass
class BacktestResult:
    """Hasil komprehensif dari simulasi backtesting."""
    strategy_name: str
    ticker: str
    start_date: str
    end_date: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    buy_and_hold_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: Optional[float]
    max_drawdown_pct: float
    trades: List[Trade] = field(default_factory=list)
    equity_series: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    chart_path: Optional[str] = None

    def summary_dict(self) -> Dict[str, Any]:
        return {
            "Strategy": self.strategy_name,
            "Ticker": self.ticker,
            "Period": f"{self.start_date} s/d {self.end_date}",
            "Initial Capital": f"Rp {self.initial_capital:,.0f}",
            "Final Equity": f"Rp {self.final_equity:,.0f}",
            "Total Return": f"{self.total_return_pct:.2f}%",
            "Buy & Hold Return": f"{self.buy_and_hold_return_pct:.2f}%",
            "Total Trades": self.total_trades,
            "Win Rate": f"{self.win_rate_pct:.1f}%",
            "Profit Factor": f"{self.profit_factor:.2f}" if self.profit_factor is not None else "N/A",
            "Max Drawdown": f"{self.max_drawdown_pct:.2f}%",
            "Chart Path": self.chart_path or "-",
        }


class Backtester:
    """Engine simulasi backtest berbasis vektor & bar-by-bar realistis (Long Only)."""

    def __init__(
        self,
        initial_capital: float = 100_000_000.0,  # Rp 100 Juta
        commission_pct: float = 0.0015,         # 0.15% fee beli / 0.25% jual rata-rata
        slippage_pct: float = 0.001,            # 0.1% estimasi slippage harga
        take_profit_pct: Optional[float] = None, # TP otomatis (opsional)
        stop_loss_pct: Optional[float] = None,   # SL otomatis (opsional)
        storage: Optional[StockStorage] = None,
    ):
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.storage = storage or StockStorage()

    def run(
        self,
        df: pd.DataFrame,
        strategy: Strategy,
        ticker: str = "STOCK.JK",
        save_chart: bool = True,
        output_dir: Optional[str | Path] = None,
        take_profit_pct: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
    ) -> BacktestResult:
        """
        Menjalankan backtest strategi terhadap data historis OHLCV.
        
        Args:
            df: DataFrame OHLCV
            strategy: Objek Strategy yang dievaluasi
            ticker: Kode saham
            save_chart: Apakah membuat dan menyimpan gambar equity curve
            output_dir: Folder penyimpanan grafik
            take_profit_pct: Target Profit persentase (opsional, misal 2.5%)
            stop_loss_pct: Stop Loss persentase (opsional, misal 1.5%)
        """
        if df.empty or len(df) < 5:
            raise ValueError("Data historis tidak mencukupi untuk backtest (< 5 baris).")

        tp_pct = take_profit_pct if take_profit_pct is not None else self.take_profit_pct
        sl_pct = stop_loss_pct if stop_loss_pct is not None else self.stop_loss_pct

        # 1. Hitung seluruh sinyal menggunakan modul Strategy / SignalEngine
        df_signals = SignalEngine.generate_signals_series(df, strategy)

        # 2. Jalankan simulasi trading
        cash = self.initial_capital
        position_shares = 0
        entry_price = 0.0
        entry_time = None
        entry_bar_idx = 0
        trades: List[Trade] = []

        equity_list = []
        dates_list = []

        # IDX Lot Size: 1 lot = 100 shares
        LOT_SIZE = 100

        for i in range(len(df_signals)):
            current_bar = df_signals.iloc[i]
            date = df_signals.index[i]
            close_price = float(current_bar["Close"])
            high_price = float(current_bar["High"])
            low_price = float(current_bar["Low"])
            signal = current_bar.get("Signal", "HOLD")

            # Update Nilai Equity saat ini
            current_equity = cash + (position_shares * close_price)
            equity_list.append(current_equity)
            dates_list.append(date)

            # Cek Exit Otomatis untuk Posisi Terbuka (TP / SL / Sell Signal)
            if position_shares > 0:
                is_exit = False
                exit_price_val = close_price
                exit_reason_str = ""

                # 1. Cek Take Profit
                if tp_pct is not None and tp_pct > 0:
                    tp_target = entry_price * (1.0 + (tp_pct / 100.0))
                    if high_price >= tp_target:
                        is_exit = True
                        exit_price_val = tp_target
                        exit_reason_str = f"Take Profit Hit (+{tp_pct:.1f}%)"

                # 2. Cek Stop Loss (jika belum TP)
                if not is_exit and sl_pct is not None and sl_pct > 0:
                    sl_target = entry_price * (1.0 - (sl_pct / 100.0))
                    if low_price <= sl_target:
                        is_exit = True
                        exit_price_val = sl_target
                        exit_reason_str = f"Stop Loss Hit (-{sl_pct:.1f}%)"

                # 3. Cek Sinyal SELL dari Indikator
                if not is_exit and signal == "SELL":
                    is_exit = True
                    exit_price_val = close_price
                    exit_reason_str = "Sell Rule Triggered"

                if is_exit:
                    effective_price = exit_price_val * (1.0 - self.slippage_pct)
                    gross_proceeds = position_shares * effective_price
                    net_proceeds = gross_proceeds * (1.0 - self.commission_pct)
                    cash += net_proceeds

                    pnl = net_proceeds - (position_shares * entry_price * (1.0 + self.commission_pct))
                    pnl_pct = (effective_price - entry_price) / entry_price * 100.0

                    trades.append(
                        Trade(
                            ticker=ticker,
                            entry_time=entry_time,
                            entry_price=entry_price,
                            exit_time=date,
                            exit_price=effective_price,
                            shares=position_shares,
                            pnl=pnl,
                            pnl_pct=pnl_pct,
                            holding_bars=i - entry_bar_idx,
                            exit_reason=exit_reason_str,
                        )
                    )

                    position_shares = 0
                    entry_price = 0.0
                    entry_time = None

            # Cek Entry (BUY) jika sedang memegang kas (tidak ada posisi terbuka)
            if signal == "BUY" and position_shares == 0:
                effective_price = close_price * (1.0 + self.slippage_pct)
                cost_per_lot = (effective_price * LOT_SIZE) * (1.0 + self.commission_pct)
                available_lots = int(cash // cost_per_lot)

                if available_lots > 0:
                    shares_to_buy = available_lots * LOT_SIZE
                    total_cost = shares_to_buy * effective_price * (1.0 + self.commission_pct)
                    cash -= total_cost
                    position_shares = shares_to_buy
                    entry_price = effective_price
                    entry_time = date
                    entry_bar_idx = i

        # Jika masih ada posisi terbuka di akhir periode, tutup paksa pada harga close terakhir untuk evaluasi final
        if position_shares > 0:
            last_price = float(df_signals["Close"].iloc[-1]) * (1.0 - self.slippage_pct)
            net_proceeds = (position_shares * last_price) * (1.0 - self.commission_pct)
            cash += net_proceeds
            pnl = net_proceeds - (position_shares * entry_price * (1.0 + self.commission_pct))
            pnl_pct = (last_price - entry_price) / entry_price * 100.0
            trades.append(
                Trade(
                    ticker=ticker,
                    entry_time=entry_time,
                    entry_price=entry_price,
                    exit_time=df_signals.index[-1],
                    exit_price=last_price,
                    shares=position_shares,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    holding_bars=len(df_signals) - 1 - entry_bar_idx,
                    exit_reason="End of Backtest Period",
                )
            )
            position_shares = 0

        final_equity = cash
        equity_series = pd.Series(equity_list, index=dates_list)

        # 3. Hitung Metrik Evaluasi Kinerja
        total_return_pct = ((final_equity - self.initial_capital) / self.initial_capital) * 100.0
        
        first_close = float(df_signals["Close"].iloc[0])
        last_close = float(df_signals["Close"].iloc[-1])
        bnh_return_pct = ((last_close - first_close) / first_close) * 100.0

        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.pnl > 0)
        losing_trades = sum(1 for t in trades if t.pnl <= 0)
        win_rate_pct = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0

        total_gain = sum(t.pnl for t in trades if t.pnl > 0)
        total_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
        if total_loss > 0:
            profit_factor = total_gain / total_loss
        elif total_gain > 0:
            profit_factor = 99.9  # Semua trade profit
        else:
            profit_factor = 0.0

        # Maximum Drawdown
        running_max = equity_series.cummax()
        drawdown_series = (equity_series - running_max) / running_max * 100.0
        max_drawdown_pct = abs(float(drawdown_series.min())) if not drawdown_series.empty else 0.0

        # 4. Generate Grafik Equity Curve jika diaktifkan
        chart_path = None
        if save_chart:
            chart_path = self._plot_equity_curve(
                equity_series=equity_series,
                drawdown_series=drawdown_series,
                df_close=df_signals["Close"],
                ticker=ticker,
                strategy_name=strategy.name,
                output_dir=output_dir,
            )

        start_date_str = str(df_signals.index[0].date() if hasattr(df_signals.index[0], "date") else df_signals.index[0])
        end_date_str = str(df_signals.index[-1].date() if hasattr(df_signals.index[-1], "date") else df_signals.index[-1])

        # Simpan ke SQLite
        try:
            self.storage.save_backtest_result(
                strategy_name=strategy.name,
                ticker=ticker,
                start_date=start_date_str,
                end_date=end_date_str,
                initial_capital=self.initial_capital,
                final_equity=final_equity,
                total_trades=total_trades,
                win_rate=win_rate_pct,
                profit_factor=profit_factor,
                max_drawdown=max_drawdown_pct,
            )
        except Exception as e:
            logger.warning(f"Gagal mencatat backtest ke SQLite: {e}")

        return BacktestResult(
            strategy_name=strategy.name,
            ticker=ticker,
            start_date=start_date_str,
            end_date=end_date_str,
            initial_capital=self.initial_capital,
            final_equity=final_equity,
            total_return_pct=total_return_pct,
            buy_and_hold_return_pct=bnh_return_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=win_rate_pct,
            profit_factor=profit_factor,
            max_drawdown_pct=max_drawdown_pct,
            trades=trades,
            equity_series=equity_series,
            chart_path=chart_path,
        )

    def _plot_equity_curve(
        self,
        equity_series: pd.Series,
        drawdown_series: pd.Series,
        df_close: pd.Series,
        ticker: str,
        strategy_name: str,
        output_dir: Optional[str | Path] = None,
    ) -> str:
        """Membuat visualisasi komprehensif: Equity Curve vs Buy & Hold dan Drawdown chart."""
        if output_dir is None:
            reports_dir = BASE_DIR / "reports"
        else:
            reports_dir = Path(output_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)

        clean_strat = strategy_name.replace(" ", "_").replace("/", "_")
        clean_ticker = ticker.replace(".JK", "").replace(".", "_")
        file_path = reports_dir / f"backtest_{clean_ticker}_{clean_strat}.png"

        # Hitung Buy & Hold Equity ternormalisasi
        bnh_equity = (df_close / df_close.iloc[0]) * self.initial_capital

        fig, (ax1, ax2) = plt.subplots(
            nrows=2,
            ncols=1,
            figsize=(12, 8),
            gridspec_kw={"height_ratios": [2.5, 1]},
            sharex=True,
        )

        # Subplot 1: Equity Curve vs Buy & Hold
        ax1.plot(equity_series.index, equity_series.values, label=f"Strategi: {strategy_name}", color="#1f77b4", linewidth=2.0)
        ax1.plot(bnh_equity.index, bnh_equity.values, label=f"Buy & Hold ({ticker})", color="#7f7f7f", linestyle="--", alpha=0.8)
        ax1.set_title(f"Hasil Backtest: {ticker} - {strategy_name}", fontsize=14, fontweight="bold", pad=12)
        ax1.set_ylabel("Portofolio Equity (IDR)", fontsize=11)
        ax1.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("Rp {x:,.0f}"))
        ax1.legend(loc="upper left", frameon=True)
        ax1.grid(True, linestyle=":", alpha=0.6)

        # Subplot 2: Drawdown Area
        ax2.fill_between(drawdown_series.index, drawdown_series.values, 0, color="#d62728", alpha=0.35, label="Drawdown (%)")
        ax2.plot(drawdown_series.index, drawdown_series.values, color="#d62728", linewidth=1.0)
        ax2.set_ylabel("Drawdown (%)", fontsize=11)
        ax2.set_xlabel("Tanggal", fontsize=11)
        ax2.set_ylim([min(float(drawdown_series.min()) * 1.15, -5.0), 1.0])
        ax2.legend(loc="lower left", frameon=True)
        ax2.grid(True, linestyle=":", alpha=0.6)

        # Formatting X-axis Date
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        fig.autofmt_xdate()
        plt.tight_layout()

        fig.savefig(str(file_path), dpi=150)
        plt.close(fig)
        logger.info(f"Grafik equity curve tersimpan di: {file_path}")
        return str(file_path)

    def parameter_sweep(
        self,
        df: pd.DataFrame,
        ticker: str,
        rsi_oversold_range: List[float] = [25.0, 30.0, 35.0, 40.0],
        rsi_overbought_range: List[float] = [65.0, 70.0, 75.0],
        volume_multipliers: List[float] = [1.0, 1.2, 1.5],
    ) -> pd.DataFrame:
        """
        Membandingkan kombinasi parameter aturan untuk menemukan konfigurasi optimal
        tanpa overfitting berlebihan.
        """
        records = []
        logger.info(f"Memulai parameter sweep untuk {ticker}...")

        for rsi_buy in rsi_oversold_range:
            for rsi_sell in rsi_overbought_range:
                for vol_mult in volume_multipliers:
                    strat_name = f"Sweep_RSI_{int(rsi_buy)}_{int(rsi_sell)}_Vol_{vol_mult}x"
                    test_strategy = Strategy(
                        name=strat_name,
                        description=f"RSI < {rsi_buy} & Vol > {vol_mult}x; Exit RSI > {rsi_sell}",
                        buy_rules=[
                            RuleCondition("rsi", "<", value=rsi_buy),
                            RuleCondition("close", ">", target="ema_50"),
                            RuleCondition("volume", ">", target="volume_sma_20", multiplier=vol_mult),
                        ],
                        buy_combine="AND",
                        sell_rules=[
                            RuleCondition("rsi", ">", value=rsi_sell),
                            RuleCondition("close", "cross_under", target="ema_20"),
                        ],
                        sell_combine="OR",
                    )

                    try:
                        res = self.run(df, test_strategy, ticker=ticker, save_chart=False)
                        records.append({
                            "Strategy": strat_name,
                            "RSI_Buy": rsi_buy,
                            "RSI_Sell": rsi_sell,
                            "Vol_Mult": vol_mult,
                            "Total_Trades": res.total_trades,
                            "Win_Rate_Pct": res.win_rate_pct,
                            "Profit_Factor": res.profit_factor,
                            "Total_Return_Pct": res.total_return_pct,
                            "Max_Drawdown_Pct": res.max_drawdown_pct,
                        })
                    except Exception as e:
                        logger.debug(f"Error on sweep {strat_name}: {e}")

        sweep_df = pd.DataFrame(records)
        if not sweep_df.empty:
            # Urutkan berdasarkan Total Return atau Profit Factor
            sweep_df.sort_values(by=["Total_Return_Pct", "Profit_Factor"], ascending=[False, False], inplace=True)
        return sweep_df
