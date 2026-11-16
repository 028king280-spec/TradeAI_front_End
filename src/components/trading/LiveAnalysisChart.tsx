'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { ResponsiveContainer, ComposedChart, Line, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine, ReferenceArea } from 'recharts';
import { motion } from 'framer-motion';
import { Activity, ArrowUpRight, ArrowDownRight, Radio, Wifi, WifiOff, TrendingUp, TrendingDown, Zap, BarChart3, Clock, Signal, CircleDot } from 'lucide-react';
import { useLiveTick, useLiveCandles } from '@/hooks/useLiveMarket';
import { optionsService } from '@/services/optionsService';

interface LiveChartProps {
  symbol: string;
  currentPrice?: number;
  supportLevel?: number;
  resistanceLevel?: number;
}

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '1d'];

// Compute simple EMA
function computeEMA(data: number[], period: number): number[] {
  const k = 2 / (period + 1);
  const ema: number[] = [];
  for (let i = 0; i < data.length; i++) {
    if (i === 0) {
      ema.push(data[0]);
    } else {
      ema.push(data[i] * k + ema[i - 1] * (1 - k));
    }
  }
  return ema;
}

// Compute RSI
function computeRSI(closes: number[], period: number = 14): number | null {
  if (closes.length < period + 1) return null;
  let gains = 0;
  let losses = 0;
  for (let i = closes.length - period; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff > 0) gains += diff;
    else losses -= diff;
  }
  if (losses === 0) return 100;
  const rs = gains / losses;
  return Math.round(100 - 100 / (1 + rs));
}

export const LiveAnalysisChart: React.FC<LiveChartProps> = ({
  symbol,
  currentPrice,
  supportLevel,
  resistanceLevel,
}) => {
  const [timeframe, setTimeframe] = useState<string>('15m');
  const [historicalCandles, setHistoricalCandles] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [showVwap, setShowVwap] = useState<boolean>(true);
  const [showEma, setShowEma] = useState<boolean>(true);
  const [showVolume, setShowVolume] = useState<boolean>(true);
  const [showSmc, setShowSmc] = useState<boolean>(true);
  const [smcOverlay, setSmcOverlay] = useState<any>(null);

  // Live data hooks
  const { tick, connected } = useLiveTick(symbol);
  const { candles: liveCandles, currentCandle } = useLiveCandles(
    symbol,
    timeframe === '1m' ? 60000 : timeframe === '5m' ? 300000 : 900000,
  );

  // Live price tracking
  const livePrice = tick?.ltp || currentPrice || 0;
  const liveChange = tick?.change || 0;
  const liveChangePct = tick?.changePercent || 0;
  const isUp = liveChange >= 0;

  // Load historical candles (static) on mount and timeframe change
  useEffect(() => {
    let isCancelled = false;
    async function loadCandles() {
      setLoading(true);
      const res = await optionsService.getCandles(symbol, timeframe);
      if (!isCancelled && res) {
        if (res.candles) setHistoricalCandles(res.candles);
        if (res.smcOverlay) setSmcOverlay(res.smcOverlay);
      }
      setLoading(false);
    }
    loadCandles();
    return () => {
      isCancelled = true;
    };
  }, [symbol, timeframe]);

  // Merge historical + live candles
  const mergedCandles = useMemo(() => {
    const base = [...historicalCandles];

    // Append live candles that were built from the tick stream
    for (const lc of liveCandles) {
      const exists = base.find((c) => c.time === lc.time);
      if (!exists) {
        base.push(lc);
      }
    }

    // Update the last candle with current live data
    if (currentCandle && base.length > 0) {
      const last = base[base.length - 1];
      last.high = Math.max(last.high || 0, currentCandle.high);
      last.low = Math.min(last.low || Infinity, currentCandle.low);
      last.close = currentCandle.close;
      last.volume = currentCandle.volume || last.volume;
    }

    // Compute EMA overlays
    const closes = base.map((c) => c.close).filter(Boolean);
    if (closes.length >= 20) {
      const ema20 = computeEMA(closes, 20);
      const ema50 = computeEMA(closes, Math.min(50, closes.length));
      base.forEach((c, i) => {
        c.ema20 = ema20[i] ? Math.round(ema20[i] * 100) / 100 : undefined;
        c.ema50 = ema50[i] ? Math.round(ema50[i] * 100) / 100 : undefined;
      });
    }

    return base;
  }, [historicalCandles, liveCandles, currentCandle]);

  // Compute domain
  const prices = mergedCandles
    .flatMap((c) => [c.low, c.high])
    .filter((p) => typeof p === 'number' && !isNaN(p));
  const minPrice = prices.length ? Math.floor(Math.min(...prices) * 0.998) : livePrice * 0.99;
  const maxPrice = prices.length ? Math.ceil(Math.max(...prices) * 1.002) : livePrice * 1.01;

  // Live analysis indicators
  const closes = mergedCandles.map((c) => c.close).filter(Boolean);
  const rsi = computeRSI(closes);
  const lastVwap = mergedCandles.length > 0 ? mergedCandles[mergedCandles.length - 1]?.vwap : null;
  const priceAboveVwap = lastVwap ? livePrice > lastVwap : null;

  // Custom Candlestick shape
  const CandlestickBar = (props: any) => {
    const { x, y, width, height, payload } = props;
    if (!payload) return null;
    const { open, close, high, low } = payload;
    const isBullish = close >= open;
    const color = isBullish ? '#10b981' : '#ef4444';

    const range = maxPrice - minPrice;
    if (range <= 0) return null;

    const chartHeight = 300;
    const getY = (val: number) => chartHeight - ((val - minPrice) / range) * chartHeight;

    const openY = getY(open);
    const closeY = getY(close);
    const highY = getY(high);
    const lowY = getY(low);

    const bodyTop = Math.min(openY, closeY);
    const bodyHeight = Math.max(2, Math.abs(closeY - openY));
    const centerX = x + width / 2;
    const bodyWidth = Math.max(3, width * 0.65);

    return (
      <g>
        <line
          x1={centerX}
          y1={highY}
          x2={centerX}
          y2={lowY}
          stroke={color}
          strokeWidth={1.2}
          strokeOpacity={0.8}
        />
        <rect
          x={centerX - bodyWidth / 2}
          y={bodyTop}
          width={bodyWidth}
          height={bodyHeight}
          fill={isBullish ? '#10b981' : '#ef4444'}
          stroke={color}
          strokeWidth={1}
          rx={1}
        />
      </g>
    );
  };

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-sm overflow-hidden">
      {/* ═══ LIVE HEADER BAR ═══ */}
      <div className="px-4 sm:px-5 pt-4 sm:pt-5 pb-3 space-y-3">
        {/* Top Row: Symbol + Live Status */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="relative">
              <div
                className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                  connected
                    ? 'bg-emerald-500/15 border border-emerald-500/30'
                    : 'bg-amber-500/15 border border-amber-500/30'
                }`}
              >
                <Activity className={`w-4.5 h-4.5 ${connected ? 'text-emerald-500' : 'text-amber-500'}`} />
              </div>
              {connected && (
                <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse border-2 border-[var(--bg-surface)]" />
              )}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-[var(--text-primary)] tabular-nums">{symbol}</h2>
                <motion.span
                  key={livePrice}
                  initial={{ scale: 1.15, opacity: 0.7 }}
                  animate={{ scale: 1, opacity: 1 }}
                  className={`text-lg font-semibold tabular-nums tabular-nums ${
                    isUp ? 'text-emerald-500' : 'text-rose-500'
                  }`}
                >
                  ₹{livePrice.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                </motion.span>
              </div>
              <div className="flex items-center gap-2 text-xs tabular-nums">
                <span
                  className={`flex items-center gap-0.5 font-semibold ${
                    isUp ? 'text-emerald-500' : 'text-rose-500'
                  }`}
                >
                  {isUp ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />}
                  {isUp ? '+' : ''}
                  {liveChange.toFixed(2)} ({isUp ? '+' : ''}
                  {liveChangePct.toFixed(2)}%)
                </span>
                <span className="text-[var(--text-muted)]">•</span>
                <span className={`flex items-center gap-1 ${connected ? 'text-emerald-500' : 'text-amber-500'}`}>
                  {connected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
                  {connected ? 'LIVE' : 'RECONNECTING'}
                </span>
              </div>
            </div>
          </div>

          {/* Timeframe & Toggle Controls */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)]">
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  onClick={() => setTimeframe(tf)}
                  className={`px-2.5 py-1 text-xs tabular-nums font-medium rounded-md transition-all ${
                    timeframe === tf
                      ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] shadow-sm'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>

            <div className="flex gap-1">
              <button
                onClick={() => setShowVwap(!showVwap)}
                className={`px-2 py-1 text-[11px] tabular-nums rounded-md border transition-all ${
                  showVwap
                    ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30'
                    : 'bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] border-[var(--border-subtle)]'
                }`}
              >
                VWAP
              </button>
              <button
                onClick={() => setShowEma(!showEma)}
                className={`px-2 py-1 text-[11px] tabular-nums rounded-md border transition-all ${
                  showEma
                    ? 'bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] dark:text-[var(--accent-blue)] border-[var(--accent-blue)]/30'
                    : 'bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] border-[var(--border-subtle)]'
                }`}
              >
                EMA
              </button>
              <button
                onClick={() => setShowVolume(!showVolume)}
                className={`px-2 py-1 text-[11px] tabular-nums rounded-md border transition-all ${
                  showVolume
                    ? 'bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] dark:text-[var(--accent-blue)] border-[var(--accent-blue)]/30'
                    : 'bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] border-[var(--border-subtle)]'
                }`}
              >
                VOL
              </button>
              <button
                onClick={() => setShowSmc(!showSmc)}
                className={`px-2 py-1 text-[11px] tabular-nums rounded-md border transition-all ${
                  showSmc
                    ? 'bg-purple-500/15 text-purple-600 dark:text-purple-400 border-purple-500/30 font-semibold'
                    : 'bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] border-[var(--border-subtle)]'
                }`}
              >
                SMC Zones
              </button>
            </div>
          </div>
        </div>

        {/* ═══ LIVE ANALYSIS STRIP ═══ */}
        <div className="flex flex-wrap gap-2">
          {/* RSI Badge */}
          {rsi !== null && (
            <div
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] tabular-nums font-medium border ${
                rsi > 70
                  ? 'bg-rose-500/10 text-rose-500 border-rose-500/20'
                  : rsi < 30
                    ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                    : 'bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border-[var(--border-subtle)]'
              }`}
            >
              <Signal className="w-3 h-3" />
              RSI: {rsi}
              <span className="text-[9px] opacity-75">
                {rsi > 70 ? '(Overbought)' : rsi < 30 ? '(Oversold)' : '(Neutral)'}
              </span>
            </div>
          )}

          {/* VWAP Position */}
          {lastVwap && priceAboveVwap !== null && (
            <div
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] tabular-nums font-medium border ${
                priceAboveVwap
                  ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                  : 'bg-rose-500/10 text-rose-500 border-rose-500/20'
              }`}
            >
              {priceAboveVwap ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
              {priceAboveVwap ? 'Above VWAP' : 'Below VWAP'}
              <span className="text-[9px] opacity-75">₹{lastVwap.toLocaleString('en-IN')}</span>
            </div>
          )}

          {/* Day Range Position */}
          {tick?.high && tick?.low && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] tabular-nums font-medium bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)]">
              <BarChart3 className="w-3 h-3" />
              Range: ₹{tick.low.toLocaleString('en-IN')} — ₹{tick.high.toLocaleString('en-IN')}
            </div>
          )}

          {/* Volume */}
          {tick?.volume && tick.volume > 0 && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] tabular-nums font-medium bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)]">
              <Zap className="w-3 h-3" />
              Vol: {(tick.volume / 100000).toFixed(2)}L
            </div>
          )}

          {/* Feed Status */}
          <div
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] tabular-nums font-medium border ${
              tick?.dataStatus === 'LIVE'
                ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                : 'bg-amber-500/10 text-amber-500 border-amber-500/20'
            }`}
          >
            <CircleDot className="w-3 h-3" />
            {tick?.dataStatus || 'WAITING'}
            {tick?.provider && <span className="text-[9px] opacity-75">({tick.provider})</span>}
          </div>
        </div>
      </div>

      {/* ═══ CANDLESTICK CHART AREA ═══ */}
      <div className="w-full h-[360px] relative px-2">
        {loading && (
          <div className="absolute inset-0 z-10 bg-[var(--bg-surface)]/80 backdrop-blur-xs flex items-center justify-center">
            <div className="flex flex-col items-center gap-2">
              <div className="w-6 h-6 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
              <span className="text-xs tabular-nums text-[var(--text-muted)]">Loading {timeframe} candles...</span>
            </div>
          </div>
        )}

        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={mergedCandles} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
            <defs>
              <linearGradient id="volumeGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="rgba(59, 130, 246, 0.25)" />
                <stop offset="100%" stopColor="rgba(59, 130, 246, 0.02)" />
              </linearGradient>
            </defs>

            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" opacity={0.4} />
            <XAxis
              dataKey="time"
              stroke="var(--text-muted)"
              fontSize={10}
              tickLine={false}
              axisLine={{ stroke: 'var(--border-subtle)' }}
            />
            <YAxis
              yAxisId="price"
              domain={[minPrice, maxPrice]}
              orientation="right"
              stroke="var(--text-muted)"
              fontSize={10}
              tickLine={false}
              axisLine={{ stroke: 'var(--border-subtle)' }}
              tickFormatter={(v) => v.toLocaleString('en-IN')}
            />
            <YAxis yAxisId="vol" domain={[0, 'dataMax * 4']} hide={true} />

            <Tooltip
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  const d = payload[0].payload;
                  const isBullish = d.close >= d.open;
                  return (
                    <div className="p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] shadow-xl tabular-nums text-xs space-y-1 backdrop-blur-sm">
                      <div className="text-[var(--text-muted)] text-[10px] pb-1 border-b border-[var(--border-subtle)] flex items-center gap-1.5">
                        <Radio className="w-3 h-3 text-emerald-500" />
                        {symbol} • {d.time} IST
                      </div>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 pt-1">
                        <span className="text-[var(--text-muted)]">Open:</span>
                        <span className="font-semibold text-right">{d.open?.toLocaleString('en-IN')}</span>
                        <span className="text-[var(--text-muted)]">High:</span>
                        <span className="font-semibold text-emerald-500 text-right">
                          {d.high?.toLocaleString('en-IN')}
                        </span>
                        <span className="text-[var(--text-muted)]">Low:</span>
                        <span className="font-semibold text-rose-500 text-right">
                          {d.low?.toLocaleString('en-IN')}
                        </span>
                        <span className="text-[var(--text-muted)]">Close:</span>
                        <span
                          className={`font-semibold text-right ${isBullish ? 'text-emerald-500' : 'text-rose-500'}`}
                        >
                          {d.close?.toLocaleString('en-IN')}
                        </span>
                        <span className="text-[var(--text-muted)]">Volume:</span>
                        <span className="text-right">{d.volume?.toLocaleString('en-IN')}</span>
                        {d.vwap && (
                          <>
                            <span className="text-amber-500">VWAP:</span>
                            <span className="text-right text-amber-500">{d.vwap?.toLocaleString('en-IN')}</span>
                          </>
                        )}
                        {d.ema20 && (
                          <>
                            <span className="text-[var(--accent-blue)]">EMA 20:</span>
                            <span className="text-right text-[var(--accent-blue)]">
                              {d.ema20?.toLocaleString('en-IN')}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                  );
                }
                return null;
              }}
            />

            {/* Support & Resistance Overlays */}
            {resistanceLevel && (
              <ReferenceLine
                yAxisId="price"
                y={resistanceLevel}
                stroke="#ef4444"
                strokeDasharray="4 4"
                label={{
                  value: `R: ₹${resistanceLevel.toLocaleString('en-IN')}`,
                  fill: '#ef4444',
                  fontSize: 10,
                  position: 'insideTopRight',
                }}
              />
            )}
            {supportLevel && (
              <ReferenceLine
                yAxisId="price"
                y={supportLevel}
                stroke="#10b981"
                strokeDasharray="4 4"
                label={{
                  value: `S: ₹${supportLevel.toLocaleString('en-IN')}`,
                  fill: '#10b981',
                  fontSize: 10,
                  position: 'insideBottomRight',
                }}
              />
            )}

            {/* Live Price Line */}
            {livePrice > 0 && (
              <ReferenceLine
                yAxisId="price"
                y={livePrice}
                stroke={isUp ? '#10b981' : '#ef4444'}
                strokeDasharray="2 2"
                strokeWidth={1.5}
                label={{
                  value: `LTP ₹${livePrice.toLocaleString('en-IN')}`,
                  fill: isUp ? '#10b981' : '#ef4444',
                  fontSize: 10,
                  position: 'insideTopLeft',
                }}
              />
            )}

            {/* SMC Institutional Overlays */}
            {showSmc && smcOverlay && (
              <>
                {/* Bullish Order Blocks (Demand Floor) */}
                {smcOverlay.orderBlocks?.filter((b: any) => b.bias === 'BULLISH').slice(0, 2).map((ob: any, i: number) => (
                  <ReferenceArea
                    key={`ob-bull-${i}`}
                    yAxisId="price"
                    y1={ob.bottom}
                    y2={ob.top}
                    fill="rgba(16, 185, 129, 0.15)"
                    stroke="rgba(16, 185, 129, 0.5)"
                    strokeDasharray="3 3"
                    label={{ value: `Bullish OB [₹${ob.bottom}-₹${ob.top}]`, fill: '#10b981', fontSize: 9, position: 'insideTopLeft' }}
                  />
                ))}

                {/* Bearish Order Blocks (Supply Ceiling) */}
                {smcOverlay.orderBlocks?.filter((b: any) => b.bias === 'BEARISH').slice(0, 2).map((ob: any, i: number) => (
                  <ReferenceArea
                    key={`ob-bear-${i}`}
                    yAxisId="price"
                    y1={ob.bottom}
                    y2={ob.top}
                    fill="rgba(244, 63, 94, 0.15)"
                    stroke="rgba(244, 63, 94, 0.5)"
                    strokeDasharray="3 3"
                    label={{ value: `Bearish OB [₹${ob.bottom}-₹${ob.top}]`, fill: '#f43f5e', fontSize: 9, position: 'insideBottomLeft' }}
                  />
                ))}

                {/* Fair Value Gaps (FVG) */}
                {smcOverlay.fairValueGaps?.filter((g: any) => !g.mitigated).slice(0, 2).map((fvg: any, i: number) => (
                  <ReferenceArea
                    key={`fvg-${i}`}
                    yAxisId="price"
                    y1={fvg.bottom}
                    y2={fvg.top}
                    fill={fvg.bias === 'BULLISH' ? 'rgba(59, 130, 246, 0.12)' : 'rgba(234, 88, 12, 0.12)'}
                    stroke={fvg.bias === 'BULLISH' ? '#3b82f6' : '#ea580c'}
                    strokeDasharray="2 2"
                    label={{ value: `FVG 50% CE: ₹${fvg.ce50}`, fill: fvg.bias === 'BULLISH' ? '#3b82f6' : '#ea580c', fontSize: 9, position: 'insideRight' }}
                  />
                ))}

                {/* 50% Equilibrium Line */}
                {smcOverlay.dealingRange?.equilibrium && (
                  <ReferenceLine
                    yAxisId="price"
                    y={smcOverlay.dealingRange.equilibrium}
                    stroke="#f59e0b"
                    strokeWidth={1.5}
                    strokeDasharray="4 4"
                    label={{ value: `50% Equilibrium: ₹${smcOverlay.dealingRange.equilibrium}`, fill: '#f59e0b', fontSize: 10, position: 'insideTopRight' }}
                  />
                )}

                {/* BSL & SSL Liquidity Levels */}
                {smcOverlay.liquidityPools?.bslLevels?.[0]?.level && (
                  <ReferenceLine
                    yAxisId="price"
                    y={smcOverlay.liquidityPools.bslLevels[0].level}
                    stroke="#ec4899"
                    strokeWidth={1}
                    strokeDasharray="5 5"
                    label={{ value: `BSL (PDH): ₹${smcOverlay.liquidityPools.bslLevels[0].level}`, fill: '#ec4899', fontSize: 9, position: 'insideTopLeft' }}
                  />
                )}
                {smcOverlay.liquidityPools?.sslLevels?.[0]?.level && (
                  <ReferenceLine
                    yAxisId="price"
                    y={smcOverlay.liquidityPools.sslLevels[0].level}
                    stroke="#06b6d4"
                    strokeWidth={1}
                    strokeDasharray="5 5"
                    label={{ value: `SSL (PDL): ₹${smcOverlay.liquidityPools.sslLevels[0].level}`, fill: '#06b6d4', fontSize: 9, position: 'insideBottomLeft' }}
                  />
                )}

                {/* BOS & CHoCH Structural Lines */}
                {smcOverlay.advancedIct?.structure?.bosChoch?.lastBos?.brokenLevel && (
                  <ReferenceLine
                    yAxisId="price"
                    y={smcOverlay.advancedIct.structure.bosChoch.lastBos.brokenLevel}
                    stroke={smcOverlay.advancedIct.structure.bosChoch.lastBos.type.includes('BULLISH') ? '#10b981' : '#f43f5e'}
                    strokeWidth={1.2}
                    strokeDasharray="3 3"
                    label={{
                      value: `BOS: ₹${smcOverlay.advancedIct.structure.bosChoch.lastBos.brokenLevel}`,
                      fill: smcOverlay.advancedIct.structure.bosChoch.lastBos.type.includes('BULLISH') ? '#10b981' : '#f43f5e',
                      fontSize: 9,
                      position: 'insideRight',
                    }}
                  />
                )}
                {smcOverlay.advancedIct?.structure?.bosChoch?.lastChoch?.brokenLevel && (
                  <ReferenceLine
                    yAxisId="price"
                    y={smcOverlay.advancedIct.structure.bosChoch.lastChoch.brokenLevel}
                    stroke="#a855f7"
                    strokeWidth={1.5}
                    strokeDasharray="2 2"
                    label={{
                      value: `CHoCH: ₹${smcOverlay.advancedIct.structure.bosChoch.lastChoch.brokenLevel}`,
                      fill: '#a855f7',
                      fontSize: 9,
                      position: 'insideLeft',
                    }}
                  />
                )}
              </>
            )}

            {/* Volume Bars */}
            {showVolume && (
              <Bar yAxisId="vol" dataKey="volume" fill="url(#volumeGradient)" radius={[2, 2, 0, 0]} />
            )}

            {/* Candlesticks */}
            <Bar yAxisId="price" dataKey="close" shape={<CandlestickBar />} />

            {/* VWAP Overlay */}
            {showVwap && (
              <Line yAxisId="price" type="monotone" dataKey="vwap" stroke="#f59e0b" strokeWidth={1.5} dot={false} />
            )}

            {/* EMA 20 & 50 Overlays */}
            {showEma && (
              <>
                <Line
                  yAxisId="price"
                  type="monotone"
                  dataKey="ema20"
                  stroke="#818cf8"
                  strokeWidth={1.5}
                  dot={false}
                />
                <Line
                  yAxisId="price"
                  type="monotone"
                  dataKey="ema50"
                  stroke="#c084fc"
                  strokeWidth={1.2}
                  strokeDasharray="3 3"
                  dot={false}
                />
              </>
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* ═══ FOOTER LEGEND ═══ */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 sm:px-5 py-3 text-[11px] tabular-nums text-[var(--text-muted)] border-t border-[var(--border-subtle)]">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500" /> Bullish
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-rose-500" /> Bearish
          </span>
          {showVwap && (
            <span className="flex items-center gap-1.5 text-amber-500">
              <span className="w-3 h-0.5 bg-amber-500" /> VWAP
            </span>
          )}
          {showEma && (
            <>
              <span className="flex items-center gap-1.5 text-[var(--accent-blue)]">
                <span className="w-3 h-0.5 bg-[var(--accent-blue)]" /> EMA20
              </span>
              <span className="flex items-center gap-1.5 text-purple-400">
                <span className="w-3 h-0.5 bg-purple-400 opacity-60" /> EMA50
              </span>
            </>
          )}
          {showSmc && (
            <>
              <span className="flex items-center gap-1.5 text-emerald-400">
                <span className="w-2.5 h-2.5 rounded-xs bg-emerald-500/30 border border-emerald-500" /> Bull OB
              </span>
              <span className="flex items-center gap-1.5 text-rose-400">
                <span className="w-2.5 h-2.5 rounded-xs bg-rose-500/30 border border-rose-500" /> Bear OB
              </span>
              <span className="flex items-center gap-1.5 text-[var(--accent-blue)]">
                <span className="w-2.5 h-2.5 rounded-xs bg-[var(--accent-blue)]/30 border border-[var(--accent-blue)]" /> FVG
              </span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Clock className="w-3 h-3" />
          <span>
            Live: <strong className="text-[var(--text-primary)]">₹{livePrice.toLocaleString('en-IN')}</strong>
          </span>
          <span className="text-[var(--text-muted)]">•</span>
          <span className={connected ? 'text-emerald-500' : 'text-amber-500'}>
            {connected ? '● Connected' : '○ Offline'}
          </span>
        </div>
      </div>
    </div>
  );
};
