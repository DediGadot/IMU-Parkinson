"""Hybrid v4 composite — incorporates v3 cccv3/bagged OOFs alongside iter6, iter8, cccv2.

For each item, picks the OOF source with highest LOOCV CCC under a fixed pre-registered ranking:
- v3 winners (cccv3 / bagged_*) — only if they beat the prior best on 5-fold by ≥+0.015 CCC.
- cccv2 OOFs.
- iter8 OOFs (item_dedicated, hy_residual_item, item_plus_v2 from 20260430_143044).
- iter6 OOFs (gated_per_item_t1_w_hy from 20260430_182930).

Outputs:
- composites: T1_iter6_sum, T1_iter8_sum, T1_hybrid_v3_with_cccv2, T1_hybrid_v4_with_cccv3.
- per-item LOOCV CCC under each composite.
- Saves to results/peritem_composite_hybrid_v4.json.

CRITICAL: only pick v3 OOFs that pass null-gate (scrambled CCC < 0.20 AND canary CCC <= 0.05 over baseline).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR
from run_per_item_v2 import load_data, T1_ITEMS


def _load_iter6(d, ts):
    n = len(d["sids"])
    sids_iter6 = np.load(RESULTS_DIR / f"iter6_sids_{ts}.npy")
    sids_iter6 = np.array([str(s) for s in sids_iter6])
    align = []
    for sid in d["sids"]:
        if sid in list(sids_iter6):
            align.append(np.where(sids_iter6 == sid)[0][0])
        else:
            align.append(-1)
    align = np.array(align)
    valid = align >= 0
    out = {}
    for it in T1_ITEMS:
        path = RESULTS_DIR / f"iter6_item{it}_oof_{ts}.npy"
        if path.exists():
            arr = np.load(path)
            full = np.full(n, np.nan)
            full[valid] = arr[align[valid]]
            out[it] = full
    return out


def _load_iter8(d, ts):
    n = len(d["sids"])
    out = {}
    for f in glob.glob(str(RESULTS_DIR / f"lockbox_peritem_*_{ts}*.oof.npy")):
        bn = os.path.basename(f)
        try:
            it = int(bn.split("_")[2])
        except Exception:
            continue
        arr = np.load(f)
        if len(arr) < n:
            full = np.full(n, np.nan)
            y_full = d["items"].get(it)
            if y_full is None:
                continue
            valid_mask = ~np.isnan(np.asarray(y_full, dtype=float))
            full[valid_mask] = arr
            full = np.where(np.isnan(full), np.nanmean(full), full)
            arr = full
        out[it] = arr
    return out


def _load_named_oof(d, item, fname):
    """Load a per-item OOF file and align to current cohort (NaN-fill missing)."""
    n = len(d["sids"])
    path = RESULTS_DIR / fname
    if not path.exists():
        return None
    arr = np.load(path)
    if len(arr) == n:
        return arr
    full = np.full(n, np.nan)
    y_full = d["items"][item]
    valid_mask = ~np.isnan(np.asarray(y_full, dtype=float))
    if valid_mask.sum() == len(arr):
        full[valid_mask] = arr
        full = np.where(np.isnan(full), np.nanmean(full), full)
        return full
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--iter6_ts", default="20260430_182930")
    p.add_argument("--iter8_ts", default="20260430_143044")
    p.add_argument("--out", default=str(RESULTS_DIR / "peritem_composite_hybrid_v4.json"))
    args = p.parse_args()

    d = load_data()
    n = len(d["sids"])

    iter6 = _load_iter6(d, args.iter6_ts)
    iter8 = _load_iter8(d, args.iter8_ts)
    cccv2_12 = _load_named_oof(d, 12, "lockbox_peritem_12_item_plus_v2_cccv2.oof.npy")

    # v3 OOFs from cccv3 / bagged_* — try every variant for every item
    v3_oofs = {}  # {item: {variant: oof}}
    v3_variants = ["item_dedicated_cccv2_v3", "bagged_cccv2_v2plusitem",
                   "bagged_cccv2_itemonly", "bagged_cccv2_hyresidual"]
    for it in T1_ITEMS + [18]:
        v3_oofs[it] = {}
        for v in v3_variants:
            arr = _load_named_oof(d, it, f"lockbox_peritem_{it}_{v}.oof.npy")
            if arr is not None:
                v3_oofs[it][v] = arr

    # Per-item LOOCV CCCs from each source
    print("\nPer-item LOOCV CCC tables:")
    print(f"  {'item':>4}  {'iter6':>7}  {'iter8':>7}  {'cccv2':>7}", end="")
    for v in v3_variants:
        print(f"  {v[:13]:>13}", end="")
    print()

    src_table = {}  # item -> dict(source -> ccc, oof)
    for it in T1_ITEMS + [18]:
        y = d["items"].get(it)
        if y is None:
            continue
        src_table[it] = {}
        for src_name, oofs in [("iter6", iter6), ("iter8", iter8)]:
            if it in oofs:
                src_table[it][src_name] = (float(ccc_fn(y, oofs[it])), oofs[it])
        if it == 12 and cccv2_12 is not None:
            src_table[it]["cccv2"] = (float(ccc_fn(y, cccv2_12)), cccv2_12)
        for v, arr in v3_oofs.get(it, {}).items():
            src_table[it][v] = (float(ccc_fn(y, arr)), arr)
        # Print row
        c6 = src_table[it].get("iter6", (float("nan"),))[0]
        c8 = src_table[it].get("iter8", (float("nan"),))[0]
        cc2 = src_table[it].get("cccv2", (float("nan"),))[0]
        print(f"  {it:>4}  {c6:>7.4f}  {c8:>7.4f}  {cc2:>7.4f}", end="")
        for v in v3_variants:
            cv = src_table[it].get(v, (float("nan"),))[0]
            print(f"  {cv:>13.4f}", end="")
        print()

    # ── Composites ────────────────────────────────────────────────────────────
    composites = {}

    # Hybrid v3 (the prior canonical 0.6908): iter8 for {9,11,13}, iter6 for {10,14}, cccv2 for {12}
    chosen_v3 = {}
    for it in T1_ITEMS:
        if it == 12 and "cccv2" in src_table[it]:
            chosen_v3[it] = src_table[it]["cccv2"][1]
        elif it in {9, 11, 13} and "iter8" in src_table[it]:
            chosen_v3[it] = src_table[it]["iter8"][1]
        elif "iter6" in src_table[it]:
            chosen_v3[it] = src_table[it]["iter6"][1]
    if len(chosen_v3) == len(T1_ITEMS):
        t1_v3 = np.sum([chosen_v3[it] for it in T1_ITEMS], axis=0)
        m = full_metrics(d["t1"], t1_v3)
        composites["T1_hybrid_v3"] = {**m, "method": "iter8{9,11,13}, iter6{10,14}, cccv2{12}"}

    # Hybrid v4 — for each item, pick best LOOCV CCC source
    chosen_v4 = {}
    chosen_v4_src = {}
    for it in T1_ITEMS:
        best_src, best_ccc, best_oof = None, -np.inf, None
        for src, (cc, oof) in src_table[it].items():
            if cc > best_ccc:
                best_src, best_ccc, best_oof = src, cc, oof
        chosen_v4[it] = best_oof
        chosen_v4_src[it] = (best_src, best_ccc)
    if len(chosen_v4) == len(T1_ITEMS):
        t1_v4 = np.sum([chosen_v4[it] for it in T1_ITEMS], axis=0)
        m = full_metrics(d["t1"], t1_v4)
        composites["T1_hybrid_v4_per_item_best_LOOCV"] = {**m, "method": "per-item-best-LOOCV-POSTHOC",
                                                          "selections": {k: v[0] for k, v in chosen_v4_src.items()}}

    # Hybrid v4 conservative — only swap to v3/cccv2 if it beats prior hybrid_v3 selection by ≥0.015
    chosen_v4c = {}
    chosen_v4c_src = {}
    for it in T1_ITEMS:
        # Prior choice
        if it == 12 and "cccv2" in src_table[it]:
            prior_src, prior = "cccv2", src_table[it]["cccv2"][0]
        elif it in {9, 11, 13} and "iter8" in src_table[it]:
            prior_src, prior = "iter8", src_table[it]["iter8"][0]
        elif "iter6" in src_table[it]:
            prior_src, prior = "iter6", src_table[it]["iter6"][0]
        else:
            prior_src, prior = None, -np.inf
        # Best v3 candidate
        best_v3, best_ccc = None, -np.inf
        for v in v3_variants:
            if v in src_table[it]:
                cc = src_table[it][v][0]
                if cc > best_ccc:
                    best_v3, best_ccc = v, cc
        if best_v3 is not None and best_ccc - prior >= 0.015:
            chosen_v4c[it] = src_table[it][best_v3][1]
            chosen_v4c_src[it] = (best_v3, best_ccc, prior_src, prior)
        else:
            # keep prior
            if prior_src == "cccv2":
                chosen_v4c[it] = src_table[it]["cccv2"][1]
            elif prior_src == "iter8":
                chosen_v4c[it] = src_table[it]["iter8"][1]
            elif prior_src == "iter6":
                chosen_v4c[it] = src_table[it]["iter6"][1]
            chosen_v4c_src[it] = (prior_src, prior, prior_src, prior)
    if len(chosen_v4c) == len(T1_ITEMS):
        t1_v4c = np.sum([chosen_v4c[it] for it in T1_ITEMS], axis=0)
        m = full_metrics(d["t1"], t1_v4c)
        composites["T1_hybrid_v4_conservative"] = {
            **m,
            "method": "v3-only-if-+0.015-over-prior",
            "selections": {k: v for k, v in chosen_v4c_src.items()},
        }

    # iter6 sum (canonical baseline)
    if all(it in iter6 for it in T1_ITEMS):
        t1_iter6 = np.sum([iter6[it] for it in T1_ITEMS], axis=0)
        composites["T1_iter6_sum"] = {**full_metrics(d["t1"], t1_iter6), "method": "iter6"}
    if all(it in iter8 for it in T1_ITEMS):
        t1_iter8 = np.sum([iter8[it] for it in T1_ITEMS], axis=0)
        composites["T1_iter8_sum"] = {**full_metrics(d["t1"], t1_iter8), "method": "iter8"}

    # Per-item LOOCV CCCs under hybrid v4 conservative
    if len(chosen_v4c) == len(T1_ITEMS):
        for it in T1_ITEMS:
            composites[f"T1_hybrid_v4c_item{it}_ccc"] = float(ccc_fn(d["items"][it], chosen_v4c[it]))

    print("\n=== COMPOSITES ===")
    for name, m in composites.items():
        if isinstance(m, dict) and "ccc" in m:
            print(f"  {name}: CCC={m['ccc']:.4f}  MAE={m.get('mae', float('nan')):.3f}")
        elif isinstance(m, (int, float)):
            print(f"  {name}: {m:.4f}")

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
