"""Iter 3 — T3 external signal injection. Self-contained.

Variants (run as `--variant <name>`):
  v2_plus_hy            — v2 features + H&Y stage as covariate
  v2_plus_velinc        — v2 + velinc CSV features (cached on remote)
  v2_plus_velinc_hy     — v2 + velinc + H&Y
  hy_only               — Ridge on H&Y alone (lower-bound)
  hy_residual           — predict T3 = HY-base + IMU-residual
  site_mixed_effects    — fixed-effect site indicator + per-site centering
  obs_subscore_aux      — multi-target T3 + obs_subscore as auxiliary; weight share
  ensemble_iter2_hy     — Ridge stack of best iter 2 OOF + H&Y
  best_stack_full       — Ridge meta on {iter2_subscore_shrink_aug, iter2_per_item_sum, v2+H&Y, velinc} OOF

Output: results/iter3_<variant>_t3_5split.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
# reuse iter2 helpers
from run_t3_iter2 import (
    load_data, impute_fold, feature_select_fold, train_lgb,
    kfold_split, T1_ITEMS, T3_ALL_ITEMS, NON_T1_ITEMS,
    site_of, is_pd, LGB_DEFAULTS,
)

ensure_dir(RESULTS_DIR)
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 6)))
SEEDS = [42, 1337, 7]
V2_FEATURES = RESULTS_DIR / "ablation_v3_features.csv"
VELINC_CACHE = RESULTS_DIR / "velinc_features.csv"


def load_full_pd_data():
    """Load PD subjects with v2 features + H&Y + obs_subscore + per-item."""
    df = pd.read_csv(V2_FEATURES)
    excluded = {"sid", "updrs3", "obs_subscore", "hy"}
    feat_cols = [c for c in df.columns
                 if c not in excluded and not any(c.startswith(p) for p in ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_"))]
    pd_mask = df["sid"].apply(is_pd)
    pd_df = df[pd_mask].reset_index(drop=True)
    sids = pd_df["sid"].to_numpy()
    X = pd_df[feat_cols].to_numpy(dtype=np.float64)
    y_t3 = pd_df["updrs3"].astype(float).to_numpy()
    hy = pd.to_numeric(pd_df["hy"], errors="coerce").to_numpy()
    obs = pd.to_numeric(pd_df.get("obs_subscore", pd.Series([np.nan]*len(pd_df))), errors="coerce").to_numpy()
    return sids, X, feat_cols, y_t3, hy, obs


def load_velinc():
    if not VELINC_CACHE.exists():
        return None
    df = pd.read_csv(VELINC_CACHE)
    return df


def get_hy_features(hy_arr):
    """Bin H&Y into one-hot + linear feature."""
    hy_clean = np.where(np.isnan(hy_arr), 0.0, hy_arr)
    one_hot = np.zeros((len(hy_arr), 5))
    bins = [(-0.1, 1.5, 0), (1.5, 2.0, 1), (2.0, 2.5, 2), (2.5, 3.0, 3), (3.0, 5.0, 4)]
    for lo, hi, idx in bins:
        mask = (hy_arr > lo) & (hy_arr <= hi)
        one_hot[mask, idx] = 1.0
    return np.column_stack([hy_clean.reshape(-1, 1), one_hot])


def variant_v2_plus_hy(sids, X, fc, y_t3, hy, obs, seed=42):
    n = len(sids)
    hy_feat = get_hy_features(hy)
    X_aug = np.column_stack([X, hy_feat])
    splits = kfold_split(n, 5, seed=seed)
    preds = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_t3[tr], Xte, k=500, seed=seed)
        preds[te] = train_lgb(Xtr, y_t3[tr], Xte, seed)
    return preds


def variant_v2_plus_velinc(sids, X, fc, y_t3, hy, obs, seed=42):
    df_velinc = load_velinc()
    if df_velinc is None:
        return None
    velinc_cols = [c for c in df_velinc.columns if c not in ("sid", "updrs3")]
    sid_to_velinc = {row["sid"]: row[velinc_cols].to_numpy(dtype=np.float64) for _, row in df_velinc.iterrows()}
    velinc_X = np.array([sid_to_velinc.get(s, np.zeros(len(velinc_cols))) for s in sids])
    X_aug = np.column_stack([X, velinc_X])
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    preds = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_t3[tr], Xte, k=500, seed=seed)
        preds[te] = train_lgb(Xtr, y_t3[tr], Xte, seed)
    return preds


def variant_v2_plus_velinc_hy(sids, X, fc, y_t3, hy, obs, seed=42):
    df_velinc = load_velinc()
    if df_velinc is None:
        return None
    velinc_cols = [c for c in df_velinc.columns if c not in ("sid", "updrs3")]
    sid_to_velinc = {row["sid"]: row[velinc_cols].to_numpy(dtype=np.float64) for _, row in df_velinc.iterrows()}
    velinc_X = np.array([sid_to_velinc.get(s, np.zeros(len(velinc_cols))) for s in sids])
    hy_feat = get_hy_features(hy)
    X_aug = np.column_stack([X, velinc_X, hy_feat])
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    preds = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_t3[tr], Xte, k=500, seed=seed)
        preds[te] = train_lgb(Xtr, y_t3[tr], Xte, seed)
    return preds


def variant_hy_only(sids, X, fc, y_t3, hy, obs, seed=42):
    hy_feat = get_hy_features(hy)
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    preds = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0)
        ridge.fit(hy_feat[tr], y_t3[tr])
        preds[te] = ridge.predict(hy_feat[te])
    return preds


def variant_hy_residual(sids, X, fc, y_t3, hy, obs, seed=42):
    """Predict T3 = HY-base (Ridge) + IMU-residual (LGB on residual)."""
    hy_feat = get_hy_features(hy)
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    preds = np.zeros(n)
    for tr, te in splits:
        # HY base
        ridge = Ridge(alpha=1.0)
        ridge.fit(hy_feat[tr], y_t3[tr])
        hy_pred_tr = ridge.predict(hy_feat[tr])
        hy_pred_te = ridge.predict(hy_feat[te])
        residual_tr = y_t3[tr] - hy_pred_tr
        # IMU-residual
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        imu_res_pred = train_lgb(Xtr, residual_tr, Xte, seed)
        preds[te] = hy_pred_te + imu_res_pred
    return preds


def variant_site_mixed_effects(sids, X, fc, y_t3, hy, obs, seed=42):
    """Per-site centering: subtract train-fold per-site mean, predict residual; add back per-site test mean."""
    n = len(sids)
    sites = np.array([site_of(s) for s in sids])
    splits = kfold_split(n, 5, seed=seed)
    preds = np.zeros(n)
    for tr, te in splits:
        # Per-site mean of T3 in training
        site_means = {}
        for site in ["NLS", "WPD"]:
            mask = sites[tr] == site
            if mask.sum() > 0:
                site_means[site] = float(y_t3[tr][mask].mean())
            else:
                site_means[site] = float(y_t3[tr].mean())
        # Compute residuals
        y_train_residual = y_t3[tr] - np.array([site_means[s] for s in sites[tr]])
        # Train LGB on residual
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_train_residual, Xte, k=500, seed=seed)
        residual_pred = train_lgb(Xtr, y_train_residual, Xte, seed)
        # Add back test-site mean
        preds[te] = residual_pred + np.array([site_means[s] for s in sites[te]])
    return preds


def variant_obs_subscore_aux(sids, X, fc, y_t3, hy, obs, seed=42):
    """Multi-target: predict T3 and obs_subscore (item 9-14 sum) jointly via stacking.

    First train two separate LGBs (T3 + obs); average their T3 forecasts.
    """
    n = len(sids)
    splits = kfold_split(n, 5, seed=seed)
    preds = np.zeros(n)
    if np.all(np.isnan(obs)):
        return None
    obs_clean = np.where(np.isnan(obs), 0.0, obs)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_t3[tr], Xte, k=500, seed=seed)
        # Direct T3
        t3_pred = train_lgb(Xtr, y_t3[tr], Xte, seed)
        # Obs prediction
        obs_pred = train_lgb(Xtr, obs_clean[tr], Xte, seed)
        # Map obs_pred to T3 via train-fold linear regression
        obs_train_pred = train_lgb(Xtr, obs_clean[tr], Xtr, seed)
        coef = np.polyfit(obs_train_pred, y_t3[tr], 1)
        t3_from_obs = np.polyval(coef, obs_pred)
        preds[te] = 0.6 * t3_pred + 0.4 * t3_from_obs  # blend
    return preds


def variant_ensemble_iter2_hy(sids, X, fc, y_t3, hy, obs, seed=42):
    """Stack: take iter2 best variant OOF preds + H&Y → Ridge meta.

    Reads iter2 OOF preds from saved JSONs. Falls back to recomputing if missing.
    """
    n = len(sids)
    # Try to load iter2 best variant OOFs
    iter2_files = ["iter2_subscore_shrink_aug_t3_5split.json",
                   "iter2_per_item_sum_t3_5split.json",
                   "iter2_item_stack_ridge_t3_5split.json",
                   "iter2_v2_only_5split.json"]
    base_preds = []
    for fname in iter2_files:
        p = RESULTS_DIR / fname
        if p.exists():
            with open(p) as f:
                d = json.load(f)
            # iter2 saves mean preds across seeds in pred_mean only — rerun base_lgb if no per-seed preds
            # Easier: just rerun the variant once for this seed
            pass
    # Fallback: recompute the 3 most promising via inline calls
    from run_t3_iter2 import (
        variant_subscore_shrink_aug, variant_per_item_sum, variant_item_stack_ridge
    )
    items = {i: np.zeros(n) for i in T3_ALL_ITEMS}
    # need item arrays
    from run_t3_iter2 import load_data as load_data_iter2
    sids2, X2, _, y2, items_full = load_data_iter2(include_hc=False)
    # Verify same sids
    if not np.array_equal(sids2, sids):
        items_full = {i: np.zeros(n) for i in T3_ALL_ITEMS}
    items_use = items_full
    p1_out = variant_subscore_shrink_aug(sids, X, y_t3, items_use, seed=seed)
    p2_out = variant_per_item_sum(sids, X, y_t3, items_use, seed=seed)
    p2 = p2_out[0] if isinstance(p2_out, tuple) else p2_out
    p3 = variant_item_stack_ridge(sids, X, y_t3, items_use, seed=seed)
    hy_feat = get_hy_features(hy)
    Z = np.column_stack([p1_out, p2, p3, hy_feat])
    splits = kfold_split(n, 5, seed=seed)
    preds = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0)
        ridge.fit(Z[tr], y_t3[tr])
        preds[te] = ridge.predict(Z[te])
    return preds


def variant_best_stack_full(sids, X, fc, y_t3, hy, obs, seed=42):
    """Full stack: iter 2/3 winners + H&Y + velinc + base_lgb."""
    n = len(sids)
    base = []
    # base 1: per-item sum (iter2)
    from run_t3_iter2 import (
        load_data as load_data_iter2, variant_per_item_sum, variant_subscore_shrink_aug,
        variant_base_lgb
    )
    sids2, X2, _, y2, items_full = load_data_iter2(include_hc=False)
    if not np.array_equal(sids2, sids):
        # fall back: regenerate items via per_item_scores load
        items_full = {i: np.zeros(n) for i in T3_ALL_ITEMS}
    p1 = variant_per_item_sum(sids, X, y_t3, items_full, seed=seed)[0]
    p2 = variant_subscore_shrink_aug(sids, X, y_t3, items_full, seed=seed)
    p3 = variant_v2_plus_hy(sids, X, fc, y_t3, hy, obs, seed=seed)
    p4 = variant_base_lgb(sids, X, y_t3, items_full, seed=seed)
    p5 = variant_v2_plus_velinc(sids, X, fc, y_t3, hy, obs, seed=seed)
    if p5 is None:
        p5 = p4
    hy_feat = get_hy_features(hy)
    Z_components = [p1, p2, p3, p4, p5]
    Z = np.column_stack(Z_components + [hy_feat])
    splits = kfold_split(n, 5, seed=seed)
    preds = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0)
        ridge.fit(Z[tr], y_t3[tr])
        preds[te] = ridge.predict(Z[te])
    return preds


VARIANTS = {
    "v2_plus_hy":          variant_v2_plus_hy,
    "v2_plus_velinc":      variant_v2_plus_velinc,
    "v2_plus_velinc_hy":   variant_v2_plus_velinc_hy,
    "hy_only":             variant_hy_only,
    "hy_residual":         variant_hy_residual,
    "site_mixed_effects":  variant_site_mixed_effects,
    "obs_subscore_aux":    variant_obs_subscore_aux,
    "ensemble_iter2_hy":   variant_ensemble_iter2_hy,
    "best_stack_full":     variant_best_stack_full,
}


def run_variant(name: str, n_seeds: int = 3):
    print(f"=== iter3 / {name} ({n_seeds} seeds) ===")
    sids, X, fc, y_t3, hy, obs = load_full_pd_data()
    print(f"  loaded {len(sids)} PD subjects, {X.shape[1]} v2 features")
    print(f"  HY non-null: {np.sum(~np.isnan(hy))}/{len(hy)}, obs non-null: {np.sum(~np.isnan(obs))}/{len(obs)}")
    fn = VARIANTS[name]
    all_preds = []
    for seed in SEEDS[:n_seeds]:
        t0 = time.time()
        preds = fn(sids, X, fc, y_t3, hy, obs, seed=seed)
        if preds is None:
            print(f"  seed {seed}: skipped")
            continue
        c = ccc_fn(y_t3, preds)
        m = mae_fn(y_t3, preds)
        r = pearson_r(y_t3, preds)
        print(f"  seed {seed}: CCC={c:.4f}, MAE={m:.3f}, r={r:.3f}, took {time.time()-t0:.1f}s")
        all_preds.append((seed, preds))
    if not all_preds:
        return None
    seed_results = [{"seed": s, "ccc": float(ccc_fn(y_t3, p)), "mae": float(mae_fn(y_t3, p)),
                     "r": float(pearson_r(y_t3, p)), "pred_std": float(p.std()), "true_std": float(y_t3.std())}
                    for s, p in all_preds]
    cccs = [s["ccc"] for s in seed_results]
    mean_preds = np.mean(np.column_stack([p for _, p in all_preds]), axis=1)
    summary = full_metrics(y_t3, mean_preds, label=name)
    summary.update({
        "variant": name,
        "ccc_mean_across_seeds": float(np.mean(cccs)),
        "ccc_std_across_seeds": float(np.std(cccs)),
        "per_seed": seed_results,
        "n": int(len(sids)),
        "target": "t3",
        "eval_mode": "5split",
        "iter": 3,
    })
    out_path = RESULTS_DIR / f"iter3_{name}_t3_5split.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"  → wrote {out_path}")
    print(f"  CCC across {len(cccs)} seeds: {np.mean(cccs):.4f} ± {np.std(cccs):.4f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--variant", default="all")
    p.add_argument("--seeds", type=int, default=3)
    args = p.parse_args()
    if args.variant == "all":
        names = list(VARIANTS.keys())
    else:
        names = [v.strip() for v in args.variant.split(",")]
    for name in names:
        if name not in VARIANTS:
            print(f"UNKNOWN variant: {name}")
            continue
        try:
            run_variant(name, n_seeds=args.seeds)
        except Exception as e:
            import traceback
            traceback.print_exc()
            with open(RESULTS_DIR / f"iter3_{name}_t3_5split.json", "w") as f:
                json.dump({"error": str(e), "variant": name, "tb": traceback.format_exc()}, f, indent=2)


if __name__ == "__main__":
    main()
