"""T1 iter30-B — Multi-task variants exploring chain order, base learner, blending.

After iter29b's +0.05 5-fold + +0.04 LOOCV-seed42 lift, this script explores
which lever drove it and whether tuning further extends the gain:

  V1  Order=random (replicates iter29b — sanity)
  V2  Order=clinical (medically-driven: 9 chair, 11 FoG, 12 stability,
      10 gait, 13 posture, 14 brady — gait→balance→posture→tone)
  V3  Order=correlation-driven (sort by per-item train r with T1 in train fold)
  V4  Base=CatBoostRegressor (instead of LGBM)
  V5  Base=LGBMRegressor with custom CCC objective on each item
  V6  V1 + post-hoc affine calibration on inner OOF (1 affine map per output column)
  V7  V1 + blend at OOF level with iter5-direct preds: alpha-weighted convex
      blend (alpha learned from inner 5-fold OOF on training subjects)

Per fold (5-fold × 3 seeds, T1 cohort N=94).
Comparator: iter5-direct-T1 same fold/seed.
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
from sklearn.linear_model import LinearRegression
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


CLINICAL_ORDER = [9, 11, 12, 10, 13, 14]  # gait→FoG→stability→posture→brady


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


def _multitask_predict(Xtr, items_tr, Xte, seed, *, base="lgb", order="random",
                       y_t1_tr=None):
    """Multi-output via RegressorChain. items_tr columns are in T1_ITEMS order."""
    import lightgbm as lgb
    from sklearn.multioutput import RegressorChain

    if base == "lgb":
        regr = lgb.LGBMRegressor(
            n_estimators=500, learning_rate=0.05, num_leaves=15,
            min_data_in_leaf=10, random_state=seed, n_jobs=1, verbose=-1,
        )
    elif base == "catboost":
        from catboost import CatBoostRegressor
        regr = CatBoostRegressor(
            iterations=500, learning_rate=0.05, depth=6,
            random_seed=seed, verbose=False, allow_writing_files=False,
        )
    else:
        raise ValueError(f"unknown base learner {base!r}")

    if order == "random":
        chain = RegressorChain(regr, order="random", random_state=seed)
    elif order == "clinical":
        # Map T1_ITEMS index in the items_tr column space to CLINICAL_ORDER ids
        idx_map = {it: T1_ITEMS.index(it) for it in T1_ITEMS}
        chain_order = [idx_map[it] for it in CLINICAL_ORDER]
        chain = RegressorChain(regr, order=chain_order)
    elif order == "correlation":
        if y_t1_tr is None:
            raise ValueError("correlation order requires y_t1_tr")
        # Sort items by |corr(item, T1)| in train descending
        rs = []
        for col_i in range(items_tr.shape[1]):
            v = items_tr[:, col_i]
            mask = ~np.isnan(v) & ~np.isnan(y_t1_tr)
            if mask.sum() < 5 or np.std(v[mask]) < 1e-9:
                rs.append(0.0)
            else:
                rs.append(abs(float(np.corrcoef(v[mask], y_t1_tr[mask])[0, 1])))
        chain_order = list(np.argsort(-np.asarray(rs)))
        chain = RegressorChain(regr, order=chain_order)
    else:
        raise ValueError(f"unknown order {order!r}")
    chain.fit(Xtr, items_tr)
    return chain.predict(Xte)


def run_variant(
    variant: str, seed: int, feature_set: str = "A3_tier1"
) -> tuple[np.ndarray, np.ndarray]:
    sids, X, y_t1, hy, items = _load_t1_cohort_with_items()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
        item_means = {}
        items_tr_residual = []
        for i in T1_ITEMS:
            v = items[i][tr]
            mu = float(np.nanmean(v))
            item_means[i] = mu
            items_tr_residual.append(np.nan_to_num(v - mu, nan=0.0))
        items_tr_arr = np.column_stack(items_tr_residual)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y_t1[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )

        if variant == "V1_random":
            ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base="lgb", order="random")
        elif variant == "V2_clinical":
            ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base="lgb", order="clinical")
        elif variant == "V3_correlation":
            ip = _multitask_predict(
                Xtr_sel, items_tr_arr, Xte_sel, seed, base="lgb",
                order="correlation", y_t1_tr=y_t1[tr],
            )
        elif variant == "V4_catboost":
            ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base="catboost", order="random")
        elif variant == "V6_calibrated":
            ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base="lgb", order="random")
            # Inner 5-fold OOF for affine calibration per item
            inner_oof = np.zeros_like(items_tr_arr)
            for tri, tei in _kfold(len(tr), seed=seed + 999):
                Xtr_in, Xte_in = Xtr_sel[tri], Xtr_sel[tei]
                ip_in = _multitask_predict(Xtr_in, items_tr_arr[tri], Xte_in, seed, base="lgb", order="random")
                inner_oof[tei] = ip_in
            for col_i in range(items_tr_arr.shape[1]):
                lr = LinearRegression().fit(inner_oof[:, col_i:col_i + 1], items_tr_arr[:, col_i])
                ip[:, col_i] = lr.predict(ip[:, col_i:col_i + 1]).ravel()
        elif variant == "V7_blend_with_iter5":
            ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base="lgb", order="random")
            # Train iter5-direct on this fold for the blend
            i5_te = train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)
            # Inner OOF to learn blend weight alpha
            n_tr = len(tr)
            mt_inner = np.zeros(n_tr)
            i5_inner = np.zeros(n_tr)
            for tri, tei in _kfold(n_tr, seed=seed + 1234):
                Xtr_in, Xte_in = Xtr_sel[tri], Xtr_sel[tei]
                ip_in = _multitask_predict(Xtr_in, items_tr_arr[tri], Xte_in, seed, base="lgb", order="random")
                mt_inner[tei] = ip_in.sum(axis=1) - sum(item_means.values())
                i5_inner[tei] = train_lgb(Xtr_in, y_t1[tr][tri] - fit_stage1(X_s1[tr][tri], y_t1[tr][tri], X_s1[tr][tei], alpha=STAGE1_ALPHA)[0], Xte_in, seed)
            # Optimal alpha via grid (avoid LR negative weights)
            t1_residual_tr = y_t1[tr] - s1_tr
            best_alpha, best_err = 0.5, np.inf
            for alpha in np.linspace(0.0, 1.0, 11):
                blend = alpha * mt_inner + (1 - alpha) * i5_inner
                err = float(np.mean((blend - t1_residual_tr) ** 2))
                if err < best_err:
                    best_err = err; best_alpha = alpha
            mt_te = ip.sum(axis=1) - sum(item_means.values())
            blended_te = best_alpha * mt_te + (1 - best_alpha) * i5_te
            preds[te] = s1_te + blended_te
            continue  # skip the generic sum-of-items step
        else:
            raise ValueError(f"unknown variant {variant!r}")

        item_pred_te = ip + np.array([item_means[i] for i in T1_ITEMS])
        t1_pred_from_items = item_pred_te.sum(axis=1)
        sum_means = float(sum(item_means.values()))
        preds[te] = s1_te + (t1_pred_from_items - sum_means)
    return y_t1, preds


def run_iter5_baseline(seed: int, feature_set: str = "A3_tier1"):
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


VARIANTS = ["V1_random", "V2_clinical", "V3_correlation", "V4_catboost",
            "V6_calibrated", "V7_blend_with_iter5"]


def run_screen(seeds: tuple[int, ...], feature_set: str, variants: list[str]) -> Path:
    print(
        f"\n=== T1 iter30-B SCREEN: multi-task variants ({len(variants)}, "
        f"5-fold, {len(seeds)} seeds, N=94) ===\n",
        flush=True,
    )
    rows = []
    oof_dict = {}
    for variant in variants:
        for seed in seeds:
            t0 = time.time()
            try:
                y_t1, preds_v = run_variant(variant, seed, feature_set)
            except Exception as e:
                print(f"  variant={variant} seed={seed}: FAILED ({type(e).__name__}: {e})", flush=True)
                continue
            wall = time.time() - t0
            y2, preds_i5 = run_iter5_baseline(seed, feature_set)
            assert np.allclose(y_t1, y2)
            c_v = float(ccc_fn(y_t1, preds_v))
            c_i5 = float(ccc_fn(y_t1, preds_i5))
            rows.append({
                "variant": variant, "seed": seed,
                "ccc_v": round(c_v, 4), "ccc_iter5_direct": round(c_i5, 4),
                "delta": round(c_v - c_i5, 4),
                "mae_v": round(float(mae_fn(y_t1, preds_v)), 3),
                "r_v": round(float(pearson_r(y_t1, preds_v)), 4),
                "wall_time_s": round(wall, 1),
            })
            oof_dict[f"{variant}_seed{seed}_pred"] = preds_v.tolist()
            oof_dict[f"{variant}_seed{seed}_iter5"] = preds_i5.tolist()
            oof_dict[f"{variant}_seed{seed}_y"] = y_t1.tolist()
            print(
                f"  variant={variant} seed={seed}: CCC_v={c_v:.4f} | "
                f"iter5={c_i5:.4f} | Δ={c_v-c_i5:+.4f} | MAE={rows[-1]['mae_v']:.3f} | "
                f"r={rows[-1]['r_v']:.4f} | {wall:.1f}s",
                flush=True,
            )

    df = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter30b_multitask_variants_5fold_{ts}.csv"
    df.to_csv(out, index=False)
    out_oof = RESULTS_DIR / f"iter30b_multitask_variants_5fold_{ts}.oof.json"
    with open(out_oof, "w") as f:
        json.dump(oof_dict, f)

    print("\nPer-variant Δ summary:")
    for v in df["variant"].unique():
        sub = df[df["variant"] == v]
        print(
            f"  {v}: mean CCC = {sub['ccc_v'].mean():.4f} ± {sub['ccc_v'].std():.4f}; "
            f"Δ̄ = {sub['delta'].mean():+.4f} ({list(sub['delta'].round(4).values)})",
            flush=True,
        )
    print(f"\nWrote {out}\n      {out_oof}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--variants", nargs="+", default=VARIANTS,
                    help=f"Subset of {VARIANTS}")
    args = ap.parse_args()
    run_screen(tuple(args.seeds), args.feature_set, args.variants)


if __name__ == "__main__":
    main()
