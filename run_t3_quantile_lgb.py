"""T3 quantile LightGBM — predict median instead of mean for robust regression.

Hypothesis: T3 errors are heavy-tailed (some subjects produce large residuals).
Quantile loss at α=0.5 (median) is robust to outliers vs L2 loss (mean).
Smaller variance in predictions may yield better CCC.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldImputer, full_metrics
from eval_utils import lins_ccc as ccc
from run_t3_iter47_invalid_code_fix import filter_cohort

K_BEST = 500
SEEDS = (42, 1337, 7)


def _univariate_kselect(X, y, k):
    if X.shape[1] <= k:
        return np.arange(X.shape[1])
    y_c = y - y.mean()
    X_c = X - X.mean(axis=0)
    Xs = X.std(axis=0) + 1e-9
    ys = y.std() + 1e-9
    corr = (X_c * y_c[:, None]).sum(axis=0) / ((Xs * ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]


def _fit_lgb(X_train, y_train, seed, objective="regression"):
    from lightgbm import LGBMRegressor
    params = dict(
        n_estimators=500, learning_rate=0.05, num_leaves=15, min_data_in_leaf=10,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=3,
        verbose=-1, random_state=seed, objective=objective,
    )
    if objective == "quantile":
        params["alpha"] = 0.5
    return LGBMRegressor(**params).fit(X_train, y_train)


def run_loocv(X, X_clin, y, seed, objective):
    n = len(y)
    preds = np.zeros(n)
    loo = LeaveOneOut()
    for fold_idx, (tr, te) in enumerate(loo.split(X)):
        m1 = Ridge(alpha=1.0)
        m1.fit(X_clin[tr], y[tr])
        s1_tr = m1.predict(X_clin[tr])
        s1_te = m1.predict(X_clin[te])
        resid_tr = y[tr] - s1_tr
        imp = FoldImputer.fit(X[tr])
        X_tr_imp = imp.transform(X[tr])
        X_te_imp = imp.transform(X[te])
        sel = _univariate_kselect(X_tr_imp, resid_tr, K_BEST)
        m2 = _fit_lgb(X_tr_imp[:, sel], resid_tr, seed, objective=objective)
        preds[te[0]] = float(s1_te[0] + m2.predict(X_te_imp[:, sel])[0])
    return preds


def main():
    print("T3 quantile LightGBM (L1/quantile vs L2 regression)")
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    y = data["y_t3"]
    hy = data["hy"]
    feat_cols_v2 = data["feat_cols"]
    clin_cols = [i for i, c in enumerate(feat_cols_v2) if c.startswith("cv_")]
    X_clinical = np.column_stack([hy, X_v2[:, clin_cols]]) if clin_cols else hy.reshape(-1, 1)

    results_by_objective = {}
    for obj in ("regression", "quantile", "huber"):
        print(f"\n  === objective: {obj} ===", flush=True)
        seed_preds = []
        for seed in SEEDS:
            try:
                p = run_loocv(X_v2, X_clinical, y, seed, obj)
            except Exception as e:
                print(f"  seed={seed} {obj} failed: {e}", flush=True)
                continue
            m = full_metrics(y, p, label=f"{obj}_seed{seed}")
            print(f"  {obj} seed={seed} CCC={m['ccc']:.4f}", flush=True)
            seed_preds.append(p)
        if not seed_preds:
            continue
        p_mean = np.mean(seed_preds, axis=0)
        m_pooled = full_metrics(y, p_mean, label=f"{obj}_pooled")
        results_by_objective[obj] = {
            "ccc": float(m_pooled["ccc"]),
            "mae": float(m_pooled["mae"]),
        }

    summary = {
        "name": "t3_quantile_lgb",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "iter47_canonical_ccc": 0.3784,
        "results_by_objective": results_by_objective,
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO_ROOT / "results" / f"lockbox_t3_quantile_lgb_{ts}.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"\n  results: {results_by_objective}")
    print(f"  Wrote {out}")


if __name__ == "__main__":
    main()
