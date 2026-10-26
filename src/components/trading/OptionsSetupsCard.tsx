'use client';

import React from 'react';
import { TodayOptionsSetupsResult, OptionTradeSetup } from '@/types/options';
import { Zap, ShieldCheck, AlertCircle, ArrowUpRight, ArrowDownRight, Target, Clock, Info } from 'lucide-react';
import { formatINR } from '@/lib/utils';

interface OptionsSetupsCardProps {
  data: TodayOptionsSetupsResult;
}

export const OptionsSetupsCard: React.FC<OptionsSetupsCardProps> = ({ data }) => {
  if (!data || !data.hasQualifiedSetups || !data.setups || data.setups.length === 0) {
    return (
      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-5 space-y-3">
        <div className="flex items-center gap-2.5 text-amber-600 dark:text-amber-400">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <h3 className="text-sm font-bold font-mono tracking-tight">
            NO QUALIFIED SETUP — WAIT FOR BETTER CONDITIONS
          </h3>
        </div>
        <p className="text-xs text-[var(--text-secondary)] font-mono leading-relaxed">
          {data?.disqualificationReasons?.length
            ? data.disqualificationReasons[0]
            : 'Current market exhibits compression or ambiguous options open interest. Directional option buying carries high theta risk in these conditions.'}
        </p>
        <div className="pt-2 border-t border-amber-500/15 flex items-center justify-between text-[11px] font-mono text-[var(--text-muted)]">
          <span>Advice: {data?.advice || 'Wait for decisive breakout or fresh institutional OI buildup.'}</span>
          <span>Checked: {data?.timestamp || 'Current Session'}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between pb-1">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
            <Zap className="w-4 h-4 text-emerald-500" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)] font-mono">
              TODAY'S OPTIONS SETUPS
            </h3>
            <span className="text-[10px] text-[var(--text-muted)] font-mono">
              Institutional derivatives qualification (Strict Risk-Reward ≥ 1:1.8)
            </span>
          </div>
        </div>
        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-semibold">
          {data.setups.length} Qualified Candidate(s)
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {data.setups.map((setup, idx) => {
          const isCall = setup.bias === 'CE';

          return (
            <div
              key={idx}
              className={`rounded-xl border p-4 font-mono transition-all hover:shadow-md ${
                isCall
                  ? 'border-blue-500/30 bg-blue-500/5 hover:border-blue-500/50'
                  : 'border-amber-500/30 bg-amber-500/5 hover:border-amber-500/50'
              }`}
            >
              {/* Card Header */}
              <div className="flex items-start justify-between pb-3 border-b border-[var(--border-subtle)]">
                <div>
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`text-xs px-2 py-0.5 rounded font-bold ${
                        isCall
                          ? 'bg-blue-600 text-white'
                          : 'bg-amber-600 text-white'
                      }`}
                    >
                      {setup.bias}
                    </span>
                    <span className="text-xs font-bold text-[var(--text-primary)]">{setup.contractSymbol}</span>
                  </div>
                  <div className="text-[10px] text-[var(--text-muted)] mt-1">
                    Expiry: {setup.expiry} • Strike: {setup.strike}
                  </div>
                </div>

                <div className="text-right">
                  <div className="text-[10px] text-[var(--text-muted)] uppercase">LTP</div>
                  <div className="text-base font-bold text-[var(--text-primary)]">
                    ₹{setup.currentPremium.toFixed(2)}
                  </div>
                </div>
              </div>

              {/* Pricing & Targets Ladder */}
              <div className="py-3 border-b border-[var(--border-subtle)] grid grid-cols-2 gap-2 text-xs">
                <div>
                  <span className="text-[10px] text-[var(--text-muted)] block">Entry Range:</span>
                  <span className="font-semibold text-[var(--text-primary)]">{setup.entryRange}</span>
                </div>
                <div>
                  <span className="text-[10px] text-rose-500 block">Stop-Loss (Premium):</span>
                  <span className="font-bold text-rose-500">₹{setup.stopLoss}</span>
                </div>
                <div>
                  <span className="text-[10px] text-emerald-500 block">Target 1 (1.2R):</span>
                  <span className="font-bold text-emerald-500">₹{setup.target1}</span>
                </div>
                <div>
                  <span className="text-[10px] text-emerald-600 block">Target 2 (1.85R):</span>
                  <span className="font-bold text-emerald-600">₹{setup.target2}</span>
                </div>
              </div>

              {/* Greeks & Risk Metrics */}
              <div className="py-2.5 border-b border-[var(--border-subtle)] flex items-center justify-between text-[11px] text-[var(--text-muted)]">
                <span>Delta: <strong className="text-[var(--text-primary)]">{setup.greeks.delta}</strong></span>
                <span>Theta: <strong className="text-rose-400">{setup.greeks.thetaPerDay}/d</strong></span>
                <span>IV: <strong className="text-[var(--text-primary)]">{setup.iv}%</strong></span>
                <span>R:R: <strong className="text-emerald-500">{setup.riskRewardRatio}</strong></span>
              </div>

              {/* Triggers & Invalidation */}
              <div className="pt-3 space-y-2 text-[11px]">
                <div>
                  <span className="text-[10px] text-[var(--text-muted)] block uppercase font-semibold">
                    Underlying Trigger:
                  </span>
                  <p className="text-[var(--text-secondary)] leading-snug">{setup.underlyingTrigger}</p>
                </div>
                <div>
                  <span className="text-[10px] text-rose-500 block uppercase font-semibold">
                    Invalidation Condition:
                  </span>
                  <p className="text-[var(--text-muted)] leading-snug">{setup.invalidationCondition}</p>
                </div>
              </div>

              {/* Disclaimer */}
              <div className="mt-3 pt-2 border-t border-[var(--border-subtle)] text-[9px] text-[var(--text-muted)] flex items-center gap-1">
                <ShieldCheck className="w-3 h-3 text-blue-500 shrink-0" />
                <span>Analytical observation idea. No order placement or guaranteed return.</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
