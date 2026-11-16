"""
AIVOLVE Phase 4 Step 4.3 — Isolated, Versioned, Configurable Indian Derivatives Cost Model.

Strictly separates:
- Mode A (`UNDERLYING_POINTS_ONLY`): research points/unit friction & configurable commission
  labelled `UNDERLYING_POINTS_ONLY` (never uses option statutory STT by default).
- Mode B (`SYNTHETIC_BS_RESEARCH`): configurable Indian option statutory schedule
  (Brokerage, STT, Exchange Txn Charges, GST, SEBI Charges, Stamp Duty, Slippage),
  prominently versioned, timestamped, and tagged as configurable research defaults
  (never asserted as permanent exchange law).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtesting.simulation_models import (
    CostBreakdown,
    CostScheduleVersion,
    OrderSide,
    SignalDirection,
    SimulationMode,
)

COST_MODEL_VERSION = "AIVOLVE-BACKTEST-COSTS-2026.1"
DEFAULT_EFFECTIVE_DATE_IST = "2026-11-11"


class UnderlyingPointsCostConfig(BaseModel):
    """
    Configurable cost schedule for Mode A (`UNDERLYING_POINTS_ONLY`).
    - Default `INDEX_POINTS_ONLY`: only `slippage_per_unit` (measured strictly in `INDEX_POINTS`
      per executed side) is allowed; all INR brokerage/tax rates MUST be 0.0.
    - Opt-in `INDEX_POINTS_AND_EXPLICIT_INR`: INR brokerage/tax rates apply in `INR`
      using the explicitly documented `instrument_multiplier_inr_per_point`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cost_model_version: str = f"{COST_MODEL_VERSION}-POINTS"
    effective_date_ist: str = DEFAULT_EFFECTIVE_DATE_IST
    brokerage_per_order: float = Field(default=0.0, ge=0.0)
    stt_sell_rate: float = Field(default=0.0, ge=0.0, le=0.05)
    exchange_txn_rate: float = Field(default=0.0, ge=0.0, le=0.05)
    gst_rate: float = Field(default=0.0, ge=0.0, le=0.5)
    sebi_turnover_rate: float = Field(default=0.0, ge=0.0, le=0.01)
    stamp_duty_buy_rate: float = Field(default=0.0, ge=0.0, le=0.05)
    slippage_per_unit: float = Field(default=0.5, ge=0.0)
    rate_disclaimer: str = (
        "Index-points slippage schedule (INDEX_POINTS per side); currency charges require explicit documented INR multiplier."
    )

    @model_validator(mode="after")
    def _validate_finite(self) -> "UnderlyingPointsCostConfig":
        for fname in (
            "brokerage_per_order",
            "stt_sell_rate",
            "exchange_txn_rate",
            "gst_rate",
            "sebi_turnover_rate",
            "stamp_duty_buy_rate",
            "slippage_per_unit",
        ):
            if not math.isfinite(getattr(self, fname)):
                raise ValueError(f"{fname} must be finite")
        return self

    def has_currency_charges(self) -> bool:
        return any(
            getattr(self, f) > 0.0
            for f in (
                "brokerage_per_order",
                "stt_sell_rate",
                "exchange_txn_rate",
                "gst_rate",
                "sebi_turnover_rate",
                "stamp_duty_buy_rate",
            )
        )


class SyntheticOptionCostConfig(BaseModel):
    """
    Configurable Indian derivatives cost schedule for Mode B (`SYNTHETIC_BS_RESEARCH`).
    All tax/fee parameters are explicitly versioned, configurable, and timestamped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cost_model_version: str = f"{COST_MODEL_VERSION}-OPTIONS"
    effective_date_ist: str = DEFAULT_EFFECTIVE_DATE_IST
    exchange_segment: Literal["NFO", "BFO"] = "NFO"
    brokerage_per_order: float = Field(default=20.0, ge=0.0)
    stt_sell_rate: float = Field(default=0.001, ge=0.0, le=0.05)
    exchange_txn_rate: float = Field(default=0.0005, ge=0.0, le=0.05)
    gst_rate: float = Field(default=0.18, ge=0.0, le=0.5)
    sebi_turnover_rate: float = Field(default=0.000001, ge=0.0, le=0.01)
    stamp_duty_buy_rate: float = Field(default=0.00003, ge=0.0, le=0.05)
    slippage_per_unit: float = Field(default=0.5, ge=0.0)
    rate_disclaimer: str = (
        "Configurable research Indian options fee schedule (INR); verify against current exchange circulars."
    )

    @model_validator(mode="after")
    def _validate_finite(self) -> "SyntheticOptionCostConfig":
        for fname in (
            "brokerage_per_order",
            "stt_sell_rate",
            "exchange_txn_rate",
            "gst_rate",
            "sebi_turnover_rate",
            "stamp_duty_buy_rate",
            "slippage_per_unit",
        ):
            if not math.isfinite(getattr(self, fname)):
                raise ValueError(f"{fname} must be finite")
        return self


class VersionedCostCalculator:
    """
    Isolated per-order leg transaction cost calculator preventing double counting
    and strictly blocking accidental mixing of index points and INR currency.
    """

    def __init__(
        self,
        *,
        mode: SimulationMode,
        points_cost_config: Optional[UnderlyingPointsCostConfig] = None,
        option_cost_config: Optional[SyntheticOptionCostConfig] = None,
        monetary_accounting_enabled: Optional[bool] = None,
        instrument_multiplier_inr_per_point: Optional[float] = None,
        instrument_multiplier_documentation: Optional[str] = None,
        recorded_at_utc: Optional[str] = None,
    ) -> None:
        self.mode = mode
        if mode == SimulationMode.UNDERLYING_POINTS_ONLY:
            if option_cost_config is not None:
                raise ValueError(
                    "Mode isolation violation: cannot supply SyntheticOptionCostConfig to UNDERLYING_POINTS_ONLY mode."
                )
            self.points_cfg = points_cost_config or UnderlyingPointsCostConfig()
            self.option_cfg = None
            self.monetary_accounting_enabled = bool(monetary_accounting_enabled)

            if not self.monetary_accounting_enabled:
                if instrument_multiplier_inr_per_point is not None:
                    raise ValueError(
                        "MODE_MIXING_POINTS_AND_CURRENCY: Cannot supply instrument_multiplier_inr_per_point "
                        "while monetary_accounting_enabled=False."
                    )
                if self.points_cfg.has_currency_charges():
                    raise ValueError(
                        "MODE_MIXING_POINTS_AND_CURRENCY: Cannot configure INR brokerage or statutory tax rates "
                        "in pure INDEX_POINTS_ONLY mode without explicit monetary_accounting_enabled=True and a "
                        "documented instrument_multiplier_inr_per_point."
                    )
                self.inr_multiplier = None
                self.inr_multiplier_doc = None
            else:
                if (
                    instrument_multiplier_inr_per_point is None
                    or not math.isfinite(instrument_multiplier_inr_per_point)
                    or instrument_multiplier_inr_per_point <= 0.0
                ):
                    raise ValueError(
                        "EXPLICIT_MULTIPLIER_REQUIRED: Monetary accounting in UNDERLYING_POINTS_ONLY requires "
                        "instrument_multiplier_inr_per_point > 0."
                    )
                doc = (instrument_multiplier_documentation or "").strip()
                if len(doc) < 10:
                    raise ValueError(
                        "MULTIPLIER_DOCUMENTATION_REQUIRED: Monetary accounting requires non-empty "
                        "instrument_multiplier_documentation (>= 10 characters)."
                    )
                self.inr_multiplier = float(instrument_multiplier_inr_per_point)
                self.inr_multiplier_doc = doc
        else:
            if points_cost_config is not None:
                raise ValueError(
                    "Mode isolation violation: cannot supply UnderlyingPointsCostConfig to SYNTHETIC_BS_RESEARCH mode."
                )
            if monetary_accounting_enabled is False:
                raise ValueError("SYNTHETIC_BS_RESEARCH always uses INR option-premium monetary accounting.")
            self.points_cfg = None
            self.option_cfg = option_cost_config or SyntheticOptionCostConfig()
            self.monetary_accounting_enabled = True
            # Mode B quotes are already INR per 1 option unit (quantity = lot_size * lots)
            self.inr_multiplier = 1.0
            self.inr_multiplier_doc = "1.0 INR per synthetic BSM option unit (quantity = lot_size * lots)."

        self._recorded_at_utc = recorded_at_utc or datetime.now(timezone.utc).isoformat()

    @property
    def active_cfg(self) -> UnderlyingPointsCostConfig | SyntheticOptionCostConfig:
        assert (self.points_cfg is not None) != (self.option_cfg is not None)
        return self.points_cfg if self.points_cfg is not None else self.option_cfg  # type: ignore[return-value]

    @property
    def cost_domain(
        self,
    ) -> Literal[
        "UNDERLYING_POINTS_ONLY",
        "UNDERLYING_POINTS_WITH_EXPLICIT_INR",
        "SYNTHETIC_OPTION_PREMIUM_RESEARCH",
    ]:
        if self.mode == SimulationMode.SYNTHETIC_BS_RESEARCH:
            return "SYNTHETIC_OPTION_PREMIUM_RESEARCH"
        if self.monetary_accounting_enabled:
            return "UNDERLYING_POINTS_WITH_EXPLICIT_INR"
        return "UNDERLYING_POINTS_ONLY"

    @property
    def cost_unit(self) -> Literal["INDEX_POINTS", "INR"]:
        return "INR" if self.monetary_accounting_enabled else "INDEX_POINTS"

    @property
    def slippage_per_unit(self) -> float:
        return float(self.active_cfg.slippage_per_unit)

    def schedule_version(self) -> CostScheduleVersion:
        cfg = self.active_cfg
        return CostScheduleVersion(
            cost_model_version=cfg.cost_model_version,
            effective_date_ist=cfg.effective_date_ist,
            recorded_at_utc=self._recorded_at_utc,
            cost_domain=self.cost_domain,
            slippage_unit=(
                "INR_PER_OPTION_UNIT"
                if self.mode == SimulationMode.SYNTHETIC_BS_RESEARCH
                else "INDEX_POINTS"
            ),
            monetary_charges_enabled=self.monetary_accounting_enabled,
            instrument_multiplier_inr_per_point=(
                self.inr_multiplier
                if (self.mode == SimulationMode.UNDERLYING_POINTS_ONLY and self.monetary_accounting_enabled)
                else None
            ),
            instrument_multiplier_documentation=(
                self.inr_multiplier_doc
                if (self.mode == SimulationMode.UNDERLYING_POINTS_ONLY and self.monetary_accounting_enabled)
                else None
            ),
            rate_disclaimer=cfg.rate_disclaimer,
            brokerage_per_order_inr=cfg.brokerage_per_order,
            stt_sell_rate=cfg.stt_sell_rate,
            exchange_txn_rate=cfg.exchange_txn_rate,
            gst_rate=cfg.gst_rate,
            sebi_turnover_rate=cfg.sebi_turnover_rate,
            stamp_duty_buy_rate=cfg.stamp_duty_buy_rate,
            slippage_per_unit=cfg.slippage_per_unit,
        )

    @staticmethod
    def is_buy_action(*, direction: SignalDirection, side: OrderSide) -> bool:
        """
        Determines whether a given order leg is a market BUY or SELL:
        - LONG ENTRY -> BUY; LONG PARTIAL_EXIT / EXIT -> SELL
        - SHORT ENTRY -> SELL; SHORT PARTIAL_EXIT / EXIT -> BUY
        """
        if side == OrderSide.ENTRY:
            return direction == SignalDirection.LONG
        return direction == SignalDirection.SHORT

    def calculate_leg_costs(
        self,
        *,
        raw_reference_price: float,
        quantity: int,
        initial_quantity: Optional[int] = None,
        direction: SignalDirection,
        side: OrderSide,
        slippage_applied_per_unit: Optional[float] = None,
    ) -> CostBreakdown:
        """
        Computes exact non-double-counted friction for one leg (`ENTRY`, `PARTIAL_EXIT`, `EXIT`):
        - Pure `INDEX_POINTS_ONLY`: returns ONLY weighted `slippage_points_leg` in `INDEX_POINTS`;
          ALL `*_inr` fields remain strictly `None`.
        - Monetary Mode A / Mode B: returns exact itemized `*_inr` breakdown (and weighted
          `slippage_points_leg` separately in Mode A).
        """
        if quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {quantity}")
        base_qty = int(initial_quantity if initial_quantity is not None else quantity)
        if base_qty <= 0 or quantity > base_qty:
            raise ValueError(f"Invalid quantity/initial_quantity pair: {quantity}/{base_qty}")
        if not math.isfinite(raw_reference_price) or raw_reference_price < 0.0:
            raise ValueError(f"raw_reference_price must be non-negative and finite, got {raw_reference_price}")

        cfg = self.active_cfg
        slip_unit = float(
            cfg.slippage_per_unit if slippage_applied_per_unit is None else slippage_applied_per_unit
        )
        if not math.isfinite(slip_unit) or slip_unit < 0.0:
            raise ValueError(f"slippage must be finite and >= 0, got {slip_unit}")

        weight = float(quantity) / float(base_qty)
        slip_pts_leg = (
            round(slip_unit * weight, 6)
            if self.mode == SimulationMode.UNDERLYING_POINTS_ONLY
            else None
        )

        if not self.monetary_accounting_enabled:
            return CostBreakdown(
                cost_model_version=cfg.cost_model_version,
                effective_date_ist=cfg.effective_date_ist,
                cost_domain=self.cost_domain,
                cost_unit="INDEX_POINTS",
                slippage_points_leg=slip_pts_leg,
            )

        assert self.inr_multiplier is not None and self.inr_multiplier > 0.0
        is_buy = self.is_buy_action(direction=direction, side=side)
        turnover = round(float(raw_reference_price) * int(quantity) * float(self.inr_multiplier), 4)
        buy_turnover = turnover if is_buy else 0.0
        sell_turnover = 0.0 if is_buy else turnover

        brokerage = round(float(cfg.brokerage_per_order), 4)
        stt = round(sell_turnover * float(cfg.stt_sell_rate), 4)
        exchange_charges = round(turnover * float(cfg.exchange_txn_rate), 4)
        gst = round((brokerage + exchange_charges) * float(cfg.gst_rate), 4)
        sebi_charges = round(turnover * float(cfg.sebi_turnover_rate), 4)
        stamp_duty = round(buy_turnover * float(cfg.stamp_duty_buy_rate), 4)

        slippage_cost = round(slip_unit * int(quantity) * float(self.inr_multiplier), 4)
        brokerage_and_statutory = round(
            brokerage + stt + exchange_charges + gst + sebi_charges + stamp_duty,
            4,
        )
        total_costs = round(brokerage_and_statutory + slippage_cost, 4)

        return CostBreakdown(
            cost_model_version=cfg.cost_model_version,
            effective_date_ist=cfg.effective_date_ist,
            cost_domain=self.cost_domain,
            cost_unit="INR",
            slippage_points_leg=slip_pts_leg,
            turnover_inr=turnover,
            buy_turnover_inr=buy_turnover,
            sell_turnover_inr=sell_turnover,
            brokerage_inr=brokerage,
            stt_inr=stt,
            exchange_txn_charges_inr=exchange_charges,
            gst_inr=gst,
            sebi_charges_inr=sebi_charges,
            stamp_duty_inr=stamp_duty,
            slippage_cost_inr=slippage_cost,
            brokerage_and_statutory_inr=brokerage_and_statutory,
            total_costs_inr=total_costs,
        )

