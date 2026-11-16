"""
AIVOLVE Quantitative Options Intelligence Engine v3.0
Phase 7 / Step 7.5: Real-Time Intraday Drawdown Circuit Breaker Engine (REQ-7.5).

Enforces institutional portfolio capital preservation:
1. Calculates real-time cumulative daily net P&L:
   L_net_daily = Realized_Net_PnL_Today + Floating_Net_PnL_Open_Positions
2. Exact statutory fee deduction on realized and floating exits via IndianDerivativesCostCalculator.
3. Prevents duplicate realization & double-counting of partial exits.
4. Deterministic State Machine:
   - ARMED: Loss budget active; PnL within budget; quotes verified fresh.
   - DAILY_DRAWDOWN_BREACHED: L_net_daily <= -B_daily_max. Fails closed for new entries; exits permitted.
   - RISK_BUDGET_UNCONFIGURED: Loss budget unconfigured or pending governance approval.
   - PNL_DATA_UNAVAILABLE: Market quotes stale (>60s), missing, or offline for open positions.
5. Multi-index shared portfolio state: NIFTY, BANK NIFTY, FINNIFTY share the same breaker.
6. SENSEX remains strictly GOVERNANCE_LOCKED.
7. Crash-resilient atomic persistence: breaches cannot be bypassed by restarting the backend.
8. Zero side-effects: Stored in isolated state file; baseline artifacts remain 100% untouched.
"""

from typing import Dict, Any, List, Optional, Tuple, Union
import os
import json
import uuid
import math
import threading
from datetime import datetime, date, timezone
from enum import Enum
import zoneinfo

from app.data.market_calendar import MarketCalendar
from app.options.paper_trading.cost_calculator import IndianDerivativesCostCalculator
from app.core.logging import logger

IST_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")
DEFAULT_CB_STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "circuit_breaker_state.json")


class CircuitBreakerState(str, Enum):
    ARMED = "ARMED"
    DAILY_DRAWDOWN_BREACHED = "DAILY_DRAWDOWN_BREACHED"
    RISK_BUDGET_UNCONFIGURED = "RISK_BUDGET_UNCONFIGURED"
    PNL_DATA_UNAVAILABLE = "PNL_DATA_UNAVAILABLE"


class IntradayDrawdownCircuitBreaker:
    """
    Server-side Institutional Portfolio Circuit Breaker.
    Monitors daily cumulative drawdown across all benchmark indices.
    """

    def __init__(
        self,
        state_file_path: Optional[str] = None,
        auto_load: bool = True,
    ):
        self.state_file_path = os.path.abspath(state_file_path) if state_file_path else os.path.abspath(DEFAULT_CB_STATE_PATH)
        self._lock = threading.RLock()
        self._configured_budget_inr: Optional[float] = None
        self._budget_approved_by: Optional[str] = None
        self._budget_approval_reference: Optional[str] = None
        self._budget_approval_reason: Optional[str] = None
        self._budget_approval_date: Optional[str] = None

        self._active_breach: Optional[Dict[str, Any]] = None
        self._historical_breaches: List[Dict[str, Any]] = []
        self._configuration_audit_log: List[Dict[str, Any]] = []
        self._consumed_approval_references: set[str] = set()

        if auto_load:
            self._load_state()

    @property
    def state(self) -> str:
        """Returns current operational state enum string."""
        return self.get_status()["state"]

    # -------------------------------------------------------------------------
    # State Persistence (Atomic & Crash-Resilient)
    # -------------------------------------------------------------------------
    def _load_state(self):
        """Loads persistent breaker state and breach latches from disk."""
        with self._lock:
            if not os.path.exists(self.state_file_path):
                return
            try:
                with open(self.state_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                self._configured_budget_inr = data.get("configuredBudgetINR")
                self._budget_approved_by = data.get("budgetApprovedBy")
                self._budget_approval_reference = data.get("budgetApprovalReference")
                self._budget_approval_reason = data.get("budgetApprovalReason")
                self._budget_approval_date = data.get("budgetApprovalDate")

                self._active_breach = data.get("activeBreach")
                self._historical_breaches = data.get("historicalBreaches", [])
                self._configuration_audit_log = data.get("configurationAuditLog", [])
                self._consumed_approval_references = set(data.get("consumedApprovalReferences", []))

                # Session boundary check upon restart
                today_ist = self.get_current_session_date()
                if self._active_breach:
                    breach_session = self._active_breach.get("sessionDate")
                    if breach_session and breach_session != today_ist:
                        try:
                            breach_d = date.fromisoformat(breach_session)
                            today_d = date.fromisoformat(today_ist)
                            if today_d > breach_d:
                                # Archive expired breach to historical log only on strictly later trading session
                                self._historical_breaches.insert(0, dict(self._active_breach))
                                self._active_breach = None
                                self._save_state()
                        except Exception as e:
                            logger.error(f"[CircuitBreaker] Error comparing session boundary dates: {e}")
            except Exception as e:
                logger.error(f"[CircuitBreaker] Failed to load state from {self.state_file_path}: {e}")

    def _save_state(self):
        """Atomically saves breaker state to unique temporary file then renames."""
        with self._lock:
            storage_dir = os.path.dirname(self.state_file_path)
            os.makedirs(storage_dir, exist_ok=True)

            payload = {
                "configuredBudgetINR": self._configured_budget_inr,
                "budgetApprovedBy": self._budget_approved_by,
                "budgetApprovalReference": self._budget_approval_reference,
                "budgetApprovalReason": self._budget_approval_reason,
                "budgetApprovalDate": self._budget_approval_date,
                "activeBreach": self._active_breach,
                "historicalBreaches": self._historical_breaches[:50],
                "configurationAuditLog": self._configuration_audit_log[:50],
                "consumedApprovalReferences": sorted(list(self._consumed_approval_references)),
                "lastUpdated": MarketCalendar.format_ist_timestamp(),
            }

            serialized = json.dumps(payload, indent=2, ensure_ascii=False)
            tmp_path = os.path.join(storage_dir, f".cb_state_{uuid.uuid4().hex}.tmp")

            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(serialized)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(tmp_path, self.state_file_path)
            except Exception as e:
                logger.error(f"[CircuitBreaker] Failed to save state atomically: {e}")
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                raise

    def _record_audit_rejection(
        self,
        actor: str,
        approval_reference: Optional[str],
        reason_attempted: str,
        rejection_reason: str,
    ) -> None:
        """Atomically records an audit entry for rejected configuration attempts."""
        now_ist = MarketCalendar.format_ist_timestamp()
        entry = {
            "id": f"CFG-REJ-{uuid.uuid4().hex[:8].upper()}",
            "timestamp": now_ist,
            "actor": actor or "UNKNOWN",
            "approvalReference": approval_reference or "NONE",
            "reason": reason_attempted or "NONE",
            "action": "CONFIGURE_BUDGET",
            "outcome": "REJECTED",
            "rejectionReason": rejection_reason,
        }
        self._configuration_audit_log.insert(0, entry)
        try:
            self._save_state()
        except Exception as e:
            logger.error(f"[CircuitBreaker] Failed to save audit rejection entry: {e}")

    # -------------------------------------------------------------------------
    # Governance & Budget Configuration
    # -------------------------------------------------------------------------
    def configure_budget(
        self,
        budget_inr: Optional[float],
        approved_by: str,
        reason: str,
        approval_reference: Optional[str] = None,
        skip_governance_registry_check: bool = False,
    ) -> Dict[str, Any]:
        """
        Configures the daily loss budget with strict audit provenance, authority binding,
        and atomic single-use replay protection.
        Must only be invoked through verified server-side execution paths.
        """
        with self._lock:
            clean_approver = str(approved_by or "").strip().upper()
            clean_ref = str(approval_reference or "").strip().upper()
            clean_reason = str(reason or "").strip()

            # 1. Budget validation
            if budget_inr is not None:
                try:
                    b = float(budget_inr)
                    if math.isnan(b) or math.isinf(b) or b <= 0.0:
                        err = f"Daily loss budget must be a positive finite number. Got: {budget_inr}"
                        self._record_audit_rejection(clean_approver, clean_ref, clean_reason, err)
                        raise ValueError(err)
                    new_budget = round(b, 2)
                except (ValueError, TypeError, OverflowError) as exc:
                    err = f"Daily loss budget must be a positive finite number. Got: {budget_inr}"
                    self._record_audit_rejection(clean_approver, clean_ref, clean_reason, err)
                    raise ValueError(err) from exc
            else:
                new_budget = None

            # 2. Metadata validation
            if not clean_approver or not clean_reason:
                err = "Mandatory governance approval metadata required: 'approved_by' and 'reason'."
                self._record_audit_rejection(clean_approver, clean_ref, clean_reason, err)
                raise ValueError(err)

            # 3. Governance registry verification
            trusted_actor = clean_approver
            if not skip_governance_registry_check and new_budget is not None:
                if not clean_ref:
                    err = "Mandatory governance approval metadata required: 'approval_reference' is strictly required."
                    self._record_audit_rejection(clean_approver, clean_ref, clean_reason, err)
                    raise ValueError(err)

                # 3a. Single-use consumption / Replay prevention check
                if clean_ref in self._consumed_approval_references:
                    err = f"Governance authorization failed: Approval reference '{clean_ref}' has already been consumed (single-use replay violation)."
                    self._record_audit_rejection(clean_approver, clean_ref, clean_reason, err)
                    raise PermissionError(err)

                try:
                    from app.options.contract_selector import TRUSTED_APPROVAL_REGISTRY, REVOKED_APPROVAL_REFERENCES, PROCESSED_APPROVAL_IDS
                    if clean_ref in PROCESSED_APPROVAL_IDS:
                        err = f"Governance authorization failed: Approval reference '{clean_ref}' has already been processed in institutional ledger (single-use replay violation)."
                        self._record_audit_rejection(clean_approver, clean_ref, clean_reason, err)
                        raise PermissionError(err)

                    if clean_ref in REVOKED_APPROVAL_REFERENCES:
                        err = f"Governance authorization failed: Approval reference '{clean_ref}' is explicitly REVOKED."
                        self._record_audit_rejection(clean_approver, clean_ref, clean_reason, err)
                        raise PermissionError(err)

                    registered = TRUSTED_APPROVAL_REGISTRY.get(clean_ref)
                    if not registered:
                        err = f"Governance authorization failed: Unknown or unregistered approval reference '{clean_ref}'."
                        self._record_audit_rejection(clean_approver, clean_ref, clean_reason, err)
                        raise PermissionError(err)

                    reg_status = str(registered.get("status") or "").upper()
                    if reg_status != "ACTIVE":
                        err = f"Governance authorization failed: Approval reference '{clean_ref}' is not ACTIVE (status='{reg_status}')."
                        self._record_audit_rejection(clean_approver, clean_ref, clean_reason, err)
                        raise PermissionError(err)

                    registered_approver = str(registered.get("approved_by") or "").strip().upper()
                    if clean_approver != registered_approver:
                        err = f"Governance authorization failed: Forged approval identity. Caller '{clean_approver}' does not match registered authority '{registered_approver}' for reference '{clean_ref}'."
                        self._record_audit_rejection(clean_approver, clean_ref, clean_reason, err)
                        raise PermissionError(err)

                    # Bind actor strictly to server-verified registered authority
                    trusted_actor = registered_approver

                    exp_date_str = registered.get("expiry_date")
                    if exp_date_str:
                        today_ist_date = MarketCalendar.now_ist().date()
                        if date.fromisoformat(exp_date_str) < today_ist_date:
                            err = f"Governance authorization failed: Approval reference '{clean_ref}' expired on {exp_date_str}."
                            self._record_audit_rejection(clean_approver, clean_ref, clean_reason, err)
                            raise PermissionError(err)

                    # Consume reference atomically
                    self._consumed_approval_references.add(clean_ref)
                except (PermissionError, ValueError):
                    raise
                except Exception as ex:
                    logger.error(f"[CircuitBreaker] Governance registry verification error: {ex}")
                    err = f"Governance verification system error (failing closed): {ex}"
                    self._record_audit_rejection(clean_approver, clean_ref, clean_reason, err)
                    raise PermissionError(err) from ex

            # 4. Mutate & Audit Record
            prev_budget = self._configured_budget_inr
            now_ist = MarketCalendar.format_ist_timestamp()

            self._configured_budget_inr = new_budget
            self._budget_approved_by = trusted_actor
            self._budget_approval_reference = clean_ref if clean_ref else None
            self._budget_approval_reason = clean_reason
            self._budget_approval_date = now_ist

            audit_entry = {
                "id": f"CFG-{uuid.uuid4().hex[:8].upper()}",
                "timestamp": now_ist,
                "actor": trusted_actor,
                "approvalReference": clean_ref if clean_ref else None,
                "reason": clean_reason,
                "action": "CONFIGURE_BUDGET",
                "outcome": "SUCCESS",
                "previousBudgetINR": prev_budget,
                "newBudgetINR": new_budget,
            }
            self._configuration_audit_log.insert(0, audit_entry)
            self._save_state()

            logger.info(
                f"[CircuitBreaker] Budget configured: INR {new_budget} (was {prev_budget}) "
                f"by '{trusted_actor}' ref '{clean_ref}' ({clean_reason})"
            )

            return {
                "configuredBudgetINR": self._configured_budget_inr,
                "approvedBy": self._budget_approved_by,
                "approvalReference": self._budget_approval_reference,
                "reason": self._budget_approval_reason,
                "approvalDate": self._budget_approval_date,
                "auditRecord": audit_entry,
                "state": self.get_status()["state"],
            }

    configure_daily_budget = configure_budget
    configure_budget_server_side = configure_budget

    # -------------------------------------------------------------------------
    # Date & Session Helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def get_current_session_date(dt: Optional[datetime] = None) -> str:
        """
        Returns the authoritative NSE trading session date (YYYY-MM-DD IST).
        Weekends and exchange holidays are normalized to the most recent trading session,
        ensuring an active breach is never prematurely cleared outside trading hours.
        """
        now_dt = dt if dt is not None else MarketCalendar.now_ist()
        try:
            curr_d = now_dt.date() if isinstance(now_dt, datetime) else now_dt
            from datetime import timedelta
            # If not a trading day (weekend/holiday), resolve to most recent prior trading day
            while not MarketCalendar.is_trading_day(curr_d):
                curr_d -= timedelta(days=1)
            return curr_d.strftime("%Y-%m-%d")
        except Exception as e:
            logger.error(f"[CircuitBreaker] Calendar error resolving trading session: {e}")
            return now_dt.strftime("%Y-%m-%d")

    @staticmethod
    def parse_ist_datetime(ts_val: Optional[Union[str, datetime]]) -> Optional[datetime]:
        """Parses human IST timestamp string or ISO string into an aware datetime (Asia/Kolkata)."""
        if not ts_val:
            return None
        if isinstance(ts_val, datetime):
            if ts_val.tzinfo is None:
                return ts_val.replace(tzinfo=IST_ZONE)
            return ts_val.astimezone(IST_ZONE)
        s = str(ts_val).strip()
        # Format: "05 Nov 2026, 10:32 PM IST"
        try:
            return datetime.strptime(s, "%d %b %Y, %I:%M %p IST").replace(tzinfo=IST_ZONE)
        except Exception:
            pass
        # ISO format
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=IST_ZONE)
            return dt.astimezone(IST_ZONE)
        except Exception:
            pass
        return None

    @staticmethod
    def parse_ist_timestamp_date(ts_str: Optional[str]) -> Optional[str]:
        """Parses human IST timestamp string or ISO string into YYYY-MM-DD date."""
        if not ts_str:
            return None
        s = str(ts_str).strip()
        # Direct YYYY-MM-DD match
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return s
        # Format: "05 Nov 2026, 10:32 PM IST"
        try:
            dt = datetime.strptime(s, "%d %b %Y, %I:%M %p IST").replace(tzinfo=IST_ZONE)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
        # Format: "05 Nov 2026"
        try:
            dt = datetime.strptime(s[:11].strip(), "%d %b %Y").replace(tzinfo=IST_ZONE)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
        # Try ISO format
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST_ZONE)
            else:
                dt = dt.astimezone(IST_ZONE)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
        return None

    # -------------------------------------------------------------------------
    # P&L Calculation Engine (REQ-7.5 Blueprint Mandate)
    # -------------------------------------------------------------------------
    def calculate_daily_pnl(
        self,
        paper_engine_state: Dict[str, Any],
        session_date: Optional[str] = None,
        quotes: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Calculates L_net_daily = Realized_Net_PnL_Today + Floating_Net_PnL_Open_Positions.
        Strictly prevents double-counting and validates price freshness.
        """
        with self._lock:
            target_date = session_date or self.get_current_session_date()
            closed_trades = paper_engine_state.get("closedTrades", [])
            open_positions = paper_engine_state.get("openPositions", [])

            # 1. Realized Net P&L Today
            realized_today = 0.0
            closed_today_count = 0
            for trade in closed_trades:
                exit_ts = trade.get("exitTimestamp")
                trade_date = self.parse_ist_timestamp_date(exit_ts)
                if trade_date == target_date:
                    # trade["netPnl"] already includes all statutory fees and prior partial exits
                    realized_today += float(trade.get("netPnl") or 0.0)
                    closed_today_count += 1

            # Include partial exits on positions that are STILL OPEN
            partial_exits_today_count = 0
            for pos in open_positions:
                for partial in pos.get("partialExits", []):
                    p_ts = partial.get("timestamp")
                    p_date = self.parse_ist_timestamp_date(p_ts)
                    if p_date == target_date:
                        realized_today += float(partial.get("netPnl") or 0.0)
                        partial_exits_today_count += 1

            realized_today = round(realized_today, 2)

            # 2. Floating Net P&L of Open Positions
            floating_net_pnl = 0.0
            pnl_data_valid = True
            unavailability_reasons = []

            for pos in open_positions:
                contract_symbol = pos.get("contractSymbol")
                rem_qty = int(pos.get("remainingQuantity") or 0)
                entry_premium = float(pos.get("entryPremium") or 0.0)
                pos_type = pos.get("positionType", "BUY").upper()

                if rem_qty <= 0:
                    continue

                # Obtain current price and validate freshness strictly (REQ-7.5 Mandate)
                current_price = None
                is_fresh = False
                now_dt = MarketCalendar.now_ist()
                MAX_QUOTE_STALENESS_SECONDS = 60.0

                disqualified = {
                    "DATA_OFFLINE",
                    "DATA_UNAVAILABLE",
                    "STALE",
                    "STALE_TICK",
                    "ANOMALOUS",
                    "MOCK",
                    "SYNTHETIC",
                    "THEORETICAL",
                    "DEGRADED",
                }

                if quotes and contract_symbol in quotes:
                    q = quotes[contract_symbol]
                    data_status = str(q.get("dataStatus", "")).upper()
                    feed_status = str(q.get("feedStatus", "")).upper()
                    q_ts = q.get("timestamp")

                    if not q_ts:
                        unavailability_reasons.append(f"Quote for {contract_symbol} missing verifiable timestamp")
                    elif data_status in disqualified or feed_status in disqualified:
                        unavailability_reasons.append(
                            f"Quote for {contract_symbol} disqualified: dataStatus='{data_status}', feedStatus='{feed_status}'"
                        )
                    else:
                        q_dt = self.parse_ist_datetime(q_ts)
                        if q_dt is None:
                            unavailability_reasons.append(f"Quote for {contract_symbol} contains unparseable timestamp: '{q_ts}'")
                        else:
                            age_sec = (now_dt - q_dt).total_seconds()
                            if age_sec < -5.0 or age_sec > MAX_QUOTE_STALENESS_SECONDS:
                                unavailability_reasons.append(
                                    f"Quote for {contract_symbol} is stale ({age_sec:.1f}s > {MAX_QUOTE_STALENESS_SECONDS}s)"
                                )
                            else:
                                val = q.get("ltp") or q.get("bid") or q.get("lastPrice")
                                try:
                                    f_val = float(val) if val is not None else 0.0
                                    if f_val > 0.0 and not math.isnan(f_val) and not math.isinf(f_val):
                                        current_price = f_val
                                        is_fresh = True
                                    else:
                                        unavailability_reasons.append(f"Quote for {contract_symbol} contains non-positive LTP")
                                except (ValueError, TypeError, OverflowError):
                                    unavailability_reasons.append(f"Quote for {contract_symbol} contains invalid LTP: {val}")
                else:
                    # Strict provenance check on position cached quote (Never silently accept stale unverified premium)
                    p_ts = pos.get("lastQuoteTimestamp") or pos.get("entryTimestamp")
                    p_status = str(pos.get("lastDataStatus", "")).upper()
                    mf = pos.get("marketFeaturesAtEntry", {})
                    mf_status = str(mf.get("dataStatus", "")).upper()

                    if not p_ts:
                        unavailability_reasons.append(f"Position {contract_symbol} lacks verifiable quote timestamp")
                    elif p_status in disqualified or mf_status in disqualified:
                        unavailability_reasons.append(f"Position {contract_symbol} flagged with disqualified data status ({p_status or mf_status})")
                    else:
                        p_dt = self.parse_ist_datetime(p_ts)
                        if p_dt is None:
                            unavailability_reasons.append(f"Position {contract_symbol} quote timestamp unparseable: '{p_ts}'")
                        else:
                            age_sec = (now_dt - p_dt).total_seconds()
                            if age_sec < -5.0 or age_sec > MAX_QUOTE_STALENESS_SECONDS:
                                unavailability_reasons.append(
                                    f"Position {contract_symbol} quote timestamp is stale ({age_sec:.1f}s > {MAX_QUOTE_STALENESS_SECONDS}s)"
                                )
                            else:
                                pos_prem = pos.get("currentPremium")
                                try:
                                    f_prem = float(pos_prem) if pos_prem is not None else 0.0
                                    if f_prem > 0.0 and not math.isnan(f_prem) and not math.isinf(f_prem):
                                        current_price = f_prem
                                        is_fresh = True
                                    else:
                                        unavailability_reasons.append(f"Position {contract_symbol} contains non-positive currentPremium")
                                except (ValueError, TypeError, OverflowError):
                                    unavailability_reasons.append(f"Position {contract_symbol} contains invalid currentPremium")

                if not is_fresh or current_price is None:
                    pnl_data_valid = False
                    continue

                # Calculate realistic exit net P&L including statutory charges
                cost_res = IndianDerivativesCostCalculator.calculate_trade_costs_and_pnl(
                    entry_price=entry_premium,
                    exit_price=current_price,
                    quantity=rem_qty,
                    position_type=pos_type,
                    orders_count=1,
                )
                floating_net_pnl += cost_res["netPnl"]

            floating_net_pnl = round(floating_net_pnl, 2)
            net_daily_pnl = round(realized_today + floating_net_pnl, 2)

            return {
                "sessionDate": target_date,
                "realizedNetPnL": realized_today,
                "floatingNetPnL": floating_net_pnl,
                "netDailyPnL": net_daily_pnl,
                "closedTodayCount": closed_today_count,
                "partialExitsTodayCount": partial_exits_today_count,
                "openPositionsCount": len(open_positions),
                "pnlDataValid": pnl_data_valid,
                "unavailabilityReasons": unavailability_reasons,
            }

    # -------------------------------------------------------------------------
    # State Machine Evaluation
    # -------------------------------------------------------------------------
    def evaluate_circuit_breaker(
        self,
        paper_engine_state: Dict[str, Any],
        session_date: Optional[str] = None,
        quotes: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates the circuit breaker state machine:
        ARMED, DAILY_DRAWDOWN_BREACHED, RISK_BUDGET_UNCONFIGURED, PNL_DATA_UNAVAILABLE.
        """
        with self._lock:
            today_ist = session_date or self.get_current_session_date()

            # 1. Budget Configuration Check (Fail-closed on unconfigured budget)
            if self._configured_budget_inr is None:
                return {
                    "state": CircuitBreakerState.RISK_BUDGET_UNCONFIGURED.value,
                    "isPermitted": False,
                    "sessionDate": today_ist,
                    "configuredBudgetINR": None,
                    "netDailyPnL": None,
                    "realizedNetPnL": None,
                    "floatingNetPnL": None,
                    "reason": "RISK_BUDGET_UNCONFIGURED: Daily loss budget is pending governance approval; new entries blocked until explicitly configured.",
                    "activeBreach": None,
                }

            budget = self._configured_budget_inr

            # 2. Check Active Breach Latch for Current Session
            if self._active_breach and self._active_breach.get("sessionDate") == today_ist:
                return {
                    "state": CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value,
                    "isPermitted": False,
                    "sessionDate": today_ist,
                    "configuredBudgetINR": budget,
                    "netDailyPnL": self._active_breach.get("breachedPnl"),
                    "realizedNetPnL": self._active_breach.get("realizedPnl"),
                    "floatingNetPnL": self._active_breach.get("floatingPnl"),
                    "reason": f"DAILY_DRAWDOWN_BREACHED: Portfolio circuit breaker is tripped for session {today_ist}. New orders blocked.",
                    "activeBreach": self._active_breach,
                }

            # 3. Calculate Real-Time Daily Net P&L
            pnl_data = self.calculate_daily_pnl(
                paper_engine_state=paper_engine_state,
                session_date=today_ist,
                quotes=quotes,
            )

            # 4. Check Data Freshness / Validity
            if not pnl_data["pnlDataValid"] and pnl_data["openPositionsCount"] > 0:
                return {
                    "state": CircuitBreakerState.PNL_DATA_UNAVAILABLE.value,
                    "isPermitted": False,
                    "sessionDate": today_ist,
                    "configuredBudgetINR": budget,
                    "netDailyPnL": pnl_data["netDailyPnL"],
                    "realizedNetPnL": pnl_data["realizedNetPnL"],
                    "floatingNetPnL": pnl_data["floatingNetPnL"],
                    "reason": f"PNL_DATA_UNAVAILABLE: Stale, offline or unverified market prices on open positions ({'; '.join(pnl_data['unavailabilityReasons'])}).",
                    "unavailabilityReasons": pnl_data.get("unavailabilityReasons", []),
                    "activeBreach": None,
                }

            net_daily = pnl_data["netDailyPnL"]

            # 5. Check Threshold Breach (L_net_daily <= -B_daily_max)
            if net_daily <= -budget:
                # Trigger breach latch atomically
                now_ist = MarketCalendar.format_ist_timestamp()
                breach_record = {
                    "id": f"BRK-{uuid.uuid4().hex[:8].upper()}",
                    "sessionDate": today_ist,
                    "timestamp": now_ist,
                    "breachedPnl": net_daily,
                    "configuredBudget": budget,
                    "realizedPnl": pnl_data["realizedNetPnL"],
                    "floatingPnl": pnl_data["floatingNetPnL"],
                    "openPositionsCount": pnl_data["openPositionsCount"],
                    "reason": (
                        f"Cumulative daily net loss (₹{net_daily:,.2f}) breached "
                        f"daily risk budget (₹{budget:,.2f}) on {today_ist}."
                    ),
                }

                self._active_breach = breach_record
                self._save_state()

                logger.warning(
                    f"[CircuitBreaker] TRIP: Intraday loss {net_daily} <= -{budget}. "
                    f"Portfolio transitioning to DAILY_DRAWDOWN_BREACHED."
                )

                return {
                    "state": CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value,
                    "isPermitted": False,
                    "sessionDate": today_ist,
                    "configuredBudgetINR": budget,
                    "netDailyPnL": net_daily,
                    "realizedNetPnL": pnl_data["realizedNetPnL"],
                    "floatingNetPnL": pnl_data["floatingNetPnL"],
                    "reason": breach_record["reason"],
                    "activeBreach": breach_record,
                }

            # 6. Normal Healthy State: ARMED
            budget_remaining = round(budget + net_daily, 2)
            utilization_pct = round((abs(min(0.0, net_daily)) / max(1.0, budget)) * 100.0, 2)

            return {
                "state": CircuitBreakerState.ARMED.value,
                "isPermitted": True,
                "sessionDate": today_ist,
                "configuredBudgetINR": budget,
                "netDailyPnL": net_daily,
                "realizedNetPnL": pnl_data["realizedNetPnL"],
                "floatingNetPnL": pnl_data["floatingNetPnL"],
                "budgetRemainingINR": budget_remaining,
                "drawdownUtilizationPct": utilization_pct,
                "reason": "Portfolio drawdown within authorized daily risk budget. New orders permitted.",
                "activeBreach": None,
            }

    # -------------------------------------------------------------------------
    # Entry Gate Integration (Called by open_position and signal selectors)
    # -------------------------------------------------------------------------
    def evaluate_entry_eligibility(
        self,
        paper_engine_state: Dict[str, Any],
        instrument: str,
        session_date: Optional[str] = None,
        quotes: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Authoritative pre-entry gate. Verifies:
        1. SENSEX governance lock.
        2. Circuit breaker state machine clearance.
        """
        with self._lock:
            # SENSEX Governance Lock Invariant
            clean_inst = str(instrument).upper().strip()
            if "SENSEX" in clean_inst:
                return {
                    "state": "GOVERNANCE_LOCKED",
                    "isPermitted": False,
                    "reason": "Execution rejected: SENSEX is GOVERNANCE_LOCKED and unconfigured for trading.",
                }

            # Evaluate portfolio circuit breaker
            res = self.evaluate_circuit_breaker(
                paper_engine_state=paper_engine_state,
                session_date=session_date,
                quotes=quotes,
            )

            return res

    def is_entry_permitted(
        self,
        paper_engine_state: Optional[Dict[str, Any]] = None,
        session_date: Optional[str] = None,
    ) -> bool:
        """Fast boolean check for signal engines."""
        with self._lock:
            if self._configured_budget_inr is None:
                return False
            today_ist = session_date or self.get_current_session_date()
            if self._active_breach and self._active_breach.get("sessionDate") == today_ist:
                return False
            if paper_engine_state is not None:
                res = self.evaluate_circuit_breaker(paper_engine_state, session_date=today_ist)
                return bool(res.get("isPermitted", False))
            return True

    def recalculate_and_check(
        self,
        paper_engine_state: Dict[str, Any],
        session_date: Optional[str] = None,
        quotes: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Invoked after position closures or tick updates to refresh latch state."""
        return self.evaluate_circuit_breaker(
            paper_engine_state=paper_engine_state,
            session_date=session_date,
            quotes=quotes,
        )

    def get_status(
        self,
        paper_engine_state: Optional[Dict[str, Any]] = None,
        session_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Returns complete circuit breaker status payload for observability & API."""
        with self._lock:
            today_ist = session_date or self.get_current_session_date()
            if self._configured_budget_inr is None:
                return {
                    "state": CircuitBreakerState.RISK_BUDGET_UNCONFIGURED.value,
                    "isPermitted": False,
                    "sessionDate": today_ist,
                    "configuredBudgetINR": None,
                    "dailyBudgetINR": None,
                    "budgetApprovedBy": self._budget_approved_by,
                    "activeBreach": None,
                    "reason": "RISK_BUDGET_UNCONFIGURED: Daily loss budget is pending governance approval; new entries blocked until explicitly configured.",
                }

            if self._active_breach and self._active_breach.get("sessionDate") == today_ist:
                return {
                    "state": CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value,
                    "isPermitted": False,
                    "sessionDate": today_ist,
                    "configuredBudgetINR": self._configured_budget_inr,
                    "dailyBudgetINR": self._configured_budget_inr,
                    "budgetApprovedBy": self._budget_approved_by,
                    "activeBreach": self._active_breach,
                    "reason": self._active_breach.get("reason"),
                }

            if paper_engine_state is not None:
                return self.evaluate_circuit_breaker(paper_engine_state, session_date=today_ist)

            return {
                "state": CircuitBreakerState.ARMED.value,
                "isPermitted": True,
                "sessionDate": today_ist,
                "configuredBudgetINR": self._configured_budget_inr,
                "dailyBudgetINR": self._configured_budget_inr,
                "budgetApprovedBy": self._budget_approved_by,
                "activeBreach": None,
                "reason": "Portfolio drawdown within authorized daily risk budget. New orders permitted.",
            }

    def reset_session_for_new_day(self, new_session_date: Optional[str] = None):
        """Forces session boundary advancement for testing or new trading days."""
        with self._lock:
            target_date = new_session_date or self.get_current_session_date()
            if self._active_breach:
                self._historical_breaches.insert(0, dict(self._active_breach))
                self._active_breach = None
            self._save_state()
            logger.info(f"[CircuitBreaker] Session advanced to {target_date}. Active breach reset.")


# -----------------------------------------------------------------------------
# Central Singleton Accessor
# -----------------------------------------------------------------------------
_circuit_breaker_instance: Optional[IntradayDrawdownCircuitBreaker] = None
_instance_lock = threading.Lock()


def get_circuit_breaker(state_file_path: Optional[str] = None) -> IntradayDrawdownCircuitBreaker:
    """Returns the process-wide IntradayDrawdownCircuitBreaker instance."""
    global _circuit_breaker_instance
    with _instance_lock:
        if _circuit_breaker_instance is None or state_file_path is not None:
            _circuit_breaker_instance = IntradayDrawdownCircuitBreaker(state_file_path=state_file_path)
        return _circuit_breaker_instance


def set_circuit_breaker(instance: Optional[IntradayDrawdownCircuitBreaker]):
    """Sets or resets the singleton instance (primarily for testing)."""
    global _circuit_breaker_instance
    with _instance_lock:
        _circuit_breaker_instance = instance
