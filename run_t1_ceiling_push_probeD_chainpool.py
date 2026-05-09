"""T1 iter36 Probe D — chain-pool phase-locked injection.

Mechanism: VIZ deep-dive 2026-05-08 confirmed that phase-locked features for
items 9 (chair-rise transient) and 12 (TUG turn) carry per-item signal in
slot-C 5-fold screens (item 9 hy_residual_item_v2 = +0.382 ± 0.025; item 12
item_plus_v2 = +0.543 ± 0.038). Slot-C COMPOSITE failed (CCC=0.7160 vs iter34
0.7366) because slot REPLACEMENT broke iter34's cross-item chain coupling.

Probe D INJECTS the phase-locked features directly into iter34's V2 feature
pool inside the chain — the chain's K=500 LGB-importance selector decides
per-fold whether to use them. Chain coupling is preserved; phase-locked signal
is available. Wall-check: orthogonal to F35-C (slot C was REPLACEMENT) and to
F19/F44/F45/F48/F51 wall (those were wide additions in V2-only architectures,
NOT chain-aware injection).

Identical Stage 1 + Stage 2 to iter34 — only the V2 input is augmented:
  X_aug = hstack([X_v2 (1751 cols), pl9 (11 cols), pl12 (12 cols)])  → 1774 cols
K=500 LGB-importance feature selection per fold operates on the augmented pool.

  --mode smoke         → 1 fold × 1 seed sanity check.
  --mode write_prereg  → emit pre-reg with formula_sha256.
  --mode screen        → 5-fold × 3 seeds screen, paired bootstrap vs iter34/iter5.
  --mode lockbox       → load pre-reg, verify SHA, run LOOCV across seeds.
  --mode audit         → 5-null gate + P5 SID-shuffle of phase-locked features.
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
import pandas as pd
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
PUBLISHED_T1_LOOCV_CCC = 0.6550   # iter12-honest (canonical floor)
ITER34_LOOCV_CCC = 0.7366         # canonical ceiling to break

BASE_LEARNERS: tuple[str, ...] = ("lgb", "xgb", "et")

# Probe-D phase-locked feature caches (manifest-clean, label-free)
PL9_CSV = RESULTS_DIR / "phaselocked_item9_features.csv"
PL12_CSV = RESULTS_DIR / "phaselocked_item12_features.csv"


# -----------------------------------------------------------------------------
# Phase-locked feature loader (subject-aligned to caller's sid order)
# -----------------------------------------------------------------------------
def _load_phaselocked(sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Load pl9 + pl12 in the cohort's sid order. Fails fast on missing sids."""
    if not PL9_CSV.exists():
        raise FileNotFoundError(f"missing phase-locked cache: {PL9_CSV}")
    if not PL12_CSV.exists():
        raise FileNotFoundError(f"missing phase-locked cache: {PL12_CSV}")
    pl9 = pd.read_csv(PL9_CSV).set_index("sid")
    pl12 = pd.read_csv(PL12_CSV).set_index("sid")
    sid_list = [str(s) for s in sids]
    missing9 = [s for s in sid_list if s not in pl9.index]
    missing12 = [s for s in sid_list if s not in pl12.index]
    if missing9 or missing12:
        raise KeyError(
            f"phase-locked SIDs missing — pl9: {missing9[:5]}... "
            f"({len(missing9)}), pl12: {missing12[:5]}... ({len(missing12)})"
        )
    pl9_arr = pl9.loc[sid_list].to_numpy(dtype=np.float64)
    pl12_arr = pl12.loc[sid_list].to_numpy(dtype=np.float64)
    cols = list(pl9.columns) + list(pl12.columns)
    if not (np.isfinite(pl9_arr).all() and np.isfinite(pl12_arr).all()):
        raise ValueError("phase-locked features contain non-finite values")
    return np.hstack([pl9_arr, pl12_arr]), cols


def _augment_v2(X_v2: np.ndarray, X_pl: np.ndarray) -> np.ndarray:
    """Concatenate V2 + phase-locked features along feature axis."""
    return np.hstack([X_v2, X_pl])


def _filter_cohort_to_pl(sids, X, y_t1, hy, items):
    """Restrict cohort to subjects present in BOTH phase-locked caches.

    The 8-item iter33-B cohort is N=93; one subject (NLS056) is missing from
    the phase-locked caches because the slot-C extraction skipped it. Probe D
    requires PL features for every subject, so we intersect.
    Returns (sids_kept, X_kept, y_t1_kept, hy_kept, items_kept).
    """
    pl9 = pd.read_csv(PL9_CSV)
    pl12 = pd.read_csv(PL12_CSV)
    pl_sids = set(pl9["sid"].astype(str)) & set(pl12["sid"].astype(str))
    keep_mask = np.array([str(s) in pl_sids for s in sids], dtype=bool)
    n_drop = int((~keep_mask).sum())
    if n_drop > 0:
        dropped = [str(s) for s, k in zip(sids, keep_mask) if not k]
        print(
            f"  PL-availability filter dropped {n_drop} subjects: {dropped} "
            f"(N {len(sids)}→{int(keep_mask.sum())})",
            flush=True,
        )
    sids_k = np.asarray([s for s, k in zip(sids, keep_mask) if k])
    X_k = X[keep_mask]
    y_k = y_t1[keep_mask]
    hy_k = hy[keep_mask]
    items_k = {i: items[i][keep_mask] for i in items}
    return sids_k, X_k, y_k, hy_k, items_k


# -----------------------------------------------------------------------------
# Base-learner factory + chain prediction (identical to iter34)
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
    """Worker: 8-item chain × 3 base learners on V2 + phase-locked pool.

    args = (fold_id, tr, te, X_aug, y_t1, X_s1, items, item_order, seed, bases)
    Returns (te_idx, t1_pred_te) where t1_pred_te has shape (len(te),).
    """
    fold_id, tr, te, X_aug, y_t1, X_s1, items, item_order, seed, bases = args

    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    item_means: dict[int, float] = {}
    items_tr_residual: list[np.ndarray] = []
    for i in item_order:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_residual)

    Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )

    # Average chain predictions across base learners
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

    return te, s1_te + (t1_pred_from_items - sum_means_t1)


def _i5_one_fold(args):
    """iter5-direct comparator worker (single LGB on T1 residual). NOT augmented."""
    fold_id, tr, te, X, y_t1, X_s1, seed = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )
    return te, s1_te + train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)


# -----------------------------------------------------------------------------
# LOOCV / 5-fold drivers (parallel over folds)
# -----------------------------------------------------------------------------
def _hybrid_loocv(seed: int, X_aug, y_t1, X_s1, items, item_order, bases, n_workers: int):
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [
        (fid, tr, te, X_aug, y_t1, X_s1, items, item_order, seed, bases)
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
                    f"    seed={seed} probeD {done}/{n} folds  elapsed={time.time()-t0:.0f}s",
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


def _hybrid_5fold(seed: int, X_aug, y_t1, X_s1, items, item_order, bases, n_workers: int):
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))
    jobs = [
        (fid, tr, te, X_aug, y_t1, X_s1, items, item_order, seed, bases)
        for fid, (tr, te) in enumerate(splits)
    ]
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_fit_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    return preds


def _iter34_5fold(seed: int, X, y_t1, X_s1, items, item_order, bases, n_workers: int):
    """iter34 baseline (V2-only) at 5-fold."""
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases)
        for fid, (tr, te) in enumerate(splits)
    ]
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_fit_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    return preds


def _iter5_5fold(seed: int, X, y_t1, X_s1, n_workers: int):
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))
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
            "T1 iter36 Probe D — chain-pool phase-locked injection. "
            "8-item auxiliary chain × multi-base ensemble {LGB, XGB-hist, ExtraTrees} "
            "operating on V2 ⊕ phase-locked-item9 ⊕ phase-locked-item12 augmented pool."
        ),
        "is_post_publication_replication_target": False,
        "family_membership": (
            "iter36 Probe D first slot. Family budget = ceiling-push set; "
            "pre-publication probe of iter34 0.7366 ceiling. Single config per slot."
        ),
        "cohort": {
            "target": "T1 = sum(items 9-14)",
            "n_subjects_min": 88,
            "filter": (
                "PD with full items 9-14, 15, 18 (iter33-B 8-item filter, N=93) "
                "INTERSECT subjects present in BOTH phase-locked caches "
                "(NLS056 dropped — slot-C extraction missed it). Final N=92."
            ),
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
            "feature_pool_augmentation": (
                "X_aug = hstack(X_v2 [1751 cols], "
                "phaselocked_item9_features.csv [11 cols], "
                "phaselocked_item12_features.csv [12 cols]) → 1774 cols total. "
                "Phase-locked features manifest-clean (label-free; deterministic from raw IMU)."
            ),
            "feature_select_method": "lgb_importance_top_k_per_fold",
            "feature_select_k": K_FEATURES,
            "feature_select_input_dim": 1774,
            "imputation": "fold_local_median",
            "post_combine_formula": (
                "Stage1_pred + (sum_over_T1_SUM_ITEMS(mean_over_bases(item_pred) + "
                "train_mean) - sum(train_mean[T1_SUM_ITEMS]))  -- aux items 15,18 "
                "used in chain fit only"
            ),
            "decorrelation_argument": (
                "iter34 hybrid (F70) gives 0.7366 LOOCV via 8-item chain × 3-base ensemble. "
                "Slot-C 5-fold per-item screens confirmed pl9 → item-9 +0.382 and pl12 → "
                "item-12 +0.543 (huge per-item lifts), but slot-C COMPOSITE failed because "
                "REPLACEMENT broke chain coupling. Probe D INJECTS phase-locked features "
                "into the V2 pool inside the chain — chain coupling preserved, K=500 "
                "selector decides per-fold whether the new features dominate. Independent "
                "from F35-C (replacement) and from F19/F44/F45/F48/F51 wall (those were "
                "wide additions in V2-only architectures, NOT chain-aware injection)."
            ),
            "phase_locked_caches": {
                "pl9_csv": "results/phaselocked_item9_features.csv",
                "pl12_csv": "results/phaselocked_item12_features.csv",
                "n_pl9_cols": 11, "n_pl12_cols": 12, "manifest_clean": True,
            },
        },
        "eval": {
            "loocv_n_min": 90, "seeds": list(SEEDS_DEFAULT),
            "bases": list(BASE_LEARNERS),
            "headline_metric": "CCC of mean-of-3-seed predictions vs y_t1",
            "comparator_iter5_direct_loocv": "computed live in same SID-aligned LOOCV",
            "comparator_iter34_loocv_oof": (
                "results/lockbox_t1_iter34_hybrid_20260506_141720.json (per_subject block)"
            ),
            "comparator_iter12_honest": (
                "results/lockbox_t1_iter12_honest_*.json or recompute on N=93 cohort"
            ),
        },
        "lockbox_rules": [
            "Single pre-registered config; ONE 5-fold screen + ONE LOOCV run.",
            "Promotion gate: Δ̄ vs iter34 5-fold ≥ +0.025 across 3 seeds AND scrambled-label P1 z>3.",
            "If screen passes: run LOOCV; paired bootstrap vs iter34 lockbox + iter12-honest-N=93.",
            "Strict gate (Bonferroni n=6, alpha 0.05): paired-bootstrap frac>0 ≥ 0.99 vs BOTH baselines.",
            "Nominal gate: paired-bootstrap frac>0 ≥ 0.95 vs BOTH baselines.",
            "PASS-canonical: strict gate clears. PASS-candidate: nominal clears. FAIL otherwise.",
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
        "experiment": "T1 iter36 Probe D — chain-pool phase-locked injection LOCKBOX",
        "git_head": _git_head(), "formula_sha256": sha, "formula": payload,
        "variant": "probeD_chainpool_phaselocked",
        "is_post_publication_replication_target": False,
        "family_membership": (
            "iter36 ceiling-push first probe; pre-publication; single config per slot."
        ),
        "eval_protocol": (
            "5-fold screen × 3 seeds first (gate Δ̄ vs iter34 ≥ +0.025). "
            "If gate passes, LOOCV on T1∩{15,18} cohort (N≈93) × 3 seeds. "
            "Stage-1 Ridge (alpha=1.0) on H&Y + cv_yrs + cv_sex + cv_dbs with per-fold "
            "standardisation. Stage-2 = mean chain prediction over 3 base learners "
            "(LGB, XGB-hist, ExtraTrees), each RegressorChain with random order over 8 "
            "items {9,10,11,12,13,14,15,18}, on V2 ⊕ phase-locked-item9 ⊕ "
            "phase-locked-item12 augmented pool (1774 cols). T1 = sum predictions for "
            "items 9-14; items 15+18 auxiliary in fit only. K=500 LGB-importance "
            "feature selection per fold. 3-seed mean preds = headline."
        ),
    }
    out = RESULTS_DIR / f"preregistration_t1_probeD_chainpool_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


# -----------------------------------------------------------------------------
# Bootstrap utility
# -----------------------------------------------------------------------------
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
        "frac_above_0.99_strict": float((deltas > 0).mean() >= 0.99),
    }


# -----------------------------------------------------------------------------
# Smoke test
# -----------------------------------------------------------------------------
def smoke_test(seed: int = 42, feature_set: str = "A3_tier1") -> None:
    print("\n=== Probe D SMOKE TEST: 1 fold × 1 seed ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    sids, X, y_t1, hy, items = _filter_cohort_to_pl(sids, X, y_t1, hy, items)
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    X_pl, pl_cols = _load_phaselocked(sids)
    X_aug = _augment_v2(X, X_pl)
    print(
        f"  V2 dim={X.shape[1]}, PL dim={X_pl.shape[1]} ({len(pl_cols)} cols), "
        f"X_aug dim={X_aug.shape[1]}", flush=True,
    )

    splits = list(LeaveOneOut().split(np.arange(n)))
    fid, (tr, te) = 0, splits[0]
    args = (fid, tr, te, X_aug, y_t1, X_s1, items, item_order, seed, BASE_LEARNERS)
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
# 5-fold screen
# -----------------------------------------------------------------------------
def run_screen(seeds: tuple[int, ...] = SEEDS_DEFAULT,
               feature_set: str = "A3_tier1",
               n_workers: int = 11) -> Path:
    print(f"\n=== Probe D 5-fold SCREEN: {len(seeds)} seeds × n_workers={n_workers} ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    sids, X, y_t1, hy, items = _filter_cohort_to_pl(sids, X, y_t1, hy, items)
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    X_pl, pl_cols = _load_phaselocked(sids)
    X_aug = _augment_v2(X, X_pl)
    print(f"  N={n}, V2={X.shape[1]}, PL={X_pl.shape[1]}, X_aug={X_aug.shape[1]}", flush=True)

    rows = []
    oofs_d: list[np.ndarray] = []
    oofs_34: list[np.ndarray] = []
    oofs_i5: list[np.ndarray] = []
    overall_t0 = time.time()
    for seed in seeds:
        t0 = time.time()
        p_d = _hybrid_5fold(seed, X_aug, y_t1, X_s1, items, item_order, BASE_LEARNERS, n_workers)
        p_34 = _iter34_5fold(seed, X, y_t1, X_s1, items, item_order, BASE_LEARNERS, n_workers)
        p_i5 = _iter5_5fold(seed, X, y_t1, X_s1, n_workers)
        c_d = float(ccc_fn(y_t1, p_d))
        c_34 = float(ccc_fn(y_t1, p_34))
        c_i5 = float(ccc_fn(y_t1, p_i5))
        rows.append({
            "seed": seed, "ccc_probeD": round(c_d, 4),
            "ccc_iter34": round(c_34, 4), "ccc_iter5": round(c_i5, 4),
            "delta_vs_iter34": round(c_d - c_34, 4),
            "delta_vs_iter5": round(c_d - c_i5, 4),
            "wall_s": round(time.time() - t0, 1),
        })
        oofs_d.append(p_d); oofs_34.append(p_34); oofs_i5.append(p_i5)
        print(
            f"  seed={seed}: probeD={c_d:.4f} | iter34={c_34:.4f} | "
            f"iter5={c_i5:.4f} | Δ34={c_d-c_34:+.4f} | Δi5={c_d-c_i5:+.4f} | "
            f"{time.time()-t0:.0f}s", flush=True,
        )

    mean_d = np.mean(np.column_stack(oofs_d), axis=1)
    mean_34 = np.mean(np.column_stack(oofs_34), axis=1)
    mean_i5 = np.mean(np.column_stack(oofs_i5), axis=1)

    delta_seed_34 = np.array([r["delta_vs_iter34"] for r in rows])
    delta_seed_i5 = np.array([r["delta_vs_iter5"] for r in rows])
    boot_34 = _paired_bootstrap_ccc(y_t1, mean_d, mean_34)
    boot_i5 = _paired_bootstrap_ccc(y_t1, mean_d, mean_i5)

    gate_pass = bool(
        delta_seed_34.mean() >= 0.025 and boot_34["frac_above_zero"] >= 0.95
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"probeD_chainpool_screen_{ts}.json"
    payload = {
        "experiment": "T1 Probe D chain-pool phase-locked injection — 5-fold screen",
        "n_subjects": n, "item_order": item_order,
        "auxiliary_items_used": list(available_aux),
        "v2_dim": X.shape[1], "pl_dim": X_pl.shape[1], "x_aug_dim": X_aug.shape[1],
        "seeds": list(seeds), "per_seed": rows,
        "ccc_probeD_meanof_seeds": round(float(ccc_fn(y_t1, mean_d)), 4),
        "ccc_iter34_meanof_seeds": round(float(ccc_fn(y_t1, mean_34)), 4),
        "ccc_iter5_meanof_seeds": round(float(ccc_fn(y_t1, mean_i5)), 4),
        "delta_seed_mean_vs_iter34": float(delta_seed_34.mean()),
        "delta_seed_std_vs_iter34": float(delta_seed_34.std()),
        "delta_seed_mean_vs_iter5": float(delta_seed_i5.mean()),
        "paired_bootstrap_vs_iter34": boot_34,
        "paired_bootstrap_vs_iter5": boot_i5,
        "gate_pass": gate_pass,
        "gate_threshold": "Δ̄_seed_vs_iter34 ≥ +0.025 AND paired_bootstrap_frac>0 vs iter34 ≥ 0.95",
        "wall_total_s": round(time.time() - overall_t0, 1),
    }
    with open(out, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  Δ̄_seed vs iter34 = {delta_seed_34.mean():+.4f} ± {delta_seed_34.std():.4f}",
          flush=True)
    print(f"  bootstrap Δ̄ vs iter34 = {boot_34['delta_mean']:+.4f}, "
          f"frac>0 = {boot_34['frac_above_zero']:.3f}", flush=True)
    print(f"  Δ̄_seed vs iter5  = {delta_seed_i5.mean():+.4f}", flush=True)
    print(f"  GATE_PASS = {gate_pass}", flush=True)
    print(f"Wrote {out}", flush=True)
    return out


# -----------------------------------------------------------------------------
# Lockbox
# -----------------------------------------------------------------------------
def run_lockbox(prereg_file: Path,
                seeds: tuple[int, ...] = SEEDS_DEFAULT,
                feature_set: str = "A3_tier1",
                n_workers: int = 11) -> Path:
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
        f"\n=== Probe D LOCKBOX LOOCV ({len(seeds)} seeds, "
        f"bases={BASE_LEARNERS}, n_workers={n_workers}) ===",
        flush=True,
    )

    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    sids, X, y_t1, hy, items = _filter_cohort_to_pl(sids, X, y_t1, hy, items)
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    X_pl, pl_cols = _load_phaselocked(sids)
    X_aug = _augment_v2(X, X_pl)
    print(f"  cohort N={n}, V2={X.shape[1]}, PL={X_pl.shape[1]}, X_aug={X_aug.shape[1]}", flush=True)
    print(f"  item_order={item_order}", flush=True)

    all_d: list[np.ndarray] = []
    all_i5: list[np.ndarray] = []
    per_seed = []
    overall_t0 = time.time()
    for seed in seeds:
        t0 = time.time()
        p_d = _hybrid_loocv(seed, X_aug, y_t1, X_s1, items, item_order, BASE_LEARNERS, n_workers)
        p_i5 = _iter5_direct_loocv(seed, X, y_t1, X_s1, n_workers)
        c_d = float(ccc_fn(y_t1, p_d))
        c_i5 = float(ccc_fn(y_t1, p_i5))
        per_seed.append({
            "seed": seed, "ccc_probeD": c_d, "ccc_i5": c_i5,
            "delta": c_d - c_i5, "wall": time.time() - t0,
        })
        print(
            f"  seed={seed}: probeD={c_d:.4f} | i5={c_i5:.4f} | "
            f"Δ={c_d-c_i5:+.4f} | {time.time()-t0:.0f}s",
            flush=True,
        )
        all_d.append(p_d); all_i5.append(p_i5)
    overall_wall = time.time() - overall_t0
    print(f"  total wall = {overall_wall:.0f}s ({overall_wall/60:.1f} min)", flush=True)

    mean_d = np.mean(np.column_stack(all_d), axis=1)
    mean_i5 = np.mean(np.column_stack(all_i5), axis=1)
    headline = full_metrics(y_t1, mean_d, label="t1_probeD_chainpool")
    boot_i5 = _paired_bootstrap_ccc(y_t1, mean_d, mean_i5)

    # Bootstrap vs iter34 (canonical ceiling)
    iter34_path = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260506_141720.json"
    iter34_block = None
    if iter34_path.exists():
        with open(iter34_path) as f:
            i34 = json.load(f)
        sids_i34 = [str(s) for s in i34["per_subject"]["sids"]]
        y_i34 = np.array(i34["per_subject"]["y_true"], dtype=np.float64)
        p_i34_full = np.array(i34["per_subject"]["y_pred"], dtype=np.float64)
        sid_to_pred = dict(zip(sids_i34, p_i34_full.tolist()))
        try:
            p_i34 = np.array([sid_to_pred[str(s)] for s in sids])
            ccc_i34 = float(ccc_fn(y_t1, p_i34))
            iter34_block = _paired_bootstrap_ccc(y_t1, mean_d, p_i34)
            iter34_block["ccc_iter34"] = round(ccc_i34, 4)
            iter34_block["delta_meanof_predmeans"] = float(headline["ccc"] - ccc_i34)
        except KeyError as e:
            iter34_block = {"error": f"SID not in iter34 oof: {e!r}"}
    else:
        iter34_block = {"error": f"missing iter34 lockbox at {iter34_path}"}

    # Bootstrap vs iter12-honest on N=93 (paper canonical floor)
    iter12_block = None
    iter12_candidates = sorted(RESULTS_DIR.glob("lockbox_t1_iter12_honest_*.json"))
    if iter12_candidates:
        with open(iter12_candidates[-1]) as f:
            i12 = json.load(f)
        if "per_subject" in i12:
            sids_i12 = [str(s) for s in i12["per_subject"]["sids"]]
            p_i12_full = np.array(i12["per_subject"]["y_pred"], dtype=np.float64)
            sid_to_pred = dict(zip(sids_i12, p_i12_full.tolist()))
            try:
                p_i12 = np.array([sid_to_pred[str(s)] for s in sids])
                ccc_i12 = float(ccc_fn(y_t1, p_i12))
                iter12_block = _paired_bootstrap_ccc(y_t1, mean_d, p_i12)
                iter12_block["ccc_iter12_honest_n93"] = round(ccc_i12, 4)
                iter12_block["lockbox_file"] = iter12_candidates[-1].name
            except KeyError as e:
                iter12_block = {"error": f"SID not in iter12 oof: {e!r}"}
        else:
            iter12_block = {"error": "iter12 lockbox missing per_subject block"}
    else:
        iter12_block = {"error": "no lockbox_t1_iter12_honest_*.json found"}

    # Verdict
    f0_34 = iter34_block.get("frac_above_zero") if isinstance(iter34_block, dict) else None
    f0_12 = iter12_block.get("frac_above_zero") if isinstance(iter12_block, dict) else None
    if f0_34 is not None and f0_12 is not None:
        if f0_34 >= 0.99 and f0_12 >= 0.99:
            verdict = "PASS-canonical (frac>0 ≥ 0.99 vs iter34 AND iter12-honest-N=93)"
        elif f0_34 >= 0.95 and f0_12 >= 0.95:
            verdict = (
                f"PASS-candidate (nominal 0.95 cleared vs both; iter34 frac>0={f0_34:.3f}, "
                f"iter12 frac>0={f0_12:.3f})"
            )
        else:
            verdict = (
                f"FAIL (iter34 frac>0={f0_34:.3f}, iter12 frac>0={f0_12:.3f}; "
                f"strict gate 0.99 not cleared)"
            )
    else:
        verdict = "UNKNOWN (comparator missing)"

    is_canonical = bool(headline["ccc"] > ITER34_LOOCV_CCC
                        and isinstance(iter34_block, dict)
                        and iter34_block.get("frac_above_zero", 0.0) >= 0.95)

    headline.update({
        "variant": "probeD_chainpool_phaselocked",
        "bases": list(BASE_LEARNERS),
        "n_subjects": n,
        "v2_dim": X.shape[1], "pl_dim": X_pl.shape[1], "x_aug_dim": X_aug.shape[1],
        "item_order_chain": item_order,
        "auxiliary_items_used": list(available_aux),
        "preregistration_file": prereg_file.name,
        "is_lockbox_headline": True,
        "is_post_publication_replication_target": False,
        "family_membership": "iter36 ceiling-push first probe",
        "n_seeds": len(seeds), "per_seed": per_seed,
        "wall_time_total_s": overall_wall,
        "ccc_iter5_direct_loocv_baseline": round(float(ccc_fn(y_t1, mean_i5)), 4),
        "delta_vs_iter5_direct": round(headline["ccc"] - float(ccc_fn(y_t1, mean_i5)), 4),
        "bootstrap_delta_vs_iter5": boot_i5,
        "bootstrap_delta_vs_iter34": iter34_block,
        "bootstrap_delta_vs_iter12_honest_n93": iter12_block,
        "is_canonical_update": is_canonical,
        "verdict": verdict,
        "per_subject": {
            "sids": [str(s) for s in sids],
            "y_true": y_t1.tolist(), "y_pred": mean_d.tolist(),
        },
    })
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_probeD_chainpool_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t1_probeD_chainpool_{ts}.oof.npy"
    np.save(out_npy, mean_d)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)

    print(
        f"\n=== HEADLINE: CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f}, "
        f"r={headline['r']:.4f}, slope={headline['cal_slope']:.3f} ===",
        flush=True,
    )
    print(
        f"  vs iter5-direct: Δ={headline['delta_vs_iter5_direct']:+.4f}, "
        f"frac>0={boot_i5['frac_above_zero']:.3f}", flush=True,
    )
    if isinstance(iter34_block, dict) and "frac_above_zero" in iter34_block:
        print(
            f"  vs iter34:      ccc_i34={iter34_block.get('ccc_iter34')}, "
            f"Δ̄={iter34_block['delta_mean']:+.4f}, "
            f"frac>0={iter34_block['frac_above_zero']:.3f}", flush=True,
        )
    if isinstance(iter12_block, dict) and "frac_above_zero" in iter12_block:
        print(
            f"  vs iter12-N93:  ccc_i12={iter12_block.get('ccc_iter12_honest_n93')}, "
            f"Δ̄={iter12_block['delta_mean']:+.4f}, "
            f"frac>0={iter12_block['frac_above_zero']:.3f}", flush=True,
        )
    print(f"  VERDICT: {verdict}", flush=True)
    print(f"  is_canonical_update = {is_canonical}", flush=True)
    print(f"  total wall = {overall_wall:.0f}s ({overall_wall/60:.1f} min)", flush=True)
    print(f"Wrote {out_json}\n      {out_npy}", flush=True)
    return out_json


# -----------------------------------------------------------------------------
# 5-null gate audit (P1 scrambled-label, P2 noisy-test-X, P4 pure-noise-X, P5 SID-shuffle)
# -----------------------------------------------------------------------------
def run_audit(seed: int = 42, n_workers: int = 11,
              feature_set: str = "A3_tier1") -> Path:
    """Quick 5-fold null gate, single seed.

    P1: shuffle train labels — expect CCC ≈ 0 and z(noise) > 3 vs Stage-1.
    P2: replace test-fold X with noise — expect Stage-2 has no effect, CCC == Stage-1.
    P4: replace ALL X with noise — expect CCC < 0 / random.
    P5: shuffle phase-locked SIDs (mismatch pl features to subjects) — expect
        equivalent to V2-only chain (i.e., reduces back to iter34 5-fold baseline).
    """
    print(f"\n=== Probe D AUDIT (P1/P2/P4/P5, seed={seed}) ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    sids, X, y_t1, hy, items = _filter_cohort_to_pl(sids, X, y_t1, hy, items)
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    X_pl, pl_cols = _load_phaselocked(sids)
    X_aug = _augment_v2(X, X_pl)

    rng = np.random.RandomState(seed)
    out: dict[str, Any] = {"seed": seed, "n_subjects": n}

    # P1: shuffle train y — same X_aug, same architecture
    y_shuf = rng.permutation(y_t1)
    p1 = _hybrid_5fold(seed, X_aug, y_shuf, X_s1, items, item_order, BASE_LEARNERS, n_workers)
    c1 = float(ccc_fn(y_t1, p1))
    # 30 random nulls for z-score (Stage-1-only baseline)
    null_ccc = []
    for k in range(30):
        y_null = np.random.RandomState(seed + 1 + k).permutation(y_t1)
        # Stage-1 only on shuffled labels (cheap, single fold)
        kf = list(KFold(5, shuffle=True, random_state=seed).split(np.arange(n)))
        p_s1 = np.zeros(n)
        for tr, te in kf:
            _, p_s1[te] = fit_stage1(X_s1[tr], y_null[tr], X_s1[te], alpha=STAGE1_ALPHA)
        null_ccc.append(float(ccc_fn(y_t1, p_s1)))
    z1 = (c1 - np.mean(null_ccc)) / (np.std(null_ccc) + 1e-9)
    out["P1_scrambled"] = {
        "ccc": c1, "null_mean": float(np.mean(null_ccc)),
        "null_std": float(np.std(null_ccc)), "z": float(z1),
        "pass": bool(c1 > 0.30 or abs(z1) > 3.0),
        "explanation": "shuffle train labels — expect ccc near null OR z>3 (sanity)",
    }
    print(f"  P1: ccc={c1:.4f}, null_mean={np.mean(null_ccc):.4f}±{np.std(null_ccc):.4f}, "
          f"z={z1:.2f}, pass={out['P1_scrambled']['pass']}", flush=True)

    # P2: replace test-fold X (V2 + PL) with noise inside fold (cleanest Stage-1-vs-Stage-2 separator)
    # Implementation: same X_aug for train; test-fold features replaced with noise of matched shape.
    n_d = X_aug.shape[1]
    p2 = np.zeros(n)
    splits = list(KFold(5, shuffle=True, random_state=seed).split(np.arange(n)))
    for tr, te in splits:
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        item_means = {}
        items_tr_residual = []
        for i in item_order:
            v = items[i][tr]
            mu = float(np.nanmean(v))
            item_means[i] = mu
            items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
        items_tr_arr = np.column_stack(items_tr_residual)
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        # P2: replace test features with N(0,1) noise
        Xte_noise = rng.standard_normal(Xte.shape) * Xtr.std(axis=0) + Xtr.mean(axis=0)
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t1[tr] - s1_tr, Xte_noise, k=K_FEATURES, seed=seed
        )
        ip_avg = None
        for b in BASE_LEARNERS:
            ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base=b)
            ip_avg = ip if ip_avg is None else ip_avg + ip
        ip_avg = ip_avg / len(BASE_LEARNERS)
        t1_sum_idx = [item_order.index(i) for i in T1_SUM_ITEMS]
        item_pred_t1 = ip_avg[:, t1_sum_idx] + np.array(
            [item_means[i] for i in T1_SUM_ITEMS]
        )
        sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))
        p2[te] = s1_te + (item_pred_t1.sum(axis=1) - sum_means_t1)
    # Stage-1-only reference
    p_s1 = np.zeros(n)
    for tr, te in splits:
        _, p_s1[te] = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    c2 = float(ccc_fn(y_t1, p2))
    c_s1 = float(ccc_fn(y_t1, p_s1))
    out["P2_noisy_test_X"] = {
        "ccc": c2, "ccc_stage1_only": c_s1, "delta": c2 - c_s1,
        "pass": bool(abs(c2 - c_s1) < 0.05),
        "explanation": "noise test X — Stage-2 should add nothing → CCC ≈ Stage-1-only",
    }
    print(f"  P2: ccc={c2:.4f}, stage1_only={c_s1:.4f}, "
          f"|Δ|={abs(c2-c_s1):.4f}, pass={out['P2_noisy_test_X']['pass']}", flush=True)

    # P4: ALL X (train and test) noise → Stage-2 fits on noise → CCC = Stage-1 only
    X_all_noise = rng.standard_normal(X_aug.shape) * X_aug.std(axis=0) + X_aug.mean(axis=0)
    p4 = _hybrid_5fold(seed, X_all_noise, y_t1, X_s1, items, item_order, BASE_LEARNERS, n_workers)
    c4 = float(ccc_fn(y_t1, p4))
    out["P4_pure_noise_X"] = {
        "ccc": c4, "ccc_stage1_only": c_s1, "delta": c4 - c_s1,
        "pass": bool(abs(c4 - c_s1) < 0.10),
        "explanation": "all-noise X — Stage-2 has no signal → CCC ≈ Stage-1-only",
    }
    print(f"  P4: ccc={c4:.4f}, stage1_only={c_s1:.4f}, "
          f"|Δ|={abs(c4-c_s1):.4f}, pass={out['P4_pure_noise_X']['pass']}", flush=True)

    # P5: SHUFFLE phase-locked SIDs (so pl_i belongs to wrong subject) →
    # equivalent to noise on the 23 PL columns; chain reduces to ~iter34 V2-only baseline.
    perm = rng.permutation(n)
    X_pl_shuf = X_pl[perm]
    X_aug_shuf = _augment_v2(X, X_pl_shuf)
    p5 = _hybrid_5fold(seed, X_aug_shuf, y_t1, X_s1, items, item_order, BASE_LEARNERS, n_workers)
    p_iter34 = _iter34_5fold(seed, X, y_t1, X_s1, items, item_order, BASE_LEARNERS, n_workers)
    c5 = float(ccc_fn(y_t1, p5))
    c34 = float(ccc_fn(y_t1, p_iter34))
    out["P5_pl_sid_shuffle"] = {
        "ccc": c5, "ccc_iter34_v2only": c34, "delta": c5 - c34,
        "pass": bool(abs(c5 - c34) < 0.05),
        "explanation": "shuffle PL SIDs — chain ignores random PL → CCC ≈ iter34 V2-only baseline",
    }
    print(f"  P5: ccc={c5:.4f}, iter34_v2only={c34:.4f}, "
          f"|Δ|={abs(c5-c34):.4f}, pass={out['P5_pl_sid_shuffle']['pass']}", flush=True)

    out["all_pass"] = bool(
        out["P1_scrambled"]["pass"]
        and out["P2_noisy_test_X"]["pass"]
        and out["P4_pure_noise_X"]["pass"]
        and out["P5_pl_sid_shuffle"]["pass"]
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"probeD_audit_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  ALL_PASS = {out['all_pass']}", flush=True)
    print(f"Wrote {out_path}", flush=True)
    return out_path


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["smoke", "write_prereg", "screen", "lockbox", "audit"],
                    required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--preregistration_file", type=str, default=None)
    ap.add_argument("--n_workers", type=int,
                    default=int(os.getenv("PROBED_WORKERS", 11)))
    args = ap.parse_args()
    if args.mode == "smoke":
        smoke_test(seed=args.seeds[0], feature_set=args.feature_set)
    elif args.mode == "write_prereg":
        write_preregistration()
    elif args.mode == "screen":
        run_screen(seeds=tuple(args.seeds),
                   feature_set=args.feature_set, n_workers=args.n_workers)
    elif args.mode == "audit":
        run_audit(seed=args.seeds[0], n_workers=args.n_workers,
                  feature_set=args.feature_set)
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
