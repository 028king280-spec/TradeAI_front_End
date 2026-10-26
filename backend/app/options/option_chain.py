from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import math
from app.data.market_calendar import MarketCalendar
from app.options.greeks import calculate_black_scholes
from app.options.pcr import calculate_pcr
from app.options.max_pain import calculate_max_pain
from app.options.oi_analysis import analyze_open_interest
from app.options.iv_analysis import analyze_implied_volatility
from app.data.instrument_master import get_instrument_master


def generate_index_option_chain(
    symbol: str,
    underlying_ltp: float,
    underlying_change: float = 0.0,
    raw_provider_chain: Optional[Dict[str, Any]] = None,
    real_quotes_map: Optional[Dict[str, Dict[str, Any]]] = None,
    expiry: Optional[str] = None,
    filter_mode: str = "ATM",  # "ATM" or "WIDE"
    vix_value: Optional[float] = None
) -> Dict[str, Any]:
    """
    Constructs an institutional option chain for Indian Indices (NIFTY, SENSEX, BANK NIFTY).
    When real_quotes_map is provided (from Angel One NFO quotes), populates exact market LTP,
    actual Bid/Ask, actual Open Interest, and exchange trading symbols.
    """
    clean_sym = symbol.upper().strip()
    now_ist = MarketCalendar.format_ist_timestamp()
    master = get_instrument_master()

    # Determine underlying key for master
    if "NIFTY" in clean_sym and "BANK" not in clean_sym and "FIN" not in clean_sym:
        und_key = "NIFTY"
        step = 50.0
        atm_strike = round(underlying_ltp / 50.0) * 50.0
        lot_size = 65  # Current official NSE lot size
    elif "BANK" in clean_sym:
        und_key = "BANKNIFTY"
        step = 100.0
        atm_strike = round(underlying_ltp / 100.0) * 100.0
        lot_size = 15
    elif "FIN" in clean_sym:
        und_key = "FINNIFTY"
        step = 50.0
        atm_strike = round(underlying_ltp / 50.0) * 50.0
        lot_size = 25
    elif "SENSEX" in clean_sym:
        und_key = "SENSEX"
        step = 100.0
        atm_strike = round(underlying_ltp / 100.0) * 100.0
        lot_size = 10
    else:
        und_key = clean_sym
        step = 50.0
        atm_strike = round(underlying_ltp / 50.0) * 50.0
        lot_size = 25

    # Retrieve real active expiries from InstrumentMaster
    real_expiries = master.get_expiries(und_key)
    if real_expiries:
        expiries = real_expiries[:8]
        selected_expiry = expiry if expiry and expiry in real_expiries else real_expiries[0]
    else:
        expiries = ["Current Weekly Expiry", "Next Weekly Expiry", "Current Month Expiry"]
        selected_expiry = expiries[0]

    num_strikes = 7 if filter_mode.upper() == "ATM" else 15
    strike_range = range(-num_strikes, num_strikes + 1)

    strikes: List[Dict[str, Any]] = []
    total_call_oi = 0
    total_put_oi = 0
    total_call_vol = 0
    total_put_vol = 0
    has_live_quotes = False

    base_iv = (vix_value / 100.0) if vix_value else 0.145

    quotes_map = real_quotes_map or {}

    for i in strike_range:
        k = round(atm_strike + (i * step), 2)
        dist_from_atm = (k - underlying_ltp) / step

        # Volatility smile skew
        ce_iv = max(0.08, base_iv + max(0.0, -dist_from_atm) * 0.003)
        pe_iv = max(0.08, base_iv + max(0.0, -dist_from_atm) * 0.007)

        # Greeks
        ce_greeks = calculate_black_scholes(underlying_ltp, k, 3.0 / 365.0, 0.065, ce_iv, "CE")
        pe_greeks = calculate_black_scholes(underlying_ltp, k, 3.0 / 365.0, 0.065, pe_iv, "PE")

        # Resolve real contracts from Instrument Master
        ce_contract = master.resolve_option_contract(und_key, k, "CE", selected_expiry)
        pe_contract = master.resolve_option_contract(und_key, k, "PE", selected_expiry)

        ce_token = str(ce_contract.get("token")) if ce_contract else None
        pe_token = str(pe_contract.get("token")) if pe_contract else None

        ce_live = quotes_map.get(ce_token) if ce_token else None
        pe_live = quotes_map.get(pe_token) if pe_token else None

        if ce_live or pe_live:
            has_live_quotes = True

        # CE Data: prioritize real Angel One quote
        if ce_live:
            ce_ltp = float(ce_live.get("ltp") or 0.0)
            ce_bid = float(ce_live.get("bid") or ce_ltp)
            ce_ask = float(ce_live.get("ask") or ce_ltp)
            ce_spread = float(ce_live.get("spread") or max(0.05, round(ce_ask - ce_bid, 2)))
            ce_oi = int(ce_live.get("openInterest") or 0)
            ce_vol = int(ce_live.get("volume") or 0)
            ce_chg_oi = int(ce_live.get("change") or 0)
            ce_status = "LIVE"
            ce_symbol = ce_live.get("tradingSymbol") or (ce_contract.get("symbol") if ce_contract else None)
        else:
            # Fallback theoretical estimate if contract not yet fetched
            decay_factor = math.exp(-0.5 * (dist_from_atm / 4.0) ** 2)
            sym_hash = (sum(ord(c) for c in clean_sym) + int(k)) % 1000
            ce_ltp = ce_greeks["price"]
            ce_bid = round(max(0.5, ce_ltp * 0.99), 1)
            ce_ask = round(ce_ltp * 1.01, 1)
            ce_spread = round(ce_ask - ce_bid, 2)
            ce_oi = int(120000 * decay_factor + (sym_hash * 35))
            ce_vol = int(ce_oi * 0.65)
            ce_chg_oi = int(15000 * decay_factor)
            ce_status = "MOCK"
            ce_symbol = ce_contract.get("symbol") if ce_contract else f"{clean_sym} {int(k)} CE"

        # PE Data: prioritize real Angel One quote
        if pe_live:
            pe_ltp = float(pe_live.get("ltp") or 0.0)
            pe_bid = float(pe_live.get("bid") or pe_ltp)
            pe_ask = float(pe_live.get("ask") or pe_ltp)
            pe_spread = float(pe_live.get("spread") or max(0.05, round(pe_ask - pe_bid, 2)))
            pe_oi = int(pe_live.get("openInterest") or 0)
            pe_vol = int(pe_live.get("volume") or 0)
            pe_chg_oi = int(pe_live.get("change") or 0)
            pe_status = "LIVE"
            pe_symbol = pe_live.get("tradingSymbol") or (pe_contract.get("symbol") if pe_contract else None)
        else:
            decay_factor = math.exp(-0.5 * (dist_from_atm / 4.0) ** 2)
            sym_hash = (sum(ord(c) for c in clean_sym) + int(k)) % 1000
            pe_ltp = pe_greeks["price"]
            pe_bid = round(max(0.5, pe_ltp * 0.99), 1)
            pe_ask = round(pe_ltp * 1.01, 1)
            pe_spread = round(pe_ask - pe_bid, 2)
            pe_oi = int(125000 * decay_factor + ((1000 - sym_hash) * 35))
            pe_vol = int(pe_oi * 0.65)
            pe_chg_oi = int(15000 * decay_factor)
            pe_status = "MOCK"
            pe_symbol = pe_contract.get("symbol") if pe_contract else f"{clean_sym} {int(k)} PE"

        total_call_oi += ce_oi
        total_put_oi += pe_oi
        total_call_vol += ce_vol
        total_put_vol += pe_vol

        ce_moneyness = "ATM" if abs(k - underlying_ltp) < (step * 0.5) else ("ITM" if k < underlying_ltp else "OTM")
        pe_moneyness = "ATM" if abs(k - underlying_ltp) < (step * 0.5) else ("ITM" if k > underlying_ltp else "OTM")

        strikes.append({
            "strike": k,
            "isAtm": abs(k - underlying_ltp) < (step * 0.5),
            "ce": {
                "ltp": ce_ltp,
                "oi": ce_oi,
                "changeInOi": ce_chg_oi,
                "volume": ce_vol,
                "iv": round(ce_iv * 100.0, 1),
                "delta": ce_greeks["delta"],
                "gamma": ce_greeks["gamma"],
                "theta": ce_greeks["theta"],
                "vega": ce_greeks["vega"],
                "moneyness": ce_moneyness,
                "bid": ce_bid,
                "ask": ce_ask,
                "spread": ce_spread,
                "contractSymbol": ce_symbol,
                "instrumentToken": ce_token,
                "expiry": selected_expiry,
                "dataStatus": ce_status,
                "marketTimestamp": ce_live.get("marketTimestamp") if ce_live else now_ist,
            },
            "pe": {
                "ltp": pe_ltp,
                "oi": pe_oi,
                "changeInOi": pe_chg_oi,
                "volume": pe_vol,
                "iv": round(pe_iv * 100.0, 1),
                "delta": pe_greeks["delta"],
                "gamma": pe_greeks["gamma"],
                "theta": pe_greeks["theta"],
                "vega": pe_greeks["vega"],
                "moneyness": pe_moneyness,
                "bid": pe_bid,
                "ask": pe_ask,
                "spread": pe_spread,
                "contractSymbol": pe_symbol,
                "instrumentToken": pe_token,
                "expiry": selected_expiry,
                "dataStatus": pe_status,
                "marketTimestamp": pe_live.get("marketTimestamp") if pe_live else now_ist,
            }
        })

    # Calculations across chain
    pcr_result = calculate_pcr(total_put_oi, total_call_oi, total_put_vol, total_call_vol)
    max_pain_result = calculate_max_pain(strikes)
    oi_analytics = analyze_open_interest(strikes, underlying_ltp, underlying_change)
    iv_analytics = analyze_implied_volatility(strikes, underlying_ltp, vix_value)

    return {
        "symbol": clean_sym,
        "underlyingPrice": round(underlying_ltp, 2),
        "underlyingChange": round(underlying_change, 2),
        "atmStrike": atm_strike,
        "strikeStep": step,
        "lotSize": lot_size,
        "selectedExpiry": selected_expiry,
        "availableExpiries": expiries,
        "filterMode": filter_mode.upper(),
        "pcr": pcr_result,
        "maxPain": max_pain_result,
        "oiAnalysis": oi_analytics,
        "ivAnalysis": iv_analytics,
        "strikes": strikes,
        "totalCallOi": total_call_oi,
        "totalPutOi": total_put_oi,
        "dataStatus": "LIVE" if has_live_quotes else "MOCK",
        "dataTimestamp": now_ist,
        "analysisTimestamp": now_ist,
    }
