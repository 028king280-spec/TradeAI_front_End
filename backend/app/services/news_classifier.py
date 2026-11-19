"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
AI News Sentiment & Financial Event Impact Classifier.

Performs deterministic institutional event categorization and sentiment classification for Indian equities.
Outputs:
- NEWS_SENTIMENT_POLARITY: -100 to +100 (Negative to Positive Directional Bias)
- NEWS_IMPACT_SCORE: 0 to 100 (Event Materiality & Market Moving Potential)
- CLASSIFICATION_CONFIDENCE: 0.0 to 1.0 (Certainty of Classification)
- VERIFICATION_STATUS: VERIFIED_OFFICIAL_FILING | VERIFIED_TIER1_MEDIA | FINANCIAL_MEDIA | UNVERIFIED_RUMOR
- EXPLANATION: Human-readable rationale detailing the catalyst and institutional significance.
"""

import re
from typing import Dict, Any, List, Optional, Tuple

# Tier-1 Financial Media Outlets
TIER1_SOURCES = {
    "ECONOMIC TIMES", "MONEYCONTROL", "LIVEMINT", "BUSINESS STANDARD",
    "NDTV PROFIT", "REUTERS", "BLOOMBERG", "CNBC-TV18", "ZEE BUSINESS"
}

OFFICIAL_FILING_MARKERS = [
    r"\bexchange\s*filing\b", r"\bcorporate\s*announcement\b", r"\boutcome\s*of\s*board\s*meeting\b",
    r"\bregulatory\s*filing\b", r"\bbse\s*disclosure\b", r"\bnse\s*disclosure\b"
]

RUMOR_MARKERS = [
    r"\brumours?\b", r"\bsources?\s*say\b", r"\breportedly\b", r"\bmay\s*consider\b",
    r"\blikely\s*to\b", r"\bspeculation\b", r"\btalks?\s*on\b", r"\bunconfirmed\b"
]


class NewsClassifier:
    """
    Deterministic Financial Event Classifier for Indian Stock News.
    Evaluates corporate events across 15 distinct financial taxonomy categories.
    """

    # Event Taxonomy with Regex Patterns, Base Polarity, and Base Impact
    EVENT_TAXONOMY: List[Dict[str, Any]] = [
        # POSITIVE EVENTS
        {
            "category": "EARNINGS_SURPRISE_BEAT",
            "type": "POSITIVE",
            "polarity": 85,
            "impact": 80,
            "patterns": [
                r"\b(q[1-4]|quarterly|pat|net\s*profit|profit)\s*(jumps?|surges?|zooms?|leaps?|rises?|up|soars?)\s*(by\s*)?\d+%",
                r"\bprofit\s*(beats?|tops?|surpasses?|outperforms?)\s*(estimates?|expectations?|street)\b",
                r"\brecord\s*(quarterly|annual|q[1-4])\s*(profit|pat|revenue)\b",
                r"\bmargin\s*(expansion|expands?|widens?)\b",
                r"\bturnaround\b.*\bprofits?\b",
            ],
            "template": "Earnings surprise: Net profit and operating metrics beat Street expectations with margin expansion."
        },
        {
            "category": "ORDER_WIN_LARGE_CONTRACT",
            "type": "POSITIVE",
            "polarity": 80,
            "impact": 85,
            "patterns": [
                r"\b(bags?|wins?|secures?|awarded|clinches?)\s*(order|contract|project|tender|deal)?\s*(worth|valued\s*at)?\s*(rs\.?|inr|usd|\$)?\s*\d+[\d,.]*\s*(cr|crore|billion|mn|million)\b",
                r"\b(bags?|wins?|secures?|awarded|clinches?)\s*(rs\.?|inr|usd|\$)?\s*\d+[\d,.]*\s*(cr|crore|billion|mn|million)\s*.*?(order|contract|project|deal|win)\b",
                r"\blarge\s*(order|contract|project)\s*(win|bags?|secures?)\b",
                r"\bdefense\s*(order|contract)\s*(win|bags?|secures?)\b",
                r"\brailway\s*(order|contract)\s*(win|bags?|secures?)\b",
                r"\border\s*book\s*(surges?|at\s*record|crosses?)\b",
            ],
            "template": "Major confirmed contract/order win significantly expanding commercial order book visibility."
        },
        {
            "category": "REGULATORY_APPROVAL_CLEARANCE",
            "type": "POSITIVE",
            "polarity": 75,
            "impact": 75,
            "patterns": [
                r"\b(usfda|fda|dcgi|dgca|rbi|sebi|cci)\s*(approves?|clears?|greenlights?|nod|grant|license)\b",
                r"\beir\s*(received|granted|issued)\b",
                r"\bzero\s*(483\s*)?observations?\b",
                r"\bvai\s*status\b",
                r"\bestablishment\s*inspection\s*report\s*without\s*observations?\b",
                r"\bpatent\s*(grant|granted|secured)\b",
            ],
            "template": "Key regulatory clearance/approval received from statutory governing authority."
        },
        {
            "category": "CAPACITY_EXPANSION_COMMISSIONING",
            "type": "POSITIVE",
            "polarity": 65,
            "impact": 70,
            "patterns": [
                r"\bcommissions?\s*(new\s*)?(plant|unit|facility|capacity|line)\b",
                r"\bcommercial\s*production\s*(starts?|commences?|begins?)\b",
                r"\bcapacity\s*(expansion|doubling|expansion\s*plan)\b",
                r"\bnew\s*manufacturing\s*plant\b",
            ],
            "template": "Capacity expansion or successful commercial commissioning of new production unit."
        },
        {
            "category": "DEBT_REDUCTION_DELEVERAGING",
            "type": "POSITIVE",
            "polarity": 70,
            "impact": 65,
            "patterns": [
                r"\bdebt[- ]free\b",
                r"\bpre[- ]?pays?\s*(loan|debt)\b",
                r"\bdebt\s*(reduction|cut|slashed|down)\b",
                r"\b(credit|rating)\s*(upgraded?|upgrade)\s*(to\s*[a-z+]+)?\b",
            ],
            "template": "Balance sheet deleveraging, substantial debt prepayment or credit rating upgrade."
        },
        {
            "category": "STRATEGIC_MA_PARTNERSHIP",
            "type": "POSITIVE",
            "polarity": 60,
            "impact": 65,
            "patterns": [
                r"\bacquires?\s*(stake|business|assets?|firm)\b",
                r"\bjoint\s*venture\s*(formed|pact|deal|agreement)\b",
                r"\bstrategic\s*partnership\b",
                r"\bmerger\s*(approved|cleared)\b",
            ],
            "template": "Value-accretive strategic partnership, acquisition or joint venture pact."
        },
        {
            "category": "POSITIVE_GUIDANCE_DIVIDEND",
            "type": "POSITIVE",
            "polarity": 65,
            "impact": 60,
            "patterns": [
                r"\b(raises?|upward\s*revision)\s*(guidance|target|forecast)\b",
                r"\bspecial\s*dividend\b",
                r"\bbonus\s*shares?\b",
                r"\bshare\s*buyback\b",
            ],
            "template": "Management upward guidance revision, share buyback announcement or high payout."
        },

        # NEGATIVE EVENTS
        {
            "category": "EARNINGS_DETERIORATION_MISS",
            "type": "NEGATIVE",
            "polarity": -85,
            "impact": 80,
            "patterns": [
                r"\b(q[1-4]|quarterly|pat|net\s*profit|profit)\s*(plunges?|drops?|falls?|tumbles?|slumps?|down|crashes?)\s*(by\s*)?\d+%",
                r"\bprofit\s*(misses?|lags?|below)\s*(estimates?|expectations?|street)\b",
                r"\bnet\s*loss\s*(widens?|reported|surges?)\b",
                r"\bmargin\s*(compression|contracts?|squeezed?|drags?)\b",
            ],
            "template": "Earnings miss: Net profit deterioration, loss widening or severe operational margin squeeze."
        },
        {
            "category": "FRAUD_ENFORCEMENT_PROBE",
            "type": "NEGATIVE",
            "polarity": -95,
            "impact": 95,
            "patterns": [
                r"\b(cbi|ed|sebi|sfio|income\s*tax|dgft)\s*(raid|raids|searches?|probe|investigates?|notice|summons?|chargesheet)\b",
                r"\b(auditor|cfo|ceo)\s*(resigns?|quits?)\s*(abruptly|suddenly)?\b",
                r"\bforensic\s*audit\b",
                r"\bfraud\b|\baccounting\s*irregularit(y|ies)\b|\bmisappropriation\b",
                r"\bshow\s*cause\s*notice\b",
            ],
            "template": "Severe regulatory enforcement action, financial fraud investigation or auditor abrupt resignation."
        },
        {
            "category": "REGULATORY_PENALTY_WARNING",
            "type": "NEGATIVE",
            "polarity": -80,
            "impact": 85,
            "patterns": [
                r"\bform\s*483\b.*\bobservations?\b",
                r"\b(warning\s*letter|import\s*alert|oai\s*status)\b",
                r"\b(rbi|sebi|usfda|fda)\s*(penalty|imposes?\s*penalty|bars?|bans?|restricts?)\b",
                r"\bstop[- ]work\s*order\b",
                r"\benvironmental\s*(clearance\s*revoked|penalty)\b",
            ],
            "template": "Material regulatory sanction, FDA warning letter / import alert or compliance ban."
        },
        {
            "category": "ORDER_CANCELLATION_LOSS",
            "type": "NEGATIVE",
            "polarity": -75,
            "impact": 80,
            "patterns": [
                r"\b(order|contract|project)\s*(cancellation|cancelled|terminated|scrapped)\b",
                r"\bloses?\s*(order|contract|tender)\b",
                r"\bdispute\s*over\s*(contract|payment)\b",
            ],
            "template": "Cancellation or unilateral termination of major revenue-generating commercial contract."
        },
        {
            "category": "DEBT_DISTRESS_DEFAULT",
            "type": "NEGATIVE",
            "polarity": -90,
            "impact": 90,
            "patterns": [
                r"\b(debt|loan|interest)\s*default\b",
                r"\bnclt\s*(admits?|petition|insolvency)\b",
                r"\bbankruptcy\b|\binsolvency\s*proceeding\b",
                r"\b(credit|rating)\s*(downgraded?|downgrade)\s*(to\s*[a-z+]+|junk|d)?\b",
            ],
            "template": "Acute debt distress: Debt default, NCLT insolvency proceedings or credit rating downgrade to default."
        },
        {
            "category": "ADVERSE_LITIGATION_TAX",
            "type": "NEGATIVE",
            "polarity": -70,
            "impact": 75,
            "patterns": [
                r"\btax\s*demand\s*(of\s*)?(rs\.?|inr)?\s*\d+[\d,.]*\s*(cr|crore)\b",
                r"\bsupreme\s*court\s*(upholds?|rejects?|orders?|rules?\s*against)\b",
                r"\barbitration\s*loss\b",
                r"\bpenalty\s*of\s*(rs\.?|inr)?\s*\d+[\d,.]*\s*(cr|crore)\b",
            ],
            "template": "Substantial adverse judicial ruling, major tax demand or arbitration award against the company."
        },
        {
            "category": "NEGATIVE_GUIDANCE_SLOWDOWN",
            "type": "NEGATIVE",
            "polarity": -70,
            "impact": 70,
            "patterns": [
                r"\b(lowers?|cuts?|slashes?)\s*(guidance|outlook|target|growth\s*forecast)\b",
                r"\bdemand\s*(slowdown|slump|weakness)\b",
                r"\bmargin\s*pressure\s*warning\b",
                r"\bheadwinds?\s*ahead\b",
            ],
            "template": "Management cuts forward business guidance or warns of severe macroeconomic demand slowdown."
        },
        {
            "category": "OPERATIONAL_DISRUPTION",
            "type": "NEGATIVE",
            "polarity": -75,
            "impact": 75,
            "patterns": [
                r"\bplant\s*(fire|explosion|shutdown|blast)\b",
                r"\boperations?\s*(halted|suspended|disrupted|shut\s*down)\b",
                r"\blabou?r\s*(strike|unrest)\b",
            ],
            "template": "Major operational disruption, industrial accident, strike or forced factory shutdown."
        },
    ]

    # Mild Sentiment Modifiers
    BULLISH_KEYWORDS = {
        "rally", "surge", "gain", "rise", "jump", "soar", "advance", "rebound", "upbeat", "bullish",
        "inflow", "boost", "positive", "high", "outperform", "milestone", "turnaround", "growth"
    }

    BEARISH_KEYWORDS = {
        "slump", "fall", "drop", "plunge", "decline", "tumble", "slip", "loss", "bearish", "crash",
        "weak", "deficit", "drag", "selloff", "worries", "cautious", "subdued", "headwinds"
    }

    def classify(self, headline: str, summary: str = "", source: str = "Financial Media") -> Dict[str, Any]:
        """
        Classifies an article into sentiment polarity, impact score, confidence, and explanation.
        """
        text = f"{headline} {summary}".strip()
        headline_lower = headline.lower()
        source_upper = source.upper()

        # 1. Determine Source Verification Status
        is_official = any(re.search(pat, headline_lower) for pat in OFFICIAL_FILING_MARKERS) or "EXCHANGE" in source_upper
        is_rumor = any(re.search(pat, headline_lower) for pat in RUMOR_MARKERS)
        is_tier1 = any(src in source_upper for src in TIER1_SOURCES)

        if is_official:
            verification_status = "VERIFIED_OFFICIAL_FILING"
            credibility_mult = 1.0
        elif is_rumor:
            verification_status = "UNVERIFIED_RUMOR"
            credibility_mult = 0.5
        elif is_tier1:
            verification_status = "VERIFIED_TIER1_MEDIA"
            credibility_mult = 0.9
        else:
            verification_status = "FINANCIAL_MEDIA"
            credibility_mult = 0.75

        # 2. Check for Structured Event Matches
        matched_events: List[Dict[str, Any]] = []
        for event in self.EVENT_TAXONOMY:
            for pat in event["patterns"]:
                if re.search(pat, headline_lower):
                    matched_events.append(event)
                    break

        # If a specific corporate event matched
        if matched_events:
            # Sort by impact descending
            matched_events.sort(key=lambda x: x["impact"], reverse=True)
            primary_event = matched_events[0]

            polarity = primary_event["polarity"]
            impact = primary_event["impact"]
            category = primary_event["category"]
            template_exp = primary_event["template"]
            confidence = round(0.85 * credibility_mult, 2)

            # Sentiment label
            if polarity >= 50:
                sentiment = "VERY_BULLISH"
            elif polarity >= 20:
                sentiment = "BULLISH"
            elif polarity <= -50:
                sentiment = "VERY_BEARISH"
            elif polarity <= -20:
                sentiment = "BEARISH"
            else:
                sentiment = "NEUTRAL"

            # Check if there are conflicting events (e.g. beat profit but raided)
            if len(matched_events) > 1:
                types = {e["type"] for e in matched_events}
                if len(types) > 1:
                    category = "MIXED_CONFLICTING_SIGNALS"
                    polarity = int(sum(e["polarity"] for e in matched_events) / len(matched_events))
                    sentiment = "MIXED"
                    template_exp = "Conflicting financial news: Simultaneous positive operational updates and regulatory/earnings headwinds."
                    confidence = round(0.65 * credibility_mult, 2)

            return {
                "sentiment": sentiment,
                "sentimentPolarity": polarity,
                "impactScore": impact,
                "confidence": confidence,
                "category": category,
                "verificationStatus": verification_status,
                "explanation": template_exp,
            }

        # 3. Fallback: Mild Lexical Scoring (When no specific major financial event detected)
        words = set(re.findall(r"\b[a-z]+\b", headline_lower))
        bull_matches = words & self.BULLISH_KEYWORDS
        bear_matches = words & self.BEARISH_KEYWORDS

        bull_count = len(bull_matches)
        bear_count = len(bear_matches)

        if bull_count > bear_count:
            diff = bull_count - bear_count
            polarity = min(60, 25 + diff * 15)
            impact = min(50, 20 + diff * 10)
            sentiment = "BULLISH"
            category = "POSITIVE_MOMENTUM"
            explanation = f"Positive market commentary highlighting bullish momentum ({', '.join(list(bull_matches)[:3])})."
            confidence = round(0.60 * credibility_mult, 2)
        elif bear_count > bull_count:
            diff = bear_count - bull_count
            polarity = max(-60, -25 - diff * 15)
            impact = min(50, 20 + diff * 10)
            sentiment = "BEARISH"
            category = "NEGATIVE_HEADWINDS"
            explanation = f"Cautious market commentary highlighting operational headwinds ({', '.join(list(bear_matches)[:3])})."
            confidence = round(0.60 * credibility_mult, 2)
        else:
            polarity = 0
            impact = 10
            sentiment = "NEUTRAL"
            category = "GENERAL_CORPORATE_UPDATE"
            explanation = "Routine corporate development or informational update with neutral directional impact."
            base_conf = 0.85 if is_official else (0.40 if is_rumor else 0.55)
            confidence = round(base_conf * credibility_mult, 2)

        return {
            "sentiment": sentiment,
            "sentimentPolarity": polarity,
            "impactScore": impact,
            "confidence": confidence,
            "category": category,
            "verificationStatus": verification_status,
            "explanation": explanation,
        }


# Singleton instance helper
_classifier_instance: Optional[NewsClassifier] = None

def get_news_classifier() -> NewsClassifier:
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = NewsClassifier()
    return _classifier_instance
