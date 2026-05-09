"""T1 iter34 — LOSO (leave-one-site-out) transportability.

Mechanism: applies iter34 hybrid architecture (Stage-1 Ridge on H&Y + cv_yrs +
cv_sex + cv_dbs; Stage-2 averaged RegressorChain over 8 items × {LGB, XGB-hist,
ExtraTrees}; T1 = sum predictions for items 9-14 only) to two cohort-shift
splits:
    NLS_to_WPD: train on all NLS subjects, predict on all WPD.
    WPD_to_NLS: train on all WPD subjects, predict on all NLS.

Reports per-direction CCC/MAE/r/slope and the two-way mean — the headline.
This is descriptive transportability, NOT a within-cohort lift claim, so NO
formula_sha256 lockbox is written. The within-cohort comparator is iter34's
LOOCV (CCC=0.7366); the LOOCV→LOSO gap quantifies cohort shift.

Per direction:
    1. Stage 1 Ridge fit on training-site only (per-fold standardisation).
    2. Stage 2 chain × 3 base learners fit on training-site residuals.
    3. Predictions on test-site (other site) — true zero-shot.
    4. 3 seeds for chain-order randomness; mean preds = headline per direction.

ProcessPool over (direction × seed) = 6 jobs (lighter than LOOCV's 279).

Usage:
    ./gpu.sh run_t1_iter34_loso.py --mode loso
    ./gpu.sh run_t1_iter34_loso.py --mode smoke   # NLS→WPD seed=42 only
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter33b_8item_chain import (
    _load_t1_cohort_with_8items,
    T1_SUM_ITEMS,
    AUX_ITEMS,
    ALL_ITEMS,
)
from run_t1_iter34_hybrid_8item_multibase import (
    BASE_LEARNERS,
    K_FEATURES,
    STAGE1_ALPHA,
    _multitask_predict,
)

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
ITER34_LOOCV_CCC = 0.7366  # within-cohort comparator (per_subject N=93)


def site_from_sid(sid: str) -> str:
    """NLS prefix → 'NLS'; otherwise 'WPD' (per CLAUDE.md / iter16 convention)."""
    return "NLS" if str(sid).startswith("NLS") else "WPD"


def site_arr(sids: np.ndarray) -> np.ndarray:
    return np.array([site_from_sid(s) for s in sids])


# -----------------------------------------------------------------------------
# Per-direction × per-seed worker (ProcessPool entry point — module-level).
# -----------------------------------------------------------------------------
def _fit_one_direction(args):
    """Worker: train iter34 hybrid on one site, predict on the other.

    args = (direction, tr, te, X, y_t1, X_s1, items, item_order, seed, bases)
    Returns (direction, seed, te_idx, pred, ccc, mae, r, slope, walltime).
    """
    direction, tr, te, X, y_t1, X_s1, items, item_order, seed, bases = args

    t0 = time.time()

    # Stage 1 Ridge on training site only
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    # Per-item train-mean centering
    item_means: dict[int, float] = {}
    items_tr_residual: list[np.ndarray] = []
    for i in item_order:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_residual)

    # Fold-local imputation + K=500 LGB-importance feature selection
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )

    # Stage 2: average chain predictions across 3 base learners
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

    pred = s1_te + (t1_pred_from_items - sum_means_t1)

    y_te = y_t1[te]
    metrics = full_metrics(y_te, pred, label=f"{direction}_seed{seed}")

    return {
        "direction": direction,
        "seed": int(seed),
        "te_idx": te.tolist(),
        "pred": pred.tolist(),
        "y_true": y_te.tolist(),
        "n_train": int(len(tr)),
        "n_test": int(len(te)),
        "ccc": float(metrics["ccc"]),
        "mae": float(metrics["mae"]),
        "r": float(metrics["r"]),
        "cal_slope": float(metrics["cal_slope"]),
        "wall_s": float(time.time() - t0),
    }


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------
def _build_jobs(sids, X, y_t1, X_s1, items, item_order, seeds):
    sites = site_arr(sids)
    nls_idx = np.where(sites == "NLS")[0]
    wpd_idx = np.where(sites == "WPD")[0]
    n = len(sids)
    if len(nls_idx) + len(wpd_idx) != n:
        raise AssertionError(
            f"site partition mismatch: NLS={len(nls_idx)} + WPD={len(wpd_idx)} != N={n}"
        )
    print(f"  partition: NLS N={len(nls_idx)} | WPD N={len(wpd_idx)} | total N={n}",
          flush=True)
    if len(nls_idx) < 5 or len(wpd_idx) < 5:
        raise AssertionError(
            f"site too small for transportability eval: NLS={len(nls_idx)}, WPD={len(wpd_idx)}"
        )

    jobs: list[tuple[Any, ...]] = []
    for seed in seeds:
        # NLS → WPD
        jobs.append((
            "NLS_to_WPD", nls_idx, wpd_idx, X, y_t1, X_s1, items, item_order,
            int(seed), BASE_LEARNERS,
        ))
        # WPD → NLS
        jobs.append((
            "WPD_to_NLS", wpd_idx, nls_idx, X, y_t1, X_s1, items, item_order,
            int(seed), BASE_LEARNERS,
        ))
    return jobs, nls_idx, wpd_idx


def run_loso(seeds: tuple[int, ...] = SEEDS_DEFAULT,
             feature_set: str = "A3_tier1",
             n_workers: int = 6) -> Path:
    print(
        f"\n=== T1 iter34 LOSO TRANSPORTABILITY ({len(seeds)} seeds, "
        f"bases={BASE_LEARNERS}, n_workers={n_workers}) ===",
        flush=True,
    )

    # Load cohort once (same as iter34 LOOCV: T1∩{15,18}, N≈93)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    jobs, nls_idx, wpd_idx = _build_jobs(sids, X, y_t1, X_s1, items, item_order, seeds)
    print(f"  total jobs: {len(jobs)} (2 directions × {len(seeds)} seeds)", flush=True)

    overall_t0 = time.time()
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_fit_one_direction, job): (job[0], job[8]) for job in jobs}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            print(
                f"  [{done}/{len(jobs)}] {r['direction']} seed={r['seed']}: "
                f"CCC={r['ccc']:.4f} | MAE={r['mae']:.3f} | r={r['r']:.4f} | "
                f"slope={r['cal_slope']:.3f} | n_tr={r['n_train']} | "
                f"n_te={r['n_test']} | wall={r['wall_s']:.0f}s",
                flush=True,
            )
    overall_wall = time.time() - overall_t0
    print(f"  total wall = {overall_wall:.0f}s ({overall_wall/60:.1f} min)", flush=True)

    # Aggregate per direction
    sids_str = [str(s) for s in sids]
    summary: dict[str, Any] = {
        "experiment": "T1 iter34 LOSO transportability",
        "iso_datetime": datetime.now().isoformat(),
        "n_subjects_total": int(n),
        "n_nls": int(len(nls_idx)),
        "n_wpd": int(len(wpd_idx)),
        "seeds": list(seeds),
        "bases": list(BASE_LEARNERS),
        "feature_set": feature_set,
        "item_order_chain": item_order,
        "auxiliary_items_used": list(available_aux),
        "iter34_loocv_ccc_within_cohort": ITER34_LOOCV_CCC,
        "wall_time_total_s": float(overall_wall),
        "notes": (
            "Descriptive transportability, NOT a within-cohort lift claim. "
            "No formula_sha256 lockbox. iter34 LOOCV CCC=0.7366 is the "
            "within-cohort comparator; LOOCV→LOSO gap quantifies cohort shift."
        ),
    }

    direction_blocks: dict[str, dict] = {}
    for direction in ("NLS_to_WPD", "WPD_to_NLS"):
        runs = sorted([r for r in results if r["direction"] == direction], key=lambda d: d["seed"])
        if not runs:
            raise AssertionError(f"no runs for direction {direction}")
        # Aggregate predictions across seeds (mean)
        # All runs share the same te_idx for a given direction.
        te_idx0 = runs[0]["te_idx"]
        for r in runs[1:]:
            if r["te_idx"] != te_idx0:
                raise AssertionError(
                    f"te_idx mismatch within direction={direction} across seeds"
                )
        preds_per_seed = np.array([r["pred"] for r in runs])  # (n_seeds, n_test)
        mean_pred = preds_per_seed.mean(axis=0)
        y_te = np.array(runs[0]["y_true"])
        agg = full_metrics(y_te, mean_pred, label=f"{direction}_meanofseeds")
        sids_te = [sids_str[i] for i in te_idx0]
        direction_blocks[direction] = {
            "n_train": runs[0]["n_train"],
            "n_test": runs[0]["n_test"],
            "ccc_meanofseed_preds": float(agg["ccc"]),
            "mae_meanofseed_preds": float(agg["mae"]),
            "r_meanofseed_preds": float(agg["r"]),
            "cal_slope_meanofseed_preds": float(agg["cal_slope"]),
            "per_seed": [
                {
                    "seed": r["seed"],
                    "ccc": r["ccc"],
                    "mae": r["mae"],
                    "r": r["r"],
                    "cal_slope": r["cal_slope"],
                    "wall_s": r["wall_s"],
                }
                for r in runs
            ],
            "ccc_seed_mean": float(np.mean([r["ccc"] for r in runs])),
            "ccc_seed_std": float(np.std([r["ccc"] for r in runs])),
            "test_sids": sids_te,
            "y_true": y_te.tolist(),
            "y_pred_meanofseed": mean_pred.tolist(),
        }

    # Two-way headline = mean of (NLS→WPD CCC, WPD→NLS CCC) on mean-of-seed preds
    ccc_n2w = direction_blocks["NLS_to_WPD"]["ccc_meanofseed_preds"]
    ccc_w2n = direction_blocks["WPD_to_NLS"]["ccc_meanofseed_preds"]
    two_way_mean_ccc = (ccc_n2w + ccc_w2n) / 2.0

    summary["headline_two_way_mean_ccc"] = float(two_way_mean_ccc)
    summary["ccc_NLS_to_WPD"] = float(ccc_n2w)
    summary["ccc_WPD_to_NLS"] = float(ccc_w2n)
    summary["mae_NLS_to_WPD"] = direction_blocks["NLS_to_WPD"]["mae_meanofseed_preds"]
    summary["mae_WPD_to_NLS"] = direction_blocks["WPD_to_NLS"]["mae_meanofseed_preds"]
    summary["r_NLS_to_WPD"] = direction_blocks["NLS_to_WPD"]["r_meanofseed_preds"]
    summary["r_WPD_to_NLS"] = direction_blocks["WPD_to_NLS"]["r_meanofseed_preds"]
    summary["cal_slope_NLS_to_WPD"] = direction_blocks["NLS_to_WPD"]["cal_slope_meanofseed_preds"]
    summary["cal_slope_WPD_to_NLS"] = direction_blocks["WPD_to_NLS"]["cal_slope_meanofseed_preds"]
    summary["loocv_minus_loso_gap"] = float(ITER34_LOOCV_CCC - two_way_mean_ccc)
    summary["per_direction"] = direction_blocks

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"iter34_loso_{ts}.json"
    with open(out_json, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    # Also write a stable filename per spec
    stable_path = RESULTS_DIR / "iter34_loso_2026_05_06.json"
    with open(stable_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(
        f"\n=== HEADLINE: two-way mean CCC = {two_way_mean_ccc:.4f} ===",
        flush=True,
    )
    print(
        f"  NLS→WPD: CCC={ccc_n2w:.4f} | "
        f"MAE={direction_blocks['NLS_to_WPD']['mae_meanofseed_preds']:.3f} | "
        f"r={direction_blocks['NLS_to_WPD']['r_meanofseed_preds']:.4f} | "
        f"slope={direction_blocks['NLS_to_WPD']['cal_slope_meanofseed_preds']:.3f} | "
        f"n_tr={direction_blocks['NLS_to_WPD']['n_train']} | "
        f"n_te={direction_blocks['NLS_to_WPD']['n_test']}",
        flush=True,
    )
    print(
        f"  WPD→NLS: CCC={ccc_w2n:.4f} | "
        f"MAE={direction_blocks['WPD_to_NLS']['mae_meanofseed_preds']:.3f} | "
        f"r={direction_blocks['WPD_to_NLS']['r_meanofseed_preds']:.4f} | "
        f"slope={direction_blocks['WPD_to_NLS']['cal_slope_meanofseed_preds']:.3f} | "
        f"n_tr={direction_blocks['WPD_to_NLS']['n_train']} | "
        f"n_te={direction_blocks['WPD_to_NLS']['n_test']}",
        flush=True,
    )
    print(
        f"  iter34 within-cohort LOOCV CCC = {ITER34_LOOCV_CCC:.4f}",
        flush=True,
    )
    print(
        f"  LOOCV→LOSO gap = {ITER34_LOOCV_CCC - two_way_mean_ccc:+.4f} "
        f"(cohort-shift transportability cliff)",
        flush=True,
    )
    print(f"Wrote {out_json}", flush=True)
    print(f"Wrote {stable_path}", flush=True)
    return out_json


# -----------------------------------------------------------------------------
# Smoke test
# -----------------------------------------------------------------------------
def smoke_test(seed: int = 42, feature_set: str = "A3_tier1") -> None:
    print("\n=== iter34 LOSO SMOKE TEST: NLS→WPD seed=42 ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    sites = site_arr(sids)
    nls_idx = np.where(sites == "NLS")[0]
    wpd_idx = np.where(sites == "WPD")[0]
    print(f"  cohort N={n} | NLS={len(nls_idx)} | WPD={len(wpd_idx)}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    args = ("NLS_to_WPD", nls_idx, wpd_idx, X, y_t1, X_s1, items, item_order,
            int(seed), BASE_LEARNERS)
    t0 = time.time()
    r = _fit_one_direction(args)
    print(
        f"  NLS→WPD seed={seed}: CCC={r['ccc']:.4f} | MAE={r['mae']:.3f} | "
        f"r={r['r']:.4f} | slope={r['cal_slope']:.3f} | "
        f"n_tr={r['n_train']} | n_te={r['n_test']} | wall={time.time()-t0:.1f}s",
        flush=True,
    )
    assert r["n_train"] + r["n_test"] == n, (
        f"sanity FAIL: n_tr+n_te={r['n_train']+r['n_test']} != N={n}"
    )
    assert np.isfinite(r["pred"]).all(), "non-finite predictions"
    print("  SMOKE PASS", flush=True)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["smoke", "loso"], required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument(
        "--n_workers", type=int,
        default=int(os.getenv("ITER34_LOSO_WORKERS", 6)),
    )
    args = ap.parse_args()
    if args.mode == "smoke":
        smoke_test(seed=args.seeds[0], feature_set=args.feature_set)
    else:
        run_loso(
            seeds=tuple(args.seeds),
            feature_set=args.feature_set,
            n_workers=args.n_workers,
        )


if __name__ == "__main__":
    main()
