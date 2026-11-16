'use client';

import React, { useState } from 'react';
import { SmcAnalysisData } from '@/types/options';
import {
  Target,
  Shield,
  ArrowUpRight,
  ArrowDownRight,
  Layers,
  Crosshair,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Sparkles,
  BarChart3,
  Activity,
  Flame,
  ChevronRight,
  Zap,
} from 'lucide-react';
import { AIMarketReportModal } from './AIMarketReportModal';
import { MultiTimeframePanel } from './MultiTimeframePanel';
import { LiquidityHeatmapPanel } from './LiquidityHeatmapPanel';

interface SmartMoneyConceptsCardProps {
  data?: SmcAnalysisData;
}

export const SmartMoneyConceptsCard: React.FC<SmartMoneyConceptsCardProps> = ({ data }) => {
  const [activeTab, setActiveTab] = useState<'OVERVIEW' | 'MTF' | 'STRUCTURE' | 'LIQUIDITY' | 'ZONES' | 'SCORECARD'>('OVERVIEW');
  const [isReportOpen, setIsReportOpen] = useState(false);

  if (!data || !data.dealingRange) {
    return null;
  }

  const { dealingRange, liquidityPools, recentSweeps, fairValueGaps, orderBlocks, executionModels, advancedIct } = data;
  const isPremium = dealingRange.regime === 'PREMIUM';
  const isDiscount = dealingRange.regime === 'DISCOUNT';

  const activeModel = executionModels?.activeSetup || executionModels?.modelA || executionModels?.modelB || executionModels?.modelC;

  const structure = advancedIct?.structure;
  const liquidityAdv = advancedIct?.liquidity;
  const fvgObAdv = advancedIct?.fvgAndOrderBlocks;
  const scorecard = advancedIct?.scorecard;
  const reportText = advancedIct?.aiReport?.reportText;

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-5 space-y-5 font-mono shadow-sm">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
            <Crosshair className="w-4 h-4 text-blue-500" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
                ADVANCED ICT + SMC ORDER FLOW ENGINE
              </h3>
              <span
                className={`text-[10px] px-2 py-0.5 rounded-full font-extrabold ${
                  isDiscount
                    ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30'
                    : isPremium
                    ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30'
                    : 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30'
                }`}
              >
                {dealingRange.regime} ZONE ({dealingRange.currentPositionPct}%)
              </span>
            </div>
            <span className="text-[10px] text-[var(--text-muted)]">
              Multi-Timeframe Structure • Liquidity Sweeps & Reclaim • FVG 50% CE • 100-Pt Scorecard
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {reportText && (
            <button
              onClick={() => setIsReportOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white shadow-sm transition-all"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>15-Pt AI Report</span>
            </button>
          )}

          <div className="text-right text-[11px] text-[var(--text-muted)] hidden sm:block">
            <span>50% Eq: </span>
            <strong className="text-[var(--text-primary)]">₹{dealingRange.equilibrium?.toLocaleString('en-IN') ?? '--'}</strong>
          </div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex items-center gap-1.5 p-1 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] overflow-x-auto">
        {[
          { id: 'OVERVIEW', label: 'Execution & Range', icon: Crosshair },
          { id: 'MTF', label: 'Multi-Timeframe Confluence', icon: Clock },
          { id: 'STRUCTURE', label: 'Market Structure (HH/LL/BOS)', icon: Activity },
          { id: 'LIQUIDITY', label: 'Liquidity & Heatmap', icon: Layers },
          { id: 'ZONES', label: 'FVG & Order Blocks', icon: Flame },
          { id: 'SCORECARD', label: '100-Pt Scorecard', icon: Shield },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all whitespace-nowrap ${
                isActive
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface)]'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* TAB 1: OVERVIEW & DEALING RANGE */}
      {activeTab === 'OVERVIEW' && (
        <div className="space-y-4">
          {/* Dealing Range Visual Bar */}
          <div className="space-y-2 p-3.5 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-emerald-500 font-bold flex items-center gap-1">
                <ArrowDownRight className="w-3.5 h-3.5" /> Discount Floor (₹{dealingRange.rangeLow?.toLocaleString('en-IN') ?? '--'})
              </span>
              <span className="text-amber-500 font-bold">
                50% Equilibrium (₹{dealingRange.equilibrium?.toLocaleString('en-IN') ?? '--'})
              </span>
              <span className="text-rose-500 font-bold flex items-center gap-1">
                Premium Ceiling (₹{dealingRange.rangeHigh?.toLocaleString('en-IN') ?? '--'}) <ArrowUpRight className="w-3.5 h-3.5" />
              </span>
            </div>

            {/* Bar */}
            <div className="relative w-full h-3 rounded-full bg-gradient-to-r from-emerald-500/30 via-amber-500/30 to-rose-500/30 overflow-visible border border-[var(--border-subtle)]">
              <div className="absolute left-1/2 top-0 bottom-0 w-0.5 bg-amber-400 z-10" />
              <div
                className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-4 h-4 rounded-full bg-blue-500 border-2 border-white dark:border-gray-900 shadow-md z-20 transition-all"
                style={{ left: `${Math.min(100, Math.max(0, dealingRange.currentPositionPct ?? 50))}%` }}
              />
            </div>

            <p className="text-[10.5px] text-[var(--text-secondary)] pt-1 leading-relaxed">
              {dealingRange.recommendation}
            </p>
          </div>

          {/* 2-Column: Liquidity Summary & Active Model */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Liquidity Matrix */}
            <div className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] space-y-3">
              <div className="flex items-center justify-between text-xs font-bold text-[var(--text-primary)]">
                <span className="flex items-center gap-1.5">
                  <Layers className="w-3.5 h-3.5 text-blue-500" />
                  KEY LIQUIDITY BOUNDARIES
                </span>
                <span className="text-[10px] text-[var(--text-muted)]">External & Internal</span>
              </div>

              <div className="space-y-2 text-xs">
                <div className="p-2.5 rounded-lg border border-rose-500/20 bg-rose-500/[0.03] space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold text-rose-500 uppercase tracking-wider">
                      Buy-Side Liquidity (BSL)
                    </span>
                    <span className="text-[10px] text-[var(--text-muted)]">Resting Buy Stops</span>
                  </div>
                  {liquidityPools?.bslLevels?.slice(0, 2).map((item, i) => (
                    <div key={i} className="flex items-center justify-between text-[11px]">
                      <span className="text-[var(--text-secondary)]">{item.name}</span>
                      <span className="font-bold text-rose-400">₹{item.level?.toLocaleString('en-IN') ?? '--'}</span>
                    </div>
                  ))}
                </div>

                <div className="p-2.5 rounded-lg border border-emerald-500/20 bg-emerald-500/[0.03] space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold text-emerald-500 uppercase tracking-wider">
                      Sell-Side Liquidity (SSL)
                    </span>
                    <span className="text-[10px] text-[var(--text-muted)]">Resting Sell Stops</span>
                  </div>
                  {liquidityPools?.sslLevels?.slice(0, 2).map((item, i) => (
                    <div key={i} className="flex items-center justify-between text-[11px]">
                      <span className="text-[var(--text-secondary)]">{item.name}</span>
                      <span className="font-bold text-emerald-400">₹{item.level?.toLocaleString('en-IN') ?? '--'}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Active Model */}
            <div className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] space-y-3">
              <div className="flex items-center justify-between text-xs font-bold text-[var(--text-primary)]">
                <span className="flex items-center gap-1.5">
                  <Shield className="w-3.5 h-3.5 text-emerald-500" />
                  SMC EXECUTION SETUP
                </span>
                <span
                  className={`text-[10px] px-2 py-0.5 rounded font-extrabold ${
                    activeModel?.status === 'QUALIFIED'
                      ? 'bg-emerald-500 text-white'
                      : 'bg-amber-500/20 text-amber-500'
                  }`}
                >
                  {activeModel?.status || 'MONITORING'}
                </span>
              </div>

              {activeModel ? (
                <div className="space-y-2.5 text-xs">
                  <div className="font-bold text-sm text-[var(--text-primary)]">
                    {activeModel.modelName}
                  </div>

                  <div className="space-y-1 text-[11px]">
                    <div className="flex items-start gap-1.5 text-[var(--text-secondary)]">
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0 mt-0.5" />
                      <span>{activeModel.triggerStep}</span>
                    </div>
                    <div className="flex items-start gap-1.5 text-[var(--text-secondary)]">
                      <Clock className="w-3.5 h-3.5 text-blue-500 shrink-0 mt-0.5" />
                      <span>Entry Zone: <strong className="text-[var(--text-primary)]">{activeModel.entryZone}</strong></span>
                    </div>
                  </div>

                  <div className="pt-2 border-t border-[var(--border-subtle)] grid grid-cols-3 gap-2 text-center text-[11px]">
                    <div className="p-1.5 rounded bg-rose-500/10 border border-rose-500/20">
                      <span className="text-[9px] text-rose-500 block uppercase">Stop-Loss</span>
                      <strong className="text-rose-500">₹{activeModel.stopLoss}</strong>
                    </div>
                    <div className="p-1.5 rounded bg-emerald-500/10 border border-emerald-500/20">
                      <span className="text-[9px] text-emerald-500 block uppercase">Target 1</span>
                      <strong className="text-emerald-500">₹{activeModel.target1}</strong>
                    </div>
                    <div className="p-1.5 rounded bg-blue-500/10 border border-blue-500/20">
                      <span className="text-[9px] text-blue-500 block uppercase">R:R Ratio</span>
                      <strong className="text-blue-500">{activeModel.riskRewardRatio}</strong>
                    </div>
                  </div>

                  <p className="text-[10px] text-[var(--text-muted)] italic pt-1">
                    {activeModel.optionsTranslation}
                  </p>
                </div>
              ) : (
                <div className="py-6 text-center text-xs text-[var(--text-muted)]">
                  Waiting for fresh liquidity sweep or break of structure confirmation.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* TAB: MULTI-TIMEFRAME CONFLUENCE */}
      {activeTab === 'MTF' && (
        <div className="space-y-4">
          <MultiTimeframePanel 
            data={(advancedIct as any)?.multiTimeframe || (data as any)?.multiTimeframe} 
            currentPrice={dealingRange.equilibrium} 
          />
        </div>
      )}

      {/* TAB 2: MARKET STRUCTURE */}
      {activeTab === 'STRUCTURE' && (
        <div className="space-y-4">
          {structure ? (
            <div className="space-y-3">
              <div className="p-3.5 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] flex items-center justify-between">
                <div>
                  <span className="text-[10px] uppercase font-bold text-[var(--text-muted)]">Structure Bias</span>
                  <div className="text-base font-extrabold text-[var(--text-primary)] mt-0.5">
                    {structure.structureBias} STRUCTURE ({structure.timeframe?.toUpperCase()})
                  </div>
                </div>
                <div className="text-right">
                  <span className="text-[10px] uppercase font-bold text-[var(--text-muted)]">Status</span>
                  <div className="text-xs font-bold text-emerald-500 mt-0.5">
                    {structure.status} (Confirmed Bar Closes)
                  </div>
                </div>
              </div>

              {/* Classified Trend Points: HH, HL, LH, LL */}
              <div className="p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-2.5">
                <div className="text-xs font-bold text-[var(--text-primary)]">
                  FRACTAL SWINGS & TREND POINTS (HH / HL / LH / LL)
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                  {structure.classifiedPoints?.slice(-6).map((pt: any, i: number) => {
                    const isBullish = pt.label === 'HH' || pt.label === 'HL';
                    return (
                      <div
                        key={i}
                        className={`p-2.5 rounded-lg border ${
                          isBullish
                            ? 'border-emerald-500/25 bg-emerald-500/[0.04]'
                            : 'border-rose-500/25 bg-rose-500/[0.04]'
                        }`}
                      >
                        <div className="flex items-center justify-between text-[10px] font-bold">
                          <span className={isBullish ? 'text-emerald-500' : 'text-rose-500'}>
                            {pt.label} ({pt.type === 'SWING_HIGH' ? 'High' : 'Low'})
                          </span>
                          <span className="text-[var(--text-muted)]">{pt.timeframe}</span>
                        </div>
                        <div className="text-sm font-bold text-[var(--text-primary)] mt-1">
                          ₹{pt.price}
                        </div>
                        <div className="text-[9px] text-[var(--text-muted)] mt-0.5">
                          {pt.timestamp}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* BOS & CHoCH Events */}
              <div className="p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-2.5">
                <div className="text-xs font-bold text-[var(--text-primary)]">
                  BREAK OF STRUCTURE (BOS) & CHANGE OF CHARACTER (CHoCH)
                </div>
                {structure.bosChoch?.events?.length > 0 ? (
                  <div className="space-y-2">
                    {structure.bosChoch.events.slice(-4).map((evt: any, i: number) => (
                      <div
                        key={i}
                        className="p-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-xs flex items-center justify-between"
                      >
                        <div>
                          <div className="font-bold text-[var(--text-primary)] flex items-center gap-2">
                            <span
                              className={`text-[10px] px-1.5 py-0.5 rounded font-extrabold ${
                                evt.type.includes('BULLISH')
                                  ? 'bg-emerald-500/15 text-emerald-500'
                                  : 'bg-rose-500/15 text-rose-500'
                              }`}
                            >
                              {evt.type ? String(evt.type).replace(/_/g, ' ') : ''}
                            </span>
                            <span>Level: ₹{evt.brokenLevel}</span>
                          </div>
                          <p className="text-[10.5px] text-[var(--text-secondary)] mt-0.5">
                            {evt.description}
                          </p>
                        </div>
                        <div className="text-right text-[10px] text-[var(--text-muted)] shrink-0 ml-3">
                          <div>Disp: {evt.displacementRatio}x</div>
                          <div className="text-emerald-500 font-bold">{evt.status}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-[var(--text-muted)] py-3 text-center">
                    No BOS or CHoCH events triggered in recent candle window.
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="py-8 text-center text-xs text-[var(--text-muted)]">
              Market structure analysis loading...
            </div>
          )}
        </div>
      )}

      {/* TAB 3: LIQUIDITY & SWEEPS */}
      {activeTab === 'LIQUIDITY' && (
        <div className="space-y-4">
          <LiquidityHeatmapPanel
            levels={(liquidityAdv as any)?.heatmap}
            currentPrice={dealingRange.equilibrium}
            sweeps={liquidityAdv?.sweeps}
          />

          {liquidityAdv ? (
            <div className="space-y-3">
              {/* Sweeps with Reclaim vs Without Reclaim */}
              <div className="p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-2.5">
                <div className="text-xs font-bold text-[var(--text-primary)] flex items-center justify-between">
                  <span>INSTITUTIONAL LIQUIDITY SWEEPS & TRAPS</span>
                  <span className="text-[10px] text-[var(--text-muted)]">Wick Reclaim vs Breakout</span>
                </div>

                {liquidityAdv.sweeps?.length > 0 ? (
                  <div className="space-y-2">
                    {liquidityAdv.sweeps.slice(-3).map((swp: any, i: number) => {
                      const isReclaim = swp.type === 'SWEEP_WITH_RECLAIM';
                      return (
                        <div
                          key={i}
                          className={`p-3 rounded-xl border ${
                            isReclaim
                              ? 'border-indigo-500/30 bg-indigo-500/[0.04]'
                              : 'border-[var(--border-subtle)] bg-[var(--bg-surface)]'
                          } space-y-1`}
                        >
                          <div className="flex items-center justify-between text-xs">
                            <div className="flex items-center gap-2">
                              <span
                                className={`text-[10px] px-2 py-0.5 rounded font-extrabold ${
                                  isReclaim ? 'bg-indigo-500 text-white' : 'bg-gray-500/20 text-gray-400'
                                }`}
                              >
                                {isReclaim ? 'SWEEP WITH RECLAIM (TRAP)' : 'BREAKOUT EXPANSION'}
                              </span>
                              <strong className="text-[var(--text-primary)]">₹{swp.level} ({swp.poolType})</strong>
                            </div>
                            <span className="text-[10px] text-[var(--text-muted)]">{swp.timestamp}</span>
                          </div>
                          <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">
                            {swp.description}
                          </p>
                          <div className="text-[10px] text-[var(--text-muted)] flex items-center gap-3 pt-1">
                            <span>Extreme: ₹{swp.extremePrice}</span>
                            <span>Close: ₹{swp.closePrice}</span>
                            <span>Invalidation: ₹{swp.invalidationLevel}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-xs text-[var(--text-muted)] py-4 text-center">
                    No recent liquidity sweep events detected.
                  </div>
                )}
              </div>

              {/* Liquidity Heatmap Zones */}
              {liquidityAdv.heatmap?.length > 0 && (
                <div className="p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-2.5">
                  <div className="text-xs font-bold text-[var(--text-primary)]">
                    LIQUIDITY DENSITY HEATMAP (ORDER BOOK WEIGHTING)
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5 text-xs">
                    {liquidityAdv.heatmap.slice(0, 6).map((zone: any, i: number) => (
                      <div
                        key={i}
                        className="p-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] flex items-center justify-between"
                      >
                        <div>
                          <div className="font-bold text-[var(--text-primary)]">{zone.name}</div>
                          <div className="text-[10px] text-[var(--text-muted)] mt-0.5">
                            Level: ₹{zone.level} ({zone.distancePts} pts away)
                          </div>
                        </div>
                        <div className="text-right">
                          <span
                            className={`text-[10px] px-1.5 py-0.5 rounded font-extrabold ${
                              zone.densityScore >= 8
                                ? 'bg-rose-500/15 text-rose-500'
                                : zone.densityScore >= 5
                                ? 'bg-amber-500/15 text-amber-500'
                                : 'bg-blue-500/15 text-blue-500'
                            }`}
                          >
                            Score: {zone.densityScore}/10
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="py-8 text-center text-xs text-[var(--text-muted)]">
              Liquidity data loading...
            </div>
          )}
        </div>
      )}

      {/* TAB 4: FVG & ORDER BLOCKS */}
      {activeTab === 'ZONES' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Fair Value Gaps (FVG) */}
            <div className="p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-3">
              <div className="text-xs font-bold text-[var(--text-primary)] flex items-center justify-between">
                <span>FAIR VALUE GAPS (FVG)</span>
                <span className="text-[10px] text-[var(--text-muted)]">50% CE Midpoint</span>
              </div>
              {fvgObAdv?.fairValueGaps && fvgObAdv.fairValueGaps.length > 0 ? (
                <div className="space-y-2">
                  {fvgObAdv.fairValueGaps.slice(-4).map((fvg: any, i: number) => (
                    <div
                      key={i}
                      className={`p-2.5 rounded-lg border ${
                        fvg.type === 'BULLISH_FVG'
                          ? 'border-emerald-500/25 bg-emerald-500/[0.04]'
                          : 'border-rose-500/25 bg-rose-500/[0.04]'
                      } text-xs space-y-1`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-[var(--text-primary)]">{fvg.type ? String(fvg.type).replace(/_/g, ' ') : ''}</span>
                        <span className="text-[10px] font-bold text-amber-500">{fvg.status}</span>
                      </div>
                      <div className="text-[11px] font-bold text-[var(--text-primary)]">
                        Range: ₹{fvg.bottom} — ₹{fvg.top}
                      </div>
                      <div className="text-[10px] text-[var(--text-muted)]">
                        50% CE: <strong className="text-amber-400">₹{fvg.ce50}</strong> • Size: {fvg.gapSize} pts
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-[var(--text-muted)] py-4 text-center">
                  No active Fair Value Gaps detected in current range.
                </div>
              )}
            </div>

            {/* Order Blocks & Breakers */}
            <div className="p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-3">
              <div className="text-xs font-bold text-[var(--text-primary)] flex items-center justify-between">
                <span>ORDER BLOCKS & BREAKERS</span>
                <span className="text-[10px] text-[var(--text-muted)]">Institutional Footprints</span>
              </div>
              {fvgObAdv?.orderBlocks && fvgObAdv.orderBlocks.length > 0 ? (
                <div className="space-y-2">
                  {fvgObAdv.orderBlocks.slice(-4).map((ob: any, i: number) => (
                    <div
                      key={i}
                      className={`p-2.5 rounded-lg border ${
                        ob.bias === 'BULLISH'
                          ? 'border-emerald-500/25 bg-emerald-500/[0.04]'
                          : 'border-rose-500/25 bg-rose-500/[0.04]'
                      } text-xs space-y-1`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-[var(--text-primary)]">{ob.type ? String(ob.type).replace(/_/g, ' ') : ''}</span>
                        <span className="text-[10px] font-bold text-blue-400">{ob.status}</span>
                      </div>
                      <div className="text-[11px] font-bold text-[var(--text-primary)]">
                        Range: ₹{ob.bottom} — ₹{ob.top}
                      </div>
                      <div className="text-[10px] text-[var(--text-muted)]">
                        Midpoint: <strong className="text-blue-400">₹{ob.midpoint}</strong>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-[var(--text-muted)] py-4 text-center">
                  No Order Blocks or Breakers detected.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* TAB 5: 100-POINT CONFLUENCE SCORECARD */}
      {activeTab === 'SCORECARD' && (
        <div className="space-y-4">
          {scorecard ? (
            <div className="space-y-3">
              {/* Score Header */}
              <div className="p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] flex items-center justify-between">
                <div>
                  <span className="text-[10px] uppercase font-bold text-[var(--text-muted)]">Conviction Grade</span>
                  <div className="text-lg font-extrabold text-[var(--text-primary)] mt-0.5 flex items-center gap-2">
                    <span>{scorecard.convictionGrade}</span>
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded font-extrabold ${
                        scorecard.isTradeable
                          ? 'bg-emerald-500 text-white'
                          : 'bg-rose-500/20 text-rose-400'
                      }`}
                    >
                      {scorecard.isTradeable ? 'TRADEABLE SETUP' : 'LOCKOUT / WAIT'}
                    </span>
                  </div>
                  <p className="text-[11px] text-[var(--text-secondary)] mt-1">
                    {scorecard.recommendation}
                  </p>
                </div>

                <div className="text-right">
                  <div className="text-2xl font-black text-blue-500">
                    {scorecard.overallScore}
                    <span className="text-xs text-[var(--text-muted)] font-normal"> / 100</span>
                  </div>
                  <span className="text-[10px] text-[var(--text-muted)]">Institutional Confluence</span>
                </div>
              </div>

              {/* Factors Table */}
              <div className="p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-2">
                <div className="text-xs font-bold text-[var(--text-primary)]">
                  CONFLUENCE FACTORS BREAKDOWN
                </div>
                <div className="space-y-1.5">
                  {scorecard.factors?.map((f: any, i: number) => (
                    <div
                      key={i}
                      className="p-2 rounded-lg bg-[var(--bg-surface)] border border-[var(--border-subtle)] flex items-center justify-between text-xs"
                    >
                      <span className="text-[var(--text-primary)]">{f.factor}</span>
                      <div className="flex items-center gap-3">
                        <span className="font-bold text-[var(--text-primary)]">
                          {f.score} / {f.maxScore} pts
                        </span>
                        <span
                          className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${
                            f.status === 'PASS'
                              ? 'bg-emerald-500/15 text-emerald-500'
                              : f.status === 'PARTIAL'
                              ? 'bg-amber-500/15 text-amber-500'
                              : 'bg-rose-500/15 text-rose-500'
                          }`}
                        >
                          {f.status}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Missing Confirmations */}
              {scorecard.missingConfirmations?.length > 0 && (
                <div className="p-3.5 rounded-xl bg-amber-500/5 border border-amber-500/20 space-y-1 text-xs">
                  <div className="font-bold text-amber-500 flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    Missing Institutional Confirmations:
                  </div>
                  <ul className="list-disc list-inside space-y-0.5 text-[11px] text-[var(--text-secondary)]">
                    {scorecard.missingConfirmations.map((m: string, i: number) => (
                      <li key={i}>{m}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <div className="py-8 text-center text-xs text-[var(--text-muted)]">
              Scorecard calculating...
            </div>
          )}
        </div>
      )}

      {/* AI Market Report Modal */}
      <AIMarketReportModal
        isOpen={isReportOpen}
        onClose={() => setIsReportOpen(false)}
        reportText={reportText}
        symbol="NIFTY 50"
      />
    </div>
  );
};
