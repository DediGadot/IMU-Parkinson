"""T1 iter29-B VALIDATE — rigorous validation of the multi-task LGB lift.

Triggered after the 5-fold screen showed Δ̄ = +0.0513 (above gate) but seed std
borderline. Three checks run sequentially:

  1) LOOCV evaluation across 3 seeds (mean preds), with paired-bootstrap CI
     of Δ vs iter5-direct-T1 LOOCV (n=5000). Critical because F58/F56 showed
     5-fold Pearson r OVERESTIMATES lift at LOOCV.
  2) Scrambled-label null gate (3 seeds): shuffle T1 within train fold, expect
     CCC ≈ 0. Catches train/test entanglement leakage.
  3) Paired bootstrap (n=5000) on the 5-fold OOF predictions vs iter5-direct OOF.
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

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
from run_t1_iter4 import load_pd_data as load_t1_pd_data, T1_ITEMS
from run_t1_iter29b_multitask_lgb import _multitask_lgb_predict

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500


def _load_t1_cohort_with_items():
    d = load_t1_pd_data()
    sids = np.asarray(d["sids"])
    X = np.asarray(d["X_v2"], dtype=np.float64)
    y_t1 = np.asarray(d["t1"], dtype=np.float64)
    hy = np.asarray(d["hy"], dtype=np.float64)
    items = {i: np.asarray(d["items"][i], dtype=np.float64) for i in T1_ITEMS}
    valid = ~np.isnan(y_t1)
    items_valid = {i: items[i][valid] for i in T1_ITEMS}
    return sids[valid], X[valid], y_t1[valid], hy[valid], items_valid


def _splits(n: int, mode: str, seed: int):
    if mode == "loocv":
        return list(LeaveOneOut().split(np.arange(n)))
    return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))


def _multitask_one_pass(seed, mode, scramble=False, feature_set="A3_tier1"):
    sids, X, y_t1, hy, items = _load_t1_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    rng = np.random.RandomState(seed + 99999)
    for fold_id, (tr, te) in enumerate(_splits(n, mode, seed)):
        if scramble:
            perm = rng.permutation(len(tr))
            y_tr = y_t1[tr][perm].copy()
            items_tr_perm = {i: items[i][tr][perm].copy() for i in T1_ITEMS}
        else:
            y_tr = y_t1[tr]
            items_tr_perm = {i: items[i][tr] for i in T1_ITEMS}
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_tr, X_s1[te], alpha=STAGE1_ALPHA)
        item_means = {}
        items_tr_residual = []
        for i in T1_ITEMS:
            v = items_tr_perm[i]
            mu = float(np.nanmean(v))
            item_means[i] = mu
            items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
        items_tr_arr = np.column_stack(items_tr_residual)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_tr - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        item_resid_pred_te = _multitask_lgb_predict(Xtr_sel, items_tr_arr, Xte_sel, seed)
        item_pred_te = item_resid_pred_te + np.array([item_means[i] for i in T1_ITEMS])
        t1_pred_from_items = item_pred_te.sum(axis=1)
        sum_means = float(sum(item_means.values()))
        preds[te] = s1_te + (t1_pred_from_items - sum_means)
        if mode == "loocv" and (fold_id + 1) % 10 == 0:
            print(f"    seed={seed} fold {fold_id+1}/{n}", flush=True)
    return y_t1, preds


def _iter5_direct_one_pass(seed, mode, scramble=False, feature_set="A3_tier1"):
    sids, X, y_t1, hy, _ = _load_t1_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    rng = np.random.RandomState(seed + 99999)
    for tr, te in _splits(n, mode, seed):
        if scramble:
            perm = rng.permutation(len(tr))
            y_tr = y_t1[tr][perm].copy()
        else:
            y_tr = y_t1[tr]
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_tr, X_s1[te], alpha=STAGE1_ALPHA)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_tr - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        preds[te] = s1_te + train_lgb(Xtr_sel, y_tr - s1_tr, Xte_sel, seed)
    return y_t1, preds


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["loocv", "5fold", "scrambled", "all"], default="all")
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    args = ap.parse_args()

    seeds = tuple(args.seeds)
    out: dict = {"timestamp": datetime.now().isoformat()}

    if args.mode in {"5fold", "all"}:
        print("\n=== 5-FOLD CONFIRMATION ===", flush=True)
        rows = []
        for seed in seeds:
            t0 = time.time()
            y, p_mt = _multitask_one_pass(seed, "5fold")
            _, p_i5 = _iter5_direct_one_pass(seed, "5fold")
            c_mt, c_i5 = float(ccc_fn(y, p_mt)), float(ccc_fn(y, p_i5))
            rows.append({"seed": seed, "ccc_mt": c_mt, "ccc_i5": c_i5,
                         "delta": c_mt - c_i5, "wall": time.time() - t0})
            print(f"  seed={seed}: mt={c_mt:.4f} | i5={c_i5:.4f} | Δ={c_mt-c_i5:+.4f}", flush=True)
        out["five_fold"] = rows

    if args.mode in {"scrambled", "all"}:
        print("\n=== SCRAMBLED-LABEL NULL GATE (5-fold) ===", flush=True)
        rows = []
        for seed in seeds:
            y, p_mt = _multitask_one_pass(seed, "5fold", scramble=True)
            _, p_i5 = _iter5_direct_one_pass(seed, "5fold", scramble=True)
            c_mt, c_i5 = float(ccc_fn(y, p_mt)), float(ccc_fn(y, p_i5))
            rows.append({"seed": seed, "ccc_mt_scram": c_mt, "ccc_i5_scram": c_i5})
            print(f"  seed={seed}: mt_scram={c_mt:+.4f} | i5_scram={c_i5:+.4f}  (expect ≈ 0)", flush=True)
        out["scrambled"] = rows

    if args.mode in {"loocv", "all"}:
        print("\n=== LOOCV (CRITICAL — F58 says 5-fold Pearson r overestimates LOOCV lift) ===", flush=True)
        all_mt: list[np.ndarray] = []
        all_i5: list[np.ndarray] = []
        y_ref = None
        rows = []
        for seed in seeds:
            t0 = time.time()
            y, p_mt = _multitask_one_pass(seed, "loocv")
            _, p_i5 = _iter5_direct_one_pass(seed, "loocv")
            c_mt, c_i5 = float(ccc_fn(y, p_mt)), float(ccc_fn(y, p_i5))
            rows.append({"seed": seed, "ccc_mt": c_mt, "ccc_i5": c_i5,
                         "delta": c_mt - c_i5, "wall": time.time() - t0})
            print(f"  seed={seed}: mt={c_mt:.4f} | i5={c_i5:.4f} | Δ={c_mt-c_i5:+.4f} | "
                  f"{time.time()-t0:.0f}s", flush=True)
            all_mt.append(p_mt); all_i5.append(p_i5); y_ref = y
        mean_mt = np.mean(np.column_stack(all_mt), axis=1)
        mean_i5 = np.mean(np.column_stack(all_i5), axis=1)
        ccc_mt_mean = float(ccc_fn(y_ref, mean_mt))
        ccc_i5_mean = float(ccc_fn(y_ref, mean_i5))
        delta_mean = ccc_mt_mean - ccc_i5_mean
        print(f"\n  3-seed-mean: mt={ccc_mt_mean:.4f} | i5={ccc_i5_mean:.4f} | "
              f"Δ={delta_mean:+.4f}", flush=True)

        # Paired bootstrap (n=5000) on mean preds
        rng = np.random.RandomState(42)
        n = len(y_ref)
        deltas = np.empty(5000)
        for i in range(5000):
            idx = rng.randint(0, n, n)
            deltas[i] = ccc_fn(y_ref[idx], mean_mt[idx]) - ccc_fn(y_ref[idx], mean_i5[idx])
        boot = {"n_boot": 5000, "delta_mean": float(deltas.mean()),
                "delta_ci_low": float(np.percentile(deltas, 2.5)),
                "delta_ci_high": float(np.percentile(deltas, 97.5)),
                "frac_above_zero": float((deltas > 0).mean()),
                "frac_above_0.025": float((deltas > 0.025).mean())}
        print(f"  Bootstrap (n=5000): mean Δ={boot['delta_mean']:+.4f}, "
              f"95% CI=[{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}], "
              f"frac>0={boot['frac_above_zero']:.3f}, frac>0.025={boot['frac_above_0.025']:.3f}",
              flush=True)
        out["loocv"] = {
            "per_seed": rows, "ccc_mt_mean": ccc_mt_mean, "ccc_i5_mean": ccc_i5_mean,
            "delta_mean": delta_mean, "bootstrap": boot,
            "y_true": y_ref.tolist(),
            "preds_multitask_mean": mean_mt.tolist(),
            "preds_iter5_direct_mean": mean_i5.tolist(),
        }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"iter29b_validate_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
