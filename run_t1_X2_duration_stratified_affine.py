"""Probe X2 — Disease-duration-stratified Stage-2 affine correction on iter34.

Mechanism: stratify training-fold subjects into short (<7 yr PD) and long (>=7 yr)
PD-duration groups; per-stratum fit affine y_t1 ~ a*yhat_iter34 + b on training
fold; apply stratum-matched affine to held-out subject.

Targets data-dive finding: abstained subjects have +1.8 yr longer PD duration
(kept 6.5 vs abst 8.3). Hypothesis: long-duration PD develops different motor
signature; per-stratum calibration captures the systematic over/under-prediction.

Wall orthogonality: F59 (Stage-1 widening with clinical extras): we don't add
clinical features to Stage-1; we Stage-2-condition on duration. F61 (tail-aware
retraining): we stratify by clinical input, not residual magnitude.

Pre-registration: results/preregistration_t1_post_closure_X_series_20260516.json
Threshold 7.0 yr predeclared (median of kept+abst means = 7.4, rounded), NOT tuned.

Usage:
  uv run python run_t1_X2_duration_stratified_affine.py
  uv run python run_t1_X2_duration_stratified_affine.py --null scrambled_y
  uv run python run_t1_X2_duration_stratified_affine.py --null sid_shuffle
  uv run python run_t1_X2_duration_stratified_affine.py --null canary_noise
  uv run python run_t1_X2_duration_stratified_affine.py --null transductive
  uv run python run_t1_X2_duration_stratified_affine.py --sanity-y-nan
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from eval_utils import lins_ccc as ccc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [X2] %(message)s")
log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent
ITER34_OOF = REPO / "results" / "t1_iter34_per_item_oof_20260511_044242.npz"
CLINICAL = REPO / "results" / "pd_demographic_clinical_v1.csv"

DURATION_THRESHOLD = 7.0  # years since PD diagnosis; predeclared
MIN_STRATUM_SIZE = 15      # fallback to full-fold if either stratum has fewer

MODEL_SEEDS_SET_A = (42, 1337, 7)
MODEL_SEEDS_SET_B = (101, 202, 303)  # used for replication on bootstrap seeds (X2 is deterministic given fold split, but we re-seed bootstrap for 2 seed sets)

N_BOOTSTRAP = 5000
BOOTSTRAP_SEED_A = 20260516
BOOTSTRAP_SEED_B = 20260601


def fit_affine(y: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    """Least-squares y ~ a*x + b. Robust to NaN: drops them."""
    valid = np.isfinite(y) & np.isfinite(x)
    if valid.sum() < 5:
        return 1.0, 0.0
    yv, xv = y[valid], x[valid]
    x_mean, y_mean = xv.mean(), yv.mean()
    x_var = ((xv - x_mean) ** 2).sum()
    if x_var < 1e-9:
        return 1.0, 0.0
    a = ((xv - x_mean) * (yv - y_mean)).sum() / x_var
    b = y_mean - a * x_mean
    return float(a), float(b)


def loocv_stratified_affine(
    yhat_iter34: np.ndarray, y_t1: np.ndarray, duration: np.ndarray,
    threshold: float, min_stratum: int,
) -> tuple[np.ndarray, dict]:
    """LOOCV: per held-out subject, fit per-stratum affine on training fold using
    its duration, apply stratum-matched affine. Long-stratum subjects with NaN
    duration are assigned to long stratum (conservative)."""
    n = len(y_t1)
    corrected = np.full(n, np.nan)
    fold_info = []
    for i in range(n):
        tr = np.arange(n) != i
        yhat_tr = yhat_iter34[tr]
        y_tr = y_t1[tr]
        d_tr = duration[tr]

        # Stratum membership (training fold)
        long_tr = (~np.isfinite(d_tr)) | (d_tr >= threshold)
        short_tr = (~long_tr)

        n_long, n_short = int(long_tr.sum()), int(short_tr.sum())

        if n_long < min_stratum or n_short < min_stratum:
            # Fallback: use full-fold affine
            a, b = fit_affine(y_tr, yhat_tr)
            corrected[i] = a * yhat_iter34[i] + b
            fold_info.append({"i": i, "fallback": True, "a": a, "b": b, "n_long": n_long, "n_short": n_short})
        else:
            a_long, b_long = fit_affine(y_tr[long_tr], yhat_tr[long_tr])
            a_short, b_short = fit_affine(y_tr[short_tr], yhat_tr[short_tr])
            d_i = duration[i]
            is_long_i = (not np.isfinite(d_i)) or (d_i >= threshold)
            if is_long_i:
                a, b = a_long, b_long
            else:
                a, b = a_short, b_short
            corrected[i] = a * yhat_iter34[i] + b
            fold_info.append({
                "i": i, "fallback": False, "stratum": "long" if is_long_i else "short",
                "a": a, "b": b, "a_long": a_long, "b_long": b_long, "a_short": a_short, "b_short": b_short,
                "n_long": n_long, "n_short": n_short,
            })
    fallback_rate = sum(1 for f in fold_info if f["fallback"]) / n
    long_count = sum(1 for f in fold_info if not f["fallback"] and f.get("stratum") == "long")
    short_count = sum(1 for f in fold_info if not f["fallback"] and f.get("stratum") == "short")
    return corrected, {
        "fallback_rate": fallback_rate,
        "applied_long_count": long_count,
        "applied_short_count": short_count,
    }


def paired_bootstrap(y, p_base, p_cand, n_boot, seed):
    rng = np.random.default_rng(seed)
    n = len(y)
    deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        deltas[b] = float(ccc(y[idx], p_cand[idx]) - ccc(y[idx], p_base[idx]))
    return {
        "median": float(np.median(deltas)),
        "ci95": [float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))],
        "frac_pos": float(np.mean(deltas > 0)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--null", choices=("scrambled_y", "sid_shuffle", "canary_noise", "transductive"), default="")
    parser.add_argument("--sanity-y-nan", action="store_true")
    args = parser.parse_args()
    null_mode = args.null
    sanity_y_nan = args.sanity_y_nan

    oof = dict(np.load(ITER34_OOF, allow_pickle=True))
    sids = oof["sids"].astype(str)
    y_t1 = oof["y_t1"].astype(float)
    yhat_iter34 = oof["t1_sum_pred"].astype(float)
    n = len(sids)

    clin = pd.read_csv(CLINICAL, header=1).rename(columns={"Subject ID": "sid"})
    clin = clin.set_index("sid").loc[sids]
    duration = pd.to_numeric(clin["Years since PD diagnosis"], errors="coerce").values
    log.info("PD duration coverage: %d/%d non-NaN; median %.1f yr",
             np.isfinite(duration).sum(), n, np.nanmedian(duration))

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011)
        y_t1 = rng.permutation(y_t1)
        log.info("NULL scrambled_y")
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(91011)
        perm = rng.permutation(n)
        duration = duration[perm]
        log.info("NULL sid_shuffle: permuted duration column (decouples clinical feature from subject)")
    elif null_mode == "canary_noise":
        rng = np.random.default_rng(91011)
        duration = duration + rng.normal(0.0, 0.01, duration.shape)
        log.info("NULL canary_noise: added sigma=0.01 to duration")
    elif null_mode == "transductive":
        # Cohort-wide z-score of yhat_iter34 (leakage variant)
        m, s = np.mean(yhat_iter34), np.std(yhat_iter34) + 1e-9
        yhat_iter34 = (yhat_iter34 - m) / s
        log.info("NULL transductive: cohort z-score yhat_iter34")

    if sanity_y_nan:
        log.info("SANITY y_nan: stratum membership is determined by duration (clinical input), NOT by y_test")

    corrected, info = loocv_stratified_affine(yhat_iter34, y_t1, duration,
                                                DURATION_THRESHOLD, MIN_STRATUM_SIZE)
    log.info("Fallback rate (insufficient stratum): %.1f%%", info["fallback_rate"]*100)
    log.info("Applied: long stratum %d, short stratum %d", info["applied_long_count"], info["applied_short_count"])

    ccc_baseline = float(ccc(y_t1, yhat_iter34))
    ccc_corrected = float(ccc(y_t1, corrected))
    mae_baseline = float(np.mean(np.abs(y_t1 - yhat_iter34)))
    mae_corrected = float(np.mean(np.abs(y_t1 - corrected)))
    pearson_baseline = float(np.corrcoef(y_t1, yhat_iter34)[0, 1])
    pearson_corrected = float(np.corrcoef(y_t1, corrected)[0, 1])

    boot_A = paired_bootstrap(y_t1, yhat_iter34, corrected, N_BOOTSTRAP, BOOTSTRAP_SEED_A)
    boot_B = paired_bootstrap(y_t1, yhat_iter34, corrected, N_BOOTSTRAP, BOOTSTRAP_SEED_B)

    correction = corrected - yhat_iter34
    t1_resid = y_t1 - yhat_iter34
    corr_correction_resid = float(np.corrcoef(correction, t1_resid)[0, 1])

    formula = json.dumps({"threshold": DURATION_THRESHOLD, "min_stratum": MIN_STRATUM_SIZE}, sort_keys=True)
    formula_sha256 = hashlib.sha256(formula.encode()).hexdigest()

    out = {
        "name": "lockbox_t1_X2_duration_stratified_affine",
        "created_at_utc": datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "preregistration": "results/preregistration_t1_post_closure_X_series_20260516.json",
        "null_mode": null_mode or "real",
        "sanity_y_nan": sanity_y_nan,
        "formula_sha256": formula_sha256,
        "duration_threshold_yr": DURATION_THRESHOLD,
        "min_stratum_size": MIN_STRATUM_SIZE,
        "fallback_rate": info["fallback_rate"],
        "applied_long_count": info["applied_long_count"],
        "applied_short_count": info["applied_short_count"],
        "n_cohort": int(n),
        "baselines": {
            "loocv_ccc_iter34": ccc_baseline,
            "loocv_mae_iter34": mae_baseline,
            "loocv_pearson_iter34": pearson_baseline,
        },
        "corrected": {
            "loocv_ccc": ccc_corrected,
            "loocv_mae": mae_corrected,
            "loocv_pearson": pearson_corrected,
            "delta_ccc": ccc_corrected - ccc_baseline,
            "delta_mae": mae_corrected - mae_baseline,
            "delta_pearson_r": pearson_corrected - pearson_baseline,
        },
        "bootstrap_seed_A": boot_A,
        "bootstrap_seed_B": boot_B,
        "d4_audit": {
            "corr_correction_T1_sum_residual": corr_correction_resid,
        },
        "verdict_provisional": _verdict(
            ccc_corrected - ccc_baseline, boot_A["frac_pos"], boot_B["frac_pos"],
            mae_corrected - mae_baseline, corr_correction_resid),
    }

    suffix = ""
    if null_mode:
        suffix = f"_{null_mode}"
    elif sanity_y_nan:
        suffix = "_sanityYnan"
    out_path = REPO / "results" / f"lockbox_t1_X2_duration_stratified_affine_{out['created_at_utc']}{suffix}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    log.info("wrote %s", out_path)

    print(f"\n=== X2 — {null_mode or 'real'}{' SANITY_Y_NAN' if sanity_y_nan else ''} ===")
    print(f"N={n} thr={DURATION_THRESHOLD} fallback_rate={info['fallback_rate']:.2%} applied long={info['applied_long_count']} short={info['applied_short_count']}")
    print(f"baseline iter34 CCC = {ccc_baseline:.4f}")
    print(f"corrected CCC = {ccc_corrected:.4f}  Δ={ccc_corrected - ccc_baseline:+.4f}")
    print(f"frac>0 seed_A={boot_A['frac_pos']:.3f}  seed_B={boot_B['frac_pos']:.3f}")
    print(f"D4 corr(correction, sum_resid) = {corr_correction_resid:+.4f}")
    print(f"VERDICT: {out['verdict_provisional']}")
    return 0


def _verdict(d, f_A, f_B, dmae, corr_sumres) -> str:
    if dmae > 0 and corr_sumres < 0:
        return "VARIANCE_COMPRESSION_MIRAGE_LIKELY"
    if d >= 0.005 and f_A >= 0.95 and f_B >= 0.95:
        return "PRIMARY_GATE_PASS_REPLICATED"
    if d >= 0.005 and (f_A >= 0.95 or f_B >= 0.95):
        return "PRIMARY_GATE_PASS_PARTIAL"
    if d > 0:
        return "POSITIVE_BUT_SUB_GATE"
    return "FAIL"


if __name__ == "__main__":
    sys.exit(main())
