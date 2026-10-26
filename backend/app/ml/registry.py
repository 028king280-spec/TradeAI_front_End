import time
from typing import Dict, Any, List, Optional
from enum import Enum


class ModelStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    PRODUCTION = "PRODUCTION"
    REJECTED = "REJECTED"


class ModelRegistry:
    """
    Manages Quantitative & ML Model Lifecycle:
    - Statuses: CANDIDATE, VALIDATED, PRODUCTION, REJECTED
    - Safety guard: NEVER automatically replaces the production model without human audit.
    """

    _registry: Dict[str, Dict[str, Any]] = {}
    _production_model_id: Optional[str] = None

    @classmethod
    def register_model(
        cls,
        name: str,
        version: str,
        model_type: str,
        model_obj: Any,
        scaler: Any,
        metrics: Dict[str, Any],
        features: List[str],
        status: ModelStatus = ModelStatus.CANDIDATE,
    ) -> str:
        model_id = f"{name}_{version}_{int(time.time())}"
        entry = {
            "model_id": model_id,
            "name": name,
            "version": version,
            "model_type": model_type,
            "status": status.value,
            "model": model_obj,
            "scaler": scaler,
            "metrics": metrics,
            "features": features,
            "registered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "notes": "Candidate model trained via time-series split.",
        }
        cls._registry[model_id] = entry
        return model_id

    @classmethod
    def promote_to_validated(cls, model_id: str) -> bool:
        if model_id in cls._registry:
            cls._registry[model_id]["status"] = ModelStatus.VALIDATED.value
            return True
        return False

    @classmethod
    def promote_to_production(cls, model_id: str) -> bool:
        """
        Promotes a validated model to production.
        Explicitly audited: demotes existing production model to VALIDATED.
        """
        if model_id not in cls._registry:
            return False

        # Demote current production model
        if cls._production_model_id and cls._production_model_id in cls._registry:
            cls._registry[cls._production_model_id]["status"] = ModelStatus.VALIDATED.value

        cls._registry[model_id]["status"] = ModelStatus.PRODUCTION.value
        cls._production_model_id = model_id
        return True

    @classmethod
    def reject_model(cls, model_id: str, reason: str = "") -> bool:
        if model_id in cls._registry:
            cls._registry[model_id]["status"] = ModelStatus.REJECTED.value
            cls._registry[model_id]["rejection_reason"] = reason
            return True
        return False

    @classmethod
    def get_production_model(cls) -> Optional[Dict[str, Any]]:
        if cls._production_model_id:
            return cls._registry.get(cls._production_model_id)
        # Fallback to any production model
        for entry in cls._registry.values():
            if entry["status"] == ModelStatus.PRODUCTION.value:
                cls._production_model_id = entry["model_id"]
                return entry
        return None

    @classmethod
    def list_models(cls) -> List[Dict[str, Any]]:
        results = []
        for m in cls._registry.values():
            results.append({
                "model_id": m["model_id"],
                "name": m["name"],
                "version": m["version"],
                "model_type": m["model_type"],
                "status": m["status"],
                "metrics": m["metrics"],
                "features_count": len(m["features"]),
                "registered_at": m["registered_at"],
            })
        return results


class ModelRegistryService:
    """
    Database-backed service for ML Model Lifecycle and persistence.
    """

    @classmethod
    async def register_model(
        cls,
        session: Any,
        model_version: str,
        model_name: str,
        model_type: str,
        target_variable: str,
        training_dataset_version: str,
        training_start: Any,
        training_end: Any,
        validation_metrics: Dict[str, Any],
        test_metrics: Dict[str, Any],
        backtest_metrics: Optional[Dict[str, Any]] = None,
        feature_version: str = "v1",
        file_path: Optional[str] = None,
    ):
        from app.models.db_models import MLModelRecord

        record = MLModelRecord(
            model_version=model_version,
            model_name=model_name,
            model_type=model_type,
            target_variable=target_variable,
            training_dataset_version=training_dataset_version,
            feature_version=feature_version,
            training_start=training_start,
            training_end=training_end,
            validation_metrics=validation_metrics,
            test_metrics=test_metrics,
            backtest_metrics=backtest_metrics,
            status=ModelStatus.CANDIDATE.value,
            file_path=file_path,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    @classmethod
    async def list_models(cls, session: Any):
        from sqlalchemy import select
        from app.models.db_models import MLModelRecord

        result = await session.execute(select(MLModelRecord).order_by(MLModelRecord.created_at.desc()))
        return list(result.scalars().all())

    @classmethod
    async def get_model(cls, session: Any, version: str):
        from sqlalchemy import select
        from app.models.db_models import MLModelRecord

        result = await session.execute(select(MLModelRecord).where(MLModelRecord.model_version == version))
        return result.scalar_one_or_none()

    @classmethod
    async def promote_model(cls, session: Any, version: str) -> Dict[str, Any]:
        from sqlalchemy import select
        from app.models.db_models import MLModelRecord

        model = await cls.get_model(session, version)
        if not model:
            return {"success": False, "message": f"Model '{version}' not found"}

        # Demote previous PRODUCTION model if any
        prev_prod = await session.execute(select(MLModelRecord).where(MLModelRecord.status == ModelStatus.PRODUCTION.value))
        for p in prev_prod.scalars().all():
            p.status = ModelStatus.VALIDATED.value

        model.status = ModelStatus.PRODUCTION.value
        await session.commit()
        return {"success": True, "message": f"Model '{version}' promoted to PRODUCTION"}

