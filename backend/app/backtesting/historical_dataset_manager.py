"""
AIVOLVE Phase 4 Step 4.6 — Historical Dataset Expansion & Resumable Ingestion Manager.

Orchestrates genuine historical OHLCV downloads across `NIFTY 50`, `BANK NIFTY`,
and `FINNIFTY` across all six timeframes (`1m`, `3m`, `5m`, `15m`, `1h`, `1d`) while:
- Enforcing SENSEX governance lockout fail-closed
- Enforcing strict timeframe non-substitution and zero synthetic backfill
- Preserving original raw timestamps and timezone offsets prior to IST normalization
- Respecting provider API limits with configurable pacing + adaptive HTTP 403/429 backoff
- Maintaining resumable chunk checkpoints & preventing duplicate candles in storage
"""

from __future__ import annotations

import asyncio
import time as py_time
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import httpx
import pandas as pd

from app.backtesting.configuration import (
    ANGELONE_INSTRUMENT_METADATA,
    ANGELONE_INTERVAL_MAP,
    ANGELONE_MAX_CHUNK_DAYS,
    BacktestConfiguration,
    IST_ZONE,
    SUPPORTED_INDICES,
    SUPPORTED_TIMEFRAMES,
    TIMEFRAME_DURATION_MINUTES,
    normalize_instrument,
    normalize_timeframe,
    verify_index_governance,
)
from app.backtesting.data_downloader import build_date_chunks
from app.backtesting.data_integrity import compute_candle_close_ist, compute_dataset_fingerprint
from app.backtesting.data_store import HistoricalDataStore
from app.backtesting.dataset_provenance import (
    ChunkProvenanceRecord,
    DatasetProvenanceRecord,
    DatasetProvenanceStore,
    IngestionCheckpointRecord,
    TimestampNormalizationResult,
    normalize_dataframe_timestamps_with_provenance,
)
from app.backtesting.dataset_validation import (
    DatasetQualityStatus,
    DatasetValidationReport,
    DatasetValidator,
)
from app.backtesting.models import CalendarStatus, DownloadStatus
from app.backtesting.multi_year_calendar import MultiYearTradingCalendar
from app.backtesting.trade_lifecycle import deterministic_id


ANGELONE_HISTORICAL_ENDPOINT: str = (
    "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
)


@dataclass(frozen=True)
class DatasetExpansionConfig:
    provider_name: str = "angelone"
    min_request_interval_seconds: float = 12.5
    rate_limit_backoff_seconds: float = 35.0
    max_retries_per_chunk: int = 3
    max_chunk_days_override: Optional[int] = None
    incremental: bool = True
    resume_from_checkpoints: bool = True
    force_refresh: bool = False
    allow_partial_exchange_gaps: bool = True
    store_raw_timestamp_provenance: bool = True


@dataclass(frozen=True)
class RawCandleFetchResult:
    df: pd.DataFrame
    source_endpoint: str
    http_status: Optional[int] = 200
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    is_transient_rate_limit: bool = False


@dataclass(frozen=True)
class DatasetExpansionResult:
    job_id: str
    ingestion_id: str
    provider: str
    instrument: str
    timeframe: str
    requested_from_ist: str
    requested_to_ist: str
    status: DownloadStatus
    quality_status: DatasetQualityStatus
    blocked: bool
    blocked_reason: Optional[str]
    chunks_total: int
    chunks_completed: int
    chunks_skipped_resumed: int
    chunks_skipped_existing: int
    chunks_failed: int
    bars_downloaded: int
    bars_stored: int
    duplicate_rows_prevented: int
    invalid_chunks_rejected: int
    source_timezone_offsets: Tuple[str, ...]
    dataset_fingerprint: Optional[str]
    validation_report: Optional[DatasetValidationReport]
    provenance_record: Optional[DatasetProvenanceRecord]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "ingestion_id": self.ingestion_id,
            "provider": self.provider,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "requested_from_ist": self.requested_from_ist,
            "requested_to_ist": self.requested_to_ist,
            "status": self.status.value,
            "quality_status": self.quality_status.value,
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "chunks_total": self.chunks_total,
            "chunks_completed": self.chunks_completed,
            "chunks_skipped_resumed": self.chunks_skipped_resumed,
            "chunks_skipped_existing": self.chunks_skipped_existing,
            "chunks_failed": self.chunks_failed,
            "bars_downloaded": self.bars_downloaded,
            "bars_stored": self.bars_stored,
            "duplicate_rows_prevented": self.duplicate_rows_prevented,
            "invalid_chunks_rejected": self.invalid_chunks_rejected,
            "source_timezone_offsets": list(self.source_timezone_offsets),
            "dataset_fingerprint": self.dataset_fingerprint,
            "validation_report": self.validation_report.to_dict() if self.validation_report else None,
            "provenance_record": self.provenance_record.to_dict() if self.provenance_record else None,
        }


def _to_ist_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"Requested datetime {dt!r} must be timezone-aware")
    return dt.astimezone(IST_ZONE)


def _sanitized_error(raw: Any) -> str:
    txt = str(raw or "").strip()
    if len(txt) > 200:
        txt = txt[:197] + "..."
    return txt or "Unspecified error"


class AngelOneRawHistoricalClient:
    """
    Lightweight raw SmartAPI historical client reusing `AngelOneMarketDataProvider`
    session authentication while preserving raw verbatim provider timestamp strings
    and unrepaired OHLCV values before normalization/validation.
    """

    def __init__(self, provider: Optional[Any] = None) -> None:
        self._provider = provider
        self._headers: Optional[Dict[str, str]] = None

    async def ensure_authenticated(self) -> Tuple[bool, Optional[str]]:
        if self._provider is None:
            from app.data.providers.angelone_provider import AngelOneMarketDataProvider

            self._provider = AngelOneMarketDataProvider()
        ok = await self._provider._ensure_authenticated()
        if not ok:
            return False, "Angel One authentication failed or credentials unavailable"
        self._headers = self._provider._get_headers()
        return True, None

    async def fetch_chunk(
        self,
        *,
        instrument: str,
        timeframe: str,
        chunk_from_ist: datetime,
        chunk_to_ist: datetime,
    ) -> RawCandleFetchResult:
        canonical_inst = normalize_instrument(instrument)
        canonical_tf = normalize_timeframe(timeframe)
        if canonical_inst not in ANGELONE_INSTRUMENT_METADATA:
            return RawCandleFetchResult(
                df=pd.DataFrame(),
                source_endpoint=ANGELONE_HISTORICAL_ENDPOINT,
                http_status=None,
                error_code="UNSUPPORTED_INSTRUMENT",
                error_message=f"No Angel One token mapping for {canonical_inst}",
            )
        meta = ANGELONE_INSTRUMENT_METADATA[canonical_inst]
        api_interval = ANGELONE_INTERVAL_MAP[canonical_tf]
        if self._headers is None:
            ok, err = await self.ensure_authenticated()
            if not ok:
                return RawCandleFetchResult(
                    df=pd.DataFrame(),
                    source_endpoint=ANGELONE_HISTORICAL_ENDPOINT,
                    http_status=401,
                    error_code="AUTH_FAILED",
                    error_message=err,
                )

        payload = {
            "exchange": meta["exchange"],
            "symboltoken": meta["symbol_token"],
            "interval": api_interval,
            "fromdate": chunk_from_ist.strftime("%Y-%m-%d %H:%M"),
            "todate": chunk_to_ist.strftime("%Y-%m-%d %H:%M"),
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    ANGELONE_HISTORICAL_ENDPOINT,
                    json=payload,
                    headers=self._headers,
                )
        except Exception as exc:
            return RawCandleFetchResult(
                df=pd.DataFrame(),
                source_endpoint=ANGELONE_HISTORICAL_ENDPOINT,
                http_status=None,
                error_code="HTTP_ERROR",
                error_message=_sanitized_error(exc),
                is_transient_rate_limit=False,
            )

        if resp.status_code in (403, 429):
            return RawCandleFetchResult(
                df=pd.DataFrame(),
                source_endpoint=ANGELONE_HISTORICAL_ENDPOINT,
                http_status=resp.status_code,
                error_code=f"HTTP_{resp.status_code}",
                error_message=_sanitized_error(resp.text),
                is_transient_rate_limit=True,
            )

        if resp.status_code != 200:
            return RawCandleFetchResult(
                df=pd.DataFrame(),
                source_endpoint=ANGELONE_HISTORICAL_ENDPOINT,
                http_status=resp.status_code,
                error_code=f"HTTP_{resp.status_code}",
                error_message=_sanitized_error(resp.text),
                is_transient_rate_limit=False,
            )

        body = resp.json()
        err_code = str(body.get("errorcode") or "")
        msg = str(body.get("message") or "")
        if not body.get("status"):
            is_rl = err_code in {"AB1004", "AB1019", "AB1021"} or "rate" in msg.lower()
            return RawCandleFetchResult(
                df=pd.DataFrame(),
                source_endpoint=ANGELONE_HISTORICAL_ENDPOINT,
                http_status=200,
                error_code=err_code or "API_ERROR",
                error_message=_sanitized_error(msg),
                is_transient_rate_limit=is_rl,
            )

        rows = body.get("data") or []
        if not rows:
            df_empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
            df_empty.attrs = {
                "provider": "angelone",
                "timeframe": canonical_tf,
                "is_mock": False,
                "synthetic": False,
                "ohlc_repaired": False,
                "dataStatus": "EMPTY",
            }
            return RawCandleFetchResult(
                df=df_empty,
                source_endpoint=ANGELONE_HISTORICAL_ENDPOINT,
                http_status=200,
            )

        raw_df = pd.DataFrame(
            rows,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        raw_df.attrs = {
            "provider": "angelone",
            "timeframe": canonical_tf,
            "instrument": canonical_inst,
            "symbol_token": meta["symbol_token"],
            "exchange": meta["exchange"],
            "is_mock": False,
            "synthetic": False,
            "is_synthetic": False,
            "ohlc_repaired": False,
            "dataStatus": "LIVE",
            "feedStatus": "VERIFIED_LIVE",
        }
        return RawCandleFetchResult(
            df=raw_df,
            source_endpoint=ANGELONE_HISTORICAL_ENDPOINT,
            http_status=200,
        )


class HistoricalDatasetManager:
    """
    Incremental, resumable, rate-limit-aware historical market data ingestion engine
    writing strictly into isolated `backend/data/backtest/`.
    """

    def __init__(
        self,
        *,
        data_store: Optional[HistoricalDataStore] = None,
        provenance_store: Optional[DatasetProvenanceStore] = None,
        calendar: Optional[MultiYearTradingCalendar] = None,
        validator: Optional[DatasetValidator] = None,
        config: Optional[BacktestConfiguration] = None,
        expansion_config: Optional[DatasetExpansionConfig] = None,
        provider: Optional[Any] = None,
        raw_fetcher: Optional[Any] = None,
        sleep_fn: Optional[Callable[[float], Any]] = None,
    ) -> None:
        self.config = config or BacktestConfiguration()
        self.exp_config = expansion_config or DatasetExpansionConfig()
        self.data_store = data_store or HistoricalDataStore(config=self.config)
        self.provenance_store = provenance_store or DatasetProvenanceStore(
            db_path=self.data_store.db_path
        )
        self.calendar = calendar or MultiYearTradingCalendar()
        self.validator = validator or DatasetValidator(
            calendar_adapter=self.calendar,
            config=self.config,
        )
        self._provider = provider
        self._raw_fetcher = raw_fetcher
        self._sleep_fn = sleep_fn
        self._last_request_monotonic: Optional[float] = None

    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self._sleep_fn is not None:
            res = self._sleep_fn(seconds)
            if asyncio.iscoroutine(res):
                await res
            return
        await asyncio.sleep(seconds)

    async def _pace_request(self) -> None:
        delay = float(self.exp_config.min_request_interval_seconds)
        if delay <= 0:
            return
        now = py_time.monotonic()
        if self._last_request_monotonic is not None:
            elapsed = now - self._last_request_monotonic
            if elapsed < delay:
                await self._sleep(delay - elapsed)
        self._last_request_monotonic = py_time.monotonic()

    async def _invoke_fetcher(
        self,
        *,
        instrument: str,
        timeframe: str,
        chunk_from_ist: datetime,
        chunk_to_ist: datetime,
    ) -> RawCandleFetchResult:
        # Option 1: Custom injected fetcher callable (e.g. for deterministic unit tests)
        if self._raw_fetcher is not None:
            res = self._raw_fetcher(
                instrument=instrument,
                timeframe=timeframe,
                from_time=chunk_from_ist,
                to_time=chunk_to_ist,
            )
            if asyncio.iscoroutine(res):
                res = await res
            if isinstance(res, RawCandleFetchResult):
                return res
            if isinstance(res, pd.DataFrame):
                return RawCandleFetchResult(
                    df=res,
                    source_endpoint="CUSTOM_RAW_FETCHER",
                    http_status=200,
                )
            raise TypeError(f"Unsupported raw_fetcher return type: {type(res).__name__}")

        # Option 2: Injected Step 4.2/MarketDataProvider adapter (async/sync get_historical_candles)
        if self._provider is not None and not isinstance(self._provider, AngelOneRawHistoricalClient):
            meta = ANGELONE_INSTRUMENT_METADATA.get(instrument, {})
            if getattr(self._provider, "is_mock", False):
                df_mock = pd.DataFrame()
                df_mock.attrs = {"is_mock": True, "provider": "mock"}
                return RawCandleFetchResult(
                    df=df_mock,
                    source_endpoint="MOCK_PROVIDER",
                    http_status=200,
                )
            maybe_coro = self._provider.get_historical_candles(
                symbol=instrument,
                interval=timeframe,
                from_date=chunk_from_ist,
                to_date=chunk_to_ist,
            )
            df = await maybe_coro if asyncio.iscoroutine(maybe_coro) else maybe_coro
            attrs = getattr(df, "attrs", {}) or {}
            err_msg = attrs.get("degraded_reason") or attrs.get("error")
            is_rl = bool(
                err_msg
                and any(
                    tok in str(err_msg).lower()
                    for tok in ("403", "429", "rate", "exceeding")
                )
            )
            return RawCandleFetchResult(
                df=df if df is not None else pd.DataFrame(),
                source_endpoint=f"provider://{attrs.get('provider', self.exp_config.provider_name)}",
                http_status=403 if is_rl else 200,
                error_code=attrs.get("errorcode"),
                error_message=str(err_msg) if err_msg else None,
                is_transient_rate_limit=is_rl,
            )

        # Option 3: Default raw Angel One SmartAPI HTTP client
        if self._provider is None:
            self._provider = AngelOneRawHistoricalClient()
        return await self._provider.fetch_chunk(
            instrument=instrument,
            timeframe=timeframe,
            chunk_from_ist=chunk_from_ist,
            chunk_to_ist=chunk_to_ist,
        )

    def _chunk_already_covered_in_store(
        self,
        *,
        existing_epochs: Set[int],
        timeframe: str,
        chunk_from_ist: datetime,
        chunk_to_ist: datetime,
    ) -> bool:
        if not existing_epochs:
            return False
        opens_by_day = self.calendar.expected_opens_by_date(
            timeframe, chunk_from_ist, chunk_to_ist
        )
        expected_epochs: List[int] = []
        for opens in opens_by_day.values():
            for dt_open in opens:
                expected_epochs.append(int(round(dt_open.timestamp() * 1000)))
        if not expected_epochs:
            return True
        return all(ep in existing_epochs for ep in expected_epochs)

    async def expand_dataset(
        self,
        *,
        instrument: str,
        timeframe: str,
        from_time: datetime,
        to_time: datetime,
        as_of_time: Optional[datetime] = None,
    ) -> DatasetExpansionResult:
        canonical_inst = normalize_instrument(instrument)
        canonical_tf = normalize_timeframe(timeframe)
        from_ist = _to_ist_dt(from_time)
        to_ist = _to_ist_dt(to_time)
        if from_ist >= to_ist:
            raise ValueError("from_time must be strictly earlier than to_time")
        effective_as_of = _to_ist_dt(as_of_time) if as_of_time is not None else to_ist

        req_from_iso = from_ist.strftime("%Y-%m-%dT%H:%M:%S+05:30")
        req_to_iso = to_ist.strftime("%Y-%m-%dT%H:%M:%S+05:30")
        job_id = self.provenance_store.build_job_id(
            provider=self.exp_config.provider_name,
            instrument=canonical_inst,
            timeframe=canonical_tf,
            requested_from_ist=req_from_iso,
            requested_to_ist=req_to_iso,
        )
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ingestion_id = deterministic_id(
            "ING46",
            {
                "job_id": job_id,
                "ts": now_utc,
                "inst": canonical_inst,
                "tf": canonical_tf,
            },
            length=16,
        )

        # 1. Governance Lock Check (SENSEX fails closed)
        gov_ok, _gov_status, gov_info = verify_index_governance(
            canonical_inst,
            sensex_governance_approved=self.config.sensex_governance_approved,
            governance_db_path=self.config.governance_ledger_path,
        )
        if not gov_ok:
            gov_reason = str(gov_info.get("reason") or _gov_status or "GOVERNANCE_LOCKOUT")
            return DatasetExpansionResult(
                job_id=job_id,
                ingestion_id=ingestion_id,
                provider=self.exp_config.provider_name,
                instrument=canonical_inst,
                timeframe=canonical_tf,
                requested_from_ist=req_from_iso,
                requested_to_ist=req_to_iso,
                status=DownloadStatus.BLOCKED,
                quality_status=DatasetQualityStatus.UNAVAILABLE,
                blocked=True,
                blocked_reason=gov_reason,
                chunks_total=0,
                chunks_completed=0,
                chunks_skipped_resumed=0,
                chunks_skipped_existing=0,
                chunks_failed=0,
                bars_downloaded=0,
                bars_stored=0,
                duplicate_rows_prevented=0,
                invalid_chunks_rejected=0,
                source_timezone_offsets=(),
                dataset_fingerprint=None,
                validation_report=None,
                provenance_record=None,
            )

        # 2. Provider validation (strictly reject mock/unverified provider names)
        prov_lower = str(self.exp_config.provider_name).strip().lower()
        if prov_lower in {"mock", "synthetic"}:
            return DatasetExpansionResult(
                job_id=job_id,
                ingestion_id=ingestion_id,
                provider=self.exp_config.provider_name,
                instrument=canonical_inst,
                timeframe=canonical_tf,
                requested_from_ist=req_from_iso,
                requested_to_ist=req_to_iso,
                status=DownloadStatus.FAILED_INTEGRITY,
                quality_status=DatasetQualityStatus.UNAVAILABLE,
                blocked=True,
                blocked_reason="Synthetic/Mock providers are permanently blocked from verified backtesting datasets.",
                chunks_total=0,
                chunks_completed=0,
                chunks_skipped_resumed=0,
                chunks_skipped_existing=0,
                chunks_failed=0,
                bars_downloaded=0,
                bars_stored=0,
                duplicate_rows_prevented=0,
                invalid_chunks_rejected=0,
                source_timezone_offsets=(),
                dataset_fingerprint=None,
                validation_report=None,
                provenance_record=None,
            )

        # 3. Calendar fail-closed validation across entire requested span
        try:
            _ = self.calendar.expected_opens_by_date(canonical_tf, from_ist, to_ist)
        except Exception as exc:
            return DatasetExpansionResult(
                job_id=job_id,
                ingestion_id=ingestion_id,
                provider=self.exp_config.provider_name,
                instrument=canonical_inst,
                timeframe=canonical_tf,
                requested_from_ist=req_from_iso,
                requested_to_ist=req_to_iso,
                status=DownloadStatus.BLOCKED,
                quality_status=DatasetQualityStatus.UNAVAILABLE,
                blocked=True,
                blocked_reason=str(exc),
                chunks_total=0,
                chunks_completed=0,
                chunks_skipped_resumed=0,
                chunks_skipped_existing=0,
                chunks_failed=0,
                bars_downloaded=0,
                bars_stored=0,
                duplicate_rows_prevented=0,
                invalid_chunks_rejected=0,
                source_timezone_offsets=(),
                dataset_fingerprint=None,
                validation_report=None,
                provenance_record=None,
            )

        # 4. Chunk plan & checkpoint loading
        chunks = build_date_chunks(
            from_ist,
            to_ist,
            timeframe=canonical_tf,
            calendar_adapter=self.calendar,
            max_chunk_days_override=self.exp_config.max_chunk_days_override,
        )
        prior_checkpoints = {
            c.chunk_index: c for c in self.provenance_store.get_checkpoints(job_id)
        }
        existing_df = self.data_store.load_candles(canonical_inst, canonical_tf)
        existing_epochs: Set[int] = set()
        if existing_df is not None and not existing_df.empty:
            if "epoch_ms" in existing_df.columns:
                existing_epochs = {int(v) for v in existing_df["epoch_ms"].tolist()}
            elif "timestamp" in existing_df.columns:
                existing_epochs = {
                    int(round(dt.timestamp() * 1000))
                    for dt in (pd.Timestamp(v).to_pydatetime() for v in existing_df["timestamp"].tolist())
                }

        meta = ANGELONE_INSTRUMENT_METADATA.get(
            canonical_inst, {"exchange": "NSE", "symbol_token": ""}
        )

        chunks_completed = 0
        chunks_skipped_resumed = 0
        chunks_skipped_existing = 0
        chunks_failed = 0
        bars_downloaded = 0
        bars_stored = 0
        duplicate_rows_prevented = 0
        invalid_chunks_rejected = 0
        observed_offsets: Set[str] = set()
        all_raw_first: Optional[str] = None
        all_raw_last: Optional[str] = None
        last_error_reason: Optional[str] = None
        source_endpoint_used = ANGELONE_HISTORICAL_ENDPOINT

        for idx, (c_from, c_to) in enumerate(chunks):
            c_from_iso = c_from.strftime("%Y-%m-%dT%H:%M:%S+05:30")
            c_to_iso = c_to.strftime("%Y-%m-%dT%H:%M:%S+05:30")
            existing_ckpt = prior_checkpoints.get(idx)

            # Skip completed checkpoints on resume
            if (
                self.exp_config.resume_from_checkpoints
                and not self.exp_config.force_refresh
                and existing_ckpt is not None
                and existing_ckpt.status == "COMPLETED"
            ):
                chunks_skipped_resumed += 1
                chunks_completed += 1
                continue

            # Skip chunks whose calendar expected trading bars are 0 (pure holiday/weekend slice)
            chunk_expected_map = self.calendar.expected_opens_by_date(canonical_tf, c_from, c_to)
            chunk_expected_total = sum(len(v) for v in chunk_expected_map.values())
            if chunk_expected_total == 0:
                self.provenance_store.upsert_checkpoint(
                    IngestionCheckpointRecord(
                        job_id=job_id,
                        provider=self.exp_config.provider_name,
                        instrument=canonical_inst,
                        timeframe=canonical_tf,
                        chunk_index=idx,
                        chunk_from_ist=c_from_iso,
                        chunk_to_ist=c_to_iso,
                        status="COMPLETED",
                        bars_downloaded=0,
                        bars_stored=0,
                        attempts=(existing_ckpt.attempts if existing_ckpt else 0),
                        last_error=None,
                        updated_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        source_endpoint="CALENDAR_NON_TRADING_SLICE",
                    )
                )
                chunks_completed += 1
                continue

            # Skip chunks already completely stored in DB when incremental=True
            if (
                self.exp_config.incremental
                and not self.exp_config.force_refresh
                and self._chunk_already_covered_in_store(
                    existing_epochs=existing_epochs,
                    timeframe=canonical_tf,
                    chunk_from_ist=c_from,
                    chunk_to_ist=c_to,
                )
            ):
                self.provenance_store.upsert_checkpoint(
                    IngestionCheckpointRecord(
                        job_id=job_id,
                        provider=self.exp_config.provider_name,
                        instrument=canonical_inst,
                        timeframe=canonical_tf,
                        chunk_index=idx,
                        chunk_from_ist=c_from_iso,
                        chunk_to_ist=c_to_iso,
                        status="COMPLETED",
                        bars_downloaded=0,
                        bars_stored=0,
                        attempts=(existing_ckpt.attempts if existing_ckpt else 0),
                        last_error=None,
                        updated_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        source_endpoint="INCREMENTAL_ALREADY_COVERED",
                    )
                )
                chunks_skipped_existing += 1
                chunks_completed += 1
                continue

            # Fetch with pacing and adaptive rate-limit retry
            attempts = (existing_ckpt.attempts if existing_ckpt else 0)
            fetch_res: Optional[RawCandleFetchResult] = None
            for retry in range(self.exp_config.max_retries_per_chunk + 1):
                attempts += 1
                await self._pace_request()
                fetch_res = await self._invoke_fetcher(
                    instrument=canonical_inst,
                    timeframe=canonical_tf,
                    chunk_from_ist=c_from,
                    chunk_to_ist=c_to,
                )
                source_endpoint_used = fetch_res.source_endpoint
                if fetch_res.http_status == 200 and not fetch_res.error_message:
                    break
                if fetch_res.is_transient_rate_limit and retry < self.exp_config.max_retries_per_chunk:
                    wait_s = float(self.exp_config.rate_limit_backoff_seconds) * (retry + 1)
                    await self._sleep(wait_s)
                    self._last_request_monotonic = None
                    continue
                break

            assert fetch_res is not None
            chunk_now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Transport / rate-limit failure
            if fetch_res.http_status != 200 or fetch_res.error_message:
                chunks_failed += 1
                last_error_reason = fetch_res.error_message or f"HTTP {fetch_res.http_status}"
                self.provenance_store.upsert_checkpoint(
                    IngestionCheckpointRecord(
                        job_id=job_id,
                        provider=self.exp_config.provider_name,
                        instrument=canonical_inst,
                        timeframe=canonical_tf,
                        chunk_index=idx,
                        chunk_from_ist=c_from_iso,
                        chunk_to_ist=c_to_iso,
                        status="FAILED",
                        bars_downloaded=0,
                        bars_stored=0,
                        attempts=attempts,
                        last_error=last_error_reason,
                        updated_at_utc=chunk_now_utc,
                        source_endpoint=fetch_res.source_endpoint,
                    )
                )
                continue

            raw_df = fetch_res.df
            attrs = getattr(raw_df, "attrs", {}) or {}
            if (
                attrs.get("is_mock") is True
                or attrs.get("synthetic") is True
                or attrs.get("is_synthetic") is True
                or attrs.get("ohlc_repaired") is True
                or str(attrs.get("provider", "")).lower() == "mock"
            ):
                invalid_chunks_rejected += 1
                chunks_failed += 1
                last_error_reason = "Synthetic/mock or repaired chunk rejected by integrity gate"
                self.provenance_store.upsert_checkpoint(
                    IngestionCheckpointRecord(
                        job_id=job_id,
                        provider=self.exp_config.provider_name,
                        instrument=canonical_inst,
                        timeframe=canonical_tf,
                        chunk_index=idx,
                        chunk_from_ist=c_from_iso,
                        chunk_to_ist=c_to_iso,
                        status="BLOCKED",
                        bars_downloaded=len(raw_df) if raw_df is not None else 0,
                        bars_stored=0,
                        attempts=attempts,
                        last_error=last_error_reason,
                        updated_at_utc=chunk_now_utc,
                        source_endpoint=fetch_res.source_endpoint,
                    )
                )
                continue

            if attrs.get("timeframe") is not None:
                try:
                    if normalize_timeframe(str(attrs["timeframe"])) != canonical_tf:
                        raise ValueError("mismatch")
                except ValueError:
                    invalid_chunks_rejected += 1
                    chunks_failed += 1
                    last_error_reason = (
                        f"Timeframe mismatch in chunk: expected {canonical_tf}, got {attrs.get('timeframe')}"
                    )
                    self.provenance_store.upsert_checkpoint(
                        IngestionCheckpointRecord(
                            job_id=job_id,
                            provider=self.exp_config.provider_name,
                            instrument=canonical_inst,
                            timeframe=canonical_tf,
                            chunk_index=idx,
                            chunk_from_ist=c_from_iso,
                            chunk_to_ist=c_to_iso,
                            status="BLOCKED",
                            bars_downloaded=len(raw_df) if raw_df is not None else 0,
                            bars_stored=0,
                            attempts=attempts,
                            last_error=last_error_reason,
                            updated_at_utc=chunk_now_utc,
                            source_endpoint=fetch_res.source_endpoint,
                        )
                    )
                    continue

            if raw_df is None or raw_df.empty:
                self.provenance_store.upsert_checkpoint(
                    IngestionCheckpointRecord(
                        job_id=job_id,
                        provider=self.exp_config.provider_name,
                        instrument=canonical_inst,
                        timeframe=canonical_tf,
                        chunk_index=idx,
                        chunk_from_ist=c_from_iso,
                        chunk_to_ist=c_to_iso,
                        status="COMPLETED",
                        bars_downloaded=0,
                        bars_stored=0,
                        attempts=attempts,
                        last_error="Provider returned 0 bars for chunk",
                        updated_at_utc=chunk_now_utc,
                        source_endpoint=fetch_res.source_endpoint,
                    )
                )
                chunks_completed += 1
                continue

            bars_downloaded += len(raw_df)

            # 5. Preserve original timestamps while normalizing to IST (+05:30)
            try:
                norm_df, ts_records = normalize_dataframe_timestamps_with_provenance(
                    raw_df,
                    timestamp_col="timestamp",
                    provider=self.exp_config.provider_name,
                )
            except Exception as exc:
                invalid_chunks_rejected += 1
                chunks_failed += 1
                last_error_reason = f"Timestamp normalization failed: {exc}"
                self.provenance_store.upsert_checkpoint(
                    IngestionCheckpointRecord(
                        job_id=job_id,
                        provider=self.exp_config.provider_name,
                        instrument=canonical_inst,
                        timeframe=canonical_tf,
                        chunk_index=idx,
                        chunk_from_ist=c_from_iso,
                        chunk_to_ist=c_to_iso,
                        status="BLOCKED",
                        bars_downloaded=len(raw_df),
                        bars_stored=0,
                        attempts=attempts,
                        last_error=last_error_reason,
                        updated_at_utc=chunk_now_utc,
                        source_endpoint=fetch_res.source_endpoint,
                    )
                )
                continue

            for tr in ts_records:
                observed_offsets.add(tr.source_timezone_offset)
            if ts_records:
                if all_raw_first is None:
                    all_raw_first = ts_records[0].source_timestamp_raw
                all_raw_last = ts_records[-1].source_timestamp_raw

            # Filter out forming/uncompleted candles strictly against effective_as_of
            completed_flags: List[bool] = []
            for dt_val in norm_df["timestamp"].tolist():
                dt_ist = dt_val.to_pydatetime().astimezone(IST_ZONE)
                wins = self.calendar.get_session_windows(dt_ist.date())
                close_t = wins[-1].close_time if wins else dt_time(15, 30)
                bar_close = compute_candle_close_ist(dt_ist, canonical_tf, close_t)
                completed_flags.append(bar_close <= effective_as_of)

            norm_df = norm_df.loc[completed_flags].reset_index(drop=True)
            ts_records = [r for r, keep in zip(ts_records, completed_flags) if keep]

            if norm_df.empty:
                chunks_completed += 1
                self.provenance_store.upsert_checkpoint(
                    IngestionCheckpointRecord(
                        job_id=job_id,
                        provider=self.exp_config.provider_name,
                        instrument=canonical_inst,
                        timeframe=canonical_tf,
                        chunk_index=idx,
                        chunk_from_ist=c_from_iso,
                        chunk_to_ist=c_to_iso,
                        status="COMPLETED",
                        bars_downloaded=len(raw_df),
                        bars_stored=0,
                        attempts=attempts,
                        last_error="Only forming bars excluded as of cutoff",
                        updated_at_utc=chunk_now_utc,
                        source_endpoint=fetch_res.source_endpoint,
                    )
                )
                continue

            # Detect intra-chunk duplicates: reject contradictory duplicates, prevent benign overlapping boundary duplicates
            chunk_dup_mask = norm_df.duplicated(subset=["epoch_ms"], keep=False)
            if chunk_dup_mask.any():
                dups_df = norm_df.loc[chunk_dup_mask]
                conflicting = False
                for _, grp in dups_df.groupby("epoch_ms"):
                    if len(grp[["open", "high", "low", "close", "volume"]].drop_duplicates()) > 1:
                        conflicting = True
                        break
                if conflicting:
                    invalid_chunks_rejected += 1
                    chunks_failed += 1
                    last_error_reason = "Conflicting OHLCV duplicate timestamps inside chunk rejected"
                    self.provenance_store.upsert_checkpoint(
                        IngestionCheckpointRecord(
                            job_id=job_id,
                            provider=self.exp_config.provider_name,
                            instrument=canonical_inst,
                            timeframe=canonical_tf,
                            chunk_index=idx,
                            chunk_from_ist=c_from_iso,
                            chunk_to_ist=c_to_iso,
                            status="BLOCKED",
                            bars_downloaded=len(raw_df),
                            bars_stored=0,
                            attempts=attempts,
                            last_error=last_error_reason,
                            updated_at_utc=chunk_now_utc,
                            source_endpoint=fetch_res.source_endpoint,
                        )
                    )
                    continue
                before_n = len(norm_df)
                keep_idx = ~norm_df.duplicated(subset=["epoch_ms"], keep="first")
                norm_df = norm_df.loc[keep_idx].reset_index(drop=True)
                ts_records = [r for r, k in zip(ts_records, keep_idx.tolist()) if k]
                duplicate_rows_prevented += before_n - len(norm_df)

            # Check overlap against already-stored DB epochs (prevent duplicate inserts & track prevented count)
            overlap_count = sum(1 for ep in norm_df["epoch_ms"].tolist() if int(ep) in existing_epochs)
            duplicate_rows_prevented += overlap_count

            # Sort chronologically cleanly before validation & persistence
            norm_df = norm_df.sort_values("epoch_ms").reset_index(drop=True)
            norm_df["is_complete"] = True
            norm_df.attrs = {
                "provider": self.exp_config.provider_name,
                "timeframe": canonical_tf,
                "instrument": canonical_inst,
                "is_mock": False,
                "synthetic": False,
                "is_synthetic": False,
                "ohlc_repaired": False,
                "dataStatus": "VERIFIED_EOD",
                "feedStatus": "VERIFIED_EOD",
            }

            # 6. Validate intrinsic quality before touching SQLite storage
            chunk_val = self.validator.validate_dataset(
                norm_df,
                instrument=canonical_inst,
                timeframe=canonical_tf,
                expected_from_ist=c_from,
                expected_to_ist=min(c_to, effective_as_of),
                require_all_completed=True,
                check_missing_intervals=not self.exp_config.allow_partial_exchange_gaps,
                as_of_time=effective_as_of,
            )
            if chunk_val.quality_status == DatasetQualityStatus.DEGRADED or (
                not self.exp_config.allow_partial_exchange_gaps
                and chunk_val.quality_status != DatasetQualityStatus.VERIFIED
            ):
                invalid_chunks_rejected += 1
                chunks_failed += 1
                last_error_reason = (
                    chunk_val.issues[0].message if chunk_val.issues else "Chunk failed integrity audit"
                )
                self.provenance_store.upsert_checkpoint(
                    IngestionCheckpointRecord(
                        job_id=job_id,
                        provider=self.exp_config.provider_name,
                        instrument=canonical_inst,
                        timeframe=canonical_tf,
                        chunk_index=idx,
                        chunk_from_ist=c_from_iso,
                        chunk_to_ist=c_to_iso,
                        status="BLOCKED",
                        bars_downloaded=len(raw_df),
                        bars_stored=0,
                        attempts=attempts,
                        last_error=last_error_reason,
                        updated_at_utc=chunk_now_utc,
                        source_endpoint=fetch_res.source_endpoint,
                    )
                )
                self.provenance_store.record_chunk_provenance(
                    ChunkProvenanceRecord(
                        provenance_chunk_id=deterministic_id(
                            "CKP",
                            {"job": job_id, "idx": idx, "ts": chunk_now_utc},
                            length=16,
                        ),
                        job_id=job_id,
                        ingestion_id=ingestion_id,
                        provider=self.exp_config.provider_name,
                        source_endpoint=fetch_res.source_endpoint,
                        instrument=canonical_inst,
                        symbol_token=meta.get("symbol_token", ""),
                        timeframe=canonical_tf,
                        chunk_index=idx,
                        chunk_from_ist=c_from_iso,
                        chunk_to_ist=c_to_iso,
                        raw_timestamp_first=ts_records[0].source_timestamp_raw if ts_records else None,
                        raw_timestamp_last=ts_records[-1].source_timestamp_raw if ts_records else None,
                        raw_timezone_observed=",".join(sorted(observed_offsets)) if observed_offsets else None,
                        normalized_timestamp_first_ist=ts_records[0].timestamp_ist_iso if ts_records else None,
                        normalized_timestamp_last_ist=ts_records[-1].timestamp_ist_iso if ts_records else None,
                        raw_row_count=len(raw_df),
                        valid_row_count=0,
                        duplicate_row_count=overlap_count,
                        http_status=fetch_res.http_status,
                        retrieved_at_utc=chunk_now_utc,
                        dataset_fingerprint=chunk_val.dataset_fingerprint,
                        status="REJECTED_DEGRADED",
                        error_detail=last_error_reason,
                    )
                )
                continue

            # 7. Persist clean chunk candles into HistoricalDataStore + source timestamp provenance
            store_auditor = (
                self.validator
                if not self.exp_config.allow_partial_exchange_gaps
                else DatasetValidator(
                    calendar_adapter=self.calendar,
                    config=self.config.model_copy(update={"strict_missing_intervals": False}),
                    auditor=self.validator.auditor,
                )
            )
            stored_n, _, chunk_fp = self.data_store.save_candles(
                norm_df,
                instrument=canonical_inst,
                timeframe=canonical_tf,
                provider=self.exp_config.provider_name,
                exchange=meta.get("exchange", "NSE"),
                symbol_token=meta.get("symbol_token", ""),
                calendar_adapter=self.calendar,
                auditor=store_auditor,
                requested_from_ist=c_from,
                requested_to_ist=min(c_to, effective_as_of),
                ingestion_id=f"{ingestion_id}-{idx:03d}",
                strict_missing_intervals=not self.exp_config.allow_partial_exchange_gaps,
            )
            bars_stored += stored_n
            existing_epochs.update(int(v) for v in norm_df["epoch_ms"].tolist())

            if self.exp_config.store_raw_timestamp_provenance and ts_records:
                self.provenance_store.record_source_timestamps(
                    instrument=canonical_inst,
                    timeframe=canonical_tf,
                    ingestion_id=ingestion_id,
                    normalized_records=ts_records,
                )

            self.provenance_store.record_chunk_provenance(
                ChunkProvenanceRecord(
                    provenance_chunk_id=deterministic_id(
                        "CKP",
                        {"job": job_id, "idx": idx, "fp": chunk_fp},
                        length=16,
                    ),
                    job_id=job_id,
                    ingestion_id=ingestion_id,
                    provider=self.exp_config.provider_name,
                    source_endpoint=fetch_res.source_endpoint,
                    instrument=canonical_inst,
                    symbol_token=meta.get("symbol_token", ""),
                    timeframe=canonical_tf,
                    chunk_index=idx,
                    chunk_from_ist=c_from_iso,
                    chunk_to_ist=c_to_iso,
                    raw_timestamp_first=ts_records[0].source_timestamp_raw if ts_records else None,
                    raw_timestamp_last=ts_records[-1].source_timestamp_raw if ts_records else None,
                    raw_timezone_observed=",".join(sorted({r.source_timezone_offset for r in ts_records})) if ts_records else None,
                    normalized_timestamp_first_ist=ts_records[0].timestamp_ist_iso if ts_records else None,
                    normalized_timestamp_last_ist=ts_records[-1].timestamp_ist_iso if ts_records else None,
                    raw_row_count=len(raw_df),
                    valid_row_count=len(norm_df),
                    duplicate_row_count=overlap_count,
                    http_status=fetch_res.http_status,
                    retrieved_at_utc=chunk_now_utc,
                    dataset_fingerprint=chunk_fp,
                    status="STORED",
                )
            )
            self.provenance_store.upsert_checkpoint(
                IngestionCheckpointRecord(
                    job_id=job_id,
                    provider=self.exp_config.provider_name,
                    instrument=canonical_inst,
                    timeframe=canonical_tf,
                    chunk_index=idx,
                    chunk_from_ist=c_from_iso,
                    chunk_to_ist=c_to_iso,
                    status="COMPLETED",
                    bars_downloaded=len(raw_df),
                    bars_stored=stored_n,
                    attempts=attempts,
                    last_error=None,
                    updated_at_utc=chunk_now_utc,
                    source_endpoint=fetch_res.source_endpoint,
                )
            )
            chunks_completed += 1

        # 8. Post-ingestion full validation of persisted candles in requested range
        merged_df = self.data_store.load_candles(
            canonical_inst, canonical_tf, start_time_ist=from_ist, end_time_ist=effective_as_of
        )
        full_val = self.validator.validate_dataset(
            merged_df,
            instrument=canonical_inst,
            timeframe=canonical_tf,
            expected_from_ist=from_ist,
            expected_to_ist=effective_as_of,
            require_all_completed=True,
            check_missing_intervals=True,
            as_of_time=effective_as_of,
        )
        completed_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.provenance_store.save_validation_snapshot(
            validation_id=full_val.validation_id,
            instrument=canonical_inst,
            timeframe=canonical_tf,
            quality_status=full_val.quality_status.value,
            integrity_status=full_val.integrity_status.value,
            expected_candles=full_val.expected_candles,
            actual_candles=full_val.actual_candles,
            missing_candles=full_val.missing_candles,
            duplicate_count=full_val.duplicate_count,
            invalid_candles=full_val.invalid_candles,
            dataset_fingerprint=full_val.dataset_fingerprint,
            validated_at_utc=completed_utc,
            report_payload=full_val.to_dict(),
        )

        prov_record = DatasetProvenanceRecord(
            provenance_id=deterministic_id(
                "PRV",
                {"ing": ingestion_id, "inst": canonical_inst, "tf": canonical_tf, "fp": full_val.dataset_fingerprint},
                length=16,
            ),
            ingestion_id=ingestion_id,
            job_id=job_id,
            provider=self.exp_config.provider_name,
            source_endpoint=source_endpoint_used,
            instrument=canonical_inst,
            symbol_token=meta.get("symbol_token", ""),
            timeframe=canonical_tf,
            requested_from_ist=req_from_iso,
            requested_to_ist=req_to_iso,
            actual_from_ist=full_val.actual_from_ist,
            actual_to_ist=full_val.actual_to_ist,
            raw_timestamp_first=all_raw_first,
            raw_timestamp_last=all_raw_last,
            source_timezone_offsets=tuple(sorted(observed_offsets)),
            row_count=full_val.actual_candles,
            duplicate_count=duplicate_rows_prevented,
            dataset_fingerprint=full_val.dataset_fingerprint,
            download_timestamp_utc=completed_utc,
            incremental_mode=self.exp_config.incremental,
            notes=full_val.notes,
        )
        if chunks_completed > 0 and (
            bars_stored > 0
            or (
                full_val.actual_candles > 0
                and not self.provenance_store.get_dataset_provenance(
                    instrument=canonical_inst, timeframe=canonical_tf
                )
            )
        ):
            self.provenance_store.record_dataset_provenance(prov_record)

        if invalid_chunks_rejected > 0 and bars_stored == 0:
            dl_status = DownloadStatus.FAILED_INTEGRITY
            blocked = True
        elif chunks_failed > 0 and chunks_completed < len(chunks):
            dl_status = DownloadStatus.INCOMPLETE
            blocked = False
        elif chunks_failed > 0:
            dl_status = DownloadStatus.BLOCKED
            blocked = True
        else:
            dl_status = DownloadStatus.COMPLETED
            blocked = False

        return DatasetExpansionResult(
            job_id=job_id,
            ingestion_id=ingestion_id,
            provider=self.exp_config.provider_name,
            instrument=canonical_inst,
            timeframe=canonical_tf,
            requested_from_ist=req_from_iso,
            requested_to_ist=req_to_iso,
            status=dl_status,
            quality_status=full_val.quality_status,
            blocked=blocked,
            blocked_reason=last_error_reason,
            chunks_total=len(chunks),
            chunks_completed=chunks_completed,
            chunks_skipped_resumed=chunks_skipped_resumed,
            chunks_skipped_existing=chunks_skipped_existing,
            chunks_failed=chunks_failed,
            bars_downloaded=bars_downloaded,
            bars_stored=bars_stored,
            duplicate_rows_prevented=duplicate_rows_prevented,
            invalid_chunks_rejected=invalid_chunks_rejected,
            source_timezone_offsets=tuple(sorted(observed_offsets)),
            dataset_fingerprint=full_val.dataset_fingerprint,
            validation_report=full_val,
            provenance_record=prov_record,
        )

    async def expand_batch(
        self,
        *,
        instruments: Sequence[str] = ("NIFTY 50", "BANK NIFTY", "FINNIFTY"),
        ranges_by_timeframe: Dict[str, Tuple[datetime, datetime]],
        as_of_time: Optional[datetime] = None,
    ) -> List[DatasetExpansionResult]:
        results: List[DatasetExpansionResult] = []
        for inst in instruments:
            for tf, (start_dt, end_dt) in ranges_by_timeframe.items():
                res = await self.expand_dataset(
                    instrument=inst,
                    timeframe=tf,
                    from_time=start_dt,
                    to_time=end_dt,
                    as_of_time=as_of_time,
                )
                results.append(res)
        return results
