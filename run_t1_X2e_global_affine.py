"""X2e — Single GLOBAL affine recalibration on iter34 (no stratification).

Tests whether iter34 itself has systematic calibration error (slope≠1 or intercept≠0)
vs y_t1. If a global affine helps CCC, the calibration is the issue. If not (X2's
+0.47 D4 corr was duration-specific), stratification matters.

Fold-local fit: each LOOCV fold fits a single global (a, b) on training fold's
(yhat, y_t1) and applies to the held-out subject.
"""
from __future__ import annotations
import argparse, hashlib, json, logging, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from eval_utils import lins_ccc as ccc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [X2e] %(message)s")
log = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parent
ITER34_OOF = REPO/"results"/"t1_iter34_per_item_oof_20260511_044242.npz"

N_BOOTSTRAP = 5000
BOOTSTRAP_SEED_A = 20260516
BOOTSTRAP_SEED_B = 20260601


def fit_affine(y, x):
    valid = np.isfinite(y) & np.isfinite(x)
    if valid.sum() < 5: return 1.0, 0.0
    yv, xv = y[valid], x[valid]; x_m, y_m = xv.mean(), yv.mean(); x_v = ((xv-x_m)**2).sum()
    if x_v < 1e-9: return 1.0, 0.0
    a = ((xv-x_m)*(yv-y_m)).sum() / x_v
    b = y_m - a * x_m
    return float(a), float(b)


def loocv_global_affine(yhat, y):
    n = len(y); corrected = np.full(n, np.nan)
    slopes = []; intercepts = []
    for i in range(n):
        tr = np.arange(n) != i
        a, b = fit_affine(y[tr], yhat[tr])
        slopes.append(a); intercepts.append(b)
        corrected[i] = a * yhat[i] + b
    return corrected, {
        "slope_mean": float(np.mean(slopes)), "slope_std": float(np.std(slopes)),
        "intercept_mean": float(np.mean(intercepts)), "intercept_std": float(np.std(intercepts)),
    }


def paired_bootstrap(y, p_base, p_cand, n_boot, seed):
    rng = np.random.default_rng(seed); n = len(y); deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        deltas[b] = float(ccc(y[idx], p_cand[idx]) - ccc(y[idx], p_base[idx]))
    return {"median": float(np.median(deltas)), "ci95": [float(np.percentile(deltas,2.5)), float(np.percentile(deltas,97.5))], "frac_pos": float(np.mean(deltas > 0))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--null", choices=("scrambled_y","sid_shuffle","canary_noise","transductive"), default="")
    parser.add_argument("--sanity-y-nan", action="store_true")
    args = parser.parse_args(); null_mode = args.null

    oof = dict(np.load(ITER34_OOF, allow_pickle=True))
    sids = oof["sids"].astype(str); y_t1 = oof["y_t1"].astype(float); yhat = oof["t1_sum_pred"].astype(float)
    n = len(sids)

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011); y_t1 = rng.permutation(y_t1)
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(91011); yhat = yhat[rng.permutation(n)]
    elif null_mode == "canary_noise":
        rng = np.random.default_rng(91011); yhat = yhat + rng.normal(0,0.01,yhat.shape)
    elif null_mode == "transductive":
        m, s = np.mean(yhat), np.std(yhat) + 1e-9; yhat = (yhat - m) / s

    corrected, info = loocv_global_affine(yhat, y_t1)
    ccc_base = float(ccc(y_t1, yhat)); ccc_corr = float(ccc(y_t1, corrected))
    mae_base = float(np.mean(np.abs(y_t1 - yhat))); mae_corr = float(np.mean(np.abs(y_t1 - corrected)))
    pearson_base = float(np.corrcoef(y_t1, yhat)[0,1]); pearson_corr = float(np.corrcoef(y_t1, corrected)[0,1])
    boot_A = paired_bootstrap(y_t1, yhat, corrected, N_BOOTSTRAP, BOOTSTRAP_SEED_A)
    boot_B = paired_bootstrap(y_t1, yhat, corrected, N_BOOTSTRAP, BOOTSTRAP_SEED_B)
    correction = corrected - yhat; t1_resid = y_t1 - yhat
    corr_correction_resid = float(np.corrcoef(correction, t1_resid)[0,1])

    formula_sha256 = hashlib.sha256(b"global_affine_loocv_fold_local").hexdigest()
    out = {
        "name":"lockbox_t1_X2e_global_affine",
        "created_at_utc": datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "preregistration":"results/preregistration_t1_post_closure_X_series_20260516.json (X2e diagnostic: global affine vs duration stratification)",
        "null_mode": null_mode or "real", "sanity_y_nan": args.sanity_y_nan,
        "formula_sha256": formula_sha256, "n_cohort": int(n),
        "slope_info": info,
        "baselines":{"loocv_ccc_iter34": ccc_base, "loocv_mae_iter34": mae_base, "loocv_pearson_iter34": pearson_base},
        "corrected":{"loocv_ccc": ccc_corr, "loocv_mae": mae_corr, "loocv_pearson": pearson_corr,
                     "delta_ccc": ccc_corr - ccc_base, "delta_mae": mae_corr - mae_base, "delta_pearson_r": pearson_corr - pearson_base},
        "bootstrap_seed_A": boot_A, "bootstrap_seed_B": boot_B,
        "d4_audit":{"corr_correction_T1_sum_residual": corr_correction_resid},
        "verdict_provisional": _verdict(ccc_corr - ccc_base, boot_A["frac_pos"], boot_B["frac_pos"], mae_corr - mae_base, corr_correction_resid),
    }
    suffix = ""
    if null_mode: suffix = f"_{null_mode}"
    elif args.sanity_y_nan: suffix = "_sanityYnan"
    out_path = REPO/"results"/f"lockbox_t1_X2e_global_affine_{out['created_at_utc']}{suffix}.json"
    with open(out_path, "w") as f: json.dump(out, f, indent=2)
    log.info("wrote %s", out_path)
    print(f"\n=== X2e GLOBAL affine — {null_mode or 'real'}{' SANITY' if args.sanity_y_nan else ''} ===")
    print(f"baseline iter34 CCC = {ccc_base:.4f}, Pearson r = {pearson_base:.4f}")
    print(f"corrected CCC = {ccc_corr:.4f}  Δ_CCC={ccc_corr - ccc_base:+.4f}  Δ_MAE={mae_corr - mae_base:+.4f}  Δ_Pearson={pearson_corr - pearson_base:+.4f}")
    print(f"frac>0 seed_A={boot_A['frac_pos']:.3f}  seed_B={boot_B['frac_pos']:.3f}")
    print(f"D4 corr={corr_correction_resid:+.4f}; slope_mean={info['slope_mean']:.4f} std={info['slope_std']:.4f}; intercept_mean={info['intercept_mean']:+.4f}")
    print(f"VERDICT: {out['verdict_provisional']}")
    return 0


def _verdict(d, fA, fB, dmae, corr_sumres):
    if dmae > 0 and corr_sumres < 0: return "VARIANCE_COMPRESSION_MIRAGE_LIKELY"
    if d >= 0.005 and fA >= 0.95 and fB >= 0.95: return "PRIMARY_GATE_PASS_REPLICATED"
    if d >= 0.005 and (fA >= 0.95 or fB >= 0.95): return "PRIMARY_GATE_PASS_PARTIAL"
    if d > 0: return "POSITIVE_BUT_SUB_GATE"
    return "FAIL"


if __name__ == "__main__":
    sys.exit(main())
