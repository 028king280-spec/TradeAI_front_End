'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Zap, CheckCircle2, AlertCircle } from 'lucide-react';
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
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[var(--bg-surface-elevated)] dark:bg-black/80 backdrop-blur-sm">
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 15 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 15 }}
          transition={{ duration: 0.2 }}
          className="relative w-full max-w-lg rounded-2xl bg-[var(--bg-surface)] dark:bg-[var(--bg-surface)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] shadow-2xl overflow-hidden p-6 space-y-5"
        >
          {/* Top Header */}
          <div className="flex items-center justify-between border-b border-[var(--border-subtle)] dark:border-[var(--border-subtle)] pb-3">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/25 flex items-center justify-center">
                <Zap className="w-4 h-4 text-amber-600 dark:text-[#dfa759]" />
              </div>
              <div>
                <h3 className="text-sm font-semibold tabular-nums text-[var(--text-primary)] dark:text-[var(--text-primary)] flex items-center gap-2">
                  <span>Paper Trade Suggestion</span>
                  <span className="text-[10px] font-normal px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-transparent tabular-nums">
                    Zero Risk
                  </span>
                </h3>
                <p className="text-xs text-[var(--text-muted)] dark:text-[var(--text-secondary)]">
                  Simulate this AI setup using virtual demo capital.
                </p>
              </div>
            </div>

            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-[var(--bg-surface-elevated)] dark:hover:bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] hover:text-[var(--text-secondary)] dark:hover:text-[var(--text-primary)] transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Stock Details & Signal */}
          <div className="p-3.5 rounded-xl bg-[var(--bg-surface-elevated)] dark:bg-black/40 border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-semibold tabular-nums text-[var(--text-primary)] dark:text-[var(--text-primary)]">
                  {candidate.symbol}
                </span>
                <SignalBadge type={candidate.signalType} size="sm" />
              </div>
              <p className="text-xs text-[var(--text-muted)] dark:text-[var(--text-secondary)]">{candidate.companyName}</p>
            </div>

            <div className="text-right tabular-nums">
              <span className="text-[10px] text-[var(--text-muted)] dark:text-[var(--text-secondary)] uppercase block">CMP Price</span>
              <span className="text-base font-semibold text-[var(--text-primary)] dark:text-[var(--text-primary)]">
                {formatINR(candidate.currentPrice)}
              </span>
            </div>
          </div>

          {/* Target, SL and AI Score info */}
          <div className="grid grid-cols-3 gap-2.5 text-xs tabular-nums">
            <div className="p-2.5 rounded-lg bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
              <span className="text-[10px] text-[var(--text-muted)] dark:text-[var(--text-secondary)] uppercase block">AI Target</span>
              <span
                className={`font-bold ${isCall ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}
              >
                {formatINR(target, false)}
              </span>
            </div>
            <div className="p-2.5 rounded-lg bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
              <span className="text-[10px] text-[var(--text-muted)] dark:text-[var(--text-secondary)] uppercase block">Stop Loss</span>
              <span className="text-[var(--text-primary)] dark:text-[var(--text-secondary)] font-semibold">{formatINR(stopLoss, false)}</span>
            </div>
            <div className="p-2.5 rounded-lg bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
              <span className="text-[10px] text-[var(--text-muted)] dark:text-[var(--text-secondary)] uppercase block">AI Score</span>
              <span className="text-amber-700 dark:text-[#dfa759] font-semibold">
                {candidate.analysisScore} / 100
              </span>
            </div>
          </div>

          {/* Quantity Selector */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs tabular-nums text-[var(--text-secondary)] dark:text-[var(--text-secondary)]">
              <span>Order Quantity:</span>
              <span className="text-amber-700 dark:text-[#dfa759] font-semibold">{quantity} shares</span>
            </div>

            <div className="flex items-center gap-2">
              {[25, 50, 100, 200, 500].map((qty) => (
                <button
                  key={qty}
                  type="button"
                  onClick={() => setQuantity(qty)}
                  className={`flex-1 py-1.5 rounded-lg text-xs tabular-nums transition-all ${
                    quantity === qty
                      ? 'bg-amber-500 dark:bg-[#dfa759] text-[var(--text-primary)] dark:text-black font-semibold shadow'
                      : 'bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] dark:hover:bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] dark:text-[var(--text-secondary)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)]'
                  }`}
                >
                  {qty}
                </button>
              ))}
            </div>
          </div>

          {/* Margin & Available Funds */}
          <div className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] space-y-1.5 text-xs tabular-nums">
            <div className="flex items-center justify-between">
              <span className="text-[var(--text-muted)] dark:text-[var(--text-secondary)]">Required Margin:</span>
              <span className="text-[var(--text-primary)] dark:text-[var(--text-primary)] font-semibold">{formatINR(totalCost)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[var(--text-muted)] dark:text-[var(--text-secondary)]">Available Virtual Demo Balance:</span>
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
              className={`p-3 rounded-xl border text-xs tabular-nums flex items-center gap-2 ${
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
              className="flex-1 py-2 rounded-xl bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] dark:hover:bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] text-xs tabular-nums text-[var(--text-secondary)] dark:text-[var(--text-secondary)] transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleExecute}
              disabled={!hasEnoughFunds}
              className="flex-1 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 dark:from-[#dfa759] dark:to-[#c89242] hover:opacity-95 text-xs tabular-nums font-semibold text-[var(--text-primary)] dark:text-black shadow-lg shadow-amber-500/15 transition-all disabled:opacity-40"
            >
              Execute Paper Trade
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};
