"""
AIVOLVE Phase 4, Step 4.9 — Paper Observation Gate & Controlled Session Runbook.

Enforces:
- Track separation: Offline Historical Replay vs Live Paper Observation
- Fail-closed gate when ANY open P0 exists, WebSocket has 0 usable ticks, or exchange is closed
- Complete controlled market observation runbook for Friday, 13 November 2026 (09:00-15:30 IST + EOD)
- Strict Controlled Defect-Fix Governance Protocol (no unapproved frozen code edits)
"""

from __future__ import annotations

from datetime import date
from typing import List, Sequence, Tuple

from app.backtesting.multi_year_calendar import MultiYearTradingCalendar
from app.backtesting.readiness_models import (
    ControlledFixProtocolRule,
    DEFAULT_OBSERVATION_SESSION_DATE,
    DefectRegisterEntry,
    DefectSeverity,
    LiveFeedObservationProbe,
    MarketObservationPlan,
    ObservationCheckpoint,
    ReadinessClassification,
)


DEFAULT_OBSERVATION_CHECKPOINTS: Tuple[ObservationCheckpoint, ...] = (
    ObservationCheckpoint(
        step_id="OBS-01",
        ist_window="08:45–09:00 IST",
        phase_focus="Pre-Market Auth, Tokens & Hash Baseline",
        objective="Authenticate Angel One SmartAPI REST/WebSocket cleanly in PAPER_TRADING_ONLY mode and verify persistence protection.",
        checks_to_verify=(
            "Confirm execution_mode == PAPER_TRADING_ONLY and broker order placement disabled",
            "Verify SmartAPI REST login succeeds and /api/health returns marketStatus=PRE_MARKET",
            "Verify 6 protected SHA-256 persistence baselines unchanged before session start",
            "Verify SENSEX remains GOVERNANCE_LOCKED",
        ),
        expected_pass_criteria=(
            "Authenticated REST session active without mock fallback",
            "6/6 SHA-256 protected hashes match baselines",
        ),
        abort_triggers=(
            "Any unexpected modification to protected persistence files or governance_ledger.db",
            "Any silent fallback to MOCK/SYNTHETIC data on NIFTY 50, BANK NIFTY, or FINNIFTY",
        ),
        logs_to_capture=(
            "pre_market_auth_status.json",
            "pre_market_hash_check.log",
        ),
    ),
    ObservationCheckpoint(
        step_id="OBS-02",
        ist_window="09:00–09:15 IST",
        phase_focus="Pre-Open Session & WebSocket Subscription",
        objective="Verify WebSocket subscription packets, token isolation, and pre-open stability before continuous matching.",
        checks_to_verify=(
            "Confirm SmartStream WebSocket connects and receives initial exchange heartbeats/ticks",
            "Verify subscribed instrument tokens map 1:1 without INDIA VIX vs NIFTY METAL collisions",
            "Verify pre-open candles remain excluded from closed-candle signal evaluation",
        ),
        expected_pass_criteria=(
            "WebSocket diagnostics show is_running=True and valid binary Mode 1/2/3 parsing",
            "Zero malformed packets or wrong-symbol token resolutions",
        ),
        abort_triggers=(
            "WebSocket reports STREAMING with 0 ticks after 09:16 IST",
            "Any token reverse-lookup mismatch or NaN/negative LTP",
        ),
        logs_to_capture=(
            "ws_diagnostics_0915.json",
            "live_status_0915.json",
        ),
    ),
    ObservationCheckpoint(
        step_id="OBS-03",
        ist_window="09:15–09:30 IST",
        phase_focus="NSE Cash/F&O Market Open & Opening Candle Integrity",
        objective="Observe opening volatility, completed-candle boundary gating, and stale/out-of-order tick handling.",
        checks_to_verify=(
            "Verify continuous live ticks flow with ticks_received > 0 and seconds_since_last_tick < 15s",
            "Verify 09:15 forming candles (1m/3m/5m/15m/1h) are NOT marked closed prior to bar_end_ist",
            "Confirm first 1m (09:16), 3m (09:18), 5m (09:20), and 15m (09:30) boundaries align cleanly",
        ),
        expected_pass_criteria=(
            "All open forming bars stay excluded by filter_completed_candles",
            "Zero future-dated or negative-sequence tick admissions",
        ),
        abort_triggers=(
            "Forming bar admitted as closed (look-ahead leakage)",
            "Feed latency exceeds 60s stale threshold without DEGRADED/STALE downgrade",
        ),
        logs_to_capture=(
            "opening_ticks_0915_0930.jsonl",
            "candle_boundary_audit_0930.json",
        ),
    ),
    ObservationCheckpoint(
        step_id="OBS-04",
        ist_window="09:30–12:00 IST",
        phase_focus="Morning Session Intelligence & Signal Funnel Observation",
        objective="Observe Phase 2 Regime/MTF + Phase 3 ICT/SMC + Paper Pipeline stages 1-11 read-only.",
        checks_to_verify=(
            "Track BUY_CE, BUY_PE, WAIT, NO_TRADE decisions and exact rejection reasons across NIFTY 50, BANK NIFTY, FINNIFTY",
            "Verify ICT predictive score remains explicitly UNAVAILABLE / NOT_CALIBRATED",
            "Confirm missing live options chain / OI / IV remains explicitly DATA_UNAVAILABLE (no synthetic backfill)",
            "Verify paper signal records persist only when Stage 1-11 qualification passes",
        ),
        expected_pass_criteria=(
            "Deterministic stage logs and clean timestamps across 15m/5m/3m/1m timeframes",
            "Zero accidental Sensex signal qualification or live order calls",
        ),
        abort_triggers=(
            "Any unverified/SYNTHETIC quote triggers trade qualification",
            "Pipeline exception or uncaught NaN propagation",
        ),
        logs_to_capture=(
            "morning_signal_funnel_0930_1200.jsonl",
            "ws_health_snapshots.jsonl",
        ),
    ),
    ObservationCheckpoint(
        step_id="OBS-05",
        ist_window="12:00–15:15 IST",
        phase_focus="Midday Compression, Afternoon Session & Disconnect Resilience",
        objective="Observe choppy/sideways regime lockout, VWAP/EMA drift, and tick continuity across institutional afternoon flow.",
        checks_to_verify=(
            "Verify SIDEWAYS / CONFLICTING MTF regimes correctly force NO_TRADE or WAIT",
            "Record sequence gaps, malformed packet counts, and REST fallback latency",
            "Monitor option chain spread/liquidity rejection logic when live quotes exist",
        ),
        expected_pass_criteria=(
            "Zero false breakout signals triggered on incomplete intraday bars",
            "Feed remains VERIFIED_LIVE or gracefully degrades to DEGRADED/DATA_UNAVAILABLE on disruption",
        ),
        abort_triggers=(
            "Silent synthetic/mock candle fallback during API rate limit (HTTP 429)",
            "Unbounded memory/queue growth in SSE client broadcast buffers",
        ),
        logs_to_capture=(
            "afternoon_signal_funnel_1200_1515.jsonl",
            "provider_retry_diagnostics.log",
        ),
    ),
    ObservationCheckpoint(
        step_id="OBS-06",
        ist_window="15:15–15:45 IST",
        phase_focus="Market Close Transition, Intraday Square-Off & EOD Reconciliation",
        objective="Observe 15:30 IST close transition into EOD settlement state and audit captured session artifacts.",
        checks_to_verify=(
            "Verify MarketCalendar transitions cleanly to POST_MARKET at 15:30 IST",
            "Verify DataQualityEngine marks post-15:30 quotes as VERIFIED_EOD with isTradeQualified=False",
            "Re-verify 6 protected SHA-256 hashes (or isolated observation log separation)",
            "Compare captured 1m/3m/5m/15m/1h live candles against Step 4.6 completeness validator",
        ),
        expected_pass_criteria=(
            "Clean EOD state transition with zero post-close trade qualifications",
            "Complete timestamp-aligned observation dataset archived inside backend/data/backtest/",
        ),
        abort_triggers=(
            "Post-15:30 quote remains marked isTradeQualified=True",
            "Protected production/ML file tampered outside authorized paper sandbox",
        ),
        logs_to_capture=(
            "eod_reconciliation_1545.json",
            "post_session_hash_check.log",
        ),
    ),
)


DEFAULT_FINAL_PASS_CRITERIA: Tuple[str, ...] = (
    "All live-data P0 defects (P0-1 through P0-5) resolved, authorized, and regression-verified (35/35 in test_p0_live_data_reliability.py).",
    "WebSocket connection sustains usable verified ticks (ticks_received > 0, no stale/future/duplicate/out-of-order leaks) during 09:15-15:30 IST.",
    "Zero incomplete/forming candles admitted by completed-candle filter across 1m, 3m, 5m, 15m, 1h.",
    "Zero silent MOCK or SYNTHETIC substitutions across API routes, providers, and option selectors.",
    "Post-session 6-file SHA-256 integrity verified and all captured observations reproducible under PAPER_TRADING_ONLY.",
)


DEFAULT_ABORT_TRIGGERS: Tuple[str, ...] = (
    "ABORT IMMEDIATELY if any execution path attempts live broker order routing or disables PAPER_TRADING_ONLY.",
    "ABORT IMMEDIATELY if any protected file (aivolve_trading.db, governance_ledger.db, paper/ML files) changes unexpectedly.",
    "ABORT IMMEDIATELY if an incomplete forming bar or future-timestamped tick produces BUY_CE or BUY_PE.",
    "ABORT IMMEDIATELY if SENSEX bypasses GOVERNANCE_LOCKED status.",
    "ABORT IMMEDIATELY if MOCK/SYNTHETIC candles are surfaced with dataStatus='LIVE'.",
)


DEFAULT_CONTROLLED_FIX_PROTOCOL: Tuple[ControlledFixProtocolRule, ...] = (
    ControlledFixProtocolRule(
        step_number=1,
        title="Inspect & Document Evidence Only",
        requirement="Step 4.9 records all P0/P1/P2 defects cleanly without mutating frozen Phase 1-3 or Step 4.2-4.8 source files.",
    ),
    ControlledFixProtocolRule(
        step_number=2,
        title="Propose Smallest Safe Diff",
        requirement="Draft minimal, single-purpose patch per P0 defect (e.g., fix duplicated 99926017 token, harden _coerce_bool_flag('nan'), align DATA_OFFLINE status).",
    ),
    ControlledFixProtocolRule(
        step_number=3,
        title="Obtain Explicit User Authorization",
        requirement="Request explicit user approval before modifying any frozen Phase 1-3 file.",
    ),
    ControlledFixProtocolRule(
        step_number=4,
        title="Re-Run Full Verification After Fix",
        requirement="Re-run test_p0_live_data_reliability.py (expect 35/35 pass), full Phase 4 suite, selected Phase 1-3 suite, Step 4.9 readiness gate, and 6-hash verification before opening live observation.",
    ),
)


class PaperObservationGate:
    """Evaluates offline vs live observation gates and builds the 13 Nov 2026 runbook."""

    def build_plan(
        self,
        probe: LiveFeedObservationProbe,
        defect_register: Sequence[DefectRegisterEntry],
        offline_classification: ReadinessClassification,
        target_session_date: str = DEFAULT_OBSERVATION_SESSION_DATE,
    ) -> MarketObservationPlan:
        cal46 = MultiYearTradingCalendar()
        target_d = date.fromisoformat(target_session_date)
        weekday_name = target_d.strftime("%A")
        is_trading_day = bool(probe.session_is_scheduled_trading_day and cal46.is_trading_day(target_d))

        open_p0_live = [
            d for d in defect_register if d.severity == DefectSeverity.P0 and d.status == "OPEN" and d.blocks_live_observation
        ]

        reasons: List[str] = []
        if not is_trading_day:
            reasons.append(f"Target session {target_session_date} ({weekday_name}) is NOT a scheduled NSE trading day.")
        if not probe.exchange_open:
            reasons.append(
                f"Exchange is currently closed (exchange_open={probe.exchange_open}); fail-closed gate prevents READY_LIVE status."
            )
        if not probe.rest_authenticated:
            reasons.append(f"REST provider '{probe.rest_provider_name}' is not authenticated in current process.")
        if not probe.websocket_connected:
            reasons.append("SmartStream WebSocket is not connected.")
        elif probe.usable_verified_ticks <= 0:
            reasons.append(
                "WebSocket is connected but has 0 usable verified ticks; a connected socket without verified ticks is never READY."
            )

        for d in open_p0_live:
            if d.defect_id != "P0-WS-ZERO-TICKS":
                reasons.append(f"[{d.defect_id}] {d.title}")

        preconditions_met = (len(open_p0_live) == 0) and is_trading_day and probe.exchange_open and probe.rest_authenticated and probe.websocket_connected and (probe.usable_verified_ticks > 0)

        if open_p0_live or not probe.exchange_open or not probe.rest_authenticated or not probe.websocket_connected or probe.usable_verified_ticks <= 0:
            live_gate_class = ReadinessClassification.BLOCKED_BY_P0
        else:
            live_gate_class = ReadinessClassification.CONDITIONAL_PAPER_OBSERVATION

        return MarketObservationPlan(
            target_session_date=target_session_date,
            target_weekday=weekday_name,
            is_scheduled_trading_day=is_trading_day,
            exchange_open_now=probe.exchange_open,
            live_observation_gate_classification=live_gate_class,
            offline_replay_gate_classification=offline_classification,
            preconditions_met=preconditions_met,
            blocking_reasons=tuple(reasons),
            checkpoints=DEFAULT_OBSERVATION_CHECKPOINTS,
            final_observation_pass_criteria=DEFAULT_FINAL_PASS_CRITERIA,
            mandatory_abort_triggers=DEFAULT_ABORT_TRIGGERS,
            controlled_fix_protocol=DEFAULT_CONTROLLED_FIX_PROTOCOL,
        )

