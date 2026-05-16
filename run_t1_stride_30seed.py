"""T1 stride 30-seed — parallel to T3 stride 30-seed.

The T3 stride 30-seed showed 25/30 positive seeds (binomial p≈10⁻⁵), Δ=+0.020.
Test if T1 (smaller range, items 9-14 axial) shows similar/stronger signal.

Architecture (residual-correction on iter34 hybrid):
  iter34 t1_sum_pred from `t1_iter34_per_item_oof_20260511_044242.npz` (CCC=0.7170)
  residual = y_t1 - iter34_t1_sum_pred
  Per-fold: Ridge α=50 on K=64 univariate-corr stride features → residual prediction
  T1_new = clip(iter34 + 0.5 * ridge_pred, 0, 24)
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

from inductive_lib import FoldImputer, FoldNormalizer, full_metrics
from eval_utils import lins_ccc as ccc

K_BEST = 64
ALPHA = 50.0
SHRINKAGE = 0.5
SEEDS = tuple(range(1, 31))
ITER34_OOF = REPO_ROOT / "results" / "t1_iter34_per_item_oof_20260511_044242.npz"
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


def run_loocv(X, residual, seed):
    n = len(residual)
    correction = np.zeros(n)
    loo = LeaveOneOut()
    for fold_idx, (tr, te) in enumerate(loo.split(X)):
        imp = FoldImputer.fit(X[tr])
        X_tr = imp.transform(X[tr])
        X_te = imp.transform(X[te])
        sel = _univariate_kselect(X_tr, residual[tr], K_BEST)
        nrm = FoldNormalizer.fit(X_tr[:, sel])
        X_tr_n = nrm.transform(X_tr[:, sel])
        X_te_n = nrm.transform(X_te[:, sel])
        m = Ridge(alpha=ALPHA, random_state=seed)
        m.fit(X_tr_n, residual[tr])
        correction[te[0]] = float(m.predict(X_te_n)[0])
    return correction


def main():
    print("=" * 72)
    print("T1 stride 30-seed — parallel to T3 stride 30-seed analysis")
    print("=" * 72)

    d = np.load(ITER34_OOF, allow_pickle=True)
    sids = np.array([str(s) for s in d["sids"]])
    y_t1 = d["y_t1"]
    t1_baseline = d["t1_sum_pred"]
    residual = y_t1 - t1_baseline
    print(f"  N={len(sids)}, baseline CCC={ccc(y_t1, t1_baseline):.4f}")

    stride_df = pd.read_csv(STRIDE_CSV)
    stride_lookup = {str(s): i for i, s in enumerate(stride_df["sid"].astype(str))}
    stride_cols = [c for c in stride_df.columns if c != "sid"]
    X_stride = np.full((len(sids), len(stride_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in stride_lookup:
            X_stride[i] = stride_df.iloc[stride_lookup[s]][stride_cols].to_numpy()
    print(f"  stride dim={X_stride.shape}")

    seed_corrections = []
    t0 = time.time()
    for seed_idx, seed in enumerate(SEEDS):
        c = run_loocv(X_stride, residual, seed)
        delta_seed = ccc(y_t1, np.clip(t1_baseline + SHRINKAGE * c, 0, 24)) - ccc(y_t1, t1_baseline)
        print(f"  seed {seed_idx+1}/30 = {seed}: Δ={delta_seed:+.4f} elapsed={time.time()-t0:.1f}s", flush=True)
        seed_corrections.append(c)

    mean_correction = np.mean(seed_corrections, axis=0)
    t1_new = np.clip(t1_baseline + SHRINKAGE * mean_correction, 0, 24)
    delta_pooled = ccc(y_t1, t1_new) - ccc(y_t1, t1_baseline)
    seed_deltas = [
        ccc(y_t1, np.clip(t1_baseline + SHRINKAGE * c, 0, 24)) - ccc(y_t1, t1_baseline)
        for c in seed_corrections
    ]

    n_positive = int(sum(1 for d in seed_deltas if d > 0))
    n_above_mcid = int(sum(1 for d in seed_deltas if d >= 0.025))

    rng = np.random.RandomState(42)
    n_boot = 5000
    boot_deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, len(y_t1), len(y_t1))
        boot_deltas[b] = ccc(y_t1[idx], t1_new[idx]) - ccc(y_t1[idx], t1_baseline[idx])
    frac_gt = float((boot_deltas > 0).mean())

    if np.mean(seed_deltas) >= 0.025 and frac_gt >= 0.95:
        verdict = "PASS_CANDIDATE"
    elif np.mean(seed_deltas) >= 0.010:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"

    summary = {
        "name": "t1_stride_30seed",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_seeds": len(SEEDS),
        "per_seed_deltas": [round(d, 4) for d in seed_deltas],
        "seed_delta_mean": round(float(np.mean(seed_deltas)), 4),
        "seed_delta_std": round(float(np.std(seed_deltas)), 4),
        "seed_delta_median": round(float(np.median(seed_deltas)), 4),
        "pooled_delta": round(delta_pooled, 4),
        "n_positive": n_positive,
        "n_above_mcid": n_above_mcid,
        "frac_gt_zero_bootstrap": round(frac_gt, 4),
        "iter34_baseline_ccc": round(float(ccc(y_t1, t1_baseline)), 4),
        "stride_corrected_ccc": round(float(ccc(y_t1, t1_new)), 4),
        "verdict": verdict,
        "per_subject": {
            "sids": sids.tolist(), "y_true": y_t1.tolist(),
            "y_pred_baseline": t1_baseline.tolist(),
            "y_pred_corrected": t1_new.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t1_stride_30seed_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))

    print(f"\n  Mean Δ = {np.mean(seed_deltas):+.4f}, std = {np.std(seed_deltas):.4f}")
    print(f"  Pooled Δ = {delta_pooled:+.4f}")
    print(f"  Positive seeds: {n_positive}/30, above-MCID: {n_above_mcid}/30")
    print(f"  frac>0 = {frac_gt:.4f}")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out_path}")


if __name__ == "__main__":
    main()
