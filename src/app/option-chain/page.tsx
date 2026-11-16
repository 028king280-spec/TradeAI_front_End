'use client';
import { PageHeading } from "@/components/shared/PageHeading";

import React, { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { optionsService } from '@/services/optionsService';
import { OptionChainResponse } from '@/types/options';
import { OptionChainTable } from '@/components/trading/OptionChainTable';
import { RefreshCw, ShieldCheck } from 'lucide-react';

function OptionChainContent() {
  const searchParams = useSearchParams();
  const initialSym = searchParams.get('symbol') || 'NIFTY 50';

  const [symbol, setSymbol] = useState<string>(initialSym);
  const [filterMode, setFilterMode] = useState<'ATM' | 'WIDE'>('ATM');
  const [expiry, setExpiry] = useState<string>('');
  const [chainData, setChainData] = useState<OptionChainResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);

  useEffect(() => {
    let isCancelled = false;
    async function loadChain() {
      setLoading(true);
      const data = await optionsService.getOptionChain(symbol, expiry || undefined, filterMode);
      if (!isCancelled && data) {
        setChainData(data);
        if (!expiry && data.selectedExpiry) {
          setExpiry(data.selectedExpiry);
        }
      }
      setLoading(false);
    }
    loadChain();
    return () => {
      isCancelled = true;
    };
  }, [symbol, expiry, filterMode, refreshTrigger]);

  const indexList = ['NIFTY 50', 'SENSEX', 'BANK NIFTY'];

  return (
    <div className="space-y-6 pb-12 tabular-nums">
      {/* Index Switcher & Header */}
      <PageHeading title="Option chain" description="Understand positioning across strikes before choosing a contract." actions={<><div className="flex items-center gap-2">
          <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)] text-xs">
            {indexList.map((idx) => (
              <button
                key={idx}
                onClick={() => {
                  setSymbol(idx);
                  setExpiry('');
                }}
                className={`px-3 py-1.5 rounded-md transition-all font-semibold ${
                  symbol.toUpperCase() === idx.toUpperCase()
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
            title="Refresh Chain"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div></>}/>

      {/* Main Table */}
      {loading && !chainData ? (
        <div className="flex flex-col items-center justify-center min-h-[40vh] space-y-3">
          <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
          <p className="text-xs text-[var(--text-muted)]">Loading {symbol} option chain & Greeks...</p>
        </div>
      ) : chainData ? (
        <OptionChainTable
          data={chainData}
          onFilterChange={(mode) => setFilterMode(mode)}
          onExpiryChange={(exp) => setExpiry(exp)}
        />
      ) : (
        <div className="p-8 text-center text-xs text-[var(--text-muted)] border border-dashed rounded-xl">
          Option chain data currently unavailable for {symbol}.
        </div>
      )}

      {/* Mandate Disclaimer */}
      <div className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[10px] text-[var(--text-muted)] flex items-center gap-2">
        <ShieldCheck className="w-3.5 h-3.5 text-[var(--accent-blue)] shrink-0" />
        <span>
          Options analytics and Greeks computed using Python mathematical models (Black-Scholes).
          Platform does NOT execute trades or orders.
        </span>
      </div>
    </div>
  );
}

export default function OptionChainPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[40vh]">
          <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <OptionChainContent />
    </Suspense>
  );
}
