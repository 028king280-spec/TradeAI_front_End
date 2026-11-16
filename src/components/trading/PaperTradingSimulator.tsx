'use client';

import React, { useState, useEffect } from 'react';
import {
  paperTradingManager,
  PaperTradingState,
  PaperPosition,
} from '@/services/paperTradingService';
import {
  Gamepad2,
  TrendingUp,
  TrendingDown,
  DollarSign,
  ShieldAlert,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  RotateCcw,
  Clock,
  ArrowRight,
  Layers,
  ChevronDown,
  ChevronUp,
  Brain,
  Award,
  Sparkles,
} from 'lucide-react';
import { WhatAiLearnedPanel } from './WhatAiLearnedPanel';
import { AITradeReviewModal } from './AITradeReviewModal';

export const PaperTradingSimulator: React.FC = () => {
  const [state, setState] = useState<PaperTradingState>(paperTradingManager.getState());
  const [activeTab, setActiveTab] = useState<'POSITIONS' | 'JOURNAL' | 'AI_KNOWLEDGE'>('POSITIONS');
  const [isExpanded, setIsExpanded] = useState<boolean>(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [selectedTradeForReview, setSelectedTradeForReview] = useState<PaperPosition | null>(null);

  useEffect(() => {
    // Automatically hydrate state directly from backend paper trading engine
    paperTradingManager.syncWithBackend().then((synced) => {
      if (synced) setState(synced);
    });
    const unsub = paperTradingManager.subscribe((updated) => {
      setState(updated);
    });
    return unsub;
  }, []);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleClosePosition = (posId: string) => {
    const pos = state.positions.find((p) => p.id === posId);
    const exitPrice = pos ? (pos.currentPremium > 0 ? pos.currentPremium : pos.entryPremium) : undefined;
    const res = paperTradingManager.closePosition(posId, exitPrice, 'Manual Close');
    if (res.success) {
      showToast(res.message);
    }
  };

  const handleTrailStopLoss = (pos: PaperPosition) => {
    // Trail to cost (entry premium)
    const res = paperTradingManager.trailStopLoss(pos.id, pos.entryPremium);
    if (res.success) {
      showToast(`Risk-Free Trailing: SL set to entry cost ₹${pos.entryPremium.toFixed(2)}.`);
    }
  };

  const handlePartialExit = async (pos: PaperPosition) => {
    const exitLots = Math.max(1, Math.floor(pos.lots / 2));
    const res = await paperTradingManager.executePartialExit(
      pos.id,
      exitLots,
      pos.currentPremium,
      'Target 1 Hit (50% Partial)'
    );
    if (res.success) {
      showToast(res.message);
    }
  };

  const handleReset = () => {
    if (window.confirm('Reset virtual portfolio back to ₹1,00,000 starting capital?')) {
      paperTradingManager.resetAccount();
      showToast('Virtual portfolio reset to ₹1,00,000.');
    }
  };

  const totalUnrealizedPnl = state.positions.reduce((acc, p) => acc + p.pnl, 0);
  const totalMarginUsed = state.positions.reduce((acc, p) => acc + p.marginUsed, 0);
  const netPortfolioValue = state.balance + totalMarginUsed + totalUnrealizedPnl;
  const portfolioReturnPct = ((netPortfolioValue - state.startingBalance) / state.startingBalance) * 100.0;
  const totalCompleted = state.winCount + state.lossCount;
  const winRate = totalCompleted > 0 ? Math.round((state.winCount / totalCompleted) * 100) : 0;

  return (
    <div className="rounded-2xl border border-indigo-500/25 bg-[var(--bg-surface)] p-5 space-y-4 font-mono shadow-sm">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="p-3 rounded-xl bg-indigo-600 text-white text-xs font-bold flex items-center justify-between shadow-lg animate-in fade-in slide-in-from-top-2">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-300" />
            <span>{toastMessage}</span>
          </div>
          <button onClick={() => setToastMessage(null)} className="text-white/80 hover:text-white text-xs">
            ✕
          </button>
        </div>
      )}

      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/25 flex items-center justify-center">
            <Gamepad2 className="w-4 h-4 text-indigo-500" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
                1-CLICK VIRTUAL / PAPER TRADING SIMULATOR
              </h3>
              <span className="text-[10px] px-2 py-0.5 rounded-full font-extrabold bg-indigo-500/15 text-indigo-500 border border-indigo-500/30">
                ZERO-RISK PRACTICE
              </span>
            </div>
            <span className="text-[10px] text-[var(--text-muted)]">
              Simulate qualified SMC options setups with real-time execution & P&L tracking (Module 15)
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleReset}
            className="px-2.5 py-1 text-xs rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-amber-500 hover:border-amber-500/30 flex items-center gap-1 transition-all"
            title="Reset Portfolio to ₹1,00,000"
          >
            <RotateCcw className="w-3 h-3" />
            Reset
          </button>
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1 rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
          >
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Metrics Strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="p-3 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider block">Available Margin</span>
          <span className="text-base font-bold text-[var(--text-primary)]" suppressHydrationWarning>
            ₹{state.balance.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </span>
        </div>

        <div className="p-3 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider block">Active Positions</span>
          <span className="text-base font-bold text-blue-500" suppressHydrationWarning>
            {state.positions.length} Open
          </span>
        </div>

        <div className="p-3 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider block">Realized Net P&L</span>
          <span
            className={`text-base font-bold flex items-center gap-1 ${
              state.totalRealizedPnl >= 0 ? 'text-emerald-500' : 'text-rose-500'
            }`}
            suppressHydrationWarning
          >
            {state.totalRealizedPnl >= 0 ? '+' : ''}₹{state.totalRealizedPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </span>
        </div>

        <div className="p-3 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider block">Win Rate</span>
          <span className="text-base font-bold text-[var(--text-primary)]" suppressHydrationWarning>
            {winRate}% ({state.winCount}W / {state.lossCount}L)
          </span>
        </div>
      </div>

      {isExpanded && (
        <div className="space-y-4 pt-1">
          {/* Tabs */}
          <div className="flex items-center gap-2 border-b border-[var(--border-subtle)] pb-2 text-xs">
            <button
              onClick={() => setActiveTab('POSITIONS')}
              className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                activeTab === 'POSITIONS'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              Open Positions ({state.positions.length})
            </button>
            <button
              onClick={() => setActiveTab('JOURNAL')}
              className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                activeTab === 'JOURNAL'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              Completed Trades Journal ({state.closedTrades.length})
            </button>
            <button
              onClick={() => setActiveTab('AI_KNOWLEDGE')}
              className={`px-3 py-1.5 rounded-lg font-bold transition-all flex items-center gap-1.5 ${
                activeTab === 'AI_KNOWLEDGE'
                  ? 'bg-purple-600 text-white shadow-sm'
                  : 'text-purple-400 hover:text-purple-300'
              }`}
            >
              <Brain className="w-3.5 h-3.5" />
              🧠 What AI Learned
            </button>
          </div>

          {/* TAB 1: ACTIVE POSITIONS */}
          {activeTab === 'POSITIONS' && (
            <div className="space-y-3">
              {state.positions.length === 0 ? (
                <div className="py-8 text-center text-xs text-[var(--text-muted)] space-y-2 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
                  <Gamepad2 className="w-6 h-6 text-indigo-400 mx-auto" />
                  <p className="font-semibold text-[var(--text-secondary)]">No active virtual positions open.</p>
                  <p className="text-[11px] max-w-sm mx-auto">
                    Click the <strong className="text-indigo-400">"🎮 Paper Trade"</strong> button on any qualified setup below to simulate a live trade!
                  </p>
                </div>
              ) : (
                <div className="space-y-2.5">
                  {state.positions.map((pos) => {
                    const isMtmUnavailable = pos.isMtmAvailable === false || pos.feedStatus === 'DATA_OFFLINE' || pos.feedStatus === 'UNAVAILABLE';
                    const isProfit = pos.pnl >= 0;
                    const estExitCosts = pos.statutoryCosts || pos.costBreakdown?.totalStatutoryCosts || 48.5;
                    const netMtmPnl = pos.netPnl !== undefined ? pos.netPnl : pos.pnl - estExitCosts;

                    return (
                      <div
                        key={pos.id}
                        className={`p-3.5 rounded-xl border transition-all ${
                          isMtmUnavailable
                            ? 'border-amber-500/30 bg-amber-500/[0.03]'
                            : isProfit
                            ? 'border-emerald-500/30 bg-emerald-500/[0.03]'
                            : 'border-rose-500/30 bg-rose-500/[0.03]'
                        }`}
                      >
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b border-[var(--border-subtle)]">
                          <div className="flex items-center gap-2">
                            <span
                              className={`text-[10px] px-2 py-0.5 rounded font-extrabold ${
                                pos.bias === 'CE'
                                  ? 'bg-emerald-500 text-white'
                                  : 'bg-rose-500 text-white'
                              }`}
                            >
                              {pos.bias}
                            </span>
                            <span className="font-bold text-xs text-[var(--text-primary)]">
                              {pos.contractSymbol}
                            </span>
                            <span className="text-[10px] text-[var(--text-muted)]">
                              ({pos.lots} Lot • {pos.totalQuantity} Qty)
                            </span>
                            <span className="text-[9.5px] px-1.5 py-0.2 rounded bg-white/[0.05] text-slate-400 font-mono">
                              ID: {pos.id}
                            </span>
                          </div>

                          <div className="text-right">
                            <span className="text-[10px] text-[var(--text-muted)] mr-2">Net MTM P&L:</span>
                            {isMtmUnavailable ? (
                              <span className="text-xs font-bold text-amber-500 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                                MTM UNAVAILABLE (FEED OFFLINE)
                              </span>
                            ) : (
                              <span
                                className={`text-sm font-extrabold ${
                                  netMtmPnl >= 0 ? 'text-emerald-500' : 'text-rose-500'
                                }`}
                              >
                                {netMtmPnl >= 0 ? '+' : ''}₹{netMtmPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })} (
                                {pos.pnlPercent >= 0 ? '+' : ''}{pos.pnlPercent.toFixed(1)}%)
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Position Details Ladder */}
                        <div className="py-2.5 px-3 rounded-lg bg-[var(--bg-surface)] border border-[var(--border-subtle)] grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs">
                          <div>
                            <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold block uppercase">Kharida (Entry):</span>
                            <span className="font-extrabold text-emerald-600 dark:text-emerald-400 font-mono text-sm">₹{pos.entryPremium.toFixed(2)}</span>
                            <span className="text-[9.5px] text-[var(--text-muted)] block">Time: {pos.openedAt}</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-[var(--text-muted)] font-semibold block uppercase">Current Verified CMP:</span>
                            <span className="font-extrabold text-[var(--text-primary)] font-mono text-sm">
                              {isMtmUnavailable ? 'UNAVAILABLE' : `₹${pos.currentPremium.toFixed(2)}`}
                            </span>
                            <span className="text-[9.5px] text-[var(--text-muted)] block">Qty: {pos.totalQuantity}</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-indigo-400 font-semibold block uppercase">Invested / Est Fee:</span>
                            <span className="font-bold text-indigo-400 font-mono">₹{pos.marginUsed.toLocaleString('en-IN')}</span>
                            <span className="text-[9.5px] text-slate-400 block">Est Exit Cost: ₹{estExitCosts.toFixed(1)}</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-rose-500 font-semibold block uppercase">Stop-Loss:</span>
                            <span className="font-bold text-rose-500 font-mono">₹{pos.stopLoss.toFixed(2)}</span>
                            <span className="text-[9.5px] text-rose-400/80 block">Risk Managed</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-emerald-500 font-semibold block uppercase">Targets:</span>
                            <span className="font-bold text-emerald-500 font-mono text-xs">T1: ₹{pos.target1.toFixed(1)}</span>
                            <span className="text-[9.5px] text-emerald-400/80 block">T2: ₹{pos.target2.toFixed(1)}</span>
                          </div>
                        </div>

                        {/* Targets Ladder Strip */}
                        <div className="mt-2 p-2 rounded-lg bg-[var(--bg-surface)] border border-[var(--border-subtle)] flex items-center justify-between text-[11px] font-mono">
                          <span className="text-emerald-500 font-bold">
                            T1 (+30%): ₹{pos.target1.toFixed(1)} <span className="text-[9.5px] px-1 py-0.2 bg-emerald-500/15 rounded">High (82%)</span>
                          </span>
                          <span className="text-amber-500 font-bold">
                            T2 (+55%): ₹{pos.target2.toFixed(1)} <span className="text-[9.5px] px-1 py-0.2 bg-amber-500/15 rounded">Moderate (54%)</span>
                          </span>
                          {pos.target3 && (
                            <span className="text-slate-400 font-bold">
                              T3 (+85%): ₹{pos.target3.toFixed(1)} <span className="text-[9.5px] px-1 py-0.2 bg-rose-500/15 text-rose-400 rounded">Low (24%)</span>
                            </span>
                          )}
                        </div>

                        {/* Action Buttons */}
                        <div className="pt-2 border-t border-[var(--border-subtle)] flex items-center justify-between text-xs">
                          <span className="text-[10px] text-[var(--text-muted)]">
                            Opened: {pos.openedAt} • {pos.smcModel || 'SMC Setup'}
                          </span>
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => handlePartialExit(pos)}
                              className="px-2.5 py-1 text-[11px] font-bold rounded-lg bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20 border border-emerald-500/30 transition-all"
                              title="Book 50% Profit at Target 1 and trail stop to cost"
                            >
                              50% Partial Exit
                            </button>
                            <button
                              onClick={() => handleTrailStopLoss(pos)}
                              className="px-2.5 py-1 text-[11px] font-bold rounded-lg bg-blue-500/10 text-blue-500 hover:bg-blue-500/20 border border-blue-500/30 transition-all"
                              title="Trail SL to Entry Price for a Risk-Free Trade"
                            >
                              Trail SL to Cost
                            </button>
                            <button
                              onClick={() => handleClosePosition(pos.id)}
                              className="px-2.5 py-1 text-[11px] font-bold rounded-lg bg-rose-500/10 text-rose-500 hover:bg-rose-500/20 border border-rose-500/30 transition-all"
                            >
                              Close Position
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* TAB 2: COMPLETED TRADES JOURNAL */}
          {activeTab === 'JOURNAL' && (
            <div className="space-y-2">
              {state.closedTrades.length === 0 ? (
                <div className="py-6 text-center text-xs text-[var(--text-muted)]">
                  No completed trades in the journal yet.
                </div>
              ) : (
                <div className="space-y-2">
                  {state.closedTrades.map((trade) => {
                    const isWin = trade.pnl > 0.01;
                    const isLoss = trade.pnl < -0.01;
                    const isBreakEven = !isWin && !isLoss;
                    return (
                      <div
                        key={trade.id}
                        className="p-3.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs"
                      >
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span
                              className={`text-[9px] px-1.5 py-0.5 rounded font-extrabold ${
                                isWin
                                  ? 'bg-emerald-500/15 text-emerald-500'
                                  : isLoss
                                  ? 'bg-rose-500/15 text-rose-500'
                                  : 'bg-slate-500/15 text-slate-400'
                              }`}
                            >
                              {isWin ? 'PROFIT' : isLoss ? 'LOSS' : 'BREAK-EVEN'}
                            </span>
                            <span className="font-bold text-[var(--text-primary)]">{trade.contractSymbol}</span>
                            <span className="text-[9.5px] px-1.5 py-0.2 rounded bg-white/[0.05] text-slate-400 font-mono">
                              ID: {trade.id}
                            </span>
                          </div>
                          <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
                            <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-semibold">
                              <strong>Kharida (Entry):</strong> ₹{trade.entryPremium.toFixed(2)}{' '}
                              <span className="text-[10px] text-[var(--text-muted)]">({trade.openedAt})</span>
                            </span>
                            <span className="text-[var(--text-muted)]">➔</span>
                            <span className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-600 dark:text-blue-400 font-semibold">
                              <strong>Becha (Exit):</strong> ₹{(trade.exitPremium || trade.currentPremium || 0).toFixed(2)}{' '}
                              <span className="text-[10px] text-[var(--text-muted)]">({trade.closedAt || 'Completed'})</span>
                            </span>
                          </div>
                          <div className="flex flex-wrap items-center gap-2 sm:gap-3 text-[10px] text-slate-400 font-mono pt-0.5">
                            <span>Qty: {trade.totalQuantity} ({trade.lots} Lot)</span>
                            <span>•</span>
                            <span>Gross P&L: ₹{(trade.grossPnl || trade.pnl + 149.75).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
                            <span>•</span>
                            <span>Brokerage & Charges: ₹{(trade.statutoryCosts || 149.75).toFixed(2)}</span>
                            <span>•</span>
                            <span>Slippage: ₹0.00</span>
                            <span>•</span>
                            <span className="text-amber-400 font-semibold">Exit Reason: {trade.exitReason}</span>
                          </div>
                        </div>

                        <div className="flex items-center gap-3">
                          <button
                            onClick={() => setSelectedTradeForReview(trade)}
                            className="px-2.5 py-1 text-[11px] font-bold rounded-lg bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 border border-purple-500/30 flex items-center gap-1 transition-all"
                          >
                            <Sparkles className="w-3 h-3" />
                            AI Review
                          </button>
                          <div className="text-right">
                            <span
                              className={`font-bold text-sm ${
                                isWin ? 'text-emerald-500' : isLoss ? 'text-rose-500' : 'text-slate-400'
                              }`}
                            >
                              {isWin ? '+' : ''}₹{trade.pnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                            </span>
                            <span className="text-[10px] text-[var(--text-muted)] block">
                              Net: ({trade.pnlPercent > 0 ? '+' : ''}{trade.pnlPercent.toFixed(1)}%)
                            </span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* TAB 3: WHAT AI LEARNED DASHBOARD */}
          {activeTab === 'AI_KNOWLEDGE' && (
            <WhatAiLearnedPanel onClose={() => setActiveTab('POSITIONS')} />
          )}
        </div>
      )}

      {/* AI Trade Review Modal */}
      {selectedTradeForReview && (
        <AITradeReviewModal
          position={selectedTradeForReview}
          isOpen={true}
          onClose={() => setSelectedTradeForReview(null)}
        />
      )}
    </div>
  );
};

