"""T1 Slot S5: Microbatch item-13-only PRIMARY + items 10/14 D4 AUDIT arms.

Three parallel LOOCV arms on the iter34 0.7170 (N=92) cohort, FULL-cohort (not
retained-subset) estimand:

  - PRIMARY  item13_PH_alpha100_PRIMARY  (Hypothesis A)
        Item-13 PH Ridge alpha=100, lambda=1.0 fixed correction.
        Pre-reg expected lift on T1 LOOCV CCC = +0.005..+0.015 over 0.7170.

  - AUDIT    item10_MFDFA_alpha1000_AUDIT (Hypothesis B)
        Item-10 MFDFA Ridge alpha=1000, lambda=1.0. Pre-reg expectation:
        CONFIRMS the 2026-05-15-AM D4 mirage diagnosis (Δr near zero,
        worse MAE, negative corr(correction, sum_residual)).

  - AUDIT    item14_PH_alpha1000_AUDIT   (Hypothesis B)
        Item-14 PH Ridge alpha=1000, lambda=1.0. Same expectation as item-10.

Any AUDIT arm that LIFTS positively (delta_pearson_r > 0.06 AND
corr_correction_sum_residual > 0 AND delta_mae < -0.005) is flagged
CONTRADICTS_D4 and triggers re-audit. Otherwise CONFIRMED_MIRAGE.

Pre-reg master: preregistration_t1t3_proresults_ablation_20260515T133800Z.json
Firewall: inductive_lib FoldImputer/FoldNormalizer fold-local; Ridge fit on
outer-train rows only; all hyperparameters FROZEN.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.linear_model import Ridge

from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

ITER34_OOF_NPZ = "results/t1_iter34_per_item_oof_20260511_044242.npz"
STEPFN_CACHE = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"

SPLIT_SEED = 20260309
MODEL_SEEDS: tuple[int, ...] = (42, 1337, 7)
LAMBDA_FIXED = 1.0
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20260515
PREREG_MASTER = (
    "results/preregistration_t1t3_proresults_ablation_20260515T133800Z.json"
)


@dataclass(frozen=True)
class ArmSpec:
    name: str
    item: int
    feature_filter: str
    alpha: float
    role: str  # "PRIMARY" | "AUDIT"


ARMS: tuple[ArmSpec, ...] = (
    ArmSpec("item13_PH_alpha100_PRIMARY", 13, "_ph_", 100.0, "PRIMARY"),
    ArmSpec("item10_MFDFA_alpha1000_AUDIT", 10, "mfdfa_", 1000.0, "AUDIT"),
    ArmSpec("item14_PH_alpha1000_AUDIT", 14, "_ph_", 1000.0, "AUDIT"),
)


def load_aligned_data() -> tuple[
    np.ndarray, np.ndarray, np.ndarray, dict[int, tuple[np.ndarray, np.ndarray]],
    pd.DataFrame,
]:
    """Load iter34 OOF + step-function cache, aligned by sid order."""
    iter34 = dict(np.load(ITER34_OOF_NPZ, allow_pickle=True))
    sids = iter34["sids"].astype(str)
    y_t1 = iter34["y_t1"].astype(float)
    yhat_iter34 = iter34["t1_sum_pred"].astype(float)
    items: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for j in range(9, 15):
        items[j] = (
            iter34[f"item_{j}_true"].astype(float),
            iter34[f"item_{j}_pred"].astype(float),
        )

    df = pd.read_csv(STEPFN_CACHE)
    df = df[df["sid"].isin(sids)].reset_index(drop=True)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids])
    df = df.iloc[order].reset_index(drop=True)
    assert (df["sid"].astype(str).values == sids).all(), "sid alignment failed"
    return sids, y_t1, yhat_iter34, items, df


def select_features(df: pd.DataFrame, substr: str) -> tuple[np.ndarray, list[str]]:
    cols = [c for c in df.columns if c != "sid" and substr in c]
    if not cols:
        raise ValueError(f"No columns containing substring {substr!r}")
    X = df[cols].values.astype(float)
    return X, cols


def loocv_ridge_correction(
    X: np.ndarray, item_resid: np.ndarray, alpha: float, model_seeds: Sequence[int]
) -> np.ndarray:
    """LOOCV fold-local PH/MFDFA Ridge correction, averaged across model seeds."""
    n = len(item_resid)
    correction = np.zeros(n, dtype=float)
    for i in range(n):
        tr = np.arange(n) != i
        X_tr_raw, X_te_raw = X[tr], X[i : i + 1]
        y_tr = item_resid[tr]
        imp = FoldImputer.fit(X_tr_raw)
        X_tr = imp.transform(X_tr_raw)
        X_te = imp.transform(X_te_raw)
        nrm = FoldNormalizer.fit(X_tr)
        X_tr = nrm.transform(X_tr)
        X_te = nrm.transform(X_te)
        preds = []
        for seed in model_seeds:
            m = Ridge(alpha=alpha, random_state=seed).fit(X_tr, y_tr)
            preds.append(float(m.predict(X_te)[0]))
        correction[i] = float(np.mean(preds))
    return correction


def paired_bootstrap_frac_pos(
    y: np.ndarray, yhat_a: np.ndarray, yhat_b: np.ndarray,
    n_boot: int, seed: int,
) -> tuple[float, tuple[float, float], float]:
    """Bootstrap delta_ccc = ccc(y, yhat_b) - ccc(y, yhat_a)."""
    rng = np.random.default_rng(seed)
    n = len(y)
    deltas = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        deltas[b] = float(ccc(y[idx], yhat_b[idx]) - ccc(y[idx], yhat_a[idx]))
    frac_pos = float((deltas > 0).mean())
    ci = (float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)))
    median = float(np.median(deltas))
    return frac_pos, ci, median


def d4_replication_status(delta_r: float, delta_mae: float, corr_sum: float) -> str:
    """Classify per the 2026-05-15-AM D4 audit mirage signature."""
    contradicts = (delta_r > 0.06) and (corr_sum > 0.0) and (delta_mae < -0.005)
    if contradicts:
        return "CONTRADICTS_D4"
    confirms = (abs(delta_r) < 0.06) and (corr_sum <= 0.0) and (delta_mae >= -0.005)
    return "CONFIRMED_MIRAGE" if confirms else "AMBIGUOUS"


def evaluate_arm(
    arm: ArmSpec, df: pd.DataFrame, y_t1: np.ndarray, yhat_iter34: np.ndarray,
    items: dict[int, tuple[np.ndarray, np.ndarray]],
) -> dict:
    item_true, item_pred = items[arm.item]
    item_resid = item_true - item_pred
    X, cols = select_features(df, arm.feature_filter)
    correction = loocv_ridge_correction(X, item_resid, arm.alpha, MODEL_SEEDS)
    t1_corrected = yhat_iter34 + LAMBDA_FIXED * correction

    sum_resid = y_t1 - yhat_iter34

    ccc_base = float(ccc(y_t1, yhat_iter34))
    ccc_corr = float(ccc(y_t1, t1_corrected))
    r_base = float(pearsonr(y_t1, yhat_iter34)[0])
    r_corr = float(pearsonr(y_t1, t1_corrected)[0])
    mae_base = float(np.mean(np.abs(y_t1 - yhat_iter34)))
    mae_corr = float(np.mean(np.abs(y_t1 - t1_corrected)))
    corr_item = float(pearsonr(correction, item_resid)[0])
    corr_sum = float(pearsonr(correction, sum_resid)[0])

    delta_ccc = ccc_corr - ccc_base
    delta_r = r_corr - r_base
    delta_mae = mae_corr - mae_base

    frac_pos, ci, median = paired_bootstrap_frac_pos(
        y_t1, yhat_iter34, t1_corrected, N_BOOTSTRAP, BOOTSTRAP_SEED
    )

    record = {
        "arm": arm.name,
        "role": arm.role,
        "item": arm.item,
        "feature_filter": arm.feature_filter,
        "n_features": len(cols),
        "alpha_fixed": arm.alpha,
        "lambda_fixed": LAMBDA_FIXED,
        "model_seeds": list(MODEL_SEEDS),
        "loocv_ccc_baseline": round(ccc_base, 6),
        "loocv_ccc_corrected": round(ccc_corr, 6),
        "delta_ccc": round(delta_ccc, 6),
        "delta_pearson_r": round(delta_r, 6),
        "delta_mae": round(delta_mae, 6),
        "corr_correction_item_residual": round(corr_item, 6),
        "corr_correction_sum_residual": round(corr_sum, 6),
        "frac_pos_bootstrap": round(frac_pos, 4),
        "bootstrap_median": round(median, 6),
        "ci95": [round(ci[0], 6), round(ci[1], 6)],
    }

    if arm.role == "PRIMARY":
        # Hypothesis A: lift +0.005..+0.015. Kill if delta_ccc <= 0.0 (5-fold proxy via LOOCV here).
        record["verdict"] = (
            "PASS_HYPOTHESIS_A" if delta_ccc >= 0.005 else
            ("BELOW_PREREG_BAND" if delta_ccc > 0.0 else "FAIL_KILL")
        )
    else:
        record["d4_replication_status"] = d4_replication_status(
            delta_r, delta_mae, corr_sum
        )
    return record


def apply_null(
    null_mode: str, y_t1: np.ndarray, yhat_iter34: np.ndarray,
    items: dict[int, tuple[np.ndarray, np.ndarray]], df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, dict[int, tuple[np.ndarray, np.ndarray]], pd.DataFrame]:
    n = len(y_t1)
    if null_mode == "scrambled_y":
        rng = np.random.default_rng(20260515)
        perm = rng.permutation(n)
        y_t1 = y_t1[perm]
        yhat_iter34 = yhat_iter34[perm]
        items = {j: (t[perm], p[perm]) for j, (t, p) in items.items()}
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(20260515 + 1)
        perm = rng.permutation(n)
        feat_cols = [c for c in df.columns if c != "sid"]
        df = df.copy()
        df[feat_cols] = df[feat_cols].values[perm]
    return y_t1, yhat_iter34, items, df


def main(null_mode: str = "") -> None:
    sids, y_t1, yhat_iter34, items, df = load_aligned_data()
    if null_mode:
        y_t1, yhat_iter34, items, df = apply_null(null_mode, y_t1, yhat_iter34, items, df)

    n = len(sids)
    print(f"[S5] N={n}, null_mode={null_mode or 'real'}")
    print(f"[S5] Baseline LOOCV iter34 CCC={float(ccc(y_t1, yhat_iter34)):.6f}")

    arm_results: dict[str, dict] = {}
    for arm in ARMS:
        # In null modes other than 'real', AUDIT arms are skipped per spec (only N1 on PRIMARY).
        if null_mode and arm.role != "PRIMARY":
            continue
        print(f"[S5] running arm={arm.name} alpha={arm.alpha} n_features=(filtering '{arm.feature_filter}')")
        arm_results[arm.name] = evaluate_arm(arm, df, y_t1, yhat_iter34, items)
        r = arm_results[arm.name]
        suffix = r.get("verdict") or r.get("d4_replication_status") or "n/a"
        print(
            f"[S5] {arm.name}: Δccc={r['delta_ccc']:+.4f}, Δr={r['delta_pearson_r']:+.4f}, "
            f"ΔMAE={r['delta_mae']:+.4f}, corr(c,sum_resid)={r['corr_correction_sum_residual']:+.4f}, "
            f"frac>0={r['frac_pos_bootstrap']:.4f} -> {suffix}"
        )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "name": "lockbox_t1_S5_microbatch_item13only_audit",
        "created_at_utc": ts,
        "preregistration_master": PREREG_MASTER,
        "session": "2026-05-15-PM-microbatch-S5",
        "null_mode": null_mode or "real",
        "n_cohort": n,
        "split_seed": SPLIT_SEED,
        "model_seeds": list(MODEL_SEEDS),
        "lambda_fixed": LAMBDA_FIXED,
        "n_bootstrap": N_BOOTSTRAP,
        "estimand_label": "full_cohort_t1_loocv_ccc_post_correction",
        "iter34_baseline_canonical_ccc": 0.7170,
        "iter34_loocv_ccc_recomputed": round(float(ccc(y_t1, yhat_iter34)), 6),
        "arms": arm_results,
        "d4_audit_reference": "results/d4_variance_compression_audit_20260515T082806Z.json",
    }
    suffix = f"_{null_mode}" if null_mode else ""
    path = Path(f"results/lockbox_t1_S5_microbatch_item13only_audit_{ts}{suffix}.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"\n[S5] Wrote {path}")


if __name__ == "__main__":
    mode = ""
    if len(sys.argv) > 1 and sys.argv[1].startswith("--null="):
        mode = sys.argv[1].split("=", 1)[1]
    main(null_mode=mode)
