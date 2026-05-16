"""iter34 5-fold OOF comparator for T1 ceiling push 2026-05-13.

This is NOT a new model variant — it is iter34's EXACT architecture re-run with
5-fold CV instead of LOOCV, on the same N=92 cohort and same KFold seeds as
Slot A, so the screen Δ can be computed apples-to-apples (5-fold to 5-fold).

Does NOT add to FWER family — this is a comparator computation, not a new claim.
"""
from __future__ import annotations

import os
os.environ.setdefault("PD_IMU_N_CORES", "1")
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import json
import multiprocessing as mp
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.model_selection import KFold

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn
from project_paths import RESULTS_DIR
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    load_clinical_dict,
)
from run_t1_iter33b_8item_chain import _load_t1_cohort_with_8items
from run_t1_iter34_hybrid_8item_multibase import _fit_one_fold, BASE_LEARNERS, T1_SUM_ITEMS, AUX_ITEMS

SEEDS = (42, 1337, 7)
N_SPLITS = 5


def _kfold_one_seed(seed, X, y_t1, X_s1, items, item_order, n_workers):
    n = len(y_t1)
    preds = np.zeros(n)
    kf = KFold(n_splits=N_SPLITS, shuffle=True, random_state=seed)
    splits = list(kf.split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, BASE_LEARNERS)
        for fid, (tr, te) in enumerate(splits)
    ]
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_fit_one_fold, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    print(f"  seed={seed} iter34_5fold wall={time.time()-t0:.0f}s", flush=True)
    return preds


def main():
    print("=== iter34 5-fold OOF comparator (T1 ceiling push 2026-05-13) ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    n = len(sids)
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])

    per_seed_ccc = []
    seed_preds = []
    for seed in SEEDS:
        p = _kfold_one_seed(seed, X, y_t1, X_s1, items, item_order, n_workers=2)
        c = float(ccc_fn(y_t1, p))
        per_seed_ccc.append({"seed": seed, "ccc_5fold": round(c, 4)})
        seed_preds.append(p)
        print(f"  iter34 5-fold seed={seed} CCC={c:.4f}", flush=True)

    pooled = np.mean(np.column_stack(seed_preds), axis=1)
    pooled_ccc = float(ccc_fn(y_t1, pooled))
    print(f"  iter34 5-fold pooled (mean of {len(SEEDS)} seeds): CCC={pooled_ccc:.4f}", flush=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter34_5fold_comparator_{ts}.json"
    npy = RESULTS_DIR / f"iter34_5fold_comparator_{ts}.oof.npy"
    np.save(npy, pooled)
    with open(out, "w") as f:
        json.dump({
            "name": "iter34 5-fold OOF comparator (apples-to-apples for ceiling push screen)",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "cohort_N": int(n),
            "kfold_n_splits": N_SPLITS,
            "kfold_seeds": list(SEEDS),
            "per_seed_ccc": per_seed_ccc,
            "pooled_5fold_ccc": round(pooled_ccc, 4),
            "iter34_loocv_canonical": 0.7170,
            "loocv_minus_5fold_gap": round(0.7170 - pooled_ccc, 4),
            "per_subject": {
                "sids": [str(s) for s in sids],
                "y_true": y_t1.tolist(),
                "y_pred_pooled": pooled.tolist(),
            },
        }, f, indent=2)
    print(f"  Wrote {out}")
    print(f"  Wrote {npy}")


if __name__ == "__main__":
    main()
