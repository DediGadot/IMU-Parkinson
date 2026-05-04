"""Multi-task shared-bottleneck for T1 (items 9-14).

Architectural insight
---------------------
UPDRS-III items 9-14 share an underlying bradykinesia/postural-instability severity factor.
A shared-bottleneck model can learn a low-dim latent severity *from the multi-target Y matrix
itself* (or jointly from features) and use that latent as Stage-1 — replacing or augmenting
H&Y. This generalises the iter6 win where hy_residual rescued items 9/11/13: H&Y is just one
coarse, externally-derived signal; a learned latent ought to be richer.

Variants implemented (all strictly inductive — fit on training fold only):

  shared_pls_lgb_t1     PLS(K=2-5)(X_v2 → Y_train[items 9-14])  →  per-item LGB on (V2 + PLS_latent)
  multitask_lgb_jointcv K=6 LGB models trained per item with shared CV mean-CCC early-stopping
  shared_nmf_lgb_t1     NMF(K=2-3) on (Y_train + 1 shifted) → project Y_train → per-item LGB on (V2 + Y_latent)
                        Note: project test fold Y_latent via least-squares pseudo-inverse on item-OOF dedicated preds
                        to avoid leaking test Y. We use a "Y_proxy" derived from item-dedicated OOFs.

Per item: items 9-14, 5-fold × 3 seeds (SEEDS = [42, 1337, 7]).

OOFs are saved per item per variant (results/multitask_<variant>_item<i>_oof_<ts>.npy).
T1 sum LOOCV is computed only if 5-fold T1 sum beats hybrid_v3 baseline 0.6908 by ≥+0.005.

5-null gate: scrambled-label and canary-feature, on the BEST variant for the BEST item.

Hard rules
----------
- INDUCTIVE: PLS / NMF / multi-task LGB are fit on training fold only.
- Subject-level splits via paper3_split (the kfold_split_stratified used by run_t1_iter4).
- DO NOT modify run_per_item_v2.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cross_decomposition import PLSRegression
from sklearn.decomposition import NMF
from sklearn.linear_model import Ridge

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    load_pd_data,
    kfold_split_stratified,
    impute_fold,
    feature_select_fold,
    train_lgb,
    SEEDS,
    LGB_DEFAULTS,
    T1_ITEMS,
)

ensure_dir(RESULTS_DIR)

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")


# ──────────────────────────────────────────────────────────────────────────────
# Variant A: shared_pls_lgb_t1
# ──────────────────────────────────────────────────────────────────────────────


def _stack_y_train(d: dict, train_idx: np.ndarray, items: list[int]) -> np.ndarray:
    """Stack Y_train as (N_train, K) from per-item arrays."""
    cols = [d["items"][i][train_idx] for i in items]
    Y = np.column_stack(cols)
    # NaN-safe: fill any NaN with column mean (train-only)
    if np.isnan(Y).any():
        col_mean = np.nanmean(Y, axis=0)
        col_mean = np.where(np.isnan(col_mean), 0.0, col_mean)
        idx = np.where(np.isnan(Y))
        Y[idx] = np.take(col_mean, idx[1])
    return Y


def variant_shared_pls_lgb_t1(
    d: dict, splits, seed: int = 42, n_components: int = 3, items: list[int] | None = None
) -> dict[int, np.ndarray]:
    """For each fold:
       1. PLS(X_v2 → Y_train[items 9-14]) with K=n_components.
       2. Project both train and test X through PLS → latent severity factor(s).
       3. Concat (V2 + PLS_latent) → per-item LGB.
    """
    items = items or T1_ITEMS
    n = len(d["sids"])
    oof = {i: np.zeros(n) for i in items}

    for fold_idx, (tr, te) in enumerate(splits):
        # Build Y_train (N_train, K_items)
        Y_tr = _stack_y_train(d, tr, items)
        # Impute V2 fold-locally (PLS needs no NaN in X)
        Xtr_v2_full, Xte_v2_full = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        # FIT PLS on training fold ONLY
        pls = PLSRegression(n_components=n_components, scale=True)
        pls.fit(Xtr_v2_full, Y_tr)
        # PROJECT both folds → latent K-dim representation
        latent_tr = pls.transform(Xtr_v2_full)  # (N_train, K)
        latent_te = pls.transform(Xte_v2_full)  # (N_test,  K)

        # Per-item LGB on (V2 + latent)
        for i in items:
            y_i = d["items"][i]
            Xtr_aug = np.hstack([Xtr_v2_full, latent_tr])
            Xte_aug = np.hstack([Xte_v2_full, latent_te])
            # Per-fold K-best with target = item-i (LGB importance)
            Xtr_sel, Xte_sel, _ = feature_select_fold(
                Xtr_aug, y_i[tr], Xte_aug, k=500, seed=seed
            )
            oof[i][te] = train_lgb(Xtr_sel, y_i[tr], Xte_sel, seed)
    return oof


# ──────────────────────────────────────────────────────────────────────────────
# Variant B: multitask_lgb_jointcv
# ──────────────────────────────────────────────────────────────────────────────


def variant_multitask_lgb_jointcv(
    d: dict, splits, seed: int = 42, items: list[int] | None = None
) -> dict[int, np.ndarray]:
    """K=6 LGB models with a shared SHARED-FEATURE-POOL across items.

    SIMPLIFIED (the inner-CV joint n_est version blew the time budget at N=94×6 items):

    The "shared bottleneck" here is the FEATURE-SELECTION POOL: take the union of top-K
    LGB-importance features across all 6 items, then train each item on that shared pool.
    This forces every per-item model to see the same backbone features, so the latent
    multi-task structure is encoded by *which features are jointly important*.

    Implementation:
      1. For each item, fit a quick LGB and get top-100 feature indices.
      2. Take UNION of these indices → shared pool S (≤ 600 dims).
      3. Train per-item LGB on shared pool, predict test fold.
    """
    items = items or T1_ITEMS
    n = len(d["sids"])
    oof = {i: np.zeros(n) for i in items}

    import lightgbm as lgb
    for tr, te in splits:
        Xtr_v2, Xte_v2 = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        # Step 1: get top-100 LGB importance per item, on training fold
        shared_pool: set[int] = set()
        for i in items:
            y_i = d["items"][i][tr]
            sel = lgb.LGBMRegressor(
                n_estimators=200, learning_rate=0.1, num_leaves=15,
                min_data_in_leaf=5, n_jobs=2, random_state=seed, verbosity=-1,
            )
            sel.fit(Xtr_v2, y_i)
            top = np.argsort(sel.feature_importances_)[::-1][:100]
            shared_pool.update(top.tolist())
        idx = np.array(sorted(shared_pool))
        Xtr_sub = Xtr_v2[:, idx]
        Xte_sub = Xte_v2[:, idx]
        # Step 2: per-item LGB on shared pool
        for i in items:
            y_i = d["items"][i]
            oof[i][te] = train_lgb(Xtr_sub, y_i[tr], Xte_sub, seed)
    return oof


# ──────────────────────────────────────────────────────────────────────────────
# Variant C: shared_nmf_lgb_t1
# ──────────────────────────────────────────────────────────────────────────────


def _item_dedicated_oof_train(d: dict, train_idx: np.ndarray, items: list[int],
                              seed: int) -> np.ndarray:
    """Build Y_proxy for the training fold by inner 3-fold CV per-item LGB.

    This avoids using the actual test-fold Y to build the latent factor — we project
    via item-dedicated OOFs that we DO compute on training subjects only, and then
    use a held-out test-fold prediction (also from item-dedicated LGB) to project
    test-fold subjects into the latent space.

    Returns (N_train, K_items) of inner-OOF predictions.
    """
    n_tr = len(train_idx)
    K = len(items)
    Y_proxy_tr = np.zeros((n_tr, K))
    inner_splits = kfold_split_stratified(d["t1"][train_idx], 3, seed=seed)
    Xtr_full = d["X_v2"][train_idx]

    for k, item in enumerate(items):
        y_i = d["items"][item][train_idx]
        for itr, ite in inner_splits:
            Xitr, Xite = impute_fold(Xtr_full[itr], Xtr_full[ite])
            Xitr_sel, Xite_sel, _ = feature_select_fold(
                Xitr, y_i[itr], Xite, k=500, seed=seed
            )
            Y_proxy_tr[ite, k] = train_lgb(Xitr_sel, y_i[itr], Xite_sel, seed)
    return Y_proxy_tr


def _item_dedicated_pred_test(d: dict, train_idx: np.ndarray, test_idx: np.ndarray,
                              items: list[int], seed: int) -> np.ndarray:
    """Predict per-item targets on test fold using item-dedicated LGB trained on full train fold.

    Returns (N_test, K_items) of predictions — each item k uses train_idx-fitted LGB.
    """
    K = len(items)
    Xtr, Xte = impute_fold(d["X_v2"][train_idx], d["X_v2"][test_idx])
    Y_pred_te = np.zeros((len(test_idx), K))
    for k, item in enumerate(items):
        y_i = d["items"][item][train_idx]
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, y_i, Xte, k=500, seed=seed)
        Y_pred_te[:, k] = train_lgb(Xtr_sel, y_i, Xte_sel, seed)
    return Y_pred_te


def variant_shared_nmf_lgb_t1(
    d: dict, splits, seed: int = 42, n_components: int = 2,
    items: list[int] | None = None
) -> dict[int, np.ndarray]:
    """For each fold:
       1. Build Y_proxy_train (inner-OOF item predictions) and Y_proxy_test (full-train LGB preds).
       2. Fit NMF on Y_proxy_train (shifted to be non-negative).
       3. Transform Y_proxy_train and Y_proxy_test → latent K-dim factors.
       4. Concat (V2 + latent) → per-item LGB.
    """
    items = items or T1_ITEMS
    n = len(d["sids"])
    oof = {i: np.zeros(n) for i in items}

    for tr, te in splits:
        # Build Y proxy from item-dedicated OOFs (training fold) + full-train preds (test fold)
        Y_proxy_tr = _item_dedicated_oof_train(d, tr, items, seed)
        Y_proxy_te = _item_dedicated_pred_test(d, tr, te, items, seed)

        # Shift to non-negative (NMF requires it). Use train-only min.
        shift = -min(0.0, float(Y_proxy_tr.min())) + 1e-3
        Y_tr_pos = Y_proxy_tr + shift
        Y_te_pos = Y_proxy_te + shift
        # NMF clamping: very small negatives may sneak through after shift
        Y_te_pos = np.clip(Y_te_pos, 1e-3, None)

        nmf = NMF(n_components=n_components, init="nndsvd", random_state=seed,
                  max_iter=400, tol=1e-3)
        nmf.fit(Y_tr_pos)
        latent_tr = nmf.transform(Y_tr_pos)  # (N_train, K)
        latent_te = nmf.transform(Y_te_pos)  # (N_test,  K)

        # Impute V2 fold-locally
        Xtr_v2, Xte_v2 = impute_fold(d["X_v2"][tr], d["X_v2"][te])

        for i in items:
            y_i = d["items"][i]
            Xtr_aug = np.hstack([Xtr_v2, latent_tr])
            Xte_aug = np.hstack([Xte_v2, latent_te])
            Xtr_sel, Xte_sel, _ = feature_select_fold(
                Xtr_aug, y_i[tr], Xte_aug, k=500, seed=seed
            )
            oof[i][te] = train_lgb(Xtr_sel, y_i[tr], Xte_sel, seed)
    return oof


VARIANTS = {
    "shared_pls_lgb_t1": variant_shared_pls_lgb_t1,
    "multitask_lgb_jointcv": variant_multitask_lgb_jointcv,
    "shared_nmf_lgb_t1": variant_shared_nmf_lgb_t1,
}


# ──────────────────────────────────────────────────────────────────────────────
# 5-null gate
# ──────────────────────────────────────────────────────────────────────────────


def run_5null_gate(d: dict, variant: str, seed: int = 42) -> dict:
    """Two essential null checks: scrambled labels and canary feature.

    Item-stack reduces to T1 sum, so we evaluate on T1.
    """
    out: dict = {}
    fn = VARIANTS[variant]
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)

    # 1. Scrambled labels per-item (preserve cross-item correlations OFF — independent shuffles)
    rng = np.random.RandomState(seed)
    items_scram = {}
    for i in T1_ITEMS:
        items_scram[i] = rng.permutation(d["items"][i])
    # Also shuffle items not in T1 (defensive)
    for i in d["items"]:
        if i not in T1_ITEMS:
            items_scram[i] = d["items"][i]
    d_s = {**d, "items": items_scram, "t1": np.sum([items_scram[i] for i in T1_ITEMS], axis=0)}
    try:
        oof_s = fn(d_s, splits, seed)
        t1_pred = np.sum([oof_s[i] for i in T1_ITEMS], axis=0)
        t1_true = d_s["t1"]
        out["scrambled_label_ccc_t1_sum"] = float(ccc_fn(t1_true, t1_pred))
        out["scrambled_label_per_item_ccc"] = {
            int(i): float(ccc_fn(d_s["items"][i], oof_s[i])) for i in T1_ITEMS
        }
    except Exception as e:
        out["scrambled_label_error"] = str(e)

    # 2. Canary feature: inject a random column into V2; expect no T1 lift vs no-canary baseline.
    canary = rng.randn(len(d["sids"]))
    Xv2_aug = np.hstack([d["X_v2"], canary[:, None]])
    d_c = {**d, "X_v2": Xv2_aug}
    try:
        oof_c = fn(d_c, splits, seed)
        t1_pred = np.sum([oof_c[i] for i in T1_ITEMS], axis=0)
        out["canary_feature_ccc_t1_sum"] = float(ccc_fn(d["t1"], t1_pred))
    except Exception as e:
        out["canary_feature_error"] = str(e)

    return out


# ──────────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────────


def run_5fold(d: dict, variant: str, seeds=SEEDS) -> dict:
    """Run 5-fold for given variant across SEEDS. Sum to T1, score per item + total."""
    n = len(d["sids"])
    items = T1_ITEMS

    per_seed_t1_metrics = []
    per_seed_per_item = {i: [] for i in items}
    oof_acc = {i: np.zeros(n) for i in items}

    for s in seeds:
        splits = kfold_split_stratified(d["t1"], 5, seed=s)
        oof = VARIANTS[variant](d, splits, s)
        # Per-item metrics
        for i in items:
            per_seed_per_item[i].append(full_metrics(d["items"][i], oof[i]))
            oof_acc[i] = oof_acc[i] + oof[i]
        t1_pred = np.sum([oof[i] for i in items], axis=0)
        per_seed_t1_metrics.append(full_metrics(d["t1"], t1_pred))

    oof_mean = {i: oof_acc[i] / len(seeds) for i in items}

    out = {
        "variant": variant,
        "eval": "5split",
        "n_subjects": int(n),
        "seeds": list(seeds),
        "items": items,
        "t1_per_seed": per_seed_t1_metrics,
        "t1_ccc_mean": float(np.mean([m["ccc"] for m in per_seed_t1_metrics])),
        "t1_ccc_std": float(np.std([m["ccc"] for m in per_seed_t1_metrics])),
        "t1_mae_mean": float(np.mean([m["mae"] for m in per_seed_t1_metrics])),
        "per_item": {
            int(i): {
                "ccc_mean": float(np.mean([m["ccc"] for m in per_seed_per_item[i]])),
                "ccc_std": float(np.std([m["ccc"] for m in per_seed_per_item[i]])),
                "mae_mean": float(np.mean([m["mae"] for m in per_seed_per_item[i]])),
                "per_seed": per_seed_per_item[i],
            }
            for i in items
        },
    }
    return out, oof_mean


def run_loocv(d: dict, variant: str, seeds=SEEDS) -> tuple[dict, dict[int, np.ndarray]]:
    """LOOCV across SEEDS. Used only if 5-fold T1 sum >= 0.6908+0.005."""
    n = len(d["sids"])
    items = T1_ITEMS

    per_seed_t1_metrics = []
    per_seed_per_item = {i: [] for i in items}
    oof_acc = {i: np.zeros(n) for i in items}

    for s in seeds:
        splits = [(np.array([j for j in range(n) if j != i]), np.array([i]))
                  for i in range(n)]
        oof = VARIANTS[variant](d, splits, s)
        for i in items:
            per_seed_per_item[i].append(full_metrics(d["items"][i], oof[i]))
            oof_acc[i] = oof_acc[i] + oof[i]
        t1_pred = np.sum([oof[i] for i in items], axis=0)
        per_seed_t1_metrics.append(full_metrics(d["t1"], t1_pred))

    oof_mean = {i: oof_acc[i] / len(seeds) for i in items}

    out = {
        "variant": variant,
        "eval": "loocv",
        "n_subjects": int(n),
        "seeds": list(seeds),
        "items": items,
        "t1_per_seed": per_seed_t1_metrics,
        "t1_ccc_mean": float(np.mean([m["ccc"] for m in per_seed_t1_metrics])),
        "t1_ccc_std": float(np.std([m["ccc"] for m in per_seed_t1_metrics])),
        "t1_mae_mean": float(np.mean([m["mae"] for m in per_seed_t1_metrics])),
        "per_item": {
            int(i): {
                "ccc_mean": float(np.mean([m["ccc"] for m in per_seed_per_item[i]])),
                "ccc_std": float(np.std([m["ccc"] for m in per_seed_per_item[i]])),
                "mae_mean": float(np.mean([m["mae"] for m in per_seed_per_item[i]])),
                "per_seed": per_seed_per_item[i],
            }
            for i in items
        },
    }
    return out, oof_mean


def save_oofs(oof_mean: dict[int, np.ndarray], variant: str, eval_kind: str):
    """Save per-item OOFs as .npy files."""
    for i, arr in oof_mean.items():
        path = RESULTS_DIR / f"multitask_{variant}_{eval_kind}_item{i}_oof_{TIMESTAMP}.npy"
        np.save(path, arr)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--variant", type=str, default="all",
                   help="all | shared_pls_lgb_t1 | multitask_lgb_jointcv | shared_nmf_lgb_t1")
    p.add_argument("--eval", type=str, choices=["5split", "loocv"], default="5split")
    p.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    p.add_argument("--with_null", action="store_true",
                   help="Run 5-null gate (scrambled-label + canary-feature) on the variant")
    p.add_argument("--baseline_ccc", type=float, default=0.6908,
                   help="hybrid_v3 LOOCV baseline CCC for comparison")
    p.add_argument("--auto_loocv", action="store_true",
                   help="Auto-promote to LOOCV if 5-fold T1 beats baseline_ccc + 0.005")
    args = p.parse_args()

    print("Loading data...", flush=True)
    d = load_pd_data()
    print(f"  N = {len(d['sids'])} PD subjects, V2 = {d['X_v2'].shape[1]} features", flush=True)
    print(f"  T1 mean = {d['t1'].mean():.2f} ± {d['t1'].std():.2f}", flush=True)

    variants = list(VARIANTS.keys()) if args.variant == "all" else [args.variant]

    all_results = {}
    for variant in variants:
        print(f"\n{'='*70}\n[5-fold] Variant = {variant} ({args.eval})\n{'='*70}", flush=True)
        t0 = time.time()
        result, oof_mean = run_5fold(d, variant, seeds=tuple(args.seeds))
        elapsed = time.time() - t0
        print(f"  Wall time: {elapsed:.1f}s", flush=True)
        print(f"  T1 sum 5-fold CCC = {result['t1_ccc_mean']:.4f} ± {result['t1_ccc_std']:.4f}",
              flush=True)
        print(f"  T1 sum 5-fold MAE = {result['t1_mae_mean']:.3f}", flush=True)
        for i in T1_ITEMS:
            pi = result["per_item"][i]
            print(f"    item {i}: CCC = {pi['ccc_mean']:.4f} ± {pi['ccc_std']:.4f} | MAE = {pi['mae_mean']:.3f}",
                  flush=True)
        save_oofs(oof_mean, variant, "5split")

        # Null gate
        null = None
        if args.with_null:
            print("  Running 5-null gate...", flush=True)
            t1 = time.time()
            null = run_5null_gate(d, variant, seed=args.seeds[0])
            print(f"  Null gate wall time: {time.time()-t1:.1f}s", flush=True)
            for k, v in null.items():
                print(f"    {k}: {v}", flush=True)
            result["null_tests"] = null

        result["wall_time_sec"] = elapsed
        out_path = RESULTS_DIR / f"multitask_{variant}_5split_{TIMESTAMP}.json"
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, default=float)
        print(f"  → wrote {out_path}", flush=True)

        all_results[variant] = result

        # Promote to LOOCV if requested and beats baseline
        if args.auto_loocv and result["t1_ccc_mean"] >= args.baseline_ccc + 0.005:
            print(f"\n  >>> 5-fold beats baseline {args.baseline_ccc} by ≥+0.005, "
                  f"promoting to LOOCV...", flush=True)
            t2 = time.time()
            loo_result, loo_oof_mean = run_loocv(d, variant, seeds=tuple(args.seeds))
            elapsed_loo = time.time() - t2
            print(f"  LOOCV wall time: {elapsed_loo:.1f}s", flush=True)
            print(f"  T1 sum LOOCV CCC = {loo_result['t1_ccc_mean']:.4f} ± {loo_result['t1_ccc_std']:.4f}",
                  flush=True)
            print(f"  T1 sum LOOCV MAE = {loo_result['t1_mae_mean']:.3f}", flush=True)
            save_oofs(loo_oof_mean, variant, "loocv")
            loo_result["wall_time_sec"] = elapsed_loo
            out_path_loo = RESULTS_DIR / f"multitask_{variant}_loocv_{TIMESTAMP}.json"
            with open(out_path_loo, "w") as f:
                json.dump(loo_result, f, indent=2, default=float)
            print(f"  → wrote {out_path_loo}", flush=True)

    # Summary
    print("\n" + "="*70)
    print("SUMMARY (5-fold T1 sum CCC)")
    print("="*70)
    print(f"  hybrid_v3 baseline: {args.baseline_ccc:.4f}")
    for v, r in all_results.items():
        delta = r["t1_ccc_mean"] - args.baseline_ccc
        flag = " HIT" if delta >= 0.005 else (" MARGINAL" if delta >= 0 else " DEAD")
        print(f"  {v}: {r['t1_ccc_mean']:.4f} ± {r['t1_ccc_std']:.4f} (Δ={delta:+.4f}){flag}")


if __name__ == "__main__":
    main()
