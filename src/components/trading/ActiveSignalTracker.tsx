'use client';

import React from 'react';
import {
  Activity,
  CheckCircle2,
  AlertOctagon,
  Clock,
  ArrowRight,
  TrendingUp,
  TrendingDown,
  Info,
  Layers,
  ChevronRight,
  FileText,
  Shield,
  Zap,
} from 'lucide-react';

export interface TrackedSignalItem {
  id: string;
  symbol: string;
  contractSymbol: string;
  optionType: 'CE' | 'PE';
  strike: number;
  expiry: string;
  status: string;
  finalOutcome?: string;
  signalPremium: number;
  entryZoneMin: number;
  entryZoneMax: number;
  entryObservedPrice?: number;
  stopLossPremium: number;
  target1Premium: number;
  target2Premium: number;
  target3Premium: number;
  netPnlInr: number;
  grossPnlPoints: number;
  lotSize: number;
  allocatedLots: number;
  createdAt: string;
  entryTriggeredAt?: string;
  closedAt?: string;
}

interface ActiveSignalTrackerProps {
  signals: TrackedSignalItem[];
  onSelectSignalTimeline?: (signalId: string) => void;
  onSelectFailureAnalysis?: (signalId: string) => void;
}

export const ActiveSignalTracker: React.FC<ActiveSignalTrackerProps> = ({
  signals,
  onSelectSignalTimeline,
  onSelectFailureAnalysis,
}) => {
  if (!signals || signals.length === 0) {
    return (
      <div className="p-6 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-center space-y-2.5 shadow-sm">
        <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-500/10 border border-blue-100 dark:border-blue-500/20 flex items-center justify-center mx-auto text-blue-500">
          <Activity className="w-5 h-5" />
        </div>
        <h4 className="text-sm font-semibold text-[var(--text-primary)]">
          No Actively Tracked Paper Setups Today
        </h4>
        <p className="text-xs text-[var(--text-muted)] max-w-md mx-auto">
          When qualified option setups satisfy market state filters and trigger entry conditions, they are automatically logged and tracked here with live tick verification.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-indigo-50 dark:bg-indigo-500/10 border border-indigo-200 dark:border-indigo-500/20 flex items-center justify-center text-indigo-500">
            <Activity className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
              Actively Tracked Paper Setups ({signals.length})
            </h3>
            <span className="text-[10px] text-[var(--text-muted)]">
              Strict zero-lookahead • Audited continuous tick feed
            </span>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {signals.map((sig) => {
          const isCall = sig.optionType === 'CE';
          const isProfit = sig.netPnlInr > 0;
          const isLoss = sig.netPnlInr < 0;
          const isFailed =
            sig.status === 'STOP_LOSS_HIT' ||
            sig.finalOutcome?.includes('LOSS') ||
            sig.status === 'MISSED';

          return (
            <div
              key={sig.id}
              className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:border-[var(--border-strong)] transition-all space-y-3.5 shadow-sm"
            >
              {/* Top Row: Symbol, Status Badge, PnL */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span
                    className={`text-xs px-2.5 py-1 rounded-md font-bold tracking-wider ${
                      isCall
                        ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-500/20'
                        : 'bg-rose-50 dark:bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-500/20'
                    }`}
                  >
                    {sig.optionType}
                  </span>
                  <div>
                    <span className="text-sm font-bold text-[var(--text-primary)]">
                      {sig.contractSymbol}
                    </span>
                    <span className="text-[11px] text-[var(--text-muted)] ml-2">
                      {sig.symbol} • Strike ₹{sig.strike} • {sig.expiry}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  {/* Status Badge */}
                  <span
                    className={`text-xs px-2.5 py-1 rounded-md font-semibold border ${
                      sig.status === 'WAITING_FOR_ENTRY'
                        ? 'bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-500/20'
                        : sig.status === 'ACTIVE'
                        ? 'bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-500/20 animate-pulse'
                        : sig.status.includes('TARGET')
                        ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20'
                        : sig.status === 'STOP_LOSS_HIT'
                        ? 'bg-rose-50 dark:bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-200 dark:border-rose-500/20'
                        : 'bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border-[var(--border-subtle)]'
                    }`}
                  >
                    {sig.status ? String(sig.status).replace(/_/g, ' ') : ''}
                  </span>

                  {/* Net P&L */}
                  <div className="text-right">
                    <span
                      className={`text-sm font-bold font-mono ${
                        isProfit
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : isLoss
                          ? 'text-rose-600 dark:text-rose-400'
                          : 'text-[var(--text-secondary)]'
                      }`}
                    >
                      {sig.netPnlInr >= 0
                        ? `+₹${sig.netPnlInr.toFixed(2)}`
                        : `-₹${Math.abs(sig.netPnlInr).toFixed(2)}`}
                    </span>
                    <span className="text-[10px] text-[var(--text-muted)] block">After costs</span>
                  </div>
                </div>
              </div>

              {/* Ladder Strip: Entry, SL, T1, T2, T3 */}
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5 text-xs pt-1">
                <div className="p-2.5 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
                  <span className="text-[10px] text-[var(--text-muted)] block font-medium">Approved Entry</span>
                  <span className="text-[var(--text-primary)] font-bold font-mono">
                    ₹{sig.entryZoneMin} - ₹{sig.entryZoneMax}
                  </span>
                </div>

                <div className="p-2.5 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
                  <span className="text-[10px] text-[var(--text-muted)] block font-medium">Actual Entry Fill</span>
                  <span className="text-blue-600 dark:text-blue-400 font-bold font-mono">
                    {sig.entryObservedPrice ? `₹${sig.entryObservedPrice.toFixed(2)}` : 'Pending'}
                  </span>
                </div>

                <div className="p-2.5 rounded-xl bg-rose-50/50 dark:bg-rose-500/5 border border-rose-200 dark:border-rose-500/20">
                  <span className="text-[10px] text-rose-600 dark:text-rose-400 block font-medium">Stop-Loss</span>
                  <span className="text-rose-600 dark:text-rose-400 font-bold font-mono">
                    ₹{sig.stopLossPremium.toFixed(1)}
                  </span>
                </div>

                <div className="p-2.5 rounded-xl bg-emerald-50/50 dark:bg-emerald-500/5 border border-emerald-200 dark:border-emerald-500/20">
                  <span className="text-[10px] text-emerald-600 dark:text-emerald-400 block font-medium">Target 1 (50%)</span>
                  <span className="text-emerald-600 dark:text-emerald-400 font-bold font-mono">
                    ₹{sig.target1Premium.toFixed(1)}
                  </span>
                </div>

                <div className="p-2.5 rounded-xl bg-emerald-50/50 dark:bg-emerald-500/5 border border-emerald-200 dark:border-emerald-500/20">
                  <span className="text-[10px] text-emerald-600 dark:text-emerald-400 block font-medium">Target 2 / 3</span>
                  <span className="text-emerald-600 dark:text-emerald-400 font-bold font-mono">
                    ₹{sig.target2Premium.toFixed(1)} / ₹{sig.target3Premium.toFixed(1)}
                  </span>
                </div>
              </div>

              {/* Action Buttons Row */}
              <div className="flex items-center justify-between pt-2 border-t border-[var(--border-subtle)] text-xs text-[var(--text-muted)]">
                <div className="flex items-center gap-1.5 text-[11px]">
                  <Clock className="w-3.5 h-3.5 text-[var(--text-muted)]" />
                  <span>Created: {sig.createdAt || 'N/A'}</span>
                </div>

                <div className="flex items-center gap-2">
                  {isFailed && onSelectFailureAnalysis && (
                    <button
                      onClick={() => onSelectFailureAnalysis(sig.id)}
                      className="px-3 py-1.5 rounded-lg bg-rose-50 dark:bg-rose-500/10 hover:bg-rose-100 dark:hover:bg-rose-500/20 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-500/20 text-xs font-semibold flex items-center gap-1.5 transition-colors"
                    >
                      <FileText className="w-3.5 h-3.5" />
                      <span>Failure Diagnostic</span>
                    </button>
                  )}

                  {onSelectSignalTimeline && (
                    <button
                      onClick={() => onSelectSignalTimeline(sig.id)}
                      className="px-3 py-1.5 rounded-lg bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-hover)] text-[var(--text-primary)] border border-[var(--border-subtle)] text-xs font-semibold flex items-center gap-1.5 transition-colors"
                    >
                      <span>Audit Events</span>
                      <ChevronRight className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
