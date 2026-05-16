"""T1 iter34 per-item OOF disaggregation — FWER-free supplementary analysis.

Re-runs iter34 hybrid LOOCV on the corrected N=92 cohort but captures per-item
predictions (items 9-14 individually) alongside the T1 sum. Reports per-item CCC,
MAE, and Pearson r as a publishable supplementary table.

NOT a new mechanism / FWER family member: same chain, same seeds, same code path
as run_t1_iter34_hybrid_8item_multibase.py with N=92 (hygiene-corrected loader).
The disaggregation just exposes intermediate predictions that the canonical
lockbox marginalizes into the sum.

Output:
  results/t1_iter34_per_item_oof_<UTC>.npz  (sids, preds[6 items], truths[6 items])
  results/t1_iter34_per_item_ccc_<UTC>.json (per-item metrics table)

Usage:
  ./gpu.sh compute_t1_iter34_per_item_disaggregation.py --n_workers 5
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
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

from inductive_lib import ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter34_hybrid_8item_multibase import (
    BASE_LEARNERS,
    K_FEATURES,
    SEEDS_DEFAULT,
    STAGE1_ALPHA,
    _multitask_predict,
)
from run_t1_iter33b_8item_chain import (
    _load_t1_cohort_with_8items,
    AUX_ITEMS,
    T1_SUM_ITEMS,
)
from run_t3_iter2 import feature_select_fold, impute_fold
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)


def _per_item_worker(args):
    """Worker returning (te_idx, t1_sum_pred, per_item_pred_dict).

    per_item_pred_dict maps T1 item id (9..14) -> np.ndarray of test-fold preds.
    """
    fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases = args

    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    item_means: dict[int, float] = {}
    items_tr_residual: list[np.ndarray] = []
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

    ip_avg = None
    for b in bases:
        ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base=b)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg = ip_avg / len(bases)

    t1_sum_idx = [item_order.index(i) for i in T1_SUM_ITEMS]
    item_pred_t1 = ip_avg[:, t1_sum_idx] + np.array(
        [item_means[i] for i in T1_SUM_ITEMS]
    )
    t1_pred_from_items = item_pred_t1.sum(axis=1)
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))
    t1_sum = s1_te + (t1_pred_from_items - sum_means_t1)

    per_item = {int(item_id): item_pred_t1[:, k]
                for k, item_id in enumerate(T1_SUM_ITEMS)}
    return te, t1_sum, per_item


def _loocv_seed_per_item(seed, X, y_t1, X_s1, items, item_order, bases, n_workers):
    n = len(y_t1)
    t1_sum_preds = np.zeros(n)
    per_item_preds = {int(i): np.zeros(n) for i in T1_SUM_ITEMS}
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [(fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases)
            for fid, (tr, te) in enumerate(splits)]
    ctx = mp.get_context("spawn")
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_per_item_worker, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, t1_sum, per_item = fut.result()
            t1_sum_preds[te_idx] = t1_sum
            for item_id, pred in per_item.items():
                per_item_preds[item_id][te_idx] = pred
            done += 1
            if done % 20 == 0 or done == n:
                print(f"    seed={seed} {done}/{n} folds elapsed={time.time()-t0:.0f}s",
                      flush=True)
    return t1_sum_preds, per_item_preds


def _pearson(y, p):
    y = np.asarray(y, dtype=np.float64)
    p = np.asarray(p, dtype=np.float64)
    if y.std() == 0 or p.std() == 0:
        return 0.0
    return float(np.corrcoef(y, p)[0, 1])


def _mae(y, p):
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(p))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--n_workers", type=int, default=5)
    args = ap.parse_args()

    ensure_dir(RESULTS_DIR)

    print(f"=== iter34 PER-ITEM OOF DISAGGREGATION (N=92, hygiene-corrected) ===",
          flush=True)
    print(f"  seeds={args.seeds}, bases={BASE_LEARNERS}, n_workers={args.n_workers}",
          flush=True)

    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[args.feature_set])

    # Collect per-seed per-item OOFs
    t1_sums_per_seed = []
    per_item_preds_per_seed = {int(i): [] for i in T1_SUM_ITEMS}
    overall_t0 = time.time()
    for seed in args.seeds:
        t1_pred_seed, per_item_seed = _loocv_seed_per_item(
            seed, X, y_t1, X_s1, items, item_order, BASE_LEARNERS, args.n_workers
        )
        t1_sums_per_seed.append(t1_pred_seed)
        for item_id, pred in per_item_seed.items():
            per_item_preds_per_seed[item_id].append(pred)
        per_item_ccc = {int(i): ccc_fn(items[i], per_item_seed[i]) for i in T1_SUM_ITEMS}
        print(f"  seed={seed}: T1_sum_CCC={ccc_fn(y_t1, t1_pred_seed):.4f} | "
              f"per-item CCC: " + ", ".join(
                  f"{i}={per_item_ccc[i]:.3f}" for i in T1_SUM_ITEMS),
              flush=True)

    # Mean-of-seeds predictions
    t1_sum_mean = np.mean(t1_sums_per_seed, axis=0)
    per_item_mean = {int(i): np.mean(per_item_preds_per_seed[i], axis=0)
                     for i in T1_SUM_ITEMS}

    # Final metrics table (mean-of-seeds, then per-seed list)
    headline = {
        "n_subjects": n,
        "T1_sum_CCC": ccc_fn(y_t1, t1_sum_mean),
        "T1_sum_MAE": _mae(y_t1, t1_sum_mean),
        "T1_sum_r": _pearson(y_t1, t1_sum_mean),
        "per_item": {
            int(i): {
                "ccc_mean_of_seeds": float(ccc_fn(items[i], per_item_mean[i])),
                "mae_mean_of_seeds": _mae(items[i], per_item_mean[i]),
                "r_mean_of_seeds": _pearson(items[i], per_item_mean[i]),
                "ccc_per_seed": [float(ccc_fn(items[i], p))
                                 for p in per_item_preds_per_seed[i]],
                "true_mean": float(np.mean(items[i])),
                "true_std": float(np.std(items[i])),
                "pred_mean": float(np.mean(per_item_mean[i])),
                "pred_std": float(np.std(per_item_mean[i])),
            }
            for i in T1_SUM_ITEMS
        },
        "wall_s_total": time.time() - overall_t0,
        "seeds": list(args.seeds),
        "bases": list(BASE_LEARNERS),
        "feature_set": args.feature_set,
        "supersedes_lockbox": None,
        "based_on_lockbox": "results/lockbox_t1_iter34_hybrid_20260510_233019.json",
        "fwer_family_independence_claim": (
            "Per-item disaggregation is a marginalization of the same chain "
            "outputs. NOT a new FWER family member; equivalent to reading "
            "sub-totals from the same lockbox. Headline T1 sum CCC must match "
            "the canonical lockbox at N=92."
        ),
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = RESULTS_DIR / f"t1_iter34_per_item_ccc_{stamp}.json"
    with open(json_path, "w") as f:
        json.dump(headline, f, indent=2)
    print(f"\nWrote {json_path}", flush=True)

    # Save OOF as compressed numpy
    npz_path = RESULTS_DIR / f"t1_iter34_per_item_oof_{stamp}.npz"
    save_kwargs = dict(sids=sids, y_t1=y_t1, t1_sum_pred=t1_sum_mean)
    for i in T1_SUM_ITEMS:
        save_kwargs[f"item_{i}_true"] = items[i]
        save_kwargs[f"item_{i}_pred"] = per_item_mean[i]
    np.savez_compressed(npz_path, **save_kwargs)
    print(f"Wrote {npz_path}", flush=True)

    # Print final table
    print("\n=== Per-item CCC table (N=92, mean of 3 seeds) ===", flush=True)
    print(f"  {'item':>4}  {'name':<25}  {'CCC':>7}  {'MAE':>7}  {'r':>7}  "
          f"{'true_mean':>9}  {'true_std':>9}", flush=True)
    names = {9: "arising from chair", 10: "gait", 11: "freezing of gait",
             12: "postural stability", 13: "posture",
             14: "body bradykinesia"}
    for i in T1_SUM_ITEMS:
        pi = headline["per_item"][int(i)]
        print(f"  {i:>4}  {names[i]:<25}  {pi['ccc_mean_of_seeds']:>7.4f}  "
              f"{pi['mae_mean_of_seeds']:>7.4f}  {pi['r_mean_of_seeds']:>7.4f}  "
              f"{pi['true_mean']:>9.3f}  {pi['true_std']:>9.3f}",
              flush=True)
    print(f"  {'SUM':>4}  {'T1 = sum(items 9-14)':<25}  "
          f"{headline['T1_sum_CCC']:>7.4f}  {headline['T1_sum_MAE']:>7.4f}  "
          f"{headline['T1_sum_r']:>7.4f}  "
          f"{float(np.mean(y_t1)):>9.3f}  {float(np.std(y_t1)):>9.3f}",
          flush=True)
    print(f"\n  wall = {headline['wall_s_total']:.0f}s "
          f"({headline['wall_s_total']/60:.1f} min)", flush=True)


if __name__ == "__main__":
    main()
