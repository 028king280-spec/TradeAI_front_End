from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.db.database import Base
from app.models.db_models import ResearchSetupEvaluationRecord, SignalRecord, SignalEvaluationRecord
from app.options import research_setup_engine as research


def candidate(score=60, entry=100, stop=85):
    return {"symbol": "NIFTY 50", "action": "BUY_CE", "is_trade_qualified": True,
            "mtf_confluence": {"confluence_score": score},
            "risk_plan": {"entry_premium": entry, "stop_loss_premium": stop},
            "selected_contract": {"contract_symbol": "NIFTY-CE", "option_type": "CE"}}


@pytest.mark.parametrize('score,qualified', [(59.99, False), (60, True), (69.99, True), (70, True)])
def test_research_threshold_and_single_target(score, qualified):
    original = candidate(score)
    before = deepcopy(original)
    result = research.build_research_setup(original)
    assert result['qualified'] is qualified
    assert original == before
    if qualified:
        assert result['setup']['targetPremium'] == 130
        assert result['setup']['grossRewardRisk'] == 2


@pytest.mark.parametrize('entry,stop', [(0, 0), (100, 100), (100, 105), (100, 70), (float('nan'), 85)])
def test_invalid_premium_or_insufficient_rr_stays_closed(entry, stop):
    result = research.build_research_setup(candidate(entry=entry, stop=stop))
    assert not result['qualified']
    assert result['setup'] is None


def test_rejections_are_preserved():
    result = candidate()
    result.update(is_trade_qualified=False, rejection_reasons=['Stale feed'])
    assert research.build_research_setup(result)['reasons'] == ['Stale feed']
    assert not research.build_research_setup(result)['qualified']


@pytest.mark.asyncio
async def test_second_profile_sets_both_gates_without_production_session(monkeypatch):
    from app.options.trade_setup_selector import DEFAULT_SETUP_CONFIG
    before = deepcopy(DEFAULT_SETUP_CONFIG)
    pipeline = AsyncMock(return_value=candidate())
    monkeypatch.setattr(research, 'execute_production_signal_pipeline', pipeline)
    await research.evaluate_research_setup('NIFTY 50', object(), {}, {}, {})
    kwargs = pipeline.call_args.kwargs
    assert kwargs['session'] is None
    assert kwargs['config']['min_confluence_score'] == 60
    assert kwargs['config']['trade_setup_config']['min_confluence_score'] == 60
    assert DEFAULT_SETUP_CONFIG == before
    assert DEFAULT_SETUP_CONFIG['min_confluence_score'] == 70


@pytest.mark.asyncio
async def test_research_history_is_separate_and_ist_filtered():
    from app.api.routes.performance import get_research_evaluations
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine)() as session:
            result = research.build_research_setup(candidate())
            session.add(ResearchSetupEvaluationRecord(
                id=result['id'], engine_id=research.ENGINE_ID, symbol='NIFTY 50',
                qualified=True, payload=result,
                evaluated_at=datetime(2026, 11, 16, 19, tzinfo=timezone.utc)))
            await session.commit()
            today = await get_research_evaluations('2026-11-17', 'NIFTY 50', 1, 0, session)
            yesterday = await get_research_evaluations('2026-11-16', None, 1, 0, session)
            assert today['count'] == 1 and yesterday['count'] == 0
            assert today['evaluations'][0]['setup']['targetPremium'] == 130
            for model in (SignalRecord, SignalEvaluationRecord):
                assert (await session.execute(select(func.count()).select_from(model))).scalar_one() == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_pipeline_65_score_passes_research_but_not_production(monkeypatch, tmp_path):
    from app.options import pipeline_orchestrator as pipeline
    from app.options.contract_selector import set_governance_ledger_db_path
    from app.data.market_calendar import MarketCalendar
    from tests.test_pipeline_integration_step4_3 import make_bullish_timeframes, build_mock_option_chain
    monkeypatch.setattr(MarketCalendar, 'is_market_open', lambda *a, **k: True)
    original_confluence = pipeline.evaluate_multi_timeframe_confluence
    def score_65(**kwargs):
        output = original_confluence(**kwargs)
        output['confluence_score'] = 65.0
        return output
    monkeypatch.setattr(pipeline, 'evaluate_multi_timeframe_confluence', score_65)
    set_governance_ledger_db_path(str(tmp_path / 'governance.db'))
    try:
        tfs = make_bullish_timeframes(24500.0)
        ltp = float(tfs['1m']['close'].iloc[-1])
        quote = {'currentPrice': ltp, 'dayHigh': ltp + 10, 'dayLow': 24300,
                 'openPrice': 24400, 'previousClose': 24350, 'change': ltp - 24350,
                 'provider': 'angelone', 'timestamp': datetime.now(timezone.utc).isoformat()}
        chain = build_mock_option_chain('NIFTY', ltp, strikes=[24500,24550,24600,24650,24700])
        kwargs = dict(symbol='NIFTY 50', custom_quote=quote, custom_timeframes=tfs, custom_option_chain=chain)
        production = await pipeline.execute_production_signal_pipeline(**kwargs)
        second = await research.evaluate_research_setup(provider=None, **kwargs)
        assert production['stage_status'][pipeline.PipelineStage.STAGE_6_MTF_CONFLUENCE] == 'BELOW_THRESHOLD'
        assert not production['is_trade_qualified']
        assert second['stages'][pipeline.PipelineStage.STAGE_6_MTF_CONFLUENCE] == 'SUCCESS'
        assert second['stages'][pipeline.PipelineStage.STAGE_7_TRADE_SETUP_QUALIFICATION] == 'SUCCESS'
        # +30% may still be rejected by the independent premium RR gate.
        if second['qualified']:
            assert second['setup']['targetPremium'] == round(second['setup']['entryPremium'] * 1.3, 2)
        else:
            assert any('reward-to-risk' in reason for reason in second['reasons'])
    finally:
        set_governance_ledger_db_path(None)
