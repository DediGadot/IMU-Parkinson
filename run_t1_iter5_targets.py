"""Iter 5 — alternative target ablation. Run tug_microscope architecture on
multiple academically-standard UPDRS-III subscores + diagnostic per-item LGB.

MDS-UPDRS Part III item mapping (verified via per_item_scores.json sub-item structure):
  1=Speech, 2=Facial expression, 3=Rigidity (5 sub), 4=Finger tap (R/L),
  5=Hand movements (R/L), 6=Pronation-supination (R/L),
  7=Toe tapping (R/L), 8=Leg agility (R/L),
  9=Arising from chair, 10=Gait, 11=Freezing of gait,
  12=Postural stability, 13=Posture, 14=Body bradykinesia,
  15=Postural tremor, 16=Kinetic tremor, 17=Rest tremor amplitude,
  18=Constancy of rest tremor

Standard published subscores tested:
  bradykinesia_subscore = {4, 5, 6, 7, 8, 9, 14}      (Goetz 2008)
  axial_subscore        = {9, 10, 11, 12, 13}          (Schrag 2007)
  axial_plus_brady      = {9, 10, 11, 12, 13, 14}      ≈ project's T1
  pigd_subscore         = {10, 11, 12}                 (Stebbins/Goetz 2013, motor part)
  tremor_subscore       = {15, 16, 17, 18}             (Stebbins/Goetz 2013)

Project-specific & diagnostic targets:
  t1                    = {9, 10, 11, 12, 13, 14}      (control, what we lockboxed)
  t1_pruned             = {10, 12, 14}                 (top-3 by per-item CCC; drop weak items)
  per_item_sum_t1       = sum of separately-trained item-LGBs for items 9-14
  per_item_diagnostic   = train per-item LGB for ALL 18 items, report per-item CCC

Output: results/iter5_<target>_t1_5split.json with per-seed metrics + per-item table where applicable.

Usage:
  python3 run_t1_iter5_targets.py --target axial_subscore
  python3 run_t1_iter5_targets.py --target per_item_diagnostic
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
    LGB_DEFAULTS, load_extra_cache,
    SEEDS, TUG_TRANSITION,
)


SUBSCORE_DEFINITIONS = {
    "t1":                   ([9, 10, 11, 12, 13, 14], "Project T1 (control); axial+truncal"),
    "axial_subscore":       ([9, 10, 11, 12, 13],     "Schrag 2007 axial: chair-rise+gait+FoG+stability+posture"),
    "axial_plus_brady":     ([9, 10, 11, 12, 13, 14], "Axial + body bradykinesia (= T1)"),
    "bradykinesia_subscore":([4, 5, 6, 7, 8, 9, 14],  "Goetz 2008 bradykinesia: tap+hand+pronation+toe+leg+chair+body"),
    "pigd_subscore":        ([10, 11, 12],            "Stebbins/Goetz 2013 PIGD: gait+FoG+stability"),
    "tremor_subscore":      [[15, 16, 17, 18],        "Stebbins/Goetz 2013 tremor: postural+kinetic+rest amp+constancy"][0:],
    "t1_pruned":            ([10, 12, 14],            "Top-3-by-CCC (gait+stability+body brady); drop 9, 11, 13"),
}
# Fix tremor (above used a list-comprehension hack; replace properly)
SUBSCORE_DEFINITIONS["tremor_subscore"] = ([15, 16, 17, 18],
                                           "Stebbins/Goetz 2013 tremor")


def load_data_with_target(target_items: list[int]) -> dict:
    """Load PD data; require all target_items to be present per subject; build target sum."""
    d = load_pd_data()
    items = d["items"]
    needed = set(target_items)
    n = len(d["sids"])
    valid = np.array([
        all(not np.isnan(items[i][k]) for i in needed) for k in range(n)
    ])
    if valid.sum() < n * 0.9:
        print(f"  WARNING: {n - valid.sum()} subjects missing some target items; keeping all and imputing zero")
    target = np.zeros(n)
    for i in target_items:
        clean = np.where(np.isnan(items[i]), 0.0, items[i])
        target = target + clean
    d["target"] = target
    d["target_items"] = target_items
    return d


def tug_microscope_predict(d: dict, target: np.ndarray, seed: int = 42) -> np.ndarray:
    """Reproduce tug_microscope arch but on a configurable target."""
    n = len(d["sids"])
    X_tug, _ = load_extra_cache(TUG_TRANSITION, d["sids"])
    df_tmp = pd.read_csv(TUG_TRANSITION)
    feat_cols_tug = [c for c in df_tmp.columns if c not in ("sid", "_spike_time_s")]
    X_tug = X_tug[:, [list(df_tmp.columns).index(c) - 1 for c in feat_cols_tug]]
    X_aug = np.hstack([d["X_v2"], X_tug])
    splits = kfold_split_stratified(target, 5, seed=seed)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, target[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, target[tr], Xte, seed)
    return oof


def variant_subscore(target_name: str, d: dict, seed: int = 42) -> dict:
    target_items = SUBSCORE_DEFINITIONS[target_name][0]
    target = np.zeros(len(d["sids"]))
    for i in target_items:
        target = target + np.where(np.isnan(d["items"][i]), 0.0, d["items"][i])
    oof = tug_microscope_predict(d, target, seed=seed)
    return {"oof": oof, "target": target, "target_items": target_items}


def variant_per_item_sum_t1(d: dict, seed: int = 42) -> dict:
    """Train each of items 9-14 separately, sum predictions = T1 prediction."""
    n = len(d["sids"])
    T1_ITEMS = [9, 10, 11, 12, 13, 14]
    oof_per_item = {}
    for item in T1_ITEMS:
        target_i = np.where(np.isnan(d["items"][item]), 0.0, d["items"][item])
        oof_per_item[item] = tug_microscope_predict(d, target_i, seed=seed)
    # Sum to get T1 prediction
    oof_sum = np.zeros(n)
    for item in T1_ITEMS:
        oof_sum = oof_sum + oof_per_item[item]
    # Per-item CCCs (vs the actual item)
    per_item_ccc = {}
    for item in T1_ITEMS:
        target_i = np.where(np.isnan(d["items"][item]), 0.0, d["items"][item])
        per_item_ccc[item] = round(float(ccc_fn(target_i, oof_per_item[item])), 4)
    return {
        "oof": oof_sum,
        "target": np.sum([np.where(np.isnan(d["items"][i]), 0.0, d["items"][i])
                          for i in T1_ITEMS], axis=0),
        "per_item_ccc": per_item_ccc,
    }


def variant_per_item_diagnostic(d: dict, seed: int = 42) -> dict:
    """Train per-item LGB for all 18 items. Report per-item CCC + cross-item OOF table."""
    n = len(d["sids"])
    per_item_ccc = {}
    per_item_oof = {}
    for item in range(1, 19):
        target_i = np.where(np.isnan(d["items"][item]), 0.0, d["items"][item])
        if target_i.std() < 1e-6:
            per_item_ccc[item] = 0.0
            continue
        oof = tug_microscope_predict(d, target_i, seed=seed)
        per_item_ccc[item] = round(float(ccc_fn(target_i, oof)), 4)
        per_item_oof[item] = oof
    # Construct a synthetic T1 prediction = sum of items 9-14 OOF
    T1_ITEMS = [9, 10, 11, 12, 13, 14]
    target_t1 = np.sum([np.where(np.isnan(d["items"][i]), 0.0, d["items"][i])
                        for i in T1_ITEMS], axis=0)
    if all(i in per_item_oof for i in T1_ITEMS):
        oof_t1_via_per_item = sum(per_item_oof[i] for i in T1_ITEMS)
        ccc_t1_via_per_item = round(float(ccc_fn(target_t1, oof_t1_via_per_item)), 4)
    else:
        oof_t1_via_per_item = np.full(n, target_t1.mean())
        ccc_t1_via_per_item = 0.0
    return {
        "oof": oof_t1_via_per_item,
        "target": target_t1,
        "per_item_ccc": per_item_ccc,
        "ccc_t1_via_per_item_sum": ccc_t1_via_per_item,
    }


REGISTRY = {
    "t1":                    lambda d, seed: variant_subscore("t1", d, seed),
    "axial_subscore":        lambda d, seed: variant_subscore("axial_subscore", d, seed),
    "axial_plus_brady":      lambda d, seed: variant_subscore("axial_plus_brady", d, seed),
    "bradykinesia_subscore": lambda d, seed: variant_subscore("bradykinesia_subscore", d, seed),
    "pigd_subscore":         lambda d, seed: variant_subscore("pigd_subscore", d, seed),
    "tremor_subscore":       lambda d, seed: variant_subscore("tremor_subscore", d, seed),
    "t1_pruned":             lambda d, seed: variant_subscore("t1_pruned", d, seed),
    "per_item_sum_t1":       variant_per_item_sum_t1,
    "per_item_diagnostic":   variant_per_item_diagnostic,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, choices=list(REGISTRY))
    ap.add_argument("--out_dir", default=str(RESULTS_DIR))
    args = ap.parse_args()

    fn = REGISTRY[args.target]
    print(f"[{args.target}] loading PD data...")
    t0 = time.time()
    d = load_pd_data()
    n = len(d["sids"])
    print(f"  loaded N={n} PD subjects")
    if args.target in SUBSCORE_DEFINITIONS:
        items, desc = SUBSCORE_DEFINITIONS[args.target]
        print(f"  target = sum(items {items})  // {desc}")

    per_seed = []
    cccs = []
    extras_collect = {}
    for seed in SEEDS:
        s_t0 = time.time()
        out = fn(d, seed=seed)
        oof = out["oof"]
        target = out["target"]
        m = full_metrics(target, oof, label=f"{args.target}_seed{seed}")
        m["seed"] = seed
        m["wall_s"] = round(time.time() - s_t0, 1)
        for k, v in out.items():
            if k not in ("oof", "target"):
                m[k] = v
                if k not in extras_collect:
                    extras_collect[k] = []
                extras_collect[k].append(v)
        per_seed.append(m)
        cccs.append(m["ccc"])
        print(f"  seed={seed} ccc={m['ccc']:.4f} mae={m['mae']:.3f} "
              f"slope={m['cal_slope']:.3f} ({m['wall_s']:.0f}s)")
        if "per_item_ccc" in out:
            sorted_items = sorted(out["per_item_ccc"].items(), key=lambda kv: -kv[1])
            print(f"  per-item CCC (top 5): {sorted_items[:5]}")

    # Aggregate per-item CCCs across seeds (mean)
    if "per_item_ccc" in extras_collect:
        per_item_means = {}
        for blocks in extras_collect["per_item_ccc"]:
            for k, v in blocks.items():
                per_item_means.setdefault(k, []).append(v)
        per_item_means = {k: round(float(np.mean(v)), 4) for k, v in per_item_means.items()}
        extras_collect["per_item_ccc_mean"] = per_item_means

    summary = {
        "variant": args.target, "target": args.target, "eval": "5split",
        "phase": "iter5_subscore",
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
    if "ccc_t1_via_per_item_sum" in extras_collect:
        summary["ccc_t1_via_per_item_sum_mean"] = round(
            float(np.mean(extras_collect["ccc_t1_via_per_item_sum"])), 4)

    out_path = Path(args.out_dir) / f"iter5_{args.target}_t1_5split.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"[{args.target}] DONE — ccc_mean={summary['ccc_mean']:.4f} "
          f"({len(cccs)} seeds, std={summary['ccc_std']:.4f}) → {out_path}")


if __name__ == "__main__":
    main()
