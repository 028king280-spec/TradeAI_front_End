'use client';
import { PageHeading } from "@/components/shared/PageHeading";

import React, { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { Sparkles, ShieldAlert, CheckCircle2, AlertTriangle, ArrowRight, Layers } from 'lucide-react';
import { marketDataService } from '@/services/marketDataService';
import { StockAnalysis } from '@/types/market';
import { formatINR } from '@/lib/utils';
import { SignalBadge } from '@/components/shared/SignalBadge';


function AIInsightsContent() {
  const searchParams = useSearchParams();
  const initialSymbol = searchParams.get('symbol') || 'RELIANCE';

  const [currentSymbol, setCurrentSymbol] = useState(initialSymbol);
  const [analysis, setAnalysis] = useState<StockAnalysis | null>(null);
  const [availableStocks, setAvailableStocks] = useState<
    { symbol: string; companyName: string; trend: string }[]
  >([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadStockList() {
      const list = await marketDataService.getAvailableSymbols();
      setAvailableStocks(list);
    }
    loadStockList();
  }, []);

  useEffect(() => {
    async function loadAnalysis() {
      setLoading(true);
      const data = await marketDataService.getStockAnalysis(currentSymbol);
      setAnalysis(data);
      setLoading(false);
    }
    loadAnalysis();
  }, [currentSymbol]);

  if (loading || !analysis) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-4">
        <div className="w-10 h-10 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
        <p className="text-xs tabular-nums text-[var(--text-secondary)]">Synthesizing multi-model AI reasoning for {currentSymbol}...</p>
      </div>
    );
  }

  const insight = analysis.aiInsights;
  const isBullish = analysis.trend === 'Bullish';

  return (
    <div className="space-y-8 max-w-6xl mx-auto pb-12">
      {/* Page Header */}
      <PageHeading title="AI insights" description="Quantitative evidence and source-backed explanations in one workspace." actions={<><div className="flex items-center gap-2 bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface)] p-1.5 rounded-xl border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] overflow-x-auto max-w-full">
          {availableStocks.map((s) => (
            <button
              key={s.symbol}
              onClick={() => setCurrentSymbol(s.symbol)}
              className={`px-3 py-1.5 rounded-lg text-xs tabular-nums transition-all shrink-0 ${
                currentSymbol === s.symbol
                  ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] font-semibold shadow-sm'
                  : 'text-[var(--text-secondary)] dark:text-[var(--text-secondary)] hover:text-[var(--text-primary)] dark:hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-elevated)] dark:hover:bg-[var(--bg-surface-elevated)]'
              }`}
            >
              {s.symbol}
            </button>
          ))}
        </div></>}/>

      {/* 1. FEATURED CARD: Why is [SYMBOL] Bullish/Bearish Today? */}
      <section className="card-terminal p-6 bg-[var(--bg-surface)] dark:bg-gradient-to-r dark:from-[#111827] dark:via-[#131e33] dark:to-[#111827] border-l-4 border-l-blue-500 shadow-sm dark:shadow-2xl relative overflow-hidden border border-[var(--border-subtle)] dark:border-transparent">
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-6">
          <div className="space-y-3 flex-1">
            <div className="flex items-center gap-2">
              <SignalBadge type={analysis.trend} size="sm" />
              <span className="text-xs tabular-nums text-[var(--text-muted)] dark:text-[var(--text-secondary)]">
                {analysis.exchange} • Current: {formatINR(analysis.currentPrice)}
              </span>
            </div>

            <h2 className="text-lg sm:text-xl font-semibold tabular-nums text-[var(--text-primary)] dark:text-[var(--text-primary)] flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-amber-500 dark:text-amber-400 shrink-0" />
              <span>{insight.headlineQuestion}</span>
            </h2>

            <p className="text-sm text-[var(--text-secondary)] dark:text-[var(--text-primary)] leading-relaxed font-sans max-w-3xl">
              {insight.explanation}
            </p>

            <div className="pt-2 flex items-center gap-4">
              <Link
                href={`/stocks/${analysis.symbol}`}
                className="inline-flex items-center gap-1.5 text-xs tabular-nums font-semibold text-[var(--accent-blue)] dark:text-[var(--accent-blue)] hover:text-[var(--accent-blue)] dark:hover:text-[var(--accent-blue)] py-1.5 px-3 rounded-lg bg-[var(--accent-blue-bg)] dark:bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)] dark:border-[var(--accent-blue)]/20 transition-colors"
              >
                <span>Open Full Research Terminal</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          </div>

          {/* AI Confidence Meter */}
          <div className="p-4 rounded-xl bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] flex flex-col items-center justify-center text-center shrink-0 min-w-[200px]">
            <span className="text-[10px] tabular-nums text-[var(--text-muted)] dark:text-[var(--text-secondary)] uppercase tracking-wider block mb-1">
              AI Signal Alignment
            </span>
            <div className="text-3xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
              {insight.aiConfidence.score}
              <span className="text-sm text-[var(--text-secondary)] font-normal">/100</span>
            </div>
            <span className="text-xs tabular-nums font-semibold text-emerald-600 dark:text-emerald-400 mt-0.5">
              Confidence: {insight.aiConfidence.level}
            </span>
            <p className="text-[10px] text-[var(--text-muted)] dark:text-[var(--text-secondary)] max-w-[160px] mt-2 leading-tight">
              {insight.aiConfidence.note}
            </p>
          </div>
        </div>
      </section>

      {/* 2. WHY THIS SETUP QUALIFIES (6 Analytical Pillars) */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-xs tabular-nums font-semibold uppercase tracking-wider text-[var(--text-secondary)] dark:text-[var(--text-secondary)] flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <span>Why This Setup Qualifies (Core Analytical Pillars)</span>
          </h3>
          <span className="text-[11px] tabular-nums text-[var(--text-muted)] dark:text-[var(--text-secondary)]">Rule-Engine Verification</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 tabular-nums">
          {insight.qualificationPillars.map((pillar) => {
            const isConf = pillar.status === 'Confirmed' || pillar.status === 'Positive';
            const isCaution = pillar.status === 'Caution' || pillar.status === 'Neutral';

            return (
              <div
                key={pillar.pillar}
                className="card-terminal p-4 space-y-2 flex flex-col justify-between bg-[var(--bg-surface)] dark:bg-[var(--bg-surface)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] shadow-sm"
              >
                <div className="flex items-center justify-between pb-2 border-b border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
                  <span className="text-xs font-semibold text-[var(--text-primary)] dark:text-[var(--text-primary)]">{pillar.pillar}</span>
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded font-semibold ${
                      isConf
                        ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-500/30'
                        : isCaution
                        ? 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-500/30'
                        : 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400 border border-rose-200 dark:border-rose-500/30'
                    }`}
                  >
                    {pillar.status}
                  </span>
                </div>
                <p className="text-xs text-[var(--text-secondary)] dark:text-[var(--text-secondary)] leading-relaxed font-sans">
                  {pillar.explanation}
                </p>
              </div>
            );
          })}
        </div>
      </section>

      {/* 3. RISKS & INVALIDATION CRITERIA */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Identified Risks */}
        <section className="card-terminal p-5 space-y-3 bg-[var(--bg-surface)] dark:bg-[var(--bg-surface)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] shadow-sm">
          <div className="flex items-center gap-2 pb-2 border-b border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
            <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
            <h3 className="text-xs tabular-nums font-semibold uppercase tracking-wider text-[var(--text-primary)] dark:text-[var(--text-primary)]">
              Identified Market & Structural Risks
            </h3>
          </div>
          <ul className="space-y-2.5 text-xs tabular-nums text-[var(--text-secondary)] dark:text-[var(--text-secondary)]">
            {insight.risks.map((risk, idx) => (
              <li key={idx} className="flex items-start gap-2.5 p-2.5 rounded-lg bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5 shrink-0" />
                <span className="leading-relaxed font-sans">{risk}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* What Would Invalidate This View? */}
        <section className="card-terminal p-5 space-y-3 bg-[var(--bg-surface)] dark:bg-[var(--bg-surface)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] shadow-sm">
          <div className="flex items-center gap-2 pb-2 border-b border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
            <ShieldAlert className="w-4 h-4 text-rose-600 dark:text-rose-400" />
            <h3 className="text-xs tabular-nums font-semibold uppercase tracking-wider text-[var(--text-primary)] dark:text-[var(--text-primary)]">
              What Would Invalidate This View?
            </h3>
          </div>
          <ul className="space-y-2.5 text-xs tabular-nums text-[var(--text-secondary)] dark:text-[var(--text-secondary)]">
            {insight.invalidationTriggers.map((trig, idx) => (
              <li key={idx} className="flex items-start gap-2.5 p-2.5 rounded-lg bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-500 mt-1.5 shrink-0" />
                <span className="leading-relaxed font-sans">{trig}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {/* 4. SCENARIOS MATRIX */}
      <section className="space-y-3">
        <h3 className="text-xs tabular-nums font-semibold uppercase tracking-wider text-[var(--text-secondary)] dark:text-[var(--text-secondary)] flex items-center gap-2">
          <Layers className="w-4 h-4 text-[var(--accent-blue)] dark:text-[var(--accent-blue)]" />
          <span>Contingency Scenarios & Zone Projections</span>
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 tabular-nums text-xs">
          {insight.scenarios.map((scen) => {
            const isBull = scen.type === 'bullish';
            const isBase = scen.type === 'base';

            return (
              <div
                key={scen.title}
                className={`card-terminal p-4 space-y-2.5 border-t-2 bg-[var(--bg-surface)] dark:bg-[var(--bg-surface)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] shadow-sm ${
                  isBull
                    ? 'border-t-emerald-500'
                    : isBase
                    ? 'border-t-blue-500'
                    : 'border-t-rose-500'
                }`}
              >
                <div className="flex items-center justify-between pb-1 border-b border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
                  <span
                    className={`font-bold uppercase ${
                      isBull ? 'text-emerald-600 dark:text-emerald-400' : isBase ? 'text-[var(--accent-blue)] dark:text-[var(--accent-blue)]' : 'text-rose-600 dark:text-rose-400'
                    }`}
                  >
                    {scen.title}
                  </span>
                  <span className="text-[10px] text-[var(--text-muted)] dark:text-[var(--text-secondary)]">
                    Conf: {scen.confidence}
                  </span>
                </div>

                <div>
                  <span className="text-[10px] text-[var(--text-muted)] dark:text-[var(--text-secondary)] uppercase block">Trigger</span>
                  <span className="text-[var(--text-primary)] dark:text-[var(--text-primary)]">{scen.trigger}</span>
                </div>

                <div>
                  <span className="text-[10px] text-[var(--text-muted)] dark:text-[var(--text-secondary)] uppercase block">Expected Range</span>
                  <span
                    className={`font-bold ${
                      isBull ? 'text-emerald-600 dark:text-emerald-400' : isBase ? 'text-[var(--accent-blue)] dark:text-[var(--accent-blue)]' : 'text-rose-600 dark:text-rose-400'
                    }`}
                  >
                    {scen.expectedZone}
                  </span>
                </div>

                <p className="text-[11px] text-[var(--text-secondary)] dark:text-[var(--text-secondary)] font-sans pt-1 border-t border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
                  {scen.explanation}
                </p>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

export default function AIInsightsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[50vh]">
          <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <AIInsightsContent />
    </Suspense>
  );
}

