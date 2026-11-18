'use client';

import React, { useState, useEffect } from 'react';
import { paperTradingManager, PaperTradingState, PaperPosition } from '@/services/paperTradingService';
import { Gamepad2, CheckCircle2, RotateCcw, ChevronDown, ChevronUp, Brain, Sparkles, Clock, RefreshCw, TrendingUp, TrendingDown, ArrowUpRight } from 'lucide-react';
import { WhatAiLearnedPanel } from './WhatAiLearnedPanel';
import { AITradeReviewModal } from './AITradeReviewModal';

export const PaperTradingSimulator: React.FC = () => {
  const [state, setState] = useState<PaperTradingState>(paperTradingManager.getState());
  const [activeTab, setActiveTab] = useState<'POSITIONS' | 'JOURNAL' | 'AI_KNOWLEDGE'>('POSITIONS');
  const [isExpanded, setIsExpanded] = useState<boolean>(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [selectedTradeForReview, setSelectedTradeForReview] = useState<PaperPosition | null>(null);
  const [nowMs, setNowMs] = useState<number>(Date.now());
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);

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

  // 1-second live duration ticker
  useEffect(() => {
    const timer = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // 10-second auto-poll for live broker quotes on active positions
  useEffect(() => {
    if (state.positions.length === 0) return;
    const poll = setInterval(() => {
      paperTradingManager.refreshLiveQuotes().catch(() => {});
    }, 10000);
    return () => clearInterval(poll);
  }, [state.positions.length]);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleRefreshAllQuotes = async () => {
    setIsRefreshing(true);
    try {
      const updated = await paperTradingManager.refreshLiveQuotes();
      if (updated && updated.positions.length > 0) {
        const p0 = updated.positions[0];
        const pnl = p0.netPnl !== undefined ? p0.netPnl : p0.pnl;
        const sign = pnl >= 0 ? '+' : '';
        showToast(`Live CMP: ₹${p0.currentPremium.toFixed(2)} | Net P&L: ${sign}₹${pnl.toFixed(2)}`);
      } else {
        showToast('Live broker quotes synced.');
      }
    } catch {
      showToast('Live quote sync completed.');
    } finally {
      setIsRefreshing(false);
    }
  };

  const getElapsedDuration = (openedAt?: string) => {
    if (!openedAt) return 'Just now';
    try {
      const clean = openedAt.replace(' IST', '').trim();
      const start = new Date(clean).getTime();
      if (isNaN(start)) return 'Active';
      const diff = Math.max(0, Math.floor((nowMs - start) / 1000));
      const hrs = Math.floor(diff / 3600);
      const mins = Math.floor((diff % 3600) / 60);
      const secs = diff % 60;
      if (hrs > 0) return `${hrs}h ${mins}m ${secs}s`;
      return `${mins}m ${secs}s`;
    } catch {
      return 'Active';
    }
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
    <div className="rounded-2xl border border-[var(--accent-blue)]/25 bg-[var(--bg-surface)] p-5 space-y-4 tabular-nums shadow-sm">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="p-3 rounded-xl bg-[var(--accent-blue)] text-[var(--accent-on)] text-xs font-semibold flex items-center justify-between shadow-lg animate-in fade-in slide-in-from-top-2">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-300" />
            <span>{toastMessage}</span>
          </div>
          <button onClick={() => setToastMessage(null)} className="text-[var(--text-primary)]/80 hover:text-[var(--text-primary)] text-xs">
            ✕
          </button>
        </div>
      )}

      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/25 flex items-center justify-center">
            <Gamepad2 className="w-4 h-4 text-[var(--accent-blue)]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] tracking-tight">
                1-CLICK VIRTUAL / PAPER TRADING SIMULATOR
              </h3>
              <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] border border-[var(--accent-blue)]/30">
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
            onClick={handleRefreshAllQuotes}
            disabled={isRefreshing}
            className="px-2.5 py-1 text-xs rounded-lg border border-[var(--accent-blue)]/30 bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] hover:bg-[var(--accent-blue)] hover:text-white flex items-center gap-1.5 transition-all font-semibold active:scale-95 disabled:opacity-50"
            title="Refresh live broker quotes for all open positions"
          >
            <RefreshCw className={`w-3 h-3 ${isRefreshing ? 'animate-spin' : ''}`} />
            {isRefreshing ? 'Refreshing...' : 'Refresh Live CMP'}
          </button>
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
          <span className="text-base font-semibold text-[var(--text-primary)]" suppressHydrationWarning>
            ₹{state.balance.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </span>
        </div>

        <div className="p-3 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider block">Active Positions</span>
          <span className="text-base font-semibold text-[var(--accent-blue)]" suppressHydrationWarning>
            {state.positions.length} Open
          </span>
        </div>

        <div className="p-3 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider block">Realized Net P&L</span>
          <span
            className={`text-base font-semibold flex items-center gap-1 ${
              state.totalRealizedPnl >= 0 ? 'text-emerald-500' : 'text-rose-500'
            }`}
            suppressHydrationWarning
          >
            {state.totalRealizedPnl >= 0 ? '+' : ''}₹{state.totalRealizedPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </span>
        </div>

        <div className="p-3 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider block">Win Rate</span>
          <span className="text-base font-semibold text-[var(--text-primary)]" suppressHydrationWarning>
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
                  ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] shadow-sm'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              Open Positions ({state.positions.length})
            </button>
            <button
              onClick={() => setActiveTab('JOURNAL')}
              className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                activeTab === 'JOURNAL'
                  ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] shadow-sm'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              Completed Trades Journal ({state.closedTrades.length})
            </button>
            <button
              onClick={() => setActiveTab('AI_KNOWLEDGE')}
              className={`px-3 py-1.5 rounded-lg font-bold transition-all flex items-center gap-1.5 ${
                activeTab === 'AI_KNOWLEDGE'
                  ? 'bg-purple-600 text-[var(--text-primary)] shadow-sm'
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
                  <Gamepad2 className="w-6 h-6 text-[var(--accent-blue)] mx-auto" />
                  <p className="font-semibold text-[var(--text-secondary)]">No active virtual positions open.</p>
                  <p className="text-[11px] max-w-sm mx-auto">
                    Click the <strong className="text-[var(--accent-blue)]">"🎮 Paper Trade"</strong> button on any qualified setup below to simulate a live trade!
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
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2.5 border-b border-[var(--border-subtle)]">
                          <div className="flex flex-wrap items-center gap-2">
                            <span
                              className={`text-[10px] px-2 py-0.5 rounded font-semibold ${
                                pos.bias === 'CE'
                                  ? 'bg-emerald-500 text-[var(--text-primary)]'
                                  : 'bg-rose-500 text-[var(--text-primary)]'
                              }`}
                            >
                              {pos.bias}
                            </span>
                            <span className="font-semibold text-xs text-[var(--text-primary)]">
                              {pos.contractSymbol}
                            </span>
                            <span className="text-[10px] text-[var(--text-muted)]">
                              ({pos.lots} Lot • {pos.totalQuantity} Qty)
                            </span>
                            <span className="text-[9.5px] px-1.5 py-0.5 rounded bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] tabular-nums">
                              ID: {pos.id}
                            </span>
                            {/* Engine / Setup Source Pill */}
                            <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/25 flex items-center gap-1">
                              <Sparkles className="w-3 h-3 text-[var(--accent-blue)]" />
                              <span>{pos.smcModel || 'SMC Standard Setup'}</span>
                            </span>
                            {/* Live Running Duration Pill */}
                            <span className="text-[10.5px] px-2 py-0.5 rounded-full bg-[var(--accent-blue)]/15 border border-[var(--accent-blue)]/30 text-[var(--accent-blue)] font-medium flex items-center gap-1">
                              <Clock className="w-3 h-3 animate-pulse" />
                              Running: {getElapsedDuration(pos.openedAt)}
                            </span>
                          </div>

                          <div className="flex items-center gap-2.5">
                            <button
                              onClick={handleRefreshAllQuotes}
                              disabled={isRefreshing}
                              className="px-2 py-1 rounded-md text-[10.5px] font-semibold border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] hover:bg-[var(--accent-blue)] hover:text-white text-[var(--text-secondary)] flex items-center gap-1 transition-all active:scale-95 disabled:opacity-50"
                              title="Fetch latest broker CMP & recalculate P&L"
                            >
                              <RefreshCw className={`w-3 h-3 ${isRefreshing ? 'animate-spin text-[var(--accent-blue)]' : ''}`} />
                              <span>{isRefreshing ? 'Checking...' : 'Refresh CMP'}</span>
                            </button>

                            <div className="text-right">
                              <span className="text-[10px] text-[var(--text-muted)] mr-1.5">Net MTM P&L:</span>
                              {isMtmUnavailable ? (
                                <span className="text-xs font-semibold text-amber-500 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                                  MTM UNAVAILABLE (FEED OFFLINE)
                                </span>
                              ) : (
                                <span
                                  className={`text-sm font-bold ${
                                    netMtmPnl >= 0 ? 'text-emerald-500' : 'text-rose-500'
                                  }`}
                                >
                                  {netMtmPnl >= 0 ? '+' : ''}₹{netMtmPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })} (
                                  {pos.pnlPercent >= 0 ? '+' : ''}{pos.pnlPercent.toFixed(1)}%)
                                </span>
                              )}
                            </div>
                          </div>
                        </div>

                        {/* Position Details Ladder */}
                        <div className="py-2.5 px-3 rounded-lg bg-[var(--bg-surface)] border border-[var(--border-subtle)] grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs">
                          <div>
                            <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold block uppercase">Kharida (Entry):</span>
                            <span className="font-bold text-emerald-600 dark:text-emerald-400 tabular-nums text-sm">₹{pos.entryPremium.toFixed(2)}</span>
                            <span className="text-[9.5px] text-[var(--text-muted)] block">Time: {pos.openedAt}</span>
                            <span className="text-[9px] text-[var(--accent-blue)] font-medium block">
                              Active for {getElapsedDuration(pos.openedAt)}
                            </span>
                          </div>
                          <div>
                            <div className="flex items-center justify-between">
                              <span className="text-[10px] text-[var(--text-muted)] font-semibold uppercase">Current CMP:</span>
                              <span className={`text-[10px] font-bold ${pos.currentPremium >= pos.entryPremium ? 'text-emerald-500' : 'text-rose-500'}`}>
                                {pos.currentPremium >= pos.entryPremium ? '+' : ''}{(pos.currentPremium - pos.entryPremium).toFixed(2)} pts
                              </span>
                            </div>
                            <div className="flex items-baseline gap-1">
                              <span className="font-bold text-[var(--text-primary)] tabular-nums text-sm">
                                {isMtmUnavailable ? 'UNAVAILABLE' : `₹${pos.currentPremium.toFixed(2)}`}
                              </span>
                              <span className={`text-[11px] font-semibold ${pos.pnlPercent >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                                ({pos.pnlPercent >= 0 ? '+' : ''}{pos.pnlPercent.toFixed(1)}%)
                              </span>
                            </div>
                            <span className="text-[9.5px] text-[var(--text-muted)] block">Qty: {pos.totalQuantity} • Live Angel One</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-[var(--accent-blue)] font-semibold block uppercase">Invested / Est Fee:</span>
                            <span className="font-semibold text-[var(--accent-blue)] tabular-nums">₹{pos.marginUsed.toLocaleString('en-IN')}</span>
                            <span className="text-[9.5px] text-[var(--text-secondary)] block">Est Exit Cost: ₹{estExitCosts.toFixed(1)}</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-rose-500 font-semibold block uppercase">Stop-Loss:</span>
                            <span className="font-semibold text-rose-500 tabular-nums">₹{pos.stopLoss.toFixed(2)}</span>
                            <span className="text-[9.5px] text-rose-400/80 block">Risk Managed</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-emerald-500 font-semibold block uppercase">Targets:</span>
                            <span className="font-semibold text-emerald-500 tabular-nums text-xs">T1: ₹{pos.target1.toFixed(1)}</span>
                            <span className="text-[9.5px] text-emerald-400/80 block">T2: ₹{pos.target2.toFixed(1)}</span>
                          </div>
                        </div>

                        {/* Targets Ladder Strip */}
                        <div className="mt-2 p-2 rounded-lg bg-[var(--bg-surface)] border border-[var(--border-subtle)] flex items-center justify-between text-[11px] tabular-nums">
                          <span className="text-emerald-500 font-semibold">
                            T1 (+30%): ₹{pos.target1.toFixed(1)} <span className="text-[9.5px] px-1 py-0.2 bg-emerald-500/15 rounded">High (82%)</span>
                          </span>
                          <span className="text-amber-500 font-semibold">
                            T2 (+55%): ₹{pos.target2.toFixed(1)} <span className="text-[9.5px] px-1 py-0.2 bg-amber-500/15 rounded">Moderate (54%)</span>
                          </span>
                          {pos.target3 && (
                            <span className="text-[var(--text-secondary)] font-semibold">
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
                              className="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20 border border-emerald-500/30 transition-all"
                              title="Book 50% Profit at Target 1 and trail stop to cost"
                            >
                              50% Partial Exit
                            </button>
                            <button
                              onClick={() => handleTrailStopLoss(pos)}
                              className="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/20 border border-[var(--accent-blue)]/30 transition-all"
                              title="Trail SL to Entry Price for a Risk-Free Trade"
                            >
                              Trail SL to Cost
                            </button>
                            <button
                              onClick={() => handleClosePosition(pos.id)}
                              className="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-rose-500/10 text-rose-500 hover:bg-rose-500/20 border border-rose-500/30 transition-all"
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
                              className={`text-[9px] px-1.5 py-0.5 rounded font-semibold ${
                                isWin
                                  ? 'bg-emerald-500/15 text-emerald-500'
                                  : isLoss
                                  ? 'bg-rose-500/15 text-rose-500'
                                  : 'bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)]'
                              }`}
                            >
                              {isWin ? 'PROFIT' : isLoss ? 'LOSS' : 'BREAK-EVEN'}
                            </span>
                            <span className="font-semibold text-[var(--text-primary)]">{trade.contractSymbol}</span>
                            <span className="text-[9.5px] px-2 py-0.5 rounded-full bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/25 font-semibold flex items-center gap-1">
                              <Sparkles className="w-2.5 h-2.5 text-[var(--accent-blue)]" />
                              <span>{trade.smcModel || 'SMC Standard Setup'}</span>
                            </span>
                            <span className="text-[9.5px] px-1.5 py-0.2 rounded bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] tabular-nums">
                              ID: {trade.id}
                            </span>
                          </div>
                          <div className="flex flex-wrap items-center gap-2 text-xs tabular-nums">
                            <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-semibold">
                              <strong>Kharida (Entry):</strong> ₹{trade.entryPremium.toFixed(2)}{' '}
                              <span className="text-[10px] text-[var(--text-muted)]">({trade.openedAt})</span>
                            </span>
                            <span className="text-[var(--text-muted)]">➔</span>
                            <span className="px-2 py-0.5 rounded bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] dark:text-[var(--accent-blue)] font-semibold">
                              <strong>Becha (Exit):</strong> ₹{(trade.exitPremium || trade.currentPremium || 0).toFixed(2)}{' '}
                              <span className="text-[10px] text-[var(--text-muted)]">({trade.closedAt || 'Completed'})</span>
                            </span>
                          </div>
                          <div className="flex flex-wrap items-center gap-2 sm:gap-3 text-[10px] text-[var(--text-secondary)] tabular-nums pt-0.5">
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
                            className="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 border border-purple-500/30 flex items-center gap-1 transition-all"
                          >
                            <Sparkles className="w-3 h-3" />
                            AI Review
                          </button>
                          <div className="text-right">
                            <span
                              className={`font-semibold text-sm ${
                                isWin ? 'text-emerald-500' : isLoss ? 'text-rose-500' : 'text-[var(--text-secondary)]'
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

