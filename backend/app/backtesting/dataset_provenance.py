"""
AIVOLVE Phase 4 Step 4.6 — Dataset Provenance, Timestamp Normalization & Resumable Checkpoints.

Preserves original provider timestamps and timezone provenance alongside IST
(`Asia/Kolkata`, +05:30) normalization, records immutable dataset/chunk provenance,
and persists resumable chunk checkpoints strictly inside `backend/data/backtest/`.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

from app.backtesting.configuration import (
    DEFAULT_BACKTEST_DB_PATH,
    IST_ZONE,
    assert_isolated_backtest_path,
    normalize_instrument,
    normalize_timeframe,
)
from app.backtesting.trade_lifecycle import deterministic_id


PROVENANCE_VERSION: str = "4.6.0"


@dataclass(frozen=True)
class TimestampNormalizationResult:
    """Preserves original raw timestamp provenance alongside canonical IST normalization."""

    source_timestamp_raw: str
    source_timezone_offset: str
    timestamp_ist_iso: str
    timestamp_utc_iso: str
    epoch_ms: int
    provider: str
    was_timezone_naive: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalize_timestamp_with_provenance(
    raw_ts: Any,
    *,
    provider: str = "angelone",
    assume_naive_tz: str = "Asia/Kolkata",
) -> TimestampNormalizationResult:
    """
    Normalizes an arbitrary provider timestamp to Asia/Kolkata (+05:30) without
    discarding the raw original timestamp string or source timezone offset.
    """
    if raw_ts is None or (isinstance(raw_ts, float) and pd.isna(raw_ts)):
        raise ValueError("Cannot normalize null/NaN timestamp")

    raw_str = str(raw_ts).strip()
    if not raw_str:
        raise ValueError("Cannot normalize empty timestamp string")

    parsed = pd.to_datetime(raw_ts, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Unparseable provider timestamp: {raw_str!r}")

    dt: datetime = parsed.to_pydatetime() if hasattr(parsed, "to_pydatetime") else parsed
    was_naive = dt.tzinfo is None or dt.utcoffset() is None

    if was_naive:
        target_naive_zone = ZoneInfo(assume_naive_tz)
        dt_aware = dt.replace(tzinfo=target_naive_zone)
        source_offset = f"NAIVE_ASSUMED_{assume_naive_tz}"
    else:
        dt_aware = dt
        offset = dt.utcoffset()
        if offset is not None:
            total_minutes = int(offset.total_seconds() // 60)
            sign = "+" if total_minutes >= 0 else "-"
            abs_min = abs(total_minutes)
            source_offset = f"{sign}{abs_min // 60:02d}:{abs_min % 60:02d}"
        else:
            source_offset = str(dt.tzinfo)

    dt_ist = dt_aware.astimezone(IST_ZONE)
    dt_utc = dt_aware.astimezone(timezone.utc)
    epoch_ms = int(round(dt_utc.timestamp() * 1000))

    return TimestampNormalizationResult(
        source_timestamp_raw=raw_str,
        source_timezone_offset=source_offset,
        timestamp_ist_iso=dt_ist.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
        timestamp_utc_iso=dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        epoch_ms=epoch_ms,
        provider=str(provider),
        was_timezone_naive=was_naive,
    )


def normalize_dataframe_timestamps_with_provenance(
    df: pd.DataFrame,
    *,
    timestamp_col: str = "timestamp",
    provider: str = "angelone",
    assume_naive_tz: str = "Asia/Kolkata",
) -> Tuple[pd.DataFrame, List[TimestampNormalizationResult]]:
    """
    Adds `source_timestamp_raw`, `source_timezone_offset`, canonical `timestamp` (IST),
    and `epoch_ms` columns to a DataFrame while returning structured provenance records.
    """
    if df is None or df.empty:
        return pd.DataFrame(), []
    if timestamp_col not in df.columns:
        raise ValueError(f"Timestamp column {timestamp_col!r} missing from DataFrame")

    work = df.copy()
    records: List[TimestampNormalizationResult] = []
    raw_strs: List[str] = []
    offsets: List[str] = []
    ist_timestamps: List[pd.Timestamp] = []
    epochs: List[int] = []

    for val in work[timestamp_col].tolist():
        norm = normalize_timestamp_with_provenance(
            val,
            provider=provider,
            assume_naive_tz=assume_naive_tz,
        )
        records.append(norm)
        raw_strs.append(norm.source_timestamp_raw)
        offsets.append(norm.source_timezone_offset)
        ist_timestamps.append(pd.Timestamp(norm.timestamp_ist_iso))
        epochs.append(norm.epoch_ms)

    work["source_timestamp_raw"] = raw_strs
    work["source_timezone_offset"] = offsets
    work["timestamp"] = ist_timestamps
    work["epoch_ms"] = epochs
    return work, records


@dataclass(frozen=True)
class IngestionCheckpointRecord:
    """Resumable chunk-level state for interrupted or incremental dataset downloads."""

    job_id: str
    provider: str
    instrument: str
    timeframe: str
    chunk_index: int
    chunk_from_ist: str
    chunk_to_ist: str
    status: str  # PENDING | COMPLETED | FAILED | BLOCKED
    bars_downloaded: int
    bars_stored: int
    attempts: int
    last_error: Optional[str]
    updated_at_utc: str
    source_endpoint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChunkProvenanceRecord:
    """Immutable audit record of a single downloaded provider chunk and its timestamp mapping."""

    provenance_chunk_id: str
    job_id: str
    ingestion_id: str
    provider: str
    source_endpoint: str
    instrument: str
    symbol_token: str
    timeframe: str
    chunk_index: int
    chunk_from_ist: str
    chunk_to_ist: str
    raw_timestamp_first: Optional[str]
    raw_timestamp_last: Optional[str]
    raw_timezone_observed: Optional[str]
    normalized_timestamp_first_ist: Optional[str]
    normalized_timestamp_last_ist: Optional[str]
    raw_row_count: int
    valid_row_count: int
    duplicate_row_count: int
    http_status: Optional[int]
    retrieved_at_utc: str
    dataset_fingerprint: Optional[str]
    status: str
    error_detail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetProvenanceRecord:
    """Dataset-level provenance snapshot linking stored candles to verified source ingestion."""

    provenance_id: str
    ingestion_id: str
    job_id: str
    provider: str
    source_endpoint: str
    instrument: str
    symbol_token: str
    timeframe: str
    requested_from_ist: str
    requested_to_ist: str
    actual_from_ist: Optional[str]
    actual_to_ist: Optional[str]
    raw_timestamp_first: Optional[str]
    raw_timestamp_last: Optional[str]
    source_timezone_offsets: Tuple[str, ...]
    row_count: int
    duplicate_count: int
    dataset_fingerprint: Optional[str]
    download_timestamp_utc: str
    incremental_mode: bool = True
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["source_timezone_offsets"] = list(self.source_timezone_offsets)
        payload["notes"] = list(self.notes)
        return payload


class DatasetProvenanceStore:
    """
    Isolated SQLite store managing Step 4.6 provenance records, original timestamp maps,
    chunk resumption checkpoints, and validation snapshots inside `backend/data/backtest/`.
    """

    def __init__(self, db_path: str | Path = DEFAULT_BACKTEST_DB_PATH) -> None:
        resolved = assert_isolated_backtest_path(db_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
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
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS dataset_ingestion_checkpoints (
                    job_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_from_ist TEXT NOT NULL,
                    chunk_to_ist TEXT NOT NULL,
                    status TEXT NOT NULL,
                    bars_downloaded INTEGER NOT NULL DEFAULT 0,
                    bars_stored INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    updated_at_utc TEXT NOT NULL,
                    source_endpoint TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (job_id, chunk_index)
                );

                CREATE INDEX IF NOT EXISTS idx_ckpt_inst_tf
                ON dataset_ingestion_checkpoints (instrument, timeframe, status);

                CREATE TABLE IF NOT EXISTS dataset_chunk_provenance (
                    provenance_chunk_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    ingestion_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    source_endpoint TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    symbol_token TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_from_ist TEXT NOT NULL,
                    chunk_to_ist TEXT NOT NULL,
                    raw_timestamp_first TEXT,
                    raw_timestamp_last TEXT,
                    raw_timezone_observed TEXT,
                    normalized_timestamp_first_ist TEXT,
                    normalized_timestamp_last_ist TEXT,
                    raw_row_count INTEGER NOT NULL,
                    valid_row_count INTEGER NOT NULL,
                    duplicate_row_count INTEGER NOT NULL,
                    http_status INTEGER,
                    retrieved_at_utc TEXT NOT NULL,
                    dataset_fingerprint TEXT,
                    status TEXT NOT NULL,
                    error_detail TEXT
                );

                CREATE TABLE IF NOT EXISTS dataset_provenance_records (
                    provenance_id TEXT PRIMARY KEY,
                    ingestion_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    source_endpoint TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    symbol_token TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    requested_from_ist TEXT NOT NULL,
                    requested_to_ist TEXT NOT NULL,
                    actual_from_ist TEXT,
                    actual_to_ist TEXT,
                    raw_timestamp_first TEXT,
                    raw_timestamp_last TEXT,
                    source_timezone_offsets_json TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    duplicate_count INTEGER NOT NULL,
                    dataset_fingerprint TEXT,
                    download_timestamp_utc TEXT NOT NULL,
                    incremental_mode INTEGER NOT NULL,
                    notes_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_prov_inst_tf
                ON dataset_provenance_records (instrument, timeframe, download_timestamp_utc);

                CREATE TABLE IF NOT EXISTS dataset_source_timestamps (
                    instrument TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    epoch_ms INTEGER NOT NULL,
                    timestamp_ist_iso TEXT NOT NULL,
                    source_timestamp_raw TEXT NOT NULL,
                    source_timezone_offset TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    ingestion_id TEXT NOT NULL,
                    recorded_at_utc TEXT NOT NULL,
                    PRIMARY KEY (instrument, timeframe, epoch_ms)
                );

                CREATE TABLE IF NOT EXISTS dataset_validation_reports (
                    validation_id TEXT PRIMARY KEY,
                    instrument TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    quality_status TEXT NOT NULL,
                    integrity_status TEXT NOT NULL,
                    expected_candles INTEGER NOT NULL,
                    actual_candles INTEGER NOT NULL,
                    missing_candles INTEGER NOT NULL,
                    duplicate_count INTEGER NOT NULL,
                    invalid_candles INTEGER NOT NULL,
                    dataset_fingerprint TEXT,
                    validated_at_utc TEXT NOT NULL,
                    report_json TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def build_job_id(
        *,
        provider: str,
        instrument: str,
        timeframe: str,
        requested_from_ist: str,
        requested_to_ist: str,
    ) -> str:
        canonical_inst = normalize_instrument(instrument)
        canonical_tf = normalize_timeframe(timeframe)
        return deterministic_id(
            "JOB",
            {
                "provider": str(provider).lower(),
                "instrument": canonical_inst,
                "timeframe": canonical_tf,
                "requested_from_ist": requested_from_ist,
                "requested_to_ist": requested_to_ist,
            },
            length=16,
        )

    def upsert_checkpoint(self, record: IngestionCheckpointRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO dataset_ingestion_checkpoints (
                    job_id, provider, instrument, timeframe, chunk_index,
                    chunk_from_ist, chunk_to_ist, status,
                    bars_downloaded, bars_stored, attempts, last_error,
                    updated_at_utc, source_endpoint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, chunk_index) DO UPDATE SET
                    status = excluded.status,
                    bars_downloaded = excluded.bars_downloaded,
                    bars_stored = excluded.bars_stored,
                    attempts = excluded.attempts,
                    last_error = excluded.last_error,
                    updated_at_utc = excluded.updated_at_utc,
                    source_endpoint = excluded.source_endpoint
                """,
                (
                    record.job_id,
                    record.provider,
                    normalize_instrument(record.instrument),
                    normalize_timeframe(record.timeframe),
                    int(record.chunk_index),
                    record.chunk_from_ist,
                    record.chunk_to_ist,
                    record.status,
                    int(record.bars_downloaded),
                    int(record.bars_stored),
                    int(record.attempts),
                    record.last_error,
                    record.updated_at_utc,
                    record.source_endpoint,
                ),
            )

    def get_checkpoints(self, job_id: str) -> List[IngestionCheckpointRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM dataset_ingestion_checkpoints
                WHERE job_id = ?
                ORDER BY chunk_index ASC
                """,
                (job_id,),
            ).fetchall()
        return [
            IngestionCheckpointRecord(
                job_id=r["job_id"],
                provider=r["provider"],
                instrument=r["instrument"],
                timeframe=r["timeframe"],
                chunk_index=int(r["chunk_index"]),
                chunk_from_ist=r["chunk_from_ist"],
                chunk_to_ist=r["chunk_to_ist"],
                status=r["status"],
                bars_downloaded=int(r["bars_downloaded"]),
                bars_stored=int(r["bars_stored"]),
                attempts=int(r["attempts"]),
                last_error=r["last_error"],
                updated_at_utc=r["updated_at_utc"],
                source_endpoint=r["source_endpoint"],
            )
            for r in rows
        ]

    def record_chunk_provenance(self, record: ChunkProvenanceRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO dataset_chunk_provenance (
                    provenance_chunk_id, job_id, ingestion_id, provider, source_endpoint,
                    instrument, symbol_token, timeframe, chunk_index, chunk_from_ist, chunk_to_ist,
                    raw_timestamp_first, raw_timestamp_last, raw_timezone_observed,
                    normalized_timestamp_first_ist, normalized_timestamp_last_ist,
                    raw_row_count, valid_row_count, duplicate_row_count, http_status,
                    retrieved_at_utc, dataset_fingerprint, status, error_detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.provenance_chunk_id,
                    record.job_id,
                    record.ingestion_id,
                    record.provider,
                    record.source_endpoint,
                    normalize_instrument(record.instrument),
                    record.symbol_token,
                    normalize_timeframe(record.timeframe),
                    int(record.chunk_index),
                    record.chunk_from_ist,
                    record.chunk_to_ist,
                    record.raw_timestamp_first,
                    record.raw_timestamp_last,
                    record.raw_timezone_observed,
                    record.normalized_timestamp_first_ist,
                    record.normalized_timestamp_last_ist,
                    int(record.raw_row_count),
                    int(record.valid_row_count),
                    int(record.duplicate_row_count),
                    record.http_status,
                    record.retrieved_at_utc,
                    record.dataset_fingerprint,
                    record.status,
                    record.error_detail,
                ),
            )

    def get_chunk_provenance(
        self,
        *,
        job_id: Optional[str] = None,
        instrument: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> List[ChunkProvenanceRecord]:
        clauses: List[str] = []
        params: List[Any] = []
        if job_id:
            clauses.append("job_id = ?")
            params.append(job_id)
        if instrument:
            clauses.append("instrument = ?")
            params.append(normalize_instrument(instrument))
        if timeframe:
            clauses.append("timeframe = ?")
            params.append(normalize_timeframe(timeframe))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM dataset_chunk_provenance {where_sql} ORDER BY chunk_index ASC, retrieved_at_utc ASC",
                params,
            ).fetchall()
        return [
            ChunkProvenanceRecord(
                provenance_chunk_id=r["provenance_chunk_id"],
                job_id=r["job_id"],
                ingestion_id=r["ingestion_id"],
                provider=r["provider"],
                source_endpoint=r["source_endpoint"],
                instrument=r["instrument"],
                symbol_token=r["symbol_token"],
                timeframe=r["timeframe"],
                chunk_index=int(r["chunk_index"]),
                chunk_from_ist=r["chunk_from_ist"],
                chunk_to_ist=r["chunk_to_ist"],
                raw_timestamp_first=r["raw_timestamp_first"],
                raw_timestamp_last=r["raw_timestamp_last"],
                raw_timezone_observed=r["raw_timezone_observed"],
                normalized_timestamp_first_ist=r["normalized_timestamp_first_ist"],
                normalized_timestamp_last_ist=r["normalized_timestamp_last_ist"],
                raw_row_count=int(r["raw_row_count"]),
                valid_row_count=int(r["valid_row_count"]),
                duplicate_row_count=int(r["duplicate_row_count"]),
                http_status=r["http_status"],
                retrieved_at_utc=r["retrieved_at_utc"],
                dataset_fingerprint=r["dataset_fingerprint"],
                status=r["status"],
                error_detail=r["error_detail"],
            )
            for r in rows
        ]

    def record_source_timestamps(
        self,
        *,
        instrument: str,
        timeframe: str,
        ingestion_id: str,
        normalized_records: Sequence[TimestampNormalizationResult],
    ) -> int:
        if not normalized_records:
            return 0
        canonical_inst = normalize_instrument(instrument)
        canonical_tf = normalize_timeframe(timeframe)
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = [
            (
                canonical_inst,
                canonical_tf,
                int(r.epoch_ms),
                r.timestamp_ist_iso,
                r.source_timestamp_raw,
                r.source_timezone_offset,
                r.provider,
                ingestion_id,
                now_utc,
            )
            for r in normalized_records
        ]
        with self._conn() as conn:
            conn.executemany(
                """
                INSERT INTO dataset_source_timestamps (
                    instrument, timeframe, epoch_ms, timestamp_ist_iso,
                    source_timestamp_raw, source_timezone_offset,
                    provider, ingestion_id, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument, timeframe, epoch_ms) DO UPDATE SET
                    timestamp_ist_iso = excluded.timestamp_ist_iso,
                    source_timestamp_raw = excluded.source_timestamp_raw,
                    source_timezone_offset = excluded.source_timezone_offset,
                    provider = excluded.provider,
                    ingestion_id = excluded.ingestion_id,
                    recorded_at_utc = excluded.recorded_at_utc
                """,
                rows,
            )
        return len(rows)

    def get_source_timestamps(
        self,
        instrument: str,
        timeframe: str,
        *,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        canonical_inst = normalize_instrument(instrument)
        canonical_tf = normalize_timeframe(timeframe)
        sql = """
            SELECT * FROM dataset_source_timestamps
            WHERE instrument = ? AND timeframe = ?
            ORDER BY epoch_ms ASC
        """
        params: List[Any] = [canonical_inst, canonical_tf]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def record_dataset_provenance(self, record: DatasetProvenanceRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO dataset_provenance_records (
                    provenance_id, ingestion_id, job_id, provider, source_endpoint,
                    instrument, symbol_token, timeframe,
                    requested_from_ist, requested_to_ist,
                    actual_from_ist, actual_to_ist,
                    raw_timestamp_first, raw_timestamp_last,
                    source_timezone_offsets_json,
                    row_count, duplicate_count, dataset_fingerprint,
                    download_timestamp_utc, incremental_mode, notes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.provenance_id,
                    record.ingestion_id,
                    record.job_id,
                    record.provider,
                    record.source_endpoint,
                    normalize_instrument(record.instrument),
                    record.symbol_token,
                    normalize_timeframe(record.timeframe),
                    record.requested_from_ist,
                    record.requested_to_ist,
                    record.actual_from_ist,
                    record.actual_to_ist,
                    record.raw_timestamp_first,
                    record.raw_timestamp_last,
                    json.dumps(list(record.source_timezone_offsets)),
                    int(record.row_count),
                    int(record.duplicate_count),
                    record.dataset_fingerprint,
                    record.download_timestamp_utc,
                    1 if record.incremental_mode else 0,
                    json.dumps(list(record.notes)),
                ),
            )

    def get_dataset_provenance(
        self,
        *,
        instrument: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> List[DatasetProvenanceRecord]:
        clauses: List[str] = []
        params: List[Any] = []
        if instrument:
            clauses.append("instrument = ?")
            params.append(normalize_instrument(instrument))
        if timeframe:
            clauses.append("timeframe = ?")
            params.append(normalize_timeframe(timeframe))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM dataset_provenance_records {where_sql} ORDER BY download_timestamp_utc DESC",
                params,
            ).fetchall()
        return [
            DatasetProvenanceRecord(
                provenance_id=r["provenance_id"],
                ingestion_id=r["ingestion_id"],
                job_id=r["job_id"],
                provider=r["provider"],
                source_endpoint=r["source_endpoint"],
                instrument=r["instrument"],
                symbol_token=r["symbol_token"],
                timeframe=r["timeframe"],
                requested_from_ist=r["requested_from_ist"],
                requested_to_ist=r["requested_to_ist"],
                actual_from_ist=r["actual_from_ist"],
                actual_to_ist=r["actual_to_ist"],
                raw_timestamp_first=r["raw_timestamp_first"],
                raw_timestamp_last=r["raw_timestamp_last"],
                source_timezone_offsets=tuple(json.loads(r["source_timezone_offsets_json"])),
                row_count=int(r["row_count"]),
                duplicate_count=int(r["duplicate_count"]),
                dataset_fingerprint=r["dataset_fingerprint"],
                download_timestamp_utc=r["download_timestamp_utc"],
                incremental_mode=bool(r["incremental_mode"]),
                notes=tuple(json.loads(r["notes_json"])),
            )
            for r in rows
        ]

    def save_validation_snapshot(
        self,
        *,
        validation_id: str,
        instrument: str,
        timeframe: str,
        quality_status: str,
        integrity_status: str,
        expected_candles: int,
        actual_candles: int,
        missing_candles: int,
        duplicate_count: int,
        invalid_candles: int,
        dataset_fingerprint: Optional[str],
        validated_at_utc: str,
        report_payload: Dict[str, Any],
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO dataset_validation_reports (
                    validation_id, instrument, timeframe, quality_status, integrity_status,
                    expected_candles, actual_candles, missing_candles, duplicate_count,
                    invalid_candles, dataset_fingerprint, validated_at_utc, report_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    validation_id,
                    normalize_instrument(instrument),
                    normalize_timeframe(timeframe),
                    str(quality_status),
                    str(integrity_status),
                    int(expected_candles),
                    int(actual_candles),
                    int(missing_candles),
                    int(duplicate_count),
                    int(invalid_candles),
                    dataset_fingerprint,
                    validated_at_utc,
                    json.dumps(report_payload, sort_keys=True, default=str),
                ),
            )

