"""
AIVOLVE Phase 4 Step 4.6 — Dedicated Verification Suite for Historical Dataset
Expansion & Validation Engine.

NOTICE: Every synthetic candle fixture used inside offline unit tests in this
suite is explicitly a `TEST_FIXTURE_ONLY` object isolated in pytest `tmp_path`
and never mixed with genuine production or genuine research datasets.

Covers all 14 mandatory test areas:
1. Incremental ingestion (no duplicate re-downloads of already covered windows)
2. Duplicate prevention (overlapping chunk boundaries & conflicting intra-chunk dups)
3. Resumable downloads (checkpoint skip on resume after transient interruption)
4. Timeframe validation & zero silent timeframe substitution
5. Timestamp normalization (UTC/naive/IST -> IST while preserving raw source timestamps)
6. Missing-candle detection & unexpected gap taxonomy (`PARTIAL` vs `VERIFIED`)
7. OHLCV, volume, NaN/Inf, incomplete candle, grid & cross-source inconsistency checks
8. Multi-year verified calendar (2024-2026, Muhurat, Budget weekend, DR split, closures, fail-closed unknown years)
9. Provider capability reporting (Angel One, Upstox, Dhan, Real, Mock)
10. Historical options data unavailability (explicit UNAVAILABLE, BS not market observation)
11. Data provenance persistence & inspection
12. Deterministic coverage & expansion reports + strict VERIFIED/PARTIAL/DEGRADED/UNAVAILABLE separation
13. Production-data isolation, AST checks & SENSEX fail-closed lockout
14. Protected persistence hash integrity verification
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import math
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.backtesting import (
    ANGELONE_INTERVAL_MAP,
    BacktestConfiguration,
    CapabilityAvailability,
    DatasetExpansionConfig,
    DatasetExpansionReportEngine,
    DatasetProvenanceStore,
    DatasetQualityStatus,
    DatasetValidator,
    DownloadStatus,
    HistoricalCoverageEngine,
    HistoricalDataStore,
    HistoricalDatasetManager,
    IntegrityStatus,
    MultiYearTradingCalendar,
    OptionsHistoryCapabilityAuditor,
    RawCandleFetchResult,
    SessionType,
    assert_isolated_backtest_path,
    check_cross_source_consistency,
    normalize_dataframe_timestamps_with_provenance,
    normalize_instrument,
    normalize_timeframe,
)
from app.backtesting.multi_year_calendar import CalendarUnavailableError
from app.backtesting.models import CalendarStatus
from app.options.ict_smc import SessionIntelligenceEngine

TEST_FIXTURE_ONLY: bool = True
IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


def _tmp_cfg(tmp_path: Path, **overrides: Any) -> BacktestConfiguration:
    params: Dict[str, Any] = {
        "storage_db_path": str(tmp_path / "isolated_step46.db"),
        "rate_limit_delay_seconds": 0.0,
        "retry_backoff_seconds": 0.0,
    }
    params.update(overrides)
    return BacktestConfiguration(**params)


def _fast_exp_cfg(**overrides: Any) -> DatasetExpansionConfig:
    params: Dict[str, Any] = {
        "provider_name": "angelone",
        "min_request_interval_seconds": 0.0,
        "rate_limit_backoff_seconds": 0.0,
        "max_retries_per_chunk": 1,
        "incremental": True,
        "resume_from_checkpoints": True,
    }
    params.update(overrides)
    return DatasetExpansionConfig(**params)


def _build_fixture_df(
    timestamps: Sequence[Any],
    *,
    timeframe: str = "5m",
    base_price: float = 24000.0,
    attrs: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    rows = []
    px = float(base_price)
    for i, ts in enumerate(timestamps):
        o = px + (i % 5) * 2.0
        c = o + 3.5
        h = max(o, c) + 4.0
        l = min(o, c) - 2.5
        rows.append(
            {
                "timestamp": ts,
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2),
                "volume": 0.0 if i % 2 == 0 else float(100 + i),
            }
        )
        px = c
    df = pd.DataFrame(rows)
    df.attrs = dict(
        attrs
        or {
            "provider": "angelone",
            "timeframe": timeframe,
            "is_mock": False,
            "synthetic": False,
            "ohlc_repaired": False,
            "dataStatus": "LIVE",
        }
    )
    return df


# ============================================================================
# 1. Incremental Ingestion & 2. Duplicate Prevention & 3. Resumable Downloads
# ============================================================================


def test_incremental_ingestion_and_duplicate_prevention(tmp_path: Path):
    cal = MultiYearTradingCalendar()
    cfg = _tmp_cfg(tmp_path)
    store = HistoricalDataStore(config=cfg)
    prov = DatasetProvenanceStore(db_path=cfg.storage_db_path)

    fetch_calls: List[tuple[datetime, datetime]] = []

    def fetcher(*, instrument: str, timeframe: str, from_time: datetime, to_time: datetime):
        fetch_calls.append((from_time, to_time))
        opens_map = cal.expected_opens_by_date(timeframe, from_time, to_time)
        ts_list = [dt.isoformat() for d in sorted(opens_map) for dt in opens_map[d]]
        df = _build_fixture_df(ts_list, timeframe=timeframe)
        # Inject 2 overlapping identical OHLCV rows from the start on purpose to test deduplication
        if len(df) >= 3:
            attrs_copy = dict(df.attrs)
            df = pd.concat([df.iloc[:2], df], ignore_index=True)
            df.attrs.update(attrs_copy)
        return df

    mgr = HistoricalDatasetManager(
        data_store=store,
        provenance_store=prov,
        calendar=cal,
        config=cfg,
        expansion_config=_fast_exp_cfg(max_chunk_days_override=2),
        raw_fetcher=fetcher,
    )

    # First pass: Mon Nov 2 -> Tue Nov 3, 2026 (2 sessions * 75 5m bars = 150)
    r1 = asyncio.run(
        mgr.expand_dataset(
            instrument="NIFTY 50",
            timeframe="5m",
            from_time=datetime(2026, 11, 2, 9, 15, tzinfo=IST),
            to_time=datetime(2026, 11, 3, 15, 30, tzinfo=IST),
        )
    )
    assert r1.status == DownloadStatus.COMPLETED
    assert r1.quality_status == DatasetQualityStatus.VERIFIED
    assert r1.bars_stored == 150
    assert r1.duplicate_rows_prevented >= 2
    assert len(fetch_calls) == 1

    # Second pass expanding through Thu Nov 5, 2026: Mon-Tue chunk must be skipped via incremental check!
    fetch_calls.clear()
    r2 = asyncio.run(
        mgr.expand_dataset(
            instrument="NIFTY 50",
            timeframe="5m",
            from_time=datetime(2026, 11, 2, 9, 15, tzinfo=IST),
            to_time=datetime(2026, 11, 5, 15, 30, tzinfo=IST),
        )
    )
    assert r2.status == DownloadStatus.COMPLETED
    assert r2.quality_status == DatasetQualityStatus.VERIFIED
    assert r2.chunks_skipped_existing >= 1
    assert len(fetch_calls) == 1  # Only Nov 4-5 chunk fetched!
    loaded = store.load_candles("NIFTY 50", "5m")
    assert len(loaded) == 4 * 75
    assert loaded["timestamp"].is_unique


def test_rejects_conflicting_intra_chunk_duplicates(tmp_path: Path):
    cal = MultiYearTradingCalendar()
    cfg = _tmp_cfg(tmp_path)
    store = HistoricalDataStore(config=cfg)

    def bad_dup_fetcher(*, instrument: str, timeframe: str, from_time: datetime, to_time: datetime):
        opens_map = cal.expected_opens_by_date(timeframe, from_time, to_time)
        ts_list = [dt.isoformat() for d in sorted(opens_map) for dt in opens_map[d]]
        df = _build_fixture_df(ts_list, timeframe=timeframe)
        # Conflicting close price on duplicate timestamp row
        conflict_row = df.iloc[[5]].copy()
        conflict_row["close"] = float(conflict_row["close"].iloc[0]) + 50.0
        conflict_row["high"] = float(conflict_row["close"].iloc[0]) + 5.0
        return pd.concat([df, conflict_row], ignore_index=True)

    mgr = HistoricalDatasetManager(
        data_store=store,
        calendar=cal,
        config=cfg,
        expansion_config=_fast_exp_cfg(),
        raw_fetcher=bad_dup_fetcher,
    )
    res = asyncio.run(
        mgr.expand_dataset(
            instrument="BANK NIFTY",
            timeframe="5m",
            from_time=datetime(2026, 11, 2, 9, 15, tzinfo=IST),
            to_time=datetime(2026, 11, 2, 15, 30, tzinfo=IST),
        )
    )
    assert res.status == DownloadStatus.FAILED_INTEGRITY
    assert res.invalid_chunks_rejected == 1
    assert res.bars_stored == 0
    assert store.load_candles("BANK NIFTY", "5m").empty


def test_resumable_download_recovers_after_transient_chunk_failure(tmp_path: Path):
    cal = MultiYearTradingCalendar()
    cfg = _tmp_cfg(tmp_path)
    store = HistoricalDataStore(config=cfg)
    prov = DatasetProvenanceStore(db_path=cfg.storage_db_path)

    fail_second_chunk = {"flag": True}
    calls_per_chunk: List[str] = []

    def flaky_fetcher(*, instrument: str, timeframe: str, from_time: datetime, to_time: datetime):
        tag = f"{from_time.date().isoformat()}..{to_time.date().isoformat()}"
        calls_per_chunk.append(tag)
        if fail_second_chunk["flag"] and from_time.date() >= date(2026, 11, 4):
            return RawCandleFetchResult(
                df=pd.DataFrame(),
                source_endpoint="TEST_STUB",
                http_status=403,
                error_code="HTTP_403",
                error_message="Transient simulated rate limit",
                is_transient_rate_limit=True,
            )
        opens_map = cal.expected_opens_by_date(timeframe, from_time, to_time)
        ts_list = [dt.isoformat() for d in sorted(opens_map) for dt in opens_map[d]]
        return _build_fixture_df(ts_list, timeframe=timeframe)

    mgr = HistoricalDatasetManager(
        data_store=store,
        provenance_store=prov,
        calendar=cal,
        config=cfg,
        expansion_config=_fast_exp_cfg(max_chunk_days_override=2, max_retries_per_chunk=0),
        raw_fetcher=flaky_fetcher,
    )

    from_dt = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    to_dt = datetime(2026, 11, 5, 15, 30, tzinfo=IST)

    run1 = asyncio.run(mgr.expand_dataset(instrument="FINNIFTY", timeframe="15m", from_time=from_dt, to_time=to_dt))
    assert run1.status == DownloadStatus.INCOMPLETE
    assert run1.chunks_completed == 1
    assert run1.chunks_failed == 1
    assert run1.bars_stored == 2 * 25
    assert run1.quality_status == DatasetQualityStatus.PARTIAL  # Never VERIFIED while incomplete!

    ckpts_after_1 = prov.get_checkpoints(run1.job_id)
    assert [c.status for c in ckpts_after_1] == ["COMPLETED", "FAILED"]

    # Resolve transient error and resume the exact job
    calls_per_chunk.clear()
    fail_second_chunk["flag"] = False
    run2 = asyncio.run(mgr.expand_dataset(instrument="FINNIFTY", timeframe="15m", from_time=from_dt, to_time=to_dt))
    assert run2.status == DownloadStatus.COMPLETED
    assert run2.chunks_skipped_resumed == 1
    assert run2.chunks_failed == 0
    assert run2.bars_stored == 2 * 25
    assert run2.quality_status == DatasetQualityStatus.VERIFIED
    # Chunk 0 was NOT re-fetched on resume!
    assert len(calls_per_chunk) == 1
    assert len(store.load_candles("FINNIFTY", "15m")) == 4 * 25


# ============================================================================
# 4. Timeframe Non-Substitution & 5. Timestamp Normalization & Provenance
# ============================================================================


def test_timeframe_validation_and_no_silent_substitution(tmp_path: Path):
    for tf in ("1m", "3m", "5m", "15m", "1h", "1d"):
        assert normalize_timeframe(tf) == tf
        assert tf in ANGELONE_INTERVAL_MAP
    for bad in ("2m", "4m", "10m", "30m", "2h", "1w"):
        with pytest.raises(ValueError):
            normalize_timeframe(bad)

    cal = MultiYearTradingCalendar()
    cfg = _tmp_cfg(tmp_path)
    store = HistoricalDataStore(config=cfg)

    def wrong_tf_fetcher(*, instrument: str, timeframe: str, from_time: datetime, to_time: datetime):
        opens_map = cal.expected_opens_by_date("15m", from_time, to_time)
        ts_list = [dt.isoformat() for d in sorted(opens_map) for dt in opens_map[d]]
        return _build_fixture_df(
            ts_list,
            timeframe="15m",
            attrs={"provider": "angelone", "timeframe": "15m", "is_mock": False, "synthetic": False, "ohlc_repaired": False},
        )

    mgr = HistoricalDatasetManager(
        data_store=store,
        calendar=cal,
        config=cfg,
        expansion_config=_fast_exp_cfg(),
        raw_fetcher=wrong_tf_fetcher,
    )
    res = asyncio.run(
        mgr.expand_dataset(
            instrument="NIFTY 50",
            timeframe="3m",
            from_time=datetime(2026, 11, 2, 9, 15, tzinfo=IST),
            to_time=datetime(2026, 11, 2, 15, 30, tzinfo=IST),
        )
    )
    assert res.status == DownloadStatus.FAILED_INTEGRITY
    assert res.bars_stored == 0
    assert store.load_candles("NIFTY 50", "3m").empty


def test_timestamp_normalization_preserves_original_provenance(tmp_path: Path):
    cal = MultiYearTradingCalendar()
    cfg = _tmp_cfg(tmp_path)
    store = HistoricalDataStore(config=cfg)
    prov = DatasetProvenanceStore(db_path=cfg.storage_db_path)

    # Supply timestamps in UTC ('Z') so normalization must convert to IST (+05:30)
    # while preserving original UTC strings & offsets in provenance tables.
    def utc_fetcher(*, instrument: str, timeframe: str, from_time: datetime, to_time: datetime):
        opens_map = cal.expected_opens_by_date(timeframe, from_time, to_time)
        utc_strs = [
            dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            for d in sorted(opens_map)
            for dt in opens_map[d]
        ]
        return _build_fixture_df(utc_strs, timeframe=timeframe)

    mgr = HistoricalDatasetManager(
        data_store=store,
        provenance_store=prov,
        calendar=cal,
        config=cfg,
        expansion_config=_fast_exp_cfg(),
        raw_fetcher=utc_fetcher,
    )
    res = asyncio.run(
        mgr.expand_dataset(
            instrument="NIFTY 50",
            timeframe="15m",
            from_time=datetime(2026, 11, 2, 9, 15, tzinfo=IST),
            to_time=datetime(2026, 11, 2, 15, 30, tzinfo=IST),
        )
    )
    assert res.status == DownloadStatus.COMPLETED
    assert res.quality_status == DatasetQualityStatus.VERIFIED
    assert "+00:00" in res.source_timezone_offsets

    ts_rows = prov.get_source_timestamps("NIFTY 50", "15m")
    assert len(ts_rows) == 25
    assert ts_rows[0]["source_timestamp_raw"] == "2026-11-02T03:45:00Z"
    assert ts_rows[0]["source_timezone_offset"] == "+00:00"
    assert ts_rows[0]["timestamp_ist_iso"] == "2026-11-02T09:15:00+05:30"

    loaded = store.load_candles("NIFTY 50", "15m")
    assert loaded.iloc[0]["timestamp"].strftime("%Y-%m-%dT%H:%M:%S%z") == "2026-11-02T09:15:00+0530"


# ============================================================================
# 6. Missing Candles & 7. OHLCV / Grid / Inconsistency Quality Validation
# ============================================================================


def test_dataset_validator_ohlcv_gaps_and_source_inconsistency(tmp_path: Path):
    cal = MultiYearTradingCalendar()
    cfg = _tmp_cfg(tmp_path)
    validator = DatasetValidator(calendar_adapter=cal, config=cfg)

    opens_d1 = cal.expected_opens_by_date("5m", datetime(2026, 11, 2, 9, 15, tzinfo=IST), datetime(2026, 11, 2, 15, 30, tzinfo=IST))[date(2026, 11, 2)]
    opens_d2 = cal.expected_opens_by_date("5m", datetime(2026, 11, 3, 9, 15, tzinfo=IST), datetime(2026, 11, 3, 15, 30, tzinfo=IST))[date(2026, 11, 3)]
    valid_df = _build_fixture_df(opens_d1 + opens_d2, timeframe="5m")

    ok_rep = validator.validate_dataset(
        valid_df,
        instrument="NIFTY 50",
        timeframe="5m",
        expected_from_ist=datetime(2026, 11, 2, 9, 15, tzinfo=IST),
        expected_to_ist=datetime(2026, 11, 3, 15, 30, tzinfo=IST),
    )
    assert ok_rep.quality_status == DatasetQualityStatus.VERIFIED
    assert ok_rep.is_verified is True
    assert ok_rep.missing_candles == 0
    assert ok_rep.invalid_candles == 0

    # Missing bar -> PARTIAL (never VERIFIED) & unexpected gap reported
    gap_df = valid_df.drop(index=10).reset_index(drop=True)
    gap_rep = validator.validate_dataset(
        gap_df,
        instrument="NIFTY 50",
        timeframe="5m",
        expected_from_ist=datetime(2026, 11, 2, 9, 15, tzinfo=IST),
        expected_to_ist=datetime(2026, 11, 3, 15, 30, tzinfo=IST),
    )
    assert gap_rep.quality_status == DatasetQualityStatus.PARTIAL
    assert gap_rep.is_verified is False
    assert gap_rep.missing_candles == 1
    assert len(gap_rep.unexpected_gaps) == 1
    assert gap_rep.unexpected_gaps[0].gap_type == "INTRADAY_GAP"

    # OHLC violation, negative volume, NaN/Inf, out-of-order, off-grid, incomplete, holiday -> DEGRADED
    mutations = [
        valid_df.assign(high=valid_df["high"].where(valid_df.index != 2, valid_df["low"] - 5.0)),
        valid_df.assign(volume=valid_df["volume"].where(valid_df.index != 3, -10.0)),
        valid_df.assign(close=valid_df["close"].where(valid_df.index != 4, float("nan"))),
        valid_df.assign(open=valid_df["open"].where(valid_df.index != 4, float("inf"))),
        pd.concat([valid_df.iloc[[1, 0]], valid_df.iloc[2:]], ignore_index=True),
        valid_df.assign(is_complete=valid_df.index != 10),
    ]
    for bad_df in mutations:
        bad_df.attrs = dict(valid_df.attrs)
        r_bad = validator.validate_dataset(bad_df, instrument="NIFTY 50", timeframe="5m")
        assert r_bad.quality_status == DatasetQualityStatus.DEGRADED
        assert not r_bad.is_verified

    # Off-grid timestamp (09:17 on 5m grid) -> DEGRADED
    off_grid = valid_df.copy()
    off_grid.loc[0, "timestamp"] = datetime(2026, 11, 2, 9, 17, tzinfo=IST)
    r_grid = validator.validate_dataset(off_grid, instrument="NIFTY 50", timeframe="5m")
    assert r_grid.quality_status == DatasetQualityStatus.DEGRADED
    assert r_grid.grid_misalignment_count >= 1

    # Bar on holiday (2026-10-20 Dussehra) -> DEGRADED
    hol_df = _build_fixture_df([datetime(2026, 10, 20, 9, 15, tzinfo=IST)], timeframe="5m")
    r_hol = validator.validate_dataset(hol_df, instrument="NIFTY 50", timeframe="5m")
    assert r_hol.quality_status == DatasetQualityStatus.DEGRADED
    assert r_hol.session_boundary_violation_count >= 1

    # Cross-source inconsistency check
    alt_df = valid_df.copy()
    alt_df.loc[5, "close"] = float(alt_df.loc[5, "close"]) * 1.05  # 5% divergence
    incons = check_cross_source_consistency(valid_df, alt_df)
    assert len(incons) >= 1
    r_src = validator.validate_dataset(valid_df, instrument="NIFTY 50", timeframe="5m", secondary_df=alt_df)
    assert r_src.quality_status == DatasetQualityStatus.DEGRADED
    assert r_src.source_inconsistency_count >= 1


# ============================================================================
# 8. Multi-Year Calendar, Muhurat & Special Sessions, Fail-Closed Unknown Years
# ============================================================================


def test_multi_year_calendar_special_sessions_and_fail_closed_unknown_years(tmp_path: Path):
    cal = MultiYearTradingCalendar()
    assert sorted(cal.covered_years) == [2024, 2025, 2026]

    # Holidays & exceptional election closures
    assert not cal.is_trading_day(date(2024, 1, 22))  # Ram Mandir Pran Pratishtha closure
    assert cal.is_trading_day(date(2024, 1, 20))      # Saturday replacement session
    assert not cal.is_trading_day(date(2024, 5, 20))  # Mumbai Lok Sabha election closure
    assert not cal.is_trading_day(date(2024, 11, 20)) # MH Assembly election closure
    assert not cal.is_trading_day(date(2026, 1, 15))  # MH Municipal election closure
    assert not cal.is_trading_day(date(2026, 3, 3))   # Corrected 2026 Holi
    assert cal.is_trading_day(date(2026, 3, 17))      # Regular trading day in 2026

    # Special Budget & DR split & Muhurat sessions
    assert cal.is_trading_day(date(2025, 2, 1))       # Sat Union Budget
    assert cal.is_trading_day(date(2026, 2, 1))       # Sun Union Budget
    assert cal.get_session_type(date(2024, 5, 18)) == SessionType.DISASTER_RECOVERY_MOCK
    dr_wins = cal.get_session_windows(date(2024, 5, 18))
    assert len(dr_wins) == 2
    assert (dr_wins[0].open_hhmm, dr_wins[0].close_hhmm) == ("09:15", "10:00")
    assert (dr_wins[1].open_hhmm, dr_wins[1].close_hhmm) == ("11:30", "12:30")

    muhurat_2024 = cal.get_session_windows(date(2024, 11, 1))
    assert (muhurat_2024[0].open_hhmm, muhurat_2024[0].close_hhmm) == ("18:00", "19:00")
    muhurat_2026 = cal.get_session_windows(date(2026, 11, 8))
    assert (muhurat_2026[0].open_hhmm, muhurat_2026[0].close_hhmm) == ("14:20", "15:30")

    # Unknown years MUST fail closed (never assume weekday is trading!)
    for unknown_d in (date(2023, 6, 14), date(2027, 2, 3)):
        res = cal.validate_date(unknown_d)
        assert res.status == CalendarStatus.CALENDAR_UNAVAILABLE
        assert res.is_trading_day is False
        assert cal.is_trading_day(unknown_d) is False
    with pytest.raises(CalendarUnavailableError):
        cal.expected_opens_by_date("5m", datetime(2027, 2, 3, 9, 15, tzinfo=IST), datetime(2027, 2, 3, 15, 30, tzinfo=IST))

    # Special session candles validate cleanly as VERIFIED when aligned to exact DR split windows (21 x 5m bars)
    cfg = _tmp_cfg(tmp_path)
    validator = DatasetValidator(calendar_adapter=cal, config=cfg)
    dr_opens = cal.expected_opens_by_date("5m", datetime(2024, 5, 18, 9, 15, tzinfo=IST), datetime(2024, 5, 18, 12, 30, tzinfo=IST))[date(2024, 5, 18)]
    assert len(dr_opens) == 21
    dr_df = _build_fixture_df(dr_opens, timeframe="5m")
    dr_rep = validator.validate_dataset(
        dr_df,
        instrument="NIFTY 50",
        timeframe="5m",
        expected_from_ist=datetime(2024, 5, 18, 9, 15, tzinfo=IST),
        expected_to_ist=datetime(2024, 5, 18, 12, 30, tzinfo=IST),
    )
    assert dr_rep.quality_status == DatasetQualityStatus.VERIFIED

    # Compatibility with Phase 3 SessionIntelligenceEngine (weekday multi-year schedule & unknown year fail-closed)
    se = SessionIntelligenceEngine(calendar=cal)
    ok_2024, _, _ = se._validate_trading_calendar(date(2024, 1, 23))
    ok_2024_closure, _, _ = se._validate_trading_calendar(date(2024, 1, 22))
    ok_2026_hol, _, _ = se._validate_trading_calendar(date(2026, 1, 15))
    ok_2027, status_2027, _ = se._validate_trading_calendar(date(2027, 2, 3))
    assert ok_2024 is True
    assert ok_2024_closure is False
    assert ok_2026_hol is False
    assert ok_2027 is False and status_2027 == "CALENDAR_UNAVAILABLE"


# ============================================================================
# 9. Provider Capability & 10. Historical Options Unavailability & 11-12. Reports
# ============================================================================


def test_options_history_capability_marks_unavailable_honestly():
    auditor = OptionsHistoryCapabilityAuditor()
    summary = auditor.run_audit()
    by_name = {p.provider_name: p for p in summary.providers}

    assert "angelone" in by_name
    assert "upstox" in by_name
    assert "dhan" in by_name
    assert "mock" in by_name

    angel = by_name["angelone"]
    assert angel.historical_bid_ask.availability == CapabilityAvailability.UNAVAILABLE
    assert angel.historical_option_chain_snapshots.availability == CapabilityAvailability.UNAVAILABLE
    assert angel.historical_implied_volatility.availability == CapabilityAvailability.LIVE_ONLY
    assert angel.historical_greeks.availability == CapabilityAvailability.LIVE_ONLY
    assert angel.historical_option_ohlc.is_usable_for_verified_backtest is False

    assert by_name["mock"].overall_underlying_status == CapabilityAvailability.DISQUALIFIED_SYNTHETIC
    assert summary.historical_bid_ask_available is False
    assert summary.historical_option_chain_available is False
    assert summary.historical_iv_available is False
    assert summary.historical_greeks_available is False
    assert summary.black_scholes_is_market_observation is False


def test_deterministic_coverage_and_expansion_report_status_separation(tmp_path: Path):
    cal = MultiYearTradingCalendar()
    cfg = _tmp_cfg(tmp_path)
    store = HistoricalDataStore(config=cfg)
    prov = DatasetProvenanceStore(db_path=cfg.storage_db_path)

    # Save complete 15m data for NIFTY 50 on Nov 2, 2026 -> VERIFIED
    opens_complete = cal.expected_opens_by_date("15m", datetime(2026, 11, 2, 9, 15, tzinfo=IST), datetime(2026, 11, 2, 15, 30, tzinfo=IST))[date(2026, 11, 2)]
    store.save_candles(_build_fixture_df(opens_complete, timeframe="15m"), instrument="NIFTY 50", timeframe="15m", calendar_adapter=cal)

    # Save intrinsically clean partial 5m data for BANK NIFTY (missing 1 bar) -> PARTIAL
    opens_part = cal.expected_opens_by_date("5m", datetime(2026, 11, 2, 9, 15, tzinfo=IST), datetime(2026, 11, 2, 15, 30, tzinfo=IST))[date(2026, 11, 2)]
    partial_df = _build_fixture_df(opens_part[:10] + opens_part[11:], timeframe="5m")
    store.save_candles(
        partial_df,
        instrument="BANK NIFTY",
        timeframe="5m",
        calendar_adapter=cal,
        auditor=DatasetValidator(
            calendar_adapter=cal,
            config=cfg.model_copy(update={"strict_missing_intervals": False}),
        ),
        strict_missing_intervals=False,
    )

    rep_engine = DatasetExpansionReportEngine(
        data_store=store,
        provenance_store=prov,
        calendar=cal,
        config=cfg,
    )
    r1 = rep_engine.generate_report(
        instruments=("NIFTY 50", "BANK NIFTY", "SENSEX"),
        timeframes=("15m", "5m"),
        generated_at_utc="2026-11-12T06:00:00Z",
    )
    r2 = rep_engine.generate_report(
        instruments=("NIFTY 50", "BANK NIFTY", "SENSEX"),
        timeframes=("15m", "5m"),
        generated_at_utc="2026-11-12T06:00:00Z",
    )
    assert r1.report_id == r2.report_id
    assert r1.report_fingerprint == r2.report_fingerprint
    assert r1.markdown_summary == r2.markdown_summary

    by_pair = {(e.instrument, e.timeframe): e for e in r1.coverage_report.entries}
    assert by_pair[("NIFTY 50", "15m")].quality_status == DatasetQualityStatus.VERIFIED
    assert by_pair[("BANK NIFTY", "5m")].quality_status == DatasetQualityStatus.PARTIAL
    assert by_pair[("BANK NIFTY", "5m")].missing_candles == 1
    assert by_pair[("FINNIFTY" if ("FINNIFTY", "5m") in by_pair else "NIFTY 50", "5m")].quality_status == DatasetQualityStatus.UNAVAILABLE
    assert by_pair[("SENSEX", "15m")].quality_status == DatasetQualityStatus.UNAVAILABLE
    assert by_pair[("SENSEX", "15m")].governance_locked is True


# ============================================================================
# 13. Isolation, SENSEX Lockout, AST Guard & 14. Protected Persistence Hashes
# ============================================================================


def test_sensex_lockout_and_production_isolation_and_ast_safety(tmp_path: Path):
    cal = MultiYearTradingCalendar()
    cfg = _tmp_cfg(tmp_path)
    mgr = HistoricalDatasetManager(calendar=cal, config=cfg, expansion_config=_fast_exp_cfg())

    res = asyncio.run(
        mgr.expand_dataset(
            instrument="SENSEX",
            timeframe="1d",
            from_time=datetime(2026, 11, 2, 9, 15, tzinfo=IST),
            to_time=datetime(2026, 11, 6, 15, 30, tzinfo=IST),
        )
    )
    assert res.blocked is True
    assert res.status == DownloadStatus.BLOCKED
    assert res.quality_status == DatasetQualityStatus.UNAVAILABLE

    # Reject production paths loudly
    for forbidden in (
        Path("d:/ReactJs/aivolve-trading-ai/backend/aivolve_trading.db"),
        Path("d:/ReactJs/aivolve-trading-ai/backend/app/data/paper_trading_records.json"),
        Path("d:/ReactJs/aivolve-trading-ai/backend/app/data/ml_trade_dataset.json"),
    ):
        with pytest.raises(Exception):
            assert_isolated_backtest_path(forbidden)

    # AST isolation check across all Step 4.6 modules
    step46_dir = Path(__file__).resolve().parents[1] / "app" / "backtesting"
    step46_files = [
        "dataset_provenance.py",
        "multi_year_calendar.py",
        "dataset_validation.py",
        "historical_coverage.py",
        "options_history_capability.py",
        "historical_dataset_manager.py",
        "dataset_expansion_report.py",
    ]
    forbidden_imports = {
        "app.options.paper_trading",
        "app.options.ml_strategy_learner",
        "app.db.database",
    }
    for fname in step46_files:
        tree = ast.parse((step46_dir / fname).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not any(alias.name.startswith(f) for f in forbidden_imports), f"Forbidden import {alias.name} in {fname}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not any(node.module.startswith(f) for f in forbidden_imports), f"Forbidden import {node.module} in {fname}"


def test_protected_persistence_files_present_and_unmodified():
    expected = {
        "aivolve_trading.db": "C85C49BE76DEE40557C4B9AAF308B4E3BEACA03CD4B1CD1CE90D051566EABF44",
        "governance_ledger.db": "4B12B3BAB44BF913F15174278B346FA321D5C473272E40F8B7E6E2350034488E",
        "paper_trading_records.json": "00F968EF85095EB7C1DE336A1780F9EDE417426A253AC531446BEF1117DA0298",
        "ml_trade_dataset.json": "87EEA8802835BB4F5A0AD1D598F2CEC561C6D5237F123B8B57CD79BBBE2E6445",
        "what_ai_learned.json": "3ED015726DFF309000EEC473AB660F34E3BD4EFAEDCBE183B14D62C572E5CCC5",
        "ml_strategy_weights.json": "C3C495F36214BD7FA58DDCA3C7F0280C14E15EB08DF41F868704F724C2A4E2FC",
    }
    backend_dir = Path(__file__).resolve().parents[1]
    paths = {
        "aivolve_trading.db": backend_dir / "aivolve_trading.db",
        "governance_ledger.db": backend_dir / "app" / "data" / "governance_ledger.db",
        "paper_trading_records.json": backend_dir / "app" / "data" / "paper_trading_records.json",
        "ml_trade_dataset.json": backend_dir / "app" / "data" / "ml_trade_dataset.json",
        "what_ai_learned.json": backend_dir / "app" / "data" / "what_ai_learned.json",
        "ml_strategy_weights.json": backend_dir / "app" / "data" / "ml_strategy_weights.json",
    }
    for name, expected_hash in expected.items():
        digest = hashlib.sha256(paths[name].read_bytes()).hexdigest().upper()
        assert digest == expected_hash, f"Hash mismatch for {name}: {digest} != {expected_hash}"


# ============================================================================
# 15. Regression: Provider Intraday 15:15–15:27 Omission -> PARTIAL & Zero Fill
# ============================================================================


def test_provider_intraday_1515_to_1527_omission_preserves_partial_without_fabrication(
    tmp_path: Path,
):
    """
    Reproduces the verified Angel One SmartAPI post-2026-09-21 index behavior where
    a single post-close tick arrives at 15:28/15:29 and omits intermediate ticks in
    15:15–15:27:
      - 5m returns 73/75 bars (missing 15:15, 15:20; flat 15:25 close bar present)
      - 3m returns 121/125 bars (missing 15:15, 15:18, 15:21, 15:24; flat 15:27 bar present)
      - 1m returns 361/375 bars (missing 15:15..15:27 & 15:29; flat 15:28 bar present)
      - 15m returns 25/25 bars (flat 15:15 bar contains the closing print)
    Local ingestion MUST preserve raw provider timestamps 1:1 without fabricating,
    interpolating, or forward-filling bars, and retain PARTIAL status on 5m/3m/1m.
    """
    import sqlite3

    cal = MultiYearTradingCalendar()
    cfg = _tmp_cfg(tmp_path)
    store = HistoricalDataStore(config=cfg)
    prov = DatasetProvenanceStore(db_path=cfg.storage_db_path)
    validator = DatasetValidator(calendar_adapter=cal, config=cfg)

    day_start = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    day_end = datetime(2026, 10, 28, 15, 30, tzinfo=IST)

    kept_specs = {
        "5m": ({"15:15", "15:20"}, "15:25", 73, 2, "2026-10-28T15:15:00+05:30", "2026-10-28T15:20:00+05:30"),
        "3m": ({"15:15", "15:18", "15:21", "15:24"}, "15:27", 121, 4, "2026-10-28T15:15:00+05:30", "2026-10-28T15:24:00+05:30"),
        "1m": (
            {f"15:{m:02d}" for m in range(15, 28)} | {"15:29"},
            "15:28",
            361,
            14,
            "2026-10-28T15:15:00+05:30",
            "2026-10-28T15:29:00+05:30",
        ),
        "15m": (set(), "15:15", 25, 0, None, None),
    }

    def provider_omitting_1515_fetcher(*, instrument: str, timeframe: str, from_time: datetime, to_time: datetime):
        opens_map = cal.expected_opens_by_date(timeframe, from_time, to_time)
        omitted_hhmm, flat_hhmm, _, _, _, _ = kept_specs[timeframe]
        ts_list = [
            dt.isoformat()
            for d in sorted(opens_map)
            for dt in opens_map[d]
            if dt.strftime("%H:%M") not in omitted_hhmm
        ]
        df = _build_fixture_df(ts_list, timeframe=timeframe)
        # Replicate flat closing-tick bar at session close (O=H=L=C, volume=0)
        close_mask = df["timestamp"].astype(str).str.slice(11, 16) == flat_hhmm
        assert close_mask.sum() == 1
        df.loc[close_mask, ["open", "high", "low", "close"]] = 22698.85
        df.loc[close_mask, "volume"] = 0.0
        return RawCandleFetchResult(
            df=df,
            source_endpoint="POST /rest/secure/angelbroking/historical/v1/getCandleData",
            http_status=200,
        )

    mgr = HistoricalDatasetManager(
        data_store=store,
        provenance_store=prov,
        calendar=cal,
        config=cfg,
        expansion_config=_fast_exp_cfg(),
        raw_fetcher=provider_omitting_1515_fetcher,
    )

    for tf, (omitted_hhmm, _, expected_rows, expected_miss, gap_start, gap_end) in kept_specs.items():
        res = asyncio.run(
            mgr.expand_dataset(
                instrument="NIFTY 50",
                timeframe=tf,
                from_time=day_start,
                to_time=day_end,
                as_of_time=datetime(2026, 10, 29, 9, 0, tzinfo=IST),
            )
        )
        assert res.status == DownloadStatus.COMPLETED
        assert res.bars_downloaded == expected_rows
        assert res.bars_stored == expected_rows

        loaded = store.load_candles("NIFTY 50", tf, start_time_ist=day_start, end_time_ist=day_end)
        assert len(loaded) == expected_rows
        loaded_hhmm = {dt.tz_convert(IST).strftime("%H:%M") for dt in loaded["timestamp"]}
        assert loaded_hhmm.isdisjoint(omitted_hhmm), f"Omitted bars fabricated for {tf}: {loaded_hhmm & omitted_hhmm}"

        val_rep = validator.validate_dataset(
            loaded,
            instrument="NIFTY 50",
            timeframe=tf,
            expected_from_ist=day_start,
            expected_to_ist=day_end,
        )
        assert val_rep.actual_candles == expected_rows
        assert val_rep.missing_candles == expected_miss
        if expected_miss == 0:
            assert res.quality_status == DatasetQualityStatus.VERIFIED
            assert val_rep.quality_status == DatasetQualityStatus.VERIFIED
            assert val_rep.unexpected_gaps == ()
        else:
            assert res.quality_status == DatasetQualityStatus.PARTIAL
            assert val_rep.quality_status == DatasetQualityStatus.PARTIAL
            assert val_rep.is_verified is False
            assert len(val_rep.unexpected_gaps) == 1
            gap = val_rep.unexpected_gaps[0]
            assert gap.gap_type == "INTRADAY_GAP"
            assert gap.missing_bars == expected_miss
            assert gap.start_ist == gap_start
            assert gap.end_ist == gap_end

        with sqlite3.connect(str(cfg.storage_db_path)) as conn:
            src_cnt = conn.execute(
                "SELECT COUNT(*) FROM dataset_source_timestamps WHERE instrument=? AND timeframe=?",
                ("NIFTY 50", tf),
            ).fetchone()[0]
            assert src_cnt == expected_rows

    cov = HistoricalCoverageEngine(
        data_store=store,
        provenance_store=prov,
        calendar=cal,
        validator=validator,
        config=cfg,
    ).build_coverage_report(instruments=("NIFTY 50",), timeframes=("15m", "5m", "3m", "1m"))
    by_tf = {e.timeframe: e for e in cov.entries}
    assert by_tf["15m"].quality_status == DatasetQualityStatus.VERIFIED
    assert by_tf["5m"].quality_status == DatasetQualityStatus.PARTIAL
    assert by_tf["3m"].quality_status == DatasetQualityStatus.PARTIAL
    assert by_tf["1m"].quality_status == DatasetQualityStatus.PARTIAL
