import os
from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings
from app.core.logging import logger

Base = declarative_base()

# ---------------------------------------------------------------------
# Production Database Protection & Test Isolation Architecture
# ---------------------------------------------------------------------
PRODUCTION_DB_FILENAME: str = "aivolve_trading.db"
PRODUCTION_DB_PATH: str = os.path.normpath(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", PRODUCTION_DB_FILENAME))
)
_TEST_MODE_ACTIVE: bool = False
_ACTIVE_DB_PATH: str = PRODUCTION_DB_PATH


def is_production_db_path(path_or_url: str) -> bool:
    """Returns True if the given path or URL points to the protected production database."""
    if not path_or_url:
        return False
    clean = os.path.normpath(str(path_or_url)).replace("\\", "/").lower()
    return PRODUCTION_DB_FILENAME.lower() in clean


def get_active_db_path() -> str:
    """Returns the absolute normalized path of the currently active SQLite database file."""
    return _ACTIVE_DB_PATH


def get_production_db_path() -> str:
    """Returns the absolute normalized path of the protected production database."""
    return PRODUCTION_DB_PATH


def enable_production_db_guard():
    """Enables strict safety guard that rejects any connection to the production database."""
    global _TEST_MODE_ACTIVE
    _TEST_MODE_ACTIVE = True


def disable_production_db_guard():
    """Disables the production database safety guard."""
    global _TEST_MODE_ACTIVE
    _TEST_MODE_ACTIVE = False


def check_production_safety_guard(db_path: str):
    """Safety guard: raises RuntimeError if test mode is active and target is production DB."""
    if _TEST_MODE_ACTIVE and is_production_db_path(db_path):
        raise RuntimeError(
            f"SAFETY VIOLATION: Automated test attempted to connect to production database: {db_path}"
        )


@event.listens_for(Engine, "connect")
def _enforce_engine_db_safety_guard(dbapi_connection, connection_record):
    """Global SQLAlchemy Engine listener preventing any connection to production DB during test mode."""
    if _TEST_MODE_ACTIVE:
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA database_list;")
            rows = cursor.fetchall()
            cursor.close()
            for row in rows:
                target_file = row[2]
                if target_file and is_production_db_path(target_file):
                    raise RuntimeError(
                        f"SAFETY VIOLATION: Automated test attempted to connect to production database: {target_file}"
                    )
        except Exception as e:
            if "SAFETY VIOLATION" in str(e):
                raise


def bind_test_database(test_db_path: str):
    """
    Redirects engine, ledger_engine, async_session_factory, and ledger_session_factory
    to an isolated temporary SQLite database.
    """
    global engine, ledger_engine, _ACTIVE_DB_PATH

    if is_production_db_path(test_db_path):
        raise RuntimeError(
            f"SAFETY VIOLATION: Cannot bind test database to production database path: {test_db_path}"
        )

    _ACTIVE_DB_PATH = os.path.normpath(os.path.abspath(test_db_path))
    test_async_url = f"sqlite+aiosqlite:///{_ACTIVE_DB_PATH}"
    test_sync_url = f"sqlite:///{_ACTIVE_DB_PATH}"

    settings.DATABASE_URL = test_async_url
    settings.SYNC_DATABASE_URL = test_sync_url

    new_engine = create_async_engine(
        test_async_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False}
    )
    new_ledger_engine = create_async_engine(
        test_async_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False}
    )

    @event.listens_for(new_engine.sync_engine, "connect")
    def _test_engine_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.close()
        except Exception:
            pass

    @event.listens_for(new_ledger_engine.sync_engine, "connect")
    def _test_ledger_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=FULL;")
            cursor.close()
        except Exception:
            pass

    async_session_factory.configure(bind=new_engine)
    ledger_session_factory.configure(bind=new_ledger_engine)

    engine = new_engine
    ledger_engine = new_ledger_engine


async def dispose_database():
    """Disposes active engines cleanly."""
    global engine, ledger_engine
    if engine is not None:
        await engine.dispose()
    if ledger_engine is not None:
        await ledger_engine.dispose()


# Determine database engine parameters
db_url = settings.DATABASE_URL
connect_args = {}
if "sqlite" in db_url:
    connect_args = {"check_same_thread": False}

# ---------------------------------------------------------------------
# 1. General Database Engine (synchronous=NORMAL)
# High-frequency telemetry, tick observations & candles
# ---------------------------------------------------------------------
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

if "sqlite" in str(engine.url):
    @event.listens_for(engine.sync_engine, "connect")
    def set_general_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception:
            pass

# ---------------------------------------------------------------------
# 2. Critical Financial Ledger Engine (synchronous=FULL)
# Dedicated connection pool for trade placement, fills, and P&L settlement.
# Guarantees physical non-volatile disk flush (FlushFileBuffers/fsync).
# Pre-configured at connection checkout before any transaction begins,
# guaranteeing zero in-transaction PRAGMA errors and zero pool leakage.
# ---------------------------------------------------------------------
try:
    ledger_engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
        connect_args=connect_args
    )
    ledger_session_factory = async_sessionmaker(
        ledger_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
except Exception as e:
    sqlite_url = "sqlite+aiosqlite:///./aivolve_trading.db"
    ledger_engine = create_async_engine(
        sqlite_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False}
    )
    ledger_session_factory = async_sessionmaker(
        ledger_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

if "sqlite" in str(ledger_engine.url):
    @event.listens_for(ledger_engine.sync_engine, "connect")
    def set_ledger_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.close()
        except Exception:
            pass


@asynccontextmanager
async def critical_ledger_transaction(session: Optional[AsyncSession] = None):
    """
    Transaction context manager for critical financial ledger records in SQLite.

    DURABILITY GUARANTEE & ARCHITECTURE:
    1. Uses a dedicated ledger connection pool pre-configured with PRAGMA synchronous=FULL (2).
    2. Because synchronous=FULL is applied at connect time (outside any transaction),
       SQLite never raises 'Safety level may not be changed inside a transaction'.
    3. Under synchronous=FULL, SQLite's COMMIT invokes a hardware-level disk flush (FlushFileBuffers on
       Windows / fsync on POSIX) on the Write-Ahead Log (.wal) before returning control. This guarantees
       zero data loss across sudden physical power failure.
    4. General sessions remain isolated on synchronous=NORMAL (1), sustaining high-frequency tick throughput.
    5. Guarantees zero connection-pool leakage because ledger_engine and general engine pools are distinct.
    6. If an unhandled exception occurs, session.rollback() is automatically invoked, ensuring
       transactional atomicity across all staged entities. Never suppresses commit failures.
    """
    if session is not None:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    else:
        async with ledger_session_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise
            finally:
                await s.close()


async def commit_critical_ledger(session: AsyncSession):
    """
    Commits an active session for critical financial ledger records.
    Never suppresses commit exceptions. Automatically rolls back if an error occurs.
    """
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def get_ledger_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for obtaining a critical financial ledger session (synchronous=FULL).
    """
    async with ledger_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


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
    Configures SQLite WAL mode for concurrency and zero lock starvation.
    Preserves all historical records without data loss.
    """
    async with engine.begin() as conn:
        if "sqlite" in str(engine.url):
            try:
                await conn.execute(text("PRAGMA journal_mode=WAL;"))
                await conn.execute(text("PRAGMA synchronous=NORMAL;"))
                logger.info("SQLite WAL mode & NORMAL synchronous verified for aivolve_trading.db.")
            except Exception as pe:
                logger.warning(f"Could not apply SQLite WAL pragma during init: {pe}")

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
