"""
AIVOLVE Phase 4 Step 4.3 — Double-Entry Isolated Portfolio Accounting & Reconciliation Ledger.

Guarantees exact conservation and zero mixing across:
- `INDEX_POINTS_ONLY`: pure index-point tracking starting at `0.0 INDEX_POINTS` with
  zero monetary `INR` cash/reserve/drawdown balances (`*_inr == None`).
- `INDEX_POINTS_AND_EXPLICIT_INR`: separate pure `INDEX_POINTS` tracking alongside an
  explicitly multiplied `INR` ledger with full double-entry cash conservation.
- `SYNTHETIC_OPTION_INR_ONLY`: Mode B (`SYNTHETIC_MODELLED_OPTION_PNL`) INR option
  ledger with zero index-points mixing.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from app.backtesting.position_manager import MutableTradePosition
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    CostBreakdown,
    EquityCurvePoint,
    FillRecord,
    OrderRecord,
    OrderSide,
    PortfolioSummary,
    ReconciliationReport,
    SimulationMode,
    TradeLifecycleState,
    TradeRecord,
)


class PortfolioLedger:
    """
    Chronological accounting ledger maintaining strict unit segregation & conservation:
    - Index Points (`Mode A`): `realized_net_points == realized_gross_points - total_slippage_points`
    - Monetary INR (`Monetary Mode A` & `Mode B`):
      `available_cash_inr + reserved_capital_inr == starting_capital_inr + realized_gross_pnl_inr - total_costs_inr`
      `realized_net_pnl_inr == realized_gross_pnl_inr - total_costs_inr`
    """

    def __init__(
        self,
        *,
        mode: SimulationMode,
        accounting_unit_mode: AccountingUnitMode,
        provenance_label: str,
        starting_capital_inr: Optional[float] = None,
        instrument_multiplier_inr_per_point: Optional[float] = None,
        instrument_multiplier_documentation: Optional[str] = None,
    ) -> None:
        self.mode = mode
        self.accounting_unit_mode = accounting_unit_mode
        self.provenance_label = provenance_label
        self.instrument_multiplier_inr_per_point = instrument_multiplier_inr_per_point
        self.instrument_multiplier_documentation = instrument_multiplier_documentation

        self.has_points_domain = accounting_unit_mode in (
            AccountingUnitMode.INDEX_POINTS_ONLY,
            AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        )
        self.has_monetary_domain = accounting_unit_mode in (
            AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
            AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
        )

        # Index-Points accumulators (Mode A only)
        if self.has_points_domain:
            self.realized_gross_points: Optional[float] = 0.0
            self.total_slippage_points: Optional[float] = 0.0
            self.realized_net_points: Optional[float] = 0.0
            self.unrealized_points: Optional[float] = 0.0
            self.peak_equity_points: Optional[float] = 0.0
            self.max_drawdown_points: Optional[float] = 0.0
        else:
            self.realized_gross_points = None
            self.total_slippage_points = None
            self.realized_net_points = None
            self.unrealized_points = None
            self.peak_equity_points = None
            self.max_drawdown_points = None

        # Monetary INR accumulators (Monetary Mode A & Mode B only)
        if self.has_monetary_domain:
            if starting_capital_inr is None or starting_capital_inr <= 0.0:
                raise ValueError(
                    f"starting_capital_inr must be > 0 for {accounting_unit_mode.value}, got {starting_capital_inr}"
                )
            cap = round(float(starting_capital_inr), 4)
            self.starting_capital_inr: Optional[float] = cap
            self.available_cash_inr: Optional[float] = cap
            self.reserved_capital_inr: Optional[float] = 0.0
            self.realized_gross_pnl_inr: Optional[float] = 0.0
            self.unrealized_pnl_inr: Optional[float] = 0.0
            self.total_brokerage_inr: Optional[float] = 0.0
            self.total_statutory_charges_inr: Optional[float] = 0.0
            self.total_slippage_cost_inr: Optional[float] = 0.0
            self.total_costs_inr: Optional[float] = 0.0
            self.realized_net_pnl_inr: Optional[float] = 0.0
            self.peak_equity_inr: Optional[float] = cap
            self.max_drawdown_inr: Optional[float] = 0.0
            self.max_drawdown_pct: Optional[float] = 0.0
        else:
            if starting_capital_inr is not None:
                raise ValueError(
                    "MODE_MIXING_POINTS_AND_CURRENCY: starting_capital_inr must be None in INDEX_POINTS_ONLY."
                )
            self.starting_capital_inr = None
            self.available_cash_inr = None
            self.reserved_capital_inr = None
            self.realized_gross_pnl_inr = None
            self.unrealized_pnl_inr = None
            self.total_brokerage_inr = None
            self.total_statutory_charges_inr = None
            self.total_slippage_cost_inr = None
            self.total_costs_inr = None
            self.realized_net_pnl_inr = None
            self.peak_equity_inr = None
            self.max_drawdown_inr = None
            self.max_drawdown_pct = None

        self.equity_curve: List[EquityCurvePoint] = []
        self.all_fills: List[FillRecord] = []
        self.all_orders: List[OrderRecord] = []

    def can_afford_entry(
        self,
        *,
        required_reserve_inr: Optional[float],
        entry_costs_inr: Optional[float],
        max_fraction: float,
    ) -> Tuple[bool, Optional[str]]:
        """Checks free INR cash and per-trade allocation limit when monetary domain is active."""
        if not self.has_monetary_domain:
            return True, None

        assert self.starting_capital_inr is not None and self.available_cash_inr is not None
        assert required_reserve_inr is not None and entry_costs_inr is not None

        max_allowed = self.starting_capital_inr * max_fraction
        if required_reserve_inr > max_allowed + 1e-6:
            return (
                False,
                f"CAPITAL_ALLOCATION_LIMIT: required reserve {required_reserve_inr:.2f} INR exceeds "
                f"{max_fraction * 100:.1f}% limit ({max_allowed:.2f} INR).",
            )
        total_outflow = round(required_reserve_inr + entry_costs_inr, 4)
        if total_outflow > self.available_cash_inr + 1e-6:
            return (
                False,
                f"INSUFFICIENT_CAPITAL: required {total_outflow:.2f} INR (reserve={required_reserve_inr:.2f} + "
                f"costs={entry_costs_inr:.2f}) exceeds available cash {self.available_cash_inr:.2f} INR.",
            )
        return True, None

    def _accumulate_inr_cost_totals(self, costs: CostBreakdown) -> None:
        assert self.has_monetary_domain
        assert costs.cost_unit == "INR"
        assert (
            costs.brokerage_inr is not None
            and costs.stt_inr is not None
            and costs.exchange_txn_charges_inr is not None
            and costs.gst_inr is not None
            and costs.sebi_charges_inr is not None
            and costs.stamp_duty_inr is not None
            and costs.slippage_cost_inr is not None
            and costs.total_costs_inr is not None
        )
        self.total_brokerage_inr = round((self.total_brokerage_inr or 0.0) + costs.brokerage_inr, 4)
        statutory_only = round(
            costs.stt_inr
            + costs.exchange_txn_charges_inr
            + costs.gst_inr
            + costs.sebi_charges_inr
            + costs.stamp_duty_inr,
            4,
        )
        self.total_statutory_charges_inr = round((self.total_statutory_charges_inr or 0.0) + statutory_only, 4)
        self.total_slippage_cost_inr = round((self.total_slippage_cost_inr or 0.0) + costs.slippage_cost_inr, 4)
        self.total_costs_inr = round((self.total_costs_inr or 0.0) + costs.total_costs_inr, 4)

    def record_entry(
        self,
        *,
        required_reserve_inr: Optional[float],
        entry_fill: FillRecord,
    ) -> None:
        """Applies entry slippage/fees and optional INR reserve atomically."""
        if self.has_points_domain:
            assert entry_fill.slippage_points_leg is not None
            assert self.realized_gross_points is not None and self.total_slippage_points is not None
            self.total_slippage_points = round(self.total_slippage_points + entry_fill.slippage_points_leg, 6)
            self.realized_net_points = round(self.realized_gross_points - self.total_slippage_points, 6)

        if self.has_monetary_domain:
            assert required_reserve_inr is not None and entry_fill.costs.total_costs_inr is not None
            assert self.available_cash_inr is not None and self.reserved_capital_inr is not None
            assert self.realized_gross_pnl_inr is not None
            total_outflow = round(required_reserve_inr + entry_fill.costs.total_costs_inr, 4)
            if total_outflow > self.available_cash_inr + 1e-6:
                raise ValueError(
                    f"Insufficient INR cash during entry commit for trade '{entry_fill.trade_id}'."
                )
            self.available_cash_inr = round(self.available_cash_inr - total_outflow, 4)
            self.reserved_capital_inr = round(self.reserved_capital_inr + required_reserve_inr, 4)
            self._accumulate_inr_cost_totals(entry_fill.costs)
            self.realized_net_pnl_inr = round(self.realized_gross_pnl_inr - (self.total_costs_inr or 0.0), 4)

        self.all_fills.append(entry_fill)

    def record_exit(
        self,
        *,
        released_reserve_inr: Optional[float],
        exit_fill: FillRecord,
    ) -> None:
        """Credits realized PnL and deducts exit slippage/fees atomically per active domain."""
        if self.has_points_domain:
            assert exit_fill.gross_points_leg is not None and exit_fill.slippage_points_leg is not None
            assert self.realized_gross_points is not None and self.total_slippage_points is not None
            self.realized_gross_points = round(self.realized_gross_points + exit_fill.gross_points_leg, 6)
            self.total_slippage_points = round(self.total_slippage_points + exit_fill.slippage_points_leg, 6)
            self.realized_net_points = round(self.realized_gross_points - self.total_slippage_points, 6)

        if self.has_monetary_domain:
            assert (
                released_reserve_inr is not None
                and exit_fill.gross_pnl_inr_leg is not None
                and exit_fill.costs.total_costs_inr is not None
            )
            assert self.available_cash_inr is not None and self.reserved_capital_inr is not None
            assert self.realized_gross_pnl_inr is not None
            self.reserved_capital_inr = round(max(0.0, self.reserved_capital_inr - released_reserve_inr), 4)
            self.realized_gross_pnl_inr = round(self.realized_gross_pnl_inr + exit_fill.gross_pnl_inr_leg, 4)
            self._accumulate_inr_cost_totals(exit_fill.costs)
            self.available_cash_inr = round(
                self.available_cash_inr
                + released_reserve_inr
                + exit_fill.gross_pnl_inr_leg
                - exit_fill.costs.total_costs_inr,
                4,
            )
            self.realized_net_pnl_inr = round(self.realized_gross_pnl_inr - (self.total_costs_inr or 0.0), 4)

        self.all_fills.append(exit_fill)

    def record_bar_snapshot(
        self,
        *,
        timestamp_ist: str,
        open_trades: Sequence[MutableTradePosition],
    ) -> EquityCurvePoint:
        """Snapshots separated points curve and/or INR equity curve at completed bar close."""
        cum_pts: Optional[float] = None
        dd_pts: Optional[float] = None
        if self.has_points_domain:
            assert (
                self.realized_gross_points is not None
                and self.total_slippage_points is not None
                and self.realized_net_points is not None
                and self.peak_equity_points is not None
                and self.max_drawdown_points is not None
            )
            mtm_pts = round(sum((t.unrealized_points or 0.0) for t in open_trades), 6)
            self.unrealized_points = mtm_pts
            cum_pts = round(self.realized_net_points + mtm_pts, 6)
            if cum_pts > self.peak_equity_points:
                self.peak_equity_points = cum_pts
            dd_pts = round(max(0.0, self.peak_equity_points - cum_pts), 6)
            if dd_pts > self.max_drawdown_points:
                self.max_drawdown_points = dd_pts

        eq_inr: Optional[float] = None
        dd_inr: Optional[float] = None
        dd_pct: Optional[float] = None
        if self.has_monetary_domain:
            assert (
                self.available_cash_inr is not None
                and self.reserved_capital_inr is not None
                and self.peak_equity_inr is not None
                and self.max_drawdown_inr is not None
                and self.max_drawdown_pct is not None
            )
            mtm_inr = round(sum((t.unrealized_pnl_inr or 0.0) for t in open_trades), 4)
            self.unrealized_pnl_inr = mtm_inr
            eq_inr = round(self.available_cash_inr + self.reserved_capital_inr + mtm_inr, 4)
            if eq_inr > self.peak_equity_inr:
                self.peak_equity_inr = eq_inr
            dd_inr = round(max(0.0, self.peak_equity_inr - eq_inr), 4)
            dd_pct = round((dd_inr / self.peak_equity_inr) * 100.0, 4) if self.peak_equity_inr > 0 else 0.0
            if dd_inr > self.max_drawdown_inr:
                self.max_drawdown_inr = dd_inr
            if dd_pct > self.max_drawdown_pct:
                self.max_drawdown_pct = dd_pct

        pt = EquityCurvePoint(
            timestamp_ist=timestamp_ist,
            accounting_unit_mode=self.accounting_unit_mode,
            realized_gross_points=self.realized_gross_points,
            total_slippage_points=self.total_slippage_points,
            realized_net_points=self.realized_net_points,
            unrealized_points=self.unrealized_points,
            cumulative_equity_points=cum_pts,
            drawdown_points=dd_pts,
            available_cash_inr=self.available_cash_inr,
            reserved_capital_inr=self.reserved_capital_inr,
            realized_gross_pnl_inr=self.realized_gross_pnl_inr,
            realized_net_pnl_inr=self.realized_net_pnl_inr,
            unrealized_pnl_inr=self.unrealized_pnl_inr,
            total_costs_inr=self.total_costs_inr,
            total_equity_inr=eq_inr,
            drawdown_inr=dd_inr,
            drawdown_pct=dd_pct,
            open_trades_count=len(open_trades),
        )
        self.equity_curve.append(pt)
        return pt

    def reconcile(self, trades: Sequence[TradeRecord]) -> ReconciliationReport:
        """Runs strict conservation, zero double-count, AND non-mixing invariants."""
        failed: List[str] = []
        non_mixing_ok = True

        accepted_trades = [
            t
            for t in trades
            if t.state not in (TradeLifecycleState.REJECTED, TradeLifecycleState.CANCELLED)
        ]

        # Non-mixing structural checks across ledger, fills, trades, and curve
        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if (
                self.available_cash_inr is not None
                or self.reserved_capital_inr is not None
                or self.realized_net_pnl_inr is not None
                or self.starting_capital_inr is not None
            ):
                non_mixing_ok = False
                failed.append("POINTS_ONLY_MONETARY_LEAKAGE_IN_LEDGER")
            for f in self.all_fills:
                if f.costs.cost_unit != "INDEX_POINTS" or f.gross_pnl_inr_leg is not None:
                    non_mixing_ok = False
                    failed.append(f"POINTS_ONLY_MONETARY_LEAKAGE_IN_FILL:{f.fill_id}")
            for tr in trades:
                if tr.gross_pnl_inr is not None or tr.net_pnl_inr is not None or tr.reserved_capital_inr is not None:
                    non_mixing_ok = False
                    failed.append(f"POINTS_ONLY_MONETARY_LEAKAGE_IN_TRADE:{tr.trade_id}")
        elif self.accounting_unit_mode == AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY:
            if self.realized_gross_points is not None or self.realized_net_points is not None:
                non_mixing_ok = False
                failed.append("OPTION_INR_INDEX_POINTS_LEAKAGE_IN_LEDGER")
            for f in self.all_fills:
                if f.gross_points_leg is not None or f.slippage_points_leg is not None:
                    non_mixing_ok = False
                    failed.append(f"OPTION_INR_INDEX_POINTS_LEAKAGE_IN_FILL:{f.fill_id}")
            for tr in trades:
                if tr.gross_points is not None or tr.net_points is not None:
                    non_mixing_ok = False
                    failed.append(f"OPTION_INR_INDEX_POINTS_LEAKAGE_IN_TRADE:{tr.trade_id}")
        else:
            if self.instrument_multiplier_inr_per_point is None or not self.instrument_multiplier_documentation:
                non_mixing_ok = False
                failed.append("MISSING_EXPLICIT_MULTIPLIER_DOCUMENTATION")

        pts_reconciled: Optional[bool] = None
        pts_net_diff: Optional[float] = None
        pts_gross_diff: Optional[float] = None
        pts_slip_diff: Optional[float] = None
        pts_trade_net_diff: Optional[float] = None

        if self.has_points_domain:
            assert (
                self.realized_gross_points is not None
                and self.total_slippage_points is not None
                and self.realized_net_points is not None
            )
            pts_net_diff = round(
                abs((self.realized_gross_points - self.total_slippage_points) - self.realized_net_points),
                6,
            )
            t_pts_gross = round(sum((t.gross_points or 0.0) for t in accepted_trades), 6)
            t_pts_slip = round(sum((t.slippage_points or 0.0) for t in accepted_trades), 6)
            t_pts_net = round(sum((t.net_points or 0.0) for t in accepted_trades), 6)

            pts_gross_diff = round(abs(t_pts_gross - self.realized_gross_points), 6)
            pts_slip_diff = round(abs(t_pts_slip - self.total_slippage_points), 6)
            pts_trade_net_diff = round(abs(t_pts_net - self.realized_net_points), 6)

            pts_ok = True
            if pts_net_diff > 1e-4:
                pts_ok = False
                failed.append(f"POINTS_NET_IDENTITY_MISMATCH: diff={pts_net_diff:.6f}")
            if pts_gross_diff > 1e-4:
                pts_ok = False
                failed.append(f"POINTS_TRADE_SUM_GROSS_MISMATCH: diff={pts_gross_diff:.6f}")
            if pts_slip_diff > 1e-4:
                pts_ok = False
                failed.append(f"POINTS_TRADE_SUM_SLIP_MISMATCH: diff={pts_slip_diff:.6f}")
            if pts_trade_net_diff > 1e-4:
                pts_ok = False
                failed.append(f"POINTS_TRADE_SUM_NET_MISMATCH: diff={pts_trade_net_diff:.6f}")
            pts_reconciled = pts_ok

        mon_reconciled: Optional[bool] = None
        cash_diff: Optional[float] = None
        net_diff_inr: Optional[float] = None
        gross_diff_inr: Optional[float] = None
        cost_diff_inr: Optional[float] = None
        trade_net_diff_inr: Optional[float] = None
        res_reserved_inr: Optional[float] = None

        over_exited: List[str] = []
        open_rem = 0
        for tr in accepted_trades:
            exit_fill_qty = sum(f.quantity for f in tr.fills if f.side != OrderSide.ENTRY)
            if exit_fill_qty > tr.initial_quantity or tr.exited_quantity > tr.initial_quantity or tr.remaining_quantity < 0:
                over_exited.append(tr.trade_id)
            if tr.state == TradeLifecycleState.CLOSED:
                if tr.remaining_quantity != 0 or exit_fill_qty != tr.initial_quantity:
                    over_exited.append(tr.trade_id)
                if tr.reserved_capital_inr is not None and abs(tr.reserved_capital_inr) > 1e-4:
                    over_exited.append(tr.trade_id)
            else:
                open_rem += 1

        if self.has_monetary_domain:
            assert (
                self.starting_capital_inr is not None
                and self.available_cash_inr is not None
                and self.reserved_capital_inr is not None
                and self.realized_gross_pnl_inr is not None
                and self.total_costs_inr is not None
                and self.realized_net_pnl_inr is not None
            )
            cash_lhs = round(self.available_cash_inr + self.reserved_capital_inr, 4)
            cash_rhs = round(self.starting_capital_inr + self.realized_gross_pnl_inr - self.total_costs_inr, 4)
            cash_diff = round(abs(cash_lhs - cash_rhs), 6)
            net_diff_inr = round(
                abs((self.realized_gross_pnl_inr - self.total_costs_inr) - self.realized_net_pnl_inr),
                6,
            )
            t_gross = round(sum((t.gross_pnl_inr or 0.0) for t in accepted_trades), 4)
            t_costs = round(sum((t.total_costs_inr or 0.0) for t in accepted_trades), 4)
            t_net = round(sum((t.net_pnl_inr or 0.0) for t in accepted_trades), 4)

            gross_diff_inr = round(abs(t_gross - self.realized_gross_pnl_inr), 6)
            cost_diff_inr = round(abs(t_costs - self.total_costs_inr), 6)
            trade_net_diff_inr = round(abs(t_net - self.realized_net_pnl_inr), 6)
            res_reserved_inr = self.reserved_capital_inr

            mon_ok = True
            if cash_diff > 1e-2:
                mon_ok = False
                failed.append(f"CASH_CONSERVATION_MISMATCH_INR: diff={cash_diff:.6f}")
            if net_diff_inr > 1e-2:
                mon_ok = False
                failed.append(f"NET_PNL_IDENTITY_MISMATCH_INR: diff={net_diff_inr:.6f}")
            if gross_diff_inr > 1e-2:
                mon_ok = False
                failed.append(f"TRADE_SUM_GROSS_MISMATCH_INR: diff={gross_diff_inr:.6f}")
            if cost_diff_inr > 1e-2:
                mon_ok = False
                failed.append(f"TRADE_SUM_COST_MISMATCH_INR: diff={cost_diff_inr:.6f}")
            if trade_net_diff_inr > 1e-2:
                mon_ok = False
                failed.append(f"TRADE_SUM_NET_MISMATCH_INR: diff={trade_net_diff_inr:.6f}")
            if open_rem == 0 and abs(self.reserved_capital_inr) > 1e-2:
                mon_ok = False
                failed.append(f"NON_ZERO_RESIDUAL_RESERVED_CAPITAL_INR:{self.reserved_capital_inr:.4f}")
            mon_reconciled = mon_ok

        over_exited_unique = tuple(dict.fromkeys(over_exited))
        if over_exited_unique:
            failed.append(f"QUANTITY_OR_CLOSE_INVARIANT_FAILED:{','.join(over_exited_unique)}")

        fill_ids = [f.fill_id for f in self.all_fills]
        dup_fills = len(fill_ids) != len(set(fill_ids))
        if dup_fills:
            failed.append("DUPLICATE_FILL_IDS_DETECTED")

        order_ids = [o.order_id for o in self.all_orders]
        dup_orders = len(order_ids) != len(set(order_ids))
        if dup_orders:
            failed.append("DUPLICATE_ORDER_IDS_DETECTED")

        return ReconciliationReport(
            reconciled=len(failed) == 0,
            accounting_unit_mode=self.accounting_unit_mode,
            non_mixing_invariant_passed=non_mixing_ok,
            points_reconciled=pts_reconciled,
            points_net_identity_diff=pts_net_diff,
            points_trade_sum_gross_diff=pts_gross_diff,
            points_trade_sum_slip_diff=pts_slip_diff,
            points_trade_sum_net_diff=pts_trade_net_diff,
            monetary_reconciled=mon_reconciled,
            cash_conservation_diff_inr=cash_diff,
            net_pnl_identity_diff_inr=net_diff_inr,
            trade_sum_gross_diff_inr=gross_diff_inr,
            trade_sum_cost_diff_inr=cost_diff_inr,
            trade_sum_net_diff_inr=trade_net_diff_inr,
            residual_reserved_capital_inr=res_reserved_inr,
            open_trades_remaining=open_rem,
            over_exited_trades=over_exited_unique,
            duplicate_fill_ids_detected=dup_fills,
            duplicate_order_ids_detected=dup_orders,
            failed_checks=tuple(failed),
        )

    def summarize(
        self,
        *,
        total_signals: int,
        trades: Sequence[TradeRecord],
    ) -> PortfolioSummary:
        opened = [
            t
            for t in trades
            if t.state not in (TradeLifecycleState.REJECTED, TradeLifecycleState.CANCELLED, TradeLifecycleState.PENDING)
        ]
        closed = [t for t in opened if t.state == TradeLifecycleState.CLOSED]
        rejected = [t for t in trades if t.state in (TradeLifecycleState.REJECTED, TradeLifecycleState.CANCELLED)]
        partial_exits = sum(
            sum(1 for f in t.fills if f.side == OrderSide.PARTIAL_EXIT)
            for t in opened
        )
        ambiguous_count = sum(t.intrabar_ambiguous_count for t in opened)

        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            winning = [t for t in closed if (t.net_points or 0.0) > 0.0 and t.intrabar_ambiguous_count == 0]
            losing = [t for t in closed if (t.net_points or 0.0) <= 0.0 or t.intrabar_ambiguous_count > 0]
        else:
            winning = [t for t in closed if (t.net_pnl_inr or 0.0) > 0.0 and t.intrabar_ambiguous_count == 0]
            losing = [t for t in closed if (t.net_pnl_inr or 0.0) <= 0.0 or t.intrabar_ambiguous_count > 0]

        end_cum_pts: Optional[float] = None
        if self.has_points_domain:
            assert self.realized_net_points is not None and self.unrealized_points is not None
            end_cum_pts = round(self.realized_net_points + self.unrealized_points, 6)

        ending_eq_inr: Optional[float] = None
        brok_stat_inr: Optional[float] = None
        net_ret_pct: Optional[float] = None
        if self.has_monetary_domain:
            assert (
                self.starting_capital_inr is not None
                and self.available_cash_inr is not None
                and self.reserved_capital_inr is not None
                and self.unrealized_pnl_inr is not None
                and self.total_brokerage_inr is not None
                and self.total_statutory_charges_inr is not None
                and self.realized_net_pnl_inr is not None
            )
            ending_eq_inr = round(self.available_cash_inr + self.reserved_capital_inr + self.unrealized_pnl_inr, 4)
            brok_stat_inr = round(self.total_brokerage_inr + self.total_statutory_charges_inr, 4)
            net_ret_pct = round((self.realized_net_pnl_inr / self.starting_capital_inr) * 100.0, 4)

        return PortfolioSummary(
            mode=self.mode,
            accounting_unit_mode=self.accounting_unit_mode,
            provenance_label=self.provenance_label,
            is_synthetic_modelled=(self.mode == SimulationMode.SYNTHETIC_BS_RESEARCH),
            monetary_accounting_enabled=self.has_monetary_domain,
            instrument_multiplier_inr_per_point=self.instrument_multiplier_inr_per_point,
            instrument_multiplier_documentation=self.instrument_multiplier_documentation,
            points_unit="INDEX_POINTS" if self.has_points_domain else None,
            realized_gross_points=self.realized_gross_points,
            total_slippage_points=self.total_slippage_points,
            realized_net_points=self.realized_net_points,
            unrealized_points=self.unrealized_points,
            ending_cumulative_points=end_cum_pts,
            max_drawdown_points=self.max_drawdown_points,
            currency_unit="INR" if self.has_monetary_domain else None,
            starting_capital_inr=self.starting_capital_inr,
            available_cash_inr=self.available_cash_inr,
            reserved_capital_inr=self.reserved_capital_inr,
            ending_equity_inr=ending_eq_inr,
            realized_gross_pnl_inr=self.realized_gross_pnl_inr,
            unrealized_pnl_inr=self.unrealized_pnl_inr,
            total_brokerage_inr=self.total_brokerage_inr,
            total_statutory_charges_inr=self.total_statutory_charges_inr,
            total_brokerage_and_statutory_inr=brok_stat_inr,
            total_slippage_cost_inr=self.total_slippage_cost_inr,
            total_costs_inr=self.total_costs_inr,
            realized_net_pnl_inr=self.realized_net_pnl_inr,
            net_return_pct=net_ret_pct,
            max_drawdown_inr=self.max_drawdown_inr,
            max_drawdown_pct=self.max_drawdown_pct,
            total_signals=total_signals,
            trades_opened=len(opened),
            trades_closed=len(closed),
            trades_rejected=len(rejected),
            partial_exits_count=partial_exits,
            intrabar_ambiguous_count=ambiguous_count,
            winning_trades=len(winning),
            losing_trades=len(losing),
        )
