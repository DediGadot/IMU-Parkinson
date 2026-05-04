"""Iter 11B: extend self-norm × hy_residual × per-item-features cross.

New variants probed (items 9, 11, 14, 18):
  self_norm_hy_residual_item        : Stage-1 Ridge(H&Y) → init; Stage-2 LGB MSE-on-residual
                                      on (V2 ∪ self-norm ∪ per-item features).
  self_norm_hy_residual_cccv2_item  : Stage-1 Ridge(H&Y) → init_score; Stage-2 LGB-CCC
                                      on (V2 ∪ self-norm ∪ per-item features), affine cal.
  self_norm_hurdle_fog              : Item 11 only — binary classifier (any-FoG) on V2 ∪ self-norm,
                                      then LGB regressor on positives, fused.

Inductive firewall: per-fold Pearson selector (K=500 — same as iter11), fold-local impute,
self-norm cache is target-agnostic.

Null gates: scrambled-label, canary-feature, sid-shuffle on self-norm cache.

Outputs:
  results/iter11b_<eval>_<tag>.csv
  results/iter11b_<item>_<variant>_<eval>_<tag>.{json,oof.npy}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    kfold_split_stratified, impute_fold,
    train_lgb, get_hy_features, SEEDS,
)
from run_per_item_v2 import get_item_features
from run_self_norm_cross import load_data, feature_select_pearson_fold, _filter_nan
from lgb_ccc_objective_v2 import train_lgb_ccc_v2
from run_per_item_ccc_v2 import fit_lgb_ccc_with_init


# ── New variants ───────────────────────────────────────────────────────────


def variant_self_norm_hy_residual_item(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Stage-1 Ridge(H&Y) → init; Stage-2 LGB-MSE on residual using V2 ∪ self-norm ∪ item features."""
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
    X_item, cols = get_item_features(d, item)
    if cols:
        X_aug = np.hstack([d["X_v2"], d["X_selfnorm"], X_item])
    else:
        X_aug = np.hstack([d["X_v2"], d["X_selfnorm"]])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], y[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte = feature_select_pearson_fold(Xtr, resid_tr, Xte, k=500)
        s2_te = train_lgb(Xtr, resid_tr, Xte, seed)
        oof[te] = s1_te + s2_te
    return oof


def variant_self_norm_hy_residual_cccv2_item(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Stage-1 Ridge(H&Y) → init_score; Stage-2 LGB-CCC on V2 ∪ self-norm ∪ item, affine cal."""
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
    X_item, cols = get_item_features(d, item)
    if cols:
        X_aug = np.hstack([d["X_v2"], d["X_selfnorm"], X_item])
    else:
        X_aug = np.hstack([d["X_v2"], d["X_selfnorm"]])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], y[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte = feature_select_pearson_fold(Xtr, y[tr], Xte, k=500)
        oof[te] = fit_lgb_ccc_with_init(
            Xtr, y[tr], Xte, init_tr=s1_tr, init_te=s1_te, seed=seed, calibrate=True
        )
    return oof


def variant_self_norm_hurdle_fog(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Item 11 only — hurdle classifier+regressor on V2 ∪ self-norm features.

    Stage 1: LGB binary classifier (item > 0 vs == 0).
    Stage 2: LGB MSE regressor on positive train rows only.
    Fused as prob * regressor_pred (zero-inflated mean).
    """
    if item != 11:
        raise ValueError("self_norm_hurdle_fog only valid for item 11")
    y = d["items"][item]
    X_aug = np.hstack([d["X_v2"], d["X_selfnorm"]])
    n = len(y)
    oof = np.zeros(n)
    import lightgbm as lgb
    for tr, te in splits:
        bin_tr = (y[tr] > 0).astype(int)
        Xtr_full, Xte_full = impute_fold(X_aug[tr], X_aug[te])
        # No feature selection on stage 1 — let LGB choose. Match per_item_v2 hurdle pattern.
        clf = lgb.LGBMClassifier(
            n_estimators=200, learning_rate=0.05, num_leaves=15,
            min_data_in_leaf=5, n_jobs=2, random_state=seed, verbosity=-1,
        )
        clf.fit(Xtr_full, bin_tr)
        prob_te = clf.predict_proba(Xte_full)[:, 1]
        # Stage 2: regress severity on positive train rows
        pos_mask = bin_tr == 1
        if pos_mask.sum() < 5:
            oof[te] = prob_te * y[tr].mean()
            continue
        Xtr_pos = Xtr_full[pos_mask]
        y_tr_pos = y[tr][pos_mask]
        Xtr_pos_sel, Xte_sel = feature_select_pearson_fold(
            Xtr_pos, y_tr_pos, Xte_full, k=300
        )
        sev_te = train_lgb(Xtr_pos_sel, y_tr_pos, Xte_sel, seed)
        oof[te] = prob_te * sev_te
    return oof


VARIANTS = {
    "self_norm_hy_residual_item": variant_self_norm_hy_residual_item,
    "self_norm_hy_residual_cccv2_item": variant_self_norm_hy_residual_cccv2_item,
    "self_norm_hurdle_fog": variant_self_norm_hurdle_fog,
}


# ── Null gate (3 nulls) ────────────────────────────────────────────────────


def run_null_gate(d: dict, item: int, variant: str, seed: int = 42) -> dict:
    d_f, y = _filter_nan(d, item)
    splits = kfold_split_stratified(y, 5, seed=seed)
    fn = VARIANTS[variant]
    null = {}
    rng = np.random.RandomState(seed)

    # 1. Scrambled-label
    y_scram = rng.permutation(y).astype(np.float64)
    d2 = {**d_f, "items": {**d_f["items"], item: y_scram}}
    try:
        oof_s = fn(d2, item, splits, seed)
        null["scrambled_label_ccc"] = float(ccc_fn(y_scram, oof_s))
    except Exception as e:
        null["scrambled_label_error"] = str(e)

    # 2. Canary feature on V2
    canary = rng.randn(len(y))
    d3 = {**d_f, "X_v2": np.hstack([d_f["X_v2"], canary[:, None]])}
    try:
        oof_c = fn(d3, item, splits, seed)
        null["canary_feature_ccc"] = float(ccc_fn(y, oof_c))
    except Exception as e:
        null["canary_feature_error"] = str(e)

    # 3. SID-shuffle on self-norm cache → must collapse to ≈ V2-baseline
    perm = rng.permutation(len(y))
    d4 = {**d_f, "X_selfnorm": d_f["X_selfnorm"][perm]}
    try:
        oof_p = fn(d4, item, splits, seed)
        null["sid_shuffle_selfnorm_ccc"] = float(ccc_fn(y, oof_p))
    except Exception as e:
        null["sid_shuffle_selfnorm_error"] = str(e)

    return null


def run_one(d: dict, item: int, variant: str, eval_kind: str,
            seeds: tuple[int, ...] = tuple(SEEDS), with_null: bool = True) -> dict:
    d_f, y = _filter_nan(d, item)
    n = len(y)
    if eval_kind == "5split":
        per_seed = []
        oof_acc = np.zeros(n)
        for s in seeds:
            splits = kfold_split_stratified(y, 5, seed=s)
            oof = VARIANTS[variant](d_f, item, splits, s)
            per_seed.append(full_metrics(y, oof))
            oof_acc += oof
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
    elif eval_kind == "loocv":
        splits = [(np.array([j for j in range(n) if j != i]), np.array([i])) for i in range(n)]
        per_seed = []
        oof_acc = np.zeros(n)
        for s in seeds:
            oof = VARIANTS[variant](d_f, item, splits, s)
            per_seed.append(full_metrics(y, oof))
            oof_acc += oof
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
        out["null_tests"] = run_null_gate(d, item, variant, seed=seeds[0])
    return out


def _run_one_for_pool(args) -> dict:
    d, item, variant, eval_kind, seeds, with_null = args
    try:
        return run_one(d, item, variant, eval_kind, seeds=seeds, with_null=with_null)
    except Exception as e:
        import traceback
        return {"item": item, "variant": variant, "eval": eval_kind,
                "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--items", type=int, nargs="+", default=[9, 11, 14, 18])
    p.add_argument("--variants", nargs="+", default=list(VARIANTS.keys()))
    p.add_argument("--eval", choices=["5split", "loocv"], default="5split")
    p.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--no-null", action="store_true")
    p.add_argument("--tag", default="iter11b")
    p.add_argument("--out_dir", type=str, default=str(RESULTS_DIR))
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)
    print("Loading data...", flush=True)
    d = load_data()
    print(f"  N={len(d['sids'])} PD subjects", flush=True)
    print(f"  V2 shape: {d['X_v2'].shape}", flush=True)
    print(f"  self-norm shape: {d['X_selfnorm'].shape}", flush=True)
    print(f"  per-item shape: {d['X_peritem'].shape}", flush=True)

    jobs = []
    for item in args.items:
        for v in args.variants:
            if v == "self_norm_hurdle_fog" and item != 11:
                continue
            jobs.append((d, item, v, args.eval, tuple(args.seeds), not args.no_null))
    print(f"Jobs: {len(jobs)}", flush=True)

    results = []
    t0 = time.time()
    out_csv = out_dir / f"iter11b_{args.eval}_{args.tag}.csv"
    out_json = out_dir / f"iter11b_{args.eval}_{args.tag}.json"

    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            future_to_job = {pool.submit(_run_one_for_pool, j): j for j in jobs}
            for fut in as_completed(future_to_job):
                r = fut.result()
                results.append(r)
                elapsed = time.time() - t0
                ccc = r.get("ccc_mean")
                ccc_str = f"{ccc:.4f}" if isinstance(ccc, (int, float)) else "ERROR"
                err = r.get("error", "")
                print(f"  [{len(results)}/{len(jobs)}] item={r.get('item')} variant={r.get('variant')} "
                      f"ccc={ccc_str} ({elapsed:.1f}s)" + (f" [{err}]" if err else ""),
                      flush=True)
    else:
        for i, j in enumerate(jobs):
            r = _run_one_for_pool(j)
            results.append(r)
            elapsed = time.time() - t0
            ccc = r.get("ccc_mean")
            ccc_str = f"{ccc:.4f}" if isinstance(ccc, (int, float)) else "ERROR"
            err = r.get("error", "")
            print(f"  [{i+1}/{len(jobs)}] item={r.get('item')} variant={r.get('variant')} "
                  f"ccc={ccc_str} ({elapsed:.1f}s)" + (f" [{err}]" if err else ""),
                  flush=True)

    # Save per-result OOF arrays + JSON
    for r in results:
        if "error" in r:
            continue
        item = r["item"]
        variant = r["variant"]
        eval_kind = r["eval"]
        oof_path = out_dir / f"iter11b_{item}_{variant}_{eval_kind}_{args.tag}.oof.npy"
        if "_oof_array" in r:
            np.save(oof_path, np.asarray(r["_oof_array"], dtype=np.float64))
        r_clean = {k: v for k, v in r.items() if k != "_oof_array"}
        json_path = out_dir / f"iter11b_{item}_{variant}_{eval_kind}_{args.tag}.json"
        with open(json_path, "w") as f:
            json.dump(r_clean, f, indent=2, default=float)

    rows = []
    for r in results:
        rows.append({
            "item": r.get("item"),
            "variant": r.get("variant"),
            "eval": r.get("eval"),
            "ccc_mean": r.get("ccc_mean", np.nan),
            "ccc_std": r.get("ccc_std", np.nan),
            "mae_mean": r.get("mae_mean", np.nan),
            "scrambled_label_ccc": r.get("null_tests", {}).get("scrambled_label_ccc", np.nan)
                if isinstance(r.get("null_tests"), dict) else np.nan,
            "canary_feature_ccc": r.get("null_tests", {}).get("canary_feature_ccc", np.nan)
                if isinstance(r.get("null_tests"), dict) else np.nan,
            "sid_shuffle_selfnorm_ccc": r.get("null_tests", {}).get("sid_shuffle_selfnorm_ccc", np.nan)
                if isinstance(r.get("null_tests"), dict) else np.nan,
            "error": r.get("error", ""),
        })
    df_out = pd.DataFrame(rows)
    df_out.to_csv(out_csv, index=False)
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2, default=float)
    print(f"\nWrote {out_csv} and {out_json}", flush=True)
    print("\nTop entries by CCC (per-item):", flush=True)
    df_ok = df_out.dropna(subset=["ccc_mean"])
    print(df_ok.sort_values(["item", "ccc_mean"], ascending=[True, False]).to_string(index=False),
          flush=True)


if __name__ == "__main__":
    main()
