from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    brier_score_loss
)


class ModelFactory:
    """
    Instantiates and evaluates machine learning models for market prediction.
    """

    @staticmethod
    def create_model(model_type: str):
        mt = model_type.lower()
        if mt == "logistic_regression":
            return LogisticRegression(max_iter=1000, random_state=42)
        elif mt == "random_forest":
            return RandomForestClassifier(n_estimators=100, max_depth=5, min_samples_split=5, random_state=42)
        elif mt == "gradient_boosting":
            return GradientBoostingClassifier(n_estimators=100, learning_rate=0.05, max_depth=3, random_state=42)
        elif mt in ["mlp", "neural_network"]:
            return MLPClassifier(hidden_layer_sizes=(32, 16), max_iter=500, random_state=42)
        else:
            return RandomForestClassifier(n_estimators=50, max_depth=4, random_state=42)

    @staticmethod
    def evaluate_model(model, X: pd.DataFrame, y: pd.Series) -> Dict[str, Any]:
        """
        Calculates institutional evaluation metrics including calibration and directional accuracy.
        """
        if len(y) == 0:
            return {"accuracy": 0.0, "f1": 0.0}

        y_pred = model.predict(X)

        acc = float(accuracy_score(y, y_pred))
        prec = float(precision_score(y, y_pred, zero_division=0))
        rec = float(recall_score(y, y_pred, zero_division=0))
        f1 = float(f1_score(y, y_pred, zero_division=0))

        auc = 0.5
        brier = 0.25
        if hasattr(model, "predict_proba"):
            y_proba = model.predict_proba(X)[:, 1]
            try:
                auc = float(roc_auc_score(y, y_proba))
            except Exception:
                auc = 0.5
            brier = float(brier_score_loss(y, y_proba))

        return {
            "accuracy": round(acc, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1Score": round(f1, 4),
            "rocAuc": round(auc, 4),
            "brierScore": round(brier, 4),
            "directionalAccuracy": round(acc * 100, 2),
            "sampleCount": len(y),
        }
