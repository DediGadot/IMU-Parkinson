"""Lockbox LOOCV for the pre-registered T3 winner: hy_residual.

Pipeline (frozen at pre-registration time):
  1. Per-fold (LOOCV — 89 folds): hold out 1 PD subject as test.
  2. On the 88 training subjects:
     a. Fit Ridge(alpha=1.0) on H&Y features → predict T3.
     b. Compute T3_residual = T3 - hy_pred (training only).
     c. Fit per-fold median imputer on v2 features.
     d. Per-fold feature selection (LightGBM importance, K=500).
     e. Fit LightGBM on v2_features → T3_residual.
  3. Test: predict hy_pred + lgb_residual_pred = T3_pred.
  4. Aggregate: CCC, MAE, slope, r over all 89 hold-outs.

Multi-seed (3 seeds) for noise reduction. Headline = mean of 3-seed CCCs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter3 import load_full_pd_data, get_hy_features
from run_t3_iter2 import impute_fold, feature_select_fold, train_lgb

ensure_dir(RESULTS_DIR)
SEEDS = [42, 1337, 7]


def hy_residual_loocv(seed: int = 42):
    sids, X, fc, y_t3, hy, obs = load_full_pd_data()
    n = len(sids)
    print(f"  n={n} PD, seed={seed}")
    hy_feat = get_hy_features(hy)
    preds = np.zeros(n)
    loo = LeaveOneOut()
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(loo.split(np.arange(n))):
        # Stage 1: Ridge on H&Y → T3
        ridge = Ridge(alpha=1.0)
        ridge.fit(hy_feat[tr], y_t3[tr])
        hy_pred_tr = ridge.predict(hy_feat[tr])
        hy_pred_te = ridge.predict(hy_feat[te])
        residual_tr = y_t3[tr] - hy_pred_tr
        # Stage 2: LGB on v2 features → residual
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        imu_res_pred = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        preds[te] = hy_pred_te + imu_res_pred
        if (fold_idx + 1) % 10 == 0:
            print(f"  fold {fold_idx+1}/{n}, elapsed {time.time()-t0:.1f}s")
    return sids, y_t3, preds


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--prereg-only", action="store_true",
                   help="Just write the pre-registration JSON without running LOOCV")
    args = p.parse_args()

    # Step 1: Write pre-registration BEFORE running LOOCV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": timestamp,
        "iso_datetime": datetime.now().isoformat(),
        "winner_variant": "hy_residual",
        "rationale": (
            "Iter 2+3 5-fold CCC ranking: hy_residual is the clear winner at CCC=0.402±0.054, "
            "exceeding all other 19 variants. Tied band winners (within 0.05 CCC): "
            "obs_subscore_aux (0.310), per_item_sum (0.310), hy_only (0.299), site_mixed_effects (0.292), "
            "best_stack_full (0.291). hy_residual chosen by the lockbox tiebreaker: highest 5-fold CCC."
        ),
        "pipeline_spec": {
            "stage_1": "Ridge(alpha=1.0) on H&Y features (1 linear + 5 one-hot bins) → T3",
            "stage_2": "LightGBM on v2 handcrafted features → (T3 - Stage1_pred) residual",
            "feature_selection": "Per-fold LightGBM importance, top K=500",
            "imputation": "Per-fold median, NaN→median",
            "lgb_params": {
                "n_estimators": 500, "learning_rate": 0.05, "num_leaves": 15,
                "min_data_in_leaf": 10, "reg_alpha": 0.1, "reg_lambda": 0.3,
                "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 5,
            },
        },
        "eval_protocol": "LOOCV (n=89), 3-seed average, no per-fold tuning.",
        "expected_loocv_range": "[0.30, 0.45] (5-fold was 0.402±0.054)",
        "headline_metric": "CCC of mean-of-3-seed predictions",
        "lockbox_rules": [
            "ONE pipeline pre-registered. ONE LOOCV run. Headline = result, no cherry-picking.",
            "5-null gate already passed at 5-fold for the underlying components.",
            "If LOOCV CCC < 0.20, report as null result; do not select runner-up.",
        ],
    }
    prereg_path = RESULTS_DIR / f"preregistration_t3_{timestamp}.json"
    with open(prereg_path, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {prereg_path}")

    if args.prereg_only:
        return

    # Step 2: Run LOOCV
    print(f"\n=== Lockbox LOOCV: hy_residual, {args.seeds} seeds ===")
    all_preds = []
    for seed in SEEDS[:args.seeds]:
        sids, y_t3, preds = hy_residual_loocv(seed=seed)
        ccc = ccc_fn(y_t3, preds)
        mae = mae_fn(y_t3, preds)
        r = pearson_r(y_t3, preds)
        print(f"  seed {seed}: CCC={ccc:.4f}, MAE={mae:.3f}, r={r:.3f}")
        all_preds.append((seed, preds))

    # Mean of seeds = headline
    mean_preds = np.mean(np.column_stack([p for _, p in all_preds]), axis=1)
    headline = full_metrics(y_t3, mean_preds, label="hy_residual_loocv")
    headline.update({
        "variant": "hy_residual",
        "eval_mode": "loocv",
        "n_seeds": args.seeds,
        "per_seed_ccc": [float(ccc_fn(y_t3, p)) for _, p in all_preds],
        "per_seed_mae": [float(mae_fn(y_t3, p)) for _, p in all_preds],
        "per_subject": {
            "sids": sids.tolist(),
            "y_true": y_t3.tolist(),
            "y_pred": mean_preds.tolist(),
        },
        "preregistration_file": str(prereg_path.name),
        "is_lockbox_headline": True,
    })
    out = RESULTS_DIR / "iter3_hy_residual_t3_loocv.json"
    with open(out, "w") as f:
        json.dump(headline, f, indent=2, default=str)
    print(f"\n=== HEADLINE (lockbox): CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f}, "
          f"r={headline['r']:.4f}, slope={headline['cal_slope']:.3f} ===")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
