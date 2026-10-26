from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.schemas.market import ApiResponse
from app.schemas.analysis import AIInsightSchema
from app.services.analysis_service import AnalysisService
from app.core.security import sanitize_stock_symbol
from app.ai.arcee_client import ArceeAIClient
from app.core.config import settings

router = APIRouter(prefix="/ai", tags=["AI & Arcee Intelligence"])


class ArceeAnalyzeRequest(BaseModel):
    text: str
    model: str = settings.ARCEE_MODEL


@router.get("/stocks/{symbol}/insights", response_model=ApiResponse[AIInsightSchema])
async def get_ai_insights(
    symbol: str,
    db: AsyncSession = Depends(get_db)
):
    clean_sym = sanitize_stock_symbol(symbol)
    try:
        analysis = await AnalysisService.get_analysis(clean_sym, session=db)
        return ApiResponse(success=True, data=analysis["aiInsights"])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI insight generation error for '{clean_sym}': {str(e)}"
        )


@router.get("/arcee/status")
async def get_arcee_status():
    """
    Check connection status with Arcee AI API.
    """
    masked_key = f"{settings.ARCEE_API_KEY[:8]}...{settings.ARCEE_API_KEY[-4:]}" if settings.ARCEE_API_KEY else "Not Configured"
    return {
        "success": True,
        "provider": "Arcee AI",
        "model": settings.ARCEE_MODEL,
        "baseUrl": settings.ARCEE_BASE_URL,
        "apiKeyMasked": masked_key,
        "isConfigured": bool(settings.ARCEE_API_KEY),
        "status": "Ready (OpenAI-compatible Trinity engine)",
    }


@router.post("/arcee/analyze")
async def analyze_with_arcee(payload: ArceeAnalyzeRequest):
    """
    Direct endpoint to analyze market text using Arcee AI.
    """
    result = await ArceeAIClient.analyze_article(payload.text)
    return ApiResponse(success=True, data=result)

