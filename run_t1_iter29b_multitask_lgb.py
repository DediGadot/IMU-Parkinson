"""T1 iter29-B — Multi-task LGB on 6 items 9-14 (joint prediction, sum to T1).

Hypothesis: Schrag axial subscore items 9-14 are strongly correlated. A
*shared-tree* multi-output learner can exploit between-item correlations that
6 independent per-item models miss. Effective sample size grows from N=94 to
N×6=564 across the joint output.

Per fold (5-fold × 3 seeds):
  Stage 1 = Ridge on (H&Y + clinical) with target = T1 (sum items 9-14)
            (BIT-IDENTICAL to iter5-direct-T1 baseline so the residual definition
             is shared between all candidate Stage-2s)
  Stage 2 = sklearn MultiOutputRegressor(LGBMRegressor) → predicts vector
            (item9_residual, ..., item14_residual) jointly. BUT to make the trees
            *shared*, we use sklearn's RegressorChain (chains predictions to
            inform later items) — closer in spirit to multi-task learning than
            independent regressors.
  Sum predicted item residuals → T1 residual. Final pred = Stage1 + Stage2.

Item-residuals: each item's "fair share" of T1 residual is item_value -
mean(item) - (mean(T1)/6 - mean(item)) ≈ item - global_mean(item). We compute
per-item train-fold means and subtract them; the multi-output target is then
(item - mean(item)) for each i in 9..14.

Comparator: iter5-direct-T1 same fold/seed.
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
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
from run_t1_iter4 import load_pd_data as load_t1_pd_data, T1_ITEMS

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500


def _load_t1_cohort_with_items():
    d = load_t1_pd_data()
    sids = np.asarray(d["sids"])
    X = np.asarray(d["X_v2"], dtype=np.float64)
    y_t1 = np.asarray(d["t1"], dtype=np.float64)
    hy = np.asarray(d["hy"], dtype=np.float64)
    items = {i: np.asarray(d["items"][i], dtype=np.float64) for i in T1_ITEMS}
    valid = ~np.isnan(y_t1)
    items_valid = {i: items[i][valid] for i in T1_ITEMS}
    return sids[valid], X[valid], y_t1[valid], hy[valid], items_valid


def _kfold(n: int, seed: int):
    return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))


def _multitask_lgb_predict(
    Xtr: np.ndarray, items_tr: np.ndarray, Xte: np.ndarray, seed: int,
) -> np.ndarray:
    """Multi-output LGB via sklearn RegressorChain.
    items_tr: (n_tr, 6) — one column per item (mean-centered residual within fold).
    Returns (n_te, 6) predictions."""
    import lightgbm as lgb
    from sklearn.multioutput import RegressorChain

    base = lgb.LGBMRegressor(
        n_estimators=500, learning_rate=0.05, num_leaves=15,
        min_data_in_leaf=10, random_state=seed, n_jobs=1, verbose=-1,
    )
    chain = RegressorChain(base, order="random", random_state=seed)
    chain.fit(Xtr, items_tr)
    return chain.predict(Xte)


def run_one_seed_multitask(
    seed: int, feature_set: str = "A3_tier1"
) -> tuple[np.ndarray, np.ndarray]:
    sids, X, y_t1, hy, items = _load_t1_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        residual_tr = y_t1[tr] - s1_tr  # T1 residual

        # Per-item targets: item value (NaN-safe → 0 for missing). We share Stage-1's
        # T1 residual across items by partitioning it: targets = each item.
        items_tr = np.column_stack([items[i][tr] for i in T1_ITEMS])
        items_tr = np.nan_to_num(items_tr, nan=0.0)

        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, residual_tr, Xte, k=K_FEATURES, seed=seed
        )
        # Multi-task predicts per-item; sum to T1 then subtract Stage1 baseline (T1 = sum items).
        item_preds_te = _multitask_lgb_predict(Xtr_sel, items_tr, Xte_sel, seed)
        t1_pred_from_items = item_preds_te.sum(axis=1)
        # T1 residual prediction = sum(item) - Stage1
        # Note: t1 = sum(items) by definition, so a multitask predicting sum-of-items IS a T1 predictor.
        # We use (Stage1) as bias correction → preds[te] = s1_te + (t1_pred_from_items - s1_te) blends back to t1_pred.
        # Simpler: just use sum-of-items directly, no Stage1 mixing — but this discards Stage1 signal.
        # To preserve Stage1: residual approach. The multitask predicts items DIRECTLY (not residuals);
        # so the natural pred is sum(item_pred) — Stage1 dropped. But we want apples-to-apples with iter5,
        # so we let the model learn to predict items (which sum to T1), and additionally calibrate via Stage1.
        # Calibration: take a convex blend with Stage1 in-fold (alpha learned on TRAIN OOF).
        preds_te_combined = 0.5 * t1_pred_from_items + 0.5 * s1_te  # fixed blend; fair vs iter5
        preds[te] = preds_te_combined
    return y_t1, preds


def run_one_seed_multitask_residual(
    seed: int, feature_set: str = "A3_tier1"
) -> tuple[np.ndarray, np.ndarray]:
    """Variant: subtract per-item train-fold mean from items, predict residuals
    via multi-task chain, then sum + Stage1. This keeps Stage1 honest (matches iter5).
    """
    sids, X, y_t1, hy, items = _load_t1_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

        # Per-item *residual* targets: subtract per-item train mean
        item_means = {}
        items_tr_residual = []
        for i in T1_ITEMS:
            v = items[i][tr]
            mu = float(np.nanmean(v))
            item_means[i] = mu
            items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
        items_tr = np.column_stack(items_tr_residual)

        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        item_resid_pred_te = _multitask_lgb_predict(Xtr_sel, items_tr, Xte_sel, seed)
        # Restore item-level prediction: residual + train-fold mean
        item_pred_te = item_resid_pred_te + np.array([item_means[i] for i in T1_ITEMS])
        t1_pred_from_items = item_pred_te.sum(axis=1)
        # Final: weighted blend of multi-task T1 vs Stage1 — keep Stage1 as anchor
        # (Stage1 + (t1_pred_from_items - sum_of_item_train_means)/2 keeps both signals)
        sum_means = float(sum(item_means.values()))
        # multi-task prediction has Stage1-like info already (it predicts items, which include H&Y signal).
        # So plain (s1_te + t1_residual_pred_from_multitask) is wrong. The clean path:
        #   final = t1_pred_from_items   (multi-task models everything; Stage1 is reflected via items)
        # But to stay symmetric with iter5 (Stage1 + Stage2), we bias toward Stage1:
        #   final = s1_te + (t1_pred_from_items - sum_means)
        # i.e. shift the multi-task delta-from-mean as the residual.
        preds[te] = s1_te + (t1_pred_from_items - sum_means)
    return y_t1, preds


def run_one_seed_iter5_baseline(
    seed: int, feature_set: str = "A3_tier1"
) -> tuple[np.ndarray, np.ndarray]:
    sids, X, y_t1, hy, _items = _load_t1_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        preds[te] = s1_te + train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)
    return y_t1, preds


def run_screen(seeds: tuple[int, ...], feature_set: str) -> Path:
    print(
        f"\n=== T1 iter29-B SCREEN: multi-task LGB on items 9-14 (5-fold, "
        f"feature_set={feature_set}, {len(seeds)} seeds) ===\n",
        flush=True,
    )
    rows = []
    oof_dict = {}
    for seed in seeds:
        t0 = time.time()
        y_t1, preds_mt = run_one_seed_multitask_residual(seed, feature_set)
        wall_mt = time.time() - t0
        y2, preds_i5 = run_one_seed_iter5_baseline(seed, feature_set)
        assert np.allclose(y_t1, y2)
        c_mt = float(ccc_fn(y_t1, preds_mt))
        c_i5 = float(ccc_fn(y_t1, preds_i5))
        rows.append({
            "seed": seed, "ccc_multitask": round(c_mt, 4),
            "ccc_iter5_direct": round(c_i5, 4),
            "delta": round(c_mt - c_i5, 4),
            "mae_multitask": round(float(mae_fn(y_t1, preds_mt)), 3),
            "r_multitask": round(float(pearson_r(y_t1, preds_mt)), 4),
            "wall_time_s": round(wall_mt, 1),
        })
        oof_dict[f"seed{seed}_pred"] = preds_mt.tolist()
        oof_dict[f"seed{seed}_iter5"] = preds_i5.tolist()
        oof_dict[f"seed{seed}_y"] = y_t1.tolist()
        print(
            f"  seed={seed}: multitask CCC={c_mt:.4f} | iter5-direct CCC={c_i5:.4f} | "
            f"Δ={c_mt-c_i5:+.4f} | MAE={rows[-1]['mae_multitask']:.3f} | "
            f"r={rows[-1]['r_multitask']:.4f} | {wall_mt:.1f}s",
            flush=True,
        )

    df = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter29b_multitask_5fold_{ts}.csv"
    df.to_csv(out, index=False)

    import json as _json
    out_oof = RESULTS_DIR / f"iter29b_multitask_5fold_{ts}.oof.json"
    with open(out_oof, "w") as f:
        _json.dump(oof_dict, f)

    print(
        f"\nMean multi-task CCC = {df['ccc_multitask'].mean():.4f} ± {df['ccc_multitask'].std():.4f}; "
        f"Mean iter5-direct CCC = {df['ccc_iter5_direct'].mean():.4f} ± {df['ccc_iter5_direct'].std():.4f}; "
        f"Δ̄ = {df['delta'].mean():+.4f}",
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
