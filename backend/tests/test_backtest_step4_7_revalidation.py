"""
AIVOLVE Phase 4, Step 4.7 — Comprehensive Tests for Historical Backtest Revalidation Engine
Covers all 19 mandatory requirements from Step 4.7 Section 11 using isolated temp DBs.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

import pandas as pd
import pytest

from app.backtesting import (
    AccountingUnitMode,
    AuditVerdict,
    BacktestConfiguration,
    DatasetEligibilityGate,
    DatasetQualityStatus,
    EligibilityClassification,
    HistoricalDataStore,
    HistoricalRevalidationPipeline,
    HistoricalRevalidationStore,
    IST_ZONE,
    MultiYearTradingCalendar,
    PROTECTED_PERSISTENCE_BASELINES,
    RevalidationAuditReportEngine,
    RevalidationConfig,
    RevalidationSignalDirection,
    RevalidationStatus,
    assert_isolated_backtest_path,
    default_accounting_domain_specs,
    verify_protected_persistence_hashes,
)
from app.backtesting.robustness_models import SampleSizeClassification


def _make_session_candles(
    trading_date: date,
    tf_minutes: int,
    *,
    base_price: float = 24000.0,
    drift_per_bar: float = 1.5,
    skip_last_n: int = 0,
    inject_nan_at: int | None = None,
) -> pd.DataFrame:
    """Builds exact NSE session candles (09:15..15:30 IST) matching MultiYearTradingCalendar grid."""
    cal = MultiYearTradingCalendar()
    tf_str = {60: "1h", 15: "15m", 5: "5m", 3: "3m", 1: "1m"}[tf_minutes]
    opens = cal.expected_opens_by_date(
        tf_str,
        datetime(trading_date.year, trading_date.month, trading_date.day, 0, 0, tzinfo=IST_ZONE),
        datetime(trading_date.year, trading_date.month, trading_date.day, 23, 59, tzinfo=IST_ZONE),
    )[trading_date]
    count = max(0, len(opens) - skip_last_n)
    rows: List[Dict] = []
    px = base_price
    for i in range(count):
        ts = opens[i]
        # Alternating mild trend with realistic wick structure for ICT/SMC & regime engines
        delta = drift_per_bar if (i % 5 != 0) else -0.4 * abs(drift_per_bar)
        o = px
        c = px + delta
        h = max(o, c) + (6.0 if tf_minutes >= 5 else 2.5)
        l = min(o, c) - (5.0 if tf_minutes >= 5 else 2.0)
        if inject_nan_at is not None and i == inject_nan_at:
            c = float("nan")
        rows.append(
            {
                "timestamp": ts.isoformat(),
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2) if pd.notna(c) else c,
                "volume": 1000 + i * 10,
            }
        )
        px = c if pd.notna(c) else o
    return pd.DataFrame(rows)


def _populate_verified_mtf_store(
    tmp_db_path: Path,
    dates: List[date],
    *,
    instrument: str = "NIFTY 50",
    partial_last_day_5m: bool = False,
) -> HistoricalDataStore:
    cfg = BacktestConfiguration(storage_db_path=str(tmp_db_path))
    store = HistoricalDataStore(config=cfg)
    tf_map = {"1h": 60, "15m": 15, "5m": 5, "3m": 3, "1m": 1}
    for tf, mins in tf_map.items():
        frames: List[pd.DataFrame] = []
        base = 24000.0
        for idx, d in enumerate(dates):
            # Alternate up/down sessions slightly or steady bullish trend
            drift = (2.0 if mins == 5 else (6.0 if mins == 15 else (18.0 if mins == 60 else 0.8)))
            if idx % 3 == 2:
                drift = -0.6 * abs(drift)
            skip_n = 2 if (partial_last_day_5m and tf == "5m" and idx == len(dates) - 1) else 0
            df_day = _make_session_candles(d, mins, base_price=base, drift_per_bar=drift, skip_last_n=skip_n)
            base = float(df_day["close"].iloc[-1])
            frames.append(df_day)
        full_df = pd.concat(frames, ignore_index=True)
        store.save_candles(
            full_df,
            instrument=instrument,
            timeframe=tf,
            provider="test_step4_7_synthetic_fixture",
            strict_missing_intervals=not (partial_last_day_5m and tf == "5m"),
        )
    return store


def _get_isolated_test_db(tmp_path: Path, name: str = "step4_7_test.db") -> Path:
    # Also test assert_isolated_backtest_path rejects outside production paths
    db_path = Path(__file__).resolve().parents[1] / "data" / "backtest" / f"_pytest_{tmp_path.name}_{name}"
    assert_isolated_backtest_path(db_path)
    return db_path


@pytest.fixture
def isolated_db_path(tmp_path: Path):
    import gc
    import time

    dbp = _get_isolated_test_db(tmp_path)
    try:
        yield dbp
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


# Real NSE trading days in June 2026
FOUR_TRADING_DATES = [
    date(2026, 6, 8),
    date(2026, 6, 9),
    date(2026, 6, 10),
    date(2026, 6, 11),
]


def test_step4_7_dataset_quality_gating_verified_vs_partial_and_degraded(isolated_db_path: Path):
    # 1. Verified dataset passes gate with full-session eligibility
    store = _populate_verified_mtf_store(isolated_db_path, FOUR_TRADING_DATES[:3], partial_last_day_5m=False)
    bt_cfg = BacktestConfiguration(storage_db_path=str(isolated_db_path))
    gate = DatasetEligibilityGate(backtest_config=bt_cfg, data_store=store)

    cfg = RevalidationConfig(
        instrument="NIFTY 50",
        primary_timeframe="5m",
        replay_timeframes=("1h", "15m", "5m"),
        required_timeframes=("1h", "15m", "5m"),
        allow_partial_research_only=False,
        storage_db_path=str(isolated_db_path),
    )
    decision, filtered = gate.evaluate_revalidation_eligibility(cfg)
    assert decision.eligible_for_replay is True
    assert decision.overall_quality_status == DatasetQualityStatus.VERIFIED
    assert decision.eligibility == EligibilityClassification.VERIFIED_FULL_SESSION_ELIGIBLE
    assert decision.full_session_claims_allowed is True
    assert len(decision.common_complete_sessions) == 3
    assert set(filtered.keys()) == {"1h", "15m", "5m"}

    # 2. Partial 5m dataset is REJECTED by default when allow_partial_research_only=False
    isolated_db_path.unlink(missing_ok=True)
    store_p = _populate_verified_mtf_store(isolated_db_path, FOUR_TRADING_DATES[:3], partial_last_day_5m=True)
    gate_p = DatasetEligibilityGate(backtest_config=bt_cfg, data_store=store_p)
    decision_blocked, filtered_blocked = gate_p.evaluate_revalidation_eligibility(cfg)
    assert decision_blocked.eligible_for_replay is False
    assert decision_blocked.full_session_claims_allowed is False
    assert decision_blocked.eligibility in (
        EligibilityClassification.REJECTED_MIXED_QUALITY,
        EligibilityClassification.PARTIAL_RESEARCH_ONLY,
    )
    assert filtered_blocked == {}

    # 3. With allow_partial_research_only=True, PARTIAL runs in research-only mode & excludes incomplete session
    cfg_opt_in = cfg.model_copy(update={"allow_partial_research_only": True})
    decision_res, filtered_res = gate_p.evaluate_revalidation_eligibility(cfg_opt_in)
    assert decision_res.eligible_for_replay is True
    assert decision_res.research_only_flag is True
    assert decision_res.full_session_claims_allowed is False
    assert "2026-06-10" in decision_res.excluded_incomplete_sessions
    assert decision_res.common_complete_sessions == ("2026-06-08", "2026-06-09")
    assert len(filtered_res["5m"]) == 2 * 75  # Strictly only complete 75-bar sessions

    # 4. Degraded (NaN) candles must fail gate before replay
    bad_df = _make_session_candles(date(2026, 6, 8), 5, inject_nan_at=10)
    decision_deg, _ = gate_p.evaluate_revalidation_eligibility(
        cfg_opt_in,
        candles_by_timeframe_override={"5m": bad_df},
    )
    assert decision_deg.eligible_for_replay is False
    assert decision_deg.eligibility == EligibilityClassification.REJECTED_QUALITY_GATE


def test_step4_7_sensex_governance_lockout_and_path_isolation(tmp_path: Path, isolated_db_path: Path):
    pipeline = HistoricalRevalidationPipeline(
        backtest_config=BacktestConfiguration(storage_db_path=str(isolated_db_path))
    )
    sensex_cfg = RevalidationConfig(
        instrument="SENSEX",
        primary_timeframe="5m",
        replay_timeframes=("1h", "15m", "5m"),
        required_timeframes=("1h", "15m", "5m"),
        storage_db_path=str(isolated_db_path),
    )
    res = pipeline.run_revalidation(sensex_cfg, persist=False)
    assert res.status == RevalidationStatus.GOVERNANCE_LOCKOUT
    assert res.eligibility_decision.eligibility == EligibilityClassification.GOVERNANCE_LOCKED
    assert res.summary_metrics.total_signals_evaluated == 0

    # Ensure production path is rejected by isolation guard
    prod_db = Path(__file__).resolve().parents[1] / "aivolve_trading.db"
    with pytest.raises((PermissionError, ValueError)):
        assert_isolated_backtest_path(prod_db)
    with pytest.raises((PermissionError, ValueError)):
        HistoricalRevalidationStore(db_path=tmp_path / "outside.db")


def test_step4_7_chronological_no_lookahead_determinism_and_phase2_phase3_integration(
    isolated_db_path: Path,
):
    store = _populate_verified_mtf_store(isolated_db_path, FOUR_TRADING_DATES[:2], partial_last_day_5m=False)
    bt_cfg = BacktestConfiguration(storage_db_path=str(isolated_db_path))
    pipeline = HistoricalRevalidationPipeline(backtest_config=bt_cfg, data_store=store)

    cfg = RevalidationConfig(
        instrument="NIFTY 50",
        primary_timeframe="5m",
        replay_timeframes=("1h", "15m", "5m", "3m", "1m"),
        required_timeframes=("1h", "15m", "5m"),
        eval_stride_bars=25,
        min_warmup_bars_primary=15,
        monte_carlo_simulations=30,
        storage_db_path=str(isolated_db_path),
    )
    fixed_ts = datetime(2026, 11, 12, 12, 0, tzinfo=IST_ZONE)
    res1 = pipeline.run_revalidation(cfg, persist=True, created_at_utc=fixed_ts)
    res2 = pipeline.run_revalidation(cfg, persist=True, created_at_utc=fixed_ts)

    # Determinism check
    assert res1.run_fingerprint == res2.run_fingerprint
    assert [s.signal_id for s in res1.signals] == [s.signal_id for s in res2.signals]
    assert [s.signal_direction for s in res1.signals] == [s.signal_direction for s in res2.signals]
    assert len(res1.signals) > 0

    # Chronology & completed bar availability timestamp & Phase 3 uncalibrated score check
    prev_ts = None
    for s in res1.signals:
        cur_ts = datetime.fromisoformat(s.as_of_time_ist)
        if prev_ts is not None:
            assert cur_ts > prev_ts
        prev_ts = cur_ts
        assert s.phase3_ict_score is None
        assert s.phase3_score_status == "UNAVAILABLE"
        assert s.phase3_calibration_status == "NOT_CALIBRATED"
        assert len(s.source_event_ids) >= 0

    # No-lookahead test: run with cutoff at midpoint vs full range; prefix signals must match 100%
    mid_ts = datetime.fromisoformat(res1.signals[len(res1.signals) // 2].as_of_time_ist)
    # Use full day 1 only (complete session 2026-06-08) and compare Day 1 signals against 2-day run
    day1_end = datetime(2026, 6, 8, 15, 30, tzinfo=IST_ZONE)
    cfg_day1 = cfg.model_copy(update={"end_time_ist": day1_end})
    res_day1 = pipeline.run_revalidation(cfg_day1, persist=False, created_at_utc=fixed_ts)
    day1_sig_map_full = {s.as_of_time_ist: s for s in res1.signals if s.session_date_ist == "2026-06-08"}
    assert len(res_day1.signals) == len(day1_sig_map_full)
    for s_d1 in res_day1.signals:
        s_full = day1_sig_map_full[s_d1.as_of_time_ist]
        assert s_d1.signal_direction == s_full.signal_direction
        assert s_d1.market_regime == s_full.market_regime
        assert s_d1.phase2_confluence_score == s_full.phase2_confluence_score
        assert s_d1.phase3_alignment == s_full.phase3_alignment
        assert s_d1.entry_price == s_full.entry_price
        assert s_d1.stop_loss == s_full.stop_loss
    assert mid_ts >= datetime(2026, 6, 8, 9, 15, tzinfo=IST_ZONE)


def test_step4_7_no_trade_preservation_and_three_accounting_domains_isolation_and_robustness(
    isolated_db_path: Path,
):
    store = _populate_verified_mtf_store(isolated_db_path, FOUR_TRADING_DATES, partial_last_day_5m=False)
    bt_cfg = BacktestConfiguration(storage_db_path=str(isolated_db_path))
    pipeline = HistoricalRevalidationPipeline(backtest_config=bt_cfg, data_store=store)

    # Higher stride still yields multi-day chronological evaluation across all 3 domains cleanly
    cfg = RevalidationConfig(
        instrument="NIFTY 50",
        primary_timeframe="5m",
        replay_timeframes=("1h", "15m", "5m"),
        required_timeframes=("1h", "15m", "5m"),
        eval_stride_bars=45,
        min_warmup_bars_primary=15,
        monte_carlo_simulations=30,
        storage_db_path=str(isolated_db_path),
    )
    res = pipeline.run_revalidation(cfg, domain_specs=default_accounting_domain_specs(), persist=True)
    assert res.actual_historical_options_status == "BLOCKED"
    assert res.status in (RevalidationStatus.COMPLETED, RevalidationStatus.NO_ELIGIBLE_SIGNALS)

    # Ensure WAIT and NO_TRADE are never forced into execution
    for sig in res.signals:
        if sig.signal_direction in (RevalidationSignalDirection.WAIT, RevalidationSignalDirection.NO_TRADE):
            assert sig.entry_eligible is False

    # Verify all 3 domains ran separately and enforced strict unit separation
    assert set(res.domain_evaluations.keys()) == {
        AccountingUnitMode.INDEX_POINTS_ONLY.value,
        AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR.value,
        AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY.value,
    }

    dom_pts = res.domain_evaluations[AccountingUnitMode.INDEX_POINTS_ONLY.value]
    assert dom_pts.analytics_report.performance_summary.points_metrics is not None
    assert dom_pts.analytics_report.performance_summary.inr_metrics is None
    assert dom_pts.simulation_run.portfolio.realized_net_pnl_inr is None
    assert dom_pts.is_synthetic_modelled is False

    dom_inr = res.domain_evaluations[AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR.value]
    assert dom_inr.analytics_report.performance_summary.points_metrics is not None
    assert dom_inr.analytics_report.performance_summary.inr_metrics is not None
    assert dom_inr.is_synthetic_modelled is False

    dom_bs = res.domain_evaluations[AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY.value]
    assert dom_bs.analytics_report.performance_summary.points_metrics is None
    assert dom_bs.analytics_report.performance_summary.inr_metrics is not None
    assert dom_bs.is_synthetic_modelled is True
    assert dom_bs.actual_historical_options_status == "BLOCKED"

    # IS/OOS chronological split & insufficient sample size governance check
    for dom_eval in res.domain_evaluations.values():
        assert dom_eval.is_oos_comparison.no_lookahead_verified is True
        assert dom_eval.statistical_significance_claimed is False
        assert dom_eval.robustness_report.statistical_significance_claimed is False
        if dom_eval.analytics_report.performance_summary.trades_closed < 30:
            assert dom_eval.sample_size_classification == SampleSizeClassification.INSUFFICIENT_SAMPLE

    # Store persistence round-trip
    loaded = pipeline.reval_store.get_revalidation_run(res.revalidation_id)
    assert loaded is not None
    assert loaded.run_fingerprint == res.run_fingerprint

    # Audit report generation with protected hashes check
    report_engine = RevalidationAuditReportEngine(backtest_config=bt_cfg, data_store=store, reval_store=pipeline.reval_store)
    report = report_engine.build_report(
        runs=[res],
        test_results_summary={"passed": 5, "failed": 0, "skipped": 0},
        persist=True,
    )
    assert all(h.matched for h in report.protected_hash_checks)
    assert report.verdict in (AuditVerdict.PASS, AuditVerdict.PARTIAL_PASS)


def test_step4_7_executed_buy_ce_and_buy_pe_across_three_domains_with_costs_and_risk(
    isolated_db_path: Path,
):
    """Explicitly verifies BUY_CE & BUY_PE signal-to-execution bridge, slippage/statutory costs,
    max drawdown, IS/OOS chronological trade separation, and 3-domain isolation when trades fill."""
    from app.backtesting.revalidation_models import RevalidationSignalRecord
    from app.backtesting.historical_revalidation import PHASE2_ENGINE_VERSIONS, classify_ist_session_bucket
    from app.backtesting.revalidation_pipeline import (
        _build_is_oos_split,
        _build_simulation_config,
        build_domain_simulation_signals,
    )
    from app.backtesting.execution_simulator import HistoricalExecutionSimulator
    from app.backtesting.backtest_report import BacktestAnalyticsEngine, BacktestAnalyticsStore
    from app.backtesting.robustness_report import BacktestRobustnessEngine, BacktestRobustnessStore
    from app.backtesting.analytics_models import TradeEvaluationMetadata

    store = _populate_verified_mtf_store(isolated_db_path, FOUR_TRADING_DATES[:3], partial_last_day_5m=False)
    df_5m = store.load_candles("NIFTY 50", "5m")
    bt_cfg = BacktestConfiguration(storage_db_path=str(isolated_db_path))
    cfg = RevalidationConfig(
        instrument="NIFTY 50",
        primary_timeframe="5m",
        monte_carlo_simulations=30,
        storage_db_path=str(isolated_db_path),
    )

    # Pick two completed bar closes on Day 1 (IS) and Day 3 (OOS)
    t1_asof = datetime(2026, 6, 8, 10, 30, tzinfo=IST_ZONE)
    t2_asof = datetime(2026, 6, 10, 10, 30, tzinfo=IST_ZONE)
    s1_price = float(df_5m.iloc[14]["close"])
    s2_price = float(df_5m.iloc[2 * 75 + 14]["close"])

    sig_records = [
        RevalidationSignalRecord(
            signal_id="REVAL-EXEC-CE-1",
            as_of_time_ist=t1_asof.isoformat(),
            session_date_ist="2026-06-08",
            session_bucket=classify_ist_session_bucket(t1_asof),
            instrument="NIFTY 50",
            primary_timeframe="5m",
            spot_reference=s1_price,
            signal_direction=RevalidationSignalDirection.BUY_CE,
            qualification_status="QUALIFIED",
            market_regime="BULLISH_TREND",
            phase2_directional_bias="BULLISH",
            phase2_confluence_score=78.0,
            phase3_alignment="BULLISH_ALIGNMENT",
            source_replay_report_id="RPT-EXEC-1",
            entry_price=s1_price,
            stop_loss=round(s1_price - 15.0, 2),
            target_1=round(s1_price + 12.0, 2),
            target_2=round(s1_price + 24.0, 2),
            reward_risk_ratio=1.6,
            data_quality_status="VERIFIED",
            entry_eligible=True,
            dataset_fingerprint="FP-TEST-EXEC",
            engine_versions=dict(PHASE2_ENGINE_VERSIONS),
            config_fingerprint="CFG-TEST-EXEC",
        ),
        RevalidationSignalRecord(
            signal_id="REVAL-EXEC-PE-2",
            as_of_time_ist=t2_asof.isoformat(),
            session_date_ist="2026-06-10",
            session_bucket=classify_ist_session_bucket(t2_asof),
            instrument="NIFTY 50",
            primary_timeframe="5m",
            spot_reference=s2_price,
            signal_direction=RevalidationSignalDirection.BUY_PE,
            qualification_status="QUALIFIED",
            market_regime="BEARISH_TREND",
            phase2_directional_bias="BEARISH",
            phase2_confluence_score=80.0,
            phase3_alignment="BEARISH_ALIGNMENT",
            source_replay_report_id="RPT-EXEC-2",
            entry_price=s2_price,
            stop_loss=round(s2_price + 15.0, 2),
            target_1=round(s2_price - 12.0, 2),
            target_2=round(s2_price - 24.0, 2),
            reward_risk_ratio=1.6,
            data_quality_status="VERIFIED",
            entry_eligible=True,
            dataset_fingerprint="FP-TEST-EXEC",
            engine_versions=dict(PHASE2_ENGINE_VERSIONS),
            config_fingerprint="CFG-TEST-EXEC",
        ),
    ]

    trade_meta = {
        s.signal_id: TradeEvaluationMetadata(
            ict_smc_setup=s.phase3_alignment,
            market_regime=s.market_regime,
            session=s.session_bucket,
            entry_reason=s.signal_direction.value,
        )
        for s in sig_records
    }

    analytics_eng = BacktestAnalyticsEngine(
        data_store=store, analytics_store=BacktestAnalyticsStore(db_path=str(isolated_db_path))
    )
    robust_eng = BacktestRobustnessEngine(
        data_store=store, robustness_store=BacktestRobustnessStore(db_path=str(isolated_db_path))
    )

    for spec in default_accounting_domain_specs():
        sim_cfg = _build_simulation_config(spec, cfg)
        sim_sigs = build_domain_simulation_signals(sig_records, domain_spec=spec, config=cfg)
        assert len(sim_sigs) == 2
        sim = HistoricalExecutionSimulator(config=sim_cfg, backtest_config=bt_cfg, data_store=store)
        run = sim.run_simulation(
            instrument="NIFTY 50",
            timeframe="5m",
            signals=sim_sigs,
            candles_df=df_5m,
            persist=True,
        )
        assert run.portfolio.trades_opened == 2
        assert run.portfolio.trades_closed == 2
        assert all(tr.final_exit_reason is not None for tr in run.trades)

        is_oos, wf_wins = _build_is_oos_split(
            domain_mode=spec.domain_mode,
            signal_records=sig_records,
            sim_run=run,
            is_ratio=0.5,
        )
        assert is_oos.is_closed_trades == 1
        assert is_oos.oos_closed_trades == 1

        arep = analytics_eng.evaluate_simulation_run(
            run, signals=sim_sigs, trade_metadata=trade_meta, walk_forward_windows=wf_wins, persist=True
        )
        rrep = robust_eng.evaluate_simulation_run(
            run,
            candles_df=df_5m,
            signals=sim_sigs,
            trade_metadata=trade_meta,
            walk_forward_windows=wf_wins,
            is_ratio=0.5,
            persist=True,
        )
        assert rrep.sample_size_governance.classification == SampleSizeClassification.INSUFFICIENT_SAMPLE
        if spec.domain_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            assert run.portfolio.total_slippage_points > 0.0
            assert run.portfolio.total_costs_inr is None
            assert arep.performance_summary.points_metrics is not None
            assert arep.performance_summary.inr_metrics is None
        elif spec.domain_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            assert run.portfolio.total_costs_inr > 0.0
            assert arep.performance_summary.points_metrics is not None
            assert arep.performance_summary.inr_metrics is not None
        else:
            assert run.is_synthetic_modelled is True
            assert run.portfolio.total_costs_inr > 0.0
            assert arep.performance_summary.points_metrics is None
            assert arep.performance_summary.inr_metrics is not None


def test_step4_7_protected_persistence_hashes_remain_intact():
    checks = verify_protected_persistence_hashes(PROTECTED_PERSISTENCE_BASELINES)
    assert len(checks) == 6
    assert all(c.exists and c.matched for c in checks)
