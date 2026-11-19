'use client';

import React, { useState } from 'react';
import type { ResearchSetupEvaluation, OptionTradeSetup } from '@/types/options';
import { Target, Zap, Shield, TrendingUp, BarChart3, Gamepad2, CheckCircle2, AlertCircle, ArrowUpRight } from 'lucide-react';
import { paperTradingManager } from '@/services/paperTradingService';

interface ResearchSetupCardProps {
  data?: ResearchSetupEvaluation | null;
  indexSymbol?: string;
}

export function ResearchSetupCard({ data, indexSymbol = 'NIFTY 50' }: ResearchSetupCardProps) {
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const setup = data?.qualified ? data.setup : null;
  const score = data?.score ?? 0;
  const threshold = data?.threshold ?? 60;
  const isQualified = Boolean(data?.qualified && setup);

  const handleExecutePaperTrade = () => {
    if (!setup) return;

    const optType = setup.contractSymbol.endsWith('CE') ? 'CE' : 'PE';
    const lotSize = indexSymbol.includes('BANK') ? 15 : indexSymbol.includes('SENSEX') ? 10 : 65;

    const optionSetup: OptionTradeSetup = {
      index: indexSymbol,
      bias: optType,
      biasLabel: `${indexSymbol} ${setup.contractSymbol}`,
      contractSymbol: setup.contractSymbol,
      strike: Number((setup as any).strike || 0),
      expiry: (setup as any).expiry || 'Current Expiry',
      entryRange: `₹${setup.entryPremium.toFixed(1)} - ₹${(setup.entryPremium * 1.02).toFixed(1)}`,
      currentPremium: setup.entryPremium,
      stopLoss: setup.stopLoss,
      target1: setup.targetPremium,
      target2: Math.round(setup.targetPremium * 1.15 * 10) / 10,
      target3: Math.round(setup.targetPremium * 1.30 * 10) / 10,
      riskRewardRatio: `${setup.grossRewardRisk.toFixed(1)}:1`,
      maxRiskPerLot: Math.round((setup.entryPremium - setup.stopLoss) * lotSize),
      potentialGainPerLot: Math.round((setup.targetPremium - setup.entryPremium) * lotSize),
      greeks: { delta: optType === 'CE' ? 0.50 : -0.50, gamma: 0.001, thetaPerDay: -12, vega: 1.0 },
      iv: 14.5,
      liquidity: 'HIGH',
      openInterest: 100000,
      changeInOi: 0,
      underlyingTrigger: '60-Point Confluence Research Trigger',
      invalidationCondition: `Premium drops below SL ₹${setup.stopLoss.toFixed(2)}`,
      supportingReasons: data?.reasons || ['Qualified on 60-point confluence research hurdle.'],
      disclaimer: 'Research Paper Setup (60-pt threshold, +30% target)',
      smcModel: 'Research Engine (60-pt Profile)',
    };

    const res = paperTradingManager.openPosition(optionSetup, 1);
    setToastMessage(res.message);
    setTimeout(() => setToastMessage(null), 5000);
  };

  return (
    <section className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-5 sm:p-6 space-y-4 shadow-sm" aria-label="60-Point Research Setup Engine">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="p-3 rounded-xl bg-emerald-600 text-white text-xs font-semibold flex items-center justify-between shadow-lg animate-in fade-in">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-200" />
            <span>{toastMessage}</span>
          </div>
          <button onClick={() => setToastMessage(null)} className="text-white/80 hover:text-white text-xs">
            ✕
          </button>
        </div>
      )}

      {/* Card Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-[var(--accent-blue-bg)] dark:bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 flex items-center justify-center text-[var(--accent-blue)]">
            <Zap className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--accent-blue)]">
                Secondary Engine • 60% Hurdle
              </span>
              <span
                className={`text-[10px] px-2 py-0.5 rounded-md font-semibold border ${
                  isQualified
                    ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20'
                    : 'bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-500/20'
                }`}
              >
                {isQualified ? 'QUALIFIED (60-PT RESEARCH)' : 'WAITING FOR 60+ CONFLUENCE'}
              </span>
            </div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mt-0.5">
              60-Point Research Engine • +30% Target
            </h3>
          </div>
        </div>

        {/* Score Pill & Action Button */}
        <div className="flex items-center gap-2.5">
          <div className="px-3 py-1 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-xs font-semibold tabular-nums text-[var(--text-primary)] flex items-center gap-1.5">
            <BarChart3 className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
            <span>Confluence: {score > 0 ? `${score.toFixed(1)}/100` : 'Evaluating'}</span>
          </div>

          {isQualified && (
            <button
              onClick={handleExecutePaperTrade}
              className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm cursor-pointer"
            >
              <Gamepad2 className="w-3.5 h-3.5" />
              <span>1-Click Paper Trade (60-pt)</span>
            </button>
          )}
        </div>
      </div>

      {/* Main Content Area */}
      {isQualified && setup ? (
        <div className="space-y-3.5">
          {/* Contract Banner */}
          <div className="flex items-center justify-between p-3.5 rounded-xl bg-emerald-50/50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20">
            <div className="flex items-center gap-2.5">
              <span className={`text-xs px-2 py-0.5 rounded font-bold text-white ${setup.contractSymbol.endsWith('CE') ? 'bg-emerald-600' : 'bg-rose-600'}`}>
                {setup.contractSymbol.endsWith('CE') ? 'CALL (CE)' : 'PUT (PE)'}
              </span>
              <span className="font-semibold text-sm text-[var(--text-primary)] tracking-wide">
                {setup.contractSymbol}
              </span>
            </div>
            <span className="text-xs font-semibold text-emerald-700 dark:text-emerald-300">
              Reward/Risk: {setup.grossRewardRisk.toFixed(2)}:1
            </span>
          </div>

          {/* Pricing Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="p-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)]">
              <span className="text-[10px] text-[var(--text-muted)] block font-medium uppercase">Entry Premium</span>
              <span className="text-sm font-bold text-[var(--text-primary)] tabular-nums">
                ₹{setup.entryPremium.toFixed(2)}
              </span>
            </div>
            <div className="p-3 rounded-xl border border-emerald-200 dark:border-emerald-500/20 bg-emerald-50/30 dark:bg-emerald-500/5">
              <span className="text-[10px] text-emerald-600 dark:text-emerald-400 block font-medium uppercase">Target (+30%)</span>
              <span className="text-sm font-bold text-emerald-600 dark:text-emerald-400 tabular-nums">
                ₹{setup.targetPremium.toFixed(2)}
              </span>
            </div>
            <div className="p-3 rounded-xl border border-rose-200 dark:border-rose-500/20 bg-rose-50/30 dark:bg-rose-500/5">
              <span className="text-[10px] text-rose-600 dark:text-rose-400 block font-medium uppercase">Stop-Loss</span>
              <span className="text-sm font-bold text-rose-600 dark:text-rose-400 tabular-nums">
                ₹{setup.stopLoss.toFixed(2)}
              </span>
            </div>
            <div className="p-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)]">
              <span className="text-[10px] text-[var(--text-muted)] block font-medium uppercase">Gross Edge</span>
              <span className="text-sm font-bold text-[var(--accent-blue)] tabular-nums">
                +{((setup.targetPremium - setup.entryPremium) / setup.entryPremium * 100).toFixed(1)}%
              </span>
            </div>
          </div>
        </div>
      ) : (
        /* Not Qualified State with Progress Towards 60-Point Hurdle */
        <div className="rounded-xl border border-dashed border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)]/50 p-4 space-y-3">
          <div className="flex items-center justify-between text-xs">
            <span className="text-[var(--text-secondary)] font-medium flex items-center gap-1.5">
              <Target className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
              60-Point Confluence Hurdle Progress:
            </span>
            <span className="font-bold tabular-nums text-[var(--text-primary)]">
              {score.toFixed(1)} / {threshold}.0 pts ({Math.min(100, Math.round((score / threshold) * 100))}%)
            </span>
          </div>

          {/* Progress Bar */}
          <div className="w-full bg-[var(--border-subtle)] h-2 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                score >= threshold ? 'bg-emerald-500' : score >= 40 ? 'bg-amber-500' : 'bg-[var(--accent-blue)]'
              }`}
              style={{ width: `${Math.min(100, Math.max(5, (score / threshold) * 100))}%` }}
            />
          </div>

          <p className="text-xs text-[var(--text-muted)] leading-relaxed">
            {data && data.reasons && data.reasons.length > 0
              ? data.reasons.join(' • ')
              : 'The 60-point research engine triggers aggressive momentum setups with lower confluence threshold than the 80-pt production engine.'}
          </p>
        </div>
      )}

      {/* Footer link to Research Paper Ledger */}
      <div className="flex items-center justify-between pt-1 text-xs text-[var(--text-muted)]">
        <span>Eligible for automatic simulation in research journal</span>
        <a href="/paper-trading" className="text-[var(--accent-blue)] hover:underline font-medium inline-flex items-center gap-1">
          <span>View Research Journal</span>
          <ArrowUpRight className="w-3 h-3" />
        </a>
      </div>
    </section>
  );
}
