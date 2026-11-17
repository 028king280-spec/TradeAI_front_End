'use client';

import { useEffect, useState } from 'react';

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
const money = (value: number | null) => value === null ? '—' : value.toLocaleString('en-IN', { style: 'currency', currency: 'INR' });
const time = (value: string | null) => value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) : '—';

export function ResearchPaperAccountPanel() {
  const [data, setData] = useState<ResearchAccount | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    async function refresh() {
      if (pending) return;
      pending = true;
      try {
        const response = await fetch('/api/performance/research-paper', { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('Research account unavailable');
        const result: ResearchAccount = await response.json();
        if (!Array.isArray(result.trades)) throw new Error('Invalid account response');
        if (!controller.signal.aborted) { setData(result); setError(false); }
      } catch { if (!controller.signal.aborted) setError(true); }
      finally { pending = false; }
    }
    void refresh();
    const timer = setInterval(refresh, 10000);
    return () => { clearInterval(timer); controller.abort(); };
  }, []);

  return <section id="research-paper" className="workspace-panel space-y-4" aria-label="Research paper account">
    <div className="workspace-panel-heading"><div>
      <p className="workspace-eyebrow">Second engine · Separate simulated account</p>
      <h2>60-point paper entries & exits</h2>
    </div><span className="text-xs">{error ? 'Update unavailable' : data ? (data.autoEntryEnabled ? 'Auto entry enabled' : 'New entries disabled') : 'Loading…'}</span></div>
    <p className="text-xs text-[var(--text-muted)]">One lot per qualified setup; +30% target from the filled premium. Automatic stop-loss and 15:25 IST session-end exits use fresh executable quotes. Setup generation follows analysis refreshes; backend exit monitoring continues with the browser closed.</p>
    {error && <p role="alert" className="text-sm text-amber-500">Could not refresh the research account. Any values below are the last received snapshot, not a live balance.</p>}
    {data && <>
      <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <div><dt>Initial virtual capital</dt><dd>{money(data.initialCash)}</dd></div>
        <div><dt>Available virtual cash</dt><dd>{money(data.availableCash)}</dd></div>
        <div><dt>Realized P&L after model costs</dt><dd>{money(data.realizedNetPnl)}</dd></div>
        <div><dt>Research trades</dt><dd>{data.totalTrades}</dd></div>
      </dl>
      <p className="text-xs text-[var(--text-muted)]">Simulation cost assumptions: {money(data.costModel.feePerSide)} per side + {data.costModel.slippageBps / 100}% slippage per side. Excludes {data.costModel.excludes}. Cash excludes capital tied up in open positions; this is not total equity.</p>
      {!data.initialized && <p className="text-sm">Waiting for the backend scheduler to initialize this account during market hours.</p>}
      {data.trades.length ? <div className="overflow-x-auto"><table className="w-full text-left text-xs">
        <caption className="pb-2 text-left text-[var(--text-muted)]">Latest {data.trades.length} trades · timestamps in IST</caption>
        <thead><tr>{['Contract / time', 'Qty', 'Entry', 'Target', 'SL', 'Exit', 'P&L after model costs', 'Status'].map(h => <th key={h} className="p-2 whitespace-nowrap">{h}</th>)}</tr></thead>
        <tbody>{data.trades.map(trade => <tr key={trade.id} className="border-t border-[var(--border-subtle)]">
          <td className="p-2"><div>{trade.contract}</div><div className="text-[var(--text-muted)]">In: {time(trade.openedAt)}</div>{trade.closedAt && <div>Out: {time(trade.closedAt)}</div>}</td>
          <td className="p-2">{trade.quantity}</td><td className="p-2">{money(trade.entry)}</td><td className="p-2">{money(trade.target)}</td><td className="p-2">{money(trade.stop)}</td><td className="p-2">{money(trade.exit)}</td><td className="p-2">{money(trade.netPnl)}</td>
          <td className="p-2"><div>{trade.exitReason || trade.status}</div>{trade.hadDataGap && <div className="text-amber-500">Data gap · review outcome</div>}{trade.status === 'OPEN' && <div className="text-[var(--text-muted)]">{trade.monitoring} · quote {time(trade.lastQuoteAt)}</div>}</td>
        </tr>)}</tbody>
      </table></div> : <p className="text-sm text-[var(--text-secondary)]">No research paper trades yet. A fresh qualified saved setup, sufficient virtual cash and verified option depth are required.</p>}
    </>}
  </section>;
}
