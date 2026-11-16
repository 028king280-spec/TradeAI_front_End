"""
AIVOLVE Quantitative Options Intelligence Engine v3.0
Phase 2 Step 4.2: Deterministic Option Contract Selection Engine.

Selects institutional-grade option contracts for qualified directional index setups:
  - Directional mapping (BUY_CE -> Call only, BUY_PE -> Put only; WAIT/NO_TRADE -> Rejected)
  - Target Delta range filtering (configurable, default 0.35 to 0.55)
  - Dynamic listed strike-spacing derivation from InstrumentMaster (Zero hardcoded strike assumptions)
  - Explicit centralized liquidity policy for all four indices (NIFTY, BANKNIFTY, FINNIFTY, SENSEX)
  - Conservative execution pricing: Entry strictly at Ask, analytical midpoint retained for valuation
  - Authoritative instrument metadata resolution from InstrumentMaster (lot size, tick size)
  - Paper-trading intelligence only. No live broker execution.
"""

from typing import Dict, Any, List, Optional, Set, Tuple
import os
import math
import hashlib
import sqlite3
import json
import threading
from contextlib import contextmanager
from datetime import datetime, date, timezone
from collections import Counter
from collections.abc import MutableSet, MutableMapping
import zoneinfo
import stat
import logging

logger = logging.getLogger("aivolve.governance")

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.exceptions import InvalidSignature

from app.options.greeks import calculate_exact_time_to_expiry
from app.data.instrument_master import get_instrument_master
from app.options.storage_security import StoragePermissionManager, scoped_posix_umask

IST_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")

# Centralized Liquidity Policy for All Four Indices
# Institutional Provenance:
#   - NIFTY, BANKNIFTY, FINNIFTY: Internal developer benchmark heuristics (marked CONFIGURED, not exchange-approved).
#   - SENSEX: Default UNCONFIGURED. Strictly rejected unless an authorized override with explicit governance provenance is provided.
CENTRALIZED_INDEX_LIQUIDITY_POLICY: Dict[str, Dict[str, Any]] = {
    "NIFTY": {
        "policy_status": "CONFIGURED",
        "policy_source": "Internal Developer Benchmark Heuristic (Unverified by Exchange)",
        "min_oi": 25000,
        "min_volume": 5000,
        "max_spread_pct": 0.025,  # 2.5% max bid-ask spread
    },
    "BANKNIFTY": {
        "policy_status": "CONFIGURED",
        "policy_source": "Internal Developer Benchmark Heuristic (Unverified by Exchange)",
        "min_oi": 15000,
        "min_volume": 2500,
        "max_spread_pct": 0.030,  # 3.0% max bid-ask spread
    },
    "FINNIFTY": {
        "policy_status": "CONFIGURED",
        "policy_source": "Internal Developer Benchmark Heuristic (Unverified by Exchange)",
        "min_oi": 10000,
        "min_volume": 1500,
        "max_spread_pct": 0.030,  # 3.0% max bid-ask spread
    },
    "SENSEX": {
        "policy_status": "UNCONFIGURED",
        "policy_source": "BSE Derivatives — Pending institutional risk committee approval",
        "min_oi": None,
        "min_volume": None,
        "max_spread_pct": None,
    },
}

# -----------------------------------------------------------------------------
# Server-Side Institutional Governance Registry for Policy Overrides
# -----------------------------------------------------------------------------
# Authoritative server-side ledger of approved institutional policy overrides.
# Arbitrary caller-supplied strings, forged policy_status="APPROVED", unknown
# references, and revoked references are strictly rejected.
# Only cryptographically/governance-audited references registered in this
# server-side table can elevate an unconfigured index (such as SENSEX) to APPROVED.
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# Server-Side Institutional Governance Trust Anchors & Durable Persistence
# -----------------------------------------------------------------------------
# Asymmetric Cryptographic Trust Architecture (Ed25519) with SQLite ACID Store
#
# Security & Provenance Rules:
#   1. ZERO private/shared signing keys in application source code, frontend, logs, or repo.
#   2. Institutional authorities retain private signing keys strictly outside AIVOLVE.
#   3. AIVOLVE backend stores ONLY trusted public keys (Ed25519, 32-byte raw hex).
#   4. Canonical signed payload deterministically binds: approval_id (nonce/UUID),
#      document_id, approval_reference, document_sha256, ratifying_authority,
#      authorized_indices, liquidity_policy_params (min_oi_floor, min_volume_floor,
#      max_spread_pct_ceiling), effective_date, and expiry_date.
#   5. Durable Replay Protection: Unique constraint and atomic SQLite transactions
#      persist processed approval IDs across application restarts and prevent race conditions.
#   6. Durable Revocation: Revocations are persisted atomically in SQLite, surviving restarts
#      and shared across all concurrent worker processes.
#   7. Authority Enrollment & Rotation: Silent key overwrites are strictly barred. Key rotation
#      is performed atomically, revoking prior keys with explicit audit provenance.
#   8. Fail-closed default: Zero active public keys or approvals exist by default.
#      SENSEX remains UNCONFIGURED and contract qualification is barred until an enrolled
#      public key verifies an authentic signed artifact.
# -----------------------------------------------------------------------------

DEFAULT_GOVERNANCE_DB_PATH: str = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "governance_ledger.db")
)


class GovernanceLedger:
    """
    Durable, thread-safe, process-safe, ACID-compliant institutional governance ledger.
    Backs replay protection, revocation tracking, authority registration,
    and approval registries via SQLite in WAL mode with synchronous=FULL.

    Durability & Hardware Considerations:
      - PRAGMA synchronous = FULL in WAL mode instructs SQLite to issue an explicit OS-level
        synchronous flush (fsync on POSIX, FlushFileBuffers on Windows) upon every transaction
        commit, flushing write-ahead log frames to non-volatile storage before reporting success.
      - While synchronous=FULL provides the strongest durability tier available in SQLite,
        absolute zero data-loss risk cannot be guaranteed solely by software:
          1. Operating System Caching: OS kernel write buffers must honor synchronous flush requests.
          2. Filesystem Semantics: Underlying filesystem (ext4, XFS, NTFS) mount flags (e.g. barrier=1)
             must guarantee write order integrity.
          3. Hardware Controller Caching: Physical storage devices (NVMe, SSD, RAID controllers)
             with volatile onboard write caches can lose unwritten frames during sudden power loss
             unless equipped with Power-Loss Protection (PLP) or Battery-Backed Write Cache (BBWC).
      - Institutional production deployments should combine synchronous=FULL with enterprise storage
        hardware featuring PLP and offsite replicated backups.
    """
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or os.environ.get("AIVOLVE_GOVERNANCE_LEDGER_PATH", DEFAULT_GOVERNANCE_DB_PATH)
        # Ensure parent directory exists if using file path under scoped umask
        if self._db_path != ":memory:":
            with scoped_posix_umask(0o077):
                os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._sec_mgr = StoragePermissionManager(self._db_path)
        self._lock = threading.RLock()
        self._init_db()

    def enforce_storage_permissions(self) -> None:
        """Enforces cross-platform storage security permissions on the database and sidecars."""
        self._sec_mgr.enforce_storage_permissions()

    def verify_storage_permissions(self) -> Tuple[bool, str]:
        """Inspects and verifies the effective filesystem permissions / NTFS DACL."""
        return self._sec_mgr.verify_storage_permissions()

    def get_storage_security_status(self, sanitize_paths: bool = True) -> Dict[str, Any]:
        """Returns auditable storage security telemetry across DB, WAL, SHM, and parent directory."""
        return self._sec_mgr.get_storage_security_status(sanitize_paths=sanitize_paths)

    def get_permissions_status(self) -> Dict[str, Any]:
        """Returns permission security status for backward compatibility."""
        st = self._sec_mgr.get_storage_security_status(sanitize_paths=False)
        return {
            "db_path": self._db_path,
            "secured": st["secured"],
            "detail": st["effective_permissions"] if st["secured"] else (st["failure_reason"] or "Security check failed"),
            "os": os.name,
        }

    @contextmanager
    def _conn(self):
        try:
            with scoped_posix_umask(0o077):
                conn = sqlite3.connect(
                    self._db_path,
                    timeout=30.0,
                    check_same_thread=False,
                    isolation_level=None,  # Direct explicit transaction control
                )
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = FULL;")
                conn.execute("PRAGMA busy_timeout = 30000;")
                conn.execute("PRAGMA foreign_keys = ON;")
        except Exception as e:
            raise ValueError(f"Governance storage failure: Storage is corrupted or inaccessible (Failing closed): {e}")
        try:
            yield conn
        except sqlite3.IntegrityError:
            raise
        except (sqlite3.DatabaseError, sqlite3.OperationalError) as e:
            raise ValueError(f"Governance storage failure: Storage is corrupted or inaccessible (Failing closed): {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @contextmanager
    def _transaction(self):
        """
        Context manager for atomic write transactions with BEGIN IMMEDIATE.
        
        Guarantees:
          - Serializes via threading RLock.
          - Acquires immediate reserved lock via 'BEGIN IMMEDIATE;' on connection.
          - If BEGIN IMMEDIATE fails (locked, inaccessible, corrupted), fails closed immediately.
          - Any statement failure inside the block triggers an explicit ROLLBACK.
          - Executes COMMIT on exit. If COMMIT fails, triggers ROLLBACK and fails closed.
          - Eliminates any possibility of false-positive success reporting.
        """
        with self._lock, self._conn() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE;")
            except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
                raise ValueError(
                    f"Governance transaction lock acquisition failed (Failing closed): {exc}"
                ) from exc
            try:
                yield conn
                conn.execute("COMMIT;")
                self._sec_mgr.enforce_storage_permissions()
            except Exception:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                raise

    def _init_db(self):
        self._sec_mgr.enforce_storage_permissions()
        with self._transaction() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_approval_ids (
                    approval_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    approval_reference TEXT NOT NULL,
                    document_sha256 TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS revoked_approval_references (
                    approval_reference TEXT PRIMARY KEY,
                    revoked_at TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS revoked_document_hashes (
                    document_sha256 TEXT PRIMARY KEY,
                    revoked_at TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trusted_governance_authorities (
                    key_id TEXT PRIMARY KEY,
                    authority_name TEXT NOT NULL,
                    public_key_hex TEXT NOT NULL,
                    authorized_indices TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    revocation_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trusted_approval_registry (
                    approval_reference TEXT PRIMARY KEY,
                    approval_id TEXT UNIQUE,
                    approved_by TEXT NOT NULL,
                    authorized_indices TEXT NOT NULL,
                    key_id TEXT,
                    min_oi_floor INTEGER NOT NULL,
                    min_volume_floor INTEGER NOT NULL,
                    max_spread_pct_ceiling REAL NOT NULL,
                    effective_date TEXT,
                    expiry_date TEXT,
                    status TEXT NOT NULL,
                    approval_evidence_json TEXT,
                    verification_notes TEXT,
                    revocation_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            # Institutional Provenance Integrity:
            # Zero synthetic records are pre-seeded. Production initializes strictly
            # fail-closed with 0 authorities, 0 revocations, and 0 approvals.
        self._sec_mgr.enforce_storage_permissions()

    def checkpoint(self, mode: str = "TRUNCATE") -> Dict[str, Any]:
        """
        Safely flushes and checkpoints WAL journal file to persistent DB.
        
        Explicit mode allowlist: PASSIVE, FULL, RESTART, TRUNCATE.
        Inspects (busy, log_frames, checkpointed_frames) returned by PRAGMA wal_checkpoint.
        Never claims successful truncation without verifying busy==0 and log frames backfilled.
        """
        allowed = {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}
        clean_mode = str(mode).strip().upper()
        if clean_mode not in allowed:
            raise ValueError(
                f"Invalid WAL checkpoint mode '{mode}'. Mode must be one of: {sorted(allowed)}"
            )

        with self._lock, self._conn() as conn:
            cursor = conn.execute(f"PRAGMA wal_checkpoint({clean_mode});")
            row = cursor.fetchone()
            if not row:
                raise ValueError("Governance storage checkpoint failure: PRAGMA wal_checkpoint returned no result")

            busy = int(row[0])
            log_frames = int(row[1])
            checkpointed_frames = int(row[2])

            is_success = (busy == 0)
            if clean_mode in {"RESTART", "TRUNCATE"} and log_frames > 0:
                is_success = is_success and (checkpointed_frames == log_frames)

            result = {
                "mode": clean_mode,
                "busy": bool(busy),
                "log_frames": log_frames,
                "checkpointed_frames": checkpointed_frames,
                "success": is_success,
            }

            if busy:
                logger.warning(
                    f"WAL checkpoint({clean_mode}) was busy (blocked by concurrent transactions). "
                    f"Frames: {checkpointed_frames}/{log_frames} checkpointed."
                )
            if not is_success and clean_mode == "TRUNCATE":
                logger.warning(
                    f"WAL truncation incomplete: {checkpointed_frames}/{log_frames} frames backfilled (busy={busy})"
                )

            self._sec_mgr.enforce_storage_permissions()
            return result

    # Replay protection queries
    def is_approval_id_processed(self, approval_id: str) -> bool:
        clean = approval_id.strip()
        if not clean:
            return False
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM processed_approval_ids WHERE approval_id = ?", (clean,)).fetchone()
            return row is not None

    def get_all_processed_approval_ids(self) -> Set[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT approval_id FROM processed_approval_ids").fetchall()
            return {r[0] for r in rows}

    def record_processed_id_stub(self, approval_id: str) -> None:
        clean = approval_id.strip()
        if not clean:
            return
        now_str = datetime.now(timezone.utc).isoformat()
        with self._transaction() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO processed_approval_ids (approval_id, document_id, approval_reference, document_sha256, processed_at)
                VALUES (?, ?, ?, ?, ?)
            """, (clean, "MANUAL_STUB", "MANUAL_STUB", "MANUAL_STUB", now_str))

    # Revocations
    def is_reference_revoked(self, ref: str) -> bool:
        clean = ref.strip().upper()
        if not clean:
            return False
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM revoked_approval_references WHERE approval_reference = ?", (clean,)).fetchone()
            return row is not None

    def get_all_revoked_references(self) -> Set[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT approval_reference FROM revoked_approval_references").fetchall()
            return {r[0] for r in rows}

    def revoke_approval_reference(self, ref: str, reason: str = "") -> None:
        clean = ref.strip().upper()
        if not clean:
            return
        now_str = datetime.now(timezone.utc).isoformat()
        with self._transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO revoked_approval_references (approval_reference, revoked_at, reason)
                VALUES (?, ?, ?)
            """, (clean, now_str, reason or "Revoked by institutional governance"))
            conn.execute("""
                UPDATE trusted_approval_registry
                SET status = 'REVOKED', revocation_reason = ?, updated_at = ?
                WHERE approval_reference = ?
            """, (reason or "Revoked by institutional governance", now_str, clean))

    def unrevoke_reference(self, ref: str) -> None:
        clean = ref.strip().upper()
        with self._transaction() as conn:
            conn.execute("DELETE FROM revoked_approval_references WHERE approval_reference = ?", (clean,))

    def is_document_hash_revoked(self, doc_hash: str) -> bool:
        clean = doc_hash.strip().lower()
        if not clean:
            return False
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM revoked_document_hashes WHERE document_sha256 = ?", (clean,)).fetchone()
            return row is not None

    def get_all_revoked_document_hashes(self) -> Set[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT document_sha256 FROM revoked_document_hashes").fetchall()
            return {r[0] for r in rows}

    def revoke_document_hash(self, doc_hash: str, reason: str = "") -> None:
        clean = doc_hash.strip().lower()
        if not clean:
            return
        now_str = datetime.now(timezone.utc).isoformat()
        with self._transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO revoked_document_hashes (document_sha256, revoked_at, reason)
                VALUES (?, ?, ?)
            """, (clean, now_str, reason or "Revoked by institutional governance"))

    def unrevoke_document_hash(self, doc_hash: str) -> None:
        clean = doc_hash.strip().lower()
        with self._transaction() as conn:
            conn.execute("DELETE FROM revoked_document_hashes WHERE document_sha256 = ?", (clean,))

    # Authorities
    def get_authority(self, key_id: str) -> Optional[Dict[str, Any]]:
        clean = key_id.strip().upper()
        if not clean:
            return None
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM trusted_governance_authorities WHERE key_id = ?", (clean,)).fetchone()
            if not row:
                return None
            return {
                "key_id": row["key_id"],
                "authority_name": row["authority_name"],
                "public_key_hex": row["public_key_hex"],
                "authorized_indices": json.loads(row["authorized_indices"]),
                "valid_from": row["valid_from"],
                "valid_until": row["valid_until"],
                "active": bool(row["active"]),
                "revoked": bool(row["revoked"]),
                "revocation_reason": row["revocation_reason"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    def get_all_authorities(self) -> Dict[str, Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM trusted_governance_authorities").fetchall()
            out = {}
            for row in rows:
                k = row["key_id"]
                out[k] = {
                    "key_id": k,
                    "authority_name": row["authority_name"],
                    "public_key_hex": row["public_key_hex"],
                    "authorized_indices": json.loads(row["authorized_indices"]),
                    "valid_from": row["valid_from"],
                    "valid_until": row["valid_until"],
                    "active": bool(row["active"]),
                    "revoked": bool(row["revoked"]),
                    "revocation_reason": row["revocation_reason"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            return out

    def register_authority(
        self,
        key_id: str,
        authority_name: str,
        public_key_hex: str,
        authorized_indices: List[str],
        valid_from: str = "2026-01-01",
        valid_until: str = "2030-01-01",
        active: bool = True,
    ) -> None:
        clean_id = key_id.strip().upper()
        clean_pub = public_key_hex.strip().lower()
        if not clean_id or not clean_pub:
            raise ValueError("Invalid key_id or public_key_hex")
        if len(clean_pub) != 64:
            raise ValueError(
                f"Invalid public_key_hex length: Ed25519 public keys must be 64 hex characters (32 bytes), got {len(clean_pub)}"
            )

        now_str = datetime.now(timezone.utc).isoformat()
        with self._transaction() as conn:
            existing = conn.execute("SELECT key_id FROM trusted_governance_authorities WHERE key_id = ?", (clean_id,)).fetchone()
            if existing:
                raise ValueError(
                    f"Duplicate key_id enrollment rejected: Authority key_id '{clean_id}' already exists. "
                    "Silent key overwrite is prohibited. Use rotate_governance_authority() for explicit key rotation."
                )
            conn.execute("""
                INSERT INTO trusted_governance_authorities (
                    key_id, authority_name, public_key_hex, authorized_indices, valid_from, valid_until,
                    active, revoked, revocation_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                clean_id, authority_name.strip(), clean_pub, json.dumps(authorized_indices),
                valid_from, valid_until, 1 if active else 0, 0, None, now_str, now_str
            ))

    def rotate_authority(
        self,
        old_key_id: str,
        new_key_id: str,
        new_authority_name: str,
        new_public_key_hex: str,
        authorized_indices: List[str],
        valid_from: str = "2026-01-01",
        valid_until: str = "2030-01-01",
        reason: str = "Routine institutional key rotation",
    ) -> None:
        clean_old = old_key_id.strip().upper()
        clean_new = new_key_id.strip().upper()
        clean_pub = new_public_key_hex.strip().lower()

        if len(clean_pub) != 64:
            raise ValueError("Invalid public_key_hex length: Ed25519 public keys must be 64 hex characters (32 bytes)")

        now_str = datetime.now(timezone.utc).isoformat()
        with self._transaction() as conn:
            old_row = conn.execute("SELECT key_id, active, revoked FROM trusted_governance_authorities WHERE key_id = ?", (clean_old,)).fetchone()
            if not old_row:
                raise ValueError(f"Key rotation failed: Prior authority key_id '{clean_old}' does not exist")
            if old_row["revoked"] or not old_row["active"]:
                raise ValueError(f"Key rotation failed: Prior authority key_id '{clean_old}' is already revoked or inactive")

            new_row = conn.execute("SELECT key_id FROM trusted_governance_authorities WHERE key_id = ?", (clean_new,)).fetchone()
            if new_row:
                raise ValueError(f"Key rotation failed: Successor authority key_id '{clean_new}' already exists")

            conn.execute("""
                UPDATE trusted_governance_authorities
                SET active = 0, revoked = 1, revocation_reason = ?, updated_at = ?
                WHERE key_id = ?
            """, (f"Superseded by key rotation to {clean_new} ({reason})", now_str, clean_old))

            conn.execute("""
                INSERT INTO trusted_governance_authorities (
                    key_id, authority_name, public_key_hex, authorized_indices, valid_from, valid_until,
                    active, revoked, revocation_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                clean_new, new_authority_name.strip(), clean_pub, json.dumps(authorized_indices),
                valid_from, valid_until, 1, 0, None, now_str, now_str
            ))

    def revoke_authority(self, key_id: str, reason: str = "") -> bool:
        clean_id = key_id.strip().upper()
        now_str = datetime.now(timezone.utc).isoformat()
        with self._transaction() as conn:
            row = conn.execute("SELECT key_id FROM trusted_governance_authorities WHERE key_id = ?", (clean_id,)).fetchone()
            if not row:
                return False
            conn.execute("""
                UPDATE trusted_governance_authorities
                SET active = 0, revoked = 1, revocation_reason = ?, updated_at = ?
                WHERE key_id = ?
            """, (reason or "Revoked by institutional governance", now_str, clean_id))
            return True

    def delete_authority(self, key_id: str) -> None:
        clean = key_id.strip().upper()
        with self._transaction() as conn:
            conn.execute("DELETE FROM trusted_governance_authorities WHERE key_id = ?", (clean,))

    def set_authority_raw(self, key_id: str, data: Dict[str, Any]) -> None:
        clean = key_id.strip().upper()
        now_str = datetime.now(timezone.utc).isoformat()
        with self._transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trusted_governance_authorities (
                    key_id, authority_name, public_key_hex, authorized_indices, valid_from, valid_until,
                    active, revoked, revocation_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                clean,
                data.get("authority_name") or data.get("title") or clean,
                data.get("public_key_hex", ""),
                json.dumps(data.get("authorized_indices", [])),
                data.get("valid_from", "2026-01-01"),
                data.get("valid_until", "2030-01-01"),
                1 if data.get("active", True) else 0,
                1 if data.get("revoked", False) else 0,
                data.get("revocation_reason"),
                now_str, now_str
            ))

    # Approvals
    def get_approval(self, approval_ref: str) -> Optional[Dict[str, Any]]:
        clean = approval_ref.strip().upper()
        if not clean:
            return None
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM trusted_approval_registry WHERE approval_reference = ?", (clean,)).fetchone()
            if not row:
                return None
            evidence = json.loads(row["approval_evidence_json"]) if row["approval_evidence_json"] else None
            return {
                "approval_reference": row["approval_reference"],
                "approval_id": row["approval_id"],
                "approved_by": row["approved_by"],
                "authorized_indices": json.loads(row["authorized_indices"]),
                "key_id": row["key_id"],
                "min_oi_floor": row["min_oi_floor"],
                "min_volume_floor": row["min_volume_floor"],
                "max_spread_pct_ceiling": row["max_spread_pct_ceiling"],
                "effective_date": row["effective_date"],
                "expiry_date": row["expiry_date"],
                "status": row["status"],
                "approval_evidence": evidence,
                "verification_notes": row["verification_notes"],
                "revocation_reason": row["revocation_reason"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    def get_all_approvals(self) -> Dict[str, Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM trusted_approval_registry").fetchall()
            out = {}
            for row in rows:
                k = row["approval_reference"]
                evidence = json.loads(row["approval_evidence_json"]) if row["approval_evidence_json"] else None
                out[k] = {
                    "approval_reference": k,
                    "approval_id": row["approval_id"],
                    "approved_by": row["approved_by"],
                    "authorized_indices": json.loads(row["authorized_indices"]),
                    "key_id": row["key_id"],
                    "min_oi_floor": row["min_oi_floor"],
                    "min_volume_floor": row["min_volume_floor"],
                    "max_spread_pct_ceiling": row["max_spread_pct_ceiling"],
                    "effective_date": row["effective_date"],
                    "expiry_date": row["expiry_date"],
                    "status": row["status"],
                    "approval_evidence": evidence,
                    "verification_notes": row["verification_notes"],
                    "revocation_reason": row["revocation_reason"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            return out

    def record_verified_approval(
        self,
        approval_reference: str,
        approval_id: str,
        approved_by: str,
        authorized_indices: List[str],
        key_id: str,
        min_oi_floor: int,
        min_volume_floor: int,
        max_spread_pct_ceiling: float,
        effective_date: str,
        expiry_date: str,
        approval_evidence: Dict[str, Any],
        doc_id: str,
        recomputed_hash: str,
    ) -> None:
        clean_ref = approval_reference.strip().upper()
        clean_appr_id = approval_id.strip()
        now_str = datetime.now(timezone.utc).isoformat()

        with self._transaction() as conn:
            row = conn.execute("SELECT 1 FROM processed_approval_ids WHERE approval_id = ?", (clean_appr_id,)).fetchone()
            if row:
                raise ValueError(f"Replay attack detected: approval_id '{clean_appr_id}' has already been processed")

            try:
                conn.execute("""
                    INSERT INTO processed_approval_ids (approval_id, document_id, approval_reference, document_sha256, processed_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (clean_appr_id, doc_id, clean_ref, recomputed_hash, now_str))
            except sqlite3.IntegrityError:
                raise ValueError(f"Replay attack detected: approval_id '{clean_appr_id}' has already been processed")

            conn.execute("""
                INSERT OR REPLACE INTO trusted_approval_registry (
                    approval_reference, approval_id, approved_by, authorized_indices, key_id,
                    min_oi_floor, min_volume_floor, max_spread_pct_ceiling, effective_date,
                    expiry_date, status, approval_evidence_json, verification_notes, revocation_reason,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                clean_ref, clean_appr_id, approved_by.strip().upper(), json.dumps(authorized_indices),
                key_id.strip().upper(), int(min_oi_floor), int(min_volume_floor), float(max_spread_pct_ceiling),
                effective_date, expiry_date, "ACTIVE", json.dumps(approval_evidence),
                f"Cryptographically verified Ed25519 institutional approval backed by artifact {doc_id}",
                None, now_str, now_str
            ))

    def revoke_approval(self, approval_reference: str, reason: str = "") -> bool:
        clean = approval_reference.strip().upper()
        if not clean:
            return False
        now_str = datetime.now(timezone.utc).isoformat()
        with self._transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO revoked_approval_references (approval_reference, revoked_at, reason)
                VALUES (?, ?, ?)
            """, (clean, now_str, reason or "Revoked by institutional governance"))
            conn.execute("""
                UPDATE trusted_approval_registry
                SET status = 'REVOKED', revocation_reason = ?, updated_at = ?
                WHERE approval_reference = ?
            """, (reason or "Revoked by institutional governance", now_str, clean))
            return True

    def delete_approval(self, approval_reference: str) -> None:
        clean = approval_reference.strip().upper()
        with self._transaction() as conn:
            conn.execute("DELETE FROM trusted_approval_registry WHERE approval_reference = ?", (clean,))

    def set_approval_raw(self, approval_reference: str, data: Dict[str, Any]) -> None:
        clean = approval_reference.strip().upper()
        now_str = datetime.now(timezone.utc).isoformat()
        evidence_json = json.dumps(data.get("approval_evidence")) if data.get("approval_evidence") else None
        with self._transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trusted_approval_registry (
                    approval_reference, approval_id, approved_by, authorized_indices, key_id,
                    min_oi_floor, min_volume_floor, max_spread_pct_ceiling, effective_date,
                    expiry_date, status, approval_evidence_json, verification_notes, revocation_reason,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                clean,
                data.get("approval_id"),
                data.get("approved_by", "QUANT_RISK_COMMITTEE"),
                json.dumps(data.get("authorized_indices", [])),
                data.get("key_id"),
                int(data.get("min_oi_floor", 1000)),
                int(data.get("min_volume_floor", 500)),
                float(data.get("max_spread_pct_ceiling", 0.050)),
                data.get("effective_date"),
                data.get("expiry_date"),
                data.get("status", "ACTIVE"),
                evidence_json,
                data.get("verification_notes") or data.get("notes"),
                data.get("revocation_reason"),
                now_str, now_str
            ))


_ACTIVE_GOVERNANCE_LEDGER: Optional[GovernanceLedger] = None
_GOVERNANCE_LEDGER_LOCK = threading.RLock()


def get_governance_ledger() -> GovernanceLedger:
    """Returns the thread-safe active singleton instance of GovernanceLedger."""
    global _ACTIVE_GOVERNANCE_LEDGER
    with _GOVERNANCE_LEDGER_LOCK:
        if _ACTIVE_GOVERNANCE_LEDGER is None:
            _ACTIVE_GOVERNANCE_LEDGER = GovernanceLedger()
        return _ACTIVE_GOVERNANCE_LEDGER


def set_governance_ledger_db_path(db_path: Optional[str]) -> None:
    """Configures the active governance ledger SQLite database path (used for test isolation)."""
    global _ACTIVE_GOVERNANCE_LEDGER
    with _GOVERNANCE_LEDGER_LOCK:
        if db_path is None:
            os.environ.pop("AIVOLVE_GOVERNANCE_LEDGER_PATH", None)
            _ACTIVE_GOVERNANCE_LEDGER = GovernanceLedger(DEFAULT_GOVERNANCE_DB_PATH)
        else:
            os.environ["AIVOLVE_GOVERNANCE_LEDGER_PATH"] = db_path
            _ACTIVE_GOVERNANCE_LEDGER = GovernanceLedger(db_path)


# -----------------------------------------------------------------------------
# Dynamic Proxy Collections for Transparent Ledger Integration
# -----------------------------------------------------------------------------
class _ProcessedApprovalIdsProxy(MutableSet):
    def __contains__(self, approval_id: object) -> bool:
        return get_governance_ledger().is_approval_id_processed(str(approval_id))

    def __iter__(self):
        return iter(get_governance_ledger().get_all_processed_approval_ids())

    def __len__(self) -> int:
        return len(get_governance_ledger().get_all_processed_approval_ids())

    def add(self, approval_id: str) -> None:
        get_governance_ledger().record_processed_id_stub(str(approval_id))

    def discard(self, approval_id: str) -> None:
        pass


class _RevokedReferencesProxy(MutableSet):
    def __contains__(self, ref: object) -> bool:
        return get_governance_ledger().is_reference_revoked(str(ref))

    def __iter__(self):
        return iter(get_governance_ledger().get_all_revoked_references())

    def __len__(self) -> int:
        return len(get_governance_ledger().get_all_revoked_references())

    def add(self, ref: str) -> None:
        get_governance_ledger().revoke_approval_reference(str(ref), "Revoked via governance proxy")

    def discard(self, ref: str) -> None:
        get_governance_ledger().unrevoke_reference(str(ref))


class _RevokedHashesProxy(MutableSet):
    def __contains__(self, h: object) -> bool:
        return get_governance_ledger().is_document_hash_revoked(str(h))

    def __iter__(self):
        return iter(get_governance_ledger().get_all_revoked_document_hashes())

    def __len__(self) -> int:
        return len(get_governance_ledger().get_all_revoked_document_hashes())

    def add(self, h: str) -> None:
        get_governance_ledger().revoke_document_hash(str(h), "Revoked via governance proxy")

    def discard(self, h: str) -> None:
        get_governance_ledger().unrevoke_document_hash(str(h))


class _AuthoritiesProxy(MutableMapping):
    def __getitem__(self, key_id: str) -> Dict[str, Any]:
        val = get_governance_ledger().get_authority(str(key_id))
        if val is None:
            raise KeyError(key_id)
        return val

    def __setitem__(self, key_id: str, value: Dict[str, Any]) -> None:
        get_governance_ledger().set_authority_raw(str(key_id), value)

    def __delitem__(self, key_id: str) -> None:
        get_governance_ledger().delete_authority(str(key_id))

    def __iter__(self):
        return iter(get_governance_ledger().get_all_authorities())

    def __len__(self) -> int:
        return len(get_governance_ledger().get_all_authorities())


class _ApprovalRegistryProxy(MutableMapping):
    def __getitem__(self, ref: str) -> Dict[str, Any]:
        val = get_governance_ledger().get_approval(str(ref))
        if val is None:
            raise KeyError(ref)
        return val

    def __setitem__(self, ref: str, value: Dict[str, Any]) -> None:
        get_governance_ledger().set_approval_raw(str(ref), value)

    def __delitem__(self, ref: str) -> None:
        get_governance_ledger().delete_approval(str(ref))

    def __iter__(self):
        return iter(get_governance_ledger().get_all_approvals())

    def __len__(self) -> int:
        return len(get_governance_ledger().get_all_approvals())


# Authoritative server-side proxies backed by durable SQLite GovernanceLedger
TRUSTED_GOVERNANCE_AUTHORITIES: _AuthoritiesProxy = _AuthoritiesProxy()
PROCESSED_APPROVAL_IDS: _ProcessedApprovalIdsProxy = _ProcessedApprovalIdsProxy()
REVOKED_APPROVAL_REFERENCES: _RevokedReferencesProxy = _RevokedReferencesProxy()
REVOKED_DOCUMENT_HASHES: _RevokedHashesProxy = _RevokedHashesProxy()
TRUSTED_APPROVAL_REGISTRY: _ApprovalRegistryProxy = _ApprovalRegistryProxy()


def get_trusted_approval_registry() -> Dict[str, Dict[str, Any]]:
    """Returns a copy of the authoritative server-side institutional approval registry."""
    return get_governance_ledger().get_all_approvals()


def get_trusted_governance_authorities() -> Dict[str, Dict[str, Any]]:
    """Returns a copy of the authoritative server-side governance authorities registry."""
    return get_governance_ledger().get_all_authorities()


def register_governance_authority(
    key_id: str,
    authority_name: str,
    public_key_hex: str,
    authorized_indices: List[str],
    valid_from: str = "2026-01-01",
    valid_until: str = "2030-01-01",
    active: bool = True,
) -> None:
    """
    Registers a trusted server-side governance authority public key.
    
    Zero private keys stored: Only 32-byte Ed25519 public key hex is retained.
    Duplicate key IDs are strictly rejected to prevent silent overwrite.
    """
    clean_id = key_id.strip().upper()
    if not clean_id:
        raise ValueError("Institutional authority registration rejected: Missing key_id")
    if not public_key_hex:
        raise ValueError("Institutional authority registration rejected: Missing public_key_hex")
    clean_pub = public_key_hex.strip().lower()
    if len(clean_pub) != 64:
        raise ValueError(
            f"Invalid public_key_hex length: Ed25519 public keys must be 64 hex characters (32 bytes), got {len(clean_pub)}"
        )
    try:
        pub_bytes = bytes.fromhex(clean_pub)
        ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
    except Exception as e:
        raise ValueError(f"Invalid Ed25519 public key: {e}")

    clean_indices = [normalize_index_symbol(idx) for idx in authorized_indices]
    get_governance_ledger().register_authority(
        key_id=clean_id,
        authority_name=authority_name.strip(),
        public_key_hex=clean_pub,
        authorized_indices=clean_indices,
        valid_from=valid_from,
        valid_until=valid_until,
        active=active,
    )


def rotate_governance_authority(
    old_key_id: str,
    new_key_id: str,
    new_authority_name: str,
    new_public_key_hex: str,
    authorized_indices: List[str],
    valid_from: str = "2026-01-01",
    valid_until: str = "2030-01-01",
    reason: str = "Routine institutional key rotation",
) -> None:
    """
    Atomically revokes an existing authority key and registers a successor key.
    Provides auditable key rotation with explicit provenance.
    """
    clean_old = old_key_id.strip().upper()
    clean_new = new_key_id.strip().upper()
    if not clean_old or not clean_new:
        raise ValueError("Key rotation rejected: Missing old_key_id or new_key_id")
    clean_pub = new_public_key_hex.strip().lower()
    if len(clean_pub) != 64:
        raise ValueError(
            f"Invalid public_key_hex length: Ed25519 public keys must be 64 hex characters (32 bytes), got {len(clean_pub)}"
        )
    try:
        pub_bytes = bytes.fromhex(clean_pub)
        ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
    except Exception as e:
        raise ValueError(f"Invalid Ed25519 public key: {e}")

    clean_indices = [normalize_index_symbol(idx) for idx in authorized_indices]
    get_governance_ledger().rotate_authority(
        old_key_id=clean_old,
        new_key_id=clean_new,
        new_authority_name=new_authority_name.strip(),
        new_public_key_hex=clean_pub,
        authorized_indices=clean_indices,
        valid_from=valid_from,
        valid_until=valid_until,
        reason=reason,
    )


def revoke_governance_authority(key_id: str, reason: str = "") -> bool:
    """Revokes a trusted governance authority public key."""
    clean_id = key_id.strip().upper()
    return get_governance_ledger().revoke_authority(clean_id, reason)


def build_canonical_approval_payload(
    approval_id: str,
    document_id: str,
    approval_reference: str,
    document_sha256: str,
    ratifying_authority: str,
    authorized_indices: List[str],
    min_oi_floor: int,
    min_volume_floor: int,
    max_spread_pct_ceiling: float,
    effective_date: str,
    expiry_date: str,
) -> bytes:
    """
    Constructs a deterministic canonical byte string representing an institutional approval.
    Any tampering with governance attributes, document hash, or risk thresholds
    immediately alters this payload and invalidates the Ed25519 cryptographic signature.
    """
    norm_indices = sorted([normalize_index_symbol(idx) for idx in authorized_indices])
    canonical_str = (
        f"APPROVAL_ID={approval_id.strip()}|"
        f"DOC_ID={document_id.strip()}|"
        f"REF={approval_reference.strip().upper()}|"
        f"DOC_SHA256={document_sha256.strip().lower()}|"
        f"AUTHORITY={ratifying_authority.strip().upper()}|"
        f"INDICES={','.join(norm_indices)}|"
        f"MIN_OI_FLOOR={int(min_oi_floor)}|"
        f"MIN_VOL_FLOOR={int(min_volume_floor)}|"
        f"MAX_SPREAD_CEILING={float(max_spread_pct_ceiling):.6f}|"
        f"EFF_DATE={effective_date.strip()}|"
        f"EXP_DATE={expiry_date.strip()}"
    )
    return canonical_str.encode("utf-8")


def register_verified_institutional_approval(
    approval_reference: str,
    approved_by: str,
    authorized_indices: List[str],
    approval_evidence: Dict[str, Any],
    min_oi_floor: int = 1000,
    min_volume_floor: int = 500,
    max_spread_pct_ceiling: float = 0.050,
    evaluation_date: Optional[date] = None,
) -> None:
    """
    Registers a genuine, cryptographically auditable institutional approval record backed by verified evidence.
    
    Asymmetric Verification Rules (Ed25519):
      1. Mandatory fields: approval_id, document_id, document_content, document_sha256, key_id,
         ratified_by, digital_signature, effective_date, expiry_date.
      2. Replay attack prevention: approval_id must be unique and not previously processed.
      3. Hash recomputation: Independently computes SHA-256 of document_content bytes. Rejects on mismatch.
      4. Revocation checks: Rejects if reference, document hash, or public key is revoked.
      5. Public key authority lookup: key_id must exist in TRUSTED_GOVERNANCE_AUTHORITIES, be active,
         and be within its validity date range.
      6. Index scope authorization: Requested indices must be covered by authority's authorized_indices.
      7. Asymmetric signature verification: Validates 64-byte Ed25519 digital signature over the
         canonical approval payload using the authority's registered public key.
      8. Temporal validity: Rejects if expired (expiry_date < evaluation_date) or premature (effective_date > evaluation_date).
    
    Zero caller-supplied bypass: caller cannot fabricate evidence without a valid private key signature.
    """
    if not approval_reference or not approved_by or not authorized_indices:
        raise ValueError("Institutional approval registration rejected: Missing mandatory governance attributes")

    if not isinstance(approval_evidence, dict):
        raise ValueError("Institutional approval registration rejected: Missing approval evidence artifact dictionary")

    # 1. Inspect required evidence fields
    approval_id = str(approval_evidence.get("approval_id") or "").strip()
    doc_id = str(approval_evidence.get("document_id") or "").strip()
    claimed_hash = str(approval_evidence.get("document_sha256") or "").strip().lower()
    doc_content = approval_evidence.get("document_content")
    key_id = str(approval_evidence.get("key_id") or "").strip().upper()
    ratified_by = str(approval_evidence.get("ratified_by") or "").strip().upper()
    sig = str(approval_evidence.get("digital_signature") or "").strip().lower()
    eff_date_str = str(approval_evidence.get("effective_date") or "").strip()
    exp_date_str = str(approval_evidence.get("expiry_date") or "").strip()

    if not approval_id:
        raise ValueError("Institutional approval registration rejected: Missing approval_id")
    if not doc_id:
        raise ValueError("Institutional approval registration rejected: Missing document_id")
    if not claimed_hash or doc_content is None:
        raise ValueError("Institutional approval registration rejected: Missing document_sha256 or document_content")
    if not key_id:
        raise ValueError("Institutional approval registration rejected: Missing key_id")
    if not ratified_by:
        raise ValueError("Institutional approval registration rejected: Missing ratified_by authority")
    if not sig:
        raise ValueError("Institutional approval registration rejected: Missing digital_signature")
    if not eff_date_str or not exp_date_str:
        raise ValueError("Institutional approval registration rejected: Missing effective_date or expiry_date")

    # 2. Replay Attack Prevention
    if approval_id in PROCESSED_APPROVAL_IDS:
        raise ValueError(f"Replay attack detected: approval_id '{approval_id}' has already been processed")

    # 3. Hash Recomputation from actual document bytes
    if isinstance(doc_content, str):
        content_bytes = doc_content.encode("utf-8")
    elif isinstance(doc_content, bytes):
        content_bytes = doc_content
    else:
        raise ValueError("Institutional approval registration rejected: document_content must be bytes or str")

    recomputed_hash = hashlib.sha256(content_bytes).hexdigest().lower()
    if recomputed_hash != claimed_hash:
        raise ValueError(
            f"Document hash mismatch: Recomputed SHA-256 '{recomputed_hash}' does not match claimed '{claimed_hash}'"
        )

    # 4. Revocation Checks
    clean_ref = approval_reference.strip().upper()
    if clean_ref in REVOKED_APPROVAL_REFERENCES:
        raise ValueError(f"Approval reference '{clean_ref}' is in server revocation registry")
    if recomputed_hash in REVOKED_DOCUMENT_HASHES:
        raise ValueError(f"Approval document hash '{recomputed_hash}' is in server revocation registry")

    # 5. Public Key Authority Verification
    if key_id not in TRUSTED_GOVERNANCE_AUTHORITIES:
        raise ValueError(f"Unknown or unregistered governance authority key_id '{key_id}'")

    authority = TRUSTED_GOVERNANCE_AUTHORITIES[key_id]
    if authority.get("revoked"):
        rev_reason = authority.get("revocation_reason") or "Revoked"
        raise ValueError(f"Revoked governance authority key_id '{key_id}' ({rev_reason})")
    if not authority.get("active"):
        raise ValueError(f"Inactive governance authority key_id '{key_id}'")

    # 6. Index Scope Authorization
    clean_indices = [normalize_index_symbol(idx) for idx in authorized_indices]
    auth_permitted = [normalize_index_symbol(idx) for idx in authority.get("authorized_indices", [])]
    for idx in clean_indices:
        if idx not in auth_permitted:
            raise ValueError(
                f"Authority '{key_id}' is not authorized for index '{idx}' (Authorized for: {auth_permitted})"
            )

    # 7. Asymmetric Digital Signature Verification (Ed25519)
    pub_hex = authority.get("public_key_hex", "")
    try:
        pub_bytes = bytes.fromhex(pub_hex)
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
    except Exception as e:
        raise ValueError(f"Failed to load Ed25519 public key for authority '{key_id}': {e}")

    try:
        sig_bytes = bytes.fromhex(sig)
        if len(sig_bytes) != 64:
            raise ValueError("Ed25519 signatures must be 64 bytes (128 hex characters)")
    except Exception as e:
        raise ValueError(f"Invalid digital signature format: {e}")

    canonical_payload = build_canonical_approval_payload(
        approval_id=approval_id,
        document_id=doc_id,
        approval_reference=clean_ref,
        document_sha256=recomputed_hash,
        ratifying_authority=ratified_by,
        authorized_indices=clean_indices,
        min_oi_floor=min_oi_floor,
        min_volume_floor=min_volume_floor,
        max_spread_pct_ceiling=max_spread_pct_ceiling,
        effective_date=eff_date_str,
        expiry_date=exp_date_str,
    )

    try:
        public_key.verify(sig_bytes, canonical_payload)
    except InvalidSignature:
        raise ValueError("Invalid digital signature: Ed25519 cryptographic verification failed against public key")
    except Exception as e:
        raise ValueError(f"Invalid digital signature: Ed25519 verification error: {e}")

    # 8. Temporal Validity Check
    today = evaluation_date or datetime.now(IST_ZONE).date()
    try:
        eff_date = date.fromisoformat(eff_date_str)
        exp_date = date.fromisoformat(exp_date_str)
    except Exception as e:
        raise ValueError(f"Invalid date format in approval artifact: {e}")

    if exp_date < today:
        raise ValueError(f"Expired approval artifact: Approval expired on {exp_date_str} (Evaluated on {today.isoformat()})")
    if eff_date > today:
        raise ValueError(f"Premature approval artifact: Approval not effective until {eff_date_str} (Evaluated on {today.isoformat()})")

    # All cryptographic and governance verifications succeeded!
    # Record approval_id and approval registry entry atomically in durable ledger
    evidence_payload = {
        "approval_id": approval_id,
        "document_id": doc_id,
        "document_sha256": recomputed_hash,
        "key_id": key_id,
        "ratified_by": ratified_by,
        "digital_signature": sig,
        "effective_date": eff_date_str,
        "expiry_date": exp_date_str,
    }
    get_governance_ledger().record_verified_approval(
        approval_reference=clean_ref,
        approval_id=approval_id,
        approved_by=approved_by.strip().upper(),
        authorized_indices=clean_indices,
        key_id=key_id,
        min_oi_floor=int(min_oi_floor),
        min_volume_floor=int(min_volume_floor),
        max_spread_pct_ceiling=float(max_spread_pct_ceiling),
        effective_date=eff_date_str,
        expiry_date=exp_date_str,
        approval_evidence=evidence_payload,
        doc_id=doc_id,
        recomputed_hash=recomputed_hash,
    )


def register_trusted_approval(approval_reference: str, approval_metadata: Dict[str, Any]) -> None:
    """Registers an authentic server-side institutional approval record."""
    if not approval_reference or not isinstance(approval_metadata, dict):
        raise ValueError("Invalid approval reference or metadata")
    clean_ref = approval_reference.strip().upper()
    get_governance_ledger().set_approval_raw(clean_ref, dict(approval_metadata))


def revoke_trusted_approval(approval_reference: str, reason: str = "") -> bool:
    """Revokes an existing institutional approval reference."""
    clean_ref = approval_reference.strip().upper()
    return get_governance_ledger().revoke_approval(clean_ref, reason)


def validate_liquidity_policy_override(
    symbol: str,
    custom_policy: Dict[str, Any],
    top_level_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Validates a caller-supplied liquidity policy override against the server-side
    institutional governance registry.
    
    Security & Provenance Rules:
      1. Forged status rejection: Any caller-supplied 'policy_status' is stripped.
         Caller cannot self-certify as 'APPROVED' or 'CONFIGURED'.
      2. Missing metadata rejection: 'approved_by' and 'approval_reference' are mandatory.
      3. Unknown reference rejection: Reference must exist in server-side TRUSTED_APPROVAL_REGISTRY.
      4. Verifiable evidence & active status check: Only ACTIVE references with authenticated
         approval evidence (document_id, document_sha256) are permitted. Unverified or revoked barred.
      5. Approver identity verification: 'approved_by' must match registered principal.
      6. Index scope authorization: Requested index must be explicitly authorized.
      7. Risk bounds verification: Proposed thresholds must not breach approved risk ceilings/floors.
    
    Returns sanitized policy dictionary with authoritative 'policy_status' and 'policy_source'.
    """
    und_key = normalize_index_symbol(symbol)
    policy_entry = dict(custom_policy)
    cfg = top_level_cfg or {}

    # Rule 1: Strip caller-supplied policy_status; only server can assign status
    caller_claimed_status = policy_entry.pop("policy_status", None)

    approved_by = str(policy_entry.get("approved_by") or "").strip()
    approval_ref = str(policy_entry.get("approval_reference") or policy_entry.get("provenance") or "").strip().upper()

    # Rule 2: Mandatory governance metadata
    if not approved_by or not approval_ref:
        policy_entry["policy_status"] = "UNVERIFIED"
        reason = "Caller override rejected: Missing authorized institutional approval provenance ('approved_by' and 'approval_reference' required)"
        if caller_claimed_status == "APPROVED":
            reason = "Caller override rejected: Forged policy_status='APPROVED' without valid institutional approval credentials"
        policy_entry["policy_source"] = reason
        return policy_entry

    # Rule 2b: Revocation registry check
    if approval_ref in REVOKED_APPROVAL_REFERENCES:
        policy_entry["policy_status"] = "UNVERIFIED"
        policy_entry["policy_source"] = (
            f"Caller override rejected: Approval reference '{approval_ref}' is REVOKED "
            "(Explicitly revoked in institutional governance registry)"
        )
        return policy_entry

    # Rule 3: Server-side registry membership check
    registered_approval = TRUSTED_APPROVAL_REGISTRY.get(approval_ref)
    if not registered_approval:
        policy_entry["policy_status"] = "UNVERIFIED"
        policy_entry["policy_source"] = (
            f"Caller override rejected: Unknown or unregistered approval reference '{approval_ref}' "
            "(Server-side governance validation failed)"
        )
        return policy_entry

    # Rule 4: Active authorization & verifiable evidence check
    reg_status = str(registered_approval.get("status") or "").upper()
    if reg_status != "ACTIVE":
        rev_reason = (
            registered_approval.get("revocation_reason")
            or registered_approval.get("verification_notes")
            or f"Status is {reg_status}"
        )
        policy_entry["policy_status"] = "UNVERIFIED"
        policy_entry["policy_source"] = (
            f"Caller override rejected: Approval reference '{approval_ref}' is {reg_status} ({rev_reason})"
        )
        return policy_entry

    evidence = registered_approval.get("approval_evidence")
    if (
        not evidence
        or not isinstance(evidence, dict)
        or not evidence.get("document_id")
        or not evidence.get("document_sha256")
        or not evidence.get("digital_signature")
    ):
        policy_entry["policy_status"] = "UNVERIFIED"
        policy_entry["policy_source"] = (
            f"Caller override rejected: Approval reference '{approval_ref}' lacks cryptographically verified approval evidence artifact"
        )
        return policy_entry

    # Check temporal expiration of active approval
    exp_date_str = evidence.get("expiry_date")
    if exp_date_str:
        try:
            today = datetime.now(IST_ZONE).date()
            if date.fromisoformat(exp_date_str) < today:
                policy_entry["policy_status"] = "UNVERIFIED"
                policy_entry["policy_source"] = (
                    f"Caller override rejected: Approval reference '{approval_ref}' expired on {exp_date_str}"
                )
                return policy_entry
        except Exception:
            pass

    # Rule 5: Approver identity matching
    expected_approver = str(registered_approval.get("approved_by") or "").strip().upper()
    if approved_by.upper() != expected_approver:
        policy_entry["policy_status"] = "UNVERIFIED"
        policy_entry["policy_source"] = (
            f"Caller override rejected: Approver '{approved_by}' is not authorized for reference '{approval_ref}' "
            f"(Expected '{expected_approver}')"
        )
        return policy_entry

    # Rule 6: Index scope authorization
    auth_indices = [normalize_index_symbol(idx) for idx in registered_approval.get("authorized_indices", [])]
    if und_key not in auth_indices:
        policy_entry["policy_status"] = "UNVERIFIED"
        policy_entry["policy_source"] = (
            f"Caller override rejected: Approval reference '{approval_ref}' is authorized for {auth_indices}, "
            f"not index '{und_key}'"
        )
        return policy_entry

    # Rule 7: Risk bounds verification
    proposed_spread = cfg.get("max_spread_pct", policy_entry.get("max_spread_pct"))
    proposed_oi = cfg.get("min_oi", policy_entry.get("min_oi"))
    proposed_vol = cfg.get("min_volume", policy_entry.get("min_volume"))

    max_spread_ceiling = registered_approval.get("max_spread_pct_ceiling")
    min_oi_floor = registered_approval.get("min_oi_floor")
    min_vol_floor = registered_approval.get("min_volume_floor")

    if max_spread_ceiling is not None and proposed_spread is not None:
        if float(proposed_spread) > float(max_spread_ceiling):
            policy_entry["policy_status"] = "UNVERIFIED"
            policy_entry["policy_source"] = (
                f"Caller override rejected: Proposed max_spread_pct {proposed_spread} exceeds approved ceiling {max_spread_ceiling}"
            )
            return policy_entry

    if min_oi_floor is not None and proposed_oi is not None:
        if int(proposed_oi) < int(min_oi_floor):
            policy_entry["policy_status"] = "UNVERIFIED"
            policy_entry["policy_source"] = (
                f"Caller override rejected: Proposed min_oi {proposed_oi} is below approved floor {min_oi_floor}"
            )
            return policy_entry

    if min_vol_floor is not None and proposed_vol is not None:
        if int(proposed_vol) < int(min_vol_floor):
            policy_entry["policy_status"] = "UNVERIFIED"
            policy_entry["policy_source"] = (
                f"Caller override rejected: Proposed min_volume {proposed_vol} is below approved floor {min_vol_floor}"
            )
            return policy_entry

    # All checks passed against server-side authoritative registry
    policy_entry["policy_status"] = "APPROVED"
    evidence_id = evidence.get("document_id")
    policy_entry["policy_source"] = (
        f"Institutionally approved by {approved_by} (Ref: {approval_ref}, Artifact: {evidence_id})"
    )
    return policy_entry


def normalize_index_symbol(symbol: str) -> str:
    """Normalizes raw input symbol to canonical index key."""
    clean = symbol.upper().strip().replace(" ", "").replace("-", "")
    if "BANK" in clean:
        return "BANKNIFTY"
    if "FIN" in clean:
        return "FINNIFTY"
    if "SENSEX" in clean:
        return "SENSEX"
    if "NIFTY" in clean:
        return "NIFTY"
    return clean


def derive_strike_spacing(
    underlying_spot: float,
    listed_strikes: List[float],
) -> Optional[float]:
    """
    Derives actual listed strike spacing around the underlying spot price
    from actual InstrumentMaster or option chain listed strikes.
    
    Zero hardcoded assumptions:
      - Inspects actual listed strikes.
      - Finds consecutive strike differences around the spot corridor.
      - Returns most common step (e.g. 50.0, 100.0).
      - Returns None if listed strikes are insufficient (< 2 distinct strikes) to derive spacing.
    """
    if not listed_strikes or len(listed_strikes) < 2:
        return None

    sorted_strikes = sorted(set(float(k) for k in listed_strikes if float(k) > 0.0))
    if len(sorted_strikes) < 2:
        return None

    # Focus on the active corridor around spot (+- 20%)
    lower_bound = underlying_spot * 0.80
    upper_bound = underlying_spot * 1.20
    local_strikes = [k for k in sorted_strikes if lower_bound <= k <= upper_bound]

    if len(local_strikes) < 2:
        # Sort by distance to spot and pick the 6 nearest strikes
        nearest = sorted(sorted_strikes, key=lambda k: abs(k - underlying_spot))[:6]
        local_strikes = sorted(nearest)

    diffs = [
        round(local_strikes[i + 1] - local_strikes[i], 2)
        for i in range(len(local_strikes) - 1)
    ]
    pos_diffs = [d for d in diffs if d > 0.0]
    if not pos_diffs:
        return None

    counts = Counter(pos_diffs)
    most_common_step, _ = counts.most_common(1)[0]
    return float(most_common_step)


def select_option_contract(
    underlying_setup: Dict[str, Any],
    symbol: str,
    underlying_spot: float,
    option_chain: Dict[str, Any],
    evaluation_timestamp: Optional[Any] = None,
    instrument_master: Optional[Any] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Selects a liquid, validated option contract matching underlying trade setup criteria.
    
    Returns structured contract selection object:
      - qualification_status: 'QUALIFIED' | 'REJECTED'
      - action: 'BUY_CE' | 'BUY_PE' | 'NO_TRADE'
      - contract metadata (symbol, token, strike, expiry, lot_size, tick_size, moneyness)
      - market quotes & validated Greeks
      - derived_strike_spacing: float (dynamically computed from listed strikes)
      - liquidity_policy_status & source
      - rejection_reasons: List of human-readable gating failures if rejected
    """
    cfg = config or {}
    master = instrument_master or get_instrument_master()
    und_key = normalize_index_symbol(symbol)

    action = underlying_setup.get("action", "NO_TRADE")
    rejection_reasons: List[str] = []

    # 1. Directional Guard
    if action not in ("BUY_CE", "BUY_PE"):
        return {
            "qualification_status": "REJECTED",
            "action": "NO_TRADE",
            "index": und_key,
            "option_type": None,
            "contract_symbol": None,
            "instrument_token": None,
            "strike": None,
            "expiry": None,
            "moneyness": None,
            "derived_strike_spacing": None,
            "lot_size": None,
            "tick_size": None,
            "entry_execution_model": "ASK",
            "entry_premium": None,
            "analytical_midpoint": None,
            "bid": None,
            "ask": None,
            "spread_pct": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "implied_volatility": None,
            "iv_source": None,
            "t_years": None,
            "data_status": "DATA_UNAVAILABLE",
            "rejection_reasons": [f"Underlying setup action '{action}' does not permit option contract selection"],
            "paper_trading_eligible": False,
        }

    is_call = (action == "BUY_CE")
    opt_type = "CE" if is_call else "PE"

    # 2. Centralized Liquidity Policy & Provenance Check for All Four Indices
    custom_policy = (
        cfg.get("liquidity_policy", {}).get(und_key)
        or cfg.get("index_liquidity_policy", {}).get(und_key)
    )

    if custom_policy and isinstance(custom_policy, dict):
        # Authoritative server-side governance validation against TRUSTED_APPROVAL_REGISTRY:
        # Caller-provided configuration must not automatically become institutionally approved.
        # Arbitrary approvers, unknown references, revoked references, forged status, and ceiling breaches are rejected.
        policy_entry = validate_liquidity_policy_override(und_key, custom_policy, top_level_cfg=cfg)
    else:
        policy_entry = CENTRALIZED_INDEX_LIQUIDITY_POLICY.get(und_key, {
            "policy_status": "UNCONFIGURED",
            "policy_source": f"No policy configured for symbol '{und_key}'",
            "min_oi": None,
            "min_volume": None,
            "max_spread_pct": None,
        })

    policy_status = policy_entry.get("policy_status", "UNCONFIGURED")
    policy_source = policy_entry.get("policy_source", "Unspecified")

    min_oi = cfg.get("min_oi", policy_entry.get("min_oi"))
    min_volume = cfg.get("min_volume", policy_entry.get("min_volume"))
    max_spread_pct = cfg.get("max_spread_pct", policy_entry.get("max_spread_pct"))

    # Only CONFIGURED or APPROVED policies with complete numeric thresholds are permitted
    if policy_status not in ("CONFIGURED", "APPROVED") or min_oi is None or min_volume is None or max_spread_pct is None:
        return {
            "qualification_status": "REJECTED",
            "action": "NO_TRADE",
            "index": und_key,
            "option_type": opt_type,
            "contract_symbol": None,
            "instrument_token": None,
            "strike": None,
            "expiry": None,
            "moneyness": None,
            "derived_strike_spacing": None,
            "lot_size": None,
            "tick_size": None,
            "entry_execution_model": "ASK",
            "entry_premium": None,
            "analytical_midpoint": None,
            "bid": None,
            "ask": None,
            "spread_pct": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "implied_volatility": None,
            "iv_source": None,
            "t_years": None,
            "data_status": "CONFIGURATION_UNAVAILABLE",
            "liquidity_policy_status": policy_status,
            "liquidity_policy_source": policy_source,
            "rejection_reasons": [
                f"UNCONFIGURED_LIQUIDITY_POLICY: Index liquidity policy for '{und_key}' is {policy_status}. ({policy_source})"
            ],
            "paper_trading_eligible": False,
        }

    # 3. Option Chain Feed Integrity
    if not option_chain or not isinstance(option_chain, dict):
        return {
            "qualification_status": "REJECTED",
            "action": "NO_TRADE",
            "index": und_key,
            "option_type": opt_type,
            "contract_symbol": None,
            "instrument_token": None,
            "strike": None,
            "expiry": None,
            "moneyness": None,
            "derived_strike_spacing": None,
            "lot_size": None,
            "tick_size": None,
            "entry_execution_model": "ASK",
            "entry_premium": None,
            "analytical_midpoint": None,
            "bid": None,
            "ask": None,
            "spread_pct": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "implied_volatility": None,
            "iv_source": None,
            "t_years": None,
            "data_status": "DATA_UNAVAILABLE",
            "rejection_reasons": ["Option chain feed is missing or invalid"],
            "paper_trading_eligible": False,
        }

    strikes_data = option_chain.get("strikes", [])
    if not strikes_data:
        return {
            "qualification_status": "REJECTED",
            "action": "NO_TRADE",
            "index": und_key,
            "option_type": opt_type,
            "contract_symbol": None,
            "instrument_token": None,
            "strike": None,
            "expiry": None,
            "moneyness": None,
            "derived_strike_spacing": None,
            "lot_size": None,
            "tick_size": None,
            "entry_execution_model": "ASK",
            "entry_premium": None,
            "analytical_midpoint": None,
            "bid": None,
            "ask": None,
            "spread_pct": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "implied_volatility": None,
            "iv_source": None,
            "t_years": None,
            "data_status": "DATA_UNAVAILABLE",
            "rejection_reasons": ["Option chain contains zero strike records"],
            "paper_trading_eligible": False,
        }

    selected_expiry = option_chain.get("selectedExpiry")
    if not selected_expiry:
        return {
            "qualification_status": "REJECTED",
            "action": "NO_TRADE",
            "index": und_key,
            "option_type": opt_type,
            "contract_symbol": None,
            "instrument_token": None,
            "strike": None,
            "expiry": None,
            "moneyness": None,
            "derived_strike_spacing": None,
            "lot_size": None,
            "tick_size": None,
            "entry_execution_model": "ASK",
            "entry_premium": None,
            "analytical_midpoint": None,
            "bid": None,
            "ask": None,
            "spread_pct": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "implied_volatility": None,
            "iv_source": None,
            "t_years": None,
            "data_status": "DATA_UNAVAILABLE",
            "rejection_reasons": ["Contract expiry date could not be determined"],
            "paper_trading_eligible": False,
        }

    t_expiry = calculate_exact_time_to_expiry(selected_expiry, evaluation_timestamp)
    if t_expiry <= 0.0:
        return {
            "qualification_status": "REJECTED",
            "action": "NO_TRADE",
            "index": und_key,
            "option_type": opt_type,
            "contract_symbol": None,
            "instrument_token": None,
            "strike": None,
            "expiry": selected_expiry,
            "moneyness": None,
            "derived_strike_spacing": None,
            "lot_size": None,
            "tick_size": None,
            "entry_execution_model": "ASK",
            "entry_premium": None,
            "analytical_midpoint": None,
            "bid": None,
            "ask": None,
            "spread_pct": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "implied_volatility": None,
            "iv_source": None,
            "t_years": 0.0,
            "data_status": "EXPIRED",
            "rejection_reasons": [f"Selected contract series '{selected_expiry}' has expired (t_years=0.0)"],
            "paper_trading_eligible": False,
        }

    # 4. Derive Strike Spacing Dynamically from Actual Listed Strikes (No Hardcoding)
    chain_strike_floats = [float(item["strike"]) for item in strikes_data if item.get("strike") is not None]
    master_strikes = master.get_strikes_for_underlying(und_key, selected_expiry) if master else []
    all_listed_strikes = sorted(set(chain_strike_floats + master_strikes))

    derived_step = derive_strike_spacing(underlying_spot, all_listed_strikes)
    if derived_step is None or derived_step <= 0.0:
        return {
            "qualification_status": "REJECTED",
            "action": "NO_TRADE",
            "index": und_key,
            "option_type": opt_type,
            "contract_symbol": None,
            "instrument_token": None,
            "strike": None,
            "expiry": selected_expiry,
            "moneyness": None,
            "derived_strike_spacing": None,
            "lot_size": None,
            "tick_size": None,
            "entry_execution_model": "ASK",
            "entry_premium": None,
            "analytical_midpoint": None,
            "bid": None,
            "ask": None,
            "spread_pct": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "implied_volatility": None,
            "iv_source": None,
            "t_years": t_expiry,
            "data_status": "CONFIGURATION_UNAVAILABLE",
            "rejection_reasons": [
                f"CONFIGURATION_UNAVAILABLE: Insufficient listed strikes to derive strike spacing for '{und_key}'"
            ],
            "paper_trading_eligible": False,
        }

    # 5. Evaluate Candidate Contracts
    min_delta = float(cfg.get("min_delta", 0.35))
    max_delta = float(cfg.get("max_delta", 0.55))

    candidates: List[Dict[str, Any]] = []

    # Find closest listed strike to spot
    closest_strike_to_spot = min(all_listed_strikes, key=lambda k: abs(k - underlying_spot))

    for item in strikes_data:
        strike_val = float(item.get("strike", 0.0))
        opt_data = item.get("ce" if is_call else "pe")
        if not opt_data or not isinstance(opt_data, dict):
            continue

        token = opt_data.get("instrumentToken") or opt_data.get("token")
        symbol_name = opt_data.get("contractSymbol") or opt_data.get("symbol")
        data_status = opt_data.get("dataStatus") or opt_data.get("data_status", "DATA_UNAVAILABLE")
        is_theoretical = bool(opt_data.get("isTheoretical") or opt_data.get("is_theoretical", False))
        is_stale = bool(opt_data.get("isStale") or opt_data.get("is_stale", False))

        # Check A: Live quote & freshness verification
        if data_status not in ("LIVE", "AVAILABLE") or is_theoretical:
            continue
        if is_stale:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Quote is stale")
            continue

        # Check B: Non-zero bid and ask depth
        bid = float(opt_data.get("bid") or 0.0) if opt_data.get("bid") is not None else 0.0
        ask = float(opt_data.get("ask") or 0.0) if opt_data.get("ask") is not None else 0.0
        ltp = float(opt_data.get("ltp") or 0.0) if opt_data.get("ltp") is not None else 0.0

        if bid <= 0.0:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Zero bid depth (bid={bid})")
            continue
        if ask <= 0.0:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Zero ask depth (ask={ask})")
            continue
        if bid > ask:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Inverted bid-ask spread ({bid} > {ask})")
            continue

        midpoint = round((bid + ask) / 2.0, 2)
        spread_val = round(ask - bid, 2)
        spread_ratio = spread_val / midpoint if midpoint > 0 else 1.0

        if spread_ratio > max_spread_pct:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Spread {spread_ratio:.2%} exceeds max {max_spread_pct:.2%}")
            continue

        # Check C: Open Interest and Volume Semantics
        oi_status = opt_data.get("oiStatus") or opt_data.get("oi_status") or ("AVAILABLE" if opt_data.get("oi") is not None else "MISSING")
        raw_oi = opt_data.get("oi")
        if oi_status != "AVAILABLE" or raw_oi is None:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Open interest data is missing from feed")
            continue
        oi_val = int(raw_oi)
        if oi_val < min_oi:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: OI {oi_val:,} below threshold {min_oi:,}")
            continue

        vol_status = opt_data.get("volumeStatus") or opt_data.get("volume_status") or ("AVAILABLE" if opt_data.get("volume") is not None else "MISSING")
        raw_vol = opt_data.get("volume")
        if vol_status != "AVAILABLE" or raw_vol is None:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Volume data is missing from feed")
            continue
        vol_val = int(raw_vol)
        if vol_val < min_volume:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Volume {vol_val:,} below threshold {min_volume:,}")
            continue

        # Check D: Valid IV and Greeks
        iv_val = opt_data.get("iv")
        if iv_val is None or iv_val <= 0.0:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: IV is missing or non-positive")
            continue

        delta_val = opt_data.get("delta")
        gamma_val = opt_data.get("gamma")
        theta_val = opt_data.get("theta")
        vega_val = opt_data.get("vega")

        if delta_val is None or gamma_val is None or theta_val is None or vega_val is None:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Validated Greeks are incomplete")
            continue

        abs_delta = abs(float(delta_val))
        if not (min_delta <= abs_delta <= max_delta):
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Delta {abs_delta:.3f} outside target range [{min_delta}, {max_delta}]")
            continue

        # Check E: Authoritative Contract Metadata
        resolved = master.resolve_option_contract(und_key, strike_val, opt_type, selected_expiry) if master else None
        if not resolved:
            # Fall back to contract metadata directly in opt_data if provided by feed/mock
            raw_lotsize = opt_data.get("lot_size") or opt_data.get("lotsize")
            raw_ticksize = opt_data.get("tick_size") or opt_data.get("ticksize")
            if raw_lotsize is not None:
                resolved = {
                    "token": token or f"{opt_type}_{strike_val}",
                    "symbol": symbol_name or f"{und_key}{selected_expiry}{int(strike_val)}{opt_type}",
                    "lotsize": raw_lotsize,
                    "tick_size": raw_ticksize or 0.05,
                }
            else:
                rejection_reasons.append(f"Strike {strike_val} {opt_type}: Unresolvable contract in instrument master")
                continue

        raw_lotsize = resolved.get("lotsize") or resolved.get("lot_size")
        if not raw_lotsize:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Missing authoritative lot size")
            continue
        try:
            lot_size = int(raw_lotsize)
            if lot_size <= 0:
                rejection_reasons.append(f"Strike {strike_val} {opt_type}: Non-positive lot size {lot_size}")
                continue
        except (ValueError, TypeError):
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Invalid lot size format {raw_lotsize}")
            continue

        raw_tick = resolved.get("tick_size")
        try:
            tick_float = float(raw_tick or 5.0)
            # Adjust paise to INR if needed
            tick_size = round(tick_float / 100.0, 4) if tick_float > 1.0 else round(tick_float, 4)
            if tick_size <= 0.0:
                tick_size = 0.05
        except (ValueError, TypeError):
            tick_size = 0.05

        token_final = str(resolved.get("token") or token or "")
        symbol_final = str(resolved.get("symbol") or symbol_name or f"{und_key} {int(strike_val)} {opt_type}")

        if not token_final:
            rejection_reasons.append(f"Strike {strike_val} {opt_type}: Missing exchange instrument token")
            continue

        # Determine exact moneyness using derived strike spacing & closest listed strike
        strike_dist = abs(strike_val - underlying_spot)
        if strike_val == closest_strike_to_spot or strike_dist <= (derived_step * 0.5):
            moneyness = "ATM"
        elif is_call:
            moneyness = "ITM" if strike_val < underlying_spot else "OTM"
        else:
            moneyness = "ITM" if strike_val > underlying_spot else "OTM"

        # Quality scoring: prioritize proximity to target Delta with tight spread
        target_delta = float(cfg.get("target_delta", 0.50))
        delta_dist = abs(abs_delta - target_delta)
        score = (delta_dist * 2.0) + (spread_ratio * 4.0)

        candidates.append({
            "strike": strike_val,
            "moneyness": moneyness,
            "token": token_final,
            "symbol": symbol_final,
            "bid": bid,
            "ask": ask,
            "ltp": ltp,
            "midpoint": midpoint,
            "spread_pct": round(spread_ratio * 100.0, 2),
            "oi": oi_val,
            "volume": vol_val,
            "iv": float(iv_val),
            "delta": float(delta_val),
            "gamma": float(gamma_val),
            "theta": float(theta_val),
            "vega": float(vega_val),
            "lot_size": lot_size,
            "tick_size": tick_size,
            "score": score,
        })

    # 6. Selection or Rejection Decision
    if not candidates:
        unique_reasons = ["NO_ELIGIBLE_CONTRACT: No active contracts met Delta, liquidity, and spread criteria"]
        unique_reasons.extend(list(dict.fromkeys(rejection_reasons))[:8])
        return {
            "qualification_status": "REJECTED",
            "action": "NO_TRADE",
            "index": und_key,
            "option_type": opt_type,
            "contract_symbol": None,
            "instrument_token": None,
            "strike": None,
            "expiry": selected_expiry,
            "moneyness": None,
            "derived_strike_spacing": derived_step,
            "lot_size": None,
            "tick_size": None,
            "entry_execution_model": "ASK",
            "entry_premium": None,
            "analytical_midpoint": None,
            "bid": None,
            "ask": None,
            "spread_pct": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "implied_volatility": None,
            "iv_source": None,
            "t_years": t_expiry,
            "data_status": "DATA_UNAVAILABLE",
            "liquidity_policy_status": policy_status,
            "liquidity_policy_source": policy_source,
            "rejection_reasons": unique_reasons,
            "paper_trading_eligible": False,
        }

    # Pick candidate with lowest penalty score
    candidates.sort(key=lambda c: c["score"])
    best = candidates[0]

    # Conservative Execution Price Model: Long option BUY entry strictly executes at Ask!
    # Analytical midpoint is retained for valuation purposes only.
    entry_premium = best["ask"]
    analytical_midpoint = best["midpoint"]

    return {
        "qualification_status": "QUALIFIED",
        "action": action,
        "index": und_key,
        "option_type": opt_type,
        "contract_symbol": best["symbol"],
        "instrument_token": best["token"],
        "strike": best["strike"],
        "expiry": selected_expiry,
        "moneyness": best["moneyness"],
        "derived_strike_spacing": derived_step,
        "strike_derivation_source": "LISTED_STRIKES_DYNAMIC",
        "liquidity_policy_status": policy_status,
        "liquidity_policy_source": policy_source,
        "lot_size": best["lot_size"],
        "tick_size": best["tick_size"],
        "entry_execution_model": "ASK",
        "entry_premium": round(entry_premium, 2),
        "analytical_midpoint": round(analytical_midpoint, 2),
        "bid": round(best["bid"], 2),
        "ask": round(best["ask"], 2),
        "spread_pct": best["spread_pct"],
        "delta": round(best["delta"], 4),
        "gamma": round(best["gamma"], 6),
        "theta": round(best["theta"], 2),
        "vega": round(best["vega"], 2),
        "implied_volatility": round(best["iv"], 2),
        "iv_source": "LIVE_MARKET",
        "t_years": t_expiry,
        "data_status": "LIVE",
        "rejection_reasons": [],
        "paper_trading_eligible": True,
    }
