import os
import json
import uuid
import hashlib
import pytest
import threading
import time
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.options.paper_trading.paper_engine import PaperTradingEngine, STORAGE_PATH
from app.options.paper_trading.ml_feedback_engine import (
    MLFeedbackEngine,
    DATASET_PATH,
    KNOWLEDGE_PATH,
    BASELINE_TRAINING_RECORDS,
)
from app.db.database import (
    engine,
    ledger_engine,
    async_session_factory,
    ledger_session_factory,
    critical_ledger_transaction,
    commit_critical_ledger,
)
from app.models.db_models import SignalRecord
from app.data.market_calendar import MarketCalendar


# =====================================================================
# ISSUE 2 Tests: Paper Trading JSON Atomic Persistence
# =====================================================================

def test_json_serialization_failure_preserves_valid_file(tmp_path):
    """Verify that if serialization fails, the previous valid file is strictly preserved."""
    test_file = str(tmp_path / "paper_records_test.json")
    engine_inst = PaperTradingEngine(storage_path=test_file)
    engine_inst.state["balance"] = 99999.0
    engine_inst._save_state()

    assert os.path.exists(test_file)
    with open(test_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["balance"] == 99999.0

    # Inject an un-serializable object
    engine_inst.state["invalid_object"] = object()
    with pytest.raises(Exception):
        engine_inst._save_state()

    # Verify original file is still intact and completely valid
    with open(test_file, "r", encoding="utf-8") as f:
        preserved_data = json.load(f)
    assert preserved_data["balance"] == 99999.0
    assert "invalid_object" not in preserved_data


def test_simulated_failure_during_temp_write(tmp_path, monkeypatch):
    """Verify that failure during write/fsync preserves existing file and cleans up temp files."""
    test_file = str(tmp_path / "paper_records_test.json")
    engine_inst = PaperTradingEngine(storage_path=test_file)
    engine_inst.state["balance"] = 88888.0
    engine_inst._save_state()

    # Monkeypatch os.fsync to simulate sudden I/O failure
    def mock_fsync(fd):
        raise OSError("Simulated hardware disk I/O failure")

    monkeypatch.setattr(os, "fsync", mock_fsync)

    engine_inst.state["balance"] = 77777.0
    with pytest.raises(OSError, match="Simulated hardware disk I/O failure"):
        engine_inst._save_state()

    # Original file must retain 88888.0, NOT 77777.0
    with open(test_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["balance"] == 88888.0

    # Verify no dangling temporary files remain
    temp_files = [f for f in os.listdir(tmp_path) if f.startswith(".paper_state_") and f.endswith(".tmp")]
    assert len(temp_files) == 0


def test_atomic_replacement_behavior(tmp_path):
    """Verify atomic file replacement and monotonic state versioning."""
    test_file = str(tmp_path / "paper_records_test.json")
    engine_inst = PaperTradingEngine(storage_path=test_file)

    initial_version = engine_inst.state.get("stateVersion", 0)
    engine_inst._save_state()
    assert engine_inst.state["stateVersion"] == initial_version + 1

    engine_inst.state["balance"] = 102500.0
    engine_inst._save_state()
    assert engine_inst.state["stateVersion"] == initial_version + 2

    with open(test_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["balance"] == 102500.0
    assert data["stateVersion"] == initial_version + 2


def test_temp_file_cleanup(tmp_path):
    """Verify engine cleans up stale temporary files left by prior crashes."""
    stale_tmp = tmp_path / ".paper_state_deadbeef1234.tmp"
    stale_tmp.write_text("partial corrupted data", encoding="utf-8")
    assert os.path.exists(str(stale_tmp))

    test_file = str(tmp_path / "paper_records_test.json")
    engine_inst = PaperTradingEngine(storage_path=test_file)
    engine_inst._cleanup_stale_temp_files()

    assert not os.path.exists(str(stale_tmp))


def test_concurrent_save_protection(tmp_path):
    """Verify thread-safe locking and monotonic state sequencing under concurrency."""
    test_file = str(tmp_path / "paper_records_test.json")
    engine_inst = PaperTradingEngine(storage_path=test_file)
    errors = []

    def worker(worker_id):
        try:
            for i in range(15):
                engine_inst.state[f"worker_{worker_id}_run"] = i
                engine_inst._save_state()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    # Confirm valid JSON on disk
    with open(test_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["stateVersion"] >= 75


def test_version_conflict_rejection(tmp_path):
    """Verify that attempting to save with a stale expected_version is rejected."""
    test_file = str(tmp_path / "paper_records_test.json")
    engine_inst = PaperTradingEngine(storage_path=test_file)
    engine_inst._save_state()
    current_ver = engine_inst._state_version

    # Attempting to save with a stale expected_version must raise ValueError
    with pytest.raises(ValueError, match="State version conflict"):
        engine_inst._save_state(expected_version=current_ver - 1)


def test_windows_transient_lock_retry(tmp_path, monkeypatch):
    """Verify retry backoff when os.replace encounters a transient PermissionError (Windows file lock)."""
    test_file = str(tmp_path / "paper_records_test.json")
    engine_inst = PaperTradingEngine(storage_path=test_file)
    engine_inst.state["balance"] = 55555.0

    original_replace = os.replace
    attempts = [0]

    def mock_replace(src, dst):
        attempts[0] += 1
        if attempts[0] < 3:
            raise PermissionError("[WinError 32] The process cannot access the file because it is being used")
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", mock_replace)
    engine_inst._save_state()

    assert attempts[0] == 3
    with open(test_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["balance"] == 55555.0


def test_restart_recovery_of_positions_and_balance(tmp_path):
    """Verify open positions, lots, and balance survive application restart."""
    test_file = str(tmp_path / "paper_records_test.json")
    engine_1 = PaperTradingEngine(storage_path=test_file)
    engine_1.state["balance"] = 94500.0
    test_pos = {
        "id": "PT-RECOVERY-001",
        "contractSymbol": "NIFTY06NOV2624500CE",
        "lots": 2,
        "entryPremium": 125.0,
        "status": "OPEN",
    }
    engine_1.state["openPositions"].append(test_pos)
    engine_1._save_state()

    # Re-instantiate engine (simulating backend cold start)
    engine_2 = PaperTradingEngine(storage_path=test_file)
    assert engine_2.state["balance"] == 94500.0
    assert len(engine_2.state["openPositions"]) == 1
    assert engine_2.state["openPositions"][0]["id"] == "PT-RECOVERY-001"
    assert engine_2.state["openPositions"][0]["lots"] == 2


def test_multi_threaded_engine_mutations_protected_by_lock(tmp_path):
    """Verify all mutating methods execute safely under multi-threaded concurrency without race conditions."""
    test_file = str(tmp_path / "paper_records_test.json")
    engine_inst = PaperTradingEngine(storage_path=test_file)
    engine_inst.state["balance"] = 200000.0
    engine_inst._save_state()

    errors = []

    def run_trading_sequence(thread_id):
        try:
            # 1. Open simulated position
            sym = f"NIFTY_TEST_{thread_id}"
            res = engine_inst.open_position(
                instrument="NIFTY 50",
                contract_symbol=sym,
                bias="CE",
                strike=24500.0,
                expiry="06NOV2026",
                entry_premium=100.0,
                lots=2,
                lot_size=25,
                stop_loss=80.0,
                target_1=120.0,
                target_2=150.0,
                market_features={"allowAfterHoursSimulation": True, "isTradeQualified": True},
            )
            assert res["success"] is True
            pos_id = res["position"]["id"]

            # 2. Update monitoring
            engine_inst.update_live_monitoring(sym, current_ltp=110.0)

            # 3. Partial exit
            engine_inst.execute_partial_exit(pos_id, exit_lots=1, exit_price=120.0)

            # 4. Close remaining
            engine_inst.close_position(pos_id, exit_price=130.0, exit_reason="Manual Close")

        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=run_trading_sequence, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    metrics = engine_inst.get_dashboard_metrics()
    assert metrics["closedTradesCount"] == 4
    assert metrics["openTradesCount"] == 0

    # Verify on-disk file is fully consistent with in-memory state
    with open(test_file, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    assert len(disk_data["closedTrades"]) == 4
    assert len(disk_data["openPositions"]) == 0
    assert disk_data["balance"] == engine_inst.state["balance"]

    # Verify ML feedback artifacts stayed strictly inside tmp_path
    tmp_root = os.path.normcase(os.path.abspath(tmp_path))
    assert os.path.dirname(os.path.normcase(os.path.abspath(engine_inst.ml_dataset_path))) == tmp_root
    assert os.path.dirname(os.path.normcase(os.path.abspath(engine_inst.ml_knowledge_path))) == tmp_root
    assert os.path.exists(engine_inst.ml_dataset_path)
    assert os.path.exists(engine_inst.ml_knowledge_path)
    with open(engine_inst.ml_dataset_path, "r", encoding="utf-8") as f:
        isolated_ds = json.load(f)
    assert len(isolated_ds) == len(BASELINE_TRAINING_RECORDS) + 4


# =====================================================================
# ML Feedback & Dataset Path Isolation Regression Tests
# =====================================================================

def _file_sha256_or_missing(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_temp_paper_engine_does_not_write_to_production_ml_files(tmp_path):
    """Temporary PaperTradingEngine instances must never mutate production ML JSON files."""
    prod_ds_before = _file_sha256_or_missing(DATASET_PATH)
    prod_kb_before = _file_sha256_or_missing(KNOWLEDGE_PATH)

    engine_inst = PaperTradingEngine(storage_path=str(tmp_path / "isolated_paper.json"))
    open_res = engine_inst.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY_ISOLATION_SINGLE",
        bias="CE",
        strike=24500.0,
        expiry="06NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=25,
        stop_loss=80.0,
        target_1=120.0,
        target_2=140.0,
        market_features={"allowAfterHoursSimulation": True, "isTradeQualified": True},
    )
    assert open_res["success"] is True
    close_res = engine_inst.close_position(
        open_res["position"]["id"], exit_price=125.0, exit_reason="Isolation Verification"
    )
    assert close_res["success"] is True

    assert os.path.exists(engine_inst.ml_dataset_path)
    assert os.path.exists(engine_inst.ml_knowledge_path)
    assert _file_sha256_or_missing(DATASET_PATH) == prod_ds_before
    assert _file_sha256_or_missing(KNOWLEDGE_PATH) == prod_kb_before


def test_explicit_ml_paths_and_feedback_engine_isolation(tmp_path):
    """Explicit ML dataset and learned-knowledge paths isolate both engine hooks and direct ML calls."""
    prod_ds_before = _file_sha256_or_missing(DATASET_PATH)
    prod_kb_before = _file_sha256_or_missing(KNOWLEDGE_PATH)

    storage_file = str(tmp_path / "paper_custom.json")
    custom_ds = str(tmp_path / "nested" / "custom_dataset.json")
    custom_kb = str(tmp_path / "nested" / "custom_knowledge.json")

    engine_inst = PaperTradingEngine(
        storage_path=storage_file,
        ml_dataset_path=custom_ds,
        ml_knowledge_path=custom_kb,
    )
    assert os.path.abspath(engine_inst.ml_dataset_path) == os.path.abspath(custom_ds)
    assert os.path.abspath(engine_inst.ml_knowledge_path) == os.path.abspath(custom_kb)

    open_res = engine_inst.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY_CUSTOM_ML_PATH",
        bias="PE",
        strike=24500.0,
        expiry="06NOV2026",
        entry_premium=110.0,
        lots=1,
        lot_size=25,
        stop_loss=90.0,
        target_1=135.0,
        target_2=160.0,
        market_features={"allowAfterHoursSimulation": True, "isTradeQualified": True},
    )
    assert open_res["success"] is True
    close_res = engine_inst.close_position(
        open_res["position"]["id"], exit_price=135.0, exit_reason="Target 1 Hit"
    )
    assert close_res["success"] is True

    ds = MLFeedbackEngine.load_dataset(dataset_path=custom_ds)
    assert len(ds) == len(BASELINE_TRAINING_RECORDS) + 1
    assert ds[-1]["contract"] == "NIFTY_CUSTOM_ML_PATH"

    kb = MLFeedbackEngine.get_what_ai_learned(knowledge_path=custom_kb, dataset_path=custom_ds)
    assert kb["totalTrainingSamples"] == len(BASELINE_TRAINING_RECORDS) + 1

    train_res = MLFeedbackEngine.train_models(ds, knowledge_path=custom_kb)
    assert train_res["sampleCount"] == len(BASELINE_TRAINING_RECORDS) + 1

    assert _file_sha256_or_missing(DATASET_PATH) == prod_ds_before
    assert _file_sha256_or_missing(KNOWLEDGE_PATH) == prod_kb_before


def test_concurrent_test_instances_cannot_leak_into_production(tmp_path):
    """Multiple concurrent test PaperTradingEngine instances stay isolated with zero production leakage."""
    prod_ds_before = _file_sha256_or_missing(DATASET_PATH)
    prod_kb_before = _file_sha256_or_missing(KNOWLEDGE_PATH)

    errors = []
    engines = []
    engines_lock = threading.Lock()

    def worker(worker_idx: int):
        try:
            worker_dir = tmp_path / f"worker_{worker_idx}"
            worker_dir.mkdir(parents=True, exist_ok=True)
            eng = PaperTradingEngine(storage_path=str(worker_dir / "paper.json"))
            eng.state["balance"] = 300000.0
            with engines_lock:
                engines.append((worker_idx, eng))

            for trade_num in range(3):
                open_res = eng.open_position(
                    instrument="NIFTY 50",
                    contract_symbol=f"NIFTY_CONC_{worker_idx}_{trade_num}",
                    bias="CE",
                    strike=24500.0,
                    expiry="06NOV2026",
                    entry_premium=100.0,
                    lots=1,
                    lot_size=25,
                    stop_loss=80.0,
                    target_1=120.0,
                    target_2=140.0,
                    market_features={"allowAfterHoursSimulation": True, "isTradeQualified": True},
                )
                assert open_res["success"] is True
                close_res = eng.close_position(
                    open_res["position"]["id"], exit_price=125.0, exit_reason="Concurrent Close"
                )
                assert close_res["success"] is True
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(engines) == 4

    seen_ds_paths = set()
    seen_kb_paths = set()
    for worker_idx, eng in engines:
        ds_abs = os.path.abspath(eng.ml_dataset_path)
        kb_abs = os.path.abspath(eng.ml_knowledge_path)
        assert ds_abs.startswith(os.path.abspath(tmp_path))
        assert kb_abs.startswith(os.path.abspath(tmp_path))
        seen_ds_paths.add(ds_abs)
        seen_kb_paths.add(kb_abs)
        with open(ds_abs, "r", encoding="utf-8") as f:
            worker_ds = json.load(f)
        assert len(worker_ds) == len(BASELINE_TRAINING_RECORDS) + 3
        contracts = {rec.get("contract") for rec in worker_ds[-3:]}
        assert contracts == {f"NIFTY_CONC_{worker_idx}_{k}" for k in range(3)}

    assert len(seen_ds_paths) == 4
    assert len(seen_kb_paths) == 4
    assert _file_sha256_or_missing(DATASET_PATH) == prod_ds_before
    assert _file_sha256_or_missing(KNOWLEDGE_PATH) == prod_kb_before


def test_production_initialization_resolves_intended_paths():
    """Default PaperTradingEngine initialization still resolves intended production paths."""
    prod_engine = PaperTradingEngine()
    assert os.path.normcase(os.path.abspath(prod_engine.storage_path)) == os.path.normcase(os.path.abspath(STORAGE_PATH))
    assert os.path.normcase(os.path.abspath(prod_engine.ml_dataset_path)) == os.path.normcase(os.path.abspath(DATASET_PATH))
    assert os.path.normcase(os.path.abspath(prod_engine.ml_knowledge_path)) == os.path.normcase(os.path.abspath(KNOWLEDGE_PATH))

    explicit_prod = PaperTradingEngine(storage_path=STORAGE_PATH)
    assert os.path.normcase(os.path.abspath(explicit_prod.ml_dataset_path)) == os.path.normcase(os.path.abspath(DATASET_PATH))
    assert os.path.normcase(os.path.abspath(explicit_prod.ml_knowledge_path)) == os.path.normcase(os.path.abspath(KNOWLEDGE_PATH))


# =====================================================================
# ISSUE 1 Tests: SQLite Critical Ledger Durability & Dual Engine
# =====================================================================

@pytest.mark.asyncio
async def test_sqlite_pragma_safety_level_exception_inside_transaction():
    """
    Directly demonstrates the SQLite C engine restriction:
    Once write operations (DML) are staged in a transaction, executing
    'PRAGMA synchronous = FULL' raises:
    '(sqlite3.OperationalError) Safety level may not be changed inside a transaction'.
    
    This proves why runtime pragma switching inside transactions was fundamentally flawed
    and why dedicated connection pools pre-configured at connect time are mandatory.
    """
    async with async_session_factory() as session:
        test_sig = SignalRecord(
            id=f"test-dml-{uuid.uuid4().hex[:8]}",
            symbol="NIFTY 50",
            contract_symbol="NIFTY09NOV2624500CE",
            exchange="NFO",
            instrument_token="777777",
            strike=24500.0,
            expiry="09NOV2026",
            option_type="CE",
            status="WAITING_FOR_ENTRY",
            underlying_price_at_signal=24500.0,
            signal_premium=150.0,
            entry_zone_min=140.0,
            entry_zone_max=160.0,
            entry_trigger_condition="Test condition",
            stop_loss_premium=120.0,
            target_1_premium=190.0,
            target_2_premium=230.0,
            target_3_premium=270.0,
        )
        session.add(test_sig)
        await session.flush()  # Stages write transaction into SQLite engine

        # Attempting to alter synchronous inside an active write transaction must raise OperationalError
        with pytest.raises(Exception) as exc_info:
            await session.execute(text("PRAGMA synchronous = FULL;"))

        err_msg = str(exc_info.value).lower()
        assert "safety level may not be changed inside a transaction" in err_msg

        # Roll back to clean up
        await session.rollback()


@pytest.mark.asyncio
async def test_dual_engine_durability_and_zero_pool_leakage():
    """
    Verifies the dual-engine connection architecture:
    1. General engine pool operates at PRAGMA synchronous == 1 (NORMAL) for tick performance.
    2. Ledger engine pool operates at PRAGMA synchronous == 2 (FULL) for guaranteed non-volatile disk flush.
    3. Sessions checked out from either pool NEVER leak PRAGMA settings across pools.
    """
    # 1. Check general pool sessions
    async with async_session_factory() as general_session:
        res_gen = await general_session.execute(text("PRAGMA synchronous;"))
        assert res_gen.scalar() == 1  # NORMAL (1)

    # 2. Check ledger pool sessions
    async with ledger_session_factory() as ledger_session:
        res_led = await ledger_session.execute(text("PRAGMA synchronous;"))
        assert res_led.scalar() == 2  # FULL (2)

    # 3. Check critical_ledger_transaction context manager provides synchronous == 2
    async with critical_ledger_transaction() as crit_session:
        res_crit = await crit_session.execute(text("PRAGMA synchronous;"))
        assert res_crit.scalar() == 2  # FULL (2)

    # 4. Check that returning connections to general pool leaves PRAGMA strictly at 1 (NORMAL)
    async with async_session_factory() as general_session_2:
        res_gen_2 = await general_session_2.execute(text("PRAGMA synchronous;"))
        assert res_gen_2.scalar() == 1  # Zero leakage!


@pytest.mark.asyncio
async def test_critical_sqlite_transaction_rollback():
    """Verify critical ledger transaction rollback leaves no inconsistent records."""
    test_sig_id = f"test-rb-{uuid.uuid4().hex[:8]}"

    with pytest.raises(RuntimeError, match="Simulated execution abort"):
        async with critical_ledger_transaction() as session:
            sig = SignalRecord(
                id=test_sig_id,
                symbol="NIFTY 50",
                contract_symbol="NIFTY09NOV2624500CE",
                exchange="NFO",
                instrument_token="999999",
                strike=24500.0,
                expiry="09NOV2026",
                option_type="CE",
                status="WAITING_FOR_ENTRY",
                underlying_price_at_signal=24500.0,
                signal_premium=150.0,
                entry_zone_min=140.0,
                entry_zone_max=160.0,
                entry_trigger_condition="Test condition",
                stop_loss_premium=120.0,
                target_1_premium=190.0,
                target_2_premium=230.0,
                target_3_premium=270.0,
            )
            session.add(sig)
            raise RuntimeError("Simulated execution abort")

    # Verify the record was rolled back completely and does not exist in the database
    async with async_session_factory() as session:
        check = await session.get(SignalRecord, test_sig_id)
        assert check is None


@pytest.mark.asyncio
async def test_commit_critical_ledger_persists_cleanly():
    """Verify commit_critical_ledger cleanly commits records using ledger pool."""
    test_sig_id = f"test-comm-{uuid.uuid4().hex[:8]}"

    async with ledger_session_factory() as session:
        sig = SignalRecord(
            id=test_sig_id,
            symbol="NIFTY 50",
            contract_symbol="NIFTY09NOV2624500CE",
            exchange="NFO",
            instrument_token="888888",
            strike=24500.0,
            expiry="09NOV2026",
            option_type="CE",
            status="WAITING_FOR_ENTRY",
            underlying_price_at_signal=24500.0,
            signal_premium=150.0,
            entry_zone_min=140.0,
            entry_zone_max=160.0,
            entry_trigger_condition="Test condition",
            stop_loss_premium=120.0,
            target_1_premium=190.0,
            target_2_premium=230.0,
            target_3_premium=270.0,
        )
        session.add(sig)
        await commit_critical_ledger(session)

    # Verify signal persisted cleanly
    async with async_session_factory() as session:
        persisted = await session.get(SignalRecord, test_sig_id)
        assert persisted is not None
        assert persisted.contract_symbol == "NIFTY09NOV2624500CE"
        # Cleanup
        await session.delete(persisted)
        await session.commit()
