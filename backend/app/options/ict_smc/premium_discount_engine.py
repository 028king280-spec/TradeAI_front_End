"""
AIVOLVE Quantitative Institutional Trading Architecture v3.0
Phase 3 Step 3.5 — Premium / Discount & Inducement Intelligence Engine.

Deterministic, point-in-time calculation and lifecycle management of Dealing Ranges,
Institutional Equilibrium (50%), Premium/Discount Zone boundaries, and Inducement
Intelligence with strict Sweep/Reclaim Pairing and 7-stage linear progression across
Indian equity indices.

Key Invariants:
1. Exact List & String Type Defense:
   - Exact built-in list validation (`type(events) is list`) on public boundaries.
   - Exact built-in string validation (`type(val) is str`) before `.strip()`.
   - Prevents execution of custom subclasses or malicious/throwing overrides.
2. Validated Immutable Snapshots:
   - Stage 1 constructs `ValidatedLiquidityEventSnapshot` and `ValidatedEvidenceSnapshot`.
   - Normalizes rejection wick ratio to an exact built-in finite float.
   - Decouples downstream stages from mutable event or evidence references.
3. Strict 4-Stage Sweep/Reclaim Pairing:
   - Window: t_candidate < t_event <= t_as_of.
   - Cardinality decision ordering: 0 sweeps -> NO_ELIGIBLE_SWEEP_EVENT;
     >1 sweeps or reclaims -> FAIL_CLOSED_AMBIGUOUS_SWEEP_RECLAIM_PAIR;
     1:0 -> UNRECLAIMED_SWEEP; 1:1 -> temporal & trigger candle identity checks.
   - Same-candle reclaim requires rejection wick ratio >= 0.35.
4. Dealing Range Geometry & Lifecycle:
   - Bounded by confirmed structural swings [L_range, H_range] with high > low.
   - Raw spot price precision preserved (prohibition of premature spot quantization).
   - Directional expansion to EXPANDING_TRANSITION on pro-trend close beyond boundary.
   - Opposing close immediately transitions to INVALIDATED.
   - Five states: ACTIVE, EXPANDING_TRANSITION, REPLACED, EXPIRED, INVALIDATED.
5. Inducement Intelligence & 7-Stage Progression:
   - Unified candidate-to-pool identity matching via source_candle_ids / source_swing_ids.
   - Secondary price tolerance validation (0.10 pts).
   - Step 3.1 approved sweep penetration (1.5 pts) & rejection wick (0.35) enforcement.
   - Step 3.2 approved displacement thresholds (body >= 0.50, ATR mult >= 1.0) &
     fail-closed ATR provenance validation (FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE).
   - Strict linear progression: CANDIDATE -> SWEPT -> RECLAIMED -> POI_TOUCH (OPTIONAL)
     -> DISPLACED -> STRUCTURALLY_CONFIRMED -> CONFIRMED.
   - Anti-bypass: CANDIDATE -> CONFIRMED is strictly prohibited.
6. Multi-Timeframe Alignment & Confluence:
   - Temporal alignment validation across approved timeframes without unapproved weights.
   - ICT Confluence Score remains UNAVAILABLE / NOT_CALIBRATED until separately approved.
   - Kept completely isolated from Phase 2 MTF scoring and risk/execution pipelines.
   - Strict PAPER TRADING ONLY.
"""

from __future__ import annotations

import math
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Set, Union

from pydantic import BaseModel, Field, ConfigDict

from app.options.ict_smc.ict_models import (
    ICTEvent,
    ICTEventType,
    EventDirection,
    ICTTimeframe,
    LiquidityType,
    LiquidityLifecycleState,
    LiquidityEvent,
    LiquidityEvidence,
    LiquidityPool,
    SwingPoint,
    MarketStructureEvent,
    MarketStructureEvidence,
    canonicalize_value,
)


# ============================================================================
# 1. SECTION 4.2: SWEEP/RECLAIM PAIRING & SNAPSHOT INFRASTRUCTURE (FROZEN SPEC)
# ============================================================================

@dataclass(frozen=True)
class ValidatedEvidenceSnapshot:
    """
    Immutable value snapshot of Step 3.1 LiquidityEvidence captured and normalized during Stage 1.
    Completely decouples Stage 4 from mutable LiquidityEvidence instances and custom numeric subclasses.
    """
    container_status: str       # "PRESENT", "MISSING", "EXTRACTION_FAILED"
    is_valid_container: bool    # True only if isinstance(container, LiquidityEvidence)
    wick_ratio_status: str     # "VALID_NORMALIZED", "MISSING_OR_NONE", "EXTRACTION_FAILED", "INVALID_VALUE"
    normalized_wick_ratio: Optional[float] = None  # Exact built-in finite float, or None


@dataclass(frozen=True)
class ValidatedLiquidityEventSnapshot:
    """
    Immutable validated snapshot of a native Step 3.1 LiquidityEvent.
    Decouples all downstream pairing logic from the source object.
    """
    event: LiquidityEvent
    pool_id: str
    event_type: ICTEventType
    available_at: datetime
    trigger_candle_id: str
    comparison_instant: datetime
    evidence_snapshot: ValidatedEvidenceSnapshot


# Exhaustive allow-list of the 7 legitimate evidence state combinations
# (container_status, is_valid_container, wick_ratio_status, has_normalized_val)
VALID_EVIDENCE_STATE_COMBINATIONS: Set[Tuple[str, bool, str, bool]] = {
    ("MISSING", False, "MISSING_OR_NONE", False),
    ("EXTRACTION_FAILED", False, "MISSING_OR_NONE", False),
    ("PRESENT", False, "MISSING_OR_NONE", False),
    ("PRESENT", True, "MISSING_OR_NONE", False),
    ("PRESENT", True, "EXTRACTION_FAILED", False),
    ("PRESENT", True, "INVALID_VALUE", False),
    ("PRESENT", True, "VALID_NORMALIZED", True),
}


def is_valid_tz_aware_datetime(dt: Any) -> bool:
    """
    Safely validates timezone-awareness on a datetime object.
    Never allows an exception to escape.
    """
    if not isinstance(dt, datetime):
        return False
    if dt.tzinfo is None:
        return False
    try:
        offset = dt.utcoffset()
        return offset is not None
    except Exception:
        return False


def to_comparison_instant(dt: datetime) -> datetime:
    """
    Resolves a validated timezone-aware datetime to an unambiguous UTC-naive instant
    solely for mathematical comparison. Preserves input object metadata without mutation.
    """
    try:
        offset = dt.utcoffset()
        if offset is None:
            raise ValueError("utcoffset() returned None")
        return dt.replace(tzinfo=None) - offset
    except Exception as exc:
        raise ValueError(f"Instant conversion failed: {exc}") from exc


def capture_and_normalize_evidence(event: Any) -> ValidatedEvidenceSnapshot:
    """
    Safely captures and normalizes evidence state during Stage 1.
    Guarantees that normalized_wick_ratio is strictly an exact built-in finite float.
    Never raises an exception; records extraction and normalization status deterministically.
    """
    # 1. Container extraction
    try:
        evidence = getattr(event, "evidence", None)
    except Exception:
        return ValidatedEvidenceSnapshot(
            container_status="EXTRACTION_FAILED",
            is_valid_container=False,
            wick_ratio_status="MISSING_OR_NONE",
            normalized_wick_ratio=None,
        )

    if evidence is None:
        return ValidatedEvidenceSnapshot(
            container_status="MISSING",
            is_valid_container=False,
            wick_ratio_status="MISSING_OR_NONE",
            normalized_wick_ratio=None,
        )

    if not isinstance(evidence, LiquidityEvidence):
        return ValidatedEvidenceSnapshot(
            container_status="PRESENT",
            is_valid_container=False,
            wick_ratio_status="MISSING_OR_NONE",
            normalized_wick_ratio=None,
        )

    # 2. Raw field extraction
    try:
        raw_ratio = getattr(evidence, "rejection_wick_ratio", None)
    except Exception:
        return ValidatedEvidenceSnapshot(
            container_status="PRESENT",
            is_valid_container=True,
            wick_ratio_status="EXTRACTION_FAILED",
            normalized_wick_ratio=None,
        )

    if raw_ratio is None:
        return ValidatedEvidenceSnapshot(
            container_status="PRESENT",
            is_valid_container=True,
            wick_ratio_status="MISSING_OR_NONE",
            normalized_wick_ratio=None,
        )

    # 3. Numeric normalization
    # 3.1: Reject boolean types upfront (bool subclasses int in Python)
    if isinstance(raw_ratio, bool):
        return ValidatedEvidenceSnapshot(
            container_status="PRESENT",
            is_valid_container=True,
            wick_ratio_status="INVALID_VALUE",
            normalized_wick_ratio=None,
        )

    # 3.2: Type allow-list: int or float only (complex, str, dict fail here)
    if not isinstance(raw_ratio, (int, float)):
        return ValidatedEvidenceSnapshot(
            container_status="PRESENT",
            is_valid_container=True,
            wick_ratio_status="INVALID_VALUE",
            normalized_wick_ratio=None,
        )

    # 3.3: Safe conversion to exact built-in float (handles OverflowError, custom __float__ exceptions)
    try:
        val_float = float(raw_ratio)
    except Exception:
        return ValidatedEvidenceSnapshot(
            container_status="PRESENT",
            is_valid_container=True,
            wick_ratio_status="INVALID_VALUE",
            normalized_wick_ratio=None,
        )

    # Ensure it is strictly the built-in float type, not a custom subclass
    if type(val_float) is not float:
        try:
            val_float = float(val_float)
        except Exception:
            return ValidatedEvidenceSnapshot(
                container_status="PRESENT",
                is_valid_container=True,
                wick_ratio_status="INVALID_VALUE",
                normalized_wick_ratio=None,
            )

    # 3.4: Finite value check (NaN, Inf, -Inf)
    try:
        if math.isnan(val_float) or math.isinf(val_float):
            return ValidatedEvidenceSnapshot(
                container_status="PRESENT",
                is_valid_container=True,
                wick_ratio_status="INVALID_VALUE",
                normalized_wick_ratio=None,
            )
    except Exception:
        return ValidatedEvidenceSnapshot(
            container_status="PRESENT",
            is_valid_container=True,
            wick_ratio_status="INVALID_VALUE",
            normalized_wick_ratio=None,
        )

    return ValidatedEvidenceSnapshot(
        container_status="PRESENT",
        is_valid_container=True,
        wick_ratio_status="VALID_NORMALIZED",
        normalized_wick_ratio=val_float,
    )


def validate_same_candle_rejection_wick(
    evidence_snap: Optional[ValidatedEvidenceSnapshot],
) -> Tuple[bool, str]:
    """
    Evaluates same-candle qualification using the pre-normalized immutable evidence snapshot.
    Zero object access, zero conversion: normalized_wick_ratio is already a built-in finite float.
    """
    if evidence_snap is None:
        return False, "FAIL_CLOSED_SAME_CANDLE_EVIDENCE_UNAVAILABLE"

    # Container-level checks
    if evidence_snap.container_status in ("MISSING", "EXTRACTION_FAILED"):
        return False, "FAIL_CLOSED_SAME_CANDLE_EVIDENCE_UNAVAILABLE"

    if not evidence_snap.is_valid_container:
        return False, "FAIL_CLOSED_INVALID_EVIDENCE_CONTAINER_TYPE"

    # Field-level checks
    if evidence_snap.wick_ratio_status in ("MISSING_OR_NONE", "EXTRACTION_FAILED"):
        return False, "FAIL_CLOSED_SAME_CANDLE_EVIDENCE_UNAVAILABLE"

    if evidence_snap.wick_ratio_status == "INVALID_VALUE":
        return False, "FAIL_CLOSED_INVALID_REJECTION_WICK_VALUE"

    wick_ratio = evidence_snap.normalized_wick_ratio
    if wick_ratio is None:
        return False, "FAIL_CLOSED_SAME_CANDLE_EVIDENCE_UNAVAILABLE"

    # Qualification Check 1: Range bounds [0.0, 1.0]
    if wick_ratio < 0.0 or wick_ratio > 1.0:
        return False, "FAIL_CLOSED_REJECTION_WICK_OUT_OF_BOUNDS"

    # Qualification Check 2: Minimum SMC threshold (0.35)
    if wick_ratio < 0.35:
        return False, "FAIL_CLOSED_INSUFFICIENT_REJECTION_WICK"

    return True, "VALID_SAME_CANDLE_EVIDENCE"


def build_validated_event_snapshots(
    events: List[Any],
) -> Tuple[Optional[List[ValidatedLiquidityEventSnapshot]], Optional[str]]:
    """
    Stage 0 & Stage 1: Enforces exact list container, source boundary, extracts fields safely,
    precomputes comparison instants, normalizes evidence state, and constructs snapshots.
    """
    # Exact list container check (rejects custom list subclasses)
    if type(events) is not list:
        return None, "FAIL_CLOSED_UNSUPPORTED_EVENT_ENVELOPE_FOR_LIQUIDITY_PAIRING"

    snapshots: List[ValidatedLiquidityEventSnapshot] = []

    # STAGE 0: Source boundary enforcement
    for e in events:
        if type(e) is not LiquidityEvent:
            return None, "FAIL_CLOSED_UNSUPPORTED_EVENT_ENVELOPE_FOR_LIQUIDITY_PAIRING"

    # STAGE 1: Field validation & snapshot construction
    for e in events:
        try:
            pool_id = getattr(e, "pool_id", None)
        except Exception:
            return None, "FAIL_CLOSED_MALFORMED_EVENT_MISSING_POOL_ID"

        # Exact str check prevents invoking .strip() on custom subclasses
        if type(pool_id) is not str or not pool_id.strip():
            return None, "FAIL_CLOSED_MALFORMED_EVENT_MISSING_POOL_ID"

        try:
            event_type = getattr(e, "event_type", None)
        except Exception:
            return None, "FAIL_CLOSED_MALFORMED_EVENT_INVALID_EVENT_TYPE"

        if not isinstance(event_type, ICTEventType) or event_type not in (
            ICTEventType.LIQUIDITY_SWEEP,
            ICTEventType.LIQUIDITY_RECLAIM,
        ):
            return None, "FAIL_CLOSED_MALFORMED_EVENT_INVALID_EVENT_TYPE"

        try:
            available_at = getattr(e, "available_at", None)
        except Exception:
            return None, "FAIL_CLOSED_MALFORMED_EVENT_INVALID_AVAILABLE_AT"

        if not is_valid_tz_aware_datetime(available_at):
            return None, "FAIL_CLOSED_MALFORMED_EVENT_INVALID_AVAILABLE_AT"

        try:
            trigger_candle_id = getattr(e, "trigger_candle_id", None)
        except Exception:
            return None, "FAIL_CLOSED_MALFORMED_EVENT_MISSING_TRIGGER_CANDLE"

        # Exact str check prevents invoking .strip() on custom subclasses
        if type(trigger_candle_id) is not str or not trigger_candle_id.strip():
            return None, "FAIL_CLOSED_MALFORMED_EVENT_MISSING_TRIGGER_CANDLE"

        try:
            comparison_instant = to_comparison_instant(available_at)
        except Exception:
            return None, "FAIL_CLOSED_TIMESTAMP_COMPARISON_FAILED"

        # Capture and normalize evidence snapshot (non-failing in Stage 1)
        evidence_snapshot = capture_and_normalize_evidence(e)

        snapshots.append(
            ValidatedLiquidityEventSnapshot(
                event=e,
                pool_id=pool_id,
                event_type=event_type,
                available_at=available_at,
                trigger_candle_id=trigger_candle_id,
                comparison_instant=comparison_instant,
                evidence_snapshot=evidence_snapshot,
            )
        )

    return snapshots, None


def validate_snapshot_integrity(snapshots: Any) -> Optional[str]:
    """
    Validates structural integrity, exact type identity, and provenance of a snapshot collection.
    Completely exception-safe: zero unhandled exceptions can escape.
    """
    try:
        # Enforce exact container type (rejects custom list subclasses)
        if type(snapshots) is not list:
            return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

        for snap in snapshots:
            # 1. Exact snapshot type assertion (rejects arbitrary subclasses)
            if type(snap) is not ValidatedLiquidityEventSnapshot:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            # 2. Exact native event policy (rejects proxies or subclasses)
            src_event = getattr(snap, "event", None)
            if type(src_event) is not LiquidityEvent:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            # 3. Defensive Provenance Extraction & Protected Comparison
            try:
                src_pool_id = getattr(src_event, "pool_id", None)
                src_event_type = getattr(src_event, "event_type", None)
                src_available_at = getattr(src_event, "available_at", None)
                src_trigger_cid = getattr(src_event, "trigger_candle_id", None)
            except Exception:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            # Extract snapshot fields safely
            try:
                snap_pool_id = snap.pool_id
                snap_event_type = snap.event_type
                snap_available_at = snap.available_at
                snap_trigger_cid = snap.trigger_candle_id
                snap_instant = snap.comparison_instant
                ev = snap.evidence_snapshot
            except Exception:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            # Field-to-event consistency checks
            try:
                if snap_pool_id != src_pool_id:
                    return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"
                if snap_event_type != src_event_type:
                    return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"
                if snap_available_at != src_available_at:
                    return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"
                if snap_trigger_cid != src_trigger_cid:
                    return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"
            except Exception:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            # 4. Snapshot Field Value Invariants (Exact str check)
            if type(snap_pool_id) is not str or not snap_pool_id.strip():
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            if type(snap_event_type) is not ICTEventType or snap_event_type not in (
                ICTEventType.LIQUIDITY_SWEEP,
                ICTEventType.LIQUIDITY_RECLAIM,
            ):
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            if not is_valid_tz_aware_datetime(snap_available_at):
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            if type(snap_instant) is not datetime or snap_instant.tzinfo is not None:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            try:
                expected_instant = to_comparison_instant(snap_available_at)
                if snap_instant != expected_instant:
                    return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"
            except Exception:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            # Exact str check
            if type(snap_trigger_cid) is not str or not snap_trigger_cid.strip():
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            # 5. Exact Evidence Snapshot Type Assertion
            if type(ev) is not ValidatedEvidenceSnapshot:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            # Safe extraction of evidence fields
            try:
                c_status = ev.container_status
                is_valid_c = ev.is_valid_container
                w_status = ev.wick_ratio_status
                norm_val = ev.normalized_wick_ratio
            except Exception:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            # Enforce exact built-in primitive types
            if type(c_status) is not str:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"
            if type(is_valid_c) is not bool:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"
            if type(w_status) is not str:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            has_val = norm_val is not None
            state_tuple = (c_status, is_valid_c, w_status, has_val)

            # Must match exactly one of the 7 legitimate combinations
            if state_tuple not in VALID_EVIDENCE_STATE_COMBINATIONS:
                return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

            if w_status == "VALID_NORMALIZED":
                if type(norm_val) is not float or not math.isfinite(norm_val):
                    return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

        return None
    except Exception:
        return "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"


def pair_validated_event_snapshots(
    target_pool_id: str,
    candidate_available_at: datetime,
    as_of_time: datetime,
    snapshots: List[ValidatedLiquidityEventSnapshot],
) -> Tuple[Optional[LiquidityEvent], Optional[LiquidityEvent], str]:
    """
    Internal-only helper executing Stage 2–4 pairing directly on validated snapshots.
    Guarantees strict parameter precedence before snapshot integrity evaluation.
    """
    # 1. Parameter Guard: target_pool_id (Exact str check prevents invoking .strip() on custom subclasses)
    if type(target_pool_id) is not str or not target_pool_id.strip():
        return None, None, "FAIL_CLOSED_INVALID_TARGET_POOL_ID"

    # 2. Parameter Guard: candidate_available_at
    if not is_valid_tz_aware_datetime(candidate_available_at):
        return None, None, "FAIL_CLOSED_INVALID_CANDIDATE_AVAILABLE_AT"

    # 3. Parameter Guard: as_of_time
    if not is_valid_tz_aware_datetime(as_of_time):
        return None, None, "FAIL_CLOSED_INVALID_AS_OF_TIME"

    # 4. Window Guard: t_candidate >= t_as_of fails closed
    try:
        t_candidate = to_comparison_instant(candidate_available_at)
        t_as_of = to_comparison_instant(as_of_time)
        if t_candidate >= t_as_of:
            return None, None, "FAIL_CLOSED_INVALID_TIME_WINDOW"
    except Exception:
        return None, None, "FAIL_CLOSED_TIMESTAMP_COMPARISON_FAILED"

    # 5. Snapshot Collection Integrity Contract
    snap_err = validate_snapshot_integrity(snapshots)
    if snap_err is not None:
        return None, None, snap_err

    # 6. STAGE 2: DETERMINISTIC FILTERING VIA SNAPSHOT FIELDS
    eligible_sweeps: List[ValidatedLiquidityEventSnapshot] = []
    eligible_reclaims: List[ValidatedLiquidityEventSnapshot] = []

    for snap in snapshots:
        # Capture primitive metadata once into locals (prevents stateful accessors)
        snap_pool_id = snap.pool_id
        snap_instant = snap.comparison_instant
        snap_type = snap.event_type

        if snap_pool_id != target_pool_id:
            continue

        if t_candidate < snap_instant <= t_as_of:
            if snap_type == ICTEventType.LIQUIDITY_SWEEP:
                eligible_sweeps.append(snap)
            elif snap_type == ICTEventType.LIQUIDITY_RECLAIM:
                eligible_reclaims.append(snap)

    count_sweeps = len(eligible_sweeps)
    count_reclaims = len(eligible_reclaims)

    # 7. STAGE 3: STRICT CARDINALITY DECISION ORDERING
    if count_sweeps == 0:
        return None, None, "NO_ELIGIBLE_SWEEP_EVENT"

    if count_sweeps > 1 or count_reclaims > 1:
        return None, None, "FAIL_CLOSED_AMBIGUOUS_SWEEP_RECLAIM_PAIR"

    if count_reclaims == 0:
        return eligible_sweeps[0].event, None, "UNRECLAIMED_SWEEP"

    # 8. STAGE 4: STRICT 1:1 TEMPORAL & TRIGGER CANDLE IDENTITY VIA SNAPSHOTS
    sweep_snap = eligible_sweeps[0]
    reclaim_snap = eligible_reclaims[0]

    # Capture comparison instants and trigger candle IDs once into locals
    t_sweep = sweep_snap.comparison_instant
    t_reclaim = reclaim_snap.comparison_instant
    cid_sweep = sweep_snap.trigger_candle_id
    cid_reclaim = reclaim_snap.trigger_candle_id

    # Case 4A: Chronological distinct candles (t_sweep < t_reclaim)
    if t_sweep < t_reclaim:
        if cid_sweep == cid_reclaim:
            return None, None, "FAIL_CLOSED_DIFFERENT_TIMESTAMP_SAME_CANDLE_ID"
        return sweep_snap.event, reclaim_snap.event, "UNIQUE_CHRONOLOGICAL_PAIR_MATCHED"

    # Case 4B: Inverted chronology (causality violation)
    if t_sweep > t_reclaim:
        return None, None, "FAIL_CLOSED_CAUSALITY_VIOLATION"

    # Case 4C: Equal availability timestamp (Same Completed Candle: t_sweep == t_reclaim)
    if cid_sweep != cid_reclaim:
        return None, None, "FAIL_CLOSED_EQUAL_TIMESTAMP_DIFFERENT_CANDLE_ID"

    # Same-candle branch: validate pre-normalized evidence from the snapshot
    is_valid, evidence_code = validate_same_candle_rejection_wick(reclaim_snap.evidence_snapshot)
    if not is_valid:
        return None, None, evidence_code

    return sweep_snap.event, reclaim_snap.event, "UNIQUE_SAME_CANDLE_PAIR_MATCHED"


def pair_sweep_and_reclaim_events(
    target_pool_id: str,
    candidate_available_at: datetime,
    as_of_time: datetime,
    events: List[Any],
) -> Tuple[Optional[LiquidityEvent], Optional[LiquidityEvent], str]:
    """
    Authoritative public entry point enforcing strict validation precedence:
    1. Container Guard: events must strictly be an exact list (type is list).
    2. Parameter Guard: target_pool_id must be exact str (type is str).
    3. Parameter Guard: candidate_available_at must be valid timezone-aware datetime.
    4. Parameter Guard: as_of_time must be valid timezone-aware datetime.
    5. Window Guard: t_candidate < t_as_of (t_candidate >= t_as_of fails closed).
    6. Stage 0 Source Guard: Every item in events must be an exact LiquidityEvent.
    7. Stage 1 Field Validation & Snapshot Construction: build_validated_event_snapshots.
    8. Snapshot Integrity Contract: validate_snapshot_integrity.
    9. Stage 2–4 Pairing Engine: pair_validated_event_snapshots.
    """
    # 1. Container Guard (Exact list type required; rejects custom list subclasses)
    if type(events) is not list:
        return None, None, "FAIL_CLOSED_UNSUPPORTED_EVENT_ENVELOPE_FOR_LIQUIDITY_PAIRING"

    # 2. Parameter Guard: target_pool_id (Exact str check prevents invoking .strip() on custom subclasses)
    if type(target_pool_id) is not str or not target_pool_id.strip():
        return None, None, "FAIL_CLOSED_INVALID_TARGET_POOL_ID"

    # 3. Parameter Guard: candidate_available_at
    if not is_valid_tz_aware_datetime(candidate_available_at):
        return None, None, "FAIL_CLOSED_INVALID_CANDIDATE_AVAILABLE_AT"

    # 4. Parameter Guard: as_of_time
    if not is_valid_tz_aware_datetime(as_of_time):
        return None, None, "FAIL_CLOSED_INVALID_AS_OF_TIME"

    # 5. Window Guard: t_candidate >= t_as_of fails closed
    try:
        t_candidate = to_comparison_instant(candidate_available_at)
        t_as_of = to_comparison_instant(as_of_time)
        if t_candidate >= t_as_of:
            return None, None, "FAIL_CLOSED_INVALID_TIME_WINDOW"
    except Exception:
        return None, None, "FAIL_CLOSED_TIMESTAMP_COMPARISON_FAILED"

    # 6 & 7: Stage 0 Source-Type Validation & Stage 1 Snapshot Construction
    snapshots, err_code = build_validated_event_snapshots(events)
    if err_code is not None:
        return None, None, err_code

    # 8. Snapshot Integrity Validation (Defense-in-depth)
    snap_err = validate_snapshot_integrity(snapshots)
    if snap_err is not None:
        return None, None, snap_err

    # 9. Stage 2, 3, & 4: Snapshot pairing evaluation
    return pair_validated_event_snapshots(
        target_pool_id=target_pool_id,
        candidate_available_at=candidate_available_at,
        as_of_time=as_of_time,
        snapshots=snapshots,
    )


# ============================================================================
# 2. CANONICAL SERIALIZATION & CRYPTOGRAPHIC ID GENERATION
# ============================================================================

def _require_exact_str(value: Any, field_name: str) -> str:
    """Enforces exact built-in str (rejecting subclasses before .strip()) and non-emptiness."""
    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact str, got {type(value).__name__}")
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field_name} cannot be empty or whitespace")
    return clean


def _extract_finite_float_attr(obj: Any, attr_name: str) -> Tuple[Optional[float], str]:
    """
    Safely extracts a finite built-in float from an attribute without allowing
    custom subclass exceptions or booleans to leak.
    Returns: (float_value | None, status) where status in {'OK', 'MISSING', 'INVALID'}
    """
    try:
        raw = getattr(obj, attr_name, None)
    except Exception:
        return None, "MISSING"
    if raw is None:
        return None, "MISSING"
    if isinstance(raw, bool):
        return None, "INVALID"
    try:
        fval = float(raw)
    except Exception:
        return None, "INVALID"
    if type(fval) is not float or not math.isfinite(fval):
        return None, "INVALID"
    return fval, "OK"


def preprocess_canonical_input(obj: Any, path: str = "root") -> Any:
    """
    Deterministically normalizes Step 3.5 domain objects prior to Step 3.4 serialization.
    Strictly bars unvalidated types and prevents fallback string conversion leaks.
    """
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError(f"Non-finite float '{obj}' at '{path}' is not permitted in canonical fingerprint")
        if obj == 0.0:
            return 0.0
        return obj
    if isinstance(obj, Enum):
        val = obj.value
        if type(val) is str:
            return val.strip()
        return preprocess_canonical_input(val, path=f"{path}.value")
    if type(obj) is str:
        return obj.strip()
    if isinstance(obj, datetime):
        if obj.tzinfo is None or obj.tzinfo.utcoffset(obj) is None:
            raise ValueError(f"Naive datetime '{obj}' at '{path}' is forbidden. All timestamps must be timezone-aware.")
        # Normalize to UTC and format with exact microsecond ISO-8601 representation
        utc_dt = obj.astimezone(timezone.utc)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(obj, dict):
        normalized_dict = {}
        seen_keys = set()
        for k, v in obj.items():
            if type(k) is not str:
                raise TypeError(f"Dictionary key '{k}' at '{path}' must be an exact str, got {type(k).__name__}")
            clean_k = k.strip()
            if clean_k in seen_keys:
                raise ValueError(f"Dictionary key collision detected at '{path}': key '{clean_k}' appears multiple times after stripping.")
            seen_keys.add(clean_k)
            normalized_dict[clean_k] = preprocess_canonical_input(v, path=f"{path}.{clean_k}")
        return {k: normalized_dict[k] for k in sorted(normalized_dict.keys())}
    if isinstance(obj, (list, tuple)):
        return [preprocess_canonical_input(item, path=f"{path}[{idx}]") for idx, item in enumerate(obj)]
    if isinstance(obj, BaseModel):
        return preprocess_canonical_input(obj.model_dump(), path=f"{path}.{type(obj).__name__}")

    raise TypeError(
        f"Unsupported type '{type(obj).__name__}' at '{path}' cannot enter canonical fingerprint. "
        f"Supported types: None, bool, int, float, str, Enum, datetime (tz-aware), dict, list, BaseModel."
    )


def compute_step3_5_fingerprint(config: Union[BaseModel, Dict[str, Any]]) -> str:
    """
    Computes a deterministic, collision-resistant 64-hex SHA-256 configuration fingerprint.
    """
    preprocessed = preprocess_canonical_input(config)
    canonical = canonicalize_value(preprocessed)
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest().upper()


def generate_dealing_range_id(
    index: str,
    timeframe: str,
    direction: EventDirection,
    high_price: float,
    low_price: float,
    start_time: datetime,
    high_swing_id: str,
    low_swing_id: str,
    config_fingerprint: str,
) -> str:
    """
    Generates a deterministic Dealing Range ID: RNG-<SHA256>
    """
    payload = {
        "config_fingerprint": _require_exact_str(config_fingerprint, "config_fingerprint"),
        "direction": direction.value if isinstance(direction, Enum) else _require_exact_str(direction, "direction"),
        "high_price": high_price,
        "high_swing_id": _require_exact_str(high_swing_id, "high_swing_id"),
        "index": _require_exact_str(index, "index").upper(),
        "low_price": low_price,
        "low_swing_id": _require_exact_str(low_swing_id, "low_swing_id"),
        "start_time": start_time,
        "timeframe": _require_exact_str(timeframe, "timeframe").lower(),
    }
    preprocessed = preprocess_canonical_input(payload)
    canonical = canonicalize_value(preprocessed)
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest().upper()
    return f"RNG-{digest}"


def compute_transition_id(
    parent_candidate_id: str,
    parent_inducement_event_id: Optional[str],
    from_stage: str,
    to_stage: str,
    source_trigger_event_id: str,
    trigger_candle_id: str,
    index: str,
    timeframe: str,
    configuration_fingerprint: str,
    configuration_version: str,
) -> str:
    """
    Generates a deterministic Inducement Lifecycle Transition ID: TRN-<SHA256>
    """
    norm_parent_idm = (
        _require_exact_str(parent_inducement_event_id, "parent_inducement_event_id")
        if parent_inducement_event_id is not None
        else None
    )
    canonical_payload = {
        "configuration_fingerprint": _require_exact_str(configuration_fingerprint, "configuration_fingerprint"),
        "configuration_version": _require_exact_str(configuration_version, "configuration_version"),
        "from_stage": _require_exact_str(from_stage, "from_stage"),
        "index": _require_exact_str(index, "index").upper(),
        "parent_candidate_id": _require_exact_str(parent_candidate_id, "parent_candidate_id"),
        "parent_inducement_event_id": norm_parent_idm,
        "source_trigger_event_id": _require_exact_str(source_trigger_event_id, "source_trigger_event_id"),
        "timeframe": _require_exact_str(timeframe, "timeframe").lower(),
        "to_stage": _require_exact_str(to_stage, "to_stage"),
        "trigger_candle_id": _require_exact_str(trigger_candle_id, "trigger_candle_id"),
    }
    preprocessed_dict = preprocess_canonical_input(canonical_payload)
    canonical_dict = canonicalize_value(preprocessed_dict)
    canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest().upper()
    return f"TRN-{digest}"


def compute_terminal_inducement_event_id(
    candidate_id: str,
    source_pool_id: str,
    structural_confirmation_event_id: str,
    trigger_candle_id: str,
    index: str,
    timeframe: str,
    configuration_fingerprint: str,
    configuration_version: str,
) -> str:
    """
    Generates a deterministic Terminal Inducement Event ID: EVT-IDM-<SHA256>
    """
    terminal_payload = {
        "candidate_id": _require_exact_str(candidate_id, "candidate_id"),
        "configuration_fingerprint": _require_exact_str(configuration_fingerprint, "configuration_fingerprint"),
        "configuration_version": _require_exact_str(configuration_version, "configuration_version"),
        "event_type": "INDUCEMENT_CONFIRMED",
        "index": _require_exact_str(index, "index").upper(),
        "source_pool_id": _require_exact_str(source_pool_id, "source_pool_id"),
        "structural_confirmation_event_id": _require_exact_str(structural_confirmation_event_id, "structural_confirmation_event_id"),
        "timeframe": _require_exact_str(timeframe, "timeframe").lower(),
        "trigger_candle_id": _require_exact_str(trigger_candle_id, "trigger_candle_id"),
    }
    preprocessed_dict = preprocess_canonical_input(terminal_payload)
    canonical_dict = canonicalize_value(preprocessed_dict)
    canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest().upper()
    return f"EVT-IDM-{digest}"


# ============================================================================
# 3. ENUMS & DATA MODELS
# ============================================================================

class DealingRangeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPANDING_TRANSITION = "EXPANDING_TRANSITION"
    REPLACED = "REPLACED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class ZoneClassification(str, Enum):
    BELOW_RANGE = "BELOW_RANGE"
    DEEP_DISCOUNT = "DEEP_DISCOUNT"
    DISCOUNT = "DISCOUNT"
    EQUILIBRIUM = "EQUILIBRIUM"
    PREMIUM = "PREMIUM"
    DEEP_PREMIUM = "DEEP_PREMIUM"
    ABOVE_RANGE = "ABOVE_RANGE"


class InducementStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    SWEPT = "SWEPT"
    RECLAIMED = "RECLAIMED"
    POI_TOUCH = "POI_TOUCH"
    DISPLACED = "DISPLACED"
    STRUCTURALLY_CONFIRMED = "STRUCTURALLY_CONFIRMED"
    CONFIRMED = "CONFIRMED"
    UNLINKED_CANDIDATE = "UNLINKED_CANDIDATE"
    UNRESOLVED_AMBIGUITY = "UNRESOLVED_AMBIGUITY"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class ATRProvenanceStatus(str, Enum):
    """Explicit upstream ATR provenance states consumed by Step 3.5 displacement validation."""
    CALCULATED = "CALCULATED"
    FALLBACK = "FALLBACK"
    UNAVAILABLE = "UNAVAILABLE"


VALID_CALCULATED_ATR_STATUSES: frozenset[str] = frozenset({
    "CALCULATED",
    "COMPUTED",
    "EMPIRICAL",
    "VERIFIED_CALCULATED",
})

REJECTED_ATR_STATUSES: frozenset[str] = frozenset({
    "FALLBACK",
    "FALLBACK_DEFAULT",
    "UNAVAILABLE",
    "MISSING",
    "UNKNOWN",
    "SYNTHETIC",
    "DEFAULT",
    "HARDCODED",
    "UNVERIFIED",
    "ESTIMATED",
})


class ATRProvenance(BaseModel):
    """Explicit ATR provenance metadata distinguishing calculated ATR from fallback/unavailable."""
    model_config = ConfigDict(frozen=True)

    atr_status: Union[ATRProvenanceStatus, str]
    is_fallback_atr: bool = False
    period: Optional[int] = Field(default=None, gt=0)
    series_length: Optional[int] = Field(default=None, gt=0)
    source: Optional[str] = None


class DealingRangeConfiguration(BaseModel):
    """Configuration for Dealing Range & Equilibrium calculation."""
    model_config = ConfigDict(frozen=True)

    tick_size: float = Field(default=0.05, gt=0.0, description="Minimum exchange tick size")
    neutral_band_pct: float = Field(default=0.0010, ge=0.0, description="Fraction of delta R for neutral band (0.10%)")
    neutral_band_min_ticks: int = Field(default=2, ge=1, description="Minimum ticks for neutral band delta")
    max_lookback_bars: int = Field(default=300, ge=10, description="Maximum bar lifespan before temporal expiry")
    configuration_version: str = Field(default="3.5.0")
    engine_version: str = Field(default="3.5.0")


class DealingRange(BaseModel):
    """Represents an institutional dealing range bounded by confirmed swings."""
    model_config = ConfigDict(frozen=True)

    range_id: str
    index: str
    timeframe: str
    direction: EventDirection
    high_price: float
    low_price: float
    equilibrium_price: float
    delta_r: float
    neutral_band_delta: float
    high_swing_id: str
    low_swing_id: str
    start_time: datetime
    available_at: datetime
    created_at: datetime
    status: DealingRangeStatus = DealingRangeStatus.ACTIVE
    predecessor_range_id: Optional[str] = None
    successor_range_id: Optional[str] = None
    invalidation_reason: Optional[str] = None
    configuration_fingerprint: str


class InducementConfiguration(BaseModel):
    """Configuration for Inducement detection and 7-stage progression."""
    model_config = ConfigDict(frozen=True)

    pool_level_tolerance_pts: float = Field(default=0.10, ge=0.0, description="Secondary price sanity tolerance")
    min_sweep_penetration_pts: float = Field(
        default=1.5,
        ge=0.0,
        description="Step 3.1 approved minimum sweep penetration (sweep_penetration_min_pts=1.5)",
    )
    min_rejection_wick_ratio: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Step 3.1 approved minimum rejection wick ratio (rejection_wick_ratio_min=0.35)",
    )
    min_displacement_body_ratio: float = Field(
        default=0.50,
        ge=0.0,
        le=1.0,
        description="Step 3.2 approved minimum displacement body ratio (mss_min_body_ratio=0.50)",
    )
    min_displacement_atr_multiple: float = Field(
        default=1.0,
        ge=0.0,
        description="Step 3.2 approved minimum displacement ATR multiple (mss_min_atr_multiple=1.0)",
    )
    configuration_version: str = Field(default="3.5.0")
    engine_version: str = Field(default="3.5.0")


class InducementLifecycleTransition(BaseModel):
    """Deterministic record of an inducement advancing from one stage to another."""
    model_config = ConfigDict(frozen=True)

    transition_id: str
    parent_candidate_id: str
    parent_inducement_event_id: Optional[str] = None
    index: str
    timeframe: str
    from_stage: str
    to_stage: str
    source_trigger_event_id: str
    trigger_candle_id: str
    event_time: datetime
    available_at: datetime
    configuration_fingerprint: str
    configuration_version: str
    transition_evidence: Dict[str, Any] = Field(default_factory=dict)


class InducementEvidence(BaseModel):
    """Evidence attached to an InducementEvent."""
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    candidate_price: float
    candidate_swing_type: str
    source_pool_id: Optional[str] = None
    sweep_event_id: Optional[str] = None
    reclaim_event_id: Optional[str] = None
    poi_reference: Optional[Dict[str, Any]] = None
    displacement_event_id: Optional[str] = None
    displacement_body_ratio: Optional[float] = None
    displacement_atr: Optional[float] = None
    displacement_atr_multiple: Optional[float] = None
    structural_break_event_id: Optional[str] = None
    broken_swing_id: Optional[str] = None
    rejection_reasons: List[str] = Field(default_factory=list)


class InducementEvent(BaseModel):
    """Terminal event emitted when an inducement achieves CONFIRMED status."""
    model_config = ConfigDict(frozen=True)

    event_id: str
    index: str
    timeframe: str
    direction: EventDirection
    price_level: float
    status: InducementStatus = InducementStatus.CONFIRMED
    dealing_range_id: str
    trigger_candle_id: str
    event_time: datetime
    available_at: datetime
    created_at: datetime
    evidence: InducementEvidence
    configuration_version: str = "3.5.0"
    engine_version: str = "3.5.0"


class TimeframePremiumDiscountReport(BaseModel):
    """Analysis report for a single timeframe. ICT confluence scoring remains UNAVAILABLE / NOT_CALIBRATED."""
    model_config = ConfigDict(frozen=True)

    index: str
    timeframe: str
    as_of_time: datetime
    active_dealing_range: Optional[DealingRange] = None
    all_ranges: List[DealingRange] = Field(default_factory=list)
    current_price: float
    current_zone: Optional[ZoneClassification] = None
    inducement_candidates: List[SwingPoint] = Field(default_factory=list)
    inducement_transitions: List[InducementLifecycleTransition] = Field(default_factory=list)
    confirmed_inducements: List[InducementEvent] = Field(default_factory=list)
    timeframe_confluence_score: Optional[float] = None
    score_status: str = "UNAVAILABLE"
    calibration_status: str = "NOT_CALIBRATED"
    timeframe_bias: str = "NEUTRAL"
    configuration_fingerprint: str
    engine_version: str = "3.5.0"


class ICTConfluenceReport(BaseModel):
    """Institutional Multi-Timeframe ICT/SMC Confluence Report (score UNAVAILABLE / NOT_CALIBRATED)."""
    model_config = ConfigDict(frozen=True)

    index: str
    as_of_time: datetime
    timeframe_reports: Dict[str, TimeframePremiumDiscountReport]
    timeframe_weights: Dict[str, float] = Field(default_factory=dict)
    composite_confluence_score: Optional[float] = None
    score_status: str = "UNAVAILABLE"
    calibration_status: str = "NOT_CALIBRATED"
    primary_bias: str
    recommended_action: str
    alignment_summary: Dict[str, Any]
    execution_mode: str = "PAPER_TRADING_ONLY"


# ============================================================================
# 4. PURE MATHEMATICAL FUNCTIONS
# ============================================================================

def calculate_equilibrium(
    high: float,
    low: float,
    tick_size: float = 0.05,
    neutral_band_pct: float = 0.0010,
    neutral_band_min_ticks: int = 2,
) -> Tuple[float, float, float]:
    """
    Calculates institutional equilibrium (50%) and neutral band delta.
    Raw spot float precision is preserved (no premature quantization of EQ).
    Returns: (equilibrium_price, delta_r, neutral_band_delta)
    """
    for name, val in (
        ("high", high),
        ("low", low),
        ("tick_size", tick_size),
        ("neutral_band_pct", neutral_band_pct),
    ):
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
            raise ValueError(f"{name} must be a finite numeric value, got {val!r}")
    if isinstance(neutral_band_min_ticks, bool) or not isinstance(neutral_band_min_ticks, int) or neutral_band_min_ticks < 1:
        raise ValueError(f"neutral_band_min_ticks must be an int >= 1, got {neutral_band_min_ticks!r}")
    if tick_size <= 0.0 or neutral_band_pct < 0.0:
        raise ValueError("tick_size must be > 0 and neutral_band_pct must be >= 0")

    if high <= low:
        raise ValueError(f"Invalid range bounds: high ({high}) must be strictly greater than low ({low})")

    delta_r = float(high) - float(low)
    eq = (float(high) + float(low)) / 2.0
    band_delta = max(float(neutral_band_min_ticks) * float(tick_size), delta_r * float(neutral_band_pct))
    return eq, delta_r, band_delta


def classify_zone(
    price: float,
    high: float,
    low: float,
    equilibrium: float,
    delta_r: float,
    neutral_band_delta: float,
) -> ZoneClassification:
    """
    Classifies a spot price relative to the dealing range boundaries and equilibrium.
    Preserves exact floating-point comparisons.
    """
    for name, val in (
        ("price", price),
        ("high", high),
        ("low", low),
        ("equilibrium", equilibrium),
        ("delta_r", delta_r),
        ("neutral_band_delta", neutral_band_delta),
    ):
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
            raise ValueError(f"{name} must be a finite numeric value, got {val!r}")
    if high <= low or delta_r <= 0.0 or neutral_band_delta < 0.0:
        raise ValueError("Invalid range geometry for zone classification")

    if price < low:
        return ZoneClassification.BELOW_RANGE
    if price > high:
        return ZoneClassification.ABOVE_RANGE

    q1 = low + (0.25 * delta_r)
    q3 = low + (0.75 * delta_r)
    eq_lower = equilibrium - neutral_band_delta
    eq_upper = equilibrium + neutral_band_delta

    if price < q1:
        return ZoneClassification.DEEP_DISCOUNT
    if price < eq_lower:
        return ZoneClassification.DISCOUNT
    if price <= eq_upper:
        return ZoneClassification.EQUILIBRIUM
    if price <= q3:
        return ZoneClassification.PREMIUM
    return ZoneClassification.DEEP_PREMIUM


# ============================================================================
# 5. CANDIDATE-TO-POOL MATCHING
# ============================================================================

def match_candidate_to_pools(
    candidate: SwingPoint,
    pools: List[LiquidityPool],
    tolerance_pts: float = 0.10,
) -> Tuple[Optional[LiquidityPool], str]:
    """
    Unified candidate-to-pool identity matching:
    1. Filter pools by matching index and timeframe.
    2. Check source membership: candidate.candle_id in pool.source_candle_ids
       or candidate.event_id in pool.evidence.source_swing_ids.
    3. Deduplicate by unique pool_id and evaluate cardinality:
       - 0 matches: UNLINKED_CANDIDATE
       - > 1 unique pools (or conflicting same-pool definitions): FAIL_CLOSED_UNRESOLVED_AMBIGUITY
       - 1 match: Secondary price tolerance check (|candidate.price - pool.level| <= tolerance_pts)
    """
    if not isinstance(candidate, SwingPoint):
        return None, "FAIL_CLOSED_INVALID_CANDIDATE_OBJECT"
    if type(pools) is not list:
        return None, "FAIL_CLOSED_INVALID_POOLS_CONTAINER"
    if isinstance(tolerance_pts, bool) or not isinstance(tolerance_pts, (int, float)) or not math.isfinite(float(tolerance_pts)) or float(tolerance_pts) < 0.0:
        return None, "FAIL_CLOSED_INVALID_TOLERANCE"

    if (
        type(candidate.index) is not str
        or type(candidate.timeframe) is not str
        or type(candidate.candle_id) is not str
        or type(candidate.event_id) is not str
    ):
        return None, "FAIL_CLOSED_INVALID_CANDIDATE_OBJECT"

    cand_index = candidate.index.upper().strip()
    cand_tf = candidate.timeframe.lower().strip()
    if not cand_index or not cand_tf:
        return None, "FAIL_CLOSED_INVALID_CANDIDATE_OBJECT"

    unique_matches: Dict[str, LiquidityPool] = {}

    for pool in pools:
        if not isinstance(pool, LiquidityPool):
            continue
        if (
            type(pool.pool_id) is not str
            or type(pool.index) is not str
            or type(pool.timeframe) is not str
        ):
            return None, "FAIL_CLOSED_UNRESOLVED_AMBIGUITY"
        pid = pool.pool_id.strip()
        if not pid:
            return None, "FAIL_CLOSED_UNRESOLVED_AMBIGUITY"
        if pool.index.upper().strip() != cand_index or pool.timeframe.lower().strip() != cand_tf:
            continue

        is_candle_member = candidate.candle_id in pool.source_candle_ids
        is_swing_member = False
        if hasattr(pool, "evidence") and pool.evidence and hasattr(pool.evidence, "source_swing_ids"):
            if pool.evidence.source_swing_ids:
                is_swing_member = candidate.event_id in pool.evidence.source_swing_ids

        if is_candle_member or is_swing_member:
            if pid in unique_matches and unique_matches[pid] != pool:
                return None, "FAIL_CLOSED_UNRESOLVED_AMBIGUITY"
            unique_matches[pid] = pool

    count = len(unique_matches)
    if count == 0:
        return None, "UNLINKED_CANDIDATE"
    if count > 1:
        return None, "FAIL_CLOSED_UNRESOLVED_AMBIGUITY"

    matched_pool = next(iter(unique_matches.values()))
    if (
        isinstance(candidate.price, bool)
        or isinstance(matched_pool.level, bool)
        or not isinstance(candidate.price, (int, float))
        or not isinstance(matched_pool.level, (int, float))
        or not math.isfinite(float(candidate.price))
        or not math.isfinite(float(matched_pool.level))
    ):
        return None, "FAIL_CLOSED_INVALID_PRICE"

    price_delta = abs(float(candidate.price) - float(matched_pool.level))
    if price_delta > float(tolerance_pts):
        return None, "REJECTED_PRICE_TOLERANCE_EXCEEDED"

    return matched_pool, "LINKED"


# ============================================================================
# 6. PREMIUM / DISCOUNT INTELLIGENCE ENGINE
# ============================================================================

class PremiumDiscountEngine:
    """
    Phase 3 Step 3.5 Institutional Engine:
    - Dealing Range lifecycle & equilibrium computation.
    - Premium / Discount zone classification.
    - Inducement Intelligence with 7-stage linear progression and strict ATR provenance.
    - Multi-timeframe alignment reporting (confluence scoring remains UNAVAILABLE / NOT_CALIBRATED).
    """

    def __init__(
        self,
        dealing_config: Optional[DealingRangeConfiguration] = None,
        inducement_config: Optional[InducementConfiguration] = None,
    ):
        self.dealing_config = dealing_config or DealingRangeConfiguration()
        self.inducement_config = inducement_config or InducementConfiguration()
        self.dealing_fingerprint = compute_step3_5_fingerprint(self.dealing_config)
        self.inducement_fingerprint = compute_step3_5_fingerprint(self.inducement_config)

    def create_dealing_range(
        self,
        high_swing: SwingPoint,
        low_swing: SwingPoint,
        direction: EventDirection,
        as_of_time: datetime,
        predecessor_range_id: Optional[str] = None,
    ) -> DealingRange:
        """
        Creates a validated dealing range bounded by confirmed structural swings
        without lookahead leakage (max(available_at) <= as_of_time).
        """
        if not isinstance(high_swing, SwingPoint) or not isinstance(low_swing, SwingPoint):
            raise TypeError("high_swing and low_swing must be instances of SwingPoint")
        if direction not in (EventDirection.BULLISH, EventDirection.BEARISH):
            raise ValueError(f"Dealing range direction must be BULLISH or BEARISH, got {direction!r}")
        if not is_valid_tz_aware_datetime(as_of_time):
            raise ValueError("as_of_time must be a valid timezone-aware datetime")

        if high_swing.swing_type != "HIGH" or low_swing.swing_type != "LOW":
            raise ValueError(
                f"Expected high_swing.swing_type == 'HIGH' and low_swing.swing_type == 'LOW', "
                f"got {high_swing.swing_type!r} and {low_swing.swing_type!r}"
            )

        high_idx = _require_exact_str(high_swing.index, "high_swing.index").upper()
        low_idx = _require_exact_str(low_swing.index, "low_swing.index").upper()
        high_tf = _require_exact_str(high_swing.timeframe, "high_swing.timeframe").lower()
        low_tf = _require_exact_str(low_swing.timeframe, "low_swing.timeframe").lower()
        if high_idx != low_idx or high_tf != low_tf:
            raise ValueError(
                f"Dealing range swing dimension mismatch: ({high_idx}, {high_tf}) vs ({low_idx}, {low_tf})"
            )

        for label, sw in (("high_swing", high_swing), ("low_swing", low_swing)):
            if not is_valid_tz_aware_datetime(sw.event_time) or not is_valid_tz_aware_datetime(sw.available_at):
                raise ValueError(f"{label} must have valid timezone-aware event_time and available_at")
            if to_comparison_instant(sw.event_time) > to_comparison_instant(sw.available_at):
                raise ValueError(f"{label} violates event_time <= available_at causality")

        if (
            isinstance(high_swing.price, bool)
            or isinstance(low_swing.price, bool)
            or not math.isfinite(float(high_swing.price))
            or not math.isfinite(float(low_swing.price))
        ):
            raise ValueError("Dealing range swing prices must be finite numeric values")

        if high_swing.price <= low_swing.price:
            raise ValueError(f"high_swing price ({high_swing.price}) must exceed low_swing price ({low_swing.price})")

        # Availability timestamp is the later of the two swing confirmations; enforce no-lookahead
        t_as_of = to_comparison_instant(as_of_time)
        t_high_avail = to_comparison_instant(high_swing.available_at)
        t_low_avail = to_comparison_instant(low_swing.available_at)
        if t_high_avail > t_as_of or t_low_avail > t_as_of:
            raise ValueError("Cannot construct dealing range from future swings with available_at > as_of_time")

        avail_at = high_swing.available_at if t_high_avail >= t_low_avail else low_swing.available_at
        t_high_ev = to_comparison_instant(high_swing.event_time)
        t_low_ev = to_comparison_instant(low_swing.event_time)
        start_t = high_swing.event_time if t_high_ev <= t_low_ev else low_swing.event_time

        eq, delta_r, band_delta = calculate_equilibrium(
            high=high_swing.price,
            low=low_swing.price,
            tick_size=self.dealing_config.tick_size,
            neutral_band_pct=self.dealing_config.neutral_band_pct,
            neutral_band_min_ticks=self.dealing_config.neutral_band_min_ticks,
        )

        range_id = generate_dealing_range_id(
            index=high_swing.index,
            timeframe=high_swing.timeframe,
            direction=direction,
            high_price=high_swing.price,
            low_price=low_swing.price,
            start_time=start_t,
            high_swing_id=high_swing.event_id,
            low_swing_id=low_swing.event_id,
            config_fingerprint=self.dealing_fingerprint,
        )

        return DealingRange(
            range_id=range_id,
            index=high_swing.index,
            timeframe=high_swing.timeframe,
            direction=direction,
            high_price=float(high_swing.price),
            low_price=float(low_swing.price),
            equilibrium_price=eq,
            delta_r=delta_r,
            neutral_band_delta=band_delta,
            high_swing_id=high_swing.event_id,
            low_swing_id=low_swing.event_id,
            start_time=start_t,
            available_at=avail_at,
            created_at=avail_at,
            status=DealingRangeStatus.ACTIVE,
            predecessor_range_id=predecessor_range_id,
            successor_range_id=None,
            invalidation_reason=None,
            configuration_fingerprint=self.dealing_fingerprint,
        )

    def evaluate_dealing_range_lifecycle(
        self,
        current_range: DealingRange,
        candle_close: float,
        candle_high: float,
        candle_low: float,
        as_of_time: datetime,
        bars_since_start: int,
        successor_high: Optional[SwingPoint] = None,
        successor_low: Optional[SwingPoint] = None,
    ) -> DealingRange:
        """
        Evaluates dealing range state transitions based on completed candle price action:
        - ACTIVE -> EXPANDING_TRANSITION (on pro-trend close beyond range bound)
        - ACTIVE -> INVALIDATED (on opposing close beyond opposite bound)
        - ACTIVE -> EXPIRED (on max_lookback_bars reached)
        - EXPANDING_TRANSITION -> REPLACED (when successor range swings confirmed)
        - EXPANDING_TRANSITION -> INVALIDATED (on opposing close)
        - EXPANDING_TRANSITION -> EXPIRED (on max_lookback_bars reached)
        """
        if not isinstance(current_range, DealingRange):
            raise TypeError("current_range must be an instance of DealingRange")
        if not is_valid_tz_aware_datetime(as_of_time) or not is_valid_tz_aware_datetime(current_range.available_at):
            raise ValueError("as_of_time and current_range.available_at must be valid timezone-aware datetimes")
        if to_comparison_instant(as_of_time) < to_comparison_instant(current_range.available_at):
            raise ValueError("Cannot evaluate dealing range lifecycle before range availability timestamp")
        if isinstance(bars_since_start, bool) or not isinstance(bars_since_start, int) or bars_since_start < 0:
            raise ValueError(f"bars_since_start must be a non-negative int, got {bars_since_start!r}")

        for name, val in (("candle_close", candle_close), ("candle_high", candle_high), ("candle_low", candle_low)):
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
                raise ValueError(f"{name} must be a finite numeric value, got {val!r}")
        if float(candle_low) > float(candle_close) or float(candle_close) > float(candle_high):
            raise ValueError("OHLC invariant violated: candle_low <= candle_close <= candle_high required")

        if current_range.status in (
            DealingRangeStatus.REPLACED,
            DealingRangeStatus.EXPIRED,
            DealingRangeStatus.INVALIDATED,
        ):
            return current_range

        # 1. Temporal expiry check
        if bars_since_start >= self.dealing_config.max_lookback_bars:
            return DealingRange(
                **{
                    **current_range.model_dump(),
                    "status": DealingRangeStatus.EXPIRED,
                    "invalidation_reason": "MAX_LOOKBACK_EXCEEDED",
                }
            )

        # 2. Bullish Range Lifecycle
        if current_range.direction == EventDirection.BULLISH:
            # Opposing structural failure: close below Range Low
            if candle_close < current_range.low_price:
                return DealingRange(
                    **{
                        **current_range.model_dump(),
                        "status": DealingRangeStatus.INVALIDATED,
                        "invalidation_reason": "OPPOSING_CLOSE_BELOW_RANGE_LOW",
                    }
                )

            # Pro-trend expansion: close above Range High
            if candle_close > current_range.high_price:
                if current_range.status == DealingRangeStatus.ACTIVE:
                    return DealingRange(
                        **{
                            **current_range.model_dump(),
                            "status": DealingRangeStatus.EXPANDING_TRANSITION,
                        }
                    )

        # 3. Bearish Range Lifecycle
        elif current_range.direction == EventDirection.BEARISH:
            # Opposing structural failure: close above Range High
            if candle_close > current_range.high_price:
                return DealingRange(
                    **{
                        **current_range.model_dump(),
                        "status": DealingRangeStatus.INVALIDATED,
                        "invalidation_reason": "OPPOSING_CLOSE_ABOVE_RANGE_HIGH",
                    }
                )

            # Pro-trend expansion: close below Range Low
            if candle_close < current_range.low_price:
                if current_range.status == DealingRangeStatus.ACTIVE:
                    return DealingRange(
                        **{
                            **current_range.model_dump(),
                            "status": DealingRangeStatus.EXPANDING_TRANSITION,
                        }
                    )

        # 4. Replacement by confirmed successor range
        if current_range.status == DealingRangeStatus.EXPANDING_TRANSITION:
            if successor_high is not None and successor_low is not None:
                succ_range = self.create_dealing_range(
                    high_swing=successor_high,
                    low_swing=successor_low,
                    direction=current_range.direction,
                    as_of_time=as_of_time,
                    predecessor_range_id=current_range.range_id,
                )
                if succ_range.range_id == current_range.range_id:
                    raise ValueError("Successor dealing range cannot be identical to current range")
                return DealingRange(
                    **{
                        **current_range.model_dump(),
                        "status": DealingRangeStatus.REPLACED,
                        "successor_range_id": succ_range.range_id,
                    }
                )

        return current_range

    @staticmethod
    def _extract_structure_candle_id(sev: Any, ev_data: Any) -> Optional[str]:
        """
        Extracts the canonical structural candle identifier from a Step 3.2 event without
        falling back to unrelated reclaim candle IDs.
        """
        try:
            bcid = getattr(ev_data, "break_candle_id", None)
        except Exception:
            bcid = None
        if type(bcid) is str and bcid.strip():
            return bcid.strip()
        try:
            sci = getattr(sev, "source_candle_identifiers", None)
        except Exception:
            sci = None
        if type(sci) is list and len(sci) > 0 and type(sci[0]) is str and sci[0].strip():
            return sci[0].strip()
        return None

    @staticmethod
    def _derive_timeframe_bias(
        active_range: Optional[DealingRange],
        current_zone: Optional[ZoneClassification],
    ) -> str:
        """Derives directional structural/zone observation without unapproved numeric scores."""
        if active_range is None or current_zone is None:
            return "NEUTRAL"
        if active_range.direction == EventDirection.BULLISH and current_zone in (
            ZoneClassification.DISCOUNT,
            ZoneClassification.DEEP_DISCOUNT,
        ):
            return "BULLISH"
        if active_range.direction == EventDirection.BEARISH and current_zone in (
            ZoneClassification.PREMIUM,
            ZoneClassification.DEEP_PREMIUM,
        ):
            return "BEARISH"
        return "NEUTRAL"

    _MISSING_ATTR = object()

    @staticmethod
    def _safe_getattr(obj: Any, attr_name: str) -> Tuple[bool, Any]:
        """Safely reads an attribute without letting custom descriptors raise uncaught faults."""
        try:
            return True, getattr(obj, attr_name, PremiumDiscountEngine._MISSING_ATTR)
        except Exception:
            return False, None

    @staticmethod
    def _normalize_provenance_status(raw: Any) -> Tuple[Optional[str], bool]:
        """
        Normalizes explicit ATR status tokens using exact built-in string checks.
        Returns (normalized_token_or_None, is_malformed).
        """
        if raw is None or raw is PremiumDiscountEngine._MISSING_ATTR:
            return None, False
        if isinstance(raw, ATRProvenanceStatus):
            enum_val = raw.value
            if type(enum_val) is not str:
                return None, True
            clean = enum_val.strip().upper()
            return (clean, False) if clean else (None, True)
        if type(raw) is str:
            clean = raw.strip().upper()
            return (clean, False) if clean else (None, True)
        return None, True

    @classmethod
    def _parse_atr_provenance_record(
        cls,
        record: Any,
    ) -> Tuple[List[str], List[bool], bool]:
        """
        Extracts status tokens and fallback flags from an explicit provenance record
        (ATRProvenance, ATRProvenanceStatus, exact str, or dict).
        """
        tokens: List[str] = []
        fallback_flags: List[bool] = []

        if record is None or record is cls._MISSING_ATTR:
            return tokens, fallback_flags, False

        if isinstance(record, ATRProvenanceStatus) or type(record) is str:
            tok, malformed = cls._normalize_provenance_status(record)
            if malformed or tok is None:
                return [], [], True
            tokens.append(tok)
            return tokens, fallback_flags, False

        if isinstance(record, str):
            # Reject custom str subclasses without calling .strip()
            return [], [], True

        if isinstance(record, ATRProvenance):
            tok, malformed = cls._normalize_provenance_status(record.atr_status)
            if malformed or tok is None:
                return [], [], True
            if type(record.is_fallback_atr) is not bool:
                return [], [], True
            if record.period is not None and (type(record.period) is not int or record.period <= 0):
                return [], [], True
            if record.series_length is not None and (type(record.series_length) is not int or record.series_length <= 0):
                return [], [], True
            tokens.append(tok)
            fallback_flags.append(record.is_fallback_atr)
            return tokens, fallback_flags, False

        if type(record) is dict:
            if not record:
                return [], [], True
            status_candidates: List[str] = []
            for key in ("atr_status", "status", "provenance"):
                if key in record and record[key] is not None:
                    tok, malformed = cls._normalize_provenance_status(record[key])
                    if malformed or tok is None:
                        return [], [], True
                    status_candidates.append(tok)
            if len(set(status_candidates)) > 1:
                return [], [], True
            tokens.extend(status_candidates)

            if "is_fallback_atr" in record and record["is_fallback_atr"] is not None:
                fb_val = record["is_fallback_atr"]
                if type(fb_val) is not bool:
                    return [], [], True
                fallback_flags.append(fb_val)

            for int_key in ("period", "series_length"):
                if int_key in record and record[int_key] is not None:
                    iv = record[int_key]
                    if type(iv) is not int or iv <= 0:
                        return [], [], True

            if "source" in record and record["source"] is not None:
                src_val = record["source"]
                if type(src_val) is not str or not src_val.strip():
                    return [], [], True

            return tokens, fallback_flags, False

        return [], [], True

    @classmethod
    def _extract_object_atr_provenance(
        cls,
        obj: Any,
    ) -> Tuple[List[str], List[bool], bool]:
        """Safely reads optional ATR provenance metadata attached to an event or evidence object."""
        tokens: List[str] = []
        fallback_flags: List[bool] = []

        ok_prov, raw_prov = cls._safe_getattr(obj, "atr_provenance")
        if not ok_prov:
            return [], [], True
        if raw_prov is not cls._MISSING_ATTR and raw_prov is not None:
            t, f, m = cls._parse_atr_provenance_record(raw_prov)
            if m:
                return [], [], True
            tokens.extend(t)
            fallback_flags.extend(f)

        ok_st, raw_st = cls._safe_getattr(obj, "atr_status")
        if not ok_st:
            return [], [], True
        if raw_st is not cls._MISSING_ATTR and raw_st is not None:
            tok, m = cls._normalize_provenance_status(raw_st)
            if m or tok is None:
                return [], [], True
            tokens.append(tok)

        ok_fb, raw_fb = cls._safe_getattr(obj, "is_fallback_atr")
        if not ok_fb:
            return [], [], True
        if raw_fb is not cls._MISSING_ATTR and raw_fb is not None:
            if type(raw_fb) is not bool:
                return [], [], True
            fallback_flags.append(raw_fb)

        for int_attr in ("atr_period", "atr_series_length"):
            ok_int, raw_int = cls._safe_getattr(obj, int_attr)
            if not ok_int:
                return [], [], True
            if raw_int is not cls._MISSING_ATTR and raw_int is not None:
                if type(raw_int) is not int or raw_int <= 0:
                    return [], [], True

        ok_ex, extra = cls._safe_getattr(obj, "__pydantic_extra__")
        if not ok_ex:
            return [], [], True
        if type(extra) is dict:
            for key in ("atr_provenance",):
                if key in extra and extra[key] is not None:
                    t, f, m = cls._parse_atr_provenance_record(extra[key])
                    if m:
                        return [], [], True
                    tokens.extend(t)
                    fallback_flags.extend(f)
            for key in ("atr_status",):
                if key in extra and extra[key] is not None:
                    tok, m = cls._normalize_provenance_status(extra[key])
                    if m or tok is None:
                        return [], [], True
                    tokens.append(tok)
            if "is_fallback_atr" in extra and extra["is_fallback_atr"] is not None:
                if type(extra["is_fallback_atr"]) is not bool:
                    return [], [], True
                fallback_flags.append(extra["is_fallback_atr"])

        return tokens, fallback_flags, False

    def _validate_atr_provenance(
        self,
        sev: MarketStructureEvent,
        ev_data: MarketStructureEvidence,
        atr_provenance: Optional[Dict[str, Any]],
    ) -> Tuple[str, Optional[str]]:
        """
        Validates explicit ATR provenance/status metadata fail-closed.
        Never identifies fallback ATR by comparing numerical value alone.
        Returns ("OK", canonical_status) or ("FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE", None).
        """
        status_tokens: List[str] = []
        fallback_flags: List[bool] = []

        if atr_provenance is not None:
            if type(atr_provenance) is not dict:
                return "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE", None
            if type(sev.event_id) is not str or not sev.event_id.strip():
                return "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE", None
            ev_id = sev.event_id.strip()
            if ev_id in atr_provenance and atr_provenance[ev_id] is not None:
                t, f, m = self._parse_atr_provenance_record(atr_provenance[ev_id])
                if m:
                    return "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE", None
                status_tokens.extend(t)
                fallback_flags.extend(f)

        for container in (ev_data, sev):
            t, f, m = self._extract_object_atr_provenance(container)
            if m:
                return "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE", None
            status_tokens.extend(t)
            fallback_flags.extend(f)

        if any(flag is True for flag in fallback_flags):
            return "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE", None

        if not status_tokens:
            return "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE", None

        for tok in status_tokens:
            if tok in REJECTED_ATR_STATUSES or tok not in VALID_CALCULATED_ATR_STATUSES:
                return "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE", None

        if len(set(status_tokens)) != 1:
            return "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE", None

        return "OK", status_tokens[0]

    def _validate_displacement_candidate(
        self,
        sev: Any,
        index_norm: str,
        tf_norm: str,
        expected_dir: EventDirection,
        t_reclaim: datetime,
        t_as_of: datetime,
        reclaim_candle_id: str,
        atr_provenance: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Optional[str], Optional[float], Optional[float], Optional[float], Optional[str]]:
        """
        Evaluates whether a structure event qualifies as Stage 5 Displacement.
        Returns: (outcome, candle_id, body_ratio, atr, atr_multiple, atr_provenance_status)
        where outcome in {'SKIP', 'MATCH'} or 'FAIL_CLOSED_*'.
        """
        if type(sev) is not MarketStructureEvent:
            return "SKIP", None, None, None, None, None
        if type(sev.index) is not str or type(sev.timeframe) is not str:
            return "FAIL_CLOSED_INVALID_STRUCTURE_EVENT", None, None, None, None, None
        if sev.index.upper().strip() != index_norm or sev.timeframe.lower().strip() != tf_norm:
            return "SKIP", None, None, None, None, None
        if not is_valid_tz_aware_datetime(sev.available_at):
            return "FAIL_CLOSED_INVALID_STRUCTURE_TIMESTAMP", None, None, None, None, None
        if not is_valid_tz_aware_datetime(sev.event_time):
            return "FAIL_CLOSED_INVALID_STRUCTURE_TIMESTAMP", None, None, None, None, None
        if to_comparison_instant(sev.event_time) > to_comparison_instant(sev.available_at):
            return "FAIL_CLOSED_CAUSALITY_VIOLATION", None, None, None, None, None

        t_sev = to_comparison_instant(sev.available_at)
        if not (t_reclaim <= t_sev <= t_as_of):
            return "SKIP", None, None, None, None, None
        if sev.direction != expected_dir:
            return "SKIP", None, None, None, None, None

        ev_data = sev.evidence
        if type(ev_data) is not MarketStructureEvidence:
            return "FAIL_CLOSED_INVALID_DISPLACEMENT_EVIDENCE", None, None, None, None, None

        dc = getattr(ev_data, "displacement_confirmed", None)
        if type(dc) is not bool or dc is not True:
            return "SKIP", None, None, None, None, None

        cand_id = self._extract_structure_candle_id(sev, ev_data)
        if cand_id is None:
            return "FAIL_CLOSED_MISSING_STRUCTURAL_CANDLE_ID", None, None, None, None, None
        if t_sev == t_reclaim and cand_id != reclaim_candle_id:
            return "FAIL_CLOSED_EQUAL_TIMESTAMP_DIFFERENT_CANDLE_ID", None, None, None, None, None

        # ATR numeric validity check (must be finite positive built-in float)
        atr_val, atr_stat = _extract_finite_float_attr(ev_data, "atr")
        if atr_stat != "OK" or atr_val is None or atr_val <= 0.0:
            return "FAIL_CLOSED_INVALID_ATR_VALUE", None, None, None, None, None

        # Explicit ATR provenance enforcement (never infer fallback from numeric value alone)
        prov_outcome, prov_status = self._validate_atr_provenance(sev, ev_data, atr_provenance)
        if prov_outcome != "OK" or prov_status is None:
            return "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE", None, None, None, None, None

        # Enforce Step 3.2 approved displacement configuration
        body_ratio, br_stat = _extract_finite_float_attr(ev_data, "body_to_range_ratio")
        if br_stat != "OK" or body_ratio is None or body_ratio < self.inducement_config.min_displacement_body_ratio:
            return "FAIL_CLOSED_INSUFFICIENT_DISPLACEMENT_BODY_RATIO", None, None, None, None, None

        atr_mult, am_stat = _extract_finite_float_attr(ev_data, "atr_multiple")
        if am_stat != "OK" or atr_mult is None or atr_mult <= 0.0 or atr_mult < self.inducement_config.min_displacement_atr_multiple:
            return "FAIL_CLOSED_INSUFFICIENT_DISPLACEMENT_ATR_MULTIPLE", None, None, None, None, None

        return "MATCH", cand_id, body_ratio, atr_val, atr_mult, prov_status

    def _validate_structural_break_candidate(
        self,
        sev: Any,
        dealing_range: DealingRange,
        index_norm: str,
        tf_norm: str,
        expected_dir: EventDirection,
        t_reclaim: datetime,
        t_displaced: datetime,
        t_as_of: datetime,
        reclaim_candle_id: str,
        disp_candle_id: str,
        available_swings: Optional[List[SwingPoint]],
        consumed_break_event_ids: Optional[Set[str]],
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Evaluates whether a structure event satisfies Stage 6 Structural Confirmation.
        Returns: (outcome, break_candle_id, broken_swing_id)
        where outcome in {'SKIP', 'MATCH'} or 'FAIL_CLOSED_*'.
        """
        if type(sev) is not MarketStructureEvent:
            return "SKIP", None, None
        if type(sev.index) is not str or type(sev.timeframe) is not str:
            return "FAIL_CLOSED_INVALID_STRUCTURE_EVENT", None, None
        if sev.index.upper().strip() != index_norm or sev.timeframe.lower().strip() != tf_norm:
            return "SKIP", None, None
        if sev.event_type not in (ICTEventType.MSS, ICTEventType.CHOCH, ICTEventType.BOS):
            return "SKIP", None, None
        if sev.direction != expected_dir:
            return "SKIP", None, None
        if not is_valid_tz_aware_datetime(sev.available_at) or not is_valid_tz_aware_datetime(sev.event_time):
            return "FAIL_CLOSED_INVALID_STRUCTURE_TIMESTAMP", None, None
        if to_comparison_instant(sev.event_time) > to_comparison_instant(sev.available_at):
            return "FAIL_CLOSED_CAUSALITY_VIOLATION", None, None

        t_sev = to_comparison_instant(sev.available_at)
        # Stage 6 cannot precede Stage 5 Displacement
        if not (t_displaced <= t_sev <= t_as_of):
            return "SKIP", None, None

        if type(sev.event_id) is not str or not sev.event_id.strip():
            return "FAIL_CLOSED_INVALID_STRUCTURE_EVENT", None, None
        if consumed_break_event_ids is not None and sev.event_id in consumed_break_event_ids:
            return "FAIL_CLOSED_STRUCTURAL_EVENT_ALREADY_CONSUMED", None, None

        ev_data = sev.evidence
        if type(ev_data) is not MarketStructureEvidence:
            return "FAIL_CLOSED_INVALID_STRUCTURE_EVENT", None, None

        break_candle_id = self._extract_structure_candle_id(sev, ev_data)
        if break_candle_id is None:
            return "FAIL_CLOSED_MISSING_STRUCTURAL_CANDLE_ID", None, None

        if t_sev == t_reclaim and break_candle_id != reclaim_candle_id:
            return "FAIL_CLOSED_EQUAL_TIMESTAMP_DIFFERENT_BREAK_CANDLE_ID", None, None
        if t_sev == t_displaced and break_candle_id != disp_candle_id:
            return "FAIL_CLOSED_EQUAL_TIMESTAMP_DIFFERENT_BREAK_CANDLE_ID", None, None

        broken_id = getattr(ev_data, "broken_swing_id", None)
        if type(broken_id) is not str or not broken_id.strip():
            return "FAIL_CLOSED_BROKEN_SWING_CAUSALITY_VIOLATION", None, None
        broken_id = broken_id.strip()

        expected_target_swing_type = "HIGH" if dealing_range.direction == EventDirection.BULLISH else "LOW"
        broken_swing_type = getattr(ev_data, "broken_swing_type", None)
        if type(broken_swing_type) is not str or broken_swing_type.upper().strip() != expected_target_swing_type:
            return "FAIL_CLOSED_BROKEN_SWING_CAUSALITY_VIOLATION", None, None

        broken_swing_time = getattr(ev_data, "broken_swing_time", None)
        if not is_valid_tz_aware_datetime(broken_swing_time):
            return "FAIL_CLOSED_BROKEN_SWING_CAUSALITY_VIOLATION", None, None
        if to_comparison_instant(broken_swing_time) >= t_sev:
            return "FAIL_CLOSED_BROKEN_SWING_CAUSALITY_VIOLATION", None, None

        broken_level, bl_stat = _extract_finite_float_attr(ev_data, "broken_level")
        if bl_stat != "OK" or broken_level is None:
            return "FAIL_CLOSED_BROKEN_SWING_CAUSALITY_VIOLATION", None, None
        if not (dealing_range.low_price <= broken_level <= dealing_range.high_price):
            return "FAIL_CLOSED_BROKEN_SWING_CAUSALITY_VIOLATION", None, None

        if available_swings is not None:
            target_swing: Optional[SwingPoint] = None
            for sw in available_swings:
                if (
                    isinstance(sw, SwingPoint)
                    and type(sw.event_id) is str
                    and sw.event_id.strip() == broken_id
                ):
                    target_swing = sw
                    break
            if target_swing is None:
                return "FAIL_CLOSED_BROKEN_SWING_CAUSALITY_VIOLATION", None, None
            if (
                type(target_swing.index) is not str
                or type(target_swing.timeframe) is not str
                or target_swing.index.upper().strip() != index_norm
                or target_swing.timeframe.lower().strip() != tf_norm
                or target_swing.swing_type != expected_target_swing_type
                or not is_valid_tz_aware_datetime(target_swing.available_at)
                or to_comparison_instant(target_swing.available_at) >= t_sev
                or not (dealing_range.low_price <= target_swing.price <= dealing_range.high_price)
            ):
                return "FAIL_CLOSED_BROKEN_SWING_CAUSALITY_VIOLATION", None, None

        return "MATCH", break_candle_id, broken_id

    def evaluate_inducement_progression(
        self,
        candidate: SwingPoint,
        dealing_range: DealingRange,
        pools: List[LiquidityPool],
        liquidity_events: List[Any],
        structure_events: List[Any],
        as_of_time: datetime,
        order_blocks: Optional[List[Any]] = None,
        fvgs: Optional[List[Any]] = None,
        available_swings: Optional[List[SwingPoint]] = None,
        consumed_sweep_event_ids: Optional[Set[str]] = None,
        consumed_break_event_ids: Optional[Set[str]] = None,
        atr_provenance: Optional[Dict[str, Any]] = None,
    ) -> Tuple[InducementStatus, Optional[InducementEvent], List[InducementLifecycleTransition], str]:
        """
        Executes strict 7-Stage Linear Inducement Progression:
        1. CANDIDATE: Internal swing inside active dealing range with no-lookahead causality.
        2. SWEPT: Paired LIQUIDITY_SWEEP event meeting Step 3.1 penetration (>= 1.5 pts).
        3. RECLAIMED: Paired LIQUIDITY_RECLAIM event for the same pool.
        4. POI_TOUCH: Optional metadata recording if price touches OB/FVG.
        5. DISPLACED: Confirmed Step 3.2 displacement with verified ATR provenance.
        6. STRUCTURALLY_CONFIRMED: Step 3.2 BOS/CHoCH/MSS breaking target swing inside range.
        7. CONFIRMED: Terminal InducementEvent emitted.
        """
        transitions: List[InducementLifecycleTransition] = []

        # Parameter & causality checks
        if not isinstance(candidate, SwingPoint):
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_INVALID_CANDIDATE"
        if not isinstance(dealing_range, DealingRange):
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_INACTIVE_DEALING_RANGE"
        if not is_valid_tz_aware_datetime(as_of_time):
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_INVALID_AS_OF_TIME"
        if not is_valid_tz_aware_datetime(candidate.event_time) or not is_valid_tz_aware_datetime(candidate.available_at):
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_INVALID_CANDIDATE_TIMESTAMP"
        if to_comparison_instant(candidate.event_time) > to_comparison_instant(candidate.available_at):
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_CAUSALITY_VIOLATION"
        if not is_valid_tz_aware_datetime(dealing_range.available_at):
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_INVALID_RANGE_TIMESTAMP"

        t_as_of = to_comparison_instant(as_of_time)
        t_cand = to_comparison_instant(candidate.available_at)
        t_range = to_comparison_instant(dealing_range.available_at)
        if t_cand > t_as_of:
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_LOOKAHEAD_CANDIDATE"
        if t_range > t_as_of:
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_LOOKAHEAD_DEALING_RANGE"

        if (
            type(candidate.index) is not str
            or type(candidate.timeframe) is not str
            or type(dealing_range.index) is not str
            or type(dealing_range.timeframe) is not str
        ):
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_DIMENSION_MISMATCH"

        cand_index_norm = candidate.index.upper().strip()
        cand_tf_norm = candidate.timeframe.lower().strip()
        if (
            not cand_index_norm
            or not cand_tf_norm
            or cand_index_norm != dealing_range.index.upper().strip()
            or cand_tf_norm != dealing_range.timeframe.lower().strip()
        ):
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_DIMENSION_MISMATCH"

        if dealing_range.status not in (DealingRangeStatus.ACTIVE, DealingRangeStatus.EXPANDING_TRANSITION):
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_INACTIVE_DEALING_RANGE"

        # Check internal swing membership strictly inside dealing range bounds (low, high)
        if candidate.price <= dealing_range.low_price or candidate.price >= dealing_range.high_price:
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_CANDIDATE_OUTSIDE_RANGE"

        # Directional candidate type check
        if dealing_range.direction == EventDirection.BULLISH:
            if candidate.swing_type != "LOW":
                return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_DIRECTIONAL_TYPE_MISMATCH"
        elif dealing_range.direction == EventDirection.BEARISH:
            if candidate.swing_type != "HIGH":
                return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_DIRECTIONAL_TYPE_MISMATCH"
        else:
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_DIRECTIONAL_TYPE_MISMATCH"

        if type(pools) is not list:
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_INVALID_POOLS_CONTAINER"
        if type(structure_events) is not list:
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_INVALID_STRUCTURE_EVENTS_CONTAINER"

        # Stage 1: Match candidate to pool
        matched_pool, match_code = match_candidate_to_pools(
            candidate=candidate,
            pools=pools,
            tolerance_pts=self.inducement_config.pool_level_tolerance_pts,
        )

        if match_code == "UNLINKED_CANDIDATE":
            return InducementStatus.UNLINKED_CANDIDATE, None, transitions, "UNLINKED_CANDIDATE"
        if match_code != "LINKED" or matched_pool is None:
            return InducementStatus.UNRESOLVED_AMBIGUITY, None, transitions, match_code

        if not is_valid_tz_aware_datetime(matched_pool.available_at):
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_INVALID_POOL_TIMESTAMP"
        if to_comparison_instant(matched_pool.available_at) > t_as_of:
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_LOOKAHEAD_POOL"

        ssl_types = (
            LiquidityType.SSL,
            LiquidityType.EQL,
            LiquidityType.PDL,
            LiquidityType.PWL,
            LiquidityType.SESSION_LOW,
            LiquidityType.OPENING_RANGE_LOW,
        )
        bsl_types = (
            LiquidityType.BSL,
            LiquidityType.EQH,
            LiquidityType.PDH,
            LiquidityType.PWH,
            LiquidityType.SESSION_HIGH,
            LiquidityType.OPENING_RANGE_HIGH,
        )
        expected_pool_types = ssl_types if dealing_range.direction == EventDirection.BULLISH else bsl_types
        if matched_pool.liquidity_type not in expected_pool_types:
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_DIRECTIONAL_POOL_MISMATCH"

        # Stage 2 & 3: Sweep and Reclaim Pairing via Section 4.2
        sweep_ev, reclaim_ev, pair_code = pair_sweep_and_reclaim_events(
            target_pool_id=matched_pool.pool_id,
            candidate_available_at=candidate.available_at,
            as_of_time=as_of_time,
            events=liquidity_events,
        )

        if sweep_ev is None:
            if pair_code == "NO_ELIGIBLE_SWEEP_EVENT":
                return InducementStatus.CANDIDATE, None, transitions, "AWAITING_SWEEP_EVENT"
            return InducementStatus.INVALIDATED, None, transitions, pair_code

        if consumed_sweep_event_ids is not None and sweep_ev.event_id in consumed_sweep_event_ids:
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_LIQUIDITY_EVENT_ALREADY_CONSUMED"

        if (
            type(sweep_ev.index) is not str
            or type(sweep_ev.timeframe) is not str
            or sweep_ev.index.upper().strip() != cand_index_norm
            or sweep_ev.timeframe.lower().strip() != cand_tf_norm
            or not is_valid_tz_aware_datetime(sweep_ev.event_time)
            or to_comparison_instant(sweep_ev.event_time) > to_comparison_instant(sweep_ev.available_at)
        ):
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_CAUSALITY_VIOLATION"

        # Enforce Step 3.1 approved sweep penetration (default 1.5 pts)
        pen_depth, pen_stat = _extract_finite_float_attr(sweep_ev, "penetration_depth_pts")
        if pen_stat != "OK" or pen_depth is None or pen_depth < self.inducement_config.min_sweep_penetration_pts:
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_INSUFFICIENT_SWEEP_PENETRATION"

        # Record Stage 2: SWEPT
        trn_swept_id = compute_transition_id(
            parent_candidate_id=candidate.event_id,
            parent_inducement_event_id=None,
            from_stage="CANDIDATE",
            to_stage="SWEPT",
            source_trigger_event_id=sweep_ev.event_id,
            trigger_candle_id=sweep_ev.trigger_candle_id,
            index=candidate.index,
            timeframe=candidate.timeframe,
            configuration_fingerprint=self.inducement_fingerprint,
            configuration_version=self.inducement_config.configuration_version,
        )
        transitions.append(
            InducementLifecycleTransition(
                transition_id=trn_swept_id,
                parent_candidate_id=candidate.event_id,
                index=candidate.index,
                timeframe=candidate.timeframe,
                from_stage="CANDIDATE",
                to_stage="SWEPT",
                source_trigger_event_id=sweep_ev.event_id,
                trigger_candle_id=sweep_ev.trigger_candle_id,
                event_time=sweep_ev.event_time,
                available_at=sweep_ev.available_at,
                configuration_fingerprint=self.inducement_fingerprint,
                configuration_version=self.inducement_config.configuration_version,
                transition_evidence={
                    "pool_id": matched_pool.pool_id,
                    "penetration_price": sweep_ev.penetration_price,
                    "penetration_depth_pts": pen_depth,
                },
            )
        )

        if reclaim_ev is None:
            return InducementStatus.SWEPT, None, transitions, pair_code

        if (
            type(reclaim_ev.index) is not str
            or type(reclaim_ev.timeframe) is not str
            or reclaim_ev.index.upper().strip() != cand_index_norm
            or reclaim_ev.timeframe.lower().strip() != cand_tf_norm
            or not is_valid_tz_aware_datetime(reclaim_ev.event_time)
            or to_comparison_instant(reclaim_ev.event_time) > to_comparison_instant(reclaim_ev.available_at)
        ):
            return InducementStatus.INVALIDATED, None, transitions, "FAIL_CLOSED_CAUSALITY_VIOLATION"

        # Record Stage 3: RECLAIMED
        trn_reclaimed_id = compute_transition_id(
            parent_candidate_id=candidate.event_id,
            parent_inducement_event_id=None,
            from_stage="SWEPT",
            to_stage="RECLAIMED",
            source_trigger_event_id=reclaim_ev.event_id,
            trigger_candle_id=reclaim_ev.trigger_candle_id,
            index=candidate.index,
            timeframe=candidate.timeframe,
            configuration_fingerprint=self.inducement_fingerprint,
            configuration_version=self.inducement_config.configuration_version,
        )
        transitions.append(
            InducementLifecycleTransition(
                transition_id=trn_reclaimed_id,
                parent_candidate_id=candidate.event_id,
                index=candidate.index,
                timeframe=candidate.timeframe,
                from_stage="SWEPT",
                to_stage="RECLAIMED",
                source_trigger_event_id=reclaim_ev.event_id,
                trigger_candle_id=reclaim_ev.trigger_candle_id,
                event_time=reclaim_ev.event_time,
                available_at=reclaim_ev.available_at,
                configuration_fingerprint=self.inducement_fingerprint,
                configuration_version=self.inducement_config.configuration_version,
                transition_evidence={"reclaim_code": pair_code},
            )
        )

        # Stage 4: POI Evidence (Optional, records metadata, does not advance stage alone)
        poi_meta: Optional[Dict[str, Any]] = None
        if order_blocks or fvgs:
            poi_meta = {"poi_inspected": True}

        # Stage 5: Displacement Check with Step 3.2 config & strict ATR provenance validation
        t_reclaim = to_comparison_instant(reclaim_ev.available_at)
        expected_dir = EventDirection.BULLISH if dealing_range.direction == EventDirection.BULLISH else EventDirection.BEARISH

        displaced_event: Optional[MarketStructureEvent] = None
        disp_candle_id: Optional[str] = None
        disp_body_ratio: Optional[float] = None
        disp_atr: Optional[float] = None
        disp_atr_mult: Optional[float] = None
        disp_atr_prov_status: Optional[str] = None

        for sev in structure_events:
            outcome, c_id, br, atr_v, atr_m, prov_st = self._validate_displacement_candidate(
                sev=sev,
                index_norm=cand_index_norm,
                tf_norm=cand_tf_norm,
                expected_dir=expected_dir,
                t_reclaim=t_reclaim,
                t_as_of=t_as_of,
                reclaim_candle_id=reclaim_ev.trigger_candle_id,
                atr_provenance=atr_provenance,
            )
            if outcome.startswith("FAIL_CLOSED_"):
                return InducementStatus.INVALIDATED, None, transitions, outcome
            if outcome == "MATCH":
                displaced_event = sev
                disp_candle_id = c_id
                disp_body_ratio = br
                disp_atr = atr_v
                disp_atr_mult = atr_m
                disp_atr_prov_status = prov_st
                break

        if displaced_event is None or disp_candle_id is None:
            return InducementStatus.RECLAIMED, None, transitions, "AWAITING_DISPLACEMENT"

        # Record Stage 5: DISPLACED
        trn_displaced_id = compute_transition_id(
            parent_candidate_id=candidate.event_id,
            parent_inducement_event_id=None,
            from_stage="RECLAIMED",
            to_stage="DISPLACED",
            source_trigger_event_id=displaced_event.event_id,
            trigger_candle_id=disp_candle_id,
            index=candidate.index,
            timeframe=candidate.timeframe,
            configuration_fingerprint=self.inducement_fingerprint,
            configuration_version=self.inducement_config.configuration_version,
        )
        transitions.append(
            InducementLifecycleTransition(
                transition_id=trn_displaced_id,
                parent_candidate_id=candidate.event_id,
                index=candidate.index,
                timeframe=candidate.timeframe,
                from_stage="RECLAIMED",
                to_stage="DISPLACED",
                source_trigger_event_id=displaced_event.event_id,
                trigger_candle_id=disp_candle_id,
                event_time=displaced_event.event_time,
                available_at=displaced_event.available_at,
                configuration_fingerprint=self.inducement_fingerprint,
                configuration_version=self.inducement_config.configuration_version,
                transition_evidence={
                    "displacement_event_id": displaced_event.event_id,
                    "atr": disp_atr,
                    "atr_multiple": disp_atr_mult,
                    "body_to_range_ratio": disp_body_ratio,
                    "atr_provenance": disp_atr_prov_status,
                },
            )
        )

        # Stage 6: Structural Confirmation Check (must not precede Stage 5 displacement)
        t_displaced = to_comparison_instant(displaced_event.available_at)
        break_event: Optional[MarketStructureEvent] = None
        break_candle_id: Optional[str] = None
        target_broken_swing_id: Optional[str] = None

        for sev in structure_events:
            outcome, b_cid, b_swing_id = self._validate_structural_break_candidate(
                sev=sev,
                dealing_range=dealing_range,
                index_norm=cand_index_norm,
                tf_norm=cand_tf_norm,
                expected_dir=expected_dir,
                t_reclaim=t_reclaim,
                t_displaced=t_displaced,
                t_as_of=t_as_of,
                reclaim_candle_id=reclaim_ev.trigger_candle_id,
                disp_candle_id=disp_candle_id,
                available_swings=available_swings,
                consumed_break_event_ids=consumed_break_event_ids,
            )
            if outcome.startswith("FAIL_CLOSED_"):
                return InducementStatus.INVALIDATED, None, transitions, outcome
            if outcome == "MATCH":
                break_event = sev
                break_candle_id = b_cid
                target_broken_swing_id = b_swing_id
                break

        if break_event is None or break_candle_id is None or target_broken_swing_id is None:
            return InducementStatus.DISPLACED, None, transitions, "AWAITING_STRUCTURAL_CONFIRMATION"

        # Record Stage 6: STRUCTURALLY_CONFIRMED
        trn_struct_id = compute_transition_id(
            parent_candidate_id=candidate.event_id,
            parent_inducement_event_id=None,
            from_stage="DISPLACED",
            to_stage="STRUCTURALLY_CONFIRMED",
            source_trigger_event_id=break_event.event_id,
            trigger_candle_id=break_candle_id,
            index=candidate.index,
            timeframe=candidate.timeframe,
            configuration_fingerprint=self.inducement_fingerprint,
            configuration_version=self.inducement_config.configuration_version,
        )
        transitions.append(
            InducementLifecycleTransition(
                transition_id=trn_struct_id,
                parent_candidate_id=candidate.event_id,
                index=candidate.index,
                timeframe=candidate.timeframe,
                from_stage="DISPLACED",
                to_stage="STRUCTURALLY_CONFIRMED",
                source_trigger_event_id=break_event.event_id,
                trigger_candle_id=break_candle_id,
                event_time=break_event.event_time,
                available_at=break_event.available_at,
                configuration_fingerprint=self.inducement_fingerprint,
                configuration_version=self.inducement_config.configuration_version,
                transition_evidence={"broken_swing_id": target_broken_swing_id},
            )
        )

        # Stage 7: Terminal CONFIRMED
        terminal_event_id = compute_terminal_inducement_event_id(
            candidate_id=candidate.event_id,
            source_pool_id=matched_pool.pool_id,
            structural_confirmation_event_id=break_event.event_id,
            trigger_candle_id=break_candle_id,
            index=candidate.index,
            timeframe=candidate.timeframe,
            configuration_fingerprint=self.inducement_fingerprint,
            configuration_version=self.inducement_config.configuration_version,
        )

        inducement_event = InducementEvent(
            event_id=terminal_event_id,
            index=candidate.index,
            timeframe=candidate.timeframe,
            direction=expected_dir,
            price_level=candidate.price,
            status=InducementStatus.CONFIRMED,
            dealing_range_id=dealing_range.range_id,
            trigger_candle_id=break_candle_id,
            event_time=break_event.event_time,
            available_at=break_event.available_at,
            created_at=break_event.available_at,
            evidence=InducementEvidence(
                candidate_id=candidate.event_id,
                candidate_price=candidate.price,
                candidate_swing_type=candidate.swing_type,
                source_pool_id=matched_pool.pool_id,
                sweep_event_id=sweep_ev.event_id,
                reclaim_event_id=reclaim_ev.event_id,
                poi_reference=poi_meta,
                displacement_event_id=displaced_event.event_id,
                displacement_body_ratio=disp_body_ratio,
                displacement_atr=disp_atr,
                displacement_atr_multiple=disp_atr_mult,
                structural_break_event_id=break_event.event_id,
                broken_swing_id=target_broken_swing_id,
            ),
            configuration_version=self.inducement_config.configuration_version,
            engine_version=self.inducement_config.engine_version,
        )

        trn_confirmed_id = compute_transition_id(
            parent_candidate_id=candidate.event_id,
            parent_inducement_event_id=terminal_event_id,
            from_stage="STRUCTURALLY_CONFIRMED",
            to_stage="CONFIRMED",
            source_trigger_event_id=break_event.event_id,
            trigger_candle_id=break_candle_id,
            index=candidate.index,
            timeframe=candidate.timeframe,
            configuration_fingerprint=self.inducement_fingerprint,
            configuration_version=self.inducement_config.configuration_version,
        )
        transitions.append(
            InducementLifecycleTransition(
                transition_id=trn_confirmed_id,
                parent_candidate_id=candidate.event_id,
                parent_inducement_event_id=terminal_event_id,
                index=candidate.index,
                timeframe=candidate.timeframe,
                from_stage="STRUCTURALLY_CONFIRMED",
                to_stage="CONFIRMED",
                source_trigger_event_id=break_event.event_id,
                trigger_candle_id=break_candle_id,
                event_time=break_event.event_time,
                available_at=break_event.available_at,
                configuration_fingerprint=self.inducement_fingerprint,
                configuration_version=self.inducement_config.configuration_version,
                transition_evidence={"confirmed_inducement_id": terminal_event_id},
            )
        )

        return InducementStatus.CONFIRMED, inducement_event, transitions, "INDUCEMENT_CONFIRMED_SUCCESS"

    def analyze_timeframe(
        self,
        index: str,
        timeframe: str,
        current_price: float,
        swings: List[SwingPoint],
        pools: List[LiquidityPool],
        liquidity_events: List[Any],
        structure_events: List[Any],
        as_of_time: datetime,
        order_blocks: Optional[List[Any]] = None,
        fvgs: Optional[List[Any]] = None,
        parent_range: Optional[DealingRange] = None,
        atr_provenance: Optional[Dict[str, Any]] = None,
    ) -> TimeframePremiumDiscountReport:
        """
        Executes point-in-time timeframe analysis with strict no-lookahead filtering:
        1. Identifies latest confirmed dealing range from matching structural swings <= as_of_time.
        2. Evaluates current price zone relative to dealing range.
        3. Identifies and progresses internal inducement candidates with 1-to-1 consumption.
        4. Emits structural bias with confluence score explicitly UNAVAILABLE / NOT_CALIBRATED.
        """
        index_norm = _require_exact_str(index, "index").upper()
        tf_norm = _require_exact_str(timeframe, "timeframe").lower()
        if not is_valid_tz_aware_datetime(as_of_time):
            raise ValueError("as_of_time must be a valid timezone-aware datetime")
        if isinstance(current_price, bool) or not isinstance(current_price, (int, float)) or not math.isfinite(float(current_price)):
            raise ValueError(f"current_price must be a finite numeric value, got {current_price!r}")
        if type(swings) is not list:
            raise TypeError("swings must be an exact list")
        if type(pools) is not list:
            raise TypeError("pools must be an exact list")
        if type(liquidity_events) is not list:
            raise TypeError("liquidity_events must be an exact list")
        if type(structure_events) is not list:
            raise TypeError("structure_events must be an exact list")
        if atr_provenance is not None and type(atr_provenance) is not dict:
            raise TypeError("atr_provenance must be an exact dict")

        t_as_of = to_comparison_instant(as_of_time)

        # Filter swings strictly by index, timeframe, and availability causality <= as_of_time
        valid_swings = [
            s for s in swings
            if isinstance(s, SwingPoint)
            and type(s.index) is str
            and type(s.timeframe) is str
            and s.index.upper().strip() == index_norm
            and s.timeframe.lower().strip() == tf_norm
            and is_valid_tz_aware_datetime(s.event_time)
            and is_valid_tz_aware_datetime(s.available_at)
            and to_comparison_instant(s.event_time) <= to_comparison_instant(s.available_at) <= t_as_of
        ]

        valid_pools = [
            p for p in pools
            if isinstance(p, LiquidityPool)
            and type(p.index) is str
            and type(p.timeframe) is str
            and p.index.upper().strip() == index_norm
            and p.timeframe.lower().strip() == tf_norm
            and is_valid_tz_aware_datetime(p.available_at)
            and to_comparison_instant(p.available_at) <= t_as_of
        ]

        valid_structure_events = [
            sev for sev in structure_events
            if type(sev) is MarketStructureEvent
            and type(sev.index) is str
            and type(sev.timeframe) is str
            and sev.index.upper().strip() == index_norm
            and sev.timeframe.lower().strip() == tf_norm
            and is_valid_tz_aware_datetime(sev.available_at)
            and to_comparison_instant(sev.available_at) <= t_as_of
        ]

        high_swings = sorted(
            [s for s in valid_swings if s.swing_type == "HIGH"],
            key=lambda s: (to_comparison_instant(s.available_at), s.event_id),
            reverse=True,
        )
        low_swings = sorted(
            [s for s in valid_swings if s.swing_type == "LOW"],
            key=lambda s: (to_comparison_instant(s.available_at), s.event_id),
            reverse=True,
        )

        active_range: Optional[DealingRange] = None
        current_zone: Optional[ZoneClassification] = None

        if high_swings and low_swings:
            recent_high = high_swings[0]
            recent_low = low_swings[0]
            if recent_high.price > recent_low.price:
                direction = (
                    EventDirection.BULLISH
                    if to_comparison_instant(recent_low.event_time) < to_comparison_instant(recent_high.event_time)
                    else EventDirection.BEARISH
                )
                try:
                    active_range = self.create_dealing_range(
                        high_swing=recent_high,
                        low_swing=recent_low,
                        direction=direction,
                        as_of_time=as_of_time,
                    )
                    current_zone = classify_zone(
                        price=float(current_price),
                        high=active_range.high_price,
                        low=active_range.low_price,
                        equilibrium=active_range.equilibrium_price,
                        delta_r=active_range.delta_r,
                        neutral_band_delta=active_range.neutral_band_delta,
                    )
                except ValueError:
                    active_range = None
                    current_zone = None

        candidates: List[SwingPoint] = []
        all_transitions: List[InducementLifecycleTransition] = []
        confirmed_inducements: List[InducementEvent] = []
        consumed_sweep_ids: Set[str] = set()
        consumed_break_ids: Set[str] = set()

        if active_range is not None:
            internal_swings = sorted(
                [
                    s for s in valid_swings
                    if active_range.low_price < s.price < active_range.high_price
                    and s.event_id != active_range.high_swing_id
                    and s.event_id != active_range.low_swing_id
                ],
                key=lambda s: (to_comparison_instant(s.available_at), s.event_id),
            )
            candidates = internal_swings

            for cand in internal_swings:
                status, ind_ev, trans_list, _code = self.evaluate_inducement_progression(
                    candidate=cand,
                    dealing_range=active_range,
                    pools=valid_pools,
                    liquidity_events=liquidity_events,
                    structure_events=valid_structure_events,
                    as_of_time=as_of_time,
                    order_blocks=order_blocks,
                    fvgs=fvgs,
                    available_swings=valid_swings,
                    consumed_sweep_event_ids=consumed_sweep_ids,
                    consumed_break_event_ids=consumed_break_ids,
                    atr_provenance=atr_provenance,
                )
                all_transitions.extend(trans_list)
                if status == InducementStatus.CONFIRMED and ind_ev is not None:
                    confirmed_inducements.append(ind_ev)
                    if ind_ev.evidence.sweep_event_id:
                        consumed_sweep_ids.add(ind_ev.evidence.sweep_event_id)
                    if ind_ev.evidence.structural_break_event_id:
                        consumed_break_ids.add(ind_ev.evidence.structural_break_event_id)

        tf_bias = self._derive_timeframe_bias(active_range, current_zone)

        return TimeframePremiumDiscountReport(
            index=index,
            timeframe=timeframe,
            as_of_time=as_of_time,
            active_dealing_range=active_range,
            all_ranges=[active_range] if active_range else [],
            current_price=float(current_price),
            current_zone=current_zone,
            inducement_candidates=candidates,
            inducement_transitions=all_transitions,
            confirmed_inducements=confirmed_inducements,
            timeframe_confluence_score=None,
            score_status="UNAVAILABLE",
            calibration_status="NOT_CALIBRATED",
            timeframe_bias=tf_bias,
            configuration_fingerprint=self.dealing_fingerprint,
            engine_version=self.dealing_config.engine_version,
        )

    def evaluate_multi_timeframe_confluence(
        self,
        reports: Dict[str, TimeframePremiumDiscountReport],
        as_of_time: datetime,
    ) -> ICTConfluenceReport:
        """
        Aggregates timeframe alignment metadata with no-lookahead verification.
        ICT timeframe weights and numeric confluence scoring remain UNAVAILABLE / NOT_CALIBRATED
        until separately approved; Phase 2 MTF engine weights remain completely untouched and separate.
        """
        if not isinstance(reports, dict):
            raise TypeError("reports must be a dict mapping timeframe keys to TimeframePremiumDiscountReport")
        if not is_valid_tz_aware_datetime(as_of_time):
            raise ValueError("as_of_time must be a valid timezone-aware datetime")

        t_as_of = to_comparison_instant(as_of_time)
        first_report = next(iter(reports.values())) if reports else None
        index_sym = first_report.index if first_report else "NIFTY 50"
        index_norm = _require_exact_str(index_sym, "index").upper()

        bullish_count = 0
        bearish_count = 0
        neutral_count = 0

        for tf_key, rep in reports.items():
            if not isinstance(rep, TimeframePremiumDiscountReport):
                raise TypeError("Each value in reports must be a TimeframePremiumDiscountReport")
            tf_key_clean = _require_exact_str(tf_key, "timeframe key").lower()
            rep_tf_clean = _require_exact_str(rep.timeframe, "report.timeframe").lower()
            if tf_key_clean != rep_tf_clean:
                raise ValueError(f"Report timeframe key '{tf_key}' does not match report.timeframe '{rep.timeframe}'")
            if _require_exact_str(rep.index, "report.index").upper() != index_norm:
                raise ValueError("Cross-index timeframe reports cannot be aggregated into one confluence report")
            if not is_valid_tz_aware_datetime(rep.as_of_time):
                raise ValueError(f"Report for '{tf_key}' has invalid as_of_time")
            if to_comparison_instant(rep.as_of_time) > t_as_of:
                raise ValueError(
                    f"Lookahead violation: timeframe report '{tf_key}' as_of_time exceeds confluence as_of_time"
                )
            if rep.active_dealing_range is not None:
                if (
                    not is_valid_tz_aware_datetime(rep.active_dealing_range.available_at)
                    or to_comparison_instant(rep.active_dealing_range.available_at) > t_as_of
                ):
                    raise ValueError(
                        f"Lookahead violation: active dealing range in '{tf_key}' exceeds confluence as_of_time"
                    )

            if rep.timeframe_bias == "BULLISH":
                bullish_count += 1
            elif rep.timeframe_bias == "BEARISH":
                bearish_count += 1
            else:
                neutral_count += 1

        if bullish_count > 0 and bearish_count > 0:
            primary_bias = "CONFLICTING"
        elif bullish_count > 0:
            primary_bias = "BULLISH"
        elif bearish_count > 0:
            primary_bias = "BEARISH"
        else:
            primary_bias = "NEUTRAL"

        return ICTConfluenceReport(
            index=index_sym,
            as_of_time=as_of_time,
            timeframe_reports=reports,
            timeframe_weights={},
            composite_confluence_score=None,
            score_status="UNAVAILABLE",
            calibration_status="NOT_CALIBRATED",
            primary_bias=primary_bias,
            recommended_action="NO_TRADE",
            alignment_summary={
                "status": "UNAVAILABLE",
                "calibration_status": "NOT_CALIBRATED",
                "reason": "ICT_CONFLUENCE_WEIGHTS_AND_THRESHOLDS_NOT_CALIBRATED",
                "bullish_timeframes": bullish_count,
                "bearish_timeframes": bearish_count,
                "neutral_timeframes": neutral_count,
                "total_timeframes_analyzed": len(reports),
                "approved_timeframe_hierarchy": ["1H", "15M", "5M", "3M", "1M"],
            },
            execution_mode="PAPER_TRADING_ONLY",
        )
