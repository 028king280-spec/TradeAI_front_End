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

const API_BASE_URL = typeof window !== 'undefined'
  ? ''
  : (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000');

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
          currentValue: 23820.00,
          change: 14.20,
          changePercent: 0.06,
          dayHigh: 23946.35,
          dayLow: 23696.15,
          openPrice: 23742.25,
          previousClose: 23810.85,
          trend: 'Bullish',
          marketStatus: 'OPEN',
          dataStatus: 'MOCK',
          timestamp: '04 Nov 2026, 12:50 PM IST',
          sparkline: [23696, 23742, 23800, 23820],
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

  private cleanSymbol(symbol?: string): string {
    return (symbol && typeof symbol === 'string' ? symbol : 'NIFTY50').replace(/\s+/g, '').toUpperCase();
  }

  async getIndexAnalysis(symbol: string): Promise<IndexAnalysisFullResponse | null> {
    const sym = this.cleanSymbol(symbol);
    return await this.fetchJson<IndexAnalysisFullResponse>(`/api/options/${sym}/analysis`);
  }

  async getCandles(
    symbol: string,
    timeframe: string = '15m',
    mode: 'spot' | 'premium' = 'spot',
    strike?: number,
    optionType: 'CE' | 'PE' = 'CE'
  ) {
    const sym = this.cleanSymbol(symbol);
    let url = `/api/options/${sym}/candles?timeframe=${timeframe}&mode=${mode}`;
    if (strike) url += `&strike=${strike}`;
    if (optionType) url += `&option_type=${optionType}`;
    return await this.fetchJson<any>(url);
  }

  async getOptionChain(symbol: string, expiry?: string, filterMode: 'ATM' | 'WIDE' = 'ATM'): Promise<OptionChainResponse | null> {
    const sym = this.cleanSymbol(symbol);
    let url = `/api/options/${sym}/option-chain?filter_mode=${filterMode}`;
    if (expiry) url += `&expiry=${encodeURIComponent(expiry)}`;
    return await this.fetchJson<OptionChainResponse>(url);
  }

  async getSetups(symbol: string): Promise<{ todayOptionsSetups: TodayOptionsSetupsResult } | null> {
    const sym = this.cleanSymbol(symbol);
    return await this.fetchJson<{ todayOptionsSetups: TodayOptionsSetupsResult }>(`/api/options/${sym}/setups`);
  }

  async getSmc(symbol: string): Promise<{ smcAnalysis: any } | null> {
    const sym = this.cleanSymbol(symbol);
    return await this.fetchJson<{ smcAnalysis: any }>(`/api/options/${sym}/smc`);
  }

  async getOutlook(symbol: string): Promise<{ todayOutlook: SessionOutlookData; nextSessionOutlook: SessionOutlookData } | null> {
    const sym = this.cleanSymbol(symbol);
    return await this.fetchJson<{ todayOutlook: SessionOutlookData; nextSessionOutlook: SessionOutlookData }>(`/api/options/${sym}/outlook`);
  }

  async getPatterns(symbol: string): Promise<{ patterns: DetectedChartPattern[] } | null> {
    const sym = this.cleanSymbol(symbol);
    return await this.fetchJson<{ patterns: DetectedChartPattern[] }>(`/api/options/${sym}/patterns`);
  }

  async getSentiment(symbol: string): Promise<{ sentiment: OptionsMarketSentiment } | null> {
    const sym = this.cleanSymbol(symbol);
    return await this.fetchJson<{ sentiment: OptionsMarketSentiment }>(`/api/options/${sym}/sentiment`);
  }

  async getNextSessionOpeningOutlook(symbol: string): Promise<{ openingOutlook: NextSessionOpeningOutlook } | null> {
    const sym = this.cleanSymbol(symbol);
    return await this.fetchJson<{ openingOutlook: NextSessionOpeningOutlook }>(`/api/options/${sym}/next-session/opening-outlook`);
  }

  async getNextSessionRecommendation(symbol: string, liveOpenPrice?: number): Promise<NextSessionRecommendation | null> {
    const sym = this.cleanSymbol(symbol);
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
    const sym = this.cleanSymbol(symbol);
    const url = `/api/options/${sym}/next-session/backtest?lookback_sessions=${lookback}&brokerage_per_order=${brokerage}&slippage_pct=${slippage}`;
    return await this.fetchJson<NextSessionBacktestResult>(url);
  }

  async getIctAnalysis(symbol: string, timeframe: string = '15m'): Promise<any | null> {
    const sym = this.cleanSymbol(symbol);
    return await this.fetchJson<any>(`/api/options/${sym}/ict-analysis?timeframe=${timeframe}`);
  }

  async getMultiTimeframe(symbol: string): Promise<any | null> {
    const sym = this.cleanSymbol(symbol);
    return await this.fetchJson<any>(`/api/options/${sym}/multi-timeframe`);
  }

  async runIctBacktest(symbol: string, payload: any = {}): Promise<any | null> {
    const sym = this.cleanSymbol(symbol);
    try {
      const res = await fetch(`${API_BASE_URL}/api/options/${sym}/backtest-ict`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) return null;
      return await res.json();
    } catch (err) {
      console.warn(`ICT backtest failed for ${sym}:`, err);
      return null;
    }
  }
}

export const optionsService = new OptionsService();

