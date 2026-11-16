import pytest
import os
import shutil
import tempfile
import sqlite3
from datetime import datetime, timezone
from sqlalchemy import text

from app.db.database import (
    bind_test_database,
    enable_production_db_guard,
    disable_production_db_guard,
    dispose_database,
    init_db,
    async_session_factory,
    get_active_db_path,
    is_production_db_path,
)
from app.models.db_models import SignalRecord, MarketCandle, Stock

# ---------------------------------------------------------------------------
# Strict Production Database Protection & Interception
# ---------------------------------------------------------------------------
_orig_sqlite_connect = sqlite3.connect

def _guarded_sqlite_connect(database, *args, **kwargs):
    if is_production_db_path(str(database)):
        raise RuntimeError(
            f"SAFETY VIOLATION: Automated test attempted to connect to production database: {database}"
        )
    return _orig_sqlite_connect(database, *args, **kwargs)

sqlite3.connect = _guarded_sqlite_connect

# Global isolated test database created for the entire test session
_TEST_TMP_DIR = tempfile.mkdtemp(prefix="aivolve_isolated_test_db_")
_TEST_DB_PATH = os.path.normpath(os.path.join(_TEST_TMP_DIR, "aivolve_test.db"))

# Redirect database engines and factories before any test module is loaded
bind_test_database(_TEST_DB_PATH)
enable_production_db_guard()


@pytest.fixture(autouse=True)
async def setup_test_db():
    """Initializes schema and baseline test records in isolated temporary database."""
    await init_db()

    # Seed baseline records if needed for tests that verify data presence
    async with async_session_factory() as session:
        sig_cnt = (await session.execute(text("SELECT COUNT(*) FROM signals"))).scalar()
        if sig_cnt == 0:
            sample_stock = Stock(
                id="TEST-STOCK-001",
                symbol="NIFTY 50",
                company_name="Nifty 50 Index",
                sector="Index",
            )
            sample_sig = SignalRecord(
                id="TEST-INIT-SIG-001",
                symbol="NIFTY 50",
                contract_symbol="NIFTY26OCT24500CE",
                instrument_token="TEST-TOKEN-INIT",
                strike=24500.0,
                expiry="2026-10-26",
                option_type="CE",
                underlying_price_at_signal=24500.0,
                signal_premium=150.0,
                entry_zone_min=145.0,
                entry_zone_max=155.0,
                entry_trigger_condition="5M close in entry zone",
                stop_loss_premium=120.0,
                target_1_premium=195.0,
                target_2_premium=230.0,
                target_3_premium=270.0,
                status="ACTIVE",
                created_at=datetime.now(timezone.utc),
            )
            sample_candle = MarketCandle(
                id="TEST-CANDLE-001",
                stock_id="TEST-STOCK-001",
                symbol="NIFTY 50",
                timeframe="15m",
                timestamp=datetime.now(timezone.utc),
                open=24500.0,
                high=24550.0,
                low=24480.0,
                close=24520.0,
                volume=1000.0,
            )
            session.add(sample_stock)
            session.add(sample_sig)
            session.add(sample_candle)
            await session.commit()


def pytest_sessionfinish(session, exitstatus):
    """Cleans up isolated temporary database and engines after test session completes."""
    disable_production_db_guard()
    sqlite3.connect = _orig_sqlite_connect
    try:
        shutil.rmtree(_TEST_TMP_DIR, ignore_errors=True)
    except Exception:
        pass
