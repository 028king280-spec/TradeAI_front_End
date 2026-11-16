"""
AIVOLVE v3.0 — Macro Calendar Store (REQ-6.2)
Part of Phase 6: Macro, Event & Overnight Drift Engine (Engine 8)

Thread-safe repository providing validated access to institutional macroeconomic
calendar data, enforcing provenance attribution and timezone normalization.
"""

import json
import logging
import threading
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import zoneinfo

from .macro_models import (
    MacroEvent,
    MacroEventSource,
    MacroEventTier,
    EventScheduleType,
    EventLiveStatus,
    CalendarSourceType,
    ThresholdPolicyStatus,
)

logger = logging.getLogger(__name__)


class MacroCalendarStore:
    _instance: Optional["MacroCalendarStore"] = None
    _lock = threading.Lock()

    def __init__(self, calendar_path: Optional[str] = None):
        if calendar_path is None:
            self._calendar_path = Path(__file__).resolve().parent.parent.parent / "data" / "macro_calendar.json"
        else:
            self._calendar_path = Path(calendar_path)

        self._events: List[MacroEvent] = []
        self._events_by_id: Dict[str, MacroEvent] = {}
        self._version: str = "1.0.0"
        self._last_updated: str = ""
        self._policy_metadata: Dict[str, Any] = {}
        self._load_lock = threading.RLock()
        self.reload()

    @classmethod
    def get_instance(cls, calendar_path: Optional[str] = None) -> "MacroCalendarStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(calendar_path)
            return cls._instance

    def reload(self) -> None:
        """Loads and strictly validates calendar JSON into memory."""
        with self._load_lock:
            if not self._calendar_path.exists():
                logger.warning(f"Macro calendar file not found at {self._calendar_path}; initializing empty.")
                self._events = []
                self._events_by_id = {}
                return

            try:
                with open(self._calendar_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                self._version = data.get("version", "1.0.0")
                self._last_updated = data.get("lastUpdated", "")
                self._policy_metadata = data.get("governancePolicy", {
                    "status": ThresholdPolicyStatus.GOVERNANCE_PENDING.value,
                    "approvalStatus": "UNAPPROVED_INFORMATIONAL_ONLY"
                })

                parsed_events: List[MacroEvent] = []
                by_id: Dict[str, MacroEvent] = {}

                for raw in data.get("events", []):
                    # Parse scheduled_time and ensure timezone-awareness
                    sched_str = raw["scheduledTime"]
                    dt = datetime.fromisoformat(sched_str)
                    if dt.tzinfo is None:
                        # If naive in raw JSON, assume Asia/Kolkata
                        dt = dt.replace(tzinfo=zoneinfo.ZoneInfo("Asia/Kolkata"))

                    src_raw = raw.get("source", {})
                    source = MacroEventSource(
                        authority=src_raw.get("authority", "UNKNOWN"),
                        source_type=CalendarSourceType(src_raw.get("sourceType", CalendarSourceType.MANUAL_UNVERIFIED.value)),
                        reference_url=src_raw.get("referenceUrl"),
                        verified_at=src_raw.get("verifiedAt")
                    )

                    event = MacroEvent(
                        event_id=raw["eventId"],
                        name=raw["name"],
                        tier=MacroEventTier(raw["tier"]),
                        scheduled_time=dt,
                        timezone_name=raw.get("timezone", "Asia/Kolkata"),
                        source=source,
                        schedule_type=EventScheduleType(raw.get("scheduleType", EventScheduleType.CONFIRMED.value)),
                        live_status=EventLiveStatus(raw.get("liveStatus", EventLiveStatus.SCHEDULED.value)),
                        affected_indices=raw.get("affectedIndices", ["NIFTY 50", "BANK NIFTY", "FINNIFTY"]),
                        description=raw.get("description"),
                        actual_value=raw.get("actualValue"),
                        consensus_value=raw.get("consensusValue"),
                        previous_value=raw.get("previousValue"),
                    )

                    parsed_events.append(event)
                    by_id[event.event_id] = event

                # Sort chronologically by scheduled_time
                parsed_events.sort(key=lambda e: e.scheduled_time)
                self._events = parsed_events
                self._events_by_id = by_id
                logger.info(f"Loaded {len(self._events)} macro calendar events from {self._calendar_path}")

            except Exception as e:
                logger.error(f"Failed to load macro calendar from {self._calendar_path}: {e}", exc_info=True)
                raise

    def get_event_by_id(self, event_id: str) -> Optional[MacroEvent]:
        with self._load_lock:
            return self._events_by_id.get(event_id)

    def get_all_events(self) -> List[MacroEvent]:
        with self._load_lock:
            return list(self._events)

    def get_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        tier: Optional[MacroEventTier] = None,
        index: Optional[str] = None
    ) -> List[MacroEvent]:
        """
        Retrieves calendar events filtered by time window, tier, and affected index.
        """
        with self._load_lock:
            filtered = self._events

            if start_time is not None:
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)
                filtered = [e for e in filtered if e.scheduled_time >= start_time]

            if end_time is not None:
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=timezone.utc)
                filtered = [e for e in filtered if e.scheduled_time <= end_time]

            if tier is not None:
                filtered = [e for e in filtered if e.tier == tier]

            if index is not None:
                clean_index = index.upper().strip()
                filtered = [e for e in filtered if clean_index in [idx.upper().strip() for idx in e.affected_indices]]

            return list(filtered)

    def get_upcoming_events(
        self,
        as_of: datetime,
        lookforward_minutes: float = 1440.0,
        tier: Optional[MacroEventTier] = None,
        index: Optional[str] = None
    ) -> List[MacroEvent]:
        """
        Returns events scheduled between as_of and as_of + lookforward_minutes.
        """
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=zoneinfo.ZoneInfo("Asia/Kolkata"))

        end_time = as_of + datetime.resolution * int(lookforward_minutes * 60 * 1_000_000)
        # Or standard timedelta:
        from datetime import timedelta
        end_time = as_of + timedelta(minutes=lookforward_minutes)

        return self.get_events(start_time=as_of, end_time=end_time, tier=tier, index=index)

    def get_governance_policy(self) -> Dict[str, Any]:
        """Returns policy threshold status metadata."""
        with self._load_lock:
            return dict(self._policy_metadata)

    def get_calendar_stats(self) -> Dict[str, Any]:
        """Summary statistics of stored calendar entries."""
        with self._load_lock:
            tier_counts = {t.value: 0 for t in MacroEventTier}
            confirmed_count = 0
            tentative_count = 0

            for e in self._events:
                tier_counts[e.tier.value] = tier_counts.get(e.tier.value, 0) + 1
                if e.schedule_type == EventScheduleType.CONFIRMED:
                    confirmed_count += 1
                else:
                    tentative_count += 1

            return {
                "version": self._version,
                "totalEvents": len(self._events),
                "confirmedEvents": confirmed_count,
                "tentativeEvents": tentative_count,
                "tierBreakdown": tier_counts,
                "policyStatus": self._policy_metadata.get("status", ThresholdPolicyStatus.GOVERNANCE_PENDING.value),
            }

