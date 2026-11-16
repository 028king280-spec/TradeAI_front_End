'use client';

import { useEffect, useState } from 'react';
import { Activity, RefreshCw, ShieldCheck, Wifi, WifiOff } from 'lucide-react';
import { PageHeading } from '@/components/shared/PageHeading';
import { feedLabel, useMarketFeed } from '@/context/MarketFeedContext';
import { SystemEfficiencyPanel } from '@/components/trading/SystemEfficiencyPanel';

interface StreamStatus {
  status: string;
  websocket_connected: boolean;
  total_subscriptions?: number;
  cached_ticks?: number;
  diagnostics?: { ticks_received?: number };
}

export default function ObserverPage() {
  const feed = useMarketFeed();
  const [stream, setStream] = useState<StreamStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const response = await fetch('/api/live/status', { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('Status unavailable');
        const data = await response.json();
        if (typeof data.status !== 'string' || typeof data.websocket_connected !== 'boolean') throw new Error('Invalid status');
        if (!stopped) setStream(data);
      } catch { if (!stopped) setStream(null); }
      finally { if (!stopped) { setLoading(false); timer = setTimeout(load, 15000); } }
    }
    void load();
    return () => { stopped = true; clearTimeout(timer); controller.abort(); };
  }, [refreshKey]);
  const number = (value?: number) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('en-IN') : '—';
  return <div className="space-y-6">
    <PageHeading title="Market observer" description="Follow feed health, quote provenance and data ingestion in one workspace." actions={<button className="workspace-secondary-button" onClick={() => setRefreshKey(value => value + 1)}><RefreshCw size={14}/> Refresh status</button>}/>
    <div className="workspace-quote-grid">
      {[{label:'Stream connection',value:loading?'Checking…':stream?.status || 'Unavailable'}, {label:'Received ticks',value:number(stream?.diagnostics?.ticks_received)}, {label:'Subscribed instruments',value:number(stream?.total_subscriptions)}, {label:'Execution mode',value:'Paper only'}].map(item => <section className="workspace-quote" key={item.label}><span className="workspace-quote-title">{item.label}</span><strong className="workspace-quote-value text-lg">{item.value}</strong></section>)}
    </div>
    <section className="workspace-panel">
      <div className="workspace-panel-heading"><h2>Index feed surveillance</h2><span className="workspace-pill">{feedLabel(feed.dataStatus)}</span></div>
      {feed.quotes.length ? <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr className="border-b border-[var(--border-subtle)] text-[var(--text-muted)]">{['Instrument','Last quote','Data status','Source timestamp'].map(title => <th className="py-3 pr-5 font-medium" key={title}>{title}</th>)}</tr></thead><tbody>{feed.quotes.map(quote => <tr key={quote.symbol} className="border-b border-[var(--border-subtle)]"><td className="py-4 pr-5">{quote.symbol}</td><td className="py-4 pr-5 tabular-nums">{quote.currentValue?.toLocaleString('en-IN', { minimumFractionDigits: 2 }) || '—'}</td><td className="py-4 pr-5">{feedLabel(quote.dataStatus)}</td><td className="py-4 pr-5 text-[var(--text-muted)]">{quote.timestamp || 'Not supplied'}</td></tr>)}</tbody></table></div> : <div className="workspace-empty"><WifiOff size={24}/>No quotes are available. Connect the market-data backend to inspect verified instrument feeds.</div>}
    </section>
    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
      <section className="workspace-panel"><div className="workspace-panel-heading"><h2>Connection integrity</h2>{stream?.websocket_connected ? <Wifi size={18}/> : <WifiOff size={18}/>}</div><p className="text-xs text-[var(--text-secondary)] leading-7">{stream?.websocket_connected ? 'The backend reports a connected WebSocket. Quote status and timestamps determine whether market data is usable.' : 'No connected WebSocket is reported. A configured REST provider may still supply market quotes; check instrument status separately.'}</p></section>
      <section className="workspace-panel"><div className="workspace-panel-heading"><h2>Execution boundary</h2><ShieldCheck size={18}/></div><p className="text-xs text-[var(--text-secondary)] leading-7">This workspace observes market data. Simulated entries continue through the existing paper-trading risk checks. No real broker routing is enabled by the interface.</p><span className="workspace-pill mt-4"><Activity size={12}/> Read-only diagnostics</span></section>
    </div>
    <SystemEfficiencyPanel/>
  </div>;
}
