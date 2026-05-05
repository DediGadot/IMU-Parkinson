"""Learning-curve sweep for iter5 architecture (LC cell of T3 iter22 ablation).

Subsamples PD subjects to N ∈ {30, 50, 70, 89}, runs iter5 LOOCV (4-cov A3_tier1)
at each subsample, records CCC. Total: 4 N-levels × 50 subsamples × 3 seeds = 600 jobs.
Embarrassingly parallel via ProcessPoolExecutor.

Output: results/learning_curve_iter5.csv with columns
  (n_pd, subsample_idx, seed, ccc, mae, r, wall_s)

Usage:
  python3 learning_curve_iter5.py --workers 16 --out results/learning_curve_iter5.csv
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

# Pin LightGBM threads to 1 inside workers (avoid thread oversubscription)
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("PD_IMU_N_CORES", "1")

from inductive_lib import ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter3 import load_full_pd_data
from run_t3_iter5_clinical import (
    FEATURE_SETS, build_stage1_features, fit_stage1, load_clinical_dict,
)
from run_t1_iter4 import impute_fold, feature_select_fold, train_lgb

LC_N_LEVELS: tuple[int, ...] = (30, 50, 70, 89)
LC_N_SUBSAMPLES: int = 50
LC_SEEDS: tuple[int, ...] = (42, 1337, 7)
FEATURE_SET = "A3_tier1"  # canonical iter5 panel


def _run_one_subsample(args: tuple[int, int, int]) -> dict:
    """Worker: run iter5 LOOCV at a specific (n_pd, subsample_idx, seed)."""
    n_pd, subsample_idx, seed = args
    t0 = time.time()
    sids, X, fc, y_t3, hy, obs = load_full_pd_data()
    full_n = len(sids)

    # Pick subsample with deterministic seed = combo of (subsample_idx, seed)
    rng = np.random.RandomState(1000 * subsample_idx + seed)
    pick = rng.choice(full_n, size=n_pd, replace=False)
    sids_s = sids[pick]
    X_s = X[pick]
    y_s = y_t3[pick]
    hy_s = hy[pick]

    clinical = load_clinical_dict(sids_s)
    extras = FEATURE_SETS[FEATURE_SET]
    X_s1, _ = build_stage1_features(hy_s, clinical, extras)

    preds = np.zeros(n_pd)
    from sklearn.model_selection import LeaveOneOut
    for tr, te in LeaveOneOut().split(np.arange(n_pd)):
        s1_pred_tr, s1_pred_te = fit_stage1(X_s1[tr], y_s[tr], X_s1[te], alpha=1.0)
        residual_tr = y_s[tr] - s1_pred_tr
        Xtr, Xte = impute_fold(X_s[tr], X_s[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        s2_pred_te = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        preds[te] = s1_pred_te + s2_pred_te

    return dict(
        n_pd=n_pd,
        subsample_idx=subsample_idx,
        seed=seed,
        ccc=float(ccc_fn(y_s, preds)),
        mae=float(mae_fn(y_s, preds)),
        r=float(pearson_r(y_s, preds)),
        wall_s=round(time.time() - t0, 1),
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--out", default=str(RESULTS_DIR / "learning_curve_iter5.csv"))
    p.add_argument("--n-levels", default=",".join(str(n) for n in LC_N_LEVELS))
    p.add_argument("--n-subsamples", type=int, default=LC_N_SUBSAMPLES)
    p.add_argument("--seeds", default=",".join(str(s) for s in LC_SEEDS))
    args = p.parse_args()
    ensure_dir(RESULTS_DIR)

    n_levels = tuple(int(n) for n in args.n_levels.split(","))
    seeds = tuple(int(s) for s in args.seeds.split(","))

    # Build job list
    jobs = []
    for n in n_levels:
        for s_idx in range(args.n_subsamples):
            for seed in seeds:
                jobs.append((n, s_idx, seed))
    total = len(jobs)
    print(f"Learning curve: {total} jobs ({len(n_levels)} N-levels × {args.n_subsamples} subsamples × {len(seeds)} seeds)", flush=True)
    print(f"Workers: {args.workers}", flush=True)

    rows = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_run_one_subsample, j): j for j in jobs}
        done = 0
        for fut in as_completed(futures):
            try:
                row = fut.result()
            except Exception as e:
                j = futures[fut]
                print(f"  job {j} FAILED: {type(e).__name__}: {e}", flush=True)
                continue
            rows.append(row)
            done += 1
            if done % 25 == 0:
                elapsed = time.time() - t0
                eta = elapsed / done * (total - done)
                print(
                    f"  [{done}/{total}] last: n={row['n_pd']} sub={row['subsample_idx']} seed={row['seed']} "
                    f"CCC={row['ccc']:+.4f}  elapsed={elapsed/60:.1f}min  ETA={eta/60:.1f}min",
                    flush=True,
                )

    df = pd.DataFrame(rows)
    df.to_csv(args.out, index=False)
    print(f"\nWrote {args.out} ({len(df)} rows)", flush=True)
    print("\nLearning curve summary (mean ± std CCC across seeds × subsamples):", flush=True)
    summ = df.groupby("n_pd")["ccc"].agg(["mean", "std", "count"]).reset_index()
    summ.columns = ["n_pd", "ccc_mean", "ccc_std", "n_jobs"]
    print(summ.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
