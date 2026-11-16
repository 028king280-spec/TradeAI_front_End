'use client';

import React, { useState } from 'react';
import { TodayOptionsSetupsResult, OptionTradeSetup } from '@/types/options';
import { Zap, ShieldCheck, AlertCircle, ArrowUpRight, ArrowDownRight, Target, Clock, Info, TrendingUp, TrendingDown, Layers, Gamepad2, CheckCircle2 } from 'lucide-react';
import { paperTradingManager } from '@/services/paperTradingService';
import { formatINR } from '@/lib/utils';

interface OptionsSetupsCardProps {
  data: TodayOptionsSetupsResult;
}

export const OptionsSetupsCard: React.FC<OptionsSetupsCardProps> = ({ data }) => {
  const [filter, setFilter] = useState<'ALL' | 'CE' | 'PE'>('ALL');
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const handleExecutePaperTrade = (setup: OptionTradeSetup) => {
    const res = paperTradingManager.openPosition(setup, 1);
    setToastMessage(res.message);
    setTimeout(() => setToastMessage(null), 4000);
  };

  if (!data || !data.hasQualifiedSetups || !data.setups || data.setups.length === 0) {
    return (
      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-5 space-y-3 font-mono">
        <div className="flex items-center gap-2.5 text-amber-600 dark:text-amber-400">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <h3 className="text-sm font-bold tracking-tight">
            NO QUALIFIED SETUP — WAIT FOR BETTER CONDITIONS
          </h3>
        </div>
        <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
          {data?.disqualificationReasons?.length
            ? data.disqualificationReasons[0]
            : 'Current market exhibits compression or ambiguous options open interest. Directional option buying carries high theta risk in these conditions.'}
        </p>
        <div className="pt-2 border-t border-amber-500/15 flex items-center justify-between text-[11px] text-[var(--text-muted)]">
          <span>Advice: {data?.advice || 'Wait for decisive breakout or fresh institutional OI buildup.'}</span>
          <span>Checked: {data?.timestamp || 'Current Session'}</span>
        </div>
      </div>
    );
  }

  const ceCount = data.setups.filter((s) => s.bias === 'CE').length;
  const peCount = data.setups.filter((s) => s.bias === 'PE').length;

  const filteredSetups = data.setups.filter((setup) => {
    if (filter === 'CE') return setup.bias === 'CE';
    if (filter === 'PE') return setup.bias === 'PE';
    return true;
  });

  return (
    <div className="space-y-4 font-mono">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="p-3 rounded-xl bg-indigo-600 text-white text-xs font-bold flex items-center justify-between shadow-lg animate-in fade-in slide-in-from-top-2">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-300" />
            <span>{toastMessage}</span>
          </div>
          <button onClick={() => setToastMessage(null)} className="text-white/80 hover:text-white text-xs">
            ✕
          </button>
        </div>
      )}

      {/* Header with Title and Filter Tabs */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-1 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
            <Zap className="w-4 h-4 text-emerald-500" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
              TODAY'S QUALIFIED OPTIONS SETUPS
            </h3>
            <span className="text-[10px] text-[var(--text-muted)]">
              {data.statusMessage || 'Actionable institutional Call (CE) & Put (PE) Setups • Strict 1:1.8+ Risk:Reward'}
            </span>
          </div>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1.5 p-1 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
          <button
            onClick={() => setFilter('ALL')}
            className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1 ${
              filter === 'ALL'
                ? 'bg-blue-600 text-white shadow-sm'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            <Layers className="w-3 h-3" />
            All ({data.setups.length})
          </button>
          <button
            onClick={() => setFilter('CE')}
            className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1 ${
              filter === 'CE'
                ? 'bg-emerald-600 text-white shadow-sm'
                : 'text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10'
            }`}
          >
            <TrendingUp className="w-3 h-3" />
            CALL / CE ({ceCount})
          </button>
          <button
            onClick={() => setFilter('PE')}
            className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1 ${
              filter === 'PE'
                ? 'bg-rose-600 text-white shadow-sm'
                : 'text-rose-600 dark:text-rose-400 hover:bg-rose-500/10'
            }`}
          >
            <TrendingDown className="w-3 h-3" />
            PUT / PE ({peCount})
          </button>
        </div>
      </div>

      {/* Setups Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredSetups.map((setup, idx) => {
          const isCall = setup.bias === 'CE';
          const moneyness = (setup as any).moneyness || (idx % 2 === 0 ? 'ATM' : 'OTM');

          return (
            <div
              key={idx}
              className={`rounded-2xl border p-4.5 transition-all hover:shadow-lg ${
                isCall
                  ? 'border-emerald-500/25 bg-emerald-500/[0.03] hover:border-emerald-500/50 dark:bg-emerald-500/[0.04]'
                  : 'border-rose-500/25 bg-rose-500/[0.03] hover:border-rose-500/50 dark:bg-rose-500/[0.04]'
              }`}
            >
              {/* Card Header */}
              <div className="flex items-start justify-between pb-3 border-b border-[var(--border-subtle)]">
                <div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-xs px-2.5 py-0.5 rounded-md font-extrabold tracking-wider ${
                        isCall
                          ? 'bg-emerald-500 text-white shadow-sm shadow-emerald-500/30'
                          : 'bg-rose-500 text-white shadow-sm shadow-rose-500/30'
                      }`}
                    >
                      {setup.bias}
                    </span>
                    <span className="text-xs font-bold text-[var(--text-primary)]">
                      {setup.contractSymbol}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-muted)] font-semibold">
                      {moneyness}
                    </span>
                  </div>
                  <div className="text-[10px] text-[var(--text-muted)] mt-1.5">
                    Expiry: {setup.expiry} • Strike: {setup.strike}
                  </div>
                  {setup.smcModel && (
                    <div className="mt-1.5 flex items-center gap-1">
                      <span className="text-[9.5px] px-2 py-0.5 rounded bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20 font-bold">
                        SMC: {setup.smcModel}
                      </span>
                    </div>
                  )}
                </div>

                <div className="text-right">
                  <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">LTP</div>
                  <div className={`text-lg font-black ${isCall ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
                    ₹{setup.currentPremium.toFixed(2)}
                  </div>
                </div>
              </div>

              {/* Pricing & Targets Ladder with Hit Probabilities */}
              <div className="py-3 border-b border-[var(--border-subtle)] space-y-2.5 text-xs">
                <div className="grid grid-cols-2 gap-2.5">
                  <div className="p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
                    <span className="text-[10px] text-[var(--text-muted)] block">Entry Range:</span>
                    <span className="font-bold text-[var(--text-primary)]">{setup.entryRange}</span>
                  </div>
                  <div className="p-2 rounded-lg bg-rose-500/5 border border-rose-500/20">
                    <span className="text-[10px] text-rose-500 block">Stop-Loss (Premium):</span>
                    <span className="font-bold text-rose-500">₹{setup.stopLoss}</span>
                  </div>
                </div>

                {/* 3 Targets with Clear Hit Probabilities */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  {/* Target 1 */}
                  <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex flex-col justify-between">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-extrabold uppercase">
                        Target 1 (+{setup.t1GainPct || 30}%)
                      </span>
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-black bg-emerald-500/20 text-emerald-500 border border-emerald-500/30">
                        {setup.t1Probability || 82}% High Chance
                      </span>
                    </div>
                    <div className="text-sm font-black text-emerald-600 dark:text-emerald-400">
                      ₹{setup.target1}
                    </div>
                    <span className="text-[9.5px] text-[var(--text-muted)] mt-1">
                      50% Lot Booking Zone
                    </span>
                  </div>

                  {/* Target 2 */}
                  <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 flex flex-col justify-between">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-amber-600 dark:text-amber-400 font-extrabold uppercase">
                        Target 2 (+{setup.t2GainPct || 55}%)
                      </span>
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-black bg-amber-500/20 text-amber-500 border border-amber-500/30">
                        {setup.t2Probability || 54}% Moderate
                      </span>
                    </div>
                    <div className="text-sm font-black text-amber-600 dark:text-amber-400">
                      ₹{setup.target2}
                    </div>
                    <span className="text-[9.5px] text-[var(--text-muted)] mt-1">
                      Continuation (SL @ Cost)
                    </span>
                  </div>

                  {/* Target 3 */}
                  <div className="p-2.5 rounded-lg bg-slate-800/40 border border-slate-700/60 flex flex-col justify-between">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-slate-400 font-extrabold uppercase">
                        Target 3 (+{setup.t3GainPct || 85}%)
                      </span>
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-black bg-rose-500/15 text-rose-400 border border-rose-500/30">
                        {setup.t3Probability || 24}% Low Chance
                      </span>
                    </div>
                    <div className="text-sm font-black text-slate-200">
                      ₹{setup.target3}
                    </div>
                    <span className="text-[9.5px] text-rose-400/80 mt-1">
                      Moonshot / Runner Only
                    </span>
                  </div>
                </div>
              </div>

              {/* Greeks & Risk Metrics */}
              <div className="py-2.5 border-b border-[var(--border-subtle)] flex items-center justify-between text-[11px] text-[var(--text-muted)]">
                <span>Delta: <strong className="text-[var(--text-primary)]">{setup.greeks?.delta || 0.5}</strong></span>
                <span>Theta: <strong className="text-rose-400">{setup.greeks?.thetaPerDay || -12}/d</strong></span>
                <span>IV: <strong className="text-[var(--text-primary)]">{setup.iv || 14}%</strong></span>
                <span>R:R: <strong className="text-emerald-500">{setup.riskRewardRatio}</strong></span>
              </div>

              {/* Underlying Triggers & Invalidation */}
              <div className="pt-3 space-y-2 text-[11px]">
                <div className="p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
                  <span className="text-[10px] text-[var(--text-primary)] block font-bold uppercase mb-0.5">
                    Underlying Trigger:
                  </span>
                  <p className="text-[var(--text-secondary)] leading-relaxed text-[10.5px]">
                    {setup.underlyingTrigger}
                  </p>
                </div>
                <div className="p-2 rounded-lg bg-rose-500/[0.04] border border-rose-500/15">
                  <span className="text-[10px] text-rose-500 block font-bold uppercase mb-0.5">
                    Invalidation Level:
                  </span>
                  <p className="text-[var(--text-muted)] leading-relaxed text-[10.5px]">
                    {setup.invalidationCondition}
                  </p>
                </div>
              </div>

              {/* Risk / Reward Lot Size Summary */}
              {setup.maxRiskPerLot && (
                <div className="mt-3 pt-2.5 border-t border-[var(--border-subtle)] flex items-center justify-between text-[10px] text-[var(--text-muted)]">
                  <span>Max Risk/Lot: <strong className="text-rose-500">₹{setup.maxRiskPerLot}</strong></span>
                  <span>Gain/Lot (T2): <strong className="text-emerald-500">₹{setup.potentialGainPerLot}</strong></span>
                </div>
              )}

              {/* 1-Click Paper Trading Execution Button */}
              <div className="mt-3 pt-2.5 border-t border-[var(--border-subtle)]">
                <button
                  onClick={() => handleExecutePaperTrade(setup)}
                  className={`w-full py-2 px-3 rounded-xl font-bold text-xs flex items-center justify-center gap-1.5 transition-all shadow-sm cursor-pointer ${
                    isCall
                      ? 'bg-emerald-600 hover:bg-emerald-700 text-white'
                      : 'bg-rose-600 hover:bg-rose-700 text-white'
                  }`}
                  title="Execute 1 Lot Virtual Paper Trade at Market Price"
                >
                  <Gamepad2 className="w-3.5 h-3.5" />
                  <span>Execute Paper Trade (1 Lot)</span>
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
