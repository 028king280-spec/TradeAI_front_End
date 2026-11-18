"""Background lifecycle of isolated research paper trades, including browser-off exits."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from app.core.logging import logger
from app.data.market_calendar import MarketCalendar
from app.data.providers.factory import get_market_data_provider
from app.db import database
from app.models.db_models import ResearchPaperTrade, ResearchSetupEvaluationRecord
from app.options.research_paper_engine import ensure_account, open_trade, process_exit, IST
from app.options.research_setup_engine import ENGINE_ID


class ResearchPaperSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    RESEARCH_PAPER_AUTO_ENTRY: bool = True


settings = ResearchPaperSettings()


def entries_enabled():
    return settings.RESEARCH_PAPER_AUTO_ENTRY


async def research_paper_job():
    # Existing open positions continue to be monitored even if new entries are disabled.
    if not MarketCalendar.is_market_open():
        return
    now = datetime.now(timezone.utc)
    provider = get_market_data_provider()
    factory = database.ledger_session_factory
    await ensure_account(factory)
    async with factory() as session:
        trades = list((await session.execute(select(ResearchPaperTrade).where(
            ResearchPaperTrade.engine_id == ENGINE_ID, ResearchPaperTrade.status == 'OPEN'
        ))).scalars())
        evaluations = []
        if entries_enabled() and now.astimezone(IST).strftime('%H:%M') < '15:25':
            evaluations = list((await session.execute(select(ResearchSetupEvaluationRecord).where(
                ResearchSetupEvaluationRecord.engine_id == ENGINE_ID,
                ResearchSetupEvaluationRecord.qualified.is_(True),
                ResearchSetupEvaluationRecord.evaluated_at >= now - timedelta(seconds=60),
            ).order_by(ResearchSetupEvaluationRecord.evaluated_at.desc()).limit(100))).scalars())
    needed = {}
    for trade in trades:
        needed.setdefault(trade.exchange, set()).add(trade.instrument_token)
    for evaluation in evaluations:
        setup = evaluation.payload.get('setup') or {}
        if setup.get('instrumentToken') and setup.get('exchange'):
            needed.setdefault(setup['exchange'], set()).add(str(setup['instrumentToken']))
    quotes = {}
    for exchange, tokens in needed.items():
        try:
            if hasattr(provider, 'get_batch_quotes'):
                batch = await provider.get_batch_quotes(exchange, sorted(tokens))
                quotes.update({(exchange, str(token)): value for token, value in batch.items()})
        except Exception as exc:
            logger.warning('Research quote retrieval failed for %s: %s', exchange, exc)
    # Use actual time after I/O so a quote cannot pass using a pre-request timestamp.
    now = datetime.now(timezone.utc)
    if not MarketCalendar.is_market_open():
        return
    for trade in trades:
        try:
            await process_exit(factory, trade.id, quotes.get((trade.exchange, trade.instrument_token)), now)
        except Exception as exc:
            logger.warning('Research exit transaction failed for %s: %s', trade.id, exc)
    for evaluation in evaluations:
        setup = evaluation.payload.get('setup') or {}
        quote = quotes.get((setup.get('exchange'), str(setup.get('instrumentToken'))))
        try:
            outcome = await open_trade(factory, evaluation.payload, quote, now)
            logger.debug('Research paper entry %s: %s', evaluation.id, outcome)
        except Exception as exc:
            logger.warning('Research entry transaction failed for %s: %s', evaluation.id, exc)
