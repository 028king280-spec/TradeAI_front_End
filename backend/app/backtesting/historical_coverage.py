"""
AIVOLVE Phase 4 Step 4.6 — Historical Dataset Coverage Reporting Engine.

Produces deterministic, auditable dataset coverage inventories across instruments
(`NIFTY 50`, `BANK NIFTY`, `FINNIFTY`, and governance-locked `SENSEX`) and all six
canonical timeframes (`1m`, `3m`, `5m`, `15m`, `1h`, `1d`), strictly distinguishing:
`VERIFIED`, `PARTIAL`, `DEGRADED`, and `UNAVAILABLE`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dt_time, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from app.backtesting.configuration import (
    BacktestConfiguration,
    IST_ZONE,
    SUPPORTED_INDICES,
    SUPPORTED_TIMEFRAMES,
    normalize_instrument,
    normalize_timeframe,
    verify_index_governance,
)
from app.backtesting.data_store import HistoricalDataStore
from app.backtesting.dataset_provenance import DatasetProvenanceStore
from app.backtesting.dataset_validation import (
    DatasetQualityStatus,
    DatasetValidationReport,
    DatasetValidator,
)
from app.backtesting.multi_year_calendar import MultiYearTradingCalendar
from app.backtesting.models import CalendarStatus
from app.backtesting.trade_lifecycle import deterministic_id


@dataclass(frozen=True)
class InstrumentTimeframeCoverage:
    instrument: str
    timeframe: str
    start_date: Optional[str]
    end_date: Optional[str]
    start_timestamp_ist: Optional[str]
    end_timestamp_ist: Optional[str]
    trading_sessions_covered: int
    expected_trading_sessions: int
    expected_candles: int
    actual_candles: int
    missing_candles: int
    duplicate_count: int
    invalid_candles: int
    data_source: str
    quality_status: DatasetQualityStatus
    last_successful_ingestion_utc: Optional[str]
    dataset_fingerprint: Optional[str]
    calendar_status: CalendarStatus
    governance_locked: bool
    source_timezone_observed: Optional[str]
    issues: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["quality_status"] = self.quality_status.value
        payload["calendar_status"] = self.calendar_status.value
        payload["issues"] = list(self.issues)
        return payload


@dataclass(frozen=True)
class HistoricalCoverageReport:
    report_id: str
    generated_at_utc: str
    storage_db_path: str
    instruments_evaluated: Tuple[str, ...]
    timeframes_evaluated: Tuple[str, ...]
    entries: Tuple[InstrumentTimeframeCoverage, ...]
    status_counts: Dict[str, int]
    total_actual_candles: int
    total_expected_candles: int
    total_missing_candles: int
    total_invalid_candles: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at_utc": self.generated_at_utc,
            "storage_db_path": self.storage_db_path,
            "instruments_evaluated": list(self.instruments_evaluated),
            "timeframes_evaluated": list(self.timeframes_evaluated),
            "entries": [e.to_dict() for e in self.entries],
            "status_counts": dict(self.status_counts),
            "total_actual_candles": self.total_actual_candles,
            "total_expected_candles": self.total_expected_candles,
            "total_missing_candles": self.total_missing_candles,
            "total_invalid_candles": self.total_invalid_candles,
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


class HistoricalCoverageEngine:
    """
    Computes deterministic coverage and quality reports from isolated `HistoricalDataStore`
    candles, `DatasetProvenanceStore` ingestion provenance, and `DatasetValidator`.
    """

    def __init__(
        self,
        *,
        data_store: Optional[HistoricalDataStore] = None,
        provenance_store: Optional[DatasetProvenanceStore] = None,
        calendar: Optional[MultiYearTradingCalendar] = None,
        validator: Optional[DatasetValidator] = None,
        config: Optional[BacktestConfiguration] = None,
    ) -> None:
        self.config = config or BacktestConfiguration()
        self.data_store = data_store or HistoricalDataStore(config=self.config)
        self.provenance_store = provenance_store or DatasetProvenanceStore(
            db_path=self.data_store.db_path
        )
        self.calendar = calendar or MultiYearTradingCalendar()
        self.validator = validator or DatasetValidator(
            calendar_adapter=self.calendar,
            config=self.config,
        )

    def _raw_duplicate_count(self, instrument: str, timeframe: str) -> int:
        # `historical_candles` enforces PRIMARY KEY (instrument, timeframe, epoch_ms),
        # while chunk/manifest provenance records any duplicate rows seen prior to upsert.
        prov_records = self.provenance_store.get_dataset_provenance(
            instrument=instrument, timeframe=timeframe
        )
        return sum(int(p.duplicate_count) for p in prov_records)

    def _resolve_provenance_meta(
        self, instrument: str, timeframe: str, df: pd.DataFrame
    ) -> Tuple[str, Optional[str], Optional[str]]:
        prov_records = self.provenance_store.get_dataset_provenance(
            instrument=instrument, timeframe=timeframe
        )
        last_ingestion_utc: Optional[str] = None
        provider_name = "NONE"
        tz_obs: Optional[str] = None

        if prov_records:
            latest = prov_records[0]
            provider_name = latest.provider or "angelone"
            last_ingestion_utc = latest.download_timestamp_utc
            if latest.source_timezone_offsets:
                tz_obs = ",".join(latest.source_timezone_offsets)
        else:
            manifests = self.data_store.get_ingestion_manifests(
                instrument=instrument, timeframe=timeframe
            )
            if manifests:
                latest_m = manifests[0]
                provider_name = str(latest_m.get("provider") or "angelone")
                last_ingestion_utc = (
                    str(latest_m.get("completed_at_utc") or latest_m.get("started_at_utc") or "")
                    or None
                )
            elif df is not None and not df.empty and "provider" in df.columns:
                providers = sorted({str(p) for p in df["provider"].dropna().tolist() if str(p)})
                provider_name = ",".join(providers) if providers else "UNKNOWN"

        if df is not None and not df.empty and tz_obs is None:
            tz_obs = "+05:30"
        return provider_name, last_ingestion_utc, tz_obs

    def evaluate_pair(
        self,
        instrument: str,
        timeframe: str,
        *,
        expected_range: Optional[Tuple[datetime, datetime]] = None,
    ) -> InstrumentTimeframeCoverage:
        canonical_inst = normalize_instrument(instrument)
        canonical_tf = normalize_timeframe(timeframe)

        gov_ok, _gov_status, gov_info = verify_index_governance(
            canonical_inst,
            sensex_governance_approved=self.config.sensex_governance_approved,
            governance_db_path=self.config.governance_ledger_path,
        )
        if not gov_ok:
            gov_reason = str(gov_info.get("reason") or _gov_status or "GOVERNANCE_LOCKOUT")
            return InstrumentTimeframeCoverage(
                instrument=canonical_inst,
                timeframe=canonical_tf,
                start_date=None,
                end_date=None,
                start_timestamp_ist=None,
                end_timestamp_ist=None,
                trading_sessions_covered=0,
                expected_trading_sessions=0,
                expected_candles=0,
                actual_candles=0,
                missing_candles=0,
                duplicate_count=0,
                invalid_candles=0,
                data_source="GOVERNANCE_LOCKED",
                quality_status=DatasetQualityStatus.UNAVAILABLE,
                last_successful_ingestion_utc=None,
                dataset_fingerprint=None,
                calendar_status=CalendarStatus.TRADING_DAY,
                governance_locked=True,
                source_timezone_observed=None,
                issues=(gov_reason,),
            )

        df = self.data_store.load_candles(canonical_inst, canonical_tf)
        provider_name, last_ingestion_utc, tz_obs = self._resolve_provenance_meta(
            canonical_inst, canonical_tf, df
        )

        if df.empty:
            exp_from, exp_to = expected_range if expected_range else (None, None)
            val_rep = self.validator.validate_dataset(
                df,
                instrument=canonical_inst,
                timeframe=canonical_tf,
                expected_from_ist=exp_from,
                expected_to_ist=exp_to,
            )
            return InstrumentTimeframeCoverage(
                instrument=canonical_inst,
                timeframe=canonical_tf,
                start_date=None,
                end_date=None,
                start_timestamp_ist=None,
                end_timestamp_ist=None,
                trading_sessions_covered=0,
                expected_trading_sessions=val_rep.expected_trading_sessions,
                expected_candles=val_rep.expected_candles,
                actual_candles=0,
                missing_candles=val_rep.missing_candles,
                duplicate_count=0,
                invalid_candles=0,
                data_source=provider_name if provider_name != "NONE" else "NONE",
                quality_status=DatasetQualityStatus.UNAVAILABLE,
                last_successful_ingestion_utc=last_ingestion_utc,
                dataset_fingerprint=None,
                calendar_status=val_rep.calendar_status,
                governance_locked=False,
                source_timezone_observed=None,
                issues=tuple(i.message for i in val_rep.issues),
            )

        ist_dts = sorted(
            dt for dt in (_to_ist_dt(v) for v in df["timestamp"].tolist()) if dt is not None
        )
        start_dt = ist_dts[0] if ist_dts else None
        end_dt = ist_dts[-1] if ist_dts else None

        if expected_range is not None:
            exp_from, exp_to = expected_range
        elif start_dt is not None and end_dt is not None:
            w_start = self.calendar.get_session_windows(start_dt.date())
            w_end = self.calendar.get_session_windows(end_dt.date())
            open_t = w_start[0].open_time if (w_start and canonical_tf != "1d") else dt_time(0, 0) if canonical_tf == "1d" else dt_time(9, 15)
            close_t = w_end[-1].close_time if w_end else dt_time(15, 30)
            exp_from = datetime.combine(start_dt.date(), open_t, tzinfo=IST_ZONE)
            exp_to = datetime.combine(end_dt.date(), close_t, tzinfo=IST_ZONE)
        else:
            exp_from, exp_to = None, None

        val_rep: DatasetValidationReport = self.validator.validate_dataset(
            df,
            instrument=canonical_inst,
            timeframe=canonical_tf,
            expected_from_ist=exp_from,
            expected_to_ist=exp_to,
            require_all_completed=True,
            check_missing_intervals=True,
        )

        # Combine in-DataFrame duplicate count (for standalone validation) with stored ingestion duplicate metric
        # Note: if database already deduplicated duplicates cleanly, val_rep.duplicate_count == 0;
        # we report raw duplicate observations separately only if detected inside dataset rows itself,
        # OR expose ingestion duplicate metrics inside provenance. Keep duplicate_count strictly accurate to validated dataset rows.
        issue_msgs = [i.message for i in val_rep.issues]
        for note in val_rep.notes:
            if note not in issue_msgs:
                issue_msgs.append(note)

        return InstrumentTimeframeCoverage(
            instrument=canonical_inst,
            timeframe=canonical_tf,
            start_date=start_dt.date().isoformat() if start_dt else None,
            end_date=end_dt.date().isoformat() if end_dt else None,
            start_timestamp_ist=start_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30") if start_dt else None,
            end_timestamp_ist=end_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30") if end_dt else None,
            trading_sessions_covered=val_rep.trading_sessions_covered,
            expected_trading_sessions=val_rep.expected_trading_sessions,
            expected_candles=val_rep.expected_candles,
            actual_candles=val_rep.actual_candles,
            missing_candles=val_rep.missing_candles,
            duplicate_count=val_rep.duplicate_count,
            invalid_candles=val_rep.invalid_candles,
            data_source=provider_name,
            quality_status=val_rep.quality_status,
            last_successful_ingestion_utc=last_ingestion_utc,
            dataset_fingerprint=val_rep.dataset_fingerprint,
            calendar_status=val_rep.calendar_status,
            governance_locked=False,
            source_timezone_observed=tz_obs,
            issues=tuple(issue_msgs),
        )

    def build_coverage_report(
        self,
        *,
        instruments: Sequence[str] = SUPPORTED_INDICES,
        timeframes: Sequence[str] = SUPPORTED_TIMEFRAMES,
        expected_ranges: Optional[Dict[Tuple[str, str], Tuple[datetime, datetime]]] = None,
        generated_at_utc: Optional[str] = None,
    ) -> HistoricalCoverageReport:
        canon_insts = tuple(normalize_instrument(i) for i in instruments)
        canon_tfs = tuple(normalize_timeframe(tf) for tf in timeframes)
        entries: List[InstrumentTimeframeCoverage] = []
        ranges_map = expected_ranges or {}

        for inst in canon_insts:
            for tf in canon_tfs:
                exp_range = ranges_map.get((inst, tf))
                entries.append(
                    self.evaluate_pair(inst, tf, expected_range=exp_range)
                )

        status_counts: Dict[str, int] = {
            DatasetQualityStatus.VERIFIED.value: 0,
            DatasetQualityStatus.PARTIAL.value: 0,
            DatasetQualityStatus.DEGRADED.value: 0,
            DatasetQualityStatus.UNAVAILABLE.value: 0,
        }
        for e in entries:
            status_counts[e.quality_status.value] = status_counts.get(e.quality_status.value, 0) + 1

        ts_utc = generated_at_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        report_id = deterministic_id(
            "COV",
            {
                "db": str(self.data_store.db_path.name),
                "entries": [
                    {
                        "i": e.instrument,
                        "tf": e.timeframe,
                        "status": e.quality_status.value,
                        "fp": e.dataset_fingerprint,
                        "actual": e.actual_candles,
                        "missing": e.missing_candles,
                    }
                    for e in entries
                ],
            },
            length=16,
        )

        return HistoricalCoverageReport(
            report_id=report_id,
            generated_at_utc=ts_utc,
            storage_db_path=str(self.data_store.db_path),
            instruments_evaluated=canon_insts,
            timeframes_evaluated=canon_tfs,
            entries=tuple(entries),
            status_counts=status_counts,
            total_actual_candles=sum(e.actual_candles for e in entries),
            total_expected_candles=sum(e.expected_candles for e in entries),
            total_missing_candles=sum(e.missing_candles for e in entries),
            total_invalid_candles=sum(e.invalid_candles for e in entries),
        )
