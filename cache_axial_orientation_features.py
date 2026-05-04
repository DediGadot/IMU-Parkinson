"""Cache axial-orientation features (Euler RPY + FreeAcc ENU) for trunk sensors.

Targets the iter6 weakness: item 13 (posture, CCC=0.10) is a STATIC trunk-angle
assessment that magnitude-only IMU features cannot capture. This cache extracts
gravity-aligned orientation from the raw 22-channel CSVs.

Sensors: LowerBack (lumbar), Xiphoid (sternum), Forehead — 3 axial sensors.
Channels: Roll, Pitch, Yaw (Euler) + FreeAcc_E, FreeAcc_N, FreeAcc_U (gravity-removed).

Per-recording features (~30 per subject after aggregation):
  Block 1 — Static posture (all tasks):
    {sen}_pitch_mean        — median trunk pitch (the canonical posture predictor)
    {sen}_pitch_excur       — pitch range p95-p5
    {sen}_roll_mean         — lateral lean
    {sen}_roll_excur
  Block 2 — Stability (Balance/TandemGait first 1.5s standing):
    {sen}_pitch_sway_std    — postural sway magnitude
    {sen}_roll_sway_std
    {sen}_pitch_sway_jerk
  Block 3 — Velocity (gait):
    {sen}_pitch_pkvel       — peak pitch angular velocity
  Block 4 — FreeAcc propulsion (gait initiation, SelfPace/HurriedPace first 2s):
    {sen}_freeacc_E_init    — forward push intensity
    {sen}_freeacc_U_pkvel   — vertical jerk

Aggregated per subject by mean across recordings (NaN-safe).

Usage:
  uv run python cache_axial_orientation_features.py
  python3 cache_axial_orientation_features.py --smoke
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir

# --- Configuration ---
DATA_DIR = Path(os.environ.get("WEARGAIT_DATA_DIR", "/root/pd-imu/data/raw/weargait-pd"))
PD_CSV_DIR = DATA_DIR / "PD PARTICIPANTS" / "CSV files"

OUT_PATH = RESULTS_DIR / "axial_orientation_features.csv"
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 12)))
FS = 100  # Hz

AXIAL_SENSORS = ["LowerBack", "Xiphoid", "Forehead"]
EULER_COLS = ["Roll", "Pitch", "Yaw"]
FREEACC_COLS = ["FreeAcc_E", "FreeAcc_N", "FreeAcc_U"]

GAIT_INIT_TASKS = {"SelfPace", "SelfPace_mat", "HurriedPace", "HurriedPace_mat"}
STABILITY_TASKS = {"Balance", "Balance_mat", "TandemGait", "TandemGait_mat"}


def axial_features_one_recording(df: pd.DataFrame, sensor: str, task: str) -> dict:
    """Extract ~10 axial features for a single sensor/task combination.

    Robust to missing columns: returns NaN where channels absent.
    """
    feats: dict = {}
    pitch_col = f"{sensor}_Pitch"
    roll_col = f"{sensor}_Roll"
    yaw_col = f"{sensor}_Yaw"
    fae_col = f"{sensor}_FreeAcc_E"
    fau_col = f"{sensor}_FreeAcc_U"

    has_euler = all(c in df.columns for c in (pitch_col, roll_col, yaw_col))
    has_freeacc = fae_col in df.columns and fau_col in df.columns

    if has_euler:
        pitch = df[pitch_col].astype(np.float32).values
        roll = df[roll_col].astype(np.float32).values
        # Block 1 — Static posture (all tasks)
        if pitch.size > 5:
            feats[f"ax_{sensor}_pitch_mean"] = float(np.nanmedian(pitch))
            feats[f"ax_{sensor}_pitch_excur"] = float(np.nanpercentile(pitch, 95) - np.nanpercentile(pitch, 5))
            feats[f"ax_{sensor}_roll_mean"] = float(np.nanmedian(roll))
            feats[f"ax_{sensor}_roll_excur"] = float(np.nanpercentile(roll, 95) - np.nanpercentile(roll, 5))
            feats[f"ax_{sensor}_pitch_pkvel"] = float(np.nanmax(np.abs(np.diff(pitch))) * FS)
        # Block 2 — Stability windows
        if task in STABILITY_TASKS and pitch.size > int(1.5 * FS) * 2:
            seg_n = int(1.5 * FS)
            front = pitch[:seg_n]
            r_front = roll[:seg_n]
            feats[f"ax_{sensor}_pitch_sway_std"] = float(np.nanstd(front))
            feats[f"ax_{sensor}_roll_sway_std"] = float(np.nanstd(r_front))
            if front.size > 1:
                feats[f"ax_{sensor}_pitch_sway_jerk"] = float(np.sqrt(np.nanmean(np.diff(front).astype(np.float64) ** 2)))

    if has_freeacc and task in GAIT_INIT_TASKS:
        fae = df[fae_col].astype(np.float32).values
        fau = df[fau_col].astype(np.float32).values
        seg_n = int(2.0 * FS)
        if fae.size > seg_n:
            front_e = fae[:seg_n]
            front_u = fau[:seg_n]
            feats[f"ax_{sensor}_freeacc_E_init"] = float(np.nanpercentile(np.abs(front_e), 90))
            if front_u.size > 1:
                feats[f"ax_{sensor}_freeacc_U_pkvel"] = float(np.nanmax(np.abs(np.diff(front_u))) * FS)
    return feats


def _process_one_csv(args) -> dict | None:
    csv_path, sid, task = args
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception as exc:  # pragma: no cover
        print(f"[skip] {csv_path}: {exc}", file=sys.stderr)
        return None
    feats: dict = {"sid": sid, "task": task}
    for sen in AXIAL_SENSORS:
        feats.update(axial_features_one_recording(df, sen, task))
    return feats


def parse_filename(path: Path) -> tuple[str, str] | None:
    """`NLS035_SelfPace.csv` → ('NLS035', 'SelfPace'); supports task variants."""
    name = path.stem
    if "_" not in name:
        return None
    sid, task = name.split("_", 1)
    return sid, task


def collect_jobs(csv_dir: Path) -> list[tuple[Path, str, str]]:
    if not csv_dir.exists():
        raise FileNotFoundError(f"{csv_dir} not present — has the Synapse download finished?")
    jobs = []
    for csv in csv_dir.glob("*.csv"):
        parsed = parse_filename(csv)
        if parsed is None:
            continue
        sid, task = parsed
        jobs.append((csv, sid, task))
    return jobs


def aggregate_per_subject(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "sid" not in df.columns:
        raise RuntimeError("No rows produced — check parsing")
    feat_cols = [c for c in df.columns if c not in ("sid", "task")]
    agg = df.groupby("sid")[feat_cols].mean(numeric_only=True).reset_index()
    return agg


def smoke_check(df: pd.DataFrame) -> None:
    n_subj = len(df)
    if n_subj < 30:
        raise RuntimeError(f"Too few subjects: {n_subj}")
    feat_cols = [c for c in df.columns if c.startswith("ax_")]
    if len(feat_cols) < 15:
        raise RuntimeError(f"Too few axial features: {len(feat_cols)} (expected ~25-30)")
    pitch_means = df.filter(like="_pitch_mean").values
    if pitch_means.size and not np.any(np.isfinite(pitch_means)):
        raise RuntimeError("All pitch_mean values NaN — Euler channels missing in raw CSVs?")
    nz_frac = float(np.isfinite(pitch_means).mean())
    print(f"  smoke OK: {n_subj} subjects, {len(feat_cols)} axial features, pitch_mean coverage={nz_frac:.2%}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="process first 5 CSVs only")
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--csv_dir", default=str(PD_CSV_DIR))
    args = ap.parse_args()

    ensure_dir(RESULTS_DIR)
    csv_dir = Path(args.csv_dir)
    jobs = collect_jobs(csv_dir)
    if not jobs:
        raise RuntimeError(f"No CSV files in {csv_dir}")
    print(f"Found {len(jobs)} CSV recordings in {csv_dir}")

    if args.smoke:
        jobs = jobs[:5]
        print(f"  smoke mode: keeping first {len(jobs)} jobs")

    print(f"Extracting axial features with {N_CORES} workers...")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        rows = [r for r in pool.map(_process_one_csv, jobs, chunksize=8) if r]
    print(f"  {len(rows)} recordings processed in {time.time() - t0:.0f}s")

    if args.smoke:
        df_smoke = pd.DataFrame(rows)
        print(df_smoke[[c for c in df_smoke.columns if c in ("sid", "task") or "pitch_mean" in c or "freeacc" in c]].head(10))
        return

    agg = aggregate_per_subject(rows)
    smoke_check(agg)
    out_path = Path(args.out)
    agg.to_csv(out_path, index=False)
    print(f"Wrote {agg.shape[0]} rows × {agg.shape[1]} cols → {out_path}")


if __name__ == "__main__":
    main()
