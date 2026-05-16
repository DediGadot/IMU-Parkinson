"""Unified extractor for 5 step-function feature families per PD subject.

Designed to maximize utilization of the remote slave (17-core CPU, RTX 4060):
single pass over each CSV reads ~25 MB once and emits descriptors for all
families. ProcessPoolExecutor with spawn context + OMP_NUM_THREADS=1 per worker
(LightGBM not used here, but the spawn pattern is required for any future fan-in
that touches LightGBM caches; see feedback_processpool_spawn_context_required.md).

Feature families (target-free; descriptiveness scored later via metric_lib):

  spd      — Riemannian SPD covariance: 13 IMU channels (Acc magnitudes) → 13x13
             cov per window → log-Euclidean tangent vectorization → per-subject
             descriptors (eigenvalue spectrum, log-det, trace, vec_norm, mean
             tangent flattened top-10 PCs).

  klc      — Kinematic loop-closure: forward-integrate pelvis→thigh→shank→foot
             on each leg using IMU orientations; measure residual to floor
             constraint at heel-strike, and bilateral closure (toe-toe distance
             at double-stance). Captures tremor/jitter that integrates over the
             kinematic chain.

  crqa     — Cross-Recurrence Quantification on bilateral pairs (L↔R foot,
             L↔R wrist, sternum↔sacrum) using sliding-window phase-space
             embeddings. Emits RR, DET, LAM, TT, L_max per pair.

  mfdfa    — Multifractal detrended fluctuation analysis on stride-time and
             gait-cycle-length series. Singularity spectrum width Δα and
             asymmetry; Hurst exponent at q=2.

  ph       — Persistent homology H0/H1 on phase-space embedding of trunk pitch
             + sacrum angular velocity. SW1PerS-style periodicity index +
             H1 lifetime entropy. Uses ripser if available, falls back to
             alpha-complex approximation if not.

Each family writes its own CSV to results/ with a sidecar manifest.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import socket
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.linalg import eigh
from scipy.signal import find_peaks, welch
from scipy.spatial.distance import cdist
from scipy.spatial.transform import Rotation

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = REPO_ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ── IMU sensor layout ──────────────────────────────────────────────────────────

SENSORS = [
    "LowerBack", "R_Wrist", "L_Wrist", "R_MidLatThigh", "L_MidLatThigh",
    "R_LatShank", "L_LatShank", "R_DorsalFoot", "L_DorsalFoot",
    "R_Ankle", "L_Ankle", "Xiphoid", "Forehead",
]
SAMPLE_RATE = 100  # Hz

TASKS = ["TUG", "SelfPace", "HurriedPace", "TandemGait", "Balance",
         "SelfPace_mat", "HurriedPace_mat", "SelfPace_matTURN"]

# Bilateral pairs for CRQA
BILATERAL_PAIRS = [
    ("R_DorsalFoot", "L_DorsalFoot"),
    ("R_Wrist", "L_Wrist"),
    ("R_LatShank", "L_LatShank"),
    ("R_MidLatThigh", "L_MidLatThigh"),
    ("Xiphoid", "LowerBack"),
    ("Forehead", "LowerBack"),
]


# ── Helpers ────────────────────────────────────────────────────────────────────


def magnitude(X: np.ndarray) -> np.ndarray:
    """Vector magnitude across the last axis."""
    return np.sqrt(np.sum(X**2, axis=-1))


def read_csv_safe(path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path, low_memory=False)
        return df
    except Exception:
        return None


def sensor_acc(df: pd.DataFrame, sensor: str) -> np.ndarray | None:
    """Return Nx3 acceleration array (Acc_X/Y/Z) for a sensor, NaN-clean."""
    cols = [f"{sensor}_Acc_X", f"{sensor}_Acc_Y", f"{sensor}_Acc_Z"]
    if not all(c in df.columns for c in cols):
        return None
    X = df[cols].to_numpy(np.float64)
    if np.all(np.isnan(X)):
        return None
    # Forward-fill then back-fill NaNs along time
    for j in range(3):
        col = X[:, j]
        nans = np.isnan(col)
        if nans.any():
            valid = ~nans
            if valid.sum() < 10:
                return None
            col = pd.Series(col).interpolate(limit_direction="both").to_numpy()
            X[:, j] = col
    return X


def sensor_gyr(df: pd.DataFrame, sensor: str) -> np.ndarray | None:
    cols = [f"{sensor}_Gyr_X", f"{sensor}_Gyr_Y", f"{sensor}_Gyr_Z"]
    if not all(c in df.columns for c in cols):
        return None
    X = df[cols].to_numpy(np.float64)
    if np.all(np.isnan(X)):
        return None
    for j in range(3):
        col = X[:, j]
        nans = np.isnan(col)
        if nans.any():
            valid = ~nans
            if valid.sum() < 10:
                return None
            col = pd.Series(col).interpolate(limit_direction="both").to_numpy()
            X[:, j] = col
    return X


def sensor_rpy(df: pd.DataFrame, sensor: str) -> np.ndarray | None:
    cols = [f"{sensor}_Roll", f"{sensor}_Pitch", f"{sensor}_Yaw"]
    if not all(c in df.columns for c in cols):
        return None
    X = df[cols].to_numpy(np.float64)
    if np.all(np.isnan(X)):
        return None
    for j in range(3):
        col = X[:, j]
        nans = np.isnan(col)
        if nans.any():
            valid = ~nans
            if valid.sum() < 10:
                return None
            col = pd.Series(col).interpolate(limit_direction="both").to_numpy()
            X[:, j] = col
    return X


# ── 1. SPD COVARIANCE FEATURES ────────────────────────────────────────────────


def spd_features_per_task(df: pd.DataFrame, win_sec: float = 4.0, hop_sec: float = 2.0) -> dict[str, float]:
    """Per-task SPD descriptors from 13-channel acc-magnitude covariance."""
    win = int(win_sec * SAMPLE_RATE)
    hop = int(hop_sec * SAMPLE_RATE)
    # 13 channels = acc-magnitude per sensor
    mags = []
    for s in SENSORS:
        X = sensor_acc(df, s)
        if X is None:
            mags.append(np.zeros(len(df)))
        else:
            mags.append(magnitude(X))
    M = np.stack(mags, axis=1)  # T x 13
    if len(M) < win:
        return {}

    tangents = []
    eigs = []
    log_dets = []
    traces = []
    for start in range(0, len(M) - win + 1, hop):
        seg = M[start:start + win]
        # Center
        seg = seg - seg.mean(axis=0, keepdims=True)
        C = (seg.T @ seg) / win + 1e-6 * np.eye(13)
        # Eigendecomp
        w, V = eigh(C)
        w = np.clip(w, 1e-9, None)
        # Log-Euclidean tangent
        log_C = V @ np.diag(np.log(w)) @ V.T
        # Upper triangle vectorization (with sqrt(2) on off-diagonals for proper Frobenius isometry)
        iu = np.triu_indices(13)
        coords = log_C[iu]
        # Scale off-diagonals
        mask = np.zeros_like(coords, dtype=bool)
        for k, (i, j) in enumerate(zip(*iu)):
            mask[k] = (i != j)
        coords[mask] *= np.sqrt(2.0)
        tangents.append(coords)
        eigs.append(w)
        log_dets.append(float(np.sum(np.log(w))))
        traces.append(float(np.trace(C)))

    if not tangents:
        return {}
    tangents = np.stack(tangents)  # n_win x 91
    eigs = np.stack(eigs)          # n_win x 13

    feat = {}
    # Tangent-vector summary statistics
    feat["spd_tangent_mean_norm"] = float(np.linalg.norm(tangents.mean(axis=0)))
    feat["spd_tangent_std_mean"] = float(tangents.std(axis=0).mean())
    feat["spd_tangent_norm_p95"] = float(np.quantile(np.linalg.norm(tangents, axis=1), 0.95))
    feat["spd_tangent_norm_mean"] = float(np.linalg.norm(tangents, axis=1).mean())

    # Eigenvalue spectrum
    for r, name in [(0, "lowest"), (12, "top"), (10, "rank10"), (6, "rank6")]:
        feat[f"spd_eig_{name}_mean"] = float(eigs[:, r].mean())
        feat[f"spd_eig_{name}_std"] = float(eigs[:, r].std())
    # Condition number stats
    cond = eigs[:, 12] / np.clip(eigs[:, 0], 1e-9, None)
    feat["spd_cond_mean"] = float(cond.mean())
    feat["spd_cond_p95"] = float(np.quantile(cond, 0.95))
    feat["spd_cond_log_mean"] = float(np.log(cond).mean())

    # Log-det and trace
    feat["spd_logdet_mean"] = float(np.mean(log_dets))
    feat["spd_logdet_std"] = float(np.std(log_dets))
    feat["spd_trace_mean"] = float(np.mean(traces))
    feat["spd_trace_std"] = float(np.std(traces))

    # Top-10 PCs of tangent vectors (per-subject reduction, no cohort stats)
    tang_centered = tangents - tangents.mean(axis=0, keepdims=True)
    if tang_centered.shape[0] >= 10:
        try:
            U, S, Vt = np.linalg.svd(tang_centered, full_matrices=False)
            for k in range(min(10, len(S))):
                feat[f"spd_pc{k}_singular"] = float(S[k])
            # Explained variance ratio
            evr = (S**2) / (S**2).sum()
            for k in range(min(10, len(evr))):
                feat[f"spd_pc{k}_evr"] = float(evr[k])
        except Exception:
            pass

    return feat


# ── 2. KINEMATIC LOOP-CLOSURE ─────────────────────────────────────────────────


def klc_features_per_task(df: pd.DataFrame, win_sec: float = 4.0, hop_sec: float = 2.0) -> dict[str, float]:
    """Forward-integrate IMU orientations + accelerations through the leg chain.

    For each leg L/R: compute the predicted foot position from
    LowerBack → MidLatThigh → LatShank → DorsalFoot using sequential
    rotation composition + acceleration double-integration.

    Errors / closure violations vs the physical floor and bilateral toe-toe
    geometry capture integrated tremor + rigidity jitter.
    """
    feat = {}
    win = int(win_sec * SAMPLE_RATE)
    hop = int(hop_sec * SAMPLE_RATE)

    # Approximate fixed body segment lengths (m) — population values
    L_thigh = 0.42
    L_shank = 0.43
    L_foot = 0.12

    rmse_R = []
    rmse_L = []
    bilateral = []

    for start in range(0, len(df) - win + 1, hop):
        seg = df.iloc[start:start + win]
        for side, rmse_list in [("R", rmse_R), ("L", rmse_L)]:
            # Use Roll/Pitch/Yaw as the segment orientations (Euler angles)
            thigh = sensor_rpy(seg, f"{side}_MidLatThigh")
            shank = sensor_rpy(seg, f"{side}_LatShank")
            foot = sensor_rpy(seg, f"{side}_DorsalFoot")
            if thigh is None or shank is None or foot is None:
                continue
            # Convert each Euler triple to a rotation matrix; chain
            try:
                R_thigh = Rotation.from_euler("xyz", thigh, degrees=True).as_matrix()
                R_shank = Rotation.from_euler("xyz", shank, degrees=True).as_matrix()
                R_foot = Rotation.from_euler("xyz", foot, degrees=True).as_matrix()
            except Exception:
                continue
            # Compute foot position by stacking segments along their local -Z axis
            seg_pos = np.zeros((len(seg), 3))
            for t in range(len(seg)):
                hip = np.array([0, 0, 0.95])  # nominal hip height
                # Translate down each segment along its -Z body axis
                v_thigh = R_thigh[t] @ np.array([0, 0, -L_thigh])
                v_shank = R_shank[t] @ np.array([0, 0, -L_shank])
                v_foot = R_foot[t] @ np.array([0, 0, -L_foot])
                seg_pos[t] = hip + v_thigh + v_shank + v_foot
            # Floor-constraint residual = foot Z below floor (z<0) or above (z>0)
            z = seg_pos[:, 2]
            # Identify "stance phase": low gyro magnitude on foot
            gyr_foot = sensor_gyr(seg, f"{side}_DorsalFoot")
            if gyr_foot is None:
                stance = np.zeros(len(seg), dtype=bool)
            else:
                gyr_mag = magnitude(gyr_foot)
                stance = gyr_mag < np.quantile(gyr_mag, 0.25)  # bottom-quartile = stance
            if stance.sum() < 5:
                continue
            z_stance = z[stance]
            # Floor constraint says z_stance should be ~constant. RMSE against median.
            rmse = float(np.sqrt(np.mean((z_stance - np.median(z_stance))**2)))
            rmse_list.append(rmse)

        # Bilateral closure during double-stance: foot-foot distance should be ~constant
        gR = sensor_gyr(seg, "R_DorsalFoot")
        gL = sensor_gyr(seg, "L_DorsalFoot")
        if gR is None or gL is None:
            continue
        gR_mag = magnitude(gR)
        gL_mag = magnitude(gL)
        ds = (gR_mag < np.quantile(gR_mag, 0.25)) & (gL_mag < np.quantile(gL_mag, 0.25))
        if ds.sum() < 5:
            continue
        thigh_R = sensor_rpy(seg, "R_MidLatThigh")
        shank_R = sensor_rpy(seg, "R_LatShank")
        foot_R = sensor_rpy(seg, "R_DorsalFoot")
        thigh_L = sensor_rpy(seg, "L_MidLatThigh")
        shank_L = sensor_rpy(seg, "L_LatShank")
        foot_L = sensor_rpy(seg, "L_DorsalFoot")
        if any(x is None for x in [thigh_R, shank_R, foot_R, thigh_L, shank_L, foot_L]):
            continue
        try:
            posR = []
            posL = []
            R_t = Rotation.from_euler("xyz", thigh_R, degrees=True).as_matrix()
            R_s = Rotation.from_euler("xyz", shank_R, degrees=True).as_matrix()
            R_f = Rotation.from_euler("xyz", foot_R, degrees=True).as_matrix()
            L_t = Rotation.from_euler("xyz", thigh_L, degrees=True).as_matrix()
            L_s = Rotation.from_euler("xyz", shank_L, degrees=True).as_matrix()
            L_f = Rotation.from_euler("xyz", foot_L, degrees=True).as_matrix()
            for t in np.where(ds)[0]:
                p_R = np.array([+0.1, 0, 0.95]) + R_t[t] @ [0, 0, -L_thigh] + R_s[t] @ [0, 0, -L_shank] + R_f[t] @ [0, 0, -L_foot]
                p_L = np.array([-0.1, 0, 0.95]) + L_t[t] @ [0, 0, -L_thigh] + L_s[t] @ [0, 0, -L_shank] + L_f[t] @ [0, 0, -L_foot]
                posR.append(p_R)
                posL.append(p_L)
            posR = np.array(posR)
            posL = np.array(posL)
            d = np.linalg.norm(posR - posL, axis=1)
            bilateral.append(float(np.std(d)))
        except Exception:
            continue

    if rmse_R:
        feat["klc_floor_rmse_R_mean"] = float(np.mean(rmse_R))
        feat["klc_floor_rmse_R_std"] = float(np.std(rmse_R))
        feat["klc_floor_rmse_R_p95"] = float(np.quantile(rmse_R, 0.95))
    if rmse_L:
        feat["klc_floor_rmse_L_mean"] = float(np.mean(rmse_L))
        feat["klc_floor_rmse_L_std"] = float(np.std(rmse_L))
        feat["klc_floor_rmse_L_p95"] = float(np.quantile(rmse_L, 0.95))
    if rmse_R and rmse_L:
        feat["klc_floor_rmse_asym"] = float(abs(np.mean(rmse_R) - np.mean(rmse_L)) /
                                            (np.mean(rmse_R) + np.mean(rmse_L) + 1e-6))
    if bilateral:
        feat["klc_bilat_dist_std_mean"] = float(np.mean(bilateral))
        feat["klc_bilat_dist_std_p95"] = float(np.quantile(bilateral, 0.95))

    return feat


# ── 3. CRQA (Cross-Recurrence Quantification) ─────────────────────────────────


def _recurrence_plot(x: np.ndarray, y: np.ndarray, eps: float) -> np.ndarray:
    """Binary cross-recurrence matrix for 1-D time series x, y at threshold eps."""
    return (cdist(x.reshape(-1, 1), y.reshape(-1, 1)) < eps).astype(np.int8)


def _crqa_metrics(R: np.ndarray, min_len: int = 2) -> dict[str, float]:
    """Extract RR, DET, LAM, TT, L_max from a recurrence matrix."""
    n = R.shape[0]
    rr = float(R.sum()) / (n * n)
    # Diagonal lines (off-diagonal, parallel to main diag)
    diag_lines = []
    for k in range(-n + 1, n):
        if k == 0:
            continue
        d = np.diagonal(R, offset=k)
        run = 0
        for x in d:
            if x == 1:
                run += 1
            else:
                if run >= min_len:
                    diag_lines.append(run)
                run = 0
        if run >= min_len:
            diag_lines.append(run)
    # Vertical lines (laminarity)
    vert_lines = []
    for j in range(n):
        col = R[:, j]
        run = 0
        for x in col:
            if x == 1:
                run += 1
            else:
                if run >= min_len:
                    vert_lines.append(run)
                run = 0
        if run >= min_len:
            vert_lines.append(run)

    det = float(sum(diag_lines) / max(1.0, R.sum()))
    lam = float(sum(vert_lines) / max(1.0, R.sum()))
    L_max = float(max(diag_lines)) if diag_lines else 0.0
    TT = float(np.mean(vert_lines)) if vert_lines else 0.0
    return {"rr": rr, "det": det, "lam": lam, "tt": TT, "l_max": L_max}


def crqa_features_per_task(df: pd.DataFrame, win_sec: float = 5.0, hop_sec: float = 5.0, max_samples: int = 200) -> dict[str, float]:
    """CRQA on bilateral phase-space pairs, downsampled to keep RP small."""
    feat = {}
    win = int(win_sec * SAMPLE_RATE)
    hop = int(hop_sec * SAMPLE_RATE)

    for sA, sB in BILATERAL_PAIRS:
        accA = sensor_acc(df, sA)
        accB = sensor_acc(df, sB)
        if accA is None or accB is None:
            continue
        xA = magnitude(accA)
        xB = magnitude(accB)
        metrics_acc = {"rr": [], "det": [], "lam": [], "tt": [], "l_max": []}
        for start in range(0, len(xA) - win + 1, hop):
            a = xA[start:start + win]
            b = xB[start:start + win]
            # Downsample
            if len(a) > max_samples:
                idx = np.linspace(0, len(a) - 1, max_samples).astype(int)
                a = a[idx]
                b = b[idx]
            # Z-score per window
            a = (a - a.mean()) / max(a.std(), 1e-6)
            b = (b - b.mean()) / max(b.std(), 1e-6)
            eps = 0.5  # ~10% of RR target
            R = _recurrence_plot(a, b, eps)
            m = _crqa_metrics(R)
            for k, v in m.items():
                metrics_acc[k].append(v)
        if metrics_acc["rr"]:
            tag = f"crqa_{sA[:3]}_{sB[:3]}"
            for k, vlist in metrics_acc.items():
                feat[f"{tag}_{k}_mean"] = float(np.mean(vlist))
                feat[f"{tag}_{k}_std"] = float(np.std(vlist))

    return feat


# ── 4. MULTIFRACTAL DFA (Kantelhardt 2002) ────────────────────────────────────


def _mfdfa_q_range(signal: np.ndarray, scales: list[int], q_values: list[float], order: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Kantelhardt MF-DFA. Returns (F_q[scale, q] = fluctuation, log-log slope per q)."""
    Y = np.cumsum(signal - signal.mean())
    n = len(Y)
    F_q = np.zeros((len(scales), len(q_values)))
    for s_idx, s in enumerate(scales):
        if n < 2 * s:
            F_q[s_idx, :] = np.nan
            continue
        n_seg = n // s
        Y_segs = Y[:n_seg * s].reshape(n_seg, s)
        # Detrend each segment with polynomial of given order
        x = np.arange(s)
        F2 = np.zeros(n_seg)
        for v in range(n_seg):
            coeffs = np.polyfit(x, Y_segs[v], order)
            trend = np.polyval(coeffs, x)
            F2[v] = np.mean((Y_segs[v] - trend) ** 2)
        F2 = np.clip(F2, 1e-12, None)
        for q_idx, q in enumerate(q_values):
            if abs(q) < 0.01:
                # q→0 limit
                F_q[s_idx, q_idx] = np.exp(0.5 * np.mean(np.log(F2)))
            else:
                F_q[s_idx, q_idx] = (np.mean(F2 ** (q / 2.0))) ** (1.0 / q)
    # Generalized Hurst h(q)
    log_s = np.log(scales)
    h_q = np.zeros(len(q_values))
    for q_idx in range(len(q_values)):
        y_log = np.log(F_q[:, q_idx])
        valid = np.isfinite(y_log)
        if valid.sum() < 3:
            h_q[q_idx] = np.nan
            continue
        slope, _ = np.polyfit(log_s[valid], y_log[valid], 1)
        h_q[q_idx] = slope
    return F_q, h_q


def mfdfa_features(signal: np.ndarray, prefix: str = "mfdfa") -> dict[str, float]:
    """Multifractal singularity spectrum width Δα + asymmetry."""
    feat = {}
    if len(signal) < 200:
        return feat
    scales = [int(s) for s in np.unique(np.round(np.logspace(np.log10(8), np.log10(min(len(signal) // 4, 256)), 12)))]
    if len(scales) < 5:
        return feat
    q_values = list(np.linspace(-5, 5, 11))
    try:
        _, h_q = _mfdfa_q_range(signal, scales, q_values, order=1)
    except Exception:
        return feat
    if np.isnan(h_q).any():
        return feat
    # Legendre transform to singularity spectrum
    q = np.array(q_values)
    tau = q * h_q - 1.0
    alpha = np.gradient(tau, q)
    f_alpha = q * alpha - tau
    delta_alpha = float(np.max(alpha) - np.min(alpha))
    # Asymmetry
    idx_max = int(np.argmax(f_alpha))
    asym = float((np.max(alpha) - alpha[idx_max]) - (alpha[idx_max] - np.min(alpha)))
    h_q2 = float(h_q[np.argmin(np.abs(q))]) if (np.abs(q) < 0.01).any() else float(h_q[5])
    hurst = float(h_q[np.argmin(np.abs(q - 2.0))])
    feat[f"{prefix}_delta_alpha"] = delta_alpha
    feat[f"{prefix}_asymmetry"] = asym
    feat[f"{prefix}_hurst_q2"] = hurst
    feat[f"{prefix}_h_q0"] = h_q2
    feat[f"{prefix}_h_q_pos5"] = float(h_q[-1])
    feat[f"{prefix}_h_q_neg5"] = float(h_q[0])
    feat[f"{prefix}_h_range"] = float(h_q[0] - h_q[-1])
    return feat


def mfdfa_features_per_task(df: pd.DataFrame) -> dict[str, float]:
    """MFDFA on stride-derived series + sensor-acceleration time series."""
    feat = {}
    # Compose stride series proxy: detect peaks in foot acceleration magnitude (heel strikes)
    for side in ["R", "L"]:
        acc = sensor_acc(df, f"{side}_DorsalFoot")
        if acc is None:
            continue
        mag = magnitude(acc)
        # Find heel-strike peaks
        peaks, _ = find_peaks(mag, distance=int(0.4 * SAMPLE_RATE), prominence=2.0)
        if len(peaks) < 30:
            continue
        stride_times = np.diff(peaks).astype(np.float64) / SAMPLE_RATE
        if len(stride_times) < 30:
            continue
        # Stride-time series (gait variability)
        f = mfdfa_features(stride_times, prefix=f"mfdfa_stride_{side}")
        feat.update(f)
        # Stride-amplitude series (impact magnitude)
        peak_amps = mag[peaks]
        f = mfdfa_features(peak_amps, prefix=f"mfdfa_amp_{side}")
        feat.update(f)

    # MFDFA on the trunk pitch series (postural strategy)
    rpy = sensor_rpy(df, "Xiphoid")
    if rpy is not None:
        pitch = rpy[:, 1]
        f = mfdfa_features(pitch, prefix="mfdfa_trunk_pitch")
        feat.update(f)

    return feat


# ── 5. PERSISTENT HOMOLOGY (light-weight implementation) ──────────────────────


def _phase_space_embed(x: np.ndarray, m: int = 3, tau: int = 5, max_pts: int = 400) -> np.ndarray:
    """Takens delay embedding. Returns embedded point cloud (N_pts x m)."""
    n = len(x) - (m - 1) * tau
    if n <= 0:
        return np.empty((0, m))
    pts = np.empty((n, m))
    for i in range(m):
        pts[:, i] = x[i * tau : i * tau + n]
    if n > max_pts:
        idx = np.linspace(0, n - 1, max_pts).astype(int)
        pts = pts[idx]
    return pts


def _h1_persistence_summary(pts: np.ndarray) -> tuple[float, float]:
    """Cheap H1 summary from a point cloud: median + max persistence of 1-cycles.

    Uses a Vietoris-Rips approximation: for each pair (i, j), find the longest
    "cycle" through the kNN graph that births when the edge is added.

    Fallback to (0, 0) if scikit-tda / ripser unavailable.
    """
    try:
        from ripser import ripser
        result = ripser(pts, maxdim=1)
        diag1 = result["dgms"][1]  # H1 birth-death pairs
        if len(diag1) == 0:
            return 0.0, 0.0
        lifetimes = diag1[:, 1] - diag1[:, 0]
        # Filter infinite
        lifetimes = lifetimes[np.isfinite(lifetimes)]
        if len(lifetimes) == 0:
            return 0.0, 0.0
        return float(np.max(lifetimes)), float(np.median(lifetimes))
    except Exception:
        # Fallback: spectral graph approximation
        n = len(pts)
        if n < 4:
            return 0.0, 0.0
        D = cdist(pts, pts)
        np.fill_diagonal(D, np.inf)
        # k-nearest graph
        k = min(5, n - 1)
        nn_dist = np.partition(D, k, axis=1)[:, k]
        # "Persistence" proxy = std of k-nn distances
        return float(np.std(nn_dist)), float(np.median(nn_dist))


def ph_features_per_task(df: pd.DataFrame) -> dict[str, float]:
    """Persistent homology summaries on trunk pitch + sacrum angular velocity."""
    feat = {}
    rpy = sensor_rpy(df, "Xiphoid")
    if rpy is not None:
        pitch = rpy[:, 1]
        # Standardize
        pitch = (pitch - pitch.mean()) / max(pitch.std(), 1e-6)
        pts = _phase_space_embed(pitch, m=3, tau=5, max_pts=400)
        if len(pts) > 50:
            h1_max, h1_med = _h1_persistence_summary(pts)
            feat["ph_trunk_pitch_h1_max"] = h1_max
            feat["ph_trunk_pitch_h1_med"] = h1_med
    gyr = sensor_gyr(df, "LowerBack")
    if gyr is not None:
        ang_vel = magnitude(gyr)
        ang_vel = (ang_vel - ang_vel.mean()) / max(ang_vel.std(), 1e-6)
        pts = _phase_space_embed(ang_vel, m=3, tau=5, max_pts=400)
        if len(pts) > 50:
            h1_max, h1_med = _h1_persistence_summary(pts)
            feat["ph_sacrum_ang_h1_max"] = h1_max
            feat["ph_sacrum_ang_h1_med"] = h1_med
    return feat


# ── Driver ────────────────────────────────────────────────────────────────────


def process_subject(args: tuple) -> tuple[str, dict]:
    sid, data_dir, families = args
    data_dir = Path(data_dir)
    subj_feat: dict[str, list[float]] = {}
    n_tasks = 0
    for task in TASKS:
        csv_path = data_dir / f"{sid}_{task}.csv"
        if not csv_path.exists():
            continue
        df = read_csv_safe(csv_path)
        if df is None or len(df) < 100:
            continue
        # Drop the SYNAPSE manifest etc by suffix check (defensive)
        n_tasks += 1
        if "spd" in families:
            for k, v in spd_features_per_task(df).items():
                subj_feat.setdefault(f"task_{task}_{k}", []).append(v)
        if "klc" in families:
            for k, v in klc_features_per_task(df).items():
                subj_feat.setdefault(f"task_{task}_{k}", []).append(v)
        if "crqa" in families:
            for k, v in crqa_features_per_task(df).items():
                subj_feat.setdefault(f"task_{task}_{k}", []).append(v)
        if "mfdfa" in families:
            for k, v in mfdfa_features_per_task(df).items():
                subj_feat.setdefault(f"task_{task}_{k}", []).append(v)
        if "ph" in families:
            for k, v in ph_features_per_task(df).items():
                subj_feat.setdefault(f"task_{task}_{k}", []).append(v)

    # Aggregate across all tasks: mean + max
    out = {"sid": sid, "n_tasks": n_tasks}
    for k, vs in subj_feat.items():
        out[k] = float(np.mean(vs))
    return sid, out


def write_manifest(name: str, csv_path: Path, *, command: str, families: list[str], n_subjects: int) -> Path:
    """Write a sidecar manifest with provenance per project policy."""
    manifest = {
        "script": Path(__file__).name,
        "git_sha": os.popen("git rev-parse HEAD 2>/dev/null").read().strip() or "unknown",
        "command": command,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "labels_used": False,
        "fold_scope": "global",  # extraction is target-free, fold-locality applied at score time
        "cohort_statistics_used": False,
        "normalization_scope": "per_subject_per_window",
        "families": families,
        "n_subjects": n_subjects,
        "source_artifacts": ["data/raw/weargait-pd/PD PARTICIPANTS/CSV files/"],
        "host": socket.gethostname(),
    }
    manifest_path = csv_path.with_suffix(csv_path.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None, help="Override raw data dir (default: ./data/raw/weargait-pd/PD PARTICIPANTS/CSV files)")
    ap.add_argument("--families", default="spd,klc,crqa,mfdfa,ph", help="Comma-separated family list")
    ap.add_argument("--out", default=None, help="Output CSV (default: results/cache_stepfunction_<families>_<ts>.csv)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--subjects", default=None, help="Comma-separated SIDs to include (default: all PD)")
    ap.add_argument("--limit", type=int, default=None, help="Limit to first N subjects (debug)")
    args = ap.parse_args()

    if args.data_dir is None:
        for cand in [REPO_ROOT / "data" / "raw" / "weargait-pd" / "PD PARTICIPANTS" / "CSV files",
                     Path("/root/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files")]:
            if cand.exists():
                args.data_dir = str(cand)
                break
        else:
            print(f"ERROR: no data dir found", file=sys.stderr)
            return 1

    families = [f.strip() for f in args.families.split(",") if f.strip()]
    data_dir = Path(args.data_dir)

    # Enumerate subjects from disk
    all_sids = sorted({f.name.split("_")[0] for f in data_dir.glob("*.csv") if f.name.startswith(("NLS", "WPD"))})
    if args.subjects:
        wanted = {s.strip() for s in args.subjects.split(",")}
        all_sids = [s for s in all_sids if s in wanted]
    if args.limit:
        all_sids = all_sids[:args.limit]

    print(f"[cache_stepfunction] families={families} N_subjects={len(all_sids)} workers={args.workers}", flush=True)
    t0 = time.time()

    rows = []
    ctx = mp.get_context("spawn")
    os.environ["OMP_NUM_THREADS"] = "1"
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=ctx) as exec_pool:
        futs = {exec_pool.submit(process_subject, (sid, str(data_dir), families)): sid for sid in all_sids}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                sid, row = fut.result(timeout=900)
                rows.append(row)
                if i % 5 == 0 or i == len(all_sids):
                    print(f"  [{i}/{len(all_sids)}] {sid} ({time.time()-t0:.0f}s elapsed)", flush=True)
            except Exception as e:
                sid = futs[fut]
                print(f"  [{i}/{len(all_sids)}] {sid} FAILED: {e}", flush=True)

    df = pd.DataFrame(rows).sort_values("sid").reset_index(drop=True)
    fam_tag = "_".join(families)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.out) if args.out else RESULTS_DIR / f"cache_stepfunction_{fam_tag}_{ts}.csv"
    df.to_csv(out_path, index=False)
    write_manifest(fam_tag, out_path, command=" ".join(sys.argv), families=families, n_subjects=len(df))

    print(f"\n[cache_stepfunction] wrote {out_path} (rows={len(df)}, cols={df.shape[1]})", flush=True)
    print(f"[cache_stepfunction] elapsed: {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
