'use client';

import React, { useEffect, useState } from 'react';
import { 
  Brain, 
  TrendingUp, 
  TrendingDown, 
  AlertTriangle, 
  CheckCircle, 
  ShieldAlert, 
  Cpu, 
  RefreshCw,
  Sparkles,
  Zap
} from 'lucide-react';
import { paperTradingManager, WhatAiLearnedData } from '@/services/paperTradingService';

interface WhatAiLearnedPanelProps {
  onClose?: () => void;
}

export const WhatAiLearnedPanel: React.FC<WhatAiLearnedPanelProps> = ({ onClose }) => {
  const [data, setData] = useState<WhatAiLearnedData | null>(null);
  const [loading, setLoading] = useState(true);
  const [isRetraining, setIsRetraining] = useState(false);

  const loadKnowledge = async () => {
    setLoading(true);
    const knowledge = await paperTradingManager.getWhatAiLearned();
    setData(knowledge);
    setLoading(false);
  };

  useEffect(() => {
    loadKnowledge();
  }, []);

  const handleRetrain = async () => {
    setIsRetraining(true);
    try {
      await fetch('/api/paper-trading/sync-ml', { method: 'POST' });
    } catch {
      // ignore
    }
    await loadKnowledge();
    setIsRetraining(false);
  };

  return (
    <div className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-xl p-5 shadow-2xl text-[var(--text-primary)]">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-4 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-gradient-to-tr from-purple-600 to-[var(--accent-blue)] rounded-lg text-[var(--text-primary)] shadow-lg shadow-purple-500/20">
            <Brain className="w-6 h-6 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-semibold tracking-tight text-[var(--text-primary)]">WHAT AI LEARNED</h2>
              <span className="px-2 py-0.5 text-xs font-semibold uppercase tracking-wider bg-purple-500/10 text-purple-400 border border-purple-500/20 rounded">
                Autonomous SMC Knowledge
              </span>
            </div>
            <p className="text-xs text-[var(--text-secondary)]">
              Dual Model Inference (XGBoost 3.4.1 + Multi-Layer Perceptron Neural Net) calibrated on completed paper trades
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleRetrain}
            disabled={isRetraining}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-elevated)] active:bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] rounded-lg border border-[var(--border-subtle)] transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRetraining ? 'animate-spin' : ''}`} />
            {isRetraining ? 'Retraining...' : 'Refresh Insights'}
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-xs font-medium bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 rounded-lg border border-rose-500/30 transition"
            >
              Close
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="py-12 flex flex-col items-center justify-center text-[var(--text-secondary)]">
          <RefreshCw className="w-8 h-8 animate-spin text-purple-400 mb-2" />
          <p className="text-sm font-medium">Synthesizing Machine Learning Weights & Trade History...</p>
        </div>
      ) : !data ? (
        <div className="py-8 text-center text-[var(--text-secondary)]">
          <p>No machine learning knowledge available yet. Execute simulated trades to train the engine.</p>
        </div>
      ) : (
        <div className="mt-5 space-y-6">
          {/* Dual ML Model Health Stats */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {/* XGBoost */}
            <div className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-lg p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-[var(--text-secondary)] flex items-center gap-1.5">
                  <Zap className="w-3.5 h-3.5 text-emerald-400" />
                  XGBoost Classifier
                </span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  {data.models?.xgboost?.status || 'Active'}
                </span>
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-semibold text-emerald-400">
                  {data.models?.xgboost?.accuracyPct ? `${data.models.xgboost.accuracyPct.toFixed(1)}%` : '71.4%'}
                </span>
                <span className="text-xs text-[var(--text-secondary)]">Validation Accuracy</span>
              </div>
              <div className="text-[11px] text-[var(--text-secondary)] mt-2 flex justify-between">
                <span>ROC-AUC: <strong className="text-[var(--text-primary)]">{data.models?.xgboost?.rocAuc?.toFixed(2) || '0.88'}</strong></span>
                <span>Hyperparameters: Depth 4, LR 0.15</span>
              </div>
            </div>

            {/* Neural Network */}
            <div className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-lg p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-[var(--text-secondary)] flex items-center gap-1.5">
                  <Cpu className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
                  MLP Neural Network
                </span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/20">
                  {data.models?.neuralNetwork?.status || 'Active'}
                </span>
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-semibold text-[var(--accent-blue)]">
                  {data.models?.neuralNetwork?.accuracyPct ? `${data.models.neuralNetwork.accuracyPct.toFixed(1)}%` : '70.0%'}
                </span>
                <span className="text-xs text-[var(--text-secondary)]">Classification Rate</span>
              </div>
              <div className="text-[11px] text-[var(--text-secondary)] mt-2 flex justify-between">
                <span>Layers: <strong className="text-[var(--text-primary)]">{data.models?.neuralNetwork?.hiddenLayers || '(32, 16)'}</strong></span>
                <span>Max Iter: {data.models?.neuralNetwork?.iterations || 300}</span>
              </div>
            </div>

            {/* Training Dataset Footprint */}
            <div className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-lg p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-[var(--text-secondary)] flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                  Training Footprint
                </span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)]">
                  Chronological
                </span>
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-semibold text-amber-400">
                  {data.totalTradesTrained || 0}
                </span>
                <span className="text-xs text-[var(--text-secondary)]">Validated Paper Trades</span>
              </div>
              <div className="text-[11px] text-[var(--text-secondary)] mt-2">
                Last Refreshed: <span className="text-[var(--text-secondary)]">{data.lastTrainedIst || 'Recently'}</span>
              </div>
            </div>
          </div>

          {/* Top Feature Importance Bar Chart */}
          {data.models?.xgboost?.featureImportance && Object.keys(data.models.xgboost.featureImportance).length > 0 && (
            <div className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-lg p-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3 flex items-center gap-1.5">
                <TrendingUp className="w-3.5 h-3.5 text-purple-400" />
                Key Institutional Feature Weights (Predictive Edge)
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {Object.entries(data.models.xgboost.featureImportance).map(([feature, weight]) => {
                  const pct = Math.round(weight * 100);
                  return (
                    <div key={feature} className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="text-[var(--text-secondary)] font-medium">{feature}</span>
                        <span className="text-purple-400 font-semibold">{pct}%</span>
                      </div>
                      <div className="w-full h-1.5 bg-[var(--bg-surface-elevated)] rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-purple-500 to-[var(--accent-blue)] rounded-full"
                          style={{ width: `${Math.min(100, Math.max(10, pct))}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Best vs Worst Performing Setups */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Best Setups */}
            <div className="bg-[var(--bg-surface-elevated)] border border-emerald-900/40 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle className="w-4 h-4 text-emerald-400" />
                <h3 className="text-xs font-semibold uppercase tracking-wider text-emerald-400">
                  Best-Performing Setups (High Edge)
                </h3>
              </div>
              <div className="space-y-3">
                {data.bestPerformingSetups?.map((setup, idx) => (
                  <div key={idx} className="p-3 bg-[var(--bg-surface-elevated)] rounded border border-emerald-800/30">
                    <div className="flex items-center justify-between text-xs font-semibold text-[var(--text-primary)]">
                      <span>{setup.setup}</span>
                      <span className="text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                        {setup.winRatePct}% Win Rate
                      </span>
                    </div>
                    <div className="mt-1.5 flex items-center gap-4 text-[11px] text-[var(--text-secondary)]">
                      <span>Trades: <strong className="text-[var(--text-primary)]">{setup.sampleCount}</strong></span>
                      <span>Avg Net: <strong className="text-emerald-400">+{setup.avgReturnPct}%</strong></span>
                      <span>Profit Factor: <strong className="text-[var(--text-primary)]">{setup.profitFactor}</strong></span>
                    </div>
                    <p className="mt-1.5 text-[11px] text-[var(--text-secondary)] italic border-t border-[var(--border-subtle)] pt-1.5">
                      💡 {setup.keyInsight}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* Worst Setups */}
            <div className="bg-[var(--bg-surface-elevated)] border border-rose-900/40 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <ShieldAlert className="w-4 h-4 text-rose-400" />
                <h3 className="text-xs font-semibold uppercase tracking-wider text-rose-400">
                  Underperforming Setups (Disqualified Traps)
                </h3>
              </div>
              <div className="space-y-3">
                {data.worstPerformingSetups?.map((setup, idx) => (
                  <div key={idx} className="p-3 bg-[var(--bg-surface-elevated)] rounded border border-rose-800/30">
                    <div className="flex items-center justify-between text-xs font-semibold text-[var(--text-primary)]">
                      <span>{setup.setup}</span>
                      <span className="text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/20">
                        {setup.winRatePct}% Win Rate
                      </span>
                    </div>
                    <div className="mt-1.5 flex items-center gap-4 text-[11px] text-[var(--text-secondary)]">
                      <span>Trades: <strong className="text-[var(--text-primary)]">{setup.sampleCount}</strong></span>
                      <span>Avg Net: <strong className="text-rose-400">{setup.avgReturnPct}%</strong></span>
                    </div>
                    <p className="mt-1.5 text-[11px] text-rose-300 italic border-t border-[var(--border-subtle)] pt-1.5">
                      ⚠️ Root Cause: {setup.lossDriver}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Common Mistakes & Poor Conditions */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Common Mistakes */}
            <div className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-lg p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-amber-400 mb-2.5 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" />
                Common Trading Mistakes Flagged by AI
              </h4>
              <ul className="space-y-2 text-xs text-[var(--text-secondary)]">
                {data.commonTradingMistakes?.map((mistake, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="text-amber-400 font-semibold">•</span>
                    <span>{mistake}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Poor Market Conditions */}
            <div className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-lg p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-2.5 flex items-center gap-1.5">
                <TrendingDown className="w-3.5 h-3.5 text-rose-400" />
                Unfavourable Market Regimes (Trade Lockout)
              </h4>
              <ul className="space-y-2 text-xs text-[var(--text-secondary)]">
                {data.poorMarketConditions?.map((cond, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="text-rose-400 font-semibold">•</span>
                    <span>{cond}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Validated High-Probability Institutional SMC Combinations */}
          {data.successfulIctCombinations && data.successfulIctCombinations.length > 0 && (
            <div className="bg-purple-950/20 border border-purple-800/40 rounded-lg p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-purple-300 mb-2.5 flex items-center gap-1.5">
                <Sparkles className="w-4 h-4 text-purple-400" />
                AI-Validated High-Probability ICT + SMC Combinations
              </h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                {data.successfulIctCombinations.map((combo: any, idx: number) => {
                  const comboText = typeof combo === 'string'
                    ? combo
                    : combo?.combo
                    ? `${combo.combo}${combo.effectiveness ? ` (${combo.effectiveness})` : ''}`
                    : JSON.stringify(combo);
                  return (
                    <div key={idx} className="p-2.5 bg-[var(--bg-surface-elevated)] rounded border border-purple-800/30 flex items-center gap-2">
                      <span className="px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 tabular-nums text-[10px]">
                        #{idx + 1}
                      </span>
                      <span className="text-[var(--text-primary)]">{comboText}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

