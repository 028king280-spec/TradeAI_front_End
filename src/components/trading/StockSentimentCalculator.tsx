'use client';

import React, { useState } from 'react';
import { Search, Gauge, TrendingUp, Minus, Sparkles, ExternalLink, AlertTriangle, CheckCircle2, Clock, RefreshCw, X, Newspaper, Layers, Crosshair, Database, Filter, Check } from 'lucide-react';
import { newsService, StockSentimentData } from '@/services/newsService';

const POPULAR_STOCKS = [
  { symbol: 'RELIANCE', name: 'Reliance' },
  { symbol: 'TCS', name: 'TCS' },
  { symbol: 'HDFCBANK', name: 'HDFC Bank' },
  { symbol: 'INFY', name: 'Infosys' },
  { symbol: 'TATAMOTORS', name: 'Tata Motors' },
  { symbol: 'ZOMATO', name: 'Zomato' },
  { symbol: 'ITC', name: 'ITC' },
  { symbol: 'SBIN', name: 'SBI' },
];

export const StockSentimentCalculator: React.FC = () => {
  const [searchInput, setSearchInput] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [sentimentData, setSentimentData] = useState<StockSentimentData | null>(null);
  const [searchedSymbol, setSearchedSymbol] = useState<string>('');
  const [selectedSourceFilter, setSelectedSourceFilter] = useState<string>('ALL');

  const handleSearch = async (stockQuery?: string) => {
    const queryToUse = (stockQuery || searchInput).trim();
    if (!queryToUse) return;

    setLoading(true);
    setError(null);
    setSearchedSymbol(queryToUse);
    setSelectedSourceFilter('ALL');

    try {
      const data = await newsService.getStockSentiment(queryToUse);
      if (data) {
        setSentimentData(data);
      } else {
        setError(`Unable to calculate sentiment for "${queryToUse}". Please check the stock name and try again.`);
      }
    } catch (err) {
      setError('An error occurred while fetching news and calculating sentiment.');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  const clearSearch = () => {
    setSearchInput('');
    setSentimentData(null);
    setError(null);
    setSearchedSymbol('');
    setSelectedSourceFilter('ALL');
  };

  const getSentimentColor = (sentiment: string) => {
    switch (sentiment) {
      case 'VERY BULLISH':
      case 'BULLISH':
        return {
          bg: 'bg-emerald-500/10 dark:bg-emerald-500/15',
          border: 'border-emerald-500/30',
          text: 'text-emerald-600 dark:text-emerald-400',
          badgeBg: 'bg-emerald-600 text-[var(--text-primary)]',
          ring: 'ring-emerald-500/20',
        };
      case 'VERY BEARISH':
      case 'BEARISH':
        return {
          bg: 'bg-rose-500/10 dark:bg-rose-500/15',
          border: 'border-rose-500/30',
          text: 'text-rose-600 dark:text-rose-400',
          badgeBg: 'bg-rose-600 text-[var(--text-primary)]',
          ring: 'ring-rose-500/20',
        };
      default:
        return {
          bg: 'bg-[var(--accent-blue)]/10 dark:bg-[var(--accent-blue)]/15',
          border: 'border-[var(--accent-blue)]/30',
          text: 'text-[var(--accent-blue)] dark:text-[var(--accent-blue)]',
          badgeBg: 'bg-[var(--accent-blue)] text-[var(--accent-on)]',
          ring: 'ring-blue-500/20',
        };
    }
  };

  const colors = sentimentData ? getSentimentColor(sentimentData.overallSentiment) : null;

  // Extract unique news sources for the filter
  const availableSources = sentimentData
    ? Array.from(new Set(sentimentData.articles.map((a) => a.source || 'Other')))
    : [];

  const filteredArticles = sentimentData
    ? selectedSourceFilter === 'ALL'
      ? sentimentData.articles
      : sentimentData.articles.filter((a) => a.source === selectedSourceFilter)
    : [];

  return (
    <div className="space-y-6 tabular-nums">
      {/* Search Header Card */}
      <div className="p-6 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-[var(--accent-blue-bg)] dark:bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)] dark:border-[var(--accent-blue)]/20 flex items-center justify-center text-[var(--accent-blue)] dark:text-[var(--accent-blue)] shrink-0">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-[var(--text-primary)] tracking-tight">
                Multi-Source Stock Sentiment Calculator
              </h2>
              <p className="text-xs text-[var(--text-muted)]">
                Cross-checking 10+ financial publications, NSE quotes, & F&O derivatives positioning
              </p>
            </div>
          </div>

          {sentimentData && (
            <button
              onClick={() => handleSearch(searchedSymbol)}
              disabled={loading}
              className="self-start sm:self-auto px-3 py-1.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-hover)] text-xs font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center gap-1.5 transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-[var(--accent-blue)]' : ''}`} />
              <span>Recalculate</span>
            </button>
          )}
        </div>

        {/* Search Input Bar */}
        <div className="flex flex-col sm:flex-row gap-2.5">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search any stock (e.g. RELIANCE, TCS, Tata Motors, HDFC Bank, Zomato)..."
              className="w-full pl-10 pr-10 py-2.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-blue)]/30 focus:border-[var(--accent-blue)] transition-all tabular-nums"
            />
            {searchInput && (
              <button
                onClick={() => setSearchInput('')}
                className="absolute right-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          <button
            onClick={() => handleSearch()}
            disabled={loading || !searchInput.trim()}
            className="px-5 py-2.5 rounded-xl bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)] active:bg-[var(--accent-blue)] disabled:opacity-50 text-[var(--accent-on)] font-semibold text-sm shadow-sm flex items-center justify-center gap-2 transition-all cursor-pointer disabled:cursor-not-allowed shrink-0"
          >
            {loading ? (
              <>
                <div className="w-4 h-4 border-2 border-[var(--border-subtle)] border-t-transparent rounded-full animate-spin" />
                <span>Checking Sources...</span>
              </>
            ) : (
              <>
                <Gauge className="w-4 h-4" />
                <span>Calculate Sentiment</span>
              </>
            )}
          </button>
        </div>

        {/* Quick Search Chips */}
        <div className="flex items-center gap-1.5 flex-wrap pt-1">
          <span className="text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wider mr-1">
            Popular Stocks:
          </span>
          {POPULAR_STOCKS.map((stock) => (
            <button
              key={stock.symbol}
              onClick={() => {
                setSearchInput(stock.symbol);
                handleSearch(stock.symbol);
              }}
              className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-hover)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-strong)] transition-all cursor-pointer"
            >
              {stock.name}
            </button>
          ))}
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="p-4 rounded-xl border border-rose-200 dark:border-rose-500/20 bg-rose-50 dark:bg-rose-500/10 text-xs text-rose-700 dark:text-rose-400 flex items-start gap-2.5">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-rose-600" />
          <div>
            <p className="font-bold">Calculation Notice</p>
            <p>{error}</p>
          </div>
        </div>
      )}

      {/* Loading State */}
      {loading && !sentimentData && (
        <div className="py-16 text-center space-y-4 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
          <div className="w-12 h-12 rounded-2xl bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 flex items-center justify-center mx-auto animate-pulse">
            <Newspaper className="w-6 h-6 text-[var(--accent-blue)] animate-spin" />
          </div>
          <div className="space-y-1">
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              Cross-Checking 10+ Financial Sources for {searchedSymbol}...
            </h3>
            <p className="text-xs text-[var(--text-muted)] max-w-md mx-auto">
              Scanning Economic Times, Moneycontrol, Business Standard, Livemint, NDTV Profit, Investing.com, & NSE F&O flow.
            </p>
          </div>
        </div>
      )}

      {/* Results View */}
      {sentimentData && colors && (
        <div className="space-y-6">
          {/* Sources Verified Banner */}
          {sentimentData.sourcesVerified && sentimentData.sourcesVerified.length > 0 && (
            <div className="p-3.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] flex flex-wrap items-center gap-2 text-xs">
              <span className="font-semibold text-[var(--text-primary)] flex items-center gap-1.5 shrink-0">
                <Database className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
                <span>{sentimentData.sourcesVerified.length} Sources Verified:</span>
              </span>
              <div className="flex flex-wrap gap-1.5">
                {sentimentData.sourcesVerified.map((src, i) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] flex items-center gap-1"
                  >
                    <Check className="w-2.5 h-2.5 text-emerald-500" />
                    {src}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Hero Result Banner */}
          <div
            className={`p-6 rounded-2xl border ${colors.border} ${colors.bg} relative overflow-hidden transition-all shadow-sm`}
          >
            <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-6">
              {/* Left Column: Symbol & Scores */}
              <div className="space-y-3 flex-1">
                <div className="flex items-center gap-2.5 flex-wrap">
                  <span className="text-xl sm:text-2xl font-semibold text-[var(--text-primary)] tracking-tight">
                    {sentimentData.symbol}
                  </span>
                  <span className="text-xs px-2.5 py-0.5 rounded-md font-semibold bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)]">
                    {sentimentData.companyName}
                  </span>
                  <span className={`text-xs px-3 py-1 rounded-full font-semibold ${colors.badgeBg} shadow-xs`}>
                    {sentimentData.overallSentiment} ({sentimentData.ratingLabel})
                  </span>
                  {sentimentData.priceMetrics && (
                    <span className="text-base sm:text-lg font-semibold text-[var(--text-primary)] bg-[var(--bg-surface-elevated)] px-3 py-1 rounded-xl border border-[var(--border-subtle)] flex items-center gap-1.5 shadow-xs">
                      <span>₹{sentimentData.priceMetrics.currentPrice.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
                      <span className={`text-xs font-semibold ${sentimentData.priceMetrics.change >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                        {sentimentData.priceMetrics.change >= 0 ? '+' : ''}{sentimentData.priceMetrics.changePercent.toFixed(2)}%
                      </span>
                      <span className="text-[10px] font-medium text-[var(--text-muted)] ml-1 px-1.5 py-0.5 rounded bg-[var(--bg-surface)] border border-[var(--border-subtle)]">
                        {sentimentData.priceMetrics.isLive ? 'LIVE' : 'EOD'}
                      </span>
                    </span>
                  )}
                </div>

                {/* Score & Gauge Metrics */}
                <div className="flex items-baseline gap-4 flex-wrap">
                  {sentimentData.priceMetrics && (
                    <>
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase block">
                            {sentimentData.priceMetrics.isLive ? 'Live Stock Price (CMP)' : 'Last Verified Close (EOD)'}
                          </span>
                          {!sentimentData.priceMetrics.isLive && sentimentData.priceMetrics.tradingSessionDate && (
                            <span className="text-[10px] font-medium text-[var(--text-muted)] bg-[var(--bg-surface)] px-1.5 py-0.2 rounded border border-[var(--border-subtle)]">
                              Session: {sentimentData.priceMetrics.tradingSessionDate}
                            </span>
                          )}
                        </div>
                        <span className="text-3xl sm:text-4xl font-semibold text-[var(--text-primary)]">
                          ₹{sentimentData.priceMetrics.currentPrice.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                        </span>
                        <span className={`text-xs font-semibold block mt-0.5 ${sentimentData.priceMetrics.change >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                          {sentimentData.priceMetrics.change >= 0 ? '+' : ''}{sentimentData.priceMetrics.change.toFixed(2)} ({sentimentData.priceMetrics.changePercent >= 0 ? '+' : ''}{sentimentData.priceMetrics.changePercent.toFixed(2)}%)
                          {!sentimentData.priceMetrics.isLive && sentimentData.priceMetrics.quoteSource && (
                            <span className="text-[10px] font-normal text-[var(--text-muted)] ml-2">
                              • Source: {sentimentData.priceMetrics.quoteSource}
                            </span>
                          )}
                        </span>
                      </div>

                      <div className="h-8 w-px bg-[var(--border-subtle)] hidden sm:block" />
                    </>
                  )}

                  <div>
                    <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase block">
                      Overall Sentiment Score
                    </span>
                    <span className="text-3xl sm:text-4xl font-semibold text-[var(--text-primary)]">
                      {sentimentData.sentimentScore}
                      <span className="text-sm font-normal text-[var(--text-muted)]"> / 100</span>
                    </span>
                  </div>

                  <div className="h-8 w-px bg-[var(--border-subtle)] hidden sm:block" />

                  <div>
                    <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase block">
                      Net Polarity
                    </span>
                    <span className={`text-2xl font-semibold ${colors.text}`}>
                      {sentimentData.polarityScore > 0 ? `+${sentimentData.polarityScore}` : sentimentData.polarityScore}
                    </span>
                  </div>

                  <div className="h-8 w-px bg-[var(--border-subtle)] hidden sm:block" />

                  <div>
                    <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase block">
                      Confidence
                    </span>
                    <span className="text-sm font-semibold text-[var(--text-primary)]">
                      {sentimentData.confidence} ({sentimentData.totalArticles} articles analyzed)
                    </span>
                  </div>
                </div>

                {/* Sentiment Distribution Bar */}
                <div className="space-y-1.5 pt-2 max-w-md">
                  <div className="flex justify-between text-[11px] text-[var(--text-muted)] font-medium">
                    <span className="text-emerald-600 dark:text-emerald-400">
                      Bullish: {sentimentData.bullishCount} ({sentimentData.bullishRatio}%)
                    </span>
                    <span className="text-[var(--text-muted)]">
                      Neutral: {sentimentData.neutralCount} ({sentimentData.neutralRatio}%)
                    </span>
                    <span className="text-rose-600 dark:text-rose-400">
                      Bearish: {sentimentData.bearishCount} ({sentimentData.bearishRatio}%)
                    </span>
                  </div>
                  <div className="h-2 w-full rounded-full bg-[var(--bg-surface-elevated)] overflow-hidden flex">
                    <div style={{ width: `${sentimentData.bullishRatio}%` }} className="bg-emerald-500 h-full" />
                    <div style={{ width: `${sentimentData.neutralRatio}%` }} className="bg-[var(--bg-surface-elevated)] h-full" />
                    <div style={{ width: `${sentimentData.bearishRatio}%` }} className="bg-rose-500 h-full" />
                  </div>
                </div>
              </div>

              {/* Right Column: Multi-Dimensional Live Cards (Quote & F&O Options Flow) */}
              <div className="flex flex-col sm:flex-row lg:flex-col gap-3 shrink-0">
                {/* 1. Market Quote Snapshot */}
                {sentimentData.priceMetrics && (
                  <div className="p-4 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] min-w-[210px] space-y-2">
                    <div className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider flex items-center justify-between">
                      <span>NSE Spot Quote</span>
                      <span className="text-emerald-500 font-semibold">• {sentimentData.priceMetrics.exchange}</span>
                    </div>
                    <div>
                      <span className="text-xl font-semibold text-[var(--text-primary)]">
                        ₹{sentimentData.priceMetrics.currentPrice.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </span>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span
                          className={`text-xs font-semibold flex items-center ${
                            sentimentData.priceMetrics.change >= 0
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : 'text-rose-600 dark:text-rose-400'
                          }`}
                        >
                          {sentimentData.priceMetrics.change >= 0 ? '+' : ''}
                          {sentimentData.priceMetrics.change.toFixed(2)} (
                          {sentimentData.priceMetrics.changePercent >= 0 ? '+' : ''}
                          {sentimentData.priceMetrics.changePercent.toFixed(2)}%)
                        </span>
                      </div>
                    </div>
                    <div className="pt-2 border-t border-[var(--border-subtle)] flex justify-between text-[10px] text-[var(--text-muted)]">
                      <span>H: ₹{sentimentData.priceMetrics.dayHigh.toFixed(2)}</span>
                      <span>L: ₹{sentimentData.priceMetrics.dayLow.toFixed(2)}</span>
                    </div>
                  </div>
                )}

                {/* 2. Options & F&O Derivatives Flow Snapshot */}
                {sentimentData.optionsMetrics && (
                  <div className="p-4 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] min-w-[210px] space-y-2">
                    <div className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider flex items-center justify-between">
                      <span className="flex items-center gap-1">
                        <Layers className="w-3 h-3 text-[var(--accent-blue)]" />
                        <span>F&O Derivatives Flow</span>
                      </span>
                      <span className="text-[var(--accent-blue)] dark:text-[var(--accent-blue)] font-semibold text-[9px] bg-[var(--accent-blue-bg)] dark:bg-[var(--accent-blue)]/10 px-1.5 py-0.5 rounded">
                        NSE NFO
                      </span>
                    </div>
                    <div className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="text-[var(--text-muted)]">Expiry:</span>
                        <span className="font-semibold text-[var(--text-primary)]">{sentimentData.optionsMetrics.nearestExpiry}</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-[var(--text-muted)]">ATM Strike:</span>
                        <span className="font-semibold text-[var(--text-primary)]">₹{sentimentData.optionsMetrics.atmStrike}</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-[var(--text-muted)]">Est. PCR:</span>
                        <span className={`font-bold ${sentimentData.optionsMetrics.estimatedPcr >= 1.0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                          {sentimentData.optionsMetrics.estimatedPcr}
                        </span>
                      </div>
                    </div>
                    <div className="pt-1.5 border-t border-[var(--border-subtle)] text-[10px] text-[var(--accent-blue)] dark:text-[var(--accent-blue)] font-semibold">
                      {sentimentData.optionsMetrics.derivativesBias}
                    </div>
                  </div>
                )}

                {/* 3. Smart Money Concepts (SMC) Dealing Range & Order Flow Snapshot */}
                {sentimentData.smcMetrics && (
                  <div className="p-4 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] min-w-[210px] space-y-2">
                    <div className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider flex items-center justify-between">
                      <span className="flex items-center gap-1">
                        <Crosshair className="w-3 h-3 text-[var(--accent-blue)]" />
                        <span>SMC Order Flow</span>
                      </span>
                      <span className={`font-semibold text-[9px] px-1.5 py-0.5 rounded ${
                        sentimentData.smcMetrics.regime === 'DISCOUNT'
                          ? 'bg-emerald-500/10 text-emerald-500'
                          : sentimentData.smcMetrics.regime === 'PREMIUM'
                          ? 'bg-rose-500/10 text-rose-500'
                          : 'bg-amber-500/10 text-amber-500'
                      }`}>
                        {sentimentData.smcMetrics.regime}
                      </span>
                    </div>
                    <div className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="text-[var(--text-muted)]">50% Equilibrium:</span>
                        <span className="font-semibold text-[var(--text-primary)]">₹{sentimentData.smcMetrics.equilibrium50}</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-[var(--text-muted)]">Range Pos:</span>
                        <span className="font-semibold text-[var(--accent-blue)]">{sentimentData.smcMetrics.positionPct}%</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-[var(--text-muted)]">SMC Model:</span>
                        <span className="font-semibold text-[var(--text-primary)] text-[10px] truncate max-w-[110px]" title={sentimentData.smcMetrics.modelAlignment}>
                          {sentimentData.smcMetrics.modelAlignment}
                        </span>
                      </div>
                    </div>
                    <div className="pt-1.5 border-t border-[var(--border-subtle)] text-[9.5px] text-[var(--text-secondary)] leading-tight">
                      {sentimentData.smcMetrics.smcOrderFlowBias}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Confluence Verdict Banner */}
            <div className="mt-5 pt-4 border-t border-[var(--border-subtle)]">
              <p className="text-xs sm:text-sm text-[var(--text-primary)] font-medium leading-relaxed">
                <strong className="text-[var(--accent-blue)] dark:text-[var(--accent-blue)] font-semibold">Multi-Source Confluence: </strong>
                {sentimentData.confluenceVerdict}
              </p>
            </div>
          </div>

          {/* Key Drivers & Risk Factors Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Bullish Catalysts */}
            <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-3">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-emerald-500/10 text-emerald-500 flex items-center justify-center">
                  <TrendingUp className="w-4 h-4" />
                </div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-primary)]">
                  Positive Catalysts & Drivers
                </h3>
              </div>
              <ul className="space-y-2">
                {sentimentData.keyDrivers.map((driver, idx) => (
                  <li key={idx} className="text-xs text-[var(--text-secondary)] flex items-start gap-2 leading-relaxed">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0 mt-0.5" />
                    <span>{driver}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Risk Factors */}
            <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-3">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-rose-500/10 text-rose-500 flex items-center justify-center">
                  <AlertTriangle className="w-4 h-4" />
                </div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-primary)]">
                  Risk Factors & Headwinds
                </h3>
              </div>
              <ul className="space-y-2">
                {sentimentData.riskFactors.map((risk, idx) => (
                  <li key={idx} className="text-xs text-[var(--text-secondary)] flex items-start gap-2 leading-relaxed">
                    <Minus className="w-3.5 h-3.5 text-rose-500 shrink-0 mt-0.5" />
                    <span>{risk}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Verified News Articles Section with Source Filters */}
          <div className="p-6 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <Newspaper className="w-4 h-4 text-[var(--accent-blue)]" />
                <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
                  Verified News Articles ({filteredArticles.length} / {sentimentData.articles.length})
                </h3>
              </div>

              {/* Source Filter Chips */}
              {availableSources.length > 1 && (
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase mr-1 flex items-center gap-1">
                    <Filter className="w-3 h-3" /> Filter:
                  </span>
                  <button
                    onClick={() => setSelectedSourceFilter('ALL')}
                    className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-all ${
                      selectedSourceFilter === 'ALL'
                        ? 'bg-[var(--accent-blue)] text-[var(--accent-on)]'
                        : 'bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                    }`}
                  >
                    All ({sentimentData.articles.length})
                  </button>
                  {availableSources.map((src) => (
                    <button
                      key={src}
                      onClick={() => setSelectedSourceFilter(src)}
                      className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-all ${
                        selectedSourceFilter === src
                          ? 'bg-[var(--accent-blue)] text-[var(--accent-on)]'
                          : 'bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                      }`}
                    >
                      {src}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {filteredArticles.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)] py-4 text-center">
                No articles match the selected source filter.
              </p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {filteredArticles.map((item) => (
                  <div
                    key={item.id}
                    className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] hover:border-[var(--border-strong)] transition-all flex flex-col justify-between gap-3 group"
                  >
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[10px] font-semibold text-[var(--accent-blue)] dark:text-[var(--accent-blue)] uppercase tracking-wider bg-[var(--accent-blue-bg)] dark:bg-[var(--accent-blue)]/10 px-2 py-0.5 rounded">
                          {item.source}
                        </span>
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`text-[9px] px-2 py-0.5 rounded font-semibold uppercase ${
                              item.sentiment === 'BULLISH'
                                ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                                : item.sentiment === 'BEARISH'
                                ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
                                : 'bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] dark:text-[var(--text-secondary)]'
                            }`}
                          >
                            {item.sentiment}
                          </span>
                          <span className="text-[9px] px-1.5 py-0.5 rounded font-semibold bg-gray-100 dark:bg-gray-800 text-[var(--text-muted)]">
                            {item.impact} IMPACT
                          </span>
                        </div>
                      </div>

                      <h4 className="text-xs font-semibold text-[var(--text-primary)] leading-snug line-clamp-2 group-hover:text-[var(--accent-blue)] dark:group-hover:text-[var(--accent-blue)] transition-colors">
                        {item.headline}
                      </h4>
                    </div>

                    <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)] pt-2 border-t border-[var(--border-subtle)]">
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {item.publishedAt ? new Date(item.publishedAt).toLocaleDateString('en-IN') : 'Recent'}
                      </span>
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[var(--accent-blue)] hover:text-[var(--accent-blue)] flex items-center gap-1 font-semibold hover:underline"
                        >
                          <span>Read Source</span>
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Initial Empty State (Before Search) */}
      {!sentimentData && !loading && !error && (
        <div className="py-12 text-center space-y-3 rounded-2xl border border-dashed border-[var(--border-subtle)] bg-[var(--bg-surface)]">
          <div className="w-12 h-12 rounded-2xl bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 flex items-center justify-center mx-auto text-[var(--accent-blue)]">
            <Search className="w-6 h-6" />
          </div>
          <div className="space-y-1">
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              Cross-Check Live Sentiment from 10+ Institutional Sources
            </h3>
            <p className="text-xs text-[var(--text-muted)] max-w-lg mx-auto leading-relaxed">
              Type any stock (e.g., <strong>Reliance</strong>, <strong>Tata Motors</strong>, <strong>TCS</strong>, <strong>HDFC Bank</strong>, <strong>Zomato</strong>) to simultaneously cross-check news across Economic Times, Moneycontrol, Business Standard, Livemint, NDTV Profit, Investing.com, plus real-time NSE spot quotes and F&O derivatives flow.
            </p>
          </div>
        </div>
      )}
    </div>
  );
};
