'use client';

import React, { useState } from 'react';
import { OptionChainResponse } from '@/types/options';
import { Layers, Info } from 'lucide-react';
import { formatNumberIN } from '@/lib/utils';

interface OptionChainTableProps {
  data: OptionChainResponse;
  onFilterChange: (mode: 'ATM' | 'WIDE') => void;
  onExpiryChange: (expiry: string) => void;
}

export const OptionChainTable: React.FC<OptionChainTableProps> = ({
  data,
  onFilterChange,
  onExpiryChange,
}) => {
  const [showGreeks, setShowGreeks] = useState<boolean>(true);
  const [moneynessFilter, setMoneynessFilter] = useState<'ALL' | 'ITM' | 'ATM' | 'OTM'>('ALL');

  const filteredStrikes = data.strikes.filter((s) => {
    if (moneynessFilter === 'ATM') return s.isAtm;
    if (moneynessFilter === 'ITM') return s.ce.moneyness === 'ITM' || s.pe.moneyness === 'ITM';
    if (moneynessFilter === 'OTM') return s.ce.moneyness === 'OTM' || s.pe.moneyness === 'OTM';
    return true;
  });

  const callWall = data.oiAnalysis?.callWall;
  const putWall = data.oiAnalysis?.putWall;
  const maxPain = data.maxPain?.maxPainStrike;

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 sm:p-5 shadow-sm space-y-4">
      {/* Top Controls & Metrics Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-4 border-b border-[var(--border-subtle)]">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 flex items-center justify-center">
              <Layers className="w-4 h-4 text-[var(--accent-blue)]" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-[var(--text-primary)] tabular-nums flex items-center gap-2">
                <span>{data.symbol} Option Chain</span>
                <span className="text-[10px] tabular-nums px-2 py-0.5 rounded bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] dark:text-[var(--accent-blue)]">
                  Spot: ₹{data.underlyingPrice.toLocaleString('en-IN')}
                </span>
              </h2>
              <p className="text-xs text-[var(--text-muted)] tabular-nums">
                Real-time strike distribution with institutional Black-Scholes Greeks
              </p>
            </div>
          </div>
        </div>

        {/* Expiry & Filters */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Expiry Selector */}
          <select
            value={data.selectedExpiry}
            onChange={(e) => onExpiryChange(e.target.value)}
            className="px-3 py-1.5 rounded-lg text-xs tabular-nums bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-blue)]"
          >
            {data.availableExpiries.map((exp) => (
              <option key={exp} value={exp}>
                {exp}
              </option>
            ))}
          </select>

          {/* ATM / Wide view toggle */}
          <div className="inline-flex rounded-lg bg-[var(--bg-surface-elevated)] p-0.5 border border-[var(--border-subtle)]">
            <button
              onClick={() => onFilterChange('ATM')}
              className={`px-2.5 py-1 text-xs tabular-nums rounded-md transition-all ${
                data.filterMode === 'ATM'
                  ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] font-semibold shadow-xs'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              ATM Strikes (±7)
            </button>
            <button
              onClick={() => onFilterChange('WIDE')}
              className={`px-2.5 py-1 text-xs tabular-nums rounded-md transition-all ${
                data.filterMode === 'WIDE'
                  ? 'bg-[var(--accent-blue)] text-[var(--accent-on)] font-semibold shadow-xs'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              Wider Range (±15)
            </button>
          </div>

          {/* Greeks Toggle */}
          <button
            onClick={() => setShowGreeks(!showGreeks)}
            className={`px-2.5 py-1.5 text-xs tabular-nums rounded-lg border transition-all ${
              showGreeks
                ? 'bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] dark:text-[var(--accent-blue)] border-[var(--accent-blue)]/30'
                : 'bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] border-[var(--border-subtle)]'
            }`}
          >
            {showGreeks ? 'Greeks (Active)' : 'Show Greeks'}
          </button>
        </div>
      </div>

      {/* Derivative Anchors (PCR, Max Pain, Walls) */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {/* PCR */}
        <div className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
          <div className="text-[10px] uppercase tabular-nums text-[var(--text-muted)] font-semibold">Put-Call Ratio (OI)</div>
          <div className="text-base font-semibold tabular-nums text-[var(--text-primary)] flex items-center gap-1.5 mt-0.5">
            <span>{data.pcr?.pcrOi}</span>
            <span
              className={`text-[9px] px-1.5 py-0.2 rounded font-semibold ${
                data.pcr?.signal === 'BULLISH'
                  ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                  : data.pcr?.signal === 'BEARISH'
                  ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
                  : 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
              }`}
            >
              {data.pcr?.signal}
            </span>
          </div>
          <div className="text-[10px] text-[var(--text-muted)] tabular-nums mt-0.5">
            PE OI: {formatNumberIN(data.pcr?.putOiTotal || 0)}
          </div>
        </div>

        {/* Max Pain */}
        <div className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
          <div className="text-[10px] uppercase tabular-nums text-[var(--text-muted)] font-semibold">Option Max Pain</div>
          <div className="text-base font-semibold tabular-nums text-[var(--text-primary)] mt-0.5">
            {maxPain ? `₹${maxPain.toLocaleString('en-IN')}` : 'Calculating...'}
          </div>
          <div className="text-[10px] text-[var(--text-muted)] tabular-nums mt-0.5">
            Descriptive positioning
          </div>
        </div>

        {/* Call Wall */}
        <div className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
          <div className="text-[10px] uppercase tabular-nums text-rose-500 font-semibold">Call Wall (Resistance)</div>
          <div className="text-base font-semibold tabular-nums text-rose-500 mt-0.5">
            {callWall ? `₹${callWall.toLocaleString('en-IN')}` : 'N/A'}
          </div>
          <div className="text-[10px] text-[var(--text-muted)] tabular-nums mt-0.5">
            Highest CE OI Concentration
          </div>
        </div>

        {/* Put Wall */}
        <div className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)]">
          <div className="text-[10px] uppercase tabular-nums text-emerald-500 font-semibold">Put Wall (Support)</div>
          <div className="text-base font-semibold tabular-nums text-emerald-500 mt-0.5">
            {putWall ? `₹${putWall.toLocaleString('en-IN')}` : 'N/A'}
          </div>
          <div className="text-[10px] text-[var(--text-muted)] tabular-nums mt-0.5">
            Highest PE OI Concentration
          </div>
        </div>
      </div>

      {/* Main Option Chain Table */}
      <div className="overflow-x-auto rounded-lg border border-[var(--border-subtle)]">
        <table className="w-full text-left tabular-nums text-xs border-collapse">
          <thead>
            {/* Header Level 1 */}
            <tr className="bg-[var(--bg-surface-elevated)] border-b border-[var(--border-subtle)] text-[10px] uppercase font-semibold">
              <th colSpan={showGreeks ? 7 : 4} className="text-center py-2 border-r border-[var(--border-subtle)] text-[var(--accent-blue)] dark:text-[var(--accent-blue)]">
                CALL OPTIONS (CE)
              </th>
              <th className="text-center py-2 px-4 bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] text-[var(--text-primary)]">
                STRIKE
              </th>
              <th colSpan={showGreeks ? 7 : 4} className="text-center py-2 border-l border-[var(--border-subtle)] text-amber-600 dark:text-amber-400">
                PUT OPTIONS (PE)
              </th>
            </tr>
            {/* Header Level 2 */}
            <tr className="bg-[var(--bg-surface)] border-b border-[var(--border-subtle)] text-[10px] text-[var(--text-muted)]">
              {showGreeks && <th className="p-2 text-right">Delta</th>}
              {showGreeks && <th className="p-2 text-right">Theta</th>}
              {showGreeks && <th className="p-2 text-right">IV %</th>}
              <th className="p-2 text-right">Volume</th>
              <th className="p-2 text-right">Chg OI</th>
              <th className="p-2 text-right">OI</th>
              <th className="p-2 text-right font-semibold text-[var(--accent-blue)] dark:text-[var(--accent-blue)] border-r border-[var(--border-subtle)]">
                LTP (₹)
              </th>

              <th className="p-2 text-center font-semibold bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] text-[var(--text-primary)] min-w-[90px]">
                Strike
              </th>

              <th className="p-2 text-left font-semibold text-amber-600 dark:text-amber-400 border-l border-[var(--border-subtle)]">
                LTP (₹)
              </th>
              <th className="p-2 text-left">OI</th>
              <th className="p-2 text-left">Chg OI</th>
              <th className="p-2 text-left">Volume</th>
              {showGreeks && <th className="p-2 text-left">IV %</th>}
              {showGreeks && <th className="p-2 text-left">Theta</th>}
              {showGreeks && <th className="p-2 text-left">Delta</th>}
            </tr>
          </thead>
          <tbody>
            {filteredStrikes.map((row) => {
              const isAtm = row.isAtm;
              const isCallWall = row.strike === callWall;
              const isPutWall = row.strike === putWall;
              const isMaxPain = row.strike === maxPain;

              return (
                <tr
                  key={row.strike}
                  className={`border-b border-[var(--border-subtle)] text-[11px] transition-colors hover:bg-[var(--bg-surface-hover)] ${
                    isAtm ? 'bg-[var(--accent-blue)]/10 font-medium' : ''
                  }`}
                >
                  {/* CALLS */}
                  {showGreeks && <td className="p-2 text-right text-[var(--text-muted)]">{row.ce.delta}</td>}
                  {showGreeks && <td className="p-2 text-right text-rose-400">{row.ce.theta}</td>}
                  {showGreeks && <td className="p-2 text-right text-[var(--text-muted)]">{row.ce.iv}%</td>}
                  <td className="p-2 text-right text-[var(--text-muted)]">{formatNumberIN(row.ce.volume)}</td>
                  <td
                    className={`p-2 text-right font-medium ${
                      row.ce.changeInOi >= 0 ? 'text-emerald-500' : 'text-rose-500'
                    }`}
                  >
                    {row.ce.changeInOi >= 0 ? `+${formatNumberIN(row.ce.changeInOi)}` : formatNumberIN(row.ce.changeInOi)}
                  </td>
                  <td className={`p-2 text-right ${isCallWall ? 'text-rose-500 font-semibold' : ''}`}>
                    {formatNumberIN(row.ce.oi || 0)}
                    {isCallWall && <span className="ml-1 text-[9px] px-1 rounded bg-rose-500/15">Wall</span>}
                  </td>
                  <td className="p-2 text-right font-semibold text-[var(--accent-blue)] dark:text-[var(--accent-blue)] border-r border-[var(--border-subtle)]">
                    ₹{row.ce.ltp != null ? Number(row.ce.ltp).toFixed(2) : '--'}
                  </td>

                  {/* STRIKE */}
                  <td className="p-2 text-center font-semibold bg-[var(--bg-surface-elevated)] dark:bg-[var(--bg-surface-elevated)] text-[var(--text-primary)]">
                    <div className="flex items-center justify-center gap-1">
                      <span>{row.strike.toLocaleString('en-IN')}</span>
                      {isAtm && (
                        <span className="text-[8px] px-1 py-0.2 rounded bg-[var(--accent-blue)] text-[var(--accent-on)] font-semibold">
                          ATM
                        </span>
                      )}
                      {isMaxPain && (
                        <span className="text-[8px] px-1 py-0.2 rounded bg-amber-500/20 text-amber-500 font-semibold">
                          MP
                        </span>
                      )}
                    </div>
                  </td>

                  {/* PUTS */}
                  <td className="p-2 text-left font-semibold text-amber-600 dark:text-amber-400 border-l border-[var(--border-subtle)]">
                    ₹{row.pe.ltp != null ? Number(row.pe.ltp).toFixed(2) : '--'}
                  </td>
                  <td className={`p-2 text-left ${isPutWall ? 'text-emerald-500 font-semibold' : ''}`}>
                    {formatNumberIN(row.pe.oi || 0)}
                    {isPutWall && <span className="ml-1 text-[9px] px-1 rounded bg-emerald-500/15">Wall</span>}
                  </td>
                  <td
                    className={`p-2 text-left font-medium ${
                      row.pe.changeInOi >= 0 ? 'text-emerald-500' : 'text-rose-500'
                    }`}
                  >
                    {row.pe.changeInOi >= 0 ? `+${formatNumberIN(row.pe.changeInOi)}` : formatNumberIN(row.pe.changeInOi)}
                  </td>
                  <td className="p-2 text-left text-[var(--text-muted)]">{formatNumberIN(row.pe.volume)}</td>
                  {showGreeks && <td className="p-2 text-left text-[var(--text-muted)]">{row.pe.iv}%</td>}
                  {showGreeks && <td className="p-2 text-left text-rose-400">{row.pe.theta}</td>}
                  {showGreeks && <td className="p-2 text-left text-[var(--text-muted)]">{row.pe.delta}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Descriptive Disclaimer Notice */}
      <div className="p-3 rounded-lg bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] text-[11px] tabular-nums text-[var(--text-muted)] flex items-start gap-2">
        <Info className="w-4 h-4 text-[var(--accent-blue)] shrink-0 mt-0.5" />
        <div>
          <span>{data.maxPain?.disclaimer}</span>
          <span className="block mt-0.5 text-[10px]">
            Data Timestamp: {data.dataTimestamp} • Analysis Timestamp: {data.analysisTimestamp} • Provider: {data.provider.toUpperCase()}
          </span>
        </div>
      </div>
    </div>
  );
};
