import {
  OptionsOverviewResponse,
  IndexAnalysisFullResponse,
  OptionChainResponse,
  TodayOptionsSetupsResult,
  SessionOutlookData,
  DetectedChartPattern,
  OptionsMarketSentiment,
  NextSessionOpeningOutlook,
  NextSessionRecommendation,
  NextSessionBacktestResult,
} from '@/types/options';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

class OptionsService {
  private async fetchJson<T>(url: string): Promise<T | null> {
    try {
      const res = await fetch(`${API_BASE_URL}${url}`, {
        cache: 'no-store',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      if (!res.ok) {
        console.warn(`Options API error ${res.status} on ${url}`);
        return null;
      }
      return (await res.json()) as T;
    } catch (err) {
      console.warn(`Options fetch failed for ${url}:`, err);
      return null;
    }
  }

  async getOverview(): Promise<OptionsOverviewResponse | null> {
    const data = await this.fetchJson<OptionsOverviewResponse>('/api/options/overview');
    if (data) return data;

    // Resilient fallback with clear MOCK dataStatus flag
    return {
      indices: [
        {
          symbol: 'NIFTY 50',
          name: 'Nifty 50 Index',
          currentValue: 24852.40,
          change: 136.20,
          changePercent: 0.55,
          dayHigh: 24890.10,
          dayLow: 24710.80,
          openPrice: 24730.00,
          previousClose: 24716.20,
          trend: 'Bullish',
          marketStatus: 'OPEN',
          dataStatus: 'MOCK',
          timestamp: '15 Oct 2026, 03:30 PM IST',
          sparkline: [24715, 24730, 24760, 24745, 24790, 24810, 24840, 24852.4],
        },
        {
          symbol: 'SENSEX',
          name: 'BSE SENSEX Index',
          currentValue: 81850.50,
          change: 420.30,
          changePercent: 0.52,
          dayHigh: 82010.20,
          dayLow: 81430.00,
          openPrice: 81490.00,
          previousClose: 81430.20,
          trend: 'Bullish',
          marketStatus: 'OPEN',
          dataStatus: 'MOCK',
          timestamp: '15 Oct 2026, 03:30 PM IST',
          sparkline: [81450, 81520, 81640, 81600, 81730, 81790, 81820, 81850.5],
        },
        {
          symbol: 'BANK NIFTY',
          name: 'Nifty Bank Index',
          currentValue: 51420.80,
          change: 312.40,
          changePercent: 0.61,
          dayHigh: 51550.00,
          dayLow: 51080.00,
          openPrice: 51120.00,
          previousClose: 51108.40,
          trend: 'Bullish',
          marketStatus: 'OPEN',
          dataStatus: 'MOCK',
          timestamp: '15 Oct 2026, 03:30 PM IST',
          sparkline: [51100, 51180, 51240, 51210, 51330, 51380, 51410, 51420.8],
        },
      ],
      marketSentiment: {
        symbol: 'NIFTY 50',
        overallSentiment: 'BULLISH',
        sentimentScore: 72,
        trendStrength: 'Strong',
        confidence: 'High',
        bullishEvidenceScore: 72.0,
        bearishEvidenceScore: 28.0,
        supportingFactors: [
          'Price sustaining above intraday VWAP, indicating institutional buying control.',
          'Put-Call Ratio (PCR) at 1.18 confirms aggressive put writing support.',
          'Bullish moving average stack (Price > EMA20 > EMA50).',
        ],
        conflictingFactors: [
          'RSI is approaching 65 (moderate resistance zone).',
        ],
        reasonsToAvoidTrade: [],
        confirmationLevel: 'Sustained trade above 24,890 level.',
        importantPriceTriggers: {
          bullishConfirmation: 24890.10,
          bearishConfirmation: 24710.80,
          vwapEquilibrium: 24825.00,
        },
        criticalDerivativeNotice: 'Underlying direction does not guarantee option profitability. Manage theta decay actively.',
      },
      vix: {
        value: 13.42,
        status: 'Moderate Volatility',
      },
      marketStatus: 'OPEN',
      provider: 'mock',
      dataStatus: 'MOCK',
      dataTimestamp: '15 Oct 2026, 03:30 PM IST',
      analysisTimestamp: '15 Oct 2026, 03:30 PM IST',
      disclaimer: 'Live market analysis only. Platform does NOT execute trades.',
    };
  }

  async getIndexAnalysis(symbol: string): Promise<IndexAnalysisFullResponse | null> {
    const sym = symbol.replace(/\s+/g, '').toUpperCase();
    return await this.fetchJson<IndexAnalysisFullResponse>(`/api/options/${sym}/analysis`);
  }

  async getCandles(symbol: string, timeframe: string = '15m') {
    const sym = symbol.replace(/\s+/g, '').toUpperCase();
    return await this.fetchJson<any>(`/api/options/${sym}/candles?timeframe=${timeframe}`);
  }

  async getOptionChain(symbol: string, expiry?: string, filterMode: 'ATM' | 'WIDE' = 'ATM'): Promise<OptionChainResponse | null> {
    const sym = symbol.replace(/\s+/g, '').toUpperCase();
    let url = `/api/options/${sym}/option-chain?filter_mode=${filterMode}`;
    if (expiry) url += `&expiry=${encodeURIComponent(expiry)}`;
    return await this.fetchJson<OptionChainResponse>(url);
  }

  async getSetups(symbol: string): Promise<{ todayOptionsSetups: TodayOptionsSetupsResult } | null> {
    const sym = symbol.replace(/\s+/g, '').toUpperCase();
    return await this.fetchJson<{ todayOptionsSetups: TodayOptionsSetupsResult }>(`/api/options/${sym}/setups`);
  }

  async getOutlook(symbol: string): Promise<{ todayOutlook: SessionOutlookData; nextSessionOutlook: SessionOutlookData } | null> {
    const sym = symbol.replace(/\s+/g, '').toUpperCase();
    return await this.fetchJson<{ todayOutlook: SessionOutlookData; nextSessionOutlook: SessionOutlookData }>(`/api/options/${sym}/outlook`);
  }

  async getPatterns(symbol: string): Promise<{ patterns: DetectedChartPattern[] } | null> {
    const sym = symbol.replace(/\s+/g, '').toUpperCase();
    return await this.fetchJson<{ patterns: DetectedChartPattern[] }>(`/api/options/${sym}/patterns`);
  }

  async getSentiment(symbol: string): Promise<{ sentiment: OptionsMarketSentiment } | null> {
    const sym = symbol.replace(/\s+/g, '').toUpperCase();
    return await this.fetchJson<{ sentiment: OptionsMarketSentiment }>(`/api/options/${sym}/sentiment`);
  }

  async getNextSessionOpeningOutlook(symbol: string): Promise<{ openingOutlook: NextSessionOpeningOutlook } | null> {
    const sym = symbol.replace(/\s+/g, '').toUpperCase();
    return await this.fetchJson<{ openingOutlook: NextSessionOpeningOutlook }>(`/api/options/${sym}/next-session/opening-outlook`);
  }

  async getNextSessionRecommendation(symbol: string, liveOpenPrice?: number): Promise<NextSessionRecommendation | null> {
    const sym = symbol.replace(/\s+/g, '').toUpperCase();
    let url = `/api/options/${sym}/next-session/recommendation`;
    if (liveOpenPrice) url += `?live_open_price=${liveOpenPrice}`;
    return await this.fetchJson<NextSessionRecommendation>(url);
  }

  async getNextSessionBacktest(
    symbol: string,
    lookback: number = 60,
    brokerage: number = 20.0,
    slippage: number = 0.05
  ): Promise<NextSessionBacktestResult | null> {
    const sym = symbol.replace(/\s+/g, '').toUpperCase();
    const url = `/api/options/${sym}/next-session/backtest?lookback_sessions=${lookback}&brokerage_per_order=${brokerage}&slippage_pct=${slippage}`;
    return await this.fetchJson<NextSessionBacktestResult>(url);
  }
}

export const optionsService = new OptionsService();

