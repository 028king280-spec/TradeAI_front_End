'use client';

import React, { useEffect, useState } from 'react';
import { NextSessionBacktestResult } from '@/types/options';
import { optionsService } from '@/services/optionsService';
import {
  X,
  BarChart3,
  TrendingUp,
  Percent,
  Shield,
  Layers,
  AlertCircle,
  Clock,
  ArrowUpRight,
  Flame,
  CheckCircle2,
  RefreshCw,
} from 'lucide-react';

interface NextSessionBacktestModalProps {
  isOpen: boolean;
  onClose: () => void;
  symbol: string;
}

export const NextSessionBacktestModal: React.FC<NextSessionBacktestModalProps> = ({
  isOpen,
  onClose,
  symbol,
}) => {
  const [data, setData] = useState<NextSessionBacktestResult | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [lookback, setLookback] = useState<number>(60);

  const fetchBacktest = async () => {
    setLoading(true);
    try {
      const res = await optionsService.getNextSessionBacktest(symbol, lookback);
      if (res) {
        setData(res);
      }
    } catch (e) {
      console.error('Failed to load backtest:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchBacktest();
    }
  }, [isOpen, symbol, lookback]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-in fade-in">
      {/* High-Contrast Bloomberg Terminal Card */}
      <div className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-700/80 bg-[#0c1017] text-slate-100 p-6 space-y-5 shadow-2xl font-mono">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="w-10 h-10 rounded-xl bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center">
              <BarChart3 className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-white tracking-wide">
                  HISTORICAL VALIDATION & OUT-OF-SAMPLE BACKTEST
                </h2>
                <span className="text-xs px-2.5 py-0.5 rounded-full bg-indigo-500/25 border border-indigo-500/40 text-indigo-300 font-extrabold">
                  {symbol}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5 font-medium">
                Walk-forward chronological simulation • Zero Lookahead Bias
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Lookback Selector */}
            <div className="flex items-center gap-2 text-xs">
              <span className="text-slate-300 font-semibold">Sessions:</span>
              <select
                value={lookback}
                onChange={(e) => setLookback(Number(e.target.value))}
                className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-white text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value={30}>30 Sessions</option>
                <option value={60}>60 Sessions</option>
                <option value={90}>90 Sessions</option>
                <option value={120}>120 Sessions</option>
              </select>
            </div>

            <button
              onClick={onClose}
              className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors border border-slate-700"
              title="Close modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {loading ? (
          <div className="py-16 text-center space-y-3">
            <RefreshCw className="w-8 h-8 text-indigo-400 animate-spin mx-auto" />
            <p className="text-xs text-slate-300 font-semibold">
              Computing out-of-sample forward simulations with slippage and exchange fees...
            </p>
          </div>
        ) : !data ? (
          <div className="py-12 text-center text-xs text-slate-400 font-medium">
            Backtest data unavailable for selected parameters.
          </div>
        ) : (
          <div className="space-y-5">
            {/* Top Metrics Row */}
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
              <div className="p-3.5 rounded-xl border border-slate-800 bg-[#121824] shadow-xs space-y-1">
                <span className="text-[11px] text-slate-300 font-bold block">Directional Accuracy</span>
                <span className="text-xl font-extrabold text-emerald-400 block">
                  {data.metrics.openingGapDirectionalAccuracy}
                </span>
                <span className="text-[10px] text-slate-400 font-medium block">Gap forecast match</span>
              </div>

              <div className="p-3.5 rounded-xl border border-slate-800 bg-[#121824] shadow-xs space-y-1">
                <span className="text-[11px] text-slate-300 font-bold block">Range Forecast MAE</span>
                <span className="text-xl font-extrabold text-sky-400 block">
                  {data.metrics.openingRangeForecastMAE}
                </span>
                <span className="text-[10px] text-slate-400 font-medium block">Mean absolute error</span>
              </div>

              <div className="p-3.5 rounded-xl border border-slate-800 bg-[#121824] shadow-xs space-y-1">
                <span className="text-[11px] text-slate-300 font-bold block">Strategy Win Rate</span>
                <span className="text-xl font-extrabold text-emerald-400 block">
                  {data.metrics.winRate}
                </span>
                <span className="text-[10px] text-slate-300 font-semibold block">
                  {data.metrics.winningTrades}W / {data.metrics.losingTrades}L
                </span>
              </div>

              <div className="p-3.5 rounded-xl border border-slate-800 bg-[#121824] shadow-xs space-y-1">
                <span className="text-[11px] text-slate-300 font-bold block">Profit Factor</span>
                <span className="text-xl font-extrabold text-emerald-400 block">
                  {data.metrics.profitFactor}
                </span>
                <span className="text-[10px] text-slate-400 font-medium block">Gross Win / Loss</span>
              </div>

              <div className="p-3.5 rounded-xl border border-slate-800 bg-[#121824] shadow-xs space-y-1">
                <span className="text-[11px] text-slate-300 font-bold block">Expectancy</span>
                <span className="text-xl font-extrabold text-indigo-400 block">
                  {data.metrics.expectancyRMultiple}
                </span>
                <span className="text-[10px] text-slate-400 font-medium block">Avg R-Multiple</span>
              </div>

              <div className="p-3.5 rounded-xl border border-slate-800 bg-[#121824] shadow-xs space-y-1">
                <span className="text-[11px] text-slate-300 font-bold block">No-Trade Preserved</span>
                <span className="text-xl font-extrabold text-amber-400 block">
                  {data.metrics.noTradePreservedSessions}
                </span>
                <span className="text-[10px] text-slate-400 font-medium block">Capital saved</span>
              </div>
            </div>

            {/* Financial Performance: Net PnL & Max Drawdown */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              <div className="p-4 rounded-xl border border-emerald-500/40 bg-emerald-950/25 space-y-1.5 shadow-xs">
                <span className="text-xs font-bold text-emerald-300 uppercase tracking-wide">
                  Net Simulated P&L (After Costs & Slippage)
                </span>
                <div className="text-2xl sm:text-3xl font-extrabold text-emerald-400">
                  {data.metrics.netPnLINR}
                </div>
                <div className="text-[11px] text-slate-300 font-medium">
                  Simulated on 1 lot allocation per qualified setup over {data.samplePeriodSessions} trading sessions.
                </div>
              </div>

              <div className="p-4 rounded-xl border border-rose-500/40 bg-rose-950/25 space-y-1.5 shadow-xs">
                <span className="text-xs font-bold text-rose-300 uppercase tracking-wide">
                  Maximum Strategy Drawdown
                </span>
                <div className="text-2xl sm:text-3xl font-extrabold text-rose-400">
                  {data.metrics.maxDrawdownINR}
                </div>
                <div className="text-[11px] text-slate-300 font-medium">
                  Peak-to-trough equity drop under consecutive stop-loss executions.
                </div>
              </div>
            </div>

            {/* Realistic Friction & Assumptions */}
            <div className="rounded-xl border border-slate-800 bg-[#121824] p-4 space-y-3">
              <span className="text-xs font-bold text-slate-200 flex items-center gap-2">
                <Shield className="w-4 h-4 text-indigo-400" />
                Zero-Lookahead Backtest Friction Assumptions
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-750 shadow-xs space-y-1">
                  <span className="text-[11px] font-bold text-slate-300 block">Exchange Brokerage</span>
                  <span className="text-sm font-extrabold text-white block">{data.frictionAssumptions.brokeragePerRoundtrip}</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-750 shadow-xs space-y-1">
                  <span className="text-[11px] font-bold text-slate-300 block">Execution Slippage</span>
                  <span className="text-sm font-extrabold text-white block">{data.frictionAssumptions.slippagePerTrade}</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-750 shadow-xs space-y-1">
                  <span className="text-[11px] font-bold text-slate-300 block">Standard Lot Size</span>
                  <span className="text-sm font-extrabold text-white block">{data.frictionAssumptions.lotSize} qty</span>
                </div>
              </div>
            </div>

            {/* Performance Across Volatility Regimes */}
            <div className="space-y-2.5">
              <span className="text-xs font-bold text-slate-200 flex items-center gap-2">
                <Flame className="w-4 h-4 text-amber-400" />
                Performance Across Volatility Regimes (India VIX)
              </span>
              <div className="overflow-x-auto rounded-xl border border-slate-800 shadow-xs">
                <table className="w-full text-xs text-left">
                  <thead className="bg-[#172033] text-slate-200 border-b border-slate-700 font-bold">
                    <tr>
                      <th className="p-3">Volatility Regime</th>
                      <th className="p-3">Win Rate</th>
                      <th className="p-3">Sample Trades</th>
                      <th className="p-3">Expectancy (R)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800 bg-[#0f141d]">
                    {data.volatilityRegimePerformance?.map((v, idx) => (
                      <tr key={idx} className="hover:bg-slate-800/60 transition-colors">
                        <td className="p-3 font-bold text-white">{v.regime}</td>
                        <td className="p-3 text-emerald-400 font-extrabold">{v.winRate}</td>
                        <td className="p-3 text-slate-300 font-bold">{v.trades}</td>
                        <td className="p-3 font-extrabold text-indigo-400">{v.expectancy}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Out of sample Disclaimer */}
            <div className="p-3.5 rounded-xl bg-amber-950/30 border border-amber-500/40 text-[11px] text-amber-200 leading-relaxed flex items-start gap-2.5">
              <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <strong className="text-amber-300 font-bold">Methodology & Risk Disclaimer: </strong>
                {data.disclaimer}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
