"""Per-family pdCor score on the step-function feature cache.

Splits the 952-feature cache into 5 family blocks by column-name prefix and scores
each block against:
  - T1 (iter34 OOF, N=92)
  - T3 (iter47 OOF, N=95)
  - Each individual item 9..14 (iter34 per-item OOF)

For each (block, target) pair: pdCor + ΔI_imb + cohort permutation + downstream Ridge stack.

Outputs:
  - results/perfamily_score_<UTC>.csv: rows = (target × family × subitem)
  - results/perfamily_score_<UTC>.json: full breakdown
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from metric_lib import (
    align_features_to_oof,
    bootstrap_ci,
    distance_correlation,
    information_imbalance,
    euclidean_distances,
    load_t1_canonical_oof,
    load_t3_canonical_oof,
    partial_distance_correlation,
    permutation_pvalue_pdcor,
    score_feature_block,
)
from inductive_lib import FoldImputer, FoldNormalizer, full_metrics


FAMILY_PREFIXES = {
    "spd": "spd_",
    "klc": "klc_",
    "crqa": "crqa_",
    "mfdfa": "mfdfa_",
    "ph": "ph_",
}


def split_features_by_family(df: pd.DataFrame) -> dict[str, list[str]]:
    out = {fam: [] for fam in FAMILY_PREFIXES}
    for col in df.columns:
        if col in {"sid", "n_tasks"}:
            continue
        for fam, prefix in FAMILY_PREFIXES.items():
            if prefix in col:
                out[fam].append(col)
                break
    return out


def score_block_quick(F: np.ndarray, y: np.ndarray, yhat_oof: np.ndarray) -> dict:
    """Quick scoring: cohort pdCor + perm p-value + downstream Ridge LOOCV."""
    n = len(y)
    # Cohort pdCor + permutation
    cohort_pdcor, cohort_p = permutation_pvalue_pdcor(F, y, yhat_oof, n_perm=500)
    # Downstream Ridge LOOCV
    residual = y - yhat_oof
    correction = np.zeros(n)
    for i in range(n):
        mask = np.arange(n) != i
        imp = FoldImputer.fit(F[mask])
        F_tr = imp.transform(F[mask])
        F_te = imp.transform(F[i:i+1])
        norm = FoldNormalizer.fit(F_tr)
        F_tr = norm.transform(F_tr)
        F_te = norm.transform(F_te)
        ridge = Ridge(alpha=100.0, random_state=42)
        ridge.fit(F_tr, residual[mask])
        correction[i] = float(ridge.predict(F_te)[0])
    yhat_stacked = yhat_oof + correction
    baseline = full_metrics(y, yhat_oof, "")
    stacked = full_metrics(y, yhat_stacked, "")
    # Bootstrap ΔCCC
    rng = np.random.RandomState(42)
    deltas = []
    from eval_utils import lins_ccc
    for _ in range(1000):
        idx = rng.randint(0, n, n)
        d = lins_ccc(y[idx], yhat_stacked[idx]) - lins_ccc(y[idx], yhat_oof[idx])
        deltas.append(d)
    deltas = np.array(deltas)
    return {
        "n": int(n),
        "d_F": int(F.shape[1]),
        "cohort_pdcor": cohort_pdcor,
        "perm_p": cohort_p,
        "baseline_ccc": baseline["ccc"],
        "stacked_ccc": stacked["ccc"],
        "delta_ccc": float(stacked["ccc"] - baseline["ccc"]),
        "delta_ccc_median": float(np.median(deltas)),
        "delta_ccc_ci_lo": float(np.quantile(deltas, 0.025)),
        "delta_ccc_ci_hi": float(np.quantile(deltas, 0.975)),
        "delta_ccc_frac_pos": float((deltas > 0).mean()),
    }


def load_t1_peritem_oof():
    d = np.load("results/t1_iter34_per_item_oof_20260511_044242.npz", allow_pickle=True)
    sids = np.asarray(d["sids"])
    items = {}
    for item in range(9, 15):
        items[item] = {
            "y": np.asarray(d[f"item_{item}_true"], np.float64),
            "yhat": np.asarray(d[f"item_{item}_pred"], np.float64),
        }
    return sids, items


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--feature", required=True)
    ap.add_argument("--out-tag", default="perfamily")
    args = ap.parse_args()

    df = pd.read_csv(args.feature)
    fam_cols = split_features_by_family(df)
    print(f"\nFamily counts in {args.feature}:")
    for fam, cols in fam_cols.items():
        print(f"  {fam}: {len(cols)} columns")
    print()

    # T1 (whole-sum) — use iter34 hybrid OOF
    sids_t1, y_t1, yhat_t1 = load_t1_canonical_oof()
    # T3 — use iter47 valid-range
    sids_t3, y_t3, yhat_t3 = load_t3_canonical_oof()
    # Per-item T1
    sids_t1_peritem, t1_items = load_t1_peritem_oof()

    results = []
    targets = {
        "t1_sum": (sids_t1, y_t1, yhat_t1),
        "t3": (sids_t3, y_t3, yhat_t3),
    }
    for item in range(9, 15):
        targets[f"t1_item{item}"] = (sids_t1_peritem, t1_items[item]["y"], t1_items[item]["yhat"])

    for fam, cols in fam_cols.items():
        if not cols:
            continue
        for tgt_name, (sids, y, yhat) in targets.items():
            t0 = time.time()
            F, mask = align_features_to_oof(df[["sid"] + cols], sids, sid_col="sid")
            if mask.sum() < 80:
                continue
            try:
                r = score_block_quick(F, y, yhat)
                r["family"] = fam
                r["target"] = tgt_name
                r["n_subjects_aligned"] = int(mask.sum())
                r["scoring_seconds"] = float(time.time() - t0)
                results.append(r)
                print(f"  {fam:>6} → {tgt_name:>12}: pdCor={r['cohort_pdcor']:+.4f} p={r['perm_p']:.3f} "
                      f"ΔCCC={r['delta_ccc']:+.4f} CI=[{r['delta_ccc_ci_lo']:+.4f},{r['delta_ccc_ci_hi']:+.4f}] "
                      f"frac+={r['delta_ccc_frac_pos']:.3f} ({r['scoring_seconds']:.0f}s)", flush=True)
            except Exception as e:
                print(f"  {fam} → {tgt_name}: FAILED {e}", flush=True)

    # ALSO score stacked top-N of each family by individual pdCor
    print("\n=== STACKED ALL FAMILIES === ")
    all_cols = [c for fam_list in fam_cols.values() for c in fam_list]
    for tgt_name, (sids, y, yhat) in targets.items():
        F, _ = align_features_to_oof(df[["sid"] + all_cols], sids, sid_col="sid")
        try:
            r = score_block_quick(F, y, yhat)
            r["family"] = "stacked_all"
            r["target"] = tgt_name
            results.append(r)
            print(f"  stacked → {tgt_name:>12}: pdCor={r['cohort_pdcor']:+.4f} p={r['perm_p']:.3f} "
                  f"ΔCCC={r['delta_ccc']:+.4f} CI=[{r['delta_ccc_ci_lo']:+.4f},{r['delta_ccc_ci_hi']:+.4f}] "
                  f"frac+={r['delta_ccc_frac_pos']:.3f}", flush=True)
        except Exception as e:
            print(f"  stacked → {tgt_name}: FAILED {e}", flush=True)

    # Save
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_csv = Path(f"results/perfamily_score_{args.out_tag}_{ts}.csv")
    pd.DataFrame(results).to_csv(out_csv, index=False)
    print(f"\n→ wrote {out_csv} ({len(results)} rows)")


if __name__ == "__main__":
    main()
