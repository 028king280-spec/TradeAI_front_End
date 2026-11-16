"""
AIVOLVE Phase 4 Step 4.6 — Dataset Expansion, Coverage & Audit Report Generator.

Combines:
- `HistoricalCoverageReport`
- `MultiYearTradingCalendar` provenance & special sessions
- `OptionsHistoryAuditSummary`
- `DatasetProvenanceStore` ingestion manifests

Produces deterministic structured reports (`DatasetExpansionReport`), Markdown
renders, and persists snapshots strictly inside `backend/data/backtest/`.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from app.backtesting.backtest_report import compute_report_fingerprint
from app.backtesting.configuration import (
    BacktestConfiguration,
    DEFAULT_BACKTEST_DB_PATH,
    SUPPORTED_INDICES,
    SUPPORTED_TIMEFRAMES,
    assert_isolated_backtest_path,
)
from app.backtesting.data_store import HistoricalDataStore
from app.backtesting.dataset_provenance import (
    DatasetProvenanceRecord,
    DatasetProvenanceStore,
)
from app.backtesting.dataset_validation import DatasetValidator
from app.backtesting.historical_coverage import (
    HistoricalCoverageEngine,
    HistoricalCoverageReport,
)
from app.backtesting.multi_year_calendar import (
    CalendarYearProvenance,
    ExceptionalClosureRecord,
    MultiYearTradingCalendar,
    SpecialTradingSessionRecord,
)
from app.backtesting.options_history_capability import (
    OptionsHistoryAuditSummary,
    OptionsHistoryCapabilityAuditor,
)
from app.backtesting.trade_lifecycle import deterministic_id


REPORT_VERSION_STEP4_6: str = "4.6.0"


@dataclass(frozen=True)
class DatasetExpansionReport:
    report_id: str
    report_version: str
    generated_at_utc: str
    report_fingerprint: str
    storage_db_path: str
    calendar_fingerprint: str
    calendar_years_covered: Tuple[int, ...]
    calendar_provenance: Tuple[CalendarYearProvenance, ...]
    special_sessions: Tuple[SpecialTradingSessionRecord, ...]
    exceptional_closures: Tuple[ExceptionalClosureRecord, ...]
    coverage_report: HistoricalCoverageReport
    options_capability_summary: OptionsHistoryAuditSummary
    ingestion_provenance_records: Tuple[DatasetProvenanceRecord, ...]
    markdown_summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "report_version": self.report_version,
            "generated_at_utc": self.generated_at_utc,
            "report_fingerprint": self.report_fingerprint,
            "storage_db_path": self.storage_db_path,
            "calendar_fingerprint": self.calendar_fingerprint,
            "calendar_years_covered": list(self.calendar_years_covered),
            "calendar_provenance": [p.to_dict() for p in self.calendar_provenance],
            "special_sessions": [s.to_dict() for s in self.special_sessions],
            "exceptional_closures": [c.to_dict() for c in self.exceptional_closures],
            "coverage_report": self.coverage_report.to_dict(),
            "options_capability_summary": self.options_capability_summary.to_dict(),
            "ingestion_provenance_records": [r.to_dict() for r in self.ingestion_provenance_records],
            "markdown_summary": self.markdown_summary,
        }


def render_dataset_expansion_markdown(report: DatasetExpansionReport) -> str:
    """Renders deterministic human-readable Step 4.6 Markdown report."""
    lines: List[str] = []
    lines.append("# AIVOLVE Phase 4 Step 4.6 — Historical Dataset Expansion & Validation Report")
    lines.append("")
    lines.append(f"- **Report ID:** `{report.report_id}`")
    lines.append(f"- **Report Fingerprint (SHA-256[:32]):** `{report.report_fingerprint}`")
    lines.append(f"- **Storage Database (Isolated):** `{report.storage_db_path}`")
    lines.append(f"- **Calendar Years Covered:** `{list(report.calendar_years_covered)}` (Fingerprint `{report.calendar_fingerprint}`)")
    lines.append(f"- **Status Counts:** `{report.coverage_report.status_counts}`")
    lines.append("")
    lines.append("## 1. Dataset Coverage by Instrument & Timeframe")
    lines.append("")
    lines.append(
        "| Instrument | Timeframe | Start Date | End Date | Sessions (Covered/Exp) | "
        "Expected | Actual | Missing | Dup | Invalid | Source | Quality Status | Last Ingestion (UTC) |"
    )
    lines.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---|")
    for e in report.coverage_report.entries:
        lines.append(
            f"| {e.instrument} | {e.timeframe} | {e.start_date or '-'} | {e.end_date or '-'} | "
            f"{e.trading_sessions_covered}/{e.expected_trading_sessions} | "
            f"{e.expected_candles} | {e.actual_candles} | {e.missing_candles} | "
            f"{e.duplicate_count} | {e.invalid_candles} | {e.data_source} | "
            f"**{e.quality_status.value}** | {e.last_successful_ingestion_utc or '-'} |"
        )
    lines.append("")
    lines.append("## 2. Historical Options Data Availability Audit")
    lines.append("")
    opt = report.options_capability_summary
    lines.append(f"- **Summary Verdict:** `{opt.summary_verdict}`")
    lines.append(f"- **Historical Option OHLC (Complete Expired Archive):** `{opt.historical_option_ohlc_available}`")
    lines.append(f"- **Historical Bid/Ask Quotes:** `{opt.historical_bid_ask_available}`")
    lines.append(f"- **Historical Option-Chain Snapshots:** `{opt.historical_option_chain_available}`")
    lines.append(f"- **Historical Implied Volatility:** `{opt.historical_iv_available}`")
    lines.append(f"- **Historical Greeks:** `{opt.historical_greeks_available}`")
    lines.append(f"- **Black-Scholes Treated as Market Observation:** `{opt.black_scholes_is_market_observation}`")
    lines.append("")
    lines.append("| Provider | Creds | Underlying OHLCV | Historical Opt OHLC | Hist Bid/Ask | Hist Option Chain | Hist IV | Hist Greeks | Expiry/Strike Metadata |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for p in opt.providers:
        lines.append(
            f"| {p.provider_name} | {p.credentials_configured} | {p.underlying_ohlcv.availability.value} | "
            f"{p.historical_option_ohlc.availability.value} | {p.historical_bid_ask.availability.value} | "
            f"{p.historical_option_chain_snapshots.availability.value} | {p.historical_implied_volatility.availability.value} | "
            f"{p.historical_greeks.availability.value} | {p.expiry_strike_metadata.availability.value} |"
        )
    lines.append("")
    lines.append("## 3. Multi-Year Calendar Provenance")
    lines.append("")
    lines.append("| Year | Exchange | Holidays | Special Sessions | Exceptional Closures | Source Reference | Checksum SHA-256 |")
    lines.append("|---:|---|---:|---:|---:|---|---|")
    for cp in report.calendar_provenance:
        lines.append(
            f"| {cp.year} | {cp.exchange} | {cp.holiday_count} | {cp.special_session_count} | "
            f"{cp.exceptional_closure_count} | {cp.source_reference} | `{cp.checksum_sha256[:16]}...` |"
        )
    return "\n".join(lines) + "\n"


class DatasetExpansionReportEngine:
    """Generates and persists deterministic Step 4.6 expansion & validation reports."""

    def __init__(
        self,
        *,
        data_store: Optional[HistoricalDataStore] = None,
        provenance_store: Optional[DatasetProvenanceStore] = None,
        calendar: Optional[MultiYearTradingCalendar] = None,
        validator: Optional[DatasetValidator] = None,
        coverage_engine: Optional[HistoricalCoverageEngine] = None,
        options_auditor: Optional[OptionsHistoryCapabilityAuditor] = None,
        config: Optional[BacktestConfiguration] = None,
    ) -> None:
        self.config = config or BacktestConfiguration()
        self.data_store = data_store or HistoricalDataStore(config=self.config)
        self.provenance_store = provenance_store or DatasetProvenanceStore(
            db_path=self.data_store.db_path
        )
        self.calendar = calendar or MultiYearTradingCalendar()
        self.validator = validator or DatasetValidator(
            calendar_adapter=self.calendar, config=self.config
        )
        self.coverage_engine = coverage_engine or HistoricalCoverageEngine(
            data_store=self.data_store,
            provenance_store=self.provenance_store,
            calendar=self.calendar,
            validator=self.validator,
            config=self.config,
        )
        self.options_auditor = options_auditor or OptionsHistoryCapabilityAuditor()
        self.db_path = assert_isolated_backtest_path(self.data_store.db_path)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_expansion_reports (
                    report_id TEXT PRIMARY KEY,
                    report_fingerprint TEXT NOT NULL,
                    report_version TEXT NOT NULL,
                    generated_at_utc TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    markdown_summary TEXT NOT NULL
                )
                """
            )

    def generate_report(
        self,
        *,
        instruments: Sequence[str] = SUPPORTED_INDICES,
        timeframes: Sequence[str] = SUPPORTED_TIMEFRAMES,
        expected_ranges: Optional[Dict[Tuple[str, str], Tuple[datetime, datetime]]] = None,
        options_probe_results: Optional[Dict[str, str]] = None,
        persist: bool = True,
        generated_at_utc: Optional[str] = None,
    ) -> DatasetExpansionReport:
        now_utc = generated_at_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        coverage = self.coverage_engine.build_coverage_report(
            instruments=instruments,
            timeframes=timeframes,
            expected_ranges=expected_ranges,
            generated_at_utc=now_utc,
        )
        options_summary = self.options_auditor.run_audit(probe_results=options_probe_results)
        prov_records = tuple(self.provenance_store.get_dataset_provenance())
        cal_prov = tuple(self.calendar.year_provenance_summary())
        sp_sessions = tuple(
            self.calendar.special_sessions[d] for d in sorted(self.calendar.special_sessions)
        )
        ec_closures = tuple(
            self.calendar.exceptional_closures[d] for d in sorted(self.calendar.exceptional_closures)
        )
        cal_fp = self.calendar.calendar_fingerprint()

        # Deterministic fingerprint excludes wall-clock timestamps and transient fields
        fingerprint_payload = {
            "version": REPORT_VERSION_STEP4_6,
            "calendar_fingerprint": cal_fp,
            "coverage_entries": [
                {
                    "instrument": e.instrument,
                    "timeframe": e.timeframe,
                    "start_date": e.start_date,
                    "end_date": e.end_date,
                    "expected_candles": e.expected_candles,
                    "actual_candles": e.actual_candles,
                    "missing_candles": e.missing_candles,
                    "duplicate_count": e.duplicate_count,
                    "invalid_candles": e.invalid_candles,
                    "quality_status": e.quality_status.value,
                    "dataset_fingerprint": e.dataset_fingerprint,
                }
                for e in coverage.entries
            ],
            "options_verdict": options_summary.summary_verdict,
        }
        report_fp = compute_report_fingerprint(fingerprint_payload)
        report_id = deterministic_id("EXP", fingerprint_payload, length=16)

        draft = DatasetExpansionReport(
            report_id=report_id,
            report_version=REPORT_VERSION_STEP4_6,
            generated_at_utc=now_utc,
            report_fingerprint=report_fp,
            storage_db_path=str(self.db_path),
            calendar_fingerprint=cal_fp,
            calendar_years_covered=tuple(sorted(self.calendar.covered_years)),
            calendar_provenance=cal_prov,
            special_sessions=sp_sessions,
            exceptional_closures=ec_closures,
            coverage_report=coverage,
            options_capability_summary=options_summary,
            ingestion_provenance_records=prov_records,
            markdown_summary="",
        )
        md = render_dataset_expansion_markdown(draft)
        final_report = DatasetExpansionReport(
            **{**draft.__dict__, "markdown_summary": md}
        )

        if persist:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO dataset_expansion_reports (
                        report_id, report_fingerprint, report_version,
                        generated_at_utc, report_json, markdown_summary
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        final_report.report_id,
                        final_report.report_fingerprint,
                        final_report.report_version,
                        final_report.generated_at_utc,
                        json.dumps(final_report.to_dict(), sort_keys=True, default=str),
                        final_report.markdown_summary,
                    ),
                )
        return final_report

