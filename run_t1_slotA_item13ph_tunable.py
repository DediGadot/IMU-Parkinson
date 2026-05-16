"""T1 Slot A (revised, 2026-05-15 PM session): item-13-PH tunable-scalar.

Mechanism (D2-confirmed biomechanical):
  - PH features applied to item 13 lift Δr=+0.161 (right pairing)
  - PH features applied to item 10 lift Δr=-0.086 (wrong pairing, negative)
  - => PH is item-13-specific biomechanical signal, not generic compression
  - corr(item-13 correction, T1_sum residual) = +0.273 (D2 result)

Architecture (orthogonal to walls #84-90):
  - Use ONLY item 13 (W#84: items 9/10/14 are mirages)
  - Use v1 cache 32 PH cols (W#89: v2 3120 cols overfits)
  - Fold-local Ridge α (W#88: tighter shrinkage may beat the linear-blend +0.021 ceiling)
  - Inner-CV-tuned scalar λ on the correction added to iter34's t1_sum_pred
    (W#87: tunable λ accommodates the chain-vs-sum scale mismatch)

Distinct from yesterday's slot D.1:
  - D.1 used λ=1.0 fixed (just added the correction to t1_sum_pred)
  - This slot tunes λ per outer-LOOCV via inner-5-fold maximizing CCC(y_t1, t1_corrected)

Distinct from yesterday's slot E (linear blend):
  - E blended {iter34_t1_sum_pred, sum_of_per_item_corrected} which suffers W#87
    scale mismatch (P2 starts at CCC=0.6187, P1 at 0.7170)
  - This slot adds correction in the t1_sum_pred SCALE directly, no scale-mixing

Pre-registration: results/preregistration_t1_slotA_item13ph_tunable_20260515_PM.json

Promotion gate (Bonferroni-corrected for LIFETIME FWER on this cohort):
  Yesterday: 4 slots tested. Today new family: n=2 (this slot + Slot C T3).
  Effective lifetime FWER family = 6 (yesterday + today on same cohort).
  Bonferroni alpha = 0.05/6 = 0.00833
  Gate: paired-bootstrap frac>0 >= 0.99167 AND ΔCCC >= +0.025
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

CACHE_PATH = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"
OOF_PATH = "results/t1_iter34_per_item_oof_20260511_044242.npz"

ALPHA_GRID = [10.0, 30.0, 100.0, 300.0, 1000.0]
LAMBDA_GRID = [0.25, 0.5, 0.75, 1.0, 1.25]
INNER_FOLDS = 5
INNER_SEED = 31415
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20260515


def get_ph_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if "_ph_" in c]


def fold_local_ridge(
    X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray, alpha: float
) -> np.ndarray:
    imp = FoldImputer.fit(X_tr)
    Xt = imp.transform(X_tr)
    Xv = imp.transform(X_te)
    nrm = FoldNormalizer.fit(Xt)
    Xt = nrm.transform(Xt)
    Xv = nrm.transform(Xv)
    m = Ridge(alpha=alpha).fit(Xt, y_tr)
    return m.predict(Xv)


def inner_cv_select_alpha_and_lambda(
    X_tr: np.ndarray,
    y_t1_tr: np.ndarray,
    yhat_t1sum_tr: np.ndarray,
    item13_resid_tr: np.ndarray,
    item13_pred_tr: np.ndarray,
    item13_true_tr: np.ndarray,
    seed: int,
) -> tuple[float, float, dict]:
    """Inner 5-fold CV over (alpha, lambda) grid maximizing CCC(y_t1, t1_corrected)."""
    n = len(y_t1_tr)
    kf = KFold(n_splits=INNER_FOLDS, shuffle=True, random_state=seed)
    scores = {}  # (alpha, lam) -> list of inner-fold CCC
    for ai, alpha in enumerate(ALPHA_GRID):
        # OOF correction for THIS alpha across inner folds
        correction_oof = np.full(n, np.nan)
        for tr_idx, va_idx in kf.split(np.arange(n)):
            X_inner_tr = X_tr[tr_idx]
            y_inner_tr = item13_resid_tr[tr_idx]
            X_inner_va = X_tr[va_idx]
            correction_oof[va_idx] = fold_local_ridge(X_inner_tr, y_inner_tr, X_inner_va, alpha)
        # Now sweep lambda for this alpha using the OOF correction
        for lam in LAMBDA_GRID:
            t1_corrected_oof = yhat_t1sum_tr + lam * correction_oof
            c = float(ccc(y_t1_tr, t1_corrected_oof))
            scores[(alpha, lam)] = c
    # Pick best
    best_key = max(scores, key=lambda k: scores[k])
    best_alpha, best_lam = best_key
    return best_alpha, best_lam, scores


def main(sanity_y_nan: bool = False, null_mode: str = ""):
    df = pd.read_csv(CACHE_PATH)
    oof = dict(np.load(OOF_PATH, allow_pickle=True))
    sids_oof = oof["sids"].astype(str)
    keep = df["sid"].isin(sids_oof).values
    df = df[keep].reset_index(drop=True)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids_oof])
    df = df.iloc[order].reset_index(drop=True)
    assert (df["sid"].astype(str).values == sids_oof).all()

    y_t1 = oof["y_t1"].astype(float)
    yhat_t1sum = oof["t1_sum_pred"].astype(float)
    item13_true = oof["item_13_true"].astype(float)
    item13_pred = oof["item_13_pred"].astype(float)
    item13_resid = item13_true - item13_pred
    n = len(sids_oof)

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011)
        item13_resid = rng.permutation(item13_resid)
        print(f"[Slot A NULL] scrambled item-13 residual")
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(91011)
        perm = rng.permutation(n)
        ph_cols = get_ph_columns(df)
        for c in ph_cols:
            df[c] = df[c].values[perm]
        print(f"[Slot A NULL] SID-shuffled PH feature rows")

    ph_cols = get_ph_columns(df)
    X = df[ph_cols].values.astype(float)
    print(f"[Slot A] N={n}, PH cols={len(ph_cols)}, null_mode={null_mode or 'none'}")

    # Outer LOOCV
    t1_corrected_loocv = np.full(n, np.nan)
    chosen_alpha = np.zeros(n)
    chosen_lambda = np.zeros(n)
    item13_correction_oof = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        X_tr, X_te = X[tr], X[i:i+1]
        y_t1_tr = y_t1[tr]
        yhat_t1sum_tr = yhat_t1sum[tr]
        item13_resid_tr = item13_resid[tr]
        item13_pred_tr = item13_pred[tr]
        item13_true_tr = item13_true[tr]

        # Inner CV to pick (alpha, lambda)
        a_star, l_star, _ = inner_cv_select_alpha_and_lambda(
            X_tr, y_t1_tr, yhat_t1sum_tr,
            item13_resid_tr, item13_pred_tr, item13_true_tr,
            seed=INNER_SEED + (i * 7),
        )
        chosen_alpha[i] = a_star
        chosen_lambda[i] = l_star

        # Fit the final Ridge on full train fold for this alpha; predict on test fold
        correction_te = fold_local_ridge(X_tr, item13_resid_tr, X_te, a_star)
        item13_correction_oof[i] = correction_te[0]
        t1_corrected_loocv[i] = yhat_t1sum[i] + l_star * correction_te[0]

        if (i + 1) % 20 == 0:
            print(f"  fold {i+1}/{n}: α*={a_star:.0f}, λ*={l_star:.2f}, "
                  f"correction={correction_te[0]:+.3f}, t1_corr={t1_corrected_loocv[i]:.3f}")

    # Metrics
    baseline_ccc = float(ccc(y_t1, yhat_t1sum))
    corrected_ccc = float(ccc(y_t1, t1_corrected_loocv))
    baseline_r = float(np.corrcoef(y_t1, yhat_t1sum)[0, 1])
    corrected_r = float(np.corrcoef(y_t1, t1_corrected_loocv)[0, 1])
    baseline_mae = float(np.mean(np.abs(y_t1 - yhat_t1sum)))
    corrected_mae = float(np.mean(np.abs(y_t1 - t1_corrected_loocv)))

    delta_ccc = corrected_ccc - baseline_ccc
    delta_r = corrected_r - baseline_r
    delta_mae = corrected_mae - baseline_mae

    print(f"\n[Slot A] Baseline iter34 T1 CCC={baseline_ccc:.4f}  MAE={baseline_mae:.4f}  r={baseline_r:.4f}")
    print(f"[Slot A] Corrected (item-13 PH tunable λ) CCC={corrected_ccc:.4f}  MAE={corrected_mae:.4f}  r={corrected_r:.4f}")
    print(f"[Slot A] Δ:  ΔCCC={delta_ccc:+.4f}  ΔMAE={delta_mae:+.4f}  Δr={delta_r:+.4f}")

    # Paired-bootstrap on Δ
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    deltas_boot = np.empty(N_BOOTSTRAP)
    for b in range(N_BOOTSTRAP):
        idx = rng.choice(n, size=n, replace=True)
        d = float(ccc(y_t1[idx], t1_corrected_loocv[idx]) - ccc(y_t1[idx], yhat_t1sum[idx]))
        deltas_boot[b] = d
    boot_ci = (float(np.percentile(deltas_boot, 2.5)),
               float(np.percentile(deltas_boot, 97.5)))
    frac_pos = float((deltas_boot > 0).mean())

    print(f"[Slot A] Bootstrap: median={np.median(deltas_boot):+.4f}, "
          f"CI=[{boot_ci[0]:+.4f}, {boot_ci[1]:+.4f}], frac>0={frac_pos:.4f}")

    # D4 audit
    corr_correction_sum_resid = float(np.corrcoef(item13_correction_oof, y_t1 - yhat_t1sum)[0, 1])
    print(f"[Slot A] D4: corr(item13_correction, T1_sum_residual) = {corr_correction_sum_resid:+.4f}")

    # Promotion gates
    YESTERDAY_FWER_N = 4
    TODAY_FWER_N = 2
    LIFETIME_FWER = YESTERDAY_FWER_N + TODAY_FWER_N
    bonf_alpha = 0.05 / LIFETIME_FWER
    bonf_frac_pos_gate = 1.0 - bonf_alpha

    gate_today_n2 = 0.975  # n=2 family today only
    gate_lifetime = bonf_frac_pos_gate  # n=6 lifetime

    if frac_pos >= gate_lifetime and delta_ccc >= 0.025:
        verdict = "PASS_LIFETIME_BONFERRONI"
    elif frac_pos >= gate_today_n2 and delta_ccc >= 0.025:
        verdict = "PASS_TODAY_N2_FAILS_LIFETIME"
    elif frac_pos >= 0.95 and delta_ccc >= 0.025:
        verdict = "PASS_UNCORRECTED_FAILS_FWER"
    elif frac_pos >= 0.95:
        verdict = "PASS_UNCORRECTED_DELTA_BELOW_MCID"
    else:
        verdict = "FAIL"

    out = {
        "name": "lockbox_t1_slotA_item13ph_tunable",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "session": "2026-05-15-PM",
        "preregistration_master": "results/preregistration_t1_ceiling_push_20260515_master.json",
        "null_mode": null_mode or "real",
        "n": n,
        "n_features_ph": len(ph_cols),
        "alpha_grid": ALPHA_GRID,
        "lambda_grid": LAMBDA_GRID,
        "inner_folds": INNER_FOLDS,
        "baseline_iter34": {
            "ccc": round(baseline_ccc, 4),
            "mae": round(baseline_mae, 4),
            "r": round(baseline_r, 4),
        },
        "corrected_metrics": {
            "ccc": round(corrected_ccc, 4),
            "mae": round(corrected_mae, 4),
            "r": round(corrected_r, 4),
        },
        "delta": {
            "ccc": round(delta_ccc, 4),
            "mae": round(delta_mae, 4),
            "r": round(delta_r, 4),
        },
        "bootstrap": {
            "n_boot": N_BOOTSTRAP,
            "median_delta": round(float(np.median(deltas_boot)), 4),
            "ci95_lower": round(boot_ci[0], 4),
            "ci95_upper": round(boot_ci[1], 4),
            "frac_positive": round(frac_pos, 4),
        },
        "fold_choices": {
            "alpha_mode": int(pd.Series(chosen_alpha).mode().iloc[0]),
            "alpha_distribution": pd.Series(chosen_alpha).value_counts().to_dict(),
            "lambda_mode": float(pd.Series(chosen_lambda).mode().iloc[0]),
            "lambda_distribution": {str(k): int(v) for k, v in pd.Series(chosen_lambda).value_counts().to_dict().items()},
        },
        "d4_audit": {
            "corr_correction_T1sum_residual": round(corr_correction_sum_resid, 4),
        },
        "gates": {
            "today_n2_bonferroni_gate": gate_today_n2,
            "lifetime_n6_bonferroni_gate": round(gate_lifetime, 5),
            "mcid_delta_ccc": 0.025,
        },
        "verdict": verdict,
    }
    ts = out["created_at_utc"]
    suffix = f"_{null_mode}" if null_mode else ""
    path = Path(f"results/lockbox_t1_slotA_item13ph_tunable_{ts}{suffix}.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"\n[Slot A] Verdict: {verdict}")
    print(f"[Slot A] Wrote {path}")


if __name__ == "__main__":
    null_mode = ""
    if len(sys.argv) > 1 and sys.argv[1].startswith("--null="):
        null_mode = sys.argv[1].split("=", 1)[1]
    main(null_mode=null_mode)
