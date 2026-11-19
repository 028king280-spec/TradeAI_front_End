"""
Intelligent Paper Trading Lifecycle Engine.
Manages full simulated trade lifecycle from creation to closure:
1. Statuses: Pending, Open, Target 1 Hit, Target 2 Hit, Stop Loss Hit, Manually Closed, Expired
2. P&L: Exact gross and net P&L via IndianDerivativesCostCalculator
3. Exits: Full exits, 50% partial exits at T1 with remaining runner at T2/SL
4. Live Monitoring: MFE (Max Favourable Excursion) and MAE (Max Adverse Excursion)
5. Analytics: Win Rate, Profit Factor, Expectancy, Max Drawdown, Daily/Weekly/Monthly reports
"""

from typing import Dict, Any, List, Optional, Union
import os
import json
import uuid
import math
import threading
import copy
from datetime import datetime, timezone

from app.data.market_calendar import MarketCalendar
from app.options.paper_trading.cost_calculator import IndianDerivativesCostCalculator
from app.core.logging import logger

STORAGE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "paper_trading_records.json")
DEFAULT_CAPITAL = 100000.0


def _sync_dir(dir_path: str):
    """
    Sync parent directory metadata to physical disk on POSIX filesystems.
    Safely ignored on Windows or platforms where directory fsync is unsupported.
    """
    try:
        if hasattr(os, "O_DIRECTORY"):
            flags = os.O_RDONLY | os.O_DIRECTORY
        else:
            flags = os.O_RDONLY
        fd = os.open(dir_path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        pass


class PaperTradingEngine:
    """
    Server-side Paper Trading Lifecycle & Portfolio Engine.
    
    Features crash-safe atomic persistence:
    - Writes complete state to a temporary file in the same directory.
    - Flushes file buffer and invokes os.fsync() on the file descriptor.
    - Atomically replaces target file using os.replace() (safe against power loss/crashes).
    - Monotonic state sequencing and thread-safe locking to prevent concurrent overwrite.
    - Guaranteed preservation of existing records if write or serialization fails.
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        ml_dataset_path: Optional[str] = None,
        ml_knowledge_path: Optional[str] = None,
        circuit_breaker: Optional[Any] = None,
        greeks_risk_sizer: Optional[Any] = None,
    ):
        from app.options.paper_trading import ml_feedback_engine

        resolved_storage = os.fspath(storage_path) if storage_path is not None else STORAGE_PATH
        self.storage_path = resolved_storage

        prod_storage_norm = os.path.normcase(os.path.abspath(STORAGE_PATH))
        prod_ds_norm = os.path.normcase(os.path.abspath(ml_feedback_engine.DATASET_PATH))
        prod_kb_norm = os.path.normcase(os.path.abspath(ml_feedback_engine.KNOWLEDGE_PATH))

        inst_storage_norm = os.path.normcase(os.path.abspath(resolved_storage))
        is_isolated_storage = storage_path is not None and inst_storage_norm != prod_storage_norm
        is_isolated_ds = ml_dataset_path is not None and os.path.normcase(os.path.abspath(os.fspath(ml_dataset_path))) != prod_ds_norm
        is_isolated_kb = ml_knowledge_path is not None and os.path.normcase(os.path.abspath(os.fspath(ml_knowledge_path))) != prod_kb_norm

        storage_dir = os.path.dirname(os.path.abspath(resolved_storage))
        storage_stem = os.path.splitext(os.path.basename(resolved_storage))[0] or "paper"

        if ml_dataset_path is not None:
            self.ml_dataset_path = os.fspath(ml_dataset_path)
        elif is_isolated_storage:
            self.ml_dataset_path = os.path.join(storage_dir, f"{storage_stem}.ml_trade_dataset.json")
        elif is_isolated_kb:
            kb_abs = os.path.abspath(os.fspath(ml_knowledge_path))
            kb_stem = os.path.splitext(os.path.basename(kb_abs))[0] or "ml"
            self.ml_dataset_path = os.path.join(os.path.dirname(kb_abs), f"{kb_stem}.ml_trade_dataset.json")
        else:
            self.ml_dataset_path = os.path.normpath(ml_feedback_engine.DATASET_PATH)

        if ml_knowledge_path is not None:
            self.ml_knowledge_path = os.fspath(ml_knowledge_path)
        elif is_isolated_storage:
            self.ml_knowledge_path = os.path.join(storage_dir, f"{storage_stem}.what_ai_learned.json")
        elif is_isolated_ds:
            ds_abs = os.path.abspath(os.fspath(ml_dataset_path))
            ds_stem = os.path.splitext(os.path.basename(ds_abs))[0] or "ml"
            self.ml_knowledge_path = os.path.join(os.path.dirname(ds_abs), f"{ds_stem}.what_ai_learned.json")
        else:
            self.ml_knowledge_path = os.path.normpath(ml_feedback_engine.KNOWLEDGE_PATH)

        if circuit_breaker is not None:
            self.circuit_breaker = circuit_breaker
        elif not is_isolated_storage:
            try:
                from app.options.drawdown_circuit_breaker import get_circuit_breaker
                self.circuit_breaker = get_circuit_breaker()
            except Exception as e:
                logger.warning(f"[PaperTradingEngine] Circuit breaker initialization warning: {e}")
                self.circuit_breaker = None
        else:
            self.circuit_breaker = None

        if greeks_risk_sizer is not None:
            self.greeks_risk_sizer = greeks_risk_sizer
        elif not is_isolated_storage:
            try:
                from app.options.greeks_risk_engine import get_greeks_risk_sizer
                self.greeks_risk_sizer = get_greeks_risk_sizer()
            except Exception as e:
                logger.warning(f"[PaperTradingEngine] Greeks risk sizer initialization warning: {e}")
                self.greeks_risk_sizer = None
        else:
            self.greeks_risk_sizer = None

        self._save_lock = threading.RLock()
        self.state = self._load_state()
        self._state_version = int(self.state.get("stateVersion", 0))
        self._persisted_state = copy.deepcopy(self.state)
        self._cleanup_stale_temp_files()

    def _cleanup_stale_temp_files(self):
        """Safely cleans up any orphaned .tmp files left over from prior abrupt system crashes."""
        try:
            directory = os.path.dirname(os.path.abspath(self.storage_path))
            if os.path.exists(directory):
                for fname in os.listdir(directory):
                    if fname.startswith(".paper_state_") and fname.endswith(".tmp"):
                        tmp_full = os.path.join(directory, fname)
                        try:
                            os.remove(tmp_full)
                        except OSError:
                            pass
        except Exception as e:
            logger.debug(f"[PaperTradingEngine] Cleanup temp files: {e}")

    def _load_state(self) -> Dict[str, Any]:
        with self._save_lock:
            try:
                if os.path.exists(self.storage_path):
                    with open(self.storage_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict) and "balance" in data:
                            # Quarantine any legacy or unsupported non-BUY positions in memory
                            raw_positions = data.get("openPositions", [])
                            safe_positions = []
                            quarantined = data.get("quarantinedPositions", [])
                            quarantine_found = False
                            for p in raw_positions:
                                if str(p.get("positionType", "BUY")).strip().upper() != "BUY":
                                    p_copy = dict(p)
                                    p_copy["status"] = "QUARANTINED_UNSAFE_SHORT"
                                    quarantined.append(p_copy)
                                    quarantine_found = True
                                    logger.warning(
                                        f"[PaperTradingEngine] Quarantining legacy non-BUY position {p.get('id')} ({p.get('positionType')})."
                                    )
                                else:
                                    safe_positions.append(p)
                            if quarantine_found:
                                data["openPositions"] = safe_positions
                                data["quarantinedPositions"] = quarantined
                            return data
                        logger.warning(
                            f"[PaperTradingEngine] Invalid state schema in {self.storage_path}; preserving file and initializing default."
                        )
            except Exception as e:
                logger.error(f"[PaperTradingEngine] Error loading state: {e}")

            return {
                "balance": DEFAULT_CAPITAL,
                "startingBalance": DEFAULT_CAPITAL,
                "openPositions": [],
                "pendingOrders": [],
                "closedTrades": [],
                "totalRealizedGrossPnl": 0.0,
                "totalRealizedNetPnl": 0.0,
                "totalTradingCosts": 0.0,
                "winCount": 0,
                "lossCount": 0,
                "stateVersion": 0,
                "lastUpdated": MarketCalendar.format_ist_timestamp(),
            }

    def _save_state(self, expected_version: Optional[int] = None):
        """
        Crash-safe atomic persistence for paper trading state.
        
        1. Thread-safe lock acquisition prevents race conditions.
        2. Validates expected_version if supplied to prevent stale overwrites.
        3. Increments stateVersion monotonically.
        4. Pre-serializes to string to trap serialization errors before touching disk.
        5. Writes to a temporary file in the same directory (same filesystem).
        6. Buffer flush + os.fsync() forces hardware-level non-volatile persistence.
        7. Windows transient lock retry backoff (PermissionError) on os.replace.
        8. Directory metadata sync (_sync_dir).
        9. Guarantees zero-byte truncation is impossible and cleans up temporary files.
        """
        with self._save_lock:
            if expected_version is not None and self._state_version != expected_version:
                raise ValueError(
                    f"[PaperTradingEngine] State version conflict: expected {expected_version}, "
                    f"current {self._state_version}. Aborting stale overwrite."
                )

            tmp_path = None
            try:
                storage_dir = os.path.dirname(os.path.abspath(self.storage_path))
                os.makedirs(storage_dir, exist_ok=True)

                self._state_version += 1
                self.state["stateVersion"] = self._state_version
                self.state["lastUpdated"] = MarketCalendar.format_ist_timestamp()

                # Step 1: Pre-serialize to detect errors BEFORE touching disk
                serialized_state = json.dumps(self.state, indent=2, ensure_ascii=False)
                committed_snapshot = copy.deepcopy(self.state)

                # Step 2: Write to unique temp file in same directory
                tmp_filename = f".paper_state_{uuid.uuid4().hex}.tmp"
                tmp_path = os.path.join(storage_dir, tmp_filename)

                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(serialized_state)
                    f.flush()
                    # Step 3: Force physical disk platter/SSD controller flush
                    os.fsync(f.fileno())

                # Step 4: Atomic rename/replace with retry backoff for Windows transient locks
                max_retries = 5
                for attempt in range(max_retries):
                    try:
                        os.replace(tmp_path, self.storage_path)
                        break
                    except PermissionError:
                        if attempt == max_retries - 1:
                            raise
                        import time
                        time.sleep(0.01 * (attempt + 1))

                # Step 5: Directory metadata sync
                _sync_dir(storage_dir)
                self._persisted_state = committed_snapshot

            except Exception as e:
                self.state = copy.deepcopy(self._persisted_state)
                self._state_version = int(self.state.get("stateVersion", 0))
                logger.error(f"[PaperTradingEngine] Atomic save failed: {e}. Existing state preserved.")
                raise
            finally:
                # Step 6: Safe cleanup if tmp_path still exists
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

    # -----------------------------------------------------------------
    # Order Lifecycle Management
    # -----------------------------------------------------------------
    def create_pending_order(
        self,
        instrument: str,
        contract_symbol: str,
        bias: str,  # CE or PE
        strike: float,
        expiry: str,
        order_type: str = "BUY",  # BUY or SELL
        lots: int = 1,
        lot_size: int = 65,
        target_entry_min: float = 0.0,
        target_entry_max: float = 0.0,
        stop_loss: float = 0.0,
        target_1: float = 0.0,
        target_2: float = 0.0,
        target_3: float = 0.0,
        strategy: str = "Model A (Liquidity Sweep & Retest)",
        ict_setup: str = "Bullish SSL Sweep + FVG 50% CE",
        allow_after_hours: bool = False,
    ) -> Dict[str, Any]:
        """Creates a pending simulated limit/trigger order."""
        with self._save_lock:
            # Naked Options Ban (Fail-closed: Only LONG option BUY orders permitted)
            clean_order_type = str(order_type or "").strip().upper()
            if clean_order_type != "BUY":
                return {
                    "success": False,
                    "status": "NAKED_OPTIONS_WRITING_PROHIBITED",
                    "message": (
                        f"Pending order rejected: NAKED_OPTIONS_WRITING_PROHIBITED: Order type '{order_type}' is prohibited. "
                        "AIVOLVE institutional risk policy permits LONG (BUY) options only. "
                        "Naked option writing/shorting is strictly barred."
                    ),
                }

            if not allow_after_hours and not MarketCalendar.is_market_open():
                return {
                    "success": False,
                    "message": "Pending orders rejected: NSE/BSE exchange is closed (Trading hours: 09:15 - 15:30 IST).",
                    "marketStatus": "CLOSED",
                }

            total_qty = lots * lot_size
            order_id = f"PO-{uuid.uuid4().hex[:8].upper()}"
            now_ist = MarketCalendar.format_ist_timestamp()

            order = {
                "id": order_id,
                "instrument": instrument,
                "contractSymbol": contract_symbol,
                "bias": bias.upper(),
                "positionType": order_type.upper(),
                "strike": strike,
                "expiry": expiry,
                "lots": lots,
                "lotSize": lot_size,
                "quantity": total_qty,
                "targetEntryMin": target_entry_min,
                "targetEntryMax": target_entry_max,
                "stopLoss": stop_loss,
                "target1": target_1,
                "target2": target_2,
                "target3": target_3,
                "strategy": strategy,
                "ictSetup": ict_setup,
                "status": "PENDING",
                "createdAt": now_ist,
            }

            self.state.setdefault("pendingOrders", []).append(order)
            self._save_state()
            return order

    def open_position(
        self,
        instrument: str,
        contract_symbol: str,
        bias: str,
        strike: float,
        expiry: str,
        entry_premium: float,
        position_type: str = "BUY",
        lots: int = 1,
        lot_size: int = 65,
        stop_loss: float = 0.0,
        target_1: float = 0.0,
        target_2: float = 0.0,
        target_3: float = 0.0,
        strategy: str = "Model A (Liquidity Sweep & Retest)",
        ict_setup: str = "Bullish SSL Sweep + FVG 50% CE",
        market_features: Optional[Dict[str, Any]] = None,
        contract_greeks: Optional[Dict[str, float]] = None,
        underlying_spot: Optional[float] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        quote_timestamp: Optional[Union[str, datetime]] = None,
        greeks_risk_sizer: Optional[Any] = None,
        enforce_greeks_sizing: bool = False,
    ) -> Dict[str, Any]:
        """Fills and opens an active simulated paper position."""
        with self._save_lock:
            # Naked Options Ban (Fail-closed: Only LONG option BUY orders permitted)
            clean_pos_type = str(position_type or "").strip().upper()
            if clean_pos_type != "BUY":
                return {
                    "success": False,
                    "status": "NAKED_OPTIONS_WRITING_PROHIBITED",
                    "message": (
                        f"Paper trade rejected: NAKED_OPTIONS_WRITING_PROHIBITED: Position type '{position_type}' is prohibited. "
                        "AIVOLVE institutional risk policy permits LONG (BUY) options only. "
                        "Naked option writing/shorting is strictly barred."
                    ),
                }

            # Domain invariants apply to every entry path, including isolated replay.
            if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (lots, lot_size)):
                return {"success": False, "status": "INVALID_QUANTITY", "message": "Lots and lot size must be positive integers."}
            for name, value in (("entry premium", entry_premium), ("strike", strike)):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    return {"success": False, "status": "INVALID_PRICE", "message": f"Invalid {name}: expected a positive finite number."}

            # SENSEX Governance Lock Invariant
            clean_inst = str(instrument or "").strip().upper()
            if "SENSEX" in clean_inst or "BSE" in clean_inst:
                return {
                    "success": False,
                    "circuitBreakerState": "GOVERNANCE_LOCKED",
                    "message": "SENSEX trading rejected: Under strict GOVERNANCE_LOCK. Unconfigured institutional parameters. Only NIFTY, BANKNIFTY, and FINNIFTY permitted.",
                }

            # Safety Requirement 1 & 2: Market Closed & Disqualified Feed Enforcement
            is_replay = bool(market_features and (market_features.get("allowAfterHoursSimulation") or market_features.get("isReplay")))
            if not is_replay and not MarketCalendar.is_market_open():
                return {
                    "success": False,
                    "message": "Paper trade rejected: NSE/BSE exchange is closed (Trading hours: 09:15 - 15:30 IST). EOD snapshots cannot be used to open live positions.",
                    "marketStatus": "CLOSED",
                }

            if market_features:
                data_status = str(market_features.get("dataStatus", "")).upper()
                feed_status = str(market_features.get("feedStatus", "")).upper()
                is_qualified = market_features.get("isTradeQualified", True)
                disqualified_statuses = {
                    "DATA_OFFLINE",
                    "DATA_UNAVAILABLE",
                    "STALE_TICK",
                    "ANOMALOUS",
                    "MARKET_CLOSED",
                    "VERIFIED_EOD",
                    "MOCK",
                    "SYNTHETIC",
                }
                if (not is_qualified and not is_replay) or data_status in disqualified_statuses or feed_status in disqualified_statuses:
                    return {
                        "success": False,
                        "message": (
                            f"Paper trade rejected by DataQualityEngine: dataStatus='{data_status}', "
                            f"feedStatus='{feed_status}'. Simulated execution strictly blocked on EOD snapshots, mock feeds, or offline market data."
                        ),
                    }

            # Phase 7 / Step 7.5: Intraday Drawdown Circuit Breaker Gate (REQ-7.5)
            if self.circuit_breaker is not None:
                eligibility = self.circuit_breaker.evaluate_entry_eligibility(self.state, instrument=clean_inst)
                if not eligibility.get("isPermitted", False):
                    return {
                        "success": False,
                        "circuitBreakerState": eligibility.get("state"),
                        "message": f"Paper trade rejected by Intraday Drawdown Circuit Breaker: {eligibility.get('reason')}",
                        "circuitBreaker": eligibility,
                    }

            # Phase 7 / Step 7.6: Dynamic Greeks-Based Position Sizing Gate (REQ-7.6)
            active_sizer = greeks_risk_sizer or self.greeks_risk_sizer
            sizing_result: Optional[Dict[str, Any]] = None

            if enforce_greeks_sizing or (active_sizer is not None and getattr(active_sizer, "is_configured", False)) or contract_greeks is not None:
                if active_sizer is None or not getattr(active_sizer, "is_configured", False):
                    return {
                        "success": False,
                        "status": "RISK_POLICY_UNCONFIGURED",
                        "message": "Paper trade rejected by Dynamic Greeks Position Sizer: RISK_POLICY_UNCONFIGURED (Institutional Greeks risk policy is unconfigured).",
                    }

                opt_type = "CE" if str(bias).upper() in ("CE", "CALL", "BULLISH") else "PE"
                sizing_result = active_sizer.calculate_position_size(
                    instrument=clean_inst,
                    contract_symbol=contract_symbol,
                    option_type=opt_type,
                    spot=underlying_spot if underlying_spot is not None else strike,
                    strike=strike,
                    entry_premium=entry_premium,
                    stop_loss=stop_loss,
                    greeks=contract_greeks,
                    available_capital=float(self.state.get("balance", 0.0)),
                    portfolio_open_positions=self.state.get("openPositions", []),
                    circuit_breaker=self.circuit_breaker,
                    paper_engine_state=self.state,
                    lot_size=lot_size,
                    bid=bid,
                    ask=ask,
                    quote_timestamp=quote_timestamp,
                    position_type=clean_pos_type,
                )

                if not sizing_result.get("isPermitted", False):
                    return {
                        "success": False,
                        "status": sizing_result.get("status"),
                        "bindingConstraint": sizing_result.get("bindingConstraint"),
                        "message": f"Paper trade rejected by Dynamic Greeks Position Sizer: {sizing_result.get('reason')}",
                        "greeksSizing": sizing_result,
                    }

                permitted_lots = int(sizing_result.get("allocatedLots", 0))
                if permitted_lots < 1:
                    return {
                        "success": False,
                        "status": sizing_result.get("status"),
                        "message": f"Paper trade rejected: Permitted lots ({permitted_lots}) < 1.",
                        "greeksSizing": sizing_result,
                    }

                lots = min(lots, permitted_lots) if (lots is not None and lots > 0) else permitted_lots

            total_qty = lots * lot_size
            margin_required = round(entry_premium * total_qty, 2)

            if margin_required > self.state["balance"]:
                return {
                    "success": False,
                    "message": f"Insufficient virtual balance. Required: ₹{margin_required}, Available: ₹{self.state['balance']}",
                }

            pos_id = f"PT-{uuid.uuid4().hex[:8].upper()}"
            now_ist = MarketCalendar.format_ist_timestamp()

            position = {
                "id": pos_id,
                "instrument": instrument,
                "contractSymbol": contract_symbol,
                "bias": bias.upper(),
                "positionType": position_type.upper(),
                "strike": strike,
                "expiry": expiry,
                "lots": lots,
                "initialLots": lots,
                "lotSize": lot_size,
                "quantity": total_qty,
                "remainingQuantity": total_qty,
                "entryPremium": entry_premium,
                "currentPremium": entry_premium,
                "lastQuoteTimestamp": now_ist,
                "lastDataStatus": "VERIFIED_LIVE",
                "stopLoss": stop_loss,
                "initialStopLoss": stop_loss,
                "target1": target_1,
                "target2": target_2,
                "target3": target_3,
                "strategy": strategy,
                "ictSetup": ict_setup,
                "marginUsed": margin_required,
                "status": "OPEN",
                "entryTimestamp": now_ist,
                # MFE & MAE Tracking
                "mfePts": 0.0,
                "mfeRupees": 0.0,
                "maePts": 0.0,
                "maeRupees": 0.0,
                "highestObservedPremium": entry_premium,
                "lowestObservedPremium": entry_premium,
                "partialExits": [],
                "marketFeaturesAtEntry": market_features or {},
                # Greeks Risk Sensitivities (REQ-7.6)
                "greeks": contract_greeks,
                "underlyingSpot": underlying_spot,
                "rupeeDelta": sizing_result.get("allocatedProfile", {}).get("allocatedRupeeDelta") if sizing_result else None,
                "rupeeGamma": sizing_result.get("allocatedProfile", {}).get("allocatedRupeeGamma") if sizing_result else None,
                "dailyTheta": sizing_result.get("allocatedProfile", {}).get("allocatedDailyTheta") if sizing_result else None,
                "rupeeVega": sizing_result.get("allocatedProfile", {}).get("allocatedRupeeVega") if sizing_result else None,
                "greeksSizing": sizing_result,
            }

            # Deduct margin from available balance
            self.state["balance"] = round(self.state["balance"] - margin_required, 2)
            self.state.setdefault("openPositions", []).append(position)
            self._save_state()

            return {
                "success": True,
                "message": f"Simulated order filled: {lots} Lot ({total_qty} Qty) of {contract_symbol} @ ₹{entry_premium:.2f}",
                "position": position,
                "greeksSizing": sizing_result,
            }

    # -----------------------------------------------------------------
    # Live Monitoring: Update Quotes & Check Exits
    # -----------------------------------------------------------------
    def update_live_monitoring(
        self,
        contract_symbol: Optional[str] = None,
        current_ltp: Optional[float] = None,
        bar_high: Optional[float] = None,
        bar_low: Optional[float] = None,
        quotes_payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Updates live option premium, tracks MFE/MAE, and auto-triggers Target or Stop Loss.
        Immediately recalculates portfolio drawdown circuit breaker on fresh verified ticks.
        """
        with self._save_lock:
            positions = self.state.get("openPositions", [])
            now_ist = MarketCalendar.format_ist_timestamp()
            last_matched = None

            # Handle dictionary quotes_payload
            effective_quotes: Dict[str, Any] = {}
            if quotes_payload:
                effective_quotes.update(quotes_payload)

            if contract_symbol and current_ltp is not None:
                effective_quotes[contract_symbol] = {
                    "ltp": float(current_ltp),
                    "lastPrice": float(current_ltp),
                    "bar_high": bar_high,
                    "bar_low": bar_low,
                    "timestamp": now_ist,
                    "dataStatus": "VERIFIED_LIVE",
                    "feedStatus": "VERIFIED_LIVE",
                }

            if not effective_quotes:
                return None

            for sym, q in effective_quotes.items():
                matched = next((p for p in positions if p["contractSymbol"] == sym), None)
                if not matched:
                    continue
                last_matched = matched

                val = q.get("ltp") or q.get("lastPrice") or (current_ltp if sym == contract_symbol else None)
                if val is None:
                    continue
                ltp = float(val)

                q_ts = q.get("timestamp") or now_ist
                q_status = q.get("dataStatus") or "VERIFIED_LIVE"

                matched["currentPremium"] = ltp
                matched["lastQuoteTimestamp"] = q_ts
                matched["lastDataStatus"] = q_status

                b_high = q.get("bar_high", bar_high if sym == contract_symbol else None)
                b_low = q.get("bar_low", bar_low if sym == contract_symbol else None)
                high_val = b_high if b_high is not None else ltp
                low_val = b_low if b_low is not None else ltp

                matched["highestObservedPremium"] = max(matched.get("highestObservedPremium", ltp), high_val)
                matched["lowestObservedPremium"] = min(matched.get("lowestObservedPremium", ltp), low_val)

                p_entry = matched["entryPremium"]
                pos_type = matched["positionType"]
                rem_qty = matched["remainingQuantity"]

                # Calculate floating excursion
                if pos_type == "BUY":
                    fav_pts = max(0.0, matched["highestObservedPremium"] - p_entry)
                    adv_pts = max(0.0, p_entry - matched["lowestObservedPremium"])
                    curr_pts = ltp - p_entry
                else:
                    fav_pts = max(0.0, p_entry - matched["lowestObservedPremium"])
                    adv_pts = max(0.0, matched["highestObservedPremium"] - p_entry)
                    curr_pts = p_entry - ltp

                matched["mfePts"] = round(fav_pts, 2)
                matched["mfeRupees"] = round(fav_pts * rem_qty, 2)
                matched["maePts"] = round(adv_pts, 2)
                matched["maeRupees"] = round(-adv_pts * rem_qty, 2)

                # Unrealized P&L
                matched["unrealizedGrossPnl"] = round(curr_pts * rem_qty, 2)

                # Check Target 1 Hit (Auto partial exit 50% if multi-lot, or full)
                t1 = matched.get("target1", 0.0)
                sl = matched.get("stopLoss", 0.0)

                # Auto Exit Checks
                if pos_type == "BUY":
                    if ltp <= sl and sl > 0:
                        return self.close_position(matched["id"], exit_price=sl, exit_reason="Stop Loss Hit")
                    t2 = matched.get("target2", 0.0)
                    if (ltp >= t2 or high_val >= t2) and t2 > 0:
                        return self.close_position(matched["id"], exit_price=t2, exit_reason="Target 2 Hit")
                    if (ltp >= t1 or high_val >= t1) and t1 > 0 and not matched.get("partialExits"):
                        if matched["lots"] > 1:
                            exit_lots = max(1, matched["lots"] // 2)
                            self.execute_partial_exit(matched["id"], exit_lots=exit_lots, exit_price=t1, exit_label="Target 1 Hit (50% Partial)")
                            matched["stopLoss"] = matched["entryPremium"]
                            matched["status"] = "TARGET_1_HIT"
                        else:
                            # Target 1 Hit: Auto-trail SL to entry cost for risk-free runner, keep position open for Target 2
                            matched["status"] = "TARGET_1_HIT"
                            matched["stopLoss"] = max(matched.get("stopLoss", 0.0), matched["entryPremium"])
                else:
                    if ltp >= sl and sl > 0:
                        return self.close_position(matched["id"], exit_price=sl, exit_reason="Stop Loss Hit")
                    t2 = matched.get("target2", 0.0)
                    if (ltp <= t2 or low_val <= t2) and t2 > 0:
                        return self.close_position(matched["id"], exit_price=t2, exit_reason="Target 2 Hit")
                    if (ltp <= t1 or low_val <= t1) and t1 > 0 and not matched.get("partialExits"):
                        if matched["lots"] > 1:
                            exit_lots = max(1, matched["lots"] // 2)
                            self.execute_partial_exit(matched["id"], exit_lots=exit_lots, exit_price=t1, exit_label="Target 1 Hit (50% Partial)")
                            matched["stopLoss"] = matched["entryPremium"]
                            matched["status"] = "TARGET_1_HIT"
                        else:
                            matched["status"] = "TARGET_1_HIT"
                            matched["stopLoss"] = min(matched.get("stopLoss", 999999.0), matched["entryPremium"])

            self._save_state()

            # Immediate portfolio drawdown circuit breaker recalculation on every fresh verified price update
            if self.circuit_breaker is not None:
                try:
                    self.circuit_breaker.recalculate_and_check(self.state, quotes=effective_quotes)
                except Exception as e:
                    logger.warning(f"[PaperTradingEngine] Circuit breaker recalculate on tick error: {e}")

            return last_matched

    # -----------------------------------------------------------------
    # Partial Exits & Position Closures
    # -----------------------------------------------------------------
    def execute_partial_exit(
        self,
        position_id: str,
        exit_lots: int,
        exit_price: float,
        exit_label: str = "Partial Exit",
    ) -> Dict[str, Any]:
        """Closes a subset of lots (e.g. 50% at Target 1) while keeping runner active."""
        with self._save_lock:
            positions = self.state.get("openPositions", [])
            matched = next((p for p in positions if p["id"] == position_id), None)
            if not matched:
                return {"success": False, "message": "Position not found or already closed."}

            pos_type = str(matched.get("positionType", "BUY")).strip().upper()
            if pos_type != "BUY":
                return {
                    "success": False,
                    "status": "QUARANTINED_UNSAFE_SHORT",
                    "message": f"Cannot partially exit unsafe non-BUY position ({pos_type}).",
                }

            try:
                exit_lots_int = int(exit_lots)
                if exit_lots_int <= 0:
                    return {"success": False, "message": f"Invalid exit lots: {exit_lots}. Must be positive integer."}
                exit_lots = exit_lots_int
            except (ValueError, TypeError):
                return {"success": False, "message": f"Invalid exit lots: {exit_lots}. Must be an integer."}

            try:
                f_exit = float(exit_price)
                if math.isnan(f_exit) or math.isinf(f_exit) or f_exit < 0.0:
                    return {"success": False, "message": f"Invalid exit price: {exit_price}. Exit price must be non-negative."}
                exit_price = f_exit
            except (ValueError, TypeError):
                return {"success": False, "message": f"Invalid exit price: {exit_price}. Exit price must be numeric."}

            lot_size = matched["lotSize"]
            exit_qty = exit_lots * lot_size
            if exit_qty >= matched["remainingQuantity"]:
                return self.close_position(position_id, exit_price=exit_price, exit_reason=exit_label)

            # Calculate partial costs & P&L
            costs_pnl = IndianDerivativesCostCalculator.calculate_trade_costs_and_pnl(
                entry_price=matched["entryPremium"],
                exit_price=exit_price,
                quantity=exit_qty,
                position_type=matched["positionType"],
                orders_count=1,
            )

            matched["remainingQuantity"] -= exit_qty
            matched["lots"] -= exit_lots
            now_ist = MarketCalendar.format_ist_timestamp()

            partial_record = {
                "exitLots": exit_lots,
                "exitQuantity": exit_qty,
                "exitPrice": exit_price,
                "grossPnl": costs_pnl["grossPnl"],
                "netPnl": costs_pnl["netPnl"],
                "totalCosts": costs_pnl["totalCosts"],
                "timestamp": now_ist,
                "label": exit_label,
            }
            matched.setdefault("partialExits", []).append(partial_record)

            # Return capital to balance
            returned_cash = round(exit_price * exit_qty, 2)
            self.state["balance"] = round(self.state["balance"] + returned_cash, 2)
            self.state["totalRealizedGrossPnl"] = round(self.state["totalRealizedGrossPnl"] + costs_pnl["grossPnl"], 2)
            self.state["totalRealizedNetPnl"] = round(self.state["totalRealizedNetPnl"] + costs_pnl["netPnl"], 2)
            self.state["totalTradingCosts"] = round(self.state["totalTradingCosts"] + costs_pnl["totalCosts"], 2)

            self._save_state()

            if self.circuit_breaker is not None:
                try:
                    self.circuit_breaker.recalculate_and_check(self.state)
                except Exception as e:
                    logger.warning(f"[PaperTradingEngine] Circuit breaker recalculate error on partial exit: {e}")

            return {
                "success": True,
                "message": f"Partial Exit: {exit_lots} Lots ({exit_qty} Qty) @ ₹{exit_price:.2f}. Net P&L: ₹{costs_pnl['netPnl']}",
                "partialRecord": partial_record,
            }

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str = "Manually Closed",
    ) -> Dict[str, Any]:
        """Closes a position completely, calculates final net P&L with statutory fees."""
        with self._save_lock:
            positions = self.state.get("openPositions", [])
            idx = next((i for i, p in enumerate(positions) if p["id"] == position_id), -1)
            if idx == -1:
                return {"success": False, "message": "Position not found or already closed."}

            try:
                f_exit = float(exit_price)
                if math.isnan(f_exit) or math.isinf(f_exit) or f_exit < 0.0:
                    return {"success": False, "message": f"Invalid exit price: {exit_price}. Exit price must be non-negative."}
                exit_price = f_exit
            except (ValueError, TypeError):
                return {"success": False, "message": f"Invalid exit price: {exit_price}. Exit price must be numeric."}

            pos = positions.pop(idx)
            rem_qty = pos["remainingQuantity"]
            pos_type = str(pos.get("positionType", "BUY")).strip().upper()
            now_ist = MarketCalendar.format_ist_timestamp()

            # Quarantine defense against legacy or unsupported non-BUY positions
            if pos_type != "BUY":
                logger.error(
                    f"[PaperTradingEngine] Quarantining unsafe non-BUY position {position_id} ({pos_type}). "
                    "Cash return blocked to prevent virtual balance corruption."
                )
                pos["status"] = "QUARANTINED_UNSAFE_SHORT"
                pos["exitReason"] = f"Quarantined: {exit_reason} (Unsafe non-BUY position prohibited)"
                pos["exitTimestamp"] = now_ist
                self.state.setdefault("quarantinedPositions", []).append(pos)
                self._save_state()
                return {
                    "success": False,
                    "status": "QUARANTINED_UNSAFE_SHORT",
                    "message": (
                        f"Position {position_id} is an unsafe non-BUY position ({pos_type}) and has been quarantined. "
                        "Cash return is blocked to prevent account balance corruption."
                    ),
                    "quarantinedPosition": pos,
                }

            # Compute exit costs & P&L for remaining quantity
            rem_costs = IndianDerivativesCostCalculator.calculate_trade_costs_and_pnl(
                entry_price=pos["entryPremium"],
                exit_price=exit_price,
                quantity=rem_qty,
                position_type=pos_type,
                orders_count=1 if pos.get("partialExits") else 2,
            )

            # Aggregate with prior partial exits (if any)
            all_partials = pos.get("partialExits", [])
            total_gross_pnl = rem_costs["grossPnl"] + sum(p["grossPnl"] for p in all_partials)
            total_costs = rem_costs["totalCosts"] + sum(p["totalCosts"] for p in all_partials)
            final_net_pnl = round(total_gross_pnl - total_costs, 2)

            # Weighted average exit price
            total_qty = pos["quantity"]
            weighted_exit = round(
                (rem_costs["exitPrice"] * rem_qty + sum(p["exitPrice"] * p["exitQuantity"] for p in all_partials)) / max(1, total_qty), 2
            )

            pos["exitPremium"] = exit_price
            pos["weightedExitPremium"] = weighted_exit
            pos["grossPnl"] = total_gross_pnl
            pos["netPnl"] = final_net_pnl
            pos["totalCosts"] = total_costs
            pos["exitReason"] = exit_reason
            pos["exitTimestamp"] = now_ist

            # Determine official trade status
            if "Target 2" in exit_reason:
                status = "TARGET_2_HIT"
            elif "Target 1" in exit_reason:
                status = "TARGET_1_HIT"
            elif "Stop Loss" in exit_reason:
                status = "STOP_LOSS_HIT"
            elif "Expired" in exit_reason:
                status = "EXPIRED"
            else:
                status = "MANUALLY_CLOSED"

            pos["status"] = status
            is_win = final_net_pnl >= 0

            # Update portfolio accounting
            returned_cash = round(exit_price * rem_qty, 2)
            self.state["balance"] = round(self.state["balance"] + returned_cash, 2)
            self.state["totalRealizedGrossPnl"] = round(self.state["totalRealizedGrossPnl"] + rem_costs["grossPnl"], 2)
            self.state["totalRealizedNetPnl"] = round(self.state["totalRealizedNetPnl"] + rem_costs["netPnl"], 2)
            self.state["totalTradingCosts"] = round(self.state["totalTradingCosts"] + rem_costs["totalCosts"], 2)

            if is_win:
                self.state["winCount"] = self.state.get("winCount", 0) + 1
            else:
                self.state["lossCount"] = self.state.get("lossCount", 0) + 1

            self.state.setdefault("closedTrades", []).insert(0, pos)
            self._save_state()

            if self.circuit_breaker is not None:
                try:
                    self.circuit_breaker.recalculate_and_check(self.state)
                except Exception as e:
                    logger.warning(f"[PaperTradingEngine] Circuit breaker recalculate error on close: {e}")

            # Trigger AI Trade Evaluation & ML Feedback automatically!
            trade_evaluation = None
            try:
                from app.options.paper_trading.trade_evaluator import AITradeEvaluator
                trade_evaluation = AITradeEvaluator.evaluate_completed_trade(pos)
                pos["aiEvaluation"] = trade_evaluation

                from app.options.paper_trading.ml_feedback_engine import MLFeedbackEngine
                MLFeedbackEngine.record_training_sample(
                    pos,
                    trade_evaluation,
                    dataset_path=self.ml_dataset_path,
                    knowledge_path=self.ml_knowledge_path,
                )
                self._save_state()
            except Exception as e:
                print(f"[PaperTradingEngine] Trade evaluation / ML feedback hook: {e}")

            return {
                "success": True,
                "message": f"Closed {pos['contractSymbol']} @ ₹{exit_price:.2f} ({exit_reason}). Net P&L: ₹{final_net_pnl}",
                "trade": pos,
                "aiEvaluation": trade_evaluation,
            }

    # -----------------------------------------------------------------
    # Analytics & Reports (Daily, Weekly, Monthly)
    # -----------------------------------------------------------------
    def get_dashboard_metrics(self) -> Dict[str, Any]:
        """Calculates institutional performance statistics."""
        with self._save_lock:
            closed = list(self.state.get("closedTrades", []))
            open_pos = list(self.state.get("openPositions", []))
            total_trades = len(closed)

            wins = [t for t in closed if t.get("netPnl", 0) >= 0]
            losses = [t for t in closed if t.get("netPnl", 0) < 0]

            gross_profit = sum(t.get("grossPnl", 0) for t in wins)
            gross_loss = abs(sum(t.get("grossPnl", 0) for t in losses))
            net_pnl = sum(t.get("netPnl", 0) for t in closed)
            total_costs = sum(t.get("totalCosts", 0) for t in closed)

            win_rate = round((len(wins) / max(1, total_trades)) * 100.0, 1)
            profit_factor = round(gross_profit / max(1.0, gross_loss), 2)
            avg_win = round(gross_profit / max(1, len(wins)), 2)
            avg_loss = round(gross_loss / max(1, len(losses)), 2)

            # Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss)
            win_prob = len(wins) / max(1, total_trades)
            loss_prob = len(losses) / max(1, total_trades)
            expectancy = round((win_prob * avg_win) - (loss_prob * avg_loss), 2)

            # Maximum Drawdown
            equity_curve = [self.state.get("startingBalance", DEFAULT_CAPITAL)]
            curr_eq = equity_curve[0]
            for t in reversed(closed):
                curr_eq += t.get("netPnl", 0)
                equity_curve.append(curr_eq)

            peak = equity_curve[0]
            max_dd_rupees = 0.0
            for eq in equity_curve:
                if eq > peak:
                    peak = eq
                dd = peak - eq
                if dd > max_dd_rupees:
                    max_dd_rupees = dd

            max_dd_pct = round((max_dd_rupees / max(1.0, peak)) * 100.0, 2)

            return {
                "totalPaperTrades": total_trades,
                "openTradesCount": len(open_pos),
                "closedTradesCount": total_trades,
                "winningTrades": len(wins),
                "losingTrades": len(losses),
                "winRate": win_rate,
                "grossProfit": round(gross_profit, 2),
                "grossLoss": round(gross_loss, 2),
                "netPnl": round(net_pnl, 2),
                "profitFactor": profit_factor,
                "averageWin": avg_win,
                "averageLoss": avg_loss,
                "expectancy": expectancy,
                "maxDrawdownRupees": round(max_dd_rupees, 2),
                "maxDrawdownPercent": max_dd_pct,
                "totalTradingCosts": round(total_costs, 2),
                "currentBalance": round(self.state.get("balance", DEFAULT_CAPITAL), 2),
                "grossCashBalance": round(self.state.get("balance", DEFAULT_CAPITAL), 2),
                "netEquity": round(self.state.get("startingBalance", DEFAULT_CAPITAL) + net_pnl, 2),
                "startingBalance": round(self.state.get("startingBalance", DEFAULT_CAPITAL), 2),
                "openPositions": open_pos,
                "recentClosedTrades": closed[:10],
            }

    def get_portfolio_greeks(
        self,
        quotes: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Phase 7 / REQ-7.6: Computes real-time aggregate portfolio Greeks across active open positions.
        """
        from app.options.greeks_risk_engine import PortfolioGreeksAggregator
        with self._save_lock:
            open_pos = self.state.get("openPositions", [])
            return PortfolioGreeksAggregator.aggregate(open_pos, quotes=quotes)

    def reload_state(self) -> Dict[str, Any]:
        """Reloads the persisted state from disk into memory."""
        with self._save_lock:
            self.state = self._load_state()
            return self.state

    def reset_account(self, initial_capital: float = DEFAULT_CAPITAL):
        """Resets virtual portfolio."""
        with self._save_lock:
            self.state = {
                "balance": initial_capital,
                "startingBalance": initial_capital,
                "openPositions": [],
                "pendingOrders": [],
                "closedTrades": [],
                "totalRealizedGrossPnl": 0.0,
                "totalRealizedNetPnl": 0.0,
                "totalTradingCosts": 0.0,
                "winCount": 0,
                "lossCount": 0,
                "stateVersion": self._state_version,
                "lastUpdated": MarketCalendar.format_ist_timestamp(),
            }
            self._save_state()


paper_engine = PaperTradingEngine()

