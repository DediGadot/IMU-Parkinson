"""Probe X2b — X2 fix attempt: per-stratum INTERCEPT-ONLY shift (slope=1 constrained).

X2 result analysis: per-stratum 2-param affine y_t1 ~ a*yhat + b produced:
  Δ_CCC = -0.0511 (FAIL CCC)
  Δ_MAE = -0.1697 (IMPROVES — substantial MAE reduction)
  D4 corr(correction, T1_sum_residual) = +0.4687 (STRONG positive direction)

Diagnosis: per-stratum affine slope a ≠ 1 compresses CCC scale; CCC heavily penalizes
scale mismatch; MAE doesn't. The +0.47 D4 corr proves directions are right.

Fix: constrain slope=1, fit only per-stratum intercept (shift). Correction becomes
  y_t1_corrected = yhat_iter34 + intercept_stratum
where intercept_stratum = mean(y_t1_train_stratum) - mean(yhat_train_stratum) on
training-fold subjects within the stratum matching held-out subject's duration.

This is a 1-param per stratum SHIFT correction — preserves scale, captures stratum-
specific bias direction.

Pre-registration: extends X-series under amendment-style mechanism (slot variant —
single-arm 1-param vs X2's 2-param). FWER counts +1 (n=4 in X-series).

Usage:
  uv run python run_t1_X2b_intercept_only_shift.py
  uv run python run_t1_X2b_intercept_only_shift.py --null scrambled_y
  uv run python run_t1_X2b_intercept_only_shift.py --null sid_shuffle
  uv run python run_t1_X2b_intercept_only_shift.py --null canary_noise
  uv run python run_t1_X2b_intercept_only_shift.py --null transductive
  uv run python run_t1_X2b_intercept_only_shift.py --sanity-y-nan
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [X2b] %(message)s")
log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent
ITER34_OOF = REPO / "results" / "t1_iter34_per_item_oof_20260511_044242.npz"
CLINICAL = REPO / "results" / "pd_demographic_clinical_v1.csv"

DURATION_THRESHOLD = 7.0
MIN_STRATUM_SIZE = 15

N_BOOTSTRAP = 5000
BOOTSTRAP_SEED_A = 20260516
BOOTSTRAP_SEED_B = 20260601


def fit_intercept_only(y_tr: np.ndarray, yhat_tr: np.ndarray) -> float:
    """Intercept-only: b = mean(y) - mean(yhat). Implies slope=1."""
    valid = np.isfinite(y_tr) & np.isfinite(yhat_tr)
    if valid.sum() < 5:
        return 0.0
    return float(np.mean(y_tr[valid]) - np.mean(yhat_tr[valid]))


def loocv_stratified_intercept(yhat: np.ndarray, y: np.ndarray, duration: np.ndarray,
                                threshold: float, min_stratum: int):
    n = len(y)
    corrected = np.full(n, np.nan)
    intercepts_long = []
    intercepts_short = []
    intercepts_full = []
    for i in range(n):
        tr = np.arange(n) != i
        yhat_tr, y_tr, d_tr = yhat[tr], y[tr], duration[tr]
        long_tr = (~np.isfinite(d_tr)) | (d_tr >= threshold)
        short_tr = ~long_tr
        n_long, n_short = int(long_tr.sum()), int(short_tr.sum())

        if n_long < min_stratum or n_short < min_stratum:
            b = fit_intercept_only(y_tr, yhat_tr)
            corrected[i] = yhat[i] + b
            intercepts_full.append(b)
        else:
            b_long = fit_intercept_only(y_tr[long_tr], yhat_tr[long_tr])
            b_short = fit_intercept_only(y_tr[short_tr], yhat_tr[short_tr])
            intercepts_long.append(b_long); intercepts_short.append(b_short)
            d_i = duration[i]
            is_long_i = (not np.isfinite(d_i)) or (d_i >= threshold)
            corrected[i] = yhat[i] + (b_long if is_long_i else b_short)
    info = {
        "n_intercepts_long": len(intercepts_long),
        "n_intercepts_short": len(intercepts_short),
        "n_intercepts_full": len(intercepts_full),
        "mean_intercept_long": float(np.mean(intercepts_long)) if intercepts_long else 0.0,
        "mean_intercept_short": float(np.mean(intercepts_short)) if intercepts_short else 0.0,
    }
    return corrected, info


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

    oof = dict(np.load(ITER34_OOF, allow_pickle=True))
    sids = oof["sids"].astype(str)
    y_t1 = oof["y_t1"].astype(float)
    yhat = oof["t1_sum_pred"].astype(float)
    n = len(sids)

    clin = pd.read_csv(CLINICAL, header=1).rename(columns={"Subject ID": "sid"})
    clin = clin.set_index("sid").loc[sids]
    duration = pd.to_numeric(clin["Years since PD diagnosis"], errors="coerce").values
    log.info("duration coverage: %d/%d", np.isfinite(duration).sum(), n)

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011); y_t1 = rng.permutation(y_t1); log.info("NULL scrambled_y")
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(91011); duration = duration[rng.permutation(n)]; log.info("NULL sid_shuffle")
    elif null_mode == "canary_noise":
        rng = np.random.default_rng(91011); duration = duration + rng.normal(0,0.01,duration.shape); log.info("NULL canary_noise")
    elif null_mode == "transductive":
        m, s = np.mean(yhat), np.std(yhat) + 1e-9; yhat = (yhat - m) / s; log.info("NULL transductive")

    corrected, info = loocv_stratified_intercept(yhat, y_t1, duration, DURATION_THRESHOLD, MIN_STRATUM_SIZE)

    ccc_base = float(ccc(y_t1, yhat))
    ccc_corr = float(ccc(y_t1, corrected))
    mae_base = float(np.mean(np.abs(y_t1 - yhat)))
    mae_corr = float(np.mean(np.abs(y_t1 - corrected)))
    pearson_base = float(np.corrcoef(y_t1, yhat)[0, 1])
    pearson_corr = float(np.corrcoef(y_t1, corrected)[0, 1])

    boot_A = paired_bootstrap(y_t1, yhat, corrected, N_BOOTSTRAP, BOOTSTRAP_SEED_A)
    boot_B = paired_bootstrap(y_t1, yhat, corrected, N_BOOTSTRAP, BOOTSTRAP_SEED_B)

    correction = corrected - yhat
    t1_resid = y_t1 - yhat
    corr_correction_resid = float(np.corrcoef(correction, t1_resid)[0, 1])

    formula_sha256 = hashlib.sha256(
        json.dumps({"threshold": DURATION_THRESHOLD, "intercept_only": True}, sort_keys=True).encode()
    ).hexdigest()

    out = {
        "name": "lockbox_t1_X2b_intercept_only_shift",
        "created_at_utc": datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "preregistration": "results/preregistration_t1_post_closure_X_series_20260516.json (X2b = X2 fix, intercept-only)",
        "null_mode": null_mode or "real",
        "sanity_y_nan": args.sanity_y_nan,
        "formula_sha256": formula_sha256,
        "fix_motivation": "X2 had Δ_CCC=-0.051 but Δ_MAE=-0.17 + D4_corr=+0.47. Slope=1 constraint preserves scale.",
        "duration_threshold_yr": DURATION_THRESHOLD,
        "stratum_info": info,
        "n_cohort": int(n),
        "baselines": {
            "loocv_ccc_iter34": ccc_base,
            "loocv_mae_iter34": mae_base,
            "loocv_pearson_iter34": pearson_base,
        },
        "corrected": {
            "loocv_ccc": ccc_corr,
            "loocv_mae": mae_corr,
            "loocv_pearson": pearson_corr,
            "delta_ccc": ccc_corr - ccc_base,
            "delta_mae": mae_corr - mae_base,
            "delta_pearson_r": pearson_corr - pearson_base,
        },
        "bootstrap_seed_A": boot_A,
        "bootstrap_seed_B": boot_B,
        "d4_audit": {"corr_correction_T1_sum_residual": corr_correction_resid},
        "verdict_provisional": _verdict(
            ccc_corr - ccc_base, boot_A["frac_pos"], boot_B["frac_pos"],
            mae_corr - mae_base, corr_correction_resid),
    }

    suffix = ""
    if null_mode: suffix = f"_{null_mode}"
    elif args.sanity_y_nan: suffix = "_sanityYnan"
    out_path = REPO / "results" / f"lockbox_t1_X2b_intercept_only_shift_{out['created_at_utc']}{suffix}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    log.info("wrote %s", out_path)

    print(f"\n=== X2b INTERCEPT-ONLY — {null_mode or 'real'}{' SANITY' if args.sanity_y_nan else ''} ===")
    print(f"baseline iter34 CCC = {ccc_base:.4f}, MAE = {mae_base:.4f}")
    print(f"corrected CCC = {ccc_corr:.4f}  Δ={ccc_corr - ccc_base:+.4f}")
    print(f"corrected MAE = {mae_corr:.4f}  Δ={mae_corr - mae_base:+.4f}")
    print(f"frac>0 seed_A={boot_A['frac_pos']:.3f}  seed_B={boot_B['frac_pos']:.3f}")
    print(f"D4 corr(correction, sum_resid) = {corr_correction_resid:+.4f}")
    print(f"Intercept long-stratum mean={info['mean_intercept_long']:+.4f}  short-stratum mean={info['mean_intercept_short']:+.4f}")
    print(f"VERDICT: {out['verdict_provisional']}")
    return 0


def _verdict(d, fA, fB, dmae, corr_sumres) -> str:
    if dmae > 0 and corr_sumres < 0:
        return "VARIANCE_COMPRESSION_MIRAGE_LIKELY"
    if d >= 0.005 and fA >= 0.95 and fB >= 0.95:
        return "PRIMARY_GATE_PASS_REPLICATED"
    if d >= 0.005 and (fA >= 0.95 or fB >= 0.95):
        return "PRIMARY_GATE_PASS_PARTIAL"
    if d > 0:
        return "POSITIVE_BUT_SUB_GATE"
    return "FAIL"


if __name__ == "__main__":
    sys.exit(main())
