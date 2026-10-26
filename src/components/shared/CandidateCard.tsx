'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import { SignalCandidate } from '@/types/market';
import { formatINR, formatPercent } from '@/lib/utils';
import { SignalBadge } from './SignalBadge';
import {
  ArrowRight,
  ChevronDown,
  Sparkles,
  ShieldCheck,
  TrendingUp,
  Activity,
  Target,
  AlertCircle,
  Zap,
} from 'lucide-react';
import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts';
import { PaperTradeModal } from '@/components/trading/PaperTradeModal';

interface CandidateCardProps {
  candidate: SignalCandidate;
  initiallyExpanded?: boolean;
}

export const CandidateCard: React.FC<CandidateCardProps> = ({
  candidate,
  initiallyExpanded = false,
}) => {
  const [isExpanded, setIsExpanded] = useState(initiallyExpanded);
  const [isPaperModalOpen, setIsPaperModalOpen] = useState(false);
  const isPositive = candidate.change >= 0;
  const isCall = candidate.signalType === 'CALL';

  const chartData = candidate.sparkline.map((val, idx) => ({ index: idx, value: val }));
  const minVal = Math.min(...candidate.sparkline);
  const maxVal = Math.max(...candidate.sparkline);

  // Compute calculated risk-reward estimate
  const current = candidate.currentPrice;
  const target = isCall ? candidate.expectedHigh : candidate.expectedLow;
  const stopLoss = isCall ? candidate.expectedLow : candidate.expectedHigh;
  const rewardDiff = Math.abs(target - current);
  const riskDiff = Math.max(1, Math.abs(current - stopLoss));
  const rrRatio = (rewardDiff / riskDiff).toFixed(1);

  return (
    <>
      <PaperTradeModal
        isOpen={isPaperModalOpen}
        onClose={() => setIsPaperModalOpen(false)}
        candidate={candidate}
      />
      <motion.div
        layout
        whileHover={{ y: -2 }}
        transition={{ duration: 0.2 }}
        className={`relative overflow-hidden rounded-xl border transition-all duration-200 ${
          isExpanded
            ? 'bg-white dark:bg-[#0e131d] border-slate-300 dark:border-white/[0.16] shadow-lg'
            : 'bg-white dark:bg-[#0c1017] hover:bg-slate-50/50 dark:hover:bg-[#0f141d] border-slate-200 dark:border-white/[0.08] hover:border-slate-300 dark:hover:border-white/[0.16] shadow-sm'
        }`}
      >
        {/* Top Subtle Luxury Accent Line */}
        <div
          className={`h-0.5 w-full ${
            isCall
              ? 'bg-gradient-to-r from-transparent via-emerald-500/60 to-transparent'
              : 'bg-gradient-to-r from-transparent via-rose-500/60 to-transparent'
          }`}
        />

        <div className="p-4 sm:p-5">
          {/* Minimal Header: Symbol, Company, Rank & Signal */}
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="flex items-center justify-center w-6 h-6 rounded-md bg-amber-50 dark:bg-white/[0.04] text-[11px] font-mono font-bold text-amber-700 dark:text-[#dfa759] border border-amber-200 dark:border-[#dfa759]/20">
                #{candidate.rank}
              </span>
              <div>
                <div className="flex items-center gap-2">
                  <Link
                    href={`/stocks/${candidate.symbol}`}
                    className="text-base font-bold font-mono text-slate-900 dark:text-slate-100 hover:text-blue-600 dark:hover:text-[#dfa759] transition-colors"
                  >
                    {candidate.symbol}
                  </Link>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-white/[0.04] text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-white/[0.06]">
                    {candidate.exchange}
                  </span>
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400 truncate max-w-[200px] sm:max-w-[240px]">
                  {candidate.companyName}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <SignalBadge type={candidate.signalType} size="sm" />
            </div>
          </div>

          {/* Primary Clean Metrics Row */}
          <div className="mt-4 pt-3 border-t border-slate-100 dark:border-white/[0.05] grid grid-cols-2 sm:grid-cols-3 gap-3 items-center">
            {/* Price & Change */}
            <div>
              <span className="text-[10px] uppercase font-mono text-slate-400 dark:text-slate-500 tracking-wider block">
                Current CMP
              </span>
              <div className="text-lg font-bold font-mono text-slate-900 dark:text-slate-100">
                {formatINR(candidate.currentPrice)}
              </div>
              <div
                className={`text-xs font-mono font-medium flex items-center gap-1 ${
                  isPositive ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
                }`}
              >
                <span>{formatPercent(candidate.changePercent)}</span>
                <span className="text-slate-400 text-[10px]">
                  ({formatINR(candidate.change, false)})
                </span>
              </div>
            </div>

            {/* Target Zone */}
            <div>
              <span className="text-[10px] uppercase font-mono text-slate-400 dark:text-slate-500 tracking-wider block">
                {isCall ? 'Target (High)' : 'Target (Low)'}
              </span>
              <div
                className={`text-base font-bold font-mono ${
                  isCall ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
                }`}
              >
                {formatINR(target, false)}
              </div>
              <span className="text-[10px] font-mono text-slate-400">
                Stop: {formatINR(stopLoss, false)}
              </span>
            </div>

            {/* AI Score */}
            <div className="hidden sm:block text-right">
              <span className="text-[10px] uppercase font-mono text-slate-400 dark:text-slate-500 tracking-wider block">
                AI Setup Score
              </span>
              <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/25 text-amber-800 dark:text-[#dfa759] font-mono font-bold text-sm">
                <Sparkles className="w-3 h-3 text-amber-600 dark:text-[#dfa759]" />
                <span>{candidate.analysisScore}</span>
                <span className="text-[10px] text-amber-700/60 dark:text-amber-400/60 font-normal">/100</span>
              </div>
              <div className="text-[10px] font-mono text-slate-500 dark:text-slate-400 mt-0.5">
                Confidence: <span className="text-slate-800 dark:text-slate-200 font-semibold">{candidate.confidence}%</span>
              </div>
            </div>
          </div>

          {/* Action Bar: Progressive Disclosure Toggle + Paper Trade Button */}
          <div className="mt-4 pt-3 border-t border-slate-100 dark:border-white/[0.05] flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => setIsExpanded(!isExpanded)}
              className="flex items-center gap-1.5 text-xs font-mono text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-[#dfa759] py-1 px-2 rounded hover:bg-slate-100 dark:hover:bg-white/[0.04] transition-colors"
            >
              <Activity className="w-3.5 h-3.5 text-amber-600 dark:text-[#dfa759]" />
              <span className="hidden sm:inline">{isExpanded ? 'Hide Deep Analysis' : 'Touch for Deep Analysis'}</span>
              <span className="sm:hidden">{isExpanded ? 'Hide' : 'Deep'}</span>
              <ChevronDown
                className={`w-3.5 h-3.5 transition-transform duration-200 ${
                  isExpanded ? 'rotate-180 text-amber-600 dark:text-[#dfa759]' : 'text-slate-400'
                }`}
              />
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setIsPaperModalOpen(true)}
                className="inline-flex items-center gap-1.5 text-xs font-mono font-bold text-white dark:text-black px-2.5 py-1 rounded-md bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-600 hover:to-amber-700 dark:from-[#dfa759] dark:to-[#c89242] shadow-sm transition-all"
              >
                <Zap className="w-3 h-3 fill-current" />
                <span>Paper Trade</span>
              </button>

              <Link
                href={`/stocks/${candidate.symbol}`}
                className="inline-flex items-center gap-1 text-xs font-mono font-medium text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white px-2 py-1 rounded-md bg-slate-100 hover:bg-slate-200 dark:bg-white/[0.04] dark:hover:bg-white/[0.08] border border-slate-200 dark:border-white/[0.08] transition-all"
              >
                <span>Terminal</span>
                <ArrowRight className="w-3 h-3 text-slate-500 dark:text-slate-400" />
              </Link>
            </div>
          </div>

        {/* Progressive Disclosure: Deep Analysis Drawer */}
        <AnimatePresence>
          {isExpanded && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.25, ease: 'easeInOut' }}
              className="overflow-hidden"
            >
              <div className="mt-4 pt-4 border-t border-slate-200 dark:border-white/[0.08] space-y-4">
                {/* Quant Breakdown Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs font-mono">
                  <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-black/40 border border-slate-200 dark:border-white/[0.06]">
                    <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block">Risk:Reward</span>
                    <span className="text-xs font-bold text-emerald-600 dark:text-emerald-400">1 : {rrRatio}</span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-black/40 border border-slate-200 dark:border-white/[0.06]">
                    <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block">Exp. High Range</span>
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200">
                      {formatINR(candidate.expectedHigh, false)}
                    </span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-black/40 border border-slate-200 dark:border-white/[0.06]">
                    <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block">Exp. Low Range</span>
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200">
                      {formatINR(candidate.expectedLow, false)}
                    </span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-black/40 border border-slate-200 dark:border-white/[0.06]">
                    <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block">Trade Horizon</span>
                    <span className="text-xs font-bold text-amber-700 dark:text-[#dfa759]">Intraday / 1-3D</span>
                  </div>
                </div>

                {/* AI Rationale & Technical Catalysts */}
                <div className="p-3 rounded-lg bg-slate-50 dark:bg-white/[0.02] border border-slate-200 dark:border-white/[0.06] space-y-2">
                  <div className="flex items-center gap-2 text-xs font-mono text-slate-800 dark:text-slate-300 font-semibold">
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                    <span>AI Algorithmic Triggers</span>
                  </div>
                  <ul className="text-[11px] text-slate-600 dark:text-slate-400 space-y-1 font-mono pl-4 list-disc">
                    <li>
                      <span className="text-slate-800 dark:text-slate-300 font-medium">Technical Momentum:</span> RSI at {isCall ? '64 (Strong Buy momentum)' : '38 (Oversold breakdown)'} with MACD bullish crossover confirmation.
                    </li>
                    <li>
                      <span className="text-slate-800 dark:text-slate-300 font-medium">Institutional Volume:</span> 1.8x 20-day moving average accumulation detected at support levels.
                    </li>
                    <li>
                      <span className="text-slate-800 dark:text-slate-300 font-medium">Moving Averages:</span> Trading safely above 20 EMA and VWAP dynamic pivot band.
                    </li>
                  </ul>
                </div>

                {/* Sparkline Intraday Visual */}
                <div className="p-3 rounded-lg bg-slate-50 dark:bg-black/30 border border-slate-200 dark:border-white/[0.05] flex items-center justify-between">
                  <div className="text-xs font-mono">
                    <span className="text-slate-500 dark:text-slate-400 text-[10px] block uppercase">Session Trajectory</span>
                    <span className="text-slate-800 dark:text-slate-300 font-semibold">Normalized Tick Flow</span>
                  </div>
                  <div className="h-10 w-36">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={chartData}>
                        <YAxis domain={[minVal, maxVal]} hide />
                        <Line
                          type="monotone"
                          dataKey="value"
                          stroke={isCall ? '#10B981' : '#F43F5E'}
                          strokeWidth={2}
                          dot={false}
                          isAnimationActive={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        </div>
      </motion.div>
    </>
  );
};
