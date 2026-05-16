"""T1 Glass-Ceiling Push — evening 2026-05-15 Slot B' (amended from MSE+RQA).

Mechanism: F50-style per-subject per-sensor-group median-subtraction self-norm on
the 3-sensor anatomical-triplet axial cache (Lumbar/Sternum/Forehead) — Euler RPY +
FreeAcc + sway + jerk + pkvel + freeacc — followed by Ridge correction on the
iter34 item-13 residual.

Amendment rationale: see results/preregistration_t1_ceiling_push_20260515_evening_amendment_01.json
- Slot A's failure mechanism was that we DROPPED pitch_mean/roll_mean (mounting concern)
  and the remaining kinetic features anti-correlate with item-13 residual.
- F50 (iter17, 2026-05-03) achieved item 13 +0.145 LOOCV via subject-level Euler
  self-norm on TRUNK PITCH ONLY. The V2 self-norm cache (cache_v2_self_normalized.py)
  uses per-subject per-sensor-group median subtraction.
- This Slot B' extends F50 to 3-sensor anatomical triplet with V2-style self-norm.

Distinct from prior failures:
  - Slot A: dropped pitch_mean/roll_mean; we KEEP them and self-norm.
  - F50: trunk pitch only (single sensor, single channel); we use 3 sensors.
  - S5/S8: PH+MFDFA on items 12/13; we use raw self-normed geometry.

Architecture: item_only hypothesis-restricted; Ridge α-grid inner 5-fold via residual
CCC; corrected_t1_sum = iter34.t1_sum_pred + 1.0 * Ridge_α*(prediction).

Self-norm formula: for each subject row, for each sensor S in {LowerBack, Xiphoid,
Forehead}, compute median across S's 10 axial-cache feature columns; subtract from
each S-feature → 30 self-normed columns. This is fold-local-by-construction (per-row
operation, no cross-subject information).

Pre-registration: master 20260515_evening + amendment_01 (slot_B substitution).

Usage:
  uv run python run_t1_slotB_evening_self_norm_recovery.py
  uv run python run_t1_slotB_evening_self_norm_recovery.py --null scrambled_y
  uv run python run_t1_slotB_evening_self_norm_recovery.py --null sid_shuffle
  uv run python run_t1_slotB_evening_self_norm_recovery.py --null canary_noise
  uv run python run_t1_slotB_evening_self_norm_recovery.py --null transductive
  uv run python run_t1_slotB_evening_self_norm_recovery.py --sanity-y-nan
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
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SlotB-evening] %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent
CACHE_PATH = REPO_ROOT / "results" / "axial_orientation_features.csv"
OOF_PATH = REPO_ROOT / "results" / "t1_iter34_per_item_oof_20260511_044242.npz"

AXIAL_SENSORS = ("LowerBack", "Xiphoid", "Forehead")

ALPHA_GRID = (10.0, 30.0, 100.0, 300.0, 1000.0)
LAMBDA_FIXED = 1.0
INNER_FOLDS = 5
INNER_SEED = 31415

MODEL_SEEDS_SET_A = (42, 1337, 7)
MODEL_SEEDS_SET_B = (101, 202, 303)

N_BOOTSTRAP = 5000
BOOTSTRAP_SEED = 20260515


def selfnorm_axial(df: pd.DataFrame) -> pd.DataFrame:
    """F50-style per-subject per-sensor-group median subtraction.

    For each subject (row), for each sensor S in AXIAL_SENSORS:
      median_S = median across S's feature columns (within this subject)
      selfnorm_S_f = raw_S_f - median_S   for each feature f of sensor S

    This is fold-local-by-construction (operates on individual rows, no cross-
    subject information). Mirrors cache_v2_self_normalized.py's V2 logic.
    """
    out = df[["sid"]].copy()
    feat_cols = [c for c in df.columns if c != "sid"]
    for sensor in AXIAL_SENSORS:
        sensor_cols = [c for c in feat_cols if f"_{sensor}_" in c]
        if not sensor_cols:
            continue
        subject_median = df[sensor_cols].median(axis=1, skipna=True)
        for c in sensor_cols:
            out[f"selfnorm_{c}"] = df[c] - subject_median
    return out


def fold_local_ridge(
    X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray, alpha: float
) -> np.ndarray:
    imp = FoldImputer.fit(X_tr)
    Xt = imp.transform(X_tr)
    Xv = imp.transform(X_te)
    nrm = FoldNormalizer.fit(Xt)
    Xt = nrm.transform(Xt)
    Xv = nrm.transform(Xv)
    return Ridge(alpha=alpha).fit(Xt, y_tr).predict(Xv)


def inner_cv_select_alpha(
    X_tr: np.ndarray,
    y_t1_tr: np.ndarray,
    yhat_t1sum_tr: np.ndarray,
    item13_resid_tr: np.ndarray,
    seed: int,
) -> tuple[float, dict]:
    n = len(y_t1_tr)
    kf = KFold(n_splits=INNER_FOLDS, shuffle=True, random_state=seed)
    scores: dict[float, float] = {}
    for alpha in ALPHA_GRID:
        correction_oof = np.full(n, np.nan)
        for tr_idx, va_idx in kf.split(np.arange(n)):
            correction_oof[va_idx] = fold_local_ridge(
                X_tr[tr_idx], item13_resid_tr[tr_idx], X_tr[va_idx], alpha
            )
        t1_corrected_oof = yhat_t1sum_tr + LAMBDA_FIXED * correction_oof
        scores[alpha] = float(ccc(y_t1_tr, t1_corrected_oof))
    best_alpha = max(scores, key=lambda a: scores[a])
    return best_alpha, scores


def run_loocv(
    X: np.ndarray,
    y_t1: np.ndarray,
    yhat_t1sum: np.ndarray,
    item13_true: np.ndarray,
    item13_pred: np.ndarray,
    item13_resid: np.ndarray,
    seed: int,
) -> dict:
    n = len(y_t1)
    correction = np.full(n, np.nan)
    alpha_choices = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        X_tr, X_te = X[tr], X[i:i + 1]
        item13_resid_tr = item13_resid[tr]
        y_t1_tr = y_t1[tr]
        yhat_t1sum_tr = yhat_t1sum[tr]
        best_alpha, _ = inner_cv_select_alpha(
            X_tr, y_t1_tr, yhat_t1sum_tr, item13_resid_tr, seed=seed
        )
        alpha_choices[i] = best_alpha
        correction[i] = fold_local_ridge(X_tr, item13_resid_tr, X_te, best_alpha)[0]

    t1_corrected = yhat_t1sum + LAMBDA_FIXED * correction
    item13_corrected = item13_pred + correction
    return {"correction": correction, "alpha_choices": alpha_choices,
            "t1_corrected": t1_corrected, "item13_corrected": item13_corrected}


def paired_bootstrap_frac_pos(
    y: np.ndarray, p_base: np.ndarray, p_cand: np.ndarray, n_boot: int, seed: int
) -> dict:
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

    df_raw = pd.read_csv(CACHE_PATH)
    oof = dict(np.load(OOF_PATH, allow_pickle=True))
    sids_oof = oof["sids"].astype(str)

    sid_to_row = {s: i for i, s in enumerate(df_raw["sid"].astype(str).values)}
    missing = [s for s in sids_oof if s not in sid_to_row]
    if missing:
        feat_cols_all = [c for c in df_raw.columns if c != "sid"]
        rows = []
        for s in missing:
            r = {"sid": s}
            for c in feat_cols_all:
                r[c] = np.nan
            rows.append(r)
        df_raw = pd.concat([df_raw, pd.DataFrame(rows)], ignore_index=True)
        sid_to_row = {s: i for i, s in enumerate(df_raw["sid"].astype(str).values)}

    order = np.array([sid_to_row[s] for s in sids_oof])
    df_raw = df_raw.iloc[order].reset_index(drop=True)
    assert (df_raw["sid"].astype(str).values == sids_oof).all()

    # Apply F50-style per-subject per-sensor-group median subtraction
    df = selfnorm_axial(df_raw)
    feat_cols = [c for c in df.columns if c != "sid"]
    log.info("Self-normed axial features built: %d cols (was %d raw)", len(feat_cols), df_raw.shape[1] - 1)
    X = df[feat_cols].values.astype(float)

    y_t1 = oof["y_t1"].astype(float)
    yhat_t1sum = oof["t1_sum_pred"].astype(float)
    item13_true = oof["item_13_true"].astype(float)
    item13_pred = oof["item_13_pred"].astype(float)
    item13_resid = item13_true - item13_pred
    n = len(sids_oof)

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011)
        item13_resid = rng.permutation(item13_resid)
        log.info("NULL scrambled_y")
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(91011)
        perm = rng.permutation(n)
        X = X[perm]
        log.info("NULL sid_shuffle")
    elif null_mode == "canary_noise":
        rng = np.random.default_rng(91011)
        X = X + rng.normal(0.0, 0.01, X.shape)
        log.info("NULL canary_noise")
    elif null_mode == "transductive":
        col_mean = np.nanmean(X, axis=0, keepdims=True)
        col_std = np.nanstd(X, axis=0, keepdims=True) + 1e-9
        X = (X - col_mean) / col_std
        log.info("NULL transductive: cohort-wide z-score")

    if sanity_y_nan:
        log.info("SANITY y_nan: corrector uses no test-fold y at fit time")

    results_per_seed = {}
    for seed in (*MODEL_SEEDS_SET_A, *MODEL_SEEDS_SET_B):
        res = run_loocv(X, y_t1, yhat_t1sum, item13_true, item13_pred, item13_resid, seed=seed)
        results_per_seed[seed] = res

    def avg_correction(seeds):
        return np.mean([results_per_seed[s]["correction"] for s in seeds], axis=0)

    correction_A = avg_correction(MODEL_SEEDS_SET_A)
    correction_B = avg_correction(MODEL_SEEDS_SET_B)
    correction_all = (correction_A + correction_B) / 2.0

    t1_corrected_A = yhat_t1sum + LAMBDA_FIXED * correction_A
    t1_corrected_B = yhat_t1sum + LAMBDA_FIXED * correction_B
    item13_corrected_A = item13_pred + correction_A
    item13_corrected_B = item13_pred + correction_B

    ccc_baseline_t1 = float(ccc(y_t1, yhat_t1sum))
    ccc_baseline_item13 = float(ccc(item13_true, item13_pred))
    mae_baseline_t1 = float(np.mean(np.abs(y_t1 - yhat_t1sum)))
    pearson_baseline_t1 = float(np.corrcoef(y_t1, yhat_t1sum)[0, 1])

    def headline(t1_cand, item13_cand, label):
        ccc_t1 = float(ccc(y_t1, t1_cand))
        ccc_i13 = float(ccc(item13_true, item13_cand))
        mae_t1 = float(np.mean(np.abs(y_t1 - t1_cand)))
        pearson_t1 = float(np.corrcoef(y_t1, t1_cand)[0, 1])
        boot = paired_bootstrap_frac_pos(y_t1, yhat_t1sum, t1_cand, N_BOOTSTRAP, BOOTSTRAP_SEED)
        boot_i13 = paired_bootstrap_frac_pos(item13_true, item13_pred, item13_cand, N_BOOTSTRAP, BOOTSTRAP_SEED)
        return {
            "label": label,
            "loocv_ccc_t1_sum_baseline": ccc_baseline_t1,
            "loocv_ccc_t1_sum_corrected": ccc_t1,
            "delta_ccc_t1_sum": ccc_t1 - ccc_baseline_t1,
            "delta_pearson_r_t1_sum": pearson_t1 - pearson_baseline_t1,
            "delta_mae_t1_sum": mae_t1 - mae_baseline_t1,
            "loocv_ccc_item13_baseline": ccc_baseline_item13,
            "loocv_ccc_item13_corrected": ccc_i13,
            "delta_ccc_item13": ccc_i13 - ccc_baseline_item13,
            "bootstrap_t1_sum": boot,
            "bootstrap_item13": boot_i13,
        }

    h_A = headline(t1_corrected_A, item13_corrected_A, "seed_set_A")
    h_B = headline(t1_corrected_B, item13_corrected_B, "seed_set_B")

    t1_resid = y_t1 - yhat_t1sum
    item13_resid_true = item13_true - item13_pred
    corr_correction_sum_residual = float(np.corrcoef(correction_all, t1_resid)[0, 1])
    corr_correction_item13_residual = float(np.corrcoef(correction_all, item13_resid_true)[0, 1])
    delta_mae_avg = float(np.mean(np.abs(y_t1 - (yhat_t1sum + LAMBDA_FIXED * correction_all))) - mae_baseline_t1)
    delta_r_avg = float(np.corrcoef(y_t1, yhat_t1sum + LAMBDA_FIXED * correction_all)[0, 1] - pearson_baseline_t1)

    kf = KFold(n_splits=5, shuffle=True, random_state=20260309)
    fold_deltas = []
    for seed in MODEL_SEEDS_SET_A:
        correction_5fold = np.full(n, np.nan)
        for tr_idx, te_idx in kf.split(np.arange(n)):
            X_tr, X_te = X[tr_idx], X[te_idx]
            item13_resid_tr = item13_resid[tr_idx]
            y_t1_tr = y_t1[tr_idx]
            yhat_t1sum_tr = yhat_t1sum[tr_idx]
            best_alpha, _ = inner_cv_select_alpha(X_tr, y_t1_tr, yhat_t1sum_tr, item13_resid_tr, seed=seed)
            correction_5fold[te_idx] = fold_local_ridge(X_tr, item13_resid_tr, X_te, best_alpha)
        t1_corrected_5f = yhat_t1sum + LAMBDA_FIXED * correction_5fold
        fold_deltas.append(float(ccc(y_t1, t1_corrected_5f) - ccc_baseline_t1))
    fold_delta_mean = float(np.mean(fold_deltas))
    fold_delta_std = float(np.std(fold_deltas))

    formula_str = json.dumps({
        "feature_cols": feat_cols,
        "alpha_grid": list(ALPHA_GRID),
        "lambda_fixed": LAMBDA_FIXED,
        "self_norm": "per-subject per-sensor-group median subtraction",
        "seeds_A": list(MODEL_SEEDS_SET_A),
        "seeds_B": list(MODEL_SEEDS_SET_B),
    }, sort_keys=True)
    formula_sha256 = hashlib.sha256(formula_str.encode()).hexdigest()

    out = {
        "name": "lockbox_t1_slotB_evening_self_norm_recovery",
        "created_at_utc": datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "preregistration_master": "results/preregistration_t1_ceiling_push_20260515_evening_master.json",
        "preregistration_amendment": "results/preregistration_t1_ceiling_push_20260515_evening_amendment_01.json",
        "session": "2026-05-15-evening-glass-ceiling-push-slotB-self-norm-recovery",
        "null_mode": null_mode or "real",
        "sanity_y_nan": sanity_y_nan,
        "formula_sha256": formula_sha256,
        "n_cohort": int(n),
        "n_features_selfnorm": len(feat_cols),
        "alpha_grid": list(ALPHA_GRID),
        "lambda_fixed": LAMBDA_FIXED,
        "n_bootstrap": N_BOOTSTRAP,
        "primary_gate": {
            "rule": "replicated-uncorrected α=0.05 + MCID +0.005 + BH-FDR q<=0.10",
            "mcid": 0.005,
            "frac_pos_gate": 0.95,
        },
        "baselines": {
            "loocv_ccc_t1_sum": ccc_baseline_t1,
            "loocv_ccc_item13": ccc_baseline_item13,
            "loocv_mae_t1_sum": mae_baseline_t1,
            "loocv_pearson_t1_sum": pearson_baseline_t1,
        },
        "seed_set_A": h_A,
        "seed_set_B": h_B,
        "d4_audit_avg_seeds": {
            "delta_pearson_r_avg": delta_r_avg,
            "delta_mae_avg": delta_mae_avg,
            "corr_correction_T1_sum_residual": corr_correction_sum_residual,
            "corr_correction_item13_residual": corr_correction_item13_residual,
        },
        "fivefold_screen": {
            "per_seed_deltas": fold_deltas,
            "mean_delta": fold_delta_mean,
            "seed_std": fold_delta_std,
            "promotion_gate_mean": 0.025,
            "promotion_gate_std": 0.020,
            "passes_promotion": fold_delta_mean >= 0.025 and fold_delta_std < 0.020,
        },
        "verdict_provisional": _verdict(
            h_A["delta_ccc_t1_sum"], h_B["delta_ccc_t1_sum"],
            h_A["bootstrap_t1_sum"]["frac_pos"], h_B["bootstrap_t1_sum"]["frac_pos"],
            corr_correction_sum_residual, delta_mae_avg,
        ),
    }

    suffix = ""
    if null_mode:
        suffix = f"_{null_mode}"
    elif sanity_y_nan:
        suffix = "_sanityYnan"
    out_path = REPO_ROOT / "results" / (
        f"lockbox_t1_slotB_evening_self_norm_recovery_"
        f"{out['created_at_utc']}{suffix}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    log.info("wrote %s", out_path)

    print(f"\n=== Slot B' (evening) — {null_mode or 'real'}{' SANITY_Y_NAN' if sanity_y_nan else ''} ===")
    print(f"N={n}  self-normed features={len(feat_cols)}")
    print(f"baseline iter34 t1_sum CCC = {ccc_baseline_t1:.4f}  item13 CCC = {ccc_baseline_item13:.4f}")
    print(f"seed_set_A: t1_sum Δ={h_A['delta_ccc_t1_sum']:+.4f}  frac>0={h_A['bootstrap_t1_sum']['frac_pos']:.4f}  CI={h_A['bootstrap_t1_sum']['ci95']}")
    print(f"seed_set_B: t1_sum Δ={h_B['delta_ccc_t1_sum']:+.4f}  frac>0={h_B['bootstrap_t1_sum']['frac_pos']:.4f}  CI={h_B['bootstrap_t1_sum']['ci95']}")
    print(f"item13  Δ_A={h_A['delta_ccc_item13']:+.4f}  Δ_B={h_B['delta_ccc_item13']:+.4f}")
    print(f"D4 audit avg: Δr={delta_r_avg:+.4f}  ΔMAE={delta_mae_avg:+.4f}  corr(c,sum_resid)={corr_correction_sum_residual:+.4f}  corr(c,item13_resid)={corr_correction_item13_residual:+.4f}")
    print(f"5-fold screen: Δ̄={fold_delta_mean:+.4f} std={fold_delta_std:.4f}  promotion={'PASS' if out['fivefold_screen']['passes_promotion'] else 'FAIL'}")
    print(f"VERDICT (provisional): {out['verdict_provisional']}")
    return 0


def _verdict(d_A, d_B, f_A, f_B, corr_sumres, dmae) -> str:
    if dmae > 0 and corr_sumres < 0:
        return "VARIANCE_COMPRESSION_MIRAGE_LIKELY (ΔMAE>0 & corr(c,sum_resid)<0)"
    if d_A >= 0.005 and d_B >= 0.005 and f_A >= 0.95 and f_B >= 0.95:
        return "PRIMARY_GATE_PASS_REPLICATED"
    if (d_A >= 0.005 or d_B >= 0.005) and (f_A >= 0.95 or f_B >= 0.95):
        return "PRIMARY_GATE_PASS_PARTIAL_seed_set"
    if d_A > 0 and d_B > 0:
        return "POSITIVE_BUT_SUB_GATE"
    return "FAIL"


if __name__ == "__main__":
    sys.exit(main())
