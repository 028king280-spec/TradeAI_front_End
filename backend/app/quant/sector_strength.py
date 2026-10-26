from typing import Dict, Any, List


# Default Institutional Sector Map
STOCK_SECTOR_MAP: Dict[str, str] = {
    "RELIANCE": "NIFTY ENERGY",
    "TCS": "NIFTY IT",
    "INFY": "NIFTY IT",
    "WIPRO": "NIFTY IT",
    "HCLTECH": "NIFTY IT",
    "HDFCBANK": "NIFTY BANK",
    "ICICIBANK": "NIFTY BANK",
    "SBIN": "NIFTY BANK",
    "KOTAKBANK": "NIFTY BANK",
    "AXISBANK": "NIFTY BANK",
    "BHARTIARTL": "NIFTY TELECOM",
    "ITC": "NIFTY FMCG",
    "TATAMOTORS": "NIFTY AUTO",
    "MARUTI": "NIFTY AUTO",
    "SUNPHARMA": "NIFTY PHARMA",
    "TITAN": "NIFTY CONSUMPTION",
    "LT": "NIFTY INFRA",
    "BAJFINANCE": "NIFTY FIN SERVICE",
    "TATASTEEL": "NIFTY METAL",
    "NTPC": "NIFTY ENERGY",
}


class SectorStrengthEngine:
    """
    Sector Relative Strength Engine:
    - Identifies stock's primary economic sector
    - Computes Sector Return, Momentum, and Trend
    - Measures Alpha: Stock Relative Strength vs Sector
    - Returns sector_bias, relative_strength, sector_score (0 to 10 points)
    """

    @classmethod
    def evaluate_sector(
        cls,
        symbol: str,
        stock_change_percent: float,
        sector_heatmap: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        clean_sym = symbol.upper().strip()
        sector_name = STOCK_SECTOR_MAP.get(clean_sym, "NIFTY 50")

        # Find sector data
        sec_item = next(
            (s for s in sector_heatmap if s.get("sector", "").upper() == sector_name.upper()),
            None
        )

        sec_perf = sec_item.get("performancePercent", 0.45) if sec_item else 0.45
        sec_trend = "Bullish" if sec_perf > 0 else "Bearish" if sec_perf < 0 else "Neutral"

        # Alpha relative strength
        alpha = round(stock_change_percent - sec_perf, 2)
        if alpha >= 0.8:
            rel_strength = "Strong"
            rel_text = f"Outperforming sector by +{alpha}%. Strong institutional alpha."
            sector_score = 10
        elif alpha >= 0.1:
            rel_strength = "Moderate"
            rel_text = f"Mild outperformance (+{alpha}%) relative to sectoral peers."
            sector_score = 8
        elif alpha <= -0.8:
            rel_strength = "Lagging"
            rel_text = f"Lagging sector by {alpha}%. Relative weakness detected."
            sector_score = 3
        else:
            rel_strength = "Neutral"
            rel_text = f"Tracking sector benchmark closely ({alpha}% diff)."
            sector_score = 6

        sector_bias = "BULLISH" if sec_perf >= 0.3 else "BEARISH" if sec_perf <= -0.3 else "NEUTRAL"

        return {
            "sectorName": sector_name,
            "sectorPerformance": sec_perf,
            "sectorTrend": sec_trend,
            "sector_bias": sector_bias,
            "relative_strength": rel_strength,
            "stockVsSector": rel_text,
            "alpha": alpha,
            "sector_score": sector_score,  # 0 to 10 for multi-factor scoring
        }
