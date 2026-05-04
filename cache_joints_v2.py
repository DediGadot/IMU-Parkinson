"""Quaternion+event-locked joint kinematics cache (joints_v2).

Iter 9 v1 NULLED because:
  1. Used absolute Euler differences (wrap-around issues at +-180 — not actually a problem
     for sagittal Pitch which is bounded +-90, but flagged in mission spec).
  2. Per-recording aggregation washed out per-stride signal.
  3. No event-locked extraction (heel-strike, toe-off, mid-swing).

This script fixes all 3 flaws:
  - Joint angle = (Pitch_proximal - Pitch_distal) using np.unwrap as safety. Pitch is
    bounded +-90 from MTW Awinda Kalman so wrap is theoretically impossible, but
    np.unwrap is cheap insurance.
  - Heel-strike (HS) and toe-off (TO) detected per-side from Foot Contact rising/falling edges.
  - For each STRIDE (HS_n -> HS_{n+1} same side), extract:
        - knee, ankle, hip flexion at HS, TO, mid-swing
        - swing-phase ROM, stance-phase ROM
        - peak knee flexion in swing
        - angular velocity (rad/s) at HS, TO, mid-swing
        - angular jerk RMS during stance + during swing
        - Joint angle smoothness via SPARC-like reciprocal of L2 of normalised PSD
  - Per-subject aggregation: across all strides from all walking tasks (SelfPace,
    HurriedPace, TandemGait, TUG), compute mean/std/cv/p90 + decline-by-thirds
    (mean of last-third minus mean of first-third) for bradykinesia decay.
  - Output: results/joints_v2_subj.csv (per-subject ~150-300 features)

Quaternion vs Euler-unwrap decision:
  Inspected NLS002 SelfPace: OriInc q0 ~ 0.99999 (incremental, per-sample, drift if
  integrated over 38s). Pitch bounded [-90, +max] without wrap on real recordings.
  Decision: USE Pitch directly with np.unwrap safety. Avoids cumulative quaternion
  integration drift. Document this as design choice.
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
DT = 1.0 / FS

# Joints: (name, proximal_sensor, distal_sensor)
JOINTS = [
    ("knee_R", "R_MidLatThigh", "R_LatShank"),
    ("knee_L", "L_MidLatThigh", "L_LatShank"),
    ("ankle_R", "R_LatShank", "R_DorsalFoot"),
    ("ankle_L", "L_LatShank", "L_DorsalFoot"),
    ("hip_R", "LowerBack", "R_MidLatThigh"),
    ("hip_L", "LowerBack", "L_MidLatThigh"),
    ("trunk", "Xiphoid", "LowerBack"),
    ("cervical", "Forehead", "Xiphoid"),
]

# Side-specific joints used for stride-locked metrics (driven by R/L Foot Contact)
SIDE_JOINTS = {
    "R": [("knee_R", "knee"), ("ankle_R", "ankle"), ("hip_R", "hip")],
    "L": [("knee_L", "knee"), ("ankle_L", "ankle"), ("hip_L", "hip")],
}

# Tasks contributing strides
GAIT_TASKS = ("SelfPace", "HurriedPace", "TandemGait", "TUG")


def _safe_stat(arr: np.ndarray, name: str, decline: bool = False) -> dict:
    """Mean/std/cv/p90 + optional decline-thirds metric."""
    a = np.asarray(arr, dtype=float)
    a = a[~np.isnan(a)]
    out = {}
    if len(a) == 0:
        for k in ("mean", "std", "cv", "p10", "p90"):
            out[f"{name}_{k}"] = np.nan
        if decline:
            out[f"{name}_decline"] = np.nan
        return out
    m = float(np.mean(a))
    s = float(np.std(a))
    out[f"{name}_mean"] = m
    out[f"{name}_std"] = s
    out[f"{name}_cv"] = float(s / (abs(m) + 1e-9))
    out[f"{name}_p10"] = float(np.percentile(a, 10))
    out[f"{name}_p90"] = float(np.percentile(a, 90))
    if decline and len(a) >= 6:
        third = max(1, len(a) // 3)
        first = a[:third].mean()
        last = a[-third:].mean()
        out[f"{name}_decline"] = float(last - first)
    elif decline:
        out[f"{name}_decline"] = np.nan
    return out


def detect_strides(fc: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Detect heel-strikes (HS), toe-offs (TO), and stride start indices from Foot
    Contact binary signal.

    Returns:
        hs_indices: array of HS sample indices (rising edges)
        to_indices: array of TO sample indices (falling edges)
        strides:    array of [start_idx, to_idx, end_idx] triplets where
                    end_idx is next-HS, defining one full stride per row.
    """
    fc = np.asarray(fc, dtype=int)
    if fc.size < 10:
        return np.array([]), np.array([]), np.zeros((0, 3), dtype=int)
    diff = np.diff(fc)
    hs = np.where(diff > 0)[0] + 1  # rising edge: 0->1 = HS
    to = np.where(diff < 0)[0] + 1  # falling edge: 1->0 = TO
    if len(hs) < 2:
        return hs, to, np.zeros((0, 3), dtype=int)
    strides = []
    for i in range(len(hs) - 1):
        start = hs[i]
        end = hs[i + 1]
        # Find the TO that occurs between start and end
        to_in = to[(to > start) & (to < end)]
        if len(to_in) == 0:
            continue
        to_idx = int(to_in[0])
        # Sanity: stride duration in [0.4s, 2.5s]
        dur = (end - start) * DT
        if dur < 0.4 or dur > 2.5:
            continue
        strides.append([int(start), to_idx, int(end)])
    return hs, to, np.array(strides, dtype=int) if strides else np.zeros((0, 3), dtype=int)


def joint_angle(df: pd.DataFrame, prox: str, dist: str) -> np.ndarray | None:
    """Joint angle in degrees: prox_pitch - dist_pitch, with np.unwrap safety.

    Returns:
        Array same length as df, with NaN preserved at original NaN positions.
    """
    p_col = f"{prox}_Pitch"
    d_col = f"{dist}_Pitch"
    if p_col not in df.columns or d_col not in df.columns:
        return None
    p = df[p_col].to_numpy(dtype=float)
    d = df[dist + "_Pitch"].to_numpy(dtype=float)
    # Track NaNs
    nan_mask = np.isnan(p) | np.isnan(d)
    # np.unwrap requires no NaN; replace temporarily, then restore
    p_safe = np.where(nan_mask, 0.0, p)
    d_safe = np.where(nan_mask, 0.0, d)
    # Unwrap each separately in radians, convert back to degrees
    p_rad = np.unwrap(np.deg2rad(p_safe))
    d_rad = np.unwrap(np.deg2rad(d_safe))
    angle_rad = p_rad - d_rad
    angle_deg = np.rad2deg(angle_rad)
    angle_deg[nan_mask] = np.nan
    return angle_deg


def stride_features_one_side(
    angles: dict[str, np.ndarray],
    strides: np.ndarray,
    side: str,
) -> list[dict]:
    """Per-stride feature dict list. angles = {'knee': arr, 'ankle': arr, 'hip': arr}.
    strides = (n_strides, 3) [start_HS, to, end_HS]."""
    out: list[dict] = []
    for s_idx in range(len(strides)):
        st, to_idx, en = strides[s_idx]
        stride_dur = (en - st) * DT
        # Mid-swing = midpoint between TO and end_HS (next HS same side)
        mid_swing = int(to_idx + (en - to_idx) // 2)
        # Stance = HS to TO; Swing = TO to next HS
        feat = {"side": side, "stride_dur": stride_dur,
                "stance_dur": (to_idx - st) * DT,
                "swing_dur": (en - to_idx) * DT}
        for jkey in ("knee", "ankle", "hip"):
            a = angles.get(jkey)
            if a is None:
                continue
            # Event-locked angles
            ang_hs = a[st] if st < len(a) else np.nan
            ang_to = a[to_idx] if to_idx < len(a) else np.nan
            ang_ms = a[mid_swing] if mid_swing < len(a) else np.nan
            feat[f"{jkey}_ang_hs"] = float(ang_hs)
            feat[f"{jkey}_ang_to"] = float(ang_to)
            feat[f"{jkey}_ang_ms"] = float(ang_ms)
            # ROM phases
            if to_idx > st + 1:
                stance_seg = a[st:to_idx]
                stance_seg = stance_seg[~np.isnan(stance_seg)]
                if len(stance_seg) >= 3:
                    feat[f"{jkey}_rom_stance"] = float(np.ptp(stance_seg))
                    feat[f"{jkey}_max_stance"] = float(np.max(stance_seg))
                    feat[f"{jkey}_min_stance"] = float(np.min(stance_seg))
                    # Angular jerk RMS (2nd deriv) during stance
                    if len(stance_seg) > 4:
                        jrk = np.diff(stance_seg, n=2) / (DT * DT)
                        feat[f"{jkey}_jerk_rms_stance"] = float(np.sqrt(np.mean(jrk * jrk)))
            if en > to_idx + 1:
                swing_seg = a[to_idx:en]
                swing_seg = swing_seg[~np.isnan(swing_seg)]
                if len(swing_seg) >= 3:
                    feat[f"{jkey}_rom_swing"] = float(np.ptp(swing_seg))
                    feat[f"{jkey}_max_swing"] = float(np.max(swing_seg))
                    feat[f"{jkey}_min_swing"] = float(np.min(swing_seg))
                    feat[f"{jkey}_peak_swing"] = float(np.max(np.abs(swing_seg - swing_seg[0])))
                    if len(swing_seg) > 4:
                        jrk = np.diff(swing_seg, n=2) / (DT * DT)
                        feat[f"{jkey}_jerk_rms_swing"] = float(np.sqrt(np.mean(jrk * jrk)))
            # Angular velocity at events (deg/s) — central diff with edge guards
            for evname, idx in (("hs", st), ("to", to_idx), ("ms", mid_swing)):
                lo, hi = max(0, idx - 1), min(len(a) - 1, idx + 1)
                if hi > lo + 1 and not np.isnan(a[hi]) and not np.isnan(a[lo]):
                    omega = (a[hi] - a[lo]) / ((hi - lo) * DT)
                    feat[f"{jkey}_omega_{evname}"] = float(omega)
            # Total stride ROM
            full = a[st:en]
            full = full[~np.isnan(full)]
            if len(full) >= 3:
                feat[f"{jkey}_rom_full"] = float(np.ptp(full))
        out.append(feat)
    return out


def trunk_axial_features(df: pd.DataFrame, strides_R: np.ndarray, strides_L: np.ndarray) -> dict:
    """Aggregated trunk-pitch (axial) features over all gait windows in this recording.
    Less event-locked because trunk doesn't have a stride-defining HS, but stride-windowed."""
    out = {}
    angle_trunk = joint_angle(df, "Xiphoid", "LowerBack")
    angle_cerv = joint_angle(df, "Forehead", "Xiphoid")
    # Concatenate stride windows from both sides
    windows: list[np.ndarray] = []
    for strides in (strides_R, strides_L):
        for st, _, en in strides:
            windows.append(np.arange(st, en))
    if not windows:
        return out
    idx = np.concatenate(windows) if windows else np.array([], dtype=int)
    if len(idx) < 50:
        return out
    for ang, name in ((angle_trunk, "trunk"), (angle_cerv, "cervical")):
        if ang is None:
            continue
        seg = ang[idx]
        seg = seg[~np.isnan(seg)]
        if len(seg) < 50:
            continue
        out[f"{name}_pitch_mean"] = float(np.mean(seg))
        out[f"{name}_pitch_std"] = float(np.std(seg))
        out[f"{name}_pitch_p90"] = float(np.percentile(seg, 90))
        out[f"{name}_pitch_p10"] = float(np.percentile(seg, 10))
        # Spectral centroid (rad-Hz)
        seg0 = seg - seg.mean()
        f, p = sp_signal.welch(seg0, fs=FS, nperseg=min(256, len(seg0)))
        if p.sum() > 0:
            cent = float(np.sum(f * p) / np.sum(p))
            out[f"{name}_pitch_centroid"] = cent
    return out


def process_file(path: str) -> list[dict] | None:
    """Return list of stride-feature dicts (one per stride) tagged with sid+task+side."""
    bn = os.path.basename(path).replace(".csv", "")
    parts = bn.split("_", 1)
    sid = parts[0]
    task = parts[1] if len(parts) > 1 else "?"
    # Skip pure walkway-mat / turn-only files; keep main gait + TUG
    if not any(task.startswith(t) for t in GAIT_TASKS):
        return None
    if "_mat" in task or "_matTURN" in task:
        return None
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception as e:
        print(f"FAIL read {path}: {e}", file=sys.stderr, flush=True)
        return None
    if "L Foot Contact" not in df.columns or "R Foot Contact" not in df.columns:
        return None
    if len(df) < 100:
        return None

    # Per-side strides
    fc_R = df["R Foot Contact"].fillna(0).to_numpy()
    fc_L = df["L Foot Contact"].fillna(0).to_numpy()
    _, _, strides_R = detect_strides(fc_R)
    _, _, strides_L = detect_strides(fc_L)

    if len(strides_R) == 0 and len(strides_L) == 0:
        return None

    # Per-side joint angles
    angles_R = {}
    angles_L = {}
    for jname, prox, dist in JOINTS:
        a = joint_angle(df, prox, dist)
        if a is None:
            continue
        if jname.endswith("_R"):
            angles_R[jname.rsplit("_", 1)[0]] = a
        elif jname.endswith("_L"):
            angles_L[jname.rsplit("_", 1)[0]] = a
    # Stride feature dicts per side
    rows: list[dict] = []
    for s_feats in stride_features_one_side(angles_R, strides_R, "R"):
        s_feats["sid"] = sid
        s_feats["task"] = task
        rows.append(s_feats)
    for s_feats in stride_features_one_side(angles_L, strides_L, "L"):
        s_feats["sid"] = sid
        s_feats["task"] = task
        rows.append(s_feats)
    # Augment last row with trunk-axial features per recording
    if rows:
        trunk_feat = trunk_axial_features(df, strides_R, strides_L)
        if trunk_feat:
            # Stash on a sentinel row marked side=trunk
            trunk_row = {"sid": sid, "task": task, "side": "trunk"}
            trunk_row.update(trunk_feat)
            rows.append(trunk_row)
    return rows


def aggregate_per_subject(stride_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-stride features to per-subject features."""
    # Separate trunk sentinel rows from stride rows
    trunk_df = stride_df[stride_df["side"] == "trunk"].copy()
    walk_df = stride_df[stride_df["side"].isin(["L", "R"])].copy()

    feat_cols_walk = [c for c in walk_df.columns
                      if c not in ("sid", "task", "side") and walk_df[c].dtype in (np.float64, np.float32, float)]
    feat_cols_trunk = [c for c in trunk_df.columns
                       if c not in ("sid", "task", "side") and trunk_df[c].dtype in (np.float64, np.float32, float)]

    rows = []
    sids = sorted(stride_df["sid"].unique())
    for sid in sids:
        row = {"sid": sid}
        sub_walk = walk_df[walk_df["sid"] == sid]
        sub_trunk = trunk_df[trunk_df["sid"] == sid]
        # Walk features: aggregate across all strides (both sides + all tasks)
        for col in feat_cols_walk:
            arr = sub_walk[col].dropna().to_numpy()
            row.update(_safe_stat(arr, col, decline=True))
        # Per-side aggregates (R only / L only) — captures asymmetry potential without
        # the L-R signed cancellation problem.
        for side in ("R", "L"):
            sub_side = sub_walk[sub_walk["side"] == side]
            for col in feat_cols_walk:
                arr = sub_side[col].dropna().to_numpy()
                row.update(_safe_stat(arr, f"{side}_{col}", decline=False))
        # Trunk features: average across recordings for this subject
        for col in feat_cols_trunk:
            arr = sub_trunk[col].dropna().to_numpy()
            if len(arr):
                row[f"trunk_agg_{col}"] = float(np.mean(arr))
        # Stride-count metadata
        row["n_strides_total"] = int(len(sub_walk))
        row["n_strides_R"] = int(len(sub_walk[sub_walk["side"] == "R"]))
        row["n_strides_L"] = int(len(sub_walk[sub_walk["side"] == "L"]))
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv_dir", required=True)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--out_strides", required=True)
    p.add_argument("--out_subj", required=True)
    args = p.parse_args()

    files = sorted(glob.glob(os.path.join(args.csv_dir, "*.csv")))
    files = [f for f in files
             if not f.endswith("_mat.csv") and not f.endswith("_matTURN.csv")
             and any(t in os.path.basename(f) for t in GAIT_TASKS)]
    print(f"Processing {len(files)} gait CSV files with {args.workers} workers...", flush=True)

    all_rows: list[dict] = []
    with mp.Pool(args.workers) as pool:
        for i, r in enumerate(pool.imap_unordered(process_file, files, chunksize=4)):
            if r is not None:
                all_rows.extend(r)
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(files)} files done; cumulative stride rows: {len(all_rows)}", flush=True)

    print(f"Total stride/trunk rows: {len(all_rows)}", flush=True)
    if not all_rows:
        print("ERROR: no stride rows extracted", file=sys.stderr)
        sys.exit(1)

    stride_df = pd.DataFrame(all_rows)
    stride_df.to_csv(args.out_strides, index=False)
    print(f"Wrote {args.out_strides} ({stride_df.shape})", flush=True)

    subj_df = aggregate_per_subject(stride_df)
    subj_df.to_csv(args.out_subj, index=False)
    print(f"Wrote {args.out_subj} ({subj_df.shape})", flush=True)
    print(f"Subjects with strides: {len(subj_df)}; non-NaN feature columns: "
          f"{sum(subj_df.iloc[:, 1:].notna().any(axis=0))}", flush=True)


if __name__ == "__main__":
    main()
