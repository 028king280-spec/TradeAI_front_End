'use client';
import { PageHeading } from "@/components/shared/PageHeading";

import React, { useState, useEffect } from 'react';
import { optionsService } from '@/services/optionsService';
import { SessionOutlookData } from '@/types/options';
import { SessionOutlookCard } from '@/components/trading/SessionOutlookCard';
import { RefreshCw, ShieldCheck } from 'lucide-react';

export default function OutlookPage() {
  const [symbol, setSymbol] = useState<string>('NIFTY 50');
  const [todayData, setTodayData] = useState<SessionOutlookData | null>(null);
  const [nextData, setNextData] = useState<SessionOutlookData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);

  const indices = ['NIFTY 50', 'SENSEX', 'BANK NIFTY'];

  useEffect(() => {
    let isCancelled = false;
    async function loadOutlook() {
      setLoading(true);
      const res = await optionsService.getOutlook(symbol);
      if (!isCancelled && res) {
        setTodayData(res.todayOutlook);
        setNextData(res.nextSessionOutlook);
      }
      setLoading(false);
    }
    loadOutlook();
    return () => {
      isCancelled = true;
    };
  }, [symbol, refreshTrigger]);

  return (
    <div className="space-y-6 pb-12 tabular-nums">
      {/* Header */}
      <PageHeading title="Session outlook" description="Prepare for the session with clear scenarios and invalidation levels." actions={<><div className="flex items-center gap-2">
          <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)] text-xs">
            {indices.map((idx) => (
              <button
                key={idx}
                onClick={() => setSymbol(idx)}
                className={`px-3 py-1.5 rounded-md transition-all font-semibold ${
                  symbol === idx
                    ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] shadow-xs'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                }`}
              >
                {idx}
              </button>
            ))}
          </div>

          <button
            onClick={() => setRefreshTrigger((prev) => prev + 1)}
            className="p-1.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div></>}/>

      {loading && (!todayData || !nextData) ? (
        <div className="flex flex-col items-center justify-center min-h-[40vh] space-y-3">
          <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
          <p className="text-xs text-[var(--text-muted)]">Calculating volatility bounds for {symbol}...</p>
        </div>
      ) : todayData && nextData ? (
        <SessionOutlookCard todayData={todayData} nextSessionData={nextData} />
      ) : null}

      {/* Disclaimers */}
      <div className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-[11px] text-[var(--text-muted)] flex items-start gap-2">
        <ShieldCheck className="w-4 h-4 text-[var(--accent-blue)] shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          Expected range boundaries and scenarios are computed using historical ATR and option implied volatility.
          Next-session planning automatically accounts for weekend closures and officially notified NSE/BSE holidays.
        </p>
      </div>
    </div>
  );
}
