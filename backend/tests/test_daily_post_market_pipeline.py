"""
Unit & Integration Tests for AIVOLVE Daily Post-Market Trade Forensics & Continuous ML Learning Pipeline.
Target Session: 19 November 2026, Asia/Kolkata
"""

import os
import json
import hashlib
import pytest
from decimal import Decimal

from app.options.paper_trading.post_market_pipeline import (
    DailyPostMarketForensicPipeline,
    OutcomeClassification,
    RecordProvenance,
    PROTECTED_BASELINE_FILES,
    MIN_SAMPLES_FOR_RETRAINING,
    BACKEND_DIR,
)
from app.options.paper_trading.cost_calculator import IndianDerivativesCostCalculator


class TestDailyPostMarketPipeline:

    def setup_method(self):
        self.pipeline = DailyPostMarketForensicPipeline("2026-11-19")

    def test_pipeline_execution_and_trade_count(self):
        report = self.pipeline.run_full_pipeline()
        assert report is not None
        assert report["execution_policy"] == "PAPER_TRADING_ONLY"
        assert report["session_date"] == "2026-11-19"
        # Total analyzed must include all 11 verified paper store trades
        assert report["paper_cockpit_trades_count"] == 11
        assert report["total_trades_analyzed"] >= 11

    def test_trade_outcome_classification(self):
        report = self.pipeline.run_full_pipeline()
        paper_trades = report["paper_trades"]

        # PT-947F4576 (BANKNIFTY 62700CE) -> Target 2 Hit
        t1 = next(t for t in paper_trades if t["trade_id"] == "PT-947F4576")
        assert t1["outcome_classification"] == OutcomeClassification.TARGET_2_HIT.value
        assert t1["net_pnl"] > 5000.0

        # PT-98070912 (NIFTY 25450CE) -> Manual Close in profit
        t2 = next(t for t in paper_trades if t["trade_id"] == "PT-98070912")
        assert t2["outcome_classification"] == OutcomeClassification.MANUAL_EXIT.value
        assert t2["net_pnl"] > 1400.0

        # PT-94BD04F7 (NIFTY 25350CE) -> Target 2 Hit
        t3 = next(t for t in paper_trades if t["trade_id"] == "PT-94BD04F7")
        assert t3["outcome_classification"] == OutcomeClassification.TARGET_2_HIT.value
        assert t3["net_pnl"] > 5000.0

        # PT-86BDFDBE -> Breakeven manual exit
        tbe = next(t for t in paper_trades if t["trade_id"] == "PT-86BDFDBE")
        assert tbe["gross_pnl"] == 0.0
        assert tbe["entry_premium"] == tbe["exit_premium"]
        assert tbe["net_pnl"] < 0.0  # Loss strictly from statutory fees

    def test_decimal_safe_financial_reconciliation(self):
        report = self.pipeline.run_full_pipeline()
        rec = report["paper_cockpit_reconciliation"]

        # Verified figures
        assert rec["total_positions_closed"] == 11
        assert rec["winning_positions"] == 5
        assert rec["losing_positions"] == 6
        assert rec["gross_realized_pnl"] == 20673.25
        assert rec["total_simulated_costs"] == 1128.79
        assert rec["net_realized_pnl"] == 19544.46
        assert rec["profit_factor"] > 5.0
        assert rec["net_win_rate_pct"] == 45.45
        assert rec["closing_virtual_equity"] > 115000.0

    def test_anti_leakage_and_forward_horizons(self):
        report = self.pipeline.run_full_pipeline()
        for t in report["trades"]:
            assert t["anti_leakage_feature_validated"] is True
            assert len(t["feature_vector"]) == 14
            # Forward horizons must contain 5, 15, 30, 60 minutes
            assert "5" in t["forward_horizons"]
            assert "15" in t["forward_horizons"]
            assert "30" in t["forward_horizons"]
            assert "60" in t["forward_horizons"]

    def test_ml_governance_500_sample_gate(self):
        report = self.pipeline.run_full_pipeline()
        gov = report["ml_governance"]

        assert gov["threshold_required"] == MIN_SAMPLES_FOR_RETRAINING  # 500
        assert gov["current_genuine_samples"] == 16
        assert gov["current_genuine_samples"] < 500
        assert gov["training_status"] == "TRAINING_BLOCKED_ACCUMULATING_SAMPLES"
        assert gov["model_weights_updated"] is False
        assert gov["strategy_weights_updated"] is False

    def test_protected_baseline_immutability(self):
        pre_hashes = self.pipeline.get_baseline_hashes()
        self.pipeline.run_full_pipeline()
        post_hashes = self.pipeline.get_baseline_hashes()

        check = self.pipeline.verify_baseline_immutability(pre_hashes, post_hashes)
        assert check["all_baselines_untouched"] is True
        for rel_path in PROTECTED_BASELINE_FILES:
            assert check["files"][rel_path]["untouched"] is True
            assert pre_hashes[rel_path] == post_hashes[rel_path]
