"""
AI-Powered Institutional Market Analysis & Standard Report Generator (ICT + SMC).
Generates:
1. 5-Part Structured AI Analysis (Overview, Structure, Liquidity, ICT, Trading Scenarios)
2. Standardized 15-Point AI Analysis Report (Exact user specification)
3. Zero Hardcoded Prices — Every price level derived from verified market data.
   If data is missing, explicitly displays 'Unavailable'.
"""

from typing import Dict, Any, List, Optional


class AIMarketExplainer:
    """
    Synthesizes multi-module ICT and SMC data into structured, institutional-grade text reports.
    """

    @classmethod
    def generate_standard_report(
        cls,
        symbol: str,
        market_bias: str,
        htf_trend: str,
        intraday_structure: str,
        liquidity_data: Dict[str, Any],
        structure_data: Dict[str, Any],
        fvg_ob_data: Dict[str, Any],
        dealing_range: Dict[str, Any],
        ce_setup: Optional[Dict[str, Any]] = None,
        pe_setup: Optional[Dict[str, Any]] = None,
        entry_trigger: Optional[str] = None,
        invalidation_conditions: Optional[str] = None,
        no_trade_conditions: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Builds both JSON structured object and formatted Markdown text.
        """
        clean_sym = symbol.upper().strip()

        # Liquidity levels formatting
        bsl_items = [f"₹{p['level']} ({p.get('name', 'BSL')})" for p in liquidity_data.get("bslPools", [])[:3]]
        ssl_items = [f"₹{p['level']} ({p.get('name', 'SSL')})" for p in liquidity_data.get("sslPools", [])[:3]]
        liq_str = f"BSL: {', '.join(bsl_items) if bsl_items else 'Unavailable'} | SSL: {', '.join(ssl_items) if ssl_items else 'Unavailable'}"

        # BOS / CHoCH
        bos_events = structure_data.get("bosChoch", {}).get("events", [])
        last_bos = structure_data.get("bosChoch", {}).get("lastBos")
        last_choch = structure_data.get("bosChoch", {}).get("lastChoch")
        bos_str = (
            f"Last BOS: {last_bos['type']} @ ₹{last_bos['brokenLevel']} ({last_bos['status']})"
            if last_bos else "No recent BOS confirmed"
        )
        if last_choch:
            bos_str += f" | Last CHoCH: {last_choch['type']} @ ₹{last_choch['brokenLevel']}"

        # FVG Zones
        fvgs = fvg_ob_data.get("fairValueGaps", [])
        fresh_fvgs = [f for f in fvgs if not f.get("isMitigated")][:2]
        fvg_str = (
            ", ".join([f"{f['type']} [₹{f['bottom']} — ₹{f['top']}] (CE: ₹{f['ce50']})" for f in fresh_fvgs])
            if fresh_fvgs else "No fresh unmitigated FVGs in immediate dealing range"
        )

        # Order Blocks
        obs = fvg_ob_data.get("orderBlocks", [])
        valid_obs = [b for b in obs if b.get("isValid")][:2]
        ob_str = (
            ", ".join([f"{b['type']} [₹{b['bottom']} — ₹{b['top']}] (Mean: ₹{b['midpoint']})" for b in valid_obs])
            if valid_obs else "No unmitigated Order Blocks in immediate proximity"
        )

        # Premium / Discount
        p_d_str = f"{dealing_range.get('regime', 'EQUILIBRIUM')} ({dealing_range.get('currentPositionPct', 50)}% of Range [₹{dealing_range.get('rangeLow', 'Unavailable')} — ₹{dealing_range.get('rangeHigh', 'Unavailable')}], 50% Eq: ₹{dealing_range.get('equilibrium', 'Unavailable')})"

        # Setups
        ce_str = (
            f"{ce_setup.get('contractSymbol', 'Unavailable')} @ ₹{ce_setup.get('currentPremium', 'Unavailable')} (SL: ₹{ce_setup.get('stopLoss', 'Unavailable')}, T1: ₹{ce_setup.get('target1', 'Unavailable')}, T2: ₹{ce_setup.get('target2', 'Unavailable')})"
            if ce_setup and ce_setup.get("target1", 0) > 0 else "Unavailable (Targets locked in sideways regime)"
        )
        pe_str = (
            f"{pe_setup.get('contractSymbol', 'Unavailable')} @ ₹{pe_setup.get('currentPremium', 'Unavailable')} (SL: ₹{pe_setup.get('stopLoss', 'Unavailable')}, T1: ₹{pe_setup.get('target1', 'Unavailable')}, T2: ₹{pe_setup.get('target2', 'Unavailable')})"
            if pe_setup and pe_setup.get("target1", 0) > 0 else "Unavailable (Targets locked in sideways regime)"
        )

        active_setup = ce_setup if market_bias == "BULLISH" else (pe_setup if market_bias == "BEARISH" else None)
        entry_conf = entry_trigger or (
            active_setup.get("underlyingTrigger") if active_setup else "Await 5-minute candle breakout outside chop range."
        )
        sl_val = f"₹{active_setup.get('stopLoss')}" if (active_setup and active_setup.get("stopLoss", 0) > 0) else "Unavailable (No Active Trade)"
        t1_val = f"₹{active_setup.get('target1')}" if (active_setup and active_setup.get("target1", 0) > 0) else "Unavailable (Targets Disabled in Chop)"
        t2_val = f"₹{active_setup.get('target2')}" if (active_setup and active_setup.get("target2", 0) > 0) else "Unavailable (Targets Disabled in Chop)"
        rr_val = active_setup.get("riskRewardRatio", "Unavailable") if (active_setup and active_setup.get("target1", 0) > 0) else "Unavailable"

        inval_str = invalidation_conditions or (
            active_setup.get("invalidationCondition") if active_setup else "Failure to break out of sideways equilibrium range."
        )
        notrade_str = no_trade_conditions or "Consolidation within 50% equilibrium; multi-timeframe conflict; high theta decay environment."

        # Exact standardized 15-point text format
        report_text = f"""==================================================
{clean_sym} MARKET ANALYSIS
==================================================
- Market Bias: {market_bias}
- Higher Timeframe Trend: {htf_trend}
- Intraday Structure: {intraday_structure}
- Important Liquidity Levels: {liq_str}
- BOS / CHoCH: {bos_str}
- FVG Zones: {fvg_str}
- Order Block Zones: {ob_str}
- Premium / Discount: {p_d_str}
- Possible CE Setup: {ce_str}
- Possible PE Setup: {pe_str}
- Entry Confirmation: {entry_conf}
- Stop Loss: {sl_val}
- Target 1: {t1_val}
- Target 2: {t2_val}
- Risk-to-Reward: {rr_val}
- Invalidation Conditions: {inval_str}
- No-Trade Conditions: {notrade_str}
=================================================="""

        # 5-Part Structured Object
        structured_analysis = {
            "marketOverview": {
                "symbol": clean_sym,
                "currentTrend": htf_trend,
                "bias": market_bias,
                "marketCondition": "TRENDING" if market_bias in ["BULLISH", "BEARISH"] else "SIDEWAYS_CHOP",
                "volatility": "MODERATE",
            },
            "structureAnalysis": {
                "structurePoints": structure_data.get("classifiedPoints", []),
                "bosEvents": bos_events,
                "structuralStrength": "HIGH" if len(bos_events) >= 2 else "MODERATE",
            },
            "liquidityAnalysis": {
                "bslPools": liquidity_data.get("bslPools", []),
                "sslPools": liquidity_data.get("sslPools", []),
                "sweeps": liquidity_data.get("sweeps", []),
            },
            "ictAnalysis": {
                "fvgZones": fresh_fvgs,
                "orderBlocks": valid_obs,
                "dealingRange": dealing_range,
            },
            "tradingScenarios": {
                "bullishScenario": f"Bullish breakout above {bsl_items[0] if bsl_items else 'Resistance'} triggering Call entry.",
                "bearishScenario": f"Bearish breakdown below {ssl_items[0] if ssl_items else 'Support'} triggering Put entry.",
                "confirmationRequired": entry_conf,
                "invalidationLevel": inval_str,
                "noTradeConditions": notrade_str,
            }
        }

        return {
            "reportText": report_text,
            "structured": structured_analysis,
        }

    @classmethod
    def generate_5part_analysis(
        cls,
        symbol: str,
        current_price: float,
        market_bias: str,
        structure_data: Dict[str, Any],
        liquidity_data: Dict[str, Any],
        sweeps: List[Dict[str, Any]],
        fvgs: List[Dict[str, Any]],
        obs: List[Dict[str, Any]],
        dealing_range: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generates 5-part institutional JSON analysis.
        """
        rep = cls.generate_standard_report(
            symbol=symbol,
            market_bias=market_bias,
            htf_trend=market_bias,
            intraday_structure=structure_data.get("summary", "Structure evaluated"),
            liquidity_data=liquidity_data,
            structure_data=structure_data,
            fvg_ob_data={"fairValueGaps": fvgs, "orderBlocks": obs},
            dealing_range=dealing_range,
        )
        return rep["structured"]
