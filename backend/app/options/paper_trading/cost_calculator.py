"""
Indian Derivatives Transaction Cost & P&L Calculator.
Implements exact statutory fee schedules for NSE Equity Option Contracts:
1. Brokerage: Flat ₹20 per executed order (Entry = ₹20, Exit = ₹20)
2. STT (Securities Transaction Tax): 0.1% on sell-side option premium turnover
3. Exchange Turnover Charges: 0.05% of total premium turnover (Buy + Sell)
4. GST (Goods & Services Tax): 18% on (Brokerage + Exchange Turnover Charges)
5. SEBI Turnover Charges: ₹10 per Crore (0.0001% of total premium turnover)
6. Stamp Duty: 0.003% on buy-side premium turnover
7. Slippage: Configurable points / rupee buffer per contract lot
"""

from typing import Dict, Any, Optional


class IndianDerivativesCostCalculator:
    """
    Precision statutory cost and net P&L calculator for Indian index & stock options.
    """

    DEFAULT_BROKERAGE_PER_ORDER = 20.0
    DEFAULT_STT_RATE = 0.001          # 0.1% on sell-side option premium
    DEFAULT_EXCHANGE_TURNOVER_RATE = 0.0005  # 0.05% of total turnover
    DEFAULT_GST_RATE = 0.18           # 18% on (Brokerage + Exchange fees)
    DEFAULT_SEBI_RATE = 0.000001      # ₹10 per crore (0.0001%)
    DEFAULT_STAMP_DUTY_RATE = 0.00003 # 0.003% on buy-side turnover
    DEFAULT_SLIPPAGE_PTS = 0.5        # 0.5 pts slippage assumption

    @classmethod
    def calculate_trade_costs_and_pnl(
        cls,
        entry_price: float,
        exit_price: float,
        quantity: int,
        position_type: str = "BUY",  # "BUY" or "SELL"
        brokerage_per_order: float = DEFAULT_BROKERAGE_PER_ORDER,
        slippage_pts: float = DEFAULT_SLIPPAGE_PTS,
        orders_count: int = 2,       # 1 for entry, 1 for exit (increases with partial exits)
    ) -> Dict[str, Any]:
        """
        Calculates exact gross P&L, statutory fee breakdown, slippage, and net P&L.
        """
        qty = int(quantity)
        p_entry = float(entry_price)
        p_exit = float(exit_price)
        pos = position_type.upper().strip()

        # Turnovers
        entry_turnover = round(p_entry * qty, 2)
        exit_turnover = round(p_exit * qty, 2)
        total_turnover = round(entry_turnover + exit_turnover, 2)

        # 1. Gross P&L
        if pos == "BUY":
            gross_pnl = round((p_exit - p_entry) * qty, 2)
            margin_used = entry_turnover
            buy_turnover = entry_turnover
            sell_turnover = exit_turnover
        else:  # SELL / SHORT option
            gross_pnl = round((p_entry - p_exit) * qty, 2)
            margin_used = max(entry_turnover, 50000.0)  # Option writing margin requirement
            buy_turnover = exit_turnover
            sell_turnover = entry_turnover

        # 2. Statutory Taxes & Fees
        brokerage = round(brokerage_per_order * orders_count, 2)
        stt = round(sell_turnover * cls.DEFAULT_STT_RATE, 2)
        exchange_charges = round(total_turnover * cls.DEFAULT_EXCHANGE_TURNOVER_RATE, 2)
        gst = round((brokerage + exchange_charges) * cls.DEFAULT_GST_RATE, 2)
        sebi_charges = round(total_turnover * cls.DEFAULT_SEBI_RATE, 2)
        stamp_duty = round(buy_turnover * cls.DEFAULT_STAMP_DUTY_RATE, 2)

        statutory_taxes = round(stt + exchange_charges + gst + sebi_charges + stamp_duty, 2)

        # 3. Slippage
        slippage_cost = round(slippage_pts * qty, 2)

        # 4. Total Trading Costs & Net P&L
        total_costs = round(brokerage + statutory_taxes + slippage_cost, 2)
        net_pnl = round(gross_pnl - total_costs, 2)

        # Return on Investment / Capital
        net_roi_pct = round((net_pnl / max(1.0, margin_used)) * 100.0, 2)
        gross_pts = round(p_exit - p_entry if pos == "BUY" else p_entry - p_exit, 2)

        return {
            "entryPrice": p_entry,
            "exitPrice": p_exit,
            "quantity": qty,
            "positionType": pos,
            "marginUsed": margin_used,
            "grossPnl": gross_pnl,
            "grossPoints": gross_pts,
            "netPnl": net_pnl,
            "netRoiPercent": net_roi_pct,
            "totalCosts": total_costs,
            "feeBreakdown": {
                "brokerage": brokerage,
                "stt": stt,
                "exchangeTurnoverCharges": exchange_charges,
                "gst": gst,
                "sebiCharges": sebi_charges,
                "stampDuty": stamp_duty,
                "slippage": slippage_cost,
                "totalStatutoryTaxes": statutory_taxes,
            },
            "turnover": {
                "entryTurnover": entry_turnover,
                "exitTurnover": exit_turnover,
                "totalTurnover": total_turnover,
            }
        }

