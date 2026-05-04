"""LOOCV lockbox runner for the v3 (Track A + Track B) winners.

Reads the v3 5-fold screening CSV, picks the per-item winner amongst variants
that pass the null gate (|scrambled_label_ccc| < 0.35), runs LOOCV exactly
once per (item, winner), saves OOFs as .npy, and recomputes the T1 hybrid
composite plugging the new OOFs in for items where they beat the canonical
0.6809 baseline (kosher: pre-registered selection on 5-fold CCC, then LOOCV
evaluation only for those items where 5-fold beat the prior winner by ≥+0.015).
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

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_per_item_ordinal_v3 import (
    load_data, run_one, VARIANTS, T1_ITEMS,
    variant_set_for_item,
)
from run_t1_iter4 import SEEDS

# Prior best per-item 5-fold CCC under iter6/iter8 (extracted from existing
# screening CSV peritem_v2_screening_5split.csv). These are the gates that
# v3 variants must beat by ≥+0.015 to be promoted to LOOCV lockbox.
PRIOR_BEST_5FOLD = {
    9:  0.3232,  # hy_residual_item
    10: 0.5256,  # item_plus_v2
    11: 0.3195,  # item_dedicated
    12: 0.5550,  # item_plus_v2
    13: 0.1597,  # item_plus_v2
    14: 0.2969,  # item_plus_v2
}

PROMOTION_DELTA = 0.015


def pick_v3_winner(df: pd.DataFrame, item: int) -> dict | None:
    sub = df[df["item"] == item].copy()
    if sub.empty:
        return None
    if "scrambled_label_ccc" in sub.columns:
        ok = (sub["scrambled_label_ccc"].abs() < 0.35) | sub["scrambled_label_ccc"].isna()
        sub = sub[ok]
    if sub.empty:
        return None
    sub = sub.sort_values("ccc_mean", ascending=False)
    row = sub.iloc[0]
    return {
        "item": int(row["item"]),
        "variant": str(row["variant"]),
        "ccc_5fold": float(row["ccc_mean"]),
        "scrambled_ccc": float(row.get("scrambled_label_ccc", np.nan)),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--screening", default=str(RESULTS_DIR / "peritem_v3_screening_5split.csv"))
    p.add_argument("--out_dir", default=str(RESULTS_DIR))
    p.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    p.add_argument("--items", type=int, nargs="+", default=T1_ITEMS)
    p.add_argument("--force_all", action="store_true",
                   help="run LOOCV for every (item, winner), even those that don't beat prior by +0.015")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)

    df = pd.read_csv(args.screening)
    print(f"Loaded screening: {df.shape}", flush=True)

    promoted = []
    skipped = []
    for it in args.items:
        w = pick_v3_winner(df, it)
        if w is None:
            print(f"  Item {it}: no valid v3 variant", flush=True)
            skipped.append({"item": it, "reason": "no_variant"})
            continue
        prior = PRIOR_BEST_5FOLD.get(it, float("nan"))
        delta = w["ccc_5fold"] - prior
        decision = "PROMOTE" if (delta >= PROMOTION_DELTA or args.force_all) else "SKIP"
        line = (f"  Item {it}: best v3 = {w['variant']} "
                f"5fCCC={w['ccc_5fold']:.4f}  prior={prior:.4f}  Δ={delta:+.4f}  "
                f"[{decision}]")
        print(line, flush=True)
        if decision == "PROMOTE":
            promoted.append(w)
        else:
            skipped.append({"item": it, "reason": "below_threshold",
                            "delta": delta, "prior": prior, "v3_5f_ccc": w["ccc_5fold"]})

    if not promoted:
        print("\nNo v3 variant beats prior winners by Δ≥+0.015. Exiting.", flush=True)
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\nLockbox timestamp: {ts}", flush=True)
    print("Loading data once...", flush=True)
    d = load_data()

    summary: list[dict] = []
    for w in promoted:
        item, variant = w["item"], w["variant"]
        prereg = {
            "item": item, "variant": variant, "track": "v3",
            "eval": "loocv", "seeds": list(args.seeds),
            "n_subjects": int(len(d["sids"])),
            "expected_5split_ccc": w["ccc_5fold"],
            "prior_best_5fold": PRIOR_BEST_5FOLD.get(item, float("nan")),
            "promotion_delta": w["ccc_5fold"] - PRIOR_BEST_5FOLD.get(item, float("nan")),
            "timestamp_prereg": ts,
        }
        prereg_path = out_dir / f"preregistration_v3_peritem_{item}_{ts}.json"
        with open(prereg_path, "w") as f:
            json.dump(prereg, f, indent=2, default=float)
        print(f"\n[Item {item} → {variant}] Pre-registered.  Running LOOCV "
              f"({len(args.seeds)} seeds × {len(d['sids'])} folds)...", flush=True)
        t0 = time.time()
        r = run_one(d, item, variant, "loocv", seeds=tuple(args.seeds), with_null=False)
        elapsed = time.time() - t0
        oof_path = out_dir / f"lockbox_v3_peritem_{item}_{variant}_{ts}.oof.npy"
        if "_oof_array" in r:
            np.save(oof_path.as_posix(), np.array(r["_oof_array"]))
            del r["_oof_array"]
        json_path = out_dir / f"lockbox_v3_peritem_{item}_{variant}_{ts}.json"
        r["wall_time_s"] = elapsed
        r["pre_registration"] = prereg_path.name
        with open(json_path, "w") as f:
            json.dump(r, f, indent=2, default=float)
        print(f"  Done in {elapsed:.1f}s. LOOCV CCC={r['ccc_mean']:.4f}±{r['ccc_std']:.4f}, "
              f"MAE={r['mae_mean']:.3f}", flush=True)
        summary.append({
            "item": item, "variant": variant,
            "loocv_ccc": r["ccc_mean"], "loocv_ccc_std": r["ccc_std"],
            "loocv_mae": r["mae_mean"],
            "screening_5fold_ccc": w["ccc_5fold"],
            "wall_time_s": elapsed,
            "oof_path": oof_path.name,
        })
        pd.DataFrame(summary).to_csv(
            out_dir / f"peritem_v3_lockbox_summary_{ts}.csv", index=False)
    print("\n=== V3 LOCKBOX RUNS COMPLETE ===")
    print(pd.DataFrame(summary).to_string())

    # Recompose hybrid composite swapping in v3 OOFs
    if summary:
        try:
            from compose_hybrid_v3 import main as compose_main  # type: ignore
        except Exception:
            pass
        new_composite = recompute_hybrid_with_v3(d, summary, out_dir, ts)
        with open(out_dir / f"peritem_composite_hybrid_v3_{ts}.json", "w") as f:
            json.dump(new_composite, f, indent=2, default=float)
        print(f"\nWrote hybrid v3 composite: peritem_composite_hybrid_v3_{ts}.json")
        print("\n=== T1 COMPOSITE COMPARISON ===")
        for k, m in new_composite["composites"].items():
            ccc = m.get("ccc")
            mae = m.get("mae")
            print(f"  {k}: CCC={ccc:.4f}  MAE={mae:.3f}")


def recompute_hybrid_with_v3(d, summary, out_dir, ts) -> dict:
    """Build T1 composite using v3 LOOCV OOFs for promoted items, falling back
    to canonical iter6/iter8 OOFs for the rest. Selection rule (kosher):
    use v3 OOF only for items present in `summary`."""
    import glob
    from sklearn.linear_model import Ridge

    n = len(d["sids"])
    # Load canonical iter6/iter8 OOFs
    iter6_files = sorted(glob.glob(str(out_dir / "iter6_t1_oof_*.npy")))
    if iter6_files:
        iter6_ts = Path(iter6_files[-1]).stem.replace("iter6_t1_oof_", "")
    else:
        iter6_ts = ""
    iter8_ts = "20260430_143044"

    iter6_item_oofs: dict[int, np.ndarray] = {}
    iter8_item_oofs: dict[int, np.ndarray] = {}
    if iter6_ts:
        sids6 = np.load(out_dir / f"iter6_sids_{iter6_ts}.npy")
        sids6 = np.array([str(s) for s in sids6])
        align_idx = []
        for sid in d["sids"]:
            hits = np.where(sids6 == sid)[0]
            align_idx.append(hits[0] if hits.size else -1)
        align_idx = np.array(align_idx)
        valid = align_idx >= 0
        for it in T1_ITEMS:
            p = out_dir / f"iter6_item{it}_oof_{iter6_ts}.npy"
            if p.exists():
                arr = np.load(p)
                full = np.full(n, np.nan)
                full[valid] = arr[align_idx[valid]]
                iter6_item_oofs[it] = full
    for f in glob.glob(str(out_dir / f"lockbox_peritem_*_{iter8_ts}*.oof.npy")):
        bn = Path(f).name
        try:
            it = int(bn.split("_")[2])
        except Exception:
            continue
        oof = np.load(f)
        if len(oof) < n:
            full = np.full(n, np.nan)
            y_full = d["items"].get(it)
            if y_full is None:
                continue
            mask = ~np.isnan(np.asarray(y_full, dtype=float))
            full[mask] = oof
            full = np.where(np.isnan(full), np.nanmean(full), full)
            oof = full
        iter8_item_oofs[it] = oof

    # Load v3 OOFs
    v3_item_oofs: dict[int, np.ndarray] = {}
    v3_winners: dict[int, str] = {}
    for s in summary:
        f = out_dir / s["oof_path"]
        if f.exists():
            v3_item_oofs[int(s["item"])] = np.load(f)
            v3_winners[int(s["item"])] = s["variant"]

    # Canonical hybrid kosher rule: items {9, 11, 13} from iter8, {10, 12, 14} from iter6
    iter8_better = {9, 11, 13}
    chosen = {}
    chosen_src = {}
    for it in T1_ITEMS:
        if it in v3_item_oofs:
            chosen[it] = v3_item_oofs[it]
            chosen_src[it] = f"v3:{v3_winners[it]}"
        elif it in iter8_better and it in iter8_item_oofs:
            chosen[it] = iter8_item_oofs[it]
            chosen_src[it] = "iter8"
        elif it in iter6_item_oofs:
            chosen[it] = iter6_item_oofs[it]
            chosen_src[it] = "iter6"
        elif it in iter8_item_oofs:
            chosen[it] = iter8_item_oofs[it]
            chosen_src[it] = "iter8"
    composites = {}
    if len(chosen) == len(T1_ITEMS):
        t1 = np.zeros(n)
        for it in T1_ITEMS:
            t1 += chosen[it]
        m = full_metrics(d["t1"], t1)
        composites["T1_hybrid_v3"] = {**m, "method": "v3+iter6+iter8 (kosher pre-reg)",
                                       "sources": chosen_src}
    # Per-item LOOCV CCC tally
    per_item = {}
    for it in T1_ITEMS:
        y = d["items"].get(it)
        if y is None:
            continue
        row = {}
        if it in iter6_item_oofs:
            row["iter6_ccc"] = float(ccc_fn(y, iter6_item_oofs[it]))
        if it in iter8_item_oofs:
            row["iter8_ccc"] = float(ccc_fn(y, iter8_item_oofs[it]))
        if it in v3_item_oofs:
            row["v3_ccc"] = float(ccc_fn(y, v3_item_oofs[it]))
            row["v3_variant"] = v3_winners[it]
        per_item[it] = row

    return {
        "ts": ts,
        "n_subjects": int(n),
        "iter6_ts": iter6_ts,
        "iter8_ts": iter8_ts,
        "v3_winners": v3_winners,
        "per_item": per_item,
        "composites": composites,
    }


if __name__ == "__main__":
    main()
