"""T3-B': Stride-locked subject-level features injected into iter47 Stage-2.

Hypothesis: Stride statistics (CV of stride duration, slope, first-last diff
of stance/swing across walks) capture stride irregularity not absorbed by
V2 K=500. Item-11 FoG and item-10 gait are observability-bounded by these
specific dynamics. Lift expected to be small but possibly real.

Note: This is NOT in the original FWER family — pre-registering as supplementary.
If clears uncorrected α=0.05, document as candidate; do not claim ceiling break
without FWER correction.

Architecture:
  Cohort: drop_allmissing_validrange, N=95.
  Stage-1: Ridge alpha=1 on H&Y + cv_yrs + cv_sex + cv_dbs.
  Stage-2: LGB on K=500 univariate-corr K-best from V2 + stride_locked_subj pool.
  Seeds: (42, 1337, 7), mean3 OOF.

Output: results/lockbox_t3_b_stride_loocv_<TS>.json
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


def run_loocv(X, X_clin, y, seed, label):
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
        sel = _univariate_kselect(X_tr_imp, resid_tr, K_BEST)
        m2 = _fit_lgb(X_tr_imp[:, sel], resid_tr, seed)
        preds[te[0]] = float(s1_te[0] + m2.predict(X_te_imp[:, sel])[0])
        if (fold_idx + 1) % 10 == 0:
            print(f"  {label} seed={seed} fold {fold_idx+1}/{n} elapsed={time.time()-t0:.1f}s", flush=True)
    return preds


def main():
    print("=" * 72)
    print("T3-B': Stride-locked features injected into iter47 Stage-2")
    print("=" * 72)

    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    feat_cols_v2 = data["feat_cols"]
    y = data["y_t3"]
    hy = data["hy"]
    clin_cols = [i for i, c in enumerate(feat_cols_v2) if c.startswith("cv_")]
    X_clinical = np.column_stack([hy, X_v2[:, clin_cols]]) if clin_cols else hy.reshape(-1, 1)
    print(f"  N={len(sids)}, V2 dim={X_v2.shape[1]}, clinical dim={X_clinical.shape[1]}")

    stride_df = pd.read_csv(STRIDE_CSV)
    stride_lookup = {str(s): i for i, s in enumerate(stride_df["sid"].astype(str))}
    stride_cols = [c for c in stride_df.columns if c != "sid"]
    X_stride = np.full((len(sids), len(stride_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in stride_lookup:
            X_stride[i] = stride_df.iloc[stride_lookup[s]][stride_cols].to_numpy()
    print(f"  stride dim={X_stride.shape}, missing rows={np.isnan(X_stride).all(axis=1).sum()}")

    X_aug = np.column_stack([X_v2, X_stride])
    print(f"  augmented dim={X_aug.shape}")

    base_seed_preds = []
    aug_seed_preds = []
    for seed in SEEDS:
        print(f"\n  === seed={seed} baseline ===", flush=True)
        p_base = run_loocv(X_v2, X_clinical, y, seed, "base")
        m_base = full_metrics(y, p_base, label=f"baseline_seed{seed}")
        print(f"  baseline CCC={m_base['ccc']:.4f}", flush=True)
        base_seed_preds.append(p_base)

        print(f"\n  === seed={seed} augmented (V2+stride) ===", flush=True)
        p_aug = run_loocv(X_aug, X_clinical, y, seed, "aug")
        m_aug = full_metrics(y, p_aug, label=f"augmented_seed{seed}")
        print(f"  augmented CCC={m_aug['ccc']:.4f} Δ={m_aug['ccc']-m_base['ccc']:+.4f}", flush=True)
        aug_seed_preds.append(p_aug)

    p_base_mean = np.mean(base_seed_preds, axis=0)
    p_aug_mean = np.mean(aug_seed_preds, axis=0)
    m_base_pooled = full_metrics(y, p_base_mean, label="baseline_pooled")
    m_aug_pooled = full_metrics(y, p_aug_mean, label="augmented_pooled")

    rng = np.random.RandomState(42)
    n_boot = 5000
    deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, len(y), len(y))
        deltas[b] = ccc(y[idx], p_aug_mean[idx]) - ccc(y[idx], p_base_mean[idx])
    mean_d = float(deltas.mean())
    ci_lo = float(np.percentile(deltas, 2.5))
    ci_hi = float(np.percentile(deltas, 97.5))
    frac_gt = float((deltas > 0).mean())

    seed_deltas = [
        full_metrics(y, a, label="aug")["ccc"] - full_metrics(y, b, label="base")["ccc"]
        for a, b in zip(aug_seed_preds, base_seed_preds)
    ]
    seed_mean = float(np.mean(seed_deltas))
    seed_std = float(np.std(seed_deltas))
    delta_pooled = m_aug_pooled["ccc"] - m_base_pooled["ccc"]

    if delta_pooled >= 0.025 and frac_gt >= 0.975:
        verdict = "PASS_UNCORRECTED_CANDIDATE"
    elif delta_pooled >= 0.010:
        verdict = "MARGINAL_BELOW_MCID"
    else:
        verdict = "FAIL_NO_LIFT"

    formula_sha = hashlib.sha256(
        json.dumps(
            {
                "cohort": "drop_allmissing_validrange",
                "k_best": K_BEST,
                "seeds": list(SEEDS),
                "stage1": "ridge_hy_cv",
                "stage2": "lgb_v2_stride_kbest",
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    summary = {
        "name": "t3_b_stride_loocv",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formula_sha256": formula_sha,
        "n_subjects": int(len(y)),
        "cohort": "drop_allmissing_validrange",
        "baseline_pooled": m_base_pooled,
        "augmented_pooled": m_aug_pooled,
        "delta_pooled_ccc": round(delta_pooled, 4),
        "iter47_canonical_ccc": 0.3784,
        "per_seed_deltas": [round(d, 4) for d in seed_deltas],
        "seed_delta_mean": round(seed_mean, 4),
        "seed_delta_std": round(seed_std, 4),
        "paired_bootstrap": {
            "n_boot": n_boot,
            "mean_delta": round(mean_d, 4),
            "ci_low": round(ci_lo, 4),
            "ci_high": round(ci_hi, 4),
            "frac_gt_zero": round(frac_gt, 4),
        },
        "verdict": verdict,
        "per_subject": {
            "sids": sids.tolist(),
            "y_true": y.tolist(),
            "y_pred_baseline": p_base_mean.tolist(),
            "y_pred_augmented": p_aug_mean.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t3_b_stride_loocv_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))
    oof_path = REPO_ROOT / "results" / f"lockbox_t3_b_stride_loocv_{ts}.oof.npy"
    np.save(oof_path, p_aug_mean)

    print(f"\n  === FINAL ===")
    print(f"  Baseline pooled CCC = {m_base_pooled['ccc']:.4f}")
    print(f"  Augmented pooled CCC = {m_aug_pooled['ccc']:.4f}")
    print(f"  Δ = {delta_pooled:+.4f}")
    print(f"  seed Δ: mean={seed_mean:+.4f}, std={seed_std:.4f}")
    print(f"  frac>0 = {frac_gt:.4f}")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out_path}")


if __name__ == "__main__":
    main()
