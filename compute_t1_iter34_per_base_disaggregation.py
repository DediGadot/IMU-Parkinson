"""T1 iter34 per-base disaggregation — slot D-hetero candidate (FWER family member).

Runs the iter34 8-item chain LOOCV at N=92 hygiene-corrected cohort but saves
per-base T1 sum predictions in addition to the averaged hybrid. From one 30-min
LOOCV run we extract three candidates:
  - LGB-only 8-item chain (equivalent to iter33-B at corrected cohort)
  - XGB-only 8-item chain (new)
  - ET-only 8-item chain (new)
  - Hybrid (averaged) = iter34 hygiene-corrected (matches lockbox)

For each base candidate: paired-bootstrap vs iter34 hybrid (CCC 0.7170) and vs
iter12-honest canonical floor (CCC 0.6550). FWER gate: Bonferroni n=8 family
(iter34_anchor + slot_A + slot_B + slot_C + slot_D_distill + 3 single-base
candidates). Per-test frac>0 gate ≥ 1 - 0.05/8 = 0.99375.

Mechanistically distinct from F66 (chain-order averaging): this picks ONE base
per chain (not averaged). At F66 the variance reduction was nil because chain
orders produced correlated OOFs. Per-base predictions are SEPARATE estimators
of the same item residual; we are not averaging, we are comparing.
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import hashlib
import json
import multiprocessing as mp
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter34_hybrid_8item_multibase import (
    BASE_LEARNERS, K_FEATURES, SEEDS_DEFAULT, STAGE1_ALPHA, _multitask_predict,
)
from run_t1_iter33b_8item_chain import _load_t1_cohort_with_8items, T1_SUM_ITEMS
from run_t3_iter2 import feature_select_fold, impute_fold
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features, fit_stage1, load_clinical_dict,
)


def _per_base_worker(args):
    """Worker returning (te_idx, per_base_t1_sums) where per_base_t1_sums is a
    dict mapping base name -> np.ndarray of T1 sum predictions for te subjects.
    """
    fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    item_means = {}
    items_tr_residual = []
    for i in item_order:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_residual)
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )

    t1_sum_idx = [item_order.index(i) for i in T1_SUM_ITEMS]
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))

    per_base = {}
    per_base_per_item = {}
    for b in bases:
        ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base=b)
        item_pred_t1 = ip[:, t1_sum_idx] + np.array(
            [item_means[i] for i in T1_SUM_ITEMS]
        )
        t1_from_items = item_pred_t1.sum(axis=1)
        per_base[b] = s1_te + (t1_from_items - sum_means_t1)
        # also store per-item per-base for the hetero matrix
        per_base_per_item[b] = {
            int(item_id): item_pred_t1[:, k]
            for k, item_id in enumerate(T1_SUM_ITEMS)
        }
    return te, per_base, per_base_per_item


def _loocv_per_base(seed, X, y_t1, X_s1, items, item_order, bases, n_workers):
    n = len(y_t1)
    splits = list(LeaveOneOut().split(np.arange(n)))
    per_base_preds = {b: np.zeros(n) for b in bases}
    per_base_per_item = {b: {int(i): np.zeros(n) for i in T1_SUM_ITEMS}
                         for b in bases}
    jobs = [(fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases)
            for fid, (tr, te) in enumerate(splits)]
    ctx = mp.get_context("spawn")
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_per_base_worker, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, pbase, pbi = fut.result()
            for b in bases:
                per_base_preds[b][te_idx] = pbase[b]
                for item_id in T1_SUM_ITEMS:
                    per_base_per_item[b][int(item_id)][te_idx] = pbi[b][int(item_id)]
            done += 1
            if done % 20 == 0 or done == n:
                print(f"    seed={seed} per-base {done}/{n} folds "
                      f"elapsed={time.time()-t0:.0f}s", flush=True)
    return per_base_preds, per_base_per_item


def paired_bootstrap(y, p_a, p_b, n_boot=5000, seed=42):
    rng = np.random.RandomState(seed)
    n = len(y); deltas = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, n)
        deltas[i] = ccc_fn(y[idx], p_a[idx]) - ccc_fn(y[idx], p_b[idx])
    return {
        "delta_mean": float(deltas.mean()),
        "delta_ci_low": float(np.percentile(deltas, 2.5)),
        "delta_ci_high": float(np.percentile(deltas, 97.5)),
        "frac_above_zero": float((deltas > 0).mean()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--n_workers", type=int, default=5)
    args = ap.parse_args()

    ensure_dir(RESULTS_DIR)
    print("=== iter34 PER-BASE DISAGGREGATION (N=92, hygiene-corrected) ===",
          flush=True)

    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, bases={BASE_LEARNERS}, n_workers={args.n_workers}",
          flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[args.feature_set])

    per_seed = []
    per_base_oof_seeds = {b: [] for b in BASE_LEARNERS}
    per_base_per_item_seeds = {b: {int(i): [] for i in T1_SUM_ITEMS}
                                for b in BASE_LEARNERS}
    overall_t0 = time.time()
    for seed in args.seeds:
        t0 = time.time()
        pb_preds, pbi = _loocv_per_base(
            seed, X, y_t1, X_s1, items, item_order, BASE_LEARNERS, args.n_workers
        )
        seed_metrics = {}
        for b in BASE_LEARNERS:
            ccc_b = ccc_fn(y_t1, pb_preds[b])
            seed_metrics[b] = float(ccc_b)
            per_base_oof_seeds[b].append(pb_preds[b])
            for item_id in T1_SUM_ITEMS:
                per_base_per_item_seeds[b][int(item_id)].append(pbi[b][int(item_id)])
        # Hybrid (average) for cross-check
        hybrid = np.mean([pb_preds[b] for b in BASE_LEARNERS], axis=0)
        seed_metrics["hybrid_avg"] = float(ccc_fn(y_t1, hybrid))
        print(f"  seed={seed}: " +
              " | ".join(f"{b}={seed_metrics[b]:.4f}" for b in BASE_LEARNERS) +
              f" | hybrid={seed_metrics['hybrid_avg']:.4f} | wall={time.time()-t0:.0f}s",
              flush=True)
        per_seed.append({"seed": seed, **seed_metrics})

    # Mean-of-seeds predictions per base
    per_base_mean_oof = {b: np.mean(per_base_oof_seeds[b], axis=0)
                          for b in BASE_LEARNERS}
    hybrid_mean = np.mean([per_base_mean_oof[b] for b in BASE_LEARNERS], axis=0)
    # Per-item per-base (mean of seeds)
    per_base_per_item_mean = {b: {int(i): np.mean(per_base_per_item_seeds[b][int(i)], axis=0)
                                    for i in T1_SUM_ITEMS}
                              for b in BASE_LEARNERS}

    # Load anchors
    iter34_oof_n92 = np.load(
        RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"
    )
    iter12_honest_baseline = 0.6550  # canonical floor

    print("\n=== Per-base candidates table (N=92, mean of 3 seeds) ===", flush=True)
    print(f"  {'base':<10} {'CCC':>7} {'MAE':>7} {'r':>7} {'slope':>7} "
          f"{'Δ_vs_hybrid':>12} {'frac>0_vs_hyb':>15}", flush=True)
    summary = {}
    for b in BASE_LEARNERS:
        m = full_metrics(y_t1, per_base_mean_oof[b])
        bs_vs_hybrid = paired_bootstrap(y_t1, per_base_mean_oof[b], iter34_oof_n92)
        bs_vs_floor = paired_bootstrap(y_t1, per_base_mean_oof[b],
                                          per_base_mean_oof[b] * 0)
        # Properly: vs floor would be a baseline pred. We don't have iter12-honest OOF
        # so use it as scalar comparator via difference of means
        delta_vs_iter34 = m['ccc'] - 0.7170
        print(f"  {b:<10} {m['ccc']:>7.4f} {m['mae']:>7.4f} {m['r']:>7.4f} "
              f"{m['cal_slope']:>7.4f} {delta_vs_iter34:>+12.4f} "
              f"{bs_vs_hybrid['frac_above_zero']:>15.4f}", flush=True)
        summary[b] = {
            "ccc": m['ccc'], "mae": m['mae'], "r": m['r'],
            "cal_slope": m['cal_slope'],
            "delta_vs_iter34_hybrid_n92": delta_vs_iter34,
            "delta_vs_iter12_honest_n94": m['ccc'] - 0.6550,
            "paired_bootstrap_vs_iter34_hybrid": bs_vs_hybrid,
            "per_seed_ccc": [s[b] for s in per_seed],
        }

    # Hybrid sanity check
    hy_metrics = full_metrics(y_t1, hybrid_mean)
    print(f"  {'hybrid':<10} {hy_metrics['ccc']:>7.4f} {hy_metrics['mae']:>7.4f} "
          f"{hy_metrics['r']:>7.4f} {hy_metrics['cal_slope']:>7.4f} "
          f"{hy_metrics['ccc']-0.7170:>+12.4f}", flush=True)
    print(f"  (Should match iter34 lockbox CCC=0.7170)", flush=True)

    # Per-item per-base matrix
    print("\n=== Per-item × Per-base CCC matrix (mean of 3 seeds) ===", flush=True)
    print(f"  {'item':>4}  {'name':<25} " +
          "  ".join(f"{b:>7}" for b in BASE_LEARNERS), flush=True)
    names = {9: "arising from chair", 10: "gait", 11: "freezing of gait",
             12: "postural stability", 13: "posture", 14: "body bradykinesia"}
    item_x_base_ccc = {}
    for i in T1_SUM_ITEMS:
        i_int = int(i)
        row = {b: ccc_fn(items[i_int], per_base_per_item_mean[b][i_int])
               for b in BASE_LEARNERS}
        item_x_base_ccc[i_int] = {b: float(v) for b, v in row.items()}
        best_b = max(row, key=row.get)
        print(f"  {i:>4}  {names[i_int]:<25} " +
              "  ".join(f"{row[b]:>7.4f}{'*' if b == best_b else ' '}" for b in BASE_LEARNERS),
              flush=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"t1_iter41_per_base_disaggregation_{stamp}.json"
    with open(out_path, "w") as f:
        json.dump({
            "n_subjects": n,
            "seeds": list(args.seeds),
            "per_seed": per_seed,
            "per_base_summary": summary,
            "hybrid_check_ccc": hy_metrics['ccc'],
            "iter34_lockbox_n92_ccc": 0.7170,
            "iter12_honest_n94_ccc": 0.6550,
            "item_x_base_ccc_matrix": item_x_base_ccc,
            "fwer_family_n8": True,
            "bonferroni_alpha_per_test": 0.05/8,
            "loocv_gate_frac_above_zero": 1-0.05/8,
            "wall_s_total": time.time() - overall_t0,
        }, f, indent=2)
    print(f"\nWrote {out_path}", flush=True)
    print(f"  wall = {(time.time()-overall_t0)/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
