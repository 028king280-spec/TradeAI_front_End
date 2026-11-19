'use client';
import { PageHeading } from "@/components/shared/PageHeading";

import React, { useState, useEffect, use } from 'react';
import Link from 'next/link';
import { ArrowUpRight, ArrowDownRight, ShieldCheck, Layers, RefreshCw, ChevronRight, BarChart3, Loader2 } from 'lucide-react';
import { optionsService } from '@/services/optionsService';
import { IndexAnalysisFullResponse } from '@/types/options';
import { OptionsCandlestickChart } from '@/components/trading/OptionsCandlestickChart';
import { ResearchSetupCard } from '@/components/trading/ResearchSetupCard';
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
import { MarketStatePanel } from '@/components/trading/MarketStatePanel';
import { SignalActivationPanel, SignalActivationData } from '@/components/trading/SignalActivationPanel';
import { ActiveSignalTracker, TrackedSignalItem } from '@/components/trading/ActiveSignalTracker';
import { SignalTimelineModal } from '@/components/trading/SignalTimelineModal';
import { FailureAnalysisModal } from '@/components/trading/FailureAnalysisModal';
import { MLStrategyLearnerPanel } from '@/components/trading/MLStrategyLearnerPanel';
import { MacroEventCalendarCard } from '@/components/trading/MacroEventCalendarCard';

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
        const sigRes = await fetch('/api/signals/today');
        if (sigRes.ok) {
          const sigJson = await sigRes.json();
          if (!isCancelled && sigJson.success && sigJson.data?.trackedOptionSetups) {
            setTrackedSignals(sigJson.data.trackedOptionSetups);
          }
        }
      } catch {
        // Silently handle if backend is reconnecting
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
    let chosenSetup = setups && setups.length > 0 ? setups[0] : null;

    // 60-Point Research Setup integration (60% Confluence Hurdle)
    const researchCandidate = analysis?.researchSetup?.qualified ? analysis.researchSetup.setup : null;
    if (!chosenSetup && researchCandidate) {
      const optType = researchCandidate.contractSymbol.endsWith('CE') ? 'CE' : 'PE';
      chosenSetup = {
        bias: optType,
        contractSymbol: researchCandidate.contractSymbol,
        strike: Math.round(currentPrice / 50) * 50,
        expiry: 'Current Expiry',
        currentPremium: researchCandidate.entryPremium,
        suggestedEntryMin: Math.round(researchCandidate.entryPremium * 0.98 * 10) / 10,
        suggestedEntryMax: Math.round(researchCandidate.entryPremium * 1.02 * 10) / 10,
        stopLoss: researchCandidate.stopLoss,
        target1: researchCandidate.targetPremium,
        target2: Math.round(researchCandidate.targetPremium * 1.15 * 10) / 10,
        target3: Math.round(researchCandidate.targetPremium * 1.30 * 10) / 10,
        riskRewardRatio: `${researchCandidate.grossRewardRisk.toFixed(1)}:1`,
        underlyingTrigger: '60-Point Confluence Research Trigger',
        invalidationCondition: `Premium drops below SL ₹${researchCandidate.stopLoss.toFixed(2)}`,
        supportingReasons: ['60-Point Confluence Research Engine Setup (+30% Target)'],
      } as any;
    }

    if (marketState?.isNoTrade || !chosenSetup) {
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

    const isCall = chosenSetup.bias === 'CE';
    return {
      index: indexSymbol,
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
      riskRewardRatio: chosenSetup.riskRewardRatio,
      entryCondition: chosenSetup.underlyingTrigger,
      invalidationCondition: chosenSetup.invalidationCondition,
      supportingReasons: chosenSetup.supportingReasons,
      dataTimestamp: analysis.dataTimestamp,
      dataStatus: analysis.dataStatus,
    };
  }, [analysis, indexSymbol, currentPrice]);

  const filteredTrackedSignals = trackedSignals.filter(
    (s) => s.symbol.toUpperCase() === indexSymbol.toUpperCase() || s.symbol.toUpperCase().includes(rawIndex)
  );

  const isMarketClosed =
    analysis?.dataStatus === 'MARKET_CLOSED' ||
    (analysis as any)?.marketCalendar === 'CLOSED';

  const isDataOffline =
    analysis?.dataStatus === 'DATA_OFFLINE' ||
    analysis?.dataStatus === 'DATA_UNAVAILABLE' ||
    analysis?.dataStatus === 'STALE_TICK';

  return (
    <div className="space-y-6 pb-12">
      {/* Top Header Bar */}
      <PageHeading title={`${indexSymbol} terminal`} description="Price action, structure and evidence in one focused workspace." actions={<><span className="workspace-pill">{analysis?.dataStatus || 'Checking data'}</span><div className="flex items-center gap-3 flex-wrap">
          {analysis?.quote && (
            <div className="flex items-center gap-4 bg-[var(--bg-surface-elevated)] px-4 py-2.5 rounded-xl border border-[var(--border-subtle)]">
              <div>
                <span className="text-[10px] text-[var(--text-muted)] block font-medium">Spot LTP</span>
                <span className="text-base font-semibold text-[var(--text-primary)] tabular-nums">
                  ₹{currentPrice.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </span>
              </div>
              <div className="w-px h-8 bg-[var(--border-subtle)]" />
              <div>
                <span className="text-[10px] text-[var(--text-muted)] block font-medium">Change</span>
                <span
                  className={`text-base font-semibold flex items-center gap-1 tabular-nums ${
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
            className="px-3.5 py-2.5 rounded-xl bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)] text-[var(--accent-on)] text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-md hover:shadow-lg"
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
        </div></>}/>

      {/* Index Switcher Tabs */}
      <div className="flex items-center gap-2 border-b border-[var(--border-subtle)] pb-2 overflow-x-auto">
        {[
          { label: 'NIFTY 50', href: '/options/nifty' },
          { label: 'BANK NIFTY', href: '/options/banknifty' },
          { label: 'FINNIFTY', href: '/options/finnifty' },
          { label: 'SENSEX', href: '/options/sensex' },
        ].map((tab) => {
          const isActive =
            indexSymbol.toUpperCase() === tab.label ||
            (tab.label === 'SENSEX' && indexSymbol.toUpperCase().includes('SENSEX'));
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                isActive
                  ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] shadow-sm'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-elevated)]'
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </div>

      {/* Institutional Market Closed Banner (Decision 3) */}
      {isMarketClosed && (
        <div className="flex items-center justify-between p-3.5 rounded-xl bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/25 text-[var(--accent-blue)] dark:text-[var(--accent-blue)] text-xs">
          <div className="flex items-center gap-2.5">
            <span className="w-2.5 h-2.5 rounded-full bg-[var(--accent-blue)] shrink-0" />
            <div>
              <span className="font-semibold uppercase tracking-wider text-[11px] block">
                MARKET CLOSED — Verified End-Of-Day (EOD) Snapshot
              </span>
              <span className="text-[11px] opacity-90">
                NSE/BSE trading session is closed. Showing official closing settlement prices. Live order execution is paused until next trading session.
              </span>
            </div>
          </div>
          <span className="px-2.5 py-1 rounded-md bg-[var(--accent-blue)]/15 tabular-nums text-[10px] font-semibold shrink-0">
            STAGE 1 PRE-MARKET
          </span>
        </div>
      )}

      {/* Data Gating / Offline Warning Banner */}
      {!isMarketClosed && isDataOffline && (
        <div className="flex items-center justify-between p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/25 text-rose-700 dark:text-rose-300 text-xs">
          <div className="flex items-center gap-2.5">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500 animate-pulse shrink-0" />
            <div>
              <span className="font-semibold uppercase tracking-wider text-[11px] block">
                DATA INTEGRITY WARNING — FEED {analysis?.dataStatus}
              </span>
              <span className="text-[11px] opacity-90">
                Live exchange quotes are currently disconnected or degraded. To protect capital, automatic setup qualification and paper trading order execution are strictly suspended.
              </span>
            </div>
          </div>
          <span className="px-2.5 py-1 rounded-md bg-rose-500/20 tabular-nums text-[10px] font-semibold text-rose-600 dark:text-rose-400 shrink-0">
            SIGNALS GATED
          </span>
        </div>
      )}

      {loading && !analysis ? (
        <div className="flex flex-col items-center justify-center min-h-[50vh] space-y-4">
          <div className="w-12 h-12 rounded-2xl bg-[var(--accent-blue-bg)] dark:bg-[var(--accent-blue)]/10 flex items-center justify-center">
            <Loader2 className="w-6 h-6 text-[var(--accent-blue)] animate-spin" />
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

          {/* Machine Learning Strategy Learner & Adaptive Accuracy Scorecard */}
          <MLStrategyLearnerPanel indexSymbol={indexSymbol} />

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

          {/* Macroeconomic Event Intelligence & Proximity Radar (REQ-6.11) */}
          <MacroEventCalendarCard currentIndex={indexSymbol} />

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

              {analysis.smcAnalysis && (
                <SmartMoneyConceptsCard data={analysis.smcAnalysis} />
              )}

              <OptionsSetupsCard data={analysis.todayOptionsSetups} />
              <ResearchSetupCard data={analysis.researchSetup} indexSymbol={indexSymbol} />

              <PaperTradingSimulator />

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
              <div className="p-5 rounded-2xl border border-[var(--accent-blue)] dark:border-[var(--accent-blue)]/20 bg-gradient-to-br from-[var(--accent-blue)]/80 via-purple-50/30 to-transparent dark:from-[var(--accent-blue)]/8 dark:via-purple-500/4 dark:to-transparent space-y-3">
                <div className="flex items-center gap-2 text-[var(--accent-blue)] dark:text-[var(--accent-blue)] font-semibold text-xs uppercase tracking-wider">
                  <Layers className="w-4 h-4" />
                  <span>Option Chain</span>
                </div>
                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                  Inspect strike-by-strike open interest, Black-Scholes Greeks, PCR, and Max Pain for {indexSymbol}.
                </p>
                <Link
                  href={`/option-chain?symbol=${encodeURIComponent(indexSymbol)}`}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-[var(--accent-blue)] text-[var(--accent-on)] text-xs font-semibold hover:bg-[var(--accent-blue)] transition-colors shadow-md hover:shadow-lg"
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
        <ShieldCheck className="w-4 h-4 text-[var(--accent-blue)] shrink-0 mt-0.5" />
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
