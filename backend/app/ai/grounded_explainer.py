import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import httpx
from app.core.config import settings
from app.core.logging import logger


SYSTEM_PROMPT = """You are an institutional analysis explanation assistant for AIVOLVE Trading AI.
CRITICAL MANDATE:
1. You must NEVER invent prices, indicators, targets, probabilities, or market facts.
2. All numbers must strictly match the supplied structured evidence package.
3. Distinguish clearly between:
   - LIVE MARKET DATA (factual prices, OHLCV, indicators)
   - QUANT & MODEL ESTIMATES (probabilities, expected ranges, scenario levels)
   - DOCUMENT KNOWLEDGE (trading literature, educational citations)
4. Return ONLY valid JSON matching the requested schema.
"""


class GroundedAIExplainer:
    """
    Knowledge-aware grounded AI explanation synthesizer.
    Builds an audited evidence package and generates structured insights
    without hallucinating numerical calculations.
    """

    @classmethod
    async def explain(
        cls,
        symbol: str,
        company_name: str,
        current_price: float,
        trend: str,
        score: int,
        technical: Dict[str, Any],
        expected_range: Dict[str, Any],
        probabilities: Dict[str, int],
        market_context: Dict[str, Any],
        sector_analysis: Dict[str, Any],
        scenarios: Dict[str, Any],
        rag_chunks: Optional[List[Dict[str, Any]]] = None,
        ml_model_version: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Synthesizes structured evidence package and generates AIInsight JSON.
        """
        # 1. Build structured evidence package
        evidence_package = {
            "symbol": symbol,
            "companyName": company_name,
            "currentPrice": current_price,
            "trend": trend,
            "quantitativeScore": score,
            "technicalIndicators": technical,
            "expectedRange": expected_range,
            "probabilities": probabilities,
            "marketContext": market_context,
            "sectorAnalysis": sector_analysis,
            "retrievedKnowledge": [
                {
                    "source": c.get("fileName"),
                    "page": c.get("pageNumber"),
                    "text": c.get("chunkText")[:200]
                }
                for c in (rag_chunks or [])[:3]
            ],
            "mlModelVersion": ml_model_version or "Quant-Rule-Engine-v1.2",
        }

        # 2. If external AI API Key is provided, call LLM (Arcee AI or Gemini)
        if settings.AI_PROVIDER == "arcee" and settings.ARCEE_API_KEY:
            try:
                explanation_json = await cls._call_arcee(evidence_package)
                if explanation_json:
                    return explanation_json
            except Exception as e:
                logger.error(f"Arcee AI LLM call failed, falling back to grounded rule synthesizer: {e}")
        elif settings.AI_API_KEY and settings.AI_PROVIDER == "gemini":
            try:
                explanation_json = await cls._call_gemini(evidence_package)
                if explanation_json:
                    return explanation_json
            except Exception as e:
                logger.error(f"External LLM call failed, falling back to grounded rule synthesizer: {e}")

        # 3. Grounded Deterministic Synthesizer
        return cls._generate_grounded_fallback(evidence_package, scenarios)

    @classmethod
    def _generate_grounded_fallback(
        cls,
        evidence: Dict[str, Any],
        scenarios: Dict[str, Any]
    ) -> Dict[str, Any]:
        symbol = evidence["symbol"]
        company = evidence["companyName"]
        price = evidence["currentPrice"]
        trend = evidence["trend"]
        score = evidence["quantitativeScore"]
        probs = evidence["probabilities"]
        exp_range = evidence["expectedRange"]["expectedHigh"]
        tech = evidence["technicalIndicators"]
        mkt = evidence["marketContext"]
        sec = evidence["sectorAnalysis"]

        rsi_val = tech.get("rsi", {}).get("currentValue", 50)
        vwap_val = tech.get("vwap", {}).get("currentValue", price)
        mkt_bias = mkt.get("bias") or mkt.get("marketBias", "NEUTRAL")
        exp_range = evidence.get("expectedRange", {}).get("expectedHigh") or evidence.get("expectedRange", {}).get("expected_high", {"min": round(price * 1.01, 2), "max": round(price * 1.02, 2)})

        sec_name = sec.get("sectorName", "Diversified")
        sec_trend = sec.get("sectorTrend", "Neutral")
        stock_vs_sec = sec.get("stockVsSector", "aligned with sector")
        mkt_status = mkt.get("status", "Neutral")
        breadth_desc = f"{mkt.get('breadthRatio', 1.2)}:1 A/D" if mkt.get("breadthRatio") else "healthy"

        # Headline
        if trend == "Bullish":
            headline = f"Why is {symbol} showing strong bullish momentum above ₹{vwap_val}?"
            core_explanation = (
                f"{company} ({symbol}) is demonstrating clear bullish structure with a quantitative score of {score}/100. "
                f"Trading above its dynamic VWAP of ₹{vwap_val} with an RSI of {rsi_val}, the setup maintains an estimated "
                f"{probs['upside']}% upside probability targeting the ₹{exp_range['min']} – ₹{exp_range['max']} resistance band. "
                f"Sector alignment in {sec_name} ({stock_vs_sec}) and {str(mkt_bias).lower()} broader market context "
                f"provide directional confluence."
            )
        else:
            headline = f"What key support levels is {symbol} testing near ₹{price}?"
            core_explanation = (
                f"{company} ({symbol}) exhibits cautious consolidation with an analysis score of {score}/100. "
                f"With price trading near dynamic equilibrium (VWAP ₹{vwap_val}, RSI {rsi_val}), the setup indicates "
                f"{probs['downside']}% downside risk against {probs['upside']}% upside recovery probability. "
                f"Patience is advised until a clear reclaim of overhead moving averages is established."
            )

        # Qualification Pillars
        pillars = [
            {
                "pillar": "Trend Confluence",
                "status": "Confirmed" if trend == "Bullish" else "Neutral",
                "explanation": f"Price is {'above' if price >= vwap_val else 'near'} key volume-weighted benchmark (₹{vwap_val}).",
            },
            {
                "pillar": "Momentum Health",
                "status": "Positive" if float(str(rsi_val).split('/')[0]) >= 55 else "Neutral",
                "explanation": f"RSI (14) at {rsi_val} reflects {'favorable buyer participation' if float(str(rsi_val).split('/')[0]) >= 55 else 'equilibrium'}.",
            },
            {
                "pillar": "Sector Confluence",
                "status": "Confirmed" if sec.get("relative_strength") in ["Strong", "Moderate"] else "Neutral",
                "explanation": f"{sec_name} sector is {str(sec_trend).lower()}; stock {str(stock_vs_sec).lower()}.",
            },
            {
                "pillar": "Macro Support",
                "status": "Positive" if mkt_bias == "BULLISH" else "Neutral",
                "explanation": f"Broader market status is {str(mkt_status).lower()} with {breadth_desc} breadth.",
            },
        ]


        # Citations
        citations = []
        for doc in evidence.get("retrievedKnowledge", []):
            citations.append({
                "document": doc.get("source"),
                "page": doc.get("page"),
                "excerpt": doc.get("text"),
            })

        scenario_list = [
            scenarios.get("bullishScenario"),
            scenarios.get("baseScenario"),
            scenarios.get("bearishScenario"),
        ]

        return {
            "symbol": symbol,
            "headlineQuestion": headline,
            "explanation": core_explanation,
            "qualificationPillars": pillars,
            "risks": scenarios.get("outlookChanges", {}).get("risks", [
                "Macro geopolitical volatility spikes expanding India VIX",
                "Failure to hold immediate support level on lower timeframe closes",
            ]),
            "invalidationTriggers": [
                scenarios.get("bullishScenario", {}).get("invalidation", "Loss of immediate support shelf"),
                scenarios.get("bearishScenario", {}).get("invalidation", "Sustained breakout above resistance"),
            ],
            "scenarios": scenario_list,
            "aiConfidence": {
                "score": score,
                "level": "High" if score >= 80 else ("Medium" if score >= 65 else "Low"),
                "note": f"Quantitative score derived from {len(pillars)} confirmed analytical pillars and {evidence['mlModelVersion']}.",
            },
            "citations": citations,
        }

    @classmethod
    async def _call_gemini(cls, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.AI_MODEL}:generateContent?key={settings.AI_API_KEY}"
        user_prompt = f"Explain the following structured market analysis evidence package without inventing any numbers:\n{json.dumps(evidence, indent=2)}"

        payload = {
            "contents": [{"parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "generationConfig": {"temperature": settings.AI_TEMPERATURE, "responseMimeType": "application/json"}
        }

        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.post(url, json=payload)
            if res.status_code == 200:
                raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(raw_text)
        return None

    @classmethod
    async def _call_arcee(cls, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from app.ai.arcee_client import ArceeAIClient
        user_prompt = f"Explain the following structured market analysis evidence package without inventing any numbers:\n{json.dumps(evidence, indent=2)}"
        
        res = await ArceeAIClient.chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model=settings.ARCEE_MODEL,
            temperature=settings.AI_TEMPERATURE
        )

        if res.get("success") and res.get("content"):
            try:
                return json.loads(res["content"])
            except Exception:
                # If content is text, wrap into explanation format
                return {
                    "symbol": evidence["symbol"],
                    "headlineQuestion": f"Why is {evidence['symbol']} highlighted by AIVOLVE AI?",
                    "explanation": res["content"],
                    "qualificationPillars": [],
                    "risks": ["Volatility in broader indices"],
                    "invalidationTriggers": ["Key support loss"],
                    "scenarios": [],
                    "aiConfidence": {"score": evidence["quantitativeScore"], "level": "High", "note": "Powered by Arcee AI"},
                    "citations": []
                }
        return None
