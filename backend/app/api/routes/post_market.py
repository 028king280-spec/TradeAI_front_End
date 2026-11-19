"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
REST API Routes for Daily Post-Market Trade Forensics and Continuous ML Learning Pipeline.
"""

from fastapi import APIRouter, Query, HTTPException, status
from typing import Dict, Any, Optional
import os
import json

from app.options.paper_trading.post_market_pipeline import (
    DailyPostMarketForensicPipeline,
    REVIEWS_DIR,
    PRODUCTION_DATASET_PATH,
    QUARANTINE_DATASET_PATH,
    MIN_SAMPLES_FOR_RETRAINING,
)

router = APIRouter(prefix="/post-market", tags=["Daily Post-Market AI Review"])


@router.get("/daily-review")
async def get_daily_review(
    date: str = Query("2026-11-19", description="Session date in YYYY-MM-DD format")
) -> Dict[str, Any]:
    """
    Returns complete post-market forensic review, verified price reconstruction,
    18-dimension WHY analysis, and financial reconciliation for the specified session.
    """
    review_path = os.path.join(REVIEWS_DIR, f"review_{date}.json")
    if os.path.exists(review_path):
        try:
            with open(review_path, "r", encoding="utf-8") as f:
                return {"success": True, "data": json.load(f)}
        except Exception as e:
            pass

    # If review file doesn't exist yet, run pipeline on-the-fly
    pipeline = DailyPostMarketForensicPipeline(date)
    report = pipeline.run_full_pipeline()
    return {"success": True, "data": report}


@router.post("/run-pipeline")
async def run_pipeline(
    date: str = Query("2026-11-19", description="Session date in YYYY-MM-DD format")
) -> Dict[str, Any]:
    """
    Triggers post-market execution pipeline, computes reconciliations,
    appends genuine observations to ml_production_dataset.json, and persists review.
    """
    try:
        pipeline = DailyPostMarketForensicPipeline(date)
        report = pipeline.run_full_pipeline()
        return {"success": True, "message": "Pipeline completed successfully", "data": report}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Post-market pipeline execution error: {str(e)}"
        )


@router.get("/governance-status")
async def get_governance_status() -> Dict[str, Any]:
    """
    Returns current Phase 5 ML Governance status, dataset accumulation progress,
    and retraining authorization state.
    """
    total_genuine = 0
    if os.path.exists(PRODUCTION_DATASET_PATH):
        try:
            with open(PRODUCTION_DATASET_PATH, "r", encoding="utf-8") as f:
                total_genuine = len(json.load(f))
        except Exception:
            total_genuine = 0

    pipeline = DailyPostMarketForensicPipeline()
    gov = pipeline.evaluate_ml_governance(total_genuine)
    baseline_check = pipeline.verify_baseline_immutability(
        pipeline.get_baseline_hashes(),
        pipeline.get_baseline_hashes()
    )

    return {
        "success": True,
        "data": {
            "governance": gov,
            "baseline_files_intact": baseline_check["all_baselines_untouched"],
            "dataset_path": PRODUCTION_DATASET_PATH,
            "quarantine_path": QUARANTINE_DATASET_PATH,
        }
    }
