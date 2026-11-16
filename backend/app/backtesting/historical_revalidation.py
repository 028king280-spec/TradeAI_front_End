"""
AIVOLVE Phase 4, Step 4.7 — Historical Revalidation Quality Gate & Causal Evaluator
Strictly PAPER_TRADING_ONLY. Reuses frozen Phase 2 & Phase 3 engines and Step 4.2/4.6
without modifying historical scoring, fabricating bars, or leaking future candles.
"""

from __future__ import annotations

from datetime import datetime, time as dt_time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from app.backtesting.configuration import (
    BacktestConfiguration,
    IST_ZONE,
    PACKAGE_VERSION,
    normalize_instrument,
    normalize_timeframe,
    verify_index_governance,
)
from app.backtesting.data_integrity import compute_candle_close_ist
from app.backtesting.data_store import HistoricalDataStore
from app.backtesting.dataset_validation import (
    DatasetQualityStatus,
    DatasetValidationReport,
    DatasetValidator,
)
from app.backtesting.models import ReplayRunRecord, ReplayValidationStatus
from app.backtesting.multi_year_calendar import MultiYearTradingCalendar
from app.backtesting.replay_runner import (
    DeterministicReplayRunner,
    slice_completed_candles_as_of,
)
from app.backtesting.revalidation_models import (
    DatasetEligibilityDecision,
    DatasetTimeframeEligibility,
    EligibilityClassification,
    RevalidationConfig,
    RevalidationSignalDirection,
    RevalidationSignalRecord,
    deterministic_reval_hash,
    parse_ist_datetime,
)
from app.options.candle_processor import process_candlestick_series
from app.options.market_state_engine import MarketRegime, evaluate_index_market_state
from app.options.multi_timeframe_engine import evaluate_multi_timeframe_confluence
from app.options.trade_setup_selector import DEFAULT_SETUP_CONFIG, select_trade_setup


PHASE2_ENGINE_VERSIONS: Dict[str, str] = {
    "phase2_market_state": "v3.0-frozen",
    "phase2_mtf_confluence": "v3.0-frozen",
    "phase2_trade_setup": "v3.0-frozen",
    "phase3_ict_smc_mtf": "v3.0-frozen-uncalibrated",
    "backtest_engine": PACKAGE_VERSION,
}


def classify_ist_session_bucket(ts_ist: datetime) -> str:
    """Deterministically classifies an IST timestamp into canonical NSE intraday session buckets."""
    t = ts_ist.astimezone(IST_ZONE).time()
    if t < dt_time(10, 0):
        return "OPENING_0915_1000"
    if t < dt_time(11, 30):
        return "MORNING_1000_1130"
    if t < dt_time(13, 30):
        return "MIDDAY_1130_1330"
    if t < dt_time(15, 0):
        return "AFTERNOON_1330_1500"
    return "CLOSING_1500_1530"


def _extract_session_completeness(
    df: Optional[pd.DataFrame],
    validation_report: DatasetValidationReport,
    calendar: MultiYearTradingCalendar,
    timeframe: str,
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """
    Separates fully complete trading sessions from incomplete sessions using
    Step 4.6 validation gaps and MultiYearTradingCalendar expected bar schedules.
    """
    if df is None or df.empty or "timestamp" not in df.columns:
        return (), ()

    ts_series = pd.to_datetime(df["timestamp"])
    dates_present = sorted({ts.tz_convert(IST_ZONE).date() if ts.tzinfo else ts.date() for ts in ts_series})
    gap_dates = {g.trading_date for g in validation_report.unexpected_gaps}

    complete: List[str] = []
    incomplete: List[str] = []
    norm_tf = normalize_timeframe(timeframe)

    for d in dates_present:
        d_str = d.isoformat()
        if d_str in gap_dates:
            incomplete.append(d_str)
            continue
        day_start = datetime(d.year, d.month, d.day, 0, 0, tzinfo=IST_ZONE)
        day_end = datetime(d.year, d.month, d.day, 23, 59, tzinfo=IST_ZONE)
        cal_res = calendar.validate_date(d)
        if not cal_res.is_trading_day:
            incomplete.append(d_str)
            continue
        expected_map = calendar.expected_opens_by_date(norm_tf, day_start, day_end)
        expected_bars = expected_map.get(d, [])
        if not expected_bars:
            incomplete.append(d_str)
            continue
        day_mask = [
            (ts.tz_convert(IST_ZONE).date() if ts.tzinfo else ts.date()) == d for ts in ts_series
        ]
        day_count = int(sum(1 for flag in day_mask if flag))
        if norm_tf == "1d":
            if day_count >= 1:
                complete.append(d_str)
            else:
                incomplete.append(d_str)
        elif day_count == len(expected_bars):
            complete.append(d_str)
        else:
            incomplete.append(d_str)

    return tuple(complete), tuple(incomplete)


def filter_dataframe_by_sessions(
    df: pd.DataFrame,
    allowed_sessions: Sequence[str],
) -> pd.DataFrame:
    """Returns chronologically ordered subset of rows belonging strictly to `allowed_sessions`."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    allowed_set = set(allowed_sessions)
    if not allowed_set:
        out = df.iloc[0:0].copy()
        out.attrs = dict(getattr(df, "attrs", {}) or {})
        return out
    parsed = pd.to_datetime(df["timestamp"])
    mask = parsed.apply(lambda ts: (ts.tz_convert(IST_ZONE).date() if ts.tzinfo else ts.date()).isoformat() in allowed_set)
    filtered = df.loc[mask].copy().reset_index(drop=True)
    filtered.attrs = dict(getattr(df, "attrs", {}) or {})
    return filtered


class DatasetEligibilityGate:
    """
    Step 4.7 Dataset Quality Gate integrating Step 4.6 DatasetValidator & governance controls.
    """

    def __init__(
        self,
        *,
        backtest_config: Optional[BacktestConfiguration] = None,
        data_store: Optional[HistoricalDataStore] = None,
        calendar: Optional[MultiYearTradingCalendar] = None,
        validator: Optional[DatasetValidator] = None,
    ) -> None:
        self.backtest_config = backtest_config or BacktestConfiguration()
        self.data_store = data_store or HistoricalDataStore(config=self.backtest_config)
        self.calendar = calendar or MultiYearTradingCalendar()
        self.validator = validator or DatasetValidator(
            calendar_adapter=self.calendar,
            config=self.backtest_config,
        )

    def evaluate_single_timeframe(
        self,
        instrument: str,
        timeframe: str,
        *,
        start_time_ist: Optional[datetime] = None,
        end_time_ist: Optional[datetime] = None,
        sensex_governance_approved: bool = False,
        governance_ledger_path: Optional[str] = None,
        candles_override: Optional[pd.DataFrame] = None,
    ) -> Tuple[DatasetTimeframeEligibility, Optional[pd.DataFrame], DatasetValidationReport]:
        """Validates one `(instrument, timeframe)` slice from Step 4.6 persistence or explicit override."""
        norm_inst = normalize_instrument(instrument)
        norm_tf = normalize_timeframe(timeframe)

        if candles_override is not None:
            df = candles_override.copy()
        else:
            df = self.data_store.load_candles(
                norm_inst,
                norm_tf,
                start_time_ist=start_time_ist,
                end_time_ist=end_time_ist,
            )

        expected_from = parse_ist_datetime(start_time_ist, "start_time_ist") if start_time_ist else None
        expected_to = parse_ist_datetime(end_time_ist, "end_time_ist") if end_time_ist else None
        if expected_from is None and df is not None and not df.empty:
            ts0 = pd.to_datetime(df["timestamp"].iloc[0])
            ts0_ist = (ts0.tz_convert(IST_ZONE) if ts0.tzinfo else ts0.tz_localize(IST_ZONE)).to_pydatetime()
            expected_from = (
                datetime(ts0_ist.year, ts0_ist.month, ts0_ist.day, 9, 15, tzinfo=IST_ZONE)
                if norm_tf != "1d"
                else ts0_ist
            )
        if expected_to is None and df is not None and not df.empty:
            ts1 = pd.to_datetime(df["timestamp"].iloc[-1])
            ts1_ist = (ts1.tz_convert(IST_ZONE) if ts1.tzinfo else ts1.tz_localize(IST_ZONE)).to_pydatetime()
            expected_to = (
                datetime(ts1_ist.year, ts1_ist.month, ts1_ist.day, 15, 30, tzinfo=IST_ZONE)
                if norm_tf != "1d"
                else ts1_ist
            )

        val_cfg = BacktestConfiguration(
            storage_db_path=self.backtest_config.storage_db_path,
            governance_ledger_path=governance_ledger_path or self.backtest_config.governance_ledger_path,
            sensex_governance_approved=sensex_governance_approved,
        )
        eff_validator = (
            self.validator
            if (
                sensex_governance_approved == self.backtest_config.sensex_governance_approved
                and (governance_ledger_path or self.backtest_config.governance_ledger_path) == self.backtest_config.governance_ledger_path
            )
            else DatasetValidator(calendar_adapter=self.calendar, config=val_cfg)
        )
        val_rep = eff_validator.validate_dataset(
            df if df is not None else pd.DataFrame(),
            instrument=norm_inst,
            timeframe=norm_tf,
            expected_from_ist=expected_from,
            expected_to_ist=expected_to,
        )

        complete_sessions, incomplete_sessions = _extract_session_completeness(
            df, val_rep, self.calendar, norm_tf
        )
        complete_df = filter_dataframe_by_sessions(df, complete_sessions) if (df is not None and not df.empty) else df

        reasons: List[str] = list(val_rep.notes)
        if val_rep.governance_locked:
            elig = EligibilityClassification.GOVERNANCE_LOCKED
            full_claims = False
            reasons.append("GOVERNANCE_LOCKED: Instrument requires cryptographic governance approval.")
        elif val_rep.quality_status == DatasetQualityStatus.VERIFIED:
            elig = EligibilityClassification.VERIFIED_FULL_SESSION_ELIGIBLE
            full_claims = True
        elif val_rep.quality_status == DatasetQualityStatus.PARTIAL:
            elig = EligibilityClassification.PARTIAL_RESEARCH_ONLY
            full_claims = False
            reasons.append(
                f"PARTIAL_DATASET: {len(incomplete_sessions)} incomplete session(s) detected; full-session claims prohibited."
            )
        else:
            elig = EligibilityClassification.REJECTED_QUALITY_GATE
            full_claims = False
            reasons.append(
                f"QUALITY_REJECTED: Status={val_rep.quality_status.value}, missing={val_rep.missing_candles}, invalid={val_rep.invalid_candles}."
            )

        rec = DatasetTimeframeEligibility(
            instrument=norm_inst,
            timeframe=norm_tf,
            quality_status=val_rep.quality_status,
            eligibility=elig,
            total_bars=int(len(df)) if df is not None else 0,
            eligible_complete_bars=int(len(complete_df)) if complete_df is not None else 0,
            expected_sessions_count=val_rep.expected_trading_sessions,
            complete_sessions=complete_sessions,
            incomplete_sessions_excluded=incomplete_sessions,
            missing_intervals_count=len(val_rep.missing_intervals),
            dataset_fingerprint=val_rep.dataset_fingerprint or "UNAVAILABLE",
            date_range_start_ist=val_rep.actual_from_ist,
            date_range_end_ist=val_rep.actual_to_ist,
            full_session_claims_allowed=full_claims,
            reasons=tuple(reasons),
        )
        return rec, df, val_rep

    def evaluate_revalidation_eligibility(
        self,
        config: RevalidationConfig,
        *,
        candles_by_timeframe_override: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> Tuple[DatasetEligibilityDecision, Dict[str, pd.DataFrame]]:
        """
        Enforces Step 4.7 dataset quality gate across all configured timeframes before replay.
        Returns `(decision, filtered_candles_by_timeframe)`.
        """
        norm_inst = normalize_instrument(config.instrument)
        norm_primary = normalize_timeframe(config.primary_timeframe)
        required_tfs = tuple(dict.fromkeys(normalize_timeframe(tf) for tf in config.required_timeframes))
        all_tfs = tuple(dict.fromkeys([*required_tfs, *(normalize_timeframe(tf) for tf in config.replay_timeframes)]))
        optional_tfs = tuple(tf for tf in all_tfs if tf not in required_tfs)

        gov_ok, gov_status, gov_info = verify_index_governance(
            norm_inst,
            sensex_governance_approved=config.sensex_governance_approved,
            governance_db_path=config.governance_ledger_path or self.backtest_config.governance_ledger_path,
        )
        cal_fp = self.calendar.calendar_fingerprint()

        if not gov_ok:
            reason = f"{gov_status}: {gov_info.get('reason')}"
            decision = DatasetEligibilityDecision(
                instrument=norm_inst,
                primary_timeframe=norm_primary,
                required_timeframes=required_tfs,
                optional_timeframes=optional_tfs,
                overall_quality_status=DatasetQualityStatus.UNAVAILABLE,
                eligibility=EligibilityClassification.GOVERNANCE_LOCKED,
                eligible_for_replay=False,
                full_session_claims_allowed=False,
                research_only_flag=True,
                composite_dataset_fingerprint="GOVERNANCE_LOCKED",
                calendar_fingerprint=cal_fp,
                rejection_reasons=(reason,),
            )
            return decision, {}

        raw_dfs: Dict[str, pd.DataFrame] = {}
        tf_records: List[DatasetTimeframeEligibility] = []
        rejections: List[str] = []

        for tf in all_tfs:
            override_df = candles_by_timeframe_override.get(tf) if candles_by_timeframe_override else None
            rec, df, _ = self.evaluate_single_timeframe(
                norm_inst,
                tf,
                start_time_ist=config.start_time_ist,
                end_time_ist=config.end_time_ist,
                sensex_governance_approved=config.sensex_governance_approved,
                governance_ledger_path=config.governance_ledger_path,
                candles_override=override_df,
            )
            tf_records.append(rec)
            if df is not None and not df.empty:
                raw_dfs[tf] = df

        by_tf = {r.timeframe: r for r in tf_records}

        # Check required timeframes exist and are not DEGRADED/UNAVAILABLE
        for tf in required_tfs:
            rec = by_tf[tf]
            if rec.quality_status in (DatasetQualityStatus.DEGRADED, DatasetQualityStatus.UNAVAILABLE):
                rejections.append(
                    f"REQUIRED_TF_REJECTED ({tf}): quality_status={rec.quality_status.value}."
                )

        if rejections:
            decision = DatasetEligibilityDecision(
                instrument=norm_inst,
                primary_timeframe=norm_primary,
                required_timeframes=required_tfs,
                optional_timeframes=optional_tfs,
                overall_quality_status=DatasetQualityStatus.DEGRADED,
                eligibility=EligibilityClassification.REJECTED_QUALITY_GATE,
                eligible_for_replay=False,
                full_session_claims_allowed=False,
                research_only_flag=True,
                composite_dataset_fingerprint=deterministic_reval_hash([r.dataset_fingerprint for r in tf_records]),
                calendar_fingerprint=cal_fp,
                timeframe_records=tuple(tf_records),
                rejection_reasons=tuple(rejections),
            )
            return decision, {}

        # Detect quality mixing across evaluated timeframes that have bars
        active_req_qualities = {by_tf[tf].quality_status for tf in required_tfs}
        all_present_qualities = {
            r.quality_status
            for r in tf_records
            if r.total_bars > 0 and r.quality_status in (DatasetQualityStatus.VERIFIED, DatasetQualityStatus.PARTIAL)
        }
        has_partial = DatasetQualityStatus.PARTIAL in all_present_qualities
        has_verified = DatasetQualityStatus.VERIFIED in all_present_qualities

        if config.require_identical_timeframe_quality and has_partial and has_verified and not config.allow_partial_research_only:
            rejections.append(
                "MIXED_DATASET_QUALITY_FORBIDDEN: Cannot silently combine VERIFIED and PARTIAL datasets without explicit allow_partial_research_only=True."
            )
            decision = DatasetEligibilityDecision(
                instrument=norm_inst,
                primary_timeframe=norm_primary,
                required_timeframes=required_tfs,
                optional_timeframes=optional_tfs,
                overall_quality_status=DatasetQualityStatus.PARTIAL,
                eligibility=EligibilityClassification.REJECTED_MIXED_QUALITY,
                eligible_for_replay=False,
                full_session_claims_allowed=False,
                research_only_flag=True,
                composite_dataset_fingerprint=deterministic_reval_hash([r.dataset_fingerprint for r in tf_records]),
                calendar_fingerprint=cal_fp,
                timeframe_records=tuple(tf_records),
                rejection_reasons=tuple(rejections),
            )
            return decision, {}

        # Optional degraded timeframes must never be silently mixed into replay
        for tf in optional_tfs:
            rec = by_tf[tf]
            if rec.total_bars > 0 and rec.quality_status in (DatasetQualityStatus.DEGRADED, DatasetQualityStatus.UNAVAILABLE):
                rejections.append(
                    f"OPTIONAL_TF_DEGRADED ({tf}): Excluded/blocked due to {rec.quality_status.value} integrity failure."
                )

        if any("OPTIONAL_TF_DEGRADED" in r for r in rejections):
            decision = DatasetEligibilityDecision(
                instrument=norm_inst,
                primary_timeframe=norm_primary,
                required_timeframes=required_tfs,
                optional_timeframes=optional_tfs,
                overall_quality_status=DatasetQualityStatus.DEGRADED,
                eligibility=EligibilityClassification.REJECTED_QUALITY_GATE,
                eligible_for_replay=False,
                full_session_claims_allowed=False,
                research_only_flag=True,
                composite_dataset_fingerprint=deterministic_reval_hash([r.dataset_fingerprint for r in tf_records]),
                calendar_fingerprint=cal_fp,
                timeframe_records=tuple(tf_records),
                rejection_reasons=tuple(rejections),
            )
            return decision, {}

        # Check PARTIAL gate
        if DatasetQualityStatus.PARTIAL in active_req_qualities or (has_partial and not all_present_qualities == {DatasetQualityStatus.VERIFIED}):
            if not config.allow_partial_research_only:
                rejections.append(
                    "PARTIAL_DATASET_REQUIRES_RESEARCH_OPT_IN: PARTIAL datasets must not be used for full-session claims and require allow_partial_research_only=True."
                )
                decision = DatasetEligibilityDecision(
                    instrument=norm_inst,
                    primary_timeframe=norm_primary,
                    required_timeframes=required_tfs,
                    optional_timeframes=optional_tfs,
                    overall_quality_status=DatasetQualityStatus.PARTIAL,
                    eligibility=EligibilityClassification.PARTIAL_RESEARCH_ONLY,
                    eligible_for_replay=False,
                    full_session_claims_allowed=False,
                    research_only_flag=True,
                    composite_dataset_fingerprint=deterministic_reval_hash([r.dataset_fingerprint for r in tf_records]),
                    calendar_fingerprint=cal_fp,
                    timeframe_records=tuple(tf_records),
                    rejection_reasons=tuple(rejections),
                )
                return decision, {}

        # Determine common complete sessions across required timeframes
        req_complete_sets = [set(by_tf[tf].complete_sessions) for tf in required_tfs]
        common_complete = sorted(set.intersection(*req_complete_sets)) if req_complete_sets else []
        all_present_sessions = sorted(
            set.union(*(set(by_tf[tf].complete_sessions) | set(by_tf[tf].incomplete_sessions_excluded) for tf in all_tfs))
        )
        excluded_incomplete = tuple(s for s in all_present_sessions if s not in set(common_complete))

        if not common_complete:
            rejections.append(
                "NO_COMMON_COMPLETE_SESSIONS: Zero complete trading sessions remain after excluding incomplete sessions."
            )
            decision = DatasetEligibilityDecision(
                instrument=norm_inst,
                primary_timeframe=norm_primary,
                required_timeframes=required_tfs,
                optional_timeframes=optional_tfs,
                overall_quality_status=DatasetQualityStatus.PARTIAL if has_partial else DatasetQualityStatus.UNAVAILABLE,
                eligibility=EligibilityClassification.REJECTED_QUALITY_GATE,
                eligible_for_replay=False,
                full_session_claims_allowed=False,
                research_only_flag=True,
                composite_dataset_fingerprint=deterministic_reval_hash([r.dataset_fingerprint for r in tf_records]),
                calendar_fingerprint=cal_fp,
                common_complete_sessions=(),
                excluded_incomplete_sessions=excluded_incomplete,
                timeframe_records=tuple(tf_records),
                rejection_reasons=tuple(rejections),
            )
            return decision, {}

        # Filter candles to complete sessions if configured (mandatory for complete-session evaluation)
        filtered_candles: Dict[str, pd.DataFrame] = {}
        for tf, raw_df in raw_dfs.items():
            rec = by_tf[tf]
            if tf not in required_tfs and rec.quality_status == DatasetQualityStatus.PARTIAL and not config.allow_partial_research_only:
                continue
            if config.exclude_incomplete_sessions:
                sub_df = filter_dataframe_by_sessions(raw_df, common_complete)
            else:
                sub_df = raw_df.copy()
            if not sub_df.empty:
                filtered_candles[tf] = sub_df

        all_req_verified = active_req_qualities == {DatasetQualityStatus.VERIFIED}
        if all_req_verified and not has_partial:
            overall_q = DatasetQualityStatus.VERIFIED
            overall_elig = EligibilityClassification.VERIFIED_FULL_SESSION_ELIGIBLE
            full_claims = True
            research_flag = False
        else:
            overall_q = DatasetQualityStatus.PARTIAL
            overall_elig = EligibilityClassification.PARTIAL_RESEARCH_ONLY
            full_claims = False
            research_flag = True

        decision = DatasetEligibilityDecision(
            instrument=norm_inst,
            primary_timeframe=norm_primary,
            required_timeframes=required_tfs,
            optional_timeframes=optional_tfs,
            overall_quality_status=overall_q,
            eligibility=overall_elig,
            eligible_for_replay=True,
            full_session_claims_allowed=full_claims,
            research_only_flag=research_flag,
            composite_dataset_fingerprint=deterministic_reval_hash([r.dataset_fingerprint for r in tf_records]),
            calendar_fingerprint=cal_fp,
            common_complete_sessions=tuple(common_complete),
            excluded_incomplete_sessions=excluded_incomplete,
            timeframe_records=tuple(tf_records),
            rejection_reasons=tuple(rejections),
        )
        return decision, filtered_candles


def build_causal_point_in_time_quote(
    sliced_by_tf: Dict[str, pd.DataFrame],
    primary_timeframe: str,
    as_of_ist: datetime,
) -> Dict[str, Any]:
    """
    Constructs a strictly causal historical quote using ONLY completed candles
    whose availability timestamp <= `as_of_ist`. Never touches future bars.
    """
    norm_primary = normalize_timeframe(primary_timeframe)
    primary_df = sliced_by_tf.get(norm_primary)
    if primary_df is None or primary_df.empty:
        # Try any available completed timeframe strictly ordered finest -> coarsest already in slice
        for candidate_tf in ("1m", "3m", "5m", "15m", "1h", "1d"):
            cand = sliced_by_tf.get(candidate_tf)
            if cand is not None and not cand.empty:
                primary_df = cand
                break
    if primary_df is None or primary_df.empty:
        raise ValueError(f"NO_CAUSAL_BARS: No completed bars exist <= {as_of_ist.isoformat()}.")

    ts_col = pd.to_datetime(primary_df["timestamp"])
    ts_ist = ts_col.apply(lambda x: x.tz_convert(IST_ZONE) if x.tzinfo else x.tz_localize(IST_ZONE))
    cur_date = as_of_ist.astimezone(IST_ZONE).date()

    same_day_mask = ts_ist.apply(lambda x: x.date() == cur_date)
    prior_day_mask = ts_ist.apply(lambda x: x.date() < cur_date)

    latest_bar = primary_df.iloc[-1]
    ltp = float(latest_bar["close"])

    if bool(same_day_mask.any()):
        day_df = primary_df.loc[same_day_mask]
        day_open = float(day_df["open"].iloc[0])
        day_high = float(day_df["high"].max())
        day_low = float(day_df["low"].min())
    else:
        day_open = float(latest_bar["open"])
        day_high = float(latest_bar["high"])
        day_low = float(latest_bar["low"])

    prev_close = float(primary_df.loc[prior_day_mask]["close"].iloc[-1]) if bool(prior_day_mask.any()) else day_open

    return {
        "currentPrice": ltp,
        "ltp": ltp,
        "open": day_open,
        "high": day_high,
        "low": day_low,
        "previousClose": prev_close,
        "asOfIst": as_of_ist.astimezone(IST_ZONE).isoformat(),
    }


def collect_chronological_replay_times(
    primary_df: pd.DataFrame,
    *,
    primary_timeframe: str,
    market_close_hhmm: str = "15:30",
    min_warmup_bars: int = 15,
    stride_bars: int = 1,
) -> List[datetime]:
    """
    Collects strictly ascending bar-close timestamps (`available_at_ist`) after
    satisfying minimum causal warmup bars on the primary timeframe.
    """
    if primary_df is None or primary_df.empty or len(primary_df) <= min_warmup_bars:
        return []
    df_sorted = primary_df.sort_values("timestamp").reset_index(drop=True)
    times: List[datetime] = []
    for idx in range(min_warmup_bars, len(df_sorted), stride_bars):
        raw_ts = pd.to_datetime(df_sorted.iloc[idx]["timestamp"]).to_pydatetime()
        if raw_ts.tzinfo is None or raw_ts.tzinfo.utcoffset(raw_ts) is None:
            raw_ts = raw_ts.replace(tzinfo=IST_ZONE)
        else:
            raw_ts = raw_ts.astimezone(IST_ZONE)
        hh_c, mm_c = [int(x) for x in market_close_hhmm.strip().split(":")]
        close_t = dt_time(hh_c, mm_c)
        avail_ist = compute_candle_close_ist(
            raw_ts, timeframe=primary_timeframe, market_close_time=close_t
        )
        if not times or avail_ist > times[-1]:
            times.append(avail_ist)
    return times


class HistoricalSignalRevalidator:
    """
    Chronologically replays frozen Phase 2 and Phase 3 (Step 4.2) engines over
    validated Step 4.6 candles with strict point-in-time causality.
    """

    def __init__(
        self,
        *,
        backtest_config: Optional[BacktestConfiguration] = None,
        data_store: Optional[HistoricalDataStore] = None,
    ) -> None:
        self.backtest_config = backtest_config or BacktestConfiguration()
        self.data_store = data_store or HistoricalDataStore(config=self.backtest_config)
        self.calendar = MultiYearTradingCalendar()

    def evaluate_chronological_signals(
        self,
        *,
        config: RevalidationConfig,
        eligibility: DatasetEligibilityDecision,
        candles_by_timeframe: Dict[str, pd.DataFrame],
        persist_replay_run: bool = True,
    ) -> Tuple[ReplayRunRecord, Tuple[RevalidationSignalRecord, ...]]:
        """
        Runs Step 4.2 DeterministicReplayRunner for Phase 3 ICT/SMC evidence and evaluates
        frozen Phase 2 market regime, MTF confluence, and setup qualification at each timestamp.
        """
        norm_inst = normalize_instrument(config.instrument)
        norm_primary = normalize_timeframe(config.primary_timeframe)
        primary_df = candles_by_timeframe.get(norm_primary)
        if primary_df is None or primary_df.empty:
            raise ValueError(f"Primary timeframe '{norm_primary}' has no eligible candles.")

        replay_times = collect_chronological_replay_times(
            primary_df,
            primary_timeframe=norm_primary,
            market_close_hhmm=self.backtest_config.market_close_hhmm,
            min_warmup_bars=config.min_warmup_bars_primary,
            stride_bars=config.eval_stride_bars,
        )
        if not replay_times:
            raise ValueError(
                f"INSUFFICIENT_BARS: Need > {config.min_warmup_bars_primary} primary '{norm_primary}' bars for causal warmup."
            )

        # In PARTIAL_RESEARCH_ONLY mode after explicit incomplete session removal,
        # intermediate session gaps exist between remaining complete sessions, so
        # strict_missing_intervals must reflect whether this run is VERIFIED full-session
        # vs research-only post-exclusion.
        replay_bt_cfg = BacktestConfiguration(
            storage_db_path=config.storage_db_path or self.backtest_config.storage_db_path,
            governance_ledger_path=config.governance_ledger_path or self.backtest_config.governance_ledger_path,
            sensex_governance_approved=config.sensex_governance_approved,
            strict_missing_intervals=not eligibility.research_only_flag,
        )
        replay_runner = DeterministicReplayRunner(
            config=replay_bt_cfg,
            data_store=self.data_store,
            calendar_adapter=self.calendar,
        )

        eval_tfs = tuple(tf for tf in config.replay_timeframes if tf in candles_by_timeframe)
        replay_run = replay_runner.run_replay(
            instrument=norm_inst,
            replay_times=replay_times,
            candles_by_timeframe=candles_by_timeframe,
            timeframes=eval_tfs,
            data_source=f"step4_7_{eligibility.eligibility.value.lower()}",
            include_session_context=True,
            persist=persist_replay_run,
        )

        if replay_run.validation_status != ReplayValidationStatus.VALIDATED:
            raise RuntimeError(
                f"REPLAY_VALIDATION_FAILED ({replay_run.validation_status.value}): {replay_run.failure_reasons}"
            )

        cfg_fp = deterministic_reval_hash(config.model_dump(mode="json"))
        point_by_ts = {pt.as_of_time_ist: pt for pt in replay_run.points}
        records: List[RevalidationSignalRecord] = []

        for as_of_ist in replay_times:
            as_of_iso = as_of_ist.astimezone(IST_ZONE).isoformat()
            pt = point_by_ts[as_of_iso]
            if pt.confluence_score is not None:
                raise RuntimeError("ICT score leakage detected: Phase 3 score must remain None.")

            # Slice strictly <= as_of_ist (completed candles only, zero future lookahead)
            sliced_by_tf: Dict[str, pd.DataFrame] = {}
            for tf in eval_tfs:
                raw_tf_df = candles_by_timeframe[tf]
                s_df, fut_c, inc_c, err = slice_completed_candles_as_of(
                    raw_tf_df,
                    timeframe=tf,
                    as_of_time=as_of_ist,
                    market_close_hhmm=self.backtest_config.market_close_hhmm,
                )
                if err is not None:
                    raise RuntimeError(f"NO_LOOKAHEAD_SLICE_ERROR ({tf}): {err}")
                if fut_c < 0 or inc_c < 0:
                    raise RuntimeError("Invalid negative exclusion count.")
                if s_df is not None and not s_df.empty:
                    # Mark sliced historical bars explicitly closed so frozen Phase 2 filter
                    # never depends on wall-clock datetime comparisons across distant years.
                    closed_copy = s_df.copy()
                    closed_copy["is_closed"] = True
                    closed_copy["is_complete"] = True
                    closed_copy.attrs = {
                        "timeframe": tf,
                        "dataStatus": "VERIFIED_LIVE",
                        "data_status": "VERIFIED_LIVE",
                        "source": f"step4_7_{eligibility.overall_quality_status.value}",
                    }
                    sliced_by_tf[tf] = closed_copy

            causal_quote = build_causal_point_in_time_quote(
                sliced_by_tf, norm_primary, as_of_ist
            )
            spot_ref = float(causal_quote["currentPrice"])
            df_15m = sliced_by_tf.get("15m")
            df_5m = sliced_by_tf.get("5m")

            rej_reasons: List[str] = []
            market_state: Optional[Dict[str, Any]] = None
            mtf_conf: Optional[Dict[str, Any]] = None
            setup_res: Optional[Dict[str, Any]] = None

            if df_15m is None or len(df_15m) < 4:
                rej_reasons.append("Stage 3 Rejection: 15M completed slice missing or < 4 bars.")
            if df_5m is None or len(df_5m) < 4:
                rej_reasons.append("Stage 3 Rejection: 5M completed slice missing or < 4 bars.")

            if not rej_reasons and df_15m is not None:
                candles_info_15m = process_candlestick_series(df_15m, symbol=norm_inst, timeframe="15m")
                market_state = evaluate_index_market_state(
                    symbol=norm_inst,
                    quote=causal_quote,
                    candles_df=df_15m,
                    candles_info=candles_info_15m,
                    option_chain_summary=None,
                    vix_value=config.neutral_vix_value,
                    is_live_data=True,
                    last_update_utc=None,
                )
                regime_str = str(market_state.get("market_regime") or MarketRegime.NO_TRADE)
                if regime_str in (MarketRegime.NO_TRADE, MarketRegime.DATA_UNAVAILABLE):
                    rej_reasons.extend(
                        market_state.get("rejection_reasons")
                        or [str(market_state.get("primaryReason", "Market regime NO_TRADE"))]
                    )
                elif regime_str == MarketRegime.SIDEWAYS:
                    rej_reasons.append("Stage 5 Rejection: SIDEWAYS regime locks directional option buying.")

                mtf_conf = evaluate_multi_timeframe_confluence(
                    symbol=norm_inst,
                    timeframe_candles=sliced_by_tf,
                    current_quote=causal_quote,
                    option_chain_summary=None,
                    vix_value=config.neutral_vix_value,
                    is_live_data=True,
                    data_quality_status="VERIFIED_LIVE",
                    market_regime_state=market_state,
                )
                mtf_conf["is_replay"] = True

                if not rej_reasons:
                    setup_cfg = dict(DEFAULT_SETUP_CONFIG)
                    setup_cfg["min_confluence_score"] = float(config.min_confluence_score)
                    setup_res = select_trade_setup(
                        symbol=norm_inst,
                        quote=causal_quote,
                        mtf_confluence=mtf_conf,
                        market_regime_state=market_state,
                        option_chain_summary=None,
                        vix_value=config.neutral_vix_value,
                        is_live_data=True,
                        config=setup_cfg,
                    )
            else:
                regime_str = MarketRegime.NO_TRADE

            # Map final action strictly without forcing NO_TRADE or WAIT
            if setup_res is not None:
                raw_action = str(setup_res.get("action", "NO_TRADE"))
                qual_status = str(setup_res.get("qualification_status", "REJECTED"))
                rej_reasons.extend(str(r) for r in setup_res.get("rejection_reasons", []))
            else:
                raw_action = "NO_TRADE"
                qual_status = "REJECTED"

            if raw_action not in ("BUY_CE", "BUY_PE", "WAIT", "NO_TRADE"):
                raw_action = "NO_TRADE"

            action_enum = RevalidationSignalDirection(raw_action)
            plan = (setup_res or {}).get("trade_setup") or {}
            entry_eligible = False
            entry_px: Optional[float] = None
            sl_px: Optional[float] = None
            t1_px: Optional[float] = None
            t2_px: Optional[float] = None
            rr_val: Optional[float] = None

            if action_enum in (RevalidationSignalDirection.BUY_CE, RevalidationSignalDirection.BUY_PE) and isinstance(plan, dict):
                e_p = plan.get("entry_price")
                s_p = plan.get("stop_loss")
                t1 = plan.get("target_1")
                t2 = plan.get("target_2")
                rr = plan.get("reward_risk_ratio")
                if e_p is not None and s_p is not None and t1 is not None:
                    e_f, s_f, t1_f = float(e_p), float(s_p), float(t1)
                    t2_f = float(t2) if t2 is not None else None
                    geom_ok = (
                        (action_enum == RevalidationSignalDirection.BUY_CE and s_f < e_f < t1_f and (t2_f is None or t2_f > t1_f))
                        or (action_enum == RevalidationSignalDirection.BUY_PE and s_f > e_f > t1_f and (t2_f is None or t2_f < t1_f))
                    )
                    if geom_ok:
                        entry_eligible = True
                        entry_px, sl_px, t1_px, t2_px = e_f, s_f, t1_f, t2_f
                        rr_val = float(rr) if rr is not None else None
                    else:
                        rej_reasons.append("Invalid geometric relationship between entry, stop_loss, and targets.")
                        action_enum = RevalidationSignalDirection.NO_TRADE
                        qual_status = "GEOMETRY_INVALID"
                else:
                    rej_reasons.append("Missing trade setup risk levels.")
                    action_enum = RevalidationSignalDirection.NO_TRADE
                    qual_status = "REJECTED"

            # Prevent duplicate rejection strings deterministically
            dedup_reasons = tuple(dict.fromkeys(r for r in rej_reasons if str(r).strip()))
            sig_id = f"REVAL-{deterministic_reval_hash([norm_inst, norm_primary, as_of_iso, eligibility.composite_dataset_fingerprint])[:16]}"
            records.append(
                RevalidationSignalRecord(
                    signal_id=sig_id,
                    as_of_time_ist=as_of_iso,
                    session_date_ist=as_of_ist.astimezone(IST_ZONE).date().isoformat(),
                    session_bucket=classify_ist_session_bucket(as_of_ist),
                    instrument=norm_inst,
                    primary_timeframe=norm_primary,
                    spot_reference=spot_ref,
                    signal_direction=action_enum,
                    qualification_status=qual_status,
                    market_regime=regime_str,
                    phase2_directional_bias=str((mtf_conf or {}).get("directional_bias", "NEUTRAL")),
                    phase2_confluence_score=(
                        float(mtf_conf["confluence_score"]) if mtf_conf and mtf_conf.get("confluence_score") is not None else None
                    ),
                    phase2_missing_timeframes=tuple(str(x) for x in (mtf_conf or {}).get("missing_timeframes", ())),
                    phase3_alignment=str(pt.overall_alignment),
                    phase3_ict_score=None,
                    phase3_score_status="UNAVAILABLE",
                    phase3_calibration_status="NOT_CALIBRATED",
                    phase3_bullish_evidence=tuple(str(x) for x in pt.report.get("bullish_evidence", ())),
                    phase3_bearish_evidence=tuple(str(x) for x in pt.report.get("bearish_evidence", ())),
                    phase3_conflicts=tuple(str(x) for x in pt.report.get("conflicts", ())),
                    source_event_ids=tuple(str(x) for x in pt.evidence_event_ids),
                    source_replay_report_id=pt.report_id,
                    entry_price=entry_px,
                    stop_loss=sl_px,
                    target_1=t1_px,
                    target_2=t2_px,
                    reward_risk_ratio=rr_val,
                    data_quality_status=eligibility.overall_quality_status.value,
                    entry_eligible=entry_eligible,
                    rejection_reasons=dedup_reasons,
                    dataset_fingerprint=eligibility.composite_dataset_fingerprint,
                    engine_versions=dict(PHASE2_ENGINE_VERSIONS),
                    config_fingerprint=cfg_fp,
                )
            )

        return replay_run, tuple(records)
