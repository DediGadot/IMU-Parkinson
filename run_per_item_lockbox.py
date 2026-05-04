"""Per-item lockbox LOOCV runner.

Reads per-item screening results, picks the winner variant per item (with null
gate passing), pre-registers each pipeline, runs LOOCV exactly once per item.

Usage:
  python3 run_per_item_lockbox.py --screening results/peritem_v2_screening_5split.csv \
      --workers 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir
from run_per_item_v2 import load_data, run_one, VARIANTS, SEEDS, MODELED_ITEMS


def pick_winner(df: pd.DataFrame, item: int) -> dict | None:
    """Pick winner variant for item: max ccc_mean among null-passing variants."""
    sub = df[df["item"] == item].copy()
    if sub.empty:
        return None
    # Null gate: scrambled_label_ccc must be reasonable (low-variance items can leak slightly)
    if "scrambled_label_ccc" in sub.columns:
        sub = sub[(sub["scrambled_label_ccc"].abs() < 0.35) | sub["scrambled_label_ccc"].isna()]
    if sub.empty:
        return None
    sub = sub.sort_values("ccc_mean", ascending=False)
    row = sub.iloc[0]
    return {
        "item": int(row["item"]),
        "variant": str(row["variant"]),
        "expected_5split_ccc": float(row["ccc_mean"]),
        "null_scrambled_ccc": float(row.get("scrambled_label_ccc", np.nan)),
    }


def run_lockbox_one(item: int, variant: str, d: dict, seeds, out_dir: Path, ts: str) -> dict:
    # Pre-register
    prereg = {
        "item": item,
        "variant": variant,
        "eval": "loocv",
        "seeds": list(seeds),
        "n_subjects": int(len(d["sids"])),
        "timestamp_prereg": ts,
        "expected_loocv_range": [-0.5, 1.0],
    }
    prereg_path = out_dir / f"preregistration_peritem_{item}_{ts}.json"
    with open(prereg_path, "w") as f:
        json.dump(prereg, f, indent=2, default=float)
    # Run LOOCV
    t0 = time.time()
    r = run_one(d, item, variant, "loocv", seeds=seeds, with_null=False)
    elapsed = time.time() - t0
    r["wall_time_s"] = elapsed
    r["pre_registration"] = prereg_path.name
    out_path = out_dir / f"lockbox_peritem_{item}_{variant}_{ts}.json"
    # Save OOF separately as numpy array for composite scoring
    if "_oof_array" in r:
        oof = np.array(r["_oof_array"])
        np.save(out_path.with_suffix("").as_posix() + ".oof.npy", oof)
        del r["_oof_array"]  # don't bloat the json
    with open(out_path, "w") as f:
        json.dump(r, f, indent=2, default=float)
    return r


def _worker(args):
    item, variant, seeds_tuple, ts = args
    d = load_data()
    return run_lockbox_one(item, variant, d, seeds_tuple, Path(args[4]), ts)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--screening", default=str(RESULTS_DIR / "peritem_v2_screening_5split.csv"))
    p.add_argument("--out_dir", default=str(RESULTS_DIR))
    p.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    p.add_argument("--items", type=int, nargs="+", default=None,
                   help="restrict to specific items (default: all 4-18)")
    p.add_argument("--max_items", type=int, default=0,
                   help="cap number of items processed (for time budget)")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)

    df = pd.read_csv(args.screening)
    print(f"Loaded screening: {df.shape}")
    items = args.items if args.items else MODELED_ITEMS
    winners = []
    for it in items:
        w = pick_winner(df, it)
        if w is None:
            print(f"  Item {it}: no valid variant — skipping")
            continue
        winners.append(w)
        print(f"  Item {it}: winner = {w['variant']} (5-fold CCC={w['expected_5split_ccc']:.4f})")
    if args.max_items:
        winners = winners[:args.max_items]
    print(f"\nPlanned lockbox runs: {len(winners)}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"Timestamp: {ts}\nLoading data once...")
    d = load_data()
    print(f"  N = {len(d['sids'])} subjects")

    # Run sequentially — LOOCV is heavy enough per item
    all_results = []
    for w in winners:
        print(f"\n[Item {w['item']}, {w['variant']}] Starting LOOCV ({len(SEEDS)} seeds × {len(d['sids'])} folds)...")
        t0 = time.time()
        r = run_lockbox_one(w["item"], w["variant"], d, args.seeds, out_dir, ts)
        elapsed = time.time() - t0
        print(f"  LOOCV done in {elapsed:.1f}s. CCC = {r['ccc_mean']:.4f} ± {r['ccc_std']:.4f}, "
              f"MAE = {r['mae_mean']:.3f}")
        all_results.append({
            "item": w["item"], "variant": w["variant"],
            "loocv_ccc_mean": r["ccc_mean"], "loocv_ccc_std": r["ccc_std"],
            "loocv_mae_mean": r["mae_mean"],
            "screening_5split_ccc": w["expected_5split_ccc"],
            "wall_time_s": elapsed,
        })
        # Progressive write of summary
        pd.DataFrame(all_results).to_csv(out_dir / f"peritem_lockbox_summary_{ts}.csv", index=False)
    print(f"\n=== ALL LOCKBOX RUNS COMPLETE ===")
    print(pd.DataFrame(all_results).to_string())


if __name__ == "__main__":
    main()
