#!/usr/bin/env python3
"""Calibration-fix ablation study for UPDRS-III prediction.

Systematically tests 5 intervention categories to fix the severe calibration
bias (slope=0.26) in PD-only total UPDRS-III prediction:
  Phase 0: Baseline verification
  Phase 1: Feature expansion (Euler angles + FreeAcc)
  Phase 2: Residual modeling on demographics
  Phase 3: Walkway integration
  Phase 4: Post-hoc calibration
  Phase 5: Training modifications
  Phase 6: Grand combination
  Phase 7: Held-out validation

Usage:
  uv run python run_calibration_ablation.py --phase 0
  uv run python run_calibration_ablation.py --phase 1
  uv run python run_calibration_ablation.py --phase 1,2,4  # multiple phases
  uv run python run_calibration_ablation.py --phase all

Output: results/calibration_ablation_phase{N}.json
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
from scipy.stats import pearsonr, spearmanr, wilcoxon
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

warnings.filterwarnings("ignore")

# ─── Shared modules ──────────────────────────────────────────────────────────
from project_paths import RESULTS_DIR, DATA_DIR, results_artifact_path
from data_split import parse_clinical, SENSORS as DS_SENSORS

# ─── Constants ────────────────────────────────────────────────────────────────
FS = 100  # Hz
SEEDS = [42, 123, 456, 789, 2024]
MCID = 3.25
OBS_ITEMS = [9, 10, 11, 12, 13, 14]  # directly observable
PARTIAL_ITEMS = [5, 6, 7, 8, 15, 16, 17]
UNOBS_ITEMS = [1, 2, 3, 4, 18]
LOOCV_PROGRESS_EVERY = 10

# Target configuration (set by --target flag in main)
_TARGET_COL = "updrs3"
_CLIP_MAX = 132
_OUTPUT_PREFIX = "calibration_ablation"
_PHASE1_MODE = "replacement"
FM_MODEL = "AutonLab/MOMENT-1-base"
FM_SEQ_LEN = 512
FM_BATCH_SIZE = 32


def clip_pred(pred):
    """Clip predictions to target range."""
    return np.clip(pred, 0, _CLIP_MAX)

# Sensors
SENSORS = [
    "L_Wrist", "R_Wrist", "LowerBack", "L_Thigh", "R_Thigh",
    "L_Shank", "R_Shank", "L_DorsalFoot", "R_DorsalFoot",
    "L_Ankle", "R_Ankle", "Xiphoid", "Forehead"
]
ACC_COLS = ["Acc_X", "Acc_Y", "Acc_Z"]
GYR_COLS = ["Gyr_X", "Gyr_Y", "Gyr_Z"]
FREEACC_COLS = ["FreeAcc_E", "FreeAcc_N", "FreeAcc_U"]
EULER_COLS = ["Roll", "Pitch", "Yaw"]

GAIT_SENSORS = {"L_DorsalFoot", "R_DorsalFoot", "L_Ankle", "R_Ankle",
                "L_Shank", "R_Shank", "LowerBack"}
PAIRED_SENSORS = [
    ("L_Wrist", "R_Wrist"), ("L_Thigh", "R_Thigh"),
    ("L_Shank", "R_Shank"), ("L_DorsalFoot", "R_DorsalFoot"),
    ("L_Ankle", "R_Ankle")
]

# ─── Metrics ──────────────────────────────────────────────────────────────────

def lin_ccc(y_true, y_pred):
    """Lin's concordance correlation coefficient."""
    yt, yp = np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float)
    mask = np.isfinite(yt) & np.isfinite(yp)
    yt, yp = yt[mask], yp[mask]
    if len(yt) < 3:
        return 0.0
    my, mp = yt.mean(), yp.mean()
    sy, sp = yt.var(), yp.var()
    sxy = np.mean((yt - my) * (yp - mp))
    denom = sy + sp + (my - mp) ** 2
    return float(2 * sxy / denom) if denom > 0 else 0.0


def calibration_slope_intercept(y_true, y_pred):
    """Regression of predicted on true (slope=1, intercept=0 ideal)."""
    yt, yp = np.asarray(y_true), np.asarray(y_pred)
    if len(yt) < 3:
        return 0.0, 0.0
    slope, intercept = np.polyfit(yt, yp, 1)
    return float(slope), float(intercept)


def full_metrics(y_true, y_pred, prefix=""):
    """Compute all metrics for a prediction set."""
    yt, yp = np.asarray(y_true), np.asarray(y_pred)
    mae = mean_absolute_error(yt, yp)
    rmse = np.sqrt(mean_squared_error(yt, yp))
    r, r_p = pearsonr(yt, yp) if len(yt) > 2 else (0.0, 1.0)
    rho, rho_p = spearmanr(yt, yp) if len(yt) > 2 else (0.0, 1.0)
    ccc = lin_ccc(yt, yp)
    r2 = r2_score(yt, yp) if len(yt) > 2 else 0.0
    cal_s, cal_i = calibration_slope_intercept(yt, yp)
    p = prefix + "_" if prefix else ""
    return {
        f"{p}mae": round(mae, 3),
        f"{p}rmse": round(rmse, 3),
        f"{p}r": round(r, 3),
        f"{p}r_p": round(r_p, 6),
        f"{p}rho": round(rho, 3),
        f"{p}ccc": round(ccc, 3),
        f"{p}r2": round(r2, 3),
        f"{p}cal_slope": round(cal_s, 3),
        f"{p}cal_intercept": round(cal_i, 3),
        f"{p}n": len(yt),
    }


def severity_quartile_metrics(y_true, y_pred):
    """Per-quartile metrics for calibration analysis."""
    yt, yp = np.asarray(y_true), np.asarray(y_pred)
    if _CLIP_MAX <= 30:  # obs_subscore (0-24)
        quartiles = [
            ("Q1 (<4)", yt < 4),
            ("Q2 (4-8)", (yt >= 4) & (yt < 8)),
            ("Q3 (8-14)", (yt >= 8) & (yt < 14)),
            ("Q4 (>=14)", yt >= 14),
        ]
    else:  # total UPDRS (0-132)
        quartiles = [
            ("Q1 (<12)", yt < 12),
            ("Q2 (12-20)", (yt >= 12) & (yt < 20)),
            ("Q3 (20-35)", (yt >= 20) & (yt < 35)),
            ("Q4 (>=35)", yt >= 35),
        ]
    results = []
    for label, mask in quartiles:
        if mask.sum() < 2:
            continue
        m = full_metrics(yt[mask], yp[mask])
        m["label"] = label
        m["n"] = int(mask.sum())
        m["bias"] = round(float(np.mean(yp[mask] - yt[mask])), 2)
        results.append(m)
    return results


# ─── Feature extraction ──────────────────────────────────────────────────────

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
    from scipy.signal import welch
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
    # Find first two peaks (step, stride)
    from scipy.signal import find_peaks
    peaks, props = find_peaks(ac, height=0.1, distance=30)
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


def _add_stream_features(ft, values, axis_labels, axis_prefixes, mag_prefix,
                         gait_prefix=None):
    """Add per-axis and magnitude features for a 3-axis stream."""
    for i, ax_label in enumerate(axis_labels):
        ft.update(td_feats(values[:, i], f"{axis_prefixes}{ax_label}"))
        ft.update(fd_feats(values[:, i], f"{axis_prefixes}{ax_label}"))

    mag = np.sqrt(np.sum(values ** 2, axis=1))
    ft.update(td_feats(mag, mag_prefix))
    ft.update(fd_feats(mag, mag_prefix))

    if gait_prefix is not None:
        ft.update(gait_reg(values[:, 2], gait_prefix))


def extract_recording_features(csv_path, sid, task, include_euler=False,
                                use_freeacc=False, append_freeacc=False):
    """Extract features from one CSV recording.

    Args:
        include_euler: If True, extract Roll/Pitch/Yaw features (3 axes × 13 sensors).
        use_freeacc: If True, prefer FreeAcc_E/N/U over Acc_X/Y/Z where available.
        append_freeacc: If True, append distinct FreeAcc features on top of the
            raw-accelerometer feature set using unique `fa*` prefixes.
    """
    df = pd.read_csv(csv_path)
    ft = {"sid": sid, "task": task, "n_samples": len(df),
          "duration_s": len(df) / FS}

    for sen in SENSORS:
        raw_acc_c = [f"{sen}_{c}" for c in ACC_COLS]
        freeacc_c = [f"{sen}_{c}" for c in FREEACC_COLS]
        gyr_c = [f"{sen}_{c}" for c in GYR_COLS]

        # Raw accelerometer features (baseline stream)
        add_raw_acc = append_freeacc or not use_freeacc
        if add_raw_acc and all(c in df.columns for c in raw_acc_c):
            acc = np.nan_to_num(df[raw_acc_c].values.astype(np.float32))
            gait_prefix = f"{sen}_g" if sen in GAIT_SENSORS else None
            _add_stream_features(
                ft, acc, "xyz", f"{sen}_a", f"{sen}_am", gait_prefix=gait_prefix
            )

        # Preferred accelerometer replacement path
        if use_freeacc and not append_freeacc:
            acc_c = freeacc_c if all(c in df.columns for c in freeacc_c) else raw_acc_c
            if all(c in df.columns for c in acc_c):
                acc = np.nan_to_num(df[acc_c].values.astype(np.float32))
                gait_prefix = f"{sen}_g" if sen in GAIT_SENSORS else None
                _add_stream_features(
                    ft, acc, "xyz", f"{sen}_a", f"{sen}_am", gait_prefix=gait_prefix
                )

        # Additive FreeAcc features with distinct names
        if append_freeacc and all(c in df.columns for c in freeacc_c):
            facc = np.nan_to_num(df[freeacc_c].values.astype(np.float32))
            gait_prefix = f"{sen}_fg" if sen in GAIT_SENSORS else None
            _add_stream_features(
                ft, facc, "enu", f"{sen}_fa", f"{sen}_fam", gait_prefix=gait_prefix
            )

        # Gyroscope features
        if all(c in df.columns for c in gyr_c):
            gyr = np.nan_to_num(df[gyr_c].values.astype(np.float32))
            gm = np.sqrt(np.sum(gyr ** 2, axis=1))
            ft.update(td_feats(gm, f"{sen}_gm"))
            ft.update(fd_feats(gm, f"{sen}_gm"))

        # Euler angle features (Roll, Pitch, Yaw)
        if include_euler:
            eul_c = [f"{sen}_{c}" for c in EULER_COLS]
            if all(c in df.columns for c in eul_c):
                eul = np.nan_to_num(df[eul_c].values.astype(np.float32))
                for i, ax in enumerate(["ro", "pi", "ya"]):
                    ft.update(td_feats(eul[:, i], f"{sen}_{ax}"))
                    ft.update(fd_feats(eul[:, i], f"{sen}_{ax}"))
                # Euler magnitude (total orientation change rate)
                eul_mag = np.sqrt(np.sum(eul ** 2, axis=1))
                ft.update(td_feats(eul_mag, f"{sen}_em"))

    return ft


def aggregate_to_subject(records: List[dict]) -> pd.DataFrame:
    """Aggregate recording-level features to subject level (mean)."""
    df = pd.DataFrame(records)
    num_cols = [c for c in df.columns if c not in ("sid", "task")]
    agg = df.groupby("sid")[num_cols].mean().reset_index()
    return agg


# ─── Data loading ─────────────────────────────────────────────────────────────

def load_covariates_from_cache():
    """Load covariates from the v2 feature cache."""
    v2 = load_v2_features()
    cv_cols = ["sid", "cv_age", "cv_sex", "cv_ht", "cv_wt", "cv_yrs", "cv_dbs"]
    cols = [c for c in cv_cols if c in v2.columns]
    return v2[cols].drop_duplicates("sid").set_index("sid").to_dict("index")


V2_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
TASKS = ["SelfPace", "HurriedPace", "TUG", "TandemGait", "Balance"]
ALL_TASKS = TASKS + [f"{t}_mat" for t in TASKS] + \
            [f"{t}_matTURN" for t in ["SelfPace", "HurriedPace"]]


def load_v2_features():
    """Load v2 feature cache (precomputed by run_ablation_v3.py --phase 0)."""
    if not os.path.exists(V2_CACHE):
        raise FileNotFoundError(
            f"V2 feature cache not found: {V2_CACHE}\n"
            f"Run: python3 run_ablation_v3.py --phase 0 first")
    return pd.read_csv(V2_CACHE)


def get_csv_paths_for_sid(sid, group):
    """Get all CSV recording paths for a subject ID."""
    if group == "PD":
        csv_dir = os.path.join(str(DATA_DIR), "PD PARTICIPANTS", "CSV files")
    else:
        csv_dir = os.path.join(str(DATA_DIR), "CONTROL PARTICIPANTS", "CSV files")
    paths = []
    for task in ALL_TASKS:
        p = os.path.join(csv_dir, f"{sid}_{task}.csv")
        if os.path.exists(p):
            paths.append((p, task))
    return paths


# ─── FM embeddings ────────────────────────────────────────────────────────────

def load_fm_embeddings():
    """Load cached FM embeddings (768-dim per recording) and recording SIDs.

    FM cache only has 'embeddings'. Recording SIDs come from the recording cache
    (rocket_recordings.npz) which tracks the subject-to-recording mapping.
    """
    cache = RESULTS_DIR / "fm_embeddings.npz"
    rec_cache = RESULTS_DIR / "rocket_recordings.npz"
    if not cache.exists():
        raise FileNotFoundError(f"FM cache not found: {cache}. Run FM extraction first.")
    if not rec_cache.exists():
        raise FileNotFoundError(f"Recording cache not found: {rec_cache}")
    fm_data = np.load(cache)
    rec_data = np.load(rec_cache)
    embeddings = fm_data["embeddings"]
    rec_sids = rec_data["sids"].tolist()
    assert len(embeddings) == len(rec_sids), \
        f"FM ({len(embeddings)}) and recording ({len(rec_sids)}) counts mismatch"
    return embeddings, rec_sids


def fm_features_for_subjects(embeddings, rec_sids, target_sids):
    """Aggregate FM embeddings to subject level."""
    fm_df = pd.DataFrame(embeddings, columns=[f"fm_{i}" for i in range(embeddings.shape[1])])
    fm_df["sid"] = rec_sids
    agg = fm_df.groupby("sid").mean().reset_index()
    return agg[agg["sid"].isin(target_sids)]


def load_recording_cache():
    """Load cached raw recordings used for FM extraction."""
    rec_cache = RESULTS_DIR / "rocket_recordings.npz"
    if not rec_cache.exists():
        raise FileNotFoundError(f"Recording cache not found: {rec_cache}")
    rec_data = np.load(rec_cache)
    return rec_data["recordings"], rec_data["sids"].tolist(), rec_data["tasks"].tolist()


def extract_fm_embeddings_custom(rec_array, cache_name, norm_mode="global"):
    """Extract frozen FM embeddings with a configurable normalization mode."""
    cache_path = RESULTS_DIR / cache_name
    if cache_path.exists():
        print(f"[cache] Loading custom FM embeddings from {cache_path}")
        data = np.load(cache_path)
        return data["embeddings"]

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch required for FM extraction") from exc
    try:
        from momentfm import MOMENTPipeline
    except ImportError:
        import subprocess
        print("Installing momentfm...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "momentfm"])
        from momentfm import MOMENTPipeline

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading {FM_MODEL} on {device} for norm_mode={norm_mode}...")
    t0 = time.time()
    model = MOMENTPipeline.from_pretrained(
        FM_MODEL,
        model_kwargs={"task_name": "embedding"}
    )
    model.init()
    model = model.to(device)
    model.eval()
    print(f"  Model loaded in {time.time()-t0:.1f}s")

    trunc_len = min(FM_SEQ_LEN, rec_array.shape[2])
    data = rec_array[:, :, :trunc_len].copy().astype(np.float32)

    if norm_mode == "global":
        for ch in range(data.shape[1]):
            ch_data = data[:, ch, :].ravel()
            mu = float(np.mean(ch_data))
            std = float(np.std(ch_data)) + 1e-8
            data[:, ch, :] = (data[:, ch, :] - mu) / std
    elif norm_mode == "recording":
        mu = data.mean(axis=2, keepdims=True)
        std = data.std(axis=2, keepdims=True) + 1e-8
        data = (data - mu) / std
    else:
        raise ValueError(f"Unknown FM norm_mode: {norm_mode}")

    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

    if trunc_len < FM_SEQ_LEN:
        pad_width = FM_SEQ_LEN - trunc_len
        data = np.pad(data, ((0, 0), (0, 0), (0, pad_width)), mode="constant")

    embeddings = []
    n = len(data)
    t1 = time.time()
    with torch.no_grad():
        for i in range(0, n, FM_BATCH_SIZE):
            batch = data[i:i + FM_BATCH_SIZE]
            x = torch.from_numpy(batch).float().to(device)

            raw_batch = rec_array[i:i + FM_BATCH_SIZE, :, :trunc_len]
            mask_arr = (np.abs(raw_batch).sum(axis=1) > 1e-6).astype(np.float32)
            if trunc_len < FM_SEQ_LEN:
                mask_arr = np.pad(
                    mask_arr,
                    ((0, 0), (0, FM_SEQ_LEN - trunc_len)),
                    mode="constant",
                    constant_values=0,
                )
            mask_t = torch.from_numpy(mask_arr).to(device)

            output = model(x_enc=x, input_mask=mask_t)
            emb = output.embeddings
            if emb.dim() == 3:
                emb = emb.mean(dim=1)
            embeddings.append(emb.cpu().numpy())

            done = min(i + FM_BATCH_SIZE, n)
            if done % (FM_BATCH_SIZE * 10) == 0 or done == n:
                elapsed = time.time() - t1
                rate = done / max(elapsed, 0.1)
                eta = (n - done) / max(rate, 0.1) / 60
                print(f"  FM[{norm_mode}]: {done}/{n} ({elapsed:.0f}s, {rate:.1f} rec/s, ETA={eta:.1f}m)")

    embeddings = np.vstack(embeddings)
    embeddings = np.nan_to_num(embeddings, nan=0.0, posinf=0.0, neginf=0.0)
    np.savez_compressed(cache_path, embeddings=embeddings)
    print(f"  Saved custom FM embeddings: {cache_path}")
    return embeddings


def fm_features_task_aware(embeddings, rec_sids, rec_tasks, target_sids, mode):
    """Aggregate FM embeddings with task-aware pooling."""
    emb_cols = [f"fm_{i}" for i in range(embeddings.shape[1])]
    fm_df = pd.DataFrame(embeddings, columns=emb_cols)
    fm_df["sid"] = rec_sids
    fm_df["task"] = rec_tasks
    fm_df = fm_df[fm_df["sid"].isin(target_sids)].copy()

    if mode == "subject_mean":
        agg = fm_df.groupby("sid")[emb_cols].mean().reset_index()
        return agg

    task_values = sorted(fm_df["task"].dropna().unique().tolist())
    frames = []
    for task in task_values:
        task_df = fm_df[fm_df["task"] == task]
        if task_df.empty:
            continue
        task_mean = task_df.groupby("sid")[emb_cols].mean().reset_index()
        safe_task = task.lower()
        task_mean = task_mean.rename(columns={c: f"{safe_task}_mean_{c}" for c in emb_cols})
        frames.append(task_mean)

        if mode == "task_mean_var":
            task_var = task_df.groupby("sid")[emb_cols].var().fillna(0.0).reset_index()
            task_var = task_var.rename(columns={c: f"{safe_task}_var_{c}" for c in emb_cols})
            frames.append(task_var)

    base = pd.DataFrame({"sid": sorted(set(target_sids))})
    for frame in frames:
        base = base.merge(frame, on="sid", how="left")
    return base.fillna(0.0)


# ─── Model training ──────────────────────────────────────────────────────────

def feature_select(X, y, names, k=150):
    """XGBoost importance-based feature selection."""
    from xgboost import XGBRegressor
    params = dict(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        reg_lambda=2.0, random_state=42, objective="reg:absoluteerror",
        verbosity=0
    )
    try:
        import torch
        if torch.cuda.is_available():
            params["device"] = "cuda"
            params["tree_method"] = "hist"
    except ImportError:
        pass
    sel = XGBRegressor(**params)
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def train_lgb(Xd, yd, Xt, seed=42, objective="mae", sample_weight=None):
    """Train LightGBM, return test predictions."""
    import lightgbm as lgb
    nv = max(1, int(len(Xd) * 0.15))
    idx = np.random.RandomState(seed).permutation(len(Xd))
    val_idx, train_idx = idx[:nv], idx[nv:]

    params = dict(
        n_estimators=2000, learning_rate=0.03, max_depth=6,
        reg_lambda=3.0, objective=objective, verbose=-1,
        random_state=seed, n_jobs=-1
    )
    # Use GPU if available
    try:
        import torch
        if torch.cuda.is_available():
            params["device"] = "gpu"
    except ImportError:
        pass

    m = lgb.LGBMRegressor(**params)
    fit_kw = dict(
        eval_set=[(Xd[val_idx], yd[val_idx])],
        callbacks=[lgb.early_stopping(100, verbose=False)]
    )
    if sample_weight is not None:
        fit_kw["sample_weight"] = sample_weight[train_idx]

    m.fit(Xd[train_idx], yd[train_idx], **fit_kw)
    pred = m.predict(Xt)
    return clip_pred(pred), m


def run_ensemble(Xd, yd, Xt, k_feats, fnames, k=150, objective="mae",
                 sample_weight=None):
    """Feature select → 5-seed LGB ensemble."""
    sel_idx, sel_names = feature_select(Xd, yd, fnames, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]
    preds = []
    for seed in SEEDS:
        p, _ = train_lgb(Xds, yd, Xts, seed, objective=objective,
                         sample_weight=sample_weight)
        preds.append(p)
    return np.mean(preds, axis=0), sel_names


def run_stack(Xd, yd, Xt, fnames, k=150, objective="mae",
              sample_weight=None):
    """Feature select → 5-seed LGB+XGB stacking with Ridge meta-learner."""
    import lightgbm as lgb
    from xgboost import XGBRegressor
    from sklearn.model_selection import KFold

    sel_idx, sel_names = feature_select(Xd, yd, fnames, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

    all_preds = []
    for seed in SEEDS:
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        oof_lgb = np.zeros(len(Xds))
        oof_xgb = np.zeros(len(Xds))
        test_lgb = np.zeros(len(Xts))
        test_xgb = np.zeros(len(Xts))

        for fold_idx, (tr, va) in enumerate(kf.split(Xds)):
            # LGB
            lgb_params = dict(
                n_estimators=1500, learning_rate=0.03, max_depth=6,
                reg_lambda=3.0, objective=objective, verbose=-1,
                random_state=seed + fold_idx, n_jobs=-1
            )
            try:
                import torch
                if torch.cuda.is_available():
                    lgb_params["device"] = "gpu"
            except ImportError:
                pass
            m_lgb = lgb.LGBMRegressor(**lgb_params)
            fit_kw = dict(
                eval_set=[(Xds[va], yd[va])],
                callbacks=[lgb.early_stopping(80, verbose=False)]
            )
            if sample_weight is not None:
                fit_kw["sample_weight"] = sample_weight[tr]
            m_lgb.fit(Xds[tr], yd[tr], **fit_kw)
            oof_lgb[va] = m_lgb.predict(Xds[va])
            test_lgb += m_lgb.predict(Xts) / 5

            # XGB
            m_xgb = XGBRegressor(
                n_estimators=1000, learning_rate=0.03, max_depth=5,
                reg_lambda=3.0, objective="reg:absoluteerror",
                random_state=seed + fold_idx, verbosity=0, n_jobs=-1
            )
            try:
                import torch
                if torch.cuda.is_available():
                    m_xgb.set_params(device="cuda")
            except ImportError:
                pass
            m_xgb.fit(Xds[tr], yd[tr], eval_set=[(Xds[va], yd[va])],
                      verbose=False)
            oof_xgb[va] = m_xgb.predict(Xds[va])
            test_xgb += m_xgb.predict(Xts) / 5

        # Meta-learner
        meta_X_train = np.column_stack([oof_lgb, oof_xgb])
        meta_X_test = np.column_stack([test_lgb, test_xgb])
        meta = Ridge(alpha=1.0)
        meta.fit(meta_X_train, yd)
        pred = clip_pred(meta.predict(meta_X_test))
        all_preds.append(pred)

    return np.mean(all_preds, axis=0), sel_names


# ─── LOOCV infrastructure ────────────────────────────────────────────────────

def run_loocv(feat_df, pd_sids, target_col="updrs3", feature_cols=None,
              k=150, use_stack=False, residual_mode=False,
              demo_cols=None, objective="mae", sample_weight_fn=None,
              progress_label=None):
    """PD-only leave-one-out cross-validation.

    Args:
        feat_df: DataFrame with sid, features, target_col
        pd_sids: list of PD subject IDs
        target_col: column to predict (updrs3 or obs_subscore)
        feature_cols: list of feature column names (if None, auto-detect)
        k: number of features to select
        use_stack: if True, use LGB+XGB stacking; else ensemble
        residual_mode: if True, predict residual after demographics
        demo_cols: demographic columns for residual mode
        objective: LGB objective
        sample_weight_fn: callable(y_train) -> weights
    """
    df = feat_df[feat_df["sid"].isin(pd_sids)].copy().reset_index(drop=True)

    if feature_cols is None:
        feature_cols = [c for c in df.columns
                        if c not in ("sid", "updrs3", "obs_subscore", "group")
                        and not c.startswith("obs_")]

    if demo_cols is None:
        demo_cols = ["cv_age", "cv_sex", "cv_yrs", "cv_ht", "cv_wt"]

    y_true_all = []
    y_pred_all = []
    sids_all = []

    t0 = time.time()
    for i, test_sid in enumerate(pd_sids):
        train_mask = df["sid"] != test_sid
        test_mask = df["sid"] == test_sid

        if test_mask.sum() == 0:
            continue

        Xd = df.loc[train_mask, feature_cols].values.astype(np.float32)
        Xt = df.loc[test_mask, feature_cols].values.astype(np.float32)
        yd = df.loc[train_mask, target_col].values.astype(np.float32)
        yt = df.loc[test_mask, target_col].values.astype(np.float32)

        if residual_mode:
            # Fit demographic Ridge on training set
            Xd_demo = df.loc[train_mask, demo_cols].values.astype(np.float32)
            Xt_demo = df.loc[test_mask, demo_cols].values.astype(np.float32)
            demo_model = Ridge(alpha=1.0)
            demo_model.fit(Xd_demo, yd)
            yd_demo = demo_model.predict(Xd_demo)
            yt_demo = demo_model.predict(Xt_demo)
            # Residual target
            yd_resid = yd - yd_demo
            # Train IMU model on residual
            sw = sample_weight_fn(yd) if sample_weight_fn else None
            if use_stack:
                pred_resid, _ = run_stack(Xd, yd_resid, Xt, feature_cols, k,
                                          objective, sw)
            else:
                pred_resid, _ = run_ensemble(Xd, yd_resid, Xt, None,
                                             feature_cols, k, objective, sw)
            pred = yt_demo + pred_resid
        else:
            sw = sample_weight_fn(yd) if sample_weight_fn else None
            if use_stack:
                pred, _ = run_stack(Xd, yd, Xt, feature_cols, k,
                                    objective, sw)
            else:
                pred, _ = run_ensemble(Xd, yd, Xt, None, feature_cols, k,
                                       objective, sw)

        pred = clip_pred(pred)
        y_true_all.append(yt[0])
        y_pred_all.append(pred[0])
        sids_all.append(test_sid)

        fold_idx = i + 1
        if progress_label and (fold_idx % LOOCV_PROGRESS_EVERY == 0 or fold_idx == len(pd_sids)):
            elapsed = time.time() - t0
            rate = fold_idx / max(elapsed, 0.1)
            eta_min = (len(pd_sids) - fold_idx) / max(rate, 0.1) / 60
            print(f"    [{progress_label}] LOOCV {fold_idx}/{len(pd_sids)} "
                  f"({elapsed/60:.1f}m elapsed, ETA {eta_min:.1f}m)")

    return np.array(y_true_all), np.array(y_pred_all), sids_all


def run_10split(feat_df, pd_sids, subjects, target_col="updrs3",
                feature_cols=None, k=150, n_splits=10,
                use_stack=False, residual_mode=False,
                demo_cols=None, objective="mae", sample_weight_fn=None):
    """PD-only 10-split cross-validation with variance estimates."""
    from sklearn.model_selection import StratifiedKFold

    df = feat_df[feat_df["sid"].isin(pd_sids)].copy().reset_index(drop=True)

    if feature_cols is None:
        feature_cols = [c for c in df.columns
                        if c not in ("sid", "updrs3", "obs_subscore", "group")
                        and not c.startswith("obs_")]

    if demo_cols is None:
        demo_cols = ["cv_age", "cv_sex", "cv_yrs", "cv_ht", "cv_wt"]

    # Create stratification bins
    y_all = df[target_col].values
    bins = pd.qcut(y_all, q=4, labels=False, duplicates="drop")

    split_results = []
    for seed in range(n_splits):
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
        y_true_split = []
        y_pred_split = []

        for train_idx, test_idx in skf.split(df, bins):
            Xd = df.iloc[train_idx][feature_cols].values.astype(np.float32)
            Xt = df.iloc[test_idx][feature_cols].values.astype(np.float32)
            yd = df.iloc[train_idx][target_col].values.astype(np.float32)
            yt = df.iloc[test_idx][target_col].values.astype(np.float32)

            if residual_mode:
                Xd_demo = df.iloc[train_idx][demo_cols].values.astype(np.float32)
                Xt_demo = df.iloc[test_idx][demo_cols].values.astype(np.float32)
                demo_model = Ridge(alpha=1.0)
                demo_model.fit(Xd_demo, yd)
                yd_resid = yd - demo_model.predict(Xd_demo)
                yt_demo = demo_model.predict(Xt_demo)
                sw = sample_weight_fn(yd) if sample_weight_fn else None
                pred_resid, _ = run_ensemble(Xd, yd_resid, Xt, None,
                                             feature_cols, k, objective, sw)
                pred = clip_pred(yt_demo + pred_resid)
            else:
                sw = sample_weight_fn(yd) if sample_weight_fn else None
                pred, _ = run_ensemble(Xd, yd, Xt, None, feature_cols, k,
                                       objective, sw)
                pred = clip_pred(pred)

            y_true_split.extend(yt.tolist())
            y_pred_split.extend(pred.tolist())

        m = full_metrics(y_true_split, y_pred_split)
        m["seed"] = seed
        split_results.append(m)

    # Aggregate
    maes = [r["mae"] for r in split_results]
    cccs = [r["ccc"] for r in split_results]
    slopes = [r["cal_slope"] for r in split_results]
    return {
        "mae_mean": round(np.mean(maes), 3),
        "mae_std": round(np.std(maes), 3),
        "ccc_mean": round(np.mean(cccs), 3),
        "ccc_std": round(np.std(cccs), 3),
        "cal_slope_mean": round(np.mean(slopes), 3),
        "cal_slope_std": round(np.std(slopes), 3),
        "splits": split_results,
    }


# ─── Observable subscore ─────────────────────────────────────────────────────

def load_obs_subscores():
    """Load observable subscores from the v2 feature cache."""
    v2 = load_v2_features()
    return dict(zip(v2["sid"], v2["obs_subscore"]))


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def phase0():
    """Phase 0: Baseline verification."""
    print("\n" + "=" * 60)
    print(f"PHASE 0: Baseline Verification (target={_TARGET_COL})")
    print("=" * 60)

    if _TARGET_COL == "updrs3":
        # Total UPDRS: load from cached results
        pe = json.loads((RESULTS_DIR / "pd_only_experiments.json").read_text())
        mt = pe["master_table"]
        fm_loocv = mt["loocv_fm"]
        demo_loocv = mt["loocv_demo"]

        p3 = json.loads((RESULTS_DIR / "pd_only_phase3.json").read_text())
        direct = p3["subscores"]["direct"]["loocv"]

        print(f"\n  FM LOOCV:  MAE={fm_loocv['mae']}, CCC={fm_loocv['ccc']}, "
              f"cal_slope={fm_loocv['cal_slope']}, intercept={fm_loocv['cal_intercept']}")
        print(f"  Demo LOOCV: MAE={demo_loocv['mae']}, CCC={demo_loocv['ccc']}, "
              f"cal_slope={demo_loocv['cal_slope']}")
        print(f"  Obs LOOCV:  MAE={direct['mae']}, CCC={direct['ccc']}, "
              f"cal_slope={direct['cal_slope']}")

        p4 = json.loads((RESULTS_DIR / "pd_only_phase4.json").read_text())
        print("\n  Severity quartile baselines:")
        for q in p4["severity_quartiles"]:
            print(f"    {q['label']}: MAE={q['mae']:.2f}, bias={q['bias']:+.1f}, "
                  f"cal_slope={q['cal_slope']:.3f}")

        result = {
            "phase": "0_baseline",
            "target": "updrs3",
            "fm_loocv": fm_loocv,
            "demo_loocv": demo_loocv,
            "obs_loocv": direct,
            "severity_quartiles": p4["severity_quartiles"],
        }
    else:
        # Observable subscore: run fresh LOOCV baselines
        subjects = parse_clinical()
        pd_sids = sorted([s for s, info in subjects.items()
                           if info.get("group") == "PD"])

        v2_full = load_v2_features()
        v2_df = v2_full[v2_full["sid"].isin(pd_sids)].copy().reset_index(drop=True)
        fm_emb, fm_rec_sids = load_fm_embeddings()
        fm_agg = fm_features_for_subjects(fm_emb, fm_rec_sids, pd_sids)
        fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]
        merged = v2_df.merge(fm_agg[["sid"] + fm_cols], on="sid", how="left").fillna(0.0)

        v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3", "group")
                   and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_",
                                         "ext_", "obs_"))]
        all_cols = v2_cols + fm_cols
        demo_cols = ["cv_age", "cv_sex", "cv_yrs", "cv_ht", "cv_wt"]

        obs_scores = load_obs_subscores()
        merged["obs_subscore"] = merged["sid"].map(obs_scores)

        # FM LOOCV on obs_subscore
        print(f"\n  Running FM LOOCV for obs_subscore ({len(pd_sids)} PD subjects)...")
        t0 = time.time()
        yt, yp, _ = run_loocv(merged, pd_sids, "obs_subscore", all_cols, k=300)
        fm_obs = full_metrics(yt, yp)
        fm_obs["quartiles"] = severity_quartile_metrics(yt, yp)
        fm_obs["time_s"] = round(time.time() - t0, 1)
        print(f"  FM obs LOOCV: MAE={fm_obs['mae']}, CCC={fm_obs['ccc']}, "
              f"cal_slope={fm_obs['cal_slope']}")

        # Demo Ridge LOOCV on obs_subscore
        print(f"\n  Running Demo Ridge LOOCV for obs_subscore...")
        t0 = time.time()
        df_pd = merged[merged["sid"].isin(pd_sids)].copy().reset_index(drop=True)
        y_true_demo, y_pred_demo = [], []
        for test_sid in pd_sids:
            train_mask = df_pd["sid"] != test_sid
            test_mask = df_pd["sid"] == test_sid
            if test_mask.sum() == 0:
                continue
            Xd = df_pd.loc[train_mask, demo_cols].values.astype(np.float32)
            Xt = df_pd.loc[test_mask, demo_cols].values.astype(np.float32)
            yd = df_pd.loc[train_mask, "obs_subscore"].values.astype(np.float32)
            yt_val = df_pd.loc[test_mask, "obs_subscore"].values.astype(np.float32)
            m = Ridge(alpha=1.0)
            m.fit(Xd, yd)
            pred = clip_pred(m.predict(Xt))
            y_true_demo.append(yt_val[0])
            y_pred_demo.append(pred[0])
        demo_obs = full_metrics(y_true_demo, y_pred_demo)
        demo_obs["quartiles"] = severity_quartile_metrics(y_true_demo, y_pred_demo)
        demo_obs["time_s"] = round(time.time() - t0, 1)
        print(f"  Demo obs LOOCV: MAE={demo_obs['mae']}, CCC={demo_obs['ccc']}, "
              f"cal_slope={demo_obs['cal_slope']}")

        # Load cached obs result from Phase 3 for reference
        p3 = json.loads((RESULTS_DIR / "pd_only_phase3.json").read_text())
        direct_cached = p3["subscores"]["direct"]["loocv"]
        print(f"\n  Cached direct obs (items 9-14): MAE={direct_cached['mae']}, "
              f"CCC={direct_cached['ccc']}, cal_slope={direct_cached['cal_slope']}")

        result = {
            "phase": "0_baseline",
            "target": "obs_subscore",
            "fm_obs_loocv": fm_obs,
            "demo_obs_loocv": demo_obs,
            "cached_direct_obs": direct_cached,
        }

    save_result(f"{_OUTPUT_PREFIX}_phase0.json", result)
    print("\n  Phase 0 complete.")
    return result


def phase1():
    """Phase 1: Feature expansion (Euler angles + FreeAcc)."""
    print("\n" + "=" * 60)
    print(f"PHASE 1: Feature Expansion (Euler + FreeAcc, mode={_PHASE1_MODE})")
    print("=" * 60)

    subjects = parse_clinical()
    pd_sids = sorted([s for s, info in subjects.items()
                       if info.get("group") == "PD"])
    print(f"  PD subjects: {len(pd_sids)}")

    # Load existing v2 baseline features for E1.0 control
    v2_full = load_v2_features()
    v2_df = v2_full[v2_full["sid"].isin(pd_sids)].copy().reset_index(drop=True)

    # Load FM embeddings
    fm_emb, fm_rec_sids = load_fm_embeddings()
    fm_agg = fm_features_for_subjects(fm_emb, fm_rec_sids, pd_sids)
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]

    # Merge v2 + FM for baseline
    baseline_df = v2_df.merge(fm_agg[["sid"] + fm_cols], on="sid", how="left").fillna(0.0)
    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3", "group")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_",
                                     "ext_", "obs_"))]
    all_baseline_cols = v2_cols + fm_cols

    # Compute observable subscores
    obs_scores = load_obs_subscores()
    baseline_df["obs_subscore"] = baseline_df["sid"].map(obs_scores)

    results = {"phase": "1_feature_expansion", "experiments": {}}

    # ── E1.0: Baseline control (v2 + FM, no Euler, no FreeAcc) ──
    print("\n  [E1.0] Baseline control (v2+FM)...")
    t0 = time.time()
    yt, yp, sids = run_loocv(
        baseline_df, pd_sids, "updrs3", all_baseline_cols, k=300,
        progress_label="E1.0 total"
    )
    m_total = full_metrics(yt, yp, "total")
    yt_obs, yp_obs, _ = run_loocv(
        baseline_df, pd_sids, "obs_subscore", all_baseline_cols, k=300,
        progress_label="E1.0 obs"
    )
    m_obs = full_metrics(yt_obs, yp_obs, "obs")
    results["experiments"]["E1.0_baseline"] = {
        **m_total, **m_obs,
        "quartiles": severity_quartile_metrics(yt, yp),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    Total: MAE={m_total['total_mae']}, CCC={m_total['total_ccc']}, "
          f"cal_slope={m_total['total_cal_slope']}")
    print(f"    Obs:   MAE={m_obs['obs_mae']}, CCC={m_obs['obs_ccc']}, "
          f"cal_slope={m_obs['obs_cal_slope']}")

    # For phases E1.1-E1.3 we need re-extracted features from CSV
    # This requires access to raw CSVs (on remote GPU server)
    def extract_expanded_features(sids, include_euler, use_freeacc, label,
                                  append_freeacc=False):
        """Extract features with expanded channels."""
        print(f"\n  [{label}] Extracting features (euler={include_euler}, "
              f"freeacc={use_freeacc}, append_freeacc={append_freeacc})...")
        t0 = time.time()
        records = []
        for i, sid in enumerate(sids):
            if (i + 1) % 20 == 0:
                print(f"    {i+1}/{len(sids)} subjects...")
            group = subjects[sid].get("group", "PD")
            csv_paths = get_csv_paths_for_sid(sid, group)
            for csv_path, task in csv_paths:
                ft = extract_recording_features(
                    csv_path, sid, task,
                    include_euler=include_euler,
                    use_freeacc=use_freeacc,
                    append_freeacc=append_freeacc,
                )
                records.append(ft)

        feat_df = aggregate_to_subject(records)
        # Add targets
        feat_df["updrs3"] = feat_df["sid"].map(
            {s: subjects[s].get("updrs3", 0.0) for s in sids})
        feat_df["obs_subscore"] = feat_df["sid"].map(obs_scores)
        # Add covariates from v2 cache
        covs = load_covariates_from_cache()
        for cv in ["cv_age", "cv_sex", "cv_ht", "cv_wt", "cv_yrs", "cv_dbs"]:
            feat_df[cv] = feat_df["sid"].map(
                {s: covs.get(s, {}).get(cv, 0.0) for s in sids})
        print(f"    Extracted {len(feat_df)} subjects, "
              f"{len(feat_df.columns)} features in {time.time()-t0:.0f}s")
        return feat_df

    def merge_with_baseline(extra_df):
        """Merge only genuinely new feature columns onto the cached v2 baseline."""
        extra_cols = [
            c for c in extra_df.columns
            if c not in ("sid", "updrs3", "obs_subscore", "group")
            and not c.startswith("cv_")
            and c not in baseline_df.columns
        ]
        merged_df = baseline_df.merge(
            extra_df[["sid"] + extra_cols], on="sid", how="left"
        ).fillna(0.0)
        return merged_df, all_baseline_cols + extra_cols, extra_cols

    # ── E1.1: +Euler ──
    euler_df = extract_expanded_features(
        pd_sids, True, False, "E1.1", append_freeacc=False
    )
    if _PHASE1_MODE == "additive":
        euler_df, euler_all_cols, euler_extra_cols = merge_with_baseline(euler_df)
    else:
        euler_feat_cols = [c for c in euler_df.columns
                           if c not in ("sid", "updrs3", "obs_subscore", "group")
                           and not c.startswith(("cv_", "obs_"))]
        euler_df = euler_df.merge(
            fm_agg[["sid"] + fm_cols], on="sid", how="left"
        ).fillna(0.0)
        euler_all_cols = euler_feat_cols + fm_cols
        euler_extra_cols = euler_feat_cols

    print(f"\n  [E1.1] +Euler LOOCV (total + obs)...")
    t0 = time.time()
    yt, yp, _ = run_loocv(
        euler_df, pd_sids, "updrs3", euler_all_cols, k=350,
        progress_label="E1.1 total"
    )
    m_total = full_metrics(yt, yp, "total")
    yt_obs, yp_obs, _ = run_loocv(
        euler_df, pd_sids, "obs_subscore", euler_all_cols, k=350,
        progress_label="E1.1 obs"
    )
    m_obs = full_metrics(yt_obs, yp_obs, "obs")
    results["experiments"]["E1.1_euler"] = {
        **m_total, **m_obs,
        "n_features": len(euler_all_cols),
        "n_added_features": len(euler_extra_cols),
        "quartiles": severity_quartile_metrics(yt, yp),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    Total: MAE={m_total['total_mae']}, CCC={m_total['total_ccc']}, "
          f"cal_slope={m_total['total_cal_slope']}")
    print(f"    Obs:   MAE={m_obs['obs_mae']}, CCC={m_obs['obs_ccc']}")

    # ── E1.2: +FreeAcc ──
    freeacc_df = extract_expanded_features(
        pd_sids, False, False, "E1.2", append_freeacc=_PHASE1_MODE == "additive"
    )
    if _PHASE1_MODE == "additive":
        freeacc_df, freeacc_all_cols, freeacc_extra_cols = merge_with_baseline(freeacc_df)
    else:
        freeacc_df = extract_expanded_features(
            pd_sids, False, True, "E1.2", append_freeacc=False
        )
        freeacc_feat_cols = [c for c in freeacc_df.columns
                             if c not in ("sid", "updrs3", "obs_subscore", "group")
                             and not c.startswith(("cv_", "obs_"))]
        freeacc_df = freeacc_df.merge(
            fm_agg[["sid"] + fm_cols], on="sid", how="left"
        ).fillna(0.0)
        freeacc_all_cols = freeacc_feat_cols + fm_cols
        freeacc_extra_cols = freeacc_feat_cols

    print(f"\n  [E1.2] +FreeAcc LOOCV...")
    t0 = time.time()
    yt, yp, _ = run_loocv(
        freeacc_df, pd_sids, "updrs3", freeacc_all_cols, k=350,
        progress_label="E1.2 total"
    )
    m_total = full_metrics(yt, yp, "total")
    yt_obs, yp_obs, _ = run_loocv(
        freeacc_df, pd_sids, "obs_subscore", freeacc_all_cols, k=350,
        progress_label="E1.2 obs"
    )
    m_obs = full_metrics(yt_obs, yp_obs, "obs")
    results["experiments"]["E1.2_freeacc"] = {
        **m_total, **m_obs,
        "n_features": len(freeacc_all_cols),
        "n_added_features": len(freeacc_extra_cols),
        "quartiles": severity_quartile_metrics(yt, yp),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    Total: MAE={m_total['total_mae']}, CCC={m_total['total_ccc']}, "
          f"cal_slope={m_total['total_cal_slope']}")

    # ── E1.3: +Euler+FreeAcc ──
    both_df = extract_expanded_features(
        pd_sids, True, False, "E1.3", append_freeacc=_PHASE1_MODE == "additive"
    )
    if _PHASE1_MODE == "additive":
        both_df, both_all_cols, both_extra_cols = merge_with_baseline(both_df)
    else:
        both_df = extract_expanded_features(
            pd_sids, True, True, "E1.3", append_freeacc=False
        )
        both_feat_cols = [c for c in both_df.columns
                          if c not in ("sid", "updrs3", "obs_subscore", "group")
                          and not c.startswith(("cv_", "obs_"))]
        both_df = both_df.merge(
            fm_agg[["sid"] + fm_cols], on="sid", how="left"
        ).fillna(0.0)
        both_all_cols = both_feat_cols + fm_cols
        both_extra_cols = both_feat_cols

    print(f"\n  [E1.3] +Euler+FreeAcc LOOCV...")
    t0 = time.time()
    yt, yp, _ = run_loocv(
        both_df, pd_sids, "updrs3", both_all_cols, k=400,
        progress_label="E1.3 total"
    )
    m_total = full_metrics(yt, yp, "total")
    yt_obs, yp_obs, _ = run_loocv(
        both_df, pd_sids, "obs_subscore", both_all_cols, k=400,
        progress_label="E1.3 obs"
    )
    m_obs = full_metrics(yt_obs, yp_obs, "obs")
    results["experiments"]["E1.3_euler_freeacc"] = {
        **m_total, **m_obs,
        "n_features": len(both_all_cols),
        "n_added_features": len(both_extra_cols),
        "quartiles": severity_quartile_metrics(yt, yp),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    Total: MAE={m_total['total_mae']}, CCC={m_total['total_ccc']}, "
          f"cal_slope={m_total['total_cal_slope']}")
    print(f"    Obs:   MAE={m_obs['obs_mae']}, CCC={m_obs['obs_ccc']}")

    results["feature_mode"] = _PHASE1_MODE
    phase1_name = f"{_OUTPUT_PREFIX}_phase1.json"
    if _PHASE1_MODE == "additive":
        phase1_name = f"{_OUTPUT_PREFIX}_phase1_additive.json"
    save_result(phase1_name, results)
    print("\n  Phase 1 complete.")
    return results


def phase2():
    """Phase 2: Residual modeling on demographics."""
    print("\n" + "=" * 60)
    print(f"PHASE 2: Residual Modeling on Demographics (target={_TARGET_COL})")
    print("=" * 60)

    subjects = parse_clinical()
    pd_sids = sorted([s for s, info in subjects.items()
                       if info.get("group") == "PD"])

    # Load v2 + FM baseline
    v2_full = load_v2_features()
    v2_df = v2_full[v2_full["sid"].isin(pd_sids)].copy().reset_index(drop=True)
    fm_emb, fm_rec_sids = load_fm_embeddings()
    fm_agg = fm_features_for_subjects(fm_emb, fm_rec_sids, pd_sids)
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]
    merged = v2_df.merge(fm_agg[["sid"] + fm_cols], on="sid", how="left").fillna(0.0)

    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3", "group")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_",
                                     "ext_", "obs_"))]
    all_cols = v2_cols + fm_cols
    demo_cols = ["cv_age", "cv_sex", "cv_yrs", "cv_ht", "cv_wt"]

    obs_scores = load_obs_subscores()
    merged["obs_subscore"] = merged["sid"].map(obs_scores)

    results = {"phase": "2_residual_modeling", "experiments": {}}

    tgt = _TARGET_COL

    # ── E2.0: Control (direct prediction, reconfirm) ──
    print(f"\n  [E2.0] Control (direct prediction, v2+FM, target={tgt})...")
    t0 = time.time()
    yt, yp, _ = run_loocv(merged, pd_sids, tgt, all_cols, k=300)
    m = full_metrics(yt, yp, "total")
    results["experiments"]["E2.0_control"] = {
        **m, "quartiles": severity_quartile_metrics(yt, yp),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    # ── E2.1: Residual modeling (v2+FM on residual after demo Ridge) ──
    print(f"\n  [E2.1] Residual: demo Ridge → IMU residual (v2+FM, target={tgt})...")
    t0 = time.time()
    yt, yp, _ = run_loocv(merged, pd_sids, tgt, all_cols, k=300,
                            residual_mode=True, demo_cols=demo_cols)
    m = full_metrics(yt, yp, "total")
    results["experiments"]["E2.1_residual"] = {
        **m,
        "quartiles": severity_quartile_metrics(yt, yp),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    # ── E2.3: Embedded demographics (demo as features, not residual) ──
    print(f"\n  [E2.3] Embedded demographics (v2+FM+demo, target={tgt})...")
    t0 = time.time()
    all_with_demo = all_cols + demo_cols
    yt, yp, _ = run_loocv(merged, pd_sids, tgt, all_with_demo, k=300)
    m = full_metrics(yt, yp, "total")
    results["experiments"]["E2.3_embedded_demo"] = {
        **m, "quartiles": severity_quartile_metrics(yt, yp),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    # ── E2.4: Two-stage stack (demo Ridge + IMU LGB → Ridge meta) ──
    print(f"\n  [E2.4] Two-stage stack (demo + IMU → Ridge meta, target={tgt})...")
    t0 = time.time()
    df = merged[merged["sid"].isin(pd_sids)].copy().reset_index(drop=True)
    y_true_all, y_pred_all = [], []

    for test_sid in pd_sids:
        train_mask = df["sid"] != test_sid
        test_mask = df["sid"] == test_sid
        if test_mask.sum() == 0:
            continue

        yd = df.loc[train_mask, tgt].values
        yt_val = df.loc[test_mask, tgt].values

        # Stage 1a: demographic Ridge
        Xd_demo = df.loc[train_mask, demo_cols].values.astype(np.float32)
        Xt_demo = df.loc[test_mask, demo_cols].values.astype(np.float32)
        demo_m = Ridge(alpha=1.0)
        demo_m.fit(Xd_demo, yd)
        pred_demo_train = demo_m.predict(Xd_demo)
        pred_demo_test = demo_m.predict(Xt_demo)

        # Stage 1b: IMU ensemble
        Xd_imu = df.loc[train_mask, all_cols].values.astype(np.float32)
        Xt_imu = df.loc[test_mask, all_cols].values.astype(np.float32)
        pred_imu_test, _ = run_ensemble(Xd_imu, yd, Xt_imu, None,
                                         all_cols, k=300)
        # For meta-learner training, get OOF IMU predictions
        from sklearn.model_selection import KFold
        oof_imu = np.zeros(len(Xd_imu))
        kf = KFold(n_splits=5, shuffle=True, random_state=42)
        for tr, va in kf.split(Xd_imu):
            p, _ = run_ensemble(Xd_imu[tr], yd[tr], Xd_imu[va], None,
                                all_cols, k=300)
            oof_imu[va] = p

        # Stage 2: Ridge meta-learner on [demo_pred, imu_pred]
        meta_X_train = np.column_stack([pred_demo_train, oof_imu])
        meta_X_test = np.column_stack([pred_demo_test, pred_imu_test])
        meta = Ridge(alpha=1.0)
        meta.fit(meta_X_train, yd)
        pred = clip_pred(meta.predict(meta_X_test))

        y_true_all.append(yt_val[0])
        y_pred_all.append(pred[0])

    m = full_metrics(y_true_all, y_pred_all, "total")
    results["experiments"]["E2.4_twostage"] = {
        **m, "quartiles": severity_quartile_metrics(y_true_all, y_pred_all),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    save_result(f"{_OUTPUT_PREFIX}_phase2.json", results)
    print("\n  Phase 2 complete.")
    return results


def phase4():
    """Phase 4: Post-hoc calibration — re-runs FM LOOCV to get predictions."""
    print("\n" + "=" * 60)
    print(f"PHASE 4: Post-Hoc Calibration (target={_TARGET_COL})")
    print("=" * 60)

    # Re-run LOOCV to get per-subject predictions
    subjects = parse_clinical()
    pd_sids = sorted([s for s, info in subjects.items()
                       if info.get("group") == "PD"])

    v2_full = load_v2_features()
    v2_df = v2_full[v2_full["sid"].isin(pd_sids)].copy().reset_index(drop=True)
    fm_emb, fm_rec_sids = load_fm_embeddings()
    fm_agg = fm_features_for_subjects(fm_emb, fm_rec_sids, pd_sids)
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]
    merged = v2_df.merge(fm_agg[["sid"] + fm_cols], on="sid", how="left").fillna(0.0)
    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3", "group")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_",
                                     "ext_", "obs_"))]
    all_cols = v2_cols + fm_cols

    obs_scores = load_obs_subscores()
    merged["obs_subscore"] = merged["sid"].map(obs_scores)

    tgt = _TARGET_COL
    print(f"  Running FM LOOCV for {len(pd_sids)} PD subjects (target={tgt})...")
    y_true, y_pred, _ = run_loocv(merged, pd_sids, tgt, all_cols, k=300)

    print(f"  Got {len(y_true)} predictions")
    m_base = full_metrics(y_true, y_pred, "base")
    print(f"  Baseline: MAE={m_base['base_mae']}, CCC={m_base['base_ccc']}, "
          f"cal_slope={m_base['base_cal_slope']}")

    results = {"phase": "4_posthoc_calibration", "baseline": m_base, "experiments": {}}

    # ── E4.1: Isotonic regression (nested LOOCV) ──
    print("\n  [E4.1] Isotonic regression...")
    y_cal_iso = np.zeros_like(y_pred)
    for i in range(len(y_true)):
        train_mask = np.ones(len(y_true), dtype=bool)
        train_mask[i] = False
        ir = IsotonicRegression(y_min=0, y_max=_CLIP_MAX, out_of_bounds="clip")
        ir.fit(y_pred[train_mask], y_true[train_mask])
        y_cal_iso[i] = ir.predict([y_pred[i]])[0]
    m = full_metrics(y_true, y_cal_iso, "total")
    results["experiments"]["E4.1_isotonic"] = {
        **m, "quartiles": severity_quartile_metrics(y_true, y_cal_iso),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    # ── E4.2: Platt scaling (linear recalibration in nested LOOCV) ──
    print("\n  [E4.2] Platt scaling (linear)...")
    y_cal_platt = np.zeros_like(y_pred)
    for i in range(len(y_true)):
        train_mask = np.ones(len(y_true), dtype=bool)
        train_mask[i] = False
        # Fit linear: y_true = a * y_pred + b
        a, b = np.polyfit(y_pred[train_mask], y_true[train_mask], 1)
        y_cal_platt[i] = np.clip(a * y_pred[i] + b, 0, _CLIP_MAX)
    m = full_metrics(y_true, y_cal_platt, "total")
    results["experiments"]["E4.2_platt"] = {
        **m, "quartiles": severity_quartile_metrics(y_true, y_cal_platt),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    # ── E4.3: Linear recalibration (global) ──
    print("\n  [E4.3] Linear recalibration (global slope/intercept)...")
    cal_s, cal_i = calibration_slope_intercept(y_true, y_pred)
    # Invert: y_cal = (y_pred - cal_i) / cal_s
    y_cal_linear = np.clip((y_pred - cal_i) / max(cal_s, 0.01), 0, _CLIP_MAX)
    m = full_metrics(y_true, y_cal_linear, "total")
    results["experiments"]["E4.3_linear"] = {
        **m, "quartiles": severity_quartile_metrics(y_true, y_cal_linear),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    # ── E4.4: Polynomial calibration (quadratic fit, nested LOOCV) ──
    print("\n  [E4.4] Polynomial calibration (quadratic)...")
    y_cal_poly = np.zeros_like(y_pred)
    for i in range(len(y_true)):
        train_mask = np.ones(len(y_true), dtype=bool)
        train_mask[i] = False
        # Fit quadratic: y_true = a*y_pred^2 + b*y_pred + c
        coeffs = np.polyfit(y_pred[train_mask], y_true[train_mask], 2)
        y_cal_poly[i] = np.clip(np.polyval(coeffs, y_pred[i]), 0, _CLIP_MAX)
    m = full_metrics(y_true, y_cal_poly, "total")
    results["experiments"]["E4.4_polynomial"] = {
        **m, "quartiles": severity_quartile_metrics(y_true, y_cal_poly),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    save_result(f"{_OUTPUT_PREFIX}_phase4.json", results)
    print("\n  Phase 4 complete.")
    return results


def phase5():
    """Phase 5: Training modifications (severity-weighted loss)."""
    print("\n" + "=" * 60)
    print(f"PHASE 5: Training Modifications (target={_TARGET_COL})")
    print("=" * 60)

    subjects = parse_clinical()
    pd_sids = sorted([s for s, info in subjects.items()
                       if info.get("group") == "PD"])

    v2_full = load_v2_features()
    v2_df = v2_full[v2_full["sid"].isin(pd_sids)].copy().reset_index(drop=True)
    fm_emb, fm_rec_sids = load_fm_embeddings()
    fm_agg = fm_features_for_subjects(fm_emb, fm_rec_sids, pd_sids)
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]
    merged = v2_df.merge(fm_agg[["sid"] + fm_cols], on="sid", how="left").fillna(0.0)

    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3", "group")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_",
                                     "ext_", "obs_"))]
    all_cols = v2_cols + fm_cols

    obs_scores = load_obs_subscores()
    merged["obs_subscore"] = merged["sid"].map(obs_scores)
    tgt = _TARGET_COL

    results = {"phase": "5_training_mods", "target": tgt, "experiments": {}}

    # ── E5.1: Severity-weighted MAE ──
    print(f"\n  [E5.1] Severity-weighted MAE (target={tgt})...")
    def severity_weights(y):
        """Weight = 1 + alpha * |y - mean| / std, upweighting extremes."""
        mean_y, std_y = np.mean(y), max(np.std(y), 1.0)
        return 1.0 + 1.5 * np.abs(y - mean_y) / std_y

    t0 = time.time()
    yt, yp, _ = run_loocv(merged, pd_sids, tgt, all_cols, k=300,
                            sample_weight_fn=severity_weights)
    m = full_metrics(yt, yp, "total")
    results["experiments"]["E5.1_severity_weighted"] = {
        **m, "quartiles": severity_quartile_metrics(yt, yp),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    # ── E5.2: Inverse-frequency weighting ──
    print(f"\n  [E5.2] Inverse-frequency weighting (target={tgt})...")
    def inv_freq_weights(y):
        """Weight ∝ 1/count_in_bin."""
        bins = pd.qcut(y, q=4, labels=False, duplicates="drop")
        counts = np.bincount(bins, minlength=4)
        w = 1.0 / np.maximum(counts[bins], 1)
        return w / w.mean()  # normalize

    t0 = time.time()
    yt, yp, _ = run_loocv(merged, pd_sids, tgt, all_cols, k=300,
                            sample_weight_fn=inv_freq_weights)
    m = full_metrics(yt, yp, "total")
    results["experiments"]["E5.2_inv_freq"] = {
        **m, "quartiles": severity_quartile_metrics(yt, yp),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    # ── E5.4: Huber loss ──
    print(f"\n  [E5.4] Huber loss (target={tgt})...")
    t0 = time.time()
    yt, yp, _ = run_loocv(merged, pd_sids, tgt, all_cols, k=300,
                            objective="huber")
    m = full_metrics(yt, yp, "total")
    results["experiments"]["E5.4_huber"] = {
        **m, "quartiles": severity_quartile_metrics(yt, yp),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    save_result(f"{_OUTPUT_PREFIX}_phase5.json", results)
    print("\n  Phase 5 complete.")
    return results


def phase6():
    """Phase 6: Grand combination — residual + severity-weighted + best features."""
    print("\n" + "=" * 60)
    print(f"PHASE 6: Grand Combination (target={_TARGET_COL})")
    print("=" * 60)

    subjects = parse_clinical()
    pd_sids = sorted([s for s, info in subjects.items()
                       if info.get("group") == "PD"])

    v2_full = load_v2_features()
    v2_df = v2_full[v2_full["sid"].isin(pd_sids)].copy().reset_index(drop=True)
    fm_emb, fm_rec_sids = load_fm_embeddings()
    fm_agg = fm_features_for_subjects(fm_emb, fm_rec_sids, pd_sids)
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]
    merged = v2_df.merge(fm_agg[["sid"] + fm_cols], on="sid", how="left").fillna(0.0)

    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3", "group")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_",
                                     "ext_", "obs_"))]
    all_cols = v2_cols + fm_cols
    demo_cols = ["cv_age", "cv_sex", "cv_yrs", "cv_ht", "cv_wt"]

    obs_scores = load_obs_subscores()
    merged["obs_subscore"] = merged["sid"].map(obs_scores)

    tgt = _TARGET_COL
    results = {"phase": "6_grand_combination", "target": tgt, "experiments": {}}

    def severity_weights(y):
        mean_y, std_y = np.mean(y), max(np.std(y), 1.0)
        return 1.0 + 1.5 * np.abs(y - mean_y) / std_y

    # ── E6.1: Residual + severity-weighted ──
    print(f"\n  [E6.1] Residual + severity-weighted (target={tgt})...")
    t0 = time.time()
    yt, yp, _ = run_loocv(merged, pd_sids, tgt, all_cols, k=300,
                            residual_mode=True, demo_cols=demo_cols,
                            sample_weight_fn=severity_weights)
    m = full_metrics(yt, yp, "total")
    results["experiments"]["E6.1_residual_weighted"] = {
        **m,
        "quartiles": severity_quartile_metrics(yt, yp),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    # ── E6.2: Residual + stack ──
    print(f"\n  [E6.2] Residual + LGB+XGB stack (target={tgt})...")
    t0 = time.time()
    yt, yp, _ = run_loocv(merged, pd_sids, tgt, all_cols, k=300,
                            residual_mode=True, demo_cols=demo_cols,
                            use_stack=True)
    m = full_metrics(yt, yp, "total")
    results["experiments"]["E6.2_residual_stack"] = {
        **m, "quartiles": severity_quartile_metrics(yt, yp),
        "time_s": round(time.time() - t0, 1),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    # ── E6.3: Residual + severity-weighted + Isotonic post-hoc ──
    print(f"\n  [E6.3] Residual + weighted + Isotonic post-hoc (target={tgt})...")
    yt_61, yp_61, _ = run_loocv(merged, pd_sids, tgt, all_cols, k=300,
                                  residual_mode=True, demo_cols=demo_cols,
                                  sample_weight_fn=severity_weights)
    y_cal_iso = np.zeros_like(yp_61)
    for i in range(len(yt_61)):
        train_mask = np.ones(len(yt_61), dtype=bool)
        train_mask[i] = False
        ir = IsotonicRegression(y_min=0, y_max=_CLIP_MAX, out_of_bounds="clip")
        ir.fit(yp_61[train_mask], yt_61[train_mask])
        y_cal_iso[i] = ir.predict([yp_61[i]])[0]
    m = full_metrics(yt_61, y_cal_iso, "total")
    results["experiments"]["E6.3_residual_weighted_isotonic"] = {
        **m, "quartiles": severity_quartile_metrics(yt_61, y_cal_iso),
    }
    print(f"    MAE={m['total_mae']}, CCC={m['total_ccc']}, "
          f"cal_slope={m['total_cal_slope']}")

    save_result(f"{_OUTPUT_PREFIX}_phase6.json", results)
    print("\n  Phase 6 complete.")
    return results


def phase8():
    """Phase 8: FM normalization + task-aware pooling."""
    print("\n" + "=" * 60)
    print("PHASE 8: FM Normalization + Task-Aware Pooling")
    print("=" * 60)

    subjects = parse_clinical()
    pd_sids = sorted([s for s, info in subjects.items() if info.get("group") == "PD"])
    v2_full = load_v2_features()
    v2_df = v2_full[v2_full["sid"].isin(pd_sids)].copy().reset_index(drop=True)
    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3", "group")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_",
                                     "ext_", "obs_"))]
    obs_scores = load_obs_subscores()
    v2_df["obs_subscore"] = v2_df["sid"].map(obs_scores)

    rec_array, rec_sids, rec_tasks = load_recording_cache()
    cached_embeddings, _ = load_fm_embeddings()
    recording_embeddings = extract_fm_embeddings_custom(
        rec_array,
        cache_name="fm_embeddings_recording_norm.npz",
        norm_mode="recording",
    )

    configs = [
        ("E8.0_cached_mean", cached_embeddings, "subject_mean", 300),
        ("E8.1_recording_mean", recording_embeddings, "subject_mean", 300),
        ("E8.2_recording_task_mean", recording_embeddings, "task_mean", 350),
        ("E8.3_recording_task_mean_var", recording_embeddings, "task_mean_var", 400),
    ]

    results = {"phase": "8_task_aware_fm", "experiments": {}}
    for exp_name, embeddings, pooling_mode, k in configs:
        print(f"\n  [{exp_name}] pooling={pooling_mode}, k={k}")
        fm_agg = fm_features_task_aware(embeddings, rec_sids, rec_tasks, pd_sids, pooling_mode)
        fm_cols = [c for c in fm_agg.columns if c != "sid"]
        merged = v2_df.merge(fm_agg, on="sid", how="left").fillna(0.0)
        all_cols = v2_cols + fm_cols

        t0 = time.time()
        yt, yp, _ = run_loocv(
            merged, pd_sids, "updrs3", all_cols, k=k,
            progress_label=f"{exp_name} total"
        )
        m_total = full_metrics(yt, yp, "total")
        yt_obs, yp_obs, _ = run_loocv(
            merged, pd_sids, "obs_subscore", all_cols, k=k,
            progress_label=f"{exp_name} obs"
        )
        m_obs = full_metrics(yt_obs, yp_obs, "obs")
        results["experiments"][exp_name] = {
            **m_total,
            **m_obs,
            "pooling_mode": pooling_mode,
            "n_fm_features": len(fm_cols),
            "n_total_features": len(all_cols),
            "quartiles": severity_quartile_metrics(yt, yp),
            "time_s": round(time.time() - t0, 1),
        }
        print(f"    Total: MAE={m_total['total_mae']}, CCC={m_total['total_ccc']}")
        print(f"    Obs:   MAE={m_obs['obs_mae']}, CCC={m_obs['obs_ccc']}")

    save_result(f"{_OUTPUT_PREFIX}_phase8.json", results)
    print("\n  Phase 8 complete.")
    return results


# ─── Utilities ────────────────────────────────────────────────────────────────

def save_result(filename, data):
    """Save result to JSON."""
    path = RESULTS_DIR / filename
    path.write_text(json.dumps(data, indent=2, default=str))
    print(f"  Saved: {path}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global _TARGET_COL, _CLIP_MAX, _OUTPUT_PREFIX, _PHASE1_MODE

    parser = argparse.ArgumentParser(description="Calibration-fix ablation study")
    parser.add_argument("--phase", type=str, required=True,
                        help="Phase(s) to run: 0,1,2,4,5,6,8 or 'all'")
    parser.add_argument("--target", type=str, default="total",
                        choices=["total", "obs"],
                        help="Target: 'total' (updrs3, 0-132) or 'obs' (obs_subscore, 0-24)")
    parser.add_argument("--phase1-mode", type=str, default="replacement",
                        choices=["replacement", "additive"],
                        help="Phase 1 feature-expansion mode")
    args = parser.parse_args()
    _PHASE1_MODE = args.phase1_mode

    if args.target == "obs":
        _TARGET_COL = "obs_subscore"
        _CLIP_MAX = 24
        _OUTPUT_PREFIX = "calibration_obs_ablation"
        print(f"\n*** TARGET: obs_subscore (range 0-24) ***\n")
    else:
        _TARGET_COL = "updrs3"
        _CLIP_MAX = 132
        _OUTPUT_PREFIX = "calibration_ablation"
        print(f"\n*** TARGET: updrs3 (range 0-132) ***\n")

    phases_to_run = []
    if args.phase == "all":
        phases_to_run = [0, 1, 2, 4, 5, 6, 8]
    else:
        phases_to_run = [int(p) for p in args.phase.split(",")]

    t_start = time.time()

    for p in phases_to_run:
        if p == 0:
            phase0()
        elif p == 1:
            phase1()
        elif p == 2:
            phase2()
        elif p == 4:
            phase4()
        elif p == 5:
            phase5()
        elif p == 6:
            phase6()
        elif p == 8:
            phase8()
        else:
            print(f"Phase {p} not implemented yet")

    total = time.time() - t_start
    print(f"\n{'=' * 60}")
    print(f"All requested phases complete in {total/60:.1f} minutes")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
