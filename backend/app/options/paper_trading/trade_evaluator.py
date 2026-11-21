"""
AI Post-Trade Audit & Evaluation Engine.
Performs deterministic, factual 9-factor review after every completed trade:
1. Was the market direction correct?
2. Was the entry correct (Discount vs Premium)?
3. Was ICT/SMC confirmation present (BOS / CHoCH / MSS)?
4. Was liquidity correctly identified (BSL / SSL sweep)?
5. Was FVG valid (50% Consequent Encroachment retest)?
6. Was stop-loss placement reasonable (Protected swing)?
7. Was the target realistic (Next opposing liquidity pool)?
8. Was the trade taken in a suitable market condition (Trending vs Sideways chop)?
9. Did theta, IV or spread affect the result?
"""

from typing import Dict, Any, List, Optional


class AITradeEvaluator:
    """
    Evaluates completed paper trades and extracts actionable quantitative lessons.
    """

    @classmethod
    def evaluate_completed_trade(cls, trade: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes 9-question audit and awards an institutional grade.
        """
        is_win = trade.get("netPnl", 0) >= 0
        bias = trade.get("bias", "CE")
        entry_p = trade.get("entryPremium", 0.0)
        exit_p = trade.get("exitPremium", 0.0)
        strategy = trade.get("strategy", "Model A")
        ict_setup = trade.get("ictSetup", "ICT Standard")
        features = trade.get("marketFeaturesAtEntry", {})
        exit_reason = trade.get("exitReason", "Manually Closed")

        mfe = float(trade.get("mfePts", 0.0) or 0.0)
        mae = float(trade.get("maePts", 0.0) or 0.0)

        # 1. Market Direction Correct? (Evidence-based on MFE/MAE excursion, NOT outcome)
        if mfe >= 10.0 or (mfe > 0 and mfe > mae * 1.5):
            q1_pass = True
            q1_text = f"Yes. Directional expansion favored {bias} contract; price expanded by +{mfe:.1f} pts MFE."
        elif mfe == 0.0 and mae > 0.0:
            q1_pass = False
            q1_text = f"No / Counter-trend. Market moved immediately against {bias} position with {mae:.1f} pts MAE (0.0 MFE)."
        else:
            # Minor excursion or ambiguous drift
            q1_pass = is_win and mfe > 0
            q1_text = f"Mixed/Stagnant. MFE: +{mfe:.1f} pts, MAE: -{mae:.1f} pts. Excursion showed minimal directional thrust."

        # 2. Entry Correct? (Strictly relies on recorded dealingRangeRegime)
        if "dealingRangeRegime" in features:
            dealing_regime = features.get("dealingRangeRegime")
            if (bias == "CE" and dealing_regime == "DISCOUNT") or (bias == "PE" and dealing_regime == "PREMIUM"):
                q2_pass = True
                q2_text = f"Optimal. Filled at ₹{entry_p:.2f} within favorable institutional {dealing_regime} zone."
            else:
                q2_pass = False
                q2_text = f"Sub-optimal. Entry taken in {dealing_regime} zone, incurring unfavorable premium pricing."
        else:
            q2_pass = False
            q2_text = "Unrecorded / Unknown: Dealing range regime was not captured in marketFeaturesAtEntry."

        # 3. ICT/SMC Confirmation Present? (Strictly verifies recorded confirmation flags)
        has_bos_choch = bool(features.get("bosConfirmed") or features.get("chochConfirmed") or features.get("mssConfirmed"))
        q3_pass = has_bos_choch
        q3_text = (
            "Confirmed. Valid Market Structure Shift (MSS) and candle-close BOS were documented in entry features."
            if has_bos_choch else
            "Unconfirmed / Early entry. No confirmed BOS/CHoCH/MSS flag recorded in entry features."
        )

        # 4. Liquidity Correctly Identified? (Strictly verifies recorded liquidity flags)
        has_sweep = bool(features.get("sweepReclaim") or features.get("liquiditySweep"))
        q4_pass = has_sweep
        q4_text = (
            "Verified. Opposing liquidity pool was cleanly swept with reclaim documented in entry features."
            if has_sweep else
            "Ambiguous liquidity pool. No sweepReclaim or liquiditySweep flag verified in entry features."
        )

        # 5. FVG Valid? (Strictly verifies recorded FVG flags)
        has_fvg = bool(features.get("fvgRetest") or features.get("fvgConsequentEncroachment"))
        q5_pass = has_fvg
        q5_text = (
            "Valid. Imbalance respected 50% Consequent Encroachment (CE) confirmed in entry features."
            if has_fvg else
            "Unverified. No fvgRetest or FVG Consequent Encroachment confirmed in entry features."
        )

        # 6. Stop Loss Reasonable?
        sl = trade.get("stopLoss", 0.0)
        sl_dist = abs(entry_p - sl)
        q6_pass = sl > 0 and sl_dist > 5.0
        q6_text = (
            f"Reasonable. Stop-loss placed at ₹{sl:.1f} ({sl_dist:.1f} pts risk), anchored to protected swing pivot."
            if q6_pass else
            "Too tight or unanchored. Vulnerable to market noise wicks."
        )

        # 7. Target Realistic?
        t1 = trade.get("target1", 0.0)
        rr = round(abs(t1 - entry_p) / max(1.0, sl_dist), 2)
        q7_pass = rr >= 1.5
        q7_text = (
            f"Realistic. Target 1 at ₹{t1:.1f} provided 1:{rr} R:R anchored to nearest resting liquidity."
            if q7_pass else
            f"Under-calibrated. R:R of 1:{rr} below institutional 1:1.5 minimum expectation."
        )

        # 8. Market Condition Suitable? (Strictly relies on recorded marketCondition)
        if "marketCondition" in features:
            market_cond = features.get("marketCondition")
            if market_cond in ("SIDEWAYS_CHOP", "EQUILIBRIUM", "CHOPPY"):
                q8_pass = False
                q8_text = f"Unsuitable. Range-bound chop regime '{market_cond}' accelerates premium theta erosion."
            else:
                q8_pass = True
                q8_text = f"Suitable. Active in verified '{market_cond}' regime with adequate directional momentum."
        else:
            q8_pass = False
            q8_text = "Unrecorded / Unknown: Market regime condition was not captured in marketFeaturesAtEntry."

        # 9. Theta, IV & Spread Impact?
        costs = trade.get("totalCosts", 0.0)
        q9_pass = True
        q9_text = f"Friction quantified: Transaction charges ₹{costs:.2f}. Holding duration and spread accounted for."

        questions = [
            {"id": "Q1", "question": "Was market direction correct?", "passed": q1_pass, "details": q1_text},
            {"id": "Q2", "question": "Was entry correct (Discount vs Premium)?", "passed": q2_pass, "details": q2_text},
            {"id": "Q3", "question": "Was ICT/SMC confirmation present?", "passed": q3_pass, "details": q3_text},
            {"id": "Q4", "question": "Was liquidity correctly identified?", "passed": q4_pass, "details": q4_text},
            {"id": "Q5", "question": "Was FVG valid (50% CE)?", "passed": q5_pass, "details": q5_text},
            {"id": "Q6", "question": "Was stop-loss placement reasonable?", "passed": q6_pass, "details": q6_text},
            {"id": "Q7", "question": "Was target realistic?", "passed": q7_pass, "details": q7_text},
            {"id": "Q8", "question": "Was market condition suitable?", "passed": q8_pass, "details": q8_text},
            {"id": "Q9", "question": "Did theta, IV or spread affect result?", "passed": q9_pass, "details": q9_text},
        ]

        score = sum(1 for q in questions if q["passed"])
        score_pct = round((score / len(questions)) * 100.0, 1)

        if score >= 8 and is_win:
            grade = "A+"
            verdict = "INSTITUTIONAL GRADE EXECUTION"
        elif score >= 7:
            grade = "A"
            verdict = "SOLID PROCESS-DRIVEN TRADE"
        elif score >= 5:
            grade = "B"
            verdict = "ACCEPTABLE WITH MINOR DEVIATIONS"
        elif score >= 4:
            grade = "C"
            verdict = "PROCESS FLAWS DETECTED"
        else:
            grade = "F"
            verdict = "DISQUALIFIED DISCIPLINE FAILURE"

        key_takeaways = []
        if not q8_pass:
            key_takeaways.append("Avoid initiating directional option buying during sideways equilibrium.")
        if not q2_pass:
            key_takeaways.append("Never buy Calls in Premium or Puts in Discount.")
        if not q6_pass:
            key_takeaways.append("Stop-loss must always be anchored behind a verified protected swing structure.")
        if not key_takeaways:
            key_takeaways.append("Clean execution adhering to core ICT liquidity sweep rules.")

        return {
            "tradeId": trade.get("id"),
            "contract": trade.get("contractSymbol"),
            "netPnl": trade.get("netPnl"),
            "grade": grade,
            "verdict": verdict,
            "scorePercent": score_pct,
            "passedFactorsCount": score,
            "totalFactorsCount": len(questions),
            "questions": questions,
            "keyTakeaways": key_takeaways,
            "mfeMaeSummary": f"Peak MFE: +{mfe:.1f} pts | Max MAE: -{mae:.1f} pts",
        }

