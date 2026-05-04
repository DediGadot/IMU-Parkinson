"""Track B: Item 11 (FoG) multi-scale freeze-index + per-event wavelet entropy.

Per PD subject, for each gait recording (SelfPace, HurriedPace, TUG, TandemGait):

1. Multi-scale Freeze Index (FI) on Shank Acc-AP (X) for L and R, and Lumbar
   Acc-AP (X) and Lumbar ML (Y), using sliding windows of {2, 4, 8} seconds.
   FI = power(3-8 Hz) / power(0.5-3 Hz). Stats: mean, max, p95, count(>2.0).

2. Detect freeze events: any 2-s window in any of the four FI streams with
   FI > 2.0. Record total_freeze_seconds, longest_freeze_run, n_freeze_events.

3. Per-event wavelet entropy: Shannon entropy of the energy distribution
   across wavelet packet decomposition (level=4, db4) on Shank Gyr-Y during
   each freeze window. Aggregate (mean, max, std) across events.

4. Inter-stride coefficient of variation during walking. Detect strides via
   shank Gyr-Y zero-crossings (already in cache_per_item_features_v2 logic),
   then CV(stride duration) and CV(stride amplitude). Multi-scale = whole-record
   plus per-(start third, mid third, end third) tertile splits.

Aggregate per subject = mean/max/std across recordings.

Output: results/item11_multiscale.csv (sid + multiscale FoG features).

Usage:
    python3 cache_item11_multiscale.py --workers 16 \
        --csv_dir "data/raw/weargait-pd/PD PARTICIPANTS/CSV files" \
        --out results/item11_multiscale.csv
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
WIN_SCALES = (2.0, 4.0, 8.0)
FREEZE_THRESHOLD = 2.0  # FI > 2.0 = freeze candidate (Moore et al. 2008)
FREEZE_DETECT_WIN_S = 2.0
WALKING_TASKS = ("SelfPace", "HurriedPace", "TUG", "TandemGait")


def _bp_ratio(x: np.ndarray, fs: float, lo_band, hi_band) -> float:
    if x.size < 32:
        return np.nan
    x = np.nan_to_num(x - np.nanmean(x), nan=0.0)
    nperseg = min(256, len(x))
    f, p = sp_signal.welch(x, fs=fs, nperseg=nperseg)
    lo_p = float(np.sum(p[(f >= lo_band[0]) & (f < lo_band[1])]))
    hi_p = float(np.sum(p[(f >= hi_band[0]) & (f < hi_band[1])]))
    if lo_p < 1e-9:
        return np.nan
    return hi_p / lo_p


def _multiscale_fi(x: np.ndarray, fs: float, win_s: float, step_s: float = 0.5) -> dict:
    """Sliding-window FI series; return mean/max/p95/count(>2)."""
    win = int(fs * win_s)
    step = int(fs * step_s)
    if len(x) < win:
        return dict(mean=np.nan, max=np.nan, p95=np.nan, count=np.nan)
    fis = []
    for i in range(0, len(x) - win, step):
        v = _bp_ratio(x[i:i + win], fs, (0.5, 3.0), (3.0, 8.0))
        if not np.isnan(v):
            fis.append(v)
    if not fis:
        return dict(mean=np.nan, max=np.nan, p95=np.nan, count=np.nan)
    a = np.asarray(fis)
    return dict(
        mean=float(np.mean(a)),
        max=float(np.max(a)),
        p95=float(np.percentile(a, 95)),
        count=int(np.sum(a > FREEZE_THRESHOLD)),
    )


def _detect_freeze_windows(x: np.ndarray, fs: float = FS,
                            win_s: float = FREEZE_DETECT_WIN_S,
                            step_s: float = 0.5) -> list[tuple[int, int]]:
    """Return list of (start, end) sample indices for each detected freeze window."""
    win = int(fs * win_s)
    step = int(fs * step_s)
    if len(x) < win:
        return []
    out = []
    for i in range(0, len(x) - win, step):
        v = _bp_ratio(x[i:i + win], fs, (0.5, 3.0), (3.0, 8.0))
        if not np.isnan(v) and v > FREEZE_THRESHOLD:
            out.append((i, i + win))
    return out


def _merge_overlapping(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    intervals = sorted(intervals)
    merged = [intervals[0]]
    for s, e in intervals[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _wp_entropy(x: np.ndarray, level: int = 4, wavelet: str = "db4") -> float:
    """Shannon entropy of WP energy distribution. Returns NaN if pywt missing or data tiny."""
    if len(x) < 2 ** level:
        return np.nan
    try:
        import pywt
    except ImportError:
        return np.nan
    x = np.nan_to_num(x - np.nanmean(x), nan=0.0)
    try:
        wp = pywt.WaveletPacket(data=x, wavelet=wavelet, mode="symmetric", maxlevel=level)
        nodes = [n.path for n in wp.get_level(level, order="natural")]
        energies = []
        for path in nodes:
            d = wp[path].data
            energies.append(float(np.sum(d * d)))
        e = np.asarray(energies)
        s = e.sum()
        if s < 1e-12:
            return np.nan
        p = e / s
        p = p[p > 0]
        return float(-np.sum(p * np.log(p)))
    except Exception:
        return np.nan


def _detect_strides_from_shank(gyr_y: np.ndarray, fs: float = FS) -> list[int]:
    if len(gyr_y) < int(fs * 2):
        return []
    s = np.nan_to_num(gyr_y - np.nanmean(gyr_y), nan=0.0)
    if len(s) > 51:
        s = sp_signal.savgol_filter(s, 51, 3)
    zc = np.where(np.diff(np.sign(s)) > 0)[0]
    if len(zc) < 3:
        return []
    durations = np.diff(zc) / fs
    keep = durations > 0.4
    out = [int(zc[0])] + [int(zc[i + 1]) for i in range(len(durations)) if keep[i]]
    return out


def _stride_cv_stats(strides: list[int], gyr_y: np.ndarray, fs: float = FS) -> dict:
    if len(strides) < 4:
        return {}
    durs = np.diff(strides) / fs
    out = {
        "stride_n": len(strides) - 1,
        "stride_dur_cv": float(np.std(durs) / (np.mean(durs) + 1e-9)),
        "stride_dur_p95": float(np.percentile(durs, 95)),
        "stride_dur_iqr": float(np.percentile(durs, 75) - np.percentile(durs, 25)),
    }
    amps = []
    for k in range(len(strides) - 1):
        seg = gyr_y[strides[k]:strides[k + 1]]
        if len(seg) > 8:
            amps.append(float(np.ptp(seg)))
    if amps:
        out["stride_amp_cv"] = float(np.std(amps) / (np.mean(amps) + 1e-9))
        out["stride_amp_iqr"] = float(np.percentile(amps, 75) - np.percentile(amps, 25))
    return out


def _resolve(df_cols: set, sensor: str, channel: str) -> str | None:
    for cand in (f"{sensor}_{channel}", f"{sensor}{channel}"):
        if cand in df_cols:
            return cand
    return None


def process_file(path: str) -> dict | None:
    bn = os.path.basename(path).replace(".csv", "")
    parts = bn.split("_", 1)
    sid = parts[0]
    task = parts[1] if len(parts) > 1 else ""
    if task.endswith("_mat") or task.endswith("_matTURN"):
        return None
    if not any(t in task for t in WALKING_TASKS):
        return None
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        print(f"FAIL read {path}: {exc}", file=sys.stderr)
        return None
    if "Time" not in df.columns or len(df) < int(FS * 4):
        return None
    cols = set(df.columns)

    out = {"sid": sid, "task": task, "recording": bn}

    # 1. Multi-scale FI on 4 streams × 3 window sizes
    streams = {
        "Lshank_AP": _resolve(cols, "L_LatShank", "Acc_X"),
        "Rshank_AP": _resolve(cols, "R_LatShank", "Acc_X"),
        "Lumbar_AP": _resolve(cols, "LowerBack", "Acc_X"),
        "Lumbar_ML": _resolve(cols, "LowerBack", "Acc_Y"),
    }
    fi_traces = {}
    for label, col in streams.items():
        if col is None:
            continue
        x = df[col].to_numpy(dtype=np.float64)
        if np.all(np.isnan(x)):
            continue
        fi_traces[label] = x
        for ws in WIN_SCALES:
            d = _multiscale_fi(x, FS, ws)
            for k, v in d.items():
                out[f"i11ms_{label}_w{int(ws)}s_{k}"] = v

    # 2. Detect freeze episodes from any of the 4 streams (union of windows)
    all_events: list[tuple[int, int]] = []
    for x in fi_traces.values():
        all_events.extend(_detect_freeze_windows(x, FS))
    merged = _merge_overlapping(all_events)
    out["i11ms_n_freeze_events"] = len(merged)
    if merged:
        durs_s = np.array([(e - s) / FS for s, e in merged])
        out["i11ms_total_freeze_s"] = float(durs_s.sum())
        out["i11ms_max_freeze_run_s"] = float(durs_s.max())
        out["i11ms_mean_freeze_s"] = float(durs_s.mean())
        # 3. Per-event wavelet entropy on Shank Gyr-Y (use L if present else R)
        gyr_col = _resolve(cols, "L_LatShank", "Gyr_Y") or _resolve(cols, "R_LatShank", "Gyr_Y")
        if gyr_col is not None:
            gyr = df[gyr_col].to_numpy(dtype=np.float64)
            ents = []
            for s, e in merged:
                seg = gyr[max(0, s):min(len(gyr), e)]
                v = _wp_entropy(seg, level=4)
                if not np.isnan(v):
                    ents.append(v)
            if ents:
                arr = np.asarray(ents)
                out["i11ms_wp_ent_mean"] = float(arr.mean())
                out["i11ms_wp_ent_max"] = float(arr.max())
                out["i11ms_wp_ent_std"] = float(arr.std())
    else:
        out["i11ms_total_freeze_s"] = 0.0
        out["i11ms_max_freeze_run_s"] = 0.0
        out["i11ms_mean_freeze_s"] = 0.0

    # 4. Inter-stride CV (whole + tertile splits)
    sh_y_col = _resolve(cols, "L_LatShank", "Gyr_Y") or _resolve(cols, "R_LatShank", "Gyr_Y")
    if sh_y_col is not None:
        gyr = df[sh_y_col].to_numpy(dtype=np.float64)
        if not np.all(np.isnan(gyr)):
            strides = _detect_strides_from_shank(gyr, FS)
            d = _stride_cv_stats(strides, gyr, FS)
            for k, v in d.items():
                out[f"i11ms_full_{k}"] = v
            # Tertiles
            n = len(gyr)
            for ti, (s, e) in enumerate([(0, n // 3), (n // 3, 2 * n // 3), (2 * n // 3, n)]):
                seg = gyr[s:e]
                if len(seg) > int(FS * 2):
                    str_t = _detect_strides_from_shank(seg, FS)
                    dt = _stride_cv_stats(str_t, seg, FS)
                    for k, v in dt.items():
                        out[f"i11ms_t{ti}_{k}"] = v
    return out


def aggregate_per_subject(df_rec: pd.DataFrame) -> pd.DataFrame:
    feature_cols = [c for c in df_rec.columns
                    if c not in ("sid", "task", "recording")]
    rows = []
    for sid, grp in df_rec.groupby("sid"):
        row = {"sid": sid}
        for c in feature_cols:
            arr = grp[c].dropna().to_numpy()
            if len(arr) == 0:
                continue
            row[f"{c}_mean"] = float(np.mean(arr))
            row[f"{c}_max"] = float(np.max(arr))
            if len(arr) > 1:
                row[f"{c}_std"] = float(np.std(arr))
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv_dir", required=True)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--out", default="results/item11_multiscale.csv")
    p.add_argument("--out_recordings", default="results/item11_multiscale_recordings.csv")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    files = sorted(glob.glob(os.path.join(args.csv_dir, "*.csv")))
    files = [f for f in files if any(t in os.path.basename(f) for t in WALKING_TASKS)
             and not (f.endswith("_mat.csv") or f.endswith("_matTURN.csv"))]
    if args.limit:
        files = files[:args.limit]
    print(f"Scanning {len(files)} walking CSVs with {args.workers} workers...", flush=True)

    if args.workers <= 1:
        rows = [process_file(f) for f in files]
    else:
        with mp.Pool(args.workers) as pool:
            rows = []
            for i, r in enumerate(pool.imap_unordered(process_file, files, chunksize=4)):
                if (i + 1) % 50 == 0:
                    print(f"  {i+1}/{len(files)}", flush=True)
                rows.append(r)
    rows = [r for r in rows if r is not None]
    print(f"Built {len(rows)} per-recording rows.", flush=True)
    if not rows:
        raise SystemExit("No item-11 multiscale rows extracted")
    df_rec = pd.DataFrame(rows)
    df_rec.to_csv(args.out_recordings, index=False)
    print(f"Wrote {args.out_recordings} ({df_rec.shape})", flush=True)
    df_subj = aggregate_per_subject(df_rec)
    df_subj.to_csv(args.out, index=False)
    print(f"Wrote {args.out} ({df_subj.shape})", flush=True)


if __name__ == "__main__":
    main()
