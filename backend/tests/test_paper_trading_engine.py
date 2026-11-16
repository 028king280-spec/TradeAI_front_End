import pytest
import os
import shutil

from app.options.paper_trading.cost_calculator import IndianDerivativesCostCalculator
from app.options.paper_trading.paper_engine import PaperTradingEngine
from app.options.paper_trading.trade_evaluator import AITradeEvaluator
from app.options.paper_trading.ml_feedback_engine import MLFeedbackEngine


def test_indian_derivatives_cost_calculator_buy():
    # Test Buy 1 Lot NIFTY (65 qty): Entry ₹100, Exit ₹130 (+30 pts gross)
    # Gross P&L = 30 * 65 = ₹1,950
    # Entry Turnover = 100 * 65 = ₹6,500
    # Exit Turnover = 130 * 65 = ₹8,450
    # Total Turnover = ₹14,950
    # Brokerage: ₹40 (2 orders)
    # STT: 8450 * 0.001 = ₹8.45
    # Exchange Fee: 14950 * 0.0005 = ₹7.48
    # GST: (40 + 7.48) * 0.18 = ₹8.55
    # Stamp Duty: 6500 * 0.00003 = ₹0.20
    # Slippage (0.5 pts * 65) = ₹32.50
    calc = IndianDerivativesCostCalculator.calculate_trade_costs_and_pnl(
        entry_price=100.0,
        exit_price=130.0,
        quantity=65,
        position_type="BUY",
        slippage_pts=0.5,
    )

    assert calc["grossPnl"] == 1950.0
    assert calc["grossPoints"] == 30.0
    assert calc["feeBreakdown"]["brokerage"] == 40.0
    assert calc["feeBreakdown"]["stt"] == 8.45
    assert calc["totalCosts"] > 90.0  # Fees + slippage
    assert calc["netPnl"] == round(1950.0 - calc["totalCosts"], 2)
    assert calc["netPnl"] > 1800.0


def test_indian_derivatives_cost_calculator_sell():
    # Test Sell / Short 1 Lot NIFTY (65 qty): Entry ₹120, Exit ₹90 (+30 pts gross gain)
    calc = IndianDerivativesCostCalculator.calculate_trade_costs_and_pnl(
        entry_price=120.0,
        exit_price=90.0,
        quantity=65,
        position_type="SELL",
        slippage_pts=0.5,
    )

    assert calc["grossPnl"] == 1950.0
    assert calc["grossPoints"] == 30.0
    assert calc["netPnl"] > 0.0


def test_paper_trading_lifecycle_and_partial_exit(monkeypatch, tmp_path):
    from app.data.market_calendar import MarketCalendar
    monkeypatch.setattr(MarketCalendar, "is_market_open", lambda: True)
    test_storage = str(tmp_path / "paper_records_lifecycle_test.json")
    engine = PaperTradingEngine(storage_path=test_storage)
    engine.reset_account(initial_capital=100000.0)

    # 1. Open a 2-Lot Position (2 * 65 = 130 qty)
    open_res = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY06NOV2624000CE",
        bias="CE",
        strike=24000.0,
        expiry="06NOV2026",
        entry_premium=100.0,
        lots=2,
        lot_size=65,
        stop_loss=80.0,
        target_1=125.0,
        target_2=160.0,
    )
    assert open_res["success"] is True
    pos = open_res["position"]
    pos_id = pos["id"]
    assert pos["remainingQuantity"] == 130
    assert engine.state["balance"] == 100000.0 - (100.0 * 130)

    # 2. Live Monitoring: Price moves to ₹120 (High=122, Low=98)
    # MFE should be +22 pts, MAE should be -2 pts
    monitored = engine.update_live_monitoring(
        contract_symbol="NIFTY06NOV2624000CE",
        current_ltp=120.0,
        bar_high=122.0,
        bar_low=98.0,
    )
    assert monitored["mfePts"] == 22.0
    assert monitored["maePts"] == 2.0

    # 3. Partial Exit: 1 Lot (65 qty) at Target 1 (₹125)
    partial_res = engine.execute_partial_exit(
        position_id=pos_id,
        exit_lots=1,
        exit_price=125.0,
        exit_label="Target 1 Hit",
    )
    assert partial_res["success"] is True
    assert pos["remainingQuantity"] == 65
    assert pos["lots"] == 1
    assert len(pos["partialExits"]) == 1

    # 4. Final Exit: Remaining 1 Lot at Target 2 (₹160)
    close_res = engine.close_position(
        position_id=pos_id,
        exit_price=160.0,
        exit_reason="Target 2 Hit",
    )
    assert close_res["success"] is True
    trade = close_res["trade"]
    assert trade["status"] == "TARGET_2_HIT"
    # Weighted Exit: (125 * 65 + 160 * 65) / 130 = 142.50
    assert trade["weightedExitPremium"] == 142.50
    assert trade["netPnl"] > 0
    assert engine.state["winCount"] == 1
    assert len(engine.state["openPositions"]) == 0
    assert len(engine.state["closedTrades"]) == 1


def test_ai_trade_evaluator():
    trade_mock = {
        "id": "PT-TEST-001",
        "contractSymbol": "NIFTY06NOV2624000CE",
        "bias": "CE",
        "entryPremium": 100.0,
        "exitPremium": 140.0,
        "netPnl": 2450.0,
        "stopLoss": 80.0,
        "target1": 125.0,
        "strategy": "Model A (Liquidity Sweep & Retest)",
        "ictSetup": "Bullish SSL Sweep + FVG 50% CE",
        "mfePts": 45.0,
        "maePts": 4.0,
        "totalCosts": 110.0,
        "marketFeaturesAtEntry": {
            "dealingRangeRegime": "DISCOUNT",
            "marketCondition": "TRENDING",
            "bosConfirmed": True,
            "sweepReclaim": True,
            "fvgRetest": True,
        }
    }

    eval_result = AITradeEvaluator.evaluate_completed_trade(trade_mock)
    assert eval_result["grade"] in ["A+", "A"]
    assert eval_result["totalFactorsCount"] == 9
    assert eval_result["passedFactorsCount"] >= 8
    assert "Peak MFE" in eval_result["mfeMaeSummary"]
    assert len(eval_result["keyTakeaways"]) > 0


def test_ml_feedback_engine(monkeypatch):
    # 1. Feature extraction
    trade_mock = {
        "id": "PT-ML-001",
        "contractSymbol": "NIFTY06NOV2624000CE",
        "bias": "CE",
        "spread": 1.1,
        "netPnl": 3100.0,
        "strategy": "Model A",
        "ictSetup": "SSL Sweep + Reclaim",
        "marketFeaturesAtEntry": {
            "greeks": {"iv": 0.14, "delta": 0.52, "theta": -12.5, "gamma": 0.002},
            "vix": 13.5,
            "atr": 110.0,
            "vwapDistancePct": 0.003,
            "dealingRangePct": 30.0,
            "mtfConfluenceScore": 90.0,
            "displacementRatio": 1.8,
            "fvgGapPts": 25.0,
            "pcr": 1.20,
        }
    }

    vec = MLFeedbackEngine.extract_features(trade_mock)
    assert len(vec) == 14
    assert vec[0] == 0.14  # IV
    assert vec[1] == 0.52  # Delta
    assert vec[10] == 1.0  # is_sweep

    # 2. Train dual models (XGBoost + Neural Network)
    dataset = MLFeedbackEngine.load_dataset()
    assert len(dataset) >= 8

    # Prevent mutation of protected what_ai_learned.json baseline
    monkeypatch.setattr(MLFeedbackEngine, "save_knowledge", lambda *a, **k: None)

    train_res = MLFeedbackEngine.train_models(dataset)
    assert "xgboostAccuracy" in train_res
    assert "neuralNetAccuracy" in train_res
    assert train_res["xgboostAccuracy"] >= 65.0
    assert train_res["neuralNetAccuracy"] >= 65.0

    # 3. Knowledge Base
    kb = MLFeedbackEngine.get_what_ai_learned()
    assert "bestPerformingSetups" in kb
    assert "worstPerformingSetups" in kb
    assert "mostCommonTradingMistakes" in kb
    assert "models" in kb
    assert "xgboost" in kb["models"]
    assert "neuralNetwork" in kb["models"]
