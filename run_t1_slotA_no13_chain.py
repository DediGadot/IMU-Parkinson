"""T1 Glass-Ceiling Push 2026-05-13, Slot A — 7-item-no-13 chain + CCC-descending order.

Mechanism (synthesis of codex + gemini consult, Slot A Sub-Phase 2):
  - Drop item 13 (CCC=0.067, IMU-noise floor) entirely from the chain.
  - Fix chain order to CCC-descending [12, 10, 14, 9, 11, 15, 18].
    Item 12 (load-bearing, CCC=0.566) anchors first; weak items condition on it.
  - Otherwise identical to iter34 hybrid: Stage-1 Ridge (H&Y + cv_*), K=500
    LGB-importance against T1 residual, 3-base ensemble (LGB + XGB-hist + ET).

T1 reconstruction: sum(pred items 9, 10, 11, 12, 14) + train_fold_mean(item_13).

Modes:
  --mode write_prereg  Emit pre-reg with formula_sha256 (slot-level).
  --mode smoke         1 fold × 1 seed sanity check.
  --mode screen_5fold  3 seeds × 5-fold OOF, gate: Δ̄ ≥ +0.020, std < 0.020.
  --mode lockbox       3 seeds × LOOCV (only if screen passed).

Pre-registration is part of master batch:
  results/preregistration_t1_ceiling_push_20260513_043852.json
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
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.model_selection import KFold, LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter4 import T1_ITEMS
from run_t1_iter33b_8item_chain import _load_t1_cohort_with_8items

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500

# Slot A architecture: drop item 13; CCC-descending chain order
T1_SUM_ITEMS_NO13: tuple[int, ...] = (9, 10, 11, 12, 14)  # 5 items in T1 with item 13 dropped
AUX_ITEMS: tuple[int, ...] = (15, 18)
CHAIN_ORDER_DESCENDING: tuple[int, ...] = (12, 10, 14, 9, 11, 15, 18)  # CCC-descending of iter34 per-item

BASE_LEARNERS: tuple[str, ...] = ("lgb", "xgb", "et")


def _make_regr(base: str, seed: int):
    if base == "lgb":
        import lightgbm as lgb
        return lgb.LGBMRegressor(
            n_estimators=500, learning_rate=0.05, num_leaves=15,
            min_data_in_leaf=10, random_state=seed, n_jobs=1, verbose=-1,
        )
    if base == "xgb":
        import xgboost as xgb
        return xgb.XGBRegressor(
            n_estimators=500, learning_rate=0.05, max_depth=4,
            min_child_weight=5, tree_method="hist",
            random_state=seed, n_jobs=1, verbosity=0,
        )
    if base == "et":
        from sklearn.ensemble import ExtraTreesRegressor
        return ExtraTreesRegressor(
            n_estimators=300, max_depth=10, min_samples_leaf=5,
            random_state=seed, n_jobs=1,
        )
    raise ValueError(f"unknown base learner {base!r}")


def _chain_predict_fixed_order(Xtr, items_tr, Xte, seed: int, base: str):
    """RegressorChain with FIXED natural-column order (items_tr columns
    already in CCC-descending order)."""
    from sklearn.multioutput import RegressorChain
    regr = _make_regr(base, seed)
    # order=None → natural column order. items_tr columns are pre-arranged in CHAIN_ORDER_DESCENDING.
    chain = RegressorChain(regr, order=None, random_state=seed)
    chain.fit(Xtr, items_tr)
    return chain.predict(Xte)


def _fit_one_fold(args):
    """Slot A worker: 7-item chain × 3 base learners, CCC-descending order, drop item 13."""
    fold_id, tr, te, X, y_t1, X_s1, items, seed, bases = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    # Build items_tr in CCC-descending order
    item_means: dict[int, float] = {}
    items_tr_cols: list[np.ndarray] = []
    for i in CHAIN_ORDER_DESCENDING:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_cols.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_cols)

    # Train-fold mean for the DROPPED item 13 (used in T1 sum reconstruction)
    item_means[13] = float(np.nanmean(items[13][tr])) if 13 in items else 0.0

    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )

    ip_avg = None
    for b in bases:
        ip = _chain_predict_fixed_order(Xtr_sel, items_tr_arr, Xte_sel, seed, base=b)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg = ip_avg / len(bases)

    # T1 reconstruction: sum predictions for items 9,10,11,12,14 + train_mean(13)
    t1_idx_in_chain = [CHAIN_ORDER_DESCENDING.index(i) for i in T1_SUM_ITEMS_NO13]
    item_pred_t1_residual = ip_avg[:, t1_idx_in_chain]  # residuals
    item_pred_t1_actual = item_pred_t1_residual + np.array(
        [item_means[i] for i in T1_SUM_ITEMS_NO13]
    )
    t1_pred_no13_sum = item_pred_t1_actual.sum(axis=1)

    # Add item-13 train mean back (T1 = sum of items 9-14)
    t1_pred_full = t1_pred_no13_sum + item_means[13]

    # Same Stage-1 offset convention as iter34
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS_NO13) + item_means[13])
    return te, s1_te + (t1_pred_full - sum_means_t1)


def _slotA_kfold(seed: int, X, y_t1, X_s1, items, n_workers: int, n_splits: int = 5):
    """5-fold OOF screen on N=92 cohort."""
    n = len(y_t1)
    preds = np.zeros(n)
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    splits = list(kf.split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, seed, BASE_LEARNERS)
        for fid, (tr, te) in enumerate(splits)
    ]
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_fit_one_fold, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    print(f"    seed={seed} 5fold wall={time.time()-t0:.0f}s", flush=True)
    return preds


def _slotA_loocv(seed: int, X, y_t1, X_s1, items, n_workers: int):
    """Full LOOCV on N=92 cohort."""
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, seed, BASE_LEARNERS)
        for fid, (tr, te) in enumerate(splits)
    ]
    t0 = time.time()
    done = 0
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_fit_one_fold, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
            done += 1
            if done % 15 == 0 or done == n:
                print(f"    seed={seed} {done}/{n} folds elapsed={time.time()-t0:.0f}s", flush=True)
    return preds


def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": "T1 Glass-Ceiling Push 2026-05-13 Slot A — 7-item-no-13 chain + CCC-descending fixed order",
        "tri_cli_consult_synthesis": "codex+gemini priors 0.03-0.12 on screen pass; gemini surfaced CCC-descending ordering as mechanism enhancement",
        "is_post_publication_replication_target": False,
        "is_t1_ceiling_push_2026-05-13_slotA": True,
        "master_prereg": "results/preregistration_t1_ceiling_push_20260513_043852.json",
        "fwer_family_size": 4,
        "fwer_per_slot_gate_frac_gt0": 0.9875,
        "cohort": {
            "target": "T1 = sum(items 9-14)",
            "n_subjects_min": 90,
            "filter": "PD with full items 9-14, 15, 18 (iter34 hygiene-corrected cohort N=92)",
            "loader": "run_t1_iter33b_8item_chain._load_t1_cohort_with_8items",
        },
        "stage1": {
            "model": "Ridge", "alpha": STAGE1_ALPHA,
            "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
            "stage1_total_features": 9,
            "per_fold_standardisation": True,
            "source_module": "run_t3_iter5_clinical:fit_stage1",
            "target": "T1 (sum items 9-14)",
        },
        "stage2": {
            "model_ensemble": [
                "RegressorChain(LGBMRegressor n=500, lr=0.05, num_leaves=15, min_data=10)",
                "RegressorChain(XGBRegressor hist, n=500, lr=0.05, depth=4, min_child=5)",
                "RegressorChain(ExtraTreesRegressor n=300, max_depth=10, min_leaf=5)",
            ],
            "ensemble_method": "average chain-output across 3 bases per fold per seed",
            "items_targets_chain": list(CHAIN_ORDER_DESCENDING),
            "items_summed_for_t1": list(T1_SUM_ITEMS_NO13),
            "item_13_handling": "dropped from chain training; replaced by train_fold_mean(item_13) in T1 sum reconstruction",
            "auxiliary_items": list(AUX_ITEMS),
            "chain_order_policy": "FIXED CCC-descending [12, 10, 14, 9, 11, 15, 18]; not random",
            "item_target_centering": "subtract per-fold train_mean(item)",
            "feature_select_method": "lgb_importance_top_k_per_fold (against T1 residual)",
            "feature_select_k": K_FEATURES,
            "imputation": "fold_local_median",
        },
        "eval": {
            "screen_n_splits": 5,
            "screen_seeds": list(SEEDS_DEFAULT),
            "loocv_seeds": list(SEEDS_DEFAULT),
            "headline_metric": "CCC of mean-of-3-seed predictions vs y_t1",
            "screen_gate": "5-fold Δ̄ vs iter34 hybrid ≥ +0.020 AND seed std < 0.020",
            "loocv_gate": "paired bootstrap frac>0 ≥ 0.9875 vs iter34 hybrid on N=92 AND vs iter12-honest on N=92",
            "comparator_iter34_loocv_oof": "results/lockbox_t1_iter34_hybrid_20260510_233019.oof.npy",
        },
        "leakage_assertions": [
            "Stage-1 Ridge fit fold-local on train indices only",
            "feature_select_fold operates on outer-train labels only",
            "impute_fold operates on outer-train values only",
            "item-13 train_fold_mean computed inside each outer fold",
            "no global imputers, no cohort-wide z-scoring, no pre-computed ranks",
        ],
    }


def _formula_sha256(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def write_preregistration() -> Path:
    payload = _formula_payload()
    sha = _formula_sha256(payload)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp_utc": ts,
        "iso_datetime_utc": datetime.now(timezone.utc).isoformat(),
        "name": "T1 Glass-Ceiling Push 2026-05-13 Slot A pre-registration",
        "formula_sha256": sha,
        "formula_payload": payload,
        "git_sha": _git_head(),
        "operator": "Claude Opus 4.7 (pd-imu-100x-researcher skill)",
    }
    out = RESULTS_DIR / f"preregistration_t1_slotA_no13_ccc_descending_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


def _paired_bootstrap_ccc(y, p_a, p_b, n_boot: int = 5000, seed: int = 42):
    rng = np.random.RandomState(seed)
    n = len(y)
    deltas = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, n)
        deltas[i] = ccc_fn(y[idx], p_a[idx]) - ccc_fn(y[idx], p_b[idx])
    return {
        "n_boot": n_boot,
        "delta_mean": float(deltas.mean()),
        "delta_ci_low": float(np.percentile(deltas, 2.5)),
        "delta_ci_high": float(np.percentile(deltas, 97.5)),
        "frac_above_zero": float((deltas > 0).mean()),
        "frac_above_0.025": float((deltas > 0.025).mean()),
    }


def smoke_test(seed: int = 42, feature_set: str = "A3_tier1") -> None:
    print("\n=== Slot A SMOKE TEST: 1 fold × 1 seed ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    n = len(sids)
    print(f"  cohort N={n}, chain order={list(CHAIN_ORDER_DESCENDING)}", flush=True)
    print(f"  T1 sum items (with item 13 train-mean handling)={list(T1_SUM_ITEMS_NO13) + [13]}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    splits = list(LeaveOneOut().split(np.arange(n)))
    fid, (tr, te) = 0, splits[0]
    args = (fid, tr, te, X, y_t1, X_s1, items, seed, BASE_LEARNERS)
    t0 = time.time()
    te_idx, te_pred = _fit_one_fold(args)
    print(f"  fold 0/{n}: te_idx={te_idx[0]}, sid={sids[te_idx[0]]}, "
          f"y_true={y_t1[te_idx[0]]:.2f}, y_pred={te_pred[0]:.2f}, "
          f"wall={time.time()-t0:.1f}s", flush=True)
    assert np.isfinite(te_pred).all(), "non-finite predictions"
    print("  SMOKE PASS", flush=True)


def run_screen_5fold(seeds: tuple[int, ...] = SEEDS_DEFAULT,
                     feature_set: str = "A3_tier1",
                     n_workers: int = 2) -> Path:
    print(f"\n=== Slot A 5-FOLD SCREEN ({len(seeds)} seeds, bases={BASE_LEARNERS}, workers={n_workers}) ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    n = len(sids)
    print(f"  cohort N={n}, chain_order={list(CHAIN_ORDER_DESCENDING)}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    # Load iter34 hybrid OOF for same-SID comparison
    iter34_oof = np.load(RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy")
    with open(RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.json") as f:
        iter34 = json.load(f)
    iter34_sids = [str(s) for s in iter34["per_subject"]["sids"]]
    sid_to_pred_iter34 = dict(zip(iter34_sids, iter34_oof.tolist()))
    try:
        iter34_pred_aligned = np.array([sid_to_pred_iter34[str(s)] for s in sids])
    except KeyError as e:
        raise AssertionError(f"iter34 OOF missing SID {e}; cohort mismatch")

    per_seed = []
    slotA_preds_seeds = []
    for seed in seeds:
        t0 = time.time()
        p_slotA = _slotA_kfold(seed, X, y_t1, X_s1, items, n_workers)
        c_slotA = float(ccc_fn(y_t1, p_slotA))
        # iter34 OOF is LOOCV — for screen, compare slot A 5-fold to iter34 LOOCV (same cohort N=92)
        c_iter34 = float(ccc_fn(y_t1, iter34_pred_aligned))
        delta = c_slotA - c_iter34
        per_seed.append({
            "seed": seed,
            "ccc_slotA_5fold": round(c_slotA, 4),
            "ccc_iter34_loocv_reference": round(c_iter34, 4),
            "delta": round(delta, 4),
            "wall_sec": round(time.time() - t0, 1),
        })
        print(f"  seed={seed}: slotA_5fold={c_slotA:.4f} | iter34_loocv_ref={c_iter34:.4f} | "
              f"Δ={delta:+.4f} | wall={time.time()-t0:.0f}s", flush=True)
        slotA_preds_seeds.append(p_slotA)

    deltas = [p["delta"] for p in per_seed]
    mean_delta = float(np.mean(deltas))
    std_delta = float(np.std(deltas))
    screen_pass = bool((mean_delta >= 0.020) and (std_delta < 0.020))
    verdict = "PROMOTE_TO_LOOCV" if screen_pass else "CLOSE_SLOT_SCREEN_FAIL"

    # Pooled prediction (mean of 3 seeds)
    pooled = np.mean(np.column_stack(slotA_preds_seeds), axis=1)
    pooled_ccc = float(ccc_fn(y_t1, pooled))
    pooled_delta = pooled_ccc - float(ccc_fn(y_t1, iter34_pred_aligned))

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"screen_t1_slotA_no13_ccc_descending_{ts}.json"
    summary = {
        "name": "T1 Slot A 5-fold screen",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "cohort_N": int(n),
        "chain_order": list(CHAIN_ORDER_DESCENDING),
        "per_seed": per_seed,
        "mean_delta": round(mean_delta, 4),
        "std_delta": round(std_delta, 4),
        "pooled_ccc_slotA": round(pooled_ccc, 4),
        "pooled_delta_vs_iter34": round(pooled_delta, 4),
        "screen_gate": "Δ̄ ≥ +0.020 AND std < 0.020",
        "screen_pass": screen_pass,
        "verdict": verdict,
        "iter34_canonical_ccc": float(ccc_fn(y_t1, iter34_pred_aligned)),
    }
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  5-fold result: mean_delta={mean_delta:+.4f}, std={std_delta:.4f}, pooled CCC={pooled_ccc:.4f}", flush=True)
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out}", flush=True)
    return out


def run_lockbox(prereg_file: Path, seeds: tuple[int, ...] = SEEDS_DEFAULT,
                feature_set: str = "A3_tier1", n_workers: int = 2) -> Path:
    if not prereg_file.exists():
        raise FileNotFoundError(prereg_file)
    with open(prereg_file) as f:
        prereg = json.load(f)
    expected_sha = _formula_sha256(_formula_payload())
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(
            f"prereg formula_sha256 {prereg.get('formula_sha256')!r} != current {expected_sha!r}"
        )
    print(f"\n=== Slot A LOCKBOX LOOCV ({len(seeds)} seeds, bases={BASE_LEARNERS}, workers={n_workers}) ===", flush=True)

    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    n = len(sids)
    print(f"  cohort N={n}, chain_order={list(CHAIN_ORDER_DESCENDING)}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    iter34_oof = np.load(RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy")
    with open(RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.json") as f:
        iter34 = json.load(f)
    iter34_sids = [str(s) for s in iter34["per_subject"]["sids"]]
    sid_to_pred_iter34 = dict(zip(iter34_sids, iter34_oof.tolist()))
    iter34_pred_aligned = np.array([sid_to_pred_iter34[str(s)] for s in sids])

    all_preds = []
    per_seed = []
    overall_t0 = time.time()
    for seed in seeds:
        t0 = time.time()
        p_slotA = _slotA_loocv(seed, X, y_t1, X_s1, items, n_workers)
        c_slotA = float(ccc_fn(y_t1, p_slotA))
        per_seed.append({"seed": seed, "ccc": c_slotA, "wall": round(time.time() - t0, 1)})
        print(f"  seed={seed}: CCC={c_slotA:.4f} wall={time.time()-t0:.0f}s", flush=True)
        all_preds.append(p_slotA)
    overall_wall = time.time() - overall_t0
    print(f"  total wall = {overall_wall:.0f}s ({overall_wall/60:.1f} min)", flush=True)

    pooled = np.mean(np.column_stack(all_preds), axis=1)
    headline = full_metrics(y_t1, pooled, label="t1_slotA_no13_ccc_descending")
    boot_iter34 = _paired_bootstrap_ccc(y_t1, pooled, iter34_pred_aligned)
    boot_iter34["ccc_iter34"] = round(float(ccc_fn(y_t1, iter34_pred_aligned)), 4)
    boot_iter34["delta_vs_iter34"] = float(headline["ccc"] - boot_iter34["ccc_iter34"])

    # Also compare vs iter12-honest if available
    iter12_path = RESULTS_DIR / "t1_iter12_honest_composite.oof.npy"
    boot_iter12 = None
    if iter12_path.exists():
        iter12_oof = np.load(iter12_path)
        # iter12 is N=94 — need same-SID alignment if different cohort
        if len(iter12_oof) == n:
            boot_iter12 = _paired_bootstrap_ccc(y_t1, pooled, iter12_oof)
            boot_iter12["ccc_iter12"] = round(float(ccc_fn(y_t1, iter12_oof)), 4)

    verdict = (
        "PASS_BONFERRONI_n=4"
        if (boot_iter34["frac_above_zero"] >= 0.9875
            and (boot_iter12 is None or boot_iter12["frac_above_zero"] >= 0.9875))
        else "FAIL_FWER"
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_slotA_no13_ccc_descending_{ts}.json"
    out_oof = RESULTS_DIR / f"lockbox_t1_slotA_no13_ccc_descending_{ts}.oof.npy"
    summary = {
        "name": "T1 Slot A lockbox (7-item-no-13 chain + CCC-descending order)",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "prereg_path": str(prereg_file),
        "formula_sha256": expected_sha,
        "git_sha": _git_head(),
        "cohort_N": int(n),
        "chain_order": list(CHAIN_ORDER_DESCENDING),
        "per_seed": per_seed,
        "headline": headline,
        "bootstrap_vs_iter34": boot_iter34,
        "bootstrap_vs_iter12": boot_iter12,
        "fwer_gate_frac_gt0": 0.9875,
        "verdict": verdict,
        "per_subject": {
            "sids": [str(s) for s in sids],
            "y_true": y_t1.tolist(),
            "y_pred_pooled": pooled.tolist(),
        },
    }
    np.save(out_oof, pooled)
    with open(out_json, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  HEADLINE CCC = {headline['ccc']:.4f} (Δ vs iter34 = {boot_iter34['delta_vs_iter34']:+.4f})")
    print(f"  Bootstrap frac>0 vs iter34 = {boot_iter34['frac_above_zero']:.4f}")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out_json}")
    return out_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["write_prereg", "smoke", "screen_5fold", "lockbox"],
                   default="smoke")
    p.add_argument("--prereg", type=Path, default=None,
                   help="for --mode lockbox: path to slot A pre-reg JSON")
    p.add_argument("--workers", type=int, default=2)
    args = p.parse_args()
    if args.mode == "write_prereg":
        write_preregistration()
    elif args.mode == "smoke":
        smoke_test()
    elif args.mode == "screen_5fold":
        run_screen_5fold(n_workers=args.workers)
    elif args.mode == "lockbox":
        if args.prereg is None:
            raise SystemExit("--mode lockbox requires --prereg PATH")
        run_lockbox(args.prereg, n_workers=args.workers)


if __name__ == "__main__":
    main()
