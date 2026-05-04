"""Stride-locked late-fusion feature cache.

Iter-9 insole was nulled because we used recording-level mean/max/min aggregation
of long-window features. Agent 1 explicitly recommended *per-stride* / *per-event*
tokenization with heel-strike-aligned mini-windows on plantar-sensor envelopes.

This cache builds:
  Phase A: stride event detection from `L Foot Contact` / `R Foot Contact` binary events
           Each STRIDE = HS_n -> HS_{n+1} on the SAME foot.
           STANCE = HS -> TO. SWING = TO -> next HS.
           Reject strides shorter than 0.4 s or longer than 2.5 s.

  Phase B: per-stride feature vector (each stride is a "token")
           - Insole: peak HS force (first 100 ms of stance), peak TO force (last 100 ms),
                     forefoot/heel pressure ratio at mid-stance, CoP path length (stance),
                     CoP_X/Y range (stance), max LTotalForce/RTotalForce.
           - Body IMU at stride boundaries: Lumbar Acc-Z impact spike at HS,
                     Shank Gyr-Y peak swing velocity, Foot Acc-Z peak (TO),
                     Thigh Pitch range during swing, Shank Pitch at HS.
           - Stride morphology: stride/swing/stance duration, swing/stance ratio,
                     double-support proxy (overlap of L-stance & R-stance).
           - Bilateral asymmetry (per-stride pair, when matchable).

  Phase C: per-subject aggregation
           Mean, std, CV (std/mean), p5, p95 across strides for each stride feature.
           Decay slope (regression of stride-feat vs stride-index — fatigability).
           First-vs-last difference (mean of first 3 strides minus mean of last 3).

Output:
  results/stride_locked_subj.csv

Usage:
  python3 cache_stride_locked.py --workers 12 \
      --csv_dir "data/raw/weargait-pd/PD PARTICIPANTS/CSV files" \
      --out results/stride_locked_subj.csv

Smoke test (10 files):
  python3 cache_stride_locked.py --workers 4 --limit 10 \
      --csv_dir ... --out /tmp/stride_locked_smoke.csv
"""
from __future__ import annotations

import argparse
import glob
import multiprocessing as mp
import os
import sys
import warnings
from typing import Sequence

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

FS = 100.0  # Hz, sampling rate
MIN_STRIDE_S = 0.4
MAX_STRIDE_S = 2.5

# Stride-relevant tasks. Skip Balance/TandemGait (no proper strides), skip _mat/_matTURN.
GAIT_TASKS = ("SelfPace", "HurriedPace", "TUG", "TandemGait")

HEEL_IDX = [1, 2, 3]
MIDFOOT_IDX = [4, 5, 6, 7]
FOREFOOT_IDX = [8, 9, 10, 11, 12]
TOE_IDX = [13, 14, 15, 16]


# ─── Time parsing ────────────────────────────────────────────────────────────


def _parse_time_seconds(time_col: pd.Series) -> np.ndarray:
    s = time_col.astype(str).str.replace(" sec", "", regex=False)
    return pd.to_numeric(s, errors="coerce").to_numpy(dtype=np.float64)


# ─── Phase A: stride detection from binary Foot Contact events ───────────────


def _binary_to_events(contact: np.ndarray) -> tuple[list[int], list[int]]:
    """Return (heel_strike_indices, toe_off_indices) from binary contact signal.
    HS = rising edge (0 -> 1), TO = falling edge (1 -> 0).
    """
    if contact.size < 4:
        return [], []
    c = (contact > 0.5).astype(np.int8)
    diff = np.diff(c)
    hs = (np.where(diff == 1)[0] + 1).tolist()
    to = (np.where(diff == -1)[0] + 1).tolist()
    return hs, to


def _strides_from_events(hs: Sequence[int], to: Sequence[int]) -> list[dict]:
    """Build stride dicts.

    Each stride: HS_n -> HS_{n+1}, with stance = HS_n -> TO_first(>HS_n).
    """
    strides = []
    if len(hs) < 2:
        return strides
    to_arr = np.asarray(to)
    for i in range(len(hs) - 1):
        hs_i = hs[i]
        hs_next = hs[i + 1]
        # First TO after this HS
        cands = to_arr[to_arr > hs_i]
        if len(cands) == 0:
            continue
        toe_i = int(cands[0])
        if toe_i >= hs_next:
            continue  # malformed: stance crosses the next HS
        stride_dur_s = (hs_next - hs_i) / FS
        if stride_dur_s < MIN_STRIDE_S or stride_dur_s > MAX_STRIDE_S:
            continue
        stance_dur_s = (toe_i - hs_i) / FS
        swing_dur_s = (hs_next - toe_i) / FS
        if stance_dur_s <= 0 or swing_dur_s <= 0:
            continue
        strides.append({
            "hs_idx": hs_i,
            "to_idx": toe_i,
            "next_hs_idx": hs_next,
            "stride_dur": stride_dur_s,
            "stance_dur": stance_dur_s,
            "swing_dur": swing_dur_s,
        })
    return strides


# ─── Phase B: per-stride feature vector ──────────────────────────────────────


def _safe_float(x) -> float:
    try:
        v = float(x)
        if np.isnan(v) or np.isinf(v):
            return np.nan
        return v
    except (TypeError, ValueError):
        return np.nan


def _segment(arr: np.ndarray | None, lo: int, hi: int) -> np.ndarray:
    if arr is None or arr.size == 0:
        return np.array([])
    lo = max(0, lo)
    hi = min(arr.size, hi)
    if hi <= lo:
        return np.array([])
    s = arr[lo:hi]
    if np.all(np.isnan(s)):
        return np.array([])
    return s[~np.isnan(s)]


def _path_len(x: np.ndarray, y: np.ndarray, lo: int, hi: int) -> float:
    if x is None or y is None:
        return np.nan
    lo = max(0, lo); hi = min(min(len(x), len(y)), hi)
    if hi - lo < 4:
        return np.nan
    sx = x[lo:hi]; sy = y[lo:hi]
    m = ~(np.isnan(sx) | np.isnan(sy))
    if m.sum() < 4:
        return np.nan
    sx = sx[m]; sy = sy[m]
    if sx.size < 2:
        return np.nan
    dx = np.diff(sx); dy = np.diff(sy)
    return _safe_float(np.sum(np.sqrt(dx ** 2 + dy ** 2)))


def _per_stride_features(
    strides: list[dict],
    side: str,
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute per-stride feature rows for one side.

    Each row = one stride. Columns are per-stride scalar features.
    """
    if not strides:
        return pd.DataFrame()

    # Pre-fetch arrays we will read often
    def _arr(col: str) -> np.ndarray | None:
        if col in df.columns:
            return df[col].to_numpy(dtype=np.float64)
        return None

    force = _arr(f"{side}TotalForce")
    cop_x = _arr(f"{side}CoP_X")
    cop_y = _arr(f"{side}CoP_Y")

    heel_cols = [f"{side}Pressure{i}" for i in HEEL_IDX if f"{side}Pressure{i}" in df.columns]
    toe_cols = [f"{side}Pressure{i}" for i in TOE_IDX if f"{side}Pressure{i}" in df.columns]
    forefoot_cols = [f"{side}Pressure{i}" for i in FOREFOOT_IDX if f"{side}Pressure{i}" in df.columns]
    midfoot_cols = [f"{side}Pressure{i}" for i in MIDFOOT_IDX if f"{side}Pressure{i}" in df.columns]
    heel_p = df[heel_cols].to_numpy(dtype=np.float64).mean(axis=1) if heel_cols else None
    toe_p = df[toe_cols].to_numpy(dtype=np.float64).mean(axis=1) if toe_cols else None
    forefoot_p = df[forefoot_cols].to_numpy(dtype=np.float64).mean(axis=1) if forefoot_cols else None
    midfoot_p = df[midfoot_cols].to_numpy(dtype=np.float64).mean(axis=1) if midfoot_cols else None

    # Body IMU at stride boundaries
    lumbar_acc_z = _arr("Lumbar_Acc_Z")
    sternum_acc_z = _arr("Sternum_Acc_Z")
    shank_gyr_y = _arr(f"{side}_LatShank_Gyr_Y")
    shank_pitch = _arr(f"{side}_LatShank_Pitch")
    thigh_pitch = _arr(f"{side}_MidLatThigh_Pitch")
    foot_acc_z = _arr(f"{side}_DorsalFoot_Acc_Z")
    insole_acc_z = _arr(f"{side}insole:Acc_Z")
    insole_gyr_y = _arr(f"{side}insole:Gyr_Y")

    n_hs100 = max(int(0.10 * FS), 1)  # 10 samples
    n_to100 = max(int(0.10 * FS), 1)

    rows = []
    for k, s in enumerate(strides):
        hs = s["hs_idx"]; toe = s["to_idx"]; nxt = s["next_hs_idx"]
        row: dict[str, float] = {
            "stride_idx": k,
            "hs_idx": hs,
            "to_idx": toe,
            "stride_dur": s["stride_dur"],
            "stance_dur": s["stance_dur"],
            "swing_dur": s["swing_dur"],
            "swing_stance_ratio": s["swing_dur"] / max(s["stance_dur"], 1e-6),
        }

        # ── Insole: peak forces in early stance (HS) and late stance (TO) ──
        if force is not None:
            # Early-stance peak force (heel-strike impact, first 100 ms of stance)
            early = _segment(force, hs, hs + n_hs100)
            row["peak_hs_force"] = _safe_float(np.max(early)) if early.size else np.nan
            # Late-stance peak force (toe-off, last 100 ms of stance)
            late = _segment(force, max(toe - n_to100, hs), toe)
            row["peak_to_force"] = _safe_float(np.max(late)) if late.size else np.nan
            # Stance peak total force
            stance = _segment(force, hs, toe)
            row["max_stance_force"] = _safe_float(np.max(stance)) if stance.size else np.nan
            # Stance impulse (∫ F dt)
            row["stance_impulse"] = _safe_float(np.sum(stance) / FS) if stance.size else np.nan

        # ── Mid-stance forefoot/heel pressure ratio ──
        mid = (hs + toe) // 2
        win_lo = max(hs, mid - 5); win_hi = min(toe, mid + 5)
        if forefoot_p is not None and heel_p is not None and win_hi > win_lo:
            ff_seg = _segment(forefoot_p, win_lo, win_hi)
            heel_seg = _segment(heel_p, win_lo, win_hi)
            if ff_seg.size and heel_seg.size:
                ff_m = float(np.mean(ff_seg))
                hl_m = float(np.mean(heel_seg))
                row["mid_ff_heel_ratio"] = _safe_float(ff_m / (hl_m + 1e-6))
        if toe_p is not None and heel_p is not None and win_hi > win_lo:
            t_seg = _segment(toe_p, win_lo, win_hi)
            h_seg = _segment(heel_p, win_lo, win_hi)
            if t_seg.size and h_seg.size:
                t_m = float(np.mean(t_seg))
                h_m = float(np.mean(h_seg))
                row["mid_toe_heel_ratio"] = _safe_float(t_m / (h_m + 1e-6))

        # ── CoP path length & range during stance ──
        if cop_x is not None and cop_y is not None:
            row["cop_path_stance"] = _path_len(cop_x, cop_y, hs, toe)
            cx_seg = _segment(cop_x, hs, toe)
            cy_seg = _segment(cop_y, hs, toe)
            row["cop_x_range_stance"] = _safe_float(np.ptp(cx_seg)) if cx_seg.size else np.nan
            row["cop_y_range_stance"] = _safe_float(np.ptp(cy_seg)) if cy_seg.size else np.nan

        # ── Body IMU at stride boundaries ──
        # Heel-strike Lumbar Acc-Z impact: peak |a_z| in first 100 ms after HS
        if lumbar_acc_z is not None:
            seg = _segment(lumbar_acc_z, hs, hs + n_hs100)
            row["lumbar_az_hs_impact"] = _safe_float(np.max(np.abs(seg))) if seg.size else np.nan
        if sternum_acc_z is not None:
            seg = _segment(sternum_acc_z, hs, hs + n_hs100)
            row["sternum_az_hs_impact"] = _safe_float(np.max(np.abs(seg))) if seg.size else np.nan
        # Shank Gyr-Y peak during swing (after toe-off, before next HS)
        if shank_gyr_y is not None:
            seg = _segment(shank_gyr_y, toe, nxt)
            row["shank_gy_swing_peak"] = _safe_float(np.max(np.abs(seg))) if seg.size else np.nan
            row["shank_gy_swing_p95"] = _safe_float(np.percentile(np.abs(seg), 95)) if seg.size else np.nan
        # Shank pitch at HS (foot orientation at heel contact)
        if shank_pitch is not None:
            seg = _segment(shank_pitch, hs, hs + n_hs100)
            row["shank_pitch_at_hs"] = _safe_float(np.mean(seg)) if seg.size else np.nan
        # Thigh pitch range during swing
        if thigh_pitch is not None:
            seg = _segment(thigh_pitch, toe, nxt)
            row["thigh_pitch_swing_range"] = _safe_float(np.ptp(seg)) if seg.size > 1 else np.nan
        # Foot Acc-Z peak in last 100 ms of stance (toe-off impact)
        if foot_acc_z is not None:
            seg = _segment(foot_acc_z, max(toe - n_to100, hs), toe)
            row["foot_az_to_peak"] = _safe_float(np.max(np.abs(seg))) if seg.size else np.nan
        # Insole IMU swing peak
        if insole_acc_z is not None:
            seg = _segment(insole_acc_z, toe, nxt)
            row["insole_az_swing_peak"] = _safe_float(np.max(np.abs(seg))) if seg.size else np.nan
        if insole_gyr_y is not None:
            seg = _segment(insole_gyr_y, toe, nxt)
            row["insole_gy_swing_peak"] = _safe_float(np.max(np.abs(seg))) if seg.size else np.nan

        rows.append(row)
    return pd.DataFrame(rows)


def _double_support_proxy(strides_l: list[dict], strides_r: list[dict]) -> float:
    """Mean fraction of L stance overlapped by R stance.

    For each L stance window [hs, toe], compute the fraction of frames where
    R contact is also in stance. This is the bilateral overlap; PD subjects
    typically have INCREASED double-support time (cautious gait).
    """
    if not strides_l or not strides_r:
        return np.nan
    # Build a binary R-stance occupancy bool
    # We just intersect intervals.
    overlaps = []
    r_intervals = [(s["hs_idx"], s["to_idx"]) for s in strides_r]
    for s in strides_l:
        lo, hi = s["hs_idx"], s["to_idx"]
        total = hi - lo
        if total <= 0:
            continue
        ov = 0
        for r_lo, r_hi in r_intervals:
            o = max(0, min(hi, r_hi) - max(lo, r_lo))
            ov += o
        overlaps.append(ov / total)
    return _safe_float(np.mean(overlaps)) if overlaps else np.nan


# ─── Phase C: per-subject aggregation ────────────────────────────────────────


AGG_FNS = {
    "mean": np.nanmean,
    "std": np.nanstd,
    "p5": lambda x: np.nanpercentile(x, 5),
    "p95": lambda x: np.nanpercentile(x, 95),
}


def _slope(values: np.ndarray) -> float:
    """Linear regression slope of values vs stride index. NaN-tolerant."""
    if values.size < 4:
        return np.nan
    idx = np.arange(values.size, dtype=np.float64)
    m = ~np.isnan(values)
    if m.sum() < 4:
        return np.nan
    try:
        slope = np.polyfit(idx[m], values[m], 1)[0]
        return _safe_float(slope)
    except (np.linalg.LinAlgError, ValueError):
        return np.nan


def _first_minus_last(values: np.ndarray, k: int = 3) -> float:
    """Mean of first k strides minus mean of last k strides."""
    if values.size < 2 * k:
        return np.nan
    a = values[:k]; b = values[-k:]
    a = a[~np.isnan(a)]; b = b[~np.isnan(b)]
    if a.size == 0 or b.size == 0:
        return np.nan
    return _safe_float(float(np.mean(a)) - float(np.mean(b)))


def _aggregate_subject_strides(stride_dfs: list[pd.DataFrame],
                                task_tag: str,
                                side_tag: str) -> dict[str, float]:
    """Aggregate per-stride features into per-subject scalars.

    Output features named: stride__{task}__{side}__{feat}__{stat}
    where stat in {mean, std, cv, p5, p95, slope, first_last_diff}.
    """
    if not stride_dfs or all(df.empty for df in stride_dfs):
        return {}
    # Stack across recordings (e.g. multiple TUG repeats — typically 1 file per task).
    all_df = pd.concat(stride_dfs, ignore_index=True) if len(stride_dfs) > 1 else stride_dfs[0]
    if all_df.empty:
        return {}
    drop_cols = {"stride_idx", "hs_idx", "to_idx"}
    feat_cols = [c for c in all_df.columns if c not in drop_cols]
    out: dict[str, float] = {}
    prefix = f"stride__{task_tag}__{side_tag}"
    out[f"{prefix}__n_strides"] = float(len(all_df))
    for col in feat_cols:
        v = all_df[col].to_numpy(dtype=np.float64)
        if v.size == 0 or np.all(np.isnan(v)):
            continue
        for stat, fn in AGG_FNS.items():
            try:
                val = float(fn(v))
                out[f"{prefix}__{col}__{stat}"] = _safe_float(val)
            except Exception:
                out[f"{prefix}__{col}__{stat}"] = np.nan
        # CV = std / |mean|
        m = float(np.nanmean(v))
        s = float(np.nanstd(v))
        if abs(m) > 1e-9:
            out[f"{prefix}__{col}__cv"] = _safe_float(s / abs(m))
        # Decay slope
        out[f"{prefix}__{col}__slope"] = _slope(v)
        # First-vs-last
        out[f"{prefix}__{col}__first_last_diff"] = _first_minus_last(v)
    return out


# ─── File-level dispatch ─────────────────────────────────────────────────────


def _detect_strides(df: pd.DataFrame, side: str) -> list[dict]:
    col = f"{side} Foot Contact"
    if col not in df.columns:
        return []
    raw = df[col].to_numpy(dtype=np.float64)
    if raw.size < 50 or np.all(np.isnan(raw)):
        return []
    raw = np.where(np.isnan(raw), 0.0, raw)
    hs, to = _binary_to_events(raw)
    if not hs or not to:
        return []
    return _strides_from_events(hs, to)


def process_file(path: str) -> dict | None:
    bn = os.path.basename(path).replace(".csv", "")
    parts = bn.split("_", 1)
    sid = parts[0]
    task = parts[1] if len(parts) > 1 else "?"
    if task.endswith("_mat") or task.endswith("_matTURN"):
        return None
    if not any(g in task for g in GAIT_TASKS):
        return None
    try:
        df = pd.read_csv(path)
    except Exception as e:
        print(f"FAIL read {path}: {e}", file=sys.stderr)
        return None
    if "Time" not in df.columns or len(df) < 100:
        return None

    # Pick the canonical task tag
    if "TUG" in task:
        tag = "TUG"
    elif "HurriedPace" in task:
        tag = "Hurried"
    elif "SelfPace" in task:
        tag = "SelfP"
    elif "TandemGait" in task:
        tag = "Tandem"
    else:
        tag = task[:6]

    strides_l = _detect_strides(df, "L")
    strides_r = _detect_strides(df, "R")

    rec = {"sid": sid, "task": task, "task_tag": tag,
           "n_strides_L": len(strides_l), "n_strides_R": len(strides_r)}
    # Per-stride DataFrames per side
    df_l = _per_stride_features(strides_l, "L", df)
    df_r = _per_stride_features(strides_r, "R", df)

    rec["_df_L"] = df_l
    rec["_df_R"] = df_r
    # Bilateral asymmetry on matched strides (greedy match by index — drop-in OK)
    if not df_l.empty and not df_r.empty:
        n = min(len(df_l), len(df_r))
        if n > 0:
            for col in df_l.columns:
                if col in {"stride_idx", "hs_idx", "to_idx"}:
                    continue
                if col not in df_r.columns:
                    continue
                lv = df_l[col].to_numpy(dtype=np.float64)[:n]
                rv = df_r[col].to_numpy(dtype=np.float64)[:n]
                with np.errstate(invalid="ignore"):
                    diff = np.abs(lv - rv)
                if not np.all(np.isnan(diff)):
                    rec[f"asym__{col}__mean"] = _safe_float(np.nanmean(diff))
                    rec[f"asym__{col}__std"] = _safe_float(np.nanstd(diff))
    rec["double_support_proxy"] = _double_support_proxy(strides_l, strides_r)
    return rec


def aggregate_subject(records: list[dict]) -> pd.DataFrame:
    """Aggregate file-level records into one row per subject."""
    by_sid: dict[str, list[dict]] = {}
    for r in records:
        by_sid.setdefault(r["sid"], []).append(r)
    rows = []
    for sid, recs in by_sid.items():
        row: dict[str, float] = {"sid": sid}
        # Per-task / per-side aggregation
        # Group recordings by task_tag, then aggregate strides inside each task
        by_task: dict[str, list[dict]] = {}
        for r in recs:
            by_task.setdefault(r["task_tag"], []).append(r)
        for tag, tag_recs in by_task.items():
            l_dfs = [r["_df_L"] for r in tag_recs if not r["_df_L"].empty]
            r_dfs = [r["_df_R"] for r in tag_recs if not r["_df_R"].empty]
            row.update(_aggregate_subject_strides(l_dfs, tag, "L"))
            row.update(_aggregate_subject_strides(r_dfs, tag, "R"))
        # Bilateral asymmetry: average across recordings
        asym_keys = set()
        for r in recs:
            asym_keys.update(k for k in r if k.startswith("asym__"))
        for k in asym_keys:
            vals = [r[k] for r in recs if k in r and not (isinstance(r[k], float) and np.isnan(r[k]))]
            if vals:
                row[f"subj__{k}"] = float(np.mean(vals))
        # Double-support proxy: mean across recordings
        ds = [r.get("double_support_proxy") for r in recs]
        ds = [v for v in ds if v is not None and not (isinstance(v, float) and np.isnan(v))]
        if ds:
            row["subj__double_support_proxy_mean"] = float(np.mean(ds))
            row["subj__double_support_proxy_std"] = float(np.std(ds))
        # Stride counts
        row["subj__n_strides_L_total"] = int(sum(r["n_strides_L"] for r in recs))
        row["subj__n_strides_R_total"] = int(sum(r["n_strides_R"] for r in recs))
        row["subj__n_recordings"] = int(len(recs))
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv_dir", required=True)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    files = sorted(glob.glob(os.path.join(args.csv_dir, "*.csv")))
    files = [f for f in files if not (
        os.path.basename(f).endswith("_mat.csv")
        or os.path.basename(f).endswith("_matTURN.csv")
    )]
    # Keep only gait tasks (we need stride detection)
    files = [f for f in files
             if any(g in os.path.basename(f) for g in GAIT_TASKS)]
    if args.limit:
        files = files[: args.limit]
    print(f"Processing {len(files)} gait CSV files with {args.workers} workers...", flush=True)

    if args.workers <= 1:
        rows = [process_file(f) for f in files]
    else:
        # Use spawn-safe pool
        with mp.Pool(args.workers) as pool:
            rows = []
            for i, r in enumerate(pool.imap_unordered(process_file, files, chunksize=4)):
                rows.append(r)
                if (i + 1) % 50 == 0:
                    print(f"  {i+1}/{len(files)} done", flush=True)
    rows = [r for r in rows if r is not None]
    print(f"Built {len(rows)} per-recording stride blocks.", flush=True)

    # Stride detection statistics
    if rows:
        n_str_l = np.array([r["n_strides_L"] for r in rows])
        n_str_r = np.array([r["n_strides_R"] for r in rows])
        print(f"Median strides/file: L={np.median(n_str_l):.0f}, R={np.median(n_str_r):.0f}", flush=True)
        print(f"  L percentiles 25/50/75/95: {np.percentile(n_str_l, [25,50,75,95])}", flush=True)
        print(f"  R percentiles 25/50/75/95: {np.percentile(n_str_r, [25,50,75,95])}", flush=True)
        print(f"  Files with >=4 L strides: {int(np.sum(n_str_l >= 4))}/{len(rows)}", flush=True)

    df_subj = aggregate_subject(rows)
    print(f"Subject rows: {df_subj.shape}", flush=True)

    # Per-subject stride stats
    if "subj__n_strides_L_total" in df_subj.columns:
        l_tot = df_subj["subj__n_strides_L_total"].to_numpy()
        r_tot = df_subj["subj__n_strides_R_total"].to_numpy()
        print(f"Median strides/subject: L={np.median(l_tot):.0f}, R={np.median(r_tot):.0f}", flush=True)
        print(f"  L percentiles 25/50/75/95: {np.percentile(l_tot, [25,50,75,95])}", flush=True)
        print(f"  R percentiles 25/50/75/95: {np.percentile(r_tot, [25,50,75,95])}", flush=True)
        print(f"  Subjects with >=20 L strides: {int(np.sum(l_tot >= 20))}/{len(df_subj)}", flush=True)

    df_subj.to_csv(args.out, index=False)
    print(f"Wrote {args.out} ({df_subj.shape})", flush=True)


if __name__ == "__main__":
    main()
