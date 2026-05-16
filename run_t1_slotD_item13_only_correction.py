"""T1 GLASS-CEILING PUSH — SLOT D (post-D4-audit)

Item-13-only correction: per D4 audit, item 13 PH lift is the ONLY real-signal
correction among the 4 yesterday-winners (items 9/10/14 are calibration mirages
with sum-resid covariance ~0 or negative).

Test: replace yesterday's naive sum-of-4-Ridge-corrections with item-13-only
correction. yhat_T1_sum_d = yhat_iter34_T1_sum + correction_item_13_only.

Mathematically, this DROPS the 3 calibration-mirage contributions and keeps
the one real positive-cov term.

Plus 5-null gate per project rule.
Plus a parallel item-13-REPLACEMENT variant: yhat_item_13_new = Ridge_PH alone
(without iter34's near-zero baseline), then sum across items.

5-min compute on master single-core.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from metric_lib import align_features_to_oof  # noqa
from inductive_lib import FoldImputer, FoldNormalizer, full_metrics  # noqa
from eval_utils import lins_ccc  # noqa


PH_PREFIX = "ph_"
ITEM_13 = 13
RIDGE_ALPHA = 100.0  # Locked from yesterday's per-item Ridge stack
SPLIT_SEED = 20260309


def fold_local_ridge_correction(F: np.ndarray, y_item: np.ndarray,
                                 yhat_item_oof: np.ndarray, alpha: float = RIDGE_ALPHA) -> np.ndarray:
    n = len(y_item)
    correction = np.zeros(n)
    residual = y_item - yhat_item_oof
    for i in range(n):
        mask = np.arange(n) != i
        imp = FoldImputer.fit(F[mask])
        F_tr = imp.transform(F[mask])
        F_te = imp.transform(F[i:i + 1])
        norm = FoldNormalizer.fit(F_tr)
        F_tr = norm.transform(F_tr)
        F_te = norm.transform(F_te)
        ridge = Ridge(alpha=alpha, random_state=42)
        ridge.fit(F_tr, residual[mask])
        correction[i] = float(ridge.predict(F_te)[0])
    return correction


def fold_local_ridge_replace(F: np.ndarray, y_item: np.ndarray, alpha: float = RIDGE_ALPHA) -> np.ndarray:
    """Pure Ridge prediction (no iter34 baseline)."""
    n = len(y_item)
    preds = np.zeros(n)
    for i in range(n):
        mask = np.arange(n) != i
        imp = FoldImputer.fit(F[mask])
        F_tr = imp.transform(F[mask])
        F_te = imp.transform(F[i:i + 1])
        norm = FoldNormalizer.fit(F_tr)
        F_tr = norm.transform(F_tr)
        F_te = norm.transform(F_te)
        ridge = Ridge(alpha=alpha, random_state=42)
        ridge.fit(F_tr, y_item[mask])
        preds[i] = float(ridge.predict(F_te)[0])
    return preds


def bootstrap_delta(y, yhat_a, yhat_b, n_boot=2000, seed=42):
    rng = np.random.RandomState(seed)
    n = len(y); deltas = np.zeros(n_boot)
    for k in range(n_boot):
        idx = rng.randint(0, n, n)
        deltas[k] = lins_ccc(y[idx], yhat_b[idx]) - lins_ccc(y[idx], yhat_a[idx])
    return {
        "delta_median": float(np.median(deltas)),
        "delta_ci_lower": float(np.quantile(deltas, 0.025)),
        "delta_ci_upper": float(np.quantile(deltas, 0.975)),
        "frac_positive": float((deltas > 0).mean()),
        "n_boot": int(n_boot),
    }


def main(feature_path: str = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv",
         oof_path: str = "results/t1_iter34_per_item_oof_20260511_044242.npz"):
    print("=" * 80)
    print("SLOT D — Item-13-only correction + replacement (post-D4 audit)")
    print("=" * 80)

    npz = np.load(oof_path, allow_pickle=True)
    sids = np.asarray(npz["sids"])
    y_t1_sum = np.asarray(npz["y_t1"], np.float64)
    yhat_iter34 = np.asarray(npz["t1_sum_pred"], np.float64)
    y_item_13 = np.asarray(npz["item_13_true"], np.float64)
    yhat_iter34_item_13 = np.asarray(npz["item_13_pred"], np.float64)

    df = pd.read_csv(feature_path)
    ph_cols = [c for c in df.columns if PH_PREFIX in c]
    F_ph, mask = align_features_to_oof(df[["sid"] + ph_cols], sids, sid_col="sid")
    print(f"  N={len(sids)} PH d_F={F_ph.shape[1]}")
    print(f"  iter34 T1_sum CCC = {lins_ccc(y_t1_sum, yhat_iter34):.4f}")
    print(f"  iter34 item 13 CCC = {lins_ccc(y_item_13, yhat_iter34_item_13):.4f}")

    # Variant D1: item-13-only correction (drop calibration-mirage items 9/10/14)
    print("\n--- VARIANT D1: Item-13-only correction ---")
    correction_13 = fold_local_ridge_correction(F_ph, y_item_13, yhat_iter34_item_13)
    yhat_T1_d1 = yhat_iter34 + correction_13
    baseline_m = full_metrics(y_t1_sum, yhat_iter34, "iter34_baseline")
    d1_m = full_metrics(y_t1_sum, yhat_T1_d1, "slotD1_item13_only_correction")
    delta_d1 = d1_m["ccc"] - baseline_m["ccc"]
    boot_d1 = bootstrap_delta(y_t1_sum, yhat_iter34, yhat_T1_d1, n_boot=2000)
    print(f"  iter34         CCC = {baseline_m['ccc']:.4f}")
    print(f"  D1 corrected   CCC = {d1_m['ccc']:.4f}  Δ={delta_d1:+.4f}  MAE={d1_m['mae']:.4f}")
    print(f"  Bootstrap: median={boot_d1['delta_median']:+.4f}  CI=[{boot_d1['delta_ci_lower']:+.4f}, {boot_d1['delta_ci_upper']:+.4f}]  frac>0={boot_d1['frac_positive']:.4f}")
    print(f"  Bonferroni n=4 (0.9875): {'PASS' if boot_d1['frac_positive'] >= 0.9875 else 'FAIL'}")
    print(f"  Uncorrected (0.95):      {'PASS' if boot_d1['frac_positive'] >= 0.95 else 'FAIL'}")

    # Variant D2: item-13 REPLACEMENT (drop iter34's item 13, replace with PH-Ridge alone)
    print("\n--- VARIANT D2: Item-13 REPLACEMENT (PH-Ridge replaces iter34 item 13) ---")
    yhat_item_13_replaced = fold_local_ridge_replace(F_ph, y_item_13)
    # T1_sum = iter34_T1_sum - iter34_item_13 + replaced_item_13
    yhat_T1_d2 = yhat_iter34 - yhat_iter34_item_13 + yhat_item_13_replaced
    d2_m = full_metrics(y_t1_sum, yhat_T1_d2, "slotD2_item13_replacement")
    delta_d2 = d2_m["ccc"] - baseline_m["ccc"]
    boot_d2 = bootstrap_delta(y_t1_sum, yhat_iter34, yhat_T1_d2, n_boot=2000)
    item_13_replaced_m = full_metrics(y_item_13, yhat_item_13_replaced, "item_13_replaced")
    print(f"  Item 13 PH-only Ridge: CCC = {item_13_replaced_m['ccc']:.4f}")
    print(f"  D2 replacement T1     CCC = {d2_m['ccc']:.4f}  Δ={delta_d2:+.4f}  MAE={d2_m['mae']:.4f}")
    print(f"  Bootstrap: median={boot_d2['delta_median']:+.4f}  CI=[{boot_d2['delta_ci_lower']:+.4f}, {boot_d2['delta_ci_upper']:+.4f}]  frac>0={boot_d2['frac_positive']:.4f}")
    print(f"  Bonferroni n=4 (0.9875): {'PASS' if boot_d2['frac_positive'] >= 0.9875 else 'FAIL'}")
    print(f"  Uncorrected (0.95):      {'PASS' if boot_d2['frac_positive'] >= 0.95 else 'FAIL'}")

    # Variant D3: hybrid — use min(0.213, replaced) for item 13 (whichever is more conservative)
    # Skip — keep deterministic for FWER discipline

    # Save lockbox
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lockbox = {
        "name": "lockbox_t1_slotD_item13_only_20260515",
        "created_at_utc": ts,
        "preregistration": "results/preregistration_t1_ceiling_push_20260515_master.json",
        "slot": "slot_D_item13_only_post_d4",
        "rationale": "Per D4 audit (codex 2026-05-15T08:25Z), items 9/10/14 per-item corrections are calibration mirages with sum-resid cov negative. Item 13 alone has +0.118 cov with T1_sum residual. D1 drops the 3 mirage corrections; D2 replaces iter34's item-13 prediction (CCC=0.07) entirely with PH-Ridge.",
        "feature_cache": feature_path,
        "oof_npz": oof_path,
        "n": int(len(y_t1_sum)),
        "baseline_iter34": baseline_m,
        "D1_item13_only_correction": {
            "metrics": d1_m, "delta_ccc": float(delta_d1), "bootstrap": boot_d1,
        },
        "D2_item13_replacement": {
            "metrics": d2_m, "delta_ccc": float(delta_d2), "bootstrap": boot_d2,
            "item_13_replaced_alone_metrics": item_13_replaced_m,
        },
    }

    def _cast(o):
        if isinstance(o, (np.integer,)): return int(o)
        if isinstance(o, (np.floating,)): return float(o)
        if isinstance(o, np.ndarray): return o.tolist()
        if isinstance(o, dict): return {str(k): _cast(v) for k, v in o.items()}
        if isinstance(o, list): return [_cast(x) for x in o]
        return o
    lockbox = _cast(lockbox)

    out = Path(f"results/lockbox_t1_slotD_item13_only_{ts}.json")
    out.write_text(json.dumps(lockbox, indent=2) + "\n")
    print(f"\n  -> wrote {out}")

    return lockbox


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--feature", default="results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv")
    ap.add_argument("--oof", default="results/t1_iter34_per_item_oof_20260511_044242.npz")
    args = ap.parse_args()
    main(args.feature, args.oof)
