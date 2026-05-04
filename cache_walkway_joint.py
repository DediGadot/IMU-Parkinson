"""Walkway gait parameters + joint angles from sensor-pair Eulers.

Walkway features per recording:
  - Stride length, step length, step width (CV)
  - Stride/step time, cadence
  - Foot placement variability
  - Pressure level CV across footfalls

Joint angles (from Euler pitch differences):
  - Knee = Thigh pitch - Shank pitch
  - Ankle = Shank pitch - DorsalFoot pitch
  - Hip = LowerBack pitch - Thigh pitch
  - TrunkSpine = Xiphoid pitch - LowerBack pitch
  - Cervical = Forehead pitch - Xiphoid pitch
For each joint: range, mean (cyclic), std, jerk RMS, swing-phase amplitude.

Outputs:
  results/walkway_joint_subj.csv (per-subject features)
  results/walkway_joint_rec.csv (per-recording features)
"""
from __future__ import annotations

import argparse
import glob
import multiprocessing as mp
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal as sp_signal

warnings.filterwarnings("ignore")

FS = 100.0


def _safe_stats(x: np.ndarray, prefix: str) -> dict:
    if x.size == 0 or np.all(np.isnan(x)):
        return {f"{prefix}_{k}": np.nan for k in ("mean", "std", "rng", "cv", "p95", "p05")}
    x = x[~np.isnan(x)]
    m = float(np.mean(x))
    return {
        f"{prefix}_mean": m,
        f"{prefix}_std": float(np.std(x)),
        f"{prefix}_rng": float(np.ptp(x)),
        f"{prefix}_cv": float(np.std(x) / (abs(m) + 1e-9)),
        f"{prefix}_p95": float(np.percentile(x, 95)),
        f"{prefix}_p05": float(np.percentile(x, 5)),
    }


def extract_walkway(df: pd.DataFrame, task: str) -> dict:
    """Walkway gait parameters from foot-placement events."""
    out = {}
    if "Walkway_X" not in df.columns:
        return out
    wx = df["Walkway_X"].to_numpy()
    wy = df["Walkway_Y"].to_numpy()
    wpl = df["WalkwayPressureLevel"].to_numpy() if "WalkwayPressureLevel" in df.columns else np.array([])
    wf = df["WalkwayFoot"].astype(str).to_numpy() if "WalkwayFoot" in df.columns else np.array([])
    t = df["Time"].to_numpy() if "Time" in df.columns else np.arange(len(df)) / FS

    # Find footfall events: rows where Walkway_X is non-NaN AND non-zero AND WalkwayFoot is L or R
    valid = (~np.isnan(wx)) & (wx != 0)
    if wf.size == len(wx):
        valid = valid & np.isin(wf, ["L", "R", "Left", "Right", "left", "right"])
    if not valid.any():
        return out

    idx = np.where(valid)[0]
    # Aggregate consecutive samples of same footfall — walkway data is held over sample steps
    # Find footfall onsets: where valid changes from False to True OR the foot label changes
    onsets = [idx[0]]
    for i in range(1, len(idx)):
        if idx[i] != idx[i-1] + 1 or (wf.size and wf[idx[i]] != wf[idx[i-1]]):
            onsets.append(idx[i])
    onsets = np.array(onsets)
    if len(onsets) < 4:
        return out

    # Per-footfall summary
    foot_x = wx[onsets]
    foot_y = wy[onsets]
    foot_t = t[onsets] if len(t) >= max(onsets) + 1 else np.arange(len(onsets)) / FS
    foot_press = wpl[onsets] if wpl.size else np.array([])
    foot_label = wf[onsets] if wf.size else np.array([])

    out["wkw_n_footfalls"] = int(len(onsets))

    # Stride time = consecutive same-foot intervals; step time = consecutive any-foot intervals
    if len(foot_t) >= 2:
        step_times = np.diff(foot_t)
        out.update(_safe_stats(step_times, "wkw_step_time"))
    if foot_label.size:
        for side in ("L", "R", "Left", "Right"):
            mask = foot_label == side
            if mask.sum() >= 2:
                t_side = foot_t[mask]
                stride_times = np.diff(t_side)
                if len(stride_times):
                    sa = "L" if side[0].upper() == "L" else "R"
                    out.update(_safe_stats(stride_times, f"wkw_stride_time_{sa}"))

    # Step length / width — consecutive footfall distances
    if len(foot_x) >= 2:
        step_lengths = np.abs(np.diff(foot_x))
        step_widths = np.abs(np.diff(foot_y))
        out.update(_safe_stats(step_lengths, "wkw_step_len"))
        out.update(_safe_stats(step_widths, "wkw_step_width"))
        out["wkw_total_path_x"] = float(np.abs(foot_x[-1] - foot_x[0]))
    if foot_press.size:
        out.update(_safe_stats(foot_press.astype(float), "wkw_press"))
    return out


def extract_joints(df: pd.DataFrame, task: str) -> dict:
    """Joint angles from Euler pitch differences."""
    out = {}
    pairs = [
        ("knee_R", "R_MidLatThigh_Pitch", "R_LatShank_Pitch"),
        ("knee_L", "L_MidLatThigh_Pitch", "L_LatShank_Pitch"),
        ("ankle_R", "R_LatShank_Pitch", "R_DorsalFoot_Pitch"),
        ("ankle_L", "L_LatShank_Pitch", "L_DorsalFoot_Pitch"),
        ("hip_R", "LowerBack_Pitch", "R_MidLatThigh_Pitch"),
        ("hip_L", "LowerBack_Pitch", "L_MidLatThigh_Pitch"),
        ("trunk_spine", "Xiphoid_Pitch", "LowerBack_Pitch"),
        ("cervical", "Forehead_Pitch", "Xiphoid_Pitch"),
    ]
    for name, prox, dist in pairs:
        if prox not in df.columns or dist not in df.columns:
            continue
        a = df[prox].to_numpy() - df[dist].to_numpy()
        if np.all(np.isnan(a)):
            continue
        out.update(_safe_stats(a, f"joint_{name}"))
        # Jerk RMS
        if len(a) > 4:
            jerk = np.diff(a, n=2)
            jerk = jerk[~np.isnan(jerk)]
            if len(jerk):
                out[f"joint_{name}_jerk_rms"] = float(np.sqrt(np.mean(jerk ** 2)))
        # Spectral edge frequency 95%
        x = a[~np.isnan(a)]
        if len(x) >= 64:
            x = x - x.mean()
            f, p = sp_signal.welch(x, fs=FS, nperseg=min(256, len(x)))
            ps = p / (p.sum() + 1e-12)
            cs = np.cumsum(ps)
            sef95_idx = np.searchsorted(cs, 0.95)
            sef95 = float(f[min(sef95_idx, len(f) - 1)])
            out[f"joint_{name}_sef95"] = sef95
            out[f"joint_{name}_dom_f"] = float(f[np.argmax(p)])
    return out


def process_file(path: str) -> dict:
    bn = os.path.basename(path).replace(".csv", "")
    parts = bn.split("_", 1)
    sid = parts[0]
    task = parts[1] if len(parts) > 1 else "?"
    if task.endswith("_mat") or task.endswith("_matTURN"):
        return None
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception as e:
        print(f"FAIL read {path}: {e}", file=sys.stderr)
        return None
    if "Time" not in df.columns or len(df) < 50:
        return None
    out = {"sid": sid, "task": task, "n_samples": len(df)}
    try:
        out.update(extract_walkway(df, task))
    except Exception as e:
        print(f"walkway extract fail {bn}: {e}", file=sys.stderr)
    try:
        out.update(extract_joints(df, task))
    except Exception as e:
        print(f"joint extract fail {bn}: {e}", file=sys.stderr)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv_dir", required=True)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--out_rec", required=True)
    p.add_argument("--out_subj", required=True)
    args = p.parse_args()

    files = sorted(glob.glob(os.path.join(args.csv_dir, "*.csv")))
    files = [f for f in files if not f.endswith("_mat.csv") and not f.endswith("_matTURN.csv")]
    print(f"Processing {len(files)} non-mat files with {args.workers} workers...")

    with mp.Pool(args.workers) as pool:
        rows = []
        for i, r in enumerate(pool.imap_unordered(process_file, files, chunksize=4)):
            rows.append(r)
            if (i + 1) % 100 == 0:
                print(f"  {i+1}/{len(files)} done")
    rows = [r for r in rows if r is not None]
    print(f"Built {len(rows)} per-recording rows.")
    df_rec = pd.DataFrame(rows)
    df_rec.to_csv(args.out_rec, index=False)
    print(f"Wrote {args.out_rec} ({df_rec.shape})")

    # Per-subject aggregation
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
    df_subj.to_csv(args.out_subj, index=False)
    print(f"Wrote {args.out_subj} ({df_subj.shape})")


if __name__ == "__main__":
    main()
