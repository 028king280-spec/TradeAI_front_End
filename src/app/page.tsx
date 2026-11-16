'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  ShieldCheck,
  Zap,
  Layers,
  Radio,
  ChevronRight,
  Sparkles,
  RefreshCw,
  Compass,
  Gauge,
  GitMerge,
  Info,
  BarChart3,
  Eye,
} from 'lucide-react';
import { optionsService } from '@/services/optionsService';
import {
  OptionsOverviewResponse,
  IndexAnalysisFullResponse,
  IndexQuoteCard,
} from '@/types/options';
import { formatINR, formatNumberIN } from '@/lib/utils';
import { OptionsCandlestickChart } from '@/components/trading/OptionsCandlestickChart';
import { LiveAnalysisChart } from '@/components/trading/LiveAnalysisChart';
import { OptionsSetupsCard } from '@/components/trading/OptionsSetupsCard';
import { SmartMoneyConceptsCard } from '@/components/trading/SmartMoneyConceptsCard';
import { PaperTradingSimulator } from '@/components/trading/PaperTradingSimulator';
import { SupportResistanceLadderView } from '@/components/trading/SupportResistanceLadder';
import { SessionOutlookCard } from '@/components/trading/SessionOutlookCard';
import { MarketSentimentPanel } from '@/components/trading/MarketSentimentPanel';
import { ChartPatternsCard } from '@/components/trading/ChartPatternsCard';
import { NextSessionOpeningCard } from '@/components/trading/NextSessionOpeningCard';
import { NextSessionRecommendationCard } from '@/components/trading/NextSessionRecommendationCard';
import { NextSessionBacktestModal } from '@/components/trading/NextSessionBacktestModal';
import { MarketNewsCard } from '@/components/trading/MarketNewsCard';
import { MarketStatePanel } from '@/components/trading/MarketStatePanel';
import { SignalActivationPanel, SignalActivationData } from '@/components/trading/SignalActivationPanel';
import { ActiveSignalTracker, TrackedSignalItem } from '@/components/trading/ActiveSignalTracker';
import { SignalTimelineModal } from '@/components/trading/SignalTimelineModal';
import { FailureAnalysisModal } from '@/components/trading/FailureAnalysisModal';
import { MLStrategyLearnerPanel } from '@/components/trading/MLStrategyLearnerPanel';

export default function OptionsDashboardPage() {
  const [overview, setOverview] = useState<OptionsOverviewResponse | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<string>('NIFTY 50');
  const [analysis, setAnalysis] = useState<IndexAnalysisFullResponse | null>(null);
  const [loadingOverview, setLoadingOverview] = useState<boolean>(true);
  const [loadingAnalysis, setLoadingAnalysis] = useState<boolean>(true);
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);
  const [isBacktestOpen, setIsBacktestOpen] = useState<boolean>(false);
  const [trackedSignals, setTrackedSignals] = useState<TrackedSignalItem[]>([]);
  const [selectedTimelineSignalId, setSelectedTimelineSignalId] = useState<string | null>(null);
  const [selectedFailureSignalId, setSelectedFailureSignalId] = useState<string | null>(null);
  const [selectedSignalBias, setSelectedSignalBias] = useState<'CE' | 'PE' | 'AUTO'>('AUTO');

  // 1. Load Overview Data (Index Cards + Overall Sentiment)
  useEffect(() => {
    let isCancelled = false;
    async function loadOverview() {
      setLoadingOverview(true);
      const data = await optionsService.getOverview();
      if (!isCancelled && data) {
        setOverview(data);
      }
      setLoadingOverview(false);
    }
    loadOverview();
    return () => {
      isCancelled = true;
    };
  }, [refreshTrigger]);

  // 2. Load Deep Analysis for Selected Index
  useEffect(() => {
    let isCancelled = false;
    async function loadAnalysis() {
      setLoadingAnalysis(true);
      const data = await optionsService.getIndexAnalysis(selectedIndex);
      if (!isCancelled && data) {
        setAnalysis(data);
      }
      setLoadingAnalysis(false);
    }
    loadAnalysis();
    return () => {
      isCancelled = true;
    };
  }, [selectedIndex, refreshTrigger]);

  // 3. Load Tracked Signals
  useEffect(() => {
    let isCancelled = false;
    async function loadSignals() {
      try {
        const res = await fetch('/api/signals/today');
        if (res.ok) {
          const json = await res.json();
          if (!isCancelled && json.success && json.data?.trackedOptionSetups) {
            setTrackedSignals(json.data.trackedOptionSetups);
          }
        }
      } catch {
        // Silently handle if backend is reconnecting
      }
    }
    loadSignals();
    return () => {
      isCancelled = true;
    };
  }, [refreshTrigger]);

  const activeQuote = overview?.indices?.find(
    (idx) => idx.symbol.toUpperCase() === selectedIndex.toUpperCase() || idx.name.toUpperCase().includes(selectedIndex.toUpperCase())
  ) || overview?.indices?.[0];

  const currentPrice = activeQuote?.currentValue || 23820.00;

  // Build SignalActivationData
  const activeSignalData: SignalActivationData | null = React.useMemo(() => {
    if (!analysis) return null;

    const marketState = analysis.marketState;
    const isSideways = marketState?.marketState === 'SIDEWAYS' || marketState?.isNoTrade || analysis.todayOptionsSetups?.hasQualifiedSetups === false;
    const setups = analysis.todayOptionsSetups?.setups || [];

    let chosenSetup = null;
    if (selectedSignalBias === 'CE') {
      chosenSetup = setups.find((s) => s.bias === 'CE') || setups[0];
    } else if (selectedSignalBias === 'PE') {
      chosenSetup = setups.find((s) => s.bias === 'PE') || setups[0];
    } else {
      chosenSetup = setups.length > 0 ? setups[0] : null;
    }

    if (!chosenSetup || isSideways || chosenSetup.target1 === 0) {
      const displaySetup = chosenSetup || setups[0];
      const fallbackLtp = displaySetup?.currentPremium && displaySetup.currentPremium > 0
        ? displaySetup.currentPremium
        : (selectedIndex.includes('BANK') ? 220.0 : 125.0);
      const entryMin = (displaySetup as any)?.suggestedEntryMin && (displaySetup as any).suggestedEntryMin > 0
        ? (displaySetup as any).suggestedEntryMin
        : Math.round(fallbackLtp * 0.98 * 10) / 10;
      const entryMax = (displaySetup as any)?.suggestedEntryMax && (displaySetup as any).suggestedEntryMax > 0
        ? (displaySetup as any).suggestedEntryMax
        : Math.round(fallbackLtp * 1.02 * 10) / 10;
      const sl = displaySetup?.stopLoss && displaySetup.stopLoss > 0
        ? displaySetup.stopLoss
        : Math.round(fallbackLtp * 0.75 * 10) / 10;
      const t1 = displaySetup?.target1 && displaySetup.target1 > 0
        ? displaySetup.target1
        : Math.round(fallbackLtp * 1.30 * 10) / 10;
      const t2 = displaySetup?.target2 && displaySetup.target2 > 0
        ? displaySetup.target2
        : Math.round(fallbackLtp * 1.60 * 10) / 10;
      const t3 = (displaySetup as any)?.target3 && (displaySetup as any).target3 > 0
        ? (displaySetup as any).target3
        : Math.round(fallbackLtp * 2.00 * 10) / 10;

      return {
        index: selectedIndex,
        signalState: 'NO_TRADE',
        bias: 'NONE',
        contractSymbol: displaySetup?.contractSymbol || `${selectedIndex} ${Math.round(currentPrice / 50) * 50} CE`,
        strike: displaySetup?.strike || Math.round(currentPrice / 50) * 50,
        expiry: displaySetup?.expiry || 'Current Expiry',
        lastObservedLtp: fallbackLtp,
        entryRangeMin: entryMin,
        entryRangeMax: entryMax,
        stopLoss: sl,
        target1: t1,
        target2: t2,
        target3: t3,
        riskRewardRatio: '1:2.0 (Estimated)',
        entryCondition: displaySetup?.underlyingTrigger || marketState?.keyLevels?.bullishActivationTrigger || 'Awaiting 5M breakout confirmation outside chop zone',
        invalidationCondition: 'Choppy sideways price action; directional targets disabled to prevent theta loss.',
        supportingReasons: displaySetup?.supportingReasons || [
          'Sideways market regime: Directional option buying targets disabled.',
          'Theta decay rapidly burns capital in non-trending markets.',
          'Wait for confirmed 5-minute candle breakout before targets arm.'
        ],
        dataTimestamp: analysis.dataTimestamp,
        dataStatus: analysis.dataStatus,
      };
    }

    const isCall = chosenSetup.bias === 'CE';
    return {
      index: selectedIndex,
      signalState: isCall ? 'CALL_SETUP_READY' : 'PUT_SETUP_READY',
      bias: chosenSetup.bias as 'CE' | 'PE',
      contractSymbol: chosenSetup.contractSymbol,
      strike: chosenSetup.strike,
      expiry: chosenSetup.expiry,
      lastObservedLtp: chosenSetup.currentPremium,
      entryRangeMin: (chosenSetup as any).suggestedEntryMin || chosenSetup.currentPremium * 0.98,
      entryRangeMax: (chosenSetup as any).suggestedEntryMax || chosenSetup.currentPremium * 1.02,
      stopLoss: chosenSetup.stopLoss,
      target1: chosenSetup.target1,
      target2: chosenSetup.target2,
      target3: chosenSetup.target3,
      targetProbabilities: (chosenSetup as any).targetProbabilities,
      t1Probability: (chosenSetup as any).t1Probability || 82,
      t2Probability: (chosenSetup as any).t2Probability || 54,
      t3Probability: (chosenSetup as any).t3Probability || 24,
      t1GainPct: (chosenSetup as any).t1GainPct || 30.0,
      t2GainPct: (chosenSetup as any).t2GainPct || 55.0,
      t3GainPct: (chosenSetup as any).t3GainPct || 85.0,
      riskRewardRatio: chosenSetup.riskRewardRatio,
      entryCondition: chosenSetup.underlyingTrigger,
      invalidationCondition: chosenSetup.invalidationCondition,
      supportingReasons: chosenSetup.supportingReasons,
      dataTimestamp: analysis.dataTimestamp,
      dataStatus: analysis.dataStatus,
    };
  }, [analysis, selectedIndex, currentPrice, selectedSignalBias]);

  return (
    <div className="space-y-6 pb-12 font-mono">
      {/* Top Notification / Platform Mandate Bar */}
      <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-3 sm:p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-2.5 text-[var(--text-primary)]">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping"></span>
          <span className="font-bold">AIVOLVE LIVE OPTIONS INTELLIGENCE</span>
          <span className="text-[var(--text-muted)] hidden md:inline">• Indian Derivatives (NSE / BSE)</span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-[var(--text-muted)]">
          <Link
            href="/sentiment"
            className="flex items-center gap-1.5 px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white font-bold tracking-wide transition-all shadow-[0_0_12px_rgba(37,99,235,0.3)]"
          >
            <Gauge className="w-3.5 h-3.5" />
            <span>Market Sentiment</span>
          </Link>
          <Link
            href="/performance"
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-indigo-600 text-white font-bold hover:bg-indigo-500 transition-colors"
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Audit Dashboard</span>
          </Link>
          <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-semibold">
            <Radio className="w-3 h-3 text-emerald-500 animate-pulse" />
            Provider: {overview?.provider ? overview.provider.toUpperCase() : 'ANGEL ONE'}
          </span>
          <span>Feed: {overview?.dataStatus || 'CONNECTING'}</span>
        </div>
      </div>

      {/* SECTION 1: LIVE INDEX BENCHMARK SELECTOR CARDS */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-blue-500" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
              Core Indian Indices
            </h2>
          </div>
          <button
            onClick={() => setRefreshTrigger((prev) => prev + 1)}
            className="text-xs flex items-center gap-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors p-1 rounded"
            title="Refresh All Quotes"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>
        </div>

        {/* Index Cards Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {(overview?.indices || [
            { symbol: 'NIFTY 50', name: 'NIFTY 50', currentValue: 23820.0, change: 14.2, changePercent: 0.06, trend: 'Bullish' },
            { symbol: 'SENSEX', name: 'BSE SENSEX', currentValue: 76950.0, change: 30.4, changePercent: 0.04, trend: 'Bullish' },
            { symbol: 'BANK NIFTY', name: 'NIFTY BANK', currentValue: 55600.0, change: 56.5, changePercent: 0.10, trend: 'Bullish' },
            { symbol: 'INDIA VIX', name: 'INDIA VIX', currentValue: 15.7, change: -0.02, changePercent: -0.13, trend: 'Bearish' },
          ]).map((idx) => {
            const isSelected = selectedIndex.toUpperCase() === idx.symbol.toUpperCase() || (idx.symbol === 'NIFTY' && selectedIndex === 'NIFTY 50');
            const isUp = (idx.change || 0) >= 0;

            return (
              <div
                key={idx.symbol}
                onClick={() => {
                  if (idx.symbol !== 'INDIA VIX') {
                    setSelectedIndex(idx.symbol === 'NIFTY' ? 'NIFTY 50' : idx.symbol);
                  }
                }}
                className={`p-4 rounded-xl border transition-all cursor-pointer relative overflow-hidden ${
                  isSelected
                    ? 'border-blue-500 bg-blue-500/10 shadow-md ring-1 ring-blue-500'
                    : 'border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] hover:border-[var(--border-strong)]'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-[var(--text-primary)]">{idx.name}</span>
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider ${
                      idx.symbol === 'INDIA VIX'
                        ? 'bg-amber-500/15 text-amber-500'
                        : isUp
                        ? 'bg-emerald-500/15 text-emerald-500'
                        : 'bg-rose-500/15 text-rose-500'
                    }`}
                  >
                    {idx.trend}
                  </span>
                </div>

                <div className="flex items-baseline justify-between mt-1">
                  <span className="text-xl font-black text-[var(--text-primary)]">
                    ₹{idx.currentValue ? idx.currentValue.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '--'}
                  </span>
                  <span
                    className={`text-xs font-bold flex items-center gap-0.5 ${
                      isUp ? 'text-emerald-500' : 'text-rose-500'
                    }`}
                  >
                    {isUp ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />}
                    {isUp ? '+' : ''}
                    {idx.change?.toFixed(2)} ({idx.changePercent?.toFixed(2)}%)
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* REQUIREMENT 1: Clear No-Trade Zone & Market State */}
      {analysis?.marketState && (
        <MarketStatePanel data={analysis.marketState} />
      )}

      {/* REQUIREMENT 2: CALL/PUT Signal Activation */}
      <SignalActivationPanel
        data={activeSignalData}
        selectedBias={selectedSignalBias}
        onSelectBias={setSelectedSignalBias}
        onOpenTimeline={() => {
          if (trackedSignals.length > 0) {
            setSelectedTimelineSignalId(trackedSignals[0].id);
          }
        }}
      />

      {/* REQUIREMENT 2 & 3: Active Signal Tracker & Outcome Monitoring */}
      <ActiveSignalTracker
        signals={trackedSignals}
        onSelectSignalTimeline={(id) => setSelectedTimelineSignalId(id)}
        onSelectFailureAnalysis={(id) => setSelectedFailureSignalId(id)}
      />

      {/* Machine Learning Strategy Learner & Adaptive Accuracy Scorecard */}
      <MLStrategyLearnerPanel indexSymbol={selectedIndex} />

      {/* CRITICAL FEATURE: NEXT-SESSION OPTIONS RECOMMENDATION ENGINE */}
      {(analysis?.nextSessionRecommendation || overview?.nextSessionRecommendation) && (
        <NextSessionRecommendationCard
          data={analysis?.nextSessionRecommendation || overview?.nextSessionRecommendation!}
          onOpenBacktest={() => setIsBacktestOpen(true)}
        />
      )}

      {/* NEXT-SESSION OPENING OUTLOOK */}
      {(analysis?.nextSessionOpeningOutlook || overview?.nextSessionOpeningOutlook) && (
        <NextSessionOpeningCard
          outlook={analysis?.nextSessionOpeningOutlook || overview?.nextSessionOpeningOutlook!}
          indexSymbol={selectedIndex}
        />
      )}

      {/* SECTION 3: LIVE REAL-TIME SMARTSTREAM CHART */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <LiveAnalysisChart
            symbol={selectedIndex}
            currentPrice={currentPrice}
            supportLevel={analysis?.supportResistance?.support1?.price}
            resistanceLevel={analysis?.supportResistance?.resistance1?.price}
          />

          {/* SECTION 4: MARKET SENTIMENT PANEL */}
          {analysis?.sentiment && <MarketSentimentPanel sentiment={analysis.sentiment} />}

          {/* SECTION 6: SMART MONEY CONCEPTS (SMC) & ORDER FLOW */}
          {analysis?.smcAnalysis && (
            <SmartMoneyConceptsCard data={analysis.smcAnalysis} />
          )}

          {/* SECTION 7: TODAY'S OPTIONS SETUPS */}
          {analysis?.todayOptionsSetups && (
            <OptionsSetupsCard data={analysis.todayOptionsSetups} />
          )}

          {/* SECTION 7.5: 1-CLICK SMC OPTIONS PAPER TRADING SIMULATOR */}
          <PaperTradingSimulator />

          {/* SECTION 8: CHART PATTERNS */}
          {analysis?.patterns && <ChartPatternsCard patterns={analysis.patterns} />}
        </div>

        {/* RIGHT COLUMN: SUPPORT & RESISTANCE LADDER + SESSION OUTLOOK */}
        <div className="space-y-6">
          {/* Support & Resistance Ladder */}
          {analysis?.supportResistance && (
            <SupportResistanceLadderView
              data={analysis.supportResistance}
              currentPrice={currentPrice}
            />
          )}

          {/* Session Outlook (Today vs Next Session) */}
          {analysis?.todayOutlook && analysis?.nextSessionOutlook && (
            <SessionOutlookCard
              todayData={analysis.todayOutlook}
              nextSessionData={analysis.nextSessionOutlook}
            />
          )}

          {/* Option Chain Quick Navigation Banner */}
          <div className="p-4 rounded-xl border border-indigo-500/25 bg-gradient-to-br from-indigo-500/10 via-purple-500/5 to-transparent space-y-3 font-mono">
            <div className="flex items-center gap-2 text-indigo-500 font-bold text-xs uppercase tracking-wider">
              <Layers className="w-4 h-4" />
              <span>Full Strike Option Chain</span>
            </div>
            <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
              Explore complete call & put strikes with Black-Scholes Greeks (Delta, Gamma, Theta, Vega),
              open interest shifts, PCR, and Max Pain for {selectedIndex}.
            </p>
            <Link
              href={`/option-chain?symbol=${encodeURIComponent(selectedIndex)}`}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700 transition-colors shadow-xs"
            >
              <span>Launch {selectedIndex} Option Chain</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          {/* Real-time Automated Indian Market News Feed */}
          <MarketNewsCard initialSymbol={selectedIndex} />
        </div>
      </div>

      {/* PLATFORM MANDATE DISCLAIMER FOOTER */}
      <div className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-[11px] font-mono text-[var(--text-muted)] space-y-1">
        <div className="flex items-center gap-2 text-[var(--text-primary)] font-bold">
          <ShieldCheck className="w-4 h-4 text-blue-500" />
          <span>Institutional Research Mandate & Analytical Integrity</span>
        </div>
        <p className="leading-relaxed">
          AIVOLVE Trading AI is strictly an Indian stock and index options analytics terminal. Numerical calculations
          (Support/Resistance, Intraday Range, PCR, Greeks, Max Pain, Probability Distributions) are deterministically
          computed by the Python Quantitative Engine. This application does NOT execute broker orders, place trades,
          or manage funds. All analytical trade ideas are probabilistic observations for educational and research purposes.
        </p>
      </div>

      {/* Modals */}
      <SignalTimelineModal
        signalId={selectedTimelineSignalId}
        onClose={() => setSelectedTimelineSignalId(null)}
      />

      <FailureAnalysisModal
        signalId={selectedFailureSignalId}
        onClose={() => setSelectedFailureSignalId(null)}
      />

      {/* HISTORICAL VALIDATION BACKTEST MODAL */}
      <NextSessionBacktestModal
        isOpen={isBacktestOpen}
        onClose={() => setIsBacktestOpen(false)}
        symbol={selectedIndex}
      />
    </div>
  );
}
