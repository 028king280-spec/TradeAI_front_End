'use client';

import React from 'react';
import { OptionsMarketSentiment } from '@/types/options';
import { Gauge, CheckCircle2, AlertTriangle, Info } from 'lucide-react';

interface MarketSentimentPanelProps {
  sentiment: OptionsMarketSentiment;
}

export const MarketSentimentPanel: React.FC<MarketSentimentPanelProps> = ({ sentiment }) => {
  if (!sentiment) return null;

  const isBullish = sentiment.overallSentiment === 'BULLISH';
  const isBearish = sentiment.overallSentiment === 'BEARISH';

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 sm:p-5 shadow-sm space-y-4 tabular-nums">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 flex items-center justify-center">
            <Gauge className="w-4 h-4 text-[var(--accent-blue)]" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              Multi-Factor Market Sentiment Engine
            </h3>
            <span className="text-[10px] text-[var(--text-muted)]">
              Cross-asset calculation: Trend, VWAP, PCR, OI Additions, Volatility
            </span>
          </div>
        </div>

        {/* Sentiment Badge */}
        <div className="flex items-center gap-2">
          <span
            className={`px-3 py-1 rounded-lg text-xs font-semibold uppercase tracking-wider ${
              isBullish
                ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30'
                : isBearish
                ? 'bg-rose-500/20 text-rose-600 dark:text-rose-400 border border-rose-500/30'
                : 'bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/30'
            }`}
          >
            {sentiment.overallSentiment} ({sentiment.sentimentScore}/100)
          </span>
          <span className="text-[10px] text-[var(--text-muted)]">
            Strength: <strong>{sentiment.trendStrength}</strong>
          </span>
        </div>
      </div>

      {/* Score Meter & Evidence Balance */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {/* Score Visual Meter */}
        <div className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-2">
          <div className="flex justify-between text-[11px]">
            <span className="text-[var(--text-muted)]">Sentiment Calibration</span>
            <span className="font-semibold text-[var(--text-primary)]">{sentiment.sentimentScore}%</span>
          </div>
          <div className="w-full h-2 rounded-full bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] overflow-hidden flex">
            <div
              className="h-full bg-emerald-500 transition-all duration-500"
              style={{ width: `${sentiment.bullishEvidenceScore}%` }}
            />
            <div
              className="h-full bg-rose-500 transition-all duration-500"
              style={{ width: `${sentiment.bearishEvidenceScore}%` }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-[var(--text-muted)] pt-0.5">
            <span className="text-emerald-500 font-semibold">Bullish: {sentiment.bullishEvidenceScore} pts</span>
            <span className="text-rose-500 font-semibold">Bearish: {sentiment.bearishEvidenceScore} pts</span>
          </div>
        </div>

        {/* Triggers */}
        <div className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-1 text-xs">
          <div className="text-[10px] text-[var(--text-muted)] uppercase font-semibold">
            Key Execution Triggers
          </div>
          <div className="flex justify-between text-[11px] pt-0.5">
            <span className="text-[var(--text-muted)]">Bullish Trigger:</span>
            <span className="font-semibold text-emerald-500">₹{sentiment.importantPriceTriggers.bullishConfirmation?.toLocaleString('en-IN')}</span>
          </div>
          <div className="flex justify-between text-[11px]">
            <span className="text-[var(--text-muted)]">Bearish Trigger:</span>
            <span className="font-semibold text-rose-500">₹{sentiment.importantPriceTriggers.bearishConfirmation?.toLocaleString('en-IN')}</span>
          </div>
        </div>

        {/* Confirmation Status */}
        <div className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-1 text-xs">
          <div className="text-[10px] text-[var(--text-muted)] uppercase font-semibold">
            Confirmation Status
          </div>
          <p className="text-[11px] text-[var(--text-secondary)] leading-snug pt-0.5">
            {sentiment.confirmationLevel}
          </p>
        </div>
      </div>

      {/* Supporting vs Conflicting Factors */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
        {/* Supporting Factors */}
        <div className="p-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 space-y-2">
          <div className="text-[11px] font-semibold text-emerald-500 flex items-center gap-1.5 uppercase">
            <CheckCircle2 className="w-3.5 h-3.5" /> Supporting Signals ({sentiment.supportingFactors.length})
          </div>
          <ul className="space-y-1.5 text-[11px] text-[var(--text-secondary)]">
            {sentiment.supportingFactors.map((factor, i) => (
              <li key={i} className="flex items-start gap-1.5 leading-snug">
                <span className="text-emerald-500 font-semibold shrink-0 mt-0.5">•</span>
                <span>{factor}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Conflicting / Risk Factors */}
        <div className="p-3 rounded-lg border border-amber-500/20 bg-amber-500/5 space-y-2">
          <div className="text-[11px] font-semibold text-amber-500 flex items-center gap-1.5 uppercase">
            <AlertTriangle className="w-3.5 h-3.5" /> Conflicting Signals & Warnings ({sentiment.conflictingFactors.length + sentiment.reasonsToAvoidTrade.length})
          </div>
          <ul className="space-y-1.5 text-[11px] text-[var(--text-secondary)]">
            {sentiment.conflictingFactors.map((factor, i) => (
              <li key={i} className="flex items-start gap-1.5 leading-snug">
                <span className="text-amber-500 font-semibold shrink-0 mt-0.5">•</span>
                <span>{factor}</span>
              </li>
            ))}
            {sentiment.reasonsToAvoidTrade.map((reason, i) => (
              <li key={`avoid-${i}`} className="flex items-start gap-1.5 leading-snug text-rose-500">
                <span className="font-bold shrink-0 mt-0.5">⚠</span>
                <span>{reason}</span>
              </li>
            ))}
            {!sentiment.conflictingFactors.length && !sentiment.reasonsToAvoidTrade.length && (
              <li className="text-[var(--text-muted)] italic">No significant conflicting signals detected.</li>
            )}
          </ul>
        </div>
      </div>

      {/* Derivative Notice */}
      <div className="p-2.5 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[10px] text-[var(--text-muted)] flex items-start gap-1.5">
        <Info className="w-3.5 h-3.5 text-[var(--accent-blue)] shrink-0 mt-0.5" />
        <span>{sentiment.criticalDerivativeNotice}</span>
      </div>
    </div>
  );
};
