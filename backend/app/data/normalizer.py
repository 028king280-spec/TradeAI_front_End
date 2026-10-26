from typing import Dict, Any, Optional
from datetime import datetime, timezone


class MarketDataNormalizer:
    """
    Standardizes raw quotes, ticks and candles into common internal AIVOLVE format.
    The frontend and quant engine NEVER depend directly on Upstox's or any broker's raw schema.
    """

    @staticmethod
    def normalize_quote(
        symbol: str,
        exchange: str,
        instrument_key: str,
        ltp: float,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        timestamp: Optional[str] = None,
        vwap: Optional[float] = None,
        change: Optional[float] = None,
        change_percent: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Produce common internal format:
        {
          "symbol": "RELIANCE",
          "exchange": "NSE",
          "instrument_key": "NSE_EQ|INE002A01018",
          "ltp": 1456.80,
          "open": 1448.00,
          "high": 1462.50,
          "low": 1442.20,
          "close": 1438.90,
          "volume": 1234567,
          "timestamp": "..."
        }
        """
        c = float(close) if close else float(ltp)
        cur_ltp = float(ltp)
        
        calc_change = change if change is not None else round(cur_ltp - c, 2)
        calc_change_pct = (
            change_percent
            if change_percent is not None
            else round((calc_change / c * 100) if c else 0.0, 2)
        )
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        calc_vwap = vwap if vwap is not None else round((open_price + high + low + cur_ltp) / 4, 2)

        return {
            "symbol": symbol.upper(),
            "companyName": f"{symbol.upper()} Limited",
            "exchange": exchange.upper(),
            "instrument_key": instrument_key,
            "ltp": round(cur_ltp, 2),
            "currentPrice": round(cur_ltp, 2),
            "open": round(float(open_price), 2),
            "openPrice": round(float(open_price), 2),
            "high": round(float(high), 2),
            "dayHigh": round(float(high), 2),
            "low": round(float(low), 2),
            "dayLow": round(float(low), 2),
            "close": round(c, 2),
            "previousClose": round(c, 2),
            "volume": int(volume),
            "vwap": round(calc_vwap, 2),
            "change": round(calc_change, 2),
            "changePercent": round(calc_change_pct, 2),
            "timestamp": ts,
        }

    @staticmethod
    def normalize_upstox_quote(symbol: str, raw_quote: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parses Upstox Market-Quote v2 response.
        Example raw structure:
        {
          "instrument_token": "NSE_EQ|INE002A01018",
          "last_price": 1456.80,
          "volume": 1234567,
          "average_price": 1452.40,
          "ohlc": { "open": 1448.0, "high": 1462.5, "low": 1442.2, "close": 1438.9 },
          "net_change": 17.9
        }
        """
        instrument_key = raw_quote.get("instrument_token") or raw_quote.get("instrument_key", f"NSE_EQ|{symbol}")
        ohlc = raw_quote.get("ohlc", {})
        ltp = float(raw_quote.get("last_price", 0.0))
        open_price = float(ohlc.get("open", ltp))
        high = float(ohlc.get("high", max(open_price, ltp)))
        low = float(ohlc.get("low", min(open_price, ltp)))
        close = float(ohlc.get("close", ltp))
        volume = float(raw_quote.get("volume", 0))
        vwap = float(raw_quote.get("average_price", (open_price + high + low + close) / 4))
        change = float(raw_quote.get("net_change", ltp - close))
        change_pct = round((change / close * 100) if close else 0.0, 2)
        ts = raw_quote.get("timestamp") or datetime.now(timezone.utc).isoformat()

        parts = instrument_key.split("|")
        exchange = parts[0].replace("_EQ", "").replace("_INDEX", "") if len(parts) > 1 else "NSE"

        return MarketDataNormalizer.normalize_quote(
            symbol=symbol,
            exchange=exchange,
            instrument_key=instrument_key,
            ltp=ltp,
            open_price=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            timestamp=ts,
            vwap=vwap,
            change=change,
            change_percent=change_pct,
        )
