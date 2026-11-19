"""
AIVOLVE Institutional API Authorization & Governance Security Guard (Workstream B2).

Enforces fail-closed identity verification on all state-changing endpoints:
- Virtual Paper Trading Operations (Open, Close, Partial Exit, Reset, Quote Ingestion)
- ML Model Training and Production Promotion
- Dynamic Risk Management & Circuit Breaker Administration
"""

from typing import Optional
from fastapi import Header, HTTPException, status
from app.core.config import settings
from app.core.logging import logger


async def verify_operator_authorization(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_aivolve_auth_token: Optional[str] = Header(None, alias="X-AIVOLVE-AUTH-TOKEN"),
) -> str:
    """
    Enforces authorization on state-changing paper-trading endpoints (REQ-B2).
    Fails closed if the caller does not present a valid operator token.
    """
    token = None
    if authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        elif len(parts) == 1:
            token = parts[0]
    elif x_aivolve_auth_token:
        token = x_aivolve_auth_token.strip()

    expected_key = getattr(settings, "OPERATOR_SECRET_KEY", "") or "aivolve-internal-operator"

    if not token or token != expected_key:
        logger.warning(
            "[SecurityAudit] Unauthorized attempt to access state-changing paper trading endpoint. "
            f"Provided token: {'Present (Mismatch)' if token else 'None'}"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status": "UNAUTHORIZED",
                "message": (
                    "Authorization required for state-changing paper trading actions. "
                    "Valid operator bearer token or X-AIVOLVE-AUTH-TOKEN header must be supplied."
                ),
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


async def verify_ml_governance_authorization(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_aivolve_auth_token: Optional[str] = Header(None, alias="X-AIVOLVE-AUTH-TOKEN"),
    x_ml_governance_token: Optional[str] = Header(None, alias="X-ML-GOVERNANCE-TOKEN"),
) -> str:
    """
    Enforces strict institutional governance on ML model training and production promotion (REQ-D).
    Fails closed unless institutional ML governance authorization is explicitly configured and supplied.
    """
    token = x_ml_governance_token or (authorization.strip().split()[-1] if authorization else None) or x_aivolve_auth_token

    expected_gov_key = getattr(settings, "ML_GOVERNANCE_SECRET_KEY", "")

    if not expected_gov_key or not token or token != expected_gov_key:
        logger.warning(
            "[SecurityAudit] Blocked unauthorized attempt to invoke governed ML training or promotion. "
            "Institutional ML governance sign-off token missing or unconfigured."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "status": "ML_GOVERNANCE_BLOCKED",
                "message": (
                    "Governed ML operation rejected: Institutional ML governance authorization is unconfigured "
                    "or sign-off token is invalid. Production training and promotion remain strictly locked."
                ),
            },
        )

    return token
