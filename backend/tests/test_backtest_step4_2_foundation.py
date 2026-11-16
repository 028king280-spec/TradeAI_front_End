"""
AIVOLVE Phase 4 Step 4.2 — Comprehensive Isolated Test Suite.

NOTICE: Every candle generator and schedule fixture in this module is a
DETERMINISTIC TEST FIXTURE ONLY (`TEST_FIXTURE_ONLY = True`), strictly isolated
inside pytest `tmp_path` directories and NEVER represented as genuine market data.

Verifies:
1. Chunked historical ingestion & isolated SQLite persistence
2. Unavailable/missing credential BLOCKED behavior & zero synthetic fallback
3. Rejection of synthetic/mock/repaired/degraded datasets
4. Duplicate timestamps & missing intraday/session gap detection
5. OHLCV, timezone, session-boundary & grid validation
6. Exact timeframe mapping without cross-timeframe substitution (`3m` vs `15m`)
7. Multi-year HistoricalMarketCalendarAdapter fail-closed & verified injection behavior
8. Chronological point-in-time replay across 1H, 15M, 5M, 3M, 1M (`VERIFIED_EOD`)
9. Zero lookahead (future bars appended never alter prior replay outputs)
10. Strict forming-candle exclusion (`close_time > as_of_time`, `is_complete=False`, `15:15` 1h boundary)
11. Deterministic repeated replay (`run_id`, `output_fingerprint`, `MTFConfluenceReport`)
12. SENSEX fail-closed governance & isolated Ed25519 approval path
13. Strict production persistence isolation (AST/path checks + zero prod mutations)
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import math
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.backtesting import (
    ANGELONE_INTERVAL_MAP,
    AngelOneHistoricalDataDownloader,
    BacktestConfiguration,
    CalendarStatus,
    DataIntegrityAuditor,
    DeterministicReplayRunner,
    DownloadStatus,
    ExecutionSimulatorDesignSpec,
    ExecutionTimingPolicy,
    HistoricalDataStore,
    HistoricalMarketCalendarAdapter,
    HolidayScheduleRecord,
    IntegrityStatus,
    IntrabarAmbiguityPolicy,
    OptionDataMode,
    REPLAY_MTF_TIMEFRAMES,
    ReplayValidationStatus,
    SimulationDomainMode,
    assert_isolated_backtest_path,
    build_date_chunks,
    compute_candle_close_ist,
    normalize_instrument,
    normalize_timeframe,
    slice_completed_candles_as_of,
)
from app.options.contract_selector import (
    GovernanceLedger,
    build_canonical_approval_payload,
)
from app.options.ict_smc import MTFConfluenceEngine, SessionIntelligenceEngine

TEST_FIXTURE_ONLY: bool = True
IST = ZoneInfo("Asia/Kolkata")
M_CLOSE = dt_time(15, 30)


# ============================================================================
# Deterministic Test Fixture Helpers (Explicitly Test Fixtures, Not Market Data)
# ============================================================================


def _fixture_trading_days(
    cal: HistoricalMarketCalendarAdapter,
    end_day: date,
    min_count: int = 12,
) -> List[date]:
    days: List[date] = []
    cur = end_day - timedelta(days=min_count * 3)
    while cur <= end_day:
        if cal.validate_date(cur).status == CalendarStatus.TRADING_DAY:
            days.append(cur)
        cur += timedelta(days=1)
    return days[-min_count:]


def _fixture_session_timestamps(
    cal: HistoricalMarketCalendarAdapter,
    timeframe: str,
    as_of_time: datetime,
    count: int,
    trading_days: Optional[List[date]] = None,
) -> List[datetime]:
    step_min = {"1h": 60, "15m": 15, "5m": 5, "3m": 3, "1m": 1}[timeframe]
    days = trading_days or _fixture_trading_days(cal, as_of_time.date(), min_count=14)
    opens: List[datetime] = []
    for d in days:
        cur = datetime.combine(d, dt_time(9, 15), tzinfo=IST)
        end_open = datetime.combine(d, M_CLOSE, tzinfo=IST)
        while cur < end_open:
            cl = compute_candle_close_ist(cur, timeframe, M_CLOSE)
            if cl <= as_of_time:
                opens.append(cur)
            cur += timedelta(minutes=step_min)
    return opens[-count:]


def _fixture_range_timestamps(
    cal: HistoricalMarketCalendarAdapter,
    timeframe: str,
    from_ist: datetime,
    to_ist: datetime,
) -> List[datetime]:
    if timeframe == "1d":
        days = cal.iter_trading_days(from_ist.date(), to_ist.date())
        return [
            datetime.combine(d, dt_time(0, 0), tzinfo=IST)
            for d in days
            if datetime.combine(d, M_CLOSE, tzinfo=IST) <= to_ist
        ]
    step_min = {"1h": 60, "15m": 15, "5m": 5, "3m": 3, "1m": 1}[timeframe]
    days = cal.iter_trading_days(from_ist.date(), to_ist.date())
    opens: List[datetime] = []
    for d in days:
        cur = datetime.combine(d, dt_time(9, 15), tzinfo=IST)
        end_open = datetime.combine(d, M_CLOSE, tzinfo=IST)
        while cur < end_open:
            cl = compute_candle_close_ist(cur, timeframe, M_CLOSE)
            if cur >= from_ist and cl <= to_ist:
                opens.append(cur)
            cur += timedelta(minutes=step_min)
    return opens


def _fixture_ohlcv_df(
    timestamps: List[datetime],
    *,
    timeframe: str,
    base_price: float = 24000.0,
    scale: float = 1.0,
    instrument: str = "NIFTY 50",
) -> pd.DataFrame:
    """Builds a deterministic bullish 37+ bar TEST FIXTURE DataFrame for Steps 3.1-3.7."""
    n = len(timestamps)
    assert n >= 37, f"Fixture needs >= 37 bars, got {n}"
    offset_bars = n - 37
    lead_mids = [110.0 + ((k % 3) - 1) * 2.0 for k in range(offset_bars)]
    core_mids = [
        110, 114, 111, 116, 113, 117, 112, 118, 114, 119, 115, 120, 114, 118,
        115, 112, 106, 100, 96, 106,
        115, 112, 106, 98, 112, 126,
        138, 152, 166, 176, 162, 148,
        136, 130, 128, 150, 206,
    ]
    mids = lead_mids + core_mids
    rows = []
    for idx, ts in enumerate(timestamps):
        rel = idx - offset_bars
        if rel == 18:
            o, h, l, c = base_price + 102 * scale, base_price + 106 * scale, base_price + 90 * scale, base_price + 96 * scale
        elif rel == 23:
            o, h, l, c = base_price + 106 * scale, base_price + 112 * scale, base_price + 20 * scale, base_price + 98 * scale
        elif rel == 29:
            o, h, l, c = base_price + 166 * scale, base_price + 180 * scale, base_price + 162 * scale, base_price + 176 * scale
        elif rel == 35:
            o, h, l, c = base_price + 160 * scale, base_price + 162 * scale, base_price + 148 * scale, base_price + 150 * scale
        elif rel == 36:
            o, h, l, c = base_price + 150 * scale, base_price + 212 * scale, base_price + 148 * scale, base_price + 206 * scale
        else:
            c = base_price + mids[idx] * scale
            prev_c = base_price + (mids[idx - 1] if idx > 0 else mids[0]) * scale
            o = prev_c
            h = max(o, c) + 4.0 * scale
            l = min(o, c) - 4.0 * scale
        rows.append(
            {
                "timestamp": ts,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(1500 + idx * 10),
                "is_complete": True,
            }
        )
    df = pd.DataFrame(rows)
    df.attrs = {
        "instrument": instrument,
        "timeframe": timeframe,
        "provider": "test_fixture",
        "dataStatus": "VERIFIED_EOD",
        "feedStatus": "VERIFIED_EOD",
        "is_mock": False,
        "is_synthetic": False,
        "ohlc_repaired": False,
    }
    return df


def _fixture_5tf_candles(
    cal: HistoricalMarketCalendarAdapter,
    as_of_time: datetime,
    *,
    instrument: str = "NIFTY 50",
) -> Dict[str, pd.DataFrame]:
    return {
        "1h": _fixture_ohlcv_df(_fixture_session_timestamps(cal, "1h", as_of_time, 40), timeframe="1h", scale=2.0, instrument=instrument),
        "15m": _fixture_ohlcv_df(_fixture_session_timestamps(cal, "15m", as_of_time, 45), timeframe="15m", scale=1.5, instrument=instrument),
        "5m": _fixture_ohlcv_df(_fixture_session_timestamps(cal, "5m", as_of_time, 60), timeframe="5m", scale=1.0, instrument=instrument),
        "3m": _fixture_ohlcv_df(_fixture_session_timestamps(cal, "3m", as_of_time, 65), timeframe="3m", scale=0.8, instrument=instrument),
        "1m": _fixture_ohlcv_df(_fixture_session_timestamps(cal, "1m", as_of_time, 80), timeframe="1m", scale=0.5, instrument=instrument),
    }


class _StubAngelOneProvider:
    """Deterministic stub simulating AngelOneMarketDataProvider behavior for offline tests."""

    def __init__(
        self,
        *,
        cal: HistoricalMarketCalendarAdapter,
        authenticated: bool = True,
        client_code: str = "TEST_CLIENT",
        pin: str = "1234",
        api_key: str = "TEST_KEY",
        totp_secret: str = "JBSWY3DPEHPK3PXP",
        mode: str = "VALID",
        fail_on_chunk_index: Optional[int] = None,
        transient_403_calls: int = 0,
    ) -> None:
        self.cal = cal
        self._auth = authenticated
        self.client_code = client_code
        self.pin = pin
        self.api_key = api_key
        self.totp_secret = totp_secret
        self.mode = mode
        self.fail_on_chunk_index = fail_on_chunk_index
        self.transient_403_calls = transient_403_calls
        self.calls: List[Dict[str, Any]] = []

    @property
    def is_authenticated(self) -> bool:
        return self._auth

    async def _ensure_authenticated(self) -> bool:
        return self._auth

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        from_date: datetime,
        to_date: datetime,
    ) -> pd.DataFrame:
        idx = len(self.calls)
        self.calls.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "from_date": from_date,
                "to_date": to_date,
            }
        )

        if self.mode == "OFFLINE":
            df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "vwap"])
            df.attrs = {"dataStatus": "DATA_OFFLINE", "provider": "angelone", "timeframe": timeframe}
            return df

        if idx < self.transient_403_calls:
            df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "vwap"])
            df.attrs = {
                "dataStatus": "DATA_UNAVAILABLE",
                "degraded_reason": f"Angel One getCandleData HTTP 403 for {symbol} {timeframe}. (retries=0)",
                "provider": "angelone",
                "timeframe": timeframe,
            }
            return df

        if self.fail_on_chunk_index is not None and idx == self.fail_on_chunk_index:
            df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "vwap"])
            df.attrs = {
                "dataStatus": "DATA_UNAVAILABLE",
                "degraded_reason": "Simulated missing chunk response",
                "provider": "angelone",
                "timeframe": timeframe,
            }
            return df

        opens = _fixture_range_timestamps(self.cal, timeframe, from_date, to_date)
        if timeframe == "1d":
            opens = [ts for ts in opens if ts >= from_date]
        rows = []
        for k, ts in enumerate(opens):
            o = 24000.0 + k * 2.0
            c = o + 1.5
            h = max(o, c) + 2.5
            l = min(o, c) - 2.0
            rows.append(
                {
                    "timestamp": ts,
                    "open": float(o),
                    "high": float(h),
                    "low": float(l),
                    "close": float(c),
                    "volume": float(1000 + k * 5),
                    "vwap": float((o + h + l + c) / 4.0),
                }
            )
        df = pd.DataFrame(rows)
        if self.mode == "MOCK":
            df.attrs = {"dataStatus": "MOCK", "is_mock": True, "is_synthetic": True, "provider": "mock", "timeframe": timeframe}
        elif self.mode == "REPAIRED":
            df.attrs = {"dataStatus": "DEGRADED", "feedStatus": "DEGRADED", "ohlc_repaired": True, "provider": "angelone", "timeframe": timeframe}
        elif self.mode == "WRONG_TIMEFRAME":
            df.attrs = {"dataStatus": "LIVE", "feedStatus": "VERIFIED_LIVE", "provider": "angelone", "timeframe": "15m"}
        else:
            df.attrs = {"dataStatus": "LIVE", "feedStatus": "VERIFIED_LIVE", "is_mock": False, "is_synthetic": False, "provider": "angelone", "timeframe": timeframe}
        return df


def _temp_cfg(tmp_path: Path, **overrides: Any) -> BacktestConfiguration:
    params = {
        "storage_db_path": str(tmp_path / "isolated_backtest.db"),
        "rate_limit_delay_seconds": 0.0,
        "retry_backoff_seconds": 0.0,
    }
    params.update(overrides)
    return BacktestConfiguration(**params)


# ============================================================================
# 1. Data Ingestion, Persistence & Chunking Tests
# ============================================================================


def test_chunked_ingestion_and_isolated_persistence(tmp_path: Path):
    cal = HistoricalMarketCalendarAdapter()
    cfg = _temp_cfg(tmp_path)
    store = HistoricalDataStore(config=cfg)
    stub = _StubAngelOneProvider(cal=cal, mode="VALID")
    downloader = AngelOneHistoricalDataDownloader(
        provider=stub,
        data_store=store,
        calendar_adapter=cal,
        config=cfg,
    )

    from_dt = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    to_dt = datetime(2026, 11, 6, 15, 30, tzinfo=IST)
    result = asyncio.run(
        downloader.download_and_store(
            instrument="NIFTY 50",
            timeframe="5m",
            from_time=from_dt,
            to_time=to_dt,
            max_chunk_days_override=2,  # Force 3 multi-day chunks across Nov 2-6
        )
    )

    assert result.status == DownloadStatus.COMPLETED
    assert result.blocked is False
    assert result.chunks_total == 3
    assert result.chunks_succeeded == 3
    assert result.bars_downloaded == 5 * 75  # 5 verified trading days * 75 5m bars
    assert result.bars_stored == 5 * 75
    assert result.dataset_fingerprint
    assert len(stub.calls) == 3

    loaded = store.load_candles("NIFTY 50", "5m")
    assert len(loaded) == 5 * 75
    assert loaded.attrs["dataStatus"] == "VERIFIED_EOD"
    assert loaded.attrs["timeframe"] == "5m"
    assert loaded.iloc[0]["timestamp"] == from_dt
    assert loaded.iloc[-1]["timestamp"] == datetime(2026, 11, 6, 15, 25, tzinfo=IST)

    manifests = store.get_ingestion_manifests(instrument="NIFTY 50", timeframe="5m")
    assert len(manifests) == 1
    assert manifests[0]["provider"] == "angelone"
    assert manifests[0]["dataset_fingerprint"] == result.dataset_fingerprint


def test_provider_unavailable_and_incomplete_chunk_fail_blocked(tmp_path: Path):
    cal = HistoricalMarketCalendarAdapter()
    cfg = _temp_cfg(tmp_path)
    store = HistoricalDataStore(config=cfg)
    from_dt = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    to_dt = datetime(2026, 11, 6, 15, 30, tzinfo=IST)

    # Case 1: Missing / failed credentials -> BLOCKED
    unauth = _StubAngelOneProvider(cal=cal, authenticated=False, client_code="", pin="")
    dl_unauth = AngelOneHistoricalDataDownloader(provider=unauth, data_store=store, calendar_adapter=cal, config=cfg)
    res_unauth = asyncio.run(dl_unauth.download_and_store(instrument="NIFTY 50", timeframe="5m", from_time=from_dt, to_time=to_dt))
    assert res_unauth.status == DownloadStatus.BLOCKED
    assert res_unauth.blocked is True
    assert res_unauth.bars_stored == 0

    # Case 2: Provider offline -> BLOCKED
    offline = _StubAngelOneProvider(cal=cal, mode="OFFLINE")
    dl_offline = AngelOneHistoricalDataDownloader(provider=offline, data_store=store, calendar_adapter=cal, config=cfg)
    res_offline = asyncio.run(dl_offline.download_and_store(instrument="NIFTY 50", timeframe="5m", from_time=from_dt, to_time=to_dt))
    assert res_offline.status == DownloadStatus.BLOCKED
    assert res_offline.blocked is True

    # Case 3: Partial chunk failure -> INCOMPLETE, 0 partial bars committed
    partial = _StubAngelOneProvider(cal=cal, fail_on_chunk_index=1)
    dl_partial = AngelOneHistoricalDataDownloader(provider=partial, data_store=store, calendar_adapter=cal, config=cfg)
    res_partial = asyncio.run(
        dl_partial.download_and_store(
            instrument="NIFTY 50",
            timeframe="5m",
            from_time=from_dt,
            to_time=to_dt,
            max_chunk_days_override=2,
        )
    )
    assert res_partial.status == DownloadStatus.INCOMPLETE
    assert res_partial.blocked is True
    assert res_partial.bars_stored == 0
    assert store.load_candles("NIFTY 50", "5m").empty


def test_downloader_rejects_synthetic_repaired_and_timeframe_mismatch(tmp_path: Path):
    cal = HistoricalMarketCalendarAdapter()
    cfg = _temp_cfg(tmp_path)
    store = HistoricalDataStore(config=cfg)
    from_dt = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    to_dt = datetime(2026, 11, 2, 15, 30, tzinfo=IST)

    for bad_mode in ("MOCK", "REPAIRED", "WRONG_TIMEFRAME"):
        stub = _StubAngelOneProvider(cal=cal, mode=bad_mode)
        dl = AngelOneHistoricalDataDownloader(provider=stub, data_store=store, calendar_adapter=cal, config=cfg)
        res = asyncio.run(dl.download_and_store(instrument="NIFTY 50", timeframe="3m", from_time=from_dt, to_time=to_dt))
        assert res.status == DownloadStatus.FAILED_INTEGRITY, f"Expected FAILED_INTEGRITY for {bad_mode}, got {res.status}"
        assert res.blocked is True
        assert res.bars_stored == 0


# ============================================================================
# 2. Data Integrity Auditor Tests (Duplicates, Gaps, OHLC, TZ, No Repair)
# ============================================================================


def test_integrity_auditor_rejects_duplicates_gaps_and_malformed_ohlcv(tmp_path: Path):
    cal = HistoricalMarketCalendarAdapter()
    auditor = DataIntegrityAuditor(calendar_adapter=cal)
    base_ts = _fixture_range_timestamps(
        cal,
        "5m",
        datetime(2026, 11, 2, 9, 15, tzinfo=IST),
        datetime(2026, 11, 2, 15, 30, tzinfo=IST),
    )
    valid_df = _fixture_ohlcv_df(base_ts, timeframe="5m")
    assert auditor.audit_dataframe(valid_df, instrument="NIFTY 50", timeframe="5m").is_valid

    # Duplicate bar
    dup_df = pd.concat([valid_df.iloc[:10], valid_df.iloc[[9]], valid_df.iloc[10:]], ignore_index=True)
    dup_rep = auditor.audit_dataframe(dup_df, instrument="NIFTY 50", timeframe="5m")
    assert not dup_rep.is_valid
    assert len(dup_rep.duplicate_timestamps) == 1

    # Missing intraday bar (drop index 12 -> 10:15 5m bar)
    gap_df = valid_df.drop(index=12).reset_index(drop=True)
    gap_rep = auditor.audit_dataframe(gap_df, instrument="NIFTY 50", timeframe="5m")
    assert not gap_rep.is_valid
    assert len(gap_rep.missing_intervals) == 1
    assert "10:15:00" in gap_rep.missing_intervals[0].expected_open_ist

    # OHLC geometry violation (does NOT repair silently!)
    bad_ohlc = valid_df.copy()
    bad_ohlc.loc[5, "high"] = bad_ohlc.loc[5, "low"] - 10.0
    rep_ohlc = auditor.audit_dataframe(bad_ohlc, instrument="NIFTY 50", timeframe="5m")
    assert not rep_ohlc.is_valid
    assert any(i.code == "OHLC_GEOMETRY_VIOLATION" for i in rep_ohlc.issues)

    # NaN, Inf, non-positive price, negative volume
    for mutate_fn, expected_code in (
        (lambda d: d.assign(close=d["close"].where(d.index != 3, float("nan"))), "INVALID_PRICE_VALUE"),
        (lambda d: d.assign(high=d["high"].where(d.index != 4, float("inf"))), "INVALID_PRICE_VALUE"),
        (lambda d: d.assign(open=d["open"].where(d.index != 2, -5.0)), "INVALID_PRICE_VALUE"),
        (lambda d: d.assign(volume=d["volume"].where(d.index != 1, -1.0)), "INVALID_VOLUME"),
    ):
        mut_df = mutate_fn(valid_df.copy())
        r = auditor.audit_dataframe(mut_df, instrument="NIFTY 50", timeframe="5m")
        assert not r.is_valid
        assert any(i.code == expected_code for i in r.issues)

    # Naive timestamp & out-of-session timestamp rejected
    naive_df = valid_df.copy()
    naive_df["timestamp"] = [ts.replace(tzinfo=None) for ts in valid_df["timestamp"]]
    assert not auditor.audit_dataframe(naive_df, instrument="NIFTY 50", timeframe="5m").is_valid

    off_session_df = valid_df.copy()
    off_session_df.loc[0, "timestamp"] = datetime(2026, 11, 2, 8, 45, tzinfo=IST)
    assert any(
        i.code == "OUT_OF_SESSION_BOUNDARY"
        for i in auditor.audit_dataframe(off_session_df, instrument="NIFTY 50", timeframe="5m").issues
    )

    # Missing intermediate trading session across 2 days (Nov 2 and Nov 4 without Nov 3)
    ts_d1 = _fixture_range_timestamps(cal, "15m", datetime(2026, 11, 2, 9, 15, tzinfo=IST), datetime(2026, 11, 2, 15, 30, tzinfo=IST))
    ts_d3 = _fixture_range_timestamps(cal, "15m", datetime(2026, 11, 4, 9, 15, tzinfo=IST), datetime(2026, 11, 4, 15, 30, tzinfo=IST))
    two_day_gap_df = _fixture_ohlcv_df(ts_d1 + ts_d3, timeframe="15m")
    two_day_rep = auditor.audit_dataframe(two_day_gap_df, instrument="NIFTY 50", timeframe="15m")
    assert not two_day_rep.is_valid
    assert any(m.trading_date == "2026-11-03" for m in two_day_rep.missing_intervals)


# ============================================================================
# 3. Timeframe Mapping & No Silent Substitution Tests
# ============================================================================


def test_timeframe_mapping_and_no_silent_substitution(tmp_path: Path):
    assert ANGELONE_INTERVAL_MAP["3m"] == "THREE_MINUTE"
    assert ANGELONE_INTERVAL_MAP["1m"] == "ONE_MINUTE"
    assert ANGELONE_INTERVAL_MAP["1d"] == "ONE_DAY"
    assert normalize_timeframe("3M") == "3m"

    for bad_tf in ("10m", "30m", "2m", "4h"):
        with pytest.raises(ValueError):
            normalize_timeframe(bad_tf)

    cal = HistoricalMarketCalendarAdapter()
    cfg = _temp_cfg(tmp_path)
    store = HistoricalDataStore(config=cfg)
    ts_15m = _fixture_session_timestamps(cal, "15m", datetime(2026, 11, 6, 15, 30, tzinfo=IST), 40)
    df_15m = _fixture_ohlcv_df(ts_15m, timeframe="15m")
    store.save_candles(df_15m, instrument="NIFTY 50", timeframe="15m", calendar_adapter=cal)

    # Storing 15m MUST NEVER return anything when asking for 3m
    df_3m_loaded = store.load_candles("NIFTY 50", "3m")
    assert df_3m_loaded.empty
    assert df_3m_loaded.attrs["timeframe"] == "3m"
    assert df_3m_loaded.attrs["dataStatus"] == "DATA_UNAVAILABLE"


# ============================================================================
# 4. Calendar Fail-Closed & Verified Multi-Year Injection Tests
# ============================================================================


def test_calendar_adapter_fail_closed_and_phase3_injection(tmp_path: Path):
    cal = HistoricalMarketCalendarAdapter()
    assert 2026 in cal.covered_years
    # Unverified years (e.g. 2025, 2027) fail closed
    assert cal.validate_date(date(2025, 6, 10)).status == CalendarStatus.CALENDAR_UNAVAILABLE
    assert cal.validate_date(date(2027, 1, 15)).status == CalendarStatus.CALENDAR_UNAVAILABLE

    # Rejects unverified or empty holiday schedules
    with pytest.raises(Exception):
        cal.register_verified_year(year=2025, holidays={}, source="test_fixture", verified=True)
    with pytest.raises(Exception):
        cal.register_verified_year(year=2025, holidays={date(2025, 1, 26): "Republic Day"}, source="test", verified=False)

    # Inject verified test fixture holiday schedule JSON for 2025
    manifest_path = tmp_path / "test_fixture_holidays_2025.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schedules": [
                    {
                        "year": 2025,
                        "source": "TEST_FIXTURE_ONLY_2025_HOLIDAYS",
                        "verified": True,
                        "holidays": {
                            "2025-01-26": "Republic Day (Fixture)",
                            "2025-08-15": "Independence Day (Fixture)",
                            "2025-10-02": "Gandhi Jayanti (Fixture)",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    cal_multi = HistoricalMarketCalendarAdapter.from_json_file(manifest_path, include_builtin_2026=True)
    assert 2025 in cal_multi.covered_years
    assert cal_multi.validate_date(date(2025, 10, 2)).status == CalendarStatus.NON_TRADING_DAY
    assert cal_multi.validate_date(date(2025, 10, 3)).status == CalendarStatus.TRADING_DAY

    # Verify compatibility with Phase 3 SessionIntelligenceEngine & MTFConfluenceEngine via calendar=
    se_default = SessionIntelligenceEngine()
    ok_def, status_def, _ = se_default._validate_trading_calendar(date(2025, 10, 3))
    assert not ok_def and status_def == "CALENDAR_UNAVAILABLE"

    se_inj = SessionIntelligenceEngine(calendar=cal_multi)
    ok_inj, _, _ = se_inj._validate_trading_calendar(date(2025, 10, 3))
    assert ok_inj

    # Historical replay on an unverified year fails closed as LOCKED_OUT
    cfg = _temp_cfg(tmp_path)
    runner = DeterministicReplayRunner(calendar_adapter=cal, config=cfg)
    rep_2025_blocked = runner.run_replay(
        instrument="NIFTY 50",
        replay_times=[datetime(2025, 10, 3, 12, 0, tzinfo=IST)],
        candles_by_timeframe={},
        persist=False,
    )
    assert rep_2025_blocked.validation_status == ReplayValidationStatus.LOCKED_OUT
    assert any("2025" in r for r in rep_2025_blocked.failure_reasons)


# ============================================================================
# 5. Point-in-Time Replay, Zero Lookahead, Forming Candle Exclusion, Determinism
# ============================================================================


def test_point_in_time_replay_zero_lookahead_and_determinism(tmp_path: Path):
    cal = HistoricalMarketCalendarAdapter()
    cfg = _temp_cfg(tmp_path)
    store = HistoricalDataStore(config=cfg)
    runner = DeterministicReplayRunner(data_store=store, calendar_adapter=cal, config=cfg)

    t1 = datetime(2026, 11, 6, 14, 15, tzinfo=IST)
    t2 = datetime(2026, 11, 6, 15, 30, tzinfo=IST)
    prefix_candles = _fixture_5tf_candles(cal, t1, instrument="NIFTY 50")
    full_candles = _fixture_5tf_candles(cal, t2, instrument="NIFTY 50")

    # Run at t1 on prefix-only data
    run_prefix = runner.run_replay(
        instrument="NIFTY 50",
        replay_times=[t1],
        candles_by_timeframe=prefix_candles,
        data_source="TEST_FIXTURE_PREFIX",
    )
    assert run_prefix.validation_status == ReplayValidationStatus.VALIDATED
    assert run_prefix.point_count == 1
    assert run_prefix.points[0].confluence_score is None
    assert run_prefix.points[0].score_status == "UNAVAILABLE"
    assert run_prefix.points[0].calibration_status == "NOT_CALIBRATED"
    assert run_prefix.points[0].data_quality_status == "VERIFIED_EOD"

    # Build poisoned-future dataset: identical bars <= t1 PLUS violent spike future bars > t1
    with_future: Dict[str, pd.DataFrame] = {}
    for tf, df_p in prefix_candles.items():
        fut_only = full_candles[tf][full_candles[tf]["timestamp"] > t1].copy()
        if not fut_only.empty:
            fut_only["open"] = fut_only["open"] + 5000.0
            fut_only["high"] = fut_only["high"] + 5200.0
            fut_only["low"] = fut_only["low"] + 4800.0
            fut_only["close"] = fut_only["close"] + 5100.0
        combined = pd.concat([df_p, fut_only], ignore_index=True)
        combined.attrs = dict(df_p.attrs)
        with_future[tf] = combined

    run_with_future = runner.run_replay(
        instrument="NIFTY 50",
        replay_times=[t1],
        candles_by_timeframe=with_future,
        data_source="TEST_FIXTURE_WITH_FUTURE",
    )
    assert run_with_future.validation_status == ReplayValidationStatus.VALIDATED
    # Bit-for-bit identical Phase 3 intelligence at t1 regardless of future candles
    assert run_with_future.points[0].report == run_prefix.points[0].report
    assert run_with_future.points[0].report_id == run_prefix.points[0].report_id
    assert run_with_future.points[0].future_bars_excluded["5m"] > 0

    # Chronological multi-point replay + determinism repeat check
    for tf, df_full in full_candles.items():
        store.save_candles(df_full, instrument="NIFTY 50", timeframe=tf, calendar_adapter=cal, provider="test_fixture")

    rep_a = runner.run_replay(instrument="NIFTY 50", replay_times=[t1, t2])
    rep_b = runner.run_replay(instrument="NIFTY 50", replay_times=[t1, t2])
    assert rep_a.validation_status == ReplayValidationStatus.VALIDATED
    assert rep_a.timeframes == REPLAY_MTF_TIMEFRAMES
    assert rep_a.run_id == rep_b.run_id
    assert rep_a.output_fingerprint == rep_b.output_fingerprint
    assert rep_a.dataset_fingerprint == rep_b.dataset_fingerprint
    assert rep_a.points[0].report == rep_b.points[0].report
    assert rep_a.points[1].report == rep_b.points[1].report

    # Persisted replay run record has all mandatory audit fields
    fetched = store.get_replay_run(rep_a.run_id)
    assert fetched is not None
    assert fetched.instrument == "NIFTY 50"
    assert fetched.historical_date_range == "2026-11-06..2026-11-06"
    assert len(fetched.replay_timestamps_ist) == 2


def test_forming_candle_exclusion_and_1515_boundary(tmp_path: Path):
    cal = HistoricalMarketCalendarAdapter()
    cfg = _temp_cfg(tmp_path)
    runner = DeterministicReplayRunner(calendar_adapter=cal, config=cfg)

    # At 15:29:59 IST, the 15:15 1h bar and 15:25 5m bar are still FORMING; at 15:30:00 they close
    t_before_close = datetime(2026, 11, 6, 15, 29, 59, tzinfo=IST)
    t_at_close = datetime(2026, 11, 6, 15, 30, 0, tzinfo=IST)
    candles = _fixture_5tf_candles(cal, t_at_close, instrument="BANK NIFTY")

    sliced_1h_before, _, inc_1h_before, err_1h = slice_completed_candles_as_of(
        candles["1h"],
        timeframe="1h",
        as_of_time=t_before_close,
    )
    assert err_1h is None
    assert inc_1h_before == 1
    assert sliced_1h_before is not None
    assert all(ts < datetime(2026, 11, 6, 15, 15, tzinfo=IST) for ts in sliced_1h_before["timestamp"])

    sliced_1h_at, _, inc_1h_at, _ = slice_completed_candles_as_of(
        candles["1h"],
        timeframe="1h",
        as_of_time=t_at_close,
    )
    assert inc_1h_at == 0
    assert datetime(2026, 11, 6, 15, 15, tzinfo=IST) in set(sliced_1h_at["timestamp"])

    # Also verify explicit is_complete=False forming tail row is excluded safely
    candles_with_flag = dict(candles)
    df_5m_forming = candles_with_flag["5m"].copy()
    df_5m_forming.loc[df_5m_forming.index[-1], "is_complete"] = False
    candles_with_flag["5m"] = df_5m_forming

    rep = runner.run_replay(
        instrument="BANK NIFTY",
        replay_times=[t_before_close, t_at_close],
        candles_by_timeframe=candles_with_flag,
        persist=False,
    )
    assert rep.validation_status == ReplayValidationStatus.VALIDATED
    assert rep.points[1].incomplete_bars_excluded["5m"] == 1


# ============================================================================
# 6. Governance (SENSEX Lockout & Approved Path), Isolation & Design Contracts
# ============================================================================


def test_sensex_governance_fail_closed_and_isolated_approval(tmp_path: Path):
    cal = HistoricalMarketCalendarAdapter()
    # By default (real read-only governance_ledger.db or empty ledger), SENSEX fails closed
    cfg_default = _temp_cfg(tmp_path)
    runner_locked = DeterministicReplayRunner(calendar_adapter=cal, config=cfg_default)
    res_locked = runner_locked.run_replay(
        instrument="SENSEX",
        replay_times=[datetime(2026, 11, 6, 15, 30, tzinfo=IST)],
        candles_by_timeframe={},
        persist=False,
    )
    assert res_locked.validation_status == ReplayValidationStatus.LOCKED_OUT
    assert any("GOVERNANCE_LOCKOUT" in r for r in res_locked.failure_reasons)

    # Even if sensex_governance_approved=True WITHOUT ledger cryptographic proof, it STILL locks out
    cfg_forged = _temp_cfg(tmp_path, sensex_governance_approved=True)
    runner_forged = DeterministicReplayRunner(calendar_adapter=cal, config=cfg_forged)
    res_forged = runner_forged.run_replay(
        instrument="SENSEX",
        replay_times=[datetime(2026, 11, 6, 15, 30, tzinfo=IST)],
        candles_by_timeframe={},
        persist=False,
    )
    assert res_forged.validation_status == ReplayValidationStatus.LOCKED_OUT

    # With an ISOLATED temp Ed25519 governance ledger approving SENSEX, Step 4.2 permits SENSEX
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    iso_ledger_path = tmp_path / "test_fixture_governance.db"
    ledger = GovernanceLedger(db_path=str(iso_ledger_path))
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    ledger.register_authority(
        key_id="TEST-FIXTURE-AUTH-01",
        authority_name="Test Fixture Committee",
        public_key_hex=pub_hex,
        authorized_indices=["SENSEX"],
        valid_from="2026-01-01",
        valid_until="2027-12-31",
    )
    doc_hash = hashlib.sha256(b"TEST_FIXTURE_SENSEX_POLICY").hexdigest()
    payload = build_canonical_approval_payload(
        approval_id="APPR-TEST-001",
        document_id="DOC-TEST-001",
        approval_reference="QRC-TEST-SENSEX-01",
        document_sha256=doc_hash,
        ratifying_authority="TEST COMMITTEE",
        authorized_indices=["SENSEX"],
        min_oi_floor=10000,
        min_volume_floor=5000,
        max_spread_pct_ceiling=0.05,
        effective_date="2026-01-01",
        expiry_date="2027-12-31",
    )
    sig_hex = priv.sign(payload).hex()
    ledger.record_verified_approval(
        approval_reference="QRC-TEST-SENSEX-01",
        approval_id="APPR-TEST-001",
        approved_by="TEST COMMITTEE",
        authorized_indices=["SENSEX"],
        key_id="TEST-FIXTURE-AUTH-01",
        min_oi_floor=10000,
        min_volume_floor=5000,
        max_spread_pct_ceiling=0.05,
        effective_date="2026-01-01",
        expiry_date="2027-12-31",
        approval_evidence={
            "document_id": "DOC-TEST-001",
            "document_sha256": doc_hash,
            "digital_signature": sig_hex,
            "ratified_by": "TEST COMMITTEE",
            "effective_date": "2026-01-01",
            "expiry_date": "2027-12-31",
        },
        doc_id="DOC-TEST-001",
        recomputed_hash=doc_hash,
    )

    cfg_approved = _temp_cfg(
        tmp_path,
        storage_db_path=str(tmp_path / "isolated_sensex.db"),
        governance_ledger_path=str(iso_ledger_path),
        sensex_governance_approved=True,
    )
    as_of = datetime(2026, 11, 6, 15, 30, tzinfo=IST)
    runner_ok = DeterministicReplayRunner(calendar_adapter=cal, config=cfg_approved)
    res_ok = runner_ok.run_replay(
        instrument="SENSEX",
        replay_times=[as_of],
        candles_by_timeframe=_fixture_5tf_candles(cal, as_of, instrument="SENSEX"),
    )
    assert res_ok.validation_status == ReplayValidationStatus.VALIDATED
    assert res_ok.points[0].confluence_score is None


def test_persistence_isolation_and_no_execution_imports():
    # Rejects every protected production persistence filename
    for protected_name in (
        "aivolve_trading.db",
        "governance_ledger.db",
        "paper_trading_records.json",
        "ml_trade_dataset.json",
        "what_ai_learned.json",
        "ml_strategy_weights.json",
    ):
        with pytest.raises(PermissionError):
            assert_isolated_backtest_path(protected_name)
        with pytest.raises(PermissionError):
            BacktestConfiguration(storage_db_path=protected_name)

    # AST scan across all app/backtesting/*.py verifies zero PaperTradingEngine or MLFeedbackEngine imports
    pkg_dir = Path(__file__).resolve().parents[1] / "app" / "backtesting"
    for py_file in pkg_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "paper_trading" not in node.module
                assert "ml_feedback_engine" not in node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert "paper_trading" not in alias.name
                    assert "ml_feedback_engine" not in alias.name

    # Validate declarative Execution Simulator Design Contract (non-executable)
    spec = ExecutionSimulatorDesignSpec(
        simulation_domain=SimulationDomainMode.OPTIONS_PREMIUM_SIMULATION,
        option_data_mode=OptionDataMode.REAL_OPTION_OHLC,
        intrabar_ambiguity_policy=IntrabarAmbiguityPolicy.CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG,
    )
    assert spec.fill_model.timing_policy == ExecutionTimingPolicy.NEXT_COMPLETED_BAR_OPEN
    assert spec.cost_model.deduct_total_costs_from_cash_balance is True


def test_downloader_1d_start_of_day_and_transient_403_retry(tmp_path: Path):
    cal = HistoricalMarketCalendarAdapter()
    cfg = _temp_cfg(tmp_path, max_retries=2, retry_backoff_seconds=0.0)
    store = HistoricalDataStore(config=cfg)

    # First-day 09:15 IST caller bound for '1d' must expand chunk start to 00:00 IST so
    # Angel One returns day-0's 00:00 daily candle instead of omitting it, and transient
    # HTTP 403 WAF throttling recovers cleanly within max_retries.
    stub_ok = _StubAngelOneProvider(cal=cal, transient_403_calls=1)
    dl_ok = AngelOneHistoricalDataDownloader(provider=stub_ok, data_store=store, calendar_adapter=cal, config=cfg)
    res_ok = asyncio.run(
        dl_ok.download_and_store(
            instrument="NIFTY 50",
            timeframe="1d",
            from_time=datetime(2026, 11, 2, 9, 15, tzinfo=IST),
            to_time=datetime(2026, 11, 6, 15, 30, tzinfo=IST),
        )
    )
    assert res_ok.status == DownloadStatus.COMPLETED
    assert res_ok.blocked is False
    assert res_ok.bars_downloaded == 5
    assert stub_ok.calls[0]["from_date"].hour == 0 and stub_ok.calls[0]["from_date"].minute == 0
    assert len(stub_ok.calls) == 2

    # When HTTP 403 persists past max_retries, ingestion still fails closed as BLOCKED
    stub_blocked = _StubAngelOneProvider(cal=cal, transient_403_calls=5)
    dl_blocked = AngelOneHistoricalDataDownloader(provider=stub_blocked, data_store=store, calendar_adapter=cal, config=cfg)
    res_blocked = asyncio.run(
        dl_blocked.download_and_store(
            instrument="NIFTY 50",
            timeframe="1d",
            from_time=datetime(2026, 11, 2, 9, 15, tzinfo=IST),
            to_time=datetime(2026, 11, 6, 15, 30, tzinfo=IST),
        )
    )
    assert res_blocked.status == DownloadStatus.BLOCKED
    assert res_blocked.blocked is True
    assert res_blocked.bars_stored == 0


def test_replay_bounds_phase3_lookback_window_after_full_integrity_audit(tmp_path: Path):
    cal = HistoricalMarketCalendarAdapter()
    cfg = _temp_cfg(tmp_path, phase3_lookback_bars=240)
    as_of = datetime(2026, 6, 19, 15, 30, tzinfo=IST)

    # Supply > 250 bars (400 1m bars, 300 3m/5m bars) including an early swing-high spike that is
    # swept immediately (< 20 bars later) and then aged past 250 bars — previously triggering
    # Step 3.1's `SWEPT -> EXPIRED` error if unbounded.
    candles = {
        "1h": _fixture_ohlcv_df(_fixture_session_timestamps(cal, "1h", as_of, 50), timeframe="1h", scale=2.0),
        "15m": _fixture_ohlcv_df(_fixture_session_timestamps(cal, "15m", as_of, 80), timeframe="15m", scale=1.5),
        "5m": _fixture_ohlcv_df(_fixture_session_timestamps(cal, "5m", as_of, 300), timeframe="5m", scale=1.0),
        "3m": _fixture_ohlcv_df(_fixture_session_timestamps(cal, "3m", as_of, 300), timeframe="3m", scale=0.8),
        "1m": _fixture_ohlcv_df(_fixture_session_timestamps(cal, "1m", as_of, 400), timeframe="1m", scale=0.5),
    }
    # Deliberately create an early swing high + wick sweep in first 15 bars of 1m (> 380 bars before end)
    candles["1m"].loc[4, "high"] = 24250.0
    candles["1m"].loc[4, "close"] = 24120.0
    candles["1m"].loc[8, "high"] = 24252.5
    candles["1m"].loc[8, "close"] = 24110.0

    runner = DeterministicReplayRunner(calendar_adapter=cal, config=cfg)
    rep = runner.run_replay(
        instrument="NIFTY 50",
        replay_times=[as_of],
        candles_by_timeframe=candles,
    )
    assert rep.validation_status == ReplayValidationStatus.VALIDATED
    assert rep.points[0].bars_used_by_timeframe["1m"] == 240
    assert rep.points[0].bars_used_by_timeframe["3m"] == 240
    assert rep.points[0].bars_used_by_timeframe["5m"] == 240
    assert rep.points[0].bars_used_by_timeframe["15m"] == 80
    assert rep.points[0].bars_used_by_timeframe["1h"] == 50
    assert rep.points[0].confluence_score is None


