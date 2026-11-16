'use client';

import React, { useState } from 'react';
import { SessionOutlookData } from '@/types/options';
import { Compass, TrendingUp, TrendingDown, ShieldCheck } from 'lucide-react';


interface SessionOutlookCardProps {
  todayData: SessionOutlookData;
  nextSessionData: SessionOutlookData;
}

export const SessionOutlookCard: React.FC<SessionOutlookCardProps> = ({
  todayData,
  nextSessionData,
}) => {
  const [activeTab, setActiveTab] = useState<'TODAY' | 'NEXT_SESSION'>('TODAY');
  const currentData = activeTab === 'TODAY' ? todayData : nextSessionData;

  if (!currentData) return null;

  const { expectedRange, triggers, probabilities, scenarios } = currentData;

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 sm:p-5 shadow-sm space-y-4">
      {/* Top Header with Tab Switcher */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 flex items-center justify-center">
            <Compass className="w-4 h-4 text-[var(--accent-blue)]" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)] tabular-nums">
              Market Session Outlook & Scenarios
            </h3>
            <span className="text-[10px] text-[var(--text-muted)] tabular-nums">
              {currentData.sessionLabel}
            </span>
          </div>
        </div>

        {/* Tab Controls */}
        <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)] tabular-nums text-xs">
          <button
            onClick={() => setActiveTab('TODAY')}
            className={`px-3 py-1 rounded-md transition-all ${
              activeTab === 'TODAY'
                ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] font-semibold shadow-xs'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            Today's Outlook
          </button>
          <button
            onClick={() => setActiveTab('NEXT_SESSION')}
            className={`px-3 py-1 rounded-md transition-all ${
              activeTab === 'NEXT_SESSION'
                ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] font-semibold shadow-xs'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            Next Trading Session
          </button>
        </div>
      </div>

      {/* Expected Price Range & Probabilities */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Range Container */}
        <div className="p-3.5 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-2.5 tabular-nums text-xs">
          <div className="flex items-center justify-between text-[10px] uppercase font-semibold text-[var(--text-muted)]">
            <span>Expected Session Range</span>
            <span className="text-[var(--accent-blue)]">ATR Move: ±{expectedRange.expectedMovePoints} pts</span>
          </div>
          <div className="grid grid-cols-2 gap-2 text-center">
            <div className="p-2 rounded bg-rose-500/10 border border-rose-500/20">
              <span className="text-[10px] text-rose-500 block">Likely Low</span>
              <span className="text-sm font-semibold text-rose-500">₹{expectedRange.likelyLow.toLocaleString('en-IN')}</span>
            </div>
            <div className="p-2 rounded bg-emerald-500/10 border border-emerald-500/20">
              <span className="text-[10px] text-emerald-500 block">Likely High</span>
              <span className="text-sm font-semibold text-emerald-500">₹{expectedRange.likelyHigh.toLocaleString('en-IN')}</span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] pt-1 text-[var(--text-muted)] border-t border-[var(--border-subtle)]">
            <span>Base-Case Range: <strong className="text-[var(--text-primary)]">{expectedRange.baseCaseRange}</strong></span>
            <span>Breakout: <strong className="text-emerald-500">₹{triggers.bullishBreakoutTrigger}</strong></span>
          </div>
        </div>

        {/* Probabilities Container */}
        <div className="p-3.5 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-2.5 tabular-nums text-xs">
          <div className="text-[10px] uppercase font-semibold text-[var(--text-muted)]">
            Model-Estimated Directional Probabilities
          </div>
          <div className="space-y-1.5">
            <div>
              <div className="flex justify-between text-[11px] mb-0.5">
                <span className="text-emerald-500 font-semibold">Upside Continuation</span>
                <span className="font-semibold text-emerald-500">{probabilities.upsideProbability}%</span>
              </div>
              <div className="w-full h-1.5 rounded-full bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] overflow-hidden">
                <div
                  className="h-full bg-emerald-500 rounded-full"
                  style={{ width: `${probabilities.upsideProbability}%` }}
                />
              </div>
            </div>

            <div>
              <div className="flex justify-between text-[11px] mb-0.5">
                <span className="text-amber-500 font-semibold">Consolidation / Range</span>
                <span className="font-semibold text-amber-500">{probabilities.neutralProbability}%</span>
              </div>
              <div className="w-full h-1.5 rounded-full bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] overflow-hidden">
                <div
                  className="h-full bg-amber-500 rounded-full"
                  style={{ width: `${probabilities.neutralProbability}%` }}
                />
              </div>
            </div>

            <div>
              <div className="flex justify-between text-[11px] mb-0.5">
                <span className="text-rose-500 font-semibold">Downside Breakdown</span>
                <span className="font-semibold text-rose-500">{probabilities.downsideProbability}%</span>
              </div>
              <div className="w-full h-1.5 rounded-full bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] overflow-hidden">
                <div
                  className="h-full bg-rose-500 rounded-full"
                  style={{ width: `${probabilities.downsideProbability}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 3 Scenarios (Bullish, Base Case, Bearish) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 tabular-nums text-xs">
        {/* Bullish Scenario */}
        <div className="p-3.5 rounded-lg border border-emerald-500/25 bg-emerald-500/5 space-y-2">
          <div className="flex items-center justify-between pb-1 border-b border-emerald-500/20">
            <span className="font-semibold text-emerald-500 flex items-center gap-1.5">
              <TrendingUp className="w-3.5 h-3.5" /> Bullish Scenario
            </span>
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 font-semibold">
              {scenarios.bullish.estimatedProbability}
            </span>
          </div>
          <div className="text-[11px] text-[var(--text-secondary)]">
            <span className="text-[10px] text-[var(--text-muted)] block uppercase">Trigger:</span>
            {scenarios.bullish.triggerCondition}
          </div>
          <div className="text-[11px] text-[var(--text-secondary)]">
            <span className="text-[10px] text-[var(--text-muted)] block uppercase">Target Zone:</span>
            <span className="font-semibold text-emerald-600 dark:text-emerald-400">{scenarios.bullish.targetZone}</span>
          </div>
          {scenarios.bullish.invalidationLevel && (
            <div className="text-[10px] text-rose-500">
              Invalidation: ₹{scenarios.bullish.invalidationLevel}
            </div>
          )}
        </div>

        {/* Base Case Scenario */}
        <div className="p-3.5 rounded-lg border border-amber-500/25 bg-amber-500/5 space-y-2">
          <div className="flex items-center justify-between pb-1 border-b border-amber-500/20">
            <span className="font-semibold text-amber-500 flex items-center gap-1.5">
              <Compass className="w-3.5 h-3.5" /> Base-Case Range
            </span>
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-600 dark:text-amber-400 font-semibold">
              {scenarios.baseCase.estimatedProbability}
            </span>
          </div>
          <div className="text-[11px] text-[var(--text-secondary)]">
            <span className="text-[10px] text-[var(--text-muted)] block uppercase">Trigger:</span>
            {scenarios.baseCase.triggerCondition}
          </div>
          <div className="text-[11px] text-[var(--text-secondary)]">
            <span className="text-[10px] text-[var(--text-muted)] block uppercase">Equilibrium:</span>
            <span className="font-semibold text-amber-600 dark:text-amber-400">{scenarios.baseCase.targetZone}</span>
          </div>
        </div>

        {/* Bearish Scenario */}
        <div className="p-3.5 rounded-lg border border-rose-500/25 bg-rose-500/5 space-y-2">
          <div className="flex items-center justify-between pb-1 border-b border-rose-500/20">
            <span className="font-semibold text-rose-500 flex items-center gap-1.5">
              <TrendingDown className="w-3.5 h-3.5" /> Bearish Scenario
            </span>
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-rose-500/20 text-rose-600 dark:text-rose-400 font-semibold">
              {scenarios.bearish.estimatedProbability}
            </span>
          </div>
          <div className="text-[11px] text-[var(--text-secondary)]">
            <span className="text-[10px] text-[var(--text-muted)] block uppercase">Trigger:</span>
            {scenarios.bearish.triggerCondition}
          </div>
          <div className="text-[11px] text-[var(--text-secondary)]">
            <span className="text-[10px] text-[var(--text-muted)] block uppercase">Downside Zone:</span>
            <span className="font-semibold text-rose-600 dark:text-rose-400">{scenarios.bearish.targetZone}</span>
          </div>
          {scenarios.bearish.invalidationLevel && (
            <div className="text-[10px] text-rose-500">
              Invalidation: ₹{scenarios.bearish.invalidationLevel}
            </div>
          )}
        </div>
      </div>

      {/* Probabilistic Disclaimer */}
      <div className="text-[10px] tabular-nums text-[var(--text-muted)] pt-1 flex items-center gap-1.5">
        <ShieldCheck className="w-3.5 h-3.5 text-[var(--accent-blue)] shrink-0" />
        <span>{currentData.disclaimer}</span>
      </div>
    </div>
  );
};
