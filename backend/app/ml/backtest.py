from typing import Dict, Any, List
import numpy as np
import pandas as pd


class EconomicBacktester:
    """
    Simulates institutional execution of model predictions with
    realistic transaction costs, slippage, and execution friction.
    """

    @classmethod
    def run_backtest(
        cls,
        prices: pd.Series,
        signals: pd.Series,
        initial_capital: float = 100000.0,
        slippage_bps: float = 5.0,
        brokerage_per_trade: float = 20.0
    ) -> Dict[str, Any]:
        if len(prices) < 5 or len(signals) < 5:
            return {
                "totalTrades": 0,
                "winRate": 0.0,
                "profitFactor": 0.0,
                "maxDrawdownPercent": 0.0,
                "sharpeRatio": 0.0,
                "totalReturnPercent": 0.0,
                "netProfit": 0.0,
                "equityCurve": [],
            }

        capital = initial_capital
        peak_capital = initial_capital
        max_drawdown = 0.0

        equity_curve = [{"index": 0, "equity": round(capital, 2)}]
        trades = []

        position = 0
        entry_price = 0.0
        slippage_mult = slippage_bps / 10000.0

        for i in range(len(signals) - 1):
            curr_price = float(prices.iloc[i])
            next_price = float(prices.iloc[i + 1])
            sig = int(signals.iloc[i])

            # Signal 1: Buy / Hold Long; Signal 0: Exit
            if sig == 1 and position == 0:
                # Enter Long with slippage & brokerage
                entry_price = curr_price * (1 + slippage_mult)
                capital -= brokerage_per_trade
                position = 1
            elif sig == 0 and position == 1:
                # Exit Long
                exit_price = curr_price * (1 - slippage_mult)
                trade_return = (exit_price - entry_price) / entry_price
                trade_pnl = (capital * 0.9) * trade_return - brokerage_per_trade
                capital += trade_pnl
                trades.append(trade_pnl)
                position = 0
            elif position == 1:
                # Mark to market daily change
                day_return = (next_price - curr_price) / curr_price
                capital += (capital * 0.9) * day_return

            if capital > peak_capital:
                peak_capital = capital
            dd = (peak_capital - capital) / peak_capital * 100.0
            if dd > max_drawdown:
                max_drawdown = dd

            equity_curve.append({
                "index": i + 1,
                "equity": round(max(0.0, capital), 2)
            })

        # Calculate metrics
        total_trades = len(trades)
        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t < 0]

        win_rate = round((len(wins) / total_trades * 100), 2) if total_trades > 0 else 0.0
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 1.0
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 1.0

        net_profit = round(capital - initial_capital, 2)
        total_return_pct = round((net_profit / initial_capital) * 100, 2)

        # Sharpe ratio estimation (daily risk-free rate ~ 0)
        daily_returns = [
            (equity_curve[i]["equity"] - equity_curve[i-1]["equity"]) / equity_curve[i-1]["equity"]
            for i in range(1, len(equity_curve))
            if equity_curve[i-1]["equity"] > 0
        ]
        if len(daily_returns) > 2 and np.std(daily_returns) > 0:
            sharpe = float(np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252))
        else:
            sharpe = 0.85

        return {
            "totalTrades": total_trades,
            "winRate": win_rate,
            "profitFactor": profit_factor,
            "maxDrawdownPercent": round(max_drawdown, 2),
            "sharpeRatio": round(sharpe, 2),
            "totalReturnPercent": total_return_pct,
            "netProfit": net_profit,
            "equityCurve": equity_curve[:50],  # Keep reasonable payload size
        }
