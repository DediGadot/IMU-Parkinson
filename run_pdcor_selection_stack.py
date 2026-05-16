"""Test whether pdCor-based selection on V2 itself adds ΔCCC over iter34.

Hypothesis: iter34's K=500 LGB-importance selection leaves measurable pdCor signal
on the table within V2 (we already confirmed 126 V2 columns have pdCor>0.10 against
y_t1 | yhat_iter34_oof).

Test: build a Ridge meta-stack trained on canonical-OOF *residuals*, using ONLY
V2 columns whose pdCor exceeds a threshold (selected per-fold, inductively).

Compare downstream ΔCCC vs iter34 OOF baseline.

This is a STAKEHOLDER-DEFINING experiment:
  - If it works: step-function moves are in SELECTION RULE design, not in new features
  - If it fails: iter34 is fully exploiting V2's extractable signal and we must invest
    in new feature extraction beyond V2.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from metric_lib import load_t1_canonical_oof, load_t3_canonical_oof, partial_distance_correlation
from inductive_lib import FoldImputer, FoldNormalizer, full_metrics


def fold_local_pdcor_selection(
    V2_all: np.ndarray, y: np.ndarray, yhat_oof: np.ndarray,
    pdcor_threshold: float = 0.10, max_k: int = 200,
) -> tuple[np.ndarray, list[int]]:
    """For one outer fold's training data, score V2 columns by pdCor.

    Returns the K selected column indices.
    """
    n, p = V2_all.shape
    pdcors = np.zeros(p)
    for j in range(p):
        try:
            pdcors[j] = partial_distance_correlation(V2_all[:, j], y, yhat_oof)
        except Exception:
            pdcors[j] = 0.0
    # Mask candidate columns
    mask = pdcors > pdcor_threshold
    selected = np.where(mask)[0]
    # Cap at max_k by pdCor magnitude
    if len(selected) > max_k:
        rank = np.argsort(pdcors[selected])[::-1][:max_k]
        selected = selected[rank]
    return pdcors, list(selected.tolist())


def loocv_pdcor_stack(target: str = "t1", threshold: float = 0.10, max_k: int = 200, alpha: float = 10.0) -> dict:
    """Leave-one-out: for each test subject i, fit pdCor selector on training-only,
    fit Ridge meta on canonical-OOF residuals with selected V2 columns, predict
    correction for subject i, add to yhat[i].
    """
    if target == "t1":
        sids, y, yhat_oof = load_t1_canonical_oof()
    else:
        sids, y, yhat_oof = load_t3_canonical_oof()

    df = pd.read_csv("results/ablation_v3_features.csv")
    drop_cols = {"sid", "updrs3", "hy", "obs_subscore"}
    feat_cols = [c for c in df.columns if c not in drop_cols]
    df_idx = df.set_index(df["sid"].astype(str))
    V2 = np.array([df_idx.loc[str(s), feat_cols].to_numpy(np.float64) for s in sids])
    col_med = np.nanmedian(V2, axis=0)
    inds = np.where(np.isnan(V2))
    V2[inds] = np.take(col_med, inds[1])
    n, p = V2.shape

    print(f"[pdcor_stack] target={target} N={n} V2_dim={p} threshold={threshold} max_k={max_k} alpha={alpha}", flush=True)

    # Per-fold pdCor selection + Ridge stack
    residual = y - yhat_oof
    correction = np.zeros(n)
    selected_counts = []
    pdcors_per_fold = []

    t0 = time.time()
    for i in range(n):
        if i % 10 == 0:
            print(f"  fold {i}/{n} ({time.time()-t0:.0f}s)", flush=True)
        mask_train = np.arange(n) != i
        V2_tr = V2[mask_train]
        y_tr = y[mask_train]
        yhat_oof_tr = yhat_oof[mask_train]

        # Fold-local pdCor selection
        pdcors, sel = fold_local_pdcor_selection(V2_tr, y_tr, yhat_oof_tr, threshold, max_k)
        pdcors_per_fold.append(pdcors)
        selected_counts.append(len(sel))
        if len(sel) == 0:
            continue

        F_tr = V2_tr[:, sel]
        F_te = V2[i:i+1, sel]
        # Per-fold impute + normalize
        imp = FoldImputer.fit(F_tr)
        F_tr = imp.transform(F_tr)
        F_te = imp.transform(F_te)
        norm = FoldNormalizer.fit(F_tr)
        F_tr = norm.transform(F_tr)
        F_te = norm.transform(F_te)
        # Train Ridge meta on residuals
        ridge = Ridge(alpha=alpha, random_state=42)
        ridge.fit(F_tr, residual[mask_train])
        correction[i] = float(ridge.predict(F_te)[0])

    yhat_stacked = yhat_oof + correction
    baseline_metrics = full_metrics(y, yhat_oof, label="canonical_OOF")
    stacked_metrics = full_metrics(y, yhat_stacked, label="canonical_OOF_plus_pdcor_selection")

    # Bootstrap ΔCCC
    rng = np.random.RandomState(42)
    deltas = []
    for _ in range(2000):
        idx = rng.randint(0, n, n)
        from eval_utils import lins_ccc
        d = lins_ccc(y[idx], yhat_stacked[idx]) - lins_ccc(y[idx], yhat_oof[idx])
        deltas.append(d)
    deltas = np.array(deltas)

    result = {
        "target": target,
        "threshold": threshold,
        "max_k": max_k,
        "ridge_alpha": alpha,
        "N": n,
        "baseline": baseline_metrics,
        "stacked": stacked_metrics,
        "delta_ccc": float(stacked_metrics["ccc"] - baseline_metrics["ccc"]),
        "delta_ccc_bootstrap_median": float(np.median(deltas)),
        "delta_ccc_bootstrap_ci_lower": float(np.quantile(deltas, 0.025)),
        "delta_ccc_bootstrap_ci_upper": float(np.quantile(deltas, 0.975)),
        "delta_ccc_bootstrap_frac_positive": float((deltas > 0).mean()),
        "selected_count_mean": float(np.mean(selected_counts)),
        "selected_count_min": int(np.min(selected_counts)),
        "selected_count_max": int(np.max(selected_counts)),
        "wall_time_seconds": float(time.time() - t0),
    }

    # Save result
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(f"results/metric_pdcor_selection_{target}_thr{int(threshold*100):03d}_k{max_k}_{ts}.json")
    out_path.write_text(json.dumps(result, indent=2, default=str) + "\n")

    print("\n" + "=" * 80)
    print(f"RESULT (pdCor selection on V2 alone, target={target}):")
    print(f"  baseline iter34 CCC: {baseline_metrics['ccc']:.4f}")
    print(f"  stacked CCC:         {stacked_metrics['ccc']:.4f}")
    print(f"  ΔCCC:                {result['delta_ccc']:+.4f}")
    print(f"  bootstrap ΔCCC median: {result['delta_ccc_bootstrap_median']:+.4f}, frac>0: {result['delta_ccc_bootstrap_frac_positive']:.4f}")
    print(f"  bootstrap 95% CI: [{result['delta_ccc_bootstrap_ci_lower']:+.4f}, {result['delta_ccc_bootstrap_ci_upper']:+.4f}]")
    print(f"  selected per fold: mean={result['selected_count_mean']:.1f}, min={result['selected_count_min']}, max={result['selected_count_max']}")
    print(f"  → wrote {out_path}")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="t1", choices=["t1", "t3"])
    ap.add_argument("--threshold", type=float, default=0.10)
    ap.add_argument("--max-k", type=int, default=200)
    ap.add_argument("--alpha", type=float, default=10.0)
    args = ap.parse_args()
    loocv_pdcor_stack(args.target, args.threshold, args.max_k, args.alpha)
