"""
AIVOLVE v3.0 — Macro Event Data Models (REQ-6.1)
Part of Phase 6: Macro, Event & Overnight Drift Engine (Engine 8)

Strictly adheres to:
- Timezone awareness (Asia/Kolkata normalization)
- Provenance tracking (official publication source metadata)
- Policy threshold governance (unapproved blackout & sizing flags remain GOVERNANCE_PENDING)
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import zoneinfo
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MacroEventTier(str, Enum):
    TIER_1_CRITICAL = "TIER_1_CRITICAL"   # RBI MPC, Union Budget, US FOMC Rate Decision
    TIER_2_HIGH = "TIER_2_HIGH"           # India CPI, India GDP, US CPI, US NFP
    TIER_3_MEDIUM = "TIER_3_MEDIUM"       # India IIP, WPI, Trade Balance, PMI


class EventScheduleType(str, Enum):
    CONFIRMED = "CONFIRMED"               # Official release calendar gazetted
    TENTATIVE = "TENTATIVE"               # Scheduled convention (e.g. Budget before gazette)


class EventLiveStatus(str, Enum):
    SCHEDULED = "SCHEDULED"               # Awaiting scheduled release time
    AWAITING_RELEASE = "AWAITING_RELEASE" # Within proximate release window
    RELEASED = "RELEASED"                 # Official data published and observed
    DELAYED = "DELAYED"                   # Release time breached without official publication
    CANCELLED = "CANCELLED"               # Authority cancelled or rescheduled release


class CalendarSourceType(str, Enum):
    RBI_OFFICIAL = "RBI_OFFICIAL"         # Reserve Bank of India official press releases
    MOSPI_OFFICIAL = "MOSPI_OFFICIAL"     # Ministry of Statistics & Programme Implementation
    FED_OFFICIAL = "FED_OFFICIAL"         # US Federal Reserve official releases
    GOVT_GAZETTE = "GOVT_GAZETTE"         # Government of India official gazette / notification
    MANUAL_UNVERIFIED = "MANUAL_UNVERIFIED" # Unverified or test records


class ThresholdPolicyStatus(str, Enum):
    UNCONFIGURED = "UNCONFIGURED"         # Threshold has not been defined
    GOVERNANCE_PENDING = "GOVERNANCE_PENDING" # Proposed threshold pending explicit authorization
    APPROVED = "APPROVED"                 # Formally approved and active for live execution gating


class ProximityBand(str, Enum):
    DISTANT = "DISTANT"                               # Outside warning and blackout horizons (> 60m)
    PRE_EVENT_WATCH = "PRE_EVENT_WATCH"               # Event on current session calendar (> 60m)
    PRE_EVENT_WARNING = "PRE_EVENT_WARNING"           # Inside warning window (T-60m to T-15m)
    EVENT_IMMINENT_BLACKOUT = "EVENT_IMMINENT_BLACKOUT" # Inside blackout window (±15m)
    POST_EVENT_REALIGNMENT = "POST_EVENT_REALIGNMENT" # Post-event volatility cooloff (T+15m to T+60m)


class MacroEventSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    authority: str
    source_type: CalendarSourceType
    reference_url: Optional[str] = None
    verified_at: Optional[str] = None     # ISO 8601 string of verification date


class MacroEvent(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    event_id: str
    name: str
    tier: MacroEventTier
    scheduled_time: datetime
    timezone_name: str = "Asia/Kolkata"
    source: MacroEventSource
    schedule_type: EventScheduleType = EventScheduleType.CONFIRMED
    live_status: EventLiveStatus = EventLiveStatus.SCHEDULED
    affected_indices: List[str] = Field(default_factory=lambda: ["NIFTY 50", "BANK NIFTY", "FINNIFTY"])
    description: Optional[str] = None
    actual_value: Optional[str] = None
    consensus_value: Optional[str] = None
    previous_value: Optional[str] = None

    @field_validator("scheduled_time")
    @classmethod
    def validate_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError(f"scheduled_time must be timezone-aware, got naive: {v}")
        return v

    def scheduled_time_ist(self) -> datetime:
        """Returns scheduled time converted to Asia/Kolkata timezone."""
        try:
            ist_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
        except Exception:
            ist_tz = timezone.utc  # Fallback only if zoneinfo data missing
        return self.scheduled_time.astimezone(ist_tz)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eventId": self.event_id,
            "name": self.name,
            "tier": self.tier.value,
            "scheduledTime": self.scheduled_time.isoformat(),
            "scheduledTimeIst": self.scheduled_time_ist().isoformat(),
            "timezone": self.timezone_name,
            "source": {
                "authority": self.source.authority,
                "sourceType": self.source.source_type.value,
                "referenceUrl": self.source.reference_url,
                "verifiedAt": self.source.verified_at,
            },
            "scheduleType": self.schedule_type.value,
            "liveStatus": self.live_status.value,
            "affectedIndices": self.affected_indices,
            "description": self.description,
            "actualValue": self.actual_value,
            "consensusValue": self.consensus_value,
            "previousValue": self.previous_value,
        }


class ProximityAssessment(BaseModel):
    """
    Mathematical assessment of an event's time proximity relative to decision time.
    
    SAFETY INVARIANT:
    All trading actions (trading_override_active, position_scaling_factor) must respect
    threshold policy governance. If policy_status is GOVERNANCE_PENDING or UNCONFIGURED,
    trading_override_active is forced to False and position_scaling_factor is forced to 1.0.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    event: MacroEvent
    as_of_time: datetime
    minutes_to_event: float                       # Positive: event in future; Negative: event in past
    proximity_band: ProximityBand
    policy_status: ThresholdPolicyStatus = ThresholdPolicyStatus.GOVERNANCE_PENDING
    
    # Proposed diagnostic flags (Informational only — unapproved for live execution)
    is_blackout_proposed: bool = False
    is_warning_proposed: bool = False
    
    # Active execution gates (Must remain inactive until policy approval)
    trading_override_active: bool = False         # Forces WAIT / NO_TRADE if True
    position_scaling_factor: float = 1.0          # Multiplied against base lots (1.0 = no reduction)
    diagnostic_message: str = ""

    @model_validator(mode="after")
    def enforce_policy_governance_invariant(self) -> "ProximityAssessment":
        # Unless policy status is explicitly APPROVED, live trading behavior cannot be altered.
        if self.policy_status != ThresholdPolicyStatus.APPROVED:
            if self.trading_override_active:
                # Disarm override: policy not approved
                object.__setattr__(self, "trading_override_active", False)
            if self.position_scaling_factor != 1.0:
                # Disarm position reduction: policy not approved
                object.__setattr__(self, "position_scaling_factor", 1.0)
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eventId": self.event.event_id,
            "eventName": self.event.name,
            "eventTier": self.event.tier.value,
            "asOfTime": self.as_of_time.isoformat(),
            "scheduledTime": self.event.scheduled_time_ist().isoformat(),
            "minutesToEvent": round(self.minutes_to_event, 2),
            "proximityBand": self.proximity_band.value,
            "policyStatus": self.policy_status.value,
            "diagnostics": {
                "isBlackoutProposed": self.is_blackout_proposed,
                "isWarningProposed": self.is_warning_proposed,
                "diagnosticMessage": self.diagnostic_message,
            },
            "governanceGuards": {
                "tradingOverrideActive": self.trading_override_active,
                "positionScalingFactor": self.position_scaling_factor,
            }
        }

