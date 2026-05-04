"""Iter 11: Cross-product self-norm × CCC objective × hy_residual × per-item heads.

Items 9, 10, 11, 12, 14, 18 (skip 13 — already locked at LOOCV CCC=0.265).

Variants:
  self_norm_only           : LGB on self-normalised V2 features only (1751)
  self_norm_plus_v2        : LGB on V2 ∪ self-norm-V2 (3502 → K=500 Pearson)
  self_norm_plus_item      : LGB on self-norm-V2 ∪ per-item features
  self_norm_cccv2          : V2 ∪ self-norm with CCC objective + affine cal
  self_norm_hy_residual    : Stage-1 Ridge(H&Y) → init_score, Stage-2 LGB on (V2∪self-norm)
                              residual, sum predictions.
  self_norm_hy_residual_cccv2 : Stage-1 Ridge → init_score, Stage-2 LGB-CCC on (V2∪self-norm),
                                 with init_score=ridge prediction (delta head).

Inductive firewall: per-fold Pearson selector (K=500), fold-local impute,
self-norm cache is target-agnostic.

Null gates: scrambled-label, canary-feature, sid-shuffle on self-norm cache.

Outputs:
  results/self_norm_cross_<eval>_<tag>.csv
  results/self_norm_cross_<eval>_<tag>.json
  results/self_norm_cross_<item>_<variant>_<eval>_<tag>.{json,oof.npy}
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
    load_pd_data, kfold_split_stratified, impute_fold,
    train_lgb, get_hy_features, SEEDS,
)
from run_per_item_v2 import load_data as load_per_item_data, get_item_features
from lgb_ccc_objective_v2 import (
    ccc_loss_grad_hess_v2, pearson_select_features, fit_ccc_affine, train_lgb_ccc_v2,
)
from run_per_item_ccc_v2 import fit_lgb_ccc_with_init

SELFNORM_CACHE = RESULTS_DIR / "v2_self_normalized.csv"

ITEMS_TO_SCREEN = [9, 10, 11, 12, 14, 18]  # 13 already locked


def load_subject_aligned_cache(path: Path, sids: list[str]) -> tuple[np.ndarray, list[str]]:
    if not path.exists():
        raise FileNotFoundError(f"Required cache missing: {path}")
    df = pd.read_csv(path)
    df = df.set_index("sid")
    cols = list(df.columns)
    n = len(sids)
    X = np.full((n, len(cols)), np.nan, dtype=np.float64)
    matched = 0
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, cols].to_numpy(dtype=np.float64)
            matched += 1
    print(f"  Cache {path.name}: {matched}/{n} subjects matched ({len(cols)} cols)", flush=True)
    return X, cols


def load_data() -> dict:
    """Load V2 + per-item + self-norm caches."""
    d = load_per_item_data()
    sids = list(d["sids"])
    X_sn, sn_cols = load_subject_aligned_cache(SELFNORM_CACHE, sids)
    d["X_selfnorm"] = X_sn
    d["selfnorm_cols"] = sn_cols
    return d


def feature_select_pearson_fold(X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray,
                                k: int = 500) -> tuple[np.ndarray, np.ndarray]:
    """Inductive Pearson-r feature selection — fits on train rows only."""
    if X_tr.shape[1] <= k:
        return X_tr, X_te
    idx = pearson_select_features(X_tr, y_tr, k=k)
    return X_tr[:, idx], X_te[:, idx]


# ── Variants ───────────────────────────────────────────────────────────────


def variant_self_norm_only(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    y = d["items"][item]
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(d["X_selfnorm"][tr], d["X_selfnorm"][te])
        Xtr, Xte = feature_select_pearson_fold(Xtr, y[tr], Xte, k=500)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_self_norm_plus_v2(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    y = d["items"][item]
    X_aug = np.hstack([d["X_v2"], d["X_selfnorm"]])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte = feature_select_pearson_fold(Xtr, y[tr], Xte, k=500)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_self_norm_plus_item(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Self-norm-V2 + per-item features (no raw V2). Forces LGB onto normalised + item-tailored basis."""
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    if cols:
        X_aug = np.hstack([d["X_selfnorm"], X_item])
    else:
        X_aug = d["X_selfnorm"]
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte = feature_select_pearson_fold(Xtr, y[tr], Xte, k=500)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_self_norm_cccv2(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """V2 ∪ self-norm with CCC objective v2 + post-hoc affine calibration."""
    y = d["items"][item]
    X_aug = np.hstack([d["X_v2"], d["X_selfnorm"]])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte = feature_select_pearson_fold(Xtr, y[tr], Xte, k=500)
        oof[te] = train_lgb_ccc_v2(Xtr, y[tr], Xte, seed)
    return oof


def variant_self_norm_hy_residual(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Stage-1 Ridge(H&Y) → init_score; Stage-2 LGB MSE on (V2 ∪ self-norm) residual.

    init_score-based: pred = ridge_pred + lgb(X_aug, init_score=ridge_pred, target=y).
    Equivalent to MSE-on-residual since LGB MSE objective is unchanged when shifting target.
    """
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
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


def variant_self_norm_hy_residual_cccv2(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Stage-1 Ridge(H&Y) → init_score; Stage-2 LGB-CCC on (V2 ∪ self-norm), init_score=ridge_pred.

    LGB optimises CCC of (init_score + delta) vs original y (NOT residual).
    """
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
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


VARIANTS = {
    "self_norm_only": variant_self_norm_only,
    "self_norm_plus_v2": variant_self_norm_plus_v2,
    "self_norm_plus_item": variant_self_norm_plus_item,
    "self_norm_cccv2": variant_self_norm_cccv2,
    "self_norm_hy_residual": variant_self_norm_hy_residual,
    "self_norm_hy_residual_cccv2": variant_self_norm_hy_residual_cccv2,
}


# ── 5-null gate (3 nulls per spec) ─────────────────────────────────────────


def run_5null_gate(d: dict, item: int, variant: str, seed: int = 42) -> dict:
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


def _filter_nan(d: dict, item: int) -> tuple[dict, np.ndarray]:
    y = d["items"][item]
    nan_mask = np.isnan(y)
    if not nan_mask.any():
        return d, y
    valid = np.where(~nan_mask)[0]
    d_f = dict(d)
    for k in ("sids",):
        d_f[k] = d[k][valid]
    for k in ("X_v2", "X_selfnorm", "X_peritem", "hy", "t1", "obs", "site"):
        if k in d and isinstance(d[k], np.ndarray):
            d_f[k] = d[k][valid]
    d_f["items"] = {k: (v[valid] if isinstance(v, np.ndarray) else v) for k, v in d["items"].items()}
    return d_f, d_f["items"][item]


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
        out["null_tests"] = run_5null_gate(d, item, variant, seed=seeds[0])
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
    p.add_argument("--items", type=int, nargs="+", default=ITEMS_TO_SCREEN)
    p.add_argument("--variants", nargs="+", default=list(VARIANTS.keys()))
    p.add_argument("--eval", choices=["5split", "loocv"], default="5split")
    p.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--no-null", action="store_true")
    p.add_argument("--tag", default="iter11")
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
            jobs.append((d, item, v, args.eval, tuple(args.seeds), not args.no_null))
    print(f"Jobs: {len(jobs)}", flush=True)

    results = []
    t0 = time.time()
    out_csv = out_dir / f"self_norm_cross_{args.eval}_{args.tag}.csv"
    out_json = out_dir / f"self_norm_cross_{args.eval}_{args.tag}.json"

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
        oof_path = out_dir / f"self_norm_cross_{item}_{variant}_{eval_kind}_{args.tag}.oof.npy"
        if "_oof_array" in r:
            np.save(oof_path, np.asarray(r["_oof_array"], dtype=np.float64))
        r_clean = {k: v for k, v in r.items() if k != "_oof_array"}
        json_path = out_dir / f"self_norm_cross_{item}_{variant}_{eval_kind}_{args.tag}.json"
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
