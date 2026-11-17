'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { ArrowRight, ArrowUpRight, BrainCircuit, Layers, RefreshCw, ShieldCheck, Sparkles, Wallet } from 'lucide-react';
import { optionsService } from '@/services/optionsService';
import {
  OptionsOverviewResponse,
  IndexAnalysisFullResponse,
} from '@/types/options';
import { LiveAnalysisChart } from '@/components/trading/LiveAnalysisChart';
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
import { MarketNewsCard } from '@/components/trading/MarketNewsCard';
import { MarketStatePanel } from '@/components/trading/MarketStatePanel';
import { SignalActivationPanel, SignalActivationData } from '@/components/trading/SignalActivationPanel';
import { ActiveSignalTracker, TrackedSignalItem } from '@/components/trading/ActiveSignalTracker';
import { SignalTimelineModal } from '@/components/trading/SignalTimelineModal';
import { FailureAnalysisModal } from '@/components/trading/FailureAnalysisModal';
import { MLStrategyLearnerPanel } from '@/components/trading/MLStrategyLearnerPanel';

import { PageHeading } from '@/components/shared/PageHeading';
import { WorkspaceTabs } from '@/components/shared/WorkspaceTabs';
import { MarketQuoteCard } from '@/components/shared/MarketQuoteCard';
import { feedLabel } from '@/context/MarketFeedContext';

export default function OptionsDashboardPage() {
  const [view, setView] = useState('Overview');
  const [overview, setOverview] = useState<OptionsOverviewResponse | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<string>('NIFTY 50');
  const [analysisData, setAnalysis] = useState<IndexAnalysisFullResponse | null>(null);
  const [loadingOverview, setLoadingOverview] = useState<boolean>(true);
  const [loadingAnalysis, setLoadingAnalysis] = useState<boolean>(true);
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);
  const [isBacktestOpen, setIsBacktestOpen] = useState<boolean>(false);
  const [trackedSignals, setTrackedSignals] = useState<TrackedSignalItem[]>([]);
  const [selectedTimelineSignalId, setSelectedTimelineSignalId] = useState<string | null>(null);
  const [selectedFailureSignalId, setSelectedFailureSignalId] = useState<string | null>(null);
  const [selectedSignalBias, setSelectedSignalBias] = useState<'CE' | 'PE' | 'AUTO'>('AUTO');

  const canonical = (value: string) => value.toUpperCase().replace(/[^A-Z0-9]/g, '').replace(/^NIFTY$/, 'NIFTY50').replace(/^NIFTYBANK$/, 'BANKNIFTY');
  const analysis = analysisData && canonical(analysisData.symbol) === canonical(selectedIndex) ? analysisData : null;

  // 1. Load Overview Data (Index Cards + Overall Sentiment)
  useEffect(() => {
    let isCancelled = false;
    async function loadOverview() {
      setLoadingOverview(true);
      const data = await optionsService.getOverview();
      if (!isCancelled) {
        if (data) setOverview(data);
        setLoadingOverview(false);
      }
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
      if (!isCancelled) {
        if (data) setAnalysis(data);
        setLoadingAnalysis(false);
      }
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

  const activeQuote = overview?.indices?.find(quote => canonical(quote.symbol) === canonical(selectedIndex));

  const currentPrice = activeQuote?.currentValue || 0;

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

  const displayIndices = overview?.indices?.length ? overview.indices : ['NIFTY 50', 'BANK NIFTY', 'FINNIFTY', 'SENSEX'].map(symbol => ({ symbol, currentValue: null, change: null, changePercent: null, sparkline: [], dataStatus: 'UNAVAILABLE' }));
  const marketState = analysis?.marketState;
  const refresh = () => setRefreshTrigger(value => value + 1);
  const contextLabel = loadingAnalysis ? 'Reading the market…' : marketState?.headline || 'Waiting for market evidence';

  return <div className="space-y-6 pb-8">
    <PageHeading title="Market overview" description="A clearer view of the market. A more deliberate next move." actions={<>
      <span className="workspace-pill"><ShieldCheck size={13}/> Paper mode</span>
      <button className="workspace-secondary-button" onClick={refresh} disabled={loadingOverview || loadingAnalysis}><RefreshCw size={14} className={loadingOverview || loadingAnalysis ? 'animate-spin' : ''}/> Refresh data</button>
    </>}/>

    <div className="workspace-quote-grid" aria-label="Index watchlist">
      {displayIndices.map(quote => <MarketQuoteCard key={quote.symbol} symbol={quote.symbol} value={quote.currentValue} change={quote.change} changePercent={quote.changePercent} dataStatus={quote.dataStatus || overview?.dataStatus || 'UNAVAILABLE'} sparkline={quote.sparkline} selected={selectedIndex === quote.symbol} onSelect={() => { if (quote.symbol !== 'INDIA VIX') setSelectedIndex(quote.symbol === 'NIFTY' ? 'NIFTY 50' : quote.symbol); }}/>)}
    </div>

    <WorkspaceTabs tabs={['Overview', 'Signals', 'Structure', 'Outlook', 'Learning', 'Paper trading']} value={view} onChange={setView}>
      {view === 'Overview' && <div className="space-y-6">
        <div className="workspace-overview-grid">
          <div className="workspace-stack">
            <LiveAnalysisChart symbol={selectedIndex} currentPrice={currentPrice || undefined} supportLevel={analysis?.supportResistance?.support1?.price} resistanceLevel={analysis?.supportResistance?.resistance1?.price}/>
            {analysis?.todayOptionsSetups ? <OptionsSetupsCard data={analysis.todayOptionsSetups}/> : <div className="workspace-empty">{loadingAnalysis ? 'Loading setups from the analysis engine…' : 'No setup data is available. Refresh when the analysis feed is connected.'}</div>}
            <ResearchSetupCard data={analysis?.researchSetup}/>
          </div>
          <aside className="workspace-stack" aria-label="Market context">
            <section className="workspace-panel workspace-copilot">
              <div className="workspace-panel-heading"><div><p className="workspace-eyebrow">Aivolve intelligence</p><h2>Your market copilot</h2></div><Sparkles size={18} className="text-[var(--accent-blue)]"/></div>
              <div className="workspace-copilot-icon"><BrainCircuit size={27}/></div>
              <h3>{contextLabel}</h3>
              <p>{marketState?.explanation || 'A connected quantitative feed will provide the market regime, confirmation conditions and supporting evidence here.'}</p>
              <div className="mt-4"><span className="workspace-pill">{feedLabel(analysis?.dataStatus || 'UNAVAILABLE')}</span></div>
              <button onClick={() => setView('Structure')} className="workspace-primary-button">Explore the evidence <ArrowUpRight size={14}/></button>
            </section>
            <section className="workspace-panel"><div className="workspace-panel-heading"><h2>Market watch</h2><Layers size={16} className="text-[var(--text-muted)]"/></div>
              {displayIndices.map(quote => <button type="button" className="workspace-watch-row" key={quote.symbol} onClick={() => { if (quote.symbol !== 'INDIA VIX') setSelectedIndex(quote.symbol); }}><span><b>{quote.symbol}</b><small>{feedLabel(quote.dataStatus || 'UNAVAILABLE')}</small></span><span><b>{quote.currentValue ? quote.currentValue.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</b>{typeof quote.changePercent === 'number' && <small style={{ color: quote.changePercent >= 0 ? 'var(--bullish)' : 'var(--bearish)' }}>{quote.changePercent >= 0 ? '+' : ''}{quote.changePercent.toFixed(2)}%</small>}</span></button>)}
              <Link className="workspace-text-link" href={`/option-chain?symbol=${encodeURIComponent(selectedIndex)}`}>Explore option chain <ArrowRight size={14}/></Link>
            </section>
          </aside>
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">{analysis?.sentiment && <MarketSentimentPanel sentiment={analysis.sentiment}/>}<section className="workspace-panel"><div className="workspace-panel-heading"><h2>Your paper workspace</h2><Wallet size={18}/></div><p className="text-xs leading-7 text-[var(--text-secondary)]">Practice entries, review open positions and follow the risk checks using virtual capital. Live broker order routing remains disabled.</p><Link className="workspace-text-link" href="/paper-trading">Open paper trading <ArrowRight size={14}/></Link></section></div>
      </div>}
      {view === 'Signals' && <div className="space-y-6">
        {marketState && <MarketStatePanel data={marketState}/>}
        <SignalActivationPanel data={activeSignalData} selectedBias={selectedSignalBias} onSelectBias={setSelectedSignalBias} onOpenTimeline={() => { if (trackedSignals.length) setSelectedTimelineSignalId(trackedSignals[0].id); }}/>
        <ActiveSignalTracker signals={trackedSignals} onSelectSignalTimeline={setSelectedTimelineSignalId} onSelectFailureAnalysis={setSelectedFailureSignalId}/>
        {analysis?.todayOptionsSetups && <OptionsSetupsCard data={analysis.todayOptionsSetups}/>}
        <ResearchSetupCard data={analysis?.researchSetup}/>
      </div>}
      {view === 'Structure' && <div className="space-y-6">
        {marketState && <MarketStatePanel data={marketState}/>}
        <div className="workspace-overview-grid"><div className="workspace-stack">{analysis?.smcAnalysis && <SmartMoneyConceptsCard data={analysis.smcAnalysis}/>}{analysis?.patterns && <ChartPatternsCard patterns={analysis.patterns}/>}</div><div>{analysis?.supportResistance && <SupportResistanceLadderView data={analysis.supportResistance} currentPrice={currentPrice}/>}</div></div>
        {!analysis && <div className="workspace-empty">Market structure is unavailable until the analysis feed responds.</div>}
      </div>}
      {view === 'Outlook' && <div className="space-y-6">
        {(analysis?.nextSessionRecommendation || overview?.nextSessionRecommendation) && <NextSessionRecommendationCard data={analysis?.nextSessionRecommendation || overview?.nextSessionRecommendation!} onOpenBacktest={() => setIsBacktestOpen(true)}/>}
        {(analysis?.nextSessionOpeningOutlook || overview?.nextSessionOpeningOutlook) && <NextSessionOpeningCard outlook={analysis?.nextSessionOpeningOutlook || overview?.nextSessionOpeningOutlook!} indexSymbol={selectedIndex}/>}
        {analysis?.todayOutlook && analysis?.nextSessionOutlook && <SessionOutlookCard todayData={analysis.todayOutlook} nextSessionData={analysis.nextSessionOutlook}/>}
        <MarketNewsCard initialSymbol={selectedIndex}/>
      </div>}
      {view === 'Learning' && <MLStrategyLearnerPanel indexSymbol={selectedIndex}/>}
      {view === 'Paper trading' && <PaperTradingSimulator/>}
    </WorkspaceTabs>
    <SignalTimelineModal signalId={selectedTimelineSignalId} onClose={() => setSelectedTimelineSignalId(null)}/>
    <FailureAnalysisModal signalId={selectedFailureSignalId} onClose={() => setSelectedFailureSignalId(null)}/>
    <NextSessionBacktestModal isOpen={isBacktestOpen} onClose={() => setIsBacktestOpen(false)} symbol={selectedIndex}/>
  </div>;
}
