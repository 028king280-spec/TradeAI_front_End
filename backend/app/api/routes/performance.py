"""
AIVOLVE Daily Performance & Accuracy Engine.
Provides comprehensive, institutional daily audit metrics with transparent denominators:
1. Entry Trigger Rate: triggered / eligible setup-ready
2. Target Hit Rates (T1, T2, T3): hits / eligible entries
3. Stop-Loss Rate: SL hits / eligible entries
4. Final Win Rate: profitable / eligible resolved paper setups
5. Directional Accuracy: target reached in defined horizon
6. Net Paper Expectancy: average net paper INR per eligible setup

Never combines or hides MISSED, EXPIRED, CANCELLED, UNRESOLVED, DATA_GAP, or AMBIGUOUS.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, case
import io
import csv

from app.db.database import get_db
from app.models.db_models import SignalRecord, SignalEventRecord, PerformanceSnapshotRecord
from app.schemas.market import ApiResponse
from app.data.market_calendar import MarketCalendar

router = APIRouter(prefix="/performance", tags=["Performance & Daily Audit"])


def format_duration(seconds: float) -> str:
    """Formats elapsed seconds into a readable string like '14m 20s' or '1h 12m'."""
    if seconds <= 0:
        return "N/A"
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    sec = total_sec % 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


@router.get("/daily")
async def get_daily_performance(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format (defaults to current trading date)"),
    symbol: Optional[str] = Query(None, description="Filter by underlying (e.g. NIFTY 50, SENSEX, BANK NIFTY)"),
    option_type: Optional[str] = Query(None, description="Filter by CE or PE"),
    strategy_version: Optional[str] = Query(None, description="Filter by strategy version"),
    session: AsyncSession = Depends(get_db),
):
    """
    Returns granular performance audit for a specific day with transparent denominators.
    Every percentage is accompanied by its explicit numerator and denominator.
    """
    # Parse target date
    if not date:
        date_str = MarketCalendar.now_ist().strftime("%Y-%m-%d")
    else:
        date_str = date

    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    start_dt = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=1)

    # Query signals created on this date
    q = select(SignalRecord).where(
        SignalRecord.created_at >= start_dt,
        SignalRecord.created_at < end_dt,
    )
    if symbol:
        q = q.where(SignalRecord.symbol == symbol)
    if option_type:
        q = q.where(SignalRecord.option_type == option_type.upper())
    if strategy_version:
        q = q.where(SignalRecord.strategy_version == strategy_version)

    q = q.order_by(SignalRecord.created_at)
    res = await session.execute(q)
    signals = res.scalars().all()

    # Calculate metrics with transparent denominators
    total_signals = len(signals)
    call_signals = sum(1 for s in signals if s.option_type == "CE")
    put_signals = sum(1 for s in signals if s.option_type == "PE")

    # Categories
    eligible_setup_ready = total_signals  # Denominator for Entry Trigger Rate
    triggered_entries = sum(1 for s in signals if s.entry_triggered_at is not None or s.status in [
        "ACTIVE", "TARGET_1_HIT", "TARGET_2_HIT", "TARGET_3_HIT", "STOP_LOSS_HIT", "CLOSED_EOD"
    ])
    missed_setups = sum(1 for s in signals if s.status == "MISSED" or s.final_outcome == "MISSED_GAP_UP")
    expired_without_entry = sum(1 for s in signals if s.status == "EXPIRED" and not s.entry_triggered_at)
    cancelled_setups = sum(1 for s in signals if s.status == "CANCELLED")
    data_gap_setups = sum(1 for s in signals if s.status == "DATA_GAP")
    ambiguous_setups = sum(1 for s in signals if s.status == "AMBIGUOUS")
    unresolved_signals = sum(1 for s in signals if s.status in ["WAITING_FOR_ENTRY", "ACTIVE"])

    # Outcome counts among triggered entries (Denominator = triggered_entries)
    t1_hits = sum(1 for s in signals if s.status in ["TARGET_1_HIT", "TARGET_2_HIT", "TARGET_3_HIT"] or s.final_outcome in ["WIN_T1", "WIN_T2", "WIN_T3"])
    t2_hits = sum(1 for s in signals if s.status in ["TARGET_2_HIT", "TARGET_3_HIT"] or s.final_outcome in ["WIN_T2", "WIN_T3"])
    t3_hits = sum(1 for s in signals if s.status == "TARGET_3_HIT" or s.final_outcome == "WIN_T3")
    sl_hits = sum(1 for s in signals if s.status == "STOP_LOSS_HIT" or s.final_outcome in ["LOSS_SL", "SL_AFTER_PARTIAL_PROFIT"])
    sl_before_target = sum(1 for s in signals if s.final_outcome == "LOSS_SL")
    sl_after_partial = sum(1 for s in signals if s.final_outcome == "SL_AFTER_PARTIAL_PROFIT")

    # Resolved paper setups (profitable vs loss)
    resolved_setups = [s for s in signals if s.status in ["TARGET_1_HIT", "TARGET_2_HIT", "TARGET_3_HIT", "STOP_LOSS_HIT", "CLOSED_EOD"] and s.entry_triggered_at]
    profitable_setups = sum(1 for s in resolved_setups if s.net_pnl_inr > 0)
    loss_setups = sum(1 for s in resolved_setups if s.net_pnl_inr < 0)

    # Financial sums
    gross_paper_pnl = round(sum(s.gross_pnl_points * s.lot_size * s.allocated_lots for s in signals), 2)
    net_paper_pnl = round(sum(s.net_pnl_inr for s in signals), 2)

    # Durations from events
    t1_seconds: List[float] = []
    t2_seconds: List[float] = []
    t3_seconds: List[float] = []
    sl_seconds: List[float] = []

    for s in signals:
        for ev in (s.events or []):
            if ev.elapsed_seconds_from_entry is not None:
                if ev.event_type == "T1_HIT":
                    t1_seconds.append(ev.elapsed_seconds_from_entry)
                elif ev.event_type == "T2_HIT":
                    t2_seconds.append(ev.elapsed_seconds_from_entry)
                elif ev.event_type == "T3_HIT":
                    t3_seconds.append(ev.elapsed_seconds_from_entry)
                elif ev.event_type == "STOP_LOSS_HIT":
                    sl_seconds.append(ev.elapsed_seconds_from_entry)

    avg_t1_sec = sum(t1_seconds) / len(t1_seconds) if t1_seconds else 0.0
    median_t1_sec = sorted(t1_seconds)[len(t1_seconds) // 2] if t1_seconds else 0.0
    avg_t2_sec = sum(t2_seconds) / len(t2_seconds) if t2_seconds else 0.0
    avg_t3_sec = sum(t3_seconds) / len(t3_seconds) if t3_seconds else 0.0
    avg_sl_sec = sum(sl_seconds) / len(sl_seconds) if sl_seconds else 0.0

    # 1. Entry Trigger Rate: triggered / eligible setup-ready
    entry_trigger_pct = round((triggered_entries / eligible_setup_ready * 100.0), 1) if eligible_setup_ready > 0 else 0.0
    entry_trigger_desc = f"{entry_trigger_pct}% — {triggered_entries} triggered out of {eligible_setup_ready} eligible setups" if eligible_setup_ready > 0 else "Insufficient data"

    # 2. Target 1 Hit Rate: T1 hit / triggered entries
    t1_rate_pct = round((t1_hits / triggered_entries * 100.0), 1) if triggered_entries > 0 else 0.0
    t1_rate_desc = f"{t1_rate_pct}% — {t1_hits} reached T1 out of {triggered_entries} triggered entries" if triggered_entries > 0 else "Insufficient triggered data"

    # 3. Target 2 Hit Rate: T2 hit / triggered entries
    t2_rate_pct = round((t2_hits / triggered_entries * 100.0), 1) if triggered_entries > 0 else 0.0
    t2_rate_desc = f"{t2_rate_pct}% — {t2_hits} reached T2 out of {triggered_entries} triggered entries" if triggered_entries > 0 else "Insufficient triggered data"

    # 4. Target 3 Hit Rate: T3 hit / triggered entries
    t3_rate_pct = round((t3_hits / triggered_entries * 100.0), 1) if triggered_entries > 0 else 0.0
    t3_rate_desc = f"{t3_rate_pct}% — {t3_hits} reached T3 out of {triggered_entries} triggered entries" if triggered_entries > 0 else "Insufficient triggered data"

    # 5. Stop-Loss Rate: SL hit / triggered entries
    sl_rate_pct = round((sl_hits / triggered_entries * 100.0), 1) if triggered_entries > 0 else 0.0
    sl_rate_desc = f"{sl_rate_pct}% — {sl_hits} hit stop-loss ({sl_after_partial} after partial profit) out of {triggered_entries} triggered entries" if triggered_entries > 0 else "Insufficient triggered data"

    # 6. Final Win Rate: profitable / resolved paper setups
    resolved_count = len(resolved_setups)
    win_rate_pct = round((profitable_setups / resolved_count * 100.0), 1) if resolved_count > 0 else 0.0
    win_rate_desc = f"{win_rate_pct}% — {profitable_setups} profitable outcomes out of {resolved_count} eligible resolved paper setups" if resolved_count > 0 else "Insufficient resolved data"

    # 7. Directional Accuracy (Target 1 achieved in session)
    directional_pct = round((t1_hits / triggered_entries * 100.0), 1) if triggered_entries > 0 else 0.0
    directional_desc = f"{directional_pct}% — {t1_hits} target hits within session horizon out of {triggered_entries} triggered setups" if triggered_entries > 0 else "Insufficient resolved data"

    # 8. Net Paper Expectancy
    expectancy_inr = round(net_paper_pnl / triggered_entries, 2) if triggered_entries > 0 else 0.0
    expectancy_desc = f"₹{expectancy_inr:+.2f} per triggered paper setup (after ₹40 brokerage & 0.05% slippage)" if triggered_entries > 0 else "Insufficient data"

    # Data Quality Warnings
    warnings: List[str] = []
    if data_gap_setups > 0:
        warnings.append(f"{data_gap_setups} signal(s) affected by market data feed interruptions exceeding 180 seconds.")
    if ambiguous_setups > 0:
        warnings.append(f"{ambiguous_setups} signal(s) flagged as ambiguous due to intra-candle target and stop-loss touch.")
    if total_signals == 0:
        warnings.append("No signals generated for selected date or filter parameters.")

    return ApiResponse(
        success=True,
        data={
            "date": date_str,
            "filterScope": {
                "symbol": symbol or "ALL_INDICES",
                "optionType": option_type or "ALL_TYPES",
                "strategyVersion": strategy_version or "ALL_VERSIONS",
            },
            "counts": {
                "totalSignals": total_signals,
                "callSignals": call_signals,
                "putSignals": put_signals,
                "triggeredEntries": triggered_entries,
                "missedSetups": missed_setups,
                "expiredWithoutEntry": expired_without_entry,
                "cancelledSetups": cancelled_setups,
                "unresolvedSignals": unresolved_signals,
                "dataGapSetups": data_gap_setups,
                "ambiguousSetups": ambiguous_setups,
                "t1Hits": t1_hits,
                "t2Hits": t2_hits,
                "t3Hits": t3_hits,
                "slHitsTotal": sl_hits,
                "slHitsBeforeTarget": sl_before_target,
                "slHitsAfterPartialTarget": sl_after_partial,
                "profitableResolved": profitable_setups,
                "lossResolved": loss_setups,
                "totalResolved": resolved_count,
            },
            "metricsWithDenominators": {
                "entryTriggerRate": {
                    "rate": entry_trigger_pct,
                    "numerator": triggered_entries,
                    "denominator": eligible_setup_ready,
                    "formatted": entry_trigger_desc,
                },
                "target1HitRate": {
                    "rate": t1_rate_pct,
                    "numerator": t1_hits,
                    "denominator": triggered_entries,
                    "formatted": t1_rate_desc,
                },
                "target2HitRate": {
                    "rate": t2_rate_pct,
                    "numerator": t2_hits,
                    "denominator": triggered_entries,
                    "formatted": t2_rate_desc,
                },
                "target3HitRate": {
                    "rate": t3_rate_pct,
                    "numerator": t3_hits,
                    "denominator": triggered_entries,
                    "formatted": t3_rate_desc,
                },
                "stopLossRate": {
                    "rate": sl_rate_pct,
                    "numerator": sl_hits,
                    "denominator": triggered_entries,
                    "formatted": sl_rate_desc,
                },
                "finalWinRate": {
                    "rate": win_rate_pct,
                    "numerator": profitable_setups,
                    "denominator": resolved_count,
                    "formatted": win_rate_desc,
                },
                "directionalAccuracy": {
                    "rate": directional_pct,
                    "numerator": t1_hits,
                    "denominator": triggered_entries,
                    "formatted": directional_desc,
                },
                "netPaperExpectancy": {
                    "inr": expectancy_inr,
                    "formatted": expectancy_desc,
                },
            },
            "financialPerformance": {
                "grossPaperPnLPoints": gross_paper_pnl,
                "netPaperPnLINR": net_paper_pnl,
                "brokerageDeductedINR": round(triggered_entries * 40.0, 2),
                "frictionAssumptions": "₹40 roundtrip brokerage + 0.05% slippage on premium",
            },
            "timings": {
                "avgTimeToT1": format_duration(avg_t1_sec),
                "avgTimeToT1Seconds": round(avg_t1_sec, 1),
                "medianTimeToT1": format_duration(median_t1_sec),
                "medianTimeToT1Seconds": round(median_t1_sec, 1),
                "avgTimeToT2": format_duration(avg_t2_sec),
                "avgTimeToT3": format_duration(avg_t3_sec),
                "avgTimeToStopLoss": format_duration(avg_sl_sec),
                "avgTimeToStopLossSeconds": round(avg_sl_sec, 1),
            },
            "dataQualityWarnings": warnings,
            "signalsList": [
                {
                    "id": s.id,
                    "symbol": s.symbol,
                    "contractSymbol": s.contract_symbol,
                    "optionType": s.option_type,
                    "strike": s.strike,
                    "expiry": s.expiry,
                    "status": s.status,
                    "finalOutcome": s.final_outcome,
                    "signalPremium": s.signal_premium,
                    "entryObservedPrice": s.entry_observed_price,
                    "stopLossPremium": s.stop_loss_premium,
                    "target1Premium": s.target_1_premium,
                    "target2Premium": s.target_2_premium,
                    "target3Premium": s.target_3_premium,
                    "netPnlInr": s.net_pnl_inr,
                    "createdAt": MarketCalendar.to_ist_str(s.created_at) if s.created_at else "",
                    "entryTriggeredAt": MarketCalendar.to_ist_str(s.entry_triggered_at) if s.entry_triggered_at else None,
                    "closedAt": MarketCalendar.to_ist_str(s.closed_at) if s.closed_at else None,
                }
                for s in signals
            ],
            "timestamp": MarketCalendar.format_ist_timestamp(),
        },
        dataStatus="LIVE",
    )


@router.get("/history")
async def get_performance_history(
    days: int = Query(30, ge=1, le=180, description="Number of historical days to summarize"),
    session: AsyncSession = Depends(get_db),
):
    """
    Returns high-level daily summary table for historical date browsing.
    """
    # Fetch distinct dates with signals
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=days)

    q = select(
        func.date(SignalRecord.created_at).label("signal_date"),
        func.count(SignalRecord.id).label("total"),
        func.sum(case((SignalRecord.option_type == "CE", 1), else_=0)).label("calls"),
        func.sum(case((SignalRecord.option_type == "PE", 1), else_=0)).label("puts"),
        func.sum(case((SignalRecord.entry_triggered_at != None, 1), else_=0)).label("triggered"),
        func.sum(case((SignalRecord.status.in_(["TARGET_1_HIT", "TARGET_2_HIT", "TARGET_3_HIT"]), 1), else_=0)).label("t1_hits"),
        func.sum(case((SignalRecord.status == "STOP_LOSS_HIT", 1), else_=0)).label("sl_hits"),
        func.sum(case((SignalRecord.net_pnl_inr > 0, 1), else_=0)).label("wins"),
        func.sum(SignalRecord.net_pnl_inr).label("total_net_pnl"),
    ).where(SignalRecord.created_at >= cutoff).group_by(func.date(SignalRecord.created_at)).order_by(desc("signal_date"))

    res = await session.execute(q)
    rows = res.all()

    summary_list = []
    for r in rows:
        d_str = str(r.signal_date)
        tot = r.total or 0
        trig = r.triggered or 0
        t1 = r.t1_hits or 0
        sl = r.sl_hits or 0
        wins = r.wins or 0
        pnl = round(float(r.total_net_pnl or 0.0), 2)

        win_rate = f"{round((wins / trig * 100.0), 1)}% ({wins}/{trig})" if trig > 0 else "N/A"
        t1_rate = f"{round((t1 / trig * 100.0), 1)}% ({t1}/{trig})" if trig > 0 else "N/A"
        sl_rate = f"{round((sl / trig * 100.0), 1)}% ({sl}/{trig})" if trig > 0 else "N/A"

        summary_list.append({
            "date": d_str,
            "totalSignals": tot,
            "calls": r.calls or 0,
            "puts": r.puts or 0,
            "triggeredEntries": trig,
            "t1Hits": t1,
            "slHits": sl,
            "t1HitRate": t1_rate,
            "finalWinRate": win_rate,
            "stopLossRate": sl_rate,
            "netPaperPnLINR": pnl,
        })

    return ApiResponse(
        success=True,
        data={
            "daysCount": len(summary_list),
            "history": summary_list,
        },
        dataStatus="LIVE",
    )


@router.get("/export")
async def export_daily_performance_csv(
    date: str = Query(..., description="Date to export in YYYY-MM-DD format"),
    session: AsyncSession = Depends(get_db),
):
    """
    Exports full daily signal audit log to CSV format.
    """
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    start_dt = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=1)

    q = select(SignalRecord).where(
        SignalRecord.created_at >= start_dt,
        SignalRecord.created_at < end_dt,
    ).order_by(SignalRecord.created_at)

    res = await session.execute(q)
    signals = res.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Signal ID",
        "Date",
        "Index",
        "Contract Symbol",
        "Type",
        "Strike",
        "Expiry",
        "Status",
        "Final Outcome",
        "Observed Signal Premium (INR)",
        "Entry Zone Min (INR)",
        "Entry Zone Max (INR)",
        "Observed Entry Price (INR)",
        "Stop Loss (INR)",
        "Target 1 (INR)",
        "Target 2 (INR)",
        "Target 3 (INR)",
        "Net Paper PnL (INR)",
        "Gross Points",
        "Lot Size",
        "Created At (IST)",
        "Entry Triggered At (IST)",
        "Closed At (IST)",
        "Strategy Version",
    ])

    for s in signals:
        writer.writerow([
            s.id,
            date,
            s.symbol,
            s.contract_symbol,
            s.option_type,
            s.strike,
            s.expiry,
            s.status,
            s.final_outcome or "UNRESOLVED",
            s.signal_premium,
            s.entry_zone_min,
            s.entry_zone_max,
            s.entry_observed_price or "",
            s.stop_loss_premium,
            s.target_1_premium,
            s.target_2_premium,
            s.target_3_premium,
            s.net_pnl_inr,
            s.gross_pnl_points,
            s.lot_size,
            MarketCalendar.to_ist_str(s.created_at) if s.created_at else "",
            MarketCalendar.to_ist_str(s.entry_triggered_at) if s.entry_triggered_at else "",
            MarketCalendar.to_ist_str(s.closed_at) if s.closed_at else "",
            s.strategy_version,
        ])

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=aivolve_signals_{date}.csv"}
    )
