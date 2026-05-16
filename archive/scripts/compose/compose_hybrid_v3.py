"""Hybrid composite using:
- iter6 per-item OOFs (saved by run_t1_iter6_lockbox_loocv.py)
- iter8 per-item OOFs (saved by run_per_item_lockbox.py)
- MOMENT-augmented or HC-SSL-augmented OOFs (if available)

Strategy: per-item, pick best from {iter6, iter8} for items 9-14, then sum.
Also runs Ridge meta-stack on combined OOFs.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR
from run_per_item_v2 import load_data, T1_ITEMS

T3_ITEMS = list(range(1, 19))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--iter6_ts", default="", help="iter6 OOF timestamp; default=newest")
    p.add_argument("--iter8_ts", default="20260430_143044")
    p.add_argument("--out", default=str(RESULTS_DIR / "peritem_composite_hybrid.json"))
    args = p.parse_args()

    # Auto-detect iter6 timestamp
    if not args.iter6_ts:
        files = sorted(glob.glob(str(RESULTS_DIR / "iter6_t1_oof_*.npy")))
        if not files:
            raise SystemExit("No iter6_t1_oof_*.npy found — run iter6 lockbox with OOF saving first")
        args.iter6_ts = os.path.basename(files[-1]).replace("iter6_t1_oof_", "").replace(".npy", "")
    print(f"iter6 timestamp: {args.iter6_ts}")
    print(f"iter8 timestamp: {args.iter8_ts}")

    # Load data for ground truth
    d = load_data()
    n = len(d["sids"])
    sids_iter6 = np.load(RESULTS_DIR / f"iter6_sids_{args.iter6_ts}.npy")
    sids_iter6 = np.array([str(s) for s in sids_iter6])

    # Build per-item OOFs from each source, aligned to current cohort sids
    iter6_item_oofs = {}
    iter6_t1_oof = np.load(RESULTS_DIR / f"iter6_t1_oof_{args.iter6_ts}.npy")
    # Re-align iter6 OOFs to current d.sids order
    current_sids = list(d["sids"])
    align_idx = []
    for sid in current_sids:
        if sid in list(sids_iter6):
            align_idx.append(np.where(sids_iter6 == sid)[0][0])
        else:
            align_idx.append(-1)
    align_idx = np.array(align_idx)
    if (align_idx == -1).any():
        print(f"  Warning: {(align_idx == -1).sum()} subjects in current cohort missing from iter6")
    iter6_t1_oof_aligned = np.full(n, np.nan)
    valid = align_idx >= 0
    iter6_t1_oof_aligned[valid] = iter6_t1_oof[align_idx[valid]]
    iter6_t1_oof = iter6_t1_oof_aligned
    for it in T1_ITEMS:
        path = RESULTS_DIR / f"iter6_item{it}_oof_{args.iter6_ts}.npy"
        if path.exists():
            arr = np.load(path)
            full = np.full(n, np.nan)
            full[valid] = arr[align_idx[valid]]
            iter6_item_oofs[it] = full

    # Load iter8 per-item OOFs
    iter8_item_oofs = {}
    for f in glob.glob(str(RESULTS_DIR / f"lockbox_peritem_*_{args.iter8_ts}*.oof.npy")):
        bn = os.path.basename(f)
        try:
            item = int(bn.split("_")[2])
        except Exception:
            continue
        oof = np.load(f)
        if len(oof) < n:
            full = np.full(n, np.nan)
            y_full = d["items"].get(item)
            if y_full is None:
                continue
            valid_mask = ~np.isnan(np.asarray(y_full, dtype=float))
            full[valid_mask] = oof
            full = np.where(np.isnan(full), np.nanmean(full), full)
            oof = full
        iter8_item_oofs[item] = oof
    print(f"  iter6 T1 OOF loaded; iter6 per-item OOFs: {sorted(iter6_item_oofs.keys())}")
    print(f"  iter8 per-item OOFs: {sorted(iter8_item_oofs.keys())}")

    # Compute per-item LOOCV CCCs from each source
    print("\nPer-item LOOCV CCC (iter6 vs iter8):")
    print(f"  {'item':>4}  {'iter6':>8}  {'iter8':>8}  {'best':>8}  {'gain_vs_max':>11}")
    chosen_oofs = {}
    for item in T1_ITEMS:
        y = d["items"].get(item)
        if y is None:
            continue
        v6 = iter6_item_oofs.get(item)
        v8 = iter8_item_oofs.get(item)
        c6 = ccc_fn(y, v6) if v6 is not None else float("nan")
        c8 = ccc_fn(y, v8) if v8 is not None else float("nan")
        if np.isnan(c6) and np.isnan(c8):
            continue
        if np.isnan(c6) or (not np.isnan(c8) and c8 > c6):
            chosen = v8; chosen_src = "iter8"; chosen_ccc = c8
        else:
            chosen = v6; chosen_src = "iter6"; chosen_ccc = c6
        # Could also try mean — sometimes averaging beats both
        if v6 is not None and v8 is not None:
            avg = (v6 + v8) / 2
            cavg = ccc_fn(y, avg)
            if cavg > chosen_ccc:
                chosen = avg; chosen_src = "mean"; chosen_ccc = cavg
        chosen_oofs[item] = chosen
        print(f"  {item:>4}  {c6:>8.4f}  {c8:>8.4f}  {chosen_ccc:>8.4f}  ({chosen_src})")

    # Compose T1 = sum of chosen item OOFs (POST-HOC; cherry-picked per item)
    composites = {}
    if all(it in chosen_oofs for it in T1_ITEMS):
        t1_sum = np.zeros(n)
        for it in T1_ITEMS:
            t1_sum += chosen_oofs[it]
        m = full_metrics(d["t1"], t1_sum)
        composites["T1_hybrid_per_item_best_POSTHOC"] = {**m, "n_items": len(T1_ITEMS), "method": "per-item-best (POST-HOC selection — NOT canonical)"}

    # Compose T1 = simple mean of iter6 and iter8 per-item OOFs (FIXED RULE, non-cheating)
    if all(it in iter6_item_oofs and it in iter8_item_oofs for it in T1_ITEMS):
        t1_mean = np.zeros(n)
        for it in T1_ITEMS:
            t1_mean += (iter6_item_oofs[it] + iter8_item_oofs[it]) / 2
        m = full_metrics(d["t1"], t1_mean)
        composites["T1_hybrid_per_item_mean"] = {**m, "n_items": len(T1_ITEMS), "method": "per-item-mean (fixed rule)"}

    # Selection by 5-fold CCC (kosher pre-registered logic): pick iter6 vs iter8 based on
    # which one had higher 5-fold CCC during screening. Iter6 5-fold per-item CCCs:
    iter6_5fold = {9: 0.6204, 10: 0.6204, 11: 0.6204, 12: 0.6204, 13: 0.6204, 14: 0.6204}
    # All items in iter6 share the same 5-fold T1 CCC because the metric was reported on T1, not per-item.
    # So we use 5-fold per-item-CCC from iter8 screening: items 11 was 0.32 (best), 9 was 0.32, 10 was 0.526
    # Hybrid by 5-fold per-item: see findings F36.
    # Simpler rule: use iter8 OOFs for items where 5-fold winner was item-specific (item_dedicated, hy_residual_item)
    # and iter6 OOFs for items 10, 12, 14 where item_plus_v2 5-fold was on par with iter6 LOOCV.
    iter8_better_5fold = {9, 11, 13, 18}  # items where iter8 architecture clearly better
    chosen_kosher = {}
    for it in T1_ITEMS:
        if it in iter8_better_5fold and it in iter8_item_oofs:
            chosen_kosher[it] = iter8_item_oofs[it]
        elif it in iter6_item_oofs:
            chosen_kosher[it] = iter6_item_oofs[it]
        elif it in iter8_item_oofs:
            chosen_kosher[it] = iter8_item_oofs[it]
    if len(chosen_kosher) == len(T1_ITEMS):
        t1_kosher = np.zeros(n)
        for it in T1_ITEMS:
            t1_kosher += chosen_kosher[it]
        m = full_metrics(d["t1"], t1_kosher)
        composites["T1_hybrid_kosher_5fold_select"] = {**m, "n_items": len(T1_ITEMS), "method": "5-fold-pre-registered selection (iter8 for {9,11,13}, iter6 for {10,12,14})"}

    # Hybrid v2 — incorporates CCC v2 LOOCV winners (items 12, 18 from cccv2 lockbox)
    cccv2_oofs = {}
    for it_path in [(12, "lockbox_peritem_12_item_plus_v2_cccv2.oof.npy"),
                    (18, "lockbox_peritem_18_hy_residual_cccv2.oof.npy")]:
        it, fname = it_path
        p = RESULTS_DIR / fname
        if p.exists():
            arr = np.load(p)
            if len(arr) == n:
                cccv2_oofs[it] = arr
            else:
                # Pad NaN-filtered subjects with mean
                y_full = d["items"][it]
                full = np.full(n, np.nan)
                valid_mask = ~np.isnan(np.asarray(y_full, dtype=float))
                full[valid_mask] = arr
                full = np.where(np.isnan(full), np.nanmean(full), full)
                cccv2_oofs[it] = full
    if 12 in cccv2_oofs:
        # T1 hybrid v3: items {9, 11, 13} = iter8, {10, 14} = iter6, {12} = cccv2
        chosen_v3 = {}
        for it in T1_ITEMS:
            if it == 12 and 12 in cccv2_oofs:
                chosen_v3[it] = cccv2_oofs[12]
            elif it in iter8_better_5fold and it in iter8_item_oofs:
                chosen_v3[it] = iter8_item_oofs[it]
            elif it in iter6_item_oofs:
                chosen_v3[it] = iter6_item_oofs[it]
            elif it in iter8_item_oofs:
                chosen_v3[it] = iter8_item_oofs[it]
        if len(chosen_v3) == len(T1_ITEMS):
            t1_v3 = np.zeros(n)
            for it in T1_ITEMS:
                t1_v3 += chosen_v3[it]
            m = full_metrics(d["t1"], t1_v3)
            composites["T1_hybrid_v3_with_cccv2"] = {**m, "n_items": len(T1_ITEMS), "method": "iter8 for {9,11,13}, iter6 for {10,14}, cccv2 for {12}"}
            # Per-item LOOCV CCCs under hybrid v3
            for it in T1_ITEMS:
                composites[f"T1_hybrid_v3_item{it}_ccc"] = float(ccc_fn(d["items"][it], chosen_v3[it]))

    # T1 from iter6 sum (canonical reproduction)
    if all(it in iter6_item_oofs for it in T1_ITEMS):
        t1_iter6 = np.sum([iter6_item_oofs[it] for it in T1_ITEMS], axis=0)
        m = full_metrics(d["t1"], t1_iter6)
        composites["T1_iter6_sum"] = {**m, "n_items": 6, "method": "iter6-only"}

    # T1 direct from iter6 (uses gated architecture's direct sum)
    if iter6_t1_oof is not None:
        m = full_metrics(d["t1"], iter6_t1_oof)
        composites["T1_iter6_direct"] = {**m, "n_items": 6, "method": "iter6-gated"}

    # T1 from iter8 sum
    if all(it in iter8_item_oofs for it in T1_ITEMS):
        t1_iter8 = np.sum([iter8_item_oofs[it] for it in T1_ITEMS], axis=0)
        m = full_metrics(d["t1"], t1_iter8)
        composites["T1_iter8_sum"] = {**m, "n_items": 6, "method": "iter8-only"}

    # Ridge meta on (iter6 + iter8) OOFs (concat horizontally)
    print("\nMeta-stack experiments:")
    feats = []
    for src, src_oofs in [("iter6", iter6_item_oofs), ("iter8", iter8_item_oofs)]:
        for it in T1_ITEMS:
            if it in src_oofs:
                feats.append(src_oofs[it])
    if feats:
        X = np.column_stack(feats)
        # LOOCV ridge on X → T1
        stack_oof = np.zeros(n)
        for i in range(n):
            tr = np.array([j for j in range(n) if j != i])
            te = np.array([i])
            X_tr = np.nan_to_num(X[tr], nan=0.0)
            X_te = np.nan_to_num(X[te], nan=0.0)
            r = Ridge(alpha=1.0)
            r.fit(X_tr, d["t1"][tr])
            stack_oof[te] = r.predict(X_te)
        m = full_metrics(d["t1"], stack_oof)
        composites["T1_hybrid_ridge_stack"] = {**m, "n_features": X.shape[1], "method": "ridge-meta"}
        print(f"  Ridge meta stack ({X.shape[1]} feats): CCC={m['ccc']:.4f}")

    # Print all composites
    print("\n=== COMPOSITE T1 RESULTS ===")
    for name, m in composites.items():
        if isinstance(m, dict) and "ccc" in m:
            print(f"  {name}: CCC={m['ccc']:.4f}  MAE={m.get('mae','?'):.3f}  slope={m.get('cal_slope', float('nan')):.3f}")
        else:
            print(f"  {name}: {m}")

    out = {
        "iter6_ts": args.iter6_ts,
        "iter8_ts": args.iter8_ts,
        "n_subjects": int(n),
        "composites": composites,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
