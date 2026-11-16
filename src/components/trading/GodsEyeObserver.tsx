'use client';

import React, { useState, useEffect } from 'react';
import { Activity, BarChart3, TrendingUp, Anchor, Crosshair, Zap, Info, RefreshCw, ArrowUpRight, ArrowDownRight, Gauge, Newspaper, ExternalLink, Clock, Sparkles } from 'lucide-react';
import { ObserverIntelligenceData, ObserverAsset } from '@/types/observer';
import { marketDataService } from '@/services/marketDataService';
import { MOCK_OBSERVER_DATA } from '@/lib/api';

// Senior-grade vector sparkline with gradient area fill
const SeniorSparkline: React.FC<{
  data: number[];
  color: 'green' | 'red' | 'blue';
  height?: number;
}> = ({ data, color, height = 44 }) => {
  if (!data || data.length === 0) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const width = 160;

  const points = data.map((val, idx) => {
    const x = (idx / (data.length - 1)) * width;
    const y = height - 6 - ((val - min) / range) * (height - 14);
    return { x, y };
  });

  const polylineStr = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const areaStr = `0,${height} ${polylineStr} ${width},${height}`;

  const strokeColor =
    color === 'green' ? '#10b981' : color === 'red' ? '#f43f5e' : '#3b82f6';
  const gradId = `spark-grad-${color}-${data[0] || 0}`;

  return (
    <div className="w-full flex items-center justify-end overflow-hidden">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-11 overflow-visible"
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={strokeColor} stopOpacity="0.22" />
            <stop offset="100%" stopColor={strokeColor} stopOpacity="0.0" />
          </linearGradient>
        </defs>
        <polygon points={areaStr} fill={`url(#${gradId})`} />
        <polyline
          fill="none"
          stroke={strokeColor}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          points={polylineStr}
        />
      </svg>
    </div>
  );
};

// Institutional Donut Chart Component
const DonutChart: React.FC<{
  bullish: number;
  bearish: number;
  neutral: number;
  volatile: number;
}> = ({ bullish, bearish, neutral, volatile }) => {
  const total = bullish + bearish + neutral + volatile || 100;
  const radius = 36;
  const circumference = 2 * Math.PI * radius;

  const segments = [
    { percent: bullish / total, color: '#10b981' },
    { percent: bearish / total, color: '#f43f5e' },
    { percent: neutral / total, color: '#6366f1' },
    { percent: volatile / total, color: '#f59e0b' },
  ];

  let accumulated = 0;

  return (
    <div className="relative w-28 h-28 flex items-center justify-center shrink-0">
      <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="transparent"
          stroke="currentColor"
          className="text-[var(--text-primary)] dark:text-[var(--text-primary)]"
          strokeWidth="11"
        />
        {segments.map((seg, idx) => {
          const strokeDash = `${seg.percent * circumference} ${circumference}`;
          const strokeOffset = -accumulated * circumference;
          accumulated += seg.percent;

          return (
            <circle
              key={idx}
              cx="50"
              cy="50"
              r={radius}
              fill="transparent"
              stroke={seg.color}
              strokeWidth="11"
              strokeDasharray={strokeDash}
              strokeDashoffset={strokeOffset}
              className="transition-all duration-700 ease-out"
            />
          );
        })}
      </svg>
      <div className="absolute inset-0 m-auto w-14 h-14 rounded-full bg-[var(--bg-surface)] border border-[var(--border-subtle)] flex items-center justify-center shadow-xs">
        <Activity className="w-4 h-4 text-[var(--accent-blue)] dark:text-[var(--accent-blue)] animate-pulse" />
      </div>
    </div>
  );
};

export const GodsEyeObserver: React.FC = () => {
  const [data, setData] = useState<ObserverIntelligenceData>(MOCK_OBSERVER_DATA);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedAsset, setSelectedAsset] = useState<ObserverAsset | null>(null);
  const [newsFilter, setNewsFilter] = useState<'ALL' | 'BULLISH' | 'BEARISH' | 'NEUTRAL'>('ALL');

  const loadData = async () => {
    try {
      const res = await marketDataService.getObserverIntelligence();
      if (res) {
        setData(res);
      }
    } catch (e) {
      console.warn('Using mock observer data due to network error:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, []);

  const rawNewsList = data.latestNews || MOCK_OBSERVER_DATA.latestNews || [];
  const filteredNews = rawNewsList.filter((n) => {
    if (newsFilter === 'ALL') return true;
    return n.sentiment?.toUpperCase() === newsFilter;
  });

  return (
    <div className="space-y-4 tabular-nums">
      {/* 1. TOP STATUS COCKPIT BAR */}
      <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 sm:p-5 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 flex items-center justify-center shrink-0">
            <Gauge className="w-4 h-4 text-[var(--accent-blue)] dark:text-[var(--accent-blue)]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-[var(--text-primary)] tracking-tight">
                Market Sentiment & Signal Radar
              </h2>
            </div>
            <p className="text-[11px] text-[var(--text-muted)]">
              Cross-asset bullish vs bearish indicators, live news catalysts, market breadth & quantitative strength
            </p>
          </div>
        </div>

        {/* Status Indicators */}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {/* Pre-Market Badge */}
          <span className="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-ping" />
            {data.marketSession || 'Pre-Market'}
          </span>

          {/* Timestamp */}
          <span className="text-[11px] text-[var(--text-muted)] px-2.5 py-1 rounded-md bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
            Updated: {data.timestamp || '30 Oct 2026, 08:02 AM IST'}
          </span>

          {/* Live Indicator */}
          <span className="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />
            LIVE
          </span>

          {/* Manual Refresh */}
          <button
            onClick={loadData}
            title="Refresh Intelligence Data"
            className="p-1.5 rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-[var(--accent-blue)]' : ''}`} />
          </button>
        </div>
      </div>

      {/* 2. REAL-TIME NEWS SENTIMENT CATALYST STRIP */}
      {data.newsSentiment && (
        <div className="rounded-xl border border-[var(--accent-blue)]/20 bg-[var(--accent-blue)]/5 p-4 flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 flex items-center justify-center shrink-0">
              <Newspaper className="w-4 h-4 text-[var(--accent-blue)] dark:text-[var(--accent-blue)]" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-[var(--text-primary)]">LIVE NEWS SENTIMENT CATALYST</span>
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] dark:text-[var(--accent-blue)] border border-[var(--accent-blue)]/20">
                  {data.newsSentiment.overallSentiment} ({data.newsSentiment.sentimentRating}/10)
                </span>
                <span className="text-[11px] text-[var(--text-muted)] hidden sm:inline">
                  • {data.newsSentiment.totalArticles} Articles Analyzed (Moneycontrol, Economic Times, Livemint)
                </span>
              </div>
              <p className="text-[11px] text-[var(--text-secondary)] mt-0.5 line-clamp-1">
                {data.newsSentiment.ratingExplanation}
              </p>
            </div>
          </div>

          {/* Key affected sectors */}
          <div className="flex items-center gap-1.5 flex-wrap shrink-0">
            <span className="text-[10px] text-[var(--text-muted)] uppercase font-semibold">Active Sectors:</span>
            {data.newsSentiment.affectedKeySectors?.slice(0, 4).map((sec, i) => (
              <span
                key={i}
                className="px-2 py-0.5 rounded text-[10px] bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[var(--text-secondary)] font-medium shadow-2xs"
              >
                {sec}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 3. MAIN 3-COLUMN DASHBOARD GRID */}
      <div className="grid grid-cols-12 gap-4">
        {/* LEFT COLUMN: Market Health, Status, F&G, VIX */}
        <div className="col-span-12 lg:col-span-3 space-y-3.5">
          {/* 1. MARKET HEALTH DIAL */}
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-xs">
            <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">
              <BarChart3 className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
              <span>MARKET HEALTH</span>
            </div>

            <div className="flex flex-col items-center justify-center py-2">
              <div className="relative w-28 h-28 flex items-center justify-center">
                <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
                  <circle
                    cx="50"
                    cy="50"
                    r="40"
                    fill="transparent"
                    stroke="currentColor"
                    className="text-[var(--text-primary)] dark:text-[var(--text-primary)]"
                    strokeWidth="8"
                  />
                  <circle
                    cx="50"
                    cy="50"
                    r="40"
                    fill="transparent"
                    stroke="#10b981"
                    strokeWidth="8"
                    strokeLinecap="round"
                    strokeDasharray={2 * Math.PI * 40}
                    strokeDashoffset={2 * Math.PI * 40 * (1 - (data.marketHealth?.score || 93) / 100)}
                    className="transition-all duration-1000 ease-out"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                  <span className="text-2xl font-semibold text-[var(--text-primary)] tracking-tight">
                    {data.marketHealth?.score || 93}%
                  </span>
                </div>
              </div>
              <span className="text-[11px] text-[var(--text-muted)] font-medium mt-1">
                {data.marketHealth?.label || 'Overall Signal Strength'}
              </span>
            </div>
          </div>

          {/* 2. MARKET STATUS BARS (NEWS & BREADTH DRIVEN) */}
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-xs">
            <div className="flex items-center justify-between text-xs mb-3">
              <div className="flex items-center gap-1.5 font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                <Crosshair className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
                <span>MARKET STATUS</span>
              </div>
              <span className="text-[10px] text-[var(--accent-blue)] dark:text-[var(--accent-blue)] font-semibold">News Driven</span>
            </div>

            <div className="space-y-2.5 text-xs">
              {/* Bullish */}
              <div className="flex items-center justify-between gap-3">
                <span className="w-14 text-[var(--text-secondary)] font-medium">Bullish</span>
                <div className="flex-1 h-2.5 bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 rounded-full transition-all duration-500"
                    style={{ width: `${data.marketStatus?.bullish || 53}%` }}
                  />
                </div>
                <span className="w-9 text-right text-emerald-600 dark:text-emerald-400 font-semibold">
                  {data.marketStatus?.bullish || 53}%
                </span>
              </div>

              {/* Bearish */}
              <div className="flex items-center justify-between gap-3">
                <span className="w-14 text-[var(--text-secondary)] font-medium">Bearish</span>
                <div className="flex-1 h-2.5 bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-rose-500 rounded-full transition-all duration-500"
                    style={{ width: `${data.marketStatus?.bearish || 34}%` }}
                  />
                </div>
                <span className="w-9 text-right text-rose-600 dark:text-rose-400 font-semibold">
                  {data.marketStatus?.bearish || 34}%
                </span>
              </div>

              {/* Neutral */}
              <div className="flex items-center justify-between gap-3">
                <span className="w-14 text-[var(--text-secondary)] font-medium">Neutral</span>
                <div className="flex-1 h-2.5 bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] rounded-full transition-all duration-500"
                    style={{ width: `${data.marketStatus?.neutral || 13}%` }}
                  />
                </div>
                <span className="w-9 text-right text-[var(--text-muted)] font-semibold">
                  {data.marketStatus?.neutral || 13}%
                </span>
              </div>
            </div>
          </div>

          {/* 3. F&G INDEX */}
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-3.5 shadow-xs">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                <TrendingUp className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
                <span>F&G INDEX</span>
              </div>
              <Info className="w-3.5 h-3.5 text-[var(--text-muted)]" />
            </div>

            <div className="mt-2 flex items-baseline justify-between">
              <span className="text-2xl font-semibold text-[var(--text-primary)]">
                {Number(data.fgIndex?.value || 0.8).toFixed(2)}
              </span>
              <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
                <span className="w-2 h-2 rounded-full bg-[var(--accent-blue)]" />
                <span>
                  Prev: {Number(data.fgIndex?.prevValue || 0.79).toFixed(2)} (
                  <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
                    +{data.fgIndex?.changePercent || 1.3}%
                  </span>
                  )
                </span>
              </div>
            </div>
          </div>

          {/* 4. VIX */}
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-3.5 shadow-xs">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                <Anchor className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
                <span>INDIA VIX</span>
              </div>
            </div>

            <div className="mt-2 flex items-center justify-between">
              <div>
                <span className="text-2xl font-semibold text-[var(--text-primary)]">
                  {Number(data.vix?.value || 21.6).toFixed(1)}
                </span>
                <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
                  Prev: {Number(data.vix?.prevValue || 21.1).toFixed(1)} (
                  <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
                    +{data.vix?.changePercent || 2.4}%
                  </span>
                  )
                </p>
              </div>
              <div className="w-24">
                <SeniorSparkline
                  data={data.vix?.sparkline || [20.8, 20.9, 21.0, 21.2, 21.4, 21.3, 21.6]}
                  color="green"
                  height={32}
                />
              </div>
            </div>
          </div>

          {/* 5. Institutional Sentiment Balance Indicator */}
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] p-3 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-emerald-600 dark:text-emerald-400">🐂 BULLISH</span>
              <span className="text-[var(--text-muted)] font-semibold text-[10px]">VS</span>
              <span className="font-semibold text-rose-600 dark:text-rose-400">🐻 BEARISH</span>
            </div>
            <span className="text-[10px] text-[var(--text-muted)] px-2 py-0.5 rounded bg-[var(--bg-surface)] border border-[var(--border-subtle)] font-medium">
              CROSS-ASSET
            </span>
          </div>
        </div>

        {/* CENTER COLUMN: 10 ASSET CARDS GRID */}
        <div className="col-span-12 lg:col-span-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            {data.assets?.map((asset) => {
              const isBull = asset.bias === 'BULLISH';
              const isBear = asset.bias === 'BEARISH';
              const isNeut = asset.bias === 'NEUTRAL';

              const badgeStyle = isBull
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-400 dark:border-emerald-800'
                : isBear
                  ? 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-800'
                  : 'bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border-[var(--border-subtle)] dark:bg-[var(--bg-surface-elevated)] dark:text-[var(--text-secondary)] dark:border-[var(--border-subtle)]';

              const sparklineColor = isBull ? 'green' : isBear ? 'red' : 'blue';

              return (
                <div
                  key={asset.id || asset.symbol}
                  onClick={() => setSelectedAsset(asset)}
                  className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:border-[var(--border-subtle)] dark:hover:border-[var(--border-subtle)] p-3.5 transition-all shadow-xs hover:shadow-sm cursor-pointer relative overflow-hidden group flex flex-col justify-between"
                >
                  <div>
                    {/* Header: Icon + Name */}
                    <div className="flex items-center justify-between text-xs mb-1.5">
                      <div className="flex items-center gap-1.5 font-semibold text-[var(--text-primary)]">
                        <BarChart3 className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
                        <span>{asset.symbol}</span>
                      </div>
                      <span className="text-[10px] text-[var(--text-muted)]">
                        {asset.name}
                      </span>
                    </div>

                    {/* Price Change & Badge */}
                    <div className="mt-1 flex items-center justify-between">
                      <span
                        className={`text-2xl font-semibold tracking-tight ${isBull
                            ? 'text-emerald-600 dark:text-emerald-400'
                            : isBear
                              ? 'text-rose-600 dark:text-rose-400'
                              : 'text-[var(--text-primary)]'
                          }`}
                      >
                        {asset.changeStr || (asset.change > 0 ? `+${asset.change}` : `${asset.change}`)}
                      </span>

                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase border tracking-wider ${badgeStyle}`}
                      >
                        {asset.bias}
                      </span>
                    </div>

                    {/* Why Bullish / Bearish Rationale */}
                    {asset.rationale && (
                      <p className="mt-2 text-[11px] font-sans text-[var(--text-secondary)] line-clamp-2 leading-snug">
                        <strong className="text-[var(--text-primary)] font-semibold">Why {asset.bias}: </strong>
                        {asset.rationale}
                      </p>
                    )}

                    {/* Vector Wave Sparkline */}
                    <div className="mt-2">
                      <SeniorSparkline
                        data={asset.sparkline}
                        color={sparklineColor}
                        height={32}
                      />
                    </div>
                  </div>

                  {/* News Catalyst Headline & Source */}
                  <div className="mt-2 pt-2 border-t border-[var(--border-subtle)] space-y-1">
                    {asset.catalyst && (
                      <div className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)] truncate">
                        <Newspaper className="w-3 h-3 text-[var(--accent-blue)] shrink-0" />
                        <span className="truncate font-sans text-[var(--text-secondary)]" title={asset.catalyst.headline}>
                          {asset.catalyst.headline}
                        </span>
                      </div>
                    )}
                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-[var(--text-muted)] font-medium flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-blue)] shrink-0" />
                        Source: <strong className="text-[var(--text-secondary)] font-semibold">{asset.sources?.[0] || asset.catalyst?.source || 'NSE Data'}</strong>
                      </span>
                      <span className="text-[var(--accent-blue)] dark:text-[var(--accent-blue)] font-semibold group-hover:underline">
                        Why &rarr;
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* RIGHT COLUMN: Trend Activity & Recent Signals */}
        <div className="col-span-12 lg:col-span-3 space-y-3.5">
          {/* 1. TREND ACTIVITY CARD */}
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-xs">
            <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-4">
              <Crosshair className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
              <span>TREND ACTIVITY</span>
            </div>

            <div className="flex items-center gap-3">
              {/* Donut chart */}
              <DonutChart
                bullish={data.trendActivity?.bullish?.percent || 33}
                bearish={data.trendActivity?.bearish?.percent || 50}
                neutral={data.trendActivity?.neutral?.percent || 8}
                volatile={data.trendActivity?.volatile?.percent || 8}
              />

              {/* Legend List */}
              <div className="space-y-1.5 text-xs flex-1">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                    <span className="text-[var(--text-secondary)]">Bullish</span>
                  </div>
                  <span className="font-semibold text-[var(--text-primary)]">
                    {data.trendActivity?.bullish?.count || 4} ({data.trendActivity?.bullish?.percent || 33}%)
                  </span>
                </div>

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
                    <span className="text-[var(--text-secondary)]">Bearish</span>
                  </div>
                  <span className="font-semibold text-[var(--text-primary)]">
                    {data.trendActivity?.bearish?.count || 6} ({data.trendActivity?.bearish?.percent || 50}%)
                  </span>
                </div>

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-[var(--accent-blue)]" />
                    <span className="text-[var(--text-secondary)]">Neutral</span>
                  </div>
                  <span className="font-semibold text-[var(--text-primary)]">
                    {data.trendActivity?.neutral?.count || 1} ({data.trendActivity?.neutral?.percent || 8}%)
                  </span>
                </div>

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                    <span className="text-[var(--text-secondary)]">Volatile</span>
                  </div>
                  <span className="font-semibold text-[var(--text-primary)]">
                    {data.trendActivity?.volatile?.count || 1} ({data.trendActivity?.volatile?.percent || 8}%)
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* 2. RECENT SIGNAL CARD */}
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-xs">
            <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--accent-blue)] dark:text-[var(--accent-blue)] mb-3.5">
              <Zap className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
              <span>RECENT SIGNAL</span>
            </div>

            <div className="space-y-2 text-xs">
              {data.recentSignals?.map((sig, idx) => {
                const isBull = sig.type === 'Bullish';
                return (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]"
                  >
                    <div className="flex items-center gap-2">
                      {isBull ? (
                        <ArrowUpRight className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                      ) : (
                        <ArrowDownRight className="w-4 h-4 text-rose-600 dark:text-rose-400" />
                      )}
                      <span className="font-semibold text-[var(--text-primary)]">{sig.symbol}</span>
                    </div>

                    <div className="flex items-center gap-2">
                      <span
                        className={`tabular-nums font-semibold ${isBull
                            ? 'text-emerald-600 dark:text-emerald-400'
                            : 'text-rose-600 dark:text-rose-400'
                          }`}
                      >
                        {sig.change}
                      </span>
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${isBull
                            ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-400 dark:border-emerald-800'
                            : 'bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-800'
                          }`}
                      >
                        {sig.type}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* 4. BREAKING FINANCIAL NEWS FEED SECTION */}
      <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 sm:p-5 shadow-xs space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-[var(--border-subtle)]">
          <div className="flex items-center gap-2">
            <Newspaper className="w-4 h-4 text-[var(--accent-blue)]" />
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              Latest Financial News Feed & Catalyst Stream
            </h3>
            <span className="text-[10px] text-emerald-600 dark:text-emerald-400 flex items-center gap-1 font-semibold">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Live RSS
            </span>
          </div>

          {/* News Sentiment Filter Pills */}
          <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)] text-xs">
            {(['ALL', 'BULLISH', 'BEARISH', 'NEUTRAL'] as const).map((cat) => (
              <button
                key={cat}
                onClick={() => setNewsFilter(cat)}
                className={`px-2.5 py-1 rounded-md transition-all font-semibold text-[11px] ${newsFilter === cat
                    ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] shadow-xs'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                  }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        {/* News Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filteredNews.map((newsItem, idx) => {
            const isBull = newsItem.sentiment?.toUpperCase() === 'BULLISH';
            const isBear = newsItem.sentiment?.toUpperCase() === 'BEARISH';

            return (
              <div
                key={newsItem.id || idx}
                className="p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] hover:border-[var(--border-subtle)] dark:hover:border-[var(--border-subtle)] transition-all flex flex-col justify-between space-y-2 text-xs"
              >
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[var(--text-secondary)]">
                      {newsItem.source}
                    </span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${isBull
                          ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-400 dark:border-emerald-800'
                          : isBear
                            ? 'bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-800'
                            : 'bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)] dark:bg-[var(--bg-surface-elevated)] dark:text-[var(--text-secondary)] dark:border-[var(--border-subtle)]'
                        }`}
                    >
                      {newsItem.sentiment}
                    </span>
                  </div>

                  <h4 className="font-sans font-medium text-[var(--text-primary)] line-clamp-2 leading-snug">
                    {newsItem.headline}
                  </h4>
                </div>

                <div className="flex items-center justify-between pt-1 border-t border-[var(--border-subtle)] text-[10px] text-[var(--text-muted)]">
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3 text-[var(--text-secondary)]" />
                    {newsItem.publishedAt || 'Recent'}
                  </span>
                  {newsItem.url && (
                    <a
                      href={newsItem.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[var(--accent-blue)] dark:text-[var(--accent-blue)] hover:underline flex items-center gap-0.5 font-semibold"
                    >
                      Read Story <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 5. BOTTOM HIGHLIGHTS STATUS RIBBON */}
      <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3 flex flex-wrap items-center justify-between gap-4 text-xs shadow-xs">
        <div className="flex items-center gap-2 text-[var(--accent-blue)] dark:text-[var(--accent-blue)] font-semibold">
          <Crosshair className="w-4 h-4" />
          <span>Key Highlights</span>
        </div>

        <div className="hidden sm:block text-[var(--border-strong)]">|</div>

        {/* Top Gainer */}
        <div className="flex items-center gap-1.5 text-[var(--text-secondary)]">
          <ArrowUpRight className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
          <span>Top Gainer:</span>
          <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
            {data.keyHighlights?.topGainer?.symbol || 'SENSEX'} (
            {data.keyHighlights?.topGainer?.change || '+3.4'})
          </span>
        </div>

        <div className="hidden sm:block text-[var(--border-strong)]">|</div>

        {/* Top Loser */}
        <div className="flex items-center gap-1.5 text-[var(--text-secondary)]">
          <ArrowDownRight className="w-4 h-4 text-rose-600 dark:text-rose-400" />
          <span>Top Loser:</span>
          <span className="text-rose-600 dark:text-rose-400 font-semibold">
            {data.keyHighlights?.topLoser?.symbol || 'SILVER'} (
            {data.keyHighlights?.topLoser?.change || '-4.5'})
          </span>
        </div>

        <div className="hidden sm:block text-[var(--border-strong)]">|</div>

        {/* Market Bias */}
        <div className="flex items-center gap-2">
          <span className="text-[var(--text-muted)]">Market Bias:</span>
          <span className="px-2.5 py-0.5 rounded text-[11px] bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-800 font-semibold uppercase">
            {data.keyHighlights?.marketBias || 'BEARISH'}
          </span>
        </div>
      </div>

      {/* 6. MODAL DRAWER FOR SELECTED ASSET */}
      {selectedAsset && (
        <div
          onClick={() => setSelectedAsset(null)}
          className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-lg max-h-[90vh] overflow-y-auto bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-2xl p-5 sm:p-6 shadow-xl space-y-4"
          >
            <div className="flex items-center justify-between border-b border-[var(--border-subtle)] pb-3">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-[var(--accent-blue)]" />
                <h3 className="text-lg font-semibold text-[var(--text-primary)]">{selectedAsset.symbol}</h3>
                <span className="text-xs text-[var(--text-muted)]">({selectedAsset.name})</span>
              </div>
              <span
                className={`px-2.5 py-0.5 rounded text-xs font-semibold uppercase border ${selectedAsset.bias === 'BULLISH'
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-400 dark:border-emerald-800'
                    : selectedAsset.bias === 'BEARISH'
                      ? 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-800'
                      : 'bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border-[var(--border-subtle)] dark:bg-[var(--bg-surface-elevated)] dark:text-[var(--text-secondary)] dark:border-[var(--border-subtle)]'
                  }`}
              >
                {selectedAsset.bias}
              </span>
            </div>

            {/* Quick Metrics */}
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="bg-[var(--bg-surface-elevated)] p-3 rounded-lg border border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)] block">Day Trajectory</span>
                <span
                  className={`text-xl font-semibold mt-1 block ${selectedAsset.bias === 'BULLISH'
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : selectedAsset.bias === 'BEARISH'
                        ? 'text-rose-600 dark:text-rose-400'
                        : 'text-[var(--text-primary)]'
                    }`}
                >
                  {selectedAsset.changeStr}
                </span>
              </div>
              <div className="bg-[var(--bg-surface-elevated)] p-3 rounded-lg border border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)] block">Signal Intensity</span>
                <span className="text-xl font-semibold mt-1 block text-[var(--accent-blue)] dark:text-[var(--accent-blue)]">
                  {Math.min(98, Math.round(Math.abs(selectedAsset.change) * 25))}%
                </span>
              </div>
            </div>

            {/* Detailed Analytical Rationale: Why Bullish / Bearish */}
            {selectedAsset.rationale && (
              <div className="bg-[var(--bg-surface-elevated)] p-3.5 rounded-xl border border-[var(--border-subtle)] space-y-1.5">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-primary)]">
                  <Sparkles className="w-3.5 h-3.5 text-amber-500" />
                  <span>Why {selectedAsset.symbol} is {selectedAsset.bias}:</span>
                </div>
                <p className="font-sans text-xs text-[var(--text-secondary)] leading-relaxed">
                  {selectedAsset.rationale}
                </p>
              </div>
            )}

            {/* Key Evidentiary Drivers */}
            {selectedAsset.drivers && selectedAsset.drivers.length > 0 && (
              <div className="space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Key Evidentiary Drivers:
                </span>
                <div className="space-y-1">
                  {selectedAsset.drivers.map((drv, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-2 p-2 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[11px] font-sans"
                    >
                      <span className="text-[var(--accent-blue)] font-semibold mt-0.5">•</span>
                      <span className="text-[var(--text-secondary)]">{drv}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* News Catalyst with Direct Article Link */}
            {selectedAsset.catalyst && (
              <div className="bg-[var(--bg-surface-elevated)] p-3 rounded-xl border border-[var(--border-subtle)] space-y-2">
                <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)]">
                  <span className="font-semibold uppercase flex items-center gap-1 text-[var(--accent-blue)] dark:text-[var(--accent-blue)]">
                    <Newspaper className="w-3 h-3" /> News Driver
                  </span>
                  <span className="font-semibold text-[var(--text-secondary)]">
                    {selectedAsset.catalyst.source} • {selectedAsset.catalyst.publishedAt}
                  </span>
                </div>
                <p className="font-sans text-xs text-[var(--text-primary)] font-medium leading-relaxed">
                  {selectedAsset.catalyst.headline}
                </p>
                {selectedAsset.catalyst.url && (
                  <a
                    href={selectedAsset.catalyst.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-[11px] text-[var(--accent-blue)] dark:text-[var(--accent-blue)] hover:underline font-semibold"
                  >
                    Read Source Article on {selectedAsset.catalyst.source} <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
            )}

            {/* Verified Sources Cited */}
            {selectedAsset.sources && selectedAsset.sources.length > 0 && (
              <div className="space-y-1 pt-1">
                <span className="text-[10px] text-[var(--text-muted)] uppercase font-semibold block">
                  Verified Data & News Sources:
                </span>
                <div className="flex flex-wrap items-center gap-1.5">
                  {selectedAsset.sources.map((src, i) => (
                    <span
                      key={i}
                      className="px-2 py-0.5 rounded text-[10px] bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] font-medium"
                    >
                      {src}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Intraday Trajectory */}
            <div>
              <span className="text-xs text-[var(--text-muted)] mb-2 block font-medium">Intraday Trajectory</span>
              <div className="bg-[var(--bg-surface-elevated)] p-3 rounded-xl border border-[var(--border-subtle)]">
                <SeniorSparkline
                  data={selectedAsset.sparkline}
                  color={
                    selectedAsset.bias === 'BULLISH'
                      ? 'green'
                      : selectedAsset.bias === 'BEARISH'
                        ? 'red'
                        : 'blue'
                  }
                  height={56}
                />
              </div>
            </div>

            <button
              onClick={() => setSelectedAsset(null)}
              className="w-full py-2.5 rounded-lg bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)] text-[var(--accent-on)] font-semibold text-xs transition-colors shadow-sm"
            >
              Close Details
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export const MarketSentimentRadar = GodsEyeObserver;
