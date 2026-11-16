import React from 'react';

interface MarketStatusBadgeProps {
  exchange: 'NSE' | 'BSE';
  status: 'OPEN' | 'CLOSED';
}

export const MarketStatusBadge: React.FC<MarketStatusBadgeProps> = ({ exchange, status }) => {
  const isOpen = status === 'OPEN';

  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] text-xs tabular-nums">
      <span className="font-semibold text-[var(--text-secondary)] dark:text-[var(--text-secondary)]">{exchange}:</span>
      <span className="flex items-center gap-1">
        <span
          className={`w-2 h-2 rounded-full ${
            isOpen ? 'bg-emerald-500 dark:bg-emerald-400 animate-pulse shadow-[0_0_8px_rgba(52,211,153,0.8)]' : 'bg-rose-500 dark:bg-rose-400'
          }`}
        />
        <span className={isOpen ? 'text-emerald-700 dark:text-emerald-400 font-semibold' : 'text-rose-700 dark:text-rose-400'}>
          {status}
        </span>
      </span>
    </div>
  );
};
