import math
from typing import Dict, Any, Optional


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def calculate_black_scholes(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float = 0.065,  # Indian benchmark ~6.5%
    iv: float = 0.15,               # e.g. 15% annualised IV
    option_type: str = "CE"
) -> Dict[str, float]:
    """
    Computes Black-Scholes analytical option price and Greeks for European index options:
    - Delta: Price sensitivity to spot price move
    - Gamma: Rate of change of Delta per unit spot move
    - Theta: 1-day time decay in INR (₹)
    - Vega: Price sensitivity per 1% absolute IV move (0.01)
    """
    opt_type = option_type.upper().strip()
    if time_to_expiry_years <= 0.0001:
        # Near/at expiry boundary
        intrinsic = max(0.0, spot - strike) if opt_type in ("CE", "CALL") else max(0.0, strike - spot)
        delta = 1.0 if (opt_type in ("CE", "CALL") and spot > strike) else (-1.0 if (opt_type in ("PE", "PUT") and spot < strike) else 0.0)
        return {
            "price": round(intrinsic, 2),
            "delta": round(delta, 4),
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
        }

    sigma = max(0.01, iv)
    r = risk_free_rate
    t = time_to_expiry_years
    s = max(1.0, spot)
    k = max(1.0, strike)

    d1 = (math.log(s / k) + (r + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)

    pdf_d1 = norm_pdf(d1)
    cdf_d1 = norm_cdf(d1)
    cdf_d2 = norm_cdf(d2)
    cdf_neg_d1 = norm_cdf(-d1)
    cdf_neg_d2 = norm_cdf(-d2)

    exp_rt = math.exp(-r * t)

    if opt_type in ("CE", "CALL"):
        price = s * cdf_d1 - k * exp_rt * cdf_d2
        delta = cdf_d1
        # Theta per day (annual theta / 365)
        annual_theta = -(s * pdf_d1 * sigma) / (2.0 * math.sqrt(t)) - r * k * exp_rt * cdf_d2
    else:
        price = k * exp_rt * cdf_neg_d2 - s * cdf_neg_d1
        delta = cdf_d1 - 1.0
        annual_theta = -(s * pdf_d1 * sigma) / (2.0 * math.sqrt(t)) + r * k * exp_rt * cdf_neg_d2

    gamma = pdf_d1 / (s * sigma * math.sqrt(t))
    # Vega per 1 percentage point IV move (0.01)
    vega = (s * math.sqrt(t) * pdf_d1) / 100.0
    theta_per_day = annual_theta / 365.0

    return {
        "price": round(max(0.05, price), 2),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta_per_day, 2),
        "vega": round(vega, 2),
    }
