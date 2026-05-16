"""Cache FoG event statistics + standing balance posture geometry features.

Slot B of T1 Glass-Ceiling Push 2026-05-10 (master pre-reg
results/preregistration_t1_ceiling_push_20260510_134829.json).

PIVOT FROM ORIGINAL kymatio-scattering DESIGN per tri-CLI synthesis 2026-05-10:
3-of-3 CLIs (codex+gemini+kimi) said SKIP kymatio scattering plan due to V2
redundancy wall + PCA-50-on-N-74 noise mapping. 2-of-3 (codex+kimi) converged
on alternative: REPRESENTATION CHANGE for items 11+13 specifically — discrete
event statistics (item 11 FoG) + low-dim standing-segment geometry (item 13)
forced-include into chain step inputs (bypassing K=500 absorption).

WHY this is mechanistically distinct from F-iter54 axial Euler:
  - F-iter54 used 30 axial features (Lumbar/Xiphoid/Forehead × Roll/Pitch/Yaw +
    FreeAcc) extracted across all gait tasks; gate-failed at +0.046 5-fold via
    K=500 absorption (joint pool variant) and variance.
  - Slot B is a FOCUSED 6-8 dim block targeting two phenomenological axes V2
    cannot encode well: (a) episodic FoG event statistics, distinct from V2's
    continuous Welch power bands; (b) postural-tilt geometry from Balance
    (standing) task only, distinct from gait-pooled axial features.
  - Architecture: forced-include the 6-8 dim block into K=500 pool (pre-K500
    selection); chain step routing keeps fog stats with item 11 and posture
    geometry with item 13 (slot A's post-K500 routing pattern).

Item 11 (FoG / 3.11 freezing of gait):
  - Detector: Lumbar (LowerBack) Acc-mag bandpass 3-8 Hz envelope > 1.5 SD
    above local mean for ≥0.5 s in SelfPace + HurriedPace gait segments.
  - Per subject features (3): fog_event_rate (events/min walking),
    fog_event_duration_mean, fog_event_duration_std (variability).

Item 13 (3.13 Posture):
  - Source: Balance task only (standing-still surrogate; no StandStill task in
    WearGait-PD).
  - Per subject features (5): bal_lumbar_pitch_mean (median forward/back lean),
    bal_lumbar_pitch_excur (sway range), bal_lumbar_roll_mean (lateral lean),
    bal_xiphoid_pitch_mean (trunk vs lumbar tilt — relative geometry),
    bal_forehead_pitch_mean (head-trunk coupling).

Total: 8 features per subject. UPDRS labels never enter extraction.

Output: results/fog_events_balance_geometry.csv + .manifest.json (label-free,
fold_scope=global, leakage_status=clean_by_construction).

Usage:
  uv run python cache_fog_events_balance_geometry.py [--smoke] [--csv_dir <path>] [--out <path>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir

DATA_DIR = Path(os.environ.get("WEARGAIT_DATA_DIR", "/home/fiod/pd-imu/data/raw/weargait-pd"))
PD_CSV_DIR = DATA_DIR / "PD PARTICIPANTS" / "CSV files"

OUT_PATH = RESULTS_DIR / "fog_events_balance_geometry.csv"
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 12)))
FS = 100  # Hz

GAIT_TASKS = {"SelfPace", "HurriedPace"}  # exclude _mat / _matTURN to keep clean cohort
BALANCE_TASKS = {"Balance"}

# FoG band: 3-8 Hz per Moore et al. 2008; freezing index = power ratio in this band
FOG_BAND_LO = 3.0
FOG_BAND_HI = 8.0
FOG_THRESH_SD = 1.5
FOG_MIN_DURATION_S = 0.5


def _bandpass_envelope(x: np.ndarray, lo: float, hi: float, fs: int = FS) -> np.ndarray:
    """Return bandpass envelope [lo,hi] Hz via FFT × Hilbert magnitude."""
    n = len(x)
    if n < 64:
        return np.zeros(n)
    # FFT bandpass
    X = np.fft.rfft(x - np.mean(x))
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    mask = (freqs >= lo) & (freqs <= hi)
    X_band = np.zeros_like(X)
    X_band[mask] = X[mask]
    x_band = np.fft.irfft(X_band, n=n)
    # Envelope = |Hilbert| ≈ moving-average magnitude
    env = np.convolve(np.abs(x_band), np.ones(int(0.1 * fs)) / int(0.1 * fs), mode="same")
    return env


def fog_event_features(df: pd.DataFrame, task: str) -> dict:
    """Detect FoG-like events in Lumbar Acc-mag bandpass; return event stats."""
    if task not in GAIT_TASKS:
        return {}
    cols = ["LowerBack_Acc_X", "LowerBack_Acc_Y", "LowerBack_Acc_Z"]
    if not all(c in df.columns for c in cols):
        return {"fog_event_rate": np.nan, "fog_event_duration_mean": np.nan, "fog_event_duration_std": np.nan}
    acc_mag = np.sqrt(df[cols[0]].values**2 + df[cols[1]].values**2 + df[cols[2]].values**2)
    acc_mag = acc_mag - np.nanmean(acc_mag)
    if not np.any(np.isfinite(acc_mag)) or len(acc_mag) < FS * 2:
        return {"fog_event_rate": np.nan, "fog_event_duration_mean": np.nan, "fog_event_duration_std": np.nan}
    env = _bandpass_envelope(acc_mag, FOG_BAND_LO, FOG_BAND_HI, FS)
    if env.std() < 1e-9:
        return {"fog_event_rate": np.nan, "fog_event_duration_mean": np.nan, "fog_event_duration_std": np.nan}
    threshold = float(np.nanmean(env) + FOG_THRESH_SD * np.nanstd(env))
    above = env > threshold
    # Find contiguous events of length >= 0.5s
    durations_s: list[float] = []
    in_event = False
    start = 0
    for i, hi_v in enumerate(above):
        if hi_v and not in_event:
            in_event = True; start = i
        elif not hi_v and in_event:
            duration = (i - start) / FS
            if duration >= FOG_MIN_DURATION_S:
                durations_s.append(duration)
            in_event = False
    if in_event:
        duration = (len(above) - start) / FS
        if duration >= FOG_MIN_DURATION_S:
            durations_s.append(duration)
    walk_minutes = len(acc_mag) / FS / 60.0
    if walk_minutes < 0.05:
        return {"fog_event_rate": np.nan, "fog_event_duration_mean": np.nan, "fog_event_duration_std": np.nan}
    return {
        "fog_event_rate": len(durations_s) / walk_minutes,
        "fog_event_duration_mean": float(np.mean(durations_s)) if durations_s else 0.0,
        "fog_event_duration_std": float(np.std(durations_s, ddof=1)) if len(durations_s) > 1 else 0.0,
    }


def balance_geometry_features(df: pd.DataFrame, task: str) -> dict:
    """Standing-segment posture geometry from Balance task. Return 5 features."""
    if task not in BALANCE_TASKS:
        return {}
    out: dict = {}
    for sen, prefix in [("LowerBack", "bal_lumbar"), ("Xiphoid", "bal_xiphoid"), ("Forehead", "bal_forehead")]:
        pcol = f"{sen}_Pitch"
        rcol = f"{sen}_Roll"
        if pcol in df.columns:
            p = df[pcol].values.astype(float)
            p = p[np.isfinite(p)]
            out[f"{prefix}_pitch_mean"] = float(np.median(p)) if p.size > 10 else np.nan
            if sen == "LowerBack":
                out[f"{prefix}_pitch_excur"] = float(np.percentile(p, 95) - np.percentile(p, 5)) if p.size > 10 else np.nan
        if rcol in df.columns and sen == "LowerBack":
            r = df[rcol].values.astype(float); r = r[np.isfinite(r)]
            out[f"{prefix}_roll_mean"] = float(np.median(r)) if r.size > 10 else np.nan
    return out


def _process_one_csv(args) -> dict | None:
    csv_path, sid, task = args
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception as e:
        print(f"[skip] {csv_path}: {e}", file=sys.stderr); return None
    feats: dict = {"sid": sid, "task": task}
    feats.update(fog_event_features(df, task))
    feats.update(balance_geometry_features(df, task))
    return feats


def parse_filename(path: Path) -> tuple[str, str] | None:
    name = path.stem
    if "_" not in name:
        return None
    sid, task = name.split("_", 1)
    return sid, task


def collect_jobs(csv_dir: Path) -> list[tuple[Path, str, str]]:
    if not csv_dir.exists():
        raise FileNotFoundError(f"{csv_dir} not present")
    jobs = []
    for csv in csv_dir.glob("*.csv"):
        parsed = parse_filename(csv)
        if parsed is None:
            continue
        sid, task = parsed
        if task in GAIT_TASKS or task in BALANCE_TASKS:
            jobs.append((csv, sid, task))
    return jobs


def aggregate_per_subject(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "sid" not in df.columns:
        raise RuntimeError("No rows produced")
    feat_cols = [c for c in df.columns if c not in ("sid", "task")]
    # FoG features: aggregate across SelfPace + HurriedPace (mean)
    fog_cols = [c for c in feat_cols if c.startswith("fog_")]
    bal_cols = [c for c in feat_cols if c.startswith("bal_")]
    agg_fog = df[df["task"].isin(GAIT_TASKS)].groupby("sid")[fog_cols].mean(numeric_only=True).reset_index()
    agg_bal = df[df["task"].isin(BALANCE_TASKS)].groupby("sid")[bal_cols].mean(numeric_only=True).reset_index()
    out = agg_fog.merge(agg_bal, on="sid", how="outer")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--csv_dir", default=str(PD_CSV_DIR))
    args = ap.parse_args()

    ensure_dir(RESULTS_DIR)
    csv_dir = Path(args.csv_dir)
    jobs = collect_jobs(csv_dir)
    if not jobs:
        raise RuntimeError(f"No CSV files in {csv_dir}")
    print(f"Found {len(jobs)} CSV recordings (gait + balance) in {csv_dir}", flush=True)

    if args.smoke:
        jobs = jobs[:5]
        print(f"  smoke mode: keeping first {len(jobs)} jobs", flush=True)

    t0 = time.time()
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        rows = [r for r in pool.map(_process_one_csv, jobs, chunksize=4) if r]
    print(f"  {len(rows)} recordings processed in {time.time()-t0:.0f}s", flush=True)

    if args.smoke:
        df_s = pd.DataFrame(rows)
        print(df_s.head(8))
        return

    agg = aggregate_per_subject(rows)
    out_path = Path(args.out)
    agg.to_csv(out_path, index=False)
    print(f"Wrote {agg.shape[0]} rows × {agg.shape[1]} cols → {out_path}", flush=True)

    # Manifest sidecar
    sids_sorted = sorted(map(str, agg["sid"].tolist()))
    sids_hash = hashlib.sha256("|".join(sids_sorted).encode()).hexdigest()
    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:
        git_sha = "unknown"
    manifest = {
        "schema_version": 1,
        "produced_by": "cache_fog_events_balance_geometry.py",
        "script_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
        "git_sha": git_sha,
        "iso_datetime_utc": datetime.now(timezone.utc).isoformat(),
        "data_sha256": hashlib.sha256(pd.util.hash_pandas_object(agg, index=True).values.tobytes()).hexdigest(),
        "n_subjects": int(agg.shape[0]),
        "n_features": int(agg.shape[1] - 1),
        "labels_used": False,
        "fold_scope": "global",
        "leakage_status": "clean_by_construction",
        "leakage_argument": (
            "All features are deterministic signal-processing aggregates of raw IMU. "
            "FoG event statistics: bandpass envelope thresholding on Lumbar Acc-mag, "
            "no labels referenced. Balance geometry: median pitch/roll on Balance task "
            "Euler angles, no labels. Aggregation is per-subject mean across recordings. "
            "Slot B of T1 ceiling push (representation change for items 11+13)."
        ),
        "constants_locked": {
            "fs_hz": FS, "fog_band_lo_hz": FOG_BAND_LO, "fog_band_hi_hz": FOG_BAND_HI,
            "fog_threshold_sd": FOG_THRESH_SD, "fog_min_duration_s": FOG_MIN_DURATION_S,
            "gait_tasks": sorted(GAIT_TASKS), "balance_tasks": sorted(BALANCE_TASKS),
        },
        "command": " ".join(sys.argv),
        "csv_dir": str(csv_dir),
        "n_jobs_processed": len(rows),
        "out_path": str(out_path),
        "included_sids_hash": sids_hash,
    }
    manifest_path = out_path.with_suffix(out_path.suffix + ".manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  manifest → {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
