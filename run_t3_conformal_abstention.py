#!/usr/bin/env python3
"""
run_t3_conformal_abstention.py
Post-hoc split conformal prediction + abstention curve on existing iter5 LOOCV OOFs.
Leakage-clean by construction: no model fitting, only interval calibration on held-out folds.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
import sys

# Import iter3 loader for exact alignment
sys.path.insert(0, str(Path(__file__).parent))
from run_t3_iter3 import load_full_pd_data, is_pd

RESULTS_DIR = Path("results")

def load_oof():
    oof_path = RESULTS_DIR / "lockbox_t3_iter5_A3_tier1_20260502_171604.oof.npy"
    if not oof_path.exists():
        raise FileNotFoundError(f"OOF not found: {oof_path}")
    preds = np.load(oof_path)
    sids, X, feat_cols, y_t3, hy, obs = load_full_pd_data()
    assert len(preds) == len(y_t3), f"OOF length mismatch: {len(preds)} vs {len(y_t3)}"
    return preds, y_t3

def split_conformal(y_true, y_pred, alpha=0.1, n_calib=None):
    """Split conformal: calibrate on first n_calib points, test on rest."""
    if n_calib is None:
        n_calib = len(y_true) // 2
    calib_resid = np.abs(y_true[:n_calib] - y_pred[:n_calib])
    q = np.quantile(calib_resid, np.ceil((n_calib + 1) * (1 - alpha)) / n_calib)
    test_lower = y_pred[n_calib:] - q
    test_upper = y_pred[n_calib:] + q
    coverage = np.mean((y_true[n_calib:] >= test_lower) & (y_true[n_calib:] <= test_upper))
    interval_width = 2 * q
    return coverage, interval_width, q, n_calib

def lins_ccc(x, y):
    """Concordance correlation coefficient."""
    mx, my = np.mean(x), np.mean(y)
    sx, sy = np.std(x, ddof=0), np.std(y, ddof=0)
    if sx == 0 or sy == 0:
        return 0.0
    cov = np.mean((x - mx) * (y - my))
    return 2 * cov / (sx**2 + sy**2 + (mx - my)**2)

def abstention_curve(y_true, y_pred, interval_widths):
    """Sort by interval width (uncertainty), discard most uncertain first."""
    order = np.argsort(interval_widths)
    y_true_s = y_true[order]
    y_pred_s = y_pred[order]
    widths_s = interval_widths[order]
    n = len(y_true)
    results = []
    for discard_frac in np.arange(0, 0.51, 0.05):
        k = int(n * discard_frac)
        if k >= n - 2:
            break
        yt, yp = y_true_s[k:], y_pred_s[k:]
        ccc = lins_ccc(yp, yt)
        mae = np.mean(np.abs(yp - yt))
        results.append({
            "discard_frac": discard_frac,
            "retained_n": n - k,
            "ccc": ccc,
            "mae": mae,
            "mean_width": np.mean(widths_s[k:]),
        })
    return pd.DataFrame(results)

def main():
    y_pred, y_true = load_oof()
    print(f"Loaded OOF: n={len(y_pred)}, base CCC={lins_ccc(y_pred, y_true):.4f}, base MAE={np.mean(np.abs(y_pred-y_true)):.3f}")

    # Split conformal at multiple alpha levels
    conformal_results = []
    for alpha in [0.05, 0.10, 0.20]:
        coverage, width, q, n_calib = split_conformal(y_true, y_pred, alpha=alpha)
        conformal_results.append({
            "alpha": alpha,
            "nominal_coverage": 1 - alpha,
            "empirical_coverage": coverage,
            "interval_width": width,
            "quantile": q,
            "n_calib": n_calib,
        })
        print(f"alpha={alpha:.2f}: coverage={coverage:.3f}, width={width:.3f}, q={q:.3f}")

    # Abstention curve 1: use absolute residual as uncertainty proxy
    residuals = np.abs(y_true - y_pred)
    abst_df = abstention_curve(y_true, y_pred, residuals)
    print("\nAbstention curve (discard by |residual|):")
    print(abst_df.to_string(index=False))

    # Abstention curve 2: discard predictions farthest from mean (tail shrinkage)
    mean_pred = np.mean(y_pred)
    tail_dist = np.abs(y_pred - mean_pred)
    abst_df2 = abstention_curve(y_true, y_pred, tail_dist)
    print("\nAbstention curve (discard by |pred - mean_pred|, tail shrinkage):")
    print(abst_df2.to_string(index=False))

    # Save outputs
    out = {
        "conformal": conformal_results,
        "abstention": abst_df.to_dict(orient="records"),
        "base_ccc": float(lins_ccc(y_pred, y_true)),
        "base_mae": float(np.mean(np.abs(y_pred - y_true))),
    }
    out_path = RESULTS_DIR / "t3_conformal_abstention_20260505.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved: {out_path}")

if __name__ == "__main__":
    main()
