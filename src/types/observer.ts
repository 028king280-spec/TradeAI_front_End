export interface NewsCatalyst {
  headline: string;
  source: string;
  sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | string;
  publishedAt: string;
  url?: string;
  impact?: string;
}

export interface LiveNewsFeedItem {
  id?: string;
  headline: string;
  source: string;
  url: string;
  publishedAt: string;
  sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | string;
  sentimentScore?: number;
  impact?: 'HIGH' | 'MEDIUM' | 'LOW' | string;
  relatedSymbols?: string[];
}

export interface ObserverAsset {
  id: string;
  symbol: string;
  name: string;
  change: number;
  changeStr: string;
  bias: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  sparkline: number[];
  rationale?: string;
  drivers?: string[];
  sources?: string[];
  catalyst?: NewsCatalyst;
}

export interface ObserverIntelligenceData {
  title: string;
  subtitle: string;
  marketSession: string;
  timestamp: string;
  isLive: boolean;
  marketHealth: {
    score: number;
    label: string;
  };
  marketStatus: {
    bullish: number;
    bearish: number;
    neutral: number;
  };
  fgIndex: {
    value: number;
    label: string;
    prevValue: number;
    changePercent: number;
  };
  vix: {
    value: number;
    prevValue: number;
    changePercent: number;
    sparkline: number[];
  };
  assets: ObserverAsset[];
  trendActivity: {
    bullish: { count: number; percent: number };
    bearish: { count: number; percent: number };
    neutral: { count: number; percent: number };
    volatile: { count: number; percent: number };
  };
  recentSignals: Array<{
    symbol: string;
    change: string;
    type: 'Bullish' | 'Bearish' | 'Neutral';
    direction: 'up' | 'down';
    time?: string;
  }>;
  keyHighlights: {
    topGainer: { symbol: string; change: string };
    topLoser: { symbol: string; change: string };
    marketBias: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  };
  newsSentiment?: {
    overallSentiment: string;
    sentimentRating: number;
    ratingLabel: string;
    sentimentScore: number;
    totalArticles: number;
    bullishCount: number;
    bearishCount: number;
    neutralCount: number;
    ratingExplanation: string;
    affectedKeySectors: string[];
    topBullishHeadlines: string[];
    topBearishHeadlines: string[];
  };
  latestNews?: LiveNewsFeedItem[];
}
