"""Phase 3 — first-principles retry of MARGINAL/DEAD variants from iter4 Phase 2.

Each retry applies ONE first-principles fix (per task_plan.md template) to the
variant that failed in Phase 2. Re-uses load_pd_data + helpers from run_t1_iter4.

Variants:
  tug_microscope_v2_top30      — keep only top-30 stable phase features (codex multi-attempt fix)
  lr_asymmetry_v2              — per-fold K=200 ON ASYMMETRY BLOCK + concat with K=500 v2
  task_expert_v2_tight         — 3 experts only (TUG, Balance, TandemGait), tighter LGB
  hierarchical_v2_blend        — BLEND 60% direct + 40% branch-sum (instead of replace)
  item11_surrogate_v2_lgb      — LGB ordinal classifier on item-11 (was LR; tree better at N=89)
  balance_posture_v2_basestack — predict T1 directly from rest-state, then stack as base learner

Output: results/iter4_<variant>_t1_5split.json (overwrites if same name).
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
    get_hy_features, LGB_DEFAULTS, LGB_TIGHT, load_extra_cache,
    SEEDS, T1_ITEMS, DISTAL_ITEMS, AXIAL_ITEMS,
    LR_ASYMMETRY, TUG_TRANSITION, REST_STATE, ROCKET_CACHE,
)


def variant_tug_microscope_v2_top30(d: dict, seed: int = 42) -> dict:
    """Codex multi-attempt fix: keep only top-30 stable TUG phase features (lowest CV)
    on training fold; concat with v2."""
    n = len(d["sids"])
    X_tug, _ = load_extra_cache(TUG_TRANSITION, d["sids"])
    df_tmp = pd.read_csv(TUG_TRANSITION)
    feat_cols_tug = [c for c in df_tmp.columns if c not in ("sid", "_spike_time_s")]
    X_tug = X_tug[:, [list(df_tmp.columns).index(c) - 1 for c in feat_cols_tug]]
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof = np.zeros(n)
    for tr, te in splits:
        # Per-fold "stability" score = mean(|train|) / std(train) — high mean and low CV
        Xtug_tr_imp, Xtug_te_imp = impute_fold(X_tug[tr], X_tug[te])
        col_mean = np.abs(Xtug_tr_imp.mean(axis=0))
        col_std = Xtug_tr_imp.std(axis=0) + 1e-8
        stability = col_mean / col_std
        top30_idx = np.argsort(stability)[::-1][:30]
        Xtug_tr_top = Xtug_tr_imp[:, top30_idx]
        Xtug_te_top = Xtug_te_imp[:, top30_idx]
        # Concat with v2
        Xv_tr, Xv_te = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xv_tr_s, Xv_te_s, _ = feature_select_fold(Xv_tr, d["t1"][tr], Xv_te, k=500, seed=seed)
        Xtr = np.hstack([Xv_tr_s, Xtug_tr_top])
        Xte = np.hstack([Xv_te_s, Xtug_te_top])
        oof[te] = train_lgb(Xtr, d["t1"][tr], Xte, seed)
    return {"oof": oof}


def variant_lr_asymmetry_v2(d: dict, seed: int = 42) -> dict:
    """Per-fold K=200 ON ASYMMETRY BLOCK + concat with K=500 v2 (de-bloat fix)."""
    n = len(d["sids"])
    X_lr, _ = load_extra_cache(LR_ASYMMETRY, d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof = np.zeros(n)
    for tr, te in splits:
        # Select K=200 from asymmetry block
        Xlr_tr, Xlr_te = impute_fold(X_lr[tr], X_lr[te])
        Xlr_tr_s, Xlr_te_s, _ = feature_select_fold(Xlr_tr, d["t1"][tr], Xlr_te,
                                                    k=200, seed=seed)
        # K=500 from v2 block
        Xv_tr, Xv_te = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xv_tr_s, Xv_te_s, _ = feature_select_fold(Xv_tr, d["t1"][tr], Xv_te,
                                                  k=500, seed=seed)
        Xtr = np.hstack([Xv_tr_s, Xlr_tr_s])
        Xte = np.hstack([Xv_te_s, Xlr_te_s])
        oof[te] = train_lgb(Xtr, d["t1"][tr], Xte, seed)
    return {"oof": oof}


def variant_task_expert_v2_tight(d: dict, seed: int = 42) -> dict:
    """Tighter experts on 3 tasks only (TUG, Balance, TandemGait); add task-avail flag."""
    n = len(d["sids"])
    rec = np.load(ROCKET_CACHE)
    rec_arr = rec["recordings"]
    rec_sids = rec["sids"]
    rec_tasks = rec["tasks"]
    EXPERT_TASKS = ["TUG", "Balance", "TandemGait"]
    sid_to_idx = {s: i for i, s in enumerate(d["sids"])}

    def per_task_features(task_name: str) -> tuple[np.ndarray, np.ndarray]:
        mask = rec_tasks == task_name
        per_subj = np.full((n, 26 * 5), np.nan, dtype=np.float64)
        avail = np.zeros(n, dtype=np.float64)
        recs_tk = rec_arr[mask]
        sids_tk = rec_sids[mask]
        for i in range(len(recs_tk)):
            r = recs_tk[i]
            if sids_tk[i] not in sid_to_idx:
                continue
            si = sid_to_idx[sids_tk[i]]
            row = []
            for ch in range(26):
                x = r[ch]
                row.extend([
                    float(np.sqrt(np.mean(x.astype(np.float64) ** 2))),
                    float(np.std(x)),
                    float(np.ptp(x)),
                    float(np.sqrt(np.mean(np.diff(x).astype(np.float64) ** 2)))
                    if len(x) > 1 else 0.0,
                    float(np.sum(np.diff(np.sign(x - np.mean(x))) != 0) / len(x)),
                ])
            avail[si] = 1.0
            if np.all(np.isnan(per_subj[si])):
                per_subj[si] = row
            else:
                per_subj[si] = (per_subj[si] + np.array(row)) / 2.0
        return per_subj, avail

    expert_data = {tk: per_task_features(tk) for tk in EXPERT_TASKS}
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_per_expert = {tk: np.zeros(n) for tk in EXPERT_TASKS}
    avail_block = np.column_stack([expert_data[tk][1] for tk in EXPERT_TASKS])

    for tr, te in splits:
        for tk in EXPERT_TASKS:
            Xtr, Xte = impute_fold(expert_data[tk][0][tr], expert_data[tk][0][te])
            oof_per_expert[tk][te] = train_lgb(Xtr, d["t1"][tr], Xte, seed,
                                               params=LGB_TIGHT)

    expert_stack = np.column_stack(
        [oof_per_expert[tk] for tk in EXPERT_TASKS] + [avail_block]
    )
    oof = np.zeros(n)
    for tr, te in splits:
        meta = Ridge(alpha=2.0, random_state=seed)
        meta.fit(expert_stack[tr], d["t1"][tr])
        oof[te] = meta.predict(expert_stack[te])
    return {"oof": oof, "per_expert_ccc": {
        tk: round(ccc_fn(d["t1"], oof_per_expert[tk]), 4) for tk in EXPERT_TASKS
    }}


def variant_hierarchical_v2_blend(d: dict, seed: int = 42) -> dict:
    """BLEND 60% direct + 40% branch-sum to avoid pure-decomp variance."""
    n = len(d["sids"])
    feat_cols = d["feat_cols"]
    distal_y = np.sum([d["items"][i] for i in DISTAL_ITEMS], axis=0)
    axial_y = np.sum([d["items"][i] for i in AXIAL_ITEMS], axis=0)
    DISTAL_PREFIXES = ("L_Wrist", "R_Wrist", "L_Shank", "R_Shank",
                       "L_DorsalFoot", "R_DorsalFoot", "L_Ankle", "R_Ankle",
                       "L_Thigh", "R_Thigh")
    AXIAL_PREFIXES = ("LowerBack", "Xiphoid", "Forehead")
    distal_mask = np.array([any(c.startswith(p + "_") for p in DISTAL_PREFIXES)
                            for c in feat_cols])
    axial_mask = np.array([any(c.startswith(p + "_") for p in AXIAL_PREFIXES)
                           for c in feat_cols])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_direct = np.zeros(n)
    oof_branch = np.zeros(n)
    for tr, te in splits:
        # Direct: full v2
        Xv_tr, Xv_te = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xv_tr_s, Xv_te_s, _ = feature_select_fold(Xv_tr, d["t1"][tr], Xv_te, k=500, seed=seed)
        oof_direct[te] = train_lgb(Xv_tr_s, d["t1"][tr], Xv_te_s, seed)
        # Distal branch
        Xd_tr, Xd_te = impute_fold(d["X_v2"][tr][:, distal_mask],
                                    d["X_v2"][te][:, distal_mask])
        if Xd_tr.shape[1] > 300:
            Xd_tr, Xd_te, _ = feature_select_fold(Xd_tr, distal_y[tr], Xd_te, k=300, seed=seed)
        d_pred = train_lgb(Xd_tr, distal_y[tr], Xd_te, seed)
        # Axial branch
        Xa_tr, Xa_te = impute_fold(d["X_v2"][tr][:, axial_mask],
                                    d["X_v2"][te][:, axial_mask])
        if Xa_tr.shape[1] > 200:
            Xa_tr, Xa_te, _ = feature_select_fold(Xa_tr, axial_y[tr], Xa_te, k=200, seed=seed)
        a_pred = train_lgb(Xa_tr, axial_y[tr], Xa_te, seed)
        oof_branch[te] = d_pred + a_pred
    blended = 0.6 * oof_direct + 0.4 * oof_branch
    return {"oof": blended,
            "ccc_direct_only": round(ccc_fn(d["t1"], oof_direct), 4),
            "ccc_branch_only": round(ccc_fn(d["t1"], oof_branch), 4),
            "ccc_blended": round(ccc_fn(d["t1"], blended), 4)}


def variant_item11_surrogate_v2_lgb(d: dict, seed: int = 42) -> dict:
    """LGB ordinal classifier (5-bin) on item-11 — replace LR with tree (more flexible at N=89)."""
    n = len(d["sids"])
    X_rest, _ = load_extra_cache(REST_STATE, d["sids"])
    item11 = d["items"][11]
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_item11 = np.zeros(n)
    import lightgbm as lgb
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_rest[tr], X_rest[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, item11[tr], Xte, k=200, seed=seed)
        # LGB regressor on raw item-11 score
        oof_item11[te] = train_lgb(Xtr, item11[tr], Xte, seed, params=LGB_TIGHT)

    X_aug = np.column_stack([d["X_v2"], oof_item11])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, d["t1"][tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, d["t1"][tr], Xte, seed)
    return {"oof": oof,
            "item11_oof_ccc": round(ccc_fn(item11, oof_item11), 4)}


def variant_balance_posture_v2_basestack(d: dict, seed: int = 42) -> dict:
    """Predict T1 directly from rest-state cache → use as base learner in Ridge stack with v2 LGB."""
    n = len(d["sids"])
    X_rest, _ = load_extra_cache(REST_STATE, d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_v2 = np.zeros(n)
    oof_rest = np.zeros(n)
    for tr, te in splits:
        # v2 base learner
        Xv_tr, Xv_te = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xv_tr_s, Xv_te_s, _ = feature_select_fold(Xv_tr, d["t1"][tr], Xv_te, k=500, seed=seed)
        oof_v2[te] = train_lgb(Xv_tr_s, d["t1"][tr], Xv_te_s, seed)
        # rest-state base learner
        Xr_tr, Xr_te = impute_fold(X_rest[tr], X_rest[te])
        Xr_tr_s, Xr_te_s, _ = feature_select_fold(Xr_tr, d["t1"][tr], Xr_te, k=200, seed=seed)
        oof_rest[te] = train_lgb(Xr_tr_s, d["t1"][tr], Xr_te_s, seed, params=LGB_TIGHT)
    stack = np.column_stack([oof_v2, oof_rest])
    oof = np.zeros(n)
    for tr, te in splits:
        meta = Ridge(alpha=1.0, random_state=seed)
        meta.fit(stack[tr], d["t1"][tr])
        oof[te] = meta.predict(stack[te])
    return {"oof": oof,
            "ccc_v2_only": round(ccc_fn(d["t1"], oof_v2), 4),
            "ccc_rest_only": round(ccc_fn(d["t1"], oof_rest), 4),
            "ccc_stacked": round(ccc_fn(d["t1"], oof), 4)}


VARIANT_REGISTRY = {
    "tug_microscope_v2_top30":      variant_tug_microscope_v2_top30,
    "lr_asymmetry_v2":              variant_lr_asymmetry_v2,
    "task_expert_v2_tight":         variant_task_expert_v2_tight,
    "hierarchical_v2_blend":        variant_hierarchical_v2_blend,
    "item11_surrogate_v2_lgb":      variant_item11_surrogate_v2_lgb,
    "balance_posture_v2_basestack": variant_balance_posture_v2_basestack,
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
        "phase": "phase3_retry",
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
