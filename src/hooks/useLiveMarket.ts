'use client';

/**
 * React hooks for consuming live market data from the SSE stream.
 * Provides auto-connecting, auto-reconnecting hooks for components.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { liveMarketService, LiveTick, LiveStreamStatus } from '@/services/liveMarketService';

/**
 * Hook: Subscribe to live ticks for a specific symbol.
 * Auto-connects to SSE stream on mount.
 */
export function useLiveTick(symbol: string): {
  tick: LiveTick | null;
  connected: boolean;
} {
  const [tick, setTick] = useState<LiveTick | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const unsub = liveMarketService.onTick(symbol, (newTick) => {
      setTick(newTick);
    });
    const statusUnsub = liveMarketService.onStatusChange(setConnected);

    return () => {
      unsub();
      statusUnsub();
    };
  }, [symbol]);

  return { tick, connected };
}

/**
 * Hook: Subscribe to live ticks for multiple symbols.
 * Returns a map of symbol -> latest tick.
 */
export function useLiveTicks(symbols: string[]): {
  ticks: Record<string, LiveTick>;
  connected: boolean;
} {
  const [ticks, setTicks] = useState<Record<string, LiveTick>>({});
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const unsubs: (() => void)[] = [];

    for (const sym of symbols) {
      const unsub = liveMarketService.onTick(sym, (newTick) => {
        setTicks((prev) => ({ ...prev, [sym.toUpperCase()]: newTick }));
      });
      unsubs.push(unsub);
    }

    const statusUnsub = liveMarketService.onStatusChange(setConnected);
    unsubs.push(statusUnsub);

    return () => unsubs.forEach((u) => u());
  }, [symbols.join(',')]);

  return { ticks, connected };
}

/**
 * Hook: Global live stream manager.
 * Call once at app level to establish SSE connection.
 */
export function useLiveStreamConnection(
  symbols: string[] = ['NIFTY 50', 'BANK NIFTY', 'FINNIFTY', 'INDIA VIX'],
): {
  connected: boolean;
  latestTick: LiveTick | null;
  tickCount: number;
} {
  const [connected, setConnected] = useState(false);
  const [latestTick, setLatestTick] = useState<LiveTick | null>(null);
  const [tickCount, setTickCount] = useState(0);

  useEffect(() => {
    // Connect to SSE
    liveMarketService.connect(symbols);

    const statusUnsub = liveMarketService.onStatusChange(setConnected);
    const tickUnsub = liveMarketService.onAnyTick((tick) => {
      setLatestTick(tick);
      setTickCount((c) => c + 1);
    });

    return () => {
      statusUnsub();
      tickUnsub();
      liveMarketService.disconnect();
    };
  }, [symbols.join(',')]);

  return { connected, latestTick, tickCount };
}

/**
 * Hook: Live stream status diagnostics.
 */
export function useLiveStreamStatus(): {
  status: LiveStreamStatus | null;
  loading: boolean;
  refresh: () => void;
} {
  const [status, setStatus] = useState<LiveStreamStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    const s = await liveMarketService.getStreamStatus();
    setStatus(s);
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  }, [refresh]);

  return { status, loading, refresh };
}

/**
 * Hook: Accumulate live candle data for charting.
 * Converts tick stream into OHLCV candle array for the chart.
 */
export function useLiveCandles(
  symbol: string,
  intervalMs: number = 60000, // 1 minute default
): {
  candles: Array<{
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  }>;
  currentCandle: { open: number; high: number; low: number; close: number; volume: number } | null;
} {
  const [candles, setCandles] = useState<
    Array<{ time: string; open: number; high: number; low: number; close: number; volume: number }>
  >([]);
  const currentCandleRef = useRef<{
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    startTime: number;
  } | null>(null);
  const [currentCandle, setCurrentCandle] = useState<{
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  } | null>(null);

  useEffect(() => {
    const unsub = liveMarketService.onTick(symbol, (tick) => {
      if (!tick.ltp) return;

      const now = Date.now();
      const candle = currentCandleRef.current;

      if (!candle || now - candle.startTime >= intervalMs) {
        // Close current candle and start new one
        if (candle) {
          const timeStr = new Date(candle.startTime).toLocaleTimeString('en-IN', {
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
          });
          setCandles((prev) => [
            ...prev.slice(-99), // Keep last 100 candles
            {
              time: timeStr,
              open: candle.open,
              high: candle.high,
              low: candle.low,
              close: candle.close,
              volume: candle.volume,
            },
          ]);
        }

        // Start new candle
        currentCandleRef.current = {
          open: tick.ltp,
          high: tick.ltp,
          low: tick.ltp,
          close: tick.ltp,
          volume: tick.volume || 0,
          startTime: now,
        };
      } else {
        // Update current candle
        candle.high = Math.max(candle.high, tick.ltp);
        candle.low = Math.min(candle.low, tick.ltp);
        candle.close = tick.ltp;
        candle.volume = tick.volume || candle.volume;
      }

      setCurrentCandle(
        currentCandleRef.current
          ? {
              open: currentCandleRef.current.open,
              high: currentCandleRef.current.high,
              low: currentCandleRef.current.low,
              close: currentCandleRef.current.close,
              volume: currentCandleRef.current.volume,
            }
          : null,
      );
    });

    return () => unsub();
  }, [symbol, intervalMs]);

  return { candles, currentCandle };
}
