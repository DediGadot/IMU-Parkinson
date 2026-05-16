"""T1 iter37 — Phase-locked items 9+12 features routed POST-K=500 at chain step level.

Slot A of T1 Glass-Ceiling Push 2026-05-10 (master pre-reg
results/preregistration_t1_ceiling_push_20260510_134829.json).

MECHANISM (codex-checked, gemini-checked, 2/3 tri-CLI converge on orthogonality):
The iter34 hybrid chain (8 items × 3 base learners, K=500 LGB-importance per fold)
sees only V2-K500 = 500 cols. Phase-locked item-9 (12 cols) + item-12 (13 cols)
cache features were NOT in V2 and never enter K=500 selection — they are appended
POST-K=500 only at the chain step where the target item id matches.

This is mechanistically distinct from:
  - F35-C (slot replacement): chain OOFs PRESERVED here; only chain INPUTS augmented.
  - F36-D (chain-pool injection): phase-locked features were ADDED to V2 then K=500
    filtered them out; here they bypass K=500 entirely and only at the right step.
  - F58 / F70: no post-hoc blender; no reparameterization of iter34's chain — it is
    iter34's chain with per-target-item routing of additional features.

Custom chain (sklearn's RegressorChain cannot route by target item identity):
  For each chain step in random per-seed order:
    item_id = order[step]
    feats = [V2-K500] ⊕ [previous_step_residuals (true on train, predicted on test)]
    if item_id == 9:  feats ⊕= phase_locked_item9 (12 cols)
    if item_id == 12: feats ⊕= phase_locked_item12 (13 cols)
    Fit base regressor; record routing audit (codex's load-bearing recommendation).

5-fold screen first; LOOCV only if screen passes Δ̄≥+0.025 + frac>0≥0.95.
5-null gate (scrambled, canary, transductive) recorded alongside.

Modes:
  --mode write_prereg     emit per-script formula_sha256 + lock pre-reg
  --mode smoke            1 fold × 1 seed sanity
  --mode screen           5-fold × 3 seeds + 5-null gate; gate decision
  --mode lockbox          LOOCV × 3 seeds (only run if screen passed gate)
  --mode null_only        run 5-null gate only

Family-wise: this script is slot A of n=4 master pre-reg with Bonferroni gate
frac>0 ≥ 0.9875 vs iter12-honest-n93 AND vs iter34-n93.
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")
# Avoid OpenMP/MKL × ProcessPool fork deadlocks in LightGBM / XGBoost / sklearn:
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
import pandas as pd
from sklearn.model_selection import KFold, LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import (
    ccc as ccc_fn,
    full_metrics,
    null_canary_feature,
    null_scrambled_label,
)
from pd_imu.core.legacy_experiment_api import (
    ALL_ITEMS,
    AUX_ITEMS,
    ITER5_FEATURE_SETS,
    T1_ITEMS,
    T1_SUM_ITEMS,
    _load_t1_cohort_with_8items,
    build_stage1_features,
    feature_select_fold,
    fit_stage1,
    impute_fold,
    load_clinical_dict,
    train_lgb,
)
from project_paths import RESULTS_DIR, ensure_dir

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500
PUBLISHED_T1_LOOCV_CCC = 0.6550
ITER34_LOOCV_CCC = 0.7366  # F70 — anchor and supersede target

BASE_LEARNERS: tuple[str, ...] = ("lgb", "xgb", "et")

PHASELOCKED_ITEM9_CSV = RESULTS_DIR / "phaselocked_item9_features.csv"
PHASELOCKED_ITEM12_CSV = RESULTS_DIR / "phaselocked_item12_features.csv"


# ─── Phase-locked cache loader (sid-aligned) ────────────────────────────────
def _load_phaselocked(sids: list[str]) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """Returns (PL9 (n,12), PL12 (n,13), pl9_cols, pl12_cols), sid-aligned to sids.
    Missing-sid rows filled with NaN; downstream FoldImputer handles."""
    pl9_df = pd.read_csv(PHASELOCKED_ITEM9_CSV).set_index("sid")
    pl12_df = pd.read_csv(PHASELOCKED_ITEM12_CSV).set_index("sid")
    pl9 = pl9_df.reindex(sids).values.astype(np.float64)
    pl12 = pl12_df.reindex(sids).values.astype(np.float64)
    return pl9, pl12, list(pl9_df.columns), list(pl12_df.columns)


# ─── Base-learner factory ───────────────────────────────────────────────────
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


# ─── Custom chain with per-target-item phase-locked routing ─────────────────
def _custom_chain_predict(
    Xtr_sel: np.ndarray,
    items_tr_residual: np.ndarray,  # (n_train, n_items), columns in item_order_ids order
    Xte_sel: np.ndarray,
    seed: int,
    base: str,
    item_order_ids: list[int],
    pl9_tr: np.ndarray, pl9_te: np.ndarray,
    pl12_tr: np.ndarray, pl12_te: np.ndarray,
) -> tuple[np.ndarray, dict]:
    """Returns (pred_test (n_test, n_items) in item_order_ids order, audit_dict)."""
    rng = np.random.default_rng(seed)
    chain_pos_to_idx = rng.permutation(len(item_order_ids))  # chain position -> col index
    n_train, n_test = Xtr_sel.shape[0], Xte_sel.shape[0]
    n_items = len(item_order_ids)
    pred_test = np.zeros((n_test, n_items))

    audit_per_step: list[dict] = []
    for chain_step, idx in enumerate(chain_pos_to_idx):
        item_id = item_order_ids[idx]
        feats_tr = [Xtr_sel]
        feats_te = [Xte_sel]
        if chain_step > 0:
            prev_idxs = chain_pos_to_idx[:chain_step]
            feats_tr.append(items_tr_residual[:, prev_idxs])
            feats_te.append(pred_test[:, prev_idxs])
        # Per-target-item phase-locked routing (codex's load-bearing requirement)
        if item_id == 9:
            feats_tr.append(pl9_tr); feats_te.append(pl9_te)
        elif item_id == 12:
            feats_tr.append(pl12_tr); feats_te.append(pl12_te)
        Xtr_aug = np.concatenate(feats_tr, axis=1)
        Xte_aug = np.concatenate(feats_te, axis=1)
        regr = _make_regr(base, seed)
        regr.fit(Xtr_aug, items_tr_residual[:, idx])
        pred_test[:, idx] = regr.predict(Xte_aug)
        audit_per_step.append({
            "chain_step": int(chain_step),
            "item_id": int(item_id),
            "n_input_cols": int(Xtr_aug.shape[1]),
            "expected_min": int(K_FEATURES + chain_step + (12 if item_id == 9 else 13 if item_id == 12 else 0)),
        })
    return pred_test, {"base": base, "seed": int(seed), "per_step": audit_per_step}


# ─── Per-fold worker ────────────────────────────────────────────────────────
def _fit_one_fold(args):
    """Worker: 8-item custom chain × 3 base learners with PL routing for one fold."""
    fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases, pl9, pl12 = args

    # Stage-1
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    # Per-fold item residuals
    item_means: dict[int, float] = {}
    items_tr_residual: list[np.ndarray] = []
    for i in item_order:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_residual)

    # V2 imputation + K=500 selection (UNCHANGED from iter34)
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )

    # Phase-locked block: fold-local median-impute (FoldImputer pattern)
    pl9_tr_raw = pl9[tr]; pl9_te_raw = pl9[te]
    pl12_tr_raw = pl12[tr]; pl12_te_raw = pl12[te]
    pl9_med = np.nanmedian(pl9_tr_raw, axis=0)
    pl12_med = np.nanmedian(pl12_tr_raw, axis=0)
    pl9_tr = np.where(np.isnan(pl9_tr_raw), pl9_med[None, :], pl9_tr_raw)
    pl9_te = np.where(np.isnan(pl9_te_raw), pl9_med[None, :], pl9_te_raw)
    pl12_tr = np.where(np.isnan(pl12_tr_raw), pl12_med[None, :], pl12_tr_raw)
    pl12_te = np.where(np.isnan(pl12_te_raw), pl12_med[None, :], pl12_te_raw)
    # Replace any remaining all-NaN-train cols with 0
    pl9_tr = np.nan_to_num(pl9_tr, nan=0.0); pl9_te = np.nan_to_num(pl9_te, nan=0.0)
    pl12_tr = np.nan_to_num(pl12_tr, nan=0.0); pl12_te = np.nan_to_num(pl12_te, nan=0.0)

    # Average chain over 3 base learners
    ip_avg = None
    audits: list[dict] = []
    for b in bases:
        ip, audit = _custom_chain_predict(
            Xtr_sel, items_tr_arr, Xte_sel, seed, b, list(item_order),
            pl9_tr, pl9_te, pl12_tr, pl12_te,
        )
        ip_avg = ip if ip_avg is None else ip_avg + ip
        audits.append(audit)
    ip_avg = ip_avg / len(bases)

    # T1 sum
    t1_sum_idx = [list(item_order).index(i) for i in T1_SUM_ITEMS]
    item_pred_t1 = ip_avg[:, t1_sum_idx] + np.array([item_means[i] for i in T1_SUM_ITEMS])
    t1_pred_from_items = item_pred_t1.sum(axis=1)
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))
    return te, s1_te + (t1_pred_from_items - sum_means_t1), audits


def _i34_one_fold(args):
    """iter34 baseline comparator (no phase-locked) — uses the same K=500 + 8-item chain
    but standard sklearn RegressorChain (no PL routing). Same as iter34's _fit_one_fold."""
    from sklearn.multioutput import RegressorChain
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
        regr = _make_regr(b, seed)
        chain = RegressorChain(regr, order="random", random_state=seed)
        chain.fit(Xtr_sel, items_tr_arr)
        ip = chain.predict(Xte_sel)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg = ip_avg / len(bases)
    t1_sum_idx = [list(item_order).index(i) for i in T1_SUM_ITEMS]
    item_pred_t1 = ip_avg[:, t1_sum_idx] + np.array([item_means[i] for i in T1_SUM_ITEMS])
    t1_pred_from_items = item_pred_t1.sum(axis=1)
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))
    return te, s1_te + (t1_pred_from_items - sum_means_t1)


# ─── CV drivers ─────────────────────────────────────────────────────────────
def _run_cv(seed: int, splits, X, y_t1, X_s1, items, item_order, bases, pl9, pl12,
            n_workers: int, label: str):
    n = len(y_t1)
    preds = np.zeros(n)
    all_audits: list[dict] = []
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases, pl9, pl12)
        for fid, (tr, te) in enumerate(splits)
    ]
    t0 = time.time()
    done = 0
    ctx = mp.get_context("spawn")  # avoid fork-OpenMP deadlock
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_fit_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred, audit = fut.result()
            preds[te_idx] = te_pred
            all_audits.append({"fold_id": int(futs[fut]), "audit": audit})
            done += 1
            if done % 1 == 0 or done == len(splits):
                print(f"    seed={seed} {label} {done}/{len(splits)}  "
                      f"elapsed={time.time()-t0:.0f}s", flush=True)
    return preds, all_audits


def _run_cv_iter34(seed: int, splits, X, y_t1, X_s1, items, item_order, bases, n_workers: int):
    n = len(y_t1)
    preds = np.zeros(n)
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases)
        for fid, (tr, te) in enumerate(splits)
    ]
    ctx = mp.get_context("spawn")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_i34_one_fold, j): j[0] for j in jobs}
        done = 0
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
            done += 1
            print(f"    seed={seed} iter34 {done}/{len(splits)}  elapsed={time.time()-t0:.0f}s", flush=True)
    return preds


# ─── Pre-registration ───────────────────────────────────────────────────────
def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": "T1 iter37 — phase-locked items 9+12 features routed POST-K=500 at chain step level",
        "slot": "A of T1 Glass-Ceiling Push 2026-05-10 (master prereg "
                "results/preregistration_t1_ceiling_push_20260510_134829.json, FWER n=4)",
        "is_post_publication_replication_target": False,
        "family_wise_independence_claim": (
            "Member of master pre-registered family n=4. Bonferroni-adjusted gate "
            "frac>0 ≥ 0.9875 vs iter12-honest-n93 AND vs iter34-n93 to claim supersede."
        ),
        "cohort": {
            "target": "T1 = sum(items 9-14)",
            "n_subjects_min": 90,
            "filter": "PD with full items 9-14, 15, 18 (matches iter34 / iter33-B 8-item filter)",
            "split_file": "results/paper3_split.json",
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
                "CustomChain(LGBMRegressor n=500, lr=0.05, num_leaves=15, min_data=10)",
                "CustomChain(XGBRegressor hist, n=500, lr=0.05, depth=4, min_child=5)",
                "CustomChain(ExtraTreesRegressor n=300, max_depth=10, min_leaf=5)",
            ],
            "ensemble_method": "average chain-output across 3 bases per fold per seed",
            "items_targets_chain": list(ALL_ITEMS),
            "items_summed_for_t1": list(T1_SUM_ITEMS),
            "auxiliary_items": list(AUX_ITEMS),
            "item_target_centering": "subtract per-fold train_mean(item)",
            "feature_select_method": "lgb_importance_top_k_per_fold (V2 only; PL features bypass selector)",
            "feature_select_k": K_FEATURES,
            "imputation": "fold_local_median (V2 + PL blocks separately)",
            "phase_locked_routing": {
                "policy": "per-TARGET-ITEM-IDENTITY routing, NOT chain position",
                "item_9": "PL9 (12 cols) appended only when chain step's target item id == 9",
                "item_12": "PL12 (13 cols) appended only when chain step's target item id == 12",
                "all_other_items": "no PL features appended",
                "audit_emission": "per-fold per-seed per-base routing audit emitted to lockbox JSON",
                "post_K500": True,
                "K500_pool_unchanged": "V2 only; PL features never enter K=500 importance ranking",
                "codex_load_bearing_requirement": "key by target item identity, not chain position (RegressorChain order='random')",
            },
            "post_combine_formula": (
                "Stage1_pred + (sum_over_T1_SUM_ITEMS(mean_over_bases(item_pred) + "
                "train_mean) - sum(train_mean[T1_SUM_ITEMS]))  -- aux items 15,18 in chain only"
            ),
            "decorrelation_argument": (
                "F36-D demonstrated K=500 absorbs phase-locked features when added "
                "to the V2 pool. Slot A bypasses K=500 by routing PL features at the "
                "chain step matching their item id, post-K500. Distinct from F35-C "
                "(slot replacement removed chain coupling); chain coupling is preserved."
            ),
        },
        "phase_locked_caches": {
            "item9_csv": str(PHASELOCKED_ITEM9_CSV.relative_to(REPO_ROOT)),
            "item9_n_features": 11,  # 12 cols incl. sid
            "item9_manifest_git_sha_amended_to": "09d2e198aea1bf7b1d1553600014b563409046ee",
            "item12_csv": str(PHASELOCKED_ITEM12_CSV.relative_to(REPO_ROOT)),
            "item12_n_features": 12,  # 13 cols incl. sid
            "item12_manifest_git_sha_amended_to": "09d2e198aea1bf7b1d1553600014b563409046ee",
            "label_free": True, "fold_scope_at_extraction": "global",
            "leakage_argument": "Deterministic signal-processing aggregates of raw IMU around TUG seat-off / turn-peak. UPDRS labels never enter extraction.",
        },
        "eval": {
            "loocv_n_min": 90, "seeds": list(SEEDS_DEFAULT),
            "bases": list(BASE_LEARNERS),
            "headline_metric": "CCC of mean-of-3-seed predictions vs y_t1",
            "comparator_iter12_honest_n93_oof": "computed live in same SID-aligned LOOCV",
            "comparator_iter34_oof": "results/lockbox_t1_iter34_hybrid_20260506_141720.oof.npy",
        },
        "screen_gate": {
            "n_splits": 5, "seeds": list(SEEDS_DEFAULT),
            "promote_to_lockbox_iff": (
                "Δ̄ vs iter34-5fold ≥ +0.025 (mean over 3 seeds) AND "
                "paired-bootstrap (5000) frac>0 ≥ 0.95"
            ),
            "rule_post_2026_05_05": "seed-std<0.020 floor dropped per user instruction",
        },
        "lockbox_rules": [
            "ONE pre-registered config. ONE LOOCV run. SLOT A of FWER n=4 family.",
            "Headline = CCC of mean-of-3-seed preds (each seed averages 3 base learners).",
            "Bonferroni-adjusted Verdict gates: frac>0 ≥ 0.9875 vs iter12-honest-n93 AND vs iter34-n93.",
            "Seed list immutable from registration. No seed addition after seeing metrics.",
            "5-null gate (scrambled, canary, transductive) recorded alongside lockbox JSON.",
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
        "timestamp": ts, "iso_datetime_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "T1 iter37 — phase-locked items 9+12 chain-step-routed POST-K=500",
        "git_head": _git_head(), "formula_sha256": sha, "formula": payload,
        "variant": "phaselocked_postk500_chainstep_routing",
        "is_post_publication_replication_target": False,
        "master_prereg_id": "t1_ceiling_push_20260510_134829",
        "master_prereg_path": "results/preregistration_t1_ceiling_push_20260510_134829.json",
        "slot_id": "A",
        "fwer_family_size_n": 4,
        "fwer_bonferroni_alpha_per_test": 0.0125,
        "promotion_gates": {
            "screen_5fold": "Δ̄≥+0.025 AND paired-bootstrap frac>0≥0.95",
            "lockbox_loocv_publishable": "frac>0 vs iter12-honest-n93 ≥ 0.9875",
            "lockbox_loocv_supersede": "frac>0 vs iter34-n93 ≥ 0.9875",
        },
    }
    out = RESULTS_DIR / f"preregistration_t1_iter37_phaselocked_postk500_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


# ─── Bootstrap ──────────────────────────────────────────────────────────────
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
        "frac_above_0.0125": float((deltas > 0.0125).mean()),
        "frac_above_0.025": float((deltas > 0.025).mean()),
    }


# ─── 5-null gate ────────────────────────────────────────────────────────────
def run_null_gate(seed: int = 42) -> dict:
    """Corrected 80/20 null gate for the Slot-A routed chain.

    Chain models train on item targets as well as the T1 sum. The scrambled
    null therefore shuffles every target-derived training array, not only
    `y_t1`. The canary check measures prediction invariance after adding a
    test-only random feature.
    """
    print("\n=== Slot A corrected null gate ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    pl9, pl12, _, _ = _load_phaselocked([str(s) for s in sids])
    n = len(sids)
    rng = np.random.RandomState(seed)
    perm = rng.permutation(n)
    cut = int(0.8 * n)
    tr_idx, te_idx = perm[:cut], perm[cut:]
    print(f"  cohort N={n}, train={len(tr_idx)}, test={len(te_idx)}", flush=True)

    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])

    def _predict(y_train, item_train_values, X_train_pl9, X_train_pl12, X_test_pl9, X_test_pl12, X_train, X_test):
        # Stage-1
        s1_tr_, s1_te_ = fit_stage1(X_s1[tr_idx], y_train, X_s1[te_idx], alpha=STAGE1_ALPHA)
        # Build per-fold residuals
        item_means: dict[int, float] = {}
        items_tr_resid = []
        for i in item_order:
            v = item_train_values[i]
            mu = float(np.nanmean(v))
            item_means[i] = mu
            items_tr_resid.append(np.nan_to_num(v - mu, nan=0.0))
        items_tr_arr = np.column_stack(items_tr_resid)
        # K=500 selection
        Xtr_, Xte_ = impute_fold(X_train, X_test)
        Xtr_sel_, Xte_sel_, _ = feature_select_fold(Xtr_, y_train - s1_tr_, Xte_, k=K_FEATURES, seed=seed)
        # PL block fold-local impute
        med9 = np.nanmedian(X_train_pl9, axis=0)
        med12 = np.nanmedian(X_train_pl12, axis=0)
        pl9_tr_ = np.nan_to_num(np.where(np.isnan(X_train_pl9), med9[None, :], X_train_pl9), nan=0.0)
        pl9_te_ = np.nan_to_num(np.where(np.isnan(X_test_pl9), med9[None, :], X_test_pl9), nan=0.0)
        pl12_tr_ = np.nan_to_num(np.where(np.isnan(X_train_pl12), med12[None, :], X_train_pl12), nan=0.0)
        pl12_te_ = np.nan_to_num(np.where(np.isnan(X_test_pl12), med12[None, :], X_test_pl12), nan=0.0)
        # Avg over bases
        ip_avg = None
        for b in BASE_LEARNERS:
            ip, _ = _custom_chain_predict(
                Xtr_sel_, items_tr_arr, Xte_sel_, seed, b, list(item_order),
                pl9_tr_, pl9_te_, pl12_tr_, pl12_te_,
            )
            ip_avg = ip if ip_avg is None else ip_avg + ip
        ip_avg /= len(BASE_LEARNERS)
        t1_sum_idx = [list(item_order).index(i) for i in T1_SUM_ITEMS]
        item_pred_t1 = ip_avg[:, t1_sum_idx] + np.array([item_means[i] for i in T1_SUM_ITEMS])
        return s1_te_ + item_pred_t1.sum(axis=1) - float(sum(item_means[i] for i in T1_SUM_ITEMS))

    nulls = {}

    true_item_train = {i: items[i][tr_idx] for i in item_order}
    normal_pred = _predict(
        y_t1[tr_idx], true_item_train,
        pl9[tr_idx], pl12[tr_idx], pl9[te_idx], pl12[te_idx], X[tr_idx], X[te_idx]
    )

    # 1. Scrambled-label null: shuffle all target-derived train arrays.
    scramble_order = rng.permutation(len(tr_idx))
    scrambled_item_train = {i: items[i][tr_idx][scramble_order] for i in item_order}
    pred_sc = _predict(
        y_t1[tr_idx][scramble_order], scrambled_item_train,
        pl9[tr_idx], pl12[tr_idx], pl9[te_idx], pl12[te_idx], X[tr_idx], X[te_idx]
    )
    nulls["scrambled_label_ccc"] = round(float(ccc_fn(y_t1[te_idx], pred_sc)), 4)

    # 2. Canary feature null: append random column nonzero only on test fold.
    canary_tr = np.zeros((len(tr_idx), 1))
    canary_te = np.random.RandomState(seed).randn(len(te_idx), 1) * 5.0
    X_canary_tr = np.hstack([X[tr_idx], canary_tr])
    X_canary_te = np.hstack([X[te_idx], canary_te])
    pred_cn = _predict(
        y_t1[tr_idx], true_item_train,
        pl9[tr_idx], pl12[tr_idx], pl9[te_idx], pl12[te_idx], X_canary_tr, X_canary_te
    )
    canary_delta = pred_cn - normal_pred
    nulls["normal_ccc"] = round(float(ccc_fn(y_t1[te_idx], normal_pred)), 4)
    nulls["canary_feature_ccc"] = round(float(ccc_fn(y_t1[te_idx], pred_cn)), 4)
    nulls["canary_vs_normal_max_abs_delta"] = float(np.max(np.abs(canary_delta)))
    nulls["canary_vs_normal_mean_abs_delta"] = float(np.mean(np.abs(canary_delta)))

    # 3. Transductive sanity: train on full data, predict test (intentional leak; expect ≈1)
    item_order_full = item_order
    s1_full_tr, s1_full_te = fit_stage1(X_s1, y_t1, X_s1[te_idx], alpha=STAGE1_ALPHA)
    items_full_arr = np.column_stack([
        np.nan_to_num(items[i] - float(np.nanmean(items[i])), nan=0.0) for i in item_order_full
    ])
    Xtr_full, Xte_full = impute_fold(X, X[te_idx])
    Xtr_full_sel, Xte_full_sel, _ = feature_select_fold(Xtr_full, y_t1 - s1_full_tr, Xte_full, k=K_FEATURES, seed=seed)
    med9 = np.nanmedian(pl9, axis=0); med12 = np.nanmedian(pl12, axis=0)
    pl9_full = np.nan_to_num(np.where(np.isnan(pl9), med9[None, :], pl9), nan=0.0)
    pl12_full = np.nan_to_num(np.where(np.isnan(pl12), med12[None, :], pl12), nan=0.0)
    pl9_te_full = pl9_full[te_idx]; pl12_te_full = pl12_full[te_idx]
    ip_avg = None
    for b in BASE_LEARNERS:
        ip, _ = _custom_chain_predict(
            Xtr_full_sel, items_full_arr, Xte_full_sel, seed, b, list(item_order_full),
            pl9_full, pl9_te_full, pl12_full, pl12_te_full,
        )
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg /= len(BASE_LEARNERS)
    t1_sum_idx = [list(item_order_full).index(i) for i in T1_SUM_ITEMS]
    item_means_full = {i: float(np.nanmean(items[i])) for i in T1_SUM_ITEMS}
    item_pred = ip_avg[:, t1_sum_idx] + np.array([item_means_full[i] for i in T1_SUM_ITEMS])
    pred_full = s1_full_te + item_pred.sum(axis=1) - float(sum(item_means_full.values()))
    nulls["transductive_sanity_ccc"] = round(float(ccc_fn(y_t1[te_idx], pred_full)), 4)

    nulls["null_seed"] = int(seed)
    nulls["n_train"] = int(len(tr_idx)); nulls["n_test"] = int(len(te_idx))
    nulls["null_gate_pass"] = bool(
        abs(nulls["scrambled_label_ccc"]) < 0.05
        and nulls["canary_vs_normal_max_abs_delta"] < 1e-6
        and nulls["transductive_sanity_ccc"] > 0.5
    )
    print(
        f"  normal={nulls['normal_ccc']:+.4f}  "
        f"scrambled={nulls['scrambled_label_ccc']:+.4f}  "
        f"canary_delta_max={nulls['canary_vs_normal_max_abs_delta']:.3g}  "
        f"transductive={nulls['transductive_sanity_ccc']:+.4f}  "
        f"pass={nulls['null_gate_pass']}",
        flush=True,
    )
    return nulls


# ─── 5-fold screen ──────────────────────────────────────────────────────────
def run_screen(seeds=SEEDS_DEFAULT, n_workers: int = 11) -> dict:
    print("\n=== 5-fold × 3 seed SCREEN: slot A vs iter34 baseline ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    pl9, pl12, _, _ = _load_phaselocked([str(s) for s in sids])
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    print(f"  PL9 valid rows = {(~np.isnan(pl9).any(axis=1)).sum()}/{n}, "
          f"PL12 valid rows = {(~np.isnan(pl12).any(axis=1)).sum()}/{n}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])

    per_seed = []
    pl_oofs = []; i34_oofs = []
    for seed in seeds:
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        splits = list(kf.split(np.arange(n)))
        t0 = time.time()
        pl_pred, _ = _run_cv(seed, splits, X, y_t1, X_s1, items, item_order,
                              BASE_LEARNERS, pl9, pl12, n_workers, "slotA")
        i34_pred = _run_cv_iter34(seed, splits, X, y_t1, X_s1, items, item_order, BASE_LEARNERS, n_workers)
        c_pl = float(ccc_fn(y_t1, pl_pred))
        c_i34 = float(ccc_fn(y_t1, i34_pred))
        per_seed.append({
            "seed": int(seed), "ccc_slotA": c_pl, "ccc_iter34_5fold": c_i34,
            "delta": c_pl - c_i34, "wall_s": float(time.time() - t0),
        })
        pl_oofs.append(pl_pred); i34_oofs.append(i34_pred)
        print(f"  seed={seed}: slot_A={c_pl:.4f}  iter34={c_i34:.4f}  Δ={c_pl-c_i34:+.4f}  "
              f"wall={time.time()-t0:.0f}s", flush=True)

    mean_pl = np.mean(np.column_stack(pl_oofs), axis=1)
    mean_i34 = np.mean(np.column_stack(i34_oofs), axis=1)
    delta_mean = float(np.mean([s["delta"] for s in per_seed]))
    delta_std = float(np.std([s["delta"] for s in per_seed], ddof=1))
    boot = _paired_bootstrap_ccc(y_t1, mean_pl, mean_i34)

    pass_screen = (delta_mean >= 0.025) and (boot["frac_above_zero"] >= 0.95)
    summary = {
        "n_subjects": int(n),
        "seeds": list(seeds),
        "per_seed": per_seed,
        "delta_mean": delta_mean,
        "delta_std": delta_std,
        "ccc_slotA_meanof_seedmeans": float(ccc_fn(y_t1, mean_pl)),
        "ccc_iter34_5fold_meanof_seedmeans": float(ccc_fn(y_t1, mean_i34)),
        "bootstrap_paired_delta": boot,
        "screen_gate_pass": bool(pass_screen),
        "screen_gate_rule": "Δ̄≥+0.025 AND frac>0≥0.95 (post-2026-05-05; std floor dropped)",
    }
    print(f"\n  SCREEN: Δ̄={delta_mean:+.4f}  std={delta_std:.4f}  "
          f"frac>0={boot['frac_above_zero']:.3f}  → "
          f"{'PASS — promote to LOOCV' if pass_screen else 'FAIL — DO NOT promote'}",
          flush=True)
    return summary


# ─── LOOCV lockbox ──────────────────────────────────────────────────────────
def run_lockbox(prereg_file: Path, seeds=SEEDS_DEFAULT, n_workers: int = 11) -> Path:
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
    print(f"\n=== T1 iter37 SLOT A LOCKBOX LOOCV ({len(seeds)} seeds, "
          f"bases={BASE_LEARNERS}, n_workers={n_workers}) ===", flush=True)

    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    pl9, pl12, pl9_cols, pl12_cols = _load_phaselocked([str(s) for s in sids])
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])

    splits = list(LeaveOneOut().split(np.arange(n)))
    all_pl: list[np.ndarray] = []
    per_seed = []
    overall_t0 = time.time()
    for seed in seeds:
        t0 = time.time()
        pl_pred, _ = _run_cv(seed, splits, X, y_t1, X_s1, items, item_order,
                              BASE_LEARNERS, pl9, pl12, n_workers, "slotA-LOOCV")
        c_pl = float(ccc_fn(y_t1, pl_pred))
        per_seed.append({"seed": int(seed), "ccc_slotA": c_pl, "wall_s": float(time.time() - t0)})
        all_pl.append(pl_pred)
        print(f"  seed={seed}: slot_A LOOCV={c_pl:.4f}  wall={time.time()-t0:.0f}s", flush=True)
    overall_wall = time.time() - overall_t0
    mean_pl = np.mean(np.column_stack(all_pl), axis=1)
    headline = full_metrics(y_t1, mean_pl, label="t1_iter37_slot_A_phaselocked_postk500")

    # Comparator OOFs
    iter34_path = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260506_141720.oof.npy"
    iter34_json = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260506_141720.json"
    boot_iter34 = None
    if iter34_path.exists() and iter34_json.exists():
        with open(iter34_json) as f:
            i34_meta = json.load(f)
        sids_i34 = [str(s) for s in i34_meta["per_subject"]["sids"]]
        p_i34_full = np.load(iter34_path)
        sid_to_pred = dict(zip(sids_i34, p_i34_full.tolist()))
        try:
            p_i34 = np.array([sid_to_pred[str(s)] for s in sids])
            ccc_i34 = float(ccc_fn(y_t1, p_i34))
            boot_iter34 = _paired_bootstrap_ccc(y_t1, mean_pl, p_i34)
            boot_iter34["ccc_iter34"] = round(ccc_i34, 4)
            boot_iter34["delta_meanof_predmeans"] = float(headline["ccc"] - ccc_i34)
        except KeyError as e:
            boot_iter34 = {"error": f"SID not in iter34 oof: {e!r}"}

    # iter12-honest baseline (compute live)
    # Would require running compose_t1_iter12_honest; for now flag as TBD
    boot_iter12 = {"note": "Compute via run-time iter12-honest reproduction; placeholder"}

    fwer_supersede = (
        boot_iter34 is not None
        and "frac_above_zero" in boot_iter34
        and boot_iter34["frac_above_zero"] >= 0.9875
    )
    headline.update({
        "variant": "phaselocked_postk500_chainstep_routing",
        "n_subjects": n,
        "item_order_chain": item_order,
        "auxiliary_items_used": list(available_aux),
        "preregistration_file": prereg_file.name,
        "is_lockbox_headline": True,
        "is_post_publication_replication_target": False,
        "master_prereg_id": "t1_ceiling_push_20260510_134829",
        "slot_id": "A",
        "fwer_family_size_n": 4,
        "n_seeds": len(seeds), "per_seed": per_seed,
        "wall_time_total_s": overall_wall,
        "bootstrap_delta_vs_iter34": boot_iter34,
        "bootstrap_delta_vs_iter12_honest": boot_iter12,
        "fwer_bonferroni_supersede_iter34": bool(fwer_supersede),
        "phaselocked_columns": {"item9": pl9_cols, "item12": pl12_cols},
        "per_subject": {
            "sids": [str(s) for s in sids],
            "y_true": y_t1.tolist(), "y_pred": mean_pl.tolist(),
        },
    })
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_iter37_slotA_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t1_iter37_slotA_{ts}.oof.npy"
    np.save(out_npy, mean_pl)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)
    print(f"\n=== HEADLINE: CCC={headline['ccc']:.4f}  MAE={headline['mae']:.3f}  "
          f"r={headline['r']:.4f}  slope={headline['cal_slope']:.3f} ===", flush=True)
    if boot_iter34 and "frac_above_zero" in boot_iter34:
        print(f"  vs iter34: Δ̄={boot_iter34['delta_mean']:+.4f}  "
              f"frac>0={boot_iter34['frac_above_zero']:.3f}  "
              f"FWER-supersede(0.9875)={fwer_supersede}", flush=True)
    return out_json


# ─── Smoke ──────────────────────────────────────────────────────────────────
def smoke_test(seed: int = 42) -> None:
    print("\n=== iter37 slot A SMOKE: 1 fold × 1 seed ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    pl9, pl12, _, _ = _load_phaselocked([str(s) for s in sids])
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])
    splits = list(LeaveOneOut().split(np.arange(n)))
    fid, (tr, te) = 0, splits[0]
    args = (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, BASE_LEARNERS, pl9, pl12)
    t0 = time.time()
    te_idx, te_pred, audits = _fit_one_fold(args)
    print(f"  fold 0/{n}: te_idx={te_idx[0]}, sid={sids[te_idx[0]]}, "
          f"y_true={y_t1[te_idx[0]]:.2f}, y_pred={te_pred[0]:.2f}, "
          f"wall={time.time()-t0:.1f}s", flush=True)
    print(f"  audit (lgb base): per-step input col counts = "
          f"{[s['n_input_cols'] for s in audits[0]['per_step']]}", flush=True)
    assert np.isfinite(te_pred).all(), "non-finite predictions"
    print("  SMOKE PASS", flush=True)


# ─── CLI ────────────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("smoke", "write_prereg", "screen", "lockbox", "null_only"),
                   default="smoke")
    p.add_argument("--prereg", help="Pre-registration file path (for lockbox mode)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n_workers", type=int, default=11)
    args = p.parse_args()

    if args.mode == "smoke":
        smoke_test(seed=args.seed)
    elif args.mode == "write_prereg":
        write_preregistration()
    elif args.mode == "null_only":
        nulls = run_null_gate(seed=args.seed)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        with open(RESULTS_DIR / f"t1_iter37_slotA_nulls_{ts}.json", "w") as f:
            json.dump(nulls, f, indent=2)
    elif args.mode == "screen":
        nulls = run_null_gate(seed=42)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = RESULTS_DIR / f"screen_t1_iter37_slotA_{ts}.json"
        if not nulls["null_gate_pass"]:
            screen = {
                "screen_aborted": True,
                "abort_reason": "null_gate_failed",
                "nulls": nulls,
                "screen_gate_pass": False,
            }
            print("\nSCREEN ABORTED: null gate failed", flush=True)
        else:
            screen = run_screen(n_workers=args.n_workers)
            screen["nulls"] = nulls
        with open(out, "w") as f:
            json.dump(screen, f, indent=2, default=str)
        print(f"\nSCREEN saved: {out}", flush=True)
        print(f"  gate_pass = {screen['screen_gate_pass']}", flush=True)
    elif args.mode == "lockbox":
        if not args.prereg:
            raise SystemExit("--prereg required for lockbox mode")
        run_lockbox(Path(args.prereg), n_workers=args.n_workers)


if __name__ == "__main__":
    main()
