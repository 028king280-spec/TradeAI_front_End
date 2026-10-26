'use client';

import React, { useEffect, useState } from 'react';
import {
  X,
  Clock,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  TrendingUp,
  RefreshCw,
  Layers,
} from 'lucide-react';

interface SignalTimelineModalProps {
  signalId: string | null;
  onClose: () => void;
}

export const SignalTimelineModal: React.FC<SignalTimelineModalProps> = ({
  signalId,
  onClose,
}) => {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    if (!signalId) return;

    let isMounted = true;
    setLoading(true);

    fetch(`http://localhost:8000/api/signals/${signalId}/timeline`)
      .then((res) => res.json())
      .then((json) => {
        if (isMounted && json.success) {
          setData(json.data);
        }
      })
      .catch((err) => console.error('Failed to load timeline:', err))
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [signalId]);

  if (!signalId) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in">
      <div className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--text-primary)] p-6 space-y-5 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-[var(--border-subtle)]">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 dark:bg-indigo-500/10 border border-indigo-200 dark:border-indigo-500/20 flex items-center justify-center text-indigo-500">
              <Clock className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-[var(--text-primary)] tracking-tight">
                Signal Audit & Event Timeline
              </h3>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                Idempotent market tick progression in Indian Standard Time (IST)
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-xl bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors border border-[var(--border-subtle)]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {loading ? (
          <div className="py-12 text-center space-y-3">
            <RefreshCw className="w-6 h-6 text-indigo-500 animate-spin mx-auto" />
            <p className="text-xs text-[var(--text-muted)]">Loading audit trail...</p>
          </div>
        ) : !data ? (
          <div className="py-8 text-center text-xs text-[var(--text-muted)]">
            Timeline data unavailable for this signal.
          </div>
        ) : (
          <div className="space-y-4">
            <div className="p-3.5 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] flex items-center justify-between text-xs">
              <div>
                <span className="text-[10px] text-[var(--text-muted)] block font-medium">Contract Symbol</span>
                <span className="font-bold text-[var(--text-primary)] text-sm font-mono">{data.contractSymbol}</span>
              </div>
              <div className="text-right">
                <span className="text-[10px] text-[var(--text-muted)] block font-medium">Current State</span>
                <span className="font-bold text-indigo-600 dark:text-indigo-400 uppercase">{data.currentStatus}</span>
              </div>
            </div>

            {/* Timeline Steps */}
            <div className="relative pl-6 space-y-4 before:absolute before:left-2.5 before:top-3 before:bottom-3 before:w-0.5 before:bg-[var(--border-subtle)]">
              {data.timeline?.map((item: any, idx: number) => {
                const isKey = item.isTargetOrSl;
                const isT = item.state.includes('T') && item.state.includes('HIT');
                const isSL = item.state === 'STOP_LOSS_HIT';

                return (
                  <div key={idx} className="relative space-y-1">
                    {/* Bullet */}
                    <div
                      className={`absolute -left-6 top-1 w-3 h-3 rounded-full border-2 ${
                        isT
                          ? 'bg-emerald-500 border-white dark:border-slate-900 shadow-sm'
                          : isSL
                          ? 'bg-rose-500 border-white dark:border-slate-900 shadow-sm'
                          : isKey
                          ? 'bg-indigo-500 border-white dark:border-slate-900 shadow-sm'
                          : 'bg-slate-400 border-white dark:border-slate-900'
                      }`}
                    />

                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-[var(--text-primary)]">{item.title}</span>
                      <span className="text-[10px] text-[var(--text-muted)] font-mono">{item.timestamp}</span>
                    </div>

                    <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{item.description}</p>

                    {item.elapsedMinutes > 0 && (
                      <span className="text-[10px] text-[var(--text-muted)] block">
                        Elapsed: {item.elapsedMinutes} mins from entry
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
