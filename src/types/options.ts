export type IndexSymbol = 'NIFTY 50' | 'SENSEX' | 'BANK NIFTY' | 'FINNIFTY';
export type SentimentDirection = 'BULLISH' | 'BEARISH' | 'NEUTRAL';
export type OptionBias = 'CE' | 'PE';
export type DataStatus =
  | 'LIVE'
  | 'STALE'
  | 'MOCK'
  | 'UNAVAILABLE'
  | 'MARKET_CLOSED'
  | 'DATA_OFFLINE'
  | 'DATA_UNAVAILABLE'
  | 'STALE_TICK'
  | 'VERIFIED_LIVE'
  | 'VERIFIED_EOD';

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
  moneyness?: 'ITM' | 'ATM' | 'OTM';
  smcModel?: string;
  contractSymbol: string;
  strike: number;
  expiry: string;
  currentPremium: number;
  entryRange: string;
  stopLoss: number;
  target1: number;
  target2: number;
  target3: number;
  targetProbabilities?: {
    target1?: { price: number; gainPct: number; probabilityPct: number; likelihood: string; badge: string; description: string };
    target2?: { price: number; gainPct: number; probabilityPct: number; likelihood: string; badge: string; description: string };
    target3?: { price: number; gainPct: number; probabilityPct: number; likelihood: string; badge: string; description: string };
  };
  t1Probability?: number;
  t2Probability?: number;
  t3Probability?: number;
  t1GainPct?: number;
  t2GainPct?: number;
  t3GainPct?: number;
  t1Likelihood?: 'HIGH' | 'MODERATE' | 'LOW';
  t2Likelihood?: 'HIGH' | 'MODERATE' | 'LOW';
  t3Likelihood?: 'HIGH' | 'MODERATE' | 'LOW';
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
  dataStatus?: string;
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
  smcAnalysis?: SmcAnalysisData;
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

export interface SmcDealingRange {
  rangeHigh: number;
  rangeLow: number;
  equilibrium: number;
  currentPositionPct: number;
  regime: 'PREMIUM' | 'DISCOUNT' | 'EQUILIBRIUM';
  recommendation: string;
}

export interface SmcLiquidityLevel {
  name: string;
  level: number;
  significance: string;
}

export interface SmcLiquidityPools {
  bslLevels: SmcLiquidityLevel[];
  sslLevels: SmcLiquidityLevel[];
  equalHighs: { level: number; type: string; description: string }[];
  equalLows: { level: number; type: string; description: string }[];
}

export interface SmcExecutionModel {
  modelName: string;
  status: 'QUALIFIED' | 'WATCHLIST';
  bias: 'BULLISH' | 'BEARISH';
  instrument: string;
  triggerStep: string;
  entryZone: string;
  stopLoss: number;
  target1: number;
  target2: number;
  riskRewardRatio: string;
  invalidation: string;
  optionsTranslation: string;
}

export interface IctMarketStructurePoint {
  index: number;
  type: 'SWING_HIGH' | 'SWING_LOW';
  price: number;
  timestamp: string;
  timeframe: string;
  status: 'CONFIRMED' | 'PENDING';
  label: 'HH' | 'HL' | 'LH' | 'LL';
  structureType: 'INTERNAL' | 'EXTERNAL';
}

export interface IctBosChochEvent {
  type: 'BULLISH_BOS' | 'BEARISH_BOS' | 'BULLISH_CHOCH' | 'BEARISH_CHOCH' | 'BULLISH_MSS' | 'BEARISH_MSS';
  timeframe: string;
  brokenLevel: number;
  breakPrice: number;
  brokenTimestamp: string;
  breakTimestamp: string;
  status: 'CONFIRMED' | 'PENDING';
  displacementRatio: number;
  volumeRatio: number;
  wickRejectionPct: number;
  description: string;
}

export interface IctMarketStructureData {
  timeframe: string;
  status: string;
  structureBias: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  externalSwings: IctMarketStructurePoint[];
  internalSwings: IctMarketStructurePoint[];
  classifiedPoints: IctMarketStructurePoint[];
  bosChoch: {
    events: IctBosChochEvent[];
    currentStructure: string;
    lastBos: IctBosChochEvent | null;
    lastChoch: IctBosChochEvent | null;
  };
  summary: string;
}

export interface IctLiquidityPool {
  name: string;
  level: number;
  type: 'BSL' | 'SSL';
  tier: 'MAJOR_EXTERNAL' | 'SESSION_INTRADAY' | 'INTERNAL_INDUCEMENT';
  description: string;
}

export interface IctLiquiditySweep {
  type: 'SWEEP_WITH_RECLAIM' | 'SWEEP_WITHOUT_RECLAIM';
  poolType: 'BSL' | 'SSL';
  level: number;
  extremePrice: number;
  closePrice: number;
  timestamp: string;
  bias: 'BULLISH' | 'BEARISH';
  status: string;
  reclaimDelta: number;
  wickRatio: number;
  title: string;
  description: string;
  invalidationLevel: number;
}

export interface IctLiquidityHeatmapZone {
  name: string;
  level: number;
  type: 'BSL' | 'SSL';
  densityScore: number;
  distancePts: number;
  distancePct: number;
  zoneBand: [number, number];
  colorIntensity: 'HIGH' | 'MEDIUM' | 'LOW';
}

export interface IctFairValueGap {
  id: string;
  type: 'BULLISH_FVG' | 'BEARISH_FVG';
  timeframe: string;
  barIndex: number;
  timestamp: string;
  top: number;
  bottom: number;
  ce50: number;
  gapSize: number;
  displacementRatio: number;
  status: 'FRESH' | 'PARTIALLY_FILLED' | 'FULLY_FILLED' | 'INVERSE_FVG';
  isMitigated: boolean;
  isInverse: boolean;
  bias: string;
  highestRetest?: number;
  lowestRetest?: number;
  description: string;
}

export interface IctOrderBlock {
  id: string;
  type: 'BULLISH_OB' | 'BEARISH_OB' | 'BEARISH_BREAKER' | 'BULLISH_BREAKER';
  originalType: string;
  timeframe: string;
  barIndex: number;
  timestamp: string;
  top: number;
  bottom: number;
  midpoint: number;
  bias: 'BULLISH' | 'BEARISH';
  status: 'VALID_ACTIVE' | 'FLIPPED_BREAKER' | 'MITIGATED';
  isValid: boolean;
  description: string;
}

export interface IctScorecardFactor {
  factor: string;
  score: number;
  maxScore: number;
  status: 'PASS' | 'PARTIAL' | 'FAIL';
}

export interface IctScorecardData {
  overallScore: number;
  maxPossibleScore: number;
  convictionGrade: string;
  recommendation: string;
  factors: IctScorecardFactor[];
  missingConfirmations: string[];
  conflictingSignals: string[];
  isTradeable: boolean;
  disclaimer: string;
}

export interface IctMultiTimeframeData {
  overallAlignment: string;
  headline: string;
  explanation: string;
  isTradeable: boolean;
  confluenceScore: number;
  bullishTfCount: number;
  bearishTfCount: number;
  totalTfEvaluated: number;
  timeframeBiases: Record<string, string>;
  htfBias: string;
  intradayBias: string;
  execBias: string;
}

export interface IctAiReportData {
  reportText: string;
  structured: Record<string, any>;
}

export interface AdvancedIctData {
  structure?: IctMarketStructureData;
  liquidity?: {
    pools: {
      bslPools: IctLiquidityPool[];
      sslPools: IctLiquidityPool[];
      equalHighs: any[];
      equalLows: any[];
    };
    sweeps: IctLiquiditySweep[];
    heatmap: IctLiquidityHeatmapZone[];
  };
  fvgAndOrderBlocks?: {
    fairValueGaps: IctFairValueGap[];
    orderBlocks: IctOrderBlock[];
    activeFvgs: IctFairValueGap[];
    activeBlocks: IctOrderBlock[];
  };
  scorecard?: IctScorecardData;
  aiReport?: IctAiReportData;
  fivePartAnalysis?: Record<string, any>;
}

export interface SmcAnalysisData {
  dealingRange: SmcDealingRange;
  liquidityPools: SmcLiquidityPools;
  recentSweeps: any[];
  fairValueGaps: any[];
  orderBlocks: any[];
  executionModels: {
    modelA?: SmcExecutionModel;
    modelB?: SmcExecutionModel;
    modelC?: SmcExecutionModel;
    activeSetup?: SmcExecutionModel;
  };
  advancedIct?: AdvancedIctData;
  disclaimer: string;
}

