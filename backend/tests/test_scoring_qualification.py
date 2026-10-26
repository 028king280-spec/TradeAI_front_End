import pytest
from app.analysis.scoring import ScoringEngine
from app.analysis.qualification import QualificationEngine


def test_deterministic_scoring():
    technical = {
        "raw": {
            "currentPrice": 1500.0,
            "rsi": 64.0,
            "macd_hist": 2.5,
            "ema20": 1480.0,
            "ema50": 1460.0,
            "vwap": 1490.0,
            "vol_ratio": 1.4,
            "roc10": 2.2,
        },
        "priceStructure": {"signal": "Bullish"},
    }
    market_context = {
        "marketBias": "BULLISH",
        "confidence": 80,
        "indiaVixStatus": "Moderate",
    }
    sector_analysis = {
        "sectorScore": 9,
        "relativeStrength": "Strong",
    }

    score_result = ScoringEngine.evaluate(technical, market_context, sector_analysis)

    assert 0 <= score_result["totalScore"] <= 100
    assert score_result["grade"] in ["STRONG", "QUALIFIED", "WATCH", "REJECT"]

    # Check that category sum matches totalScore
    cat_sum = sum(c["score"] for c in score_result["categories"])
    assert cat_sum == score_result["totalScore"]


def test_candidate_qualification_not_forced():
    # Setup with poor score and negative risk reward
    qual = QualificationEngine.qualify_call(
        analysis_score=60,
        current_price=1000.0,
        expected_high_max=1005.0,  # 5 upside
        support_1=990.0,            # 10 risk (0.5:1 RR)
        market_bias="BEARISH",
        volume_ratio=0.5
    )
    assert qual["qualified"] is False
    assert "threshold" in qual["reason"].lower() or "risk" in qual["reason"].lower()

    # Highly qualified setup
    qual_good = QualificationEngine.qualify_call(
        analysis_score=86,
        current_price=1000.0,
        expected_high_max=1035.0,  # 35 upside
        support_1=985.0,            # 15 risk (2.3:1 RR)
        market_bias="BULLISH",
        volume_ratio=1.4
    )
    assert qual_good["qualified"] is True
