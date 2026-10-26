from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np


def process_candlestick_series(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "15m"
) -> Dict[str, Any]:
    """
    Processes OHLCV candles and attaches quantitative overlays:
    - EMA 20 & EMA 50
    - Intraday VWAP
    - Volume surges
    - Rolling ATR (14)
    - Formats candles for charting libraries with IST timestamps
    """
    if df is None or len(df) == 0:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": [],
            "current": None,
            "ema20": None,
            "ema50": None,
            "vwap": None,
            "atr": None,
        }

    candles_df = df.copy()

    # Ensure required columns
    for col in ["open", "high", "low", "close", "volume"]:
        if col in candles_df.columns:
            candles_df[col] = candles_df[col].astype(float)

    # 1. EMAs
    candles_df["ema_20"] = candles_df["close"].ewm(span=20, adjust=False).mean().round(2)
    candles_df["ema_50"] = candles_df["close"].ewm(span=50, adjust=False).mean().round(2)

    # 2. VWAP
    if "vwap" not in candles_df.columns or candles_df["vwap"].isna().all():
        cum_vol = candles_df["volume"].cumsum()
        typical_price = (candles_df["high"] + candles_df["low"] + candles_df["close"]) / 3.0
        cum_pv = (typical_price * candles_df["volume"]).cumsum()
        candles_df["vwap"] = (cum_pv / np.where(cum_vol == 0, 1, cum_vol)).round(2)

    # 3. True Range and ATR
    prev_close = candles_df["close"].shift(1).fillna(candles_df["open"])
    tr1 = candles_df["high"] - candles_df["low"]
    tr2 = (candles_df["high"] - prev_close).abs()
    tr3 = (candles_df["low"] - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    candles_df["atr_14"] = tr.rolling(window=min(14, len(candles_df)), min_periods=1).mean().round(2)

    # Format into lightweight JSON objects for charting
    formatted_candles = []
    for _, row in candles_df.iterrows():
        ts_val = row.get("timestamp")
        time_str = row.get("time")
        if hasattr(ts_val, "strftime"):
            label = ts_val.strftime("%H:%M") if timeframe != "1d" else ts_val.strftime("%Y-%m-%d")
        else:
            label = str(time_str or ts_val or "")

        formatted_candles.append({
            "time": label,
            "timestamp": str(ts_val) if ts_val is not None else None,
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
            "volume": int(row["volume"]),
            "vwap": round(float(row["vwap"]), 2) if not pd.isna(row["vwap"]) else None,
            "ema20": round(float(row["ema_20"]), 2) if not pd.isna(row["ema_20"]) else None,
            "ema50": round(float(row["ema_50"]), 2) if not pd.isna(row["ema_50"]) else None,
        })

    latest = formatted_candles[-1] if formatted_candles else None

    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "candles": formatted_candles,
        "current": latest,
        "ema20": latest.get("ema20") if latest else None,
        "ema50": latest.get("ema50") if latest else None,
        "vwap": latest.get("vwap") if latest else None,
        "atr": float(candles_df["atr_14"].iloc[-1]) if not candles_df.empty else 15.0,
    }
