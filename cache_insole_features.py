"""Insole-specific UPDRS-III feature cache for items 7, 12, 14.

Reads each PD raw CSV once, extracts insole-pressure / CoP / GRF / insole-IMU
features that are NOT covered by the body-worn IMU cache (cache_per_item_features_v2.py).

Channels exploited (per CSV — all on the active GPU slave):
  Time                                    — string "X.XX sec", parsed to float seconds
  L Foot Pressure / R Foot Pressure       — single scalar / side
  LPressure1..16, RPressure1..16          — 16 plantar sensors / side
  Linsole:Acc_{X,Y,Z} / Linsole:Gyr_{X,Y,Z} — separate insole IMU
  Rinsole:Acc_{X,Y,Z} / Rinsole:Gyr_{X,Y,Z}
  LTotalForce, RTotalForce                — total ground reaction force / side
  LCoP_X, LCoP_Y, RCoP_X, RCoP_Y          — CoP coordinates / side

Item-targeted feature blocks:
  i7_  toe-tap                — heel-strike force decay, toe/heel pressure ratio,
                                CoP path / stride, stance-time asymmetry,
                                toe-off impulse, heel-strike impact
  i12_ postural stability     — 95% CoP confidence-ellipse area, path length,
                                mean / max velocity, frequency centroid (ML/AP),
                                CoP_X sample entropy, ML/AP std ratio,
                                bilateral cross-correlation max
  i14_ body bradykinesia      — total kinetic effort (∫ TotalForce dt),
                                force CV, TUG total duration,
                                32-sensor mean pressure, plantar PCA explained-variance ratios

Outputs:
  results/insole_recording_features.csv   — per (subject, task) row
  results/insole_subj_features.csv        — per subject (mean/max/min across tasks)

Usage:
  python3 cache_insole_features.py --workers 16 \
      --csv_dir "data/raw/weargait-pd/PD PARTICIPANTS/CSV files" \
      --out_recording results/insole_recording_features.csv \
      --out_subject   results/insole_subj_features.csv

Smoke test (20 files):
  python3 cache_insole_features.py --workers 4 --limit 20 \
      --csv_dir ... --out_recording /tmp/ins_rec.csv --out_subject /tmp/ins_subj.csv
"""
from __future__ import annotations

import argparse
import glob
import multiprocessing as mp
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import signal as sp_signal
from scipy.stats import iqr, kurtosis, skew

warnings.filterwarnings("ignore")

FS = 100.0  # Hz, sampling rate

# Plantar pressure sensor groups (16 sensors / side, anatomical layout from Moticon Insole 3 spec).
# Sensors 1-3 ≈ heel, 4-7 ≈ midfoot, 8-12 ≈ forefoot, 13-16 ≈ toes.
HEEL_IDX = [1, 2, 3]
MIDFOOT_IDX = [4, 5, 6, 7]
FOREFOOT_IDX = [8, 9, 10, 11, 12]
TOE_IDX = [13, 14, 15, 16]


# ---------------------------------------------------------------------------
# Generic primitives (kept compact; mirrors cache_per_item_features_v2.py
# but does not import it so this script is self-contained).
# ---------------------------------------------------------------------------


def _parse_time_seconds(time_col: pd.Series) -> np.ndarray:
    """Time is stored as e.g. "0.01 sec" — strip and convert to float seconds."""
    s = time_col.astype(str).str.replace(" sec", "", regex=False)
    return pd.to_numeric(s, errors="coerce").to_numpy(dtype=np.float64)


def _safe_stats(x: np.ndarray, prefix: str) -> dict:
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


def _spectral_centroid(x: np.ndarray, fs: float = FS) -> float:
    if x.size < 32 or np.all(np.isnan(x)):
        return np.nan
    x = x - np.nanmean(x)
    x = np.nan_to_num(x, nan=0.0)
    nperseg = min(256, len(x))
    f, p = sp_signal.welch(x, fs=fs, nperseg=nperseg)
    p = p + 1e-12
    return float(np.sum(f * p) / np.sum(p))


def _sample_entropy(x: np.ndarray, m: int = 2, r_factor: float = 0.2) -> float:
    if len(x) < 50 or np.all(np.isnan(x)):
        return np.nan
    if len(x) > 500:
        x = x[:: int(np.ceil(len(x) / 500))]
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


def _detect_strides_force(total_force: np.ndarray, fs: float = FS, min_dur_s: float = 0.4):
    """Stride boundaries from rising edges of TotalForce above mid-threshold.

    Returns a list of (heel_strike_idx, toe_off_idx) per stride.
    """
    if total_force.size < int(fs * 1.5) or np.all(np.isnan(total_force)):
        return []
    f = np.nan_to_num(total_force, nan=0.0)
    if len(f) > 51:
        f = sp_signal.savgol_filter(f, 51, 3)
    if f.max() < 1e-6:
        return []
    thr = 0.3 * np.percentile(f, 95)  # 30 % of typical peak
    above = f > thr
    # Find rising / falling edges
    rises = np.where(np.diff(above.astype(int)) > 0)[0]
    falls = np.where(np.diff(above.astype(int)) < 0)[0]
    strides = []
    for hs in rises:
        # Find next fall
        cand = falls[falls > hs]
        if len(cand) == 0:
            continue
        toe = cand[0]
        if (toe - hs) / fs < min_dur_s:
            continue
        strides.append((int(hs), int(toe)))
    return strides


def _confidence_ellipse_area(x: np.ndarray, y: np.ndarray) -> float:
    """95 % confidence-ellipse area = 2.4477 * σx * σy * sqrt(1-ρ²)."""
    m = ~(np.isnan(x) | np.isnan(y))
    if m.sum() < 16:
        return np.nan
    x_ = x[m]
    y_ = y[m]
    sx = np.std(x_)
    sy = np.std(y_)
    if sx < 1e-9 or sy < 1e-9:
        return 0.0
    rho = np.corrcoef(x_, y_)[0, 1]
    rho2 = max(0.0, 1.0 - rho ** 2)
    return float(2.4477 * sx * sy * np.sqrt(rho2))


def _path_length(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 2 or np.all(np.isnan(x)):
        return np.nan
    dx = np.diff(np.nan_to_num(x, nan=0.0))
    dy = np.diff(np.nan_to_num(y, nan=0.0))
    return float(np.sum(np.sqrt(dx ** 2 + dy ** 2)))


def _xcorr_max(x: np.ndarray, y: np.ndarray, max_lag: int = 50) -> float:
    """Max cross-correlation magnitude over [-max_lag, +max_lag] samples."""
    m = ~(np.isnan(x) | np.isnan(y))
    if m.sum() < 64:
        return np.nan
    a = x[m] - np.nanmean(x[m])
    b = y[m] - np.nanmean(y[m])
    sa = np.std(a)
    sb = np.std(b)
    if sa < 1e-9 or sb < 1e-9:
        return 0.0
    n = min(len(a), len(b))
    a = a[:n] / sa
    b = b[:n] / sb
    lags = range(-max_lag, max_lag + 1)
    best = 0.0
    for k in lags:
        if k < 0:
            v = np.mean(a[-k:n] * b[: n + k])
        elif k > 0:
            v = np.mean(a[: n - k] * b[k:n])
        else:
            v = np.mean(a * b)
        if abs(v) > abs(best):
            best = v
    return float(best)


# ---------------------------------------------------------------------------
# Per-item extractors
# ---------------------------------------------------------------------------


def extract_item_7_insole(df: pd.DataFrame, task: str) -> dict:
    """Toe-tap surrogates: heel-strike force decay, toe/heel pressure ratio,
    CoP path / stride, stance-time asymmetry, toe-off and heel-strike impulses."""
    out: dict[str, float] = {}
    if not ("Pace" in task or "TUG" in task or "Tandem" in task):
        return out
    for side in ("L", "R"):
        force = df.get(f"{side}TotalForce")
        cop_x = df.get(f"{side}CoP_X")
        cop_y = df.get(f"{side}CoP_Y")
        if force is None:
            continue
        force_a = force.to_numpy(dtype=np.float64)
        cop_x_a = cop_x.to_numpy(dtype=np.float64) if cop_x is not None else None
        cop_y_a = cop_y.to_numpy(dtype=np.float64) if cop_y is not None else None
        if np.all(np.isnan(force_a)):
            continue

        # Toe / heel pressure regions
        heel_cols = [f"{side}Pressure{i}" for i in HEEL_IDX if f"{side}Pressure{i}" in df.columns]
        toe_cols = [f"{side}Pressure{i}" for i in TOE_IDX if f"{side}Pressure{i}" in df.columns]
        forefoot_cols = [f"{side}Pressure{i}" for i in FOREFOOT_IDX if f"{side}Pressure{i}" in df.columns]

        if heel_cols and toe_cols:
            heel_p = df[heel_cols].to_numpy(dtype=np.float64).mean(axis=1)
            toe_p = df[toe_cols].to_numpy(dtype=np.float64).mean(axis=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = toe_p / (heel_p + 1e-6)
            out[f"i7_{side}_toe_heel_ratio_mean"] = float(np.nanmean(ratio))
            out[f"i7_{side}_toe_heel_ratio_p95"] = float(np.nanpercentile(ratio, 95))
            out[f"i7_{side}_toe_heel_ratio_std"] = float(np.nanstd(ratio))
        if forefoot_cols and heel_cols:
            ff_p = df[forefoot_cols].to_numpy(dtype=np.float64).mean(axis=1)
            heel_p2 = df[heel_cols].to_numpy(dtype=np.float64).mean(axis=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio2 = ff_p / (heel_p2 + 1e-6)
            out[f"i7_{side}_forefoot_heel_ratio_mean"] = float(np.nanmean(ratio2))

        # Strides
        strides = _detect_strides_force(force_a)
        if not strides:
            continue
        n_strides = len(strides)
        out[f"i7_{side}_n_strides"] = float(n_strides)
        # Stance time
        stance_durs = np.array([(toe - hs) / FS for hs, toe in strides])
        out[f"i7_{side}_stance_mean"] = float(np.mean(stance_durs))
        out[f"i7_{side}_stance_cv"] = float(np.std(stance_durs) / (np.mean(stance_durs) + 1e-9))

        # Per-stride peak force, toe-off impulse, heel-strike impact
        peaks, hs_imps, to_imps = [], [], []
        cop_paths = []
        for hs, toe in strides:
            seg = force_a[hs:toe]
            if len(seg) < 4:
                continue
            peaks.append(np.nanmax(seg))
            # Heel strike: first 0.1 s ≈ 10 samples
            hs_n = min(int(0.1 * FS), len(seg))
            hs_imps.append(np.nansum(seg[:hs_n]) / FS)
            # Toe off: last 0.2 s ≈ 20 samples
            to_n = min(int(0.2 * FS), len(seg))
            to_imps.append(np.nansum(seg[-to_n:]) / FS)
            # CoP path / stride
            if cop_x_a is not None and cop_y_a is not None:
                pl = _path_length(cop_x_a[hs:toe], cop_y_a[hs:toe])
                if not np.isnan(pl):
                    cop_paths.append(pl)
        if peaks:
            out[f"i7_{side}_peak_mean"] = float(np.mean(peaks))
            out[f"i7_{side}_peak_cv"] = float(np.std(peaks) / (np.mean(peaks) + 1e-9))
            # Decay across strides: linear slope
            if len(peaks) >= 4:
                t = np.arange(len(peaks))
                slope, _ = np.polyfit(t, peaks, 1)
                out[f"i7_{side}_peak_decay"] = float(slope)
                out[f"i7_{side}_peak_fatigue"] = float(np.mean(peaks[-3:]) - np.mean(peaks[:3]))
        if hs_imps:
            out[f"i7_{side}_hs_impulse_mean"] = float(np.mean(hs_imps))
            out[f"i7_{side}_hs_impulse_cv"] = float(np.std(hs_imps) / (np.mean(hs_imps) + 1e-9))
        if to_imps:
            out[f"i7_{side}_to_impulse_mean"] = float(np.mean(to_imps))
            out[f"i7_{side}_to_impulse_cv"] = float(np.std(to_imps) / (np.mean(to_imps) + 1e-9))
        if cop_paths:
            out[f"i7_{side}_cop_path_per_stride_mean"] = float(np.mean(cop_paths))
            out[f"i7_{side}_cop_path_per_stride_cv"] = float(np.std(cop_paths) / (np.mean(cop_paths) + 1e-9))

    # Stance-time asymmetry (L vs R)
    l_st = out.get("i7_L_stance_mean")
    r_st = out.get("i7_R_stance_mean")
    if l_st is not None and r_st is not None and l_st > 0 and r_st > 0:
        out["i7_stance_asym"] = float(abs(l_st - r_st) / max(l_st, r_st))
    l_pk = out.get("i7_L_peak_mean")
    r_pk = out.get("i7_R_peak_mean")
    if l_pk is not None and r_pk is not None and (l_pk + r_pk) > 0:
        out["i7_peak_asym"] = float(abs(l_pk - r_pk) / (l_pk + r_pk))
    return out


def extract_item_12_insole(df: pd.DataFrame, task: str) -> dict:
    """Postural stability: CoP-based sway in Balance / Tandem trials."""
    out: dict[str, float] = {}
    if "Balance" not in task and "Tandem" not in task:
        return out
    cops: dict[str, np.ndarray] = {}
    for side in ("L", "R"):
        cx = df.get(f"{side}CoP_X")
        cy = df.get(f"{side}CoP_Y")
        if cx is None or cy is None:
            continue
        cx_a = cx.to_numpy(dtype=np.float64)
        cy_a = cy.to_numpy(dtype=np.float64)
        if np.all(np.isnan(cx_a)) or np.all(np.isnan(cy_a)):
            continue
        cops[side] = (cx_a, cy_a)
        out[f"i12_{side}_cop_ellipse_area"] = _confidence_ellipse_area(cx_a, cy_a)
        out[f"i12_{side}_cop_path"] = _path_length(cx_a, cy_a)
        # Velocity (samples → mm/s assuming insole units consistent within subject)
        dt = 1.0 / FS
        m = ~(np.isnan(cx_a) | np.isnan(cy_a))
        if m.sum() > 16:
            vx = np.diff(cx_a[m]) / dt
            vy = np.diff(cy_a[m]) / dt
            v = np.sqrt(vx ** 2 + vy ** 2)
            out[f"i12_{side}_cop_vel_mean"] = float(np.mean(v))
            out[f"i12_{side}_cop_vel_max"] = float(np.max(v))
            out[f"i12_{side}_cop_vel_p95"] = float(np.percentile(v, 95))
        # Frequency centroid per axis
        out[f"i12_{side}_cop_x_freq_centroid"] = _spectral_centroid(cx_a)
        out[f"i12_{side}_cop_y_freq_centroid"] = _spectral_centroid(cy_a)
        # Sample entropy (CoP_X — ML axis)
        out[f"i12_{side}_cop_x_sampen"] = _sample_entropy(cx_a)
        out[f"i12_{side}_cop_y_sampen"] = _sample_entropy(cy_a)
        # ML/AP std ratio (lateral vs anterior–posterior preference)
        cx_clean = cx_a[~np.isnan(cx_a)]
        cy_clean = cy_a[~np.isnan(cy_a)]
        if len(cx_clean) > 16 and len(cy_clean) > 16 and np.std(cy_clean) > 1e-9:
            out[f"i12_{side}_ml_ap_std_ratio"] = float(np.std(cx_clean) / np.std(cy_clean))
        out.update(_safe_stats(cx_a, f"i12_{side}_cop_x"))
        out.update(_safe_stats(cy_a, f"i12_{side}_cop_y"))

    # Bilateral synchrony: L-vs-R CoP_X cross-correlation
    if "L" in cops and "R" in cops:
        l_cx, l_cy = cops["L"]
        r_cx, r_cy = cops["R"]
        out["i12_LR_xcorr_x_max"] = _xcorr_max(l_cx, r_cx, max_lag=50)
        out["i12_LR_xcorr_y_max"] = _xcorr_max(l_cy, r_cy, max_lag=50)
        # Mean COP across both feet (composite COP)
        m = ~(np.isnan(l_cx) | np.isnan(r_cx) | np.isnan(l_cy) | np.isnan(r_cy))
        if m.sum() > 64:
            mid_x = 0.5 * (l_cx[m] + r_cx[m])
            mid_y = 0.5 * (l_cy[m] + r_cy[m])
            out["i12_mid_cop_ellipse_area"] = _confidence_ellipse_area(mid_x, mid_y)
            out["i12_mid_cop_path"] = _path_length(mid_x, mid_y)
            dt = 1.0 / FS
            v = np.sqrt(np.diff(mid_x) ** 2 + np.diff(mid_y) ** 2) / dt
            out["i12_mid_cop_vel_mean"] = float(np.mean(v))
            out["i12_mid_cop_vel_max"] = float(np.max(v))
    return out


def extract_item_14_insole(df: pd.DataFrame, task: str) -> dict:
    """Body bradykinesia: global force economy + plantar PCA + TUG duration."""
    out: dict[str, float] = {}

    # Total kinetic effort (∫|TotalForce|dt) over the recording.
    l_force = df.get("LTotalForce")
    r_force = df.get("RTotalForce")
    if l_force is not None and r_force is not None:
        l_a = l_force.to_numpy(dtype=np.float64)
        r_a = r_force.to_numpy(dtype=np.float64)
        if not (np.all(np.isnan(l_a)) and np.all(np.isnan(r_a))):
            total = np.nansum(np.abs(l_a) + np.abs(r_a)) / FS
            duration = float(np.sum(~(np.isnan(l_a) & np.isnan(r_a)))) / FS
            out[f"i14_{task[:6]}_force_int"] = float(total)
            out[f"i14_{task[:6]}_force_int_per_s"] = float(total / max(duration, 1e-3))
            # CV of summed force
            with np.errstate(invalid="ignore"):
                summed = np.nan_to_num(l_a, nan=0.0) + np.nan_to_num(r_a, nan=0.0)
            mean_f = float(np.nanmean(summed))
            std_f = float(np.nanstd(summed))
            if abs(mean_f) > 1e-9:
                out[f"i14_{task[:6]}_force_cv"] = float(std_f / mean_f)

    # Plantar pressure: average across all 32 sensors and sensor-coordination via PCA
    plantar_cols = [f"{side}Pressure{i}" for side in ("L", "R") for i in range(1, 17) if f"{side}Pressure{i}" in df.columns]
    if len(plantar_cols) >= 16:
        P = df[plantar_cols].to_numpy(dtype=np.float64)
        # Global mean / std
        global_mean = float(np.nanmean(P))
        global_std = float(np.nanstd(P))
        out[f"i14_{task[:6]}_plantar_mean"] = global_mean
        out[f"i14_{task[:6]}_plantar_std"] = global_std
        # PCA explained variance ratios (first 3 components)
        # Drop rows with any NaN to feed PCA cleanly.
        mask = ~np.any(np.isnan(P), axis=1)
        if mask.sum() > 32:
            Pc = P[mask]
            Pc = Pc - Pc.mean(axis=0)
            try:
                # Use SVD instead of sklearn to keep deps minimal
                _, s, _ = np.linalg.svd(Pc, full_matrices=False)
                var = s ** 2
                if var.sum() > 1e-9:
                    var_ratio = var / var.sum()
                    for k in range(min(3, len(var_ratio))):
                        out[f"i14_{task[:6]}_plantar_pca_pc{k+1}"] = float(var_ratio[k])
            except np.linalg.LinAlgError:
                pass

    # TUG total duration — proven literature feature (Mirelman 2018).
    if "TUG" in task:
        time_arr = _parse_time_seconds(df["Time"]) if "Time" in df.columns else None
        if time_arr is not None and not np.all(np.isnan(time_arr)):
            out["i14_TUG_duration"] = float(np.nanmax(time_arr) - np.nanmin(time_arr))

    # Insole IMU magnitudes (separate from body-worn IMU cache)
    for side in ("L", "R"):
        ax = df.get(f"{side}insole:Acc_X")
        ay = df.get(f"{side}insole:Acc_Y")
        az = df.get(f"{side}insole:Acc_Z")
        if ax is None or ay is None or az is None:
            continue
        a = np.sqrt(
            np.nan_to_num(ax.to_numpy(dtype=np.float64), nan=0.0) ** 2
            + np.nan_to_num(ay.to_numpy(dtype=np.float64), nan=0.0) ** 2
            + np.nan_to_num(az.to_numpy(dtype=np.float64), nan=0.0) ** 2
        )
        out.update(_safe_stats(a, f"i14_{task[:6]}_{side}insole_acc_mag"))
    return out


# ---------------------------------------------------------------------------
# File-level dispatch
# ---------------------------------------------------------------------------


EXTRACTORS = {
    7: extract_item_7_insole,
    12: extract_item_12_insole,
    14: extract_item_14_insole,
}


def process_file(path: str) -> dict | None:
    bn = os.path.basename(path).replace(".csv", "")
    parts = bn.split("_", 1)
    sid = parts[0]
    task = parts[1] if len(parts) > 1 else "?"
    # Skip mat-only tasks (walkway-only, no insole data of interest)
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
            out.update(fn(df, task))
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
    files = [f for f in files if not (
        os.path.basename(f).endswith("_mat.csv")
        or os.path.basename(f).endswith("_matTURN.csv")
    )]
    if args.limit:
        files = files[: args.limit]
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

    feature_cols = [c for c in df_rec.columns if c not in ("sid", "task", "n_samples")]
    subj_rows = []
    for sid, grp in df_rec.groupby("sid"):
        row = {"sid": sid}
        for col in feature_cols:
            arr = grp[col].dropna().to_numpy()
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
