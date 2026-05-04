"""Run fusion-method screening: cross-sensor coherence + Mahalanobis-to-HC.

Two new sensor-fusion feature sets that have NEVER been tried in this project:

  1. Cross-sensor frequency-domain coherence (cache_cross_sensor_coherence.py)
     → results/cross_sensor_coherence.csv
     ~30-60 features per subject, magnitude-squared coherence between clinically-
     meaningful sensor pairs at gait fundamental + 2nd harmonic + integrated band.

  2. Mahalanobis distance to HC manifold (cache_mahalanobis_hc.py)
     → results/mahalanobis_hc_subj.csv
     ~30-50 features per subject, robust covariance fit on HC-only feature space
     per-task, distance computed for each PD subject. HC stats are computed ONCE
     from all 80 HC and never enter PD train/test splits → not a leak.

Variants (per item ∈ {7, 8, 9, 10, 11, 12, 14, 18}):

  coherence_only                       LGB on coherence features only
  coherence_plus_v2                    LGB on coherence + V2
  mahalanobis_only                     LGB on Mahalanobis features only
  mahalanobis_plus_v2                  LGB on Mahalanobis + V2
  coherence_plus_mahalanobis_plus_v2   all combined
  late_fusion_coh_mah_v2               Ridge meta over OOFs of (coh, mah, v2) base learners

Eval: 5-fold × 3 seeds for screening; LOOCV lockbox if any variant beats prior best
by +0.015 with null-pass.

5-null gate per variant (per spec):
  - scrambled-label (target permutation)
  - canary feature (gaussian noise injection into V2)
  - SID-shuffle on the new caches (decouples cache from PD targets)

Usage:
  python3 run_fusion_methods.py --eval 5split
  python3 run_fusion_methods.py --eval 5split --items 9 10 12 14
  python3 run_fusion_methods.py --eval loocv --variant coherence_plus_v2 --item 12
  python3 run_fusion_methods.py --pre_lockbox <item> <variant>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    load_pd_data, kfold_split_stratified, impute_fold,
    feature_select_fold, train_lgb, SEEDS,
)

COH_CACHE = RESULTS_DIR / "cross_sensor_coherence.csv"
MAH_CACHE = RESULTS_DIR / "mahalanobis_hc_subj.csv"
PRIOR_BEST = {
    # Best 5-fold across prior peritem_v2 variants per item (results/peritem_v2_screening_5split.csv).
    # These are the most apples-to-apples comparisons for the new fusion variants.
    7: 0.303,   # item_plus_v2
    8: 0.234,   # item_plus_v2
    9: 0.323,   # hy_residual_item
    10: 0.526,  # item_plus_v2
    11: 0.319,  # item_dedicated
    12: 0.555,  # item_plus_v2
    14: 0.297,  # item_plus_v2
    18: 0.400,  # hy_residual_item
}
TARGET_ITEMS = (7, 8, 9, 10, 11, 12, 14, 18)
LOCKBOX_THRESHOLD = 0.015


# ── Cache loading ───────────────────────────────────────────────────────────


def load_cache_aligned(path: Path, sids: np.ndarray) -> tuple[np.ndarray, list[str], int]:
    """Load a per-subject cache CSV, align rows with `sids`. Missing → NaN.

    Returns (X, feat_cols, n_matched).
    """
    if not path.exists():
        raise FileNotFoundError(f"Cache missing: {path}")
    df = pd.read_csv(path)
    df = df.set_index("sid")
    feat_cols = list(df.columns)
    n = len(sids)
    X = np.full((n, len(feat_cols)), np.nan, dtype=np.float64)
    matched = 0
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, feat_cols].to_numpy(dtype=np.float64)
            matched += 1
    return X, feat_cols, matched


def load_data_fusion() -> dict:
    """Load PD data + coherence + Mahalanobis caches."""
    d = load_pd_data()
    print(f"  PD N={len(d['sids'])}, V2 dim={d['X_v2'].shape[1]}", flush=True)
    X_coh, coh_cols, n_coh = load_cache_aligned(COH_CACHE, d["sids"])
    print(f"  Coherence: matched {n_coh}/{len(d['sids'])} subjects, "
          f"{len(coh_cols)} features", flush=True)
    X_mah, mah_cols, n_mah = load_cache_aligned(MAH_CACHE, d["sids"])
    print(f"  Mahalanobis: matched {n_mah}/{len(d['sids'])} subjects, "
          f"{len(mah_cols)} features", flush=True)
    d["X_coh"] = X_coh
    d["coh_cols"] = coh_cols
    d["X_mah"] = X_mah
    d["mah_cols"] = mah_cols
    return d


# ── Variants ─────────────────────────────────────────────────────────────────


def _train_lgb_oof(d: dict, X: np.ndarray, y: np.ndarray,
                   splits, seed: int, k: int = 500) -> np.ndarray:
    n = len(y)
    oof = np.zeros(n, dtype=np.float64)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=k, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_coherence_only(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    y = d["items"][item]
    return _train_lgb_oof(d, d["X_coh"], y, splits, seed,
                          k=min(500, d["X_coh"].shape[1]))


def variant_coherence_plus_v2(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    y = d["items"][item]
    X = np.hstack([d["X_v2"], d["X_coh"]])
    return _train_lgb_oof(d, X, y, splits, seed)


def variant_mahalanobis_only(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    y = d["items"][item]
    return _train_lgb_oof(d, d["X_mah"], y, splits, seed,
                          k=min(500, d["X_mah"].shape[1]))


def variant_mahalanobis_plus_v2(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    y = d["items"][item]
    X = np.hstack([d["X_v2"], d["X_mah"]])
    return _train_lgb_oof(d, X, y, splits, seed)


def variant_coh_plus_mah_plus_v2(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    y = d["items"][item]
    X = np.hstack([d["X_v2"], d["X_coh"], d["X_mah"]])
    return _train_lgb_oof(d, X, y, splits, seed)


def variant_late_fusion(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Stack OOFs of (coh-only, mah-only, V2-only) via Ridge meta on inner OOFs.

    Implemented properly to avoid leakage: for each outer test fold, fit each
    base learner on the outer-train block; produce OOFs on outer-train via inner
    K=3 split; train Ridge meta on those inner OOFs vs y[outer-train]; then
    predict each base on outer-test, push through Ridge.
    """
    y = d["items"][item]
    n = len(y)
    oof = np.zeros(n, dtype=np.float64)

    def base_oof_for_train(X: np.ndarray, y_tr: np.ndarray, seed_in: int,
                           k: int = 500) -> tuple[np.ndarray, callable]:
        """Return inner-OOF for train block + a final-model-predict callable."""
        n_tr = len(y_tr)
        inner = kfold_split_stratified(y_tr, 3, seed=seed_in)
        inner_oof = np.zeros(n_tr, dtype=np.float64)
        for itr, ite in inner:
            Xitr, Xite = impute_fold(X[itr], X[ite])
            Xitr, Xite, _ = feature_select_fold(Xitr, y_tr[itr], Xite,
                                                k=min(k, X.shape[1]), seed=seed_in)
            inner_oof[ite] = train_lgb(Xitr, y_tr[itr], Xite, seed_in)
        # Final model on full train block
        def final_predict(Xte_outer: np.ndarray) -> np.ndarray:
            Xtr_full, Xte_full = impute_fold(X, Xte_outer)
            Xtr_sel, Xte_sel, _ = feature_select_fold(
                Xtr_full, y_tr, Xte_full, k=min(k, X.shape[1]), seed=seed_in)
            return train_lgb(Xtr_sel, y_tr, Xte_sel, seed_in)
        return inner_oof, final_predict

    for tr, te in splits:
        y_tr = y[tr]
        # Compute inner OOFs and final predictors for each base
        coh_oof, coh_final = base_oof_for_train(d["X_coh"][tr], y_tr, seed)
        mah_oof, mah_final = base_oof_for_train(d["X_mah"][tr], y_tr, seed)
        v2_oof,  v2_final  = base_oof_for_train(d["X_v2"][tr],  y_tr, seed)
        # Ridge meta on inner OOFs
        Z_tr = np.column_stack([coh_oof, mah_oof, v2_oof])
        meta = Ridge(alpha=1.0, random_state=seed)
        meta.fit(Z_tr, y_tr)
        # Predict outer-test via each base, then meta
        coh_te = coh_final(d["X_coh"][te])
        mah_te = mah_final(d["X_mah"][te])
        v2_te  = v2_final(d["X_v2"][te])
        Z_te = np.column_stack([coh_te, mah_te, v2_te])
        oof[te] = meta.predict(Z_te)
    return oof


VARIANTS = {
    "coherence_only": variant_coherence_only,
    "coherence_plus_v2": variant_coherence_plus_v2,
    "mahalanobis_only": variant_mahalanobis_only,
    "mahalanobis_plus_v2": variant_mahalanobis_plus_v2,
    "coherence_plus_mahalanobis_plus_v2": variant_coh_plus_mah_plus_v2,
    "late_fusion_coh_mah_v2": variant_late_fusion,
}


# ── 5-null gate ─────────────────────────────────────────────────────────────


def run_5null_gate(d: dict, item: int, variant: str, seed: int = 42) -> dict:
    """Three null tests: scrambled-label, canary feature, SID-shuffle on caches."""
    y = d["items"][item]
    splits = kfold_split_stratified(y, 5, seed=seed)
    fn = VARIANTS[variant]
    null: dict = {}
    rng = np.random.RandomState(seed)
    # 1. Scrambled-label
    try:
        y_scram = rng.permutation(y)
        d2 = {**d, "items": {**d["items"], item: y_scram}}
        oof_s = fn(d2, item, splits, seed)
        null["scrambled_label_ccc"] = float(ccc_fn(y_scram, oof_s))
    except Exception as e:  # noqa: BLE001
        null["scrambled_label_error"] = str(e)
    # 2. Canary feature (injected into V2)
    try:
        canary = rng.randn(len(y))
        d3 = {**d, "X_v2": np.hstack([d["X_v2"], canary[:, None]])}
        oof_c = fn(d3, item, splits, seed)
        null["canary_feature_ccc"] = float(ccc_fn(y, oof_c))
    except Exception as e:  # noqa: BLE001
        null["canary_feature_error"] = str(e)
    # 3. SID-shuffle on coherence + mahalanobis caches (decouples them from y)
    try:
        perm = rng.permutation(len(y))
        d4 = {**d, "X_coh": d["X_coh"][perm], "X_mah": d["X_mah"][perm]}
        oof_p = fn(d4, item, splits, seed)
        null["sid_shuffle_caches_ccc"] = float(ccc_fn(y, oof_p))
    except Exception as e:  # noqa: BLE001
        null["sid_shuffle_caches_error"] = str(e)
    return null


# ── Driver ──────────────────────────────────────────────────────────────────


def filter_nan_target(d: dict, item: int) -> dict:
    y = d["items"][item]
    nan_mask = np.isnan(y)
    if not nan_mask.any():
        return d
    valid = np.where(~nan_mask)[0]
    out = {
        "sids": d["sids"][valid],
        "X_v2": d["X_v2"][valid],
        "X_coh": d["X_coh"][valid],
        "X_mah": d["X_mah"][valid],
        "coh_cols": d["coh_cols"],
        "mah_cols": d["mah_cols"],
        "feat_cols": d["feat_cols"],
        "hy": d["hy"][valid],
        "items": {k: (v[valid] if isinstance(v, np.ndarray) else v)
                  for k, v in d["items"].items()},
        "t1": d["t1"][valid],
    }
    return out


def run_one(d: dict, item: int, variant: str, eval_kind: str,
            seeds=SEEDS, with_null: bool = True) -> dict:
    d_f = filter_nan_target(d, item)
    y = d_f["items"][item]
    n = len(y)
    if eval_kind == "5split":
        per_seed = []
        for s in seeds:
            splits = kfold_split_stratified(y, 5, seed=s)
            oof = VARIANTS[variant](d_f, item, splits, s)
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
        splits = [(np.array([j for j in range(n) if j != i]), np.array([i]))
                  for i in range(n)]
        per_seed = []
        oof_acc = np.zeros(n, dtype=np.float64)
        for s in seeds:
            oof_s = VARIANTS[variant](d_f, item, splits, s)
            per_seed.append(full_metrics(y, oof_s))
            oof_acc += oof_s
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
        out["null_tests"] = run_5null_gate(d_f, item, variant, seed=seeds[0])
    return out


def screen_all(d: dict, items: tuple[int, ...], eval_kind: str,
               seeds=SEEDS, out_dir: Path = RESULTS_DIR) -> Path:
    rows: list[dict] = []
    out_csv = out_dir / f"fusion_methods_screening_{eval_kind}.csv"
    t0 = time.time()
    for item in items:
        for variant in VARIANTS:
            print(f"[fusion] item={item} variant={variant}", flush=True)
            try:
                r = run_one(d, item, variant, eval_kind, seeds=seeds,
                            with_null=(eval_kind == "5split"))
            except Exception as e:  # noqa: BLE001
                r = {"item": item, "variant": variant, "eval": eval_kind,
                     "error": str(e)}
            # Save individual JSON
            ip = out_dir / f"fusion_item{item}_{variant}_{eval_kind}.json"
            with open(ip, "w") as f:
                json.dump(r, f, indent=2)
            # Save OOF array if present (LOOCV)
            if "_oof_array" in r:
                np.save(out_dir / f"fusion_item{item}_{variant}_{eval_kind}_oof.npy",
                        np.asarray(r["_oof_array"], dtype=np.float64))
            row = {
                "item": item, "variant": variant,
                "ccc_mean": r.get("ccc_mean", np.nan),
                "ccc_std": r.get("ccc_std", np.nan),
                "mae_mean": r.get("mae_mean", np.nan),
                "n_subjects": r.get("n_subjects"),
                "error": r.get("error"),
            }
            if "null_tests" in r:
                row.update({
                    f"null_{k}": v for k, v in r["null_tests"].items()
                })
            rows.append(row)
            print(f"[fusion]   ccc={row['ccc_mean']:.4f} ± {row['ccc_std']:.4f} "
                  f"({time.time()-t0:.0f}s elapsed)", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    print(f"[fusion] Wrote {out_csv}", flush=True)
    # Print leaderboard
    df["prior_best"] = df["item"].map(PRIOR_BEST)
    df["delta"] = df["ccc_mean"] - df["prior_best"]
    print("\n[fusion] === Leaderboard (by item, top variant) ===", flush=True)
    for item in items:
        sub = df[df["item"] == item].copy()
        sub = sub.sort_values("ccc_mean", ascending=False).head(3)
        print(f"  item {item} (prior best={PRIOR_BEST.get(item):.3f}):", flush=True)
        for _, r in sub.iterrows():
            print(f"    {r['variant']:<40s} ccc={r['ccc_mean']:.4f} "
                  f"Δ={r['delta']:+.4f}", flush=True)
    # Lockbox candidates
    cands = df[df["delta"] >= LOCKBOX_THRESHOLD].copy()
    if not cands.empty:
        print(f"\n[fusion] {len(cands)} variant(s) clear the +{LOCKBOX_THRESHOLD:.3f} "
              "lockbox threshold (5-fold). Verify nulls before LOOCV:", flush=True)
        for _, r in cands.iterrows():
            n_scram = r.get("null_scrambled_label_ccc", np.nan)
            n_canary = r.get("null_canary_feature_ccc", np.nan)
            n_sid = r.get("null_sid_shuffle_caches_ccc", np.nan)
            print(f"  item={int(r['item'])} variant={r['variant']} "
                  f"ccc={r['ccc_mean']:.4f} (Δ{r['delta']:+.4f}) "
                  f"nulls: scram={n_scram:.3f} canary={n_canary:.3f} "
                  f"sid={n_sid:.3f}", flush=True)
    else:
        print("\n[fusion] No variants beat prior best by the lockbox threshold.",
              flush=True)
    return out_csv


def lockbox(d: dict, item: int, variant: str, seeds=SEEDS,
            out_dir: Path = RESULTS_DIR) -> dict:
    """Pre-register and run LOOCV exactly once on a 5-fold winner."""
    d_f = filter_nan_target(d, item)
    y = d_f["items"][item]
    n = len(y)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pre_reg = {
        "timestamp_utc": timestamp,
        "item": item,
        "variant": variant,
        "n_subjects": int(n),
        "seeds": list(seeds),
        "eval": "loocv",
        "lockbox_threshold": LOCKBOX_THRESHOLD,
        "prior_best_5fold": PRIOR_BEST.get(item),
    }
    pre_path = out_dir / f"preregistration_fusion_item{item}_{variant}_{timestamp}.json"
    with open(pre_path, "w") as f:
        json.dump(pre_reg, f, indent=2)
    print(f"[fusion] Pre-registered: {pre_path}", flush=True)
    r = run_one(d_f, item, variant, "loocv", seeds=seeds, with_null=False)
    out_path = out_dir / (
        f"lockbox_fusion_item{item}_{variant}_loocv_{timestamp}.json"
    )
    with open(out_path, "w") as f:
        json.dump(r, f, indent=2)
    if "_oof_array" in r:
        np.save(out_dir / f"lockbox_fusion_item{item}_{variant}_loocv_oof.npy",
                np.asarray(r["_oof_array"], dtype=np.float64))
    print(f"[fusion] Lockbox result: ccc={r['ccc_mean']:.4f} ± {r['ccc_std']:.4f} "
          f"mae={r['mae_mean']:.3f}", flush=True)
    print(f"[fusion] Wrote {out_path}", flush=True)
    return r


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--eval", choices=["5split", "loocv"], default="5split")
    p.add_argument("--items", type=int, nargs="*", default=None,
                   help="Items to screen (default: 7 8 9 10 11 12 14 18)")
    p.add_argument("--variant", type=str, default="",
                   help="Run a single variant (used with --item)")
    p.add_argument("--item", type=int, default=0,
                   help="Single item (used with --variant)")
    p.add_argument("--lockbox", action="store_true",
                   help="LOOCV lockbox runner (use with --item, --variant)")
    p.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    args = p.parse_args()

    print(f"[fusion] Loading data... eval={args.eval}", flush=True)
    d = load_data_fusion()

    if args.lockbox:
        if not args.variant or not args.item:
            print("ERROR: --lockbox needs --item and --variant", file=sys.stderr)
            return 2
        lockbox(d, args.item, args.variant, seeds=tuple(args.seeds))
        return 0

    if args.variant and args.item:
        r = run_one(d, args.item, args.variant, args.eval,
                    seeds=tuple(args.seeds))
        out_path = RESULTS_DIR / (
            f"fusion_item{args.item}_{args.variant}_{args.eval}.json"
        )
        with open(out_path, "w") as f:
            json.dump(r, f, indent=2)
        if "_oof_array" in r:
            np.save(RESULTS_DIR / (
                f"fusion_item{args.item}_{args.variant}_{args.eval}_oof.npy"
            ), np.asarray(r["_oof_array"], dtype=np.float64))
        print(f"[fusion] Wrote {out_path}", flush=True)
        print(f"[fusion] ccc={r['ccc_mean']:.4f} ± {r['ccc_std']:.4f}", flush=True)
        return 0

    items = tuple(args.items) if args.items else TARGET_ITEMS
    screen_all(d, items, args.eval, seeds=tuple(args.seeds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
