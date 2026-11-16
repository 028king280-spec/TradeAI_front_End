"""
AIVOLVE Phase 4 Step 4.2 — Multi-Year Historical Market Calendar Adapter.

Provides an injectable, fail-closed NSE calendar adapter compatible with Phase 3
`SessionIntelligenceEngine(calendar=...)` and `MTFConfluenceEngine(calendar=...)`.

Strict Policies:
- Does NOT modify `app/data/market_calendar.py` or any Phase 3 module.
- Does NOT invent historical holiday dates or assume arbitrary weekdays are trading days.
- Fails closed with `CALENDAR_UNAVAILABLE` whenever a requested date's year lacks
  an explicitly verified holiday schedule.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from app.backtesting.configuration import IST_ZONE
from app.backtesting.models import (
    CalendarStatus,
    CalendarValidationResult,
    HolidayScheduleRecord,
)
from app.data import market_calendar as production_market_calendar


class CalendarUnavailableError(RuntimeError):
    """Raised when historical calendar verification lacks verified holiday coverage."""


def _parse_iso_date(raw: Union[date, str], field_name: str = "date") -> date:
    if isinstance(raw, datetime):
        raise TypeError(f"{field_name} must be a date or ISO YYYY-MM-DD string, not datetime")
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and raw.strip():
        return date.fromisoformat(raw.strip())
    raise ValueError(f"Invalid holiday date {raw!r} in {field_name}")


def _to_ist_date(dt_or_date: Union[datetime, date]) -> date:
    if isinstance(dt_or_date, datetime):
        if dt_or_date.tzinfo is None or dt_or_date.tzinfo.utcoffset(dt_or_date) is None:
            raise CalendarUnavailableError(
                f"Timezone-naive datetime rejected by historical calendar: {dt_or_date!r}"
            )
        return dt_or_date.astimezone(IST_ZONE).date()
    if isinstance(dt_or_date, date):
        return dt_or_date
    raise CalendarUnavailableError(f"Unsupported date value {dt_or_date!r}")


class HistoricalMarketCalendarAdapter:
    """
    Injectable multi-year NSE exchange holiday adapter compatible with Phase 3 engines.

    Exposes `.NSE_HOLIDAYS` (`FrozenSet[date]`) and `.is_trading_day(dt)` matching the
    contract inspected by `SessionIntelligenceEngine._validate_trading_calendar`.
    """

    def __init__(
        self,
        *,
        include_builtin_2026: bool = True,
        verified_schedules: Optional[
            Union[
                Sequence[HolidayScheduleRecord],
                Mapping[int, Union[Mapping[str, str], Iterable[Union[date, str]]]],
            ]
        ] = None,
        source_label: str = "verified_multi_year_calendar",
    ) -> None:
        self._schedules_by_year: Dict[int, HolidayScheduleRecord] = {}
        self._holidays: Set[date] = set()
        self.source_label = source_label

        if include_builtin_2026:
            builtin_dates = getattr(production_market_calendar, "NSE_HOLIDAYS", None)
            if isinstance(builtin_dates, (set, frozenset, list, tuple)) and len(builtin_dates) > 0:
                dates_2026 = {
                    d.isoformat(): "NSE Recognized Holiday (MarketCalendar)"
                    for d in sorted(builtin_dates)
                    if isinstance(d, date) and d.year == 2026
                }
                if dates_2026:
                    self.register_verified_year(
                        year=2026,
                        holidays=dates_2026,
                        source="app.data.market_calendar.NSE_HOLIDAYS",
                        verified=True,
                    )

        if verified_schedules is not None:
            if isinstance(verified_schedules, Mapping):
                for yr, entries in verified_schedules.items():
                    self.register_verified_year(
                        year=int(yr),
                        holidays=entries,
                        source=source_label,
                        verified=True,
                    )
            else:
                for rec in verified_schedules:
                    if not isinstance(rec, HolidayScheduleRecord):
                        raise TypeError(
                            "verified_schedules sequence items must be HolidayScheduleRecord instances"
                        )
                    self.register_verified_record(rec)

    @property
    def NSE_HOLIDAYS(self) -> FrozenSet[date]:
        """Compatibility attribute required by Phase 3 `SessionIntelligenceEngine`."""
        return frozenset(self._holidays)

    @property
    def covered_years(self) -> FrozenSet[int]:
        return frozenset(self._schedules_by_year.keys())

    def register_verified_record(self, record: HolidayScheduleRecord) -> None:
        """Registers an already validated `HolidayScheduleRecord`."""
        self.register_verified_year(
            year=record.year,
            holidays=record.holidays,
            source=record.source,
            verified=record.verified,
        )

    def register_verified_year(
        self,
        *,
        year: int,
        holidays: Union[Mapping[str, str], Iterable[Union[date, str]]],
        source: str,
        verified: bool = True,
    ) -> HolidayScheduleRecord:
        """
        Registers a verified NSE annual holiday schedule.

        Rejects unverified schedules or empty holiday lists so callers cannot bypass
        calendar governance by registering blank placeholder years.
        """
        if not verified:
            raise CalendarUnavailableError(
                f"Cannot register unverified holiday schedule for year {year} (source={source!r})."
            )
        if not isinstance(year, int) or isinstance(year, bool) or year < 1990 or year > 2100:
            raise ValueError(f"Invalid exchange calendar year: {year!r}")
        if not source or not source.strip():
            raise ValueError("Verified holiday schedule must declare a non-empty provenance source.")

        normalized: Dict[str, str] = {}
        if isinstance(holidays, Mapping):
            for raw_dt, label in holidays.items():
                parsed = _parse_iso_date(raw_dt, f"holidays[{raw_dt!r}]")
                if parsed.year != year:
                    raise ValueError(
                        f"Holiday date {parsed.isoformat()} does not match declared year {year}."
                    )
                normalized[parsed.isoformat()] = str(label or "Exchange Holiday").strip()
        else:
            for raw_dt in holidays:
                parsed = _parse_iso_date(raw_dt, "holidays")
                if parsed.year != year:
                    raise ValueError(
                        f"Holiday date {parsed.isoformat()} does not match declared year {year}."
                    )
                normalized[parsed.isoformat()] = "Exchange Holiday"

        if not normalized:
            raise CalendarUnavailableError(
                f"Cannot register empty holiday set for NSE year {year}; refusing placeholder calendar."
            )

        sorted_map = {k: normalized[k] for k in sorted(normalized.keys())}
        payload = json.dumps({"year": year, "holidays": sorted_map}, sort_keys=True)
        checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24].upper()
        record = HolidayScheduleRecord(
            year=year,
            holidays=sorted_map,
            source=source.strip(),
            verified=True,
            checksum_sha256=checksum,
        )

        # Replace year holidays deterministically
        self._holidays = {d for d in self._holidays if d.year != year}
        self._holidays.update(date.fromisoformat(d_str) for d_str in sorted_map.keys())
        self._schedules_by_year[year] = record
        return record

    @classmethod
    def from_json_file(
        cls,
        json_path: Union[Path, str],
        *,
        include_builtin_2026: bool = True,
    ) -> "HistoricalMarketCalendarAdapter":
        """Loads verified historical NSE holiday schedules from a JSON manifest."""
        path = Path(json_path)
        if not path.exists():
            raise CalendarUnavailableError(f"Verified holiday manifest not found: '{path}'")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("schedules"), list):
            raise ValueError("Holiday manifest JSON must contain a top-level 'schedules' list.")

        records = [HolidayScheduleRecord(**item) for item in raw["schedules"]]
        return cls(
            include_builtin_2026=include_builtin_2026,
            verified_schedules=records,
            source_label=f"json:{path.name}",
        )

    def calendar_fingerprint(self) -> str:
        """Returns deterministic SHA-256 fingerprint across all verified registered years."""
        canonical = {
            str(yr): sorted(self._schedules_by_year[yr].holidays.keys())
            for yr in sorted(self._schedules_by_year.keys())
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24].upper()

    def validate_date(self, target_date: Union[datetime, date]) -> CalendarValidationResult:
        """
        Validates whether `target_date` falls on a verified NSE trading day.
        Fails closed with `CALENDAR_UNAVAILABLE` if its year is unverified.
        """
        try:
            d = _to_ist_date(target_date)
        except Exception as exc:
            raise CalendarUnavailableError(f"Invalid target date for calendar validation: {exc}") from exc

        fp = self.calendar_fingerprint()

        if d.year not in self._schedules_by_year:
            return CalendarValidationResult(
                is_valid=False,
                is_trading_day=False,
                status=CalendarStatus.CALENDAR_UNAVAILABLE,
                target_date=d,
                reason=f"Verified NSE holiday schedule unavailable for year {d.year} (fail-closed).",
                calendar_fingerprint=fp,
            )

        if d.weekday() >= 5:
            return CalendarValidationResult(
                is_valid=True,
                is_trading_day=False,
                status=CalendarStatus.NON_TRADING_DAY,
                target_date=d,
                reason=f"Weekend non-trading day ({d.strftime('%A')} {d.isoformat()}).",
                calendar_fingerprint=fp,
            )

        if d in self._holidays:
            hol_name = self._schedules_by_year[d.year].holidays.get(d.isoformat(), "Exchange Holiday")
            return CalendarValidationResult(
                is_valid=True,
                is_trading_day=False,
                status=CalendarStatus.NON_TRADING_DAY,
                target_date=d,
                reason=f"Exchange holiday ({d.isoformat()}: {hol_name}).",
                calendar_fingerprint=fp,
            )

        return CalendarValidationResult(
            is_valid=True,
            is_trading_day=True,
            status=CalendarStatus.TRADING_DAY,
            target_date=d,
            reason=f"Verified NSE trading session ({d.isoformat()}).",
            calendar_fingerprint=fp,
        )

    def is_trading_day(self, dt: Union[datetime, date]) -> bool:
        """
        Boolean compatibility check for `SessionIntelligenceEngine`.
        Raises `CalendarUnavailableError` when calendar coverage for `dt.year` is absent.
        """
        res = self.validate_date(dt)
        if res.status == CalendarStatus.CALENDAR_UNAVAILABLE:
            raise CalendarUnavailableError(res.reason)
        return res.is_trading_day

    def iter_trading_days(self, start_date: date, end_date: date) -> List[date]:
        """
        Returns ascending verified NSE trading days within `[start_date, end_date]`.
        Fails closed if ANY calendar day inside the interval belongs to an unverified year.
        """
        if end_date < start_date:
            raise ValueError(f"end_date ({end_date}) cannot precede start_date ({start_date}).")

        trading_days: List[date] = []
        cur = start_date
        while cur <= end_date:
            res = self.validate_date(cur)
            if res.status == CalendarStatus.CALENDAR_UNAVAILABLE:
                raise CalendarUnavailableError(res.reason)
            if res.is_trading_day:
                trading_days.append(cur)
            cur += timedelta(days=1)
        return trading_days

    def schedule_summary(self) -> Dict[str, Any]:
        return {
            "source_label": self.source_label,
            "covered_years": sorted(self._schedules_by_year.keys()),
            "holiday_counts_by_year": {
                yr: len(rec.holidays) for yr, rec in sorted(self._schedules_by_year.items())
            },
            "sources_by_year": {
                yr: rec.source for yr, rec in sorted(self._schedules_by_year.items())
            },
            "calendar_fingerprint": self.calendar_fingerprint(),
        }

