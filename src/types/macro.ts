/**
 * AIVOLVE v3.0 — Macro & Event Intelligence TypeScript Definitions (REQ-6.11)
 * Part of Phase 6: Macro, Event & Overnight Drift Engine (Engine 8)
 */

export type MacroEventTier = 'TIER_1_CRITICAL' | 'TIER_2_HIGH' | 'TIER_3_MEDIUM';

export type EventScheduleType = 'CONFIRMED' | 'TENTATIVE';

export type EventLiveStatus = 'SCHEDULED' | 'AWAITING_RELEASE' | 'RELEASED' | 'DELAYED' | 'CANCELLED';

export type CalendarSourceType =
  | 'RBI_OFFICIAL'
  | 'MOSPI_OFFICIAL'
  | 'FED_OFFICIAL'
  | 'GOVT_GAZETTE'
  | 'MANUAL_UNVERIFIED';

export type ThresholdPolicyStatus = 'UNCONFIGURED' | 'GOVERNANCE_PENDING' | 'APPROVED';

export type ProximityBand =
  | 'DISTANT'
  | 'PRE_EVENT_WATCH'
  | 'PRE_EVENT_WARNING'
  | 'EVENT_IMMINENT_BLACKOUT'
  | 'POST_EVENT_REALIGNMENT';

export interface MacroEventSourceItem {
  authority: string;
  sourceType: CalendarSourceType;
  referenceUrl?: string | null;
  verifiedAt?: string | null;
}

export interface MacroEventItem {
  eventId: string;
  name: string;
  tier: MacroEventTier;
  scheduledTime: string;
  scheduledTimeIst: string;
  timezone: string;
  source: MacroEventSourceItem;
  scheduleType: EventScheduleType;
  liveStatus: EventLiveStatus;
  affectedIndices: string[];
  description?: string | null;
  actualValue?: string | null;
  consensusValue?: string | null;
  previousValue?: string | null;
}

export interface ProximityAssessmentItem {
  eventId: string;
  eventName: string;
  eventTier: MacroEventTier;
  asOfTime: string;
  scheduledTime: string;
  minutesToEvent: number;
  proximityBand: ProximityBand;
  policyStatus: ThresholdPolicyStatus;
  diagnostics: {
    isBlackoutProposed: boolean;
    isWarningProposed: boolean;
    diagnosticMessage: string;
  };
  governanceGuards: {
    tradingOverrideActive: boolean;
    positionScalingFactor: number;
  };
}

export interface MacroCalendarStats {
  version: string;
  totalEvents: number;
  confirmedEvents: number;
  tentativeEvents: number;
  tierBreakdown: Record<string, number>;
  policyStatus: string;
}

export interface MacroCalendarResponse {
  events: MacroEventItem[];
  stats: MacroCalendarStats;
  governancePolicy: Record<string, any>;
  count: number;
}

export interface ProximityReport {
  asOf: string;
  targetIndex: string;
  activeProximityBand: ProximityBand;
  policyStatus: ThresholdPolicyStatus;
  governanceGuards: {
    tradingOverrideActive: boolean;
    positionScalingFactor: number;
    policyApprovalRequired: boolean;
  };
  diagnostics: {
    hasProposedBlackout: boolean;
    hasProposedWarning: boolean;
    summaryMessage: string;
    eventsAssessedCount: number;
  };
  nearestCriticalEvent?: ProximityAssessmentItem | null;
  activeAssessments: ProximityAssessmentItem[];
}

export interface MacroFeedStatus {
  connection: {
    provider: string;
    status: string;
    credentialsStatus: string;
    isLive: boolean;
    message: string;
    timestamp: string;
  };
  adapter: {
    provider: string;
    isConfigured: boolean;
    isAuthenticated: boolean;
    baseUrl: string;
    lastSyncTime: string | null;
    lastError: string | null;
    failClosedPolicy: string;
  };
}

