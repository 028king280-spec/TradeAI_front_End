from typing import Dict, Any
import numpy as np
from sklearn.metrics import classification_report, roc_auc_score, brier_score_loss, log_loss


class ModelEvaluator:
    """
    Evaluates ML classification models out-of-sample for institutional quantitative trading.
    """

    @staticmethod
    def evaluate(
        y_true: np.ndarray,
        y_pred: np.ndarray,
        y_prob: np.ndarray
    ) -> Dict[str, Any]:
        if len(y_true) == 0:
            return {}

        report = classification_report(y_true, y_pred, output_dict=True, zero_division=0)
        auc = float(roc_auc_score(y_true, y_prob)) if len(np.unique(y_true)) > 1 else 0.5
        brier = float(brier_score_loss(y_true, y_prob))

        return {
            "accuracy": round(float(report.get("accuracy", 0.0)), 4),
            "precision_class_1": round(float(report.get("1", {}).get("precision", 0.0)), 4),
            "recall_class_1": round(float(report.get("1", {}).get("recall", 0.0)), 4),
            "f1_class_1": round(float(report.get("1", {}).get("f1-score", 0.0)), 4),
            "roc_auc": round(auc, 4),
            "brier_score": round(brier, 4),
            "sample_size": len(y_true),
        }
