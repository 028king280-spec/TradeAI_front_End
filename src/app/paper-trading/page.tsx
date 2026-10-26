'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Zap,
  TrendingUp,
  TrendingDown,
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  ArrowUpRight,
  ArrowDownRight,
  ShieldCheck,
  Award,
  Wallet,
  Clock,
  History,
  Info,
} from 'lucide-react';
import { usePaperTrading } from '@/context/PaperTradingContext';
import { formatINR, formatPercent } from '@/lib/utils';
import { SignalBadge } from '@/components/shared/SignalBadge';

export default function PaperTradingPage() {
  const {
    virtualBalance,
    initialCapital,
    positions,
    history,
    squareOffPosition,
    resetPortfolio,
  } = usePaperTrading();

  const [confirmReset, setConfirmReset] = useState(false);
  const [activeTab, setActiveTab] = useState<'POSITIONS' | 'HISTORY'>('POSITIONS');

  // Calculate portfolio totals
  const totalInvested = positions.reduce((acc, p) => acc + p.investedAmount, 0);
  const totalUnrealizedPnl = positions.reduce((acc, p) => acc + p.pnl, 0);
  const totalRealizedPnl = history.reduce((acc, h) => acc + h.realizedPnl, 0);
  const portfolioNetWorth = virtualBalance + totalInvested + totalUnrealizedPnl;

  const totalClosedTrades = history.length;
  const winningTrades = history.filter((h) => h.realizedPnl > 0).length;
  const winRate =
    totalClosedTrades > 0 ? ((winningTrades / totalClosedTrades) * 100).toFixed(1) : '100.0';

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-white/[0.07]">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/25 flex items-center justify-center">
              <Zap className="w-4 h-4 text-[#dfa759]" />
            </div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-white font-mono flex items-center gap-2">
              <span>Virtual Paper Trading</span>
              <span className="text-[11px] font-normal px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/25 text-[#dfa759]">
                ₹10L Demo Capital
              </span>
            </h1>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Test AI stock suggestions and track accuracy with zero financial risk.
          </p>
        </div>

        {/* Reset & Quick Action */}
        <div className="flex items-center gap-3">
          {confirmReset ? (
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-rose-400">Reset to ₹10L?</span>
              <button
                type="button"
                onClick={() => {
                  resetPortfolio();
                  setConfirmReset(false);
                }}
                className="px-2.5 py-1 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 text-xs font-mono border border-rose-500/40 transition-colors"
              >
                Yes, Reset
              </button>
              <button
                type="button"
                onClick={() => setConfirmReset(false)}
                className="px-2 py-1 rounded bg-white/[0.05] text-slate-300 text-xs font-mono"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmReset(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-xs font-mono text-slate-300 transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Reset Capital</span>
            </button>
          )}

          <Link
            href="/"
            className="px-3 py-1.5 rounded-lg bg-[#dfa759]/10 hover:bg-[#dfa759]/20 border border-[#dfa759]/30 text-[#dfa759] text-xs font-mono transition-all"
          >
            + Browse Setups
          </Link>
        </div>
      </div>

      {/* Advisory Notice Banner */}
      <div className="p-3.5 rounded-xl bg-amber-50 dark:bg-amber-500/[0.05] border border-amber-200 dark:border-amber-500/20 flex items-center justify-between text-xs font-mono text-slate-700 dark:text-slate-300">
        <div className="flex items-center gap-2.5">
          <Info className="w-4 h-4 text-amber-600 dark:text-[#dfa759] shrink-0" />
          <span>
            <strong className="text-amber-800 dark:text-[#dfa759]">Pure AI Suggestion Model:</strong> We provide algorithmic trade suggestions. Use this virtual simulator to verify setup accuracy before making personal market decisions.
          </span>
        </div>
        <span className="hidden sm:inline text-[10px] text-slate-500 dark:text-slate-400">
          NSE / BSE Feeds
        </span>
      </div>

      {/* Executive Portfolio KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {/* Net Worth */}
        <div className="p-4 rounded-xl bg-white dark:bg-[#0c1017]/90 border border-slate-200 dark:border-white/[0.08] shadow-sm space-y-1">
          <div className="flex items-center justify-between text-xs font-mono text-slate-500 dark:text-slate-400">
            <span>Total Net Worth</span>
            <Wallet className="w-3.5 h-3.5 text-amber-600 dark:text-[#dfa759]" />
          </div>
          <div className="text-xl font-bold font-mono text-slate-900 dark:text-white">
            {formatINR(portfolioNetWorth)}
          </div>
          <div
            className={`text-xs font-mono flex items-center gap-1 ${
              portfolioNetWorth >= initialCapital ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
            }`}
          >
            {portfolioNetWorth >= initialCapital ? (
              <ArrowUpRight className="w-3.5 h-3.5" />
            ) : (
              <ArrowDownRight className="w-3.5 h-3.5" />
            )}
            <span>
              {formatPercent(((portfolioNetWorth - initialCapital) / initialCapital) * 100)}
            </span>
            <span className="text-slate-400 dark:text-slate-500 text-[10px]">(All-time)</span>
          </div>
        </div>

        {/* Available Virtual Cash */}
        <div className="p-4 rounded-xl bg-white dark:bg-[#0c1017]/90 border border-slate-200 dark:border-white/[0.08] shadow-sm space-y-1">
          <div className="flex items-center justify-between text-xs font-mono text-slate-500 dark:text-slate-400">
            <span>Available Cash</span>
            <span className="text-[10px] text-slate-400 dark:text-slate-500">Unallocated</span>
          </div>
          <div className="text-xl font-bold font-mono text-slate-900 dark:text-slate-200">
            {formatINR(virtualBalance)}
          </div>
          <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400">
            Invested: {formatINR(totalInvested)}
          </div>
        </div>

        {/* Realized P&L */}
        <div className="p-4 rounded-xl bg-white dark:bg-[#0c1017]/90 border border-slate-200 dark:border-white/[0.08] shadow-sm space-y-1">
          <div className="flex items-center justify-between text-xs font-mono text-slate-500 dark:text-slate-400">
            <span>Realized P&L</span>
            <span className="text-[10px] text-slate-400 dark:text-slate-500">{totalClosedTrades} trades</span>
          </div>
          <div
            className={`text-xl font-bold font-mono ${
              totalRealizedPnl >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
            }`}
          >
            {totalRealizedPnl >= 0 ? '+' : ''}
            {formatINR(totalRealizedPnl)}
          </div>
          <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400">
            Unrealized: <span className="text-emerald-600 dark:text-emerald-400">+{formatINR(totalUnrealizedPnl)}</span>
          </div>
        </div>

        {/* AI Win Rate */}
        <div className="p-4 rounded-xl bg-white dark:bg-[#0c1017]/90 border border-slate-200 dark:border-white/[0.08] shadow-sm space-y-1">
          <div className="flex items-center justify-between text-xs font-mono text-slate-500 dark:text-slate-400">
            <span>AI Suggestion Win Rate</span>
            <Award className="w-3.5 h-3.5 text-amber-600 dark:text-[#dfa759]" />
          </div>
          <div className="text-xl font-bold font-mono text-amber-700 dark:text-[#dfa759]">
            {winRate}%
          </div>
          <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400">
            {winningTrades} Won / {totalClosedTrades} Completed
          </div>
        </div>
      </div>

      {/* Tabs: Active Positions vs Closed History */}
      <div className="rounded-xl border border-slate-200 dark:border-white/[0.08] bg-white dark:bg-[#0c1017]/90 p-4 sm:p-5 space-y-4 shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-100 dark:border-white/[0.06] pb-3">
          <div className="flex items-center gap-2 text-xs font-mono">
            <button
              onClick={() => setActiveTab('POSITIONS')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                activeTab === 'POSITIONS'
                  ? 'bg-slate-100 dark:bg-white/[0.08] text-slate-900 dark:text-white border border-slate-200 dark:border-white/[0.12] font-bold shadow-sm'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              Active Tested Positions ({positions.length})
            </button>
            <button
              onClick={() => setActiveTab('HISTORY')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                activeTab === 'HISTORY'
                  ? 'bg-slate-100 dark:bg-white/[0.08] text-slate-900 dark:text-white border border-slate-200 dark:border-white/[0.12] font-bold shadow-sm'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              Completed Trades History ({history.length})
            </button>
          </div>

          <span className="text-[11px] font-mono text-slate-500 dark:text-slate-400">
            Mark-to-Market Realtime
          </span>
        </div>

        {/* Active Positions Table */}
        {activeTab === 'POSITIONS' && (
          <div>
            {positions.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs font-mono">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-white/[0.06] text-slate-500 dark:text-slate-400 text-[10px] uppercase">
                      <th className="pb-2.5">Instrument</th>
                      <th className="pb-2.5">Signal</th>
                      <th className="pb-2.5">Entry CMP</th>
                      <th className="pb-2.5">Current</th>
                      <th className="pb-2.5">Qty / Invested</th>
                      <th className="pb-2.5">Target / Stop</th>
                      <th className="pb-2.5">Unrealized P&L</th>
                      <th className="pb-2.5 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-white/[0.04]">
                    {positions.map((pos) => {
                      const isPos = pos.pnl >= 0;
                      return (
                        <tr key={pos.id} className="hover:bg-slate-50/70 dark:hover:bg-white/[0.02] transition-colors">
                          <td className="py-3">
                            <Link
                              href={`/stocks/${pos.symbol}`}
                              className="font-bold text-slate-900 dark:text-white hover:text-blue-600 dark:hover:text-[#dfa759]"
                            >
                              {pos.symbol}
                            </Link>
                            <span className="text-[10px] text-slate-500 dark:text-slate-400 block truncate max-w-[140px]">
                              {pos.companyName}
                            </span>
                          </td>
                          <td className="py-3">
                            <SignalBadge type={pos.signalType} size="sm" />
                          </td>
                          <td className="py-3 text-slate-700 dark:text-slate-200">
                            {formatINR(pos.entryPrice)}
                          </td>
                          <td className="py-3 text-slate-900 dark:text-white font-bold">
                            {formatINR(pos.currentPrice)}
                          </td>
                          <td className="py-3 text-slate-700 dark:text-slate-300">
                            <div>{pos.quantity} shares</div>
                            <div className="text-[10px] text-slate-500 dark:text-slate-400">
                              {formatINR(pos.investedAmount)}
                            </div>
                          </td>
                          <td className="py-3 text-[11px]">
                            <div className="text-emerald-600 dark:text-emerald-400">Tgt: {formatINR(pos.targetPrice, false)}</div>
                            <div className="text-slate-500 dark:text-slate-400">SL: {formatINR(pos.stopLossPrice, false)}</div>
                          </td>
                          <td className="py-3">
                            <div className={`font-bold ${isPos ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
                              {isPos ? '+' : ''}{formatINR(pos.pnl)}
                            </div>
                            <div className={`text-[10px] ${isPos ? 'text-emerald-600/80 dark:text-emerald-400/80' : 'text-rose-600/80 dark:text-rose-400/80'}`}>
                              ({formatPercent(pos.pnlPercent)})
                            </div>
                          </td>
                          <td className="py-3 text-right">
                            <button
                              type="button"
                              onClick={() => squareOffPosition(pos.id, pos.currentPrice, 'Manual Square Off')}
                              className="px-2.5 py-1 rounded-md bg-rose-50 hover:bg-rose-100 dark:bg-rose-500/10 dark:hover:bg-rose-500/20 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-500/25 transition-colors"
                            >
                              Square Off
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-center py-10 space-y-2">
                <p className="text-xs font-mono text-slate-500 dark:text-slate-400">
                  No active paper trades right now.
                </p>
                <Link
                  href="/"
                  className="inline-block px-3 py-1.5 rounded-lg bg-amber-50 hover:bg-amber-100 dark:bg-[#dfa759]/10 text-amber-800 dark:text-[#dfa759] border border-amber-200 dark:border-[#dfa759]/30 text-xs font-mono transition-colors"
                >
                  Explore Today&apos;s AI Setups →
                </Link>
              </div>
            )}
          </div>
        )}

        {/* History Table */}
        {activeTab === 'HISTORY' && (
          <div>
            {history.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs font-mono">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-white/[0.06] text-slate-500 dark:text-slate-400 text-[10px] uppercase">
                      <th className="pb-2.5">Instrument</th>
                      <th className="pb-2.5">Side</th>
                      <th className="pb-2.5">Entry</th>
                      <th className="pb-2.5">Exit</th>
                      <th className="pb-2.5">Qty</th>
                      <th className="pb-2.5">Realized P&L</th>
                      <th className="pb-2.5">Exit Reason</th>
                      <th className="pb-2.5 text-right">Closed At</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-white/[0.04]">
                    {history.map((h) => {
                      const isProfit = h.realizedPnl >= 0;
                      return (
                        <tr key={h.id} className="hover:bg-slate-50/70 dark:hover:bg-white/[0.02] transition-colors">
                          <td className="py-3 font-bold text-slate-900 dark:text-white">{h.symbol}</td>
                          <td className="py-3">
                            <SignalBadge type={h.signalType} size="sm" />
                          </td>
                          <td className="py-3 text-slate-700 dark:text-slate-300">{formatINR(h.entryPrice)}</td>
                          <td className="py-3 text-slate-900 dark:text-slate-200">{formatINR(h.exitPrice)}</td>
                          <td className="py-3 text-slate-500 dark:text-slate-400">{h.quantity}</td>
                          <td className="py-3">
                            <span
                              className={`font-bold ${
                                isProfit ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
                              }`}
                            >
                              {isProfit ? '+' : ''}{formatINR(h.realizedPnl)} ({formatPercent(h.realizedPnlPercent)})
                            </span>
                          </td>
                          <td className="py-3">
                            <span className="px-2 py-0.5 rounded bg-slate-100 dark:bg-white/[0.04] text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-white/[0.06] text-[10px]">
                              {h.exitReason}
                            </span>
                          </td>
                          <td className="py-3 text-right text-slate-500 dark:text-slate-400 text-[11px]">
                            {h.closedAt}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-center py-10 text-xs font-mono text-slate-500 dark:text-slate-400">
                No completed paper trade history yet.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
