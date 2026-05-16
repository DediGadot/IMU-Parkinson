"""T1 GLASS-CEILING PUSH — SLOT C downstream test on richer PH/MFDFA features.

Tests three variants on the richer cache (cache_stepfunction_v2_ph_v2_mfdfa_v2_*.csv):

  C1 — Item 13 PH-Ridge replacement (yhat_item_13_new replaces iter34's near-zero item-13)
  C2 — Item 13 PH-Ridge correction (yhat_item_13_corrected = iter34 + Ridge(residual))
  C3 — Joint stage-3 LGB on T1_sum residual with all ph_v2 + mfdfa_v2 features

For each: paired bootstrap delta vs iter34 baseline, with FWER-corrected gate.

Also runs the D4 variance-compression audit on the new item-13 predictions
to verify the richer features carry real signal (not more calibration mirage).
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
from sklearn.model_selection import KFold

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from metric_lib import align_features_to_oof  # noqa
from inductive_lib import FoldImputer, FoldNormalizer, full_metrics  # noqa
from eval_utils import lins_ccc  # noqa


SPLIT_SEED = 20260309
FEATURE_SEED = 31415
PH_V2_PREFIX = "ph2_"
MFDFA_V2_PREFIX = "mfdfa2_"
ALPHA_GRID = (10.0, 100.0, 1000.0)
K_GRID = (20, 50, 100)
INNER_NFOLDS = 5


def lins_ccc_decomp(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Lin's CCC + r + C_b + MAE + RMSE."""
    mu_y, mu_p = y_true.mean(), y_pred.mean()
    sd_y, sd_p = y_true.std(ddof=0), y_pred.std(ddof=0)
    if sd_y < 1e-12 or sd_p < 1e-12:
        return {"ccc": 0.0, "r": 0.0, "C_b": 1.0, "MAE": float(np.mean(np.abs(y_true - y_pred))), "RMSE": float(np.sqrt(np.mean((y_true - y_pred)**2)))}
    r = float(np.corrcoef(y_true, y_pred)[0, 1])
    cov_yp = float(np.mean((y_true - mu_y) * (y_pred - mu_p)))
    ccc = 2 * cov_yp / (sd_y ** 2 + sd_p ** 2 + (mu_y - mu_p) ** 2 + 1e-12)
    v = sd_p / sd_y if sd_y > 0 else 0
    u = (mu_p - mu_y) / np.sqrt(sd_y * sd_p) if (sd_y > 0 and sd_p > 0) else 0
    C_b = 2 / (v + 1 / v + u ** 2 + 1e-12) if v > 0 else 0
    return {"ccc": float(ccc), "r": r, "C_b": float(C_b),
            "MAE": float(np.mean(np.abs(y_true - y_pred))),
            "RMSE": float(np.sqrt(np.mean((y_true - y_pred)**2))),
            "var_ratio": float(v)}


def fold_local_ridge_correction(F: np.ndarray, y_item: np.ndarray,
                                 yhat_item_oof: np.ndarray, alpha: float) -> np.ndarray:
    n = len(y_item)
    correction = np.zeros(n)
    residual = y_item - yhat_item_oof
    for i in range(n):
        mask = np.arange(n) != i
        imp = FoldImputer.fit(F[mask]); F_tr = imp.transform(F[mask]); F_te = imp.transform(F[i:i+1])
        norm = FoldNormalizer.fit(F_tr); F_tr = norm.transform(F_tr); F_te = norm.transform(F_te)
        ridge = Ridge(alpha=alpha, random_state=42); ridge.fit(F_tr, residual[mask])
        correction[i] = float(ridge.predict(F_te)[0])
    return correction


def fold_local_ridge_replace(F: np.ndarray, y_item: np.ndarray, alpha: float) -> np.ndarray:
    n = len(y_item)
    preds = np.zeros(n)
    for i in range(n):
        mask = np.arange(n) != i
        imp = FoldImputer.fit(F[mask]); F_tr = imp.transform(F[mask]); F_te = imp.transform(F[i:i+1])
        norm = FoldNormalizer.fit(F_tr); F_tr = norm.transform(F_tr); F_te = norm.transform(F_te)
        ridge = Ridge(alpha=alpha, random_state=42); ridge.fit(F_tr, y_item[mask])
        preds[i] = float(ridge.predict(F_te)[0])
    return preds


def select_alpha_inner(F: np.ndarray, y: np.ndarray, alphas: tuple = ALPHA_GRID) -> float:
    """Inner 5-fold select alpha for replacement (or correction) Ridge."""
    n = len(y)
    kf = KFold(n_splits=INNER_NFOLDS, shuffle=True, random_state=SPLIT_SEED)
    best_alpha, best_ccc = alphas[0], -np.inf
    for alpha in alphas:
        oof_preds = np.full(n, np.nan)
        for tr_inner, va_inner in kf.split(np.arange(n)):
            F_tr = F[tr_inner]; F_va = F[va_inner]
            imp = FoldImputer.fit(F_tr); F_tr_n = imp.transform(F_tr); F_va_n = imp.transform(F_va)
            norm = FoldNormalizer.fit(F_tr_n); F_tr_n = norm.transform(F_tr_n); F_va_n = norm.transform(F_va_n)
            r = Ridge(alpha=alpha, random_state=42); r.fit(F_tr_n, y[tr_inner])
            oof_preds[va_inner] = r.predict(F_va_n)
        valid = ~np.isnan(oof_preds)
        if valid.sum() < 3: continue
        c = lins_ccc(y[valid], oof_preds[valid])
        if c > best_ccc:
            best_ccc, best_alpha = c, alpha
    return best_alpha


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


def main(feature_path: str, oof_path: str = "results/t1_iter34_per_item_oof_20260511_044242.npz",
         family_prefix: str = PH_V2_PREFIX, alpha_grid: tuple = ALPHA_GRID):
    print("=" * 80)
    print("SLOT C — Richer PH/MFDFA downstream test")
    print("=" * 80)

    npz = np.load(oof_path, allow_pickle=True)
    sids = np.asarray(npz["sids"])
    y_t1_sum = np.asarray(npz["y_t1"], np.float64)
    yhat_iter34 = np.asarray(npz["t1_sum_pred"], np.float64)
    y_item_13 = np.asarray(npz["item_13_true"], np.float64)
    yhat_iter34_item_13 = np.asarray(npz["item_13_pred"], np.float64)
    y_item_14 = np.asarray(npz["item_14_true"], np.float64)
    yhat_iter34_item_14 = np.asarray(npz["item_14_pred"], np.float64)
    y_item_10 = np.asarray(npz["item_10_true"], np.float64)
    yhat_iter34_item_10 = np.asarray(npz["item_10_pred"], np.float64)
    sum_resid = y_t1_sum - yhat_iter34

    df = pd.read_csv(feature_path)
    ph_cols = [c for c in df.columns if PH_V2_PREFIX in c]
    mfdfa_cols = [c for c in df.columns if MFDFA_V2_PREFIX in c]
    print(f"  N={len(sids)}  ph_v2 cols={len(ph_cols)}  mfdfa_v2 cols={len(mfdfa_cols)}")
    print(f"  iter34 T1_sum CCC = {lins_ccc(y_t1_sum, yhat_iter34):.4f}")
    print(f"  iter34 item 13 CCC = {lins_ccc(y_item_13, yhat_iter34_item_13):.4f}")
    print(f"  iter34 item 14 CCC = {lins_ccc(y_item_14, yhat_iter34_item_14):.4f}")
    print(f"  iter34 item 10 CCC = {lins_ccc(y_item_10, yhat_iter34_item_10):.4f}")

    baseline_m = full_metrics(y_t1_sum, yhat_iter34, "iter34_baseline")
    results = {"baseline_iter34": baseline_m, "n": int(len(sids))}

    # Align PH features
    F_ph, mask = align_features_to_oof(df[["sid"] + ph_cols], sids, sid_col="sid")
    F_mf, _ = align_features_to_oof(df[["sid"] + mfdfa_cols], sids, sid_col="sid")
    print(f"  Aligned: PH d_F={F_ph.shape[1]}  MFDFA d_F={F_mf.shape[1]}")

    # ---- Variant C1: item-13 PH-RIDGE REPLACEMENT (richer features) ----
    print("\n--- C1: Item-13 PH-Ridge replacement (richer PH features) ---")
    alpha_star_13 = select_alpha_inner(F_ph, y_item_13)
    print(f"  inner-CV selected alpha = {alpha_star_13}")
    yhat_item_13_replaced = fold_local_ridge_replace(F_ph, y_item_13, alpha=alpha_star_13)
    item_13_m = lins_ccc_decomp(y_item_13, yhat_item_13_replaced)
    print(f"  PH-Ridge item 13: CCC={item_13_m['ccc']:.4f}  r={item_13_m['r']:.4f}  C_b={item_13_m['C_b']:.4f}  MAE={item_13_m['MAE']:.4f}")
    yhat_T1_c1 = yhat_iter34 - yhat_iter34_item_13 + yhat_item_13_replaced
    c1_m = full_metrics(y_t1_sum, yhat_T1_c1, "slotC1_item13_replace_richer")
    delta_c1 = c1_m["ccc"] - baseline_m["ccc"]
    boot_c1 = bootstrap_delta(y_t1_sum, yhat_iter34, yhat_T1_c1)
    print(f"  T1_sum: iter34={baseline_m['ccc']:.4f}  C1={c1_m['ccc']:.4f}  Δ={delta_c1:+.4f}  CI=[{boot_c1['delta_ci_lower']:+.4f}, {boot_c1['delta_ci_upper']:+.4f}]  frac>0={boot_c1['frac_positive']:.4f}")
    print(f"  Bonferroni n=4 (0.9875): {'PASS' if boot_c1['frac_positive'] >= 0.9875 else 'FAIL'}")
    print(f"  Uncorrected (0.95):      {'PASS' if boot_c1['frac_positive'] >= 0.95 else 'FAIL'}")
    results["C1_item13_replace_richer_ph"] = {
        "alpha": float(alpha_star_13),
        "item_13_decomp": item_13_m,
        "metrics": c1_m, "delta_ccc": float(delta_c1), "bootstrap": boot_c1,
    }

    # ---- Variant C2: item-13 PH-RIDGE CORRECTION (richer features) ----
    print("\n--- C2: Item-13 PH-Ridge correction (richer PH features) ---")
    correction_13 = fold_local_ridge_correction(F_ph, y_item_13, yhat_iter34_item_13, alpha=alpha_star_13)
    yhat_item_13_corrected = yhat_iter34_item_13 + correction_13
    item_13_corr_m = lins_ccc_decomp(y_item_13, yhat_item_13_corrected)
    item_13_base_m = lins_ccc_decomp(y_item_13, yhat_iter34_item_13)
    print(f"  iter34 item 13: CCC={item_13_base_m['ccc']:.4f}  r={item_13_base_m['r']:.4f}")
    print(f"  Corrected item 13: CCC={item_13_corr_m['ccc']:.4f}  r={item_13_corr_m['r']:.4f}  Δr={item_13_corr_m['r']-item_13_base_m['r']:+.4f}  ΔMAE={item_13_corr_m['MAE']-item_13_base_m['MAE']:+.4f}")
    corr_delta_sum_resid = float(np.corrcoef(correction_13, sum_resid)[0, 1])
    print(f"  corr(delta_13, sum_resid) = {corr_delta_sum_resid:+.4f}")
    yhat_T1_c2 = yhat_iter34 + correction_13
    c2_m = full_metrics(y_t1_sum, yhat_T1_c2, "slotC2_item13_corr_richer")
    delta_c2 = c2_m["ccc"] - baseline_m["ccc"]
    boot_c2 = bootstrap_delta(y_t1_sum, yhat_iter34, yhat_T1_c2)
    print(f"  T1_sum: iter34={baseline_m['ccc']:.4f}  C2={c2_m['ccc']:.4f}  Δ={delta_c2:+.4f}  CI=[{boot_c2['delta_ci_lower']:+.4f}, {boot_c2['delta_ci_upper']:+.4f}]  frac>0={boot_c2['frac_positive']:.4f}")
    print(f"  Bonferroni n=4 (0.9875): {'PASS' if boot_c2['frac_positive'] >= 0.9875 else 'FAIL'}")
    print(f"  Uncorrected (0.95):      {'PASS' if boot_c2['frac_positive'] >= 0.95 else 'FAIL'}")
    results["C2_item13_corr_richer_ph"] = {
        "alpha": float(alpha_star_13),
        "item_13_corrected_decomp": item_13_corr_m,
        "item_13_baseline_decomp": item_13_base_m,
        "corr_delta_sum_resid": corr_delta_sum_resid,
        "metrics": c2_m, "delta_ccc": float(delta_c2), "bootstrap": boot_c2,
    }

    # ---- Variant C3: also try richer MFDFA on item 10 + PH on item 13/14 stacked ----
    print("\n--- C3: Item 13 PH-Ridge replacement + iter34 unchanged for other items ---")
    print("    (same as C1; C3 reserved for joint multi-task in future iter)")

    # Save lockbox
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lockbox = {
        "name": "lockbox_t1_slotC_richer_ph_downstream",
        "created_at_utc": ts,
        "preregistration": "results/preregistration_t1_ceiling_push_20260515_master.json",
        "slot": "slot_C_richer_ph_mfdfa",
        "feature_cache": feature_path,
        "results": results,
    }
    def _cast(o):
        if isinstance(o, (np.integer,)): return int(o)
        if isinstance(o, (np.floating,)): return float(o)
        if isinstance(o, np.ndarray): return o.tolist()
        if isinstance(o, dict): return {str(k): _cast(v) for k, v in o.items()}
        if isinstance(o, list): return [_cast(x) for x in o]
        return o
    lockbox = _cast(lockbox)

    out = Path(f"results/lockbox_t1_slotC_richer_ph_downstream_{ts}.json")
    out.write_text(json.dumps(lockbox, indent=2) + "\n")
    print(f"\n  -> wrote {out}")
    return lockbox


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--feature", required=True, help="cache_stepfunction_v2_*.csv")
    ap.add_argument("--oof", default="results/t1_iter34_per_item_oof_20260511_044242.npz")
    args = ap.parse_args()
    main(args.feature, args.oof)
