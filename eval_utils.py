"""Shared evaluation utilities for PD-IMU experiments.

Canonical implementations of metrics, feature selection, and bootstrap
statistics. Import from here instead of re-implementing in each script.
"""

import os

import numpy as np

N_CORES = min(os.cpu_count() or 4, 11)


def lins_ccc(y_true, y_pred):
    """Lin's concordance correlation coefficient.

    Handles NaN/Inf values and degenerate inputs (< 3 samples).
    """
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    y_true, y_pred = y_true[mask], y_pred[mask]
    if len(y_true) < 3:
        return 0.0
    mu_t, mu_p = np.mean(y_true), np.mean(y_pred)
    var_t, var_p = np.var(y_true), np.var(y_pred)
    cov = np.mean((y_true - mu_t) * (y_pred - mu_p))
    denom = var_t + var_p + (mu_t - mu_p) ** 2
    return float(2 * cov / denom) if denom > 1e-12 else 0.0


def cal_slope(y_true, y_pred):
    """Calibration slope: linear regression of predicted on true.

    Ideal value is 1.0. Values < 1 indicate regression to the mean.
    """
    if np.std(y_true) < 1e-8 or len(y_true) < 3:
        return 0.0
    return float(np.polyfit(y_true, y_pred, 1)[0])


def calibration_slope_intercept(y_true, y_pred):
    """Full calibration: slope + intercept. Ideal: slope=1, intercept=0."""
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    if len(y_true) < 3:
        return 1.0, 0.0
    slope, intercept = np.polyfit(y_true, y_pred, 1)
    return float(slope), float(intercept)


def feature_select(X, y, names, k=150, fs_params=None):
    """XGB importance-based feature selection.

    Fits XGBRegressor on all data, returns top-k features by importance.

    Args:
        X: Feature matrix (n_samples, n_features).
        y: Target vector (n_samples,).
        names: Feature name list.
        k: Number of top features to select.
        fs_params: Optional dict to override XGB hyperparameters.

    Returns:
        (indices, names): Tuple of selected feature indices and names.
    """
    from xgboost import XGBRegressor

    k = min(k, X.shape[1])
    params = {
        "n_estimators": 300,
        "max_depth": 4,
        "learning_rate": 0.05,
        "reg_lambda": 2.0,
        "random_state": 42,
        "n_jobs": N_CORES,
        "objective": "reg:absoluteerror",
    }
    if fs_params:
        params.update(fs_params)
    sel = XGBRegressor(**params)
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def bootstrap_ci(y_true, y_pred, metric_fn, n_boot=2000, alpha=0.05, seed=42):
    """Bootstrap confidence interval for any metric function.

    Args:
        y_true, y_pred: Arrays of true and predicted values.
        metric_fn: Callable(y_true, y_pred) -> float.
        n_boot: Number of bootstrap iterations.
        alpha: Significance level (0.05 = 95% CI).
        seed: Random seed for reproducibility.

    Returns:
        (lower, upper): CI bounds.
    """
    rng = np.random.RandomState(seed)
    n = len(y_true)
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    vals = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        vals[b] = metric_fn(y_true[idx], y_pred[idx])
    lo = np.percentile(vals, 100 * alpha / 2)
    hi = np.percentile(vals, 100 * (1 - alpha / 2))
    return float(lo), float(hi)


def subject_paired_bootstrap(errors_a, errors_b, n_boot=10000, seed=42):
    """Subject-level paired bootstrap for MAE difference.

    Returns: (mean_diff, ci_lo, ci_hi, p_value_two_sided).
    """
    errors_a, errors_b = np.asarray(errors_a), np.asarray(errors_b)
    rng = np.random.RandomState(seed)
    n = len(errors_a)
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.choice(n, n, replace=True)
        diffs[b] = np.mean(errors_a[idx]) - np.mean(errors_b[idx])
    mean_diff = float(np.mean(diffs))
    ci_lo = float(np.percentile(diffs, 2.5))
    ci_hi = float(np.percentile(diffs, 97.5))
    if mean_diff < 0:
        p_val = float(np.mean(diffs >= 0))
    else:
        p_val = float(np.mean(diffs <= 0))
    p_val = min(2 * p_val, 1.0)
    return mean_diff, ci_lo, ci_hi, p_val


def cohens_d(errors_a, errors_b):
    """Cohen's d effect size for paired samples."""
    diff = np.asarray(errors_a) - np.asarray(errors_b)
    return float(np.mean(diff) / (np.std(diff, ddof=1) + 1e-12))
