"""Durable, isolated paper fills. No broker orders and no production account writes."""
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from app.data.market_calendar import MarketCalendar
from app.models.db_models import ResearchPaperAccount, ResearchPaperTrade
from app.options.research_setup_engine import ENGINE_ID

IST = ZoneInfo("Asia/Kolkata")
INITIAL_CASH = 10_000_000  # paise: explicitly virtual INR 100,000
FEE = 2_000  # model assumption: INR 20 per side; excludes GST/other statutory fees
SLIPPAGE_BPS = 5  # model assumption: 0.05% on each side


def paise(value):
    number = Decimal(str(value))
    if not number.is_finite() or number <= 0:
        raise ValueError("Price must be finite and positive")
    return int((number * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def timestamp(value):
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            dt = datetime.strptime(str(value), '%d-%b-%Y %H:%M:%S')
    return (dt.replace(tzinfo=IST) if dt.tzinfo is None else dt).astimezone(timezone.utc)


def executable_quote(quote, token, exchange, quantity, now):
    """Fail closed on stale, fallback, crossed, missing depth or wrong-instrument data."""
    try:
        if not quote or quote.get('dataStatus') not in ('LIVE', 'VERIFIED_LIVE'):
            return None
        if quote.get('is_mock') or quote.get('is_synthetic') or str(quote.get('provider', '')).lower() in ('', 'mock', 'synthetic'):
            return None
        if not quote.get('hasExecutableDepth') or not quote.get('marketTimestampVerified'):
            return None
        if str(quote.get('symbolToken')) != str(token) or quote.get('exchange') != exchange:
            return None
        at = timestamp(quote['marketTimestamp'])
        if not -2 <= (now - at).total_seconds() <= 30:
            return None
        bid, ask = paise(quote['bid']), paise(quote['ask'])
        if ask < bid or (ask - bid) / ask > .05:
            return None
        if min(int(quote.get('bidQuantity', 0)), int(quote.get('askQuantity', 0))) < quantity:
            return None
        return bid, ask, at
    except (KeyError, TypeError, ValueError, ArithmeticError, OverflowError):
        return None


def fill_price(price_paise, bps):
    return int((Decimal(price_paise) * (Decimal(10000 + bps) / 10000)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


async def ensure_account(factory):
    async with factory() as session:
        try:
            async with session.begin():
                if await session.get(ResearchPaperAccount, ENGINE_ID) is None:
                    session.add(ResearchPaperAccount(id=ENGINE_ID, initial_cash_paise=INITIAL_CASH, cash_paise=INITIAL_CASH))
        except IntegrityError:
            # Another worker initialized the same deterministic account.
            await session.rollback()


async def open_trade(factory, evaluation, quote, now):
    """One lot, one open trade per underlying, one contract per IST day."""
    if not MarketCalendar.is_market_open(now.astimezone(IST)):
        return 'MARKET_CLOSED'
    if not evaluation.get('qualified') or not evaluation.get('journalSaved') or evaluation.get('engineId') != ENGINE_ID:
        return 'NOT_ELIGIBLE'
    setup = evaluation.get('setup') or {}
    try:
        age = (now - timestamp(evaluation['timestamp'])).total_seconds()
        if not 0 <= age <= 60 or now.astimezone(IST).strftime('%H:%M') >= '15:25':
            return 'EXPIRED_EVALUATION'
        quantity = int(setup['lotSize'])
        if quantity <= 0 or quantity != float(setup['lotSize']):
            return 'INVALID_LOT'
        token, exchange = str(setup['instrumentToken']), setup['exchange']
        validated = executable_quote(quote, token, exchange, quantity, now)
        if validated is None:
            return 'QUOTE_UNAVAILABLE'
        bid, ask, quote_at = validated
        if quote_at < timestamp(evaluation['timestamp']):
            return 'QUOTE_BEFORE_SETUP'
        reference = paise(setup['entryPremium'])
        if abs(ask - reference) / reference > .02:
            return 'ENTRY_MOVED'
        entry = fill_price(ask, SLIPPAGE_BPS)
        target = fill_price(entry, 3000)
        stop = paise(setup['stopLoss'])
        if not 0 < stop < bid <= ask or (target - entry) / (entry - stop) < 1.5:
            return 'INVALID_RISK'
        key = f"{ENGINE_ID}|{now.astimezone(IST).date()}|{exchange}|{token}"
        trade_id = hashlib.sha256(key.encode()).hexdigest()
        cost = entry * quantity + FEE
        async with factory() as session:
            try:
                async with session.begin():
                    cash = await session.execute(update(ResearchPaperAccount).where(
                        ResearchPaperAccount.id == ENGINE_ID,
                        ResearchPaperAccount.cash_paise >= cost,
                    ).values(cash_paise=ResearchPaperAccount.cash_paise - cost))
                    if cash.rowcount != 1:
                        return 'INSUFFICIENT_CASH'
                    session.add(ResearchPaperTrade(
                        id=trade_id, evaluation_id=evaluation['id'], engine_id=ENGINE_ID,
                        symbol=evaluation['symbol'], active_slot=f"{ENGINE_ID}:{evaluation['symbol']}",
                        contract_symbol=setup['contractSymbol'], instrument_token=token, exchange=exchange,
                        quantity=quantity, status='OPEN', entry_paise=entry, target_paise=target,
                        stop_paise=stop, entry_fee_paise=FEE, exit_fee_paise=FEE,
                        slippage_bps=SLIPPAGE_BPS, opened_at=now, entry_quote_at=quote_at,
                        last_quote_at=quote_at, last_bid_paise=bid, monitoring_status='LIVE', snapshot=evaluation,
                    ))
                return 'OPENED'
            except IntegrityError:
                # Unique trade key/active slot rolls back the cash debit too.
                await session.rollback()
                return 'DUPLICATE_OR_ACTIVE'
    except (KeyError, TypeError, ValueError, ArithmeticError, OverflowError):
        return 'INVALID_EVALUATION'


async def process_exit(factory, trade_id, quote, now):
    if not MarketCalendar.is_market_open(now.astimezone(IST)):
        return 'MARKET_CLOSED'
    async with factory() as session:
        async with session.begin():
            trade = await session.get(ResearchPaperTrade, trade_id)
            if trade is None or trade.status != 'OPEN':
                return 'ALREADY_CLOSED'
            validated = executable_quote(quote, trade.instrument_token, trade.exchange, trade.quantity, now)
            if validated is None:
                await session.execute(update(ResearchPaperTrade).where(
                    ResearchPaperTrade.id == trade_id, ResearchPaperTrade.status == 'OPEN'
                ).values(monitoring_status='DATA_GAP', had_data_gap=True))
                return 'DATA_GAP'
            bid, ask, quote_at = validated
            prior = trade.last_quote_at or trade.entry_quote_at
            # SQLite returns naive UTC; never reinterpret stored UTC as IST.
            prior = prior.replace(tzinfo=timezone.utc) if prior.tzinfo is None else prior
            if quote_at <= prior:
                return 'OLD_QUOTE'
            reason = None
            if bid <= trade.stop_paise:
                reason = 'STOP_LOSS'
            elif bid >= trade.target_paise:
                reason = 'TARGET_30'
            elif now.astimezone(IST).strftime('%H:%M') >= '15:25':
                reason = 'SESSION_END'
            else:
                opened = trade.opened_at.replace(tzinfo=timezone.utc) if trade.opened_at.tzinfo is None else trade.opened_at
                if now.astimezone(IST).date() > opened.astimezone(IST).date():
                    reason = 'DELAYED_SESSION_END'
            values = dict(last_quote_at=quote_at, last_bid_paise=bid, monitoring_status='LIVE')
            if (quote_at - prior).total_seconds() > 30:
                values['had_data_gap'] = True
            if reason:
                exit_price = fill_price(bid, -trade.slippage_bps)
                pnl = (exit_price - trade.entry_paise) * trade.quantity - trade.entry_fee_paise - trade.exit_fee_paise
                values.update(status='CLOSED', active_slot=None, closed_at=now, exit_paise=exit_price,
                              exit_reason=reason, net_pnl_paise=pnl)
            changed = await session.execute(update(ResearchPaperTrade).where(
                ResearchPaperTrade.id == trade_id, ResearchPaperTrade.status == 'OPEN',
                ResearchPaperTrade.last_quote_at == trade.last_quote_at,
            ).values(**values))
            if changed.rowcount != 1:
                return 'CONCURRENT_UPDATE'
            if reason:
                credited = await session.execute(update(ResearchPaperAccount).where(
                    ResearchPaperAccount.id == ENGINE_ID
                ).values(cash_paise=ResearchPaperAccount.cash_paise + exit_price * trade.quantity - trade.exit_fee_paise))
                if credited.rowcount != 1:
                    raise RuntimeError('Research account missing; closing transaction rolled back')
                return reason
            return 'OPEN'
