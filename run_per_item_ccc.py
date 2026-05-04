"""Run CCC-objective LGB variants per item (non-conflicting with agents)."""
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
    load_data, kfold_split_stratified, impute_fold, feature_select_fold,
    get_item_features, get_hy_features, SEEDS, T1_ITEMS,
)
from lgb_ccc_objective import train_lgb_ccc


def variant_v2_baseline_ccc(d, item, splits, seed=42):
    y = d["items"][item]
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb_ccc(Xtr, y[tr], Xte, seed)
    return oof


def variant_item_plus_v2_ccc(d, item, splits, seed=42):
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    if not cols:
        return variant_v2_baseline_ccc(d, item, splits, seed)
    X_aug = np.hstack([d["X_v2"], X_item])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb_ccc(Xtr, y[tr], Xte, seed)
    return oof


def variant_hy_residual_ccc(d, item, splits, seed=42):
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
        resid_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        s2_te = train_lgb_ccc(Xtr, resid_tr, Xte, seed)
        oof[te] = s1_te + s2_te
    return oof


VARIANTS = {
    "v2_baseline_ccc": variant_v2_baseline_ccc,
    "item_plus_v2_ccc": variant_item_plus_v2_ccc,
    "hy_residual_ccc": variant_hy_residual_ccc,
}


def run_one(d, item, variant, eval_kind, seeds=SEEDS):
    y = d["items"][item]
    nan_mask = np.isnan(y)
    if nan_mask.any():
        valid = np.where(~nan_mask)[0]
        d_f = {**d}
        d_f["sids"] = d["sids"][valid]
        d_f["X_v2"] = d["X_v2"][valid]
        d_f["X_peritem"] = d["X_peritem"][valid] if "X_peritem" in d else None
        d_f["hy"] = d["hy"][valid]
        d_f["items"] = {k: (v[valid] if isinstance(v, np.ndarray) else v) for k, v in d["items"].items()}
        d_f["t1"] = d["t1"][valid] if "t1" in d else None
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
            "per_seed": per_seed,
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
            "per_seed": per_seed,
            "_oof_array": oof_mean.tolist(),
        }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--items", type=int, nargs="+", default=T1_ITEMS)
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
                # Save OOF for loocv
                if args.eval == "loocv" and "_oof_array" in r:
                    oof = np.array(r["_oof_array"])
                    out = RESULTS_DIR / f"lockbox_peritem_{it}_{v}_ccc.oof.npy"
                    np.save(out, oof)
            except Exception as e:
                print(f"item={it} variant={v} FAIL: {e}", flush=True)
    df = pd.DataFrame(results)
    out_csv = RESULTS_DIR / f"peritem_ccc_{args.eval}.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}")
    print(df.sort_values("ccc_mean", ascending=False).to_string())


if __name__ == "__main__":
    main()
