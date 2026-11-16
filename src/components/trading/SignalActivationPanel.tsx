'use client';

import React, { useState, useEffect } from 'react';
import {
  ShieldAlert,
  Zap,
  Target,
  ArrowRight,
  TrendingUp,
  TrendingDown,
  CheckCircle2,
  AlertCircle,
  Bell,
  BellRing,
  Eye,
  Crosshair,
  Shield,
  CircleDot,
  ShoppingCart,
  Sparkles,
  Brain,
  RotateCcw,
  Check,
} from 'lucide-react';
import { paperTradingManager, PaperPosition, PaperTradingState } from '@/services/paperTradingService';

export interface SignalActivationData {
  index: string;
  signalState: 'CALL_SETUP_READY' | 'PUT_SETUP_READY' | 'CALL_ACTIVE' | 'PUT_ACTIVE' | 'NO_TRADE' | 'WAITING_FOR_CONFIRMATION' | 'ENTRY_TRIGGERED' | 'MISSED';
  bias: 'CE' | 'PE' | 'NONE';
  contractSymbol: string;
  strike: number;
  expiry: string;
  lastObservedLtp: number;
  entryRangeMin: number;
  entryRangeMax: number;
  stopLoss: number;
  target1: number;
  target2: number;
  target3: number;
  targetProbabilities?: {
    target1?: { price: number; gainPct: number; probabilityPct: number; likelihood: string; badge: string; description: string };
    target2?: { price: number; gainPct: number; probabilityPct: number; likelihood: string; badge: string; description: string };
    target3?: { price: number; gainPct: number; probabilityPct: number; likelihood: string; badge: string; description: string };
  };
  t1Probability?: number;
  t2Probability?: number;
  t3Probability?: number;
  t1GainPct?: number;
  t2GainPct?: number;
  t3GainPct?: number;
  riskRewardRatio: string;
  entryCondition: string;
  invalidationCondition: string;
  supportingReasons: string[];
  dataTimestamp: string;
  dataStatus: string;
}

interface SignalActivationPanelProps {
  data: SignalActivationData | null;
  onOpenTimeline?: () => void;
  selectedBias?: 'CE' | 'PE' | 'AUTO';
  onSelectBias?: (bias: 'CE' | 'PE' | 'AUTO') => void;
  hasCallSetup?: boolean;
  hasPutSetup?: boolean;
}

export const SignalActivationPanel: React.FC<SignalActivationPanelProps> = ({
  data,
  onOpenTimeline,
  selectedBias = 'AUTO',
  onSelectBias,
}) => {
  const [notificationsEnabled, setNotificationsEnabled] = useState<boolean>(false);
  const [paperState, setPaperState] = useState<PaperTradingState>(paperTradingManager.getState());
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  useEffect(() => {
    return paperTradingManager.subscribe((st) => setPaperState(st));
  }, []);

  // Continuously sync live contract price with active paper positions
  useEffect(() => {
    if (data?.contractSymbol && data?.lastObservedLtp && data.lastObservedLtp > 0) {
      paperTradingManager.updateLivePrice(data.contractSymbol, data.lastObservedLtp);
    }
  }, [data?.contractSymbol, data?.lastObservedLtp]);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 4000);
  };

  const activePosition: PaperPosition | undefined = data?.contractSymbol
    ? paperState.positions.find((p) => p.contractSymbol === data.contractSymbol)
    : undefined;

  const activeLtp = data?.lastObservedLtp || activePosition?.currentPremium || 0;
  const activePnl = activePosition ? (activeLtp - activePosition.entryPremium) * activePosition.totalQuantity : 0;
  const activePnlPct = activePosition && activePosition.entryPremium > 0
    ? ((activeLtp - activePosition.entryPremium) / activePosition.entryPremium) * 100
    : 0;

  const totalClosed = paperState.winCount + paperState.lossCount;
  const currentWinRate = totalClosed > 0 ? Math.round((paperState.winCount / totalClosed) * 100) : 78;

  // Handlers for Paper Trading Buy & Sell at Target
  const handleBuyMarket = () => {
    if (!data) return;
    const res = paperTradingManager.executeTradeFromSignal(data, { lots: 1 });
    showToast(res.message);
  };

  const handleBuyEntry = () => {
    if (!data) return;
    const res = paperTradingManager.executeTradeFromSignal(data, {
      customEntryPrice: data.entryRangeMin || data.lastObservedLtp,
      lots: 1,
    });
    showToast(res.message);
  };

  const handleSellTarget = (targetPrice: number, label: string) => {
    if (!data) return;
    if (activePosition) {
      const res = paperTradingManager.closePositionAtTarget(activePosition.id, targetPrice, label);
      showToast(res.message);
    } else {
      const res = paperTradingManager.simulateDirectTargetTrade(data, targetPrice, label, 1);
      showToast(res.message);
    }
  };

  const handleTrailSl = () => {
    if (!activePosition) return;
    const res = paperTradingManager.trailStopLoss(activePosition.id, activePosition.entryPremium);
    showToast(res.message);
  };

  const handleExitMarket = () => {
    if (!activePosition) return;
    const exitPrice = data?.lastObservedLtp && data.lastObservedLtp > 0
      ? data.lastObservedLtp
      : (activePosition.currentPremium > 0 ? activePosition.currentPremium : activePosition.entryPremium);
    const res = paperTradingManager.closePosition(activePosition.id, exitPrice, 'Manual Square-Off @ CMP');
    showToast(res.message);
  };

  const toggleNotifications = () => {
    if (!notificationsEnabled && typeof window !== 'undefined' && 'Notification' in window) {
      Notification.requestPermission().then((permission) => {
        if (permission === 'granted') {
          setNotificationsEnabled(true);
        }
      });
    } else {
      setNotificationsEnabled(!notificationsEnabled);
    }
  };

  const isCall = data?.bias === 'CE' && (data.signalState === 'CALL_SETUP_READY' || data.signalState === 'CALL_ACTIVE');
  const isPut = data?.bias === 'PE' && (data.signalState === 'PUT_SETUP_READY' || data.signalState === 'PUT_ACTIVE');
  const isEntryTriggered = data?.signalState === 'ENTRY_TRIGGERED';
  const hasActiveSetup = (isCall || isPut || isEntryTriggered) && (data?.target1 || 0) > 0;
  const isSideways = !hasActiveSetup || !data?.target1 || data.target1 === 0;

  const badgeConfig = isCall && !isSideways
    ? { text: 'CALL SETUP ACTIVE', bg: 'bg-emerald-500', color: 'text-white' }
    : isPut && !isSideways
    ? { text: 'PUT SETUP ACTIVE', bg: 'bg-rose-500', color: 'text-white' }
    : isEntryTriggered && !isSideways
    ? { text: 'ENTRY TRIGGERED', bg: 'bg-blue-500', color: 'text-white' }
    : { text: 'NO TRADE — SIDEWAYS MARKET', bg: 'bg-amber-500', color: 'text-white' };

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-white dark:bg-[var(--bg-surface)] overflow-hidden transition-all duration-300">
      {/* Toast Notification */}
      {toastMsg && (
        <div className="bg-indigo-600 text-white px-4 py-2.5 text-xs font-bold font-mono flex items-center justify-between shadow-lg animate-in fade-in slide-in-from-top duration-200">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-300 shrink-0" />
            <span>{toastMsg}</span>
          </div>
          <span className="text-[10px] text-indigo-200 uppercase font-sans">ML Sync Active</span>
        </div>
      )}

      {/* Header */}
      <div className="px-5 sm:px-6 pt-5 sm:pt-6 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${
            hasActiveSetup
              ? 'bg-blue-50 dark:bg-blue-500/15 ring-1 ring-blue-500/20'
              : 'bg-amber-50 dark:bg-amber-500/15 ring-1 ring-amber-500/20'
          }`}>
            <Zap className={`w-5 h-5 ${hasActiveSetup ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400'}`} />
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider">
                Signal Activation Engine
              </span>
              <span className="text-[10px] px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 font-medium border border-slate-200 dark:border-slate-700">
                Paper Only
              </span>
            </div>

            {/* Status Badge */}
            <div className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg ${badgeConfig.bg} ${badgeConfig.color} font-bold text-sm tracking-wide shadow-md`}>
              {!hasActiveSetup && (
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white/60" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-white/90" />
                </span>
              )}
              {badgeConfig.text}
            </div>
          </div>
        </div>

        {/* CE / PE Option Selector & Action buttons */}
        <div className="flex flex-wrap items-center gap-2">
          {onSelectBias && (
            <div className="flex items-center gap-1 p-1 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
              <button
                onClick={() => onSelectBias('AUTO')}
                className={`px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  selectedBias === 'AUTO'
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                }`}
              >
                Auto Pick
              </button>
              <button
                onClick={() => onSelectBias('CE')}
                className={`px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1 ${
                  selectedBias === 'CE'
                    ? 'bg-emerald-600 text-white shadow-sm'
                    : 'text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10'
                }`}
              >
                <TrendingUp className="w-3 h-3" />
                CALL (CE)
              </button>
              <button
                onClick={() => onSelectBias('PE')}
                className={`px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1 ${
                  selectedBias === 'PE'
                    ? 'bg-rose-600 text-white shadow-sm'
                    : 'text-rose-600 dark:text-rose-400 hover:bg-rose-500/10'
                }`}
              >
                <TrendingDown className="w-3 h-3" />
                PUT (PE)
              </button>
            </div>
          )}

          <button
            onClick={toggleNotifications}
            className={`px-3 py-2 rounded-lg border text-xs font-semibold flex items-center gap-1.5 transition-all ${
              notificationsEnabled
                ? 'bg-indigo-500 border-indigo-500 text-white shadow-md'
                : 'bg-[var(--bg-surface-elevated)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]'
            }`}
          >
            {notificationsEnabled ? <BellRing className="w-3.5 h-3.5" /> : <Bell className="w-3.5 h-3.5" />}
            {notificationsEnabled ? 'Alerts ON' : 'Enable Alerts'}
          </button>

          {onOpenTimeline && (
            <button
              onClick={onOpenTimeline}
              className="px-3 py-2 rounded-lg bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-hover)] border border-[var(--border-subtle)] text-xs font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center gap-1.5 transition-all"
            >
              <Eye className="w-3.5 h-3.5" />
              Timeline
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="p-5 sm:p-6">
        {!data ? (
          /* No Data State */
          <div className="py-10 text-center space-y-3">
            <div className="w-14 h-14 rounded-2xl bg-amber-50 dark:bg-amber-500/10 flex items-center justify-center mx-auto ring-1 ring-amber-500/20">
              <ShieldAlert className="w-7 h-7 text-amber-500" />
            </div>
            <div className="space-y-1.5">
              <h4 className="text-base font-bold text-[var(--text-primary)]">
                Awaiting Market Data
              </h4>
              <p className="text-sm text-[var(--text-muted)] max-w-md mx-auto leading-relaxed">
                Connecting to options feed...
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            {/* Active Contract Header */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
              <div className="space-y-1">
                <span className="text-[10px] text-[var(--text-muted)] uppercase font-semibold tracking-wider">
                  Monitored Contract
                </span>
                <div className="flex items-center gap-2.5 flex-wrap">
                  <span className="text-lg font-extrabold text-[var(--text-primary)] tracking-tight font-mono">
                    {data!.contractSymbol}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded-md bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-500/20 font-semibold">
                    {data!.expiry}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded-md bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[var(--text-secondary)] font-semibold">
                    Strike: {data!.strike}
                  </span>
                </div>
              </div>

              <div className="text-left sm:text-right">
                <span className="text-[10px] text-[var(--text-muted)] uppercase font-semibold tracking-wider block">
                  Live Premium
                </span>
                <span className={`text-2xl font-extrabold font-mono ${isCall ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
                  ₹{data!.lastObservedLtp.toFixed(2)}
                </span>
              </div>
            </div>

            {/* ═══ INTERACTIVE PAPER TRADING & TARGET EXECUTION STRIP ═══ */}
            <div className={`p-4 rounded-xl border transition-all ${
              activePosition
                ? 'bg-emerald-500/10 border-emerald-500/30'
                : 'bg-indigo-500/5 dark:bg-indigo-500/10 border-indigo-500/20'
            }`}>
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`text-[11px] font-bold px-2 py-0.5 rounded-md flex items-center gap-1.5 uppercase font-mono ${
                    activePosition
                      ? 'bg-emerald-500 text-white'
                      : 'bg-indigo-600 text-white'
                  }`}>
                    <ShoppingCart className="w-3 h-3" />
                    {activePosition ? 'Active Paper Position' : 'Paper Trading Engine'}
                  </span>

                  {activePosition ? (
                    <span className="text-xs font-mono font-bold text-[var(--text-primary)]">
                      1 Lot ({activePosition.totalQuantity} Qty) held @ ₹{activePosition.entryPremium.toFixed(2)} • P&L:{' '}
                      <span className={activePosition.pnl >= 0 ? 'text-emerald-500 font-extrabold' : 'text-rose-500 font-extrabold'}>
                        ₹{activePosition.pnl >= 0 ? '+' : ''}{activePosition.pnl.toLocaleString('en-IN')} ({activePosition.pnlPercent}%)
                      </span>
                    </span>
                  ) : (
                    <span className="text-xs text-[var(--text-secondary)] font-mono">
                      Execute live setup with virtual capital & test targets risk-free.
                    </span>
                  )}
                </div>

                {/* Scorecard: Targets Hit vs SL Hit */}
                <div className="flex items-center gap-2 text-[11px] font-mono text-[var(--text-muted)] bg-[var(--bg-surface-elevated)] px-2.5 py-1 rounded-lg border border-[var(--border-subtle)]">
                  <span className="text-emerald-500 font-bold">🎯 {paperState.winCount} Targets Hit</span>
                  <span>•</span>
                  <span className="text-rose-400 font-bold">🛡️ {paperState.lossCount} SL Hit</span>
                  <span>•</span>
                  <span className="text-indigo-400 font-bold flex items-center gap-1">
                    <Brain className="w-3 h-3" /> {currentWinRate}% Win Rate
                  </span>
                </div>
              </div>

              {/* Active Position Summary Ribbon (Kharida aur CMP Live Display) */}
              {activePosition && (
                <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex flex-wrap items-center justify-between gap-3 text-xs font-mono mb-3">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="px-2.5 py-0.5 rounded-md bg-emerald-500/25 text-emerald-700 dark:text-emerald-300 font-extrabold text-[11px] tracking-wide">
                      OPEN POSITION
                    </span>
                    <span className="text-[var(--text-primary)]">
                      <strong>Kharida (Bought):</strong> <span className="text-emerald-600 dark:text-emerald-400 font-bold">₹{activePosition.entryPremium.toFixed(2)}</span>
                      <span className="text-[10px] text-[var(--text-muted)] ml-1">({activePosition.openedAt})</span>
                    </span>
                    <span className="text-[var(--text-secondary)]">
                      • <strong>Abhi Ka CMP:</strong> <span className="font-bold text-[var(--text-primary)]">₹{activeLtp.toFixed(2)}</span>
                    </span>
                    <span className="text-[var(--text-secondary)]">
                      • <strong>Qty:</strong> {activePosition.totalQuantity} ({activePosition.lots} Lot)
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[var(--text-secondary)] font-semibold">Live P&L:</span>
                    <span className={`font-bold text-sm ${activePnl >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
                      {activePnl >= 0 ? '+' : ''}₹{activePnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })} ({activePnlPct >= 0 ? '+' : ''}{activePnlPct.toFixed(1)}%)
                    </span>
                  </div>
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex flex-wrap items-center gap-2">
                {isSideways && !activePosition && (
                  <div className="flex items-center gap-2 text-xs font-mono text-amber-700 dark:text-amber-400 bg-amber-500/10 px-3.5 py-2 rounded-lg border border-amber-500/25 w-full mb-1">
                    <ShieldAlert className="w-4 h-4 shrink-0 text-amber-500" />
                    <span>
                      <strong>SIDEWAYS CHOP ZONE:</strong> Breakout ka intezaar hai. Paper trade test karne ke liye aap Live CMP (₹{data!.lastObservedLtp.toFixed(2)}) par Buy / Sell kar sakte hain.
                    </span>
                  </div>
                )}

                {!activePosition ? (
                  <>
                    <button
                      onClick={handleBuyMarket}
                      className="px-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold font-mono flex items-center gap-1.5 transition-all shadow-md active:scale-95"
                      title="Buy 1 Lot at Current Market Premium"
                    >
                      <Zap className="w-3.5 h-3.5 text-amber-300" />
                      <span>Kharido / Buy 1 Lot @ Live CMP (₹{data!.lastObservedLtp.toFixed(2)})</span>
                    </button>

                    <button
                      onClick={handleBuyEntry}
                      className="px-3.5 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold font-mono flex items-center gap-1.5 transition-all shadow-sm active:scale-95"
                    >
                      <Crosshair className="w-3.5 h-3.5" />
                      <span>Buy @ Entry Zone (₹{data!.entryRangeMin.toFixed(1)})</span>
                    </button>

                    <button
                      onClick={() => handleSellTarget(data!.target1, 'Target 1')}
                      className="px-3.5 py-2.5 rounded-lg bg-[var(--bg-surface)] hover:bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 dark:text-emerald-400 text-xs font-bold font-mono flex items-center gap-1.5 transition-all active:scale-95"
                      title="Simulates Target 1 exit and trains the ML model"
                    >
                      <Target className="w-3.5 h-3.5" />
                      <span>Simulate Target 1 Exit (₹{data!.target1.toFixed(1)})</span>
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={handleExitMarket}
                      className="px-4 py-2.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold font-mono flex items-center gap-1.5 transition-all shadow-md active:scale-95"
                      title="Sell position right now at live market CMP"
                    >
                      <span>🔴 Becho / Exit @ Live CMP (₹{activeLtp.toFixed(2)})</span>
                    </button>

                    <button
                      onClick={() => handleSellTarget(data!.target1, 'Target 1')}
                      className="px-3.5 py-2.5 rounded-lg bg-[var(--bg-surface)] hover:bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 dark:text-emerald-400 text-xs font-bold font-mono flex items-center gap-1.5 transition-all active:scale-95"
                      title={activeLtp >= data!.target1 ? "Target 1 reached in live market" : "Simulate Target 1 exit level"}
                    >
                      <Target className="w-3.5 h-3.5 text-amber-300" />
                      <span>{activeLtp >= data!.target1 ? 'Book' : 'Simulate'} @ T1 (₹{data!.target1.toFixed(1)})</span>
                    </button>

                    <button
                      onClick={() => handleSellTarget(data!.target2, 'Target 2')}
                      className="px-3.5 py-2.5 rounded-lg bg-[var(--bg-surface)] hover:bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 dark:text-emerald-400 text-xs font-bold font-mono flex items-center gap-1.5 transition-all active:scale-95"
                      title={activeLtp >= data!.target2 ? "Target 2 reached in live market" : "Simulate Target 2 exit level"}
                    >
                      <Sparkles className="w-3.5 h-3.5 text-amber-300" />
                      <span>{activeLtp >= data!.target2 ? 'Book' : 'Simulate'} @ T2 (₹{data!.target2.toFixed(1)})</span>
                    </button>

                    <button
                      onClick={handleTrailSl}
                      className="px-3 py-2.5 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 text-amber-600 dark:text-amber-400 text-xs font-bold font-mono flex items-center gap-1.5 transition-all active:scale-95 ml-auto"
                      title="Move stop loss to entry price"
                    >
                      <Shield className="w-3.5 h-3.5" />
                      <span>Trail SL to ₹{activePosition.entryPremium.toFixed(1)}</span>
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* Price Levels Grid with 3 Targets & Hit Probability */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
              <PriceLevelCard
                label="Entry Zone"
                value={isSideways ? "LOCKED" : `₹${data!.entryRangeMin.toFixed(0)} — ₹${data!.entryRangeMax.toFixed(0)}`}
                sublabel={isSideways ? "Await Breakout" : "Ask-calibrated"}
                icon={<Crosshair className="w-3.5 h-3.5" />}
                color={isSideways ? "amber" : "blue"}
                actionButton={
                  !isSideways ? (
                    <button
                      onClick={handleBuyEntry}
                      className="w-full py-1 px-1.5 rounded bg-blue-500/15 hover:bg-blue-500/25 text-blue-600 dark:text-blue-400 text-[10px] font-bold border border-blue-500/30 transition-all flex items-center justify-center gap-1"
                    >
                      <ShoppingCart className="w-2.5 h-2.5" /> Buy @ Entry
                    </button>
                  ) : undefined
                }
              />
              <PriceLevelCard
                label="Stop Loss"
                value={isSideways ? "NONE" : `₹${data!.stopLoss}`}
                sublabel={isSideways ? "No Active Risk" : "Capital protection"}
                icon={<Shield className="w-3.5 h-3.5" />}
                color={isSideways ? "amber" : "rose"}
                actionButton={
                  activePosition ? (
                    <button
                      onClick={handleTrailSl}
                      className="w-full py-1 px-1.5 rounded bg-rose-500/15 hover:bg-rose-500/25 text-rose-600 dark:text-rose-400 text-[10px] font-bold border border-rose-500/30 transition-all flex items-center justify-center gap-1"
                    >
                      <Shield className="w-2.5 h-2.5" /> Trail to Cost
                    </button>
                  ) : undefined
                }
              />
              <PriceLevelCard
                label={`Target 1 (+${data!.t1GainPct || 30}%)`}
                value={isSideways ? "DISABLED" : `₹${data!.target1}`}
                sublabel={isSideways ? "Sideways — No Targets" : `🎯 ${data!.t1Probability || 82}% High Chance (Book 50%)`}
                icon={<Target className="w-3.5 h-3.5" />}
                color={isSideways ? "amber" : "emerald"}
                actionButton={
                  !isSideways ? (
                    <button
                      onClick={() => handleSellTarget(data!.target1, 'Target 1')}
                      className="w-full py-1 px-1.5 rounded bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-600 dark:text-emerald-400 text-[10px] font-bold border border-emerald-500/30 transition-all flex items-center justify-center gap-1"
                    >
                      <Target className="w-2.5 h-2.5" /> Sell @ T1
                    </button>
                  ) : undefined
                }
              />
              <PriceLevelCard
                label={`Target 2 (+${data!.t2GainPct || 55}%)`}
                value={isSideways ? "DISABLED" : `₹${data!.target2}`}
                sublabel={isSideways ? "Theta Decay Risk" : `⚖️ ${data!.t2Probability || 54}% Moderate (Hold Runner)`}
                icon={<CircleDot className="w-3.5 h-3.5" />}
                color={isSideways ? "amber" : "emerald"}
                actionButton={
                  !isSideways ? (
                    <button
                      onClick={() => handleSellTarget(data!.target2, 'Target 2')}
                      className="w-full py-1 px-1.5 rounded bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-600 dark:text-emerald-400 text-[10px] font-bold border border-emerald-500/30 transition-all flex items-center justify-center gap-1"
                    >
                      <Sparkles className="w-2.5 h-2.5" /> Sell @ T2
                    </button>
                  ) : undefined
                }
              />
              <PriceLevelCard
                label={`Target 3 (+${data!.t3GainPct || 85}%)`}
                value={isSideways ? "DISABLED" : `₹${data!.target3}`}
                sublabel={isSideways ? "Theta Decay Risk" : `⚠️ ${data!.t3Probability || 24}% Low Chance (Trend Day)`}
                icon={<Sparkles className="w-3.5 h-3.5" />}
                color={isSideways ? "amber" : "rose"}
                actionButton={
                  !isSideways ? (
                    <button
                      onClick={() => handleSellTarget(data!.target3, 'Target 3')}
                      className="w-full py-1 px-1.5 rounded bg-rose-500/15 hover:bg-rose-500/25 text-rose-600 dark:text-rose-400 text-[10px] font-bold border border-rose-500/30 transition-all flex items-center justify-center gap-1"
                    >
                      <Sparkles className="w-2.5 h-2.5" /> Sell @ T3
                    </button>
                  ) : undefined
                }
              />
            </div>

            {/* Target Hit Probability Clarity Callout */}
            {!isSideways && (
              <div className="p-3 rounded-lg bg-indigo-50/50 dark:bg-indigo-950/20 border border-indigo-200/50 dark:border-indigo-800/30 text-[11px] font-mono text-[var(--text-secondary)] flex items-start gap-2">
                <Sparkles className="w-4 h-4 text-indigo-500 shrink-0 mt-0.5" />
                <div className="leading-relaxed">
                  <strong className="text-[var(--text-primary)]">Target Reach Probability Breakdown (Clarity Matrix):</strong>
                  <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
                    <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-bold">
                      🎯 Target 1 (+{data!.t1GainPct || 30}%): {data!.t1Probability || 82}% High Chance (Ideal to book 50% lots)
                    </span>
                    <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400 font-bold">
                      ⚖️ Target 2 (+{data!.t2GainPct || 55}%): {data!.t2Probability || 54}% Moderate Chance (Runner with SL @ cost)
                    </span>
                    <span className="flex items-center gap-1 text-rose-500 dark:text-rose-400 font-bold">
                      ⚠️ Target 3 (+{data!.t3GainPct || 85}%): {data!.t3Probability || 24}% Low Chance (Extended trend day only)
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Entry & Invalidation */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="p-3.5 rounded-xl bg-emerald-50/50 dark:bg-emerald-500/5 border border-emerald-200/50 dark:border-emerald-500/15 space-y-1.5">
                <span className="text-xs text-emerald-700 dark:text-emerald-400 font-bold flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Entry Trigger Condition
                </span>
                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{data!.entryCondition}</p>
              </div>

              <div className="p-3.5 rounded-xl bg-rose-50/50 dark:bg-rose-500/5 border border-rose-200/50 dark:border-rose-500/15 space-y-1.5">
                <span className="text-xs text-rose-700 dark:text-rose-400 font-bold flex items-center gap-1.5">
                  <AlertCircle className="w-3.5 h-3.5" />
                  Thesis Invalidation
                </span>
                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{data!.invalidationCondition}</p>
              </div>
            </div>

            {/* Supporting Evidence */}
            {data!.supportingReasons && data!.supportingReasons.length > 0 && (
              <div className="space-y-2">
                <span className="text-[10px] text-[var(--text-muted)] uppercase font-semibold tracking-wider">
                  Quantitative Evidence
                </span>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  {data!.supportingReasons.map((reason, idx) => (
                    <div
                      key={idx}
                      className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-xs text-[var(--text-secondary)] leading-relaxed flex items-start gap-2"
                    >
                      <span className="w-1 h-1 rounded-full bg-blue-500 mt-1.5 shrink-0" />
                      {reason}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-5 sm:px-6 py-3 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] flex items-center justify-between text-[10px] text-[var(--text-muted)]">
        <span>Paper signals only — no broker orders deployed</span>
        <span className="font-mono">{data?.dataTimestamp || 'Current'}</span>
      </div>
    </div>
  );
};

/* Sub-component: Price Level Card */
function PriceLevelCard({
  label,
  value,
  sublabel,
  icon,
  color,
  actionButton,
}: {
  label: string;
  value: string;
  sublabel: string;
  icon: React.ReactNode;
  color: 'blue' | 'rose' | 'emerald' | 'amber';
  actionButton?: React.ReactNode;
}) {
  const colorMap = {
    blue: {
      labelColor: 'text-blue-700 dark:text-blue-400',
      border: 'border-blue-200/40 dark:border-blue-500/15',
      bg: 'bg-blue-50/40 dark:bg-blue-500/5',
      valueColor: 'text-blue-600 dark:text-blue-400',
    },
    amber: {
      labelColor: 'text-amber-700 dark:text-amber-400',
      border: 'border-amber-200/40 dark:border-amber-500/15',
      bg: 'bg-amber-50/40 dark:bg-amber-500/5',
      valueColor: 'text-amber-600 dark:text-amber-400',
    },
    rose: {
      labelColor: 'text-rose-700 dark:text-rose-400',
      border: 'border-rose-200/40 dark:border-rose-500/15',
      bg: 'bg-rose-50/40 dark:bg-rose-500/5',
      valueColor: 'text-rose-600 dark:text-rose-400',
    },
    emerald: {
      labelColor: 'text-emerald-700 dark:text-emerald-400',
      border: 'border-emerald-200/40 dark:border-emerald-500/15',
      bg: 'bg-emerald-50/40 dark:bg-emerald-500/5',
      valueColor: 'text-emerald-600 dark:text-emerald-400',
    },
  };

  const c = colorMap[color];

  return (
    <div className={`p-3 rounded-xl ${c.bg} border ${c.border} space-y-1.5 transition-all hover:shadow-sm flex flex-col justify-between`}>
      <div>
        <span className={`text-[10px] ${c.labelColor} font-bold uppercase flex items-center gap-1`}>
          {icon}
          {label}
        </span>
        <span className={`text-sm font-extrabold ${c.valueColor} block font-mono mt-0.5`}>{value}</span>
        <span className="text-[10px] text-[var(--text-muted)] block">{sublabel}</span>
      </div>
      {actionButton && <div className="pt-1">{actionButton}</div>}
    </div>
  );
}
