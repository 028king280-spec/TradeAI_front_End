from typing import List, Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.database import async_session_factory
from app.models.db_models import Stock


# Comprehensive initial seed of institutional Indian F&O stock universe
INITIAL_INDIAN_UNIVERSE: List[Dict[str, Any]] = [
    {
        "symbol": "RELIANCE",
        "company_name": "Reliance Industries Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE002A01018",
        "isin": "INE002A01018",
        "sector": "Energy & Conglomerate",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 250,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "TCS",
        "company_name": "Tata Consultancy Services Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE467B01029",
        "isin": "INE467B01029",
        "sector": "Information Technology",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 175,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "HDFCBANK",
        "company_name": "HDFC Bank Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE040A01034",
        "isin": "INE040A01034",
        "sector": "Banking & Financials",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 550,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "INFY",
        "company_name": "Infosys Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE009A01021",
        "isin": "INE009A01021",
        "sector": "Information Technology",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 400,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "ICICIBANK",
        "company_name": "ICICI Bank Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE090A01021",
        "isin": "INE090A01021",
        "sector": "Banking & Financials",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 700,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "SBIN",
        "company_name": "State Bank of India",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE062A01020",
        "isin": "INE062A01020",
        "sector": "Banking & Financials",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 750,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "BHARTIARTL",
        "company_name": "Bharti Airtel Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE397D01024",
        "isin": "INE397D01024",
        "sector": "Telecommunication",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 475,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "ITC",
        "company_name": "ITC Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE154A01025",
        "isin": "INE154A01025",
        "sector": "FMCG",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 1600,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "TATAMOTORS",
        "company_name": "Tata Motors Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE155A01022",
        "isin": "INE155A01022",
        "sector": "Automobile",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 575,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "AXISBANK",
        "company_name": "Axis Bank Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE238A01034",
        "isin": "INE238A01034",
        "sector": "Banking & Financials",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 625,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "LT",
        "company_name": "Larsen & Toubro Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE018A01030",
        "isin": "INE018A01030",
        "sector": "Capital Goods & Infra",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 150,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "MARUTI",
        "company_name": "Maruti Suzuki India Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE585B01010",
        "isin": "INE585B01010",
        "sector": "Automobile",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 50,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "SUNPHARMA",
        "company_name": "Sun Pharmaceutical Industries Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE044A01036",
        "isin": "INE044A01036",
        "sector": "Pharmaceuticals",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 350,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "TITAN",
        "company_name": "Titan Company Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE280A01028",
        "isin": "INE280A01028",
        "sector": "Consumer Discretionary",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 175,
        "tick_size": 0.05,
        "is_fno": True,
    },
    {
        "symbol": "BAJFINANCE",
        "company_name": "Bajaj Finance Limited",
        "exchange": "NSE",
        "instrument_key": "NSE_EQ|INE296A01024",
        "isin": "INE296A01024",
        "sector": "Financial Services (NBFC)",
        "instrument_type": "EQUITY",
        "category": "Large Cap",
        "lot_size": 125,
        "tick_size": 0.05,
        "is_fno": True,
    },
]


class InstrumentService:
    """
    Manages Indian stock market instrument master data:
    - Symbol, Company Name, Exchange, Instrument Key, ISIN, Sector, Lot Size, Tick Size, is_fno.
    - Resolves symbols to Upstox instrument_key for live WebSocket subscriptions.
    - Synchronizes master catalog with database.
    """

    _cache_by_symbol: Dict[str, Dict[str, Any]] = {s["symbol"]: s for s in INITIAL_INDIAN_UNIVERSE}
    _cache_by_key: Dict[str, Dict[str, Any]] = {s["instrument_key"]: s for s in INITIAL_INDIAN_UNIVERSE}

    @classmethod
    async def initialize(cls):
        """
        Seeds initial stock universe into database if empty and refreshes in-memory cache.
        """
        async with async_session_factory() as session:
            try:
                stmt = select(Stock)
                res = await session.execute(stmt)
                existing = res.scalars().all()

                if not existing:
                    logger.info("Seeding initial Indian Stock Universe to Instrument Master...")
                    for s_data in INITIAL_INDIAN_UNIVERSE:
                        stock = Stock(
                            symbol=s_data["symbol"],
                            company_name=s_data["company_name"],
                            exchange=s_data["exchange"],
                            instrument_key=s_data["instrument_key"],
                            isin=s_data["isin"],
                            sector=s_data["sector"],
                            instrument_type=s_data["instrument_type"],
                            category=s_data["category"],
                            lot_size=s_data["lot_size"],
                            tick_size=s_data["tick_size"],
                            is_fno=s_data["is_fno"],
                        )
                        session.add(stock)
                    await session.commit()
                else:
                    for stock in existing:
                        data = {
                            "symbol": stock.symbol,
                            "company_name": stock.company_name,
                            "exchange": stock.exchange,
                            "instrument_key": stock.instrument_key or f"NSE_EQ|{stock.symbol}",
                            "isin": stock.isin,
                            "sector": stock.sector,
                            "instrument_type": stock.instrument_type,
                            "category": stock.category,
                            "lot_size": stock.lot_size,
                            "tick_size": stock.tick_size,
                            "is_fno": stock.is_fno,
                        }
                        cls._cache_by_symbol[stock.symbol] = data
                        if stock.instrument_key:
                            cls._cache_by_key[stock.instrument_key] = data
            except Exception as e:
                logger.warning(f"Instrument service initialization notice: {e}")

    @classmethod
    def get_instrument_key(cls, symbol: str) -> str:
        clean = symbol.upper().strip()
        item = cls._cache_by_symbol.get(clean)
        if item and item.get("instrument_key"):
            return item["instrument_key"]
        return f"NSE_EQ|{clean}"

    @classmethod
    def get_symbol_by_key(cls, instrument_key: str) -> str:
        item = cls._cache_by_key.get(instrument_key)
        if item:
            return item["symbol"]
        parts = instrument_key.split("|")
        return parts[-1] if len(parts) > 1 else instrument_key

    @classmethod
    def get_instrument(cls, symbol: str) -> Optional[Dict[str, Any]]:
        return cls._cache_by_symbol.get(symbol.upper().strip())

    @classmethod
    def list_eligible_universe(cls) -> List[Dict[str, Any]]:
        return list(cls._cache_by_symbol.values())
