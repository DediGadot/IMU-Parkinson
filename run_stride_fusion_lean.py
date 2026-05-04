"""First-principles fix attempt — stride_lean variant.

Hypothesis: 1173 stride features × N=94 = K=200 selection picks noisy
CV/slope/first_last_diff features. Drop them — keep only robust mean/std/p95
+ bilateral-asymmetry + stride counts.

Run on items where stride_plus_v2 came closest to prior best:
  item 12: +0.011 (closest) → if can clear +0.015, promote
  item 10: +0.002 (parity)
  item 14: -0.085 (worst on a gait item; check if dropping noise saves it)
  item 11: -0.084 (FoG; check)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR
from run_t1_iter4 import (
    load_pd_data, kfold_split_stratified, impute_fold,
    feature_select_fold, train_lgb, SEEDS,
)

STRIDE_CACHE = REPO_ROOT / "results" / "stride_locked_subj.csv"

# "Lean" suffix set: keep only the most stable aggregates.
LEAN_SUFFIXES = ("__mean", "__std", "__p95")
KEEP_PREFIXES = ("subj__", "asym__")  # asymmetry + n-strides total


def load_lean_stride(sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    df = pd.read_csv(STRIDE_CACHE).set_index("sid")
    cols = [
        c for c in df.columns
        if any(c.endswith(s) for s in LEAN_SUFFIXES)
        or any(c.startswith(p) for p in KEEP_PREFIXES)
    ]
    n = len(sids)
    X = np.full((n, len(cols)), np.nan)
    matched = 0
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, cols].to_numpy(dtype=np.float64)
            matched += 1
    print(f"  Lean stride features: {matched}/{n} subjects, {len(cols)} features", flush=True)
    return X, cols


def variant_stride_plus_v2_lean(d: dict, X_str: np.ndarray, y: np.ndarray,
                                  splits, seed: int) -> np.ndarray:
    n = len(y)
    X_aug = np.hstack([d["X_v2"], X_str])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", type=str, default="10,11,12,14")
    args = ap.parse_args()
    items = [int(x) for x in args.items.split(",")]

    print("Loading PD data...", flush=True)
    d = load_pd_data()
    sids = d["sids"]
    X_str, str_cols = load_lean_stride(sids)

    PRIOR = {7: 0.273, 8: 0.259, 9: 0.237, 10: 0.495, 11: 0.215, 12: 0.553, 14: 0.369}

    print("\n=== stride_plus_v2_LEAN (mean/std/p95 only) ===", flush=True)
    out = {}
    for it in items:
        y = d["items"][it]
        ccs = []
        for seed in SEEDS:
            t0 = time.time()
            splits = kfold_split_stratified(y, 5, seed=seed)
            oof = variant_stride_plus_v2_lean(d, X_str, y, splits, seed)
            c = ccc_fn(y, oof)
            ccs.append(c)
        ccc_mean = float(np.mean(ccs))
        ccc_std = float(np.std(ccs))
        prior = PRIOR.get(it, 0.0)
        out[it] = {"ccc_mean": round(ccc_mean, 4), "ccc_std": round(ccc_std, 4),
                   "delta": round(ccc_mean - prior, 4),
                   "ccc_per_seed": [round(c, 4) for c in ccs],
                   "n_features": len(str_cols)}
        print(f"  item {it}: 5-fold CCC = {ccc_mean:.4f} ± {ccc_std:.4f}"
              f" [prior {prior:.3f}, Δ={ccc_mean - prior:+.3f}]",
              flush=True)
    with open(RESULTS_DIR / "stride_lean_summary.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote results/stride_lean_summary.json", flush=True)


if __name__ == "__main__":
    main()
