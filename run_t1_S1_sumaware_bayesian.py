"""T1 Slot S1: Sum-aware joint Bayesian Ridge correction on per-item residuals.

Hypothesis (pre-reg `preregistration_t1t3_proresults_ablation_20260515T133800Z`):
Iter34 per-item PH/MFDFA residual lifts failed to compound into T1 sum because
per-item independent Ridges double-count covariance. A joint sum-aware
multi-output Bayesian Ridge with an explicit ``lambda_sum * (r_sum - Z @ sum_j B_j)^2``
penalty should lift T1 LOOCV CCC by +0.015..+0.035 over iter34 0.7170.

Implementation of the sum-aware objective (data-augmentation trick):
  For each item j in {9..14} fit `sklearn.linear_model.BayesianRidge` on
  ``[Z_train; w * Z_train_full]`` against ``[r_j_train; w * r_sum_train / J]``
  with ``w = sqrt(lambda_sum)`` and ``J = 6`` items. The augmented rows act
  as a soft equality constraint ``sum_j Z @ B_j ≈ r_sum_train``: since each
  per-item model receives the same augmented row scaled by ``1/J``, the
  posterior means of B_j summed across j approximately satisfy that constraint
  in expectation, while BayesianRidge's empirical-Bayes shrinkage estimates a
  shared inverse-variance ``alpha_j`` per item. (Augmented-target ridge is the
  standard primal trick; see Hastie/Tibshirani/Friedman §3.4.)

Pre-reg constants:
  split_seed=20260309, feature_seed=31415, model_seed_list=[42,1337,7]
  lambda_sum grid: [0.0, 1.0, 5.0, 10.0]
  Inner-CV selection: 5-fold OOF T1_sum CCC on train rows ONLY.

Kill threshold: 5-fold mean Δ < 0 across 3 seeds OR seed_std > 0.020 OR
                5-null gate fails (N1 scrambled-y or N2 SID-shuffle).

Firewall:
  - FoldImputer + FoldNormalizer fit on TRAIN ONLY (outer + every inner fold).
  - lambda_sum chosen via inner 5-fold on train rows only.
  - No outer test y leaks into any fit step.
  - Z is target-free at construction (subject-level mean of feature columns).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import BayesianRidge
from sklearn.model_selection import KFold

from eval_utils import lins_ccc as ccc
from inductive_lib import FoldImputer, FoldNormalizer

ITER34_OOF_NPZ = "results/t1_iter34_per_item_oof_20260511_044242.npz"
PH_CACHE = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"

ITEM_IDS = [9, 10, 11, 12, 13, 14]
J = len(ITEM_IDS)
LAMBDA_GRID = [0.0, 1.0, 5.0, 10.0]
SPLIT_SEED = 20260309
FEATURE_SEED = 31415  # noqa: F841 — recorded in lockbox, no stochastic feature step
MODEL_SEEDS = [42, 1337, 7]
N_BOOTSTRAP = 2000
INNER_K = 5
OUTER_K = 5

MFDFA_SUFFIXES = (
    "_mfdfa_trunk_pitch_delta_alpha",
    "_mfdfa_trunk_pitch_hurst_q2",
    "_mfdfa_trunk_pitch_h_range",
    "_mfdfa_trunk_pitch_asymmetry",
)
PH_SUFFIXES = ("_ph_trunk_pitch_h1_", "_ph_sacrum_ang_h1_")


def build_factor_block(df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Build target-free 6-column subject-level Z by pooling task columns.

    4 MFDFA subfamilies (delta_alpha, hurst_q2, h_range, asymmetry) on
    trunk_pitch + 2 PH subfamilies (trunk_pitch_h1, sacrum_ang_h1, max+med
    pooled). All means are over task columns, no labels involved.
    """
    cols = df.columns.tolist()
    blocks: list[np.ndarray] = []
    names: list[str] = []
    for suf in MFDFA_SUFFIXES:
        members = [c for c in cols if c.endswith(suf)]
        if not members:
            continue
        blocks.append(df[members].mean(axis=1).values.astype(float))
        names.append(f"mean_task{suf}")
    for suf in PH_SUFFIXES:
        members = [c for c in cols if suf in c]
        if not members:
            continue
        blocks.append(df[members].mean(axis=1).values.astype(float))
        names.append(f"mean_task_{suf.strip('_')}_maxmed_pooled")
    Z = np.column_stack(blocks)
    return Z, names


def load_aligned() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Return sids, y_t1, t1_iter34_pred, R (residual matrix Nx6), Z (Nx6), z_names."""
    iter34 = dict(np.load(ITER34_OOF_NPZ, allow_pickle=True))
    sids = iter34["sids"].astype(str)
    y_t1 = iter34["y_t1"].astype(float)
    t1_pred = iter34["t1_sum_pred"].astype(float)

    R = np.column_stack([
        iter34[f"item_{j}_true"].astype(float) - iter34[f"item_{j}_pred"].astype(float)
        for j in ITEM_IDS
    ])

    df = pd.read_csv(PH_CACHE)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids])
    df = df.iloc[order].reset_index(drop=True)
    assert (df["sid"].astype(str).values == sids).all(), "SID alignment broke"

    Z, z_names = build_factor_block(df)
    assert Z.shape[0] == len(sids)
    return sids, y_t1, t1_pred, R, Z, z_names


def fit_joint_sumaware(
    Z_tr: np.ndarray,
    R_tr: np.ndarray,
    r_sum_tr: np.ndarray,
    lambda_sum: float,
) -> list[BayesianRidge]:
    """Fit J per-item BayesianRidge models with augmented sum-aware rows.

    Each item j is fit on stacked design ``[Z_tr; w * Z_tr]`` against
    ``[r_j_tr; w * r_sum_tr / J]`` with ``w = sqrt(lambda_sum)``. This adds a
    soft constraint that the average of each item's predictions matches
    1/J of the row sum residual, encouraging the summed coefficient to track
    the observed r_sum.
    """
    n, p = Z_tr.shape
    models: list[BayesianRidge] = []
    if lambda_sum <= 0.0:
        for j in range(J):
            br = BayesianRidge(fit_intercept=True, max_iter=300, tol=1e-4)
            br.fit(Z_tr, R_tr[:, j])
            models.append(br)
        return models
    w = float(np.sqrt(lambda_sum))
    Z_aug = np.vstack([Z_tr, w * Z_tr])
    sum_target = w * (r_sum_tr / J)
    for j in range(J):
        y_aug = np.concatenate([R_tr[:, j], sum_target])
        br = BayesianRidge(fit_intercept=True, max_iter=300, tol=1e-4)
        br.fit(Z_aug, y_aug)
        models.append(br)
    return models


def predict_joint(models: list[BayesianRidge], Z: np.ndarray) -> np.ndarray:
    """Per-item predicted residual corrections, shape (n, J)."""
    return np.column_stack([m.predict(Z) for m in models])


def inner_select_lambda(
    Z_train: np.ndarray,
    R_train: np.ndarray,
    iter34_t1_train: np.ndarray,
    y_t1_train: np.ndarray,
    seed: int,
) -> float:
    """Select lambda_sum via inner 5-fold OOF T1 sum CCC on train rows only."""
    n = Z_train.shape[0]
    r_sum_train = R_train.sum(axis=1)
    best_lam, best_ccc = LAMBDA_GRID[0], -np.inf
    for lam in LAMBDA_GRID:
        kf = KFold(n_splits=INNER_K, shuffle=True, random_state=seed)
        oof_correction_sum = np.zeros(n)
        for tr_idx, va_idx in kf.split(np.arange(n)):
            imp = FoldImputer.fit(Z_train[tr_idx])
            Zt = imp.transform(Z_train[tr_idx])
            Zv = imp.transform(Z_train[va_idx])
            nrm = FoldNormalizer.fit(Zt)
            Zt = nrm.transform(Zt)
            Zv = nrm.transform(Zv)
            models = fit_joint_sumaware(Zt, R_train[tr_idx], r_sum_train[tr_idx], lam)
            preds = predict_joint(models, Zv)
            oof_correction_sum[va_idx] = preds.sum(axis=1)
        t1_corrected = iter34_t1_train + oof_correction_sum
        c = float(ccc(y_t1_train, t1_corrected))
        if c > best_ccc:
            best_ccc, best_lam = c, lam
    return best_lam


def loocv_corrected(
    Z: np.ndarray,
    R: np.ndarray,
    iter34_t1: np.ndarray,
    y_t1: np.ndarray,
    inner_seed: int,
) -> tuple[np.ndarray, list[float]]:
    """LOOCV: at each held-out subject, select lambda via inner 5-fold then refit."""
    n = Z.shape[0]
    corrected = np.full(n, np.nan)
    selected_lambdas: list[float] = []
    for i in range(n):
        tr = np.arange(n) != i
        Z_tr_raw, Z_te_raw = Z[tr], Z[i:i + 1]
        R_tr = R[tr]

        lam = inner_select_lambda(
            Z_tr_raw, R_tr, iter34_t1[tr], y_t1[tr], seed=inner_seed
        )
        selected_lambdas.append(lam)

        imp = FoldImputer.fit(Z_tr_raw)
        Zt = imp.transform(Z_tr_raw)
        Zv = imp.transform(Z_te_raw)
        nrm = FoldNormalizer.fit(Zt)
        Zt = nrm.transform(Zt)
        Zv = nrm.transform(Zv)
        models = fit_joint_sumaware(Zt, R_tr, R_tr.sum(axis=1), lam)
        delta_pred = predict_joint(models, Zv).sum(axis=1)[0]
        corrected[i] = iter34_t1[i] + delta_pred
        if (i + 1) % 10 == 0 or i == n - 1:
            print(f"[S1 LOOCV] {i + 1}/{n}  lam_chosen={lam}")
    return corrected, selected_lambdas


def fivefold_corrected_predictions(
    Z: np.ndarray,
    R: np.ndarray,
    iter34_t1: np.ndarray,
    y_t1: np.ndarray,
    seed: int,
) -> np.ndarray:
    """5-fold OOF corrected T1 predictions under a single outer split seed."""
    n = Z.shape[0]
    kf = KFold(n_splits=OUTER_K, shuffle=True, random_state=seed)
    oof = np.zeros(n)
    for tr_idx, va_idx in kf.split(np.arange(n)):
        Z_tr_raw, Z_va_raw = Z[tr_idx], Z[va_idx]
        R_tr = R[tr_idx]
        lam = inner_select_lambda(
            Z_tr_raw, R_tr, iter34_t1[tr_idx], y_t1[tr_idx], seed=seed
        )
        imp = FoldImputer.fit(Z_tr_raw)
        Zt = imp.transform(Z_tr_raw)
        Zv = imp.transform(Z_va_raw)
        nrm = FoldNormalizer.fit(Zt)
        Zt = nrm.transform(Zt)
        Zv = nrm.transform(Zv)
        models = fit_joint_sumaware(Zt, R_tr, R_tr.sum(axis=1), lam)
        delta = predict_joint(models, Zv).sum(axis=1)
        oof[va_idx] = iter34_t1[va_idx] + delta
    return oof


def fivefold_corrected(
    Z: np.ndarray,
    R: np.ndarray,
    iter34_t1: np.ndarray,
    y_t1: np.ndarray,
    seed: int,
) -> float:
    """5-fold OOF T1 CCC under a single outer split seed."""
    oof = fivefold_corrected_predictions(Z, R, iter34_t1, y_t1, seed)
    return float(ccc(y_t1, oof))


def bootstrap_frac_pos(
    y: np.ndarray, base: np.ndarray, corrected: np.ndarray, seed: int
) -> tuple[float, float, float, float]:
    rng = np.random.default_rng(seed)
    n = len(y)
    deltas = np.empty(N_BOOTSTRAP)
    for b in range(N_BOOTSTRAP):
        idx = rng.choice(n, size=n, replace=True)
        deltas[b] = float(ccc(y[idx], corrected[idx]) - ccc(y[idx], base[idx]))
    return (
        float((deltas > 0).mean()),
        float(np.percentile(deltas, 2.5)),
        float(np.percentile(deltas, 97.5)),
        float(np.median(deltas)),
    )


def _basic_metrics(y: np.ndarray, pred: np.ndarray) -> dict:
    return {
        "ccc": round(float(ccc(y, pred)), 4),
        "mae": round(float(np.mean(np.abs(y - pred))), 4),
        "pred_mean": round(float(np.mean(pred)), 4),
        "pred_std": round(float(np.std(pred)), 4),
        "true_mean": round(float(np.mean(y)), 4),
        "true_std": round(float(np.std(y)), 4),
    }


def _apply_null_arrays(
    y_t1: np.ndarray,
    iter34_t1: np.ndarray,
    R: np.ndarray,
    Z: np.ndarray,
    null_mode: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if null_mode in ("", "real"):
        return y_t1, iter34_t1, R, Z
    if null_mode == "scrambled_y":
        rng = np.random.default_rng(20260515)
        perm = rng.permutation(len(y_t1))
        return y_t1[perm], iter34_t1[perm], R[perm], Z
    if null_mode == "sid_shuffle":
        rng = np.random.default_rng(31415927)
        perm = rng.permutation(len(y_t1))
        return y_t1, iter34_t1, R, Z[perm]
    raise ValueError(f"unknown null mode: {null_mode}")


def _screen_core(
    y_t1: np.ndarray,
    iter34_t1: np.ndarray,
    R: np.ndarray,
    Z: np.ndarray,
    seeds: list[int],
) -> dict:
    base_metrics = _basic_metrics(y_t1, iter34_t1)
    preds_by_seed: list[np.ndarray] = []
    seed_rows: list[dict] = []
    for seed in seeds:
        pred = fivefold_corrected_predictions(Z, R, iter34_t1, y_t1, seed=seed)
        preds_by_seed.append(pred)
        metrics = _basic_metrics(y_t1, pred)
        seed_rows.append(
            {
                "seed": seed,
                "candidate": metrics,
                "delta_ccc": round(metrics["ccc"] - base_metrics["ccc"], 4),
                "delta_mae": round(metrics["mae"] - base_metrics["mae"], 4),
            }
        )
        print(
            f"[S1 SCREEN] seed={seed} corrected CCC={metrics['ccc']:.4f} "
            f"delta={metrics['ccc'] - base_metrics['ccc']:+.4f}"
        )
    ensemble = np.mean(np.vstack(preds_by_seed), axis=0)
    ensemble_metrics = _basic_metrics(y_t1, ensemble)
    frac_pos, ci_lo, ci_hi, boot_med = bootstrap_frac_pos(
        y_t1, iter34_t1, ensemble, SPLIT_SEED
    )
    deltas = np.array([row["delta_ccc"] for row in seed_rows], dtype=float)
    return {
        "baseline": base_metrics,
        "seed_summaries": seed_rows,
        "seed_mean_delta_ccc": round(float(np.mean(deltas)), 4),
        "seed_delta_std": round(float(np.std(deltas, ddof=1)), 4),
        "ensemble_summary": {
            "candidate": ensemble_metrics,
            "delta_ccc": round(ensemble_metrics["ccc"] - base_metrics["ccc"], 4),
            "delta_mae": round(ensemble_metrics["mae"] - base_metrics["mae"], 4),
            "bootstrap_frac_positive": round(frac_pos, 4),
            "bootstrap_median_delta": round(boot_med, 4),
            "bootstrap_ci95": [round(ci_lo, 4), round(ci_hi, 4)],
        },
        "predictions_by_seed": preds_by_seed,
        "ensemble_pred": ensemble,
    }


def screen(null_mode: str = "") -> None:
    """Run the S1 promotion screen without running LOOCV."""
    sids, y_base, iter34_base, R_base, Z_base, z_names = load_aligned()
    y_t1, iter34_t1, R, Z = _apply_null_arrays(
        y_base, iter34_base, R_base, Z_base, null_mode
    )
    print(
        f"[S1 SCREEN] N={len(sids)}, Z cols={Z.shape[1]} ({z_names}), "
        f"null_mode={null_mode or 'real'}"
    )
    core = _screen_core(y_t1, iter34_t1, R, Z, MODEL_SEEDS)
    gate = {
        "mean_seed_delta_ccc_min": 0.025,
        "seed_delta_std_max": 0.020,
        "ensemble_bootstrap_frac_positive_min": 0.95,
        "max_material_mae_degradation": 0.05,
        "gate_pass": bool(
            core["seed_mean_delta_ccc"] >= 0.025
            and core["seed_delta_std"] < 0.020
            and core["ensemble_summary"]["bootstrap_frac_positive"] >= 0.95
            and core["ensemble_summary"]["delta_mae"] <= 0.05
        ),
    }
    verdict = (
        "SCREEN_PASS_PROMOTE_TO_SINGLE_PREREG_LOOCV"
        if gate["gate_pass"]
        else "SCREEN_FAIL_NO_LOOCV"
    )

    null_results = None
    if null_mode in ("", "real"):
        null_results = {}
        for nm in ("scrambled_y", "sid_shuffle"):
            print(f"[S1 SCREEN NULL] {nm}")
            y_n, p_n, r_n, z_n = _apply_null_arrays(y_base, iter34_base, R_base, Z_base, nm)
            null_core = _screen_core(y_n, p_n, r_n, z_n, MODEL_SEEDS)
            null_results[nm] = {
                "baseline": null_core["baseline"],
                "seed_mean_delta_ccc": null_core["seed_mean_delta_ccc"],
                "seed_delta_std": null_core["seed_delta_std"],
                "ensemble_summary": null_core["ensemble_summary"],
            }
        null_results["retrieval_library_exclusion"] = {
            "status": "not_applicable",
            "rationale": "No nearest-neighbor or retrieval library is used.",
        }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"_{null_mode}" if null_mode else ""
    out = {
        "name": "screen_t1_S1_sumaware_bayesian",
        "created_at_utc": ts,
        "preregistration_master": "results/preregistration_t1t3_proresults_ablation_20260515T133800Z.json",
        "slot": "S1",
        "screen_only": True,
        "null_mode": null_mode or "real",
        "n_cohort": int(len(sids)),
        "z_names": z_names,
        "lambda_grid": LAMBDA_GRID,
        "split_seed": SPLIT_SEED,
        "feature_seed": FEATURE_SEED,
        "model_seed_list": MODEL_SEEDS,
        "baseline": core["baseline"],
        "seed_summaries": core["seed_summaries"],
        "seed_mean_delta_ccc": core["seed_mean_delta_ccc"],
        "seed_delta_std": core["seed_delta_std"],
        "ensemble_summary": core["ensemble_summary"],
        "promotion_gate": gate,
        "null_results": null_results,
        "verdict": verdict,
    }
    json_path = Path(f"results/screen_t1_S1_sumaware_bayesian_{ts}{suffix}.json")
    json_path.write_text(json.dumps(out, indent=2))
    npz_path = Path(f"results/screen_t1_S1_sumaware_bayesian_{ts}{suffix}.npz")
    np.savez(
        npz_path,
        sids=sids,
        y_t1=y_t1,
        iter34_t1_pred=iter34_t1,
        t1_corrected_5fold_ensemble=core["ensemble_pred"],
        **{
            f"t1_corrected_5fold_seed_{seed}": pred
            for seed, pred in zip(MODEL_SEEDS, core["predictions_by_seed"])
        },
    )
    print(
        f"[S1 SCREEN] verdict={verdict}, "
        f"ensemble_delta={core['ensemble_summary']['delta_ccc']:+.4f}, "
        f"frac>0={core['ensemble_summary']['bootstrap_frac_positive']:.4f}"
    )
    print(f"[S1 SCREEN] Wrote {json_path}")
    print(f"[S1 SCREEN] Wrote {npz_path}")


def main(null_mode: str = "") -> None:
    sids, y_t1, iter34_t1, R, Z, z_names = load_aligned()
    n = len(sids)
    print(f"[S1] N={n}, Z cols={Z.shape[1]} ({z_names}), null_mode={null_mode or 'real'}")

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(20260515)
        perm = rng.permutation(n)
        y_t1 = y_t1[perm]
        R = R[perm]
        iter34_t1 = iter34_t1[perm]
        print("[S1 NULL] permuted y_t1, residual matrix, and iter34 sum jointly")
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(31415927)
        perm = rng.permutation(n)
        Z = Z[perm]
        print("[S1 NULL] permuted Z rows; y_t1 and iter34 preserved")

    base_ccc = float(ccc(y_t1, iter34_t1))
    print(f"[S1] iter34 LOOCV baseline CCC={base_ccc:.4f}")

    corrected, sel_lams = loocv_corrected(Z, R, iter34_t1, y_t1, inner_seed=SPLIT_SEED)
    loocv_ccc = float(ccc(y_t1, corrected))
    delta = loocv_ccc - base_ccc
    frac_pos, ci_lo, ci_hi, boot_med = bootstrap_frac_pos(y_t1, iter34_t1, corrected, SPLIT_SEED)
    print(f"[S1] LOOCV corrected CCC={loocv_ccc:.4f}, Δ={delta:+.4f}, frac>0={frac_pos:.4f}")

    fivefold_per_seed = [
        fivefold_corrected(Z, R, iter34_t1, y_t1, seed=s) for s in MODEL_SEEDS
    ]
    base_per_seed_5f: list[float] = []
    for s in MODEL_SEEDS:
        kf = KFold(n_splits=OUTER_K, shuffle=True, random_state=s)
        oof = np.zeros(n)
        for tr_idx, va_idx in kf.split(np.arange(n)):
            oof[va_idx] = iter34_t1[va_idx]
        base_per_seed_5f.append(float(ccc(y_t1, oof)))
    deltas_5f = [a - b for a, b in zip(fivefold_per_seed, base_per_seed_5f)]
    five_mean = float(np.mean(deltas_5f))
    five_std = float(np.std(deltas_5f, ddof=0))
    print(f"[S1] 5-fold per-seed corrected CCC={fivefold_per_seed} (base {base_per_seed_5f})")
    print(f"[S1] 5-fold Δ per seed={deltas_5f}, mean={five_mean:+.4f}, std={five_std:.4f}")

    kill_reasons: list[str] = []
    if five_mean < 0.0:
        kill_reasons.append("5fold_mean_delta_below_zero")
    if five_std > 0.020:
        kill_reasons.append("5fold_seed_std_exceeds_0.020")
    if null_mode:
        kill_reasons.append(f"null_mode={null_mode}")
    verdict = "KILL" if kill_reasons else ("PASS_SCREEN" if delta > 0 else "FAIL_DELTA")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "name": "lockbox_t1_S1_sumaware_bayesian",
        "created_at_utc": ts,
        "preregistration_master": "preregistration_t1t3_proresults_ablation_20260515T133800Z",
        "null_mode": null_mode or "real",
        "n_cohort": n,
        "z_names": z_names,
        "lambda_grid": LAMBDA_GRID,
        "split_seed": SPLIT_SEED,
        "feature_seed": FEATURE_SEED,
        "model_seed_list": MODEL_SEEDS,
        "loocv_ccc_baseline_iter34": round(base_ccc, 4),
        "loocv_ccc_corrected": round(loocv_ccc, 4),
        "delta_ccc": round(delta, 4),
        "frac_pos_bootstrap": round(frac_pos, 4),
        "bootstrap_median_delta": round(boot_med, 4),
        "ci95": [round(ci_lo, 4), round(ci_hi, 4)],
        "5fold_per_seed_corrected_ccc": [round(v, 4) for v in fivefold_per_seed],
        "5fold_per_seed_baseline_ccc": [round(v, 4) for v in base_per_seed_5f],
        "5fold_per_seed_delta": [round(v, 4) for v in deltas_5f],
        "5fold_mean_delta_3seeds": round(five_mean, 4),
        "5fold_seed_std": round(five_std, 4),
        "selected_lambda_sum_per_fold": sel_lams,
        "kill_threshold_evaluation": {
            "rule": "5fold_mean<0 OR seed_std>0.020 OR null gate hit",
            "reasons_triggered": kill_reasons,
        },
        "verdict": verdict,
    }
    suffix = f"_{null_mode}" if null_mode else ""
    json_path = Path(f"results/lockbox_t1_S1_sumaware_bayesian_{ts}{suffix}.json")
    json_path.write_text(json.dumps(out, indent=2))

    npz_path = Path(f"results/oof_t1_S1_sumaware_bayesian_{ts}{suffix}.npz")
    np.savez(
        npz_path,
        sids=sids,
        y_t1=y_t1,
        iter34_t1_pred=iter34_t1,
        t1_corrected=corrected,
        selected_lambda_per_fold=np.array(sel_lams, dtype=float),
    )
    print(f"[S1] Wrote {json_path}")
    print(f"[S1] Wrote {npz_path}")
    print(f"[S1] VERDICT={verdict}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--mode=screen":
        null_mode = ""
        for arg in sys.argv[2:]:
            if arg.startswith("--null="):
                null_mode = arg.split("=", 1)[1]
        if null_mode and null_mode not in {"scrambled_y", "sid_shuffle"}:
            raise SystemExit(f"unknown --null mode: {null_mode}")
        screen(null_mode=null_mode)
        sys.exit(0)
    null_mode = ""
    if len(sys.argv) > 1 and sys.argv[1].startswith("--null="):
        null_mode = sys.argv[1].split("=", 1)[1]
        if null_mode not in {"scrambled_y", "sid_shuffle"}:
            raise SystemExit(f"unknown --null mode: {null_mode}")
    main(null_mode=null_mode)
