"""Iter 6 lockbox LOOCV runner for gated_per_item_t1_w_hy.

Pre-registered variant:
  - Items {10, 12, 14} predicted via LGB on (V2 + TUG transition phase features)
  - Items {9, 11, 13} predicted via hy_residual (Stage-1 Ridge on H&Y → Stage-2 LGB on V2 residual)
  - Sum 6 per-item OOFs = T1 prediction

3 seeds × 89 LOOCV folds × 6 per-item models = 1602 per-item LGB trains per seed.
Estimated wall-clock: ~45-75 min per seed at 4 cores. With process-pool parallelism
across outer folds (11 workers), drops to ~5-10 min per seed.

Usage:
  # Step 1: write pre-registration
  python3 run_t1_iter6_lockbox_loocv.py --write_prereg \
      --expected_loocv_low 0.60 --expected_loocv_high 0.70 \
      --screening_ccc 0.6638

  # Step 2: run LOOCV
  python3 run_t1_iter6_lockbox_loocv.py --execute
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    load_pd_data, impute_fold, feature_select_fold, train_lgb,
    get_hy_features, LGB_DEFAULTS, SEEDS, TUG_TRANSITION,
    load_extra_cache,
)


T1_ITEMS = [9, 10, 11, 12, 13, 14]
GAIN_ITEMS = [10, 12, 14]
HURT_ITEMS = [9, 11, 13]
N_WORKERS = int(os.getenv("PD_IMU_LOOCV_WORKERS", 11))


def load_tug_features_for_fold(sids):
    X_tug, _ = load_extra_cache(TUG_TRANSITION, sids)
    df_tmp = pd.read_csv(TUG_TRANSITION)
    feat_cols_tug = [c for c in df_tmp.columns if c not in ("sid", "_spike_time_s")]
    X_tug = X_tug[:, [list(df_tmp.columns).index(c) - 1 for c in feat_cols_tug]]
    return X_tug


def predict_one_fold(args):
    """LOOCV one outer fold. Returns (i, oof_value)."""
    (i, X_v2, X_tug, hy_feat, items_dict, t1_target, seed) = args
    n = len(t1_target)
    tr = np.arange(n) != i
    te = ~tr

    X_v2_aug_tug = np.hstack([X_v2, X_tug])

    # Per-item predictions
    item_preds = {}
    for it in GAIN_ITEMS:
        target = items_dict[it]
        Xtr, Xte = impute_fold(X_v2_aug_tug[tr], X_v2_aug_tug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, target[tr], Xte, k=500, seed=seed)
        pred = train_lgb(Xtr, target[tr], Xte, seed)
        item_preds[it] = float(pred[0])

    for it in HURT_ITEMS:
        target = items_dict[it]
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], target[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = target[tr] - s1_tr
        Xtr, Xte = impute_fold(X_v2[tr], X_v2[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        s2_te = train_lgb(Xtr, resid_tr, Xte, seed)
        item_preds[it] = float(s1_te[0] + s2_te[0])

    return i, item_preds


def loocv_run(d: dict, seed: int) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    """Run LOOCV in parallel across outer folds. Returns (T1_sum_oof, per_item_oof)."""
    n = len(d["sids"])
    X_tug = load_tug_features_for_fold(d["sids"])
    hy_feat = get_hy_features(d["hy"])

    # Pre-clean items
    items_dict = {it: np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
                  for it in T1_ITEMS}

    # Build job list
    jobs = [(i, d["X_v2"], X_tug, hy_feat, items_dict, d["t1"], seed)
            for i in range(n)]

    # Use process pool to parallelize across outer folds
    item_oofs = {it: np.zeros(n) for it in T1_ITEMS}
    print(f"  dispatching {n} LOOCV folds across {N_WORKERS} workers...")
    with ProcessPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = [pool.submit(predict_one_fold, j) for j in jobs]
        done_count = 0
        for fut in as_completed(futures):
            i, item_preds = fut.result()
            for it, val in item_preds.items():
                item_oofs[it][i] = val
            done_count += 1
            if done_count % 20 == 0:
                print(f"    progress: {done_count}/{n} folds")
    t1_sum = np.zeros(n)
    for it in T1_ITEMS:
        t1_sum = t1_sum + item_oofs[it]
    return t1_sum, item_oofs


def write_prereg(args) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    spec = {
        "iter": "iter6_t1",
        "variant_locked": "gated_per_item_t1_w_hy",
        "architecture": {
            "items_via_v2_plus_tug": GAIN_ITEMS,
            "items_via_hy_residual": HURT_ITEMS,
            "stage1_ridge_alpha": 1.0,
            "stage2_lgb_defaults": LGB_DEFAULTS,
            "feature_selection_k": 500,
        },
        "expected_loocv_range": [args.expected_loocv_low, args.expected_loocv_high],
        "seeds": SEEDS,
        "n_folds_loocv": 89,
        "screened_5fold_winner_ccc": args.screening_ccc,
        "timestamp_utc": ts,
        "rule": "Run LOOCV exactly once. Report regardless of result. No re-runs.",
    }
    ensure_dir(RESULTS_DIR)
    path = RESULTS_DIR / f"preregistration_t1_iter6_{ts}.json"
    with open(path, "w") as f:
        json.dump(spec, f, indent=2)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected_loocv_low", type=float, default=0.60)
    ap.add_argument("--expected_loocv_high", type=float, default=0.70)
    ap.add_argument("--screening_ccc", type=float, default=0.6638)
    ap.add_argument("--write_prereg", action="store_true")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    if args.write_prereg:
        path = write_prereg(args)
        print(f"Pre-registration written to {path}")
        return

    if not args.execute:
        raise ValueError("Specify --write_prereg or --execute")

    # Load preregistration
    files = sorted((RESULTS_DIR).glob("preregistration_t1_iter6_*.json"))
    if not files:
        raise FileNotFoundError("No preregistration_t1_iter6_*.json — write one first")
    with open(files[-1]) as f:
        spec = json.load(f)
    print(f"Pre-registration loaded: {files[-1].name}")
    print(f"  variant_locked: {spec['variant_locked']}")

    print("Loading data...")
    d = load_pd_data()
    n = len(d["sids"])
    print(f"  N={n} PD subjects")

    per_seed_metrics = []
    cccs = []
    per_item_cccs_collected = {it: [] for it in T1_ITEMS}
    # Accumulate OOFs across seeds for hybrid composite
    t1_oof_acc = np.zeros(len(d["sids"]))
    item_oof_acc = {it: np.zeros(len(d["sids"])) for it in T1_ITEMS}
    t0 = time.time()
    for seed in SEEDS:
        s_t0 = time.time()
        print(f"[seed={seed}] running parallel LOOCV...")
        t1_oof, item_oofs = loocv_run(d, seed)
        m = full_metrics(d["t1"], t1_oof, label=f"loocv_seed{seed}")
        m["seed"] = seed
        m["wall_s"] = round(time.time() - s_t0, 1)
        t1_oof_acc = t1_oof_acc + t1_oof
        for it in T1_ITEMS:
            item_oof_acc[it] = item_oof_acc[it] + item_oofs[it]
        # per-item CCC under LOOCV
        per_item_ccc = {}
        for it in T1_ITEMS:
            target_item = np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
            c = round(float(ccc_fn(target_item, item_oofs[it])), 4)
            per_item_ccc[it] = c
            per_item_cccs_collected[it].append(c)
        m["per_item_ccc"] = per_item_ccc
        per_seed_metrics.append(m)
        cccs.append(m["ccc"])
        print(f"  seed={seed} ccc={m['ccc']:.4f} mae={m['mae']:.3f} "
              f"slope={m['cal_slope']:.3f} ({m['wall_s']:.0f}s)")
        print(f"  per-item CCC: {per_item_ccc}")

    summary = {
        "variant": "gated_per_item_t1_w_hy",
        "target": "t1", "eval": "loocv",
        "preregistration_file": files[-1].name,
        "n_subjects": n,
        "ccc_mean": round(float(np.mean(cccs)), 4),
        "ccc_std": round(float(np.std(cccs)), 4),
        "ccc_per_seed": [round(c, 4) for c in cccs],
        "mae_mean": round(float(np.mean([m["mae"] for m in per_seed_metrics])), 4),
        "slope_mean": round(float(np.mean([m["cal_slope"] for m in per_seed_metrics])), 4),
        "per_item_ccc_mean": {
            it: round(float(np.mean(per_item_cccs_collected[it])), 4) for it in T1_ITEMS
        },
        "per_seed": per_seed_metrics,
        "wall_total_s": round(time.time() - t0, 1),
    }
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"lockbox_t1_iter6_loocv_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    # Save mean OOFs across seeds for hybrid composite
    t1_oof_mean = t1_oof_acc / len(SEEDS)
    np.save(RESULTS_DIR / f"iter6_t1_oof_{ts}.npy", t1_oof_mean)
    for it in T1_ITEMS:
        np.save(RESULTS_DIR / f"iter6_item{it}_oof_{ts}.npy", item_oof_acc[it] / len(SEEDS))
    np.save(RESULTS_DIR / f"iter6_sids_{ts}.npy", d["sids"])
    print(f"Saved per-seed-mean OOFs: iter6_t1_oof_{ts}.npy + 6 item OOFs + sids")
    print(f"\n=== HEADLINE ===")
    print(f"Variant: gated_per_item_t1_w_hy")
    print(f"LOOCV CCC: {summary['ccc_mean']:.4f} ± {summary['ccc_std']:.4f}")
    print(f"Per-seed: {summary['ccc_per_seed']}")
    print(f"MAE: {summary['mae_mean']:.3f}, slope: {summary['slope_mean']:.3f}")
    print(f"Per-item CCC: {summary['per_item_ccc_mean']}")
    print(f"Saved to: {out_path}")


if __name__ == "__main__":
    main()
