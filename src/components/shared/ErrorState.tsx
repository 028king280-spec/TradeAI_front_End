import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Unable to refresh market analysis',
  message = 'An unexpected connection interruption occurred while querying the simulated feed. Please retry.',
  onRetry,
}) => {
  return (
    <div className="card-terminal p-8 text-center max-w-md mx-auto my-8 border-rose-500/30 bg-rose-950/10 space-y-4">
      <div className="w-12 h-12 rounded-full bg-rose-500/10 border border-rose-500/30 flex items-center justify-center mx-auto text-rose-400">
        <AlertTriangle className="w-6 h-6" />
      </div>
      <div>
        <h3 className="text-sm font-semibold tabular-nums text-[var(--text-primary)] uppercase tracking-wider">
          {title}
        </h3>
        <p className="text-xs text-[var(--text-secondary)] mt-1 leading-relaxed">
          {message}
        </p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)] text-[var(--accent-on)] tabular-nums text-xs font-semibold transition-colors shadow-sm"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Try Again</span>
        </button>
      )}
    </div>
  );
};
