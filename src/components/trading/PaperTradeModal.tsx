'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  Zap,
  ShieldCheck,
  TrendingUp,
  TrendingDown,
  CheckCircle2,
  AlertCircle,
  Sparkles,
} from 'lucide-react';
import { formatINR } from '@/lib/utils';
import { SignalBadge } from '@/components/shared/SignalBadge';
import { usePaperTrading } from '@/context/PaperTradingContext';
import { SignalType } from '@/types/market';

interface PaperTradeModalProps {
  isOpen: boolean;
  onClose: () => void;
  candidate: {
    symbol: string;
    companyName: string;
    signalType: SignalType;
    currentPrice: number;
    expectedHigh: number;
    expectedLow: number;
    analysisScore: number;
  };
}

export const PaperTradeModal: React.FC<PaperTradeModalProps> = ({
  isOpen,
  onClose,
  candidate,
}) => {
  const { virtualBalance, executePaperTrade } = usePaperTrading();
  const [quantity, setQuantity] = useState(50);
  const [feedback, setFeedback] = useState<{ success?: boolean; message?: string } | null>(null);

  if (!isOpen) return null;

  const isCall = candidate.signalType === 'CALL';
  const target = isCall ? candidate.expectedHigh : candidate.expectedLow;
  const stopLoss = isCall ? candidate.expectedLow : candidate.expectedHigh;
  const totalCost = candidate.currentPrice * quantity;
  const hasEnoughFunds = virtualBalance >= totalCost;

  const handleExecute = () => {
    const tradeSignal: 'CALL' | 'PUT' = candidate.signalType === 'PUT' ? 'PUT' : 'CALL';
    const res = executePaperTrade(
      candidate.symbol,
      candidate.companyName,
      tradeSignal,
      candidate.currentPrice,
      quantity,
      target,
      stopLoss
    );

    setFeedback(res);

    if (res.success) {
      setTimeout(() => {
        setFeedback(null);
        onClose();
      }, 1400);
    }
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 dark:bg-black/80 backdrop-blur-sm">
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 15 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 15 }}
          transition={{ duration: 0.2 }}
          className="relative w-full max-w-lg rounded-2xl bg-white dark:bg-[#0c1017] border border-slate-200 dark:border-white/[0.12] shadow-2xl overflow-hidden p-6 space-y-5"
        >
          {/* Top Header */}
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-white/[0.08] pb-3">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/25 flex items-center justify-center">
                <Zap className="w-4 h-4 text-amber-600 dark:text-[#dfa759]" />
              </div>
              <div>
                <h3 className="text-sm font-bold font-mono text-slate-900 dark:text-white flex items-center gap-2">
                  <span>Paper Trade Suggestion</span>
                  <span className="text-[10px] font-normal px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-transparent font-mono">
                    Zero Risk
                  </span>
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Simulate this AI setup using virtual demo capital.
                </p>
              </div>
            </div>

            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-white/[0.06] text-slate-400 hover:text-slate-700 dark:hover:text-white transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Stock Details & Signal */}
          <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-black/40 border border-slate-200 dark:border-white/[0.06] flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-bold font-mono text-slate-900 dark:text-white">
                  {candidate.symbol}
                </span>
                <SignalBadge type={candidate.signalType} size="sm" />
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400">{candidate.companyName}</p>
            </div>

            <div className="text-right font-mono">
              <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block">CMP Price</span>
              <span className="text-base font-bold text-slate-900 dark:text-white">
                {formatINR(candidate.currentPrice)}
              </span>
            </div>
          </div>

          {/* Target, SL and AI Score info */}
          <div className="grid grid-cols-3 gap-2.5 text-xs font-mono">
            <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-white/[0.02] border border-slate-200 dark:border-white/[0.06]">
              <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block">AI Target</span>
              <span
                className={`font-bold ${isCall ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}
              >
                {formatINR(target, false)}
              </span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-white/[0.02] border border-slate-200 dark:border-white/[0.06]">
              <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block">Stop Loss</span>
              <span className="text-slate-800 dark:text-slate-300 font-bold">{formatINR(stopLoss, false)}</span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-white/[0.02] border border-slate-200 dark:border-white/[0.06]">
              <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block">AI Score</span>
              <span className="text-amber-700 dark:text-[#dfa759] font-bold">
                {candidate.analysisScore} / 100
              </span>
            </div>
          </div>

          {/* Quantity Selector */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs font-mono text-slate-700 dark:text-slate-300">
              <span>Order Quantity:</span>
              <span className="text-amber-700 dark:text-[#dfa759] font-bold">{quantity} shares</span>
            </div>

            <div className="flex items-center gap-2">
              {[25, 50, 100, 200, 500].map((qty) => (
                <button
                  key={qty}
                  type="button"
                  onClick={() => setQuantity(qty)}
                  className={`flex-1 py-1.5 rounded-lg text-xs font-mono transition-all ${
                    quantity === qty
                      ? 'bg-amber-500 dark:bg-[#dfa759] text-white dark:text-black font-bold shadow'
                      : 'bg-slate-100 hover:bg-slate-200 dark:bg-white/[0.03] dark:hover:bg-white/[0.06] text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-white/[0.08]'
                  }`}
                >
                  {qty}
                </button>
              ))}
            </div>
          </div>

          {/* Margin & Available Funds */}
          <div className="p-3 rounded-lg bg-slate-50 dark:bg-white/[0.02] border border-slate-200 dark:border-white/[0.06] space-y-1.5 text-xs font-mono">
            <div className="flex items-center justify-between">
              <span className="text-slate-500 dark:text-slate-400">Required Margin:</span>
              <span className="text-slate-900 dark:text-white font-bold">{formatINR(totalCost)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500 dark:text-slate-400">Available Virtual Demo Balance:</span>
              <span
                className={`font-bold ${hasEnoughFunds ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}
              >
                {formatINR(virtualBalance)}
              </span>
            </div>
          </div>

          {/* Feedback Message */}
          {feedback && (
            <div
              className={`p-3 rounded-xl border text-xs font-mono flex items-center gap-2 ${
                feedback.success
                  ? 'bg-emerald-50 dark:bg-emerald-500/15 border-emerald-200 dark:border-emerald-500/30 text-emerald-700 dark:text-emerald-300'
                  : 'bg-rose-50 dark:bg-rose-500/15 border-rose-200 dark:border-rose-500/30 text-rose-700 dark:text-rose-300'
              }`}
            >
              {feedback.success ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
              ) : (
                <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0" />
              )}
              <span>{feedback.message}</span>
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex items-center gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-white/[0.04] dark:hover:bg-white/[0.08] border border-slate-200 dark:border-white/[0.08] text-xs font-mono text-slate-700 dark:text-slate-300 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleExecute}
              disabled={!hasEnoughFunds}
              className="flex-1 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 dark:from-[#dfa759] dark:to-[#c89242] hover:opacity-95 text-xs font-mono font-bold text-white dark:text-black shadow-lg shadow-amber-500/15 transition-all disabled:opacity-40"
            >
              Execute Paper Trade
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};
