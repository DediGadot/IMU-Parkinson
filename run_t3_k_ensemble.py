"""T3 K-ensemble — train at multiple K values, ensemble predictions.

Hypothesis: K=500 absorbs noise at N=95. K=100, 200, 300 each give different
subset selections. Ensembling across K may smooth out K-dependence and lift
T3 baseline.

Architecture:
  For each K in {100, 200, 300, 500}: train iter47-arch LOOCV, get OOF preds.
  Ensemble = MEAN of 4 K-variant OOF preds.
  Compare to iter47 canonical K=500.
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

K_VALUES = (100, 200, 300, 500)
SEED = 42


def _univariate_kselect(X, y, k):
    if X.shape[1] <= k:
        return np.arange(X.shape[1])
    y_c = y - y.mean()
    X_c = X - X.mean(axis=0)
    Xs = X.std(axis=0) + 1e-9
    ys = y.std() + 1e-9
    corr = (X_c * y_c[:, None]).sum(axis=0) / ((Xs * ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]


def _fit_lgb(X_train, y_train, seed):
    from lightgbm import LGBMRegressor
    return LGBMRegressor(
        n_estimators=500, learning_rate=0.05, num_leaves=15, min_data_in_leaf=10,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=3,
        verbose=-1, random_state=seed,
    ).fit(X_train, y_train)


def run_loocv(X, X_clin, y, seed, k_best):
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
        sel = _univariate_kselect(X_tr_imp, resid_tr, k_best)
        m2 = _fit_lgb(X_tr_imp[:, sel], resid_tr, seed)
        preds[te[0]] = float(s1_te[0] + m2.predict(X_te_imp[:, sel])[0])
    return preds


def main():
    print("T3 K-ensemble (univariate-corr K-best at multiple K values)")
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    y = data["y_t3"]
    hy = data["hy"]
    feat_cols_v2 = data["feat_cols"]
    clin_cols = [i for i, c in enumerate(feat_cols_v2) if c.startswith("cv_")]
    X_clinical = np.column_stack([hy, X_v2[:, clin_cols]]) if clin_cols else hy.reshape(-1, 1)
    print(f"  N={len(sids)}")

    preds_by_k = {}
    for k in K_VALUES:
        print(f"  K={k}...", flush=True)
        preds_by_k[k] = run_loocv(X_v2, X_clinical, y, SEED, k)
        m = full_metrics(y, preds_by_k[k], label=f"K={k}")
        print(f"    K={k} CCC={m['ccc']:.4f}", flush=True)

    # Ensemble: mean of all K-variants
    ens = np.mean(list(preds_by_k.values()), axis=0)
    m_ens = full_metrics(y, ens, label="ensemble")
    print(f"\n  Ensemble (mean of K=100/200/300/500): CCC={m_ens['ccc']:.4f}")
    print(f"  Δ vs iter47 canonical (0.3784): {m_ens['ccc'] - 0.3784:+.4f}")

    summary = {
        "name": "t3_k_ensemble",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "K_values": list(K_VALUES),
        "ccc_per_k": {str(k): float(ccc(y, p)) for k, p in preds_by_k.items()},
        "ensemble_ccc": float(m_ens["ccc"]),
        "iter47_canonical": 0.3784,
        "delta_vs_iter47": round(float(m_ens["ccc"] - 0.3784), 4),
        "per_subject": {
            "sids": sids.tolist(), "y_true": y.tolist(),
            "y_pred_per_k": {str(k): p.tolist() for k, p in preds_by_k.items()},
            "y_pred_ensemble": ens.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO_ROOT / "results" / f"lockbox_t3_k_ensemble_{ts}.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"  Wrote {out}")


if __name__ == "__main__":
    main()
