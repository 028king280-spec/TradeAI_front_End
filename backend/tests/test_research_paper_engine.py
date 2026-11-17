import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, func, update, event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import Session

from app.db.database import Base
from app.models.db_models import ResearchPaperAccount, ResearchPaperTrade, ResearchSetupEvaluationRecord, SignalRecord
from app.options import research_paper_engine as paper

NOW = datetime(2026, 11, 17, 5, 0, tzinfo=timezone.utc)


def evaluation(now=NOW, token='123', symbol='NIFTY 50'):
    return {'id': str(uuid4()), 'engineId': paper.ENGINE_ID, 'qualified': True,
            'journalSaved': True, 'timestamp': now.isoformat(), 'symbol': symbol,
            'setup': {'contractSymbol': 'NIFTY-CE', 'instrumentToken': token, 'exchange': 'NFO',
                      'lotSize': 50, 'entryPremium': 100, 'stopLoss': 85}}


def quote(now=NOW, bid=99, ask=100, token='123'):
    return {'symbolToken': token, 'exchange': 'NFO', 'provider': 'angelone',
            'dataStatus': 'LIVE', 'hasExecutableDepth': True, 'marketTimestampVerified': True,
            'bidQuantity': 200, 'askQuantity': 200, 'marketTimestamp': now.isoformat(),
            'bid': bid, 'ask': ask}


@pytest.fixture
async def ledger(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "research.db"}')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await paper.ensure_account(factory)
    yield factory, engine
    await engine.dispose()


async def snapshot(factory):
    async with factory() as session:
        account = await session.get(ResearchPaperAccount, paper.ENGINE_ID)
        trades = list((await session.execute(select(ResearchPaperTrade))).scalars())
        return account.cash_paise, trades


@pytest.mark.asyncio
async def test_entry_target_exit_cash_and_net_pnl_reconcile(ledger):
    factory, _ = ledger
    assert await paper.open_trade(factory, evaluation(), quote(), NOW) == 'OPENED'
    cash, trades = await snapshot(factory)
    trade = trades[0]
    assert trade.entry_paise == 10005 and trade.target_paise == 13007
    assert cash == paper.INITIAL_CASH - 10005 * 50 - 2000
    later = NOW + timedelta(seconds=20)
    assert await paper.process_exit(factory, trade.id, quote(later, bid=140, ask=141), later) == 'TARGET_30'
    cash, trades = await snapshot(factory)
    assert trades[0].exit_paise == 13993
    assert trades[0].net_pnl_paise == 195400
    assert cash == paper.INITIAL_CASH + 195400
    assert trades[0].active_slot is None
    assert await paper.process_exit(factory, trade.id, quote(later, 140, 141), later) == 'ALREADY_CLOSED'
    assert (await snapshot(factory))[0] == cash
    async with factory() as session:
        assert (await session.execute(select(func.count()).select_from(SignalRecord))).scalar_one() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('bid,ask,at,reason', [
    (80, 81, NOW + timedelta(seconds=20), 'STOP_LOSS'),
    (110, 111, NOW.replace(hour=9, minute=55), 'SESSION_END'),
    (110, 111, NOW + timedelta(days=1), 'DELAYED_SESSION_END'),
])
async def test_exit_paths_use_observed_bid_not_target_or_stop(ledger, bid, ask, at, reason):
    factory, _ = ledger
    await paper.open_trade(factory, evaluation(), quote(), NOW)
    _, trades = await snapshot(factory)
    assert await paper.process_exit(factory, trades[0].id, quote(at, bid, ask), at) == reason
    cash, trades = await snapshot(factory)
    assert trades[0].exit_paise == paper.fill_price(paper.paise(bid), -5)
    assert cash == paper.INITIAL_CASH + trades[0].net_pnl_paise


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'dataStatus': 'STALE'}, {'provider': 'mock'}, {'hasExecutableDepth': False},
    {'marketTimestampVerified': False}, {'marketTimestamp': (NOW - timedelta(minutes=1)).isoformat()},
    {'marketTimestamp': (NOW + timedelta(minutes=1)).isoformat()}, {'symbolToken': 'WRONG'},
    {'exchange': 'BFO'}, {'ask': 98}, {'bid': 0}, {'askQuantity': 1}, {'bid': float('nan')},
])
async def test_invalid_quotes_cannot_create_fill(ledger, changes):
    factory, _ = ledger
    q = dict(quote(), **changes)
    assert await paper.open_trade(factory, evaluation(), q, NOW) == 'QUOTE_UNAVAILABLE'
    cash, trades = await snapshot(factory)
    assert not trades and cash == paper.INITIAL_CASH


@pytest.mark.asyncio
async def test_missing_exit_quote_does_not_fabricate_close(ledger):
    factory, _ = ledger
    await paper.open_trade(factory, evaluation(), quote(), NOW)
    cash, trades = await snapshot(factory)
    later = NOW + timedelta(seconds=40)
    assert await paper.process_exit(factory, trades[0].id, quote(), later) == 'DATA_GAP'
    new_cash, current = await snapshot(factory)
    assert new_cash == cash and current[0].status == 'OPEN'
    assert current[0].monitoring_status == 'DATA_GAP'


@pytest.mark.asyncio
async def test_duplicate_and_active_slot_rollback_debit(ledger):
    factory, _ = ledger
    ev = evaluation()
    results = await asyncio.gather(*(paper.open_trade(factory, ev, quote(), NOW) for _ in range(4)))
    assert results.count('OPENED') == 1
    cash, trades = await snapshot(factory)
    assert len(trades) == 1 and cash == paper.INITIAL_CASH - trades[0].entry_paise * 50 - 2000
    assert await paper.open_trade(factory, evaluation(token='456'), quote(token='456'), NOW) == 'DUPLICATE_OR_ACTIVE'
    assert (await snapshot(factory))[0] == cash


@pytest.mark.asyncio
async def test_concurrent_closers_credit_once(ledger):
    factory, _ = ledger
    await paper.open_trade(factory, evaluation(), quote(), NOW)
    _, trades = await snapshot(factory)
    later = NOW + timedelta(seconds=20)
    outcomes = await asyncio.gather(*(paper.process_exit(factory, trades[0].id, quote(later, 140, 141), later) for _ in range(4)))
    assert outcomes.count('TARGET_30') == 1
    cash, trades = await snapshot(factory)
    assert cash == paper.INITIAL_CASH + trades[0].net_pnl_paise


@pytest.mark.asyncio
async def test_restart_recovers_open_trade_and_insufficient_cash_blocks(ledger):
    factory, engine = ledger
    await paper.open_trade(factory, evaluation(), quote(), NOW)
    await engine.dispose()
    restarted_factory = async_sessionmaker(engine, expire_on_commit=False)
    cash, trades = await snapshot(restarted_factory)
    await paper.ensure_account(restarted_factory)
    assert (await snapshot(restarted_factory))[0] == cash
    async with restarted_factory() as session:
        await session.execute(update(ResearchPaperAccount).values(cash_paise=1))
        await session.commit()
    assert await paper.open_trade(restarted_factory, evaluation(token='456', symbol='BANK NIFTY'), quote(token='456'), NOW) == 'INSUFFICIENT_CASH'


@pytest.mark.asyncio
async def test_failed_commit_rolls_back_trade_and_cash(ledger):
    factory, engine = ledger
    class FailingSession(Session):
        pass
    def fail_commit(session):
        raise RuntimeError('injected commit failure')
    event.listen(FailingSession, 'before_commit', fail_commit)
    broken = async_sessionmaker(engine, sync_session_class=FailingSession, expire_on_commit=False)
    with pytest.raises(RuntimeError, match='injected'):
        await paper.open_trade(broken, evaluation(), quote(), NOW)
    cash, trades = await snapshot(factory)
    assert cash == paper.INITIAL_CASH and not trades
    await paper.open_trade(factory, evaluation(), quote(), NOW)
    cash, trades = await snapshot(factory)
    later = NOW + timedelta(seconds=20)
    with pytest.raises(RuntimeError, match='injected'):
        await paper.process_exit(broken, trades[0].id, quote(later, 140, 141), later)
    actual_cash, actual_trades = await snapshot(factory)
    assert actual_cash == cash and actual_trades[0].status == 'OPEN'


@pytest.mark.asyncio
async def test_old_evaluation_unqualified_and_out_of_session_do_not_open(ledger):
    factory, _ = ledger
    assert await paper.open_trade(factory, evaluation(NOW-timedelta(seconds=61)), quote(), NOW) == 'EXPIRED_EVALUATION'
    assert await paper.open_trade(factory, dict(evaluation(), qualified=False), quote(), NOW) == 'NOT_ELIGIBLE'
    assert await paper.open_trade(factory, evaluation(), quote(), NOW.replace(hour=1)) == 'MARKET_CLOSED'
    assert not (await snapshot(factory))[1]


@pytest.mark.asyncio
async def test_same_day_closed_contract_does_not_reenter(ledger):
    factory, _ = ledger
    await paper.open_trade(factory, evaluation(), quote(), NOW)
    _, trades = await snapshot(factory)
    later = NOW + timedelta(seconds=20)
    await paper.process_exit(factory, trades[0].id, quote(later, 140, 141), later)
    cash, _ = await snapshot(factory)
    assert await paper.open_trade(factory, evaluation(later), quote(later), later) == 'DUPLICATE_OR_ACTIVE'
    assert (await snapshot(factory))[0] == cash


@pytest.mark.asyncio
async def test_scheduler_saved_evaluation_entry_browser_off_exit_and_http(ledger, monkeypatch):
    from app.jobs import research_paper as job
    from app.api.routes.performance import get_research_paper
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.api.routes.performance import router
    from app.db.database import get_db
    factory, _ = ledger
    current = [NOW]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0]
    class Provider:
        async def get_batch_quotes(self, exchange, tokens):
            return {'123': quote(current[0], 99 if current[0] == NOW else 140, 100 if current[0] == NOW else 141)}
    monkeypatch.setattr(job, 'datetime', Clock)
    monkeypatch.setattr(job.MarketCalendar, 'is_market_open', lambda *a: True)
    monkeypatch.setattr(job, 'get_market_data_provider', lambda: Provider())
    monkeypatch.setattr(job.database, 'ledger_session_factory', factory)
    monkeypatch.setattr(job.settings, 'RESEARCH_PAPER_AUTO_ENTRY', True)
    ev = evaluation()
    async with factory() as session:
        session.add(ResearchSetupEvaluationRecord(id=ev['id'], engine_id=paper.ENGINE_ID,
                    symbol=ev['symbol'], qualified=True, payload=ev, evaluated_at=NOW))
        await session.commit()
    await job.research_paper_job()
    assert len((await snapshot(factory))[1]) == 1
    # No new analysis request. Turning off entries must not disable exits.
    current[0] = NOW + timedelta(seconds=20)
    monkeypatch.setattr(job.settings, 'RESEARCH_PAPER_AUTO_ENTRY', False)
    await job.research_paper_job()
    cash, trades = await snapshot(factory)
    assert trades[0].status == 'CLOSED'
    app = FastAPI()
    app.include_router(router, prefix='/api')
    async def db():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_db] = db
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/api/performance/research-paper')
    assert response.status_code == 200
    data = response.json()
    assert data['totalTrades'] == 1 and data['availableCash'] == cash / 100
    assert data['realizedNetPnl'] == trades[0].net_pnl_paise / 100
    assert data['trades'][0]['exitReason'] == 'TARGET_30'
    assert not data['autoEntryEnabled']


@pytest.mark.asyncio
async def test_quote_before_signal_is_not_an_entry(ledger):
    factory, _ = ledger
    assert await paper.open_trade(factory, evaluation(), quote(NOW-timedelta(seconds=5)), NOW) == 'QUOTE_BEFORE_SETUP'
    assert not (await snapshot(factory))[1]


@pytest.mark.asyncio
async def test_older_exit_tick_cannot_undo_newer_tick(ledger):
    factory, _ = ledger
    await paper.open_trade(factory, evaluation(), quote(), NOW)
    _, trades = await snapshot(factory)
    later = NOW + timedelta(seconds=20)
    assert await paper.process_exit(factory, trades[0].id, quote(later, 110, 111), later) == 'OPEN'
    assert await paper.process_exit(factory, trades[0].id, quote(NOW + timedelta(seconds=10), 140, 141), later) == 'OLD_QUOTE'
    assert (await snapshot(factory))[1][0].status == 'OPEN'


@pytest.mark.asyncio
async def test_data_gap_is_retained_after_recovery_for_training_review(ledger):
    factory, _ = ledger
    await paper.open_trade(factory, evaluation(), quote(), NOW)
    _, trades = await snapshot(factory)
    later = NOW + timedelta(seconds=40)
    await paper.process_exit(factory, trades[0].id, None, later)
    recovered = NOW + timedelta(seconds=50)
    await paper.process_exit(factory, trades[0].id, quote(recovered, 140, 141), recovered)
    _, trades = await snapshot(factory)
    assert trades[0].status == 'CLOSED' and trades[0].had_data_gap
