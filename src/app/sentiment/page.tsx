'use client';

import React, { useState, useEffect } from 'react';
import { optionsService } from '@/services/optionsService';
import { OptionsMarketSentiment } from '@/types/options';
import { MarketSentimentPanel } from '@/components/trading/MarketSentimentPanel';
import { MarketSentimentRadar } from '@/components/trading/GodsEyeObserver';
import { StockSentimentCalculator } from '@/components/trading/StockSentimentCalculator';
import { Gauge, RefreshCw, ShieldCheck, Activity, Layers, Crosshair, Sparkles } from 'lucide-react';

export default function MarketSentimentPage() {
  const [symbol, setSymbol] = useState<string>('NIFTY 50');
  const [sentiment, setSentiment] = useState<OptionsMarketSentiment | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);
  const [viewMode, setViewMode] = useState<'stock-calculator' | 'all' | 'indicators' | 'index-deep-dive'>('stock-calculator');

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
      {/* Top Header & View Filter */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-[var(--border-subtle)]">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-indigo-500" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-[var(--text-primary)]">
                Stock Sentiment Calculator & Market Indicators
              </h1>
              <p className="text-xs text-[var(--text-muted)]">
                On-demand stock news sentiment analysis, cross-asset indicators, & index multi-factor sentiment
              </p>
            </div>
          </div>
        </div>

        {/* View Switcher Tabs */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)] text-xs flex-wrap">
            <button
              onClick={() => setViewMode('stock-calculator')}
              className={`px-3 py-1.5 rounded-md transition-all font-semibold flex items-center gap-1.5 ${
                viewMode === 'stock-calculator'
                  ? 'bg-indigo-600 text-white shadow-xs'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Stock Calculator</span>
            </button>
            <button
              onClick={() => setViewMode('all')}
              className={`px-3 py-1.5 rounded-md transition-all font-semibold ${
                viewMode === 'all'
                  ? 'bg-blue-600 text-white shadow-xs'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              All Views
            </button>
            <button
              onClick={() => setViewMode('indicators')}
              className={`px-3 py-1.5 rounded-md transition-all font-semibold ${
                viewMode === 'indicators'
                  ? 'bg-blue-600 text-white shadow-xs'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              Bullish / Bearish Matrix
            </button>
            <button
              onClick={() => setViewMode('index-deep-dive')}
              className={`px-3 py-1.5 rounded-md transition-all font-semibold ${
                viewMode === 'index-deep-dive'
                  ? 'bg-blue-600 text-white shadow-xs'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              Options Index
            </button>
          </div>

          <button
            onClick={() => setRefreshTrigger((prev) => prev + 1)}
            title="Refresh Sentiment"
            className="p-1.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* SECTION 0: ON-DEMAND STOCK SENTIMENT CALCULATOR */}
      {(viewMode === 'stock-calculator' || viewMode === 'all') && (
        <div className="space-y-4">
          <StockSentimentCalculator />
        </div>
      )}

      {/* SECTION 1: Bullish & Bearish Signal Array (The Observer Matrix) */}
      {(viewMode === 'all' || viewMode === 'indicators') && (
        <div className="space-y-4 pt-4 border-t border-[var(--border-subtle)]">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-blue-500" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-[var(--text-primary)]">
              Cross-Asset Market Sentiment Matrix
            </h2>
          </div>
          <MarketSentimentRadar />
        </div>
      )}

      {/* SECTION 2: Options Index Sentiment Deep Dive */}
      {(viewMode === 'all' || viewMode === 'index-deep-dive') && (
        <div className="space-y-4 pt-4 border-t border-[var(--border-subtle)]">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-[var(--border-subtle)]">
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-blue-500" />
              <h2 className="text-sm font-bold uppercase tracking-wider text-[var(--text-primary)]">
                Options Index Multi-Factor Sentiment
              </h2>
            </div>

            {/* Index Switcher */}
            <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)] text-xs">
              {indices.map((idx) => (
                <button
                  key={idx}
                  onClick={() => setSymbol(idx)}
                  className={`px-3 py-1 rounded-md transition-all font-semibold ${
                    symbol === idx
                      ? 'bg-blue-600 text-white shadow-xs'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                  }`}
                >
                  {idx}
                </button>
              ))}
            </div>
          </div>

          {loading && !sentiment ? (
            <div className="flex flex-col items-center justify-center min-h-[25vh] space-y-3">
              <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-xs text-[var(--text-muted)]">Evaluating multi-factor sentiment for {symbol}...</p>
            </div>
          ) : sentiment ? (
            <MarketSentimentPanel sentiment={sentiment} />
          ) : null}
        </div>
      )}

      {/* Disclaimers */}
      <div className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-[11px] text-[var(--text-muted)] flex items-start gap-2">
        <ShieldCheck className="w-4 h-4 text-blue-500 shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          Stock Sentiment is calculated on-demand from real-time financial news headlines and quantitative price action confirmation.
          The platform does NOT execute trades or guarantee financial outcomes. Always apply strict risk management.
        </p>
      </div>
    </div>
  );
}
