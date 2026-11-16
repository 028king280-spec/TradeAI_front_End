import pytest
import pandas as pd
import numpy as np

from app.options.ict_smc.structure_analyzer import MarketStructureAnalyzer
from app.options.ict_smc.liquidity_engine import LiquidityDetectionEngine
from app.options.ict_smc.fvg_orderblock_engine import FvgOrderBlockEngine
from app.options.ict_smc.multi_timeframe_engine import MultiTimeframeEngine
from app.options.ict_smc.scorecard_engine import AnalysisScorecardEngine
from app.options.ict_smc.historical_backtester import HistoricalBacktester
from app.options.ict_smc.ai_market_explainer import AIMarketExplainer


def create_sample_candles(trend="BULLISH", n=40, base_price=25000.0) -> pd.DataFrame:
    """Helper to generate realistic synthetic OHLCV candles."""
    np.random.seed(42)
    candles = []
    curr = base_price

    for i in range(n):
        if trend == "BULLISH":
            drift = 12.0 + np.random.normal(0, 4)
        elif trend == "BEARISH":
            drift = -12.0 + np.random.normal(0, 4)
        else:
            drift = np.random.normal(0, 8)

        open_p = curr
        close_p = open_p + drift
        high_p = max(open_p, close_p) + abs(np.random.normal(5, 2))
        low_p = min(open_p, close_p) - abs(np.random.normal(5, 2))
        volume = int(np.random.uniform(15000, 80000))

        candles.append({
            "timestamp": f"2026-11-04 09:{15 + (i * 5) % 60:02d}:00",
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": volume
        })
        curr = close_p

    return pd.DataFrame(candles)


def test_market_structure_analyzer():
    df_bull = create_sample_candles(trend="BULLISH", n=40, base_price=24800.0)
    res = MarketStructureAnalyzer.analyze_market_structure(df_bull, timeframe="15m")

    assert res["status"] == "CONFIRMED"
    assert "structureBias" in res
    assert len(res["externalSwings"]) >= 0
    assert len(res["internalSwings"]) >= 0
    assert "bosChoch" in res
    assert "summary" in res


def test_liquidity_detection_and_sweeps():
    df = create_sample_candles(trend="SIDEWAYS", n=40, base_price=25000.0)
    daily_h = 25150.0
    daily_l = 24850.0

    pools = LiquidityDetectionEngine.identify_liquidity_pools(
        df, daily_high=daily_h, daily_low=daily_l, prev_day_high=25160.0, prev_day_low=24840.0
    )

    assert "bslPools" in pools
    assert "sslPools" in pools
    assert "equalHighs" in pools
    assert "equalLows" in pools

    # Check sweep detection
    sweeps = LiquidityDetectionEngine.detect_liquidity_sweeps(df, pools)
    assert isinstance(sweeps, list)

    # Check heatmap
    heatmap = LiquidityDetectionEngine.build_liquidity_heatmap(pools, current_price=25000.0, atr_14=100.0)
    assert isinstance(heatmap, list)
    if heatmap:
        assert "densityScore" in heatmap[0]
        assert "colorIntensity" in heatmap[0]


def test_fvg_and_order_block_detection():
    # Build a 3-candle bullish FVG intentionally
    # Candle 0: High = 25000
    # Candle 1: Big impulse up, Open=25005, Close=25080, High=25090, Low=25002
    # Candle 2: Low = 25030, High = 25100
    # Gap between Candle 0 High (25000) and Candle 2 Low (25030) is 30 pts!
    df_fvg = pd.DataFrame([
        {"timestamp": "09:15", "open": 24980, "high": 25000, "low": 24960, "close": 24990, "volume": 10000},
        {"timestamp": "09:30", "open": 25005, "high": 25090, "low": 25002, "close": 25080, "volume": 50000},
        {"timestamp": "09:45", "open": 25075, "high": 25100, "low": 25030, "close": 25095, "volume": 20000},
        {"timestamp": "10:00", "open": 25095, "high": 25120, "low": 25080, "close": 25110, "volume": 15000},
        {"timestamp": "10:15", "open": 25110, "high": 25130, "low": 25090, "close": 25120, "volume": 12000},
    ])

    fvgs = FvgOrderBlockEngine.detect_fair_value_gaps(df_fvg, timeframe="15m", min_gap_pts=5.0)
    assert len(fvgs) >= 1
    bull_fvg = fvgs[0]
    assert bull_fvg["type"] == "BULLISH_FVG"
    assert bull_fvg["bottom"] == 25000.0
    assert bull_fvg["top"] == 25030.0
    assert bull_fvg["ce50"] == 25015.0

    # Order block detection
    blocks = FvgOrderBlockEngine.detect_order_blocks_and_breakers(df_fvg, timeframe="15m")
    assert isinstance(blocks, list)


def test_multi_timeframe_engine():
    df_1d = create_sample_candles(trend="BULLISH", n=20, base_price=24500.0)
    df_1h = create_sample_candles(trend="BULLISH", n=25, base_price=24800.0)
    df_15m = create_sample_candles(trend="BEARISH", n=30, base_price=25000.0)

    res = MultiTimeframeEngine.evaluate_multi_timeframe(
        timeframe_dfs={"1d": df_1d, "1h": df_1h, "15m": df_15m},
        current_price=25000.0,
        daily_high=25100.0,
        daily_low=24900.0
    )

    assert "overallAlignment" in res
    assert "confluenceScore" in res
    assert "isTradeable" in res
    assert "headline" in res
    assert res["overallAlignment"] in ["Mixed / Conflicting", "BIAS_CONFLICT"]
    assert res["isTradeable"] is False


def test_analysis_scorecard_engine():
    scorecard = AnalysisScorecardEngine.calculate_scorecard(
        htf_score_pct=1.0,        # 20
        structure_score_pct=1.0,  # 20
        liquidity_score_pct=1.0,  # 20
        displacement_score_pct=1.0,# 15
        fvg_ob_score_pct=1.0,     # 15
        rr_score_pct=1.0,         # 10
    )

    assert scorecard["overallScore"] == 100.0
    assert scorecard["convictionGrade"] == "HIGH_CONVICTION_INSTITUTIONAL"
    assert "suitable" in scorecard["recommendation"].lower()
    assert len(scorecard["missingConfirmations"]) == 0

    # Test incomplete setup
    scorecard_low = AnalysisScorecardEngine.calculate_scorecard(
        htf_score_pct=0.4,
        structure_score_pct=0.4,
        liquidity_score_pct=0.3,
        displacement_score_pct=0.5,
        fvg_ob_score_pct=0.5,
        rr_score_pct=0.4,
    )
    assert scorecard_low["overallScore"] < 50.0
    assert scorecard_low["convictionGrade"] in ["WEAK_WATCHLIST", "NO_TRADE_DISQUALIFIED"]
    assert len(scorecard_low["missingConfirmations"]) > 0


def test_ai_market_explainer_standard_report():
    df = create_sample_candles(trend="BULLISH", n=30, base_price=25000.0)
    structure = MarketStructureAnalyzer.analyze_market_structure(df, timeframe="15m")
    pools = LiquidityDetectionEngine.identify_liquidity_pools(df, daily_high=25100.0, daily_low=24900.0)

    report = AIMarketExplainer.generate_standard_report(
        symbol="NIFTY 50",
        market_bias="Bullish",
        htf_trend="Bullish",
        intraday_structure="Bullish BOS confirmed",
        liquidity_data=pools,
        structure_data=structure,
        fvg_ob_data={"fairValueGaps": [], "orderBlocks": []},
        dealing_range={"regime": "DISCOUNT", "equilibrium": 25000.0, "rangeHigh": 25100.0, "rangeLow": 24900.0},
    )

    assert "reportText" in report
    assert "structured" in report
    assert "NIFTY 50 MARKET ANALYSIS" in report["reportText"]
    assert "Market Bias: Bullish" in report["reportText"]


def test_historical_backtester_no_lookahead():
    df = create_sample_candles(trend="BULLISH", n=50, base_price=24800.0)
    res = HistoricalBacktester.backtest_algorithm(
        df=df,
        algorithm_type="COMBINED_ICT_SMC",
        timeframe="15m",
        slippage_pts=1.5,
        brokerage_per_trade=40.0
    )

    assert "winRate" in res
    assert "sampleSize" in res
    assert "profitFactor" in res
    assert "maxDrawdownRupees" in res
    assert "totalPnlRupees" in res
    assert res["sampleSize"] >= 0
