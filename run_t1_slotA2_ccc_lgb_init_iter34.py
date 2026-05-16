"""T1 Slot A2: CCC-objective LightGBM with init_score=iter34.t1_sum_pred on item-13 PH.

Mechanism orthogonal to:
  - Slot A (Ridge tunable-scalar) — different model class
  - Slot D.1 yesterday (Ridge λ=1 fixed) — different model class + custom CCC loss
  - All prior CCC-LGB attempts (E1 in old paper failed Δ=-0.023 because they used
    LGB on RESIDUALS without init_score=baseline_pred; this slot puts iter34 as
    init_score so LGB only learns the delta on top of iter34's pred scale)

Design (orthogonal to walls #84-94):
  - Item-13 PH features (32 cols, v1 cache per W#89)
  - Custom CCC objective v2 (project's proven primitive in `lgb_ccc_objective_v2.py`)
  - init_score = iter34.t1_sum_pred (NOT mean as default) — LGB output IS the corrected T1_sum
  - Target = y_t1 directly (NOT item-13 residual) — LGB optimizes the actual reported metric on the right scale
  - Light LGB (num_leaves=7, min_data_in_leaf=5, n_estimators=200, lr=0.05) to avoid overfitting at N=92
  - Outer LOOCV, 3 seeds averaged
  - Post-hoc affine calibration on inner-OOF (standard CCC v2)

Lifetime FWER family = 8 (yesterday n=4 + Slot A + Slot A2 + Slot C).
Bonferroni gate frac>0 ≥ 0.99375.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc
from lgb_ccc_objective_v2 import ccc_loss_grad_hess_v2, fit_ccc_affine

CACHE_PATH = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"
OOF_PATH = "results/t1_iter34_per_item_oof_20260511_044242.npz"

SEEDS = [42, 1337, 7]
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20260515

LGB_PARAMS = {
    "learning_rate": 0.05,
    "num_leaves": 7,
    "min_data_in_leaf": 5,
    "feature_fraction": 1.0,
    "bagging_fraction": 1.0,
    "n_jobs": 1,
    "verbosity": -1,
    "reg_lambda": 0.0,
}
N_ESTIMATORS = 200


def get_ph_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if "_ph_" in c]


def train_lgb_ccc_with_iter34_init(
    X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray,
    iter34_tr: np.ndarray, iter34_te: np.ndarray,
    seed: int, params: dict, n_estimators: int = N_ESTIMATORS,
    calibrate: bool = True,
) -> np.ndarray:
    """LGB with CCC objective + init_score = iter34.t1_sum_pred."""
    p = dict(params)
    p["objective"] = ccc_loss_grad_hess_v2
    p["metric"] = "None"
    p["random_state"] = seed
    booster = lgb.train(
        params=p,
        train_set=lgb.Dataset(X_tr, label=y_tr, init_score=iter34_tr),
        num_boost_round=n_estimators,
    )
    pred_tr = booster.predict(X_tr) + iter34_tr
    pred_te = booster.predict(X_te) + iter34_te
    if calibrate:
        a, b = fit_ccc_affine(y_tr, pred_tr)
        pred_te = a * pred_te + b
    return pred_te


def main(null_mode: str = ""):
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
    n = len(sids_oof)

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011)
        y_t1 = rng.permutation(y_t1)
        print(f"[Slot A2 NULL] scrambled y_t1")

    ph_cols = get_ph_columns(df)
    X = df[ph_cols].values.astype(float)
    print(f"[Slot A2] N={n}, PH cols={len(ph_cols)}, null_mode={null_mode or 'none'}, seeds={SEEDS}")

    # Outer LOOCV × seeds
    preds_per_seed = []
    for seed in SEEDS:
        preds = np.full(n, np.nan)
        for i in range(n):
            tr = np.arange(n) != i
            X_tr_raw, X_te_raw = X[tr], X[i:i+1]
            y_tr = y_t1[tr]
            iter34_tr = yhat_t1sum[tr].astype(float)
            iter34_te = yhat_t1sum[i:i+1].astype(float)

            imp = FoldImputer.fit(X_tr_raw)
            Xt = imp.transform(X_tr_raw)
            Xv = imp.transform(X_te_raw)
            nrm = FoldNormalizer.fit(Xt)
            Xt = nrm.transform(Xt)
            Xv = nrm.transform(Xv)

            preds[i] = train_lgb_ccc_with_iter34_init(
                Xt, y_tr, Xv, iter34_tr, iter34_te, seed=seed,
                params=LGB_PARAMS, n_estimators=N_ESTIMATORS, calibrate=True,
            )[0]

            if (i + 1) % 20 == 0:
                print(f"  seed {seed} fold {i+1}/{n}: pred={preds[i]:.3f}")
        seed_ccc = float(ccc(y_t1, preds))
        print(f"  seed {seed}: LOOCV CCC = {seed_ccc:.4f}")
        preds_per_seed.append(preds)

    pred_mean = np.mean(preds_per_seed, axis=0)
    seed_cccs = [float(ccc(y_t1, p)) for p in preds_per_seed]

    # Metrics
    baseline_ccc = float(ccc(y_t1, yhat_t1sum))
    corrected_ccc = float(ccc(y_t1, pred_mean))
    delta_ccc = corrected_ccc - baseline_ccc
    baseline_mae = float(np.mean(np.abs(y_t1 - yhat_t1sum)))
    corrected_mae = float(np.mean(np.abs(y_t1 - pred_mean)))
    delta_mae = corrected_mae - baseline_mae
    baseline_r = float(np.corrcoef(y_t1, yhat_t1sum)[0, 1])
    corrected_r = float(np.corrcoef(y_t1, pred_mean)[0, 1])
    delta_r = corrected_r - baseline_r

    seed_std = float(np.std(seed_cccs))
    print(f"\n[Slot A2] Per-seed CCC: {[round(c,4) for c in seed_cccs]}, std={seed_std:.4f}")
    print(f"[Slot A2] Baseline iter34 CCC={baseline_ccc:.4f}, MAE={baseline_mae:.4f}, r={baseline_r:.4f}")
    print(f"[Slot A2] CCC-LGB (mean of seeds) CCC={corrected_ccc:.4f}, MAE={corrected_mae:.4f}, r={corrected_r:.4f}")
    print(f"[Slot A2] Δ: CCC={delta_ccc:+.4f}, MAE={delta_mae:+.4f}, r={delta_r:+.4f}")

    # Paired-bootstrap
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    deltas_boot = np.empty(N_BOOTSTRAP)
    for b in range(N_BOOTSTRAP):
        idx = rng.choice(n, size=n, replace=True)
        d = float(ccc(y_t1[idx], pred_mean[idx]) - ccc(y_t1[idx], yhat_t1sum[idx]))
        deltas_boot[b] = d
    boot_ci = (float(np.percentile(deltas_boot, 2.5)),
               float(np.percentile(deltas_boot, 97.5)))
    frac_pos = float((deltas_boot > 0).mean())
    print(f"[Slot A2] Bootstrap: median={np.median(deltas_boot):+.4f}, "
          f"CI=[{boot_ci[0]:+.4f}, {boot_ci[1]:+.4f}], frac>0={frac_pos:.4f}")

    # D4
    correction_oof = pred_mean - yhat_t1sum
    corr_correction_sum_resid = float(np.corrcoef(correction_oof, y_t1 - yhat_t1sum)[0, 1])
    print(f"[Slot A2] D4: corr(correction, T1_sum_residual) = {corr_correction_sum_resid:+.4f}")

    # Verdict gates
    LIFETIME_FWER = 8
    bonf_gate_lifetime = 1.0 - 0.05 / LIFETIME_FWER
    if frac_pos >= bonf_gate_lifetime and delta_ccc >= 0.025:
        verdict = "PASS_LIFETIME_BONFERRONI"
    elif frac_pos >= 0.95 and delta_ccc >= 0.025:
        verdict = "PASS_UNCORRECTED_FAILS_FWER"
    elif frac_pos >= 0.95:
        verdict = "PASS_UNCORRECTED_DELTA_BELOW_MCID"
    else:
        verdict = "FAIL"

    out = {
        "name": "lockbox_t1_slotA2_ccc_lgb_init_iter34",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "session": "2026-05-15-PM-extended",
        "preregistration_master": "results/preregistration_t1_ceiling_push_20260515_master.json",
        "null_mode": null_mode or "real",
        "n": n,
        "seeds": SEEDS,
        "n_features_ph": len(ph_cols),
        "lgb_params": LGB_PARAMS,
        "n_estimators": N_ESTIMATORS,
        "init_score": "iter34_t1_sum_pred",
        "objective": "ccc_loss_grad_hess_v2",
        "calibration": "fit_ccc_affine_on_inner_train_preds",
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
        "per_seed_ccc": [round(c, 4) for c in seed_cccs],
        "seed_std": round(seed_std, 4),
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
        "d4_audit": {
            "corr_correction_T1sum_residual": round(corr_correction_sum_resid, 4),
        },
        "gates": {
            "lifetime_n8_bonferroni_gate": round(bonf_gate_lifetime, 5),
            "mcid_delta_ccc": 0.025,
        },
        "verdict": verdict,
    }
    ts = out["created_at_utc"]
    suffix = f"_{null_mode}" if null_mode else ""
    path = Path(f"results/lockbox_t1_slotA2_ccc_lgb_init_iter34_{ts}{suffix}.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"\n[Slot A2] Verdict: {verdict}")
    print(f"[Slot A2] Wrote {path}")


if __name__ == "__main__":
    null_mode = ""
    if len(sys.argv) > 1 and sys.argv[1].startswith("--null="):
        null_mode = sys.argv[1].split("=", 1)[1]
    main(null_mode=null_mode)
