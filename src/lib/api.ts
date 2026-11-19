/**
 * AIVOLVE Trading AI — API Client
 * Connects the Next.js frontend to the FastAPI quantitative backend.
 * Preserves empty results and explicit unavailable states when the backend fails.
 */

import {
  MarketIndex,
  MarketSentiment,
  SignalCandidate,
  MarketDriver,
  SectorHeatmapItem,
  RecentAISignal,
  StockAnalysis,
  AIInsight,
} from '@/types/market';
import { MacroCalendarResponse, ProximityReport } from '@/types/macro';
import { ObserverIntelligenceData } from '@/types/observer';
import {
  ALL_SEARCH_STOCKS,
} from '@/lib/mock-market-data';

const API_BASE_URL = typeof window !== 'undefined'
  ? ''
  : (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000');

interface BackendEnvelope<T> {
  success: boolean;
  data: T;
  error?: {
    code: string;
    message: string;
  };
  timestamp?: string;
}

async function fetchFromBackend<T>(endpoint: string, options?: RequestInit): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE_URL}${endpoint}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options?.headers || {}),
      },
      // Short timeout to fallback gracefully if backend is offline
      signal: AbortSignal.timeout(6000),
    });

    if (!res.ok) {
      console.warn(`Backend endpoint ${endpoint} returned status ${res.status}`);
      return null;
    }

    const envelope: BackendEnvelope<T> = await res.json();
    if (envelope.success && envelope.data !== undefined) {
      return envelope.data;
    }
    return null;
  } catch {
    // Graceful fallback during offline development
    return null;
  }
}

export const apiClient = {
  /**
   * Check backend health and market data provider status
   */
  async getHealth(): Promise<{ status: string; provider: string; marketStatus: string } | null> {
    return fetchFromBackend('/api/health');
  },

  /**
   * Fetch market indices
   */
  async getMarketOverview(): Promise<MarketIndex[]> {
    const data = await fetchFromBackend<MarketIndex[]>('/api/market/overview');
    return data ?? [];
  },

  /**
   * Fetch market sentiment and breadth
   */
  async getMarketSentiment(): Promise<MarketSentiment> {
    const data = await fetchFromBackend<MarketSentiment>('/api/market/sentiment');
    if (!data) throw new Error('Market sentiment is unavailable');
    return data;
  },

  /**
   * Fetch Top CALL candidates
   */
  async getTopCallCandidates(): Promise<SignalCandidate[]> {
    const data = await fetchFromBackend<SignalCandidate[]>('/api/signals/calls');
    if (data && Array.isArray(data) && data.length > 0) {
      return data;
    }
    return [];
  },

  /**
   * Fetch Top PUT candidates
   */
  async getTopPutCandidates(): Promise<SignalCandidate[]> {
    const data = await fetchFromBackend<SignalCandidate[]>('/api/signals/puts');
    if (data && Array.isArray(data) && data.length > 0) {
      return data;
    }
    return [];
  },

  /**
   * Fetch today's qualified CALL and PUT candidates from scanner
   */
  async getTodaySignals(): Promise<{ calls: SignalCandidate[]; puts: SignalCandidate[] }> {
    const data = await fetchFromBackend<{ calls: SignalCandidate[]; puts: SignalCandidate[] }>('/api/signals/today');
    if (data && data.calls && data.puts) {
      return data;
    }
    const calls = await this.getTopCallCandidates();
    const puts = await this.getTopPutCandidates();
    return { calls, puts };
  },

  /**
   * Fetch market drivers cards
   */
  async getMarketDrivers(): Promise<MarketDriver[]> {
    const data = await fetchFromBackend<MarketDriver[]>('/api/market/drivers');
    return data ?? [];
  },

  /**
   * Fetch sector heatmap
   */
  async getSectorHeatmap(): Promise<SectorHeatmapItem[]> {
    const data = await fetchFromBackend<SectorHeatmapItem[]>('/api/market/sectors');
    return data ?? [];
  },

  /**
   * Fetch recent AI signals
   */
  async getRecentSignals(): Promise<RecentAISignal[]> {
    const data = await fetchFromBackend<RecentAISignal[]>('/api/market/recent-signals');
    return data ?? [];
  },

  /**
   * Fetch The God's Eye - Observer Intelligence Dashboard Data
   */
  async getObserverIntelligence(): Promise<ObserverIntelligenceData> {
    const data = await fetchFromBackend<ObserverIntelligenceData>('/api/market/observer');
    if (!data) throw new Error('Observer data is unavailable');
    return data;
  },

  /**
   * Search stock directory
   */
  async searchStocks(
    query = '',
    filters?: { exchange?: string; cap?: string }
  ): Promise<typeof ALL_SEARCH_STOCKS> {
    const params = new URLSearchParams();
    if (query) params.append('q', query);
    if (filters?.exchange) params.append('exchange', filters.exchange);
    if (filters?.cap) params.append('cap', filters.cap);

    const data = await fetchFromBackend<typeof ALL_SEARCH_STOCKS>(`/api/stocks/search?${params.toString()}`);
    if (data && Array.isArray(data) && data.length > 0) {
      return data;
    }

    return [];
  },

  /**
   * Fetch complete stock analytical dossier
   */
  async getStockAnalysis(symbol: string): Promise<StockAnalysis | null> {
    const data = await fetchFromBackend<StockAnalysis>(`/api/stocks/${symbol.toUpperCase()}/analysis`);
    if (data) {
      return data;
    }

    return null;
  },

  /**
   * Fetch AI structured insights
   */
  async getAIInsights(symbol: string): Promise<AIInsight | null> {
    const data = await fetchFromBackend<AIInsight>(`/api/stocks/${symbol.toUpperCase()}/ai-insights`);
    if (data) {
      return data;
    }
    const analysis = await this.getStockAnalysis(symbol);
    return analysis ? analysis.aiInsights : null;
  },

  /**
   * Fetch institutional macroeconomic calendar events (REQ-6.11)
   */
  async getMacroCalendar(params?: { tier?: string; index?: string }): Promise<MacroCalendarResponse | null> {
    const query = new URLSearchParams();
    if (params?.tier) query.set('tier', params.tier);
    if (params?.index) query.set('index', params.index);
    const qs = query.toString();
    return fetchFromBackend<MacroCalendarResponse>(`/api/macro/calendar${qs ? `?${qs}` : ''}`);
  },

  /**
   * Fetch deterministic macro proximity diagnostics (REQ-6.11)
   */
  async getMacroProximity(index: string = 'NIFTY 50'): Promise<ProximityReport | null> {
    const query = new URLSearchParams({ index });
    return fetchFromBackend<ProximityReport>(`/api/macro/proximity?${query.toString()}`);
  },
};
