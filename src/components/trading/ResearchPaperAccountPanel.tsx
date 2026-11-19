'use client';

import { useEffect, useState, useCallback } from 'react';
import { RefreshCw } from 'lucide-react';

interface ResearchTrade {
  id: string; contract: string; quantity: number; status: string;
  entry: number; target: number; stop: number; exit: number | null;
  exitReason: string | null; netPnl: number | null; monitoring: string; hadDataGap: boolean;
  openedAt: string; closedAt: string | null; lastQuoteAt: string | null;
}
interface ResearchAccount {
  initialized: boolean; autoEntryEnabled: boolean; initialCash: number;
  availableCash: number | null; realizedNetPnl: number; totalTrades: number;
  costModel: { feePerSide: number; slippageBps: number; excludes: string };
  trades: ResearchTrade[];
}

const STORAGE_KEY = 'aivolve_research_paper_snapshot_v1';
const money = (value: number | null) => value === null ? '—' : value.toLocaleString('en-IN', { style: 'currency', currency: 'INR' });
const time = (value: string | null) => value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) : '—';

export function ResearchPaperAccountPanel() {
  const [data, setData] = useState<ResearchAccount | null>(null);
  const [error, setError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // Initialize from cached snapshot if available so trades don't disappear on offline/transient errors
  useEffect(() => {
    try {
      const cached = localStorage.getItem(STORAGE_KEY);
      if (cached) {
        const parsed = JSON.parse(cached);
        if (parsed && Array.isArray(parsed.trades)) {
          setData(parsed);
        }
      }
    } catch {
      // Ignore localStorage errors
    }
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const response = await fetch('/api/performance/research-paper', { cache: 'no-store' });
      if (!response.ok) throw new Error('Research account unavailable');
      const result: ResearchAccount = await response.json();
      if (!Array.isArray(result.trades)) throw new Error('Invalid account response');
      setData(result);
      setError(false);
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(result));
      } catch {
        // Ignore quota errors
      }
    } catch {
      setError(true);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 10000);
    return () => clearInterval(timer);
  }, [refresh]);

  return (
    <section id="research-paper" className="workspace-panel space-y-4" aria-label="Research paper account">
      <div className="workspace-panel-heading flex items-center justify-between">
        <div>
          <p className="workspace-eyebrow">Second engine · Separate simulated account</p>
          <h2>60-point paper entries & exits</h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void refresh()}
            disabled={refreshing}
            className="p-1.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all cursor-pointer"
            title="Refresh Account Data"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
          <span className="text-xs">
            {error ? 'Update unavailable (Showing snapshot)' : data ? (data.autoEntryEnabled ? 'Auto entry enabled' : 'New entries disabled') : 'Loading…'}
          </span>
        </div>
      </div>

      <p className="text-xs text-[var(--text-muted)]">
        One lot per qualified setup; +30% target from the filled premium. Automatic stop-loss and 15:25 IST session-end exits use fresh executable quotes. Setup generation follows analysis refreshes; backend exit monitoring continues with the browser closed.
      </p>

      {error && (
        <p role="alert" className="text-sm text-amber-500">
          Could not refresh the research account live. Any values below are the last received snapshot, not a live balance.
        </p>
      )}

      {data && (
        <>
          <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div><dt className="text-xs text-[var(--text-muted)]">Initial virtual capital</dt><dd className="font-semibold">{money(data.initialCash)}</dd></div>
            <div><dt className="text-xs text-[var(--text-muted)]">Available virtual cash</dt><dd className="font-semibold">{money(data.availableCash)}</dd></div>
            <div>
              <dt className="text-xs text-[var(--text-muted)]">Realized P&L after model costs</dt>
              <dd className={`font-semibold ${data.realizedNetPnl >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                {money(data.realizedNetPnl)}
              </dd>
            </div>
            <div><dt className="text-xs text-[var(--text-muted)]">Research trades</dt><dd className="font-semibold">{data.totalTrades}</dd></div>
          </dl>

          <p className="text-xs text-[var(--text-muted)]">
            Simulation cost assumptions: {money(data.costModel.feePerSide)} per side + {data.costModel.slippageBps / 100}% slippage per side. Excludes {data.costModel.excludes}. Cash excludes capital tied up in open positions; this is not total equity.
          </p>

          {!data.initialized && (
            <p className="text-sm">Waiting for the backend scheduler to initialize this account during market hours.</p>
          )}

          {data.trades.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <caption className="pb-2 text-left text-[var(--text-muted)] font-medium">
                  Latest {data.trades.length} trades · timestamps in IST
                </caption>
                <thead>
                  <tr className="border-b border-[var(--border-subtle)] text-[var(--text-muted)]">
                    {['Contract / time', 'Qty', 'Entry', 'Target', 'SL', 'Exit', 'P&L after costs', 'Status'].map(h => (
                      <th key={h} className="p-2 whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.trades.map(trade => (
                    <tr key={trade.id} className="border-t border-[var(--border-subtle)] hover:bg-[var(--bg-surface-elevated)]/40 transition-colors">
                      <td className="p-2">
                        <div className="font-semibold">{trade.contract}</div>
                        <div className="text-[var(--text-muted)]">In: {time(trade.openedAt)}</div>
                        {trade.closedAt && <div className="text-[var(--text-muted)]">Out: {time(trade.closedAt)}</div>}
                      </td>
                      <td className="p-2 font-mono">{trade.quantity}</td>
                      <td className="p-2 font-mono">{money(trade.entry)}</td>
                      <td className="p-2 font-mono text-emerald-600 dark:text-emerald-400">{money(trade.target)}</td>
                      <td className="p-2 font-mono text-rose-600 dark:text-rose-400">{money(trade.stop)}</td>
                      <td className="p-2 font-mono">{money(trade.exit)}</td>
                      <td className={`p-2 font-mono font-semibold ${(trade.netPnl || 0) >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                        {money(trade.netPnl)}
                      </td>
                      <td className="p-2">
                        <span className={`px-2 py-0.5 rounded text-[11px] font-semibold ${
                          trade.exitReason === 'STOP_LOSS'
                            ? 'bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-400 border border-rose-200 dark:border-rose-500/20'
                            : trade.exitReason === 'TARGET'
                            ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-500/20'
                            : 'bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20'
                        }`}>
                          {trade.exitReason || trade.status}
                        </span>
                        {trade.hadDataGap && <div className="text-[10px] text-amber-500 mt-0.5">Data gap · reviewed</div>}
                        {trade.status === 'OPEN' && <div className="text-[10px] text-[var(--text-muted)] mt-0.5">{trade.monitoring} · quote {time(trade.lastQuoteAt)}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-[var(--text-secondary)]">
              No research paper trades yet. A fresh qualified saved setup, sufficient virtual cash and verified option depth are required.
            </p>
          )}
        </>
      )}
    </section>
  );
}
