import React from 'react';

interface ConfidenceScoreProps {
  score: number;
  label?: string;
  size?: 'sm' | 'md' | 'lg';
  showBar?: boolean;
}

export const ConfidenceScore: React.FC<ConfidenceScoreProps> = ({
  score,
  label = 'Confidence',
  size = 'md',
  showBar = false,
}) => {
  const getColor = (val: number) => {
    if (val >= 80) return 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30';
    if (val >= 70) return 'text-[var(--accent-blue)] bg-[var(--accent-blue)]/10 border-[var(--accent-blue)]/30';
    if (val >= 55) return 'text-amber-400 bg-amber-500/10 border-amber-500/30';
    return 'text-rose-400 bg-rose-500/10 border-rose-500/30';
  };

  const getBarColor = (val: number) => {
    if (val >= 80) return 'bg-emerald-400';
    if (val >= 70) return 'bg-[var(--accent-blue)]';
    if (val >= 55) return 'bg-amber-400';
    return 'bg-rose-400';
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        {label && <span className="text-xs text-[var(--text-secondary)] font-medium">{label}</span>}
        <div
          className={`inline-flex items-center px-2 py-0.5 rounded border tabular-nums font-semibold text-xs ${getColor(
            score
          )}`}
        >
          {score}
          <span className="text-[10px] text-[var(--text-secondary)] font-normal ml-0.5">/100</span>
        </div>
      </div>
      {showBar && (
        <div className="w-full bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface)] h-1.5 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${getBarColor(score)}`}
            style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
          />
        </div>
      )}
    </div>
  );
};
