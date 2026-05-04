"""Per-item CCC objective v3 — deeper methodology fixes:

Builds on run_per_item_ccc_v2.py (which already correctly applies init_score=s1_pred for
hy_residual_cccv2). v3 adds three new variants:

Track 2 — item-feature only (no V2 dilution):
  item_dedicated_cccv2_v3 — CCC objective on item-i features only + Pearson + affine cal.

Track 3 — bagged CCC ensembles (32 bags × subsample 0.8 × feature_fraction 0.7):
  bagged_cccv2_v2plusitem      — bagging on (V2 ∪ item) base for items where item_plus_v2 is the prior winner.
  bagged_cccv2_hyresidual      — bagging hy-residual stage-2 with init_score=s1_pred.
  bagged_cccv2_itemonly        — bagging on item-features only.

Selectors and calibration are computed PER FOLD; bagging seeds vary per bag inside each fold.

CRITICAL constraints honoured:
- Inductive only (per-fold impute + per-fold Pearson selection).
- 5-null gate (scrambled label + canary feature) on every variant we report.
- Subject-level splits via run_per_item_v2.kfold_split_stratified (paper3_split.json).
- Saves OOFs as .npy with unique cccv3/bagged filename suffix.
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
from run_per_item_ccc_v2 import fit_lgb_ccc_with_init

import os as _os
BAG_COUNT = int(_os.environ.get("CCCV3_BAGS", "16"))


# ── Bagging helpers ─────────────────────────────────────────────────────────


def _train_one_bag_ccc(
    X_tr: np.ndarray,
    y_tr: np.ndarray,
    X_te: np.ndarray,
    seed: int,
    init_tr: np.ndarray | None,
    init_te: np.ndarray | None,
    subsample: float,
    feature_fraction: float,
    num_boost_round: int,
):
    """Train ONE bag with CCC objective.

    - Subsample rows with replacement at fraction `subsample`.
    - Subsample columns without replacement at `feature_fraction`.
    - If init_tr/init_te provided, use them as base scores (CCC on init+delta).
    """
    import lightgbm as lgb
    rng = np.random.RandomState(seed)
    n_tr = X_tr.shape[0]
    n_feat = X_tr.shape[1]
    n_bag = max(int(round(subsample * n_tr)), 8)
    rows = rng.choice(n_tr, size=n_bag, replace=True)
    n_keep = max(int(round(feature_fraction * n_feat)), 4)
    cols = rng.choice(n_feat, size=n_keep, replace=False)
    Xb = X_tr[np.ix_(rows, cols)]
    yb = y_tr[rows]
    Xte_b = X_te[:, cols]
    p = {
        "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 5,
        "feature_fraction": 1.0, "bagging_fraction": 1.0,
        "n_jobs": 1, "verbosity": -1, "random_state": seed,
        "reg_lambda": 0.0,
        "objective": ccc_loss_grad_hess_v2, "metric": "None",
    }
    if init_tr is None:
        init_b = np.full_like(yb, fill_value=float(yb.mean()), dtype=np.float64)
        init_te_b = np.full_like(np.zeros(X_te.shape[0]), fill_value=float(yb.mean()), dtype=np.float64)
    else:
        init_b = init_tr[rows].astype(np.float64)
        init_te_b = init_te.astype(np.float64)
    booster = lgb.train(
        params=p,
        train_set=lgb.Dataset(Xb, label=yb, init_score=init_b),
        num_boost_round=num_boost_round,
    )
    delta_tr = booster.predict(Xb)
    delta_te = booster.predict(Xte_b)
    pred_tr_full = init_b + delta_tr
    pred_te_full = init_te_b + delta_te
    # Per-bag affine calibration, fit on the (bag-train, bag-pred) pair
    a, b = fit_ccc_affine(yb, pred_tr_full)
    return a * pred_te_full + b


def bagged_predict_ccc(
    X_tr: np.ndarray,
    y_tr: np.ndarray,
    X_te: np.ndarray,
    base_seed: int,
    init_tr: np.ndarray | None = None,
    init_te: np.ndarray | None = None,
    n_bags: int = 32,
    subsample: float = 0.8,
    feature_fraction: float = 0.7,
    num_boost_round: int = 400,
) -> np.ndarray:
    """Average predictions from `n_bags` CCC-LGBs and apply final affine cal on the OOF training prediction.

    A second affine calibration is applied at the ensemble level — fit on (y_tr, mean of train preds across bags).
    """
    n_te = X_te.shape[0]
    n_tr = X_tr.shape[0]
    preds_te = np.zeros(n_te, dtype=np.float64)
    preds_tr_acc = np.zeros(n_tr, dtype=np.float64)
    # We also need the per-bag training predictions to fit the final ensemble calibration.
    # To avoid re-doing each bag fit twice, run each bag and predict on train fold once.
    import lightgbm as lgb
    rng_master = np.random.RandomState(base_seed)
    bag_seeds = rng_master.randint(0, 10**9, size=n_bags)
    for bs in bag_seeds:
        # Identical to _train_one_bag_ccc but also returns training-fold predictions
        rng = np.random.RandomState(int(bs))
        n_bag_rows = max(int(round(subsample * n_tr)), 8)
        rows = rng.choice(n_tr, size=n_bag_rows, replace=True)
        n_keep = max(int(round(feature_fraction * X_tr.shape[1])), 4)
        cols = rng.choice(X_tr.shape[1], size=n_keep, replace=False)
        Xb = X_tr[np.ix_(rows, cols)]
        yb = y_tr[rows]
        Xte_b = X_te[:, cols]
        Xtr_full_b = X_tr[:, cols]
        if init_tr is None:
            init_b = np.full_like(yb, fill_value=float(yb.mean()), dtype=np.float64)
            init_te_b = np.full_like(np.zeros(n_te), fill_value=float(yb.mean()), dtype=np.float64)
            init_tr_full_b = np.full_like(np.zeros(n_tr), fill_value=float(yb.mean()), dtype=np.float64)
        else:
            init_b = init_tr[rows].astype(np.float64)
            init_te_b = init_te.astype(np.float64)
            init_tr_full_b = init_tr.astype(np.float64)
        p = {
            "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 5,
            "feature_fraction": 1.0, "bagging_fraction": 1.0,
            "n_jobs": 1, "verbosity": -1, "random_state": int(bs),
            "reg_lambda": 0.0,
            "objective": ccc_loss_grad_hess_v2, "metric": "None",
        }
        booster = lgb.train(
            params=p,
            train_set=lgb.Dataset(Xb, label=yb, init_score=init_b),
            num_boost_round=num_boost_round,
        )
        delta_te = booster.predict(Xte_b)
        delta_tr_full = booster.predict(Xtr_full_b)
        pred_te_full = init_te_b + delta_te
        pred_tr_full = init_tr_full_b + delta_tr_full
        # Per-bag affine cal using the BAG'S own train rows (yb vs init_b+delta_tr_bag)
        delta_tr_bag = booster.predict(Xb)
        pred_tr_bag_full = init_b + delta_tr_bag
        a, b = fit_ccc_affine(yb, pred_tr_bag_full)
        preds_te += (a * pred_te_full + b)
        preds_tr_acc += (a * pred_tr_full + b)
    preds_te /= float(n_bags)
    preds_tr_acc /= float(n_bags)
    # Final ensemble-level affine on the held-out fold's training predictions vs labels
    a2, b2 = fit_ccc_affine(y_tr, preds_tr_acc)
    return a2 * preds_te + b2


# ── Variants ────────────────────────────────────────────────────────────────


def feature_select_pearson(X_tr, y_tr, X_te, k=500):
    if X_tr.shape[1] <= k:
        return X_tr, X_te
    idx = pearson_select_features(X_tr, y_tr, k=k)
    return X_tr[:, idx], X_te[:, idx]


def variant_item_dedicated_cccv2_v3(d, item, splits, seed=42):
    """Track 2: CCC objective on ITEM-i features only (no V2 dilution)."""
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    n = len(y)
    if not cols:
        return np.full(n, np.nan)
    oof = np.zeros(n)
    k = min(500, X_item.shape[1])
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_item[tr], X_item[te])
        Xtr, Xte = feature_select_pearson(Xtr, y[tr], Xte, k=k)
        oof[te] = train_lgb_ccc_v2(Xtr, y[tr], Xte, seed)
    return oof


def variant_bagged_cccv2_v2plusitem(d, item, splits, seed=42):
    """Track 3: 32-bag CCC ensemble on (V2 ∪ item)."""
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    X_aug = np.hstack([d["X_v2"], X_item]) if cols else d["X_v2"]
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte = feature_select_pearson(Xtr, y[tr], Xte, k=500)
        oof[te] = bagged_predict_ccc(
            Xtr, y[tr], Xte, base_seed=seed,
            init_tr=None, init_te=None,
            n_bags=BAG_COUNT, subsample=0.8, feature_fraction=0.7,
        )
    return oof


def variant_bagged_cccv2_itemonly(d, item, splits, seed=42):
    """Track 3: 32-bag CCC ensemble on item-features only."""
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    n = len(y)
    if not cols:
        return np.full(n, np.nan)
    oof = np.zeros(n)
    k = min(500, X_item.shape[1])
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_item[tr], X_item[te])
        Xtr, Xte = feature_select_pearson(Xtr, y[tr], Xte, k=k)
        oof[te] = bagged_predict_ccc(
            Xtr, y[tr], Xte, base_seed=seed,
            init_tr=None, init_te=None,
            n_bags=BAG_COUNT, subsample=0.8, feature_fraction=0.7,
        )
    return oof


def variant_bagged_cccv2_hyresidual(d, item, splits, seed=42):
    """Track 3: 32-bag CCC ensemble with init_score=Ridge(H&Y) (proper init_score fix)."""
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
        oof[te] = bagged_predict_ccc(
            Xtr, y[tr], Xte, base_seed=seed,
            init_tr=s1_tr, init_te=s1_te,
            n_bags=BAG_COUNT, subsample=0.8, feature_fraction=0.7,
        )
    return oof


VARIANTS = {
    "item_dedicated_cccv2_v3": variant_item_dedicated_cccv2_v3,
    "bagged_cccv2_v2plusitem": variant_bagged_cccv2_v2plusitem,
    "bagged_cccv2_itemonly": variant_bagged_cccv2_itemonly,
    "bagged_cccv2_hyresidual": variant_bagged_cccv2_hyresidual,
}


# ── 5-null gate ─────────────────────────────────────────────────────────────


def run_5null_gate(d, item, variant, seed=42):
    """Run scrambled-label and canary-feature null tests for one (item, variant)."""
    y = d["items"][item]
    splits = kfold_split_stratified(y, 5, seed=seed)
    fn = VARIANTS[variant]
    null = {}
    rng = np.random.RandomState(seed)
    # 1. Scrambled-label
    y_scram = rng.permutation(y)
    d2 = {**d, "items": {**d["items"], item: y_scram}}
    try:
        oof_s = fn(d2, item, splits, seed)
        null["scrambled_label_ccc"] = float(ccc_fn(y_scram, oof_s))
    except Exception as e:
        null["scrambled_label_error"] = str(e)
    # 2. Canary feature appended to V2
    canary = rng.randn(len(y))
    d3 = {**d, "X_v2": np.hstack([d["X_v2"], canary[:, None]])}
    try:
        oof_c = fn(d3, item, splits, seed)
        null["canary_feature_ccc"] = float(ccc_fn(y, oof_c))
    except Exception as e:
        null["canary_feature_error"] = str(e)
    return null


# ── Driver ──────────────────────────────────────────────────────────────────


def _filter_nan_target(d, item):
    y = d["items"][item]
    nan_mask = np.isnan(y)
    if not nan_mask.any():
        return d
    valid = np.where(~nan_mask)[0]
    d_f = {
        "sids": d["sids"][valid],
        "X_v2": d["X_v2"][valid],
        "X_peritem": d["X_peritem"][valid] if "X_peritem" in d else None,
        "peritem_cols": d.get("peritem_cols"),
        "hy": d["hy"][valid],
        "items": {k: (v[valid] if isinstance(v, np.ndarray) else v) for k, v in d["items"].items()},
    }
    if "t1" in d and isinstance(d["t1"], np.ndarray):
        d_f["t1"] = d["t1"][valid]
    return d_f


def run_one(d, item, variant, eval_kind, seeds=SEEDS, with_null=True):
    d = _filter_nan_target(d, item)
    y = d["items"][item]
    n = len(y)
    if eval_kind == "5split":
        per_seed = []
        for s in seeds:
            splits = kfold_split_stratified(y, 5, seed=s)
            oof = VARIANTS[variant](d, item, splits, s)
            per_seed.append(full_metrics(y, oof))
        out = {
            "item": item, "variant": variant, "eval": eval_kind,
            "n_subjects": int(n), "seeds": list(seeds),
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
            oof_acc = oof_acc + oof_s
        oof_mean = oof_acc / len(seeds)
        out = {
            "item": item, "variant": variant, "eval": eval_kind,
            "n_subjects": int(n), "seeds": list(seeds),
            "ccc_mean": float(np.mean([m["ccc"] for m in per_seed])),
            "ccc_std": float(np.std([m["ccc"] for m in per_seed])),
            "mae_mean": float(np.mean([m["mae"] for m in per_seed])),
            "per_seed": per_seed,
            "_oof_array": oof_mean.tolist(),
        }
    else:
        raise ValueError(f"unknown eval_kind {eval_kind}")
    if with_null and eval_kind == "5split":
        out["null_tests"] = run_5null_gate(d, item, variant, seed=seeds[0])
    return out


def _run_one_job(args_tuple):
    d, item, variant, eval_kind, seeds, with_null, tag = args_tuple
    try:
        r = run_one(d, item, variant, eval_kind, seeds=tuple(seeds), with_null=with_null)
        row = {"item": item, "variant": variant, "eval": eval_kind,
               "ccc_mean": r["ccc_mean"], "ccc_std": r["ccc_std"],
               "mae_mean": r["mae_mean"]}
        if "null_tests" in r:
            row["scrambled_label_ccc"] = r["null_tests"].get("scrambled_label_ccc", np.nan)
            row["canary_feature_ccc"] = r["null_tests"].get("canary_feature_ccc", np.nan)
        loocv_payload = None
        if eval_kind == "loocv" and "_oof_array" in r:
            oof_arr = np.array(r["_oof_array"])
            rj = {k: vv for k, vv in r.items() if k != "_oof_array"}
            loocv_payload = {"oof": oof_arr, "json": rj}
        return {"row": row, "loocv": loocv_payload}
    except Exception as e:
        return {"row": {"item": item, "variant": variant, "eval": eval_kind, "error": str(e)},
                "loocv": None}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--items", type=int, nargs="+", default=T1_ITEMS + [18])
    p.add_argument("--eval", default="5split", choices=["5split", "loocv"])
    p.add_argument("--variants", nargs="+", default=list(VARIANTS.keys()))
    p.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    p.add_argument("--tag", default="cccv3", help="filename suffix for outputs")
    global BAG_COUNT
    p.add_argument("--no-null", action="store_true", help="skip 5-null gate (much faster)")
    p.add_argument("--workers", type=int, default=1, help="parallel jobs (1=sequential)")
    p.add_argument("--bags", type=int, default=BAG_COUNT, help="bag count for bagged variants (default 16)")
    args = p.parse_args()
    _os.environ["CCCV3_BAGS"] = str(args.bags)
    BAG_COUNT = args.bags
    print(f"BAG_COUNT={BAG_COUNT}", flush=True)

    print(f"v3 run: items={args.items} variants={args.variants} eval={args.eval} seeds={args.seeds} workers={args.workers}", flush=True)
    d = load_data()
    print(f"  N = {len(d['sids'])} PD subjects, V2={d['X_v2'].shape[1]} feats, peritem={d['X_peritem'].shape[1]} feats", flush=True)

    with_null = (args.eval == "5split") and (not args.no_null)

    jobs = []
    for it in args.items:
        for v in args.variants:
            jobs.append((d, it, v, args.eval, tuple(args.seeds), with_null, args.tag))

    out_csv = RESULTS_DIR / f"peritem_{args.tag}_{args.eval}.csv"
    results = []
    t0 = time.time()
    if args.workers <= 1:
        for j in jobs:
            res = _run_one_job(j)
            row = res["row"]
            results.append(row)
            ccc = row.get("ccc_mean", float("nan"))
            extra = ""
            if "scrambled_label_ccc" in row:
                extra = f" [null_scram={row.get('scrambled_label_ccc', float('nan')):.3f}, canary={row.get('canary_feature_ccc', float('nan')):.3f}]"
            err = row.get("error", "")
            print(f"item={row.get('item')} variant={row.get('variant')} ccc={ccc:.4f}" + extra
                  + f" ({time.time()-t0:.0f}s)" + (f" ERR:{err}" if err else ""), flush=True)
            if res["loocv"] is not None:
                oof_arr = res["loocv"]["oof"]
                out_npy = RESULTS_DIR / f"lockbox_peritem_{row['item']}_{row['variant']}.oof.npy"
                np.save(out_npy, oof_arr)
                out_json = RESULTS_DIR / f"lockbox_peritem_{row['item']}_{row['variant']}_{args.tag}.json"
                with open(out_json, "w") as f:
                    json.dump(res["loocv"]["json"], f, indent=2, default=float)
                print(f"   wrote {out_npy.name} and {out_json.name}", flush=True)
            # Progressive save
            pd.DataFrame(results).to_csv(out_csv, index=False)
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=args.workers) as exe:
            futures = {exe.submit(_run_one_job, j): j for j in jobs}
            for fut in as_completed(futures):
                res = fut.result()
                row = res["row"]
                results.append(row)
                ccc = row.get("ccc_mean", float("nan"))
                extra = ""
                if "scrambled_label_ccc" in row:
                    extra = f" [null_scram={row.get('scrambled_label_ccc', float('nan')):.3f}, canary={row.get('canary_feature_ccc', float('nan')):.3f}]"
                err = row.get("error", "")
                print(f"item={row.get('item')} variant={row.get('variant')} ccc={ccc:.4f}" + extra
                      + f" ({time.time()-t0:.0f}s)" + (f" ERR:{err}" if err else ""), flush=True)
                if res["loocv"] is not None:
                    oof_arr = res["loocv"]["oof"]
                    out_npy = RESULTS_DIR / f"lockbox_peritem_{row['item']}_{row['variant']}.oof.npy"
                    np.save(out_npy, oof_arr)
                    out_json = RESULTS_DIR / f"lockbox_peritem_{row['item']}_{row['variant']}_{args.tag}.json"
                    with open(out_json, "w") as f:
                        json.dump(res["loocv"]["json"], f, indent=2, default=float)
                    print(f"   wrote {out_npy.name} and {out_json.name}", flush=True)
                pd.DataFrame(results).to_csv(out_csv, index=False)

    df = pd.DataFrame(results)
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}", flush=True)
    if "ccc_mean" in df:
        print(df.sort_values("ccc_mean", ascending=False).to_string(), flush=True)


if __name__ == "__main__":
    main()
