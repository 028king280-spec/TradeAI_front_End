'use client';

import React, { useState, useEffect, useMemo, useRef } from 'react';
import { ResponsiveContainer, ComposedChart, Line, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine, ReferenceArea } from 'recharts';
import { optionsService } from '@/services/optionsService';

import { Activity, Target, Crosshair, ZoomIn, ZoomOut, RotateCcw, ChevronLeft, ChevronRight } from 'lucide-react';

interface CandleData {
  time: string;
  timestamp?: string;
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

const TIMEFRAMES = [
  { id: '5m', label: '5m' },
  { id: '15m', label: '15m' },
  { id: '30m', label: '30m' },
  { id: '1h', label: '1h' },
  { id: '1d', label: '1D' },
];

export const OptionsCandlestickChart: React.FC<OptionsCandlestickChartProps> = ({
  symbol,
  currentPrice,
  supportLevel,
  resistanceLevel,
}) => {
  // Chart Modes: 'spot' for Index or 'premium' for Option Contract
  const [chartMode, setChartMode] = useState<'spot' | 'premium'>('spot');
  const [timeframe, setTimeframe] = useState<string>('5m');
  const [allCandles, setAllCandles] = useState<CandleData[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [showVwap, setShowVwap] = useState<boolean>(true);
  const [showEma, setShowEma] = useState<boolean>(true);
  const [showSmc, setShowSmc] = useState<boolean>(true);
  const [smcOverlay, setSmcOverlay] = useState<any>(null);

  // Zoom and Pan Controls
  const [zoomLevel, setZoomLevel] = useState<number>(1); // 1 = 100% (all), 2 = 200%, 3 = 300%, 4 = 400%
  const [panOffset, setPanOffset] = useState<number>(0); // 0 = latest bars, positive = scroll left into past
  const chartContainerRef = useRef<HTMLDivElement>(null);

  // Option Contract Controls
  const [optionType, setOptionType] = useState<'CE' | 'PE'>('CE');
  const [selectedStrike, setSelectedStrike] = useState<number | null>(null);
  const [availableStrikes, setAvailableStrikes] = useState<number[]>([]);
  const [contractSymbol, setContractSymbol] = useState<string>('');
  const [greeks, setGreeks] = useState<{ delta?: number; theta?: number; iv?: number } | null>(null);

  useEffect(() => {
    let isCancelled = false;
    async function loadCandles() {
      setLoading(true);
      const res = await optionsService.getCandles(
        symbol,
        timeframe,
        chartMode,
        selectedStrike || undefined,
        optionType
      );
      if (!isCancelled && res) {
        if (res.candles) {
          setAllCandles(res.candles);
          setPanOffset(0); // reset pan on data reload
        }
        if (res.availableStrikes && res.availableStrikes.length > 0) {
          setAvailableStrikes(res.availableStrikes);
          if (!selectedStrike) {
            setSelectedStrike(res.atmStrike || res.availableStrikes[Math.floor(res.availableStrikes.length / 2)]);
          }
        }
        if (res.contractSymbol) setContractSymbol(res.contractSymbol);
        if (res.greeks) setGreeks(res.greeks);
        if (res.smcOverlay) setSmcOverlay(res.smcOverlay);
      }
      setLoading(false);
    }
    loadCandles();
    return () => {
      isCancelled = true;
    };
  }, [symbol, timeframe, chartMode, selectedStrike, optionType]);

  // Compute visible window based on zoomLevel and panOffset
  const displayedCandles = useMemo(() => {
    if (!allCandles || allCandles.length === 0) return [];
    const total = allCandles.length;
    // Visible bars: minimum 8 bars, scaled down as zoom increases
    const visibleCount = Math.max(8, Math.min(total, Math.floor(total / zoomLevel)));

    // Constrain pan offset
    const maxOffset = Math.max(0, total - visibleCount);
    const validOffset = Math.max(0, Math.min(panOffset, maxOffset));

    const endIndex = total - validOffset;
    const startIndex = Math.max(0, endIndex - visibleCount);
    return allCandles.slice(startIndex, endIndex);
  }, [allCandles, zoomLevel, panOffset]);

  // Compute dynamic domain based on displayed candles
  const prices = displayedCandles
    .flatMap((c) => [c.low, c.high])
    .filter((p) => typeof p === 'number' && !isNaN(p) && p > 0);

  const activeLtp = displayedCandles.length > 0
    ? displayedCandles[displayedCandles.length - 1].close
    : (chartMode === 'spot' ? currentPrice : 120);

  const minPrice = prices.length ? Math.floor(Math.min(...prices) * 0.985) : Math.floor(activeLtp * 0.95);
  const maxPrice = prices.length ? Math.ceil(Math.max(...prices) * 1.015) : Math.ceil(activeLtp * 1.05);

  // Zoom handlers
  const handleZoomIn = () => {
    setZoomLevel((prev) => Math.min(4, +(prev + 0.5).toFixed(1)));
  };

  const handleZoomOut = () => {
    setZoomLevel((prev) => {
      const next = Math.max(1, +(prev - 0.5).toFixed(1));
      if (next === 1) setPanOffset(0);
      return next;
    });
  };

  const handleResetZoom = () => {
    setZoomLevel(1);
    setPanOffset(0);
  };

  const handlePanLeft = () => {
    const total = allCandles.length;
    const visibleCount = Math.max(8, Math.floor(total / zoomLevel));
    const step = Math.max(2, Math.floor(visibleCount * 0.25));
    setPanOffset((prev) => Math.min(total - visibleCount, prev + step));
  };

  const handlePanRight = () => {
    const total = allCandles.length;
    const visibleCount = Math.max(8, Math.floor(total / zoomLevel));
    const step = Math.max(2, Math.floor(visibleCount * 0.25));
    setPanOffset((prev) => Math.max(0, prev - step));
  };

  // Mouse wheel zoom
  const handleWheel = (e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey || e.altKey) {
      e.preventDefault();
      if (e.deltaY < 0) {
        handleZoomIn();
      } else {
        handleZoomOut();
      }
    }
  };

  // Custom Candlestick shape
  const CandlestickBar = (props: any) => {
    const { x, width, payload } = props;
    if (!payload) return null;
    const { open, close, high, low } = payload;
    const isUp = close >= open;
    const color = isUp ? '#10b981' : '#ef4444';

    const range = maxPrice - minPrice;
    if (range <= 0) return null;

    const chartHeight = 270;
    const getY = (val: number) => chartHeight - ((val - minPrice) / range) * chartHeight;

    const openY = getY(open);
    const closeY = getY(close);
    const highY = getY(high);
    const lowY = getY(low);

    const bodyTop = Math.min(openY, closeY);
    const bodyHeight = Math.max(3, Math.abs(closeY - openY));
    const centerX = x + width / 2;
    const bodyWidth = Math.max(4, width * 0.7);

    return (
      <g>
        {/* Wick */}
        <line
          x1={centerX}
          y1={highY}
          x2={centerX}
          y2={lowY}
          stroke={color}
          strokeWidth={1.5}
          strokeOpacity={0.9}
        />
        {/* Body */}
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
    <div
      ref={chartContainerRef}
      onWheel={handleWheel}
      className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 sm:p-5 shadow-sm space-y-4"
    >
      {/* Top Header: Mode Switcher & Controls */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
        {/* Left: Mode Switcher & Strikes */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-1 border border-[var(--border-subtle)]">
            <button
              onClick={() => setChartMode('spot')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md transition-all ${
                chartMode === 'spot'
                  ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] shadow-sm'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              <Activity className="w-3.5 h-3.5" />
              <span>{symbol} Spot Index</span>
            </button>
            <button
              onClick={() => setChartMode('premium')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md transition-all ${
                chartMode === 'premium'
                  ? 'bg-amber-600 text-[var(--text-primary)] shadow-sm'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              <Target className="w-3.5 h-3.5" />
              <span>Option Premium (Strike)</span>
            </button>
          </div>

          {/* If Option Premium Mode is Active: Strike & CE/PE controls */}
          {chartMode === 'premium' && (
            <div className="flex items-center gap-2">
              {/* CE / PE Toggle */}
              <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)]">
                <button
                  onClick={() => setOptionType('CE')}
                  className={`px-2.5 py-1 text-xs font-semibold rounded-md transition-all ${
                    optionType === 'CE'
                      ? 'bg-emerald-600 text-[var(--text-primary)] shadow-xs'
                      : 'text-[var(--text-muted)] hover:text-emerald-500'
                  }`}
                >
                  CE (Call)
                </button>
                <button
                  onClick={() => setOptionType('PE')}
                  className={`px-2.5 py-1 text-xs font-semibold rounded-md transition-all ${
                    optionType === 'PE'
                      ? 'bg-rose-600 text-[var(--text-primary)] shadow-xs'
                      : 'text-[var(--text-muted)] hover:text-rose-500'
                  }`}
                >
                  PE (Put)
                </button>
              </div>

              {/* Strike Dropdown */}
              {availableStrikes.length > 0 && (
                <select
                  value={selectedStrike || ''}
                  onChange={(e) => setSelectedStrike(Number(e.target.value))}
                  className="px-2.5 py-1 text-xs tabular-nums font-semibold rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-blue)] cursor-pointer"
                >
                  {availableStrikes.map((stk) => (
                    <option key={stk} value={stk}>
                      {stk} {stk === (availableStrikes[Math.floor(availableStrikes.length / 2)]) ? '(ATM)' : ''}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
        </div>

        {/* Right: Timeframes, Indicators, and Zoom Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Timeframe Buttons */}
          <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)]">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf.id}
                onClick={() => setTimeframe(tf.id)}
                className={`px-2.5 py-1 text-xs tabular-nums font-semibold rounded-md transition-all ${
                  timeframe === tf.id
                    ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] shadow-xs'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                }`}
              >
                {tf.label}
              </button>
            ))}
          </div>

          {/* Toggle VWAP & EMA */}
          <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)]">
            <button
              onClick={() => setShowVwap(!showVwap)}
              className={`px-2 py-1 text-xs tabular-nums rounded transition-all ${
                showVwap
                  ? 'bg-amber-500/20 text-amber-600 dark:text-amber-400 font-semibold'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              VWAP
            </button>
            <button
              onClick={() => setShowEma(!showEma)}
              className={`px-2 py-1 text-xs tabular-nums rounded transition-all ${
                showEma
                  ? 'bg-[var(--accent-blue)]/20 text-[var(--accent-blue)] dark:text-[var(--accent-blue)] font-semibold'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              EMA
            </button>
            <button
              onClick={() => setShowSmc(!showSmc)}
              className={`px-2 py-1 text-xs tabular-nums rounded transition-all flex items-center gap-1 ${
                showSmc
                  ? 'bg-[var(--accent-blue)]/20 text-[var(--accent-blue)] dark:text-[var(--accent-blue)] font-semibold'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
              title="Toggle Smart Money Concepts (Order Blocks, FVGs, Equilibrium)"
            >
              <Crosshair className="w-3 h-3" />
              SMC
            </button>
          </div>

          {/* ZOOM & PAN CONTROLS */}
          <div className="inline-flex items-center rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)] gap-0.5">
            {/* Pan Left */}
            <button
              onClick={handlePanLeft}
              title="Pan Left (Back in Time)"
              disabled={panOffset >= Math.max(0, allCandles.length - displayedCandles.length)}
              className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>

            {/* Zoom In */}
            <button
              onClick={handleZoomIn}
              title="Zoom In"
              disabled={zoomLevel >= 4}
              className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--accent-blue)] hover:bg-[var(--bg-surface)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>

            {/* Zoom Level Indicator */}
            <span className="px-1.5 text-[10px] tabular-nums font-semibold text-[var(--text-primary)] min-w-[34px] text-center">
              {Math.round(zoomLevel * 100)}%
            </span>

            {/* Zoom Out */}
            <button
              onClick={handleZoomOut}
              title="Zoom Out"
              disabled={zoomLevel <= 1}
              className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--accent-blue)] hover:bg-[var(--bg-surface)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>

            {/* Pan Right */}
            <button
              onClick={handlePanRight}
              title="Pan Right (Recent Time)"
              disabled={panOffset <= 0}
              className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>

            {/* Reset Zoom */}
            <button
              onClick={handleResetZoom}
              title="Reset Zoom & Pan"
              className="p-1 rounded text-[var(--text-muted)] hover:text-amber-500 hover:bg-[var(--bg-surface)] transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Sub-header Bar: Active Instrument & Live Greek stats */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-xs tabular-nums">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm text-[var(--text-primary)]">
            {chartMode === 'spot' ? `${symbol} Spot` : contractSymbol || `${symbol} ${selectedStrike} ${optionType}`}
          </span>
          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] dark:text-[var(--accent-blue)] border border-[var(--accent-blue)]/20">
            {timeframe.toUpperCase()} Candles
          </span>
          {chartMode === 'premium' && (
            <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
              Option Premium LTP: ₹{activeLtp?.toFixed(2)}
            </span>
          )}
          {zoomLevel > 1 && (
            <span className="text-[10px] text-[var(--text-muted)]">
              (Viewing {displayedCandles.length} of {allCandles.length} bars)
            </span>
          )}
        </div>

        {/* Greeks display when in Premium mode */}
        {chartMode === 'premium' && greeks && (
          <div className="flex items-center gap-3 text-[11px] text-[var(--text-muted)]">
            {greeks.delta !== undefined && (
              <span>Delta: <strong className="text-[var(--text-primary)]">{greeks.delta?.toFixed(2)}</strong></span>
            )}
            {greeks.theta !== undefined && (
              <span>Theta: <strong className="text-rose-500">{greeks.theta?.toFixed(1)}/day</strong></span>
            )}
            {greeks.iv !== undefined && (
              <span>IV: <strong className="text-amber-500">{(greeks.iv * 100)?.toFixed(1)}%</strong></span>
            )}
          </div>
        )}
      </div>

      {/* Candlestick Chart Area */}
      <div className="w-full h-[350px] relative">
        {loading && (
          <div className="absolute inset-0 z-10 bg-[var(--bg-surface)]/80 backdrop-blur-xs flex items-center justify-center">
            <div className="flex flex-col items-center gap-2">
              <div className="w-6 h-6 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
              <span className="text-xs tabular-nums text-[var(--text-muted)]">
                Loading {chartMode === 'spot' ? symbol : contractSymbol} ({timeframe}) candles...
              </span>
            </div>
          </div>
        )}

        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={displayedCandles} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
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
              tickFormatter={(v) => `₹${Number(v).toFixed(chartMode === 'premium' ? 1 : 0)}`}
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
                    <div className="p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] shadow-lg tabular-nums text-xs space-y-1">
                      <div className="text-[var(--text-muted)] text-[10px] pb-1 border-b border-[var(--border-subtle)] flex items-center justify-between gap-4">
                        <span className="font-semibold text-[var(--text-primary)]">
                          {chartMode === 'spot' ? symbol : contractSymbol}
                        </span>
                        <span>{d.time} IST</span>
                      </div>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 pt-1">
                        <span className="text-[var(--text-muted)]">Open:</span>
                        <span className="font-semibold text-right">₹{d.open?.toFixed(2)}</span>
                        <span className="text-[var(--text-muted)]">High:</span>
                        <span className="font-semibold text-emerald-500 text-right">₹{d.high?.toFixed(2)}</span>
                        <span className="text-[var(--text-muted)]">Low:</span>
                        <span className="font-semibold text-rose-500 text-right">₹{d.low?.toFixed(2)}</span>
                        <span className="text-[var(--text-muted)]">Close:</span>
                        <span className={`font-semibold text-right ${isUp ? 'text-emerald-500' : 'text-rose-500'}`}>
                          ₹{d.close?.toFixed(2)}
                        </span>
                        <span className="text-[var(--text-muted)]">Volume:</span>
                        <span className="text-right">{d.volume?.toLocaleString('en-IN')}</span>
                        {d.vwap && (
                          <>
                            <span className="text-amber-500">VWAP:</span>
                            <span className="text-right text-amber-500">₹{d.vwap?.toFixed(2)}</span>
                          </>
                        )}
                        {d.ema20 && (
                          <>
                            <span className="text-[var(--accent-blue)]">EMA 20:</span>
                            <span className="text-right text-[var(--accent-blue)]">₹{d.ema20?.toFixed(2)}</span>
                          </>
                        )}
                      </div>
                    </div>
                  );
                }
                return null;
              }}
            />

            {/* Support & Resistance Overlays for Spot */}
            {chartMode === 'spot' && resistanceLevel && (
              <ReferenceLine
                yAxisId="price"
                y={resistanceLevel}
                stroke="#ef4444"
                strokeDasharray="4 4"
                label={{ value: `Res: ₹${resistanceLevel}`, fill: '#ef4444', fontSize: 10, position: 'insideTopRight' }}
              />
            )}
            {chartMode === 'spot' && supportLevel && (
              <ReferenceLine
                yAxisId="price"
                y={supportLevel}
                stroke="#10b981"
                strokeDasharray="4 4"
                label={{ value: `Sup: ₹${supportLevel}`, fill: '#10b981', fontSize: 10, position: 'insideBottomRight' }}
              />
            )}

            {/* Smart Money Concepts (SMC) Visual Overlays */}
            {showSmc && chartMode === 'spot' && smcOverlay && (
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
              </>
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

      {/* Legend & Summary Footer */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 text-[11px] tabular-nums text-[var(--text-muted)] border-t border-[var(--border-subtle)]">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-xs bg-emerald-500"></span> Bullish
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-xs bg-rose-500"></span> Bearish
          </span>
          {showVwap && (
            <span className="flex items-center gap-1.5 text-amber-500">
              <span className="w-3 h-0.5 bg-amber-500"></span> VWAP
            </span>
          )}
          {showEma && (
            <span className="flex items-center gap-1.5 text-[var(--accent-blue)]">
              <span className="w-3 h-0.5 bg-[var(--accent-blue)]"></span> EMA 20/50
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-[var(--text-muted)] hidden sm:inline">
            Use <strong>[Ctrl + Scroll]</strong> or <strong>Zoom buttons</strong>
          </span>
          <div>
            {chartMode === 'spot' ? 'Index Spot:' : 'Contract LTP:'}{' '}
            <span className="text-[var(--text-primary)] font-semibold">
              ₹{activeLtp?.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
