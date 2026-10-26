import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import pandas as pd
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.database import async_session_factory
from app.models.db_models import MarketCandle, Stock
from app.data.providers.factory import get_market_data_provider


VALID_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "1d"}


class HistoricalDataService:
    """
    Manages OHLCV candle historical ingestion, validation and storage in PostgreSQL/SQLite.
    - Supported timeframes: 1m, 5m, 15m, 30m, 1h, 1d.
    - Enforces uniqueness constraint on (symbol, timeframe, timestamp) to prevent duplicate candles.
    """

    @classmethod
    def validate_candle(cls, candle: Dict[str, Any]) -> bool:
        """
        Validates OHLCV integrity:
        - All prices > 0
        - High >= Low
        - High >= Open, High >= Close
        - Low <= Open, Low <= Close
        - Volume >= 0
        """
        try:
            o = float(candle["open"])
            h = float(candle["high"])
            l = float(candle["low"])
            c = float(candle["close"])
            v = float(candle.get("volume", 0))

            if o <= 0 or h <= 0 or l <= 0 or c <= 0 or v < 0:
                return False
            if h < l:
                return False
            if h < o or h < c or l > o or l > c:
                return False
            return True
        except (KeyError, ValueError, TypeError):
            return False

    @classmethod
    async def ingest_candles(
        cls,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        session: Optional[AsyncSession] = None
    ) -> int:
        """
        Stores validated candles into PostgreSQL database.
        Skips or ignores duplicate entries via uniqueness check.
        """
        if timeframe not in VALID_TIMEFRAMES:
            logger.warning(f"Unsupported timeframe '{timeframe}', defaulting to 15m")
            timeframe = "15m"

        clean_sym = symbol.upper().strip()
        inserted_count = 0

        async def _persist(s: AsyncSession):
            nonlocal inserted_count
            # Find stock_id
            stmt_stock = select(Stock.id).where(Stock.symbol == clean_sym)
            res = await s.execute(stmt_stock)
            stock_id = res.scalar_one_or_none() or f"temp-{clean_sym}"

            for _, row in df.iterrows():
                ts = pd.to_datetime(row["timestamp"]).to_pydatetime()
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)

                candle_dict = {
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0)),
                }

                if not cls.validate_candle(candle_dict):
                    continue

                # Check if already exists to avoid duplicate
                stmt_check = select(MarketCandle.id).where(
                    and_(
                        MarketCandle.symbol == clean_sym,
                        MarketCandle.timeframe == timeframe,
                        MarketCandle.timestamp == ts,
                    )
                )
                existing = (await s.execute(stmt_check)).scalar_one_or_none()
                if not existing:
                    vwap_val = row.get("vwap")
                    if vwap_val is None or pd.isna(vwap_val):
                        vwap_val = (candle_dict["open"] + candle_dict["high"] + candle_dict["low"] + candle_dict["close"]) / 4

                    new_candle = MarketCandle(
                        id=str(uuid.uuid4()),
                        stock_id=stock_id,
                        symbol=clean_sym,
                        timeframe=timeframe,
                        timestamp=ts,
                        open=candle_dict["open"],
                        high=candle_dict["high"],
                        low=candle_dict["low"],
                        close=candle_dict["close"],
                        volume=candle_dict["volume"],
                        vwap=round(float(vwap_val), 2),
                    )
                    s.add(new_candle)
                    inserted_count += 1

            await s.commit()

        if session:
            await _persist(session)
        else:
            async with async_session_factory() as s:
                await _persist(s)

        return inserted_count

    @classmethod
    async def get_candles(
        cls,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 200,
        session: Optional[AsyncSession] = None
    ) -> pd.DataFrame:
        """
        Retrieves historical candles from database.
        If database is empty for this symbol, fetches from market provider and saves.
        """
        clean_sym = symbol.upper().strip()

        async def _query(s: AsyncSession) -> List[MarketCandle]:
            stmt = (
                select(MarketCandle)
                .where(
                    and_(
                        MarketCandle.symbol == clean_sym,
                        MarketCandle.timeframe == timeframe,
                    )
                )
                .order_by(MarketCandle.timestamp.asc())
                .limit(limit)
            )
            res = await s.execute(stmt)
            return res.scalars().all()

        if session:
            candles = await _query(session)
        else:
            async with async_session_factory() as s:
                candles = await _query(s)

        if candles and len(candles) >= 15:
            records = [
                {
                    "timestamp": c.timestamp,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                    "vwap": c.vwap,
                }
                for c in candles
            ]
            return pd.DataFrame(records)

        # Ingest from market data provider
        provider = get_market_data_provider()
        to_date = datetime.now(timezone.utc)
        from_date = to_date - timedelta(days=90)

        df = await provider.get_historical_candles(clean_sym, timeframe, from_date, to_date)
        if not df.empty:
            asyncio_task = cls.ingest_candles(clean_sym, timeframe, df, session)
            import asyncio
            asyncio.create_task(asyncio_task)

        return df
