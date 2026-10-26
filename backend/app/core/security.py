import re
from typing import Optional
from fastapi import HTTPException, status
from app.core.config import settings


def sanitize_stock_symbol(symbol: str) -> str:
    """
    Sanitize and validate Indian stock symbols (NSE/BSE).
    Must be alphanumeric, optionally containing '&' or '-' (e.g. M&M).
    Max length 20 characters.
    """
    cleaned = symbol.strip().upper()
    if not re.match(r"^[A-Z0-9&\-]{1,20}$", cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid stock symbol format: '{symbol}'"
        )
    return cleaned


def sanitize_search_query(q: Optional[str]) -> str:
    """
    Sanitize search text queries to prevent SQL or pattern injection.
    """
    if not q:
        return ""
    # Strip any characters that are not alphanumeric, spaces, ampersands, or hyphens
    cleaned = re.sub(r"[^\w\s&\-]", "", q, flags=re.UNICODE)
    return cleaned.strip()[:50]
