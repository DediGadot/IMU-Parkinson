"""T3 LGB-importance K-best + stride — apples-to-apples vs iter47 canonical.

Hypothesis: my univariate-corr K-best produced +0.024 architectural drift over
iter47 (LGB-importance K-best). The stride lift at 30-seed used my arch (+0.020
within-arch). Apples-to-apples test: use iter47-canonical LGB-importance K-best
with stride augmentation. If lift survives, it's a real signal at the canonical
architecture.

Architecture (matches iter47 EXACTLY):
  Stage-1: Ridge alpha=1 on H&Y + cv_yrs + cv_sex + cv_dbs.
  Stage-2 K-selection: LightGBM regressor n_estimators=200, lr=0.1, num_leaves=15,
                       min_data=5 fitted on residual; feature_importances_ ranking.
                       K=500 top.
  Stage-2 LGB on selected K=500: iter47 hyperparameters.
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
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldImputer, full_metrics
from eval_utils import lins_ccc as ccc
from run_t3_iter47_invalid_code_fix import filter_cohort

K_BEST = 500
SEEDS = (42, 1337, 7)
STRIDE_CSV = REPO_ROOT / "results" / "stride_locked_subj.csv"


def _lgb_importance_kselect(X, y, k, seed):
    if X.shape[1] <= k:
        return np.arange(X.shape[1])
    from lightgbm import LGBMRegressor
    sel = LGBMRegressor(
        n_estimators=200, learning_rate=0.1, num_leaves=15,
        min_data_in_leaf=5, verbose=-1, random_state=seed,
    )
    sel.fit(X, y)
    imp = sel.feature_importances_
    return np.argsort(-imp)[:k]


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
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(loo.split(X)):
        m1 = Ridge(alpha=1.0)
        m1.fit(X_clin[tr], y[tr])
        s1_tr = m1.predict(X_clin[tr])
        s1_te = m1.predict(X_clin[te])
        resid_tr = y[tr] - s1_tr
        imp = FoldImputer.fit(X[tr])
        X_tr_imp = imp.transform(X[tr])
        X_te_imp = imp.transform(X[te])
        sel = _lgb_importance_kselect(X_tr_imp, resid_tr, K_BEST, seed)
        m2 = _fit_lgb(X_tr_imp[:, sel], resid_tr, seed)
        preds[te[0]] = float(s1_te[0] + m2.predict(X_te_imp[:, sel])[0])
        if (fold_idx + 1) % 20 == 0:
            print(f"  seed={seed} fold {fold_idx+1}/{n} elapsed={time.time()-t0:.1f}s", flush=True)
    return preds


def main():
    print("=" * 72)
    print("T3 LGB-importance K-best + stride — apples-to-apples vs iter47")
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
    print(f"  N={len(sids)}, V2 dim={X_v2.shape[1]}, aug dim={X_aug.shape[1]}")
    print(f"  Stage-1 dim={X_clinical.shape[1]}")

    base_preds_per_seed = []
    aug_preds_per_seed = []
    for seed in SEEDS:
        print(f"\n  === seed={seed} baseline V2 (LGB-importance K=500) ===", flush=True)
        p_base = run_loocv(X_v2, X_clinical, y, seed)
        m_base = full_metrics(y, p_base, label=f"baseline_seed{seed}")
        print(f"  baseline CCC={m_base['ccc']:.4f}", flush=True)
        base_preds_per_seed.append(p_base)

        print(f"\n  === seed={seed} V2+stride (LGB-importance K=500) ===", flush=True)
        p_aug = run_loocv(X_aug, X_clinical, y, seed)
        m_aug = full_metrics(y, p_aug, label=f"aug_seed{seed}")
        print(f"  aug CCC={m_aug['ccc']:.4f} Δ={m_aug['ccc']-m_base['ccc']:+.4f}", flush=True)
        aug_preds_per_seed.append(p_aug)

    p_base_mean = np.mean(base_preds_per_seed, axis=0)
    p_aug_mean = np.mean(aug_preds_per_seed, axis=0)
    m_base_pooled = full_metrics(y, p_base_mean, label="baseline_pooled")
    m_aug_pooled = full_metrics(y, p_aug_mean, label="aug_pooled")
    delta = m_aug_pooled["ccc"] - m_base_pooled["ccc"]
    seed_deltas = [ccc(y, a) - ccc(y, b) for a, b in zip(aug_preds_per_seed, base_preds_per_seed)]

    rng = np.random.RandomState(42)
    n_boot = 5000
    boot_deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, len(y), len(y))
        boot_deltas[b] = ccc(y[idx], p_aug_mean[idx]) - ccc(y[idx], p_base_mean[idx])
    frac_gt = float((boot_deltas > 0).mean())

    summary = {
        "name": "t3_lgbimp_kbest_stride",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "kbest_method": "LGB-importance (iter47 canonical)",
        "baseline_pooled": m_base_pooled,
        "aug_pooled": m_aug_pooled,
        "delta_pooled": round(delta, 4),
        "iter47_canonical_ccc_expected": 0.3784,
        "per_seed_deltas": [round(d, 4) for d in seed_deltas],
        "seed_delta_mean": round(float(np.mean(seed_deltas)), 4),
        "seed_delta_std": round(float(np.std(seed_deltas)), 4),
        "paired_bootstrap_frac_gt_zero": round(frac_gt, 4),
        "verdict": "PASS" if delta >= 0.025 and frac_gt >= 0.95 else "MARGINAL" if delta >= 0.010 else "FAIL",
        "per_subject": {
            "sids": sids.tolist(), "y_true": y.tolist(),
            "y_pred_baseline_mean": p_base_mean.tolist(),
            "y_pred_aug_mean": p_aug_mean.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t3_lgbimp_kbest_stride_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))

    print(f"\n  Baseline (LGB-imp K=500) CCC = {m_base_pooled['ccc']:.4f}")
    print(f"  V2+stride (LGB-imp K=500) CCC = {m_aug_pooled['ccc']:.4f}")
    print(f"  Δ = {delta:+.4f}")
    print(f"  Per-seed: {seed_deltas}")
    print(f"  frac>0 = {frac_gt:.4f}")
    print(f"  Verdict: {summary['verdict']}")
    print(f"  Wrote {out_path}")


if __name__ == "__main__":
    main()
