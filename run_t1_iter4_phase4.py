"""Iter 4 Phase 4 — Tier-2 ideas + full stacking. Self-contained.

Variants (run as `--variant <name>`):
  reliability_repeated_trials  — idea 7. Inverse-variance reweight of per-(subject, task)
                                  recording features in the rocket cache.
  within_stage_ranker          — idea 8. Residualize on H&Y+demo first; pairwise XGBRanker
                                  within same H&Y stratum; blend with residual regression.
  tabpfn_challenger            — idea 10. TabPFN-2.5 as ensemble member only.
                                  Per fold: K=200 features → TabPFN OOF predictions.
  full_stack_t1                — Ridge meta over OOF predictions of the HIT-pool variants
                                  named via --base-variants ENV var (comma list).

Output: results/iter4_<variant>_t1_5split.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
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
    feature_select_fold, train_lgb,
    get_hy_features, LGB_DEFAULTS, LGB_TIGHT,
    SEEDS, T1_ITEMS,
    ROCKET_CACHE,
)


def variant_reliability_repeated_trials(d: dict, seed: int = 42) -> dict:
    """Idea 7: inverse-variance reweight per (subject, task) trial repeats.

    Build per-subject features by:
    1. For each task, find all recordings for that subject.
    2. Compute simple stats per recording.
    3. Aggregate as inverse-variance-weighted mean (downweight noisy trials).

    If <2 repeats per subject for >50% of subjects → fall back to plain mean (declare
    dead per stopping rule).
    """
    n = len(d["sids"])
    rec = np.load(ROCKET_CACHE)
    rec_arr = rec["recordings"]
    rec_sids = rec["sids"]
    rec_tasks = rec["tasks"]
    sid_to_idx = {s: i for i, s in enumerate(d["sids"])}

    # Compute per-recording feature vector: stats per channel
    def per_rec_feats(r: np.ndarray) -> np.ndarray:
        feats = []
        for ch in range(26):
            x = r[ch]
            feats.extend([
                float(np.sqrt(np.mean(x.astype(np.float64) ** 2))),
                float(np.std(x)),
                float(np.ptp(x)),
                float(np.sqrt(np.mean(np.diff(x).astype(np.float64) ** 2)))
                if len(x) > 1 else 0.0,
                float(np.sum(np.diff(np.sign(x - np.mean(x))) != 0) / len(x)),
            ])
        return np.array(feats, dtype=np.float64)

    # Group by (subject, task)
    by_subj_task: dict[tuple[str, str], list[np.ndarray]] = {}
    for i in range(len(rec_arr)):
        sid = str(rec_sids[i]); tk = str(rec_tasks[i])
        if sid not in sid_to_idx:
            continue
        by_subj_task.setdefault((sid, tk), []).append(per_rec_feats(rec_arr[i]))

    # Stats per subject
    n_repeats = []
    per_subj_mat = np.full((n, 26 * 5), np.nan, dtype=np.float64)
    for sid, idx in sid_to_idx.items():
        all_recs_for_subj = []
        for (s, _), recs in by_subj_task.items():
            if s == sid:
                all_recs_for_subj.extend(recs)
                n_repeats.append(len(recs))
        if not all_recs_for_subj:
            continue
        block = np.vstack(all_recs_for_subj)  # (k, 130)
        if block.shape[0] < 2:
            per_subj_mat[idx] = block.mean(axis=0)
            continue
        # Inverse-variance weight: per-feature variance across trials → 1/var weight
        var = block.var(axis=0) + 1e-8
        weights = 1.0 / var
        weights = weights / weights.sum()
        per_subj_mat[idx] = (block * weights[None, :]).sum(axis=0)

    # Sanity: if too many subjects have <2 repeats, declare dead
    repeat_frac = float(sum(1 for r in n_repeats if r >= 2) / max(len(n_repeats), 1))
    if repeat_frac < 0.5:
        return {"oof": np.full(n, d["t1"].mean()),
                "_note": f"DEAD: only {repeat_frac:.1%} of (subj,task) cells have ≥2 repeats"}

    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(per_subj_mat[tr], per_subj_mat[te])
        oof[te] = train_lgb(Xtr, d["t1"][tr], Xte, seed)
    return {"oof": oof, "repeat_frac": round(repeat_frac, 3)}


def variant_within_stage_ranker(d: dict, seed: int = 42) -> dict:
    """Idea 8: residualize on H&Y+demo first; pairwise XGBRanker within H&Y strata;
    blend rank-pred and residual-regression."""
    n = len(d["sids"])
    hy_feat = get_hy_features(d["hy"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)

    # Stage 1: H&Y+demo Ridge baseline (same as hy_residual)
    oof_s1 = np.zeros(n)
    oof_s2_resid = np.zeros(n)
    oof_s2_rank = np.zeros(n)
    try:
        import xgboost as xgb
    except ImportError:
        return {"oof": np.full(n, d["t1"].mean()),
                "_note": "DEAD: xgboost not available"}

    for tr, te in splits:
        # Stage 1: Ridge on H&Y
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], d["t1"][tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        oof_s1[te] = s1_te
        # Stage 2a: residual LGB on v2 (same as hy_residual_t1 logic)
        resid_tr = d["t1"][tr] - s1_tr
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr_s, Xte_s, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        oof_s2_resid[te] = train_lgb(Xtr_s, resid_tr, Xte_s, seed)
        # Stage 2b: ranker. Stratify by H&Y bin.
        # Build query groups by H&Y bin. Within each group, rank labels.
        hy_train = d["hy"][tr]
        # Discretize H&Y to bins so within-bin pairwise rank
        hy_bins_train = np.where(np.isnan(hy_train), 99, np.round(hy_train * 2)).astype(int)
        # XGBRanker requires sorted by group
        order = np.argsort(hy_bins_train)
        Xtr_ord = Xtr_s[order]
        ytr_ord = d["t1"][tr][order]
        groups_train = pd.Series(hy_bins_train[order]).value_counts(sort=False).sort_index().values
        ranker = xgb.XGBRanker(
            objective="rank:pairwise", n_estimators=200, learning_rate=0.05,
            max_depth=4, subsample=0.8, colsample_bytree=0.8,
            random_state=seed, n_jobs=4, verbosity=0,
        )
        ranker.fit(Xtr_ord, ytr_ord, group=groups_train)
        oof_s2_rank[te] = ranker.predict(Xte_s)

    # Blend: 60% residual regression + 40% rank-pred (rank is rank score, not score; rescale)
    rank_norm = (oof_s2_rank - oof_s2_rank.mean()) / (oof_s2_rank.std() + 1e-8)
    rank_scaled = rank_norm * d["t1"].std() * 0.5  # bring to t1 scale-ish
    blend = oof_s1 + 0.6 * oof_s2_resid + 0.4 * rank_scaled
    return {"oof": blend,
            "ccc_blend": round(ccc_fn(d["t1"], blend), 4),
            "ccc_resid_only": round(ccc_fn(d["t1"], oof_s1 + oof_s2_resid), 4),
            "ccc_rank_only": round(ccc_fn(d["t1"], oof_s1 + rank_scaled), 4)}


def variant_tabpfn_challenger(d: dict, seed: int = 42) -> dict:
    """Idea 10: TabPFN-2.5 as ensemble member. Per fold: K=200 features → TabPFN OOF."""
    n = len(d["sids"])
    try:
        from tabpfn import TabPFNRegressor
    except ImportError:
        return {"oof": np.full(n, d["t1"].mean()),
                "_note": "DEAD: tabpfn not available — install with `pip install tabpfn`"}

    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr, Xte, _ = feature_select_fold(Xtr, d["t1"][tr], Xte, k=200, seed=seed)
        # Standardise (TabPFN benefits from it)
        mean, std = Xtr.mean(axis=0), Xtr.std(axis=0)
        std = np.where(std < 1e-8, 1.0, std)
        Xtr_s = (Xtr - mean) / std
        Xte_s = (Xte - mean) / std
        m = TabPFNRegressor(random_state=seed, n_estimators=4)
        m.fit(Xtr_s, d["t1"][tr])
        oof[te] = m.predict(Xte_s)
    return {"oof": oof}


def variant_full_stack_t1(d: dict, seed: int = 42) -> dict:
    """Ridge meta over OOF predictions from base variants in HIT pool.

    Reads results/iter4_<variant>_t1_5split.json for each base variant in
    the env BASE_VARIANTS=tug_microscope,hy_residual_t1,...
    Loads their per-seed OOF predictions and trains Ridge meta on them per-fold.
    """
    n = len(d["sids"])
    base_variants_str = os.getenv("BASE_VARIANTS", "")
    base_variants = [v.strip() for v in base_variants_str.split(",") if v.strip()]
    if not base_variants:
        raise ValueError("Set BASE_VARIANTS env var (comma-separated variant names)")

    # Each base variant's OOF predictions (seed-averaged) loaded from per-seed metrics
    # but we don't store per-seed OOF arrays in the JSONs. Recompute from scratch
    # for each base variant per fold within this run for simplicity.
    from run_t1_iter4 import VARIANT_REGISTRY

    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_base: dict[str, np.ndarray] = {}
    for v in base_variants:
        if v not in VARIANT_REGISTRY:
            print(f"  warning: unknown base variant {v}; skipping")
            continue
        out = VARIANT_REGISTRY[v](d, seed=seed)
        oof_base[v] = out["oof"]

    if len(oof_base) < 2:
        return {"oof": np.full(n, d["t1"].mean()),
                "_note": "DEAD: <2 valid base variants"}

    stack = np.column_stack([oof_base[v] for v in oof_base])
    oof = np.zeros(n)
    for tr, te in splits:
        meta = Ridge(alpha=1.0, random_state=seed)
        meta.fit(stack[tr], d["t1"][tr])
        oof[te] = meta.predict(stack[te])
    return {"oof": oof,
            "base_variants": list(oof_base),
            "individual_ccc": {v: round(ccc_fn(d["t1"], oof_base[v]), 4)
                               for v in oof_base}}


VARIANT_REGISTRY = {
    "reliability_repeated_trials": variant_reliability_repeated_trials,
    "within_stage_ranker":         variant_within_stage_ranker,
    "tabpfn_challenger":           variant_tabpfn_challenger,
    "full_stack_t1":               variant_full_stack_t1,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=list(VARIANT_REGISTRY))
    ap.add_argument("--out_dir", default=str(RESULTS_DIR))
    args = ap.parse_args()

    fn = VARIANT_REGISTRY[args.variant]
    print(f"[{args.variant}] loading data...")
    t0 = time.time()
    d = load_pd_data()
    n = len(d["sids"])
    print(f"  loaded {n} PD subjects, T1 mean={d['t1'].mean():.2f}")

    per_seed = []
    cccs = []
    for seed in SEEDS:
        s_t0 = time.time()
        out = fn(d, seed=seed)
        oof = out["oof"]
        m = full_metrics(d["t1"], oof, label=f"{args.variant}_seed{seed}")
        m["seed"] = seed
        m["wall_s"] = round(time.time() - s_t0, 1)
        for k, v in out.items():
            if k != "oof":
                m[k] = v
        per_seed.append(m)
        cccs.append(m["ccc"])
        print(f"  seed={seed} ccc={m['ccc']:.4f} mae={m['mae']:.3f} ({m['wall_s']:.0f}s)")

    summary = {
        "variant": args.variant, "target": "t1", "eval": "5split",
        "n_subjects": n,
        "ccc_mean": round(float(np.mean(cccs)), 4),
        "ccc_std": round(float(np.std(cccs)), 4),
        "ccc_per_seed": [round(c, 4) for c in cccs],
        "mae_mean": round(float(np.mean([m["mae"] for m in per_seed])), 4),
        "slope_mean": round(float(np.mean([m["cal_slope"] for m in per_seed])), 4),
        "per_seed": per_seed,
        "wall_total_s": round(time.time() - t0, 1),
    }

    out_path = Path(args.out_dir) / f"iter4_{args.variant}_t1_5split.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"[{args.variant}] DONE — ccc_mean={summary['ccc_mean']:.4f} → {out_path}")


if __name__ == "__main__":
    main()
