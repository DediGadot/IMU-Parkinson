"""T1 iter29-C — Direct CCC-objective LGB on T1 (single-stage with v2 fixes).

Hypothesis: training LGB to MAXIMIZE CCC directly, with the F50 v2 fixes
(init_score=mean(y), Pearson feature selector, hessian=1.0 scaling, post-hoc
affine calibration) might beat the standard MSE-based Stage1+Stage2 pipeline.
This was successful at per-item level (items 12, 18 with cccv2). Untried for T1
as a sum-target.

Per fold (5-fold × 3 seeds):
  - Pearson-based feature selector (top K=500) — per fold
  - LGB with custom objective (1 - CCC) gradient/hessian
  - init_score=mean(y_train) on each tree boosting round
  - Post-hoc affine calibration on training OOF (using a 5-fold inner loop):
    fit (a, b) such that y_pred ≈ a * pred + b on inner-OOF preds; apply to test pred.
  - Stage 1 (Ridge on H&Y + clinical) ON OR OFF — try both. Both as variants.

Comparator: iter5-direct-T1 (MSE Stage2) same fold/seed.
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
from run_t1_iter4 import load_pd_data as load_t1_pd_data

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA = 1.0
K_FEATURES = 500


def _load_t1_cohort():
    d = load_t1_pd_data()
    sids = np.asarray(d["sids"])
    X = np.asarray(d["X_v2"], dtype=np.float64)
    y = np.asarray(d["t1"], dtype=np.float64)
    hy = np.asarray(d["hy"], dtype=np.float64)
    valid = ~np.isnan(y)
    return sids[valid], X[valid], y[valid], hy[valid]


def _kfold(n: int, seed: int):
    return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))


def _ccc_objective_factory(y_mean: float):
    """Return (grad, hess) callable for LightGBM custom objective minimising 1-CCC.

    CCC(y, p) = 2 * cov(y, p) / (var(y) + var(p) + (mean(y) - mean(p))^2)
    Minimise L = 1 - CCC. Gradient and Hessian computed analytically per sample,
    with hessian=1.0 scaling per F50 v2 (the analytical hessian is too small to
    drive learning at small N; constant hessian regularises like MSE).
    """
    def obj(preds, train_set):
        # LightGBM passes (preds, train_set) where train_set is a Dataset.
        y = train_set.get_label()
        p = np.asarray(preds, dtype=np.float64)
        my = float(np.mean(y))
        mp = float(np.mean(p))
        vy = float(np.var(y))
        vp = float(np.var(p))
        cov = float(np.mean((y - my) * (p - mp)))
        denom = vy + vp + (my - mp) ** 2 + 1e-9
        # ∂L/∂p_i ≈ −[2*(y_i - my)/denom − 2*cov*(2*(p_i - mp)/n + 2*(mp - my)/n)/denom^2]
        n = len(y)
        d_cov_dp = (y - my) / n  # shape (n,)
        d_var_dp = 2 * (p - mp) / n
        d_mp_dp = 1.0 / n
        d_denom_dp = d_var_dp + 2 * (mp - my) * d_mp_dp
        grad_ccc = (2 * d_cov_dp * denom - 2 * cov * d_denom_dp) / (denom ** 2)
        grad = -grad_ccc  # we minimise 1 - CCC
        hess = np.ones_like(grad)  # F50 v2 fix: constant hessian
        return grad, hess

    return obj


def _pearson_topk(X_tr, y_tr, X_te, k: int):
    """Top-K Pearson |r| selector on X_tr columns vs y_tr."""
    n, p = X_tr.shape
    if p <= k:
        return X_tr, X_te
    y_c = y_tr - y_tr.mean()
    Xc = X_tr - X_tr.mean(axis=0, keepdims=True)
    num = (Xc * y_c.reshape(-1, 1)).sum(axis=0)
    denom = np.sqrt((Xc ** 2).sum(axis=0) * (y_c ** 2).sum() + 1e-12)
    rs = np.abs(num / denom)
    sel = np.argsort(-rs)[:k]
    return X_tr[:, sel], X_te[:, sel]


def _train_ccc_lgb(X_tr, y_tr, X_te, seed: int):
    import lightgbm as lgb

    y_mean = float(np.mean(y_tr))
    obj = _ccc_objective_factory(y_mean)
    init_score = np.full(len(y_tr), y_mean, dtype=np.float64)
    train_set = lgb.Dataset(X_tr, label=y_tr, init_score=init_score)
    params = {
        "objective": obj, "metric": "None", "learning_rate": 0.05,
        "num_leaves": 15, "min_data_in_leaf": 10, "verbose": -1,
        "seed": seed, "deterministic": True, "feature_fraction": 0.9,
    }
    booster = lgb.train(params, train_set, num_boost_round=400)
    raw_te = booster.predict(X_te)
    return raw_te + y_mean  # add init_score back


def _affine_calibrate(pred_te, X_tr, y_tr, seed: int):
    """Inner 5-fold OOF + LinearRegression on (oof_pred, y_tr) → apply to pred_te."""
    n = len(y_tr)
    oof = np.zeros(n)
    for tr_in, te_in in _kfold(n, seed=seed + 7777):
        Xtr_in, Xte_in = _pearson_topk(X_tr[tr_in], y_tr[tr_in], X_tr[te_in], k=K_FEATURES)
        oof[te_in] = _train_ccc_lgb(Xtr_in, y_tr[tr_in], Xte_in, seed)
    lr = LinearRegression().fit(oof.reshape(-1, 1), y_tr)
    return lr.predict(pred_te.reshape(-1, 1))


def run_one_seed_ccc_direct(
    seed: int, feature_set: str = "A3_tier1", use_stage1: bool = True
) -> tuple[np.ndarray, np.ndarray]:
    sids, X, y, hy = _load_t1_cohort()
    n = len(sids)
    if use_stage1:
        clinical = load_clinical_dict(sids)
        X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed):
        if use_stage1:
            s1_tr, s1_te = fit_stage1(X_s1[tr], y[tr], X_s1[te], alpha=STAGE1_ALPHA)
            target_tr = y[tr] - s1_tr
        else:
            s1_te = np.zeros(len(te))
            target_tr = y[tr] - float(np.mean(y[tr]))
            s1_offset = float(np.mean(y[tr]))
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel = _pearson_topk(Xtr, target_tr, Xte, k=K_FEATURES)
        s2_te_raw = _train_ccc_lgb(Xtr_sel, target_tr, Xte_sel, seed)
        # Affine-calibrate s2 onto target-tr scale (inner OOF)
        s2_te_cal = _affine_calibrate(s2_te_raw, Xtr_sel, target_tr, seed)
        if use_stage1:
            preds[te] = s1_te + s2_te_cal
        else:
            preds[te] = s1_offset + s2_te_cal
    return y, preds


def run_one_seed_iter5_baseline(
    seed: int, feature_set: str = "A3_tier1"
) -> tuple[np.ndarray, np.ndarray]:
    sids, X, y, hy = _load_t1_cohort()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n)
    for tr, te in _kfold(n, seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y[tr], X_s1[te], alpha=STAGE1_ALPHA)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr, y[tr] - s1_tr, Xte, k=K_FEATURES, seed=seed
        )
        preds[te] = s1_te + train_lgb(Xtr_sel, y[tr] - s1_tr, Xte_sel, seed)
    return y, preds


def run_screen(seeds: tuple[int, ...], feature_set: str) -> Path:
    print(
        f"\n=== T1 iter29-C SCREEN: CCC-direct LGB (F50 v2 fixes) on T1 (5-fold, "
        f"feature_set={feature_set}, {len(seeds)} seeds) ===\n",
        flush=True,
    )
    rows = []
    oof_dict = {}
    for variant_label, use_s1 in [("with_stage1", True), ("no_stage1", False)]:
        for seed in seeds:
            t0 = time.time()
            y_t1, preds_cc = run_one_seed_ccc_direct(seed, feature_set, use_stage1=use_s1)
            wall_cc = time.time() - t0
            y2, preds_i5 = run_one_seed_iter5_baseline(seed, feature_set)
            assert np.allclose(y_t1, y2)
            c_cc = float(ccc_fn(y_t1, preds_cc))
            c_i5 = float(ccc_fn(y_t1, preds_i5))
            rows.append({
                "variant": variant_label, "seed": seed,
                "ccc_ccc_direct": round(c_cc, 4), "ccc_iter5_direct": round(c_i5, 4),
                "delta": round(c_cc - c_i5, 4),
                "mae_ccc_direct": round(float(mae_fn(y_t1, preds_cc)), 3),
                "r_ccc_direct": round(float(pearson_r(y_t1, preds_cc)), 4),
                "wall_time_s": round(wall_cc, 1),
            })
            oof_dict[f"{variant_label}_seed{seed}_pred"] = preds_cc.tolist()
            oof_dict[f"{variant_label}_seed{seed}_iter5"] = preds_i5.tolist()
            oof_dict[f"{variant_label}_seed{seed}_y"] = y_t1.tolist()
            print(
                f"  variant={variant_label} seed={seed}: ccc-direct CCC={c_cc:.4f} | "
                f"iter5-direct CCC={c_i5:.4f} | Δ={c_cc-c_i5:+.4f} | "
                f"MAE={rows[-1]['mae_ccc_direct']:.3f} | "
                f"r={rows[-1]['r_ccc_direct']:.4f} | {wall_cc:.1f}s",
                flush=True,
            )

    df = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter29c_ccc_direct_5fold_{ts}.csv"
    df.to_csv(out, index=False)

    import json as _json
    out_oof = RESULTS_DIR / f"iter29c_ccc_direct_5fold_{ts}.oof.json"
    with open(out_oof, "w") as f:
        _json.dump(oof_dict, f)

    for v in df["variant"].unique():
        sub = df[df["variant"] == v]
        print(
            f"\n[{v}] Mean ccc-direct CCC = {sub['ccc_ccc_direct'].mean():.4f} ± "
            f"{sub['ccc_ccc_direct'].std():.4f}; Mean iter5-direct CCC = "
            f"{sub['ccc_iter5_direct'].mean():.4f} ± {sub['ccc_iter5_direct'].std():.4f}; "
            f"Δ̄ = {sub['delta'].mean():+.4f}",
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
