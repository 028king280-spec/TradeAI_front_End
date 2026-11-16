"""
Transparent 100-Point Analysis Scorecard Engine (ICT + SMC).
Implements the institutional quantitative scoring model across 6 distinct pillars:
1. Higher-Timeframe Alignment: 20 points
2. Market Structure (BOS / CHoCH / MSS): 20 points
3. Liquidity Confirmation (Sweeps / Grabs): 20 points
4. Displacement & Momentum: 15 points
5. FVG & Order Block Quality: 15 points
6. Risk-to-Reward Ratio (>= 1:2.0): 10 points
Total: 100 points

Important Disclaimer:
This scorecard is a configurable quantitative heuristic to enforce disciplined trade selection.
It does NOT represent a statistically guaranteed probability of winning.
"""

from typing import Dict, Any, List, Optional


class AnalysisScorecardEngine:
    """
    Computes a transparent, auditable 100-point institutional setup score.
    """

    DEFAULT_WEIGHTS = {
        "htf_alignment": 20,
        "market_structure": 20,
        "liquidity_confirmation": 20,
        "displacement": 15,
        "fvg_order_block": 15,
        "risk_to_reward": 10,
    }

    @classmethod
    def calculate_scorecard(
        cls,
        htf_score_pct: float,        # 0.0 to 1.0
        structure_score_pct: float,  # 0.0 to 1.0
        liquidity_score_pct: float,  # 0.0 to 1.0
        displacement_score_pct: float, # 0.0 to 1.0
        fvg_ob_score_pct: float,     # 0.0 to 1.0
        rr_score_pct: float,         # 0.0 to 1.0
        conflicting_signals: Optional[List[str]] = None,
        weights: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        w = weights or cls.DEFAULT_WEIGHTS

        s_htf = round(htf_score_pct * w["htf_alignment"], 1)
        s_struct = round(structure_score_pct * w["market_structure"], 1)
        s_liq = round(liquidity_score_pct * w["liquidity_confirmation"], 1)
        s_disp = round(displacement_score_pct * w["displacement"], 1)
        s_fvg = round(fvg_ob_score_pct * w["fvg_order_block"], 1)
        s_rr = round(rr_score_pct * w["risk_to_reward"], 1)

        total_score = round(s_htf + s_struct + s_liq + s_disp + s_fvg + s_rr, 1)

        missing_confirmations = []
        if htf_score_pct < 0.6:
            missing_confirmations.append("Higher-timeframe (Daily/1H) trend confirmation missing.")
        if structure_score_pct < 0.6:
            missing_confirmations.append("Clean Market Structure Shift (MSS) or BOS not fully confirmed.")
        if liquidity_score_pct < 0.6:
            missing_confirmations.append("Decisive Liquidity Sweep with Reclaim has not occurred.")
        if displacement_score_pct < 0.6:
            missing_confirmations.append("Lacks high-conviction displacement candle expansion.")
        if fvg_ob_score_pct < 0.6:
            missing_confirmations.append("Unmitigated FVG or Order Block zone not tapped.")
        if rr_score_pct < 0.6:
            missing_confirmations.append("Risk-to-Reward ratio does not meet 1:2.0 minimum threshold.")

        conflicts = conflicting_signals or []

        # Determine setup conviction grade
        if total_score >= 82 and not conflicts:
            conviction = "HIGH_CONVICTION_INSTITUTIONAL"
            recommendation = "All primary institutional criteria satisfied. Suitable for execution with standard position sizing."
        elif total_score >= 65 and len(conflicts) <= 1:
            conviction = "MODERATE_CONVICTION"
            recommendation = "Meets minimum confluence threshold. Consider half-size scaling and wait for 5M candle trigger close."
        elif total_score >= 50:
            conviction = "WEAK_WATCHLIST"
            recommendation = "Sub-optimal confluence. High risk of false breakout or chop. Await further structural development."
        else:
            conviction = "NO_TRADE_DISQUALIFIED"
            recommendation = "Disqualified setup. Trade parameters do not provide positive expected value."

        factors = [
            {"factor": "Higher-Timeframe Alignment", "score": s_htf, "maxScore": w["htf_alignment"], "status": "PASS" if htf_score_pct >= 0.7 else ("PARTIAL" if htf_score_pct >= 0.4 else "FAIL")},
            {"factor": "Market Structure (BOS/CHoCH)", "score": s_struct, "maxScore": w["market_structure"], "status": "PASS" if structure_score_pct >= 0.7 else ("PARTIAL" if structure_score_pct >= 0.4 else "FAIL")},
            {"factor": "Liquidity Confirmation (Sweeps)", "score": s_liq, "maxScore": w["liquidity_confirmation"], "status": "PASS" if liquidity_score_pct >= 0.7 else ("PARTIAL" if liquidity_score_pct >= 0.4 else "FAIL")},
            {"factor": "Displacement & Momentum", "score": s_disp, "maxScore": w["displacement"], "status": "PASS" if displacement_score_pct >= 0.7 else ("PARTIAL" if displacement_score_pct >= 0.4 else "FAIL")},
            {"factor": "FVG & Order Block Quality", "score": s_fvg, "maxScore": w["fvg_order_block"], "status": "PASS" if fvg_ob_score_pct >= 0.7 else ("PARTIAL" if fvg_ob_score_pct >= 0.4 else "FAIL")},
            {"factor": "Risk-to-Reward Ratio (>= 1:2)", "score": s_rr, "maxScore": w["risk_to_reward"], "status": "PASS" if rr_score_pct >= 0.7 else ("PARTIAL" if rr_score_pct >= 0.4 else "FAIL")},
        ]

        return {
            "overallScore": total_score,
            "maxPossibleScore": 100,
            "convictionGrade": conviction,
            "recommendation": recommendation,
            "factors": factors,
            "missingConfirmations": missing_confirmations,
            "conflictingSignals": conflicts,
            "isTradeable": total_score >= 65 and not conflicts,
            "disclaimer": "This score is a configurable heuristic, not a statistically validated probability of winning.",
        }
