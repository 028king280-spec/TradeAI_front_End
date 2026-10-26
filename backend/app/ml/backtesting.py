from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd


class BacktestEngine:
    """
    Institutional Backtesting Engine for Indian Stock Markets.
    - Simulates signal generation, entry, target exit, stop-loss exit, and time exit.
    - Factors in Indian transaction costs (STT, exchange turnover fees, GST) and slippage.
    - Calculates Win Rate, Profit Factor, Max Drawdown, Average Return, Sharpe-like metric, Expectancy.
    - Strictly disclaims backtest metrics as historical simulation, never guaranteed future return.
    """

    @classmethod
    def run_backtest(
        cls,
        df: pd.DataFrame,
        signals: pd.Series,  # 1 for CALL, -1 for PUT, 0 for neutral
        initial_capital: float = 1000000.0,
        position_size_pct: float = 0.15,
        target_pct: float = 0.025,
        stop_loss_pct: float = 0.015,
        max_holding_bars: int = 8,
        slippage_pct: float = 0.0005,
        cost_bps: float = 0.0012,  # 12 bps for STT + Brokerage + Exchange fees
    ) -> Dict[str, Any]:
        if df.empty or len(df) < 20:
            return cls._empty_result(initial_capital)

        capital = initial_capital
        equity_curve = [initial_capital]
        trades: List[Dict[str, Any]] = []

        in_position = False
        pos_type = 0  # 1: Long, -1: Short
        entry_price = 0.0
        entry_bar = 0
        allocated_capital = 0.0

        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        timestamps = df["timestamp"].values if "timestamp" in df.columns else df.index.values

        for i in range(len(df)):
            cur_close = float(close[i])
            cur_high = float(high[i])
            cur_low = float(low[i])
            cur_time = str(timestamps[i])

            if in_position:
                bars_held = i - entry_bar
                exit_price = None
                exit_reason = None

                if pos_type == 1:  # Long / CALL
                    # Check Target
                    if cur_high >= entry_price * (1.0 + target_pct):
                        exit_price = entry_price * (1.0 + target_pct) * (1.0 - slippage_pct)
                        exit_reason = "Target Met"
                    # Check Stop Loss
                    elif cur_low <= entry_price * (1.0 - stop_loss_pct):
                        exit_price = entry_price * (1.0 - stop_loss_pct) * (1.0 - slippage_pct)
                        exit_reason = "Stop Loss"
                    # Check Time Exit
                    elif bars_held >= max_holding_bars:
                        exit_price = cur_close * (1.0 - slippage_pct)
                        exit_reason = "Time Exit"

                    if exit_price is not None:
                        gross_return = (exit_price - entry_price) / entry_price
                        net_return = gross_return - (cost_bps * 2)  # Entry + exit round trip
                        pnl = allocated_capital * net_return
                        capital += pnl

                        trades.append({
                            "symbol": "BACKTEST",
                            "type": "CALL",
                            "entry_price": round(entry_price, 2),
                            "exit_price": round(exit_price, 2),
                            "pnl": round(pnl, 2),
                            "pnl_pct": round(net_return * 100, 2),
                            "reason": exit_reason,
                            "bars_held": bars_held,
                            "exit_time": cur_time,
                        })
                        in_position = False

                elif pos_type == -1:  # Short / PUT
                    if cur_low <= entry_price * (1.0 - target_pct):
                        exit_price = entry_price * (1.0 - target_pct) * (1.0 + slippage_pct)
                        exit_reason = "Target Met"
                    elif cur_high >= entry_price * (1.0 + stop_loss_pct):
                        exit_price = entry_price * (1.0 + stop_loss_pct) * (1.0 + slippage_pct)
                        exit_reason = "Stop Loss"
                    elif bars_held >= max_holding_bars:
                        exit_price = cur_close * (1.0 + slippage_pct)
                        exit_reason = "Time Exit"

                    if exit_price is not None:
                        gross_return = (entry_price - exit_price) / entry_price
                        net_return = gross_return - (cost_bps * 2)
                        pnl = allocated_capital * net_return
                        capital += pnl

                        trades.append({
                            "symbol": "BACKTEST",
                            "type": "PUT",
                            "entry_price": round(entry_price, 2),
                            "exit_price": round(exit_price, 2),
                            "pnl": round(pnl, 2),
                            "pnl_pct": round(net_return * 100, 2),
                            "reason": exit_reason,
                            "bars_held": bars_held,
                            "exit_time": cur_time,
                        })
                        in_position = False

            # Check new signal entry
            if not in_position and i < len(signals):
                sig = int(signals.iloc[i]) if hasattr(signals, "iloc") else int(signals[i])
                if sig in [1, -1]:
                    in_position = True
                    pos_type = sig
                    entry_price = cur_close * (1.0 + (slippage_pct if sig == 1 else -slippage_pct))
                    entry_bar = i
                    allocated_capital = capital * position_size_pct

            equity_curve.append(round(capital, 2))

        # Metric calculations
        total_trades = len(trades)
        if total_trades == 0:
            return cls._empty_result(initial_capital)

        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]

        win_rate = round((len(wins) / total_trades) * 100.0, 2)
        total_profit = sum(t["pnl"] for t in wins)
        total_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = round(total_profit / total_loss, 2) if total_loss > 0 else 9.99

        avg_return_pct = round(float(np.mean([t["pnl_pct"] for t in trades])), 2)
        avg_win_pct = round(float(np.mean([t["pnl_pct"] for t in wins])), 2) if wins else 0.0
        avg_loss_pct = round(abs(float(np.mean([t["pnl_pct"] for t in losses]))), 2) if losses else 0.0

        # Mathematical Expectancy
        expectancy = round(((win_rate / 100.0) * avg_win_pct) - (((100.0 - win_rate) / 100.0) * avg_loss_pct), 2)

        # Max Drawdown calculation
        eq_arr = np.array(equity_curve)
        peak = np.maximum.accumulate(eq_arr)
        drawdowns = (eq_arr - peak) / peak
        max_drawdown_pct = round(float(abs(np.min(drawdowns)) * 100.0), 2)

        # Sharpe Ratio (annualized assuming daily candles)
        returns_arr = np.diff(eq_arr) / eq_arr[:-1]
        std_ret = np.std(returns_arr)
        sharpe = round(float((np.mean(returns_arr) / std_ret) * np.sqrt(252)), 2) if std_ret > 0 else 0.0

        return {
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown_pct": max_drawdown_pct,
            "average_return_pct": avg_return_pct,
            "sharpe_ratio": sharpe,
            "total_trades": total_trades,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "expectancy": expectancy,
            "initial_capital": initial_capital,
            "final_equity": round(capital, 2),
            "net_pnl": round(capital - initial_capital, 2),
            "trades": trades[-20:],  # Recent 20 trades
            "disclaimer": "Simulated historical performance under slippage and fees. Does NOT guarantee future results.",
        }

    @staticmethod
    def _empty_result(initial_capital: float) -> Dict[str, Any]:
        return {
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "average_return_pct": 0.0,
            "sharpe_ratio": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "expectancy": 0.0,
            "initial_capital": initial_capital,
            "final_equity": initial_capital,
            "net_pnl": 0.0,
            "trades": [],
            "disclaimer": "Insufficient trade occurrences for statistical simulation.",
        }
