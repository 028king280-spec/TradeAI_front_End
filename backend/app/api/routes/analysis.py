from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.schemas.market import ApiResponse
from app.schemas.analysis import StockAnalysisSchema, TechnicalIndicatorsSchema
from app.services.analysis_service import AnalysisService
from app.core.security import sanitize_stock_symbol

router = APIRouter(prefix="/stocks", tags=["Analysis"])
direct_analysis_router = APIRouter(prefix="/analysis", tags=["Analysis"])


@router.get("/{symbol}/analysis", response_model=ApiResponse[StockAnalysisSchema])
@direct_analysis_router.get("/{symbol}", response_model=ApiResponse[StockAnalysisSchema])
async def get_stock_analysis(
    symbol: str,
    db: AsyncSession = Depends(get_db)
):
    clean_sym = sanitize_stock_symbol(symbol)
    try:
        analysis = await AnalysisService.get_analysis(clean_sym, session=db)
        return ApiResponse(success=True, data=analysis)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis pipeline error for '{clean_sym}': {str(e)}"
        )


@router.get("/{symbol}/technical", response_model=ApiResponse[TechnicalIndicatorsSchema])
async def get_stock_technical(
    symbol: str,
    db: AsyncSession = Depends(get_db)
):
    clean_sym = sanitize_stock_symbol(symbol)
    try:
        analysis = await AnalysisService.get_analysis(clean_sym, session=db)
        return ApiResponse(success=True, data=analysis["technicalIndicators"])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Technical indicators error for '{clean_sym}': {str(e)}"
        )


@router.get("/{symbol}/scenarios", response_model=ApiResponse[dict])
async def get_stock_scenarios(
    symbol: str,
    db: AsyncSession = Depends(get_db)
):
    clean_sym = sanitize_stock_symbol(symbol)
    try:
        analysis = await AnalysisService.get_analysis(clean_sym, session=db)
        return ApiResponse(
            success=True,
            data={
                "bullishScenario": analysis["bullishScenario"],
                "baseScenario": analysis["baseScenario"],
                "bearishScenario": analysis["bearishScenario"],
                "outlookChanges": analysis["outlookChanges"],
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scenarios error for '{clean_sym}': {str(e)}"
        )
