"""Custom CCC-loss objective for LightGBM.

CCC = 2 * cov(y, yhat) / (var(y) + var(yhat) + (mean(y) - mean(yhat))^2)

Loss = 1 - CCC. Want to minimize.

Derivation of gradient (dL / dyhat_i):
  Let N = len(y), mu_y = mean(y), mu_x = mean(yhat),
      sx = var(yhat) = sum((x - mu_x)^2)/N
      sy = var(y) = sum((y - mu_y)^2)/N
      sxy = cov(y, yhat) = sum((x - mu_x)(y - mu_y))/N
      D = sx + sy + (mu_x - mu_y)^2
      CCC = 2*sxy / D

  d(sxy)/dx_i = (y_i - mu_y) / N
  d(sx)/dx_i = 2*(x_i - mu_x) / N
  d((mu_x - mu_y)^2)/dx_i = 2*(mu_x - mu_y) / N
  d(D)/dx_i = 2*(x_i - mu_x)/N + 2*(mu_x - mu_y)/N = 2*(x_i - mu_y)/N

  Quotient rule:
  d(CCC)/dx_i = (2*(y_i-mu_y)/N * D - 2*sxy * 2*(x_i-mu_y)/N) / D^2
              = (2/N) * ((y_i - mu_y)*D - 2*sxy*(x_i - mu_y)) / D^2

  d(L)/dx_i = -d(CCC)/dx_i

For hessian, we approximate via diagonal (heuristic): h_i ≈ 2/(N * D).
Empirically this works for small-N gradient boosting; LGB normalizes anyway.
"""
from __future__ import annotations

import numpy as np


def ccc_loss_grad_hess(preds: np.ndarray, dtrain) -> tuple:
    """LightGBM custom objective: returns (grad, hess).

    Args:
        preds: (N,) array of current predictions
        dtrain: lightgbm Dataset; we extract labels via dtrain.get_label()
    Returns:
        grad, hess: (N,) arrays
    """
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
    # gradient of CCC w.r.t. x_i
    dCCC_dx = (2.0 / n) * ((y - mu_y) * D - 2.0 * sxy * (x - mu_y)) / (D ** 2)
    # We're minimizing L = 1 - CCC, so grad = -dCCC/dx
    grad = -dCCC_dx
    # Diagonal hessian approx (heuristic, scales gradient steps)
    hess = np.full(n, 2.0 / (n * D), dtype=np.float64)
    return grad, hess


def ccc_eval_metric(preds: np.ndarray, dtrain) -> tuple:
    """LightGBM custom eval: returns (name, value, is_higher_better)."""
    y = np.asarray(dtrain.get_label(), dtype=np.float64)
    x = np.asarray(preds, dtype=np.float64)
    if y.std() < 1e-9 or x.std() < 1e-9:
        return ("ccc", 0.0, True)
    cov = float(((x - x.mean()) * (y - y.mean())).mean())
    ccc = (2 * cov) / (x.var() + y.var() + (x.mean() - y.mean()) ** 2 + 1e-12)
    return ("ccc", float(ccc), True)


def train_lgb_ccc(X_tr, y_tr, X_te, seed: int, params: dict | None = None) -> np.ndarray:
    """Train LightGBM with custom CCC objective. Returns OOF predictions on X_te."""
    import lightgbm as lgb
    base = {
        "n_estimators": 300, "learning_rate": 0.05, "num_leaves": 15,
        "min_data_in_leaf": 5, "feature_fraction": 0.8, "bagging_fraction": 0.9,
        "bagging_freq": 1, "n_jobs": 2, "verbosity": -1, "random_state": seed,
    }
    if params:
        base.update(params)
    p = dict(base)
    p["objective"] = ccc_loss_grad_hess
    p["metric"] = "None"  # disable default metric
    booster = lgb.train(
        params={k: v for k, v in p.items() if k not in ("n_estimators",)},
        train_set=lgb.Dataset(X_tr, label=y_tr),
        num_boost_round=base.get("n_estimators", 300),
    )
    pred = booster.predict(X_te)
    return pred


if __name__ == "__main__":
    # Quick test
    import lightgbm as lgb
    rng = np.random.RandomState(0)
    n = 100
    X = rng.randn(n, 20)
    y = X[:, 0] + 0.5 * X[:, 1] + 0.3 * rng.randn(n)
    pred = train_lgb_ccc(X[:80], y[:80], X[80:], seed=0)
    cov = ((pred - pred.mean()) * (y[80:] - y[80:].mean())).mean()
    ccc = 2 * cov / (pred.var() + y[80:].var() + (pred.mean() - y[80:].mean()) ** 2 + 1e-12)
    print(f"Test CCC: {ccc:.4f}")
