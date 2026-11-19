from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import precision_score, recall_score, roc_auc_score, brier_score_loss

from app.ml.models import get_model
from app.core.logging import logger


class ModelTrainer:
    """
    Time-Series Aware Machine Learning Training Engine.
    Uses walk-forward TimeSeriesSplit to prevent look-ahead bias and data leakage.
    """

    @classmethod
    def train_and_validate(
        cls,
        X: pd.DataFrame,
        y: pd.Series,
        model_type: str = "random_forest",
        n_splits: int = 4
    ) -> Dict[str, Any]:
        if len(X) < 500:
            return {
                "status": "FAILED",
                "error": "GOVERNANCE_BLOCKED: Insufficient dataset length (< 500 verified samples required for production trading model training).",
            }

        tscv = TimeSeriesSplit(n_splits=n_splits)
        fold_scores = []

        scaler = StandardScaler()
        model = get_model(model_type)

        for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
            X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
            y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

            # Fit scaler only on train to prevent leakage
            X_train_sc = scaler.fit_transform(X_train)
            X_val_sc = scaler.transform(X_val)

            model.fit(X_train_sc, y_train)
            val_preds = model.predict(X_val_sc)
            val_proba = model.predict_proba(X_val_sc)[:, 1] if hasattr(model, "predict_proba") else val_preds

            prec = float(precision_score(y_val, val_preds, zero_division=0))
            rec = float(recall_score(y_val, val_preds, zero_division=0))
            auc = float(roc_auc_score(y_val, val_proba)) if len(np.unique(y_val)) > 1 else 0.5
            brier = float(brier_score_loss(y_val, val_proba))

            fold_scores.append({
                "fold": fold + 1,
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "auc": round(auc, 4),
                "brier": round(brier, 4),
            })

        # Final fit on complete history for inference
        X_all_sc = scaler.fit_transform(X)
        model.fit(X_all_sc, y)

        mean_auc = round(float(np.mean([f["auc"] for f in fold_scores])), 4)
        mean_prec = round(float(np.mean([f["precision"] for f in fold_scores])), 4)

        return {
            "status": "SUCCESS",
            "model_type": model_type,
            "mean_auc": mean_auc,
            "mean_precision": mean_prec,
            "folds": fold_scores,
            "model": model,
            "scaler": scaler,
        }
