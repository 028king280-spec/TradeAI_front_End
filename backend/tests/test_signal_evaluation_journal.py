from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.db_models import SignalEvaluationRecord, SignalRecord
from app.api.routes.performance import get_signal_evaluations, get_performance_history, ist_day_bounds


@pytest.mark.asyncio
async def test_ist_day_and_rejection_journal_are_separate_from_signals():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add(SignalEvaluationRecord(
                symbol="NIFTY 50", data_status="DATA_UNAVAILABLE", action="NO_TRADE",
                qualified=False, rejection_reasons=["Stale feed"], stage_status={"stage1": "FAILED"},
                evaluated_at=datetime(2026, 11, 16, 19, 0, tzinfo=timezone.utc),
            ))
            await session.commit()
            today = await get_signal_evaluations(date="2026-11-17", symbol="NIFTY 50", session=session)
            prior = await get_signal_evaluations(date="2026-11-16", symbol="NIFTY 50", session=session)
            assert today["count"] == 1
            assert today["evaluations"][0]["reasons"] == ["Stale feed"]
            assert today["evaluations"][0]["qualified"] is False
            assert prior["count"] == 0
            assert ist_day_bounds(datetime(2026, 11, 17).date())[0].hour == 18
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_history_groups_signals_by_ist_date(monkeypatch):
    from app.api.routes import performance

    monkeypatch.setattr(performance.MarketCalendar, "now_ist", lambda: datetime(2026, 11, 17, 12, tzinfo=performance.IST))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add(SignalRecord(
                symbol="NIFTY 50", contract_symbol="NIFTY25500CE", instrument_token="123",
                strike=25500, expiry="2026-11-19", option_type="CE",
                underlying_price_at_signal=25500, signal_premium=100,
                entry_zone_min=100, entry_zone_max=105, entry_trigger_condition="breakout",
                stop_loss_premium=90, target_1_premium=110, target_2_premium=120,
                target_3_premium=130, created_at=datetime(2026, 11, 16, 19, tzinfo=timezone.utc),
            ))
            await session.commit()
            result = await get_performance_history(days=2, session=session)
            assert result.data["history"][0]["date"] == "2026-11-17"
            assert result.data["history"][0]["totalSignals"] == 1
    finally:
        await engine.dispose()
