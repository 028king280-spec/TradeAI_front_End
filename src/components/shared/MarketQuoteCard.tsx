'use client';
import { ArrowDownRight, ArrowUpRight } from 'lucide-react';
import { feedLabel } from '@/context/MarketFeedContext';

interface QuoteProps {
  symbol: string; value: number | null; change: number | null; changePercent: number | null;
  dataStatus: string; sparkline?: number[]; selected: boolean; onSelect: () => void;
}
export function MarketQuoteCard({ symbol, value, change, changePercent, dataStatus, sparkline = [], selected, onSelect }: QuoteProps) {
  const validValue = typeof value === 'number' && Number.isFinite(value) && value > 0;
  const validChange = validValue && typeof change === 'number' && Number.isFinite(change);
  const validPercent = validValue && typeof changePercent === 'number' && Number.isFinite(changePercent);
  const up = (change || 0) >= 0;
  const points = sparkline.filter(Number.isFinite);
  const low = Math.min(...points), high = Math.max(...points);
  const coordinates = points.map((point, index) => `${index / Math.max(points.length - 1, 1) * 100},${40 - (point - low) / (high - low || 1) * 35}`).join(' ');
  return <button type="button" className="workspace-quote" aria-pressed={selected} onClick={onSelect}>
    <span className="workspace-quote-title"><span>{symbol}</span>{validChange && (up ? <ArrowUpRight size={15}/> : <ArrowDownRight size={15}/>)}</span>
    <strong className="workspace-quote-value">{validValue ? value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</strong>
    <span className="workspace-quote-change" style={{ color: validChange ? up ? 'var(--bullish)' : 'var(--bearish)' : 'var(--text-muted)' }}>{validChange ? `${up ? '+' : ''}${change.toFixed(2)}` : 'Awaiting quote'}{validPercent && ` (${changePercent >= 0 ? '+' : ''}${changePercent.toFixed(2)}%)`}</span>
    <span className="workspace-quote-status">{feedLabel(dataStatus)}</span>
    {points.length > 1 && validValue && <svg className="sparkline" viewBox="0 0 100 45" aria-hidden="true"><polyline points={coordinates} fill="none" stroke={up ? 'var(--bullish)' : 'var(--bearish)'} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/></svg>}
  </button>;
}
