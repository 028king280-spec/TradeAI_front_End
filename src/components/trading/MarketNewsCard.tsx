'use client';

import React, { useState, useEffect } from 'react';
import {
  Newspaper,
  ExternalLink,
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
  Clock,
  Search,
  Filter,
  Radio,
  CheckCircle2,
} from 'lucide-react';
import { newsService, NewsItem } from '@/services/newsService';

interface MarketNewsCardProps {
  initialSymbol?: string;
}

export const MarketNewsCard: React.FC<MarketNewsCardProps> = ({ initialSymbol }) => {
  const [news, setNews] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [filter, setFilter] = useState<'ALL' | 'BULLISH' | 'BEARISH' | 'NEUTRAL'>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [lastUpdated, setLastUpdated] = useState<string>('');
  const [refreshCount, setRefreshCount] = useState<number>(0);

  useEffect(() => {
    let isCancelled = false;
    async function fetchNews() {
      setLoading(true);
      try {
        let items: NewsItem[] = [];
        if (searchQuery.trim().length >= 3) {
          items = await newsService.searchNews(searchQuery.trim(), 15);
        } else if (initialSymbol && initialSymbol !== 'ALL') {
          items = await newsService.getStockNews(initialSymbol, 15);
          if (items.length === 0) {
            items = await newsService.getMarketNews(15);
          }
        } else {
          items = await newsService.getMarketNews(15);
        }

        if (!isCancelled) {
          setNews(items);
          setLastUpdated(new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
        }
      } catch (err) {
        console.warn('Failed to load market news:', err);
      } finally {
        if (!isCancelled) setLoading(false);
      }
    }

    fetchNews();
    const interval = setInterval(fetchNews, 60000); // Auto-refresh every 60 seconds
    return () => {
      isCancelled = true;
      clearInterval(interval);
    };
  }, [initialSymbol, searchQuery, refreshCount]);

  const filteredNews = news.filter((item) => {
    if (filter === 'ALL') return true;
    return item.sentiment.toUpperCase() === filter;
  });

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 sm:p-5 shadow-sm space-y-4 font-mono">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
            <Newspaper className="w-4 h-4 text-amber-500" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-[var(--text-primary)]">
                Live Indian Market News Feed
              </h3>
              <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                <Radio className="w-3 h-3 animate-pulse" />
                <span>LIVE FEED</span>
              </span>
            </div>
            <span className="text-[10px] text-[var(--text-muted)]">
              Verified financial reporting from Economic Times, Moneycontrol, Livemint & NSE Macro
            </span>
          </div>
        </div>

        {/* Action / Refresh */}
        <div className="flex items-center gap-2 text-xs">
          {lastUpdated && (
            <span className="text-[11px] text-[var(--text-muted)] hidden md:inline">
              Sync: {lastUpdated} IST
            </span>
          )}
          <button
            onClick={() => setRefreshCount((c) => c + 1)}
            disabled={loading}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] hover:bg-slate-100 dark:hover:bg-slate-800 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-50"
            title="Refresh news"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Filter Tabs and Quick Search */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
        <div className="flex items-center gap-1.5 flex-wrap">
          {(['ALL', 'BULLISH', 'BEARISH', 'NEUTRAL'] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setFilter(mode)}
              className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${
                filter === mode
                  ? mode === 'BULLISH'
                    ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/40'
                    : mode === 'BEARISH'
                    ? 'bg-rose-500/20 text-rose-600 dark:text-rose-400 border border-rose-500/40'
                    : mode === 'NEUTRAL'
                    ? 'bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/40'
                    : 'bg-blue-500/20 text-blue-600 dark:text-blue-400 border border-blue-500/40'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-elevated)]'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>

        {/* Search Input */}
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            type="text"
            placeholder="Search stock news (e.g. RELIANCE, TCS)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8 pr-3 py-1 text-xs rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-1 focus:ring-blue-500 w-full sm:w-64"
          />
        </div>
      </div>

      {/* News List */}
      <div className="space-y-2.5 max-h-[460px] overflow-y-auto pr-1">
        {loading && news.length === 0 ? (
          <div className="p-8 text-center text-xs text-[var(--text-muted)] space-y-2">
            <RefreshCw className="w-5 h-5 mx-auto animate-spin text-blue-500" />
            <p>Fetching real-time Indian stock market headlines...</p>
          </div>
        ) : filteredNews.length === 0 ? (
          <div className="p-8 text-center text-xs text-[var(--text-muted)]">
            No market news matching the filter criteria.
          </div>
        ) : (
          filteredNews.map((item) => {
            const isBull = item.sentiment.toUpperCase() === 'BULLISH';
            const isBear = item.sentiment.toUpperCase() === 'BEARISH';

            return (
              <div
                key={item.id}
                className="p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] hover:border-slate-400 dark:hover:border-slate-600 transition-all space-y-2 group"
              >
                {/* Meta row: Source, Time, Sentiment, Impact */}
                <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)] flex-wrap gap-1">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-[var(--text-primary)] px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-800">
                      {item.source}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      <span>{item.publishedAt ? item.publishedAt.slice(0, 16) : 'Just now'}</span>
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    {/* Impact */}
                    <span
                      className={`px-1.5 py-0.2 rounded font-semibold text-[9px] ${
                        item.impact === 'HIGH'
                          ? 'bg-purple-500/15 text-purple-600 dark:text-purple-400'
                          : 'bg-slate-500/15 text-slate-600 dark:text-slate-400'
                      }`}
                    >
                      {item.impact} IMPACT
                    </span>

                    {/* Sentiment */}
                    <span
                      className={`flex items-center gap-1 px-1.5 py-0.2 rounded font-bold text-[9px] ${
                        isBull
                          ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                          : isBear
                          ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
                          : 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
                      }`}
                    >
                      {isBull ? (
                        <TrendingUp className="w-2.5 h-2.5" />
                      ) : isBear ? (
                        <TrendingDown className="w-2.5 h-2.5" />
                      ) : (
                        <Minus className="w-2.5 h-2.5" />
                      )}
                      <span>{item.sentiment}</span>
                    </span>
                  </div>
                </div>

                {/* Headline & External Link */}
                <div className="flex items-start justify-between gap-3">
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs font-semibold text-[var(--text-primary)] hover:text-blue-500 dark:hover:text-blue-400 transition-colors leading-snug"
                  >
                    {item.headline}
                  </a>
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors p-1 rounded group-hover:text-blue-500"
                    title="Read full article on original publisher"
                  >
                    <ExternalLink className="w-3.5 h-3.5 shrink-0" />
                  </a>
                </div>

                {/* Related Symbols */}
                {item.relatedSymbols && item.relatedSymbols.length > 0 && (
                  <div className="flex items-center gap-1.5 pt-1 text-[9px] text-[var(--text-muted)]">
                    <span>Related:</span>
                    {item.relatedSymbols.map((sym) => (
                      <span
                        key={sym}
                        className="px-1.5 py-0.2 rounded bg-blue-500/10 text-blue-600 dark:text-blue-400 font-semibold"
                      >
                        {sym}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
