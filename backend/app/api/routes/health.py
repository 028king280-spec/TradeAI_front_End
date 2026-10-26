from fastapi import APIRouter
from app.schemas.market import ApiResponse
from app.core.config import settings
from app.data.market_calendar import MarketCalendar

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=ApiResponse[dict])
async def health_check():
    return ApiResponse(
        success=True,
        data={
            "status": "healthy",
            "service": settings.APP_NAME,
            "environment": settings.APP_ENV,
            "provider": settings.MARKET_DATA_PROVIDER,
            "marketStatus": MarketCalendar.get_market_status(),
            "serverTimeIST": MarketCalendar.format_ist_timestamp(),
            "version": "1.0.0",
        }
    )
