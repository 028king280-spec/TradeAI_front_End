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
    <div className="flex flex-col items-center justify-center p-8 text-center rounded-xl border border-dashed border-[var(--border-subtle)] dark:border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface)] my-2">
      <div className="w-10 h-10 rounded-full bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] flex items-center justify-center text-[var(--text-muted)] dark:text-[var(--text-secondary)] mb-3">
        {icon || <ShieldAlert className="w-5 h-5 text-amber-500 dark:text-amber-400" />}
      </div>
      <h4 className="text-sm font-semibold tracking-wider text-[var(--text-primary)] dark:text-[var(--text-primary)] uppercase tabular-nums">
        {title}
      </h4>
      <p className="text-xs text-[var(--text-muted)] dark:text-[var(--text-secondary)] max-w-xs mt-1 leading-relaxed">
        {description}
      </p>
    </div>
  );
};
