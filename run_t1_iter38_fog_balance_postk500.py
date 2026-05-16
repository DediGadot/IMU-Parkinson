"""T1 iter38 — FoG event statistics + balance geometry routed POST-K=500 at chain
step level for items 11 (FoG) and 13 (posture).

Slot B of T1 Glass-Ceiling Push 2026-05-10 (master pre-reg
results/preregistration_t1_ceiling_push_20260510_134829.json).

PIVOT FROM ORIGINAL kymatio-scattering DESIGN per tri-CLI 2026-05-10:
3-of-3 CLIs said SKIP kymatio for V2 redundancy / PCA-noise reasons. 2-of-3
(codex+kimi) converged on REPRESENTATION CHANGE for items 11+13:
  - Item 11 (FoG): episodic event statistics, NOT continuous spectral regression
    (V2 + F14 wall: continuous Welch-band features absorbed). Cache provides 3
    scalars: fog_event_rate, fog_event_duration_mean, fog_event_duration_std.
  - Item 13 (posture): standing-segment Euler tilt geometry from Balance task
    only, NOT pooled-across-tasks features. F-iter54 used 30 axial features
    pooled across all gait tasks; here 5 features Balance-only.

Mechanism distinction from slot A:
  - Slot A (iter37): pre-built phase-locked items 9+12 cache, post-K500 routing
    at chain steps for items 9 and 12.
  - Slot B (iter38): pre-built FoG+balance cache, post-K500 routing at chain
    steps for items 11 and 13.
  - Same chain-step-routing axis, different items, different feature semantics.

Mechanism distinction from F-iter54:
  - F-iter54 used 30-dim axial pool with K=500 selection → absorption (joint
    pool variant) or item-13-only-LOOCV (gate-fail variance).
  - Slot B uses 8-dim focused block, post-K500 routing (escapes absorption),
    only for items 11+13 chain steps.

Custom chain identical to slot A; only the cache and routed item ids change.
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
import pandas as pd
from sklearn.model_selection import KFold, LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from pd_imu.core.legacy_experiment_api import (
    ALL_ITEMS, AUX_ITEMS, ITER5_FEATURE_SETS, T1_ITEMS, T1_SUM_ITEMS,
    _load_t1_cohort_with_8items, build_stage1_features, feature_select_fold,
    fit_stage1, impute_fold, load_clinical_dict,
)
from project_paths import RESULTS_DIR, ensure_dir

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500
ITER34_LOOCV_CCC = 0.7366
PUBLISHED_T1_LOOCV_CCC = 0.6550

BASE_LEARNERS: tuple[str, ...] = ("lgb", "xgb", "et")

CACHE_CSV = RESULTS_DIR / "fog_events_balance_geometry.csv"

# Routing target items for slot B (FoG → item 11; balance geometry → item 13)
FOG_FEATURE_PREFIX = "fog_"
BALANCE_FEATURE_PREFIX = "bal_"
FOG_TARGET_ITEM = 11
BALANCE_TARGET_ITEM = 13


def _load_slotb_cache(sids: list[str]):
    """Returns (FOG (n,3), BAL (n,5), fog_cols, bal_cols) sid-aligned. NaN where missing."""
    df = pd.read_csv(CACHE_CSV).set_index("sid")
    fog_cols = [c for c in df.columns if c.startswith(FOG_FEATURE_PREFIX)]
    bal_cols = [c for c in df.columns if c.startswith(BALANCE_FEATURE_PREFIX)]
    fog = df[fog_cols].reindex(sids).values.astype(np.float64)
    bal = df[bal_cols].reindex(sids).values.astype(np.float64)
    return fog, bal, fog_cols, bal_cols


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


def _custom_chain_predict(
    Xtr_sel, items_tr_residual, Xte_sel, seed, base, item_order_ids,
    fog_tr, fog_te, bal_tr, bal_te,
):
    """Custom chain with per-target-item routing (items 11, 13 only)."""
    rng = np.random.default_rng(seed)
    chain_pos_to_idx = rng.permutation(len(item_order_ids))
    n_train, n_test = Xtr_sel.shape[0], Xte_sel.shape[0]
    n_items = len(item_order_ids)
    pred_test = np.zeros((n_test, n_items))
    audit = []
    for chain_step, idx in enumerate(chain_pos_to_idx):
        item_id = item_order_ids[idx]
        feats_tr = [Xtr_sel]; feats_te = [Xte_sel]
        if chain_step > 0:
            prev = chain_pos_to_idx[:chain_step]
            feats_tr.append(items_tr_residual[:, prev])
            feats_te.append(pred_test[:, prev])
        if item_id == FOG_TARGET_ITEM:
            feats_tr.append(fog_tr); feats_te.append(fog_te)
        elif item_id == BALANCE_TARGET_ITEM:
            feats_tr.append(bal_tr); feats_te.append(bal_te)
        Xtr_aug = np.concatenate(feats_tr, axis=1)
        Xte_aug = np.concatenate(feats_te, axis=1)
        regr = _make_regr(base, seed)
        regr.fit(Xtr_aug, items_tr_residual[:, idx])
        pred_test[:, idx] = regr.predict(Xte_aug)
        audit.append({"chain_step": int(chain_step), "item_id": int(item_id), "n_input_cols": int(Xtr_aug.shape[1])})
    return pred_test, {"base": base, "seed": int(seed), "per_step": audit}


def _fit_one_fold(args):
    fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases, fog, bal = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    item_means: dict[int, float] = {}
    items_tr_resid: list[np.ndarray] = []
    for i in item_order:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_resid.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_resid)
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed)

    # Fold-local impute on FoG + balance blocks
    def _impute(blk_tr, blk_te):
        med = np.nanmedian(blk_tr, axis=0)
        return (
            np.nan_to_num(np.where(np.isnan(blk_tr), med[None, :], blk_tr), nan=0.0),
            np.nan_to_num(np.where(np.isnan(blk_te), med[None, :], blk_te), nan=0.0),
        )
    fog_tr, fog_te = _impute(fog[tr], fog[te])
    bal_tr, bal_te = _impute(bal[tr], bal[te])

    ip_avg = None
    audits = []
    for b in bases:
        ip, audit = _custom_chain_predict(
            Xtr_sel, items_tr_arr, Xte_sel, seed, b, list(item_order),
            fog_tr, fog_te, bal_tr, bal_te,
        )
        ip_avg = ip if ip_avg is None else ip_avg + ip
        audits.append(audit)
    ip_avg /= len(bases)
    t1_sum_idx = [list(item_order).index(i) for i in T1_SUM_ITEMS]
    item_pred = ip_avg[:, t1_sum_idx] + np.array([item_means[i] for i in T1_SUM_ITEMS])
    t1_pred = item_pred.sum(axis=1)
    return te, s1_te + (t1_pred - float(sum(item_means[i] for i in T1_SUM_ITEMS))), audits


def _i34_one_fold(args):
    """iter34 baseline (no slot B routing)."""
    from sklearn.multioutput import RegressorChain
    fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    item_means = {}; items_tr_resid = []
    for i in item_order:
        v = items[i][tr]; mu = float(np.nanmean(v)); item_means[i] = mu
        items_tr_resid.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_resid)
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed)
    ip_avg = None
    for b in bases:
        regr = _make_regr(b, seed)
        chain = RegressorChain(regr, order="random", random_state=seed)
        chain.fit(Xtr_sel, items_tr_arr)
        ip = chain.predict(Xte_sel)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg /= len(bases)
    t1_sum_idx = [list(item_order).index(i) for i in T1_SUM_ITEMS]
    item_pred = ip_avg[:, t1_sum_idx] + np.array([item_means[i] for i in T1_SUM_ITEMS])
    return te, s1_te + (item_pred.sum(axis=1) - float(sum(item_means[i] for i in T1_SUM_ITEMS)))


def _run_cv(seed, splits, X, y_t1, X_s1, items, item_order, bases, fog, bal, n_workers, label):
    n = len(y_t1)
    preds = np.zeros(n)
    audits = []
    jobs = [(fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases, fog, bal)
            for fid, (tr, te) in enumerate(splits)]
    ctx = mp.get_context("spawn")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_fit_one_fold, j): j[0] for j in jobs}
        done = 0
        for fut in as_completed(futs):
            te_idx, te_pred, a = fut.result()
            preds[te_idx] = te_pred
            audits.append({"fold_id": int(futs[fut]), "audit": a})
            done += 1
            print(f"    seed={seed} {label} {done}/{len(splits)}  elapsed={time.time()-t0:.0f}s", flush=True)
    return preds, audits


def _run_cv_iter34(seed, splits, X, y_t1, X_s1, items, item_order, bases, n_workers):
    n = len(y_t1)
    preds = np.zeros(n)
    jobs = [(fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases)
            for fid, (tr, te) in enumerate(splits)]
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


def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": "T1 iter38 — FoG event stats + balance geometry routed POST-K=500 for items 11+13",
        "slot": "B of T1 Glass-Ceiling Push 2026-05-10 (master prereg "
                "results/preregistration_t1_ceiling_push_20260510_134829.json, FWER n=4)",
        "is_post_publication_replication_target": False,
        "cohort": {
            "target": "T1 = sum(items 9-14)",
            "n_subjects_min": 90,
            "filter": "PD with full items 9-14, 15, 18 (matches iter34 cohort)",
            "split_file": "results/paper3_split.json",
        },
        "stage1": {"model": "Ridge", "alpha": STAGE1_ALPHA, "feature_set_name": "A3_tier1",
                   "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"], "stage1_total_features": 9},
        "stage2": {
            "model_ensemble": ["CustomChain(LGB)", "CustomChain(XGB-hist)", "CustomChain(ET)"],
            "ensemble_method": "average chain-output across 3 bases per fold per seed",
            "items_targets_chain": list(ALL_ITEMS),
            "items_summed_for_t1": list(T1_SUM_ITEMS),
            "auxiliary_items": list(AUX_ITEMS),
            "feature_select_k": K_FEATURES,
            "fog_balance_routing": {
                "policy": "per-TARGET-ITEM-IDENTITY routing",
                "item_11_fog": "fog_event_rate + fog_event_duration_mean + fog_event_duration_std appended to chain step where target item id == 11",
                "item_13_balance": "bal_lumbar_pitch_mean + bal_lumbar_pitch_excur + bal_lumbar_roll_mean + bal_xiphoid_pitch_mean + bal_forehead_pitch_mean appended to chain step where target item id == 13",
                "all_other_items": "no slot B features appended",
                "post_K500": True,
                "K500_pool_unchanged": "V2 only; FoG+bal features never enter K=500 ranking",
            },
        },
        "slot_b_cache": {
            "csv": str(CACHE_CSV.relative_to(REPO_ROOT)),
            "n_features_total": 8,
            "label_free": True, "fold_scope_at_extraction": "global",
            "leakage_argument": "FoG events: bandpass envelope thresholding on Lumbar Acc-mag in 3-8 Hz band, no labels. Balance geometry: median pitch/roll on Balance task Euler angles, no labels.",
        },
        "eval": {"loocv_n_min": 90, "seeds": list(SEEDS_DEFAULT), "bases": list(BASE_LEARNERS)},
        "screen_gate": {"n_splits": 5, "promote": "Δ̄≥+0.025 AND frac>0≥0.95"},
        "lockbox_rules": ["ONE pre-registered config. ONE LOOCV run. SLOT B of FWER n=4 family.",
                          "Bonferroni gates: frac>0 ≥ 0.9875 vs iter12-honest-n93 AND vs iter34-n93."],
    }


def _formula_sha256(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def write_preregistration() -> Path:
    payload = _formula_payload()
    sha = _formula_sha256(payload)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts, "iso_datetime_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "T1 iter38 — FoG events + balance geometry chain-step-routed POST-K=500",
        "git_head": _git_head(), "formula_sha256": sha, "formula": payload,
        "variant": "fog_balance_postk500_chainstep_routing",
        "master_prereg_id": "t1_ceiling_push_20260510_134829",
        "master_prereg_path": "results/preregistration_t1_ceiling_push_20260510_134829.json",
        "slot_id": "B",
        "fwer_family_size_n": 4,
    }
    out = RESULTS_DIR / f"preregistration_t1_iter38_fog_balance_postk500_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


def _paired_bootstrap_ccc(y, p_a, p_b, n_boot=5000, seed=42):
    rng = np.random.RandomState(seed); n = len(y)
    deltas = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, n)
        deltas[i] = ccc_fn(y[idx], p_a[idx]) - ccc_fn(y[idx], p_b[idx])
    return {"n_boot": n_boot, "delta_mean": float(deltas.mean()),
            "delta_ci_low": float(np.percentile(deltas, 2.5)),
            "delta_ci_high": float(np.percentile(deltas, 97.5)),
            "frac_above_zero": float((deltas > 0).mean()),
            "frac_above_0.025": float((deltas > 0.025).mean())}


def run_null_gate(seed: int = 42) -> dict:
    """Corrected 80/20 null gate for the Slot-B routed chain."""
    print("\n=== Slot B corrected null gate ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    fog, bal, _, _ = _load_slotb_cache([str(s) for s in sids])
    n = len(sids)
    rng = np.random.RandomState(seed)
    perm = rng.permutation(n)
    cut = int(0.8 * n)
    tr_idx, te_idx = perm[:cut], perm[cut:]
    print(f"  cohort N={n}, train={len(tr_idx)}, test={len(te_idx)}", flush=True)

    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])

    def _impute_block(block_tr, block_te):
        med = np.nanmedian(block_tr, axis=0)
        return (
            np.nan_to_num(np.where(np.isnan(block_tr), med[None, :], block_tr), nan=0.0),
            np.nan_to_num(np.where(np.isnan(block_te), med[None, :], block_te), nan=0.0),
        )

    def _predict(y_train, item_train_values, X_train, X_test, fog_train, fog_test, bal_train, bal_test):
        s1_tr_, s1_te_ = fit_stage1(X_s1[tr_idx], y_train, X_s1[te_idx], alpha=STAGE1_ALPHA)
        item_means: dict[int, float] = {}
        items_tr_resid: list[np.ndarray] = []
        for i in item_order:
            v = item_train_values[i]
            mu = float(np.nanmean(v))
            item_means[i] = mu
            items_tr_resid.append(np.nan_to_num(v - mu, nan=0.0))
        items_tr_arr = np.column_stack(items_tr_resid)
        Xtr_, Xte_ = impute_fold(X_train, X_test)
        Xtr_sel_, Xte_sel_, _ = feature_select_fold(Xtr_, y_train - s1_tr_, Xte_, k=K_FEATURES, seed=seed)
        fog_tr_, fog_te_ = _impute_block(fog_train, fog_test)
        bal_tr_, bal_te_ = _impute_block(bal_train, bal_test)
        ip_avg = None
        for b in BASE_LEARNERS:
            ip, _ = _custom_chain_predict(
                Xtr_sel_, items_tr_arr, Xte_sel_, seed, b, list(item_order),
                fog_tr_, fog_te_, bal_tr_, bal_te_,
            )
            ip_avg = ip if ip_avg is None else ip_avg + ip
        ip_avg /= len(BASE_LEARNERS)
        t1_sum_idx = [list(item_order).index(i) for i in T1_SUM_ITEMS]
        item_pred = ip_avg[:, t1_sum_idx] + np.array([item_means[i] for i in T1_SUM_ITEMS])
        return s1_te_ + item_pred.sum(axis=1) - float(sum(item_means[i] for i in T1_SUM_ITEMS))

    nulls = {}

    true_item_train = {i: items[i][tr_idx] for i in item_order}
    normal_pred = _predict(
        y_t1[tr_idx], true_item_train,
        X[tr_idx], X[te_idx], fog[tr_idx], fog[te_idx], bal[tr_idx], bal[te_idx]
    )

    scramble_order = rng.permutation(len(tr_idx))
    scrambled_item_train = {i: items[i][tr_idx][scramble_order] for i in item_order}
    pred_sc = _predict(
        y_t1[tr_idx][scramble_order], scrambled_item_train,
        X[tr_idx], X[te_idx], fog[tr_idx], fog[te_idx], bal[tr_idx], bal[te_idx]
    )
    nulls["scrambled_label_ccc"] = round(float(ccc_fn(y_t1[te_idx], pred_sc)), 4)

    canary_tr = np.zeros((len(tr_idx), 1))
    canary_te = np.random.RandomState(seed).randn(len(te_idx), 1) * 5.0
    pred_cn = _predict(
        y_t1[tr_idx],
        true_item_train,
        np.hstack([X[tr_idx], canary_tr]),
        np.hstack([X[te_idx], canary_te]),
        fog[tr_idx],
        fog[te_idx],
        bal[tr_idx],
        bal[te_idx],
    )
    canary_delta = pred_cn - normal_pred
    nulls["normal_ccc"] = round(float(ccc_fn(y_t1[te_idx], normal_pred)), 4)
    nulls["canary_feature_ccc"] = round(float(ccc_fn(y_t1[te_idx], pred_cn)), 4)
    nulls["canary_vs_normal_max_abs_delta"] = float(np.max(np.abs(canary_delta)))
    nulls["canary_vs_normal_mean_abs_delta"] = float(np.mean(np.abs(canary_delta)))

    s1_full_tr, s1_full_te = fit_stage1(X_s1, y_t1, X_s1[te_idx], alpha=STAGE1_ALPHA)
    items_full = np.column_stack([
        np.nan_to_num(items[i] - float(np.nanmean(items[i])), nan=0.0) for i in item_order
    ])
    Xtr_full, Xte_full = impute_fold(X, X[te_idx])
    Xtr_full_sel, Xte_full_sel, _ = feature_select_fold(
        Xtr_full, y_t1 - s1_full_tr, Xte_full, k=K_FEATURES, seed=seed
    )
    fog_full, fog_te_full = _impute_block(fog, fog[te_idx])
    bal_full, bal_te_full = _impute_block(bal, bal[te_idx])
    ip_avg = None
    for b in BASE_LEARNERS:
        ip, _ = _custom_chain_predict(
            Xtr_full_sel, items_full, Xte_full_sel, seed, b, list(item_order),
            fog_full, fog_te_full, bal_full, bal_te_full,
        )
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg /= len(BASE_LEARNERS)
    t1_sum_idx = [list(item_order).index(i) for i in T1_SUM_ITEMS]
    item_means_full = {i: float(np.nanmean(items[i])) for i in T1_SUM_ITEMS}
    item_pred = ip_avg[:, t1_sum_idx] + np.array([item_means_full[i] for i in T1_SUM_ITEMS])
    pred_full = s1_full_te + item_pred.sum(axis=1) - float(sum(item_means_full.values()))
    nulls["transductive_sanity_ccc"] = round(float(ccc_fn(y_t1[te_idx], pred_full)), 4)

    nulls["null_seed"] = int(seed)
    nulls["n_train"] = int(len(tr_idx))
    nulls["n_test"] = int(len(te_idx))
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


def smoke_test(seed: int = 42) -> None:
    print("\n=== iter38 slot B SMOKE: 1 fold × 1 seed ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    fog, bal, _, _ = _load_slotb_cache([str(s) for s in sids])
    n = len(sids)
    print(f"  cohort N={n}, FOG valid={(~np.isnan(fog).any(axis=1)).sum()}/{n}, "
          f"BAL valid={(~np.isnan(bal).any(axis=1)).sum()}/{n}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])
    splits = list(LeaveOneOut().split(np.arange(n)))
    fid, (tr, te) = 0, splits[0]
    args = (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, BASE_LEARNERS, fog, bal)
    t0 = time.time()
    te_idx, te_pred, audits = _fit_one_fold(args)
    print(f"  fold 0/{n}: y_true={y_t1[te_idx[0]]:.2f}, y_pred={te_pred[0]:.2f}, "
          f"wall={time.time()-t0:.1f}s", flush=True)
    print(f"  audit: {[s['n_input_cols'] for s in audits[0]['per_step']]}", flush=True)
    assert np.isfinite(te_pred).all()
    print("  SMOKE PASS", flush=True)


def run_screen(seeds=SEEDS_DEFAULT, n_workers: int = 5) -> dict:
    print("\n=== 5-fold × 3 seed SCREEN: slot B vs iter34 ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    fog, bal, _, _ = _load_slotb_cache([str(s) for s in sids])
    print(f"  cohort N={n}, FOG valid={(~np.isnan(fog).any(axis=1)).sum()}/{n}, "
          f"BAL valid={(~np.isnan(bal).any(axis=1)).sum()}/{n}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])
    per_seed = []; pl_oofs = []; i34_oofs = []
    for seed in seeds:
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        splits = list(kf.split(np.arange(n)))
        t0 = time.time()
        pl_pred, _ = _run_cv(seed, splits, X, y_t1, X_s1, items, item_order, BASE_LEARNERS, fog, bal, n_workers, "slotB")
        i34_pred = _run_cv_iter34(seed, splits, X, y_t1, X_s1, items, item_order, BASE_LEARNERS, n_workers)
        c_pl = float(ccc_fn(y_t1, pl_pred)); c_i34 = float(ccc_fn(y_t1, i34_pred))
        per_seed.append({"seed": int(seed), "ccc_slotB": c_pl, "ccc_iter34_5fold": c_i34,
                         "delta": c_pl - c_i34, "wall_s": float(time.time() - t0)})
        pl_oofs.append(pl_pred); i34_oofs.append(i34_pred)
        print(f"  seed={seed}: slot_B={c_pl:.4f}  iter34={c_i34:.4f}  Δ={c_pl-c_i34:+.4f}", flush=True)
    mean_pl = np.mean(np.column_stack(pl_oofs), axis=1)
    mean_i34 = np.mean(np.column_stack(i34_oofs), axis=1)
    delta_mean = float(np.mean([s["delta"] for s in per_seed]))
    delta_std = float(np.std([s["delta"] for s in per_seed], ddof=1))
    boot = _paired_bootstrap_ccc(y_t1, mean_pl, mean_i34)
    pass_screen = (delta_mean >= 0.025) and (boot["frac_above_zero"] >= 0.95)
    summary = {
        "n_subjects": int(n), "seeds": list(seeds), "per_seed": per_seed,
        "delta_mean": delta_mean, "delta_std": delta_std,
        "ccc_slotB_meanof_seedmeans": float(ccc_fn(y_t1, mean_pl)),
        "ccc_iter34_5fold_meanof_seedmeans": float(ccc_fn(y_t1, mean_i34)),
        "bootstrap_paired_delta": boot,
        "screen_gate_pass": bool(pass_screen),
    }
    print(f"\n  SCREEN: Δ̄={delta_mean:+.4f}  std={delta_std:.4f}  frac>0={boot['frac_above_zero']:.3f}  "
          f"→ {'PASS' if pass_screen else 'FAIL'}", flush=True)
    return summary


def run_lockbox(prereg_file: Path, seeds=SEEDS_DEFAULT, n_workers: int = 5) -> Path:
    if not prereg_file.exists():
        raise FileNotFoundError(prereg_file)
    with open(prereg_file) as f:
        prereg = json.load(f)
    expected_sha = _formula_sha256(_formula_payload())
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(f"prereg sha mismatch")
    print(f"\n=== T1 iter38 SLOT B LOCKBOX LOOCV ===", flush=True)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    fog, bal, fog_cols, bal_cols = _load_slotb_cache([str(s) for s in sids])
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])
    splits = list(LeaveOneOut().split(np.arange(n)))
    all_pl = []; per_seed = []
    for seed in seeds:
        t0 = time.time()
        pl_pred, _ = _run_cv(seed, splits, X, y_t1, X_s1, items, item_order, BASE_LEARNERS, fog, bal, n_workers, "slotB-LOOCV")
        c_pl = float(ccc_fn(y_t1, pl_pred))
        per_seed.append({"seed": int(seed), "ccc_slotB": c_pl, "wall_s": float(time.time() - t0)})
        all_pl.append(pl_pred)
        print(f"  seed={seed}: slot_B LOOCV={c_pl:.4f}", flush=True)
    mean_pl = np.mean(np.column_stack(all_pl), axis=1)
    headline = full_metrics(y_t1, mean_pl, label="t1_iter38_slot_B_fog_balance_postk500")

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
            boot_iter34 = _paired_bootstrap_ccc(y_t1, mean_pl, p_i34)
            boot_iter34["ccc_iter34"] = round(float(ccc_fn(y_t1, p_i34)), 4)
            boot_iter34["delta_meanof_predmeans"] = float(headline["ccc"] - boot_iter34["ccc_iter34"])
        except KeyError as e:
            boot_iter34 = {"error": f"SID missing: {e!r}"}

    fwer_supersede = boot_iter34 and "frac_above_zero" in boot_iter34 and boot_iter34["frac_above_zero"] >= 0.9875
    headline.update({"variant": "fog_balance_postk500", "n_subjects": n,
                     "preregistration_file": prereg_file.name, "is_lockbox_headline": True,
                     "master_prereg_id": "t1_ceiling_push_20260510_134829", "slot_id": "B",
                     "fwer_family_size_n": 4, "n_seeds": len(seeds), "per_seed": per_seed,
                     "bootstrap_delta_vs_iter34": boot_iter34,
                     "fwer_bonferroni_supersede_iter34": bool(fwer_supersede),
                     "slot_b_columns": {"fog": fog_cols, "balance": bal_cols},
                     "per_subject": {"sids": [str(s) for s in sids],
                                     "y_true": y_t1.tolist(), "y_pred": mean_pl.tolist()}})
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_iter38_slotB_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t1_iter38_slotB_{ts}.oof.npy"
    np.save(out_npy, mean_pl)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)
    print(f"\n=== HEADLINE: CCC={headline['ccc']:.4f}  MAE={headline['mae']:.3f} ===", flush=True)
    if boot_iter34 and "frac_above_zero" in boot_iter34:
        print(f"  vs iter34: Δ̄={boot_iter34['delta_mean']:+.4f}  frac>0={boot_iter34['frac_above_zero']:.3f}  "
              f"FWER-supersede(0.9875)={fwer_supersede}", flush=True)
    return out_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("smoke", "write_prereg", "null_only", "screen", "lockbox"), default="smoke")
    p.add_argument("--prereg", help="prereg path (lockbox)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n_workers", type=int, default=5)
    args = p.parse_args()
    if args.mode == "smoke": smoke_test(seed=args.seed)
    elif args.mode == "write_prereg": write_preregistration()
    elif args.mode == "null_only":
        nulls = run_null_gate(seed=args.seed)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = RESULTS_DIR / f"t1_iter38_slotB_nulls_{ts}.json"
        with open(out, "w") as f:
            json.dump(nulls, f, indent=2)
        print(f"\nNULLS saved: {out}", flush=True)
    elif args.mode == "screen":
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = RESULTS_DIR / f"screen_t1_iter38_slotB_{ts}.json"
        nulls = run_null_gate(seed=args.seed)
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
    elif args.mode == "lockbox":
        if not args.prereg: raise SystemExit("--prereg required")
        run_lockbox(Path(args.prereg), n_workers=args.n_workers)


if __name__ == "__main__":
    main()
