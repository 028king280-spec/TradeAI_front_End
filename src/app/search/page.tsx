'use client';

import React, { useState, useEffect, Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import {
  Search,
  Filter,
  TrendingUp,
  Clock,
  Sparkles,
  ArrowRight,
  ShieldCheck,
  Building2,
} from 'lucide-react';
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
      {/* Page Header */}
      <div className="text-center max-w-2xl mx-auto space-y-2 pt-4">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/30 text-blue-400 text-xs font-mono">
          <Sparkles className="w-3.5 h-3.5" />
          <span>INSTITUTIONAL RESEARCH DIRECTORY</span>
        </div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-100 font-mono">
          Analyze Any Indian Stock
        </h1>
        <p className="text-xs sm:text-sm text-slate-400">
          Search any supported NSE/BSE stock to view a detailed market analysis, probability models, and scenario zones.
        </p>
      </div>

      {/* Large Premium Search Box */}
      <div className="max-w-3xl mx-auto space-y-3">
        <div className="relative group">
          <div className="absolute inset-0 bg-gradient-to-r from-blue-500/20 via-emerald-500/20 to-indigo-500/20 rounded-xl blur-md group-hover:blur-lg transition-all opacity-50" />
          <div className="relative flex items-center bg-white dark:bg-[#111622] border border-slate-200 dark:border-[#232F46] focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-500/20 rounded-xl p-2 shadow-sm dark:shadow-2xl transition-all">
            <Search className="w-5 h-5 text-slate-400 dark:text-slate-500 ml-2 shrink-0" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search stock by symbol or company name (e.g. RELIANCE, TCS, SBIN)..."
              className="w-full bg-transparent px-3 py-2 text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none font-mono"
            />
            {query && (
              <button
                onClick={() => setQuery('')}
                className="text-xs font-mono text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 px-2 py-1 rounded bg-slate-100 dark:bg-slate-800"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Popular Quick Suggestions */}
        <div className="flex items-center flex-wrap gap-1.5 text-xs font-mono text-slate-500 dark:text-slate-400">
          <span className="text-slate-500 dark:text-slate-400">Quick Select:</span>
          {popularExamples.map((sym) => (
            <button
              key={sym}
              onClick={() => setQuery(sym)}
              className="px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-[#131a27] dark:hover:bg-[#1b263b] text-slate-700 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 border border-slate-200 dark:border-[#1e283d] transition-colors"
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
          <span className="text-xs font-mono text-slate-500 dark:text-slate-400 flex items-center gap-1">
            <Filter className="w-3.5 h-3.5 text-blue-500 dark:text-blue-400" />
            <span>Exchange:</span>
          </span>
          <div className="flex items-center gap-1 font-mono text-xs">
            {(['ALL', 'NSE', 'BSE'] as const).map((ex) => (
              <button
                key={ex}
                onClick={() => setExchangeFilter(ex)}
                className={`px-2.5 py-1 rounded-md transition-colors ${
                  exchangeFilter === ex
                    ? 'bg-blue-600 text-white font-semibold shadow-sm'
                    : 'bg-slate-100 dark:bg-[#141b29] text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 border border-slate-200 dark:border-[#1e283d]'
                }`}
              >
                {ex}
              </button>
            ))}
          </div>
        </div>

        {/* Market Cap Filter */}
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-slate-500 dark:text-slate-400">Market Cap:</span>
          <div className="flex items-center gap-1 font-mono text-xs">
            {(['ALL', 'Large Cap', 'Mid Cap', 'Small Cap'] as const).map((cap) => (
              <button
                key={cap}
                onClick={() => setCapFilter(cap)}
                className={`px-2.5 py-1 rounded-md transition-colors ${
                  capFilter === cap
                    ? 'bg-emerald-600 text-white font-semibold shadow-sm'
                    : 'bg-slate-100 dark:bg-[#141b29] text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 border border-slate-200 dark:border-[#1e283d]'
                }`}
              >
                {cap}
              </button>
            ))}
          </div>
        </div>

        {/* Result Count */}
        <div className="text-xs font-mono text-slate-500 dark:text-slate-400 self-end md:self-center">
          Showing <strong className="text-slate-800 dark:text-slate-200">{results.length}</strong> stocks
        </div>
      </div>

      {/* Recent Searches */}
      {recentSearches.length > 0 && !query && (
        <div className="flex items-center gap-2 text-xs font-mono text-slate-500 dark:text-slate-400">
          <Clock className="w-3.5 h-3.5 text-slate-400" />
          <span>Recent Searches:</span>
          {recentSearches.map((sym) => (
            <button
              key={sym}
              onClick={() => handleSelectRecent(sym)}
              className="px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-[#141b29] dark:hover:bg-[#1a2335] text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-[#1e283d] transition-colors"
            >
              {sym}
            </button>
          ))}
        </div>
      )}

      {/* Results Grid */}
      <div className="space-y-3">
        <h2 className="text-xs font-mono font-bold tracking-wider uppercase text-slate-500 dark:text-slate-400 flex items-center gap-2">
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
                  className="card-terminal p-4 flex flex-col justify-between hover:border-blue-500/50 hover:shadow-md transition-all duration-200 group"
                >
                  <div>
                    {/* Header: Symbol & Badges */}
                    <div className="flex items-center justify-between pb-2 border-b border-slate-100 dark:border-[#1e283d]">
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded bg-blue-50 dark:bg-[#161f30] border border-blue-200 dark:border-[#232F46] flex items-center justify-center font-mono font-bold text-xs text-blue-600 dark:text-blue-400">
                          {stock.symbol.slice(0, 2)}
                        </div>
                        <div>
                          <span className="text-sm font-bold font-mono text-slate-900 dark:text-slate-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                            {stock.symbol}
                          </span>
                          <span className="text-[10px] font-mono text-slate-500 dark:text-slate-400 block">
                            {stock.exchange} • {stock.category}
                          </span>
                        </div>
                      </div>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-50 dark:bg-[#161f30] text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-[#232F46]">
                        {stock.marketStatus}
                      </span>
                    </div>

                    {/* Company Name & Sector */}
                    <div className="py-2.5">
                      <p className="text-xs text-slate-700 dark:text-slate-300 font-medium truncate">
                        {stock.companyName}
                      </p>
                      <span className="text-[11px] text-slate-500 dark:text-slate-400 font-mono">
                        Sector: {stock.sector}
                      </span>
                    </div>

                    {/* Price and Change */}
                    <div className="flex items-baseline justify-between py-2 bg-slate-50 dark:bg-[#0b0e14]/50 px-2.5 rounded-lg border border-slate-200 dark:border-[#1e283d]">
                      <div>
                        <span className="text-[10px] text-slate-500 dark:text-slate-400 font-mono uppercase block">
                          Current Price
                        </span>
                        <span className="text-base font-mono font-bold text-slate-900 dark:text-slate-100">
                          {formatINR(stock.currentPrice)}
                        </span>
                      </div>
                      <div
                        className={`text-xs font-mono font-semibold ${
                          isPos ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
                        }`}
                      >
                        {formatPercent(stock.changePercent)}
                      </div>
                    </div>
                  </div>

                  {/* Footer: Setup Score & Action */}
                  <div className="mt-4 pt-3 border-t border-slate-100 dark:border-[#1e283d] flex items-center justify-between">
                    <ConfidenceScore score={stock.analysisScore} label="AI Score" size="sm" />
                    <Link
                      href={`/stocks/${stock.symbol}`}
                      className="inline-flex items-center gap-1 text-xs font-mono font-semibold text-blue-600 dark:text-blue-400 group-hover:text-blue-700 dark:group-hover:text-blue-300 px-3 py-1.5 rounded-lg bg-blue-50 dark:bg-blue-500/10 hover:bg-blue-100 dark:hover:bg-blue-500/20 border border-blue-200 dark:border-blue-500/20 transition-all"
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
            <div className="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center mx-auto text-slate-400">
              <Search className="w-6 h-6" />
            </div>
            <h3 className="text-sm font-bold font-mono text-slate-200">
              No Indian stocks found matching &quot;{query}&quot;
            </h3>
            <p className="text-xs text-slate-400 max-w-sm mx-auto">
              Please check the symbol spelling or clear exchange/market-cap filters to view the full NSE/BSE universe.
            </p>
            <button
              onClick={() => {
                setQuery('');
                setExchangeFilter('ALL');
                setCapFilter('ALL');
              }}
              className="text-xs font-mono px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-500 transition-colors"
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
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <StockSearchContent />
    </Suspense>
  );
}

