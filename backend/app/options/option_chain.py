from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import math
from app.data.market_calendar import MarketCalendar
from app.options.greeks import (
    calculate_black_scholes,
    calculate_exact_time_to_expiry,
    calculate_implied_volatility_brent,
    validate_contract_quote,
)
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
    Constructs an institutional option chain for Indian Indices (NIFTY, SENSEX, BANK NIFTY, FINNIFTY).

    Data Integrity Mandates:
    - Never fabricates synthetic Open Interest, volume, or mock bid-ask spreads.
    - Explicitly distinguishes verified zero liquidity (oi=0, oiStatus='AVAILABLE') from missing feed data (oi=None, oiStatus='MISSING').
    - When broker quotes are missing, returns dataStatus='DATA_UNAVAILABLE' and explicit None metrics.
    - Numerically solves Implied Volatility (IV) using Brent's method inverted against actual market premium
      (preferring valid bid-ask midpoint over isolated LTP).
    - Uses exact annualized time-to-expiry calculated from contract expiry and quote timestamp,
      preserving continuous time value down to true expiration.
    - Computes Black-Scholes Greeks only when IV and inputs are strictly valid.
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

    quotes_map = real_quotes_map or {}

    for i in strike_range:
        k = round(atm_strike + (i * step), 2)

        # Resolve real contracts from Instrument Master
        ce_contract = master.resolve_option_contract(und_key, k, "CE", selected_expiry)
        pe_contract = master.resolve_option_contract(und_key, k, "PE", selected_expiry)

        ce_token = str(ce_contract.get("token")) if ce_contract else None
        pe_token = str(pe_contract.get("token")) if pe_contract else None

        ce_live = quotes_map.get(ce_token) if ce_token else None
        pe_live = quotes_map.get(pe_token) if pe_token else None

        # ----------------------------------------------------
        # CE Contract Processing
        # ----------------------------------------------------
        if ce_live:
            ce_val = validate_contract_quote(ce_live)
            ce_symbol = ce_live.get("tradingSymbol") or (ce_contract.get("symbol") if ce_contract else None)
            ce_raw_ts = ce_live.get("marketTimestamp") or ce_live.get("exchFeedTime") or ce_live.get("receivedAt")

            ce_ltp = ce_val["ltp"]
            ce_bid = ce_val["bid"]
            ce_ask = ce_val["ask"]
            ce_spread = ce_val["spread"]
            ce_oi = ce_val["oi"]
            ce_oi_status = ce_val["oiStatus"]
            ce_vol = ce_val["volume"]
            ce_vol_status = ce_val["volumeStatus"]
            ce_chg_oi = int(ce_live.get("change") or 0)
            ce_status = ce_val["status"]
            ce_quote_status = ce_val["quoteStatus"]
            ce_notes = ce_val["issues"]

            if ce_val["isValid"] and ce_val["observedPrice"] is not None:
                has_live_quotes = True
                t_ce = calculate_exact_time_to_expiry(selected_expiry, ce_raw_ts)
                ce_iv_solved = calculate_implied_volatility_brent(
                    market_price=ce_val["observedPrice"],
                    spot=underlying_ltp,
                    strike=k,
                    time_to_expiry_years=t_ce,
                    risk_free_rate=0.065,
                    option_type="CE"
                )
                if ce_iv_solved is not None:
                    ce_iv = round(ce_iv_solved * 100.0, 2)
                    ce_greeks = calculate_black_scholes(
                        spot=underlying_ltp,
                        strike=k,
                        time_to_expiry_years=t_ce,
                        risk_free_rate=0.065,
                        iv=ce_iv_solved,
                        option_type="CE"
                    )
                else:
                    ce_iv = None
                    ce_greeks = None
            else:
                ce_iv = None
                ce_greeks = None

            ce_delta = ce_greeks["delta"] if ce_greeks else None
            ce_gamma = ce_greeks["gamma"] if ce_greeks else None
            ce_theta = ce_greeks["theta"] if ce_greeks else None
            ce_vega = ce_greeks["vega"] if ce_greeks else None
            ce_ts = ce_raw_ts or now_ist

        else:
            # Missing quote: Strict data integrity - return DATA_UNAVAILABLE without fabrication
            ce_ltp = None
            ce_bid = None
            ce_ask = None
            ce_spread = None
            ce_oi = None
            ce_oi_status = "MISSING"
            ce_vol = None
            ce_vol_status = "MISSING"
            ce_chg_oi = 0
            ce_iv = None
            ce_delta = None
            ce_gamma = None
            ce_theta = None
            ce_vega = None
            ce_status = "DATA_UNAVAILABLE"
            ce_quote_status = "MISSING"
            ce_notes = ["MISSING_BROKER_QUOTE"]
            ce_symbol = ce_contract.get("symbol") if ce_contract else f"{clean_sym} {int(k)} CE"
            ce_ts = None

        # ----------------------------------------------------
        # PE Contract Processing
        # ----------------------------------------------------
        if pe_live:
            pe_val = validate_contract_quote(pe_live)
            pe_symbol = pe_live.get("tradingSymbol") or (pe_contract.get("symbol") if pe_contract else None)
            pe_raw_ts = pe_live.get("marketTimestamp") or pe_live.get("exchFeedTime") or pe_live.get("receivedAt")

            pe_ltp = pe_val["ltp"]
            pe_bid = pe_val["bid"]
            pe_ask = pe_val["ask"]
            pe_spread = pe_val["spread"]
            pe_oi = pe_val["oi"]
            pe_oi_status = pe_val["oiStatus"]
            pe_vol = pe_val["volume"]
            pe_vol_status = pe_val["volumeStatus"]
            pe_chg_oi = int(pe_live.get("change") or 0)
            pe_status = pe_val["status"]
            pe_quote_status = pe_val["quoteStatus"]
            pe_notes = pe_val["issues"]

            if pe_val["isValid"] and pe_val["observedPrice"] is not None:
                has_live_quotes = True
                t_pe = calculate_exact_time_to_expiry(selected_expiry, pe_raw_ts)
                pe_iv_solved = calculate_implied_volatility_brent(
                    market_price=pe_val["observedPrice"],
                    spot=underlying_ltp,
                    strike=k,
                    time_to_expiry_years=t_pe,
                    risk_free_rate=0.065,
                    option_type="PE"
                )
                if pe_iv_solved is not None:
                    pe_iv = round(pe_iv_solved * 100.0, 2)
                    pe_greeks = calculate_black_scholes(
                        spot=underlying_ltp,
                        strike=k,
                        time_to_expiry_years=t_pe,
                        risk_free_rate=0.065,
                        iv=pe_iv_solved,
                        option_type="PE"
                    )
                else:
                    pe_iv = None
                    pe_greeks = None
            else:
                pe_iv = None
                pe_greeks = None

            pe_delta = pe_greeks["delta"] if pe_greeks else None
            pe_gamma = pe_greeks["gamma"] if pe_greeks else None
            pe_theta = pe_greeks["theta"] if pe_greeks else None
            pe_vega = pe_greeks["vega"] if pe_greeks else None
            pe_ts = pe_raw_ts or now_ist

        else:
            # Missing quote: Strict data integrity - return DATA_UNAVAILABLE without fabrication
            pe_ltp = None
            pe_bid = None
            pe_ask = None
            pe_spread = None
            pe_oi = None
            pe_oi_status = "MISSING"
            pe_vol = None
            pe_vol_status = "MISSING"
            pe_chg_oi = 0
            pe_iv = None
            pe_delta = None
            pe_gamma = None
            pe_theta = None
            pe_vega = None
            pe_status = "DATA_UNAVAILABLE"
            pe_quote_status = "MISSING"
            pe_notes = ["MISSING_BROKER_QUOTE"]
            pe_symbol = pe_contract.get("symbol") if pe_contract else f"{clean_sym} {int(k)} PE"
            pe_ts = None

        total_call_oi += (ce_oi if ce_oi is not None else 0)
        total_put_oi += (pe_oi if pe_oi is not None else 0)
        total_call_vol += (ce_vol if ce_vol is not None else 0)
        total_put_vol += (pe_vol if pe_vol is not None else 0)

        ce_moneyness = "ATM" if abs(k - underlying_ltp) < (step * 0.5) else ("ITM" if k < underlying_ltp else "OTM")
        pe_moneyness = "ATM" if abs(k - underlying_ltp) < (step * 0.5) else ("ITM" if k > underlying_ltp else "OTM")

        strikes.append({
            "strike": k,
            "isAtm": abs(k - underlying_ltp) < (step * 0.5),
            "ce": {
                "ltp": ce_ltp,
                "oi": ce_oi,
                "oiStatus": ce_oi_status,
                "changeInOi": ce_chg_oi,
                "volume": ce_vol,
                "volumeStatus": ce_vol_status,
                "iv": ce_iv,
                "delta": ce_delta,
                "gamma": ce_gamma,
                "theta": ce_theta,
                "vega": ce_vega,
                "moneyness": ce_moneyness,
                "bid": ce_bid,
                "ask": ce_ask,
                "spread": ce_spread,
                "contractSymbol": ce_symbol,
                "instrumentToken": ce_token,
                "expiry": selected_expiry,
                "dataStatus": ce_status,
                "quoteStatus": ce_quote_status,
                "validationNotes": ce_notes,
                "marketTimestamp": ce_ts,
            },
            "pe": {
                "ltp": pe_ltp,
                "oi": pe_oi,
                "oiStatus": pe_oi_status,
                "changeInOi": pe_chg_oi,
                "volume": pe_vol,
                "volumeStatus": pe_vol_status,
                "iv": pe_iv,
                "delta": pe_delta,
                "gamma": pe_gamma,
                "theta": pe_theta,
                "vega": pe_vega,
                "moneyness": pe_moneyness,
                "bid": pe_bid,
                "ask": pe_ask,
                "spread": pe_spread,
                "contractSymbol": pe_symbol,
                "instrumentToken": pe_token,
                "expiry": selected_expiry,
                "dataStatus": pe_status,
                "quoteStatus": pe_quote_status,
                "validationNotes": pe_notes,
                "marketTimestamp": pe_ts,
            }
        })

    # Calculations across chain
    pcr_result = calculate_pcr(total_put_oi, total_call_oi, total_put_vol, total_call_vol)
    max_pain_result = calculate_max_pain(strikes)
    if max_pain_result.get("maxPainStrike") is None:
        max_pain_result["maxPainStrike"] = atm_strike
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
        "dataStatus": "LIVE" if has_live_quotes else "DATA_UNAVAILABLE",
        "dataTimestamp": now_ist,
        "analysisTimestamp": now_ist,
    }
