"""T3 iter30-A — Multi-task LGB on all 18 UPDRS-III items (cross-pollination from T1 iter29b).

Hypothesis: iter29b's multi-task chain on items 9-14 lifted T1 CCC by +0.05 5-fold.
The same mechanism on the FULL 18 items (predicting all of UPDRS-III items 1-18 jointly,
summing to T3) could lift T3 if between-item correlations exist outside items 9-14.

Per fold (5-fold × 3 seeds, T3 cohort N=98):
  Stage 1 = iter5 Ridge on H&Y + cv_yrs + cv_sex + cv_dbs (target = updrs3 directly)
  Stage 2 = sklearn RegressorChain(LGBMRegressor) predicting per-item residuals
            for items 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18.
  Final: Stage1 + (sum_of_predicted_items - sum_of_train_means)

Comparator: iter5-direct-T3 (Stage1 + Stage2 LGB on T3 directly), same fold/seed.
Canonical T3 LOOCV CCC = 0.5227.
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t3_iter3 import load_full_pd_data
from run_t1_iter29b_multitask_lgb import _multitask_lgb_predict
from run_t1_iter4 import load_per_item_scores

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500
ALL_ITEMS = list(range(1, 19))


def _load_t3_cohort_with_items():
    """Returns (sids, X_v2, y_t3, hy, items_dict). T3 cohort N=98."""
    sids, X, _fc, y_t3, hy, _obs = load_full_pd_data()
    pis = load_per_item_scores()  # dict sid → {item_id: value}
    items: dict[int, np.ndarray] = {}
    for it in ALL_ITEMS:
        arr = np.array(
            [pis.get(str(s), {}).get(it, np.nan) for s in sids], dtype=np.float64
        )
        items[it] = arr
    return sids, X, y_t3, hy, items


def _kfold(n: int, seed: int):
    return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))


def run_one_seed_multitask(seed: int, feature_set: str = "A3_tier1"):
    sids, X, y_t3, hy, items = _load_t3_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=STAGE1_ALPHA)
        item_means: dict[int, float] = {}
        items_tr_residual: list[np.ndarray] = []
        for i in ALL_ITEMS:
            v = items[i][tr]
            mu = float(np.nanmean(v)) if np.any(~np.isnan(v)) else 0.0
            item_means[i] = mu
            items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
        items_tr_arr = np.column_stack(items_tr_residual)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t3[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        item_resid_pred_te = _multitask_lgb_predict(Xtr_sel, items_tr_arr, Xte_sel, seed)
        item_pred_te = item_resid_pred_te + np.array([item_means[i] for i in ALL_ITEMS])
        t3_pred_from_items = item_pred_te.sum(axis=1)
        sum_means = float(sum(item_means.values()))
        preds[te] = s1_te + (t3_pred_from_items - sum_means)
    return y_t3, preds


def run_one_seed_iter5_baseline(seed: int, feature_set: str = "A3_tier1"):
    sids, X, _fc, y_t3, hy, _obs = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=STAGE1_ALPHA)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t3[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        preds[te] = s1_te + train_lgb(Xtr_sel, y_t3[tr] - s1_tr, Xte_sel, seed)
    return y_t3, preds


def run_screen(seeds: tuple[int, ...], feature_set: str) -> Path:
    print(
        f"\n=== T3 iter30-A SCREEN: multi-task LGB on items 1-18 (5-fold, "
        f"feature_set={feature_set}, {len(seeds)} seeds, N=98) ===\n",
        flush=True,
    )
    rows = []
    oof_dict = {}
    for seed in seeds:
        t0 = time.time()
        y_t3, preds_mt = run_one_seed_multitask(seed, feature_set)
        wall_mt = time.time() - t0
        y2, preds_i5 = run_one_seed_iter5_baseline(seed, feature_set)
        assert np.allclose(y_t3, y2)
        c_mt = float(ccc_fn(y_t3, preds_mt))
        c_i5 = float(ccc_fn(y_t3, preds_i5))
        rows.append({
            "seed": seed, "ccc_multitask_t3": round(c_mt, 4),
            "ccc_iter5_direct_t3": round(c_i5, 4),
            "delta": round(c_mt - c_i5, 4),
            "mae_multitask": round(float(mae_fn(y_t3, preds_mt)), 3),
            "r_multitask": round(float(pearson_r(y_t3, preds_mt)), 4),
            "wall_time_s": round(wall_mt, 1),
        })
        oof_dict[f"seed{seed}_pred"] = preds_mt.tolist()
        oof_dict[f"seed{seed}_iter5"] = preds_i5.tolist()
        oof_dict[f"seed{seed}_y"] = y_t3.tolist()
        print(
            f"  seed={seed}: MT-T3 CCC={c_mt:.4f} | iter5-direct-T3 CCC={c_i5:.4f} | "
            f"Δ={c_mt-c_i5:+.4f} | MAE={rows[-1]['mae_multitask']:.3f} | "
            f"r={rows[-1]['r_multitask']:.4f} | {wall_mt:.1f}s",
            flush=True,
        )

    df = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter30a_multitask_t3_5fold_{ts}.csv"
    df.to_csv(out, index=False)
    out_oof = RESULTS_DIR / f"iter30a_multitask_t3_5fold_{ts}.oof.json"
    with open(out_oof, "w") as f:
        json.dump(oof_dict, f)

    print(
        f"\nMean MT-T3 CCC = {df['ccc_multitask_t3'].mean():.4f} ± {df['ccc_multitask_t3'].std():.4f}; "
        f"Mean iter5-direct-T3 CCC = {df['ccc_iter5_direct_t3'].mean():.4f} ± "
        f"{df['ccc_iter5_direct_t3'].std():.4f}; Δ̄ = {df['delta'].mean():+.4f}",
        flush=True,
    )
    print(f"Wrote {out}\n      {out_oof}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    args = ap.parse_args()
    run_screen(tuple(args.seeds), args.feature_set)


if __name__ == "__main__":
    main()
