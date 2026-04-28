#!/usr/bin/env python3
"""Calibration fix ablation — 7 experiments to fix prediction compression.

Ablates Stage 2 of the SSL ranking pipeline. Stage 1 (XGBRanker) stays fixed.
All experiments evaluated on T1 (observable subscore, items 9-14) with LOOCV.

Experiments:
  E0: Baseline — exact replica of P5 5-seed LGB ensemble (MSE loss)
  E1: CCC loss — custom LGB objective maximizing Lin's CCC
  E2: Quantile median — LGB quantile at tau={0.1, 0.5, 0.9}
  E3: KNN — distance-weighted KNN on PCA-reduced leaf features
  E4: Variance penalty — custom LGB objective penalizing low pred variance
  E5: CQR — conformalized quantile regression with spread recalibration
  E6: Ridge — linear head on PCA-reduced [selected + leaf] features
  E7: Temperature — post-hoc scaling of E0 ensemble predictions

Usage:
    python3 -u run_calibration_v2.py --experiment E0        # baseline verification
    python3 -u run_calibration_v2.py --experiment E3,E6,E7  # quick wins
    python3 -u run_calibration_v2.py --experiment all        # run everything
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
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge
from sklearn.neighbors import KNeighborsRegressor

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
from xgboost import XGBRegressor, XGBRanker

from project_paths import REPO_ROOT, RESULTS_DIR, ensure_dir, results_artifact_path
sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, DATA_DIR
from updrs_columns import find_updrs_value
from eval_utils import lins_ccc, cal_slope


# ── Constants ────────────────────────────────────────────────────────
V2_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
_FM_CACHE_PRIMARY = str(results_artifact_path("sensor_fm_cache/all_13_fm.npz"))
_FM_CACHE_LEGACY = str(results_artifact_path("fm_embeddings.npz"))
FM_CACHE = _FM_CACHE_PRIMARY if os.path.exists(_FM_CACHE_PRIMARY) else _FM_CACHE_LEGACY
RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))
PER_ITEM_CACHE = str(results_artifact_path("per_item_scores.json"))
N_CORES = min(os.cpu_count() or 4, 11)
SEEDS = [42, 123, 456, 789, 2024]
LOOCV_PROGRESS_EVERY = 10
ensure_dir(RESULTS_DIR)

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

def full_metrics(y_true: np.ndarray, y_pred: np.ndarray, target_key: str) -> dict:
    """Compute all metrics including calibration, quartile biases, and std_ratio."""
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    r = float(sp_stats.pearsonr(y_true, y_pred)[0]) if len(y_true) > 2 else 0.0
    ccc = lins_ccc(y_true, y_pred)
    slope = cal_slope(y_true, y_pred)
    std_ratio = float(np.std(y_pred) / np.std(y_true)) if np.std(y_true) > 1e-8 else 0.0
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
        "std_ratio": round(std_ratio, 3),
        "quartiles": quartiles, "n": len(y_true),
    }


# ═══════════════════════════════════════════════════════════════════════
# DATA LOADING (copied from run_compression_ablation.py)
# ═══════════════════════════════════════════════════════════════════════

def parse_per_item_scores() -> dict:
    """Parse per-item UPDRS scores from clinical CSVs or cache."""
    if os.path.exists(PER_ITEM_CACHE):
        print(f"Loading per-item scores from cache: {PER_ITEM_CACHE}")
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


def compute_target(item_scores: dict, sid: str, target_key: str):
    """Compute target score for a subject (T1 or T2 only; T3 from v2 cache)."""
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
    """Load v2+FM features and all 3 targets. Returns merged DataFrames + metadata."""
    assert os.path.exists(V2_CACHE), f"V2 cache not found: {V2_CACHE}"
    assert os.path.exists(FM_CACHE), f"FM cache not found: {FM_CACHE}"
    assert os.path.exists(RECORDING_CACHE), f"Recording cache not found: {RECORDING_CACHE}"

    v2_df = pd.read_csv(V2_CACHE)
    fm_embeddings = np.load(FM_CACHE)["embeddings"]
    rec_sids = np.load(RECORDING_CACHE)["sids"].tolist()

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

    return pd_merged, all_merged, feature_cols, subjects, item_scores


# ═══════════════════════════════════════════════════════════════════════
# FEATURE SELECTION
# ═══════════════════════════════════════════════════════════════════════

def feature_select(X: np.ndarray, y: np.ndarray, names: list, k: int = 500):
    """XGB importance-based feature selection (inside each fold)."""
    k = min(k, X.shape[1])
    sel = XGBRegressor(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
        objective="reg:absoluteerror",
    )
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


# ═══════════════════════════════════════════════════════════════════════
# STAGE 2 TRAINERS
# ═══════════════════════════════════════════════════════════════════════

def train_lgb(Xd: np.ndarray, yd: np.ndarray, Xt: np.ndarray, seed: int,
              params: dict = None, fobj=None) -> np.ndarray:
    """Train single LightGBM, return predictions on Xt.

    If fobj is provided, uses lgb.train() with custom objective.
    Otherwise uses LGBMRegressor with MSE.
    """
    p = dict(DEFAULT_LGB_PARAMS)
    if params:
        p.update(params)
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * p.get("val_frac", 0.15)))

    if fobj is not None:
        # Custom objective path — use lgb.train() API
        dtrain = lgb.Dataset(Xd[idx[nv:]], label=yd[idx[nv:]])
        dval = lgb.Dataset(Xd[idx[:nv]], label=yd[idx[:nv]], reference=dtrain)
        lgb_params = {
            "learning_rate": p["learning_rate"],
            "max_depth": p["max_depth"],
            "num_leaves": p["num_leaves"],
            "reg_lambda": p["reg_lambda"],
            "min_data_in_leaf": p["min_data_in_leaf"],
            "colsample_bytree": p["colsample_bytree"],
            "subsample": p["subsample"],
            "seed": seed,
            "num_threads": N_CORES,
            "verbose": -1,
        }
        lgb_params["objective"] = fobj
        lgb_params["metric"] = "mae"
        model = lgb.train(
            lgb_params,
            dtrain,
            num_boost_round=p["n_estimators"],
            valid_sets=[dval],
            callbacks=[lgb.early_stopping(p["early_stopping_rounds"], verbose=False)],
        )
        return model.predict(Xt)
    else:
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
        m.fit(
            X=Xd[idx[nv:]],
            y=yd[idx[nv:]],
            eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
            callbacks=[lgb.early_stopping(p["early_stopping_rounds"], verbose=False)],
        )
        return m.predict(Xt)


def train_lgb_quantile(Xd: np.ndarray, yd: np.ndarray, Xt: np.ndarray,
                       seed: int, alpha: float) -> np.ndarray:
    """Train single LightGBM with quantile objective, return predictions."""
    p = dict(DEFAULT_LGB_PARAMS)
    p["objective"] = "quantile"
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
        objective="quantile",
        alpha=alpha,
        verbose=-1,
    )
    m.fit(
        X=Xd[idx[nv:]],
        y=yd[idx[nv:]],
        eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
        callbacks=[lgb.early_stopping(p["early_stopping_rounds"], verbose=False)],
    )
    return m.predict(Xt)


# ═══════════════════════════════════════════════════════════════════════
# SSL RANKING STAGE 1 (shared across all experiments)
# ═══════════════════════════════════════════════════════════════════════

def ssl_stage1(X_all_sel: np.ndarray, rank_labels: np.ndarray,
               sids_train: list, sids_test: list,
               all_sids: np.ndarray) -> tuple:
    """Run XGBRanker (Stage 1) and extract leaf features for train/test.

    Returns (train_leaf_features, test_leaf_features) as np.ndarray.
    """
    sid_to_all_idx = {s: i for i, s in enumerate(all_sids)}
    train_all_indices = [sid_to_all_idx[s] for s in sids_train if s in sid_to_all_idx]
    test_all_indices = [sid_to_all_idx[s] for s in sids_test if s in sid_to_all_idx]

    group_sizes = np.array([len(X_all_sel)])

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
        train_leaves = ranker.apply(X_all_sel[train_all_indices])
        test_leaves = ranker.apply(X_all_sel[test_all_indices])
        all_leaf_features.append((train_leaves, test_leaves))

    train_leaf_cat = np.hstack([lf[0] for lf in all_leaf_features]).astype(np.float32)
    test_leaf_cat = np.hstack([lf[1] for lf in all_leaf_features]).astype(np.float32)

    return train_leaf_cat, test_leaf_cat


# ═══════════════════════════════════════════════════════════════════════
# SSL LOOCV RUNNER
# ═══════════════════════════════════════════════════════════════════════

def ssl_loocv(pd_merged: pd.DataFrame, all_merged: pd.DataFrame,
              feature_cols: list, target_key: str,
              predict_fn, label: str = "") -> dict:
    """Run SSL LOOCV with a custom Stage 2 predictor.

    predict_fn signature:
        predict_fn(Xd_combined, yd, Xt_combined, clip_lo, clip_hi,
                   train_leaf, test_leaf) -> np.ndarray of predictions

    Stage 1 (XGBRanker) runs inside this function. predict_fn handles
    only Stage 2 (final prediction from combined features).
    """
    t0 = time.time()
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    # Precompute ranking labels for ALL subjects
    all_sids = all_merged["sid"].values
    all_targets = all_merged[target_col].values.astype(np.float32)
    is_pd = all_merged["is_pd"].values

    rank_labels = np.zeros(len(all_sids), dtype=np.int32)
    pd_indices = np.where(is_pd == 1)[0]
    pd_order = np.argsort(all_targets[pd_indices])
    for rank, idx in enumerate(pd_order):
        rank_labels[pd_indices[idx]] = rank + 1

    X_all_full = all_merged[feature_cols].values.astype(np.float32)

    # PD-only data
    sids = pd_merged["sid"].values
    n = len(sids)
    y_true_all = pd_merged[target_col].values.astype(np.float32)
    X_pd_full = pd_merged[feature_cols].values.astype(np.float32)
    y_pred_all = np.zeros(n, dtype=np.float64)

    print(f"\n{'='*60}")
    print(f"  {label} — LOOCV on T1 (N={n})")
    print(f"{'='*60}")

    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        Xd = X_pd_full[mask]
        yd = y_true_all[mask]
        Xt = X_pd_full[i:i + 1]

        # Feature selection inside fold
        sel_idx, sel_names = feature_select(Xd, yd, list(feature_cols), k=500)
        Xd_sel = Xd[:, sel_idx]
        Xt_sel = Xt[:, sel_idx]

        # Stage 1: SSL ranking on ALL subjects using selected features
        X_all_sel = X_all_full[:, sel_idx]

        sids_train = sids[mask].tolist()
        sids_test = [sids[i]]

        train_leaf, test_leaf = ssl_stage1(
            X_all_sel, rank_labels, sids_train, sids_test, all_sids,
        )

        assert train_leaf.shape[0] == Xd_sel.shape[0], (
            f"Shape mismatch: train leaves {train_leaf.shape[0]} vs Xd_sel {Xd_sel.shape[0]}")
        assert test_leaf.shape[0] == Xt_sel.shape[0], (
            f"Shape mismatch: test leaves {test_leaf.shape[0]} vs Xt_sel {Xt_sel.shape[0]}")

        # Combine original selected features + leaf features
        Xd_combined = np.hstack([Xd_sel, train_leaf])
        Xt_combined = np.hstack([Xt_sel, test_leaf])

        ep = predict_fn(Xd_combined, yd, Xt_combined, clip_lo, clip_hi,
                        train_leaf, test_leaf)
        y_pred_all[i] = float(ep[0]) if hasattr(ep, '__len__') else float(ep)

        if (i + 1) % LOOCV_PROGRESS_EVERY == 0:
            running_mae = float(np.mean(np.abs(y_true_all[:i + 1] - y_pred_all[:i + 1])))
            running_ccc = lins_ccc(y_true_all[:i + 1], y_pred_all[:i + 1])
            running_slope = cal_slope(y_true_all[:i + 1], y_pred_all[:i + 1])
            elapsed = time.time() - t0
            remaining = elapsed / (i + 1) * (n - i - 1)
            print(f"    [{i + 1}/{n}] CCC={running_ccc:.3f} slope={running_slope:.3f} "
                  f"MAE={running_mae:.3f} ({elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining)")

    metrics = full_metrics(y_true_all, y_pred_all, target_key)
    metrics["eval_mode"] = "loocv"
    metrics["experiment"] = label
    metrics["runtime_s"] = round(time.time() - t0, 1)
    metrics["per_subject"] = {
        "sids": sids.tolist(),
        "y_true": y_true_all.tolist(),
        "y_pred": y_pred_all.tolist(),
    }
    return metrics


# ═══════════════════════════════════════════════════════════════════════
# EXPERIMENT DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════

def run_e0(pd_merged: pd.DataFrame, all_merged: pd.DataFrame,
           feature_cols: list) -> dict:
    """E0: Baseline — exact replica of P5 5-seed LGB ensemble (MSE loss)."""

    def predict_fn(Xd_combined, yd, Xt_combined, clip_lo, clip_hi,
                   train_leaf, test_leaf):
        preds = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd, Xt_combined, s)
            preds.append(np.clip(p, clip_lo, clip_hi))
        return np.mean(preds, axis=0)

    return ssl_loocv(pd_merged, all_merged, feature_cols, "t1", predict_fn, label="E0_baseline")


def run_e1(pd_merged: pd.DataFrame, all_merged: pd.DataFrame,
           feature_cols: list) -> dict:
    """E1: CCC loss — custom LGB objective maximizing Lin's CCC."""

    def make_ccc_objective(y_full_train: np.ndarray):
        """Create a CCC-based custom objective closure.

        The gradient is computed over the full training set (not just the
        mini-batch seen by each tree). We use the current predictions from
        the model to compute population-level CCC statistics.
        """
        def ccc_objective(preds: np.ndarray, dataset: lgb.Dataset) -> tuple:
            y = dataset.get_label()
            n = len(y)

            mu_y = np.mean(y)
            mu_p = np.mean(preds)
            var_y = np.var(y)
            var_p = np.var(preds)
            cov_yp = np.mean((y - mu_y) * (preds - mu_p))

            D = var_y + var_p + (mu_y - mu_p) ** 2
            if D < 1e-12:
                D = 1e-12

            ccc_val = 2.0 * cov_yp / D

            # Gradient of Loss = 1 - CCC w.r.t. each p_i
            # d(CCC)/d(p_i) = (2/N) * [(y_i - mu_y)/D - CCC*(p_i - mu_p + mu_p - mu_y)/D]
            # d(Loss)/d(p_i) = -d(CCC)/d(p_i)
            grad = -(2.0 / n) * (
                (y - mu_y) / D
                - ccc_val * ((preds - mu_p) + (mu_p - mu_y)) / D
            )

            # Hessian approximation: diagonal constant = 2/N * (1 + CCC) / D
            hess_val = (2.0 / n) * (1.0 + abs(ccc_val)) / D
            hess = np.full(n, hess_val, dtype=np.float64)

            return grad.astype(np.float64), hess

        return ccc_objective

    def predict_fn(Xd_combined, yd, Xt_combined, clip_lo, clip_hi,
                   train_leaf, test_leaf):
        fobj = make_ccc_objective(yd)
        preds = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd, Xt_combined, s, fobj=fobj)
            preds.append(np.clip(p, clip_lo, clip_hi))
        return np.mean(preds, axis=0)

    return ssl_loocv(pd_merged, all_merged, feature_cols, "t1", predict_fn, label="E1_ccc_loss")


def run_e2(pd_merged: pd.DataFrame, all_merged: pd.DataFrame,
           feature_cols: list) -> dict:
    """E2: Quantile median — train LGB at tau={0.1, 0.5, 0.9}, use median as prediction."""

    def predict_fn(Xd_combined, yd, Xt_combined, clip_lo, clip_hi,
                   train_leaf, test_leaf):
        quantile_preds = {}
        for alpha in [0.1, 0.5, 0.9]:
            preds_seeds = []
            for s in SEEDS:
                p = train_lgb_quantile(Xd_combined, yd, Xt_combined, s, alpha)
                preds_seeds.append(np.clip(p, clip_lo, clip_hi))
            quantile_preds[alpha] = np.mean(preds_seeds, axis=0)

        # Use median (tau=0.5) as point prediction
        return quantile_preds[0.5]

    return ssl_loocv(pd_merged, all_merged, feature_cols, "t1", predict_fn, label="E2_quantile_median")


def run_e3(pd_merged: pd.DataFrame, all_merged: pd.DataFrame,
           feature_cols: list) -> dict:
    """E3: KNN — PCA on leaf features, then distance-weighted KNN. Sweep K."""

    best_k = None
    best_ccc = -1.0
    best_metrics = None

    for k_neighbors in [3, 5, 7, 11]:
        print(f"\n  E3: Trying K={k_neighbors}")

        def predict_fn(Xd_combined, yd, Xt_combined, clip_lo, clip_hi,
                       train_leaf, test_leaf, _k=k_neighbors):
            # PCA on leaf features only (not the original selected features)
            n_components = min(30, train_leaf.shape[1], train_leaf.shape[0] - 1)
            pca = PCA(n_components=n_components)
            train_leaf_pca = pca.fit_transform(train_leaf)
            test_leaf_pca = pca.transform(test_leaf)

            knn = KNeighborsRegressor(n_neighbors=min(_k, len(train_leaf_pca) - 1),
                                      weights='distance')
            knn.fit(train_leaf_pca, yd)
            p = knn.predict(test_leaf_pca)
            return np.clip(p, clip_lo, clip_hi)

        metrics = ssl_loocv(pd_merged, all_merged, feature_cols, "t1",
                            predict_fn, label=f"E3_knn_k{k_neighbors}")

        if metrics["ccc"] > best_ccc:
            best_ccc = metrics["ccc"]
            best_k = k_neighbors
            best_metrics = metrics

    print(f"\n  E3 best: K={best_k}, CCC={best_ccc:.3f}")
    best_metrics["experiment"] = f"E3_knn_k{best_k}"
    best_metrics["best_k"] = best_k
    return best_metrics


def run_e4(pd_merged: pd.DataFrame, all_merged: pd.DataFrame,
           feature_cols: list) -> dict:
    """E4: Variance penalty — custom LGB objective penalizing low prediction variance."""

    best_lam = None
    best_ccc = -1.0
    best_metrics = None

    for lam in [0.1, 0.5, 1.0, 2.0, 5.0]:
        print(f"\n  E4: Trying lambda={lam}")

        def make_var_penalty_objective(target_var_ratio: float = 0.95,
                                       lam_val: float = lam):
            """Create variance-penalty objective closure."""
            def var_penalty_obj(preds: np.ndarray, dataset: lgb.Dataset) -> tuple:
                y = dataset.get_label()
                n = len(y)

                target_var = target_var_ratio * np.var(y)
                pred_var = np.var(preds)
                mean_p = np.mean(preds)

                # MSE gradient
                grad = 2.0 * (preds - y) / n

                # Variance penalty gradient (only when under-dispersed)
                if pred_var < target_var:
                    grad += lam_val * (-2.0 / n) * (preds - mean_p)

                # Hessian: MSE hessian + penalty hessian
                hess = np.full(n, 2.0 / n, dtype=np.float64)
                if pred_var < target_var:
                    hess += lam_val * (2.0 / n)

                return grad.astype(np.float64), hess

            return var_penalty_obj

        def predict_fn(Xd_combined, yd, Xt_combined, clip_lo, clip_hi,
                       train_leaf, test_leaf, _lam=lam):
            fobj = make_var_penalty_objective(target_var_ratio=0.95, lam_val=_lam)
            preds = []
            for s in SEEDS:
                p = train_lgb(Xd_combined, yd, Xt_combined, s, fobj=fobj)
                preds.append(np.clip(p, clip_lo, clip_hi))
            return np.mean(preds, axis=0)

        metrics = ssl_loocv(pd_merged, all_merged, feature_cols, "t1",
                            predict_fn, label=f"E4_varp_lam{lam}")

        if metrics["ccc"] > best_ccc:
            best_ccc = metrics["ccc"]
            best_lam = lam
            best_metrics = metrics

    print(f"\n  E4 best: lambda={best_lam}, CCC={best_ccc:.3f}")
    best_metrics["experiment"] = f"E4_varp_lam{best_lam}"
    best_metrics["best_lambda"] = best_lam
    return best_metrics


def run_e5(pd_merged: pd.DataFrame, all_merged: pd.DataFrame,
           feature_cols: list) -> dict:
    """E5: CQR — conformalized quantile regression with spread recalibration.

    Uses E2's 3-quantile approach but splits train into train+cal (85/15),
    computes conformal correction on cal, recalibrates predictions.
    """

    def predict_fn(Xd_combined, yd, Xt_combined, clip_lo, clip_hi,
                   train_leaf, test_leaf):
        n_train = len(yd)
        n_cal = max(1, int(n_train * 0.15))
        n_fit = n_train - n_cal

        # Deterministic split for calibration
        rng = np.random.RandomState(42)
        idx = np.arange(n_train)
        rng.shuffle(idx)
        fit_idx = idx[n_cal:]
        cal_idx = idx[:n_cal]

        Xd_fit = Xd_combined[fit_idx]
        yd_fit = yd[fit_idx]
        Xd_cal = Xd_combined[cal_idx]
        yd_cal = yd[cal_idx]

        # Train 3 quantile models on fit set, predict on cal and test
        quantile_cal = {}
        quantile_test = {}
        for alpha in [0.1, 0.5, 0.9]:
            cal_preds_seeds = []
            test_preds_seeds = []
            for s in SEEDS:
                p_cal = train_lgb_quantile(Xd_fit, yd_fit, Xd_cal, s, alpha)
                p_test = train_lgb_quantile(Xd_fit, yd_fit, Xt_combined, s, alpha)
                cal_preds_seeds.append(np.clip(p_cal, clip_lo, clip_hi))
                test_preds_seeds.append(np.clip(p_test, clip_lo, clip_hi))
            quantile_cal[alpha] = np.mean(cal_preds_seeds, axis=0)
            quantile_test[alpha] = np.mean(test_preds_seeds, axis=0)

        # Recalibrate: p = mean_y_cal + (q50 - mean_q50_cal) * (std_y_cal / std_q50_cal)
        q50_cal = quantile_cal[0.5]
        q50_test = quantile_test[0.5]
        mean_y_cal = np.mean(yd_cal)
        std_y_cal = np.std(yd_cal)
        mean_q50_cal = np.mean(q50_cal)
        std_q50_cal = np.std(q50_cal)

        if std_q50_cal > 1e-8:
            correction = std_y_cal / std_q50_cal
        else:
            correction = 1.0

        p_recal = mean_y_cal + (q50_test - mean_q50_cal) * correction
        return np.clip(p_recal, clip_lo, clip_hi)

    return ssl_loocv(pd_merged, all_merged, feature_cols, "t1", predict_fn, label="E5_cqr")


def run_e6(pd_merged: pd.DataFrame, all_merged: pd.DataFrame,
           feature_cols: list) -> dict:
    """E6: Ridge — PCA on [selected+leaf] features, then Ridge regression. Sweep alpha."""

    best_alpha = None
    best_ccc = -1.0
    best_metrics = None

    for alpha_val in [0.01, 0.1, 1.0, 10.0]:
        print(f"\n  E6: Trying alpha={alpha_val}")

        def predict_fn(Xd_combined, yd, Xt_combined, clip_lo, clip_hi,
                       train_leaf, test_leaf, _alpha=alpha_val):
            n_components = min(30, Xd_combined.shape[1], Xd_combined.shape[0] - 1)
            pca = PCA(n_components=n_components)
            Xd_pca = pca.fit_transform(Xd_combined)
            Xt_pca = pca.transform(Xt_combined)

            ridge = Ridge(alpha=_alpha)
            ridge.fit(Xd_pca, yd)
            p = ridge.predict(Xt_pca)
            return np.clip(p, clip_lo, clip_hi)

        metrics = ssl_loocv(pd_merged, all_merged, feature_cols, "t1",
                            predict_fn, label=f"E6_ridge_a{alpha_val}")

        if metrics["ccc"] > best_ccc:
            best_ccc = metrics["ccc"]
            best_alpha = alpha_val
            best_metrics = metrics

    print(f"\n  E6 best: alpha={best_alpha}, CCC={best_ccc:.3f}")
    best_metrics["experiment"] = f"E6_ridge_a{best_alpha}"
    best_metrics["best_alpha"] = best_alpha
    return best_metrics


def run_e7(pd_merged: pd.DataFrame, all_merged: pd.DataFrame,
           feature_cols: list) -> dict:
    """E7: Temperature — run E0 baseline, then scale predictions away from mean.

    p_scaled = mean_train + T * (p_ens - mean_train)
    Select T that minimizes |slope - 1.0| on LOO predictions.
    """
    # First run E0 to get raw LOO predictions
    print("\n  E7: Running baseline E0 to get raw predictions...")

    def predict_fn_raw(Xd_combined, yd, Xt_combined, clip_lo, clip_hi,
                       train_leaf, test_leaf):
        preds = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd, Xt_combined, s)
            preds.append(np.clip(p, clip_lo, clip_hi))
        return np.mean(preds, axis=0)

    raw_metrics = ssl_loocv(pd_merged, all_merged, feature_cols, "t1",
                            predict_fn_raw, label="E7_raw")

    y_true = np.array(raw_metrics["per_subject"]["y_true"], dtype=np.float64)
    y_pred_raw = np.array(raw_metrics["per_subject"]["y_pred"], dtype=np.float64)
    mean_train = np.mean(y_true)  # population mean as centering point
    clip_lo, clip_hi = TARGET_CLIP["t1"]

    # Sweep T
    temps = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0]
    best_T = 1.0
    best_slope_err = float("inf")

    print("\n  E7 Temperature sweep:")
    for T in temps:
        p_scaled = mean_train + T * (y_pred_raw - mean_train)
        p_scaled = np.clip(p_scaled, clip_lo, clip_hi)
        slope = cal_slope(y_true, p_scaled)
        ccc = lins_ccc(y_true, p_scaled)
        mae = float(np.mean(np.abs(y_true - p_scaled)))
        slope_err = abs(slope - 1.0)
        print(f"    T={T:.1f}: slope={slope:.3f} CCC={ccc:.3f} MAE={mae:.3f} |slope-1|={slope_err:.3f}")
        if slope_err < best_slope_err:
            best_slope_err = slope_err
            best_T = T

    # Apply best T
    p_best = mean_train + best_T * (y_pred_raw - mean_train)
    p_best = np.clip(p_best, clip_lo, clip_hi)

    metrics = full_metrics(y_true, p_best, "t1")
    metrics["eval_mode"] = "loocv"
    metrics["experiment"] = f"E7_temp_T{best_T}"
    metrics["best_T"] = best_T
    metrics["runtime_s"] = raw_metrics["runtime_s"]
    metrics["per_subject"] = {
        "sids": raw_metrics["per_subject"]["sids"],
        "y_true": y_true.tolist(),
        "y_pred": p_best.tolist(),
    }

    print(f"\n  E7 best: T={best_T}, slope={metrics['cal_slope']:.3f}, CCC={metrics['ccc']:.3f}")
    return metrics


# ═══════════════════════════════════════════════════════════════════════
# SUMMARY TABLE
# ═══════════════════════════════════════════════════════════════════════

def print_summary_table(results: dict) -> None:
    """Print comparison table of all experiments."""
    print("\n" + "=" * 90)
    print("  CALIBRATION ABLATION SUMMARY — T1 (observable subscore, items 9-14)")
    print("=" * 90)
    header = f"{'Experiment':<28} {'CCC':>6} {'slope':>7} {'std_r':>7} {'MAE':>6} {'r':>6} {'time':>7}"
    print(header)
    print("-" * 90)

    for name in sorted(results.keys()):
        m = results[name]
        exp_label = m.get("experiment", name)
        print(f"{exp_label:<28} {m['ccc']:>6.3f} {m['cal_slope']:>7.3f} "
              f"{m.get('std_ratio', 0):>7.3f} {m['mae']:>6.3f} {m['r']:>6.3f} "
              f"{m.get('runtime_s', 0):>6.0f}s")

    print("=" * 90)

    # Find best by slope (among those with CCC >= 0.80)
    eligible = {k: v for k, v in results.items() if v["ccc"] >= 0.80}
    if eligible:
        best_slope = max(eligible.items(), key=lambda x: x[1]["cal_slope"])
        best_ccc = max(eligible.items(), key=lambda x: x[1]["ccc"])
        print(f"\n  Best slope (CCC>=0.80): {best_slope[1].get('experiment', best_slope[0])} "
              f"— slope={best_slope[1]['cal_slope']:.3f}, CCC={best_slope[1]['ccc']:.3f}")
        print(f"  Best CCC:  {best_ccc[1].get('experiment', best_ccc[0])} "
              f"— CCC={best_ccc[1]['ccc']:.3f}, slope={best_ccc[1]['cal_slope']:.3f}")


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

EXPERIMENT_MAP = {
    "E0": run_e0,
    "E1": run_e1,
    "E2": run_e2,
    "E3": run_e3,
    "E4": run_e4,
    "E5": run_e5,
    "E6": run_e6,
    "E7": run_e7,
}


def main():
    parser = argparse.ArgumentParser(description="Calibration fix ablation for SSL ranking pipeline")
    parser.add_argument("--experiment", type=str, required=True,
                        help="Experiment(s) to run: E0, E1, ..., E7, or 'all', or comma-separated (E0,E3,E7)")
    args = parser.parse_args()

    # Parse experiment list
    if args.experiment.lower() == "all":
        experiments = list(EXPERIMENT_MAP.keys())
    else:
        experiments = [e.strip().upper() for e in args.experiment.split(",")]
        for e in experiments:
            assert e in EXPERIMENT_MAP, f"Unknown experiment: {e}. Available: {list(EXPERIMENT_MAP.keys())}"

    print(f"Experiments to run: {experiments}")
    print(f"N_CORES: {N_CORES}")
    print(f"SEEDS: {SEEDS}")

    # Load data once
    pd_merged, all_merged, feature_cols, subjects, item_scores = load_features_and_targets()

    results = {}
    for exp_name in experiments:
        print(f"\n{'#' * 70}")
        print(f"#  Running {exp_name}")
        print(f"{'#' * 70}")

        run_fn = EXPERIMENT_MAP[exp_name]
        metrics = run_fn(pd_merged, all_merged, feature_cols)

        results[exp_name] = metrics

        # Save individual result
        out_path = os.path.join(str(RESULTS_DIR), f"calib_v2_{exp_name}.json")
        with open(out_path, "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"\n  Saved: {out_path}")
        print(f"  CCC={metrics['ccc']:.3f}  slope={metrics['cal_slope']:.3f}  "
              f"std_ratio={metrics.get('std_ratio', 0):.3f}  MAE={metrics['mae']:.3f}  "
              f"r={metrics['r']:.3f}")

    # Summary
    if len(results) > 1:
        print_summary_table(results)

    # Save combined results
    if len(results) > 1:
        combined_path = os.path.join(str(RESULTS_DIR), "calib_v2_all.json")
        # Strip per_subject for the combined file (too large)
        combined = {}
        for k, v in results.items():
            combined[k] = {kk: vv for kk, vv in v.items() if kk != "per_subject"}
        with open(combined_path, "w") as f:
            json.dump(combined, f, indent=2)
        print(f"\nCombined summary saved: {combined_path}")


if __name__ == "__main__":
    main()
