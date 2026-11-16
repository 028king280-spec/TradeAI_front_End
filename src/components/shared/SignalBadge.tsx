import React from 'react';
import { ArrowUpRight, ArrowDownRight, Minus } from 'lucide-react';

interface SignalBadgeProps {
  type: 'Bullish' | 'Bearish' | 'Neutral' | 'CALL' | 'PUT' | 'NEUTRAL';
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export const SignalBadge: React.FC<SignalBadgeProps> = ({ type, size = 'md', className = '' }) => {
  const isBullish = type === 'Bullish' || type === 'CALL';
  const isBearish = type === 'Bearish' || type === 'PUT';

  const sizeClasses = {
    sm: 'text-xs px-2 py-0.5 font-medium',
    md: 'text-xs px-2.5 py-1 font-semibold',
    lg: 'text-sm px-3.5 py-1.5 font-semibold',
  };

  const colorClasses = isBullish
    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
    : isBearish
    ? 'bg-rose-500/10 text-rose-400 border border-rose-500/30'
    : 'bg-amber-500/10 text-amber-400 border border-amber-500/30';

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md uppercase tracking-wider tabular-nums ${sizeClasses[size]} ${colorClasses} ${className}`}
    >
      {isBullish && <ArrowUpRight className="w-3.5 h-3.5 stroke-[2.5]" />}
      {isBearish && <ArrowDownRight className="w-3.5 h-3.5 stroke-[2.5]" />}
      {!isBullish && !isBearish && <Minus className="w-3.5 h-3.5" />}
      <span>{type}</span>
    </span>
  );
};
