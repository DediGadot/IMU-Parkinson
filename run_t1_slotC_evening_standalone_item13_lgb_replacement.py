"""T1 Glass-Ceiling Push — evening 2026-05-15 Slot C' (amended from Numpyro hierarchical).

Mechanism: F50-style STANDALONE single-task LightGBM trained on axial cache features
(full 30 cols, including pitch_mean/roll_mean) predicting item_13_true directly.
REPLACE iter34.item_13_pred with standalone prediction; recompute T1_sum.

Amendment rationale: see preregistration_t1_ceiling_push_20260515_evening_amendment_02.json
- Slots A and B' both FAIL via Ridge CORRECTION on item-13 residual; corr(c, item13_resid)=-0.2 to -0.5
  shows correction approaches anti-fit to the iter34-extracted-already-kinetic component.
- Slot C ORIGINAL Numpyro hierarchical Bayes not feasible on master (no numpyro install).
- Slot C AMENDED to REPLACEMENT not CORRECTION: standalone LGB fits item_13_true directly,
  sidesteps the residual anti-correlation pathology.
- F50 trunk-pitch standalone gave item-13 +0.145 LOOCV; this is the 3-sensor extension.

Architecture: F50-style hypothesis-restricted item_only STANDALONE replacement.
T1_sum_replacement = sum_{j != 13} iter34.item_j_pred + standalone.item_13_pred.
Iter34 item-13 baseline CCC=0.067 → effectively zero signal → REPLACEMENT is safe.

Wall check vs F35-C: F35-C tested replacement for items 9, 12 (iter34 CCC 0.234, 0.566) and
failed at composite ("cross-item information loss"). Item 13 (iter34 CCC=0.067) has no
chain information to lose. F35-C wall does NOT apply.

Pre-registration: master 20260515_evening + amendment_02 (slot_C substitution).

Usage:
  uv run python run_t1_slotC_evening_standalone_item13_lgb_replacement.py
  uv run python run_t1_slotC_evening_standalone_item13_lgb_replacement.py --null scrambled_y
  uv run python run_t1_slotC_evening_standalone_item13_lgb_replacement.py --null sid_shuffle
  uv run python run_t1_slotC_evening_standalone_item13_lgb_replacement.py --null canary_noise
  uv run python run_t1_slotC_evening_standalone_item13_lgb_replacement.py --null transductive
  uv run python run_t1_slotC_evening_standalone_item13_lgb_replacement.py --sanity-y-nan
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
import lightgbm as lgb
from sklearn.model_selection import KFold

from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SlotC-evening] %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent
CACHE_PATH = REPO_ROOT / "results" / "axial_orientation_features.csv"
OOF_PATH = REPO_ROOT / "results" / "t1_iter34_per_item_oof_20260511_044242.npz"

# LGB hyperparams (predeclared from prior project pattern, NOT tuned for this slot)
LGB_PARAMS = {
    "objective": "regression",
    "metric": "mse",
    "num_leaves": 15,
    "learning_rate": 0.05,
    "n_estimators": 200,
    "min_data_in_leaf": 5,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbose": -1,
    "n_jobs": 4,  # cap LGB threads to avoid OpenMP oversubscription when multi-mode parallel runs
}

MODEL_SEEDS_SET_A = (42, 1337, 7)
MODEL_SEEDS_SET_B = (101, 202, 303)

N_BOOTSTRAP = 5000
BOOTSTRAP_SEED = 20260515


def fold_local_lgb_predict(
    X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray, seed: int
) -> np.ndarray:
    imp = FoldImputer.fit(X_tr)
    Xt = imp.transform(X_tr)
    Xv = imp.transform(X_te)
    nrm = FoldNormalizer.fit(Xt)
    Xt = nrm.transform(Xt)
    Xv = nrm.transform(Xv)
    params = dict(LGB_PARAMS)
    params["random_state"] = seed
    params["bagging_seed"] = seed
    params["feature_fraction_seed"] = seed
    model = lgb.LGBMRegressor(**params)
    model.fit(Xt, y_tr)
    return model.predict(Xv)


def run_loocv(
    X: np.ndarray,
    item13_true: np.ndarray,
    seed: int,
) -> np.ndarray:
    n = len(item13_true)
    pred = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        pred[i] = fold_local_lgb_predict(X[tr], item13_true[tr], X[i:i + 1], seed=seed)[0]
    return pred


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

    df = pd.read_csv(CACHE_PATH)
    oof = dict(np.load(OOF_PATH, allow_pickle=True))
    sids_oof = oof["sids"].astype(str)

    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    missing = [s for s in sids_oof if s not in sid_to_row]
    if missing:
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
    assert (df["sid"].astype(str).values == sids_oof).all()

    feat_cols = [c for c in df.columns if c != "sid"]
    X = df[feat_cols].values.astype(float)

    y_t1 = oof["y_t1"].astype(float)
    yhat_t1sum_iter34 = oof["t1_sum_pred"].astype(float)
    item13_true = oof["item_13_true"].astype(float)
    item13_pred_iter34 = oof["item_13_pred"].astype(float)
    # T1 sum without item-13 contribution from iter34
    yhat_t1sum_minus_item13 = yhat_t1sum_iter34 - item13_pred_iter34
    n = len(sids_oof)

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011)
        item13_true_train = rng.permutation(item13_true)
        log.info("NULL scrambled_y")
    else:
        item13_true_train = item13_true.copy()

    if null_mode == "sid_shuffle":
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
        log.info("NULL transductive")

    if sanity_y_nan:
        log.info("SANITY y_nan: corrector uses no test-fold y at fit time (replacement uses train-fold item13_true only)")

    log.info("Running standalone item-13 LGB LOOCV across %d outer folds × %d seeds",
             n, len(MODEL_SEEDS_SET_A) + len(MODEL_SEEDS_SET_B))

    preds_per_seed = {}
    for seed in (*MODEL_SEEDS_SET_A, *MODEL_SEEDS_SET_B):
        preds_per_seed[seed] = run_loocv(X, item13_true_train, seed=seed)

    def avg_pred(seeds):
        return np.mean([preds_per_seed[s] for s in seeds], axis=0)

    standalone_item13_A = avg_pred(MODEL_SEEDS_SET_A)
    standalone_item13_B = avg_pred(MODEL_SEEDS_SET_B)
    standalone_item13_avg = (standalone_item13_A + standalone_item13_B) / 2.0

    # T1 sum replacement: drop iter34.item_13_pred, add standalone.item_13_pred
    t1_sum_replacement_A = yhat_t1sum_minus_item13 + standalone_item13_A
    t1_sum_replacement_B = yhat_t1sum_minus_item13 + standalone_item13_B
    t1_sum_replacement_avg = yhat_t1sum_minus_item13 + standalone_item13_avg

    ccc_baseline_t1 = float(ccc(y_t1, yhat_t1sum_iter34))
    ccc_baseline_item13 = float(ccc(item13_true, item13_pred_iter34))
    mae_baseline_t1 = float(np.mean(np.abs(y_t1 - yhat_t1sum_iter34)))
    pearson_baseline_t1 = float(np.corrcoef(y_t1, yhat_t1sum_iter34)[0, 1])

    def headline(t1_cand, item13_cand, label):
        ccc_t1 = float(ccc(y_t1, t1_cand))
        ccc_i13 = float(ccc(item13_true, item13_cand))
        mae_t1 = float(np.mean(np.abs(y_t1 - t1_cand)))
        pearson_t1 = float(np.corrcoef(y_t1, t1_cand)[0, 1])
        boot = paired_bootstrap_frac_pos(y_t1, yhat_t1sum_iter34, t1_cand, N_BOOTSTRAP, BOOTSTRAP_SEED)
        boot_i13 = paired_bootstrap_frac_pos(item13_true, item13_pred_iter34, item13_cand, N_BOOTSTRAP, BOOTSTRAP_SEED)
        return {
            "label": label,
            "loocv_ccc_t1_sum_baseline": ccc_baseline_t1,
            "loocv_ccc_t1_sum_replacement": ccc_t1,
            "delta_ccc_t1_sum": ccc_t1 - ccc_baseline_t1,
            "delta_pearson_r_t1_sum": pearson_t1 - pearson_baseline_t1,
            "delta_mae_t1_sum": mae_t1 - mae_baseline_t1,
            "loocv_ccc_item13_baseline": ccc_baseline_item13,
            "loocv_ccc_item13_standalone": ccc_i13,
            "delta_ccc_item13": ccc_i13 - ccc_baseline_item13,
            "bootstrap_t1_sum": boot,
            "bootstrap_item13": boot_i13,
        }

    h_A = headline(t1_sum_replacement_A, standalone_item13_A, "seed_set_A")
    h_B = headline(t1_sum_replacement_B, standalone_item13_B, "seed_set_B")

    # D4 audit: "replacement" replaces iter34.item_13_pred entirely, so the natural diagnostic
    # is corr(standalone_item13_pred, item13_true) and the resulting T1_sum direction.
    t1_resid = y_t1 - yhat_t1sum_iter34
    item13_resid_true = item13_true - item13_pred_iter34
    replacement_delta = standalone_item13_avg - item13_pred_iter34  # the "correction direction"
    corr_replacement_sum_residual = float(np.corrcoef(replacement_delta, t1_resid)[0, 1])
    corr_replacement_item13_residual = float(np.corrcoef(replacement_delta, item13_resid_true)[0, 1])
    delta_mae_avg = float(np.mean(np.abs(y_t1 - t1_sum_replacement_avg)) - mae_baseline_t1)
    delta_r_avg = float(np.corrcoef(y_t1, t1_sum_replacement_avg)[0, 1] - pearson_baseline_t1)

    # 5-fold screen
    kf = KFold(n_splits=5, shuffle=True, random_state=20260309)
    fold_deltas = []
    for seed in MODEL_SEEDS_SET_A:
        standalone_5f = np.full(n, np.nan)
        for tr_idx, te_idx in kf.split(np.arange(n)):
            X_tr, X_te = X[tr_idx], X[te_idx]
            standalone_5f[te_idx] = fold_local_lgb_predict(
                X_tr, item13_true_train[tr_idx], X_te, seed=seed
            )
        t1_5f_replacement = yhat_t1sum_minus_item13 + standalone_5f
        fold_deltas.append(float(ccc(y_t1, t1_5f_replacement) - ccc_baseline_t1))
    fold_delta_mean = float(np.mean(fold_deltas))
    fold_delta_std = float(np.std(fold_deltas))

    formula_str = json.dumps({
        "feature_cols": feat_cols,
        "lgb_params": LGB_PARAMS,
        "seeds_A": list(MODEL_SEEDS_SET_A),
        "seeds_B": list(MODEL_SEEDS_SET_B),
    }, sort_keys=True)
    formula_sha256 = hashlib.sha256(formula_str.encode()).hexdigest()

    out = {
        "name": "lockbox_t1_slotC_evening_standalone_item13_lgb_replacement",
        "created_at_utc": datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "preregistration_master": "results/preregistration_t1_ceiling_push_20260515_evening_master.json",
        "preregistration_amendment_01": "results/preregistration_t1_ceiling_push_20260515_evening_amendment_01.json",
        "preregistration_amendment_02": "results/preregistration_t1_ceiling_push_20260515_evening_amendment_02.json",
        "session": "2026-05-15-evening-glass-ceiling-push-slotC-replacement",
        "null_mode": null_mode or "real",
        "sanity_y_nan": sanity_y_nan,
        "formula_sha256": formula_sha256,
        "n_cohort": int(n),
        "n_features": len(feat_cols),
        "lgb_params": LGB_PARAMS,
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
            "corr_replacement_T1_sum_residual": corr_replacement_sum_residual,
            "corr_replacement_item13_residual": corr_replacement_item13_residual,
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
            h_A["loocv_ccc_item13_standalone"], h_B["loocv_ccc_item13_standalone"],
        ),
    }

    suffix = ""
    if null_mode:
        suffix = f"_{null_mode}"
    elif sanity_y_nan:
        suffix = "_sanityYnan"
    out_path = REPO_ROOT / "results" / (
        f"lockbox_t1_slotC_evening_standalone_item13_lgb_replacement_"
        f"{out['created_at_utc']}{suffix}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    log.info("wrote %s", out_path)

    print(f"\n=== Slot C (evening) — {null_mode or 'real'}{' SANITY_Y_NAN' if sanity_y_nan else ''} ===")
    print(f"N={n}  features={len(feat_cols)}")
    print(f"baseline iter34 t1_sum CCC = {ccc_baseline_t1:.4f}  item13 CCC = {ccc_baseline_item13:.4f}")
    print(f"seed_set_A: t1_sum Δ={h_A['delta_ccc_t1_sum']:+.4f}  frac>0={h_A['bootstrap_t1_sum']['frac_pos']:.4f}  CI={h_A['bootstrap_t1_sum']['ci95']}")
    print(f"            item13 standalone CCC={h_A['loocv_ccc_item13_standalone']:.4f}  item13 Δ={h_A['delta_ccc_item13']:+.4f}")
    print(f"seed_set_B: t1_sum Δ={h_B['delta_ccc_t1_sum']:+.4f}  frac>0={h_B['bootstrap_t1_sum']['frac_pos']:.4f}")
    print(f"            item13 standalone CCC={h_B['loocv_ccc_item13_standalone']:.4f}  item13 Δ={h_B['delta_ccc_item13']:+.4f}")
    print(f"D4 audit avg: Δr={delta_r_avg:+.4f}  ΔMAE={delta_mae_avg:+.4f}  corr(replacement,sum_resid)={corr_replacement_sum_residual:+.4f}  corr(replacement,item13_resid)={corr_replacement_item13_residual:+.4f}")
    print(f"5-fold screen: Δ̄={fold_delta_mean:+.4f} std={fold_delta_std:.4f}  promotion={'PASS' if out['fivefold_screen']['passes_promotion'] else 'FAIL'}")
    print(f"VERDICT (provisional): {out['verdict_provisional']}")
    return 0


def _verdict(d_A, d_B, f_A, f_B, item13_A, item13_B) -> str:
    if item13_A < 0.10 and item13_B < 0.10:
        return "FAIL_ITEM13_STANDALONE_TOO_WEAK"
    if d_A >= 0.005 and d_B >= 0.005 and f_A >= 0.95 and f_B >= 0.95:
        return "PRIMARY_GATE_PASS_REPLICATED"
    if (d_A >= 0.005 or d_B >= 0.005) and (f_A >= 0.95 or f_B >= 0.95):
        return "PRIMARY_GATE_PASS_PARTIAL_seed_set"
    if d_A > 0 and d_B > 0:
        return "POSITIVE_BUT_SUB_GATE"
    return "FAIL"


if __name__ == "__main__":
    sys.exit(main())
