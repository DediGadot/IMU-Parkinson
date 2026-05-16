"""T3 RandomForest base — different base learner than LGB for Stage-2 residual.

Hypothesis: LGB's tree splits at N=95 may over-aggregate noise. RandomForest with
many shallow trees, no boosting, may be more robust.

Architecture (iter47-ish):
  Stage-1: Ridge alpha=1 on H&Y+cv_*
  Stage-2: RandomForest(n=300, max_depth=4) on K=500 univariate-corr features
  Cohort: drop_allmissing_validrange, N=95. Seeds (42, 1337, 7).
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
from sklearn.ensemble import RandomForestRegressor
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


def run_loocv_rf(X, X_clin, y, seed):
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
        rf = RandomForestRegressor(
            n_estimators=300, max_depth=4, min_samples_leaf=5,
            max_features="sqrt", random_state=seed, n_jobs=-1,
        )
        rf.fit(X_tr_imp[:, sel], resid_tr)
        preds[te[0]] = float(s1_te[0] + rf.predict(X_te_imp[:, sel])[0])
    return preds


def main():
    print("T3 RandomForest base learner — alternative to LGB")
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    y = data["y_t3"]
    hy = data["hy"]
    feat_cols_v2 = data["feat_cols"]
    clin_cols = [i for i, c in enumerate(feat_cols_v2) if c.startswith("cv_")]
    X_clinical = np.column_stack([hy, X_v2[:, clin_cols]]) if clin_cols else hy.reshape(-1, 1)
    print(f"  N={len(sids)}")

    seed_preds = []
    t0 = time.time()
    for seed in SEEDS:
        p = run_loocv_rf(X_v2, X_clinical, y, seed)
        m = full_metrics(y, p, label=f"rf_seed{seed}")
        print(f"  seed={seed} CCC={m['ccc']:.4f} elapsed={time.time()-t0:.1f}s", flush=True)
        seed_preds.append(p)

    p_mean = np.mean(seed_preds, axis=0)
    metrics = full_metrics(y, p_mean, label="rf_pooled")
    summary = {
        "name": "t3_rf_base",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "metrics_pooled": metrics,
        "iter47_canonical": 0.3784,
        "delta_vs_iter47": round(metrics["ccc"] - 0.3784, 4),
        "per_subject": {
            "sids": sids.tolist(), "y_true": y.tolist(),
            "y_pred_pooled": p_mean.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO_ROOT / "results" / f"lockbox_t3_rf_base_{ts}.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"  Pooled CCC = {metrics['ccc']:.4f}, Δ vs iter47 = {summary['delta_vs_iter47']:+.4f}")
    print(f"  Wrote {out}")


if __name__ == "__main__":
    main()
