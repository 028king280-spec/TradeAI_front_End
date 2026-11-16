"""
AIVOLVE Phase 4 Step 4.6 — Data Quality & Integrity Validation Engine.

Reuses Step 4.2 `DataIntegrityAuditor` and `IntegrityStatus` classifications without
duplicating core checks or introducing contradictory status semantics, while adding:
- Multi-year calendar & special-session window validation (Muhurat, Union Budget, DR split)
- Strict separation between VERIFIED, PARTIAL, DEGRADED, and UNAVAILABLE
- Unexpected gap taxonomy & cross-source consistency verification
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as dt_time, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

from app.backtesting.configuration import (
    BacktestConfiguration,
    IST_ZONE,
    SUPPORTED_INDICES,
    TIMEFRAME_DURATION_MINUTES,
    normalize_instrument,
    normalize_timeframe,
    verify_index_governance,
)
from app.backtesting.data_integrity import (
    DISQUALIFYING_STATUSES,
    DataIntegrityAuditor,
    compute_candle_close_ist,
    compute_dataset_fingerprint,
)
from app.backtesting.models import (
    CalendarStatus,
    DataIntegrityReport,
    IntegrityIssue,
    IntegrityIssueSeverity,
    IntegrityStatus,
    MissingCandleInterval,
)
from app.backtesting.trade_lifecycle import deterministic_id

if TYPE_CHECKING:
    from app.backtesting.multi_year_calendar import MultiYearTradingCalendar


class DatasetQualityStatus(str, Enum):
    """Canonical Step 4.6 quality classification strictly consistent with IntegrityStatus."""

    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class UnexpectedGapSummary:
    trading_date: str
    gap_type: str  # WHOLE_SESSION_GAP | INTRADAY_GAP | BOUNDARY_GAP
    start_ist: str
    end_ist: str
    missing_bars: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceInconsistencyItem:
    timestamp_ist: str
    field_name: str
    primary_value: Any
    secondary_value: Any
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetValidationReport:
    """Comprehensive Step 4.6 quality & integrity assessment for a dataset slice."""

    validation_id: str
    instrument: str
    timeframe: str
    quality_status: DatasetQualityStatus
    integrity_status: IntegrityStatus
    calendar_status: CalendarStatus
    governance_locked: bool
    is_verified: bool
    is_usable: bool
    expected_from_ist: Optional[str]
    expected_to_ist: Optional[str]
    actual_from_ist: Optional[str]
    actual_to_ist: Optional[str]
    expected_trading_sessions: int
    trading_sessions_covered: int
    expected_candles: int
    actual_candles: int
    missing_candles: int
    duplicate_count: int
    out_of_order_count: int
    invalid_ohlc_count: int
    invalid_volume_count: int
    nan_inf_count: int
    grid_misalignment_count: int
    incomplete_candle_count: int
    session_boundary_violation_count: int
    wrong_timeframe_detected: bool
    synthetic_or_repaired_detected: bool
    source_inconsistency_count: int
    invalid_candles: int
    dataset_fingerprint: Optional[str]
    validated_at_utc: str
    issues: Tuple[IntegrityIssue, ...] = field(default_factory=tuple)
    missing_intervals: Tuple[MissingCandleInterval, ...] = field(default_factory=tuple)
    unexpected_gaps: Tuple[UnexpectedGapSummary, ...] = field(default_factory=tuple)
    source_inconsistencies: Tuple[SourceInconsistencyItem, ...] = field(default_factory=tuple)
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "quality_status": self.quality_status.value,
            "integrity_status": self.integrity_status.value,
            "calendar_status": self.calendar_status.value,
            "governance_locked": self.governance_locked,
            "is_verified": self.is_verified,
            "is_usable": self.is_usable,
            "expected_from_ist": self.expected_from_ist,
            "expected_to_ist": self.expected_to_ist,
            "actual_from_ist": self.actual_from_ist,
            "actual_to_ist": self.actual_to_ist,
            "expected_trading_sessions": self.expected_trading_sessions,
            "trading_sessions_covered": self.trading_sessions_covered,
            "expected_candles": self.expected_candles,
            "actual_candles": self.actual_candles,
            "missing_candles": self.missing_candles,
            "duplicate_count": self.duplicate_count,
            "out_of_order_count": self.out_of_order_count,
            "invalid_ohlc_count": self.invalid_ohlc_count,
            "invalid_volume_count": self.invalid_volume_count,
            "nan_inf_count": self.nan_inf_count,
            "grid_misalignment_count": self.grid_misalignment_count,
            "incomplete_candle_count": self.incomplete_candle_count,
            "session_boundary_violation_count": self.session_boundary_violation_count,
            "wrong_timeframe_detected": self.wrong_timeframe_detected,
            "synthetic_or_repaired_detected": self.synthetic_or_repaired_detected,
            "source_inconsistency_count": self.source_inconsistency_count,
            "invalid_candles": self.invalid_candles,
            "dataset_fingerprint": self.dataset_fingerprint,
            "validated_at_utc": self.validated_at_utc,
            "issues": [i.model_dump(mode="json") if hasattr(i, "model_dump") else asdict(i) for i in self.issues],
            "missing_intervals": [m.model_dump(mode="json") if hasattr(m, "model_dump") else asdict(m) for m in self.missing_intervals],
            "unexpected_gaps": [g.to_dict() for g in self.unexpected_gaps],
            "source_inconsistencies": [s.to_dict() for s in self.source_inconsistencies],
            "notes": list(self.notes),
        }


def _to_ist_dt(val: Any) -> Optional[datetime]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return None
        dt = val.to_pydatetime()
    elif isinstance(val, datetime):
        dt = val
    else:
        parsed = pd.to_datetime(val, errors="coerce")
        if pd.isna(parsed):
            return None
        dt = parsed.to_pydatetime()
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(IST_ZONE)


def _summarize_unexpected_gaps(
    missing_intervals: Sequence[MissingCandleInterval],
    expected_by_date: Dict[date, int],
) -> Tuple[UnexpectedGapSummary, ...]:
    if not missing_intervals:
        return ()

    grouped: Dict[str, List[MissingCandleInterval]] = {}
    for item in missing_intervals:
        grouped.setdefault(item.trading_date, []).append(item)

    summaries: List[UnexpectedGapSummary] = []
    for day_str in sorted(grouped.keys()):
        items = sorted(grouped[day_str], key=lambda x: x.expected_open_ist)
        d = date.fromisoformat(day_str)
        expected_total = expected_by_date.get(d, len(items))
        if expected_total > 0 and len(items) >= expected_total:
            gap_type = "WHOLE_SESSION_GAP"
        else:
            gap_type = "INTRADAY_GAP"
        summaries.append(
            UnexpectedGapSummary(
                trading_date=day_str,
                gap_type=gap_type,
                start_ist=items[0].expected_open_ist,
                end_ist=items[-1].expected_open_ist,
                missing_bars=len(items),
            )
        )
    return tuple(summaries)


def check_cross_source_consistency(
    primary_df: pd.DataFrame,
    secondary_df: pd.DataFrame,
    *,
    ohlc_rel_tol: float = 1e-4,
) -> Tuple[SourceInconsistencyItem, ...]:
    """
    Compares overlapping timestamps between primary and secondary OHLCV sources
    and flags timestamp alignment or OHLC discrepancies exceeding `ohlc_rel_tol`.
    """
    if primary_df is None or primary_df.empty or secondary_df is None or secondary_df.empty:
        return ()
    if "timestamp" not in primary_df.columns or "timestamp" not in secondary_df.columns:
        return ()

    p = primary_df.copy()
    s = secondary_df.copy()
    p["ts_norm"] = pd.to_datetime(p["timestamp"], utc=True, errors="coerce")
    s["ts_norm"] = pd.to_datetime(s["timestamp"], utc=True, errors="coerce")
    p = p.dropna(subset=["ts_norm"]).drop_duplicates(subset=["ts_norm"])
    s = s.dropna(subset=["ts_norm"]).drop_duplicates(subset=["ts_norm"])

    merged = p.merge(s, on="ts_norm", how="inner", suffixes=("_pri", "_sec"))
    items: List[SourceInconsistencyItem] = []
    for _, row in merged.iterrows():
        ts_ist = row["ts_norm"].tz_convert(IST_ZONE).strftime("%Y-%m-%dT%H:%M:%S+05:30")
        for col in ("open", "high", "low", "close"):
            c_pri = f"{col}_pri"
            c_sec = f"{col}_sec"
            if c_pri not in row or c_sec not in row:
                continue
            v1 = float(row[c_pri])
            v2 = float(row[c_sec])
            if not (np.isfinite(v1) and np.isfinite(v2)):
                items.append(
                    SourceInconsistencyItem(
                        timestamp_ist=ts_ist,
                        field_name=col,
                        primary_value=v1,
                        secondary_value=v2,
                        detail="Non-finite OHLC value in cross-source comparison",
                    )
                )
                continue
            denom = max(abs(v1), abs(v2), 1e-9)
            rel_diff = abs(v1 - v2) / denom
            if rel_diff > ohlc_rel_tol:
                items.append(
                    SourceInconsistencyItem(
                        timestamp_ist=ts_ist,
                        field_name=col,
                        primary_value=round(v1, 4),
                        secondary_value=round(v2, 4),
                        detail=f"Cross-source {col} mismatch rel_diff={rel_diff:.6f} > tol={ohlc_rel_tol}",
                    )
                )
    return tuple(items)


class DatasetValidator:
    """
    Comprehensive Step 4.6 dataset quality & integrity engine.

    Composes Step 4.2 `DataIntegrityAuditor` while properly handling multi-year calendars
    and special trading sessions (Muhurat Trading, Union Budget weekend sessions,
    DR split sessions, exceptional closures).
    """

    def __init__(
        self,
        *,
        calendar_adapter: Optional["MultiYearTradingCalendar"] = None,
        config: Optional[BacktestConfiguration] = None,
        auditor: Optional[DataIntegrityAuditor] = None,
    ) -> None:
        self.config = config or BacktestConfiguration()
        if calendar_adapter is None:
            from app.backtesting.multi_year_calendar import MultiYearTradingCalendar

            self.calendar = MultiYearTradingCalendar()
        else:
            self.calendar = calendar_adapter
        self.auditor = auditor or DataIntegrityAuditor(
            calendar_adapter=self.calendar,
            market_open_hhmm=self.config.market_open_hhmm,
            market_close_hhmm=self.config.market_close_hhmm,
            strict_missing_intervals=self.config.strict_missing_intervals,
            require_volume_column=self.config.require_volume_column,
        )

    def _validate_ohlcv_intrinsic(
        self,
        df: pd.DataFrame,
        *,
        instrument: str,
        timeframe: str,
        require_all_completed: bool = True,
        as_of_time: Optional[datetime] = None,
    ) -> Tuple[List[IntegrityIssue], Dict[str, Any]]:
        """
        Validates intrinsic row-level & sequence integrity for special-session/full-df checks,
        ensuring compatibility with DataIntegrityAuditor and avoiding duplicate logic on regular days.
        """
        issues: List[IntegrityIssue] = []
        counts: Dict[str, Any] = {
            "duplicate_count": 0,
            "out_of_order_count": 0,
            "invalid_ohlc_count": 0,
            "invalid_volume_count": 0,
            "nan_inf_count": 0,
            "grid_misalignment_count": 0,
            "incomplete_candle_count": 0,
            "session_boundary_violation_count": 0,
            "wrong_timeframe_detected": False,
            "synthetic_or_repaired_detected": False,
        }

        attrs = getattr(df, "attrs", {}) or {}
        if attrs.get("is_mock") is True or attrs.get("synthetic") is True or attrs.get("is_synthetic") is True:
            counts["synthetic_or_repaired_detected"] = True
            issues.append(
                IntegrityIssue(
                    code="SYNTHETIC_FEED_REJECTED",
                    severity=IntegrityIssueSeverity.ERROR,
                    message="Dataset carries synthetic/mock provenance flag.",
                )
            )
        if attrs.get("ohlc_repaired") is True:
            counts["synthetic_or_repaired_detected"] = True
            issues.append(
                IntegrityIssue(
                    code="REPAIRED_FEED_REJECTED",
                    severity=IntegrityIssueSeverity.ERROR,
                    message="Dataset was silently repaired (ohlc_repaired=True).",
                )
            )
        feed_status = str(attrs.get("feedStatus", "") or "").upper()
        data_status = str(attrs.get("dataStatus", "") or "").upper()
        if feed_status in DISQUALIFYING_STATUSES or data_status in DISQUALIFYING_STATUSES:
            counts["synthetic_or_repaired_detected"] = True
            issues.append(
                IntegrityIssue(
                    code="DISQUALIFYING_FEED_STATUS",
                    severity=IntegrityIssueSeverity.ERROR,
                    message=f"Disqualifying status feedStatus={feed_status!r} dataStatus={data_status!r}.",
                )
            )

        reported_tf = attrs.get("timeframe")
        if reported_tf is not None:
            try:
                if normalize_timeframe(str(reported_tf)) != timeframe:
                    counts["wrong_timeframe_detected"] = True
                    issues.append(
                        IntegrityIssue(
                            code="TIMEFRAME_MISMATCH",
                            severity=IntegrityIssueSeverity.ERROR,
                            message=f"Expected timeframe {timeframe}, got {reported_tf}.",
                        )
                    )
            except ValueError:
                counts["wrong_timeframe_detected"] = True
                issues.append(
                    IntegrityIssue(
                        code="INVALID_TIMEFRAME_ATTR",
                        severity=IntegrityIssueSeverity.ERROR,
                        message=f"Unrecognized timeframe attr {reported_tf!r}.",
                    )
                )

        required_cols = {"timestamp", "open", "high", "low", "close"}
        if self.config.require_volume_column:
            required_cols.add("volume")
        missing_cols = sorted(required_cols - set(df.columns))
        if missing_cols:
            issues.append(
                IntegrityIssue(
                    code="MISSING_REQUIRED_COLUMNS",
                    severity=IntegrityIssueSeverity.ERROR,
                    message=f"Missing required columns: {missing_cols}",
                )
            )
            counts["invalid_ohlc_count"] += len(df)
            return issues, counts

        # Parse & inspect timestamps row-by-row for timezone awareness, ordering, duplicates, grid & boundary
        step_min = TIMEFRAME_DURATION_MINUTES[timeframe]
        ist_times: List[Optional[datetime]] = []
        seen_ts: Set[int] = set()
        prev_epoch: Optional[int] = None
        invalid_row_indices: Set[int] = set()

        for idx, raw_ts in enumerate(df["timestamp"].tolist()):
            dt_ist = _to_ist_dt(raw_ts)
            if dt_ist is None:
                counts["nan_inf_count"] += 1
                counts["session_boundary_violation_count"] += 1
                invalid_row_indices.add(idx)
                issues.append(
                    IntegrityIssue(
                        code="INVALID_OR_NAIVE_TIMESTAMP",
                        severity=IntegrityIssueSeverity.ERROR,
                        message=f"Row {idx} has null or timezone-naive timestamp {raw_ts!r}.",
                        row_index=idx,
                    )
                )
                ist_times.append(None)
                continue

            ist_times.append(dt_ist)
            epoch_ms = int(round(dt_ist.timestamp() * 1000))
            if epoch_ms in seen_ts:
                counts["duplicate_count"] += 1
                invalid_row_indices.add(idx)
                issues.append(
                    IntegrityIssue(
                        code="DUPLICATE_TIMESTAMP",
                        severity=IntegrityIssueSeverity.ERROR,
                        message=f"Duplicate timestamp at row {idx}: {dt_ist.isoformat()}",
                        row_index=idx,
                        timestamp_ist=dt_ist.isoformat(),
                    )
                )
            else:
                seen_ts.add(epoch_ms)

            if prev_epoch is not None and epoch_ms < prev_epoch:
                counts["out_of_order_count"] += 1
                invalid_row_indices.add(idx)
                issues.append(
                    IntegrityIssue(
                        code="NON_MONOTONIC_TIMESTAMPS",
                        severity=IntegrityIssueSeverity.ERROR,
                        message=f"Out-of-order timestamp at row {idx}: {dt_ist.isoformat()}",
                        row_index=idx,
                        timestamp_ist=dt_ist.isoformat(),
                    )
                )
            elif prev_epoch is not None and epoch_ms > prev_epoch:
                prev_epoch = epoch_ms
            elif prev_epoch is None:
                prev_epoch = epoch_ms

            # Calendar & session boundary check using MultiYearTradingCalendar
            d = dt_ist.date()
            cal_res = self.calendar.validate_date(d)
            if cal_res.status == CalendarStatus.CALENDAR_UNAVAILABLE:
                counts["session_boundary_violation_count"] += 1
                invalid_row_indices.add(idx)
                issues.append(
                    IntegrityIssue(
                        code="CALENDAR_UNAVAILABLE",
                        severity=IntegrityIssueSeverity.ERROR,
                        message=f"Calendar unavailable for {d.isoformat()}.",
                        row_index=idx,
                        timestamp_ist=dt_ist.isoformat(),
                    )
                )
            elif not cal_res.is_trading_day:
                counts["session_boundary_violation_count"] += 1
                invalid_row_indices.add(idx)
                issues.append(
                    IntegrityIssue(
                        code="NON_TRADING_DAY_BAR",
                        severity=IntegrityIssueSeverity.ERROR,
                        message=f"Bar present on non-trading day {d.isoformat()} ({cal_res.reason}).",
                        row_index=idx,
                        timestamp_ist=dt_ist.isoformat(),
                    )
                )
            else:
                windows = self.calendar.get_session_windows(d)
                if timeframe == "1d":
                    # Daily bar: allow 00:00:00 or 09:15:00 / window open
                    t_only = dt_ist.time().replace(microsecond=0)
                    valid_daily_times = {dt_time(0, 0), dt_time(9, 15)}
                    for w in windows:
                        valid_daily_times.add(w.open_time)
                    if t_only not in valid_daily_times:
                        counts["session_boundary_violation_count"] += 1
                        invalid_row_indices.add(idx)
                        issues.append(
                            IntegrityIssue(
                                code="OUT_OF_SESSION_BOUNDARY",
                                severity=IntegrityIssueSeverity.ERROR,
                                message=f"Unexpected daily bar timestamp {t_only} on {d.isoformat()}.",
                                row_index=idx,
                                timestamp_ist=dt_ist.isoformat(),
                            )
                        )
                else:
                    # Intraday: check bar opens cleanly inside a declared session window & aligns to timeframe grid
                    t_only = dt_ist.time().replace(microsecond=0)
                    matched_window = None
                    for w in windows:
                        if w.open_time <= t_only < w.close_time:
                            matched_window = w
                            break
                    if matched_window is None:
                        counts["session_boundary_violation_count"] += 1
                        invalid_row_indices.add(idx)
                        issues.append(
                            IntegrityIssue(
                                code="OUT_OF_SESSION_BOUNDARY",
                                severity=IntegrityIssueSeverity.ERROR,
                                message=(
                                    f"Intraday bar {dt_ist.isoformat()} outside session windows "
                                    f"{[(w.open_hhmm, w.close_hhmm) for w in windows]}."
                                ),
                                row_index=idx,
                                timestamp_ist=dt_ist.isoformat(),
                            )
                        )
                    else:
                        if dt_ist.second != 0 or dt_ist.microsecond != 0:
                            counts["grid_misalignment_count"] += 1
                            invalid_row_indices.add(idx)
                            issues.append(
                                IntegrityIssue(
                                    code="TIMEFRAME_GRID_MISALIGNMENT",
                                    severity=IntegrityIssueSeverity.ERROR,
                                    message=f"Sub-minute offset on bar {dt_ist.isoformat()}.",
                                    row_index=idx,
                                    timestamp_ist=dt_ist.isoformat(),
                                )
                            )
                        else:
                            w_start = datetime.combine(d, matched_window.open_time, tzinfo=IST_ZONE)
                            delta_min = int((dt_ist - w_start).total_seconds() // 60)
                            if delta_min % step_min != 0:
                                counts["grid_misalignment_count"] += 1
                                invalid_row_indices.add(idx)
                                issues.append(
                                    IntegrityIssue(
                                        code="TIMEFRAME_GRID_MISALIGNMENT",
                                        severity=IntegrityIssueSeverity.ERROR,
                                        message=(
                                            f"Bar {dt_ist.isoformat()} off {timeframe} grid anchored at "
                                            f"{matched_window.open_hhmm}."
                                        ),
                                        row_index=idx,
                                        timestamp_ist=dt_ist.isoformat(),
                                    )
                                )
                        if require_all_completed:
                            close_dt = compute_candle_close_ist(dt_ist, timeframe, matched_window.close_time)
                            if "is_complete" in df.columns:
                                is_comp = df.iloc[idx]["is_complete"]
                                if not bool(is_comp):
                                    counts["incomplete_candle_count"] += 1
                                    invalid_row_indices.add(idx)
                                    issues.append(
                                        IntegrityIssue(
                                            code="INCOMPLETE_CANDLE",
                                            severity=IntegrityIssueSeverity.ERROR,
                                            message=f"Incomplete forming bar at {dt_ist.isoformat()}.",
                                            row_index=idx,
                                            timestamp_ist=dt_ist.isoformat(),
                                        )
                                    )
                            if as_of_time is not None:
                                as_of_ist = _to_ist_dt(as_of_time)
                                if as_of_ist is not None and close_dt > as_of_ist:
                                    counts["incomplete_candle_count"] += 1
                                    invalid_row_indices.add(idx)
                                    issues.append(
                                        IntegrityIssue(
                                            code="FORMING_CANDLE_AFTER_AS_OF",
                                            severity=IntegrityIssueSeverity.ERROR,
                                            message=f"Bar closes at {close_dt.isoformat()} > as_of {as_of_ist.isoformat()}.",
                                            row_index=idx,
                                            timestamp_ist=dt_ist.isoformat(),
                                        )
                                    )

        # Price & Volume checks
        for idx, row in df.reset_index(drop=True).iterrows():
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            prices = [o, h, l, c]
            bad_num = False
            for val in prices:
                try:
                    fval = float(val)
                except (TypeError, ValueError):
                    bad_num = True
                    break
                if not np.isfinite(fval) or fval <= 0.0:
                    bad_num = True
                    break
            if bad_num:
                counts["nan_inf_count"] += 1
                counts["invalid_ohlc_count"] += 1
                invalid_row_indices.add(idx)
                issues.append(
                    IntegrityIssue(
                        code="INVALID_PRICE_VALUE",
                        severity=IntegrityIssueSeverity.ERROR,
                        message=f"Non-finite or non-positive OHLC price at row {idx}.",
                        row_index=idx,
                    )
                )
            else:
                fo, fh, fl, fc = float(o), float(h), float(l), float(c)
                if fh < max(fo, fc, fl) or fl > min(fo, fc, fh) or fh < fl:
                    counts["invalid_ohlc_count"] += 1
                    invalid_row_indices.add(idx)
                    issues.append(
                        IntegrityIssue(
                            code="OHLC_GEOMETRY_VIOLATION",
                            severity=IntegrityIssueSeverity.ERROR,
                            message=f"OHLC geometry violated at row {idx}: O={fo}, H={fh}, L={fl}, C={fc}.",
                            row_index=idx,
                        )
                    )

            if "volume" in df.columns:
                v_raw = row["volume"]
                try:
                    fv = float(v_raw)
                    if not np.isfinite(fv) or fv < 0.0:
                        counts["invalid_volume_count"] += 1
                        invalid_row_indices.add(idx)
                        issues.append(
                            IntegrityIssue(
                                code="INVALID_VOLUME",
                                severity=IntegrityIssueSeverity.ERROR,
                                message=f"Invalid/negative/non-finite volume {v_raw!r} at row {idx}.",
                                row_index=idx,
                            )
                        )
                except (TypeError, ValueError):
                    counts["invalid_volume_count"] += 1
                    invalid_row_indices.add(idx)
                    issues.append(
                        IntegrityIssue(
                            code="INVALID_VOLUME",
                            severity=IntegrityIssueSeverity.ERROR,
                            message=f"Non-numeric volume {v_raw!r} at row {idx}.",
                            row_index=idx,
                        )
                    )

        counts["invalid_candles"] = len(invalid_row_indices)
        return issues, counts

    def audit_for_store(
        self,
        df: pd.DataFrame,
        *,
        instrument: str,
        timeframe: str,
        expected_from_ist: Optional[datetime] = None,
        expected_to_ist: Optional[datetime] = None,
        require_all_completed: bool = True,
        check_missing_intervals: bool = True,
        as_of_time: Optional[datetime] = None,
    ) -> DataIntegrityReport:
        """
        Adapter bridging multi-year/special-session validation cleanly to `DataIntegrityReport`
        expected by `HistoricalDataStore.save_candles(auditor=...)`.
        """
        vrep = self.validate_dataset(
            df,
            instrument=instrument,
            timeframe=timeframe,
            expected_from_ist=expected_from_ist,
            expected_to_ist=expected_to_ist,
            require_all_completed=require_all_completed,
            check_missing_intervals=check_missing_intervals,
            as_of_time=as_of_time,
        )
        enforce_missing = bool(check_missing_intervals and self.config.strict_missing_intervals)
        is_store_valid = (
            vrep.quality_status == DatasetQualityStatus.VERIFIED
            if enforce_missing
            else vrep.quality_status in {DatasetQualityStatus.VERIFIED, DatasetQualityStatus.PARTIAL}
        )
        return DataIntegrityReport(
            is_valid=is_store_valid,
            status=IntegrityStatus.PASSED if is_store_valid else vrep.integrity_status,
            instrument=vrep.instrument,
            timeframe=vrep.timeframe,
            total_bars=vrep.actual_candles,
            valid_bars=max(0, vrep.actual_candles - vrep.invalid_candles),
            rejected_reasons=tuple(i.message for i in vrep.issues[:10]),
            issues=vrep.issues,
            duplicate_timestamps=tuple(
                i.timestamp_ist
                for i in vrep.issues
                if i.code == "DUPLICATE_TIMESTAMP" and i.timestamp_ist
            ),
            missing_intervals=vrep.missing_intervals,
            repaired_detected=vrep.synthetic_or_repaired_detected,
            synthetic_detected=vrep.synthetic_or_repaired_detected,
            incomplete_candles_detected=int(vrep.incomplete_candle_count),
            tz_name="Asia/Kolkata",
            first_timestamp_ist=vrep.actual_from_ist,
            last_timestamp_ist=vrep.actual_to_ist,
            dataset_fingerprint=vrep.dataset_fingerprint or "",
        )

    def audit_dataframe(
        self,
        df: pd.DataFrame,
        *,
        instrument: str,
        timeframe: str,
        as_of_time: Optional[datetime] = None,
        expected_from_ist: Optional[datetime] = None,
        expected_to_ist: Optional[datetime] = None,
        require_all_completed: bool = True,
        check_missing_intervals: bool = True,
        **kwargs: Any,
    ) -> DataIntegrityReport:
        """Drop-in compatible method signature for `HistoricalDataStore.save_candles(auditor=...)`."""
        return self.audit_for_store(
            df,
            instrument=instrument,
            timeframe=timeframe,
            expected_from_ist=expected_from_ist,
            expected_to_ist=expected_to_ist,
            require_all_completed=require_all_completed,
            check_missing_intervals=check_missing_intervals,
            as_of_time=as_of_time,
        )

    def validate_dataset(
        self,
        df: pd.DataFrame,
        *,
        instrument: str,
        timeframe: str,
        expected_from_ist: Optional[datetime] = None,
        expected_to_ist: Optional[datetime] = None,
        require_all_completed: bool = True,
        check_missing_intervals: bool = True,
        as_of_time: Optional[datetime] = None,
        secondary_df: Optional[pd.DataFrame] = None,
    ) -> DatasetValidationReport:
        canonical_inst = normalize_instrument(instrument)
        canonical_tf = normalize_timeframe(timeframe)
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1. Governance Lock Check (SENSEX locked by default)
        gov_ok, _gov_status, gov_info = verify_index_governance(
            canonical_inst,
            sensex_governance_approved=self.config.sensex_governance_approved,
            governance_db_path=self.config.governance_ledger_path,
        )
        if not gov_ok:
            gov_reason = str(gov_info.get("reason") or _gov_status or "GOVERNANCE_LOCKOUT")
            issue = IntegrityIssue(
                code="GOVERNANCE_LOCKED",
                severity=IntegrityIssueSeverity.ERROR,
                message=gov_reason,
            )
            return DatasetValidationReport(
                validation_id=deterministic_id("VAL", {"i": canonical_inst, "tf": canonical_tf, "ts": now_utc}, length=16),
                instrument=canonical_inst,
                timeframe=canonical_tf,
                quality_status=DatasetQualityStatus.UNAVAILABLE,
                integrity_status=IntegrityStatus.FAILED,
                calendar_status=CalendarStatus.TRADING_DAY,
                governance_locked=True,
                is_verified=False,
                is_usable=False,
                expected_from_ist=expected_from_ist.isoformat() if expected_from_ist else None,
                expected_to_ist=expected_to_ist.isoformat() if expected_to_ist else None,
                actual_from_ist=None,
                actual_to_ist=None,
                expected_trading_sessions=0,
                trading_sessions_covered=0,
                expected_candles=0,
                actual_candles=0,
                missing_candles=0,
                duplicate_count=0,
                out_of_order_count=0,
                invalid_ohlc_count=0,
                invalid_volume_count=0,
                nan_inf_count=0,
                grid_misalignment_count=0,
                incomplete_candle_count=0,
                session_boundary_violation_count=0,
                wrong_timeframe_detected=False,
                synthetic_or_repaired_detected=False,
                source_inconsistency_count=0,
                invalid_candles=0,
                dataset_fingerprint=None,
                validated_at_utc=now_utc,
                issues=(issue,),
                notes=(gov_reason,),
            )

        # 2. Empty DataFrame -> UNAVAILABLE (not VERIFIED!)
        if df is None or df.empty:
            start_dt = _to_ist_dt(expected_from_ist) if expected_from_ist else None
            end_dt = _to_ist_dt(expected_to_ist) if expected_to_ist else None
            expected_count = 0
            expected_sessions = 0
            cal_status = CalendarStatus.TRADING_DAY
            notes: List[str] = ["No genuine historical candles available in storage."]
            if start_dt and end_dt:
                try:
                    opens_map = self.calendar.expected_opens_by_date(canonical_tf, start_dt, end_dt)
                    expected_sessions = len(opens_map)
                    expected_count = sum(len(v) for v in opens_map.values())
                except Exception as exc:
                    cal_status = CalendarStatus.CALENDAR_UNAVAILABLE
                    notes.append(str(exc))

            return DatasetValidationReport(
                validation_id=deterministic_id("VAL", {"i": canonical_inst, "tf": canonical_tf, "empty": True}, length=16),
                instrument=canonical_inst,
                timeframe=canonical_tf,
                quality_status=DatasetQualityStatus.UNAVAILABLE,
                integrity_status=IntegrityStatus.FAILED,
                calendar_status=cal_status,
                governance_locked=False,
                is_verified=False,
                is_usable=False,
                expected_from_ist=start_dt.isoformat() if start_dt else None,
                expected_to_ist=end_dt.isoformat() if end_dt else None,
                actual_from_ist=None,
                actual_to_ist=None,
                expected_trading_sessions=expected_sessions,
                trading_sessions_covered=0,
                expected_candles=expected_count,
                actual_candles=0,
                missing_candles=expected_count,
                duplicate_count=0,
                out_of_order_count=0,
                invalid_ohlc_count=0,
                invalid_volume_count=0,
                nan_inf_count=0,
                grid_misalignment_count=0,
                incomplete_candle_count=0,
                session_boundary_violation_count=0,
                wrong_timeframe_detected=False,
                synthetic_or_repaired_detected=False,
                source_inconsistency_count=0,
                invalid_candles=0,
                dataset_fingerprint=None,
                validated_at_utc=now_utc,
                issues=(
                    IntegrityIssue(
                        code="EMPTY_DATASET",
                        severity=IntegrityIssueSeverity.WARNING,
                        message=f"No stored candles for {canonical_inst} {canonical_tf}.",
                    ),
                ),
                notes=tuple(notes),
            )

        # 3. Intrinsic row & sequence checks
        issues, counts = self._validate_ohlcv_intrinsic(
            df,
            instrument=canonical_inst,
            timeframe=canonical_tf,
            require_all_completed=require_all_completed,
            as_of_time=as_of_time,
        )

        # Determine IST date bounds
        valid_ist_times = sorted(
            dt for dt in (_to_ist_dt(v) for v in df["timestamp"].tolist()) if dt is not None
        )
        actual_from = valid_ist_times[0] if valid_ist_times else None
        actual_to = valid_ist_times[-1] if valid_ist_times else None
        range_start = _to_ist_dt(expected_from_ist) or actual_from
        range_end = _to_ist_dt(expected_to_ist) or actual_to

        # Special handling if expected range wasn't passed: cover full first-to-last trading day
        if expected_from_ist is None and actual_from is not None:
            windows = self.calendar.get_session_windows(actual_from.date())
            day_start_t = windows[0].open_time if windows else dt_time(9, 15)
            range_start = datetime.combine(actual_from.date(), day_start_t if canonical_tf != "1d" else dt_time(0, 0), tzinfo=IST_ZONE)
        if expected_to_ist is None and actual_to is not None:
            windows = self.calendar.get_session_windows(actual_to.date())
            day_end_t = windows[-1].close_time if windows else dt_time(15, 30)
            range_end = datetime.combine(actual_to.date(), day_end_t, tzinfo=IST_ZONE)

        # 4. Also cross-check regular days through unmodified Step 4.2 DataIntegrityAuditor
        #    so no rule implemented in Step 4.2 can silently diverge.
        regular_dates: Set[date] = set()
        for dt_val in valid_ist_times:
            d = dt_val.date()
            if d.year in self.calendar.covered_years:
                if not self.calendar.is_special_session(d) and self.calendar.is_trading_day(d):
                    regular_dates.add(d)
        if regular_dates and len(issues) == 0:
            sub_mask = [
                (_to_ist_dt(v) is not None and _to_ist_dt(v).date() in regular_dates)
                for v in df["timestamp"].tolist()
            ]
            reg_df = df.loc[sub_mask].reset_index(drop=True)
            if not reg_df.empty:
                step42_report = self.auditor.audit_dataframe(
                    reg_df,
                    instrument=canonical_inst,
                    timeframe=canonical_tf,
                    require_all_completed=require_all_completed,
                    check_missing_intervals=False,
                    as_of_time=as_of_time,
                )
                for iss in step42_report.issues:
                    if iss.code not in {existing.code for existing in issues}:
                        issues.append(iss)
                counts["duplicate_count"] = max(
                    counts["duplicate_count"], len(step42_report.duplicate_timestamps)
                )
                if step42_report.incomplete_candles_detected:
                    counts["incomplete_candle_count"] = max(counts["incomplete_candle_count"], 1)
                counts["synthetic_or_repaired_detected"] = (
                    counts["synthetic_or_repaired_detected"]
                    or step42_report.synthetic_detected
                    or step42_report.repaired_detected
                )

        # 5. Missing intervals & trading sessions via MultiYearTradingCalendar
        cal_status = CalendarStatus.TRADING_DAY
        missing_intervals: List[MissingCandleInterval] = []
        expected_opens_by_date: Dict[date, List[datetime]] = {}
        notes_list: List[str] = []

        if range_start is not None and range_end is not None:
            try:
                expected_opens_by_date = self.calendar.expected_opens_by_date(
                    canonical_tf,
                    range_start,
                    range_end,
                )
            except Exception as exc:
                cal_status = CalendarStatus.CALENDAR_UNAVAILABLE
                issues.append(
                    IntegrityIssue(
                        code="CALENDAR_UNAVAILABLE",
                        severity=IntegrityIssueSeverity.ERROR,
                        message=str(exc),
                    )
                )
                notes_list.append(str(exc))

        actual_epoch_set: Set[int] = set()
        actual_date_set: Set[date] = set()
        for dt_val in valid_ist_times:
            actual_date_set.add(dt_val.date())
            if canonical_tf == "1d":
                actual_epoch_set.add(int(dt_val.date().toordinal()))
            else:
                actual_epoch_set.add(int(round(dt_val.timestamp())))

        expected_candles = 0
        expected_sessions = len(expected_opens_by_date)
        for d, opens_list in expected_opens_by_date.items():
            expected_candles += len(opens_list)
            if check_missing_intervals:
                for exp_open in opens_list:
                    key = int(d.toordinal()) if canonical_tf == "1d" else int(round(exp_open.timestamp()))
                    if key not in actual_epoch_set:
                        windows = self.calendar.get_session_windows(d)
                        close_time_t = windows[-1].close_time if windows else dt_time(15, 30)
                        exp_close = compute_candle_close_ist(exp_open, canonical_tf, close_time_t)
                        missing_intervals.append(
                            MissingCandleInterval(
                                timeframe=canonical_tf,
                                trading_date=d.isoformat(),
                                expected_open_ist=exp_open.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
                                expected_close_ist=exp_close.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
                                reason="MISSING_EXPECTED_SESSION_BAR",
                            )
                        )

        expected_count_by_date = {d: len(v) for d, v in expected_opens_by_date.items()}
        unexpected_gaps = _summarize_unexpected_gaps(missing_intervals, expected_count_by_date)

        # 6. Cross-source inconsistency check if secondary source supplied
        source_inconsistencies: Tuple[SourceInconsistencyItem, ...] = ()
        if secondary_df is not None:
            source_inconsistencies = check_cross_source_consistency(df, secondary_df)
            if source_inconsistencies:
                issues.append(
                    IntegrityIssue(
                        code="SOURCE_INCONSISTENCY",
                        severity=IntegrityIssueSeverity.WARNING,
                        message=f"Detected {len(source_inconsistencies)} cross-source OHLC inconsistencies.",
                    )
                )

        if missing_intervals:
            issues.append(
                IntegrityIssue(
                    code="MISSING_CANDLE_INTERVALS",
                    severity=IntegrityIssueSeverity.WARNING,
                    message=f"Missing {len(missing_intervals)} expected {canonical_tf} candle(s).",
                )
            )

        # 7. Canonical Step 4.6 Quality Status Classification (zero contradictory semantics)
        has_intrinsic_defect = any(
            (
                counts["duplicate_count"] > 0,
                counts["out_of_order_count"] > 0,
                counts["invalid_ohlc_count"] > 0,
                counts["invalid_volume_count"] > 0,
                counts["nan_inf_count"] > 0,
                counts["grid_misalignment_count"] > 0,
                counts["incomplete_candle_count"] > 0,
                counts["session_boundary_violation_count"] > 0,
                counts["wrong_timeframe_detected"],
                counts["synthetic_or_repaired_detected"],
                len(source_inconsistencies) > 0,
            )
        )

        missing_count = len(missing_intervals) if check_missing_intervals else max(0, expected_candles - len(valid_ist_times))
        sessions_covered = len(actual_date_set)

        if cal_status == CalendarStatus.CALENDAR_UNAVAILABLE:
            quality_status = DatasetQualityStatus.DEGRADED
            integrity_status = IntegrityStatus.FAILED
        elif has_intrinsic_defect:
            quality_status = DatasetQualityStatus.DEGRADED
            integrity_status = IntegrityStatus.FAILED
        elif missing_count > 0 or (expected_sessions > 0 and sessions_covered < expected_sessions):
            quality_status = DatasetQualityStatus.PARTIAL
            integrity_status = IntegrityStatus.PASSED if not check_missing_intervals else IntegrityStatus.FAILED
            notes_list.append(
                f"Intrinsic OHLCV checks passed, but {missing_count} expected candle(s) are missing across "
                f"{sessions_covered}/{expected_sessions} session(s) -> classified PARTIAL, never VERIFIED."
            )
        else:
            quality_status = DatasetQualityStatus.VERIFIED
            integrity_status = IntegrityStatus.PASSED

        fingerprint: Optional[str] = None
        if not has_intrinsic_defect and len(valid_ist_times) == len(df):
            fingerprint = compute_dataset_fingerprint(
                df,
                instrument=canonical_inst,
                timeframe=canonical_tf,
                timestamps_ist=valid_ist_times,
            )
        val_id = deterministic_id(
            "VAL",
            {
                "instrument": canonical_inst,
                "timeframe": canonical_tf,
                "fp": fingerprint,
                "status": quality_status.value,
                "missing": missing_count,
            },
            length=16,
        )

        return DatasetValidationReport(
            validation_id=val_id,
            instrument=canonical_inst,
            timeframe=canonical_tf,
            quality_status=quality_status,
            integrity_status=integrity_status,
            calendar_status=cal_status,
            governance_locked=False,
            is_verified=(quality_status == DatasetQualityStatus.VERIFIED),
            is_usable=(quality_status in {DatasetQualityStatus.VERIFIED, DatasetQualityStatus.PARTIAL}),
            expected_from_ist=range_start.strftime("%Y-%m-%dT%H:%M:%S+05:30") if range_start else None,
            expected_to_ist=range_end.strftime("%Y-%m-%dT%H:%M:%S+05:30") if range_end else None,
            actual_from_ist=actual_from.strftime("%Y-%m-%dT%H:%M:%S+05:30") if actual_from else None,
            actual_to_ist=actual_to.strftime("%Y-%m-%dT%H:%M:%S+05:30") if actual_to else None,
            expected_trading_sessions=expected_sessions,
            trading_sessions_covered=sessions_covered,
            expected_candles=expected_candles,
            actual_candles=len(df),
            missing_candles=missing_count,
            duplicate_count=int(counts["duplicate_count"]),
            out_of_order_count=int(counts["out_of_order_count"]),
            invalid_ohlc_count=int(counts["invalid_ohlc_count"]),
            invalid_volume_count=int(counts["invalid_volume_count"]),
            nan_inf_count=int(counts["nan_inf_count"]),
            grid_misalignment_count=int(counts["grid_misalignment_count"]),
            incomplete_candle_count=int(counts["incomplete_candle_count"]),
            session_boundary_violation_count=int(counts["session_boundary_violation_count"]),
            wrong_timeframe_detected=bool(counts["wrong_timeframe_detected"]),
            synthetic_or_repaired_detected=bool(counts["synthetic_or_repaired_detected"]),
            source_inconsistency_count=len(source_inconsistencies),
            invalid_candles=int(counts["invalid_candles"]),
            dataset_fingerprint=fingerprint,
            validated_at_utc=now_utc,
            issues=tuple(issues),
            missing_intervals=tuple(missing_intervals),
            unexpected_gaps=unexpected_gaps,
            source_inconsistencies=source_inconsistencies,
            notes=tuple(notes_list),
        )
