import React from 'react';
import { ShieldAlert } from 'lucide-react';

interface EmptyStateProps {
  title?: string;
  description?: string;
  icon?: React.ReactNode;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title = 'NO QUALIFIED SETUP',
  description = 'Current technical, sector, and risk-adjusted scores do not meet high-conviction entry criteria.',
  icon,
}) => {
  return (
    <div className="flex flex-col items-center justify-center p-8 text-center rounded-xl border border-dashed border-slate-300 dark:border-[#232F46] bg-slate-50 dark:bg-[#111622]/50 my-2">
      <div className="w-10 h-10 rounded-full bg-slate-100 dark:bg-slate-800/80 flex items-center justify-center text-slate-500 dark:text-slate-400 mb-3">
        {icon || <ShieldAlert className="w-5 h-5 text-amber-500 dark:text-amber-400" />}
      </div>
      <h4 className="text-sm font-semibold tracking-wider text-slate-800 dark:text-slate-200 uppercase font-mono">
        {title}
      </h4>
      <p className="text-xs text-slate-500 dark:text-slate-400 max-w-xs mt-1 leading-relaxed">
        {description}
      </p>
    </div>
  );
};
