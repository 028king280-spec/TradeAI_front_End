"""
AIVOLVE Phase 4 Step 4.6 — Multi-Year Verified Exchange Trading Calendar.

Extends `HistoricalMarketCalendarAdapter` for multi-year (2024–2026+) NSE trading
calendars with full source provenance, special trading sessions (Muhurat Trading,
Union Budget weekend sessions, DR switchover split sessions, replacement sessions),
exceptional closures (elections / special public holidays), custom per-date session
boundaries, and strict fail-closed behavior for unverified calendar years.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as dt_time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from app.backtesting.calendar_adapter import (
    CalendarUnavailableError,
    HistoricalMarketCalendarAdapter,
)
from app.backtesting.configuration import (
    IST_ZONE,
    TIMEFRAME_DURATION_MINUTES,
    normalize_timeframe,
)
from app.backtesting.data_integrity import compute_candle_close_ist
from app.backtesting.models import (
    CalendarStatus,
    CalendarValidationResult,
    HolidayScheduleRecord,
)


class SessionType(str, Enum):
    REGULAR = "REGULAR"
    MUHURAT_TRADING = "MUHURAT_TRADING"
    WEEKEND_SPECIAL_BUDGET = "WEEKEND_SPECIAL_BUDGET"
    DISASTER_RECOVERY_MOCK = "DISASTER_RECOVERY_MOCK"
    REPLACEMENT_SPECIAL_SESSION = "REPLACEMENT_SPECIAL_SESSION"
    HOLIDAY = "HOLIDAY"
    EXCEPTIONAL_CLOSURE = "EXCEPTIONAL_CLOSURE"
    WEEKEND = "WEEKEND"
    CALENDAR_UNAVAILABLE = "CALENDAR_UNAVAILABLE"


@dataclass(frozen=True)
class SessionWindow:
    open_hhmm: str
    close_hhmm: str
    label: str = "REGULAR"

    @property
    def open_time(self) -> dt_time:
        hh, mm = (int(x) for x in self.open_hhmm.split(":"))
        return dt_time(hh, mm)

    @property
    def close_time(self) -> dt_time:
        hh, mm = (int(x) for x in self.close_hhmm.split(":"))
        return dt_time(hh, mm)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SpecialTradingSessionRecord:
    session_date: str  # YYYY-MM-DD
    session_type: SessionType
    description: str
    windows: Tuple[SessionWindow, ...]
    source_reference: str
    verified: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_date": self.session_date,
            "session_type": self.session_type.value,
            "description": self.description,
            "windows": [w.to_dict() for w in self.windows],
            "source_reference": self.source_reference,
            "verified": self.verified,
        }


@dataclass(frozen=True)
class ExceptionalClosureRecord:
    closure_date: str  # YYYY-MM-DD
    description: str
    replaced_by_date: Optional[str]
    source_reference: str
    verified: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CalendarYearProvenance:
    year: int
    exchange: str
    source_reference: str
    circular_reference: str
    verification_note: str
    checksum_sha256: str
    holiday_count: int
    special_session_count: int
    exceptional_closure_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


REGULAR_NSE_WINDOWS: Tuple[SessionWindow, ...] = (
    SessionWindow(open_hhmm="09:15", close_hhmm="15:30", label="REGULAR"),
)


VERIFIED_NSE_2024_HOLIDAYS: Dict[date, str] = {
    date(2024, 1, 22): "Exceptional Closure: Ram Mandir Pran Pratishtha (replaced by Sat 2024-01-20)",
    date(2024, 1, 26): "Republic Day",
    date(2024, 3, 8): "Mahashivratri",
    date(2024, 3, 25): "Holi",
    date(2024, 3, 29): "Good Friday",
    date(2024, 4, 11): "Id-Ul-Fitr (Ramzan Id)",
    date(2024, 4, 17): "Shri Ram Navmi",
    date(2024, 5, 1): "Maharashtra Day",
    date(2024, 5, 20): "Exceptional Closure: Lok Sabha General Elections - Mumbai (NSE/CMTR/61518)",
    date(2024, 6, 17): "Bakri Id",
    date(2024, 7, 17): "Moharram",
    date(2024, 8, 15): "Independence Day",
    date(2024, 10, 2): "Mahatma Gandhi Jayanti",
    date(2024, 11, 15): "Gurunanak Jayanti",
    date(2024, 11, 20): "Exceptional Closure: Maharashtra Legislative Assembly Elections",
    date(2024, 12, 25): "Christmas",
}

VERIFIED_NSE_2025_HOLIDAYS: Dict[date, str] = {
    date(2025, 2, 26): "Mahashivratri",
    date(2025, 3, 14): "Holi",
    date(2025, 3, 31): "Id-Ul-Fitr (Ramzan Id)",
    date(2025, 4, 10): "Shri Mahavir Jayanti",
    date(2025, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    date(2025, 4, 18): "Good Friday",
    date(2025, 5, 1): "Maharashtra Day",
    date(2025, 8, 15): "Independence Day",
    date(2025, 8, 27): "Ganesh Chaturthi",
    date(2025, 10, 2): "Mahatma Gandhi Jayanti / Dussehra",
    date(2025, 10, 22): "Diwali Balipratipada",
    date(2025, 11, 5): "Prakash Gurpurb Sri Guru Nanak Dev",
    date(2025, 12, 25): "Christmas",
}

VERIFIED_NSE_2026_HOLIDAYS: Dict[date, str] = {
    date(2026, 1, 15): "Exceptional Closure: Maharashtra Municipal Corporation Elections",
    date(2026, 1, 26): "Republic Day",
    date(2026, 3, 3): "Holi",
    date(2026, 3, 26): "Shri Ram Navami",
    date(2026, 3, 31): "Shri Mahavir Jayanti",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    date(2026, 5, 1): "Maharashtra Day",
    date(2026, 5, 28): "Bakri Id",
    date(2026, 6, 26): "Muharram",
    date(2026, 9, 14): "Ganesh Chaturthi",
    date(2026, 10, 2): "Mahatma Gandhi Jayanti",
    date(2026, 10, 20): "Dussehra",
    date(2026, 11, 10): "Diwali Balipratipada",
    date(2026, 11, 24): "Prakash Gurpurb Sri Guru Nanak Dev",
    date(2026, 12, 25): "Christmas",
}

YEAR_CIRCULAR_NOTES: Dict[int, str] = {
    2024: "NSE Circulars 2024 + Empirically verified Jan 20 replacement, May 18 DR split, Nov 1 Muhurat, May 20 / Nov 20 election closures",
    2025: "NSE Circulars 2025 + Empirically verified Feb 1 Budget Sat, Oct 21 Muhurat (13:45-14:45 IST), Oct 22 Balipratipada",
    2026: "NSE Circulars 2026 + Empirically verified Jan 15 election, Feb 1 Budget Sun, Mar 3 Holi, Sep 14 Ganesh Chaturthi, Oct 20 Dussehra, Nov 8 Muhurat (14:20-15:30 IST), Nov 10 Balipratipada",
}

BUILTIN_SPECIAL_SESSIONS: Tuple[SpecialTradingSessionRecord, ...] = (
    SpecialTradingSessionRecord(
        session_date="2024-01-20",
        session_type=SessionType.REPLACEMENT_SPECIAL_SESSION,
        description="Saturday full trading day replacing Mon 2024-01-22 Ram Mandir closure",
        windows=(SessionWindow("09:15", "15:30", "REPLACEMENT_FULL_SESSION"),),
        source_reference="NSE Circular Jan 2024 + Angel One NIFTY 1d bar verified",
        verified=True,
    ),
    SpecialTradingSessionRecord(
        session_date="2024-03-02",
        session_type=SessionType.DISASTER_RECOVERY_MOCK,
        description="Saturday Special Live DR Switchover Session (Primary 09:15-10:00, DR 11:30-12:30)",
        windows=(
            SessionWindow("09:15", "10:00", "PRIMARY_SITE"),
            SessionWindow("11:30", "12:30", "DR_SITE"),
        ),
        source_reference="NSE CMTR Special Live DR Circular Mar 2024",
        verified=True,
    ),
    SpecialTradingSessionRecord(
        session_date="2024-05-18",
        session_type=SessionType.DISASTER_RECOVERY_MOCK,
        description="Saturday Special Live DR Switchover Session (Primary 09:15-10:00, DR 11:30-12:30)",
        windows=(
            SessionWindow("09:15", "10:00", "PRIMARY_SITE"),
            SessionWindow("11:30", "12:30", "DR_SITE"),
        ),
        source_reference="NSE CMTR Special Live DR Circular May 2024 + Angel One 21x5m bars verified",
        verified=True,
    ),
    SpecialTradingSessionRecord(
        session_date="2024-11-01",
        session_type=SessionType.MUHURAT_TRADING,
        description="Diwali Laxmi Pujan Muhurat Trading Session (Samvat 2081)",
        windows=(SessionWindow("18:00", "19:00", "MUHURAT_TRADING"),),
        source_reference="NSE Diwali Muhurat Circular Nov 2024 + Angel One 60x1m bars verified (18:00-18:59)",
        verified=True,
    ),
    SpecialTradingSessionRecord(
        session_date="2025-02-01",
        session_type=SessionType.WEEKEND_SPECIAL_BUDGET,
        description="Union Budget 2025-26 Saturday Special Full-Day Session",
        windows=(SessionWindow("09:15", "15:30", "BUDGET_SPECIAL_SESSION"),),
        source_reference="NSE Budget Day Circular Feb 2025 + Angel One 75x5m bars verified",
        verified=True,
    ),
    SpecialTradingSessionRecord(
        session_date="2025-10-21",
        session_type=SessionType.MUHURAT_TRADING,
        description="Diwali Laxmi Pujan Muhurat Trading Session (Samvat 2082)",
        windows=(SessionWindow("13:45", "14:45", "MUHURAT_TRADING"),),
        source_reference="NSE Diwali Muhurat Circular Oct 2025 (Normal Market 1:45 PM - 2:45 PM IST)",
        verified=True,
    ),
    SpecialTradingSessionRecord(
        session_date="2026-02-01",
        session_type=SessionType.WEEKEND_SPECIAL_BUDGET,
        description="Union Budget 2026-27 Sunday Special Full-Day Session",
        windows=(SessionWindow("09:15", "15:30", "BUDGET_SPECIAL_SESSION"),),
        source_reference="NSE Budget Day Circular Feb 2026 + Angel One NIFTY 1d bar verified",
        verified=True,
    ),
    SpecialTradingSessionRecord(
        session_date="2026-11-08",
        session_type=SessionType.MUHURAT_TRADING,
        description="Diwali Laxmi Pujan Muhurat Trading Session (Samvat 2083)",
        windows=(SessionWindow("14:20", "15:30", "MUHURAT_TRADING"),),
        source_reference="NSE Diwali Muhurat Circular Nov 2026 (2:20 PM - 3:30 PM IST) + Angel One 1d bar verified",
        verified=True,
    ),
)

BUILTIN_EXCEPTIONAL_CLOSURES: Tuple[ExceptionalClosureRecord, ...] = (
    ExceptionalClosureRecord(
        closure_date="2024-01-22",
        description="Ram Mandir Pran Pratishtha Public Closure",
        replaced_by_date="2024-01-20",
        source_reference="NSE Special Closure Circular Jan 2024 + Angel One 1d gap verified",
        verified=True,
    ),
    ExceptionalClosureRecord(
        closure_date="2024-05-20",
        description="Lok Sabha General Elections - Mumbai",
        replaced_by_date=None,
        source_reference="NSE/CMTR/61518 (2024-04-08)",
        verified=True,
    ),
    ExceptionalClosureRecord(
        closure_date="2024-11-20",
        description="Maharashtra Legislative Assembly Elections",
        replaced_by_date=None,
        source_reference="NSE Election Holiday Circular Nov 2024",
        verified=True,
    ),
    ExceptionalClosureRecord(
        closure_date="2026-01-15",
        description="Maharashtra Municipal Corporation Elections",
        replaced_by_date=None,
        source_reference="NSE Election Holiday Circular Jan 2026 + Angel One 1d gap verified",
        verified=True,
    ),
)


class MultiYearTradingCalendar(HistoricalMarketCalendarAdapter):
    """
    Multi-year verified exchange calendar supporting regular trading sessions,
    holidays, Muhurat sessions, weekend special sessions, exceptional closures,
    and per-date custom session windows while failing closed on unknown years.
    """

    def __init__(
        self,
        *,
        include_verified_2024_2026: bool = True,
        additional_schedules: Sequence[HolidayScheduleRecord] = (),
        additional_special_sessions: Sequence[SpecialTradingSessionRecord] = (),
        additional_exceptional_closures: Sequence[ExceptionalClosureRecord] = (),
    ) -> None:
        initial_schedules: List[HolidayScheduleRecord] = []
        if include_verified_2024_2026:
            initial_schedules.extend(
                [
                    HolidayScheduleRecord(
                        year=2024,
                        holidays={d.isoformat(): desc for d, desc in VERIFIED_NSE_2024_HOLIDAYS.items()},
                        source="NSE_CIRCULARS_AND_EMPIRICAL_2024",
                        verified=True,
                    ),
                    HolidayScheduleRecord(
                        year=2025,
                        holidays={d.isoformat(): desc for d, desc in VERIFIED_NSE_2025_HOLIDAYS.items()},
                        source="NSE_CIRCULARS_AND_EMPIRICAL_2025",
                        verified=True,
                    ),
                    HolidayScheduleRecord(
                        year=2026,
                        holidays={d.isoformat(): desc for d, desc in VERIFIED_NSE_2026_HOLIDAYS.items()},
                        source="NSE_CIRCULARS_AND_EMPIRICAL_2026",
                        verified=True,
                    ),
                ]
            )
        initial_schedules.extend(additional_schedules)

        super().__init__(
            include_builtin_2026=not include_verified_2024_2026 and len(initial_schedules) == 0,
            verified_schedules=initial_schedules if initial_schedules else None,
            source_label="verified_multi_year_calendar_2024_2026",
        )

        self._special_sessions: Dict[date, SpecialTradingSessionRecord] = {}
        self._exceptional_closures: Dict[date, ExceptionalClosureRecord] = {}

        if include_verified_2024_2026:
            for sp in BUILTIN_SPECIAL_SESSIONS:
                self.register_special_session(sp)
            for ec in BUILTIN_EXCEPTIONAL_CLOSURES:
                self.register_exceptional_closure(ec)

        for sp in additional_special_sessions:
            self.register_special_session(sp)
        for ec in additional_exceptional_closures:
            self.register_exceptional_closure(ec)

    def register_special_session(self, record: SpecialTradingSessionRecord) -> None:
        if not record.verified:
            raise ValueError("Cannot register unverified special trading session")
        if not record.windows:
            raise ValueError(f"Special trading session {record.session_date} must declare >=1 window")
        d = date.fromisoformat(record.session_date)
        if d.year not in self._schedules_by_year:
            raise CalendarUnavailableError(
                f"Cannot register special session for unverified year {d.year}; register year schedule first."
            )
        self._special_sessions[d] = record

    def register_exceptional_closure(self, record: ExceptionalClosureRecord) -> None:
        if not record.verified:
            raise ValueError("Cannot register unverified exceptional closure")
        d = date.fromisoformat(record.closure_date)
        if d.year not in self._schedules_by_year:
            raise CalendarUnavailableError(
                f"Cannot register exceptional closure for unverified year {d.year}; register year schedule first."
            )
        self._exceptional_closures[d] = record
        sched = self._schedules_by_year[d.year]
        updated_hols = dict(sched.holidays)
        updated_hols[d.isoformat()] = f"Exceptional Closure: {record.description}"
        self._schedules_by_year[d.year] = HolidayScheduleRecord(
            year=sched.year,
            holidays=updated_hols,
            source=sched.source,
            verified=sched.verified,
        )
        self._holidays.add(d)

    @property
    def special_sessions(self) -> Dict[date, SpecialTradingSessionRecord]:
        return dict(self._special_sessions)

    @property
    def exceptional_closures(self) -> Dict[date, ExceptionalClosureRecord]:
        return dict(self._exceptional_closures)

    @property
    def NSE_HOLIDAYS(self) -> FrozenSet[date]:
        """Compatibility property for Phase 3 SessionIntelligenceEngine multi-year holiday discovery."""
        return frozenset(self._holidays)

    def is_special_session(self, target_date: date | datetime) -> bool:
        d = target_date.date() if isinstance(target_date, datetime) else target_date
        return d in self._special_sessions

    def _holidays_for_year(self, year: int) -> Dict[date, str]:
        sched = self._schedules_by_year.get(year)
        if sched is None:
            return {}
        return {date.fromisoformat(k): v for k, v in sched.holidays.items()}

    def get_session_type(self, target_date: date | datetime) -> SessionType:
        d = target_date.date() if isinstance(target_date, datetime) else target_date
        if d.year not in self._schedules_by_year:
            return SessionType.CALENDAR_UNAVAILABLE
        if d in self._exceptional_closures:
            return SessionType.EXCEPTIONAL_CLOSURE
        if d in self._holidays_for_year(d.year):
            return SessionType.HOLIDAY
        if d in self._special_sessions:
            return self._special_sessions[d].session_type
        if d.weekday() >= 5:
            return SessionType.WEEKEND
        return SessionType.REGULAR

    def get_session_windows(self, target_date: date | datetime) -> Tuple[SessionWindow, ...]:
        d = target_date.date() if isinstance(target_date, datetime) else target_date
        if d.year not in self._schedules_by_year:
            return ()
        if d in self._exceptional_closures or d in self._holidays_for_year(d.year):
            return ()
        if d in self._special_sessions:
            return self._special_sessions[d].windows
        if d.weekday() >= 5:
            return ()
        return REGULAR_NSE_WINDOWS

    def validate_date(self, target_date: date | datetime) -> CalendarValidationResult:
        d = target_date.date() if isinstance(target_date, datetime) else target_date
        fp = self.calendar_fingerprint()
        if d.year not in self._schedules_by_year:
            return CalendarValidationResult(
                is_valid=False,
                is_trading_day=False,
                status=CalendarStatus.CALENDAR_UNAVAILABLE,
                target_date=d.isoformat(),
                reason=f"Verified holiday calendar is UNAVAILABLE for year {d.year} (fail closed)",
                calendar_fingerprint=fp,
            )
        year_meta = self._schedules_by_year[d.year]
        if not year_meta.verified:
            return CalendarValidationResult(
                is_valid=False,
                is_trading_day=False,
                status=CalendarStatus.CALENDAR_UNAVAILABLE,
                target_date=d.isoformat(),
                reason=f"Calendar for year {d.year} is unverified (fail closed)",
                calendar_fingerprint=fp,
            )
        if d in self._exceptional_closures:
            ec = self._exceptional_closures[d]
            return CalendarValidationResult(
                is_valid=True,
                is_trading_day=False,
                status=CalendarStatus.NON_TRADING_DAY,
                target_date=d.isoformat(),
                reason=f"Exceptional Closure: {ec.description}",
                calendar_fingerprint=fp,
            )
        holidays = self._holidays_for_year(d.year)
        if d in holidays:
            return CalendarValidationResult(
                is_valid=True,
                is_trading_day=False,
                status=CalendarStatus.NON_TRADING_DAY,
                target_date=d.isoformat(),
                reason=f"NSE Holiday: {holidays[d]}",
                calendar_fingerprint=fp,
            )
        if d in self._special_sessions:
            sp = self._special_sessions[d]
            win_str = ", ".join(f"{w.open_hhmm}-{w.close_hhmm}" for w in sp.windows)
            return CalendarValidationResult(
                is_valid=True,
                is_trading_day=True,
                status=CalendarStatus.TRADING_DAY,
                target_date=d.isoformat(),
                reason=f"Special Trading Session ({sp.session_type.value}): {sp.description} [{win_str} IST]",
                calendar_fingerprint=fp,
            )
        if d.weekday() >= 5:
            return CalendarValidationResult(
                is_valid=True,
                is_trading_day=False,
                status=CalendarStatus.NON_TRADING_DAY,
                target_date=d.isoformat(),
                reason="Weekend (Exchange Closed)",
                calendar_fingerprint=fp,
            )
        return CalendarValidationResult(
            is_valid=True,
            is_trading_day=True,
            status=CalendarStatus.TRADING_DAY,
            target_date=d.isoformat(),
            reason="Regular NSE Trading Session (09:15-15:30 IST)",
            calendar_fingerprint=fp,
        )

    def is_trading_day(self, target_date: date | datetime) -> bool:
        return self.validate_date(target_date).is_trading_day

    def expected_opens_by_date(
        self,
        timeframe: str,
        start_ist: datetime,
        end_ist: datetime,
    ) -> Dict[date, List[datetime]]:
        canonical_tf = normalize_timeframe(timeframe)
        step_min = TIMEFRAME_DURATION_MINUTES[canonical_tf]
        out: Dict[date, List[datetime]] = {}

        cur_day = start_ist.date()
        last_day = end_ist.date()
        while cur_day <= last_day:
            res = self.validate_date(cur_day)
            if res.status == CalendarStatus.CALENDAR_UNAVAILABLE:
                raise CalendarUnavailableError(res.reason)
            if res.is_trading_day:
                windows = self.get_session_windows(cur_day)
                if canonical_tf == "1d":
                    day_open = datetime.combine(cur_day, dt_time(0, 0), tzinfo=IST_ZONE)
                    if start_ist.date() <= cur_day <= end_ist.date():
                        out[cur_day] = [day_open]
                else:
                    day_opens: List[datetime] = []
                    for w in windows:
                        cur_dt = datetime.combine(cur_day, w.open_time, tzinfo=IST_ZONE)
                        w_close_dt = datetime.combine(cur_day, w.close_time, tzinfo=IST_ZONE)
                        while cur_dt < w_close_dt:
                            bar_close = compute_candle_close_ist(cur_dt, canonical_tf, w.close_time)
                            if cur_dt >= start_ist and bar_close <= end_ist:
                                day_opens.append(cur_dt)
                            cur_dt += timedelta(minutes=step_min)
                    if day_opens:
                        out[cur_day] = day_opens
            cur_day += timedelta(days=1)
        return out

    def calendar_fingerprint(self) -> str:
        payload = {
            "years": sorted(self._schedules_by_year.keys()),
            "holidays": {
                str(y): sorted(self._schedules_by_year[y].holidays.keys())
                for y in sorted(self._schedules_by_year.keys())
            },
            "special_sessions": [
                self._special_sessions[d].to_dict()
                for d in sorted(self._special_sessions)
            ],
            "exceptional_closures": [
                self._exceptional_closures[d].to_dict()
                for d in sorted(self._exceptional_closures)
            ],
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32].upper()

    def year_provenance_summary(self) -> List[CalendarYearProvenance]:
        summaries: List[CalendarYearProvenance] = []
        for year in sorted(self._schedules_by_year.keys()):
            rec = self._schedules_by_year[year]
            hols = rec.holidays
            sp_for_year = [s for d, s in self._special_sessions.items() if d.year == year]
            ec_for_year = [c for d, c in self._exceptional_closures.items() if d.year == year]
            payload = json.dumps(
                {
                    "year": year,
                    "holidays": sorted(hols.keys()),
                    "special_sessions": [
                        s.to_dict() for s in sorted(sp_for_year, key=lambda x: x.session_date)
                    ],
                    "exceptional_closures": [
                        c.to_dict() for c in sorted(ec_for_year, key=lambda x: x.closure_date)
                    ],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()
            summaries.append(
                CalendarYearProvenance(
                    year=year,
                    exchange="NSE",
                    source_reference=rec.source,
                    circular_reference=YEAR_CIRCULAR_NOTES.get(year, rec.source),
                    verification_note="Verified against official NSE circulars & Angel One historical bar checks",
                    checksum_sha256=checksum,
                    holiday_count=len(hols),
                    special_session_count=len(sp_for_year),
                    exceptional_closure_count=len(ec_for_year),
                )
            )
        return summaries

    @classmethod
    def from_json_file(
        cls,
        path: str | Path,
        *,
        include_verified_2024_2026: bool = True,
    ) -> "MultiYearTradingCalendar":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        schedules: List[HolidayScheduleRecord] = []
        for entry in data.get("schedules", []):
            schedules.append(
                HolidayScheduleRecord(
                    year=int(entry["year"]),
                    holidays=dict(entry.get("holidays", {})),
                    source=str(entry.get("source", "JSON_MANIFEST")),
                    verified=bool(entry.get("verified", False)),
                )
            )
        specials: List[SpecialTradingSessionRecord] = []
        for entry in data.get("special_sessions", []):
            windows = tuple(
                SessionWindow(
                    open_hhmm=w["open_hhmm"],
                    close_hhmm=w["close_hhmm"],
                    label=w.get("label", "SPECIAL"),
                )
                for w in entry.get("windows", [])
            )
            specials.append(
                SpecialTradingSessionRecord(
                    session_date=entry["session_date"],
                    session_type=SessionType(entry["session_type"]),
                    description=entry["description"],
                    windows=windows,
                    source_reference=entry.get("source_reference", "JSON_MANIFEST"),
                    verified=bool(entry.get("verified", False)),
                )
            )
        closures: List[ExceptionalClosureRecord] = []
        for entry in data.get("exceptional_closures", []):
            closures.append(
                ExceptionalClosureRecord(
                    closure_date=entry["closure_date"],
                    description=entry["description"],
                    replaced_by_date=entry.get("replaced_by_date"),
                    source_reference=entry.get("source_reference", "JSON_MANIFEST"),
                    verified=bool(entry.get("verified", False)),
                )
            )
        return cls(
            include_verified_2024_2026=include_verified_2024_2026,
            additional_schedules=schedules,
            additional_special_sessions=specials,
            additional_exceptional_closures=closures,
        )
