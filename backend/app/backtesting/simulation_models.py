"""
AIVOLVE Phase 4 Step 4.3 — Canonical Schemas for Isolated Historical Execution Simulator.

Defines strict, immutable data structures enforcing:
- PAPER_TRADING_ONLY (zero live broker routing)
- Strict separation between UNDERLYING_POINTS_ONLY and SYNTHETIC_BS_RESEARCH
- Explicit provenance labelling (`SYNTHETIC_MODELLED_OPTION_PNL` on synthetic BS)
- Explicit intrabar SL/target ambiguity records and policies
- Order lifecycle, trade lifecycle, fill records, portfolio ledger & reconciliation schemas
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtesting.configuration import EXECUTION_MODE, IST_ZONE


def _ensure_ist_dt(dt: datetime, field_name: str) -> datetime:
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime, got {dt!r}")
    return dt.astimezone(IST_ZONE)


class SimulationMode(str, Enum):
    """Strictly segregated execution simulation modes for Step 4.3."""

    UNDERLYING_POINTS_ONLY = "UNDERLYING_POINTS_ONLY"
    SYNTHETIC_BS_RESEARCH = "SYNTHETIC_BS_RESEARCH"


class AccountingUnitMode(str, Enum):
    """Explicit unit-domain boundary preventing mixing of index points and INR currency."""

    INDEX_POINTS_ONLY = "INDEX_POINTS_ONLY"
    INDEX_POINTS_AND_EXPLICIT_INR = "INDEX_POINTS_AND_EXPLICIT_INR"
    SYNTHETIC_OPTION_INR_ONLY = "SYNTHETIC_OPTION_INR_ONLY"


class SimulationStatus(str, Enum):
    COMPLETED = "COMPLETED"
    LOCKED_OUT = "LOCKED_OUT"
    FAILED_INTEGRITY = "FAILED_INTEGRITY"
    GOVERNANCE_LOCKOUT = "GOVERNANCE_LOCKOUT"
    BLOCKED = "BLOCKED"


class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class TriggerPriceDomain(str, Enum):
    """Explicit domain for entry zones, stop-loss, and target price levels."""

    UNDERLYING_POINTS = "UNDERLYING_POINTS"
    SYNTHETIC_OPTION_PREMIUM = "SYNTHETIC_OPTION_PREMIUM"


class OrderSide(str, Enum):
    ENTRY = "ENTRY"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    EXIT = "EXIT"


class OrderStatus(str, Enum):
    PENDING_NEXT_BAR = "PENDING_NEXT_BAR"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class TradeLifecycleState(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_EXITED = "PARTIALLY_EXITED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TARGET_1 = "TARGET_1"
    TARGET_2 = "TARGET_2"
    INTRABAR_AMBIGUOUS_SL = "INTRABAR_AMBIGUOUS_SL"
    INTRABAR_AMBIGUOUS_WORST_CASE = "INTRABAR_AMBIGUOUS_WORST_CASE"
    GAP_STOP_OUT = "GAP_STOP_OUT"
    GAP_TARGET = "GAP_TARGET"
    EOD_SQUARE_OFF = "EOD_SQUARE_OFF"
    EXPIRY_CLOSE = "EXPIRY_CLOSE"
    END_OF_DATA = "END_OF_DATA"
    SIGNAL_EXPIRY = "SIGNAL_EXPIRY"


class AmbiguityPolicy(str, Enum):
    """Conservative policies applied when SL and Target fall inside a single OHLC bar."""

    CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG = "CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG"
    MARK_AMBIGUOUS_WORST_CASE = "MARK_AMBIGUOUS_WORST_CASE"
    MARK_AMBIGUOUS_NO_FILL = "MARK_AMBIGUOUS_NO_FILL"


class GapPolicy(str, Enum):
    """Explicit handling when next bar or subsequent bar opens gapped past boundaries."""

    ADVERSE_OPEN_FILL = "ADVERSE_OPEN_FILL"
    REJECT_ENTRY_ON_GAP = "REJECT_ENTRY_ON_GAP"


class SyntheticBSAssumptions(BaseModel):
    """
    Mandatory assumptions recorded with every Mode B (`SYNTHETIC_BS_RESEARCH`) trade.
    Strictly labelled SYNTHETIC_MODELLED_OPTION_PNL; never represented as real option quotes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    option_type: Literal["CE", "PE"]
    strike_price: float = Field(..., gt=0.0)
    expiry_datetime_ist: datetime
    implied_volatility: float = Field(..., gt=0.0, le=5.0)
    risk_free_rate: float = Field(..., ge=0.0, le=1.0)
    dividend_yield: float = Field(default=0.0, ge=0.0, le=1.0)
    lot_size: int = Field(..., gt=0)
    lots: int = Field(..., gt=0)
    tick_size: float = Field(default=0.05, gt=0.0)
    pricing_model_version: str = "BLACK_SCHOLES_EURO_1973_V1"
    assumption_source: str = "EXPLICIT_RESEARCH_INPUT"
    provenance_label: Literal["SYNTHETIC_MODELLED_OPTION_PNL"] = "SYNTHETIC_MODELLED_OPTION_PNL"
    disclaimer: str = (
        "Synthetic Black-Scholes modelled premium over underlying OHLCV; NOT historical market option quotes."
    )

    @model_validator(mode="after")
    def _validate_assumptions(self) -> "SyntheticBSAssumptions":
        import math

        _ensure_ist_dt(self.expiry_datetime_ist, "expiry_datetime_ist")
        for fname in ("strike_price", "implied_volatility", "risk_free_rate", "dividend_yield", "tick_size"):
            val = getattr(self, fname)
            if not math.isfinite(val):
                raise ValueError(f"{fname} must be finite, got {val}")
        return self


class SimulationSignal(BaseModel):
    """
    Point-in-time directional signal intent eligible strictly from completed bar close `t_k`.
    Execution begins only on the next completed bar (`t_{k+1}` open) — never same-bar close.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str = Field(..., min_length=1)
    instrument: str = Field(..., min_length=1)
    timeframe: str = Field(..., min_length=1)
    signal_available_at_ist: datetime
    direction: SignalDirection
    trigger_domain: TriggerPriceDomain
    stop_loss: float = Field(..., gt=0.0)
    target_1: float = Field(..., gt=0.0)
    target_2: Optional[float] = Field(default=None, gt=0.0)
    partial_exit_fraction: float = Field(default=0.5, gt=0.0, lt=1.0)
    entry_zone_min: Optional[float] = Field(default=None, gt=0.0)
    entry_zone_max: Optional[float] = Field(default=None, gt=0.0)
    quantity_units: int = Field(..., gt=0)
    max_entry_wait_bars: int = Field(default=1, ge=1, le=50)
    intraday_square_off: bool = True
    synthetic_bs_assumptions: Optional[SyntheticBSAssumptions] = None
    source_report_id: Optional[str] = None
    notes: str = ""

    @model_validator(mode="after")
    def _validate_signal_geometry(self) -> "SimulationSignal":
        import math

        sig_ist = _ensure_ist_dt(self.signal_available_at_ist, "signal_available_at_ist")
        for fname in ("stop_loss", "target_1"):
            if not math.isfinite(getattr(self, fname)):
                raise ValueError(f"{fname} must be finite")
        if self.target_2 is not None and not math.isfinite(self.target_2):
            raise ValueError("target_2 must be finite")
        if self.entry_zone_min is not None and self.entry_zone_max is not None:
            if self.entry_zone_max < self.entry_zone_min:
                raise ValueError("entry_zone_max must be >= entry_zone_min")

        if self.synthetic_bs_assumptions is not None:
            if self.direction != SignalDirection.LONG:
                raise ValueError(
                    "SYNTHETIC_BS_RESEARCH only simulates long option buying (direction must be LONG)."
                )
            exp_ist = self.synthetic_bs_assumptions.expiry_datetime_ist.astimezone(IST_ZONE)
            if exp_ist <= sig_ist:
                raise ValueError("Option expiry_datetime_ist must be strictly after signal_available_at_ist.")
            expected_qty = self.synthetic_bs_assumptions.lot_size * self.synthetic_bs_assumptions.lots
            if self.quantity_units != expected_qty:
                raise ValueError(
                    f"quantity_units ({self.quantity_units}) must equal lot_size * lots ({expected_qty})."
                )

        if self.trigger_domain == TriggerPriceDomain.SYNTHETIC_OPTION_PREMIUM:
            if self.synthetic_bs_assumptions is None:
                raise ValueError(
                    "synthetic_bs_assumptions must be explicitly provided for SYNTHETIC_OPTION_PREMIUM triggers."
                )
            if self.stop_loss >= self.target_1:
                raise ValueError("For long option premium targets, stop_loss must be < target_1.")
            if self.target_2 is not None and self.target_2 <= self.target_1:
                raise ValueError("target_2 must exceed target_1 for long option premium triggers.")
        else:
            is_pe_spot = (
                self.synthetic_bs_assumptions is not None
                and self.synthetic_bs_assumptions.option_type == "PE"
            )
            expect_up = (self.direction == SignalDirection.LONG) and (not is_pe_spot)
            if expect_up:
                if self.stop_loss >= self.target_1:
                    raise ValueError("Signal requires stop_loss < target_1 for upward triggers.")
                if self.target_2 is not None and self.target_2 <= self.target_1:
                    raise ValueError("Signal requires target_2 > target_1 for upward triggers.")
            else:
                if self.stop_loss <= self.target_1:
                    raise ValueError("Signal requires stop_loss > target_1 for downward triggers.")
                if self.target_2 is not None and self.target_2 >= self.target_1:
                    raise ValueError("Signal requires target_2 < target_1 for downward triggers.")
        return self


class CostScheduleVersion(BaseModel):
    """Versioned, timestamped, explicitly domain-tagged cost rates saved with every run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cost_model_version: str
    effective_date_ist: str
    recorded_at_utc: str
    cost_domain: Literal[
        "UNDERLYING_POINTS_ONLY",
        "UNDERLYING_POINTS_WITH_EXPLICIT_INR",
        "SYNTHETIC_OPTION_PREMIUM_RESEARCH",
    ]
    slippage_unit: Literal["INDEX_POINTS", "INR_PER_OPTION_UNIT"]
    monetary_charges_enabled: bool
    instrument_multiplier_inr_per_point: Optional[float] = Field(default=None, gt=0.0)
    instrument_multiplier_documentation: Optional[str] = None
    rate_disclaimer: str
    brokerage_per_order_inr: float = Field(..., ge=0.0)
    stt_sell_rate: float = Field(..., ge=0.0)
    exchange_txn_rate: float = Field(..., ge=0.0)
    gst_rate: float = Field(..., ge=0.0)
    sebi_turnover_rate: float = Field(..., ge=0.0)
    stamp_duty_buy_rate: float = Field(..., ge=0.0)
    slippage_per_unit: float = Field(..., ge=0.0)


class CostBreakdown(BaseModel):
    """
    Exact itemized transaction fees & slippage for one executed leg.
    Strictly segregates `INDEX_POINTS` slippage-only legs from `INR` monetary bills.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cost_model_version: str
    effective_date_ist: str
    cost_domain: Literal[
        "UNDERLYING_POINTS_ONLY",
        "UNDERLYING_POINTS_WITH_EXPLICIT_INR",
        "SYNTHETIC_OPTION_PREMIUM_RESEARCH",
    ]
    cost_unit: Literal["INDEX_POINTS", "INR"]
    slippage_points_leg: Optional[float] = Field(default=None, ge=0.0)
    turnover_inr: Optional[float] = Field(default=None, ge=0.0)
    buy_turnover_inr: Optional[float] = Field(default=None, ge=0.0)
    sell_turnover_inr: Optional[float] = Field(default=None, ge=0.0)
    brokerage_inr: Optional[float] = Field(default=None, ge=0.0)
    stt_inr: Optional[float] = Field(default=None, ge=0.0)
    exchange_txn_charges_inr: Optional[float] = Field(default=None, ge=0.0)
    gst_inr: Optional[float] = Field(default=None, ge=0.0)
    sebi_charges_inr: Optional[float] = Field(default=None, ge=0.0)
    stamp_duty_inr: Optional[float] = Field(default=None, ge=0.0)
    slippage_cost_inr: Optional[float] = Field(default=None, ge=0.0)
    brokerage_and_statutory_inr: Optional[float] = Field(default=None, ge=0.0)
    total_costs_inr: Optional[float] = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _validate_unit_purity(self) -> "CostBreakdown":
        inr_fields = (
            "turnover_inr",
            "buy_turnover_inr",
            "sell_turnover_inr",
            "brokerage_inr",
            "stt_inr",
            "exchange_txn_charges_inr",
            "gst_inr",
            "sebi_charges_inr",
            "stamp_duty_inr",
            "slippage_cost_inr",
            "brokerage_and_statutory_inr",
            "total_costs_inr",
        )
        if self.cost_unit == "INDEX_POINTS":
            if self.slippage_points_leg is None:
                raise ValueError("INDEX_POINTS CostBreakdown must set slippage_points_leg.")
            leaked = [f for f in inr_fields if getattr(self, f) is not None]
            if leaked:
                raise ValueError(
                    f"MODE_MIXING_POINTS_AND_CURRENCY: INR fields forbidden in INDEX_POINTS cost breakdown: {leaked}"
                )
        else:
            missing = [f for f in inr_fields if getattr(self, f) is None]
            if missing:
                raise ValueError(f"INR CostBreakdown missing monetary fields: {missing}")
        return self


class IntrabarAmbiguityEvidence(BaseModel):
    """Full audit evidence captured whenever SL and Target both fall in a bar's [low, high]."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_id: str
    bar_open_ist: str
    bar_close_ist: str
    bar_open: float
    bar_high: float
    bar_low: float
    bar_close: float
    stop_loss_level: float
    target_level: float
    policy_applied: AmbiguityPolicy
    resolved_exit_reason: ExitReason
    resolved_fill_price: float
    resolution_note: str


class OrderRecord(BaseModel):
    """Immutable audit record of every simulated entry or exit order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    trade_id: str
    signal_id: str
    instrument: str
    timeframe: str
    mode: SimulationMode
    provenance_label: str
    side: OrderSide
    direction: SignalDirection
    quantity: int
    status: OrderStatus
    signal_available_at_ist: str
    eligible_from_bar_open_ist: Optional[str] = None
    executed_at_ist: Optional[str] = None
    limit_min: Optional[float] = None
    limit_max: Optional[float] = None
    rejection_reason: Optional[str] = None


class FillRecord(BaseModel):
    """Immutable executed fill leg with strictly segregated points vs INR accounting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fill_id: str
    order_id: str
    trade_id: str
    signal_id: str
    side: OrderSide
    mode: SimulationMode
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    bar_open_ist: str
    bar_close_ist: str
    executed_at_ist: str
    quantity: int = Field(..., gt=0)
    raw_reference_price: float = Field(..., ge=0.0)
    slippage_per_unit: float = Field(..., ge=0.0)
    effective_fill_price: float = Field(..., ge=0.0)
    underlying_spot_at_fill: float = Field(..., gt=0.0)
    gross_points_leg: Optional[float] = None
    slippage_points_leg: Optional[float] = None
    net_points_impact_leg: Optional[float] = None
    gross_pnl_inr_leg: Optional[float] = None
    net_pnl_inr_impact_leg: Optional[float] = None
    costs: CostBreakdown
    exit_reason: Optional[ExitReason] = None
    is_intrabar_ambiguous: bool = False
    ambiguity_evidence: Optional[IntrabarAmbiguityEvidence] = None

    @model_validator(mode="after")
    def _validate_fill_units(self) -> "FillRecord":
        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if (
                self.gross_points_leg is None
                or self.slippage_points_leg is None
                or self.net_points_impact_leg is None
            ):
                raise ValueError("INDEX_POINTS_ONLY FillRecord requires *_points_leg fields.")
            if self.gross_pnl_inr_leg is not None or self.net_pnl_inr_impact_leg is not None:
                raise ValueError("MODE_MIXING_POINTS_AND_CURRENCY: INR leg PnL forbidden in INDEX_POINTS_ONLY.")
            if self.costs.cost_unit != "INDEX_POINTS":
                raise ValueError("MODE_MIXING_POINTS_AND_CURRENCY: Fill cost_unit must be INDEX_POINTS.")
        elif self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if (
                self.gross_points_leg is None
                or self.slippage_points_leg is None
                or self.net_points_impact_leg is None
                or self.gross_pnl_inr_leg is None
                or self.net_pnl_inr_impact_leg is None
            ):
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR FillRecord requires both points and INR legs.")
            if self.costs.cost_unit != "INR":
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR Fill cost_unit must be INR.")
        else:
            if (
                self.gross_points_leg is not None
                or self.slippage_points_leg is not None
                or self.net_points_impact_leg is not None
            ):
                raise ValueError("MODE_MIXING: Underlying index points fields forbidden in SYNTHETIC_OPTION_INR_ONLY.")
            if self.gross_pnl_inr_leg is None or self.net_pnl_inr_impact_leg is None:
                raise ValueError("SYNTHETIC_OPTION_INR_ONLY FillRecord requires *_inr_leg fields.")
            if self.costs.cost_unit != "INR":
                raise ValueError("SYNTHETIC_OPTION_INR_ONLY Fill cost_unit must be INR.")
        return self


class TradeRecord(BaseModel):
    """Complete trade lifecycle summary with strict points vs INR unit segregation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_id: str
    signal_id: str
    instrument: str
    timeframe: str
    mode: SimulationMode
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    quantity_unit_label: Literal[
        "PARTIAL_EXIT_SLICE_UNITS",
        "SPECIFIED_INDEX_MULTIPLIER_UNITS",
        "SYNTHETIC_OPTION_UNITS",
    ]
    instrument_multiplier_inr_per_point: Optional[float] = None
    instrument_multiplier_documentation: Optional[str] = None
    direction: SignalDirection
    state: TradeLifecycleState
    signal_available_at_ist: str
    entry_time_ist: Optional[str] = None
    exit_time_ist: Optional[str] = None
    entry_price: Optional[float] = None
    initial_quantity: int
    exited_quantity: int = 0
    remaining_quantity: int
    stop_loss: float
    target_1: float
    target_2: Optional[float] = None
    target_1_executed: bool = False
    target_2_executed: bool = False

    # Pure index-point performance (Mode A only; None in Mode B)
    gross_points: Optional[float] = None
    slippage_points: Optional[float] = None
    net_points: Optional[float] = None
    unrealized_points: Optional[float] = None

    # Mode B option-premium per-unit change (explicitly NOT underlying index points)
    option_premium_points_per_unit: Optional[float] = None

    # Monetary INR accounting (ONLY when monetary accounting enabled; None in INDEX_POINTS_ONLY)
    reserved_capital_inr: Optional[float] = None
    gross_pnl_inr: Optional[float] = None
    total_brokerage_and_statutory_inr: Optional[float] = None
    total_slippage_cost_inr: Optional[float] = None
    total_costs_inr: Optional[float] = None
    net_pnl_inr: Optional[float] = None
    unrealized_pnl_inr: Optional[float] = None

    intrabar_ambiguous_count: int = 0
    ambiguity_events: Tuple[IntrabarAmbiguityEvidence, ...] = ()
    synthetic_bs_assumptions: Optional[SyntheticBSAssumptions] = None
    fills: Tuple[FillRecord, ...] = ()
    rejection_reason: Optional[str] = None
    final_exit_reason: Optional[ExitReason] = None

    @model_validator(mode="after")
    def _validate_trade_units(self) -> "TradeRecord":
        pts_fields = ("gross_points", "slippage_points", "net_points", "unrealized_points")
        inr_fields = (
            "reserved_capital_inr",
            "gross_pnl_inr",
            "total_brokerage_and_statutory_inr",
            "total_slippage_cost_inr",
            "total_costs_inr",
            "net_pnl_inr",
            "unrealized_pnl_inr",
        )
        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if any(getattr(self, f) is None for f in pts_fields):
                raise ValueError("INDEX_POINTS_ONLY TradeRecord must populate *_points fields.")
            if self.option_premium_points_per_unit is not None:
                raise ValueError("option_premium_points_per_unit forbidden in INDEX_POINTS_ONLY.")
            if any(getattr(self, f) is not None for f in inr_fields):
                raise ValueError("MODE_MIXING_POINTS_AND_CURRENCY: INR fields forbidden on INDEX_POINTS_ONLY trade.")
        elif self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if any(getattr(self, f) is None for f in pts_fields) or any(getattr(self, f) is None for f in inr_fields):
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR TradeRecord requires both points and INR fields.")
            if self.instrument_multiplier_inr_per_point is None or not self.instrument_multiplier_documentation:
                raise ValueError("Explicit multiplier and documentation required on monetary Mode A trade.")
        else:
            if any(getattr(self, f) is not None for f in pts_fields):
                raise ValueError("MODE_MIXING: Index points fields forbidden on SYNTHETIC_OPTION_INR_ONLY trade.")
            if any(getattr(self, f) is None for f in inr_fields):
                raise ValueError("SYNTHETIC_OPTION_INR_ONLY TradeRecord requires all *_inr fields.")
        return self


class EquityCurvePoint(BaseModel):
    """Chronological mark-to-market snapshot strictly segregated by accounting unit mode."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp_ist: str
    accounting_unit_mode: AccountingUnitMode

    # Index-points equity curve (Mode A only)
    realized_gross_points: Optional[float] = None
    total_slippage_points: Optional[float] = None
    realized_net_points: Optional[float] = None
    unrealized_points: Optional[float] = None
    cumulative_equity_points: Optional[float] = None
    drawdown_points: Optional[float] = None

    # Monetary INR equity curve (ONLY when monetary accounting enabled)
    available_cash_inr: Optional[float] = None
    reserved_capital_inr: Optional[float] = None
    realized_gross_pnl_inr: Optional[float] = None
    realized_net_pnl_inr: Optional[float] = None
    unrealized_pnl_inr: Optional[float] = None
    total_costs_inr: Optional[float] = None
    total_equity_inr: Optional[float] = None
    drawdown_inr: Optional[float] = None
    drawdown_pct: Optional[float] = None

    open_trades_count: int

    @model_validator(mode="after")
    def _validate_curve_units(self) -> "EquityCurvePoint":
        pts = (
            "realized_gross_points",
            "total_slippage_points",
            "realized_net_points",
            "unrealized_points",
            "cumulative_equity_points",
            "drawdown_points",
        )
        inr = (
            "available_cash_inr",
            "reserved_capital_inr",
            "realized_gross_pnl_inr",
            "realized_net_pnl_inr",
            "unrealized_pnl_inr",
            "total_costs_inr",
            "total_equity_inr",
            "drawdown_inr",
            "drawdown_pct",
        )
        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if any(getattr(self, f) is None for f in pts):
                raise ValueError("INDEX_POINTS_ONLY EquityCurvePoint requires *_points fields.")
            if any(getattr(self, f) is not None for f in inr):
                raise ValueError("MODE_MIXING_POINTS_AND_CURRENCY: INR equity fields forbidden in INDEX_POINTS_ONLY.")
        elif self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if any(getattr(self, f) is None for f in pts) or any(getattr(self, f) is None for f in inr):
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR EquityCurvePoint requires both points and INR fields.")
        else:
            if any(getattr(self, f) is not None for f in pts):
                raise ValueError("MODE_MIXING: Underlying index points fields forbidden in SYNTHETIC_OPTION_INR_ONLY.")
            if any(getattr(self, f) is None for f in inr):
                raise ValueError("SYNTHETIC_OPTION_INR_ONLY EquityCurvePoint requires all *_inr fields.")
        return self


class ReconciliationReport(BaseModel):
    """Strict double-entry & non-mixing conservation verification report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reconciled: bool
    accounting_unit_mode: AccountingUnitMode
    non_mixing_invariant_passed: bool

    # Points audit (Mode A)
    points_reconciled: Optional[bool] = None
    points_net_identity_diff: Optional[float] = None
    points_trade_sum_gross_diff: Optional[float] = None
    points_trade_sum_slip_diff: Optional[float] = None
    points_trade_sum_net_diff: Optional[float] = None

    # Monetary INR audit (Monetary Mode A & Mode B)
    monetary_reconciled: Optional[bool] = None
    cash_conservation_diff_inr: Optional[float] = None
    net_pnl_identity_diff_inr: Optional[float] = None
    trade_sum_gross_diff_inr: Optional[float] = None
    trade_sum_cost_diff_inr: Optional[float] = None
    trade_sum_net_diff_inr: Optional[float] = None
    residual_reserved_capital_inr: Optional[float] = None

    open_trades_remaining: int
    over_exited_trades: Tuple[str, ...] = ()
    duplicate_fill_ids_detected: bool = False
    duplicate_order_ids_detected: bool = False
    failed_checks: Tuple[str, ...] = ()


class PortfolioSummary(BaseModel):
    """Aggregate accounting summary with explicit separation between INDEX_POINTS and INR."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: SimulationMode
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    monetary_accounting_enabled: bool
    instrument_multiplier_inr_per_point: Optional[float] = None
    instrument_multiplier_documentation: Optional[str] = None

    # Index-Points Performance Section (Mode A only)
    points_unit: Optional[Literal["INDEX_POINTS"]] = None
    realized_gross_points: Optional[float] = None
    total_slippage_points: Optional[float] = None
    realized_net_points: Optional[float] = None
    unrealized_points: Optional[float] = None
    ending_cumulative_points: Optional[float] = None
    max_drawdown_points: Optional[float] = None

    # Monetary Performance Section (ONLY when monetary_accounting_enabled=True)
    currency_unit: Optional[Literal["INR"]] = None
    starting_capital_inr: Optional[float] = None
    available_cash_inr: Optional[float] = None
    reserved_capital_inr: Optional[float] = None
    ending_equity_inr: Optional[float] = None
    realized_gross_pnl_inr: Optional[float] = None
    unrealized_pnl_inr: Optional[float] = None
    total_brokerage_inr: Optional[float] = None
    total_statutory_charges_inr: Optional[float] = None
    total_brokerage_and_statutory_inr: Optional[float] = None
    total_slippage_cost_inr: Optional[float] = None
    total_costs_inr: Optional[float] = None
    realized_net_pnl_inr: Optional[float] = None
    net_return_pct: Optional[float] = None
    max_drawdown_inr: Optional[float] = None
    max_drawdown_pct: Optional[float] = None

    total_signals: int
    trades_opened: int
    trades_closed: int
    trades_rejected: int
    partial_exits_count: int
    intrabar_ambiguous_count: int
    winning_trades: int
    losing_trades: int

    @model_validator(mode="after")
    def _validate_summary_units(self) -> "PortfolioSummary":
        pts = (
            "points_unit",
            "realized_gross_points",
            "total_slippage_points",
            "realized_net_points",
            "unrealized_points",
            "ending_cumulative_points",
            "max_drawdown_points",
        )
        inr = (
            "currency_unit",
            "starting_capital_inr",
            "available_cash_inr",
            "reserved_capital_inr",
            "ending_equity_inr",
            "realized_gross_pnl_inr",
            "unrealized_pnl_inr",
            "total_brokerage_inr",
            "total_statutory_charges_inr",
            "total_brokerage_and_statutory_inr",
            "total_slippage_cost_inr",
            "total_costs_inr",
            "realized_net_pnl_inr",
            "net_return_pct",
            "max_drawdown_inr",
            "max_drawdown_pct",
        )
        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if self.monetary_accounting_enabled:
                raise ValueError("INDEX_POINTS_ONLY must have monetary_accounting_enabled=False.")
            if any(getattr(self, f) is None for f in pts):
                raise ValueError("INDEX_POINTS_ONLY summary requires all points metrics.")
            if any(getattr(self, f) is not None for f in inr):
                raise ValueError("MODE_MIXING_POINTS_AND_CURRENCY: INR metrics forbidden in INDEX_POINTS_ONLY summary.")
        elif self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if not self.monetary_accounting_enabled:
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR must have monetary_accounting_enabled=True.")
            if any(getattr(self, f) is None for f in pts) or any(getattr(self, f) is None for f in inr):
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR summary requires both points and INR sections.")
            if self.instrument_multiplier_inr_per_point is None or not self.instrument_multiplier_documentation:
                raise ValueError("Explicit multiplier & documentation required on monetary Mode A summary.")
        else:
            if not self.monetary_accounting_enabled or not self.is_synthetic_modelled:
                raise ValueError("SYNTHETIC_OPTION_INR_ONLY requires monetary_accounting_enabled & is_synthetic_modelled.")
            if any(getattr(self, f) is not None for f in pts):
                raise ValueError("MODE_MIXING: Underlying index points fields forbidden in Mode B summary.")
            if any(getattr(self, f) is None for f in inr):
                raise ValueError("SYNTHETIC_OPTION_INR_ONLY summary requires all INR fields.")
        return self


class SimulationConfiguration(BaseModel):
    """Versioned immutable configuration governing isolated Step 4.3 execution simulation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    simulator_version: str = "4.3.1"
    execution_mode: str = EXECUTION_MODE
    mode: SimulationMode

    monetary_accounting_enabled: Optional[bool] = None
    starting_capital_inr: Optional[float] = Field(default=None, gt=0.0)
    instrument_multiplier_inr_per_point: Optional[float] = Field(default=None, gt=0.0)
    instrument_multiplier_documentation: Optional[str] = None
    mode_a_margin_fraction: Optional[float] = Field(default=None, gt=0.0, le=1.0)
    max_capital_fraction_per_trade: float = Field(default=0.25, gt=0.0, le=1.0)

    tick_size: float = Field(default=0.05, gt=0.0)
    enforce_tick_rounding: bool = True
    ambiguity_policy: AmbiguityPolicy = AmbiguityPolicy.CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG
    gap_policy: GapPolicy = GapPolicy.ADVERSE_OPEN_FILL
    allow_overlapping_positions: bool = False
    square_off_time_hhmm: str = "15:20"
    require_verified_data_store: bool = True
    sensex_governance_approved: bool = False
    storage_db_path: Optional[str] = None
    governance_ledger_path: Optional[str] = None

    @property
    def effective_monetary_accounting_enabled(self) -> bool:
        if self.mode == SimulationMode.SYNTHETIC_BS_RESEARCH:
            return True
        return bool(self.monetary_accounting_enabled)

    @property
    def accounting_unit_mode(self) -> AccountingUnitMode:
        if self.mode == SimulationMode.SYNTHETIC_BS_RESEARCH:
            return AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY
        if self.effective_monetary_accounting_enabled:
            return AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR
        return AccountingUnitMode.INDEX_POINTS_ONLY

    @property
    def effective_starting_capital_inr(self) -> Optional[float]:
        if not self.effective_monetary_accounting_enabled:
            return None
        if self.starting_capital_inr is not None:
            return float(self.starting_capital_inr)
        return 1_000_000.0

    @property
    def effective_mode_a_margin_fraction(self) -> Optional[float]:
        if self.mode != SimulationMode.UNDERLYING_POINTS_ONLY or not self.effective_monetary_accounting_enabled:
            return None
        return float(self.mode_a_margin_fraction if self.mode_a_margin_fraction is not None else 0.15)

    @model_validator(mode="after")
    def _validate_cfg(self) -> "SimulationConfiguration":
        import math

        if self.execution_mode != EXECUTION_MODE:
            raise ValueError(f"execution_mode must remain '{EXECUTION_MODE}'")
        parts = self.square_off_time_hhmm.strip().split(":")
        if len(parts) != 2 or not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
            raise ValueError(f"Invalid square_off_time_hhmm: {self.square_off_time_hhmm!r}")

        if self.mode == SimulationMode.UNDERLYING_POINTS_ONLY:
            if not bool(self.monetary_accounting_enabled):
                if self.instrument_multiplier_inr_per_point is not None:
                    raise ValueError(
                        "CURRENCY_DISALLOWED_IN_POINTS_ONLY: instrument_multiplier_inr_per_point "
                        "cannot be set unless monetary_accounting_enabled=True."
                    )
                if self.instrument_multiplier_documentation and self.instrument_multiplier_documentation.strip():
                    raise ValueError(
                        "CURRENCY_DISALLOWED_IN_POINTS_ONLY: instrument_multiplier_documentation "
                        "cannot be set unless monetary_accounting_enabled=True."
                    )
                if self.starting_capital_inr is not None:
                    raise ValueError(
                        "CURRENCY_DISALLOWED_IN_POINTS_ONLY: starting_capital_inr must be None in pure "
                        "INDEX_POINTS_ONLY mode (no fake cash balance)."
                    )
                if self.mode_a_margin_fraction is not None:
                    raise ValueError(
                        "CURRENCY_DISALLOWED_IN_POINTS_ONLY: mode_a_margin_fraction requires "
                        "monetary_accounting_enabled=True."
                    )
            else:
                mult = self.instrument_multiplier_inr_per_point
                if mult is None or not math.isfinite(mult) or mult <= 0.0:
                    raise ValueError(
                        "EXPLICIT_MULTIPLIER_REQUIRED: Monetary accounting in UNDERLYING_POINTS_ONLY requires "
                        "an explicit finite instrument_multiplier_inr_per_point > 0."
                    )
                doc = (self.instrument_multiplier_documentation or "").strip()
                if len(doc) < 10:
                    raise ValueError(
                        "MULTIPLIER_DOCUMENTATION_REQUIRED: Monetary accounting in UNDERLYING_POINTS_ONLY requires "
                        "non-empty instrument_multiplier_documentation (>= 10 characters)."
                    )
                cap = self.starting_capital_inr
                if cap is None or not math.isfinite(cap) or cap <= 0.0:
                    raise ValueError(
                        "STARTING_CAPITAL_INR_REQUIRED: Monetary accounting in UNDERLYING_POINTS_ONLY requires "
                        "explicit starting_capital_inr > 0."
                    )
        else:
            if self.monetary_accounting_enabled is False:
                raise ValueError(
                    "SYNTHETIC_BS_RESEARCH always simulates INR modelled option premiums; "
                    "monetary_accounting_enabled cannot be False."
                )
            if self.instrument_multiplier_inr_per_point is not None or self.mode_a_margin_fraction is not None:
                raise ValueError(
                    "MODE_ISOLATION_VIOLATION: Mode A multiplier/margin parameters forbidden in SYNTHETIC_BS_RESEARCH."
                )
        return self


class SimulationRunResult(BaseModel):
    """Top-level deterministic persisted Step 4.3 simulation run artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    output_fingerprint: str
    status: SimulationStatus
    execution_mode: str = EXECUTION_MODE
    mode: SimulationMode
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    instrument: str
    timeframe: str
    historical_date_range: str
    dataset_fingerprint: str
    calendar_fingerprint: str
    replay_run_id: Optional[str] = None
    simulator_version: str
    cost_schedule: CostScheduleVersion
    ambiguity_policy: AmbiguityPolicy
    gap_policy: GapPolicy
    portfolio: PortfolioSummary
    reconciliation: ReconciliationReport
    equity_curve: Tuple[EquityCurvePoint, ...] = ()
    trades: Tuple[TradeRecord, ...] = ()
    orders: Tuple[OrderRecord, ...] = ()
    failure_reasons: Tuple[str, ...] = ()
    created_at_utc: datetime
