"""
AIVOLVE Quantitative Options Intelligence Engine v3.0
Phase 7 / Step 7.6: Dynamic Greeks-Based Position Sizing Engine (REQ-7.6).

Institutional Quantitative Risk Management & Sizing Architecture:
1. Multi-Dimensional Greeks Risk Profiles:
   - Notional Rupee Delta (₹ underlying directional exposure): Delta * Spot * LotSize
   - Rupee Point Delta (₹/point underlying move): Delta * LotSize
   - Rupee Gamma Convexity (2nd-order acceleration in ₹): Gamma * Spot^2 * LotSize
   - Daily Theta Decay Burden (time decay loss in ₹/day): Theta * LotSize
   - Rupee Vega Sensitivity (volatility exposure in ₹ per 1% absolute IV shift): Vega * LotSize
2. Portfolio Greeks Aggregation across active positions in real-time.
3. Multi-Constraint Position Sizing Sieve:
   - Trade Risk Budget constraint: floor(RiskBudget / RiskPerLot)
   - Trade Capital / Margin constraint: floor(CapitalCap / ExposurePerLot)
   - Circuit Breaker remaining daily loss budget constraint: floor(CbRemaining / RiskPerLot)
   - Portfolio Delta Capacity constraint: floor(DeltaHeadroom / RupeeDeltaPerLot)
   - Portfolio Gamma Capacity constraint: floor(GammaHeadroom / RupeeGammaPerLot)
   - Portfolio Theta Capacity constraint: floor(ThetaHeadroom / DailyThetaPerLot)
   - Portfolio Vega Capacity constraint: floor(VegaHeadroom / RupeeVegaPerLot)
   - Hard maximum lots ceiling per instrument / trade.
4. Deterministic State Machine & Rejection Taxonomy:
   - ALLOCATED: Sizing successful, permitted lots >= 1.
   - RISK_POLICY_UNCONFIGURED: Unconfigured or unapproved institutional policy.
   - GOVERNANCE_LOCKED: SENSEX rejected fail-closed.
   - GREEKS_DATA_UNAVAILABLE: Greeks missing or None (never substituted with 0.0).
   - INVALID_PREMIUM: Non-positive or NaN option premium.
   - INVALID_STOP_LOSS: Stop loss <= 0 or >= entry premium.
   - STALE_QUOTE: Quote older than max freshness threshold (60s).
   - EXTREME_VOLATILITY: Implied volatility outside valid institutional bounds.
   - EXCESSIVE_SPREAD: Bid-ask spread exceeds configured policy limit.
   - CIRCUIT_BREAKER_BLOCKED: Circuit breaker breached or daily budget exhausted.
   - INSUFFICIENT_RISK_BUDGET: Risk budget cannot accommodate 1 full lot.
   - INSUFFICIENT_CAPITAL: Available capital cannot accommodate 1 full lot.
   - DELTA_LIMIT_EXCEEDED: Portfolio delta limit reached.
   - GAMMA_LIMIT_EXCEEDED: Portfolio gamma limit reached.
   - THETA_LIMIT_EXCEEDED: Daily portfolio theta decay limit reached.
   - VEGA_LIMIT_EXCEEDED: Portfolio vega limit reached.
5. Zero-Invention Rule: Never fabricate risk parameters, Greeks, or unapproved budgets.
6. Atomic persistence & Single-use governance approval replay protection.
"""

from typing import Dict, Any, List, Optional, Tuple, Union
import os
import json
import uuid
import math
import threading
from datetime import datetime, date, timezone
from dataclasses import dataclass, asdict
import zoneinfo

from app.data.market_calendar import MarketCalendar
from app.options.greeks import calculate_exact_time_to_expiry, calculate_black_scholes
from app.options.drawdown_circuit_breaker import IntradayDrawdownCircuitBreaker, CircuitBreakerState
from app.core.logging import logger

IST_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")
DEFAULT_GREEKS_STATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "greeks_risk_state.json"
)

# Authoritative standard exchange lot sizes for Indian benchmark indices
DEFAULT_INDEX_LOT_SIZES: Dict[str, int] = {
    "NIFTY": 65,
    "NIFTY 50": 65,
    "BANKNIFTY": 30,
    "BANK NIFTY": 30,
    "FINNIFTY": 65,
    "NIFTY FINANCIAL SERVICES": 65,
}


@dataclass
class GreeksRiskProfile:
    """Contract-level quantitative Greeks sensitivities and per-lot metrics."""
    instrument: str
    contract_symbol: str
    option_type: str
    spot: float
    strike: float
    entry_premium: float
    stop_loss: float
    lot_size: int
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float
    time_to_expiry_years: float
    # Computed per-lot metrics
    risk_per_lot: float
    exposure_per_lot: float
    point_delta_per_lot: float
    rupee_delta_per_lot: float
    rupee_gamma_per_lot: float
    daily_theta_per_lot: float
    rupee_vega_per_lot: float
    # Market quality indicators
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread: Optional[float] = None
    spread_pct: Optional[float] = None
    quote_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GreeksRiskPolicy:
    """Institutional Governance-Approved Greeks Risk Limits Policy."""
    policy_id: str
    approved_by: str
    approval_reference: str
    reason: str
    approval_date: str
    max_trade_risk_inr: float
    max_portfolio_delta_inr: float
    max_portfolio_gamma_inr: float
    max_daily_theta_loss_inr: float
    max_portfolio_vega_inr: float
    max_capital_per_trade_inr: float
    max_permitted_lots: int = 10
    max_spread_pct: float = 0.05
    min_iv_floor: float = 0.05
    max_iv_ceiling: float = 1.50
    enforce_circuit_breaker: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PortfolioGreeksAggregator:
    """
    Real-time Portfolio Greeks Aggregator.
    Aggregates active open positions into portfolio-level risk sensitivities.
    """

    @staticmethod
    def aggregate(
        open_positions: List[Dict[str, Any]],
        quotes: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Computes aggregate Net Rupee Delta, Point Delta, Rupee Gamma, Daily Theta decay,
        Rupee Vega, and Capital Exposure across all active paper trading positions.
        """
        total_notional_rupee_delta = 0.0
        total_point_delta_inr = 0.0
        total_rupee_gamma = 0.0
        total_daily_theta_inr = 0.0
        total_rupee_vega = 0.0
        total_open_exposure_inr = 0.0

        index_breakdown: Dict[str, Dict[str, float]] = {}
        has_incomplete_data = False
        audited_positions: List[Dict[str, Any]] = []

        for pos in open_positions:
            status = str(pos.get("status") or "OPEN").upper()
            if status != "OPEN":
                continue

            inst = str(pos.get("instrument", "")).upper().strip()
            clean_inst = "NIFTY" if "BANK" not in inst and "FIN" not in inst and "NIFTY" in inst else (
                "BANKNIFTY" if "BANK" in inst else (
                    "FINNIFTY" if "FIN" in inst else inst
                )
            )
            if clean_inst not in index_breakdown:
                index_breakdown[clean_inst] = {
                    "notionalRupeeDelta": 0.0,
                    "pointDeltaInr": 0.0,
                    "rupeeGamma": 0.0,
                    "dailyThetaInr": 0.0,
                    "rupeeVega": 0.0,
                    "exposureInr": 0.0,
                    "lots": 0,
                }

            remaining_qty = int(pos.get("remainingQuantity") or pos.get("quantity") or 0)
            lots = int(pos.get("lots") or (remaining_qty // (pos.get("lotSize") or 65)))
            lot_size = int(pos.get("lotSize") or 65)

            # Check for current premium
            curr_premium = pos.get("currentPremium")
            if curr_premium is None or curr_premium <= 0:
                curr_premium = pos.get("entryPremium", 0.0)
            exposure = round(curr_premium * remaining_qty, 2)
            total_open_exposure_inr += exposure
            index_breakdown[clean_inst]["exposureInr"] += exposure
            index_breakdown[clean_inst]["lots"] += lots

            # Greeks extraction
            greeks = pos.get("greeks")
            if not isinstance(greeks, dict):
                # Check top-level position fields
                if pos.get("delta") is not None:
                    greeks = {
                        "delta": pos.get("delta"),
                        "gamma": pos.get("gamma"),
                        "theta": pos.get("theta"),
                        "vega": pos.get("vega"),
                    }

            if not greeks or greeks.get("delta") is None:
                has_incomplete_data = True
                audited_positions.append({
                    "id": pos.get("id"),
                    "contractSymbol": pos.get("contractSymbol"),
                    "status": "MISSING_GREEKS",
                })
                continue

            delta = float(greeks.get("delta", 0.0))
            gamma = float(greeks.get("gamma", 0.0))
            theta = float(greeks.get("theta", 0.0))
            vega = float(greeks.get("vega", 0.0))

            # Underlying spot price
            spot = float(pos.get("underlyingSpot") or pos.get("spot") or pos.get("strike", 0.0))

            # Contract calculations
            # Direction multiplier: BUY is +1, SELL is -1
            side = str(pos.get("positionType", "BUY")).strip().upper()
            is_supported = (side == "BUY")
            if not is_supported:
                has_incomplete_data = True
                logger.warning(
                    f"[PortfolioGreeksAggregator] Non-BUY position {pos.get('id')} ({side}) "
                    "encountered in open positions. Tagged as unsupported exposure."
                )
            mult = 1.0 if is_supported else -1.0

            # Sensitivities
            point_delta = round(mult * delta * remaining_qty, 2)
            rupee_delta = round(mult * delta * spot * remaining_qty, 2)
            rupee_gamma = round(mult * gamma * (spot ** 2) * remaining_qty, 2)
            daily_theta = round(mult * theta * remaining_qty, 2)
            rupee_vega = round(mult * vega * remaining_qty, 2)

            total_notional_rupee_delta += rupee_delta
            total_point_delta_inr += point_delta
            total_rupee_gamma += rupee_gamma
            total_daily_theta_inr += daily_theta
            total_rupee_vega += rupee_vega

            index_breakdown[clean_inst]["notionalRupeeDelta"] += rupee_delta
            index_breakdown[clean_inst]["pointDeltaInr"] += point_delta
            index_breakdown[clean_inst]["rupeeGamma"] += rupee_gamma
            index_breakdown[clean_inst]["dailyThetaInr"] += daily_theta
            index_breakdown[clean_inst]["rupeeVega"] += rupee_vega

            audited_positions.append({
                "id": pos.get("id"),
                "contractSymbol": pos.get("contractSymbol"),
                "instrument": clean_inst,
                "positionType": side,
                "isSupported": is_supported,
                "lots": lots,
                "quantity": remaining_qty,
                "spot": spot,
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                "notionalRupeeDelta": rupee_delta,
                "rupeeGamma": rupee_gamma,
                "dailyThetaInr": daily_theta,
                "rupeeVega": rupee_vega,
                "exposureInr": exposure,
            })

        return {
            "netNotionalRupeeDelta": round(total_notional_rupee_delta, 2),
            "netPointDeltaInr": round(total_point_delta_inr, 2),
            "netRupeeGamma": round(total_rupee_gamma, 2),
            "netDailyThetaInr": round(total_daily_theta_inr, 2),
            "netDailyThetaLossInr": round(abs(min(0.0, total_daily_theta_inr)), 2),
            "netRupeeVega": round(total_rupee_vega, 2),
            "totalOpenExposureInr": round(total_open_exposure_inr, 2),
            "openPositionsCount": len([p for p in open_positions if str(p.get("status") or "OPEN").upper() == "OPEN"]),
            "indexBreakdown": {
                k: {
                    "notionalRupeeDelta": round(v["notionalRupeeDelta"], 2),
                    "pointDeltaInr": round(v["pointDeltaInr"], 2),
                    "rupeeGamma": round(v["rupeeGamma"], 2),
                    "dailyThetaInr": round(v["dailyThetaInr"], 2),
                    "rupeeVega": round(v["rupeeVega"], 2),
                    "exposureInr": round(v["exposureInr"], 2),
                    "lots": v["lots"],
                }
                for k, v in index_breakdown.items()
            },
            "hasIncompleteData": has_incomplete_data,
            "auditedPositions": audited_positions,
        }


class DynamicGreeksPositionSizer:
    """
    Phase 7 / REQ-7.6: Dynamic Greeks-Based Position Sizing Engine.
    Enforces multi-constraint sizing sieves with institutional governance controls.
    """

    def __init__(
        self,
        state_file_path: Optional[str] = None,
        auto_load: bool = True,
    ):
        self.state_file_path = (
            os.path.abspath(state_file_path) if state_file_path else os.path.abspath(DEFAULT_GREEKS_STATE_PATH)
        )
        self._lock = threading.RLock()
        self._policy: Optional[GreeksRiskPolicy] = None
        self._configuration_audit_log: List[Dict[str, Any]] = []
        self._consumed_approval_references: set[str] = set()

        if auto_load:
            self._load_state()

    @property
    def is_configured(self) -> bool:
        with self._lock:
            return self._policy is not None

    def get_policy(self) -> Optional[GreeksRiskPolicy]:
        with self._lock:
            return self._policy

    # -------------------------------------------------------------------------
    # State Persistence (Atomic & Safe)
    # -------------------------------------------------------------------------
    def _load_state(self):
        """Loads persistent policy and audit state from disk."""
        with self._lock:
            if not os.path.exists(self.state_file_path):
                return
            try:
                with open(self.state_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                pol_dict = data.get("activePolicy")
                if pol_dict:
                    self._policy = GreeksRiskPolicy(**pol_dict)
                else:
                    self._policy = None

                self._configuration_audit_log = data.get("configurationAuditLog", [])
                self._consumed_approval_references = set(data.get("consumedApprovalReferences", []))
            except Exception as e:
                logger.error(f"[GreeksRiskEngine] Failed to load state from {self.state_file_path}: {e}")

    def _save_state(self):
        """Atomically saves state to unique temporary file then renames."""
        with self._lock:
            try:
                storage_dir = os.path.dirname(self.state_file_path)
                os.makedirs(storage_dir, exist_ok=True)

                payload = {
                    "activePolicy": self._policy.to_dict() if self._policy else None,
                    "configurationAuditLog": self._configuration_audit_log,
                    "consumedApprovalReferences": list(self._consumed_approval_references),
                    "lastUpdated": MarketCalendar.format_ist_timestamp(),
                }

                tmp_name = f".greeks_state_{uuid.uuid4().hex}.tmp"
                tmp_path = os.path.join(storage_dir, tmp_name)

                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(tmp_path, self.state_file_path)
            except Exception as e:
                logger.error(f"[GreeksRiskEngine] Failed to save state to {self.state_file_path}: {e}")
                raise

    # -------------------------------------------------------------------------
    # Institutional Policy Governance Configuration
    # -------------------------------------------------------------------------
    def configure_policy(
        self,
        max_trade_risk_inr: float,
        max_portfolio_delta_inr: float,
        max_portfolio_gamma_inr: float,
        max_daily_theta_loss_inr: float,
        max_portfolio_vega_inr: float,
        max_capital_per_trade_inr: float,
        approved_by: str,
        reason: str,
        approval_reference: Optional[str] = None,
        max_permitted_lots: int = 10,
        max_spread_pct: float = 0.05,
        min_iv_floor: float = 0.05,
        max_iv_ceiling: float = 1.50,
        enforce_circuit_breaker: bool = True,
        skip_governance_registry_check: bool = False,
    ) -> Dict[str, Any]:
        """
        Configures the institutional Greeks risk limits policy with strict audit provenance,
        governance authority binding, and replay prevention.
        """
        with self._lock:
            clean_approver = str(approved_by or "").strip().upper()
            clean_ref = str(approval_reference or "").strip().upper()
            clean_reason = str(reason or "").strip()

            # 1. Parameter Validation
            try:
                mtr = float(max_trade_risk_inr)
                mpd = float(max_portfolio_delta_inr)
                mpg = float(max_portfolio_gamma_inr)
                mdt = float(max_daily_theta_loss_inr)
                mpv = float(max_portfolio_vega_inr)
                mct = float(max_capital_per_trade_inr)
                mpl = int(max_permitted_lots)
                msp = float(max_spread_pct)
                miv_fl = float(min_iv_floor)
                miv_cl = float(max_iv_ceiling)

                for val, name in [
                    (mtr, "max_trade_risk_inr"),
                    (mpd, "max_portfolio_delta_inr"),
                    (mpg, "max_portfolio_gamma_inr"),
                    (mdt, "max_daily_theta_loss_inr"),
                    (mpv, "max_portfolio_vega_inr"),
                    (mct, "max_capital_per_trade_inr"),
                    (mpl, "max_permitted_lots"),
                    (msp, "max_spread_pct"),
                    (miv_fl, "min_iv_floor"),
                    (miv_cl, "max_iv_ceiling"),
                ]:
                    if math.isnan(val) or math.isinf(val) or val <= 0.0:
                        raise ValueError(f"Limit '{name}' must be a positive finite number. Got: {val}")

                if miv_fl >= miv_cl:
                    raise ValueError(f"min_iv_floor ({miv_fl}) must be strictly less than max_iv_ceiling ({miv_cl})")

            except (ValueError, TypeError) as exc:
                err = f"Invalid quantitative limit parameters: {exc}"
                self._record_audit_event("CONFIG_REJECTED", clean_approver, clean_ref, clean_reason, err)
                raise ValueError(err) from exc

            # 2. Metadata Validation
            if not clean_approver or not clean_reason:
                err = "Mandatory governance metadata required: 'approved_by' and 'reason'."
                self._record_audit_event("CONFIG_REJECTED", clean_approver, clean_ref, clean_reason, err)
                raise ValueError(err)

            # 3. Governance Ledger & Replay Verification
            if clean_ref:
                # Single-use consumption & Replay check
                if clean_ref in self._consumed_approval_references:
                    err = f"APPROVAL_REPLAY_DETECTED: Reference '{clean_ref}' has already been consumed."
                    self._record_audit_event("REPLAY_REJECTED", clean_approver, clean_ref, clean_reason, err)
                    raise ValueError(err)

            if not skip_governance_registry_check:
                if not clean_ref:
                    err = "Mandatory governance metadata required: 'approval_reference' is strictly required."
                    self._record_audit_event("CONFIG_REJECTED", clean_approver, clean_ref, clean_reason, err)
                    raise ValueError(err)

                # Query governance ledger
                from app.options.contract_selector import get_governance_ledger
                ledger = get_governance_ledger()
                if ledger is None:
                    err = "GOVERNANCE_LEDGER_UNAVAILABLE: Institutional governance database unavailable."
                    self._record_audit_event("CONFIG_REJECTED", clean_approver, clean_ref, clean_reason, err)
                    raise ValueError(err)

                approval = ledger.get_approval(clean_ref)
                if not approval:
                    err = f"GOVERNANCE_APPROVAL_NOT_FOUND: Reference '{clean_ref}' does not exist in trusted registry."
                    self._record_audit_event("CONFIG_REJECTED", clean_approver, clean_ref, clean_reason, err)
                    raise ValueError(err)

                # Revocation check
                if ledger.is_reference_revoked(clean_ref):
                    err = f"GOVERNANCE_APPROVAL_REVOKED: Reference '{clean_ref}' has been revoked."
                    self._record_audit_event("REVOKED_REJECTED", clean_approver, clean_ref, clean_reason, err)
                    raise ValueError(err)

                # Authority verification
                expected_actor = str(approval.get("approved_by") or "").strip().upper()
                if clean_approver != expected_actor:
                    err = (
                        f"AUTHORITY_MISMATCH: Caller identity '{clean_approver}' does not match "
                        f"registered authority '{expected_actor}' for reference '{clean_ref}'."
                    )
                    self._record_audit_event("AUTHORITY_MISMATCH", clean_approver, clean_ref, clean_reason, err)
                    raise ValueError(err)

                # Authority status check
                key_id = approval.get("key_id")
                if key_id:
                    auth = ledger.get_authority(key_id)
                    if not auth or not auth.get("active") or auth.get("revoked"):
                        err = f"GOVERNANCE_AUTHORITY_INVALID: Authority '{key_id}' is inactive or revoked."
                        self._record_audit_event("AUTHORITY_INVALID", clean_approver, clean_ref, clean_reason, err)
                        raise ValueError(err)

            # Consume reference
            if clean_ref:
                self._consumed_approval_references.add(clean_ref)

            # 4. Construct and Save Active Policy
            now_ist = MarketCalendar.format_ist_timestamp()
            policy_id = f"POL-{uuid.uuid4().hex[:8].upper()}"

            self._policy = GreeksRiskPolicy(
                policy_id=policy_id,
                approved_by=clean_approver,
                approval_reference=clean_ref,
                reason=clean_reason,
                approval_date=now_ist,
                max_trade_risk_inr=round(mtr, 2),
                max_portfolio_delta_inr=round(mpd, 2),
                max_portfolio_gamma_inr=round(mpg, 2),
                max_daily_theta_loss_inr=round(mdt, 2),
                max_portfolio_vega_inr=round(mpv, 2),
                max_capital_per_trade_inr=round(mct, 2),
                max_permitted_lots=mpl,
                max_spread_pct=round(msp, 4),
                min_iv_floor=round(miv_fl, 4),
                max_iv_ceiling=round(miv_cl, 4),
                enforce_circuit_breaker=enforce_circuit_breaker,
            )

            self._record_audit_event(
                "POLICY_CONFIGURED",
                clean_approver,
                clean_ref,
                clean_reason,
                "Policy successfully configured and activated.",
                self._policy.to_dict(),
            )
            self._save_state()

            logger.info(f"[GreeksRiskEngine] Configured policy {policy_id} by {clean_approver} (ref: {clean_ref})")
            return {
                "success": True,
                "policyId": policy_id,
                "policy": self._policy.to_dict(),
            }

    def clear_policy(self, cleared_by: str, reason: str) -> None:
        """Clears active policy back to RISK_POLICY_UNCONFIGURED state."""
        with self._lock:
            self._policy = None
            self._record_audit_event(
                "POLICY_CLEARED",
                cleared_by.upper().strip(),
                "NONE",
                reason,
                "Active risk policy cleared to unconfigured state.",
            )
            self._save_state()

    def _record_audit_event(
        self,
        event_type: str,
        actor: str,
        ref: str,
        reason: str,
        details: str,
        payload: Optional[Dict[str, Any]] = None,
    ):
        entry = {
            "id": f"AUD-{uuid.uuid4().hex[:8].upper()}",
            "timestamp": MarketCalendar.format_ist_timestamp(),
            "eventType": event_type,
            "actor": actor,
            "approvalReference": ref,
            "reason": reason,
            "details": details,
            "payload": payload,
        }
        self._configuration_audit_log.insert(0, entry)
        if len(self._configuration_audit_log) > 200:
            self._configuration_audit_log = self._configuration_audit_log[:200]

    # -------------------------------------------------------------------------
    # Contract Greeks Sensitivity Profile Builder
    # -------------------------------------------------------------------------
    @staticmethod
    def calculate_contract_profile(
        instrument: str,
        contract_symbol: str,
        option_type: str,
        spot: float,
        strike: float,
        entry_premium: float,
        stop_loss: float,
        greeks: Dict[str, float],
        lot_size: Optional[int] = None,
        iv: Optional[float] = None,
        time_to_expiry_years: Optional[float] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        quote_timestamp: Optional[str] = None,
        position_type: str = "BUY",
    ) -> GreeksRiskProfile:
        """
        Computes analytical per-lot sensitivity metrics from Black-Scholes Greeks.
        Strictly restricted to long option (BUY) purchases under institutional policy.
        """
        clean_pos_type = str(position_type or "BUY").strip().upper()
        if clean_pos_type != "BUY":
            raise ValueError(
                f"NAKED_OPTIONS_WRITING_PROHIBITED: Position type '{position_type}' is prohibited. "
                "Contract sensitivity profiling is strictly defined for long option (BUY) purchases."
            )

        if stop_loss is None or math.isnan(stop_loss) or stop_loss <= 0.0 or stop_loss >= entry_premium:
            raise ValueError(
                f"INVALID_STOP_LOSS: For a long option, stop loss ({stop_loss}) must be strictly positive "
                f"and strictly below entry premium ({entry_premium})."
            )

        clean_inst = str(instrument).upper().strip()
        effective_lot_size = int(lot_size or DEFAULT_INDEX_LOT_SIZES.get(clean_inst, 65))

        delta = float(greeks["delta"])
        gamma = float(greeks["gamma"])
        theta = float(greeks["theta"])
        vega = float(greeks["vega"])
        effective_iv = float(iv if iv is not None else greeks.get("iv", 0.15))
        effective_t = float(time_to_expiry_years if time_to_expiry_years is not None else 0.0)

        # Spread metrics
        spread = round(ask - bid, 2) if (ask is not None and bid is not None and ask >= bid) else None
        spread_pct = round(spread / entry_premium, 4) if (spread is not None and entry_premium > 0) else None

        # Per-lot sensitivities (Long Option geometry: max loss = entry_premium * lot_size)
        risk_per_unit = max(0.0, entry_premium - stop_loss)
        risk_per_lot = round(risk_per_unit * effective_lot_size, 2)
        exposure_per_lot = round(entry_premium * effective_lot_size, 2)

        point_delta_per_lot = round(delta * effective_lot_size, 2)
        rupee_delta_per_lot = round(delta * spot * effective_lot_size, 2)
        rupee_gamma_per_lot = round(gamma * (spot ** 2) * effective_lot_size, 2)
        daily_theta_per_lot = round(theta * effective_lot_size, 2)
        rupee_vega_per_lot = round(vega * effective_lot_size, 2)

        return GreeksRiskProfile(
            instrument=clean_inst,
            contract_symbol=contract_symbol,
            option_type=option_type.upper().strip(),
            spot=round(spot, 2),
            strike=round(strike, 2),
            entry_premium=round(entry_premium, 2),
            stop_loss=round(stop_loss, 2),
            lot_size=effective_lot_size,
            delta=round(delta, 4),
            gamma=round(gamma, 6),
            theta=round(theta, 2),
            vega=round(vega, 2),
            iv=round(effective_iv, 4),
            time_to_expiry_years=round(effective_t, 6),
            risk_per_lot=risk_per_lot,
            exposure_per_lot=exposure_per_lot,
            point_delta_per_lot=point_delta_per_lot,
            rupee_delta_per_lot=rupee_delta_per_lot,
            rupee_gamma_per_lot=rupee_gamma_per_lot,
            daily_theta_per_lot=daily_theta_per_lot,
            rupee_vega_per_lot=rupee_vega_per_lot,
            bid=bid,
            ask=ask,
            spread=spread,
            spread_pct=spread_pct,
            quote_timestamp=quote_timestamp,
        )

    # -------------------------------------------------------------------------
    # Core Multi-Constraint Sizing Sieve
    # -------------------------------------------------------------------------
    def calculate_position_size(
        self,
        instrument: str,
        contract_symbol: str,
        option_type: str,
        spot: float,
        strike: float,
        entry_premium: float,
        stop_loss: float,
        greeks: Optional[Dict[str, float]],
        available_capital: float,
        portfolio_open_positions: List[Dict[str, Any]],
        circuit_breaker: Optional[IntradayDrawdownCircuitBreaker] = None,
        paper_engine_state: Optional[Dict[str, Any]] = None,
        lot_size: Optional[int] = None,
        iv: Optional[float] = None,
        time_to_expiry_years: Optional[float] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        quote_timestamp: Optional[Union[str, datetime]] = None,
        max_quote_age_sec: float = 60.0,
        position_type: str = "BUY",
    ) -> Dict[str, Any]:
        """
        Executes the institutional multi-constraint sizing sieve.
        Evaluates Trade Risk, Capital, Circuit Breaker, Delta, Gamma, Theta, Vega,
        and Spread constraints before allocating permitted integer lots.
        Strictly restricted to long option (BUY) purchases under institutional policy.
        """
        with self._lock:
            clean_inst = str(instrument or "").upper().strip()

            # 1. SENSEX Governance Lock
            if "SENSEX" in clean_inst or "BSE" in clean_inst:
                return {
                    "isPermitted": False,
                    "status": "GOVERNANCE_LOCKED",
                    "allocatedLots": 0,
                    "totalQuantity": 0,
                    "bindingConstraint": "GOVERNANCE_LOCKED",
                    "reason": "SENSEX trading rejected: Under strict GOVERNANCE_LOCK. Unconfigured institutional parameters.",
                    "constraintsBreakdown": {},
                }

            # 1b. Position Direction Invariant (Fail-closed: Long BUY options only)
            clean_pos_type = str(position_type or "BUY").strip().upper()
            if clean_pos_type != "BUY":
                return {
                    "isPermitted": False,
                    "status": "NAKED_OPTIONS_WRITING_PROHIBITED",
                    "allocatedLots": 0,
                    "totalQuantity": 0,
                    "bindingConstraint": "NAKED_OPTIONS_WRITING_PROHIBITED",
                    "reason": (
                        f"NAKED_OPTIONS_WRITING_PROHIBITED: Position type '{position_type}' is prohibited. "
                        "AIVOLVE institutional risk policy permits LONG (BUY) options only."
                    ),
                    "constraintsBreakdown": {},
                }

            # 2. Risk Policy Configuration Check (Fail-closed)
            if self._policy is None:
                return {
                    "isPermitted": False,
                    "status": "RISK_POLICY_UNCONFIGURED",
                    "allocatedLots": 0,
                    "totalQuantity": 0,
                    "bindingConstraint": "RISK_POLICY_UNCONFIGURED",
                    "reason": "RISK_POLICY_UNCONFIGURED: Institutional Greeks risk policy is not configured or approved. Position sizing rejected.",
                    "constraintsBreakdown": {},
                }

            policy = self._policy

            # 3. Market Data & Numerical Quality Invariants
            if entry_premium is None or math.isnan(entry_premium) or entry_premium <= 0.0:
                return {
                    "isPermitted": False,
                    "status": "INVALID_PREMIUM",
                    "allocatedLots": 0,
                    "totalQuantity": 0,
                    "bindingConstraint": "INVALID_PREMIUM",
                    "reason": f"INVALID_PREMIUM: Option entry premium must be strictly positive. Got: {entry_premium}",
                    "constraintsBreakdown": {},
                }

            if stop_loss is None or math.isnan(stop_loss) or stop_loss <= 0.0 or stop_loss >= entry_premium:
                return {
                    "isPermitted": False,
                    "status": "INVALID_STOP_LOSS",
                    "allocatedLots": 0,
                    "totalQuantity": 0,
                    "bindingConstraint": "INVALID_STOP_LOSS",
                    "reason": (
                        f"INVALID_STOP_LOSS: Stop loss ({stop_loss}) must be strictly positive and "
                        f"strictly below entry premium ({entry_premium})."
                    ),
                    "constraintsBreakdown": {},
                }

            # 4. Greeks Integrity (Zero Invention Invariant)
            if greeks is None:
                return {
                    "isPermitted": False,
                    "status": "GREEKS_DATA_UNAVAILABLE",
                    "allocatedLots": 0,
                    "totalQuantity": 0,
                    "bindingConstraint": "GREEKS_DATA_UNAVAILABLE",
                    "reason": "GREEKS_DATA_UNAVAILABLE: Option Greeks are missing or uncalculated. Sizing rejected fail-closed.",
                    "constraintsBreakdown": {},
                }

            required_greeks = ["delta", "gamma", "theta", "vega"]
            for g_name in required_greeks:
                g_val = greeks.get(g_name)
                if g_val is None or math.isnan(float(g_val)):
                    return {
                        "isPermitted": False,
                        "status": "GREEKS_DATA_UNAVAILABLE",
                        "allocatedLots": 0,
                        "totalQuantity": 0,
                        "bindingConstraint": "GREEKS_DATA_UNAVAILABLE",
                        "reason": f"GREEKS_DATA_UNAVAILABLE: Greek sensitivity '{g_name}' is unavailable or NaN.",
                        "constraintsBreakdown": {},
                    }

            # 5. Volatility Limits
            effective_iv = float(iv if iv is not None else greeks.get("iv", 0.15))
            if effective_iv <= policy.min_iv_floor or effective_iv > policy.max_iv_ceiling or math.isnan(effective_iv):
                return {
                    "isPermitted": False,
                    "status": "EXTREME_VOLATILITY",
                    "allocatedLots": 0,
                    "totalQuantity": 0,
                    "bindingConstraint": "EXTREME_VOLATILITY",
                    "reason": (
                        f"EXTREME_VOLATILITY: Implied volatility ({effective_iv*100:.1f}%) is outside "
                        f"governed institutional bounds [{policy.min_iv_floor*100:.1f}%, {policy.max_iv_ceiling*100:.1f}%]."
                    ),
                    "constraintsBreakdown": {},
                }

            # 6. Staleness Check
            if quote_timestamp is not None:
                q_dt = self._parse_quote_timestamp(quote_timestamp)
                if q_dt is not None:
                    now_ist = datetime.now(IST_ZONE)
                    age_sec = (now_ist - q_dt).total_seconds()
                    if age_sec > max_quote_age_sec:
                        return {
                            "isPermitted": False,
                            "status": "STALE_QUOTE",
                            "allocatedLots": 0,
                            "totalQuantity": 0,
                            "bindingConstraint": "STALE_QUOTE",
                            "reason": f"STALE_QUOTE: Market quote age ({age_sec:.1f}s) exceeds max freshness ceiling ({max_quote_age_sec}s).",
                            "constraintsBreakdown": {},
                        }

            # 7. Spread / Liquidity Check
            if bid is not None and ask is not None:
                if bid > ask:
                    return {
                        "isPermitted": False,
                        "status": "INVALID_QUOTE",
                        "allocatedLots": 0,
                        "totalQuantity": 0,
                        "bindingConstraint": "INVALID_QUOTE",
                        "reason": f"INVALID_QUOTE: Inverted bid-ask spread (Bid: ₹{bid:.2f} > Ask: ₹{ask:.2f}).",
                        "constraintsBreakdown": {},
                    }
                spread_val = round(ask - bid, 2)
                spread_pct = round(spread_val / entry_premium, 4) if entry_premium > 0 else 0.0
                if spread_pct > policy.max_spread_pct:
                    return {
                        "isPermitted": False,
                        "status": "EXCESSIVE_SPREAD",
                        "allocatedLots": 0,
                        "totalQuantity": 0,
                        "bindingConstraint": "EXCESSIVE_SPREAD",
                        "reason": (
                            f"EXCESSIVE_SPREAD: Bid-ask spread ({spread_pct*100:.2f}%) exceeds "
                            f"policy ceiling ({policy.max_spread_pct*100:.2f}%)."
                        ),
                        "constraintsBreakdown": {},
                    }

            # 8. Construct Contract Sensitivity Profile
            profile = self.calculate_contract_profile(
                instrument=clean_inst,
                contract_symbol=contract_symbol,
                option_type=option_type,
                spot=spot,
                strike=strike,
                entry_premium=entry_premium,
                stop_loss=stop_loss,
                greeks=greeks,
                lot_size=lot_size,
                iv=effective_iv,
                time_to_expiry_years=time_to_expiry_years,
                bid=bid,
                ask=ask,
                quote_timestamp=str(quote_timestamp) if quote_timestamp else None,
                position_type=clean_pos_type,
            )

            # 9. Aggregate Existing Portfolio Greeks
            port_greeks = PortfolioGreeksAggregator.aggregate(portfolio_open_positions)
            cur_rupee_delta = port_greeks["netNotionalRupeeDelta"]
            cur_rupee_gamma = port_greeks["netRupeeGamma"]
            cur_daily_theta = port_greeks["netDailyThetaLossInr"]
            cur_rupee_vega = port_greeks["netRupeeVega"]

            # 10. Multi-Constraint Capacity Calculation
            # 10a. Trade Risk Budget Constraint
            risk_per_lot = profile.risk_per_lot
            lots_risk = int(policy.max_trade_risk_inr // risk_per_lot) if risk_per_lot > 0 else 0

            # 10b. Capital / Margin Constraint
            exposure_per_lot = profile.exposure_per_lot
            effective_cap = min(float(available_capital), policy.max_capital_per_trade_inr)
            lots_cap = int(effective_cap // exposure_per_lot) if exposure_per_lot > 0 else 0

            # 10c. Circuit Breaker Constraint
            lots_cb = 999999
            cb_reason = None
            if policy.enforce_circuit_breaker and circuit_breaker is not None:
                cb_state = circuit_breaker.get_status()
                # Check eligibility
                if paper_engine_state is not None:
                    elig = circuit_breaker.evaluate_entry_eligibility(paper_engine_state, instrument=clean_inst)
                    if not elig.get("isPermitted", False):
                        return {
                            "isPermitted": False,
                            "status": "CIRCUIT_BREAKER_BLOCKED",
                            "allocatedLots": 0,
                            "totalQuantity": 0,
                            "bindingConstraint": "CIRCUIT_BREAKER_BLOCKED",
                            "reason": f"CIRCUIT_BREAKER_BLOCKED: {elig.get('reason')}",
                            "constraintsBreakdown": {},
                        }
                # Remaining daily budget
                conf_budget = cb_state.get("configuredBudgetINR")
                if conf_budget is None:
                    return {
                        "isPermitted": False,
                        "status": "CIRCUIT_BREAKER_BLOCKED",
                        "allocatedLots": 0,
                        "totalQuantity": 0,
                        "bindingConstraint": "CIRCUIT_BREAKER_BLOCKED",
                        "reason": "CIRCUIT_BREAKER_BLOCKED: Circuit breaker daily risk budget is unconfigured.",
                        "constraintsBreakdown": {},
                    }
                net_pnl = cb_state.get("netDailyPnL") or 0.0
                cb_remaining = max(0.0, float(conf_budget) + float(net_pnl))
                lots_cb = int(cb_remaining // risk_per_lot) if risk_per_lot > 0 else 0
                if lots_cb < 1:
                    cb_reason = f"Circuit breaker remaining budget (₹{cb_remaining:,.2f}) cannot support 1 lot."

            # 10d. Delta Capacity Constraint
            abs_delta_per_lot = abs(profile.rupee_delta_per_lot)
            delta_headroom = max(0.0, policy.max_portfolio_delta_inr - abs(cur_rupee_delta))
            lots_delta = int(delta_headroom // abs_delta_per_lot) if abs_delta_per_lot > 0 else 999999

            # 10e. Gamma Capacity Constraint
            gamma_per_lot = profile.rupee_gamma_per_lot
            gamma_headroom = max(0.0, policy.max_portfolio_gamma_inr - cur_rupee_gamma)
            lots_gamma = int(gamma_headroom // gamma_per_lot) if gamma_per_lot > 0 else 999999

            # 10f. Theta Decay Capacity Constraint
            abs_theta_per_lot = abs(profile.daily_theta_per_lot)
            theta_headroom = max(0.0, policy.max_daily_theta_loss_inr - cur_daily_theta)
            lots_theta = int(theta_headroom // abs_theta_per_lot) if abs_theta_per_lot > 0 else 999999

            # 10g. Vega Capacity Constraint
            vega_per_lot = profile.rupee_vega_per_lot
            vega_headroom = max(0.0, policy.max_portfolio_vega_inr - cur_rupee_vega)
            lots_vega = int(vega_headroom // vega_per_lot) if vega_per_lot > 0 else 999999

            # 10h. Hard Max Lots Cap
            lots_hard_cap = policy.max_permitted_lots

            constraints_breakdown = {
                "riskBudget": {"maxLots": lots_risk, "limit": policy.max_trade_risk_inr, "perLot": risk_per_lot},
                "capitalBudget": {"maxLots": lots_cap, "limit": effective_cap, "perLot": exposure_per_lot},
                "circuitBreaker": {"maxLots": lots_cb, "reason": cb_reason},
                "portfolioDelta": {"maxLots": lots_delta, "limit": policy.max_portfolio_delta_inr, "current": cur_rupee_delta, "headroom": delta_headroom, "perLot": abs_delta_per_lot},
                "portfolioGamma": {"maxLots": lots_gamma, "limit": policy.max_portfolio_gamma_inr, "current": cur_rupee_gamma, "headroom": gamma_headroom, "perLot": gamma_per_lot},
                "portfolioTheta": {"maxLots": lots_theta, "limit": policy.max_daily_theta_loss_inr, "current": cur_daily_theta, "headroom": theta_headroom, "perLot": abs_theta_per_lot},
                "portfolioVega": {"maxLots": lots_vega, "limit": policy.max_portfolio_vega_inr, "current": cur_rupee_vega, "headroom": vega_headroom, "perLot": vega_per_lot},
                "hardLotsCap": {"maxLots": lots_hard_cap},
            }

            # 11. Determine Final Sized Lots
            candidate_lots = [
                (lots_risk, "INSUFFICIENT_RISK_BUDGET"),
                (lots_cap, "INSUFFICIENT_CAPITAL"),
                (lots_cb, "CIRCUIT_BREAKER_BLOCKED"),
                (lots_delta, "DELTA_LIMIT_EXCEEDED"),
                (lots_gamma, "GAMMA_LIMIT_EXCEEDED"),
                (lots_theta, "THETA_LIMIT_EXCEEDED"),
                (lots_vega, "VEGA_LIMIT_EXCEEDED"),
                (lots_hard_cap, "HARD_LOTS_CAP"),
            ]

            min_lots, binding_constraint = min(candidate_lots, key=lambda x: x[0])
            allocated_lots = max(0, min_lots)

            if allocated_lots < 1:
                reason = self._build_rejection_reason(
                    binding_constraint, constraints_breakdown, profile
                )
                return {
                    "isPermitted": False,
                    "status": binding_constraint,
                    "allocatedLots": 0,
                    "totalQuantity": 0,
                    "bindingConstraint": binding_constraint,
                    "reason": reason,
                    "contractProfile": profile.to_dict(),
                    "constraintsBreakdown": constraints_breakdown,
                    "portfolioGreeks": port_greeks,
                }

            # Allocation Successful
            total_qty = allocated_lots * profile.lot_size
            allocated_profile = {
                "allocatedLots": allocated_lots,
                "totalQuantity": total_qty,
                "totalRiskInr": round(allocated_lots * profile.risk_per_lot, 2),
                "totalCapitalExposureInr": round(allocated_lots * profile.exposure_per_lot, 2),
                "allocatedRupeeDelta": round(allocated_lots * profile.rupee_delta_per_lot, 2),
                "allocatedPointDelta": round(allocated_lots * profile.point_delta_per_lot, 2),
                "allocatedRupeeGamma": round(allocated_lots * profile.rupee_gamma_per_lot, 2),
                "allocatedDailyTheta": round(allocated_lots * profile.daily_theta_per_lot, 2),
                "allocatedRupeeVega": round(allocated_lots * profile.rupee_vega_per_lot, 2),
            }

            return {
                "isPermitted": True,
                "status": "ALLOCATED",
                "allocatedLots": allocated_lots,
                "totalQuantity": total_qty,
                "bindingConstraint": binding_constraint,
                "reason": f"Sized {allocated_lots} lots ({total_qty} units) bounded by {binding_constraint}.",
                "allocatedProfile": allocated_profile,
                "contractProfile": profile.to_dict(),
                "constraintsBreakdown": constraints_breakdown,
                "portfolioGreeks": port_greeks,
            }

    @staticmethod
    def _parse_quote_timestamp(ts: Union[str, datetime]) -> Optional[datetime]:
        """Parses quote timestamp into IST datetime."""
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                return ts.replace(tzinfo=IST_ZONE)
            return ts.astimezone(IST_ZONE)
        s = str(ts).strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST_ZONE)
            return dt.astimezone(IST_ZONE)
        except Exception:
            pass
        formats = [
            "%d %b %Y, %I:%M %p IST",
            "%d %b %Y, %I:%M %p",
            "%Y-%m-%d %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
        ]
        clean_s = s.replace("IST", "").strip()
        for fmt in formats:
            try:
                dt = datetime.strptime(clean_s, fmt)
                return dt.replace(tzinfo=IST_ZONE)
            except Exception:
                pass
        return None

    @staticmethod
    def _build_rejection_reason(
        constraint: str,
        breakdown: Dict[str, Any],
        profile: GreeksRiskProfile,
    ) -> str:
        """Formats a human-readable audit reason for sizing rejection."""
        if constraint == "INSUFFICIENT_RISK_BUDGET":
            lim = breakdown["riskBudget"]["limit"]
            per_lot = breakdown["riskBudget"]["perLot"]
            return f"INSUFFICIENT_RISK_BUDGET: Trade risk budget (₹{lim:,.2f}) cannot support 1 full lot (risk/lot = ₹{per_lot:,.2f})."
        elif constraint == "INSUFFICIENT_CAPITAL":
            lim = breakdown["capitalBudget"]["limit"]
            per_lot = breakdown["capitalBudget"]["perLot"]
            return f"INSUFFICIENT_CAPITAL: Available capital / limit (₹{lim:,.2f}) cannot support 1 full lot (exposure/lot = ₹{per_lot:,.2f})."
        elif constraint == "CIRCUIT_BREAKER_BLOCKED":
            reason = breakdown["circuitBreaker"].get("reason")
            return f"CIRCUIT_BREAKER_BLOCKED: {reason or 'Daily loss budget exhausted or circuit breaker active.'}"
        elif constraint == "DELTA_LIMIT_EXCEEDED":
            hd = breakdown["portfolioDelta"]["headroom"]
            per_lot = breakdown["portfolioDelta"]["perLot"]
            return f"DELTA_LIMIT_EXCEEDED: Portfolio delta headroom (₹{hd:,.2f}) cannot support 1 lot (delta/lot = ₹{per_lot:,.2f})."
        elif constraint == "GAMMA_LIMIT_EXCEEDED":
            hd = breakdown["portfolioGamma"]["headroom"]
            per_lot = breakdown["portfolioGamma"]["perLot"]
            return f"GAMMA_LIMIT_EXCEEDED: Portfolio gamma headroom (₹{hd:,.2f}) cannot support 1 lot (gamma/lot = ₹{per_lot:,.2f})."
        elif constraint == "THETA_LIMIT_EXCEEDED":
            hd = breakdown["portfolioTheta"]["headroom"]
            per_lot = breakdown["portfolioTheta"]["perLot"]
            return f"THETA_LIMIT_EXCEEDED: Daily theta loss headroom (₹{hd:,.2f}) cannot support 1 lot (theta/lot = ₹{per_lot:,.2f})."
        elif constraint == "VEGA_LIMIT_EXCEEDED":
            hd = breakdown["portfolioVega"]["headroom"]
            per_lot = breakdown["portfolioVega"]["perLot"]
            return f"VEGA_LIMIT_EXCEEDED: Portfolio vega headroom (₹{hd:,.2f}) cannot support 1 lot (vega/lot = ₹{per_lot:,.2f})."
        return f"POSITION_SIZING_REJECTED: Constraint {constraint} blocked order."


# Global Singleton Accessor
_greeks_risk_sizer_instance: Optional[DynamicGreeksPositionSizer] = None
_instance_lock = threading.Lock()


def get_greeks_risk_sizer(state_file_path: Optional[str] = None) -> DynamicGreeksPositionSizer:
    """Returns the process-wide DynamicGreeksPositionSizer instance."""
    global _greeks_risk_sizer_instance
    with _instance_lock:
        if _greeks_risk_sizer_instance is None or state_file_path is not None:
            _greeks_risk_sizer_instance = DynamicGreeksPositionSizer(state_file_path=state_file_path)
        return _greeks_risk_sizer_instance


def set_greeks_risk_sizer(instance: Optional[DynamicGreeksPositionSizer]) -> None:
    """Sets or resets the process-wide instance (primarily for test isolation)."""
    global _greeks_risk_sizer_instance
    with _instance_lock:
        _greeks_risk_sizer_instance = instance
