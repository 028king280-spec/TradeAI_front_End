'use client';

import React, { useState } from 'react';
import { 
  Flame, 
  Filter, 
  ArrowUp, 
  ArrowDown, 
  CheckCircle2, 
  AlertCircle, 
  Clock, 
  Eye, 
  ShieldCheck,
  TrendingUp,
  Sparkles
} from 'lucide-react';

export interface LiquidityLevelItem {
  id: string;
  type: string;                 // 'BSL', 'SSL', 'EQH', 'EQL', 'PDH', 'PDL', 'SESSION_HIGH', 'SESSION_LOW', etc.
  price: number;
  timeframe?: string;
  category: 'BSL' | 'SSL' | 'EQH_EQL' | 'SESSION' | 'SWEPT';
  status: 'IDENTIFIED' | 'SWEPT' | 'SWEPT_WITH_RECLAIM' | 'SWEPT_WITHOUT_RECLAIM' | 'BROKEN_OUT';
  strengthScore: number;        // 1 to 10
  clusterCount?: number;
  volumeRatio?: number;
  wickRejectionPct?: number;
  isExternal?: boolean;
  distancePts?: number;
}

interface LiquidityHeatmapPanelProps {
  levels?: LiquidityLevelItem[];
  currentPrice?: number;
  sweeps?: any[];
}

export const LiquidityHeatmapPanel: React.FC<LiquidityHeatmapPanelProps> = ({
  levels = [],
  currentPrice = 24500.0,
  sweeps = [],
}) => {
  const [activeFilter, setActiveFilter] = useState<'ALL' | 'BSL' | 'SSL' | 'EQH_EQL' | 'SWEPT'>('ALL');

  // Fallback sample pools if none provided yet from live stream
  const activeLevels: LiquidityLevelItem[] = levels.length > 0 ? levels : [
    {
      id: 'bsl-pdh',
      type: 'PDH (Previous Day High)',
      price: currentPrice + 85.0,
      category: 'BSL',
      status: 'IDENTIFIED',
      strengthScore: 9,
      clusterCount: 3,
      volumeRatio: 1.8,
      wickRejectionPct: 42,
      isExternal: true,
      distancePts: 85.0,
    },
    {
      id: 'eqh-int',
      type: 'Equal Highs (EQH Clustered)',
      price: currentPrice + 45.0,
      category: 'EQH_EQL',
      status: 'IDENTIFIED',
      strengthScore: 8,
      clusterCount: 2,
      volumeRatio: 1.4,
      wickRejectionPct: 35,
      isExternal: false,
      distancePts: 45.0,
    },
    {
      id: 'ssl-swp',
      type: 'SSL (Sell Side Liquidity)',
      price: currentPrice - 32.0,
      category: 'SWEPT',
      status: 'SWEPT_WITH_RECLAIM',
      strengthScore: 9,
      clusterCount: 2,
      volumeRatio: 2.1,
      wickRejectionPct: 58,
      isExternal: false,
      distancePts: -32.0,
    },
    {
      id: 'ssl-pdl',
      type: 'PDL (Previous Day Low)',
      price: currentPrice - 110.0,
      category: 'SSL',
      status: 'IDENTIFIED',
      strengthScore: 10,
      clusterCount: 4,
      volumeRatio: 2.4,
      wickRejectionPct: 50,
      isExternal: true,
      distancePts: -110.0,
    },
    {
      id: 'eql-int',
      type: 'Equal Lows (EQL Pool)',
      price: currentPrice - 65.0,
      category: 'EQH_EQL',
      status: 'IDENTIFIED',
      strengthScore: 7,
      clusterCount: 2,
      volumeRatio: 1.2,
      wickRejectionPct: 30,
      isExternal: false,
      distancePts: -65.0,
    },
  ];

  const filteredLevels = activeLevels.filter((lvl) => {
    if (activeFilter === 'ALL') return true;
    if (activeFilter === 'BSL') return lvl.category === 'BSL';
    if (activeFilter === 'SSL') return lvl.category === 'SSL';
    if (activeFilter === 'EQH_EQL') return lvl.category === 'EQH_EQL';
    if (activeFilter === 'SWEPT') return lvl.status.includes('SWEPT') || lvl.category === 'SWEPT';
    return true;
  });

  const getBadgeStyle = (category: string, status: string) => {
    if (status.includes('SWEPT')) {
      return {
        bg: 'bg-slate-700/40',
        text: 'text-slate-300',
        border: 'border-slate-600/40',
        pill: 'bg-slate-500/20 text-slate-300',
      };
    }
    if (category === 'BSL') {
      return {
        bg: 'bg-emerald-950/30',
        text: 'text-emerald-400',
        border: 'border-emerald-800/40',
        pill: 'bg-emerald-500/20 text-emerald-400',
      };
    }
    if (category === 'SSL') {
      return {
        bg: 'bg-rose-950/30',
        text: 'text-rose-400',
        border: 'border-rose-800/40',
        pill: 'bg-rose-500/20 text-rose-400',
      };
    }
    // EQH / EQL
    return {
      bg: 'bg-amber-950/30',
      text: 'text-amber-400',
      border: 'border-amber-800/40',
      pill: 'bg-amber-500/20 text-amber-400',
    };
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl text-slate-100">
      {/* Top Header & Color Taxonomy Legend */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-4 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-gradient-to-tr from-amber-600 to-rose-600 rounded-lg text-white shadow-lg shadow-amber-500/20">
            <Flame className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-white tracking-tight">
                Advanced Liquidity Detection & Heatmap Engine
              </h3>
              <span className="text-[10px] px-2 py-0.5 rounded font-black uppercase tracking-wider bg-amber-500/10 text-amber-400 border border-amber-500/20">
                Institutional Pools
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Tolerance-based clustering distinguishing institutional sweeps with reclaim from true breakouts
            </p>
          </div>
        </div>

        {/* Color Taxonomy Legend */}
        <div className="flex items-center gap-2 text-[11px] self-start md:self-auto flex-wrap">
          <span className="flex items-center gap-1 font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
            <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" /> BSL (Green)
          </span>
          <span className="flex items-center gap-1 font-semibold text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/20">
            <span className="w-2 h-2 rounded-full bg-rose-400 inline-block" /> SSL (Red)
          </span>
          <span className="flex items-center gap-1 font-semibold text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
            <span className="w-2 h-2 rounded-full bg-amber-400 inline-block" /> EQH/EQL (Yellow)
          </span>
          <span className="flex items-center gap-1 font-semibold text-slate-300 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">
            <span className="w-2 h-2 rounded-full bg-slate-400 inline-block" /> Swept (Grey)
          </span>
        </div>
      </div>

      {/* Filter Toggles */}
      <div className="mt-4 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-1.5">
          <Filter className="w-3.5 h-3.5 text-slate-400 mr-1" />
          {(['ALL', 'BSL', 'SSL', 'EQH_EQL', 'SWEPT'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveFilter(tab)}
              className={`px-3 py-1 text-xs font-semibold rounded-lg border transition ${
                activeFilter === tab
                  ? 'bg-slate-800 text-white border-slate-600 shadow-sm'
                  : 'bg-slate-950/40 text-slate-400 border-slate-800/80 hover:text-slate-200'
              }`}
            >
              {tab === 'ALL' ? 'All Pools' : tab === 'EQH_EQL' ? 'EQH / EQL' : tab}
            </button>
          ))}
        </div>

        <div className="text-xs text-slate-400">
          Current LTP: <strong className="text-white font-mono">₹{currentPrice.toLocaleString('en-IN')}</strong>
        </div>
      </div>

      {/* Liquidity Heatmap Grid / Ladder */}
      <div className="mt-4 space-y-2.5">
        {filteredLevels.map((lvl) => {
          const style = getBadgeStyle(lvl.category, lvl.status);
          const distance = lvl.distancePts !== undefined ? lvl.distancePts : (lvl.price - currentPrice);
          const isAbove = distance >= 0;

          return (
            <div
              key={lvl.id}
              className={`p-3.5 rounded-lg border transition hover:bg-slate-800/40 ${style.bg} ${style.border} flex flex-col sm:flex-row sm:items-center justify-between gap-3`}
            >
              <div className="flex items-start sm:items-center gap-3">
                <div className={`p-2 rounded-lg font-bold shrink-0 ${style.pill}`}>
                  {isAbove ? <ArrowUp className="w-4 h-4" /> : <ArrowDown className="w-4 h-4" />}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-white">{lvl.type}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-black uppercase tracking-wider ${style.pill}`}>
                      {lvl.status.replace(/_/g, ' ')}
                    </span>
                    {lvl.isExternal && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-semibold">
                        External
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-slate-400 mt-1">
                    <span>
                      Strength:{' '}
                      <strong className="text-white font-mono">{lvl.strengthScore}/10</strong>
                    </span>
                    {lvl.clusterCount && lvl.clusterCount > 1 && (
                      <span>
                        Cluster: <strong className="text-slate-200">{lvl.clusterCount} Points</strong>
                      </span>
                    )}
                    {lvl.volumeRatio && (
                      <span>
                        Vol Ratio: <strong className="text-slate-200">{lvl.volumeRatio}x</strong>
                      </span>
                    )}
                    {lvl.wickRejectionPct && (
                      <span>
                        Wick Rejection: <strong className="text-slate-200">{lvl.wickRejectionPct}%</strong>
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Price & Dealing Distance */}
              <div className="text-right sm:self-auto self-end">
                <div className="text-base font-black text-white font-mono">
                  ₹{lvl.price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </div>
                <div className={`text-xs font-semibold ${isAbove ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {isAbove ? `+${distance.toFixed(1)} pts away` : `${distance.toFixed(1)} pts away`}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Sweep vs True Breakout Validation Note */}
      <div className="mt-4 p-3 bg-slate-950/60 border border-slate-800 rounded-lg text-xs text-slate-400 flex items-start gap-2">
        <Sparkles className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          <strong className="text-slate-200">Institutional Validation Rule:</strong> A valid liquidity sweep requires a wick extending beyond the pool followed by a rapid candle body reclaim inside the dealing range and displacement confirmation. Wicks without reclaim are classified as continuous expansion breakouts, preventing premature reversal traps.
        </p>
      </div>
    </div>
  );
};

