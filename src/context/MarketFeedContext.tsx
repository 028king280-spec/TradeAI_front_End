'use client';

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

export interface WorkspaceQuote {
  symbol: string;
  currentValue: number | null;
  changePercent: number | null;
  dataStatus: string;
  timestamp: string | null;
}
interface MarketFeedSnapshot {
  dataStatus: string;
  marketStatus: string;
  provider: string | null;
  quotes: WorkspaceQuote[];
  checkedAt: string | null;
}
const empty: MarketFeedSnapshot = { dataStatus: 'CHECKING', marketStatus: 'UNKNOWN', provider: null, quotes: [], checkedAt: null };
const MarketFeedContext = createContext<MarketFeedSnapshot>(empty);

export function MarketFeedProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState(empty);
  useEffect(() => {
    let stopped = false;
    let nextPoll: ReturnType<typeof setTimeout>;
    let controller: AbortController;
    async function poll() {
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch('/api/market/live', { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('Market feed unavailable');
        const payload = await response.json();
        if (payload.success !== true || !Array.isArray(payload.data?.indices)) throw new Error('Invalid market feed');
        const data = payload.data;
        const quotes = data.indices.filter((item: Record<string, unknown>) => item && typeof item.symbol === 'string').map((item: Record<string, unknown>) => ({
          symbol: String(item.symbol),
          currentValue: typeof item.currentValue === 'number' && Number.isFinite(item.currentValue) && item.currentValue > 0 ? item.currentValue : null,
          changePercent: typeof item.changePercent === 'number' && Number.isFinite(item.changePercent) ? item.changePercent : null,
          dataStatus: typeof item.dataStatus === 'string' ? item.dataStatus : 'UNAVAILABLE',
          timestamp: typeof item.timestamp === 'string' ? item.timestamp : null,
        }));
        if (!stopped) setSnapshot({ dataStatus: typeof payload.dataStatus === 'string' ? payload.dataStatus : 'UNAVAILABLE', marketStatus: data.marketStatus || 'UNKNOWN', provider: data.provider || null, quotes, checkedAt: new Date().toISOString() });
      } catch {
        if (!stopped) setSnapshot({ ...empty, dataStatus: 'DATA_OFFLINE' });
      } finally {
        clearTimeout(timeout);
        if (!stopped) nextPoll = setTimeout(poll, 15000);
      }
    }
    void poll();
    return () => { stopped = true; clearTimeout(nextPoll); controller?.abort(); };
  }, []);
  return <MarketFeedContext.Provider value={snapshot}>{children}</MarketFeedContext.Provider>;
}

export const useMarketFeed = () => useContext(MarketFeedContext);

export function feedLabel(status: string) {
  switch (status) {
    case 'LIVE': case 'VERIFIED_LIVE': return 'Live data';
    case 'MOCK': return 'Demo data';
    case 'MARKET_CLOSED': case 'VERIFIED_EOD': return 'End-of-day data';
    case 'STALE': case 'STALE_TICK': return 'Stale data';
    case 'CHECKING': return 'Checking feed';
    case 'DATA_OFFLINE': return 'Data offline';
    default: return 'Data unavailable';
  }
}
