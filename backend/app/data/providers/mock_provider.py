import math
import random
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from app.data.providers.base import MarketDataProvider
from app.data.market_calendar import MarketCalendar

MOCK_UNIVERSE = {
    "NIFTY 50": {
        "companyName": "Nifty 50 Index",
        "basePrice": 24852.40,
        "exchange": "NSE",
        "sector": "Benchmark Index",
        "category": "Index",
        "trend": "Bullish",
        "volatility": 0.012,
    },
    "NIFTY": {
        "companyName": "Nifty 50 Index",
        "basePrice": 24852.40,
        "exchange": "NSE",
        "sector": "Benchmark Index",
        "category": "Index",
        "trend": "Bullish",
        "volatility": 0.012,
    },
    "SENSEX": {
        "companyName": "BSE SENSEX Index",
        "basePrice": 81850.50,
        "exchange": "BSE",
        "sector": "Benchmark Index",
        "category": "Index",
        "trend": "Bullish",
        "volatility": 0.011,
    },
    "BSE SENSEX": {
        "companyName": "BSE SENSEX Index",
        "basePrice": 81850.50,
        "exchange": "BSE",
        "sector": "Benchmark Index",
        "category": "Index",
        "trend": "Bullish",
        "volatility": 0.011,
    },
    "BANK NIFTY": {
        "companyName": "Nifty Bank Index",
        "basePrice": 51420.80,
        "exchange": "NSE",
        "sector": "Banking Index",
        "category": "Index",
        "trend": "Bullish",
        "volatility": 0.015,
    },
    "BANKNIFTY": {
        "companyName": "Nifty Bank Index",
        "basePrice": 51420.80,
        "exchange": "NSE",
        "sector": "Banking Index",
        "category": "Index",
        "trend": "Bullish",
        "volatility": 0.015,
    },
    "INDIA VIX": {
        "companyName": "India Volatility Index",
        "basePrice": 13.42,
        "exchange": "NSE",
        "sector": "Volatility Index",
        "category": "Index",
        "trend": "Bearish",
        "volatility": 0.035,
    },
    "RELIANCE": {
        "companyName": "Reliance Industries Limited",
        "basePrice": 1456.80,
        "exchange": "NSE",
        "sector": "Energy & Conglomerates",
        "category": "Large Cap",
        "trend": "Bullish",
        "volatility": 0.016,
    },
    "TCS": {
        "companyName": "Tata Consultancy Services Limited",
        "basePrice": 4235.50,
        "exchange": "NSE",
        "sector": "IT",
        "category": "Large Cap",
        "trend": "Bullish",
        "volatility": 0.014,
    },
    "INFY": {
        "companyName": "Infosys Limited",
        "basePrice": 1845.20,
        "exchange": "NSE",
        "sector": "IT",
        "category": "Large Cap",
        "trend": "Bearish",
        "volatility": 0.018,
    },
    "SBIN": {
        "companyName": "State Bank of India",
        "basePrice": 815.40,
        "exchange": "NSE",
        "sector": "Banking",
        "category": "Large Cap",
        "trend": "Bullish",
        "volatility": 0.019,
    },
    "LT": {
        "companyName": "Larsen & Toubro Limited",
        "basePrice": 3620.00,
        "exchange": "NSE",
        "sector": "Infrastructure",
        "category": "Large Cap",
        "trend": "Bullish",
        "volatility": 0.015,
    },
    "HDFCBANK": {
        "companyName": "HDFC Bank Limited",
        "basePrice": 1642.30,
        "exchange": "NSE",
        "sector": "Banking",
        "category": "Large Cap",
        "trend": "Bullish",
        "volatility": 0.013,
    },
    "ICICIBANK": {
        "companyName": "ICICI Bank Limited",
        "basePrice": 1218.60,
        "exchange": "NSE",
        "sector": "Banking",
        "category": "Large Cap",
        "trend": "Bullish",
        "volatility": 0.015,
    },
    "AXISBANK": {
        "companyName": "Axis Bank Limited",
        "basePrice": 1175.40,
        "exchange": "NSE",
        "sector": "Banking",
        "category": "Large Cap",
        "trend": "Neutral",
        "volatility": 0.017,
    },
    "MARUTI": {
        "companyName": "Maruti Suzuki India Limited",
        "basePrice": 12150.00,
        "exchange": "NSE",
        "sector": "Auto",
        "category": "Large Cap",
        "trend": "Bearish",
        "volatility": 0.016,
    },
    "ITC": {
        "companyName": "ITC Limited",
        "basePrice": 502.10,
        "exchange": "NSE",
        "sector": "FMCG",
        "category": "Large Cap",
        "trend": "Neutral",
        "volatility": 0.011,
    },
    "SUNPHARMA": {
        "companyName": "Sun Pharmaceutical Industries Limited",
        "basePrice": 1820.75,
        "exchange": "NSE",
        "sector": "Pharma",
        "category": "Large Cap",
        "trend": "Bearish",
        "volatility": 0.015,
    },
    "BHARTIARTL": {
        "companyName": "Bharti Airtel Limited",
        "basePrice": 1548.00,
        "exchange": "NSE",
        "sector": "Telecom",
        "category": "Large Cap",
        "trend": "Bullish",
        "volatility": 0.014,
    },
    "ADANIENT": {
        "companyName": "Adani Enterprises Limited",
        "basePrice": 2980.50,
        "exchange": "NSE",
        "sector": "Metals",
        "category": "Large Cap",
        "trend": "Neutral",
        "volatility": 0.024,
    },
    "M&M": {
        "companyName": "Mahindra & Mahindra Limited",
        "basePrice": 2780.00,
        "exchange": "NSE",
        "sector": "Auto",
        "category": "Large Cap",
        "trend": "Bullish",
        "volatility": 0.018,
    },
    "KOTAKBANK": {
        "companyName": "Kotak Mahindra Bank Limited",
        "basePrice": 1785.60,
        "exchange": "NSE",
        "sector": "Banking",
        "category": "Large Cap",
        "trend": "Neutral",
        "volatility": 0.014,
    },
}


class MockMarketDataProvider(MarketDataProvider):
    """
    Deterministic realistic mock provider for Indian markets.
    Generates mathematically consistent OHLCV data, indicators, and indices.
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)
        np.random.seed(seed)

    def get_provider_name(self) -> str:
        return "mock"

    def _get_stock_info(self, symbol: str) -> Dict[str, Any]:
        sym = symbol.upper().replace("_", " ").strip()
        if "NIFTY 50" in sym or sym == "NIFTY":
            return {
                "companyName": "Nifty 50 Index",
                "basePrice": 24852.40,
                "exchange": "NSE",
                "sector": "Benchmark Index",
                "category": "Index",
                "trend": "Bullish",
                "volatility": 0.012,
            }
        if "SENSEX" in sym:
            return {
                "companyName": "BSE SENSEX Index",
                "basePrice": 81850.50,
                "exchange": "BSE",
                "sector": "Benchmark Index",
                "category": "Index",
                "trend": "Bullish",
                "volatility": 0.011,
            }
        if "BANK" in sym:
            return {
                "companyName": "Nifty Bank Index",
                "basePrice": 51420.80,
                "exchange": "NSE",
                "sector": "Sectoral Index",
                "category": "Index",
                "trend": "Bullish",
                "volatility": 0.015,
            }

        if sym in MOCK_UNIVERSE:
            return MOCK_UNIVERSE[sym]
        # Fallback for unknown symbols
        return {
            "companyName": f"{sym} India Limited",
            "basePrice": 1000.0,
            "exchange": "NSE",
            "sector": "Diversified",
            "category": "Mid Cap",
            "trend": "Neutral",
            "volatility": 0.018,
        }

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        info = self._get_stock_info(symbol)
        base = info["basePrice"]
        trend = info["trend"]

        # Deterministic variation based on symbol chars
        sym_hash = sum(ord(c) for c in symbol)
        drift = 0.008 if trend == "Bullish" else (-0.008 if trend == "Bearish" else 0.001)
        current_price = round(base * (1 + drift), 2)
        change = round(current_price - base, 2)
        change_pct = round((change / base) * 100, 2)

        day_high = round(max(current_price, base) * 1.008, 2)
        day_low = round(min(current_price, base) * 0.992, 2)
        open_price = round(base * 0.998, 2)
        volume = int(1200000 + (sym_hash * 10000) % 2500000)
        vwap = round((open_price + day_high + day_low + current_price) / 4, 2)

        return {
            "symbol": symbol.upper(),
            "companyName": info["companyName"],
            "exchange": info["exchange"],
            "sector": info["sector"],
            "category": info["category"],
            "currentPrice": current_price,
            "change": change,
            "changePercent": change_pct,
            "openPrice": open_price,
            "dayHigh": day_high,
            "dayLow": day_low,
            "previousClose": base,
            "volume": volume,
            "vwap": vwap,
            "timestamp": MarketCalendar.format_ist_timestamp(),
            "dataStatus": "MOCK",
        }

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        from_date: datetime,
        to_date: datetime
    ) -> pd.DataFrame:
        """
        Generate synthetic historical daily/hourly candles with realistic trend & noise.
        """
        info = self._get_stock_info(symbol)
        base = info["basePrice"]
        trend_mult = 1.0006 if info["trend"] == "Bullish" else (0.9994 if info["trend"] == "Bearish" else 1.0)
        vol = info["volatility"]

        # Calculate number of trading days
        days = max(1, (to_date - from_date).days)
        records = []

        curr_close = base * (0.85 if info["trend"] == "Bullish" else 1.15)
        # Seed generator based on symbol for consistency across calls
        rng = np.random.RandomState(sum(ord(c) for c in symbol))

        current_dt = from_date
        while current_dt <= to_date:
            if current_dt.weekday() < 5:  # Mon-Fri
                pct_return = rng.normal(loc=0.0003, scale=vol) * (1 if info["trend"] == "Bullish" else -0.8)
                curr_close = curr_close * (1 + pct_return)
                open_p = curr_close * (1 + rng.normal(0, vol * 0.3))
                high_p = max(open_p, curr_close) * (1 + abs(rng.normal(0, vol * 0.5)))
                low_p = min(open_p, curr_close) * (1 - abs(rng.normal(0, vol * 0.5)))
                volume = int(rng.uniform(800000, 3500000))
                vwap = round((open_p + high_p + low_p + curr_close) / 4, 2)

                records.append({
                    "timestamp": current_dt,
                    "open": round(open_p, 2),
                    "high": round(high_p, 2),
                    "low": round(low_p, 2),
                    "close": round(curr_close, 2),
                    "volume": volume,
                    "vwap": vwap,
                })
            current_dt += timedelta(days=1)

        df = pd.DataFrame(records)
        return df

    async def get_intraday_candles(
        self,
        symbol: str,
        timeframe: str = "15m"
    ) -> pd.DataFrame:
        info = self._get_stock_info(symbol)
        base = info["basePrice"]
        trend = info["trend"]

        # 26 15-min intervals between 09:15 and 15:30
        now = MarketCalendar.now_ist()
        start_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
        records = []
        curr = base * 0.995

        rng = np.random.RandomState(sum(ord(c) for c in symbol) + 99)
        step_drift = 0.0008 if trend == "Bullish" else (-0.0008 if trend == "Bearish" else 0.0)

        cum_vol = 0
        cum_pv = 0.0

        for i in range(26):
            bar_time = start_time + timedelta(minutes=15 * i)
            delta = rng.normal(loc=step_drift, scale=0.003) * curr
            open_p = curr
            close_p = round(curr + delta, 2)
            high_p = round(max(open_p, close_p) * (1 + abs(rng.normal(0, 0.0015))), 2)
            low_p = round(min(open_p, close_p) * (1 - abs(rng.normal(0, 0.0015))), 2)
            volume = int(rng.uniform(30000, 150000))

            typical_price = (high_p + low_p + close_p) / 3
            cum_vol += volume
            cum_pv += typical_price * volume
            vwap = round(cum_pv / cum_vol, 2) if cum_vol > 0 else close_p

            records.append({
                "timestamp": bar_time,
                "time": bar_time.strftime("%H:%M"),
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": volume,
                "vwap": vwap,
            })
            curr = close_p

        return pd.DataFrame(records)

    async def get_index_quote(self, index_symbol: str) -> Dict[str, Any]:
        indices = await self.get_all_indices()
        for idx in indices:
            if idx["symbol"].upper() == index_symbol.upper():
                return idx
        return indices[0]

    async def get_all_indices(self) -> List[Dict[str, Any]]:
        return [
            {
                "symbol": "NIFTY 50",
                "name": "Nifty 50 Index",
                "currentValue": 24852.40,
                "change": 136.20,
                "changePercent": 0.55,
                "dayHigh": 24890.10,
                "dayLow": 24710.80,
                "trend": "Bullish",
                "sparkline": [24715, 24730, 24760, 24745, 24790, 24810, 24840, 24852.4],
                "volatilityStatus": "Moderate",
            },
            {
                "symbol": "SENSEX",
                "name": "BSE SENSEX Index",
                "currentValue": 81850.50,
                "change": 420.30,
                "changePercent": 0.52,
                "dayHigh": 82010.20,
                "dayLow": 81430.00,
                "trend": "Bullish",
                "sparkline": [81450, 81520, 81640, 81600, 81730, 81790, 81820, 81850.5],
                "volatilityStatus": "Moderate",
            },
            {
                "symbol": "BANK NIFTY",
                "name": "Nifty Bank Index",
                "currentValue": 51420.80,
                "change": 312.40,
                "changePercent": 0.61,
                "dayHigh": 51550.00,
                "dayLow": 51080.00,
                "trend": "Bullish",
                "sparkline": [51100, 51180, 51240, 51210, 51330, 51380, 51410, 51420.8],
                "volatilityStatus": "Moderate",
            },
            {
                "symbol": "INDIA VIX",
                "name": "India Volatility Index",
                "currentValue": 13.42,
                "change": -0.54,
                "changePercent": -3.85,
                "dayHigh": 14.15,
                "dayLow": 13.20,
                "trend": "Bearish",  # Volatility dropping is equity bullish
                "sparkline": [14.10, 13.95, 13.80, 13.70, 13.60, 13.50, 13.45, 13.42],
                "volatilityStatus": "Moderate",
            },
            {
                "symbol": "FINNIFTY",
                "name": "Nifty Financial Services",
                "currentValue": 23910.15,
                "change": 122.30,
                "changePercent": 0.51,
                "dayHigh": 23980.50,
                "dayLow": 23760.00,
                "trend": "Bullish",
                "sparkline": [23780, 23810, 23850, 23830, 23890, 23900, 23920, 23910.15],
                "volatilityStatus": "Moderate",
            },
        ]

    async def get_sector_data(self) -> List[Dict[str, Any]]:
        return [
            {"sector": "IT", "performancePercent": 1.42, "strength": "Strong", "topStock": "TCS (+1.49%)", "advancers": 8, "decliners": 2},
            {"sector": "Energy", "performancePercent": 1.10, "strength": "Strong", "topStock": "RELIANCE (+1.24%)", "advancers": 7, "decliners": 3},
            {"sector": "Banking", "performancePercent": 0.98, "strength": "Strong", "topStock": "SBIN (+1.38%)", "advancers": 9, "decliners": 3},
            {"sector": "Financial Services", "performancePercent": 0.85, "strength": "Moderate", "topStock": "BAJFINANCE (+1.15%)", "advancers": 14, "decliners": 6},
            {"sector": "Metals", "performancePercent": 0.75, "strength": "Moderate", "topStock": "TATASTEEL (+1.05%)", "advancers": 10, "decliners": 5},
            {"sector": "Auto", "performancePercent": 0.65, "strength": "Moderate", "topStock": "M&M (+1.82%)", "advancers": 9, "decliners": 6},
            {"sector": "FMCG", "performancePercent": 0.12, "strength": "Moderate", "topStock": "ITC (+0.45%)", "advancers": 8, "decliners": 7},
            {"sector": "Realty", "performancePercent": -0.30, "strength": "Negative", "topStock": "DLF (-0.75%)", "advancers": 4, "decliners": 6},
            {"sector": "Pharma", "performancePercent": -0.45, "strength": "Weak", "topStock": "SUNPHARMA (-0.88%)", "advancers": 5, "decliners": 10},
        ]

    async def get_market_breadth(self) -> Dict[str, Any]:
        return {
            "advancing": 1482,
            "declining": 746,
            "unchanged": 104,
            "ratio": 1.99,
        }

    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None
    ) -> Dict[str, Any]:
        quote = await self.get_quote(symbol)
        ltp = quote["currentPrice"]
        strike_step = 20.0 if ltp > 1000 else 10.0
        atm_strike = round(ltp / strike_step) * strike_step

        strikes = []
        for i in range(-5, 6):
            strike = atm_strike + (i * strike_step)
            ce_oi = int(150000 + abs(strike - ltp) * 200 + random.randint(10000, 50000))
            pe_oi = int(160000 + abs(strike - ltp) * 180 + random.randint(10000, 50000))
            strikes.append({
                "strike": strike,
                "ce": {
                    "ltp": round(max(0.5, (ltp - strike) + 15), 2),
                    "oi": ce_oi,
                    "changeInOi": random.randint(-5000, 15000),
                    "iv": 14.5,
                },
                "pe": {
                    "ltp": round(max(0.5, (strike - ltp) + 15), 2),
                    "oi": pe_oi,
                    "changeInOi": random.randint(-5000, 15000),
                    "iv": 15.2,
                }
            })

        return {
            "symbol": symbol,
            "underlyingLtp": ltp,
            "expiry": expiry or "Current Week",
            "strikes": strikes,
        }
