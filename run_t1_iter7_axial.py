"""Iter 7 — gated per-item T1 with axial-orientation rescue for item 13 (posture).

Architecture (per CLI consensus + iter6 diagnostic):
  Item 9  (chair-rise)         → hy_residual on V2 (= iter6)
  Item 10 (gait)               → V2 + TUG (= iter6)
  Item 11 (FoG)                → hy_residual on V2 + axial (NEW: trunk pitch oscillation)
  Item 12 (postural stability) → V2 + TUG (= iter6)
  Item 13 (posture)            → hy_residual on AXIAL ONLY (NEW: drops V2 — magnitude failed)
  Item 14 (body bradykinesia)  → V2 + TUG (= iter6)

Variants:
  iter6_baseline         — reproduces gated_per_item_t1_w_hy (control)
  iter7_axial_item13     — only item 13 routed to hy_residual on axial-only
  iter7_axial_full       — items 11 + 13 use axial; item 14 adds axial as auxiliary
  iter7_axial_v2_concat  — items 11/13/14 use V2 + axial concat; iter6 base unchanged

Output: results/iter7_<variant>_t1_5split.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    load_pd_data, kfold_split_stratified, impute_fold,
    feature_select_fold, train_lgb,
    get_hy_features, LGB_DEFAULTS,
    SEEDS, TUG_TRANSITION,
    load_extra_cache,
)

T1_ITEMS = [9, 10, 11, 12, 13, 14]
GAIN_ITEMS_TUG = [10, 12, 14]   # Items where TUG features HELP
HURT_ITEMS_TUG = [9, 11, 13]    # Items where TUG features HURT

AXIAL_CACHE = RESULTS_DIR / "axial_orientation_features.csv"


def load_tug_features(sids):
    X_tug, _ = load_extra_cache(TUG_TRANSITION, sids)
    df_tmp = pd.read_csv(TUG_TRANSITION)
    feat_cols_tug = [c for c in df_tmp.columns if c not in ("sid", "_spike_time_s")]
    X_tug = X_tug[:, [list(df_tmp.columns).index(c) - 1 for c in feat_cols_tug]]
    return X_tug


def load_axial_features(sids):
    if not AXIAL_CACHE.exists():
        raise FileNotFoundError(f"Required axial cache missing: {AXIAL_CACHE}. Run cache_axial_orientation_features.py first.")
    X_ax, _ = load_extra_cache(AXIAL_CACHE, sids)
    df_tmp = pd.read_csv(AXIAL_CACHE)
    feat_cols_ax = [c for c in df_tmp.columns if c != "sid"]
    X_ax = X_ax[:, [list(df_tmp.columns).index(c) - 1 for c in feat_cols_ax]]
    return X_ax


def predict_item_v2_only(d, item_target, splits, seed=42):
    n = len(d["sids"])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr, Xte, _ = feature_select_fold(Xtr, item_target[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, item_target[tr], Xte, seed)
    return oof


def predict_item_v2_plus_tug(d, X_tug, item_target, splits, seed=42):
    n = len(d["sids"])
    X_aug = np.hstack([d["X_v2"], X_tug])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, item_target[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, item_target[tr], Xte, seed)
    return oof


def predict_item_hy_residual(d, X_v2_or_axial, item_target, splits, seed=42, k=500):
    """Stage-1 Ridge on H&Y → Stage-2 LGB on (caller's choice of V2 / axial / V2+axial) residual."""
    n = len(d["sids"])
    hy_feat = get_hy_features(d["hy"])
    oof = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], item_target[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = item_target[tr] - s1_tr
        Xtr, Xte = impute_fold(X_v2_or_axial[tr], X_v2_or_axial[te])
        if Xtr.shape[1] > k:
            Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=k, seed=seed)
        s2_te = train_lgb(Xtr, resid_tr, Xte, seed)
        oof[te] = s1_te + s2_te
    return oof


def variant_iter6_baseline(d, seed=42):
    """Reproduce gated_per_item_t1_w_hy as control."""
    n = len(d["sids"])
    X_tug = load_tug_features(d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_per: dict[int, np.ndarray] = {}
    for it in T1_ITEMS:
        target = np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
        if it in GAIN_ITEMS_TUG:
            oof_per[it] = predict_item_v2_plus_tug(d, X_tug, target, splits, seed=seed)
        else:
            oof_per[it] = predict_item_hy_residual(d, d["X_v2"], target, splits, seed=seed)
    oof_sum = sum(oof_per[it] for it in T1_ITEMS)
    return {
        "oof": oof_sum,
        "per_item_ccc": _per_item_cccs(d, oof_per),
    }


def variant_iter7_axial_item13(d, seed=42):
    """Only item 13 uses axial-only hy_residual; everything else iter6."""
    n = len(d["sids"])
    X_tug = load_tug_features(d["sids"])
    X_ax = load_axial_features(d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_per: dict[int, np.ndarray] = {}
    for it in T1_ITEMS:
        target = np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
        if it == 13:
            # Axial-only Stage-2 (drop V2 entirely for posture)
            oof_per[it] = predict_item_hy_residual(d, X_ax, target, splits, seed=seed, k=200)
        elif it in GAIN_ITEMS_TUG:
            oof_per[it] = predict_item_v2_plus_tug(d, X_tug, target, splits, seed=seed)
        else:
            oof_per[it] = predict_item_hy_residual(d, d["X_v2"], target, splits, seed=seed)
    oof_sum = sum(oof_per[it] for it in T1_ITEMS)
    return {
        "oof": oof_sum,
        "per_item_ccc": _per_item_cccs(d, oof_per),
        "axial_for_item": [13],
    }


def variant_iter7_axial_full(d, seed=42):
    """Item 13 → axial-only hy_residual; item 11 → V2+axial hy_residual; item 14 → V2+TUG+axial."""
    n = len(d["sids"])
    X_tug = load_tug_features(d["sids"])
    X_ax = load_axial_features(d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_per: dict[int, np.ndarray] = {}
    for it in T1_ITEMS:
        target = np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
        if it == 13:
            oof_per[it] = predict_item_hy_residual(d, X_ax, target, splits, seed=seed, k=200)
        elif it == 11:
            X_v2_ax = np.hstack([d["X_v2"], X_ax])
            oof_per[it] = predict_item_hy_residual(d, X_v2_ax, target, splits, seed=seed, k=500)
        elif it == 14:
            X_aug = np.hstack([d["X_v2"], X_tug, X_ax])
            oof = np.zeros(n)
            for tr, te in splits:
                Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
                Xtr, Xte, _ = feature_select_fold(Xtr, target[tr], Xte, k=500, seed=seed)
                oof[te] = train_lgb(Xtr, target[tr], Xte, seed)
            oof_per[it] = oof
        elif it in GAIN_ITEMS_TUG:
            oof_per[it] = predict_item_v2_plus_tug(d, X_tug, target, splits, seed=seed)
        else:
            oof_per[it] = predict_item_hy_residual(d, d["X_v2"], target, splits, seed=seed)
    oof_sum = sum(oof_per[it] for it in T1_ITEMS)
    return {
        "oof": oof_sum,
        "per_item_ccc": _per_item_cccs(d, oof_per),
        "axial_for_item": [13, 11, 14],
    }


def variant_iter7_axial_v2_concat(d, seed=42):
    """Add axial as concat to V2 for ALL items in HURT pool (items 9, 11, 13)."""
    n = len(d["sids"])
    X_tug = load_tug_features(d["sids"])
    X_ax = load_axial_features(d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_per: dict[int, np.ndarray] = {}
    for it in T1_ITEMS:
        target = np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
        if it in HURT_ITEMS_TUG:
            X_v2_ax = np.hstack([d["X_v2"], X_ax])
            oof_per[it] = predict_item_hy_residual(d, X_v2_ax, target, splits, seed=seed, k=500)
        else:
            oof_per[it] = predict_item_v2_plus_tug(d, X_tug, target, splits, seed=seed)
    oof_sum = sum(oof_per[it] for it in T1_ITEMS)
    return {
        "oof": oof_sum,
        "per_item_ccc": _per_item_cccs(d, oof_per),
        "axial_for_item": HURT_ITEMS_TUG,
    }


def _per_item_cccs(d, oof_per):
    out = {}
    for it, vec in oof_per.items():
        target = np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
        out[it] = round(float(ccc_fn(target, vec)), 4)
    return out


REGISTRY = {
    "iter6_baseline": variant_iter6_baseline,
    "iter7_axial_item13": variant_iter7_axial_item13,
    "iter7_axial_full": variant_iter7_axial_full,
    "iter7_axial_v2_concat": variant_iter7_axial_v2_concat,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=list(REGISTRY))
    ap.add_argument("--out_dir", default=str(RESULTS_DIR))
    args = ap.parse_args()

    fn = REGISTRY[args.variant]
    print(f"[{args.variant}] loading PD data...")
    t0 = time.time()
    d = load_pd_data()
    n = len(d["sids"])
    print(f"  N={n} PD subjects")

    per_seed = []
    cccs = []
    extras_collect: dict[str, list] = {}
    for seed in SEEDS:
        s_t0 = time.time()
        out = fn(d, seed=seed)
        oof = out["oof"]
        m = full_metrics(d["t1"], oof, label=f"{args.variant}_seed{seed}")
        m["seed"] = seed
        m["wall_s"] = round(time.time() - s_t0, 1)
        for k, v in out.items():
            if k != "oof":
                m[k] = v
                extras_collect.setdefault(k, []).append(v)
        per_seed.append(m)
        cccs.append(m["ccc"])
        print(f"  seed={seed} ccc={m['ccc']:.4f} mae={m['mae']:.3f} ({m['wall_s']:.0f}s)")
        if "per_item_ccc" in out:
            print(f"  per-item: {out['per_item_ccc']}")

    if "per_item_ccc" in extras_collect:
        per_item_means = {}
        for blocks in extras_collect["per_item_ccc"]:
            for k, v in blocks.items():
                per_item_means.setdefault(int(k) if isinstance(k, str) else k, []).append(v)
        per_item_means = {k: round(float(np.mean(v)), 4) for k, v in per_item_means.items()}
        extras_collect["per_item_ccc_mean"] = per_item_means

    summary = {
        "variant": args.variant, "target": "t1", "eval": "5split",
        "phase": "iter7_axial",
        "n_subjects": n,
        "ccc_mean": round(float(np.mean(cccs)), 4),
        "ccc_std": round(float(np.std(cccs)), 4),
        "ccc_per_seed": [round(c, 4) for c in cccs],
        "mae_mean": round(float(np.mean([m["mae"] for m in per_seed])), 4),
        "slope_mean": round(float(np.mean([m["cal_slope"] for m in per_seed])), 4),
        "per_seed": per_seed,
        "wall_total_s": round(time.time() - t0, 1),
    }
    if "per_item_ccc_mean" in extras_collect:
        summary["per_item_ccc_mean"] = extras_collect["per_item_ccc_mean"]
    if "axial_for_item" in extras_collect:
        summary["axial_for_item"] = extras_collect["axial_for_item"][0]

    out_path = Path(args.out_dir) / f"iter7_{args.variant}_t1_5split.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"[{args.variant}] DONE — ccc_mean={summary['ccc_mean']:.4f} ± {summary['ccc_std']:.4f} → {out_path}")


if __name__ == "__main__":
    main()
