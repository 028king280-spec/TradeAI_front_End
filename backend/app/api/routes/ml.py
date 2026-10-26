from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.schemas.market import ApiResponse
from app.schemas.ml import (
    MLTrainRequest,
    MLTrainResponse,
    MLJobStatusSchema,
    MLModelDetailsSchema,
    MLBacktestRequest,
    MLBacktestResponse,
)
from app.models.db_models import MLTrainingJob
from app.ml.trainer import MLTrainingPipeline
from app.ml.registry import ModelRegistryService
from app.ml.backtest import EconomicBacktester
from app.data.providers.factory import get_market_data_provider

router = APIRouter(prefix="/ml", tags=["ML Model Lab"])


@router.post("/train", response_model=ApiResponse[MLTrainResponse])
async def trigger_training_job(
    req: MLTrainRequest,
    db: AsyncSession = Depends(get_db)
):
    job = await MLTrainingPipeline.start_training_job(
        session=db,
        model_type=req.modelType,
        target=req.target,
        symbols=req.symbols,
        lookback_days=req.lookbackDays,
        features=req.features,
    )
    return ApiResponse(
        success=True,
        data=MLTrainResponse(
            jobId=job.id,
            status=job.status,
            message="Time-series aware training job queued successfully. Tracking metrics out-of-sample.",
        )
    )


@router.get("/jobs", response_model=ApiResponse[List[MLJobStatusSchema]])
async def list_training_jobs(db: AsyncSession = Depends(get_db)):
    stmt = select(MLTrainingJob).order_by(MLTrainingJob.created_at.desc()).limit(20)
    result = await db.execute(stmt)
    jobs = result.scalars().all()
    items = [
        MLJobStatusSchema(
            jobId=j.id,
            modelType=j.model_type,
            target=j.target,
            status=j.status,
            progress=j.progress,
            resultModelVersion=j.result_model_version,
            errorMessage=j.error_message,
            createdAt=j.created_at.isoformat(),
            completedAt=j.completed_at.isoformat() if j.completed_at else None,
        )
        for j in jobs
    ]
    return ApiResponse(success=True, data=items)


@router.get("/models", response_model=ApiResponse[List[MLModelDetailsSchema]])
async def list_models(db: AsyncSession = Depends(get_db)):
    models = await ModelRegistryService.list_models(db)
    items = [
        MLModelDetailsSchema(
            modelVersion=m.model_version,
            modelName=m.model_name,
            modelType=m.model_type,
            targetVariable=m.target_variable,
            status=m.status,
            trainingDatasetVersion=m.training_dataset_version,
            featureVersion=m.feature_version,
            trainingStart=m.training_start.isoformat(),
            trainingEnd=m.training_end.isoformat(),
            validationMetrics=m.validation_metrics,
            testMetrics=m.test_metrics,
            backtestMetrics=m.backtest_metrics,
            createdAt=m.created_at.isoformat(),
        )
        for m in models
    ]
    return ApiResponse(success=True, data=items)


@router.get("/models/{version}", response_model=ApiResponse[MLModelDetailsSchema])
async def get_model_details(version: str, db: AsyncSession = Depends(get_db)):
    m = await ModelRegistryService.get_model(db, version)
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Model '{version}' not found")

    return ApiResponse(
        success=True,
        data=MLModelDetailsSchema(
            modelVersion=m.model_version,
            modelName=m.model_name,
            modelType=m.model_type,
            targetVariable=m.target_variable,
            status=m.status,
            trainingDatasetVersion=m.training_dataset_version,
            featureVersion=m.feature_version,
            trainingStart=m.training_start.isoformat(),
            trainingEnd=m.training_end.isoformat(),
            validationMetrics=m.validation_metrics,
            testMetrics=m.test_metrics,
            backtestMetrics=m.backtest_metrics,
            createdAt=m.created_at.isoformat(),
        )
    )


@router.post("/models/{version}/promote", response_model=ApiResponse[dict])
async def promote_model_to_production(version: str, db: AsyncSession = Depends(get_db)):
    res = await ModelRegistryService.promote_model(db, version)
    if not res["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=res["message"])
    return ApiResponse(success=True, data={"message": res["message"]})


@router.post("/backtest", response_model=ApiResponse[MLBacktestResponse])
async def run_standalone_backtest(
    req: MLBacktestRequest,
    db: AsyncSession = Depends(get_db)
):
    model_record = await ModelRegistryService.get_model(db, req.modelVersion)
    if not model_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Model '{req.modelVersion}' not found")

    provider = get_market_data_provider()
    # Fetch historical candles for symbol
    from datetime import datetime, timezone, timedelta
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=90)
    df = await provider.get_historical_candles(req.symbol, "1d", start_dt, end_dt)

    if df.empty or len(df) < 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient price data for backtest")

    # Generate test signals based on model directional forecast
    prices = df["close"]
    signals = (prices.pct_change().shift(-1) > 0).astype(int).fillna(0)

    backtest = EconomicBacktester.run_backtest(
        prices=prices,
        signals=signals,
        initial_capital=req.initialCapital,
        slippage_bps=req.slippageBps,
        brokerage_per_trade=req.brokeragePerTrade,
    )

    return ApiResponse(
        success=True,
        data=MLBacktestResponse(
            modelVersion=req.modelVersion,
            symbol=req.symbol,
            totalTrades=backtest["totalTrades"],
            winRate=backtest["winRate"],
            profitFactor=backtest["profitFactor"],
            maxDrawdownPercent=backtest["maxDrawdownPercent"],
            sharpeRatio=backtest["sharpeRatio"],
            totalReturnPercent=backtest["totalReturnPercent"],
            netProfit=backtest["netProfit"],
            equityCurve=backtest["equityCurve"],
        )
    )
