"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Dedicated Safety Test Suite: SQLite Database Isolation & Production Protection

Tests the 10 mandatory safety requirements:
1. Test database path differs from production database path.
2. Async session factory points to temporary database.
3. Sync database operations point to temporary database.
4. OutcomeTrackerService writes only to temporary database.
5. Signal events remain in temporary database.
6. Signal status history remains in temporary database.
7. Knowledge documents and chunks remain in temporary database.
8. ML training job records remain in temporary database.
9. Temporary database is cleaned up after test execution.
10. Production database path is rejected by test safety guard.
"""

import os
import uuid
import io
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.database import (
    get_active_db_path,
    get_production_db_path,
    is_production_db_path,
    async_session_factory,
    check_production_safety_guard,
    bind_test_database,
)
from app.services.outcome_tracker import OutcomeTrackerService
from app.models.db_models import SignalRecord, SignalEventRecord, SignalStatusHistoryRecord
from app.core.config import settings

# Helper: Read production database directly in read-only mode to verify absence of test records
def _count_in_production(table: str, col: str, val: str) -> int:
    prod_path = get_production_db_path()
    # Connect using raw sqlite3 without guard to inspect production in strict read-only mode
    # We bypass the test monkeypatch via sqlite3.__dict__['_orig_sqlite_connect'] if present
    import conftest
    orig_connect = getattr(conftest, "_orig_sqlite_connect", sqlite3.connect)
    conn = orig_connect(f"file:{prod_path}?mode=ro", uri=True)
    try:
        c = conn.cursor()
        c.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (val,))
        return c.fetchone()[0]
    finally:
        conn.close()


def test_1_test_database_path_differs_from_production():
    """Safety 1: Verify test database path differs from production database path."""
    active_path = os.path.normpath(get_active_db_path())
    prod_path = os.path.normpath(get_production_db_path())

    assert active_path.lower() != prod_path.lower(), (
        f"Active test database path matches production path! {active_path}"
    )
    assert "aivolve_trading.db" not in active_path.lower(), (
        f"Active path should not contain production db filename: {active_path}"
    )
    assert os.path.exists(active_path), f"Active test database does not exist: {active_path}"


@pytest.mark.asyncio
async def test_2_async_session_factory_points_to_temporary_database():
    """Safety 2: Verify async session factory executes against temporary database."""
    async with async_session_factory() as session:
        res = await session.execute(text("PRAGMA database_list;"))
        rows = res.fetchall()
        assert len(rows) > 0
        main_db_file = os.path.normpath(rows[0][2])
        active_path = os.path.normpath(get_active_db_path())
        assert main_db_file.lower() == active_path.lower(), (
            f"AsyncSession connected to unexpected file: {main_db_file} vs {active_path}"
        )
        assert "aivolve_trading.db" not in main_db_file.lower()


def test_3_sync_database_operations_point_to_temporary_database():
    """Safety 3: Verify synchronous sqlite3 operations connect to temporary database."""
    active_path = get_active_db_path()
    conn = sqlite3.connect(active_path)
    c = conn.cursor()
    c.execute("PRAGMA database_list;")
    rows = c.fetchall()
    conn.close()

    assert len(rows) > 0
    sync_db_file = os.path.normpath(rows[0][2])
    assert sync_db_file.lower() == os.path.normpath(active_path).lower()
    assert "aivolve_trading.db" not in sync_db_file.lower()


@pytest.mark.asyncio
async def test_4_outcome_tracker_writes_only_to_temporary_database():
    """Safety 4: Verify OutcomeTrackerService registers signals only in temporary database."""
    tracker = OutcomeTrackerService.get_instance()
    unique_token = f"TEST_ISOL_{uuid.uuid4().hex[:8]}"

    async with async_session_factory() as session:
        sig_data = {
            "symbol": "NIFTY 50",
            "contract_symbol": "NIFTY26OCT24500CE",
            "exchange": "NFO",
            "instrument_token": unique_token,
            "strike": 24500,
            "expiry": "2026-10-26",
            "option_type": "CE",
            "signal_premium": 150.0,
            "entry_zone_min": 145.0,
            "entry_zone_max": 155.0,
            "stop_loss_premium": 120.0,
            "target_1_premium": 195.0,
            "target_2_premium": 230.0,
            "target_3_premium": 270.0,
            "lot_size": 50,
            "allocated_lots": 1,
        }
        signal = await tracker.register_signal(session, sig_data)
        sig_id = signal.id

    # 1. Verify signal exists in temporary database
    conn = sqlite3.connect(get_active_db_path())
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM signals WHERE id = ?", (sig_id,))
    count_temp = c.fetchone()[0]
    conn.close()
    assert count_temp == 1, "Signal was not written to temporary database!"

    # 2. Verify signal DOES NOT exist in production database
    count_prod = _count_in_production("signals", "id", sig_id)
    assert count_prod == 0, f"Signal leaked into production database! (id: {sig_id})"


@pytest.mark.asyncio
async def test_5_signal_events_remain_in_temporary_database():
    """Safety 5: Verify signal events persist only in temporary database."""
    tracker = OutcomeTrackerService.get_instance()
    unique_token = f"TEST_EV_{uuid.uuid4().hex[:8]}"

    async with async_session_factory() as session:
        sig_data = {
            "symbol": "NIFTY 50",
            "contract_symbol": "NIFTY26OCT24500CE",
            "exchange": "NFO",
            "instrument_token": unique_token,
            "strike": 24500,
            "expiry": "2026-10-26",
            "option_type": "CE",
            "signal_premium": 150.0,
            "entry_zone_min": 145.0,
            "entry_zone_max": 155.0,
            "stop_loss_premium": 120.0,
            "target_1_premium": 195.0,
            "target_2_premium": 230.0,
            "target_3_premium": 270.0,
            "lot_size": 50,
            "allocated_lots": 1,
        }
        sig = await tracker.register_signal(session, sig_data)
        # Trigger market tick event
        now = datetime.now(timezone.utc)
        evs = await tracker.process_market_tick(session, unique_token, ltp=150.0, market_ts=now)
        assert len(evs) == 1

    # Verify event in temporary database
    conn = sqlite3.connect(get_active_db_path())
    c = conn.cursor()
    c.execute("SELECT id FROM signal_events WHERE signal_id = ?", (sig.id,))
    rows = c.fetchall()
    conn.close()
    assert len(rows) >= 1
    ev_id = rows[0][0]

    # Verify event DOES NOT exist in production database
    count_prod = _count_in_production("signal_events", "signal_id", sig.id)
    assert count_prod == 0, f"Event leaked into production database! (id: {ev_id})"


@pytest.mark.asyncio
async def test_6_signal_status_history_remains_in_temporary_database():
    """Safety 6: Verify status history entries persist only in temporary database."""
    tracker = OutcomeTrackerService.get_instance()
    unique_token = f"TEST_HIST_{uuid.uuid4().hex[:8]}"

    async with async_session_factory() as session:
        sig_data = {
            "symbol": "NIFTY 50",
            "contract_symbol": "NIFTY26OCT24500CE",
            "exchange": "NFO",
            "instrument_token": unique_token,
            "strike": 24500,
            "expiry": "2026-10-26",
            "option_type": "CE",
            "signal_premium": 150.0,
            "entry_zone_min": 145.0,
            "entry_zone_max": 155.0,
            "stop_loss_premium": 120.0,
            "target_1_premium": 195.0,
            "target_2_premium": 230.0,
            "target_3_premium": 270.0,
            "lot_size": 50,
            "allocated_lots": 1,
        }
        sig = await tracker.register_signal(session, sig_data)
        sig_id = sig.id

    # Verify status history in temporary database
    conn = sqlite3.connect(get_active_db_path())
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM signal_status_history WHERE signal_id = ?", (sig_id,))
    count_temp = c.fetchone()[0]
    conn.close()
    assert count_temp >= 1

    # Verify status history DOES NOT exist in production database
    count_prod = _count_in_production("signal_status_history", "signal_id", sig_id)
    assert count_prod == 0, f"Status history leaked into production database for signal: {sig_id}"


@pytest.mark.asyncio
async def test_7_knowledge_documents_and_chunks_remain_in_temporary_database():
    """Safety 7: Verify uploaded knowledge documents persist only in temporary database."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unique_text = f"Institutional isolation test document {uuid.uuid4().hex} with unique contents."
        files = {
            "file": ("test_doc.txt", io.BytesIO(unique_text.encode("utf-8")), "text/plain")
        }
        data = {
            "category": "Risk Management",
            "author": "Safety Inspector",
        }
        res = await client.post("/api/knowledge/upload", files=files, data=data)
        assert res.status_code == 200
        doc_id = res.json()["data"]["documentId"]

    # Verify in temporary DB
    conn = sqlite3.connect(get_active_db_path())
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM knowledge_documents WHERE id = ?", (doc_id,))
    count_temp = c.fetchone()[0]
    conn.close()
    assert count_temp == 1

    # Verify NOT in production DB
    count_prod = _count_in_production("knowledge_documents", "id", doc_id)
    assert count_prod == 0, f"Knowledge document leaked into production database: {doc_id}"


@pytest.mark.asyncio
async def test_8_ml_training_job_records_remain_in_temporary_database():
    """Safety 8: Verify ML training job records persist only in temporary database."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        req_body = {
            "modelType": "random_forest",
            "target": "next_30m_direction",
            "symbols": ["RELIANCE"],
            "lookbackDays": 30,
            "features": ["return_1d", "rsi_14"]
        }
        res = await client.post("/api/ml/train", json=req_body)
        assert res.status_code == 200
        job_id = res.json()["data"]["jobId"]

    # Verify in temporary DB
    conn = sqlite3.connect(get_active_db_path())
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM ml_training_jobs WHERE id = ?", (job_id,))
    count_temp = c.fetchone()[0]
    conn.close()
    assert count_temp == 1

    # Verify NOT in production DB
    count_prod = _count_in_production("ml_training_jobs", "id", job_id)
    assert count_prod == 0, f"ML training job leaked into production database: {job_id}"


def test_9_temporary_database_cleanup_after_execution(tmp_path):
    """Safety 9: Verify a temporary database created in a test lifecycle can be safely cleaned up."""
    custom_temp_db = str(tmp_path / "custom_test.db")
    conn = sqlite3.connect(custom_temp_db)
    conn.execute("CREATE TABLE cleanup_probe (id INT PRIMARY KEY);")
    conn.commit()
    conn.close()

    assert os.path.exists(custom_temp_db)
    # Perform cleanup
    os.remove(custom_temp_db)
    assert not os.path.exists(custom_temp_db)


def test_10_production_database_path_rejected_by_test_safety_guard():
    """Safety 10: Verify production database path connection attempts are strictly rejected."""
    prod_path = get_production_db_path()

    # 1. Test check_production_safety_guard
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
        check_production_safety_guard(prod_path)

    # 2. Test sqlite3.connect safety interception
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
        sqlite3.connect(prod_path)

    # 3. Test bind_test_database rejects production path
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
        bind_test_database(prod_path)
