export interface NewsItem {
  id: string;
  headline: string;
  source: string;
  url: string;
  publishedAt: string;
  retrievedAt: string;
  sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | string;
  impact: 'HIGH' | 'MEDIUM' | 'LOW' | string;
  relatedSymbols: string[];
  dataStatus: string;
  provider: string;
}

export interface NewsApiResponse {
  success: boolean;
  data: NewsItem[];
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
    lastFetchTimestamp: string | null;
    totalArticlesFetched: number;
    cacheTtlSeconds: number;
    freeTier: boolean;
    rateLimitPerMinute: string;
  };
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

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

  async getMarketNews(limit: number = 15): Promise<NewsItem[]> {
    const res = await this.fetchJson<NewsApiResponse>(`/api/news/market?limit=${limit}`);
    if (res && res.success && Array.isArray(res.data)) {
      return res.data;
    }
    return [];
  }

  async getStockNews(symbol: string, limit: number = 6): Promise<NewsItem[]> {
    const clean = encodeURIComponent(symbol.trim());
    const res = await this.fetchJson<NewsApiResponse>(`/api/news/symbol/${clean}?limit=${limit}`);
    if (res && res.success && Array.isArray(res.data)) {
      return res.data;
    }
    return [];
  }

  async searchNews(query: string, limit: number = 10): Promise<NewsItem[]> {
    const q = encodeURIComponent(query.trim());
    const res = await this.fetchJson<NewsApiResponse>(`/api/news/search?q=${q}&limit=${limit}`);
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
}

export const newsService = new NewsService();
