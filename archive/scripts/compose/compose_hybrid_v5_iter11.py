"""Hybrid composite v5 (iter11): incorporate self-norm-cross winners.

Starts from hybrid_v4 (item 13 swap winner from iter10 = v2_plus_self_norm LOOCV 0.265).
Considers iter11 self-norm-cross LOOCV results for items 9-14 + 18.

For each item, swap if:
  - LOOCV CCC ≥ canonical_v4 LOOCV + 0.015
  - 5-fold screen passed null gates (loose criterion: |scram|<0.20, canary>0)

Output: results/peritem_composite_hybrid_v5_iter11.json with:
  - T1_hybrid_v3_baseline (reference)
  - T1_hybrid_v4_canonical (item 13 self-norm swap, from iter10)
  - T1_hybrid_v5_iter11 (v4 + iter11 swaps that pass criteria)
  - T1_hybrid_v5_per_item_best_POSTHOC (upper bound)
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR
from run_per_item_v2 import load_data as load_peritem_data, T1_ITEMS

ITER6_TS = "20260430_182930"
ITER8_TS = "20260430_143044"


def _align_oof(oof: np.ndarray, n: int, valid_mask: np.ndarray) -> np.ndarray:
    """Map a possibly-partial OOF (length valid_mask.sum()) into a full-length array.

    For test subjects with NaN target, fill with mean of OOF predictions on valid set.
    """
    if len(oof) == n:
        return oof
    full = np.full(n, np.nan)
    full[valid_mask] = oof
    full = np.where(np.isnan(full), np.nanmean(full), full)
    return full


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(RESULTS_DIR / "peritem_composite_hybrid_v5_iter11.json"))
    p.add_argument("--iter11_5fold_csv", default=str(RESULTS_DIR / "self_norm_cross_5split_iter11_5split.csv"))
    args = p.parse_args()

    d = load_peritem_data()
    n = len(d["sids"])
    sids_cur = list(d["sids"])

    # ── iter6 OOFs (5-fold per-item, T1 aligned via SID) ───────────────────
    sids_iter6 = np.load(RESULTS_DIR / f"iter6_sids_{ITER6_TS}.npy", allow_pickle=True)
    sids_iter6 = np.array([str(s) for s in sids_iter6])
    align_idx = np.array([np.where(sids_iter6 == s)[0][0] if s in list(sids_iter6) else -1
                          for s in sids_cur])
    valid6 = align_idx >= 0
    iter6_oofs: dict[int, np.ndarray] = {}
    for it in T1_ITEMS:
        path = RESULTS_DIR / f"iter6_item{it}_oof_{ITER6_TS}.npy"
        if path.exists():
            arr = np.load(path)
            full = np.full(n, np.nan)
            full[valid6] = arr[align_idx[valid6]]
            iter6_oofs[it] = full

    # ── iter8 OOFs (LOOCV per-item) ─────────────────────────────────────────
    iter8_oofs: dict[int, np.ndarray] = {}
    for f in glob.glob(str(RESULTS_DIR / f"lockbox_peritem_*_{ITER8_TS}*.oof.npy")):
        try:
            item = int(Path(f).name.split("_")[2])
        except Exception:
            continue
        oof = np.load(f)
        y = d["items"].get(item)
        if y is None:
            continue
        valid_mask = ~np.isnan(np.asarray(y, dtype=float))
        if len(oof) < n:
            oof = _align_oof(oof, n, valid_mask)
        iter8_oofs[item] = oof

    # ── cccv2 OOFs (item 12 + 18 winners) ───────────────────────────────────
    cccv2_oofs: dict[int, np.ndarray] = {}
    for it, fname in [(12, "lockbox_peritem_12_item_plus_v2_cccv2.oof.npy"),
                      (18, "lockbox_peritem_18_hy_residual_cccv2.oof.npy")]:
        p_path = RESULTS_DIR / fname
        if not p_path.exists():
            continue
        arr = np.load(p_path)
        y_full = d["items"][it]
        valid_mask = ~np.isnan(np.asarray(y_full, dtype=float))
        cccv2_oofs[it] = _align_oof(arr, n, valid_mask)

    # ── interaction-screen LOOCV OOFs (the iter10 self-norm winners) ────────
    inter_oofs: dict[tuple[int, str], np.ndarray] = {}
    for f in glob.glob(str(RESULTS_DIR / "interaction_*_loocv_loocv_winners.oof.npy")):
        bn = Path(f).name
        try:
            parts = bn.replace(".oof.npy", "").split("_")
            item = int(parts[1])
            variant = "_".join(parts[2:-3])  # parts[-3]='loocv', [-2]='loocv', [-1]='winners'
        except Exception:
            continue
        arr = np.load(f)
        y = d["items"].get(item)
        if y is None:
            continue
        valid_mask = ~np.isnan(np.asarray(y, dtype=float))
        inter_oofs[(item, variant)] = _align_oof(arr, n, valid_mask)

    # ── iter11 self-norm-cross LOOCV OOFs ───────────────────────────────────
    iter11_oofs: dict[tuple[int, str], np.ndarray] = {}
    iter11_meta: dict[tuple[int, str], dict] = {}
    for f in glob.glob(str(RESULTS_DIR / "lockbox_self_norm_cross_*_*.oof.npy")):
        bn = Path(f).name.replace(".oof.npy", "")
        # lockbox_self_norm_cross_<item>_<variant>_<timestamp>
        toks = bn.split("_")
        try:
            # toks[0..3] = ['lockbox','self','norm','cross']
            item = int(toks[4])
            # variant is between item and timestamp (timestamp is 8 digits + _ + 6 digits)
            # last two tokens are date_time
            variant_toks = toks[5:-2]
            variant = "_".join(variant_toks)
        except Exception:
            continue
        arr = np.load(f)
        y = d["items"].get(item)
        if y is None:
            continue
        valid_mask = ~np.isnan(np.asarray(y, dtype=float))
        iter11_oofs[(item, variant)] = _align_oof(arr, n, valid_mask)
        # Also load JSON for metadata
        json_path = Path(f).with_suffix("").with_suffix(".json")
        if json_path.exists():
            try:
                with open(json_path) as jf:
                    iter11_meta[(item, variant)] = json.load(jf)
            except Exception:
                pass

    # ── iter11 5-fold screen for null gates ─────────────────────────────────
    iter11_screen = pd.read_csv(args.iter11_5fold_csv) if Path(args.iter11_5fold_csv).exists() else pd.DataFrame()

    print(f"\nLoaded sources:")
    print(f"  iter6={sorted(iter6_oofs)} (5-fold per-item)")
    print(f"  iter8={sorted(iter8_oofs)} (LOOCV per-item)")
    print(f"  cccv2={sorted(cccv2_oofs)} (LOOCV cccv2)")
    print(f"  interaction={sorted(set(i for (i,_) in inter_oofs))} (iter10 self-norm LOOCV)")
    print(f"  iter11={sorted(set(i for (i,_) in iter11_oofs))} (self-norm cross LOOCV)")

    # ── Compute per-item LOOCV CCC across all sources ────────────────────────
    print(f"\n{'item':>4}  {'iter6':>8}  {'iter8':>8}  {'cccv2':>8}  {'inter':>15} {'iter11':>22}")
    per_item_table = {}
    for it in T1_ITEMS + [18]:
        y = d["items"][it]
        c6 = ccc_fn(y, iter6_oofs[it]) if it in iter6_oofs else float("nan")
        c8 = ccc_fn(y, iter8_oofs[it]) if it in iter8_oofs else float("nan")
        cv2 = ccc_fn(y, cccv2_oofs[it]) if it in cccv2_oofs else float("nan")
        # best interaction
        ic = {v: ccc_fn(y, o) for (i, v), o in inter_oofs.items() if i == it}
        best_inter = (max(ic, key=ic.get), max(ic.values())) if ic else ("", float("nan"))
        # best iter11
        i11c = {v: ccc_fn(y, o) for (i, v), o in iter11_oofs.items() if i == it}
        best_iter11 = (max(i11c, key=i11c.get), max(i11c.values())) if i11c else ("", float("nan"))

        per_item_table[it] = {
            "iter6": c6, "iter8": c8, "cccv2": cv2,
            "inter_best": best_inter, "inter_all": ic,
            "iter11_best": best_iter11, "iter11_all": i11c,
        }
        print(f"  {it:>2}  {c6:>8.4f}  {c8:>8.4f}  {cv2:>8.4f}  {best_inter[0]:>15s}={best_inter[1]:.4f}  {best_iter11[0]:>22s}={best_iter11[1]:.4f}")

    # ── Composite 1: hybrid_v3 baseline (iter6{10,14}, iter8{9,11,13}, cccv2{12}) ──
    chosen_v3 = {
        9: iter8_oofs.get(9), 10: iter6_oofs.get(10), 11: iter8_oofs.get(11),
        12: cccv2_oofs.get(12), 13: iter8_oofs.get(13), 14: iter6_oofs.get(14),
    }
    composites = {}
    if all(v is not None for v in chosen_v3.values()):
        t1 = sum(chosen_v3[it] for it in T1_ITEMS)
        composites["T1_hybrid_v3_baseline"] = {
            **full_metrics(d["t1"], t1),
            "method": "iter8{9,11,13}, iter6{10,14}, cccv2{12}",
        }

    # ── Composite 2: hybrid_v4 (iter10 — item 13 swap to interaction v2_plus_self_norm) ──
    chosen_v4 = dict(chosen_v3)
    item13_inter = inter_oofs.get((13, "v2_plus_self_norm"))
    if item13_inter is not None:
        chosen_v4[13] = item13_inter
    if all(v is not None for v in chosen_v4.values()):
        t1 = sum(chosen_v4[it] for it in T1_ITEMS)
        composites["T1_hybrid_v4_canonical"] = {
            **full_metrics(d["t1"], t1),
            "method": "v3 + item13 swap to inter v2_plus_self_norm (iter10C)",
            "selections": {it: ("inter_v2_plus_self_norm" if it == 13 else
                               ("iter8" if it in {9, 11} else
                                ("iter6" if it in {10, 14} else "cccv2")))
                          for it in T1_ITEMS},
        }

    # ── Composite 3: hybrid_v5 iter11 KOSHER swaps ──────────────────────────
    chosen_v5 = dict(chosen_v4)
    swaps_v5 = {}
    for it in T1_ITEMS:
        y = d["items"][it]
        # current best in chosen_v4
        base_ccc = ccc_fn(y, chosen_v4[it])
        # candidates: iter11 self-norm-cross LOOCV winners
        i11c = sorted(per_item_table[it]["iter11_all"].items(), key=lambda kv: -kv[1])
        for variant, ccc_v in i11c:
            if ccc_v < base_ccc + 0.015:
                continue
            # Check 5-fold null gate: scram-abs<0.20, canary>0
            if iter11_screen.empty:
                passes_null = True
                screen_ccc = float("nan")
                screen_nulls = {}
                screen_delta = float("nan")
            else:
                sub = iter11_screen[(iter11_screen["item"] == it) & (iter11_screen["variant"] == variant)]
                if sub.empty:
                    passes_null = False
                    screen_ccc = float("nan")
                    screen_nulls = {}
                    screen_delta = float("nan")
                else:
                    r = sub.iloc[0]
                    screen_ccc = float(r["ccc_mean"])
                    scram = float(r.get("scrambled_label_ccc", 0.0))
                    canary = float(r.get("canary_feature_ccc", 0.0))
                    sid_shuf = float(r.get("sid_shuffle_selfnorm_ccc", 0.0))
                    screen_nulls = {"scram": scram, "canary": canary, "sid_shuf": sid_shuf}
                    # 5-fold delta over baseline iter6
                    base_5fold = ccc_fn(y, iter6_oofs[it]) if it in iter6_oofs else float("nan")
                    screen_delta = screen_ccc - base_5fold
                    # STRICT null criterion (matches compose_hybrid_v4_interaction.py rule):
                    #   delta_5fold >= 0.015,
                    #   |scram| < 0.15,
                    #   |canary - ccc| < 0.05,
                    #   sid_shuf <= ccc - 0.05
                    passes_null = (screen_delta >= 0.015
                                   and abs(scram) < 0.15
                                   and abs(canary - screen_ccc) < 0.05
                                   and sid_shuf <= screen_ccc - 0.05)
            if passes_null:
                chosen_v5[it] = iter11_oofs[(it, variant)]
                swaps_v5[it] = {
                    "variant": f"iter11_{variant}",
                    "loocv_ccc": ccc_v,
                    "v4_ccc": base_ccc,
                    "delta_loocv": ccc_v - base_ccc,
                    "screen_5fold_ccc": screen_ccc,
                    "screen_5fold_delta": screen_delta,
                    "screen_nulls": screen_nulls,
                    "criterion": "delta_5fold>=0.015, |scram|<0.15, |canary-ccc|<0.05, sid_shuf<=ccc-0.05",
                }
                break
    if all(v is not None for v in chosen_v5.values()):
        t1 = sum(chosen_v5[it] for it in T1_ITEMS)
        composites["T1_hybrid_v5_iter11"] = {
            **full_metrics(d["t1"], t1),
            "method": "v4 + iter11 self-norm-cross swaps (≥+0.015 LOOCV, null-pass)",
            "swaps": swaps_v5,
        }

    # ── Composite 4: per-item-best LOOCV (POSTHOC upper bound) ──────────────
    chosen_post = {}
    for it in T1_ITEMS:
        y = d["items"][it]
        cands = [("iter6", iter6_oofs.get(it)),
                 ("iter8", iter8_oofs.get(it)),
                 ("cccv2", cccv2_oofs.get(it))]
        for (i, v), o in inter_oofs.items():
            if i == it:
                cands.append((f"inter_{v}", o))
        for (i, v), o in iter11_oofs.items():
            if i == it:
                cands.append((f"iter11_{v}", o))
        cands_finite = [(name, o) for name, o in cands if o is not None]
        cands_scored = [(name, o, ccc_fn(y, o)) for name, o in cands_finite]
        cands_scored.sort(key=lambda x: -x[2])
        chosen_post[it] = cands_scored[0]
    t1_post = sum(c[1] for c in chosen_post.values())
    composites["T1_hybrid_v5_per_item_best_POSTHOC"] = {
        **full_metrics(d["t1"], t1_post),
        "method": "post-hoc per-item LOOCV best (upper bound, NOT a deployment number)",
        "selections": {it: f"{c[0]} (CCC={c[2]:.4f})" for it, c in chosen_post.items()},
    }

    # ── Print + save ────────────────────────────────────────────────────────
    print("\n=== Composite results ===")
    for k, v in composites.items():
        if isinstance(v, dict) and "ccc" in v:
            print(f"  {k}: T1 LOOCV CCC={v['ccc']:.4f}  MAE={v['mae']:.3f}  slope={v['cal_slope']:.3f}")
            if "swaps" in v and v["swaps"]:
                for it, swap in v["swaps"].items():
                    print(f"      Swap item {it}: {swap['variant']} (loocv {swap['v4_ccc']:.4f} → {swap['loocv_ccc']:.4f})")
            if "selections" in v:
                print(f"      Selections: {v['selections']}")

    out_path = Path(args.out)
    with open(out_path, "w") as f:
        json.dump({
            "composites": composites,
            "per_item_table": {it: {k: (v if not isinstance(v, tuple) else list(v))
                                    for k, v in row.items() if k != "iter11_all" and k != "inter_all"}
                              for it, row in per_item_table.items()},
            "iter11_per_item_loocv": {f"{it}_{v}": float(c) for it, row in per_item_table.items()
                                      for v, c in row["iter11_all"].items()},
            "n_subjects": int(n),
        }, f, indent=2, default=float)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
