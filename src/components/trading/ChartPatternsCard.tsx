'use client';

import React from 'react';
import { DetectedChartPattern } from '@/types/options';
import { GitMerge, CheckCircle2, AlertTriangle, Clock, ShieldCheck } from 'lucide-react';

interface ChartPatternsCardProps {
  patterns: DetectedChartPattern[];
}

export const ChartPatternsCard: React.FC<ChartPatternsCardProps> = ({ patterns }) => {
  if (!patterns || patterns.length === 0) {
    return (
      <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-5 text-center font-mono text-xs text-[var(--text-muted)] space-y-1">
        <GitMerge className="w-5 h-5 mx-auto text-[var(--text-muted)] opacity-50" />
        <div>No distinct chart or candlestick pattern currently meeting confirmation criteria.</div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 sm:p-5 shadow-sm space-y-3 font-mono">
      <div className="flex items-center justify-between pb-2 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center">
            <GitMerge className="w-4 h-4 text-indigo-500" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)]">
              Detected Candlestick & Price-Action Patterns
            </h3>
            <span className="text-[10px] text-[var(--text-muted)]">
              Mathematical criteria verified on latest candles
            </span>
          </div>
        </div>
        <span className="text-[10px] px-2 py-0.5 rounded bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 font-semibold">
          {patterns.length} Pattern(s) Active
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {patterns.map((p, idx) => {
          const isBull = p.interpretation === 'BULLISH';
          const isBear = p.interpretation === 'BEARISH';

          return (
            <div
              key={idx}
              className={`p-3.5 rounded-lg border text-xs space-y-2 ${
                isBull
                  ? 'border-emerald-500/25 bg-emerald-500/5'
                  : isBear
                  ? 'border-rose-500/25 bg-rose-500/5'
                  : 'border-amber-500/25 bg-amber-500/5'
              }`}
            >
              <div className="flex items-center justify-between pb-1 border-b border-[var(--border-subtle)]">
                <div className="flex items-center gap-1.5 font-bold">
                  {p.confirmed ? (
                    <CheckCircle2 className={`w-3.5 h-3.5 ${isBull ? 'text-emerald-500' : isBear ? 'text-rose-500' : 'text-amber-500'}`} />
                  ) : (
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
                  )}
                  <span className="text-[var(--text-primary)]">{p.patternName}</span>
                </div>
                <div className="flex items-center gap-1.5 text-[10px]">
                  <span className="px-1.5 py-0.2 rounded bg-[var(--bg-surface-elevated)] text-[var(--text-muted)]">
                    {p.timeframe}
                  </span>
                  <span
                    className={`px-1.5 py-0.2 rounded font-bold uppercase ${
                      isBull
                        ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400'
                        : isBear
                        ? 'bg-rose-500/20 text-rose-600 dark:text-rose-400'
                        : 'bg-amber-500/20 text-amber-600 dark:text-amber-400'
                    }`}
                  >
                    {p.interpretation}
                  </span>
                </div>
              </div>

              <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">
                {p.description}
              </p>

              <div className="space-y-1 text-[10px] text-[var(--text-muted)] pt-1 border-t border-[var(--border-subtle)]">
                <div>
                  <strong className="text-[var(--text-primary)]">Confirmation:</strong> {p.confirmationCondition}
                </div>
                <div>
                  <strong className="text-rose-500">Invalidation:</strong> {p.invalidationCondition}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
