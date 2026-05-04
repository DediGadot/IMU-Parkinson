"""Iter 6 — gated per-item T1 prediction. Tests whether item-specific feature
gating (TUG features only for items where they help) outperforms uniform feature use.

Hypothesis: TUG transition features HELP items {10, 12, 14, 7, 8} but HURT items
{9, 11, 13}. Train per-item LGBs with feature blocks chosen by where the gate falls.

Variants (--variant):
  per_item_v2_only_sum_t1     — control: per-item LGB on V2 only, sum 6 items 9-14
  per_item_tug_for_all_t1     — control: per-item LGB on V2+TUG, sum 6 items (= iter5 per_item_sum_t1)
  gated_per_item_t1           — items {10, 12, 14} use V2+TUG; items {9, 11, 13} use V2 only — sum
  gated_per_item_t1_w_hy      — same as gated, but items {9, 11, 13} use hy_residual (Stage1 H&Y + LGB on v2)
  gated_extended_5item        — predict items {10, 12, 14, 7, 8} via V2+TUG, sum (NEW target T_strong)
  gated_meta_ridge            — per-item OOF (gated by feature block) → Ridge meta on T1

Output: results/iter6_<variant>_t1_5split.json
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
GAIN_ITEMS = [10, 12, 14]  # TUG features HELP these (per iter 5 diagnostic)
HURT_ITEMS = [9, 11, 13]   # TUG features HURT these (per iter 5 diagnostic)
EXTENDED_STRONG = [10, 12, 14, 7, 8]  # all items where TUG helps significantly


def load_tug_features(sids):
    X_tug, _ = load_extra_cache(TUG_TRANSITION, sids)
    df_tmp = pd.read_csv(TUG_TRANSITION)
    feat_cols_tug = [c for c in df_tmp.columns if c not in ("sid", "_spike_time_s")]
    X_tug = X_tug[:, [list(df_tmp.columns).index(c) - 1 for c in feat_cols_tug]]
    return X_tug


def predict_item_v2_only(d, item_target, splits, seed=42):
    """LGB on V2 only for a single item target."""
    n = len(d["sids"])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr, Xte, _ = feature_select_fold(Xtr, item_target[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, item_target[tr], Xte, seed)
    return oof


def predict_item_v2_plus_tug(d, X_tug, item_target, splits, seed=42):
    """LGB on V2 + TUG features for a single item target."""
    n = len(d["sids"])
    X_aug = np.hstack([d["X_v2"], X_tug])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, item_target[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, item_target[tr], Xte, seed)
    return oof


def predict_item_hy_residual(d, item_target, splits, seed=42):
    """Stage-1 Ridge on H&Y → Stage-2 LGB on V2 residual for a single item."""
    n = len(d["sids"])
    hy_feat = get_hy_features(d["hy"])
    oof = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], item_target[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = item_target[tr] - s1_tr
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        s2_te = train_lgb(Xtr, resid_tr, Xte, seed)
        oof[te] = s1_te + s2_te
    return oof


# ── Variants ──────────────────────────────────────────────────────────────────


def variant_per_item_v2_only_sum_t1(d, seed=42):
    """All 6 T1 items predicted via V2-only per-item, then summed."""
    n = len(d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_per = {}
    for it in T1_ITEMS:
        target = np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
        oof_per[it] = predict_item_v2_only(d, target, splits, seed=seed)
    oof_sum = sum(oof_per[it] for it in T1_ITEMS)
    return {
        "oof": oof_sum,
        "per_item_ccc": {it: round(float(ccc_fn(
            np.where(np.isnan(d["items"][it]), 0.0, d["items"][it]),
            oof_per[it])), 4) for it in T1_ITEMS},
    }


def variant_per_item_tug_for_all_t1(d, seed=42):
    """Reproduce iter5 per_item_sum_t1: all items use V2+TUG."""
    n = len(d["sids"])
    X_tug = load_tug_features(d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_per = {}
    for it in T1_ITEMS:
        target = np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
        oof_per[it] = predict_item_v2_plus_tug(d, X_tug, target, splits, seed=seed)
    oof_sum = sum(oof_per[it] for it in T1_ITEMS)
    return {
        "oof": oof_sum,
        "per_item_ccc": {it: round(float(ccc_fn(
            np.where(np.isnan(d["items"][it]), 0.0, d["items"][it]),
            oof_per[it])), 4) for it in T1_ITEMS},
    }


def variant_gated_per_item_t1(d, seed=42):
    """Items 10/12/14 use V2+TUG; items 9/11/13 use V2 only. Sum."""
    n = len(d["sids"])
    X_tug = load_tug_features(d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_per = {}
    for it in T1_ITEMS:
        target = np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
        if it in GAIN_ITEMS:
            oof_per[it] = predict_item_v2_plus_tug(d, X_tug, target, splits, seed=seed)
        elif it in HURT_ITEMS:
            oof_per[it] = predict_item_v2_only(d, target, splits, seed=seed)
        else:
            raise ValueError(f"Item {it} not in gain or hurt list")
    oof_sum = sum(oof_per[it] for it in T1_ITEMS)
    return {
        "oof": oof_sum,
        "per_item_ccc": {it: round(float(ccc_fn(
            np.where(np.isnan(d["items"][it]), 0.0, d["items"][it]),
            oof_per[it])), 4) for it in T1_ITEMS},
        "gating_scheme": {"v2+tug": GAIN_ITEMS, "v2_only": HURT_ITEMS},
    }


def variant_gated_per_item_t1_w_hy(d, seed=42):
    """Items 10/12/14 use V2+TUG; items 9/11/13 use hy_residual."""
    n = len(d["sids"])
    X_tug = load_tug_features(d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_per = {}
    for it in T1_ITEMS:
        target = np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
        if it in GAIN_ITEMS:
            oof_per[it] = predict_item_v2_plus_tug(d, X_tug, target, splits, seed=seed)
        elif it in HURT_ITEMS:
            oof_per[it] = predict_item_hy_residual(d, target, splits, seed=seed)
        else:
            raise ValueError(f"Item {it} not in gain or hurt list")
    oof_sum = sum(oof_per[it] for it in T1_ITEMS)
    return {
        "oof": oof_sum,
        "per_item_ccc": {it: round(float(ccc_fn(
            np.where(np.isnan(d["items"][it]), 0.0, d["items"][it]),
            oof_per[it])), 4) for it in T1_ITEMS},
        "gating_scheme": {"v2+tug": GAIN_ITEMS, "hy_residual": HURT_ITEMS},
    }


def variant_gated_meta_ridge(d, seed=42):
    """Train per-item gated OOF preds, then Ridge meta on T1 (instead of naive sum)."""
    n = len(d["sids"])
    X_tug = load_tug_features(d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_per = {}
    for it in T1_ITEMS:
        target = np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
        if it in GAIN_ITEMS:
            oof_per[it] = predict_item_v2_plus_tug(d, X_tug, target, splits, seed=seed)
        else:
            oof_per[it] = predict_item_v2_only(d, target, splits, seed=seed)
    stack = np.column_stack([oof_per[it] for it in T1_ITEMS])
    oof = np.zeros(n)
    for tr, te in splits:
        meta = Ridge(alpha=1.0, random_state=seed)
        meta.fit(stack[tr], d["t1"][tr])
        oof[te] = meta.predict(stack[te])
    return {
        "oof": oof,
        "per_item_ccc": {it: round(float(ccc_fn(
            np.where(np.isnan(d["items"][it]), 0.0, d["items"][it]),
            oof_per[it])), 4) for it in T1_ITEMS},
    }


def variant_gated_extended_5item(d, seed=42):
    """Predict items {10, 12, 14, 7, 8} via V2+TUG, sum = T_strong (a new target)."""
    n = len(d["sids"])
    X_tug = load_tug_features(d["sids"])
    target = np.zeros(n)
    for it in EXTENDED_STRONG:
        target = target + np.where(np.isnan(d["items"][it]), 0.0, d["items"][it])
    splits = kfold_split_stratified(target, 5, seed=seed)
    X_aug = np.hstack([d["X_v2"], X_tug])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, target[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, target[tr], Xte, seed)
    return {"oof": oof, "target_used": target,
            "extended_items": EXTENDED_STRONG}


REGISTRY = {
    "per_item_v2_only_sum_t1":  variant_per_item_v2_only_sum_t1,
    "per_item_tug_for_all_t1":  variant_per_item_tug_for_all_t1,
    "gated_per_item_t1":        variant_gated_per_item_t1,
    "gated_per_item_t1_w_hy":   variant_gated_per_item_t1_w_hy,
    "gated_meta_ridge":         variant_gated_meta_ridge,
    "gated_extended_5item":     variant_gated_extended_5item,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=list(REGISTRY))
    ap.add_argument("--out_dir", default=str(RESULTS_DIR))
    args = ap.parse_args()

    fn = REGISTRY[args.variant]
    print(f"[{args.variant}] loading data...")
    t0 = time.time()
    d = load_pd_data()
    n = len(d["sids"])
    print(f"  N={n} PD subjects, T1 mean={d['t1'].mean():.2f}")

    per_seed = []
    cccs = []
    extras_collect = {}
    for seed in SEEDS:
        s_t0 = time.time()
        out = fn(d, seed=seed)
        oof = out["oof"]
        if "target_used" in out:
            target = out["target_used"]
        else:
            target = d["t1"]
        m = full_metrics(target, oof, label=f"{args.variant}_seed{seed}")
        m["seed"] = seed
        m["wall_s"] = round(time.time() - s_t0, 1)
        for k, v in out.items():
            if k not in ("oof", "target_used"):
                m[k] = v
                extras_collect.setdefault(k, []).append(v)
        per_seed.append(m)
        cccs.append(m["ccc"])
        print(f"  seed={seed} ccc={m['ccc']:.4f} mae={m['mae']:.3f} ({m['wall_s']:.0f}s)")
        if "per_item_ccc" in out:
            print(f"  per-item: {out['per_item_ccc']}")

    # Aggregate per-item across seeds
    if "per_item_ccc" in extras_collect:
        per_item_means = {}
        for blocks in extras_collect["per_item_ccc"]:
            for k, v in blocks.items():
                per_item_means.setdefault(int(k) if isinstance(k, str) else k, []).append(v)
        per_item_means = {k: round(float(np.mean(v)), 4) for k, v in per_item_means.items()}
        extras_collect["per_item_ccc_mean"] = per_item_means

    summary = {
        "variant": args.variant, "target": "t1", "eval": "5split",
        "phase": "iter6_gated",
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
    if "gating_scheme" in extras_collect:
        summary["gating_scheme"] = extras_collect["gating_scheme"][0]
    if "extended_items" in extras_collect:
        summary["extended_items"] = extras_collect["extended_items"][0]

    out_path = Path(args.out_dir) / f"iter6_{args.variant}_t1_5split.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"[{args.variant}] DONE — ccc_mean={summary['ccc_mean']:.4f} "
          f"(±{summary['ccc_std']:.4f}) → {out_path}")


if __name__ == "__main__":
    main()
