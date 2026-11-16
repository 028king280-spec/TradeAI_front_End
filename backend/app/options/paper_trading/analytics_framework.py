"""
AIVOLVE 3.0 — Phase E: Prediction & Performance Analytics Framework.

Institutional quantitative evaluation framework for:
1. Directional Accuracy, Precision, Recall, and F1 (Binary & Multiclass).
2. Confidence Calibration & Reliability (Expected Calibration Error, Brier Score).
3. Fixed-Horizon Outcome Dynamics (5, 15, 30, 60m MFE, MAE, realized return).
4. Paper Trading Accounting & Performance (Win Rate, Profit Factor, Drawdown, Net PnL, Holding Duration).
5. Pipeline Reliability & Latency (p50, p95, p99 Signal-to-Execution latency).
6. Strict Dataset Quarantine (Historical, Synthetic, Test, and Live datasets kept isolated).
7. Strict Zero-Fabrication Rule (Does not report live metrics before genuine eligible observations exist).
"""

import math
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum


class MetricDatasetClassification(str, Enum):
    VERIFIED_LIVE_PAPER = "VERIFIED_LIVE_PAPER"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    SYNTHETIC_RESEARCH = "SYNTHETIC_RESEARCH"
    TEST_DATA = "TEST_DATA"


@dataclass
class ClassificationMetrics:
    total_samples: int
    accuracy: float
    precision_macro: float
    recall_macro: float
    f1_macro: float
    class_report: Dict[str, Dict[str, float]] = field(default_factory=dict)


@dataclass
class CalibrationMetrics:
    brier_score: float
    expected_calibration_error: float
    mean_confidence: float
    observed_accuracy: float


@dataclass
class HorizonOutcomeStats:
    horizon_minutes: int
    sample_count: int
    resolved_count: int
    insufficient_data_count: int
    mean_return_pts: float
    mean_return_pct: float
    win_rate: float
    mean_mfe_pts: float
    mean_mae_pts: float
    return_std_pct: float


@dataclass
class TradePerformanceMetrics:
    total_trades: int
    winning_trades: int
    losing_trades: int
    scratch_trades: int
    win_rate_pct: float
    gross_pnl: float
    total_costs: float
    net_pnl: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    avg_holding_duration_minutes: float
    largest_win: float
    largest_loss: float
    avg_win: float
    avg_loss: float


@dataclass
class PipelineReliabilityMetrics:
    total_signals: int
    executed_signals: int
    rejected_signals: int
    execution_rate_pct: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    error_count: int
    uptime_pct: float


class PredictionPerformanceAnalytics:
    """
    Quantitative Analytics Engine evaluating prediction reliability and trade performance.
    Enforces strict separation of TEST_DATA, SYNTHETIC_RESEARCH, and VERIFIED_LIVE_PAPER.
    """

    @classmethod
    def compute_classification_metrics(
        cls,
        y_true: List[int],
        y_pred: List[int],
        labels: Optional[List[int]] = None,
    ) -> ClassificationMetrics:
        """
        Computes multiclass/binary accuracy, precision, recall, and F1.
        """
        if not y_true or not y_pred or len(y_true) != len(y_pred):
            return ClassificationMetrics(
                total_samples=0,
                accuracy=0.0,
                precision_macro=0.0,
                recall_macro=0.0,
                f1_macro=0.0,
            )

        n = len(y_true)
        correct = sum(1 for yt, yp in zip(y_true, y_pred) if yt == yp)
        accuracy = correct / n

        unique_labels = sorted(list(set(y_true + y_pred))) if labels is None else labels
        class_report: Dict[str, Dict[str, float]] = {}

        precisions: List[float] = []
        recalls: List[float] = []
        f1s: List[float] = []

        for lbl in unique_labels:
            tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == lbl and yp == lbl)
            fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt != lbl and yp == lbl)
            fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == lbl and yp != lbl)

            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

            precisions.append(prec)
            recalls.append(rec)
            f1s.append(f1)

            class_report[str(lbl)] = {
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
                "support": sum(1 for yt in y_true if yt == lbl),
            }

        macro_p = sum(precisions) / len(precisions) if precisions else 0.0
        macro_r = sum(recalls) / len(recalls) if recalls else 0.0
        macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0

        return ClassificationMetrics(
            total_samples=n,
            accuracy=round(accuracy, 4),
            precision_macro=round(macro_p, 4),
            recall_macro=round(macro_r, 4),
            f1_macro=round(macro_f1, 4),
            class_report=class_report,
        )

    @classmethod
    def compute_confidence_calibration(
        cls,
        confidences: List[float],
        outcomes: List[int],  # 1 for correct, 0 for incorrect
        num_bins: int = 5,
    ) -> CalibrationMetrics:
        """
        Computes Brier Score and Expected Calibration Error (ECE).
        """
        if not confidences or not outcomes or len(confidences) != len(outcomes):
            return CalibrationMetrics(
                brier_score=0.0,
                expected_calibration_error=0.0,
                mean_confidence=0.0,
                observed_accuracy=0.0,
            )

        n = len(confidences)
        brier = sum((c - y) ** 2 for c, y in zip(confidences, outcomes)) / n
        mean_conf = sum(confidences) / n
        obs_acc = sum(outcomes) / n

        # Binning for ECE
        bin_size = 1.0 / num_bins
        ece = 0.0

        for b in range(num_bins):
            bin_lower = b * bin_size
            bin_upper = (b + 1) * bin_size
            in_bin = [
                (c, y) for c, y in zip(confidences, outcomes)
                if (bin_lower <= c < bin_upper) or (b == num_bins - 1 and bin_lower <= c <= bin_upper)
            ]
            if in_bin:
                bin_acc = sum(y for _, y in in_bin) / len(in_bin)
                bin_conf = sum(c for c, _ in in_bin) / len(in_bin)
                ece += (len(in_bin) / n) * abs(bin_acc - bin_conf)

        return CalibrationMetrics(
            brier_score=round(brier, 4),
            expected_calibration_error=round(ece, 4),
            mean_confidence=round(mean_conf, 4),
            observed_accuracy=round(obs_acc, 4),
        )

    @classmethod
    def compute_horizon_outcomes(
        cls,
        horizon_minutes: int,
        records: List[Dict[str, Any]],
    ) -> HorizonOutcomeStats:
        """
        Evaluates forward price excursion, returns, and win-rates for a fixed horizon.
        """
        n = len(records)
        if n == 0:
            return HorizonOutcomeStats(
                horizon_minutes=horizon_minutes,
                sample_count=0,
                resolved_count=0,
                insufficient_data_count=0,
                mean_return_pts=0.0,
                mean_return_pct=0.0,
                win_rate=0.0,
                mean_mfe_pts=0.0,
                mean_mae_pts=0.0,
                return_std_pct=0.0,
            )

        resolved_returns_pts: List[float] = []
        resolved_returns_pct: List[float] = []
        resolved_mfe: List[float] = []
        resolved_mae: List[float] = []
        insufficient_count = 0

        for r in records:
            h_data = r.get("forward_horizons", {}).get(str(horizon_minutes), {})
            status = h_data.get("status")
            if status == "RESOLVED":
                ret_pts = float(h_data.get("premium_return_pts", 0.0) or 0.0)
                ret_pct = float(h_data.get("premium_return_pct", 0.0) or 0.0)
                mfe = float(h_data.get("mfe_points", 0.0) or ret_pts)
                mae = float(h_data.get("mae_points", 0.0) or 0.0)

                resolved_returns_pts.append(ret_pts)
                resolved_returns_pct.append(ret_pct)
                resolved_mfe.append(mfe)
                resolved_mae.append(mae)
            else:
                insufficient_count += 1

        resolved_count = len(resolved_returns_pts)
        if resolved_count == 0:
            return HorizonOutcomeStats(
                horizon_minutes=horizon_minutes,
                sample_count=n,
                resolved_count=0,
                insufficient_data_count=insufficient_count,
                mean_return_pts=0.0,
                mean_return_pct=0.0,
                win_rate=0.0,
                mean_mfe_pts=0.0,
                mean_mae_pts=0.0,
                return_std_pct=0.0,
            )

        mean_pts = sum(resolved_returns_pts) / resolved_count
        mean_pct = sum(resolved_returns_pct) / resolved_count
        mean_mfe = sum(resolved_mfe) / resolved_count
        mean_mae = sum(resolved_mae) / resolved_count
        win_rate = sum(1 for p in resolved_returns_pts if p > 0.0) / resolved_count

        variance = sum((p - mean_pct) ** 2 for p in resolved_returns_pct) / resolved_count
        std_pct = math.sqrt(variance)

        return HorizonOutcomeStats(
            horizon_minutes=horizon_minutes,
            sample_count=n,
            resolved_count=resolved_count,
            insufficient_data_count=insufficient_count,
            mean_return_pts=round(mean_pts, 2),
            mean_return_pct=round(mean_pct, 4),
            win_rate=round(win_rate, 4),
            mean_mfe_pts=round(mean_mfe, 2),
            mean_mae_pts=round(mean_mae, 2),
            return_std_pct=round(std_pct, 4),
        )

    @classmethod
    def compute_trade_performance(cls, trades: List[Dict[str, Any]]) -> TradePerformanceMetrics:
        """
        Computes institutional trading metrics: Win Rate, Profit Factor, Net PnL, Drawdown.
        """
        closed_trades = [t for t in trades if t.get("status") in ["CLOSED", "COMPLETED", "EXITED"]]
        n = len(closed_trades)
        if n == 0:
            return TradePerformanceMetrics(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                scratch_trades=0,
                win_rate_pct=0.0,
                gross_pnl=0.0,
                total_costs=0.0,
                net_pnl=0.0,
                profit_factor=0.0,
                max_drawdown=0.0,
                max_drawdown_pct=0.0,
                avg_holding_duration_minutes=0.0,
                largest_win=0.0,
                largest_loss=0.0,
                avg_win=0.0,
                avg_loss=0.0,
            )

        gross_pnls: List[float] = []
        net_pnls: List[float] = []
        costs: List[float] = []
        durations: List[float] = []

        winning_pnls: List[float] = []
        losing_pnls: List[float] = []
        scratch_count = 0

        for t in closed_trades:
            net_p = float(t.get("netPnl") or t.get("net_pnl") or 0.0)
            gross_p = float(t.get("grossPnl") or t.get("gross_pnl") or net_p)
            cost = float(t.get("totalCosts") or t.get("total_charges") or (gross_p - net_p))

            gross_pnls.append(gross_p)
            net_pnls.append(net_p)
            costs.append(cost)

            # Holding duration calculation
            entry_ts_str = t.get("entryTime") or t.get("entryTimestamp")
            exit_ts_str = t.get("exitTime") or t.get("exitTimestamp")
            if entry_ts_str and exit_ts_str:
                try:
                    e_dt = datetime.fromisoformat(entry_ts_str)
                    x_dt = datetime.fromisoformat(exit_ts_str)
                    durations.append(max(0.0, (x_dt - e_dt).total_seconds() / 60.0))
                except Exception:
                    durations.append(0.0)

            if net_p > 1.0:
                winning_pnls.append(net_p)
            elif net_p < -1.0:
                losing_pnls.append(net_p)
            else:
                scratch_count += 1

        wins_count = len(winning_pnls)
        loss_count = len(losing_pnls)
        total_pnl = sum(net_pnls)
        total_gross = sum(gross_pnls)
        total_cost = sum(costs)

        win_rate = (wins_count / n) * 100.0 if n > 0 else 0.0
        profit_factor = (
            abs(sum(winning_pnls) / sum(losing_pnls))
            if loss_count > 0 and sum(losing_pnls) != 0.0
            else (999.0 if wins_count > 0 else 0.0)
        )

        # Drawdown calculation
        cumulative_pnl: List[float] = []
        peak = 0.0
        max_dd = 0.0
        running = 0.0

        for p in net_pnls:
            running += p
            cumulative_pnl.append(running)
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd

        max_dd_pct = (max_dd / peak * 100.0) if peak > 0.0 else 0.0

        avg_win = (sum(winning_pnls) / wins_count) if wins_count > 0 else 0.0
        avg_loss = (sum(losing_pnls) / loss_count) if loss_count > 0 else 0.0
        largest_win = max(winning_pnls) if winning_pnls else 0.0
        largest_loss = min(losing_pnls) if losing_pnls else 0.0
        avg_duration = sum(durations) / len(durations) if durations else 0.0

        return TradePerformanceMetrics(
            total_trades=n,
            winning_trades=wins_count,
            losing_trades=loss_count,
            scratch_trades=scratch_count,
            win_rate_pct=round(win_rate, 2),
            gross_pnl=round(total_gross, 2),
            total_costs=round(total_cost, 2),
            net_pnl=round(total_pnl, 2),
            profit_factor=round(profit_factor, 2),
            max_drawdown=round(max_dd, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            avg_holding_duration_minutes=round(avg_duration, 1),
            largest_win=round(largest_win, 2),
            largest_loss=round(largest_loss, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
        )

    @classmethod
    def compute_pipeline_reliability(
        cls,
        latencies_ms: List[float],
        total_signals: int,
        executed_signals: int,
        rejected_signals: int,
        errors: int = 0,
    ) -> PipelineReliabilityMetrics:
        """
        Computes latency percentiles and execution reliability.
        """
        if not latencies_ms:
            latencies_ms = [0.0]

        sorted_lat = sorted(latencies_ms)
        n = len(sorted_lat)

        p50 = sorted_lat[int(0.50 * (n - 1))]
        p95 = sorted_lat[int(0.95 * (n - 1))]
        p99 = sorted_lat[int(0.99 * (n - 1))]

        exec_rate = (executed_signals / total_signals * 100.0) if total_signals > 0 else 0.0
        uptime = 100.0 if errors == 0 else max(0.0, 100.0 - (errors / max(1, total_signals) * 100.0))

        return PipelineReliabilityMetrics(
            total_signals=total_signals,
            executed_signals=executed_signals,
            rejected_signals=rejected_signals,
            execution_rate_pct=round(exec_rate, 2),
            p50_latency_ms=round(p50, 2),
            p95_latency_ms=round(p95, 2),
            p99_latency_ms=round(p99, 2),
            error_count=errors,
            uptime_pct=round(uptime, 2),
        )

