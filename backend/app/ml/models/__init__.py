from typing import Dict, Any
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.neural_network import MLPClassifier


def get_model(model_type: str = "random_forest", **kwargs):
    """
    Model Factory supporting Logistic Regression, Random Forest, Gradient Boosting, and MLP Neural Networks.
    """
    m_type = model_type.lower()
    if m_type in ["logistic", "lr", "logistic_regression"]:
        return LogisticRegression(max_iter=1000, random_state=42, **kwargs)
    elif m_type in ["gradient_boosting", "gb", "gbm"]:
        return GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=42, **kwargs)
    elif m_type in ["neural_network", "mlp", "nn"]:
        return MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=500, random_state=42, **kwargs)
    else:
        # Default Random Forest
        return RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42, **kwargs)


class ModelFactory:
    @staticmethod
    def get_model(model_type: str = "random_forest", **kwargs):
        return get_model(model_type, **kwargs)

    @staticmethod
    def create_model(model_type: str = "random_forest", **kwargs):
        return get_model(model_type, **kwargs)

    @staticmethod
    def evaluate_model(model, X: Any, y: Any) -> Dict[str, Any]:
        from sklearn.metrics import (
            accuracy_score,
            precision_score,
            recall_score,
            f1_score,
            roc_auc_score,
            brier_score_loss,
        )
        if len(y) == 0:
            return {"accuracy": 0.0, "f1Score": 0.0}

        y_pred = model.predict(X)

        acc = float(accuracy_score(y, y_pred))
        prec = float(precision_score(y, y_pred, zero_division=0))
        rec = float(recall_score(y, y_pred, zero_division=0))
        f1 = float(f1_score(y, y_pred, zero_division=0))

        auc = 0.5
        brier = 0.25
        if hasattr(model, "predict_proba"):
            try:
                y_proba = model.predict_proba(X)[:, 1]
                auc = float(roc_auc_score(y, y_proba))
                brier = float(brier_score_loss(y, y_proba))
            except Exception:
                auc = 0.5
                brier = 0.25

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


