"""
AIVOLVE Phase 3 Step 3.5 — Automated Verification Suite.
Premium / Discount & Inducement Intelligence Engine.

Covers:
1. Section 4.2 Exact Built-in Type & Defensive Validation (including 6 frozen proposed tests).
2. Evidence Snapshot Normalization & Valid State Matrix.
3. Strict Sweep/Reclaim Pairing & Cardinality.
4. Timestamp Causality, Time-Window & DST Safety.
5. Dealing Range Geometry, Raw Spot Precision & Equilibrium.
6. Premium / Discount Zone Classification.
7. Candidate-to-Pool Identity Matching & Tolerance.
8. Strict 7-Stage Linear Inducement Progression (Anti-Bypass).
9. Parent-Child Multi-Timeframe Alignment & Confluence Scorecard.
10. Determinism, RFC-Style Canonical Preprocessing & No-Lookahead.
"""

import math
import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Any

import pytest
from pydantic import BaseModel

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
    MarketStructureEvidence,
    MarketStructureEvent,
)
from app.options.ict_smc.premium_discount_engine import (
    ValidatedEvidenceSnapshot,
    ValidatedLiquidityEventSnapshot,
    VALID_EVIDENCE_STATE_COMBINATIONS,
    is_valid_tz_aware_datetime,
    to_comparison_instant,
    capture_and_normalize_evidence,
    validate_same_candle_rejection_wick,
    build_validated_event_snapshots,
    validate_snapshot_integrity,
    pair_validated_event_snapshots,
    pair_sweep_and_reclaim_events,
    preprocess_canonical_input,
    compute_step3_5_fingerprint,
    generate_dealing_range_id,
    compute_transition_id,
    compute_terminal_inducement_event_id,
    DealingRangeStatus,
    ZoneClassification,
    InducementStatus,
    ATRProvenanceStatus,
    ATRProvenance,
    DealingRangeConfiguration,
    DealingRange,
    InducementConfiguration,
    InducementLifecycleTransition,
    InducementEvidence,
    InducementEvent,
    TimeframePremiumDiscountReport,
    ICTConfluenceReport,
    calculate_equilibrium,
    classify_zone,
    match_candidate_to_pools,
    PremiumDiscountEngine,
)


# ============================================================================
# FIXTURES & HELPER CONSTRUCTORS
# ============================================================================

def make_tz_datetime(hour: int = 9, minute: int = 15, second: int = 0, day: int = 10, offset_hours: int = 5, offset_minutes: int = 30) -> datetime:
    tz = timezone(timedelta(hours=offset_hours, minutes=offset_minutes))
    return datetime(2026, 11, day, hour, minute, second, tzinfo=tz)


def make_native_liquidity_event(
    event_id: str = "EVT-SWP-1",
    pool_id: str = "POOL_1",
    event_type: ICTEventType = ICTEventType.LIQUIDITY_SWEEP,
    available_at: Optional[datetime] = None,
    trigger_candle_id: str = "c_10",
    rejection_wick_ratio: Optional[float] = 0.40,
    is_wick_sweep: bool = True,
    is_reclaimed: bool = False,
    penetration_depth_pts: float = 3.0,
) -> LiquidityEvent:
    if available_at is None:
        available_at = make_tz_datetime(9, 30)

    evidence = LiquidityEvidence(
        touch_count=1,
        distance_from_current_pts=5.0,
        distance_from_current_pct=0.02,
        penetration_depth_pts=penetration_depth_pts,
        penetration_depth_pct=0.01,
        is_wick_penetration=True,
        is_candle_close_breakout=False,
        is_reclaim_confirmed=is_reclaimed,
        rejection_wick_ratio=rejection_wick_ratio,
        source_swing_ids=["SWI-1"],
    )

    return LiquidityEvent(
        event_id=event_id,
        pool_id=pool_id,
        index="NIFTY 50",
        event_type=event_type,
        liquidity_type=LiquidityType.SSL,
        direction=EventDirection.BULLISH,
        timeframe="15m",
        level=24000.0,
        price_level=24000.0,
        trigger_candle_id=trigger_candle_id,
        penetration_price=23997.0,
        close_price=24002.0,
        penetration_depth_pts=penetration_depth_pts,
        event_time=available_at,
        available_at=available_at,
        created_at=available_at,
        confirmed_at=available_at,
        is_wick_sweep=is_wick_sweep,
        is_candle_close_breakout=False,
        is_reclaimed=is_reclaimed,
        evidence=evidence,
        status=LiquidityLifecycleState.SWEPT if not is_reclaimed else LiquidityLifecycleState.RECLAIMED,
        source_candle_identifiers=[trigger_candle_id],
        source_data_quality="PRISTINE",
        configuration_version="3.1.0",
        engine_version="3.1.0",
    )


def make_native_swing_point(
    event_id: str = "SWI-1",
    swing_type: str = "LOW",
    price: float = 24000.0,
    candle_id: str = "c_5",
    timeframe: str = "15m",
    available_at: Optional[datetime] = None,
) -> SwingPoint:
    if available_at is None:
        available_at = make_tz_datetime(9, 20)
    return SwingPoint(
        event_id=event_id,
        index="NIFTY 50",
        swing_type=swing_type,
        price=price,
        timeframe=timeframe,
        bar_index=5,
        candle_id=candle_id,
        event_time=available_at,
        available_at=available_at,
        left_bars=3,
        right_bars=3,
        volume=1000.0,
        data_quality_status="PRISTINE",
    )


def make_native_liquidity_pool(
    pool_id: str = "POOL_1",
    level: float = 24000.0,
    source_candle_ids: Optional[List[str]] = None,
    source_swing_ids: Optional[List[str]] = None,
    liquidity_type: LiquidityType = LiquidityType.SSL,
    direction: EventDirection = EventDirection.BULLISH,
    timeframe: str = "15m",
) -> LiquidityPool:
    c_ids = source_candle_ids if source_candle_ids is not None else ["c_5"]
    s_ids = source_swing_ids if source_swing_ids is not None else ["SWI-1"]
    t = make_tz_datetime(9, 20)

    evidence = LiquidityEvidence(
        touch_count=1,
        distance_from_current_pts=0.0,
        distance_from_current_pct=0.0,
        penetration_depth_pts=0.0,
        penetration_depth_pct=0.0,
        is_wick_penetration=False,
        is_candle_close_breakout=False,
        is_reclaim_confirmed=False,
        source_swing_ids=s_ids,
    )

    return LiquidityPool(
        pool_id=pool_id,
        index="NIFTY 50",
        liquidity_type=liquidity_type,
        direction=direction,
        timeframe=timeframe,
        level=level,
        upper_bound=level + 2.0,
        lower_bound=level - 2.0,
        status=LiquidityLifecycleState.CONFIRMED,
        touch_count=1,
        formation_time=t,
        available_at=t,
        updated_at=t,
        source_candle_ids=c_ids,
        evidence=evidence,
        source_data_quality="PRISTINE",
        configuration_version="3.1.0",
        engine_version="3.1.0",
    )


# ============================================================================
# SUITE 1: SECTION 4.2 EXACT BUILT-IN TYPE & DEFENSIVE VALIDATION (PROPOSED 1-6)
# ============================================================================

class FaultyStr(str):
    def strip(self, chars=None):
        raise RuntimeError("Custom strip fault should never execute!")


class FaultyList(list):
    def __iter__(self):
        raise RuntimeError("Custom iterator fault should never execute!")


class FaultySnapshot(ValidatedLiquidityEventSnapshot):
    def __init__(self, *args, **kwargs):
        pass

    @property
    def trigger_candle_id(self):
        raise RuntimeError("Malicious trigger candle property!")


class TestSection42DefensiveValidation:
    """Implements and verifies the 6 frozen proposed tests plus boundary conditions."""

    def test_proposed_1_faulty_str_target_pool_id_in_pair_sweep_and_reclaim_events(self):
        """Test 1: Custom String Subclass on target_pool_id in pair_sweep_and_reclaim_events."""
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        faulty_id = FaultyStr("POOL_1")

        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id=faulty_id,
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=[],
        )
        assert s is None
        assert r is None
        assert code == "FAIL_CLOSED_INVALID_TARGET_POOL_ID"

    def test_proposed_2_faulty_str_target_pool_id_in_pair_validated_event_snapshots(self):
        """Test 2: Custom String Subclass on target_pool_id in pair_validated_event_snapshots."""
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        faulty_id = FaultyStr("POOL_1")

        s, r, code = pair_validated_event_snapshots(
            target_pool_id=faulty_id,
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            snapshots=[],
        )
        assert s is None
        assert r is None
        assert code == "FAIL_CLOSED_INVALID_TARGET_POOL_ID"

    def test_proposed_3_faulty_str_pool_id_in_build_validated_event_snapshots(self):
        """Test 3: Custom String Subclass on pool_id in build_validated_event_snapshots."""
        e = make_native_liquidity_event()
        # Direct attribute assignment of FaultyStr
        object.__setattr__(e, "pool_id", FaultyStr("POOL_1"))

        snaps, code = build_validated_event_snapshots([e])
        assert snaps is None
        assert code == "FAIL_CLOSED_MALFORMED_EVENT_MISSING_POOL_ID"

    def test_proposed_4_faulty_str_trigger_candle_id_in_build_validated_event_snapshots(self):
        """Test 4: Custom String Subclass on trigger_candle_id in build_validated_event_snapshots."""
        e = make_native_liquidity_event()
        object.__setattr__(e, "trigger_candle_id", FaultyStr("c_10"))

        snaps, code = build_validated_event_snapshots([e])
        assert snaps is None
        assert code == "FAIL_CLOSED_MALFORMED_EVENT_MISSING_TRIGGER_CANDLE"

    def test_proposed_5_faulty_list_subclass_with_throwing_iterator(self):
        """Test 5: Custom List Subclass With Exception-Raising Iterator."""
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        faulty_events = FaultyList([make_native_liquidity_event()])

        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=faulty_events,
        )
        assert s is None
        assert r is None
        assert code == "FAIL_CLOSED_UNSUPPORTED_EVENT_ENVELOPE_FOR_LIQUIDITY_PAIRING"

    def test_proposed_6_snapshot_subclass_with_throwing_property(self):
        """Test 6: Snapshot Subclass With Exception-Raising Property."""
        faulty_snap = object.__new__(FaultySnapshot)

        code = validate_snapshot_integrity([faulty_snap])
        assert code == "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"

    def test_exact_str_validation_rejects_non_str_types(self):
        """Verifies exact str check rejects ints, dicts, None without exception."""
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)

        for invalid_val in [123, 45.6, None, ["POOL_1"], {"pool": "POOL_1"}]:
            s, r, code = pair_sweep_and_reclaim_events(
                target_pool_id=invalid_val,
                candidate_available_at=t_cand,
                as_of_time=t_as_of,
                events=[],
            )
            assert code == "FAIL_CLOSED_INVALID_TARGET_POOL_ID"

    def test_whitespace_strings_rejected(self):
        """Empty or whitespace-only strings fail closed."""
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        for ws in ["", "   ", "\t", "\n"]:
            s, r, code = pair_sweep_and_reclaim_events(
                target_pool_id=ws,
                candidate_available_at=t_cand,
                as_of_time=t_as_of,
                events=[],
            )
            assert code == "FAIL_CLOSED_INVALID_TARGET_POOL_ID"

    def test_stage_0_rejects_non_liquidity_event_instances(self):
        """Stage 0 rejects non-LiquidityEvent instances in events list."""
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        events = [
            make_native_liquidity_event(),
            {"event_type": "LIQUIDITY_SWEEP", "pool_id": "POOL_1"},  # mock dict
        ]
        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=events,
        )
        assert code == "FAIL_CLOSED_UNSUPPORTED_EVENT_ENVELOPE_FOR_LIQUIDITY_PAIRING"


# ============================================================================
# SUITE 2: EVIDENCE SNAPSHOT NORMALIZATION & VALID STATE MATRIX
# ============================================================================

class CustomFloat(float):
    """Custom float subclass that overrides __float__."""
    def __float__(self):
        return 999.999


class TestEvidenceSnapshotNormalization:

    def test_capture_and_normalize_valid_float(self):
        e = make_native_liquidity_event(rejection_wick_ratio=0.45)
        snap = capture_and_normalize_evidence(e)
        assert snap.container_status == "PRESENT"
        assert snap.is_valid_container is True
        assert snap.wick_ratio_status == "VALID_NORMALIZED"
        assert type(snap.normalized_wick_ratio) is float
        assert snap.normalized_wick_ratio == 0.45

    def test_capture_rejects_boolean(self):
        e = make_native_liquidity_event()
        object.__setattr__(e.evidence, "rejection_wick_ratio", True)
        snap = capture_and_normalize_evidence(e)
        assert snap.wick_ratio_status == "INVALID_VALUE"
        assert snap.normalized_wick_ratio is None

    def test_capture_converts_custom_float_to_builtin_float(self):
        class SimpleFloatSubclass(float):
            pass

        e = make_native_liquidity_event()
        cf = SimpleFloatSubclass(0.38)
        object.__setattr__(e.evidence, "rejection_wick_ratio", cf)
        snap = capture_and_normalize_evidence(e)
        assert snap.wick_ratio_status == "VALID_NORMALIZED"
        assert type(snap.normalized_wick_ratio) is float
        assert snap.normalized_wick_ratio == 0.38

    def test_capture_handles_overflow_float(self):
        e = make_native_liquidity_event()
        object.__setattr__(e.evidence, "rejection_wick_ratio", 1e308 * 10)  # Inf
        snap = capture_and_normalize_evidence(e)
        assert snap.wick_ratio_status == "INVALID_VALUE"
        assert snap.normalized_wick_ratio is None

    def test_capture_handles_nan(self):
        e = make_native_liquidity_event()
        object.__setattr__(e.evidence, "rejection_wick_ratio", float("nan"))
        snap = capture_and_normalize_evidence(e)
        assert snap.wick_ratio_status == "INVALID_VALUE"
        assert snap.normalized_wick_ratio is None

    def test_capture_missing_evidence_container(self):
        e = make_native_liquidity_event()
        object.__setattr__(e, "evidence", None)
        snap = capture_and_normalize_evidence(e)
        assert snap.container_status == "MISSING"
        assert snap.is_valid_container is False
        assert snap.wick_ratio_status == "MISSING_OR_NONE"
        assert snap.normalized_wick_ratio is None

    def test_validate_all_7_legitimate_states(self):
        """Verifies that all 7 combinations in VALID_EVIDENCE_STATE_COMBINATIONS pass integrity."""
        e = make_native_liquidity_event()
        t = make_tz_datetime(9, 30)
        c_inst = to_comparison_instant(t)

        for c_status, is_valid_c, w_status, has_norm in VALID_EVIDENCE_STATE_COMBINATIONS:
            norm_val = 0.40 if has_norm else None
            ev_snap = ValidatedEvidenceSnapshot(c_status, is_valid_c, w_status, norm_val)
            snap = ValidatedLiquidityEventSnapshot(
                event=e,
                pool_id=e.pool_id,
                event_type=e.event_type,
                available_at=e.available_at,
                trigger_candle_id=e.trigger_candle_id,
                comparison_instant=c_inst,
                evidence_snapshot=ev_snap,
            )
            err = validate_snapshot_integrity([snap])
            assert err is None, f"State {c_status, is_valid_c, w_status, has_norm} failed with {err}"

    def test_illegal_evidence_state_combination_fails_integrity(self):
        """Verifies that an unlisted combination fails snapshot integrity."""
        e = make_native_liquidity_event()
        t = make_tz_datetime(9, 30)
        c_inst = to_comparison_instant(t)

        # Illegal: MISSING container but is_valid_container=True
        ev_snap = ValidatedEvidenceSnapshot("MISSING", True, "MISSING_OR_NONE", None)
        snap = ValidatedLiquidityEventSnapshot(
            event=e,
            pool_id=e.pool_id,
            event_type=e.event_type,
            available_at=e.available_at,
            trigger_candle_id=e.trigger_candle_id,
            comparison_instant=c_inst,
            evidence_snapshot=ev_snap,
        )
        err = validate_snapshot_integrity([snap])
        assert err == "FAIL_CLOSED_MALFORMED_SNAPSHOT_INTEGRITY_VIOLATION"


# ============================================================================
# SUITE 3: STRICT SWEEP/RECLAIM PAIRING & CARDINALITY
# ============================================================================

class TestSweepReclaimPairingCardinality:

    def test_zero_sweeps_returns_no_eligible_sweep_event(self):
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=[],
        )
        assert s is None
        assert r is None
        assert code == "NO_ELIGIBLE_SWEEP_EVENT"

    def test_multiple_sweeps_fail_closed_ambiguous(self):
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        e1 = make_native_liquidity_event("EVT-1", available_at=make_tz_datetime(9, 25), trigger_candle_id="c_6")
        e2 = make_native_liquidity_event("EVT-2", available_at=make_tz_datetime(9, 35), trigger_candle_id="c_8")

        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=[e1, e2],
        )
        assert s is None
        assert r is None
        assert code == "FAIL_CLOSED_AMBIGUOUS_SWEEP_RECLAIM_PAIR"

    def test_one_sweep_zero_reclaims_returns_unreclaimed_sweep(self):
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        e1 = make_native_liquidity_event("EVT-1", available_at=make_tz_datetime(9, 25), trigger_candle_id="c_6")

        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=[e1],
        )
        assert s is not None
        assert r is None
        assert code == "UNRECLAIMED_SWEEP"

    def test_unique_chronological_distinct_candles_matched(self):
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        sweep = make_native_liquidity_event("EVT-SWP", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_6")
        reclaim = make_native_liquidity_event("EVT-REC", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_7", is_reclaimed=True)

        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=[sweep, reclaim],
        )
        assert s == sweep
        assert r == reclaim
        assert code == "UNIQUE_CHRONOLOGICAL_PAIR_MATCHED"

    def test_different_timestamp_same_candle_id_fails_closed(self):
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        sweep = make_native_liquidity_event("EVT-SWP", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_6")
        reclaim = make_native_liquidity_event("EVT-REC", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_6", is_reclaimed=True)

        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=[sweep, reclaim],
        )
        assert code == "FAIL_CLOSED_DIFFERENT_TIMESTAMP_SAME_CANDLE_ID"

    def test_causality_inversion_fails_closed(self):
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        sweep = make_native_liquidity_event("EVT-SWP", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 35), trigger_candle_id="c_8")
        reclaim = make_native_liquidity_event("EVT-REC", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_6", is_reclaimed=True)

        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=[sweep, reclaim],
        )
        assert code == "FAIL_CLOSED_CAUSALITY_VIOLATION"

    def test_equal_timestamp_different_candle_id_fails_closed(self):
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        same_t = make_tz_datetime(9, 30)
        sweep = make_native_liquidity_event("EVT-SWP", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=same_t, trigger_candle_id="c_6")
        reclaim = make_native_liquidity_event("EVT-REC", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=same_t, trigger_candle_id="c_7", is_reclaimed=True)

        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=[sweep, reclaim],
        )
        assert code == "FAIL_CLOSED_EQUAL_TIMESTAMP_DIFFERENT_CANDLE_ID"

    def test_same_candle_reclaim_valid_ratio_matched(self):
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        same_t = make_tz_datetime(9, 30)
        sweep = make_native_liquidity_event("EVT-SWP", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=same_t, trigger_candle_id="c_6")
        reclaim = make_native_liquidity_event("EVT-REC", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=same_t, trigger_candle_id="c_6", rejection_wick_ratio=0.45, is_reclaimed=True)

        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=[sweep, reclaim],
        )
        assert s == sweep
        assert r == reclaim
        assert code == "UNIQUE_SAME_CANDLE_PAIR_MATCHED"

    def test_same_candle_insufficient_wick_fails_closed(self):
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)
        same_t = make_tz_datetime(9, 30)
        sweep = make_native_liquidity_event("EVT-SWP", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=same_t, trigger_candle_id="c_6")
        reclaim = make_native_liquidity_event("EVT-REC", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=same_t, trigger_candle_id="c_6", rejection_wick_ratio=0.20, is_reclaimed=True)

        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=[sweep, reclaim],
        )
        assert code == "FAIL_CLOSED_INSUFFICIENT_REJECTION_WICK"


# ============================================================================
# SUITE 4: TIME WINDOW, REPLAY & DST SAFETY
# ============================================================================

class TestTimeWindowAndDSTSafety:

    def test_candidate_time_greater_equal_as_of_time_fails(self):
        t1 = make_tz_datetime(10, 0)
        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t1,
            as_of_time=t1,
            events=[],
        )
        assert code == "FAIL_CLOSED_INVALID_TIME_WINDOW"

    def test_is_valid_tz_aware_datetime_rejects_naive(self):
        naive_dt = datetime(2026, 11, 10, 9, 15)
        assert is_valid_tz_aware_datetime(naive_dt) is False
        assert is_valid_tz_aware_datetime("2026-11-10T09:15:00") is False
        assert is_valid_tz_aware_datetime(None) is False

    def test_comparison_instants_cross_timezone_deterministic(self):
        utc_dt = datetime(2026, 11, 10, 4, 0, tzinfo=timezone.utc)
        ist_dt = datetime(2026, 11, 10, 9, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        assert to_comparison_instant(utc_dt) == to_comparison_instant(ist_dt)

    def test_events_outside_replay_window_filtered_out(self):
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(9, 45)

        # Event before candidate
        e_early = make_native_liquidity_event("EVT-EARLY", available_at=make_tz_datetime(9, 15), trigger_candle_id="c_2")
        # Event after as_of_time (future lookahead)
        e_late = make_native_liquidity_event("EVT-LATE", available_at=make_tz_datetime(9, 50), trigger_candle_id="c_12")

        s, r, code = pair_sweep_and_reclaim_events(
            target_pool_id="POOL_1",
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            events=[e_early, e_late],
        )
        assert code == "NO_ELIGIBLE_SWEEP_EVENT"


# ============================================================================
# SUITE 5: DEALING RANGE GEOMETRY & RAW SPOT PRECISION
# ============================================================================

class TestDealingRangeAndEquilibrium:

    def test_raw_spot_float_equilibrium_preserved(self):
        high = 24185.35
        low = 23912.10
        eq, delta_r, band = calculate_equilibrium(high, low, tick_size=0.05)
        assert eq == 24048.725
        assert delta_r == 273.25
        # Neutral band: max(2 * 0.05, 273.25 * 0.0010) = max(0.10, 0.27325) = 0.27325
        assert round(band, 5) == 0.27325

    def test_invalid_range_bounds_raise_value_error(self):
        with pytest.raises(ValueError):
            calculate_equilibrium(24000.0, 24000.0)
        with pytest.raises(ValueError):
            calculate_equilibrium(23900.0, 24000.0)

    def test_zone_classification_all_seven_zones(self):
        high = 24100.0
        low = 23900.0
        eq = 24000.0
        delta_r = 200.0
        band = 0.20  # neutral band: [23999.80, 24000.20]

        # Below Range: < 23900
        assert classify_zone(23890.0, high, low, eq, delta_r, band) == ZoneClassification.BELOW_RANGE
        # Deep Discount: [23900, 23950)
        assert classify_zone(23910.0, high, low, eq, delta_r, band) == ZoneClassification.DEEP_DISCOUNT
        # Discount: [23950, 23999.80)
        assert classify_zone(23970.0, high, low, eq, delta_r, band) == ZoneClassification.DISCOUNT
        # Equilibrium: [23999.80, 24000.20]
        assert classify_zone(24000.0, high, low, eq, delta_r, band) == ZoneClassification.EQUILIBRIUM
        # Premium: (24000.20, 24050]
        assert classify_zone(24030.0, high, low, eq, delta_r, band) == ZoneClassification.PREMIUM
        # Deep Premium: (24050, 24100]
        assert classify_zone(24080.0, high, low, eq, delta_r, band) == ZoneClassification.DEEP_PREMIUM
        # Above Range: > 24100
        assert classify_zone(24110.0, high, low, eq, delta_r, band) == ZoneClassification.ABOVE_RANGE

    def test_bullish_range_expansion_and_invalidation(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0)
        sl = make_native_swing_point("SL-1", "LOW", 23900.0)
        t = make_tz_datetime(9, 30)

        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, t)
        assert rng.status == DealingRangeStatus.ACTIVE

        # Pro-trend close above Range High -> EXPANDING_TRANSITION
        rng_exp = engine.evaluate_dealing_range_lifecycle(rng, candle_close=24105.0, candle_high=24110.0, candle_low=24090.0, as_of_time=t, bars_since_start=10)
        assert rng_exp.status == DealingRangeStatus.EXPANDING_TRANSITION

        # Opposing close below Range Low -> INVALIDATED
        rng_inv = engine.evaluate_dealing_range_lifecycle(rng, candle_close=23895.0, candle_high=23950.0, candle_low=23890.0, as_of_time=t, bars_since_start=10)
        assert rng_inv.status == DealingRangeStatus.INVALIDATED

    def test_bearish_range_expansion_and_invalidation(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0)
        sl = make_native_swing_point("SL-1", "LOW", 23900.0)
        t = make_tz_datetime(9, 30)

        rng = engine.create_dealing_range(sh, sl, EventDirection.BEARISH, t)
        assert rng.status == DealingRangeStatus.ACTIVE

        # Pro-trend close below Range Low -> EXPANDING_TRANSITION
        rng_exp = engine.evaluate_dealing_range_lifecycle(rng, candle_close=23895.0, candle_high=23950.0, candle_low=23890.0, as_of_time=t, bars_since_start=10)
        assert rng_exp.status == DealingRangeStatus.EXPANDING_TRANSITION

        # Opposing close above Range High -> INVALIDATED
        rng_inv = engine.evaluate_dealing_range_lifecycle(rng, candle_close=24105.0, candle_high=24110.0, candle_low=24090.0, as_of_time=t, bars_since_start=10)
        assert rng_inv.status == DealingRangeStatus.INVALIDATED

    def test_wick_beyond_boundary_keeps_range_active(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0)
        sl = make_native_swing_point("SL-1", "LOW", 23900.0)
        t = make_tz_datetime(9, 30)
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, t)

        # High wicked to 24105, but closed inside at 24090
        rng_wick = engine.evaluate_dealing_range_lifecycle(rng, candle_close=24090.0, candle_high=24105.0, candle_low=24050.0, as_of_time=t, bars_since_start=10)
        assert rng_wick.status == DealingRangeStatus.ACTIVE

    def test_successor_range_replaces_expanding_range(self):
        engine = PremiumDiscountEngine()
        sh1 = make_native_swing_point("SH-1", "HIGH", 24100.0)
        sl1 = make_native_swing_point("SL-1", "LOW", 23900.0)
        t = make_tz_datetime(9, 30)
        rng1 = engine.create_dealing_range(sh1, sl1, EventDirection.BULLISH, t)
        rng_exp = engine.evaluate_dealing_range_lifecycle(rng1, candle_close=24105.0, candle_high=24110.0, candle_low=24090.0, as_of_time=t, bars_since_start=10)

        sh2 = make_native_swing_point("SH-2", "HIGH", 24200.0)
        sl2 = make_native_swing_point("SL-2", "LOW", 24050.0)
        rng_repl = engine.evaluate_dealing_range_lifecycle(rng_exp, candle_close=24150.0, candle_high=24200.0, candle_low=24050.0, as_of_time=t, bars_since_start=20, successor_high=sh2, successor_low=sl2)

        assert rng_repl.status == DealingRangeStatus.REPLACED
        assert rng_repl.successor_range_id is not None


# ============================================================================
# SUITE 6: CANDIDATE-TO-POOL IDENTITY MATCHING
# ============================================================================

class TestCandidateToPoolMatching:

    def test_matching_by_candle_id(self):
        cand = make_native_swing_point("SWI-CAND", "LOW", 24000.0, candle_id="c_14")
        pool = make_native_liquidity_pool("POOL_1", level=24000.0, source_candle_ids=["c_14"])

        matched, code = match_candidate_to_pools(cand, [pool])
        assert matched == pool
        assert code == "LINKED"

    def test_matching_by_swing_id(self):
        cand = make_native_swing_point("SWI-CAND", "LOW", 24000.0, candle_id="c_99")
        pool = make_native_liquidity_pool("POOL_1", level=24000.0, source_candle_ids=["c_14"], source_swing_ids=["SWI-CAND"])

        matched, code = match_candidate_to_pools(cand, [pool])
        assert matched == pool
        assert code == "LINKED"

    def test_zero_matches_unlinked_candidate(self):
        cand = make_native_swing_point("SWI-CAND", "LOW", 24000.0, candle_id="c_99")
        pool = make_native_liquidity_pool("POOL_1", level=24000.0, source_candle_ids=["c_14"], source_swing_ids=["SWI-OTHER"])

        matched, code = match_candidate_to_pools(cand, [pool])
        assert matched is None
        assert code == "UNLINKED_CANDIDATE"

    def test_multiple_matches_unresolved_ambiguity(self):
        cand = make_native_swing_point("SWI-CAND", "LOW", 24000.0, candle_id="c_14")
        p1 = make_native_liquidity_pool("POOL_1", level=24000.0, source_candle_ids=["c_14"])
        p2 = make_native_liquidity_pool("POOL_2", level=24000.0, source_candle_ids=["c_14"])

        matched, code = match_candidate_to_pools(cand, [p1, p2])
        assert matched is None
        assert code == "FAIL_CLOSED_UNRESOLVED_AMBIGUITY"

    def test_price_tolerance_exceeded_fails_closed(self):
        cand = make_native_swing_point("SWI-CAND", "LOW", 24000.50, candle_id="c_14")
        pool = make_native_liquidity_pool("POOL_1", level=24000.0, source_candle_ids=["c_14"])

        matched, code = match_candidate_to_pools(cand, [pool], tolerance_pts=0.10)
        assert matched is None
        assert code == "REJECTED_PRICE_TOLERANCE_EXCEEDED"


# ============================================================================
# SUITE 7: INDUCEMENT 7-STAGE PROGRESSION (ANTI-BYPASS)
# ============================================================================

class TestInducementSevenStageProgression:

    def test_candidate_outside_range_rejected(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0)
        sl = make_native_swing_point("SL-1", "LOW", 23900.0)
        t = make_tz_datetime(9, 30)
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, t)

        cand_out = make_native_swing_point("CAND-1", "LOW", 23850.0)
        status, ind_ev, trans, code = engine.evaluate_inducement_progression(
            candidate=cand_out,
            dealing_range=rng,
            pools=[],
            liquidity_events=[],
            structure_events=[],
            as_of_time=t,
        )
        assert status == InducementStatus.INVALIDATED
        assert code == "FAIL_CLOSED_CANDIDATE_OUTSIDE_RANGE"

    def test_anti_bypass_direct_jump_prevented(self):
        """Verifies that an inducement cannot jump to CONFIRMED without prior stages."""
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0)
        sl = make_native_swing_point("SL-1", "LOW", 23900.0)
        t = make_tz_datetime(9, 30)
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, t)

        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10")
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])

        # No sweep or reclaim events provided
        status, ind_ev, trans, code = engine.evaluate_inducement_progression(
            candidate=cand,
            dealing_range=rng,
            pools=[pool],
            liquidity_events=[],
            structure_events=[],
            as_of_time=t,
        )
        assert status == InducementStatus.CANDIDATE
        assert ind_ev is None
        assert code == "AWAITING_SWEEP_EVENT"

    def test_full_seven_stage_linear_confirmation(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        t_start = make_tz_datetime(9, 20)
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, t_start)

        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 22))
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])

        # Stage 2 & 3: Sweep and Reclaim
        t_sweep = make_tz_datetime(9, 25)
        sweep = make_native_liquidity_event("EVT-SWP", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=t_sweep, trigger_candle_id="c_11")
        t_rec = make_tz_datetime(9, 30)
        reclaim = make_native_liquidity_event("EVT-REC", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=t_rec, trigger_candle_id="c_12", is_reclaimed=True)

        # Target swing high to be broken
        target_swing = make_native_swing_point("SWI-TARGET-HIGH", "HIGH", 24020.0, available_at=make_tz_datetime(9, 24))

        # Stage 5: Displacement event (empirical ATR=22.0, distinct from Step 3.2 fallback 10.0)
        t_disp = make_tz_datetime(9, 32)
        disp_ev = MarketStructureEvent(
            event_id="EVT-DISP",
            index="NIFTY 50",
            event_type=ICTEventType.MSS,
            direction=EventDirection.BULLISH,
            timeframe="15m",
            broken_level=24020.0,
            event_time=t_disp,
            available_at=t_disp,
            created_at=t_disp,
            confirmed_at=t_disp,
            source_candle_identifiers=["c_13"],
            evidence=MarketStructureEvidence(
                broken_level=24020.0,
                broken_swing_id="SWI-TARGET-HIGH",
                broken_swing_type="HIGH",
                broken_swing_time=make_tz_datetime(9, 24),
                break_candle_id="c_13",
                break_candle_time=t_disp,
                break_candle_open=24000.0,
                break_candle_high=24030.0,
                break_candle_low=23998.0,
                break_candle_close=24025.0,
                penetration_depth_pts=5.0,
                displacement_confirmed=True,
                body_to_range_ratio=0.65,
                atr=22.0,
                atr_multiple=1.4,
            ),
            status="CONFIRMED",
            configuration_version="3.2.0",
            engine_version="3.2.0",
        )

        t_as_of = make_tz_datetime(9, 35)

        status, ind_ev, trans, code = engine.evaluate_inducement_progression(
            candidate=cand,
            dealing_range=rng,
            pools=[pool],
            liquidity_events=[sweep, reclaim],
            structure_events=[disp_ev],
            as_of_time=t_as_of,
            available_swings=[sh, sl, cand, target_swing],
            atr_provenance={
                "EVT-DISP": ATRProvenance(
                    atr_status=ATRProvenanceStatus.CALCULATED,
                    is_fallback_atr=False,
                    period=14,
                    series_length=50,
                    source="STEP3_2_ROLLING_TR",
                )
            },
        )

        assert status == InducementStatus.CONFIRMED
        assert ind_ev is not None
        assert ind_ev.event_id.startswith("EVT-IDM-")
        assert ind_ev.trigger_candle_id == "c_13"
        assert ind_ev.evidence.displacement_atr == 22.0
        assert code == "INDUCEMENT_CONFIRMED_SUCCESS"
        assert len(trans) == 5  # SWEPT, RECLAIMED, DISPLACED, STRUCTURALLY_CONFIRMED, CONFIRMED
        assert [t_rec.trigger_candle_id for t_rec in trans] == ["c_11", "c_12", "c_13", "c_13", "c_13"]


# ============================================================================
# SUITE 8: MULTI-TIMEFRAME CONFLUENCE (UNAVAILABLE / NOT CALIBRATED)
# ============================================================================

class TestMultiTimeframeAndConfluence:

    def test_confluence_score_remains_unavailable_and_unweighted(self):
        engine = PremiumDiscountEngine()
        t = make_tz_datetime(10, 0)

        rep_1h = TimeframePremiumDiscountReport(
            index="NIFTY 50", timeframe="1H", as_of_time=t,
            timeframe_bias="BULLISH", current_price=24000.0, configuration_fingerprint="FP",
        )
        rep_15m = TimeframePremiumDiscountReport(
            index="NIFTY 50", timeframe="15M", as_of_time=t,
            timeframe_bias="BULLISH", current_price=24000.0, configuration_fingerprint="FP",
        )
        rep_5m = TimeframePremiumDiscountReport(
            index="NIFTY 50", timeframe="5M", as_of_time=t,
            timeframe_bias="BULLISH", current_price=24000.0, configuration_fingerprint="FP",
        )
        rep_3m = TimeframePremiumDiscountReport(
            index="NIFTY 50", timeframe="3M", as_of_time=t,
            timeframe_bias="NEUTRAL", current_price=24000.0, configuration_fingerprint="FP",
        )
        rep_1m = TimeframePremiumDiscountReport(
            index="NIFTY 50", timeframe="1M", as_of_time=t,
            timeframe_bias="NEUTRAL", current_price=24000.0, configuration_fingerprint="FP",
        )

        reports = {"1H": rep_1h, "15M": rep_15m, "5M": rep_5m, "3M": rep_3m, "1M": rep_1m}
        conf = engine.evaluate_multi_timeframe_confluence(reports, t)

        assert conf.timeframe_weights == {}
        assert conf.composite_confluence_score is None
        assert conf.score_status == "UNAVAILABLE"
        assert conf.calibration_status == "NOT_CALIBRATED"
        assert conf.primary_bias == "BULLISH"
        assert conf.recommended_action == "NO_TRADE"
        assert conf.alignment_summary["status"] == "UNAVAILABLE"
        assert conf.alignment_summary["calibration_status"] == "NOT_CALIBRATED"
        assert conf.alignment_summary["bullish_timeframes"] == 3
        assert conf.execution_mode == "PAPER_TRADING_ONLY"


# ============================================================================
# SUITE 9: DETERMINISM & NO-LOOKAHEAD VERIFICATION
# ============================================================================

class TestDeterminismAndNoLookahead:

    def test_canonical_preprocessing_and_fingerprint_reproducibility(self):
        cfg1 = DealingRangeConfiguration(tick_size=0.05, max_lookback_bars=300)
        cfg2 = DealingRangeConfiguration(tick_size=0.05, max_lookback_bars=300)
        h1 = compute_step3_5_fingerprint(cfg1)
        h2 = compute_step3_5_fingerprint(cfg2)
        assert h1 == h2
        assert len(h1) == 64

    def test_dealing_range_id_reproducible(self):
        t = make_tz_datetime(9, 15)
        id1 = generate_dealing_range_id("NIFTY 50", "15m", EventDirection.BULLISH, 24100.0, 23900.0, t, "SH-1", "SL-1", "FPRINT")
        id2 = generate_dealing_range_id("NIFTY 50", "15m", EventDirection.BULLISH, 24100.0, 23900.0, t, "SH-1", "SL-1", "FPRINT")
        assert id1 == id2
        assert id1.startswith("RNG-")

    def test_no_future_candle_leakage(self):
        engine = PremiumDiscountEngine()
        t_as_of = make_tz_datetime(9, 30)

        # Past swings
        sh_past = make_native_swing_point("SH-P", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl_past = make_native_swing_point("SL-P", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))

        # Future swing (after as_of_time)
        sh_future = make_native_swing_point("SH-F", "HIGH", 24300.0, available_at=make_tz_datetime(9, 45))

        rep = engine.analyze_timeframe(
            index="NIFTY 50",
            timeframe="15m",
            current_price=24000.0,
            swings=[sh_past, sl_past, sh_future],
            pools=[],
            liquidity_events=[],
            structure_events=[],
            as_of_time=t_as_of,
        )

        assert rep.active_dealing_range is not None
        # Must reference past swings only
        assert rep.active_dealing_range.high_swing_id == "SH-P"
        assert rep.active_dealing_range.high_price == 24100.0
        assert rep.timeframe_confluence_score is None
        assert rep.score_status == "UNAVAILABLE"
        assert rep.calibration_status == "NOT_CALIBRATED"

    def test_parameter_precedence_over_snapshot_integrity(self):
        """Parameter guards must execute before snapshot integrity checks."""
        t_cand = make_tz_datetime(9, 20)
        t_as_of = make_tz_datetime(10, 0)

        # Invalid target_pool_id with malformed snapshot collection
        s, r, code = pair_validated_event_snapshots(
            target_pool_id="",  # invalid
            candidate_available_at=t_cand,
            as_of_time=t_as_of,
            snapshots="NOT_A_LIST",  # also invalid
        )
        assert code == "FAIL_CLOSED_INVALID_TARGET_POOL_ID"

    def test_exception_raising_float_subclass_caught_safely(self):
        """Custom float subclass whose __float__ raises RuntimeError is caught and marked INVALID_VALUE."""
        class RaisingFloat(float):
            def __float__(self):
                raise RuntimeError("Malicious float conversion fault")

        e = make_native_liquidity_event()
        rf = RaisingFloat(0.40)
        object.__setattr__(e.evidence, "rejection_wick_ratio", rf)
        snap = capture_and_normalize_evidence(e)
        assert snap.wick_ratio_status == "INVALID_VALUE"
        assert snap.normalized_wick_ratio is None

    def test_preprocess_canonical_input_key_collision_raises(self):
        """preprocess_canonical_input detects whitespace key collisions."""
        payload = {"param": 1, " param ": 2}
        with pytest.raises(ValueError, match="Dictionary key collision detected"):
            preprocess_canonical_input(payload)

    def test_preprocess_canonical_input_naive_datetime_raises(self):
        """preprocess_canonical_input rejects naive datetimes."""
        payload = {"timestamp": datetime(2026, 11, 10, 9, 15)}
        with pytest.raises(ValueError, match="Naive datetime"):
            preprocess_canonical_input(payload)

    def test_unapproved_min_range_pts_removed_allows_positive_range(self):
        """Unapproved min_range_pts cutoff is removed; any finite range with high > low is accepted."""
        assert "min_range_pts" not in DealingRangeConfiguration.model_fields
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24005.0)
        sl = make_native_swing_point("SL-1", "LOW", 24000.0)  # delta = 5.0
        t = make_tz_datetime(9, 30)
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, t)
        assert rng.delta_r == 5.0
        assert rng.equilibrium_price == 24002.5

    def test_expanding_range_opposing_close_invalidates(self):
        """Opposing close while in EXPANDING_TRANSITION terminates immediately to INVALIDATED."""
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0)
        sl = make_native_swing_point("SL-1", "LOW", 23900.0)
        t = make_tz_datetime(9, 30)
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, t)
        rng_exp = engine.evaluate_dealing_range_lifecycle(rng, candle_close=24105.0, candle_high=24110.0, candle_low=24090.0, as_of_time=t, bars_since_start=10)
        assert rng_exp.status == DealingRangeStatus.EXPANDING_TRANSITION

        # Next bar experiences an catastrophic opposing drop below Range Low
        rng_inv = engine.evaluate_dealing_range_lifecycle(rng_exp, candle_close=23890.0, candle_high=24000.0, candle_low=23880.0, as_of_time=t, bars_since_start=11)
        assert rng_inv.status == DealingRangeStatus.INVALIDATED
        assert rng_inv.invalidation_reason == "OPPOSING_CLOSE_BELOW_RANGE_LOW"

    def test_directional_candidate_type_mismatch_fails_closed(self):
        """Bullish range rejects HIGH candidate; Bearish range rejects LOW candidate."""
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0)
        sl = make_native_swing_point("SL-1", "LOW", 23900.0)
        t = make_tz_datetime(9, 30)

        # Bullish range
        rng_bull = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, t)
        cand_high = make_native_swing_point("CAND-HIGH", "HIGH", 24050.0)
        status, ind_ev, trans, code = engine.evaluate_inducement_progression(
            candidate=cand_high, dealing_range=rng_bull, pools=[], liquidity_events=[], structure_events=[], as_of_time=t,
        )
        assert status == InducementStatus.INVALIDATED
        assert code == "FAIL_CLOSED_DIRECTIONAL_TYPE_MISMATCH"

        # Bearish range
        rng_bear = engine.create_dealing_range(sh, sl, EventDirection.BEARISH, t)
        cand_low = make_native_swing_point("CAND-LOW", "LOW", 23950.0)
        status, ind_ev, trans, code = engine.evaluate_inducement_progression(
            candidate=cand_low, dealing_range=rng_bear, pools=[], liquidity_events=[], structure_events=[], as_of_time=t,
        )
        assert status == InducementStatus.INVALIDATED
        assert code == "FAIL_CLOSED_DIRECTIONAL_TYPE_MISMATCH"


# ============================================================================
# SUITE 10: STEP 3.5 GOVERNANCE REMEDIATION, ATR PROVENANCE & CAUSALITY GUARDS
# ============================================================================

def _make_structure_event(
    event_id: str = "EVT-DISP",
    event_type: ICTEventType = ICTEventType.MSS,
    direction: EventDirection = EventDirection.BULLISH,
    index: str = "NIFTY 50",
    timeframe: str = "15m",
    broken_swing_id: str = "SWI-TARGET-HIGH",
    broken_swing_type: str = "HIGH",
    broken_level: float = 24020.0,
    broken_swing_time: Optional[datetime] = None,
    break_candle_id: str = "c_13",
    available_at: Optional[datetime] = None,
    displacement_confirmed: bool = True,
    body_to_range_ratio: float = 0.65,
    atr: Optional[float] = 22.0,
    atr_multiple: Optional[float] = 1.4,
) -> MarketStructureEvent:
    t_avail = available_at or make_tz_datetime(9, 32)
    t_sw = broken_swing_time or make_tz_datetime(9, 24)
    return MarketStructureEvent(
        event_id=event_id,
        index=index,
        event_type=event_type,
        direction=direction,
        timeframe=timeframe,
        broken_level=broken_level,
        event_time=t_avail,
        available_at=t_avail,
        created_at=t_avail,
        confirmed_at=t_avail,
        source_candle_identifiers=[break_candle_id],
        evidence=MarketStructureEvidence(
            broken_level=broken_level,
            broken_swing_id=broken_swing_id,
            broken_swing_type=broken_swing_type,
            broken_swing_time=t_sw,
            break_candle_id=break_candle_id,
            break_candle_time=t_avail,
            break_candle_open=24000.0,
            break_candle_high=24030.0,
            break_candle_low=23998.0,
            break_candle_close=24025.0,
            penetration_depth_pts=5.0,
            displacement_confirmed=displacement_confirmed,
            body_to_range_ratio=body_to_range_ratio,
            atr=atr,
            atr_multiple=atr_multiple,
        ),
        configuration_version="3.2.0",
        engine_version="3.2.0",
    )


def _calc_provenance(*event_ids: str) -> dict:
    """Explicit calculated ATR provenance mapping for test events."""
    return {
        ev_id: ATRProvenance(
            atr_status=ATRProvenanceStatus.CALCULATED,
            is_fallback_atr=False,
            period=14,
            series_length=50,
            source="STEP3_2_ROLLING_TR",
        )
        for ev_id in event_ids
    }


class TestGovernanceRemediationAndHardening:

    def test_approved_config_defaults_and_unapproved_fields_removed(self):
        dcfg = DealingRangeConfiguration()
        icfg = InducementConfiguration()
        assert "min_range_pts" not in DealingRangeConfiguration.model_fields
        assert "max_inducement_window_bars" not in InducementConfiguration.model_fields
        assert not hasattr(dcfg, "min_range_pts")
        assert not hasattr(icfg, "max_inducement_window_bars")
        assert icfg.min_sweep_penetration_pts == 1.5
        assert icfg.min_rejection_wick_ratio == 0.35
        assert icfg.min_displacement_body_ratio == 0.50
        assert icfg.min_displacement_atr_multiple == 1.0

    def test_sweep_penetration_below_1_5_rejected_and_1_5_accepted(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, make_tz_datetime(9, 20))
        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 22))
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])
        reclaim = make_native_liquidity_event("EVT-REC", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_12", is_reclaimed=True)
        disp = _make_structure_event()
        t_as_of = make_tz_datetime(9, 35)
        prov = _calc_provenance("EVT-DISP")

        # Below Step 3.1 approved 1.5 -> fails closed
        sweep_low = make_native_liquidity_event("EVT-SWP-LOW", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11", penetration_depth_pts=1.4)
        status, ev, _, code = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep_low, reclaim], [disp], t_as_of, atr_provenance=prov,
        )
        assert status == InducementStatus.INVALIDATED
        assert ev is None
        assert code == "FAIL_CLOSED_INSUFFICIENT_SWEEP_PENETRATION"

        # Exactly 1.5 -> passes Stage 2 & confirms full progression
        sweep_exact = make_native_liquidity_event("EVT-SWP-EXACT", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11", penetration_depth_pts=1.5)
        status2, ev2, _, code2 = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep_exact, reclaim], [disp], t_as_of, atr_provenance=prov,
        )
        assert status2 == InducementStatus.CONFIRMED
        assert ev2 is not None
        assert code2 == "INDUCEMENT_CONFIRMED_SUCCESS"

    def test_genuine_atr_10_0_with_calculated_provenance_accepted(self):
        """Genuine calculated ATR == 10.0 must be accepted when explicit calculated provenance is established."""
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, make_tz_datetime(9, 20))
        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 22))
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])
        sweep = make_native_liquidity_event("EVT-SWP", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11")
        reclaim = make_native_liquidity_event("EVT-REC", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_12", is_reclaimed=True)
        disp_calc_10 = _make_structure_event(atr=10.0, atr_multiple=1.6)
        t_as_of = make_tz_datetime(9, 35)

        # 1. Explicit ATRProvenance object in mapping
        st1, ev1, trans1, c1 = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [disp_calc_10], t_as_of,
            atr_provenance=_calc_provenance("EVT-DISP"),
        )
        assert st1 == InducementStatus.CONFIRMED
        assert ev1 is not None and ev1.evidence.displacement_atr == 10.0
        assert c1 == "INDUCEMENT_CONFIRMED_SUCCESS"
        disp_trn = [tr for tr in trans1 if tr.to_stage == "DISPLACED"][0]
        assert disp_trn.transition_evidence["atr_provenance"] == "CALCULATED"

        # 2. Dict provenance mapping with COMPUTED status
        st2, ev2, _, c2 = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [disp_calc_10], t_as_of,
            atr_provenance={"EVT-DISP": {"atr_status": "COMPUTED", "is_fallback_atr": False, "period": 14}},
        )
        assert st2 == InducementStatus.CONFIRMED
        assert ev2 is not None and ev2.evidence.displacement_atr == 10.0
        assert c2 == "INDUCEMENT_CONFIRMED_SUCCESS"

        # 3. Direct attribute metadata attached to MarketStructureEvidence
        disp_attr = _make_structure_event(event_id="EVT-DISP-ATTR", atr=10.0, atr_multiple=1.5)
        object.__setattr__(disp_attr.evidence, "atr_status", "CALCULATED")
        object.__setattr__(disp_attr.evidence, "is_fallback_atr", False)
        st3, ev3, _, c3 = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [disp_attr], t_as_of,
        )
        assert st3 == InducementStatus.CONFIRMED
        assert ev3 is not None and ev3.evidence.displacement_atr == 10.0
        assert c3 == "INDUCEMENT_CONFIRMED_SUCCESS"

    @pytest.mark.parametrize("atr_val", [10.0, 22.0])
    @pytest.mark.parametrize("bad_meta", [
        ATRProvenance(atr_status=ATRProvenanceStatus.FALLBACK, is_fallback_atr=True),
        ATRProvenance(atr_status=ATRProvenanceStatus.UNAVAILABLE, is_fallback_atr=False),
        {"atr_status": "FALLBACK", "is_fallback_atr": False},
        {"atr_status": "UNAVAILABLE"},
        {"atr_status": "CALCULATED", "is_fallback_atr": True},
        "FALLBACK",
        "UNAVAILABLE",
    ])
    def test_explicit_fallback_or_unavailable_atr_rejected_regardless_of_value(self, atr_val, bad_meta):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, make_tz_datetime(9, 20))
        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 22))
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])
        sweep = make_native_liquidity_event("EVT-SWP", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11")
        reclaim = make_native_liquidity_event("EVT-REC", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_12", is_reclaimed=True)
        disp = _make_structure_event(atr=atr_val)

        status, ind_ev, _, code = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [disp], make_tz_datetime(9, 35),
            atr_provenance={"EVT-DISP": bad_meta},
        )
        assert status == InducementStatus.INVALIDATED
        assert ind_ev is None
        assert code == "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE"

        # Attribute-level fallback also rejects even if mapping claimed CALCULATED
        disp_conflict = _make_structure_event(atr=atr_val)
        object.__setattr__(disp_conflict.evidence, "is_fallback_atr", True)
        st2, ev2, _, code2 = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [disp_conflict], make_tz_datetime(9, 35),
            atr_provenance=_calc_provenance("EVT-DISP"),
        )
        assert st2 == InducementStatus.INVALIDATED
        assert ev2 is None
        assert code2 == "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE"

    @pytest.mark.parametrize("atr_val", [10.0, 22.0])
    @pytest.mark.parametrize("unknown_or_missing_prov", [
        None,
        {},
        {"EVT-OTHER": {"atr_status": "CALCULATED"}},
        {"EVT-DISP": {"atr_status": "UNKNOWN"}},
        {"EVT-DISP": {"atr_status": ""}},
        {"EVT-DISP": {"atr_status": "   "}},
        {"EVT-DISP": {"atr_status": "DEFAULT"}},
        {"EVT-DISP": {"atr_status": "LEGACY"}},
        {"EVT-DISP": {"is_fallback_atr": False}},
        {"EVT-DISP": {"atr_status": "CALCULATED", "is_fallback_atr": "false"}},
        {"EVT-DISP": {"atr_status": "CALCULATED", "period": 0}},
        {"EVT-DISP": "UNKNOWN"},
        "NOT_A_DICT",
    ])
    def test_missing_or_unknown_atr_provenance_fails_closed(self, atr_val, unknown_or_missing_prov):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, make_tz_datetime(9, 20))
        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 22))
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])
        sweep = make_native_liquidity_event("EVT-SWP", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11")
        reclaim = make_native_liquidity_event("EVT-REC", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_12", is_reclaimed=True)
        disp = _make_structure_event(atr=atr_val)

        status, ind_ev, _, code = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [disp], make_tz_datetime(9, 35),
            atr_provenance=unknown_or_missing_prov,
        )
        assert status == InducementStatus.INVALIDATED
        assert ind_ev is None
        assert code == "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE"

    def test_faulty_str_in_atr_provenance_fails_closed_without_invoking_strip(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, make_tz_datetime(9, 20))
        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 22))
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])
        sweep = make_native_liquidity_event("EVT-SWP", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11")
        reclaim = make_native_liquidity_event("EVT-REC", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_12", is_reclaimed=True)
        disp = _make_structure_event(atr=10.0)

        st, ind_ev, _, code = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [disp], make_tz_datetime(9, 35),
            atr_provenance={"EVT-DISP": FaultyStr("CALCULATED")},
        )
        assert st == InducementStatus.INVALIDATED
        assert ind_ev is None
        assert code == "FAIL_CLOSED_ATR_PROVENANCE_UNAVAILABLE"

    @pytest.mark.parametrize("bad_atr", [None, 0.0, -4.5, float("nan"), float("inf"), float("-inf"), "BOOL_TRUE"])
    def test_displacement_invalid_atr_fails_closed(self, bad_atr):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, make_tz_datetime(9, 20))
        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 22))
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])
        sweep = make_native_liquidity_event("EVT-SWP", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11")
        reclaim = make_native_liquidity_event("EVT-REC", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_12", is_reclaimed=True)
        if bad_atr == "BOOL_TRUE":
            disp = _make_structure_event(atr=22.0)
            object.__setattr__(disp.evidence, "atr", True)
        else:
            disp = _make_structure_event(atr=bad_atr)

        # Invalid ATR rejected both without provenance and with explicit calculated provenance
        for prov in (None, _calc_provenance("EVT-DISP")):
            status, ind_ev, _, code = engine.evaluate_inducement_progression(
                cand, rng, [pool], [sweep, reclaim], [disp], make_tz_datetime(9, 35),
                atr_provenance=prov,
            )
            assert status == InducementStatus.INVALIDATED
            assert ind_ev is None
            assert code == "FAIL_CLOSED_INVALID_ATR_VALUE"

    def test_displacement_config_thresholds_enforced(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, make_tz_datetime(9, 20))
        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 22))
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])
        sweep = make_native_liquidity_event("EVT-SWP", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11")
        reclaim = make_native_liquidity_event("EVT-REC", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_12", is_reclaimed=True)
        prov = _calc_provenance("EVT-DISP")

        low_body = _make_structure_event(body_to_range_ratio=0.45, atr=22.0, atr_multiple=1.4)
        st1, _, _, code1 = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [low_body], make_tz_datetime(9, 35), atr_provenance=prov,
        )
        assert st1 == InducementStatus.INVALIDATED
        assert code1 == "FAIL_CLOSED_INSUFFICIENT_DISPLACEMENT_BODY_RATIO"

        low_atr_mult = _make_structure_event(body_to_range_ratio=0.65, atr=22.0, atr_multiple=0.8)
        st2, _, _, code2 = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [low_atr_mult], make_tz_datetime(9, 35), atr_provenance=prov,
        )
        assert st2 == InducementStatus.INVALIDATED
        assert code2 == "FAIL_CLOSED_INSUFFICIENT_DISPLACEMENT_ATR_MULTIPLE"

    def test_pairing_failure_codes_not_swallowed_in_progression(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, make_tz_datetime(9, 20))
        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 22))
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])
        sw1 = make_native_liquidity_event("EVT-SWP-1", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11")
        sw2 = make_native_liquidity_event("EVT-SWP-2", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 27), trigger_candle_id="c_12")

        status, ev, _, code = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sw1, sw2], [], make_tz_datetime(9, 35),
        )
        assert status == InducementStatus.INVALIDATED
        assert ev is None
        assert code == "FAIL_CLOSED_AMBIGUOUS_SWEEP_RECLAIM_PAIR"

    def test_stage6_cannot_precede_stage5_displacement_chronology(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, make_tz_datetime(9, 20))
        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 22))
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])
        sweep = make_native_liquidity_event("EVT-SWP", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11")
        reclaim = make_native_liquidity_event("EVT-REC", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_12", is_reclaimed=True)

        # Earlier non-displaced BOS at 09:31, displacement only later at 09:34 with empty broken_swing_id or later break absent
        early_bos = _make_structure_event(
            event_id="EVT-EARLY-BOS", event_type=ICTEventType.BOS, break_candle_id="c_13",
            available_at=make_tz_datetime(9, 31), displacement_confirmed=False, body_to_range_ratio=0.40, atr=22.0, atr_multiple=0.8,
        )
        # Note: if displaced_event itself lacks valid broken_swing_id on a non-break or different candle -> wait for valid break >= t_displaced
        later_disp = _make_structure_event(
            event_id="EVT-LATE-DISP", event_type=ICTEventType.MSS, break_candle_id="c_14",
            broken_swing_id="", available_at=make_tz_datetime(9, 34), displacement_confirmed=True, atr=22.0,
        )
        # Modify later_disp? Actually MSS with empty broken_swing_id fails Stage 6; test BOS before MSS separately:
        early_bos_valid = _make_structure_event(
            event_id="EVT-EARLY-BOS", event_type=ICTEventType.BOS, break_candle_id="c_13",
            available_at=make_tz_datetime(9, 31), displacement_confirmed=False, body_to_range_ratio=0.40, atr=22.0, atr_multiple=0.8,
        )
        later_disp_only = _make_structure_event(
            event_id="EVT-LATE-MSS", event_type=ICTEventType.MSS, break_candle_id="c_14",
            broken_swing_id="SWI-TARGET-HIGH", available_at=make_tz_datetime(9, 34), displacement_confirmed=True, atr=22.0,
        )
        status, ev, trans, code = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [early_bos_valid, later_disp_only], make_tz_datetime(9, 35),
            atr_provenance=_calc_provenance("EVT-LATE-MSS"),
        )
        assert status == InducementStatus.CONFIRMED
        assert ev is not None
        # Confirm break chosen is EVT-LATE-MSS at 09:34, NOT EVT-EARLY-BOS at 09:31!
        assert ev.evidence.structural_break_event_id == "EVT-LATE-MSS"
        assert ev.trigger_candle_id == "c_14"

        # If ONLY early BOS precedes a displaced event with no break at/after displacement: must fail closed rather than picking 09:31
        status_fc, ev_fc, _, code_fc = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [early_bos_valid, later_disp], make_tz_datetime(9, 35),
            atr_provenance=_calc_provenance("EVT-LATE-DISP"),
        )
        assert status_fc == InducementStatus.INVALIDATED
        assert ev_fc is None
        assert code_fc == "FAIL_CLOSED_BROKEN_SWING_CAUSALITY_VIOLATION"

    def test_broken_swing_causality_and_range_bounds_enforced(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, make_tz_datetime(9, 20))
        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 22))
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])
        sweep = make_native_liquidity_event("EVT-SWP", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11")
        reclaim = make_native_liquidity_event("EVT-REC", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_12", is_reclaimed=True)

        prov = _calc_provenance("EVT-DISP")

        # Out-of-range broken_level
        disp_out = _make_structure_event(broken_level=24250.0, atr=22.0)
        st1, _, _, c1 = engine.evaluate_inducement_progression(cand, rng, [pool], [sweep, reclaim], [disp_out], make_tz_datetime(9, 35), atr_provenance=prov)
        assert st1 == InducementStatus.INVALIDATED and c1 == "FAIL_CLOSED_BROKEN_SWING_CAUSALITY_VIOLATION"

        # broken_swing_time >= break.available_at
        disp_future_sw = _make_structure_event(broken_swing_time=make_tz_datetime(9, 32), available_at=make_tz_datetime(9, 32), atr=22.0)
        st2, _, _, c2 = engine.evaluate_inducement_progression(cand, rng, [pool], [sweep, reclaim], [disp_future_sw], make_tz_datetime(9, 35), atr_provenance=prov)
        assert st2 == InducementStatus.INVALIDATED and c2 == "FAIL_CLOSED_BROKEN_SWING_CAUSALITY_VIOLATION"

        # Wrong broken_swing_type ("LOW" on BULLISH setup)
        disp_wrong_type = _make_structure_event(broken_swing_type="LOW", atr=22.0)
        st3, _, _, c3 = engine.evaluate_inducement_progression(cand, rng, [pool], [sweep, reclaim], [disp_wrong_type], make_tz_datetime(9, 35), atr_provenance=prov)
        assert st3 == InducementStatus.INVALIDATED and c3 == "FAIL_CLOSED_BROKEN_SWING_CAUSALITY_VIOLATION"

    def test_equal_timestamp_break_different_candle_fails_closed(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        rng = engine.create_dealing_range(sh, sl, EventDirection.BULLISH, make_tz_datetime(9, 20))
        cand = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 22))
        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])
        sweep = make_native_liquidity_event("EVT-SWP", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11")
        reclaim = make_native_liquidity_event("EVT-REC", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_12", is_reclaimed=True)

        disp_ev = _make_structure_event(event_id="EVT-DISP", break_candle_id="c_13", available_at=make_tz_datetime(9, 32), atr=22.0)
        # Break event at exact same timestamp as displacement (09:32) but different break_candle_id ('c_14')
        conflict_brk = _make_structure_event(event_id="EVT-BRK", event_type=ICTEventType.BOS, break_candle_id="c_14", available_at=make_tz_datetime(9, 32), displacement_confirmed=False, atr=22.0)
        # First force Stage 6 past disp_ev if disp_ev lacked broken_swing_id: use disp_ev only for displacement via non-matching broken?
        # Equal timestamp with reclaim (09:30, 'c_12') on break ('c_13'):
        same_t_disp = _make_structure_event(event_id="EVT-D0", break_candle_id="c_13", available_at=make_tz_datetime(9, 30), atr=22.0)
        st, _, _, code = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [same_t_disp], make_tz_datetime(9, 35),
            atr_provenance=_calc_provenance("EVT-D0"),
        )
        assert st == InducementStatus.INVALIDATED
        assert code == "FAIL_CLOSED_EQUAL_TIMESTAMP_DIFFERENT_CANDLE_ID"

        # Equal timestamp between displaced event (09:32, c_13) and separate BOS (09:32, c_14) -> fails Stage 6!
        # Give disp_ev an ineligible swing type? No, conflict checked if BOS scanned or after disp_ev without swing break; let's verify clean equal-t break:
        st2, _, _, code2 = engine.evaluate_inducement_progression(
            cand, rng, [pool], [sweep, reclaim], [conflict_brk, disp_ev], make_tz_datetime(9, 35),
            atr_provenance=_calc_provenance("EVT-DISP"),
        )
        # Because loop encounters conflict_brk first at t_displaced==09:32 with c_14 != c_13
        assert st2 == InducementStatus.INVALIDATED
        assert code2 == "FAIL_CLOSED_EQUAL_TIMESTAMP_DIFFERENT_BREAK_CANDLE_ID"

    def test_no_lookahead_and_dimension_guards(self):
        engine = PremiumDiscountEngine()
        t_as_of = make_tz_datetime(9, 30)
        sh_ok = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 20))
        sl_future = make_native_swing_point("SL-F", "LOW", 23900.0, available_at=make_tz_datetime(9, 45))

        with pytest.raises(ValueError, match="future swings"):
            engine.create_dealing_range(sh_ok, sl_future, EventDirection.BULLISH, t_as_of)

        sl_ok = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 20))
        rng = engine.create_dealing_range(sh_ok, sl_ok, EventDirection.BULLISH, t_as_of)

        # Future candidate rejected in evaluate_inducement_progression
        cand_future = make_native_swing_point("CAND-F", "LOW", 23950.0, candle_id="c_20", available_at=make_tz_datetime(9, 40))
        st_f, _, _, c_f = engine.evaluate_inducement_progression(cand_future, rng, [], [], [], t_as_of)
        assert st_f == InducementStatus.INVALIDATED
        assert c_f == "FAIL_CLOSED_LOOKAHEAD_CANDIDATE"

        # Future HTF report rejected in evaluate_multi_timeframe_confluence
        rep_now = TimeframePremiumDiscountReport(
            index="NIFTY 50", timeframe="15M", as_of_time=t_as_of,
            timeframe_bias="BULLISH", current_price=24000.0, configuration_fingerprint="FP",
        )
        rep_future = TimeframePremiumDiscountReport(
            index="NIFTY 50", timeframe="1H", as_of_time=make_tz_datetime(10, 0),
            timeframe_bias="BULLISH", current_price=24000.0, configuration_fingerprint="FP",
        )
        with pytest.raises(ValueError, match="Lookahead violation"):
            engine.evaluate_multi_timeframe_confluence({"15M": rep_now, "1H": rep_future}, t_as_of)

    def test_analyze_timeframe_one_to_one_consumption_and_dimension_filter(self):
        engine = PremiumDiscountEngine()
        sh = make_native_swing_point("SH-1", "HIGH", 24100.0, available_at=make_tz_datetime(9, 24))
        sl = make_native_swing_point("SL-1", "LOW", 23900.0, available_at=make_tz_datetime(9, 23))
        # Foreign 1h high swing must NOT contaminate 15m dealing range
        sh_1h = make_native_swing_point("SH-1H", "HIGH", 24500.0, timeframe="1h", available_at=make_tz_datetime(9, 25))
        cand1 = make_native_swing_point("CAND-1", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 16))
        cand2 = make_native_swing_point("CAND-2", "LOW", 23950.0, candle_id="c_10", available_at=make_tz_datetime(9, 17))
        target_swing = make_native_swing_point("SWI-TARGET-HIGH", "HIGH", 24020.0, available_at=make_tz_datetime(9, 18))

        pool = make_native_liquidity_pool("POOL_1", level=23950.0, source_candle_ids=["c_10"])
        sweep = make_native_liquidity_event("EVT-SWP", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_SWEEP, available_at=make_tz_datetime(9, 25), trigger_candle_id="c_11")
        reclaim = make_native_liquidity_event("EVT-REC", pool_id="POOL_1", event_type=ICTEventType.LIQUIDITY_RECLAIM, available_at=make_tz_datetime(9, 30), trigger_candle_id="c_12", is_reclaimed=True)
        disp_ev = _make_structure_event(atr=22.0)

        rep = engine.analyze_timeframe(
            index="NIFTY 50",
            timeframe="15m",
            current_price=23960.0,
            swings=[sh, sl, sh_1h, cand1, cand2, target_swing],
            pools=[pool],
            liquidity_events=[sweep, reclaim],
            structure_events=[disp_ev],
            as_of_time=make_tz_datetime(9, 35),
            atr_provenance=_calc_provenance("EVT-DISP"),
        )
        assert rep.active_dealing_range is not None
        assert rep.active_dealing_range.high_price == 24100.0  # sh_1h ignored
        # Only ONE candidate may consume EVT-SWP and EVT-DISP
        assert len(rep.confirmed_inducements) == 1
        assert rep.timeframe_confluence_score is None
        assert rep.score_status == "UNAVAILABLE"
        assert rep.calibration_status == "NOT_CALIBRATED"

    def test_faulty_str_in_canonical_and_id_builders_fails_safely(self):
        class ThrowingStr(str):
            def strip(self, chars=None):
                raise RuntimeError("Should never invoke strip() on str subclass")
            def upper(self):
                raise RuntimeError("Should never invoke upper() on str subclass")
            def lower(self):
                raise RuntimeError("Should never invoke lower() on str subclass")

        fs = ThrowingStr("NIFTY 50")
        with pytest.raises(TypeError):
            preprocess_canonical_input(fs)
        with pytest.raises(TypeError):
            generate_dealing_range_id(fs, "15m", EventDirection.BULLISH, 24100.0, 23900.0, make_tz_datetime(9, 15), "SH", "SL", "FP")

    def test_pool_deduplication_and_conflict_handling(self):
        cand = make_native_swing_point("SWI-CAND", "LOW", 24000.0, candle_id="c_14")
        p1 = make_native_liquidity_pool("POOL_1", level=24000.0, source_candle_ids=["c_14"])
        p1_dup = make_native_liquidity_pool("POOL_1", level=24000.0, source_candle_ids=["c_14"])
        matched, code = match_candidate_to_pools(cand, [p1, p1_dup])
        assert matched == p1
        assert code == "LINKED"

        p1_conflict = make_native_liquidity_pool("POOL_1", level=24001.0, source_candle_ids=["c_14"])
        m2, code2 = match_candidate_to_pools(cand, [p1, p1_conflict])
        assert m2 is None
        assert code2 == "FAIL_CLOSED_UNRESOLVED_AMBIGUITY"

