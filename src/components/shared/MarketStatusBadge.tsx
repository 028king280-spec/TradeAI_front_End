import React from 'react';

interface MarketStatusBadgeProps {
  exchange: 'NSE' | 'BSE';
  status: 'OPEN' | 'CLOSED';
}

export const MarketStatusBadge: React.FC<MarketStatusBadgeProps> = ({ exchange, status }) => {
  const isOpen = status === 'OPEN';

  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-100 dark:bg-[#161D2B] border border-slate-200 dark:border-[#232F46] text-xs font-mono">
      <span className="font-semibold text-slate-700 dark:text-slate-300">{exchange}:</span>
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
