from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings
from app.core.logging import logger

Base = declarative_base()

# Determine database engine parameters
db_url = settings.DATABASE_URL
connect_args = {}
if "sqlite" in db_url:
    connect_args = {"check_same_thread": False}

try:
    engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
        connect_args=connect_args
    )
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
except Exception as e:
    logger.error(f"Failed to initialize database engine with URL {db_url}: {e}")
    # Fallback to local SQLite
    sqlite_url = "sqlite+aiosqlite:///./aivolve_trading.db"
    logger.info(f"Falling back to local SQLite: {sqlite_url}")
    engine = create_async_engine(
        sqlite_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False}
    )
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for obtaining an async database session.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """
    Create database tables if they do not exist and apply safe incremental migrations.
    Preserves all historical records without data loss.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def migrate_sqlite_columns(connection):
            from sqlalchemy import inspect, text
            inspector = inspect(connection)
            tables = inspector.get_table_names()

            if "signals" in tables:
                existing_cols = {col["name"] for col in inspector.get_columns("signals")}
                migrations = [
                    ("model_version", "VARCHAR(50) DEFAULT 'MODEL_V2.1'"),
                    ("exit_policy_version", "VARCHAR(50) DEFAULT 'EXIT_POLICY_V2.0'"),
                    ("initial_market_state", "VARCHAR(40) DEFAULT 'NO_TRADE'"),
                    ("supporting_factors", "JSON"),
                    ("contradicting_factors", "JSON"),
                ]
                for col_name, col_type in migrations:
                    if col_name not in existing_cols:
                        try:
                            connection.execute(text(f"ALTER TABLE signals ADD COLUMN {col_name} {col_type}"))
                            logger.info(f"Migrated signals table: added column {col_name}")
                        except Exception as e:
                            logger.warning(f"Could not add column {col_name} to signals: {e}")

            if "signal_events" in tables:
                existing_event_cols = {col["name"] for col in inspector.get_columns("signal_events")}
                if "idempotency_key" not in existing_event_cols:
                    try:
                        connection.execute(text("ALTER TABLE signal_events ADD COLUMN idempotency_key VARCHAR(120)"))
                        logger.info("Migrated signal_events table: added idempotency_key column")
                    except Exception as e:
                        logger.warning(f"Could not add idempotency_key to signal_events: {e}")

        await conn.run_sync(migrate_sqlite_columns)
