export type MarketTrend = 'Bullish' | 'Bearish' | 'Neutral';
export type SignalType = 'CALL' | 'PUT' | 'NEUTRAL';
export type MarketStatus = 'OPEN' | 'CLOSED';
export type Exchange = 'NSE' | 'BSE';
export type CapCategory = 'Large Cap' | 'Mid Cap' | 'Small Cap';

export interface MarketIndex {
  symbol: string;
  name: string;
  currentValue: number;
  change: number;
  changePercent: number;
  dayHigh: number;
  dayLow: number;
  trend: MarketTrend;
  sparkline: number[];
  volatilityStatus?: 'Low' | 'Moderate' | 'High' | 'Elevated';
}

export interface MarketBreadth {
  advancing: number;
  declining: number;
  unchanged: number;
  ratio: number;
}

export interface MarketSentiment {
  score: number; // 0-100
  status: MarketTrend;
  confidence: 'Low' | 'Medium' | 'High';
  marketBreadth: MarketBreadth;
  marketMomentum: 'Strong Bullish' | 'Bullish' | 'Neutral' | 'Bearish' | 'Strong Bearish';
  volatility: 'Low' | 'Moderate' | 'High' | 'Extreme';
  liquidityCondition: 'Optimal' | 'Average' | 'Tight';
  lastUpdated: string;
}

export interface StockPriceRange {
  extremeLow: number;
  likelyLow: number;
  currentPrice: number;
  likelyHigh: number;
  extremeHigh: number;
}

export interface ScenarioDetail {
  title: string;
  type: 'bullish' | 'base' | 'bearish';
  trigger: string;
  expectedZone: string;
  conditions: string[];
  confidence: 'High' | 'Medium' | 'Low' | 'Medium/High';
  explanation: string;
}

export interface SupportResistanceLevel {
  label: 'Resistance 2' | 'Resistance 1' | 'Current' | 'Support 1' | 'Support 2' | 'Support 3';
  price: number;
  strength: 'Major' | 'Moderate' | 'Minor';
  distancePercent: number;
  implication: 'Bearish Rejection Risk' | 'Key Resistance' | 'Current Trading Zone' | 'Immediate Support' | 'Crucial Demand Zone' | 'Critical Breakdown Level';
}

export interface IndicatorDetail {
  name: string;
  currentValue: string | number;
  signal: 'Bullish' | 'Bearish' | 'Neutral';
  interpretation: string;
}

export interface TechnicalIndicators {
  rsi: IndicatorDetail;
  macd: IndicatorDetail;
  ema20: IndicatorDetail;
  ema50: IndicatorDetail;
  ema200: IndicatorDetail;
  vwap: IndicatorDetail;
  atr: IndicatorDetail;
  volume: IndicatorDetail;
  momentum: IndicatorDetail;
  priceStructure: IndicatorDetail;
}

export interface VolumeAnalysis {
  currentVolume: string;
  averageVolume: string;
  volumeRatio: number;
  volumeTrend: 'Above Average' | 'Average' | 'Below Average' | 'Surging';
  intradayBars: { time: string; volume: number; isUp: boolean }[];
}

export interface SectorAnalysis {
  sectorName: string;
  sectorTrend: MarketTrend;
  sectorPerformance: number;
  relativeStrength: 'Strong' | 'Moderate' | 'Lagging' | 'Neutral';
  stockVsSector: string;
}

export interface MarketContext {
  nifty50Trend: MarketTrend;
  bankNiftyTrend: MarketTrend;
  marketBreadthStatus: 'Positive' | 'Neutral' | 'Negative';
  indiaVixStatus: 'Low' | 'Moderate' | 'High' | 'Elevated';
  overallMarketSupport: 'Strong' | 'Moderate' | 'Weak';
}

export interface NewsEvent {
  id: string;
  time: string;
  headline: string;
  impact: 'High' | 'Medium' | 'Low';
  sentiment: 'Positive' | 'Negative' | 'Neutral';
}

export interface ScoreCategory {
  category: string;
  score: number;
  maxScore: number;
}

export interface StockAnalysisScore {
  totalScore: number; // 0-100
  status: string;
  categories: ScoreCategory[];
}

export interface QualificationPillar {
  pillar: string;
  status: 'Confirmed' | 'Positive' | 'Neutral' | 'Caution' | 'Negative';
  explanation: string;
}

export interface AIInsight {
  symbol: string;
  headlineQuestion: string;
  explanation: string;
  qualificationPillars: QualificationPillar[];
  risks: string[];
  invalidationTriggers: string[];
  scenarios: ScenarioDetail[];
  aiConfidence: {
    score: number;
    level: 'High' | 'Medium' | 'Low';
    note: string;
  };
}

export interface CandlePoint {
  time: string;
  price: number;
  vwap: number;
  ema20: number;
  ema50: number;
  volume: number;
  support?: number;
  resistance?: number;
  expectedHigh?: number;
  expectedLow?: number;
}

export interface StockAnalysis {
  symbol: string;
  companyName: string;
  exchange: Exchange;
  category: CapCategory;
  sector: string;
  currentPrice: number;
  change: number;
  changePercent: number;
  dayHigh: number;
  dayLow: number;
  volume: string;
  analysisTimestamp: string;
  trend: MarketTrend;
  analysisScore: StockAnalysisScore;
  confidence: number; // 0-100
  expectedHigh: {
    min: number;
    max: number;
  };
  expectedLow: {
    min: number;
    max: number;
  };
  probabilities: {
    upside: number;
    downside: number;
  };
  currentBias: MarketTrend;
  priceRange: StockPriceRange;
  bullishScenario: ScenarioDetail;
  baseScenario: ScenarioDetail;
  bearishScenario: ScenarioDetail;
  outlookChanges: {
    bullishConfirmation: string;
    bearishConfirmation: string;
    risks: string[];
  };
  supportResistance: SupportResistanceLevel[];
  technicalIndicators: TechnicalIndicators;
  volumeAnalysis: VolumeAnalysis;
  marketContext: MarketContext;
  sectorAnalysis: SectorAnalysis;
  news: NewsEvent[];
  aiInsights: AIInsight;
  summary: string;
  chartData: {
    '1D': CandlePoint[];
    '5D': CandlePoint[];
    '1M': CandlePoint[];
    '3M': CandlePoint[];
    '6M': CandlePoint[];
    '1Y': CandlePoint[];
  };
}

export interface SignalCandidate {
  rank: number;
  companyName: string;
  symbol: string;
  exchange: Exchange;
  currentPrice: number;
  change: number;
  changePercent: number;
  trend: MarketTrend;
  signalType: SignalType;
  analysisScore: number;
  confidence: number;
  expectedHigh: number;
  expectedLow: number;
  sparkline: number[];
  qualified: boolean;
}

export interface SectorHeatmapItem {
  sector: string;
  performancePercent: number;
  strength: 'Strong' | 'Moderate' | 'Weak' | 'Negative';
  topStock: string;
  advancers: number;
  decliners: number;
}

export interface RecentAISignal {
  id: string;
  time: string;
  symbol: string;
  companyName: string;
  signal: 'Bullish' | 'Bearish';
  score: number;
  expectedMove: string;
  status: 'Active' | 'Target Met' | 'Trailing';
}

export interface MarketDriver {
  id: string;
  title: string;
  value: string;
  subtext: string;
  trend: MarketTrend;
  indicator: 'positive' | 'negative' | 'neutral';
}

export interface PaperPosition {
  id: string;
  symbol: string;
  companyName: string;
  signalType: 'CALL' | 'PUT';
  entryPrice: number;
  currentPrice: number;
  quantity: number;
  investedAmount: number;
  targetPrice: number;
  stopLossPrice: number;
  pnl: number;
  pnlPercent: number;
  openedAt: string;
}

export interface PaperTradeHistory {
  id: string;
  symbol: string;
  companyName: string;
  signalType: 'CALL' | 'PUT';
  entryPrice: number;
  exitPrice: number;
  quantity: number;
  investedAmount: number;
  realizedPnl: number;
  realizedPnlPercent: number;
  exitReason: 'Target Met' | 'Stop Loss' | 'Manual Square Off';
  openedAt: string;
  closedAt: string;
}

export interface TelegramAlertConfig {
  botToken: string;
  chatId: string;
  enabled: boolean;
  minScore: number;
  notifyCall: boolean;
  notifyPut: boolean;
  lastTestedAt?: string;
}

