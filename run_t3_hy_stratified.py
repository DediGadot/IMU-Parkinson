"""T3 H&Y-stratified Stage-2 — train separate LGBs for low/high H&Y.

Hypothesis: T3 residual structure differs between mild (HY≤2.0) and moderate-
severe (HY>2.0) PD. Training a single LGB on all 95 subjects fits a
compromise model. Per-HY-stratum LGB may fit each subpopulation better;
combining predictions via the stratum membership.

Architecture:
  Stage-1: Ridge on H&Y + cv_yrs/cv_sex/cv_dbs (same as iter47).
  Stage-2 stratified:
    HY ≤ 2.0 subset: LGB on K=300 (smaller K due to smaller N≈60)
    HY > 2.0 subset: LGB on K=300 (N≈35)
  Per-fold: train both stratum-LGBs on outer-train, route outer-test
            to its HY-membership stratum-LGB.

If the stratification helps for SOME folds, the mean LOOCV may lift.
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

K_BEST = 300
SEEDS = (42, 1337, 7)
HY_THRESHOLD = 2.0


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
        n_estimators=500, learning_rate=0.05, num_leaves=10, min_data_in_leaf=8,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=3,
        verbose=-1, random_state=seed,
    ).fit(X_train, y_train)


def run_loocv_stratified(X, X_clin, hy, y, seed):
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

        hy_tr = hy[tr]
        hy_te = hy[te][0]
        low_mask = hy_tr <= HY_THRESHOLD
        high_mask = hy_tr > HY_THRESHOLD

        if hy_te <= HY_THRESHOLD:
            stratum_mask = low_mask
        else:
            stratum_mask = high_mask

        if stratum_mask.sum() < 10:
            # Fall back to global model if stratum too small
            sel = _univariate_kselect(X_tr_imp, resid_tr, K_BEST)
            m2 = _fit_lgb(X_tr_imp[:, sel], resid_tr, seed)
            preds[te[0]] = float(s1_te[0] + m2.predict(X_te_imp[:, sel])[0])
        else:
            X_strat = X_tr_imp[stratum_mask]
            resid_strat = resid_tr[stratum_mask]
            sel = _univariate_kselect(X_strat, resid_strat, K_BEST)
            m2 = _fit_lgb(X_strat[:, sel], resid_strat, seed)
            preds[te[0]] = float(s1_te[0] + m2.predict(X_te_imp[:, sel])[0])
        if (fold_idx + 1) % 20 == 0:
            print(f"  seed={seed} fold {fold_idx+1}/{n} elapsed={time.time()-t0:.1f}s", flush=True)
    return preds


def run_loocv_global(X, X_clin, y, seed, k_best=500):
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
    print("=" * 72)
    print("T3 H&Y-STRATIFIED Stage-2 — separate LGBs for HY low/high")
    print("=" * 72)

    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    y = data["y_t3"]
    hy = data["hy"]
    feat_cols_v2 = data["feat_cols"]
    clin_cols = [i for i, c in enumerate(feat_cols_v2) if c.startswith("cv_")]
    X_clinical = np.column_stack([hy, X_v2[:, clin_cols]]) if clin_cols else hy.reshape(-1, 1)
    low_n = int((hy <= HY_THRESHOLD).sum())
    high_n = int((hy > HY_THRESHOLD).sum())
    print(f"  N={len(sids)}, low_HY (≤{HY_THRESHOLD})={low_n}, high_HY (>{HY_THRESHOLD})={high_n}")

    base_preds_per_seed = []
    strat_preds_per_seed = []
    for seed in SEEDS:
        print(f"\n  === seed={seed} baseline (global K=500) ===", flush=True)
        p_base = run_loocv_global(X_v2, X_clinical, y, seed, k_best=500)
        m_base = full_metrics(y, p_base, label=f"baseline_seed{seed}")
        print(f"  baseline CCC={m_base['ccc']:.4f}", flush=True)
        base_preds_per_seed.append(p_base)

        print(f"\n  === seed={seed} stratified (HY-split K=300) ===", flush=True)
        p_strat = run_loocv_stratified(X_v2, X_clinical, hy, y, seed)
        m_strat = full_metrics(y, p_strat, label=f"stratified_seed{seed}")
        print(f"  stratified CCC={m_strat['ccc']:.4f} Δ={m_strat['ccc']-m_base['ccc']:+.4f}", flush=True)
        strat_preds_per_seed.append(p_strat)

    p_base_mean = np.mean(base_preds_per_seed, axis=0)
    p_strat_mean = np.mean(strat_preds_per_seed, axis=0)
    m_base_pooled = full_metrics(y, p_base_mean, label="baseline_pooled")
    m_strat_pooled = full_metrics(y, p_strat_mean, label="stratified_pooled")
    delta = m_strat_pooled["ccc"] - m_base_pooled["ccc"]
    seed_deltas = [ccc(y, a) - ccc(y, b) for a, b in zip(strat_preds_per_seed, base_preds_per_seed)]

    rng = np.random.RandomState(42)
    n_boot = 5000
    boot_deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, len(y), len(y))
        boot_deltas[b] = ccc(y[idx], p_strat_mean[idx]) - ccc(y[idx], p_base_mean[idx])
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
        "name": "t3_hy_stratified",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_subjects": int(len(y)),
        "hy_threshold": HY_THRESHOLD,
        "low_hy_n": low_n,
        "high_hy_n": high_n,
        "baseline_pooled": m_base_pooled,
        "stratified_pooled": m_strat_pooled,
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
            "y_pred_stratified_mean": p_strat_mean.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t3_hy_stratified_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))

    print(f"\n  Baseline pooled CCC = {m_base_pooled['ccc']:.4f}")
    print(f"  Stratified pooled CCC = {m_strat_pooled['ccc']:.4f}")
    print(f"  Δ = {delta:+.4f}")
    print(f"  Per-seed Δ: {seed_deltas}")
    print(f"  frac>0 = {frac_gt:.4f}")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out_path}")


if __name__ == "__main__":
    main()
