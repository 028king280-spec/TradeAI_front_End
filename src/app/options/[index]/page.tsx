'use client';

import React, { useState, useEffect, use } from 'react';
import Link from 'next/link';
import {
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  ShieldCheck,
  Zap,
  Layers,
  RefreshCw,
  ChevronRight,
  BarChart3,
  Loader2,
} from 'lucide-react';
import { optionsService } from '@/services/optionsService';
import { IndexAnalysisFullResponse } from '@/types/options';
import { OptionsCandlestickChart } from '@/components/trading/OptionsCandlestickChart';
import { OptionsSetupsCard } from '@/components/trading/OptionsSetupsCard';
import { SupportResistanceLadderView } from '@/components/trading/SupportResistanceLadder';
import { SessionOutlookCard } from '@/components/trading/SessionOutlookCard';
import { MarketSentimentPanel } from '@/components/trading/MarketSentimentPanel';
import { ChartPatternsCard } from '@/components/trading/ChartPatternsCard';
import { NextSessionOpeningCard } from '@/components/trading/NextSessionOpeningCard';
import { NextSessionRecommendationCard } from '@/components/trading/NextSessionRecommendationCard';
import { NextSessionBacktestModal } from '@/components/trading/NextSessionBacktestModal';
import { MarketStatePanel } from '@/components/trading/MarketStatePanel';
import { SignalActivationPanel, SignalActivationData } from '@/components/trading/SignalActivationPanel';
import { ActiveSignalTracker, TrackedSignalItem } from '@/components/trading/ActiveSignalTracker';
import { SignalTimelineModal } from '@/components/trading/SignalTimelineModal';
import { FailureAnalysisModal } from '@/components/trading/FailureAnalysisModal';

interface PageProps {
  params: Promise<{ index: string }>;
}

export default function IndexAnalysisPage({ params }: PageProps) {
  const resolvedParams = use(params);
  const rawIndex = decodeURIComponent(resolvedParams.index).toUpperCase();
  
  const indexSymbol =
    rawIndex === 'NIFTY' ? 'NIFTY 50' : rawIndex === 'BANKNIFTY' ? 'BANK NIFTY' : rawIndex;

  const [analysis, setAnalysis] = useState<IndexAnalysisFullResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);
  const [isBacktestOpen, setIsBacktestOpen] = useState<boolean>(false);
  const [trackedSignals, setTrackedSignals] = useState<TrackedSignalItem[]>([]);
  const [selectedTimelineSignalId, setSelectedTimelineSignalId] = useState<string | null>(null);
  const [selectedFailureSignalId, setSelectedFailureSignalId] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;
    async function loadData() {
      if (refreshTrigger > 0) setRefreshing(true);
      else setLoading(true);
      
      const data = await optionsService.getIndexAnalysis(indexSymbol);
      if (!isCancelled && data) {
        setAnalysis(data);
      }

      // Fetch today's tracked signals from backend
      try {
        const sigRes = await fetch(`http://localhost:8000/api/signals/today`);
        const sigJson = await sigRes.json();
        if (!isCancelled && sigJson.success && sigJson.data?.trackedOptionSetups) {
          setTrackedSignals(sigJson.data.trackedOptionSetups);
        }
      } catch (e) {
        console.error('Failed to load tracked signals:', e);
      }

      setLoading(false);
      setRefreshing(false);
    }
    loadData();
    return () => {
      isCancelled = true;
    };
  }, [indexSymbol, refreshTrigger]);

  const currentPrice = analysis?.quote
    ? Number(analysis.quote.currentPrice || analysis.quote.ltp || 0)
    : 0;

  // Build SignalActivationData from qualified setups or NO_TRADE state
  const activeSignalData: SignalActivationData | null = React.useMemo(() => {
    if (!analysis) return null;

    const marketState = analysis.marketState;
    const setups = analysis.todayOptionsSetups?.setups;
    const primarySetup = setups && setups.length > 0 ? setups[0] : null;

    if (marketState?.isNoTrade || !primarySetup) {
      return {
        index: indexSymbol,
        signalState: 'NO_TRADE',
        bias: 'NONE',
        contractSymbol: `${indexSymbol} AWAIT SETUP`,
        strike: Math.round(currentPrice / 50) * 50,
        expiry: 'Current Expiry',
        lastObservedLtp: 0.0,
        entryRangeMin: 0.0,
        entryRangeMax: 0.0,
        stopLoss: 0.0,
        target1: 0.0,
        target2: 0.0,
        target3: 0.0,
        riskRewardRatio: 'N/A',
        entryCondition: marketState?.keyLevels?.bullishActivationTrigger || 'Awaiting breakout confirmation',
        invalidationCondition: 'Choppy sideways price action; risk of rapid theta decay',
        supportingReasons: marketState?.contributingFactors || [],
        dataTimestamp: analysis.dataTimestamp,
        dataStatus: analysis.dataStatus,
      };
    }

    const isCall = primarySetup.bias === 'CE';
    return {
      index: indexSymbol,
      signalState: isCall ? 'CALL_SETUP_READY' : 'PUT_SETUP_READY',
      bias: primarySetup.bias as 'CE' | 'PE',
      contractSymbol: primarySetup.contractSymbol,
      strike: primarySetup.strike,
      expiry: primarySetup.expiry,
      lastObservedLtp: primarySetup.currentPremium,
      entryRangeMin: (primarySetup as any).suggestedEntryMin || primarySetup.currentPremium * 0.98,
      entryRangeMax: (primarySetup as any).suggestedEntryMax || primarySetup.currentPremium * 1.02,
      stopLoss: primarySetup.stopLoss,
      target1: primarySetup.target1,
      target2: primarySetup.target2,
      target3: primarySetup.target3,
      riskRewardRatio: primarySetup.riskRewardRatio,
      entryCondition: primarySetup.underlyingTrigger,
      invalidationCondition: primarySetup.invalidationCondition,
      supportingReasons: primarySetup.supportingReasons,
      dataTimestamp: analysis.dataTimestamp,
      dataStatus: analysis.dataStatus,
    };
  }, [analysis, indexSymbol, currentPrice]);

  const filteredTrackedSignals = trackedSignals.filter(
    (s) => s.symbol.toUpperCase() === indexSymbol.toUpperCase() || s.symbol.toUpperCase().includes(rawIndex)
  );

  return (
    <div className="space-y-6 pb-12">
      {/* Top Header Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-5 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-blue-500/20 flex items-center justify-center">
            <Activity className="w-5 h-5 text-blue-600 dark:text-blue-400" />
          </div>
          <div>
            <div className="flex items-center gap-2.5 flex-wrap">
              <h1 className="text-xl font-bold tracking-tight text-[var(--text-primary)]">
                {indexSymbol} Options Terminal
              </h1>
              <span className={`text-[10px] px-2.5 py-1 rounded-md font-bold border ${
                analysis?.dataStatus === 'LIVE'
                  ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20'
                  : 'bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-500/20'
              }`}>
                {analysis?.dataStatus || 'CONNECTING'}
              </span>
            </div>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Audit-compliant option outcome tracking • Angel One Verified Feed
            </p>
          </div>
        </div>

        {/* Index Metrics + Actions */}
        <div className="flex items-center gap-3 flex-wrap">
          {analysis?.quote && (
            <div className="flex items-center gap-4 bg-[var(--bg-surface-elevated)] px-4 py-2.5 rounded-xl border border-[var(--border-subtle)]">
              <div>
                <span className="text-[10px] text-[var(--text-muted)] block font-medium">Spot LTP</span>
                <span className="text-base font-extrabold text-[var(--text-primary)] font-mono">
                  ₹{currentPrice.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </span>
              </div>
              <div className="w-px h-8 bg-[var(--border-subtle)]" />
              <div>
                <span className="text-[10px] text-[var(--text-muted)] block font-medium">Change</span>
                <span
                  className={`text-base font-extrabold flex items-center gap-1 font-mono ${
                    Number(analysis.quote.change) >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
                  }`}
                >
                  {Number(analysis.quote.change) >= 0 ? (
                    <ArrowUpRight className="w-4 h-4" />
                  ) : (
                    <ArrowDownRight className="w-4 h-4" />
                  )}
                  {Number(analysis.quote.change) >= 0 ? '+' : ''}
                  {Number(analysis.quote.change).toFixed(2)} ({Number(analysis.quote.changePercent || 0).toFixed(2)}%)
                </span>
              </div>
            </div>
          )}

          <Link
            href="/performance"
            className="px-3.5 py-2.5 rounded-xl bg-indigo-500 hover:bg-indigo-600 text-white text-xs font-bold flex items-center gap-1.5 transition-colors shadow-md hover:shadow-lg"
            title="View Daily Accuracy Audit & Signal History"
          >
            <BarChart3 className="w-4 h-4" />
            <span>Audit Engine</span>
          </Link>

          <button
            onClick={() => setRefreshTrigger((prev) => prev + 1)}
            className="p-2.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:border-[var(--border-strong)] transition-all"
            title="Refresh Analysis"
            disabled={refreshing}
          >
            {refreshing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {loading && !analysis ? (
        <div className="flex flex-col items-center justify-center min-h-[50vh] space-y-4">
          <div className="w-12 h-12 rounded-2xl bg-blue-50 dark:bg-blue-500/10 flex items-center justify-center">
            <Loader2 className="w-6 h-6 text-blue-500 animate-spin" />
          </div>
          <div className="text-center space-y-1">
            <p className="text-sm font-semibold text-[var(--text-primary)]">Computing {indexSymbol} Models</p>
            <p className="text-xs text-[var(--text-muted)]">Loading quantitative analysis & market data...</p>
          </div>
        </div>
      ) : analysis ? (
        <div className="space-y-6">
          {/* REQUIREMENT 1: Clear No-Trade Zone & Market State */}
          {analysis.marketState && (
            <MarketStatePanel data={analysis.marketState} />
          )}

          {/* REQUIREMENT 2: CALL/PUT Signal Activation */}
          <SignalActivationPanel
            data={activeSignalData}
            onOpenTimeline={() => {
              if (filteredTrackedSignals.length > 0) {
                setSelectedTimelineSignalId(filteredTrackedSignals[0].id);
              }
            }}
          />

          {/* REQUIREMENT 2 & 3: Active Signal Tracker & Outcome Monitoring */}
          <ActiveSignalTracker
            signals={filteredTrackedSignals}
            onSelectSignalTimeline={(id) => setSelectedTimelineSignalId(id)}
            onSelectFailureAnalysis={(id) => setSelectedFailureSignalId(id)}
          />

          {/* Next-Session Options Recommendation Engine */}
          {analysis.nextSessionRecommendation && (
            <NextSessionRecommendationCard
              data={analysis.nextSessionRecommendation}
              onOpenBacktest={() => setIsBacktestOpen(true)}
            />
          )}

          {/* Next-Session Opening Outlook */}
          {analysis.nextSessionOpeningOutlook && (
            <NextSessionOpeningCard
              outlook={analysis.nextSessionOpeningOutlook}
              indexSymbol={indexSymbol}
            />
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Main Column */}
            <div className="lg:col-span-2 space-y-6">
              <OptionsCandlestickChart
                symbol={indexSymbol}
                currentPrice={currentPrice}
                supportLevel={analysis.supportResistance?.support1?.price}
                resistanceLevel={analysis.supportResistance?.resistance1?.price}
              />

              <MarketSentimentPanel sentiment={analysis.sentiment} />

              <OptionsSetupsCard data={analysis.todayOptionsSetups} />

              <ChartPatternsCard patterns={analysis.patterns} />
            </div>

            {/* Right Column */}
            <div className="space-y-6">
              <SupportResistanceLadderView
                data={analysis.supportResistance}
                currentPrice={currentPrice}
              />

              <SessionOutlookCard
                todayData={analysis.todayOutlook}
                nextSessionData={analysis.nextSessionOutlook}
              />

              {/* Quick Option Chain Link */}
              <div className="p-5 rounded-2xl border border-indigo-200 dark:border-indigo-500/20 bg-gradient-to-br from-indigo-50/80 via-purple-50/30 to-transparent dark:from-indigo-500/8 dark:via-purple-500/4 dark:to-transparent space-y-3">
                <div className="flex items-center gap-2 text-indigo-600 dark:text-indigo-400 font-bold text-xs uppercase tracking-wider">
                  <Layers className="w-4 h-4" />
                  <span>Option Chain</span>
                </div>
                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                  Inspect strike-by-strike open interest, Black-Scholes Greeks, PCR, and Max Pain for {indexSymbol}.
                </p>
                <Link
                  href={`/option-chain?symbol=${encodeURIComponent(indexSymbol)}`}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-indigo-500 text-white text-xs font-semibold hover:bg-indigo-600 transition-colors shadow-md hover:shadow-lg"
                >
                  <span>Open {indexSymbol} Option Chain</span>
                  <ChevronRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Mandate Disclaimer */}
      <div className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-[11px] text-[var(--text-muted)] flex items-start gap-2.5">
        <ShieldCheck className="w-4 h-4 text-blue-500 shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          {indexSymbol} options analysis is generated from real OHLCV market feeds and Python quantitative models.
          This terminal does NOT execute trades or orders. All targets and ranges are probabilistic estimates.
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

      <NextSessionBacktestModal
        isOpen={isBacktestOpen}
        onClose={() => setIsBacktestOpen(false)}
        symbol={indexSymbol}
      />
    </div>
  );
}
