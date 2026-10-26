'use client';

import React from 'react';
import { NextSessionOpeningOutlook } from '@/types/options';
import {
  Compass,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  CheckCircle2,
  Calendar,
  Layers,
  Info,
} from 'lucide-react';

interface NextSessionOpeningCardProps {
  outlook: NextSessionOpeningOutlook;
  indexSymbol?: string;
}

export const NextSessionOpeningCard: React.FC<NextSessionOpeningCardProps> = ({
  outlook,
  indexSymbol = 'NIFTY 50',
}) => {
  if (!outlook) return null;

  const isGapUp = outlook.estimatedGap?.direction === 'GAP_UP';
  const isGapDown = outlook.estimatedGap?.direction === 'GAP_DOWN';

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-5 sm:p-6 space-y-5 shadow-sm">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-indigo-50 dark:bg-indigo-500/10 border border-indigo-200 dark:border-indigo-500/20 flex items-center justify-center text-indigo-500">
            <Compass className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
                NEXT-SESSION OPENING OUTLOOK
              </h3>
              <span className="text-[10px] px-2 py-0.5 rounded-md bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 font-bold border border-indigo-200 dark:border-indigo-500/20">
                {outlook.symbol || indexSymbol}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] mt-0.5">
              <Calendar className="w-3.5 h-3.5" />
              <span>Target Session: {outlook.targetSessionDate}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="text-right">
            <div className="text-[10px] text-[var(--text-muted)] font-medium">Confidence Level</div>
            <span
              className={`text-xs font-bold px-2.5 py-0.5 rounded-md inline-block border ${
                outlook.confidence.toLowerCase().includes('high')
                  ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20'
                  : outlook.confidence.toLowerCase().includes('moderate')
                  ? 'bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-500/20'
                  : 'bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-500/20'
              }`}
            >
              {outlook.confidence}
            </span>
          </div>
        </div>
      </div>

      {/* Main Stats: Expected Range & Estimated Gap */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
        {/* Estimated Opening Range */}
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] p-4 space-y-2">
          <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
            <span className="flex items-center gap-1.5 font-semibold">
              <Layers className="w-3.5 h-3.5 text-indigo-500" />
              Estimated Opening Range
            </span>
            <span className="text-[10px] text-[var(--text-muted)]">Volatility & ATR Blended</span>
          </div>
          <div className="text-lg font-bold text-[var(--text-primary)] font-mono">
            {outlook.expectedOpeningRange?.rangeString || 'Calculating...'}
          </div>
          <div className="flex items-center justify-between text-xs text-[var(--text-muted)] pt-2 border-t border-[var(--border-subtle)] font-mono">
            <span>Low: ₹{outlook.expectedOpeningRange?.low?.toLocaleString('en-IN', { minimumFractionDigits: 1 }) || '—'}</span>
            <span>Mid: ₹{outlook.expectedOpeningRange?.midpoint?.toLocaleString('en-IN', { minimumFractionDigits: 1 }) || '—'}</span>
            <span>High: ₹{outlook.expectedOpeningRange?.high?.toLocaleString('en-IN', { minimumFractionDigits: 1 }) || '—'}</span>
          </div>
        </div>

        {/* Estimated Gap Magnitude */}
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] p-4 space-y-2">
          <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
            <span className="flex items-center gap-1.5 font-semibold">
              {isGapUp ? (
                <TrendingUp className="w-3.5 h-3.5 text-emerald-500" />
              ) : isGapDown ? (
                <TrendingDown className="w-3.5 h-3.5 text-rose-500" />
              ) : (
                <Minus className="w-3.5 h-3.5 text-blue-500" />
              )}
              Estimated Opening Gap
            </span>
            <span className="text-[10px] text-[var(--text-muted)] font-mono">
              Prev Close: ₹{outlook.previousClose?.toLocaleString('en-IN') || '—'}
            </span>
          </div>
          <div className="flex items-baseline gap-2 font-mono">
            <div
              className={`text-lg font-bold ${
                isGapUp
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : isGapDown
                  ? 'text-rose-600 dark:text-rose-400'
                  : 'text-blue-600 dark:text-blue-400'
              }`}
            >
              {outlook.estimatedGap?.points > 0 ? `+${outlook.estimatedGap?.points}` : outlook.estimatedGap?.points} pts
            </div>
            <span className="text-xs font-semibold text-[var(--text-muted)]">
              ({outlook.estimatedGap?.percent > 0 ? `+${outlook.estimatedGap?.percent}` : outlook.estimatedGap?.percent}%)
            </span>
          </div>
          <p className="text-xs text-[var(--text-secondary)] pt-2 border-t border-[var(--border-subtle)] truncate">
            {outlook.estimatedGap?.summary || 'Equilibrium expected'}
          </p>
        </div>
      </div>

      {/* Probabilistic Opening Scenarios */}
      <div className="space-y-3">
        <div className="text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider">
          Probabilistic Opening Scenarios
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* Bullish Gap */}
          <div className="rounded-xl border border-emerald-200 dark:border-emerald-500/20 bg-emerald-50/30 dark:bg-emerald-500/5 p-4 space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-emerald-700 dark:text-emerald-400 flex items-center gap-1.5">
                <TrendingUp className="w-3.5 h-3.5 text-emerald-500" /> Bullish Gap-Up
              </span>
              <span className="text-xs font-bold font-mono px-2 py-0.5 rounded-md bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/20">
                {outlook.scenarios?.bullishGap?.probability || '—'}
              </span>
            </div>
            <div className="text-xs text-[var(--text-secondary)] leading-relaxed">
              {outlook.scenarios?.bullishGap?.description}
            </div>
            <div className="text-[11px] text-emerald-800 dark:text-emerald-300/90 pt-2 border-t border-emerald-200 dark:border-emerald-500/15">
              <span className="font-semibold">Action:</span> {outlook.scenarios?.bullishGap?.actionableTakeaway}
            </div>
          </div>

          {/* Flat / Equilibrium */}
          <div className="rounded-xl border border-blue-200 dark:border-blue-500/20 bg-blue-50/30 dark:bg-blue-500/5 p-4 space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-blue-700 dark:text-blue-400 flex items-center gap-1.5">
                <Minus className="w-3.5 h-3.5 text-blue-500" /> Flat / Equilibrium
              </span>
              <span className="text-xs font-bold font-mono px-2 py-0.5 rounded-md bg-blue-100 dark:bg-blue-500/15 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-500/20">
                {outlook.scenarios?.flatOpening?.probability || '—'}
              </span>
            </div>
            <div className="text-xs text-[var(--text-secondary)] leading-relaxed">
              {outlook.scenarios?.flatOpening?.description}
            </div>
            <div className="text-[11px] text-blue-800 dark:text-blue-300/90 pt-2 border-t border-blue-200 dark:border-blue-500/15">
              <span className="font-semibold">Action:</span> {outlook.scenarios?.flatOpening?.actionableTakeaway}
            </div>
          </div>

          {/* Bearish Gap */}
          <div className="rounded-xl border border-rose-200 dark:border-rose-500/20 bg-rose-50/30 dark:bg-rose-500/5 p-4 space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-rose-700 dark:text-rose-400 flex items-center gap-1.5">
                <TrendingDown className="w-3.5 h-3.5 text-rose-500" /> Bearish Gap-Down
              </span>
              <span className="text-xs font-bold font-mono px-2 py-0.5 rounded-md bg-rose-100 dark:bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-500/20">
                {outlook.scenarios?.bearishGap?.probability || '—'}
              </span>
            </div>
            <div className="text-xs text-[var(--text-secondary)] leading-relaxed">
              {outlook.scenarios?.bearishGap?.description}
            </div>
            <div className="text-[11px] text-rose-800 dark:text-rose-300/90 pt-2 border-t border-rose-200 dark:border-rose-500/15">
              <span className="font-semibold">Action:</span> {outlook.scenarios?.bearishGap?.actionableTakeaway}
            </div>
          </div>
        </div>
      </div>

      {/* Supporting Evidence & Invalidation Conditions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 pt-1">
        {/* Supporting Evidence */}
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] p-4 space-y-2.5">
          <div className="flex items-center gap-1.5 text-xs font-bold text-[var(--text-primary)]">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
            Supporting Quantitative Evidence
          </div>
          <ul className="space-y-1.5">
            {outlook.supportingEvidence?.map((ev, i) => (
              <li key={i} className="text-xs text-[var(--text-secondary)] flex items-start gap-2">
                <span className="text-emerald-500 mt-0.5 font-bold">•</span>
                <span>{ev}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Key Invalidation Conditions */}
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] p-4 space-y-2.5">
          <div className="flex items-center gap-1.5 text-xs font-bold text-amber-700 dark:text-amber-400">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
            Forecast Invalidation Thresholds
          </div>
          <ul className="space-y-1.5">
            {outlook.keyInvalidationConditions?.map((inv, i) => (
              <li key={i} className="text-xs text-[var(--text-secondary)] flex items-start gap-2">
                <span className="text-amber-500 mt-0.5 font-bold">•</span>
                <span>{inv}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Pre-Market Disclaimer */}
      <div className="rounded-xl bg-[var(--bg-surface-elevated)] p-3.5 flex items-start gap-2.5 border border-[var(--border-subtle)] text-xs text-[var(--text-muted)]">
        <Info className="w-4 h-4 text-[var(--text-muted)] shrink-0 mt-0.5" />
        <div className="leading-relaxed">
          <span className="font-semibold text-[var(--text-secondary)]">Opening Price Disclaimer: </span>
          {outlook.disclaimer ||
            'Opening range is a probabilistic estimate from quantitative volatility models. Exact opening prices are determined exclusively by the NSE/BSE 09:00-09:08 AM IST pre-market auction.'}
        </div>
      </div>
    </div>
  );
};
