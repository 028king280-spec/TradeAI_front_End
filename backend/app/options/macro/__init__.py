"""
AIVOLVE v3.0 — Macro and Event Intelligence Module (Engine 8 / Phase 6)
"""

from .macro_models import (
    MacroEventTier,
    EventScheduleType,
    EventLiveStatus,
    CalendarSourceType,
    ThresholdPolicyStatus,
    ProximityBand,
    MacroEventSource,
    MacroEvent,
    ProximityAssessment,
)
from .macro_calendar_store import MacroCalendarStore
from .macro_proximity_engine import MacroProximityEngine
from .macro_feed_adapter import (
    BaseMacroCalendarAdapter,
    ExternalMacroFeedAdapter,
    get_macro_feed_adapter,
)

__all__ = [
    "MacroEventTier",
    "EventScheduleType",
    "EventLiveStatus",
    "CalendarSourceType",
    "ThresholdPolicyStatus",
    "ProximityBand",
    "MacroEventSource",
    "MacroEvent",
    "ProximityAssessment",
    "MacroCalendarStore",
    "MacroProximityEngine",
    "BaseMacroCalendarAdapter",
    "ExternalMacroFeedAdapter",
    "get_macro_feed_adapter",
]
