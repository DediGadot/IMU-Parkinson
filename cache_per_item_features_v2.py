"""Unified per-item UPDRS-III feature cache (v2 — uses raw 22-channel CSVs).

Reads each PD raw CSV once, extracts ALL per-item features in a single pass,
and writes one row per (subject, task) plus a per-subject aggregated cache.

Design:
- Item-specific extractor functions; dispatched per item.
- 16-way multiprocessing over CSV files.
- No fold-aware ops here; pure per-recording feature extraction.
- Outputs: results/peritem_recording_features.csv (per-recording rows)
          results/peritem_subject_features.csv (per-subject aggregated rows)

Usage:
    python3 cache_per_item_features_v2.py --workers 16 \
        --csv_dir "data/raw/weargait-pd/PD PARTICIPANTS/CSV files" \
        --out_recording results/peritem_recording_features.csv \
        --out_subject results/peritem_subject_features.csv
"""
import argparse
import glob
import json
import os
import sys
import warnings
import multiprocessing as mp
from functools import partial

import numpy as np
import pandas as pd
from scipy import signal as sp_signal
from scipy.stats import iqr, kurtosis, skew, entropy as sp_entropy

warnings.filterwarnings("ignore")

FS = 100.0  # Hz, sampling rate

# 13 IMU sensors with 22 channels each
SENSORS = [
    "LowerBack", "Xiphoid", "Forehead",
    "R_Wrist", "L_Wrist",
    "R_MidLatThigh", "L_MidLatThigh",
    "R_LatShank", "L_LatShank",
    "R_DorsalFoot", "L_DorsalFoot",
    "R_Ankle", "L_Ankle",
]
CHANNEL_GROUPS = {
    "Acc": ["X", "Y", "Z"],
    "FreeAcc": ["E", "N", "U"],
    "Gyr": ["X", "Y", "Z"],
    "Mag": ["X", "Y", "Z"],
    "VelInc": ["X", "Y", "Z"],
    "OriInc": ["q0", "q1", "q2", "q3"],
    "Euler": ["Roll", "Pitch", "Yaw"],
}


# ---------------------------------------------------------------------------
# Generic feature primitives
# ---------------------------------------------------------------------------

def _safe_stats(x: np.ndarray, prefix: str) -> dict:
    """Mean, std, range, IQR, skew, kurt, p95, p05."""
    if x.size == 0 or np.all(np.isnan(x)):
        return {f"{prefix}_{k}": np.nan for k in ("mean", "std", "rng", "iqr", "p05", "p95", "skew", "kurt", "rms")}
    x = x[~np.isnan(x)]
    return {
        f"{prefix}_mean": float(np.mean(x)),
        f"{prefix}_std": float(np.std(x)),
        f"{prefix}_rng": float(np.ptp(x)),
        f"{prefix}_iqr": float(iqr(x)),
        f"{prefix}_p05": float(np.percentile(x, 5)),
        f"{prefix}_p95": float(np.percentile(x, 95)),
        f"{prefix}_skew": float(skew(x)) if len(x) > 3 else 0.0,
        f"{prefix}_kurt": float(kurtosis(x)) if len(x) > 3 else 0.0,
        f"{prefix}_rms": float(np.sqrt(np.mean(x ** 2))),
    }


def _spectral_features(x: np.ndarray, fs: float, prefix: str, bands=((0.5, 3), (3, 8), (4, 6), (8, 12))) -> dict:
    """Spectral edge frequency 95%, dominant frequency, entropy, band-powers."""
    if x.size < 32 or np.all(np.isnan(x)):
        out = {f"{prefix}_dom_f": np.nan, f"{prefix}_sef95": np.nan, f"{prefix}_spec_ent": np.nan}
        for lo, hi in bands:
            out[f"{prefix}_bp_{lo}_{hi}"] = np.nan
        return out
    x = x - np.nanmean(x)
    x = np.nan_to_num(x, nan=0.0)
    nperseg = min(256, len(x))
    f, p = sp_signal.welch(x, fs=fs, nperseg=nperseg)
    p = p + 1e-12
    pn = p / p.sum()
    out = {
        f"{prefix}_dom_f": float(f[np.argmax(p)]),
        f"{prefix}_sef95": float(f[np.searchsorted(np.cumsum(pn), 0.95)]),
        f"{prefix}_spec_ent": float(-np.sum(pn * np.log(pn))),
    }
    for lo, hi in bands:
        m = (f >= lo) & (f < hi)
        out[f"{prefix}_bp_{lo}_{hi}"] = float(np.sum(p[m]) * (f[1] - f[0]))
    return out


def _band_power_ratio(x: np.ndarray, fs: float, lo_band, hi_band) -> float:
    """Moore freeze index style ratio: power(hi) / power(lo)."""
    if x.size < 32 or np.all(np.isnan(x)):
        return np.nan
    x = x - np.nanmean(x)
    x = np.nan_to_num(x, nan=0.0)
    nperseg = min(256, len(x))
    f, p = sp_signal.welch(x, fs=fs, nperseg=nperseg)
    lo_p = np.sum(p[(f >= lo_band[0]) & (f < lo_band[1])])
    hi_p = np.sum(p[(f >= hi_band[0]) & (f < hi_band[1])])
    if lo_p < 1e-9:
        return np.nan
    return float(hi_p / lo_p)


def _jerk(x: np.ndarray, fs: float) -> np.ndarray:
    if x.size < 2:
        return np.array([])
    return np.diff(x) * fs


def _sample_entropy(x: np.ndarray, m: int = 2, r_factor: float = 0.2) -> float:
    """Approximate sample entropy. Down-sample if long."""
    if len(x) < 50 or np.all(np.isnan(x)):
        return np.nan
    if len(x) > 500:
        x = x[::int(np.ceil(len(x) / 500))]
    x = x[~np.isnan(x)]
    if len(x) < 50:
        return np.nan
    r = r_factor * np.std(x)
    if r < 1e-9:
        return np.nan
    n = len(x)

    def _phi(m_):
        templates = np.array([x[i:i + m_] for i in range(n - m_)])
        if len(templates) < 2:
            return 0.0
        d = np.max(np.abs(templates[:, None, :] - templates[None, :, :]), axis=-1)
        c = (np.sum(d <= r, axis=1) - 1) / max(n - m_ - 1, 1)
        c = c[c > 0]
        return float(np.mean(np.log(c))) if len(c) else 0.0

    try:
        return _phi(m) - _phi(m + 1)
    except Exception:
        return np.nan


def _phase_locking_value(x: np.ndarray, y: np.ndarray) -> float:
    """PLV between two signals via Hilbert phase."""
    if len(x) < 32 or len(y) < 32:
        return np.nan
    x = x - np.nanmean(x)
    y = y - np.nanmean(y)
    x = np.nan_to_num(x, nan=0.0)
    y = np.nan_to_num(y, nan=0.0)
    n = min(len(x), len(y))
    px = np.angle(sp_signal.hilbert(x[:n]))
    py = np.angle(sp_signal.hilbert(y[:n]))
    return float(np.abs(np.mean(np.exp(1j * (px - py)))))


def _harmonic_ratio(x: np.ndarray, fs: float) -> float:
    """Even/odd harmonic ratio of dominant frequency. PD harmonic loss reflected here."""
    if len(x) < 64 or np.all(np.isnan(x)):
        return np.nan
    x = x - np.nanmean(x)
    x = np.nan_to_num(x, nan=0.0)
    nperseg = min(256, len(x))
    f, p = sp_signal.welch(x, fs=fs, nperseg=nperseg)
    if p.max() < 1e-12:
        return np.nan
    f0 = f[np.argmax(p)]
    if f0 < 0.3:
        return np.nan
    even = sum(p[np.argmin(np.abs(f - k * f0))] for k in (2, 4, 6, 8))
    odd = sum(p[np.argmin(np.abs(f - k * f0))] for k in (1, 3, 5, 7))
    if odd < 1e-12:
        return np.nan
    return float(even / odd)


def _phase_space_area(angle: np.ndarray, ang_vel: np.ndarray) -> float:
    """Area of (angle, ang_vel) trajectory via convex hull approximation."""
    if len(angle) < 16 or len(ang_vel) < 16:
        return np.nan
    a = np.nan_to_num(angle, nan=0.0)
    v = np.nan_to_num(ang_vel, nan=0.0)
    return float(np.std(a) * np.std(v))


def _cv(x: np.ndarray) -> float:
    if len(x) < 2 or np.all(np.isnan(x)):
        return np.nan
    m = np.nanmean(x)
    if abs(m) < 1e-9:
        return np.nan
    return float(np.nanstd(x) / m)


# ---------------------------------------------------------------------------
# Event detection (sit-to-stand, gait phases, freeze events)
# ---------------------------------------------------------------------------

def _detect_seat_off(lumbar_acc_z: np.ndarray, fs: float = FS):
    """Find sit-to-stand transition window in TUG. Returns (start_idx, peak_idx, end_idx)."""
    if len(lumbar_acc_z) < int(fs * 2):
        return None
    sig = lumbar_acc_z - np.nanmean(lumbar_acc_z)
    sig = np.abs(sig)
    sig = np.nan_to_num(sig, nan=0.0)
    # First quarter has the sit-to-stand spike most reliably
    quarter = len(sig) // 3
    peak_idx = int(np.argmax(sig[:max(quarter, int(fs * 4))]))
    # Window [-0.8, +2.0]s around peak
    start = max(0, peak_idx - int(0.8 * fs))
    end = min(len(sig), peak_idx + int(2.0 * fs))
    return (start, peak_idx, end)


def _moore_freeze_index(shank_acc_ap: np.ndarray, fs: float = FS, win_s: float = 4.0, step_s: float = 0.5):
    """Sliding-window freeze index = power(3-8 Hz) / power(0.5-3 Hz). Returns (mean, max, p95, freeze_count)."""
    if len(shank_acc_ap) < int(fs * win_s):
        return dict(fi_mean=np.nan, fi_max=np.nan, fi_p95=np.nan, fi_count=np.nan)
    win = int(fs * win_s)
    step = int(fs * step_s)
    fis = []
    for i in range(0, len(shank_acc_ap) - win, step):
        w = shank_acc_ap[i:i + win]
        fi = _band_power_ratio(w, fs, (0.5, 3), (3, 8))
        if not np.isnan(fi):
            fis.append(fi)
    if not fis:
        return dict(fi_mean=np.nan, fi_max=np.nan, fi_p95=np.nan, fi_count=np.nan)
    fis_a = np.asarray(fis)
    return dict(
        fi_mean=float(np.mean(fis_a)),
        fi_max=float(np.max(fis_a)),
        fi_p95=float(np.percentile(fis_a, 95)),
        fi_count=int(np.sum(fis_a > 2.0)),
    )


def _detect_strides_from_shank(gyr_y: np.ndarray, fs: float = FS):
    """Find stride boundaries from shank gyro Y zero-crossings (heel-strike)."""
    if len(gyr_y) < int(fs * 2):
        return []
    s = gyr_y - np.nanmean(gyr_y)
    s = np.nan_to_num(s, nan=0.0)
    # Smooth lightly
    if len(s) > 51:
        s = sp_signal.savgol_filter(s, 51, 3)
    zc = np.where(np.diff(np.sign(s)) > 0)[0]
    # Filter: stride duration >= 0.4 s
    if len(zc) < 3:
        return []
    durations = np.diff(zc) / fs
    keep_mask = durations > 0.4
    zc_filtered = [zc[0]] + [zc[i + 1] for i in range(len(durations)) if keep_mask[i]]
    return zc_filtered


# ---------------------------------------------------------------------------
# Per-item extractors. Each returns a dict of feature_name -> float.
# ---------------------------------------------------------------------------

def _get_col(df: pd.DataFrame, sensor: str, group: str, axis: str):
    """Get a channel column with safe fallback."""
    candidates = [
        f"{sensor}_{group}_{axis}",
        f"{sensor}{group}{axis}",
    ]
    if group == "Euler":
        candidates = [f"{sensor}_{axis}"]  # Roll/Pitch/Yaw are bare-named
    for c in candidates:
        if c in df.columns:
            return df[c].to_numpy()
    return np.full(len(df), np.nan)


def extract_item_4_finger_tap(df: pd.DataFrame, task: str) -> dict:
    """Item 3.4 finger tap. Surrogate: wrist pronation 1.5-4 Hz spectral + arm-swing fatigability."""
    out = {}
    if "TUG" in task or "Pace" in task:
        for side, sensor in [("R", "R_Wrist"), ("L", "L_Wrist")]:
            gyr_y = _get_col(df, sensor, "Gyr", "Y")
            if np.all(np.isnan(gyr_y)):
                continue
            # 1.5-4 Hz pronation spectral
            out.update(_spectral_features(gyr_y, FS, f"i4_{side}_wrist_gyrY",
                                          bands=((1.5, 4), (4, 8))))
            # Arm-swing fatigability: amplitude of first vs last third
            third = len(gyr_y) // 3
            if third > 32:
                first = np.std(gyr_y[:third])
                last = np.std(gyr_y[-third:])
                out[f"i4_{side}_armswing_fatigue"] = float(last - first)
                out[f"i4_{side}_armswing_fatigue_rel"] = float((last - first) / (first + 1e-9))
    return out


def extract_item_5_hand_mvmt(df: pd.DataFrame, task: str) -> dict:
    """Item 3.5 hand mvmt. Phase-Locking Value Lumbar↔Wrist + arm-swing excursion asymmetry."""
    out = {}
    if "TUG" in task or "Pace" in task:
        lumbar_y = _get_col(df, "LowerBack", "Gyr", "Y")
        for side, sensor in [("R", "R_Wrist"), ("L", "L_Wrist")]:
            wrist_y = _get_col(df, sensor, "Gyr", "Y")
            wrist_acc_x = _get_col(df, sensor, "Acc", "X")
            wrist_acc_y = _get_col(df, sensor, "Acc", "Y")
            wrist_acc_z = _get_col(df, sensor, "Acc", "Z")
            if not np.all(np.isnan(wrist_y)) and not np.all(np.isnan(lumbar_y)):
                out[f"i5_{side}_plv_lumbar_wrist"] = _phase_locking_value(lumbar_y, wrist_y)
            for ax_name, ax_data in [("X", wrist_acc_x), ("Y", wrist_acc_y), ("Z", wrist_acc_z)]:
                if not np.all(np.isnan(ax_data)):
                    out.update(_safe_stats(ax_data, f"i5_{side}_acc{ax_name}"))
    return out


def extract_item_6_pronation_supination(df: pd.DataFrame, task: str) -> dict:
    """Item 3.6 pronation-supination. Relative UpperArm-Wrist yaw (we have Wrist; UpperArm absent).
    Use Wrist yaw stability + Roll dispersion as surrogate."""
    out = {}
    if "TUG" in task or "Pace" in task:
        for side, sensor in [("R", "R_Wrist"), ("L", "L_Wrist")]:
            yaw = _get_col(df, sensor, "Euler", "Yaw")
            roll = _get_col(df, sensor, "Euler", "Roll")
            if not np.all(np.isnan(yaw)):
                out.update(_safe_stats(yaw, f"i6_{side}_yaw"))
                # Frame-wrap-safe: convert to unit complex
                yaw_rad = np.deg2rad(yaw)
                out[f"i6_{side}_yaw_circular_var"] = 1 - float(np.abs(np.nanmean(np.exp(1j * yaw_rad))))
            if not np.all(np.isnan(roll)):
                out.update(_safe_stats(roll, f"i6_{side}_roll"))
            # Gyro X (radioulnar rotation surrogate)
            gx = _get_col(df, sensor, "Gyr", "X")
            if not np.all(np.isnan(gx)):
                out.update(_spectral_features(gx, FS, f"i6_{side}_gyrX",
                                              bands=((1.5, 4), (4, 8))))
    return out


def extract_item_7_toe_tap(df: pd.DataFrame, task: str) -> dict:
    """Item 3.7 toe tap. Foot Acc Z swing peak + cadence regularity + scattering on heel-strike."""
    out = {}
    if "Pace" in task or "TUG" in task or "Tandem" in task:
        for side, sensor, shank_sensor in [("R", "R_DorsalFoot", "R_LatShank"),
                                           ("L", "L_DorsalFoot", "L_LatShank")]:
            foot_z = _get_col(df, sensor, "Acc", "Z")
            free_z = _get_col(df, sensor, "FreeAcc", "U")
            shank_y = _get_col(df, shank_sensor, "Gyr", "Y")
            if not np.all(np.isnan(foot_z)):
                out.update(_safe_stats(foot_z, f"i7_{side}_foot_accZ"))
                # Find strides via shank Gyr Y
                strides = _detect_strides_from_shank(shank_y) if not np.all(np.isnan(shank_y)) else []
                if len(strides) >= 4:
                    durs = np.diff(strides) / FS
                    out[f"i7_{side}_stride_n"] = len(strides) - 1
                    out[f"i7_{side}_stride_dur_mean"] = float(np.mean(durs))
                    out[f"i7_{side}_stride_dur_cv"] = float(np.std(durs) / (np.mean(durs) + 1e-9))
                    # Per-stride peak-to-peak amplitude of foot Acc Z
                    p2ps = []
                    for k in range(len(strides) - 1):
                        seg = foot_z[strides[k]:strides[k + 1]]
                        if len(seg) > 8:
                            p2ps.append(np.ptp(seg))
                    if p2ps:
                        out[f"i7_{side}_p2p_mean"] = float(np.mean(p2ps))
                        out[f"i7_{side}_p2p_cv"] = float(np.std(p2ps) / (np.mean(p2ps) + 1e-9))
                        # Fatigability: first 3 vs last 3 stride peaks
                        if len(p2ps) >= 6:
                            out[f"i7_{side}_p2p_fatigue"] = float(np.mean(p2ps[-3:]) - np.mean(p2ps[:3]))
            if not np.all(np.isnan(free_z)):
                out.update(_spectral_features(free_z, FS, f"i7_{side}_freeZ",
                                              bands=((0.5, 3), (3, 8), (8, 15))))
    return out


def extract_item_8_leg_agility(df: pd.DataFrame, task: str) -> dict:
    """Item 3.8 leg agility. Shank Gyr Y swing-phase amplitude + heel vertical velocity RMS + tibial-Lumbar CRP."""
    out = {}
    if "Pace" in task or "TUG" in task:
        lumbar_pitch = _get_col(df, "LowerBack", "Euler", "Pitch")
        for side, shank, thigh in [("R", "R_LatShank", "R_MidLatThigh"),
                                   ("L", "L_LatShank", "L_MidLatThigh")]:
            sh_y = _get_col(df, shank, "Gyr", "Y")
            sh_pitch = _get_col(df, shank, "Euler", "Pitch")
            th_pitch = _get_col(df, thigh, "Euler", "Pitch")
            if not np.all(np.isnan(sh_y)):
                out.update(_safe_stats(sh_y, f"i8_{side}_shankGyrY"))
                out.update(_spectral_features(sh_y, FS, f"i8_{side}_shankGyrY"))
                # Per-stride amplitude
                strides = _detect_strides_from_shank(sh_y)
                if len(strides) >= 4:
                    amps = []
                    for k in range(len(strides) - 1):
                        seg = sh_y[strides[k]:strides[k + 1]]
                        if len(seg) > 8:
                            amps.append(np.ptp(seg))
                    if amps:
                        out[f"i8_{side}_amp_mean"] = float(np.mean(amps))
                        out[f"i8_{side}_amp_cv"] = float(np.std(amps) / (np.mean(amps) + 1e-9))
                        if len(amps) >= 6:
                            out[f"i8_{side}_amp_fatigue"] = float(np.mean(amps[-3:]) - np.mean(amps[:3]))
            # Tibial-Lumbar continuous relative phase (proxy via PLV)
            if not np.all(np.isnan(sh_pitch)) and not np.all(np.isnan(lumbar_pitch)):
                out[f"i8_{side}_crp_lumbar"] = _phase_locking_value(lumbar_pitch, sh_pitch)
            # Thigh-shank phase lag
            if not np.all(np.isnan(sh_pitch)) and not np.all(np.isnan(th_pitch)):
                out[f"i8_{side}_thigh_shank_plv"] = _phase_locking_value(th_pitch, sh_pitch)
    return out


def extract_item_9_chair_rise(df: pd.DataFrame, task: str) -> dict:
    """Item 3.9 arising from chair. APA magnitude + seat-off impulse + phase-space area."""
    out = {}
    if "TUG" not in task:
        return out
    lumbar_acc_z = _get_col(df, "LowerBack", "Acc", "Z")
    lumbar_free_u = _get_col(df, "LowerBack", "FreeAcc", "U")
    lumbar_pitch = _get_col(df, "LowerBack", "Euler", "Pitch")
    lumbar_gyr_y = _get_col(df, "LowerBack", "Gyr", "Y")
    xiph_pitch = _get_col(df, "Xiphoid", "Euler", "Pitch")
    seat_event = _detect_seat_off(lumbar_acc_z)
    if seat_event is None:
        return out
    start, peak, end = seat_event
    # Pre-seat-off APA window (0.5s before)
    apa_start = max(0, peak - int(0.5 * FS))
    apa_end = peak
    if apa_end > apa_start:
        # APA magnitude = lateral acceleration std in pre-window (LowerBack Acc Y)
        lumbar_acc_y = _get_col(df, "LowerBack", "Acc", "Y")
        if apa_end - apa_start > 4:
            out["i9_apa_lat_std"] = float(np.nanstd(lumbar_acc_y[apa_start:apa_end]))
            out["i9_apa_pitch_excur"] = float(np.nanmax(lumbar_pitch[apa_start:apa_end]) - np.nanmin(lumbar_pitch[apa_start:apa_end]))
    # Seat-off power impulse (peak ± 0.5s)
    impulse_start = max(0, peak - int(0.5 * FS))
    impulse_end = min(len(lumbar_free_u), peak + int(0.8 * FS))
    if impulse_end > impulse_start:
        seg = lumbar_free_u[impulse_start:impulse_end]
        if len(seg) > 4:
            out["i9_seat_impulse_max"] = float(np.nanmax(seg))
            out["i9_seat_impulse_int"] = float(np.nansum(np.abs(seg)) / FS)
            out["i9_seat_impulse_jerk_max"] = float(np.nanmax(np.abs(_jerk(seg, FS))))
    # Phase-space area: lumbar pitch vs gyr Y over [-0.8, +2.0]s
    if end > start + 8:
        out["i9_phase_space_area"] = _phase_space_area(lumbar_pitch[start:end], lumbar_gyr_y[start:end])
    # Rise smoothness via xiphoid pitch
    if not np.all(np.isnan(xiph_pitch)) and end > start + 8:
        seg = xiph_pitch[start:end]
        out["i9_xiph_pitch_jerk_int"] = float(np.nansum(np.abs(_jerk(seg, FS))) / FS)
    # Transition duration
    out["i9_transition_dur"] = float((end - start) / FS)
    # Vertical power peak
    if not np.all(np.isnan(lumbar_free_u)):
        out["i9_vert_power_peak_1s"] = float(pd.Series(lumbar_free_u).rolling(int(FS), min_periods=1).mean().max())
    return out


def extract_item_10_gait(df: pd.DataFrame, task: str) -> dict:
    """Item 3.10 gait. Cadence, stride length proxy, harmonic ratio, RQA-like determinism, en-bloc index."""
    out = {}
    if not ("Pace" in task or "TUG" in task or "Tandem" in task):
        return out
    lumbar_acc_y = _get_col(df, "LowerBack", "Acc", "Y")  # ML
    lumbar_acc_x = _get_col(df, "LowerBack", "Acc", "X")  # AP
    lumbar_acc_z = _get_col(df, "LowerBack", "Acc", "Z")  # vertical
    lumbar_yaw = _get_col(df, "LowerBack", "Euler", "Yaw")
    sh_y = _get_col(df, "L_LatShank", "Gyr", "Y")
    if not np.all(np.isnan(lumbar_acc_z)):
        out.update(_spectral_features(lumbar_acc_z, FS, "i10_lumbar_accZ"))
        out["i10_harmonic_ratio_z"] = _harmonic_ratio(lumbar_acc_z, FS)
    if not np.all(np.isnan(lumbar_acc_y)):
        out.update(_spectral_features(lumbar_acc_y, FS, "i10_lumbar_accY"))
        out["i10_harmonic_ratio_ml"] = _harmonic_ratio(lumbar_acc_y, FS)
        out["i10_lumbar_ap_sample_ent"] = _sample_entropy(lumbar_acc_y)
    if not np.all(np.isnan(lumbar_acc_x)):
        out["i10_lumbar_ml_sample_ent"] = _sample_entropy(lumbar_acc_x)
    # Cadence + stride regularity from shank Gyr Y
    strides = _detect_strides_from_shank(sh_y) if not np.all(np.isnan(sh_y)) else []
    if len(strides) >= 4:
        durs = np.diff(strides) / FS
        out["i10_n_strides"] = len(strides) - 1
        out["i10_stride_dur_mean"] = float(np.mean(durs))
        out["i10_stride_dur_cv"] = float(np.std(durs) / (np.mean(durs) + 1e-9))
        out["i10_cadence"] = float(60.0 / np.mean(durs)) if np.mean(durs) > 0 else np.nan
    # Yaw range = turn angle proxy
    if not np.all(np.isnan(lumbar_yaw)):
        yaw_rad = np.deg2rad(lumbar_yaw)
        unwrapped = np.unwrap(yaw_rad)
        out["i10_yaw_total_excur_deg"] = float(np.rad2deg(np.ptp(unwrapped)))
        # Yaw velocity for en-bloc index
        yv = np.diff(unwrapped) * FS
        if len(yv) > 8:
            out["i10_yaw_vel_max"] = float(np.max(np.abs(yv)))
            out["i10_yaw_vel_p95"] = float(np.percentile(np.abs(yv), 95))
    # En-bloc index: lumbar vs xiphoid yaw correlation during turns
    xiph_yaw = _get_col(df, "Xiphoid", "Euler", "Yaw")
    if not np.all(np.isnan(lumbar_yaw)) and not np.all(np.isnan(xiph_yaw)):
        try:
            corr = np.corrcoef(np.unwrap(np.deg2rad(lumbar_yaw)), np.unwrap(np.deg2rad(xiph_yaw)))[0, 1]
            out["i10_enbloc_yaw_corr"] = float(corr)
        except Exception:
            pass
    return out


def extract_item_11_fog(df: pd.DataFrame, task: str) -> dict:
    """Item 3.11 FoG. Adaptive Freezing Index (Moore) + APA-failure score + turn dwell."""
    out = {}
    if not ("Pace" in task or "TUG" in task or "Tandem" in task):
        return out
    for side, shank in [("R", "R_LatShank"), ("L", "L_LatShank")]:
        sh_acc_x = _get_col(df, shank, "Acc", "X")  # AP
        if not np.all(np.isnan(sh_acc_x)):
            d = _moore_freeze_index(sh_acc_x, FS, win_s=4.0, step_s=0.5)
            for k, v in d.items():
                out[f"i11_{side}_{k}"] = v
    # APA-failure score: Lumbar ML FreeAcc smoothness drops before freeze
    lumbar_free_n = _get_col(df, "LowerBack", "FreeAcc", "N")
    if not np.all(np.isnan(lumbar_free_n)):
        # Total ML excursion variability
        out.update(_spectral_features(lumbar_free_n, FS, "i11_lumbar_freeML"))
    # Turn dwell: low-cadence segments during gait
    sh_y = _get_col(df, "L_LatShank", "Gyr", "Y")
    if not np.all(np.isnan(sh_y)):
        strides = _detect_strides_from_shank(sh_y)
        if len(strides) >= 3:
            durs = np.diff(strides) / FS
            # Count strides > 1.5s = candidate freeze
            out["i11_long_stride_count"] = int(np.sum(durs > 1.5))
            out["i11_max_gap_s"] = float(np.max(durs)) if len(durs) > 0 else 0.0
            out["i11_freeze_burden"] = float(np.sum(durs[durs > 1.5]))
    # Lumbar yaw kurtosis during turns
    lumbar_yaw = _get_col(df, "LowerBack", "Euler", "Yaw")
    if not np.all(np.isnan(lumbar_yaw)):
        yv = np.diff(np.unwrap(np.deg2rad(lumbar_yaw))) * FS
        if len(yv) > 8:
            out["i11_yaw_vel_kurt"] = float(kurtosis(yv))
    return out


def extract_item_12_postural_stability(df: pd.DataFrame, task: str) -> dict:
    """Item 3.12 postural stability. Sway features, ankle-vs-hip strategy ratio, CoP."""
    out = {}
    if "Balance" not in task and "Tandem" not in task:
        return out
    # Lumbar sway
    lumbar_x = _get_col(df, "LowerBack", "Acc", "X")
    lumbar_y = _get_col(df, "LowerBack", "Acc", "Y")
    lumbar_pitch = _get_col(df, "LowerBack", "Euler", "Pitch")
    if not np.all(np.isnan(lumbar_x)) and not np.all(np.isnan(lumbar_y)):
        # 95% sway area = 2.4477 * sqrt(σx σy * sqrt(1-ρ²))
        x = lumbar_x[~np.isnan(lumbar_x)]
        y = lumbar_y[~np.isnan(lumbar_y)]
        n = min(len(x), len(y))
        if n > 16:
            sx, sy = np.std(x[:n]), np.std(y[:n])
            rho = np.corrcoef(x[:n], y[:n])[0, 1] if sx > 0 and sy > 0 else 0
            rho2 = max(0, 1 - rho ** 2)
            out["i12_sway_area_95"] = float(2.4477 * sx * sy * np.sqrt(rho2))
            out["i12_sway_vel_mean"] = float(np.mean(np.sqrt(np.diff(x[:n]) ** 2 + np.diff(y[:n]) ** 2) * FS))
        out["i12_sample_ent_x"] = _sample_entropy(lumbar_x)
        out["i12_sample_ent_y"] = _sample_entropy(lumbar_y)
    # Ankle-vs-hip strategy ratio: shank pitch var / lumbar pitch var
    for side, shank in [("R", "R_LatShank"), ("L", "L_LatShank")]:
        sh_pitch = _get_col(df, shank, "Euler", "Pitch")
        if not np.all(np.isnan(sh_pitch)) and not np.all(np.isnan(lumbar_pitch)):
            sh_var = np.nanvar(sh_pitch)
            lb_var = np.nanvar(lumbar_pitch)
            out[f"i12_{side}_ankle_hip_ratio"] = float(sh_var / (lb_var + 1e-9))
    # Frequency centroid stability
    if not np.all(np.isnan(lumbar_x)):
        # Sliding 10s window, dominant freq
        w = int(FS * 10)
        if len(lumbar_x) > 2 * w:
            f1 = _spectral_features(lumbar_x[:w], FS, "tmp")["tmp_dom_f"]
            f2 = _spectral_features(lumbar_x[-w:], FS, "tmp")["tmp_dom_f"]
            out["i12_freq_centroid_drift"] = float(abs(f2 - f1))
    # CoP from insole
    for side in ("L", "R"):
        cop_x = df.get(f"{side}CoP_X")
        cop_y = df.get(f"{side}CoP_Y")
        if cop_x is not None and cop_y is not None:
            cx = cop_x.to_numpy()
            cy = cop_y.to_numpy()
            if not np.all(np.isnan(cx)):
                out.update(_safe_stats(cx, f"i12_{side}_copX"))
                out.update(_safe_stats(cy, f"i12_{side}_copY"))
                # Path length
                pl = np.nansum(np.sqrt(np.diff(cx) ** 2 + np.diff(cy) ** 2))
                out[f"i12_{side}_cop_path"] = float(pl)
    return out


def extract_item_13_posture(df: pd.DataFrame, task: str) -> dict:
    """Item 3.13 posture. Time-above-flexion threshold + cervical-Lumbar delta + flexion fatigue slope."""
    out = {}
    # Use any task with sustained quiet periods: Balance, Tandem, pre-TUG
    if not ("Balance" in task or "Tandem" in task or "TUG" in task):
        return out
    lumbar_pitch = _get_col(df, "LowerBack", "Euler", "Pitch")
    xiph_pitch = _get_col(df, "Xiphoid", "Euler", "Pitch")
    forehead_pitch = _get_col(df, "Forehead", "Euler", "Pitch")
    # Time above flexion threshold (kyphosis cutoff)
    if not np.all(np.isnan(lumbar_pitch)):
        # Median pitch as anatomical baseline
        lp = lumbar_pitch[~np.isnan(lumbar_pitch)]
        if len(lp) > 16:
            base = np.percentile(lp, 50)
            for thr_deg in (5, 10, 15):
                mask = lp > base + thr_deg
                out[f"i13_time_above_flex_{thr_deg}"] = float(np.mean(mask))
        # Sustained median over central 60% of trial
        n = len(lp)
        out["i13_lumbar_pitch_med_central"] = float(np.median(lp[int(n * 0.2):int(n * 0.8)]))
        # Flexion fatigue slope: trend over time
        if n > 32:
            t = np.arange(n) / FS
            slope, _ = np.polyfit(t, lp, 1)
            out["i13_lumbar_flex_slope"] = float(slope)
    # Cervical-Lumbar delta (Forehead - Lumbar pitch)
    if not np.all(np.isnan(forehead_pitch)) and not np.all(np.isnan(lumbar_pitch)):
        delta = forehead_pitch - lumbar_pitch
        out.update(_safe_stats(delta[~np.isnan(delta)], "i13_cervical_lumbar_delta"))
    # Sternum-Lumbar delta
    if not np.all(np.isnan(xiph_pitch)) and not np.all(np.isnan(lumbar_pitch)):
        delta = xiph_pitch - lumbar_pitch
        out.update(_safe_stats(delta[~np.isnan(delta)], "i13_sternum_lumbar_delta"))
    # Vector magnitude of static FreeAcc in ENU frame
    e = _get_col(df, "LowerBack", "FreeAcc", "E")
    n_ = _get_col(df, "LowerBack", "FreeAcc", "N")
    u = _get_col(df, "LowerBack", "FreeAcc", "U")
    if not np.all(np.isnan(e)) and not np.all(np.isnan(n_)) and not np.all(np.isnan(u)):
        mag = np.sqrt(e ** 2 + n_ ** 2 + u ** 2)
        out.update(_safe_stats(mag, "i13_lumbar_freeENU_mag"))
    return out


def extract_item_14_body_brady(df: pd.DataFrame, task: str) -> dict:
    """Item 3.14 body bradykinesia. Global kinematic energy + spectral edge frequency 95% + multi-joint coupling."""
    out = {}
    # Global kinematic energy = sum of RMS(FreeAcc magnitude) across all 13 sensors
    energies = []
    for sensor in SENSORS:
        e = _get_col(df, sensor, "FreeAcc", "E")
        n_ = _get_col(df, sensor, "FreeAcc", "N")
        u = _get_col(df, sensor, "FreeAcc", "U")
        if not (np.all(np.isnan(e)) or np.all(np.isnan(n_)) or np.all(np.isnan(u))):
            mag = np.sqrt(e ** 2 + n_ ** 2 + u ** 2)
            rms = float(np.sqrt(np.nanmean(mag ** 2)))
            energies.append(rms)
            out[f"i14_{sensor}_freeENU_rms"] = rms
    if energies:
        out["i14_global_kin_energy"] = float(np.sum(energies))
        out["i14_kin_energy_max_sensor"] = float(np.max(energies))
        out["i14_kin_energy_min_sensor"] = float(np.min(energies))
        out["i14_kin_energy_disp"] = float(np.std(energies))
    # Spectral edge frequency 95% on Lumbar Acc
    lumbar_z = _get_col(df, "LowerBack", "Acc", "Z")
    if not np.all(np.isnan(lumbar_z)):
        out.update(_spectral_features(lumbar_z, FS, "i14_lumbar_z_spec"))
    # Multi-joint PLV matrix eigenvalues (proxy via top-3 variance of pairwise PLV)
    pitches = []
    for sensor in ["LowerBack", "Xiphoid", "L_LatShank", "R_LatShank", "L_MidLatThigh", "R_MidLatThigh"]:
        p = _get_col(df, sensor, "Euler", "Pitch")
        if not np.all(np.isnan(p)):
            pitches.append((sensor, p))
    if len(pitches) >= 3:
        plvs = []
        for i in range(len(pitches)):
            for j in range(i + 1, len(pitches)):
                plvs.append(_phase_locking_value(pitches[i][1], pitches[j][1]))
        plvs = [v for v in plvs if not np.isnan(v)]
        if plvs:
            out["i14_plv_mean"] = float(np.mean(plvs))
            out["i14_plv_std"] = float(np.std(plvs))
    return out


def extract_item_15_postural_tremor(df: pd.DataFrame, task: str) -> dict:
    """Item 3.15 postural tremor. 4-7 Hz wrist bandpower during static windows."""
    out = {}
    if "Balance" not in task and "Tandem" not in task:
        return out
    # First and last 5s of Balance/Tandem = candidate static
    n_full = len(df)
    quiet_idxs = []
    if n_full > int(FS * 10):
        quiet_idxs.append((0, int(FS * 5)))
        quiet_idxs.append((n_full - int(FS * 5), n_full))
    for side, sensor in [("R", "R_Wrist"), ("L", "L_Wrist")]:
        for ax in ("X", "Y", "Z"):
            full = _get_col(df, sensor, "Acc", ax)
            if np.all(np.isnan(full)):
                continue
            for q_i, (s, e) in enumerate(quiet_idxs):
                seg = full[s:e]
                if len(seg) > 16:
                    d = _spectral_features(seg, FS, f"i15_{side}_acc{ax}_q{q_i}",
                                           bands=((4, 7), (8, 12)))
                    out.update({k: v for k, v in d.items() if "bp_4_7" in k or "bp_8_12" in k})
    return out


def extract_item_16_kinetic_tremor(df: pd.DataFrame, task: str) -> dict:
    """Item 3.16 kinetic tremor. 5-8 Hz wrist during gait phases (deceleration)."""
    out = {}
    if not ("TUG" in task or "Pace" in task):
        return out
    for side, sensor in [("R", "R_Wrist"), ("L", "L_Wrist")]:
        for ax in ("X", "Y", "Z"):
            data = _get_col(df, sensor, "Acc", ax)
            if not np.all(np.isnan(data)):
                # 5-8 Hz bandpower
                d = _spectral_features(data, FS, f"i16_{side}_acc{ax}",
                                       bands=((5, 8), (8, 12)))
                out.update({k: v for k, v in d.items() if "bp_5_8" in k})
        # Gyr too
        for ax in ("X", "Y", "Z"):
            data = _get_col(df, sensor, "Gyr", ax)
            if not np.all(np.isnan(data)):
                d = _spectral_features(data, FS, f"i16_{side}_gyr{ax}",
                                       bands=((5, 8),))
                out.update({k: v for k, v in d.items() if "bp_5_8" in k})
    return out


def extract_item_17_18_rest_tremor(df: pd.DataFrame, task: str) -> dict:
    """Items 3.17 (amplitude) and 3.18 (constancy). 4-6 Hz wrist + foot during quiet windows."""
    out = {}
    if "Balance" not in task and "Tandem" not in task and "TUG" not in task:
        return out
    n_full = len(df)
    # Quiet candidate windows: first 5s of Balance, last 5s of Balance, first 3s of TUG (pre-rise)
    quiet_idxs = []
    if "Balance" in task and n_full > int(FS * 10):
        quiet_idxs += [(0, int(FS * 5)), (n_full - int(FS * 5), n_full)]
    if "TUG" in task and n_full > int(FS * 4):
        quiet_idxs.append((0, int(FS * 3)))
    # Tremor amplitude (item 17) features per limb in 4-6 Hz band
    for side, sensor in [("R", "R_Wrist"), ("L", "L_Wrist"),
                         ("Rf", "R_DorsalFoot"), ("Lf", "L_DorsalFoot")]:
        bp4_6_per_window = []
        for q_i, (s, e) in enumerate(quiet_idxs):
            for ax in ("X", "Y", "Z"):
                seg = _get_col(df, sensor, "Acc", ax)[s:e]
                if len(seg) > 16:
                    d = _spectral_features(seg, FS, f"_t",
                                           bands=((4, 6), (3, 8)))
                    if not np.isnan(d["_t_bp_4_6"]):
                        bp4_6_per_window.append(d["_t_bp_4_6"])
                        out[f"i1718_{side}_acc{ax}_q{q_i}_bp4_6"] = d["_t_bp_4_6"]
        if bp4_6_per_window:
            out[f"i1718_{side}_bp4_6_max"] = float(np.max(bp4_6_per_window))
            out[f"i1718_{side}_bp4_6_mean"] = float(np.mean(bp4_6_per_window))
    # Constancy (item 18): tremor duty cycle = % windows with 4-6 Hz power > threshold
    # Use sliding 1s windows on R_Wrist Acc magnitude
    for side, sensor in [("R", "R_Wrist"), ("L", "L_Wrist")]:
        ax_x = _get_col(df, sensor, "Acc", "X")
        ax_y = _get_col(df, sensor, "Acc", "Y")
        ax_z = _get_col(df, sensor, "Acc", "Z")
        if any(np.all(np.isnan(a)) for a in (ax_x, ax_y, ax_z)):
            continue
        mag = np.sqrt(ax_x ** 2 + ax_y ** 2 + ax_z ** 2)
        win = int(FS * 1)
        step = int(FS * 0.5)
        active = []
        for i in range(0, len(mag) - win, step):
            w = mag[i:i + win]
            if len(w) < 16:
                continue
            d = _spectral_features(w, FS, "_t", bands=((4, 6),))
            v = d["_t_bp_4_6"]
            if not np.isnan(v):
                active.append(v)
        if active:
            arr = np.asarray(active)
            thr = max(np.percentile(arr, 80), 0.01)
            duty = float(np.mean(arr > thr))
            out[f"i1718_{side}_tremor_duty_p80"] = duty
            # Burst length distribution
            mask = arr > thr
            bursts = []
            cur = 0
            for m in mask:
                if m:
                    cur += 1
                else:
                    if cur > 0:
                        bursts.append(cur)
                    cur = 0
            if cur > 0:
                bursts.append(cur)
            if bursts:
                out[f"i1718_{side}_burst_n"] = float(len(bursts))
                out[f"i1718_{side}_burst_med"] = float(np.median(bursts))
                out[f"i1718_{side}_burst_max"] = float(np.max(bursts))
    return out


# ---------------------------------------------------------------------------
# File-level dispatch
# ---------------------------------------------------------------------------

EXTRACTORS = {
    4: extract_item_4_finger_tap,
    5: extract_item_5_hand_mvmt,
    6: extract_item_6_pronation_supination,
    7: extract_item_7_toe_tap,
    8: extract_item_8_leg_agility,
    9: extract_item_9_chair_rise,
    10: extract_item_10_gait,
    11: extract_item_11_fog,
    12: extract_item_12_postural_stability,
    13: extract_item_13_posture,
    14: extract_item_14_body_brady,
    15: extract_item_15_postural_tremor,
    16: extract_item_16_kinetic_tremor,
    1718: extract_item_17_18_rest_tremor,
}


def process_file(path: str) -> dict:
    bn = os.path.basename(path).replace(".csv", "")
    parts = bn.split("_", 1)
    sid = parts[0]
    task = parts[1] if len(parts) > 1 else "?"
    # Skip mat tasks (walkway-only) — we want body-worn IMU
    if task.endswith("_mat") or task.endswith("_matTURN"):
        return None
    try:
        df = pd.read_csv(path)
    except Exception as e:
        print(f"FAIL read {path}: {e}", file=sys.stderr)
        return None
    if "Time" not in df.columns or len(df) < 50:
        return None
    out = {"sid": sid, "task": task, "n_samples": len(df)}
    for item_id, fn in EXTRACTORS.items():
        try:
            d = fn(df, task)
            out.update(d)
        except Exception as e:
            print(f"FAIL extract item {item_id} on {bn}: {e}", file=sys.stderr)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv_dir", required=True)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--out_recording", required=True)
    p.add_argument("--out_subject", required=True)
    p.add_argument("--limit", type=int, default=0, help="cap N files for smoke test")
    args = p.parse_args()

    files = sorted(glob.glob(os.path.join(args.csv_dir, "*.csv")))
    # Skip mat-tasks
    files = [f for f in files if not (
        os.path.basename(f).endswith("_mat.csv")
        or os.path.basename(f).endswith("_matTURN.csv")
    )]
    if args.limit:
        files = files[:args.limit]
    print(f"Processing {len(files)} CSV files with {args.workers} workers...", flush=True)

    if args.workers <= 1:
        rows = [process_file(f) for f in files]
    else:
        with mp.Pool(args.workers) as pool:
            rows = []
            for i, r in enumerate(pool.imap_unordered(process_file, files, chunksize=4)):
                rows.append(r)
                if (i + 1) % 50 == 0:
                    print(f"  {i+1}/{len(files)} done", flush=True)
    rows = [r for r in rows if r is not None]
    print(f"Built {len(rows)} per-recording rows.", flush=True)

    df_rec = pd.DataFrame(rows)
    df_rec.to_csv(args.out_recording, index=False)
    print(f"Wrote {args.out_recording} ({df_rec.shape})", flush=True)

    # Aggregate per subject: mean across tasks for each feature; also keep per-task subset for items that need a specific task
    feature_cols = [c for c in df_rec.columns if c not in ("sid", "task", "n_samples")]
    subj_rows = []
    for sid, grp in df_rec.groupby("sid"):
        row = {"sid": sid}
        for col in feature_cols:
            arr = grp[col].dropna().values
            if len(arr):
                row[f"{col}_mean"] = float(np.mean(arr))
                row[f"{col}_max"] = float(np.max(arr))
                row[f"{col}_min"] = float(np.min(arr))
        subj_rows.append(row)
    df_subj = pd.DataFrame(subj_rows)
    df_subj.to_csv(args.out_subject, index=False)
    print(f"Wrote {args.out_subject} ({df_subj.shape})", flush=True)


if __name__ == "__main__":
    main()
