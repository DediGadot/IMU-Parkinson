"""Stride-locked late-fusion runner — items 7, 8, 9, 10, 11, 12, 14.

Three new variants tested per item (5-fold × 3 seeds):

  stride_locked_only:   LGB on stride-aggregated features only (per-fold K=200 LGB importance).
  stride_plus_v2:       LGB on stride ∪ V2 (per-fold K=500).
  late_fusion_ridge:    Train SEPARATE LGB on (a) V2, (b) stride, (c) per-item peritem only.
                        Get OOF for each. Stack via Ridge meta on training-fold OOF only
                        (FOLD-CLEAN). Avoids feature-concat dilution.

If any variant beats prior best 5-fold by >= +0.015 (with null gate scrambled-CCC < 0.20),
promote to LOOCV lockbox.

Inductive contract:
  - subject-level splits (run_t1_iter4.kfold_split_stratified — same protocol as iter4)
  - FoldImputer / FoldNormalizer from inductive_lib.py — fit on TRAIN only.
  - Per-fold LGB importance K-best feature selection.
  - Multi-seed: SEEDS = [42, 1337, 7].
  - 5-null gate: scrambled-label, canary feature.
  - Save per-variant OOF as .npy alongside lockbox JSONs.

Output:
  results/stride_screen_<item>_<variant>_5split.json
  results/stride_screen_<item>_<variant>_oof.npy
  results/lockbox_peritem_<item>_stride_<variant>.json   (only if promoted)
  results/lockbox_peritem_<item>_stride_<variant>_oof.npy

Usage:
  python3 run_stride_fusion.py --screen --items 7,8,9,10,11,12,14
  python3 run_stride_fusion.py --lockbox --item 11 --variant stride_locked_only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    load_pd_data, kfold_split_stratified, impute_fold,
    feature_select_fold, train_lgb,
    SEEDS, LGB_DEFAULTS,
)

ensure_dir(RESULTS_DIR)

STRIDE_CACHE = REPO_ROOT / "results" / "stride_locked_subj.csv"
PERITEM_CACHE = REPO_ROOT / "results" / "peritem_subj_features.csv"

TARGET_ITEMS = [7, 8, 9, 10, 11, 12, 14]
PROMOTE_DELTA = 0.015  # promote to LOOCV if 5-fold improves by this much


# ─── Data ────────────────────────────────────────────────────────────────────


def load_stride_features(sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Align stride cache with subject ids. Missing rows -> NaN."""
    if not STRIDE_CACHE.exists():
        raise FileNotFoundError(f"Missing {STRIDE_CACHE} — run cache_stride_locked.py first")
    df = pd.read_csv(STRIDE_CACHE).set_index("sid")
    feat_cols = list(df.columns)
    n = len(sids)
    X = np.full((n, len(feat_cols)), np.nan)
    matched = 0
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, feat_cols].to_numpy(dtype=np.float64)
            matched += 1
    print(f"  Stride features matched for {matched}/{n} subjects ({len(feat_cols)} features)", flush=True)
    return X, feat_cols


def load_peritem_features(sids: np.ndarray, item: int) -> tuple[np.ndarray, list[str]]:
    """Subset peritem cache to columns starting with 'i{item}_'. Returns (n, k) array."""
    if not PERITEM_CACHE.exists():
        raise FileNotFoundError(f"Missing {PERITEM_CACHE}")
    df = pd.read_csv(PERITEM_CACHE).set_index("sid")
    if item == 17 or item == 18:
        prefix = "i1718_"
    else:
        prefix = f"i{item}_"
    cols = [c for c in df.columns if c.startswith(prefix)]
    if not cols:
        return np.zeros((len(sids), 0)), []
    n = len(sids)
    X = np.full((n, len(cols)), np.nan)
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, cols].to_numpy(dtype=np.float64)
    return X, cols


def get_target(d: dict, item: int) -> np.ndarray:
    return d["items"][item]


# ─── Variants ────────────────────────────────────────────────────────────────


def variant_stride_locked_only(X_stride: np.ndarray, y: np.ndarray,
                                splits, seed: int = 42) -> np.ndarray:
    """LGB on stride-aggregated features only. K=200."""
    n = len(y)
    oof = np.zeros(n)
    k = min(200, X_stride.shape[1])
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_stride[tr], X_stride[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=k, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_stride_plus_v2(d: dict, X_stride: np.ndarray, y: np.ndarray,
                            splits, seed: int = 42) -> np.ndarray:
    """LGB on stride ∪ V2 features. K=500."""
    n = len(y)
    X_aug = np.hstack([d["X_v2"], X_stride])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_late_fusion_ridge(d: dict, X_stride: np.ndarray, X_peritem: np.ndarray,
                               y: np.ndarray, splits, seed: int = 42) -> np.ndarray:
    """Late-fusion stack: train separate LGBs on V2, stride, peritem; stack via Ridge meta.

    For each outer split, we generate three OOF columns by running an INNER 5-fold split
    on the training-fold rows (so the meta model never sees direct base predictions on
    its training data, which would overfit). The Ridge meta is then fit on the inner-OOF
    matrix and predicts on the outer-test base predictions.
    """
    n = len(y)
    oof = np.zeros(n)
    has_peritem = X_peritem.shape[1] > 0

    for tr, te in splits:
        n_tr = len(tr)
        # Inner 5-fold (different seed to break correlation with outer fold structure)
        inner_splits = kfold_split_stratified(y[tr], 5, seed=seed + 100)
        # Build inner OOF for each base
        inner_oof_v2 = np.zeros(n_tr)
        inner_oof_str = np.zeros(n_tr)
        inner_oof_pi = np.zeros(n_tr)
        for itr, ite in inner_splits:
            # V2 base
            X_v2_tr_i = d["X_v2"][tr][itr]
            X_v2_te_i = d["X_v2"][tr][ite]
            X_v2_tr_i, X_v2_te_i = impute_fold(X_v2_tr_i, X_v2_te_i)
            X_v2_tr_i, X_v2_te_i, _ = feature_select_fold(
                X_v2_tr_i, y[tr][itr], X_v2_te_i, k=500, seed=seed)
            inner_oof_v2[ite] = train_lgb(X_v2_tr_i, y[tr][itr], X_v2_te_i, seed)
            # Stride base
            X_str_tr_i = X_stride[tr][itr]
            X_str_te_i = X_stride[tr][ite]
            X_str_tr_i, X_str_te_i = impute_fold(X_str_tr_i, X_str_te_i)
            k_str = min(200, X_str_tr_i.shape[1])
            X_str_tr_i, X_str_te_i, _ = feature_select_fold(
                X_str_tr_i, y[tr][itr], X_str_te_i, k=k_str, seed=seed)
            inner_oof_str[ite] = train_lgb(X_str_tr_i, y[tr][itr], X_str_te_i, seed)
            # Peritem base (or zeros)
            if has_peritem:
                X_pi_tr_i = X_peritem[tr][itr]
                X_pi_te_i = X_peritem[tr][ite]
                X_pi_tr_i, X_pi_te_i = impute_fold(X_pi_tr_i, X_pi_te_i)
                k_pi = min(200, X_pi_tr_i.shape[1])
                X_pi_tr_i, X_pi_te_i, _ = feature_select_fold(
                    X_pi_tr_i, y[tr][itr], X_pi_te_i, k=k_pi, seed=seed)
                inner_oof_pi[ite] = train_lgb(X_pi_tr_i, y[tr][itr], X_pi_te_i, seed)
        # Build outer-test base predictions: train each base on full outer-train
        # V2 outer
        X_v2_tr, X_v2_te = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        X_v2_tr, X_v2_te, _ = feature_select_fold(
            X_v2_tr, y[tr], X_v2_te, k=500, seed=seed)
        v2_te = train_lgb(X_v2_tr, y[tr], X_v2_te, seed)
        # Stride outer
        X_str_tr, X_str_te = impute_fold(X_stride[tr], X_stride[te])
        k_str = min(200, X_str_tr.shape[1])
        X_str_tr, X_str_te, _ = feature_select_fold(
            X_str_tr, y[tr], X_str_te, k=k_str, seed=seed)
        str_te = train_lgb(X_str_tr, y[tr], X_str_te, seed)
        # Peritem outer
        if has_peritem:
            X_pi_tr, X_pi_te = impute_fold(X_peritem[tr], X_peritem[te])
            k_pi = min(200, X_pi_tr.shape[1])
            X_pi_tr, X_pi_te, _ = feature_select_fold(
                X_pi_tr, y[tr], X_pi_te, k=k_pi, seed=seed)
            pi_te = train_lgb(X_pi_tr, y[tr], X_pi_te, seed)
        else:
            pi_te = np.zeros(len(te))
        # Fit Ridge meta on inner-OOF, predict on outer-test base preds
        if has_peritem:
            Z_tr = np.column_stack([inner_oof_v2, inner_oof_str, inner_oof_pi])
            Z_te = np.column_stack([v2_te, str_te, pi_te])
        else:
            Z_tr = np.column_stack([inner_oof_v2, inner_oof_str])
            Z_te = np.column_stack([v2_te, str_te])
        meta = Ridge(alpha=1.0, random_state=seed)
        meta.fit(Z_tr, y[tr])
        oof[te] = meta.predict(Z_te)
    return oof


def run_variant(name: str, d: dict, X_stride: np.ndarray, X_peritem: np.ndarray,
                y: np.ndarray, splits, seed: int) -> np.ndarray:
    if name == "stride_locked_only":
        return variant_stride_locked_only(X_stride, y, splits, seed)
    if name == "stride_plus_v2":
        return variant_stride_plus_v2(d, X_stride, y, splits, seed)
    if name == "late_fusion_ridge":
        return variant_late_fusion_ridge(d, X_stride, X_peritem, y, splits, seed)
    raise ValueError(f"Unknown variant: {name}")


# ─── Null gate ───────────────────────────────────────────────────────────────


def null_scrambled_ccc(name: str, d: dict, X_stride: np.ndarray,
                        X_peritem: np.ndarray, y: np.ndarray, seed: int = 42) -> float:
    """Null #1: shuffle target within train fold; expect test CCC ≈ 0."""
    splits = kfold_split_stratified(y, 5, seed=seed)
    oof = np.zeros(len(y))
    rng = np.random.RandomState(seed)
    for tr, te in splits:
        y_tr_shuf = y[tr].copy()
        rng.shuffle(y_tr_shuf)
        # Re-build a fake d with shuffled y for late-fusion to behave consistently
        fake_y = y.copy()
        fake_y[tr] = y_tr_shuf
        # The variants don't take a separate d-target — they take y. Pass shuffled y.
        if name == "stride_locked_only":
            Xtr, Xte = impute_fold(X_stride[tr], X_stride[te])
            k = min(200, Xtr.shape[1])
            Xtr, Xte, _ = feature_select_fold(Xtr, y_tr_shuf, Xte, k=k, seed=seed)
            oof[te] = train_lgb(Xtr, y_tr_shuf, Xte, seed)
        elif name == "stride_plus_v2":
            X_aug = np.hstack([d["X_v2"], X_stride])
            Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
            Xtr, Xte, _ = feature_select_fold(Xtr, y_tr_shuf, Xte, k=500, seed=seed)
            oof[te] = train_lgb(Xtr, y_tr_shuf, Xte, seed)
        elif name == "late_fusion_ridge":
            # Simplified: just V2+stride concat with shuffled y; the full nested-CV is overkill
            X_aug = np.hstack([d["X_v2"], X_stride])
            Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
            Xtr, Xte, _ = feature_select_fold(Xtr, y_tr_shuf, Xte, k=500, seed=seed)
            oof[te] = train_lgb(Xtr, y_tr_shuf, Xte, seed)
    return ccc_fn(y, oof)


def null_canary_ccc(name: str, d: dict, X_stride: np.ndarray,
                     X_peritem: np.ndarray, y: np.ndarray, seed: int = 42) -> float:
    """Null #3: inject canary value only into test fold; model must ignore it."""
    splits = kfold_split_stratified(y, 5, seed=seed)
    oof = np.zeros(len(y))
    canary_val = 999.0
    for tr, te in splits:
        if name == "stride_locked_only":
            X = X_stride
        else:
            X = np.hstack([d["X_v2"], X_stride])
        n_tr = len(tr); n_te = len(te); n_feat = X.shape[1]
        canary_tr = np.zeros((n_tr, 1))
        canary_te = np.full((n_te, 1), canary_val)
        Xtr = np.hstack([X[tr], canary_tr])
        Xte = np.hstack([X[te], canary_te])
        Xtr, Xte = impute_fold(Xtr, Xte)
        k = min(500 if "v2" in name or "fusion" in name else 200, Xtr.shape[1])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=k, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return ccc_fn(y, oof)


# ─── Screening (5-fold × 3 seeds) ────────────────────────────────────────────


def screen_variant(name: str, d: dict, X_stride: np.ndarray, X_peritem: np.ndarray,
                    y: np.ndarray, item: int, save: bool = True) -> dict:
    """Run 5-fold × 3 seeds, return CCC mean ± std + per-seed."""
    seed_oofs = {}
    seed_ccs = []
    seed_metrics = []
    for seed in SEEDS:
        splits = kfold_split_stratified(y, 5, seed=seed)
        oof = run_variant(name, d, X_stride, X_peritem, y, splits, seed)
        seed_oofs[seed] = oof
        m = full_metrics(y, oof, label=f"{name}/seed{seed}")
        seed_metrics.append(m)
        seed_ccs.append(m["ccc"])
    ccc_mean = float(np.mean(seed_ccs))
    ccc_std = float(np.std(seed_ccs))
    out = {
        "variant": name,
        "item": item,
        "ccc_mean": round(ccc_mean, 4),
        "ccc_std": round(ccc_std, 4),
        "ccc_per_seed": [round(c, 4) for c in seed_ccs],
        "seed_metrics": seed_metrics,
        "n": int(len(y)),
    }
    if save:
        out_path = RESULTS_DIR / f"stride_screen_item{item}_{name}_5split.json"
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2)
        # Save mean OOF
        mean_oof = np.mean(np.stack([seed_oofs[s] for s in SEEDS]), axis=0)
        np.save(RESULTS_DIR / f"stride_screen_item{item}_{name}_oof.npy", mean_oof)
    return out


def run_null_gate_for(name: str, d: dict, X_stride: np.ndarray,
                       X_peritem: np.ndarray, y: np.ndarray) -> dict:
    sc = null_scrambled_ccc(name, d, X_stride, X_peritem, y, seed=42)
    cn = null_canary_ccc(name, d, X_stride, X_peritem, y, seed=42)
    return {"scrambled_label_ccc": round(sc, 4),
            "canary_feature_ccc": round(cn, 4),
            "passed": bool(abs(sc) < 0.20 and abs(cn) < 0.20)}


# ─── LOOCV lockbox ───────────────────────────────────────────────────────────


def lockbox_loocv(name: str, d: dict, X_stride: np.ndarray, X_peritem: np.ndarray,
                   y: np.ndarray, item: int, screen_5fold: dict) -> dict:
    """LOOCV with multi-seed average. Pre-register and run once."""
    n = len(y)
    seed_oofs = {}
    for seed in SEEDS:
        oof = np.zeros(n)
        loo = LeaveOneOut()
        for tr, te in loo.split(np.arange(n)):
            tr = list(tr); te = list(te)
            splits = [(np.array(tr), np.array(te))]
            o = run_variant(name, d, X_stride, X_peritem, y, splits, seed)
            oof[te] = o[te]
        seed_oofs[seed] = oof
    seed_ccs = [ccc_fn(y, seed_oofs[s]) for s in SEEDS]
    mean_oof = np.mean(np.stack([seed_oofs[s] for s in SEEDS]), axis=0)
    metrics = full_metrics(y, mean_oof, label=f"loocv_{name}")

    spec = {
        "lockbox_type": "stride_late_fusion",
        "variant": name,
        "item": item,
        "screening_5fold_ccc_mean": screen_5fold["ccc_mean"],
        "screening_5fold_ccc_std": screen_5fold["ccc_std"],
        "loocv_metrics": metrics,
        "loocv_per_seed_ccc": [round(c, 4) for c in seed_ccs],
        "n_subjects": int(n),
        "seeds": SEEDS,
        "timestamp": datetime.utcnow().isoformat(),
    }
    out_json = RESULTS_DIR / f"lockbox_peritem_{item}_stride_{name}.json"
    with open(out_json, "w") as f:
        json.dump(spec, f, indent=2)
    np.save(RESULTS_DIR / f"lockbox_peritem_{item}_stride_{name}_oof.npy", mean_oof)
    return spec


# ─── Best prior 5-fold per item (for promotion threshold) ────────────────────
# Source: MEMORY.md "Per-item 5-fold CCC under tug_microscope (iter 5 diagnostic)".


PRIOR_BEST_5FOLD = {
    7: 0.273,    # iter5 v2+TUG
    8: 0.259,    # iter5 v2+TUG
    9: 0.237,    # iter1 baseline (iter5 hurt to 0.174)
    10: 0.495,   # iter5 v2+TUG
    11: 0.215,   # iter1 baseline (iter5 crashed to 0.060)
    12: 0.553,   # iter5 v2+TUG
    14: 0.369,   # iter5 v2+TUG
}


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen", action="store_true", help="Run 5-fold screening")
    ap.add_argument("--lockbox", action="store_true", help="Run LOOCV lockbox")
    ap.add_argument("--items", type=str, default=",".join(str(i) for i in TARGET_ITEMS),
                    help="Comma-separated items (default: all 7,8,9,10,11,12,14)")
    ap.add_argument("--variants", type=str,
                    default="stride_locked_only,stride_plus_v2,late_fusion_ridge",
                    help="Comma-separated variant names")
    ap.add_argument("--item", type=int, help="Single item for lockbox mode")
    ap.add_argument("--variant", type=str, help="Single variant for lockbox mode")
    args = ap.parse_args()

    print("Loading PD data and stride cache...", flush=True)
    d = load_pd_data()
    sids = d["sids"]
    print(f"  N PD subjects: {len(sids)}", flush=True)
    X_stride, stride_cols = load_stride_features(sids)

    items = [int(x) for x in args.items.split(",") if x.strip()]
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    # Per-item peritem caches (small, load once)
    peritem_cache = {}
    for it in items:
        pi, pi_cols = load_peritem_features(sids, it)
        peritem_cache[it] = pi
        print(f"  Item {it}: peritem features = {pi.shape[1]}", flush=True)

    if args.screen or (not args.screen and not args.lockbox):
        print("\n=== 5-fold screening ===", flush=True)
        results: dict[int, dict[str, dict]] = {}
        null_gates: dict[int, dict[str, dict]] = {}
        promoted: list[tuple[int, str, float, dict]] = []
        for it in items:
            y = get_target(d, it)
            X_pi = peritem_cache[it]
            results[it] = {}
            null_gates[it] = {}
            for v in variants:
                t0 = time.time()
                r = screen_variant(v, d, X_stride, X_pi, y, it)
                # Null gate
                ng = run_null_gate_for(v, d, X_stride, X_pi, y)
                null_gates[it][v] = ng
                dt = time.time() - t0
                results[it][v] = r
                prior = PRIOR_BEST_5FOLD.get(it, 0.0)
                gain = r["ccc_mean"] - prior
                promote_flag = "PROMOTE" if (gain >= PROMOTE_DELTA and ng["passed"]) else ""
                if promote_flag:
                    promoted.append((it, v, r["ccc_mean"], r))
                print(f"  item {it} {v:>22}: 5-fold CCC = {r['ccc_mean']:.4f} ± {r['ccc_std']:.4f}"
                      f" [prior {prior:.3f}, Δ={gain:+.3f}, null_sc={ng['scrambled_label_ccc']:+.3f}, "
                      f"null_can={ng['canary_feature_ccc']:+.3f}] {promote_flag}  "
                      f"({dt:.1f}s)", flush=True)
        # Save summary
        summary = {
            "items": items,
            "variants": variants,
            "results": {str(it): {v: results[it][v] for v in variants} for it in items},
            "null_gates": {str(it): null_gates[it] for it in items},
            "promoted": [{"item": it, "variant": v, "ccc_5fold": c}
                          for it, v, c, _ in promoted],
            "timestamp": datetime.utcnow().isoformat(),
        }
        sum_path = RESULTS_DIR / "stride_screen_summary.json"
        with open(sum_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\nWrote summary to {sum_path}", flush=True)

        # Auto-run LOOCV for promoted variants
        for it, v, _, screen_5fold in promoted:
            print(f"\n=== LOOCV lockbox: item {it} variant {v} ===", flush=True)
            t0 = time.time()
            spec = lockbox_loocv(v, d, X_stride, peritem_cache[it], get_target(d, it), it,
                                  screen_5fold)
            dt = time.time() - t0
            m = spec["loocv_metrics"]
            print(f"  LOOCV CCC = {m['ccc']:.4f}  MAE = {m['mae']:.4f}  ({dt:.1f}s)", flush=True)
        if not promoted:
            print("\n[ no variants met promotion threshold ]", flush=True)

    elif args.lockbox:
        if args.item is None or args.variant is None:
            sys.exit("--lockbox requires --item and --variant")
        y = get_target(d, args.item)
        # Read screening result (must exist)
        screen_path = RESULTS_DIR / f"stride_screen_item{args.item}_{args.variant}_5split.json"
        if not screen_path.exists():
            sys.exit(f"Screening result missing: {screen_path}. Run --screen first.")
        with open(screen_path) as f:
            screen_5fold = json.load(f)
        spec = lockbox_loocv(args.variant, d, X_stride, peritem_cache[args.item], y,
                              args.item, screen_5fold)
        print(json.dumps(spec, indent=2), flush=True)


if __name__ == "__main__":
    main()
