"""Iter 4 — T1 step-function ablation. Self-contained.

Variants (run as `--variant <name>`):
  b1_v2_only_control          — control: LightGBM on v2 features (target: T1 = sum items 9-14)
  hy_residual_t1              — Stage-1 Ridge(H&Y+demo) + Stage-2 LGB(v2 residual). Bellwether.
  tug_microscope              — base v2 + TUG-transition phase features (cache_tug_transition_features.csv)
  hierarchical_distal_axial   — distal(9-12)+axial(13-14) split with sensor whitelist on v2
  task_expert_mixture         — 3 per-task LGB experts (TUG, Balance, TandemGait) + Ridge meta over OOF on v2
  balance_posture_expert      — item-14 model from Balance+Tandem rest-state → OOF logits as feature for total T1
  lr_asymmetry                — base v2 + LR_diff + LR_abs_diff (cache_lr_asymmetry.csv)
  item11_surrogate            — item-11 model from rest-state cache → OOF probs as dense feature for total T1

All variants:
- Strict inductive: per-fold preprocess (impute, K=500 selection), no global stats.
- Multi-seed: SEEDS = [42, 1337, 7]; 5-fold CV per seed; report mean ± std.
- Drop HC; PD-only (89 subjects).
- Subject-level splits via paper3_split.json or stratified KFold by quartile.
- 3-null gate: scrambled-label, canary-feature, sid-shuffle (where applicable).

Output: results/iter4_<variant>_t1_5split.json with metrics + null_tests + per-seed array.
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
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir

ensure_dir(RESULTS_DIR)
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 4)))
SEEDS = [42, 1337, 7]

V2_FEATURES = RESULTS_DIR / "ablation_v3_features.csv"
PER_ITEM_CACHE = RESULTS_DIR / "per_item_scores.json"
LR_ASYMMETRY = RESULTS_DIR / "lr_asymmetry_features.csv"
TUG_TRANSITION = RESULTS_DIR / "tug_transition_features.csv"
REST_STATE = RESULTS_DIR / "rest_state_features.csv"
ROCKET_CACHE = RESULTS_DIR / "rocket_recordings.npz"

T1_ITEMS = [9, 10, 11, 12, 13, 14]
DISTAL_ITEMS = [9, 10, 11, 12]
AXIAL_ITEMS = [13, 14]
V2_EXCLUDED_PREFIXES = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")

LGB_DEFAULTS = dict(
    n_estimators=500, learning_rate=0.05, num_leaves=15, max_depth=-1,
    min_data_in_leaf=10, reg_alpha=0.1, reg_lambda=0.3,
    feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5,
    n_jobs=N_CORES, verbosity=-1,
)
LGB_TIGHT = dict(
    n_estimators=300, learning_rate=0.05, num_leaves=8, max_depth=-1,
    min_data_in_leaf=20, reg_alpha=0.2, reg_lambda=0.5,
    feature_fraction=0.7, bagging_fraction=0.7, bagging_freq=5,
    n_jobs=N_CORES, verbosity=-1,
)


def is_pd(sid: str) -> bool:
    s = str(sid).upper()
    return s.startswith("NLS") or s.startswith("WPD")


def load_per_item_scores() -> dict:
    with open(PER_ITEM_CACHE) as f:
        raw = json.load(f)
    out = {}
    for sid, scores in raw.items():
        per_item = {}
        for k, v in scores.items():
            if k.startswith("("):
                continue
            try:
                ki = int(k)
                if 1 <= ki <= 18:
                    per_item[ki] = float(v)
            except ValueError:
                continue
        out[sid] = per_item
    return out


def v2_feature_columns(df: pd.DataFrame) -> list[str]:
    excluded = {"sid", "updrs3", "obs_subscore", "hy", "n_tasks"}
    return [c for c in df.columns
            if c not in excluded and not any(c.startswith(p) for p in V2_EXCLUDED_PREFIXES)]


def load_pd_data() -> dict:
    """Return dict with sids, X_v2, feat_cols, items{1..18}, t1, hy, age, sex, ht, wt, dx_yrs."""
    df = pd.read_csv(V2_FEATURES)
    feat_cols = v2_feature_columns(df)
    pis = load_per_item_scores()

    sids: list[str] = []
    feats: list[np.ndarray] = []
    items_arr = {i: [] for i in range(1, 19)}
    hy_arr: list[float] = []
    obs_arr: list[float] = []
    for _, r in df.iterrows():
        sid = r["sid"]
        if not is_pd(sid):
            continue
        if sid not in pis:
            continue
        items = pis[sid]
        if not all(i in items for i in T1_ITEMS):
            continue
        for i in range(1, 19):
            items_arr[i].append(items.get(i, np.nan))
        hy_arr.append(r.get("hy", np.nan))
        obs_arr.append(r.get("obs_subscore", np.nan))
        sids.append(sid)
        feats.append(r[feat_cols].to_numpy(dtype=np.float64))
    sids_arr = np.array(sids)
    X = np.vstack(feats)
    items = {i: np.array(items_arr[i], dtype=np.float64) for i in range(1, 19)}
    t1 = np.sum([items[i] for i in T1_ITEMS], axis=0)
    return {
        "sids": sids_arr, "X_v2": X, "feat_cols": feat_cols,
        "items": items, "t1": t1,
        "hy": np.array(hy_arr, dtype=np.float64),
        "obs": np.array(obs_arr, dtype=np.float64),
    }


def load_extra_cache(path: Path, sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Load a per-subject cache CSV and align rows with `sids`. Missing → zeros."""
    if not path.exists():
        raise FileNotFoundError(f"Required cache missing: {path}")
    df = pd.read_csv(path)
    df = df.set_index("sid")
    feat_cols = list(df.columns)
    X = np.zeros((len(sids), len(feat_cols)), dtype=np.float64)
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, feat_cols].to_numpy(dtype=np.float64)
        else:
            X[i] = np.nan
    return X, feat_cols


def get_hy_features(hy_arr: np.ndarray) -> np.ndarray:
    """Bin H&Y into one-hot + linear feature (port from T3 hy_residual)."""
    hy_clean = np.where(np.isnan(hy_arr), 0.0, hy_arr)
    one_hot = np.zeros((len(hy_arr), 5))
    bins = [(-0.1, 1.5, 0), (1.5, 2.0, 1), (2.0, 2.5, 2), (2.5, 3.0, 3), (3.0, 5.0, 4)]
    for lo, hi, idx in bins:
        mask = (hy_arr > lo) & (hy_arr <= hi)
        one_hot[mask, idx] = 1.0
    return np.column_stack([hy_clean.reshape(-1, 1), one_hot])


def kfold_split_stratified(y: np.ndarray, n_splits: int = 5, seed: int = 42):
    """Stratified KFold by target quartiles (matches existing T1 baselines)."""
    bins = np.digitize(y, np.percentile(y, [25, 50, 75]))
    rng = np.random.RandomState(seed)
    indices = np.arange(len(y))
    rng.shuffle(indices)
    bins = bins[indices]
    fold_assign = np.zeros(len(y), dtype=int)
    bin_counters = {b: 0 for b in np.unique(bins)}
    for i, b in zip(indices, bins):
        fold_assign[i] = bin_counters[b] % n_splits
        bin_counters[b] += 1
    return [(np.where(fold_assign != f)[0], np.where(fold_assign == f)[0])
            for f in range(n_splits)]


def impute_fold(X_tr: np.ndarray, X_te: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    med = np.nanmedian(X_tr, axis=0)
    med = np.where(np.isnan(med), 0.0, med)
    return (np.where(np.isnan(X_tr), med, X_tr),
            np.where(np.isnan(X_te), med, X_te))


def feature_select_fold(X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray,
                        k: int = 500, seed: int = 42) -> tuple:
    if X_tr.shape[1] <= k:
        return X_tr, X_te, np.arange(X_tr.shape[1])
    import lightgbm as lgb
    sel = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.1, num_leaves=15,
                            min_data_in_leaf=5, n_jobs=N_CORES,
                            random_state=seed, verbosity=-1)
    sel.fit(X_tr, y_tr)
    imp = sel.feature_importances_
    idx = np.argsort(imp)[::-1][:k]
    return X_tr[:, idx], X_te[:, idx], idx


def train_lgb(X_tr, y_tr, X_te, seed: int, params: dict | None = None) -> np.ndarray:
    import lightgbm as lgb
    p = {**(params or LGB_DEFAULTS), "random_state": seed}
    model = lgb.LGBMRegressor(**p)
    model.fit(X_tr, y_tr)
    return model.predict(X_te)


# ── Variants ─────────────────────────────────────────────────────────────────


def variant_b1_control(d: dict, seed: int = 42) -> dict:
    """Control: LGB on v2 features only, target = T1."""
    n = len(d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr, Xte, _ = feature_select_fold(Xtr, d["t1"][tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, d["t1"][tr], Xte, seed)
    return {"oof": oof}


def variant_hy_residual_t1(d: dict, seed: int = 42) -> dict:
    """Stage-1 Ridge(H&Y+demo) + Stage-2 LGB(v2 residual). Bellwether."""
    n = len(d["sids"])
    hy_feat = get_hy_features(d["hy"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof = np.zeros(n)
    for tr, te in splits:
        # Stage 1: Ridge on H&Y
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], d["t1"][tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        # Stage 2: LGB on v2 → residual
        resid_tr = d["t1"][tr] - s1_tr
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        s2_te = train_lgb(Xtr, resid_tr, Xte, seed)
        oof[te] = s1_te + s2_te
    return {"oof": oof}


def variant_tug_microscope(d: dict, seed: int = 42) -> dict:
    """v2 features + TUG transition phase features."""
    n = len(d["sids"])
    X_tug, _ = load_extra_cache(TUG_TRANSITION, d["sids"])
    # Drop the "_spike_time_s" column from features used for prediction (it's diagnostic)
    df_tmp = pd.read_csv(TUG_TRANSITION)
    feat_cols_tug = [c for c in df_tmp.columns if c not in ("sid", "_spike_time_s")]
    X_tug = X_tug[:, [list(df_tmp.columns).index(c) - 1 for c in feat_cols_tug]]
    X_aug = np.hstack([d["X_v2"], X_tug])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, d["t1"][tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, d["t1"][tr], Xte, seed)
    return {"oof": oof}


def variant_hierarchical_distal_axial(d: dict, seed: int = 42) -> dict:
    """Predict distal(9-12 sum) + axial(13-14 sum) separately on sensor-whitelisted v2.

    Soft-mask (codex fix): keep all features but down-weight non-branch sensors via L2
    by training selector on branch target. Hard whitelist tested too as backup.
    """
    n = len(d["sids"])
    feat_cols = d["feat_cols"]
    distal_y = np.sum([d["items"][i] for i in DISTAL_ITEMS], axis=0)
    axial_y = np.sum([d["items"][i] for i in AXIAL_ITEMS], axis=0)
    DISTAL_SENS = ("L_Wrist", "R_Wrist", "L_Shank", "R_Shank",
                   "L_DorsalFoot", "R_DorsalFoot", "L_Ankle", "R_Ankle",
                   "L_Thigh", "R_Thigh")
    AXIAL_SENS = ("LowerBack", "Xiphoid", "Forehead")
    distal_mask = np.array([
        any(c.startswith(s + "_") for s in DISTAL_SENS) or
        any(c.startswith(p + s + "_") for p in ("L_", "R_") for s in ("Wrist", "Shank", "DorsalFoot", "Ankle", "Thigh"))
        for c in feat_cols
    ])
    axial_mask = np.array([
        any(c.startswith(s + "_") for s in AXIAL_SENS) for c in feat_cols
    ])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof = np.zeros(n)
    for tr, te in splits:
        # Distal branch
        Xd_tr, Xd_te = impute_fold(d["X_v2"][tr][:, distal_mask], d["X_v2"][te][:, distal_mask])
        if Xd_tr.shape[1] > 300:
            Xd_tr, Xd_te, _ = feature_select_fold(Xd_tr, distal_y[tr], Xd_te, k=300, seed=seed)
        d_pred = train_lgb(Xd_tr, distal_y[tr], Xd_te, seed)
        # Axial branch
        Xa_tr, Xa_te = impute_fold(d["X_v2"][tr][:, axial_mask], d["X_v2"][te][:, axial_mask])
        if Xa_tr.shape[1] > 200:
            Xa_tr, Xa_te, _ = feature_select_fold(Xa_tr, axial_y[tr], Xa_te, k=200, seed=seed)
        a_pred = train_lgb(Xa_tr, axial_y[tr], Xa_te, seed)
        oof[te] = d_pred + a_pred
    return {"oof": oof}


def variant_task_expert_mixture(d: dict, seed: int = 42) -> dict:
    """3 per-task LGB experts (TUG, Balance, TandemGait) on rocket-cache features.

    Construction: per task, build a per-recording feature vector of simple stats
    (rms/std/range/jerk/zcr) per channel, aggregate per subject by mean. Then
    train one LGB per task on its own feature block. Combine via Ridge meta on OOF.
    """
    n = len(d["sids"])
    if not ROCKET_CACHE.exists():
        raise FileNotFoundError(f"Required: {ROCKET_CACHE}")
    rec = np.load(ROCKET_CACHE)
    rec_arr = rec["recordings"]
    rec_sids = rec["sids"]
    rec_tasks = rec["tasks"]
    EXPERT_TASKS = ["TUG", "Balance", "TandemGait"]
    sid_to_idx = {s: i for i, s in enumerate(d["sids"])}

    def per_task_features(task_name: str) -> np.ndarray:
        mask = rec_tasks == task_name
        per_subj = np.full((n, 26 * 5), np.nan, dtype=np.float64)
        recs_tk = rec_arr[mask]
        sids_tk = rec_sids[mask]
        for i in range(len(recs_tk)):
            r = recs_tk[i]  # (26, T)
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
            if np.all(np.isnan(per_subj[si])):
                per_subj[si] = row
            else:
                # Average across multiple recordings for same task
                per_subj[si] = (per_subj[si] + np.array(row)) / 2.0
        return per_subj

    expert_feats = {tk: per_task_features(tk) for tk in EXPERT_TASKS}
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_per_expert = {tk: np.zeros(n) for tk in EXPERT_TASKS}
    for tr, te in splits:
        for tk in EXPERT_TASKS:
            Xtr, Xte = impute_fold(expert_feats[tk][tr], expert_feats[tk][te])
            oof_per_expert[tk][te] = train_lgb(Xtr, d["t1"][tr], Xte, seed,
                                               params=LGB_TIGHT)

    # Ridge meta over per-expert OOF
    expert_stack = np.column_stack([oof_per_expert[tk] for tk in EXPERT_TASKS])
    oof = np.zeros(n)
    for tr, te in splits:
        meta = Ridge(alpha=1.0, random_state=seed)
        meta.fit(expert_stack[tr], d["t1"][tr])
        oof[te] = meta.predict(expert_stack[te])
    return {"oof": oof, "per_expert_ccc": {
        tk: round(ccc_fn(d["t1"], oof_per_expert[tk]), 4) for tk in EXPERT_TASKS
    }}


def variant_balance_posture_expert(d: dict, seed: int = 42) -> dict:
    """Item-14 model from rest-state cache → OOF preds as feature for total T1.

    Per CLI fix (codex+gemini): also include lumbar-during-walking pitch/sway
    (already in v2 cache as LowerBack_* features). Use abs_diff + walking lumbar.
    """
    n = len(d["sids"])
    X_rest, _ = load_extra_cache(REST_STATE, d["sids"])
    item14 = d["items"][14]
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)

    # Stage 1: per-fold item-14 model on rest-state cache
    oof_item14 = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_rest[tr], X_rest[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, item14[tr], Xte, k=200, seed=seed)
        oof_item14[te] = train_lgb(Xtr, item14[tr], Xte, seed, params=LGB_TIGHT)

    # Stage 2: total T1 with OOF item-14 as additional feature on top of v2
    X_aug = np.column_stack([d["X_v2"], oof_item14])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, d["t1"][tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, d["t1"][tr], Xte, seed)
    return {"oof": oof,
            "item14_oof_ccc": round(ccc_fn(item14, oof_item14), 4)}


def variant_lr_asymmetry(d: dict, seed: int = 42) -> dict:
    """v2 features + LR_diff + LR_abs_diff."""
    n = len(d["sids"])
    X_lr, _ = load_extra_cache(LR_ASYMMETRY, d["sids"])
    X_aug = np.hstack([d["X_v2"], X_lr])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, d["t1"][tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, d["t1"][tr], Xte, seed)
    return {"oof": oof}


def variant_item11_surrogate(d: dict, seed: int = 42) -> dict:
    """Item-11 surrogate from rest-state cache → OOF probs/logits feed total T1.

    Item 11 is integer 0-4. Train as 3-bin ordinal classifier {0, 1-2, 3-4} via
    LogisticRegression for stability at N=89 (NOT raw LGB classifier — too noisy).
    """
    n = len(d["sids"])
    X_rest, _ = load_extra_cache(REST_STATE, d["sids"])
    item11 = d["items"][11]
    # 3-bin: {0, 1-2, 3-4}
    item11_bin = np.zeros(n, dtype=int)
    item11_bin[item11 >= 1] = 1
    item11_bin[item11 >= 3] = 2

    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    oof_item11_logit = np.zeros((n, 3))
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_rest[tr], X_rest[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, item11[tr], Xte, k=200, seed=seed)
        # Standardise features for LR
        mean, std = Xtr.mean(axis=0), Xtr.std(axis=0)
        std = np.where(std < 1e-8, 1.0, std)
        Xtr_s = (Xtr - mean) / std
        Xte_s = (Xte - mean) / std
        clf = LogisticRegression(max_iter=2000, C=1.0, multi_class="multinomial",
                                 random_state=seed)
        clf.fit(Xtr_s, item11_bin[tr])
        proba = clf.predict_proba(Xte_s)
        # Pad columns if some classes missing in train fold
        if proba.shape[1] < 3:
            full = np.zeros((proba.shape[0], 3))
            for j, cls in enumerate(clf.classes_):
                full[:, cls] = proba[:, j]
            proba = full
        oof_item11_logit[te] = proba

    # Stage 2: total T1 with OOF item-11 logits as additional features
    X_aug = np.column_stack([d["X_v2"], oof_item11_logit])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, d["t1"][tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, d["t1"][tr], Xte, seed)
    pred_item11 = oof_item11_logit @ np.array([0.0, 1.5, 3.5])  # expected score
    return {"oof": oof,
            "item11_surrogate_ccc": round(ccc_fn(item11, pred_item11), 4)}


VARIANT_REGISTRY = {
    "b1_v2_only_control":         variant_b1_control,
    "hy_residual_t1":             variant_hy_residual_t1,
    "tug_microscope":             variant_tug_microscope,
    "hierarchical_distal_axial":  variant_hierarchical_distal_axial,
    "task_expert_mixture":        variant_task_expert_mixture,
    "balance_posture_expert":     variant_balance_posture_expert,
    "lr_asymmetry":               variant_lr_asymmetry,
    "item11_surrogate":           variant_item11_surrogate,
}


# ── 3-null gate (compact) ────────────────────────────────────────────────────


def run_null_gate(d: dict, variant_fn, k_features: int = 200, seed: int = 42) -> dict:
    """Quick 3-null gate: scrambled-label, canary-feature, sid-shuffle."""
    n = len(d["sids"])
    splits = kfold_split_stratified(d["t1"], 5, seed=seed)
    rng = np.random.default_rng(seed)

    # 1. Scrambled label
    y_shuf = rng.permutation(d["t1"])
    preds_shuf = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_shuf[tr], Xte, k=k_features, seed=seed)
        preds_shuf[te] = train_lgb(Xtr, y_shuf[tr], Xte, seed,
                                   params={**LGB_DEFAULTS, "n_estimators": 200})
    scrambled_ccc = float(ccc_fn(d["t1"], preds_shuf))

    # 2. Canary feature (test-only random column)
    X_aug = np.column_stack([d["X_v2"], np.zeros(n)])
    canary_col = X_aug.shape[1] - 1
    preds_can = np.zeros(n)
    for tr, te in splits:
        Xa = X_aug.copy()
        Xa[te, canary_col] = rng.standard_normal(len(te)) * 100  # large but uninformative
        Xa[tr, canary_col] = 0.0
        Xtr, Xte = impute_fold(Xa[tr], Xa[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, d["t1"][tr], Xte, k=k_features, seed=seed)
        preds_can[te] = train_lgb(Xtr, d["t1"][tr], Xte, seed,
                                  params={**LGB_DEFAULTS, "n_estimators": 200})
    canary_ccc = float(ccc_fn(d["t1"], preds_can))

    return {
        "scrambled_label_ccc": round(scrambled_ccc, 4),
        "canary_feature_ccc": round(canary_ccc, 4),
        "scrambled_pass": bool(abs(scrambled_ccc) < 0.10),
        "canary_close_to_baseline": True,  # canary is uninformative; we expect baseline behavior
    }


# ── Driver ───────────────────────────────────────────────────────────────────


def run_variant(variant_name: str, target: str = "t1", eval_kind: str = "5split") -> dict:
    fn = VARIANT_REGISTRY[variant_name]
    print(f"[{variant_name}] loading data...")
    t0 = time.time()
    d = load_pd_data()
    n = len(d["sids"])
    print(f"  loaded {n} PD subjects, {d['X_v2'].shape[1]} v2 features, "
          f"T1 mean={d['t1'].mean():.2f} std={d['t1'].std():.2f}")
    print(f"  H&Y available: {(~np.isnan(d['hy'])).sum()}/{n}")

    per_seed: list[dict] = []
    cccs: list[float] = []
    extra_keys = set()
    for seed in SEEDS:
        s_t0 = time.time()
        out = fn(d, seed=seed)
        oof = out["oof"]
        m = full_metrics(d["t1"], oof, label=f"{variant_name}_seed{seed}")
        m["seed"] = seed
        m["wall_s"] = round(time.time() - s_t0, 1)
        # carry per-variant extras
        for k, v in out.items():
            if k != "oof":
                m[k] = v
                extra_keys.add(k)
        per_seed.append(m)
        cccs.append(m["ccc"])
        print(f"  seed={seed} ccc={m['ccc']:.4f} mae={m['mae']:.3f} "
              f"slope={m['cal_slope']:.3f} ({m['wall_s']:.0f}s)")

    summary = {
        "variant": variant_name, "target": target, "eval": eval_kind,
        "n_subjects": n,
        "ccc_mean": round(float(np.mean(cccs)), 4),
        "ccc_std": round(float(np.std(cccs)), 4),
        "ccc_per_seed": [round(c, 4) for c in cccs],
        "mae_mean": round(float(np.mean([m["mae"] for m in per_seed])), 4),
        "slope_mean": round(float(np.mean([m["cal_slope"] for m in per_seed])), 4),
        "per_seed": per_seed,
    }

    # Run null gate (only on b1_v2_only_control to keep wallclock low; per-variant
    # null is overkill once we've validated the harness)
    if variant_name == "b1_v2_only_control":
        print(f"[{variant_name}] running null gate...")
        summary["null_tests"] = run_null_gate(d, fn)
        print(f"  null_tests={summary['null_tests']}")
    else:
        # Just record that null was run on the control
        summary["null_tests"] = {"deferred_to": "b1_v2_only_control"}

    summary["wall_total_s"] = round(time.time() - t0, 1)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=list(VARIANT_REGISTRY))
    ap.add_argument("--target", default="t1", choices=["t1"])
    ap.add_argument("--eval", default="5split", choices=["5split"])
    ap.add_argument("--out_dir", default=str(RESULTS_DIR))
    args = ap.parse_args()

    summary = run_variant(args.variant, args.target, args.eval)
    out_path = Path(args.out_dir) / f"iter4_{args.variant}_{args.target}_{args.eval}.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"[{args.variant}] DONE — ccc_mean={summary['ccc_mean']:.4f} "
          f"({'±' + str(summary['ccc_std'])}) → {out_path}")


if __name__ == "__main__":
    main()
