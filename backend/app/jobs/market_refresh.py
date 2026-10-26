from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.data.market_calendar import MarketCalendar
from app.services.market_service import MarketService
from app.services.signal_service import SignalService
from app.core.logging import logger

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


async def pre_market_job():
    """
    Runs at 09:00 AM IST before market opens.
    Prepares market universe and refreshes previous-day closing levels.
    """
    if not MarketCalendar.is_trading_day():
        return
    logger.info("Executing Pre-Market Job: Initializing universe and cache warmup")
    await MarketService.get_indices()
    await MarketService.get_sector_heatmap()


async def intraday_refresh_job():
    """
    Runs every 2 minutes during active market hours (09:15 to 15:30 IST).
    Refreshes benchmark indices, breadth, and candidate signals.
    """
    if not MarketCalendar.is_market_open():
        return
    logger.info("Executing Intraday Refresh: Updating indices and candidate setups")
    await MarketService.get_indices()
    await MarketService.get_market_sentiment()
    await SignalService.get_top_call_candidates()
    await SignalService.get_top_put_candidates()


async def post_market_job():
    """
    Runs at 15:35 PM IST after market close.
    Saves final analysis snapshot and computes daily statistics.
    """
    if not MarketCalendar.is_trading_day():
        return
    logger.info("Executing Post-Market Job: Finalizing daily market session snapshot")


def start_scheduler():
    # Pre-market job at 09:00 AM IST Mon-Fri
    scheduler.add_job(pre_market_job, "cron", day_of_week="mon-fri", hour=9, minute=0)

    # Intraday refresh every 2 minutes
    scheduler.add_job(intraday_refresh_job, "interval", minutes=2)

    # Post-market job at 15:35 PM IST Mon-Fri
    scheduler.add_job(post_market_job, "cron", day_of_week="mon-fri", hour=15, minute=35)

    scheduler.start()
    logger.info("APScheduler initialized for Indian Stock Market hours (Asia/Kolkata)")
