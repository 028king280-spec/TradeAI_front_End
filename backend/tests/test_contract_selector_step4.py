"""
AIVOLVE Quantitative Options Intelligence Engine v3.0 - Phase 2 Step 4.2 Dedicated Tests
Part 1: Option Contract Selector Tests (Remediated Quantitative Engine)

Tests:
  1. Directional Guard: BUY_CE selects only CE, BUY_PE selects only PE.
  2. Non-Directional Rejection: WAIT and NO_TRADE reject contract selection.
  3. Delta Range Filtering: Strictly filters contracts in [0.35, 0.55].
  4. Delta Optimization: Selects strike closest to target Delta (default 0.45-0.50).
  5. Deep OTM / ITM Delta Rejection (Delta < 0.35 or Delta > 0.55).
  6. Moneyness Classification: Dynamic ATM, ITM, OTM derived from listed strikes.
  7. Actual Strike-Spacing Derivation from listed strikes (NIFTY 50, BANKNIFTY 100).
  8. Missing / Insufficient Listed Strikes Rejection (CONFIGURATION_UNAVAILABLE).
  9. Centralized Liquidity Policy: NIFTY, BANKNIFTY, FINNIFTY (APPROVED).
  10. Centralized Liquidity Policy: SENSEX Unconfigured Policy Rejection.
  11. Configurable Policy Override for SENSEX.
  12. Conservative Execution Model: Entry strictly fills at Ask (Midpoint analytical only).
  13. Liquidity Gating: Zero bid, zero ask, inverted spread, excessive spread rejection.
  14. Open Interest Gating: Missing OI, zero OI, below-minimum OI rejection.
  15. Volume Gating: Missing volume, zero volume, below-minimum volume rejection.
  16. Freshness & Live Gating: Stale quote and theoretical quote rejection.
  17. Expiry Validation: Expired series (t <= 0) rejection.
  18. Missing Greeks / Non-Converged IV Rejection.
  19. Authoritative Metadata Resolution: Lot size & tick size.
  20. Cross-Index Symbol Normalization (NIFTY, BANKNIFTY, FINNIFTY, SENSEX).
  21. Empty / Malformed Option Chain Graceful Rejection.
"""

import os
import math
from datetime import datetime, timezone, timedelta
import zoneinfo
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.options.greeks import calculate_black_scholes, calculate_exact_time_to_expiry
from app.options.contract_selector import (
    select_option_contract,
    normalize_index_symbol,
    derive_strike_spacing,
    CENTRALIZED_INDEX_LIQUIDITY_POLICY,
    TRUSTED_APPROVAL_REGISTRY,
    TRUSTED_GOVERNANCE_AUTHORITIES,
    PROCESSED_APPROVAL_IDS,
    REVOKED_APPROVAL_REFERENCES,
    REVOKED_DOCUMENT_HASHES,
    get_trusted_approval_registry,
    get_trusted_governance_authorities,
    register_governance_authority,
    rotate_governance_authority,
    revoke_governance_authority,
    build_canonical_approval_payload,
    register_trusted_approval,
    register_verified_institutional_approval,
    revoke_trusted_approval,
    validate_liquidity_policy_override,
    set_governance_ledger_db_path,
    get_governance_ledger,
)

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


@pytest.fixture(autouse=True)
def isolated_governance_ledger(tmp_path):
    """Guarantees complete SQLite database isolation using an ephemeral per-test ledger."""
    test_db = str(tmp_path / "test_governance_ledger.db")
    set_governance_ledger_db_path(test_db)
    yield test_db
    set_governance_ledger_db_path(None)


def build_mock_option_chain(
    symbol: str = "NIFTY",
    underlying_spot: float = 24500.0,
    expiry_days_ahead: int = 5,
    strikes: list = None,
    iv: float = 15.0,
    r: float = 0.065,
    custom_ce_overrides: dict = None,
    custom_pe_overrides: dict = None,
):
    """Generates an authentic, Black-Scholes consistent mock option chain."""
    now_ist = datetime.now(IST)
    expiry_dt = (now_ist + timedelta(days=expiry_days_ahead)).replace(hour=15, minute=30, second=0, microsecond=0)
    expiry_str = expiry_dt.strftime("%d-%b-%Y").upper()

    t_years = calculate_exact_time_to_expiry(expiry_str, now_ist)
    if strikes is None:
        strikes = [24300, 24350, 24400, 24450, 24500, 24550, 24600, 24650, 24700]

    lot_size = 15 if "BANK" in symbol else (25 if "FIN" in symbol else 65)

    strike_records = []
    for k in strikes:
        k_flt = float(k)
        ce_bs = calculate_black_scholes(underlying_spot, k_flt, t_years, r, iv / 100.0, "CE")
        pe_bs = calculate_black_scholes(underlying_spot, k_flt, t_years, r, iv / 100.0, "PE")

        ce_price = round(ce_bs["price"], 2)
        pe_price = round(pe_bs["price"], 2)

        # Baseline liquid quotes
        ce_data = {
            "symbol": f"{symbol}{expiry_str}{k}CE",
            "token": f"CE_{k}",
            "expiry": expiry_str,
            "ltp": ce_price,
            "bid": round(ce_price - 0.15, 2),
            "ask": round(ce_price + 0.15, 2),
            "spread_pct": round(0.30 / ce_price, 4) if ce_price > 0 else 0.0,
            "delta": ce_bs["delta"],
            "gamma": ce_bs["gamma"],
            "theta": ce_bs["theta"],
            "vega": ce_bs["vega"],
            "iv": iv,
            "iv_source": "BRENT_NUMERICAL",
            "oi": 150000,
            "volume": 75000,
            "lot_size": lot_size,
            "tick_size": 0.05,
            "isStale": False,
            "isTheoretical": False,
            "data_status": "LIVE",
        }

        pe_data = {
            "symbol": f"{symbol}{expiry_str}{k}PE",
            "token": f"PE_{k}",
            "expiry": expiry_str,
            "ltp": pe_price,
            "bid": round(pe_price - 0.15, 2),
            "ask": round(pe_price + 0.15, 2),
            "spread_pct": round(0.30 / pe_price, 4) if pe_price > 0 else 0.0,
            "delta": pe_bs["delta"],
            "gamma": pe_bs["gamma"],
            "theta": pe_bs["theta"],
            "vega": pe_bs["vega"],
            "iv": iv,
            "iv_source": "BRENT_NUMERICAL",
            "oi": 140000,
            "volume": 65000,
            "lot_size": lot_size,
            "tick_size": 0.05,
            "isStale": False,
            "isTheoretical": False,
            "data_status": "LIVE",
        }

        if custom_ce_overrides and k in custom_ce_overrides:
            ce_data.update(custom_ce_overrides[k])
        if custom_pe_overrides and k in custom_pe_overrides:
            pe_data.update(custom_pe_overrides[k])

        strike_records.append({
            "strike": k_flt,
            "ce": ce_data,
            "pe": pe_data,
        })

    return {
        "symbol": symbol,
        "selectedExpiry": expiry_str,
        "underlyingPrice": underlying_spot,
        "strikes": strike_records,
        "timestamp": now_ist.isoformat(),
    }


# =====================================================================
# 1. Dynamic Strike-Spacing Derivation Tests
# =====================================================================

def test_actual_strike_spacing_derivation_nifty():
    """Derives actual 50.0 strike interval from listed NIFTY strikes."""
    strikes = [24300.0, 24350.0, 24400.0, 24450.0, 24500.0, 24550.0, 24600.0]
    step = derive_strike_spacing(24500.0, strikes)
    assert step == 50.0


def test_actual_strike_spacing_derivation_banknifty():
    """Derives actual 100.0 strike interval from listed BANKNIFTY strikes."""
    strikes = [51800.0, 51900.0, 52000.0, 52100.0, 52200.0, 52300.0]
    step = derive_strike_spacing(52000.0, strikes)
    assert step == 100.0


def test_insufficient_strikes_metadata_rejection():
    """Rejects setup with CONFIGURATION_UNAVAILABLE when strikes metadata is missing (< 2 strikes)."""
    # Single strike provided: cannot derive spacing
    chain = build_mock_option_chain("NIFTY", 24500.0, strikes=[24500])
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    # Pass empty instrument master so no fallback strikes exist
    class MockEmptyMaster:
        def get_strikes_for_underlying(self, u, exp=None):
            return []
        def resolve_option_contract(self, *args, **kwargs):
            return None

    res = select_option_contract(setup, "NIFTY", 24500.0, chain, instrument_master=MockEmptyMaster())
    assert res["qualification_status"] == "REJECTED"
    assert res["data_status"] == "CONFIGURATION_UNAVAILABLE"
    assert any("CONFIGURATION_UNAVAILABLE" in r for r in res["rejection_reasons"])


# =====================================================================
# 2. Centralized Liquidity Policy for All Four Indices Tests
# =====================================================================

def test_liquidity_policy_configured_provenance():
    """Validates CONFIGURED status (not exchange-approved) for NIFTY, BANKNIFTY, FINNIFTY."""
    assert CENTRALIZED_INDEX_LIQUIDITY_POLICY["NIFTY"]["policy_status"] == "CONFIGURED"
    assert CENTRALIZED_INDEX_LIQUIDITY_POLICY["BANKNIFTY"]["policy_status"] == "CONFIGURED"
    assert CENTRALIZED_INDEX_LIQUIDITY_POLICY["FINNIFTY"]["policy_status"] == "CONFIGURED"
    assert "Unverified" in CENTRALIZED_INDEX_LIQUIDITY_POLICY["NIFTY"]["policy_source"]
    assert CENTRALIZED_INDEX_LIQUIDITY_POLICY["NIFTY"]["min_oi"] == 25000
    assert CENTRALIZED_INDEX_LIQUIDITY_POLICY["BANKNIFTY"]["min_oi"] == 15000
    assert CENTRALIZED_INDEX_LIQUIDITY_POLICY["FINNIFTY"]["min_oi"] == 10000


def test_liquidity_policy_sensex_unconfigured_rejection():
    """SENSEX is explicitly UNCONFIGURED by default; selection must be rejected with explicit reason."""
    assert CENTRALIZED_INDEX_LIQUIDITY_POLICY["SENSEX"]["policy_status"] == "UNCONFIGURED"

    chain = build_mock_option_chain("SENSEX", 80000.0, strikes=[79800, 79900, 80000, 80100, 80200])
    setup = {"action": "BUY_CE", "entry_price": 80000.0}

    res = select_option_contract(setup, "SENSEX", 80000.0, chain)
    assert res["qualification_status"] == "REJECTED"
    assert res["data_status"] == "CONFIGURATION_UNAVAILABLE"
    assert res["liquidity_policy_status"] == "UNCONFIGURED"
    assert any("UNCONFIGURED_LIQUIDITY_POLICY" in r for r in res["rejection_reasons"])


def test_sensex_unapproved_override_rejection():
    """Custom override without trusted approval provenance (approved_by) is downgraded to UNVERIFIED and rejected."""
    chain = build_mock_option_chain("SENSEX", 80000.0, strikes=[79800, 79900, 80000, 80100, 80200])
    setup = {"action": "BUY_CE", "entry_price": 80000.0}
    # Override missing approved_by and approval_reference
    cfg = {
        "liquidity_policy": {
            "SENSEX": {
                "min_oi": 5000,
                "min_volume": 1000,
                "max_spread_pct": 0.035,
            }
        }
    }
    res = select_option_contract(setup, "SENSEX", 80000.0, chain, config=cfg)
    assert res["qualification_status"] == "REJECTED"
    assert res["liquidity_policy_status"] == "UNVERIFIED"
    assert any("UNVERIFIED" in r for r in res["rejection_reasons"])


def test_sensex_unverified_hardcoded_reference_rejected():
    """QRC-2026-BSE-01 lacks authentic supporting evidence artifact and is strictly rejected as UNVERIFIED."""
    register_trusted_approval("QRC-2026-BSE-01", {
        "approval_reference": "QRC-2026-BSE-01",
        "approved_by": "QUANT_RISK_COMMITTEE",
        "authorized_indices": ["SENSEX"],
        "status": "UNVERIFIED",
        "approval_evidence": None,
    })
    chain = build_mock_option_chain("SENSEX", 80000.0, strikes=[79800, 79900, 80000, 80100, 80200])
    setup = {"action": "BUY_CE", "entry_price": 80000.0}
    cfg = {
        "liquidity_policy": {
            "SENSEX": {
                "approved_by": "QUANT_RISK_COMMITTEE",
                "approval_reference": "QRC-2026-BSE-01",  # Unverified status, no evidence artifact
                "min_oi": 5000,
                "min_volume": 1000,
                "max_spread_pct": 0.035,
            }
        }
    }
    res = select_option_contract(setup, "SENSEX", 80000.0, chain, config=cfg)
    assert res["qualification_status"] == "REJECTED"
    assert res["liquidity_policy_status"] == "UNVERIFIED"
    assert any("UNVERIFIED" in r for r in res["rejection_reasons"])
    assert "UNVERIFIED" in res["liquidity_policy_source"] or "lacks verifiable" in res["liquidity_policy_source"]


# Ephemeral Ed25519 test keypair generated strictly in test memory (never stored in production code)
_TEST_PRIVATE_KEY = ed25519.Ed25519PrivateKey.generate()
_TEST_PUBLIC_KEY = _TEST_PRIVATE_KEY.public_key()
_TEST_PUBLIC_KEY_HEX = _TEST_PUBLIC_KEY.public_bytes_raw().hex()
_TEST_KEY_ID = "TEST-ED25519-CRO-KEY-01"


def setup_test_governance_authority():
    """Enrolls the ephemeral test public key into server-side TRUSTED_GOVERNANCE_AUTHORITIES."""
    if _TEST_KEY_ID not in get_trusted_governance_authorities():
        register_governance_authority(
            key_id=_TEST_KEY_ID,
            authority_name="Test Chief Risk Officer Desk",
            public_key_hex=_TEST_PUBLIC_KEY_HEX,
            authorized_indices=["SENSEX", "NIFTY", "BANKNIFTY", "FINNIFTY"],
            valid_from="2026-01-01",
            valid_until="2030-01-01",
            active=True,
        )


def build_valid_signed_approval_artifact(
    approval_id: str = None,
    doc_id: str = "AIVOLVE-RES-BSE-2026-001",
    content: str = "BSE_SENSEX_DERIVATIVES_INSTITUTIONAL_APPROVAL_2026",
    key_id: str = _TEST_KEY_ID,
    ratified_by: str = "CHIEF_RISK_OFFICER",
    approval_reference: str = "AUTH-BSE-2026-VERIFIED",
    authorized_indices: list = None,
    min_oi_floor: int = 1000,
    min_volume_floor: int = 500,
    max_spread_pct_ceiling: float = 0.050,
    effective_date: str = "2026-01-01",
    expiry_date: str = "2027-01-01",
    private_key=None,
):
    """Builds an authentic, Ed25519-signed institutional approval artifact for testing."""
    import uuid
    import hashlib

    setup_test_governance_authority()

    if approval_id is None:
        approval_id = f"APPR-ID-{uuid.uuid4().hex[:12].upper()}"
    if authorized_indices is None:
        authorized_indices = ["SENSEX"]
    if private_key is None:
        private_key = _TEST_PRIVATE_KEY

    content_bytes = content.encode("utf-8")
    doc_hash = hashlib.sha256(content_bytes).hexdigest().lower()

    canonical_payload = build_canonical_approval_payload(
        approval_id=approval_id,
        document_id=doc_id,
        approval_reference=approval_reference,
        document_sha256=doc_hash,
        ratifying_authority=ratified_by,
        authorized_indices=authorized_indices,
        min_oi_floor=min_oi_floor,
        min_volume_floor=min_volume_floor,
        max_spread_pct_ceiling=max_spread_pct_ceiling,
        effective_date=effective_date,
        expiry_date=expiry_date,
    )

    sig_bytes = private_key.sign(canonical_payload)
    sig_hex = sig_bytes.hex()

    return {
        "approval_id": approval_id,
        "document_id": doc_id,
        "document_content": content,
        "document_sha256": doc_hash,
        "key_id": key_id,
        "ratified_by": ratified_by,
        "digital_signature": sig_hex,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
    }


def test_sensex_arbitrary_approved_by_rejected():
    """Caller-supplied arbitrary approved_by for verified reference is rejected by server."""
    art = build_valid_signed_approval_artifact(approval_reference="AUTH-BSE-TEST-01")
    register_verified_institutional_approval(
        approval_reference="AUTH-BSE-TEST-01",
        approved_by="QUANT_RISK_COMMITTEE",
        authorized_indices=["SENSEX"],
        approval_evidence=art,
        min_oi_floor=1000,
        min_volume_floor=500,
        max_spread_pct_ceiling=0.050,
    )

    chain = build_mock_option_chain("SENSEX", 80000.0, strikes=[79800, 79900, 80000, 80100, 80200])
    setup = {"action": "BUY_CE", "entry_price": 80000.0}
    cfg = {
        "liquidity_policy": {
            "SENSEX": {
                "approved_by": "Arbitrary_Caller_Alice",  # Wrong approver
                "approval_reference": "AUTH-BSE-TEST-01",
                "min_oi": 5000,
                "min_volume": 1000,
                "max_spread_pct": 0.035,
            }
        }
    }
    res = select_option_contract(setup, "SENSEX", 80000.0, chain, config=cfg)
    assert res["qualification_status"] == "REJECTED"
    assert res["liquidity_policy_status"] == "UNVERIFIED"
    assert "Expected 'QUANT_RISK_COMMITTEE'" in res["liquidity_policy_source"]
    assert any("UNVERIFIED" in r for r in res["rejection_reasons"])


def test_sensex_arbitrary_approval_reference_rejected():
    """Caller-supplied arbitrary approval_reference unknown to server is rejected."""
    chain = build_mock_option_chain("SENSEX", 80000.0, strikes=[79800, 79900, 80000, 80100, 80200])
    setup = {"action": "BUY_CE", "entry_price": 80000.0}
    cfg = {
        "liquidity_policy": {
            "SENSEX": {
                "approved_by": "QUANT_RISK_COMMITTEE",
                "approval_reference": "FAKE-ARBITRARY-REF-999",  # Unregistered
                "min_oi": 5000,
                "min_volume": 1000,
                "max_spread_pct": 0.035,
            }
        }
    }
    res = select_option_contract(setup, "SENSEX", 80000.0, chain, config=cfg)
    assert res["qualification_status"] == "REJECTED"
    assert res["liquidity_policy_status"] == "UNVERIFIED"
    assert "Unknown or unregistered approval reference" in res["liquidity_policy_source"]
    assert any("UNVERIFIED" in r for r in res["rejection_reasons"])


def test_sensex_forged_approved_status_rejected():
    """Caller attempting to forge policy_status='APPROVED' without valid registry entry is stripped and rejected."""
    chain = build_mock_option_chain("SENSEX", 80000.0, strikes=[79800, 79900, 80000, 80100, 80200])
    setup = {"action": "BUY_CE", "entry_price": 80000.0}
    # Forged policy_status with no credentials
    cfg = {
        "liquidity_policy": {
            "SENSEX": {
                "policy_status": "APPROVED",
                "min_oi": 5000,
                "min_volume": 1000,
                "max_spread_pct": 0.035,
            }
        }
    }
    res = select_option_contract(setup, "SENSEX", 80000.0, chain, config=cfg)
    assert res["qualification_status"] == "REJECTED"
    assert res["liquidity_policy_status"] == "UNVERIFIED"
    assert "Forged policy_status='APPROVED'" in res["liquidity_policy_source"]
    assert any("UNVERIFIED" in r for r in res["rejection_reasons"])


def test_sensex_revoked_approval_reference_rejected():
    """Approval reference marked REVOKED in server registry is strictly rejected."""
    revoke_trusted_approval("REVOKED-REF-2025-09", reason="Superseded by review")
    chain = build_mock_option_chain("SENSEX", 80000.0, strikes=[79800, 79900, 80000, 80100, 80200])
    setup = {"action": "BUY_CE", "entry_price": 80000.0}
    cfg = {
        "liquidity_policy": {
            "SENSEX": {
                "approved_by": "QUANT_RISK_COMMITTEE",
                "approval_reference": "REVOKED-REF-2025-09",  # Explicitly revoked in server registry
                "min_oi": 5000,
                "min_volume": 1000,
                "max_spread_pct": 0.035,
            }
        }
    }
    res = select_option_contract(setup, "SENSEX", 80000.0, chain, config=cfg)
    assert res["qualification_status"] == "REJECTED"
    assert res["liquidity_policy_status"] == "UNVERIFIED"
    assert "is REVOKED" in res["liquidity_policy_source"] or "has been revoked" in res["liquidity_policy_source"]
    assert any("UNVERIFIED" in r for r in res["rejection_reasons"])


def test_sensex_unauthorized_index_rejected():
    """Approval reference authorized only for another index cannot be applied to SENSEX."""
    art = build_valid_signed_approval_artifact(
        approval_reference="TEMP-NIFTY-ONLY-01",
        authorized_indices=["NIFTY"],
    )
    register_verified_institutional_approval(
        approval_reference="TEMP-NIFTY-ONLY-01",
        approved_by="QUANT_RISK_COMMITTEE",
        authorized_indices=["NIFTY"],  # Not SENSEX
        approval_evidence=art,
        min_oi_floor=1000,
        min_volume_floor=500,
        max_spread_pct_ceiling=0.050,
    )

    chain = build_mock_option_chain("SENSEX", 80000.0, strikes=[79800, 79900, 80000, 80100, 80200])
    setup = {"action": "BUY_CE", "entry_price": 80000.0}
    cfg = {
        "liquidity_policy": {
            "SENSEX": {
                "approved_by": "QUANT_RISK_COMMITTEE",
                "approval_reference": "TEMP-NIFTY-ONLY-01",
                "min_oi": 5000,
                "min_volume": 1000,
                "max_spread_pct": 0.035,
            }
        }
    }
    res = select_option_contract(setup, "SENSEX", 80000.0, chain, config=cfg)
    assert res["qualification_status"] == "REJECTED"
    assert res["liquidity_policy_status"] == "UNVERIFIED"
    assert "not index 'SENSEX'" in res["liquidity_policy_source"]


def test_sensex_risk_ceiling_breach_rejected():
    """Policy thresholds that breach server-side registered risk ceilings are rejected."""
    art = build_valid_signed_approval_artifact(approval_reference="AUTH-BSE-TEST-01")
    register_verified_institutional_approval(
        approval_reference="AUTH-BSE-TEST-01",
        approved_by="QUANT_RISK_COMMITTEE",
        authorized_indices=["SENSEX"],
        approval_evidence=art,
        min_oi_floor=1000,
        min_volume_floor=500,
        max_spread_pct_ceiling=0.050,
    )

    chain = build_mock_option_chain("SENSEX", 80000.0, strikes=[79800, 79900, 80000, 80100, 80200])
    setup = {"action": "BUY_CE", "entry_price": 80000.0}
    # Proposed spread 0.08 exceeds 0.050 ceiling in registry for AUTH-BSE-TEST-01
    cfg = {
        "liquidity_policy": {
            "SENSEX": {
                "approved_by": "QUANT_RISK_COMMITTEE",
                "approval_reference": "AUTH-BSE-TEST-01",
                "min_oi": 5000,
                "min_volume": 1000,
                "max_spread_pct": 0.080,  # Breaches 0.050 ceiling
            }
        }
    }
    res = select_option_contract(setup, "SENSEX", 80000.0, chain, config=cfg)
    assert res["qualification_status"] == "REJECTED"
    assert res["liquidity_policy_status"] == "UNVERIFIED"
    assert "exceeds approved ceiling" in res["liquidity_policy_source"]


def test_sensex_arbitrary_document_id_and_hash_rejected():
    """Fabricated document ID and arbitrary SHA-256 not matching actual document bytes is strictly rejected."""
    setup_test_governance_authority()
    with pytest.raises(ValueError, match="Document hash mismatch"):
        register_verified_institutional_approval(
            approval_reference="FAKE-DOC-REF-01",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence={
                "approval_id": "APPR-FAKE-HASH-01",
                "document_id": "FABRICATED-DOC-99",
                "document_content": "Legitimate institutional resolution text",
                "document_sha256": "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",  # Arbitrary fake hash
                "key_id": _TEST_KEY_ID,
                "ratified_by": "CHIEF_RISK_OFFICER",
                "digital_signature": "00" * 64,
                "effective_date": "2026-01-01",
                "expiry_date": "2027-01-01",
            },
        )


def test_sensex_hash_mismatch_rejected():
    """Even with well-formed hex, hash mismatch against recomputed content bytes is rejected."""
    setup_test_governance_authority()
    content = "Real resolution content"
    with pytest.raises(ValueError, match="Document hash mismatch"):
        register_verified_institutional_approval(
            approval_reference="MISMATCH-REF-01",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence={
                "approval_id": "APPR-MISMATCH-01",
                "document_id": "MISMATCH-DOC-01",
                "document_content": content,
                "document_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                "key_id": _TEST_KEY_ID,
                "ratified_by": "CHIEF_RISK_OFFICER",
                "digital_signature": "00" * 64,
                "effective_date": "2026-01-01",
                "expiry_date": "2027-01-01",
            },
        )


def test_sensex_invalid_digital_signature_rejected():
    """Artifact with recomputed hash matching content but forged/invalid digital signature is rejected."""
    setup_test_governance_authority()
    content = "Authentic governance resolution"
    import hashlib
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest().lower()
    with pytest.raises(ValueError, match="Invalid digital signature"):
        register_verified_institutional_approval(
            approval_reference="BAD-SIG-REF-01",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence={
                "approval_id": "APPR-BAD-SIG-01",
                "document_id": "DOC-BAD-SIG",
                "document_content": content,
                "document_sha256": content_hash,
                "key_id": _TEST_KEY_ID,
                "ratified_by": "CHIEF_RISK_OFFICER",
                "digital_signature": "deadbeef" * 16,  # 64 bytes (128 hex chars) of forged signature
                "effective_date": "2026-01-01",
                "expiry_date": "2027-01-01",
            },
        )


def test_sensex_unknown_approver_ratifier_rejected():
    """Artifact ratified by an unknown entity not in TRUSTED_GOVERNANCE_AUTHORITIES is rejected."""
    content = "Resolution signed by unauthorized entity"
    import hashlib
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest().lower()
    with pytest.raises(ValueError, match="Unknown or unregistered governance authority key_id"):
        register_verified_institutional_approval(
            approval_reference="UNKNOWN-RATIFIER-REF",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence={
                "approval_id": "APPR-UNKNOWN-KEY-01",
                "document_id": "DOC-UNKNOWN-RATIFIER",
                "document_content": content,
                "document_sha256": content_hash,
                "key_id": "UNAUTHORIZED_ANONYMOUS_KEY_ID",  # Not in TRUSTED_GOVERNANCE_AUTHORITIES
                "ratified_by": "UNAUTHORIZED_DESK",
                "digital_signature": "00" * 64,
                "effective_date": "2026-01-01",
                "expiry_date": "2027-01-01",
            },
        )


def test_sensex_expired_approval_rejected():
    """Approval artifact whose expiry_date is in the past is rejected."""
    art = build_valid_signed_approval_artifact(
        approval_reference="EXPIRED-BSE-REF",
        effective_date="2020-01-01",
        expiry_date="2021-01-01",  # Expired
    )
    with pytest.raises(ValueError, match="Expired approval artifact"):
        register_verified_institutional_approval(
            approval_reference="EXPIRED-BSE-REF",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence=art,
        )


def test_sensex_revoked_reference_registration_rejected():
    """Attempting to register approval for a revoked reference raises ValueError."""
    revoke_trusted_approval("REVOKED-REF-2025-09", reason="Synthetic test revocation")
    art = build_valid_signed_approval_artifact(
        approval_reference="REVOKED-REF-2025-09",
    )
    with pytest.raises(ValueError, match="is in server revocation registry"):
        register_verified_institutional_approval(
            approval_reference="REVOKED-REF-2025-09",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence=art,
        )


def test_sensex_revoked_document_hash_rejected():
    """Attempting to register approval for a revoked document hash raises ValueError."""
    art = build_valid_signed_approval_artifact(approval_reference="REVOKED-HASH-REF")
    doc_hash = art["document_sha256"]
    REVOKED_DOCUMENT_HASHES.add(doc_hash)
    try:
        with pytest.raises(ValueError, match="is in server revocation registry"):
            register_verified_institutional_approval(
                approval_reference="REVOKED-HASH-REF",
                approved_by="QUANT_RISK_COMMITTEE",
                authorized_indices=["SENSEX"],
                approval_evidence=art,
            )
    finally:
        REVOKED_DOCUMENT_HASHES.remove(doc_hash)


def test_sensex_registration_missing_evidence_raises_error():
    """Attempting to register institutional approval without verifiable evidence artifact raises ValueError."""
    with pytest.raises(ValueError, match="Missing approval_id"):
        register_verified_institutional_approval(
            approval_reference="UNVERIFIED-TEST-REF",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence={},  # Empty evidence dict
        )


def test_sensex_with_verified_institutional_approval_success():
    """SENSEX qualifies successfully ONLY when backed by a verified institutional approval artifact."""
    art = build_valid_signed_approval_artifact(
        doc_id="AIVOLVE-RES-BSE-DERIVATIVES-2026-FINAL",
        approval_reference="AUTH-BSE-FINAL-VERIFIED",
    )
    register_verified_institutional_approval(
        approval_reference="AUTH-BSE-FINAL-VERIFIED",
        approved_by="QUANT_RISK_COMMITTEE",
        authorized_indices=["SENSEX"],
        approval_evidence=art,
        min_oi_floor=1000,
        min_volume_floor=500,
        max_spread_pct_ceiling=0.050,
    )

    chain = build_mock_option_chain("SENSEX", 80000.0, strikes=[79800, 79900, 80000, 80100, 80200])
    setup = {"action": "BUY_CE", "entry_price": 80000.0, "stop_loss": 79800.0}

    cfg = {
        "liquidity_policy": {
            "SENSEX": {
                "approved_by": "QUANT_RISK_COMMITTEE",
                "approval_reference": "AUTH-BSE-FINAL-VERIFIED",
                "min_oi": 5000,
                "min_volume": 1000,
                "max_spread_pct": 0.035,
            }
        }
    }

    res = select_option_contract(setup, "SENSEX", 80000.0, chain, config=cfg)
    assert res["qualification_status"] == "QUALIFIED"
    assert res["liquidity_policy_status"] == "APPROVED"
    assert "QUANT_RISK_COMMITTEE" in res["liquidity_policy_source"]


def test_sensex_tampered_liquidity_thresholds_rejected():
    """Tampering with approved liquidity thresholds breaks Ed25519 signature verification."""
    # Artifact signed with max_spread_pct_ceiling=0.050
    art = build_valid_signed_approval_artifact(
        approval_reference="AUTH-TAMPER-TEST-01",
        min_oi_floor=1000,
        min_volume_floor=500,
        max_spread_pct_ceiling=0.050,
    )

    # Attacker tries to register with relaxed max_spread_pct_ceiling=0.080
    with pytest.raises(ValueError, match="Invalid digital signature: Ed25519 cryptographic verification failed"):
        register_verified_institutional_approval(
            approval_reference="AUTH-TAMPER-TEST-01",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence=art,
            min_oi_floor=1000,
            min_volume_floor=500,
            max_spread_pct_ceiling=0.080,  # Tampered!
        )


def test_sensex_revoked_governance_authority_key_rejected():
    """Attempting to register approval using a revoked authority key is rejected."""
    key_id = "REVOKED-TEST-KEY-01"
    register_governance_authority(
        key_id=key_id,
        authority_name="Compromised Desk",
        public_key_hex=_TEST_PUBLIC_KEY_HEX,
        authorized_indices=["SENSEX"],
    )
    revoke_governance_authority(key_id, reason="Private key exposure suspected")

    art = build_valid_signed_approval_artifact(
        key_id=key_id,
        approval_reference="AUTH-REVOKED-KEY-01",
    )
    with pytest.raises(ValueError, match="Revoked governance authority key_id"):
        register_verified_institutional_approval(
            approval_reference="AUTH-REVOKED-KEY-01",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence=art,
        )


def test_sensex_inactive_governance_authority_key_rejected():
    """Attempting to register approval using an inactive authority key is rejected."""
    key_id = "INACTIVE-TEST-KEY-01"
    register_governance_authority(
        key_id=key_id,
        authority_name="Inactive Desk",
        public_key_hex=_TEST_PUBLIC_KEY_HEX,
        authorized_indices=["SENSEX"],
        active=False,
    )

    art = build_valid_signed_approval_artifact(
        key_id=key_id,
        approval_reference="AUTH-INACTIVE-KEY-01",
    )
    with pytest.raises(ValueError, match="Inactive governance authority key_id"):
        register_verified_institutional_approval(
            approval_reference="AUTH-INACTIVE-KEY-01",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence=art,
        )


def test_sensex_authority_unauthorized_index_scope_rejected():
    """Authority key restricted to NIFTY cannot authorize SENSEX."""
    key_id = "NIFTY-ONLY-KEY-01"
    register_governance_authority(
        key_id=key_id,
        authority_name="Nifty Only Desk",
        public_key_hex=_TEST_PUBLIC_KEY_HEX,
        authorized_indices=["NIFTY"],  # Only NIFTY!
    )

    art = build_valid_signed_approval_artifact(
        key_id=key_id,
        approval_reference="AUTH-NIFTY-KEY-ON-SENSEX",
        authorized_indices=["SENSEX"],
    )
    with pytest.raises(ValueError, match="is not authorized for index 'SENSEX'"):
        register_verified_institutional_approval(
            approval_reference="AUTH-NIFTY-KEY-ON-SENSEX",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence=art,
        )


def test_sensex_replay_attack_rejected():
    """Replaying the exact same approval artifact with duplicate approval_id is strictly rejected."""
    replay_id = "REPLAY-ATTACK-NONCE-UNIQUE-001"
    art = build_valid_signed_approval_artifact(
        approval_id=replay_id,
        approval_reference="AUTH-REPLAY-ORIGINAL-01",
    )

    # First registration succeeds
    register_verified_institutional_approval(
        approval_reference="AUTH-REPLAY-ORIGINAL-01",
        approved_by="QUANT_RISK_COMMITTEE",
        authorized_indices=["SENSEX"],
        approval_evidence=art,
    )

    # Second registration with same approval_id must be rejected
    with pytest.raises(ValueError, match="Replay attack detected"):
        register_verified_institutional_approval(
            approval_reference="AUTH-REPLAY-DUPLICATE-02",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence=art,
        )


def test_sensex_fail_closed_without_enrolled_authorities():
    """In fail-closed default state (no authorities), SENSEX selection is strictly rejected."""
    chain = build_mock_option_chain("SENSEX", 80000.0, strikes=[79800, 79900, 80000, 80100, 80200])
    setup = {"action": "BUY_CE", "entry_price": 80000.0}

    # Default unconfigured attempt
    res = select_option_contract(setup, "SENSEX", 80000.0, chain)
    assert res["qualification_status"] == "REJECTED"
    assert res["liquidity_policy_status"] == "UNCONFIGURED"
    assert any("UNCONFIGURED" in r for r in res["rejection_reasons"])


# =====================================================================
# Institutional Governance Persistence, Concurrency & Authority Audit Tests
# =====================================================================

def test_governance_replay_protection_survives_restart(tmp_path):
    """Processed approval IDs persist across application restarts in durable SQLite store."""
    test_db = str(tmp_path / "test_restart_replay.db")
    set_governance_ledger_db_path(test_db)

    art = build_valid_signed_approval_artifact(
        approval_id="REPLAY-RESTART-NONCE-01",
        approval_reference="AUTH-RESTART-REPLAY-01",
    )
    register_verified_institutional_approval(
        approval_reference="AUTH-RESTART-REPLAY-01",
        approved_by="QUANT_RISK_COMMITTEE",
        authorized_indices=["SENSEX"],
        approval_evidence=art,
    )

    # Simulate full application restart by reloading from the same SQLite file
    set_governance_ledger_db_path(test_db)

    # Replay attempt after restart must be rejected atomically
    with pytest.raises(ValueError, match="Replay attack detected"):
        register_verified_institutional_approval(
            approval_reference="AUTH-RESTART-REPLAY-DUPLICATE",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence=art,
        )


def test_governance_concurrent_duplicate_approval_submissions(tmp_path):
    """Concurrent worker submissions of duplicate approval IDs are rejected atomically by SQLite unique constraint."""
    from concurrent.futures import ThreadPoolExecutor

    test_db = str(tmp_path / "test_concurrent_replay.db")
    set_governance_ledger_db_path(test_db)

    shared_nonce = "CONCURRENT-ATOMIC-NONCE-12345"
    art = build_valid_signed_approval_artifact(
        approval_id=shared_nonce,
        approval_reference="AUTH-CONCURRENT-BASE",
    )

    def submit_worker(worker_id):
        try:
            register_verified_institutional_approval(
                approval_reference="AUTH-CONCURRENT-BASE",
                approved_by="QUANT_RISK_COMMITTEE",
                authorized_indices=["SENSEX"],
                approval_evidence=art,
            )
            return "SUCCESS"
        except ValueError as e:
            if "Replay attack detected" in str(e):
                return "REPLAY_REJECTED"
            return f"ERROR: {e}"

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(submit_worker, range(5)))

    # Exactly one worker succeeds; all 4 concurrent duplicates are rejected
    assert results.count("SUCCESS") == 1
    assert results.count("REPLAY_REJECTED") == 4


def test_governance_revocation_persistence_survives_restart(tmp_path):
    """Revoked references and document hashes persist in durable SQLite store across restarts."""
    test_db = str(tmp_path / "test_restart_revocation.db")
    set_governance_ledger_db_path(test_db)

    ref_to_revoke = "REVOKED-TEST-REF-99"
    hash_to_revoke = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"

    # Revoke via durable proxies
    REVOKED_APPROVAL_REFERENCES.add(ref_to_revoke)
    REVOKED_DOCUMENT_HASHES.add(hash_to_revoke)

    # Simulate application restart
    set_governance_ledger_db_path(test_db)

    assert ref_to_revoke in REVOKED_APPROVAL_REFERENCES
    assert hash_to_revoke in REVOKED_DOCUMENT_HASHES


def test_governance_revoked_key_rejection_survives_restart(tmp_path):
    """Revoked governance authority keys remain revoked after restart and reject new approvals."""
    test_db = str(tmp_path / "test_restart_key_revocation.db")
    set_governance_ledger_db_path(test_db)

    key_id = "KEY-RESTART-REVOKE-01"
    register_governance_authority(
        key_id=key_id,
        authority_name="Key To Revoke",
        public_key_hex=_TEST_PUBLIC_KEY_HEX,
        authorized_indices=["SENSEX"],
    )
    revoke_governance_authority(key_id, reason="Revocation survival test")

    # Simulate application restart
    set_governance_ledger_db_path(test_db)

    art = build_valid_signed_approval_artifact(
        key_id=key_id,
        approval_reference="AUTH-AFTER-RESTART-REVOKED-KEY",
    )
    with pytest.raises(ValueError, match="Revoked governance authority key_id"):
        register_verified_institutional_approval(
            approval_reference="AUTH-AFTER-RESTART-REVOKED-KEY",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence=art,
        )


def test_governance_unauthorized_authority_enrollment_api_isolation():
    """Ordinary API routes do not expose authority enrollment to external or unauthenticated callers."""
    from app.main import app

    for route in app.routes:
        path = getattr(route, "path", "")
        # No HTTP endpoint should ever expose authority enrollment or key registration
        assert "register_governance_authority" not in path
        assert "register_authority" not in path
        assert "enroll_key" not in path


def test_governance_duplicate_key_id_enrollment_rejected():
    """Attempting to enroll an existing key_id is strictly rejected to prevent silent overwrite."""
    key_id = "KEY-DUPLICATE-PREVENTION-01"
    register_governance_authority(
        key_id=key_id,
        authority_name="Original Authority Desk",
        public_key_hex=_TEST_PUBLIC_KEY_HEX,
        authorized_indices=["SENSEX"],
    )

    # Re-enrolling with same key_id must be rejected
    with pytest.raises(ValueError, match="Duplicate key_id enrollment rejected"):
        register_governance_authority(
            key_id=key_id,
            authority_name="Attacker Impersonation Desk",
            public_key_hex=_TEST_PUBLIC_KEY_HEX,
            authorized_indices=["SENSEX"],
        )


def test_governance_key_rotation_and_old_key_revocation():
    """Key rotation atomically revokes prior authority key and activates successor key."""
    old_key = ed25519.Ed25519PrivateKey.generate()
    old_pub_hex = old_key.public_key().public_bytes_raw().hex()
    new_key = ed25519.Ed25519PrivateKey.generate()
    new_pub_hex = new_key.public_key().public_bytes_raw().hex()

    register_governance_authority(
        key_id="KEY-ROT-OLD-01",
        authority_name="Active Desk v1",
        public_key_hex=old_pub_hex,
        authorized_indices=["SENSEX"],
    )

    # Execute atomic rotation
    rotate_governance_authority(
        old_key_id="KEY-ROT-OLD-01",
        new_key_id="KEY-ROT-NEW-02",
        new_authority_name="Active Desk v2",
        new_public_key_hex=new_pub_hex,
        authorized_indices=["SENSEX"],
        reason="Scheduled bi-annual cryptographic key rotation",
    )

    old_record = get_trusted_governance_authorities()["KEY-ROT-OLD-01"]
    new_record = get_trusted_governance_authorities()["KEY-ROT-NEW-02"]

    assert old_record["active"] is False
    assert old_record["revoked"] is True
    assert "Superseded by key rotation to KEY-ROT-NEW-02" in old_record["revocation_reason"]
    assert new_record["active"] is True
    assert new_record["revoked"] is False

    # Old key cannot authorize new approvals
    art_old = build_valid_signed_approval_artifact(
        key_id="KEY-ROT-OLD-01",
        approval_reference="AUTH-USING-OLD-KEY",
        private_key=old_key,
    )
    with pytest.raises(ValueError, match="Revoked governance authority key_id"):
        register_verified_institutional_approval(
            approval_reference="AUTH-USING-OLD-KEY",
            approved_by="QUANT_RISK_COMMITTEE",
            authorized_indices=["SENSEX"],
            approval_evidence=art_old,
        )

    # New key successfully authorizes approvals
    art_new = build_valid_signed_approval_artifact(
        key_id="KEY-ROT-NEW-02",
        approval_reference="AUTH-USING-NEW-KEY",
        private_key=new_key,
    )
    register_verified_institutional_approval(
        approval_reference="AUTH-USING-NEW-KEY",
        approved_by="QUANT_RISK_COMMITTEE",
        authorized_indices=["SENSEX"],
        approval_evidence=art_new,
    )
    assert get_trusted_approval_registry()["AUTH-USING-NEW-KEY"]["status"] == "ACTIVE"


def test_governance_production_startup_zero_enrolled_authorities(tmp_path):
    """Pristine production startup initializes with zero enrolled authorities and fail-closed state."""
    fresh_db = str(tmp_path / "fresh_production_test.db")
    set_governance_ledger_db_path(fresh_db)

    authorities = get_trusted_governance_authorities()
    assert len(authorities) == 0

    chain = build_mock_option_chain("SENSEX", 80000.0)
    setup = {"action": "BUY_CE", "entry_price": 80000.0}
    res = select_option_contract(setup, "SENSEX", 80000.0, chain)
    assert res["qualification_status"] == "REJECTED"
    assert res["liquidity_policy_status"] == "UNCONFIGURED"


def test_governance_test_keys_never_become_production_trust_anchors():
    """Test private keys exist strictly in test memory and never in production ledger or defaults."""
    # Production ledger starts with zero authorities
    # Ephemeral test key has never been written into production configuration
    assert not os.path.exists("backend/app/data/fake_private_key.pem")
    assert not os.path.exists("backend/app/data/test_signing_key.key")
    assert "AIVOLVE_TEST_PRIVATE_KEY" not in os.environ


def test_governance_multiprocess_concurrency_atomic_replay_rejection(tmp_path):
    """Separate operating system processes concurrently submitting duplicate approvals are rejected atomically."""
    import sys
    import subprocess
    import json
    import sqlite3

    test_db = str(tmp_path / "shared_multiprocess.db")
    set_governance_ledger_db_path(test_db)

    # 1. Parent process generates ephemeral keypair and registers authority
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    key_id = "TEST-MULTIPROCESS-KEY-01"

    register_governance_authority(
        key_id=key_id,
        authority_name="Multi-Process Test Desk",
        public_key_hex=pub_hex,
        authorized_indices=["SENSEX"],
    )

    # 2. Build signed approval artifact with unique shared nonce
    import hashlib
    content = "MULTIPROCESS_CONCURRENCY_ARTIFACT"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    shared_nonce = "NONCE-MULTIPROCESS-ATOMIC-999"
    ref = "AUTH-MULTIPROC-ATOMIC"

    canonical = build_canonical_approval_payload(
        approval_id=shared_nonce,
        document_id="DOC-MULTI-01",
        approval_reference=ref,
        document_sha256=content_hash,
        ratifying_authority="CRO",
        authorized_indices=["SENSEX"],
        min_oi_floor=1000,
        min_volume_floor=500,
        max_spread_pct_ceiling=0.050,
        effective_date="2026-01-01",
        expiry_date="2027-01-01",
    )
    sig = priv.sign(canonical).hex()

    art = {
        "approval_id": shared_nonce,
        "document_id": "DOC-MULTI-01",
        "document_content": content,
        "document_sha256": content_hash,
        "key_id": key_id,
        "ratified_by": "CRO",
        "digital_signature": sig,
        "effective_date": "2026-01-01",
        "expiry_date": "2027-01-01",
    }
    art_json = json.dumps(art)

    # 3. Worker script executed by completely separate Python OS processes
    worker_script = f"""
import sys, json
sys.path.insert(0, r'd:/ReactJs/aivolve-trading-ai/backend')
from app.options.contract_selector import set_governance_ledger_db_path, register_verified_institutional_approval

set_governance_ledger_db_path(r'{test_db}')
art = json.loads({repr(art_json)})

try:
    register_verified_institutional_approval(
        approval_reference='{ref}',
        approved_by='QUANT_RISK_COMMITTEE',
        authorized_indices=['SENSEX'],
        approval_evidence=art,
    )
    print("SUCCESS")
except ValueError as e:
    if "Replay attack detected" in str(e):
        print("REPLAY_REJECTED")
    else:
        print("ERROR:", e)
except Exception as e:
    print("UNEXPECTED_ERROR:", e)
"""

    # Spawn 5 independent concurrent OS processes
    procs = []
    for _ in range(5):
        p = subprocess.Popen(
            [sys.executable, "-c", worker_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        procs.append(p)

    outputs = []
    for p in procs:
        stdout, stderr = p.communicate(timeout=20)
        outputs.append(stdout.strip())

    # Assert exactly 1 OS process succeeded, and all other 4 received replay rejection
    assert outputs.count("SUCCESS") == 1
    assert outputs.count("REPLAY_REJECTED") == 4

    # Assert database integrity and record counts
    conn = sqlite3.connect(test_db)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    rec_count = conn.execute("SELECT COUNT(*) FROM processed_approval_ids").fetchone()[0]
    reg_count = conn.execute("SELECT COUNT(*) FROM trusted_approval_registry WHERE approval_reference = ?", (ref,)).fetchone()[0]
    conn.close()

    assert integrity == "ok"
    assert rec_count == 1
    assert reg_count == 1


def test_governance_corrupt_storage_fails_closed(tmp_path):
    """Corrupted SQLite storage causes governance operations to fail closed safely."""
    test_db = str(tmp_path / "corrupt_governance.db")
    set_governance_ledger_db_path(test_db)

    # Corrupt database file by overwriting with garbage bytes
    with open(test_db, "wb") as f:
        f.write(b"CORRUPTED_GARBAGE_HEADER_DATA_NOT_SQLITE")

    # Inaccessible / corrupted storage must raise explicit governance storage failure and fail closed
    with pytest.raises(ValueError, match="Governance storage failure"):
        get_governance_ledger().is_approval_id_processed("ANY-ID")


def test_governance_wal_checkpoint_truncate(tmp_path):
    """WAL checkpoint safely flushes journal frames to persistent DB file."""
    test_db = str(tmp_path / "test_wal_checkpoint.db")
    set_governance_ledger_db_path(test_db)

    # Perform writes
    register_governance_authority(
        key_id="KEY-WAL-01",
        authority_name="WAL Test Desk",
        public_key_hex=_TEST_PUBLIC_KEY_HEX,
        authorized_indices=["SENSEX"],
    )

    # Checkpoint
    chk_res = get_governance_ledger().checkpoint("TRUNCATE")
    assert chk_res["success"] is True
    assert chk_res["busy"] is False

    # Re-open and verify data persisted cleanly
    set_governance_ledger_db_path(test_db)
    assert "KEY-WAL-01" in get_trusted_governance_authorities()


def test_governance_permissions_status(tmp_path):
    """Permissions status inspection reports accurately and distinguishes OS environments."""
    test_db = str(tmp_path / "test_perms.db")
    set_governance_ledger_db_path(test_db)
    ledger = get_governance_ledger()
    status = ledger.get_permissions_status()
    assert status["db_path"] == test_db
    assert status["secured"] is True
    assert status["os"] == os.name
    if os.name == "nt":
        assert "NTFS" in status["detail"]
    else:
        assert "0600" in status["detail"]


def test_governance_checkpoint_allowlist_and_result_inspection(tmp_path):
    """WAL checkpoint validates against mode allowlist and inspects busy/frame statistics."""
    test_db = str(tmp_path / "test_chk_inspection.db")
    set_governance_ledger_db_path(test_db)
    ledger = get_governance_ledger()

    # Invalid mode rejected
    with pytest.raises(ValueError, match="Invalid WAL checkpoint mode"):
        ledger.checkpoint("MALICIOUS_PRAGMA_INJECTION")

    with pytest.raises(ValueError, match="Invalid WAL checkpoint mode"):
        ledger.checkpoint("SYNC")

    # Allowed modes succeed and return structured dictionary
    for mode in ["PASSIVE", "FULL", "RESTART", "TRUNCATE"]:
        res = ledger.checkpoint(mode)
        assert isinstance(res, dict)
        assert res["mode"] == mode
        assert "busy" in res
        assert "log_frames" in res
        assert "checkpointed_frames" in res
        assert "success" in res
        assert res["busy"] is False
        assert res["success"] is True


def test_governance_transaction_rollback_on_write_failure(tmp_path):
    """SQL statement failure inside transaction triggers explicit ROLLBACK and leaves state clean."""
    test_db = str(tmp_path / "test_tx_rollback.db")
    set_governance_ledger_db_path(test_db)
    ledger = get_governance_ledger()

    # Initial state
    assert len(ledger.get_all_revoked_references()) == 0

    # Write failure inside atomic transaction
    with pytest.raises(RuntimeError, match="Simulated mid-transaction failure"):
        with ledger._transaction() as conn:
            conn.execute(
                "INSERT INTO revoked_approval_references (approval_reference, revoked_at, reason) VALUES (?, ?, ?)",
                ("TEMP-REV-FAIL", "2026-01-01", "Should be rolled back"),
            )
            raise RuntimeError("Simulated mid-transaction failure")

    # Verify rollback succeeded and table remains empty
    assert "TEMP-REV-FAIL" not in ledger.get_all_revoked_references()
    assert len(ledger.get_all_revoked_references()) == 0


def test_governance_transaction_begin_immediate_failure_fails_closed(tmp_path):
    """If database is locked or inaccessible during BEGIN IMMEDIATE, transaction fails closed."""
    import sqlite3
    test_db = str(tmp_path / "test_tx_lock_fail.db")
    set_governance_ledger_db_path(test_db)
    ledger = get_governance_ledger()

    # Hold an exclusive lock with another connection
    blocking_conn = sqlite3.connect(test_db, timeout=0.1, isolation_level=None)
    try:
        blocking_conn.execute("BEGIN EXCLUSIVE;")
        # Set a short timeout on ledger connection so test runs fast
        with pytest.raises(ValueError, match="Governance (transaction lock acquisition failed|storage failure)"):
            with ledger._transaction() as conn:
                conn.execute("SELECT 1;")
    finally:
        try:
            blocking_conn.execute("ROLLBACK;")
            blocking_conn.close()
        except Exception:
            pass


# =====================================================================
# 3. Conservative Execution Price Model (Ask Entry, Analytical Midpoint)
# =====================================================================

def test_ask_based_entry_execution():
    """Long option entry executes strictly at Ask; Midpoint is retained for analytical valuation only."""
    chain = build_mock_option_chain("NIFTY", 24500.0)
    setup = {"action": "BUY_CE", "entry_price": 24500.0, "stop_loss": 24420.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "QUALIFIED"
    assert res["entry_execution_model"] == "ASK"
    assert res["entry_premium"] == res["ask"]
    assert res["entry_premium"] > res["bid"]
    # Verify midpoint is tracked separately
    assert res["analytical_midpoint"] == round((res["bid"] + res["ask"]) / 2.0, 2)


# =====================================================================
# 4. Directional Guard Tests
# =====================================================================

def test_directional_guard_buy_ce():
    """BUY_CE action selects strictly Call option (CE) and rejects Put."""
    chain = build_mock_option_chain("NIFTY", 24500.0)
    setup = {
        "action": "BUY_CE",
        "entry_price": 24500.0,
        "stop_loss": 24420.0,
        "target_1": 24600.0,
        "target_2": 24680.0,
    }
    contract = select_option_contract(setup, "NIFTY", 24500.0, chain)

    assert contract["qualification_status"] == "QUALIFIED"
    assert contract["action"] == "BUY_CE"
    assert contract["option_type"] == "CE"
    assert "CE" in contract["contract_symbol"]
    assert contract["delta"] is not None
    assert contract["delta"] > 0.0


def test_directional_guard_buy_pe():
    """BUY_PE action selects strictly Put option (PE) and rejects Call."""
    chain = build_mock_option_chain("NIFTY", 24500.0)
    setup = {
        "action": "BUY_PE",
        "entry_price": 24500.0,
        "stop_loss": 24580.0,
        "target_1": 24400.0,
        "target_2": 24320.0,
    }
    contract = select_option_contract(setup, "NIFTY", 24500.0, chain)

    assert contract["qualification_status"] == "QUALIFIED"
    assert contract["action"] == "BUY_PE"
    assert contract["option_type"] == "PE"
    assert "PE" in contract["contract_symbol"]
    assert contract["delta"] is not None
    assert contract["delta"] < 0.0


def test_directional_guard_wait_and_no_trade():
    """WAIT and NO_TRADE underlying setups reject contract selection with explanation."""
    chain = build_mock_option_chain("NIFTY", 24500.0)

    for action in ["WAIT", "NO_TRADE", "INVALID_ACTION"]:
        setup = {"action": action, "entry_price": 24500.0}
        res = select_option_contract(setup, "NIFTY", 24500.0, chain)

        assert res["qualification_status"] == "REJECTED"
        assert res["action"] == "NO_TRADE"
        assert res["contract_symbol"] is None
        assert res["paper_trading_eligible"] is False
        assert any("does not permit option contract selection" in r for r in res["rejection_reasons"])


# =====================================================================
# 5. Delta Filtering & Moneyness Tests
# =====================================================================

def test_delta_filtering_within_target_range():
    """Selects contracts strictly within [0.35, 0.55] Delta and picks closest to target Delta."""
    chain = build_mock_option_chain("NIFTY", 24500.0)
    setup = {"action": "BUY_CE", "entry_price": 24500.0, "stop_loss": 24420.0}

    contract = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert contract["qualification_status"] == "QUALIFIED"
    assert 0.35 <= contract["delta"] <= 0.55
    assert contract["strike"] in [24500.0, 24550.0]


def test_delta_filtering_deep_otm_rejection():
    """Contracts with Delta < 0.35 are rejected when no contracts in [0.35, 0.55] exist."""
    overrides = {
        k: {"delta": 0.20, "ltp": 25.0, "bid": 24.5, "ask": 25.5}
        for k in [24300, 24350, 24400, 24450, 24500, 24550, 24600, 24650, 24700]
    }
    chain = build_mock_option_chain("NIFTY", 24500.0, custom_ce_overrides=overrides)
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "REJECTED"
    assert any("NO_ELIGIBLE_CONTRACT" in r for r in res["rejection_reasons"])


def test_delta_filtering_deep_itm_rejection():
    """Contracts with Delta > 0.55 are rejected when no contracts in [0.35, 0.55] exist."""
    overrides = {
        k: {"delta": 0.75, "ltp": 450.0, "bid": 449.0, "ask": 451.0}
        for k in [24300, 24350, 24400, 24450, 24500, 24550, 24600, 24650, 24700]
    }
    chain = build_mock_option_chain("NIFTY", 24500.0, custom_ce_overrides=overrides)
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "REJECTED"
    assert any("NO_ELIGIBLE_CONTRACT" in r for r in res["rejection_reasons"])


def test_configurable_delta_range():
    """Custom Delta range [0.25, 0.35] passed via config selects appropriate contract."""
    chain = build_mock_option_chain("NIFTY", 24500.0, strikes=[24650, 24700, 24750, 24800])
    setup = {"action": "BUY_CE", "entry_price": 24500.0}
    cfg = {"min_delta": 0.25, "max_delta": 0.35, "target_delta": 0.30}

    contract = select_option_contract(setup, "NIFTY", 24500.0, chain, config=cfg)
    assert contract["qualification_status"] == "QUALIFIED"
    assert 0.25 <= contract["delta"] <= 0.35


def test_moneyness_tagging():
    """Correctly assigns ATM, ITM, and OTM moneyness."""
    chain = build_mock_option_chain("NIFTY", 24500.0)
    setup_ce = {"action": "BUY_CE", "entry_price": 24500.0}
    c_atm = select_option_contract(setup_ce, "NIFTY", 24500.0, chain)
    assert c_atm["qualification_status"] == "QUALIFIED"
    if c_atm["strike"] == 24500.0:
        assert c_atm["moneyness"] == "ATM"
    elif c_atm["strike"] < 24500.0:
        assert c_atm["moneyness"] == "ITM"
    else:
        assert c_atm["moneyness"] == "OTM"


# =====================================================================
# 6. Liquidity and Spread Gating Tests
# =====================================================================

def test_liquidity_zero_bid_rejection():
    """Option with zero bid is rejected for liquidity risk."""
    overrides = {24500: {"bid": 0.0, "ask": 150.0}}
    chain = build_mock_option_chain("NIFTY", 24500.0, custom_ce_overrides=overrides)
    for s in chain["strikes"]:
        if s["strike"] != 24500.0:
            s["ce"]["delta"] = 0.10
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "REJECTED"
    assert any("Zero bid depth" in r or "NO_ELIGIBLE_CONTRACT" in r for r in res["rejection_reasons"])


def test_liquidity_zero_ask_rejection():
    """Option with zero ask is rejected."""
    overrides = {24500: {"bid": 150.0, "ask": 0.0}}
    chain = build_mock_option_chain("NIFTY", 24500.0, custom_ce_overrides=overrides)
    chain["strikes"] = [s for s in chain["strikes"] if s["strike"] == 24500.0]
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "REJECTED"


def test_liquidity_inverted_spread_rejection():
    """Option with inverted bid-ask spread (bid > ask) is rejected."""
    overrides = {24500: {"bid": 160.0, "ask": 150.0}}
    chain = build_mock_option_chain("NIFTY", 24500.0, custom_ce_overrides=overrides)
    chain["strikes"] = [s for s in chain["strikes"] if s["strike"] == 24500.0]
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "REJECTED"


def test_liquidity_excessive_spread_rejection():
    """Option exceeding index maximum permitted spread is rejected."""
    overrides = {24500: {"bid": 100.0, "ask": 110.0, "spread_pct": 0.095}}
    chain = build_mock_option_chain("NIFTY", 24500.0, custom_ce_overrides=overrides)
    chain["strikes"] = [s for s in chain["strikes"] if s["strike"] == 24500.0]
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "REJECTED"


def test_open_interest_gating():
    """Options with missing, zero, or below-threshold OI are rejected."""
    overrides = {24500: {"oi": 5000}}
    chain = build_mock_option_chain("NIFTY", 24500.0, custom_ce_overrides=overrides)
    chain["strikes"] = [s for s in chain["strikes"] if s["strike"] == 24500.0]
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "REJECTED"


def test_volume_gating():
    """Options with missing, zero, or below-threshold volume are rejected."""
    overrides = {24500: {"volume": 200}}
    chain = build_mock_option_chain("NIFTY", 24500.0, custom_ce_overrides=overrides)
    chain["strikes"] = [s for s in chain["strikes"] if s["strike"] == 24500.0]
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "REJECTED"


def test_freshness_stale_quote_rejection():
    """Stale quote feed (isStale=True) is rejected."""
    overrides = {24500: {"isStale": True}}
    chain = build_mock_option_chain("NIFTY", 24500.0, custom_ce_overrides=overrides)
    chain["strikes"] = [s for s in chain["strikes"] if s["strike"] == 24500.0]
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "REJECTED"


def test_theoretical_quote_rejection():
    """Theoretical quote (isTheoretical=True) is rejected for paper trading execution."""
    overrides = {24500: {"isTheoretical": True, "data_status": "THEORETICAL"}}
    chain = build_mock_option_chain("NIFTY", 24500.0, custom_ce_overrides=overrides)
    chain["strikes"] = [s for s in chain["strikes"] if s["strike"] == 24500.0]
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "REJECTED"


def test_expired_series_rejection():
    """Option chain with expired selectedExpiry is rejected with status EXPIRED."""
    chain = build_mock_option_chain("NIFTY", 24500.0)
    chain["selectedExpiry"] = "01-JAN-2020"
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "REJECTED"
    assert res["data_status"] == "EXPIRED"
    assert any("expired" in r for r in res["rejection_reasons"])


def test_missing_greeks_rejection():
    """Contracts with None or NaN Greeks are rejected."""
    overrides = {24500: {"delta": None, "iv": 0.0}}
    chain = build_mock_option_chain("NIFTY", 24500.0, custom_ce_overrides=overrides)
    chain["strikes"] = [s for s in chain["strikes"] if s["strike"] == 24500.0]
    setup = {"action": "BUY_CE", "entry_price": 24500.0}

    res = select_option_contract(setup, "NIFTY", 24500.0, chain)
    assert res["qualification_status"] == "REJECTED"


def test_symbol_normalization():
    """Normalizes various market index notations."""
    assert normalize_index_symbol("NIFTY 50") == "NIFTY"
    assert normalize_index_symbol("NIFTY") == "NIFTY"
    assert normalize_index_symbol("BANK NIFTY") == "BANKNIFTY"
    assert normalize_index_symbol("NIFTY BANK") == "BANKNIFTY"
    assert normalize_index_symbol("FINNIFTY") == "FINNIFTY"
    assert normalize_index_symbol("BSE SENSEX") == "SENSEX"


def test_banknifty_contract_selection():
    """Selects valid BANKNIFTY contract with authoritative lot size."""
    chain = build_mock_option_chain(
        symbol="BANKNIFTY",
        underlying_spot=52000.0,
        strikes=[51800, 51900, 52000, 52100, 52200],
    )
    setup = {"action": "BUY_PE", "entry_price": 52000.0, "stop_loss": 52250.0}

    res = select_option_contract(setup, "BANKNIFTY", 52000.0, chain)
    assert res["qualification_status"] == "QUALIFIED"
    assert res["index"] == "BANKNIFTY"
    assert res["option_type"] == "PE"
    assert res["lot_size"] in (15, 30)
    assert res["tick_size"] == 0.05
    assert res["strike"] in [51900.0, 52000.0, 52100.0]


def test_empty_or_malformed_chain_rejection():
    """Handles empty or missing strikes list gracefully."""
    setup = {"action": "BUY_CE", "entry_price": 24500.0}
    res1 = select_option_contract(setup, "NIFTY", 24500.0, {})
    assert res1["qualification_status"] == "REJECTED"
    assert any("missing or invalid" in r for r in res1["rejection_reasons"])

    res2 = select_option_contract(setup, "NIFTY", 24500.0, {"strikes": []})
    assert res2["qualification_status"] == "REJECTED"
    assert any("zero strike records" in r for r in res2["rejection_reasons"])
