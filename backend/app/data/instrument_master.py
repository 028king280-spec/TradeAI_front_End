"""
Angel One SmartAPI Instrument Master & Contract Resolver.
Loads, indexes, and resolves official NSE and NFO instruments from OpenAPIScripMaster.json.
Provides fast in-memory indexing of:
- Underlying Indices & Equities (NSE)
- Active Option Contracts (NFO) by Strike, Expiry, and Option Type (CE/PE)
"""

import json
import os
import re
from datetime import datetime, date
from typing import Dict, List, Optional, Any, Tuple
from app.core.logging import logger

SCRIP_MASTER_PATH = os.path.join(os.path.dirname(__file__), "OpenAPIScripMaster.json")

class InstrumentMaster:
    _instance: Optional["InstrumentMaster"] = None

    def __init__(self):
        self._loaded = False
        # Index dictionaries
        # (symbol, exch_seg) -> instrument dict
        self._equity_by_symbol: Dict[str, Dict[str, Any]] = {}
        # token -> instrument dict
        self._by_token: Dict[str, Dict[str, Any]] = {}
        self._by_exchange_token: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # (underlying, expiry_str, strike_float, option_type) -> instrument dict
        self._options_by_spec: Dict[Tuple[str, str, float, str], Dict[str, Any]] = {}
        # option symbol -> instrument dict
        self._options_by_symbol: Dict[str, Dict[str, Any]] = {}
        # underlying -> list of unique sorted expiry date strings
        self._expiries_by_underlying: Dict[str, List[str]] = {}

    @classmethod
    def get_instance(cls) -> "InstrumentMaster":
        if cls._instance is None:
            cls._instance = InstrumentMaster()
            cls._instance.load()
        return cls._instance

    def is_loaded(self) -> bool:
        return self._loaded

    def load(self, force_reload: bool = False):
        if self._loaded and not force_reload:
            return

        if not os.path.exists(SCRIP_MASTER_PATH):
            logger.warning(f"Instrument master file not found at {SCRIP_MASTER_PATH}")
            return

        try:
            logger.info("Indexing Angel One OpenAPIScripMaster instruments...")
            with open(SCRIP_MASTER_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            today = date.today()
            expiries_set: Dict[str, set] = {}

            for item in data:
                exch_seg = item.get("exch_seg")
                token = item.get("token")
                name = (item.get("name") or "").upper().strip()
                symbol = (item.get("symbol") or "").upper().strip()
                instrument_type = item.get("instrumenttype") or ""

                if not token:
                    continue
                self._by_exchange_token[(exch_seg, str(token))] = item

                if token not in self._by_token or exch_seg in ("NSE", "NFO"):
                    self._by_token[token] = item

                # 1. NSE Equities & Benchmark Indices
                if exch_seg in ("NSE", "BSE") and instrument_type in ("", "AMXIDX", "INDEX"):
                    clean_name = name.replace(" ", "")
                    clean_sym = symbol.replace("-EQ", "").replace(" ", "")
                    self._equity_by_symbol[(clean_name, exch_seg)] = item
                    self._equity_by_symbol[(clean_sym, exch_seg)] = item
                    if "NIFTY" in clean_name or "SENSEX" in clean_name or "BANKNIFTY" in clean_name:
                        self._equity_by_symbol[(clean_name, "NSE")] = item

                # 2. NFO Index & Stock Options (OPTIDX, OPTSTK)
                elif exch_seg in ("NFO", "BFO") and instrument_type in ("OPTIDX", "OPTSTK"):
                    expiry_raw = item.get("expiry") or ""
                    strike_raw = item.get("strike") or "0"

                    try:
                        # Angel One strikes in ScripMaster are in paise (divided by 100)
                        strike_val = round(float(strike_raw) / 100.0, 2)
                    except ValueError:
                        continue

                    # Option Type from symbol suffix
                    opt_type = "CE" if symbol.endswith("CE") else ("PE" if symbol.endswith("PE") else None)
                    if not opt_type:
                        continue

                    # Parse expiry date to filter out already-expired contracts
                    # Format: 19OCT2026 or 29DEC2026
                    try:
                        exp_dt = datetime.strptime(expiry_raw, "%d%b%Y").date()
                        # Allow today and future expiries
                        if exp_dt < today:
                            continue
                    except Exception:
                        pass

                    key = (name, expiry_raw, strike_val, opt_type)
                    self._options_by_spec[key] = item
                    self._options_by_symbol[symbol] = item

                    if name not in expiries_set:
                        expiries_set[name] = set()
                    expiries_set[name].add(expiry_raw)

            # Sort expiries chronologically
            for und, exp_set in expiries_set.items():
                sorted_exp = sorted(
                    list(exp_set),
                    key=lambda x: datetime.strptime(x, "%d%b%Y") if self._is_valid_date(x) else datetime.max
                )
                self._expiries_by_underlying[und] = sorted_exp

            self._loaded = True
            logger.info(
                f"✅ InstrumentMaster indexed: {len(self._options_by_spec):,} active option contracts, "
                f"{len(self._expiries_by_underlying)} option underlyings, {len(self._equity_by_symbol)} equities/indices."
            )

        except Exception as e:
            logger.error(f"Failed to load InstrumentMaster: {e}")

    @staticmethod
    def _is_valid_date(s: str) -> bool:
        try:
            datetime.strptime(s, "%d%b%Y")
            return True
        except ValueError:
            return False

    def get_expiries(self, underlying: str) -> List[str]:
        """Returns sorted list of active future expiry date strings (e.g. ['19OCT2026', '26OCT2026'])."""
        clean = underlying.upper().replace(" 50", "").replace(" ", "").strip()
        # Canonical mappings
        if clean in ("NIFTY50", "NIFTY"):
            key = "NIFTY"
        elif clean in ("BANKNIFTY", "NIFTYBANK"):
            key = "BANKNIFTY"
        elif clean in ("FINNIFTY", "NIFTYFIN"):
            key = "FINNIFTY"
        else:
            key = clean
        return self._expiries_by_underlying.get(key, [])

    def get_option_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Returns option contract dict for given symbol if indexed, else None."""
        clean = symbol.upper().strip()
        return self._options_by_symbol.get(clean)

    def resolve_option_contract(
        self,
        underlying: str,
        strike: float,
        option_type: str,
        expiry: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Resolves exact official Angel One option contract specification:
        Returns {token, symbol, name, expiry, strike, lotsize, exch_seg, tick_size}.
        """
        clean = underlying.upper().replace(" 50", "").replace(" ", "").strip()
        if clean in ("NIFTY50", "NIFTY"):
            key_und = "NIFTY"
        elif clean in ("BANKNIFTY", "NIFTYBANK"):
            key_und = "BANKNIFTY"
        elif clean in ("FINNIFTY", "NIFTYFIN"):
            key_und = "FINNIFTY"
        else:
            key_und = clean

        expiries = self.get_expiries(key_und)
        if not expiries:
            return None

        rounded_strike = round(float(strike), 2)
        target_opt = option_type.upper().strip()

        # Search across active expiries (starting with preferred/nearest)
        target_expiries = [expiry] if (expiry and expiry in expiries) else expiries
        for cand_exp in target_expiries:
            contract = self._options_by_spec.get((key_und, cand_exp, rounded_strike, target_opt))
            if contract:
                return contract

        # If exact strike match failed across expiries, search nearest strike within 5 points
        for cand_exp in target_expiries:
            candidates = [
                (spec, item) for spec, item in self._options_by_spec.items()
                if spec[0] == key_und and spec[1] == cand_exp and spec[3] == target_opt
            ]
            if candidates:
                best_match = min(candidates, key=lambda c: abs(c[0][2] - rounded_strike))
                if abs(best_match[0][2] - rounded_strike) <= 5.0:
                    return best_match[1]

        return None

    def get_option_chain_contracts(
        self,
        underlying: str,
        atm_strike: float,
        step: float,
        num_strikes: int = 7,
        expiry: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Resolves paired CE and PE contracts for a strike ladder around ATM strike.
        """
        clean = underlying.upper().replace(" 50", "").replace(" ", "").strip()
        if clean in ("NIFTY50", "NIFTY"):
            key_und = "NIFTY"
        elif clean in ("BANKNIFTY", "NIFTYBANK"):
            key_und = "BANKNIFTY"
        elif clean in ("FINNIFTY", "NIFTYFIN"):
            key_und = "FINNIFTY"
        else:
            key_und = clean

        expiries = self.get_expiries(key_und)
        if not expiries:
            return []

        chosen_expiry = expiry
        if not chosen_expiry or chosen_expiry not in expiries:
            # Pick first expiry that actually has strikes around atm_strike
            for exp in expiries:
                if (key_und, exp, round(atm_strike, 2), "CE") in self._options_by_spec or \
                   (key_und, exp, round(atm_strike, 2), "PE") in self._options_by_spec:
                    chosen_expiry = exp
                    break
            if not chosen_expiry:
                chosen_expiry = expiries[0]
        results = []

        strike_range = range(-num_strikes, num_strikes + 1)
        for i in strike_range:
            k = round(atm_strike + (i * step), 2)
            ce_contract = self._options_by_spec.get((key_und, chosen_expiry, k, "CE"))
            pe_contract = self._options_by_spec.get((key_und, chosen_expiry, k, "PE"))

            results.append({
                "strike": k,
                "expiry": chosen_expiry,
                "underlying": key_und,
                "ce_contract": ce_contract,
                "pe_contract": pe_contract,
                "is_atm": (i == 0),
            })

        return results

    def resolve_token(self, token: str, exchange: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if exchange is not None:
            return self._by_exchange_token.get((exchange.upper(), str(token)))
        return self._by_token.get(token)

    def get_equity(self, symbol: str, preferred_exch: str = "NSE") -> Optional[Dict[str, Any]]:
        """
        Dynamically finds official equity scrip across 30,000+ NSE/BSE listed instruments.
        """
        clean = symbol.upper().replace("-EQ", "").replace(" ", "").strip()
        # 1. Try preferred exchange
        eq = self._equity_by_symbol.get((clean, preferred_exch))
        if eq:
            return eq
        # 2. Try NSE then BSE
        for ex in ("NSE", "BSE"):
            eq = self._equity_by_symbol.get((clean, ex))
            if eq:
                return eq
        return None

    def get_strikes_for_underlying(self, underlying: str, expiry: Optional[str] = None) -> List[float]:
        """
        Returns sorted list of distinct available option strikes for an underlying.
        """
        clean = underlying.upper().replace(" 50", "").replace(" ", "").strip()
        if clean in ("NIFTY50", "NIFTY"):
            key_und = "NIFTY"
        elif clean in ("BANKNIFTY", "NIFTYBANK"):
            key_und = "BANKNIFTY"
        elif clean in ("FINNIFTY", "NIFTYFIN"):
            key_und = "FINNIFTY"
        else:
            key_und = clean

        strikes = set()
        for (u, exp, strike, _opt) in self._options_by_spec.keys():
            if u == key_und:
                if expiry is None or exp == expiry:
                    strikes.add(strike)
        return sorted(strikes)


# Global singleton helper
def get_instrument_master() -> InstrumentMaster:
    return InstrumentMaster.get_instance()
