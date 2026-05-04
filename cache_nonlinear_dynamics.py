"""Nonlinear dynamics feature cache for items 10 (gait) and 12 (postural stability).

Augments existing per-item features with:
- RQA on Lumbar Acc AP/ML during gait (determinism, longest line, laminarity, trapping time)
- DFA alpha exponent on stride-time series (item 10)
- Multifractal DFA spectrum width (q=-3..3) on Lumbar Acc AP (item 10)
- Largest Lyapunov exponent (Rosenstein) on Lumbar AP (item 12)
- Frequency-centroid drift over time on Lumbar Acc (item 12 sway)
- Approximate entropy ratio of Lumbar X (ML) vs Y (AP) accel (item 12 — proxy
  for CoP since dataset has no force plate)

Self-contained: 16-way multiprocessing across recordings, aggregates per-subject.
Output: results/nonlinear_dynamics_features.csv (per-subject, prefix `nl_`).

Usage:
    python3 cache_nonlinear_dynamics.py --workers 16 \
        --csv_dir "data/raw/weargait-pd/PD PARTICIPANTS/CSV files" \
        --out results/nonlinear_dynamics_features.csv
"""
from __future__ import annotations

import argparse
import glob
import math
import os
import sys
import warnings
import multiprocessing as mp
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import signal as sp_signal

warnings.filterwarnings("ignore")

FS = 100.0  # Hz

# Tasks where each item-specific extractor is valid
GAIT_TASKS = ("Pace", "TUG", "Tandem")  # for item 10
SWAY_TASKS = ("Balance", "Tandem")       # for item 12


def _get_col(df: pd.DataFrame, sensor: str, group: str, axis: str) -> np.ndarray:
    col = f"{sensor}_{group}_{axis}"
    if col in df.columns:
        return df[col].to_numpy(dtype=np.float64)
    return np.full(len(df), np.nan)


# ───────────────────────────────────────────────────────────────────────────
# Primitive nonlinear-dynamics functions
# ───────────────────────────────────────────────────────────────────────────


def _clean(x: np.ndarray, max_n: int = 6000) -> np.ndarray:
    """Drop NaNs, mean-center, cap length."""
    x = x[~np.isnan(x)]
    if x.size == 0:
        return x
    x = x - np.mean(x)
    if x.size > max_n:
        x = x[:max_n]
    return x


def _embed(x: np.ndarray, m: int, tau: int) -> np.ndarray:
    """Time-delay embedding."""
    n = len(x) - (m - 1) * tau
    if n <= 1:
        return np.empty((0, m))
    return np.array([x[i:i + m * tau:tau] for i in range(n)])


def _rqa_features(x: np.ndarray, m: int = 3, tau: int = 5,
                  thresh_q: float = 0.10, max_n: int = 1500) -> dict:
    """Recurrence Quantification Analysis on a 1-D signal.

    Computes: recurrence rate, determinism, average line length,
    longest diagonal line, laminarity, trapping time. Cap embedded N at
    max_n to keep distance matrix tractable (1500x1500 = 18 MB).
    """
    keys = ("rqa_rr", "rqa_det", "rqa_avgline", "rqa_lmax",
            "rqa_lam", "rqa_tt")
    out = {k: float("nan") for k in keys}
    if x.size < (m - 1) * tau + 64:
        return out
    Y = _embed(x, m, tau)
    if Y.shape[0] < 32:
        return out
    if Y.shape[0] > max_n:
        idx = np.linspace(0, Y.shape[0] - 1, max_n).astype(int)
        Y = Y[idx]
    n = Y.shape[0]
    # Pairwise euclidean distances
    diff = Y[:, None, :] - Y[None, :, :]
    D = np.sqrt(np.sum(diff * diff, axis=-1))
    # Threshold = q-quantile of pairwise distances (theiler-corrected)
    iu = np.triu_indices(n, k=1)
    thresh = np.quantile(D[iu], thresh_q) if iu[0].size else 0.0
    R = (D <= thresh).astype(np.uint8)
    np.fill_diagonal(R, 0)
    rr = R.sum() / (n * (n - 1) + 1e-12)
    out["rqa_rr"] = float(rr)
    # Diagonal line statistics (excluding main diagonal)
    diag_lines: list[int] = []
    for k in range(1, n - 1):
        diag = np.diagonal(R, offset=k)
        run = 0
        for v in diag:
            if v:
                run += 1
            else:
                if run >= 2:
                    diag_lines.append(run)
                run = 0
        if run >= 2:
            diag_lines.append(run)
    if diag_lines:
        diag_pts = sum(diag_lines)
        det = diag_pts / (R.sum() / 2 + 1e-12)  # /2 because matrix is symmetric
        out["rqa_det"] = float(min(det, 1.0))
        out["rqa_avgline"] = float(np.mean(diag_lines))
        out["rqa_lmax"] = float(max(diag_lines))
    else:
        out["rqa_det"] = 0.0
        out["rqa_avgline"] = 0.0
        out["rqa_lmax"] = 0.0
    # Vertical line statistics (laminarity, trapping time)
    vert_lines: list[int] = []
    for col in range(n):
        run = 0
        for v in R[:, col]:
            if v:
                run += 1
            else:
                if run >= 2:
                    vert_lines.append(run)
                run = 0
        if run >= 2:
            vert_lines.append(run)
    if vert_lines:
        vert_pts = sum(vert_lines)
        lam = vert_pts / (R.sum() + 1e-12)
        out["rqa_lam"] = float(min(lam, 1.0))
        out["rqa_tt"] = float(np.mean(vert_lines))
    else:
        out["rqa_lam"] = 0.0
        out["rqa_tt"] = 0.0
    return out


def _dfa_alpha(x: np.ndarray, n_min: int = 16, n_max: int = 512) -> float:
    """Detrended Fluctuation Analysis. Returns Hurst-like alpha exponent.

    For stride-time series we expect alpha ≈ 0.7-0.9 in healthy gait,
    closer to 0.5 (random-walk-free) in PD. Falls back to nolds if available
    (more robust), else uses the canonical Peng implementation.
    """
    x = x[~np.isnan(x)]
    if x.size < n_min * 4:
        return float("nan")
    try:
        from nolds import dfa
        return float(dfa(x))
    except Exception:
        pass
    # Hand-rolled fallback (Peng 1994)
    y = np.cumsum(x - np.mean(x))
    n_max = min(n_max, len(y) // 4)
    if n_max <= n_min:
        return float("nan")
    ns = np.unique(np.logspace(math.log10(n_min), math.log10(n_max), 12).astype(int))
    fs = []
    for n in ns:
        n_seg = len(y) // n
        if n_seg < 2:
            continue
        rms_acc = []
        for k in range(n_seg):
            seg = y[k * n:(k + 1) * n]
            t = np.arange(n)
            coef = np.polyfit(t, seg, 1)
            trend = np.polyval(coef, t)
            rms_acc.append(np.mean((seg - trend) ** 2))
        if rms_acc:
            fs.append(math.sqrt(np.mean(rms_acc)))
        else:
            fs.append(np.nan)
    fs = np.asarray(fs, dtype=float)
    valid = ~np.isnan(fs)
    if valid.sum() < 3:
        return float("nan")
    log_n = np.log(ns[valid])
    log_f = np.log(fs[valid])
    slope = np.polyfit(log_n, log_f, 1)[0]
    return float(slope)


def _mfdfa_width(x: np.ndarray, q_min: float = -3.0, q_max: float = 3.0,
                 n_q: int = 7) -> dict:
    """Multifractal-DFA spectrum width Δh = h(q_min) − h(q_max) and h_q variance."""
    out = {"mfdfa_h_q-3": float("nan"), "mfdfa_h_q3": float("nan"),
           "mfdfa_width": float("nan"), "mfdfa_h_var": float("nan")}
    x = x[~np.isnan(x)]
    if x.size < 256:
        return out
    try:
        from MFDFA import MFDFA  # type: ignore
        # Use lag scales 8..max(N//4, 16). Convert to ints.
        max_lag = max(16, x.size // 4)
        lag = np.unique(np.logspace(0.9, math.log10(max_lag), 12).astype(int))
        q = np.linspace(q_min, q_max, n_q)
        # Avoid q=0 (degenerate)
        q = q[np.abs(q) > 0.01]
        try:
            scales, F = MFDFA(x, lag=lag, q=q)
        except Exception:
            return out
        F = np.asarray(F)
        # Each column corresponds to a q. Compute Hurst exponent h(q) via slope.
        log_lag = np.log(lag)
        h_q: list[float] = []
        for j in range(F.shape[1]):
            f = F[:, j]
            valid = (f > 0) & np.isfinite(f)
            if valid.sum() < 4:
                h_q.append(np.nan)
                continue
            slope = np.polyfit(log_lag[valid], np.log(f[valid]), 1)[0]
            h_q.append(float(slope))
        h_q = np.array(h_q)
        valid = ~np.isnan(h_q)
        if valid.sum() < 3:
            return out
        # Match q to its h
        out["mfdfa_h_q-3"] = float(h_q[0])
        out["mfdfa_h_q3"] = float(h_q[-1])
        out["mfdfa_width"] = float(np.nanmax(h_q) - np.nanmin(h_q))
        out["mfdfa_h_var"] = float(np.nanvar(h_q))
    except ImportError:
        return out
    return out


def _largest_lyapunov(x: np.ndarray, m: int = 5, lag: int | None = None,
                      max_n: int = 4000) -> float:
    """Rosenstein largest Lyapunov exponent. Uses nolds if available."""
    x = x[~np.isnan(x)]
    if x.size < 256:
        return float("nan")
    if x.size > max_n:
        x = x[:max_n]
    try:
        from nolds import lyap_r
        if lag is None:
            return float(lyap_r(x, emb_dim=m))
        return float(lyap_r(x, emb_dim=m, lag=lag))
    except Exception:
        return float("nan")


def _frequency_centroid_drift(x: np.ndarray, fs: float = FS,
                              win_s: float = 5.0, step_s: float = 1.0) -> dict:
    """Sliding-window dominant-frequency std + centroid drift std."""
    out = {"freq_centroid_std": float("nan"), "dom_freq_std": float("nan"),
           "freq_drift_slope": float("nan")}
    x = x[~np.isnan(x)]
    if x.size < int(2 * win_s * fs):
        return out
    win = int(win_s * fs)
    step = int(step_s * fs)
    if step < 1:
        step = 1
    centroids: list[float] = []
    domf: list[float] = []
    for i in range(0, len(x) - win + 1, step):
        seg = x[i:i + win]
        seg = seg - np.mean(seg)
        f, p = sp_signal.welch(seg, fs=fs, nperseg=min(256, len(seg)))
        if p.sum() < 1e-12:
            continue
        c = float(np.sum(f * p) / np.sum(p))
        centroids.append(c)
        domf.append(float(f[np.argmax(p)]))
    if len(centroids) < 3:
        return out
    centroids = np.asarray(centroids)
    domf = np.asarray(domf)
    out["freq_centroid_std"] = float(np.std(centroids))
    out["dom_freq_std"] = float(np.std(domf))
    # Linear slope of centroid over time = drift
    t = np.arange(len(centroids))
    out["freq_drift_slope"] = float(np.polyfit(t, centroids, 1)[0])
    return out


def _approx_entropy(x: np.ndarray, m: int = 2, r_factor: float = 0.2,
                    max_n: int = 1500) -> float:
    """Approximate entropy. Using nolds if present (faster)."""
    x = x[~np.isnan(x)]
    if x.size < 32:
        return float("nan")
    if x.size > max_n:
        x = x[:max_n]
    try:
        from nolds import sampen
        # sampen returns sample-entropy; valid stand-in for ApEn at this granularity
        return float(sampen(x, emb_dim=m, tolerance=r_factor * np.std(x)))
    except Exception:
        return float("nan")


def _detect_strides(gyr_y: np.ndarray, fs: float = FS) -> np.ndarray:
    """Detect heel-strikes from shank gyro Y peaks. Returns sample indices."""
    if gyr_y.size < int(fs * 2):
        return np.array([], dtype=int)
    sig = gyr_y - np.nanmean(gyr_y)
    sig = np.nan_to_num(sig, nan=0.0)
    # Lowpass to denoise
    try:
        b, a = sp_signal.butter(4, 6.0 / (fs / 2), "low")
        sig = sp_signal.filtfilt(b, a, sig)
    except Exception:
        pass
    height = max(np.percentile(np.abs(sig), 60), 30.0)
    peaks, _ = sp_signal.find_peaks(sig, height=height, distance=int(fs * 0.4))
    return peaks


# ───────────────────────────────────────────────────────────────────────────
# Per-recording extractor
# ───────────────────────────────────────────────────────────────────────────


def process_file(path: str) -> dict | None:
    bn = os.path.basename(path).replace(".csv", "")
    parts = bn.split("_", 1)
    sid = parts[0]
    task = parts[1] if len(parts) > 1 else "?"
    if task.endswith("_mat") or task.endswith("_matTURN"):
        return None
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if "Time" not in df.columns or len(df) < 200:
        return None

    out: dict = {"sid": sid, "task": task}
    # ── Item 10 (gait) — only on gait tasks ──
    if any(t in task for t in GAIT_TASKS):
        lumbar_ap = _clean(_get_col(df, "LowerBack", "Acc", "X"))   # AP
        lumbar_ml = _clean(_get_col(df, "LowerBack", "Acc", "Y"))   # ML

        if lumbar_ap.size > 64:
            for k, v in _rqa_features(lumbar_ap, m=3, tau=5).items():
                out[f"nl_i10_ap_{k}"] = v
            out["nl_i10_ap_lyap"] = _largest_lyapunov(lumbar_ap, m=5)
            for k, v in _mfdfa_width(lumbar_ap).items():
                out[f"nl_i10_ap_{k}"] = v
        if lumbar_ml.size > 64:
            for k, v in _rqa_features(lumbar_ml, m=3, tau=5).items():
                out[f"nl_i10_ml_{k}"] = v
            out["nl_i10_ml_lyap"] = _largest_lyapunov(lumbar_ml, m=5)

        # DFA on stride-time interval series (preferred for item 10 per Hausdorff)
        sh_y = _get_col(df, "L_LatShank", "Gyr", "Y")
        strides = _detect_strides(sh_y, FS)
        if len(strides) >= 16:
            durs = np.diff(strides) / FS
            out["nl_i10_dfa_alpha_stride"] = _dfa_alpha(durs)
            out["nl_i10_n_strides_dfa"] = float(len(durs))
        else:
            out["nl_i10_dfa_alpha_stride"] = float("nan")
            out["nl_i10_n_strides_dfa"] = float(len(strides))

    # ── Item 12 (postural stability) — only on Balance/Tandem ──
    if any(t in task for t in SWAY_TASKS):
        lumbar_ap = _clean(_get_col(df, "LowerBack", "Acc", "X"))
        lumbar_ml = _clean(_get_col(df, "LowerBack", "Acc", "Y"))

        if lumbar_ap.size > 64:
            out["nl_i12_ap_lyap"] = _largest_lyapunov(lumbar_ap, m=5)
            out["nl_i12_ap_apen"] = _approx_entropy(lumbar_ap)
            for k, v in _frequency_centroid_drift(lumbar_ap).items():
                out[f"nl_i12_ap_{k}"] = v
            for k, v in _rqa_features(lumbar_ap, m=3, tau=5).items():
                out[f"nl_i12_ap_{k}"] = v
        if lumbar_ml.size > 64:
            out["nl_i12_ml_lyap"] = _largest_lyapunov(lumbar_ml, m=5)
            out["nl_i12_ml_apen"] = _approx_entropy(lumbar_ml)
            for k, v in _frequency_centroid_drift(lumbar_ml).items():
                out[f"nl_i12_ml_{k}"] = v
        # Anisotropy: ratio of AP to ML approx-entropy (CoP-X/Y proxy)
        if lumbar_ap.size > 64 and lumbar_ml.size > 64:
            ap_e = out.get("nl_i12_ap_apen", float("nan"))
            ml_e = out.get("nl_i12_ml_apen", float("nan"))
            if (not np.isnan(ap_e)) and (not np.isnan(ml_e)) and ml_e > 1e-6:
                out["nl_i12_apen_ratio_ap_ml"] = float(ap_e / ml_e)

    return out


# ───────────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv_dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    files = sorted(glob.glob(os.path.join(args.csv_dir, "*.csv")))
    files = [f for f in files if not (
        os.path.basename(f).endswith("_mat.csv")
        or os.path.basename(f).endswith("_matTURN.csv")
    )]
    if args.limit:
        files = files[: args.limit]
    print(f"Processing {len(files)} CSV files with {args.workers} workers...", flush=True)

    rows: list[dict] = []
    if args.workers <= 1:
        for i, f in enumerate(files):
            r = process_file(f)
            if r is not None:
                rows.append(r)
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(files)} done", flush=True)
    else:
        with mp.Pool(args.workers) as pool:
            for i, r in enumerate(pool.imap_unordered(process_file, files, chunksize=2)):
                if r is not None:
                    rows.append(r)
                if (i + 1) % 50 == 0:
                    print(f"  {i+1}/{len(files)} done", flush=True)

    print(f"Built {len(rows)} per-recording rows", flush=True)
    df_rec = pd.DataFrame(rows)
    feat_cols = [c for c in df_rec.columns if c not in ("sid", "task")]

    # Aggregate per subject: mean / std across tasks for each feature
    subj_rows: list[dict] = []
    for sid, grp in df_rec.groupby("sid"):
        row: dict = {"sid": sid}
        for col in feat_cols:
            arr = grp[col].dropna().values
            if arr.size == 0:
                continue
            row[f"{col}_mean"] = float(np.mean(arr))
            if arr.size > 1:
                row[f"{col}_std"] = float(np.std(arr))
        subj_rows.append(row)
    df_subj = pd.DataFrame(subj_rows)
    df_subj.to_csv(args.out, index=False)
    print(f"Wrote {args.out} ({df_subj.shape})", flush=True)


if __name__ == "__main__":
    main()
