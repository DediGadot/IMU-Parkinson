"""Compose per-item LOOCV OOF predictions into subscore predictions (T1, T3, etc.).

Loads:
- All lockbox_peritem_<i>_<variant>_<ts>.json files matching --timestamp
- Computes per-item OOF arrays from the lockbox `per_seed` lists
- Sums to T1 (items 9-14), T3 (items 1-18 with severity-proxy fallback for 1-3),
  PIGD (10+11+12), axial (9-13), brady (4-8 + 9 + 14), tremor (15-18)
- For severity-proxy items 1-3: use H&Y-only ridge prediction
- Also runs Ridge meta-stack on item OOFs for T1 and T3

Output: results/peritem_composite_<ts>.json + .csv
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_per_item_v2 import load_data
from run_t1_iter4 import get_hy_features

T1_ITEMS = [9, 10, 11, 12, 13, 14]
T3_ITEMS = list(range(1, 19))
PIGD = [10, 11, 12]
AXIAL = [9, 10, 11, 12, 13]
BRADY = [4, 5, 6, 7, 8, 9, 14]
TREMOR = [15, 16, 17, 18]


def predict_severity_proxy(d, item: int, seeds=(42, 7, 123)):
    """For unobservable items 1-3: H&Y + demo ridge LOOCV. Handles NaN target."""
    y = d["items"].get(item)
    if y is None:
        return None
    y = np.asarray(y, dtype=float)
    n = len(y)
    hy_feat = get_hy_features(d["hy"])
    demo = hy_feat
    nan_mask = np.isnan(y)
    if nan_mask.all():
        return np.full(n, np.nan)
    oof_seeds = []
    for s in seeds:
        oof = np.full(n, np.nan)
        for i in range(n):
            tr = np.array([j for j in range(n) if j != i and not nan_mask[j]])
            if len(tr) < 5:
                continue
            te = np.array([i])
            r = Ridge(alpha=1.0, random_state=s)
            r.fit(demo[tr], y[tr])
            oof[te] = r.predict(demo[te])
        oof_seeds.append(oof)
    return np.nanmean(oof_seeds, axis=0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out_dir", default=str(RESULTS_DIR))
    p.add_argument("--timestamp", default="", help="filter lockbox files by timestamp; default = newest")
    args = p.parse_args()
    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)

    # Find lockbox JSONs
    pattern = str(out_dir / "lockbox_peritem_*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"No lockbox files found at {pattern}")
    if args.timestamp:
        files = [f for f in files if args.timestamp in f]
    else:
        # Pick newest timestamp by sorting filenames
        # filename: lockbox_peritem_<item>_<variant>_<ts>.json
        timestamps = set()
        for f in files:
            bn = os.path.basename(f)
            parts = bn.split("_")
            if len(parts) >= 4:
                ts = "_".join(parts[-2:]).replace(".json", "")
                timestamps.add(ts)
        if not timestamps:
            raise SystemExit("Could not parse timestamps from lockbox files")
        newest = max(timestamps)
        files = [f for f in files if newest in f]
        args.timestamp = newest
    print(f"Using timestamp: {args.timestamp}")
    print(f"Lockbox files: {len(files)}")

    print("Loading data...")
    d = load_data()
    n = len(d["sids"])
    print(f"  N = {n} subjects")

    # Per-item OOF: align to full N cohort (pad with item-mean if subject filtered)
    item_oof = {}  # item -> ndarray (n,)
    item_meta = {}
    for f in files:
        with open(f) as fp:
            j = json.load(fp)
        item = j["item"]
        oof_path = Path(f).with_suffix("").with_suffix(".oof.npy")
        if oof_path.exists():
            oof = np.load(oof_path)
            # Align to full cohort: items where subject was NaN-filtered will have shorter oof
            if len(oof) < n:
                # Find which subjects were valid for this item
                y_full = d["items"].get(item)
                if y_full is None:
                    continue
                valid_mask = ~np.isnan(np.asarray(y_full, dtype=float))
                full_oof = np.full(n, np.nan)
                full_oof[valid_mask] = oof
                # Fill missing positions with item-mean of OOF predictions
                fill_val = float(np.nanmean(full_oof))
                full_oof = np.where(np.isnan(full_oof), fill_val, full_oof)
                oof = full_oof
            item_oof[item] = oof
        item_meta[item] = {
            "variant": j["variant"],
            "loocv_ccc": j["ccc_mean"],
            "loocv_mae": j["mae_mean"],
        }

    # For severity-proxy items 1, 2, 3: ALWAYS use H&Y-ridge fallback
    for item in (1, 2, 3):
        if item in d["items"] and not np.all(np.isnan(d["items"][item])):
            print(f"  Item {item}: severity-proxy (H&Y ridge)")
            item_oof[item] = predict_severity_proxy(d, item)
            item_meta[item] = {"variant": "severity_proxy_ridge", "loocv_ccc": np.nan, "loocv_mae": np.nan}

    # Composite scoring
    composites = {}
    for name, items in [("T1", T1_ITEMS), ("T3", T3_ITEMS), ("PIGD", PIGD),
                        ("axial", AXIAL), ("brady", BRADY), ("tremor", TREMOR)]:
        # Sum of per-item OOFs
        valid = [i for i in items if i in item_oof and item_oof[i] is not None]
        if not valid:
            print(f"  {name}: no valid items, skipping")
            continue
        sum_oof = np.zeros(n)
        for i in valid:
            sum_oof += item_oof[i]
        # True target — handle NaN by using nansum + filtering subjects
        if name == "T1":
            y_true = d["t1"]
        elif name == "T3":
            arr = np.column_stack([d["items"][i] for i in items if i in d["items"]])
            y_true = np.nansum(arr, axis=1)
        else:
            arr = np.column_stack([d["items"][i] for i in valid])
            y_true = np.nansum(arr, axis=1)
        m = full_metrics(y_true, sum_oof)
        composites[f"{name}_sum"] = {**m, "items_used": valid, "n_items": len(valid)}
        # Stack via Ridge
        if len(valid) >= 2:
            X = np.column_stack([item_oof[i] for i in valid])
            # LOOCV ridge stack
            stack_oof = np.zeros(n)
            for i in range(n):
                tr = np.array([j for j in range(n) if j != i])
                te = np.array([i])
                r = Ridge(alpha=1.0)
                r.fit(X[tr], y_true[tr])
                stack_oof[te] = r.predict(X[te])
            m2 = full_metrics(y_true, stack_oof)
            composites[f"{name}_stack"] = {**m2, "items_used": valid, "n_items": len(valid)}

    # Print summary
    print("\n=== COMPOSITE SCORES ===")
    for name, m in composites.items():
        print(f"  {name}: CCC={m['ccc']:.4f} MAE={m['mae']:.3f} ({m['n_items']} items)")

    out = {
        "timestamp": args.timestamp,
        "n_subjects": int(n),
        "per_item_meta": {str(k): v for k, v in item_meta.items()},
        "composites": composites,
    }
    out_path = out_dir / f"peritem_composite_{args.timestamp}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
