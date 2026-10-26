'use client';

import React, { useState, useEffect } from 'react';
import { optionsService } from '@/services/optionsService';
import { OptionsMarketSentiment } from '@/types/options';
import { MarketSentimentPanel } from '@/components/trading/MarketSentimentPanel';
import { Gauge, RefreshCw, ShieldCheck } from 'lucide-react';

export default function MarketSentimentPage() {
  const [symbol, setSymbol] = useState<string>('NIFTY 50');
  const [sentiment, setSentiment] = useState<OptionsMarketSentiment | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);

  const indices = ['NIFTY 50', 'SENSEX', 'BANK NIFTY'];

  useEffect(() => {
    let isCancelled = false;
    async function loadSentiment() {
      setLoading(true);
      const res = await optionsService.getSentiment(symbol);
      if (!isCancelled && res && res.sentiment) {
        setSentiment(res.sentiment);
      }
      setLoading(false);
    }
    loadSentiment();
    return () => {
      isCancelled = true;
    };
  }, [symbol, refreshTrigger]);

  return (
    <div className="space-y-6 pb-12 font-mono">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-[var(--border-subtle)]">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
              <Gauge className="w-4 h-4 text-blue-500" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-[var(--text-primary)]">
                Options Market Sentiment Engine
              </h1>
              <p className="text-xs text-[var(--text-muted)]">
                Multi-factor quantitative evidence: Trend, VWAP, PCR, Open Interest shifts & Volatility
              </p>
            </div>
          </div>
        </div>

        {/* Index Switcher */}
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)] text-xs">
            {indices.map((idx) => (
              <button
                key={idx}
                onClick={() => setSymbol(idx)}
                className={`px-3 py-1.5 rounded-md transition-all font-semibold ${
                  symbol === idx
                    ? 'bg-blue-600 text-white shadow-xs'
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
        </div>
      </div>

      {loading && !sentiment ? (
        <div className="flex flex-col items-center justify-center min-h-[40vh] space-y-3">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-xs text-[var(--text-muted)]">Evaluating multi-factor sentiment for {symbol}...</p>
        </div>
      ) : sentiment ? (
        <MarketSentimentPanel sentiment={sentiment} />
      ) : null}

      {/* Disclaimers */}
      <div className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-[11px] text-[var(--text-muted)] flex items-start gap-2">
        <ShieldCheck className="w-4 h-4 text-blue-500 shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          Sentiment scores are calculated strictly from quantitative market metrics (price relative to VWAP, moving average slope,
          options PCR, and open interest shifts). The platform does NOT execute trades or guarantee outcomes.
        </p>
      </div>
    </div>
  );
}
