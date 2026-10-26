import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.db_models import MLTrainingJob
from app.data.providers.factory import get_market_data_provider
from app.ml.features import FeatureEngineering
from app.ml.validation import TimeSeriesSplitter
from app.ml.models import ModelFactory
from app.ml.backtest import EconomicBacktester
from app.ml.registry import ModelRegistryService
from app.core.logging import logger


class MLTrainingPipeline:
    """
    Orchestrates the asynchronous machine learning training pipeline.
    Ensures zero lookahead bias with chronological time-series cross-validation.
    """

    @classmethod
    async def start_training_job(
        cls,
        session: AsyncSession,
        model_type: str,
        target: str,
        symbols: List[str],
        lookback_days: int = 180,
        features: List[str] = None
    ) -> MLTrainingJob:
        job = MLTrainingJob(
            model_type=model_type,
            target=target,
            dataset_range=f"{lookback_days} days across {len(symbols)} symbols",
            features=features or FeatureEngineering.FEATURE_NAMES,
            status="RUNNING",
            progress=10,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        # Run background training task
        asyncio.create_task(cls._execute_training(job.id, model_type, target, symbols, lookback_days))
        return job

    @classmethod
    async def _execute_training(
        cls,
        job_id: str,
        model_type: str,
        target: str,
        symbols: List[str],
        lookback_days: int
    ):
        from app.db.database import async_session_factory
        provider = get_market_data_provider()

        async with async_session_factory() as session:
            try:
                # Update progress to 25%
                job = await session.get(MLTrainingJob, job_id)
                if not job:
                    return
                job.progress = 25
                await session.commit()

                # Ingest historical data
                end_dt = datetime.now(timezone.utc)
                start_dt = end_dt - timedelta(days=lookback_days)

                dfs = []
                for sym in symbols:
                    df_sym = await provider.get_historical_candles(sym, "1d", start_dt, end_dt)
                    if not df_sym.empty and len(df_sym) >= 30:
                        dfs.append(df_sym)

                if not dfs:
                    raise RuntimeError("Insufficient historical candle data retrieved for training")

                combined_df = pd.concat(dfs).sort_values("timestamp").reset_index(drop=True)

                job.progress = 50
                await session.commit()

                # Feature engineering & labels
                X, y = FeatureEngineering.create_labels(combined_df, target)
                if len(X) < 40:
                    raise RuntimeError(f"Insufficient samples ({len(X)}) for time-series training")

                # Time-series split (No shuffling!)
                X_tr, X_val, X_te, y_tr, y_val, y_te = TimeSeriesSplitter.train_val_test_split(X, y)

                job.progress = 70
                await session.commit()

                # Train model
                model = ModelFactory.create_model(model_type)
                model.fit(X_tr, y_tr)

                val_metrics = ModelFactory.evaluate_model(model, X_val, y_val)
                test_metrics = ModelFactory.evaluate_model(model, X_te, y_te)

                # Economic backtesting on test fold
                test_signals = pd.Series(model.predict(X_te))
                test_prices = combined_df.iloc[X_te.index]["close"]
                backtest_results = EconomicBacktester.run_backtest(test_prices, test_signals)

                job.progress = 90
                await session.commit()

                # Register model candidate
                model_ver = f"{model_type.lower()}-{target}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                model_name = f"{model_type.title()} {target.replace('_', ' ').title()}"

                await ModelRegistryService.register_model(
                    session=session,
                    model_version=model_ver,
                    model_name=model_name,
                    model_type=model_type,
                    target_variable=target,
                    training_dataset_version=f"DS-NSE-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                    training_start=start_dt,
                    training_end=end_dt,
                    validation_metrics=val_metrics,
                    test_metrics=test_metrics,
                    backtest_metrics=backtest_results,
                )

                job.status = "COMPLETED"
                job.progress = 100
                job.result_model_version = model_ver
                job.completed_at = datetime.now(timezone.utc)
                await session.commit()

                logger.info(f"Training job {job_id} successfully completed. Model registered: {model_ver}")

            except Exception as e:
                logger.error(f"Training job {job_id} failed: {e}")
                job = await session.get(MLTrainingJob, job_id)
                if job:
                    job.status = "FAILED"
                    job.error_message = str(e)
                    job.completed_at = datetime.now(timezone.utc)
                    await session.commit()
