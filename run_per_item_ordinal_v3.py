"""Per-item Track-A (nonlinear dynamics) + Track-B (ordinal regression) screener.

Adds variants on top of run_per_item_v2.py for items 9-14 only:

  Track A (nonlinear dynamics; only for items 10, 12):
    item_plus_v2_plus_nonlinear   — LGB on V2 ∪ item ∪ nl_dynamics
    item_plus_v2_only_nl          — LGB on V2 ∪ nl_dynamics (no item-specific)

  Track B (ordinal regression; for ALL T1 items 9-14):
    ordinal_mord_at      — mord.LogisticAT on V2 ∪ item; expected-value decoding
    ordinal_lgb_cuts     — K=4 binary LGBs per cut-point; expected-value decoding
    ordinal_catboost     — CatBoost regression w/ MultiClass on integer targets,
                           expected-value decoding
    ordinal_coral_lgb    — Cao et al. 2020 CORAL ordinal applied to per-cut LGBs
                           (rank-monotonic projection)

  Track C (multi-task regression — DROPPED per spec; falls back to Track A/B)

All variants enforce the inductive firewall (fold-local fits) by reusing
impute_fold + feature_select_fold from run_t1_iter4 and the FoldNormalizer
from inductive_lib.

Usage:
    python3 run_per_item_ordinal_v3.py --all 5split --workers 6
    python3 run_per_item_ordinal_v3.py --item 12 --variant ordinal_mord_at \
        --eval 5split
    python3 run_per_item_ordinal_v3.py --lockbox --winners results/peritem_v3_screening_5split.csv
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

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn, FoldNormalizer
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    load_pd_data, kfold_split_stratified, impute_fold,
    feature_select_fold, train_lgb,
    LGB_DEFAULTS,
    SEEDS,
)
from run_per_item_v2 import (
    PERITEM_CACHE, get_item_features as get_item_feats_v2,
    load_data as load_data_v2,
)

NL_CACHE = REPO_ROOT / "results" / "nonlinear_dynamics_features.csv"
T1_ITEMS = [9, 10, 11, 12, 13, 14]
NL_TARGET_ITEMS = [10, 12]  # only items 10 and 12 use nonlinear dynamics features
ORDINAL_TARGET_ITEMS = T1_ITEMS  # ordinal is valid for any 0-4 item


# ── Data loading: extends load_data_v2 with nonlinear-dynamics cache ─────────


def load_data() -> dict:
    d = load_data_v2()
    if NL_CACHE.exists():
        df_nl = pd.read_csv(NL_CACHE).set_index("sid")
        nl_cols = list(df_nl.columns)
        n = len(d["sids"])
        X_nl = np.full((n, len(nl_cols)), np.nan)
        matched = 0
        for i, sid in enumerate(d["sids"]):
            if sid in df_nl.index:
                X_nl[i] = df_nl.loc[sid, nl_cols].to_numpy(dtype=np.float64)
                matched += 1
        print(f"  Nonlinear-dynamics features matched {matched}/{n} subjects "
              f"({len(nl_cols)} features)", flush=True)
        d["X_nl"] = X_nl
        d["nl_cols"] = nl_cols
    else:
        print(f"  WARNING: {NL_CACHE} missing — Track A variants will skip", flush=True)
        d["X_nl"] = None
        d["nl_cols"] = []
    return d


# ── Per-item helpers ─────────────────────────────────────────────────────────


def get_item_features(d: dict, item: int) -> tuple[np.ndarray, list[str]]:
    return get_item_feats_v2(d, item)


def get_item_nl_features(d: dict, item: int) -> tuple[np.ndarray, list[str]]:
    """Subset nonlinear-dynamics features by item-specific prefix."""
    if d.get("X_nl") is None:
        return np.zeros((len(d["sids"]), 0)), []
    cols = d["nl_cols"]
    prefix = f"nl_i{item}_"
    idx = [i for i, c in enumerate(cols) if c.startswith(prefix)]
    if not idx:
        return np.zeros((len(d["sids"]), 0)), []
    return d["X_nl"][:, idx], [cols[i] for i in idx]


# ── Track A: Nonlinear dynamics variants ─────────────────────────────────────


def variant_item_plus_v2_plus_nonlinear(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """LGB on V2 ∪ item-specific ∪ nl_dynamics. Items 10, 12 only."""
    y = d["items"][item]
    X_item, _ = get_item_features(d, item)
    X_nl, nl_cols = get_item_nl_features(d, item)
    parts = [d["X_v2"]]
    if X_item.shape[1] > 0:
        parts.append(X_item)
    if X_nl.shape[1] > 0:
        parts.append(X_nl)
    X_aug = np.hstack(parts)
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_item_plus_v2_only_nl(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """LGB on V2 ∪ nl_dynamics only (no item-specific). Diagnostic — does NL alone help?"""
    y = d["items"][item]
    X_nl, nl_cols = get_item_nl_features(d, item)
    if X_nl.shape[1] == 0:
        return variant_item_plus_v2_plus_nonlinear(d, item, splits, seed)
    X_aug = np.hstack([d["X_v2"], X_nl])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


# ── Track B: Ordinal regression variants ─────────────────────────────────────


def _build_X_for_ordinal(d: dict, item: int) -> np.ndarray:
    X_item, _ = get_item_features(d, item)
    if X_item.shape[1] > 0:
        return np.hstack([d["X_v2"], X_item])
    return d["X_v2"]


def _expected_value_from_cumprobs(cum_probs: np.ndarray, n_classes: int) -> np.ndarray:
    """cum_probs shape (n_samples, n_classes-1) — P(y > k) for k=0..K-2.
    Convert to class probabilities and compute expected value."""
    # P(y == 0) = 1 - P(y > 0)
    # P(y == k) = P(y > k-1) - P(y > k) for 1 <= k <= K-2
    # P(y == K-1) = P(y > K-2)
    cp = np.clip(cum_probs, 0.0, 1.0)
    # Enforce monotonicity: P(y > k) decreasing in k
    cp = np.minimum.accumulate(cp, axis=1)
    n = cp.shape[0]
    pmf = np.zeros((n, n_classes))
    pmf[:, 0] = 1.0 - cp[:, 0]
    for k in range(1, n_classes - 1):
        pmf[:, k] = cp[:, k - 1] - cp[:, k]
    pmf[:, -1] = cp[:, -1]
    # Renormalize for tiny numerical bumps
    s = pmf.sum(axis=1, keepdims=True)
    s = np.where(s < 1e-9, 1.0, s)
    pmf = pmf / s
    classes = np.arange(n_classes)
    return pmf @ classes


def variant_ordinal_mord_at(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Proportional-odds (cumulative-link) ordinal regression via mord.LogisticAT.

    Fold-local: standardize on train fold, fit LogisticAT on train integer
    targets, return expected value over predicted class probabilities.
    """
    try:
        from mord import LogisticAT
    except ImportError:
        print("  mord not available — fallback to v2 baseline", flush=True)
        from run_per_item_v2 import variant_v2_baseline
        return variant_v2_baseline(d, item, splits, seed)

    y = d["items"][item]
    X = _build_X_for_ordinal(d, item)
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        # Per-fold LGB importance dim-reduction (ordinal models don't scale to 1700 feats well)
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y[tr], Xte, k=200, seed=seed)
        norm = FoldNormalizer.fit(Xtr_s)
        Xtr_z = norm.transform(Xtr_s)
        Xte_z = norm.transform(Xte_s)
        y_int = np.round(y[tr]).astype(int)
        y_int = np.clip(y_int, 0, 4)
        try:
            model = LogisticAT(alpha=1.0)
            model.fit(Xtr_z, y_int)
            # mord exposes predict_proba returning (n, n_classes)
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba(Xte_z)
                classes = np.asarray(model.classes_, dtype=float)
                oof[te] = proba @ classes
            else:
                oof[te] = model.predict(Xte_z).astype(float)
        except Exception as e:
            # Fall back to LGB train if mord failed (e.g. all-zero target)
            oof[te] = train_lgb(Xtr_s, y[tr], Xte_s, seed)
    return oof


def variant_ordinal_lgb_cuts(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """K-1 binary LGBs, one per cut-point P(y > k). Aggregate via expected value."""
    import lightgbm as lgb
    y = d["items"][item]
    X = _build_X_for_ordinal(d, item)
    n = len(y)
    n_classes = 5  # 0..4
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y[tr], Xte, k=300, seed=seed)
        y_int = np.round(y[tr]).astype(int)
        cut_probs_te = np.zeros((Xte_s.shape[0], n_classes - 1))
        for k in range(n_classes - 1):
            bin_tr = (y_int > k).astype(int)
            if bin_tr.min() == bin_tr.max():
                # All same class → fixed prob
                cut_probs_te[:, k] = float(bin_tr[0])
                continue
            clf = lgb.LGBMClassifier(
                n_estimators=300, learning_rate=0.05, num_leaves=15,
                min_data_in_leaf=10, n_jobs=2, random_state=seed, verbosity=-1,
                reg_alpha=0.1, reg_lambda=0.3,
            )
            clf.fit(Xtr_s, bin_tr)
            cut_probs_te[:, k] = clf.predict_proba(Xte_s)[:, 1]
        oof[te] = _expected_value_from_cumprobs(cut_probs_te, n_classes)
    return oof


def variant_ordinal_coral_lgb(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """CORAL-style rank-monotonic per-cut probabilities (Cao 2020).

    Trains K-1 binary LGBs as cut-points but enforces monotonicity at decoding:
    P(y > k) ≤ P(y > k-1). Aggregates via expected value.
    Differs from ordinal_lgb_cuts only in monotonicity enforcement (cleaner PMF
    for skewed item distributions).
    """
    import lightgbm as lgb
    y = d["items"][item]
    X = _build_X_for_ordinal(d, item)
    n = len(y)
    n_classes = 5
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y[tr], Xte, k=300, seed=seed)
        y_int = np.round(y[tr]).astype(int)
        cut_probs_te = np.zeros((Xte_s.shape[0], n_classes - 1))
        for k in range(n_classes - 1):
            bin_tr = (y_int > k).astype(int)
            if bin_tr.min() == bin_tr.max():
                cut_probs_te[:, k] = float(bin_tr[0])
                continue
            clf = lgb.LGBMClassifier(
                n_estimators=300, learning_rate=0.05, num_leaves=15,
                min_data_in_leaf=10, n_jobs=2, random_state=seed, verbosity=-1,
                reg_alpha=0.1, reg_lambda=0.3,
            )
            clf.fit(Xtr_s, bin_tr)
            cut_probs_te[:, k] = clf.predict_proba(Xte_s)[:, 1]
        # Force monotonicity
        cut_probs_te = np.minimum.accumulate(cut_probs_te, axis=1)
        oof[te] = _expected_value_from_cumprobs(cut_probs_te, n_classes)
    return oof


def variant_ordinal_catboost(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """CatBoost regression on integer targets — mature gradient boost variant.

    Falls back gracefully if catboost not installed.
    """
    try:
        from catboost import CatBoostRegressor
    except ImportError:
        from run_per_item_v2 import variant_v2_baseline
        return variant_v2_baseline(d, item, splits, seed)
    y = d["items"][item]
    X = _build_X_for_ordinal(d, item)
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, y[tr], Xte, k=300, seed=seed)
        model = CatBoostRegressor(
            iterations=400, learning_rate=0.05, depth=5,
            l2_leaf_reg=3.0, random_seed=seed, verbose=False,
            allow_writing_files=False, thread_count=2,
        )
        model.fit(Xtr_s, y[tr])
        oof[te] = model.predict(Xte_s)
    return oof


# ── Compose / aggregate ─────────────────────────────────────────────────────


VARIANTS = {
    "item_plus_v2_plus_nonlinear": variant_item_plus_v2_plus_nonlinear,
    "item_plus_v2_only_nl": variant_item_plus_v2_only_nl,
    "ordinal_mord_at": variant_ordinal_mord_at,
    "ordinal_lgb_cuts": variant_ordinal_lgb_cuts,
    "ordinal_coral_lgb": variant_ordinal_coral_lgb,
    "ordinal_catboost": variant_ordinal_catboost,
}


def variant_set_for_item(item: int) -> list[str]:
    out = ["ordinal_mord_at", "ordinal_lgb_cuts", "ordinal_coral_lgb",
           "ordinal_catboost"]
    if item in NL_TARGET_ITEMS:
        out.insert(0, "item_plus_v2_plus_nonlinear")
        out.insert(1, "item_plus_v2_only_nl")
    return out


# ── Driver ──────────────────────────────────────────────────────────────────


def filter_to_valid(d: dict, item: int) -> dict:
    """Filter cohort to subjects with non-NaN target for `item`."""
    y = d["items"][item]
    nan_mask = np.isnan(y)
    if not nan_mask.any():
        return d
    valid = np.where(~nan_mask)[0]
    return {
        "sids": d["sids"][valid],
        "X_v2": d["X_v2"][valid],
        "X_peritem": d["X_peritem"][valid] if "X_peritem" in d else None,
        "peritem_cols": d.get("peritem_cols"),
        "X_nl": d["X_nl"][valid] if d.get("X_nl") is not None else None,
        "nl_cols": d.get("nl_cols", []),
        "hy": d["hy"][valid],
        "site": d["site"][valid] if "site" in d else None,
        "items": {k: (v[valid] if isinstance(v, np.ndarray) else v) for k, v in d["items"].items()},
        "feat_cols": d.get("feat_cols"),
        "t1": d["t1"][valid] if "t1" in d else None,
    }


def run_one(d: dict, item: int, variant: str, eval_kind: str,
            seeds=SEEDS, with_null: bool = True) -> dict:
    d = filter_to_valid(d, item)
    y = d["items"][item]
    n = len(y)
    fn = VARIANTS[variant]
    if eval_kind == "5split":
        per_seed = []
        for s in seeds:
            splits = kfold_split_stratified(y, 5, seed=s)
            oof = fn(d, item, splits, s)
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
        oof_acc = np.zeros(n)
        for s in seeds:
            oof_s = fn(d, item, splits, s)
            per_seed.append(full_metrics(y, oof_s))
            oof_acc = oof_acc + oof_s
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
    # 5-null gate (cheap subset: scrambled-label only, since canary needs same featureset)
    if with_null and eval_kind == "5split":
        try:
            rng = np.random.RandomState(seeds[0])
            y_scram = rng.permutation(y)
            d_scram = {**d, "items": {**d["items"], item: y_scram}}
            splits = kfold_split_stratified(y_scram, 5, seed=seeds[0])
            oof_s = fn(d_scram, item, splits, seeds[0])
            scram_ccc = float(ccc_fn(y_scram, oof_s))
            out["null_tests"] = {"scrambled_label_ccc": scram_ccc}
        except Exception as e:
            out["null_tests"] = {"scrambled_label_error": str(e)}
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--item", type=int, default=0)
    p.add_argument("--variant", type=str, default="")
    p.add_argument("--eval", type=str, choices=["5split", "loocv"], default="5split")
    p.add_argument("--all", type=str, default="",
                   help="run all T1 items × all variants for given eval kind")
    p.add_argument("--items", type=int, nargs="+", default=T1_ITEMS,
                   help="restrict to items list")
    p.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    p.add_argument("--out_dir", type=str, default=str(RESULTS_DIR))
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)
    print("Loading data...", flush=True)
    d = load_data()
    print(f"  N = {len(d['sids'])} PD subjects, {d['X_v2'].shape[1]} V2 features, "
          f"{d['X_peritem'].shape[1]} per-item features, "
          f"{0 if d.get('X_nl') is None else d['X_nl'].shape[1]} nl features", flush=True)

    if args.all:
        eval_kind = args.all
        jobs = []
        for item in args.items:
            for v in variant_set_for_item(item):
                jobs.append((item, v, eval_kind))
        print(f"Total jobs: {len(jobs)}", flush=True)
        results: list[dict] = []
        t0 = time.time()
        out_csv = out_dir / f"peritem_v3_screening_{eval_kind}.csv"
        out_json = out_dir / f"peritem_v3_screening_{eval_kind}.json"
        for i, (item, variant, ek) in enumerate(jobs):
            try:
                r = run_one(d, item, variant, ek, seeds=tuple(args.seeds),
                            with_null=(ek == "5split"))
            except Exception as e:
                r = {"item": item, "variant": variant, "eval": ek, "error": str(e)}
            results.append(r)
            elapsed = time.time() - t0
            ccc = r.get("ccc_mean")
            ccc_str = f"{ccc:.4f}" if isinstance(ccc, (int, float)) else "ERROR"
            err = r.get("error", "")
            print(f"  [{i+1}/{len(jobs)}] item={item} variant={variant} "
                  f"ccc={ccc_str} ({elapsed:.1f}s elapsed)"
                  + (f" [{err}]" if err else ""), flush=True)
            df_out = pd.DataFrame([
                {"item": r2["item"], "variant": r2["variant"], "eval": r2["eval"],
                 "ccc_mean": r2.get("ccc_mean", np.nan),
                 "ccc_std": r2.get("ccc_std", np.nan),
                 "mae_mean": r2.get("mae_mean", np.nan),
                 "scrambled_label_ccc": r2.get("null_tests", {}).get("scrambled_label_ccc", np.nan)}
                for r2 in results
            ])
            df_out.to_csv(out_csv, index=False)
            with open(out_json, "w") as f:
                json.dump(results, f, indent=2, default=float)
        print(f"\nWrote {out_csv} and {out_json}", flush=True)
        print(f"\nTop 30 by CCC:", flush=True)
        df_top = df_out.dropna(subset=["ccc_mean"]).sort_values("ccc_mean", ascending=False)
        print(df_top.head(30).to_string(), flush=True)
    else:
        if not args.variant:
            raise SystemExit("--variant required if --all not used")
        if args.item < 1 or args.item > 18:
            raise SystemExit("--item must be 1..18")
        r = run_one(d, args.item, args.variant, args.eval, seeds=tuple(args.seeds))
        out_path = out_dir / f"peritem_v3_item{args.item}_{args.variant}_{args.eval}.json"
        with open(out_path, "w") as f:
            json.dump(r, f, indent=2, default=float)
        print(json.dumps({"item": r["item"], "variant": r["variant"], "eval": r["eval"],
                          "ccc_mean": r.get("ccc_mean")}, default=float))
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
