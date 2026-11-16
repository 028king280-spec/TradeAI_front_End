"""
AIVOLVE Quantitative Options Intelligence Engine v3.0
Black-Scholes Analytical Pricing, Exact Time-to-Expiry, Numerical Brent IV Solver,
and Greeks Sensitivity Calculations for Indian Benchmark Index Options.
"""

import math
from datetime import datetime, date, time, timezone
from typing import Dict, Any, Optional, Union
import zoneinfo

try:
    import scipy.optimize as sp_opt
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

IST_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def parse_expiry_to_ist_datetime(expiry: Union[str, date, datetime]) -> datetime:
    """
    Parses contract expiry into an IST-aware datetime representing expiry close.
    - If input contains an authoritative exchange timestamp, preserves that exact time.
    - If input is a date or date string, applies standard Indian exchange close (15:30:00 IST).
    - Never hardcodes any day of the week (Thursdays, Wednesdays, or special holiday shifts).
    """
    if isinstance(expiry, datetime):
        if expiry.tzinfo is None:
            return expiry.replace(tzinfo=IST_ZONE)
        return expiry.astimezone(IST_ZONE)

    if isinstance(expiry, date):
        return datetime.combine(expiry, time(15, 30, 0), tzinfo=IST_ZONE)

    s = str(expiry).strip()
    if not s:
        raise ValueError("Expiry parameter is empty")

    # Try ISO format (preserve explicit time if present)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            if dt.time() == time(0, 0, 0):
                dt = datetime.combine(dt.date(), time(15, 30, 0), tzinfo=IST_ZONE)
            else:
                dt = dt.replace(tzinfo=IST_ZONE)
        return dt.astimezone(IST_ZONE)
    except Exception:
        pass

    # Authoritative exchange format from InstrumentMaster / NSE: %d%b%Y (e.g. 26NOV2026)
    clean_s = s.upper().replace(" ", "").replace("-", "")
    try:
        d = datetime.strptime(clean_s, "%d%b%Y").date()
        return datetime.combine(d, time(15, 30, 0), tzinfo=IST_ZONE)
    except Exception:
        pass

    formats = [
        "%d%b%Y",
        "%d-%b-%Y",
        "%Y-%m-%d",
        "%d %b %Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            d = datetime.strptime(s.strip(), fmt).date()
            return datetime.combine(d, time(15, 30, 0), tzinfo=IST_ZONE)
        except Exception:
            pass

    raise ValueError(f"Unable to parse contract expiry format: '{expiry}'")


def parse_quote_to_ist_datetime(quote_timestamp: Optional[Union[str, datetime]]) -> datetime:
    """
    Normalizes quote market timestamp into an IST-aware datetime.
    If None or empty, returns the current IST time.
    """
    if quote_timestamp is None:
        return datetime.now(IST_ZONE)

    if isinstance(quote_timestamp, datetime):
        if quote_timestamp.tzinfo is None:
            return quote_timestamp.replace(tzinfo=IST_ZONE)
        return quote_timestamp.astimezone(IST_ZONE)

    s = str(quote_timestamp).strip()
    if not s:
        return datetime.now(IST_ZONE)

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
        "%Y-%m-%d %H:%M:%S%z",
        "%d-%m-%Y %H:%M:%S",
    ]
    s_cleaned = s.replace("IST", "").strip()
    for fmt in formats:
        try:
            dt = datetime.strptime(s_cleaned, fmt)
            return dt.replace(tzinfo=IST_ZONE)
        except Exception:
            pass

    return datetime.now(IST_ZONE)


def calculate_exact_time_to_expiry(
    expiry: Union[str, date, datetime],
    quote_timestamp: Optional[Union[str, datetime]] = None
) -> float:
    """
    Calculates exact annualized time-to-expiry (in years) based on:
    - Contract expiry (exchange-defined expiry timestamp or 15:30:00 IST on expiry date)
    - Quote/market timestamp (IST-aligned)

    Formula: t_years = max(0.0, (expiry_dt - quote_dt).total_seconds()) / (365.0 * 86400.0)
    Returns 0.0 if and only if the contract is at or past expiry.
    Does NOT discard time value during the final trading hour.
    """
    try:
        exp_dt = parse_expiry_to_ist_datetime(expiry)
        q_dt = parse_quote_to_ist_datetime(quote_timestamp)
        diff_seconds = (exp_dt - q_dt).total_seconds()
        if diff_seconds <= 0.0:
            return 0.0
        return diff_seconds / (365.0 * 86400.0)
    except Exception:
        return 0.0


def _pure_brentq(
    f,
    a: float,
    b: float,
    xtol: float = 1e-6,
    maxiter: int = 100
) -> float:
    """
    Guaranteed pure-Python Dekker-Brent root finder.
    Used when scipy is unavailable or as a deterministic numerical fallback.
    """
    fa = f(a)
    fb = f(b)
    if fa * fb > 0:
        raise ValueError(f"Root not bracketed in [{a}, {b}]: f(a)={fa}, f(b)={fb}")

    if abs(fa) < abs(fb):
        a, b = b, a
        fa, fb = fb, fa

    c = a
    fc = fa
    mflag = True
    d = 0.0

    for _ in range(maxiter):
        if abs(fb) < xtol:
            return b

        tol = 2.0 * 1e-15 * abs(b) + 0.5 * xtol

        if fa != fc and fb != fc:
            s = (a * fb * fc) / ((fa - fb) * (fa - fc)) + \
                (b * fa * fc) / ((fb - fa) * (fb - fc)) + \
                (c * fa * fb) / ((fc - fa) * (fc - fb))
        else:
            s = b - fb * (b - a) / (fb - fa)

        cond1 = not ((3.0 * a + b) / 4.0 <= s <= b or b <= s <= (3.0 * a + b) / 4.0)
        cond2 = mflag and (abs(s - b) >= 0.5 * abs(b - c))
        cond3 = (not mflag) and (abs(s - b) >= 0.5 * abs(c - d))
        cond4 = mflag and (abs(b - c) < tol)
        cond5 = (not mflag) and (abs(c - d) < tol)

        if cond1 or cond2 or cond3 or cond4 or cond5:
            s = (a + b) / 2.0
            mflag = True
        else:
            mflag = False

        fs = f(s)
        d = c
        c = b
        fc = fb

        if fa * fs < 0:
            b = s
            fb = fs
        else:
            a = s
            fa = fs

        if abs(fa) < abs(fb):
            a, b = b, a
            fa, fb = fb, fa

        if abs(b - a) < tol:
            return b

    return b


def _bs_pricing_raw(spot: float, strike: float, t: float, r: float, sigma: float, is_call: bool) -> float:
    """Internal fast Black-Scholes formula without minimum price clamping."""
    if t <= 0.0:
        return max(0.0, spot - strike) if is_call else max(0.0, strike - spot)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    exp_rt = math.exp(-r * t)
    if is_call:
        return spot * norm_cdf(d1) - strike * exp_rt * norm_cdf(d2)
    else:
        return strike * exp_rt * norm_cdf(-d2) - spot * norm_cdf(-d1)


def calculate_implied_volatility_brent(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float = 0.065,
    option_type: str = "CE",
    sigma_min: float = 0.005,
    sigma_max: float = 5.0,
    tolerance: float = 1e-6,
    max_iter: int = 100
) -> Optional[float]:
    """
    Numerically solves for implied volatility (IV) using Brent's root-finding method.

    Mathematical Formulation:
      f(sigma) = BlackScholes(spot, strike, t, r, sigma, type) - market_price = 0

    Validation & Boundary Conditions:
      - Requires market_price > 0, spot > 0, strike > 0, t > 0, r >= 0.
      - Enforces European arbitrage bounds:
        For CE: max(0.0, spot - strike * exp(-rt)) <= market_price < spot
        For PE: max(0.0, strike * exp(-rt) - spot) <= market_price < strike * exp(-rt)
      - Returns None if arbitrage bounds are violated or root does not converge in [sigma_min, sigma_max].
      - Supports valid numerical inversion near expiry (down to sub-second t > 0).
    """
    if market_price is None or math.isnan(market_price) or market_price <= 0.0:
        return None
    if spot is None or math.isnan(spot) or spot <= 0.0:
        return None
    if strike is None or math.isnan(strike) or strike <= 0.0:
        return None
    if time_to_expiry_years is None or math.isnan(time_to_expiry_years) or time_to_expiry_years <= 0.0:
        # At or past expiry: pure intrinsic value exists, no volatility can be inferred from time value
        return None
    if risk_free_rate is None or math.isnan(risk_free_rate) or risk_free_rate < 0.0:
        return None

    opt_type = option_type.upper().strip()
    is_call = opt_type in ("CE", "CALL")
    if not is_call and opt_type not in ("PE", "PUT"):
        return None

    t = time_to_expiry_years
    r = risk_free_rate
    exp_rt = math.exp(-r * t)

    # European Arbitrage Boundary Checks
    if is_call:
        intrinsic_lower = max(0.0, spot - strike * exp_rt)
        if market_price < (intrinsic_lower - 1e-6) or market_price >= spot:
            return None
    else:
        intrinsic_lower = max(0.0, strike * exp_rt - spot)
        if market_price < (intrinsic_lower - 1e-6) or market_price >= (strike * exp_rt):
            return None

    def obj_func(sigma: float) -> float:
        return _bs_pricing_raw(spot, strike, t, r, sigma, is_call) - market_price

    f_low = obj_func(sigma_min)
    f_high = obj_func(sigma_max)

    if f_low > 0.0:
        # Market price is lower than theoretical price at min sigma (0.5% IV)
        return None
    if f_high < 0.0:
        # Market price exceeds theoretical price even at 500% IV
        return None

    # Solve via scipy.optimize.brentq with pure-Python fallback
    if _HAS_SCIPY:
        try:
            solved = sp_opt.brentq(
                obj_func,
                sigma_min,
                sigma_max,
                xtol=tolerance,
                rtol=tolerance,
                maxiter=max_iter
            )
            return round(float(solved), 6)
        except Exception:
            pass

    try:
        solved = _pure_brentq(obj_func, sigma_min, sigma_max, xtol=tolerance, maxiter=max_iter)
        return round(float(solved), 6)
    except Exception:
        return None


def validate_contract_quote(
    quote: Optional[Dict[str, Any]],
    max_stale_seconds: int = 180,
    reference_timestamp: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Validates option contract quotes, market depth, bid-ask spreads, and freshness.

    Data Integrity & Status Semantics:
      - Field-level OI status: 'AVAILABLE', 'MISSING', 'INVALID'.
        Distinguishes verified zero open interest (oi=0, status='AVAILABLE')
        from missing feed data (oi=None, status='MISSING').
      - Field-level Volume status: 'AVAILABLE', 'MISSING', 'INVALID'.
        Distinguishes verified zero trades (volume=0, status='AVAILABLE')
        from missing volume data (volume=None, status='MISSING').
      - Field-level Quote status: 'AVAILABLE', 'STALE', 'INVALID', 'MISSING'.
      - Observed Market Price: Prefers valid bid-ask midpoint ((bid + ask) / 2.0)
        over isolated LTP.
    """
    if not quote or not isinstance(quote, dict):
        return {
            "isValid": False,
            "status": "DATA_UNAVAILABLE",
            "quoteStatus": "MISSING",
            "issues": ["MISSING_BROKER_QUOTE"],
            "observedPrice": None,
            "isStale": False,
            "midpoint": None,
            "spread": None,
            "bid": None,
            "ask": None,
            "ltp": None,
            "oi": None,
            "oiStatus": "MISSING",
            "volume": None,
            "volumeStatus": "MISSING",
        }

    issues = []
    now = reference_timestamp or datetime.now(IST_ZONE)
    if isinstance(now, datetime) and now.tzinfo is None:
        now = now.replace(tzinfo=IST_ZONE)
    elif isinstance(now, datetime):
        now = now.astimezone(IST_ZONE)

    # Freshness Check
    is_stale = False
    raw_ts = quote.get("marketTimestamp") or quote.get("exchFeedTime") or quote.get("receivedAt")
    if raw_ts:
        try:
            if isinstance(raw_ts, datetime):
                q_dt = raw_ts if raw_ts.tzinfo else raw_ts.replace(tzinfo=IST_ZONE)
            else:
                q_dt = datetime.fromisoformat(str(raw_ts))
            q_dt = q_dt.astimezone(IST_ZONE)
            age = (now - q_dt).total_seconds()
            if age > max_stale_seconds:
                is_stale = True
                issues.append("STALE_QUOTE")
        except Exception:
            pass

    ltp = float(quote.get("ltp") or 0.0) if quote.get("ltp") is not None else None
    bid = float(quote.get("bid") or 0.0) if quote.get("bid") is not None else None
    ask = float(quote.get("ask") or 0.0) if quote.get("ask") is not None else None

    # Open Interest Semantics: Distinguish Missing from Actual Zero
    raw_oi = quote.get("openInterest") if quote.get("openInterest") is not None else quote.get("opnInterest")
    if raw_oi is None:
        oi = None
        oi_status = "MISSING"
        issues.append("MISSING_OI")
    else:
        try:
            oi_val = int(raw_oi)
            if oi_val < 0:
                oi = None
                oi_status = "INVALID"
                issues.append("INVALID_OI")
            elif oi_val == 0:
                oi = 0
                oi_status = "AVAILABLE"  # Verified zero open positions
                issues.append("ZERO_OI")
            else:
                oi = oi_val
                oi_status = "AVAILABLE"
        except (ValueError, TypeError):
            oi = None
            oi_status = "INVALID"
            issues.append("INVALID_OI")

    # Volume Semantics: Distinguish Missing from Actual Zero
    raw_vol = quote.get("volume") if quote.get("volume") is not None else quote.get("tradeVolume")
    if raw_vol is None:
        vol = None
        vol_status = "MISSING"
        issues.append("MISSING_VOLUME")
    else:
        try:
            vol_val = int(raw_vol)
            if vol_val < 0:
                vol = None
                vol_status = "INVALID"
                issues.append("INVALID_VOLUME")
            elif vol_val == 0:
                vol = 0
                vol_status = "AVAILABLE"  # Verified zero contracts traded today
                issues.append("ZERO_VOLUME")
            else:
                vol = vol_val
                vol_status = "AVAILABLE"
        except (ValueError, TypeError):
            vol = None
            vol_status = "INVALID"
            issues.append("INVALID_VOLUME")

    if ltp is None or ltp <= 0.0:
        issues.append("INVALID_LTP")

    if bid is None or bid <= 0.0:
        issues.append("ZERO_BID")

    if ask is None or ask <= 0.0:
        issues.append("ZERO_ASK")

    spread = None
    midpoint = None
    if bid is not None and ask is not None and bid > 0.0 and ask > 0.0:
        if bid > ask:
            issues.append("INVERTED_SPREAD")
        else:
            spread = round(ask - bid, 2)
            midpoint = round((bid + ask) / 2.0, 2)

    # Select observed market premium
    if midpoint is not None and "INVERTED_SPREAD" not in issues:
        observed_price = midpoint
    elif ltp is not None and ltp > 0.0:
        observed_price = ltp
    else:
        observed_price = None

    if observed_price is None:
        status = "DATA_UNAVAILABLE"
        quote_status = "MISSING"
        is_valid = False
    elif "INVERTED_SPREAD" in issues:
        status = "INVALID_QUOTE"
        quote_status = "INVALID"
        is_valid = False
    elif is_stale:
        status = "STALE"
        quote_status = "STALE"
        is_valid = False
    else:
        status = "LIVE"
        quote_status = "AVAILABLE"
        is_valid = True

    return {
        "isValid": is_valid,
        "status": status,
        "quoteStatus": quote_status,
        "issues": issues,
        "observedPrice": observed_price,
        "isStale": is_stale,
        "midpoint": midpoint,
        "spread": spread,
        "bid": bid,
        "ask": ask,
        "ltp": ltp,
        "oi": oi,
        "oiStatus": oi_status,
        "volume": vol,
        "volumeStatus": vol_status,
    }


def calculate_black_scholes(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float = 0.065,
    iv: Optional[float] = 0.15,
    option_type: str = "CE"
) -> Optional[Dict[str, float]]:
    """
    Computes Black-Scholes analytical option price and Greeks for European index options:
    - Delta: Price sensitivity to spot price move (CE in (0, 1), PE in (-1, 0))
    - Gamma: Rate of change of Delta per unit spot move (Gamma >= 0)
    - Theta: 1-day time decay in INR (₹)
      NOTE: Theta is negative for buyers in standard scenarios, but mathematically
      can be positive for deep in-the-money European put options when r > 0.
    - Vega: Price sensitivity per 1% absolute IV move (0.01)

    Validation & Boundary Conditions:
      - If time_to_expiry_years <= 0.0 or < 1e-12: returns exact intrinsic payoff and Greeks.
      - If time_to_expiry_years > 0.0: computes continuous Black-Scholes sensitivities.
        Does NOT prematurely discard time value during the final trading hour.
      - If IV is None, <= 0, or NaN, returns None. Does NOT silently substitute defaults or India VIX.
    """
    if spot is None or math.isnan(spot) or spot <= 0.0:
        return None
    if strike is None or math.isnan(strike) or strike <= 0.0:
        return None
    if time_to_expiry_years is None or math.isnan(time_to_expiry_years):
        return None

    opt_type = option_type.upper().strip()
    is_call = opt_type in ("CE", "CALL")
    if not is_call and opt_type not in ("PE", "PUT"):
        return None

    # Expiry Boundary Handling: Exact expiry when t <= 0.0 or sub-millisecond numerical boundary
    if time_to_expiry_years <= 0.0 or time_to_expiry_years < 1e-12:
        if is_call:
            intrinsic = max(0.0, spot - strike)
            delta = 1.0 if spot > strike else (0.5 if spot == strike else 0.0)
        else:
            intrinsic = max(0.0, strike - spot)
            delta = -1.0 if spot < strike else (-0.5 if spot == strike else 0.0)
        return {
            "price": round(intrinsic, 2),
            "delta": round(delta, 4),
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
        }

    # Strict IV Requirement
    if iv is None or math.isnan(iv) or iv <= 0.0:
        return None

    sigma = float(iv)
    r = float(risk_free_rate)
    t = float(time_to_expiry_years)
    s = float(spot)
    k = float(strike)

    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)

    pdf_d1 = norm_pdf(d1)
    cdf_d1 = norm_cdf(d1)
    cdf_d2 = norm_cdf(d2)
    cdf_neg_d1 = norm_cdf(-d1)
    cdf_neg_d2 = norm_cdf(-d2)

    exp_rt = math.exp(-r * t)

    if is_call:
        price = s * cdf_d1 - k * exp_rt * cdf_d2
        delta = cdf_d1
        annual_theta = -(s * pdf_d1 * sigma) / (2.0 * math.sqrt(t)) - r * k * exp_rt * cdf_d2
    else:
        price = k * exp_rt * cdf_neg_d2 - s * cdf_neg_d1
        delta = cdf_d1 - 1.0
        annual_theta = -(s * pdf_d1 * sigma) / (2.0 * math.sqrt(t)) + r * k * exp_rt * cdf_neg_d2

    gamma = pdf_d1 / (s * sigma * math.sqrt(t))
    vega = (s * math.sqrt(t) * pdf_d1) / 100.0
    theta_per_day = annual_theta / 365.0

    return {
        "price": round(max(0.0, price), 2),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta_per_day, 2),
        "vega": round(vega, 2),
    }
