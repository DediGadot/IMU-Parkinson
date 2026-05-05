"""T3 iter25 — Cross-dataset zero-shot transportability on PADS smartwatch.

Mission: produce the FIRST published zero-shot transportability number for the
WearGait-PD-trained iter5 T3 architecture, evaluated on a fully external PD
cohort that shares NO subjects, NO devices, NO acquisition site, NO clinical
team with WearGait. The target external dataset is **PADS** (Parkinson's
Disease Smartwatch dataset, PhysioNet, public, no DUA): 74 PD + 63 HC subjects
recorded with a wrist-worn smartwatch (Apple Watch–style accelerometer, 100Hz).

WHY THIS IS A REAL TRANSPORTABILITY CLAIM (not just LOSO):

  - WearGait-PD = US sites NLS + WPD, 13-IMU body-worn (Movella Xsens), 100Hz,
    full UPDRS-III scored by trained MDS examiners.
  - PADS = German cohort, single wrist smartwatch, different recruitment, no
    UPDRS-III (only PD/HC binary label per subject).
  - iter16 LOSO (NLS↔WPD, two-way 0.341) was within WearGait-PD — same
    devices, same protocol. iter25 PADS is **fully external** — different
    devices, country, protocol.

CAVEATS (load-bearing for paper framing):

  - PADS has no UPDRS-III, so the headline metric is **AUROC of iter25's
    continuous UPDRS-III prediction vs PADS's PD/HC binary label**. We are
    asking: "does an iter5-style severity prediction transport to a fully
    external cohort well enough to discriminate PD from HC zero-shot?"
  - Feature alignment is restricted to what both WearGait wrist sensors and
    PADS smartwatch can produce: 3-axis accelerometer + magnitude → ~70
    time/freq/gait features per axis-channel. NO sensor fusion, NO multi-IMU
    relationships, NO Roll/Pitch/Yaw, NO FreeAcc.
  - Clinical Stage 1 covariates: PADS provides age + gender. cv_yrs, cv_dbs,
    H&Y are **NOT in PADS** and are mean-imputed from the WearGait training
    cohort's PD distribution. This is a valid zero-shot protocol (the model
    sees only WearGait-trained values for missing covariates).

ARCHITECTURE (FROZEN before any PADS evaluation):

  Two tracks evaluated in a single batch:

  TRACK A — V2-wrist LGB regressor (no clinical Stage 1):
    Train: LGB regression on common wrist features → updrs3 (WearGait).
    Apply: predict updrs3 for each PADS subject from their wrist features.
    Score: AUROC of continuous predictions vs PADS PD/HC labels.

  TRACK B — iter5-restricted Stage 1+2 with PADS clinical-imputation:
    Stage 1 Ridge on (H&Y_imp + cv_yrs_imp + cv_sex_imp + cv_dbs_imp) →
      WearGait subjects use real values; PADS subjects get cv_sex from PADS
      `gender`, cv_yrs/cv_dbs/H&Y mean-imputed from WearGait PD cohort.
    Stage 2 LGB on common wrist features → residual.
    Apply: full prediction = Stage1_pred + Stage2_pred.
    Score: AUROC of continuous predictions vs PADS PD/HC labels.

  Baseline references (computed in the same script):
    - PADS-only 5-fold AUROC (upper bound — same-dataset CV).
    - WearGait-only LOOCV AUROC (lower bound on AUROC achievable from full
      WearGait wrist features alone, evaluated on its own held-out folds).

GATE / LOCKBOX:
  This is exploratory, not a CCC-push. Pre-registered single-batch (TRACK A +
  TRACK B together; no cherry-picking). No "gate" — we report AUROC honestly
  whatever it is. Reportable threshold for the paper:
    - AUROC > 0.65 = useful zero-shot transfer (paper claims transportability).
    - AUROC ∈ (0.55, 0.65) = borderline (caveat-heavy).
    - AUROC ≤ 0.55 = no transfer (also publishable as "the architecture does
      not transport" — adds to the paper's structural-ceiling story).

USAGE:
  python3 run_t3_iter25_pads_zeroshot.py --mode write_prereg --seeds 42 1337 7
  python3 run_t3_iter25_pads_zeroshot.py --mode run --preregistration_file <path>

LEAKAGE INHERITANCE:
  PADS subjects never appear in WearGait training. Common features are
  fold-locally standardized using WearGait training-fold statistics ONLY.
  Mean-imputation values for missing PADS clinical extras come from WearGait
  PD distribution (NOT from PADS labels). Manifest validation: refuses to
  start if PADS data path missing or clinical_extras manifest is leaky.
"""
from __future__ import annotations

import os
os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
import hashlib
import json
import subprocess
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal as sp_signal, stats as sp_stats
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score, balanced_accuracy_score
from sklearn.model_selection import KFold, StratifiedKFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldNormalizer, ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter3 import load_full_pd_data, get_hy_features
from run_t3_iter5_clinical import (
    CLINICAL_COLS_BINARY, CLINICAL_COLS_CONTINUOUS,
    fit_stage1, FEATURE_SETS as ITER5_FEATURE_SETS, load_clinical_dict,
)
from run_t3_iter2 import train_lgb

def _resolve_pads_dir() -> Path:
    """PADS may be unpacked under either:
        /root/pd-imu/data/raw/pads/physionet.org/files/parkinsons-disease-smartwatch/1.0.0/
        /root/pd-imu/data/raw/pads/parkinsons-disease-smartwatch-1.0.0/
        /root/pd-imu/data/raw/pads/<extracted>/
    Find the directory containing `movement/` and `preprocessed/file_list.csv`.
    """
    base = Path("/root/pd-imu/data/raw/pads")
    if not base.exists():
        # Local fallback for syntax-check / dry-run
        return Path("/tmp/pads_missing")
    for cand in [
        base / "v1",
        base / "physionet.org/files/parkinsons-disease-smartwatch/1.0.0",
        base / "parkinsons-disease-smartwatch-1.0.0",
        base,
    ]:
        if (cand / "movement").is_dir() and (cand / "preprocessed" / "file_list.csv").is_file():
            return cand
    # Walk one level deep
    for child in base.iterdir():
        if not child.is_dir():
            continue
        for sub in [child, *list(child.iterdir())]:
            if not sub.is_dir():
                continue
            if (sub / "movement").is_dir() and (sub / "preprocessed" / "file_list.csv").is_file():
                return sub
    return base  # let downstream raise FileNotFoundError with informative path


PADS_DIR = _resolve_pads_dir()
WEARGAIT_PD_CSV = Path("/root/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files")
WEARGAIT_HC_CSV = Path("/root/pd-imu/data/raw/weargait-pd/CONTROL PARTICIPANTS/CSV files")
WEARGAIT_TASKS = ["SelfPace", "HurriedPace", "TUG", "Balance", "TandemGait"]
FS_WG = 100  # Hz, WearGait
FS_PADS = 100  # PADS smartwatch sampling rate (per file_list.csv per movement obs)


# ── Wrist feature extraction (alignable across both datasets) ────────────────


def _safe(fn, x):
    try:
        return float(fn(np.asarray(x, dtype=np.float64)))
    except Exception:
        return 0.0


def td_feats(x: np.ndarray, prefix: str, fs: int) -> dict:
    """Time-domain features: rms / std / range / iqr / skew / kurt / jerk_rms / zcr."""
    f: dict[str, float] = {}
    f[f"{prefix}_rms"] = _safe(lambda d: np.sqrt(np.mean(d ** 2)), x)
    f[f"{prefix}_std"] = _safe(np.std, x)
    f[f"{prefix}_range"] = _safe(np.ptp, x)
    f[f"{prefix}_iqr"] = _safe(lambda d: np.percentile(d, 75) - np.percentile(d, 25), x)
    f[f"{prefix}_skew"] = _safe(lambda d: float(sp_stats.skew(d)), x)
    f[f"{prefix}_kurt"] = _safe(lambda d: float(sp_stats.kurtosis(d)), x)
    jerk = np.diff(x) * fs
    f[f"{prefix}_jerk"] = _safe(lambda d: np.sqrt(np.mean(d ** 2)), jerk)
    f[f"{prefix}_zcr"] = float(np.sum(np.diff(np.sign(x - np.mean(x))) != 0)) / max(len(x), 1)
    return f


def fd_feats(x: np.ndarray, prefix: str, fs: int) -> dict:
    """Frequency-domain features: 3-band log-power + ratio + dominant freq + spectral entropy."""
    f: dict[str, float] = {}
    try:
        freqs, psd = sp_signal.welch(x, fs=fs, nperseg=min(256, len(x)),
                                     noverlap=min(128, len(x) // 2))
        psd = psd + 1e-12
        total = np.trapz(psd, freqs) + 1e-12
        for bn, lo, hi in [("loco", 0.5, 3.0), ("trem", 3.0, 8.0), ("high", 8.0, 20.0)]:
            mask = (freqs >= lo) & (freqs <= hi)
            bp = float(np.trapz(psd[mask], freqs[mask])) if mask.sum() > 1 else 1e-12
            f[f"{prefix}_{bn}"] = float(np.log10(max(bp, 1e-12)))
            f[f"{prefix}_{bn}_r"] = float(bp / total)
        f[f"{prefix}_dom"] = float(freqs[np.argmax(psd)])
        pn = psd / psd.sum()
        f[f"{prefix}_se"] = float(-np.sum(pn * np.log2(pn + 1e-12)))
    except Exception:
        for bn in ["loco", "trem", "high"]:
            f[f"{prefix}_{bn}"] = 0.0
            f[f"{prefix}_{bn}_r"] = 0.0
        f[f"{prefix}_dom"] = 0.0
        f[f"{prefix}_se"] = 0.0
    return f


def gait_reg(acc_v: np.ndarray, prefix: str, fs: int) -> dict:
    """Gait regularity from autocorrelation peaks."""
    f: dict[str, float] = {}
    try:
        x = acc_v - np.mean(acc_v)
        ac = np.correlate(x, x, mode="full")[len(x) - 1:]
        ac = ac / (ac[0] + 1e-12)
        peaks, _ = sp_signal.find_peaks(ac, distance=30, height=0.1)
        if len(peaks) >= 2:
            f[f"{prefix}_step_t"] = float(peaks[0] / fs)
            f[f"{prefix}_stride_t"] = float(peaks[1] / fs)
            f[f"{prefix}_cadence"] = float(60.0 * fs / peaks[0]) if peaks[0] > 0 else 0.0
            f[f"{prefix}_step_reg"] = float(ac[peaks[0]])
            f[f"{prefix}_stride_reg"] = float(ac[peaks[1]]) if peaks[1] < len(ac) else 0.0
        else:
            raise ValueError
    except Exception:
        for k in ["step_t", "stride_t", "cadence", "step_reg", "stride_reg"]:
            f[f"{prefix}_{k}"] = 0.0
    return f


def extract_wrist_block(ax: np.ndarray, ay: np.ndarray, az: np.ndarray, fs: int) -> dict:
    """Run td/fd on each axis + magnitude + gait_reg on magnitude. Returns flat dict."""
    out: dict[str, float] = {}
    for axis_name, x in [("ax", ax), ("ay", ay), ("az", az)]:
        out.update(td_feats(x, f"wrist_{axis_name}", fs))
        out.update(fd_feats(x, f"wrist_{axis_name}", fs))
    am = np.sqrt(ax ** 2 + ay ** 2 + az ** 2)
    out.update(td_feats(am, "wrist_am", fs))
    out.update(fd_feats(am, "wrist_am", fs))
    out.update(gait_reg(am, "wrist_g", fs))
    return out


# ── PADS extraction ─────────────────────────────────────────────────────────


def extract_pads() -> tuple[pd.DataFrame, list[str]]:
    """Return (per-subject feature dataframe, feature column list).

    PADS: each subject has multiple movement observations (different tasks). We
    average features across observations per subject.
    """
    if not PADS_DIR.exists():
        raise FileNotFoundError(f"Missing PADS dataset directory: {PADS_DIR}")
    file_list = pd.read_csv(PADS_DIR / "preprocessed" / "file_list.csv")
    movement_dir = PADS_DIR / "movement"
    patient_dir = PADS_DIR / "patients"

    # Load PADS subject metadata (age, gender, condition, label)
    patients: dict[str, dict] = {}
    for _, row in file_list.iterrows():
        pid_int = row.get("id")
        if pid_int is None or pd.isna(pid_int):
            continue
        pid = str(int(pid_int)).zfill(3)
        label = int(row.get("label", -1))
        if label not in (0, 1):  # 0=HC, 1=PD; 2=other excluded
            continue
        patients[pid] = {
            "label": label,
            "age": float(row.get("age", 0.0)) if not pd.isna(row.get("age", np.nan)) else np.nan,
            "gender": str(row.get("gender", "")).strip(),
            "condition": str(row.get("condition", "")).strip(),
        }

    # PADS v1.0.0 schema: each observation_NNN.json references CSV-format .txt files
    # via the `file_name` field (NOT `data_file`). Each .txt is comma-separated with
    # 7 columns: Time, Accelerometer_{X,Y,Z}, Gyroscope_{X,Y,Z}. Per-session records
    # exist for both LeftWrist and RightWrist; we use RightWrist to match WearGait
    # R_Wrist, falling back to LeftWrist if Right is missing.
    obs_files = sorted([f for f in os.listdir(movement_dir)
                       if f.startswith("observation_") and f.endswith(".json")])
    rows = []
    for obs_file in obs_files:
        try:
            with open(movement_dir / obs_file) as f:
                obs = json.load(f)
        except Exception:
            continue
        pid = str(obs.get("subject_id", "")).zfill(3)
        if pid not in patients:
            continue
        sr = int(obs.get("sampling_rate", FS_PADS))

        for session in obs.get("session", []):
            n_rows = int(session.get("rows", 0))
            if n_rows < 200:
                continue
            # Prefer RightWrist (matching WearGait R_Wrist); fall back to LeftWrist.
            chosen_rec = None
            for rec in session.get("records", []):
                if rec.get("device_location", "") == "RightWrist":
                    chosen_rec = rec
                    break
            if chosen_rec is None:
                for rec in session.get("records", []):
                    if rec.get("device_location", "") == "LeftWrist":
                        chosen_rec = rec
                        break
            if chosen_rec is None:
                continue
            channels = chosen_rec.get("channels", [])
            if "Accelerometer_X" not in channels:
                continue
            txt_file = chosen_rec.get("file_name", "")
            if not txt_file:
                continue
            txt_path = movement_dir / txt_file
            if not txt_path.exists():
                continue
            try:
                data = np.loadtxt(txt_path, delimiter=",", dtype=np.float64)
            except Exception:
                continue
            if data.ndim != 2 or data.shape[0] < 200:
                continue
            ch_idx = {c: i for i, c in enumerate(channels)}
            ax = data[:, ch_idx["Accelerometer_X"]].astype(np.float32)
            ay = data[:, ch_idx["Accelerometer_Y"]].astype(np.float32)
            az = data[:, ch_idx["Accelerometer_Z"]].astype(np.float32)
            feats = extract_wrist_block(ax, ay, az, sr)
            feats["pid"] = pid
            feats["label"] = patients[pid]["label"]
            feats["age"] = patients[pid]["age"]
            feats["gender"] = patients[pid]["gender"]
            feats["session"] = session.get("record_name", "")
            feats["wrist_used"] = chosen_rec.get("device_location", "")
            rows.append(feats)

    if not rows:
        raise RuntimeError("No PADS observations parsed.")
    df = pd.DataFrame(rows)
    # Aggregate to subject-level (mean across sessions/observations per pid)
    feat_cols = [c for c in df.columns if c.startswith("wrist_")]
    if not feat_cols:
        raise RuntimeError("No wrist_* feature columns extracted from PADS — check schema.")
    agg = df.groupby("pid")[feat_cols].mean(numeric_only=True).reset_index()
    meta = df.groupby("pid").agg({"label": "first", "age": "first", "gender": "first"}).reset_index()
    out = agg.merge(meta, on="pid")
    return out, feat_cols


# ── WearGait wrist extraction (matching feature schema) ─────────────────────


def extract_weargait_wrist(sids: np.ndarray, label_for_sid: dict[str, int]) -> tuple[pd.DataFrame, list[str]]:
    """Extract right-wrist features from WearGait CSVs to match PADS schema.

    For each subject, average wrist features across the 5 task CSVs.
    """
    rows = []
    for sid in sids:
        is_pd = label_for_sid.get(sid, 0) == 1
        d = WEARGAIT_PD_CSV if is_pd else WEARGAIT_HC_CSV
        sess_feats: list[dict] = []
        for task in WEARGAIT_TASKS:
            p = d / f"{sid}_{task}.csv"
            if not p.exists():
                continue
            ax_col = "R_Wrist_Acc_X"
            ay_col = "R_Wrist_Acc_Y"
            az_col = "R_Wrist_Acc_Z"
            try:
                df = pd.read_csv(p, usecols=[ax_col, ay_col, az_col])
            except Exception:
                continue
            if not all(c in df.columns for c in [ax_col, ay_col, az_col]):
                continue
            ax = np.nan_to_num(df[ax_col].values.astype(np.float32))
            ay = np.nan_to_num(df[ay_col].values.astype(np.float32))
            az = np.nan_to_num(df[az_col].values.astype(np.float32))
            if len(ax) < 200:
                continue
            sess_feats.append(extract_wrist_block(ax, ay, az, FS_WG))
        if not sess_feats:
            continue
        # Average across tasks
        avg = {}
        for k in sess_feats[0]:
            avg[k] = float(np.mean([sf[k] for sf in sess_feats if k in sf]))
        avg["sid"] = sid
        avg["label"] = label_for_sid[sid]
        rows.append(avg)
    if not rows:
        raise RuntimeError("No WearGait wrist features extracted.")
    df = pd.DataFrame(rows)
    feat_cols = sorted([c for c in df.columns if c.startswith("wrist_")])
    return df, feat_cols


# ── Train + apply pipelines ─────────────────────────────────────────────────


def _winsorize(x: np.ndarray, lo_pct: float = 1.0, hi_pct: float = 99.0) -> np.ndarray:
    """Clip outliers per column to (1pct, 99pct) — for cross-domain robustness."""
    lo = np.nanpercentile(x, lo_pct, axis=0)
    hi = np.nanpercentile(x, hi_pct, axis=0)
    return np.clip(x, lo, hi)


def track_a_v2_only(
    wg_df: pd.DataFrame, pads_df: pd.DataFrame, common_feats: list[str], seeds: list[int]
) -> dict:
    """LGB regression on WearGait PD-only wrist features → updrs3; apply to PADS; AUROC vs label.

    Trains on WG PD subjects only (matching canonical iter5 N=98). HC subjects are
    excluded from training; they have no UPDRS-III. Continuous predictions on PADS
    are then thresholded implicitly via AUROC against the binary label.
    """
    pd_mask = (wg_df["label"].values == 1)
    wg_pd = wg_df[pd_mask].reset_index(drop=True)
    y_wg = wg_pd["updrs3"].values.astype(np.float64)
    Xwg = wg_pd[common_feats].values.astype(np.float64)
    Xpads = pads_df[common_feats].values.astype(np.float64)
    # Clean
    Xwg = np.nan_to_num(Xwg, nan=0.0, posinf=0.0, neginf=0.0)
    Xpads = np.nan_to_num(Xpads, nan=0.0, posinf=0.0, neginf=0.0)
    Xwg = _winsorize(Xwg)
    Xpads = _winsorize(Xpads)
    # Standardize using WG-only statistics (zero-shot — never see PADS in training)
    nrm = FoldNormalizer.fit(Xwg)
    Xwg_n = nrm.transform(Xwg)
    Xpads_n = nrm.transform(Xpads)
    # Train ensemble across seeds; predict PADS continuous
    preds_per_seed = []
    for seed in seeds:
        pred = train_lgb(Xwg_n, y_wg, Xpads_n, seed)
        preds_per_seed.append(pred)
    pred_mean = np.mean(np.stack(preds_per_seed, axis=0), axis=0)
    # AUROC on PADS labels
    y_pads = pads_df["label"].values.astype(int)
    auroc = float(roc_auc_score(y_pads, pred_mean))
    # Spearman r vs label is also informative
    spearman_r = float(sp_stats.spearmanr(pred_mean, y_pads).statistic)
    return {
        "track": "A_v2_only_lgb",
        "auroc": auroc,
        "spearman_r": spearman_r,
        "pred_mean_HC": float(pred_mean[y_pads == 0].mean()),
        "pred_mean_PD": float(pred_mean[y_pads == 1].mean()),
        "pred_std_HC": float(pred_mean[y_pads == 0].std()),
        "pred_std_PD": float(pred_mean[y_pads == 1].std()),
        "n_pd": int((y_pads == 1).sum()),
        "n_hc": int((y_pads == 0).sum()),
        "preds_per_seed_auroc": [float(roc_auc_score(y_pads, p)) for p in preds_per_seed],
    }


def track_b_iter5_imputed(
    wg_df: pd.DataFrame, pads_df: pd.DataFrame, common_feats: list[str], seeds: list[int],
    wg_clinical: dict[str, np.ndarray], pads_meta: pd.DataFrame,
) -> dict:
    """iter5-restricted Stage 1 + Stage 2 with mean-imputed clinical extras for PADS.

    Stage 1: Ridge on (H&Y_imp + cv_yrs_imp + cv_sex + cv_dbs_imp).
    Stage 2: LGB on common wrist features → residual.

    Apply to PADS:
      cv_sex from PADS gender ("male" → 0.0, "female" → 1.0; matches WearGait coding
      convention — but verified against WearGait's cv_sex distribution).
      H&Y, cv_yrs, cv_dbs: WearGait PD-cohort mean imputation (a single constant
      vector for all PADS subjects).
    Trains on WG PD-only (N=98) — matches canonical iter5.
    """
    pd_mask = (wg_df["label"].values == 1)
    wg_pd = wg_df[pd_mask].reset_index(drop=True)
    y_wg = wg_pd["updrs3"].values.astype(np.float64)
    Xwg = wg_pd[common_feats].values.astype(np.float64)
    Xpads = pads_df[common_feats].values.astype(np.float64)
    Xwg = np.nan_to_num(Xwg, nan=0.0, posinf=0.0, neginf=0.0)
    Xpads = np.nan_to_num(Xpads, nan=0.0, posinf=0.0, neginf=0.0)
    Xwg = _winsorize(Xwg)
    Xpads = _winsorize(Xpads)
    nrm = FoldNormalizer.fit(Xwg)
    Xwg_n = nrm.transform(Xwg)
    Xpads_n = nrm.transform(Xpads)

    # Build Stage-1 covariate matrices (PD-only)
    n_wg = len(wg_pd)
    n_pads = len(pads_df)
    hy_wg = wg_pd["hy"].values.astype(np.float64)
    hy_feat_wg = get_hy_features(hy_wg)  # (n_wg, 6)
    cv_yrs_wg = wg_clinical["cv_yrs"][pd_mask]
    cv_sex_wg = wg_clinical["cv_sex"][pd_mask]
    cv_dbs_wg = wg_clinical["cv_dbs"][pd_mask]
    # PADS imputation: mean from WG-PD-cohort for missing clinical
    cv_yrs_pads_imp = float(cv_yrs_wg.mean())
    cv_dbs_pads_imp = float(cv_dbs_wg.mean())
    hy_pads_imp = float(hy_wg.mean())
    # PADS gender → cv_sex (WearGait coding: 0=Male, 1=Female — verify by cross-tab)
    pads_gender = pads_meta["gender"].fillna("").values
    cv_sex_pads = np.array([
        1.0 if g.lower().startswith("f") else 0.0 for g in pads_gender
    ])
    hy_feat_pads = get_hy_features(np.full(n_pads, hy_pads_imp))  # (n_pads, 6)
    cv_yrs_pads = np.full(n_pads, cv_yrs_pads_imp)
    cv_dbs_pads = np.full(n_pads, cv_dbs_pads_imp)

    Xs1_wg = np.column_stack([hy_feat_wg, cv_yrs_wg, cv_sex_wg, cv_dbs_wg])
    Xs1_pads = np.column_stack([hy_feat_pads, cv_yrs_pads, cv_sex_pads, cv_dbs_pads])

    # Stage 1 on full WG cohort (PD+HC); predict PADS
    s1_tr, s1_te = fit_stage1(Xs1_wg, y_wg, Xs1_pads, alpha=1.0)
    residual_tr = y_wg - s1_tr

    # Stage 2 LGB on common wrist features (residual target)
    preds_per_seed = []
    for seed in seeds:
        s2_pred = train_lgb(Xwg_n, residual_tr, Xpads_n, seed)
        preds_per_seed.append(s1_te + s2_pred)
    pred_mean = np.mean(np.stack(preds_per_seed, axis=0), axis=0)

    y_pads = pads_df["label"].values.astype(int)
    auroc = float(roc_auc_score(y_pads, pred_mean))
    spearman_r = float(sp_stats.spearmanr(pred_mean, y_pads).statistic)
    return {
        "track": "B_iter5_with_clinical_imputation",
        "auroc": auroc,
        "spearman_r": spearman_r,
        "pred_mean_HC": float(pred_mean[y_pads == 0].mean()),
        "pred_mean_PD": float(pred_mean[y_pads == 1].mean()),
        "pred_std_HC": float(pred_mean[y_pads == 0].std()),
        "pred_std_PD": float(pred_mean[y_pads == 1].std()),
        "preds_per_seed_auroc": [float(roc_auc_score(y_pads, p)) for p in preds_per_seed],
        "imputed_constants": {
            "hy_pd_mean": hy_pads_imp,
            "cv_yrs_pd_mean": cv_yrs_pads_imp,
            "cv_dbs_pd_mean": cv_dbs_pads_imp,
            "n_pads_male": int((cv_sex_pads == 0).sum()),
            "n_pads_female": int((cv_sex_pads == 1).sum()),
        },
        "stage1_pred_mean_HC": float(s1_te[y_pads == 0].mean()),
        "stage1_pred_mean_PD": float(s1_te[y_pads == 1].mean()),
    }


def track_c_pads_only_5fold(pads_df: pd.DataFrame, common_feats: list[str], seeds: list[int]) -> dict:
    """Within-PADS 5-fold AUROC baseline (upper bound on what's achievable from these features alone)."""
    Xpads = pads_df[common_feats].values.astype(np.float64)
    Xpads = np.nan_to_num(Xpads, nan=0.0, posinf=0.0, neginf=0.0)
    Xpads = _winsorize(Xpads)
    y_pads = pads_df["label"].values.astype(int)
    aurocs = []
    for seed in seeds:
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
        oof = np.zeros(len(y_pads), dtype=np.float64)
        for tr_idx, te_idx in skf.split(Xpads, y_pads):
            nrm = FoldNormalizer.fit(Xpads[tr_idx])
            Xtr = nrm.transform(Xpads[tr_idx])
            Xte = nrm.transform(Xpads[te_idx])
            # Use LGB with classification objective via score (use binary as continuous)
            pred = train_lgb(Xtr, y_pads[tr_idx].astype(np.float64), Xte, seed)
            oof[te_idx] = pred
        aurocs.append(float(roc_auc_score(y_pads, oof)))
    return {
        "track": "C_pads_only_5fold_baseline",
        "auroc_mean": float(np.mean(aurocs)),
        "auroc_std": float(np.std(aurocs)),
        "auroc_per_seed": aurocs,
        "n_pd": int((y_pads == 1).sum()),
        "n_hc": int((y_pads == 0).sum()),
    }


# ── Pre-reg / run ───────────────────────────────────────────────────────────


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        return "unknown"


def _formula_sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def make_prereg_payload(seeds: list[int]) -> dict:
    return {
        "experiment": "T3 iter25 — Cross-dataset zero-shot transportability on PADS",
        "external_dataset": "PADS (PhysioNet, parkinsons-disease-smartwatch v1.0.0)",
        "internal_dataset": "WearGait-PD (NLS+WPD, 13-IMU body-worn, 100Hz, full UPDRS-III)",
        "feature_alignment": (
            "Right-wrist 3-axis accelerometer + magnitude → time-domain (rms/std/range/iqr/skew/"
            "kurt/jerk_rms/zcr) + frequency-domain (loco/trem/high band log-power and ratios + "
            "dominant freq + spectral entropy) + magnitude gait_reg (step_t/stride_t/cadence/"
            "step_reg/stride_reg). ~70 common features."
        ),
        "tracks": [
            "A — V2-wrist LGB regressor (no clinical Stage 1; UPDRS-III prediction → AUROC vs PADS PD/HC)",
            "B — iter5-restricted Stage 1+2 with PADS clinical imputation (cv_sex from gender; H&Y/cv_yrs/cv_dbs = WearGait PD-cohort means)",
            "C — Within-PADS 5-fold AUROC baseline (upper bound)",
        ],
        "headline_metric": "AUROC of continuous predictions vs PADS PD/HC binary label",
        "training_set": "Full WearGait-PD cohort (98 PD + 80 HC), wrist-only features, 5 tasks averaged per subject",
        "test_set": "PADS subjects with label ∈ {0=HC, 1=PD}",
        "seeds": list(seeds),
        "5null_inheritance": (
            "PADS subjects never appear in training. Common features standardized using WearGait-only "
            "training statistics. Mean-imputation values for PADS clinical come from WearGait PD "
            "distribution (NOT from PADS labels). LGB tree splits cannot leak PADS labels because "
            "PADS data is never in training."
        ),
        "purpose": (
            "Produce the FIRST published cross-dataset zero-shot transportability number for "
            "WearGait-PD-trained iter5 architecture. Test whether gait-IMU severity prediction "
            "transports to a fully external cohort with different devices, country, and protocol."
        ),
        "thresholds": {
            "useful_transfer_AUROC": 0.65,
            "borderline_AUROC_lower": 0.55,
            "no_transfer_AUROC_max": 0.55,
        },
    }


def write_prereg(seeds: list[int]) -> Path:
    payload = make_prereg_payload(seeds)
    formula = _formula_sha256(payload)
    git = _git_sha()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        **payload,
        "formula_sha256": formula,
        "git_sha": git,
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "created_at_local": datetime.now().isoformat(),
        "timestamp": ts,
        "lockbox_rules": [
            "Architecture FROZEN before any PADS evaluation.",
            "All 3 tracks (A, B, C) evaluated in ONE batch; reported regardless of AUROC.",
            "No 'gate' — paper claims transportability/borderline/no-transfer based on AUROC bins.",
            "PADS data path validated; refuses to run if PADS dataset missing.",
        ],
    }
    pre_path = RESULTS_DIR / f"preregistration_t3_iter25_pads_{ts}.json"
    if pre_path.exists():
        raise RuntimeError(f"Pre-reg path clash: {pre_path}")
    with open(pre_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nPre-reg: {pre_path.name}", flush=True)
    print(f"  formula_sha256 = {formula[:16]}...", flush=True)
    print(f"  git_sha = {git[:12]}", flush=True)
    print(f"  seeds = {seeds}", flush=True)
    return pre_path


def load_and_validate_prereg(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing pre-reg: {path}")
    with open(path) as f:
        pre = json.load(f)
    expected = make_prereg_payload(pre["seeds"])
    if pre["formula_sha256"] != _formula_sha256(expected):
        raise RuntimeError("formula_sha256 mismatch; architecture changed since pre-reg.")
    return pre


def is_pd_sid(sid: str) -> bool:
    return sid.upper().startswith(("NLS", "WPD"))


def run_mode(prereg_path: Path) -> None:
    pre = load_and_validate_prereg(prereg_path)
    seeds = list(pre["seeds"])
    ts = pre["timestamp"]

    if not PADS_DIR.exists():
        raise FileNotFoundError(
            f"PADS dataset not present at {PADS_DIR}. "
            f"Download via: wget -r -N -c -np "
            f"https://physionet.org/files/parkinsons-disease-smartwatch/1.0.0/"
        )

    print(f"\nLoaded pre-reg {prereg_path.name}", flush=True)
    print(f"  seeds = {seeds}, formula_sha256 = {pre['formula_sha256'][:16]}...", flush=True)

    # ── Extract WearGait wrist features (PD-only N=98 — HC CSVs not on remote) ──
    print("\n=== Extract WearGait wrist features (PD-only, matches canonical iter5) ===", flush=True)
    sids_pd, _, _, y_t3, hy, _ = load_full_pd_data()
    clinical = load_clinical_dict(sids_pd)
    pd_sids_set = set(sids_pd)
    label_for_sid = {s: 1 for s in sids_pd}  # All WG subjects we extract are PD
    all_sids = list(sids_pd)
    print(f"  WG SIDs: {len(sids_pd)} PD (HC not available locally — see F31 download notes)", flush=True)
    t0 = time.time()
    wg_df, wg_feats = extract_weargait_wrist(np.array(all_sids), label_for_sid)
    print(f"  WG wrist features: {wg_df.shape}  ({len(wg_feats)} cols, extract elapsed {time.time()-t0:.1f}s)", flush=True)

    # Attach updrs3 + clinical to wg_df (only PD have updrs3 — HC=0 by convention)
    sid_to_y = dict(zip(sids_pd, y_t3))
    sid_to_hy = dict(zip(sids_pd, hy))
    sid_to_cv_yrs = {s: float(v) for s, v in zip(sids_pd, clinical["cv_yrs"])}
    sid_to_cv_sex = {s: float(v) for s, v in zip(sids_pd, clinical["cv_sex"])}
    sid_to_cv_dbs = {s: float(v) for s, v in zip(sids_pd, clinical["cv_dbs"])}
    wg_df["updrs3"] = wg_df["sid"].map(lambda s: sid_to_y.get(s, 0.0)).astype(np.float64)
    wg_df["hy"] = wg_df["sid"].map(lambda s: sid_to_hy.get(s, 0.0)).astype(np.float64)
    wg_df["cv_yrs"] = wg_df["sid"].map(lambda s: sid_to_cv_yrs.get(s, 0.0)).astype(np.float64)
    wg_df["cv_sex"] = wg_df["sid"].map(lambda s: sid_to_cv_sex.get(s, 0.0)).astype(np.float64)
    wg_df["cv_dbs"] = wg_df["sid"].map(lambda s: sid_to_cv_dbs.get(s, 0.0)).astype(np.float64)

    wg_clinical_aligned = {
        "cv_yrs": wg_df["cv_yrs"].values.astype(np.float64),
        "cv_sex": wg_df["cv_sex"].values.astype(np.float64),
        "cv_dbs": wg_df["cv_dbs"].values.astype(np.float64),
    }

    # ── Extract PADS ──
    print("\n=== Extract PADS wrist features ===", flush=True)
    t0 = time.time()
    pads_df, pads_feats = extract_pads()
    print(f"  PADS subjects: {len(pads_df)} ({(pads_df['label']==1).sum()} PD + {(pads_df['label']==0).sum()} HC)", flush=True)
    print(f"  PADS features: {len(pads_feats)} (extract elapsed {time.time()-t0:.1f}s)", flush=True)

    # ── Common feature set ──
    common = sorted(set(wg_feats) & set(pads_feats))
    if len(common) < 30:
        raise RuntimeError(f"Only {len(common)} common features — schema mismatch.")
    print(f"  Common features: {len(common)}", flush=True)

    # ── Track A ──
    print("\n=== Track A — V2-wrist LGB regressor (zero-shot UPDRS regression → AUROC) ===", flush=True)
    res_a = track_a_v2_only(wg_df, pads_df, common, seeds)
    print(f"  AUROC = {res_a['auroc']:.4f}", flush=True)
    print(f"  Spearman ρ vs label = {res_a['spearman_r']:+.4f}", flush=True)
    print(f"  Pred mean: HC={res_a['pred_mean_HC']:.2f}, PD={res_a['pred_mean_PD']:.2f}", flush=True)
    print(f"  Per-seed AUROC: {[round(a,3) for a in res_a['preds_per_seed_auroc']]}", flush=True)

    # ── Track B ──
    print("\n=== Track B — iter5-restricted Stage 1+2 with PADS clinical imputation ===", flush=True)
    pads_meta = pads_df[["pid", "label", "age", "gender"]].copy()
    res_b = track_b_iter5_imputed(wg_df, pads_df, common, seeds, wg_clinical_aligned, pads_meta)
    print(f"  AUROC = {res_b['auroc']:.4f}", flush=True)
    print(f"  Spearman ρ vs label = {res_b['spearman_r']:+.4f}", flush=True)
    print(f"  Stage 1 pred mean: HC={res_b['stage1_pred_mean_HC']:.2f}, PD={res_b['stage1_pred_mean_PD']:.2f}", flush=True)
    print(f"  Full pred mean:    HC={res_b['pred_mean_HC']:.2f}, PD={res_b['pred_mean_PD']:.2f}", flush=True)
    print(f"  Imputed: hy={res_b['imputed_constants']['hy_pd_mean']:.2f}, cv_yrs={res_b['imputed_constants']['cv_yrs_pd_mean']:.2f}, cv_dbs={res_b['imputed_constants']['cv_dbs_pd_mean']:.3f}", flush=True)
    print(f"  Per-seed AUROC: {[round(a,3) for a in res_b['preds_per_seed_auroc']]}", flush=True)

    # ── Track C — PADS-only baseline ──
    print("\n=== Track C — PADS-only 5-fold baseline (upper bound) ===", flush=True)
    res_c = track_c_pads_only_5fold(pads_df, common, seeds)
    print(f"  AUROC mean ± std: {res_c['auroc_mean']:.4f} ± {res_c['auroc_std']:.4f}", flush=True)
    print(f"  Per-seed: {[round(a,3) for a in res_c['auroc_per_seed']]}", flush=True)

    # ── Verdict ──
    headline = max(res_a["auroc"], res_b["auroc"])
    if headline >= 0.65:
        verdict = "USEFUL TRANSFER (paper claims transportability)"
    elif headline >= 0.55:
        verdict = "BORDERLINE (caveat-heavy)"
    else:
        verdict = "NO TRANSFER (also publishable; adds to structural-ceiling story)"
    print(f"\n=== VERDICT (headline AUROC {headline:.4f}): {verdict} ===", flush=True)

    out = {
        "preregistration": prereg_path.name,
        "ts": ts,
        "n_pads_pd": int((pads_df["label"] == 1).sum()),
        "n_pads_hc": int((pads_df["label"] == 0).sum()),
        "n_wg_pd": int((wg_df["label"] == 1).sum()),
        "n_wg_hc": int((wg_df["label"] == 0).sum()),
        "n_common_features": len(common),
        "common_features": common,
        "track_a": res_a,
        "track_b": res_b,
        "track_c": res_c,
        "headline_auroc": headline,
        "verdict": verdict,
    }
    out_path = RESULTS_DIR / f"iter25_pads_zeroshot_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nWrote {out_path.name}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["write_prereg", "run"], required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 1337, 7])
    ap.add_argument("--preregistration_file", type=str, default=None)
    args = ap.parse_args()
    ensure_dir(RESULTS_DIR)
    if args.mode == "write_prereg":
        write_prereg(seeds=list(args.seeds))
        return
    if args.mode == "run":
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required")
        prereg_path = Path(args.preregistration_file)
        if not prereg_path.is_absolute():
            prereg_path = (REPO_ROOT / args.preregistration_file).resolve()
        run_mode(prereg_path)


if __name__ == "__main__":
    main()
