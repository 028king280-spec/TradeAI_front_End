from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Query, Path
from datetime import datetime, timezone

from app.schemas.market import ApiResponse
from app.schemas.news import (
    NewsItemSchema,
    NewsStatusSchema,
    MarketNewsSentimentSchema,
    StockSentimentAnalysisSchema,
)
from app.data.financial_news_provider import get_financial_news_provider
from app.services.stock_sentiment_service import StockSentimentCalculatorService
from app.core.logging import logger

router = APIRouter(prefix="/news", tags=["Market News"])


@router.get("/stock-sentiment/{symbol}", response_model=ApiResponse[StockSentimentAnalysisSchema])
async def calculate_stock_sentiment(
    symbol: str = Path(..., description="Indian stock symbol or company name, e.g. RELIANCE, TCS, TATAMOTORS, HDFCBANK")
):
    """
    On-Demand Multi-Factor Stock Sentiment Calculator.
    Calculates stock-specific sentiment from live financial news headlines,
    evaluates headline polarities, incorporates live market price action,
    and returns institutional metrics, key drivers, and risks.
    """
    try:
        result = await StockSentimentCalculatorService.calculate(symbol)
        return ApiResponse(
            success=True,
            data=result,
            dataStatus="LIVE" if result.get("totalArticles", 0) > 0 else "LIMITED",
            dataTimestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.error(f"Error calculating stock sentiment for {symbol}: {e}")
        return ApiResponse(
            success=False,
            error={"code": "STOCK_SENTIMENT_ERROR", "message": str(e)},
            data=None,
            dataStatus="ERROR",
        )



@router.get("/sentiment", response_model=ApiResponse[MarketNewsSentimentSchema])
async def get_market_news_sentiment():
    """
    Returns aggregated Indian stock market sentiment derived from real-time news headlines
    (Moneycontrol, Economic Times, Livemint).
    Provides overall bias (BULLISH/BEARISH/NEUTRAL), score (-100 to +100), and sector catalysts.
    """
    try:
        provider = get_financial_news_provider()
        sentiment_summary = await provider.get_market_sentiment_summary()
        return ApiResponse(
            success=True,
            data=sentiment_summary,
            dataStatus="LIVE" if sentiment_summary.get("totalArticles", 0) > 0 else "UNAVAILABLE",
            dataTimestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.error(f"Error serving /api/news/sentiment: {e}")
        return ApiResponse(
            success=False,
            error={"code": "SENTIMENT_FETCH_ERROR", "message": str(e)},
            data=None,
            dataStatus="UNAVAILABLE",
        )



@router.get("/market", response_model=ApiResponse[List[NewsItemSchema]])
async def get_live_market_news(
    limit: int = Query(15, ge=1, le=50, description="Max news items to return")
):
    """
    Returns verified, live stock-market news for Indian markets (NIFTY, Sensex, NSE, Macro).
    Sources: Google News Financial RSS / Economic Times / Moneycontrol.
    Includes sentiment classification and impact scoring.
    """
    try:
        provider = get_financial_news_provider()
        items = await provider.get_market_news(limit=limit)
        return ApiResponse(
            success=True,
            data=items,
            dataStatus="LIVE" if items else "UNAVAILABLE",
            dataTimestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.error(f"Error serving /api/news/market: {e}")
        return ApiResponse(
            success=False,
            error={"code": "NEWS_FETCH_ERROR", "message": str(e)},
            data=[],
            dataStatus="UNAVAILABLE",
        )


@router.get("/symbol/{symbol}", response_model=ApiResponse[List[NewsItemSchema]])
async def get_stock_news(
    symbol: str = Path(..., description="NSE Stock or Index symbol, e.g. RELIANCE, TCS, NIFTY 50"),
    limit: int = Query(6, ge=1, le=20, description="Max news items to return")
):
    """
    Returns live news specifically matching an Indian equity or index symbol.
    """
    try:
        provider = get_financial_news_provider()
        items = await provider.get_news_for_stock(symbol=symbol, limit=limit)
        return ApiResponse(
            success=True,
            data=items,
            dataStatus="LIVE" if items else "UNAVAILABLE",
            dataTimestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.error(f"Error serving /api/news/symbol/{symbol}: {e}")
        return ApiResponse(
            success=False,
            error={"code": "NEWS_FETCH_ERROR", "message": str(e)},
            data=[],
            dataStatus="UNAVAILABLE",
        )


@router.get("/search", response_model=ApiResponse[List[NewsItemSchema]])
async def search_market_news(
    q: str = Query(..., min_length=2, max_length=100, description="Search query string"),
    limit: int = Query(10, ge=1, le=30, description="Max news items to return")
):
    """
    Searches live Indian financial news for arbitrary search topics.
    """
    try:
        provider = get_financial_news_provider()
        items = await provider.search_news(query=q, limit=limit)
        return ApiResponse(
            success=True,
            data=items,
            dataStatus="LIVE" if items else "UNAVAILABLE",
            dataTimestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.error(f"Error serving /api/news/search: {e}")
        return ApiResponse(
            success=False,
            error={"code": "NEWS_SEARCH_ERROR", "message": str(e)},
            data=[],
            dataStatus="UNAVAILABLE",
        )


@router.get("/status", response_model=ApiResponse[NewsStatusSchema])
async def get_news_provider_status():
    """
    Returns diagnostics and status of the live Indian Financial News feed.
    """
    provider = get_financial_news_provider()
    status_data = provider.get_status()
    return ApiResponse(
        success=True,
        data=status_data,
        dataStatus="LIVE",
        dataTimestamp=datetime.now(timezone.utc).isoformat(),
    )
