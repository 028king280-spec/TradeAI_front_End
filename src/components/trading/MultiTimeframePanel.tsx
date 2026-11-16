'use client';

import React from 'react';
import { Compass, Clock, Layers, Activity, AlertOctagon } from 'lucide-react';

export interface TimeframeDetails {
  timeframe: string;
  bias: string;
  marketDirection?: string;
  externalStructure?: string;
  internalStructure?: string;
  majorSwingHigh?: number;
  majorSwingLow?: number;
  lastBos?: any;
  lastChoch?: any;
  displacementConfirmed?: boolean;
  entryStatus?: string;
  invalidationLevel?: number;
  reasoning?: string;
  classifiedPoints?: Array<{ label: string; price: number; type: string }>;
}

export interface MultiTimeframeData {
  classification: string;
  overallAlignment: string;
  headline: string;
  isTradeable: boolean;
  confluenceScore: number;
  reasoning15m?: string;
  reasoning5m?: string;
  reasoning1m?: string;
  overallReasoning?: string;
  timeframe15m?: TimeframeDetails;
  timeframe5m?: TimeframeDetails;
  timeframe1m?: TimeframeDetails;
}

interface MultiTimeframePanelProps {
  data?: MultiTimeframeData | null;
  currentPrice?: number;
}

export const MultiTimeframePanel: React.FC<MultiTimeframePanelProps> = ({
  data,
  currentPrice = 24500.0,
}) => {
  if (!data) {
    return (
      <div className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-xl p-5 text-center text-[var(--text-secondary)]">
        <Clock className="w-6 h-6 mx-auto mb-2 text-[var(--text-muted)] animate-spin" />
        <p className="text-xs">Loading multi-timeframe confluence analysis...</p>
      </div>
    );
  }

  const alignment = data.overallAlignment || data.classification || 'No Clear Bias';
  const isConflict = alignment === 'Mixed / Conflicting' || !data.isTradeable;

  const stateColors: Record<string, { bg: string; text: string; border: string }> = {
    'Strong Bullish Alignment': { bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/40' },
    'Bullish Alignment': { bg: 'bg-emerald-500/15', text: 'text-emerald-400', border: 'border-emerald-500/30' },
    'Strong Bearish Alignment': { bg: 'bg-rose-500/20', text: 'text-rose-400', border: 'border-rose-500/40' },
    'Bearish Alignment': { bg: 'bg-rose-500/15', text: 'text-rose-400', border: 'border-rose-500/30' },
    'Mixed / Conflicting': { bg: 'bg-amber-500/20', text: 'text-amber-400', border: 'border-amber-500/40' },
    'No Clear Bias': { bg: 'bg-[var(--bg-surface-elevated)]', text: 'text-[var(--text-secondary)]', border: 'border-[var(--border-subtle)]' },
  };

  const style = stateColors[alignment] || stateColors['No Clear Bias'];

  return (
    <div className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-xl p-5 shadow-xl text-[var(--text-primary)]">
      {/* Top Confluence State Badge */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-[var(--accent-blue)]/20 text-[var(--accent-blue)] border border-[var(--accent-blue)]/30 rounded-lg">
            <Compass className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-[var(--text-primary)] tracking-tight">
                Multi-Timeframe Confluence Engine
              </h3>
              <span className={`px-2.5 py-0.5 rounded text-xs font-semibold uppercase tracking-wider border ${style.bg} ${style.text} ${style.border}`}>
                {alignment}
              </span>
            </div>
            <p className="text-xs text-[var(--text-secondary)] mt-0.5">
              Coordinated institutional synchronization across 15M (Macro), 5M (Structure), and 1M (Execution)
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <div className="text-right">
            <span className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wider font-semibold block">
              Confluence Score
            </span>
            <span className={`text-xl font-semibold ${data.confluenceScore >= 70 ? 'text-emerald-400' : data.confluenceScore <= 40 ? 'text-rose-400' : 'text-amber-400'}`}>
              {data.confluenceScore}
              <span className="text-xs font-normal text-[var(--text-secondary)]"> / 100</span>
            </span>
          </div>
        </div>
      </div>

      {/* Lockout Warning Banner if Conflicting or Untradeable */}
      {isConflict && (
        <div className="mt-4 p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg flex items-start gap-2.5 text-xs text-amber-300">
          <AlertOctagon className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <span className="font-bold block uppercase tracking-wide">
              {data.headline || 'TIMEFRAME CONFLICT — DIRECTIONAL LOCKOUT ACTIVE'}
            </span>
            <p className="mt-0.5 text-[var(--text-secondary)] leading-relaxed">
              {data.overallReasoning || 'Evidence diverges across timeframes. Institutional SMC rule: Never force a bullish or bearish conclusion when macro direction and execution structure conflict.'}
            </p>
          </div>
        </div>
      )}

      {/* 3 Coordinated Timeframe Cards */}
      <div className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* 15-Minute: Macro Direction & External Structure */}
        <div className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-lg p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-2 border-b border-[var(--border-subtle)] mb-3">
              <span className="text-xs font-semibold text-[var(--text-secondary)] flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
                15M: Macro Direction
              </span>
              <span className={`text-[10px] px-2 py-0.5 font-semibold uppercase rounded ${
                data.timeframe15m?.bias === 'BULLISH'
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : data.timeframe15m?.bias === 'BEARISH'
                  ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                  : 'bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)]'
              }`}>
                {data.timeframe15m?.bias || 'NEUTRAL'}
              </span>
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">External Structure:</span>
                <span className="font-semibold text-[var(--text-primary)]">
                  {data.timeframe15m?.marketDirection || data.timeframe15m?.externalStructure || 'Range-Bound'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Dealing High:</span>
                <span className="tabular-nums text-emerald-400">
                  ₹{data.timeframe15m?.majorSwingHigh ? data.timeframe15m.majorSwingHigh.toLocaleString('en-IN') : 'N/A'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Dealing Low:</span>
                <span className="tabular-nums text-rose-400">
                  ₹{data.timeframe15m?.majorSwingLow ? data.timeframe15m.majorSwingLow.toLocaleString('en-IN') : 'N/A'}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-[var(--border-subtle)] text-[11px] text-[var(--text-secondary)] leading-relaxed italic">
            {data.reasoning15m || '15M macro trend establishing primary dealing boundaries.'}
          </div>
        </div>

        {/* 5-Minute: Internal Execution & BOS/CHoCH */}
        <div className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-lg p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-2 border-b border-[var(--border-subtle)] mb-3">
              <span className="text-xs font-semibold text-[var(--text-secondary)] flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
                5M: Execution Structure
              </span>
              <span className={`text-[10px] px-2 py-0.5 font-semibold uppercase rounded ${
                data.timeframe5m?.bias === 'BULLISH'
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : data.timeframe5m?.bias === 'BEARISH'
                  ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                  : 'bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)]'
              }`}>
                {data.timeframe5m?.bias || 'NEUTRAL'}
              </span>
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Last BOS / CHoCH:</span>
                <span className="font-semibold text-[var(--text-primary)]">
                  {data.timeframe5m?.lastBos?.type || data.timeframe5m?.lastChoch?.type || 'No Confirmed Shift'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Displacement:</span>
                <span className={`font-semibold ${data.timeframe5m?.displacementConfirmed ? 'text-emerald-400' : 'text-[var(--text-secondary)]'}`}>
                  {data.timeframe5m?.displacementConfirmed ? 'Confirmed (Expansion)' : 'Compressing'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Internal Swings:</span>
                <span className="tabular-nums text-[var(--text-secondary)]">
                  {data.timeframe5m?.internalStructure || 'Monitored'}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-[var(--border-subtle)] text-[11px] text-[var(--text-secondary)] leading-relaxed italic">
            {data.reasoning5m || '5M structure validates body closes beyond swing levels.'}
          </div>
        </div>

        {/* 1-Minute: Micro Entry & Exact Invalidation */}
        <div className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-lg p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-2 border-b border-[var(--border-subtle)] mb-3">
              <span className="text-xs font-semibold text-[var(--text-secondary)] flex items-center gap-1.5">
                <Activity className="w-3.5 h-3.5 text-purple-400" />
                1M: Micro Entry Trigger
              </span>
              <span className={`text-[10px] px-2 py-0.5 font-semibold uppercase rounded ${
                data.timeframe1m?.bias === 'BULLISH'
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : data.timeframe1m?.bias === 'BEARISH'
                  ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                  : 'bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)]'
              }`}>
                {data.timeframe1m?.bias || 'NEUTRAL'}
              </span>
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Entry Confirmation:</span>
                <span className="font-semibold text-[var(--text-primary)]">
                  {data.timeframe1m?.entryStatus || 'Monitoring FVG Retest'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Exact Invalidation:</span>
                <span className="tabular-nums text-rose-400">
                  ₹{data.timeframe1m?.invalidationLevel ? data.timeframe1m.invalidationLevel.toFixed(2) : 'Structure Low/High'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">FVG Mitigation:</span>
                <span className="font-semibold text-purple-400">
                  50% CE Respected
                </span>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-[var(--border-subtle)] text-[11px] text-[var(--text-secondary)] leading-relaxed italic">
            {data.reasoning1m || '1M micro structure ensures tight invalidation and favorable R:R.'}
          </div>
        </div>
      </div>
    </div>
  );
};

