'use client';

import React, { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import {
  BrainCircuit,
  Sparkles,
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  TrendingUp,
  ArrowRight,
  ChevronRight,
  Layers,
  Zap,
} from 'lucide-react';
import { marketDataService } from '@/services/marketDataService';
import { StockAnalysis } from '@/types/market';
import { formatINR } from '@/lib/utils';
import { SignalBadge } from '@/components/shared/SignalBadge';
import { ConfidenceScore } from '@/components/shared/ConfidenceScore';

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
        <div className="w-10 h-10 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-xs font-mono text-slate-400">Synthesizing multi-model AI reasoning for {currentSymbol}...</p>
      </div>
    );
  }

  const insight = analysis.aiInsights;
  const isBullish = analysis.trend === 'Bullish';

  return (
    <div className="space-y-8 max-w-6xl mx-auto pb-12">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-200 dark:border-[#1e283d]">
        <div>
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-blue-500/30 text-blue-600 dark:text-blue-400">
              <BrainCircuit className="w-5 h-5" />
            </div>
            <h1 className="text-xl sm:text-2xl font-bold font-mono tracking-tight text-slate-900 dark:text-slate-100">
              AI Market Insights
            </h1>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Understand why the system is bullish, bearish or neutral — structured from quantitative signals without hallucinations.
          </p>
        </div>

        {/* Stock Switcher Selector */}
        <div className="flex items-center gap-2 bg-slate-100 dark:bg-[#111622] p-1.5 rounded-xl border border-slate-200 dark:border-[#1e283d] overflow-x-auto max-w-full">
          {availableStocks.map((s) => (
            <button
              key={s.symbol}
              onClick={() => setCurrentSymbol(s.symbol)}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-all shrink-0 ${
                currentSymbol === s.symbol
                  ? 'bg-blue-600 text-white font-bold shadow-sm'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-200/60 dark:hover:bg-slate-800'
              }`}
            >
              {s.symbol}
            </button>
          ))}
        </div>
      </div>

      {/* 1. FEATURED CARD: Why is [SYMBOL] Bullish/Bearish Today? */}
      <section className="card-terminal p-6 bg-white dark:bg-gradient-to-r dark:from-[#111827] dark:via-[#131e33] dark:to-[#111827] border-l-4 border-l-blue-500 shadow-sm dark:shadow-2xl relative overflow-hidden border border-slate-200 dark:border-transparent">
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-6">
          <div className="space-y-3 flex-1">
            <div className="flex items-center gap-2">
              <SignalBadge type={analysis.trend} size="sm" />
              <span className="text-xs font-mono text-slate-500 dark:text-slate-400">
                {analysis.exchange} • Current: {formatINR(analysis.currentPrice)}
              </span>
            </div>

            <h2 className="text-lg sm:text-xl font-bold font-mono text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-amber-500 dark:text-amber-400 shrink-0" />
              <span>{insight.headlineQuestion}</span>
            </h2>

            <p className="text-sm text-slate-700 dark:text-slate-200 leading-relaxed font-sans max-w-3xl">
              {insight.explanation}
            </p>

            <div className="pt-2 flex items-center gap-4">
              <Link
                href={`/stocks/${analysis.symbol}`}
                className="inline-flex items-center gap-1.5 text-xs font-mono font-semibold text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 py-1.5 px-3 rounded-lg bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-blue-500/20 transition-colors"
              >
                <span>Open Full Research Terminal</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          </div>

          {/* AI Confidence Meter */}
          <div className="p-4 rounded-xl bg-slate-50 dark:bg-[#0b0e14]/90 border border-slate-200 dark:border-[#1e283d] flex flex-col items-center justify-center text-center shrink-0 min-w-[200px]">
            <span className="text-[10px] font-mono text-slate-500 dark:text-slate-400 uppercase tracking-wider block mb-1">
              AI Signal Alignment
            </span>
            <div className="text-3xl font-bold font-mono text-emerald-600 dark:text-emerald-400">
              {insight.aiConfidence.score}
              <span className="text-sm text-slate-400 font-normal">/100</span>
            </div>
            <span className="text-xs font-mono font-semibold text-emerald-600 dark:text-emerald-400 mt-0.5">
              Confidence: {insight.aiConfidence.level}
            </span>
            <p className="text-[10px] text-slate-500 dark:text-slate-400 max-w-[160px] mt-2 leading-tight">
              {insight.aiConfidence.note}
            </p>
          </div>
        </div>
      </section>

      {/* 2. WHY THIS SETUP QUALIFIES (6 Analytical Pillars) */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <span>Why This Setup Qualifies (Core Analytical Pillars)</span>
          </h3>
          <span className="text-[11px] font-mono text-slate-500 dark:text-slate-400">Rule-Engine Verification</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 font-mono">
          {insight.qualificationPillars.map((pillar) => {
            const isConf = pillar.status === 'Confirmed' || pillar.status === 'Positive';
            const isCaution = pillar.status === 'Caution' || pillar.status === 'Neutral';

            return (
              <div
                key={pillar.pillar}
                className="card-terminal p-4 space-y-2 flex flex-col justify-between bg-white dark:bg-[#0c1017] border border-slate-200 dark:border-[#1e283d] shadow-sm"
              >
                <div className="flex items-center justify-between pb-2 border-b border-slate-100 dark:border-[#1e283d]">
                  <span className="text-xs font-bold text-slate-800 dark:text-slate-200">{pillar.pillar}</span>
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
                <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed font-sans">
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
        <section className="card-terminal p-5 space-y-3 bg-white dark:bg-[#0c1017] border border-slate-200 dark:border-[#1e283d] shadow-sm">
          <div className="flex items-center gap-2 pb-2 border-b border-slate-100 dark:border-[#1e283d]">
            <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
            <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-slate-800 dark:text-slate-200">
              Identified Market & Structural Risks
            </h3>
          </div>
          <ul className="space-y-2.5 text-xs font-mono text-slate-700 dark:text-slate-300">
            {insight.risks.map((risk, idx) => (
              <li key={idx} className="flex items-start gap-2.5 p-2.5 rounded-lg bg-slate-50 dark:bg-[#0b0e14] border border-slate-200 dark:border-[#1e283d]">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5 shrink-0" />
                <span className="leading-relaxed font-sans">{risk}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* What Would Invalidate This View? */}
        <section className="card-terminal p-5 space-y-3 bg-white dark:bg-[#0c1017] border border-slate-200 dark:border-[#1e283d] shadow-sm">
          <div className="flex items-center gap-2 pb-2 border-b border-slate-100 dark:border-[#1e283d]">
            <ShieldAlert className="w-4 h-4 text-rose-600 dark:text-rose-400" />
            <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-slate-800 dark:text-slate-200">
              What Would Invalidate This View?
            </h3>
          </div>
          <ul className="space-y-2.5 text-xs font-mono text-slate-700 dark:text-slate-300">
            {insight.invalidationTriggers.map((trig, idx) => (
              <li key={idx} className="flex items-start gap-2.5 p-2.5 rounded-lg bg-slate-50 dark:bg-[#0b0e14] border border-slate-200 dark:border-[#1e283d]">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-500 mt-1.5 shrink-0" />
                <span className="leading-relaxed font-sans">{trig}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {/* 4. SCENARIOS MATRIX */}
      <section className="space-y-3">
        <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 flex items-center gap-2">
          <Layers className="w-4 h-4 text-blue-600 dark:text-blue-400" />
          <span>Contingency Scenarios & Zone Projections</span>
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs">
          {insight.scenarios.map((scen) => {
            const isBull = scen.type === 'bullish';
            const isBase = scen.type === 'base';

            return (
              <div
                key={scen.title}
                className={`card-terminal p-4 space-y-2.5 border-t-2 bg-white dark:bg-[#0c1017] border border-slate-200 dark:border-[#1e283d] shadow-sm ${
                  isBull
                    ? 'border-t-emerald-500'
                    : isBase
                    ? 'border-t-blue-500'
                    : 'border-t-rose-500'
                }`}
              >
                <div className="flex items-center justify-between pb-1 border-b border-slate-100 dark:border-[#1e283d]">
                  <span
                    className={`font-bold uppercase ${
                      isBull ? 'text-emerald-600 dark:text-emerald-400' : isBase ? 'text-blue-600 dark:text-blue-400' : 'text-rose-600 dark:text-rose-400'
                    }`}
                  >
                    {scen.title}
                  </span>
                  <span className="text-[10px] text-slate-500 dark:text-slate-400">
                    Conf: {scen.confidence}
                  </span>
                </div>

                <div>
                  <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block">Trigger</span>
                  <span className="text-slate-800 dark:text-slate-200">{scen.trigger}</span>
                </div>

                <div>
                  <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block">Expected Range</span>
                  <span
                    className={`font-bold ${
                      isBull ? 'text-emerald-600 dark:text-emerald-400' : isBase ? 'text-blue-600 dark:text-blue-400' : 'text-rose-600 dark:text-rose-400'
                    }`}
                  >
                    {scen.expectedZone}
                  </span>
                </div>

                <p className="text-[11px] text-slate-600 dark:text-slate-400 font-sans pt-1 border-t border-slate-100 dark:border-[#1e283d]">
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
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <AIInsightsContent />
    </Suspense>
  );
}

