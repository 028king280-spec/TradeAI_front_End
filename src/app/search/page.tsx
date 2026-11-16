'use client';
import { PageHeading } from '@/components/shared/PageHeading';

import React, { useState, useEffect, Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Search, Filter, Clock, ArrowRight, Building2 } from 'lucide-react';
import { marketDataService } from '@/services/marketDataService';
import { ALL_SEARCH_STOCKS } from '@/lib/mock-market-data';
import { formatINR, formatPercent } from '@/lib/utils';
import { ConfidenceScore } from '@/components/shared/ConfidenceScore';

function StockSearchContent() {
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get('q') || '';

  const [query, setQuery] = useState(initialQuery);
  const [exchangeFilter, setExchangeFilter] = useState<'ALL' | 'NSE' | 'BSE'>('ALL');
  const [capFilter, setCapFilter] = useState<'ALL' | 'Large Cap' | 'Mid Cap' | 'Small Cap'>('ALL');
  const [results, setResults] = useState(ALL_SEARCH_STOCKS);
  const [recentSearches, setRecentSearches] = useState<string[]>([
    'RELIANCE',
    'TCS',
    'INFY',
    'HDFCBANK',
  ]);

  useEffect(() => {
    async function filterData() {
      const data = await marketDataService.searchStocks(query, {
        exchange: exchangeFilter,
        cap: capFilter,
      });
      setResults(data);
    }
    filterData();
  }, [query, exchangeFilter, capFilter]);

  const handleSelectRecent = (sym: string) => {
    setQuery(sym);
  };

  const popularExamples = ['RELIANCE', 'TCS', 'SBIN', 'HDFCBANK', 'ICICIBANK', 'INFY', 'LT', 'MARUTI', 'ITC'];

  return (
    <div className="space-y-8 max-w-6xl mx-auto pb-12">
      <PageHeading title="Stock explorer" description="Discover Indian equities in a focused, searchable research workspace."/>

      {/* Large Premium Search Box */}
      <div className="max-w-3xl mx-auto space-y-3">
        <div className="relative group">
          <div className="absolute inset-0 bg-gradient-to-r from-[var(--accent-blue)]/20 via-emerald-500/20 to-[var(--accent-blue)]/20 rounded-xl blur-md group-hover:blur-lg transition-all opacity-50" />
          <div className="relative flex items-center bg-[var(--bg-surface)] dark:bg-[var(--bg-surface)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] focus-within:border-[var(--accent-blue)] focus-within:ring-2 focus-within:ring-[var(--accent-blue)]/20 rounded-xl p-2 shadow-sm dark:shadow-2xl transition-all">
            <Search className="w-5 h-5 text-[var(--text-secondary)] dark:text-[var(--text-muted)] ml-2 shrink-0" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search stock by symbol or company name (e.g. RELIANCE, TCS, SBIN)..."
              className="w-full bg-transparent px-3 py-2 text-sm text-[var(--text-primary)] dark:text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none tabular-nums"
            />
            {query && (
              <button
                onClick={() => setQuery('')}
                className="text-xs tabular-nums text-[var(--text-secondary)] dark:text-[var(--text-secondary)] hover:text-[var(--text-primary)] dark:hover:text-[var(--text-primary)] px-2 py-1 rounded bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)]"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Popular Quick Suggestions */}
        <div className="flex items-center flex-wrap gap-1.5 text-xs tabular-nums text-[var(--text-muted)] dark:text-[var(--text-secondary)]">
          <span className="text-[var(--text-muted)] dark:text-[var(--text-secondary)]">Quick Select:</span>
          {popularExamples.map((sym) => (
            <button
              key={sym}
              onClick={() => setQuery(sym)}
              className="px-2 py-0.5 rounded bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface)] dark:hover:bg-[var(--bg-surface)] text-[var(--text-secondary)] dark:text-[var(--text-secondary)] hover:text-[var(--accent-blue)] dark:hover:text-[var(--accent-blue)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] transition-colors"
            >
              {sym}
            </button>
          ))}
        </div>
      </div>

      {/* Filter Chips & Search Controls */}
      <div className="card-terminal p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        {/* Exchange Filter */}
        <div className="flex items-center gap-2">
          <span className="text-xs tabular-nums text-[var(--text-muted)] dark:text-[var(--text-secondary)] flex items-center gap-1">
            <Filter className="w-3.5 h-3.5 text-[var(--accent-blue)] dark:text-[var(--accent-blue)]" />
            <span>Exchange:</span>
          </span>
          <div className="flex items-center gap-1 tabular-nums text-xs">
            {(['ALL', 'NSE', 'BSE'] as const).map((ex) => (
              <button
                key={ex}
                onClick={() => setExchangeFilter(ex)}
                className={`px-2.5 py-1 rounded-md transition-colors ${
                  exchangeFilter === ex
                    ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] font-semibold shadow-sm'
                    : 'bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface)] text-[var(--text-secondary)] dark:text-[var(--text-secondary)] hover:text-[var(--text-primary)] dark:hover:text-[var(--text-primary)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)]'
                }`}
              >
                {ex}
              </button>
            ))}
          </div>
        </div>

        {/* Market Cap Filter */}
        <div className="flex items-center gap-2">
          <span className="text-xs tabular-nums text-[var(--text-muted)] dark:text-[var(--text-secondary)]">Market Cap:</span>
          <div className="flex items-center gap-1 tabular-nums text-xs">
            {(['ALL', 'Large Cap', 'Mid Cap', 'Small Cap'] as const).map((cap) => (
              <button
                key={cap}
                onClick={() => setCapFilter(cap)}
                className={`px-2.5 py-1 rounded-md transition-colors ${
                  capFilter === cap
                    ? 'bg-emerald-600 text-[var(--text-primary)] font-semibold shadow-sm'
                    : 'bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface)] text-[var(--text-secondary)] dark:text-[var(--text-secondary)] hover:text-[var(--text-primary)] dark:hover:text-[var(--text-primary)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)]'
                }`}
              >
                {cap}
              </button>
            ))}
          </div>
        </div>

        {/* Result Count */}
        <div className="text-xs tabular-nums text-[var(--text-muted)] dark:text-[var(--text-secondary)] self-end md:self-center">
          Showing <strong className="text-[var(--text-primary)] dark:text-[var(--text-primary)]">{results.length}</strong> stocks
        </div>
      </div>

      {/* Recent Searches */}
      {recentSearches.length > 0 && !query && (
        <div className="flex items-center gap-2 text-xs tabular-nums text-[var(--text-muted)] dark:text-[var(--text-secondary)]">
          <Clock className="w-3.5 h-3.5 text-[var(--text-secondary)]" />
          <span>Recent Searches:</span>
          {recentSearches.map((sym) => (
            <button
              key={sym}
              onClick={() => handleSelectRecent(sym)}
              className="px-2 py-0.5 rounded bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface)] dark:hover:bg-[var(--bg-surface)] text-[var(--text-secondary)] dark:text-[var(--text-secondary)] border border-[var(--border-subtle)] dark:border-[var(--border-subtle)] transition-colors"
            >
              {sym}
            </button>
          ))}
        </div>
      )}

      {/* Results Grid */}
      <div className="space-y-3">
        <h2 className="text-xs tabular-nums font-semibold tracking-wider uppercase text-[var(--text-muted)] dark:text-[var(--text-secondary)] flex items-center gap-2">
          <Building2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
          <span>{query ? `Search Results for "${query}"` : 'Popular Indian Stocks'}</span>
        </h2>

        {results.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {results.map((stock) => {
              const isPos = stock.changePercent >= 0;

              return (
                <div
                  key={stock.symbol}
                  className="card-terminal p-4 flex flex-col justify-between hover:border-[var(--accent-blue)]/50 hover:shadow-md transition-all duration-200 group"
                >
                  <div>
                    {/* Header: Symbol & Badges */}
                    <div className="flex items-center justify-between pb-2 border-b border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded bg-[var(--accent-blue-bg)] dark:bg-[var(--bg-surface)] border border-[var(--accent-blue)] dark:border-[var(--border-subtle)] flex items-center justify-center tabular-nums font-semibold text-xs text-[var(--accent-blue)] dark:text-[var(--accent-blue)]">
                          {stock.symbol.slice(0, 2)}
                        </div>
                        <div>
                          <span className="text-sm font-semibold tabular-nums text-[var(--text-primary)] dark:text-[var(--text-primary)] group-hover:text-[var(--accent-blue)] dark:group-hover:text-[var(--accent-blue)] transition-colors">
                            {stock.symbol}
                          </span>
                          <span className="text-[10px] tabular-nums text-[var(--text-muted)] dark:text-[var(--text-secondary)] block">
                            {stock.exchange} • {stock.category}
                          </span>
                        </div>
                      </div>
                      <span className="text-[10px] tabular-nums px-2 py-0.5 rounded bg-emerald-50 dark:bg-[var(--bg-surface)] text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-[var(--border-subtle)]">
                        {stock.marketStatus}
                      </span>
                    </div>

                    {/* Company Name & Sector */}
                    <div className="py-2.5">
                      <p className="text-xs text-[var(--text-secondary)] dark:text-[var(--text-secondary)] font-medium truncate">
                        {stock.companyName}
                      </p>
                      <span className="text-[11px] text-[var(--text-muted)] dark:text-[var(--text-secondary)] tabular-nums">
                        Sector: {stock.sector}
                      </span>
                    </div>

                    {/* Price and Change */}
                    <div className="flex items-baseline justify-between py-2 bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface)] px-2.5 rounded-lg border border-[var(--border-subtle)] dark:border-[var(--border-subtle)]">
                      <div>
                        <span className="text-[10px] text-[var(--text-muted)] dark:text-[var(--text-secondary)] tabular-nums uppercase block">
                          Current Price
                        </span>
                        <span className="text-base tabular-nums font-semibold text-[var(--text-primary)] dark:text-[var(--text-primary)]">
                          {formatINR(stock.currentPrice)}
                        </span>
                      </div>
                      <div
                        className={`text-xs tabular-nums font-semibold ${
                          isPos ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
                        }`}
                      >
                        {formatPercent(stock.changePercent)}
                      </div>
                    </div>
                  </div>

                  {/* Footer: Setup Score & Action */}
                  <div className="mt-4 pt-3 border-t border-[var(--border-subtle)] dark:border-[var(--border-subtle)] flex items-center justify-between">
                    <ConfidenceScore score={stock.analysisScore} label="AI Score" size="sm" />
                    <Link
                      href={`/stocks/${stock.symbol}`}
                      className="inline-flex items-center gap-1 text-xs tabular-nums font-semibold text-[var(--accent-blue)] dark:text-[var(--accent-blue)] group-hover:text-[var(--accent-blue)] dark:group-hover:text-[var(--accent-blue)] px-3 py-1.5 rounded-lg bg-[var(--accent-blue-bg)] dark:bg-[var(--accent-blue)]/10 hover:bg-[var(--accent-blue-bg)] dark:hover:bg-[var(--accent-blue)]/20 border border-[var(--accent-blue)] dark:border-[var(--accent-blue)]/20 transition-all"
                    >
                      <span>Analyze Stock</span>
                      <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="card-terminal p-12 text-center space-y-3">
            <div className="w-12 h-12 rounded-full bg-[var(--bg-surface-elevated)] flex items-center justify-center mx-auto text-[var(--text-secondary)]">
              <Search className="w-6 h-6" />
            </div>
            <h3 className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">
              No Indian stocks found matching &quot;{query}&quot;
            </h3>
            <p className="text-xs text-[var(--text-secondary)] max-w-sm mx-auto">
              Please check the symbol spelling or clear exchange/market-cap filters to view the full NSE/BSE universe.
            </p>
            <button
              onClick={() => {
                setQuery('');
                setExchangeFilter('ALL');
                setCapFilter('ALL');
              }}
              className="text-xs tabular-nums px-3 py-1.5 rounded bg-[var(--accent-blue)] text-[var(--accent-on)] hover:bg-[var(--accent-blue)] transition-colors"
            >
              Reset Search Filters
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function StockSearchPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[50vh]">
          <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <StockSearchContent />
    </Suspense>
  );
}

