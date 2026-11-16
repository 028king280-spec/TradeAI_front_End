"""
AIVOLVE Phase 4 Step 4.2 — Deterministic Point-in-Time Replay Runner.

Executes chronological historical replay across Phase 3 multi-timeframe ICT/SMC
engines (`MTFConfluenceEngine` + injected `HistoricalMarketCalendarAdapter`)
strictly under `PAPER_TRADING_ONLY` governance.

Guarantees:
- Never modifies or bypasses frozen Phase 1, Phase 2, or Phase 3 engines.
- Never silently substitutes missing timeframes (`3m` stays `3m`).
- Physically excludes future (`open > as_of_time` / `close > as_of_time`) and
  forming (`is_complete != True`) bars BEFORE passing slices to Phase 3.
- Enforces `DataIntegrityAuditor` fail-closed validation on sliced windows.
- Supplies `VERIFIED_EOD` feed status for valid historical bars.
- Preserves ICT score strictly as `None` (`score_status="UNAVAILABLE"`,
  `calibration_status="NOT_CALIBRATED"`).
- Writes run manifests ONLY to isolated `HistoricalDataStore` (never prod DBs/JSONs).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, time as dt_time, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd

from app.backtesting.calendar_adapter import (
    CalendarUnavailableError,
    HistoricalMarketCalendarAdapter,
)
from app.backtesting.configuration import (
    BacktestConfiguration,
    IST_ZONE,
    REPLAY_MTF_TIMEFRAMES,
    normalize_instrument,
    normalize_timeframe,
    verify_index_governance,
)
from app.backtesting.data_integrity import (
    DataIntegrityAuditor,
    DISQUALIFYING_STATUSES,
    _is_tz_aware,
    _strict_bool_completion,
    compute_candle_close_ist,
    compute_dataset_fingerprint,
)
from app.backtesting.data_store import HistoricalDataStore
from app.backtesting.models import (
    CalendarStatus,
    IntegrityStatus,
    ReplayPointResult,
    ReplayRunRecord,
    ReplayValidationStatus,
)
from app.options.ict_smc.mtf_confluence_engine import (
    ENGINE_VERSION as MTF_ENGINE_VERSION,
    AlignmentClassification,
    MTFConfluenceConfiguration,
    MTFConfluenceEngine,
    MTFConfluenceReport,
)


def _parse_close_hhmm(hhmm: str) -> dt_time:
    hh, mm = hhmm.strip().split(":")
    return dt_time(int(hh), int(mm))


def _require_chronological_replay_times(replay_times: Sequence[datetime]) -> List[datetime]:
    if not isinstance(replay_times, (list, tuple)) or len(replay_times) == 0:
        raise ValueError("replay_times must be a non-empty list or tuple of timezone-aware datetimes.")

    converted: List[datetime] = []
    for idx, ts in enumerate(replay_times):
        if not _is_tz_aware(ts):
            raise ValueError(f"replay_times[{idx}] must be timezone-aware, got {ts!r}")
        ts_ist = ts.astimezone(IST_ZONE)
        if converted and ts_ist < converted[-1]:
            raise ValueError(
                f"replay_times must be chronological (non-decreasing): "
                f"{ts_ist.isoformat()} < {converted[-1].isoformat()}"
            )
        converted.append(ts_ist)
    return converted


def slice_completed_candles_as_of(
    df: Any,
    *,
    timeframe: str,
    as_of_time: datetime,
    market_close_hhmm: str = "15:30",
) -> Tuple[Optional[pd.DataFrame], int, int, Optional[str]]:
    """
    Strictly isolates completed bars closed at or before `as_of_time` (IST) without
    mutating or peeking into future bar OHLCV fields.

    Returns `(sliced_df, future_bars_excluded, incomplete_bars_excluded, preflight_error)`.
    """
    norm_tf = normalize_timeframe(timeframe)
    if df is None:
        return None, 0, 0, None
    if not isinstance(df, pd.DataFrame):
        return None, 0, 0, f"[{norm_tf}] candles_df must be a pandas.DataFrame"

    attrs = df.attrs if hasattr(df, "attrs") and isinstance(df.attrs, dict) else {}
    for flag_key in ("is_mock", "isMock", "is_synthetic", "isSynthetic"):
        if attrs.get(flag_key) is True:
            return None, 0, 0, f"[{norm_tf}] Disqualified synthetic/mock dataset ({flag_key}=True)"

    if attrs.get("ohlc_repaired") is True or str(attrs.get("quality_status", "")).upper() == "REPAIRED":
        return None, 0, 0, f"[{norm_tf}] Repaired OHLC dataset rejected (ohlc_repaired=True)"

    for status_key in ("data_status", "feed_status", "dataStatus", "feedStatus"):
        raw_stat = attrs.get(status_key)
        if raw_stat is not None and str(raw_stat).strip().upper() in DISQUALIFYING_STATUSES:
            stat_upper = str(raw_stat).strip().upper()
            if df.empty and stat_upper in {"DATA_UNAVAILABLE", "NO_COMPLETED_BARS"}:
                empty_df = df.copy()
                empty_df.attrs = {**dict(attrs), "timeframe": norm_tf, "dataStatus": "NO_COMPLETED_BARS", "data_status": "NO_COMPLETED_BARS"}
                return empty_df, 0, 0, None
            return None, 0, 0, f"[{norm_tf}] Disqualifying feed status '{stat_upper}'"

    attr_tf = attrs.get("timeframe")
    if attr_tf is not None and normalize_timeframe(str(attr_tf)) != norm_tf:
        return None, 0, 0, f"[{norm_tf}] Timeframe mismatch: attrs['timeframe']={attr_tf!r}"

    if df.empty:
        empty_df = df.copy()
        empty_df.attrs = {**dict(attrs), "timeframe": norm_tf, "dataStatus": "NO_COMPLETED_BARS", "data_status": "NO_COMPLETED_BARS"}
        return empty_df, 0, 0, None

    if "timestamp" not in df.columns:
        return None, 0, 0, f"[{norm_tf}] Missing mandatory 'timestamp' column"

    as_of_ist = as_of_time.astimezone(IST_ZONE)
    close_time = _parse_close_hhmm(market_close_hhmm)
    has_is_complete = "is_complete" in df.columns
    has_is_closed = "is_closed" in df.columns

    keep_indices: List[Any] = []
    future_excluded = 0
    incomplete_excluded = 0

    for idx, row in df.iterrows():
        raw_ts = row["timestamp"]
        try:
            ts_obj = pd.to_datetime(raw_ts) if type(raw_ts) is str else raw_ts
            py_dt = ts_obj.to_pydatetime() if isinstance(ts_obj, pd.Timestamp) else ts_obj
        except Exception as exc:
            return None, 0, 0, f"[{norm_tf}] Unparseable timestamp {raw_ts!r}: {exc}"

        if not _is_tz_aware(py_dt):
            return None, 0, 0, f"[{norm_tf}] Timezone-naive timestamp rejected: {raw_ts!r}"

        open_ist = py_dt.astimezone(IST_ZONE)
        if open_ist > as_of_ist:
            future_excluded += 1
            continue

        bar_close_ist = compute_candle_close_ist(open_ist, norm_tf, close_time)
        if bar_close_ist > as_of_ist:
            incomplete_excluded += 1
            continue

        if has_is_complete and _strict_bool_completion(row["is_complete"]) is not True:
            incomplete_excluded += 1
            continue
        if has_is_closed and _strict_bool_completion(row["is_closed"]) is not True:
            incomplete_excluded += 1
            continue

        keep_indices.append(idx)

    sliced = df.loc[keep_indices].copy().reset_index(drop=True)
    eff_status = "VERIFIED_EOD" if len(sliced) > 0 else "NO_COMPLETED_BARS"
    sliced.attrs = {
        **dict(attrs),
        "timeframe": norm_tf,
        "dataStatus": eff_status,
        "feedStatus": eff_status,
        "data_status": eff_status,
        "feed_status": eff_status,
        "is_mock": False,
        "is_synthetic": False,
        "ohlc_repaired": False,
    }
    return sliced, future_excluded, incomplete_excluded, None


class DeterministicReplayRunner:
    """
    Chronological point-in-time historical replay harness consuming frozen Phase 3
    engines and persisting results strictly inside `HistoricalDataStore`.
    """

    def __init__(
        self,
        *,
        data_store: Optional[HistoricalDataStore] = None,
        calendar_adapter: Optional[HistoricalMarketCalendarAdapter] = None,
        config: Optional[BacktestConfiguration] = None,
        mtf_config: Optional[MTFConfluenceConfiguration] = None,
    ) -> None:
        self.config = config or BacktestConfiguration()
        self.calendar_adapter = calendar_adapter or HistoricalMarketCalendarAdapter()
        self.data_store = data_store or HistoricalDataStore(config=self.config)
        self.mtf_config = mtf_config or MTFConfluenceConfiguration(
            sensex_governance_approved=self.config.sensex_governance_approved,
            market_close_hhmm=self.config.market_close_hhmm,
        )
        self.auditor = DataIntegrityAuditor(
            calendar_adapter=self.calendar_adapter,
            market_open_hhmm=self.config.market_open_hhmm,
            market_close_hhmm=self.config.market_close_hhmm,
            strict_missing_intervals=self.config.strict_missing_intervals,
            require_volume_column=self.config.require_volume_column,
        )

    @staticmethod
    def _normalize_replay_timeframes(timeframes: Optional[Sequence[str]]) -> Tuple[str, ...]:
        requested = tuple(timeframes) if timeframes is not None else REPLAY_MTF_TIMEFRAMES
        normalized: List[str] = []
        for tf in requested:
            norm_tf = normalize_timeframe(tf)
            if norm_tf not in REPLAY_MTF_TIMEFRAMES:
                raise ValueError(
                    f"Timeframe '{norm_tf}' is not part of Phase 3 Step 3.7 replay hierarchy {REPLAY_MTF_TIMEFRAMES}."
                )
            if norm_tf not in normalized:
                normalized.append(norm_tf)
        # Preserve canonical HTF -> LTF order deterministically
        return tuple(tf for tf in REPLAY_MTF_TIMEFRAMES if tf in normalized)

    def _compute_combined_dataset_fingerprint(
        self,
        *,
        instrument: str,
        candles_by_tf: Dict[str, pd.DataFrame],
        timeframes: Tuple[str, ...],
    ) -> str:
        per_tf: Dict[str, Any] = {}
        for tf in timeframes:
            df = candles_by_tf.get(tf)
            if df is None or df.empty:
                per_tf[tf] = {"bars": 0, "fingerprint": "EMPTY"}
                continue
            try:
                ts_list = [
                    (
                        pd.to_datetime(t).to_pydatetime()
                        if isinstance(pd.to_datetime(t), pd.Timestamp)
                        else pd.to_datetime(t)
                    ).astimezone(IST_ZONE)
                    for t in df["timestamp"].tolist()
                ]
                per_tf[tf] = {
                    "bars": len(df),
                    "fingerprint": compute_dataset_fingerprint(
                        df,
                        instrument=instrument,
                        timeframe=tf,
                        timestamps_ist=ts_list,
                    ),
                }
            except Exception as exc:
                per_tf[tf] = {"bars": len(df), "fingerprint": f"UNPARSEABLE:{exc}"}
        payload = json.dumps(
            {"instrument": instrument, "timeframes": per_tf},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32].upper()

    def run_replay(
        self,
        *,
        instrument: str,
        replay_times: Sequence[datetime],
        candles_by_timeframe: Optional[Dict[str, pd.DataFrame]] = None,
        timeframes: Optional[Sequence[str]] = None,
        data_source: str = "isolated_backtest_store",
        include_session_context: bool = True,
        persist: bool = True,
    ) -> ReplayRunRecord:
        """
        Replays chronological point-in-time Phase 3 MTF ICT/SMC intelligence strictly
        using completed bars available at each `as_of_time`, with VERIFIED_EOD status.
        """
        norm_inst = normalize_instrument(instrument)
        norm_tfs = self._normalize_replay_timeframes(timeframes)
        schedule = _require_chronological_replay_times(replay_times)

        # Normalize supplied candles_by_timeframe without silent substitution
        loaded_candles: Dict[str, pd.DataFrame]
        if candles_by_timeframe is not None:
            loaded_candles = {}
            for raw_tf, df_val in candles_by_timeframe.items():
                ntf = normalize_timeframe(raw_tf)
                if ntf in norm_tfs:
                    loaded_candles[ntf] = df_val
        else:
            start_bound = schedule[0].replace(hour=0, minute=0, second=0, microsecond=0)
            loaded_candles = self.data_store.load_candles_for_replay(
                norm_inst,
                norm_tfs,
                end_time_ist=schedule[-1],
            )
            _ = start_bound

        dataset_fp = self._compute_combined_dataset_fingerprint(
            instrument=norm_inst,
            candles_by_tf=loaded_candles,
            timeframes=norm_tfs,
        )
        cal_fp = self.calendar_adapter.calendar_fingerprint()

        # Check governance upfront (fail-closed on SENSEX unless governance permits it)
        gov_ok, gov_status, gov_info = verify_index_governance(
            norm_inst,
            sensex_governance_approved=self.config.sensex_governance_approved,
            governance_db_path=self.config.governance_ledger_path,
            evaluation_date=schedule[-1].date(),
        )
        if not gov_ok:
            return self._finalize_and_persist(
                instrument=norm_inst,
                timeframes=norm_tfs,
                schedule=schedule,
                data_source=data_source,
                dataset_fingerprint=dataset_fp,
                calendar_fingerprint=cal_fp,
                points=(),
                validation_status=ReplayValidationStatus.LOCKED_OUT,
                failure_reasons=(f"{gov_status}: {gov_info.get('reason')}",),
                persist=persist,
            )

        # Validate historical calendar coverage for all replay dates before running
        calendar_errors: List[str] = []
        checked_dates: Set[Any] = set()
        for ts in schedule:
            d = ts.date()
            if d in checked_dates:
                continue
            checked_dates.add(d)
            try:
                cal_res = self.calendar_adapter.validate_date(d)
                if cal_res.status == CalendarStatus.CALENDAR_UNAVAILABLE:
                    calendar_errors.append(cal_res.reason)
                elif cal_res.status == CalendarStatus.NON_TRADING_DAY:
                    calendar_errors.append(cal_res.reason)
            except CalendarUnavailableError as exc:
                calendar_errors.append(str(exc))

        if calendar_errors:
            return self._finalize_and_persist(
                instrument=norm_inst,
                timeframes=norm_tfs,
                schedule=schedule,
                data_source=data_source,
                dataset_fingerprint=dataset_fp,
                calendar_fingerprint=cal_fp,
                points=(),
                validation_status=ReplayValidationStatus.LOCKED_OUT,
                failure_reasons=tuple(dict.fromkeys(calendar_errors)),
                persist=persist,
            )

        # Fresh frozen MTFConfluenceEngine instance per deterministic run with injected verified calendar
        eff_mtf_cfg = self.mtf_config.model_copy(
            update={"sensex_governance_approved": True if (norm_inst == "SENSEX" and gov_ok) else self.mtf_config.sensex_governance_approved}
        )
        mtf_engine = MTFConfluenceEngine(
            config=eff_mtf_cfg,
            calendar=self.calendar_adapter,
        )

        points: List[ReplayPointResult] = []
        run_failures: List[str] = []

        for as_of_ist in schedule:
            sliced_by_tf: Dict[str, pd.DataFrame] = {}
            bars_used: Dict[str, int] = {}
            future_excl: Dict[str, int] = {}
            incomplete_excl: Dict[str, int] = {}
            step_integrity_errors: List[str] = []

            for tf in norm_tfs:
                raw_tf_df = loaded_candles.get(tf)
                if raw_tf_df is None:
                    bars_used[tf] = 0
                    future_excl[tf] = 0
                    incomplete_excl[tf] = 0
                    continue

                sliced_df, fut_c, inc_c, pre_err = slice_completed_candles_as_of(
                    raw_tf_df,
                    timeframe=tf,
                    as_of_time=as_of_ist,
                    market_close_hhmm=self.config.market_close_hhmm,
                )
                future_excl[tf] = fut_c
                incomplete_excl[tf] = inc_c

                if pre_err is not None:
                    step_integrity_errors.append(pre_err)
                    bars_used[tf] = 0
                    bad_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
                    bad_df.attrs = {"timeframe": tf, "dataStatus": "INVALID_DATA", "data_status": "INVALID_DATA"}
                    sliced_by_tf[tf] = bad_df
                    continue

                if sliced_df is None or sliced_df.empty:
                    bars_used[tf] = 0
                    # Omit completely empty timeframe only when NO bars closed yet; if explicit empty frame present pass clean NO_COMPLETED_BARS
                    if sliced_df is not None:
                        sliced_by_tf[tf] = sliced_df
                    continue

                # Full DataIntegrityAuditor check strictly over completed slice `<= as_of_ist`
                audit_rep = self.auditor.audit_dataframe(
                    sliced_df,
                    instrument=norm_inst,
                    timeframe=tf,
                    as_of_time=as_of_ist,
                    require_all_completed=True,
                    check_missing_intervals=True,
                )
                if not audit_rep.is_valid or audit_rep.status != IntegrityStatus.PASSED:
                    step_integrity_errors.extend(audit_rep.rejected_reasons)
                    bars_used[tf] = 0
                    bad_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
                    bad_df.attrs = {"timeframe": tf, "dataStatus": "INVALID_DATA", "data_status": "INVALID_DATA"}
                    sliced_by_tf[tf] = bad_df
                    continue

                window_limit = self.config.phase3_lookback_bars
                if len(sliced_df) > window_limit:
                    eval_df = sliced_df.tail(window_limit).reset_index(drop=True)
                    eval_df.attrs = dict(sliced_df.attrs)
                else:
                    eval_df = sliced_df

                bars_used[tf] = len(eval_df)
                sliced_by_tf[tf] = eval_df

            if step_integrity_errors:
                run_failures.extend(step_integrity_errors)
                # Still call Phase 3 with INVALID_DATA status so fail-closed alignment matches governance
                mtf_report = mtf_engine.evaluate_from_candles(
                    index=norm_inst,
                    as_of_time=as_of_ist,
                    candles_by_timeframe=sliced_by_tf,
                    data_quality_status="INVALID_DATA",
                    include_session_context=include_session_context,
                )
            else:
                mtf_report = mtf_engine.evaluate_from_candles(
                    index=norm_inst,
                    as_of_time=as_of_ist,
                    candles_by_timeframe=sliced_by_tf,
                    data_quality_status="VERIFIED_EOD",
                    include_session_context=include_session_context,
                )

            if mtf_report.confluence_score is not None or mtf_report.score_status != "UNAVAILABLE" or mtf_report.calibration_status != "NOT_CALIBRATED":
                raise RuntimeError(
                    "GOVERNANCE VIOLATION: Frozen Phase 3 engine emitted calibrated/numeric ICT score."
                )

            report_dict = mtf_report.model_dump(mode="json")
            points.append(
                ReplayPointResult(
                    as_of_time_ist=as_of_ist.isoformat(),
                    report_id=mtf_report.report_id,
                    overall_alignment=mtf_report.overall_alignment.value,
                    data_quality_status=mtf_report.data_quality_status,
                    score_status=mtf_report.score_status,
                    calibration_status=mtf_report.calibration_status,
                    confluence_score=mtf_report.confluence_score,
                    bars_used_by_timeframe=bars_used,
                    future_bars_excluded=future_excl,
                    incomplete_bars_excluded=incomplete_excl,
                    conflicts_count=len(mtf_report.conflicts),
                    evidence_event_ids=tuple(mtf_report.evidence_event_ids),
                    report=report_dict,
                )
            )

        any_lockout = any(
            p.overall_alignment == AlignmentClassification.DATA_QUALITY_LOCKOUT.value
            for p in points
        )
        if run_failures:
            val_status = ReplayValidationStatus.FAILED
        elif any_lockout:
            val_status = ReplayValidationStatus.LOCKED_OUT
        else:
            val_status = ReplayValidationStatus.VALIDATED

        return self._finalize_and_persist(
            instrument=norm_inst,
            timeframes=norm_tfs,
            schedule=schedule,
            data_source=data_source,
            dataset_fingerprint=dataset_fp,
            calendar_fingerprint=cal_fp,
            points=tuple(points),
            validation_status=val_status,
            failure_reasons=tuple(dict.fromkeys(run_failures)),
            persist=persist,
        )

    def _finalize_and_persist(
        self,
        *,
        instrument: str,
        timeframes: Tuple[str, ...],
        schedule: List[datetime],
        data_source: str,
        dataset_fingerprint: str,
        calendar_fingerprint: str,
        points: Tuple[ReplayPointResult, ...],
        validation_status: ReplayValidationStatus,
        failure_reasons: Tuple[str, ...],
        persist: bool,
    ) -> ReplayRunRecord:
        replay_ts_iso = tuple(dt.isoformat() for dt in schedule)
        start_iso = schedule[0].isoformat()
        end_iso = schedule[-1].isoformat()
        date_range = f"{schedule[0].date().isoformat()}..{schedule[-1].date().isoformat()}"

        out_payload = {
            "instrument": instrument,
            "timeframes": list(timeframes),
            "dataset_fingerprint": dataset_fingerprint,
            "calendar_fingerprint": calendar_fingerprint,
            "engine_version": MTF_ENGINE_VERSION,
            "configuration_version": self.config.configuration_version,
            "validation_status": validation_status.value,
            "failure_reasons": list(failure_reasons),
            "points": [p.model_dump(mode="json") for p in points],
        }
        output_fp = hashlib.sha256(
            json.dumps(out_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()[:32].upper()

        run_id_seed = "|".join(
            [
                instrument,
                ",".join(timeframes),
                start_iso,
                end_iso,
                dataset_fingerprint,
                calendar_fingerprint,
                output_fp,
            ]
        )
        run_id = "RPL-" + hashlib.sha256(run_id_seed.encode("utf-8")).hexdigest()[:16].upper()

        record = ReplayRunRecord(
            run_id=run_id,
            instrument=instrument,
            timeframes=timeframes,
            start_date_ist=start_iso,
            end_date_ist=end_iso,
            historical_date_range=date_range,
            data_source=data_source,
            dataset_fingerprint=dataset_fingerprint,
            engine_version=MTF_ENGINE_VERSION,
            configuration_version=self.config.configuration_version,
            calendar_source=self.calendar_adapter.source_label,
            calendar_fingerprint=calendar_fingerprint,
            replay_timestamps_ist=replay_ts_iso,
            output_fingerprint=output_fp,
            validation_status=validation_status,
            failure_reasons=failure_reasons,
            point_count=len(points),
            points=points,
            created_at_utc=datetime.now(timezone.utc),
        )
        if persist:
            self.data_store.save_replay_run(record)
        return record

