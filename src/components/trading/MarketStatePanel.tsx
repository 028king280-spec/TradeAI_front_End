'use client';

import React from 'react';
import {
  ShieldAlert,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  ArrowUpRight,
  ArrowDownRight,
  CheckCircle2,
  Clock,
  Radio,
  Minus,
  WifiOff,
} from 'lucide-react';

export interface MarketStateData {
  symbol: string;
  marketState: 'BULLISH' | 'BEARISH' | 'SIDEWAYS' | 'NO_TRADE' | 'DATA_UNAVAILABLE';
  isNoTrade: boolean;
  prominentStatus?: string;
  statusBadge: string;
  headline: string;
  explanation: string;
  primaryReason: string;
  reasonForNoTrade?: string;
  contributingFactors: string[];
  keyLevels: {
    immediateSupport: number;
    immediateResistance: number;
    importantSupport?: number;
    importantResistance?: number;
    bullishActivationTrigger: string;
    bearishActivationTrigger: string;
    confirmationRequired: string;
  };
  dataStatus: string;
  dataTimestamp: string;
  analysisTimestamp: string;
}

interface MarketStatePanelProps {
  data: MarketStateData;
}

const stateConfig = {
  BULLISH: {
    icon: TrendingUp,
    gradient: 'from-emerald-500/8 via-emerald-500/3 to-transparent',
    darkGradient: 'dark:from-emerald-500/12 dark:via-emerald-500/4 dark:to-transparent',
    border: 'border-emerald-500/20 dark:border-emerald-500/25',
    iconBg: 'bg-emerald-50 dark:bg-emerald-500/15',
    iconColor: 'text-emerald-600 dark:text-emerald-400',
    badgeBg: 'bg-emerald-500',
    badgeText: 'text-white',
    pillBg: 'bg-emerald-50 dark:bg-emerald-500/10',
    pillText: 'text-emerald-700 dark:text-emerald-400',
    pillBorder: 'border-emerald-200 dark:border-emerald-500/25',
    accentRing: 'ring-emerald-500/20',
  },
  BEARISH: {
    icon: TrendingDown,
    gradient: 'from-rose-500/8 via-rose-500/3 to-transparent',
    darkGradient: 'dark:from-rose-500/12 dark:via-rose-500/4 dark:to-transparent',
    border: 'border-rose-500/20 dark:border-rose-500/25',
    iconBg: 'bg-rose-50 dark:bg-rose-500/15',
    iconColor: 'text-rose-600 dark:text-rose-400',
    badgeBg: 'bg-rose-500',
    badgeText: 'text-white',
    pillBg: 'bg-rose-50 dark:bg-rose-500/10',
    pillText: 'text-rose-700 dark:text-rose-400',
    pillBorder: 'border-rose-200 dark:border-rose-500/25',
    accentRing: 'ring-rose-500/20',
  },
  SIDEWAYS: {
    icon: Minus,
    gradient: 'from-amber-500/8 via-amber-500/3 to-transparent',
    darkGradient: 'dark:from-amber-500/10 dark:via-amber-500/3 dark:to-transparent',
    border: 'border-amber-500/20 dark:border-amber-500/25',
    iconBg: 'bg-amber-50 dark:bg-amber-500/15',
    iconColor: 'text-amber-600 dark:text-amber-400',
    badgeBg: 'bg-amber-500',
    badgeText: 'text-white',
    pillBg: 'bg-amber-50 dark:bg-amber-500/10',
    pillText: 'text-amber-700 dark:text-amber-400',
    pillBorder: 'border-amber-200 dark:border-amber-500/25',
    accentRing: 'ring-amber-500/20',
  },
  NO_TRADE: {
    icon: ShieldAlert,
    gradient: 'from-orange-500/8 via-red-500/3 to-transparent',
    darkGradient: 'dark:from-orange-500/10 dark:via-red-500/4 dark:to-transparent',
    border: 'border-orange-500/25 dark:border-orange-500/30',
    iconBg: 'bg-orange-50 dark:bg-orange-500/15',
    iconColor: 'text-orange-600 dark:text-orange-400',
    badgeBg: 'bg-orange-500',
    badgeText: 'text-white',
    pillBg: 'bg-orange-50 dark:bg-orange-500/10',
    pillText: 'text-orange-700 dark:text-orange-400',
    pillBorder: 'border-orange-200 dark:border-orange-500/25',
    accentRing: 'ring-orange-500/20',
  },
  DATA_UNAVAILABLE: {
    icon: WifiOff,
    gradient: 'from-slate-500/6 via-slate-500/2 to-transparent',
    darkGradient: 'dark:from-slate-500/10 dark:via-slate-500/3 dark:to-transparent',
    border: 'border-slate-300 dark:border-slate-600',
    iconBg: 'bg-slate-100 dark:bg-slate-700',
    iconColor: 'text-slate-500 dark:text-slate-400',
    badgeBg: 'bg-slate-500',
    badgeText: 'text-white',
    pillBg: 'bg-slate-100 dark:bg-slate-700',
    pillText: 'text-slate-600 dark:text-slate-400',
    pillBorder: 'border-slate-300 dark:border-slate-600',
    accentRing: 'ring-slate-500/20',
  },
};

export const MarketStatePanel: React.FC<MarketStatePanelProps> = ({ data }) => {
  const state = data.marketState;
  const config = stateConfig[state] || stateConfig.DATA_UNAVAILABLE;
  const StateIcon = config.icon;
  const isNoTradeOrSideways = state === 'NO_TRADE' || state === 'SIDEWAYS';

  return (
    <div
      className={`relative overflow-hidden rounded-2xl border bg-gradient-to-br ${config.gradient} ${config.darkGradient} ${config.border} bg-white dark:bg-[var(--bg-surface)] transition-all duration-300`}
    >
      {/* Decorative glow */}
      <div className="absolute top-0 right-0 w-72 h-72 rounded-full opacity-[0.04] blur-3xl pointer-events-none"
        style={{ background: state === 'BULLISH' ? '#10b981' : state === 'BEARISH' ? '#f43f5e' : state === 'NO_TRADE' ? '#f97316' : '#f59e0b' }}
      />

      <div className="relative p-5 sm:p-6">
        {/* Header Row */}
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 mb-5">
          <div className="flex items-start gap-3.5">
            {/* State Icon */}
            <div className={`w-11 h-11 rounded-xl ${config.iconBg} flex items-center justify-center shrink-0 ring-1 ${config.accentRing}`}>
              <StateIcon className={`w-5.5 h-5.5 ${config.iconColor}`} />
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider">
                  {data.symbol} Market Regime
                </span>
                <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-md ${config.pillBg} ${config.pillText} border ${config.pillBorder}`}>
                  {state.replace('_', ' ')}
                </span>
              </div>

              {/* Headline */}
              <h3 className="text-lg sm:text-xl font-bold text-[var(--text-primary)] leading-tight tracking-tight">
                {data.headline}
              </h3>
            </div>
          </div>

          {/* Status Badge + Data Status */}
          <div className="flex items-center gap-3 shrink-0">
            {/* Prominent NO TRADE / Status Badge */}
            <div className={`px-4 py-2 rounded-xl ${config.badgeBg} ${config.badgeText} font-extrabold text-sm tracking-wide flex items-center gap-2 shadow-lg`}>
              {isNoTradeOrSideways && (
                <span className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white/60" />
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-white/90" />
                </span>
              )}
              {isNoTradeOrSideways ? 'NO TRADE' : data.statusBadge}
            </div>

            {/* Live indicator */}
            <div className="hidden sm:flex flex-col items-end gap-0.5">
              <span className="text-[10px] font-medium text-[var(--text-muted)]">Feed</span>
              <span className={`text-xs font-bold flex items-center gap-1 ${data.dataStatus === 'LIVE' ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`}>
                <Radio className="w-3 h-3" />
                {data.dataStatus}
              </span>
            </div>
          </div>
        </div>

        {/* Analysis Explanation */}
        <div className="mb-4 p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            <strong className="text-[var(--text-primary)] font-semibold">Analysis: </strong>
            {data.explanation}
          </p>
        </div>

        {/* NO TRADE Reason Alert */}
        {isNoTradeOrSideways && (data.reasonForNoTrade || data.primaryReason) && (
          <div className={`mb-4 p-4 rounded-xl border ${state === 'NO_TRADE' ? 'bg-orange-50/80 dark:bg-orange-500/8 border-orange-200 dark:border-orange-500/20' : 'bg-amber-50/80 dark:bg-amber-500/8 border-amber-200 dark:border-amber-500/20'}`}>
            <div className="flex items-start gap-2.5">
              <AlertTriangle className={`w-4 h-4 shrink-0 mt-0.5 ${state === 'NO_TRADE' ? 'text-orange-500' : 'text-amber-500'}`} />
              <div className="space-y-1">
                <span className={`text-[10px] font-bold uppercase tracking-wider ${state === 'NO_TRADE' ? 'text-orange-600 dark:text-orange-400' : 'text-amber-600 dark:text-amber-400'}`}>
                  Reason for No Trade
                </span>
                <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
                  {data.reasonForNoTrade || data.primaryReason}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Contributing Factors */}
        {data.contributingFactors && data.contributingFactors.length > 0 && (
          <div className="mb-5 flex flex-wrap gap-2">
            {data.contributingFactors.map((factor, idx) => (
              <span
                key={idx}
                className="text-xs px-3 py-1.5 rounded-lg bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)] font-medium transition-colors hover:border-[var(--border-strong)]"
              >
                {factor}
              </span>
            ))}
          </div>
        )}

        {/* Activation Trigger Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
          <TriggerCard
            icon={<ArrowUpRight className="w-4 h-4" />}
            label="Bullish Activation"
            description={data.keyLevels.bullishActivationTrigger}
            color="emerald"
          />
          <TriggerCard
            icon={<ArrowDownRight className="w-4 h-4" />}
            label="Bearish Activation"
            description={data.keyLevels.bearishActivationTrigger}
            color="rose"
          />
          <TriggerCard
            icon={<CheckCircle2 className="w-4 h-4" />}
            label="Required Confirmation"
            description={data.keyLevels.confirmationRequired}
            color="indigo"
          />
        </div>

        {/* Footer: Timestamp + Key Levels */}
        <div className="pt-3 border-t border-[var(--border-subtle)] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-xs text-[var(--text-muted)]">
          <div className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            <span>{data.analysisTimestamp}</span>
          </div>
          <div className="flex items-center gap-3 font-medium">
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
              Support: ₹{data.keyLevels.importantSupport || data.keyLevels.immediateSupport}
            </span>
            <span className="text-[var(--border-strong)]">•</span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-500 inline-block" />
              Resistance: ₹{data.keyLevels.importantResistance || data.keyLevels.immediateResistance}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

/* Sub-component: Trigger Card */
function TriggerCard({
  icon,
  label,
  description,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  description: string;
  color: 'emerald' | 'rose' | 'indigo';
}) {
  const colorMap = {
    emerald: {
      iconColor: 'text-emerald-600 dark:text-emerald-400',
      bg: 'bg-emerald-50/60 dark:bg-emerald-500/6',
      border: 'border-emerald-200/60 dark:border-emerald-500/15',
      label: 'text-emerald-700 dark:text-emerald-400',
    },
    rose: {
      iconColor: 'text-rose-600 dark:text-rose-400',
      bg: 'bg-rose-50/60 dark:bg-rose-500/6',
      border: 'border-rose-200/60 dark:border-rose-500/15',
      label: 'text-rose-700 dark:text-rose-400',
    },
    indigo: {
      iconColor: 'text-indigo-600 dark:text-indigo-400',
      bg: 'bg-indigo-50/60 dark:bg-indigo-500/6',
      border: 'border-indigo-200/60 dark:border-indigo-500/15',
      label: 'text-indigo-700 dark:text-indigo-400',
    },
  };

  const c = colorMap[color];

  return (
    <div className={`p-3.5 rounded-xl ${c.bg} border ${c.border} transition-all hover:shadow-sm group`}>
      <div className={`flex items-center gap-1.5 mb-1.5 ${c.iconColor}`}>
        {icon}
        <span className={`text-[11px] font-bold uppercase tracking-wide ${c.label}`}>{label}</span>
      </div>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed font-medium">
        {description}
      </p>
    </div>
  );
}
