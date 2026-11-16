"""
AIVOLVE Phase 4 Step 4.2 — Isolated Backtesting Configuration & Governance Policies.

Provides canonical instrument definitions, strict non-substituting timeframe mappings,
Angel One SmartAPI historical chunk limits, production persistence isolation guards,
and read-only institutional SENSEX governance verification.

Strict Governance:
- Operating mode: PAPER_TRADING_ONLY (foundation data & deterministic intelligence replay only).
- Zero modifications to accepted Phase 1, Phase 2, Phase 3, or legacy backtester modules.
- Zero writes to protected production persistence files or governance_ledger.db.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

PACKAGE_VERSION: str = "4.2.0"
EXECUTION_MODE: str = "PAPER_TRADING_ONLY"
DEFAULT_TIMEZONE_NAME: str = "Asia/Kolkata"
IST_ZONE: ZoneInfo = ZoneInfo(DEFAULT_TIMEZONE_NAME)

MARKET_OPEN_HHMM: str = "09:15"
MARKET_CLOSE_HHMM: str = "15:30"

BACKEND_ROOT: Path = Path(__file__).resolve().parents[2]
DEFAULT_BACKTEST_DATA_DIR: Path = BACKEND_ROOT / "data" / "backtest"
DEFAULT_BACKTEST_DB_PATH: Path = DEFAULT_BACKTEST_DATA_DIR / "backtest_foundation.db"
DEFAULT_GOVERNANCE_DB_PATH: Path = BACKEND_ROOT / "app" / "data" / "governance_ledger.db"

PROTECTED_PRODUCTION_FILENAMES: Tuple[str, ...] = (
    "aivolve_trading.db",
    "governance_ledger.db",
    "paper_trading_records.json",
    "ml_trade_dataset.json",
    "what_ai_learned.json",
    "ml_strategy_weights.json",
)

SUPPORTED_INDICES: Tuple[str, ...] = (
    "NIFTY 50",
    "BANK NIFTY",
    "FINNIFTY",
    "SENSEX",
)

CANONICAL_INDEX_MAP: Dict[str, str] = {
    "NIFTY": "NIFTY 50",
    "NIFTY50": "NIFTY 50",
    "NIFTY 50": "NIFTY 50",
    "BANKNIFTY": "BANK NIFTY",
    "BANK NIFTY": "BANK NIFTY",
    "NIFTY BANK": "BANK NIFTY",
    "FINNIFTY": "FINNIFTY",
    "NIFTYFIN": "FINNIFTY",
    "NIFTY FINANCIAL SERVICES": "FINNIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY",
    "SENSEX": "SENSEX",
    "BSE SENSEX": "SENSEX",
}

CONTRACT_LEDGER_INDEX_KEY: Dict[str, str] = {
    "NIFTY 50": "NIFTY",
    "BANK NIFTY": "BANKNIFTY",
    "FINNIFTY": "FINNIFTY",
    "SENSEX": "SENSEX",
}

ANGELONE_INSTRUMENT_METADATA: Dict[str, Dict[str, str]] = {
    "NIFTY 50": {
        "exchange": "NSE",
        "symbol_token": "99926000",
        "tradingsymbol": "NIFTY",
    },
    "BANK NIFTY": {
        "exchange": "NSE",
        "symbol_token": "99926009",
        "tradingsymbol": "BANKNIFTY",
    },
    "FINNIFTY": {
        "exchange": "NSE",
        "symbol_token": "99926037",
        "tradingsymbol": "FINNIFTY",
    },
    "SENSEX": {
        "exchange": "BSE",
        "symbol_token": "99919000",
        "tradingsymbol": "SENSEX",
    },
}

# Strictly supported storage/download timeframes (Step 4.2 Section 1)
SUPPORTED_TIMEFRAMES: Tuple[str, ...] = ("1m", "3m", "5m", "15m", "1h", "1d")

# Strictly required Step 3.7 Multi-Timeframe ICT/SMC order (Step 4.2 Section 5)
REPLAY_MTF_TIMEFRAMES: Tuple[str, ...] = ("1h", "15m", "5m", "3m", "1m")

# Exact 1-to-1 timeframe normalization without silent cross-timeframe substitution
CANONICAL_TIMEFRAME_MAP: Dict[str, str] = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "1d": "1d",
}

TIMEFRAME_DURATION_MINUTES: Dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "1d": 1440,
}

ANGELONE_INTERVAL_MAP: Dict[str, str] = {
    "1m": "ONE_MINUTE",
    "3m": "THREE_MINUTE",
    "5m": "FIVE_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "1h": "ONE_HOUR",
    "1d": "ONE_DAY",
}

# Safe chunk windows (calendar days per request) respecting Angel One SmartAPI limits
ANGELONE_MAX_CHUNK_DAYS: Dict[str, int] = {
    "1m": 5,
    "3m": 15,
    "5m": 25,
    "15m": 60,
    "1h": 120,
    "1d": 365,
}


def assert_isolated_backtest_path(target_path: os.PathLike[str] | str) -> Path:
    """
    Fails closed if a configured storage path overlaps any protected production database
    or persistence JSON artifact.
    """
    if target_path is None or str(target_path).strip() == "":
        raise ValueError("Backtest storage path must be a non-empty filesystem path.")
    if str(target_path).strip() == ":memory:":
        raise ValueError("Explicit file-backed isolated path is required rather than ':memory:'.")

    resolved = Path(target_path).resolve()
    normalized_lower = str(resolved).replace("\\", "/").lower()
    basename_lower = resolved.name.lower()

    for protected in PROTECTED_PRODUCTION_FILENAMES:
        prot_lower = protected.lower()
        if basename_lower == prot_lower or normalized_lower.endswith("/" + prot_lower):
            raise PermissionError(
                f"ISOLATION VIOLATION: Backtest storage cannot target protected production artifact '{resolved}'."
            )
    return resolved


def normalize_instrument(symbol: str) -> str:
    """Normalizes a supported Indian index symbol cleanly without silently mapping unknown tickers."""
    if type(symbol) is not str or not symbol.strip():
        raise ValueError("Instrument symbol must be a non-empty string.")
    collapsed = " ".join(symbol.strip().upper().split())
    canonical = CANONICAL_INDEX_MAP.get(collapsed)
    if canonical is None:
        raise ValueError(
            f"Unsupported instrument '{symbol}'. Supported indices: {', '.join(SUPPORTED_INDICES)}."
        )
    return canonical


def normalize_timeframe(timeframe: str) -> str:
    """
    Validates and normalizes requested timeframe cleanly.
    Never substitutes one timeframe (e.g., 3m) with another (e.g., 15m).
    """
    if type(timeframe) is not str or not timeframe.strip():
        raise ValueError("Timeframe must be a non-empty string.")
    cleaned = timeframe.strip().lower()
    canonical = CANONICAL_TIMEFRAME_MAP.get(cleaned)
    if canonical is None:
        raise ValueError(
            f"Unsupported timeframe '{timeframe}'. Supported timeframes (no substitution permitted): {', '.join(SUPPORTED_TIMEFRAMES)}."
        )
    return canonical


def _ledger_index_aliases(symbol: str) -> Tuple[str, ...]:
    canonical = normalize_instrument(symbol)
    ledger_key = CONTRACT_LEDGER_INDEX_KEY[canonical]
    return tuple({canonical, ledger_key})


def verify_index_governance(
    instrument: str,
    *,
    sensex_governance_approved: bool = False,
    governance_db_path: Optional[Path | str] = None,
    evaluation_date: Optional[date] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Checks index governance strictly read-only.

    - NIFTY 50, BANK NIFTY, FINNIFTY: permitted.
    - SENSEX: permitted ONLY when a cryptographically verified ACTIVE non-revoked
      institutional approval exists in the read-only governance ledger for SENSEX AND
      matches authority Ed25519 signature verification (never writes or creates the DB).
    """
    canonical = normalize_instrument(instrument)
    if canonical != "SENSEX":
        return True, "AUTHORIZED", {"instrument": canonical, "reason": "Standard permitted NSE index"}

    ledger_path = Path(governance_db_path) if governance_db_path is not None else DEFAULT_GOVERNANCE_DB_PATH
    if not ledger_path.exists():
        return (
            False,
            "GOVERNANCE_LOCKOUT",
            {
                "instrument": canonical,
                "reason": f"Governance ledger not found at '{ledger_path}'; SENSEX remains locked.",
            },
        )

    eval_day = evaluation_date or date.today()

    try:
        from app.options.contract_selector import build_canonical_approval_payload
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except Exception as exc:
        return (
            False,
            "GOVERNANCE_LOCKOUT",
            {"instrument": canonical, "reason": f"Governance cryptographic verifier unavailable: {exc}"},
        )

    uri = f"file:{ledger_path.resolve().as_posix()}?mode=ro&immutable=1"
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row

        revoked_refs = {
            str(r["approval_reference"]).strip().upper()
            for r in conn.execute("SELECT approval_reference FROM revoked_approval_references").fetchall()
        }
        revoked_hashes = {
            str(r["document_sha256"]).strip().lower()
            for r in conn.execute("SELECT document_sha256 FROM revoked_document_hashes").fetchall()
        }
        authorities: Dict[str, Dict[str, Any]] = {}
        for row in conn.execute("SELECT * FROM trusted_governance_authorities").fetchall():
            authorities[str(row["key_id"]).strip().upper()] = dict(row)

        if not authorities:
            return (
                False,
                "GOVERNANCE_LOCKOUT",
                {
                    "instrument": canonical,
                    "reason": "Zero registered trusted governance authorities in governance ledger; SENSEX locked.",
                    "sensex_config_flag": sensex_governance_approved,
                },
            )

        import json

        rows = conn.execute("SELECT * FROM trusted_approval_registry").fetchall()
        for row in rows:
            ref = str(row["approval_reference"] or "").strip().upper()
            status = str(row["status"] or "").strip().upper()
            if status != "ACTIVE" or ref in revoked_refs:
                continue

            auth_indices_raw = json.loads(row["authorized_indices"] or "[]")
            auth_indices = [str(idx).strip().upper() for idx in auth_indices_raw]
            if not any(alias in auth_indices for alias in _ledger_index_aliases("SENSEX")):
                continue

            key_id = str(row["key_id"] or "").strip().upper()
            authority = authorities.get(key_id)
            if not authority or not authority.get("active") or authority.get("revoked"):
                continue

            authority_indices = [
                str(idx).strip().upper() for idx in json.loads(authority["authorized_indices"] or "[]")
            ]
            if not any(alias in authority_indices for alias in _ledger_index_aliases("SENSEX")):
                continue

            evidence_raw = row["approval_evidence_json"]
            if not evidence_raw:
                continue
            evidence = json.loads(evidence_raw)
            doc_hash = str(evidence.get("document_sha256") or "").strip().lower()
            sig_hex = str(evidence.get("digital_signature") or "").strip()
            if not doc_hash or doc_hash in revoked_hashes or not sig_hex:
                continue

            eff_str = str(row["effective_date"] or evidence.get("effective_date") or "")
            exp_str = str(row["expiry_date"] or evidence.get("expiry_date") or "")
            if not eff_str or not exp_str:
                continue
            eff_dt = date.fromisoformat(eff_str)
            exp_dt = date.fromisoformat(exp_str)
            if not (eff_dt <= eval_day <= exp_dt):
                continue

            # Verify Ed25519 cryptographic signature cleanly
            canonical_payload = build_canonical_approval_payload(
                approval_id=str(row["approval_id"] or evidence.get("approval_id") or ""),
                document_id=str(evidence.get("document_id") or ""),
                approval_reference=ref,
                document_sha256=doc_hash,
                ratifying_authority=str(evidence.get("ratified_by") or row["approved_by"] or ""),
                authorized_indices=sorted(
                    {CONTRACT_LEDGER_INDEX_KEY.get(a, a) for a in auth_indices_raw}
                ),
                min_oi_floor=int(row["min_oi_floor"]),
                min_volume_floor=int(row["min_volume_floor"]),
                max_spread_pct_ceiling=float(row["max_spread_pct_ceiling"]),
                effective_date=eff_str,
                expiry_date=exp_str,
            )
            pub_key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(authority["public_key_hex"]))
            pub_key.verify(bytes.fromhex(sig_hex), canonical_payload)

            if not sensex_governance_approved:
                return (
                    False,
                    "GOVERNANCE_LOCKOUT",
                    {
                        "instrument": canonical,
                        "reason": (
                            f"Active SENSEX ledger approval '{ref}' exists, but BacktestConfiguration.sensex_governance_approved is False (fail-closed)."
                        ),
                    },
                )

            return (
                True,
                "AUTHORIZED",
                {
                    "instrument": canonical,
                    "approval_reference": ref,
                    "key_id": key_id,
                    "effective_date": eff_str,
                    "expiry_date": exp_str,
                },
            )

        return (
            False,
            "GOVERNANCE_LOCKOUT",
            {
                "instrument": canonical,
                "reason": "No ACTIVE cryptographically verified institutional approval for SENSEX in governance ledger.",
                "sensex_config_flag": sensex_governance_approved,
            },
        )
    except Exception as exc:
        return (
            False,
            "GOVERNANCE_LOCKOUT",
            {"instrument": canonical, "reason": f"SENSEX governance verification failed closed: {exc}"},
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


class BacktestConfiguration(BaseModel):
    """Configuration governing Step 4.2 isolated historical ingestion and replay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    configuration_version: str = PACKAGE_VERSION
    execution_mode: str = EXECUTION_MODE
    timezone_name: str = DEFAULT_TIMEZONE_NAME
    storage_db_path: str = Field(default_factory=lambda: str(DEFAULT_BACKTEST_DB_PATH))
    governance_ledger_path: str = Field(default_factory=lambda: str(DEFAULT_GOVERNANCE_DB_PATH))
    sensex_governance_approved: bool = False
    rate_limit_delay_seconds: float = Field(default=0.35, ge=0.0, le=30.0)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=0.5, ge=0.0, le=60.0)
    strict_missing_intervals: bool = True
    require_volume_column: bool = True
    # Bounded completed-bar analysis window passed into frozen Phase 3 Step 3.7 after full
    # DataIntegrityAuditor validation (kept <= 250 to align with Step 3.1 max_lookback_bars=250).
    phase3_lookback_bars: int = Field(default=240, ge=30, le=250)
    market_open_hhmm: str = MARKET_OPEN_HHMM
    market_close_hhmm: str = MARKET_CLOSE_HHMM

    @model_validator(mode="after")
    def _validate_cfg(self) -> "BacktestConfiguration":
        if self.execution_mode != EXECUTION_MODE:
            raise ValueError(f"execution_mode must remain '{EXECUTION_MODE}'")
        assert_isolated_backtest_path(self.storage_db_path)
        ZoneInfo(self.timezone_name)
        return self

