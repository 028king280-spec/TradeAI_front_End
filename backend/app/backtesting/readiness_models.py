"""
AIVOLVE Phase 4, Step 4.9 — Final Research Readiness Gate & Market Observation Schemas.

Defines strict PAPER_TRADING_ONLY readiness classifications, bottom-up audit checks,
P0/P1/P2 defect register records, track-separated readiness decisions, and the
controlled 13 November 2026 market observation runbook models.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtesting.revalidation_models import ProtectedHashCheckRecord


READINESS_ENGINE_VERSION: str = "4.9.0"
DEFAULT_OBSERVATION_SESSION_DATE: str = "2026-11-13"
ICT_SCORE_GOVERNANCE_STATUS: str = "UNAVAILABLE / NOT_CALIBRATED"
PAPER_ONLY_DISCLAIMER: str = (
    "PAPER_TRADING_ONLY research readiness audit — NOT live trading authorization. "
    "Live broker order placement and real capital execution remain strictly disabled."
)


def deterministic_readiness_hash(payload: Any) -> str:
    """Computes a canonical SHA-256 hex digest for reproducible Step 4.9 outputs."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ReadinessClassification(str, Enum):
    """Bottom-up Step 4.9 research and paper observation classifications."""

    READY_FOR_HISTORICAL_RESEARCH = "READY_FOR_HISTORICAL_RESEARCH"
    READY_FOR_OFFLINE_REPLAY = "READY_FOR_OFFLINE_REPLAY"
    CONDITIONAL_PAPER_OBSERVATION = "CONDITIONAL_PAPER_OBSERVATION"
    BLOCKED_BY_P0 = "BLOCKED_BY_P0"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    GOVERNANCE_LOCKED = "GOVERNANCE_LOCKED"


class DefectSeverity(str, Enum):
    """Severity classification for Step 4.9 system & data-integrity defects."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class CheckOutcome(str, Enum):
    """Single audit check status."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    BLOCKED = "BLOCKED"
    UNAVAILABLE = "UNAVAILABLE"


class AuditCheckRecord(BaseModel):
    """Individual verifiable check inside a phase readiness audit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: str
    phase: str
    area: str
    outcome: CheckOutcome
    severity_if_failed: Optional[DefectSeverity] = None
    summary: str
    evidence: Tuple[str, ...] = ()
    affects_offline_replay: bool = False
    affects_live_observation: bool = True


class DefectRegisterEntry(BaseModel):
    """Structured defect ledger entry carrying forward concrete code/test evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    defect_id: str
    severity: DefectSeverity
    phase: str
    title: str
    status: Literal["OPEN", "RESOLVED_VERIFIED"] = "OPEN"
    component: str
    file_locations: Tuple[str, ...]
    observed_evidence: str
    blocks_offline_replay: bool = False
    blocks_live_observation: bool = True
    minimal_safe_fix: str
    requires_explicit_authorization: bool = True
    verification_requirement: str


class LiveFeedObservationProbe(BaseModel):
    """
    Observable runtime state snapshot for Phase 1 REST/WebSocket readiness.
    Used both for live introspection and deterministic test injection.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    exchange_open: bool = False
    observation_session_date: str = DEFAULT_OBSERVATION_SESSION_DATE
    session_is_scheduled_trading_day: bool = True
    rest_provider_name: str = "angelone"
    rest_authenticated: bool = False
    websocket_connected: bool = False
    ticks_received: int = 0
    usable_verified_ticks: int = 0
    seconds_since_last_tick: Optional[float] = None
    sequence_gaps_detected: int = 0
    malformed_packets_rejected: int = 0
    stale_ticks_rejected: int = 0
    options_chain_available: bool = False
    live_greeks_available: bool = False
    probe_source: Literal["AUTO_INSPECTED", "INJECTED_SIMULATION"] = "AUTO_INSPECTED"

    @model_validator(mode="after")
    def _validate_counts(self) -> "LiveFeedObservationProbe":
        if self.ticks_received < 0 or self.usable_verified_ticks < 0:
            raise ValueError("Tick counters must be non-negative")
        if self.usable_verified_ticks > self.ticks_received:
            raise ValueError("usable_verified_ticks cannot exceed ticks_received")
        return self


class PhaseAuditResult(BaseModel):
    """Readiness audit result for one AIVOLVE phase (Phase 1, 2, 3, or 4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_name: str
    scope: str
    offline_classification: ReadinessClassification
    live_classification: ReadinessClassification
    checks: Tuple[AuditCheckRecord, ...]
    open_p0_ids: Tuple[str, ...] = ()
    open_p1_ids: Tuple[str, ...] = ()
    open_p2_ids: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()


class InstrumentReadinessDecision(BaseModel):
    """Track-separated readiness verdict per canonical instrument."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str
    historical_replay_classification: ReadinessClassification
    live_observation_classification: ReadinessClassification
    evidence_classification: ReadinessClassification
    verified_timeframes: Tuple[str, ...] = ()
    partial_timeframes: Tuple[str, ...] = ()
    governance_locked: bool = False
    blocking_reasons: Tuple[str, ...] = ()


class ObservationCheckpoint(BaseModel):
    """Time-window step inside the controlled Friday 13 Nov 2026 observation runbook."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_id: str
    ist_window: str
    phase_focus: str
    objective: str
    checks_to_verify: Tuple[str, ...]
    expected_pass_criteria: Tuple[str, ...]
    abort_triggers: Tuple[str, ...]
    logs_to_capture: Tuple[str, ...]


class ControlledFixProtocolRule(BaseModel):
    """Explicit governance step required before modifying frozen Phase 1-3 code."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_number: int
    title: str
    requirement: str


class MarketObservationPlan(BaseModel):
    """Full controlled market observation plan and gate evaluation for a trading session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_session_date: str
    target_weekday: str
    is_scheduled_trading_day: bool
    exchange_open_now: bool
    live_observation_gate_classification: ReadinessClassification
    offline_replay_gate_classification: ReadinessClassification
    preconditions_met: bool
    blocking_reasons: Tuple[str, ...]
    checkpoints: Tuple[ObservationCheckpoint, ...]
    final_observation_pass_criteria: Tuple[str, ...]
    mandatory_abort_triggers: Tuple[str, ...]
    controlled_fix_protocol: Tuple[ControlledFixProtocolRule, ...]


class ResearchReadinessConfig(BaseModel):
    """Immutable Step 4.9 configuration. Rejects any attempt to bypass P0 gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    readiness_version: str = READINESS_ENGINE_VERSION
    execution_mode: Literal["PAPER_TRADING_ONLY"] = "PAPER_TRADING_ONLY"
    observation_session_date: str = DEFAULT_OBSERVATION_SESSION_DATE
    bypass_p0_gates: bool = False
    override_classification: Optional[ReadinessClassification] = None

    @model_validator(mode="after")
    def _forbid_bypass(self) -> "ResearchReadinessConfig":
        if self.bypass_p0_gates:
            raise ValueError("Step 4.9 P0 safety gates cannot be bypassed")
        if self.override_classification is not None:
            raise ValueError(
                "Manual classification override is forbidden; readiness must be derived bottom-up"
            )
        return self


class ResearchReadinessReport(BaseModel):
    """Complete immutable Step 4.9 Final Research Readiness Gate & Observation Report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    readiness_id: str
    report_fingerprint: str
    generated_at_utc: str
    execution_mode: Literal["PAPER_TRADING_ONLY"] = "PAPER_TRADING_ONLY"
    live_trading_authorized: Literal[False] = False
    disclaimer: str = PAPER_ONLY_DISCLAIMER

    # Bottom-up derived classifications (tracks kept strictly separate)
    overall_classification: ReadinessClassification
    offline_historical_replay_classification: ReadinessClassification
    live_market_observation_classification: ReadinessClassification
    strategy_evidence_classification: ReadinessClassification
    ict_score_status: str = ICT_SCORE_GOVERNANCE_STATUS

    # Detailed phase audits & instrument matrix
    phase_audits: Tuple[PhaseAuditResult, ...]
    instrument_decisions: Tuple[InstrumentReadinessDecision, ...]
    defect_register: Tuple[DefectRegisterEntry, ...]
    open_p0_count: int
    open_p1_count: int
    open_p2_count: int

    # Reused Phase 4 Steps 4.6-4.8 anchor facts
    step4_8_review_id: Optional[str] = None
    step4_7_run_count: int = 0
    closed_trade_count_total: int = 0
    verified_matrix_combinations: int = 0
    partial_matrix_combinations: int = 0
    locked_matrix_combinations: int = 0
    missing_options_history_status: str = "OPTION_HISTORY_BLOCKED"

    # Controlled observation runbook & protection checks
    probe_snapshot: LiveFeedObservationProbe
    observation_plan: MarketObservationPlan
    protected_hash_checks: Tuple[ProtectedHashCheckRecord, ...]
    protected_hashes_all_matched: bool
    isolation_verified: bool = True
    ready_conditions_summary: Tuple[str, ...]
    final_recommendation: str

    @model_validator(mode="after")
    def _enforce_bottom_up_invariants(self) -> "ResearchReadinessReport":
        if self.live_trading_authorized is not False:
            raise ValueError("live_trading_authorized must always be False in Step 4.9")
        if self.open_p0_count > 0 and self.live_market_observation_classification in (
            ReadinessClassification.READY_FOR_HISTORICAL_RESEARCH,
            ReadinessClassification.READY_FOR_OFFLINE_REPLAY,
            ReadinessClassification.CONDITIONAL_PAPER_OBSERVATION,
        ):
            raise ValueError(
                "Live market observation cannot be marked READY or CONDITIONAL while open P0 defects exist"
            )
        if not any(
            d.instrument == "SENSEX"
            and d.governance_locked
            and d.live_observation_classification == ReadinessClassification.GOVERNANCE_LOCKED
            for d in self.instrument_decisions
        ):
            raise ValueError("SENSEX must remain GOVERNANCE_LOCKED in instrument_decisions")
        return self

