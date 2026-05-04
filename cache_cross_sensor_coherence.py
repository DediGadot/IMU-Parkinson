"""Cache cross-sensor frequency-domain coherence features (Method 1 in fusion mission).

Approach:
- For each PD subject's raw 22-channel CSV (gait tasks only: SelfPace, HurriedPace,
  TandemGait, plus their `_mat` variants), compute pairwise magnitude-squared coherence
  between clinically-meaningful sensor pairs.
- Detect gait fundamental frequency f_gait per recording from Lumbar Acc_Z PSD peak
  in the 0.5-3 Hz band (typical PD step-frequency range).
- For each pair, extract coherence at f_gait, at 2*f_gait, and integrated coherence in
  0.5-3 Hz band (mean).

Sensor pairs (10 pairs, clinically meaningful):
  - Bilateral wrist            (R_Wrist, L_Wrist)            channel: Gyr_Y
  - Bilateral shank            (R_LatShank, L_LatShank)      channel: Gyr_Y
  - Bilateral foot             (R_DorsalFoot, L_DorsalFoot)  channel: Gyr_Y
  - Lumbar–Sternum (axial)     (LowerBack, Xiphoid)          channel: Acc_Z
  - Lumbar–Forehead (cervical) (LowerBack, Forehead)         channel: Acc_Z
  - Lumbar–R Wrist             (LowerBack, R_Wrist)          channel: Acc_Z|Gyr_Y
  - Lumbar–L Wrist             (LowerBack, L_Wrist)          channel: Acc_Z|Gyr_Y
  - Lumbar–R Shank             (LowerBack, R_LatShank)       channel: Acc_Z|Gyr_Y
  - Lumbar–L Shank             (LowerBack, L_LatShank)       channel: Acc_Z|Gyr_Y
  - Bilateral thigh            (R_MidLatThigh, L_MidLatThigh) channel: Gyr_Y

For each (pair, channel), we extract 3 metrics (coh@f, coh@2f, coh_integrated_0.5_3Hz)
→ ~30-50 features per recording. Mean / std across subject's gait recordings → ~60-100
features per subject.

Fail-fast: if Lumbar f_gait cannot be detected (signal energy too low), the recording
is skipped — no fallback peaks. NaN ratios reported in summary.

Output: results/cross_sensor_coherence.csv

Usage:
  python3 cache_cross_sensor_coherence.py
  python3 cache_cross_sensor_coherence.py --smoke  # 5 subjects only
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import coherence, welch

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir

FS = 100  # Hz, all WearGait IMUs sample at 100 Hz
GAIT_BAND = (0.5, 3.0)  # Hz — fundamental step-frequency band
COH_NPERSEG = 256       # Welch window for coherence (~2.56s)
COH_NOVERLAP = 128
GAIT_TASK_NAMES = {
    "SelfPace", "SelfPace_mat",
    "HurriedPace", "HurriedPace_mat",
    "TandemGait",
}
RAW_CSV_DIR_PD = Path("/root/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files")

# ── Sensor pair definitions ─────────────────────────────────────────────────

# Each pair: (label, sensor_a, sensor_b, channels). Channels listed will each be
# used to compute 3 coherence metrics.
PAIRS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("biw",   "R_Wrist",       "L_Wrist",        ("Gyr_Y",)),
    ("bish",  "R_LatShank",    "L_LatShank",     ("Gyr_Y",)),
    ("bif",   "R_DorsalFoot",  "L_DorsalFoot",   ("Gyr_Y",)),
    ("bith",  "R_MidLatThigh", "L_MidLatThigh",  ("Gyr_Y",)),
    ("axial", "LowerBack",     "Xiphoid",        ("Acc_Z",)),
    ("cerv",  "LowerBack",     "Forehead",       ("Acc_Z",)),
    ("lbrw",  "LowerBack",     "R_Wrist",        ("Acc_Z", "Gyr_Y")),
    ("lblw",  "LowerBack",     "L_Wrist",        ("Acc_Z", "Gyr_Y")),
    ("lbrsh", "LowerBack",     "R_LatShank",     ("Acc_Z", "Gyr_Y")),
    ("lblsh", "LowerBack",     "L_LatShank",     ("Acc_Z", "Gyr_Y")),
]


def detect_gait_fundamental(lumbar_acc_z: np.ndarray, fs: int = FS) -> float | None:
    """Find peak in 0.5-3 Hz band of Lumbar Acc_Z PSD. Return f in Hz or None."""
    if lumbar_acc_z is None or len(lumbar_acc_z) < fs * 3:
        return None
    x = lumbar_acc_z - np.mean(lumbar_acc_z)
    f, p = welch(x, fs=fs, nperseg=min(512, len(x)), noverlap=256)
    band = (f >= GAIT_BAND[0]) & (f <= GAIT_BAND[1])
    if not band.any() or p[band].max() < 1e-9:
        return None
    return float(f[band][np.argmax(p[band])])


def coherence_metrics(
    sig_a: np.ndarray, sig_b: np.ndarray, f_gait: float, fs: int = FS
) -> tuple[float, float, float]:
    """Return (coh@f_gait, coh@2*f_gait, coh_mean_0.5_3Hz). NaNs if signal too short."""
    if sig_a is None or sig_b is None:
        return float("nan"), float("nan"), float("nan")
    n = min(len(sig_a), len(sig_b))
    if n < COH_NPERSEG:
        return float("nan"), float("nan"), float("nan")
    a = sig_a[:n] - np.mean(sig_a[:n])
    b = sig_b[:n] - np.mean(sig_b[:n])
    f, c = coherence(a, b, fs=fs, nperseg=COH_NPERSEG, noverlap=COH_NOVERLAP)
    if c.size == 0:
        return float("nan"), float("nan"), float("nan")
    coh_f1 = float(np.interp(f_gait, f, c))
    coh_f2 = float(np.interp(min(2 * f_gait, fs / 2 - 0.01), f, c))
    band = (f >= GAIT_BAND[0]) & (f <= GAIT_BAND[1])
    coh_int = float(np.mean(c[band])) if band.any() else float("nan")
    return coh_f1, coh_f2, coh_int


def features_for_recording(df: pd.DataFrame, task: str) -> dict | None:
    """Return per-recording feature dict, or None if f_gait undetected."""
    lumbar_z_col = "LowerBack_Acc_Z"
    if lumbar_z_col not in df.columns:
        return None
    lumbar_z = df[lumbar_z_col].to_numpy(dtype=np.float64)
    f_gait = detect_gait_fundamental(lumbar_z)
    if f_gait is None or not (GAIT_BAND[0] <= f_gait <= GAIT_BAND[1]):
        return None
    feats: dict[str, float] = {"_f_gait": f_gait}
    for label, sa, sb, channels in PAIRS:
        for ch in channels:
            ca = f"{sa}_{ch}"
            cb = f"{sb}_{ch}"
            if ca not in df.columns or cb not in df.columns:
                feats[f"{label}_{ch}_coh_f1"] = float("nan")
                feats[f"{label}_{ch}_coh_f2"] = float("nan")
                feats[f"{label}_{ch}_coh_int"] = float("nan")
                continue
            sig_a = df[ca].to_numpy(dtype=np.float64)
            sig_b = df[cb].to_numpy(dtype=np.float64)
            c1, c2, ci = coherence_metrics(sig_a, sig_b, f_gait)
            feats[f"{label}_{ch}_coh_f1"] = c1
            feats[f"{label}_{ch}_coh_f2"] = c2
            feats[f"{label}_{ch}_coh_int"] = ci
    return feats


def process_subject(args: tuple[str, list[Path]]) -> tuple[str, dict]:
    sid, paths = args
    rec_feats: list[dict] = []
    for p in paths:
        try:
            df = pd.read_csv(p, low_memory=False)
        except Exception:
            continue
        # Determine task name from the file stem (e.g., NLS002_SelfPace.csv → SelfPace)
        stem = p.stem
        # Strip leading SID
        if "_" in stem:
            task = stem.split("_", 1)[1]
        else:
            continue
        if task not in GAIT_TASK_NAMES:
            continue
        feats = features_for_recording(df, task)
        if feats is None:
            continue
        rec_feats.append(feats)
    if not rec_feats:
        return sid, {}
    # Aggregate: mean and std across recordings per metric
    keys = sorted({k for r in rec_feats for k in r if not k.startswith("_")})
    agg: dict[str, float] = {}
    for k in keys:
        vals = np.array([r.get(k, np.nan) for r in rec_feats], dtype=np.float64)
        valid = vals[~np.isnan(vals)]
        if len(valid) == 0:
            agg[f"coh_mean_{k}"] = float("nan")
            agg[f"coh_std_{k}"] = float("nan")
        else:
            agg[f"coh_mean_{k}"] = float(np.mean(valid))
            agg[f"coh_std_{k}"] = float(np.std(valid)) if len(valid) > 1 else 0.0
    # f_gait stats (kept as feature)
    fg = np.array([r["_f_gait"] for r in rec_feats], dtype=np.float64)
    agg["coh_f_gait_mean"] = float(np.mean(fg))
    agg["coh_f_gait_std"] = float(np.std(fg)) if len(fg) > 1 else 0.0
    agg["coh_n_recordings"] = float(len(rec_feats))
    return sid, agg


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true",
                        help="Process 5 subjects only")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--csv-dir", type=Path, default=RAW_CSV_DIR_PD,
                        help="Directory containing raw PD CSVs")
    parser.add_argument("--out", type=Path,
                        default=RESULTS_DIR / "cross_sensor_coherence.csv")
    args = parser.parse_args()

    ensure_dir(RESULTS_DIR)

    if not args.csv_dir.exists():
        raise FileNotFoundError(f"Raw CSV dir not found: {args.csv_dir}")
    all_csvs = sorted(args.csv_dir.glob("*.csv"))
    # Group by subject
    by_sid: dict[str, list[Path]] = {}
    for p in all_csvs:
        sid = p.stem.split("_", 1)[0]
        by_sid.setdefault(sid, []).append(p)
    sids = sorted(by_sid.keys())
    if args.smoke:
        sids = sids[:5]
    print(f"[coh] Processing {len(sids)} subjects ({sum(len(by_sid[s]) for s in sids)} files)",
          flush=True)
    print(f"[coh] Pairs: {len(PAIRS)}, channels per pair: variable",
          flush=True)

    rows: list[dict] = []
    t0 = time.time()
    work = [(sid, by_sid[sid]) for sid in sids]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_subject, w): w[0] for w in work}
        done = 0
        for fut in as_completed(futures):
            sid, agg = fut.result()
            done += 1
            if not agg:
                print(f"[coh] {sid}: NO FEATURES (gait f undetected or no gait recordings)",
                      flush=True)
                continue
            row = {"sid": sid}
            row.update(agg)
            rows.append(row)
            if done % 10 == 0:
                print(f"[coh] {done}/{len(sids)} ({time.time()-t0:.0f}s)", flush=True)

    if not rows:
        print("[coh] FAILED: no rows produced", flush=True)
        return 1

    df = pd.DataFrame(rows)
    cols = ["sid"] + [c for c in df.columns if c != "sid"]
    df = df[cols]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    feat_cols = [c for c in df.columns if c != "sid"]
    nan_ratio = df[feat_cols].isna().mean().mean()
    print(f"[coh] Wrote {args.out} — {len(df)} rows × {len(feat_cols)} features, "
          f"NaN ratio = {nan_ratio:.3f}", flush=True)
    print(f"[coh] elapsed: {time.time()-t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
