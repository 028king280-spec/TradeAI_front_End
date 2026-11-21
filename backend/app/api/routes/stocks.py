from typing import List, Optional, Any
from fastapi import APIRouter, Query, HTTPException, status
from app.schemas.market import ApiResponse
from app.schemas.stock import StockSearchItem, StockQuote
from app.services.stock_service import StockService
from app.data.providers.factory import get_market_data_provider
from app.core.security import sanitize_stock_symbol, sanitize_search_query

router = APIRouter(prefix="/stocks", tags=["Stocks"])


@router.get("/search", response_model=ApiResponse[List[StockSearchItem]])
async def search_stocks(
    q: Optional[str] = Query(default=""),
    exchange: Optional[str] = Query(default="ALL"),
    cap: Optional[str] = Query(default="ALL"),
):
    cleaned_q = sanitize_search_query(q)
    results = await StockService.search_stocks(cleaned_q, exchange, cap)
    return ApiResponse(success=True, data=results)


def _normalize_api_data_status(raw_status: Any, is_mock: bool = False) -> str:
    status_str = str(raw_status or "").upper()
    if is_mock or status_str == "MOCK":
        return "MOCK"
    if status_str in ("LIVE", "VERIFIED_LIVE"):
        return "LIVE"
    if status_str in ("MARKET_CLOSED", "VERIFIED_EOD", "EOD"):
        return "MARKET_CLOSED"
    if status_str in ("STALE", "DATA_OFFLINE", "UNAVAILABLE"):
        return status_str
    return "UNAVAILABLE"


@router.get("/{symbol}", response_model=ApiResponse[StockQuote])
@router.get("/{symbol}/quote", response_model=ApiResponse[StockQuote])
async def get_stock_quote(symbol: str):
    clean_sym = sanitize_stock_symbol(symbol)
    provider = get_market_data_provider()
    try:
        quote = await provider.get_quote(clean_sym)
        data_status = _normalize_api_data_status(quote.get("dataStatus"), bool(quote.get("is_mock")))
        if isinstance(quote, dict):
            quote["dataStatus"] = data_status
            if not quote.get("timestamp"):
                from app.data.market_calendar import MarketCalendar
                quote["timestamp"] = MarketCalendar.format_ist_timestamp()
        return ApiResponse(success=True, data=quote, dataStatus=data_status)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stock '{clean_sym}' not found or quote unavailable: {e}"
        )


@router.get("/{symbol}/candles", response_model=ApiResponse[List[dict]])
async def get_stock_candles(
    symbol: str,
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|30m|1h|1d)$"),
    limit: int = Query(default=100, ge=1, le=500),
):
    from app.services.historical_service import HistoricalDataService
    clean_sym = sanitize_stock_symbol(symbol)
    try:
        df = await HistoricalDataService.get_candles(clean_sym, timeframe, limit)
        records = []
        if not df.empty:
            for _, row in df.iterrows():
                records.append({
                    "timestamp": str(row["timestamp"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0)),
                    "vwap": float(row.get("vwap", row["close"])),
                })
        df_attrs = df.attrs if (df is not None and hasattr(df, "attrs")) else {}
        data_status = _normalize_api_data_status(
            df_attrs.get("dataStatus") or ("LIVE" if records else "UNAVAILABLE"),
            bool(df_attrs.get("is_mock")),
        )
        return ApiResponse(success=True, data=records, dataStatus=data_status)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve historical candles for '{clean_sym}': {e}"
        )


@router.get("/{symbol}/analysis", response_model=ApiResponse[dict])
async def get_stock_analysis(symbol: str):
    from app.services.analysis_service import AnalysisService
    clean_sym = sanitize_stock_symbol(symbol)
    try:
        analysis = await AnalysisService.get_analysis(clean_sym)
        return ApiResponse(
            success=True,
            data=analysis,
            dataStatus=_normalize_api_data_status(analysis.get("dataStatus")),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate analysis for '{clean_sym}': {e}"
        )




@router.get("/{symbol}/technical", response_model=ApiResponse[dict])
async def get_stock_technical(symbol: str):
    from app.services.analysis_service import AnalysisService
    clean_sym = sanitize_stock_symbol(symbol)
    try:
        analysis = await AnalysisService.get_analysis(clean_sym)
        return ApiResponse(
            success=True,
            data=analysis["technicalIndicators"],
            dataStatus=_normalize_api_data_status(analysis.get("dataStatus")),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve technical indicators for '{clean_sym}': {e}"
        )


@router.get("/{symbol}/scenarios", response_model=ApiResponse[List[dict]])
async def get_stock_scenarios(symbol: str):
    from app.services.analysis_service import AnalysisService
    clean_sym = sanitize_stock_symbol(symbol)
    try:
        analysis = await AnalysisService.get_analysis(clean_sym)
        return ApiResponse(
            success=True,
            data=analysis["scenarios"],
            dataStatus=_normalize_api_data_status(analysis.get("dataStatus")),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve scenarios for '{clean_sym}': {e}"
        )


@router.get("/{symbol}/ai-insights", response_model=ApiResponse[dict])
async def get_stock_ai_insights(symbol: str):
    from app.services.analysis_service import AnalysisService
    clean_sym = sanitize_stock_symbol(symbol)
    try:
        analysis = await AnalysisService.get_analysis(clean_sym)
        return ApiResponse(
            success=True,
            data=analysis["aiInsights"],
            dataStatus=_normalize_api_data_status(analysis.get("dataStatus")),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate AI insights for '{clean_sym}': {e}"
        )

