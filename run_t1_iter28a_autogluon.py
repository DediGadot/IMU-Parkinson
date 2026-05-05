"""T1 iter28-A — AutoGluon Stage-2 replacement for T1 (sum items 9-14).

Mirrors run_t3_iter28a_autogluon.py:
  Stage 1 = Ridge alpha=1.0 on H&Y + cv_yrs + cv_sex + cv_dbs, target=T1 (sum items 9-14).
  Stage 2 = AutoGluon TabularPredictor (presets=best_quality, time_limit=180s)
           on V2 residual after per-fold median imputation + K=500 LGB importance.

Cohort = 94 PD subjects with full items 9-14 (load_pd_data from run_t1_iter4).

Modes: screen | write_prereg | lockbox.

Comparator on each seed/fold = T1 iter5-direct (Stage1+Stage2-LGB, same target).
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")
os.environ.setdefault("AUTOGLUON_LOG_LEVEL", "30")

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold, LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter4 import load_pd_data as load_t1_pd_data

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
PUBLISHED_T1_LOOCV_CCC = 0.6550  # iter12 honest composite (per-item gated)
STAGE1_ALPHA = 1.0
K_FEATURES = 500


def _load_t1_cohort() -> tuple[np.ndarray, np.ndarray, list[str], np.ndarray, np.ndarray]:
    """Return (sids, X_v2, feat_cols, y_t1, hy) on the 94-PD T1 cohort."""
    d = load_t1_pd_data()
    sids = np.asarray(d["sids"])
    X = np.asarray(d["X_v2"], dtype=np.float64)
    y_t1 = np.asarray(d["t1"], dtype=np.float64)
    hy = np.asarray(d["hy"], dtype=np.float64)
    valid = ~np.isnan(y_t1)
    return sids[valid], X[valid], d["feat_cols"], y_t1[valid], hy[valid]


def _ag_workdir(seed: int, fold_id: int) -> str:
    return f"/tmp/agt1_iter28a_{seed}_{fold_id}_{int(time.time()*1000)}"


def stage2_autogluon(
    Xtr_sel: np.ndarray, residual_tr: np.ndarray, Xte_sel: np.ndarray,
    seed: int, fold_id: int, time_limit: int = 180,
) -> np.ndarray:
    from autogluon.tabular import TabularPredictor

    tr_df = pd.DataFrame(Xtr_sel)
    tr_df.columns = [f"f{i}" for i in range(tr_df.shape[1])]
    tr_df["__target__"] = residual_tr
    te_df = pd.DataFrame(Xte_sel)
    te_df.columns = [f"f{i}" for i in range(te_df.shape[1])]
    workdir = _ag_workdir(seed, fold_id)
    try:
        pred = TabularPredictor(
            label="__target__", problem_type="regression",
            eval_metric="mean_absolute_error", verbosity=1, path=workdir,
        ).fit(
            tr_df, time_limit=time_limit, presets="best_quality",
            ag_args_fit={"random_state": seed, "num_cpus": 1},
        )
        return pred.predict(te_df).values.astype(np.float64)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _fit_one_fold(
    seed: int, fold_id: int, tr_idx: np.ndarray, te_idx: np.ndarray,
    X: np.ndarray, y: np.ndarray, X_s1: np.ndarray, time_limit: int,
) -> tuple[np.ndarray, np.ndarray]:
    s1_pred_tr, s1_pred_te = fit_stage1(X_s1[tr_idx], y[tr_idx], X_s1[te_idx], alpha=STAGE1_ALPHA)
    residual_tr = y[tr_idx] - s1_pred_tr
    Xtr, Xte = impute_fold(X[tr_idx], X[te_idx])
    Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=K_FEATURES, seed=seed)
    s2_pred_te = stage2_autogluon(
        Xtr_sel, residual_tr, Xte_sel, seed=seed, fold_id=fold_id, time_limit=time_limit
    )
    return te_idx, s1_pred_te + s2_pred_te


def _splits(n: int, seed: int, eval_mode: str):
    if eval_mode == "5fold":
        return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))
    if eval_mode == "loocv":
        return list(LeaveOneOut().split(np.arange(n)))
    raise ValueError(f"unknown eval_mode {eval_mode!r}")


def _run_seed(
    seed: int, feature_set: str, time_limit: int, eval_mode: str, n_workers: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    sids, X, _, y_t1, hy = _load_t1_cohort()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    splits = _splits(n, seed, eval_mode)
    preds = np.zeros(n)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futures = {
            ex.submit(_fit_one_fold, seed, fid, tr, te, X, y_t1, X_s1, time_limit): fid
            for fid, (tr, te) in enumerate(splits)
        }
        for fut in as_completed(futures):
            te_idx, te_preds = fut.result()
            preds[te_idx] = te_preds
    return sids, y_t1, preds, time.time() - t0


def _iter5_direct_t1_kfold(seed: int, feature_set: str) -> tuple[np.ndarray, np.ndarray]:
    """T1 iter5-direct comparator: Stage1 Ridge + Stage2 LGB, target=T1, same 5-fold/seed."""
    sids, X, _, y_t1, hy = _load_t1_cohort()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    splits = _splits(n, seed, "5fold")
    for tr, te in splits:
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed)
        preds[te] = s1_te + train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)
    return y_t1, preds


def _q_residuals(y, p):
    q1 = np.percentile(y, 25); q4 = np.percentile(y, 75)
    res = p - y
    return (
        float(res[y <= q1].mean()) if (y <= q1).any() else float("nan"),
        float(res[y >= q4].mean()) if (y >= q4).any() else float("nan"),
    )


def run_screen(seeds, feature_set, time_limit, n_workers) -> Path:
    print(
        f"\n=== T1 iter28-A SCREEN (5-fold, feature_set={feature_set}, "
        f"time_limit={time_limit}s, {len(seeds)} seeds, {n_workers} workers) ===",
        flush=True,
    )
    rows = []
    for seed in seeds:
        sids, y_t1, preds_ag, elapsed = _run_seed(
            seed=seed, feature_set=feature_set, time_limit=time_limit,
            eval_mode="5fold", n_workers=n_workers,
        )
        y_ref, iter5_preds = _iter5_direct_t1_kfold(seed=seed, feature_set=feature_set)
        assert np.allclose(y_ref, y_t1)
        c_ag = float(ccc_fn(y_t1, preds_ag))
        c_i5 = float(ccc_fn(y_t1, iter5_preds))
        m = float(mae_fn(y_t1, preds_ag))
        r = float(pearson_r(y_t1, preds_ag))
        slope = float(np.polyfit(preds_ag, y_t1, 1)[0]) if preds_ag.std() > 1e-9 else float("nan")
        q1res, q4res = _q_residuals(y_t1, preds_ag)
        rows.append({
            "seed": seed, "ccc": round(c_ag, 4), "mae": round(m, 3), "r": round(r, 4),
            "slope": round(slope, 4), "q1_residual": round(q1res, 3), "q4_residual": round(q4res, 3),
            "wall_time_s": round(elapsed, 1),
            "iter5_direct_t1_5fold_ccc": round(c_i5, 4),
            "delta_vs_iter5_direct": round(c_ag - c_i5, 4),
        })
        print(
            f"  seed={seed}: AG-T1 CCC={c_ag:.4f} | iter5-direct-T1 CCC={c_i5:.4f} | "
            f"Δ={c_ag-c_i5:+.4f} | MAE={m:.3f} | r={r:.4f} | slope={slope:.3f} | "
            f"Q1res={q1res:+.2f} Q4res={q4res:+.2f} | {elapsed:.1f}s",
            flush=True,
        )
    df = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter28a_t1_autogluon_5fold_{ts}.csv"
    df.to_csv(out, index=False)
    print(
        f"\nMean AG-T1 CCC = {df['ccc'].mean():.4f} ± {df['ccc'].std():.4f}; "
        f"Mean iter5-direct-T1 CCC = {df['iter5_direct_t1_5fold_ccc'].mean():.4f} ± "
        f"{df['iter5_direct_t1_5fold_ccc'].std():.4f}; "
        f"Δ̄ = {df['delta_vs_iter5_direct'].mean():+.4f}",
        flush=True,
    )
    print(f"Wrote {out}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["screen", "write_prereg", "lockbox"], required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--time_limit", type=int, default=180)
    ap.add_argument("--n_workers", type=int, default=int(os.getenv("ITER28A_T1_WORKERS", 5)))
    ap.add_argument("--preregistration_file", type=str, default=None)
    args = ap.parse_args()

    if args.feature_set not in ITER5_FEATURE_SETS:
        raise ValueError(f"feature_set must be one of {list(ITER5_FEATURE_SETS)}; got {args.feature_set!r}")

    seeds = tuple(args.seeds)
    if args.mode == "screen":
        run_screen(seeds, args.feature_set, args.time_limit, args.n_workers)
    elif args.mode == "write_prereg":
        raise NotImplementedError("Run lockbox only after screen passes Δ ≥ +0.025 with std<0.02.")
    elif args.mode == "lockbox":
        raise NotImplementedError("Run lockbox only after screen passes Δ ≥ +0.025 with std<0.02.")


if __name__ == "__main__":
    main()
