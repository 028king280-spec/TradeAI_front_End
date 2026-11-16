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
import { MacroCalendarResponse, ProximityReport } from '@/types/macro';
import { ObserverIntelligenceData } from '@/types/observer';
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

export const MOCK_OBSERVER_DATA: ObserverIntelligenceData = {
  title: "MARKET SENTIMENT & BIAS RADAR",
  subtitle: "SIGNAL INTELLIGENCE ARRAY · PATTERN RECOGNITION ENGINE",
  marketSession: "Pre-Market",
  timestamp: "30 Oct 2026, 08:02 AM IST",
  isLive: true,
  marketHealth: {
    score: 93,
    label: "Overall Signal Strength",
  },
  marketStatus: {
    bullish: 53,
    bearish: 34,
    neutral: 13,
  },
  fgIndex: {
    value: 0.8,
    label: "Extreme Greed",
    prevValue: 0.79,
    changePercent: 1.3,
  },
  vix: {
    value: 21.6,
    prevValue: 21.1,
    changePercent: 2.4,
    sparkline: [20.8, 20.9, 21.0, 21.2, 21.4, 21.3, 21.6],
  },
  assets: [
    {
      id: "nifty",
      symbol: "NIFTY",
      name: "NIFTY 50",
      change: 2.8,
      changeStr: "+2.8",
      bias: "BULLISH",
      sparkline: [24500, 24580, 24620, 24590, 24710, 24780, 24850, 24820, 24910, 24960],
      rationale: "Holding strong above 20 & 50 EMA cluster with aggressive Put writing at 24,800. Strong domestic DII buying in banking & auto counters.",
      drivers: [
        "Derivatives: PCR at 1.24 confirms heavy Put writing base support",
        "Technicals: Price sustained above intraday VWAP with RSI at 61.5",
        "Institutional: Sustained DII net absorption countering minor FII sales"
      ],
      sources: ["Moneycontrol Markets", "NSE Derivatives & PCR", "Economic Times"],
      catalyst: {
        headline: "Nifty holds above key support as institutional inflows remain steady",
        source: "Economic Times",
        sentiment: "BULLISH",
        publishedAt: "25m ago",
        url: "https://economictimes.indiatimes.com",
        impact: "HIGH",
      },
    },
    {
      id: "sensex",
      symbol: "SENSEX",
      name: "BSE SENSEX",
      change: 3.4,
      changeStr: "+3.4",
      bias: "BULLISH",
      sparkline: [80500, 80700, 80900, 80850, 81200, 81400, 81750, 81680, 82100, 82350],
      rationale: "Top gainer (+3.4%) led by rally in heavyweight private banking, telecom, and consumer majors surpassing the 81,500 hurdle.",
      drivers: [
        "Heavyweights: ICICI Bank, Reliance & HDFC Bank leading index momentum",
        "Macro: Robust corporate balance sheets and strong GST collections",
        "Technicals: Decisive breakout above previous session resistance"
      ],
      sources: ["BSE India Official", "Economic Times", "Livemint"],
      catalyst: {
        headline: "Sensex gains driven by heavyweights in IT and Banking",
        source: "Moneycontrol",
        sentiment: "BULLISH",
        publishedAt: "30m ago",
        url: "https://www.moneycontrol.com",
        impact: "HIGH",
      },
    },
    {
      id: "banknifty",
      symbol: "BANKNIFTY",
      name: "NIFTY BANK",
      change: 2.2,
      changeStr: "+2.2",
      bias: "BULLISH",
      sparkline: [50800, 50950, 51100, 51020, 51300, 51450, 51600, 51520, 51800, 51950],
      rationale: "Driven by solid credit growth (14.5% YoY), robust net interest margins (NIMs), and call unwinding across 51,000 strikes.",
      drivers: [
        "Sectoral: Private banking asset quality at multi-year peak with record low NPAs",
        "Derivatives: Heavy call unwinding indicating minimal overhead supply",
        "Technicals: Sustained trading above 51,200 swing resistance"
      ],
      sources: ["Livemint Banking", "RBI Sectoral Credit", "Moneycontrol"],
      catalyst: {
        headline: "Banking sector benefits from strong credit demand and stable asset quality",
        source: "Livemint",
        sentiment: "BULLISH",
        publishedAt: "45m ago",
        url: "https://www.livemint.com",
        impact: "HIGH",
      },
    },
    {
      id: "gold",
      symbol: "GOLD",
      name: "Gold Commodity",
      change: -2.3,
      changeStr: "-2.3",
      bias: "BEARISH",
      sparkline: [78400, 78200, 78050, 78150, 77900, 77750, 77600, 77650, 77400, 77200],
      rationale: "Softening (-2.3%) as the US Dollar index strengthens to 104.2 and benchmark US 10-year Treasury yields advance.",
      drivers: [
        "Currency: US Dollar Index (DXY) rebound dampens non-yielding bullion demand",
        "Yields: Rising US Treasury yields increase the opportunity cost of holding gold",
        "Flows: Institutional profit-booking after testing all-time highs"
      ],
      sources: ["Reuters Commodities", "Economic Times Commodities", "MCX India"],
      catalyst: {
        headline: "Gold prices soften as US dollar firms ahead of macroeconomic data",
        source: "Economic Times",
        sentiment: "BEARISH",
        publishedAt: "1h ago",
        url: "https://economictimes.indiatimes.com",
        impact: "HIGH",
      },
    },
    {
      id: "crudeoil",
      symbol: "CRUDEOIL",
      name: "Crude Oil",
      change: -1.6,
      changeStr: "-1.6",
      bias: "NEUTRAL",
      sparkline: [6150, 6120, 6140, 6110, 6130, 6100, 6115, 6080, 6095, 6090],
      rationale: "Range-bound trading (-1.6%) caught in a tug-of-war between Middle East geopolitical risk premiums and sluggish global manufacturing demand.",
      drivers: [
        "Supply: OPEC+ production quota compliance maintains price floor",
        "Demand: Subdued industrial manufacturing indices from major importing nations",
        "Range: Brent crude fluctuating in narrow $72-$76/barrel corridor"
      ],
      sources: ["Energy Intelligence", "Livemint Energy", "Moneycontrol"],
      catalyst: {
        headline: "Crude oil trades range-bound amid demand concerns and supply checks",
        source: "Moneycontrol",
        sentiment: "NEUTRAL",
        publishedAt: "1h ago",
        url: "https://www.moneycontrol.com",
        impact: "MEDIUM",
      },
    },
    {
      id: "bitcoin",
      symbol: "BITCOIN",
      name: "Bitcoin USD",
      change: -3.0,
      changeStr: "-3.0",
      bias: "BEARISH",
      sparkline: [68500, 68100, 67900, 68050, 67600, 67300, 67100, 67250, 66800, 66500],
      rationale: "Short-term pullback (-3.0%) triggered by derivative long liquidations after testing psychological resistance at $68,500.",
      drivers: [
        "Derivatives: High leverage flush and long liquidations on crypto exchanges",
        "Flows: Spot Bitcoin ETF daily net inflows recorded temporary pause",
        "Technicals: Failed breakout at upper Bollinger Band on 4-hour chart"
      ],
      sources: ["CoinDesk Market Analysis", "Livemint Crypto", "TradingView"],
      catalyst: {
        headline: "Crypto assets witness profit-taking after testing upper resistance levels",
        source: "Livemint",
        sentiment: "BEARISH",
        publishedAt: "2h ago",
        url: "https://www.livemint.com",
        impact: "HIGH",
      },
    },
    {
      id: "nasdaq",
      symbol: "NASDAQ",
      name: "NASDAQ 100",
      change: -3.4,
      changeStr: "-3.4",
      bias: "BEARISH",
      sparkline: [20400, 20250, 20180, 20220, 19980, 19850, 19790, 19820, 19680, 19550],
      rationale: "Growth tech stocks under pressure (-3.4%) as rising US 10-year yields compress equity valuation multiples.",
      drivers: [
        "Valuation: US 10-Year yield pushing above 4.25% compresses tech P/E multiples",
        "Earnings: Market digesting heavy capital expenditure outlook for AI infrastructure",
        "Technicals: Breached 20-day moving average on above-average selling volume"
      ],
      sources: ["Bloomberg Markets", "Economic Times Global", "CNBC"],
      catalyst: {
        headline: "Global tech stocks under pressure as bond yields tick higher",
        source: "Economic Times",
        sentiment: "BEARISH",
        publishedAt: "2h ago",
        url: "https://economictimes.indiatimes.com",
        impact: "HIGH",
      },
    },
    {
      id: "silver",
      symbol: "SILVER",
      name: "Silver Commodity",
      change: -4.5,
      changeStr: "-4.5",
      bias: "BEARISH",
      sparkline: [98500, 97800, 97200, 97400, 96500, 95800, 95200, 95400, 94600, 94100],
      rationale: "Top loser (-4.5%) as dual headwinds of stronger dollar and slowing global industrial manufacturing weigh heavily.",
      drivers: [
        "Industrial: Demand contraction in solar panel and industrial electronics manufacturing",
        "Ratio: Gold-to-Silver ratio widening, signaling sharp silver underperformance",
        "Technicals: Pierced primary technical support at 96,000 on MCX"
      ],
      sources: ["MCX India", "Moneycontrol Commodities", "Economic Times"],
      catalyst: {
        headline: "Industrial metals and silver retreat on strong dollar index",
        source: "Moneycontrol",
        sentiment: "BEARISH",
        publishedAt: "3h ago",
        url: "https://www.moneycontrol.com",
        impact: "HIGH",
      },
    },
    {
      id: "dji",
      symbol: "DJI",
      name: "Dow Jones Industrial",
      change: -2.6,
      changeStr: "-2.6",
      bias: "BEARISH",
      sparkline: [43500, 43300, 43150, 43250, 42950, 42800, 42700, 42780, 42550, 42400],
      rationale: "Dow pulls back (-2.6%) amid earnings dispersion, industrial margin compression, and institutional de-risking.",
      drivers: [
        "Earnings: Mixed corporate quarterly results in manufacturing and healthcare",
        "Macro: Uncertainty surrounding central bank rate trajectory",
        "Technicals: Lower highs formation on hourly timeframes"
      ],
      sources: ["Wall Street Journal", "Economic Times", "MarketWatch"],
      catalyst: {
        headline: "US markets consolidate as investors digest earnings and Fed rate trajectory",
        source: "Economic Times",
        sentiment: "BEARISH",
        publishedAt: "3h ago",
        url: "https://economictimes.indiatimes.com",
        impact: "HIGH",
      },
    },
    {
      id: "globalrisk",
      symbol: "GLOBALRISK",
      name: "Global Risk Composite",
      change: -4.0,
      changeStr: "-4.0",
      bias: "BEARISH",
      sparkline: [105, 103, 102, 102.5, 100, 98.5, 98, 97.5, 96, 95],
      rationale: "Risk appetite composite declines (-4.0%) indicating widespread global institutional de-risking and defensive positioning into cash.",
      drivers: [
        "Cross-Asset: Simultaneous sell-off in growth equities, metals, and crypto",
        "Volatility: Global FX and bond volatility indexes testing multi-week highs",
        "Liquidity: Re-allocation towards money market funds and short-term paper"
      ],
      sources: ["Bank for International Settlements (BIS)", "Livemint Macro", "Reuters"],
      catalyst: {
        headline: "Geopolitical risk premium elevates defensive positioning across equities",
        source: "Livemint",
        sentiment: "BEARISH",
        publishedAt: "4h ago",
        url: "https://www.livemint.com",
        impact: "HIGH",
      },
    },
  ],
  trendActivity: {
    bullish: { count: 4, percent: 33 },
    bearish: { count: 6, percent: 50 },
    neutral: { count: 1, percent: 8 },
    volatile: { count: 1, percent: 8 },
  },
  recentSignals: [
    { symbol: "NIFTY", change: "+2.8", type: "Bullish", direction: "up" },
    { symbol: "SENSEX", change: "+3.4", type: "Bullish", direction: "up" },
    { symbol: "SILVER", change: "-4.5", type: "Bearish", direction: "down" },
    { symbol: "GLOBALRISK", change: "-4.0", type: "Bearish", direction: "down" },
  ],
  keyHighlights: {
    topGainer: { symbol: "SENSEX", change: "+3.4" },
    topLoser: { symbol: "SILVER", change: "-4.5" },
    marketBias: "BEARISH",
  },
  newsSentiment: {
    overallSentiment: "NEUTRAL",
    sentimentRating: 6.4,
    ratingLabel: "Neutral",
    sentimentScore: 20,
    totalArticles: 35,
    bullishCount: 10,
    bearishCount: 3,
    neutralCount: 22,
    ratingExplanation: "Market sentiment rated 6.4/10 based on live articles from Moneycontrol, Economic Times & Livemint.",
    affectedKeySectors: ["Banking", "IT & Tech", "Metals", "Auto"],
    topBullishHeadlines: ["Steel stocks rally as govt extends MIP on 66 steel products"],
    topBearishHeadlines: ["Dalal Street Weak Ahead: Nifty stands on firmer footing"],
  },
  latestNews: [
    {
      headline: "Sensex, Nifty hold steady; Banking, Metals lead early trade gains",
      source: "Economic Times",
      url: "https://economictimes.indiatimes.com",
      publishedAt: "12m ago",
      sentiment: "BULLISH",
      impact: "HIGH",
      relatedSymbols: ["NIFTY", "SENSEX", "BANKNIFTY"],
    },
    {
      headline: "Muthoot Finance Q2 consolidated profit jumps 36% YoY to Rs 3,278 crore",
      source: "Moneycontrol",
      url: "https://www.moneycontrol.com",
      publishedAt: "25m ago",
      sentiment: "BULLISH",
      impact: "MEDIUM",
      relatedSymbols: ["MUTHOOTFIN", "BANKNIFTY"],
    },
    {
      headline: "Crude oil trades range-bound amid demand checks and OPEC supply signals",
      source: "Livemint",
      url: "https://www.livemint.com",
      publishedAt: "40m ago",
      sentiment: "NEUTRAL",
      impact: "MEDIUM",
      relatedSymbols: ["CRUDEOIL"],
    },
    {
      headline: "Global tech stocks consolidate as US bond yields tick higher ahead of macro data",
      source: "Economic Times",
      url: "https://economictimes.indiatimes.com",
      publishedAt: "1h ago",
      sentiment: "BEARISH",
      impact: "HIGH",
      relatedSymbols: ["NASDAQ", "DJI"],
    },
  ],
};

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
   * Fetch The God's Eye - Observer Intelligence Dashboard Data
   */
  async getObserverIntelligence(): Promise<ObserverIntelligenceData> {
    const data = await fetchFromBackend<ObserverIntelligenceData>('/api/market/observer');
    return data || MOCK_OBSERVER_DATA;
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
