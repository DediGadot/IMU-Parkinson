"""Iter 9 v2 — joints_v2 (event-locked stride kinematics) variants.

Targets: items 8 (leg agility), 9 (arising from chair), 10 (gait), 11 (FoG), 14 (body brady).

Joints_v2 cache (results/joints_v2_subj.csv) is built from quaternion-aware
event-locked stride kinematics; see cache_joints_v2.py for design notes.

Variants (per item):
  joints_v2_only         — LGB on joints_v2 features only
  joints_v2_plus_v2      — LGB on joints_v2 + V2 (concat, per-fold K=500)
  hy_residual_plus_jv2   — Stage-1 Ridge(H&Y) + Stage-2 LGB on (V2 ∪ joints_v2) residual
  late_fusion_jv2        — Ridge meta-stack of OOF[v2_only] + OOF[joints_v2_only]
                           + OOF[item_plus_v2] (per-item).

5-null gate: scrambled-label, canary-feature, null-target permutation.
Lockbox eligible if any variant beats prior per-item 5-fold by +0.015 with null pass.

Output:
  results/joints_v2_<item>_<variant>_5split.json  (5-fold + null gate)
  results/joints_v2_<item>_<variant>_loocv.json   (lockbox LOOCV, only if winning)

DO NOT overwrite or modify run_per_item_v2.py.

Usage:
  python3 run_joints_v2.py --all 5split --workers 8
  python3 run_joints_v2.py --item 14 --variant joints_v2_plus_v2 --eval 5split
  python3 run_joints_v2.py --item 14 --variant joints_v2_plus_v2 --eval loocv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn  # noqa: E402
from project_paths import RESULTS_DIR, ensure_dir  # noqa: E402
from run_t1_iter4 import (  # noqa: E402
    SEEDS,
    feature_select_fold,
    get_hy_features,
    impute_fold,
    kfold_split_stratified,
    load_pd_data,
    train_lgb,
)

JOINTS_V2_CACHE = RESULTS_DIR / "joints_v2_subj.csv"
PERITEM_CACHE = RESULTS_DIR / "peritem_subj_features.csv"
TARGET_ITEMS = [8, 9, 10, 11, 14]
VARIANTS_LIST = [
    "joints_v2_only",
    "joints_v2_plus_v2",
    "hy_residual_plus_jv2",
    "late_fusion_jv2",
]


def load_data() -> dict:
    """Load V2 + per-item + joints_v2 caches; align by sid."""
    d = load_pd_data()
    n = len(d["sids"])
    # Per-item cache (for late_fusion_jv2 baseline OOF)
    if not PERITEM_CACHE.exists():
        raise FileNotFoundError(f"Missing {PERITEM_CACHE}")
    df_pi = pd.read_csv(PERITEM_CACHE).set_index("sid")
    pi_cols = list(df_pi.columns)
    X_pi = np.full((n, len(pi_cols)), np.nan)
    matched_pi = 0
    for i, sid in enumerate(d["sids"]):
        if sid in df_pi.index:
            X_pi[i] = df_pi.loc[sid, pi_cols].to_numpy(dtype=np.float64)
            matched_pi += 1
    print(f"  Per-item cache: {matched_pi}/{n} subjects, {len(pi_cols)} features", flush=True)
    d["X_peritem"] = X_pi
    d["peritem_cols"] = pi_cols

    # Joints_v2 cache
    if not JOINTS_V2_CACHE.exists():
        raise FileNotFoundError(
            f"Missing {JOINTS_V2_CACHE} — run cache_joints_v2.py on remote first"
        )
    df_jv = pd.read_csv(JOINTS_V2_CACHE).set_index("sid")
    jv_cols = list(df_jv.columns)
    X_jv = np.full((n, len(jv_cols)), np.nan)
    matched_jv = 0
    for i, sid in enumerate(d["sids"]):
        if sid in df_jv.index:
            X_jv[i] = df_jv.loc[sid, jv_cols].to_numpy(dtype=np.float64)
            matched_jv += 1
    print(f"  joints_v2 cache: {matched_jv}/{n} subjects, {len(jv_cols)} features", flush=True)
    d["X_joints_v2"] = X_jv
    d["joints_v2_cols"] = jv_cols
    if matched_jv < int(0.7 * n):
        print(f"  WARNING: <70% subjects have joints_v2 features — fallback NaNs will dominate.",
              flush=True)
    return d


def get_item_features(d: dict, item: int) -> tuple[np.ndarray, list[str]]:
    """Subset of per-item features for this item."""
    prefix = f"i{item}_" if item not in (17, 18) else "i1718_"
    cols = d["peritem_cols"]
    idx = [i for i, c in enumerate(cols) if c.startswith(prefix)]
    if not idx:
        return np.zeros((len(d["sids"]), 1)), []
    return d["X_peritem"][:, idx], [cols[i] for i in idx]


# ── Variants ────────────────────────────────────────────────────────────────


def variant_joints_v2_only(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """LGB on joints_v2 features only."""
    y = d["items"][item]
    n = len(y)
    X = d["X_joints_v2"]
    oof = np.zeros(n)
    k = min(500, X.shape[1])
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=k, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_joints_v2_plus_v2(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """LGB on V2 ∪ joints_v2 (per-fold K=500)."""
    y = d["items"][item]
    n = len(y)
    X = np.hstack([d["X_v2"], d["X_joints_v2"]])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_hy_residual_plus_jv2(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Stage-1 Ridge(H&Y) + Stage-2 LGB on V2 ∪ joints_v2 residual."""
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
    n = len(y)
    X = np.hstack([d["X_v2"], d["X_joints_v2"]])
    oof = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], y[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        s2_te = train_lgb(Xtr, resid_tr, Xte, seed)
        oof[te] = s1_te + s2_te
    return oof


def _oof_v2_only(y: np.ndarray, X_v2: np.ndarray, splits, seed: int) -> np.ndarray:
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_v2[tr], X_v2[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def _oof_item_plus_v2(d: dict, item: int, splits, seed: int) -> np.ndarray:
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    n = len(y)
    if not cols:
        return _oof_v2_only(y, d["X_v2"], splits, seed)
    X = np.hstack([d["X_v2"], X_item])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_late_fusion_jv2(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Late-fusion Ridge-meta of {v2-only, joints_v2-only, item+V2} OOFs.

    To avoid leakage, base-learner OOFs MUST come from inner CV inside each outer
    training fold. We do that with an inner 5-fold split per outer-train. The
    meta Ridge is fit on inner-OOF base predictions vs y_train, then applied to
    the outer-test base predictions.
    """
    y = d["items"][item]
    n = len(y)
    X_v2 = d["X_v2"]
    X_jv = d["X_joints_v2"]
    X_item, _ = get_item_features(d, item)
    oof = np.zeros(n)
    for tr, te in splits:
        # Build the test-fold base predictions (each base learner trained on full tr fold)
        # Base 1: v2-only LGB
        Xtr_v2, Xte_v2 = impute_fold(X_v2[tr], X_v2[te])
        Xtr_v2, Xte_v2, _ = feature_select_fold(Xtr_v2, y[tr], Xte_v2, k=500, seed=seed)
        b1_te = train_lgb(Xtr_v2, y[tr], Xte_v2, seed)
        # Base 2: joints_v2-only LGB
        Xtr_jv, Xte_jv = impute_fold(X_jv[tr], X_jv[te])
        k_jv = min(500, X_jv.shape[1])
        Xtr_jv, Xte_jv, _ = feature_select_fold(Xtr_jv, y[tr], Xte_jv, k=k_jv, seed=seed)
        b2_te = train_lgb(Xtr_jv, y[tr], Xte_jv, seed)
        # Base 3: item+V2 LGB
        if X_item.shape[1] >= 1 and not np.all(np.isnan(X_item)):
            X3 = np.hstack([X_v2, X_item])
        else:
            X3 = X_v2
        Xtr_3, Xte_3 = impute_fold(X3[tr], X3[te])
        Xtr_3, Xte_3, _ = feature_select_fold(Xtr_3, y[tr], Xte_3, k=500, seed=seed)
        b3_te = train_lgb(Xtr_3, y[tr], Xte_3, seed)

        # Inner-CV OOFs on training fold for meta fit
        inner = list(KFold(n_splits=min(5, len(tr)), shuffle=True, random_state=seed).split(tr))
        b1_tr_oof = np.zeros(len(tr))
        b2_tr_oof = np.zeros(len(tr))
        b3_tr_oof = np.zeros(len(tr))
        y_tr = y[tr]
        for itr_local, ite_local in inner:
            itr = tr[itr_local]
            ite = tr[ite_local]
            # b1 inner
            Xa, Xb = impute_fold(X_v2[itr], X_v2[ite])
            Xa, Xb, _ = feature_select_fold(Xa, y[itr], Xb, k=500, seed=seed)
            b1_tr_oof[ite_local] = train_lgb(Xa, y[itr], Xb, seed)
            # b2 inner
            Xa, Xb = impute_fold(X_jv[itr], X_jv[ite])
            Xa, Xb, _ = feature_select_fold(Xa, y[itr], Xb, k=k_jv, seed=seed)
            b2_tr_oof[ite_local] = train_lgb(Xa, y[itr], Xb, seed)
            # b3 inner
            Xa, Xb = impute_fold(X3[itr], X3[ite])
            Xa, Xb, _ = feature_select_fold(Xa, y[itr], Xb, k=500, seed=seed)
            b3_tr_oof[ite_local] = train_lgb(Xa, y[itr], Xb, seed)
        meta_X_tr = np.column_stack([b1_tr_oof, b2_tr_oof, b3_tr_oof])
        meta_X_te = np.column_stack([b1_te, b2_te, b3_te])
        meta = Ridge(alpha=1.0, random_state=seed, positive=True)
        meta.fit(meta_X_tr, y_tr)
        oof[te] = meta.predict(meta_X_te)
    return oof


VARIANTS = {
    "joints_v2_only": variant_joints_v2_only,
    "joints_v2_plus_v2": variant_joints_v2_plus_v2,
    "hy_residual_plus_jv2": variant_hy_residual_plus_jv2,
    "late_fusion_jv2": variant_late_fusion_jv2,
}


# ── 5-null gate ─────────────────────────────────────────────────────────────


def run_5null_gate(d: dict, item: int, variant: str, seed: int = 42) -> dict:
    y = d["items"][item]
    splits = kfold_split_stratified(y, 5, seed=seed)
    fn = VARIANTS[variant]
    null = {}
    rng = np.random.RandomState(seed)
    # 1. Scrambled label
    y_scram = rng.permutation(y)
    d2 = {**d, "items": {**d["items"], item: y_scram}}
    try:
        oof_s = fn(d2, item, splits, seed)
        null["scrambled_label_ccc"] = ccc_fn(y_scram, oof_s)
    except Exception as e:
        null["scrambled_label_error"] = str(e)
    # 2. Canary feature appended to V2
    canary = rng.randn(len(y))
    Xv2_aug = np.hstack([d["X_v2"], canary[:, None]])
    d3 = {**d, "X_v2": Xv2_aug}
    try:
        oof_c = fn(d3, item, splits, seed)
        null["canary_feature_ccc"] = ccc_fn(y, oof_c)
    except Exception as e:
        null["canary_feature_error"] = str(e)
    # 3. SID-shuffle on joints_v2 join (re-randomise rows of the joints_v2 cache)
    perm = rng.permutation(len(y))
    d4 = {**d, "X_joints_v2": d["X_joints_v2"][perm]}
    try:
        oof_p = fn(d4, item, splits, seed)
        null["sid_shuffle_ccc"] = ccc_fn(y, oof_p)
    except Exception as e:
        null["sid_shuffle_error"] = str(e)
    return null


# ── Driver ──────────────────────────────────────────────────────────────────


def run_one(
    d: dict,
    item: int,
    variant: str,
    eval_kind: str,
    seeds: tuple = tuple(SEEDS),
    with_null: bool = True,
) -> dict:
    y = d["items"][item]
    nan_mask = np.isnan(y)
    if nan_mask.any():
        valid = np.where(~nan_mask)[0]
        d_f = {**d}
        d_f["sids"] = d["sids"][valid]
        d_f["X_v2"] = d["X_v2"][valid]
        d_f["X_peritem"] = d["X_peritem"][valid]
        d_f["X_joints_v2"] = d["X_joints_v2"][valid]
        d_f["hy"] = d["hy"][valid]
        d_f["t1"] = d["t1"][valid]
        d_f["items"] = {k: (v[valid] if isinstance(v, np.ndarray) else v) for k, v in d["items"].items()}
        d = d_f
        y = d["items"][item]
    n = len(y)
    if eval_kind == "5split":
        per_seed = []
        for s in seeds:
            splits = kfold_split_stratified(y, 5, seed=s)
            oof = VARIANTS[variant](d, item, splits, s)
            per_seed.append(full_metrics(y, oof))
        ccc_mean = float(np.mean([m["ccc"] for m in per_seed]))
        ccc_std = float(np.std([m["ccc"] for m in per_seed]))
        mae_mean = float(np.mean([m["mae"] for m in per_seed]))
        out = {
            "item": item, "variant": variant, "eval": eval_kind,
            "n_subjects": int(n), "seeds": list(seeds),
            "ccc_mean": ccc_mean, "ccc_std": ccc_std, "mae_mean": mae_mean,
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
        ccc_mean = float(np.mean([m["ccc"] for m in per_seed]))
        ccc_std = float(np.std([m["ccc"] for m in per_seed]))
        mae_mean = float(np.mean([m["mae"] for m in per_seed]))
        out = {
            "item": item, "variant": variant, "eval": eval_kind,
            "n_subjects": int(n), "seeds": list(seeds),
            "ccc_mean": ccc_mean, "ccc_std": ccc_std, "mae_mean": mae_mean,
            "per_seed": per_seed,
            "_oof_array": oof_mean.tolist(),
        }
    else:
        raise ValueError(f"unknown eval_kind {eval_kind}")
    if with_null and eval_kind == "5split":
        out["null_tests"] = run_5null_gate(d, item, variant, seed=seeds[0])
    return out


def _run_one_for_pool(args) -> dict:
    d, item, variant, eval_kind, seeds = args
    try:
        return run_one(d, item, variant, eval_kind, seeds=seeds, with_null=(eval_kind == "5split"))
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"item": item, "variant": variant, "eval": eval_kind, "error": str(e)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--item", type=int, default=0)
    p.add_argument("--variant", type=str, default="")
    p.add_argument("--eval", type=str, choices=["5split", "loocv"], default="5split")
    p.add_argument("--all", type=str, default="", help="screen TARGET_ITEMS x VARIANTS_LIST")
    p.add_argument("--workers", type=int, default=1, help="ProcessPool workers (1 = sequential)")
    p.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    p.add_argument("--out_dir", type=str, default=str(RESULTS_DIR))
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)
    print("Loading data...", flush=True)
    d = load_data()
    print(
        f"  N={len(d['sids'])} PD subjects | V2={d['X_v2'].shape[1]} | "
        f"peritem={d['X_peritem'].shape[1]} | joints_v2={d['X_joints_v2'].shape[1]}",
        flush=True,
    )

    if args.all:
        eval_kind = args.all
        jobs = [(d, item, v, eval_kind, tuple(args.seeds))
                for item in TARGET_ITEMS for v in VARIANTS_LIST]
        print(f"Total jobs: {len(jobs)}", flush=True)
        results = []
        t0 = time.time()
        out_csv = out_dir / f"joints_v2_screening_{eval_kind}.csv"
        out_json = out_dir / f"joints_v2_screening_{eval_kind}.json"
        for i, args_ in enumerate(jobs):
            r = _run_one_for_pool(args_)
            results.append(r)
            elapsed = time.time() - t0
            ccc = r.get("ccc_mean")
            ccc_str = f"{ccc:.4f}" if isinstance(ccc, (int, float)) else "ERROR"
            err = r.get("error", "")
            print(
                f"  [{i+1}/{len(jobs)}] item={r.get('item')} variant={r.get('variant')} "
                f"ccc={ccc_str} ({elapsed:.1f}s)" + (f" [{err}]" if err else ""),
                flush=True,
            )
            df_out = pd.DataFrame([
                {"item": r2["item"], "variant": r2["variant"], "eval": r2["eval"],
                 "ccc_mean": r2.get("ccc_mean", np.nan),
                 "ccc_std": r2.get("ccc_std", np.nan),
                 "mae_mean": r2.get("mae_mean", np.nan),
                 "scrambled_label_ccc": r2.get("null_tests", {}).get("scrambled_label_ccc", np.nan),
                 "canary_feature_ccc": r2.get("null_tests", {}).get("canary_feature_ccc", np.nan),
                 "sid_shuffle_ccc": r2.get("null_tests", {}).get("sid_shuffle_ccc", np.nan)}
                for r2 in results
            ])
            df_out.to_csv(out_csv, index=False)
            with open(out_json, "w") as f:
                json.dump(results, f, indent=2, default=float)
        print(f"\nWrote {out_csv} and {out_json}", flush=True)
        print("\nLeaderboard:", flush=True)
        df_top = df_out.dropna(subset=["ccc_mean"]).sort_values(["item", "ccc_mean"], ascending=[True, False])
        print(df_top.to_string(), flush=True)
    else:
        if not args.variant:
            raise SystemExit("--variant required if --all not used")
        if args.item < 1 or args.item > 18:
            raise SystemExit("--item must be 1..18")
        r = run_one(d, args.item, args.variant, args.eval, seeds=tuple(args.seeds))
        out_path = out_dir / f"joints_v2_item{args.item}_{args.variant}_{args.eval}.json"
        with open(out_path, "w") as f:
            json.dump(r, f, indent=2, default=float)
        print(json.dumps(
            {"item": r["item"], "variant": r["variant"], "eval": r["eval"],
             "ccc_mean": r.get("ccc_mean")}, default=float))
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
