"""
AIVOLVE Phase 4 Step 4.3 — Deterministic Position Manager.

Enforces:
- Strict Mode A (`UNDERLYING_POINTS_ONLY`) vs Mode B (`SYNTHETIC_BS_RESEARCH`) separation
- Deterministic position capital reservation & cash sufficiency verification
- Lot-aligned / unit-aligned partial target exit quantity sizing preventing rounding drift
- Overlap constraints & fail-closed signal rejection diagnostics
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.backtesting.configuration import normalize_instrument, normalize_timeframe
from app.backtesting.cost_model import VersionedCostCalculator
from app.backtesting.trade_lifecycle import assert_exit_quantity_valid, validate_trade_transition
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    AmbiguityPolicy,
    CostBreakdown,
    ExitReason,
    FillRecord,
    IntrabarAmbiguityEvidence,
    OrderSide,
    SignalDirection,
    SimulationConfiguration,
    SimulationMode,
    SimulationSignal,
    TradeLifecycleState,
    TradeRecord,
    TriggerPriceDomain,
)


def quantity_unit_label_for_config(config: SimulationConfiguration) -> str:
    um = config.accounting_unit_mode
    if um == AccountingUnitMode.INDEX_POINTS_ONLY:
        return "PARTIAL_EXIT_SLICE_UNITS"
    if um == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
        return "SPECIFIED_INDEX_MULTIPLIER_UNITS"
    return "SYNTHETIC_OPTION_UNITS"


def compute_required_capital_reserve(
    *,
    raw_entry_price: float,
    quantity: int,
    config: SimulationConfiguration,
) -> Optional[float]:
    """
    Computes exact deterministic INR capital reserved upon trade entry:
    - Pure `INDEX_POINTS_ONLY` (`monetary_accounting_enabled=False`): `None` (no currency reserve).
    - Monetary Mode A (`INDEX_POINTS_AND_EXPLICIT_INR`): `entry_price * qty * explicit_inr_mult * margin_fraction`.
    - Mode B (`SYNTHETIC_BS_RESEARCH`): full option premium outlay (`entry_price * qty`, in INR).
    """
    if not config.effective_monetary_accounting_enabled:
        return None
    if config.mode == SimulationMode.SYNTHETIC_BS_RESEARCH:
        return round(float(raw_entry_price) * int(quantity), 4)
    mult = float(config.instrument_multiplier_inr_per_point or 0.0)
    if mult <= 0.0:
        raise ValueError("Explicit instrument_multiplier_inr_per_point > 0 required for INR reserve.")
    margin_frac = float(config.effective_mode_a_margin_fraction or 0.15)
    return round(float(raw_entry_price) * int(quantity) * mult * margin_frac, 4)


def compute_partial_exit_quantity(
    *,
    initial_quantity: int,
    remaining_quantity: int,
    fraction: float,
    signal: SimulationSignal,
) -> int:
    """
    Computes deterministic integer partial-exit quantity:
    - In Mode B (`synthetic_bs_assumptions`), maintains strict lot-size multiples when lots >= 2.
    - Never exceeds `remaining_quantity`; prevents 0-unit or >remaining exits.
    """
    if remaining_quantity <= 0:
        raise ValueError(f"Cannot compute partial exit qty when remaining_quantity={remaining_quantity}.")

    assumptions = signal.synthetic_bs_assumptions
    if assumptions is not None:
        lot_size = int(assumptions.lot_size)
        rem_lots = remaining_quantity // lot_size
        if rem_lots <= 1:
            return remaining_quantity
        init_lots = initial_quantity // lot_size
        split_lots = max(1, min(rem_lots - 1, int(math.floor(init_lots * fraction))))
        return split_lots * lot_size

    if remaining_quantity == 1:
        return 1
    split_units = max(1, min(remaining_quantity - 1, int(math.floor(initial_quantity * fraction))))
    return split_units


def validate_signal_for_mode(
    signal: SimulationSignal,
    *,
    mode: SimulationMode,
    expected_instrument: str,
    expected_timeframe: str,
) -> Optional[str]:
    """Enforces strict mode, provenance, instrument, and timeframe isolation."""
    try:
        sig_inst = normalize_instrument(signal.instrument)
        sig_tf = normalize_timeframe(signal.timeframe)
    except ValueError as exc:
        return f"UNSUPPORTED_INSTRUMENT_OR_TIMEFRAME:{exc}"

    if sig_inst != expected_instrument:
        return f"INSTRUMENT_MISMATCH:signal={sig_inst},simulator={expected_instrument}"
    if sig_tf != expected_timeframe:
        return f"TIMEFRAME_MISMATCH:signal={sig_tf},simulator={expected_timeframe}"

    if mode == SimulationMode.UNDERLYING_POINTS_ONLY:
        if signal.trigger_domain != TriggerPriceDomain.UNDERLYING_POINTS:
            return "MODE_ISOLATION_VIOLATION:SYNTHETIC_OPTION_PREMIUM_FORBIDDEN_IN_MODE_A"
        if signal.synthetic_bs_assumptions is not None:
            return "MODE_ISOLATION_VIOLATION:BS_ASSUMPTIONS_FORBIDDEN_IN_MODE_A"
    else:
        if signal.synthetic_bs_assumptions is None:
            return "MISSING_BS_ASSUMPTIONS:Mode B SYNTHETIC_BS_RESEARCH requires explicit SyntheticBSAssumptions"
        if signal.direction != SignalDirection.LONG:
            return "MODE_ISOLATION_VIOLATION:Mode B supports LONG option buying only"

    return None


@dataclass
class MutableTradePosition:
    """Mutable execution tracker converted into an immutable `TradeRecord` upon output."""

    trade_id: str
    signal: SimulationSignal
    mode: SimulationMode
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    quantity_unit_label: str
    entry_bar_index: int
    entry_time_ist: str
    entry_price: float
    initial_quantity: int
    remaining_quantity: int
    instrument_multiplier_inr_per_point: Optional[float] = None
    instrument_multiplier_documentation: Optional[str] = None
    exited_quantity: int = 0
    state: TradeLifecycleState = TradeLifecycleState.OPEN
    target_1_executed: bool = False
    target_2_executed: bool = False

    # Pure index-points accounting (Mode A only)
    gross_points: Optional[float] = None
    slippage_points: Optional[float] = None
    net_points: Optional[float] = None
    unrealized_points: Optional[float] = None

    # Monetary INR accounting (ONLY when monetary accounting enabled)
    reserved_capital_inr: Optional[float] = None
    gross_pnl_inr: Optional[float] = None
    total_brokerage_and_statutory_inr: Optional[float] = None
    total_slippage_cost_inr: Optional[float] = None
    total_costs_inr: Optional[float] = None
    net_pnl_inr: Optional[float] = None
    unrealized_pnl_inr: Optional[float] = None

    fills: List[FillRecord] = field(default_factory=list)
    ambiguity_events: List[IntrabarAmbiguityEvidence] = field(default_factory=list)
    exit_time_ist: Optional[str] = None
    final_exit_reason: Optional[ExitReason] = None

    def __post_init__(self) -> None:
        if self.accounting_unit_mode in (
            AccountingUnitMode.INDEX_POINTS_ONLY,
            AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        ):
            if self.gross_points is None:
                self.gross_points = 0.0
            if self.slippage_points is None:
                self.slippage_points = 0.0
            if self.net_points is None:
                self.net_points = 0.0
            if self.unrealized_points is None:
                self.unrealized_points = 0.0

        if self.accounting_unit_mode in (
            AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
            AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
        ):
            if self.reserved_capital_inr is None:
                self.reserved_capital_inr = 0.0
            if self.gross_pnl_inr is None:
                self.gross_pnl_inr = 0.0
            if self.total_brokerage_and_statutory_inr is None:
                self.total_brokerage_and_statutory_inr = 0.0
            if self.total_slippage_cost_inr is None:
                self.total_slippage_cost_inr = 0.0
            if self.total_costs_inr is None:
                self.total_costs_inr = 0.0
            if self.net_pnl_inr is None:
                self.net_pnl_inr = 0.0
            if self.unrealized_pnl_inr is None:
                self.unrealized_pnl_inr = 0.0

    def record_entry_fill(self, entry_fill: FillRecord) -> None:
        """Applies entry fill friction cleanly within the active unit domain."""
        if self.fills:
            raise ValueError(f"Entry fill already recorded for trade '{self.trade_id}'.")
        self.fills.append(entry_fill)

        if self.accounting_unit_mode in (
            AccountingUnitMode.INDEX_POINTS_ONLY,
            AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        ):
            assert entry_fill.slippage_points_leg is not None
            self.slippage_points = round(entry_fill.slippage_points_leg, 6)
            self.net_points = round((self.gross_points or 0.0) - self.slippage_points, 6)

        if self.accounting_unit_mode in (
            AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
            AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
        ):
            assert entry_fill.costs.brokerage_and_statutory_inr is not None
            assert entry_fill.costs.slippage_cost_inr is not None
            assert entry_fill.costs.total_costs_inr is not None
            self.total_brokerage_and_statutory_inr = round(entry_fill.costs.brokerage_and_statutory_inr, 4)
            self.total_slippage_cost_inr = round(entry_fill.costs.slippage_cost_inr, 4)
            self.total_costs_inr = round(entry_fill.costs.total_costs_inr, 4)
            self.net_pnl_inr = round((self.gross_pnl_inr or 0.0) - self.total_costs_inr, 4)

    def release_capital_for_exit(self, exit_qty: int) -> Optional[float]:
        """Releases exact proportional reserved INR capital down to zero at final close (None in INDEX_POINTS_ONLY)."""
        if self.reserved_capital_inr is None:
            return None
        if exit_qty >= self.remaining_quantity:
            released = self.reserved_capital_inr
            self.reserved_capital_inr = 0.0
            return round(released, 4)
        ratio = float(exit_qty) / float(self.remaining_quantity)
        released = round(self.reserved_capital_inr * ratio, 4)
        self.reserved_capital_inr = round(max(0.0, self.reserved_capital_inr - released), 4)
        return released

    def apply_exit_fill(
        self,
        *,
        fill: FillRecord,
        exit_qty: int,
        exit_reason: ExitReason,
    ) -> Optional[float]:
        """Updates trade quantities, realized PnL, friction, and lifecycle atomically."""
        new_remaining = assert_exit_quantity_valid(
            trade_id=self.trade_id,
            state=self.state,
            initial_quantity=self.initial_quantity,
            exited_quantity=self.exited_quantity,
            remaining_quantity=self.remaining_quantity,
            exit_qty=exit_qty,
        )
        released_reserve = self.release_capital_for_exit(exit_qty)
        self.exited_quantity += exit_qty
        self.remaining_quantity = new_remaining

        if self.accounting_unit_mode in (
            AccountingUnitMode.INDEX_POINTS_ONLY,
            AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        ):
            assert fill.gross_points_leg is not None and fill.slippage_points_leg is not None
            self.gross_points = round((self.gross_points or 0.0) + fill.gross_points_leg, 6)
            self.slippage_points = round((self.slippage_points or 0.0) + fill.slippage_points_leg, 6)
            self.net_points = round(self.gross_points - self.slippage_points, 6)

        if self.accounting_unit_mode in (
            AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
            AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
        ):
            assert fill.gross_pnl_inr_leg is not None
            assert fill.costs.brokerage_and_statutory_inr is not None
            assert fill.costs.slippage_cost_inr is not None
            assert fill.costs.total_costs_inr is not None
            self.gross_pnl_inr = round((self.gross_pnl_inr or 0.0) + fill.gross_pnl_inr_leg, 4)
            self.total_brokerage_and_statutory_inr = round(
                (self.total_brokerage_and_statutory_inr or 0.0) + fill.costs.brokerage_and_statutory_inr,
                4,
            )
            self.total_slippage_cost_inr = round(
                (self.total_slippage_cost_inr or 0.0) + fill.costs.slippage_cost_inr,
                4,
            )
            self.total_costs_inr = round((self.total_costs_inr or 0.0) + fill.costs.total_costs_inr, 4)
            self.net_pnl_inr = round(self.gross_pnl_inr - self.total_costs_inr, 4)

        self.fills.append(fill)

        if fill.ambiguity_evidence is not None:
            self.ambiguity_events.append(fill.ambiguity_evidence)

        if exit_reason == ExitReason.TARGET_1:
            self.target_1_executed = True
        elif exit_reason == ExitReason.TARGET_2:
            self.target_2_executed = True

        target_state = (
            TradeLifecycleState.CLOSED
            if new_remaining == 0
            else TradeLifecycleState.PARTIALLY_EXITED
        )
        validate_trade_transition(self.state, target_state)
        self.state = target_state

        if new_remaining == 0:
            self.exit_time_ist = fill.executed_at_ist
            self.final_exit_reason = exit_reason
            if self.unrealized_points is not None:
                self.unrealized_points = 0.0
            if self.unrealized_pnl_inr is not None:
                self.unrealized_pnl_inr = 0.0

        return released_reserve

    def update_mark_to_market(
        self,
        *,
        current_price: float,
        inr_multiplier: Optional[float],
    ) -> Tuple[Optional[float], Optional[float]]:
        """Updates mark-to-market separately in points and/or INR without modifying realized values."""
        if self.remaining_quantity <= 0 or self.state == TradeLifecycleState.CLOSED:
            if self.unrealized_points is not None:
                self.unrealized_points = 0.0
            if self.unrealized_pnl_inr is not None:
                self.unrealized_pnl_inr = 0.0
            return self.unrealized_points, self.unrealized_pnl_inr

        delta = (
            float(current_price) - float(self.entry_price)
            if self.signal.direction == SignalDirection.LONG
            else float(self.entry_price) - float(current_price)
        )
        rem_weight = float(self.remaining_quantity) / float(self.initial_quantity)

        if self.accounting_unit_mode in (
            AccountingUnitMode.INDEX_POINTS_ONLY,
            AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        ):
            self.unrealized_points = round(delta * rem_weight, 6)

        if self.accounting_unit_mode in (
            AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
            AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
        ):
            assert inr_multiplier is not None and inr_multiplier > 0.0
            self.unrealized_pnl_inr = round(delta * self.remaining_quantity * float(inr_multiplier), 4)

        return self.unrealized_points, self.unrealized_pnl_inr

    def to_record(self) -> TradeRecord:
        opt_pts = None
        if self.accounting_unit_mode == AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY:
            opt_pts = round((self.gross_pnl_inr or 0.0) / float(self.initial_quantity), 4)
        return TradeRecord(
            trade_id=self.trade_id,
            signal_id=self.signal.signal_id,
            instrument=self.signal.instrument,
            timeframe=self.signal.timeframe,
            mode=self.mode,
            accounting_unit_mode=self.accounting_unit_mode,
            provenance_label=self.provenance_label,
            is_synthetic_modelled=(self.mode == SimulationMode.SYNTHETIC_BS_RESEARCH),
            quantity_unit_label=self.quantity_unit_label,  # type: ignore[arg-type]
            instrument_multiplier_inr_per_point=self.instrument_multiplier_inr_per_point,
            instrument_multiplier_documentation=self.instrument_multiplier_documentation,
            direction=self.signal.direction,
            state=self.state,
            signal_available_at_ist=self.signal.signal_available_at_ist.isoformat(),
            entry_time_ist=self.entry_time_ist,
            exit_time_ist=self.exit_time_ist,
            entry_price=self.entry_price,
            initial_quantity=self.initial_quantity,
            exited_quantity=self.exited_quantity,
            remaining_quantity=self.remaining_quantity,
            stop_loss=self.signal.stop_loss,
            target_1=self.signal.target_1,
            target_2=self.signal.target_2,
            target_1_executed=self.target_1_executed,
            target_2_executed=self.target_2_executed,
            gross_points=self.gross_points,
            slippage_points=self.slippage_points,
            net_points=self.net_points,
            unrealized_points=self.unrealized_points,
            option_premium_points_per_unit=opt_pts,
            reserved_capital_inr=self.reserved_capital_inr,
            gross_pnl_inr=self.gross_pnl_inr,
            total_brokerage_and_statutory_inr=self.total_brokerage_and_statutory_inr,
            total_slippage_cost_inr=self.total_slippage_cost_inr,
            total_costs_inr=self.total_costs_inr,
            net_pnl_inr=self.net_pnl_inr,
            unrealized_pnl_inr=self.unrealized_pnl_inr,
            intrabar_ambiguous_count=len(self.ambiguity_events),
            ambiguity_events=tuple(self.ambiguity_events),
            synthetic_bs_assumptions=self.signal.synthetic_bs_assumptions,
            fills=tuple(self.fills),
            final_exit_reason=self.final_exit_reason,
        )
