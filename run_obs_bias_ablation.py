#!/usr/bin/env python3
"""run_obs_bias_ablation.py — Observable subscore calibration bias ablation.

3 proposals to fix cal_slope from 0.40 toward 1.0 for the observable subscore
(items 3.9-3.14, range 0-24), plus baseline reproduction.

Phases:
  0: Baseline (reproduce Phase 3 observable model)
  1: Walkway Metrics (E1.0-E1.3)
  3: Task-Specific Ensemble (E3.0-E3.2)
  5: VelocityIncrement Features (E5.0-E5.2)

Usage:
    python3 -u run_obs_bias_ablation.py --phase 0
    python3 -u run_obs_bias_ablation.py --phase 1
    python3 -u run_obs_bias_ablation.py --phase 3
    python3 -u run_obs_bias_ablation.py --phase 5
    python3 -u run_obs_bias_ablation.py --phase all
"""
import argparse
import json
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from scipy.signal import welch, find_peaks
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error

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
from xgboost import XGBRegressor

from project_paths import REPO_ROOT, RESULTS_DIR, ensure_dir, results_artifact_path
sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, DATA_DIR, SENSORS, FS, _get_valid_sids
from updrs_columns import find_updrs_value

# ── Constants ────────────────────────────────────────────────────────
ACC_COLS = ["Acc_X", "Acc_Y", "Acc_Z"]
GYR_COLS = ["Gyr_X", "Gyr_Y", "Gyr_Z"]
VELINC_COLS = ["VelInc_X", "VelInc_Y", "VelInc_Z"]
TASKS = ["SelfPace", "HurriedPace", "TUG", "TandemGait", "Balance"]
ALL_TASKS = TASKS + [f"{t}_mat" for t in TASKS] + [f"{t}_matTURN" for t in ["SelfPace", "HurriedPace"]]
SEEDS = [42, 123, 456, 789, 2024]
N_CORES = min(os.cpu_count() or 4, 9)
CLIP_MAX = 24  # observable subscore range [0, 24]
LOOCV_PROGRESS_EVERY = 10

# Items 9-14 for observable subscore
DIRECT_ITEMS = {9, 10, 11, 12, 13, 14}

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

# Gait-relevant sensors for gait regularity features
GAIT_SENSORS = {"L_DorsalFoot", "R_DorsalFoot", "L_Ankle", "R_Ankle",
                "L_LatShank", "R_LatShank", "LowerBack"}

V2_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
FM_CACHE = str(results_artifact_path("fm_embeddings.npz"))
RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))

ensure_dir(RESULTS_DIR)


# ═══════════════════════════════════════════════════════════════════════
# METRICS
# ═══════════════════════════════════════════════════════════════════════

def full_metrics(y_true, y_pred):
    """Compute all metrics including calibration and quartile biases."""
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    r = float(sp_stats.pearsonr(y_true, y_pred)[0]) if len(y_true) > 2 else 0.0
    # CCC
    mu_t, mu_p = np.mean(y_true), np.mean(y_pred)
    var_t, var_p = np.var(y_true), np.var(y_pred)
    cov = np.mean((y_true - mu_t) * (y_pred - mu_p))
    denom = var_t + var_p + (mu_t - mu_p) ** 2
    ccc = float(2 * cov / denom) if denom > 1e-12 else 0.0
    # Calibration
    if np.std(y_true) > 0 and len(y_true) > 2:
        slope, intercept = np.polyfit(y_true, y_pred, 1)
    else:
        slope, intercept = 0.0, 0.0
    # Quartile bias
    quartiles = []
    for label, lo, hi in [("Q1 (<4)", 0, 4), ("Q2 (4-8)", 4, 8),
                           ("Q3 (8-14)", 8, 14), ("Q4 (>=14)", 14, 100)]:
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
# CLINICAL DATA HELPERS
# ═══════════════════════════════════════════════════════════════════════

def parse_item_scores():
    """Parse per-item UPDRS-III scores from clinical CSVs."""
    item_scores = {}
    for fn, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(DATA_DIR, fn)
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
                    for s in sub:
                        v = find_updrs_value(row, df.columns, item_num, s)
                        if v is not None:
                            vals.append(v)
                    if len(vals) == len(sub):
                        scores[item_num] = float(sum(vals))
                    elif len(vals) == 0 and group == "HC":
                        scores[item_num] = 0.0
            if scores:
                item_scores[sid] = scores
    return item_scores


def compute_obs_subscore(item_scores_dict, sid):
    """Sum of items 9-14 for a subject. Returns None if any item missing."""
    if sid not in item_scores_dict:
        return None
    total = 0.0
    for item in DIRECT_ITEMS:
        if item not in item_scores_dict[sid]:
            return None
        total += item_scores_dict[sid][item]
    return total


# ═══════════════════════════════════════════════════════════════════════
# FEATURE EXTRACTION HELPERS
# ═══════════════════════════════════════════════════════════════════════

def td_feats(x, prefix):
    """Time-domain features for a 1D signal."""
    x = np.nan_to_num(x, nan=0.0)
    if len(x) < 10:
        return {f"{prefix}_{s}": 0.0 for s in
                ["rms", "std", "range", "iqr", "skew", "kurt", "jerk", "zcr"]}
    return {
        f"{prefix}_rms": float(np.sqrt(np.mean(x ** 2))),
        f"{prefix}_std": float(np.std(x)),
        f"{prefix}_range": float(np.ptp(x)),
        f"{prefix}_iqr": float(np.percentile(x, 75) - np.percentile(x, 25)),
        f"{prefix}_skew": float(sp_stats.skew(x)),
        f"{prefix}_kurt": float(sp_stats.kurtosis(x)),
        f"{prefix}_jerk": float(np.sqrt(np.mean(np.diff(x) ** 2)) * FS),
        f"{prefix}_zcr": float(np.sum(np.diff(np.sign(x - np.mean(x))) != 0) / len(x)),
    }


def fd_feats(x, prefix, fs=FS):
    """Frequency-domain features."""
    x = np.nan_to_num(x, nan=0.0)
    if len(x) < 64:
        return {f"{prefix}_{s}": 0.0 for s in
                ["loco", "trem", "high", "lr_loco", "lr_trem", "lr_high",
                 "domf", "entropy"]}
    freqs, psd = welch(x, fs=fs, nperseg=min(256, len(x)))
    psd = np.maximum(psd, 1e-12)
    total = psd.sum()

    def band_power(lo, hi):
        mask = (freqs >= lo) & (freqs < hi)
        return psd[mask].sum() if mask.any() else 1e-12

    loco = band_power(0.5, 3.0)
    trem = band_power(3.0, 8.0)
    high = band_power(8.0, 25.0)
    domf = freqs[np.argmax(psd)] if len(psd) > 0 else 0.0
    psd_norm = psd / total
    entropy = float(-np.sum(psd_norm * np.log2(psd_norm + 1e-12)))

    return {
        f"{prefix}_loco": float(loco),
        f"{prefix}_trem": float(trem),
        f"{prefix}_high": float(high),
        f"{prefix}_lr_loco": float(np.log10(loco + 1e-12)),
        f"{prefix}_lr_trem": float(np.log10(trem + 1e-12)),
        f"{prefix}_lr_high": float(np.log10(high + 1e-12)),
        f"{prefix}_domf": float(domf),
        f"{prefix}_entropy": float(entropy),
    }


def gait_reg(acc_v, prefix):
    """Gait regularity from vertical acceleration autocorrelation."""
    x = np.nan_to_num(acc_v, nan=0.0)
    if len(x) < 200:
        return {f"{prefix}_{s}": 0.0 for s in
                ["step_t", "stride_t", "cadence", "step_reg", "stride_reg"]}
    x = x - np.mean(x)
    ac = np.correlate(x, x, mode="full")
    ac = ac[len(ac) // 2:]
    ac = ac / (ac[0] + 1e-12)
    peaks, _ = find_peaks(ac, height=0.1, distance=30)
    step_t = peaks[0] / FS if len(peaks) > 0 else 0.0
    stride_t = peaks[1] / FS if len(peaks) > 1 else 0.0
    cadence = 60.0 / step_t if step_t > 0.2 else 0.0
    step_reg = float(ac[peaks[0]]) if len(peaks) > 0 else 0.0
    stride_reg = float(ac[peaks[1]]) if len(peaks) > 1 else 0.0
    return {
        f"{prefix}_step_t": step_t,
        f"{prefix}_stride_t": stride_t,
        f"{prefix}_cadence": cadence,
        f"{prefix}_step_reg": step_reg,
        f"{prefix}_stride_reg": stride_reg,
    }


# ═══════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════

def get_csv_path(sid, task, subjects):
    """Get CSV path for a subject's recording."""
    grp = subjects[sid]["group"]
    base = "PD PARTICIPANTS" if grp == "PD" else "CONTROL PARTICIPANTS"
    return os.path.join(DATA_DIR, base, "CSV files", f"{sid}_{task}.csv")


def load_cached_features():
    """Load cached v2 + FM features. Fail fast if missing."""
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

    # Standard v2 feature filter
    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_", "obs_subscore"))
               and c != "hy"]

    # Merge v2 + FM
    merged = v2_df[["sid", "updrs3"] + v2_cols].merge(fm_agg, on="sid", how="left").fillna(0.0)
    all_cols = v2_cols + fm_cols

    print(f"Data loaded: {len(merged)} subjects, {len(v2_cols)} v2 + {len(fm_cols)} FM = {len(all_cols)} features")
    return merged, all_cols, v2_cols, fm_cols


def load_walkway():
    """Load walkway gait metrics CSV. Returns dict sid -> {feature: value}."""
    wk_path = os.path.join(DATA_DIR, "Walkway-derived metrics",
                           "PKMAS Walkway Gait Metrics - HP+SP.csv")
    assert os.path.exists(wk_path), f"Walkway CSV not found: {wk_path}"
    df = pd.read_csv(wk_path)
    # Row 0 is sub-headers (#Samples, Mean, Mean-Ratio, etc.), data starts row 1
    sub_headers = df.iloc[0].values
    df = df.iloc[1:].reset_index(drop=True)
    # Find Mean columns (sub_header == "Mean")
    mean_idx = [i for i in range(len(sub_headers)) if str(sub_headers[i]).strip() == "Mean"]
    mean_col_names = [df.columns[i] for i in mean_idx]
    # Clean parameter names
    clean_names = []
    for cn in mean_col_names:
        name = cn.split("(")[0].strip().replace(" ", "_").lower()
        name = name.rstrip(".")
        clean_names.append(f"wk_{name}")

    wk = {}
    for _, row in df.iterrows():
        sid = str(row.get("Participant ID", "")).strip()
        task = str(row.get("Task", "")).strip()
        if not sid or sid == "nan":
            continue
        feats = {}
        for mi, cn in zip(mean_idx, clean_names):
            val = pd.to_numeric(row.iloc[mi], errors="coerce")
            if pd.notna(val):
                feats[cn] = float(val)
        if feats:
            if sid in wk:
                for k, v in feats.items():
                    wk[sid][k] = (wk[sid].get(k, v) + v) / 2
            else:
                wk[sid] = feats
    print(f"Walkway loaded: {len(wk)} subjects, {len(clean_names)} metrics")
    return wk, clean_names


# ═══════════════════════════════════════════════════════════════════════
# ML BUILDING BLOCKS
# ═══════════════════════════════════════════════════════════════════════

def feature_select(X, y, names, k=300):
    """XGBoost importance-based feature selection."""
    k = min(k, X.shape[1])
    sel = XGBRegressor(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
        objective="reg:absoluteerror",
    )
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def train_lgb_single(Xd, yd, Xt, seed):
    """Train single LightGBM, return predictions on Xt."""
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    m = lgb.LGBMRegressor(
        n_estimators=2000, learning_rate=0.03, max_depth=6,
        num_leaves=31, reg_lambda=3.0, min_data_in_leaf=20,
        random_state=seed, n_jobs=N_CORES,
        objective="mse", verbose=-1,
    )
    m.fit(
        Xd[idx[nv:]], yd[idx[nv:]],
        eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    return m.predict(Xt)


def run_lgb_ensemble(Xd, yd, Xt):
    """5-seed LGB ensemble prediction, clipped to [0, CLIP_MAX]."""
    preds = []
    for seed in SEEDS:
        p = train_lgb_single(Xd, yd, Xt, seed)
        preds.append(np.clip(p, 0, CLIP_MAX))
    return np.mean(preds, axis=0)


# ═══════════════════════════════════════════════════════════════════════
# LOOCV ENGINE
# ═══════════════════════════════════════════════════════════════════════

def run_loocv(merged_df, feat_cols, pd_sids, obs_scores, k_select=300,
              experiment_name="unnamed", all_sids=None):
    """PD-only LOOCV. Returns (y_true, y_pred, metrics_dict).

    Args:
        merged_df: DataFrame with sid and feature columns
        feat_cols: list of feature column names
        pd_sids: list of PD subject IDs to iterate over
        obs_scores: dict sid -> obs_subscore value
        k_select: number of features to select
        experiment_name: for logging
        all_sids: all SIDs to use as training pool (default = pd_sids)
    """
    if all_sids is None:
        all_sids = pd_sids

    # Add obs_subscore target column
    df = merged_df.copy()
    df["obs_target"] = df["sid"].map(obs_scores)
    df_valid = df.dropna(subset=["obs_target"])

    valid_pd = [s for s in pd_sids if s in obs_scores]
    print(f"\n  [{experiment_name}] LOOCV over {len(valid_pd)} PD subjects, "
          f"K={k_select}, {len(feat_cols)} features")
    t0 = time.time()

    y_true_all, y_pred_all = [], []
    for i, loo_sid in enumerate(valid_pd):
        # Train on all subjects except the held-out one
        dev_sids = [s for s in all_sids if s != loo_sid and s in obs_scores]
        dm = df_valid["sid"].isin(dev_sids)
        tm = df_valid["sid"] == loo_sid

        Xd = df_valid.loc[dm, feat_cols].values.astype(np.float32)
        yd = df_valid.loc[dm, "obs_target"].values.astype(np.float32)
        Xt = df_valid.loc[tm, feat_cols].values.astype(np.float32)
        yt = df_valid.loc[tm, "obs_target"].values.astype(np.float32)

        if len(Xt) == 0 or len(yt) == 0:
            continue

        # Feature selection inside fold
        sel_idx, _ = feature_select(Xd, yd, feat_cols, k=k_select)
        Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

        pred = run_lgb_ensemble(Xds, yd, Xts)
        y_true_all.append(float(yt[0]))
        y_pred_all.append(float(pred[0]))

        if (i + 1) % LOOCV_PROGRESS_EVERY == 0:
            running_mae = float(np.mean(np.abs(
                np.array(y_true_all) - np.array(y_pred_all))))
            elapsed = time.time() - t0
            eta = elapsed / (i + 1) * (len(valid_pd) - i - 1)
            print(f"    [{i + 1}/{len(valid_pd)}] running MAE={running_mae:.3f} "
                  f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining)")

    y_true_arr = np.array(y_true_all)
    y_pred_arr = np.array(y_pred_all)
    metrics = full_metrics(y_true_arr, y_pred_arr)
    elapsed = time.time() - t0

    print(f"  [{experiment_name}] DONE in {elapsed:.0f}s: MAE={metrics['mae']}, "
          f"CCC={metrics['ccc']}, cal_slope={metrics['cal_slope']}, r={metrics['r']}")
    return y_true_arr, y_pred_arr, metrics


# ═══════════════════════════════════════════════════════════════════════
# PHASE 0: BASELINE
# ═══════════════════════════════════════════════════════════════════════

def phase0():
    """Reproduce Phase 3 observable model as baseline."""
    print("\n" + "=" * 70)
    print("PHASE 0: Baseline (reproduce Phase 3 observable model)")
    print("=" * 70)
    t0 = time.time()

    subjects = parse_clinical()
    item_scores = parse_item_scores()
    merged, all_cols, v2_cols, fm_cols = load_cached_features()

    # Compute obs subscores for all subjects
    all_sids = merged["sid"].tolist()
    obs_scores = {}
    for sid in all_sids:
        val = compute_obs_subscore(item_scores, sid)
        if val is not None:
            obs_scores[sid] = val

    pd_sids = [s for s in all_sids if subjects.get(s, {}).get("group") == "PD"]
    valid_pd = [s for s in pd_sids if s in obs_scores]
    print(f"PD subjects with obs_subscore: {len(valid_pd)}")

    y_true, y_pred, metrics = run_loocv(
        merged, all_cols, pd_sids, obs_scores, k_select=300,
        experiment_name="P0_baseline", all_sids=all_sids,
    )

    results = {
        "phase": 0, "experiment": "P0_baseline",
        "description": "Reproduce Phase 3 observable model (v2+FM, K=300, LOOCV)",
        "metrics": metrics,
        "runtime_s": round(time.time() - t0, 1),
    }
    out_path = str(results_artifact_path("obs_bias_ablation_phase0.json"))
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {out_path}")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 1: WALKWAY METRICS
# ═══════════════════════════════════════════════════════════════════════

def phase1():
    """Walkway gait metrics ablation (E1.0-E1.3)."""
    print("\n" + "=" * 70)
    print("PHASE 1: Walkway Metrics")
    print("=" * 70)
    t0_phase = time.time()

    subjects = parse_clinical()
    item_scores = parse_item_scores()
    merged, all_cols, v2_cols, fm_cols = load_cached_features()

    # Compute obs subscores
    all_sids = merged["sid"].tolist()
    obs_scores = {}
    for sid in all_sids:
        val = compute_obs_subscore(item_scores, sid)
        if val is not None:
            obs_scores[sid] = val

    pd_sids = [s for s in all_sids if subjects.get(s, {}).get("group") == "PD"]

    # Load walkway
    wk_dict, wk_feat_names = load_walkway()
    pd_with_wk = [s for s in pd_sids if s in wk_dict and s in obs_scores]
    pd_without_wk = [s for s in pd_sids if s not in wk_dict and s in obs_scores]
    print(f"PD with walkway: {len(pd_with_wk)}, without: {len(pd_without_wk)}")

    # Build walkway feature columns for all subjects (median imputation for missing)
    wk_all_names = sorted(set().union(*[set(wk_dict[s].keys()) for s in wk_dict]))
    # Compute medians from available data for imputation
    wk_medians = {}
    for col in wk_all_names:
        vals = [wk_dict[s][col] for s in wk_dict if col in wk_dict[s]]
        wk_medians[col] = float(np.median(vals)) if vals else 0.0

    # Add walkway columns to merged
    merged_wk = merged.copy()
    has_walkway_flag = []
    for sid in merged_wk["sid"]:
        has_walkway_flag.append(1.0 if sid in wk_dict else 0.0)
    merged_wk["wk_has_data"] = has_walkway_flag

    for col in wk_all_names:
        vals = []
        for sid in merged_wk["sid"]:
            if sid in wk_dict and col in wk_dict[sid]:
                vals.append(wk_dict[sid][col])
            else:
                vals.append(wk_medians[col])
        merged_wk[col] = vals

    wk_cols_in_df = ["wk_has_data"] + wk_all_names
    print(f"Walkway features in DataFrame: {len(wk_cols_in_df)}")

    experiments = {}

    # E1.0: Walkway-only
    print("\n--- E1.0: Walkway-only ---")
    _, _, m10 = run_loocv(
        merged_wk, wk_cols_in_df, pd_sids, obs_scores, k_select=150,
        experiment_name="E1.0_walkway_only", all_sids=all_sids,
    )
    experiments["E1.0_walkway_only"] = m10

    # E1.1: Walkway + v2 handcrafted
    print("\n--- E1.1: Walkway + v2 ---")
    wk_v2_cols = v2_cols + wk_cols_in_df
    _, _, m11 = run_loocv(
        merged_wk, wk_v2_cols, pd_sids, obs_scores, k_select=300,
        experiment_name="E1.1_walkway_v2", all_sids=all_sids,
    )
    experiments["E1.1_walkway_v2"] = m11

    # E1.2: Walkway + v2 + FM (full fusion)
    print("\n--- E1.2: Walkway + v2 + FM ---")
    wk_all_feat_cols = all_cols + wk_cols_in_df
    _, _, m12 = run_loocv(
        merged_wk, wk_all_feat_cols, pd_sids, obs_scores, k_select=300,
        experiment_name="E1.2_walkway_v2_fm", all_sids=all_sids,
    )
    experiments["E1.2_walkway_v2_fm"] = m12

    # E1.3: Walkway-only, EXCLUDING subjects without walkway data
    print("\n--- E1.3: Walkway-only (walkway-available subjects only) ---")
    wk_available_sids = [s for s in all_sids if s in wk_dict]
    pd_wk_sids = [s for s in pd_sids if s in wk_dict]
    _, _, m13 = run_loocv(
        merged_wk, wk_all_names, pd_wk_sids, obs_scores, k_select=150,
        experiment_name="E1.3_walkway_only_available", all_sids=wk_available_sids,
    )
    experiments["E1.3_walkway_only_available"] = m13

    results = {
        "phase": 1, "description": "Walkway Metrics Ablation",
        "experiments": experiments,
        "n_pd_with_walkway": len(pd_with_wk),
        "n_pd_without_walkway": len(pd_without_wk),
        "runtime_s": round(time.time() - t0_phase, 1),
    }
    out_path = str(results_artifact_path("obs_bias_ablation_phase1.json"))
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nPhase 1 saved: {out_path}")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 3: TASK-SPECIFIC ENSEMBLE
# ═══════════════════════════════════════════════════════════════════════

def extract_task_features_for_subject(sid, task, subjects):
    """Extract handcrafted features from one task's raw CSV.
    Returns dict of features or None if file missing."""
    csv_path = get_csv_path(sid, task, subjects)
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None

    ft = {}
    for sen in SENSORS:
        # Acc features
        acc_c = [f"{sen}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in acc_c):
            acc = np.nan_to_num(df[acc_c].values.astype(np.float32))
            mag = np.sqrt(np.sum(acc ** 2, axis=1))
            for i, ax in enumerate(["x", "y", "z"]):
                ft.update(td_feats(acc[:, i], f"{sen}_a{ax}"))
                ft.update(fd_feats(acc[:, i], f"{sen}_a{ax}"))
            ft.update(td_feats(mag, f"{sen}_am"))
            ft.update(fd_feats(mag, f"{sen}_am"))
            if sen in GAIT_SENSORS:
                ft.update(gait_reg(acc[:, 2], f"{sen}_g"))

        # Gyr features
        gyr_c = [f"{sen}_{c}" for c in GYR_COLS]
        if all(c in df.columns for c in gyr_c):
            gyr = np.nan_to_num(df[gyr_c].values.astype(np.float32))
            gm = np.sqrt(np.sum(gyr ** 2, axis=1))
            ft.update(td_feats(gm, f"{sen}_gm"))
            ft.update(fd_feats(gm, f"{sen}_gm"))

    return ft if ft else None


def phase3():
    """Task-specific ensemble ablation (E3.0-E3.2)."""
    print("\n" + "=" * 70)
    print("PHASE 3: Task-Specific Ensemble")
    print("=" * 70)
    t0_phase = time.time()

    subjects = parse_clinical()
    item_scores = parse_item_scores()

    # Compute obs subscores
    obs_scores = {}
    for sid in subjects:
        val = compute_obs_subscore(item_scores, sid)
        if val is not None:
            obs_scores[sid] = val

    pd_sids = sorted([s for s in subjects if subjects[s]["group"] == "PD" and s in obs_scores])
    all_sids_with_obs = sorted([s for s in subjects if s in obs_scores])
    print(f"PD with obs_subscore: {len(pd_sids)}")

    # Extract per-task features for all subjects
    task_features = {}  # task -> DataFrame with sid + features
    for task in TASKS:
        print(f"\n  Extracting features for task: {task}")
        records = []
        for sid in all_sids_with_obs:
            ft = extract_task_features_for_subject(sid, task, subjects)
            if ft is not None:
                ft["sid"] = sid
                records.append(ft)
            # Also try _mat variant
            ft_mat = extract_task_features_for_subject(sid, f"{task}_mat", subjects)
            if ft_mat is not None:
                ft_mat["sid"] = sid
                records.append(ft_mat)

        if not records:
            print(f"    No recordings found for {task}")
            continue

        df_recs = pd.DataFrame(records)
        num_cols = [c for c in df_recs.columns if c != "sid"]
        df_agg = df_recs.groupby("sid")[num_cols].mean().reset_index()
        df_agg = df_agg.fillna(0.0)
        task_features[task] = df_agg
        sids_with_task = set(df_agg["sid"].tolist())
        n_pd = sum(1 for s in pd_sids if s in sids_with_task)
        print(f"    {task}: {len(df_agg)} subjects ({n_pd} PD), {len(num_cols)} features")

    # Find common PD subjects across all tasks
    common_pd = set(pd_sids)
    for task, df in task_features.items():
        common_pd &= set(df["sid"].tolist())
    common_pd = sorted(common_pd)
    print(f"\nCommon PD subjects across all {len(task_features)} tasks: {len(common_pd)}")

    # Find common all subjects across all tasks (for training pool)
    common_all = set(all_sids_with_obs)
    for task, df in task_features.items():
        common_all &= set(df["sid"].tolist())
    common_all = sorted(common_all)
    print(f"Common all subjects across all tasks: {len(common_all)}")

    experiments = {}

    # ── E3.0: Task-specific ensemble with Ridge meta-learner ──────────
    print("\n--- E3.0: Task-specific ensemble ---")
    t0 = time.time()

    # LOOCV with per-task models + Ridge meta-learner
    y_true_all, y_pred_all = [], []
    for i, loo_sid in enumerate(common_pd):
        dev_sids = [s for s in common_all if s != loo_sid]

        # Per-task OOF predictions for meta-learner
        task_preds_dev = {}  # task -> array of OOF preds for dev subjects
        task_pred_test = {}  # task -> single pred for loo_sid
        dev_sid_order = None  # consistent dev SID ordering for meta-learner

        for task, df_task in task_features.items():
            feat_cols = [c for c in df_task.columns if c != "sid"]
            # Dev and test arrays
            dm = df_task["sid"].isin(dev_sids)
            tm = df_task["sid"] == loo_sid
            if tm.sum() == 0:
                continue

            dev_sids_in_task = df_task.loc[dm, "sid"].tolist()
            Xd = df_task.loc[dm, feat_cols].values.astype(np.float32)
            yd = np.array([obs_scores[s] for s in dev_sids_in_task], dtype=np.float32)
            Xt = df_task.loc[tm, feat_cols].values.astype(np.float32)

            # Feature selection inside fold
            k = min(150, Xd.shape[1])
            sel_idx, _ = feature_select(Xd, yd, feat_cols, k=k)
            Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

            pred = run_lgb_ensemble(Xds, yd, Xts)
            task_pred_test[task] = float(pred[0])

            # For meta-learner training: train on dev, predict dev (in-sample)
            dev_pred = run_lgb_ensemble(Xds, yd, Xds)
            task_preds_dev[task] = dev_pred
            dev_sid_order = dev_sids_in_task  # same across tasks (common_all - loo_sid)

        if len(task_pred_test) < 2 or dev_sid_order is None:
            continue

        # Ridge meta-learner on task predictions
        task_order = sorted(task_pred_test.keys())
        meta_X_dev = np.column_stack([task_preds_dev[t] for t in task_order])
        meta_y_dev = np.array([obs_scores[s] for s in dev_sid_order], dtype=np.float32)
        meta_X_test = np.array([[task_pred_test[t] for t in task_order]])

        meta = Ridge(alpha=1.0)
        meta.fit(meta_X_dev, meta_y_dev)
        final_pred = float(np.clip(meta.predict(meta_X_test)[0], 0, CLIP_MAX))

        y_true_all.append(obs_scores[loo_sid])
        y_pred_all.append(final_pred)

        if (i + 1) % LOOCV_PROGRESS_EVERY == 0:
            running_mae = float(np.mean(np.abs(
                np.array(y_true_all) - np.array(y_pred_all))))
            elapsed = time.time() - t0
            eta = elapsed / (i + 1) * (len(common_pd) - i - 1)
            print(f"    [{i + 1}/{len(common_pd)}] running MAE={running_mae:.3f} "
                  f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining)")

    y_true_arr = np.array(y_true_all)
    y_pred_arr = np.array(y_pred_all)
    m30 = full_metrics(y_true_arr, y_pred_arr)
    print(f"  E3.0 DONE in {time.time() - t0:.0f}s: MAE={m30['mae']}, "
          f"CCC={m30['ccc']}, cal_slope={m30['cal_slope']}")
    experiments["E3.0_task_ensemble"] = m30

    # ── E3.1: Best single task model ──────────────────────────────────
    print("\n--- E3.1: Best single task model ---")
    task_metrics = {}
    for task, df_task in task_features.items():
        print(f"\n  Single task: {task}")
        t0_task = time.time()
        feat_cols = [c for c in df_task.columns if c != "sid"]
        task_pd = [s for s in pd_sids if s in set(df_task["sid"].tolist())]
        task_all = [s for s in all_sids_with_obs if s in set(df_task["sid"].tolist())]

        if len(task_pd) < 10:
            print(f"    SKIP: only {len(task_pd)} PD subjects for {task}")
            continue

        # Add obs target
        df_t = df_task.copy()
        df_t["obs_target"] = df_t["sid"].map(obs_scores)
        df_t_valid = df_t.dropna(subset=["obs_target"])

        y_true_t, y_pred_t = [], []
        for j, loo_sid in enumerate(task_pd):
            dev_t = [s for s in task_all if s != loo_sid and s in obs_scores]
            dm = df_t_valid["sid"].isin(dev_t)
            tm = df_t_valid["sid"] == loo_sid

            Xd = df_t_valid.loc[dm, feat_cols].values.astype(np.float32)
            yd = df_t_valid.loc[dm, "obs_target"].values.astype(np.float32)
            Xt = df_t_valid.loc[tm, feat_cols].values.astype(np.float32)
            yt = df_t_valid.loc[tm, "obs_target"].values.astype(np.float32)

            if len(Xt) == 0:
                continue

            k = min(150, Xd.shape[1])
            sel_idx, _ = feature_select(Xd, yd, feat_cols, k=k)
            pred = run_lgb_ensemble(Xd[:, sel_idx], yd, Xt[:, sel_idx])
            y_true_t.append(float(yt[0]))
            y_pred_t.append(float(pred[0]))

            if (j + 1) % LOOCV_PROGRESS_EVERY == 0:
                running_mae = float(np.mean(np.abs(
                    np.array(y_true_t) - np.array(y_pred_t))))
                print(f"    [{j + 1}/{len(task_pd)}] {task} running MAE={running_mae:.3f}")

        if len(y_true_t) > 2:
            m_task = full_metrics(np.array(y_true_t), np.array(y_pred_t))
            task_metrics[task] = m_task
            print(f"  {task}: MAE={m_task['mae']}, CCC={m_task['ccc']}, "
                  f"cal_slope={m_task['cal_slope']} ({time.time() - t0_task:.0f}s)")

    # Find best single task
    if task_metrics:
        best_task = min(task_metrics, key=lambda t: task_metrics[t]["mae"])
        print(f"\n  Best single task: {best_task} (MAE={task_metrics[best_task]['mae']})")
        experiments["E3.1_single_task_results"] = task_metrics
        experiments["E3.1_best_task"] = best_task
        experiments["E3.1_best_metrics"] = task_metrics[best_task]

    # ── E3.2: Task-specific + walkway fusion ──────────────────────────
    print("\n--- E3.2: Task-specific + walkway fusion ---")
    t0_e32 = time.time()

    wk_dict, wk_feat_names = load_walkway()
    wk_all_names = sorted(set().union(*[set(wk_dict[s].keys()) for s in wk_dict]))
    wk_medians = {}
    for col in wk_all_names:
        vals = [wk_dict[s][col] for s in wk_dict if col in wk_dict[s]]
        wk_medians[col] = float(np.median(vals)) if vals else 0.0

    # LOOCV with per-task + walkway
    y_true_32, y_pred_32 = [], []
    for i, loo_sid in enumerate(common_pd):
        dev_sids = [s for s in common_all if s != loo_sid]

        task_pred_test = {}
        task_preds_dev = {}
        dev_sid_order_32 = None

        for task, df_task in task_features.items():
            feat_cols = [c for c in df_task.columns if c != "sid"]
            dm = df_task["sid"].isin(dev_sids)
            tm = df_task["sid"] == loo_sid
            if tm.sum() == 0:
                continue

            dev_sids_in_task = df_task.loc[dm, "sid"].tolist()
            Xd = df_task.loc[dm, feat_cols].values.astype(np.float32)
            yd = np.array([obs_scores[s] for s in dev_sids_in_task], dtype=np.float32)
            Xt = df_task.loc[tm, feat_cols].values.astype(np.float32)

            k = min(150, Xd.shape[1])
            sel_idx, _ = feature_select(Xd, yd, feat_cols, k=k)
            Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

            pred = run_lgb_ensemble(Xds, yd, Xts)
            task_pred_test[task] = float(pred[0])
            dev_pred = run_lgb_ensemble(Xds, yd, Xds)
            task_preds_dev[task] = dev_pred
            dev_sid_order_32 = dev_sids_in_task

        if len(task_pred_test) < 2 or dev_sid_order_32 is None:
            continue

        # Add walkway features to meta-learner
        task_order = sorted(task_pred_test.keys())
        meta_X_dev_base = np.column_stack([task_preds_dev[t] for t in task_order])
        meta_y_dev = np.array([obs_scores[s] for s in dev_sid_order_32], dtype=np.float32)

        # Walkway features for dev subjects
        dev_sid_list = dev_sid_order_32
        wk_dev = np.array([[wk_dict.get(s, {}).get(c, wk_medians[c]) for c in wk_all_names]
                           for s in dev_sid_list], dtype=np.float32)
        wk_test = np.array([[wk_dict.get(loo_sid, {}).get(c, wk_medians[c])
                             for c in wk_all_names]], dtype=np.float32)

        meta_X_dev = np.hstack([meta_X_dev_base, wk_dev])
        meta_X_test = np.array([[task_pred_test[t] for t in task_order]])
        meta_X_test = np.hstack([meta_X_test, wk_test])

        meta = Ridge(alpha=1.0)
        meta.fit(meta_X_dev, meta_y_dev)
        final_pred = float(np.clip(meta.predict(meta_X_test)[0], 0, CLIP_MAX))

        y_true_32.append(obs_scores[loo_sid])
        y_pred_32.append(final_pred)

        if (i + 1) % LOOCV_PROGRESS_EVERY == 0:
            running_mae = float(np.mean(np.abs(
                np.array(y_true_32) - np.array(y_pred_32))))
            print(f"    [{i + 1}/{len(common_pd)}] running MAE={running_mae:.3f}")

    if len(y_true_32) > 2:
        m32 = full_metrics(np.array(y_true_32), np.array(y_pred_32))
        print(f"  E3.2 DONE in {time.time() - t0_e32:.0f}s: MAE={m32['mae']}, "
              f"CCC={m32['ccc']}, cal_slope={m32['cal_slope']}")
        experiments["E3.2_task_walkway_fusion"] = m32

    results = {
        "phase": 3, "description": "Task-Specific Ensemble Ablation",
        "experiments": experiments,
        "n_common_pd": len(common_pd),
        "n_tasks": len(task_features),
        "runtime_s": round(time.time() - t0_phase, 1),
    }
    out_path = str(results_artifact_path("obs_bias_ablation_phase3.json"))
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nPhase 3 saved: {out_path}")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 5: VELOCITY INCREMENT FEATURES
# ═══════════════════════════════════════════════════════════════════════

def extract_velinc_features(csv_path, sid, phase_gated=False):
    """Extract VelocityIncrement features from one CSV recording.

    Args:
        csv_path: path to CSV file
        sid: subject ID
        phase_gated: if True, extract Walk-only and Turn-only features separately

    Returns dict of features or None if file missing or no VelInc columns.
    """
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None

    # Check if VelInc columns exist
    first_sensor = SENSORS[0]
    test_col = f"{first_sensor}_VelInc_X"
    if test_col not in df.columns:
        return None

    ft = {}

    if phase_gated and "GeneralEvent" in df.columns:
        # Phase-gated extraction: separate Walk vs Turn
        events = df["GeneralEvent"].fillna("")
        walk_mask = events.str.contains("Walk", case=False, na=False)
        turn_mask = events.str.contains("Turn", case=False, na=False)

        for phase_name, mask in [("walk", walk_mask), ("turn", turn_mask)]:
            df_phase = df[mask]
            if len(df_phase) < 64:
                continue
            for sen in SENSORS:
                vi_c = [f"{sen}_{c}" for c in VELINC_COLS]
                if all(c in df_phase.columns for c in vi_c):
                    vi = np.nan_to_num(df_phase[vi_c].values.astype(np.float32))
                    mag = np.sqrt(np.sum(vi ** 2, axis=1))
                    for i, ax in enumerate(["x", "y", "z"]):
                        ft.update(td_feats(vi[:, i], f"{sen}_vi{ax}_{phase_name}"))
                        ft.update(fd_feats(vi[:, i], f"{sen}_vi{ax}_{phase_name}"))
                    ft.update(td_feats(mag, f"{sen}_vim_{phase_name}"))
                    ft.update(fd_feats(mag, f"{sen}_vim_{phase_name}"))
    else:
        # Full-recording extraction
        for sen in SENSORS:
            vi_c = [f"{sen}_{c}" for c in VELINC_COLS]
            if all(c in df.columns for c in vi_c):
                vi = np.nan_to_num(df[vi_c].values.astype(np.float32))
                mag = np.sqrt(np.sum(vi ** 2, axis=1))
                for i, ax in enumerate(["x", "y", "z"]):
                    ft.update(td_feats(vi[:, i], f"{sen}_vi{ax}"))
                    ft.update(fd_feats(vi[:, i], f"{sen}_vi{ax}"))
                ft.update(td_feats(mag, f"{sen}_vim"))
                ft.update(fd_feats(mag, f"{sen}_vim"))

    return ft if ft else None


def extract_velinc_for_all_subjects(subjects, all_sids, phase_gated=False):
    """Extract VelocityIncrement features for all subjects across all tasks.
    Returns DataFrame with sid + features."""
    print(f"  Extracting VelInc features (phase_gated={phase_gated})...")
    t0 = time.time()
    records = []
    n_found = 0
    for sid in all_sids:
        if sid not in subjects:
            continue
        sid_records = []
        for task in ALL_TASKS:
            csv_path = get_csv_path(sid, task, subjects)
            if not os.path.exists(csv_path):
                continue
            ft = extract_velinc_features(csv_path, sid, phase_gated=phase_gated)
            if ft is not None:
                ft["sid"] = sid
                sid_records.append(ft)
                n_found += 1
        if sid_records:
            records.extend(sid_records)

    if not records:
        print(f"    No VelInc data found! VelInc columns may not exist in CSVs.")
        return None

    df = pd.DataFrame(records).fillna(0.0)
    num_cols = [c for c in df.columns if c != "sid"]
    df_agg = df.groupby("sid")[num_cols].mean().reset_index()
    print(f"  VelInc: {len(df_agg)} subjects, {len(num_cols)} features, "
          f"{n_found} recordings ({time.time() - t0:.0f}s)")
    return df_agg


def phase5():
    """VelocityIncrement features ablation (E5.0-E5.2)."""
    print("\n" + "=" * 70)
    print("PHASE 5: VelocityIncrement Features")
    print("=" * 70)
    t0_phase = time.time()

    subjects = parse_clinical()
    item_scores = parse_item_scores()
    merged, all_cols, v2_cols, fm_cols = load_cached_features()

    # Compute obs subscores
    all_sids = merged["sid"].tolist()
    obs_scores = {}
    for sid in all_sids:
        val = compute_obs_subscore(item_scores, sid)
        if val is not None:
            obs_scores[sid] = val

    pd_sids = [s for s in all_sids if subjects.get(s, {}).get("group") == "PD"]

    experiments = {}

    # Extract VelInc (non-gated)
    vi_df = extract_velinc_for_all_subjects(subjects, all_sids, phase_gated=False)
    if vi_df is None:
        print("  FATAL: No VelocityIncrement data found. Skipping Phase 5.")
        results = {
            "phase": 5, "description": "VelocityIncrement Features - NO DATA",
            "experiments": {}, "runtime_s": round(time.time() - t0_phase, 1),
        }
        out_path = str(results_artifact_path("obs_bias_ablation_phase5.json"))
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        return results

    vi_cols = [c for c in vi_df.columns if c != "sid"]

    # Merge VelInc with main DataFrame
    merged_vi = merged.merge(vi_df, on="sid", how="left").fillna(0.0)

    # E5.0: VelInc features only
    print("\n--- E5.0: VelInc-only ---")
    vi_sids_set = set(vi_df["sid"].tolist())
    pd_vi_sids = [s for s in pd_sids if s in vi_sids_set and s in obs_scores]
    all_vi_sids = [s for s in all_sids if s in vi_sids_set]
    print(f"  PD with VelInc: {len(pd_vi_sids)}")

    _, _, m50 = run_loocv(
        merged_vi, vi_cols, pd_vi_sids, obs_scores, k_select=150,
        experiment_name="E5.0_velinc_only", all_sids=all_vi_sids,
    )
    experiments["E5.0_velinc_only"] = m50

    # E5.1: VelInc + v2 + FM (additive)
    print("\n--- E5.1: VelInc + v2 + FM ---")
    vi_v2_fm_cols = all_cols + vi_cols
    _, _, m51 = run_loocv(
        merged_vi, vi_v2_fm_cols, pd_sids, obs_scores, k_select=300,
        experiment_name="E5.1_velinc_v2_fm", all_sids=all_sids,
    )
    experiments["E5.1_velinc_v2_fm"] = m51

    # E5.2: Phase-gated VelInc (Walk-only + Turn-only)
    print("\n--- E5.2: Phase-gated VelInc ---")
    vi_gated_df = extract_velinc_for_all_subjects(subjects, all_sids, phase_gated=True)
    if vi_gated_df is not None:
        vi_gated_cols = [c for c in vi_gated_df.columns if c != "sid"]
        merged_vi_gated = merged.merge(vi_gated_df, on="sid", how="left").fillna(0.0)
        vi_gated_all_cols = all_cols + vi_gated_cols
        pd_vi_gated_sids = [s for s in pd_sids if s in set(vi_gated_df["sid"].tolist())
                            and s in obs_scores]
        all_vi_gated_sids = [s for s in all_sids if s in set(vi_gated_df["sid"].tolist())]

        print(f"  PD with phase-gated VelInc: {len(pd_vi_gated_sids)}")

        _, _, m52 = run_loocv(
            merged_vi_gated, vi_gated_all_cols, pd_sids, obs_scores, k_select=300,
            experiment_name="E5.2_velinc_phase_gated", all_sids=all_sids,
        )
        experiments["E5.2_velinc_phase_gated"] = m52
    else:
        print("  Phase-gated VelInc extraction returned no data (no GeneralEvent column?)")
        experiments["E5.2_velinc_phase_gated"] = {"error": "no phase-gated data"}

    results = {
        "phase": 5, "description": "VelocityIncrement Features Ablation",
        "experiments": experiments,
        "n_velinc_features": len(vi_cols),
        "runtime_s": round(time.time() - t0_phase, 1),
    }
    out_path = str(results_artifact_path("obs_bias_ablation_phase5.json"))
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nPhase 5 saved: {out_path}")
    return results


# ═══════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════

def print_summary(all_results):
    """Print a comparison table across all experiments."""
    print("\n" + "=" * 90)
    print("SUMMARY: Observable Subscore Calibration Bias Ablation")
    print("=" * 90)
    print(f"{'Experiment':<40} {'MAE':>6} {'CCC':>6} {'cal_slope':>10} {'r':>6} {'N':>5}")
    print("-" * 90)

    for r in all_results:
        if isinstance(r, dict):
            phase = r.get("phase", "?")
            if "metrics" in r:
                # Phase 0 format
                m = r["metrics"]
                name = r.get("experiment", f"P{phase}")
                print(f"{name:<40} {m['mae']:>6.3f} {m['ccc']:>6.3f} "
                      f"{m['cal_slope']:>10.3f} {m['r']:>6.3f} {m['n']:>5d}")
            elif "experiments" in r:
                # Phases 1, 3, 5 format
                for ename, m in r["experiments"].items():
                    if isinstance(m, dict) and "mae" in m:
                        print(f"{ename:<40} {m['mae']:>6.3f} {m['ccc']:>6.3f} "
                              f"{m['cal_slope']:>10.3f} {m['r']:>6.3f} {m['n']:>5d}")

    print("=" * 90)
    print("\nTarget: cal_slope closer to 1.0 (current baseline ~0.40)")
    print("Observable subscore range: [0, 24], items 3.9-3.14")


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Observable subscore calibration bias ablation")
    parser.add_argument("--phase", type=str, required=True,
                        help="Phase to run: 0, 1, 3, 5, or all")
    args = parser.parse_args()

    phases = args.phase.strip().lower()
    if phases == "all":
        run_phases = [0, 1, 3, 5]
    else:
        run_phases = [int(p.strip()) for p in phases.split(",")]

    valid_phases = {0, 1, 3, 5}
    for p in run_phases:
        assert p in valid_phases, f"Invalid phase: {p}. Valid: {sorted(valid_phases)}"

    print("=" * 70)
    print("OBSERVABLE SUBSCORE CALIBRATION BIAS ABLATION")
    print(f"Phases: {run_phases}")
    print(f"Items: 3.9-3.14 (direct observable), max=24")
    print(f"Seeds: {SEEDS}")
    print(f"Device: CPU (GPU too slow for N=94)")
    print("=" * 70)

    t0_total = time.time()
    all_results = []

    if 0 in run_phases:
        all_results.append(phase0())

    if 1 in run_phases:
        all_results.append(phase1())

    if 3 in run_phases:
        all_results.append(phase3())

    if 5 in run_phases:
        all_results.append(phase5())

    print_summary(all_results)

    total_time = time.time() - t0_total
    print(f"\nTotal runtime: {total_time:.0f}s ({total_time / 60:.1f} min)")


if __name__ == "__main__":
    main()
