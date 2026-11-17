'use client';

import { OptionTradeSetup } from '@/types/options';

export interface PartialExitRecord {
  exitLots: number;
  exitPrice: number;
  exitTimestamp: string;
  exitLabel: string;
  grossPnl: number;
  netPnl: number;
  statutoryDeductions: number;
}

export interface CostBreakdown {
  brokerage: number;
  stt: number;
  exchangeCharges: number;
  gst: number;
  sebiTurnoverCharges: number;
  stampDuty: number;
  slippageCost: number;
  totalStatutoryCosts: number;
  grossPnl: number;
  netPnl: number;
  grossTurnover: number;
}

export interface EvaluationItem {
  passed: boolean;
  explanation: string;
}

export interface AITradeEvaluation {
  tradeId: string;
  contractSymbol: string;
  grade: 'A+' | 'A' | 'B' | 'C' | 'D' | 'F';
  score: number;
  directionCorrect: EvaluationItem;
  entryCorrect: EvaluationItem;
  ictSmcConfirmation: EvaluationItem;
  liquidityCorrect: EvaluationItem;
  fvgValid: EvaluationItem;
  stopLossReasonable: EvaluationItem;
  targetRealistic: EvaluationItem;
  marketConditionSuitable: EvaluationItem;
  thetaIvSpreadImpact: EvaluationItem & { totalFriction?: number };
  keyTakeaway: string;
  actionableImprovements: string[];
}

export interface WhatAiLearnedData {
  totalTradesTrained: number;
  lastTrainedIst: string;
  models: {
    xgboost: {
      accuracyPct: number;
      rocAuc: number;
      featureImportance: Record<string, number>;
      status: string;
    };
    neuralNetwork: {
      accuracyPct: number;
      hiddenLayers: string;
      iterations: number;
      status: string;
    };
  };
  bestPerformingSetups: Array<{
    setup: string;
    sampleCount: number;
    winRatePct: number;
    avgReturnPct: number;
    profitFactor: number;
    keyInsight: string;
  }>;
  worstPerformingSetups: Array<{
    setup: string;
    sampleCount: number;
    winRatePct: number;
    avgReturnPct: number;
    lossDriver: string;
  }>;
  commonTradingMistakes: string[];
  poorMarketConditions: string[];
  successfulIctCombinations: string[];
}

export interface PaperPosition {
  id: string;
  symbol: string;               // e.g. "NIFTY 50", "RELIANCE"
  contractSymbol: string;       // e.g. "NIFTY03NOV2623800CE"
  bias: 'CE' | 'PE';
  strike: number;
  expiry: string;
  entryPremium: number;
  currentPremium: number;
  stopLoss: number;
  target1: number;
  target2: number;
  target3?: number;
  lots: number;
  lotSize: number;
  totalQuantity: number;
  remainingLots?: number;
  remainingQuantity?: number;
  marginUsed: number;
  pnl: number;
  pnlPercent: number;
  grossPnl?: number;
  netPnl?: number;
  statutoryCosts?: number;
  smcModel?: string;
  status: 'OPEN' | 'TARGET1_HIT' | 'TARGET2_HIT' | 'STOPPED_OUT' | 'CLOSED_MANUALLY' | 'PARTIALLY_CLOSED';
  openedAt: string;
  closedAt?: string;
  exitPremium?: number;
  exitReason?: string;
  highestObservedLtp?: number;
  lowestObservedLtp?: number;
  mfe?: number;
  mae?: number;
  partialExits?: PartialExitRecord[];
  aiEvaluation?: AITradeEvaluation;
  costBreakdown?: CostBreakdown;
  isMtmAvailable?: boolean;
  feedStatus?: string;
  holdingDuration?: string;
}

export interface PaperTradingState {
  balance: number;              // Current cash available
  startingBalance: number;      // Initial starting capital (default ₹1,00,000)
  positions: PaperPosition[];   // Active open positions
  closedTrades: PaperPosition[];// Completed trades journal
  totalRealizedPnl: number;
  winCount: number;
  lossCount: number;
}

const STORAGE_KEY = 'aivolve_paper_trading_state_v1';
const DEFAULT_CAPITAL = 100000.0;

class PaperTradingManager {
  private state: PaperTradingState;
  private listeners: Set<(state: PaperTradingState) => void> = new Set();

  constructor() {
    this.state = this.loadState();
  }

  private loadState(): PaperTradingState {
    if (typeof window === 'undefined') {
      return this.getDefaultState();
    }
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed.positions)) {
          parsed.positions = parsed.positions.filter((p: any) => p && Number(p.entryPremium) > 0);
        }
        if (Array.isArray(parsed.closedTrades)) {
          parsed.closedTrades = parsed.closedTrades.filter((t: any) => t && Number(t.entryPremium) > 0);
          // Recalculate true winCount and lossCount
          parsed.winCount = parsed.closedTrades.filter((t: any) => Number(t.pnl) > 0.01).length;
          parsed.lossCount = parsed.closedTrades.filter((t: any) => Number(t.pnl) < -0.01).length;
          parsed.totalRealizedPnl = round(parsed.closedTrades.reduce((acc: number, t: any) => acc + (Number(t.pnl) || 0), 0), 2);
        }
        return parsed;
      }
    } catch (e) {
      console.warn('Failed to load paper trading state:', e);
    }
    return this.getDefaultState();
  }

  private getDefaultState(): PaperTradingState {
    return {
      balance: DEFAULT_CAPITAL,
      startingBalance: DEFAULT_CAPITAL,
      positions: [],
      closedTrades: [],
      totalRealizedPnl: 0.0,
      winCount: 0,
      lossCount: 0,
    };
  }

  private saveState() {
    if (typeof window !== 'undefined') {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(this.state));
      } catch (e) {
        console.warn('Failed to save paper trading state:', e);
      }
    }
    this.notify();
  }

  private notify() {
    const clone = JSON.parse(JSON.stringify(this.state));
    this.listeners.forEach((fn) => fn(clone));
  }

  public subscribe(listener: (state: PaperTradingState) => void): () => void {
    this.listeners.add(listener);
    listener(JSON.parse(JSON.stringify(this.state)));
    return () => this.listeners.delete(listener);
  }

  public getState(): PaperTradingState {
    return JSON.parse(JSON.stringify(this.state));
  }

  /**
   * 1-Click Execution from an OptionTradeSetup.
   */
  public openPosition(setup: OptionTradeSetup, lots: number = 1): { success: boolean; message: string; position?: PaperPosition } {
    const lotSize = (setup as any).lotSize || (setup.index.includes('BANK') ? 15 : setup.index.includes('SENSEX') ? 10 : 65);
    const totalQty = lots * lotSize;
    const rawPrice = setup.currentPremium || (setup as any).lastObservedLtp;
    const entryPrice = Math.max(1.0, typeof rawPrice === 'number' && rawPrice > 0 ? rawPrice : 120.0);
    const marginRequired = round(entryPrice * totalQty, 2);

    if (marginRequired > this.state.balance) {
      return {
        success: false,
        message: `Insufficient virtual funds. Required ₹${marginRequired.toLocaleString('en-IN')}, available ₹${this.state.balance.toLocaleString('en-IN')}.`,
      };
    }

    const posId = `PT-${Date.now().toString(36).toUpperCase()}-${Math.floor(Math.random() * 900 + 100)}`;
    const nowStr = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });

    const newPosition: PaperPosition = {
      id: posId,
      symbol: setup.index,
      contractSymbol: setup.contractSymbol,
      bias: setup.bias,
      strike: setup.strike,
      expiry: setup.expiry,
      entryPremium: entryPrice,
      currentPremium: entryPrice,
      stopLoss: setup.stopLoss && setup.stopLoss > 0 ? setup.stopLoss : round(entryPrice * 0.85, 1),
      target1: setup.target1 && setup.target1 > 0 ? setup.target1 : round(entryPrice * 1.30, 1),
      target2: setup.target2 && setup.target2 > 0 ? setup.target2 : round(entryPrice * 1.55, 1),
      lots: lots,
      lotSize: lotSize,
      totalQuantity: totalQty,
      marginUsed: marginRequired,
      pnl: 0.0,
      pnlPercent: 0.0,
      smcModel: (setup as any).smcModel || 'SMC Standard Setup',
      status: 'OPEN',
      openedAt: nowStr,
    };

    this.state.balance = round(this.state.balance - marginRequired, 2);
    this.state.positions.unshift(newPosition);
    this.saveState();

    return {
      success: true,
      message: `Kharid Liya (Bought): ${lots} Lot (${totalQty} Qty) of ${setup.contractSymbol} @ ₹${entryPrice.toFixed(2)} at ${nowStr}.`,
      position: newPosition,
    };
  }

  /**
   * Close an open virtual position (Manual Exit or Target/SL triggered).
   */
  public closePosition(positionId: string, manualExitPrice?: number, exitReason: string = 'Manual Exit'): { success: boolean; message: string } {
    const idx = this.state.positions.findIndex((p) => p.id === positionId);
    if (idx === -1) {
      return { success: false, message: 'Position not found or already closed.' };
    }

    const pos = this.state.positions[idx];
    const rawExit = manualExitPrice !== undefined && manualExitPrice > 0 ? manualExitPrice : (pos.currentPremium > 0 ? pos.currentPremium : pos.entryPremium);
    const exitPrice = Math.max(1.0, typeof rawExit === 'number' && rawExit > 0 ? rawExit : 120.0);
    const grossReturn = round(exitPrice * pos.totalQuantity, 2);
    const realizedPnl = round(grossReturn - pos.marginUsed, 2);
    const pnlPct = round(((exitPrice - pos.entryPremium) / pos.entryPremium) * 100.0, 2);

    const nowStr = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });

    pos.exitPremium = exitPrice;
    pos.pnl = realizedPnl;
    pos.pnlPercent = pnlPct;
    pos.closedAt = nowStr;
    pos.exitReason = exitReason;
    pos.status = realizedPnl > 0.01 ? 'TARGET1_HIT' : (realizedPnl < -0.01 ? 'STOPPED_OUT' : 'CLOSED_MANUALLY');

    // Update balances & analytics
    this.state.balance = round(this.state.balance + grossReturn, 2);
    this.state.totalRealizedPnl = round(this.state.totalRealizedPnl + realizedPnl, 2);
    if (realizedPnl > 0.01) {
      this.state.winCount += 1;
    } else if (realizedPnl < -0.01) {
      this.state.lossCount += 1;
    }

    // Move to closed trades
    this.state.positions.splice(idx, 1);
    this.state.closedTrades.unshift(pos);
    this.saveState();

    // Asynchronously send feedback to Machine Learning strategy learner
    this.sendMlFeedback(pos);

    return {
      success: true,
      message: `Bech Diya (Sold): ${pos.contractSymbol} @ ₹${exitPrice.toFixed(2)} at ${nowStr}. P&L: ₹${realizedPnl >= 0 ? '+' : ''}${realizedPnl.toLocaleString('en-IN')} (${pnlPct >= 0 ? '+' : ''}${pnlPct}%).`,
    };
  }

  /**
   * Helper to find an active open position for a given contract symbol.
   */
  public getOpenPositionForContract(contractSymbol: string): PaperPosition | undefined {
    return this.state.positions.find((p) => p.contractSymbol === contractSymbol);
  }

  /**
   * 1-Click execution from a Signal Activation Data object.
   */
  public executeTradeFromSignal(
    signal: {
      index: string;
      contractSymbol: string;
      bias: 'CE' | 'PE' | string;
      strike: number;
      expiry: string;
      lastObservedLtp: number;
      stopLoss: number;
      target1: number;
      target2: number;
      entryRangeMin?: number;
      entryRangeMax?: number;
    },
    options?: { customEntryPrice?: number; lots?: number }
  ): { success: boolean; message: string; position?: PaperPosition } {
    const idxSym = (signal.index || '').toUpperCase();
    const lotSize = idxSym.includes('BANK') ? 15 : idxSym.includes('SENSEX') ? 10 : 50;
    const lots = options?.lots || 1;
    const totalQty = lots * lotSize;
    const rawEntry = options?.customEntryPrice !== undefined ? options.customEntryPrice : signal.lastObservedLtp;
    const entryPrice = Math.max(1.0, round(rawEntry || 120.0, 2));
    const marginRequired = round(entryPrice * totalQty, 2);

    if (marginRequired > this.state.balance) {
      return {
        success: false,
        message: `Insufficient virtual funds. Required ₹${marginRequired.toLocaleString('en-IN')}, available ₹${this.state.balance.toLocaleString('en-IN')}.`,
      };
    }

    const posId = `PT-${Date.now().toString(36).toUpperCase()}-${Math.floor(Math.random() * 900 + 100)}`;
    const nowStr = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    const stopLoss = signal.stopLoss > 0 ? signal.stopLoss : round(entryPrice * 0.75, 1);
    const target1 = signal.target1 > 0 ? signal.target1 : round(entryPrice * 1.30, 1);
    const target2 = signal.target2 > 0 ? signal.target2 : round(entryPrice * 1.60, 1);

    const newPosition: PaperPosition = {
      id: posId,
      symbol: signal.index,
      contractSymbol: signal.contractSymbol,
      bias: signal.bias === 'PE' ? 'PE' : 'CE',
      strike: signal.strike,
      expiry: signal.expiry,
      entryPremium: entryPrice,
      currentPremium: entryPrice,
      stopLoss: stopLoss,
      target1: target1,
      target2: target2,
      lots: lots,
      lotSize: lotSize,
      totalQuantity: totalQty,
      marginUsed: marginRequired,
      pnl: 0.0,
      pnlPercent: 0.0,
      smcModel: 'Signal Activation Engine',
      status: 'OPEN',
      openedAt: nowStr,
    };

    this.state.balance = round(this.state.balance - marginRequired, 2);
    this.state.positions.unshift(newPosition);
    this.saveState();

    return {
      success: true,
      message: `Kharid Liya (Bought): ${lots} Lot (${totalQty} Qty) of ${signal.contractSymbol} @ ₹${entryPrice.toFixed(2)} at ${nowStr}.`,
      position: newPosition,
    };
  }

  /**
   * Closes a position directly at a designated target (Target 1, Target 2, Target 3).
   */
  public closePositionAtTarget(
    positionId: string,
    targetPrice: number,
    targetLabel: string = 'Target 1'
  ): { success: boolean; message: string } {
    return this.closePosition(positionId, targetPrice, `${targetLabel} Hit (₹${targetPrice.toFixed(2)})`);
  }

  /**
   * Blocked in strict production paper trading mode.
   * Prohibits artificial/synthetic trade generation.
   */
  public simulateDirectTargetTrade(
    _signal: any,
    _targetPrice: number,
    _targetLabel: string = 'Target 1',
    _lots: number = 1
  ): { success: boolean; message: string } {
    return {
      success: false,
      message: 'STRICT GOVERNANCE ENFORCED: Artificial trade generation is disabled. Trades can only execute from verified signals.',
    };
  }

  /**
   * Sends completed trade outcomes to backend Machine Learning engine.
   */
  private sendMlFeedback(pos: PaperPosition) {
    if (typeof window === 'undefined') return;
    try {
      fetch('/api/options/trade-feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contractSymbol: pos.contractSymbol,
          outcome: pos.status,
          smcModel: pos.smcModel || 'Model A (Liquidity Sweep & CHoCH)',
          realizedPnl: pos.pnl,
          realizedRr: pos.pnl > 0 ? 1.85 : -1.0,
          entryPrice: pos.entryPremium,
          exitPrice: pos.exitPremium || pos.currentPremium,
        }),
      }).catch(() => {});
    } catch {
      // offline handling
    }
  }

  /**
   * Trail stop-loss to cost or custom level (Risk-Free Trade management).
   */
  public trailStopLoss(positionId: string, newStopLoss: number): { success: boolean; message: string } {
    const pos = this.state.positions.find((p) => p.id === positionId);
    if (!pos) {
      return { success: false, message: 'Position not found.' };
    }

    pos.stopLoss = round(newStopLoss, 2);
    this.saveState();
    return {
      success: true,
      message: `Stop-Loss trailed to ₹${newStopLoss.toFixed(2)} for ${pos.contractSymbol}.`,
    };
  }

  /**
   * Updates live market premiums and checks for automatic Stop-Loss or Target executions.
   * Enforces fail-closed MTM: If feed is offline or stale, marks MTM as unavailable.
   */
  public updateLivePrice(contractSymbol: string, currentLtp: number, feedStatus?: string) {
    let changed = false;
    for (let i = this.state.positions.length - 1; i >= 0; i--) {
      const pos = this.state.positions[i];
      if (pos.contractSymbol === contractSymbol) {
        if (currentLtp <= 0 || feedStatus === 'DATA_OFFLINE' || feedStatus === 'UNAVAILABLE' || feedStatus === 'STALE') {
          pos.isMtmAvailable = false;
          pos.feedStatus = feedStatus || 'DATA_OFFLINE';
          changed = true;
          continue;
        }
        pos.isMtmAvailable = true;
        pos.feedStatus = feedStatus || 'LIVE';
        pos.currentPremium = currentLtp;
        pos.pnl = round((currentLtp - pos.entryPremium) * pos.totalQuantity, 2);
        pos.pnlPercent = round(((currentLtp - pos.entryPremium) / pos.entryPremium) * 100.0, 2);
        changed = true;

        // Auto-Exit Condition A: Stop Loss Hit
        if (currentLtp <= pos.stopLoss) {
          this.closePosition(pos.id, pos.stopLoss, 'Auto Stop-Loss Triggered');
          continue;
        }

        // Auto-Exit Condition B: Target 2 Hit
        if (currentLtp >= pos.target2) {
          this.closePosition(pos.id, pos.target2, 'Target 2 (1.85R) Reached');
          continue;
        }
      }
    }

    if (changed) {
      this.saveState();
      this.notify();
    }
  }

  /**
   * Sync local paper trading state with the FastAPI backend engine.
   */
  public async syncWithBackend(): Promise<PaperTradingState | null> {
    if (typeof window === 'undefined') return null;
    try {
      const res = await fetch('/api/paper-trading/portfolio');
      if (!res.ok) return null;
      const data = await res.json();
      if (data && data.status === 'SUCCESS') {
        const bal = data.currentBalance !== undefined ? data.currentBalance : data.balance;
        if (bal !== undefined) this.state.balance = bal;
        if (data.startingBalance !== undefined) this.state.startingBalance = data.startingBalance;
        if (Array.isArray(data.openPositions)) {
          this.state.positions = data.openPositions.map((p: any) => ({
            id: p.id,
            symbol: p.instrument || 'NIFTY 50',
            contractSymbol: p.contractSymbol,
            bias: p.bias,
            strike: p.strike,
            expiry: p.expiry,
            entryPremium: p.entryPremium,
            currentPremium: p.currentPremium,
            stopLoss: p.stopLoss,
            target1: p.target1,
            target2: p.target2,
            target3: p.target3,
            lots: p.lots,
            lotSize: p.lotSize,
            totalQuantity: p.quantity,
            remainingLots: p.remainingLots,
            remainingQuantity: p.remainingQuantity,
            marginUsed: p.entryPremium * p.quantity,
            pnl: p.unrealizedPnl || 0.0,
            pnlPercent: p.unrealizedPnlPct || 0.0,
            grossPnl: p.grossPnl,
            netPnl: p.netPnl,
            statutoryCosts: p.statutoryCosts,
            smcModel: p.strategy,
            status: p.status,
            openedAt: p.entryTimestamp,
            mfe: p.mfe,
            mae: p.mae,
            highestObservedLtp: p.highestObservedLtp,
            lowestObservedLtp: p.lowestObservedLtp,
            partialExits: p.partialExits,
            aiEvaluation: p.aiEvaluation,
            costBreakdown: p.costBreakdown,
          }));
        }
        const closed = Array.isArray(data.recentClosedTrades)
          ? data.recentClosedTrades
          : Array.isArray(data.closedTrades)
          ? data.closedTrades
          : null;
        if (closed) {
          this.state.closedTrades = closed.map((p: any) => ({
            id: p.id,
            symbol: p.instrument || 'NIFTY 50',
            contractSymbol: p.contractSymbol,
            bias: p.bias,
            strike: p.strike,
            expiry: p.expiry,
            entryPremium: p.entryPremium,
            currentPremium: p.exitPremium || p.currentPremium,
            exitPremium: p.exitPremium,
            stopLoss: p.stopLoss,
            target1: p.target1,
            target2: p.target2,
            target3: p.target3,
            lots: p.lots,
            lotSize: p.lotSize,
            totalQuantity: p.quantity,
            marginUsed: p.entryPremium * p.quantity,
            pnl: p.netPnl ?? p.grossPnl ?? 0.0,
            pnlPercent: p.pnlPercent || 0.0,
            grossPnl: p.grossPnl,
            netPnl: p.netPnl,
            statutoryCosts: p.statutoryCosts,
            smcModel: p.strategy,
            status: p.status,
            openedAt: p.entryTimestamp,
            closedAt: p.exitTimestamp,
            exitReason: p.exitReason,
            mfe: p.mfe,
            mae: p.mae,
            partialExits: p.partialExits,
            aiEvaluation: p.aiEvaluation,
            costBreakdown: p.costBreakdown,
          }));
        }
        if (data.totalRealizedNetPnl !== undefined) this.state.totalRealizedPnl = data.totalRealizedNetPnl;
        if (data.winningTrades !== undefined) this.state.winCount = data.winningTrades;
        if (data.losingTrades !== undefined) this.state.lossCount = data.losingTrades;
        this.saveState();
        return this.getState();
      }
    } catch (e) {
      console.warn('Paper trading backend sync failed, using local state:', e);
    }
    return null;
  }

  /**
   * Open simulated trade on backend engine.
   */
  public async openPositionBackend(params: {
    instrument: string;
    contractSymbol: string;
    bias: 'CE' | 'PE';
    strike: number;
    expiry: string;
    entryPremium: number;
    lots: number;
    lotSize: number;
    stopLoss: number;
    target1: number;
    target2: number;
    target3?: number;
    strategy?: string;
    ictSetup?: string;
    marketFeatures?: Record<string, any>;
  }): Promise<{ success: boolean; message: string; position?: PaperPosition }> {
    try {
      const res = await fetch('/api/paper-trading/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      const data = await res.json();
      if (res.ok && data?.success === true) {
        await this.syncWithBackend();
        return { success: true, message: data.message, position: data.position };
      }
      return { success: false, message: typeof data?.message === 'string' ? data.message : 'Server rejected this trade. No local trade was created.' };
    } catch {
      return { success: false, message: 'Trade outcome could not be confirmed. Refresh the portfolio before retrying.' };
    }
  }

  /**
   * Close simulated trade on backend engine with full statutory fee calculation & AI review.
   */
  public async closePositionBackend(
    positionId: string,
    exitPrice?: number,
    exitReason: string = 'Manually Closed'
  ): Promise<{ success: boolean; message: string }> {
    try {
      const pos = this.state.positions.find((p) => p.id === positionId);
      const actualExit = exitPrice !== undefined ? exitPrice : (pos?.currentPremium || 0.0);
      const res = await fetch('/api/paper-trading/close', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          positionId: positionId,
          exitPrice: actualExit,
          exitReason: exitReason,
        }),
      });
      const data = await res.json();
      if (res.ok && data?.success === true) {
        await this.syncWithBackend();
        return { success: true, message: data.message };
      }
      return { success: false, message: typeof data?.message === 'string' ? data.message : 'Server rejected this exit. The local position was retained.' };
    } catch {
      return { success: false, message: 'Exit outcome could not be confirmed. Refresh the portfolio before retrying.' };
    }
  }

  /**
   * Execute partial exit (e.g. 50% at Target 1) and trail stop loss for runner.
   */
  public async executePartialExit(
    positionId: string,
    exitLots: number = 1,
    exitPrice?: number,
    exitLabel: string = 'Target 1 Hit (50% Partial)'
  ): Promise<{ success: boolean; message: string }> {
    try {
      const pos = this.state.positions.find((p) => p.id === positionId);
      const actualExit = exitPrice !== undefined ? exitPrice : (pos?.currentPremium || 0.0);
      const res = await fetch('/api/paper-trading/partial-exit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          positionId: positionId,
          exitLots: exitLots,
          exitPrice: actualExit,
          exitLabel: exitLabel,
        }),
      });
      const data = await res.json();
      if (data && data.success) {
        await this.syncWithBackend();
        return { success: true, message: data.message };
      }
    } catch (e) {
      console.warn('Backend partial exit failed:', e);
    }
    return { success: false, message: 'Partial exit could not be executed on server.' };
  }

  /**
   * Fetch WHAT AI LEARNED Knowledge Dashboard from backend.
   */
  public async getWhatAiLearned(): Promise<WhatAiLearnedData | null> {
    try {
      const res = await fetch('/api/paper-trading/what-ai-learned');
      if (!res.ok) return null;
      const data = await res.json();
      if (data && data.status === 'SUCCESS') {
        return data as WhatAiLearnedData;
      }
    } catch (e) {
      console.warn('Failed to fetch what AI learned:', e);
    }
    return null;
  }

  /**
   * Fetch 9-factor AI post-trade review for a specific closed trade.
   */
  public async getTradeEvaluation(tradeId: string): Promise<AITradeEvaluation | null> {
    try {
      const res = await fetch(`/api/paper-trading/trade-evaluation/${tradeId}`);
      if (!res.ok) return null;
      const data = await res.json();
      if (data && data.status === 'SUCCESS') {
        return data.evaluation as AITradeEvaluation;
      }
    } catch (e) {
      console.warn(`Failed to fetch trade evaluation for ${tradeId}:`, e);
    }
    return null;
  }

  /**
   * Statutory tax and brokerage calculator for Indian derivatives.
   */
  public async calculateCosts(
    entryPrice: number,
    exitPrice: number,
    quantity: number,
    positionType: 'BUY' | 'SELL' = 'BUY'
  ): Promise<CostBreakdown | null> {
    try {
      const res = await fetch('/api/paper-trading/calculate-costs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          entryPrice: entryPrice,
          exitPrice: exitPrice,
          quantity: quantity,
          positionType: positionType,
        }),
      });
      if (res.ok) {
        return await res.json();
      }
    } catch (e) {
      console.warn('Cost calculation request failed:', e);
    }
    return null;
  }

  /**
   * Reset Virtual Portfolio both locally and on backend server.
   */
  public async resetAccount() {
    try {
      const response = await fetch('/api/paper-trading/reset', { method: 'POST' });
      const data = await response.json();
      if (!response.ok || data?.status !== 'SUCCESS') return { success: false, message: 'Server rejected portfolio reset.' };
      const state = await this.syncWithBackend();
      return { success: Boolean(state), message: state ? 'Portfolio reset.' : 'Reset accepted; refresh to confirm the portfolio.' };
    } catch {
      return { success: false, message: 'Reset outcome could not be confirmed. Refresh the portfolio.' };
    }
  }

}

function round(val: number, decimals: number = 2): number {
  const factor = Math.pow(10, decimals);
  return Math.round(val * factor) / factor;
}

export const paperTradingManager = new PaperTradingManager();

