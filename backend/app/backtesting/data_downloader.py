"""
AIVOLVE Phase 4 Step 4.2 — Dedicated Historical Data Downloader Adapter.

Adapts the existing `AngelOneMarketDataProvider` for safe multi-chunk historical
candlestick ingestion into isolated `HistoricalDataStore`.

Strict Policies:
- Does NOT modify `app/data/providers/angelone_provider.py` or Phase 1 quality logic.
- Validates credentials/authentication upfront; reports `BLOCKED` cleanly when offline.
- Uses conservative timeframe-specific date-range chunking + rate-limit backoff.
- Preserves original OHLCV values verbatim; NEVER creates synthetic/mock bars.
- Never silently repairs malformed/missing candles: rejects DEGRADED/repaired chunks,
  detects incomplete downloads across trading dates, and runs full `DataIntegrityAuditor`
  before storing anything.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any, List, Optional, Tuple

import pandas as pd

from app.backtesting.calendar_adapter import (
    CalendarUnavailableError,
    HistoricalMarketCalendarAdapter,
)
from app.backtesting.configuration import (
    ANGELONE_INSTRUMENT_METADATA,
    ANGELONE_MAX_CHUNK_DAYS,
    BacktestConfiguration,
    IST_ZONE,
    normalize_instrument,
    normalize_timeframe,
    verify_index_governance,
)
from app.backtesting.data_integrity import DataIntegrityAuditor, compute_candle_close_ist
from app.backtesting.data_store import HistoricalDataStore
from app.backtesting.models import (
    ChunkDownloadRecord,
    DownloadStatus,
    HistoricalDownloadResult,
    IntegrityStatus,
)
from app.data.providers.angelone_provider import AngelOneMarketDataProvider


def _require_tz_aware_ist(dt: datetime, field_name: str) -> datetime:
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime, got {dt!r}")
    return dt.astimezone(IST_ZONE)


def build_date_chunks(
    from_ist: datetime,
    to_ist: datetime,
    *,
    timeframe: str,
    calendar_adapter: Optional[HistoricalMarketCalendarAdapter] = None,
    max_chunk_days_override: Optional[int] = None,
) -> List[Tuple[datetime, datetime]]:
    """
    Splits `[from_ist, to_ist]` into non-overlapping IST date chunks respecting Angel One limits.
    When `calendar_adapter` is supplied, validates multi-year coverage and omits pure
    holiday/weekend spans with zero trading sessions.
    """
    norm_tf = normalize_timeframe(timeframe)
    if to_ist <= from_ist:
        raise ValueError(f"to_time ({to_ist}) must exceed from_time ({from_ist}).")

    max_days = max_chunk_days_override or ANGELONE_MAX_CHUNK_DAYS[norm_tf]
    if max_days < 1:
        raise ValueError("max_chunk_days must be >= 1")

    chunks: List[Tuple[datetime, datetime]] = []
    cur_date = from_ist.date()
    end_date = to_ist.date()

    while cur_date <= end_date:
        span_end_date = min(end_date, cur_date + timedelta(days=max_days - 1))

        if calendar_adapter is not None:
            trading_days = calendar_adapter.iter_trading_days(cur_date, span_end_date)
            if not trading_days:
                cur_date = span_end_date + timedelta(days=1)
                continue

        if cur_date == from_ist.date():
            if norm_tf == "1d":
                c_start = min(from_ist, datetime.combine(cur_date, dt_time(0, 0), tzinfo=IST_ZONE))
            else:
                c_start = from_ist
        else:
            start_t = dt_time(0, 0) if norm_tf == "1d" else dt_time(9, 15)
            c_start = datetime.combine(cur_date, start_t, tzinfo=IST_ZONE)

        if span_end_date == end_date:
            c_end = to_ist
        else:
            c_end = datetime.combine(span_end_date, dt_time(15, 30), tzinfo=IST_ZONE)

        if c_end > c_start:
            chunks.append((c_start, c_end))

        cur_date = span_end_date + timedelta(days=1)

    return chunks


class AngelOneHistoricalDataDownloader:
    """
    Dedicated historical market-data adapter wrapping `AngelOneMarketDataProvider`.
    """

    def __init__(
        self,
        *,
        provider: Optional[AngelOneMarketDataProvider] = None,
        data_store: Optional[HistoricalDataStore] = None,
        calendar_adapter: Optional[HistoricalMarketCalendarAdapter] = None,
        config: Optional[BacktestConfiguration] = None,
    ) -> None:
        self.config = config or BacktestConfiguration()
        self.provider = provider
        self.calendar_adapter = calendar_adapter or HistoricalMarketCalendarAdapter()
        self.data_store = data_store or HistoricalDataStore(config=self.config)
        self.auditor = DataIntegrityAuditor(
            calendar_adapter=self.calendar_adapter,
            market_open_hhmm=self.config.market_open_hhmm,
            market_close_hhmm=self.config.market_close_hhmm,
            strict_missing_intervals=self.config.strict_missing_intervals,
            require_volume_column=self.config.require_volume_column,
        )

    def _resolve_provider(self) -> AngelOneMarketDataProvider:
        if self.provider is None:
            self.provider = AngelOneMarketDataProvider()
        return self.provider

    async def _verify_provider_ready(
        self,
        provider: Any,
    ) -> Tuple[bool, Optional[str]]:
        if getattr(provider, "is_authenticated", False):
            return True, None

        client_code = str(getattr(provider, "client_code", "") or "").strip()
        pin = str(getattr(provider, "pin", "") or "").strip()
        api_key = str(getattr(provider, "api_key", "") or "").strip()
        totp = str(getattr(provider, "totp_secret", "") or "").strip()

        ensure_auth = getattr(provider, "_ensure_authenticated", None)
        if not client_code or not pin or not api_key or not totp:
            # Allow test providers overriding `_ensure_authenticated` to decide explicitly if stubbed,
            # otherwise missing credentials immediately block ingestion without hitting live network.
            if callable(ensure_auth) and type(provider) is not AngelOneMarketDataProvider:
                try:
                    ok = bool(await ensure_auth())
                except Exception as exc:
                    return False, f"Provider authentication error: {exc}"
                return (ok, None if ok else "Provider authentication returned False.")
            return (
                False,
                "Angel One credentials missing (ANGELONE_API_KEY / CLIENT_CODE / PIN / TOTP_SECRET); historical download BLOCKED.",
            )

        if callable(ensure_auth):
            try:
                ok = bool(await ensure_auth())
            except Exception as exc:
                return False, f"Angel One authentication failed: {exc}"
            if not ok:
                return (
                    False,
                    "Angel One login failed or credentials rejected; historical download BLOCKED.",
                )
        return True, None

    @staticmethod
    def _build_blocked_result(
        *,
        status: DownloadStatus,
        reason: str,
        instrument: str,
        meta: dict[str, str],
        timeframe: str,
        from_ist: datetime,
        to_ist: datetime,
        chunks: List[ChunkDownloadRecord] = (),  # type: ignore[assignment]
        bars_downloaded: int = 0,
        integrity_report: Any = None,
    ) -> HistoricalDownloadResult:
        return HistoricalDownloadResult(
            status=status,
            blocked=True,
            block_reason=reason,
            provider="angelone",
            instrument=instrument,
            exchange=meta["exchange"],
            symbol_token=meta["symbol_token"],
            timeframe=timeframe,
            requested_from_ist=from_ist.isoformat(),
            requested_to_ist=to_ist.isoformat(),
            bars_downloaded=bars_downloaded,
            bars_stored=0,
            chunks_total=len(chunks),
            chunks_succeeded=sum(1 for c in chunks if c.status == "OK"),
            chunks_empty=sum(1 for c in chunks if c.bars_received == 0),
            chunks=tuple(chunks),
            integrity_report=integrity_report,
            retrieved_at_utc=datetime.now(timezone.utc),
        )

    async def download_and_store(
        self,
        *,
        instrument: str,
        timeframe: str,
        from_time: datetime,
        to_time: datetime,
        max_chunk_days_override: Optional[int] = None,
        persist: bool = True,
    ) -> HistoricalDownloadResult:
        """
        Downloads historical OHLCV bars from Angel One in safe chunks, validates raw
        response & integrity without silent repair, and stores verified bars cleanly.
        """
        norm_inst = normalize_instrument(instrument)
        norm_tf = normalize_timeframe(timeframe)
        meta = ANGELONE_INSTRUMENT_METADATA[norm_inst]
        from_ist = _require_tz_aware_ist(from_time, "from_time")
        to_ist = _require_tz_aware_ist(to_time, "to_time")

        if to_ist <= from_ist:
            return self._build_blocked_result(
                status=DownloadStatus.BLOCKED,
                reason=f"Invalid download interval: to_time ({to_ist}) must exceed from_time ({from_ist}).",
                instrument=norm_inst,
                meta=meta,
                timeframe=norm_tf,
                from_ist=from_ist,
                to_ist=to_ist,
            )

        gov_ok, _gov_status, gov_info = verify_index_governance(
            norm_inst,
            sensex_governance_approved=self.config.sensex_governance_approved,
            governance_db_path=self.config.governance_ledger_path,
        )
        if not gov_ok:
            return self._build_blocked_result(
                status=DownloadStatus.GOVERNANCE_LOCKOUT,
                reason=str(gov_info.get("reason") or "GOVERNANCE_LOCKOUT"),
                instrument=norm_inst,
                meta=meta,
                timeframe=norm_tf,
                from_ist=from_ist,
                to_ist=to_ist,
            )

        try:
            chunks_plan = build_date_chunks(
                from_ist,
                to_ist,
                timeframe=norm_tf,
                calendar_adapter=self.calendar_adapter,
                max_chunk_days_override=max_chunk_days_override,
            )
        except CalendarUnavailableError as exc:
            return self._build_blocked_result(
                status=DownloadStatus.BLOCKED,
                reason=f"CALENDAR_UNAVAILABLE: {exc}",
                instrument=norm_inst,
                meta=meta,
                timeframe=norm_tf,
                from_ist=from_ist,
                to_ist=to_ist,
            )

        if not chunks_plan:
            return self._build_blocked_result(
                status=DownloadStatus.BLOCKED,
                reason=(
                    f"No verified NSE trading sessions present between {from_ist.date().isoformat()} "
                    f"and {to_ist.date().isoformat()}."
                ),
                instrument=norm_inst,
                meta=meta,
                timeframe=norm_tf,
                from_ist=from_ist,
                to_ist=to_ist,
            )

        provider = self._resolve_provider()
        auth_ok, auth_reason = await self._verify_provider_ready(provider)
        if not auth_ok:
            return self._build_blocked_result(
                status=DownloadStatus.BLOCKED,
                reason=auth_reason or "Angel One authentication failed; ingestion BLOCKED.",
                instrument=norm_inst,
                meta=meta,
                timeframe=norm_tf,
                from_ist=from_ist,
                to_ist=to_ist,
            )

        chunk_records: List[ChunkDownloadRecord] = []
        chunk_frames: List[pd.DataFrame] = []

        for idx, (c_start, c_end) in enumerate(chunks_plan):
            if idx > 0 and self.config.rate_limit_delay_seconds > 0:
                await asyncio.sleep(self.config.rate_limit_delay_seconds)

            chunk_df: Optional[pd.DataFrame] = None
            last_exc: Optional[str] = None
            for attempt in range(self.config.max_retries + 1):
                try:
                    chunk_df = await provider.get_historical_candles(
                        norm_inst,
                        norm_tf,
                        c_start,
                        c_end,
                    )
                except Exception as exc:
                    last_exc = str(exc)
                    chunk_df = None

                if chunk_df is not None and not chunk_df.empty:
                    attrs = chunk_df.attrs if hasattr(chunk_df, "attrs") and isinstance(chunk_df.attrs, dict) else {}
                    break

                # Retry only if transient throttle/DEGRADED or exception; otherwise break early
                attrs = (
                    chunk_df.attrs
                    if (chunk_df is not None and hasattr(chunk_df, "attrs") and isinstance(chunk_df.attrs, dict))
                    else {}
                )
                d_stat = str(attrs.get("dataStatus") or attrs.get("feedStatus") or "").upper()
                d_reason_l = str(attrs.get("degraded_reason") or "").lower()
                is_transient_throttle = (
                    chunk_df is None
                    or d_stat in {"DEGRADED", "RATE_LIMITED"}
                    or "http 403" in d_reason_l
                    or "http 429" in d_reason_l
                    or "rate" in d_reason_l
                    or "throttl" in d_reason_l
                )
                should_retry = is_transient_throttle and (attempt < self.config.max_retries)
                if not should_retry:
                    break
                if self.config.retry_backoff_seconds > 0:
                    await asyncio.sleep(self.config.retry_backoff_seconds * (attempt + 1))

            if chunk_df is None or not isinstance(chunk_df, pd.DataFrame):
                chunk_records.append(
                    ChunkDownloadRecord(
                        chunk_index=idx,
                        from_time_ist=c_start.isoformat(),
                        to_time_ist=c_end.isoformat(),
                        status="PROVIDER_ERROR",
                        bars_received=0,
                        reason=last_exc or "Provider returned invalid non-DataFrame chunk.",
                    )
                )
                return self._build_blocked_result(
                    status=DownloadStatus.BLOCKED,
                    reason=f"Provider error on chunk {idx}: {last_exc or 'invalid response'}.",
                    instrument=norm_inst,
                    meta=meta,
                    timeframe=norm_tf,
                    from_ist=from_ist,
                    to_ist=to_ist,
                    chunks=chunk_records,
                )

            attrs = chunk_df.attrs if hasattr(chunk_df, "attrs") and isinstance(chunk_df.attrs, dict) else {}
            data_status = str(attrs.get("dataStatus") or attrs.get("feedStatus") or "").upper()

            if chunk_df.empty:
                reason = str(
                    attrs.get("degraded_reason")
                    or f"Provider returned 0 candles (status={data_status or 'EMPTY'})"
                )
                chunk_records.append(
                    ChunkDownloadRecord(
                        chunk_index=idx,
                        from_time_ist=c_start.isoformat(),
                        to_time_ist=c_end.isoformat(),
                        status=data_status or "EMPTY",
                        bars_received=0,
                        http_status=attrs.get("http_status"),
                        error_code=attrs.get("error_code"),
                        reason=reason,
                    )
                )
                out_status = (
                    DownloadStatus.INCOMPLETE if chunk_frames else DownloadStatus.BLOCKED
                )
                return self._build_blocked_result(
                    status=out_status,
                    reason=(
                        f"Incomplete or unavailable provider response on chunk {idx} "
                        f"[{c_start.isoformat()} .. {c_end.isoformat()}]: {reason}"
                    ),
                    instrument=norm_inst,
                    meta=meta,
                    timeframe=norm_tf,
                    from_ist=from_ist,
                    to_ist=to_ist,
                    chunks=chunk_records,
                    bars_downloaded=sum(len(f) for f in chunk_frames),
                )

            # Fail closed on synthetic/mock OR provider-repaired (DEGRADED) non-empty chunks
            if (
                attrs.get("is_mock") is True
                or attrs.get("is_synthetic") is True
                or data_status in {"MOCK", "SYNTHETIC"}
            ):
                chunk_records.append(
                    ChunkDownloadRecord(
                        chunk_index=idx,
                        from_time_ist=c_start.isoformat(),
                        to_time_ist=c_end.isoformat(),
                        status="SYNTHETIC_REJECTED",
                        bars_received=len(chunk_df),
                        reason="Provider returned synthetic/mock candles (rejected).",
                    )
                )
                return self._build_blocked_result(
                    status=DownloadStatus.FAILED_INTEGRITY,
                    reason="Provider returned synthetic or mock candle data (rejected).",
                    instrument=norm_inst,
                    meta=meta,
                    timeframe=norm_tf,
                    from_ist=from_ist,
                    to_ist=to_ist,
                    chunks=chunk_records,
                    bars_downloaded=sum(len(f) for f in chunk_frames) + len(chunk_df),
                )

            if attrs.get("ohlc_repaired") is True or data_status in {
                "DEGRADED",
                "DATA_OFFLINE",
                "DATA_UNAVAILABLE",
                "STALE",
                "ANOMALOUS",
            }:
                chunk_records.append(
                    ChunkDownloadRecord(
                        chunk_index=idx,
                        from_time_ist=c_start.isoformat(),
                        to_time_ist=c_end.isoformat(),
                        status="REPAIRED_OR_DEGRADED_REJECTED",
                        bars_received=len(chunk_df),
                        reason=(
                            f"Chunk flagged {data_status or 'REPAIRED'} — "
                            "silently repaired or degraded OHLCV rejected."
                        ),
                    )
                )
                return self._build_blocked_result(
                    status=DownloadStatus.FAILED_INTEGRITY,
                    reason=(
                        f"Chunk {idx} marked '{data_status or 'ohlc_repaired'}': "
                        "Step 4.2 refuses silently repaired/degraded historical bars."
                    ),
                    instrument=norm_inst,
                    meta=meta,
                    timeframe=norm_tf,
                    from_ist=from_ist,
                    to_ist=to_ist,
                    chunks=chunk_records,
                    bars_downloaded=sum(len(f) for f in chunk_frames) + len(chunk_df),
                )

            raw_copy = chunk_df.copy()
            # Explicitly reject mismatched attrs['timeframe'] without silent override
            attr_tf = attrs.get("timeframe")
            if attr_tf is not None and str(attr_tf).strip().lower() != norm_tf:
                chunk_records.append(
                    ChunkDownloadRecord(
                        chunk_index=idx,
                        from_time_ist=c_start.isoformat(),
                        to_time_ist=c_end.isoformat(),
                        status="TIMEFRAME_MISMATCH",
                        bars_received=len(chunk_df),
                        reason=f"Provider returned timeframe '{attr_tf}' when '{norm_tf}' was requested.",
                    )
                )
                return self._build_blocked_result(
                    status=DownloadStatus.FAILED_INTEGRITY,
                    reason=(
                        f"Provider timeframe mismatch: requested '{norm_tf}', got '{attr_tf}'."
                    ),
                    instrument=norm_inst,
                    meta=meta,
                    timeframe=norm_tf,
                    from_ist=from_ist,
                    to_ist=to_ist,
                    chunks=chunk_records,
                )

            # Filter columns cleanly preserving exact OHLCV values (add is_complete only if absent & provably closed)
            if "volume" not in raw_copy.columns:
                chunk_records.append(
                    ChunkDownloadRecord(
                        chunk_index=idx,
                        from_time_ist=c_start.isoformat(),
                        to_time_ist=c_end.isoformat(),
                        status="MISSING_VOLUME_COLUMN",
                        bars_received=len(chunk_df),
                        reason="Provider chunk lacks required 'volume' column.",
                    )
                )
                return self._build_blocked_result(
                    status=DownloadStatus.FAILED_INTEGRITY,
                    reason="Provider chunk lacks required 'volume' column.",
                    instrument=norm_inst,
                    meta=meta,
                    timeframe=norm_tf,
                    from_ist=from_ist,
                    to_ist=to_ist,
                    chunks=chunk_records,
                )

            keep_cols = ["timestamp", "open", "high", "low", "close", "volume"]
            if "is_complete" in raw_copy.columns:
                keep_cols.append("is_complete")
            clean_chunk = raw_copy[keep_cols].copy()
            clean_chunk.attrs = {
                "instrument": norm_inst,
                "timeframe": norm_tf,
                "provider": str(attrs.get("provider") or "angelone"),
                "dataStatus": "VERIFIED_EOD",
                "feedStatus": "VERIFIED_EOD",
                "is_mock": False,
                "is_synthetic": False,
                "ohlc_repaired": False,
            }
            chunk_frames.append(clean_chunk)
            chunk_records.append(
                ChunkDownloadRecord(
                    chunk_index=idx,
                    from_time_ist=c_start.isoformat(),
                    to_time_ist=c_end.isoformat(),
                    status="OK",
                    bars_received=len(clean_chunk),
                )
            )

        combined_df = pd.concat(chunk_frames, ignore_index=True)
        combined_df.attrs = dict(chunk_frames[0].attrs)

        # Ensure historical completion bound `as_of_time = to_ist` checks every bar closed by to_ist
        integrity_report = self.auditor.audit_dataframe(
            combined_df,
            instrument=norm_inst,
            timeframe=norm_tf,
            as_of_time=to_ist,
            expected_from_ist=from_ist,
            expected_to_ist=to_ist,
            require_all_completed=True,
            check_missing_intervals=True,
        )

        if not integrity_report.is_valid or integrity_report.status != IntegrityStatus.PASSED:
            out_status = (
                DownloadStatus.INCOMPLETE
                if integrity_report.missing_intervals
                else DownloadStatus.FAILED_INTEGRITY
            )
            return HistoricalDownloadResult(
                status=out_status,
                blocked=True,
                block_reason="; ".join(integrity_report.rejected_reasons),
                provider="angelone",
                instrument=norm_inst,
                exchange=meta["exchange"],
                symbol_token=meta["symbol_token"],
                timeframe=norm_tf,
                requested_from_ist=from_ist.isoformat(),
                requested_to_ist=to_ist.isoformat(),
                actual_from_ist=integrity_report.first_timestamp_ist,
                actual_to_ist=integrity_report.last_timestamp_ist,
                bars_downloaded=len(combined_df),
                bars_stored=0,
                chunks_total=len(chunks_plan),
                chunks_succeeded=sum(1 for c in chunk_records if c.status == "OK"),
                chunks_empty=0,
                chunks=tuple(chunk_records),
                integrity_report=integrity_report,
                retrieved_at_utc=datetime.now(timezone.utc),
            )

        bars_stored = 0
        ingestion_id: Optional[str] = None
        if persist:
            bars_stored, integrity_report, ingestion_id = self.data_store.save_candles(
                combined_df,
                instrument=norm_inst,
                timeframe=norm_tf,
                provider="angelone",
                exchange=meta["exchange"],
                symbol_token=meta["symbol_token"],
                calendar_adapter=self.calendar_adapter,
                auditor=self.auditor,
                requested_from_ist=from_ist,
                requested_to_ist=to_ist,
                chunk_records=chunk_records,
            )

        return HistoricalDownloadResult(
            status=DownloadStatus.COMPLETED,
            blocked=False,
            provider="angelone",
            instrument=norm_inst,
            exchange=meta["exchange"],
            symbol_token=meta["symbol_token"],
            timeframe=norm_tf,
            requested_from_ist=from_ist.isoformat(),
            requested_to_ist=to_ist.isoformat(),
            actual_from_ist=integrity_report.first_timestamp_ist,
            actual_to_ist=integrity_report.last_timestamp_ist,
            bars_downloaded=len(combined_df),
            bars_stored=bars_stored,
            chunks_total=len(chunks_plan),
            chunks_succeeded=len(chunk_records),
            chunks_empty=0,
            chunks=tuple(chunk_records),
            integrity_report=integrity_report,
            dataset_fingerprint=integrity_report.dataset_fingerprint,
            ingestion_id=ingestion_id,
            retrieved_at_utc=datetime.now(timezone.utc),
        )

