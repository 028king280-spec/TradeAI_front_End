"""
AIVOLVE v3.0 — Deterministic Macro Proximity Engine (REQ-6.3)
Part of Phase 6: Macro, Event & Overnight Drift Engine (Engine 8)

Calculates deterministic time distance between decision time and scheduled
institutional events. 

SAFETY GOVERNANCE INVARIANT:
Thresholds (±15m blackout, T-60 to T-15m warning, 50% position scaling) remain
GOVERNANCE_PENDING and are NEVER activated in live execution.
All trading overrides remain FALSE and position scaling remains 1.0 (no reduction).
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import zoneinfo

from .macro_models import (
    MacroEvent,
    MacroEventTier,
    ProximityBand,
    ThresholdPolicyStatus,
    ProximityAssessment,
)
from .macro_calendar_store import MacroCalendarStore

logger = logging.getLogger(__name__)


class MacroProximityEngine:
    """
    Deterministic mathematical engine evaluating time proximity to macroeconomic events.
    """

    def __init__(self, calendar_store: Optional[MacroCalendarStore] = None):
        self._calendar_store = calendar_store or MacroCalendarStore.get_instance()

    def assess_event(self, event: MacroEvent, as_of: datetime) -> ProximityAssessment:
        """
        Assesses time proximity between a single event and as_of timestamp.
        Calculates Delta t in minutes: (T_event - as_of)
        """
        # Ensure as_of is timezone-aware
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=zoneinfo.ZoneInfo("Asia/Kolkata"))

        # Calculate time delta in minutes
        time_diff = event.scheduled_time - as_of
        minutes_to_event = time_diff.total_seconds() / 60.0

        # Classify Proximity Band (Proposed Mathematical Definitions)
        # Note: Thresholds are for informational/diagnostic classification only.
        is_tier_1 = (event.tier == MacroEventTier.TIER_1_CRITICAL)
        is_blackout = False
        is_warning = False

        if -15.0 <= minutes_to_event <= 15.0:
            band = ProximityBand.EVENT_IMMINENT_BLACKOUT
            is_blackout = is_tier_1
            diag = f"[DIAGNOSTIC] Event '{event.name}' is within ±15m blackout horizon (Delta t = {minutes_to_event:+.1f}m)."
        elif 15.0 < minutes_to_event <= 60.0:
            band = ProximityBand.PRE_EVENT_WARNING
            is_warning = is_tier_1
            diag = f"[DIAGNOSTIC] Event '{event.name}' is within T-60m warning window (Delta t = +{minutes_to_event:.1f}m)."
        elif -60.0 <= minutes_to_event < -15.0:
            band = ProximityBand.POST_EVENT_REALIGNMENT
            diag = f"[DIAGNOSTIC] Event '{event.name}' in post-event realignment window (Delta t = {minutes_to_event:.1f}m)."
        elif 60.0 < minutes_to_event <= 1440.0:
            band = ProximityBand.PRE_EVENT_WATCH
            diag = f"[DIAGNOSTIC] Event '{event.name}' scheduled later today (Delta t = +{minutes_to_event / 60.0:.1f}h)."
        else:
            band = ProximityBand.DISTANT
            diag = f"Event '{event.name}' is distant from decision horizon."

        # STRICT GOVERNANCE POLICY:
        # Trading overrides and scaling are strictly inactive (False and 1.0)
        return ProximityAssessment(
            event=event,
            as_of_time=as_of,
            minutes_to_event=minutes_to_event,
            proximity_band=band,
            policy_status=ThresholdPolicyStatus.GOVERNANCE_PENDING,
            is_blackout_proposed=is_blackout,
            is_warning_proposed=is_warning,
            trading_override_active=False,      # FORCED FALSE
            position_scaling_factor=1.0,         # FORCED 1.0 (NO SCALING)
            diagnostic_message=diag,
        )

    def evaluate_proximity(
        self,
        as_of: Optional[datetime] = None,
        index: Optional[str] = None,
        lookback_minutes: float = 60.0,
        lookforward_minutes: float = 240.0
    ) -> Dict[str, Any]:
        """
        Scans all calendar events within the active evaluation horizon [as_of - lookback, as_of + lookforward].
        Returns diagnostic proximity summary and nearest critical event assessment.
        """
        if as_of is None:
            as_of = datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata"))
        elif as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=zoneinfo.ZoneInfo("Asia/Kolkata"))

        from datetime import timedelta
        start_time = as_of - timedelta(minutes=lookback_minutes)
        end_time = as_of + timedelta(minutes=lookforward_minutes)

        candidates = self._calendar_store.get_events(
            start_time=start_time,
            end_time=end_time,
            index=index
        )

        assessments: List[ProximityAssessment] = []
        for event in candidates:
            assessment = self.assess_event(event, as_of)
            assessments.append(assessment)

        # Sort assessments by absolute distance to decision time
        assessments.sort(key=lambda a: abs(a.minutes_to_event))

        # Identify nearest critical/high tier event
        nearest_tier1 = next((a for a in assessments if a.event.tier == MacroEventTier.TIER_1_CRITICAL), None)
        nearest_any = assessments[0] if assessments else None

        active_band = ProximityBand.DISTANT
        has_proposed_blackout = False
        has_proposed_warning = False

        if nearest_tier1:
            active_band = nearest_tier1.proximity_band
            has_proposed_blackout = nearest_tier1.is_blackout_proposed
            has_proposed_warning = nearest_tier1.is_warning_proposed

        summary_msg = "No proximate macro events within active monitoring horizon."
        if nearest_tier1:
            summary_msg = (
                f"Nearest Tier 1 Event: '{nearest_tier1.event.name}' "
                f"at {nearest_tier1.event.scheduled_time_ist().strftime('%H:%M:%S IST')} "
                f"(Delta t: {nearest_tier1.minutes_to_event:+.1f}m, Band: {active_band.value}). "
                f"Policy: GOVERNANCE_PENDING (No live trading halt active)."
            )
        elif nearest_any:
            summary_msg = (
                f"Nearest Event: '{nearest_any.event.name}' ({nearest_any.event.tier.value}) "
                f"(Delta t: {nearest_any.minutes_to_event:+.1f}m)."
            )

        return {
            "asOf": as_of.isoformat(),
            "targetIndex": index or "ALL_SUPPORTED",
            "activeProximityBand": active_band.value,
            "policyStatus": ThresholdPolicyStatus.GOVERNANCE_PENDING.value,
            "governanceGuards": {
                "tradingOverrideActive": False,
                "positionScalingFactor": 1.0,
                "policyApprovalRequired": True,
            },
            "diagnostics": {
                "hasProposedBlackout": has_proposed_blackout,
                "hasProposedWarning": has_proposed_warning,
                "summaryMessage": summary_msg,
                "eventsAssessedCount": len(assessments),
            },
            "nearestCriticalEvent": nearest_tier1.to_dict() if nearest_tier1 else None,
            "activeAssessments": [a.to_dict() for a in assessments],
        }

