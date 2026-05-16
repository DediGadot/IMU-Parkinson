"""T3 100-seed median ensemble — variance reduction at scale.

The T3 stride 30-seed showed +0.020 mean with 25/30 positive seeds. If the
underlying signal is +0.020 and the per-seed noise is normally distributed,
then 100-seed MEAN drives down the sampling variance by √(100/30)≈1.83×.
But 100-seed MEDIAN is more robust to outliers (the -0.045 outlier seed).

Hypothesis: median of 100 seeds (V2+stride aug) - median of 100 seeds (V2 base)
gives a cleaner Δ estimate. Test if median ≥ +0.025.

WALL TIME: ~100 seeds × 2 conditions × N=95 ≈ 30 min on remote.
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
SEEDS = tuple(range(1, 101))  # 100 seeds
STRIDE_CSV = REPO_ROOT / "results" / "stride_locked_subj.csv"


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


def run_loocv(X, X_clin, y, seed):
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
        m2 = _fit_lgb(X_tr_imp[:, sel], resid_tr, seed)
        preds[te[0]] = float(s1_te[0] + m2.predict(X_te_imp[:, sel])[0])
    return preds


def main():
    print("=" * 72)
    print("T3 100-SEED MEDIAN ENSEMBLE — variance reduction test")
    print("=" * 72)

    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    y = data["y_t3"]
    hy = data["hy"]
    feat_cols_v2 = data["feat_cols"]
    clin_cols = [i for i, c in enumerate(feat_cols_v2) if c.startswith("cv_")]
    X_clinical = np.column_stack([hy, X_v2[:, clin_cols]]) if clin_cols else hy.reshape(-1, 1)

    stride_df = pd.read_csv(STRIDE_CSV)
    stride_lookup = {str(s): i for i, s in enumerate(stride_df["sid"].astype(str))}
    stride_cols = [c for c in stride_df.columns if c != "sid"]
    X_stride = np.full((len(sids), len(stride_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in stride_lookup:
            X_stride[i] = stride_df.iloc[stride_lookup[s]][stride_cols].to_numpy()
    X_aug = np.column_stack([X_v2, X_stride])
    print(f"  N={len(sids)}, aug dim={X_aug.shape[1]}")

    base_preds_per_seed = []
    aug_preds_per_seed = []
    t0 = time.time()
    for seed_idx, seed in enumerate(SEEDS):
        p_base = run_loocv(X_v2, X_clinical, y, seed)
        p_aug = run_loocv(X_aug, X_clinical, y, seed)
        delta = ccc(y, p_aug) - ccc(y, p_base)
        if (seed_idx + 1) % 10 == 0:
            print(f"  seed {seed_idx+1}/100 = {seed}: Δ={delta:+.4f} elapsed={time.time()-t0:.1f}s", flush=True)
        base_preds_per_seed.append(p_base)
        aug_preds_per_seed.append(p_aug)

    seed_deltas = [ccc(y, a) - ccc(y, b) for a, b in zip(aug_preds_per_seed, base_preds_per_seed)]
    delta_mean = float(np.mean(seed_deltas))
    delta_median = float(np.median(seed_deltas))
    delta_std = float(np.std(seed_deltas))

    # Median ensemble per-subject (more robust than mean)
    p_base_median = np.median(base_preds_per_seed, axis=0)
    p_aug_median = np.median(aug_preds_per_seed, axis=0)
    pooled_median_delta = ccc(y, p_aug_median) - ccc(y, p_base_median)

    p_base_mean = np.mean(base_preds_per_seed, axis=0)
    p_aug_mean = np.mean(aug_preds_per_seed, axis=0)
    pooled_mean_delta = ccc(y, p_aug_mean) - ccc(y, p_base_mean)

    n_positive = int(sum(1 for d in seed_deltas if d > 0))
    n_above_mcid = int(sum(1 for d in seed_deltas if d >= 0.025))

    rng = np.random.RandomState(42)
    n_boot = 5000
    boot_deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, len(y), len(y))
        boot_deltas[b] = ccc(y[idx], p_aug_mean[idx]) - ccc(y[idx], p_base_mean[idx])
    frac_gt = float((boot_deltas > 0).mean())

    if delta_mean >= 0.025 and frac_gt >= 0.95:
        verdict = "PASS"
    elif delta_mean >= 0.015:
        verdict = "WEAK_POSITIVE"
    else:
        verdict = "FAIL"

    summary = {
        "name": "t3_100seed_median",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_seeds": len(SEEDS),
        "per_seed_deltas": [round(d, 4) for d in seed_deltas],
        "seed_delta_mean": round(delta_mean, 4),
        "seed_delta_std": round(delta_std, 4),
        "seed_delta_median": round(delta_median, 4),
        "pooled_mean_delta": round(pooled_mean_delta, 4),
        "pooled_median_delta": round(pooled_median_delta, 4),
        "n_positive": n_positive,
        "n_above_mcid": n_above_mcid,
        "frac_gt_bootstrap": round(frac_gt, 4),
        "base_pooled_mean_ccc": round(float(ccc(y, p_base_mean)), 4),
        "aug_pooled_mean_ccc": round(float(ccc(y, p_aug_mean)), 4),
        "base_pooled_median_ccc": round(float(ccc(y, p_base_median)), 4),
        "aug_pooled_median_ccc": round(float(ccc(y, p_aug_median)), 4),
        "verdict": verdict,
        "wall_time_s": round(time.time() - t0, 1),
        "per_subject": {
            "sids": sids.tolist(), "y_true": y.tolist(),
            "y_pred_base_mean": p_base_mean.tolist(),
            "y_pred_aug_mean": p_aug_mean.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO_ROOT / "results" / f"lockbox_t3_100seed_median_{ts}.json"
    out.write_text(json.dumps(summary, indent=2))

    print(f"\n  === FINAL (100 seeds) ===")
    print(f"  seed Δ: mean={delta_mean:+.4f}, std={delta_std:.4f}, median={delta_median:+.4f}")
    print(f"  pooled-mean Δ: {pooled_mean_delta:+.4f}")
    print(f"  pooled-median Δ: {pooled_median_delta:+.4f}")
    print(f"  positive: {n_positive}/100, above-MCID: {n_above_mcid}/100")
    print(f"  frac>0 = {frac_gt:.4f}")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out}")


if __name__ == "__main__":
    main()
