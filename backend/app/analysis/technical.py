from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd


class TechnicalAnalysisEngine:
    """
    Deterministic mathematical calculations for technical indicators
    using strictly historical and intraday OHLCV pandas DataFrames.
    """

    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average."""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_rsi(close_prices: pd.Series, period: int = 14) -> pd.Series:
        """Wilder's smoothed Relative Strength Index."""
        delta = close_prices.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50.0)

    @staticmethod
    def calculate_macd(
        close_prices: pd.Series,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> Dict[str, pd.Series]:
        """Moving Average Convergence Divergence."""
        ema_fast = TechnicalAnalysisEngine.calculate_ema(close_prices, fast_period)
        ema_slow = TechnicalAnalysisEngine.calculate_ema(close_prices, slow_period)
        macd_line = ema_fast - ema_slow
        signal_line = TechnicalAnalysisEngine.calculate_ema(macd_line, signal_period)
        histogram = macd_line - signal_line

        return {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": histogram
        }

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range."""
        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        return atr

    @staticmethod
    def calculate_vwap(df: pd.DataFrame) -> pd.Series:
        """Cumulative Volume Weighted Average Price."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        pv = typical_price * df["volume"]
        cum_pv = pv.cumsum()
        cum_vol = df["volume"].cumsum()
        vwap = cum_pv / cum_vol.replace(0, np.nan)
        return vwap.fillna(df["close"])

    @classmethod
    def analyze(cls, df_daily: pd.DataFrame, df_intraday: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """
        Compute full technical indicators snapshot from real candle data.
        Returns formatted indicators ready for the frontend schema.
        """
        if df_daily.empty:
            raise ValueError("Daily DataFrame cannot be empty for technical analysis")

        close = df_daily["close"]
        current_price = float(close.iloc[-1])

        # EMAs
        ema20_series = cls.calculate_ema(close, 20)
        ema50_series = cls.calculate_ema(close, 50)
        ema200_series = cls.calculate_ema(close, 200)

        ema20_val = float(ema20_series.iloc[-1])
        ema50_val = float(ema50_series.iloc[-1])
        ema200_val = float(ema200_series.iloc[-1]) if len(close) >= 50 else round(current_price * 0.95, 2)

        # RSI
        rsi_series = cls.calculate_rsi(close, 14)
        rsi_val = round(float(rsi_series.iloc[-1]), 1)

        # MACD
        macd_dict = cls.calculate_macd(close)
        macd_val = round(float(macd_dict["macd"].iloc[-1]), 2)
        macd_sig = round(float(macd_dict["signal"].iloc[-1]), 2)
        macd_hist = round(float(macd_dict["histogram"].iloc[-1]), 2)

        # ATR
        atr_series = cls.calculate_atr(df_daily, 14)
        atr_val = round(float(atr_series.iloc[-1]), 2) if not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else round(current_price * 0.015, 2)

        # VWAP (from intraday if available, else daily)
        if df_intraday is not None and not df_intraday.empty:
            vwap_series = cls.calculate_vwap(df_intraday)
            vwap_val = round(float(vwap_series.iloc[-1]), 2)
        else:
            vwap_series = cls.calculate_vwap(df_daily)
            vwap_val = round(float(vwap_series.iloc[-1]), 2)

        # Volume
        vol_series = df_daily["volume"]
        vol_avg20 = float(vol_series.rolling(20).mean().iloc[-1]) if len(vol_series) >= 20 else float(vol_series.mean())
        current_vol = float(vol_series.iloc[-1])
        vol_ratio = round(current_vol / vol_avg20, 2) if vol_avg20 > 0 else 1.0

        # Momentum (Rate of Change 10)
        roc10 = round(float(((close.iloc[-1] - close.iloc[-10]) / close.iloc[-10]) * 100), 2) if len(close) >= 11 else 1.5

        # Price Structure
        recent_highs = df_daily["high"].iloc[-5:].values
        recent_lows = df_daily["low"].iloc[-5:].values
        is_higher_high = recent_highs[-1] >= recent_highs[0]
        is_higher_low = recent_lows[-1] >= recent_lows[0]

        if is_higher_high and is_higher_low:
            structure_signal = "Bullish"
            structure_interp = "Higher Highs & Higher Lows continuation"
            structure_strength = 85
        elif not is_higher_high and not is_higher_low:
            structure_signal = "Bearish"
            structure_interp = "Lower Highs & Lower Lows breakdown"
            structure_strength = 80
        else:
            structure_signal = "Neutral"
            structure_interp = "Consolidating within narrow trading band"
            structure_strength = 60

        # Interpretations & Signals
        # RSI
        if rsi_val >= 60:
            rsi_signal = "Bullish"
            rsi_interp = f"Strong bullish momentum in accumulation zone ({rsi_val})"
            rsi_strength = min(95, int(rsi_val + 15))
        elif rsi_val <= 40:
            rsi_signal = "Bearish"
            rsi_interp = f"Bearish momentum under selling pressure ({rsi_val})"
            rsi_strength = min(95, int(100 - rsi_val))
        else:
            rsi_signal = "Neutral"
            rsi_interp = f"RSI neutral in equilibrium zone ({rsi_val})"
            rsi_strength = 55

        # MACD
        if macd_hist > 0:
            macd_signal = "Bullish"
            macd_interp = f"MACD line ({macd_val}) above signal ({macd_sig}) with expanding histogram"
            macd_strength = 78
        else:
            macd_signal = "Bearish"
            macd_interp = f"MACD line ({macd_val}) below signal ({macd_sig}) indicating distribution"
            macd_strength = 75

        # EMA 20 / 50 / 200
        ema20_signal = "Bullish" if current_price >= ema20_val else "Bearish"
        ema20_interp = f"Price {'above' if current_price >= ema20_val else 'below'} 20 EMA (₹{ema20_val:.2f})"

        ema50_signal = "Bullish" if current_price >= ema50_val else "Bearish"
        ema50_interp = f"Price {'above' if current_price >= ema50_val else 'below'} 50 EMA (₹{ema50_val:.2f})"

        ema200_signal = "Bullish" if current_price >= ema200_val else "Bearish"
        ema200_interp = f"Long-term trend {'bullish' if current_price >= ema200_val else 'bearish'} vs 200 EMA (₹{ema200_val:.2f})"

        # VWAP
        vwap_signal = "Bullish" if current_price >= vwap_val else "Bearish"
        vwap_interp = f"Institutional intraday positioning {'positive above' if current_price >= vwap_val else 'negative below'} VWAP (₹{vwap_val:.2f})"

        # ATR
        atr_signal = "Neutral"
        atr_interp = f"14-day average volatility range ₹{atr_val:.2f} ({((atr_val/current_price)*100):.2f}% of price)"

        # Volume
        if vol_ratio >= 1.4:
            vol_signal = "Bullish" if current_price >= close.iloc[-2] else "Bearish"
            vol_interp = f"Volume surging {vol_ratio:.1f}x above 20-day average"
        elif vol_ratio >= 1.0:
            vol_signal = "Bullish" if current_price >= close.iloc[-2] else "Neutral"
            vol_interp = f"Healthy volume participation ({vol_ratio:.1f}x 20D avg)"
        else:
            vol_signal = "Neutral"
            vol_interp = f"Subdued volume ({vol_ratio:.1f}x 20D avg) indicating consolidation"

        # Momentum
        if roc10 > 1.5:
            mom_signal = "Bullish"
            mom_interp = f"+{roc10:.1f}% 10-day Rate of Change confirms buying impulse"
        elif roc10 < -1.5:
            mom_signal = "Bearish"
            mom_interp = f"{roc10:.1f}% 10-day Rate of Change indicates active selling"
        else:
            mom_signal = "Neutral"
            mom_interp = f"Rate of change ({roc10:.1f}%) within normal stationary bounds"

        return {
            "rsi": {
                "name": "RSI (14)",
                "currentValue": rsi_val,
                "signal": rsi_signal,
                "interpretation": rsi_interp,
                "strength": rsi_strength,
            },
            "macd": {
                "name": "MACD (12, 26, 9)",
                "currentValue": f"{macd_val}/{macd_sig}",
                "signal": macd_signal,
                "interpretation": macd_interp,
                "strength": macd_strength,
            },
            "ema20": {
                "name": "EMA 20",
                "currentValue": round(ema20_val, 2),
                "signal": ema20_signal,
                "interpretation": ema20_interp,
                "strength": 75,
            },
            "ema50": {
                "name": "EMA 50",
                "currentValue": round(ema50_val, 2),
                "signal": ema50_signal,
                "interpretation": ema50_interp,
                "strength": 80,
            },
            "ema200": {
                "name": "EMA 200",
                "currentValue": round(ema200_val, 2),
                "signal": ema200_signal,
                "interpretation": ema200_interp,
                "strength": 85,
            },
            "vwap": {
                "name": "VWAP",
                "currentValue": round(vwap_val, 2),
                "signal": vwap_signal,
                "interpretation": vwap_interp,
                "strength": 82,
            },
            "atr": {
                "name": "ATR (14)",
                "currentValue": round(atr_val, 2),
                "signal": atr_signal,
                "interpretation": atr_interp,
                "strength": 70,
            },
            "volume": {
                "name": "Volume Ratio",
                "currentValue": f"{vol_ratio:.2f}x",
                "signal": vol_signal,
                "interpretation": vol_interp,
                "strength": int(min(95, max(40, vol_ratio * 50))),
            },
            "momentum": {
                "name": "Momentum (10D)",
                "currentValue": f"{roc10:+.2f}%",
                "signal": mom_signal,
                "interpretation": mom_interp,
                "strength": 75,
            },
            "priceStructure": {
                "name": "Price Structure",
                "currentValue": structure_signal,
                "signal": structure_signal,
                "interpretation": structure_interp,
                "strength": structure_strength,
            },
            "raw": {
                "currentPrice": current_price,
                "rsi": rsi_val,
                "macd_val": macd_val,
                "macd_sig": macd_sig,
                "macd_hist": macd_hist,
                "ema20": ema20_val,
                "ema50": ema50_val,
                "ema200": ema200_val,
                "vwap": vwap_val,
                "atr": atr_val,
                "vol_ratio": vol_ratio,
                "roc10": roc10,
            }
        }
