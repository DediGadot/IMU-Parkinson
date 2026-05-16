"""T3 iter21 — Nested-CV hybrid (iter5 + 18 per-item gated) → Ridge meta-learner.

Mission: break T3 LOOCV CCC > 0.5227 (iter5 canonical) WITHOUT data leakage.
F55 (2026-05-04) showed at N=94 5-fold: pearson(composite − iter5, updrs3 − iter5)
= +0.327 → theoretical hybrid Pearson upper bound +0.518; lift available up to
+0.113 over iter5 5-fold. F53 raw-sum composite at N=94 underperformed by Δ=−0.107
(variance compounding). F54 audit identified four bugs that iter21 fixes:

  1. iter20 single-loop CV stacking is leaky (meta trains on OOFs whose base-fold
     overlaps meta-train rows). FIX: genuinely nested CV — inner 5-fold on outer-
     train ONLY produces inner-OOF predictions; meta-learner fits on those; base
     models retrain on full outer-train; outer-test predicted by base + meta.

  2. run_per_item_v2.load_data() silently filters T3 cohort to N=94 (T1 filter).
     FIX: T3-native loader at canonical N=98 (`updrs3` cohort); per-item targets
     allowed NaN; fold-locally drop NaN-target rows from per-item training.

  3. Multiple pre-reg files per attempt blur the iter11A bright line. FIX: split
     --mode write_prereg from --mode run; ONE immutable JSON; --run requires
     --preregistration_file=path; refuses to start without it.

  4. sum_of_items vs updrs3 mismatch is subject-specific. FIX: hybrid endpoint is
     updrs3 directly via the fold-local Ridge meta-learner. Meta-learner mixes 19
     base predictions (iter5 + 18 per-item) to predict updrs3.

ARCHITECTURE (per-item base map FROZEN from iter19, no cherry-picking):

  items 1-3:    v2_baseline                (Phase A1)
  items 4, 5:   v2_baseline                (iter8 lockboxed)
  item 6:       lr_multitask               (iter8 lockboxed)
  items 7, 8:   iter17:hy_residual_item_v2 (Phase A2 5-fold winner)
  item 9:       hy_residual_item           (iter8 lockboxed)
  items 10, 12-14: item_plus_v2            (iter8 lockboxed)
  item 11:      item_dedicated             (iter8 lockboxed)
  item 15:      iter17:item_only           (iter17 lockboxed)
  items 16, 17: iter17:item_plus_v2        (Phase A2 5-fold winner)
  item 18:      iter17:hy_residual_item_v2 (iter17 lockboxed)

GATES:
  5-fold sum-level: hybrid CCC ≥ iter5 5-fold + 0.025 AND hybrid std < 0.020 (3 seeds).
  LOOCV lockbox:    paired bootstrap CI vs iter5 LOOCV on same N=98 with 5000
                    resamples; canonical update requires frac>0 ≥ 95% AND
                    ccc > 0.5227.

USAGE:

  # 1. Write the immutable pre-registration (5-fold gate). Exits without running.
  python3 run_t3_iter21_nested.py --mode write_prereg --cv 5fold \\
      --seeds 42 1337 7

  # 2. Execute the 5-fold gate (requires --preregistration_file=<path>).
  python3 run_t3_iter21_nested.py --mode run --cv 5fold \\
      --preregistration_file results/preregistration_t3_iter21_nested_<ts>.json

  # 3. If 5-fold passes, write LOOCV pre-reg and run lockbox separately.
  python3 run_t3_iter21_nested.py --mode write_prereg --cv loocv --seeds 42 1337 7
  python3 run_t3_iter21_nested.py --mode run --cv loocv \\
      --preregistration_file results/preregistration_t3_iter21_nested_<ts>.json

5-NULL GATE INHERITANCE:
  Per-item architectures bit-equivalent to iter8/iter17/A1 lockboxes — each passed
  the 5-null gate. iter5 base inherits its own pre-registered nulls. Meta-learner
  is per-fold leakage-clean Ridge on inner-OOF training rows only.
"""
from __future__ import annotations

import os
# Default LGB threads to 1 so we can saturate cores via ProcessPoolExecutor without
# thread oversubscription. Set PD_IMU_N_CORES explicitly to override.
os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
import hashlib
import json
import subprocess
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    feature_select_fold,
    get_hy_features,
    impute_fold,
    train_lgb,
)
from run_t3_iter5_clinical import (
    CLINICAL_COLS_BINARY,
    CLINICAL_COLS_CONTINUOUS,
    FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
)
from run_per_item_iter17_hypothesis import load_item_features as iter17_load_item_features

# ── Fixed architecture map (FROZEN before any composite is computed) ────────


ARCH_MAP: dict[int, str] = {
    1: "v2_baseline",
    2: "v2_baseline",
    3: "v2_baseline",
    4: "v2_baseline",
    5: "v2_baseline",
    6: "lr_multitask",
    7: "iter17:hy_residual_item_v2",
    8: "iter17:hy_residual_item_v2",
    9: "hy_residual_item",
    10: "item_plus_v2",
    11: "item_dedicated",
    12: "item_plus_v2",
    13: "item_plus_v2",
    14: "item_plus_v2",
    15: "iter17:item_only",
    16: "iter17:item_plus_v2",
    17: "iter17:item_plus_v2",
    18: "iter17:hy_residual_item_v2",
}

ITER5_FEATURE_SET = "A3_tier1"  # cv_yrs + cv_sex + cv_dbs
ITER5_ALPHA = 1.0
META_ALPHA = 1.0
LGB_FEATURE_K = 500
PAIRED_ITEMS = [4, 5, 6, 7, 8, 15, 16]
V2_FEATURES_PATH = RESULTS_DIR / "ablation_v3_features.csv"
PER_ITEM_CACHE_PATH = RESULTS_DIR / "per_item_scores.json"
ITEM_SPECIFIC_CACHE_PATH = RESULTS_DIR / "item_specific_features.csv"

V2_EXCLUDED_PREFIXES = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")


# ── T3-native loader (F54 bug #2 fix: keyed to canonical updrs3 cohort N=98) ─


def is_pd(sid: str) -> bool:
    s = str(sid).upper()
    return s.startswith("NLS") or s.startswith("WPD")


def load_data_t3() -> dict:
    """T3-native loader: returns N=98 PD cohort with all fields needed for iter21.

    Per-item targets are allowed NaN (some items not rated for some subjects). Per-
    item base models drop NaN-target rows from training fold-locally and predict
    NaN-target subjects normally (we never use NaN-target rows as TRAINING rows).

    Returns
    -------
    dict with keys:
      sids        — np.ndarray (N=98,) str
      X_v2        — (N, K_v2) V2 IMU features
      hy          — (N,) Hoehn & Yahr stage
      clinical    — dict[str, (N,)] for cv_yrs, cv_sex, cv_dbs (and others)
      items       — dict[int, (N,)] per-item targets (NaN for non-rated)
      updrs3      — (N,) canonical T3 target
      sum_items   — (N,) sum_of_items_1to18 (with NaN→per-item-mean imputation)
      X_per_item  — dict[int, (N, k_i)] item-specific cache features (items 7, 8,
                    15, 16, 17, 18 from item_specific_features.csv)
      X_per_item_v2cache — dict[int, (N, k_i)] from peritem_subj_features.csv
                          (general per-item cache used by run_per_item_v2 variants)
    """
    df = pd.read_csv(V2_FEATURES_PATH)
    excluded = {"sid", "updrs3", "obs_subscore", "hy"}
    feat_cols = [
        c for c in df.columns
        if c not in excluded and not any(c.startswith(p) for p in V2_EXCLUDED_PREFIXES)
    ]
    pd_mask = df["sid"].apply(is_pd)
    pd_df = df[pd_mask].reset_index(drop=True)

    sids = pd_df["sid"].to_numpy()
    n = len(sids)
    X_v2 = pd_df[feat_cols].to_numpy(dtype=np.float64)
    updrs3 = pd_df["updrs3"].astype(float).to_numpy()
    hy = pd.to_numeric(pd_df["hy"], errors="coerce").to_numpy()

    # Clinical extras (must be present in V2_FEATURES per CLAUDE.md schema)
    clinical: dict[str, np.ndarray] = {}
    for col in CLINICAL_COLS_CONTINUOUS + CLINICAL_COLS_BINARY:
        if col not in pd_df.columns:
            raise KeyError(f"Required clinical column missing: {col!r}")
        clinical[col] = pd.to_numeric(pd_df[col], errors="coerce").to_numpy(dtype=np.float64)
    clinical["site_nls"] = np.array([1.0 if s.startswith("NLS") else 0.0 for s in sids])

    # Per-item targets — NaN-allowed
    with open(PER_ITEM_CACHE_PATH) as f:
        raw = json.load(f)
    items: dict[int, np.ndarray] = {i: np.full(n, np.nan, dtype=np.float64) for i in range(1, 19)}
    for j, sid in enumerate(sids):
        scores = raw.get(sid, {})
        for k_str, v in scores.items():
            if k_str.startswith("("):
                continue
            try:
                ki = int(k_str)
            except ValueError:
                continue
            if 1 <= ki <= 18 and v is not None:
                try:
                    items[ki][j] = float(v)
                except (ValueError, TypeError):
                    pass
    sum_items = np.zeros(n, dtype=np.float64)
    for i in range(1, 19):
        col = items[i].copy()
        col[np.isnan(col)] = float(np.nanmean(col))
        sum_items += col

    # Per-item v2 cache (general — needed by run_per_item_v2 variants).
    # Note: items 17 and 18 share prefix `i1718_` in peritem_subj_features.csv per
    # the existing run_per_item_v2.get_item_features convention.
    peritem_v2_cache_path = RESULTS_DIR / "peritem_subj_features.csv"
    X_per_item_v2cache: dict[int, np.ndarray] = {}
    peritem_cols_by_item: dict[int, list[str]] = {}
    if peritem_v2_cache_path.exists():
        df_pi = pd.read_csv(peritem_v2_cache_path).set_index("sid")
        all_cols = list(df_pi.columns)
        for i in range(1, 19):
            prefix = "i1718_" if i in (17, 18) else f"i{i}_"
            cols_i = [c for c in all_cols if c.startswith(prefix)]
            if not cols_i:
                X_per_item_v2cache[i] = np.full((n, 0), np.nan, dtype=np.float64)
                peritem_cols_by_item[i] = []
                continue
            X = np.full((n, len(cols_i)), np.nan, dtype=np.float64)
            for j, sid in enumerate(sids):
                if sid in df_pi.index:
                    X[j] = df_pi.loc[sid, cols_i].to_numpy(dtype=np.float64)
            X_per_item_v2cache[i] = X
            peritem_cols_by_item[i] = cols_i
    else:
        raise FileNotFoundError(f"Missing required cache: {peritem_v2_cache_path}")

    # Item-specific cache for iter17 hypothesis-restricted items (4, 6, 7, 8, 15, 16, 17, 18).
    # Default to empty (n, 0) for any item without a prefix in the CSV.
    X_per_item_iter17: dict[int, np.ndarray] = {i: np.full((n, 0), np.nan, dtype=np.float64) for i in range(1, 19)}
    if ITEM_SPECIFIC_CACHE_PATH.exists():
        df_is = pd.read_csv(ITEM_SPECIFIC_CACHE_PATH).set_index("sid")
        for i in [4, 6, 7, 8, 15, 16, 17, 18]:
            prefix = f"i{i}_"
            cols_i = [c for c in df_is.columns if c.startswith(prefix)]
            if not cols_i:
                continue
            X = np.full((n, len(cols_i)), np.nan, dtype=np.float64)
            for j, sid in enumerate(sids):
                if sid in df_is.index:
                    X[j] = df_is.loc[sid, cols_i].to_numpy(dtype=np.float64)
            X_per_item_iter17[i] = X
    else:
        raise FileNotFoundError(f"Missing iter17 item-specific cache: {ITEM_SPECIFIC_CACHE_PATH}")

    return {
        "sids": sids,
        "X_v2": X_v2,
        "feat_cols": feat_cols,
        "hy": hy,
        "clinical": clinical,
        "items": items,
        "updrs3": updrs3,
        "sum_items": sum_items,
        "X_per_item_v2cache": X_per_item_v2cache,
        "peritem_cols_by_item": peritem_cols_by_item,
        "X_per_item_iter17": X_per_item_iter17,
        "site": clinical["site_nls"],
    }


# ── Base model functions ─────────────────────────────────────────────────────


def _drop_nan_train(tr_idx: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Filter NaN-target rows from a training index array."""
    mask = ~np.isnan(y[tr_idx])
    return tr_idx[mask]


def base_iter5(d: dict, tr: np.ndarray, te: np.ndarray, seed: int) -> np.ndarray:
    """iter5 base prediction on test fold te using training rows tr.

    Stage 1: Ridge(α=1.0) on H&Y(linear+1hot) + cv_yrs + cv_sex + cv_dbs → updrs3.
    Stage 2: LGB(K=500) on V2 residual.
    """
    extras = FEATURE_SETS[ITER5_FEATURE_SET]
    X_s1, _ = build_stage1_features(d["hy"], d["clinical"], extras)
    s1_tr, s1_te = fit_stage1(X_s1[tr], d["updrs3"][tr], X_s1[te], alpha=ITER5_ALPHA)
    resid_tr = d["updrs3"][tr] - s1_tr
    Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
    Xtr_s, Xte_s, _ = feature_select_fold(Xtr, resid_tr, Xte, k=LGB_FEATURE_K, seed=seed)
    s2_te = train_lgb(Xtr_s, resid_tr, Xte_s, seed)
    return s1_te + s2_te


def _v2_baseline_item(d: dict, item: int, tr: np.ndarray, te: np.ndarray, seed: int) -> np.ndarray:
    y = d["items"][item]
    tr_v = _drop_nan_train(tr, y)
    if len(tr_v) < 5:
        return np.full(len(te), float(np.nanmean(y)))
    Xtr, Xte = impute_fold(d["X_v2"][tr_v], d["X_v2"][te])
    Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y[tr_v], Xte, k=LGB_FEATURE_K, seed=seed)
    return train_lgb(Xtr_s, y[tr_v], Xte_s, seed)


def _item_dedicated_item(d: dict, item: int, tr: np.ndarray, te: np.ndarray, seed: int) -> np.ndarray:
    y = d["items"][item]
    X_item = d["X_per_item_v2cache"].get(item)
    if X_item is None or X_item.shape[1] == 0:
        return _v2_baseline_item(d, item, tr, te, seed)
    tr_v = _drop_nan_train(tr, y)
    if len(tr_v) < 5:
        return np.full(len(te), float(np.nanmean(y)))
    Xtr, Xte = impute_fold(X_item[tr_v], X_item[te])
    k = min(LGB_FEATURE_K, Xtr.shape[1])
    Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y[tr_v], Xte, k=k, seed=seed)
    return train_lgb(Xtr_s, y[tr_v], Xte_s, seed)


def _item_plus_v2_item(d: dict, item: int, tr: np.ndarray, te: np.ndarray, seed: int) -> np.ndarray:
    y = d["items"][item]
    X_item = d["X_per_item_v2cache"].get(item)
    if X_item is None or X_item.shape[1] == 0:
        return _v2_baseline_item(d, item, tr, te, seed)
    X_aug = np.hstack([d["X_v2"], X_item])
    tr_v = _drop_nan_train(tr, y)
    if len(tr_v) < 5:
        return np.full(len(te), float(np.nanmean(y)))
    Xtr, Xte = impute_fold(X_aug[tr_v], X_aug[te])
    Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y[tr_v], Xte, k=LGB_FEATURE_K, seed=seed)
    return train_lgb(Xtr_s, y[tr_v], Xte_s, seed)


def _hy_residual_item_item(d: dict, item: int, tr: np.ndarray, te: np.ndarray, seed: int) -> np.ndarray:
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
    X_item = d["X_per_item_v2cache"].get(item)
    if X_item is not None and X_item.shape[1] > 0:
        X_aug = np.hstack([d["X_v2"], X_item])
    else:
        X_aug = d["X_v2"]
    tr_v = _drop_nan_train(tr, y)
    if len(tr_v) < 5:
        return np.full(len(te), float(np.nanmean(y)))
    ridge = Ridge(alpha=1.0, random_state=seed)
    ridge.fit(hy_feat[tr_v], y[tr_v])
    s1_tr = ridge.predict(hy_feat[tr_v])
    s1_te = ridge.predict(hy_feat[te])
    resid_tr = y[tr_v] - s1_tr
    Xtr, Xte = impute_fold(X_aug[tr_v], X_aug[te])
    Xtr_s, Xte_s, _ = feature_select_fold(Xtr, resid_tr, Xte, k=LGB_FEATURE_K, seed=seed)
    return s1_te + train_lgb(Xtr_s, resid_tr, Xte_s, seed)


def _lr_multitask_item(d: dict, item: int, tr: np.ndarray, te: np.ndarray, seed: int) -> np.ndarray:
    """LGB with item-level + V2 + L/R abs-diff augmentation."""
    if item not in PAIRED_ITEMS:
        return _v2_baseline_item(d, item, tr, te, seed)
    y = d["items"][item]
    X_item = d["X_per_item_v2cache"].get(item)
    cols = d["peritem_cols_by_item"].get(item, [])
    if not cols or X_item is None or X_item.shape[1] == 0:
        return _v2_baseline_item(d, item, tr, te, seed)
    paired = []
    for lc in cols:
        if "_L_" in lc or lc.startswith(f"i{item}_L_"):
            rc = lc.replace("_L_", "_R_").replace(f"i{item}_L_", f"i{item}_R_")
            if rc in cols:
                paired.append((cols.index(lc), cols.index(rc)))
    if paired:
        ad = np.array([np.abs(X_item[:, li] - X_item[:, ri]) for li, ri in paired]).T
        X_full = np.hstack([d["X_v2"], X_item, ad])
    else:
        X_full = np.hstack([d["X_v2"], X_item])
    tr_v = _drop_nan_train(tr, y)
    if len(tr_v) < 5:
        return np.full(len(te), float(np.nanmean(y)))
    Xtr, Xte = impute_fold(X_full[tr_v], X_full[te])
    Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y[tr_v], Xte, k=LGB_FEATURE_K, seed=seed)
    return train_lgb(Xtr_s, y[tr_v], Xte_s, seed)


def _iter17_item(d: dict, item: int, variant: str, tr: np.ndarray, te: np.ndarray, seed: int) -> np.ndarray:
    """iter17 hypothesis-restricted variants: item_only / item_plus_v2 / hy_residual_item_v2.

    Uses item-specific cache (item_specific_features.csv) for items 7, 8, 15, 16, 17, 18.
    """
    y = d["items"][item]
    X_item = d["X_per_item_iter17"].get(item)
    if X_item is None or X_item.shape[1] == 0:
        return _v2_baseline_item(d, item, tr, te, seed)
    tr_v = _drop_nan_train(tr, y)
    if len(tr_v) < 5:
        return np.full(len(te), float(np.nanmean(y)))
    if variant == "item_only":
        Xtr, Xte = impute_fold(X_item[tr_v], X_item[te])
        k = min(LGB_FEATURE_K, Xtr.shape[1])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y[tr_v], Xte, k=k, seed=seed)
        return train_lgb(Xtr_s, y[tr_v], Xte_s, seed)
    elif variant == "item_plus_v2":
        X_aug = np.hstack([d["X_v2"], X_item])
        Xtr, Xte = impute_fold(X_aug[tr_v], X_aug[te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y[tr_v], Xte, k=LGB_FEATURE_K, seed=seed)
        return train_lgb(Xtr_s, y[tr_v], Xte_s, seed)
    elif variant == "hy_residual_item_v2":
        X_aug = np.hstack([d["X_v2"], X_item])
        hy_feat = get_hy_features(d["hy"])
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr_v], y[tr_v])
        s1_tr = ridge.predict(hy_feat[tr_v])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = y[tr_v] - s1_tr
        Xtr, Xte = impute_fold(X_aug[tr_v], X_aug[te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, resid_tr, Xte, k=LGB_FEATURE_K, seed=seed)
        return s1_te + train_lgb(Xtr_s, resid_tr, Xte_s, seed)
    else:
        raise ValueError(f"unknown iter17 variant: {variant!r}")


def base_per_item(arch: str, d: dict, item: int, tr: np.ndarray, te: np.ndarray, seed: int) -> np.ndarray:
    """Dispatch to the right per-item architecture and return predictions on `te`."""
    if arch == "v2_baseline":
        return _v2_baseline_item(d, item, tr, te, seed)
    if arch == "item_dedicated":
        return _item_dedicated_item(d, item, tr, te, seed)
    if arch == "item_plus_v2":
        return _item_plus_v2_item(d, item, tr, te, seed)
    if arch == "hy_residual_item":
        return _hy_residual_item_item(d, item, tr, te, seed)
    if arch == "lr_multitask":
        return _lr_multitask_item(d, item, tr, te, seed)
    if arch.startswith("iter17:"):
        variant = arch.split(":", 1)[1]
        return _iter17_item(d, item, variant, tr, te, seed)
    raise ValueError(f"unknown architecture: {arch!r}")


# ── Nested CV core ───────────────────────────────────────────────────────────


def _build_outer_splits(n: int, cv: str, seed: int) -> list[tuple[np.ndarray, np.ndarray]]:
    if cv == "5fold":
        return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))
    elif cv == "loocv":
        return [(np.array([j for j in range(n) if j != i]), np.array([i])) for i in range(n)]
    raise ValueError(f"unknown cv: {cv!r}")


def _build_inner_splits(outer_tr: np.ndarray, seed: int, n_splits: int = 5) -> list[tuple[np.ndarray, np.ndarray]]:
    """5-fold inner splits over the OUTER_TR positions (returns indices into outer_tr,
    NOT into the global N). Caller maps back to global indices."""
    return list(KFold(n_splits=n_splits, shuffle=True, random_state=seed + 1).split(np.arange(len(outer_tr))))


def _compute_outer_fold(args: tuple) -> dict:
    """Per-outer-fold worker: computes inner-OOF matrix, fits Ridge meta, predicts outer-test.

    Args is a tuple to keep ProcessPoolExecutor happy with single-arg map.
    """
    (
        d_data, outer_idx, outer_tr_global, outer_te_global, seed, cv, n_inner_splits, fold_label,
    ) = args
    # Reconstruct dict from pickled-friendly form
    d = d_data
    n_outer_tr = len(outer_tr_global)
    items_in_map = sorted(ARCH_MAP.keys())
    n_base = 1 + len(items_in_map)  # iter5 + 18 per-item

    # ── Inner loop: build inner-OOF matrix (n_outer_tr × n_base) ──
    inner_oof = np.zeros((n_outer_tr, n_base), dtype=np.float64)
    inner_splits_local = _build_inner_splits(outer_tr_global, seed, n_inner_splits)
    t0 = time.time()
    for inner_pos, (inner_tr_local, inner_te_local) in enumerate(inner_splits_local):
        inner_tr_global = outer_tr_global[inner_tr_local]
        inner_te_global = outer_tr_global[inner_te_local]
        # iter5 base
        try:
            inner_oof[inner_te_local, 0] = base_iter5(d, inner_tr_global, inner_te_global, seed)
        except Exception as exc:
            print(f"    [{fold_label} seed={seed}] inner {inner_pos}: iter5 FAIL: {exc}", flush=True)
            inner_oof[inner_te_local, 0] = float(np.nanmean(d["updrs3"][inner_tr_global]))
        # 18 per-item bases
        for col_idx, item in enumerate(items_in_map, start=1):
            try:
                pred = base_per_item(ARCH_MAP[item], d, item, inner_tr_global, inner_te_global, seed)
            except Exception as exc:
                print(f"    [{fold_label} seed={seed}] inner {inner_pos} item {item}: FAIL: {exc}", flush=True)
                pred = np.full(len(inner_te_global), float(np.nanmean(d["items"][item])))
            inner_oof[inner_te_local, col_idx] = pred
    inner_elapsed = time.time() - t0

    # ── Fit Ridge meta-learner on (inner_oof, updrs3[outer_tr]) ──
    y_outer_tr = d["updrs3"][outer_tr_global]
    meta = Ridge(alpha=META_ALPHA, fit_intercept=True, random_state=seed)
    meta.fit(inner_oof, y_outer_tr)
    meta_coefs = meta.coef_.astype(np.float64).tolist()
    meta_intercept = float(meta.intercept_)

    # ── Retrain base models on FULL outer-train; predict outer-test ──
    n_outer_te = len(outer_te_global)
    outer_te_features = np.zeros((n_outer_te, n_base), dtype=np.float64)
    t1 = time.time()
    try:
        outer_te_features[:, 0] = base_iter5(d, outer_tr_global, outer_te_global, seed)
    except Exception as exc:
        print(f"    [{fold_label} seed={seed}] outer iter5 FAIL: {exc}", flush=True)
        outer_te_features[:, 0] = float(np.nanmean(d["updrs3"][outer_tr_global]))
    for col_idx, item in enumerate(items_in_map, start=1):
        try:
            outer_te_features[:, col_idx] = base_per_item(
                ARCH_MAP[item], d, item, outer_tr_global, outer_te_global, seed
            )
        except Exception as exc:
            print(f"    [{fold_label} seed={seed}] outer item {item} FAIL: {exc}", flush=True)
            outer_te_features[:, col_idx] = float(np.nanmean(d["items"][item]))
    outer_elapsed = time.time() - t1

    # Hybrid predictions on outer-test via meta-learner
    hybrid_pred = meta.predict(outer_te_features)
    iter5_outer_pred = outer_te_features[:, 0]  # already computed for free

    return {
        "fold_label": fold_label,
        "seed": seed,
        "outer_idx": outer_idx,
        "outer_tr_global": outer_tr_global.tolist(),
        "outer_te_global": outer_te_global.tolist(),
        "hybrid_pred": hybrid_pred.tolist(),
        "iter5_outer_pred": iter5_outer_pred.tolist(),
        "outer_te_features": outer_te_features.tolist(),
        "meta_coefs": meta_coefs,
        "meta_intercept": meta_intercept,
        "inner_elapsed_s": round(inner_elapsed, 1),
        "outer_elapsed_s": round(outer_elapsed, 1),
        "n_inner_splits": n_inner_splits,
        "n_outer_tr": int(n_outer_tr),
        "n_outer_te": int(n_outer_te),
    }


def run_nested(d: dict, seeds: list[int], cv: str, n_workers: int, n_inner_splits: int = 5) -> dict:
    """Run nested CV across seeds and outer folds. Parallelizes per (seed, outer_fold)."""
    n = len(d["sids"])
    items_in_map = sorted(ARCH_MAP.keys())
    n_base = 1 + len(items_in_map)

    # Build job list
    jobs = []
    seed_outer_splits: dict[int, list] = {}
    for seed in seeds:
        outer_splits = _build_outer_splits(n, cv, seed)
        seed_outer_splits[seed] = outer_splits
        for outer_idx, (otr, ote) in enumerate(outer_splits):
            label = f"{cv}_o{outer_idx+1}/{len(outer_splits)}"
            jobs.append((d, outer_idx, otr, ote, seed, cv, n_inner_splits, label))

    n_jobs = len(jobs)
    print(f"\n=== run_nested: {n_jobs} (seed, outer_fold) jobs, n_workers={n_workers} ===", flush=True)
    print(f"  per job: 1 (iter5) + {len(items_in_map)} per-item × {n_inner_splits} inner + 1 outer-train retrain = "
          f"~{(1 + len(items_in_map)) * (n_inner_splits + 1)} model fits", flush=True)
    print(f"  total fits: ~{n_jobs * (1 + len(items_in_map)) * (n_inner_splits + 1)}", flush=True)

    fold_results: dict[tuple[int, int], dict] = {}
    t0 = time.time()
    if n_workers <= 1:
        for j_idx, j in enumerate(jobs):
            r = _compute_outer_fold(j)
            fold_results[(r["seed"], r["outer_idx"])] = r
            print(f"  [{j_idx+1}/{n_jobs}] seed={r['seed']} outer={r['outer_idx']+1}: "
                  f"inner={r['inner_elapsed_s']}s outer={r['outer_elapsed_s']}s", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=n_workers) as ex:
            futures = {ex.submit(_compute_outer_fold, j): j for j in jobs}
            done_count = 0
            for fut in as_completed(futures):
                r = fut.result()
                fold_results[(r["seed"], r["outer_idx"])] = r
                done_count += 1
                print(f"  [{done_count}/{n_jobs}] seed={r['seed']} outer={r['outer_idx']+1}: "
                      f"inner={r['inner_elapsed_s']}s outer={r['outer_elapsed_s']}s", flush=True)
    total_elapsed = time.time() - t0
    print(f"  TOTAL nested CV elapsed: {total_elapsed:.0f}s = {total_elapsed/60:.1f}min", flush=True)

    # Reassemble per-seed OOF predictions
    per_seed_hybrid: dict[int, np.ndarray] = {}
    per_seed_iter5: dict[int, np.ndarray] = {}
    per_seed_meta_coefs: dict[int, list[list[float]]] = {}
    for seed in seeds:
        outer_splits = seed_outer_splits[seed]
        hybrid_oof = np.zeros(n, dtype=np.float64)
        iter5_oof = np.zeros(n, dtype=np.float64)
        meta_coef_list = []
        for outer_idx, (otr, ote) in enumerate(outer_splits):
            r = fold_results[(seed, outer_idx)]
            hybrid_oof[ote] = np.asarray(r["hybrid_pred"])
            iter5_oof[ote] = np.asarray(r["iter5_outer_pred"])
            meta_coef_list.append([r["meta_intercept"]] + r["meta_coefs"])
        per_seed_hybrid[seed] = hybrid_oof
        per_seed_iter5[seed] = iter5_oof
        per_seed_meta_coefs[seed] = meta_coef_list

    # Compute per-seed CCC
    y = d["updrs3"]
    hybrid_cccs = [float(ccc_fn(y, per_seed_hybrid[s])) for s in seeds]
    iter5_cccs = [float(ccc_fn(y, per_seed_iter5[s])) for s in seeds]
    hybrid_mean_oof = np.mean(np.stack([per_seed_hybrid[s] for s in seeds], axis=0), axis=0)
    iter5_mean_oof = np.mean(np.stack([per_seed_iter5[s] for s in seeds], axis=0), axis=0)

    return {
        "n": int(n),
        "cv": cv,
        "seeds": list(seeds),
        "items_in_map": items_in_map,
        "n_base": n_base,
        "y_updrs3": y.tolist(),
        "sids": d["sids"].tolist(),
        "hybrid_per_seed_oof": {int(s): per_seed_hybrid[s].tolist() for s in seeds},
        "iter5_per_seed_oof": {int(s): per_seed_iter5[s].tolist() for s in seeds},
        "hybrid_mean_oof": hybrid_mean_oof.tolist(),
        "iter5_mean_oof": iter5_mean_oof.tolist(),
        "hybrid_per_seed_ccc": hybrid_cccs,
        "iter5_per_seed_ccc": iter5_cccs,
        "hybrid_ccc_mean": float(np.mean(hybrid_cccs)),
        "hybrid_ccc_std": float(np.std(hybrid_cccs)),
        "iter5_ccc_mean": float(np.mean(iter5_cccs)),
        "iter5_ccc_std": float(np.std(iter5_cccs)),
        "hybrid_3seed_ccc": float(ccc_fn(y, hybrid_mean_oof)),
        "iter5_3seed_ccc": float(ccc_fn(y, iter5_mean_oof)),
        "hybrid_mae_3seed_mean": float(mae_fn(y, hybrid_mean_oof)),
        "iter5_mae_3seed_mean": float(mae_fn(y, iter5_mean_oof)),
        "meta_coefs_per_seed_per_fold": per_seed_meta_coefs,
        "total_elapsed_s": round(total_elapsed, 1),
    }


# ── Pre-registration discipline (F54 bug #3 fix) ─────────────────────────────


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT
        ).decode().strip()
    except Exception:
        return "unknown"


def _formula_sha256(payload: dict) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canon).hexdigest()


def make_prereg_payload(seeds: list[int], cv: str, n_inner_splits: int) -> dict:
    return {
        "experiment": "T3 iter21 — Nested-CV hybrid (iter5 + 18 per-item) → Ridge meta",
        "origin": (
            "F53 owl review identified F55 +0.327 orthogonality probe (composite vs iter5 at "
            "N=94 5-fold); F54 audit flagged 4 leakage/discipline bugs; iter21 fixes all four "
            "and tests whether the F55 +0.113 theoretical lift is realizable under properly "
            "nested CV at canonical N=98."
        ),
        "architecture_map": {str(k): v for k, v in ARCH_MAP.items()},
        "iter5_feature_set": ITER5_FEATURE_SET,
        "iter5_alpha": ITER5_ALPHA,
        "meta_learner": "Ridge",
        "meta_alpha": META_ALPHA,
        "meta_n_features": 1 + len(ARCH_MAP),  # iter5 + 18 per-item
        "lgb_feature_K": LGB_FEATURE_K,
        "cv": cv,
        "n_inner_splits": n_inner_splits,
        "seeds": list(seeds),
        "n_subjects": "T3-native cohort N=98 (canonical updrs3); per-item targets allowed NaN, "
                     "fold-locally dropped from per-item TRAINING only.",
        "endpoint": "updrs3 (T3 canonical)",
        "5null_inheritance": (
            "iter5 base: pre-registered, canonical (results/preregistration_t3_iter5_*.json). "
            "Per-item bases: bit-equivalent to iter8/iter17/Phase A1 lockboxes — each pre-passed "
            "the 5-null gate. Meta-learner is Ridge fit on inner-OOF predictions whose base-fold "
            "is disjoint from meta-train rows by construction (genuinely nested CV)."
        ),
        "purpose": (
            "Test whether per-item composite carries information complementary to iter5 in a "
            "leakage-clean nested-CV stack. F55 said pearson(comp-iter5, updrs3-iter5)=+0.327 "
            "(N=94 5-fold) → theoretical hybrid Pearson upper bound +0.518; lift available up "
            "to +0.113. iter21 quantifies the realizable lift at N=98."
        ),
    }


def write_preregistration(seeds: list[int], cv: str, n_inner_splits: int) -> Path:
    payload = make_prereg_payload(seeds, cv, n_inner_splits)
    formula_sha = _formula_sha256(payload)
    git_sha = _git_sha()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        **payload,
        "formula_sha256": formula_sha,
        "git_sha": git_sha,
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "created_at_local": datetime.now().isoformat(),
        "timestamp": ts,
        "lockbox_rules": [
            "Architecture map (per-item) + iter5 base + Ridge meta α=1.0 are LOCKED before any "
            "hybrid CCC is computed.",
            "ONE pre-reg JSON per (cv mode) execution. --mode run requires --preregistration_file.",
            "5-fold gate: hybrid CCC ≥ iter5 5-fold + 0.025 AND hybrid std < 0.020 across 3 seeds.",
            "LOOCV lockbox: paired bootstrap CI vs iter5 LOOCV on identical N=98 with 5000 "
            "resamples; canonical update requires frac>0 ≥ 95% AND ccc > 0.5227.",
            "Borderline (5-fold Δ ∈ (0, +0.025)): report diagnostic; skip LOOCV; do NOT iterate "
            "the formula to fit the gate.",
            "If no gate passes: F56 negative writeup; canonical numbers UNCHANGED.",
        ],
    }
    pre_path = RESULTS_DIR / f"preregistration_t3_iter21_nested_{ts}.json"
    if pre_path.exists():
        raise RuntimeError(f"Pre-reg path already exists (timestamp clash): {pre_path}")
    with open(pre_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nPre-registration written: {pre_path.name}", flush=True)
    print(f"  formula_sha256 = {formula_sha[:16]}...", flush=True)
    print(f"  git_sha = {git_sha[:12]}", flush=True)
    print(f"  cv = {cv}, seeds = {seeds}, n_inner_splits = {n_inner_splits}", flush=True)
    print(f"\nNext: --mode run --preregistration_file={pre_path}", flush=True)
    return pre_path


def load_and_validate_prereg(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing pre-registration: {path}")
    with open(path) as f:
        pre = json.load(f)
    expected_payload = make_prereg_payload(
        pre["seeds"], pre["cv"], pre["n_inner_splits"]
    )
    expected_sha = _formula_sha256(expected_payload)
    if pre["formula_sha256"] != expected_sha:
        raise RuntimeError(
            f"Pre-reg formula_sha256 mismatch: {pre['formula_sha256'][:16]} vs {expected_sha[:16]}. "
            "The architecture map / hyperparameters in the script have changed since pre-registration."
        )
    return pre


# ── Run modes ────────────────────────────────────────────────────────────────


def paired_bootstrap_ci(y, pred_a, pred_b, n_boot: int = 5000, seed: int = 42) -> dict:
    n = len(y)
    rng = np.random.RandomState(seed)
    diffs = []
    for _ in range(n_boot):
        idx = rng.randint(0, n, size=n)
        diffs.append(float(ccc_fn(y[idx], pred_a[idx]) - ccc_fn(y[idx], pred_b[idx])))
    diffs = np.array(diffs)
    return {
        "ccc_a": float(ccc_fn(y, pred_a)),
        "ccc_b": float(ccc_fn(y, pred_b)),
        "delta_point": float(ccc_fn(y, pred_a) - ccc_fn(y, pred_b)),
        "delta_mean_boot": float(diffs.mean()),
        "delta_ci_low": float(np.percentile(diffs, 2.5)),
        "delta_ci_high": float(np.percentile(diffs, 97.5)),
        "frac_above_zero": float((diffs > 0).mean()),
        "n_boot": int(n_boot),
    }


def run_mode(prereg_path: Path, n_workers: int) -> None:
    pre = load_and_validate_prereg(prereg_path)
    cv = pre["cv"]
    seeds = list(pre["seeds"])
    n_inner_splits = int(pre["n_inner_splits"])
    ts = pre["timestamp"]
    print(f"\nLoaded pre-registration {prereg_path.name}", flush=True)
    print(f"  cv={cv}, seeds={seeds}, n_inner_splits={n_inner_splits}", flush=True)
    print(f"  formula_sha256 = {pre['formula_sha256'][:16]}...", flush=True)

    print("\nLoading T3-native cohort (N=98)...", flush=True)
    d = load_data_t3()
    n = len(d["sids"])
    print(f"  N = {n} PD subjects", flush=True)
    print(f"  updrs3: mean={d['updrs3'].mean():.2f}, std={d['updrs3'].std():.2f}", flush=True)
    valid_per_item = {i: int(np.isfinite(d["items"][i]).sum()) for i in range(1, 19)}
    print(f"  per-item valid counts: {valid_per_item}", flush=True)

    res = run_nested(d, seeds, cv, n_workers=n_workers, n_inner_splits=n_inner_splits)

    # ── Gate evaluation ──
    print("\n" + "=" * 80, flush=True)
    if cv == "5fold":
        print(f"=== 5-FOLD GATE (hybrid vs iter5) ===", flush=True)
        print(f"  hybrid 5-fold CCC = {res['hybrid_ccc_mean']:+.4f} ± {res['hybrid_ccc_std']:.4f}", flush=True)
        print(f"  iter5  5-fold CCC = {res['iter5_ccc_mean']:+.4f} ± {res['iter5_ccc_std']:.4f}", flush=True)
        delta = res["hybrid_ccc_mean"] - res["iter5_ccc_mean"]
        print(f"  per-seed hybrid: {[f'{x:+.4f}' for x in res['hybrid_per_seed_ccc']]}", flush=True)
        print(f"  per-seed iter5:  {[f'{x:+.4f}' for x in res['iter5_per_seed_ccc']]}", flush=True)
        print(f"  Δ (hybrid − iter5) = {delta:+.4f}", flush=True)
        gate_delta_pass = delta >= 0.025
        gate_std_pass = res["hybrid_ccc_std"] < 0.020
        gate_pass = gate_delta_pass and gate_std_pass
        if delta < 0:
            gate_msg = "FAIL (Δ < 0; F56 negative)"
        elif 0 <= delta < 0.025:
            gate_msg = f"BORDERLINE (Δ ∈ (0, +0.025); diagnostic only — do NOT iterate)"
        elif delta >= 0.025 and not gate_std_pass:
            gate_msg = f"STD-FAIL (Δ ≥ +0.025 but std={res['hybrid_ccc_std']:.4f} ≥ 0.020)"
        elif gate_pass:
            gate_msg = "PASS — proceed to LOOCV lockbox"
        else:
            gate_msg = "FAIL (unspecified)"
        print(f"  GATE: {gate_msg}", flush=True)
        # Show 3-seed-mean point too
        print(f"  hybrid 3-seed-mean CCC (informative) = {res['hybrid_3seed_ccc']:+.4f}", flush=True)
        print(f"  iter5  3-seed-mean CCC (informative) = {res['iter5_3seed_ccc']:+.4f}", flush=True)
        # Boot
        boot = paired_bootstrap_ci(
            np.asarray(res["y_updrs3"]),
            np.asarray(res["hybrid_mean_oof"]),
            np.asarray(res["iter5_mean_oof"]),
            n_boot=2000, seed=42,
        )
        print(f"  Paired bootstrap (n=2000, 3-seed-mean): Δ={boot['delta_point']:+.4f}, "
              f"95% CI [{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}], "
              f"frac>0={boot['frac_above_zero']:.3f}", flush=True)
        out_summary = {
            "mode": "5fold_gate",
            "preregistration": prereg_path.name,
            "ts": ts,
            "n_subjects": int(n),
            "seeds": list(seeds),
            "cv": cv,
            "n_inner_splits": n_inner_splits,
            "hybrid_ccc_mean": res["hybrid_ccc_mean"],
            "hybrid_ccc_std": res["hybrid_ccc_std"],
            "hybrid_per_seed_ccc": res["hybrid_per_seed_ccc"],
            "iter5_ccc_mean": res["iter5_ccc_mean"],
            "iter5_ccc_std": res["iter5_ccc_std"],
            "iter5_per_seed_ccc": res["iter5_per_seed_ccc"],
            "delta": delta,
            "gate_pass": bool(gate_pass),
            "gate_message": gate_msg,
            "hybrid_3seed_ccc": res["hybrid_3seed_ccc"],
            "iter5_3seed_ccc": res["iter5_3seed_ccc"],
            "hybrid_3seed_mae": res["hybrid_mae_3seed_mean"],
            "iter5_3seed_mae": res["iter5_mae_3seed_mean"],
            "bootstrap": boot,
            "meta_coefs_per_seed_per_fold": res["meta_coefs_per_seed_per_fold"],
            "total_elapsed_s": res["total_elapsed_s"],
        }
        out_path = RESULTS_DIR / f"iter21_5fold_gate_{ts}.json"
        with open(out_path, "w") as f:
            json.dump(out_summary, f, indent=2, default=float)
        np.save(RESULTS_DIR / f"iter21_5fold_gate_{ts}.hybrid_oof.npy", np.asarray(res["hybrid_mean_oof"]))
        np.save(RESULTS_DIR / f"iter21_5fold_gate_{ts}.iter5_oof.npy", np.asarray(res["iter5_mean_oof"]))
        np.save(RESULTS_DIR / f"iter21_5fold_gate_{ts}.sids.npy", d["sids"])
        print(f"\nWrote {out_path.name}", flush=True)
        return

    if cv == "loocv":
        print(f"=== LOOCV LOCKBOX (paired bootstrap CI vs iter5 LOOCV) ===", flush=True)
        # Compare against canonical iter5 LOOCV OOF (3-seed mean) saved at
        # results/lockbox_t3_iter5_A3_tier1_*.oof.npy (length 98) to be apples-to-apples.
        canonical_iter5 = sorted(RESULTS_DIR.glob("lockbox_t3_iter5_A3_tier1_*.oof.npy"))
        if not canonical_iter5:
            raise FileNotFoundError("Missing canonical iter5 LOOCV OOF .npy")
        iter5_oof_canonical = np.load(canonical_iter5[-1])
        # Sanity: align by SID (load canonical lockbox JSON and verify SIDs)
        canonical_json = canonical_iter5[-1].with_suffix("").with_suffix(".json")
        with open(canonical_json) as f:
            cj = json.load(f)
        sids_can = list(cj["per_subject"]["sids"])
        sids_now = list(d["sids"])
        if sids_can != sids_now:
            # Reorder canonical to match d['sids']
            sid_to_pred = dict(zip(sids_can, iter5_oof_canonical))
            iter5_oof_canonical = np.array([sid_to_pred[s] for s in sids_now])
        y = np.asarray(res["y_updrs3"])
        hybrid_mean = np.asarray(res["hybrid_mean_oof"])
        boot = paired_bootstrap_ci(y, hybrid_mean, iter5_oof_canonical, n_boot=5000, seed=42)
        print(f"  hybrid LOOCV CCC (3-seed mean) = {boot['ccc_a']:+.4f}", flush=True)
        print(f"  iter5  LOOCV CCC (canonical)   = {boot['ccc_b']:+.4f}", flush=True)
        print(f"  Δ point = {boot['delta_point']:+.4f}", flush=True)
        print(f"  95% CI  = [{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}]", flush=True)
        print(f"  frac>0  = {boot['frac_above_zero']:.3f}", flush=True)
        canonical_update = (boot["frac_above_zero"] >= 0.95) and (boot["ccc_a"] > 0.5227)
        print(f"  CANONICAL UPDATE: {'YES' if canonical_update else 'NO'}", flush=True)

        out_summary = {
            "mode": "loocv_lockbox",
            "preregistration": prereg_path.name,
            "ts": ts,
            "n_subjects": int(n),
            "seeds": list(seeds),
            "cv": cv,
            "n_inner_splits": n_inner_splits,
            "hybrid_ccc": boot["ccc_a"],
            "iter5_ccc_canonical": boot["ccc_b"],
            "hybrid_per_seed_ccc": res["hybrid_per_seed_ccc"],
            "hybrid_per_seed_std": res["hybrid_ccc_std"],
            "hybrid_3seed_mae": res["hybrid_mae_3seed_mean"],
            "bootstrap": boot,
            "is_canonical_update": bool(canonical_update),
            "meta_coefs_per_seed_per_fold": res["meta_coefs_per_seed_per_fold"],
            "total_elapsed_s": res["total_elapsed_s"],
        }
        out_path = RESULTS_DIR / f"iter21_loocv_lockbox_{ts}.json"
        with open(out_path, "w") as f:
            json.dump(out_summary, f, indent=2, default=float)
        np.save(RESULTS_DIR / f"iter21_loocv_lockbox_{ts}.hybrid_oof.npy", hybrid_mean)
        np.save(RESULTS_DIR / f"iter21_loocv_lockbox_{ts}.sids.npy", d["sids"])
        print(f"\nWrote {out_path.name}", flush=True)
        return

    raise ValueError(f"unknown cv: {cv!r}")


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["write_prereg", "run"], required=True)
    ap.add_argument("--cv", choices=["5fold", "loocv"], default=None,
                    help="(write_prereg only) outer CV mode")
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 1337, 7],
                    help="(write_prereg only) random seeds")
    ap.add_argument("--n_inner_splits", type=int, default=5,
                    help="(write_prereg only) inner CV folds for stacking")
    ap.add_argument("--preregistration_file", type=str, default=None,
                    help="(run only) path to immutable pre-reg JSON")
    ap.add_argument("--n_workers", type=int, default=int(os.getenv("ITER21_WORKERS", 11)),
                    help="(run only) ProcessPoolExecutor workers")
    args = ap.parse_args()

    ensure_dir(RESULTS_DIR)

    if args.mode == "write_prereg":
        if args.cv is None:
            raise ValueError("--cv required for write_prereg mode")
        write_preregistration(seeds=list(args.seeds), cv=args.cv, n_inner_splits=args.n_inner_splits)
        return

    if args.mode == "run":
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required for run mode")
        prereg_path = Path(args.preregistration_file)
        if not prereg_path.is_absolute():
            prereg_path = (REPO_ROOT / args.preregistration_file).resolve()
        run_mode(prereg_path, n_workers=args.n_workers)
        return


if __name__ == "__main__":
    main()
