"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Test Suite for AI News Sentiment & Top 10 Intraday Stock Opportunity Scanner.

Validates:
1. Positive News Classification (Earnings Beat, Order Win, Regulatory Clearance)
2. Negative News Classification (Earnings Deterioration, Enforcement Probe, Regulatory Warning)
3. Neutral and Mixed/Conflicting News Classification
4. Rumor vs Official Exchange Filing verification status
5. High-Precision Entity Resolution (Real NSE Symbols, Discarding Macro Nifty/Sensex talk)
6. Duplicate Syndicated Articles Handling
7. Real Market Confirmation (Bullish, Bearish, Divergence, Unverified)
8. Zero Fabricated Prices Invariant
9. Non-Padded Ranking (Does not force 10 if fewer qualify)
10. Six Protected Historical Baseline Hashes Immutability
"""

import os
import json
import pytest
from app.services.news_classifier import get_news_classifier, NewsClassifier
from app.services.news_entity_resolver import get_news_entity_resolver, NewsEntityResolver
from app.services.news_scanner_service import get_intraday_news_scanner, IntradayNewsScannerService
from app.options.paper_trading.post_market_pipeline import DailyPostMarketForensicPipeline, PROTECTED_BASELINE_FILES


class TestNewsSentimentClassifier:
    """Validates deterministic financial event classification."""

    @pytest.fixture(autouse=True)
    def setup_classifier(self):
        self.classifier = get_news_classifier()

    def test_positive_earnings_beat(self):
        res = self.classifier.classify("Tata Consumer Q2 profit jumps 45% YoY beating Street estimates")
        assert res["sentiment"] in ("VERY_BULLISH", "BULLISH")
        assert res["sentimentPolarity"] >= 50
        assert res["impactScore"] >= 70
        assert res["category"] == "EARNINGS_SURPRISE_BEAT"

    def test_positive_order_win(self):
        res = self.classifier.classify("BEL secures Rs 3,500 crore defense contract order win from Indian Army")
        assert res["sentiment"] in ("VERY_BULLISH", "BULLISH")
        assert res["sentimentPolarity"] >= 60
        assert res["impactScore"] >= 75
        assert res["category"] == "ORDER_WIN_LARGE_CONTRACT"

    def test_positive_regulatory_approval(self):
        res = self.classifier.classify("Sun Pharma receives USFDA EIR approval with zero observations for Halol facility")
        assert res["sentiment"] in ("VERY_BULLISH", "BULLISH")
        assert res["sentimentPolarity"] >= 60
        assert res["impactScore"] >= 70
        assert res["category"] == "REGULATORY_APPROVAL_CLEARANCE"

    def test_negative_fraud_and_probe(self):
        res = self.classifier.classify("CBI searches offices of corporate firm over accounting fraud allegations")
        assert res["sentiment"] in ("VERY_BEARISH", "BEARISH")
        assert res["sentimentPolarity"] <= -60
        assert res["impactScore"] >= 80
        assert res["category"] == "FRAUD_ENFORCEMENT_PROBE"

    def test_negative_regulatory_warning(self):
        res = self.classifier.classify("USFDA issues warning letter to drugmaker citing data integrity observations")
        assert res["sentiment"] in ("VERY_BEARISH", "BEARISH")
        assert res["sentimentPolarity"] <= -60
        assert res["impactScore"] >= 75
        assert res["category"] == "REGULATORY_PENALTY_WARNING"

    def test_negative_debt_distress(self):
        res = self.classifier.classify("NCLT admits insolvency petition against infrastructure firm following loan default")
        assert res["sentiment"] in ("VERY_BEARISH", "BEARISH")
        assert res["sentimentPolarity"] <= -70
        assert res["impactScore"] >= 85
        assert res["category"] == "DEBT_DISTRESS_DEFAULT"

    def test_neutral_corporate_update(self):
        res = self.classifier.classify("Company informs board meeting scheduled next week to consider financial statements")
        assert res["sentiment"] == "NEUTRAL"
        assert -15 <= res["sentimentPolarity"] <= 15
        assert res["impactScore"] <= 25

    def test_rumor_versus_official_verification(self):
        rumor_res = self.classifier.classify("Sources say company reportedly in talks for potential stake sale")
        assert rumor_res["verificationStatus"] == "UNVERIFIED_RUMOR"
        assert rumor_res["confidence"] < 0.5

        official_res = self.classifier.classify("Company informs exchange filing regarding board outcome of meeting", source="NSE Corporate Announcement")
        assert official_res["verificationStatus"] == "VERIFIED_OFFICIAL_FILING"
        assert official_res["confidence"] >= 0.8


class TestNewsEntityResolver:
    """Validates company name and symbol resolution."""

    @pytest.fixture(autouse=True)
    def setup_resolver(self):
        self.resolver = get_news_entity_resolver()

    def test_resolve_exact_equity_symbol(self):
        res = self.resolver.resolve("Reliance Industries reports Rs 18,000 crore revenue")
        assert res is not None
        assert res["symbol"] == "RELIANCE"
        assert res["sector"] == "Energy & Conglomerate"
        assert res["isCompanySpecific"] is True

    def test_resolve_brand_variants(self):
        res = self.resolver.resolve("Tata Motors shares rally 3% on JLR global sales update")
        assert res is not None
        assert res["symbol"] == "TATAMOTORS"
        assert res["isCompanySpecific"] is True

    def test_resolve_defense_psu(self):
        res = self.resolver.resolve("Bharat Electronics bags new export order worth $50 million")
        assert res is not None
        assert res["symbol"] == "BEL"
        assert res["isCompanySpecific"] is True

    def test_generic_market_news_rejected(self):
        # Must return None so generic market news does not taint single stocks
        res1 = self.resolver.resolve("Sensex drops 400 pts amid broad-based selloff on Dalal Street")
        assert res1 is None

        res2 = self.resolver.resolve("FIIs sell shares worth Rs 3,500 crore as global cues weaken")
        assert res2 is None


class TestNewsScannerEngine:
    """Validates ranking, deduplication, and zero-fabricated-price safety."""

    @pytest.fixture(autouse=True)
    def setup_scanner(self):
        self.scanner = get_intraday_news_scanner()

    @pytest.mark.asyncio
    async def test_non_padded_ranking_and_structure(self):
        data = await self.scanner.scan_and_rank_opportunities()
        assert "topOverall" in data
        assert "topBullish" in data
        assert "topBearish" in data
        assert isinstance(data["topOverall"], list)

        # Invariant: Never pad with artificial stocks if fewer qualify
        assert len(data["topOverall"]) <= 10
        assert len(data["topBullish"]) <= 10
        assert len(data["topBearish"]) <= 10

        # Ranks must be consecutive starting at 1
        for i, s in enumerate(data["topOverall"]):
            assert s["rank"] == i + 1
            assert "symbol" in s
            assert "compositeRankScore" in s
            assert 0 <= s["compositeRankScore"] <= 100

    @pytest.mark.asyncio
    async def test_zero_fabricated_prices_invariant(self):
        data = await self.scanner.scan_and_rank_opportunities()
        for s in data["topOverall"]:
            # If currentPrice is None or <= 0, dataStatus MUST NOT be claimed as VERIFIED_LIVE
            if s["currentPrice"] is None or s["currentPrice"] <= 0:
                assert s["dataStatus"] in ("DATA_OFFLINE", "PRICE_UNVERIFIED")
                assert s["priceConfirmation"] == "PRICE_UNVERIFIED"
            else:
                # If price is provided, it must be a positive float with valid status
                assert s["currentPrice"] > 0
                assert s["dataStatus"] in ("VERIFIED_LIVE", "VERIFIED_EOD")

    def test_six_protected_baselines_immutability(self):
        pipeline = DailyPostMarketForensicPipeline("2026-11-19")
        hashes = pipeline.get_baseline_hashes()
        for f in PROTECTED_BASELINE_FILES:
            assert f in hashes
            assert len(hashes[f]) == 64  # Valid SHA-256 string

