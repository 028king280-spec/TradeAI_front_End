import type { ResearchSetupEvaluation } from '@/types/options';

export function ResearchSetupCard({ data }: { data?: ResearchSetupEvaluation | null }) {
  const setup = data?.qualified ? data.setup : null;
  return <section className="workspace-panel space-y-3" aria-label="Second research engine">
    <div className="workspace-panel-heading"><div>
      <p className="workspace-eyebrow">Second engine · Research paper</p>
      <h2>60-point setups · +30% premium target</h2>
    </div><span className="text-sm">Score: {data?.score ?? 'N/A'}/100</span></div>
    <p className="text-xs text-[var(--text-muted)]">Qualified saved setups are eligible for automatic entry in the separate research paper account. Score is not a win probability; target is gross before fees and slippage.</p>
    {setup ? <><p className="font-semibold">{setup.contractSymbol}</p>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><dt>Entry premium</dt><dd>₹{setup.entryPremium.toFixed(2)}</dd></div>
        <div><dt>Target (+30%)</dt><dd>₹{setup.targetPremium.toFixed(2)}</dd></div>
        <div><dt>Stop-loss</dt><dd>₹{setup.stopLoss.toFixed(2)}</dd></div>
        <div><dt>Gross reward/risk</dt><dd>{setup.grossRewardRisk.toFixed(2)}:1</dd></div>
      </dl></> : <p className="text-sm text-[var(--text-secondary)]">{data ? (data.reasons.join(' · ') || 'No qualified research setup.') : 'Research evaluation unavailable.'}</p>}
    <a href="/paper-trading#research-paper" className="text-sm text-[var(--accent-blue)] underline">View research paper entries and exits</a>
    <p className="text-xs text-[var(--text-muted)]">{data?.journalSaved ? 'Saved in separate research journal' : 'Research journal not saved'}{data ? ` · ${data.timestamp}` : ''}</p>
  </section>;
}
