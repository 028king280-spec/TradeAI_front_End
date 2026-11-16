"""
AIVOLVE Quantitative Options Intelligence Engine v3.0
Phase 2 Step 4.2: Dedicated Cross-Platform Storage Permission Security Tests

Verifies genuine, auditable filesystem security for GovernanceLedger across:
  - Windows NTFS DACL Security (Native Windows Execution):
      * Strict canonical SID allowlist model (Process User SID, SYSTEM, Administrators)
      * Token user SID resolution from Windows access token (immune to env spoofing)
      * Rejection of unknown non-broad principals under strict allowlist
      * Rejection of broad principals (Everyone, Users, Authenticated Users, Guests)
      * Detection and rejection of unexpected Deny ACEs
      * Rejection of unexpected inherited ACEs (DACL inheritance protection)
      * Parent directory unauthorized write/modify access rejection
      * Zero silent exception swallowing on reset or grant failures (fail-closed)
      * Reopening preserves secure permissions across instance lifecycles
  - POSIX Cross-Platform Security:
      * NOTICE: These POSIX tests run via unit/mock simulation on this Windows NT host
        to verify cross-platform logic coverage. Native POSIX kernel execution is
        explicitly documented as NOT VERIFIED on Windows.
      * Scoped umask context manager guarantees restoration of prior umask
      * Enforcing and verifying mode 0600 on DB, WAL, and SHM
      * Insecure parent directory detection (group/other write mask 0o022)
      * Parent directory and file ownership validation matching service identity
      * Enforcement failure fail-closed behavior
  - Cross-Platform Lifecycle & Telemetry:
      * Missing database creation handling
      * Existing database opening and WAL checkpoint security maintenance
      * Path sanitization preventing host filesystem disclosure
      * In-memory database virtual memory protection
"""

import os
import sys
import stat
import shutil
import tempfile
import subprocess
from unittest.mock import patch, MagicMock
import pytest

from app.options.storage_security import (
    StoragePermissionManager,
    Win32Ace,
    WELL_KNOWN_SID_SYSTEM,
    WELL_KNOWN_SID_ADMINISTRATORS,
    UNAUTHORIZED_WINDOWS_PRINCIPALS,
    get_process_user_sid,
    get_authorized_windows_sids,
    get_current_windows_user,
    get_authorized_windows_principals,
    get_file_security_descriptor_aces,
    scoped_posix_umask,
    parse_icacls_entries,
)
from app.options.contract_selector import (
    GovernanceLedger,
    set_governance_ledger_db_path,
    get_governance_ledger,
)


# =====================================================================
# 1. Windows NTFS DACL Security Tests (Native Windows Execution)
# =====================================================================

@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS DACL tests run natively on Windows NT")
def test_windows_process_user_sid_resolution_from_token():
    """Resolves actual process identity from Windows access token; immune to USERNAME env spoofing."""
    real_sid = get_process_user_sid()
    assert real_sid is not None
    assert real_sid.startswith("S-1-"), f"Invalid SID format: {real_sid}"
    assert len(real_sid) > 10

    # Verify resolution does NOT rely on USERNAME environment variable
    with patch.dict(os.environ, {"USERNAME": "FORGED_ATTACKER_ACCOUNT", "USERDOMAIN": "EVIL_DOMAIN"}):
        token_sid = get_process_user_sid()
        assert token_sid == real_sid, "get_process_user_sid must query kernel token, not %USERNAME%"


@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS DACL tests run natively on Windows NT")
def test_windows_strict_sid_allowlist_enforced():
    """Authorized SIDs allowlist accepts strictly process token SID, SYSTEM, and Administrators."""
    authorized_sids = get_authorized_windows_sids()
    process_sid = get_process_user_sid().upper()

    assert process_sid in authorized_sids
    assert WELL_KNOWN_SID_SYSTEM in authorized_sids
    assert WELL_KNOWN_SID_ADMINISTRATORS in authorized_sids

    # Verify broad principals are never in the allowlist
    assert "EVERYONE" not in authorized_sids
    assert "USERS" not in authorized_sids
    assert "S-1-1-0" not in authorized_sids        # Everyone SID
    assert "S-1-5-32-545" not in authorized_sids   # Users SID
    assert "S-1-5-11" not in authorized_sids       # Authenticated Users SID


@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS DACL tests run natively on Windows NT")
def test_windows_authorized_dacl_accepted(tmp_path):
    """Enforcing NTFS DACL grants full control strictly to authorized canonical SIDs and passes verification."""
    test_db = str(tmp_path / "test_auth_dacl.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_TEST_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)
    mgr.enforce_storage_permissions()

    ok, reason = mgr.verify_storage_permissions()
    assert ok is True, f"Verification failed unexpectedly: {reason}"
    assert "verified secure" in reason

    status = mgr.get_storage_security_status()
    assert status["platform"] == "windows"
    assert status["secured"] is True
    assert status["verification_passed"] is True
    assert status["failure_reason"] is None


@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS DACL tests run natively on Windows NT")
def test_windows_unknown_non_broad_principal_rejected(tmp_path):
    """
    Strict allowlist model rejects unknown non-broad principals (e.g. S-1-5-19 Local Service)
    that would have bypassed a simple broad-principal blocklist.
    """
    test_db = str(tmp_path / "test_unknown_principal.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_TEST_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)
    mgr.enforce_storage_permissions()

    icacls_bin = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "icacls.exe")

    # Inject an unauthorized, non-broad specific SID: S-1-5-19 (NT AUTHORITY\LOCAL SERVICE)
    subprocess.run([icacls_bin, test_db, "/grant", "*S-1-5-19:(R)"], check=True, capture_output=True)

    ok, reason = mgr.verify_storage_permissions()
    assert ok is False
    assert "Unauthorized ACE detected" in reason
    assert "S-1-5-19" in reason


@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS DACL tests run natively on Windows NT")
def test_windows_unauthorized_broad_principal_rejected(tmp_path):
    """Detecting broad principals (e.g. Users, Everyone) immediately fails verification."""
    test_db = str(tmp_path / "test_unauth_dacl.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_TEST_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)
    mgr.enforce_storage_permissions()

    icacls_bin = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "icacls.exe")

    # 1. Deliberately grant 'Users:(RX)'
    subprocess.run([icacls_bin, test_db, "/grant", "Users:(RX)"], check=True, capture_output=True)
    ok, reason = mgr.verify_storage_permissions()
    assert ok is False
    assert "Unauthorized ACE detected" in reason or "Unauthorized broad principal" in reason

    # 2. Re-enforcing cleans up broad principals and verifies secure
    mgr.enforce_storage_permissions()
    ok, reason = mgr.verify_storage_permissions()
    assert ok is True

    # 3. Grant 'Everyone:(R)' and assert rejection
    subprocess.run([icacls_bin, test_db, "/grant", "Everyone:(R)"], check=True, capture_output=True)
    ok, reason = mgr.verify_storage_permissions()
    assert ok is False
    assert "Unauthorized ACE detected" in reason or "Unauthorized broad principal" in reason


@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS DACL tests run natively on Windows NT")
def test_windows_unexpected_deny_ace_rejected(tmp_path):
    """Unexpected Deny ACEs contradict required permissions and are rejected."""
    test_db = str(tmp_path / "test_deny_ace.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_TEST_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)
    mgr.enforce_storage_permissions()

    icacls_bin = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "icacls.exe")

    # Inject a Deny ACE for SYSTEM
    subprocess.run([icacls_bin, test_db, "/deny", "*S-1-5-18:(W)"], check=True, capture_output=True)

    ok, reason = mgr.verify_storage_permissions()
    assert ok is False
    assert "Unexpected Deny ACE detected" in reason
    assert "S-1-5-18" in reason


@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS DACL tests run natively on Windows NT")
def test_windows_unexpected_inherited_ace_rejected(tmp_path):
    """Inherited ACEs or enabled inheritance without protection are rejected."""
    test_db = str(tmp_path / "test_inherited_ace.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_TEST_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)
    mgr.enforce_storage_permissions()

    # Simulate get_file_security_descriptor_aces returning an inherited ACE
    mock_ace = Win32Ace(sid=WELL_KNOWN_SID_SYSTEM, ace_type=0, ace_flags=0x10, mask=0x1F01FF)  # 0x10 = INHERITED_ACE
    with patch("app.options.storage_security.get_file_security_descriptor_aces", return_value=(True, [mock_ace], True)):
        ok, reason = mgr.verify_storage_permissions()
        assert ok is False
        assert "Unexpected inherited ACE detected" in reason


@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS DACL tests run natively on Windows NT")
def test_windows_reset_failure_stops_execution_without_swallowing(tmp_path):
    """A failure during icacls /reset must stop execution and fail closed without exception swallowing."""
    test_db = str(tmp_path / "test_reset_fail.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_TEST_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)

    def fake_subprocess_run(cmd, *args, **kwargs):
        if "/reset" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr="Simulated /reset access denied")
        return MagicMock(returncode=0, stdout="Successfully processed 1 files; Failed processing 0 files")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        with pytest.raises(ValueError, match="Failed to reset permissions"):
            mgr.enforce_storage_permissions()


@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS DACL tests run natively on Windows NT")
def test_windows_grant_failure_fails_closed(tmp_path):
    """A failure during icacls /grant raises ValueError and fails closed."""
    test_db = str(tmp_path / "test_grant_fail.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_TEST_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)

    def fake_subprocess_run(cmd, *args, **kwargs):
        if "/grant:r" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr="Simulated /grant write fault")
        return MagicMock(returncode=0, stdout="Successfully processed 1 files; Failed processing 0 files")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        with pytest.raises(ValueError, match="Failed to enforce Windows NTFS DACL"):
            mgr.enforce_storage_permissions()


@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS DACL tests run natively on Windows NT")
def test_windows_parent_directory_unauthorized_write_rejected(tmp_path):
    """Parent directory granting write/create/delete access to an unauthorized identity is detected and rejected."""
    dir_path = tempfile.mkdtemp(prefix="aivolve_parent_test_")
    test_db = os.path.join(dir_path, "ledger.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_TEST_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)
    mgr.enforce_storage_permissions()

    icacls_bin = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "icacls.exe")

    try:
        # Initially secure
        ok, _ = mgr.verify_storage_permissions()
        assert ok is True

        # Grant Write permission on parent directory to an unauthorized identity (S-1-5-19 Local Service)
        subprocess.run([icacls_bin, dir_path, "/grant", "*S-1-5-19:(W)"], check=True, capture_output=True)

        ok2, reason2 = mgr.verify_storage_permissions()
        assert ok2 is False
        assert "Insecure parent directory" in reason2
        assert "S-1-5-19" in reason2
        assert "write/create/delete" in reason2
    finally:
        subprocess.run([icacls_bin, dir_path, "/reset"], capture_output=True)
        shutil.rmtree(dir_path, ignore_errors=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS DACL tests run natively on Windows NT")
def test_windows_reopen_preserves_secure_permissions(tmp_path):
    """Reopening an existing GovernanceLedger preserves secure NTFS permissions across instance lifecycles."""
    test_db = str(tmp_path / "test_reopen.db")
    set_governance_ledger_db_path(test_db)

    # Instance 1: Initial creation and write
    ledger1 = get_governance_ledger()
    ledger1.record_processed_id_stub("TEST-REOPEN-NONCE-01")
    st1 = ledger1.get_storage_security_status()
    assert st1["secured"] is True

    # Instance 2: Reopen existing database
    set_governance_ledger_db_path(test_db)
    ledger2 = get_governance_ledger()
    assert ledger2.is_approval_id_processed("TEST-REOPEN-NONCE-01")
    st2 = ledger2.get_storage_security_status()
    assert st2["secured"] is True
    assert st2["verification_passed"] is True


# =====================================================================
# 2. POSIX Security Tests (Simulated / Unit Mocking on Windows NT Host)
# =====================================================================
# NOTICE: These POSIX tests execute via unit mocking on Windows NT host
# to verify cross-platform logic coverage. Native POSIX kernel execution
# is explicitly documented as NOT VERIFIED on this Windows environment.

def test_posix_scoped_umask_restores_prior_umask():
    """scoped_posix_umask sets restrictive umask during execution and guarantees restoring prior umask on exit."""
    recorded_masks = []
    current_fake_umask = 0o022

    def fake_umask(new_mask):
        nonlocal current_fake_umask
        old = current_fake_umask
        current_fake_umask = new_mask
        recorded_masks.append((old, new_mask))
        return old

    with patch("os.name", "posix"), patch("os.umask", side_effect=fake_umask):
        # Normal execution
        with scoped_posix_umask(0o077):
            assert current_fake_umask == 0o077
        assert current_fake_umask == 0o022

        # Exception safety
        try:
            with scoped_posix_umask(0o077):
                assert current_fake_umask == 0o077
                raise RuntimeError("Simulated crash inside block")
        except RuntimeError:
            pass
        assert current_fake_umask == 0o022, "Prior umask must be restored even if an exception occurs"


def test_posix_database_mode_0600(tmp_path):
    """POSIX mode 0600 passes verification."""
    test_db = str(tmp_path / "posix_valid.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)
    mgr._is_windows = False  # Exercise POSIX code path

    mock_file_st = MagicMock(st_mode=stat.S_IFREG | 0o600, st_uid=1000)
    mock_dir_st = MagicMock(st_mode=stat.S_IFDIR | 0o700, st_uid=1000)

    def fake_stat(p):
        return mock_dir_st if os.path.isdir(p) else mock_file_st

    with patch("os.stat", side_effect=fake_stat), patch("os.geteuid", return_value=1000, create=True):
        ok, reason = mgr._verify_posix_permissions()
        assert ok is True
        assert "POSIX mode 0600 verified secure" in reason


def test_posix_insecure_mode_rejected(tmp_path):
    """POSIX files with group/other access bits (e.g. 0644 or 0666) fail verification."""
    test_db = str(tmp_path / "posix_insecure.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)
    mgr._is_windows = False

    mock_file_st = MagicMock(st_mode=stat.S_IFREG | 0o644, st_uid=1000)
    mock_dir_st = MagicMock(st_mode=stat.S_IFDIR | 0o700, st_uid=1000)

    def fake_stat(p):
        return mock_dir_st if os.path.isdir(p) else mock_file_st

    with patch("os.stat", side_effect=fake_stat), patch("os.geteuid", return_value=1000, create=True):
        ok, reason = mgr._verify_posix_permissions()
        assert ok is False
        assert "insecure permissions" in reason
        assert "Group and other access must be 0" in reason


def test_posix_parent_dir_unauthorized_write_mask_0o022_rejected(tmp_path):
    """POSIX parent directory granting group or other write access (mask 0o022) is rejected."""
    test_db = str(tmp_path / "posix_dir_test.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)
    mgr._is_windows = False

    mock_file_st = MagicMock(st_mode=stat.S_IFREG | 0o600, st_uid=1000)
    # Group writable parent directory (0o770)
    mock_dir_st = MagicMock(st_mode=stat.S_IFDIR | 0o770, st_uid=1000)

    def fake_stat(p):
        return mock_dir_st if os.path.isdir(p) else mock_file_st

    with patch("os.stat", side_effect=fake_stat), patch("os.geteuid", return_value=1000, create=True):
        ok, reason = mgr._verify_posix_permissions()
        assert ok is False
        assert "Insecure parent directory" in reason
        assert "group/other write mask 0o022 matched" in reason


def test_posix_parent_dir_unauthorized_owner_rejected(tmp_path):
    """POSIX parent directory owned by an unauthorized UID is rejected."""
    test_db = str(tmp_path / "posix_owner_test.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)
    mgr._is_windows = False

    mock_file_st = MagicMock(st_mode=stat.S_IFREG | 0o600, st_uid=1000)
    mock_dir_st = MagicMock(st_mode=stat.S_IFDIR | 0o700, st_uid=2000)  # Owned by different user (UID 2000)

    def fake_stat(p):
        return mock_dir_st if os.path.isdir(p) else mock_file_st

    with patch("os.stat", side_effect=fake_stat), patch("os.geteuid", return_value=1000, create=True):
        ok, reason = mgr._verify_posix_permissions()
        assert ok is False
        assert "Insecure parent directory" in reason
        assert "UID 2000" in reason
        assert "does not match current service identity" in reason


def test_posix_wal_shm_permissions_verified(tmp_path):
    """POSIX verification inspects base db, wal, and shm files."""
    test_db = str(tmp_path / "posix_wal_test.db")
    wal_file = f"{test_db}-wal"
    shm_file = f"{test_db}-shm"

    for p in [test_db, wal_file, shm_file]:
        with open(p, "wb") as f:
            f.write(b"DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)
    mgr._is_windows = False

    # 1. All files 0600 -> succeeds across all 3 files
    mock_st_600 = MagicMock(st_mode=stat.S_IFREG | 0o600, st_uid=1000)
    mock_dir_st = MagicMock(st_mode=stat.S_IFDIR | 0o700, st_uid=1000)

    def fake_stat_all_600(p):
        p_str = str(p)
        if "." in os.path.basename(p_str):
            return mock_st_600
        return mock_dir_st

    with patch("os.stat", side_effect=fake_stat_all_600), patch("os.geteuid", return_value=1000, create=True):
        ok, reason = mgr._verify_posix_permissions()
        assert ok is True
        assert "across 3 storage file(s)" in reason

    # 2. SHM file insecure -> fails
    def fake_stat_shm_insecure(p):
        p_str = str(p)
        if p_str.endswith("-shm"):
            return MagicMock(st_mode=stat.S_IFREG | 0o666, st_uid=1000)
        if "." in os.path.basename(p_str):
            return mock_st_600
        return mock_dir_st

    with patch("os.stat", side_effect=fake_stat_shm_insecure), patch("os.geteuid", return_value=1000, create=True):
        ok, reason = mgr._verify_posix_permissions()
        assert ok is False
        assert "posix_wal_test.db-shm' has insecure permissions" in reason


def test_posix_permission_enforcement_failure_fails_closed(tmp_path):
    """POSIX chmod failure in production fails closed with ValueError."""
    test_db = str(tmp_path / "posix_fail.db")
    with open(test_db, "wb") as f:
        f.write(b"SQLITE_DATA")

    mgr = StoragePermissionManager(test_db, is_production=True)
    mgr._is_windows = False

    with patch("os.chmod", side_effect=OSError("chmod operation not permitted")):
        with pytest.raises(ValueError, match="Governance storage security failure"):
            mgr.enforce_storage_permissions()


# =====================================================================
# 3. Cross-Platform Lifecycle & Telemetry Tests
# =====================================================================

def test_cross_platform_missing_database_creation(tmp_path):
    """StoragePermissionManager handles missing database path gracefully before creation."""
    test_db = str(tmp_path / "nonexistent_dir" / "new_ledger.db")
    os.makedirs(os.path.dirname(test_db), exist_ok=True)

    mgr = StoragePermissionManager(test_db, is_production=False)
    ok, reason = mgr.verify_storage_permissions()
    assert ok is True
    assert "Pending database file creation" in reason

    # Create and initialize ledger
    ledger = GovernanceLedger(test_db)
    st = ledger.get_storage_security_status()
    assert st["secured"] is True
    assert st["verification_passed"] is True


def test_cross_platform_wal_checkpoint_maintains_security(tmp_path):
    """WAL checkpoint flushes frames and maintains verified storage security."""
    test_db = str(tmp_path / "checkpoint_sec.db")
    set_governance_ledger_db_path(test_db)
    ledger = get_governance_ledger()

    ledger.record_processed_id_stub("TEST-NONCE-CHECKPOINT-01")
    chk_res = ledger.checkpoint("TRUNCATE")
    assert chk_res["success"] is True

    st = ledger.get_storage_security_status()
    assert st["secured"] is True
    assert st["verification_passed"] is True
    assert st["failure_reason"] is None


def test_cross_platform_sanitized_status_does_not_leak_full_paths(tmp_path):
    """Security status sanitization prevents leaking absolute host directory paths."""
    test_db = str(tmp_path / "leak_test.db")
    mgr = StoragePermissionManager(test_db, is_production=False)

    status_sanitized = mgr.get_storage_security_status(sanitize_paths=True)
    assert status_sanitized["database_path"] == "leak_test.db"
    assert status_sanitized["parent_directory_status"]["path"] == "[PROTECTED_PARENT_DIR]"
    assert str(tmp_path) not in status_sanitized["database_path"]
    assert str(tmp_path) not in status_sanitized["parent_directory_status"]["path"]

    status_raw = mgr.get_storage_security_status(sanitize_paths=False)
    assert status_raw["database_path"] == test_db


def test_cross_platform_in_memory_security_handling():
    """In-memory database is verified safely via process virtual memory isolation."""
    mgr = StoragePermissionManager(":memory:", is_production=False)
    mgr.enforce_storage_permissions()
    ok, reason = mgr.verify_storage_permissions()
    assert ok is True
    assert "In-memory database" in reason

    st = mgr.get_storage_security_status()
    assert st["secured"] is True
    assert st["database_path"] == ":memory:"
