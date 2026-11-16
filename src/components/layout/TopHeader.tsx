'use client';

import React, { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  Search,
  Bell,
  Clock,
  Menu,
  Sparkles,
  ArrowRight,
  Sun,
  Moon,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { MarketStatusBadge } from '@/components/shared/MarketStatusBadge';
import { ALL_SEARCH_STOCKS } from '@/lib/mock-market-data';
import { formatINR, formatPercent } from '@/lib/utils';
import { apiClient } from '@/lib/api';
import { usePaperTrading } from '@/context/PaperTradingContext';
import { useTheme } from '@/context/ThemeContext';

interface TopHeaderProps {
  onToggleMobile: () => void;
}

const TICKER_ITEMS = [
  { symbol: 'NIFTY 50', name: 'NIFTY 50', change: 0.55, price: 24852.40 },
  { symbol: 'SENSEX', name: 'BSE SENSEX', change: 0.52, price: 81850.50 },
  { symbol: 'BANKNIFTY', name: 'Bank Nifty', change: 0.61, price: 51420.80 },
  { symbol: 'INDIA VIX', name: 'India VIX', change: -3.85, price: 13.42 },
  { symbol: 'RELIANCE', name: 'Reliance Ind', change: 1.24, price: 1456.80 },
  { symbol: 'TCS', name: 'Tata Consultancy', change: 0.82, price: 3480.00 },
  { symbol: 'HDFCBANK', name: 'HDFC Bank', change: 0.35, price: 1720.00 },
  { symbol: 'INFY', name: 'Infosys Ltd', change: -0.45, price: 1480.00 },
  { symbol: 'ICICIBANK', name: 'ICICI Bank', change: 0.95, price: 1245.50 },
];

export const TopHeader: React.FC<TopHeaderProps> = ({ onToggleMobile }) => {
  const router = useRouter();
  const { virtualBalance } = usePaperTrading();
  const { theme, toggleTheme } = useTheme();
  const [query, setQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [providerMode, setProviderMode] = useState<'MOCK' | 'LIVE' | 'MARKET_CLOSED' | 'DATA_OFFLINE'>('MOCK');
  const [marketStatus, setMarketStatus] = useState<'OPEN' | 'CLOSED'>('CLOSED');
  const searchRef = useRef<HTMLDivElement>(null);
  const tickerRef = useRef<HTMLDivElement>(null);

  // Filtered autocomplete suggestions
  const suggestions = query.trim()
    ? ALL_SEARCH_STOCKS.filter(
        (s) =>
          s.symbol.toLowerCase().includes(query.toLowerCase()) ||
          s.companyName.toLowerCase().includes(query.toLowerCase())
      ).slice(0, 6)
    : [];

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        const input = document.getElementById('global-search-input');
        input?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    async function checkHealth() {
      try {
        const res = await fetch('/api/market/live');
        if (res.ok) {
          const json = await res.json();
          const mktStatus = json?.data?.marketStatus || 'CLOSED';
          setMarketStatus(mktStatus === 'OPEN' ? 'OPEN' : 'CLOSED');
          if (mktStatus === 'CLOSED') {
            setProviderMode('MARKET_CLOSED');
          } else if (json?.dataStatus === 'LIVE') {
            setProviderMode('LIVE');
          } else if (json?.dataStatus === 'DATA_OFFLINE') {
            setProviderMode('DATA_OFFLINE');
          } else {
            setProviderMode('MOCK');
          }
          return;
        }
      } catch {
        // Fallback check
      }
      const health = await apiClient.getHealth();
      if (health && health.provider === 'real') {
        setProviderMode('LIVE');
      } else {
        setProviderMode('MOCK');
      }
    }
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleSelectStock = (symbol: string) => {
    setIsOpen(false);
    setQuery('');
    router.push(`/stocks/${symbol}`);
  };

  const scrollTicker = (dir: 'left' | 'right') => {
    if (tickerRef.current) {
      tickerRef.current.scrollBy({
        left: dir === 'left' ? -200 : 200,
        behavior: 'smooth',
      });
    }
  };

  return (
    <header className="sticky top-0 z-30 w-full bg-[var(--bg-surface)] border-b border-[var(--border-subtle)] transition-colors duration-200">
      {/* 1. Top Ticker Strip (Yahoo Finance style) */}
      <div className="w-full bg-[var(--bg-main)] border-b border-[var(--border-subtle)] px-3 py-1 flex items-center justify-between text-[11px] font-mono select-none overflow-hidden">
        <div className="flex items-center gap-2 flex-1 overflow-hidden">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)] shrink-0 pr-1 border-r border-[var(--border-subtle)]">
            Recent
          </span>
          <div
            ref={tickerRef}
            className="flex items-center gap-4 overflow-x-auto no-scrollbar scroll-smooth whitespace-nowrap py-0.5"
            style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
          >
            {TICKER_ITEMS.map((item) => {
              const isPos = item.change >= 0;
              return (
                <Link
                  key={item.symbol}
                  href={`/stocks/${item.symbol}`}
                  className="inline-flex items-center gap-1.5 hover:opacity-80 transition-opacity"
                >
                  <span className="font-semibold text-[var(--text-primary)]">
                    {item.symbol}
                  </span>
                  <span
                    className={`font-semibold ${
                      isPos ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
                    }`}
                  >
                    {isPos ? '+' : ''}
                    {item.change.toFixed(2)}%
                  </span>
                </Link>
              );
            })}
          </div>
        </div>

        <div className="hidden sm:flex items-center gap-1 shrink-0 pl-2">
          <button
            onClick={() => scrollTicker('left')}
            aria-label="Scroll left"
            className="p-1 rounded hover:bg-[var(--border-subtle)] text-[var(--text-muted)] transition-colors"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => scrollTicker('right')}
            aria-label="Scroll right"
            className="p-1 rounded hover:bg-[var(--border-subtle)] text-[var(--text-muted)] transition-colors"
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* 2. Main Header Bar */}
      <div className="w-full h-14 flex items-center justify-between px-4 sm:px-6 gap-3">
        {/* Left: Mobile Menu Button & Market Badges */}
        <div className="flex items-center gap-3">
          <button
            onClick={onToggleMobile}
            aria-label="Toggle Navigation Menu"
            className="p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] md:hidden hover:text-[var(--text-primary)]"
          >
            <Menu className="w-5 h-5" />
          </button>

          {/* Market Status Indicators */}
          <div className="hidden sm:flex items-center gap-2">
            <MarketStatusBadge exchange="NSE" status={marketStatus} />
            <MarketStatusBadge exchange="BSE" status={marketStatus} />
          </div>

          {/* Data Mode Indicator (LIVE vs MARKET_CLOSED vs DATA_OFFLINE vs MOCK) */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[10px] font-mono">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                providerMode === 'LIVE'
                  ? 'bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(52,211,153,0.8)]'
                  : providerMode === 'MARKET_CLOSED'
                  ? 'bg-blue-500'
                  : providerMode === 'DATA_OFFLINE'
                  ? 'bg-rose-500 animate-ping'
                  : 'bg-amber-500'
              }`}
            />
            <span
              className={`font-semibold ${
                providerMode === 'LIVE'
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : providerMode === 'MARKET_CLOSED'
                  ? 'text-blue-600 dark:text-blue-400'
                  : providerMode === 'DATA_OFFLINE'
                  ? 'text-rose-600 dark:text-rose-400'
                  : 'text-amber-600 dark:text-amber-400'
              }`}
            >
              {providerMode === 'LIVE'
                ? 'LIVE DATA'
                : providerMode === 'MARKET_CLOSED'
                ? 'MARKET CLOSED (EOD)'
                : providerMode === 'DATA_OFFLINE'
                ? 'DATA OFFLINE'
                : 'MOCK FEED'}
            </span>
          </div>

          {/* Live Clock */}
          <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-xs font-mono text-[var(--text-secondary)]">
            <Clock className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
            <span>IST Real-Time</span>
          </div>
        </div>

        {/* Center: Global Search Bar */}
        <div ref={searchRef} className="relative flex-1 max-w-xs sm:max-w-md mx-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-muted)]" />
            <input
              id="global-search-input"
              type="text"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setIsOpen(true);
              }}
              onFocus={() => setIsOpen(true)}
              placeholder="Search stocks, ETFs, & more..."
              className="w-full pl-9 pr-12 py-1.5 bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] focus:border-blue-500 focus:bg-[var(--bg-surface)] rounded-lg text-xs text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none transition-colors shadow-inner"
            />
            <kbd className="hidden sm:inline-block absolute right-2.5 top-1/2 -translate-y-1/2 px-1.5 py-0.5 rounded text-[10px] font-mono bg-[var(--bg-main)] text-[var(--text-muted)] border border-[var(--border-subtle)]">
              Ctrl+K
            </kbd>
          </div>

          {/* Autocomplete Dropdown */}
          {isOpen && query.trim() && (
            <div className="absolute left-0 right-0 top-full mt-1.5 bg-[var(--bg-surface)] border border-[var(--border-strong)] rounded-lg shadow-2xl overflow-hidden z-50">
              <div className="p-2 text-[10px] font-mono text-[var(--text-muted)] uppercase tracking-wider border-b border-[var(--border-subtle)] flex items-center justify-between bg-[var(--bg-main)]">
                <span>Matching Stocks</span>
                <span>{suggestions.length} results</span>
              </div>
              {suggestions.length > 0 ? (
                <div className="divide-y divide-[var(--border-subtle)]">
                  {suggestions.map((s) => (
                    <button
                      key={s.symbol}
                      onClick={() => handleSelectStock(s.symbol)}
                      className="w-full px-3 py-2.5 flex items-center justify-between hover:bg-[var(--bg-surface-hover)] text-left transition-colors group"
                    >
                      <div className="flex items-center gap-2">
                        <div className="w-6 h-6 rounded bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] flex items-center justify-center font-bold text-[10px] text-blue-600 dark:text-blue-400 font-mono">
                          {s.symbol.slice(0, 2)}
                        </div>
                        <div>
                          <div className="text-xs font-bold text-[var(--text-primary)] group-hover:text-blue-600 dark:group-hover:text-blue-400 font-mono">
                            {s.symbol}{' '}
                            <span className="text-[10px] font-normal text-[var(--text-muted)]">
                              • {s.exchange}
                            </span>
                          </div>
                          <div className="text-[11px] text-[var(--text-muted)] truncate max-w-[170px] sm:max-w-[220px]">
                            {s.companyName}
                          </div>
                        </div>
                      </div>
                      <div className="text-right font-mono">
                        <div className="text-xs font-bold text-[var(--text-primary)]">
                          {formatINR(s.currentPrice)}
                        </div>
                        <div
                          className={`text-[10px] ${
                            s.changePercent >= 0
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : 'text-rose-600 dark:text-rose-400'
                          }`}
                        >
                          {formatPercent(s.changePercent)}
                        </div>
                      </div>
                    </button>
                  ))}
                  <Link
                    href={`/search?q=${encodeURIComponent(query)}`}
                    onClick={() => setIsOpen(false)}
                    className="w-full px-3 py-2 flex items-center justify-center gap-1.5 text-xs text-blue-600 dark:text-blue-400 hover:underline font-mono bg-[var(--bg-main)] transition-colors"
                  >
                    <span>View all results for &quot;{query}&quot;</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              ) : (
                <div className="p-4 text-center text-xs text-[var(--text-muted)] font-mono">
                  No stocks matching &quot;{query}&quot;
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: Actions, Balance, Theme Toggle */}
        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          {/* Virtual Balance Chip */}
          <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-xs font-mono">
            <span className="text-[var(--text-muted)]">Demo Funds:</span>
            <span className="font-bold text-emerald-600 dark:text-emerald-400">
              {formatINR(virtualBalance)}
            </span>
          </div>

          {/* Theme Toggle Button */}
          <button
            onClick={toggleTheme}
            aria-label="Toggle theme"
            title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} mode`}
            className="p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            {theme === 'dark' ? (
              <Sun className="w-4 h-4 text-amber-500" />
            ) : (
              <Moon className="w-4 h-4 text-blue-600" />
            )}
          </button>

          {/* Quick Research/Article Button */}
          <Link
            href="/research"
            className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-50 dark:bg-blue-900/20 hover:bg-blue-100 dark:hover:bg-blue-900/30 border border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300 text-xs font-medium transition-all"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>AI News</span>
          </Link>

          {/* Notification Bell */}
          <div className="relative">
            <button
              onClick={() => setNotificationsOpen(!notificationsOpen)}
              aria-label="View notifications"
              className="p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] relative transition-colors"
            >
              <Bell className="w-4 h-4" />
              <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            </button>

            {/* Notifications Flyout */}
            {notificationsOpen && (
              <div className="absolute right-0 top-full mt-2 w-80 bg-[var(--bg-surface)] border border-[var(--border-strong)] rounded-xl shadow-2xl p-3 z-50">
                <div className="flex items-center justify-between pb-2 border-b border-[var(--border-subtle)]">
                  <span className="text-xs font-mono font-bold text-[var(--text-primary)]">
                    AI Signals & Alerts
                  </span>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 font-semibold">
                    2 New
                  </span>
                </div>
                <div className="space-y-2 pt-2 text-xs">
                  <div className="p-2 rounded-lg bg-[var(--bg-main)] border border-[var(--border-subtle)]">
                    <div className="flex items-center justify-between text-[11px] font-mono">
                      <span className="font-bold text-emerald-600 dark:text-emerald-400">RELIANCE • Bullish Alert</span>
                      <span className="text-[var(--text-muted)]">10:30 AM</span>
                    </div>
                    <p className="text-[11px] text-[var(--text-secondary)] mt-1">
                      Price crossed ₹1,455 with above-average volume (+45%). Upside probability 72%.
                    </p>
                  </div>
                  <div className="p-2 rounded-lg bg-[var(--bg-main)] border border-[var(--border-subtle)]">
                    <div className="flex items-center justify-between text-[11px] font-mono">
                      <span className="font-bold text-blue-600 dark:text-blue-400">NIFTY 50 • Breadth Expansion</span>
                      <span className="text-[var(--text-muted)]">10:15 AM</span>
                    </div>
                    <p className="text-[11px] text-[var(--text-secondary)] mt-1">
                      Advance/Decline ratio reaches 1.99x favoring bullish continuation.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* User Avatar */}
          <div className="flex items-center gap-2 pl-2 border-l border-[var(--border-subtle)]">
            <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/40 border border-blue-200 dark:border-blue-700 flex items-center justify-center font-mono font-bold text-xs text-blue-700 dark:text-blue-300 shadow-sm">
              AV
            </div>
          </div>
        </div>
      </div>
    </header>
  );
};
