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

// Pre-seeded initial active suggestions so user sees working live data immediately!
const SEED_POSITIONS: PaperPosition[] = [
  {
    id: 'pos-1',
    symbol: 'RELIANCE',
    companyName: 'Reliance Industries Ltd',
    signalType: 'CALL',
    entryPrice: 1448.0,
    currentPrice: 1455.0,
    quantity: 100,
    investedAmount: 144800,
    targetPrice: 1510.0,
    stopLossPrice: 1420.0,
    pnl: 700,
    pnlPercent: 0.48,
    openedAt: 'Today, 09:35 AM',
  },
  {
    id: 'pos-2',
    symbol: 'SBIN',
    companyName: 'State Bank of India',
    signalType: 'CALL',
    entryPrice: 820.0,
    currentPrice: 825.4,
    quantity: 200,
    investedAmount: 164000,
    targetPrice: 855.0,
    stopLossPrice: 805.0,
    pnl: 1080,
    pnlPercent: 0.66,
    openedAt: 'Today, 10:15 AM',
  },
];

const SEED_HISTORY: PaperTradeHistory[] = [
  {
    id: 'hist-1',
    symbol: 'TCS',
    companyName: 'Tata Consultancy Services',
    signalType: 'CALL',
    entryPrice: 4120.0,
    exitPrice: 4210.0,
    quantity: 50,
    investedAmount: 206000,
    realizedPnl: 4500,
    realizedPnlPercent: 2.18,
    exitReason: 'Target Met',
    openedAt: 'Yesterday, 10:00 AM',
    closedAt: 'Yesterday, 02:45 PM',
  },
];

const PaperTradingContext = createContext<PaperTradingContextType | undefined>(undefined);

export const PaperTradingProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [virtualBalance, setVirtualBalance] = useState<number>(691200); // 10L - invested in seed positions
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
