#!/usr/bin/env python3
"""run_compression_ablation.py — Anti-compression ablation across 3 prediction targets.

5 proposals to fix the regression-to-mean compression problem (cal_slope ~0.26)
across 3 prediction targets:
  T1: Direct observable (items 9-14, max=24)
  T2: Broad observable (items 7-14, max=32, items 7-8 use max(L,R))
  T3: Total UPDRS-III (from v2 cache, range 0-59)

Proposals:
  P1: Per-item ordinal + temperature sharpening
  P2: Pairwise contrastive boosting
  P3: SMOGN tail augmentation
  P4: NGBoost distributional
  P5: Semi-supervised ranking from HC

Usage:
    python3 -u run_compression_ablation.py --phase 1 --target t1
    python3 -u run_compression_ablation.py --phase 2 --target all
    python3 -u run_compression_ablation.py --phase all --target all --eval 5split
    python3 -u run_compression_ablation.py --phase all --target all --eval loocv
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
from sklearn.model_selection import StratifiedShuffleSplit, KFold
from sklearn.linear_model import Ridge
from sklearn.neighbors import NearestNeighbors

warnings.filterwarnings("ignore")


# ── Auto-install ─────────────────────────────────────────────────────
def _ensure_deps():
    missing = []
    for pkg, imp in [("lightgbm", "lightgbm"), ("xgboost", "xgboost"),
                     ("ngboost", "ngboost")]:
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
from xgboost import XGBRegressor, XGBRanker
from ngboost import NGBRegressor
from ngboost.distns import Normal, Poisson, LogNormal

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

# Items for each target
T1_ITEMS = [9, 10, 11, 12, 13, 14]  # direct observable, max=24
T2_ITEMS = [7, 8, 9, 10, 11, 12, 13, 14]  # broad observable, max=32
T2_LR_ITEMS = {7, 8}  # items with L/R variants: take max(L,R)
T3_ITEMS = list(range(1, 19))  # all 18 items for total UPDRS-III

# Target ranges
TARGET_CLIP = {"t1": (0, 24), "t2": (0, 32), "t3": (0, 59)}

# LGB default params (matching autoresearch_ccc_eval.py)
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
# METRICS (reused from autoresearch_ccc_eval.py + run_obs_bias_ablation.py)
# ═══════════════════════════════════════════════════════════════════════

def lins_ccc(y_true, y_pred):
    """Lin's concordance correlation coefficient."""
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    mu_t, mu_p = np.mean(y_true), np.mean(y_pred)
    var_t, var_p = np.var(y_true), np.var(y_pred)
    cov = np.mean((y_true - mu_t) * (y_pred - mu_p))
    denom = var_t + var_p + (mu_t - mu_p) ** 2
    return float(2 * cov / denom) if denom > 1e-12 else 0.0


def cal_slope(y_true, y_pred):
    """Calibration slope (linear regression of pred on true)."""
    if np.std(y_true) < 1e-8 or len(y_true) < 3:
        return 0.0
    return float(np.polyfit(y_true, y_pred, 1)[0])


def full_metrics(y_true, y_pred, target_key):
    """Compute all metrics including calibration and quartile biases."""
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
    # Quartile bias — adaptive bins based on target range
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
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════

def parse_per_item_scores():
    """Parse per-INDIVIDUAL-item scores from clinical CSVs.

    Returns dict: sid -> {item_num -> score}
    For items with L/R subitems (3-8, 15-17): stores each subpart separately
      as (item_num, suffix) keys, plus the combined item_num key.
    For items 7-8 specifically: also stores individual L and R values for
      max(L,R) computation needed by T2.
    """
    # Check cache first
    if os.path.exists(PER_ITEM_CACHE):
        print(f"Loading per-item scores from cache: {PER_ITEM_CACHE}")
        with open(PER_ITEM_CACHE) as f:
            raw = json.load(f)
        # Convert string keys back to int item numbers
        result = {}
        for sid, scores in raw.items():
            result[sid] = {}
            for k, v in scores.items():
                if k.startswith("("):
                    # Tuple key like "(7, 'a')" — store as string
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
                    # Single-value item (e.g., items 9-14, 18)
                    val = find_updrs_value(row, df.columns, item_num)
                    if val is not None:
                        scores[item_num] = val
                    elif group == "HC":
                        scores[item_num] = 0.0
                else:
                    # Multi-subpart item
                    vals = []
                    subpart_scores = {}
                    for s in sub:
                        v = find_updrs_value(row, df.columns, item_num, s)
                        if v is not None:
                            vals.append(v)
                            subpart_scores[s] = v
                    if len(vals) == len(sub):
                        # For items 7,8: store L/R separately for max(L,R)
                        if item_num in T2_LR_ITEMS:
                            # "a" = Right, "b" = Left per updrs_columns.py
                            r_val = subpart_scores.get("a", 0.0)
                            l_val = subpart_scores.get("b", 0.0)
                            scores[f"({item_num}, 'R')"] = r_val
                            scores[f"({item_num}, 'L')"] = l_val
                            scores[item_num] = max(r_val, l_val)
                        else:
                            # Sum for all other multi-subpart items
                            scores[item_num] = float(sum(vals))
                        # Also store individual subparts for per-item ordinal models
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

    # Cache to disk
    # Convert int keys to strings for JSON
    cache_obj = {}
    for sid, scores in item_scores.items():
        cache_obj[sid] = {str(k): v for k, v in scores.items()}
    with open(PER_ITEM_CACHE, "w") as f:
        json.dump(cache_obj, f, indent=2)
    print(f"Cached per-item scores to {PER_ITEM_CACHE} ({len(item_scores)} subjects)")
    return item_scores


def compute_target(item_scores, sid, target_key):
    """Compute target score for a subject.

    T1: sum of items 9-14 (max=24)
    T2: sum of items 7-14, items 7,8 use max(L,R) (max=32)
    T3: not used here — comes from v2 cache 'updrs3' column
    """
    if sid not in item_scores:
        return None
    scores = item_scores[sid]
    if target_key == "t1":
        items = T1_ITEMS
    elif target_key == "t2":
        items = T2_ITEMS
    else:
        raise ValueError(f"compute_target not used for T3 (use v2 cache). Got: {target_key}")
    total = 0.0
    for item in items:
        if item not in scores:
            return None
        total += scores[item]
    return total


def load_features_and_targets():
    """Load v2+FM features and all 3 targets. Returns merged dataframe + metadata.

    Returns:
        merged: DataFrame with sid, features, and target columns (t1_target, t2_target, t3_target)
        feature_cols: list of feature column names
        subjects: dict from parse_clinical()
        item_scores: per-item scores dict
    """
    assert os.path.exists(V2_CACHE), f"V2 cache not found: {V2_CACHE}"
    assert os.path.exists(FM_CACHE), f"FM cache not found: {FM_CACHE}"
    assert os.path.exists(RECORDING_CACHE), f"Recording cache not found: {RECORDING_CACHE}"

    v2_df = pd.read_csv(V2_CACHE)
    fm_embeddings = np.load(FM_CACHE)["embeddings"]
    rec_sids = np.load(RECORDING_CACHE)["sids"].tolist()

    # Aggregate FM embeddings per subject
    d_model = fm_embeddings.shape[1]
    fm_df = pd.DataFrame(fm_embeddings, columns=[f"fm_{i}" for i in range(d_model)])
    fm_df["sid"] = rec_sids
    fm_agg = fm_df.groupby("sid").mean().reset_index()
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]

    # v2 feature columns (exclude targets and known non-feature columns)
    EXCLUDED_COLS = {"sid", "updrs3", "obs_subscore", "hy"}
    EXTRA_PREFIXES = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")
    v2_feat_cols = [c for c in v2_df.columns
                    if c not in EXCLUDED_COLS
                    and not any(c.startswith(p) for p in EXTRA_PREFIXES)]

    # Merge v2 + FM
    merged = v2_df[["sid", "updrs3"] + v2_feat_cols].merge(fm_agg, on="sid", how="left").fillna(0.0)
    feature_cols = v2_feat_cols + fm_cols

    # Parse per-item scores
    item_scores = parse_per_item_scores()

    # Compute targets
    subjects = parse_clinical()
    merged["t1_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t1"))
    merged["t2_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t2"))
    merged["t3_target"] = merged["updrs3"].astype(float)

    # Identify PD subjects with ALL targets available
    pd_sids = {sid for sid, info in subjects.items() if info.get("group") == "PD"}
    all_sids = {sid for sid, info in subjects.items()}

    pd_mask = merged["sid"].isin(pd_sids)
    hc_mask = merged["sid"].isin(all_sids - pd_sids)

    # For PD-only: require t1 and t2 are not None
    pd_valid = pd_mask & merged["t1_target"].notna() & merged["t2_target"].notna()
    pd_merged = merged[pd_valid].copy()
    pd_merged["t1_target"] = pd_merged["t1_target"].astype(np.float32)
    pd_merged["t2_target"] = pd_merged["t2_target"].astype(np.float32)
    pd_merged["t3_target"] = pd_merged["t3_target"].astype(np.float32)

    # All subjects (PD + HC) for P5
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

    return pd_merged, all_merged, feature_cols, subjects, item_scores


# ═══════════════════════════════════════════════════════════════════════
# SHARED TRAINING COMPONENTS
# ═══════════════════════════════════════════════════════════════════════

def feature_select(X, y, names, k=500):
    """XGB importance-based feature selection."""
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
    """Train single LightGBM on CPU, return predictions on Xt."""
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
    """5-seed LGB ensemble, clipped to target range."""
    preds = []
    for s in SEEDS:
        p = train_lgb(Xd, yd, Xt, s, params=params, sample_weight=sample_weight)
        preds.append(np.clip(p, clip_lo, clip_hi))
    return np.mean(preds, axis=0)


# ═══════════════════════════════════════════════════════════════════════
# SPLITTING
# ═══════════════════════════════════════════════════════════════════════

def _target_bin(score, target_key):
    """Bin target score for stratification."""
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
    """Deterministic stratified 80/20 split on PD-only subjects."""
    sids = pd_merged["sid"].values
    target_col = f"{target_key}_target"
    bins = pd_merged[target_col].apply(lambda x: _target_bin(x, target_key)).values
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    di, ti = next(sss.split(sids, bins))
    return sids[di].tolist(), sids[ti].tolist()


# ═══════════════════════════════════════════════════════════════════════
# BASELINE (standard LGB ensemble)
# ═══════════════════════════════════════════════════════════════════════

def run_baseline(pd_merged, feature_cols, target_key, eval_mode):
    """Standard LGB 5-seed ensemble baseline for comparison."""
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    if eval_mode == "5split":
        return _run_5split(pd_merged, feature_cols, target_key, target_col,
                           clip_lo, clip_hi, _baseline_predict)
    else:
        return _run_loocv(pd_merged, feature_cols, target_key, target_col,
                          clip_lo, clip_hi, _baseline_predict)


def _baseline_predict(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra):
    """Standard LGB ensemble prediction."""
    return train_lgb_ensemble(Xd_sel, yd, Xt_sel, clip_lo, clip_hi)


# ═══════════════════════════════════════════════════════════════════════
# P1: PER-ITEM ORDINAL + TEMPERATURE SHARPENING
# ═══════════════════════════════════════════════════════════════════════

def _get_ordinal_keys_for_target(target_key):
    """Return list of keys for per-item ordinal prediction.

    Each key is either:
      - int item_num: for single-value items (score 0-4)
      - str "(item_num, 'suffix')": for individual subparts of multi-subpart items

    For T1 (items 9-14): all single-value, 6 ordinal models.
    For T2 (items 7-14): items 7,8 use max(L,R), so predict item_num directly
        (max score is 0-4 since each side is 0-4). Items 9-14 are single.
    For T3 (items 1-18): multi-subpart items decomposed into individual subparts.
        Each subpart is 0-4, we sum across subparts to reconstruct item score.
    """
    if target_key == "t1":
        # Items 9-14, all single-value (0-4 each)
        return T1_ITEMS
    elif target_key == "t2":
        # Items 7-14. Items 7,8: max(L,R) is 0-4. Items 9-14: single 0-4.
        return T2_ITEMS
    elif target_key == "t3":
        # All 18 items. Multi-subpart items decomposed into individual subparts.
        keys = []
        for item_num in T3_ITEMS:
            sub = SUBITEMS_MAP[item_num]
            if sub is None:
                keys.append(item_num)
            else:
                for s in sub:
                    keys.append(f"({item_num}, '{s}')")
        return keys
    else:
        raise ValueError(f"Unknown target: {target_key}")


def _ordinal_predict_fold(Xd_sel, yd_items, Xt_sel, temperature, seed):
    """Train per-item multiclass LGB, apply temperature scaling, sum expected values.

    Args:
        Xd_sel: train features (N_train, K)
        yd_items: dict of item_num -> np.array of per-item scores (int 0-4) for train
        Xt_sel: test features (N_test, K)
        temperature: float, temperature for softmax sharpening
        seed: random seed

    Returns:
        predictions: np.array (N_test,) — sum of expected values across items
    """
    n_test = Xt_sel.shape[0]
    total_pred = np.zeros(n_test, dtype=np.float64)

    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd_sel))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    train_idx = idx[nv:]
    val_idx = idx[:nv]

    for item_num, item_y in yd_items.items():
        # Determine number of classes present
        n_classes = 5  # always 0-4
        item_y_int = item_y.astype(int)

        # Train multiclass LGB
        m = lgb.LGBMClassifier(
            n_estimators=1000,
            learning_rate=0.03,
            max_depth=5,
            num_leaves=20,
            reg_lambda=0.5,
            min_data_in_leaf=5,
            colsample_bytree=0.5,
            random_state=seed,
            n_jobs=N_CORES,
            num_class=n_classes,
            objective="multiclass",
            verbose=-1,
        )
        # Fit without eval_set to avoid unseen-label crash when rare classes
        # (e.g., score=3,4) appear only in val but not train subset
        train_y = item_y_int[train_idx]
        val_y = item_y_int[val_idx]
        # Check if val has classes not in train — if so, skip eval_set
        train_classes = set(np.unique(train_y))
        val_classes = set(np.unique(val_y))
        if val_classes.issubset(train_classes):
            m.fit(
                Xd_sel[train_idx], train_y,
                eval_set=[(Xd_sel[val_idx], val_y)],
                callbacks=[lgb.early_stopping(50, verbose=False)],
            )
        else:
            m.set_params(n_estimators=300)  # fixed tree count without early stopping
            m.fit(Xd_sel[train_idx], train_y)

        # Get raw logits (log-probabilities from LGB multiclass)
        raw_probs = m.predict_proba(Xt_sel)  # (N_test, n_classes_actual)

        # Handle case where some classes are missing in training data
        actual_classes = m.classes_
        full_probs = np.zeros((n_test, n_classes), dtype=np.float64)
        for ci, c in enumerate(actual_classes):
            if c < n_classes:
                full_probs[:, int(c)] = raw_probs[:, ci]

        # Temperature scaling: convert to logits, scale, re-softmax
        # Avoid log(0) by adding small epsilon
        logits = np.log(np.maximum(full_probs, 1e-10))
        scaled_logits = logits / temperature
        # Softmax
        exp_logits = np.exp(scaled_logits - np.max(scaled_logits, axis=1, keepdims=True))
        probs = exp_logits / np.sum(exp_logits, axis=1, keepdims=True)

        # Expected value for this item
        class_values = np.arange(n_classes, dtype=np.float64)
        expected = np.dot(probs, class_values)
        total_pred += expected

    return total_pred


def _p1_inner_cv_temperature(Xd_sel, yd_items, yd_total, clip_lo, clip_hi):
    """3-fold inner CV to select best temperature."""
    temperatures = [0.3, 0.5, 0.7, 1.0]
    kf = KFold(n_splits=3, shuffle=True, random_state=42)
    temp_scores = {t: [] for t in temperatures}

    for fold_tr, fold_val in kf.split(Xd_sel):
        fold_items_train = {k: v[fold_tr] for k, v in yd_items.items()}
        for temp in temperatures:
            preds_val = _ordinal_predict_fold(
                Xd_sel[fold_tr], fold_items_train, Xd_sel[fold_val], temp, seed=42
            )
            preds_val = np.clip(preds_val, clip_lo, clip_hi)
            ccc = lins_ccc(yd_total[fold_val], preds_val)
            temp_scores[temp].append(ccc)

    # Select temperature with best mean CCC
    best_temp = max(temperatures, key=lambda t: np.mean(temp_scores[t]))
    return best_temp


def run_p1(pd_merged, feature_cols, target_key, eval_mode, item_scores):
    """P1: Per-item ordinal + temperature sharpening."""
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]
    ordinal_keys = _get_ordinal_keys_for_target(target_key)

    def _p1_predict(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra):
        sids_train = extra["sids_train"]
        # Build per-item/subpart target arrays for train set
        # Each key maps to a 0-4 ordinal score array
        yd_items = {}
        for key in ordinal_keys:
            item_vals = []
            for sid in sids_train:
                if sid not in item_scores:
                    item_vals.append(0)
                    continue
                scores = item_scores[sid]
                if isinstance(key, int):
                    # Single-value item or max(L,R) item — score is 0-4
                    val = scores.get(key, 0.0)
                    item_vals.append(int(min(4, max(0, round(val)))))
                else:
                    # Subpart key like "(3, 'a')" — score is 0-4
                    val = scores.get(key, 0.0)
                    item_vals.append(int(min(4, max(0, round(val)))))
            yd_items[key] = np.array(item_vals, dtype=np.int32)

        # Inner CV to select temperature
        best_temp = _p1_inner_cv_temperature(Xd_sel, yd_items, yd, clip_lo, clip_hi)

        # Train final models with best temperature, 5-seed ensemble
        preds = []
        for s in SEEDS:
            p = _ordinal_predict_fold(Xd_sel, yd_items, Xt_sel, best_temp, s)
            preds.append(np.clip(p, clip_lo, clip_hi))
        return np.mean(preds, axis=0)

    if eval_mode == "5split":
        return _run_5split(pd_merged, feature_cols, target_key, target_col,
                           clip_lo, clip_hi, _p1_predict, need_sids=True)
    else:
        return _run_loocv(pd_merged, feature_cols, target_key, target_col,
                          clip_lo, clip_hi, _p1_predict, need_sids=True)


# ═══════════════════════════════════════════════════════════════════════
# P2: PAIRWISE CONTRASTIVE BOOSTING
# ═══════════════════════════════════════════════════════════════════════

def _p2_predict(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra):
    """Pairwise contrastive boosting prediction."""
    n_train = len(yd)
    n_test = Xt_sel.shape[0]
    K_ANCHORS = 20

    # Create paired dataset: features = X_i - X_j, target = y_i - y_j
    # Use random sampling of pairs to keep computational cost reasonable
    rng = np.random.RandomState(42)
    n_pairs = min(n_train * (n_train - 1) // 2, 5000)

    # Generate pairs
    pair_features = []
    pair_targets = []
    for _ in range(n_pairs):
        i, j = rng.choice(n_train, size=2, replace=False)
        pair_features.append(Xd_sel[i] - Xd_sel[j])
        pair_targets.append(yd[i] - yd[j])
    pair_X = np.array(pair_features, dtype=np.float32)
    pair_y = np.array(pair_targets, dtype=np.float32)

    # Select K stratified anchors from train fold
    # Stratify by target score quartiles
    anchor_bins = np.digitize(yd, np.percentile(yd, [25, 50, 75]))
    anchor_indices = []
    for b in range(4):
        b_indices = np.where(anchor_bins == b)[0]
        if len(b_indices) > 0:
            n_from_bin = max(1, K_ANCHORS // 4)
            chosen = rng.choice(b_indices, size=min(n_from_bin, len(b_indices)), replace=False)
            anchor_indices.extend(chosen.tolist())
    # Fill remaining from all
    remaining = K_ANCHORS - len(anchor_indices)
    if remaining > 0:
        available = [i for i in range(n_train) if i not in set(anchor_indices)]
        if available:
            extra_anch = rng.choice(available, size=min(remaining, len(available)), replace=False)
            anchor_indices.extend(extra_anch.tolist())

    # Train LGB on pairs, 5-seed ensemble
    all_preds = []
    for seed in SEEDS:
        pair_rng = np.random.RandomState(seed)
        pair_idx = np.arange(len(pair_X))
        pair_rng.shuffle(pair_idx)
        nv = max(1, int(len(pair_idx) * 0.15))

        m = lgb.LGBMRegressor(
            n_estimators=2000, learning_rate=0.03, max_depth=6,
            num_leaves=31, reg_lambda=0.3, min_data_in_leaf=8,
            colsample_bytree=0.5, random_state=seed, n_jobs=N_CORES,
            objective="mse", verbose=-1,
        )
        m.fit(
            pair_X[pair_idx[nv:]], pair_y[pair_idx[nv:]],
            eval_set=[(pair_X[pair_idx[:nv]], pair_y[pair_idx[:nv]])],
            callbacks=[lgb.early_stopping(100, verbose=False)],
        )

        # Predict: for each test subject, pair with each anchor
        test_preds = np.zeros(n_test, dtype=np.float64)
        for ti in range(n_test):
            reconstructed = []
            for ai in anchor_indices:
                diff_feat = (Xt_sel[ti] - Xd_sel[ai]).reshape(1, -1)
                delta_hat = m.predict(diff_feat)[0]
                reconstructed.append(yd[ai] + delta_hat)
            test_preds[ti] = np.mean(reconstructed)
        all_preds.append(np.clip(test_preds, clip_lo, clip_hi))

    return np.mean(all_preds, axis=0)


def run_p2(pd_merged, feature_cols, target_key, eval_mode):
    """P2: Pairwise contrastive boosting."""
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    if eval_mode == "5split":
        return _run_5split(pd_merged, feature_cols, target_key, target_col,
                           clip_lo, clip_hi, _p2_predict)
    else:
        return _run_loocv(pd_merged, feature_cols, target_key, target_col,
                          clip_lo, clip_hi, _p2_predict)


# ═══════════════════════════════════════════════════════════════════════
# P3: SMOGN TAIL AUGMENTATION
# ═══════════════════════════════════════════════════════════════════════

def _p3_predict(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra):
    """SMOGN tail augmentation prediction."""
    n_train = len(yd)
    rng = np.random.RandomState(42)

    # Define "rare" as top 15% of target distribution
    threshold = np.percentile(yd, 85)
    rare_mask = yd >= threshold
    rare_indices = np.where(rare_mask)[0]
    dense_mask = ~rare_mask

    # Generate synthetic subjects for rare tail
    synthetic_X = []
    synthetic_y = []
    if len(rare_indices) >= 2:
        # Find 3 nearest neighbors among rare subjects
        nn = NearestNeighbors(n_neighbors=min(4, len(rare_indices)), metric="euclidean")
        nn.fit(Xd_sel[rare_indices])
        distances, neighbors = nn.kneighbors(Xd_sel[rare_indices])

        for i in range(len(rare_indices)):
            # neighbors[i][0] is self, use [1:]
            for j_idx in neighbors[i][1:]:
                lam = rng.uniform(0.3, 0.7)
                x_new = lam * Xd_sel[rare_indices[i]] + (1 - lam) * Xd_sel[rare_indices[j_idx]]
                y_new = lam * yd[rare_indices[i]] + (1 - lam) * yd[rare_indices[j_idx]]
                synthetic_X.append(x_new)
                synthetic_y.append(y_new)

    # Build augmented training set
    if synthetic_X:
        aug_X = np.vstack([Xd_sel, np.array(synthetic_X)])
        aug_y = np.concatenate([yd, np.array(synthetic_y)])
        # Sample weights: original = 1.0, synthetic = 0.5
        # Dense middle (within 1 SD of mean) downweighted to 0.7
        weights = np.ones(len(aug_y), dtype=np.float32)
        # Downweight dense middle
        mean_y = np.mean(yd)
        std_y = np.std(yd)
        for i in range(n_train):
            if abs(yd[i] - mean_y) < std_y:
                weights[i] = 0.7
        # Synthetic weights
        weights[n_train:] = 0.5
    else:
        aug_X = Xd_sel
        aug_y = yd
        weights = np.ones(len(aug_y), dtype=np.float32)
        mean_y = np.mean(yd)
        std_y = np.std(yd)
        for i in range(n_train):
            if abs(yd[i] - mean_y) < std_y:
                weights[i] = 0.7

    # Train LGB ensemble with sample weights
    return train_lgb_ensemble(aug_X, aug_y, Xt_sel, clip_lo, clip_hi,
                              sample_weight=weights)


def run_p3(pd_merged, feature_cols, target_key, eval_mode):
    """P3: SMOGN tail augmentation."""
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    if eval_mode == "5split":
        return _run_5split(pd_merged, feature_cols, target_key, target_col,
                           clip_lo, clip_hi, _p3_predict)
    else:
        return _run_loocv(pd_merged, feature_cols, target_key, target_col,
                          clip_lo, clip_hi, _p3_predict)


# ═══════════════════════════════════════════════════════════════════════
# P4: NGBOOST DISTRIBUTIONAL
# ═══════════════════════════════════════════════════════════════════════

def _p4_predict(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra):
    """NGBoost distributional prediction with CCC-tuned percentile."""
    target_key = extra["target_key"]

    # Choose distributions based on target
    if target_key == "t1":
        dist_configs = [
            ("Poisson", Poisson),
            ("Normal", Normal),
        ]
    else:
        dist_configs = [
            ("Normal", Normal),
            ("LogNormal", LogNormal),
        ]

    best_ccc = -999.0
    best_preds = None
    best_dist_name = None

    for dist_name, dist_cls in dist_configs:
        try:
            # For Poisson: target must be non-negative integers
            yd_dist = yd.copy()
            if dist_cls == Poisson:
                yd_dist = np.round(np.maximum(yd_dist, 0)).astype(int)
            elif dist_cls == LogNormal:
                # LogNormal needs strictly positive targets
                yd_dist = np.maximum(yd_dist, 0.1)

            # Train NGBoost, 3-seed ensemble (NGBoost is slower)
            all_preds = []
            for seed in SEEDS[:3]:
                rng = np.random.RandomState(seed)
                idx = np.arange(len(yd_dist))
                rng.shuffle(idx)
                nv = max(1, int(len(idx) * 0.15))

                ngb = NGBRegressor(
                    Dist=dist_cls,
                    n_estimators=500,
                    learning_rate=0.05,
                    minibatch_frac=0.8,
                    random_state=seed,
                    verbose=False,
                )
                ngb.fit(
                    Xd_sel[idx[nv:]], yd_dist[idx[nv:]],
                    X_val=Xd_sel[idx[:nv]], Y_val=yd_dist[idx[:nv]],
                    early_stopping_rounds=50,
                )

                # Get distributional predictions
                dists = ngb.pred_dist(Xt_sel)

                if dist_cls == Poisson:
                    # Poisson: use CCC-tuned percentile
                    means = dists.params["mu"]
                    max_mean = np.max(means) if np.max(means) > 0 else 1.0
                    q_vals = 0.3 + 0.4 * (means / max_mean)
                    preds = np.array([
                        float(sp_stats.poisson.ppf(q_vals[i], mu=max(means[i], 0.01)))
                        for i in range(len(means))
                    ], dtype=np.float64)
                elif dist_cls == Normal:
                    means = dists.params["loc"]
                    scales = dists.params["scale"]
                    max_mean = np.max(means) if np.max(means) > 0 else 1.0
                    q_vals = 0.3 + 0.4 * (means / max_mean)
                    preds = np.array([
                        float(sp_stats.norm.ppf(q_vals[i], loc=means[i], scale=max(scales[i], 0.01)))
                        for i in range(len(means))
                    ], dtype=np.float64)
                elif dist_cls == LogNormal:
                    s_param = dists.params["s"]
                    scale_param = dists.params["scale"]
                    means = scale_param * np.exp(0.5 * s_param ** 2)
                    max_mean = np.max(means) if np.max(means) > 0 else 1.0
                    q_vals = 0.3 + 0.4 * (means / max_mean)
                    preds = np.array([
                        float(sp_stats.lognorm.ppf(
                            q_vals[i], s=max(s_param[i], 0.01),
                            scale=max(scale_param[i], 0.01)))
                        for i in range(len(means))
                    ], dtype=np.float64)
                else:
                    raise ValueError(f"Unsupported distribution: {dist_cls}")

                all_preds.append(np.clip(preds, clip_lo, clip_hi))

            ensemble_pred = np.mean(all_preds, axis=0)

            # Use inner validation CCC to pick best distribution
            # Approximate with a quick split
            inner_rng = np.random.RandomState(999)
            inner_idx = np.arange(len(yd))
            inner_rng.shuffle(inner_idx)
            inner_nv = max(1, int(len(inner_idx) * 0.2))
            inner_test = inner_idx[:inner_nv]
            inner_train = inner_idx[inner_nv:]

            yd_inner = yd_dist.copy()
            ngb_inner = NGBRegressor(
                Dist=dist_cls, n_estimators=300, learning_rate=0.05,
                minibatch_frac=0.8, random_state=999, verbose=False,
            )
            ngb_inner.fit(Xd_sel[inner_train], yd_inner[inner_train])
            dists_inner = ngb_inner.pred_dist(Xd_sel[inner_test])

            if dist_cls == Poisson:
                inner_means = dists_inner.params["mu"]
                inner_max = np.max(inner_means) if np.max(inner_means) > 0 else 1.0
                inner_q = 0.3 + 0.4 * (inner_means / inner_max)
                inner_preds = np.array([
                    float(sp_stats.poisson.ppf(inner_q[i], mu=max(inner_means[i], 0.01)))
                    for i in range(len(inner_means))
                ], dtype=np.float64)
            elif dist_cls == Normal:
                inner_means = dists_inner.params["loc"]
                inner_scales = dists_inner.params["scale"]
                inner_max = np.max(inner_means) if np.max(inner_means) > 0 else 1.0
                inner_q = 0.3 + 0.4 * (inner_means / inner_max)
                inner_preds = np.array([
                    float(sp_stats.norm.ppf(inner_q[i], loc=inner_means[i],
                                            scale=max(inner_scales[i], 0.01)))
                    for i in range(len(inner_means))
                ], dtype=np.float64)
            elif dist_cls == LogNormal:
                inner_s = dists_inner.params["s"]
                inner_scale = dists_inner.params["scale"]
                inner_means = inner_scale * np.exp(0.5 * inner_s ** 2)
                inner_max = np.max(inner_means) if np.max(inner_means) > 0 else 1.0
                inner_q = 0.3 + 0.4 * (inner_means / inner_max)
                inner_preds = np.array([
                    float(sp_stats.lognorm.ppf(
                        inner_q[i], s=max(inner_s[i], 0.01),
                        scale=max(inner_scale[i], 0.01)))
                    for i in range(len(inner_means))
                ], dtype=np.float64)
            else:
                raise ValueError(f"Unsupported distribution: {dist_cls}")

            inner_preds = np.clip(inner_preds, clip_lo, clip_hi)
            inner_ccc = lins_ccc(yd[inner_test], inner_preds)

            print(f"      P4 {dist_name}: inner CCC={inner_ccc:.3f}")

            if inner_ccc > best_ccc:
                best_ccc = inner_ccc
                best_preds = ensemble_pred
                best_dist_name = dist_name

        except Exception as e:
            print(f"      P4 {dist_name} failed: {e}")
            continue

    if best_preds is None:
        raise RuntimeError("P4: All distribution fits failed")

    print(f"      P4 selected: {best_dist_name} (inner CCC={best_ccc:.3f})")
    return best_preds


def run_p4(pd_merged, feature_cols, target_key, eval_mode):
    """P4: NGBoost distributional."""
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    if eval_mode == "5split":
        return _run_5split(pd_merged, feature_cols, target_key, target_col,
                           clip_lo, clip_hi, _p4_predict,
                           extra_static={"target_key": target_key})
    else:
        return _run_loocv(pd_merged, feature_cols, target_key, target_col,
                          clip_lo, clip_hi, _p4_predict,
                          extra_static={"target_key": target_key})


# ═══════════════════════════════════════════════════════════════════════
# P5: SEMI-SUPERVISED RANKING FROM HC
# ═══════════════════════════════════════════════════════════════════════

def run_p5(pd_merged, all_merged, feature_cols, target_key, eval_mode):
    """P5: Semi-supervised ranking from HC.

    Stage 1: Train XGBRanker on ALL subjects (PD + HC)
    Stage 2: Extract leaf indices as new features
    Stage 3: Train LGB on PD-only using original + ranking leaf features
    """
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    # Pre-compute ranking labels for ALL subjects
    # HC = 0, PD sorted by target score into ordinal ranks
    all_sids = all_merged["sid"].values
    all_targets = all_merged[target_col].values.astype(np.float32)
    is_pd = all_merged["is_pd"].values

    # Build ordinal labels: HC=0, PD ranked 1..N_PD
    rank_labels = np.zeros(len(all_sids), dtype=np.int32)
    pd_indices = np.where(is_pd == 1)[0]
    pd_order = np.argsort(all_targets[pd_indices])
    for rank, idx in enumerate(pd_order):
        rank_labels[pd_indices[idx]] = rank + 1

    X_all = all_merged[feature_cols].values.astype(np.float32)

    def _p5_predict(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra):
        sids_train = extra["sids_train"]
        sids_test = extra["sids_test"]

        # Feature selection was already done (Xd_sel, Xt_sel are selected features)
        # We need the selected feature indices to apply to all_merged too
        sel_idx = extra["sel_idx"]

        # Stage 1: Train XGBRanker on ALL subjects using selected features
        X_all_sel = X_all[:, sel_idx]

        # For ranking: group by "query" — treat all subjects as one query group
        group_sizes = np.array([len(X_all_sel)])

        # 3-seed ensemble for ranking features
        all_leaf_features = []
        for seed in SEEDS[:3]:
            ranker = XGBRanker(
                n_estimators=300,
                max_depth=4,
                learning_rate=0.05,
                reg_lambda=2.0,
                random_state=seed,
                n_jobs=N_CORES,
                objective="rank:pairwise",
            )
            ranker.fit(X_all_sel, rank_labels, group=group_sizes)

            # Stage 2: Extract leaf indices for train and test subjects
            # Map sids to indices in all_merged
            sid_to_all_idx = {s: i for i, s in enumerate(all_sids)}
            train_all_indices = [sid_to_all_idx[s] for s in sids_train if s in sid_to_all_idx]
            test_all_indices = [sid_to_all_idx[s] for s in sids_test if s in sid_to_all_idx]

            train_leaves = ranker.apply(X_all_sel[train_all_indices])  # (N_train, n_trees)
            test_leaves = ranker.apply(X_all_sel[test_all_indices])

            all_leaf_features.append((train_leaves, test_leaves))

        # Concatenate leaf features from all seeds
        train_leaf_cat = np.hstack([lf[0] for lf in all_leaf_features]).astype(np.float32)
        test_leaf_cat = np.hstack([lf[1] for lf in all_leaf_features]).astype(np.float32)

        # Stage 3: Combine original features + ranking leaf features
        assert train_leaf_cat.shape[0] == Xd_sel.shape[0], (
            f"Shape mismatch: train leaves {train_leaf_cat.shape[0]} vs Xd_sel {Xd_sel.shape[0]}")
        assert test_leaf_cat.shape[0] == Xt_sel.shape[0], (
            f"Shape mismatch: test leaves {test_leaf_cat.shape[0]} vs Xt_sel {Xt_sel.shape[0]}")

        Xd_combined = np.hstack([Xd_sel, train_leaf_cat])
        Xt_combined = np.hstack([Xt_sel, test_leaf_cat])

        # Train LGB ensemble on combined features
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
# GENERIC EVAL RUNNERS
# ═══════════════════════════════════════════════════════════════════════

def _run_5split(pd_merged, feature_cols, target_key, target_col,
                clip_lo, clip_hi, predict_fn, need_sids=False,
                need_sel_idx=False, extra_static=None):
    """Run 5-split stratified CV."""
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

        # Feature selection inside fold
        sel_idx, sel_names = feature_select(Xd, yd, list(feature_cols), k=500)
        Xd_sel = Xd[:, sel_idx]
        Xt_sel = Xt[:, sel_idx]

        # Build extra dict
        extra = dict(extra_static or {})
        if need_sids:
            extra["sids_train"] = pd_merged.loc[dm, "sid"].values.tolist()
            extra["sids_test"] = pd_merged.loc[tm, "sid"].values.tolist()
        if need_sel_idx:
            extra["sel_idx"] = sel_idx

        ep = predict_fn(Xd_sel, yd, Xt_sel, clip_lo, clip_hi, extra)

        ccc = lins_ccc(yt, ep)
        mae = float(np.mean(np.abs(yt - ep)))
        slope = cal_slope(yt, ep)
        print(f"  Split {split_i}/{n_splits}: CCC={ccc:.3f} slope={slope:.3f} MAE={mae:.3f}")

        all_true.extend(yt.tolist())
        all_pred.extend(ep.tolist())

    metrics = full_metrics(np.array(all_true), np.array(all_pred), target_key)
    metrics["eval_mode"] = "5split"
    metrics["runtime_s"] = round(time.time() - t0, 1)
    metrics["per_subject"] = {
        "y_true": all_true,
        "y_pred": [float(p) for p in all_pred],
    }
    return metrics


def _run_loocv(pd_merged, feature_cols, target_key, target_col,
               clip_lo, clip_hi, predict_fn, need_sids=False,
               need_sel_idx=False, extra_static=None):
    """Run PD-only LOOCV."""
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

        # Feature selection inside fold
        sel_idx, sel_names = feature_select(Xd, yd, list(feature_cols), k=500)
        Xd_sel = Xd[:, sel_idx]
        Xt_sel = Xt[:, sel_idx]

        # Build extra dict
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
    """Print a summary table of all results."""
    print("\n" + "=" * 90)
    print(f"{'Proposal':<12} {'Target':<6} {'Eval':<8} {'CCC':>7} {'Slope':>7} "
          f"{'MAE':>7} {'r':>7} {'Time':>8}")
    print("-" * 90)
    for r in results:
        print(f"{r['proposal']:<12} {r['target']:<6} {r['eval_mode']:<8} "
              f"{r['ccc']:>7.3f} {r['cal_slope']:>7.3f} "
              f"{r['mae']:>7.3f} {r['r']:>7.3f} {r['runtime_s']:>7.1f}s")
    print("=" * 90)


def save_result(result, phase, target_key):
    """Save individual result to JSON."""
    eval_mode = result.get("eval_mode", "")
    suffix = f"_{eval_mode}" if eval_mode else ""
    out_path = str(results_artifact_path(f"compression_P{phase}_T{target_key.upper()}{suffix}.json"))
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Anti-compression ablation")
    parser.add_argument("--phase", type=str, default="all",
                        help="Phase to run: 0(baseline)|1|2|3|4|5|all")
    parser.add_argument("--target", type=str, default="all",
                        help="Target: t1|t2|t3|all")
    parser.add_argument("--eval", type=str, default="5split",
                        help="Evaluation mode: 5split|loocv")
    args = parser.parse_args()

    # Parse phases and targets
    if args.phase == "all":
        phases = [0, 1, 2, 3, 4, 5]
    else:
        phases = [int(p) for p in args.phase.split(",")]

    if args.target == "all":
        targets = ["t1", "t2", "t3"]
    else:
        targets = [t.strip() for t in args.target.split(",")]

    eval_mode = args.eval
    assert eval_mode in ("5split", "loocv"), f"Invalid eval mode: {eval_mode}"

    print("=" * 70)
    print("COMPRESSION ABLATION — Anti-compression proposals x 3 targets")
    print(f"Phases: {phases}")
    print(f"Targets: {targets}")
    print(f"Eval: {eval_mode}")
    print("=" * 70)

    # Load data
    pd_merged, all_merged, feature_cols, subjects, item_scores = load_features_and_targets()

    all_results = []

    for phase in phases:
        for target_key in targets:
            tag = f"P{phase}_{target_key.upper()}"
            clip_lo, clip_hi = TARGET_CLIP[target_key]
            print(f"\n{'─' * 60}")
            print(f"Running {tag} ({eval_mode})...")
            print(f"  Target: {target_key.upper()}, range [{clip_lo}, {clip_hi}]")
            print(f"{'─' * 60}")

            t0 = time.time()

            if phase == 0:
                # Baseline
                metrics = run_baseline(pd_merged, feature_cols, target_key, eval_mode)
                metrics["proposal"] = "P0_baseline"
            elif phase == 1:
                # P1: Per-item ordinal + temperature sharpening
                metrics = run_p1(pd_merged, feature_cols, target_key, eval_mode, item_scores)
                metrics["proposal"] = "P1_ordinal"
            elif phase == 2:
                # P2: Pairwise contrastive boosting
                metrics = run_p2(pd_merged, feature_cols, target_key, eval_mode)
                metrics["proposal"] = "P2_pairwise"
            elif phase == 3:
                # P3: SMOGN tail augmentation
                metrics = run_p3(pd_merged, feature_cols, target_key, eval_mode)
                metrics["proposal"] = "P3_smogn"
            elif phase == 4:
                # P4: NGBoost distributional
                metrics = run_p4(pd_merged, feature_cols, target_key, eval_mode)
                metrics["proposal"] = "P4_ngboost"
            elif phase == 5:
                # P5: Semi-supervised ranking from HC
                metrics = run_p5(pd_merged, all_merged, feature_cols, target_key, eval_mode)
                metrics["proposal"] = "P5_ranking"
            else:
                raise ValueError(f"Unknown phase: {phase}")

            metrics["target"] = target_key.upper()
            metrics["phase"] = phase

            # Print detailed results
            print(f"\n  Results for {tag}:")
            print(f"    CCC       = {metrics['ccc']:.3f}")
            print(f"    cal_slope = {metrics['cal_slope']:.3f}")
            print(f"    MAE       = {metrics['mae']:.3f}")
            print(f"    r         = {metrics['r']:.3f}")
            print(f"    RMSE      = {metrics['rmse']:.3f}")
            if metrics.get("quartiles"):
                print(f"    Quartile biases:")
                for q in metrics["quartiles"]:
                    print(f"      {q['label']}: n={q['n']}, bias={q['bias']:+.3f}, mae={q['mae']:.3f}")

            save_result(metrics, phase, target_key)
            all_results.append(metrics)

    # Print summary table
    print_summary_table(all_results)

    # Save combined results
    combined_path = str(results_artifact_path("compression_ablation_all.json"))
    with open(combined_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nAll results saved to: {combined_path}")


if __name__ == "__main__":
    main()
