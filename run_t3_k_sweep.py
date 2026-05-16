"""T3 K-sweep — test K=100, K=200, K=300 for stride augmentation.

Hypothesis: at N=95 with K=500 univariate-corr, the bottom 200-400 features in
the K=500 selection are noise. Smaller K may reduce noise allocation and let
stride features have higher signal-density.

Test K ∈ {100, 200, 300, 500} for V2+stride aug vs V2-only baseline.
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
    print("T3 K-sweep: K ∈ {100, 200, 300, 500} for V2+stride aug")
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    y = data["y_t3"]
    hy = data["hy"]
    feat_cols_v2 = data["feat_cols"]
    clin_cols = [i for i, c in enumerate(feat_cols_v2) if c.startswith("cv_")]
    X_clinical = np.column_stack([hy, X_v2[:, clin_cols]]) if clin_cols else hy.reshape(-1, 1)

    stride_df = pd.read_csv(REPO_ROOT / "results" / "stride_locked_subj.csv")
    stride_lookup = {str(s): i for i, s in enumerate(stride_df["sid"].astype(str))}
    stride_cols = [c for c in stride_df.columns if c != "sid"]
    X_stride = np.full((len(sids), len(stride_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in stride_lookup:
            X_stride[i] = stride_df.iloc[stride_lookup[s]][stride_cols].to_numpy()
    X_aug = np.column_stack([X_v2, X_stride])

    results_by_k = {}
    for k_best in K_VALUES:
        print(f"\n  ==== K={k_best} ====", flush=True)
        base_preds = []
        aug_preds = []
        for seed in SEEDS:
            p_base = run_loocv(X_v2, X_clinical, y, seed, k_best)
            p_aug = run_loocv(X_aug, X_clinical, y, seed, k_best)
            delta = ccc(y, p_aug) - ccc(y, p_base)
            print(f"  K={k_best} seed={seed}: base={ccc(y, p_base):.4f} aug={ccc(y, p_aug):.4f} Δ={delta:+.4f}", flush=True)
            base_preds.append(p_base)
            aug_preds.append(p_aug)
        p_base_mean = np.mean(base_preds, axis=0)
        p_aug_mean = np.mean(aug_preds, axis=0)
        delta_pooled = ccc(y, p_aug_mean) - ccc(y, p_base_mean)
        seed_deltas = [ccc(y, a) - ccc(y, b) for a, b in zip(aug_preds, base_preds)]
        results_by_k[k_best] = {
            "k": k_best,
            "base_pooled_ccc": round(float(ccc(y, p_base_mean)), 4),
            "aug_pooled_ccc": round(float(ccc(y, p_aug_mean)), 4),
            "delta_pooled": round(delta_pooled, 4),
            "seed_delta_mean": round(float(np.mean(seed_deltas)), 4),
            "seed_delta_std": round(float(np.std(seed_deltas)), 4),
            "per_seed_deltas": [round(d, 4) for d in seed_deltas],
        }

    # Find best K
    best_k = max(K_VALUES, key=lambda k: results_by_k[k]["delta_pooled"])

    summary = {
        "name": "t3_k_sweep_stride",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "results_by_k": results_by_k,
        "best_k": best_k,
        "best_delta": results_by_k[best_k]["delta_pooled"],
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO_ROOT / "results" / f"lockbox_t3_k_sweep_{ts}.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"\n  Best K = {best_k} with Δ = {results_by_k[best_k]['delta_pooled']:+.4f}")
    print(f"  Wrote {out}")


if __name__ == "__main__":
    main()
