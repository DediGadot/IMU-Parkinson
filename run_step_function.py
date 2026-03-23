#!/usr/bin/env python3
"""run_step_function.py — Next step-function experiments beyond P5 SSL ranking.

4 proposals to push CCC beyond current SSL ranking (T1=0.868, T3=0.776):
  P6: Rank-Gauss target transformation + P5 SSL ranking
  P7: HC-anchored cumulative severity CDF (replaces pairwise ranking)
  P8: Temporal anomaly mining from HC manifold (new features)
  P9: Nested target residualization T1→ΔT2→ΔT3

Usage:
    python3 -u run_step_function.py --phase 6 --target t1
    python3 -u run_step_function.py --phase 7 --target all
    python3 -u run_step_function.py --phase all --target all --eval loocv
    python3 -u run_step_function.py --phase 5 --target all --eval loocv   # P5 baseline for comparison
"""
import argparse
import json
import os
import sys
import time
import warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.covariance import EmpiricalCovariance

warnings.filterwarnings("ignore")


# ── Auto-install ─────────────────────────────────────────────────────
def _ensure_deps():
    missing = []
    for pkg, imp in [("lightgbm", "lightgbm"), ("xgboost", "xgboost")]:
        try:
            __import__(imp)
        except ImportError:
            missing.append(pkg)
    if missing:
        import subprocess
        print(f"Installing: {' '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q"] + missing)

_ensure_deps()

import lightgbm as lgb
from xgboost import XGBRegressor, XGBRanker, XGBClassifier

from project_paths import REPO_ROOT, RESULTS_DIR, ensure_dir, results_artifact_path
sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, DATA_DIR
from updrs_columns import find_updrs_value


# ── Constants ────────────────────────────────────────────────────────
V2_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
FM_CACHE = str(results_artifact_path("fm_embeddings.npz"))
RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))
OBS_DIRECT_CACHE = str(results_artifact_path("obs_direct_subscores.json"))
PER_ITEM_CACHE = str(results_artifact_path("per_item_scores.json"))
N_CORES = min(os.cpu_count() or 4, 11)
SEEDS = [42, 123, 456, 789, 2024]
LOOCV_PROGRESS_EVERY = 10
ensure_dir(RESULTS_DIR)

# Subitem map for parsing individual UPDRS items
SUBITEMS_MAP = {
    1: None, 2: None,
    3: ["a", "b", "c", "d", "e"],
    4: ["a", "b"], 5: ["a", "b"], 6: ["a", "b"],
    7: ["a", "b"], 8: ["a", "b"],
    9: None, 10: None, 11: None, 12: None, 13: None, 14: None,
    15: ["a", "b"], 16: ["a", "b"],
    17: ["a", "b", "c", "d", "e"],
    18: None,
}

T1_ITEMS = [9, 10, 11, 12, 13, 14]
T2_ITEMS = [7, 8, 9, 10, 11, 12, 13, 14]
T2_LR_ITEMS = {7, 8}
T3_ITEMS = list(range(1, 19))

TARGET_CLIP = {"t1": (0, 24), "t2": (0, 32), "t3": (0, 59)}

DEFAULT_LGB_PARAMS = {
    "n_estimators": 2000,
    "learning_rate": 0.03,
    "max_depth": 6,
    "num_leaves": 31,
    "reg_lambda": 0.3,
    "min_data_in_leaf": 8,
    "colsample_bytree": 0.5,
    "subsample": 1.0,
    "objective": "mse",
    "val_frac": 0.15,
    "early_stopping_rounds": 100,
}


# ═══════════════════════════════════════════════════════════════════════
# METRICS
# ═══════════════════════════════════════════════════════════════════════

def lins_ccc(y_true, y_pred):
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    mu_t, mu_p = np.mean(y_true), np.mean(y_pred)
    var_t, var_p = np.var(y_true), np.var(y_pred)
    cov = np.mean((y_true - mu_t) * (y_pred - mu_p))
    denom = var_t + var_p + (mu_t - mu_p) ** 2
    return float(2 * cov / denom) if denom > 1e-12 else 0.0


def cal_slope(y_true, y_pred):
    if np.std(y_true) < 1e-8 or len(y_true) < 3:
        return 0.0
    return float(np.polyfit(y_true, y_pred, 1)[0])


def full_metrics(y_true, y_pred, target_key):
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    r = float(sp_stats.pearsonr(y_true, y_pred)[0]) if len(y_true) > 2 else 0.0
    ccc = lins_ccc(y_true, y_pred)
    slope = cal_slope(y_true, y_pred)
    if np.std(y_true) > 0 and len(y_true) > 2:
        _, intercept = np.polyfit(y_true, y_pred, 1)
    else:
        intercept = 0.0
    clip_lo, clip_hi = TARGET_CLIP[target_key]
    q25, q50, q75 = np.percentile(y_true, [25, 50, 75])
    quartile_bounds = [
        (f"Q1 (<{q25:.0f})", clip_lo, q25),
        (f"Q2 ({q25:.0f}-{q50:.0f})", q25, q50),
        (f"Q3 ({q50:.0f}-{q75:.0f})", q50, q75),
        (f"Q4 (>={q75:.0f})", q75, clip_hi + 1),
    ]
    quartiles = []
    for label, lo, hi in quartile_bounds:
        mask = (y_true >= lo) & (y_true < hi)
        if mask.sum() > 0:
            quartiles.append({
                "label": label, "n": int(mask.sum()),
                "bias": round(float(np.mean(y_pred[mask] - y_true[mask])), 3),
                "mae": round(float(np.mean(np.abs(y_true[mask] - y_pred[mask]))), 3),
            })
    return {
        "mae": round(mae, 3), "rmse": round(rmse, 3), "r": round(r, 3),
        "ccc": round(ccc, 3), "cal_slope": round(float(slope), 3),
        "cal_intercept": round(float(intercept), 3),
        "quartiles": quartiles, "n": len(y_true),
    }


# ═══════════════════════════════════════════════════════════════════════
# DATA LOADING (reused from run_compression_ablation.py)
# ═══════════════════════════════════════════════════════════════════════

def parse_per_item_scores():
    if os.path.exists(PER_ITEM_CACHE):
        with open(PER_ITEM_CACHE) as f:
            raw = json.load(f)
        result = {}
        for sid, scores in raw.items():
            result[sid] = {}
            for k, v in scores.items():
                if k.startswith("("):
                    result[sid][k] = v
                else:
                    result[sid][int(k)] = v
        return result

    print("Parsing per-item scores from clinical CSVs...")
    item_scores = {}
    for fn, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(str(DATA_DIR), fn)
        assert os.path.exists(path), f"Clinical CSV not found: {path}"
        df = pd.read_csv(path, header=1)
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            scores = {}
            for item_num in range(1, 19):
                sub = SUBITEMS_MAP[item_num]
                if sub is None:
                    val = find_updrs_value(row, df.columns, item_num)
                    if val is not None:
                        scores[item_num] = val
                    elif group == "HC":
                        scores[item_num] = 0.0
                else:
                    vals = []
                    subpart_scores = {}
                    for s in sub:
                        v = find_updrs_value(row, df.columns, item_num, s)
                        if v is not None:
                            vals.append(v)
                            subpart_scores[s] = v
                    if len(vals) == len(sub):
                        if item_num in T2_LR_ITEMS:
                            r_val = subpart_scores.get("a", 0.0)
                            l_val = subpart_scores.get("b", 0.0)
                            scores[f"({item_num}, 'R')"] = r_val
                            scores[f"({item_num}, 'L')"] = l_val
                            scores[item_num] = max(r_val, l_val)
                        else:
                            scores[item_num] = float(sum(vals))
                        for s, v in subpart_scores.items():
                            scores[f"({item_num}, '{s}')"] = v
                    elif len(vals) == 0 and group == "HC":
                        scores[item_num] = 0.0
                        if item_num in T2_LR_ITEMS:
                            scores[f"({item_num}, 'R')"] = 0.0
                            scores[f"({item_num}, 'L')"] = 0.0
                        for s in sub:
                            scores[f"({item_num}, '{s}')"] = 0.0
            if scores:
                item_scores[sid] = scores

    cache_obj = {}
    for sid, scores in item_scores.items():
        cache_obj[sid] = {str(k): v for k, v in scores.items()}
    with open(PER_ITEM_CACHE, "w") as f:
        json.dump(cache_obj, f, indent=2)
    print(f"Cached per-item scores to {PER_ITEM_CACHE} ({len(item_scores)} subjects)")
    return item_scores


def compute_target(item_scores, sid, target_key):
    if sid not in item_scores:
        return None
    scores = item_scores[sid]
    if target_key == "t1":
        items = T1_ITEMS
    elif target_key == "t2":
        items = T2_ITEMS
    else:
        raise ValueError(f"compute_target not used for T3. Got: {target_key}")
    total = 0.0
    for item in items:
        if item not in scores:
            return None
        total += scores[item]
    return total


def load_features_and_targets():
    assert os.path.exists(V2_CACHE), f"V2 cache not found: {V2_CACHE}"
    assert os.path.exists(FM_CACHE), f"FM cache not found: {FM_CACHE}"
    assert os.path.exists(RECORDING_CACHE), f"Recording cache not found: {RECORDING_CACHE}"

    v2_df = pd.read_csv(V2_CACHE)
    fm_data = np.load(FM_CACHE)
    fm_embeddings = fm_data["embeddings"]
    rec_data = np.load(RECORDING_CACHE)
    rec_sids = rec_data["sids"].tolist()

    # Aggregate FM embeddings per subject (mean)
    d_model = fm_embeddings.shape[1]
    fm_df = pd.DataFrame(fm_embeddings, columns=[f"fm_{i}" for i in range(d_model)])
    fm_df["sid"] = rec_sids
    fm_agg = fm_df.groupby("sid").mean().reset_index()
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]

    EXCLUDED_COLS = {"sid", "updrs3", "obs_subscore", "hy"}
    EXTRA_PREFIXES = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")
    v2_feat_cols = [c for c in v2_df.columns
                    if c not in EXCLUDED_COLS
                    and not any(c.startswith(p) for p in EXTRA_PREFIXES)]

    merged = v2_df[["sid", "updrs3"] + v2_feat_cols].merge(fm_agg, on="sid", how="left").fillna(0.0)
    feature_cols = v2_feat_cols + fm_cols

    item_scores = parse_per_item_scores()
    subjects = parse_clinical()
    merged["t1_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t1"))
    merged["t2_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t2"))
    merged["t3_target"] = merged["updrs3"].astype(float)

    pd_sids = {sid for sid, info in subjects.items() if info.get("group") == "PD"}
    all_sids = {sid for sid, info in subjects.items()}

    pd_mask = merged["sid"].isin(pd_sids)
    pd_valid = pd_mask & merged["t1_target"].notna() & merged["t2_target"].notna()
    pd_merged = merged[pd_valid].copy()
    pd_merged["t1_target"] = pd_merged["t1_target"].astype(np.float32)
    pd_merged["t2_target"] = pd_merged["t2_target"].astype(np.float32)
    pd_merged["t3_target"] = pd_merged["t3_target"].astype(np.float32)

    all_valid = merged["t1_target"].notna() & merged["t2_target"].notna()
    all_merged = merged[all_valid].copy()
    all_merged["t1_target"] = all_merged["t1_target"].astype(np.float32)
    all_merged["t2_target"] = all_merged["t2_target"].astype(np.float32)
    all_merged["t3_target"] = all_merged["t3_target"].astype(np.float32)
    all_merged["is_pd"] = all_merged["sid"].isin(pd_sids).astype(int)

    print(f"\nData loaded:")
    print(f"  PD subjects: {len(pd_merged)}")
    print(f"  All subjects (PD+HC): {len(all_merged)}")
    print(f"  Features: {len(feature_cols)} (v2: {len(v2_feat_cols)}, FM: {len(fm_cols)})")
    for tk in ["t1", "t2", "t3"]:
        col = f"{tk}_target"
        vals = pd_merged[col]
        print(f"  {tk.upper()}: range [{vals.min():.0f}, {vals.max():.0f}], "
              f"mean={vals.mean():.1f}, std={vals.std():.1f}")

    # Also compute per-recording FM data for P8
    fm_per_rec = {}
    for i, sid in enumerate(rec_sids):
        if sid not in fm_per_rec:
            fm_per_rec[sid] = []
        fm_per_rec[sid].append(fm_embeddings[i])

    return pd_merged, all_merged, feature_cols, subjects, item_scores, fm_per_rec


# ═══════════════════════════════════════════════════════════════════════
# SHARED TRAINING COMPONENTS
# ═══════════════════════════════════════════════════════════════════════

def feature_select(X, y, names, k=500):
    k = min(k, X.shape[1])
    sel = XGBRegressor(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
        objective="reg:absoluteerror",
    )
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def train_lgb(Xd, yd, Xt, seed, params=None, sample_weight=None):
    p = dict(DEFAULT_LGB_PARAMS)
    if params:
        p.update(params)
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * p.get("val_frac", 0.15)))
    m = lgb.LGBMRegressor(
        n_estimators=p["n_estimators"],
        learning_rate=p["learning_rate"],
        max_depth=p["max_depth"],
        num_leaves=p["num_leaves"],
        reg_lambda=p["reg_lambda"],
        min_data_in_leaf=p["min_data_in_leaf"],
        colsample_bytree=p["colsample_bytree"],
        subsample=p["subsample"],
        random_state=seed,
        n_jobs=N_CORES,
        objective=p["objective"],
        verbose=-1,
    )
    fit_kwargs = {
        "X": Xd[idx[nv:]],
        "y": yd[idx[nv:]],
        "eval_set": [(Xd[idx[:nv]], yd[idx[:nv]])],
        "callbacks": [lgb.early_stopping(p["early_stopping_rounds"], verbose=False)],
    }
    if sample_weight is not None:
        fit_kwargs["sample_weight"] = sample_weight[idx[nv:]]
    m.fit(**fit_kwargs)
    return m.predict(Xt)


def train_lgb_ensemble(Xd, yd, Xt, clip_lo, clip_hi, params=None, sample_weight=None):
    preds = []
    for s in SEEDS:
        p = train_lgb(Xd, yd, Xt, s, params=params, sample_weight=sample_weight)
        preds.append(np.clip(p, clip_lo, clip_hi))
    return np.mean(preds, axis=0)


def _target_bin(score, target_key):
    clip_lo, clip_hi = TARGET_CLIP[target_key]
    rng = clip_hi - clip_lo
    if score < clip_lo + rng * 0.25:
        return 0
    elif score < clip_lo + rng * 0.5:
        return 1
    elif score < clip_lo + rng * 0.75:
        return 2
    else:
        return 3


def gen_split(pd_merged, seed, target_key):
    sids = pd_merged["sid"].values
    target_col = f"{target_key}_target"
    bins = pd_merged[target_col].apply(lambda x: _target_bin(x, target_key)).values
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    di, ti = next(sss.split(sids, bins))
    return sids[di].tolist(), sids[ti].tolist()


# ═══════════════════════════════════════════════════════════════════════
# P5: SSL RANKING BASELINE (copied for comparison)
# ═══════════════════════════════════════════════════════════════════════

def run_p5(pd_merged, all_merged, feature_cols, target_key, eval_mode):
    """P5: Semi-supervised ranking from HC (baseline for comparison)."""
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    all_sids = all_merged["sid"].values
    all_targets = all_merged[target_col].values.astype(np.float32)
    is_pd = all_merged["is_pd"].values

    rank_labels = np.zeros(len(all_sids), dtype=np.int32)
    pd_indices = np.where(is_pd == 1)[0]
    pd_order = np.argsort(all_targets[pd_indices])
    for rank, idx in enumerate(pd_order):
        rank_labels[pd_indices[idx]] = rank + 1

    X_all = all_merged[feature_cols].values.astype(np.float32)

    def _p5_predict(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra):
        sids_train = extra["sids_train"]
        sids_test = extra["sids_test"]
        sel_idx = extra["sel_idx"]

        X_all_sel = X_all[:, sel_idx]
        group_sizes = np.array([len(X_all_sel)])

        all_leaf_features = []
        for seed in SEEDS[:3]:
            ranker = XGBRanker(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
                objective="rank:pairwise",
            )
            ranker.fit(X_all_sel, rank_labels, group=group_sizes)

            sid_to_all_idx = {s: i for i, s in enumerate(all_sids)}
            train_all_indices = [sid_to_all_idx[s] for s in sids_train if s in sid_to_all_idx]
            test_all_indices = [sid_to_all_idx[s] for s in sids_test if s in sid_to_all_idx]

            train_leaves = ranker.apply(X_all_sel[train_all_indices])
            test_leaves = ranker.apply(X_all_sel[test_all_indices])
            all_leaf_features.append((train_leaves, test_leaves))

        train_leaf_cat = np.hstack([lf[0] for lf in all_leaf_features]).astype(np.float32)
        test_leaf_cat = np.hstack([lf[1] for lf in all_leaf_features]).astype(np.float32)

        Xd_combined = np.hstack([Xd_sel, train_leaf_cat])
        Xt_combined = np.hstack([Xt_sel, test_leaf_cat])

        preds = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd, Xt_combined, s)
            preds.append(np.clip(p, clip_lo, clip_hi))
        return np.mean(preds, axis=0)

    if eval_mode == "5split":
        return _run_5split(pd_merged, feature_cols, target_key, target_col,
                           clip_lo, clip_hi, _p5_predict,
                           need_sids=True, need_sel_idx=True)
    else:
        return _run_loocv(pd_merged, feature_cols, target_key, target_col,
                          clip_lo, clip_hi, _p5_predict,
                          need_sids=True, need_sel_idx=True)


# ═══════════════════════════════════════════════════════════════════════
# P6: RANK-GAUSS TARGET TRANSFORMATION + P5 SSL RANKING
# ═══════════════════════════════════════════════════════════════════════

def rank_gauss_transform(y_train):
    """Map targets to Gaussian via rank → uniform → inverse-normal CDF.

    Returns: y_transformed, and the sorted unique training targets for inverse mapping.
    """
    n = len(y_train)
    # Rank (1-based, average ties)
    ranks = sp_stats.rankdata(y_train, method="average")
    # Map to (0, 1) uniform — Blom's offset for stability
    uniform = (ranks - 0.375) / (n + 0.25)
    # Inverse normal CDF
    y_gauss = sp_stats.norm.ppf(uniform)
    return y_gauss.astype(np.float32)


def rank_gauss_inverse(y_gauss_pred, y_train_original):
    """Map Gaussian predictions back to original scale via empirical CDF.

    predicted_percentile = Phi(y_gauss_pred)
    final_score = quantile(y_train_original, predicted_percentile)
    """
    # Get predicted percentile (CDF of standard normal)
    predicted_pct = sp_stats.norm.cdf(y_gauss_pred)
    # Clamp to avoid extrapolation beyond training range
    predicted_pct = np.clip(predicted_pct, 0.001, 0.999)
    # Map through empirical inverse CDF of training targets
    sorted_train = np.sort(y_train_original)
    n = len(sorted_train)
    # Interpolate: percentile → value
    train_pcts = (np.arange(1, n + 1) - 0.5) / n
    result = np.interp(predicted_pct, train_pcts, sorted_train)
    return result.astype(np.float32)


def run_p6(pd_merged, all_merged, feature_cols, target_key, eval_mode):
    """P6: Rank-Gauss target transformation + P5 SSL ranking.

    Key insight: MSE on original scale compresses predictions toward the mean.
    Rank-Gauss maps targets to Gaussian, where MSE treats all quantiles equally.
    Inverse-mapping through empirical CDF structurally preserves the training
    distribution's variance.
    """
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    all_sids = all_merged["sid"].values
    all_targets = all_merged[target_col].values.astype(np.float32)
    is_pd = all_merged["is_pd"].values

    # Build ranking labels (same as P5)
    rank_labels = np.zeros(len(all_sids), dtype=np.int32)
    pd_indices = np.where(is_pd == 1)[0]
    pd_order = np.argsort(all_targets[pd_indices])
    for rank, idx in enumerate(pd_order):
        rank_labels[pd_indices[idx]] = rank + 1

    X_all = all_merged[feature_cols].values.astype(np.float32)

    def _p6_predict(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra):
        sids_train = extra["sids_train"]
        sids_test = extra["sids_test"]
        sel_idx = extra["sel_idx"]

        # Stage 1: Same SSL ranking as P5
        X_all_sel = X_all[:, sel_idx]
        group_sizes = np.array([len(X_all_sel)])

        all_leaf_features = []
        for seed in SEEDS[:3]:
            ranker = XGBRanker(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
                objective="rank:pairwise",
            )
            ranker.fit(X_all_sel, rank_labels, group=group_sizes)

            sid_to_all_idx = {s: i for i, s in enumerate(all_sids)}
            train_all_indices = [sid_to_all_idx[s] for s in sids_train if s in sid_to_all_idx]
            test_all_indices = [sid_to_all_idx[s] for s in sids_test if s in sid_to_all_idx]

            train_leaves = ranker.apply(X_all_sel[train_all_indices])
            test_leaves = ranker.apply(X_all_sel[test_all_indices])
            all_leaf_features.append((train_leaves, test_leaves))

        train_leaf_cat = np.hstack([lf[0] for lf in all_leaf_features]).astype(np.float32)
        test_leaf_cat = np.hstack([lf[1] for lf in all_leaf_features]).astype(np.float32)

        Xd_combined = np.hstack([Xd_sel, train_leaf_cat])
        Xt_combined = np.hstack([Xt_sel, test_leaf_cat])

        # Stage 2: Rank-Gauss transformation
        yd_gauss = rank_gauss_transform(yd)

        # Stage 3: Train LGB ensemble on Gaussian targets
        preds_gauss = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd_gauss, Xt_combined, s)
            preds_gauss.append(p)
        mean_gauss = np.mean(preds_gauss, axis=0)

        # Stage 4: Inverse-map through empirical CDF
        preds_original = rank_gauss_inverse(mean_gauss, yd)
        return np.clip(preds_original, clip_lo, clip_hi)

    if eval_mode == "5split":
        return _run_5split(pd_merged, feature_cols, target_key, target_col,
                           clip_lo, clip_hi, _p6_predict,
                           need_sids=True, need_sel_idx=True)
    else:
        return _run_loocv(pd_merged, feature_cols, target_key, target_col,
                          clip_lo, clip_hi, _p6_predict,
                          need_sids=True, need_sel_idx=True)


# ═══════════════════════════════════════════════════════════════════════
# P7: HC-ANCHORED CUMULATIVE SEVERITY CDF
# ═══════════════════════════════════════════════════════════════════════

def run_p7(pd_merged, all_merged, feature_cols, target_key, eval_mode):
    """P7: HC-Anchored Cumulative Severity CDF.

    Instead of pairwise ranking, train K binary threshold classifiers:
    P(score >= tau_k) with HC providing dense P=0 anchors for all tau > ~3.
    Enforce monotonicity, integrate exceedance function to get score estimate.

    This learns SPACING (not just ordering) — directly attacks the calibration
    slope gap (0.69 vs ideal 1.0).
    """
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    all_sids = all_merged["sid"].values
    all_targets = all_merged[target_col].values.astype(np.float32)
    is_pd = all_merged["is_pd"].values

    X_all = all_merged[feature_cols].values.astype(np.float32)

    def _p7_predict(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra):
        sids_train = extra["sids_train"]
        sids_test = extra["sids_test"]
        sel_idx = extra["sel_idx"]

        X_all_sel = X_all[:, sel_idx]
        sid_to_all_idx = {s: i for i, s in enumerate(all_sids)}
        train_all_indices = [sid_to_all_idx[s] for s in sids_train if s in sid_to_all_idx]
        test_all_indices = [sid_to_all_idx[s] for s in sids_test if s in sid_to_all_idx]

        # Get ALL subjects' features and targets for threshold training
        X_all_train = X_all_sel[train_all_indices]
        y_all_train = all_targets[train_all_indices]
        is_pd_train = is_pd[train_all_indices]

        # HC subjects + PD training subjects for threshold models
        # Include ALL HC subjects (they are always available)
        hc_indices_all = np.where(is_pd == 0)[0]
        X_hc = X_all_sel[hc_indices_all]
        y_hc = all_targets[hc_indices_all]

        # PD training subjects
        X_pd_train = Xd_sel
        y_pd_train = yd

        # Combine HC + PD train for threshold models
        X_thresh_train = np.vstack([X_hc, X_pd_train])
        y_thresh_train = np.concatenate([y_hc, y_pd_train])

        # Define thresholds from PD training distribution
        n_thresholds = 16
        quantiles = np.linspace(0.05, 0.95, n_thresholds)
        taus = np.quantile(y_pd_train, quantiles)
        # Remove duplicate thresholds (can happen with discrete scores)
        taus = np.unique(taus)

        # Train binary classifiers for each threshold
        exceedance_probs_test = []
        exceedance_probs_train_pd = []

        for tau in taus:
            # Binary labels: score >= tau
            y_binary = (y_thresh_train >= tau).astype(np.int32)

            # Skip if too few positives or negatives
            if y_binary.sum() < 3 or (1 - y_binary).sum() < 3:
                continue

            # 3-seed XGBClassifier ensemble
            proba_test_seeds = []
            proba_train_pd_seeds = []
            for seed in SEEDS[:3]:
                clf = XGBClassifier(
                    n_estimators=200, max_depth=3, learning_rate=0.05,
                    reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                    use_label_encoder=False, eval_metric="logloss",
                    verbosity=0,
                )
                clf.fit(X_thresh_train, y_binary)
                proba_test_seeds.append(clf.predict_proba(Xt_sel)[:, 1])
                proba_train_pd_seeds.append(clf.predict_proba(X_pd_train)[:, 1])

            exceedance_probs_test.append(np.mean(proba_test_seeds, axis=0))
            exceedance_probs_train_pd.append(np.mean(proba_train_pd_seeds, axis=0))

        if len(exceedance_probs_test) < 2:
            # Fallback to simple ensemble if too few thresholds
            return train_lgb_ensemble(Xd_sel, yd, Xt_sel, clip_lo, clip_hi)

        # Stack exceedance probabilities: shape (n_thresholds, n_test)
        P_test = np.array(exceedance_probs_test)  # (K, n_test)
        P_train_pd = np.array(exceedance_probs_train_pd)  # (K, n_train_pd)

        # Enforce monotonicity: P(Y >= tau_k+1) <= P(Y >= tau_k)
        for i in range(1, len(P_test)):
            P_test[i] = np.minimum(P_test[i], P_test[i - 1])
            P_train_pd[i] = np.minimum(P_train_pd[i], P_train_pd[i - 1])

        # Numerical integration: E[Y] ≈ clip_lo + sum(delta_tau * P(Y >= tau))
        # More precisely: integral over the exceedance function
        extended_taus = np.concatenate([[clip_lo], taus[:len(P_test)], [clip_hi]])
        score_estimate_test = np.full(P_test.shape[1], float(clip_lo))
        score_estimate_train_pd = np.full(P_train_pd.shape[1], float(clip_lo))

        for i in range(len(P_test)):
            delta_tau = extended_taus[i + 1] - extended_taus[i]
            score_estimate_test += delta_tau * P_test[i]
            score_estimate_train_pd += delta_tau * P_train_pd[i]

        # Add tail contribution (above last threshold to clip_hi)
        tail_delta = clip_hi - extended_taus[-2]
        score_estimate_test += tail_delta * P_test[-1]
        score_estimate_train_pd += tail_delta * P_train_pd[-1]

        # Use CDF scores as features for final LGB (hybrid approach)
        cdf_features_train = P_train_pd.T  # (n_train_pd, K)
        cdf_features_test = P_test.T  # (n_test, K)

        # Add the integral estimate as a feature too
        cdf_features_train = np.hstack([
            cdf_features_train,
            score_estimate_train_pd.reshape(-1, 1),
        ])
        cdf_features_test = np.hstack([
            cdf_features_test,
            score_estimate_test.reshape(-1, 1),
        ])

        # Combine: original features + CDF features
        Xd_combined = np.hstack([Xd_sel, cdf_features_train])
        Xt_combined = np.hstack([Xt_sel, cdf_features_test])

        # Train final LGB ensemble on original targets
        preds = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd, Xt_combined, s)
            preds.append(np.clip(p, clip_lo, clip_hi))
        return np.mean(preds, axis=0)

    if eval_mode == "5split":
        return _run_5split(pd_merged, feature_cols, target_key, target_col,
                           clip_lo, clip_hi, _p7_predict,
                           need_sids=True, need_sel_idx=True)
    else:
        return _run_loocv(pd_merged, feature_cols, target_key, target_col,
                          clip_lo, clip_hi, _p7_predict,
                          need_sids=True, need_sel_idx=True)


# ═══════════════════════════════════════════════════════════════════════
# P8: TEMPORAL ANOMALY MINING FROM HC MANIFOLD
# ═══════════════════════════════════════════════════════════════════════

def compute_anomaly_features(fm_per_rec, pd_sids, hc_sids):
    """Compute temporal anomaly features: per-recording FM embeddings scored
    against the HC manifold (Mahalanobis distance).

    For each PD subject, extract:
    - max_anomaly: worst motor episode
    - p90_anomaly: 90th percentile anomaly
    - mean_anomaly: average anomaly
    - std_anomaly: motor fluctuation / instability
    - frac_above_p75: fraction of recordings above 75th pct HC distance

    For HC subjects: same features (they should all be low).
    """
    print("  Computing temporal anomaly features from HC manifold...")

    # Collect all HC embeddings to build the "healthy" distribution
    hc_embeddings = []
    for sid in hc_sids:
        if sid in fm_per_rec:
            for emb in fm_per_rec[sid]:
                hc_embeddings.append(emb)

    if len(hc_embeddings) < 10:
        raise ValueError(f"Too few HC embeddings: {len(hc_embeddings)}")

    hc_matrix = np.array(hc_embeddings, dtype=np.float64)
    print(f"  HC embeddings: {hc_matrix.shape[0]} recordings from {len(hc_sids)} subjects")

    # PCA to reduce dimensionality (768 → 32) to avoid singular covariance
    from sklearn.decomposition import PCA
    n_components = min(32, hc_matrix.shape[0] - 1, hc_matrix.shape[1])
    pca = PCA(n_components=n_components, random_state=42)
    hc_pca = pca.fit_transform(hc_matrix)

    # Fit Mahalanobis distance model on HC
    cov_model = EmpiricalCovariance()
    cov_model.fit(hc_pca)
    hc_center = cov_model.location_
    hc_precision = cov_model.precision_

    # Compute distances for HC (to establish baseline distribution)
    hc_distances = cov_model.mahalanobis(hc_pca)
    hc_p75 = np.percentile(hc_distances, 75)
    print(f"  HC Mahalanobis: mean={np.mean(hc_distances):.2f}, "
          f"std={np.std(hc_distances):.2f}, p75={hc_p75:.2f}")

    # Compute features for each subject
    all_sids_list = list(set(list(pd_sids) + list(hc_sids)))
    anomaly_features = {}

    for sid in all_sids_list:
        if sid not in fm_per_rec or len(fm_per_rec[sid]) == 0:
            continue

        embeddings = np.array(fm_per_rec[sid], dtype=np.float64)
        embeddings_pca = pca.transform(embeddings)
        distances = cov_model.mahalanobis(embeddings_pca)

        # Clip extreme distances for stability
        distances = np.clip(distances, 0, np.percentile(hc_distances, 99.5) * 5)

        anomaly_features[sid] = {
            "max_anomaly": float(np.max(distances)),
            "p90_anomaly": float(np.percentile(distances, 90)),
            "p75_anomaly": float(np.percentile(distances, 75)),
            "mean_anomaly": float(np.mean(distances)),
            "std_anomaly": float(np.std(distances)),
            "cv_anomaly": float(np.std(distances) / (np.mean(distances) + 1e-8)),
            "frac_above_hc_p75": float(np.mean(distances > hc_p75)),
            "n_recordings": len(distances),
            "range_anomaly": float(np.max(distances) - np.min(distances)),
        }

    print(f"  Anomaly features computed for {len(anomaly_features)} subjects")
    return anomaly_features


def run_p8(pd_merged, all_merged, feature_cols, target_key, eval_mode, fm_per_rec):
    """P8: Temporal anomaly mining + P5 SSL ranking.

    New features: per-recording distances from HC manifold (Mahalanobis).
    Captures episodic motor failures that mean-pooling suppresses.
    Combined with P5 leaf features.
    """
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    all_sids_arr = all_merged["sid"].values
    all_targets = all_merged[target_col].values.astype(np.float32)
    is_pd = all_merged["is_pd"].values

    # Build ranking labels (same as P5)
    rank_labels = np.zeros(len(all_sids_arr), dtype=np.int32)
    pd_indices = np.where(is_pd == 1)[0]
    pd_order = np.argsort(all_targets[pd_indices])
    for rank, idx in enumerate(pd_order):
        rank_labels[pd_indices[idx]] = rank + 1

    X_all = all_merged[feature_cols].values.astype(np.float32)

    # Compute anomaly features for all subjects
    pd_sids_set = set(pd_merged["sid"].values)
    hc_sids_set = set(all_sids_arr) - pd_sids_set
    anomaly_feats = compute_anomaly_features(fm_per_rec, pd_sids_set, hc_sids_set)

    # Add anomaly features to feature matrices
    anomaly_col_names = ["max_anomaly", "p90_anomaly", "p75_anomaly", "mean_anomaly",
                         "std_anomaly", "cv_anomaly", "frac_above_hc_p75",
                         "range_anomaly"]

    def _get_anomaly_row(sid):
        if sid in anomaly_feats:
            return [anomaly_feats[sid][c] for c in anomaly_col_names]
        return [0.0] * len(anomaly_col_names)

    # Augment pd_merged features
    pd_anomaly = np.array([_get_anomaly_row(s) for s in pd_merged["sid"].values], dtype=np.float32)
    all_anomaly = np.array([_get_anomaly_row(s) for s in all_sids_arr], dtype=np.float32)

    extended_feature_cols = list(feature_cols) + [f"anom_{c}" for c in anomaly_col_names]
    X_pd_ext = np.hstack([pd_merged[feature_cols].values.astype(np.float32), pd_anomaly])
    X_all_ext = np.hstack([X_all, all_anomaly])

    def _p8_predict(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra):
        sids_train = extra["sids_train"]
        sids_test = extra["sids_test"]
        sel_idx = extra["sel_idx"]

        # Use extended features for ranking too
        X_all_sel = X_all_ext[:, sel_idx]
        group_sizes = np.array([len(X_all_sel)])

        all_leaf_features = []
        for seed in SEEDS[:3]:
            ranker = XGBRanker(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
                objective="rank:pairwise",
            )
            ranker.fit(X_all_sel, rank_labels, group=group_sizes)

            sid_to_all_idx = {s: i for i, s in enumerate(all_sids_arr)}
            train_all_indices = [sid_to_all_idx[s] for s in sids_train if s in sid_to_all_idx]
            test_all_indices = [sid_to_all_idx[s] for s in sids_test if s in sid_to_all_idx]

            train_leaves = ranker.apply(X_all_sel[train_all_indices])
            test_leaves = ranker.apply(X_all_sel[test_all_indices])
            all_leaf_features.append((train_leaves, test_leaves))

        train_leaf_cat = np.hstack([lf[0] for lf in all_leaf_features]).astype(np.float32)
        test_leaf_cat = np.hstack([lf[1] for lf in all_leaf_features]).astype(np.float32)

        Xd_combined = np.hstack([Xd_sel, train_leaf_cat])
        Xt_combined = np.hstack([Xt_sel, test_leaf_cat])

        preds = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd, Xt_combined, s)
            preds.append(np.clip(p, clip_lo, clip_hi))
        return np.mean(preds, axis=0)

    # Override pd_merged features with extended version
    pd_ext = pd_merged.copy()
    for i, col in enumerate(anomaly_col_names):
        pd_ext[f"anom_{col}"] = pd_anomaly[:, i]

    if eval_mode == "5split":
        return _run_5split(pd_ext, extended_feature_cols, target_key, target_col,
                           clip_lo, clip_hi, _p8_predict,
                           need_sids=True, need_sel_idx=True)
    else:
        return _run_loocv(pd_ext, extended_feature_cols, target_key, target_col,
                          clip_lo, clip_hi, _p8_predict,
                          need_sids=True, need_sel_idx=True)


# ═══════════════════════════════════════════════════════════════════════
# P9: NESTED TARGET RESIDUALIZATION T1→ΔT2→ΔT3
# ═══════════════════════════════════════════════════════════════════════

def run_p9(pd_merged, all_merged, feature_cols, target_key, eval_mode):
    """P9: Nested target residualization.

    Only meaningful for T2 and T3:
    - T2_hat = T1_hat + max(0, delta21_hat)
    - T3_hat = T2_hat + max(0, delta32_hat)

    For T1: falls back to P5.

    Uses SSL ranking for each stage independently.
    """
    if target_key == "t1":
        print("  P9: T1 falls back to P5 (no decomposition needed)")
        return run_p5(pd_merged, all_merged, feature_cols, target_key, eval_mode)

    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    all_sids_arr = all_merged["sid"].values
    all_targets_t1 = all_merged["t1_target"].values.astype(np.float32)
    all_targets_t2 = all_merged["t2_target"].values.astype(np.float32)
    all_targets_t3 = all_merged["t3_target"].values.astype(np.float32)
    is_pd = all_merged["is_pd"].values

    X_all = all_merged[feature_cols].values.astype(np.float32)

    def _build_rank_labels(targets):
        labels = np.zeros(len(all_sids_arr), dtype=np.int32)
        pi = np.where(is_pd == 1)[0]
        po = np.argsort(targets[pi])
        for rank, idx in enumerate(po):
            labels[pi[idx]] = rank + 1
        return labels

    rank_labels_t1 = _build_rank_labels(all_targets_t1)
    rank_labels_t2 = _build_rank_labels(all_targets_t2)
    rank_labels_t3 = _build_rank_labels(all_targets_t3)

    def _ssl_leaf_features(X_sel, rank_labels_used, sids_train, sids_test):
        """Extract SSL leaf features for a given ranking target."""
        group_sizes = np.array([len(X_sel)])
        all_leaf_features = []
        for seed in SEEDS[:3]:
            ranker = XGBRanker(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
                objective="rank:pairwise",
            )
            ranker.fit(X_sel, rank_labels_used, group=group_sizes)

            sid_to_all_idx = {s: i for i, s in enumerate(all_sids_arr)}
            train_all_indices = [sid_to_all_idx[s] for s in sids_train if s in sid_to_all_idx]
            test_all_indices = [sid_to_all_idx[s] for s in sids_test if s in sid_to_all_idx]

            train_leaves = ranker.apply(X_sel[train_all_indices])
            test_leaves = ranker.apply(X_sel[test_all_indices])
            all_leaf_features.append((train_leaves, test_leaves))

        train_cat = np.hstack([lf[0] for lf in all_leaf_features]).astype(np.float32)
        test_cat = np.hstack([lf[1] for lf in all_leaf_features]).astype(np.float32)
        return train_cat, test_cat

    def _p9_predict(Xd_sel, yd_unused, Xt_sel, clip_lo, clip_hi, extra):
        sids_train = extra["sids_train"]
        sids_test = extra["sids_test"]
        sel_idx = extra["sel_idx"]

        X_all_sel = X_all[:, sel_idx]

        # Get all training targets
        pd_train_mask = pd_merged["sid"].isin(sids_train)
        pd_test_mask = pd_merged["sid"].isin(sids_test)
        yd_t1 = pd_merged.loc[pd_train_mask, "t1_target"].values.astype(np.float32)
        yd_t2 = pd_merged.loc[pd_train_mask, "t2_target"].values.astype(np.float32)
        yd_t3 = pd_merged.loc[pd_train_mask, "t3_target"].values.astype(np.float32)

        # Stage A: Predict T1 with SSL ranking
        train_leaf_t1, test_leaf_t1 = _ssl_leaf_features(
            X_all_sel, rank_labels_t1, sids_train, sids_test)
        Xd_t1 = np.hstack([Xd_sel, train_leaf_t1])
        Xt_t1 = np.hstack([Xt_sel, test_leaf_t1])

        t1_preds_train = []
        t1_preds_test = []
        for s in SEEDS:
            p_tr = train_lgb(Xd_t1, yd_t1, Xd_t1, s)
            p_te = train_lgb(Xd_t1, yd_t1, Xt_t1, s)
            t1_preds_train.append(np.clip(p_tr, 0, 24))
            t1_preds_test.append(np.clip(p_te, 0, 24))
        t1_hat_train = np.mean(t1_preds_train, axis=0)
        t1_hat_test = np.mean(t1_preds_test, axis=0)

        if target_key == "t2":
            # Stage B: Predict delta21 = T2 - T1 >= 0
            delta21_train = np.maximum(0, yd_t2 - yd_t1)

            train_leaf_t2, test_leaf_t2 = _ssl_leaf_features(
                X_all_sel, rank_labels_t2, sids_train, sids_test)

            # Add T1 prediction as feature
            Xd_d21 = np.hstack([Xd_sel, train_leaf_t2, t1_hat_train.reshape(-1, 1)])
            Xt_d21 = np.hstack([Xt_sel, test_leaf_t2, t1_hat_test.reshape(-1, 1)])

            d21_preds = []
            for s in SEEDS:
                p = train_lgb(Xd_d21, delta21_train, Xt_d21, s)
                d21_preds.append(np.maximum(0, p))  # Non-negative residual
            d21_hat = np.mean(d21_preds, axis=0)

            final_pred = t1_hat_test + d21_hat
            return np.clip(final_pred, clip_lo, clip_hi)

        elif target_key == "t3":
            # Stage B: Predict delta21
            delta21_train = np.maximum(0, yd_t2 - yd_t1)

            train_leaf_t2, test_leaf_t2 = _ssl_leaf_features(
                X_all_sel, rank_labels_t2, sids_train, sids_test)

            Xd_d21 = np.hstack([Xd_sel, train_leaf_t2, t1_hat_train.reshape(-1, 1)])
            Xt_d21 = np.hstack([Xt_sel, test_leaf_t2, t1_hat_test.reshape(-1, 1)])

            d21_preds_train = []
            d21_preds_test = []
            for s in SEEDS:
                p_tr = train_lgb(Xd_d21, delta21_train, Xd_d21, s)
                p_te = train_lgb(Xd_d21, delta21_train, Xt_d21, s)
                d21_preds_train.append(np.maximum(0, p_tr))
                d21_preds_test.append(np.maximum(0, p_te))
            d21_hat_train = np.mean(d21_preds_train, axis=0)
            d21_hat_test = np.mean(d21_preds_test, axis=0)

            t2_hat_train = t1_hat_train + d21_hat_train
            t2_hat_test = t1_hat_test + d21_hat_test

            # Stage C: Predict delta32 = T3 - T2 >= 0
            delta32_train = np.maximum(0, yd_t3 - yd_t2)

            train_leaf_t3, test_leaf_t3 = _ssl_leaf_features(
                X_all_sel, rank_labels_t3, sids_train, sids_test)

            Xd_d32 = np.hstack([Xd_sel, train_leaf_t3,
                                 t1_hat_train.reshape(-1, 1),
                                 t2_hat_train.reshape(-1, 1)])
            Xt_d32 = np.hstack([Xt_sel, test_leaf_t3,
                                 t1_hat_test.reshape(-1, 1),
                                 t2_hat_test.reshape(-1, 1)])

            d32_preds = []
            for s in SEEDS:
                p = train_lgb(Xd_d32, delta32_train, Xt_d32, s)
                d32_preds.append(np.maximum(0, p))
            d32_hat = np.mean(d32_preds, axis=0)

            final_pred = t2_hat_test + d32_hat
            return np.clip(final_pred, clip_lo, clip_hi)

    if eval_mode == "5split":
        return _run_5split(pd_merged, feature_cols, target_key, target_col,
                           clip_lo, clip_hi, _p9_predict,
                           need_sids=True, need_sel_idx=True)
    else:
        return _run_loocv(pd_merged, feature_cols, target_key, target_col,
                          clip_lo, clip_hi, _p9_predict,
                          need_sids=True, need_sel_idx=True)


# ═══════════════════════════════════════════════════════════════════════
# P10: COMBINED BEST — P6 (Rank-Gauss) + P8 (Anomaly Features)
# ═══════════════════════════════════════════════════════════════════════

def run_p10(pd_merged, all_merged, feature_cols, target_key, eval_mode, fm_per_rec):
    """P10: Rank-Gauss + Temporal Anomaly + SSL Ranking combined."""
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    all_sids_arr = all_merged["sid"].values
    all_targets = all_merged[target_col].values.astype(np.float32)
    is_pd = all_merged["is_pd"].values

    rank_labels = np.zeros(len(all_sids_arr), dtype=np.int32)
    pd_indices = np.where(is_pd == 1)[0]
    pd_order = np.argsort(all_targets[pd_indices])
    for rank, idx in enumerate(pd_order):
        rank_labels[pd_indices[idx]] = rank + 1

    X_all = all_merged[feature_cols].values.astype(np.float32)

    # Compute anomaly features
    pd_sids_set = set(pd_merged["sid"].values)
    hc_sids_set = set(all_sids_arr) - pd_sids_set
    anomaly_feats = compute_anomaly_features(fm_per_rec, pd_sids_set, hc_sids_set)

    anomaly_col_names = ["max_anomaly", "p90_anomaly", "p75_anomaly", "mean_anomaly",
                         "std_anomaly", "cv_anomaly", "frac_above_hc_p75", "range_anomaly"]

    def _get_anomaly_row(sid):
        if sid in anomaly_feats:
            return [anomaly_feats[sid][c] for c in anomaly_col_names]
        return [0.0] * len(anomaly_col_names)

    pd_anomaly = np.array([_get_anomaly_row(s) for s in pd_merged["sid"].values], dtype=np.float32)
    all_anomaly = np.array([_get_anomaly_row(s) for s in all_sids_arr], dtype=np.float32)

    extended_feature_cols = list(feature_cols) + [f"anom_{c}" for c in anomaly_col_names]
    X_all_ext = np.hstack([X_all, all_anomaly])

    def _p10_predict(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra):
        sids_train = extra["sids_train"]
        sids_test = extra["sids_test"]
        sel_idx = extra["sel_idx"]

        X_all_sel = X_all_ext[:, sel_idx]
        group_sizes = np.array([len(X_all_sel)])

        all_leaf_features = []
        for seed in SEEDS[:3]:
            ranker = XGBRanker(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
                objective="rank:pairwise",
            )
            ranker.fit(X_all_sel, rank_labels, group=group_sizes)

            sid_to_all_idx = {s: i for i, s in enumerate(all_sids_arr)}
            train_all_indices = [sid_to_all_idx[s] for s in sids_train if s in sid_to_all_idx]
            test_all_indices = [sid_to_all_idx[s] for s in sids_test if s in sid_to_all_idx]

            train_leaves = ranker.apply(X_all_sel[train_all_indices])
            test_leaves = ranker.apply(X_all_sel[test_all_indices])
            all_leaf_features.append((train_leaves, test_leaves))

        train_leaf_cat = np.hstack([lf[0] for lf in all_leaf_features]).astype(np.float32)
        test_leaf_cat = np.hstack([lf[1] for lf in all_leaf_features]).astype(np.float32)

        Xd_combined = np.hstack([Xd_sel, train_leaf_cat])
        Xt_combined = np.hstack([Xt_sel, test_leaf_cat])

        # Rank-Gauss transformation
        yd_gauss = rank_gauss_transform(yd)

        preds_gauss = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd_gauss, Xt_combined, s)
            preds_gauss.append(p)
        mean_gauss = np.mean(preds_gauss, axis=0)

        preds_original = rank_gauss_inverse(mean_gauss, yd)
        return np.clip(preds_original, clip_lo, clip_hi)

    pd_ext = pd_merged.copy()
    for i, col in enumerate(anomaly_col_names):
        pd_ext[f"anom_{col}"] = pd_anomaly[:, i]

    if eval_mode == "5split":
        return _run_5split(pd_ext, extended_feature_cols, target_key, target_col,
                           clip_lo, clip_hi, _p10_predict,
                           need_sids=True, need_sel_idx=True)
    else:
        return _run_loocv(pd_ext, extended_feature_cols, target_key, target_col,
                          clip_lo, clip_hi, _p10_predict,
                          need_sids=True, need_sel_idx=True)


# ═══════════════════════════════════════════════════════════════════════
# GENERIC EVAL RUNNERS
# ═══════════════════════════════════════════════════════════════════════

def _run_5split(pd_merged, feature_cols, target_key, target_col,
                clip_lo, clip_hi, predict_fn, need_sids=False,
                need_sel_idx=False, extra_static=None):
    t0 = time.time()
    n_splits = 5
    all_true = []
    all_pred = []

    for split_i in range(1, n_splits + 1):
        dev_s, test_s = gen_split(pd_merged, split_i, target_key)
        dm = pd_merged["sid"].isin(dev_s)
        tm = pd_merged["sid"].isin(test_s)
        Xd = pd_merged.loc[dm, feature_cols].values.astype(np.float32)
        yd = pd_merged.loc[dm, target_col].values.astype(np.float32)
        Xt = pd_merged.loc[tm, feature_cols].values.astype(np.float32)
        yt = pd_merged.loc[tm, target_col].values.astype(np.float32)

        sel_idx, sel_names = feature_select(Xd, yd, list(feature_cols), k=500)
        Xd_sel = Xd[:, sel_idx]
        Xt_sel = Xt[:, sel_idx]

        extra = dict(extra_static or {})
        if need_sids:
            extra["sids_train"] = dev_s
            extra["sids_test"] = test_s
        if need_sel_idx:
            extra["sel_idx"] = sel_idx

        ep = predict_fn(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra)
        all_true.extend(yt.tolist())
        all_pred.extend(ep.tolist() if hasattr(ep, 'tolist') else [float(ep)])

        running_ccc = lins_ccc(all_true, all_pred)
        running_mae = float(np.mean(np.abs(np.array(all_true) - np.array(all_pred))))
        print(f"  Split {split_i}/{n_splits}: running CCC={running_ccc:.3f} MAE={running_mae:.3f}")

    metrics = full_metrics(np.array(all_true), np.array(all_pred), target_key)
    metrics["eval_mode"] = "5split"
    metrics["runtime_s"] = round(time.time() - t0, 1)
    return metrics


def _run_loocv(pd_merged, feature_cols, target_key, target_col,
               clip_lo, clip_hi, predict_fn, need_sids=False,
               need_sel_idx=False, extra_static=None):
    t0 = time.time()
    sids = pd_merged["sid"].values
    n = len(sids)
    y_true_all = pd_merged[target_col].values.astype(np.float32)
    X_all = pd_merged[feature_cols].values.astype(np.float32)
    y_pred_all = np.zeros(n, dtype=np.float64)

    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        Xd, yd = X_all[mask], y_true_all[mask]
        Xt = X_all[i:i + 1]

        sel_idx, sel_names = feature_select(Xd, yd, list(feature_cols), k=500)
        Xd_sel = Xd[:, sel_idx]
        Xt_sel = Xt[:, sel_idx]

        extra = dict(extra_static or {})
        if need_sids:
            sids_train = sids[mask].tolist()
            sids_test = [sids[i]]
            extra["sids_train"] = sids_train
            extra["sids_test"] = sids_test
        if need_sel_idx:
            extra["sel_idx"] = sel_idx

        ep = predict_fn(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra)
        y_pred_all[i] = float(ep[0]) if hasattr(ep, '__len__') else float(ep)

        if (i + 1) % LOOCV_PROGRESS_EVERY == 0:
            running_mae = float(np.mean(np.abs(y_true_all[:i + 1] - y_pred_all[:i + 1])))
            running_ccc = lins_ccc(y_true_all[:i + 1], y_pred_all[:i + 1])
            elapsed = time.time() - t0
            remaining = elapsed / (i + 1) * (n - i - 1)
            print(f"    [{i + 1}/{n}] CCC={running_ccc:.3f} MAE={running_mae:.3f} "
                  f"({elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining)")

    metrics = full_metrics(y_true_all, y_pred_all, target_key)
    metrics["eval_mode"] = "loocv"
    metrics["runtime_s"] = round(time.time() - t0, 1)
    metrics["per_subject"] = {
        "sids": sids.tolist(),
        "y_true": y_true_all.tolist(),
        "y_pred": y_pred_all.tolist(),
    }
    return metrics


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def print_summary_table(results):
    print("\n" + "=" * 90)
    print(f"{'Proposal':<15} {'Target':<6} {'Eval':<8} {'CCC':>7} {'Slope':>7} "
          f"{'MAE':>7} {'r':>7} {'Time':>8}")
    print("-" * 90)
    for r in results:
        print(f"{r['proposal']:<15} {r['target']:<6} {r['eval_mode']:<8} "
              f"{r['ccc']:>7.3f} {r['cal_slope']:>7.3f} "
              f"{r['mae']:>7.3f} {r['r']:>7.3f} {r['runtime_s']:>7.1f}s")
    print("=" * 90)


def save_result(result, phase, target_key):
    eval_mode = result.get("eval_mode", "")
    suffix = f"_{eval_mode}" if eval_mode else ""
    out_path = str(results_artifact_path(f"stepfn_P{phase}_T{target_key.upper()}{suffix}.json"))
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Step-function experiments beyond P5")
    parser.add_argument("--phase", type=str, default="all",
                        help="Phase: 5(baseline)|6(RankGauss)|7(CDF)|8(Anomaly)|9(Nested)|10(Combined)|all")
    parser.add_argument("--target", type=str, default="all",
                        help="Target: t1|t2|t3|all")
    parser.add_argument("--eval", type=str, default="5split",
                        help="Evaluation mode: 5split|loocv")
    args = parser.parse_args()

    if args.phase == "all":
        phases = [5, 6, 7, 8, 10]
    else:
        phases = [int(p) for p in args.phase.split(",")]

    if args.target == "all":
        targets = ["t1", "t2", "t3"]
    else:
        targets = [t.strip() for t in args.target.split(",")]

    eval_mode = args.eval
    assert eval_mode in ("5split", "loocv"), f"Invalid eval mode: {eval_mode}"

    print("=" * 70)
    print("STEP FUNCTION EXPERIMENTS — Beyond P5 SSL Ranking")
    print(f"Phases: {phases}")
    print(f"Targets: {targets}")
    print(f"Eval: {eval_mode}")
    print("=" * 70)

    pd_merged, all_merged, feature_cols, subjects, item_scores, fm_per_rec = load_features_and_targets()

    all_results = []

    for phase in phases:
        for target_key in targets:
            tag = f"P{phase}_{target_key.upper()}"
            print(f"\n{'─' * 60}")
            print(f"Running {tag} ({eval_mode})...")
            print(f"{'─' * 60}")

            t0 = time.time()
            if phase == 5:
                metrics = run_p5(pd_merged, all_merged, feature_cols, target_key, eval_mode)
                metrics["proposal"] = "P5_SSL_baseline"
            elif phase == 6:
                metrics = run_p6(pd_merged, all_merged, feature_cols, target_key, eval_mode)
                metrics["proposal"] = "P6_RankGauss"
            elif phase == 7:
                metrics = run_p7(pd_merged, all_merged, feature_cols, target_key, eval_mode)
                metrics["proposal"] = "P7_CDF"
            elif phase == 8:
                metrics = run_p8(pd_merged, all_merged, feature_cols, target_key, eval_mode, fm_per_rec)
                metrics["proposal"] = "P8_Anomaly"
            elif phase == 9:
                metrics = run_p9(pd_merged, all_merged, feature_cols, target_key, eval_mode)
                metrics["proposal"] = "P9_Nested"
            elif phase == 10:
                metrics = run_p10(pd_merged, all_merged, feature_cols, target_key, eval_mode, fm_per_rec)
                metrics["proposal"] = "P10_Combined"
            else:
                raise ValueError(f"Unknown phase: {phase}")

            metrics["target"] = target_key.upper()
            metrics["phase"] = phase

            print(f"\n  {tag}: CCC={metrics['ccc']:.3f} slope={metrics['cal_slope']:.3f} "
                  f"MAE={metrics['mae']:.3f} r={metrics['r']:.3f} "
                  f"({metrics['runtime_s']:.1f}s)")

            if "quartiles" in metrics:
                for q in metrics["quartiles"]:
                    print(f"    {q['label']}: n={q['n']} bias={q['bias']:+.3f} mae={q['mae']:.3f}")

            save_result(metrics, phase, target_key)
            all_results.append(metrics)

    print_summary_table(all_results)

    # Save combined results
    summary_path = str(results_artifact_path("stepfn_summary.json"))
    summary = [{k: v for k, v in r.items() if k != "per_subject"} for r in all_results]
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved: {summary_path}")


if __name__ == "__main__":
    main()
