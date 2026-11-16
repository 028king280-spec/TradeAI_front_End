"""
AIVOLVE Phase 4 Step 4.2 — Isolated Historical Data & Replay Run Store.

Persists integrity-verified historical OHLCV datasets, ingestion manifests, and
deterministic Phase 3 replay run artifacts inside an isolated SQLite database
(default: `backend/data/backtest/backtest_foundation.db`).

Strict Isolation Guarantees:
- Never opens, creates, or writes to `aivolve_trading.db`, `governance_ledger.db`,
  `paper_trading_records.json`, `ml_trade_dataset.json`, `what_ai_learned.json`,
  or `ml_strategy_weights.json`.
- Never instantiates `PaperTradingEngine` or `MLFeedbackEngine`.
- Enforces strict `(instrument, timeframe)` storage & lookup with zero timeframe
  substitution (`3m` never falls back to `15m`).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from app.backtesting.calendar_adapter import HistoricalMarketCalendarAdapter
from app.backtesting.configuration import (
    BacktestConfiguration,
    DEFAULT_BACKTEST_DB_PATH,
    IST_ZONE,
    assert_isolated_backtest_path,
    normalize_instrument,
    normalize_timeframe,
    verify_index_governance,
)
from app.backtesting.data_integrity import DataIntegrityAuditor, compute_dataset_fingerprint
from app.backtesting.models import (
    ChunkDownloadRecord,
    DataIntegrityReport,
    IntegrityStatus,
    ReplayPointResult,
    ReplayRunRecord,
    ReplayValidationStatus,
)
from app.backtesting.simulation_models import SimulationRunResult


def _ensure_ist(dt: Optional[datetime], field_name: str) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{field_name} must be timezone-aware, got {dt!r}")
    return dt.astimezone(IST_ZONE)


class HistoricalDataStore:
    """
    SQLite-backed isolated storage for Phase 4 historical candles, download
    manifests, and deterministic Phase 3 replay run records.
    """

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        *,
        config: Optional[BacktestConfiguration] = None,
    ) -> None:
        self.config = config or BacktestConfiguration()
        raw_path = db_path if db_path is not None else self.config.storage_db_path
        self.db_path: Path = assert_isolated_backtest_path(raw_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        assert_isolated_backtest_path(self.db_path)
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = FULL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self):
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                yield conn
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def _init_schema(self) -> None:
        with self._transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_candles (
                    instrument TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    epoch_ms INTEGER NOT NULL,
                    timestamp_ist TEXT NOT NULL,
                    open REAL NOT NULL CHECK (open > 0),
                    high REAL NOT NULL CHECK (high > 0 AND high >= open AND high >= close),
                    low REAL NOT NULL CHECK (low > 0 AND low <= open AND low <= close AND high >= low),
                    close REAL NOT NULL CHECK (close > 0),
                    volume REAL NOT NULL CHECK (volume >= 0),
                    is_complete INTEGER NOT NULL CHECK (is_complete = 1),
                    provider TEXT NOT NULL,
                    ingestion_id TEXT NOT NULL,
                    PRIMARY KEY (instrument, timeframe, epoch_ms)
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_hist_candles_lookup
                ON historical_candles (instrument, timeframe, epoch_ms);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_ingestion_manifests (
                    ingestion_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol_token TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    requested_from_ist TEXT NOT NULL,
                    requested_to_ist TEXT NOT NULL,
                    actual_from_ist TEXT,
                    actual_to_ist TEXT,
                    bars_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    dataset_fingerprint TEXT NOT NULL,
                    integrity_report_json TEXT NOT NULL,
                    chunk_records_json TEXT NOT NULL,
                    retrieved_at_utc TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS replay_runs (
                    run_id TEXT PRIMARY KEY,
                    instrument TEXT NOT NULL,
                    timeframes_json TEXT NOT NULL,
                    start_date_ist TEXT NOT NULL,
                    end_date_ist TEXT NOT NULL,
                    historical_date_range TEXT NOT NULL,
                    data_source TEXT NOT NULL,
                    dataset_fingerprint TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    configuration_version TEXT NOT NULL,
                    calendar_source TEXT NOT NULL,
                    calendar_fingerprint TEXT NOT NULL,
                    replay_timestamps_json TEXT NOT NULL,
                    output_fingerprint TEXT NOT NULL,
                    validation_status TEXT NOT NULL,
                    run_payload_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                """
            )
            existing_sim_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(simulation_runs)").fetchall()
            }
            if existing_sim_cols and "accounting_unit_mode" not in existing_sim_cols:
                # Recreate only pre-clarification Step 4.3 `simulation_runs` lacking explicit unit segregation;
                # Step 4.2 tables (`historical_candles`, `historical_ingestion_manifests`, `replay_runs`) are untouched.
                conn.execute("DROP TABLE simulation_runs")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS simulation_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    accounting_unit_mode TEXT NOT NULL,
                    monetary_accounting_enabled INTEGER NOT NULL,
                    provenance_label TEXT NOT NULL,
                    is_synthetic_modelled INTEGER NOT NULL,
                    instrument TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    historical_date_range TEXT NOT NULL,
                    dataset_fingerprint TEXT NOT NULL,
                    calendar_fingerprint TEXT NOT NULL,
                    replay_run_id TEXT,
                    simulator_version TEXT NOT NULL,
                    cost_model_version TEXT NOT NULL,
                    output_fingerprint TEXT NOT NULL,
                    points_unit TEXT,
                    realized_net_points REAL,
                    total_slippage_points REAL,
                    currency_unit TEXT,
                    realized_net_pnl_inr REAL,
                    total_costs_inr REAL,
                    reconciled INTEGER NOT NULL,
                    run_payload_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                """
            )

    def save_candles(
        self,
        df: pd.DataFrame,
        *,
        instrument: str,
        timeframe: str,
        provider: str = "angelone",
        exchange: str = "NSE",
        symbol_token: str = "",
        calendar_adapter: Optional[HistoricalMarketCalendarAdapter] = None,
        auditor: Optional[DataIntegrityAuditor] = None,
        requested_from_ist: Optional[datetime] = None,
        requested_to_ist: Optional[datetime] = None,
        chunk_records: Sequence[ChunkDownloadRecord] = (),
        ingestion_id: Optional[str] = None,
        strict_missing_intervals: bool = True,
    ) -> Tuple[int, DataIntegrityReport, str]:
        """
        Audits and atomically persists clean historical OHLCV bars.

        Fails closed cleanly if SENSEX governance rejects the instrument or if
        `DataIntegrityAuditor` detects any anomaly, mock/repaired flag, or gap.
        """
        norm_inst = normalize_instrument(instrument)
        norm_tf = normalize_timeframe(timeframe)

        gov_ok, gov_status, gov_info = verify_index_governance(
            norm_inst,
            sensex_governance_approved=self.config.sensex_governance_approved,
            governance_db_path=self.config.governance_ledger_path,
        )
        if not gov_ok:
            raise PermissionError(f"{gov_status}: {gov_info.get('reason')}")

        eff_auditor = auditor or DataIntegrityAuditor(
            calendar_adapter=calendar_adapter,
            market_open_hhmm=self.config.market_open_hhmm,
            market_close_hhmm=self.config.market_close_hhmm,
            strict_missing_intervals=strict_missing_intervals,
            require_volume_column=self.config.require_volume_column,
        )
        req_from = _ensure_ist(requested_from_ist, "requested_from_ist")
        req_to = _ensure_ist(requested_to_ist, "requested_to_ist")

        report = eff_auditor.audit_dataframe(
            df,
            instrument=norm_inst,
            timeframe=norm_tf,
            expected_from_ist=req_from,
            expected_to_ist=req_to,
            require_all_completed=True,
            check_missing_intervals=True,
        )
        if not report.is_valid or report.status != IntegrityStatus.PASSED:
            raise ValueError(
                f"Cannot store unvalidated historical candles for {norm_inst} {norm_tf}: "
                + "; ".join(report.rejected_reasons)
            )

        eff_ingestion_id = ingestion_id or f"ING-{uuid.uuid4().hex[:16].upper()}"
        retrieved_utc = datetime.now(timezone.utc).isoformat()

        rows_to_insert: List[Tuple[Any, ...]] = []
        has_volume = "volume" in df.columns
        for idx in range(len(df)):
            row = df.iloc[idx]
            raw_ts = row["timestamp"]
            ts_obj = pd.to_datetime(raw_ts) if type(raw_ts) is str else raw_ts
            py_dt = ts_obj.to_pydatetime() if isinstance(ts_obj, pd.Timestamp) else ts_obj
            ts_ist = py_dt.astimezone(IST_ZONE)
            epoch_ms = int(round(ts_ist.timestamp() * 1000))
            rows_to_insert.append(
                (
                    norm_inst,
                    norm_tf,
                    epoch_ms,
                    ts_ist.isoformat(),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["volume"]) if has_volume else 0.0,
                    1,
                    provider.strip().lower(),
                    eff_ingestion_id,
                )
            )

        manifest_row = (
            eff_ingestion_id,
            provider.strip().lower(),
            norm_inst,
            exchange,
            symbol_token,
            norm_tf,
            (req_from.isoformat() if req_from else (report.first_timestamp_ist or "")),
            (req_to.isoformat() if req_to else (report.last_timestamp_ist or "")),
            report.first_timestamp_ist,
            report.last_timestamp_ist,
            len(rows_to_insert),
            "COMPLETED",
            report.dataset_fingerprint,
            report.model_dump_json(),
            json.dumps([c.model_dump() for c in chunk_records], sort_keys=True),
            retrieved_utc,
        )

        with self._transaction() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO historical_candles (
                    instrument, timeframe, epoch_ms, timestamp_ist,
                    open, high, low, close, volume, is_complete, provider, ingestion_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows_to_insert,
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO historical_ingestion_manifests (
                    ingestion_id, provider, instrument, exchange, symbol_token, timeframe,
                    requested_from_ist, requested_to_ist, actual_from_ist, actual_to_ist,
                    bars_count, status, dataset_fingerprint, integrity_report_json,
                    chunk_records_json, retrieved_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                manifest_row,
            )

        return len(rows_to_insert), report, eff_ingestion_id

    def load_candles(
        self,
        instrument: str,
        timeframe: str,
        *,
        start_time_ist: Optional[datetime] = None,
        end_time_ist: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Loads persisted candles for exact `(instrument, timeframe)` in ascending
        IST order. Never silently falls back to another timeframe.
        """
        norm_inst = normalize_instrument(instrument)
        norm_tf = normalize_timeframe(timeframe)
        start_dt = _ensure_ist(start_time_ist, "start_time_ist")
        end_dt = _ensure_ist(end_time_ist, "end_time_ist")

        query = """
            SELECT timestamp_ist, open, high, low, close, volume, is_complete, provider
            FROM historical_candles
            WHERE instrument = ? AND timeframe = ?
        """
        params: List[Any] = [norm_inst, norm_tf]
        if start_dt is not None:
            query += " AND epoch_ms >= ?"
            params.append(int(round(start_dt.timestamp() * 1000)))
        if end_dt is not None:
            query += " AND epoch_ms <= ?"
            params.append(int(round(end_dt.timestamp() * 1000)))
        query += " ORDER BY epoch_ms ASC"

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()

        columns = ["timestamp", "open", "high", "low", "close", "volume", "is_complete"]
        if not rows:
            empty_df = pd.DataFrame(columns=columns)
            empty_df.attrs.update(
                {
                    "instrument": norm_inst,
                    "timeframe": norm_tf,
                    "provider": "isolated_backtest_store",
                    "dataStatus": "DATA_UNAVAILABLE",
                    "feedStatus": "DATA_UNAVAILABLE",
                    "data_status": "DATA_UNAVAILABLE",
                    "feed_status": "DATA_UNAVAILABLE",
                    "is_mock": False,
                    "is_synthetic": False,
                    "ohlc_repaired": False,
                }
            )
            return empty_df

        parsed_ts = [datetime.fromisoformat(r["timestamp_ist"]).astimezone(IST_ZONE) for r in rows]
        records = [
            {
                "timestamp": parsed_ts[i],
                "open": float(rows[i]["open"]),
                "high": float(rows[i]["high"]),
                "low": float(rows[i]["low"]),
                "close": float(rows[i]["close"]),
                "volume": float(rows[i]["volume"]),
                "is_complete": bool(rows[i]["is_complete"]),
            }
            for i in range(len(rows))
        ]
        providers = sorted({str(r["provider"]) for r in rows})
        df = pd.DataFrame(records, columns=columns)
        fp = compute_dataset_fingerprint(
            df,
            instrument=norm_inst,
            timeframe=norm_tf,
            timestamps_ist=parsed_ts,
        )
        df.attrs.update(
            {
                "instrument": norm_inst,
                "timeframe": norm_tf,
                "provider": providers[0] if len(providers) == 1 else ",".join(providers),
                "dataStatus": "VERIFIED_EOD",
                "feedStatus": "VERIFIED_EOD",
                "data_status": "VERIFIED_EOD",
                "feed_status": "VERIFIED_EOD",
                "is_mock": False,
                "is_synthetic": False,
                "ohlc_repaired": False,
                "dataset_fingerprint": fp,
            }
        )
        return df

    def load_candles_for_replay(
        self,
        instrument: str,
        timeframes: Sequence[str],
        *,
        start_time_ist: Optional[datetime] = None,
        end_time_ist: Optional[datetime] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Loads exact requested timeframes for replay; never substitutes missing timeframes."""
        out: Dict[str, pd.DataFrame] = {}
        for tf in timeframes:
            norm_tf = normalize_timeframe(tf)
            out[norm_tf] = self.load_candles(
                instrument,
                norm_tf,
                start_time_ist=start_time_ist,
                end_time_ist=end_time_ist,
            )
        return out

    def list_ingested_datasets(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT instrument, timeframe, COUNT(*) AS bar_count,
                       MIN(timestamp_ist) AS first_timestamp_ist,
                       MAX(timestamp_ist) AS last_timestamp_ist
                FROM historical_candles
                GROUP BY instrument, timeframe
                ORDER BY instrument, timeframe
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_ingestion_manifests(
        self,
        *,
        instrument: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM historical_ingestion_manifests WHERE 1=1"
        params: List[Any] = []
        if instrument is not None:
            query += " AND instrument = ?"
            params.append(normalize_instrument(instrument))
        if timeframe is not None:
            query += " AND timeframe = ?"
            params.append(normalize_timeframe(timeframe))
        query += " ORDER BY retrieved_at_utc DESC"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            item["integrity_report"] = json.loads(item.pop("integrity_report_json"))
            item["chunks"] = json.loads(item.pop("chunk_records_json"))
            out.append(item)
        return out

    def save_replay_run(self, record: ReplayRunRecord) -> str:
        """Persists a deterministic replay run manifest and points strictly to isolated store."""
        payload_json = record.model_dump_json()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO replay_runs (
                    run_id, instrument, timeframes_json, start_date_ist, end_date_ist,
                    historical_date_range, data_source, dataset_fingerprint, engine_version,
                    configuration_version, calendar_source, calendar_fingerprint,
                    replay_timestamps_json, output_fingerprint, validation_status,
                    run_payload_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.instrument,
                    json.dumps(list(record.timeframes)),
                    record.start_date_ist,
                    record.end_date_ist,
                    record.historical_date_range,
                    record.data_source,
                    record.dataset_fingerprint,
                    record.engine_version,
                    record.configuration_version,
                    record.calendar_source,
                    record.calendar_fingerprint,
                    json.dumps(list(record.replay_timestamps_ist)),
                    record.output_fingerprint,
                    record.validation_status.value,
                    payload_json,
                    record.created_at_utc.astimezone(timezone.utc).isoformat(),
                ),
            )
        return record.run_id

    def get_replay_run(self, run_id: str) -> Optional[ReplayRunRecord]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT run_payload_json FROM replay_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return ReplayRunRecord.model_validate_json(row["run_payload_json"])

    def list_replay_runs(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT run_id, instrument, timeframes_json, historical_date_range,
                       data_source, dataset_fingerprint, engine_version,
                       configuration_version, output_fingerprint, validation_status, created_at_utc
                FROM replay_runs
                ORDER BY created_at_utc DESC
                """
            ).fetchall()
        results: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["timeframes"] = json.loads(d.pop("timeframes_json"))
            results.append(d)
        return results

    def save_simulation_run(self, result: SimulationRunResult) -> str:
        """Persists a Step 4.3 deterministic execution simulation result into isolated storage."""
        payload_json = result.model_dump_json()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO simulation_runs (
                    run_id, status, mode, accounting_unit_mode, monetary_accounting_enabled,
                    provenance_label, is_synthetic_modelled, instrument, timeframe,
                    historical_date_range, dataset_fingerprint, calendar_fingerprint,
                    replay_run_id, simulator_version, cost_model_version, output_fingerprint,
                    points_unit, realized_net_points, total_slippage_points,
                    currency_unit, realized_net_pnl_inr, total_costs_inr,
                    reconciled, run_payload_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.run_id,
                    result.status.value,
                    result.mode.value,
                    result.accounting_unit_mode.value,
                    1 if result.portfolio.monetary_accounting_enabled else 0,
                    result.provenance_label,
                    1 if result.is_synthetic_modelled else 0,
                    result.instrument,
                    result.timeframe,
                    result.historical_date_range,
                    result.dataset_fingerprint,
                    result.calendar_fingerprint,
                    result.replay_run_id,
                    result.simulator_version,
                    result.cost_schedule.cost_model_version,
                    result.output_fingerprint,
                    result.portfolio.points_unit,
                    result.portfolio.realized_net_points,
                    result.portfolio.total_slippage_points,
                    result.portfolio.currency_unit,
                    result.portfolio.realized_net_pnl_inr,
                    result.portfolio.total_costs_inr,
                    1 if result.reconciliation.reconciled else 0,
                    payload_json,
                    result.created_at_utc.astimezone(timezone.utc).isoformat(),
                ),
            )
        return result.run_id

    def get_simulation_run(self, run_id: str) -> Optional[SimulationRunResult]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT run_payload_json FROM simulation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return SimulationRunResult.model_validate_json(row["run_payload_json"])

    def list_simulation_runs(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT run_id, status, mode, accounting_unit_mode,
                       monetary_accounting_enabled, provenance_label, is_synthetic_modelled,
                       instrument, timeframe, historical_date_range, dataset_fingerprint,
                       cost_model_version, output_fingerprint, points_unit,
                       realized_net_points, total_slippage_points, currency_unit,
                       realized_net_pnl_inr, total_costs_inr, reconciled, created_at_utc
                FROM simulation_runs
                ORDER BY created_at_utc DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

