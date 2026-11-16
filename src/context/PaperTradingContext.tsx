'use client';

import React, { createContext, useContext, useState, useEffect } from 'react';
import { PaperPosition, PaperTradeHistory, TelegramAlertConfig } from '@/types/market';

interface PaperTradingContextType {
  virtualBalance: number;
  initialCapital: number;
  positions: PaperPosition[];
  history: PaperTradeHistory[];
  telegramConfig: TelegramAlertConfig;
  executePaperTrade: (
    symbol: string,
    companyName: string,
    signalType: 'CALL' | 'PUT',
    price: number,
    quantity: number,
    targetPrice: number,
    stopLossPrice: number
  ) => { success: boolean; message: string };
  squareOffPosition: (positionId: string, exitPrice: number, reason?: 'Target Met' | 'Stop Loss' | 'Manual Square Off') => void;
  resetPortfolio: () => void;
  updateTelegramConfig: (config: Partial<TelegramAlertConfig>) => void;
  sendTelegramTestAlert: () => Promise<{ success: boolean; message: string }>;
}

const INITIAL_CAPITAL = 1000000; // ₹10,00,000 INR Demo capital

const DEFAULT_TELEGRAM_CONFIG: TelegramAlertConfig = {
  botToken: '',
  chatId: '',
  enabled: false,
  minScore: 80,
  notifyCall: true,
  notifyPut: true,
};

// Truthful initial state: Zero mock/fabricated trades.
const SEED_POSITIONS: PaperPosition[] = [];
const SEED_HISTORY: PaperTradeHistory[] = [];

const PaperTradingContext = createContext<PaperTradingContextType | undefined>(undefined);

export const PaperTradingProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [virtualBalance, setVirtualBalance] = useState<number>(INITIAL_CAPITAL);
  const [positions, setPositions] = useState<PaperPosition[]>(SEED_POSITIONS);
  const [history, setHistory] = useState<PaperTradeHistory[]>(SEED_HISTORY);
  const [telegramConfig, setTelegramConfig] = useState<TelegramAlertConfig>(DEFAULT_TELEGRAM_CONFIG);

  // Load from localStorage on mount
  useEffect(() => {
    try {
      const savedBalance = localStorage.getItem('aivolve_virtual_balance');
      const savedPositions = localStorage.getItem('aivolve_paper_positions');
      const savedHistory = localStorage.getItem('aivolve_paper_history');
      const savedTg = localStorage.getItem('aivolve_telegram_config');

      queueMicrotask(() => {
        if (savedBalance) setVirtualBalance(parseFloat(savedBalance));
        if (savedPositions) setPositions(JSON.parse(savedPositions));
        if (savedHistory) setHistory(JSON.parse(savedHistory));
        if (savedTg) setTelegramConfig(JSON.parse(savedTg));
      });
    } catch {
      // Ignore localStorage errors
    }
  }, []);

  // Save to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('aivolve_virtual_balance', virtualBalance.toString());
      localStorage.setItem('aivolve_paper_positions', JSON.stringify(positions));
      localStorage.setItem('aivolve_paper_history', JSON.stringify(history));
      localStorage.setItem('aivolve_telegram_config', JSON.stringify(telegramConfig));
    } catch {
      // Ignore
    }
  }, [virtualBalance, positions, history, telegramConfig]);

  // Execute Paper Trade
  const executePaperTrade = (
    symbol: string,
    companyName: string,
    signalType: 'CALL' | 'PUT',
    price: number,
    quantity: number,
    targetPrice: number,
    stopLossPrice: number
  ) => {
    const totalCost = price * quantity;

    if (totalCost > virtualBalance) {
      return {
        success: false,
        message: `Insufficient demo funds! Required: ₹${totalCost.toLocaleString('en-IN')}, Available: ₹${virtualBalance.toLocaleString('en-IN')}`,
      };
    }

    const newPosition: PaperPosition = {
      id: `pos-${Date.now()}`,
      symbol,
      companyName,
      signalType,
      entryPrice: price,
      currentPrice: price,
      quantity,
      investedAmount: totalCost,
      targetPrice,
      stopLossPrice,
      pnl: 0,
      pnlPercent: 0,
      openedAt: 'Just now',
    };

    setVirtualBalance((prev) => prev - totalCost);
    setPositions((prev) => [newPosition, ...prev]);

    return {
      success: true,
      message: `Paper Trade Executed: ${quantity} shares of ${symbol} (${signalType}) at ₹${price}`,
    };
  };

  // Square off position
  const squareOffPosition = (
    positionId: string,
    exitPrice: number,
    reason: 'Target Met' | 'Stop Loss' | 'Manual Square Off' = 'Manual Square Off'
  ) => {
    const pos = positions.find((p) => p.id === positionId);
    if (!pos) return;

    const returnAmount = exitPrice * pos.quantity;
    const realizedPnl =
      pos.signalType === 'CALL'
        ? (exitPrice - pos.entryPrice) * pos.quantity
        : (pos.entryPrice - exitPrice) * pos.quantity;
    const realizedPnlPercent = (realizedPnl / pos.investedAmount) * 100;

    const historyItem: PaperTradeHistory = {
      id: `hist-${Date.now()}`,
      symbol: pos.symbol,
      companyName: pos.companyName,
      signalType: pos.signalType,
      entryPrice: pos.entryPrice,
      exitPrice,
      quantity: pos.quantity,
      investedAmount: pos.investedAmount,
      realizedPnl: Math.round(realizedPnl),
      realizedPnlPercent: parseFloat(realizedPnlPercent.toFixed(2)),
      exitReason: reason,
      openedAt: pos.openedAt,
      closedAt: 'Just now',
    };

    setVirtualBalance((prev) => prev + returnAmount);
    setPositions((prev) => prev.filter((p) => p.id !== positionId));
    setHistory((prev) => [historyItem, ...prev]);
  };

  // Reset portfolio to ₹10 Lakh
  const resetPortfolio = () => {
    setVirtualBalance(INITIAL_CAPITAL);
    setPositions([]);
    setHistory([]);
  };

  // Update Telegram configuration
  const updateTelegramConfig = (config: Partial<TelegramAlertConfig>) => {
    setTelegramConfig((prev) => ({ ...prev, ...config }));
  };

  // Send real test alert to Telegram
  const sendTelegramTestAlert = async () => {
    if (!telegramConfig.botToken || !telegramConfig.chatId) {
      return {
        success: false,
        message: 'Please provide both Telegram Bot Token and Chat/Channel ID!',
      };
    }

    const messageText = `🚀 *AIVOLVE TRADING AI — BREAKOUT ALERT* ⚡
━━━━━━━━━━━━━━━━━━━━
📈 *Stock:* RELIANCE (NSE)
🎯 *Signal:* CALL (Bullish Momentum)
📊 *Quant Setup Score:* 86 / 100
💵 *CMP:* ₹1,455.00
🎯 *Target:* ₹1,510.00 (+3.78%)
🛡️ *Stop Loss:* ₹1,420.00 (-2.40%)
⚡ *Risk:Reward:* 1 : 1.6
━━━━━━━━━━━━━━━━━━━━
💡 *AI Catalyst:* Price trading above 20 EMA and VWAP dynamic pivot with 1.8x institutional volume surge.
⚠️ _Disclaimer: AI research suggestion only. Test with virtual paper trading._`;

    try {
      const url = `https://api.telegram.org/bot${telegramConfig.botToken}/sendMessage`;
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chat_id: telegramConfig.chatId,
          text: messageText,
          parse_mode: 'Markdown',
        }),
      });

      const data = await res.json();
      if (data.ok) {
        setTelegramConfig((prev) => ({ ...prev, lastTestedAt: new Date().toLocaleTimeString() }));
        return { success: true, message: 'Test Alert sent successfully to your Telegram!' };
      } else {
        return { success: false, message: `Telegram Error: ${data.description || 'Failed to send'}` };
      }
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Network error';
      return { success: false, message: `Failed to connect to Telegram API: ${errorMsg}` };
    }
  };

  return (
    <PaperTradingContext.Provider
      value={{
        virtualBalance,
        initialCapital: INITIAL_CAPITAL,
        positions,
        history,
        telegramConfig,
        executePaperTrade,
        squareOffPosition,
        resetPortfolio,
        updateTelegramConfig,
        sendTelegramTestAlert,
      }}
    >
      {children}
    </PaperTradingContext.Provider>
  );
};

export const usePaperTrading = () => {
  const context = useContext(PaperTradingContext);
  if (!context) {
    throw new Error('usePaperTrading must be used within a PaperTradingProvider');
  }
  return context;
};
