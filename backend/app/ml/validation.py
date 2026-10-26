from typing import Tuple, List, Generator
import pandas as pd
import numpy as np


class TimeSeriesSplitter:
    """
    Guarantees strict chronological ordering for train, validation, and test splits.
    Prohibits random shuffling to prevent lookahead bias in financial time-series.
    """

    @staticmethod
    def train_val_test_split(
        X: pd.DataFrame,
        y: pd.Series,
        train_pct: float = 0.65,
        val_pct: float = 0.20
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series]:
        n = len(X)
        train_end = int(n * train_pct)
        val_end = int(n * (train_pct + val_pct))

        X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
        X_val, y_val = X.iloc[train_end:val_end], y.iloc[train_end:val_end]
        X_test, y_test = X.iloc[val_end:], y.iloc[val_end:]

        return X_train, X_val, X_test, y_train, y_val, y_test

    @staticmethod
    def walk_forward_folds(
        X: pd.DataFrame,
        y: pd.Series,
        n_splits: int = 3,
        test_size: int = 20
    ) -> Generator[Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series], None, None]:
        """
        Expanding-window walk-forward cross validation.
        """
        n = len(X)
        for i in range(n_splits):
            split_idx = n - (n_splits - i) * test_size
            if split_idx <= 20:
                continue
            X_tr, y_tr = X.iloc[:split_idx], y.iloc[:split_idx]
            X_te, y_te = X.iloc[split_idx:split_idx + test_size], y.iloc[split_idx:split_idx + test_size]
            yield X_tr, X_te, y_tr, y_te
