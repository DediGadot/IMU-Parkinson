"""T3 V2+PSI only — test if PSI alone (without GSP/stride/shapelet) lifts T3.

Motivation: comprehensive_aug (wall #36) showed PSI captured 30.5% of K=500
picks — high feature density. But the multi-block combination HURT. Test V2+PSI
alone to determine if PSI is genuinely informative or just K-selection noise.

Architecture: V2 + PSI unified K=500 univariate-corr, iter47-arch LOOCV.
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
PSI_CSV = REPO_ROOT / "results" / "v3_psi_features.csv"


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
    print("T3 V2+PSI only — isolate PSI signal at T3")
    print("=" * 72)

    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    feat_cols_v2 = data["feat_cols"]
    y = data["y_t3"]
    hy = data["hy"]
    clin_cols = [i for i, c in enumerate(feat_cols_v2) if c.startswith("cv_")]
    X_clinical = np.column_stack([hy, X_v2[:, clin_cols]]) if clin_cols else hy.reshape(-1, 1)

    psi_df = pd.read_csv(PSI_CSV)
    psi_lookup = {str(s): i for i, s in enumerate(psi_df["sid"].astype(str))}
    psi_cols = [c for c in psi_df.columns if c != "sid"]
    X_psi = np.full((len(sids), len(psi_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in psi_lookup:
            X_psi[i] = psi_df.iloc[psi_lookup[s]][psi_cols].to_numpy()
    print(f"  V2 dim={X_v2.shape[1]}, PSI dim={X_psi.shape[1]}")

    X_aug = np.column_stack([X_v2, X_psi])
    print(f"  Combined dim={X_aug.shape[1]}")

    base_preds_per_seed = []
    aug_preds_per_seed = []
    for seed in SEEDS:
        print(f"\n  === seed={seed} baseline ===", flush=True)
        p_base = run_loocv(X_v2, X_clinical, y, seed)
        m_base = full_metrics(y, p_base, label=f"baseline_seed{seed}")
        print(f"  baseline CCC={m_base['ccc']:.4f}", flush=True)
        base_preds_per_seed.append(p_base)

        print(f"\n  === seed={seed} V2+PSI ===", flush=True)
        p_aug = run_loocv(X_aug, X_clinical, y, seed)
        m_aug = full_metrics(y, p_aug, label=f"v2psi_seed{seed}")
        print(f"  V2+PSI CCC={m_aug['ccc']:.4f} Δ={m_aug['ccc']-m_base['ccc']:+.4f}", flush=True)
        aug_preds_per_seed.append(p_aug)

    p_base_mean = np.mean(base_preds_per_seed, axis=0)
    p_aug_mean = np.mean(aug_preds_per_seed, axis=0)
    m_base_pooled = full_metrics(y, p_base_mean, label="baseline_pooled")
    m_aug_pooled = full_metrics(y, p_aug_mean, label="v2psi_pooled")
    delta = m_aug_pooled["ccc"] - m_base_pooled["ccc"]
    seed_deltas = [ccc(y, a) - ccc(y, b) for a, b in zip(aug_preds_per_seed, base_preds_per_seed)]

    rng = np.random.RandomState(42)
    n_boot = 5000
    boot_deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, len(y), len(y))
        boot_deltas[b] = ccc(y[idx], p_aug_mean[idx]) - ccc(y[idx], p_base_mean[idx])
    frac_gt = float((boot_deltas > 0).mean())
    ci_lo = float(np.percentile(boot_deltas, 2.5))
    ci_hi = float(np.percentile(boot_deltas, 97.5))

    if delta >= 0.025 and frac_gt >= 0.95 and np.std(seed_deltas) < 0.020:
        verdict = "PASS_UNCORRECTED_CANDIDATE"
    elif delta >= 0.010:
        verdict = "MARGINAL_BELOW_MCID"
    else:
        verdict = "FAIL_NO_LIFT"

    summary = {
        "name": "t3_v2_psi_only",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_subjects": int(len(y)),
        "baseline_pooled": m_base_pooled,
        "v2psi_pooled": m_aug_pooled,
        "delta_pooled": round(delta, 4),
        "iter47_canonical": 0.3784,
        "per_seed_deltas": [round(d, 4) for d in seed_deltas],
        "seed_delta_mean": round(float(np.mean(seed_deltas)), 4),
        "seed_delta_std": round(float(np.std(seed_deltas)), 4),
        "paired_bootstrap": {
            "n_boot": n_boot,
            "frac_gt_zero": round(frac_gt, 4),
            "ci_low": round(ci_lo, 4),
            "ci_high": round(ci_hi, 4),
        },
        "verdict": verdict,
        "per_subject": {
            "sids": sids.tolist(),
            "y_true": y.tolist(),
            "y_pred_baseline_mean": p_base_mean.tolist(),
            "y_pred_v2psi_mean": p_aug_mean.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t3_v2_psi_only_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))

    print(f"\n  Baseline pooled CCC = {m_base_pooled['ccc']:.4f}")
    print(f"  V2+PSI pooled CCC = {m_aug_pooled['ccc']:.4f}")
    print(f"  Δ = {delta:+.4f}")
    print(f"  seed Δ: {seed_deltas}")
    print(f"  frac>0 = {frac_gt:.4f}")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out_path}")


if __name__ == "__main__":
    main()
