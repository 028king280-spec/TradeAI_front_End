'use client';
import { PageHeading } from "@/components/shared/PageHeading";

import React, { useState, useEffect } from 'react';
import { optionsService } from '@/services/optionsService';
import { DetectedChartPattern } from '@/types/options';
import { ChartPatternsCard } from '@/components/trading/ChartPatternsCard';
import { RefreshCw, ShieldCheck } from 'lucide-react';

export default function ChartPatternsPage() {
  const [symbol, setSymbol] = useState<string>('NIFTY 50');
  const [patterns, setPatterns] = useState<DetectedChartPattern[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);

  const indices = ['NIFTY 50', 'SENSEX', 'BANK NIFTY'];

  useEffect(() => {
    let isCancelled = false;
    async function loadPatterns() {
      setLoading(true);
      const res = await optionsService.getPatterns(symbol);
      if (!isCancelled && res && res.patterns) {
        setPatterns(res.patterns);
      }
      setLoading(false);
    }
    loadPatterns();
    return () => {
      isCancelled = true;
    };
  }, [symbol, refreshTrigger]);

  return (
    <div className="space-y-6 pb-12 tabular-nums">
      {/* Header */}
      <PageHeading title="Patterns & structure" description="Market structure worth watching, with confirmation still required." actions={<><div className="flex items-center gap-2">
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

      {loading ? (
        <div className="flex flex-col items-center justify-center min-h-[40vh] space-y-3">
          <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
          <p className="text-xs text-[var(--text-muted)]">Scanning candlestick patterns for {symbol}...</p>
        </div>
      ) : (
        <ChartPatternsCard patterns={patterns} />
      )}

      {/* Disclaimers */}
      <div className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-[11px] text-[var(--text-muted)] flex items-start gap-2">
        <ShieldCheck className="w-4 h-4 text-[var(--accent-blue)] shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          Chart pattern recognition is derived purely from mathematical OHLC geometric relations.
          Patterns do NOT guarantee future price direction.
        </p>
      </div>
    </div>
  );
}
