'use client';

import React, { useState } from 'react';
import {
  ShieldAlert,
  Zap,
  Target,
  ArrowRight,
  TrendingUp,
  TrendingDown,
  CheckCircle2,
  AlertCircle,
  Bell,
  BellRing,
  Eye,
  Crosshair,
  Shield,
  CircleDot,
} from 'lucide-react';

export interface SignalActivationData {
  index: string;
  signalState: 'CALL_SETUP_READY' | 'PUT_SETUP_READY' | 'CALL_ACTIVE' | 'PUT_ACTIVE' | 'NO_TRADE' | 'WAITING_FOR_CONFIRMATION' | 'ENTRY_TRIGGERED' | 'MISSED';
  bias: 'CE' | 'PE' | 'NONE';
  contractSymbol: string;
  strike: number;
  expiry: string;
  lastObservedLtp: number;
  entryRangeMin: number;
  entryRangeMax: number;
  stopLoss: number;
  target1: number;
  target2: number;
  target3: number;
  riskRewardRatio: string;
  entryCondition: string;
  invalidationCondition: string;
  supportingReasons: string[];
  dataTimestamp: string;
  dataStatus: string;
}

interface SignalActivationPanelProps {
  data: SignalActivationData | null;
  onOpenTimeline?: () => void;
}

export const SignalActivationPanel: React.FC<SignalActivationPanelProps> = ({
  data,
  onOpenTimeline,
}) => {
  const [notificationsEnabled, setNotificationsEnabled] = useState<boolean>(false);

  const toggleNotifications = () => {
    if (!notificationsEnabled && typeof window !== 'undefined' && 'Notification' in window) {
      Notification.requestPermission().then((permission) => {
        if (permission === 'granted') {
          setNotificationsEnabled(true);
        }
      });
    } else {
      setNotificationsEnabled(!notificationsEnabled);
    }
  };

  const isCall = data?.bias === 'CE' && (data.signalState === 'CALL_SETUP_READY' || data.signalState === 'CALL_ACTIVE');
  const isPut = data?.bias === 'PE' && (data.signalState === 'PUT_SETUP_READY' || data.signalState === 'PUT_ACTIVE');
  const isEntryTriggered = data?.signalState === 'ENTRY_TRIGGERED';
  const hasActiveSetup = isCall || isPut || isEntryTriggered;

  const badgeConfig = isCall
    ? { text: 'CALL SETUP ACTIVE', bg: 'bg-emerald-500', color: 'text-white' }
    : isPut
    ? { text: 'PUT SETUP ACTIVE', bg: 'bg-rose-500', color: 'text-white' }
    : isEntryTriggered
    ? { text: 'ENTRY TRIGGERED', bg: 'bg-blue-500', color: 'text-white' }
    : { text: 'NO TRADE — WAIT FOR CONFIRMATION', bg: 'bg-amber-500', color: 'text-white' };

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-white dark:bg-[var(--bg-surface)] overflow-hidden transition-all duration-300">
      {/* Header */}
      <div className="px-5 sm:px-6 pt-5 sm:pt-6 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${
            hasActiveSetup
              ? 'bg-blue-50 dark:bg-blue-500/15 ring-1 ring-blue-500/20'
              : 'bg-amber-50 dark:bg-amber-500/15 ring-1 ring-amber-500/20'
          }`}>
            <Zap className={`w-5 h-5 ${hasActiveSetup ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400'}`} />
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider">
                Signal Activation Engine
              </span>
              <span className="text-[10px] px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 font-medium border border-slate-200 dark:border-slate-700">
                Paper Only
              </span>
            </div>

            {/* Status Badge */}
            <div className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg ${badgeConfig.bg} ${badgeConfig.color} font-bold text-sm tracking-wide shadow-md`}>
              {!hasActiveSetup && (
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white/60" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-white/90" />
                </span>
              )}
              {badgeConfig.text}
            </div>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={toggleNotifications}
            className={`px-3 py-2 rounded-lg border text-xs font-semibold flex items-center gap-1.5 transition-all ${
              notificationsEnabled
                ? 'bg-indigo-500 border-indigo-500 text-white shadow-md'
                : 'bg-[var(--bg-surface-elevated)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]'
            }`}
          >
            {notificationsEnabled ? <BellRing className="w-3.5 h-3.5" /> : <Bell className="w-3.5 h-3.5" />}
            {notificationsEnabled ? 'Alerts ON' : 'Enable Alerts'}
          </button>

          {onOpenTimeline && (
            <button
              onClick={onOpenTimeline}
              className="px-3 py-2 rounded-lg bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-hover)] border border-[var(--border-subtle)] text-xs font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center gap-1.5 transition-all"
            >
              <Eye className="w-3.5 h-3.5" />
              Timeline
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="p-5 sm:p-6">
        {!hasActiveSetup ? (
          /* No Active Setup State */
          <div className="py-10 text-center space-y-3">
            <div className="w-14 h-14 rounded-2xl bg-amber-50 dark:bg-amber-500/10 flex items-center justify-center mx-auto ring-1 ring-amber-500/20">
              <ShieldAlert className="w-7 h-7 text-amber-500" />
            </div>
            <div className="space-y-1.5">
              <h4 className="text-base font-bold text-[var(--text-primary)]">
                No Directional Setup Qualified
              </h4>
              <p className="text-sm text-[var(--text-muted)] max-w-md mx-auto leading-relaxed">
                Option buying in chop or non-confirmed regimes yields negative expected value.
                Wait for the market state engine to verify momentum and volume expansion.
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            {/* Active Contract Header */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
              <div className="space-y-1">
                <span className="text-[10px] text-[var(--text-muted)] uppercase font-semibold tracking-wider">
                  Monitored Contract
                </span>
                <div className="flex items-center gap-2.5 flex-wrap">
                  <span className="text-lg font-extrabold text-[var(--text-primary)] tracking-tight font-mono">
                    {data!.contractSymbol}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded-md bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-500/20 font-semibold">
                    {data!.expiry}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded-md bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[var(--text-secondary)] font-semibold">
                    Strike: {data!.strike}
                  </span>
                </div>
              </div>

              <div className="text-left sm:text-right">
                <span className="text-[10px] text-[var(--text-muted)] uppercase font-semibold tracking-wider block">
                  Live Premium
                </span>
                <span className={`text-2xl font-extrabold font-mono ${isCall ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
                  ₹{data!.lastObservedLtp.toFixed(2)}
                </span>
              </div>
            </div>

            {/* Price Levels Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <PriceLevelCard
                label="Entry Zone"
                value={`₹${data!.entryRangeMin.toFixed(0)} — ₹${data!.entryRangeMax.toFixed(0)}`}
                sublabel="Ask-calibrated"
                icon={<Crosshair className="w-3.5 h-3.5" />}
                color="blue"
              />
              <PriceLevelCard
                label="Stop Loss"
                value={`₹${data!.stopLoss}`}
                sublabel="Capital protection"
                icon={<Shield className="w-3.5 h-3.5" />}
                color="rose"
              />
              <PriceLevelCard
                label="Target 1 (50%)"
                value={`₹${data!.target1}`}
                sublabel="SL trails to cost"
                icon={<Target className="w-3.5 h-3.5" />}
                color="emerald"
              />
              <PriceLevelCard
                label="T2 & T3"
                value={`₹${data!.target2} / ₹${data!.target3}`}
                sublabel="Runner scale-out"
                icon={<CircleDot className="w-3.5 h-3.5" />}
                color="emerald"
              />
            </div>

            {/* Entry & Invalidation */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="p-3.5 rounded-xl bg-emerald-50/50 dark:bg-emerald-500/5 border border-emerald-200/50 dark:border-emerald-500/15 space-y-1.5">
                <span className="text-xs text-emerald-700 dark:text-emerald-400 font-bold flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Entry Trigger Condition
                </span>
                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{data!.entryCondition}</p>
              </div>

              <div className="p-3.5 rounded-xl bg-rose-50/50 dark:bg-rose-500/5 border border-rose-200/50 dark:border-rose-500/15 space-y-1.5">
                <span className="text-xs text-rose-700 dark:text-rose-400 font-bold flex items-center gap-1.5">
                  <AlertCircle className="w-3.5 h-3.5" />
                  Thesis Invalidation
                </span>
                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{data!.invalidationCondition}</p>
              </div>
            </div>

            {/* Supporting Evidence */}
            {data!.supportingReasons && data!.supportingReasons.length > 0 && (
              <div className="space-y-2">
                <span className="text-[10px] text-[var(--text-muted)] uppercase font-semibold tracking-wider">
                  Quantitative Evidence
                </span>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  {data!.supportingReasons.map((reason, idx) => (
                    <div
                      key={idx}
                      className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-xs text-[var(--text-secondary)] leading-relaxed flex items-start gap-2"
                    >
                      <span className="w-1 h-1 rounded-full bg-blue-500 mt-1.5 shrink-0" />
                      {reason}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-5 sm:px-6 py-3 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] flex items-center justify-between text-[10px] text-[var(--text-muted)]">
        <span>Paper signals only — no broker orders deployed</span>
        <span className="font-mono">{data?.dataTimestamp || 'Current'}</span>
      </div>
    </div>
  );
};

/* Sub-component: Price Level Card */
function PriceLevelCard({
  label,
  value,
  sublabel,
  icon,
  color,
}: {
  label: string;
  value: string;
  sublabel: string;
  icon: React.ReactNode;
  color: 'blue' | 'rose' | 'emerald';
}) {
  const colorMap = {
    blue: {
      labelColor: 'text-blue-700 dark:text-blue-400',
      border: 'border-blue-200/40 dark:border-blue-500/15',
      bg: 'bg-blue-50/40 dark:bg-blue-500/5',
      valueColor: 'text-blue-600 dark:text-blue-400',
    },
    rose: {
      labelColor: 'text-rose-700 dark:text-rose-400',
      border: 'border-rose-200/40 dark:border-rose-500/15',
      bg: 'bg-rose-50/40 dark:bg-rose-500/5',
      valueColor: 'text-rose-600 dark:text-rose-400',
    },
    emerald: {
      labelColor: 'text-emerald-700 dark:text-emerald-400',
      border: 'border-emerald-200/40 dark:border-emerald-500/15',
      bg: 'bg-emerald-50/40 dark:bg-emerald-500/5',
      valueColor: 'text-emerald-600 dark:text-emerald-400',
    },
  };

  const c = colorMap[color];

  return (
    <div className={`p-3 rounded-xl ${c.bg} border ${c.border} space-y-1 transition-all hover:shadow-sm`}>
      <span className={`text-[10px] ${c.labelColor} font-bold uppercase flex items-center gap-1`}>
        {icon}
        {label}
      </span>
      <span className={`text-sm font-extrabold ${c.valueColor} block font-mono`}>{value}</span>
      <span className="text-[10px] text-[var(--text-muted)] block">{sublabel}</span>
    </div>
  );
}
