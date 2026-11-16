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
import { ObserverIntelligenceData } from '@/types/observer';
import { apiClient } from '@/lib/api';
import { ALL_SEARCH_STOCKS, MOCK_STOCK_ANALYSES } from '@/lib/mock-market-data';

// Service layer connected to FastAPI Quantitative Backend with resilient local fallback
export const marketDataService = {
  /**
   * Fetch The God's Eye - Observer Signal Intelligence Array
   */
  async getObserverIntelligence(): Promise<ObserverIntelligenceData> {
    return apiClient.getObserverIntelligence();
  },
  /**
   * Fetch primary market benchmark indices (NIFTY 50, BANK NIFTY, FINNIFTY, INDIA VIX)
   */
  async getMarketOverview(): Promise<MarketIndex[]> {
    return apiClient.getMarketOverview();
  },

  /**
   * Fetch overarching market sentiment and breadth indicators
   */
  async getMarketSentiment(): Promise<MarketSentiment> {
    return apiClient.getMarketSentiment();
  },

  /**
   * Fetch Top CALL candidates.
   * Business Rule 1: Never force 5 candidates. Returns strictly qualified setups (e.g. 3).
   * Business Rule 3: If no candidate qualifies, returns empty array to show "NO QUALIFIED SETUP".
   */
  async getTopCallCandidates(): Promise<SignalCandidate[]> {
    return apiClient.getTopCallCandidates();
  },

  /**
   * Fetch Top PUT candidates.
   * Business Rule 2: Never force 5 candidates. Returns strictly qualified setups (e.g. 2).
   */
  async getTopPutCandidates(): Promise<SignalCandidate[]> {
    return apiClient.getTopPutCandidates();
  },

  /**
   * Fetch market drivers summary cards
   */
  async getMarketDrivers(): Promise<MarketDriver[]> {
    return apiClient.getMarketDrivers();
  },

  /**
   * Fetch sectoral heatmap data
   */
  async getSectorHeatmap(): Promise<SectorHeatmapItem[]> {
    return apiClient.getSectorHeatmap();
  },

  /**
   * Fetch recent AI signals table
   */
  async getRecentSignals(): Promise<RecentAISignal[]> {
    return apiClient.getRecentSignals();
  },

  /**
   * Search stock database by symbol or company name with exchange & cap filters
   */
  async searchStocks(query = '', filters?: { exchange?: string; cap?: string }): Promise<typeof ALL_SEARCH_STOCKS> {
    return apiClient.searchStocks(query, filters);
  },

  /**
   * Fetch deep analytical dossier for a specific stock symbol
   */
  async getStockAnalysis(symbol: string): Promise<StockAnalysis | null> {
    return apiClient.getStockAnalysis(symbol);
  },

  /**
   * Fetch dedicated AI structured insights for a given stock
   */
  async getAIInsights(symbol: string): Promise<AIInsight | null> {
    return apiClient.getAIInsights(symbol);
  },

  /**
   * Get list of all available stock symbols for switching in AI insights
   */
  async getAvailableSymbols(): Promise<{ symbol: string; companyName: string; trend: string }[]> {
    return Object.values(MOCK_STOCK_ANALYSES).map((a) => ({
      symbol: a.symbol,
      companyName: a.companyName,
      trend: a.trend,
    }));
  },
};
