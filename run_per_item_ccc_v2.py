"""Per-item CCC objective v2 — incorporates codex+gemini debug fixes:

1. Pearson-correlation feature selection (replaces MSE selector).
2. init_score = train mean for LGB (avoids 0.0 init).
3. Hessian = 1.0 scaling (matches MSE GBDT regularization).
4. Post-hoc affine calibration on inner-fold OOF.
5. hy_residual_ccc rewritten: LGB with init_score=ridge_pred, target=y (CCC on base+delta vs original y).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR
from run_per_item_v2 import (
    load_data, kfold_split_stratified, impute_fold,
    get_item_features, get_hy_features, SEEDS, T1_ITEMS,
)
from lgb_ccc_objective_v2 import (
    ccc_loss_grad_hess_v2, pearson_select_features, fit_ccc_affine, train_lgb_ccc_v2,
)


def fit_lgb_ccc_with_init(X_tr, y_tr, X_te, init_tr, init_te, seed: int,
                          calibrate: bool = True) -> np.ndarray:
    """LGB with custom init_score (e.g., ridge prediction) + CCC objective.

    Returns predictions on X_te = init_te + lgb_delta_te (+ affine cal if requested).
    """
    import lightgbm as lgb
    p = {
        "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 5,
        "feature_fraction": 1.0, "bagging_fraction": 1.0,
        "n_jobs": 2, "verbosity": -1, "random_state": seed,
        "reg_lambda": 0.0,
        "objective": ccc_loss_grad_hess_v2, "metric": "None",
    }
    booster = lgb.train(
        params=p,
        train_set=lgb.Dataset(X_tr, label=y_tr, init_score=np.asarray(init_tr, dtype=np.float64)),
        num_boost_round=400,
    )
    delta_tr = booster.predict(X_tr)
    delta_te = booster.predict(X_te)
    pred_tr_full = init_tr + delta_tr
    pred_te_full = init_te + delta_te
    if calibrate:
        a, b = fit_ccc_affine(y_tr, pred_tr_full)
        pred_te_full = a * pred_te_full + b
    return pred_te_full


def feature_select_pearson(X_tr, y_tr, X_te, k=500):
    if X_tr.shape[1] <= k:
        return X_tr, X_te
    idx = pearson_select_features(X_tr, y_tr, k=k)
    return X_tr[:, idx], X_te[:, idx]


def variant_v2_baseline_cccv2(d, item, splits, seed=42):
    y = d["items"][item]
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr, Xte = feature_select_pearson(Xtr, y[tr], Xte, k=500)
        oof[te] = train_lgb_ccc_v2(Xtr, y[tr], Xte, seed)
    return oof


def variant_item_plus_v2_cccv2(d, item, splits, seed=42):
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    if not cols:
        return variant_v2_baseline_cccv2(d, item, splits, seed)
    X_aug = np.hstack([d["X_v2"], X_item])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte = feature_select_pearson(Xtr, y[tr], Xte, k=500)
        oof[te] = train_lgb_ccc_v2(Xtr, y[tr], Xte, seed)
    return oof


def variant_hy_residual_cccv2(d, item, splits, seed=42):
    """Stage-1 Ridge(H&Y) gives init_score; Stage-2 LGB with CCC on (init+delta) vs original y."""
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
    X_item, cols = get_item_features(d, item)
    X_aug = np.hstack([d["X_v2"], X_item]) if cols else d["X_v2"]
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], y[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte = feature_select_pearson(Xtr, y[tr], Xte, k=500)
        oof[te] = fit_lgb_ccc_with_init(
            Xtr, y[tr], Xte, init_tr=s1_tr, init_te=s1_te, seed=seed, calibrate=True
        )
    return oof


VARIANTS = {
    "v2_baseline_cccv2": variant_v2_baseline_cccv2,
    "item_plus_v2_cccv2": variant_item_plus_v2_cccv2,
    "hy_residual_cccv2": variant_hy_residual_cccv2,
}


def run_one(d, item, variant, eval_kind, seeds=SEEDS):
    y = d["items"][item]
    nan_mask = np.isnan(y)
    if nan_mask.any():
        valid = np.where(~nan_mask)[0]
        d_f = {k: (v[valid] if isinstance(v, np.ndarray) and len(v) == len(d["sids"]) else v)
               for k, v in d.items()}
        d_f["sids"] = d["sids"][valid]
        d_f["X_v2"] = d["X_v2"][valid]
        d_f["X_peritem"] = d["X_peritem"][valid] if "X_peritem" in d else None
        d_f["hy"] = d["hy"][valid]
        d_f["items"] = {k: (v[valid] if isinstance(v, np.ndarray) else v) for k, v in d["items"].items()}
        if "t1" in d:
            d_f["t1"] = d["t1"][valid]
        d = d_f
        y = d["items"][item]
    n = len(y)
    if eval_kind == "5split":
        per_seed = []
        for s in seeds:
            splits = kfold_split_stratified(y, 5, seed=s)
            oof = VARIANTS[variant](d, item, splits, s)
            per_seed.append(full_metrics(y, oof))
        return {
            "item": item, "variant": variant, "eval": eval_kind,
            "ccc_mean": float(np.mean([m["ccc"] for m in per_seed])),
            "ccc_std": float(np.std([m["ccc"] for m in per_seed])),
            "mae_mean": float(np.mean([m["mae"] for m in per_seed])),
        }
    elif eval_kind == "loocv":
        splits = [(np.array([j for j in range(n) if j != i]), np.array([i])) for i in range(n)]
        per_seed = []
        oof_acc = np.zeros(n)
        for s in seeds:
            oof_s = VARIANTS[variant](d, item, splits, s)
            per_seed.append(full_metrics(y, oof_s))
            oof_acc += oof_s
        oof_mean = oof_acc / len(seeds)
        return {
            "item": item, "variant": variant, "eval": eval_kind,
            "ccc_mean": float(np.mean([m["ccc"] for m in per_seed])),
            "ccc_std": float(np.std([m["ccc"] for m in per_seed])),
            "mae_mean": float(np.mean([m["mae"] for m in per_seed])),
            "_oof_array": oof_mean.tolist(),
        }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--items", type=int, nargs="+", default=T1_ITEMS + [18])
    p.add_argument("--eval", default="5split", choices=["5split", "loocv"])
    p.add_argument("--variants", nargs="+", default=list(VARIANTS.keys()))
    args = p.parse_args()

    d = load_data()
    results = []
    t0 = time.time()
    for it in args.items:
        for v in args.variants:
            try:
                r = run_one(d, it, v, args.eval)
                results.append({"item": it, "variant": v, "eval": args.eval,
                                "ccc_mean": r["ccc_mean"], "ccc_std": r["ccc_std"],
                                "mae_mean": r["mae_mean"]})
                print(f"item={it} variant={v} ccc={r['ccc_mean']:.4f} ± {r['ccc_std']:.4f} ({time.time()-t0:.0f}s)", flush=True)
                if args.eval == "loocv" and "_oof_array" in r:
                    oof = np.array(r["_oof_array"])
                    out = RESULTS_DIR / f"lockbox_peritem_{it}_{v}.oof.npy"
                    np.save(out, oof)
                    out_json = RESULTS_DIR / f"lockbox_peritem_{it}_{v}_cccv2.json"
                    rj = {k: v for k, v in r.items() if k != "_oof_array"}
                    with open(out_json, "w") as f:
                        json.dump(rj, f, indent=2, default=float)
            except Exception as e:
                print(f"item={it} variant={v} FAIL: {e}", flush=True)
    df = pd.DataFrame(results)
    out_csv = RESULTS_DIR / f"peritem_cccv2_{args.eval}.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}")
    print(df.sort_values("ccc_mean", ascending=False).to_string())


if __name__ == "__main__":
    main()
