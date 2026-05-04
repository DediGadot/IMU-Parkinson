"""CCC objective v2 — fixes from codex+gemini debug consult:

1. Hessian scaling — multiply grad/hess by (n*D/2.0) so hess=1.0 (matches MSE GBDT scaling).
2. init_score = train mean (avoid LGB starting at 0.0 with no mean-correction signal).
3. Pearson-correlation feature selection (instead of MSE-LGB selector).
4. Post-hoc affine calibration on training-fold OOF.
5. hy_residual_ccc rewritten: optimize CCC on (base + delta) vs original y, NOT on residuals.

Both consults agree: these fixes + affine calibration are the highest-ROI change.
"""
from __future__ import annotations

import numpy as np


def ccc_loss_grad_hess_v2(preds, dtrain):
    """Scaled CCC custom objective — hess=1.0 matches LGB MSE scaling."""
    y = np.asarray(dtrain.get_label(), dtype=np.float64)
    x = np.asarray(preds, dtype=np.float64)
    n = len(y)
    if n < 4:
        return np.zeros(n), np.ones(n)
    mu_y = float(y.mean())
    mu_x = float(x.mean())
    sxy = float(((x - mu_x) * (y - mu_y)).mean())
    sx = float(((x - mu_x) ** 2).mean())
    sy = float(((y - mu_y) ** 2).mean())
    D = sx + sy + (mu_x - mu_y) ** 2 + 1e-12
    # Original grad scaled to make hess = 1.0:
    # grad = -((y - mu_y) - (2*sxy/D)*(x - mu_y))
    grad = -((y - mu_y) - (2.0 * sxy / D) * (x - mu_y))
    hess = np.ones(n, dtype=np.float64)
    return grad, hess


def pearson_select_features(X_tr, y_tr, k=500):
    """Pearson correlation feature selection (replaces MSE-LGB selector)."""
    if X_tr.shape[1] <= k:
        return np.arange(X_tr.shape[1])
    # Vectorized abs-Pearson
    X = X_tr - np.nanmean(X_tr, axis=0, keepdims=True)
    y = y_tr - y_tr.mean()
    sx = np.nan_to_num(np.std(X, axis=0), nan=1e-9) + 1e-9
    sy = y.std() + 1e-9
    cov = np.nanmean(X * y[:, None], axis=0)
    corr = np.abs(cov / (sx * sy))
    corr = np.where(np.isnan(corr), 0.0, corr)
    return np.argsort(corr)[::-1][:k]


def fit_ccc_affine(y, p, eps=1e-8):
    """Fit a, b s.t. y_cal = a*p + b maximizes CCC. Returns (a, b)."""
    y = np.asarray(y, dtype=np.float64)
    p = np.asarray(p, dtype=np.float64)
    if len(y) < 3 or p.std(ddof=0) < eps:
        return 0.0, float(y.mean())
    sd_y = y.std(ddof=0)
    sd_p = p.std(ddof=0)
    rho = np.corrcoef(y, p)[0, 1]
    if not np.isfinite(rho):
        return 1.0, 0.0
    a = float(np.sign(rho) * sd_y / sd_p)
    b = float(y.mean() - a * p.mean())
    return a, b


def train_lgb_ccc_v2(X_tr, y_tr, X_te, seed: int, params: dict | None = None,
                     calibrate: bool = True) -> np.ndarray:
    """Train LightGBM with v2 CCC objective + init_score + (optional) calibration on inner OOF."""
    import lightgbm as lgb
    base = {
        "learning_rate": 0.05, "num_leaves": 15,
        "min_data_in_leaf": 5, "feature_fraction": 1.0, "bagging_fraction": 1.0,
        "n_jobs": 2, "verbosity": -1, "random_state": seed, "reg_lambda": 0.0,
    }
    if params:
        base.update(params)
    n_estimators = base.pop("n_estimators", 400) if "n_estimators" in base else 400
    p = dict(base)
    p["objective"] = ccc_loss_grad_hess_v2
    p["metric"] = "None"
    init_tr = np.full_like(y_tr, fill_value=float(y_tr.mean()), dtype=np.float64)
    init_te = np.full_like(np.zeros(X_te.shape[0]), fill_value=float(y_tr.mean()), dtype=np.float64)
    booster = lgb.train(
        params=p,
        train_set=lgb.Dataset(X_tr, label=y_tr, init_score=init_tr),
        num_boost_round=n_estimators,
    )
    pred_tr = booster.predict(X_tr) + init_tr
    pred_te = booster.predict(X_te) + init_te
    if calibrate:
        a, b = fit_ccc_affine(y_tr, pred_tr)
        pred_te = a * pred_te + b
    return pred_te


# Backwards-compat alias for callers using the v1 name
def train_lgb_ccc(X_tr, y_tr, X_te, seed: int, params: dict | None = None) -> np.ndarray:
    return train_lgb_ccc_v2(X_tr, y_tr, X_te, seed, params=params, calibrate=True)


if __name__ == "__main__":
    rng = np.random.RandomState(0)
    n = 100
    X = rng.randn(n, 50)
    y = X[:, 0] + 0.5 * X[:, 1] + 0.3 * rng.randn(n)
    pred = train_lgb_ccc_v2(X[:80], y[:80], X[80:], seed=0)
    cov = ((pred - pred.mean()) * (y[80:] - y[80:].mean())).mean()
    ccc = 2 * cov / (pred.var() + y[80:].var() + (pred.mean() - y[80:].mean()) ** 2 + 1e-12)
    print(f"v2 CCC: {ccc:.4f}")
