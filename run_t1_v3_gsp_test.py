"""T1 V3-GSP test — substitute V2 with V3-GSP features in the iter34 chain.

Goal: empirically test whether V3-GSP (550 multi-sensor graph-spectrum features)
matches or beats V2 (1875 per-sensor statistical features) when plugged into the
canonical iter34 8-item chain × 3-base ensemble.

Three modes:
  --mode v3_only     : iter34 chain on V3-GSP features alone, K=500 (truncated)
  --mode v2_v3_append: iter34 chain on V2 + V3-GSP, K=500 selection
  --mode v3_no_kselect: iter34 chain on V3-GSP only, no K=500 (all 550 features)

Comparator: iter34 hygiene-corrected OOF (lockbox_t1_iter34_hybrid_20260510_233019).
Cohort: N=92 hygiene-corrected (same as iter34).
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
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features, fit_stage1, load_clinical_dict,
)
from run_t1_iter33b_8item_chain import (
    _load_t1_cohort_with_8items, T1_SUM_ITEMS,
)
from run_t1_iter34_hybrid_8item_multibase import (
    BASE_LEARNERS, K_FEATURES, SEEDS_DEFAULT, STAGE1_ALPHA,
    _multitask_predict, _paired_bootstrap_ccc,
)
from run_t3_iter54_dann_tier2 import (
    per_subject_signflip_pvalue, bca_ci_delta_ccc, joint_promotion_decision,
)

ensure_dir(RESULTS_DIR)

V3_GSP_CSV = RESULTS_DIR / "v3_gsp_features.csv"
ITER34_OOF = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"
ITER34_JSON = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.json"
ITER34_CCC = 0.7170


def _load_v3_features(sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Load V3-GSP features aligned to the given SID order."""
    df = pd.read_csv(V3_GSP_CSV)
    df["sid"] = df["sid"].astype(str)
    sid_to_row = df.set_index("sid")
    feat_cols = [c for c in df.columns if c != "sid"]
    rows = []
    missing = []
    for s in sids:
        s = str(s)
        if s in sid_to_row.index:
            rows.append(sid_to_row.loc[s, feat_cols].values.astype(np.float64))
        else:
            missing.append(s)
            rows.append(np.full(len(feat_cols), np.nan))
    if missing:
        print(f"  WARNING: {len(missing)} SIDs missing from V3-GSP: {missing}",
              flush=True)
    X = np.array(rows)
    return X, feat_cols


def _fit_one_fold_v3(args):
    fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases, use_kselect = args

    # Stage-1
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    # Per-item residuals for chain training
    item_means: dict[int, float] = {}
    items_tr_residual = []
    for i in item_order:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_residual)

    # Imputation (fold-local median)
    Xtr_imp, Xte_imp = impute_fold(X[tr], X[te])

    # Optional K=500 LGB-importance selection
    if use_kselect:
        k = min(K_FEATURES, Xtr_imp.shape[1])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr_imp, y_t1[tr] - s1_tr, Xte_imp, k=k, seed=seed
        )
    else:
        Xtr_sel, Xte_sel = Xtr_imp, Xte_imp

    # 3-base ensemble
    ip_avg = None
    for b in bases:
        ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base=b)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg = ip_avg / len(bases)

    # T1 sum = sum predictions for items 9-14 only
    t1_sum_idx = [item_order.index(i) for i in T1_SUM_ITEMS]
    item_pred_t1 = ip_avg[:, t1_sum_idx] + np.array(
        [item_means[i] for i in T1_SUM_ITEMS]
    )
    t1_pred_from_items = item_pred_t1.sum(axis=1)
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))

    return te, s1_te + (t1_pred_from_items - sum_means_t1)


def loocv_run(seed: int, X, y_t1, X_s1, items, item_order, bases, use_kselect, n_workers):
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases, use_kselect)
        for fid, (tr, te) in enumerate(splits)
    ]
    t0 = time.time()
    done = 0
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_fit_one_fold_v3, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
            done += 1
            if done % 20 == 0 or done == n:
                print(
                    f"    seed={seed} fold {done}/{n} elapsed={time.time()-t0:.0f}s",
                    flush=True,
                )
    return preds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode", required=True,
        choices=["v3_only", "v2_v3_append", "v3_no_kselect"],
    )
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--n_workers", type=int, default=5)
    args = ap.parse_args()

    print(f"\n=== V3-GSP TEST — mode={args.mode}, seeds={args.seeds} ===", flush=True)

    # Load iter34 cohort
    sids, X_v2, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)

    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])

    # Load V3-GSP features aligned to iter34 SIDs
    X_v3, v3_cols = _load_v3_features(sids)
    print(f"  V2 feature count = {X_v2.shape[1]}", flush=True)
    print(f"  V3-GSP feature count = {X_v3.shape[1]}", flush=True)

    # Build the feature matrix per mode
    if args.mode == "v3_only":
        X = X_v3
        use_kselect = True
    elif args.mode == "v3_no_kselect":
        X = X_v3
        use_kselect = False
    elif args.mode == "v2_v3_append":
        X = np.column_stack([X_v2, X_v3])
        use_kselect = True
    else:
        raise ValueError(f"unknown mode {args.mode!r}")
    print(f"  X.shape after mode = {X.shape}", flush=True)
    print(f"  use_kselect = {use_kselect}", flush=True)

    # Run LOOCV per seed
    all_preds = []
    per_seed = []
    overall_t0 = time.time()
    for seed in args.seeds:
        t0 = time.time()
        p = loocv_run(seed, X, y_t1, X_s1, items, item_order, BASE_LEARNERS,
                      use_kselect, args.n_workers)
        c = float(ccc_fn(y_t1, p))
        per_seed.append({"seed": seed, "ccc": c, "wall_s": time.time() - t0})
        print(f"  seed={seed}: CCC={c:.4f} wall={time.time()-t0:.0f}s",
              flush=True)
        all_preds.append(p)
    overall_wall = time.time() - overall_t0

    mean_pred = np.mean(np.column_stack(all_preds), axis=1)
    headline = full_metrics(y_t1, mean_pred, label=f"t1_v3_gsp_{args.mode}")
    print(f"\n=== HEADLINE CCC = {headline['ccc']:.4f} ===", flush=True)
    print(f"  Δ vs iter34 = {headline['ccc'] - ITER34_CCC:+.4f}", flush=True)

    # Bootstrap vs iter34
    if ITER34_OOF.exists() and ITER34_JSON.exists():
        with open(ITER34_JSON) as f:
            j = json.load(f)
        sids_h = [str(s) for s in j["per_subject"]["sids"]]
        p_h_full = np.load(ITER34_OOF)
        sid_to_pred = dict(zip(sids_h, p_h_full.tolist()))
        try:
            p_h = np.array([sid_to_pred[str(s)] for s in sids])
            sign_flip = per_subject_signflip_pvalue(
                y_t1, mean_pred, p_h, n_perms=10000, seed=42
            )
            bca = bca_ci_delta_ccc(
                y_t1, mean_pred, p_h, n_boot=5000, seed=42
            )
            decision = joint_promotion_decision(
                {"sign_flip": sign_flip, "bca": bca},
                bonferroni_p_threshold=0.05,  # uncorrected single test
                mcid_delta=0.025,
            )
            print(f"  sign-flip p (one-sided, vs iter34) = {sign_flip['p_one_sided']:.4f}",
                  flush=True)
            print(f"  BCa 95% CI on ΔCCC = [{bca['ci_low']:+.4f}, {bca['ci_high']:+.4f}]",
                  flush=True)
            print(f"  decision verdict (uncorrected): {decision['verdict']}",
                  flush=True)
        except KeyError as e:
            print(f"  comparator alignment failed: {e}", flush=True)
            sign_flip = bca = decision = None
    else:
        sign_flip = bca = decision = None

    out = {
        "mode": args.mode,
        "n_subjects": n,
        "seeds": args.seeds,
        "feature_count_used": X.shape[1],
        "k_selection": use_kselect,
        "per_seed": per_seed,
        "headline": headline,
        "comparator_iter34_ccc": ITER34_CCC,
        "delta_vs_iter34_observed": headline["ccc"] - ITER34_CCC,
        "sign_flip": sign_flip,
        "bca": bca,
        "decision": decision,
        "wall_time_total_s": overall_wall,
        "per_subject": {
            "sids": [str(s) for s in sids],
            "y_true": y_t1.tolist(),
            "y_pred": mean_pred.tolist(),
        },
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"lockbox_t1_v3_gsp_{args.mode}_{ts}.json"
    npy_path = RESULTS_DIR / f"lockbox_t1_v3_gsp_{args.mode}_{ts}.oof.npy"
    np.save(npy_path, mean_pred)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote {out_path}", flush=True)
    return out_path


if __name__ == "__main__":
    main()
