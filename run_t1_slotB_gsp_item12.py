"""T1 Glass-Ceiling Push 2026-05-13, Slot B — V3-GSP feature substitution at item-12 chain step.

Mechanism: custom 8-item RegressorChain where:
  - Item 12 chain step uses V3-GSP features (no K=500 selection, ~110 features)
  - Other items (9, 10, 11, 13, 14, 15, 18) use V2 K=500 LGB-importance (iter34 standard)
  - Chain order CCC-descending: [12, 10, 14, 9, 11, 13, 15, 18]
  - Item 12 first → no upstream chain residuals as inputs
  - Downstream items condition on item-12's V3-GSP-derived prediction

Mechanism is orthogonal to:
  - V2+V3 K=500 hybrid wall (Δ=-0.016) — we don't mix in K-best
  - V2+V3 4-source nested CV (Δ=-0.005 catastrophic) — we don't stack 4 sources
  - F19/F36-D/F44/F45/F48/F51 K=500 absorption — V3-GSP bypasses K=500 at item-12
  - Per-item composite F53 — we still train a joint chain, not OOF sum

Pre-registration: results/preregistration_t1_ceiling_push_20260513_043852.json (Slot B)

Modes:
  --mode write_prereg
  --mode smoke
  --mode screen_5fold
  --mode lockbox
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
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold
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

T1_SUM_ITEMS: tuple[int, ...] = tuple(T1_ITEMS)  # items 9-14
AUX_ITEMS: tuple[int, ...] = (15, 18)
CHAIN_ORDER: tuple[int, ...] = (12, 10, 14, 9, 11, 13, 15, 18)  # CCC-descending, all 8 items

BASE_LEARNERS: tuple[str, ...] = ("lgb", "xgb", "et")

V3_GSP_CSV = RESULTS_DIR / "v3_gsp_features.csv"


def _load_gsp_aligned(sids: list[str]) -> tuple[np.ndarray, list[str]]:
    """Load V3-GSP features aligned to cohort SIDs. Returns (X_gsp, feat_names)."""
    df = pd.read_csv(V3_GSP_CSV)
    df["sid"] = df["sid"].astype(str)
    df_idx = df.set_index("sid")
    feat_cols = [c for c in df.columns if c != "sid"]
    X = np.full((len(sids), len(feat_cols)), np.nan)
    for i, s in enumerate(sids):
        sid_s = str(s)
        if sid_s in df_idx.index:
            X[i] = df_idx.loc[sid_s, feat_cols].to_numpy()
    return X, feat_cols


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
    Xtr_v2sel: np.ndarray,
    Xte_v2sel: np.ndarray,
    Xtr_gsp: np.ndarray,
    Xte_gsp: np.ndarray,
    items_tr_residual: np.ndarray,
    seed: int,
    base: str,
):
    """Custom 8-item chain. Item 12 step uses V3-GSP features ONLY; other steps use V2 K=500.

    Chain order (FIXED CCC-descending): [12, 10, 14, 9, 11, 13, 15, 18]
    Returns pred_test (n_test, n_items) in CHAIN_ORDER column ordering.
    """
    n_train, n_test = Xtr_v2sel.shape[0], Xte_v2sel.shape[0]
    n_items = len(CHAIN_ORDER)
    pred_test = np.zeros((n_test, n_items))

    for chain_step, item_id in enumerate(CHAIN_ORDER):
        if item_id == 12:
            # V3-GSP features ONLY (no V2, no K=500 selection)
            feats_tr = [Xtr_gsp]
            feats_te = [Xte_gsp]
        else:
            # V2 K=500 (iter34 standard)
            feats_tr = [Xtr_v2sel]
            feats_te = [Xte_v2sel]
        # Add chain residuals from prior steps
        if chain_step > 0:
            feats_tr.append(items_tr_residual[:, :chain_step])
            feats_te.append(pred_test[:, :chain_step])
        Xtr_aug = np.concatenate(feats_tr, axis=1)
        Xte_aug = np.concatenate(feats_te, axis=1)
        regr = _make_regr(base, seed)
        regr.fit(Xtr_aug, items_tr_residual[:, chain_step])
        pred_test[:, chain_step] = regr.predict(Xte_aug)
    return pred_test


def _impute_gsp_fold(Xtr, Xte):
    """Fold-local median imputation for V3-GSP features."""
    med = np.nanmedian(Xtr, axis=0)
    Xtr_imp = np.where(np.isnan(Xtr), med[None, :], Xtr)
    Xte_imp = np.where(np.isnan(Xte), med[None, :], Xte)
    Xtr_imp = np.nan_to_num(Xtr_imp, nan=0.0)
    Xte_imp = np.nan_to_num(Xte_imp, nan=0.0)
    return Xtr_imp, Xte_imp


def _fit_one_fold(args):
    fold_id, tr, te, X_v2, y_t1, X_s1, items, X_gsp, seed, bases = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    # Build items residuals in CHAIN_ORDER column ordering
    item_means: dict[int, float] = {}
    items_tr_cols: list[np.ndarray] = []
    for i in CHAIN_ORDER:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_cols.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_cols)

    # V2 imputation + K=500
    Xtr, Xte = impute_fold(X_v2[tr], X_v2[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
    )
    # V3-GSP imputation (fold-local)
    Xtr_gsp, Xte_gsp = _impute_gsp_fold(X_gsp[tr], X_gsp[te])

    # Average chain over 3 bases
    ip_avg = None
    for b in bases:
        ip = _custom_chain_predict(
            Xtr_sel, Xte_sel, Xtr_gsp, Xte_gsp, items_tr_arr, seed, b
        )
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg = ip_avg / len(bases)

    # T1 reconstruction: sum predictions for items 9-14 (all in CHAIN_ORDER positions 0-5)
    t1_idx_in_chain = [CHAIN_ORDER.index(i) for i in T1_SUM_ITEMS]
    item_pred_t1 = ip_avg[:, t1_idx_in_chain] + np.array(
        [item_means[i] for i in T1_SUM_ITEMS]
    )
    t1_pred_from_items = item_pred_t1.sum(axis=1)
    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))
    return te, s1_te + (t1_pred_from_items - sum_means_t1)


def _slotB_kfold(seed, X_v2, y_t1, X_s1, items, X_gsp, n_workers, n_splits=5):
    n = len(y_t1)
    preds = np.zeros(n)
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    jobs = [
        (fid, tr, te, X_v2, y_t1, X_s1, items, X_gsp, seed, BASE_LEARNERS)
        for fid, (tr, te) in enumerate(kf.split(np.arange(n)))
    ]
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_fit_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    print(f"    seed={seed} 5fold wall={time.time()-t0:.0f}s", flush=True)
    return preds


def _slotB_loocv(seed, X_v2, y_t1, X_s1, items, X_gsp, n_workers):
    n = len(y_t1)
    preds = np.zeros(n)
    jobs = [
        (fid, tr, te, X_v2, y_t1, X_s1, items, X_gsp, seed, BASE_LEARNERS)
        for fid, (tr, te) in enumerate(LeaveOneOut().split(np.arange(n)))
    ]
    t0 = time.time()
    done = 0
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_fit_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
            done += 1
            if done % 15 == 0 or done == n:
                print(f"    seed={seed} {done}/{n} folds wall={time.time()-t0:.0f}s", flush=True)
    return preds


def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": "T1 Glass-Ceiling Push 2026-05-13 Slot B — V3-GSP at item-12 chain step + CCC-descending order",
        "tri_cli_consult": "codex+gemini Slot A consult informed mechanism; CCC-descending order adopted; Slot B-specific consult pending",
        "is_t1_ceiling_push_2026-05-13_slotB": True,
        "master_prereg": "results/preregistration_t1_ceiling_push_20260513_043852.json",
        "fwer_family_size": 4,
        "fwer_per_slot_gate_frac_gt0": 0.9875,
        "cohort": {
            "target": "T1 = sum(items 9-14)",
            "n_subjects_min": 90,
            "filter": "PD with items 9-14, 15, 18 + V3-GSP feature coverage (N=92)",
        },
        "stage1": {
            "model": "Ridge", "alpha": STAGE1_ALPHA,
            "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
        },
        "stage2": {
            "chain_order": list(CHAIN_ORDER),
            "chain_order_policy": "FIXED CCC-descending; item 12 step first → no upstream chain features",
            "per_step_feature_routing": {
                "item_12": "V3-GSP features ONLY (550 cols, no K=500 selection, fold-local median impute)",
                "items_9_10_11_13_14_15_18": "V2 K=500 LGB-importance against T1 residual (iter34 standard)",
            },
            "feature_select_k_v2": K_FEATURES,
            "v3_gsp_cache": str(V3_GSP_CSV.relative_to(REPO_ROOT)),
            "v3_gsp_manifest": "results/v3_gsp_features.csv.manifest.json",
            "model_ensemble": [
                "LGBMRegressor(n=500, lr=0.05, num_leaves=15, min_data=10)",
                "XGBRegressor(hist, n=500, lr=0.05, depth=4, min_child=5)",
                "ExtraTreesRegressor(n=300, max_depth=10, min_leaf=5)",
            ],
            "ensemble_method": "average chain-output across 3 bases per fold per seed",
            "items_summed_for_t1": list(T1_SUM_ITEMS),
        },
        "eval": {
            "screen_n_splits": 5,
            "screen_seeds": list(SEEDS_DEFAULT),
            "loocv_seeds": list(SEEDS_DEFAULT),
            "screen_gate": "5-fold Δ̄ vs iter34-5-fold (same KFold seeds) ≥ +0.020 AND seed std < 0.020",
            "loocv_gate": "paired bootstrap frac>0 ≥ 0.9875 vs iter34 LOOCV on N=92 AND vs iter12-honest on N=92",
            "comparator_iter34_loocv_oof": "results/lockbox_t1_iter34_hybrid_20260510_233019.oof.npy",
            "comparator_iter34_5fold_oof": "results/iter34_5fold_comparator_<latest>.oof.npy",
        },
        "leakage_assertions": [
            "Stage-1 Ridge fit fold-local",
            "feature_select_fold + impute_fold operate on outer-train only",
            "V3-GSP imputation: fold-local median, train-fold only",
            "no global imputers, no cohort-wide z-scoring, no global ranks",
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
    out = RESULTS_DIR / f"preregistration_t1_slotB_gsp_item12_{ts}.json"
    with open(out, "w") as f:
        json.dump({
            "timestamp_utc": ts,
            "iso_datetime_utc": datetime.now(timezone.utc).isoformat(),
            "name": "T1 Glass-Ceiling Push 2026-05-13 Slot B pre-registration",
            "formula_sha256": sha,
            "formula_payload": payload,
            "git_sha": _git_head(),
        }, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


def _paired_bootstrap_ccc(y, p_a, p_b, n_boot=5000, seed=42):
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


def smoke_test(seed=42, feature_set="A3_tier1"):
    print("\n=== Slot B SMOKE TEST: 1 fold × 1 seed ===", flush=True)
    sids, X_v2, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    n = len(sids)
    print(f"  cohort N={n}, chain_order={list(CHAIN_ORDER)}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    X_gsp, gsp_feats = _load_gsp_aligned([str(s) for s in sids])
    print(f"  V3-GSP feature count = {X_gsp.shape[1]}, non-nan rows = {(~np.isnan(X_gsp).all(axis=1)).sum()}/{n}", flush=True)
    splits = list(LeaveOneOut().split(np.arange(n)))
    fid, (tr, te) = 0, splits[0]
    args = (fid, tr, te, X_v2, y_t1, X_s1, items, X_gsp, seed, BASE_LEARNERS)
    t0 = time.time()
    te_idx, te_pred = _fit_one_fold(args)
    print(f"  fold 0/{n}: te_idx={te_idx[0]}, sid={sids[te_idx[0]]}, "
          f"y_true={y_t1[te_idx[0]]:.2f}, y_pred={te_pred[0]:.2f}, "
          f"wall={time.time()-t0:.1f}s", flush=True)
    assert np.isfinite(te_pred).all(), "non-finite predictions"
    print("  SMOKE PASS", flush=True)


def run_screen_5fold(seeds=SEEDS_DEFAULT, feature_set="A3_tier1", n_workers=2):
    print(f"\n=== Slot B 5-FOLD SCREEN ({len(seeds)} seeds, workers={n_workers}) ===", flush=True)
    sids, X_v2, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    n = len(sids)
    print(f"  cohort N={n}, chain_order={list(CHAIN_ORDER)}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    X_gsp, _ = _load_gsp_aligned([str(s) for s in sids])

    # Load iter34 5-fold comparator (apples-to-apples)
    comparators = sorted(RESULTS_DIR.glob("iter34_5fold_comparator_*.json"))
    if not comparators:
        print("  WARNING: no iter34_5fold_comparator_*.json found; using LOOCV (BIASED)")
        iter34_oof = np.load(RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy")
        with open(RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.json") as f:
            iter34_meta = json.load(f)
        iter34_sids = [str(s) for s in iter34_meta["per_subject"]["sids"]]
        sid_to_pred = dict(zip(iter34_sids, iter34_oof.tolist()))
        iter34_5fold = np.array([sid_to_pred[str(s)] for s in sids])
        comparator_label = "iter34_LOOCV_biased"
    else:
        comp_json = json.loads(comparators[-1].read_text())
        sids_c = [str(s) for s in comp_json["per_subject"]["sids"]]
        sid_to_pred = dict(zip(sids_c, comp_json["per_subject"]["y_pred_pooled"]))
        iter34_5fold = np.array([sid_to_pred[str(s)] for s in sids])
        comparator_label = f"iter34_5fold_{comparators[-1].stem.split('_')[-1]}"
    print(f"  comparator: {comparator_label}, CCC={ccc_fn(y_t1, iter34_5fold):.4f}", flush=True)

    per_seed = []
    seed_preds = []
    for seed in seeds:
        t0 = time.time()
        p = _slotB_kfold(seed, X_v2, y_t1, X_s1, items, X_gsp, n_workers)
        c_slotB = float(ccc_fn(y_t1, p))
        c_iter34 = float(ccc_fn(y_t1, iter34_5fold))
        delta = c_slotB - c_iter34
        per_seed.append({"seed": seed, "ccc_slotB_5fold": round(c_slotB, 4),
                         "ccc_iter34_comparator": round(c_iter34, 4),
                         "delta": round(delta, 4),
                         "wall_sec": round(time.time() - t0, 1)})
        print(f"  seed={seed}: slotB_5fold={c_slotB:.4f} | {comparator_label}={c_iter34:.4f} | "
              f"Δ={delta:+.4f} | wall={time.time()-t0:.0f}s", flush=True)
        seed_preds.append(p)

    deltas = [p["delta"] for p in per_seed]
    mean_delta = float(np.mean(deltas))
    std_delta = float(np.std(deltas))
    screen_pass = bool(mean_delta >= 0.020 and std_delta < 0.020)
    verdict = "PROMOTE_TO_LOOCV" if screen_pass else "CLOSE_SLOT_SCREEN_FAIL"
    pooled = np.mean(np.column_stack(seed_preds), axis=1)
    pooled_ccc = float(ccc_fn(y_t1, pooled))
    pooled_delta = pooled_ccc - float(ccc_fn(y_t1, iter34_5fold))

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"screen_t1_slotB_gsp_item12_{ts}.json"
    with open(out, "w") as f:
        json.dump({
            "name": "T1 Slot B 5-fold screen (V3-GSP at item-12 + CCC-descending order)",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "cohort_N": int(n),
            "chain_order": list(CHAIN_ORDER),
            "comparator_label": comparator_label,
            "per_seed": per_seed,
            "mean_delta": round(mean_delta, 4),
            "std_delta": round(std_delta, 4),
            "pooled_ccc_slotB": round(pooled_ccc, 4),
            "pooled_delta_vs_iter34": round(pooled_delta, 4),
            "screen_gate": "Δ̄ ≥ +0.020 AND std < 0.020",
            "screen_pass": screen_pass,
            "verdict": verdict,
        }, f, indent=2)
    print(f"\n  5-fold result: mean_delta={mean_delta:+.4f}, std={std_delta:.4f}, pooled CCC={pooled_ccc:.4f}")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out}")
    return out


def run_lockbox(prereg_file: Path, seeds=SEEDS_DEFAULT, feature_set="A3_tier1", n_workers=2):
    if not prereg_file.exists():
        raise FileNotFoundError(prereg_file)
    with open(prereg_file) as f:
        prereg = json.load(f)
    expected_sha = _formula_sha256(_formula_payload())
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(f"prereg sha {prereg.get('formula_sha256')!r} != {expected_sha!r}")
    print(f"\n=== Slot B LOCKBOX LOOCV ({len(seeds)} seeds) ===", flush=True)
    sids, X_v2, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    X_gsp, _ = _load_gsp_aligned([str(s) for s in sids])

    iter34_oof = np.load(RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy")
    with open(RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.json") as f:
        iter34_meta = json.load(f)
    iter34_sids = [str(s) for s in iter34_meta["per_subject"]["sids"]]
    sid_to_pred = dict(zip(iter34_sids, iter34_oof.tolist()))
    iter34_loocv = np.array([sid_to_pred[str(s)] for s in sids])

    all_preds = []
    per_seed = []
    overall_t0 = time.time()
    for seed in seeds:
        t0 = time.time()
        p = _slotB_loocv(seed, X_v2, y_t1, X_s1, items, X_gsp, n_workers)
        c = float(ccc_fn(y_t1, p))
        per_seed.append({"seed": seed, "ccc": c, "wall": round(time.time() - t0, 1)})
        print(f"  seed={seed}: CCC={c:.4f}", flush=True)
        all_preds.append(p)
    pooled = np.mean(np.column_stack(all_preds), axis=1)
    headline = full_metrics(y_t1, pooled, label="t1_slotB_gsp_item12")
    boot_iter34 = _paired_bootstrap_ccc(y_t1, pooled, iter34_loocv)
    boot_iter34["ccc_iter34"] = round(float(ccc_fn(y_t1, iter34_loocv)), 4)
    boot_iter34["delta_vs_iter34"] = float(headline["ccc"] - boot_iter34["ccc_iter34"])
    verdict = ("PASS_BONFERRONI_n=4" if boot_iter34["frac_above_zero"] >= 0.9875
               else "FAIL_FWER")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_slotB_gsp_item12_{ts}.json"
    out_oof = RESULTS_DIR / f"lockbox_t1_slotB_gsp_item12_{ts}.oof.npy"
    np.save(out_oof, pooled)
    with open(out_json, "w") as f:
        json.dump({
            "name": "T1 Slot B lockbox (V3-GSP at item-12 chain step + CCC-descending)",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "prereg_path": str(prereg_file),
            "formula_sha256": expected_sha,
            "cohort_N": int(n),
            "chain_order": list(CHAIN_ORDER),
            "per_seed": per_seed,
            "headline": headline,
            "bootstrap_vs_iter34": boot_iter34,
            "verdict": verdict,
            "per_subject": {
                "sids": [str(s) for s in sids],
                "y_true": y_t1.tolist(),
                "y_pred_pooled": pooled.tolist(),
            },
        }, f, indent=2)
    print(f"\n  HEADLINE CCC = {headline['ccc']:.4f} (Δ vs iter34 = {boot_iter34['delta_vs_iter34']:+.4f})")
    print(f"  Bootstrap frac>0 vs iter34 = {boot_iter34['frac_above_zero']:.4f}")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out_json}")
    return out_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["write_prereg", "smoke", "screen_5fold", "lockbox"], default="smoke")
    p.add_argument("--prereg", type=Path, default=None)
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
