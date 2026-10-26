import React from 'react';
import { AlertCircle } from 'lucide-react';

export const DisclaimerBanner: React.FC = () => {
  return (
    <footer className="w-full mt-12 py-6 border-t border-slate-200 dark:border-[#1e283d] bg-white/80 dark:bg-[#0b0e14]/80 backdrop-blur text-xs text-slate-600 dark:text-slate-400">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="flex items-start gap-2.5 max-w-3xl">
          <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <p className="leading-relaxed">
            <strong className="text-slate-800 dark:text-slate-200 font-semibold">Regulatory Disclaimer:</strong> Market analysis is probabilistic and for informational and educational purposes only. It is not a guarantee of future price movement or profit. Always perform your own due diligence and manage risk. This platform is not a registered SEBI research analyst, broker, or order execution system.
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="px-2.5 py-1 rounded bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30 text-amber-800 dark:text-amber-300 font-mono text-[11px] font-medium tracking-wide">
            SIMULATED MOCK FEED
          </span>
          <span className="text-slate-500 dark:text-slate-400 font-mono text-xs">
            IST • INR (₹)
          </span>
        </div>
      </div>
    </footer>
  );
};
