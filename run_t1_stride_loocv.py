"""T1-stride: stride-locked subject-level features injected into iter34 chain.

Hypothesis: Stride irregularity statistics (CV, slope, first-last diff of
stride/stance/swing duration across walking tasks) capture item-10 gait and
item-11 FoG dynamics that V2 may absorb but stride-specific features make
explicit. Apply as a Stage-3 RIDGE correction on iter34 T1 hybrid prediction.

Architecture (residual model, parallel to WILDCARD-A but with stride features
instead of GSP per-task):
  Outer LOOCV, N=92.
  Per fold:
    residual_train = y_t1_train - iter34_t1_sum_pred_train
    Inner 5-fold OOF Ridge on K=64 stride features (univariate-corr) → residual
    Outer-train refit Ridge predicts residual_test
  T1_new = clip(iter34_t1_sum_pred + 0.5 * ridge_residual_pred, 0, 24)

Pre-registered as supplementary to FWER family (NOT a Bonferroni n=2 member;
WILDCARD-A already burned that slot). Reportable as uncorrected candidate
if Δ ≥ +0.025 and frac>0 ≥ 0.975.
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
from sklearn.model_selection import KFold, LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldImputer, FoldNormalizer, full_metrics
from eval_utils import lins_ccc as ccc

ITER34_OOF_PATH = REPO_ROOT / "results" / "t1_iter34_per_item_oof_20260511_044242.npz"
STRIDE_CSV = REPO_ROOT / "results" / "stride_locked_subj.csv"
K_BEST = 64
ALPHA_RIDGE = 50.0
SHRINKAGE = 0.5
INNER_KFOLD = 5
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


def _fit_specialist(X_train, y_train, X_test):
    imp = FoldImputer.fit(X_train)
    X_train_imp = imp.transform(X_train)
    X_test_imp = imp.transform(X_test)
    sel = _univariate_kselect(X_train_imp, y_train, K_BEST)
    X_train_sel = X_train_imp[:, sel]
    X_test_sel = X_test_imp[:, sel]
    nrm = FoldNormalizer.fit(X_train_sel)
    X_train_n = nrm.transform(X_train_sel)
    X_test_n = nrm.transform(X_test_sel)
    m = Ridge(alpha=ALPHA_RIDGE, random_state=0)
    m.fit(X_train_n, y_train)
    return m.predict(X_train_n), m.predict(X_test_n)


def _inner_oof(X_train, y_train, n_splits, seed):
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    oof = np.zeros(len(y_train))
    for tr_idx, va_idx in kf.split(X_train):
        _, pred_va = _fit_specialist(X_train[tr_idx], y_train[tr_idx], X_train[va_idx])
        oof[va_idx] = pred_va
    return oof


def main():
    print("=" * 72)
    print("T1-STRIDE: stride-locked features → Ridge residual correction on iter34")
    print("=" * 72)

    d = np.load(ITER34_OOF_PATH, allow_pickle=True)
    sids = np.array([str(s) for s in d["sids"]])
    y_t1 = d["y_t1"]
    t1_baseline = d["t1_sum_pred"]
    print(f"  iter34 baseline N={len(sids)}, CCC={ccc(y_t1, t1_baseline):.4f}")
    residual = y_t1 - t1_baseline
    print(f"  residual: mean={residual.mean():.3f} std={residual.std():.3f}")

    stride_df = pd.read_csv(STRIDE_CSV)
    stride_lookup = {str(s): i for i, s in enumerate(stride_df["sid"].astype(str))}
    stride_cols = [c for c in stride_df.columns if c != "sid"]
    X_stride = np.full((len(sids), len(stride_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in stride_lookup:
            X_stride[i] = stride_df.iloc[stride_lookup[s]][stride_cols].to_numpy()
    missing = np.isnan(X_stride).all(axis=1).sum()
    print(f"  stride dim={X_stride.shape}, missing rows={missing}")

    all_seeds_correction = []
    for seed in SEEDS:
        print(f"\n  === seed={seed} ===", flush=True)
        residual_correction = np.zeros(len(sids))
        loo = LeaveOneOut()
        t0 = time.time()
        for fold_idx, (tr, te) in enumerate(loo.split(sids)):
            X_tr, X_te = X_stride[tr], X_stride[te]
            resid_tr = residual[tr]
            # Use single specialist (no per-task split — keep architecture simple)
            _, pred_te = _fit_specialist(X_tr, resid_tr, X_te)
            residual_correction[te[0]] = pred_te[0]
            if (fold_idx + 1) % 20 == 0:
                print(f"  seed={seed} fold {fold_idx+1}/{len(sids)} elapsed={time.time()-t0:.1f}s", flush=True)
        all_seeds_correction.append(residual_correction)

    mean_correction = np.mean(all_seeds_correction, axis=0)
    t1_new = np.clip(t1_baseline + SHRINKAGE * mean_correction, 0.0, 24.0)
    m_base = full_metrics(y_t1, t1_baseline, label="iter34_baseline")
    m_new = full_metrics(y_t1, t1_new, label="t1_stride_corrected")

    rng = np.random.RandomState(42)
    n_boot = 5000
    deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, len(y_t1), len(y_t1))
        deltas[b] = ccc(y_t1[idx], t1_new[idx]) - ccc(y_t1[idx], t1_baseline[idx])
    frac_gt = float((deltas > 0).mean())
    ci_lo = float(np.percentile(deltas, 2.5))
    ci_hi = float(np.percentile(deltas, 97.5))
    delta = m_new["ccc"] - m_base["ccc"]

    if delta >= 0.025 and frac_gt >= 0.975:
        verdict = "PASS_UNCORRECTED_CANDIDATE"
    elif delta >= 0.010:
        verdict = "MARGINAL_BELOW_MCID"
    else:
        verdict = "FAIL_NO_LIFT"

    formula_sha = hashlib.sha256(
        json.dumps(
            {
                "k_best": K_BEST,
                "alpha_ridge": ALPHA_RIDGE,
                "shrinkage": SHRINKAGE,
                "inner_kfold": INNER_KFOLD,
                "seeds": list(SEEDS),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    summary = {
        "name": "t1_stride_loocv",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formula_sha256": formula_sha,
        "n_subjects": int(len(y_t1)),
        "iter34_baseline_ccc": round(m_base["ccc"], 4),
        "t1_stride_corrected_ccc": round(m_new["ccc"], 4),
        "delta_ccc": round(delta, 4),
        "paired_bootstrap": {
            "n_boot": n_boot,
            "frac_gt_zero": round(frac_gt, 4),
            "ci_low": round(ci_lo, 4),
            "ci_high": round(ci_hi, 4),
        },
        "verdict": verdict,
        "per_subject": {
            "sids": sids.tolist(),
            "y_true": y_t1.tolist(),
            "y_pred_baseline": t1_baseline.tolist(),
            "y_pred_corrected": t1_new.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t1_stride_loocv_{ts}.json"
    oof_path = REPO_ROOT / "results" / f"lockbox_t1_stride_loocv_{ts}.oof.npy"
    out_path.write_text(json.dumps(summary, indent=2))
    np.save(oof_path, t1_new)

    print(f"\n  Baseline CCC = {m_base['ccc']:.4f}")
    print(f"  Corrected CCC = {m_new['ccc']:.4f}")
    print(f"  Δ = {delta:+.4f}")
    print(f"  frac>0 = {frac_gt:.4f}")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out_path}")


if __name__ == "__main__":
    main()
