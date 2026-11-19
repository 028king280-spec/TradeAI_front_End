'use client';

import React, { useState, useEffect, useMemo } from 'react';
import {
  Newspaper,
  TrendingUp,
  TrendingDown,
  Sparkles,
  ExternalLink,
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  Clock,
  RefreshCw,
  X,
  Filter,
  Search,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  Info,
  Radio,
  Flame,
  Activity,
  BookmarkCheck
} from 'lucide-react';
import { newsService, IntradayStockOpportunity, StockNewsArticle } from '@/services/newsService';
import { formatINR } from '@/lib/utils';

type TabType = 'overall' | 'bullish' | 'bearish' | 'stream' | 'watchlist';

export const Top10NewsScanner: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('overall');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [stocks, setStocks] = useState<IntradayStockOpportunity[]>([]);
  const [selectedStock, setSelectedStock] = useState<IntradayStockOpportunity | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedSector, setSelectedSector] = useState<string>('ALL');
  const [selectedConfirmation, setSelectedConfirmation] = useState<string>('ALL');
  const [lastRefreshed, setLastRefreshed] = useState<string>('');
  const [totalAnalyzed, setTotalAnalyzed] = useState<number>(0);
  const [refreshCount, setRefreshCount] = useState<number>(0);

  // Load Top Stocks Data from API
  useEffect(() => {
    let isCancelled = false;
    async function loadData() {
      setLoading(true);
      setError(null);
      try {
        const direction = activeTab === 'bullish' ? 'bullish' : activeTab === 'bearish' ? 'bearish' : 'all';
        const res = await newsService.getIntradayTopStocks(direction, 10);
        if (!isCancelled) {
          if (res && Array.isArray(res.stocks)) {
            setStocks(res.stocks);
            setTotalAnalyzed(res.totalArticlesAnalyzed || 0);
            setLastRefreshed(new Date(res.generatedAt).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' }));
          } else {
            setStocks([]);
          }
        }
      } catch (err: any) {
        if (!isCancelled) {
          setError('Failed to fetch intraday news opportunities. Check backend connectivity.');
        }
      } finally {
        if (!isCancelled) {
          setLoading(false);
        }
      }
    }
    loadData();
    return () => {
      isCancelled = true;
    };
  }, [activeTab, refreshCount]);

  // Escape key closes modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSelectedStock(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Extract unique sectors for filter
  const sectors = useMemo(() => {
    const set = new Set<string>();
    stocks.forEach((s) => {
      if (s.sector) set.add(s.sector);
    });
    return Array.from(set);
  }, [stocks]);

  // Filtered stocks list
  const filteredStocks = useMemo(() => {
    return stocks.filter((s) => {
      // Sector filter
      if (selectedSector !== 'ALL' && s.sector !== selectedSector) return false;
      // Confirmation filter
      if (selectedConfirmation === 'CONFIRMED' && !s.priceConfirmation.includes('CANDIDATE')) return false;
      if (selectedConfirmation === 'DIVERGENCE' && s.priceConfirmation !== 'NEWS_PRICE_DIVERGENCE') return false;
      if (selectedConfirmation === 'UNVERIFIED' && s.priceConfirmation !== 'PRICE_UNVERIFIED') return false;
      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesSym = s.symbol.toLowerCase().includes(q);
        const matchesName = s.companyName.toLowerCase().includes(q);
        const matchesHead = s.primaryHeadline.toLowerCase().includes(q);
        if (!matchesSym && !matchesName && !matchesHead) return false;
      }
      return true;
    });
  }, [stocks, selectedSector, selectedConfirmation, searchQuery]);

  // Stream View: flatten all articles from candidate stocks
  const streamArticles = useMemo(() => {
    const list: (StockNewsArticle & { symbol: string; companyName: string })[] = [];
    stocks.forEach((s) => {
      s.articles.forEach((a) => {
        list.push({ ...a, symbol: s.symbol, companyName: s.companyName });
      });
    });
    list.sort((a, b) => b.impact - a.impact);
    return list;
  }, [stocks]);

  return (
    <div className="space-y-5 tabular-nums">
      {/* SECTION HEADER & CONTROL BAR */}
      <div className="p-5 rounded-2xl bg-[var(--bg-surface)] dark:bg-[var(--bg-surface)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] shadow-xs space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-3 border-b border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="p-1.5 rounded-lg bg-purple-500/10 text-purple-600 dark:text-purple-400 border border-purple-500/20">
                <Flame className="w-4 h-4" />
              </span>
              <h2 className="text-base font-bold text-[var(--text-primary)] dark:text-[var(--text-primary)]">
                AI NEWS SENTIMENT & INTRADAY STOCK OPPORTUNITY SCANNER
              </h2>
            </div>
            <p className="text-xs text-[var(--text-secondary)] dark:text-[var(--text-secondary)]">
              Real-time Indian financial news ingestion, deterministic event classification, and live market price confirmation.
            </p>
          </div>

          <div className="flex items-center gap-2.5 flex-wrap text-xs">
            <span className="px-2.5 py-1 rounded-md bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] flex items-center gap-1.5">
              <Radio className="w-3 h-3 text-emerald-500 animate-pulse" />
              <span>Feeds: 9 Verified Sources</span>
            </span>
            <span className="px-2.5 py-1 rounded-md bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] flex items-center gap-1.5">
              <Clock className="w-3 h-3 text-[var(--accent-blue)]" />
              <span>Refreshed: {lastRefreshed || 'Syncing...'}</span>
            </span>
            <button
              onClick={() => setRefreshCount((p) => p + 1)}
              disabled={loading}
              className="px-3 py-1 rounded-lg bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/90 text-[var(--accent-on)] font-semibold transition-all flex items-center gap-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              <span>Scan Now</span>
            </button>
          </div>
        </div>

        {/* NAVIGATION TABS */}
        <div className="flex items-center justify-between gap-2 flex-wrap pt-1">
          <div className="inline-flex rounded-xl bg-[var(--bg-surface-elevated)] p-1 border border-[var(--border-subtle)] text-xs gap-1 flex-wrap">
            <button
              onClick={() => setActiveTab('overall')}
              className={`px-3.5 py-1.5 rounded-lg font-semibold transition-all flex items-center gap-1.5 ${
                activeTab === 'overall'
                  ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] shadow-xs'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              <Flame className="w-3.5 h-3.5 text-amber-400" />
              <span>Top 10 Overall Impact</span>
            </button>
            <button
              onClick={() => setActiveTab('bullish')}
              className={`px-3.5 py-1.5 rounded-lg font-semibold transition-all flex items-center gap-1.5 ${
                activeTab === 'bullish'
                  ? 'bg-emerald-600 text-white shadow-xs'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              <TrendingUp className="w-3.5 h-3.5 text-emerald-300" />
              <span>Top 10 Bullish News</span>
            </button>
            <button
              onClick={() => setActiveTab('bearish')}
              className={`px-3.5 py-1.5 rounded-lg font-semibold transition-all flex items-center gap-1.5 ${
                activeTab === 'bearish'
                  ? 'bg-rose-600 text-white shadow-xs'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              <TrendingDown className="w-3.5 h-3.5 text-rose-300" />
              <span>Top 10 Bearish News</span>
            </button>
            <button
              onClick={() => setActiveTab('stream')}
              className={`px-3.5 py-1.5 rounded-lg font-semibold transition-all flex items-center gap-1.5 ${
                activeTab === 'stream'
                  ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] shadow-xs'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              <Newspaper className="w-3.5 h-3.5" />
              <span>Latest High-Impact News</span>
            </button>
            <button
              onClick={() => setActiveTab('watchlist')}
              className={`px-3.5 py-1.5 rounded-lg font-semibold transition-all flex items-center gap-1.5 ${
                activeTab === 'watchlist'
                  ? 'bg-purple-600 text-white shadow-xs'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              <BookmarkCheck className="w-3.5 h-3.5" />
              <span>Intraday Watchlist</span>
            </button>
          </div>

          <div className="text-[11px] text-[var(--text-muted)] dark:text-[var(--text-secondary)]">
            Total Articles Analyzed: <strong className="text-[var(--text-primary)]">{totalAnalyzed}</strong> | Qualified: <strong className="text-[var(--text-primary)]">{filteredStocks.length}</strong>
          </div>
        </div>

        {/* FILTER & SEARCH BAR */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 text-xs">
          {/* Search Input */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              type="text"
              placeholder="Search stock by symbol, company or headline..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-blue)]"
            />
          </div>

          {/* Sector Filter */}
          <div className="flex items-center gap-2">
            <Filter className="w-3.5 h-3.5 text-[var(--text-muted)] shrink-0" />
            <select
              value={selectedSector}
              onChange={(e) => setSelectedSector(e.target.value)}
              className="w-full px-2.5 py-1.5 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] focus:outline-none"
            >
              <option value="ALL">All Sectors</option>
              {sectors.map((sec) => (
                <option key={sec} value={sec}>
                  {sec}
                </option>
              ))}
            </select>
          </div>

          {/* Price Confirmation Filter */}
          <div>
            <select
              value={selectedConfirmation}
              onChange={(e) => setSelectedConfirmation(e.target.value)}
              className="w-full px-2.5 py-1.5 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] focus:outline-none"
            >
              <option value="ALL">All Price Confirmations</option>
              <option value="CONFIRMED">Price Confirmed Only</option>
              <option value="DIVERGENCE">News/Price Divergence Only</option>
              <option value="UNVERIFIED">Price Unverified / Offline</option>
            </select>
          </div>
        </div>
      </div>

      {/* ERROR OR LOADING NOTICES */}
      {error && (
        <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-500 text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {loading && !stocks.length && (
        <div className="p-12 rounded-2xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] flex flex-col items-center justify-center space-y-3">
          <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
          <p className="text-xs text-[var(--text-secondary)]">
            Scanning 9 Tier-1 Indian financial news feeds and matching NSE equity scrips...
          </p>
        </div>
      )}

      {/* VIEW A: TOP 10 OPPORTUNITY CARDS & TABLE */}
      {(activeTab === 'overall' || activeTab === 'bullish' || activeTab === 'bearish' || activeTab === 'watchlist') && (
        <div className="space-y-3">
          {filteredStocks.length === 0 && !loading ? (
            <div className="p-8 rounded-2xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-center space-y-2">
              <ShieldAlert className="w-8 h-8 text-amber-500 mx-auto" />
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                NO QUALIFIED STOCKS FOUND FOR CURRENT FILTER
              </h3>
              <p className="text-xs text-[var(--text-secondary)] max-w-md mx-auto">
                Rule Mandate: We do not force a full list of 10 if fewer genuinely qualified stocks exist. Try selecting "All Sectors" or switching tabs.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3">
              {filteredStocks.map((stock) => {
                const isBull = stock.sentimentPolarity > 0;
                const isBear = stock.sentimentPolarity < 0;
                const isDivergence = stock.priceConfirmation === 'NEWS_PRICE_DIVERGENCE';

                return (
                  <div
                    key={stock.symbol}
                    onClick={() => setSelectedStock(stock)}
                    className="p-4 sm:p-5 rounded-2xl bg-[var(--bg-surface)] dark:bg-[var(--bg-surface)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] hover:border-[var(--accent-blue)] transition-all cursor-pointer shadow-xs hover:shadow-md space-y-3"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 pb-2.5 border-b border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
                      <div className="flex items-center gap-3">
                        <span className="w-6 h-6 rounded-full bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-xs font-bold flex items-center justify-center text-[var(--text-primary)]">
                          #{stock.rank}
                        </span>
                        <div>
                          <div className="flex items-center gap-2">
                            <h3 className="text-sm font-bold text-[var(--text-primary)] hover:text-[var(--accent-blue)] transition-colors">
                              {stock.symbol}
                            </h3>
                            <span className="text-[10px] px-2 py-0.5 rounded-md bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)] font-medium">
                              {stock.sector}
                            </span>
                            <span className="text-[10px] px-1.5 py-0.2 rounded bg-purple-500/10 text-purple-400 font-semibold border border-purple-500/20">
                              {stock.exchange}
                            </span>
                          </div>
                          <p className="text-xs text-[var(--text-secondary)]">{stock.companyName}</p>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 flex-wrap">
                        {/* Research Bias Pill */}
                        <span
                          className={`text-xs font-semibold px-2.5 py-1 rounded-md border flex items-center gap-1 ${
                            stock.intradayBias === 'BULLISH'
                              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                              : stock.intradayBias === 'BEARISH'
                              ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                              : stock.intradayBias === 'DIVERGENCE'
                              ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                              : 'bg-blue-500/10 text-blue-400 border-blue-500/30'
                          }`}
                        >
                          {stock.intradayBias === 'BULLISH' && <ArrowUpRight className="w-3.5 h-3.5" />}
                          {stock.intradayBias === 'BEARISH' && <ArrowDownRight className="w-3.5 h-3.5" />}
                          {stock.intradayBias === 'DIVERGENCE' && <AlertTriangle className="w-3.5 h-3.5" />}
                          <span>{stock.intradayBias} BIAS</span>
                        </span>

                        {/* Price Confirmation Pill */}
                        <span
                          className={`text-[10px] font-semibold px-2 py-0.5 rounded uppercase border ${
                            stock.priceConfirmation === 'BULLISH_WATCHLIST_CANDIDATE'
                              ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                              : stock.priceConfirmation === 'BEARISH_WATCHLIST_CANDIDATE'
                              ? 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                              : stock.priceConfirmation === 'NEWS_PRICE_DIVERGENCE'
                              ? 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                              : 'bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border-[var(--border-subtle)]'
                          }`}
                        >
                          {stock.priceConfirmation.replace(/_/g, ' ')}
                        </span>
                      </div>
                    </div>

                    {/* Headline and Primary Catalyst */}
                    <div className="space-y-1.5">
                      <div className="flex items-start justify-between gap-3">
                        <p className="text-xs font-semibold text-[var(--text-primary)] dark:text-[var(--text-primary)] leading-snug">
                          {stock.primaryHeadline}
                        </p>
                        {stock.primaryUrl && (
                          <a
                            href={stock.primaryUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            title="Open original news source"
                            className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--accent-blue)] transition-colors shrink-0"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}
                      </div>
                      <div className="flex items-center gap-3 text-[11px] text-[var(--text-muted)] dark:text-[var(--text-secondary)]">
                        <span>Source: <strong className="text-[var(--text-primary)]">{stock.primarySource}</strong></span>
                        <span>•</span>
                        <span>Catalyst: <strong className="text-purple-400">{stock.catalyst}</strong></span>
                        <span>•</span>
                        <span>Articles: {stock.articlesCount}</span>
                      </div>
                    </div>

                    {/* Quantitative Metric Bar */}
                    <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5 pt-1 text-xs">
                      {/* Sentiment Polarity */}
                      <div className="p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
                        <span className="text-[10px] text-[var(--text-secondary)] block uppercase">Sentiment Polarity</span>
                        <span className={`font-bold ${stock.sentimentPolarity > 0 ? 'text-emerald-400' : stock.sentimentPolarity < 0 ? 'text-rose-400' : 'text-blue-400'}`}>
                          {stock.sentimentPolarity > 0 ? `+${stock.sentimentPolarity}` : stock.sentimentPolarity} / 100
                        </span>
                      </div>

                      {/* Event Impact Score */}
                      <div className="p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
                        <span className="text-[10px] text-[var(--text-secondary)] block uppercase">Event Impact Score</span>
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold text-[var(--text-primary)]">{stock.impactScore} / 100</span>
                          <div className="w-12 h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                            <div
                              className="h-full bg-purple-500 rounded-full"
                              style={{ width: `${stock.impactScore}%` }}
                            />
                          </div>
                        </div>
                      </div>

                      {/* Composite Rank Score */}
                      <div className="p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
                        <span className="text-[10px] text-[var(--text-secondary)] block uppercase">Composite Rank</span>
                        <span className="font-bold text-[var(--accent-blue)]">{stock.compositeRankScore} pts</span>
                      </div>

                      {/* Live Market LTP */}
                      <div className="p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
                        <span className="text-[10px] text-[var(--text-secondary)] block uppercase">Actual Stock Price</span>
                        {stock.currentPrice && stock.currentPrice > 0 ? (
                          <span className="font-semibold text-[var(--text-primary)]">
                            ₹{stock.currentPrice.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                          </span>
                        ) : (
                          <span className="text-amber-500 font-medium">PRICE_UNVERIFIED</span>
                        )}
                      </div>

                      {/* Day Change % */}
                      <div className="p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
                        <span className="text-[10px] text-[var(--text-secondary)] block uppercase">Day Change %</span>
                        {stock.changePercent !== null && stock.currentPrice ? (
                          <span className={`font-bold ${stock.changePercent >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {stock.changePercent >= 0 ? '+' : ''}{stock.changePercent.toFixed(2)}%
                          </span>
                        ) : (
                          <span className="text-[var(--text-muted)]">Offline / EOD</span>
                        )}
                      </div>
                    </div>

                    {/* Explanation Summary */}
                    <div className="p-2.5 rounded-lg bg-[var(--bg-surface-elevated)]/60 border border-[var(--border-subtle)] text-[11px] text-[var(--text-secondary)] flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <Info className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                        <span className="line-clamp-1">{stock.explanation}</span>
                      </div>
                      <span className="text-[10px] text-[var(--accent-blue)] font-semibold shrink-0">
                        View Forensic Timeline →
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* VIEW B: HIGH-IMPACT NEWS STREAM */}
      {activeTab === 'stream' && (
        <div className="space-y-3">
          {streamArticles.length === 0 ? (
            <p className="text-xs text-[var(--text-muted)] text-center py-8">No live news stream available.</p>
          ) : (
            <div className="grid grid-cols-1 gap-2.5">
              {streamArticles.map((art) => (
                <div
                  key={art.id}
                  className="p-4 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] hover:border-[var(--border-subtle)] space-y-2 text-xs"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded font-bold bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/20">
                        {art.symbol}
                      </span>
                      <span className="text-[var(--text-secondary)]">{art.companyName}</span>
                    </div>
                    <div className="flex items-center gap-2 text-[10px]">
                      <span className="text-[var(--text-muted)]">{art.source}</span>
                      <span className="px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400 font-semibold border border-purple-500/20">
                        Impact: {art.impact}/100
                      </span>
                    </div>
                  </div>

                  <p className="font-semibold text-[var(--text-primary)]">{art.headline}</p>

                  <div className="flex items-center justify-between pt-1 border-t border-[var(--border-subtle)] text-[11px] text-[var(--text-muted)]">
                    <span>Category: <strong className="text-[var(--text-primary)]">{art.category}</strong></span>
                    {art.url && (
                      <a
                        href={art.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[var(--accent-blue)] hover:underline flex items-center gap-1 font-medium"
                      >
                        <span>Original Article</span>
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* MODAL: DETAILED STOCK FORENSIC RESEARCH VIEW */}
      {selectedStock && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] shadow-2xl p-6 space-y-5">
            {/* Modal Header */}
            <div className="flex items-start justify-between pb-3 border-b border-[var(--border-subtle)]">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-bold text-[var(--text-primary)]">
                    {selectedStock.symbol} — {selectedStock.companyName}
                  </h3>
                  <span className="px-2 py-0.5 rounded bg-[var(--bg-surface-elevated)] text-[11px] text-[var(--text-secondary)] border border-[var(--border-subtle)]">
                    {selectedStock.sector}
                  </span>
                </div>
                <p className="text-xs text-[var(--text-muted)]">
                  Rank #{selectedStock.rank} • Composite Score: {selectedStock.compositeRankScore} pts • Status: {selectedStock.researchStatus}
                </p>
              </div>
              <button
                onClick={() => setSelectedStock(null)}
                className="p-1.5 rounded-lg bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Price & Sentiment Strip */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              <div className="p-3 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
                <span className="text-[10px] text-[var(--text-secondary)] block uppercase">Price & Day Change</span>
                <span className="font-bold text-sm text-[var(--text-primary)]">
                  {selectedStock.currentPrice ? `₹${selectedStock.currentPrice.toFixed(2)}` : 'UNVERIFIED'}
                </span>
                {selectedStock.changePercent !== null && (
                  <span className={`block text-xs font-semibold ${selectedStock.changePercent >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {selectedStock.changePercent >= 0 ? '+' : ''}{selectedStock.changePercent.toFixed(2)}%
                  </span>
                )}
              </div>

              <div className="p-3 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
                <span className="text-[10px] text-[var(--text-secondary)] block uppercase">Sentiment Polarity</span>
                <span className={`font-bold text-sm ${selectedStock.sentimentPolarity > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {selectedStock.sentimentPolarity > 0 ? `+${selectedStock.sentimentPolarity}` : selectedStock.sentimentPolarity} / 100
                </span>
                <span className="block text-[10px] text-[var(--text-muted)]">Scale: -100 to +100</span>
              </div>

              <div className="p-3 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
                <span className="text-[10px] text-[var(--text-secondary)] block uppercase">News Impact Score</span>
                <span className="font-bold text-sm text-purple-400">
                  {selectedStock.impactScore} / 100
                </span>
                <span className="block text-[10px] text-[var(--text-muted)]">Event Materiality</span>
              </div>

              <div className="p-3 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-0.5">
                <span className="text-[10px] text-[var(--text-secondary)] block uppercase">Source Provenance</span>
                <span className="font-bold text-sm text-[var(--accent-blue)]">
                  {selectedStock.verificationStatus.replace(/_/g, ' ')}
                </span>
                <span className="block text-[10px] text-[var(--text-muted)]">Confidence: {(selectedStock.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>

            {/* Research Thesis & Institutional Explanation */}
            <div className="p-4 rounded-xl bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] space-y-2 text-xs">
              <div className="flex items-center gap-1.5 font-semibold text-[var(--text-primary)]">
                <Sparkles className="w-4 h-4 text-purple-400" />
                <span>Event Impact Thesis & Catalyst Rationale</span>
              </div>
              <p className="text-[var(--text-secondary)] leading-relaxed">
                {selectedStock.explanation}
              </p>
              <div className="pt-2 border-t border-[var(--border-subtle)] grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
                <div>
                  <span className="text-emerald-400 font-semibold block">Why this stock qualified:</span>
                  <span className="text-[var(--text-secondary)]">High event materiality ({selectedStock.catalyst}) with verified news provenance across independent financial publications.</span>
                </div>
                <div>
                  <span className="text-amber-400 font-semibold block">Risk Warnings & Limitations:</span>
                  <span className="text-[var(--text-secondary)]">
                    {selectedStock.priceConfirmation === 'NEWS_PRICE_DIVERGENCE'
                      ? 'Divergence Alert: Stock price is moving opposite to news sentiment direction. Exercise caution.'
                      : selectedStock.priceConfirmation === 'PRICE_UNVERIFIED'
                      ? 'Market Data Offline: Stock prices must be confirmed with live exchange quotes before formulating a trade.'
                      : 'Intraday momentum depends on overall index trend and volume sustainability.'}
                  </span>
                </div>
              </div>
            </div>

            {/* Verified Article Timeline */}
            <div className="space-y-2 text-xs">
              <h4 className="font-semibold text-[var(--text-primary)] flex items-center gap-1.5">
                <Newspaper className="w-4 h-4 text-[var(--accent-blue)]" />
                <span>Associated News Coverage ({selectedStock.articles.length} Articles)</span>
              </h4>
              <div className="space-y-2 max-h-52 overflow-y-auto pr-1">
                {selectedStock.articles.map((art, idx) => (
                  <div
                    key={idx}
                    className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] flex items-start justify-between gap-3"
                  >
                    <div className="space-y-1">
                      <p className="font-medium text-[var(--text-primary)] leading-tight">{art.headline}</p>
                      <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)]">
                        <span>{art.source}</span>
                        <span>•</span>
                        <span>Polarity: {art.polarity > 0 ? `+${art.polarity}` : art.polarity}</span>
                        <span>•</span>
                        <span>Impact: {art.impact}/100</span>
                        {art.isSyndicatedCopy && <span className="text-amber-500">(Syndicated Copy)</span>}
                      </div>
                    </div>
                    {art.url && (
                      <a
                        href={art.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-1 text-[var(--accent-blue)] hover:underline shrink-0"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                      </a>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Read-Only Safety Mandate Strip */}
            <div className="p-3 rounded-xl bg-amber-500/[0.05] border border-amber-500/20 text-[11px] text-amber-500 flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 shrink-0" />
              <span>
                <strong>Read-Only Governance Mandate:</strong> This is a quantitative news research scanner. It does not place live equity orders or guarantee profitability.
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
