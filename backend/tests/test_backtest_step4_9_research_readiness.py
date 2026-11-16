"""
AIVOLVE Phase 4, Step 4.9 — Final Research Readiness Gate & Market Observation Tests.

Covers:
1. WebSocket connected with 0 usable ticks NEVER marks READY / blocks live observation
2. WebSocket with verified usable ticks passes WS check (conditional observation only when no open P0 & exchange open)
3. Real Phase 1 P0 defect detection: token collision (99926017), _coerce_bool_flag('nan'),
   validate_tick gaps, /live/status API inconsistency, Upstox/AngelOne provider parity
4. Closed exchange fail-closed behavior
5. Strict anti-bypass & bottom-up classification enforcement
6. PAPER_TRADING_ONLY lock, SENSEX GOVERNANCE_LOCKED, ICT score UNAVAILABLE / NOT_CALIBRATED
7. Track separation: READY_FOR_OFFLINE_REPLAY vs BLOCKED_BY_P0 live vs INSUFFICIENT_EVIDENCE strategy
8. Controlled Friday 13 Nov 2026 observation runbook completeness & 4-step controlled fix protocol
9. Isolated SQLite round-trip, deterministic hash reproducibility, and 15-section Markdown rendering
10. 6-file protected persistence SHA-256 baseline integrity verification
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.backtesting import (
    DEFAULT_BACKTEST_DATA_DIR,
    DEFAULT_BACKTEST_DB_PATH,
    DEFAULT_OBSERVATION_SESSION_DATE,
    ICT_SCORE_GOVERNANCE_STATUS,
    CheckOutcome,
    DefectSeverity,
    LiveFeedObservationProbe,
    ReadinessClassification,
    ResearchReadinessConfig,
    ResearchReadinessEngine,
    ResearchReadinessReport,
    ResearchReadinessStore,
    StrategyEvidenceStore,
    generate_step4_9_readiness_markdown,
)
from app.backtesting.revalidation_report import verify_protected_persistence_hashes


@pytest.fixture()
def isolated_readiness_db() -> Path:
    import gc

    db_path = DEFAULT_BACKTEST_DATA_DIR / "_pytest_step4_9_readiness.db"
    if db_path.exists():
        db_path.unlink()
    try:
        yield db_path
    finally:
        gc.collect()
        if db_path.exists():
            db_path.unlink()


def test_ws_connected_zero_usable_ticks_never_ready():
    probe = LiveFeedObservationProbe(
        exchange_open=True,
        observation_session_date=DEFAULT_OBSERVATION_SESSION_DATE,
        session_is_scheduled_trading_day=True,
        rest_provider_name="angelone",
        rest_authenticated=True,
        websocket_connected=True,
        ticks_received=0,
        usable_verified_ticks=0,
        probe_source="INJECTED_SIMULATION",
    )
    engine = ResearchReadinessEngine(db_path=DEFAULT_BACKTEST_DB_PATH)
    # Even if code defects were hypothetically resolved, connected WS with 0 ticks MUST block live observation
    report = engine.evaluate(
        probe=probe,
        resolved_defect_ids=("P0-1", "P0-2", "P0-3", "P0-4", "P0-5", "P1-1", "P1-2"),
        persist=False,
    )
    ws_check = next(c for c in report.phase_audits[0].checks if c.check_id == "P1-WS-USABLE-TICKS")
    assert ws_check.outcome == CheckOutcome.FAIL
    assert "P0-WS-ZERO-TICKS" in {d.defect_id for d in report.defect_register}
    assert report.live_market_observation_classification == ReadinessClassification.BLOCKED_BY_P0
    assert report.overall_classification == ReadinessClassification.BLOCKED_BY_P0
    assert report.observation_plan.preconditions_met is False


def test_ws_with_usable_ticks_passes_when_no_open_p0_and_exchange_open():
    probe = LiveFeedObservationProbe(
        exchange_open=True,
        observation_session_date=DEFAULT_OBSERVATION_SESSION_DATE,
        session_is_scheduled_trading_day=True,
        rest_provider_name="angelone",
        rest_authenticated=True,
        websocket_connected=True,
        ticks_received=15,
        usable_verified_ticks=15,
        seconds_since_last_tick=1.5,
        probe_source="INJECTED_SIMULATION",
    )
    engine = ResearchReadinessEngine(db_path=DEFAULT_BACKTEST_DB_PATH)
    report = engine.evaluate(
        probe=probe,
        resolved_defect_ids=("P0-1", "P0-2", "P0-3", "P0-4", "P0-5"),
        persist=False,
    )
    ws_check = next(c for c in report.phase_audits[0].checks if c.check_id == "P1-WS-USABLE-TICKS")
    assert ws_check.outcome == CheckOutcome.PASS
    assert report.open_p0_count == 0
    assert report.live_market_observation_classification == ReadinessClassification.CONDITIONAL_PAPER_OBSERVATION
    assert report.observation_plan.preconditions_met is True
    assert report.strategy_evidence_classification == ReadinessClassification.INSUFFICIENT_EVIDENCE


def test_real_baseline_p0_defects_explicitly_detected():
    engine = ResearchReadinessEngine(db_path=DEFAULT_BACKTEST_DB_PATH)
    report = engine.evaluate(persist=False)

    defect_map = {d.defect_id: d for d in report.defect_register}
    assert {"P0-1", "P0-2", "P0-3", "P0-4", "P0-5"}.issubset(defect_map.keys())
    assert defect_map["P0-1"].severity == DefectSeverity.P0
    assert "99926017" in defect_map["P0-1"].observed_evidence
    assert "True" in defect_map["P0-3"].observed_evidence
    assert defect_map["P0-5"].severity == DefectSeverity.P0
    assert "P1-1" in defect_map and defect_map["P1-1"].severity == DefectSeverity.P1
    assert "P1-2" in defect_map and defect_map["P1-2"].severity == DefectSeverity.P1
    assert "P2-1" in defect_map and defect_map["P2-1"].severity == DefectSeverity.P2


def test_closed_exchange_fails_closed():
    probe = LiveFeedObservationProbe(
        exchange_open=False,
        observation_session_date=DEFAULT_OBSERVATION_SESSION_DATE,
        session_is_scheduled_trading_day=True,
        rest_provider_name="angelone",
        rest_authenticated=True,
        websocket_connected=True,
        ticks_received=25,
        usable_verified_ticks=25,
        seconds_since_last_tick=2.0,
        probe_source="INJECTED_SIMULATION",
    )
    engine = ResearchReadinessEngine(db_path=DEFAULT_BACKTEST_DB_PATH)
    report = engine.evaluate(
        probe=probe,
        resolved_defect_ids=("P0-1", "P0-2", "P0-3", "P0-4", "P0-5"),
        persist=False,
    )
    assert report.live_market_observation_classification == ReadinessClassification.BLOCKED_BY_P0
    assert report.observation_plan.preconditions_met is False
    assert any("closed" in r.lower() for r in report.observation_plan.blocking_reasons)


def test_cannot_bypass_p0_or_override_classification():
    with pytest.raises(ValueError, match="bypassed"):
        ResearchReadinessConfig(bypass_p0_gates=True)

    with pytest.raises(ValueError, match="override"):
        ResearchReadinessConfig(override_classification=ReadinessClassification.READY_FOR_HISTORICAL_RESEARCH)

    # Attempting to construct an inconsistent ResearchReadinessReport (open_p0 > 0 + CONDITIONAL live) must fail
    engine = ResearchReadinessEngine(db_path=DEFAULT_BACKTEST_DB_PATH)
    valid_report = engine.evaluate(persist=False)
    payload = valid_report.model_dump()
    payload["open_p0_count"] = 1
    payload["live_market_observation_classification"] = ReadinessClassification.CONDITIONAL_PAPER_OBSERVATION.value
    with pytest.raises(ValueError, match="open P0 defects"):
        ResearchReadinessReport.model_validate(payload)


def test_governance_locks_paper_mode_sensex_and_ict_score():
    engine = ResearchReadinessEngine(db_path=DEFAULT_BACKTEST_DB_PATH)
    report = engine.evaluate(persist=False)

    assert report.execution_mode == "PAPER_TRADING_ONLY"
    assert report.live_trading_authorized is False
    assert report.ict_score_status == ICT_SCORE_GOVERNANCE_STATUS
    p3_pillars = next(c for c in report.phase_audits[2].checks if c.check_id == "P3-8-PILLARS")
    assert p3_pillars.outcome == CheckOutcome.PASS

    sensex = next(i for i in report.instrument_decisions if i.instrument == "SENSEX")
    assert sensex.governance_locked is True
    assert sensex.historical_replay_classification == ReadinessClassification.GOVERNANCE_LOCKED
    assert sensex.live_observation_classification == ReadinessClassification.GOVERNANCE_LOCKED
    assert sensex.evidence_classification == ReadinessClassification.GOVERNANCE_LOCKED


def test_track_separation_offline_ready_vs_insufficient_evidence():
    engine = ResearchReadinessEngine(db_path=DEFAULT_BACKTEST_DB_PATH)
    report = engine.evaluate(persist=False)

    assert report.offline_historical_replay_classification == ReadinessClassification.READY_FOR_OFFLINE_REPLAY
    assert report.live_market_observation_classification == ReadinessClassification.BLOCKED_BY_P0
    assert report.strategy_evidence_classification == ReadinessClassification.INSUFFICIENT_EVIDENCE
    assert report.closed_trade_count_total == 5
    assert report.verified_matrix_combinations == 5
    assert report.partial_matrix_combinations == 13
    assert report.locked_matrix_combinations == 6
    assert report.missing_options_history_status == "OPTION_HISTORY_BLOCKED"

    nifty = next(i for i in report.instrument_decisions if i.instrument == "NIFTY 50")
    assert nifty.historical_replay_classification == ReadinessClassification.READY_FOR_OFFLINE_REPLAY
    assert nifty.live_observation_classification == ReadinessClassification.BLOCKED_BY_P0
    assert nifty.evidence_classification == ReadinessClassification.INSUFFICIENT_EVIDENCE


def test_friday_13_nov_2026_observation_runbook_and_fix_protocol():
    engine = ResearchReadinessEngine(db_path=DEFAULT_BACKTEST_DB_PATH)
    report = engine.evaluate(persist=False)
    plan = report.observation_plan

    assert plan.target_session_date == "2026-11-13"
    assert plan.target_weekday == "Friday"
    assert plan.is_scheduled_trading_day is True
    assert len(plan.checkpoints) == 6
    windows = [cp.ist_window for cp in plan.checkpoints]
    assert windows[0].startswith("08:45")
    assert windows[-1].endswith("15:45 IST")
    assert len(plan.final_observation_pass_criteria) >= 4
    assert len(plan.mandatory_abort_triggers) >= 4
    assert len(plan.controlled_fix_protocol) == 4


def test_isolated_store_roundtrip_deterministic_hash_and_15_section_report(isolated_readiness_db: Path):
    shutil.copy2(DEFAULT_BACKTEST_DB_PATH, isolated_readiness_db)
    probe = LiveFeedObservationProbe(
        exchange_open=False,
        observation_session_date="2026-11-13",
        session_is_scheduled_trading_day=True,
        rest_provider_name="angelone",
        rest_authenticated=False,
        websocket_connected=False,
        ticks_received=0,
        usable_verified_ticks=0,
        probe_source="INJECTED_SIMULATION",
    )
    engine = ResearchReadinessEngine(db_path=isolated_readiness_db)
    r1 = engine.evaluate(probe=probe, persist=True)
    r2 = engine.evaluate(probe=probe, persist=False)

    assert r1.report_fingerprint == r2.report_fingerprint
    assert r1.readiness_id == r2.readiness_id

    loaded = ResearchReadinessStore(isolated_readiness_db).load_report(r1.readiness_id)
    assert loaded is not None
    assert loaded.report_fingerprint == r1.report_fingerprint

    md = generate_step4_9_readiness_markdown(r1)
    for sec in range(1, 16):
        assert f"## {sec}. " in md


def test_protected_persistence_hashes_unchanged():
    checks = verify_protected_persistence_hashes()
    assert len(checks) == 6
    assert all(c.matched for c in checks)

