export interface NewsItem {
  id: string;
  headline: string;
  source: string;
  url: string;
  publishedAt: string;
  retrievedAt: string;
  sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | string;
  sentimentScore: number; // -100 to +100
  impact: 'HIGH' | 'MEDIUM' | 'LOW' | string;
  relatedSymbols: string[];
  category?: string;
  dataStatus: string;
  provider: string;
}

export interface MarketNewsSentiment {
  overallSentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  sentimentRating: number; // 1.0 (Extreme Bearish) to 10.0 (Extreme Bullish), 5.5 = Neutral
  ratingLabel: 'Strong Bearish' | 'Mild Bearish' | 'Neutral' | 'Mild Bullish' | 'Strong Bullish' | string;
  sentimentScore: number; // -100 to +100
  bullishCount: number;
  bearishCount: number;
  neutralCount: number;
  totalArticles: number;
  ratingExplanation: string;
  topBullishHeadlines: string[];
  topBearishHeadlines: string[];
  affectedKeySectors: string[];
  updatedAt: string;
}

export interface StockPriceMetrics {
  symbol: string;
  companyName: string;
  currentPrice: number;
  change: number;
  changePercent: number;
  dayHigh: number;
  dayLow: number;
  exchange: string;
  isLive: boolean;
}

export interface StockSentimentData {
  symbol: string;
  companyName: string;
  overallSentiment: 'VERY BULLISH' | 'BULLISH' | 'NEUTRAL' | 'BEARISH' | 'VERY BEARISH' | string;
  sentimentScore: number; // 0 to 100
  polarityScore: number; // -100 to +100
  sentimentRating: number; // 1.0 to 10.0
  ratingLabel: string;
  confidence: 'HIGH' | 'MODERATE' | 'LOW' | string;
  totalArticles: number;
  bullishCount: number;
  bearishCount: number;
  neutralCount: number;
  bullishRatio: number;
  bearishRatio: number;
  neutralRatio: number;
  confluenceVerdict: string;
  institutionalVerdict: string;
  keyDrivers: string[];
  riskFactors: string[];
  priceMetrics?: StockPriceMetrics | null;
  optionsMetrics?: {
    isFnO: boolean;
    nearestExpiry: string;
    atmStrike: number;
    estimatedPcr: number;
    derivativesBias: string;
    activeExpiriesCount: number;
    fnoSegment: string;
  } | null;
  smcMetrics?: {
    dealingRangeHigh: number;
    dealingRangeLow: number;
    equilibrium50: number;
    positionPct: number;
    regime: string;
    smcOrderFlowBias: string;
    bslTarget: number;
    sslTarget: number;
    modelAlignment: string;
  } | null;
  sourcesVerified?: string[];
  articles: NewsItem[];
  calculatedAt: string;
  disclaimer: string;
}



export interface NewsApiResponse<T = NewsItem[]> {
  success: boolean;
  data: T;
  dataStatus?: string;
  dataTimestamp?: string;
  error?: { code: string; message: string };
}

export interface NewsStatusResponse {
  success: boolean;
  data: {
    provider: string;
    sourceType: string;
    status: string;
    activeSources?: string[];
    lastFetchTimestamp: string | null;
    totalArticlesFetched: number;
    cacheTtlSeconds: number;
    freeTier: boolean;
    rateLimitPerMinute: string;
  };
}

export interface StockNewsArticle {
  id: string;
  headline: string;
  source: string;
  url: string;
  publishedAt: string;
  ingestedAt: string;
  category: string;
  polarity: number;
  impact: number;
  confidence: number;
  verificationStatus: string;
  explanation: string;
  isSyndicatedCopy?: boolean;
}

export interface IntradayStockOpportunity {
  rank: number;
  symbol: string;
  companyName: string;
  sector: string;
  exchange: string;
  primaryHeadline: string;
  primarySource: string;
  primaryUrl: string;
  publishedAt: string;
  ageHours: number;
  category: string;
  sentiment: 'VERY_BULLISH' | 'BULLISH' | 'NEUTRAL' | 'BEARISH' | 'VERY_BEARISH' | string;
  sentimentPolarity: number; // -100 to +100
  impactScore: number;       // 0 to 100
  compositeRankScore: number;// 0 to 100
  confidence: number;        // 0.0 to 1.0
  verificationStatus: string;
  explanation: string;
  catalyst: string;
  articlesCount: number;
  articles: StockNewsArticle[];
  currentPrice: number | null;
  change: number | null;
  changePercent: number | null;
  dayHigh: number | null;
  dayLow: number | null;
  volume: number | null;
  vwap: number | null;
  quoteTimestamp: string | null;
  dataStatus: string;
  priceConfirmation: 'BULLISH_WATCHLIST_CANDIDATE' | 'BEARISH_WATCHLIST_CANDIDATE' | 'NEWS_PRICE_DIVERGENCE' | 'PENDING_CONFIRMATION' | 'PRICE_UNVERIFIED' | string;
  intradayBias: 'BULLISH' | 'BEARISH' | 'DIVERGENCE' | 'NEUTRAL' | string;
  researchStatus: 'RESEARCH_WATCHLIST_ACTIVE' | 'PRICE_UNVERIFIED' | 'NO_CONFIRMED_SETUP' | string;
}

export interface IntradayTopStocksResponse {
  direction: 'all' | 'bullish' | 'bearish';
  generatedAt: string;
  sourceFreshness: string;
  totalArticlesAnalyzed: number;
  totalQualifiedStocks: number;
  stocks: IntradayStockOpportunity[];
  dataStatus: string;
  disclaimer: string;
}

export interface IntradayScannerStatus {
  status: string;
  sourcesActive: string[];
  lastIngestionTimestamp: string | null;
  totalArticlesInCache: number;
  totalStocksScanned: number;
  totalQualifiedBullish: number;
  totalQualifiedBearish: number;
  unauthorizedSourcesReported: string[];
  cacheTtlSeconds: number;
}


const API_BASE_URL = typeof window !== 'undefined'
  ? ''
  : (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000');

class NewsService {
  private async fetchJson<T>(endpoint: string): Promise<T | null> {
    try {
      const res = await fetch(`${API_BASE_URL}${endpoint}`, {
        cache: 'no-store',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      if (!res.ok) {
        console.warn(`News API error ${res.status} on ${endpoint}`);
        return null;
      }
      return (await res.json()) as T;
    } catch (err) {
      console.warn(`News fetch failed for ${endpoint}:`, err);
      return null;
    }
  }

  async getStockSentiment(symbol: string): Promise<StockSentimentData | null> {
    const clean = encodeURIComponent(symbol.trim());
    const res = await this.fetchJson<NewsApiResponse<StockSentimentData>>(`/api/news/stock-sentiment/${clean}`);
    if (res && res.success && res.data) {
      return res.data;
    }
    return null;
  }

  async getMarketNews(limit: number = 20): Promise<NewsItem[]> {
    const res = await this.fetchJson<NewsApiResponse<NewsItem[]>>(`/api/news/market?limit=${limit}`);
    if (res && res.success && Array.isArray(res.data)) {
      return res.data;
    }
    return [];
  }

  async getMarketSentiment(): Promise<MarketNewsSentiment | null> {
    const res = await this.fetchJson<NewsApiResponse<MarketNewsSentiment>>('/api/news/sentiment');
    if (res && res.success && res.data) {
      return res.data;
    }
    return null;
  }

  async getStockNews(symbol: string, limit: number = 6): Promise<NewsItem[]> {
    const clean = encodeURIComponent(symbol.trim());
    const res = await this.fetchJson<NewsApiResponse<NewsItem[]>>(`/api/news/symbol/${clean}?limit=${limit}`);
    if (res && res.success && Array.isArray(res.data)) {
      return res.data;
    }
    return [];
  }

  async searchNews(query: string, limit: number = 10): Promise<NewsItem[]> {
    const q = encodeURIComponent(query.trim());
    const res = await this.fetchJson<NewsApiResponse<NewsItem[]>>(`/api/news/search?q=${q}&limit=${limit}`);
    if (res && res.success && Array.isArray(res.data)) {
      return res.data;
    }
    return [];
  }

  async getNewsStatus(): Promise<NewsStatusResponse['data'] | null> {
    const res = await this.fetchJson<NewsStatusResponse>('/api/news/status');
    if (res && res.success && res.data) {
      return res.data;
    }
    return null;
  }

  async getIntradayTopStocks(direction: 'all' | 'bullish' | 'bearish' = 'all', limit: number = 10): Promise<IntradayTopStocksResponse | null> {
    const res = await this.fetchJson<NewsApiResponse<IntradayTopStocksResponse>>(`/api/news/intraday/top-stocks?direction=${direction}&limit=${limit}`);
    if (res && res.success && res.data) {
      return res.data;
    }
    return null;
  }

  async getIntradayStockOpportunity(symbol: string): Promise<IntradayStockOpportunity | null> {
    const clean = encodeURIComponent(symbol.trim());
    const res = await this.fetchJson<NewsApiResponse<IntradayStockOpportunity>>(`/api/news/intraday/stock/${clean}`);
    if (res && res.success && res.data) {
      return res.data;
    }
    return null;
  }

  async getIntradayScannerStatus(): Promise<IntradayScannerStatus | null> {
    const res = await this.fetchJson<NewsApiResponse<IntradayScannerStatus>>('/api/news/intraday/status');
    if (res && res.success && res.data) {
      return res.data;
    }
    return null;
  }
}

export const newsService = new NewsService();
