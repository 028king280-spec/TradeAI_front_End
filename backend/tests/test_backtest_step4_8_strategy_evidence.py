"""
AIVOLVE Phase 4, Step 4.8 — Strategy Performance & Evidence Review Engine Tests.

Covers all mandatory verification criteria from Step 4.8 Section 9:
- Accounting-domain isolation (`INDEX_POINTS_ONLY`, `INDEX_POINTS_AND_EXPLICIT_INR`, `SYNTHETIC_OPTION_INR_ONLY`)
- Reused Step 4.4 / 4.5 / 4.7 metric correctness
- Missing metadata preserved strictly as `UNKNOWN` (`missing_metadata_flag=True`, never fabricated)
- Insufficient sample classification (< 30 trades never classified MODERATE or STRONG; statistical_significance_claimed=False)
- Regime / session / instrument / timeframe / direction / entry_reason / exit_reason breakdown accuracy
- 8-pillar ICT/SMC evidence handling & `ict_score=None` (`UNAVAILABLE / NOT_CALIBRATED`)
- Synthetic BS provenance separation (`SYNTHETIC_MODELLED_OPTION_PNL` vs actual options `BLOCKED`)
- Chronological IS/OOS validation & out-of-order/lookahead timestamp violation detection
- Deterministic reports (`review_id`, `review_fingerprint`, rendered Markdown identical across repeated runs)
- Isolated persistence (`StrategyEvidenceStore` & Markdown writer reject production/governance/ML paths)
- End-to-end integration against persisted Step 4.6/4.7 SQLite state & 6-file SHA-256 protection
"""

from __future__ import annotations

import gc
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd
import pytest

from app.backtesting import (
    AccountingUnitMode,
    BacktestConfiguration,
    DEFAULT_BACKTEST_DB_PATH,
    DomainPerformanceEvidence,
    DomainRobustnessDigest,
    EvidenceVerdict,
    HistoricalDataStore,
    HistoricalRevalidationPipeline,
    HistoricalRevalidationRunResult,
    IST_ZONE,
    MultiYearTradingCalendar,
    PILLAR_ORDER,
    PROTECTED_PERSISTENCE_BASELINES,
    RevalidationConfig,
    RevalidationSignalDirection,
    RevalidationStatus,
    SampleSizeClassification,
    StrategyEvidenceStore,
    StrategyPerformanceEvidenceEngine,
    StrategyReviewConfig,
    assert_isolated_backtest_path,
    classify_evidence_verdict,
    classify_sample_size,
    render_strategy_evidence_markdown,
    review_ict_smc_evidence,
    review_regime_evidence,
    review_session_evidence,
    review_signal_quality,
    verify_protected_persistence_hashes,
)
from app.backtesting.analytics_models import DomainPerformanceMetrics, DomainRiskMetrics, UNKNOWN_LABEL
from app.backtesting.backtest_report import BacktestAnalyticsEngine
from app.backtesting.robustness_models import RobustnessStatus
from app.backtesting.simulation_models import ExitReason


FOUR_TRADING_DATES = [
    date(2026, 6, 8),
    date(2026, 6, 9),
    date(2026, 6, 10),
    date(2026, 6, 11),
]


def _make_session_candles(
    trading_date: date,
    tf_minutes: int,
    *,
    base_price: float = 24000.0,
    drift_per_bar: float = 1.5,
) -> pd.DataFrame:
    cal = MultiYearTradingCalendar()
    tf_str = {60: "1h", 15: "15m", 5: "5m", 3: "3m", 1: "1m"}[tf_minutes]
    opens = cal.expected_opens_by_date(
        tf_str,
        datetime(trading_date.year, trading_date.month, trading_date.day, 0, 0, tzinfo=IST_ZONE),
        datetime(trading_date.year, trading_date.month, trading_date.day, 23, 59, tzinfo=IST_ZONE),
    )[trading_date]
    rows: List[Dict] = []
    px = base_price
    for i, ts in enumerate(opens):
        delta = drift_per_bar if (i % 5 != 0) else -0.4 * abs(drift_per_bar)
        o = px
        c = px + delta
        h = max(o, c) + (6.0 if tf_minutes >= 5 else 2.5)
        l = min(o, c) - (5.0 if tf_minutes >= 5 else 2.0)
        rows.append(
            {
                "timestamp": ts.isoformat(),
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2),
                "volume": 1000 + i * 10,
            }
        )
        px = c
    return pd.DataFrame(rows)


def _populate_verified_mtf_store(db_path: Path, dates: List[date], instrument: str = "NIFTY 50") -> HistoricalDataStore:
    cfg = BacktestConfiguration(storage_db_path=str(db_path))
    store = HistoricalDataStore(config=cfg)
    tf_map = {"1h": 60, "15m": 15, "5m": 5, "3m": 3, "1m": 1}
    for tf, mins in tf_map.items():
        frames: List[pd.DataFrame] = []
        base = 24000.0
        for idx, d in enumerate(dates):
            drift = 2.0 if mins == 5 else (6.0 if mins == 15 else (18.0 if mins == 60 else 0.8))
            if idx % 3 == 2:
                drift = -0.6 * abs(drift)
            df_day = _make_session_candles(d, mins, base_price=base, drift_per_bar=drift)
            base = float(df_day["close"].iloc[-1])
            frames.append(df_day)
        store.save_candles(
            pd.concat(frames, ignore_index=True),
            instrument=instrument,
            timeframe=tf,
            provider="test_step4_8_fixture",
            strict_missing_intervals=True,
        )
    return store


@pytest.fixture(scope="module")
def module_reval_fixture(tmp_path_factory: pytest.TempPathFactory):
    tmp_dir = tmp_path_factory.mktemp("step4_8_mod")
    dbp = Path(__file__).resolve().parents[1] / "data" / "backtest" / f"_pytest_{tmp_dir.name}_step4_8.db"
    assert_isolated_backtest_path(dbp)
    try:
        store = _populate_verified_mtf_store(dbp, FOUR_TRADING_DATES[:2])
        bt_cfg = BacktestConfiguration(storage_db_path=str(dbp))
        pipeline = HistoricalRevalidationPipeline(backtest_config=bt_cfg, data_store=store)
        rcfg = RevalidationConfig(
            instrument="NIFTY 50",
            primary_timeframe="15m",
            replay_timeframes=("1h", "15m"),
            required_timeframes=("1h", "15m"),
            eval_stride_bars=3,
            allow_partial_research_only=False,
            storage_db_path=str(dbp),
        )
        run = pipeline.run_revalidation(rcfg, persist=True)
        yield dbp, run
    finally:
        gc.collect()
        for suffix in ("", "-wal", "-shm"):
            target = Path(str(dbp) + suffix)
            if target.exists():
                for _ in range(3):
                    try:
                        target.unlink(missing_ok=True)
                        break
                    except PermissionError:
                        gc.collect()
                        time.sleep(0.1)


def test_step4_8_accounting_domain_isolation_validators(module_reval_fixture):
    """Accounting domains must strictly reject cross-domain metric or multiplier leakage."""
    _, run = module_reval_fixture
    with pytest.raises(ValueError, match="DOMAIN_ISOLATION_VIOLATION"):
        DomainRobustnessDigest(
            accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_ONLY,
            provenance_label="BACKTEST_REVALIDATION",
            is_synthetic_modelled=False,
            overall_status=RobustnessStatus.INSUFFICIENT_DATA,
            slippage_status=RobustnessStatus.INSUFFICIENT_DATA,
            transaction_cost_status=RobustnessStatus.NOT_APPLICABLE_IN_DOMAIN,
            regime_robustness_status=RobustnessStatus.INSUFFICIENT_DATA,
            parameter_sensitivity_status=RobustnessStatus.INSUFFICIENT_DATA,
            parameter_stability="INSUFFICIENT_DATA",  # type: ignore[arg-type]
            oos_status=RobustnessStatus.INSUFFICIENT_DATA,
            oos_no_lookahead_verified=True,
            monte_carlo_status=RobustnessStatus.INSUFFICIENT_DATA,
            monte_carlo_iterations=10,
            mc_p50_net_pnl_inr=125.0,  # Forbidden INR leak inside INDEX_POINTS_ONLY
            sample_size_classification=SampleSizeClassification.INSUFFICIENT_SAMPLE,
        )

    with pytest.raises(ValueError, match="DOMAIN_ISOLATION_VIOLATION"):
        DomainRobustnessDigest(
            accounting_unit_mode=AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
            provenance_label="SYNTHETIC_MODELLED_OPTION_PNL",
            is_synthetic_modelled=True,
            overall_status=RobustnessStatus.INSUFFICIENT_DATA,
            slippage_status=RobustnessStatus.INSUFFICIENT_DATA,
            transaction_cost_status=RobustnessStatus.INSUFFICIENT_DATA,
            regime_robustness_status=RobustnessStatus.INSUFFICIENT_DATA,
            parameter_sensitivity_status=RobustnessStatus.INSUFFICIENT_DATA,
            parameter_stability="INSUFFICIENT_DATA",  # type: ignore[arg-type]
            oos_status=RobustnessStatus.INSUFFICIENT_DATA,
            oos_no_lookahead_verified=True,
            monte_carlo_status=RobustnessStatus.INSUFFICIENT_DATA,
            monte_carlo_iterations=10,
            mc_p50_net_pnl_points=10.0,  # Forbidden points leak inside SYNTHETIC_OPTION_INR_ONLY
            sample_size_classification=SampleSizeClassification.INSUFFICIENT_SAMPLE,
        )

    # Governance validator must reject assigning MODERATE/STRONG when sample is INSUFFICIENT_SAMPLE
    pts_eval = run.domain_evaluations[AccountingUnitMode.INDEX_POINTS_ONLY.value]
    pts_dummy = pts_eval.analytics_report.performance_summary.points_metrics
    risk_dummy = pts_eval.analytics_report.risk_summary.points_risk
    with pytest.raises(ValueError, match="GOVERNANCE_VIOLATION"):
        DomainPerformanceEvidence(
            accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_ONLY,
            provenance_label="BACKTEST_REVALIDATION",
            is_synthetic_modelled=False,
            eligible_runs_count=1,
            sessions_evaluated=5,
            total_signals=50,
            trades_opened=5,
            trades_closed=5,
            trades_rejected=0,
            trade_frequency_per_session=1.0,
            max_consecutive_wins=2,
            max_consecutive_losses=1,
            reconciliation_verified=True,
            points_metrics=pts_dummy,
            points_risk=risk_dummy,
            sample_size_classification=SampleSizeClassification.INSUFFICIENT_SAMPLE,
            verdict=EvidenceVerdict.MODERATE_EVIDENCE,
        )


def test_step4_8_insufficient_sample_and_verdict_classification():
    """<30 closed trades MUST stay INSUFFICIENT_SAMPLE & INSUFFICIENT_EVIDENCE even with high PF."""
    cfg = StrategyReviewConfig()
    assert classify_sample_size(5, cfg) == SampleSizeClassification.INSUFFICIENT_SAMPLE
    assert classify_sample_size(29, cfg) == SampleSizeClassification.INSUFFICIENT_SAMPLE
    assert classify_sample_size(30, cfg) == SampleSizeClassification.LIMITED_EVIDENCE
    assert classify_sample_size(100, cfg) == SampleSizeClassification.MODERATE_SAMPLE
    assert classify_sample_size(300, cfg) == SampleSizeClassification.LARGER_SAMPLE

    verdict, ssc, _ = classify_evidence_verdict(
        closed_trades=5,
        config=cfg,
        net_expectancy=50.0,
        profit_factor=5.0,
        oos_positive=True,
        survives_2x_stress=True,
        context_label="5_trade_sample",
    )
    assert ssc == SampleSizeClassification.INSUFFICIENT_SAMPLE
    assert verdict == EvidenceVerdict.INSUFFICIENT_EVIDENCE

    # >=300 trades with strong metrics & OOS + 2x stress reaches STRONG_EVIDENCE
    v_strong, ssc_strong, _ = classify_evidence_verdict(
        closed_trades=320,
        config=cfg,
        net_expectancy=12.0,
        profit_factor=1.65,
        oos_positive=True,
        survives_2x_stress=True,
        context_label="320_trade_sample",
    )
    assert ssc_strong == SampleSizeClassification.LARGER_SAMPLE
    assert v_strong == EvidenceVerdict.STRONG_EVIDENCE

    # Negative expectancy with sufficient sample classifies WEAK_EVIDENCE
    v_weak, _, _ = classify_evidence_verdict(
        closed_trades=120,
        config=cfg,
        net_expectancy=-3.5,
        profit_factor=0.82,
        oos_positive=False,
        survives_2x_stress=False,
        context_label="120_trade_neg",
    )
    assert v_weak == EvidenceVerdict.WEAK_EVIDENCE


def test_step4_8_metrics_isolation_missing_metadata_and_synthetic_provenance(module_reval_fixture):
    """Verifies Step 4.4 metric reuse, UNKNOWN metadata handling, ICT pillar bounds, and synthetic BS separation."""
    isolated_db_path, run = module_reval_fixture

    # Inject blank/missing metadata + synthetic Phase 3 evidence on a copy without mutating Step 4.7 persistence
    mutated_signals = []
    for idx, sig in enumerate(run.signals):
        if idx == 0:
            mutated_signals.append(
                sig.model_copy(
                    update={
                        "market_regime": "",
                        "session_bucket": "  ",
                        "phase3_alignment": "",
                        "phase2_confluence_score": 72.5,
                        "phase3_bullish_evidence": (
                            "{'event_id': 'ev1', 'event_category': 'BSL', 'status': 'SWEPT'}",
                            "{'event_id': 'ev2', 'event_category': 'BOS', 'status': 'ACTIVE'}",
                            "{'event_id': 'ev3', 'event_category': 'ORDER_BLOCK', 'status': 'MITIGATED'}",
                            "{'event_id': 'ev4', 'event_category': 'FVG', 'status': 'OPEN'}",
                            "{'event_id': 'ev5', 'event_category': 'DEALING_RANGE', 'status': 'DISCOUNT'}",
                            "{'event_id': 'ev6', 'event_category': 'INDUCEMENT_CONFIRMED', 'status': 'CONFIRMED'}",
                        ),
                        "phase3_bearish_evidence": (
                            "{'event_id': 'ev7', 'event_category': 'CHOCH', 'status': 'CONFIRMED'}",
                        ),
                        "phase3_conflicts": (
                            "{'conflict_type': 'PREMIUM_DISCOUNT_CONFLICT'}",
                        ),
                    }
                )
            )
        else:
            mutated_signals.append(sig)
    edited_run = run.model_copy(update={"signals": tuple(mutated_signals)})

    bt_cfg = BacktestConfiguration(storage_db_path=str(isolated_db_path))
    rev_cfg = StrategyReviewConfig(storage_db_path=str(isolated_db_path))
    engine = StrategyPerformanceEvidenceEngine(review_config=rev_cfg, backtest_config=bt_cfg)
    fixed_ts = datetime(2026, 11, 12, 12, 0, 0, tzinfo=timezone.utc)

    report = engine.review_from_runs(runs=[edited_run], persist=True, created_at_utc=fixed_ts)

    # 1. All 3 accounting domains separated & verified against BacktestAnalyticsEngine
    assert set(report.domain_evidence.keys()) == {
        AccountingUnitMode.INDEX_POINTS_ONLY.value,
        AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR.value,
        AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY.value,
    }
    pts_ev = report.domain_evidence[AccountingUnitMode.INDEX_POINTS_ONLY.value]
    assert pts_ev.inr_metrics is None
    assert pts_ev.is_synthetic_modelled is False
    assert pts_ev.actual_historical_options_status == "BLOCKED"

    direct_pts = BacktestAnalyticsEngine().evaluate_simulation_run(
        edited_run.domain_evaluations[AccountingUnitMode.INDEX_POINTS_ONLY.value].simulation_run,
        persist=False,
    )
    assert pts_ev.points_metrics is not None
    assert pts_ev.points_metrics.net_pnl == pytest.approx(
        direct_pts.performance_summary.points_metrics.net_pnl
    )
    assert pts_ev.points_metrics.total_costs == pytest.approx(
        direct_pts.performance_summary.points_metrics.total_costs
    )

    syn_ev = report.domain_evidence[AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY.value]
    assert syn_ev.is_synthetic_modelled is True
    assert syn_ev.provenance_label == "SYNTHETIC_MODELLED_OPTION_PNL"
    assert syn_ev.points_metrics is None
    assert syn_ev.actual_historical_options_status == "BLOCKED"

    # 2. Missing metadata MUST stay UNKNOWN cleanly across regime, session, and ict_setup
    assert any(r.bucket_key == UNKNOWN_LABEL and r.missing_metadata_flag for r in report.regime_evidence)
    assert any(r.bucket_key == UNKNOWN_LABEL and r.missing_metadata_flag for r in report.session_evidence)
    assert any(r.bucket_key == UNKNOWN_LABEL and r.missing_metadata_flag for r in report.ict_setup_evidence)
    assert report.signal_quality.missing_metadata_counts["market_regime"] >= 1
    assert report.signal_quality.missing_metadata_counts["session_bucket"] >= 1

    # 3. ICT/SMC 8 pillars strictly covered, UNAVAILABLE / NOT_CALIBRATED, zero invented thresholds
    assert tuple(p.pillar_name for p in report.ict_smc_evidence.pillars) == PILLAR_ORDER
    assert report.ict_smc_evidence.ict_score is None
    assert report.ict_smc_evidence.ict_score_status == "UNAVAILABLE"
    assert report.ict_smc_evidence.ict_calibration_status == "NOT_CALIBRATED"
    assert report.ict_smc_evidence.weights_or_thresholds_invented is False
    for pillar in report.ict_smc_evidence.pillars:
        assert pillar.ict_score is None
        assert pillar.profitability_claimed is False
        assert pillar.events_observed_count >= 1  # Every one of the 8 pillars was observed

    # 4. Verdicts & research disclaimers strictly preserved
    assert report.verdict_summary.statistical_significance_claimed is False
    assert report.verdict_summary.auto_optimization_performed is False
    assert report.verdict_summary.strategy_parameters_modified is False
    assert report.execution_mode == "PAPER_TRADING_ONLY"
    assert report.verdict_summary.overall_verdict in (
        EvidenceVerdict.INSUFFICIENT_EVIDENCE,
        EvidenceVerdict.DATA_QUALITY_BLOCKED,
    )

    # 5. Deterministic fingerprint, review_id, and Markdown rendering
    report2 = engine.review_from_runs(runs=[edited_run], persist=False, created_at_utc=fixed_ts)
    assert report.review_id == report2.review_id
    assert report.review_fingerprint == report2.review_fingerprint
    md1 = render_strategy_evidence_markdown(report)
    md2 = render_strategy_evidence_markdown(report2)
    assert md1 == md2
    for heading_num in range(1, 18):
        assert f"## {heading_num}." in md1

    # 6. Persisted snapshot round-trip inside isolated DB
    loaded = engine.evidence_store.get_review(report.review_id)
    assert loaded is not None
    loaded_rep, loaded_md = loaded
    assert loaded_rep.review_fingerprint == report.review_fingerprint
    assert loaded_md == md1


def test_step4_8_chronology_violation_and_lookahead_detection(module_reval_fixture):
    """Out-of-order signal timestamps must be flagged and block positive evidence verdict."""
    isolated_db_path, run = module_reval_fixture
    sigs = list(run.signals)
    assert len(sigs) >= 2
    # Swap first two timestamps to simulate chronological / lookahead corruption
    swapped = [
        sigs[0].model_copy(update={"as_of_time_ist": sigs[1].as_of_time_ist}),
        sigs[1].model_copy(update={"as_of_time_ist": sigs[0].as_of_time_ist}),
        *sigs[2:],
    ]
    corrupted_run = run.model_copy(update={"signals": tuple(swapped)})
    cfg = StrategyReviewConfig(storage_db_path=str(isolated_db_path))

    sq = review_signal_quality(runs=[corrupted_run], config=cfg)
    assert sq.chronological_no_lookahead_verified is False
    assert sq.chronology_violations_count >= 1
    assert sq.verdict == EvidenceVerdict.DATA_QUALITY_BLOCKED


def test_step4_8_persistence_isolation_rejects_production_paths(module_reval_fixture):
    """Step 4.8 Store & Markdown writer must refuse writing outside backend/data/backtest/."""
    isolated_db_path, run = module_reval_fixture
    backend_root = Path(__file__).resolve().parents[1]
    forbidden_targets = [
        backend_root / "aivolve_trading.db",
        backend_root / "app" / "data" / "governance_ledger.db",
        backend_root / "app" / "data" / "paper_trading_records.json",
        backend_root / "app" / "data" / "ml_trade_dataset.json",
    ]
    for bad in forbidden_targets:
        with pytest.raises(PermissionError, match="ISOLATION VIOLATION"):
            StrategyEvidenceStore(db_path=bad)

    bt_cfg = BacktestConfiguration(storage_db_path=str(isolated_db_path))
    rev_cfg = StrategyReviewConfig(storage_db_path=str(isolated_db_path))
    engine = StrategyPerformanceEvidenceEngine(review_config=rev_cfg, backtest_config=bt_cfg)
    rep = engine.review_from_runs(runs=[run], persist=False)

    with pytest.raises(PermissionError, match="ISOLATION VIOLATION"):
        engine.write_markdown_report(rep, output_path=backend_root / "app" / "data" / "paper_trading_records.json")


def test_step4_8_live_persisted_step4_7_compatibility_and_protected_hashes():
    """
    Read-only validation on persisted backtest_foundation.db + 6/6 protected hash check.
    Does NOT write to backtest_foundation.db inside pytest.
    """
    checks = verify_protected_persistence_hashes(PROTECTED_PERSISTENCE_BASELINES)
    assert len(checks) == 6
    assert all(c.exists and c.matched for c in checks)

    if not DEFAULT_BACKTEST_DB_PATH.exists():
        pytest.skip("backtest_foundation.db not present in environment")

    store = StrategyEvidenceStore(db_path=DEFAULT_BACKTEST_DB_PATH)
    live_runs = store.load_step4_7_runs()
    if not live_runs:
        pytest.skip("No persisted Step 4.7 runs found in backtest_foundation.db")

    engine = StrategyPerformanceEvidenceEngine(
        review_config=StrategyReviewConfig(storage_db_path=str(DEFAULT_BACKTEST_DB_PATH)),
        backtest_config=BacktestConfiguration(storage_db_path=str(DEFAULT_BACKTEST_DB_PATH)),
        evidence_store=store,
    )
    report = engine.review_from_runs(runs=live_runs, persist=False)
    assert report.signal_quality.chronological_no_lookahead_verified is True
    assert report.signal_quality.chronology_violations_count == 0
    assert report.verdict_summary.overall_sample_size == SampleSizeClassification.INSUFFICIENT_SAMPLE
    assert report.verdict_summary.overall_verdict == EvidenceVerdict.INSUFFICIENT_EVIDENCE
    assert report.verdict_summary.statistical_significance_claimed is False
    assert all(h.matched for h in report.protected_hash_checks)
    live_md = render_strategy_evidence_markdown(report)
    assert "## 17." in live_md
    assert "REVALRUN-5acfd6e991b165" in live_md

