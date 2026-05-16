"""T3 iter25b — Cross-dataset zero-shot transportability on PADS, FIXED.

iter25 (committed at `921a6e8`, F60) found AUROC = 0.5166 (chance) and labeled
this "NO TRANSFER." First-order debug revealed two upstream bugs that polluted
the comparison:

  Bug 1 — units + gravity convention mismatch (60-100× scale gap):
    WG used `R_Wrist_Acc_*` (raw accelerometer in m/s², gravity included; ~10 m/s²
    typical magnitude). PADS used Apple Watch accelerometer in g, gravity-removed
    (~0.05g ≈ 0.5 m/s² typical). Combined unit + gravity-removal: ~200× theoretical
    scale gap. Observed feature ratios 12-110× (e.g., wrist_am_rms WG=10.4, PADS=0.17,
    ratio 62×; wrist_ax_rms ratio 111×).

    After standardizing PADS with WG-only mean/std, all PADS samples ended up at
    z-scores around −3, far outside any LGB tree split. Trees fell through to leaf
    defaults → constant prediction. (Track A pred mean: HC=24.53, PD=24.89 — same.)

  Bug 2 — gait_reg features meaningless on stationary PADS tasks:
    WG records 5 gait/balance tasks (subject is walking/balancing); PADS records
    11 mostly-stationary upper-limb tasks (Relaxed, CrossArms, DrinkGlas, etc.).
    `gait_reg` (step_t, stride_t, cadence, step_reg, stride_reg) measures gait
    autocorrelation peaks. On stationary PADS data these are noise; e.g. PADS
    "cadence" ≈ 293 (impossible for walking), WG = 96 (normal walking).

iter25b FIXES:

  Fix A — match acc convention.
    WG: use `R_Wrist_FreeAcc_E/N/U` (gravity-removed, Earth frame, m/s²).
    PADS: convert from g to m/s² (multiply acc by 9.81). PADS native is FreeAcc-
    style (gravity already removed by Apple onboard fusion).
    Both now in m/s², gravity-removed. Magnitudes are physically comparable.

  Fix B — drop gait_reg features.
    Most subjects in PADS aren't walking; gait_reg is meaningless there.
    extract_wrist_block now skips gait_reg.

  Fix C — keep WG task scope at all 5 tasks (NOT Balance-only).
    Restricting to Balance loses too much WG data (98 → 98 single-task recordings
    with shorter duration). Per-subject averaging across 5 tasks gives more robust
    feature estimates. Task-protocol mismatch remains a caveat in the paper.

TRACKS (single-batch pre-reg):
  Track A2 — V2-wrist LGB regressor (no clinical Stage 1) — same as iter25 Track A
    but with fixed acc convention + no gait_reg.
  Track B2 — iter5 Stage 1+2 with mean-imputed PADS clinical — same as iter25
    Track B but with fixed acc convention + no gait_reg.
  Track C2 — PADS-only 5-fold baseline (upper bound).
  Track D2 — V2-wrist LGB on DIMENSIONLESS features only (skew, kurt, zcr, *_r
    band ratios, dom, se) — robustness check; should be insensitive to any
    remaining unit issues by construction.

USAGE:
  python3 run_t3_iter25b_pads_fixed.py --mode write_prereg --seeds 42 1337 7
  python3 run_t3_iter25b_pads_fixed.py --mode run --preregistration_file <path>
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
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

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

WEARGAIT_PD_CSV = Path("/root/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files")
WEARGAIT_TASKS = ["SelfPace", "HurriedPace", "TUG", "Balance", "TandemGait"]
FS_WG = 100
FS_PADS = 100

# PADS Apple Watch outputs in g (gravity-removed); convert to m/s² to match WG.
PADS_G_TO_MS2 = 9.81

# Feature subsets
DIMENSIONLESS_SUFFIXES = ("_skew", "_kurt", "_zcr", "_loco_r", "_trem_r", "_high_r", "_dom", "_se")
MAGNITUDE_PREFIX = "wrist_am_"  # frame-invariant features (magnitude doesn't depend on axis frame)


def _is_dimensionless(col: str) -> bool:
    return any(col.endswith(suf) for suf in DIMENSIONLESS_SUFFIXES)


def _is_magnitude(col: str) -> bool:
    return col.startswith(MAGNITUDE_PREFIX)


def _resolve_pads_dir() -> Path:
    base = Path("/root/pd-imu/data/raw/pads")
    if not base.exists():
        return Path("/tmp/pads_missing")
    for cand in [
        base / "v1",
        base / "physionet.org/files/parkinsons-disease-smartwatch/1.0.0",
    ]:
        if (cand / "movement").is_dir() and (cand / "preprocessed" / "file_list.csv").is_file():
            return cand
    return base


PADS_DIR = _resolve_pads_dir()


# ── Feature blocks (dimensionless and unit-dependent split) ─────────────────


def _safe(fn, x):
    try:
        return float(fn(np.asarray(x, dtype=np.float64)))
    except Exception:
        return 0.0


def td_feats(x: np.ndarray, prefix: str, fs: int) -> dict:
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


def extract_wrist_block_no_gait(ax: np.ndarray, ay: np.ndarray, az: np.ndarray, fs: int) -> dict:
    """Per-axis td/fd + magnitude td/fd. No gait_reg (Fix B)."""
    out: dict[str, float] = {}
    for axis_name, x in [("ax", ax), ("ay", ay), ("az", az)]:
        out.update(td_feats(x, f"wrist_{axis_name}", fs))
        out.update(fd_feats(x, f"wrist_{axis_name}", fs))
    am = np.sqrt(ax ** 2 + ay ** 2 + az ** 2)
    out.update(td_feats(am, "wrist_am", fs))
    out.update(fd_feats(am, "wrist_am", fs))
    return out


# ── PADS extraction (Fix A: ×9.81 to convert g → m/s²) ──────────────────────


def _verify_pads_assumptions(first_data: np.ndarray, ch_idx: dict, sampling_rate_json: int) -> dict:
    """Sanity checks on PADS assumptions (codex/gemini consult-driven):
       - Sampling rate from Time column delta matches sampling_rate field.
       - Acc values are gravity-removed (mean magnitude in g near 0, NOT near 1).
    """
    t_col = ch_idx.get("Time")
    if t_col is None:
        raise RuntimeError("PADS file missing 'Time' channel — cannot verify sampling rate.")
    times = first_data[:, t_col]
    dt = float(np.median(np.diff(times)))
    fs_from_time = 1.0 / dt if dt > 0 else 0.0
    if not (0.95 * sampling_rate_json <= fs_from_time <= 1.05 * sampling_rate_json):
        raise RuntimeError(
            f"Sampling rate mismatch on PADS: file_Time delta → {fs_from_time:.2f} Hz vs JSON sampling_rate={sampling_rate_json} Hz. "
            "Spectral features would be wrong."
        )
    ax = first_data[:, ch_idx["Accelerometer_X"]]
    ay = first_data[:, ch_idx["Accelerometer_Y"]]
    az = first_data[:, ch_idx["Accelerometer_Z"]]
    mag_g = np.sqrt(ax ** 2 + ay ** 2 + az ** 2)
    mean_mag_g = float(np.mean(mag_g))
    # Gravity-removed (FreeAcc-style): mean magnitude in g should be < 0.5 (typical motion ~0.05 g).
    # Gravity-included (raw): mean magnitude near 1.0 g (mostly gravity + small motion).
    if mean_mag_g > 0.5:
        raise RuntimeError(
            f"PADS acc looks GRAVITY-INCLUDED (mean magnitude {mean_mag_g:.3f} g ≥ 0.5). "
            "Apple CoreMotion CMUserAcceleration vs CMAcceleration distinction matters; "
            "the ×9.81 fix assumes gravity is already removed (FreeAcc-style)."
        )
    return {
        "fs_from_time": round(fs_from_time, 2),
        "fs_json": int(sampling_rate_json),
        "mean_acc_magnitude_g": round(mean_mag_g, 4),
        "gravity_removed": True,
    }


def extract_pads_fixed() -> tuple[pd.DataFrame, list[str], dict]:
    if not PADS_DIR.exists() or not (PADS_DIR / "movement").exists():
        raise FileNotFoundError(f"PADS dataset directory not found: {PADS_DIR}")
    file_list = pd.read_csv(PADS_DIR / "preprocessed" / "file_list.csv")
    movement_dir = PADS_DIR / "movement"

    patients: dict[str, dict] = {}
    for _, row in file_list.iterrows():
        pid_int = row.get("id")
        if pid_int is None or pd.isna(pid_int):
            continue
        pid = str(int(pid_int)).zfill(3)
        label = int(row.get("label", -1))
        if label not in (0, 1):
            continue
        patients[pid] = {
            "label": label,
            "age": float(row.get("age", 0.0)) if not pd.isna(row.get("age", np.nan)) else np.nan,
            "gender": str(row.get("gender", "")).strip(),
        }

    obs_files = sorted([f for f in os.listdir(movement_dir)
                       if f.startswith("observation_") and f.endswith(".json")])
    rows = []
    sanity = None  # filled on first parsed record
    skipped_left_wrist_only = 0
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
            # ── ADJUSTMENT: RightWrist-ONLY (no LeftWrist fallback) — eliminates
            # mirror-axis ambiguity when device-frame axes are reversed for L vs R wrist.
            chosen_rec = None
            has_left = False
            for rec in session.get("records", []):
                loc = rec.get("device_location", "")
                if loc == "RightWrist":
                    chosen_rec = rec
                    break
                if loc == "LeftWrist":
                    has_left = True
            if chosen_rec is None:
                if has_left:
                    skipped_left_wrist_only += 1
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
            # ── ADJUSTMENT: fs + gravity-removal verification on first parsed record ──
            if sanity is None:
                sanity = _verify_pads_assumptions(data, ch_idx, sr)
                print(f"  PADS sanity: fs_from_time={sanity['fs_from_time']} Hz vs json={sanity['fs_json']}; "
                      f"mean acc magnitude in g = {sanity['mean_acc_magnitude_g']} (gravity-removed: True) ✓",
                      flush=True)
            # ── FIX A: convert g → m/s² ─────────────────────────────────────
            ax = data[:, ch_idx["Accelerometer_X"]].astype(np.float32) * PADS_G_TO_MS2
            ay = data[:, ch_idx["Accelerometer_Y"]].astype(np.float32) * PADS_G_TO_MS2
            az = data[:, ch_idx["Accelerometer_Z"]].astype(np.float32) * PADS_G_TO_MS2
            # ── FIX B: no gait_reg ──────────────────────────────────────────
            feats = extract_wrist_block_no_gait(ax, ay, az, sr)
            feats["pid"] = pid
            feats["label"] = patients[pid]["label"]
            feats["age"] = patients[pid]["age"]
            feats["gender"] = patients[pid]["gender"]
            feats["session"] = session.get("record_name", "")
            feats["wrist_used"] = "RightWrist"
            rows.append(feats)

    if sanity is None:
        raise RuntimeError("No PADS records passed RightWrist filter — sanity check could not run.")
    sanity["sessions_parsed"] = len(rows)
    sanity["skipped_left_wrist_only_sessions"] = skipped_left_wrist_only

    if not rows:
        raise RuntimeError("No PADS observations parsed.")
    df = pd.DataFrame(rows)
    feat_cols = [c for c in df.columns if c.startswith("wrist_")]
    if not feat_cols:
        raise RuntimeError("No wrist_* feature columns extracted from PADS.")
    agg = df.groupby("pid")[feat_cols].mean(numeric_only=True).reset_index()
    meta = df.groupby("pid").agg({"label": "first", "age": "first", "gender": "first"}).reset_index()
    out = agg.merge(meta, on="pid")
    return out, feat_cols, sanity


# ── WearGait wrist extraction (Fix A: use FreeAcc gravity-removed) ──────────


def extract_weargait_freeacc(sids: np.ndarray, label_for_sid: dict[str, int]) -> tuple[pd.DataFrame, list[str]]:
    """R_Wrist FreeAcc (gravity-removed, Earth-NEU frame, m/s²) — matches PADS after ×9.81 conversion."""
    rows = []
    for sid in sids:
        d = WEARGAIT_PD_CSV  # PD only — HC CSVs not on remote (F31)
        sess_feats: list[dict] = []
        for task in WEARGAIT_TASKS:
            p = d / f"{sid}_{task}.csv"
            if not p.exists():
                continue
            # ── FIX A: use FreeAcc_E/N/U (gravity-removed, m/s²) ──
            cols = ["R_Wrist_FreeAcc_E", "R_Wrist_FreeAcc_N", "R_Wrist_FreeAcc_U"]
            try:
                df = pd.read_csv(p, usecols=cols)
            except Exception:
                continue
            if not all(c in df.columns for c in cols):
                continue
            ax = np.nan_to_num(df[cols[0]].values.astype(np.float32))
            ay = np.nan_to_num(df[cols[1]].values.astype(np.float32))
            az = np.nan_to_num(df[cols[2]].values.astype(np.float32))
            if len(ax) < 200:
                continue
            # ── FIX B: no gait_reg ──
            sess_feats.append(extract_wrist_block_no_gait(ax, ay, az, FS_WG))
        if not sess_feats:
            continue
        avg = {}
        for k in sess_feats[0]:
            avg[k] = float(np.mean([sf[k] for sf in sess_feats if k in sf]))
        avg["sid"] = sid
        avg["label"] = label_for_sid[sid]
        rows.append(avg)
    if not rows:
        raise RuntimeError("No WG FreeAcc wrist features extracted.")
    df = pd.DataFrame(rows)
    feat_cols = sorted([c for c in df.columns if c.startswith("wrist_")])
    return df, feat_cols


# ── Helpers ──────────────────────────────────────────────────────────────────


def _winsorize(x: np.ndarray, lo_pct: float = 1.0, hi_pct: float = 99.0) -> np.ndarray:
    lo = np.nanpercentile(x, lo_pct, axis=0)
    hi = np.nanpercentile(x, hi_pct, axis=0)
    return np.clip(x, lo, hi)


# ── Tracks ──────────────────────────────────────────────────────────────────


def _train_apply_lgb(Xwg: np.ndarray, ywg: np.ndarray, Xpads: np.ndarray, seeds: list[int]) -> tuple[np.ndarray, list[np.ndarray]]:
    """Standard pipeline: clean → winsorize → standardize (WG-only stats) → LGB ensemble across seeds."""
    Xwg = np.nan_to_num(Xwg, nan=0.0, posinf=0.0, neginf=0.0)
    Xpads = np.nan_to_num(Xpads, nan=0.0, posinf=0.0, neginf=0.0)
    Xwg = _winsorize(Xwg)
    Xpads = _winsorize(Xpads)
    nrm = FoldNormalizer.fit(Xwg)
    Xwg_n = nrm.transform(Xwg)
    Xpads_n = nrm.transform(Xpads)
    preds_per_seed = []
    for seed in seeds:
        pred = train_lgb(Xwg_n, ywg, Xpads_n, seed)
        preds_per_seed.append(pred)
    pred_mean = np.mean(np.stack(preds_per_seed, axis=0), axis=0)
    return pred_mean, preds_per_seed


def track_a2(wg_df: pd.DataFrame, pads_df: pd.DataFrame, common_feats: list[str], seeds: list[int]) -> dict:
    pd_mask = (wg_df["label"].values == 1)
    wg_pd = wg_df[pd_mask].reset_index(drop=True)
    Xwg = wg_pd[common_feats].values.astype(np.float64)
    Xpads = pads_df[common_feats].values.astype(np.float64)
    y_wg = wg_pd["updrs3"].values.astype(np.float64)
    y_pads = pads_df["label"].values.astype(int)
    pred_mean, preds_per_seed = _train_apply_lgb(Xwg, y_wg, Xpads, seeds)
    return {
        "track": "A2_v2_wrist_lgb_freeacc",
        "auroc": float(roc_auc_score(y_pads, pred_mean)),
        "spearman_r": float(sp_stats.spearmanr(pred_mean, y_pads).statistic),
        "pred_mean_HC": float(pred_mean[y_pads == 0].mean()),
        "pred_mean_PD": float(pred_mean[y_pads == 1].mean()),
        "pred_std_HC": float(pred_mean[y_pads == 0].std()),
        "pred_std_PD": float(pred_mean[y_pads == 1].std()),
        "preds_per_seed_auroc": [float(roc_auc_score(y_pads, p)) for p in preds_per_seed],
        "n_features": len(common_feats),
    }


def track_b2(wg_df: pd.DataFrame, pads_df: pd.DataFrame, common_feats: list[str], seeds: list[int],
             wg_clinical: dict[str, np.ndarray], pads_meta: pd.DataFrame) -> dict:
    pd_mask = (wg_df["label"].values == 1)
    wg_pd = wg_df[pd_mask].reset_index(drop=True)
    Xwg = wg_pd[common_feats].values.astype(np.float64)
    Xpads = pads_df[common_feats].values.astype(np.float64)
    y_wg = wg_pd["updrs3"].values.astype(np.float64)
    y_pads = pads_df["label"].values.astype(int)

    Xwg_c = np.nan_to_num(Xwg, nan=0.0, posinf=0.0, neginf=0.0)
    Xpads_c = np.nan_to_num(Xpads, nan=0.0, posinf=0.0, neginf=0.0)
    Xwg_c = _winsorize(Xwg_c)
    Xpads_c = _winsorize(Xpads_c)
    nrm = FoldNormalizer.fit(Xwg_c)
    Xwg_n = nrm.transform(Xwg_c)
    Xpads_n = nrm.transform(Xpads_c)

    n_pads = len(pads_df)
    hy_wg = wg_pd["hy"].values.astype(np.float64)
    hy_feat_wg = get_hy_features(hy_wg)
    cv_yrs_wg = wg_clinical["cv_yrs"][pd_mask]
    cv_sex_wg = wg_clinical["cv_sex"][pd_mask]
    cv_dbs_wg = wg_clinical["cv_dbs"][pd_mask]
    cv_yrs_pads_imp = float(cv_yrs_wg.mean())
    cv_dbs_pads_imp = float(cv_dbs_wg.mean())
    hy_pads_imp = float(hy_wg.mean())
    pads_gender = pads_meta["gender"].fillna("").values
    cv_sex_pads = np.array([1.0 if str(g).lower().startswith("f") else 0.0 for g in pads_gender])
    hy_feat_pads = get_hy_features(np.full(n_pads, hy_pads_imp))
    cv_yrs_pads = np.full(n_pads, cv_yrs_pads_imp)
    cv_dbs_pads = np.full(n_pads, cv_dbs_pads_imp)

    Xs1_wg = np.column_stack([hy_feat_wg, cv_yrs_wg, cv_sex_wg, cv_dbs_wg])
    Xs1_pads = np.column_stack([hy_feat_pads, cv_yrs_pads, cv_sex_pads, cv_dbs_pads])
    s1_tr, s1_te = fit_stage1(Xs1_wg, y_wg, Xs1_pads, alpha=1.0)
    residual_tr = y_wg - s1_tr

    preds_per_seed = []
    for seed in seeds:
        s2_pred = train_lgb(Xwg_n, residual_tr, Xpads_n, seed)
        preds_per_seed.append(s1_te + s2_pred)
    pred_mean = np.mean(np.stack(preds_per_seed, axis=0), axis=0)
    return {
        "track": "B2_iter5_freeacc_clinical_imp",
        "auroc": float(roc_auc_score(y_pads, pred_mean)),
        "spearman_r": float(sp_stats.spearmanr(pred_mean, y_pads).statistic),
        "pred_mean_HC": float(pred_mean[y_pads == 0].mean()),
        "pred_mean_PD": float(pred_mean[y_pads == 1].mean()),
        "preds_per_seed_auroc": [float(roc_auc_score(y_pads, p)) for p in preds_per_seed],
        "stage1_pred_mean_HC": float(s1_te[y_pads == 0].mean()),
        "stage1_pred_mean_PD": float(s1_te[y_pads == 1].mean()),
        "imputed_constants": {
            "hy_pd_mean": hy_pads_imp,
            "cv_yrs_pd_mean": cv_yrs_pads_imp,
            "cv_dbs_pd_mean": cv_dbs_pads_imp,
            "n_pads_male": int((cv_sex_pads == 0).sum()),
            "n_pads_female": int((cv_sex_pads == 1).sum()),
        },
    }


def track_c2(pads_df: pd.DataFrame, common_feats: list[str], seeds: list[int]) -> dict:
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
            pred = train_lgb(Xtr, y_pads[tr_idx].astype(np.float64), Xte, seed)
            oof[te_idx] = pred
        aurocs.append(float(roc_auc_score(y_pads, oof)))
    return {
        "track": "C2_pads_only_5fold_baseline",
        "auroc_mean": float(np.mean(aurocs)),
        "auroc_std": float(np.std(aurocs)),
        "auroc_per_seed": aurocs,
    }


def track_d2_dimensionless(wg_df: pd.DataFrame, pads_df: pd.DataFrame, common_feats: list[str], seeds: list[int]) -> dict:
    """Track D2 — V2-wrist LGB on dimensionless features only (robustness check)."""
    dl_feats = [c for c in common_feats if _is_dimensionless(c)]
    pd_mask = (wg_df["label"].values == 1)
    wg_pd = wg_df[pd_mask].reset_index(drop=True)
    Xwg = wg_pd[dl_feats].values.astype(np.float64)
    Xpads = pads_df[dl_feats].values.astype(np.float64)
    y_wg = wg_pd["updrs3"].values.astype(np.float64)
    y_pads = pads_df["label"].values.astype(int)
    pred_mean, preds_per_seed = _train_apply_lgb(Xwg, y_wg, Xpads, seeds)
    return {
        "track": "D2_dimensionless_only",
        "auroc": float(roc_auc_score(y_pads, pred_mean)),
        "spearman_r": float(sp_stats.spearmanr(pred_mean, y_pads).statistic),
        "preds_per_seed_auroc": [float(roc_auc_score(y_pads, p)) for p in preds_per_seed],
        "n_features": len(dl_feats),
        "feature_list": dl_feats,
    }


def track_a3_magnitude_only(wg_df: pd.DataFrame, pads_df: pd.DataFrame, common_feats: list[str], seeds: list[int]) -> dict:
    """Track A3 — V2-wrist LGB on MAGNITUDE-only features (frame-invariant).

    Per consult synthesis: WG R_Wrist FreeAcc is in EARTH-NEU frame; PADS Apple Watch
    FreeAcc is in DEVICE-XYZ frame. Per-axis features (ax/ay/az) are NOT semantically
    aligned across datasets. Only magnitude features (wrist_am_*) are frame-invariant
    and physically comparable. This track is the cleanest cross-dataset comparison.
    """
    mag_feats = [c for c in common_feats if _is_magnitude(c)]
    if not mag_feats:
        raise RuntimeError("No magnitude features (wrist_am_*) found in common set.")
    pd_mask = (wg_df["label"].values == 1)
    wg_pd = wg_df[pd_mask].reset_index(drop=True)
    Xwg = wg_pd[mag_feats].values.astype(np.float64)
    Xpads = pads_df[mag_feats].values.astype(np.float64)
    y_wg = wg_pd["updrs3"].values.astype(np.float64)
    y_pads = pads_df["label"].values.astype(int)
    pred_mean, preds_per_seed = _train_apply_lgb(Xwg, y_wg, Xpads, seeds)
    return {
        "track": "A3_magnitude_only_frame_invariant",
        "auroc": float(roc_auc_score(y_pads, pred_mean)),
        "spearman_r": float(sp_stats.spearmanr(pred_mean, y_pads).statistic),
        "pred_mean_HC": float(pred_mean[y_pads == 0].mean()),
        "pred_mean_PD": float(pred_mean[y_pads == 1].mean()),
        "preds_per_seed_auroc": [float(roc_auc_score(y_pads, p)) for p in preds_per_seed],
        "n_features": len(mag_feats),
        "feature_list": mag_feats,
    }


def track_a3d2_magnitude_dimensionless(wg_df: pd.DataFrame, pads_df: pd.DataFrame, common_feats: list[str], seeds: list[int]) -> dict:
    """Track A3∩D2 — magnitude-only AND dimensionless (most rigorous frame+unit-invariant)."""
    feats = [c for c in common_feats if _is_magnitude(c) and _is_dimensionless(c)]
    if not feats:
        return {"track": "A3D2_mag_and_dimensionless", "auroc": float("nan"), "n_features": 0, "note": "no features matched both filters"}
    pd_mask = (wg_df["label"].values == 1)
    wg_pd = wg_df[pd_mask].reset_index(drop=True)
    Xwg = wg_pd[feats].values.astype(np.float64)
    Xpads = pads_df[feats].values.astype(np.float64)
    y_wg = wg_pd["updrs3"].values.astype(np.float64)
    y_pads = pads_df["label"].values.astype(int)
    pred_mean, preds_per_seed = _train_apply_lgb(Xwg, y_wg, Xpads, seeds)
    return {
        "track": "A3D2_mag_and_dimensionless",
        "auroc": float(roc_auc_score(y_pads, pred_mean)),
        "spearman_r": float(sp_stats.spearmanr(pred_mean, y_pads).statistic),
        "preds_per_seed_auroc": [float(roc_auc_score(y_pads, p)) for p in preds_per_seed],
        "n_features": len(feats),
        "feature_list": feats,
    }


# ── Pre-reg / run ───────────────────────────────────────────────────────────


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        return "unknown"


def _formula_sha256(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def make_prereg_payload(seeds: list[int]) -> dict:
    return {
        "experiment": "T3 iter25b — Cross-dataset zero-shot transportability on PADS, FIXED acc convention + drop gait_reg + frame-invariant tracks + RightWrist-only + sanity-checked",
        "external_dataset": "PADS (PhysioNet, parkinsons-disease-smartwatch v1.0.0)",
        "internal_dataset": "WearGait-PD (PD-only N=98)",
        "fixes_vs_iter25": {
            "A_match_acc_convention": "WG: R_Wrist_FreeAcc_E/N/U (gravity-removed, Earth, m/s²); PADS: ×9.81 (g → m/s²). Both gravity-removed in m/s².",
            "B_drop_gait_reg": "Removed step_t/stride_t/cadence/step_reg/stride_reg — meaningless on PADS stationary tasks.",
            "C_keep_5_tasks": "WG keeps all 5 tasks (averaging); restricting to Balance loses too much data.",
            "D_rightwrist_only": "PADS RightWrist-only (no LeftWrist fallback) — eliminates mirror-axis ambiguity for per-axis features when device-frame axes flip L vs R.",
            "E_sanity_checks": "Verify PADS sampling rate from Time-column delta matches JSON sampling_rate (±5%); verify PADS acc is gravity-removed (mean magnitude in g < 0.5).",
            "F_add_magnitude_only_track": "Add Track A3 (magnitude-only wrist_am_* features) — frame-invariant; cleanest cross-dataset comparison per codex+gemini consults flagging Earth-NEU vs Device-XYZ axis mismatch.",
        },
        "tracks": [
            "A2 — V2-wrist LGB regressor on FreeAcc features (per-axis + magnitude)",
            "A3 — V2-wrist LGB on MAGNITUDE-ONLY features (frame-invariant; primary headline)",
            "A3D2 — magnitude-only AND dimensionless (most rigorous frame+unit-invariant)",
            "B2 — iter5 Stage 1+2 with PADS clinical imputation",
            "C2 — PADS-only 5-fold baseline (upper bound)",
            "D2 — V2-wrist LGB on dimensionless features only (robustness check)",
        ],
        "primary_headline_track": "A3_magnitude_only_frame_invariant",
        "headline_metric": "AUROC of continuous predictions vs PADS PD/HC binary label",
        "seeds": list(seeds),
        "thresholds": {"useful_transfer_AUROC": 0.65, "borderline_AUROC_lower": 0.55},
        "comparison_to_iter25_AUROC_0_5166": "If iter25b A3 ≥ 0.55 → iter25 was measurement artifact (units + frame); if iter25b A3 ≈ 0.52 → iter25 verdict stands.",
        "consult_predictions": {
            "codex": {"A2": 0.54, "B2": 0.49, "C2": 0.63, "D2": 0.55, "headline": 0.56, "range": [0.50, 0.62]},
            "gemini": {"A2": 0.55, "B2": 0.53, "C2": 0.63, "D2": 0.56, "headline": 0.56, "range": [0.52, 0.60]},
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
            "All 4 tracks (A2, B2, C2, D2) evaluated in ONE batch; reported regardless of AUROC.",
            "Direct comparison vs iter25 AUROC=0.5166 to determine if iter25 was measurement artifact.",
        ],
    }
    pre_path = RESULTS_DIR / f"preregistration_t3_iter25b_pads_{ts}.json"
    if pre_path.exists():
        raise RuntimeError(f"Pre-reg path clash: {pre_path}")
    with open(pre_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nPre-reg: {pre_path.name}", flush=True)
    print(f"  formula_sha256 = {formula[:16]}...", flush=True)
    print(f"  git_sha = {git[:12]}", flush=True)
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


def run_mode(prereg_path: Path) -> None:
    pre = load_and_validate_prereg(prereg_path)
    seeds = list(pre["seeds"])
    ts = pre["timestamp"]
    print(f"\nLoaded pre-reg {prereg_path.name}", flush=True)
    print(f"  seeds = {seeds}, formula_sha256 = {pre['formula_sha256'][:16]}...", flush=True)
    if not (PADS_DIR / "movement").exists():
        raise FileNotFoundError(f"PADS dataset not present at {PADS_DIR}")

    # ── WG FreeAcc extraction ──
    print("\n=== Extract WG R_Wrist FreeAcc (gravity-removed, m/s²) ===", flush=True)
    sids_pd, _, _, y_t3, hy, _ = load_full_pd_data()
    clinical = load_clinical_dict(sids_pd)
    label_for_sid = {s: 1 for s in sids_pd}
    t0 = time.time()
    wg_df, wg_feats = extract_weargait_freeacc(np.array(list(sids_pd)), label_for_sid)
    print(f"  WG: {wg_df.shape}, {len(wg_feats)} cols, elapsed {time.time()-t0:.1f}s", flush=True)

    sid_to_y = dict(zip(sids_pd, y_t3))
    sid_to_hy = dict(zip(sids_pd, hy))
    sid_to_yrs = {s: float(v) for s, v in zip(sids_pd, clinical["cv_yrs"])}
    sid_to_sex = {s: float(v) for s, v in zip(sids_pd, clinical["cv_sex"])}
    sid_to_dbs = {s: float(v) for s, v in zip(sids_pd, clinical["cv_dbs"])}
    wg_df["updrs3"] = wg_df["sid"].map(lambda s: sid_to_y.get(s, 0.0)).astype(np.float64)
    wg_df["hy"] = wg_df["sid"].map(lambda s: sid_to_hy.get(s, 0.0)).astype(np.float64)
    wg_df["cv_yrs"] = wg_df["sid"].map(lambda s: sid_to_yrs.get(s, 0.0)).astype(np.float64)
    wg_df["cv_sex"] = wg_df["sid"].map(lambda s: sid_to_sex.get(s, 0.0)).astype(np.float64)
    wg_df["cv_dbs"] = wg_df["sid"].map(lambda s: sid_to_dbs.get(s, 0.0)).astype(np.float64)
    wg_clinical_aligned = {
        "cv_yrs": wg_df["cv_yrs"].values.astype(np.float64),
        "cv_sex": wg_df["cv_sex"].values.astype(np.float64),
        "cv_dbs": wg_df["cv_dbs"].values.astype(np.float64),
    }

    # ── PADS extraction (×9.81 conversion + RightWrist-only + sanity checks) ──
    print("\n=== Extract PADS Apple Watch (×9.81 → m/s², RightWrist-only, no gait_reg, sanity-checked) ===", flush=True)
    t0 = time.time()
    pads_df, pads_feats, pads_sanity = extract_pads_fixed()
    print(f"  PADS: {len(pads_df)} subjects ({(pads_df['label']==1).sum()} PD + {(pads_df['label']==0).sum()} HC), {len(pads_feats)} cols, elapsed {time.time()-t0:.1f}s", flush=True)
    print(f"  Sanity: {pads_sanity}", flush=True)

    common = sorted(set(wg_feats) & set(pads_feats))
    if len(common) < 30:
        raise RuntimeError(f"Only {len(common)} common features.")
    print(f"  Common features: {len(common)}", flush=True)

    # ── Sanity check: feature scale comparison ──
    print("\n=== Scale sanity check (WG vs PADS, post-fix) ===", flush=True)
    print(f"{'feature':32s} {'WG mean':>10s} {'PADS mean':>10s} {'ratio':>8s}")
    for f in ["wrist_am_rms", "wrist_am_std", "wrist_am_jerk", "wrist_am_loco", "wrist_am_loco_r",
              "wrist_ax_rms", "wrist_ax_skew", "wrist_ax_kurt"]:
        if f in common:
            wm = float(wg_df[f].mean())
            pm = float(pads_df[f].mean())
            r = wm / pm if pm != 0 else float("inf")
            print(f"  {f:32s} {wm:>10.3f} {pm:>10.3f} {r:>8.2f}")

    # ── Tracks ──
    print("\n=== Track A2 — V2-wrist LGB regressor (FreeAcc, no gait_reg) ===", flush=True)
    res_a = track_a2(wg_df, pads_df, common, seeds)
    print(f"  AUROC = {res_a['auroc']:.4f}  (per-seed: {[round(a,3) for a in res_a['preds_per_seed_auroc']]})", flush=True)
    print(f"  Pred mean: HC={res_a['pred_mean_HC']:.3f}, PD={res_a['pred_mean_PD']:.3f}", flush=True)

    print("\n=== Track B2 — iter5 Stage 1+2 with clinical imputation ===", flush=True)
    pads_meta = pads_df[["pid", "label", "age", "gender"]].copy()
    res_b = track_b2(wg_df, pads_df, common, seeds, wg_clinical_aligned, pads_meta)
    print(f"  AUROC = {res_b['auroc']:.4f}  (per-seed: {[round(a,3) for a in res_b['preds_per_seed_auroc']]})", flush=True)
    print(f"  Stage 1 pred mean: HC={res_b['stage1_pred_mean_HC']:.3f}, PD={res_b['stage1_pred_mean_PD']:.3f}", flush=True)
    print(f"  Full pred mean:    HC={res_b['pred_mean_HC']:.3f}, PD={res_b['pred_mean_PD']:.3f}", flush=True)

    print("\n=== Track C2 — PADS-only 5-fold baseline ===", flush=True)
    res_c = track_c2(pads_df, common, seeds)
    print(f"  AUROC = {res_c['auroc_mean']:.4f} ± {res_c['auroc_std']:.4f}", flush=True)

    print("\n=== Track D2 — Dimensionless features only (robustness) ===", flush=True)
    res_d = track_d2_dimensionless(wg_df, pads_df, common, seeds)
    print(f"  AUROC = {res_d['auroc']:.4f}  (n_feats = {res_d['n_features']})", flush=True)
    print(f"  Per-seed: {[round(a,3) for a in res_d['preds_per_seed_auroc']]}", flush=True)

    print("\n=== Track A3 — MAGNITUDE-ONLY features (frame-invariant; primary headline) ===", flush=True)
    res_a3 = track_a3_magnitude_only(wg_df, pads_df, common, seeds)
    print(f"  AUROC = {res_a3['auroc']:.4f}  (n_feats = {res_a3['n_features']})", flush=True)
    print(f"  Pred mean: HC={res_a3['pred_mean_HC']:.3f}, PD={res_a3['pred_mean_PD']:.3f}", flush=True)
    print(f"  Per-seed: {[round(a,3) for a in res_a3['preds_per_seed_auroc']]}", flush=True)

    print("\n=== Track A3∩D2 — magnitude AND dimensionless (most rigorous) ===", flush=True)
    res_a3d2 = track_a3d2_magnitude_dimensionless(wg_df, pads_df, common, seeds)
    print(f"  AUROC = {res_a3d2.get('auroc', 'n/a')}  (n_feats = {res_a3d2.get('n_features', 0)})", flush=True)
    if "preds_per_seed_auroc" in res_a3d2:
        print(f"  Per-seed: {[round(a,3) for a in res_a3d2['preds_per_seed_auroc']]}", flush=True)

    # ── Verdict + comparison vs iter25 ──
    # Primary headline is A3 (magnitude-only, frame-invariant) — the cleanest cross-dataset claim.
    primary_headline = res_a3["auroc"]
    all_track_aurocs = {
        "A2": res_a["auroc"], "A3": res_a3["auroc"],
        "B2": res_b["auroc"], "D2": res_d["auroc"],
        "A3D2": res_a3d2.get("auroc", float("nan")),
    }
    best_headline = max(v for v in all_track_aurocs.values() if not np.isnan(v))
    iter25_auroc = 0.5166
    delta_primary = primary_headline - iter25_auroc
    delta_best = best_headline - iter25_auroc

    if primary_headline >= 0.65:
        verdict = "USEFUL TRANSFER"
    elif primary_headline >= 0.55:
        verdict = "BORDERLINE"
    else:
        verdict = "NO TRANSFER"
    if abs(delta_primary) < 0.02:
        artifact_check = "iter25 verdict STANDS — fixes did not change the result"
    elif delta_primary > 0.02:
        artifact_check = "iter25 was MEASUREMENT ARTIFACT — fixes substantively change the result"
    else:
        artifact_check = "iter25b PERFORMS WORSE — unexpected (regression)"

    print(f"\n=== PRIMARY HEADLINE (Track A3 magnitude-only, frame-invariant): AUROC = {primary_headline:.4f} ===", flush=True)
    print(f"  vs iter25 0.5166, Δ = {delta_primary:+.4f}", flush=True)
    print(f"  Best across all tracks: {best_headline:.4f} (Δ = {delta_best:+.4f})", flush=True)
    print(f"  Verdict: {verdict}", flush=True)
    print(f"  {artifact_check}", flush=True)
    print(f"  Track table: {all_track_aurocs}", flush=True)

    out = {
        "preregistration": prereg_path.name,
        "ts": ts,
        "n_pads_pd": int((pads_df["label"] == 1).sum()),
        "n_pads_hc": int((pads_df["label"] == 0).sum()),
        "n_wg_pd": int((wg_df["label"] == 1).sum()),
        "n_common_features": len(common),
        "common_features": common,
        "pads_sanity": pads_sanity,
        "track_a2": res_a,
        "track_a3_magnitude_only": res_a3,
        "track_a3d2_mag_and_dimensionless": res_a3d2,
        "track_b2": res_b,
        "track_c2": res_c,
        "track_d2": res_d,
        "iter25_auroc_baseline": iter25_auroc,
        "primary_headline_auroc": primary_headline,
        "best_track_auroc": best_headline,
        "delta_primary_vs_iter25": delta_primary,
        "delta_best_vs_iter25": delta_best,
        "verdict": verdict,
        "artifact_check": artifact_check,
        "all_track_aurocs": all_track_aurocs,
    }
    out_path = RESULTS_DIR / f"iter25b_pads_fixed_{ts}.json"
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
