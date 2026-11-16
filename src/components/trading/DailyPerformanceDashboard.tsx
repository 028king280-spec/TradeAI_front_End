'use client';

import React, { useEffect, useState } from 'react';
import { BarChart3, Calendar, Download, RefreshCw } from 'lucide-react';

export const DailyPerformanceDashboard: React.FC = () => {
  const [selectedDate, setSelectedDate] = useState<string>(() => {
    const today = new Date();
    return today.toISOString().split('T')[0];
  });
  const [selectedSymbol, setSelectedSymbol] = useState<string>('ALL');
  const [selectedType, setSelectedType] = useState<string>('ALL');
  const [loading, setLoading] = useState<boolean>(true);
  const [data, setData] = useState<any>(null);
  const [historyList, setHistoryList] = useState<any[]>([]);

  const fetchPerformance = async () => {
    setLoading(true);
    try {
      const symParam = selectedSymbol !== 'ALL' ? `&symbol=${encodeURIComponent(selectedSymbol)}` : '';
      const typeParam = selectedType !== 'ALL' ? `&option_type=${selectedType}` : '';
      const res = await fetch(`/api/performance/daily?date=${selectedDate}${symParam}${typeParam}`);
      const json = await res.json();
      if (json.success) {
        setData(json.data);
      }

      // Also fetch history summary
      const histRes = await fetch(`/api/performance/history?days=30`);
      const histJson = await histRes.json();
      if (histJson.success) {
        setHistoryList(histJson.data.history || []);
      }
    } catch (err) {
      console.error('Failed to load daily performance:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPerformance();
  }, [selectedDate, selectedSymbol, selectedType]);

  const handleExportCSV = () => {
    window.open(`/api/performance/export?date=${selectedDate}`, '_blank');
  };

  return (
    <div className="space-y-6 pb-12">
      {/* Top Filter Bar */}
      <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[var(--accent-blue-bg)] dark:bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)] dark:border-[var(--accent-blue)]/20 flex items-center justify-center text-[var(--accent-blue)]">
            <BarChart3 className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)] tracking-tight">
              Daily Signal Performance & Audit Engine
            </h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Institutional accuracy audit with transparent denominators
            </p>
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Date Picker */}
          <div className="flex items-center gap-2 bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-xl px-3 py-2 text-xs">
            <Calendar className="w-3.5 h-3.5 text-[var(--text-muted)]" />
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="bg-transparent text-[var(--text-primary)] font-medium focus:outline-none text-xs cursor-pointer"
            />
          </div>

          {/* Index Selector */}
          <select
            value={selectedSymbol}
            onChange={(e) => setSelectedSymbol(e.target.value)}
            className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-xl px-3 py-2 text-[var(--text-primary)] font-medium text-xs focus:outline-none cursor-pointer"
          >
            <option value="ALL">All Indices</option>
            <option value="NIFTY 50">NIFTY 50</option>
            <option value="SENSEX">SENSEX</option>
            <option value="BANK NIFTY">BANK NIFTY</option>
          </select>

          {/* Type Selector */}
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
            className="bg-[var(--bg-surface-elevated)] border border-[var(--border-subtle)] rounded-xl px-3 py-2 text-[var(--text-primary)] font-medium text-xs focus:outline-none cursor-pointer"
          >
            <option value="ALL">CALL & PUT</option>
            <option value="CE">CALL (CE) Only</option>
            <option value="PE">PUT (PE) Only</option>
          </select>

          {/* Export CSV Button */}
          <button
            onClick={handleExportCSV}
            className="px-3.5 py-2 rounded-xl bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)] text-[var(--accent-on)] font-semibold text-xs flex items-center gap-1.5 transition-colors shadow-sm cursor-pointer"
            title="Download full daily audit to CSV"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export CSV</span>
          </button>
        </div>
      </div>

      {loading && !data ? (
        <div className="py-20 text-center space-y-3">
          <RefreshCw className="w-8 h-8 text-[var(--accent-blue)] animate-spin mx-auto" />
          <p className="text-xs text-[var(--text-muted)]">Loading daily signal performance audit...</p>
        </div>
      ) : !data ? (
        <div className="py-12 text-center text-xs text-[var(--text-muted)]">
          No audit metrics recorded for the selected date.
        </div>
      ) : (
        <div className="space-y-6">
          {/* Transparent Accuracy Metrics Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {/* Metric 1: Entry Trigger Rate */}
            <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-2 shadow-sm">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-[var(--text-secondary)]">Entry Trigger Rate</span>
                <span className="text-[10px] px-2 py-0.5 rounded-md bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] font-semibold border border-[var(--border-subtle)]">
                  Triggered / Eligible
                </span>
              </div>
              <div className="text-2xl font-semibold tabular-nums text-[var(--accent-blue)] dark:text-[var(--accent-blue)]">
                {data.counts.totalSignals === 0 ? 'Insufficient data' : `${data.metricsWithDenominators.entryTriggerRate.rate}%`}
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                {data.metricsWithDenominators.entryTriggerRate.formatted}
              </p>
            </div>

            {/* Metric 2: Target 1 Hit Rate */}
            <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-2 shadow-sm">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-[var(--text-secondary)]">Target 1 Hit Rate</span>
                <span className="text-[10px] px-2 py-0.5 rounded-md bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] font-semibold border border-[var(--border-subtle)]">
                  T1 Hits / Entries
                </span>
              </div>
              <div className="text-2xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                {data.counts.triggeredEntries === 0 ? 'Insufficient data' : `${data.metricsWithDenominators.target1HitRate.rate}%`}
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                {data.metricsWithDenominators.target1HitRate.formatted}
              </p>
            </div>

            {/* Metric 3: Final Win Rate */}
            <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-2 shadow-sm">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-[var(--text-secondary)]">Final Win Rate</span>
                <span className="text-[10px] px-2 py-0.5 rounded-md bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] font-semibold border border-[var(--border-subtle)]">
                  Profitable / Resolved
                </span>
              </div>
              <div className="text-2xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                {data.counts.totalResolved === 0 ? 'Insufficient data' : `${data.metricsWithDenominators.finalWinRate.rate}%`}
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                {data.metricsWithDenominators.finalWinRate.formatted}
              </p>
            </div>

            {/* Metric 4: Stop-Loss Rate */}
            <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-2 shadow-sm">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-[var(--text-secondary)]">Stop-Loss Rate</span>
                <span className="text-[10px] px-2 py-0.5 rounded-md bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] font-semibold border border-[var(--border-subtle)]">
                  SL / Entries
                </span>
              </div>
              <div className="text-2xl font-semibold tabular-nums text-rose-600 dark:text-rose-400">
                {data.counts.triggeredEntries === 0 ? 'Insufficient data' : `${data.metricsWithDenominators.stopLossRate.rate}%`}
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                {data.metricsWithDenominators.stopLossRate.formatted}
              </p>
            </div>

            {/* Metric 5: Directional Accuracy */}
            <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-2 shadow-sm">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-[var(--text-secondary)]">Directional Accuracy</span>
                <span className="text-[10px] px-2 py-0.5 rounded-md bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] font-semibold border border-[var(--border-subtle)]">
                  Target In Horizon
                </span>
              </div>
              <div className="text-2xl font-semibold tabular-nums text-[var(--accent-blue)] dark:text-[var(--accent-blue)]">
                {data.counts.triggeredEntries === 0 ? 'Insufficient data' : `${data.metricsWithDenominators.directionalAccuracy.rate}%`}
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                {data.metricsWithDenominators.directionalAccuracy.formatted}
              </p>
            </div>

            {/* Metric 6: Net Paper Expectancy */}
            <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-2 shadow-sm">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-[var(--text-secondary)]">Net Paper Expectancy</span>
                <span className="text-[10px] px-2 py-0.5 rounded-md bg-[var(--bg-surface-elevated)] text-[var(--text-muted)] font-semibold border border-[var(--border-subtle)]">
                  Per Setup
                </span>
              </div>
              <div
                className={`text-2xl font-semibold tabular-nums ${
                  data.counts.triggeredEntries === 0
                    ? 'text-[var(--text-muted)]'
                    : data.metricsWithDenominators.netPaperExpectancy.inr >= 0
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-rose-600 dark:text-rose-400'
                }`}
              >
                {data.counts.triggeredEntries === 0
                  ? 'Insufficient data'
                  : `${data.metricsWithDenominators.netPaperExpectancy.inr >= 0 ? '+' : ''}₹${data.metricsWithDenominators.netPaperExpectancy.inr.toFixed(2)}`}
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                {data.metricsWithDenominators.netPaperExpectancy.formatted}
              </p>
            </div>
          </div>

          {/* Counts & Timing Strip */}
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            <div className="p-3.5 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] space-y-1">
              <span className="text-[10px] text-[var(--text-muted)] font-semibold uppercase block">Total Generated</span>
              <span className="text-base font-semibold text-[var(--text-primary)] tabular-nums block">{data.counts.totalSignals}</span>
              <span className="text-[10px] text-[var(--text-muted)] block">
                {data.counts.callSignals} CE / {data.counts.putSignals} PE
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] space-y-1">
              <span className="text-[10px] text-[var(--text-muted)] font-semibold uppercase block">Triggered / Missed</span>
              <span className="text-base font-semibold text-[var(--text-primary)] tabular-nums block">
                {data.counts.triggeredEntries} / {data.counts.missedSetups}
              </span>
              <span className="text-[10px] text-[var(--text-muted)] block">
                {data.counts.expiredWithoutEntry} Expired
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] space-y-1">
              <span className="text-[10px] text-[var(--text-muted)] font-semibold uppercase block">Avg Time to T1</span>
              <span className="text-base font-semibold text-emerald-600 dark:text-emerald-400 tabular-nums block">{data.timings.avgTimeToT1}</span>
              <span className="text-[10px] text-[var(--text-muted)] block">Median: {data.timings.medianTimeToT1}</span>
            </div>

            <div className="p-3.5 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] space-y-1">
              <span className="text-[10px] text-[var(--text-muted)] font-semibold uppercase block">Avg Time to SL</span>
              <span className="text-base font-semibold text-rose-600 dark:text-rose-400 tabular-nums block">
                {data.timings.avgTimeToStopLoss}
              </span>
              <span className="text-[10px] text-[var(--text-muted)] block">Capital saved</span>
            </div>

            <div className="p-3.5 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] space-y-1">
              <span className="text-[10px] text-[var(--text-muted)] font-semibold uppercase block">Gross Paper Points</span>
              <span className="text-base font-semibold text-[var(--text-primary)] tabular-nums block">
                {data.financialPerformance.grossPaperPnLPoints} pts
              </span>
              <span className="text-[10px] text-[var(--text-muted)] block">1 lot basis</span>
            </div>

            <div className="p-3.5 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] space-y-1">
              <span className="text-[10px] text-[var(--text-muted)] font-semibold uppercase block">Net Paper P&L</span>
              <span
                className={`text-base font-semibold tabular-nums block ${
                  data.financialPerformance.netPaperPnLINR >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
                }`}
              >
                ₹{data.financialPerformance.netPaperPnLINR.toFixed(2)}
              </span>
              <span className="text-[10px] text-[var(--text-muted)] block">After brokerage</span>
            </div>
          </div>

          {/* Historical Summary Table (Browse Past Days) */}
          <div className="space-y-3 pt-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-7 h-7 rounded-lg bg-[var(--accent-blue-bg)] dark:bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)] dark:border-[var(--accent-blue)]/20 flex items-center justify-center text-[var(--accent-blue)]">
                  <Calendar className="w-4 h-4" />
                </div>
                <h3 className="text-sm font-semibold text-[var(--text-primary)] tracking-tight">
                  Historical Trading Sessions (Last 30 Days)
                </h3>
              </div>
              <span className="text-xs text-[var(--text-muted)]">Click any date to inspect full signal audit</span>
            </div>

            <div className="overflow-x-auto rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-sm">
              <table className="w-full text-xs text-left">
                <thead className="bg-[var(--bg-surface-elevated)] text-[var(--text-secondary)] border-b border-[var(--border-subtle)] font-semibold">
                  <tr>
                    <th className="p-3.5">Trading Date</th>
                    <th className="p-3.5">Total Setups</th>
                    <th className="p-3.5">Triggered Entries</th>
                    <th className="p-3.5">Target 1 Hits</th>
                    <th className="p-3.5">Stop Loss Hits</th>
                    <th className="p-3.5">T1 Hit Rate</th>
                    <th className="p-3.5">Final Win Rate</th>
                    <th className="p-3.5">Net Paper P&L</th>
                    <th className="p-3.5 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {historyList.map((row, idx) => (
                    <tr
                      key={idx}
                      onClick={() => setSelectedDate(row.date)}
                      className={`hover:bg-[var(--bg-surface-elevated)] cursor-pointer transition-colors ${
                        row.date === selectedDate ? 'bg-[var(--accent-blue-bg)]/60 dark:bg-[var(--accent-blue)]/10 border-l-2 border-[var(--accent-blue)]' : ''
                      }`}
                    >
                      <td className="p-3.5 font-semibold text-[var(--text-primary)] tabular-nums">{row.date}</td>
                      <td className="p-3.5 text-[var(--text-secondary)] tabular-nums font-medium">{row.totalSignals}</td>
                      <td className="p-3.5 text-[var(--text-secondary)] tabular-nums font-medium">{row.triggeredEntries}</td>
                      <td className="p-3.5 text-emerald-600 dark:text-emerald-400 tabular-nums font-semibold">{row.t1Hits}</td>
                      <td className="p-3.5 text-rose-600 dark:text-rose-400 tabular-nums font-semibold">{row.slHits}</td>
                      <td className="p-3.5 font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">{row.t1HitRate}</td>
                      <td className="p-3.5 font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">{row.finalWinRate}</td>
                      <td
                        className={`p-3.5 font-semibold tabular-nums ${
                          row.netPaperPnLINR >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
                        }`}
                      >
                        {row.netPaperPnLINR >= 0 ? `+₹${row.netPaperPnLINR.toFixed(2)}` : `-₹${Math.abs(row.netPaperPnLINR).toFixed(2)}`}
                      </td>
                      <td className="p-3.5 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedDate(row.date);
                          }}
                          className="px-3 py-1 rounded-lg bg-[var(--bg-surface-elevated)] hover:bg-[var(--bg-surface-hover)] text-[var(--text-primary)] border border-[var(--border-subtle)] text-[11px] font-semibold transition-colors"
                        >
                          View Audit
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
