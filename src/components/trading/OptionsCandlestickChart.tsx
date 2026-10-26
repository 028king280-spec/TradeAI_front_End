'use client';

import React, { useState, useEffect } from 'react';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from 'recharts';
import { optionsService } from '@/services/optionsService';
import { formatINR } from '@/lib/utils';
import { Activity, Clock, Layers, Sparkles, TrendingUp, TrendingDown } from 'lucide-react';

interface CandleData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap?: number;
  ema20?: number;
  ema50?: number;
}

interface OptionsCandlestickChartProps {
  symbol: string;
  currentPrice: number;
  supportLevel?: number;
  resistanceLevel?: number;
}

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '1d'];

export const OptionsCandlestickChart: React.FC<OptionsCandlestickChartProps> = ({
  symbol,
  currentPrice,
  supportLevel,
  resistanceLevel,
}) => {
  const [timeframe, setTimeframe] = useState<string>('15m');
  const [candles, setCandles] = useState<CandleData[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [showVwap, setShowVwap] = useState<boolean>(true);
  const [showEma, setShowEma] = useState<boolean>(true);

  useEffect(() => {
    let isCancelled = false;
    async function loadCandles() {
      setLoading(true);
      const res = await optionsService.getCandles(symbol, timeframe);
      if (!isCancelled && res && res.candles) {
        setCandles(res.candles);
      }
      setLoading(false);
    }
    loadCandles();
    return () => {
      isCancelled = true;
    };
  }, [symbol, timeframe]);

  // Compute domain
  const prices = candles.flatMap((c) => [c.low, c.high]).filter((p) => typeof p === 'number' && !isNaN(p));
  const minPrice = prices.length ? Math.floor(Math.min(...prices) * 0.998) : currentPrice * 0.99;
  const maxPrice = prices.length ? Math.ceil(Math.max(...prices) * 1.002) : currentPrice * 1.01;

  // Custom Candlestick shape for ComposedChart
  const CandlestickBar = (props: any) => {
    const { x, y, width, height, payload } = props;
    if (!payload) return null;
    const { open, close, high, low } = payload;
    const isUp = close >= open;
    const color = isUp ? '#10b981' : '#ef4444';

    // Calculate Y coordinates relative to chart scale
    // Using minPrice and maxPrice range
    const range = maxPrice - minPrice;
    if (range <= 0) return null;

    const chartHeight = 240;
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
        {/* Wick */}
        <line
          x1={centerX}
          y1={highY}
          x2={centerX}
          y2={lowY}
          stroke={color}
          strokeWidth={1.2}
          strokeOpacity={0.8}
        />
        {/* Candle Body */}
        <rect
          x={centerX - bodyWidth / 2}
          y={bodyTop}
          width={bodyWidth}
          height={bodyHeight}
          fill={isUp ? '#10b981' : '#ef4444'}
          stroke={color}
          strokeWidth={1}
          rx={1}
        />
      </g>
    );
  };

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 sm:p-5 shadow-sm space-y-4">
      {/* Header Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
            <Activity className="w-4 h-4 text-blue-500" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-[var(--text-primary)] font-mono">{symbol} Live Chart</h2>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-semibold">
                IST (09:15 - 15:30)
              </span>
            </div>
            <p className="text-xs text-[var(--text-muted)] font-mono">
              Deterministic OHLCV with VWAP, EMA 20 & EMA 50 Overlays
            </p>
          </div>
        </div>

        {/* Timeframe & Overlays */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Timeframe buttons */}
          <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)]">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-2.5 py-1 text-xs font-mono font-medium rounded-md transition-all ${
                  timeframe === tf
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>

          {/* Toggle VWAP & EMA */}
          <button
            onClick={() => setShowVwap(!showVwap)}
            className={`px-2.5 py-1 text-xs font-mono rounded-lg border transition-all ${
              showVwap
                ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30'
                : 'bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] border-[var(--border-subtle)]'
            }`}
          >
            VWAP
          </button>
          <button
            onClick={() => setShowEma(!showEma)}
            className={`px-2.5 py-1 text-xs font-mono rounded-lg border transition-all ${
              showEma
                ? 'bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 border-indigo-500/30'
                : 'bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] border-[var(--border-subtle)]'
            }`}
          >
            EMA 20/50
          </button>
        </div>
      </div>

      {/* Candlestick Area */}
      <div className="w-full h-[320px] relative">
        {loading && (
          <div className="absolute inset-0 z-10 bg-[var(--bg-surface)]/80 backdrop-blur-xs flex items-center justify-center">
            <div className="flex flex-col items-center gap-2">
              <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <span className="text-xs font-mono text-[var(--text-muted)]">Loading {timeframe} candles...</span>
            </div>
          </div>
        )}

        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={candles} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" opacity={0.5} />
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
            <YAxis
              yAxisId="vol"
              domain={[0, 'dataMax * 4']}
              hide={true}
            />

            <Tooltip
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  const d = payload[0].payload as CandleData;
                  const isUp = d.close >= d.open;
                  return (
                    <div className="p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] shadow-lg font-mono text-xs space-y-1">
                      <div className="text-[var(--text-muted)] text-[10px] pb-1 border-b border-[var(--border-subtle)]">
                        {symbol} • {d.time} IST
                      </div>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 pt-1">
                        <span className="text-[var(--text-muted)]">Open:</span>
                        <span className="font-semibold text-right">{d.open?.toLocaleString('en-IN')}</span>
                        <span className="text-[var(--text-muted)]">High:</span>
                        <span className="font-semibold text-emerald-500 text-right">{d.high?.toLocaleString('en-IN')}</span>
                        <span className="text-[var(--text-muted)]">Low:</span>
                        <span className="font-semibold text-rose-500 text-right">{d.low?.toLocaleString('en-IN')}</span>
                        <span className="text-[var(--text-muted)]">Close:</span>
                        <span className={`font-semibold text-right ${isUp ? 'text-emerald-500' : 'text-rose-500'}`}>
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
                            <span className="text-indigo-400">EMA 20:</span>
                            <span className="text-right text-indigo-400">{d.ema20?.toLocaleString('en-IN')}</span>
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
                label={{ value: `Res: ₹${resistanceLevel}`, fill: '#ef4444', fontSize: 10, position: 'insideTopRight' }}
              />
            )}
            {supportLevel && (
              <ReferenceLine
                yAxisId="price"
                y={supportLevel}
                stroke="#10b981"
                strokeDasharray="4 4"
                label={{ value: `Sup: ₹${supportLevel}`, fill: '#10b981', fontSize: 10, position: 'insideBottomRight' }}
              />
            )}

            {/* Volume Bars */}
            <Bar
              yAxisId="vol"
              dataKey="volume"
              fill="rgba(59, 130, 246, 0.2)"
              radius={[2, 2, 0, 0]}
            />

            {/* Candlesticks */}
            <Bar
              yAxisId="price"
              dataKey="close"
              shape={<CandlestickBar />}
            />

            {/* VWAP Overlay */}
            {showVwap && (
              <Line
                yAxisId="price"
                type="monotone"
                dataKey="vwap"
                stroke="#f59e0b"
                strokeWidth={1.5}
                dot={false}
              />
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

      {/* Legend & Status */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 text-[11px] font-mono text-[var(--text-muted)] border-t border-[var(--border-subtle)]">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500"></span> Bullish Candle
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-rose-500"></span> Bearish Candle
          </span>
          {showVwap && (
            <span className="flex items-center gap-1.5 text-amber-500">
              <span className="w-3 h-0.5 bg-amber-500"></span> VWAP
            </span>
          )}
          {showEma && (
            <span className="flex items-center gap-1.5 text-indigo-400">
              <span className="w-3 h-0.5 bg-indigo-400"></span> EMA 20
            </span>
          )}
        </div>
        <div>
          Current: <span className="text-[var(--text-primary)] font-bold">₹{currentPrice.toLocaleString('en-IN')}</span>
        </div>
      </div>
    </div>
  );
};
