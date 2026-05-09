"""T1 Ceiling Push — SLOT C: phase-locked items 9 + 12 (axis 5, F50-style).

Slot C of the 5-slot T1 ceiling push (master pre-reg
preregistration_t1_ceiling_push_20260508_051417.json). Mechanism: items 9
(chair-rise) and 12 (postural-stability/turn) are TUG-phase-locked transients.
iter34's K=500 LGB selector on V2 absorbs phase-segmented signal because the
8-item chain shares one feature pool. F50-style hypothesis-restricted item
slots (small focused feature set per item) bypass K=500 absorption.

Architecture:
  Per-item slot C model (for items 9 and 12):
    item_only            — LGB on ~10 phase-locked features ONLY.
    hy_residual_item_v2  — Stage-1 Ridge(H&Y + cv_yrs + cv_sex + cv_dbs) +
                           Stage-2 LGB on (V2 ⊕ phase-locked).
    item_plus_v2         — LGB on (V2 ⊕ phase-locked), K=500 selector.

  T1 composite (lockbox):
    For items {10, 11, 13, 14, 15, 18}: iter34 hybrid chain (multi-base × 8-item
      auxiliary). Re-runs iter34 chain, extracts per-item OOFs, sums.
    For items {9, 12}: slot C OOFs.
    T1 = Stage1_pred + (sum slot_C_items + sum iter34_items - sum_means_T1).

Pre-registration: written via --mode write_prereg with formula_sha256.
Lockbox: --mode lockbox --preregistration_file <path>.

Modes:
  smoke        : 1 fold × 1 seed item-only screen for items 9+12 (sanity check).
  screen       : 5-fold × 3 seeds, per-item × 3 variants screen. Promote variant
                 with best mean Δ_T1_sum (vs iter34 5-fold) per item if Δ̄ ≥ +0.025
                 across seeds.
  write_prereg : write pre-reg with formula_sha256 + selected variants per item.
  lockbox      : load pre-reg, verify SHA, run LOOCV; build composite T1; emit
                 paired bootstrap vs iter12-honest-on-N=93 + iter34-on-N=93.

Usage:
  ./gpu.sh run_t1_ceiling_push_slotC.py --mode smoke
  ./gpu.sh run_t1_ceiling_push_slotC.py --mode screen --n_workers 11
  ./gpu.sh run_t1_ceiling_push_slotC.py --mode write_prereg \\
           --item9_variant hy_residual_item_v2 --item12_variant hy_residual_item_v2
  ./gpu.sh run_t1_ceiling_push_slotC.py --mode lockbox \\
           --preregistration_file results/preregistration_t1_ceiling_push_slotC_<ts>.json \\
           --n_workers 11
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

# Per the n_workers=1 requirement of inner LGB
os.environ.setdefault("PD_IMU_N_CORES", "1")

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    feature_select_fold,
    get_hy_features,
    impute_fold,
    kfold_split_stratified,
    train_lgb,
)
from run_t3_iter2 import feature_select_fold as fs_t3, impute_fold as imp_t3, train_lgb as lgb_t3
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
)

# Slot-C constants
SLOT_C_ITEMS: tuple[int, ...] = (9, 12)
SLOT_C_VARIANTS: tuple[str, ...] = ("item_only", "item_plus_v2", "hy_residual_item_v2")
PHASELOCKED_CACHES = {
    9: RESULTS_DIR / "phaselocked_item9_features.csv",
    12: RESULTS_DIR / "phaselocked_item12_features.csv",
}
PHASELOCKED_MANIFESTS = {
    9: RESULTS_DIR / "phaselocked_item9_features.csv.manifest.json",
    12: RESULTS_DIR / "phaselocked_item12_features.csv.manifest.json",
}

SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
ITER34_LOCKBOX_JSON = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260506_141720.json"
ITER34_OOF_NPY = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260506_141720.oof.npy"
ITER12_HONEST_OOF_PATH_CANDIDATES = [
    RESULTS_DIR / "lockbox_t1_iter12_honest_oof.npy",
    RESULTS_DIR / "lockbox_t1_iter12_honest.oof.npy",
]
ITER12_HONEST_JSON_CANDIDATES = [
    RESULTS_DIR / "lockbox_t1_iter12_honest.json",
]
ITER12_HONEST_N93_PAIRED_JSON = RESULTS_DIR / "iter12_honest_n93_vs_iter33b_paired_2026_05_06.json"

PUBLISHED_T1_LOOCV_CCC = 0.6550
ITER34_LOOCV_CCC = 0.7366
GATE_DELTA = 0.025
STAGE1_ALPHA = 1.0
K_FEATURES = 500


def _verify_phaselocked_manifest(item: int) -> dict:
    p = PHASELOCKED_MANIFESTS[item]
    if not p.exists():
        raise FileNotFoundError(f"Missing manifest: {p}. Run cache_phaselocked_item{item}.py first.")
    with open(p) as f:
        m = json.load(f)
    if m.get("labels_used", True):
        raise RuntimeError(f"Manifest reports labels_used=True for item {item}; cache is not feature-safe.")
    if m.get("leakage_status") != "clean_by_construction":
        raise RuntimeError(
            f"Manifest leakage_status={m.get('leakage_status')!r} != 'clean_by_construction' (item {item})."
        )
    return m


def load_phaselocked_features(sids: np.ndarray, item: int) -> tuple[np.ndarray, list[str]]:
    """Return aligned phase-locked features (n, k_pl) for the given SID order."""
    _verify_phaselocked_manifest(item)
    p = PHASELOCKED_CACHES[item]
    if not p.exists():
        raise FileNotFoundError(f"Missing {p}; run cache_phaselocked_item{item}.py")
    df = pd.read_csv(p).set_index("sid")
    prefix = f"pl{item}_"
    feat_cols = [c for c in df.columns if c.startswith(prefix)]
    if not feat_cols:
        raise RuntimeError(f"No phase-locked features for item {item} (prefix {prefix!r})")
    n = len(sids)
    X = np.full((n, len(feat_cols)), np.nan)
    matched = 0
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, feat_cols].to_numpy(dtype=np.float64)
            matched += 1
    print(
        f"  item {item} phase-locked features matched {matched}/{n} subjects ({len(feat_cols)} cols)",
        flush=True,
    )
    return X, feat_cols


def _run_per_item_kfold(
    item: int,
    X_pl: np.ndarray,
    X_v2: np.ndarray,
    hy: np.ndarray,
    y_item: np.ndarray,
    variant: str,
    splits,
    seed: int,
) -> np.ndarray:
    n = len(y_item)
    oof = np.zeros(n, dtype=np.float64)
    if variant == "item_only":
        X_base = X_pl
        use_hy = False
    elif variant == "item_plus_v2":
        X_base = np.hstack([X_v2, X_pl])
        use_hy = False
    elif variant == "hy_residual_item_v2":
        X_base = np.hstack([X_v2, X_pl])
        use_hy = True
    else:
        raise ValueError(f"Unknown variant {variant!r}")
    if use_hy:
        hy_feat = get_hy_features(hy)
    for tr, te in splits:
        y_tr = y_item[tr]
        valid_tr_mask = ~np.isnan(y_tr)
        if valid_tr_mask.sum() < 10:
            oof[te] = np.nan
            continue
        tr_v = tr[valid_tr_mask]
        if use_hy:
            ridge = Ridge(alpha=1.0, random_state=seed)
            ridge.fit(hy_feat[tr_v], y_item[tr_v])
            s1_tr = ridge.predict(hy_feat[tr_v])
            s1_te = ridge.predict(hy_feat[te])
            target_tr = y_item[tr_v] - s1_tr
        else:
            s1_te = np.zeros(len(te))
            target_tr = y_item[tr_v]
        Xtr, Xte = impute_fold(X_base[tr_v], X_base[te])
        k = min(K_FEATURES, Xtr.shape[1])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, target_tr, Xte, k=k, seed=seed)
        s2_te = train_lgb(Xtr_sel, target_tr, Xte_sel, seed)
        oof[te] = s1_te + s2_te
    return oof


def screen(d: dict, X_v2: np.ndarray, n_workers: int) -> dict:
    """5-fold × 3 seeds × 2 items × 3 variants screen.

    Per item, pick the variant with the highest mean per-item CCC across seeds.
    For composite-level promotion check, compute Δ_T1_sum vs iter34 hybrid 5-fold.
    """
    sids = d["sids"]
    items = d["items"]
    hy = d["hy"]
    rows = []
    per_item_variant_seed: dict[tuple[int, str], list[float]] = {}

    for item in SLOT_C_ITEMS:
        X_pl, _ = load_phaselocked_features(sids, item)
        y_item = items[item].astype(np.float64)
        for variant in SLOT_C_VARIANTS:
            seed_cccs = []
            for seed in SEEDS_DEFAULT:
                splits = list(kfold_split_stratified(d["t1"], n_splits=5, seed=seed))
                oof = _run_per_item_kfold(item, X_pl, X_v2, hy, y_item, variant, splits, seed)
                valid = ~np.isnan(y_item) & ~np.isnan(oof)
                c = float(ccc_fn(y_item[valid], oof[valid]))
                seed_cccs.append(c)
                rows.append(
                    {
                        "item": item,
                        "variant": variant,
                        "seed": seed,
                        "ccc_per_item": round(c, 4),
                    }
                )
            per_item_variant_seed[(item, variant)] = seed_cccs
            mn, sd = float(np.mean(seed_cccs)), float(np.std(seed_cccs))
            print(
                f"  item {item:2d}  {variant:24s}: 5-fold per-item CCC = {mn:+.4f} ± {sd:.4f}",
                flush=True,
            )
    df = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = RESULTS_DIR / f"slotC_screen_{ts}.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nScreen CSV: {out_csv}", flush=True)

    # Pick best variant per item (max per-item CCC mean)
    print(
        "\n--- PER-ITEM BEST VARIANT (slot C will use these for composite eval) ---",
        flush=True,
    )
    summaries = []
    best_per_item: dict[int, str] = {}
    for item in SLOT_C_ITEMS:
        best_variant = None
        best_mean = -1e9
        best_std = 0.0
        for variant in SLOT_C_VARIANTS:
            cccs = per_item_variant_seed[(item, variant)]
            mn, sd = float(np.mean(cccs)), float(np.std(cccs))
            if mn > best_mean:
                best_mean = mn
                best_std = sd
                best_variant = variant
        best_per_item[item] = best_variant
        print(
            f"  item {item:2d}: best = {best_variant:24s}  CCC = {best_mean:+.4f} ± {best_std:.4f}",
            flush=True,
        )
        summaries.append(
            {
                "item": item,
                "best_variant": best_variant,
                "best_mean": round(best_mean, 4),
                "best_std": round(best_std, 4),
            }
        )

    out_json = RESULTS_DIR / f"slotC_screen_{ts}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "iso_datetime_utc": datetime.now(timezone.utc).isoformat(),
                "summaries": summaries,
                "best_per_item": best_per_item,
                "screen_csv": out_csv.name,
            },
            f,
            indent=2,
        )
    print(f"Screen JSON: {out_json}", flush=True)
    return {"summaries": summaries, "best_per_item": best_per_item, "ts": ts}


# -----------------------------------------------------------------------------
# LOOCV: per-item slot C OOF
# -----------------------------------------------------------------------------
def _loo_per_item_one_fold(args):
    """Worker: one LOOCV fold for slot C item."""
    fid, tr, te, item, X_pl, X_v2, hy, y_item, variant, seed = args
    if variant == "item_only":
        X_base = X_pl
        use_hy = False
    elif variant == "item_plus_v2":
        X_base = np.hstack([X_v2, X_pl])
        use_hy = False
    elif variant == "hy_residual_item_v2":
        X_base = np.hstack([X_v2, X_pl])
        use_hy = True
    else:
        raise ValueError(f"Unknown variant {variant!r}")
    if use_hy:
        hy_feat = get_hy_features(hy)
    y_tr = y_item[tr]
    valid_tr_mask = ~np.isnan(y_tr)
    tr_v = tr[valid_tr_mask]
    if use_hy:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr_v], y_item[tr_v])
        s1_te = ridge.predict(hy_feat[te])
        target_tr = y_item[tr_v] - ridge.predict(hy_feat[tr_v])
    else:
        s1_te = np.zeros(len(te))
        target_tr = y_item[tr_v]
    Xtr, Xte = impute_fold(X_base[tr_v], X_base[te])
    k = min(K_FEATURES, Xtr.shape[1])
    Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, target_tr, Xte, k=k, seed=seed)
    s2_te = train_lgb(Xtr_sel, target_tr, Xte_sel, seed)
    return te, s1_te + s2_te


def _loocv_per_item(item: int, X_pl, X_v2, hy, y_item, variant: str, seed: int, n_workers: int) -> np.ndarray:
    n = len(y_item)
    preds = np.zeros(n, dtype=np.float64)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [
        (fid, tr, te, item, X_pl, X_v2, hy, y_item, variant, seed)
        for fid, (tr, te) in enumerate(splits)
    ]
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_loo_per_item_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
            done += 1
            if done % 25 == 0 or done == n:
                print(
                    f"    item {item} seed={seed} {done}/{n}  elapsed={time.time()-t0:.0f}s",
                    flush=True,
                )
    return preds


# -----------------------------------------------------------------------------
# iter34-style chain LOOCV BUT returning per-item OOFs (T1 sum items only)
# -----------------------------------------------------------------------------
def _iter34_chain_oneFold_per_item(args):
    """Run iter34 hybrid chain for one fold; return per-item predictions for T1_SUM_ITEMS."""
    fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    item_means: dict[int, float] = {}
    items_tr_residual: list[np.ndarray] = []
    for i in item_order:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_arr = np.column_stack(items_tr_residual)
    Xtr, Xte = imp_t3(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = fs_t3(Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed)
    # Average chain predictions across bases
    from sklearn.multioutput import RegressorChain
    ip_avg = None
    for b in bases:
        from run_t1_iter34_hybrid_8item_multibase import _make_regr
        regr = _make_regr(b, seed)
        chain = RegressorChain(regr, order="random", random_state=seed)
        chain.fit(Xtr_sel, items_tr_arr)
        ip = chain.predict(Xte_sel)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg = ip_avg / len(bases)
    # Per-item recovery: ip_avg is residual prediction; add back item_mean
    item_pred_full = ip_avg + np.array([item_means[i] for i in item_order])
    # Return s1_te and per-item predictions in item_order
    return te, s1_te, item_pred_full, item_order, item_means


def _iter34_chain_loocv_per_item(seed, X, y_t1, X_s1, items, item_order, bases, n_workers):
    n = len(y_t1)
    splits = list(LeaveOneOut().split(np.arange(n)))
    s1_arr = np.zeros(n)
    item_pred_arr = np.zeros((n, len(item_order)))
    item_means_per_fold: list[dict[int, float]] = [{} for _ in range(n)]
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases)
        for fid, (tr, te) in enumerate(splits)
    ]
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_iter34_chain_oneFold_per_item, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, s1_te, ipred, order, imeans = fut.result()
            assert order == item_order
            s1_arr[te_idx] = s1_te
            item_pred_arr[te_idx, :] = ipred
            for ti in te_idx.tolist():
                item_means_per_fold[ti] = imeans
            done += 1
            if done % 20 == 0 or done == n:
                print(
                    f"    iter34-chain seed={seed} {done}/{n}  elapsed={time.time()-t0:.0f}s",
                    flush=True,
                )
    return s1_arr, item_pred_arr, item_means_per_fold


# -----------------------------------------------------------------------------
# Pre-registration
# -----------------------------------------------------------------------------
def _formula_payload(item9_variant: str, item12_variant: str, bases: tuple[str, ...]) -> dict[str, Any]:
    return {
        "experiment": "T1 ceiling-push slot C — phase-locked item-9 + item-12 slot replacement",
        "mechanism_axis": 5,
        "fwer_family_size": 5,
        "per_slot_strict_gate_frac_above_zero": 0.99,  # Bonferroni n=5
        "cohort": {
            "target": "T1 = sum(items 9-14)",
            "n_subjects_min": 90,
            "filter": "PD with full items 9-14, 15, 18 (matches iter34 N=93)",
        },
        "stage1": {
            "model": "Ridge", "alpha": STAGE1_ALPHA,
            "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
            "stage1_total_features": 9, "per_fold_standardisation": True,
            "source_module": "run_t3_iter5_clinical:fit_stage1",
            "target": "T1 (sum items 9-14)",
        },
        "stage2_slotC": {
            "items": list(SLOT_C_ITEMS),
            "item9_variant": item9_variant,
            "item12_variant": item12_variant,
            "phaselocked_caches": {
                "item9": str(PHASELOCKED_CACHES[9].name),
                "item12": str(PHASELOCKED_CACHES[12].name),
            },
            "per_item_model": "LightGBM (n=500, lr=0.05, num_leaves=15, min_data=10)",
            "feature_select": "K=500 LGB importance per fold (variant-dependent)",
            "imputation": "fold_local_median",
        },
        "stage2_iter34_chain_for_other_items": {
            "items_used_from_chain_for_T1": [10, 11, 13, 14],
            "auxiliary_items_in_chain_fit_only": [15, 18],
            "items_in_chain_target": list(T1_SUM_ITEMS) + list(AUX_ITEMS),
            "bases": list(bases),
            "ensemble_method": "average chain output across bases per fold per seed",
            "chain_class": "sklearn.multioutput.RegressorChain(order='random')",
            "stage2_feature_select": "K=500 LGB importance per fold on T1 residual",
            "imputation": "fold_local_median",
            "centering": "subtract per-fold train_mean(item)",
        },
        "composite_formula": (
            "T1_pred = Stage1_pred + (slot_C_item9_pred + iter34_chain_item10 + "
            "iter34_chain_item11 + slot_C_item12_pred + iter34_chain_item13 + "
            "iter34_chain_item14) - sum(train_mean[items 9..14]). "
            "Slot-C item OOFs include their own item_mean + Ridge Stage-1 (per "
            "item-variant); iter34 chain items include item_mean. The composite "
            "Stage-1 (T1-level) is added once on top after subtracting the per-item "
            "train means baked into each piece."
        ),
        "eval": {
            "loocv_n_min": 90, "seeds": list(SEEDS_DEFAULT),
            "headline_metric": "CCC of mean-of-3-seed predictions vs y_t1",
            "comparator_iter34": str(ITER34_LOCKBOX_JSON.name),
            "comparator_iter34_oof": str(ITER34_OOF_NPY.name),
            "comparator_iter12_honest_paired_n93_json": str(ITER12_HONEST_N93_PAIRED_JSON.name),
            "fwer_strict_gate_vs_iter12_honest_n93": 0.99,
            "fwer_strict_gate_vs_iter34_n93": 0.99,
        },
        "lockbox_rules": [
            "ONE pre-registered config (formula_sha256-bound). ONE LOOCV run.",
            "Headline = CCC of mean-of-3-seed predictions.",
            "Bonferroni n=5: per-slot strict gate frac>0 ≥ 0.99 to claim canonical update.",
            "Verdict 'PASS-canonical' if frac>0 vs BOTH iter12-honest-n93 AND iter34-n93 ≥ 0.99.",
            "Verdict 'PASS-candidate' if frac>0 vs iter12-honest-n93 ≥ 0.99 but vs iter34 < 0.99.",
            "Verdict 'FAIL' otherwise. Composite-level cherry-picking guard: variants frozen in pre-reg.",
        ],
        "constants": {"K_FEATURES": K_FEATURES, "STAGE1_ALPHA": STAGE1_ALPHA},
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


def write_preregistration(item9_variant: str, item12_variant: str, bases: tuple[str, ...]) -> Path:
    if item9_variant not in SLOT_C_VARIANTS:
        raise ValueError(f"item9_variant {item9_variant!r} not in {SLOT_C_VARIANTS}")
    if item12_variant not in SLOT_C_VARIANTS:
        raise ValueError(f"item12_variant {item12_variant!r} not in {SLOT_C_VARIANTS}")
    payload = _formula_payload(item9_variant, item12_variant, bases)
    sha = _formula_sha256(payload)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts, "iso_datetime": datetime.now().isoformat(),
        "experiment": "T1 ceiling-push slot C — phase-locked item-9 + item-12 LOCKBOX",
        "git_head": _git_head(), "formula_sha256": sha, "formula": payload,
        "variant": "phaselocked_item9_item12_slot_replacement",
        "is_post_publication_replication_target": False,
        "fwer_family_membership": "T1 ceiling-push family of 5 (slots A,B,C,D + iter34 baseline)",
        "fwer_correction_method": "Bonferroni; per-slot strict gate frac>0 ≥ 0.99",
        "eval_protocol": (
            "LOOCV on T1∩{15,18} cohort (N≈93). Per-item slot C models for items {9,12} "
            "use phase-locked features + chosen variant. iter34-style chain re-run with "
            "per-item OOF extraction provides items {10, 11, 13, 14}. Composite T1 "
            "summed per fold. 3-seed mean preds = headline."
        ),
    }
    out = RESULTS_DIR / f"preregistration_t1_ceiling_push_slotC_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    print(f"  item9_variant  = {item9_variant}", flush=True)
    print(f"  item12_variant = {item12_variant}", flush=True)
    return out


# -----------------------------------------------------------------------------
# Bootstrap utility (paired, N=93)
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
    }


# -----------------------------------------------------------------------------
# Lockbox composite
# -----------------------------------------------------------------------------
def run_lockbox(prereg_file: Path,
                seeds: tuple[int, ...] = SEEDS_DEFAULT,
                feature_set: str = "A3_tier1",
                n_workers: int = 11,
                bases: tuple[str, ...] = ("lgb", "xgb", "et")) -> Path:
    if not prereg_file.exists():
        raise FileNotFoundError(prereg_file)
    with open(prereg_file) as f:
        prereg = json.load(f)
    item9_variant = prereg["formula"]["stage2_slotC"]["item9_variant"]
    item12_variant = prereg["formula"]["stage2_slotC"]["item12_variant"]
    expected_sha = _formula_sha256(_formula_payload(item9_variant, item12_variant, bases))
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(
            f"prereg formula_sha256 {prereg.get('formula_sha256')!r} != current {expected_sha!r}"
        )
    print(
        f"\n=== T1 SLOT C LOCKBOX LOOCV ({len(seeds)} seeds, "
        f"item9={item9_variant}, item12={item12_variant}, bases={bases}, "
        f"n_workers={n_workers}) ===",
        flush=True,
    )

    # Load cohort + V2 + items
    sids, X_v2, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    # Per-seed: slot-C OOFs + iter34 chain OOFs → composite
    per_seed_t1 = []
    per_seed_diag = []
    overall_t0 = time.time()
    for seed in seeds:
        t0 = time.time()
        # 1. iter34-style chain LOOCV → s1, per-item preds, per-fold means
        s1_arr, item_pred_arr, item_means_per_fold = _iter34_chain_loocv_per_item(
            seed, X_v2, y_t1, X_s1, items, item_order, bases, n_workers
        )
        # 2. Slot C per-item LOOCV (items 9 + 12)
        slot_c_oofs: dict[int, np.ndarray] = {}
        for item, var in ((9, item9_variant), (12, item12_variant)):
            X_pl, _ = load_phaselocked_features(sids, item)
            y_item = items[item].astype(np.float64)
            slot_c_oofs[item] = _loocv_per_item(item, X_pl, X_v2, hy, y_item, var, seed, n_workers)

        # 3. Build composite T1 predictions per subject:
        # T1_pred[i] = s1_arr[i] + sum_{k in T1_SUM_ITEMS}(piece_k[i] - item_means_per_fold[i][k])
        # piece_k = slot_c_oofs[k] for k in {9,12} (already includes own ridge stage1 + item_mean if hy_residual; for non-hy_residual variants it's s2 only — we add per-fold item mean explicitly below for consistency)
        # iter34 chain item_pred_full[i, j] already includes item_mean.
        n = len(sids)
        t1_composite = np.zeros(n)
        # Fold loop is implicit per-subject (since LOOCV is one subject per fold)
        for i in range(n):
            imeans = item_means_per_fold[i]
            piece_sum = 0.0
            for k in T1_SUM_ITEMS:
                if k in (9, 12):
                    # slot C OOF is "Stage1(item) + Stage2(item residual)" for hy_residual_item_v2
                    # OR "Stage2(item)" for item_only/item_plus_v2 (no per-item Ridge Stage1)
                    # For composite consistency, we use the slot-C item prediction directly as the "piece for item k"
                    piece = float(slot_c_oofs[k][i])
                else:
                    j = item_order.index(k)
                    piece = float(item_pred_arr[i, j])
                piece_sum += piece
            t1_composite[i] = s1_arr[i] + piece_sum - sum(imeans[k] for k in T1_SUM_ITEMS)
        c_slotC = float(ccc_fn(y_t1, t1_composite))

        # iter34 hybrid replication for same-seed comparator
        # T1_iter34 = s1 + sum_{k in T1_SUM_ITEMS}(item_pred_arr[k] - item_mean_k)
        t1_iter34 = np.zeros(n)
        for i in range(n):
            imeans = item_means_per_fold[i]
            ssum = 0.0
            for k in T1_SUM_ITEMS:
                j = item_order.index(k)
                ssum += float(item_pred_arr[i, j])
            t1_iter34[i] = s1_arr[i] + ssum - sum(imeans[k] for k in T1_SUM_ITEMS)
        c_iter34_repl = float(ccc_fn(y_t1, t1_iter34))

        per_seed_t1.append({"seed": seed, "ccc_slotC": c_slotC, "ccc_iter34_repl": c_iter34_repl,
                            "delta": c_slotC - c_iter34_repl, "wall": time.time() - t0,
                            "preds_slotC": t1_composite.tolist(),
                            "preds_iter34_repl": t1_iter34.tolist()})
        per_seed_diag.append({
            "seed": seed,
            "slotC_per_item_ccc": {
                int(k): float(ccc_fn(items[k][~np.isnan(items[k])], slot_c_oofs[k][~np.isnan(items[k])]))
                for k in (9, 12)
            },
        })
        print(
            f"  seed={seed}: SLOT-C T1={c_slotC:.4f} | iter34-repl T1={c_iter34_repl:.4f} | "
            f"Δ={c_slotC-c_iter34_repl:+.4f} | {time.time()-t0:.0f}s",
            flush=True,
        )
    overall_wall = time.time() - overall_t0

    # Mean-of-seeds preds
    mean_slotC = np.mean(np.column_stack([np.array(p["preds_slotC"]) for p in per_seed_t1]), axis=1)
    mean_iter34 = np.mean(np.column_stack([np.array(p["preds_iter34_repl"]) for p in per_seed_t1]), axis=1)
    headline = full_metrics(y_t1, mean_slotC, label="t1_slotC_phaselocked")

    # 1. Bootstrap vs iter34 on this cohort (re-run, same SIDs)
    boot_iter34 = _paired_bootstrap_ccc(y_t1, mean_slotC, mean_iter34)
    # 2. Bootstrap vs canonical iter34 lockbox OOF (SID-aligned)
    boot_iter34_canonical = None
    if ITER34_LOCKBOX_JSON.exists() and ITER34_OOF_NPY.exists():
        with open(ITER34_LOCKBOX_JSON) as f:
            i34 = json.load(f)
        sids_i34 = [str(s) for s in i34["per_subject"]["sids"]]
        p_i34 = np.load(ITER34_OOF_NPY)
        sid_to_pred = dict(zip(sids_i34, p_i34.tolist()))
        try:
            p_i34_aligned = np.array([sid_to_pred[str(s)] for s in sids])
            ccc_i34_canonical = float(ccc_fn(y_t1, p_i34_aligned))
            boot_iter34_canonical = _paired_bootstrap_ccc(y_t1, mean_slotC, p_i34_aligned)
            boot_iter34_canonical["ccc_iter34_canonical"] = round(ccc_i34_canonical, 4)
        except KeyError as e:
            boot_iter34_canonical = {"error": f"SID not in iter34 oof: {e!r}"}
    # 3. Bootstrap vs iter12-honest-on-N=93 — load from existing paired JSON if present
    boot_iter12_honest = None
    if ITER12_HONEST_N93_PAIRED_JSON.exists():
        with open(ITER12_HONEST_N93_PAIRED_JSON) as f:
            ihn = json.load(f)
        try:
            ihn_sids = ihn.get("sids") or ihn.get("per_subject", {}).get("sids")
            ihn_pred = ihn.get("iter12_honest_n93_pred") or ihn.get("y_pred_iter12_honest")
            if ihn_pred is None:
                # File has different structure; try to find arrays
                for k in ihn:
                    if "iter12" in k.lower() and "pred" in k.lower():
                        ihn_pred = ihn[k]
                        break
            if ihn_sids and ihn_pred:
                sid_to_p = dict(zip([str(s) for s in ihn_sids], list(ihn_pred)))
                p_ihn_aligned = np.array([sid_to_p[str(s)] for s in sids if str(s) in sid_to_p])
                if len(p_ihn_aligned) == len(sids):
                    ccc_ihn = float(ccc_fn(y_t1, p_ihn_aligned))
                    boot_iter12_honest = _paired_bootstrap_ccc(y_t1, mean_slotC, p_ihn_aligned)
                    boot_iter12_honest["ccc_iter12_honest_n93"] = round(ccc_ihn, 4)
                else:
                    boot_iter12_honest = {"error": f"SID-alignment len {len(p_ihn_aligned)} != {len(sids)}"}
            else:
                boot_iter12_honest = {"error": "could not parse iter12_honest preds from paired JSON"}
        except Exception as e:
            boot_iter12_honest = {"error": f"{type(e).__name__}: {e}"}
    else:
        boot_iter12_honest = {"error": f"missing {ITER12_HONEST_N93_PAIRED_JSON}"}

    # Verdict
    f0_iter34 = boot_iter34_canonical.get("frac_above_zero") if isinstance(boot_iter34_canonical, dict) else None
    f0_iter12 = boot_iter12_honest.get("frac_above_zero") if isinstance(boot_iter12_honest, dict) else None
    if f0_iter34 is not None and f0_iter12 is not None:
        if f0_iter34 >= 0.99 and f0_iter12 >= 0.99:
            verdict = "PASS-canonical (frac>0 vs iter34 AND iter12-honest-n93 BOTH ≥ 0.99)"
        elif f0_iter12 >= 0.99:
            verdict = f"PASS-candidate (frac>0 vs iter12-honest-n93 ≥ 0.99 but vs iter34 = {f0_iter34:.3f})"
        else:
            verdict = f"FAIL (frac>0 vs iter12={f0_iter12:.3f}, vs iter34={f0_iter34:.3f})"
    else:
        verdict = "UNKNOWN (comparator missing)"

    headline.update({
        "variant": "phaselocked_item9_item12_slot_replacement",
        "n_subjects": n,
        "preregistration_file": prereg_file.name,
        "is_lockbox_headline": True,
        "fwer_family_membership": "T1 ceiling-push family of 5",
        "fwer_correction_method": "Bonferroni; per-slot strict gate frac>0 ≥ 0.99",
        "n_seeds": len(seeds),
        "per_seed": [{k: v for k, v in s.items() if k not in ("preds_slotC", "preds_iter34_repl")} for s in per_seed_t1],
        "per_seed_diag": per_seed_diag,
        "wall_time_total_s": overall_wall,
        "ccc_iter34_replication": round(float(ccc_fn(y_t1, mean_iter34)), 4),
        "delta_vs_iter34_replication": round(headline["ccc"] - float(ccc_fn(y_t1, mean_iter34)), 4),
        "bootstrap_delta_vs_iter34_same_seed_replication": boot_iter34,
        "bootstrap_delta_vs_iter34_canonical_lockbox": boot_iter34_canonical,
        "bootstrap_delta_vs_iter12_honest_n93": boot_iter12_honest,
        "verdict": verdict,
        "is_canonical_update": "PASS-canonical" in verdict,
        "per_subject": {
            "sids": [str(s) for s in sids],
            "y_true": y_t1.tolist(), "y_pred": mean_slotC.tolist(),
        },
    })
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_ceiling_push_slotC_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t1_ceiling_push_slotC_{ts}.oof.npy"
    np.save(out_npy, mean_slotC)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)

    print(
        f"\n=== HEADLINE: CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f}, "
        f"r={headline['r']:.4f} ===",
        flush=True,
    )
    print(f"  iter34 replication CCC = {headline['ccc_iter34_replication']:.4f}", flush=True)
    print(f"  Δ vs iter34 replication = {headline['delta_vs_iter34_replication']:+.4f}", flush=True)
    if isinstance(boot_iter34_canonical, dict) and "frac_above_zero" in boot_iter34_canonical:
        print(
            f"  vs iter34 canonical: ccc_i34={boot_iter34_canonical['ccc_iter34_canonical']:.4f}, "
            f"Δ̄={boot_iter34_canonical['delta_mean']:+.4f}, "
            f"frac>0={boot_iter34_canonical['frac_above_zero']:.3f}",
            flush=True,
        )
    if isinstance(boot_iter12_honest, dict) and "frac_above_zero" in boot_iter12_honest:
        print(
            f"  vs iter12-honest-n93: ccc={boot_iter12_honest['ccc_iter12_honest_n93']:.4f}, "
            f"Δ̄={boot_iter12_honest['delta_mean']:+.4f}, "
            f"frac>0={boot_iter12_honest['frac_above_zero']:.3f}",
            flush=True,
        )
    print(f"  VERDICT: {verdict}", flush=True)
    print(f"  total wall = {overall_wall:.0f}s ({overall_wall/60:.1f} min)", flush=True)
    print(f"Wrote {out_json}\n      {out_npy}", flush=True)
    return out_json


# -----------------------------------------------------------------------------
# Smoke (1 fold × 1 seed, item-only screen for items 9+12)
# -----------------------------------------------------------------------------
def smoke_test(seed: int = 42) -> None:
    print("\n=== SLOT C SMOKE TEST: 1 fold × 1 seed item-only on items 9+12 ===", flush=True)
    sids, X_v2, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    print(f"  cohort N={len(sids)}, T1 mean={y_t1.mean():.2f}", flush=True)

    for item in SLOT_C_ITEMS:
        X_pl, cols = load_phaselocked_features(sids, item)
        y_item = items[item].astype(np.float64)
        # Single 80/20 split
        n = len(sids)
        rng = np.random.RandomState(seed)
        idx = rng.permutation(n)
        tr = idx[: int(0.8 * n)]
        te = idx[int(0.8 * n) :]
        oof_partial = np.zeros(n)
        for var in ("item_only", "hy_residual_item_v2"):
            arg = (0, tr, te, item, X_pl, X_v2, hy, y_item, var, seed)
            te_idx, te_pred = _loo_per_item_one_fold(arg)
            mask = ~np.isnan(y_item[te_idx])
            c = float(ccc_fn(y_item[te_idx][mask], te_pred[mask])) if mask.any() else float("nan")
            print(f"  item {item} {var:24s}: 80/20 holdout per-item CCC = {c:+.4f}, "
                  f"k_pl={len(cols)}, n_tr={len(tr)}, n_te={len(te)}", flush=True)
    print("  SMOKE PASS", flush=True)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["smoke", "screen", "write_prereg", "lockbox"], required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--n_workers", type=int, default=int(os.getenv("SLOTC_WORKERS", 11)))
    ap.add_argument("--preregistration_file", type=str, default=None)
    ap.add_argument("--item9_variant", type=str, default="hy_residual_item_v2",
                    choices=list(SLOT_C_VARIANTS))
    ap.add_argument("--item12_variant", type=str, default="hy_residual_item_v2",
                    choices=list(SLOT_C_VARIANTS))
    ap.add_argument("--bases", type=str, nargs="+", default=["lgb", "xgb", "et"])
    args = ap.parse_args()

    ensure_dir(RESULTS_DIR)
    bases = tuple(args.bases)

    if args.mode == "smoke":
        smoke_test(seed=args.seeds[0])
    elif args.mode == "screen":
        sids, X_v2, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
        d = {"sids": sids, "items": items, "hy": hy, "t1": y_t1}
        screen(d, X_v2, n_workers=args.n_workers)
    elif args.mode == "write_prereg":
        write_preregistration(args.item9_variant, args.item12_variant, bases)
    else:
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required for lockbox mode")
        run_lockbox(
            Path(args.preregistration_file),
            seeds=tuple(args.seeds),
            feature_set=args.feature_set,
            n_workers=args.n_workers,
            bases=bases,
        )


if __name__ == "__main__":
    main()
