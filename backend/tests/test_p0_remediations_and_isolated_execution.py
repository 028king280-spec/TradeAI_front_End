"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Comprehensive Test Suite for P0 Defect Remediations & Isolated Execution (Task 4).
"""

import os
import tempfile
import pytest
from decimal import Decimal

from app.options.next_session_engine import evaluate_next_session_recommendation
from app.data.instrument_master import InstrumentMaster
from app.data.market_calendar import MarketCalendar
from app.options.paper_trading.paper_engine import PaperTradingEngine
from app.options.paper_trading.cost_calculator import IndianDerivativesCostCalculator
from app.options.paper_trading.post_market_pipeline import (
    DailyPostMarketForensicPipeline,
    PROTECTED_BASELINE_FILES,
    MIN_SAMPLES_FOR_RETRAINING,
)


class TestP0RemediationsAndExecution:

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="aivolve_p0_test_")
        self.tmp_storage = os.path.join(self.tmp_dir, "test_paper_state.json")
        self.im = InstrumentMaster.get_instance()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_correct_exchange_lot_sizes(self):
        """Validates that authoritative NSE lot sizes are 65 (NIFTY), 30 (BANKNIFTY), 60 (FINNIFTY), 10 (SENSEX)."""
        nifty_opt = self.im.resolve_option_contract("NIFTY", 25350.0, "CE")
        assert nifty_opt is not None
        assert int(nifty_opt.get("lotsize", 0)) == 65

        bank_opt = self.im.resolve_option_contract("BANKNIFTY", 62700.0, "CE")
        assert bank_opt is not None
        assert int(bank_opt.get("lotsize", 0)) == 30

        fin_opt = self.im.resolve_option_contract("FINNIFTY", 24000.0, "CE")
        assert fin_opt is not None
        assert int(fin_opt.get("lotsize", 0)) == 60

    def test_signed_greeks_negative_pe_delta(self):
        """Verifies that PE contracts have strictly negative Delta (-1.0 to 0.0), and CE positive (0.0 to 1.0)."""
        strikes_mock = [
            {
                "strike": 25350.0,
                "ce": {"ltp": 150.0, "bid": 149.5, "ask": 150.5, "oi": 80000, "iv": 14.0},
                "pe": {"ltp": 120.0, "bid": 119.5, "ask": 120.5, "oi": 95000, "iv": 14.5},
            }
        ]

        # Call recommendation
        rec_call = evaluate_next_session_recommendation(
            symbol="NIFTY 50",
            underlying_ltp=25350.0,
            sentiment="BULLISH",
            sentiment_score=68,
            strikes_data=strikes_mock,
            atr_14=110.0,
            daily_high=25450.0,
            daily_low=25250.0,
            daily_close=25300.0,
            daily_open=25280.0,
            vix_value=13.5
        )
        assert rec_call["recommendation"] is not None
        assert rec_call["recommendation"]["optionType"] == "CE"
        assert rec_call["recommendation"]["greeks"]["delta"] > 0.0
        assert 0.0 < rec_call["recommendation"]["greeks"]["delta"] <= 1.0

        # Put recommendation
        rec_put = evaluate_next_session_recommendation(
            symbol="NIFTY 50",
            underlying_ltp=25350.0,
            sentiment="BEARISH",
            sentiment_score=35,
            strikes_data=strikes_mock,
            atr_14=110.0,
            daily_high=25450.0,
            daily_low=25250.0,
            daily_close=25400.0,
            daily_open=25380.0,
            vix_value=13.5
        )
        assert rec_put["recommendation"] is not None
        assert rec_put["recommendation"]["optionType"] == "PE"
        # Delta for Put MUST be negative!
        assert rec_put["recommendation"]["greeks"]["delta"] < 0.0
        assert -1.0 <= rec_put["recommendation"]["greeks"]["delta"] < 0.0

    def test_future_target_session_stage_1_pre_market(self):
        """Verifies that recommendations for future upcoming sessions are Stage 1 (Pre-Market), NOT Stage 2."""
        strikes_mock = [
            {"strike": 25350.0, "ce": {"ltp": 150.0, "bid": 149.5, "ask": 150.5, "oi": 80000, "iv": 14.0}, "pe": {}}
        ]
        rec = evaluate_next_session_recommendation(
            symbol="NIFTY 50",
            underlying_ltp=25350.0,
            sentiment="BULLISH",
            sentiment_score=65,
            strikes_data=strikes_mock,
            atr_14=110.0,
            daily_high=25450.0,
            daily_low=25250.0,
            daily_close=25300.0,
            daily_open=25280.0,
            vix_value=13.5
        )
        # Next session is tomorrow or Monday -> must be Stage 1 Pre-Market
        assert rec["stage"] == "STAGE_1_PRE_MARKET"
        assert "STAGE 1" in rec["stageLabel"]

    def test_paper_buy_entry_and_partial_booking_isolated(self):
        """Tests full execution lifecycle: BUY entry, 50% partial exit at T1, remainder at T2 in sandbox storage."""
        engine = PaperTradingEngine(storage_path=self.tmp_storage)
        assert engine.state["balance"] == 100000.0

        # Open 2 lots of BANKNIFTY (2 * 30 = 60 Qty)
        open_res = engine.open_position(
            instrument="BANK NIFTY",
            contract_symbol="BANKNIFTY23NOV2662700CE",
            bias="CE",
            strike=62700.0,
            expiry="23NOV2026",
            entry_premium=350.0,
            position_type="BUY",
            lots=2,
            lot_size=30,
            stop_loss=300.0,
            target_1=450.0,
            target_2=550.0,
            target_3=650.0,
            strategy="SMC Expansion",
            ict_setup="Bullish SSL Sweep",
            market_features={"allowAfterHoursSimulation": True}
        )
        assert open_res["success"] is True
        pos = open_res["position"]
        pos_id = pos["id"]
        assert pos["lots"] == 2
        assert pos["quantity"] == 60
        assert pos["lotSize"] == 30
        assert engine.state["balance"] == 100000.0 - (350.0 * 60)

        # 50% Partial Exit (1 lot = 30 Qty) at Target 1 (₹450.0)
        part_res = engine.execute_partial_exit(
            position_id=pos_id,
            exit_lots=1,
            exit_price=450.0,
            exit_label="Target 1 Hit"
        )
        assert part_res["success"] is True
        assert part_res["partialRecord"]["exitLots"] == 1
        assert part_res["partialRecord"]["exitQuantity"] == 30
        assert part_res["partialRecord"]["netPnl"] > 0.0
        assert pos["lots"] == 1
        assert pos["remainingQuantity"] == 30

        # Close remaining 1 lot at Target 2 (₹550.0)
        close_res = engine.close_position(
            position_id=pos_id,
            exit_price=550.0,
            exit_reason="Target 2 Hit"
        )
        assert close_res["success"] is True
        assert len(engine.state["openPositions"]) == 0
        assert len(engine.state["closedTrades"]) == 1

        # Financial reconciliation
        closed_trade = engine.state["closedTrades"][0]
        assert closed_trade["status"] in ("CLOSED", "TARGET_2_HIT")
        assert closed_trade["grossPnl"] > 0.0
        assert closed_trade["netPnl"] > 0.0
        # Balance must reflect starting capital + net P&L
        assert engine.state["balance"] > 100000.0

    def test_governance_locked_rejections(self):
        """Verifies SENSEX is strictly rejected and naked option selling is blocked."""
        engine = PaperTradingEngine(storage_path=self.tmp_storage)

        # 1. SENSEX rejection
        res_sensex = engine.open_position(
            instrument="SENSEX",
            contract_symbol="SENSEX20NOV2680000CE",
            bias="CE",
            strike=80000.0,
            expiry="20NOV2026",
            entry_premium=200.0,
            position_type="BUY",
            lots=1,
            lot_size=10,
            market_features={"allowAfterHoursSimulation": True}
        )
        assert res_sensex["success"] is False
        assert "GOVERNANCE_LOCK" in res_sensex["message"]

        # 2. Naked Option Selling rejection
        res_sell = engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY23NOV2625350CE",
            bias="CE",
            strike=25350.0,
            expiry="23NOV2026",
            entry_premium=150.0,
            position_type="SELL",  # Short option
            lots=1,
            lot_size=65,
            market_features={"allowAfterHoursSimulation": True}
        )
        assert res_sell["success"] is False
        assert "SHORT_OPTIONS_PROHIBITED" in res_sell.get("status", "") or "BUY" in res_sell["message"]

    def test_baseline_immutability(self):
        """Verifies that all 6 protected baseline files remain 100% untouched."""
        pipeline = DailyPostMarketForensicPipeline("2026-11-19")
        pre = pipeline.get_baseline_hashes()
        pipeline.run_full_pipeline()
        post = pipeline.get_baseline_hashes()

        check = pipeline.verify_baseline_immutability(pre, post)
        assert check["all_baselines_untouched"] is True
        for f in PROTECTED_BASELINE_FILES:
            assert pre[f] == post[f]
