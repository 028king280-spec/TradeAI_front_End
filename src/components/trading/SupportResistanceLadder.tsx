'use client';

import React from 'react';
import { SupportResistanceLadder, SupportResistanceItem } from '@/types/options';
import { ShieldCheck, TrendingUp, TrendingDown, Layers, Activity } from 'lucide-react';
import { formatINR } from '@/lib/utils';

interface SupportResistanceLadderProps {
  data: SupportResistanceLadder;
  currentPrice: number;
}

export const SupportResistanceLadderView: React.FC<SupportResistanceLadderProps> = ({
  data,
  currentPrice,
}) => {
  if (!data || !data.ladder) return null;

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 sm:p-5 shadow-sm space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
            <Layers className="w-4 h-4 text-blue-500" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)] font-mono">
              Support & Resistance Ladder
            </h3>
            <span className="text-[10px] text-[var(--text-muted)] font-mono">
              Price-Action Pivots vs Option-Chain (OI) Walls
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3 text-[10px] font-mono">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-blue-500"></span> Price-Derived
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-500"></span> Option-Chain (OI)
          </span>
        </div>
      </div>

      {/* Ladder Items */}
      <div className="space-y-2">
        {data.ladder.map((item, idx) => {
          const isSpot = item.levelType === 'SPOT';
          const isResistance = item.role.startsWith('Resistance') || item.role.includes('Call Wall');
          const isSupport = item.role.startsWith('Support') || item.role.includes('Put Wall');
          const isOptionChain = item.levelType === 'OPTION_CHAIN';

          if (isSpot) {
            return (
              <div
                key={idx}
                className="py-2.5 px-4 rounded-lg bg-blue-600 text-white font-mono flex items-center justify-between shadow-sm my-1"
              >
                <div className="flex items-center gap-2">
                  <Activity className="w-4 h-4 animate-pulse" />
                  <span className="font-bold text-xs uppercase tracking-wider">Spot Price</span>
                </div>
                <span className="text-sm font-bold tracking-tight">₹{currentPrice.toLocaleString('en-IN')}</span>
              </div>
            );
          }

          return (
            <div
              key={idx}
              className={`p-3 rounded-lg border font-mono transition-all flex items-center justify-between ${
                isOptionChain
                  ? 'bg-amber-500/5 border-amber-500/30'
                  : isResistance
                  ? 'bg-rose-500/5 border-rose-500/20'
                  : 'bg-emerald-500/5 border-emerald-500/20'
              }`}
            >
              <div className="flex items-center gap-3">
                <span
                  className={`text-[9px] px-1.5 py-0.5 rounded font-bold uppercase ${
                    isOptionChain
                      ? 'bg-amber-500/20 text-amber-600 dark:text-amber-400'
                      : isResistance
                      ? 'bg-rose-500/20 text-rose-600 dark:text-rose-400'
                      : 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400'
                  }`}
                >
                  {item.role}
                </span>
                <div>
                  <div className="text-xs font-semibold text-[var(--text-primary)]">
                    {item.label}
                  </div>
                  <div className="text-[10px] text-[var(--text-muted)]">
                    {item.calculationMethod} • {item.confirmationStatus}
                  </div>
                </div>
              </div>

              <div className="text-right">
                <div className="text-xs font-bold text-[var(--text-primary)]">
                  ₹{item.price.toLocaleString('en-IN')}
                </div>
                <div
                  className={`text-[10px] font-semibold ${
                    item.distancePercent >= 0 ? 'text-rose-500' : 'text-emerald-500'
                  }`}
                >
                  {item.distancePercent >= 0 ? `+${item.distancePercent}%` : `${item.distancePercent}%`}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
