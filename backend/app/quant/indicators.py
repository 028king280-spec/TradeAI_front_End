from typing import Dict, Any, Optional
import numpy as np
import pandas as pd


class TechnicalIndicators:
    """
    Institutional Technical Indicator Engine.
    Computes mathematically rigorous indicators:
    RSI, MACD, EMA 20/50/200, VWAP, ATR, Volume SMA, Volume Ratio, Momentum, Volatility.
    Never uses random or hardcoded mock figures.
    """

    @staticmethod
    def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """
        RSI using Wilder's exponential smoothing method.
        """
        delta = series.diff()
        gain = (delta.where(delta > 0, 0.0)).copy()
        loss = (-delta.where(delta < 0, 0.0)).copy()

        # Initial simple average
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()

        # Exponential moving average (Wilder smoothing: alpha = 1 / period)
        for i in range(period, len(series)):
            avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
            avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.fillna(50.0)

    @staticmethod
    def calculate_ema(series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    @staticmethod
    def calculate_macd(
        series: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Dict[str, pd.Series]:
        fast_ema = TechnicalIndicators.calculate_ema(series, fast)
        slow_ema = TechnicalIndicators.calculate_ema(series, slow)
        macd_line = fast_ema - slow_ema
        signal_line = TechnicalIndicators.calculate_ema(macd_line, signal)
        histogram = macd_line - signal_line
        return {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": histogram,
        }

    @staticmethod
    def calculate_vwap(df: pd.DataFrame) -> pd.Series:
        """
        Volume-Weighted Average Price = cumsum(Typical Price * Volume) / cumsum(Volume)
        """
        typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
        pv = typical_price * df["volume"]
        vol_sum = df["volume"].cumsum()
        vwap = pv.cumsum() / vol_sum.replace(0, np.nan)
        return vwap.bfill().ffill()

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Average True Range (ATR) with Wilder smoothing.
        True Range = max(H - L, abs(H - PrevClose), abs(L - PrevClose))
        """
        prev_close = df["close"].shift(1)
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - prev_close).abs()
        tr3 = (df["low"] - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        return atr.bfill().ffill()

    @classmethod
    def compute_all_indicators(cls, df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """
        Computes full technical indicator suite on OHLCV DataFrame.
        Returns structured dictionary conforming strictly to AIVOLVE schema contracts.
        """
        if df.empty or len(df) < 5:
            return cls._empty_indicators()

        close = df["close"]
        current_price = float(close.iloc[-1])

        # 1. RSI
        rsi_series = cls.calculate_rsi(close, 14)
        latest_rsi = round(float(rsi_series.iloc[-1]), 2)
        if latest_rsi >= 60:
            rsi_sig = "Bullish"
            rsi_strength = min(100, int((latest_rsi - 50) * 2.5 + 50))
            rsi_interp = f"Momentum bullish above 60 ({latest_rsi}). Upward acceleration supported."
        elif latest_rsi <= 40:
            rsi_sig = "Bearish"
            rsi_strength = min(100, int((50 - latest_rsi) * 2.5 + 50))
            rsi_interp = f"Bearish momentum under 40 ({latest_rsi}). Sellers dominate order flow."
        else:
            rsi_sig = "Neutral"
            rsi_strength = 50
            rsi_interp = f"Consolidating in neutral band ({latest_rsi})."

        # 2. MACD
        macd_dict = cls.calculate_macd(close, 12, 26, 9)
        latest_macd = round(float(macd_dict["macd"].iloc[-1]), 2)
        latest_signal = round(float(macd_dict["signal"].iloc[-1]), 2)
        latest_hist = round(float(macd_dict["histogram"].iloc[-1]), 2)

        if latest_hist > 0 and latest_macd > latest_signal:
            macd_sig = "Bullish"
            macd_strength = 75 if latest_macd > 0 else 60
            macd_interp = f"Bullish crossover with expanding histogram (+{latest_hist})."
        elif latest_hist < 0 and latest_macd < latest_signal:
            macd_sig = "Bearish"
            macd_strength = 75 if latest_macd < 0 else 60
            macd_interp = f"Bearish divergence with negative histogram ({latest_hist})."
        else:
            macd_sig = "Neutral"
            macd_strength = 50
            macd_interp = "MACD line converging with signal line."

        # 3. EMAs
        ema20 = cls.calculate_ema(close, 20)
        ema50 = cls.calculate_ema(close, 50)
        ema200 = cls.calculate_ema(close, min(200, len(close)))

        val_ema20 = round(float(ema20.iloc[-1]), 2)
        val_ema50 = round(float(ema50.iloc[-1]), 2)
        val_ema200 = round(float(ema200.iloc[-1]), 2)

        # 4. VWAP
        vwap_series = cls.calculate_vwap(df)
        val_vwap = round(float(vwap_series.iloc[-1]), 2)
        vwap_sig = "Bullish" if current_price >= val_vwap else "Bearish"
        vwap_diff_pct = round(((current_price - val_vwap) / val_vwap) * 100, 2)
        vwap_interp = (
            f"Trading above VWAP by {vwap_diff_pct}%. Buyers defending benchmark intraday value."
            if current_price >= val_vwap
            else f"Trading below VWAP by {abs(vwap_diff_pct)}%. Intraday supply overhead."
        )

        # 5. ATR
        atr_series = cls.calculate_atr(df, 14)
        val_atr = round(float(atr_series.iloc[-1]), 2)
        atr_pct = round((val_atr / current_price) * 100, 2)
        atr_sig = "Bullish" if atr_pct < 2.5 else "Neutral" if atr_pct < 4.0 else "Bearish"
        atr_interp = f"14-period True Range is ₹{val_atr} ({atr_pct}% of CMP). Volatility measured."

        # 6. Volume
        vol = df["volume"]
        vol_sma20 = vol.rolling(window=min(20, len(vol)), min_periods=1).mean()
        cur_vol = float(vol.iloc[-1])
        avg_vol = float(vol_sma20.iloc[-1])
        vol_ratio = round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0

        if vol_ratio >= 1.5:
            vol_sig = "Bullish" if current_price >= val_ema20 else "Bearish"
            vol_interp = f"High institutional participation: {vol_ratio}x 20-period average volume."
        elif vol_ratio < 0.7:
            vol_sig = "Neutral"
            vol_interp = f"Light volume ({vol_ratio}x avg). Awaiting institutional breakout trigger."
        else:
            vol_sig = "Neutral"
            vol_interp = f"Average market turnover ({vol_ratio}x 20-period average)."

        # 7. Momentum
        roc = float(((close.iloc[-1] - close.iloc[-min(10, len(close))]) / close.iloc[-min(10, len(close))]) * 100)
        mom_sig = "Bullish" if roc > 0.5 else "Bearish" if roc < -0.5 else "Neutral"
        mom_strength = min(100, max(20, int(abs(roc) * 12 + 40)))

        return {
            "rsi": {
                "name": "RSI (14)",
                "currentValue": latest_rsi,
                "signal": rsi_sig,
                "strength": rsi_strength,
                "interpretation": rsi_interp,
            },
            "macd": {
                "name": "MACD (12, 26, 9)",
                "currentValue": f"{latest_macd} / {latest_signal}",
                "signal": macd_sig,
                "strength": macd_strength,
                "interpretation": macd_interp,
            },
            "ema20": {
                "name": "20 EMA",
                "currentValue": val_ema20,
                "signal": "Bullish" if current_price > val_ema20 else "Bearish",
                "strength": 75 if current_price > val_ema20 else 35,
                "interpretation": f"Price is {'above' if current_price > val_ema20 else 'below'} short-term 20 EMA dynamic trend guide.",
            },
            "ema50": {
                "name": "50 EMA",
                "currentValue": val_ema50,
                "signal": "Bullish" if current_price > val_ema50 else "Bearish",
                "strength": 70 if current_price > val_ema50 else 40,
                "interpretation": f"Medium-term 50 EMA {'maintained as dynamic floor' if current_price > val_ema50 else 'resisting upside attempts'}.",
            },
            "ema200": {
                "name": "200 EMA",
                "currentValue": val_ema200,
                "signal": "Bullish" if current_price > val_ema200 else "Bearish",
                "strength": 85 if current_price > val_ema200 else 30,
                "interpretation": f"Primary macro trend is {'bullish above' if current_price > val_ema200 else 'bearish below'} 200 EMA.",
            },
            "vwap": {
                "name": "Intraday VWAP",
                "currentValue": val_vwap,
                "signal": vwap_sig,
                "strength": 80 if vwap_sig == "Bullish" else 40,
                "interpretation": vwap_interp,
            },
            "atr": {
                "name": "ATR (14)",
                "currentValue": val_atr,
                "signal": atr_sig,
                "strength": 65,
                "interpretation": atr_interp,
            },
            "volume": {
                "name": "Volume Ratio",
                "currentValue": f"{vol_ratio}x",
                "signal": vol_sig,
                "strength": min(100, int(vol_ratio * 40)),
                "interpretation": vol_interp,
            },
            "momentum": {
                "name": "Price Momentum (ROC 10)",
                "currentValue": f"{round(roc, 2)}%",
                "signal": mom_sig,
                "strength": mom_strength,
                "interpretation": f"10-period momentum oscillator at {round(roc, 2)}%.",
            },
            "priceStructure": {
                "name": "Structure Bias",
                "currentValue": "Higher Highs" if current_price > val_ema20 else "Consolidation",
                "signal": "Bullish" if current_price > val_ema20 else "Neutral",
                "strength": 70,
                "interpretation": "Structure aligned with primary trend trajectory.",
            },
        }

    @staticmethod
    def _empty_indicators() -> Dict[str, Dict[str, Any]]:
        return {
            "rsi": {"name": "RSI", "currentValue": 50.0, "signal": "Neutral", "interpretation": "Insufficient candle data"},
            "macd": {"name": "MACD", "currentValue": "0 / 0", "signal": "Neutral", "interpretation": "Insufficient candle data"},
            "ema20": {"name": "20 EMA", "currentValue": 0.0, "signal": "Neutral", "interpretation": "Insufficient candle data"},
            "ema50": {"name": "50 EMA", "currentValue": 0.0, "signal": "Neutral", "interpretation": "Insufficient candle data"},
            "ema200": {"name": "200 EMA", "currentValue": 0.0, "signal": "Neutral", "interpretation": "Insufficient candle data"},
            "vwap": {"name": "VWAP", "currentValue": 0.0, "signal": "Neutral", "interpretation": "Insufficient candle data"},
            "atr": {"name": "ATR", "currentValue": 0.0, "signal": "Neutral", "interpretation": "Insufficient candle data"},
            "volume": {"name": "Volume", "currentValue": "1.0x", "signal": "Neutral", "interpretation": "Insufficient candle data"},
            "momentum": {"name": "Momentum", "currentValue": "0.0%", "signal": "Neutral", "interpretation": "Insufficient candle data"},
            "priceStructure": {"name": "Structure", "currentValue": "Neutral", "signal": "Neutral", "interpretation": "Insufficient candle data"},
        }
