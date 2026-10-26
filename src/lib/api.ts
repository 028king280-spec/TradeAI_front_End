/**
 * AIVOLVE Trading AI — API Client
 * Connects the Next.js frontend to the FastAPI quantitative backend.
 * Provides resilient fallback to local data if backend is unreachable.
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
import {
  MOCK_INDICES,
  MOCK_MARKET_SENTIMENT,
  MOCK_CALL_CANDIDATES,
  MOCK_PUT_CANDIDATES,
  MOCK_MARKET_DRIVERS,
  MOCK_SECTOR_HEATMAP,
  MOCK_RECENT_SIGNALS,
  MOCK_STOCK_ANALYSES,
  ALL_SEARCH_STOCKS,
} from '@/lib/mock-market-data';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

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
  } catch (err) {
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
    return data || MOCK_INDICES;
  },

  /**
   * Fetch market sentiment and breadth
   */
  async getMarketSentiment(): Promise<MarketSentiment> {
    const data = await fetchFromBackend<MarketSentiment>('/api/market/sentiment');
    return data || MOCK_MARKET_SENTIMENT;
  },

  /**
   * Fetch Top CALL candidates
   */
  async getTopCallCandidates(): Promise<SignalCandidate[]> {
    const data = await fetchFromBackend<SignalCandidate[]>('/api/signals/calls');
    if (data && Array.isArray(data) && data.length > 0) {
      return data;
    }
    return MOCK_CALL_CANDIDATES.filter((c) => c.qualified && c.analysisScore >= 80).slice(0, 5);
  },

  /**
   * Fetch Top PUT candidates
   */
  async getTopPutCandidates(): Promise<SignalCandidate[]> {
    const data = await fetchFromBackend<SignalCandidate[]>('/api/signals/puts');
    if (data && Array.isArray(data) && data.length > 0) {
      return data;
    }
    return MOCK_PUT_CANDIDATES.filter((c) => c.qualified && c.analysisScore >= 75).slice(0, 5);
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
    return data || MOCK_MARKET_DRIVERS;
  },

  /**
   * Fetch sector heatmap
   */
  async getSectorHeatmap(): Promise<SectorHeatmapItem[]> {
    const data = await fetchFromBackend<SectorHeatmapItem[]>('/api/market/sectors');
    return data || MOCK_SECTOR_HEATMAP;
  },

  /**
   * Fetch recent AI signals
   */
  async getRecentSignals(): Promise<RecentAISignal[]> {
    const data = await fetchFromBackend<RecentAISignal[]>('/api/market/recent-signals');
    return data || MOCK_RECENT_SIGNALS;
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

    // Local fallback
    const q = query.trim().toUpperCase();
    let results = ALL_SEARCH_STOCKS;
    if (q) {
      results = results.filter(
        (s) => s.symbol.toUpperCase().includes(q) || s.companyName.toUpperCase().includes(q)
      );
    }
    if (filters?.exchange && filters.exchange !== 'ALL') {
      results = results.filter((s) => s.exchange === filters.exchange);
    }
    if (filters?.cap && filters.cap !== 'ALL') {
      results = results.filter((s) => s.category === filters.cap);
    }
    return results;
  },

  /**
   * Fetch complete stock analytical dossier
   */
  async getStockAnalysis(symbol: string): Promise<StockAnalysis | null> {
    const data = await fetchFromBackend<StockAnalysis>(`/api/stocks/${symbol.toUpperCase()}/analysis`);
    if (data) {
      return data;
    }

    // Fallback to local mock analysis
    const upper = symbol.toUpperCase();
    if (MOCK_STOCK_ANALYSES[upper]) {
      return MOCK_STOCK_ANALYSES[upper];
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
};
