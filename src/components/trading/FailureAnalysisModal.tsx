'use client';

import React, { useEffect, useState } from 'react';
import { X, Activity, RefreshCw, ShieldAlert } from 'lucide-react';

interface FailureAnalysisModalProps {
  signalId: string | null;
  onClose: () => void;
}

export const FailureAnalysisModal: React.FC<FailureAnalysisModalProps> = ({
  signalId,
  onClose,
}) => {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    if (!signalId) return;

    let isMounted = true;
    setLoading(true);

    fetch(`/api/signals/${signalId}/failure-analysis`)
      .then((res) => res.json())
      .then((json) => {
        if (isMounted && json.success) {
          setData(json.data);
        }
      })
      .catch((err) => console.error('Failed to load failure analysis:', err))
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
      <div className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border border-rose-200 dark:border-rose-500/30 bg-[var(--bg-surface)] text-[var(--text-primary)] p-6 space-y-5 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-[var(--border-subtle)]">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/20 flex items-center justify-center text-rose-500">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-[var(--text-primary)] tracking-tight">
                Factual Signal Failure Diagnostic
              </h3>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                Audited against stored market evidence • Zero fabricated news
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
            <RefreshCw className="w-6 h-6 text-rose-500 animate-spin mx-auto" />
            <p className="text-xs text-[var(--text-muted)]">Querying tick audit log and market evidence...</p>
          </div>
        ) : !data ? (
          <div className="py-8 text-center text-xs text-[var(--text-muted)]">
            No diagnostic details recorded for this signal.
          </div>
        ) : (
          <div className="space-y-4">
            {/* Primary Outcome Banner */}
            <div className="p-4 rounded-xl bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/30 space-y-1.5">
              <span className="text-[10px] text-rose-700 dark:text-rose-300 font-semibold uppercase tracking-wider">
                Primary Observed Outcome
              </span>
              <div className="text-lg font-semibold text-rose-600 dark:text-rose-400">
                {data.primaryOutcome.replace(/_/g, ' ')}
              </div>
              <div className="text-xs text-[var(--text-secondary)] leading-relaxed">
                {data.primaryContributingFactor}
              </div>
            </div>

            {/* Contributing Factors */}
            {data.contributingFactors && data.contributingFactors.length > 0 && (
              <div className="space-y-2">
                <span className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide">
                  Verified Contributing Factors
                </span>
                <div className="space-y-1.5">
                  {data.contributingFactors.map((factor: string, idx: number) => (
                    <div
                      key={idx}
                      className="p-3 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-xs text-[var(--text-secondary)] flex items-start gap-2.5"
                    >
                      <span className="text-rose-500 font-semibold">•</span>
                      <span>{factor}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Market Reversal Evidence */}
            {data.reversalEvidence && (
              <div className="p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-3">
                <span className="text-xs font-semibold text-[var(--text-primary)] uppercase tracking-wide flex items-center gap-1.5">
                  <Activity className="w-4 h-4 text-[var(--accent-blue)]" />
                  Market Reversal Audit
                </span>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] block font-medium">Reversal Detected</span>
                    <span className={`font-bold ${data.reversalEvidence.reversalDetected ? 'text-amber-600 dark:text-amber-400' : 'text-[var(--text-secondary)]'}`}>
                      {data.reversalEvidence.reversalDetected ? 'YES' : 'NO'}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] block font-medium">Reversal Classification</span>
                    <span className="font-semibold text-[var(--text-primary)]">{data.reversalEvidence.reversalType}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] block font-medium">Trigger Level</span>
                    <span className="font-semibold tabular-nums text-[var(--text-primary)]">{data.reversalEvidence.reversalTrigger}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] block font-medium">Confirmed Before SL Hit</span>
                    <span className="font-semibold text-[var(--text-primary)]">
                      {data.reversalEvidence.confirmedBeforeSL ? 'Confirmed Before SL' : 'Post-Exit Observation'}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Diagnostic Metadata Footer */}
            <div className="pt-3 border-t border-[var(--border-subtle)] flex items-center justify-between text-xs text-[var(--text-muted)] tabular-nums">
              <span>Strategy: {data.strategyVersion}</span>
              <span>Confidence: {data.confidence}</span>
              <span>Audit Time: {data.timestamp}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
