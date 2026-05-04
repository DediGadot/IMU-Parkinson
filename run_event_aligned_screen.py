"""Event-aligned variant screening + lockbox runner for items 9 and 11.

Runs the new event-aligned variants from `run_per_item_v2.py` at 5-fold
(3-seed) on PD subjects, compares against the current lockbox baselines
(item 9 hy_residual_item LOOCV CCC = 0.4437; item 11 item_dedicated LOOCV
CCC = 0.3794), and lockbox-LOOCVs any variant beating its prior 5-fold by
>= 0.015 CCC.

Output:
  results/event_aligned_screen_<ts>.csv (5-fold table)
  results/preregistration_eventaligned_<item>_<variant>_<ts>.json
  results/lockbox_eventaligned_<item>_<variant>_<ts>.json
  results/lockbox_eventaligned_<item>_<variant>_<ts>.oof.npy
  results/event_aligned_summary_<ts>.json

Usage:
  python3 run_event_aligned_screen.py \
      --item9_variants item_plus_v2 hy_residual_item item9_event_moment item9_event_moment_hy_residual \
      --item11_variants item_dedicated hurdle_fog item11_multiscale item11_hurdle_calibrated item11_ngboost \
      --lockbox_threshold 0.015 \
      --workers 4
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir
from run_per_item_v2 import load_data, run_one, VARIANTS, SEEDS

# Prior lockbox-LOOCV baselines (from results/lockbox_peritem_*_20260430_143044.json)
PRIOR_LOOCV = {
    9: {"variant": "hy_residual_item", "ccc": 0.4437},
    11: {"variant": "item_dedicated", "ccc": 0.3794},
}


def screen_variant(d: dict, item: int, variant: str, seeds: tuple) -> dict:
    if variant not in VARIANTS:
        return {"item": item, "variant": variant, "error": "variant not registered"}
    try:
        return run_one(d, item, variant, "5split", seeds=seeds, with_null=True)
    except Exception as e:
        return {"item": item, "variant": variant, "error": str(e)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--item9_variants", nargs="+",
                   default=["item_plus_v2", "hy_residual_item",
                            "item9_event_moment", "item9_event_moment_hy_residual"])
    p.add_argument("--item11_variants", nargs="+",
                   default=["item_dedicated", "hurdle_fog",
                            "item11_multiscale", "item11_hurdle_calibrated",
                            "item11_ngboost"])
    p.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    p.add_argument("--lockbox_threshold", type=float, default=0.015,
                   help="Min Δ CCC over prior 5-fold to trigger lockbox LOOCV")
    p.add_argument("--out_dir", default=str(RESULTS_DIR))
    p.add_argument("--skip_lockbox", action="store_true")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    seeds_tuple = tuple(args.seeds)

    print(f"[{ts}] Loading data once...", flush=True)
    d = load_data()
    n = len(d["sids"])
    print(f"  N = {n} PD subjects", flush=True)
    has_event_moment = "X_item9_event_moment" in d
    has_multiscale = "X_item11_multiscale" in d
    print(f"  Event-aligned MOMENT cache: {has_event_moment}", flush=True)
    print(f"  Multiscale FoG cache:       {has_multiscale}", flush=True)

    plan = []
    for v in args.item9_variants:
        plan.append((9, v))
    for v in args.item11_variants:
        plan.append((11, v))

    print(f"\nScreening {len(plan)} (item, variant) jobs at 5-fold × {len(seeds_tuple)} seeds...", flush=True)
    rows = []
    t0 = time.time()
    for i, (item, variant) in enumerate(plan):
        print(f"  [{i+1}/{len(plan)}] item={item} variant={variant} ...", flush=True)
        t1 = time.time()
        r = screen_variant(d, item, variant, seeds_tuple)
        dt = time.time() - t1
        ccc = r.get("ccc_mean")
        ccc_str = f"{ccc:.4f}" if isinstance(ccc, (int, float)) else "ERROR"
        err = r.get("error", "")
        nulls = r.get("null_tests", {})
        scram = nulls.get("scrambled_label_ccc", np.nan)
        canary = nulls.get("canary_feature_ccc", np.nan)
        print(f"    -> ccc={ccc_str}  scram={scram}  canary={canary}  ({dt:.1f}s)"
              + (f"  [{err}]" if err else ""), flush=True)
        rows.append({
            "item": item, "variant": variant,
            "ccc_mean": ccc, "ccc_std": r.get("ccc_std"),
            "mae_mean": r.get("mae_mean"),
            "scrambled_label_ccc": nulls.get("scrambled_label_ccc"),
            "canary_feature_ccc": nulls.get("canary_feature_ccc"),
            "error": err,
            "wall_time_s": dt,
        })
        df_progress = pd.DataFrame(rows)
        df_progress.to_csv(out_dir / f"event_aligned_screen_{ts}.csv", index=False)
    print(f"\nScreening done in {time.time() - t0:.1f}s", flush=True)
    df = pd.DataFrame(rows)

    print("\n=== 5-fold screening (PD-only, N=94) ===", flush=True)
    print(df.sort_values(["item", "ccc_mean"], ascending=[True, False]).to_string(index=False), flush=True)

    # Lockbox-LOOCV: any variant strictly better than its peer-baseline by threshold
    summary = {"timestamp": ts, "screening": rows, "lockbox": []}
    if args.skip_lockbox:
        print("\n--skip_lockbox: not running LOOCV", flush=True)
    else:
        # For each item, find the 5-fold best ITEM variant and the 5-fold best NEW variant
        for item in (9, 11):
            sub = df[(df["item"] == item) & df["ccc_mean"].notna()].copy()
            if sub.empty:
                continue
            sub = sub.sort_values("ccc_mean", ascending=False)
            best_5fold_ccc = float(sub.iloc[0]["ccc_mean"])
            best_variant = str(sub.iloc[0]["variant"])
            prior = PRIOR_LOOCV.get(item)
            # Trigger lockbox if best_5fold beats prior LOOCV by threshold
            # (5-fold and LOOCV have similar magnitudes inductively at N≈94)
            should_lockbox = (prior is None) or (
                best_5fold_ccc - prior["ccc"] >= args.lockbox_threshold
            )
            print(f"\nItem {item}: best 5-fold = {best_variant} CCC={best_5fold_ccc:.4f} "
                  f"(prior LOOCV {prior['variant']}={prior['ccc']:.4f}). "
                  f"Lockbox? {should_lockbox}", flush=True)
            if not should_lockbox:
                continue
            # Pre-register and run LOOCV (single shot)
            prereg = {
                "item": item, "variant": best_variant, "eval": "loocv",
                "seeds": list(seeds_tuple), "n_subjects": int(n),
                "timestamp_prereg": ts,
                "expected_loocv_range": [-0.5, 1.0],
                "expected_5split_ccc": best_5fold_ccc,
                "prior_loocv_baseline": prior,
            }
            prereg_path = out_dir / f"preregistration_eventaligned_{item}_{best_variant}_{ts}.json"
            with open(prereg_path, "w") as f:
                json.dump(prereg, f, indent=2, default=float)
            print(f"  Pre-registered: {prereg_path.name}", flush=True)
            t1 = time.time()
            r = run_one(d, item, best_variant, "loocv", seeds=seeds_tuple, with_null=False)
            elapsed = time.time() - t1
            r["wall_time_s"] = elapsed
            r["pre_registration"] = prereg_path.name
            out_path = out_dir / f"lockbox_eventaligned_{item}_{best_variant}_{ts}.json"
            if "_oof_array" in r:
                oof = np.array(r["_oof_array"])
                np.save(str(out_path).replace(".json", ".oof.npy"), oof)
                del r["_oof_array"]
            with open(out_path, "w") as f:
                json.dump(r, f, indent=2, default=float)
            print(f"  Lockbox LOOCV done in {elapsed:.1f}s. CCC = {r['ccc_mean']:.4f} ± {r['ccc_std']:.4f}, "
                  f"MAE = {r['mae_mean']:.3f}", flush=True)
            summary["lockbox"].append({
                "item": item, "variant": best_variant,
                "loocv_ccc_mean": r["ccc_mean"], "loocv_ccc_std": r["ccc_std"],
                "loocv_mae_mean": r["mae_mean"],
                "screening_5split_ccc": best_5fold_ccc,
                "prior_loocv_baseline_ccc": prior["ccc"] if prior else None,
                "delta_loocv_vs_prior": (r["ccc_mean"] - prior["ccc"]) if prior else None,
                "wall_time_s": elapsed,
                "preregistration_file": prereg_path.name,
                "lockbox_file": out_path.name,
            })

    summary_path = out_dir / f"event_aligned_summary_{ts}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=float)
    print(f"\nWrote {summary_path}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
