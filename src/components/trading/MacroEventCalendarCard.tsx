'use client';

import React, { useState, useEffect } from 'react';
import {
  Calendar,
  AlertTriangle,
  Clock,
  ShieldCheck,
  ShieldAlert,
  Info,
  Globe,
  RefreshCw,
  ExternalLink,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { macroService } from '@/services/macroService';
import {
  MacroEventItem,
  MacroCalendarResponse,
  ProximityReport,
  MacroEventTier,
  ProximityBand,
} from '@/types/macro';

interface MacroEventCalendarCardProps {
  currentIndex?: string;
  className?: string;
}

export const MacroEventCalendarCard: React.FC<MacroEventCalendarCardProps> = ({
  currentIndex = 'NIFTY 50',
  className = '',
}) => {
  const [calendarData, setCalendarData] = useState<MacroCalendarResponse | null>(null);
  const [proximityReport, setProximityReport] = useState<ProximityReport | null>(null);
  const [activeTab, setActiveTab] = useState<'ALL' | 'TIER_1' | 'TIER_2'>('ALL');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);

  const loadData = async (refresh: boolean = false) => {
    if (refresh) setIsRefreshing(true);
    else setIsLoading(true);

    try {
      const [cal, prox] = await Promise.all([
        macroService.getCalendarEvents({ index: currentIndex }),
        macroService.getProximityReport(currentIndex),
      ]);
      setCalendarData(cal);
      setProximityReport(prox);
    } catch (err) {
      console.warn('Failed to load macro intelligence data:', err);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [currentIndex]);

  const filteredEvents = (calendarData?.events || []).filter((event) => {
    if (activeTab === 'TIER_1') return event.tier === 'TIER_1_CRITICAL';
    if (activeTab === 'TIER_2') return event.tier === 'TIER_2_HIGH';
    return true;
  });

  const getTierBadge = (tier: MacroEventTier) => {
    switch (tier) {
      case 'TIER_1_CRITICAL':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-red-500/10 text-red-400 border border-red-500/30">
            <ShieldAlert className="w-3 h-3 text-red-400" />
            Tier 1 Critical
          </span>
        );
      case 'TIER_2_HIGH':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-amber-500/10 text-amber-400 border border-amber-500/30">
            <AlertTriangle className="w-3 h-3 text-amber-400" />
            Tier 2 High
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider bg-blue-500/10 text-blue-400 border border-blue-500/30">
            <Info className="w-3 h-3 text-blue-400" />
            Tier 3 Medium
          </span>
        );
    }
  };

  const getBandBadge = (band: ProximityBand) => {
    switch (band) {
      case 'EVENT_IMMINENT_BLACKOUT':
        return {
          label: 'EVENT HORIZON ACTIVE (±15m Blackout Proposed)',
          color: 'bg-red-950/40 text-red-300 border-red-500/40',
          icon: ShieldAlert,
        };
      case 'PRE_EVENT_WARNING':
        return {
          label: 'PRE-EVENT WARNING HORIZON (T-60m Window Proposed)',
          color: 'bg-amber-950/40 text-amber-300 border-amber-500/40',
          icon: AlertTriangle,
        };
      case 'POST_EVENT_REALIGNMENT':
        return {
          label: 'POST-EVENT REALIGNMENT HORIZON (T+15m to T+60m)',
          color: 'bg-purple-950/40 text-purple-300 border-purple-500/40',
          icon: Clock,
        };
      case 'PRE_EVENT_WATCH':
        return {
          label: 'EVENT WATCH ACTIVE (Scheduled Later Today)',
          color: 'bg-blue-950/40 text-blue-300 border-blue-500/40',
          icon: Calendar,
        };
      default:
        return {
          label: 'DISTANT HORIZON (> 60m — No Active Event Overhang)',
          color: 'bg-emerald-950/30 text-emerald-300 border-emerald-500/30',
          icon: ShieldCheck,
        };
    }
  };

  const activeBandInfo = proximityReport
    ? getBandBadge(proximityReport.activeProximityBand)
    : getBandBadge('DISTANT');
  const BandIcon = activeBandInfo.icon;

  const nearest = proximityReport?.nearestCriticalEvent;

  return (
    <div
      className={`bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl text-slate-100 ${className}`}
    >
      {/* Header */}
      <div className="p-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3 bg-slate-900/90">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
            <Globe className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-base text-slate-100 tracking-tight">
                Macro & Event Intelligence
              </h3>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-mono uppercase bg-slate-800 text-slate-300 border border-slate-700">
                Engine 8
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Institutional Economic Calendar · Proximity Diagnostics ({currentIndex})
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-mono font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            28 Confirmed Events
          </span>
          <button
            onClick={() => loadData(true)}
            disabled={isRefreshing}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors disabled:opacity-50"
            title="Refresh Macro Data"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Proximity Radar Banner */}
      <div className="p-3 bg-slate-950/60 border-b border-slate-800/80">
        <div
          className={`p-3 rounded-lg border flex flex-col md:flex-row md:items-center justify-between gap-2.5 ${activeBandInfo.color}`}
        >
          <div className="flex items-center gap-2.5">
            <BandIcon className="w-5 h-5 shrink-0" />
            <div>
              <div className="text-xs font-bold uppercase tracking-wider">
                {activeBandInfo.label}
              </div>
              <div className="text-[11px] opacity-80 mt-0.5">
                {proximityReport?.diagnostics.summaryMessage ||
                  'No imminent high-impact macro releases in current window.'}
              </div>
            </div>
          </div>

          <div className="shrink-0 flex items-center gap-2">
            <span className="text-[10px] font-mono uppercase px-2 py-1 rounded bg-slate-900/80 text-amber-300 border border-amber-500/30">
              Policy: GOVERNANCE_PENDING (Informational Only)
            </span>
          </div>
        </div>
      </div>

      {/* Spotlight: Nearest Critical Event */}
      {nearest && (
        <div className="p-4 bg-slate-900/50 border-b border-slate-800">
          <div className="text-[11px] font-mono uppercase tracking-wider text-slate-400 mb-2 flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-indigo-400" />
            Nearest Critical Catalyst
          </div>
          <div className="bg-slate-950/80 border border-slate-800 rounded-lg p-3 flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold text-sm text-slate-200">{nearest.eventName}</span>
                {getTierBadge(nearest.eventTier)}
              </div>
              <div className="text-xs text-slate-400 mt-1 flex items-center gap-3 flex-wrap">
                <span>
                  Scheduled:{' '}
                  <strong className="text-slate-300 font-mono">
                    {new Date(nearest.scheduledTime).toLocaleString('en-IN', {
                      timeZone: 'Asia/Kolkata',
                      dateStyle: 'medium',
                      timeStyle: 'short',
                    })}
                  </strong>
                </span>
                <span>
                  Authority:{' '}
                  <strong className="text-slate-300 font-mono">Reserve Bank of India (RBI)</strong>
                </span>
              </div>
            </div>

            <div className="text-right shrink-0">
              <div className="text-xs text-slate-400">Time to Event</div>
              <div className="text-base font-bold font-mono text-indigo-300">
                {nearest.minutesToEvent > 0
                  ? `+${nearest.minutesToEvent.toFixed(1)} mins`
                  : `${nearest.minutesToEvent.toFixed(1)} mins`}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="px-4 pt-3 flex items-center justify-between border-b border-slate-800 bg-slate-900/40">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setActiveTab('ALL')}
            className={`pb-2.5 px-2 text-xs font-medium border-b-2 transition-colors ${
              activeTab === 'ALL'
                ? 'border-indigo-500 text-indigo-400 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            All Events ({calendarData?.stats.totalEvents || 0})
          </button>
          <button
            onClick={() => setActiveTab('TIER_1')}
            className={`pb-2.5 px-2 text-xs font-medium border-b-2 transition-colors ${
              activeTab === 'TIER_1'
                ? 'border-red-500 text-red-400 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            Tier 1 Critical ({calendarData?.stats.tierBreakdown?.TIER_1_CRITICAL || 0})
          </button>
          <button
            onClick={() => setActiveTab('TIER_2')}
            className={`pb-2.5 px-2 text-xs font-medium border-b-2 transition-colors ${
              activeTab === 'TIER_2'
                ? 'border-amber-500 text-amber-400 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            Tier 2 High ({calendarData?.stats.tierBreakdown?.TIER_2_HIGH || 0})
          </button>
        </div>

        <span className="text-[11px] text-slate-500 pb-2.5 font-mono">
          Showing {filteredEvents.length} events
        </span>
      </div>

      {/* Event List */}
      <div className="divide-y divide-slate-800/60 max-h-80 overflow-y-auto">
        {isLoading ? (
          <div className="p-8 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
            <RefreshCw className="w-4 h-4 animate-spin text-indigo-400" />
            Loading audited institutional calendar records...
          </div>
        ) : filteredEvents.length === 0 ? (
          <div className="p-8 text-center text-slate-500 text-xs">
            No events found for selected tier filter.
          </div>
        ) : (
          filteredEvents.map((event) => {
            const isExpanded = expandedEventId === event.eventId;
            const eventDate = new Date(event.scheduledTimeIst);

            return (
              <div
                key={event.eventId}
                className="p-3 hover:bg-slate-800/40 transition-colors text-xs"
              >
                <div
                  className="flex items-center justify-between gap-3 cursor-pointer"
                  onClick={() => setExpandedEventId(isExpanded ? null : event.eventId)}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="text-center shrink-0 w-12 py-1 rounded bg-slate-950 border border-slate-800 font-mono">
                      <div className="text-[9px] uppercase text-slate-400 font-bold">
                        {eventDate.toLocaleString('en-IN', { month: 'short' })}
                      </div>
                      <div className="text-sm font-bold text-slate-200">{eventDate.getDate()}</div>
                    </div>

                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-slate-200 truncate">{event.name}</span>
                        {getTierBadge(event.tier)}
                        {event.scheduleType === 'TENTATIVE' ? (
                          <span className="px-1.5 py-0.2 rounded text-[9px] font-mono bg-purple-500/10 text-purple-400 border border-purple-500/20">
                            Tentative
                          </span>
                        ) : (
                          <span className="px-1.5 py-0.2 rounded text-[9px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                            Confirmed
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-400 flex items-center gap-2 mt-0.5 font-mono">
                        <span>
                          {eventDate.toLocaleTimeString('en-IN', {
                            hour: '2-digit',
                            minute: '2-digit',
                            hour12: true,
                          })}{' '}
                          IST
                        </span>
                        <span>•</span>
                        <span className="text-indigo-400">{event.source.authority}</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-[10px] font-mono text-slate-500">
                      {event.eventId.split('-')[0]}
                    </span>
                    {isExpanded ? (
                      <ChevronUp className="w-4 h-4 text-slate-400" />
                    ) : (
                      <ChevronDown className="w-4 h-4 text-slate-400" />
                    )}
                  </div>
                </div>

                {isExpanded && (
                  <div className="mt-3 pt-3 border-t border-slate-800/80 pl-14 pr-2 text-[11px] text-slate-300 space-y-2">
                    <p className="text-slate-300 leading-relaxed">
                      {event.description || 'Institutional macroeconomic announcement.'}
                    </p>
                    <div className="flex items-center gap-4 text-[10px] text-slate-400 flex-wrap">
                      <span>
                        Source Type:{' '}
                        <strong className="text-slate-300 font-mono">
                          {event.source.sourceType}
                        </strong>
                      </span>
                      <span>
                        Timezone:{' '}
                        <strong className="text-slate-300 font-mono">{event.timezone}</strong>
                      </span>
                      {event.source.referenceUrl && (
                        <a
                          href={event.source.referenceUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-indigo-400 hover:text-indigo-300 underline"
                        >
                          Source Gazette
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Institutional Disclaimer Footer */}
      <div className="p-3 bg-slate-950 border-t border-slate-800 text-[10px] text-slate-400 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-1.5">
          <Info className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <span>
            Verified institutional provenance from RBI, MOSPI & Federal Reserve.
            Blackout/scaling thresholds remain GOVERNANCE_PENDING.
          </span>
        </div>
        <div className="font-mono text-slate-400">STRICTLY PAPER_TRADING_ONLY</div>
      </div>
    </div>
  );
};

