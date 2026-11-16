/**
 * AIVOLVE Trading AI — Live Market Data Streaming Service
 *
 * Connects to the backend SSE (Server-Sent Events) endpoint for
 * real-time tick data from Angel One SmartStream WebSocket.
 *
 * Features:
 * - Auto-reconnecting EventSource connection
 * - Tick event dispatching via callbacks
 * - Connection status monitoring
 * - Fallback polling for non-WebSocket providers
 */

const API_BASE_URL = typeof window !== 'undefined'
  ? ''
  : (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000');

export interface LiveTick {
  symbol: string;
  ltp: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  avgPrice?: number;
  change?: number;
  changePercent?: number;
  dataStatus: 'LIVE' | 'MOCK' | 'UNAVAILABLE' | 'WAITING' | 'DATA_OFFLINE' | 'STALE_TICK' | 'MARKET_CLOSED';
  feedStatus?: string;
  isTradeQualified?: boolean;
  provider?: string;
  timestamp?: number;
}

export interface LiveStreamStatus {
  provider: string;
  websocket_connected: boolean;
  subscribed_exchanges?: string[];
  total_subscriptions?: number;
  sse_clients_connected?: number;
  cached_ticks?: number;
  status: 'STREAMING' | 'DISCONNECTED' | 'REST_POLLING';
}

type TickCallback = (tick: LiveTick) => void;
type StatusCallback = (connected: boolean) => void;

class LiveMarketService {
  private eventSource: EventSource | null = null;
  private tickCallbacks: Map<string, TickCallback[]> = new Map();
  private globalCallbacks: TickCallback[] = [];
  private statusCallbacks: StatusCallback[] = [];
  private isConnected = false;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 2000;
  private maxReconnectDelay = 30000;
  private currentSymbols: string[] = [];

  /**
   * Connect to the live SSE stream for given symbols.
   */
  connect(symbols: string[] = ['NIFTY 50', 'BANK NIFTY', 'FINNIFTY', 'INDIA VIX']): void {
    this.currentSymbols = symbols;
    this.disconnect(); // Clean up any existing connection

    const symbolParam = encodeURIComponent(symbols.join(','));
    const url = `${API_BASE_URL}/api/live/stream?symbols=${symbolParam}`;

    try {
      this.eventSource = new EventSource(url);

      this.eventSource.onopen = () => {
        this.isConnected = true;
        this.reconnectDelay = 2000; // Reset backoff
        this.notifyStatus(true);
        console.log('🟢 Live market stream connected');
      };

      this.eventSource.onmessage = (event) => {
        try {
          const tick: LiveTick = JSON.parse(event.data);
          this.dispatchTick(tick);
        } catch (err) {
          // Ignore parse errors (heartbeats, etc.)
        }
      };

      this.eventSource.onerror = () => {
        this.isConnected = false;
        this.notifyStatus(false);
        this.eventSource?.close();
        this.eventSource = null;
        console.warn('🔴 Live market stream disconnected. Reconnecting...');
        this.scheduleReconnect();
      };
    } catch (err) {
      console.error('Failed to create EventSource:', err);
      this.scheduleReconnect();
    }
  }

  /**
   * Disconnect from the live stream.
   */
  disconnect(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    this.isConnected = false;
    this.notifyStatus(false);
  }

  /**
   * Subscribe to tick updates for a specific symbol.
   */
  onTick(symbol: string, callback: TickCallback): () => void {
    const sym = symbol.toUpperCase().trim();
    if (!this.tickCallbacks.has(sym)) {
      this.tickCallbacks.set(sym, []);
    }
    this.tickCallbacks.get(sym)!.push(callback);

    // Return unsubscribe function
    return () => {
      const callbacks = this.tickCallbacks.get(sym);
      if (callbacks) {
        const idx = callbacks.indexOf(callback);
        if (idx !== -1) callbacks.splice(idx, 1);
      }
    };
  }

  /**
   * Subscribe to ALL tick updates (global listener).
   */
  onAnyTick(callback: TickCallback): () => void {
    this.globalCallbacks.push(callback);
    return () => {
      const idx = this.globalCallbacks.indexOf(callback);
      if (idx !== -1) this.globalCallbacks.splice(idx, 1);
    };
  }

  /**
   * Subscribe to connection status changes.
   */
  onStatusChange(callback: StatusCallback): () => void {
    this.statusCallbacks.push(callback);
    return () => {
      const idx = this.statusCallbacks.indexOf(callback);
      if (idx !== -1) this.statusCallbacks.splice(idx, 1);
    };
  }

  /**
   * Fetch a single live quote (REST, not SSE).
   */
  async getLiveQuote(symbol: string): Promise<LiveTick | null> {
    try {
      const res = await fetch(`${API_BASE_URL}/api/live/quote/${encodeURIComponent(symbol)}`, {
        signal: AbortSignal.timeout(5000),
      });
      if (!res.ok) return null;
      const envelope = await res.json();
      return envelope.data || null;
    } catch {
      return null;
    }
  }

  /**
   * Fetch LTP only (ultra-fast).
   */
  async getLTP(symbol: string): Promise<number | null> {
    try {
      const res = await fetch(`${API_BASE_URL}/api/live/ltp/${encodeURIComponent(symbol)}`, {
        signal: AbortSignal.timeout(3000),
      });
      if (!res.ok) return null;
      const data = await res.json();
      return data.ltp || null;
    } catch {
      return null;
    }
  }

  /**
   * Get streaming connection status.
   */
  async getStreamStatus(): Promise<LiveStreamStatus | null> {
    try {
      const res = await fetch(`${API_BASE_URL}/api/live/status`, {
        signal: AbortSignal.timeout(3000),
      });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  /**
   * Get all cached live ticks (initial hydration).
   */
  async getAllTicks(): Promise<Record<string, LiveTick>> {
    try {
      const res = await fetch(`${API_BASE_URL}/api/live/ticks`, {
        signal: AbortSignal.timeout(5000),
      });
      if (!res.ok) return {};
      const envelope = await res.json();
      return envelope.data || {};
    } catch {
      return {};
    }
  }

  /**
   * Check if currently connected.
   */
  get connected(): boolean {
    return this.isConnected;
  }

  // ── Internal Methods ──

  private dispatchTick(tick: LiveTick): void {
    const sym = tick.symbol?.toUpperCase().trim();
    if (!sym) return;

    // Symbol-specific callbacks
    const callbacks = this.tickCallbacks.get(sym);
    if (callbacks) {
      for (const cb of callbacks) {
        try {
          cb(tick);
        } catch (err) {
          console.error(`Tick callback error for ${sym}:`, err);
        }
      }
    }

    // Global callbacks
    for (const cb of this.globalCallbacks) {
      try {
        cb(tick);
      } catch (err) {
        console.error('Global tick callback error:', err);
      }
    }
  }

  private notifyStatus(connected: boolean): void {
    for (const cb of this.statusCallbacks) {
      try {
        cb(connected);
      } catch {
        // ignore
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimeout) return;

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null;
      this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.maxReconnectDelay);
      this.connect(this.currentSymbols);
    }, this.reconnectDelay);
  }
}

// Singleton instance
export const liveMarketService = new LiveMarketService();
