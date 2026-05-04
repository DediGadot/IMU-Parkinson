"""Item 14 deep dive: 4 approaches to break the LOOCV CCC=0.454 ceiling.

CONTEXT
-------
Item 14 = MDS-UPDRS 3.14 "body bradykinesia" — examiner's *integrative* judgment of global
slowness across arising-from-chair, walking, posture, finger taps, hand movements, leg agility.
Iter6 reaches LOOCV CCC=0.4537 using v2+TUG features. Self-norm and per-item-features approaches
were null. This runner investigates 4 first-principles angles:

  1) sensor_region_ensemble  — separate LGB per anatomical region (Forehead/Trunk/LowerBack/Lower-ext/Walkway),
                                stack via Ridge meta. Proxy for "global slowness across motor contexts."
  2) item_oof_meta_stack     — Stage-1: LOOCV OOFs of items 9, 10, 11, 12, 13 from iter6 (already
                                fold-clean: leave-one-out per subject). Stage-2: Ridge meta on the
                                training-fold OOFs ↑ predicting item 14 on the test fold.
  3) shap_top100_lgb         — Train baseline LGB on V2+per_item, compute SHAP magnitudes, pick
                                top-100, retrain LGB on those.
  4) multi_sensor_energy     — Build per-subject quantile aggregations of FreeAcc/Acc magnitudes
                                across 13 sensors. Concat with V2.

USAGE
-----
  python3 run_item14_deep.py --eval 5split           # screen all 4 approaches
  python3 run_item14_deep.py --eval loocv --variant <name>   # lockbox a single variant

ARTIFACTS
---------
  results/item14_deep_<variant>_<eval>.json   per-variant metrics
  results/item14_deep_<variant>_oof.npy       OOF vector
  results/item14_deep_screen_5split.csv       screening summary

CRITICAL CONSTRAINTS (post-leakage audit)
-----------------------------------------
  - Subject-level splits via paper3_split.json (94 PD).
  - All preprocessing is fold-local (impute/select).
  - Item-OOF meta-stack uses LOOCV OOFs (each row predicted with that subject excluded).
  - 5-null gate: scrambled-label + canary-feature for any winner.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    load_pd_data, kfold_split_stratified, impute_fold,
    feature_select_fold, train_lgb,
    load_extra_cache, TUG_TRANSITION,
    SEEDS,
)

ITEM = 14
PERITEM_CACHE = REPO_ROOT / "results" / "peritem_subj_features.csv"
ITER6_TS = "20260430_182930"
ITER6_ITEMS_OOF = {it: REPO_ROOT / "results" / f"iter6_item{it}_oof_{ITER6_TS}.npy"
                   for it in [9, 10, 11, 12, 13, 14]}


def load_tug_features(sids: np.ndarray) -> np.ndarray:
    """Load TUG transition phase features (matches iter6)."""
    X_tug, _ = load_extra_cache(TUG_TRANSITION, sids)
    df_tmp = pd.read_csv(TUG_TRANSITION)
    feat_cols_tug = [c for c in df_tmp.columns if c not in ("sid", "_spike_time_s")]
    X_tug = X_tug[:, [list(df_tmp.columns).index(c) - 1 for c in feat_cols_tug]]
    return X_tug

# ── Sensor-region grouping ─────────────────────────────────────────────────────

# Anatomical buckets — partition v2 columns by sensor name in column.
# These mirror the WearGait-PD 13-sensor placement.
REGION_KEYWORDS = {
    "head_trunk": ["Forehead", "Sternum", "Xiphoid"],
    "lumbar": ["LowerBack"],
    "upper_ext": ["L_wrist", "R_wrist", "L_Wrist", "R_Wrist"],
    "lower_ext": ["L_Ankle", "R_Ankle", "L_thigh", "R_thigh", "L_shank", "R_shank",
                  "DorsalFoot", "L_DorsalFoot", "R_DorsalFoot"],
    "walkway": ["dst_", "fc_", "ev_", "k_", "ins_", "asy_", "bal_", "sts_", "trn_", "r_hp_"],
}


def split_by_region(feat_cols: list[str]) -> dict[str, list[int]]:
    """Return dict region -> column indices."""
    out: dict[str, list[int]] = {r: [] for r in REGION_KEYWORDS}
    out["other"] = []
    for i, c in enumerate(feat_cols):
        placed = False
        for region, kws in REGION_KEYWORDS.items():
            if any(kw in c for kw in kws):
                out[region].append(i)
                placed = True
                break
        if not placed:
            out["other"].append(i)
    return out


# ── Approach 1: sensor-region ensemble ────────────────────────────────────────


def variant_sensor_region_ensemble(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Train one LGB per anatomical region, blend via Ridge meta on inner OOFs.

    Per outer fold:
      - For each region with > 5 features, build a region-LGB.
      - Compute inner-OOF on training fold (3-fold stratified) → 5 columns of OOF preds.
      - Fit Ridge meta on inner-OOFs vs y_train.
      - Predict on test fold via region LGBs trained on full training fold → Ridge.predict.
    """
    y = d["items"][ITEM]
    n = len(y)
    feat_cols = d["feat_cols"]
    regions = split_by_region(feat_cols)
    # Filter regions with enough features (> 5)
    regions = {r: idx for r, idx in regions.items() if len(idx) >= 5}
    region_names = list(regions.keys())
    oof = np.zeros(n)
    rng = np.random.RandomState(seed)
    for tr, te in splits:
        # Inner 3-fold stratified on training subjects to compute meta-features
        inner_splits = kfold_split_stratified(y[tr], 3, seed=seed)
        n_tr = len(tr)
        inner_oofs = np.zeros((n_tr, len(region_names)))
        # outer test predictions per region
        test_preds = np.zeros((len(te), len(region_names)))
        for ri, rname in enumerate(region_names):
            cols = regions[rname]
            X_full = d["X_v2"][:, cols]
            X_tr_full = X_full[tr]
            X_te_full = X_full[te]
            # Inner OOF on training fold for meta-features
            for itr, ite in inner_splits:
                Xi_tr, Xi_te = impute_fold(X_tr_full[itr], X_tr_full[ite])
                k = min(300, Xi_tr.shape[1])
                Xi_tr_s, Xi_te_s, _ = feature_select_fold(Xi_tr, y[tr][itr], Xi_te, k=k, seed=seed)
                inner_oofs[ite, ri] = train_lgb(Xi_tr_s, y[tr][itr], Xi_te_s, seed)
            # Final region LGB on full training fold → predict test fold
            Xtr_imp, Xte_imp = impute_fold(X_tr_full, X_te_full)
            k = min(300, Xtr_imp.shape[1])
            Xtr_s, Xte_s, _ = feature_select_fold(Xtr_imp, y[tr], Xte_imp, k=k, seed=seed)
            test_preds[:, ri] = train_lgb(Xtr_s, y[tr], Xte_s, seed)
        # Ridge meta on inner-OOFs
        meta = Ridge(alpha=1.0, random_state=seed)
        meta.fit(inner_oofs, y[tr])
        oof[te] = meta.predict(test_preds)
    return oof


# Variant 1b: sensor-region ensemble with V2-base anchor (avoid losing global signal)


def variant_sensor_region_plus_v2_anchor(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Same as approach 1, but the meta-stack also receives a V2-baseline LGB prediction
    so the regression weights are not forced to recover full global signal from regions alone."""
    y = d["items"][ITEM]
    n = len(y)
    feat_cols = d["feat_cols"]
    regions = split_by_region(feat_cols)
    regions = {r: idx for r, idx in regions.items() if len(idx) >= 5}
    region_names = list(regions.keys())
    oof = np.zeros(n)
    for tr, te in splits:
        inner_splits = kfold_split_stratified(y[tr], 3, seed=seed)
        n_tr = len(tr)
        meta_cols = region_names + ["v2_anchor"]
        inner_oofs = np.zeros((n_tr, len(meta_cols)))
        test_preds = np.zeros((len(te), len(meta_cols)))
        # Per region
        for ri, rname in enumerate(region_names):
            cols = regions[rname]
            X_full = d["X_v2"][:, cols]
            X_tr_full = X_full[tr]
            X_te_full = X_full[te]
            for itr, ite in inner_splits:
                Xi_tr, Xi_te = impute_fold(X_tr_full[itr], X_tr_full[ite])
                k = min(300, Xi_tr.shape[1])
                Xi_tr_s, Xi_te_s, _ = feature_select_fold(Xi_tr, y[tr][itr], Xi_te, k=k, seed=seed)
                inner_oofs[ite, ri] = train_lgb(Xi_tr_s, y[tr][itr], Xi_te_s, seed)
            Xtr_imp, Xte_imp = impute_fold(X_tr_full, X_te_full)
            k = min(300, Xtr_imp.shape[1])
            Xtr_s, Xte_s, _ = feature_select_fold(Xtr_imp, y[tr], Xte_imp, k=k, seed=seed)
            test_preds[:, ri] = train_lgb(Xtr_s, y[tr], Xte_s, seed)
        # V2 anchor
        X_v2_full = d["X_v2"]
        for itr, ite in inner_splits:
            Xi_tr, Xi_te = impute_fold(X_v2_full[tr][itr], X_v2_full[tr][ite])
            Xi_tr_s, Xi_te_s, _ = feature_select_fold(Xi_tr, y[tr][itr], Xi_te, k=500, seed=seed)
            inner_oofs[ite, -1] = train_lgb(Xi_tr_s, y[tr][itr], Xi_te_s, seed)
        Xtr_imp, Xte_imp = impute_fold(X_v2_full[tr], X_v2_full[te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr_imp, y[tr], Xte_imp, k=500, seed=seed)
        test_preds[:, -1] = train_lgb(Xtr_s, y[tr], Xte_s, seed)
        # Meta
        meta = Ridge(alpha=1.0, random_state=seed)
        meta.fit(inner_oofs, y[tr])
        oof[te] = meta.predict(test_preds)
    return oof


# ── Approach 2: item-OOF meta stack ───────────────────────────────────────────


def load_iter6_item_oofs() -> dict[int, np.ndarray]:
    """Load LOOCV OOFs from iter6 lockbox for items 9–13 (item 14 is the target — exclude!)."""
    out = {}
    for it in [9, 10, 11, 12, 13]:
        p = ITER6_ITEMS_OOF[it]
        if not p.exists():
            raise FileNotFoundError(f"Missing iter6 OOF for item {it}: {p}")
        out[it] = np.load(p)
    return out


def variant_item_oof_meta_stack(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Stage-2 Ridge on LOOCV-OOF predictions of items 9, 10, 11, 12, 13 → predict item 14.

    LEAKAGE NOTE: each iter6 LOOCV OOF[i] was produced WITHOUT subject i in training, so it is
    fold-clean for subject i. Ridge trained on training-fold OOFs and predicts on test-fold OOFs.
    """
    y = d["items"][ITEM]
    item_oofs = load_iter6_item_oofs()
    # Stack as (n, 5) feature matrix
    stack_cols = sorted(item_oofs.keys())
    X_stack = np.column_stack([item_oofs[i] for i in stack_cols])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        meta = Ridge(alpha=1.0, random_state=seed)
        meta.fit(X_stack[tr], y[tr])
        oof[te] = meta.predict(X_stack[te])
    return oof


def variant_item_oof_plus_v2(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Combine item-OOF meta-stack with V2 LGB via Ridge.

    Per fold:
      - V2 LGB inner-OOF on training fold (3-fold stratified) → meta-feature.
      - Add item-9..13 OOFs as 5 more meta-features.
      - Ridge on (n_tr, 6) meta matrix → predict on test fold.
    """
    y = d["items"][ITEM]
    item_oofs = load_iter6_item_oofs()
    stack_cols = sorted(item_oofs.keys())
    X_item = np.column_stack([item_oofs[i] for i in stack_cols])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        # Inner OOF for V2 baseline
        inner_splits = kfold_split_stratified(y[tr], 3, seed=seed)
        v2_inner = np.zeros(len(tr))
        Xv2 = d["X_v2"]
        for itr, ite in inner_splits:
            Xi_tr, Xi_te = impute_fold(Xv2[tr][itr], Xv2[tr][ite])
            Xi_tr_s, Xi_te_s, _ = feature_select_fold(Xi_tr, y[tr][itr], Xi_te, k=500, seed=seed)
            v2_inner[ite] = train_lgb(Xi_tr_s, y[tr][itr], Xi_te_s, seed)
        # V2 final on full training fold → test
        Xtr_imp, Xte_imp = impute_fold(Xv2[tr], Xv2[te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr_imp, y[tr], Xte_imp, k=500, seed=seed)
        v2_test = train_lgb(Xtr_s, y[tr], Xte_s, seed)
        # Build meta features
        meta_tr = np.column_stack([X_item[tr], v2_inner])
        meta_te = np.column_stack([X_item[te], v2_test])
        meta = Ridge(alpha=1.0, random_state=seed)
        meta.fit(meta_tr, y[tr])
        oof[te] = meta.predict(meta_te)
    return oof


# ── Approach 3: SHAP-driven feature selection ─────────────────────────────────


def variant_shap_top100_lgb(d: dict, splits, seed: int = 42, top_k: int = 100) -> np.ndarray:
    """Train an LGB on V2+per_item, compute SHAP per fold, pick top-K, retrain LGB.

    Note: peritem features are loaded if cache exists.
    """
    import shap
    import lightgbm as lgb
    y = d["items"][ITEM]
    n = len(y)
    # Combined feature matrix: V2 + item-14 peritem (if available)
    parts = [d["X_v2"]]
    if "X_peritem_item14" in d:
        parts.append(d["X_peritem_item14"])
    X_full = np.hstack(parts)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_full[tr], X_full[te])
        # Stage 1: full LGB to compute SHAP magnitudes
        # Use a small/fast LGB so SHAP doesn't explode
        from run_t1_iter4 import LGB_DEFAULTS
        params = dict(LGB_DEFAULTS)
        params.update({"random_state": seed, "n_jobs": 2, "verbosity": -1})
        model = lgb.LGBMRegressor(**params)
        model.fit(Xtr, y[tr])
        # SHAP values via TreeExplainer (fast for LGB)
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(Xtr)  # (n_tr, n_features)
        # Mean abs SHAP per feature
        mag = np.abs(shap_vals).mean(axis=0)
        top_idx = np.argsort(mag)[::-1][:top_k]
        # Stage 2: retrain LGB on top-K
        Xtr_top = Xtr[:, top_idx]
        Xte_top = Xte[:, top_idx]
        oof[te] = train_lgb(Xtr_top, y[tr], Xte_top, seed)
    return oof


# ── Approach 4: multi-sensor energy quantile aggregation ──────────────────────


def build_multi_sensor_energy(d: dict) -> tuple[np.ndarray, list[str]]:
    """Build cross-sensor quantile features from V2 RMS-like columns.

    Per subject:
      - Identify all rms-like columns matching pattern *_a[xyzm]_rms (acc magnitudes per sensor)
      - Aggregate across sensors via quantiles (min, p25, p50, p75, max, std, cv)
      - Same for gyro (g[xyzm])
    """
    feat_cols = d["feat_cols"]
    # Acc magnitude RMS per sensor (look for `_am_rms` and similar)
    acc_mag_rms = [i for i, c in enumerate(feat_cols)
                   if c.endswith("_am_rms") or c.endswith("_a_rms")]
    gyr_mag_rms = [i for i, c in enumerate(feat_cols)
                   if c.endswith("_gm_rms") or c.endswith("_g_rms")]
    acc_xyz_rms = [i for i, c in enumerate(feat_cols)
                   if c.endswith("_ax_rms") or c.endswith("_ay_rms") or c.endswith("_az_rms")]
    gyr_xyz_rms = [i for i, c in enumerate(feat_cols)
                   if c.endswith("_gx_rms") or c.endswith("_gy_rms") or c.endswith("_gz_rms")]
    n = d["X_v2"].shape[0]
    out_cols: list[str] = []
    out_blocks: list[np.ndarray] = []

    def quantiles(arr: np.ndarray, name: str) -> tuple[np.ndarray, list[str]]:
        # arr: (n, n_sensors), aggregate across sensors
        if arr.shape[1] == 0:
            return np.zeros((n, 0)), []
        q = np.zeros((n, 7))
        for i in range(n):
            row = arr[i]
            valid = row[~np.isnan(row)]
            if len(valid) == 0:
                q[i] = np.nan
                continue
            q[i, 0] = np.min(valid)
            q[i, 1] = np.percentile(valid, 25)
            q[i, 2] = np.percentile(valid, 50)
            q[i, 3] = np.percentile(valid, 75)
            q[i, 4] = np.max(valid)
            q[i, 5] = np.std(valid)
            q[i, 6] = np.std(valid) / (np.abs(np.mean(valid)) + 1e-9)
        cols = [f"mse_{name}_{stat}" for stat in ["min", "p25", "p50", "p75", "max", "std", "cv"]]
        return q, cols

    for subset, name in [(acc_mag_rms, "accmag"), (gyr_mag_rms, "gyrmag"),
                          (acc_xyz_rms, "accxyz"), (gyr_xyz_rms, "gyrxyz")]:
        if subset:
            arr = d["X_v2"][:, subset]
            q, cols = quantiles(arr, name)
            out_blocks.append(q)
            out_cols.extend(cols)

    if not out_blocks:
        return np.zeros((n, 0)), []
    X_mse = np.hstack(out_blocks)
    return X_mse, out_cols


def variant_multi_sensor_energy(d: dict, splits, seed: int = 42) -> np.ndarray:
    """LGB on V2 + multi-sensor energy quantiles."""
    if "X_mse" not in d:
        d["X_mse"], d["mse_cols"] = build_multi_sensor_energy(d)
    y = d["items"][ITEM]
    n = len(y)
    if d["X_mse"].shape[1] == 0:
        # fallback: V2 baseline
        return variant_v2_baseline(d, splits, seed)
    X_aug = np.hstack([d["X_v2"], d["X_mse"]])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_multi_sensor_energy_only(d: dict, splits, seed: int = 42) -> np.ndarray:
    """LGB on multi-sensor energy quantiles ONLY (sanity check)."""
    if "X_mse" not in d:
        d["X_mse"], d["mse_cols"] = build_multi_sensor_energy(d)
    y = d["items"][ITEM]
    n = len(y)
    if d["X_mse"].shape[1] == 0:
        return np.zeros(n)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(d["X_mse"][tr], d["X_mse"][te])
        # No feature selection — already small
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


# ── Baseline reproductions ────────────────────────────────────────────────────


def variant_v2_baseline(d: dict, splits, seed: int = 42) -> np.ndarray:
    """LGB on V2, target = item 14 (sanity baseline)."""
    y = d["items"][ITEM]
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_iter6_repro(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Reproduces iter6's item-14 path: LGB on V2 + TUG transition features."""
    y = d["items"][ITEM]
    n = len(y)
    if "X_tug" not in d:
        d["X_tug"] = load_tug_features(d["sids"])
    X_aug = np.hstack([d["X_v2"], d["X_tug"]])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_iter6_plus_mse(d: dict, splits, seed: int = 42) -> np.ndarray:
    """V2 + TUG + multi-sensor energy quantiles (combines iter6 + Approach 4)."""
    if "X_tug" not in d:
        d["X_tug"] = load_tug_features(d["sids"])
    if "X_mse" not in d:
        d["X_mse"], d["mse_cols"] = build_multi_sensor_energy(d)
    y = d["items"][ITEM]
    n = len(y)
    X_aug = np.hstack([d["X_v2"], d["X_tug"], d["X_mse"]])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_iter6_shap_top100(d: dict, splits, seed: int = 42, top_k: int = 100) -> np.ndarray:
    """V2 + TUG, but post-hoc SHAP-based top-K feature selection per fold."""
    import shap
    import lightgbm as lgb
    from run_t1_iter4 import LGB_DEFAULTS
    if "X_tug" not in d:
        d["X_tug"] = load_tug_features(d["sids"])
    y = d["items"][ITEM]
    n = len(y)
    X_aug = np.hstack([d["X_v2"], d["X_tug"]])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        params = dict(LGB_DEFAULTS)
        params.update({"random_state": seed, "n_jobs": 2, "verbosity": -1})
        model = lgb.LGBMRegressor(**params)
        model.fit(Xtr, y[tr])
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(Xtr)
        mag = np.abs(shap_vals).mean(axis=0)
        top_idx = np.argsort(mag)[::-1][:top_k]
        Xtr_top = Xtr[:, top_idx]
        Xte_top = Xte[:, top_idx]
        oof[te] = train_lgb(Xtr_top, y[tr], Xte_top, seed)
    return oof


def variant_iter6_sensor_region(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Sensor-region ensemble + TUG region (added) + V2 anchor."""
    y = d["items"][ITEM]
    n = len(y)
    feat_cols = d["feat_cols"]
    if "X_tug" not in d:
        d["X_tug"] = load_tug_features(d["sids"])
    regions = split_by_region(feat_cols)
    regions = {r: idx for r, idx in regions.items() if len(idx) >= 5}
    region_names = list(regions.keys())
    oof = np.zeros(n)
    for tr, te in splits:
        inner_splits = kfold_split_stratified(y[tr], 3, seed=seed)
        n_tr = len(tr)
        meta_cols = region_names + ["tug", "v2_anchor"]
        inner_oofs = np.zeros((n_tr, len(meta_cols)))
        test_preds = np.zeros((len(te), len(meta_cols)))
        # Region LGBs
        for ri, rname in enumerate(region_names):
            cols = regions[rname]
            X_full = d["X_v2"][:, cols]
            X_tr_full, X_te_full = X_full[tr], X_full[te]
            for itr, ite in inner_splits:
                Xi_tr, Xi_te = impute_fold(X_tr_full[itr], X_tr_full[ite])
                k = min(300, Xi_tr.shape[1])
                Xi_tr_s, Xi_te_s, _ = feature_select_fold(Xi_tr, y[tr][itr], Xi_te, k=k, seed=seed)
                inner_oofs[ite, ri] = train_lgb(Xi_tr_s, y[tr][itr], Xi_te_s, seed)
            Xtr_imp, Xte_imp = impute_fold(X_tr_full, X_te_full)
            k = min(300, Xtr_imp.shape[1])
            Xtr_s, Xte_s, _ = feature_select_fold(Xtr_imp, y[tr], Xte_imp, k=k, seed=seed)
            test_preds[:, ri] = train_lgb(Xtr_s, y[tr], Xte_s, seed)
        # TUG-only LGB
        X_tug = d["X_tug"]
        X_tr_full, X_te_full = X_tug[tr], X_tug[te]
        for itr, ite in inner_splits:
            Xi_tr, Xi_te = impute_fold(X_tr_full[itr], X_tr_full[ite])
            k = min(200, Xi_tr.shape[1])
            Xi_tr_s, Xi_te_s, _ = feature_select_fold(Xi_tr, y[tr][itr], Xi_te, k=k, seed=seed)
            inner_oofs[ite, -2] = train_lgb(Xi_tr_s, y[tr][itr], Xi_te_s, seed)
        Xtr_imp, Xte_imp = impute_fold(X_tr_full, X_te_full)
        k = min(200, Xtr_imp.shape[1])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr_imp, y[tr], Xte_imp, k=k, seed=seed)
        test_preds[:, -2] = train_lgb(Xtr_s, y[tr], Xte_s, seed)
        # V2+TUG anchor (iter6 path)
        X_v2tug = np.hstack([d["X_v2"], d["X_tug"]])
        for itr, ite in inner_splits:
            Xi_tr, Xi_te = impute_fold(X_v2tug[tr][itr], X_v2tug[tr][ite])
            Xi_tr_s, Xi_te_s, _ = feature_select_fold(Xi_tr, y[tr][itr], Xi_te, k=500, seed=seed)
            inner_oofs[ite, -1] = train_lgb(Xi_tr_s, y[tr][itr], Xi_te_s, seed)
        Xtr_imp, Xte_imp = impute_fold(X_v2tug[tr], X_v2tug[te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr_imp, y[tr], Xte_imp, k=500, seed=seed)
        test_preds[:, -1] = train_lgb(Xtr_s, y[tr], Xte_s, seed)
        meta = Ridge(alpha=1.0, random_state=seed)
        meta.fit(inner_oofs, y[tr])
        oof[te] = meta.predict(test_preds)
    return oof


# ── First-principles retries (focus: build on iter6 path, not from V2 alone) ──


def variant_iter6_plus_item_oof(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Retry of Approach 2: iter6 path (V2+TUG) PLUS items 9, 10, 11, 12, 13 LOOCV OOFs as 5
    extra features. Early fusion instead of meta-stack."""
    if "X_tug" not in d:
        d["X_tug"] = load_tug_features(d["sids"])
    item_oofs = load_iter6_item_oofs()
    stack_cols = sorted(item_oofs.keys())
    X_item_oof = np.column_stack([item_oofs[i] for i in stack_cols])
    y = d["items"][ITEM]
    n = len(y)
    X_aug = np.hstack([d["X_v2"], d["X_tug"], X_item_oof])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_iter6_shap_top200(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Retry of Approach 3: SHAP top-200 (less aggressive cut)."""
    return variant_iter6_shap_top100(d, splits, seed, top_k=200)


def variant_iter6_shap_top500(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Retry of Approach 3: SHAP top-500 (matches iter6's K=500)."""
    return variant_iter6_shap_top100(d, splits, seed, top_k=500)


def variant_iter6_shap_blend(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Retry of Approach 3: blend iter6_repro + iter6_shap_top200 via simple mean.
    SHAP picks nonlinear-interaction features; LGB importance picks univariate; both have signal."""
    o1 = variant_iter6_repro(d, splits, seed)
    o2 = variant_iter6_shap_top100(d, splits, seed, top_k=200)
    return 0.5 * o1 + 0.5 * o2


def variant_gait_only_regions(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Retry of Approach 1: Drop head_trunk and upper_ext; only walkway + lumbar + lower_ext + tug.
    Item 14 = body bradykinesia is gait-driven; trunk and arms add variance not signal."""
    y = d["items"][ITEM]
    n = len(y)
    if "X_tug" not in d:
        d["X_tug"] = load_tug_features(d["sids"])
    feat_cols = d["feat_cols"]
    regions = split_by_region(feat_cols)
    keep_regions = ["lumbar", "lower_ext", "walkway"]
    regions = {r: regions[r] for r in keep_regions if r in regions and len(regions[r]) >= 5}
    region_names = list(regions.keys())
    oof = np.zeros(n)
    for tr, te in splits:
        inner_splits = kfold_split_stratified(y[tr], 3, seed=seed)
        n_tr = len(tr)
        meta_cols = region_names + ["tug", "v2_anchor"]
        inner_oofs = np.zeros((n_tr, len(meta_cols)))
        test_preds = np.zeros((len(te), len(meta_cols)))
        for ri, rname in enumerate(region_names):
            cols = regions[rname]
            X_full = d["X_v2"][:, cols]
            X_tr_full, X_te_full = X_full[tr], X_full[te]
            for itr, ite in inner_splits:
                Xi_tr, Xi_te = impute_fold(X_tr_full[itr], X_tr_full[ite])
                k = min(300, Xi_tr.shape[1])
                Xi_tr_s, Xi_te_s, _ = feature_select_fold(Xi_tr, y[tr][itr], Xi_te, k=k, seed=seed)
                inner_oofs[ite, ri] = train_lgb(Xi_tr_s, y[tr][itr], Xi_te_s, seed)
            Xtr_imp, Xte_imp = impute_fold(X_tr_full, X_te_full)
            k = min(300, Xtr_imp.shape[1])
            Xtr_s, Xte_s, _ = feature_select_fold(Xtr_imp, y[tr], Xte_imp, k=k, seed=seed)
            test_preds[:, ri] = train_lgb(Xtr_s, y[tr], Xte_s, seed)
        # TUG
        X_tug = d["X_tug"]
        X_tr_full, X_te_full = X_tug[tr], X_tug[te]
        for itr, ite in inner_splits:
            Xi_tr, Xi_te = impute_fold(X_tr_full[itr], X_tr_full[ite])
            k = min(200, Xi_tr.shape[1])
            Xi_tr_s, Xi_te_s, _ = feature_select_fold(Xi_tr, y[tr][itr], Xi_te, k=k, seed=seed)
            inner_oofs[ite, -2] = train_lgb(Xi_tr_s, y[tr][itr], Xi_te_s, seed)
        Xtr_imp, Xte_imp = impute_fold(X_tr_full, X_te_full)
        k = min(200, Xtr_imp.shape[1])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr_imp, y[tr], Xte_imp, k=k, seed=seed)
        test_preds[:, -2] = train_lgb(Xtr_s, y[tr], Xte_s, seed)
        # V2+TUG anchor
        X_v2tug = np.hstack([d["X_v2"], d["X_tug"]])
        for itr, ite in inner_splits:
            Xi_tr, Xi_te = impute_fold(X_v2tug[tr][itr], X_v2tug[tr][ite])
            Xi_tr_s, Xi_te_s, _ = feature_select_fold(Xi_tr, y[tr][itr], Xi_te, k=500, seed=seed)
            inner_oofs[ite, -1] = train_lgb(Xi_tr_s, y[tr][itr], Xi_te_s, seed)
        Xtr_imp, Xte_imp = impute_fold(X_v2tug[tr], X_v2tug[te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr_imp, y[tr], Xte_imp, k=500, seed=seed)
        test_preds[:, -1] = train_lgb(Xtr_s, y[tr], Xte_s, seed)
        meta = Ridge(alpha=1.0, random_state=seed)
        meta.fit(inner_oofs, y[tr])
        oof[te] = meta.predict(test_preds)
    return oof


def variant_iter6_cumulative_ordinal(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Codex retry: cumulative-link ordinal on V2+TUG.

    Item 14 distribution: {0: 25, 1: 46, 2: 22, 3: 1}. Class 3 has only 1 subject — collapse
    to 2+. Train two binary heads:
      h1: P(y >= 1)   (separates {0} from {1, 2, 3})
      h2: P(y >= 2)   (separates {0, 1} from {2, 3})
    Reconstruct continuous ŷ = P(y>=1) + P(y>=2). This matches the *threshold structure*
    of the rating scale better than a 4-level regression, per the cumulative-link / ordered
    logit family. Use shrinkage classifier (logistic with L2) per codex's "diffuse weak signal,
    not sparse nonlinear phenotype" prior. Per-fold feature selection.
    """
    from sklearn.linear_model import LogisticRegression
    if "X_tug" not in d:
        d["X_tug"] = load_tug_features(d["sids"])
    y = d["items"][ITEM]
    n = len(y)
    # Collapse y to ordinal {0,1,2}: clamp y>=3 to 2
    y_ord = np.clip(y, 0, 2).astype(int)
    X_aug = np.hstack([d["X_v2"], d["X_tug"]])
    oof = np.zeros(n, dtype=float)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        # Use ANOVA F-score selection driven by ordinal target (treat y_ord as continuous proxy)
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y_ord[tr].astype(float), Xte, k=300, seed=seed)
        # Standardize for logistic stability
        scaler = StandardScaler()
        Xtr_s = scaler.fit_transform(Xtr_s)
        Xte_s = scaler.transform(Xte_s)
        # h1: P(y >= 1)
        b1 = (y_ord[tr] >= 1).astype(int)
        if b1.sum() == 0 or b1.sum() == len(b1):
            p1 = np.full(len(te), b1.mean(), dtype=float)
        else:
            clf1 = LogisticRegression(C=1.0, max_iter=2000, random_state=seed)
            clf1.fit(Xtr_s, b1)
            p1 = clf1.predict_proba(Xte_s)[:, 1]
        # h2: P(y >= 2)
        b2 = (y_ord[tr] >= 2).astype(int)
        if b2.sum() == 0 or b2.sum() == len(b2):
            p2 = np.full(len(te), b2.mean(), dtype=float)
        else:
            clf2 = LogisticRegression(C=1.0, max_iter=2000, random_state=seed)
            clf2.fit(Xtr_s, b2)
            p2 = clf2.predict_proba(Xte_s)[:, 1]
        oof[te] = p1 + p2
    return oof


def variant_iter6_cumulative_ordinal_lgb(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Same cumulative ordinal but with LGB classifier heads (preserves nonlinear interactions)."""
    import lightgbm as lgb
    if "X_tug" not in d:
        d["X_tug"] = load_tug_features(d["sids"])
    y = d["items"][ITEM]
    n = len(y)
    y_ord = np.clip(y, 0, 2).astype(int)
    X_aug = np.hstack([d["X_v2"], d["X_tug"]])
    oof = np.zeros(n, dtype=float)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y_ord[tr].astype(float), Xte, k=500, seed=seed)
        # h1: P(y >= 1)
        b1 = (y_ord[tr] >= 1).astype(int)
        if b1.sum() == 0 or b1.sum() == len(b1):
            p1 = np.full(len(te), b1.mean(), dtype=float)
        else:
            clf1 = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.04, num_leaves=15,
                                       min_data_in_leaf=5, n_jobs=2,
                                       random_state=seed, verbosity=-1)
            clf1.fit(Xtr_s, b1)
            p1 = clf1.predict_proba(Xte_s)[:, 1]
        # h2: P(y >= 2)
        b2 = (y_ord[tr] >= 2).astype(int)
        if b2.sum() == 0 or b2.sum() == len(b2):
            p2 = np.full(len(te), b2.mean(), dtype=float)
        else:
            clf2 = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.04, num_leaves=15,
                                       min_data_in_leaf=5, n_jobs=2,
                                       random_state=seed, verbosity=-1)
            clf2.fit(Xtr_s, b2)
            p2 = clf2.predict_proba(Xte_s)[:, 1]
        oof[te] = p1 + p2
    return oof


def variant_iter6_cumulative_ordinal_blend(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Blend iter6_repro (regression) with cumulative_ordinal (classification) at 50/50.
    Two different objectives may capture different aspects of item 14."""
    o1 = variant_iter6_repro(d, splits, seed)
    o2 = variant_iter6_cumulative_ordinal_lgb(d, splits, seed)
    return 0.5 * o1 + 0.5 * o2


def variant_iter6_plus_mse_concat_only(d: dict, splits, seed: int = 42) -> np.ndarray:
    """Retry of Approach 4: skip k=500 selection — pass V2+TUG+MSE through LGB at native dim
    and let LGB column-sample internally (LGB defaults colsample_bytree handles this)."""
    if "X_tug" not in d:
        d["X_tug"] = load_tug_features(d["sids"])
    if "X_mse" not in d:
        d["X_mse"], d["mse_cols"] = build_multi_sensor_energy(d)
    y = d["items"][ITEM]
    n = len(y)
    X_aug = np.hstack([d["X_v2"], d["X_tug"], d["X_mse"]])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        # Looser feature selection — top-800 vs top-500
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=800, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


VARIANTS = {
    "v2_baseline": variant_v2_baseline,
    "iter6_repro": variant_iter6_repro,
    "sensor_region_ensemble": variant_sensor_region_ensemble,
    "sensor_region_plus_v2_anchor": variant_sensor_region_plus_v2_anchor,
    "item_oof_meta_stack": variant_item_oof_meta_stack,
    "item_oof_plus_v2": variant_item_oof_plus_v2,
    "shap_top100_lgb": variant_shap_top100_lgb,
    "multi_sensor_energy": variant_multi_sensor_energy,
    "multi_sensor_energy_only": variant_multi_sensor_energy_only,
    "iter6_plus_mse": variant_iter6_plus_mse,
    "iter6_shap_top100": variant_iter6_shap_top100,
    "iter6_sensor_region": variant_iter6_sensor_region,
    # Retries
    "iter6_plus_item_oof": variant_iter6_plus_item_oof,
    "iter6_shap_top200": variant_iter6_shap_top200,
    "iter6_shap_top500": variant_iter6_shap_top500,
    "iter6_shap_blend": variant_iter6_shap_blend,
    "gait_only_regions": variant_gait_only_regions,
    "iter6_plus_mse_top800": variant_iter6_plus_mse_concat_only,
    # Codex-suggested cumulative ordinal
    "iter6_cumulative_ordinal": variant_iter6_cumulative_ordinal,
    "iter6_cumulative_ordinal_lgb": variant_iter6_cumulative_ordinal_lgb,
    "iter6_cumulative_ordinal_blend": variant_iter6_cumulative_ordinal_blend,
}


# ── 5-null gate ───────────────────────────────────────────────────────────────


def run_5null_gate(d: dict, variant: str, seed: int = 42) -> dict:
    y = d["items"][ITEM]
    splits = kfold_split_stratified(y, 5, seed=seed)
    fn = VARIANTS[variant]
    null = {}
    rng = np.random.RandomState(seed)
    # 1. Scrambled-label
    y_scram = rng.permutation(y)
    d2 = {**d, "items": {**d["items"], ITEM: y_scram}}
    try:
        oof_s = fn(d2, splits, seed)
        null["scrambled_label_ccc"] = float(ccc_fn(y_scram, oof_s))
    except Exception as e:
        null["scrambled_label_error"] = str(e)
    # 2. Canary feature: append a random feature; expect no boost
    canary = rng.randn(len(y))
    Xv2_aug = np.hstack([d["X_v2"], canary[:, None]])
    feat_cols_aug = list(d["feat_cols"]) + ["canary_random"]
    d3 = {**d, "X_v2": Xv2_aug, "feat_cols": feat_cols_aug}
    try:
        oof_c = fn(d3, splits, seed)
        null["canary_feature_ccc"] = float(ccc_fn(y, oof_c))
    except Exception as e:
        null["canary_feature_error"] = str(e)
    return null


# ── Driver ────────────────────────────────────────────────────────────────────


def load_data_with_peritem() -> dict:
    """Load PD data + item-14 peritem features."""
    d = load_pd_data()
    if PERITEM_CACHE.exists():
        df_pi = pd.read_csv(PERITEM_CACHE).set_index("sid")
        cols = [c for c in df_pi.columns if c.startswith("i14_")]
        if cols:
            n = len(d["sids"])
            X_pi = np.full((n, len(cols)), np.nan)
            for i, sid in enumerate(d["sids"]):
                if sid in df_pi.index:
                    X_pi[i] = df_pi.loc[sid, cols].to_numpy(dtype=np.float64)
            d["X_peritem_item14"] = X_pi
            d["peritem_item14_cols"] = cols
            print(f"  item 14 peritem features: {len(cols)}", flush=True)
    return d


def run_variant(d: dict, variant: str, eval_kind: str, seeds=SEEDS, with_null: bool = True) -> dict:
    y = d["items"][ITEM]
    n = len(y)
    fn = VARIANTS[variant]
    if eval_kind == "5split":
        per_seed = []
        for s in seeds:
            splits = kfold_split_stratified(y, 5, seed=s)
            oof = fn(d, splits, s)
            per_seed.append(full_metrics(y, oof))
        ccc_mean = float(np.mean([m["ccc"] for m in per_seed]))
        ccc_std = float(np.std([m["ccc"] for m in per_seed]))
        mae_mean = float(np.mean([m["mae"] for m in per_seed]))
        out = {
            "variant": variant, "eval": eval_kind, "n_subjects": int(n),
            "seeds": list(seeds), "ccc_mean": ccc_mean, "ccc_std": ccc_std,
            "mae_mean": mae_mean, "per_seed": per_seed,
        }
        if with_null:
            out["null_tests"] = run_5null_gate(d, variant, seed=seeds[0])
    elif eval_kind == "loocv":
        splits = [(np.array([j for j in range(n) if j != i]), np.array([i])) for i in range(n)]
        per_seed = []
        oof_acc = np.zeros(n)
        for s in seeds:
            oof_s = fn(d, splits, s)
            per_seed.append(full_metrics(y, oof_s))
            oof_acc += oof_s
        oof_mean = oof_acc / len(seeds)
        ccc_mean = float(np.mean([m["ccc"] for m in per_seed]))
        ccc_std = float(np.std([m["ccc"] for m in per_seed]))
        mae_mean = float(np.mean([m["mae"] for m in per_seed]))
        out = {
            "variant": variant, "eval": eval_kind, "n_subjects": int(n),
            "seeds": list(seeds), "ccc_mean": ccc_mean, "ccc_std": ccc_std,
            "mae_mean": mae_mean, "per_seed": per_seed,
        }
        # Save mean OOF to disk
        oof_path = RESULTS_DIR / f"item14_deep_{variant}_oof.npy"
        np.save(oof_path, oof_mean)
        out["oof_path"] = str(oof_path)
    else:
        raise ValueError(f"unknown eval_kind {eval_kind}")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--variant", type=str, default="")
    p.add_argument("--eval", type=str, choices=["5split", "loocv"], default="5split")
    p.add_argument("--all", action="store_true", help="run all variants for the given eval kind")
    p.add_argument("--variants", type=str, default="", help="comma-separated variant list")
    p.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    p.add_argument("--out_dir", type=str, default=str(RESULTS_DIR))
    args = p.parse_args()
    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)

    print("Loading data...", flush=True)
    d = load_data_with_peritem()
    print(f"  N = {len(d['sids'])} PD, V2 = {d['X_v2'].shape[1]} features", flush=True)

    # Pre-build sensor region split for inspection
    regions = split_by_region(d["feat_cols"])
    for r, idx in regions.items():
        print(f"  region {r}: {len(idx)} cols", flush=True)

    # Pre-build multi-sensor energy
    X_mse, mse_cols = build_multi_sensor_energy(d)
    d["X_mse"] = X_mse
    d["mse_cols"] = mse_cols
    print(f"  multi-sensor energy: {X_mse.shape[1]} features", flush=True)

    if args.all or args.variants:
        results = []
        t0 = time.time()
        suffix = "_retry" if args.variants else ""
        out_csv = out_dir / f"item14_deep_screen_{args.eval}{suffix}.csv"
        out_json = out_dir / f"item14_deep_screen_{args.eval}{suffix}.json"
        if args.variants:
            variants = [v.strip() for v in args.variants.split(",") if v.strip()]
            for v in variants:
                if v not in VARIANTS:
                    raise SystemExit(f"unknown variant {v}; choices: {list(VARIANTS)}")
        else:
            variants = list(VARIANTS.keys())
        for i, v in enumerate(variants):
            t1 = time.time()
            try:
                r = run_variant(d, v, args.eval, seeds=tuple(args.seeds),
                                with_null=(args.eval == "5split"))
            except Exception as e:
                r = {"variant": v, "eval": args.eval, "error": str(e)}
            r["wall_s"] = round(time.time() - t1, 1)
            results.append(r)
            elapsed = time.time() - t0
            ccc = r.get('ccc_mean')
            ccc_str = f"{ccc:.4f}" if isinstance(ccc, (int, float)) else "ERROR"
            err = r.get('error', '')
            print(f"  [{i+1}/{len(variants)}] variant={v} ccc={ccc_str} ({r['wall_s']}s, total {elapsed:.1f}s)"
                  + (f" [{err}]" if err else ""), flush=True)
            df_out = pd.DataFrame([
                {"variant": r2["variant"], "eval": r2["eval"],
                 "ccc_mean": r2.get("ccc_mean", np.nan),
                 "ccc_std": r2.get("ccc_std", np.nan),
                 "mae_mean": r2.get("mae_mean", np.nan),
                 "scrambled_ccc": r2.get("null_tests", {}).get("scrambled_label_ccc", np.nan),
                 "canary_ccc": r2.get("null_tests", {}).get("canary_feature_ccc", np.nan),
                 "wall_s": r2.get("wall_s", np.nan),
                 "error": r2.get("error", "")}
                for r2 in results
            ])
            df_out.to_csv(out_csv, index=False)
            with open(out_json, "w") as f:
                json.dump(results, f, indent=2, default=float)
        print(f"\nWrote {out_csv} and {out_json}", flush=True)
        df_top = df_out.dropna(subset=["ccc_mean"]).sort_values("ccc_mean", ascending=False)
        print("\nLeaderboard:", flush=True)
        print(df_top.to_string(index=False), flush=True)
    else:
        if not args.variant:
            raise SystemExit("--variant required if --all not used")
        if args.variant not in VARIANTS:
            raise SystemExit(f"unknown variant {args.variant}; choices: {list(VARIANTS)}")
        r = run_variant(d, args.variant, args.eval, seeds=tuple(args.seeds),
                        with_null=(args.eval == "5split"))
        out_path = out_dir / f"item14_deep_{args.variant}_{args.eval}.json"
        with open(out_path, "w") as f:
            json.dump(r, f, indent=2, default=float)
        print(json.dumps({"variant": r["variant"], "eval": r["eval"],
                          "ccc_mean": r.get("ccc_mean")}, default=float))
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
