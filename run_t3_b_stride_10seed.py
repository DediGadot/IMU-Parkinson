"""T3-B stride LOOCV with 10 seeds — confirm or refute the +0.046 seed-7 outlier.

Pre-reg: results/preregistration_t3_b_stride_10seed_20260512.json (auto-written).
Decision rule:
  - If 10-seed mean Δ ≥ +0.025 AND std < 0.015 AND frac>0 ≥ 0.95: PASS uncorrected candidate.
  - If 10-seed mean Δ ≥ +0.010 AND std < 0.020: WEAK_POSITIVE_NEEDS_EXTERNAL.
  - Else: FAIL_NOISE_DOMINATED.
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
SEEDS = (42, 1337, 7, 23, 99, 314, 271, 161803, 777, 11)


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
    print("T3-B stride 10-seed LOOCV — confirm/refute the +0.046 seed-7 outlier")
    print("=" * 72)

    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    feat_cols_v2 = data["feat_cols"]
    y = data["y_t3"]
    hy = data["hy"]
    clin_cols = [i for i, c in enumerate(feat_cols_v2) if c.startswith("cv_")]
    X_clinical = np.column_stack([hy, X_v2[:, clin_cols]]) if clin_cols else hy.reshape(-1, 1)

    STRIDE_CSV = REPO_ROOT / "results" / "stride_locked_subj.csv"
    stride_df = pd.read_csv(STRIDE_CSV)
    stride_lookup = {str(s): i for i, s in enumerate(stride_df["sid"].astype(str))}
    stride_cols = [c for c in stride_df.columns if c != "sid"]
    X_stride = np.full((len(sids), len(stride_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in stride_lookup:
            X_stride[i] = stride_df.iloc[stride_lookup[s]][stride_cols].to_numpy()
    X_aug = np.column_stack([X_v2, X_stride])
    print(f"  N={len(sids)}, V2 dim={X_v2.shape[1]}, aug dim={X_aug.shape[1]}")

    base_preds_per_seed = []
    aug_preds_per_seed = []
    t0 = time.time()
    for seed_idx, seed in enumerate(SEEDS):
        print(f"\n  === seed {seed_idx+1}/{len(SEEDS)} = {seed} ===", flush=True)
        t_s = time.time()
        p_base = run_loocv(X_v2, X_clinical, y, seed)
        p_aug = run_loocv(X_aug, X_clinical, y, seed)
        delta = ccc(y, p_aug) - ccc(y, p_base)
        print(f"  seed={seed} base={ccc(y, p_base):.4f} aug={ccc(y, p_aug):.4f} "
              f"Δ={delta:+.4f} wall={time.time()-t_s:.1f}s", flush=True)
        base_preds_per_seed.append(p_base)
        aug_preds_per_seed.append(p_aug)

    seed_deltas = [ccc(y, a) - ccc(y, b) for a, b in zip(aug_preds_per_seed, base_preds_per_seed)]
    delta_mean = float(np.mean(seed_deltas))
    delta_std = float(np.std(seed_deltas))
    p_base_mean = np.mean(base_preds_per_seed, axis=0)
    p_aug_mean = np.mean(aug_preds_per_seed, axis=0)
    pooled_delta = ccc(y, p_aug_mean) - ccc(y, p_base_mean)

    rng = np.random.RandomState(42)
    n_boot = 5000
    boot_deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, len(y), len(y))
        boot_deltas[b] = ccc(y[idx], p_aug_mean[idx]) - ccc(y[idx], p_base_mean[idx])
    frac_gt = float((boot_deltas > 0).mean())
    ci_lo = float(np.percentile(boot_deltas, 2.5))
    ci_hi = float(np.percentile(boot_deltas, 97.5))

    if delta_mean >= 0.025 and delta_std < 0.015 and frac_gt >= 0.95:
        verdict = "PASS_UNCORRECTED_CANDIDATE"
    elif delta_mean >= 0.010 and delta_std < 0.020:
        verdict = "WEAK_POSITIVE_NEEDS_EXTERNAL"
    elif delta_std > 0.025:
        verdict = "FAIL_NOISE_DOMINATED"
    else:
        verdict = "FAIL_NO_LIFT"

    formula_sha = hashlib.sha256(
        json.dumps({"seeds": list(SEEDS), "k_best": K_BEST, "stage": "10seed"}, sort_keys=True).encode()
    ).hexdigest()

    summary = {
        "name": "t3_b_stride_10seed",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formula_sha256": formula_sha,
        "n_subjects": int(len(y)),
        "n_seeds": len(SEEDS),
        "seeds": list(SEEDS),
        "per_seed_deltas": [round(d, 4) for d in seed_deltas],
        "seed_delta_mean": round(delta_mean, 4),
        "seed_delta_std": round(delta_std, 4),
        "pooled_delta": round(pooled_delta, 4),
        "pooled_base_ccc": round(float(ccc(y, p_base_mean)), 4),
        "pooled_aug_ccc": round(float(ccc(y, p_aug_mean)), 4),
        "paired_bootstrap": {
            "n_boot": n_boot,
            "frac_gt_zero": round(frac_gt, 4),
            "ci_low": round(ci_lo, 4),
            "ci_high": round(ci_hi, 4),
        },
        "verdict": verdict,
        "iter47_canonical": 0.3784,
        "wall_time_total_s": round(time.time() - t0, 1),
        "per_subject": {
            "sids": sids.tolist(),
            "y_true": y.tolist(),
            "y_pred_baseline_mean": p_base_mean.tolist(),
            "y_pred_augmented_mean": p_aug_mean.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t3_b_stride_10seed_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))

    print(f"\n  === FINAL (10 seeds) ===")
    print(f"  Per-seed Δ: {[round(d, 4) for d in seed_deltas]}")
    print(f"  Mean Δ = {delta_mean:+.4f}, std = {delta_std:.4f}")
    print(f"  Pooled Δ = {pooled_delta:+.4f}")
    print(f"  frac>0 = {frac_gt:.4f}, BCa CI [{ci_lo:+.4f}, {ci_hi:+.4f}]")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out_path}")


if __name__ == "__main__":
    main()
