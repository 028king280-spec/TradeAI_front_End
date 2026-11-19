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
    badgeText: 'text-[var(--text-primary)]',
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
    badgeText: 'text-[var(--text-primary)]',
    pillBg: 'bg-rose-50 dark:bg-rose-500/10',
    pillText: 'text-rose-700 dark:text-rose-400',
    pillBorder: 'border-rose-200 dark:border-rose-500/25',
    accentRing: 'ring-rose-500/20',
  },
  SIDEWAYS: {
    icon: Minus,
    gradient: 'from-[var(--accent-blue)]/8 via-[var(--accent-blue)]/3 to-transparent',
    darkGradient: 'dark:from-[var(--accent-blue)]/10 dark:via-[var(--accent-blue)]/3 dark:to-transparent',
    border: 'border-[var(--accent-blue)]/20 dark:border-[var(--accent-blue)]/25',
    iconBg: 'bg-[var(--accent-blue-bg)] dark:bg-[var(--accent-blue)]/15',
    iconColor: 'text-[var(--accent-blue)] dark:text-[var(--accent-blue)]',
    badgeBg: 'bg-[var(--accent-blue)]',
    badgeText: 'text-[var(--text-primary)]',
    pillBg: 'bg-[var(--accent-blue-bg)] dark:bg-[var(--accent-blue)]/10',
    pillText: 'text-[var(--accent-blue)] dark:text-[var(--accent-blue)]',
    pillBorder: 'border-[var(--accent-blue)] dark:border-[var(--accent-blue)]/25',
    accentRing: 'ring-blue-500/20',
  },
  NO_TRADE: {
    icon: ShieldAlert,
    gradient: 'from-orange-500/8 via-red-500/3 to-transparent',
    darkGradient: 'dark:from-orange-500/10 dark:via-red-500/4 dark:to-transparent',
    border: 'border-orange-500/25 dark:border-orange-500/30',
    iconBg: 'bg-orange-50 dark:bg-orange-500/15',
    iconColor: 'text-orange-600 dark:text-orange-400',
    badgeBg: 'bg-orange-500',
    badgeText: 'text-[var(--text-primary)]',
    pillBg: 'bg-orange-50 dark:bg-orange-500/10',
    pillText: 'text-orange-700 dark:text-orange-400',
    pillBorder: 'border-orange-200 dark:border-orange-500/25',
    accentRing: 'ring-orange-500/20',
  },
  DATA_UNAVAILABLE: {
    icon: WifiOff,
    gradient: 'from-[var(--bg-surface)] via-[var(--bg-surface)] to-transparent',
    darkGradient: 'dark:from-[var(--bg-surface)] dark:via-[var(--bg-surface)] dark:to-transparent',
    border: 'border-[var(--border-subtle)] dark:border-[var(--border-subtle)]',
    iconBg: 'bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)]',
    iconColor: 'text-[var(--text-muted)] dark:text-[var(--text-secondary)]',
    badgeBg: 'bg-[var(--bg-surface-elevated)]',
    badgeText: 'text-[var(--text-primary)]',
    pillBg: 'bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)]',
    pillText: 'text-[var(--text-secondary)] dark:text-[var(--text-secondary)]',
    pillBorder: 'border-[var(--border-subtle)] dark:border-[var(--border-subtle)]',
    accentRing: 'ring-slate-500/20',
  },
};

export const MarketStatePanel: React.FC<MarketStatePanelProps> = ({ data }) => {
  const rawState = data.marketState || (data as MarketStateData & { market_regime?: string }).market_regime || 'NO_TRADE';
  const state = (typeof rawState === 'string' ? rawState : 'NO_TRADE').toUpperCase() as keyof typeof stateConfig;
  const config = stateConfig[state] || stateConfig.NO_TRADE || stateConfig.DATA_UNAVAILABLE;
  const StateIcon = config.icon;
  const isStrictNoTrade = data.isNoTrade === true || state === 'NO_TRADE';

  const keyLevels = data.keyLevels || {
    immediateSupport: 0,
    immediateResistance: 0,
    importantSupport: 0,
    importantResistance: 0,
    bullishActivationTrigger: 'Awaiting 5M breakout confirmation outside chop zone',
    bearishActivationTrigger: 'Awaiting 5M breakdown confirmation outside chop zone',
    confirmationRequired: '5M Close outside range with displacement',
  };

  const headline = data.headline || `${data.symbol || 'Index'} Market Regime: ${isStrictNoTrade ? 'NO TRADE' : state}`;
  const explanation = data.explanation || data.reasonForNoTrade || data.primaryReason || (isStrictNoTrade ? 'No trade reason is unavailable. Check market data and risk status.' : 'Market structure active.');

  return (
    <div
      className={`relative overflow-hidden rounded-2xl border bg-gradient-to-br ${config.gradient} ${config.darkGradient} ${config.border} bg-[var(--bg-surface)] dark:bg-[var(--bg-surface)] transition-all duration-300 tabular-nums`}
    >
      {/* Decorative glow */}
      <div className="absolute top-0 right-0 w-72 h-72 rounded-full opacity-[0.04] blur-3xl pointer-events-none"
        style={{ background: state === 'BULLISH' ? '#10b981' : state === 'BEARISH' ? '#f43f5e' : isStrictNoTrade ? '#f97316' : '#3b82f6' }}
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
                <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-md ${config.pillBg} ${config.pillText} border ${config.pillBorder}`}>
                  {isStrictNoTrade ? 'NO TRADE' : (typeof state === 'string' ? state.replace(/_/g, ' ') : 'NO TRADE')}
                </span>
              </div>

              {/* Headline */}
              <h3 className="text-lg sm:text-xl font-semibold text-[var(--text-primary)] leading-tight tracking-tight">
                {headline}
              </h3>
            </div>
          </div>

          {/* Status Badge + Data Status */}
          <div className="flex items-center gap-3 shrink-0">
            {/* Prominent Status Badge */}
            <div className={`px-4 py-2 rounded-xl ${isStrictNoTrade ? 'bg-orange-500 text-[var(--text-primary)]' : config.badgeBg + ' ' + config.badgeText} font-semibold text-sm tracking-wide flex items-center gap-2 shadow-lg`}>
              {isStrictNoTrade && (
                <span className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--bg-surface-elevated)]" />
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-[var(--bg-surface-elevated)]" />
                </span>
              )}
              {isStrictNoTrade ? 'NO TRADE' : (data.statusBadge || 'SETUPS ARMED')}
            </div>

            {/* Live indicator */}
            <div className="hidden sm:flex flex-col items-end gap-0.5">
              <span className="text-[10px] font-medium text-[var(--text-muted)]">Feed</span>
              <span className={`text-xs font-semibold flex items-center gap-1 ${data.dataStatus === 'LIVE' ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`}>
                <Radio className="w-3 h-3" />
                {data.dataStatus || 'UNKNOWN'}
              </span>
            </div>
          </div>
        </div>

        {/* Analysis Explanation */}
        <div className="mb-4 p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            <strong className="text-[var(--text-primary)] font-semibold">Analysis: </strong>
            {explanation}
          </p>
        </div>

        {/* NO TRADE Reason Alert (Render ONLY when strictly in No-Trade mode) */}
        {isStrictNoTrade && data.reasonForNoTrade && !data.reasonForNoTrade.toLowerCase().includes('none') && !data.reasonForNoTrade.toLowerCase().includes('qualified') && (
          <div className="mb-4 p-4 rounded-xl border bg-orange-50/80 dark:bg-orange-500/8 border-orange-200 dark:border-orange-500/20">
            <div className="flex items-start gap-2.5">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-orange-500" />
              <div className="space-y-1">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-orange-600 dark:text-orange-400">
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
            description={keyLevels.bullishActivationTrigger}
            color="emerald"
          />
          <TriggerCard
            icon={<ArrowDownRight className="w-4 h-4" />}
            label="Bearish Activation"
            description={keyLevels.bearishActivationTrigger}
            color="rose"
          />
          <TriggerCard
            icon={<CheckCircle2 className="w-4 h-4" />}
            label="Required Confirmation"
            description={keyLevels.confirmationRequired}
            color="indigo"
          />
        </div>

        {/* Footer: Timestamp + Key Levels */}
        <div className="pt-3 border-t border-[var(--border-subtle)] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-xs text-[var(--text-muted)]">
          <div className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            <span>{data.analysisTimestamp || 'Live Market'}</span>
          </div>
          <div className="flex items-center gap-3 font-medium">
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
              Support: ₹{keyLevels.importantSupport || keyLevels.immediateSupport || '--'}
            </span>
            <span className="text-[var(--border-strong)]">•</span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-500 inline-block" />
              Resistance: ₹{keyLevels.importantResistance || keyLevels.immediateResistance || '--'}
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
      iconColor: 'text-[var(--accent-blue)] dark:text-[var(--accent-blue)]',
      bg: 'bg-[var(--accent-blue-bg)]/60 dark:bg-[var(--accent-blue)]/6',
      border: 'border-[var(--accent-blue)]/60 dark:border-[var(--accent-blue)]/15',
      label: 'text-[var(--accent-blue)] dark:text-[var(--accent-blue)]',
    },
  };

  const c = colorMap[color];

  return (
    <div className={`p-3.5 rounded-xl ${c.bg} border ${c.border} transition-all hover:shadow-sm group`}>
      <div className={`flex items-center gap-1.5 mb-1.5 ${c.iconColor}`}>
        {icon}
        <span className={`text-[11px] font-semibold uppercase tracking-wide ${c.label}`}>{label}</span>
      </div>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed font-medium">
        {description}
      </p>
    </div>
  );
}
