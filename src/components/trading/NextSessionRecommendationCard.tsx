'use client';

import React from 'react';
import { NextSessionRecommendation, QualifiedNextSessionSetup } from '@/types/options';
import {
  ShieldAlert,
  ShieldCheck,
  Zap,
  Target,
  Clock,
  AlertOctagon,
  TrendingUp,
  TrendingDown,
  Info,
  CheckCircle,
  Activity,
  Layers,
  BarChart3,
  Flame,
  ArrowRight,
} from 'lucide-react';
import { formatINR } from '@/lib/utils';

interface NextSessionRecommendationCardProps {
  data: NextSessionRecommendation;
  onOpenBacktest?: () => void;
}

export const NextSessionRecommendationCard: React.FC<NextSessionRecommendationCardProps> = ({
  data,
  onOpenBacktest,
}) => {
  if (!data) return null;

  const isLiveStage = data.stage === 'STAGE_2_LIVE_CONFIRMED';
  const hasQualified = data.hasQualifiedRecommendation && data.recommendation !== null;
  const rec: QualifiedNextSessionSetup | null = data.recommendation;

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-5 sm:p-6 space-y-4 shadow-sm">
      {/* Header with Stage Indicator & Action Button */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
            <Zap className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
                NEXT-SESSION OPTIONS RECOMMENDATION
              </h3>
              <span
                className={`text-[10px] px-2 py-0.5 rounded-md font-bold border ${
                  hasQualified
                    ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20'
                    : 'bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-500/20'
                }`}
              >
                {data.decisionBadge || (hasQualified ? 'QUALIFIED SETUP' : 'NO TRADE — PRESERVE CAPITAL')}
              </span>
            </div>
            <div className="text-xs text-[var(--text-muted)] mt-0.5">
              Target Session: {data.targetSessionDate} • {data.symbol}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {onOpenBacktest && (
            <button
              onClick={onOpenBacktest}
              className="px-3 py-1.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-hover)] text-xs font-semibold text-[var(--text-primary)] flex items-center gap-1.5 transition-colors shadow-sm"
            >
              <BarChart3 className="w-3.5 h-3.5 text-indigo-500" />
              <span>Historical Backtest</span>
            </button>
          )}

          {/* Two-Stage Confirmation Badge */}
          <div
            className={`px-2.5 py-1 rounded-lg border text-[11px] font-semibold flex items-center gap-1.5 ${
              isLiveStage
                ? 'bg-blue-50 dark:bg-blue-500/10 border-blue-200 dark:border-blue-500/20 text-blue-600 dark:text-blue-400'
                : 'bg-indigo-50 dark:bg-indigo-500/10 border-indigo-200 dark:border-indigo-500/20 text-indigo-600 dark:text-indigo-400'
            }`}
          >
            <Activity className="w-3 h-3 shrink-0" />
            <span>{isLiveStage ? 'STAGE 2: LIVE CONFIRMED' : 'STAGE 1: PRE-MARKET OUTLOOK'}</span>
          </div>
        </div>
      </div>

      {/* STAGE DESCRIPTION BANNER */}
      <div className="rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] p-3 text-xs text-[var(--text-secondary)] flex items-start gap-2.5">
        <Info className="w-4 h-4 text-indigo-500 shrink-0 mt-0.5" />
        <div className="leading-relaxed">
          {isLiveStage ? (
            <span>
              <strong className="text-[var(--text-primary)]">STAGE 2 (Live Confirmation):</strong> Active post-09:15 AM IST.
              Signals are verified against opening auction price, live 5m candles, VWAP, opening range hold, and real-time option spread.
            </span>
          ) : (
            <span>
              <strong className="text-[var(--text-primary)]">STAGE 1 (Pre-Market Preliminary):</strong> Computed using overnight cues,
              GIFT Nifty drift, and previous close. Levels must be confirmed at market open (09:15-09:20 AM IST) before execution.
            </span>
          )}
        </div>
      </div>

      {/* CASE 1: NO TRADE (MANDATORY ENFORCEMENT) */}
      {!hasQualified || !rec ? (
        <div className="rounded-2xl border border-amber-200 dark:border-amber-500/20 bg-amber-50/40 dark:bg-amber-500/5 p-5 space-y-4">
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded-xl bg-amber-100 dark:bg-amber-500/15 border border-amber-200 dark:border-amber-500/30 flex items-center justify-center shrink-0">
              <ShieldAlert className="w-5 h-5 text-amber-600 dark:text-amber-400" />
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-bold text-amber-800 dark:text-amber-300">
                  NO TRADE — PRESERVE CAPITAL
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded-md bg-amber-100 dark:bg-amber-500/20 text-amber-800 dark:text-amber-300 font-semibold border border-amber-200 dark:border-amber-500/30">
                  Capital Protection Gate Active
                </span>
              </div>
              <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                The institutional recommendation engine evaluated next-session setups for {data.symbol} and determined that
                market conditions do not qualify for directional option buying. Never force a trade.
              </p>
            </div>
          </div>

          {/* List of reasons */}
          <div className="rounded-xl bg-[var(--bg-surface)] border border-amber-200/80 dark:border-amber-500/20 p-4 space-y-2.5">
            <span className="text-xs font-bold text-[var(--text-primary)] flex items-center gap-1.5">
              <AlertOctagon className="w-3.5 h-3.5 text-amber-500" />
              Technical Reasons Behind NO-TRADE Decision:
            </span>
            <ul className="space-y-1.5 text-xs text-[var(--text-secondary)]">
              {data.reasonsForNoTrade && data.reasonsForNoTrade.length > 0 ? (
                data.reasonsForNoTrade.map((reason, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="text-amber-500 font-bold">•</span>
                    <span>{reason}</span>
                  </li>
                ))
              ) : (
                <li className="flex items-start gap-2">
                  <span className="text-amber-500 font-bold">•</span>
                  <span>Market regime is in neutral compression or chop. Directional option buying has negative expectancy due to overnight theta decay.</span>
                </li>
              )}
            </ul>
          </div>

          {/* Actionable Rules */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5 pt-1 text-xs text-[var(--text-muted)]">
            <div className="p-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
              <span className="font-semibold text-[var(--text-primary)] block mb-0.5">Capital Deployment</span>
              <span className="font-mono text-[var(--text-secondary)]">₹0.00 (Zero risk allocated)</span>
            </div>
            <div className="p-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
              <span className="font-semibold text-[var(--text-primary)] block mb-0.5">Re-analysis Trigger</span>
              <span className="text-[var(--text-secondary)]">Wait for 09:15 AM opening candle & VWAP expansion</span>
            </div>
            <div className="p-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
              <span className="font-semibold text-[var(--text-primary)] block mb-0.5">Discipline Note</span>
              <span className="text-[var(--text-secondary)]">Sitting in cash is an active, profitable position.</span>
            </div>
          </div>
        </div>
      ) : (
        /* CASE 2: QUALIFIED CANDIDATE SETUP */
        <div className="space-y-4">
          {/* Main Contract Hero Card */}
          <div
            className={`rounded-2xl border p-5 transition-all ${
              rec.optionType === 'CE'
                ? 'border-emerald-200 dark:border-emerald-500/20 bg-emerald-50/30 dark:bg-emerald-500/5'
                : 'border-rose-200 dark:border-rose-500/20 bg-rose-50/30 dark:bg-rose-500/5'
            }`}
          >
            {/* Contract Title & Basic Details */}
            <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
              <div className="flex items-center gap-2.5">
                <span
                  className={`text-xs px-2.5 py-1 rounded-md font-bold text-white shadow-sm ${
                    rec.optionType === 'CE' ? 'bg-emerald-600' : 'bg-rose-600'
                  }`}
                >
                  {rec.optionType} ({rec.optionType === 'CE' ? 'CALL' : 'PUT'})
                </span>
                <span className="text-sm font-bold text-[var(--text-primary)] font-mono">
                  {rec.contractSymbol}
                </span>
                <span className="text-xs text-[var(--text-muted)]">
                  ({rec.expiry})
                </span>
              </div>

              <div className="flex items-center gap-2 text-xs">
                <span className="px-2.5 py-1 rounded-md bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)] font-semibold font-mono">
                  R:R {rec.riskRewardRatio}
                </span>
                <span className="px-2.5 py-1 rounded-md bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)] font-semibold font-mono">
                  Delta: {rec.greeks?.delta?.toFixed(2) || '0.50'}
                </span>
              </div>
            </div>

            {/* Premium Levels Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2.5 py-4">
              {/* Last Verified Premium */}
              <div className="p-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
                <span className="text-[10px] text-[var(--text-muted)] block font-medium">Last Verified</span>
                <span className="text-base font-bold text-[var(--text-primary)] font-mono">
                  ₹{rec.lastVerifiedPremium?.toFixed(1)}
                </span>
                <span className="text-[10px] text-[var(--text-muted)] block">Observed close</span>
              </div>

              {/* Suggested Entry Range */}
              <div className="p-3 rounded-xl border border-indigo-200 dark:border-indigo-500/20 bg-indigo-50/50 dark:bg-indigo-500/10">
                <span className="text-[10px] text-indigo-600 dark:text-indigo-400 font-semibold block">Suggested Entry</span>
                <span className="text-sm font-bold text-indigo-700 dark:text-indigo-300 font-mono">
                  {rec.suggestedEntryRange}
                </span>
                <span className="text-[10px] text-[var(--text-muted)] block">Planned bracket</span>
              </div>

              {/* Stop Loss */}
              <div className="p-3 rounded-xl border border-rose-200 dark:border-rose-500/20 bg-rose-50/50 dark:bg-rose-500/10">
                <span className="text-[10px] text-rose-600 dark:text-rose-400 font-semibold block">Stop-Loss (SL)</span>
                <span className="text-base font-bold text-rose-700 dark:text-rose-400 font-mono">
                  ₹{rec.stopLossPremium?.toFixed(1)}
                </span>
                <span className="text-[10px] text-rose-500 block">Strict invalidation</span>
              </div>

              {/* Target 1 */}
              <div className="p-3 rounded-xl border border-emerald-200 dark:border-emerald-500/20 bg-emerald-50/50 dark:bg-emerald-500/10">
                <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold block">Target 1 (1.2R)</span>
                <span className="text-base font-bold text-emerald-700 dark:text-emerald-400 font-mono">
                  ₹{rec.target1Premium?.toFixed(1)}
                </span>
                <span className="text-[10px] text-emerald-600 dark:text-emerald-400 block">Book 50% lot</span>
              </div>

              {/* Target 2 */}
              <div className="p-3 rounded-xl border border-emerald-200 dark:border-emerald-500/20 bg-emerald-50/50 dark:bg-emerald-500/10">
                <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold block">Target 2 (1.85R)</span>
                <span className="text-base font-bold text-emerald-700 dark:text-emerald-400 font-mono">
                  ₹{rec.target2Premium?.toFixed(1)}
                </span>
                <span className="text-[10px] text-emerald-600 dark:text-emerald-400 block">Runner target</span>
              </div>

              {/* Target 3 */}
              <div className="p-3 rounded-xl border border-emerald-200 dark:border-emerald-500/20 bg-emerald-50/50 dark:bg-emerald-500/10">
                <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold block">Target 3 (2.5R)</span>
                <span className="text-base font-bold text-emerald-700 dark:text-emerald-400 font-mono">
                  ₹{rec.target3Premium?.toFixed(1)}
                </span>
                <span className="text-[10px] text-emerald-600 dark:text-emerald-400 block">Trend stretch</span>
              </div>
            </div>

            {/* DO-NOT-CHASE THRESHOLD & EXECUTION CAUTION */}
            <div className="rounded-xl border border-amber-200 dark:border-amber-500/20 bg-amber-50 dark:bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-200 flex items-center gap-2.5">
              <AlertOctagon className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
              <div>
                <span className="font-bold">DO-NOT-CHASE THRESHOLD: </span>
                <span className="font-mono">{rec.doNotChaseThreshold}</span>
              </div>
            </div>

            {/* Triggers, Confirmation & Invalidation Details */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-3">
              {/* Entry Confirmation Condition */}
              <div className="space-y-2 p-3.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
                <div className="flex items-center gap-1.5 text-xs font-bold text-[var(--text-primary)]">
                  <CheckCircle className="w-4 h-4 text-emerald-500" />
                  Entry Confirmation Condition
                </div>
                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                  {rec.entryConfirmationCondition}
                </p>
                <div className="text-[11px] text-[var(--text-muted)] pt-2 border-t border-[var(--border-subtle)]">
                  Holding Horizon: <span className="font-medium text-[var(--text-secondary)]">{rec.estimatedHoldingHorizon}</span>
                </div>
              </div>

              {/* Invalidation Condition */}
              <div className="space-y-2 p-3.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
                <div className="flex items-center gap-1.5 text-xs font-bold text-rose-600 dark:text-rose-400">
                  <AlertOctagon className="w-4 h-4 text-rose-500" />
                  Invalidating Condition (Immediate Exit)
                </div>
                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                  {rec.invalidationCondition}
                </p>
                <div className="text-[11px] text-[var(--text-muted)] pt-2 border-t border-[var(--border-subtle)]">
                  Underlying Trigger: <span className="font-mono text-[var(--text-secondary)]">{rec.underlyingTrigger}</span>
                </div>
              </div>
            </div>

            {/* Greeks, Liquidity & Risk Stats */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 pt-3 text-xs">
              <div className="p-2.5 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
                <span className="text-[10px] text-[var(--text-muted)] block font-medium">Contract Liquidity</span>
                <span className="font-bold text-[var(--text-primary)]">
                  {rec.liquidityAssessment} ({rec.contractOpenInterest?.toLocaleString('en-IN') || '—'} OI)
                </span>
              </div>
              <div className="p-2.5 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
                <span className="text-[10px] text-[var(--text-muted)] block font-medium">Theta Decay</span>
                <span className="font-bold text-rose-600 dark:text-rose-400 font-mono">
                  {rec.greeks?.thetaPerDay?.toFixed(1) || '-12.5'} ₹/day
                </span>
              </div>
              <div className="p-2.5 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
                <span className="text-[10px] text-[var(--text-muted)] block font-medium">Max Risk / Lot ({rec.financialImpact?.lotSize || 25} qty)</span>
                <span className="font-bold text-rose-600 dark:text-rose-400 font-mono">
                  ₹{rec.financialImpact?.maxRiskINR?.toLocaleString('en-IN') || '—'}
                </span>
              </div>
              <div className="p-2.5 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
                <span className="text-[10px] text-[var(--text-muted)] block font-medium">Potential Gain / Lot (Target 2)</span>
                <span className="font-bold text-emerald-600 dark:text-emerald-400 font-mono">
                  ₹{rec.financialImpact?.potentialRewardINR?.toLocaleString('en-IN') || '—'}
                </span>
              </div>
            </div>

            {/* Reasons for Selection */}
            {rec.reasonsForSelection && rec.reasonsForSelection.length > 0 && (
              <div className="space-y-2 pt-3">
                <span className="text-xs font-bold text-[var(--text-primary)] block">
                  Institutional Selection Criteria Met:
                </span>
                <ul className="space-y-1">
                  {rec.reasonsForSelection.map((r, i) => (
                    <li key={i} className="text-xs text-[var(--text-secondary)] flex items-start gap-2">
                      <span className="text-emerald-500 font-bold">•</span>
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Clear Distinction Banner (Crucial Requirement C) */}
      <div className="rounded-xl bg-[var(--bg-surface-elevated)] p-4 border border-[var(--border-subtle)] space-y-2 text-xs text-[var(--text-muted)]">
        <div className="text-xs font-bold text-[var(--text-secondary)] flex items-center gap-1.5">
          <ShieldCheck className="w-4 h-4 text-indigo-500" />
          Execution Distinction & Compliance Notice
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 pt-1 text-[11px] leading-relaxed">
          <div>
            <span className="font-semibold text-[var(--text-primary)]">1. Last Observed Premium:</span> Verified market print from prior close.
          </div>
          <div>
            <span className="font-semibold text-[var(--text-primary)]">2. Planned Entry Premium:</span> Calculated mathematical band for opening auction.
          </div>
          <div>
            <span className="font-semibold text-[var(--text-primary)]">3. Actual Fill Price:</span> Unavailable (Platform is purely analytical and does not trade).
          </div>
          <div>
            <span className="font-semibold text-[var(--text-primary)]">4. Calculated Exits:</span> Strict stops and targets based on volatility models.
          </div>
        </div>
      </div>
    </div>
  );
};
