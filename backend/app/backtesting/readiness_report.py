"""
AIVOLVE Phase 4, Step 4.9 — Deterministic 15-Section Final Research Readiness Report Generator.

Produces `step4_9_research_readiness_report.md` inside `backend/data/backtest/`
strictly preserving PAPER_TRADING_ONLY governance, track-separated verdicts,
exact code/test P0 evidence, and the Friday 13 November 2026 observation runbook.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.backtesting.configuration import DEFAULT_BACKTEST_DATA_DIR, assert_isolated_backtest_path
from app.backtesting.readiness_models import ResearchReadinessReport


def generate_step4_9_readiness_markdown(report: ResearchReadinessReport) -> str:
    """Renders the deterministic 15-section Step 4.9 Readiness & Observation Report."""
    lines: list[str] = []

    # Header
    lines.append("# AIVOLVE — Phase 4, Step 4.9: Final Research Readiness Gate & Market Observation Report")
    lines.append("")
    lines.append(f"- **Readiness Gate ID:** `{report.readiness_id}`")
    lines.append(f"- **Report Fingerprint:** `{report.report_fingerprint}`")
    lines.append(f"- **Generated (UTC):** `{report.generated_at_utc}`")
    lines.append(f"- **Execution Mode:** `{report.execution_mode}` (Live Trading Authorized: `{report.live_trading_authorized}`)")
    lines.append(f"- **Notice:** {report.disclaimer}")
    lines.append("")

    # Section 1
    lines.append("## 1. Executive Readiness Decision")
    lines.append("")
    lines.append("| Track / Scope | Classification | Notes |")
    lines.append("|---|---|---|")
    lines.append(f"| **Overall Platform Readiness Gate** | `{report.overall_classification.value}` | Open P0={report.open_p0_count}, Open P1={report.open_p1_count}, Open P2={report.open_p2_count} |")
    lines.append(f"| **Offline Historical Replay Track** | `{report.offline_historical_replay_classification.value}` | {report.verified_matrix_combinations} verified matrix cells; {report.step4_7_run_count} Step 4.7 runs |")
    lines.append(f"| **Live Market Observation Track** | `{report.live_market_observation_classification.value}` | Requires P0 remediation + open exchange + authenticated REST + WS usable ticks |")
    lines.append(f"| **Strategy Evidence / Sample Proof** | `{report.strategy_evidence_classification.value}` | Step 4.8 `{report.step4_8_review_id}` ({report.closed_trade_count_total} closed trades; min 30) |")
    lines.append(f"| **Phase 3 ICT Predictive Score** | `{report.ict_score_status}` | Strictly uncalibrated; heuristic scorecard weights not promoted |")
    lines.append("")
    for item in report.ready_conditions_summary:
        lines.append(f"- {item}")
    lines.append("")

    # Sections 2-5 (Phase 1, Phase 2, Phase 3, Phase 4 + Governance)
    section_nums = [2, 3, 4, 5]
    for sec_no, phase in zip(section_nums, report.phase_audits[:4]):
        lines.append(f"## {sec_no}. {phase.phase_name}")
        lines.append("")
        lines.append(
            f"- **Offline Classification:** `{phase.offline_classification.value}` | "
            f"**Live Classification:** `{phase.live_classification.value}`"
        )
        lines.append("")
        lines.append("| Check ID | Area | Outcome | Summary |")
        lines.append("|---|---|---|---|")
        for chk in phase.checks:
            lines.append(f"| `{chk.check_id}` | {chk.area} | `{chk.outcome.value}` | {chk.summary} |")
        lines.append("")
        for note in phase.notes:
            lines.append(f"- _{note}_")
        lines.append("")

    # Section 6: Complete Defect Register
    lines.append("## 6. Complete P0 / P1 / P2 Defect & Ambiguity Register")
    lines.append("")
    lines.append("| Defect ID | Severity | Status | Component | Observed Evidence | Blocks Live | Blocks Offline |")
    lines.append("|---|---|---|---|---|---|---|")
    for d in report.defect_register:
        ev = d.observed_evidence.replace("|", "/")
        lines.append(
            f"| `{d.defect_id}` | `{d.severity.value}` | `{d.status}` | {d.component} | {ev} | `{d.blocks_live_observation}` | `{d.blocks_offline_replay}` |"
        )
    lines.append("")
    for d in report.defect_register:
        lines.append(f"- **`{d.defect_id}` ({d.severity.value}) — {d.title}:** Files `{', '.join(d.file_locations)}`. Minimal fix: {d.minimal_safe_fix}")
    lines.append("")

    # Section 7: Track-Separated Instrument Readiness Matrix
    lines.append("## 7. Track-Separated Readiness Matrix by Instrument")
    lines.append("")
    lines.append("| Instrument | Offline Historical Replay | Live Market Observation | Strategy Evidence | Verified TFs | Partial TFs | Governance Locked |")
    lines.append("|---|---|---|---|---|---|---|")
    for inst in report.instrument_decisions:
        vtfs = ", ".join(inst.verified_timeframes) or "NONE"
        ptfs = ", ".join(inst.partial_timeframes) or "NONE"
        lines.append(
            f"| `{inst.instrument}` | `{inst.historical_replay_classification.value}` | "
            f"`{inst.live_observation_classification.value}` | `{inst.evidence_classification.value}` | "
            f"{vtfs} | {ptfs} | `{inst.governance_locked}` |"
        )
    lines.append("")

    # Section 8: Pre-Observation Gate & Runtime Probe Snapshot
    p = report.probe_snapshot
    plan = report.observation_plan
    lines.append("## 8. Pre-Observation Preconditions & Runtime Probe Snapshot")
    lines.append("")
    lines.append(
        f"- **Probe Source:** `{p.probe_source}` | **Target Session:** `{plan.target_session_date}` ({plan.target_weekday}) | "
        f"**Scheduled Trading Day:** `{plan.is_scheduled_trading_day}` | **Exchange Open Now:** `{p.exchange_open}`"
    )
    lines.append(
        f"- **REST Provider:** `{p.rest_provider_name}` (`rest_authenticated={p.rest_authenticated}`) | "
        f"**WebSocket Connected:** `{p.websocket_connected}` | **Ticks Received:** `{p.ticks_received}` | "
        f"**Usable Verified Ticks:** `{p.usable_verified_ticks}`"
    )
    lines.append(
        f"- **Live Observation Preconditions Met:** `{plan.preconditions_met}` | "
        f"**Live Gate:** `{plan.live_observation_gate_classification.value}` | "
        f"**Offline Gate:** `{plan.offline_replay_gate_classification.value}`"
    )
    lines.append("")
    if plan.blocking_reasons:
        lines.append("### Active Pre-Observation Blocking Reasons")
        for r in plan.blocking_reasons:
            lines.append(f"- {r}")
        lines.append("")

    # Section 9: Controlled Market Observation Runbook (Friday, 13 Nov 2026)
    lines.append(f"## 9. Controlled Market Observation Runbook — {plan.target_weekday}, {plan.target_session_date} (IST)")
    lines.append("")
    for cp in plan.checkpoints:
        lines.append(f"### {cp.step_id}: `{cp.ist_window}` — {cp.phase_focus}")
        lines.append(f"- **Objective:** {cp.objective}")
        lines.append("- **Checks to Verify:** " + "; ".join(cp.checks_to_verify))
        lines.append("- **Pass Criteria:** " + "; ".join(cp.expected_pass_criteria))
        lines.append("- **Abort Triggers:** " + "; ".join(cp.abort_triggers))
        lines.append("- **Logs to Capture:** " + ", ".join(f"`{l}`" for l in cp.logs_to_capture))
        lines.append("")

    # Section 10: Controlled Defect-Fix Protocol
    lines.append("## 10. Controlled Defect-Fix & Re-Verification Protocol (Frozen Phase 1–3 Policy)")
    lines.append("")
    for rule in plan.controlled_fix_protocol:
        lines.append(f"{rule.step_number}. **{rule.title}:** {rule.requirement}")
    lines.append("")

    # Section 11: Final Observation Pass Criteria & Immediate Abort Triggers
    lines.append("## 11. Final Observation Pass Criteria & Mandatory Abort Triggers")
    lines.append("")
    lines.append("### Pass Criteria")
    for c in plan.final_observation_pass_criteria:
        lines.append(f"- {c}")
    lines.append("")
    lines.append("### Immediate Abort Triggers")
    for t in plan.mandatory_abort_triggers:
        lines.append(f"- {t}")
    lines.append("")

    # Section 12: Protected Persistence SHA-256 Verification
    lines.append("## 12. Persistence Protection & 6-File SHA-256 Verification")
    lines.append("")
    lines.append(f"- **All 6 Protected Files Matched:** `{report.protected_hashes_all_matched}` | **Backtest Storage Isolation Verified:** `{report.isolation_verified}`")
    lines.append("")
    lines.append("| File Label | Matched | Expected SHA-256 | Observed SHA-256 |")
    lines.append("|---|---|---|---|")
    for h in report.protected_hash_checks:
        lines.append(f"| `{h.label}` | `{h.matched}` | `{h.expected_sha256}` | `{h.observed_sha256 or 'MISSING'}` |")
    lines.append("")

    # Section 13: Governance & Safety Locks
    gov_phase = report.phase_audits[4]
    lines.append("## 13. Governance Locks, Paper Boundary & Synthetic Options Separation")
    lines.append("")
    for chk in gov_phase.checks:
        lines.append(f"- `{chk.check_id}` (`{chk.outcome.value}`): {chk.summary}")
    lines.append(f"- Real Historical Options Capability: `{report.missing_options_history_status}` (synthetic BS never conflated with market option quotes).")
    lines.append("")

    # Section 14: Deterministic Fingerprints & Scope Disclaimers
    lines.append("## 14. Deterministic Fingerprints & Provenance")
    lines.append("")
    lines.append(f"- **Step 4.8 Strategy Review Anchor:** `{report.step4_8_review_id}`")
    lines.append(f"- **Step 4.9 Readiness ID:** `{report.readiness_id}`")
    lines.append(f"- **Step 4.9 Canonical SHA-256 Fingerprint:** `{report.report_fingerprint}`")
    lines.append("")

    # Section 15: Final Gatekeeper Verdict & Next Authorized Action
    lines.append("## 15. Final Gatekeeper Verdict & Next Authorized Action")
    lines.append("")
    lines.append(f"- **Overall Platform Verdict:** `{report.overall_classification.value}`")
    lines.append(f"- **Offline Historical Research Track:** `{report.offline_historical_replay_classification.value}`")
    lines.append(f"- **Live Paper Observation Track (13 Nov 2026):** `{report.live_market_observation_classification.value}`")
    lines.append(f"- **Strategy Proof Track:** `{report.strategy_evidence_classification.value}`")
    lines.append("")
    lines.append(f"> **Gatekeeper Conclusion:** {report.final_recommendation}")
    lines.append("")
    return "\n".join(lines)


def write_step4_9_readiness_report(
    report: ResearchReadinessReport,
    output_path: Optional[Path | str] = None,
) -> Path:
    """Writes the Step 4.9 Markdown report inside the isolated backtest directory."""
    target = (
        Path(output_path)
        if output_path is not None
        else DEFAULT_BACKTEST_DATA_DIR / "step4_9_research_readiness_report.md"
    )
    resolved = assert_isolated_backtest_path(target)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(generate_step4_9_readiness_markdown(report), encoding="utf-8")
    return resolved

