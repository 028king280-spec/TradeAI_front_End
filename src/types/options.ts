export type IndexSymbol = 'NIFTY 50' | 'SENSEX' | 'BANK NIFTY';
export type SentimentDirection = 'BULLISH' | 'BEARISH' | 'NEUTRAL';
export type OptionBias = 'CE' | 'PE';
export type DataStatus = 'LIVE' | 'STALE' | 'MOCK' | 'UNAVAILABLE';

export interface IndexQuoteCard {
  symbol: string;
  name: string;
  currentValue: number;
  change: number;
  changePercent: number;
  dayHigh: number;
  dayLow: number;
  openPrice: number;
  previousClose: number;
  trend: 'Bullish' | 'Bearish' | 'Neutral';
  marketStatus: 'OPEN' | 'CLOSED';
  dataStatus: DataStatus;
  timestamp: string;
  sparkline: number[];
}

export interface GreekDetails {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
}

export interface OptionContractDetails {
  ltp: number;
  oi: number;
  changeInOi: number;
  volume: number;
  iv: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  moneyness: 'ITM' | 'ATM' | 'OTM';
  bid: number;
  ask: number;
  spread: number;
}

export interface OptionStrikeRow {
  strike: number;
  isAtm: boolean;
  ce: OptionContractDetails;
  pe: OptionContractDetails;
}

export interface PcrData {
  pcrOi: number;
  pcrVolume?: number;
  sentiment: string;
  signal: SentimentDirection;
  interpretation: string;
  scopeDescription: string;
  putOiTotal: number;
  callOiTotal: number;
}

export interface MaxPainData {
  maxPainStrike: number | null;
  minCumulativeLoss: number | null;
  strikesEvaluated: number;
  isDescriptiveOnly: boolean;
  disclaimer: string;
}

export interface OiAnalysisData {
  callWall: number | null;
  callWallOi: number;
  putWall: number | null;
  putWallOi: number;
  maxCeAdditionStrike: number | null;
  maxCeAdditionOi: number;
  maxPeAdditionStrike: number | null;
  maxPeAdditionOi: number;
  totalCeOi: number;
  totalPeOi: number;
  totalCeChgOi: number;
  totalPeChgOi: number;
  positioning: string;
  implication: string;
}

export interface OptionChainResponse {
  symbol: string;
  underlyingPrice: number;
  underlyingChange: number;
  atmStrike: number;
  strikeStep: number;
  lotSize: number;
  selectedExpiry: string;
  availableExpiries: string[];
  filterMode: 'ATM' | 'WIDE';
  pcr: PcrData;
  maxPain: MaxPainData;
  oiAnalysis: OiAnalysisData;
  strikes: OptionStrikeRow[];
  totalCallOi: number;
  totalPutOi: number;
  dataStatus: DataStatus;
  dataTimestamp: string;
  analysisTimestamp: string;
  provider: string;
}

export interface SupportResistanceItem {
  role: string;
  label: string;
  price: number;
  levelType: 'PRICE_ACTION' | 'OPTION_CHAIN' | 'SPOT';
  calculationMethod: string;
  strength: 'Major' | 'Moderate' | 'Minor';
  distancePercent: number;
  confirmationStatus: 'Confirmed' | 'Tested' | 'Untested' | 'Active';
  timestamp: string;
}

export interface SupportResistanceLadder {
  support1: SupportResistanceItem;
  support2: SupportResistanceItem;
  support3: SupportResistanceItem;
  resistance1: SupportResistanceItem;
  resistance2: SupportResistanceItem;
  resistance3: SupportResistanceItem;
  ladder: SupportResistanceItem[];
}

export interface ScenarioItem {
  title: string;
  triggerCondition: string;
  targetZone: string;
  invalidationLevel?: number;
  confirmationRequirements?: string[];
  supportingEvidence?: string[];
  estimatedProbability: string;
}

export interface SessionOutlookData {
  symbol: string;
  mode: 'TODAY' | 'NEXT_SESSION';
  sessionLabel: string;
  targetSessionDate: string;
  currentPrice: number;
  expectedRange: {
    likelyHigh: number;
    likelyLow: number;
    extremeHigh: number;
    extremeLow: number;
    baseCaseRange: string;
    expectedMovePoints: number;
  };
  triggers: {
    bullishBreakoutTrigger: number;
    bearishBreakdownTrigger: number;
    equilibrium: number;
  };
  probabilities: {
    upsideProbability: number;
    downsideProbability: number;
    neutralProbability: number;
  };
  scenarios: {
    bullish: ScenarioItem;
    baseCase: ScenarioItem;
    bearish: ScenarioItem;
  };
  catalystsAndRiskFactors: string[];
  disclaimer: string;
}

export interface OptionsMarketSentiment {
  symbol: string;
  overallSentiment: SentimentDirection;
  sentimentScore: number;
  trendStrength: string;
  confidence: 'High' | 'Medium' | 'Low';
  bullishEvidenceScore: number;
  bearishEvidenceScore: number;
  supportingFactors: string[];
  conflictingFactors: string[];
  reasonsToAvoidTrade: string[];
  confirmationLevel: string;
  importantPriceTriggers: {
    bullishConfirmation: number;
    bearishConfirmation: number;
    vwapEquilibrium: number;
  };
  criticalDerivativeNotice: string;
}

export interface DetectedChartPattern {
  patternName: string;
  timeframe: string;
  detectionTimestamp: string;
  interpretation: SentimentDirection;
  confirmed: boolean;
  relevantPriceLevels: Record<string, number>;
  confirmationCondition: string;
  invalidationCondition: string;
  confidence: string;
  description: string;
}

export interface OptionTradeSetup {
  index: string;
  bias: OptionBias;
  biasLabel: string;
  contractSymbol: string;
  strike: number;
  expiry: string;
  currentPremium: number;
  entryRange: string;
  stopLoss: number;
  target1: number;
  target2: number;
  target3: number;
  riskRewardRatio: string;
  maxRiskPerLot: number;
  potentialGainPerLot: number;
  greeks: {
    delta: number;
    gamma: number;
    thetaPerDay: number;
    vega: number;
  };
  iv: number;
  liquidity: string;
  openInterest: number;
  changeInOi: number;
  underlyingTrigger: string;
  invalidationCondition: string;
  supportingReasons: string[];
  disclaimer: string;
}

export interface TodayOptionsSetupsResult {
  symbol: string;
  hasQualifiedSetups: boolean;
  statusMessage: string;
  disqualificationReasons?: string[];
  timestamp: string;
  setups: OptionTradeSetup[];
  advice?: string;
}

export interface NextSessionOpeningScenario {
  name: string;
  threshold?: number;
  range?: string;
  probability: string;
  description: string;
  actionableTakeaway: string;
}

export interface NextSessionOpeningOutlook {
  symbol: string;
  targetSessionDate: string;
  previousClose: number;
  expectedOpeningRange: {
    low: number;
    high: number;
    midpoint: number;
    rangeString: string;
  };
  estimatedGap: {
    points: number;
    percent: number;
    direction: 'GAP_UP' | 'FLAT' | 'GAP_DOWN' | string;
    summary: string;
  };
  scenarios: {
    bullishGap: NextSessionOpeningScenario;
    flatOpening: NextSessionOpeningScenario;
    bearishGap: NextSessionOpeningScenario;
  };
  confidence: string;
  supportingEvidence: string[];
  keyInvalidationConditions: string[];
  disclaimer: string;
  timestamp: string;
}

export interface QualifiedNextSessionSetup {
  index: string;
  optionType: 'CE' | 'PE';
  biasLabel: string;
  contractSymbol: string;
  strike: number;
  expiry: string;
  lastVerifiedPremium: number;
  suggestedEntryRange: string;
  entryConfirmationCondition: string;
  stopLossPremium: number;
  target1Premium: number;
  target2Premium: number;
  target3Premium: number;
  riskRewardRatio: string;
  estimatedHoldingHorizon: string;
  underlyingTrigger: string;
  invalidationCondition: string;
  doNotChaseThreshold: string;
  liquidityAssessment: string;
  contractOpenInterest: number;
  greeks: {
    delta: number;
    thetaPerDay: number;
    ivPercent: number;
  };
  financialImpact: {
    lotSize: number;
    maxRiskINR: number;
    potentialRewardINR: number;
  };
  reasonsForSelection: string[];
  dataTimestamp: string;
  analysisTimestamp: string;
}

export interface NextSessionRecommendation {
  symbol: string;
  targetSessionDate: string;
  stage: 'STAGE_1_PRE_MARKET' | 'STAGE_2_LIVE_CONFIRMED' | string;
  stageLabel: string;
  hasQualifiedRecommendation: boolean;
  decision: 'QUALIFIED' | 'NO TRADE';
  decisionBadge: string;
  reasonsForNoTrade?: string[];
  recommendation: QualifiedNextSessionSetup | null;
  openingOutlook: NextSessionOpeningOutlook;
  riskRules: {
    maxRiskPerLot: string;
    timeBasedExit: string;
    reanalysisRequired: string;
  };
  disclaimer: string;
  dataTimestamp: string;
  analysisTimestamp: string;
  provider?: string;
  dataStatus?: DataStatus;
}

export interface NextSessionBacktestResult {
  symbol: string;
  samplePeriodSessions: number;
  validationMethod: string;
  metrics: {
    winRate: string;
    profitFactor: number;
    totalSimulatedTrades: number;
    winningTrades: number;
    losingTrades: number;
    noTradePreservedSessions: number;
    expectancyRMultiple: string;
    netPnLINR: string;
    maxDrawdownINR: string;
    openingGapDirectionalAccuracy: string;
    openingRangeForecastMAE: string;
  };
  frictionAssumptions: {
    brokeragePerRoundtrip: string;
    slippagePerTrade: string;
    lotSize: number;
  };
  volatilityRegimePerformance: Array<{
    regime: string;
    winRate: string;
    trades: number;
    expectancy: string;
  }>;
  equityCurveSample: number[];
  disclaimer: string;
}

export interface IndexAnalysisFullResponse {
  symbol: string;
  quote: Record<string, any>;
  marketState?: any;
  supportResistance: SupportResistanceLadder;
  sentiment: OptionsMarketSentiment;
  todayOutlook: SessionOutlookData;
  nextSessionOutlook: SessionOutlookData;
  nextSessionOpeningOutlook?: NextSessionOpeningOutlook;
  nextSessionRecommendation?: NextSessionRecommendation;
  patterns: DetectedChartPattern[];
  todayOptionsSetups: TodayOptionsSetupsResult;
  optionChainSummary: {
    pcr: PcrData;
    maxPain: MaxPainData;
    callWall: number | null;
    putWall: number | null;
  };
  provider: string;
  dataStatus: DataStatus;
  dataTimestamp: string;
  analysisTimestamp: string;
  disclaimer: string;
}

export interface OptionsOverviewResponse {
  indices: IndexQuoteCard[];
  marketSentiment: OptionsMarketSentiment;
  nextSessionOpeningOutlook?: NextSessionOpeningOutlook;
  nextSessionRecommendation?: NextSessionRecommendation;
  vix: {
    value: number;
    status: string;
  };
  marketStatus: 'OPEN' | 'CLOSED';
  provider: string;
  dataStatus: DataStatus;
  dataTimestamp: string;
  analysisTimestamp: string;
  disclaimer: string;
}

