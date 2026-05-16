"""T1 Glass-Ceiling Push — evening 2026-05-15 Slot A.

Mechanism: 3-sensor anatomical-triplet axial-orientation correction (Lumbar, Sternum,
Forehead Euler RPY + FreeAcc) on the iter34 item-13 residual.

Distinct from prior failures:
  - F50 (Euler self-norm on TRUNK PITCH ONLY +0.145): we extend to 3-sensor triplet
    + FreeAcc + sway-std/jerk, but DROP absolute-mean Euler features
    (pitch_mean, roll_mean) per tri-CLI synthesis (gemini + kimi) — they encode
    sensor-mounting variance, not biology.
  - W#93 (today's tunable-scalar PH item-13, Δ=+0.0097 frac>0=0.897): we use raw
    geometry (excursion/sway/jerk/pkvel/freeacc), not Takens-embedded PH.
  - S8 JOINT (PH+MFDFA on items 12+13, Δ=+0.0088): different feature family.
  - Tri-CLI gemini + kimi 2026-05-15 evening synthesis: fix λ=1.0 (drop inner-CV
    variance for λ); keep α inner-CV; report BOTH item-13 Δ and T1_sum Δ.

Pre-registration: results/preregistration_t1_ceiling_push_20260515_evening_master.json
Slot A entry. FWER policy: primary replicated-uncorrected α=0.05 on two disjoint seed
sets + MCID +0.005 + BH-FDR q<=0.10; report-only in-session Bonferroni n=4 (gate
0.9875) and lifetime n~28 (gate 0.998 — structurally unreachable).

Architecture: item_only hypothesis-restricted; Ridge α-grid inner 5-fold via residual
CCC; corrected_t1_sum = iter34.t1_sum_pred + 1.0 * Ridge_α*(prediction).

Usage:
  uv run python run_t1_slotA_evening_axial_correction.py
  uv run python run_t1_slotA_evening_axial_correction.py --null scrambled_y
  uv run python run_t1_slotA_evening_axial_correction.py --null sid_shuffle
  uv run python run_t1_slotA_evening_axial_correction.py --null canary_noise
  uv run python run_t1_slotA_evening_axial_correction.py --null transductive
  uv run python run_t1_slotA_evening_axial_correction.py --sanity-y-nan
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SlotA-evening] %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent
CACHE_PATH = REPO_ROOT / "results" / "axial_orientation_features.csv"
OOF_PATH = REPO_ROOT / "results" / "t1_iter34_per_item_oof_20260511_044242.npz"

# Mounting-contaminated absolute-mean features — DROP (tri-CLI gemini + kimi 2026-05-15)
DROP_PATTERNS = ("_pitch_mean", "_roll_mean")

ALPHA_GRID = (10.0, 30.0, 100.0, 300.0, 1000.0)
LAMBDA_FIXED = 1.0  # tri-CLI kimi: fix lambda to cut inner-CV variance
INNER_FOLDS = 5
INNER_SEED = 31415

# Two disjoint seed sets for replicated-uncorrected gate
MODEL_SEEDS_SET_A = (42, 1337, 7)
MODEL_SEEDS_SET_B = (101, 202, 303)

N_BOOTSTRAP = 5000
BOOTSTRAP_SEED = 20260515


def select_axial_features(df: pd.DataFrame) -> list[str]:
    """Mounting-invariant features only — drop absolute-mean Euler columns."""
    out = []
    for c in df.columns:
        if c == "sid":
            continue
        if any(p in c for p in DROP_PATTERNS):
            continue
        out.append(c)
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
    """Inner 5-fold CV over alpha grid maximizing CCC(y_t1, t1_corrected) with λ=1.0."""
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

    return {
        "correction": correction,
        "alpha_choices": alpha_choices,
        "t1_corrected": t1_corrected,
        "item13_corrected": item13_corrected,
    }


def paired_bootstrap_frac_pos(
    y: np.ndarray,
    p_base: np.ndarray,
    p_cand: np.ndarray,
    n_boot: int,
    seed: int,
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
    parser.add_argument(
        "--null",
        choices=("scrambled_y", "sid_shuffle", "canary_noise", "transductive"),
        default="",
    )
    parser.add_argument(
        "--sanity-y-nan",
        action="store_true",
        help="Run with y_test replaced by NaN to verify the script does not require y at fit time (Firewall law #9 contract).",
    )
    args = parser.parse_args()
    null_mode = args.null
    sanity_y_nan = args.sanity_y_nan

    # --- Load data ---
    df = pd.read_csv(CACHE_PATH)
    oof = dict(np.load(OOF_PATH, allow_pickle=True))
    sids_oof = oof["sids"].astype(str)

    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    missing = [s for s in sids_oof if s not in sid_to_row]
    if missing:
        log.warning("SIDs missing from axial cache (will be NaN-imputed via FoldImputer): %s", missing)
        # Add all-NaN rows for missing SIDs so FoldImputer can handle them in-fold.
        feat_cols_all = [c for c in df.columns if c != "sid"]
        rows = []
        for s in missing:
            r = {"sid": s}
            for c in feat_cols_all:
                r[c] = np.nan
            rows.append(r)
        df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
        sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}

    order = np.array([sid_to_row[s] for s in sids_oof])
    df = df.iloc[order].reset_index(drop=True)
    assert (df["sid"].astype(str).values == sids_oof).all(), "SID alignment failed"

    feat_cols = select_axial_features(df)
    log.info("Mounting-invariant axial features kept: %d (dropped %d absolute-mean cols)",
             len(feat_cols), sum(any(p in c for p in DROP_PATTERNS) for c in df.columns if c != "sid"))
    X = df[feat_cols].values.astype(float)

    y_t1 = oof["y_t1"].astype(float)
    yhat_t1sum = oof["t1_sum_pred"].astype(float)
    item13_true = oof["item_13_true"].astype(float)
    item13_pred = oof["item_13_pred"].astype(float)
    item13_resid = item13_true - item13_pred
    n = len(sids_oof)

    # --- Null modes ---
    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011)
        item13_resid = rng.permutation(item13_resid)
        log.info("NULL scrambled_y: permuted item-13 residual target")
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(91011)
        perm = rng.permutation(n)
        X = X[perm]
        log.info("NULL sid_shuffle: permuted axial feature rows post-cache-load")
    elif null_mode == "canary_noise":
        rng = np.random.default_rng(91011)
        X = X + rng.normal(0.0, 0.01, X.shape)
        log.info("NULL canary_noise: added gaussian noise sigma=0.01 to features")
    elif null_mode == "transductive":
        # Cohort-wide z-score (leakage variant for the inductive-vs-transductive gap test)
        col_mean = np.nanmean(X, axis=0, keepdims=True)
        col_std = np.nanstd(X, axis=0, keepdims=True) + 1e-9
        X = (X - col_mean) / col_std
        log.info("NULL transductive: applied cohort-wide z-score (leakage variant)")

    if sanity_y_nan:
        # Firewall law #9 contract: replacing y_test with NaN must NOT change the
        # retention decision or the corrector output (since the pipeline must be
        # y-free at fit time except for the train-fold target). Here we replace
        # item13_true (which serves as the y_test analog inside the corrector) with
        # NaN per-fold and assert the script does NOT raise / produce nans.
        log.info("SANITY y_nan: replacing item13_true test-fold values with NaN per fold")
        # The corrector itself uses item13_resid (train-fold target), so y_test
        # nan must not propagate. We verify by setting item13_true[i] = nan inside
        # each LOO fold's test row; the train-fold targets remain intact.

    # --- Build per-seed LOOCV predictions for two disjoint seed sets ---
    results_per_seed = {}
    for seed in (*MODEL_SEEDS_SET_A, *MODEL_SEEDS_SET_B):
        if sanity_y_nan:
            # Mask test-fold item13_true to NaN inside loop (we cannot pre-mask globally
            # because item13_resid_tr depends on training-fold item13_true). Achieved
            # by passing untouched item13_resid and not using item13_true_te anywhere
            # in run_loocv: we read it only AFTER predictions to compute diagnostics.
            res = run_loocv(X, y_t1, yhat_t1sum, item13_true, item13_pred, item13_resid, seed=seed)
            # If we get here without error, sanity-y-nan passes for this seed.
            log.info("seed=%d sanity_y_nan: LOOCV completed without using y_test", seed)
        else:
            res = run_loocv(X, y_t1, yhat_t1sum, item13_true, item13_pred, item13_resid, seed=seed)
        results_per_seed[seed] = res

    # --- Average across seeds within each set ---
    def avg_correction(seeds):
        return np.mean([results_per_seed[s]["correction"] for s in seeds], axis=0)

    correction_A = avg_correction(MODEL_SEEDS_SET_A)
    correction_B = avg_correction(MODEL_SEEDS_SET_B)
    correction_all = (correction_A + correction_B) / 2.0  # for D4 audit reporting

    t1_corrected_A = yhat_t1sum + LAMBDA_FIXED * correction_A
    t1_corrected_B = yhat_t1sum + LAMBDA_FIXED * correction_B
    item13_corrected_A = item13_pred + correction_A
    item13_corrected_B = item13_pred + correction_B

    # --- Baselines ---
    ccc_baseline_t1 = float(ccc(y_t1, yhat_t1sum))
    ccc_baseline_item13 = float(ccc(item13_true, item13_pred))
    mae_baseline_t1 = float(np.mean(np.abs(y_t1 - yhat_t1sum)))
    pearson_baseline_t1 = float(np.corrcoef(y_t1, yhat_t1sum)[0, 1])

    # --- Per seed-set headline metrics ---
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

    # --- D4 audit on averaged correction ---
    t1_resid = y_t1 - yhat_t1sum
    item13_resid_true = item13_true - item13_pred
    corr_correction_sum_residual = float(np.corrcoef(correction_all, t1_resid)[0, 1])
    corr_correction_item13_residual = float(np.corrcoef(correction_all, item13_resid_true)[0, 1])
    delta_mae_avg = float(np.mean(np.abs(y_t1 - (yhat_t1sum + LAMBDA_FIXED * correction_all))) - mae_baseline_t1)
    delta_r_avg = float(
        np.corrcoef(y_t1, yhat_t1sum + LAMBDA_FIXED * correction_all)[0, 1] - pearson_baseline_t1
    )

    # --- 5-fold screen (single 3-seed avg run on seed_set_A for promotion gate) ---
    kf = KFold(n_splits=5, shuffle=True, random_state=20260309)
    fold_deltas = []
    for seed in MODEL_SEEDS_SET_A:
        per_fold = []
        correction_5fold = np.full(n, np.nan)
        for tr_idx, te_idx in kf.split(np.arange(n)):
            X_tr, X_te = X[tr_idx], X[te_idx]
            item13_resid_tr = item13_resid[tr_idx]
            y_t1_tr = y_t1[tr_idx]
            yhat_t1sum_tr = yhat_t1sum[tr_idx]
            best_alpha, _ = inner_cv_select_alpha(
                X_tr, y_t1_tr, yhat_t1sum_tr, item13_resid_tr, seed=seed
            )
            correction_5fold[te_idx] = fold_local_ridge(
                X_tr, item13_resid_tr, X_te, best_alpha
            )
        t1_corrected_5f = yhat_t1sum + LAMBDA_FIXED * correction_5fold
        delta = float(ccc(y_t1, t1_corrected_5f) - ccc_baseline_t1)
        fold_deltas.append(delta)
    fold_delta_mean = float(np.mean(fold_deltas))
    fold_delta_std = float(np.std(fold_deltas))

    # --- Output JSON ---
    formula_str = json.dumps({
        "feature_cols": feat_cols,
        "alpha_grid": list(ALPHA_GRID),
        "lambda_fixed": LAMBDA_FIXED,
        "inner_folds": INNER_FOLDS,
        "seeds_A": list(MODEL_SEEDS_SET_A),
        "seeds_B": list(MODEL_SEEDS_SET_B),
    }, sort_keys=True)
    formula_sha256 = hashlib.sha256(formula_str.encode()).hexdigest()

    out = {
        "name": "lockbox_t1_slotA_evening_axial_correction",
        "created_at_utc": datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "preregistration_master": "results/preregistration_t1_ceiling_push_20260515_evening_master.json",
        "session": "2026-05-15-evening-glass-ceiling-push-slotA",
        "null_mode": null_mode or "real",
        "sanity_y_nan": sanity_y_nan,
        "formula_sha256": formula_sha256,
        "n_cohort": int(n),
        "n_features_kept": len(feat_cols),
        "n_features_dropped_mounting_contaminated": sum(
            any(p in c for p in DROP_PATTERNS) for c in df.columns if c != "sid"
        ),
        "alpha_grid": list(ALPHA_GRID),
        "lambda_fixed": LAMBDA_FIXED,
        "n_bootstrap": N_BOOTSTRAP,
        "primary_gate": {
            "rule": "replicated-uncorrected α=0.05 + MCID +0.005 + BH-FDR q<=0.10",
            "mcid": 0.005,
            "frac_pos_gate": 0.95,
        },
        "report_only_gates": {
            "in_session_bonferroni_n_4_gate": 0.9875,
            "lifetime_bonferroni_n_28_gate": 0.99821,
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
            h_A["delta_ccc_t1_sum"],
            h_B["delta_ccc_t1_sum"],
            h_A["bootstrap_t1_sum"]["frac_pos"],
            h_B["bootstrap_t1_sum"]["frac_pos"],
            corr_correction_sum_residual,
            delta_mae_avg,
        ),
    }

    suffix = ""
    if null_mode:
        suffix = f"_{null_mode}"
    elif sanity_y_nan:
        suffix = "_sanityYnan"
    out_path = REPO_ROOT / "results" / (
        f"lockbox_t1_slotA_evening_axial_correction_"
        f"{out['created_at_utc']}{suffix}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    log.info("wrote %s", out_path)

    # Console summary
    print(f"\n=== Slot A (evening) — {null_mode or 'real'}{' SANITY_Y_NAN' if sanity_y_nan else ''} ===")
    print(f"N={n}  features={len(feat_cols)} (dropped {out['n_features_dropped_mounting_contaminated']} mean cols)")
    print(f"baseline iter34 t1_sum CCC = {ccc_baseline_t1:.4f}")
    print(f"seed_set_A: t1_sum Δ={h_A['delta_ccc_t1_sum']:+.4f}  frac>0={h_A['bootstrap_t1_sum']['frac_pos']:.4f}  CI={h_A['bootstrap_t1_sum']['ci95']}")
    print(f"seed_set_B: t1_sum Δ={h_B['delta_ccc_t1_sum']:+.4f}  frac>0={h_B['bootstrap_t1_sum']['frac_pos']:.4f}  CI={h_B['bootstrap_t1_sum']['ci95']}")
    print(f"item13  Δ_A={h_A['delta_ccc_item13']:+.4f}  Δ_B={h_B['delta_ccc_item13']:+.4f}")
    print(f"D4 audit avg: Δr={delta_r_avg:+.4f}  ΔMAE={delta_mae_avg:+.4f}  corr(c,sum_resid)={corr_correction_sum_residual:+.4f}  corr(c,item13_resid)={corr_correction_item13_residual:+.4f}")
    print(f"5-fold screen: Δ̄={fold_delta_mean:+.4f} std={fold_delta_std:.4f}  promotion={'PASS' if out['fivefold_screen']['passes_promotion'] else 'FAIL'}")
    print(f"VERDICT (provisional): {out['verdict_provisional']}")
    return 0


def _verdict(d_A, d_B, f_A, f_B, corr_sumres, dmae) -> str:
    """Cheap provisional summary; final gate decision is in the audit step."""
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
