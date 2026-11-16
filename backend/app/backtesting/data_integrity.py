"""
AIVOLVE Phase 4 Step 4.2 — Strict Fail-Closed Historical Data Integrity Auditor.

Validates OHLCV candle datasets without ever silently repairing, forward-filling,
clamping, or fabricating missing data.

Checks:
- Required schema & absence of synthetic/mock/repaired flags
- Explicit timezone-awareness & uniform offset converted strictly to Asia/Kolkata
- Strictly ascending chronological timestamps with duplicate detection
- Positive, finite OHLC prices + mathematical invariants (high >= max(o,c), low <= min(o,c))
- Finite non-negative volumes
- Explicit IST market session [09:15, 15:30) grid & exchange trading calendar checks
- Completed candle enforcement (`close_time <= as_of_time` & `is_complete=True` if present)
- Missing intraday interval and missing trading session detection
- Canonical SHA-256 dataset fingerprinting over raw numeric values
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

from app.backtesting.calendar_adapter import (
    CalendarUnavailableError,
    HistoricalMarketCalendarAdapter,
)
from app.backtesting.configuration import (
    IST_ZONE,
    MARKET_CLOSE_HHMM,
    MARKET_OPEN_HHMM,
    TIMEFRAME_DURATION_MINUTES,
    normalize_instrument,
    normalize_timeframe,
)
from app.backtesting.models import (
    CalendarStatus,
    DataIntegrityReport,
    IntegrityIssue,
    IntegrityIssueSeverity,
    IntegrityStatus,
    MissingCandleInterval,
)

DISQUALIFYING_STATUSES: Set[str] = {
    "DATA_OFFLINE",
    "DATA_UNAVAILABLE",
    "STALE",
    "STALE_TICK",
    "DEGRADED",
    "ANOMALOUS",
    "SYNTHETIC",
    "OFFLINE",
    "UNAVAILABLE",
    "MOCK",
    "UNKNOWN",
    "INVALID_DATA",
    "CALENDAR_UNAVAILABLE",
    "NON_TRADING_DAY",
    "GOVERNANCE_LOCKOUT",
}


def _parse_hhmm(hhmm: str) -> dt_time:
    parts = hhmm.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Expected HH:MM time string, got {hhmm!r}")
    return dt_time(int(parts[0]), int(parts[1]))


def _strict_bool_completion(val: Any) -> Optional[bool]:
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (bool, np.bool_)):
        return bool(val)
    if isinstance(val, (int, np.integer, float, np.floating)):
        if val == 1 or val == 1.0:
            return True
        if val == 0 or val == 0.0:
            return False
        return None
    if isinstance(val, str):
        norm = val.strip().lower()
        if norm in ("true", "1", "yes", "closed", "complete"):
            return True
        if norm in ("false", "0", "no", "open", "forming", ""):
            return False
    return None


def _is_tz_aware(dt: Any) -> bool:
    if not isinstance(dt, datetime) or dt.tzinfo is None:
        return False
    try:
        return dt.tzinfo.utcoffset(dt) is not None
    except Exception:
        return False


def compute_candle_close_ist(
    bar_open_ist: datetime,
    timeframe: str,
    market_close_time: dt_time = dt_time(15, 30),
) -> datetime:
    """
    Computes exact closing instant in Asia/Kolkata aligned with P0 & Step 3.6/3.7 rules:
    - Intraday bars: open + tf_minutes capped at 15:30 for the 15:15 1h bar
    - 1d bars: trading session close 15:30 IST on the candle's date
    """
    tf = normalize_timeframe(timeframe)
    if tf == "1d":
        return datetime.combine(bar_open_ist.date(), market_close_time, tzinfo=IST_ZONE)

    minutes = TIMEFRAME_DURATION_MINUTES[tf]
    raw_end = bar_open_ist + timedelta(minutes=minutes)
    session_close_dt = datetime.combine(bar_open_ist.date(), market_close_time, tzinfo=IST_ZONE)
    if (
        bar_open_ist <= session_close_dt
        and raw_end > session_close_dt
        and bar_open_ist.hour == 15
        and bar_open_ist.minute == 15
        and minutes == 60
    ):
        return session_close_dt
    return raw_end


def compute_dataset_fingerprint(
    df: pd.DataFrame,
    *,
    instrument: str,
    timeframe: str,
    timestamps_ist: Sequence[datetime],
) -> str:
    """Computes a reproducible SHA-256 fingerprint over canonical OHLCV bars."""
    rows: List[List[Any]] = []
    has_vol = "volume" in df.columns
    for idx, ts in enumerate(timestamps_ist):
        row = df.iloc[idx]
        rows.append(
            [
                ts.isoformat(),
                round(float(row["open"]), 6),
                round(float(row["high"]), 6),
                round(float(row["low"]), 6),
                round(float(row["close"]), 6),
                round(float(row["volume"]), 6) if has_vol else 0.0,
            ]
        )
    payload = json.dumps(
        {"instrument": instrument, "timeframe": timeframe, "rows": rows},
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32].upper()


def _expected_day_opens(
    trading_day: date,
    timeframe: str,
    market_open_t: dt_time,
    market_close_t: dt_time,
) -> List[datetime]:
    """Generates exact NSE session candle open instants in IST for a single verified trading day."""
    if timeframe == "1d":
        return [datetime.combine(trading_day, dt_time(0, 0), tzinfo=IST_ZONE)]

    step_min = TIMEFRAME_DURATION_MINUTES[timeframe]
    cur = datetime.combine(trading_day, market_open_t, tzinfo=IST_ZONE)
    close_dt = datetime.combine(trading_day, market_close_t, tzinfo=IST_ZONE)
    opens: List[datetime] = []
    while cur < close_dt:
        opens.append(cur)
        cur += timedelta(minutes=step_min)
    return opens


class DataIntegrityAuditor:
    """
    Fail-closed historical candlestick auditor.
    Never modifies, repairs, clips, fills, or interpolates input DataFrames.
    """

    def __init__(
        self,
        *,
        calendar_adapter: Optional[HistoricalMarketCalendarAdapter] = None,
        market_open_hhmm: str = MARKET_OPEN_HHMM,
        market_close_hhmm: str = MARKET_CLOSE_HHMM,
        strict_missing_intervals: bool = True,
        require_volume_column: bool = True,
    ) -> None:
        self.calendar_adapter = calendar_adapter
        self.market_open_t = _parse_hhmm(market_open_hhmm)
        self.market_close_t = _parse_hhmm(market_close_hhmm)
        self.strict_missing_intervals = strict_missing_intervals
        self.require_volume_column = require_volume_column

    def _audit_metadata_flags(
        self,
        df: pd.DataFrame,
        expected_tf: str,
    ) -> Tuple[List[IntegrityIssue], bool, bool]:
        issues: List[IntegrityIssue] = []
        synthetic_detected = False
        repaired_detected = False
        attrs = df.attrs if (hasattr(df, "attrs") and isinstance(df.attrs, dict)) else {}

        attr_tf = attrs.get("timeframe")
        if attr_tf is not None:
            try:
                norm_attr_tf = normalize_timeframe(str(attr_tf))
            except ValueError:
                issues.append(
                    IntegrityIssue(
                        code="INVALID_METADATA_TIMEFRAME",
                        message=f"Dataset declares invalid attrs['timeframe']={attr_tf!r}.",
                    )
                )
            else:
                if norm_attr_tf != expected_tf:
                    issues.append(
                        IntegrityIssue(
                            code="TIMEFRAME_MISMATCH",
                            message=(
                                f"Dataset timeframe mismatch: expected '{expected_tf}', got '{norm_attr_tf}' "
                                "(silent timeframe substitution prohibited)."
                            ),
                        )
                    )

        for key in ("is_mock", "isMock", "is_synthetic", "isSynthetic"):
            if attrs.get(key) is True:
                synthetic_detected = True
                issues.append(
                    IntegrityIssue(
                        code="SYNTHETIC_DATA_DETECTED",
                        message=f"Rejected dataset due to metadata flag {key}=True.",
                    )
                )

        if (
            attrs.get("ohlc_repaired") is True
            or str(attrs.get("quality_status", "")).strip().upper() == "REPAIRED"
            or bool(attrs.get("repair_details"))
        ):
            repaired_detected = True
            issues.append(
                IntegrityIssue(
                    code="REPAIRED_DATA_DETECTED",
                    message="Rejected dataset flagged as repaired/sanitized (`ohlc_repaired=True`).",
                )
            )

        imp_cnt = attrs.get("imputed_bars_count")
        if imp_cnt is not None:
            try:
                if int(imp_cnt) > 0:
                    repaired_detected = True
                    issues.append(
                        IntegrityIssue(
                            code="IMPUTED_BARS_DETECTED",
                            message=f"Rejected dataset containing imputed_bars_count={int(imp_cnt)}.",
                        )
                    )
            except (TypeError, ValueError):
                repaired_detected = True
                issues.append(
                    IntegrityIssue(
                        code="INVALID_IMPUTATION_META",
                        message=f"Rejected invalid imputed_bars_count={imp_cnt!r}.",
                    )
                )

        for key in ("data_status", "feed_status", "dataStatus", "feedStatus"):
            val = attrs.get(key)
            if val is not None:
                norm_status = str(val).strip().upper()
                if norm_status in DISQUALIFYING_STATUSES:
                    if norm_status in {"MOCK", "SYNTHETIC"}:
                        synthetic_detected = True
                    issues.append(
                        IntegrityIssue(
                            code="DISQUALIFIED_FEED_STATUS",
                            message=f"Rejected dataset with disqualifying {key}='{norm_status}'.",
                        )
                    )

        for col, kind in (
            ("is_mock", "SYNTHETIC"),
            ("isMock", "SYNTHETIC"),
            ("is_synthetic", "SYNTHETIC"),
            ("isSynthetic", "SYNTHETIC"),
            ("ohlc_repaired", "REPAIRED"),
            ("is_repaired", "REPAIRED"),
        ):
            if col in df.columns:
                flagged = [
                    i
                    for i, v in enumerate(df[col].tolist())
                    if (isinstance(v, bool) and v) or str(v).strip().lower() in ("true", "1")
                ]
                if flagged:
                    if kind == "SYNTHETIC":
                        synthetic_detected = True
                        code = "SYNTHETIC_ROW_FLAG"
                    else:
                        repaired_detected = True
                        code = "REPAIRED_ROW_FLAG"
                    issues.append(
                        IntegrityIssue(
                            code=code,
                            message=f"Rejected rows with {col}=True at indices {flagged[:5]}.",
                            row_index=flagged[0],
                        )
                    )

        return issues, synthetic_detected, repaired_detected

    def _detect_missing_intervals(
        self,
        *,
        timeframe: str,
        parsed_timestamps: List[datetime],
        expected_from_ist: Optional[datetime],
        expected_to_ist: Optional[datetime],
    ) -> Tuple[List[MissingCandleInterval], List[IntegrityIssue]]:
        missing: List[MissingCandleInterval] = []
        issues: List[IntegrityIssue] = []

        if not parsed_timestamps:
            return missing, issues

        if timeframe == "1d":
            present_dates = {ts.date() for ts in parsed_timestamps}
            range_start_d = expected_from_ist.date() if expected_from_ist else parsed_timestamps[0].date()
            range_end_d = expected_to_ist.date() if expected_to_ist else parsed_timestamps[-1].date()

            if self.calendar_adapter is not None:
                try:
                    trading_days = self.calendar_adapter.iter_trading_days(range_start_d, range_end_d)
                except CalendarUnavailableError as exc:
                    issues.append(IntegrityIssue(code="CALENDAR_UNAVAILABLE", message=str(exc)))
                    return missing, issues

                for td in trading_days:
                    day_close = datetime.combine(td, self.market_close_t, tzinfo=IST_ZONE)
                    if expected_to_ist is not None and day_close > expected_to_ist:
                        continue
                    if td not in present_dates:
                        day_open = datetime.combine(td, dt_time(0, 0), tzinfo=IST_ZONE)
                        missing.append(
                            MissingCandleInterval(
                                timeframe=timeframe,
                                trading_date=td.isoformat(),
                                expected_open_ist=day_open.isoformat(),
                                expected_close_ist=day_close.isoformat(),
                                reason="Missing daily candle on verified trading day.",
                            )
                        )
            return missing, issues

        observed_set = set(parsed_timestamps)
        by_day: Dict[date, List[datetime]] = {}
        for ts in parsed_timestamps:
            by_day.setdefault(ts.date(), []).append(ts)

        first_day = expected_from_ist.date() if expected_from_ist else parsed_timestamps[0].date()
        last_day = expected_to_ist.date() if expected_to_ist else parsed_timestamps[-1].date()

        if self.calendar_adapter is not None and (expected_from_ist is not None or len(by_day) > 1):
            try:
                days_to_check = self.calendar_adapter.iter_trading_days(first_day, last_day)
            except CalendarUnavailableError as exc:
                issues.append(IntegrityIssue(code="CALENDAR_UNAVAILABLE", message=str(exc)))
                return missing, issues
        else:
            days_to_check = sorted(by_day.keys())

        for td in days_to_check:
            day_opens = _expected_day_opens(td, timeframe, self.market_open_t, self.market_close_t)
            if not day_opens:
                continue

            if expected_from_ist is not None or expected_to_ist is not None:
                for op in day_opens:
                    cl = compute_candle_close_ist(op, timeframe, self.market_close_t)
                    if expected_from_ist is not None and op < expected_from_ist:
                        continue
                    if expected_to_ist is not None and cl > expected_to_ist:
                        continue
                    if op not in observed_set:
                        missing.append(
                            MissingCandleInterval(
                                timeframe=timeframe,
                                trading_date=td.isoformat(),
                                expected_open_ist=op.isoformat(),
                                expected_close_ist=cl.isoformat(),
                                reason="Missing expected intraday bar inside requested range.",
                            )
                        )
            else:
                day_bars = by_day.get(td)
                if not day_bars:
                    # Verified intermediate trading day completely missing between present dates
                    if first_day < td < last_day:
                        missing.append(
                            MissingCandleInterval(
                                timeframe=timeframe,
                                trading_date=td.isoformat(),
                                expected_open_ist=day_opens[0].isoformat(),
                                expected_close_ist=compute_candle_close_ist(
                                    day_opens[-1], timeframe, self.market_close_t
                                ).isoformat(),
                                reason="Entire intermediate trading session missing candles.",
                            )
                        )
                    continue

                day_first, day_last = day_bars[0], day_bars[-1]
                for op in day_opens:
                    in_window = (td > first_day or op >= day_first) and (td < last_day or op <= day_last)
                    if in_window and op not in observed_set:
                        cl = compute_candle_close_ist(op, timeframe, self.market_close_t)
                        missing.append(
                            MissingCandleInterval(
                                timeframe=timeframe,
                                trading_date=td.isoformat(),
                                expected_open_ist=op.isoformat(),
                                expected_close_ist=cl.isoformat(),
                                reason="Interior missing intraday candle gap.",
                            )
                        )

        return missing, issues

    def audit_dataframe(
        self,
        df: Any,
        *,
        instrument: str,
        timeframe: str,
        as_of_time: Optional[datetime] = None,
        expected_from_ist: Optional[datetime] = None,
        expected_to_ist: Optional[datetime] = None,
        require_all_completed: bool = True,
        check_missing_intervals: bool = True,
    ) -> DataIntegrityReport:
        """
        Performs complete structural, temporal, session, calendar, and gap validation.
        Fails closed cleanly whenever any invariant fails.
        """
        norm_inst = normalize_instrument(instrument)
        norm_tf = normalize_timeframe(timeframe)

        if df is None or not isinstance(df, pd.DataFrame):
            return DataIntegrityReport(
                is_valid=False,
                status=IntegrityStatus.FAILED,
                instrument=norm_inst,
                timeframe=norm_tf,
                total_bars=0,
                valid_bars=0,
                rejected_reasons=("Dataset must be a non-null pandas DataFrame.",),
                issues=(
                    IntegrityIssue(code="INVALID_INPUT_TYPE", message="Expected pandas.DataFrame."),
                ),
            )

        issues: List[IntegrityIssue] = []
        meta_issues, synthetic_detected, repaired_detected = self._audit_metadata_flags(df, norm_tf)
        issues.extend(meta_issues)

        if df.empty:
            issues.append(IntegrityIssue(code="EMPTY_DATASET", message="Candlestick DataFrame is empty."))
            reasons = tuple(dict.fromkeys(i.message for i in issues))
            return DataIntegrityReport(
                is_valid=False,
                status=IntegrityStatus.FAILED,
                instrument=norm_inst,
                timeframe=norm_tf,
                total_bars=0,
                valid_bars=0,
                rejected_reasons=reasons,
                issues=tuple(issues),
                repaired_detected=repaired_detected,
                synthetic_detected=synthetic_detected,
            )

        required_cols = {"timestamp", "open", "high", "low", "close"}
        if self.require_volume_column:
            required_cols.add("volume")
        missing_cols = sorted(required_cols - set(df.columns))
        if missing_cols:
            issues.append(
                IntegrityIssue(
                    code="MISSING_COLUMNS",
                    message=f"Missing mandatory columns: {missing_cols}.",
                )
            )
            reasons = tuple(dict.fromkeys(i.message for i in issues))
            return DataIntegrityReport(
                is_valid=False,
                status=IntegrityStatus.FAILED,
                instrument=norm_inst,
                timeframe=norm_tf,
                total_bars=len(df),
                valid_bars=0,
                rejected_reasons=reasons,
                issues=tuple(issues),
                repaired_detected=repaired_detected,
                synthetic_detected=synthetic_detected,
            )

        as_of_ist: Optional[datetime] = None
        if as_of_time is not None:
            if not _is_tz_aware(as_of_time):
                issues.append(
                    IntegrityIssue(
                        code="NAIVE_AS_OF_TIME",
                        message="as_of_time must be timezone-aware.",
                    )
                )
            else:
                as_of_ist = as_of_time.astimezone(IST_ZONE)

        exp_from_ist: Optional[datetime] = None
        if expected_from_ist is not None:
            if not _is_tz_aware(expected_from_ist):
                issues.append(
                    IntegrityIssue(
                        code="NAIVE_EXPECTED_RANGE",
                        message="expected_from_ist must be timezone-aware.",
                    )
                )
            else:
                exp_from_ist = expected_from_ist.astimezone(IST_ZONE)

        exp_to_ist: Optional[datetime] = None
        if expected_to_ist is not None:
            if not _is_tz_aware(expected_to_ist):
                issues.append(
                    IntegrityIssue(
                        code="NAIVE_EXPECTED_RANGE",
                        message="expected_to_ist must be timezone-aware.",
                    )
                )
            else:
                exp_to_ist = expected_to_ist.astimezone(IST_ZONE)

        tf_minutes = TIMEFRAME_DURATION_MINUTES[norm_tf]
        open_minutes = self.market_open_t.hour * 60 + self.market_open_t.minute
        close_minutes = self.market_close_t.hour * 60 + self.market_close_t.minute

        has_is_complete = "is_complete" in df.columns
        has_is_closed = "is_closed" in df.columns
        has_volume = "volume" in df.columns

        parsed_ts: List[datetime] = []
        valid_row_flags: List[bool] = []
        seen_ts: Set[datetime] = set()
        duplicate_ts_list: List[str] = []
        tz_offsets: Set[Any] = set()
        incomplete_count = 0
        prev_ts: Optional[datetime] = None
        validated_dates: Dict[date, CalendarStatus] = {}

        for row_idx in range(len(df)):
            row = df.iloc[row_idx]
            row_ok = True

            raw_ts = row["timestamp"]
            bar_dt: Optional[datetime] = None
            try:
                ts_candidate = pd.to_datetime(raw_ts) if type(raw_ts) is str else raw_ts
                if isinstance(ts_candidate, pd.Timestamp):
                    if pd.isna(ts_candidate):
                        ts_candidate = None
                    else:
                        ts_candidate = ts_candidate.to_pydatetime()
                if not _is_tz_aware(ts_candidate):
                    row_ok = False
                    issues.append(
                        IntegrityIssue(
                            code="NAIVE_OR_INVALID_TIMESTAMP",
                            message=f"Row {row_idx}: timestamp {raw_ts!r} must be timezone-aware (IST/tz-aware).",
                            row_index=row_idx,
                        )
                    )
                else:
                    tz_offsets.add(ts_candidate.utcoffset())
                    bar_dt = ts_candidate.astimezone(IST_ZONE)
            except Exception as exc:
                row_ok = False
                issues.append(
                    IntegrityIssue(
                        code="INVALID_TIMESTAMP",
                        message=f"Row {row_idx}: failed parsing timestamp {raw_ts!r}: {exc}",
                        row_index=row_idx,
                    )
                )

            if bar_dt is not None:
                parsed_ts.append(bar_dt)
                ts_iso = bar_dt.isoformat()

                if bar_dt in seen_ts:
                    row_ok = False
                    duplicate_ts_list.append(ts_iso)
                    issues.append(
                        IntegrityIssue(
                            code="DUPLICATE_TIMESTAMP",
                            message=f"Duplicate candle timestamp {ts_iso}.",
                            row_index=row_idx,
                            timestamp_ist=ts_iso,
                        )
                    )
                seen_ts.add(bar_dt)

                if prev_ts is not None and bar_dt < prev_ts:
                    row_ok = False
                    issues.append(
                        IntegrityIssue(
                            code="OUT_OF_ORDER_TIMESTAMP",
                            message=f"Non-ascending timestamp at row {row_idx}: {ts_iso} < {prev_ts.isoformat()}.",
                            row_index=row_idx,
                            timestamp_ist=ts_iso,
                        )
                    )
                if prev_ts is None or bar_dt > prev_ts:
                    prev_ts = bar_dt

                # Session boundary & grid check
                bar_t = bar_dt.time()
                if norm_tf == "1d":
                    valid_daily_t = (bar_t == dt_time(0, 0)) or (
                        self.market_open_t <= bar_t <= self.market_close_t
                    )
                    if not valid_daily_t:
                        row_ok = False
                        issues.append(
                            IntegrityIssue(
                                code="OUT_OF_SESSION_BOUNDARY",
                                message=f"Daily candle timestamp outside IST session/midnight at {ts_iso}.",
                                row_index=row_idx,
                                timestamp_ist=ts_iso,
                            )
                        )
                else:
                    bar_mins = bar_t.hour * 60 + bar_t.minute
                    if (
                        bar_t.second != 0
                        or bar_t.microsecond != 0
                        or bar_mins < open_minutes
                        or bar_mins >= close_minutes
                    ):
                        row_ok = False
                        issues.append(
                            IntegrityIssue(
                                code="OUT_OF_SESSION_BOUNDARY",
                                message=f"Intraday candle {ts_iso} falls outside IST [09:15, 15:30).",
                                row_index=row_idx,
                                timestamp_ist=ts_iso,
                            )
                        )
                    elif (bar_mins - open_minutes) % tf_minutes != 0:
                        row_ok = False
                        issues.append(
                            IntegrityIssue(
                                code="SESSION_GRID_MISALIGNMENT",
                                message=(
                                    f"Intraday candle {ts_iso} does not align with '{norm_tf}' NSE session grid from 09:15 IST."
                                ),
                                row_index=row_idx,
                                timestamp_ist=ts_iso,
                            )
                        )

                # Trading calendar check
                if self.calendar_adapter is not None:
                    d_key = bar_dt.date()
                    if d_key not in validated_dates:
                        cal_res = self.calendar_adapter.validate_date(d_key)
                        validated_dates[d_key] = cal_res.status
                        if cal_res.status != CalendarStatus.TRADING_DAY:
                            row_ok = False
                            issues.append(
                                IntegrityIssue(
                                    code=cal_res.status.value,
                                    message=f"Calendar rejected date {d_key.isoformat()}: {cal_res.reason}",
                                    row_index=row_idx,
                                    timestamp_ist=ts_iso,
                                )
                            )
                    elif validated_dates[d_key] != CalendarStatus.TRADING_DAY:
                        row_ok = False

                # Completion check
                if require_all_completed:
                    row_incomplete = False
                    if has_is_complete and _strict_bool_completion(row["is_complete"]) is not True:
                        row_incomplete = True
                    if has_is_closed and _strict_bool_completion(row["is_closed"]) is not True:
                        row_incomplete = True
                    close_ist = compute_candle_close_ist(bar_dt, norm_tf, self.market_close_t)
                    if as_of_ist is not None and close_ist > as_of_ist:
                        row_incomplete = True

                    if row_incomplete:
                        row_ok = False
                        incomplete_count += 1
                        issues.append(
                            IntegrityIssue(
                                code="INCOMPLETE_CANDLE",
                                message=f"Candle at {ts_iso} is incomplete or unclosed relative to {as_of_ist or 'flag'}.",
                                row_index=row_idx,
                                timestamp_ist=ts_iso,
                            )
                        )

            # OHLC numeric & geometry invariants
            ohlc_vals: Dict[str, float] = {}
            for col in ("open", "high", "low", "close"):
                try:
                    val = float(row[col])
                except (TypeError, ValueError):
                    val = float("nan")
                if not math.isfinite(val) or val <= 0.0:
                    row_ok = False
                    issues.append(
                        IntegrityIssue(
                            code="INVALID_PRICE_VALUE",
                            message=f"Row {row_idx}: invalid {col}={row[col]!r} (must be finite and > 0).",
                            row_index=row_idx,
                            timestamp_ist=bar_dt.isoformat() if bar_dt else None,
                        )
                    )
                else:
                    ohlc_vals[col] = val

            if len(ohlc_vals) == 4:
                o, h, l, c = ohlc_vals["open"], ohlc_vals["high"], ohlc_vals["low"], ohlc_vals["close"]
                if h < max(o, c) or l > min(o, c) or h < l:
                    row_ok = False
                    issues.append(
                        IntegrityIssue(
                            code="OHLC_GEOMETRY_VIOLATION",
                            message=(
                                f"Row {row_idx}: invalid OHLC geometry O={o}, H={h}, L={l}, C={c}."
                            ),
                            row_index=row_idx,
                            timestamp_ist=bar_dt.isoformat() if bar_dt else None,
                        )
                    )

            if has_volume:
                try:
                    vol = float(row["volume"])
                except (TypeError, ValueError):
                    vol = float("nan")
                if not math.isfinite(vol) or vol < 0.0:
                    row_ok = False
                    issues.append(
                        IntegrityIssue(
                            code="INVALID_VOLUME",
                            message=f"Row {row_idx}: invalid volume={row['volume']!r} (must be finite and >= 0).",
                            row_index=row_idx,
                            timestamp_ist=bar_dt.isoformat() if bar_dt else None,
                        )
                    )

            valid_row_flags.append(row_ok)

        if len(tz_offsets) > 1:
            issues.append(
                IntegrityIssue(
                    code="MIXED_TIMEZONE_OFFSETS",
                    message="Dataset contains mixed timezone offsets; timestamps must have uniform timezone offset.",
                )
            )

        missing_intervals: List[MissingCandleInterval] = []
        if (
            check_missing_intervals
            and len(parsed_ts) == len(df)
            and not duplicate_ts_list
            and all(parsed_ts[i] > parsed_ts[i - 1] for i in range(1, len(parsed_ts)))
        ):
            missing_intervals, gap_issues = self._detect_missing_intervals(
                timeframe=norm_tf,
                parsed_timestamps=parsed_ts,
                expected_from_ist=exp_from_ist,
                expected_to_ist=exp_to_ist,
            )
            issues.extend(gap_issues)
            if missing_intervals:
                severity = (
                    IntegrityIssueSeverity.ERROR
                    if self.strict_missing_intervals
                    else IntegrityIssueSeverity.WARNING
                )
                issues.append(
                    IntegrityIssue(
                        code="MISSING_INTERVALS_DETECTED",
                        severity=severity,
                        message=(
                            f"Detected {len(missing_intervals)} missing '{norm_tf}' interval(s); "
                            "first gap at "
                            f"{missing_intervals[0].expected_open_ist} ({missing_intervals[0].reason})."
                        ),
                    )
                )

        has_error = any(i.severity == IntegrityIssueSeverity.ERROR for i in issues)
        is_valid = not has_error
        valid_bars = sum(1 for flag in valid_row_flags if flag)
        fingerprint = ""
        if is_valid and len(parsed_ts) == len(df):
            fingerprint = compute_dataset_fingerprint(
                df,
                instrument=norm_inst,
                timeframe=norm_tf,
                timestamps_ist=parsed_ts,
            )

        reasons = tuple(dict.fromkeys(i.message for i in issues if i.severity == IntegrityIssueSeverity.ERROR))
        return DataIntegrityReport(
            is_valid=is_valid,
            status=IntegrityStatus.PASSED if is_valid else IntegrityStatus.FAILED,
            instrument=norm_inst,
            timeframe=norm_tf,
            total_bars=len(df),
            valid_bars=valid_bars,
            rejected_reasons=reasons,
            issues=tuple(issues),
            duplicate_timestamps=tuple(sorted(set(duplicate_ts_list))),
            missing_intervals=tuple(missing_intervals),
            repaired_detected=repaired_detected,
            synthetic_detected=synthetic_detected,
            incomplete_candles_detected=incomplete_count,
            first_timestamp_ist=parsed_ts[0].isoformat() if parsed_ts else None,
            last_timestamp_ist=parsed_ts[-1].isoformat() if parsed_ts else None,
            dataset_fingerprint=fingerprint,
        )
