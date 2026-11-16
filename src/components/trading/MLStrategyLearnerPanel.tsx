'use client';

import React, { useState, useEffect } from 'react';
import { Brain, Sparkles, TrendingUp, Target, Shield, CheckCircle2, RotateCcw, Award, Layers, ArrowUpRight } from 'lucide-react';

interface MLStrategyData {
  symbol: string;
  accuracySummary: {
    totalTrades: number;
    targetsHit: number;
    target1Hits: number;
    target2Hits: number;
    target3Hits: number;
    slHits: number;
    winRate: number;
    profitFactor: number;
    avgRealizedRr: number;
    netPointsGained: number;
  };
  modelPerformance: Record<
    string,
    {
      key: string;
      targetsHit: number;
      slHits: number;
      winRate: number;
      weight: number;
      status: string;
      edge: string;
      optimalCondition: string;
    }
  >;
  learnedRules: Array<{
    id: string;
    title: string;
    strategy: string;
    discovery: string;
    actionTaken: string;
    confidenceScore: number;
  }>;
  lastUpdated: string;
  systemStatus: string;
  algorithm: string;
}

interface MLStrategyLearnerPanelProps {
  indexSymbol: string;
}

export const MLStrategyLearnerPanel: React.FC<MLStrategyLearnerPanelProps> = ({ indexSymbol }) => {
  const [data, setData] = useState<MLStrategyData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshKey, setRefreshKey] = useState<number>(0);

  useEffect(() => {
    let isCancelled = false;
    async function fetchMLReport() {
      setLoading(true);
      try {
        const clean = indexSymbol.replace(/\s+/g, '');
        const res = await fetch(`/api/options/${clean}/ml-strategy`);
        if (res.ok) {
          const json = await res.json();
          if (!isCancelled && json) {
            setData(json);
          }
        }
      } catch (e) {
        console.debug('ML strategy fetch failed:', e);
      }
      setLoading(false);
    }
    fetchMLReport();
    return () => {
      isCancelled = true;
    };
  }, [indexSymbol, refreshKey]);

  const summary = data?.accuracySummary;
  const models = data?.modelPerformance || {};
  const rules = data?.learnedRules || [];

  return (
    <div className="rounded-2xl border border-[var(--accent-blue)]/25 bg-[var(--bg-surface)] overflow-hidden shadow-sm space-y-5 tabular-nums">
      {/* Header */}
      <div className="px-5 sm:px-6 pt-5 sm:pt-6 pb-4 border-b border-[var(--border-subtle)] flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-purple-500/15 border border-purple-500/25 flex items-center justify-center text-purple-600 dark:text-purple-400 shrink-0">
            <Brain className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-base font-semibold text-[var(--text-primary)]">
                Machine Learning Strategy Learner
              </h3>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-600 dark:text-purple-400 font-semibold border border-purple-500/30">
                Online RL Reinforcement
              </span>
            </div>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Self-calibrating strategy weights & target accuracy engine • Retrains on every Paper Trade
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setRefreshKey((k) => k + 1)}
            className="p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-all flex items-center gap-1"
            title="Refresh ML Diagnostics"
          >
            <RotateCcw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span className="text-[11px]">Sync ML Weights</span>
          </button>
        </div>
      </div>

      <div className="p-5 sm:p-6 space-y-6">
        {/* KPI Scorecard: Target Hit vs Stop Loss Hit */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {/* Targets Hit */}
          <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 space-y-1">
            <span className="text-[10px] text-emerald-600 dark:text-emerald-400 uppercase font-semibold flex items-center gap-1">
              <Target className="w-3.5 h-3.5" /> Targets Hit
            </span>
            <div className="text-2xl font-semibold text-emerald-600 dark:text-emerald-400">
              {summary ? summary.targetsHit : '--'}
            </div>
            <span className="text-[10px] text-[var(--text-muted)] block">
              T1: {summary?.target1Hits || 0} • T2: {summary?.target2Hits || 0} • T3: {summary?.target3Hits || 0}
            </span>
          </div>

          {/* Stop Losses Hit */}
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 space-y-1">
            <span className="text-[10px] text-rose-600 dark:text-rose-400 uppercase font-semibold flex items-center gap-1">
              <Shield className="w-3.5 h-3.5" /> Stop Losses Hit
            </span>
            <div className="text-2xl font-semibold text-rose-600 dark:text-rose-400">
              {summary ? summary.slHits : '--'}
            </div>
            <span className="text-[10px] text-[var(--text-muted)] block">
              Capped capital drawdowns
            </span>
          </div>

          {/* Win Rate % */}
          <div className="p-4 rounded-xl bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 space-y-1">
            <span className="text-[10px] text-[var(--accent-blue)] dark:text-[var(--accent-blue)] uppercase font-semibold flex items-center gap-1">
              <Award className="w-3.5 h-3.5" /> Target Accuracy
            </span>
            <div className="text-2xl font-semibold text-[var(--accent-blue)] dark:text-[var(--accent-blue)]">
              {summary ? `${summary.winRate}%` : '--'}
            </div>
            <span className="text-[10px] text-[var(--text-muted)] block">
              Audited win probability
            </span>
          </div>

          {/* Realized Profit Factor & R:R */}
          <div className="p-4 rounded-xl bg-purple-500/10 border border-purple-500/20 space-y-1">
            <span className="text-[10px] text-purple-600 dark:text-purple-400 uppercase font-semibold flex items-center gap-1">
              <TrendingUp className="w-3.5 h-3.5" /> Profit Factor
            </span>
            <div className="text-2xl font-semibold text-purple-600 dark:text-purple-400">
              {summary ? `${summary.profitFactor}x` : '--'}
            </div>
            <span className="text-[10px] text-[var(--text-muted)] block">
              Avg Realized R:R: 1:{summary?.avgRealizedRr || 1.9}
            </span>
          </div>
        </div>

        {/* Visual Target Hit vs SL Progress Bar */}
        {summary && (
          <div className="space-y-1.5 p-3.5 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
            <div className="flex items-center justify-between text-xs font-semibold">
              <span className="text-emerald-500 flex items-center gap-1">
                🎯 {summary.targetsHit} Targets Hit ({summary.winRate}%)
              </span>
              <span className="text-rose-400 flex items-center gap-1">
                🛡️ {summary.slHits} SL Hit ({(100 - summary.winRate).toFixed(1)}%)
              </span>
            </div>
            <div className="w-full h-2.5 rounded-full bg-rose-500/30 overflow-hidden flex">
              <div
                className="h-full bg-emerald-500 transition-all duration-500"
                style={{ width: `${summary.winRate}%` }}
              />
            </div>
          </div>
        )}

        {/* Model Performance Matrix (Adaptive Weights) */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase font-semibold text-[var(--text-muted)] tracking-wider flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
              SMC Strategy Models Calibration (ML Weighted)
            </span>
            <span className="text-[10px] text-[var(--accent-blue)]">Auto-prioritizes high edge models</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {Object.entries(models).map(([modelTitle, m]) => (
              <div
                key={modelTitle}
                className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] space-y-2.5 relative overflow-hidden"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-[var(--text-primary)] truncate max-w-[170px]" title={modelTitle}>
                    {modelTitle.split('(')[0]}
                  </span>
                  <span className={`text-[10px] px-2 py-0.5 rounded-md font-semibold uppercase ${
                    m.weight >= 1.2
                      ? 'bg-emerald-500/15 text-emerald-500 border border-emerald-500/30'
                      : m.weight >= 1.0
                      ? 'bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] border border-[var(--accent-blue)]/30'
                      : 'bg-amber-500/15 text-amber-500 border border-amber-500/30'
                  }`}>
                    {m.weight}x Weight
                  </span>
                </div>

                <div className="flex items-baseline justify-between">
                  <span className="text-xl font-semibold tabular-nums text-[var(--text-primary)]">
                    {m.winRate}%
                  </span>
                  <span className="text-[11px] font-semibold text-emerald-500 tabular-nums">
                    {m.edge}
                  </span>
                </div>

                <div className="text-[10px] text-[var(--text-muted)] space-y-1 pt-1 border-t border-[var(--border-subtle)]">
                  <div>🎯 {m.targetsHit} Targets / 🛡️ {m.slHits} SL</div>
                  <div className="text-[var(--text-secondary)] italic truncate" title={m.optimalCondition}>
                    💡 {m.optimalCondition}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Machine Learning Discovered Rules & New Strategies */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase font-semibold text-[var(--text-muted)] tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-amber-400" />
              ML Discovered Rules & Algorithmic Strategy Optimizations
            </span>
            <span className="text-[10px] text-amber-500">Bayesian Evidence Engine</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {rules.map((rule) => (
              <div
                key={rule.id}
                className="p-4 rounded-xl border border-[var(--accent-blue)]/15 bg-gradient-to-br from-[var(--accent-blue)]/5 via-[var(--bg-surface-elevated)] to-transparent space-y-2 hover:border-[var(--accent-blue)]/35 transition-all"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-[var(--text-primary)] flex items-center gap-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    {rule.title}
                  </span>
                  <span className="text-[10px] font-semibold text-purple-400 px-1.5 py-0.5 rounded bg-purple-500/10 border border-purple-500/20">
                    {rule.confidenceScore}% Conf
                  </span>
                </div>

                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                  {rule.discovery}
                </p>

                <div className="p-2.5 rounded-lg bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[11px] text-emerald-600 dark:text-emerald-400 flex items-start gap-1.5">
                  <ArrowUpRight className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span><strong>ML Action:</strong> {rule.actionTaken}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Footer System Status */}
      <div className="px-5 sm:px-6 py-3 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] flex flex-wrap items-center justify-between gap-2 text-[10px] text-[var(--text-muted)]">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping" />
          <span>Active ML Engine: {data?.algorithm || 'Online Bayesian Reinforcement Learner'}</span>
        </div>
        <span>Last Retrained: {data?.lastUpdated || 'Current'}</span>
      </div>
    </div>
  );
};

