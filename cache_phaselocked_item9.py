"""Cache phase-locked item-9 (chair-rise / 3.9) features.

Slot C of T1 ceiling push (axis 5 — per-item phase-locked, F50-style).

Item 3.9 (Arising from Chair) is the TUG sit-to-stand transient. UPDRS scores
0-4 reflect speed and stability of the rise. Phase-locked features detect the
seat-off event in the TUG recording and compute a small, hypothesis-restricted
set of biomechanical descriptors of that single transient.

Method:
  1. For each subject, read TUG.csv (NOT TUG_mat).
  2. Detect seat-off via Lumbar (LowerBack) Acc-Z magnitude argmax in first 1/3
     of the recording (after de-mean). Same trigger as cache_item9_event_moment.
  3. Around seat-off [-0.8s, +2.0s] @ 100 Hz extract:
       - peak vertical acceleration (LowerBack Acc-Z)
       - time-to-peak (s, post-seat-off)
       - peak thigh angular velocity (R_LatShank Gyr-Y)
       - peak shank angular velocity asymmetry (|L|-|R|)
       - pre-stand quiet variance (250-ms pre-window)
       - post-stand stability variance (500-ms post-window)
       - jerk integral (∫|d/dt(Acc-Z)| over event window)
       - sternum (Xiphoid) pitch peak velocity (trunk forward lean rate)
       - rise-event duration (time from seat-off to next quiet plateau)
       - peak-to-peak amplitude (Acc-Z 95th - 5th percentile)
  4. Aggregate per subject = mean across recordings (typically 1 TUG per subject).

Output: results/phaselocked_item9_features.csv + .manifest.json (NO labels used).

Usage:
  uv run python cache_phaselocked_item9.py [--smoke] [--csv_dir <path>] [--out <path>]
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

# --- Configuration ---
DATA_DIR = Path(os.environ.get("WEARGAIT_DATA_DIR", str(Path.home() / "pd-imu" / "data" / "raw" / "weargait-pd")))
PD_CSV_DIR = DATA_DIR / "PD PARTICIPANTS" / "CSV files"

OUT_PATH = RESULTS_DIR / "phaselocked_item9_features.csv"
MANIFEST_PATH = RESULTS_DIR / "phaselocked_item9_features.csv.manifest.json"
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 11)))
FS = 100.0  # Hz
PRE_S = 0.8
POST_S = 2.0
PRE_QUIET_S = 0.25
POST_STABLE_S = 0.5

LUMBAR = "LowerBack"
STERNUM = "Xiphoid"


def _resolve_col(df_cols: set, sensor: str, channel: str) -> str | None:
    for cand in (f"{sensor}_{channel}", f"{sensor}{channel}"):
        if cand in df_cols:
            return cand
    return None


def _detect_seat_off(lumbar_acc_z: np.ndarray) -> int | None:
    if len(lumbar_acc_z) < int(FS * 2):
        return None
    sig = np.abs(np.nan_to_num(lumbar_acc_z - np.nanmean(lumbar_acc_z), nan=0.0))
    upto = max(int(len(sig) // 3), int(FS * 4))
    upto = min(upto, len(sig))
    return int(np.argmax(sig[:upto]))


def phaselocked_item9_features(df: pd.DataFrame) -> dict:
    """Return ~10 phase-locked descriptors of the TUG sit-to-stand transient."""
    feats: dict = {}
    cols = set(df.columns)
    lumb_z = _resolve_col(cols, LUMBAR, "Acc_Z")
    if lumb_z is None or lumb_z not in df.columns:
        return feats
    sig_z = df[lumb_z].astype(np.float32).to_numpy()
    if len(sig_z) < int(FS * 3):
        return feats
    seat_off = _detect_seat_off(sig_z)
    if seat_off is None:
        return feats
    pre_n = int(PRE_S * FS)
    post_n = int(POST_S * FS)
    a, b = max(0, seat_off - pre_n), min(len(sig_z), seat_off + post_n)
    if b - a < int(FS * 1.5):
        return feats

    z_event = sig_z[a:b]
    # Peak Acc-Z (event)
    z_dem = np.nan_to_num(z_event - np.nanmean(z_event), nan=0.0)
    feats["pl9_z_peak_abs"] = float(np.nanmax(np.abs(z_dem)))
    # Time-to-peak relative to seat_off (signed, in seconds)
    pk_idx = int(np.nanargmax(np.abs(z_dem)))
    feats["pl9_z_time_to_peak_s"] = float((pk_idx - (seat_off - a)) / FS)
    # Peak-to-peak (95th - 5th percentile)
    feats["pl9_z_p95_p5"] = float(np.nanpercentile(z_event, 95) - np.nanpercentile(z_event, 5))
    # Jerk integral over event window
    if len(z_event) > 2:
        feats["pl9_z_jerk_int"] = float(np.nansum(np.abs(np.diff(z_event))) * FS)

    # Pre-stand quiet variance (250 ms pre-window)
    qpre_n = int(PRE_QUIET_S * FS)
    if seat_off - qpre_n > 0:
        qpre = sig_z[seat_off - qpre_n : seat_off]
        feats["pl9_pre_quiet_std"] = float(np.nanstd(qpre))

    # Post-stand stability variance (500 ms after the peak)
    pst_n = int(POST_STABLE_S * FS)
    pst_start = a + pk_idx
    if pst_start + pst_n < len(sig_z):
        pst = sig_z[pst_start : pst_start + pst_n]
        feats["pl9_post_stable_std"] = float(np.nanstd(pst))

    # Rise-event duration (time from seat_off until Acc-Z |z|<=0.4*peak for 100 ms)
    pk = float(np.nanmax(np.abs(z_dem)) + 1e-9)
    thresh = 0.4 * pk
    quiet_run = 0
    end_idx = len(z_dem) - 1
    for i in range(int(seat_off - a), len(z_dem)):
        if abs(z_dem[i]) < thresh:
            quiet_run += 1
            if quiet_run >= int(0.1 * FS):
                end_idx = i - quiet_run + 1
                break
        else:
            quiet_run = 0
    feats["pl9_rise_duration_s"] = float((end_idx - (seat_off - a)) / FS)

    # Thigh / shank angular velocity peaks
    for side in ("L", "R"):
        gyr_col = _resolve_col(cols, f"{side}_LatShank", "Gyr_Y")
        if gyr_col and gyr_col in df.columns:
            gy = df[gyr_col].astype(np.float32).to_numpy()
            if a < len(gy) and b <= len(gy):
                gy_evt = gy[a:b]
                feats[f"pl9_shank_{side}_gyr_y_peak"] = float(np.nanmax(np.abs(gy_evt)))

    # L/R asymmetry of shank Gyr-Y peak
    lp = feats.get("pl9_shank_L_gyr_y_peak")
    rp = feats.get("pl9_shank_R_gyr_y_peak")
    if lp is not None and rp is not None and (lp + rp) > 1e-6:
        feats["pl9_shank_LR_asym"] = float(abs(lp - rp) / (abs(lp) + abs(rp) + 1e-6))

    # Sternum/Xiphoid pitch peak velocity (trunk lean rate).
    # Unwrap to handle Euler-angle wrap; clip non-physiological diffs.
    pit_col = _resolve_col(cols, STERNUM, "Pitch")
    if pit_col and pit_col in df.columns:
        pit = df[pit_col].astype(np.float32).to_numpy()
        if a < len(pit) and b <= len(pit) and (b - a) > 1:
            pit_evt = np.unwrap(np.deg2rad(pit[a:b].astype(np.float64))) * (180.0 / np.pi)
            d_pit = np.diff(pit_evt) * FS
            d_pit = d_pit[np.abs(d_pit) < 720.0]
            if d_pit.size:
                feats["pl9_sternum_pitch_pkvel"] = float(np.nanmax(np.abs(d_pit)))
    return feats


def _process_one(args) -> dict | None:
    csv_path, sid = args
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception as exc:
        print(f"[skip] {csv_path}: {exc}", file=sys.stderr)
        return None
    feats = phaselocked_item9_features(df)
    if not feats:
        return None
    feats.update({"sid": sid})
    return feats


def collect_jobs(csv_dir: Path) -> list[tuple[Path, str]]:
    if not csv_dir.exists():
        raise FileNotFoundError(f"{csv_dir} not present — Synapse download incomplete?")
    jobs = []
    for csv in sorted(csv_dir.glob("*.csv")):
        name = csv.stem
        if "_" not in name:
            continue
        sid, task = name.split("_", 1)
        # Restrict to canonical TUG (NOT TUG_mat / TUG_matTURN)
        if task == "TUG":
            jobs.append((csv, sid))
    return jobs


def aggregate_per_subject(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "sid" not in df.columns:
        raise RuntimeError("No rows produced — check parsing")
    feat_cols = [c for c in df.columns if c.startswith("pl9_")]
    agg = df.groupby("sid")[feat_cols].mean(numeric_only=True).reset_index()
    return agg


def _data_sha256(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update(df.sort_values("sid").to_csv(index=False).encode())
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _script_sha256() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def write_manifest(df: pd.DataFrame, csv_path: Path, csv_dir: Path, n_jobs: int) -> None:
    feat_cols = [c for c in df.columns if c.startswith("pl9_")]
    manifest = {
        "schema_version": 1,
        "produced_by": "cache_phaselocked_item9.py",
        "script_sha256": _script_sha256(),
        "git_sha": _git_sha(),
        "iso_datetime_utc": datetime.now(timezone.utc).isoformat(),
        "data_sha256": _data_sha256(df),
        "n_subjects": int(len(df)),
        "n_features": int(len(feat_cols)),
        "labels_used": False,
        "fold_scope": "global",
        "leakage_status": "clean_by_construction",
        "leakage_argument": (
            "Phase-locked TUG sit-to-stand features are deterministic signal-processing "
            "aggregates of raw IMU channels (Lumbar Acc-Z trigger, Lumbar/Sternum/Shank "
            "Acc/Gyr/Pitch around seat-off event window). UPDRS-III labels never enter "
            "the extraction. Aggregation across recordings per subject uses mean only — "
            "no global statistics. Slot C of T1 ceiling push (axis 5)."
        ),
        "constants_locked": {
            "fs_hz": FS,
            "event_pre_s": PRE_S,
            "event_post_s": POST_S,
            "pre_quiet_s": PRE_QUIET_S,
            "post_stable_s": POST_STABLE_S,
            "trigger": "Lumbar (LowerBack) Acc-Z absolute argmax in first 1/3 of TUG",
            "task_filter": "TUG only (excludes TUG_mat, TUG_matTURN)",
        },
        "command": " ".join(sys.argv),
        "csv_dir": str(csv_dir),
        "n_jobs_processed": int(n_jobs),
        "out_path": str(csv_path),
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest written → {MANIFEST_PATH}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--csv_dir", default=str(PD_CSV_DIR))
    ap.add_argument("--n_workers", type=int, default=N_CORES)
    args = ap.parse_args()

    ensure_dir(RESULTS_DIR)
    csv_dir = Path(args.csv_dir)
    jobs = collect_jobs(csv_dir)
    if not jobs:
        raise RuntimeError(f"No TUG CSVs in {csv_dir}")
    print(f"Found {len(jobs)} TUG recordings in {csv_dir}", flush=True)

    if args.smoke:
        jobs = jobs[:5]
        print(f"  smoke: keeping first {len(jobs)} jobs", flush=True)

    print(f"Extracting phase-locked item-9 features with {args.n_workers} workers...", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.n_workers) as pool:
        rows = [r for r in pool.map(_process_one, jobs, chunksize=4) if r]
    print(f"  {len(rows)}/{len(jobs)} recordings processed in {time.time() - t0:.0f}s", flush=True)
    if args.smoke:
        df_smoke = pd.DataFrame(rows)
        print(df_smoke.head())
        return

    agg = aggregate_per_subject(rows)
    out_path = Path(args.out)
    agg.to_csv(out_path, index=False)
    print(f"Wrote {agg.shape[0]} rows × {agg.shape[1]} cols → {out_path}", flush=True)
    write_manifest(agg, out_path, csv_dir, n_jobs=len(jobs))


if __name__ == "__main__":
    main()
