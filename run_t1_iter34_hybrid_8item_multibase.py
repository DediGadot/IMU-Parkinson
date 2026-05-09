"""T1 iter34 — HYBRID: 8-item auxiliary chain × multi-base ensemble {LGB, XGB-hist, ExtraTrees}.

Mechanism: combines two near-canonical lifts measured at LOOCV:
  • iter33-B (F68): 8-item auxiliary chain on {9,10,11,12,13,14,15,18} → CCC=0.7219,
    Δ_vs_iter5=+0.0723, frac>0=0.979 (canonical-update on N=93).
  • iter33-C (F69): multi-base ensemble {LGB, XGB-hist, ExtraTrees} on 6-item chain
    → CCC=0.7231, Δ_vs_iter5=+0.0522, frac>0=0.937.

Both lifts are real but neither cleanly clears Bonferroni-adjusted family-wise α
across the 9-probe iter33 family (council 2026-05-06). This script pre-registers
the structural product (8-item chain × 3 base learners) as a SINGLE
POST-PUBLICATION REPLICATION TARGET — independent of the iter33-B canonical-update
family-wise comparison. Pre-registration carries an explicit
`is_post_publication_replication_target: True` flag in formula_sha256 to
prevent future leakage between this run and the canonical-update family.

Per fold per seed: train 3 RegressorChain bases over 8 items {9-14, 15, 18}
(items 15+18 auxiliary; T1 = sum predictions for 9-14 only); average chain output
across the 3 base learners; combine with iter5 Stage-1 Ridge prediction.

ProcessPool-parallel over LOOCV folds (≈ N×n_seeds = 93×3 = 279 fold-jobs)
to saturate the 17-core remote slave.

  --mode write_prereg  → emit pre-reg with formula_sha256 + replication-target flag.
  --mode lockbox       → load pre-reg, verify SHA, run LOOCV.
  --mode smoke         → 1 fold × 1 seed sanity check.
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.model_selection import LeaveOneOut

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
from run_t1_iter33b_8item_chain import (
    _load_t1_cohort_with_8items,
    T1_SUM_ITEMS,
    AUX_ITEMS,
    ALL_ITEMS,
)

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500
PUBLISHED_T1_LOOCV_CCC = 0.6550
ITER33B_LOOCV_CCC = 0.7219  # F68 8-item chain canonical-update candidate
ITER33C_LOOCV_CCC = 0.7231  # F69 multi-base 6-item ensemble

BASE_LEARNERS: tuple[str, ...] = ("lgb", "xgb", "et")


# -----------------------------------------------------------------------------
# Base-learner factory + chain prediction
# -----------------------------------------------------------------------------
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


def _multitask_predict(Xtr, items_tr, Xte, seed: int, base: str):
    from sklearn.multioutput import RegressorChain
    regr = _make_regr(base, seed)
    chain = RegressorChain(regr, order="random", random_state=seed)
    chain.fit(Xtr, items_tr)
    return chain.predict(Xte)


# -----------------------------------------------------------------------------
# Per-fold worker (ProcessPool entry point — module-level, picklable)
# -----------------------------------------------------------------------------
def _fit_one_fold(args):
    """Worker: 8-item chain × 3 base learners for one CV fold.

    args = (fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases)
    Returns (te_idx, t1_pred_te) where t1_pred_te has shape (len(te),).
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

    # Average chain predictions across 3 base learners
    ip_avg = None
    for b in bases:
        ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base=b)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg = ip_avg / len(bases)

    # T1 sum = sum predictions for items 9-14 only (auxiliary items 15+18 used in fit)
    t1_sum_idx = [item_order.index(i) for i in T1_SUM_ITEMS]
    item_pred_t1 = ip_avg[:, t1_sum_idx] + np.array(
        [item_means[i] for i in T1_SUM_ITEMS]
    )
    t1_pred_from_items = item_pred_t1.sum(axis=1)
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))

    return te, s1_te + (t1_pred_from_items - sum_means_t1)


def _i5_one_fold(args):
    """iter5-direct comparator worker (single LGB on T1 residual)."""
    fold_id, tr, te, X, y_t1, X_s1, seed = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )
    return te, s1_te + train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)


# -----------------------------------------------------------------------------
# LOOCV drivers (parallel over folds)
# -----------------------------------------------------------------------------
def _hybrid_loocv(seed: int, X, y_t1, X_s1, items, item_order, bases, n_workers: int):
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases)
        for fid, (tr, te) in enumerate(splits)
    ]
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_fit_one_fold, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
            done += 1
            if done % 20 == 0 or done == n:
                print(
                    f"    seed={seed} hybrid {done}/{n} folds  elapsed={time.time()-t0:.0f}s",
                    flush=True,
                )
    return preds


def _iter5_direct_loocv(seed: int, X, y_t1, X_s1, n_workers: int):
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, seed)
        for fid, (tr, te) in enumerate(splits)
    ]
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_i5_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    return preds


# -----------------------------------------------------------------------------
# Pre-registration
# -----------------------------------------------------------------------------
def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": (
            "T1 iter34 HYBRID — 8-item auxiliary-task chain × multi-base ensemble "
            "{LGB, XGB-hist, ExtraTrees}"
        ),
        "is_post_publication_replication_target": True,
        "family_wise_independence_claim": (
            "Single pre-registered post-publication run; not part of iter33-B "
            "canonical-update family of comparisons (council 2026-05-06)."
        ),
        "cohort": {
            "target": "T1 = sum(items 9-14)",
            "n_subjects_min": 90,
            "filter": "PD with full items 9-14, 15, 18 (matches iter33-B 8-item filter)",
        },
        "stage1": {
            "model": "Ridge", "alpha": STAGE1_ALPHA,
            "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
            "stage1_total_features": 9, "per_fold_standardisation": True,
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
            "items_targets_chain": list(ALL_ITEMS),
            "items_summed_for_t1": list(T1_SUM_ITEMS),
            "auxiliary_items": list(AUX_ITEMS),
            "item_target_centering": "subtract per-fold train_mean(item)",
            "feature_select_method": "lgb_importance_top_k_per_fold",
            "feature_select_k": K_FEATURES,
            "imputation": "fold_local_median",
            "post_combine_formula": (
                "Stage1_pred + (sum_over_T1_SUM_ITEMS(mean_over_bases(item_pred) + "
                "train_mean) - sum(train_mean[T1_SUM_ITEMS]))  -- aux items 15,18 "
                "used in chain fit only"
            ),
            "decorrelation_argument": (
                "F68 (iter33-B) 8-item auxiliary chain regularizes via shared latent "
                "severity. F69 (iter33-C) different base learners produce decorrelated "
                "chain OOFs. Hybrid combines both — auxiliary regularization (variance "
                "via cross-task signal) × base diversity (variance via algorithmic "
                "decorrelation). Independent levers, multiplicative effect predicted."
            ),
        },
        "eval": {
            "loocv_n_min": 90, "seeds": list(SEEDS_DEFAULT),
            "bases": list(BASE_LEARNERS),
            "headline_metric": "CCC of mean-of-3-seed predictions vs y_t1",
            "comparator_iter5_direct_loocv": "computed live in same SID-aligned LOOCV",
            "comparator_iter33b_8item_loocv_oof": (
                "results/lockbox_t1_iter33b_8item_20260506_071631.oof.npy"
            ),
            "comparator_iter30b_v1_loocv_oof": (
                "results/lockbox_t1_iter30b_V1_random_20260505_211112.oof.npy"
            ),
        },
        "lockbox_rules": [
            "ONE pre-registered config. ONE LOOCV run. POST-PUBLICATION REPLICATION TARGET.",
            "Headline = CCC of mean-of-3-seed preds (each seed averages 3 base learners).",
            "Verdict frame: replication target — interpret in light of family-wise iter33 priors.",
            "Bonferroni adjustment trivial (n_tests=1) since this is a SINGLE replication run.",
            "Verdict 'lift' if paired-bootstrap (n=5000) frac>0 vs iter33-B ≥ 0.95.",
            "Verdict 'wash' if frac>0 vs iter33-B < 0.50.",
            "Verdict 'tied' otherwise (within sampling noise — interpret as no improvement).",
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
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts, "iso_datetime": datetime.now().isoformat(),
        "experiment": "T1 iter34 HYBRID 8-item × multi-base LOCKBOX",
        "git_head": _git_head(), "formula_sha256": sha, "formula": payload,
        "variant": "hybrid_8item_multibase",
        "is_post_publication_replication_target": True,
        "family_wise_independence_claim": (
            "Single pre-registered post-publication run; not part of iter33-B "
            "canonical-update family of comparisons (council 2026-05-06)."
        ),
        "eval_protocol": (
            "LOOCV on T1∩{15,18} cohort (N≈93). Stage-1 Ridge (alpha=1.0) on H&Y + "
            "cv_yrs + cv_sex + cv_dbs with per-fold standardisation. Stage-2 = mean "
            "chain prediction over 3 base learners (LGB, XGB-hist, ExtraTrees), each "
            "RegressorChain with random order over 8 items {9,10,11,12,13,14,15,18}. "
            "T1 = sum predictions for items 9-14; items 15+18 auxiliary in fit only. "
            "K=500 LGB-importance feature selection per fold. 3-seed mean preds = headline."
        ),
    }
    out = RESULTS_DIR / f"preregistration_t1_iter34_hybrid_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    print(f"  is_post_publication_replication_target = True", flush=True)
    return out


# -----------------------------------------------------------------------------
# Bootstrap utility
# -----------------------------------------------------------------------------
def _paired_bootstrap_ccc(y, p_a, p_b, n_boot: int = 5000, seed: int = 42):
    """Returns delta dist (a - b) bootstrap stats."""
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


# -----------------------------------------------------------------------------
# Smoke test
# -----------------------------------------------------------------------------
def smoke_test(seed: int = 42, feature_set: str = "A3_tier1") -> None:
    print("\n=== iter34 SMOKE TEST: 1 fold × 1 seed ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    splits = list(LeaveOneOut().split(np.arange(n)))
    fid, (tr, te) = 0, splits[0]
    args = (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, BASE_LEARNERS)
    t0 = time.time()
    te_idx, te_pred = _fit_one_fold(args)
    print(
        f"  fold 0/{n}: te_idx={te_idx[0]}, sid={sids[te_idx[0]]}, "
        f"y_true={y_t1[te_idx[0]]:.2f}, y_pred={te_pred[0]:.2f}, "
        f"wall={time.time()-t0:.1f}s",
        flush=True,
    )
    assert te_pred.shape == te.shape, f"shape mismatch {te_pred.shape} vs {te.shape}"
    assert np.isfinite(te_pred).all(), "non-finite predictions"
    print("  SMOKE PASS", flush=True)


# -----------------------------------------------------------------------------
# Lockbox
# -----------------------------------------------------------------------------
def run_lockbox(prereg_file: Path,
                seeds: tuple[int, ...] = SEEDS_DEFAULT,
                feature_set: str = "A3_tier1",
                n_workers: int = 14) -> Path:
    if not prereg_file.exists():
        raise FileNotFoundError(prereg_file)
    with open(prereg_file) as f:
        prereg = json.load(f)
    expected_sha = _formula_sha256(_formula_payload())
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(
            f"prereg formula_sha256 {prereg.get('formula_sha256')!r} "
            f"!= current {expected_sha!r}"
        )
    print(
        f"\n=== T1 iter34 HYBRID LOCKBOX LOOCV ({len(seeds)} seeds, "
        f"bases={BASE_LEARNERS}, n_workers={n_workers}) ===",
        flush=True,
    )

    # Load cohort once
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    all_mt: list[np.ndarray] = []
    all_i5: list[np.ndarray] = []
    per_seed = []
    overall_t0 = time.time()
    for seed in seeds:
        t0 = time.time()
        p_mt = _hybrid_loocv(seed, X, y_t1, X_s1, items, item_order, BASE_LEARNERS, n_workers)
        p_i5 = _iter5_direct_loocv(seed, X, y_t1, X_s1, n_workers)
        c_mt = float(ccc_fn(y_t1, p_mt))
        c_i5 = float(ccc_fn(y_t1, p_i5))
        per_seed.append({
            "seed": seed, "ccc_mt": c_mt, "ccc_i5": c_i5,
            "delta": c_mt - c_i5, "wall": time.time() - t0,
        })
        print(
            f"  seed={seed}: HYBRID={c_mt:.4f} | i5={c_i5:.4f} | "
            f"Δ={c_mt-c_i5:+.4f} | {time.time()-t0:.0f}s",
            flush=True,
        )
        all_mt.append(p_mt); all_i5.append(p_i5)
    overall_wall = time.time() - overall_t0
    print(f"  total wall = {overall_wall:.0f}s ({overall_wall/60:.1f} min)", flush=True)

    mean_mt = np.mean(np.column_stack(all_mt), axis=1)
    mean_i5 = np.mean(np.column_stack(all_i5), axis=1)
    headline = full_metrics(y_t1, mean_mt, label="t1_iter34_hybrid")

    # Bootstrap vs iter5-direct (same seeds, same cohort)
    boot_i5 = _paired_bootstrap_ccc(y_t1, mean_mt, mean_i5)

    # Bootstrap vs iter33-B (the key new comparison)
    iter33b_path = RESULTS_DIR / "lockbox_t1_iter33b_8item_20260506_071631.oof.npy"
    iter33b_json_path = RESULTS_DIR / "lockbox_t1_iter33b_8item_20260506_071631.json"
    iter33b_block = None
    if iter33b_path.exists() and iter33b_json_path.exists():
        with open(iter33b_json_path) as f:
            i33b = json.load(f)
        sids_i33b = [str(s) for s in i33b["per_subject"]["sids"]]
        p_i33b_full = np.load(iter33b_path)
        sid_to_pred = dict(zip(sids_i33b, p_i33b_full.tolist()))
        try:
            p_i33b = np.array([sid_to_pred[str(s)] for s in sids])
            ccc_i33b = float(ccc_fn(y_t1, p_i33b))
            iter33b_block = _paired_bootstrap_ccc(y_t1, mean_mt, p_i33b)
            iter33b_block["ccc_iter33b"] = round(ccc_i33b, 4)
            iter33b_block["delta_meanof_predmeans"] = float(headline["ccc"] - ccc_i33b)
        except KeyError as e:
            iter33b_block = {"error": f"SID not in iter33b oof: {e!r}"}
    else:
        iter33b_block = {"error": f"missing iter33b oof at {iter33b_path}"}

    # Bootstrap vs iter30b V1 (F65 baseline)
    iter30b_path = RESULTS_DIR / "lockbox_t1_iter30b_V1_random_20260505_211112.oof.npy"
    iter30b_json_path = RESULTS_DIR / "lockbox_t1_iter30b_V1_random_20260505_211112.json"
    iter30b_block = None
    if iter30b_path.exists() and iter30b_json_path.exists():
        with open(iter30b_json_path) as f:
            i30b = json.load(f)
        sids_i30b = [str(s) for s in i30b["per_subject"]["sids"]]
        p_i30b_full = np.load(iter30b_path)
        sid_to_pred = dict(zip(sids_i30b, p_i30b_full.tolist()))
        try:
            p_i30b = np.array([sid_to_pred[str(s)] for s in sids])
            ccc_i30b = float(ccc_fn(y_t1, p_i30b))
            iter30b_block = _paired_bootstrap_ccc(y_t1, mean_mt, p_i30b)
            iter30b_block["ccc_iter30b_v1"] = round(ccc_i30b, 4)
        except KeyError as e:
            iter30b_block = {"error": f"SID not in iter30b oof: {e!r}"}

    # Verdict
    if iter33b_block and "frac_above_zero" in iter33b_block:
        f0 = iter33b_block["frac_above_zero"]
        if f0 >= 0.95:
            verdict = "LIFT (frac>0 vs iter33-B ≥ 0.95)"
        elif f0 < 0.50:
            verdict = "WASH (frac>0 vs iter33-B < 0.50)"
        else:
            verdict = f"TIED (frac>0={f0:.3f}, between 0.50 and 0.95 — within sampling noise)"
    else:
        verdict = "UNKNOWN (iter33-B comparator missing)"

    is_canonical = bool(boot_i5["frac_above_zero"] >= 0.95
                        and headline["ccc"] > PUBLISHED_T1_LOOCV_CCC)

    headline.update({
        "variant": "hybrid_8item_multibase",
        "bases": list(BASE_LEARNERS),
        "n_subjects": n,
        "item_order_chain": item_order,
        "auxiliary_items_used": list(available_aux),
        "preregistration_file": prereg_file.name,
        "is_lockbox_headline": True,
        "is_post_publication_replication_target": True,
        "family_wise_independence_claim": (
            "Single pre-registered post-publication run; not part of iter33-B "
            "canonical-update family of comparisons (council 2026-05-06). "
            "Bonferroni adjustment trivial (n_tests=1)."
        ),
        "n_seeds": len(seeds), "per_seed": per_seed,
        "wall_time_total_s": overall_wall,
        "ccc_iter5_direct_loocv_baseline": round(float(ccc_fn(y_t1, mean_i5)), 4),
        "delta_vs_iter5_direct": round(headline["ccc"] - float(ccc_fn(y_t1, mean_i5)), 4),
        "bootstrap_delta_vs_iter5": boot_i5,
        "bootstrap_delta_vs_iter33b_8item": iter33b_block,
        "bootstrap_delta_vs_iter30b_v1_random": iter30b_block,
        "is_canonical_update": is_canonical,
        "verdict_vs_iter33b": verdict,
        "per_subject": {
            "sids": [str(s) for s in sids],
            "y_true": y_t1.tolist(), "y_pred": mean_mt.tolist(),
        },
    })
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_iter34_hybrid_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t1_iter34_hybrid_{ts}.oof.npy"
    np.save(out_npy, mean_mt)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)

    print(
        f"\n=== HEADLINE: CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f}, "
        f"r={headline['r']:.4f}, slope={headline['cal_slope']:.3f} ===",
        flush=True,
    )
    print(
        f"  vs iter5-direct: Δ={headline['delta_vs_iter5_direct']:+.4f}, "
        f"frac>0={boot_i5['frac_above_zero']:.3f}",
        flush=True,
    )
    if iter33b_block and "frac_above_zero" in iter33b_block:
        print(
            f"  vs iter33-B 8item: ccc_i33b={iter33b_block['ccc_iter33b']:.4f}, "
            f"Δ̄={iter33b_block['delta_mean']:+.4f}, "
            f"frac>0={iter33b_block['frac_above_zero']:.3f}",
            flush=True,
        )
    if iter30b_block and "frac_above_zero" in iter30b_block:
        print(
            f"  vs iter30b V1:    ccc_v1={iter30b_block['ccc_iter30b_v1']:.4f}, "
            f"Δ̄={iter30b_block['delta_mean']:+.4f}, "
            f"frac>0={iter30b_block['frac_above_zero']:.3f}",
            flush=True,
        )
    print(f"  VERDICT: {verdict}", flush=True)
    print(f"  is_canonical_update = {is_canonical}", flush=True)
    print(f"  total wall = {overall_wall:.0f}s ({overall_wall/60:.1f} min)", flush=True)
    print(f"Wrote {out_json}\n      {out_npy}", flush=True)
    return out_json


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["smoke", "write_prereg", "lockbox"], required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--preregistration_file", type=str, default=None)
    ap.add_argument("--n_workers", type=int,
                    default=int(os.getenv("ITER34_WORKERS", 14)))
    args = ap.parse_args()
    if args.mode == "smoke":
        smoke_test(seed=args.seeds[0], feature_set=args.feature_set)
    elif args.mode == "write_prereg":
        write_preregistration()
    else:
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required for lockbox mode")
        run_lockbox(
            Path(args.preregistration_file),
            seeds=tuple(args.seeds),
            feature_set=args.feature_set,
            n_workers=args.n_workers,
        )


if __name__ == "__main__":
    main()
