/**
 * AIVOLVE v3.0 — Macro & Event Intelligence API Service (REQ-6.11)
 * Part of Phase 6: Macro, Event & Overnight Drift Engine (Engine 8)
 */

import {
  MacroCalendarResponse,
  ProximityReport,
  MacroEventItem,
  MacroFeedStatus,
} from '@/types/macro';

const API_BASE_URL =
  typeof window !== 'undefined'
    ? ''
    : (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000');

class MacroService {
  private async fetchJson<T>(url: string): Promise<T | null> {
    try {
      const res = await fetch(`${API_BASE_URL}${url}`, {
        cache: 'no-store',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!res.ok) {
        console.warn(`Macro API error ${res.status} on ${url}`);
        return null;
      }

      const envelope = await res.json();
      if (envelope && envelope.success && envelope.data !== undefined) {
        return envelope.data as T;
      }
      return envelope as T;
    } catch (err) {
      console.warn(`Macro fetch failed for ${url}:`, err);
      return null;
    }
  }

  /**
   * Retrieves macroeconomic calendar events with optional filtering.
   */
  async getCalendarEvents(params?: {
    startTime?: string;
    endTime?: string;
    tier?: string;
    index?: string;
  }): Promise<MacroCalendarResponse | null> {
    const query = new URLSearchParams();
    if (params?.startTime) query.set('start_time', params.startTime);
    if (params?.endTime) query.set('end_time', params.endTime);
    if (params?.tier) query.set('tier', params.tier);
    if (params?.index) query.set('index', params.index);

    const queryString = query.toString();
    const url = `/api/macro/calendar${queryString ? `?${queryString}` : ''}`;
    return this.fetchJson<MacroCalendarResponse>(url);
  }

  /**
   * Evaluates current deterministic mathematical time proximity.
   */
  async getProximityReport(index: string = 'NIFTY 50'): Promise<ProximityReport | null> {
    const query = new URLSearchParams({ index });
    return this.fetchJson<ProximityReport>(`/api/macro/proximity?${query.toString()}`);
  }

  /**
   * Retrieves a specific macro event by ID.
   */
  async getEventById(eventId: string): Promise<MacroEventItem | null> {
    return this.fetchJson<MacroEventItem>(`/api/macro/events/${encodeURIComponent(eventId)}`);
  }

  /**
   * Retrieves status of external calendar feed adapter.
   */
  async getFeedStatus(): Promise<MacroFeedStatus | null> {
    return this.fetchJson<MacroFeedStatus>('/api/macro/feed-status');
  }
}

export const macroService = new MacroService();

