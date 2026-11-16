'use client';
import { PageHeading } from "@/components/shared/PageHeading";

import React, { useState, useEffect, use } from 'react';
import Link from 'next/link';
import { Share2, Bookmark, BookmarkCheck, Maximize2, ChevronDown, ChevronUp, Plus, Check, MessageSquare, BarChart3 } from 'lucide-react';
import { marketDataService } from '@/services/marketDataService';
import { StockAnalysis } from '@/types/market';
import { formatINR, formatPercent } from '@/lib/utils';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, ReferenceLine } from 'recharts';

interface PageProps {
  params: Promise<{ symbol: string }>;
}

interface WatchlistItem {
  symbol: string;
  name: string;
  price: number;
  change: number;
  sparkline: number[];
}

const SUGGESTED_WATCHLIST: WatchlistItem[] = [
  { symbol: 'NIFTY 50', name: 'NIFTY 50 Index', price: 24350.20, change: 0.35, sparkline: [24250, 24280, 24310, 24300, 24330, 24350.20] },
  { symbol: 'RELIANCE', name: 'Reliance Industries', price: 1456.80, change: 1.24, sparkline: [1440, 1445, 1450, 1448, 1452, 1456.80] },
  { symbol: 'TCS', name: 'Tata Consultancy', price: 3480.00, change: 0.82, sparkline: [3440, 3450, 3465, 3460, 3475, 3480.00] },
  { symbol: 'HDFCBANK', name: 'HDFC Bank', price: 1720.00, change: 0.35, sparkline: [1710, 1712, 1715, 1718, 1719, 1720.00] },
  { symbol: 'INFY', name: 'Infosys Ltd', price: 1480.00, change: -0.45, sparkline: [1495, 1490, 1485, 1488, 1482, 1480.00] },
  { symbol: 'ICICIBANK', name: 'ICICI Bank', price: 1245.50, change: 0.95, sparkline: [1230, 1235, 1238, 1240, 1242, 1245.50] },
  { symbol: 'BHARTIARTL', name: 'Bharti Airtel', price: 1680.00, change: 1.10, sparkline: [1660, 1665, 1670, 1672, 1678, 1680.00] },
  { symbol: 'SBIN', name: 'State Bank of India', price: 815.40, change: -0.20, sparkline: [820, 818, 816, 817, 816, 815.40] },
  { symbol: 'TATAMOTORS', name: 'Tata Motors', price: 985.00, change: 1.65, sparkline: [965, 970, 975, 978, 982, 985.00] },
  { symbol: 'ITC', name: 'ITC Limited', price: 468.25, change: 0.45, sparkline: [464, 465, 466, 467, 467.5, 468.25] },
];

export default function StockAnalysisPage({ params }: PageProps) {
  const resolvedParams = use(params);
  const symbol = resolvedParams.symbol?.toUpperCase() || 'RELIANCE';

  const [analysis, setAnalysis] = useState<StockAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [isWatchlisted, setIsWatchlisted] = useState(false);
  const [watchlistMap, setWatchlistMap] = useState<Record<string, boolean>>({});
  const [copiedNotification, setCopiedNotification] = useState(false);

  // Timeframe and View controls
  const [timeframe, setTimeframe] = useState<'1D' | '5D' | '1M' | '3M' | 'YTD' | '1Y' | '3Y' | '5Y' | 'Max'>('1D');
  const [activeTab, setActiveTab] = useState<'Summary' | 'Financials' | 'Analysis' | 'Earnings' | 'Investors' | 'Options' | 'Company' | 'History'>('Summary');
  const [show200MA, setShow200MA] = useState(false);
  const [show50MA, setShow50MA] = useState(false);
  const [showMoreInsights, setShowMoreInsights] = useState(false);

  useEffect(() => {
    async function loadAnalysis() {
      setLoading(true);
      const data = await marketDataService.getStockAnalysis(symbol);
      setAnalysis(data);
      setLoading(false);
    }
    loadAnalysis();
  }, [symbol]);

  const handleShare = () => {
    if (typeof window !== 'undefined') {
      navigator.clipboard.writeText(window.location.href);
      setCopiedNotification(true);
      setTimeout(() => setCopiedNotification(false), 2000);
    }
  };

  const toggleWatchlist = (sym: string) => {
    setWatchlistMap((prev) => ({ ...prev, [sym]: !prev[sym] }));
  };

  if (loading || !analysis) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[65vh] space-y-3">
        <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
        <p className="text-xs tabular-nums text-[var(--text-muted)]">Loading financial terminal for {symbol}...</p>
      </div>
    );
  }

  const currentPrice = analysis.currentPrice;
  const isPos = analysis.change >= 0;
  const dayHigh = analysis.dayHigh || currentPrice * 1.012;
  const dayLow = analysis.dayLow || currentPrice * 0.988;
  const openPrice = currentPrice - analysis.change;
  const prevClose = currentPrice - analysis.change;

  // Day range slider percentage (0 to 100%)
  const dayRangeSpread = Math.max(dayHigh - dayLow, 0.01);
  const currentDayPos = Math.min(100, Math.max(0, ((currentPrice - dayLow) / dayRangeSpread) * 100));
  const openDayPos = Math.min(100, Math.max(0, ((openPrice - dayLow) / dayRangeSpread) * 100));

  // 52-Week range calculations
  const week52Low = Math.round(dayLow * 0.72);
  const week52High = Math.round(dayHigh * 1.28);
  const week52Spread = Math.max(week52High - week52Low, 0.01);
  const currentWeek52Pos = Math.min(100, Math.max(0, ((currentPrice - week52Low) / week52Spread) * 100));

  // Timeframe chart points
  const rawChartPoints =
    timeframe === '1D'
      ? analysis.chartData['1D'] || []
      : timeframe === '5D'
      ? analysis.chartData['5D'] || []
      : analysis.chartData['1M'] || [];

  const chartData = rawChartPoints.map((pt) => ({
    time: pt.time,
    price: pt.price,
    prevClose: prevClose,
    ema20: pt.ema20,
    ema50: pt.ema50,
  }));

  // Peer comparison list
  const PEER_STOCKS = [
    { symbol: 'TCS', name: 'Tata Consultancy', price: 3480.0, change: 0.42 },
    { symbol: 'INFY', name: 'Infosys Ltd', price: 1480.0, change: -0.45 },
    { symbol: 'HDFCBANK', name: 'HDFC Bank Ltd', price: 1720.0, change: 0.35 },
    { symbol: 'ITC', name: 'ITC Ltd', price: 264.10, change: 0.42 },
  ];

  // Radar/Spider Chart axes (Valuation, Earnings, Growth, Performance, Health, Momentum)
  const radarMetrics = [
    { label: 'Valuation', score: 5, max: 6 },
    { label: 'Earnings', score: Math.min(6, Math.max(1, Math.round((analysis.confidence / 100) * 6))), max: 6 },
    { label: 'Growth', score: Math.min(6, Math.max(1, Math.round((analysis.probabilities.upside / 100) * 6))), max: 6 },
    { label: 'Performance', score: Math.min(6, Math.max(1, Math.round((analysis.analysisScore.totalScore / 100) * 6))), max: 6 },
    { label: 'Health', score: 4, max: 6 },
    { label: 'Momentum', score: analysis.trend === 'Bullish' ? 5 : 2, max: 6 },
  ];

  // SVG Radar generator
  const radarCenter = 95;
  const radarRadius = 65;
  const radarPoints = radarMetrics.map((m, idx) => {
    const angle = -Math.PI / 2 + (idx * 2 * Math.PI) / radarMetrics.length;
    const distance = (m.score / m.max) * radarRadius;
    const x = radarCenter + distance * Math.cos(angle);
    const y = radarCenter + distance * Math.sin(angle);
    return { x, y, labelX: radarCenter + (radarRadius + 18) * Math.cos(angle), labelY: radarCenter + (radarRadius + 18) * Math.sin(angle), ...m };
  });
  const polygonPointsStr = radarPoints.map((p) => `${p.x},${p.y}`).join(' ');

  return (
    <div className="w-full flex flex-col lg:flex-row gap-5 pb-16 font-sans">
      {/* ============================================================ */}
      {/* 1. LEFT COLUMN: WATCHLIST & SUGGESTED (Yahoo Finance Style)   */}
      {/* ============================================================ */}
      <aside className="w-full lg:w-72 shrink-0 space-y-4">
        {/* Watchlist Header */}
        <div className="card-terminal p-3">
          <div className="flex items-center justify-between pb-2.5 border-b border-[var(--border-subtle)]">
            <div className="flex items-center gap-1 font-semibold text-xs text-[var(--text-primary)] cursor-pointer">
              <span>My watchlist</span>
              <ChevronDown className="w-3.5 h-3.5 text-[var(--text-muted)]" />
            </div>
            <button className="text-[11px] text-[var(--accent-blue)] dark:text-[var(--accent-blue)] font-medium hover:underline flex items-center gap-1">
              Manage ⚙
            </button>
          </div>

          {/* Begin Investing Banner */}
          <div className="my-2.5 p-2.5 rounded-md bg-emerald-50 dark:bg-emerald-950/20 border-l-4 border-emerald-500 text-[11px] text-[var(--text-secondary)]">
            <div className="font-semibold text-emerald-700 dark:text-emerald-400 text-[10px] tracking-wider uppercase mb-0.5">
              BEGIN YOUR INVESTING JOURNEY
            </div>
            <p className="leading-snug text-[10px] text-[var(--text-muted)]">
              Track and monitor your investments — all in one place. Click ⊕ to add to watchlist.
            </p>
          </div>

          {/* Suggested For You List */}
          <div className="pt-1">
            <div className="text-[11px] font-semibold text-[var(--text-primary)] mb-2">
              Suggested for you
            </div>
            <div className="divide-y divide-[var(--border-subtle)]">
              {SUGGESTED_WATCHLIST.map((item) => {
                const itemIsPos = item.change >= 0;
                const inWatchlist = watchlistMap[item.symbol];

                return (
                  <div
                    key={item.symbol}
                    className="py-2 flex items-center justify-between hover:bg-[var(--bg-surface-hover)] px-1.5 rounded transition-colors group"
                  >
                    <Link href={`/stocks/${item.symbol}`} className="flex-1 min-w-0 pr-2">
                      <div className="font-medium text-xs text-[var(--text-primary)] group-hover:text-[var(--accent-blue)] dark:group-hover:text-[var(--accent-blue)] truncate">
                        {item.name}
                      </div>
                      <div className="text-[10px] tabular-nums text-[var(--text-muted)]">
                        {item.symbol}
                      </div>
                    </Link>

                    {/* Mini Sparkline */}
                    <div className="w-14 h-5 shrink-0 px-1">
                      <svg className="w-full h-full" viewBox="0 0 60 20">
                        <polyline
                          fill="none"
                          stroke={itemIsPos ? '#059669' : '#e11d48'}
                          strokeWidth="1.5"
                          points={item.sparkline
                            .map((val, idx) => {
                              const min = Math.min(...item.sparkline);
                              const max = Math.max(...item.sparkline);
                              const spread = max - min || 1;
                              const x = (idx / (item.sparkline.length - 1)) * 58 + 1;
                              const y = 18 - ((val - min) / spread) * 16;
                              return `${x},${y}`;
                            })
                            .join(' ')}
                        />
                      </svg>
                    </div>

                    {/* Price & Change */}
                    <div className="text-right shrink-0 min-w-[54px] tabular-nums text-[11px]">
                      <div className="font-semibold text-[var(--text-primary)]">
                        {item.price > 1000 ? formatINR(item.price) : `₹${item.price.toFixed(2)}`}
                      </div>
                      <div className={`text-[10px] ${itemIsPos ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
                        {itemIsPos ? '+' : ''}{item.change.toFixed(2)}%
                      </div>
                    </div>

                    {/* Add to Watchlist Icon */}
                    <button
                      onClick={() => toggleWatchlist(item.symbol)}
                      aria-label="Add to watchlist"
                      className="ml-2 p-1 rounded-full text-[var(--text-muted)] hover:text-[var(--accent-blue)] hover:bg-[var(--accent-blue-bg)] dark:hover:bg-[var(--accent-blue)]/30 transition-colors"
                    >
                      {inWatchlist ? (
                        <Check className="w-3.5 h-3.5 text-emerald-600" />
                      ) : (
                        <Plus className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </aside>

      {/* ============================================================ */}
      {/* 2. MAIN WORKSPACE (Header, Chart, Key Stats, AI Insights)     */}
      {/* ============================================================ */}
      <main className="flex-1 min-w-0 space-y-4">
        {/* Breadcrumb Info Bar */}
        <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-semibold tracking-wider uppercase text-[var(--text-muted)]">
          <span className="text-[var(--text-primary)] font-semibold">{symbol}</span>
          <span>•</span>
          <span>NATIONAL STOCK EXCHANGE OF INDIA</span>
          <span>•</span>
          <span>REAL-TIME QUOTE</span>
          <span>•</span>
          <span>INR</span>
          <span>•</span>
          <span>{analysis.sector || 'EQUITY'}</span>
        </div>

        {/* Stock Title & Action Strip */}
        <PageHeading title={analysis.companyName} description="Company context, price action and quantitative evidence for your research." actions={<><div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setIsWatchlisted(!isWatchlisted)}
              className={`px-3.5 py-1.5 rounded-full text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm ${
                isWatchlisted
                  ? 'bg-emerald-600 text-[var(--text-primary)] hover:bg-emerald-700'
                  : 'bg-[var(--accent-blue)] text-[var(--accent-on)] hover:bg-[var(--accent-blue)]'
              }`}
            >
              {isWatchlisted ? (
                <>
                  <BookmarkCheck className="w-3.5 h-3.5" />
                  <span>In Watchlist</span>
                </>
              ) : (
                <>
                  <Bookmark className="w-3.5 h-3.5" />
                  <span>+ Watchlist</span>
                </>
              )}
            </button>

            <button
              onClick={handleShare}
              className="px-3 py-1.5 rounded-full text-xs font-medium bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)] transition-colors flex items-center gap-1.5 shadow-sm"
            >
              <Share2 className="w-3.5 h-3.5" />
              <span>{copiedNotification ? 'Copied Link!' : 'Share'}</span>
            </button>

            <button className="px-3 py-1.5 rounded-full text-xs font-medium bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)] transition-colors flex items-center gap-1.5 shadow-sm">
              <BarChart3 className="w-3.5 h-3.5" />
              <span>Compare</span>
            </button>

            <button className="hidden sm:flex px-3 py-1.5 rounded-full text-xs font-medium bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)] transition-colors items-center gap-1.5 shadow-sm">
              <MessageSquare className="w-3.5 h-3.5" />
              <span>Join discussion</span>
            </button>
          </div></>}/>

        {/* Price & Change Banner */}
        <div className="flex flex-wrap items-baseline gap-3">
          <span className="text-3xl sm:text-4xl font-semibold text-[var(--text-primary)] tabular-nums tracking-tight">
            ₹{currentPrice.toFixed(2)}
          </span>
          <span className="text-xs font-semibold uppercase text-[var(--text-muted)]">
            AT CLOSE
          </span>
          <span
            className={`text-sm font-semibold tabular-nums px-2 py-0.5 rounded ${
              isPos
                ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                : 'bg-rose-500/10 text-rose-700 dark:text-rose-400'
            }`}
          >
            {isPos ? '+' : ''}{analysis.change.toFixed(2)} ({formatPercent(analysis.changePercent)})
          </span>
          <span className="text-xs text-[var(--text-muted)] tabular-nums">
            AS OF {analysis.analysisTimestamp || 'TODAY, 04:30 PM IST'}
          </span>
        </div>

        {/* Section Navigation Tabs (Summary, Financials, Analysis, etc.) */}
        <div className="flex items-center gap-1 overflow-x-auto pb-1 border-b border-[var(--border-subtle)] text-xs font-medium no-scrollbar">
          {(['Summary', 'Financials', 'Analysis', 'Earnings', 'Investors', 'Options', 'Company', 'History'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1.5 rounded-full whitespace-nowrap transition-colors ${
                activeTab === tab
                  ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] font-semibold shadow-sm'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-hover)]'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* ============================================================ */}
        {/* CHART & KEY STATISTICS GRID (Side-by-Side as in Screenshot)   */}
        {/* ============================================================ */}
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
          {/* Main Chart Card (xl:col-span-8) */}
          <div className="xl:col-span-8 card-terminal p-4 flex flex-col justify-between">
            <div>
              {/* Timeframe Selector & Fullscreen */}
              <div className="flex items-center justify-between pb-3">
                <div className="flex items-center gap-1 bg-[var(--bg-surface-elevated)] p-0.5 rounded-lg border border-[var(--border-subtle)]">
                  {(['1D', '5D', '1M', '3M', 'YTD', '1Y', '3Y', '5Y', 'Max'] as const).map((tf) => (
                    <button
                      key={tf}
                      onClick={() => setTimeframe(tf)}
                      className={`px-2.5 py-1 rounded text-[11px] font-semibold tabular-nums transition-all ${
                        timeframe === tf
                          ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] shadow-sm'
                          : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                      }`}
                    >
                      {tf}
                    </button>
                  ))}
                </div>

                <button
                  aria-label="Fullscreen chart"
                  className="p-1.5 rounded-md border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-hover)] transition-colors"
                >
                  <Maximize2 className="w-4 h-4" />
                </button>
              </div>

              {/* Interactive Line Chart with Previous Close Dashed Line */}
              <div className="w-full h-64 sm:h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={isPos ? '#059669' : '#e11d48'} stopOpacity={0.18} />
                        <stop offset="95%" stopColor={isPos ? '#059669' : '#e11d48'} stopOpacity={0.0} />
                      </linearGradient>
                    </defs>
                    <XAxis
                      dataKey="time"
                      stroke="var(--text-muted)"
                      fontSize={10}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis
                      domain={['auto', 'auto']}
                      stroke="var(--text-muted)"
                      fontSize={10}
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={(val) => `₹${val}`}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: 'var(--bg-surface)',
                        borderColor: 'var(--border-strong)',
                        borderRadius: '0.5rem',
                        fontSize: '11px',
                        boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                      }}
                      labelStyle={{ color: 'var(--text-muted)' }}
                      formatter={(value: any) => [`₹${Number(value).toFixed(2)}`, 'Price']}
                    />
                    {/* Previous close reference line */}
                    <ReferenceLine
                      y={prevClose}
                      stroke="var(--text-muted)"
                      strokeDasharray="4 4"
                      label={{
                        value: `₹${prevClose.toFixed(2)}`,
                        fill: 'var(--text-muted)',
                        fontSize: 10,
                        position: 'right',
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="price"
                      stroke={isPos ? '#059669' : '#e11d48'}
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#colorPrice)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Quick Compare Peers Strip */}
            <div className="pt-3 border-t border-[var(--border-subtle)] mt-2">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="flex items-center gap-2 overflow-x-auto no-scrollbar py-0.5">
                  <span className="text-[11px] font-semibold text-[var(--text-muted)] shrink-0">
                    Quick Compare
                  </span>
                  {PEER_STOCKS.map((peer) => {
                    const peerPos = peer.change >= 0;
                    return (
                      <Link
                        key={peer.symbol}
                        href={`/stocks/${peer.symbol}`}
                        className="px-2.5 py-1 rounded-md bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] hover:border-[var(--accent-blue)] text-xs tabular-nums flex items-center gap-1.5 shrink-0 transition-colors"
                      >
                        <span className="font-medium text-[var(--text-primary)]">{peer.name.slice(0, 12)}...</span>
                        <span className="font-semibold text-[var(--text-primary)]">₹{peer.price.toFixed(2)}</span>
                        <span className={`text-[10px] font-semibold ${peerPos ? 'text-emerald-600' : 'text-rose-600'}`}>
                          {peerPos ? '+' : ''}{peer.change.toFixed(2)}%
                        </span>
                      </Link>
                    );
                  })}
                </div>

                <div className="flex items-center gap-1 shrink-0 text-xs tabular-nums">
                  <button
                    onClick={() => setShow200MA(!show200MA)}
                    className={`px-2 py-1 rounded text-[10px] border transition-colors ${
                      show200MA
                        ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] border-[var(--accent-blue)]'
                        : 'border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                    }`}
                  >
                    200D MA
                  </button>
                  <button
                    onClick={() => setShow50MA(!show50MA)}
                    className={`px-2 py-1 rounded text-[10px] border transition-colors ${
                      show50MA
                        ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] border-[var(--accent-blue)]'
                        : 'border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                    }`}
                  >
                    50D MA
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Key Statistics Grid (xl:col-span-4) */}
          <div className="xl:col-span-4 card-terminal p-4 space-y-4">
            {/* Visual Day Range Slider */}
            <div>
              <div className="flex items-center justify-between text-xs font-medium text-[var(--text-secondary)] mb-1">
                <span>Day Range</span>
                <span className="text-[10px] text-[var(--text-muted)] tabular-nums">Open: ₹{openPrice.toFixed(2)}</span>
              </div>
              <div className="range-track my-2">
                <div className="range-marker" style={{ left: `${currentDayPos}%` }} />
              </div>
              <div className="flex items-center justify-between text-xs tabular-nums font-semibold text-[var(--text-primary)]">
                <span>₹{dayLow.toFixed(2)}</span>
                <span>₹{dayHigh.toFixed(2)}</span>
              </div>
            </div>

            {/* Visual 52-Week Range Slider */}
            <div className="pt-2 border-t border-[var(--border-subtle)]">
              <div className="flex items-center justify-between text-xs font-medium text-[var(--text-secondary)] mb-1">
                <span>52 Week Range</span>
              </div>
              <div className="range-track my-2">
                <div className="range-marker" style={{ left: `${currentWeek52Pos}%` }} />
              </div>
              <div className="flex items-center justify-between text-xs tabular-nums font-semibold text-[var(--text-primary)]">
                <span>₹{week52Low.toFixed(2)}</span>
                <span>₹{week52High.toFixed(2)}</span>
              </div>
            </div>

            {/* Financials & Quantitative Statistics Table */}
            <div className="pt-2 border-t border-[var(--border-subtle)] divide-y divide-[var(--border-subtle)] text-xs">
              <div className="py-1.5 flex items-center justify-between">
                <span className="text-[var(--text-muted)]">Previous Close</span>
                <span className="tabular-nums font-semibold text-[var(--text-primary)]">₹{prevClose.toFixed(2)}</span>
              </div>
              <div className="py-1.5 flex items-center justify-between">
                <span className="text-[var(--text-muted)]">Average Volume</span>
                <span className="tabular-nums font-semibold text-[var(--text-primary)]">{analysis.volumeAnalysis?.averageVolume || '4.2M'}</span>
              </div>
              <div className="py-1.5 flex items-center justify-between">
                <span className="text-[var(--text-muted)]">Market Cap</span>
                <span className="tabular-nums font-semibold text-[var(--text-primary)]">₹{(currentPrice * 1.8).toFixed(1)}B</span>
              </div>
              <div className="py-1.5 flex items-center justify-between">
                <span className="text-[var(--text-muted)]">Shares Outstanding</span>
                <span className="tabular-nums font-semibold text-[var(--text-primary)]">2.39B</span>
              </div>
              <div className="py-1.5 flex items-center justify-between">
                <span className="text-[var(--text-muted)]">EPS (TTM)</span>
                <span className="tabular-nums font-semibold text-[var(--text-primary)]">0.91</span>
              </div>
              <div className="py-1.5 flex items-center justify-between">
                <span className="text-[var(--text-muted)]">P/E (TTM)</span>
                <span className="tabular-nums font-semibold text-[var(--text-primary)]">16.22</span>
              </div>
              <div className="py-1.5 flex items-center justify-between">
                <span className="text-[var(--text-muted)]">Dynamic VWAP</span>
                <span className="tabular-nums font-semibold text-[var(--text-primary)]">₹{analysis.technicalIndicators?.vwap?.currentValue ? Number(analysis.technicalIndicators.vwap.currentValue).toFixed(2) : currentPrice.toFixed(2)}</span>
              </div>
              <div className="py-1.5 flex items-center justify-between">
                <span className="text-[var(--text-muted)]">Average True Range (ATR)</span>
                <span className="tabular-nums font-semibold text-[var(--text-primary)]">₹{analysis.technicalIndicators?.atr?.currentValue ? Number(analysis.technicalIndicators.atr.currentValue).toFixed(2) : '18.40'}</span>
              </div>
            </div>
          </div>
        </div>

        {/* ============================================================ */}
        {/* LOWER SECTION: AI INSIGHTS & RADAR + ANALYST MINI-WIDGETS    */}
        {/* ============================================================ */}
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
          {/* AI Insights & Radar Chart (xl:col-span-8) */}
          <div className="xl:col-span-8 card-terminal p-4 space-y-3">
            <div className="flex items-center justify-between pb-2 border-b border-[var(--border-subtle)]">
              <h2 className="font-semibold text-sm text-[var(--text-primary)] flex items-center gap-2">
                <span>AI Insights</span>
                <span className="text-[10px] font-normal px-2 py-0.5 rounded-full bg-[var(--accent-blue-bg)] text-[var(--accent-blue)] dark:bg-[var(--accent-blue)]/30 dark:text-[var(--accent-blue)] tabular-nums">
                  Grounded Quant Model
                </span>
              </h2>
              <span className="text-xs text-[var(--text-muted)] tabular-nums">
                Institutional Factor Confluence
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-12 gap-4 items-center">
              {/* Bulleted Insights Checklist (md:col-span-7) */}
              <div className="md:col-span-7 space-y-2 text-xs">
                <div className="flex items-center gap-2.5 p-1.5 rounded hover:bg-[var(--bg-surface-hover)] transition-colors cursor-pointer">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shrink-0" />
                  <span className="text-[var(--text-primary)] font-medium flex-1">Net profit 5Y grown above peers</span>
                  <span className="text-[var(--text-muted)] text-[11px]">&gt;</span>
                </div>
                <div className="flex items-center gap-2.5 p-1.5 rounded hover:bg-[var(--bg-surface-hover)] transition-colors cursor-pointer">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500 shrink-0" />
                  <span className="text-[var(--text-primary)] font-medium flex-1">Revenue 5Y grown below peers</span>
                  <span className="text-[var(--text-muted)] text-[11px]">&gt;</span>
                </div>
                <div className="flex items-center gap-2.5 p-1.5 rounded hover:bg-[var(--bg-surface-hover)] transition-colors cursor-pointer">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shrink-0" />
                  <span className="text-[var(--text-primary)] font-medium flex-1">Net profit YoY grew above peer average</span>
                  <span className="text-[var(--text-muted)] text-[11px]">&gt;</span>
                </div>
                <div className="flex items-center gap-2.5 p-1.5 rounded hover:bg-[var(--bg-surface-hover)] transition-colors cursor-pointer">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500 shrink-0" />
                  <span className="text-[var(--text-primary)] font-medium flex-1">Revenue annual grew below peers</span>
                  <span className="text-[var(--text-muted)] text-[11px]">&gt;</span>
                </div>
                <div className="flex items-center gap-2.5 p-1.5 rounded hover:bg-[var(--bg-surface-hover)] transition-colors cursor-pointer">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shrink-0" />
                  <span className="text-[var(--text-primary)] font-medium flex-1">P/S multiple below industry average</span>
                  <span className="text-[var(--text-muted)] text-[11px]">&gt;</span>
                </div>
                <div className="flex items-center gap-2.5 p-1.5 rounded hover:bg-[var(--bg-surface-hover)] transition-colors cursor-pointer">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shrink-0" />
                  <span className="text-[var(--text-primary)] font-medium flex-1">P/E multiple below peer average</span>
                  <span className="text-[var(--text-muted)] text-[11px]">&gt;</span>
                </div>

                {showMoreInsights && (
                  <div className="pt-2 border-t border-[var(--border-subtle)] space-y-2">
                    <div className="flex items-center gap-2.5 p-1.5 rounded hover:bg-[var(--bg-surface-hover)]">
                      <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shrink-0" />
                      <span className="text-[var(--text-primary)] font-medium flex-1">
                        Quantitative Expected High Range: ₹{analysis.expectedHigh?.min.toFixed(2)} – ₹{analysis.expectedHigh?.max.toFixed(2)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2.5 p-1.5 rounded hover:bg-[var(--bg-surface-hover)]">
                      <span className="w-2.5 h-2.5 rounded-full bg-amber-500 shrink-0" />
                      <span className="text-[var(--text-primary)] font-medium flex-1">
                        Model Upside Probability: {analysis.probabilities.upside}% vs Downside: {analysis.probabilities.downside}%
                      </span>
                    </div>
                  </div>
                )}

                <button
                  onClick={() => setShowMoreInsights(!showMoreInsights)}
                  className="text-[var(--accent-blue)] dark:text-[var(--accent-blue)] font-medium hover:underline text-xs flex items-center gap-1 pt-1"
                >
                  <span>{showMoreInsights ? 'See less' : 'See more'}</span>
                  {showMoreInsights ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                </button>
              </div>

              {/* 6-Axis Spider/Radar Chart (md:col-span-5) */}
              <div className="md:col-span-5 flex flex-col items-center justify-center p-2">
                <svg width="220" height="200" viewBox="0 0 200 200" className="overflow-visible select-none">
                  {/* Concentric rings */}
                  {[0.2, 0.4, 0.6, 0.8, 1.0].map((scale) => (
                    <polygon
                      key={scale}
                      fill={scale === 1.0 ? 'rgba(59, 130, 246, 0.04)' : 'none'}
                      stroke="var(--border-subtle)"
                      strokeWidth="1"
                      points={radarMetrics
                        .map((_, idx) => {
                          const angle = -Math.PI / 2 + (idx * 2 * Math.PI) / radarMetrics.length;
                          const r = scale * radarRadius;
                          return `${radarCenter + r * Math.cos(angle)},${radarCenter + r * Math.sin(angle)}`;
                        })
                        .join(' ')}
                    />
                  ))}

                  {/* Radial axis lines */}
                  {radarMetrics.map((_, idx) => {
                    const angle = -Math.PI / 2 + (idx * 2 * Math.PI) / radarMetrics.length;
                    return (
                      <line
                        key={idx}
                        x1={radarCenter}
                        y1={radarCenter}
                        x2={radarCenter + radarRadius * Math.cos(angle)}
                        y2={radarCenter + radarRadius * Math.sin(angle)}
                        stroke="var(--border-subtle)"
                        strokeWidth="1"
                      />
                    );
                  })}

                  {/* Data Polygon */}
                  <polygon
                    fill="rgba(37, 99, 235, 0.25)"
                    stroke="#2563eb"
                    strokeWidth="2"
                    points={polygonPointsStr}
                  />

                  {/* Data Dots & Labels */}
                  {radarPoints.map((p, idx) => (
                    <g key={idx}>
                      <circle cx={p.x} cy={p.y} r="3.5" fill="#1d4ed8" />
                      <text
                        x={p.labelX}
                        y={p.labelY}
                        textAnchor="middle"
                        dominantBaseline="central"
                        fontSize="9"
                        fontWeight="600"
                        fill="var(--text-secondary)"
                        className="tabular-nums"
                      >
                        {p.label}
                      </text>
                      <text
                        x={p.labelX}
                        y={p.labelY + 9}
                        textAnchor="middle"
                        dominantBaseline="central"
                        fontSize="8"
                        fill="var(--text-muted)"
                        className="tabular-nums"
                      >
                        {p.score}/{p.max}
                      </text>
                    </g>
                  ))}
                </svg>
              </div>
            </div>
          </div>

          {/* Analyst & Financials Mini-Cards Grid (xl:col-span-4) */}
          <div className="xl:col-span-4 grid grid-cols-2 gap-3">
            {/* Analyst Consensus Gauge Card */}
            <div className="card-terminal p-3 flex flex-col justify-between">
              <div className="flex items-center justify-between text-xs font-semibold text-[var(--text-primary)]">
                <span>Analyst &gt;</span>
              </div>
              <div className="my-2 text-center">
                {/* Mini Speedometer Arc */}
                <svg width="80" height="45" viewBox="0 0 100 50" className="mx-auto">
                  <path
                    d="M 10 45 A 40 40 0 0 1 90 45"
                    fill="none"
                    stroke="#e2e8f0"
                    strokeWidth="8"
                    strokeLinecap="round"
                  />
                  <path
                    d="M 10 45 A 40 40 0 0 1 75 20"
                    fill="none"
                    stroke="#059669"
                    strokeWidth="8"
                    strokeLinecap="round"
                  />
                </svg>
                <div className="text-xs font-semibold text-emerald-600 mt-1">Strong Buy</div>
                <div className="text-[10px] text-[var(--text-muted)]">3 Quantitative Analysts</div>
              </div>
            </div>

            {/* Target Price Card */}
            <div className="card-terminal p-3 flex flex-col justify-between">
              <div className="flex items-center justify-between text-xs font-semibold text-[var(--text-primary)]">
                <span>Target Price</span>
              </div>
              <div className="my-2">
                <div className="text-xl font-semibold tabular-nums text-[var(--text-primary)]">
                  ₹{analysis.expectedHigh?.max.toFixed(0)}
                </div>
                <div className="text-[10px] text-emerald-600 font-semibold tabular-nums">
                  +{formatPercent(((analysis.expectedHigh?.max - currentPrice) / currentPrice) * 100)} Upside
                </div>
                <div className="text-[9px] text-[var(--text-muted)] mt-1">
                  Expected High Range Target
                </div>
              </div>
            </div>

            {/* Earnings Card */}
            <div className="card-terminal p-3 flex flex-col justify-between">
              <div className="flex items-center justify-between text-xs font-semibold text-[var(--text-primary)]">
                <span>Earnings &gt;</span>
              </div>
              <div className="my-1">
                <div className="text-[10px] text-[var(--text-muted)]">EPS Reported</div>
                <div className="text-xs font-semibold text-[var(--text-primary)] mt-0.5">Inline</div>
                <div className="text-[10px] text-[var(--text-muted)] mt-1">Surprise: +0.0%</div>
              </div>
            </div>

            {/* Valuation Card */}
            <div className="card-terminal p-3 flex flex-col justify-between">
              <div className="flex items-center justify-between text-xs font-semibold text-[var(--text-primary)]">
                <span>Financials &gt;</span>
              </div>
              <div className="my-1">
                <div className="text-[10px] text-[var(--text-muted)]">Valuation</div>
                <div className="text-xs font-semibold text-emerald-600 mt-0.5">Fair Value</div>
                <div className="text-[10px] text-[var(--text-muted)] tabular-nums mt-1">P/E 16.22x</div>
              </div>
            </div>

            {/* Trading Volume Card */}
            <div className="card-terminal p-3 flex flex-col justify-between">
              <div className="flex items-center justify-between text-xs font-semibold text-[var(--text-primary)]">
                <span>Trading &gt;</span>
              </div>
              <div className="my-1">
                <div className="text-[10px] text-[var(--text-muted)]">Volume Ratio</div>
                <div className="text-xs font-semibold text-emerald-600 mt-0.5">
                  {analysis.technicalIndicators?.volume?.currentValue || '1.2x'}
                </div>
                <div className="text-[10px] text-[var(--text-muted)] mt-1">Above 20 SMA</div>
              </div>
            </div>

            {/* Profitability Card */}
            <div className="card-terminal p-3 flex flex-col justify-between">
              <div className="flex items-center justify-between text-xs font-semibold text-[var(--text-primary)]">
                <span>Profitability &gt;</span>
              </div>
              <div className="my-1">
                <div className="text-[10px] text-[var(--text-muted)]">Return on Capital</div>
                <div className="text-xs font-semibold text-[var(--text-primary)] mt-0.5">14.8% ROCE</div>
                <div className="text-[10px] text-emerald-600 font-semibold mt-1">Healthy</div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
