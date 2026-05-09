"""Cache phase-locked item-12 (postural stability / 3.12 pull-test) features.

Slot C of T1 ceiling push (axis 5 — per-item phase-locked, F50-style).

Item 3.12 (Postural Stability) is the pull-test, but pull-tests are NOT recorded
in WearGait-PD. The closest in-dataset surrogate is the TUG turn (lateral
postural recovery while pivoting): UPDRS scores 0-4 reflect ability to recover
balance, which the turn phase exposes through trunk angular velocity and
recovery dynamics.

Method:
  1. For each subject, read TUG.csv (NOT TUG_mat).
  2. Detect TUG turn via Lumbar (LowerBack) Gyr-Z absolute peak in the second
     half of the recording (after walking out, before walking back).
  3. Around turn-peak [-1.0s, +1.5s] @ 100 Hz extract:
       - peak yaw angular velocity (LowerBack Gyr-Z) — turn intensity
       - turn duration (s, time |Gyr-Z| > 0.3 * peak)
       - lateral sway during turn (LowerBack Roll p95-p5)
       - vertical jerk during turn (LowerBack Acc-Z RMS jerk)
       - post-turn step recovery (Lumbar Acc-mag std in 0.5-1.5 s post-turn)
       - L/R shank Gyr-Y peak asymmetry during turn
       - Sternum (Xiphoid) Roll excursion during turn
       - Forehead Yaw peak velocity (head-trunk coupling)
       - Pre-turn stability (Lumbar Acc-mag std in 0.5 s pre-turn)
       - Turn yaw integral (∫|Gyr-Z| over turn window)

Output: results/phaselocked_item12_features.csv + .manifest.json (NO labels used).

Usage:
  uv run python cache_phaselocked_item12.py [--smoke] [--csv_dir <path>] [--out <path>]
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

DATA_DIR = Path(os.environ.get("WEARGAIT_DATA_DIR", str(Path.home() / "pd-imu" / "data" / "raw" / "weargait-pd")))
PD_CSV_DIR = DATA_DIR / "PD PARTICIPANTS" / "CSV files"

OUT_PATH = RESULTS_DIR / "phaselocked_item12_features.csv"
MANIFEST_PATH = RESULTS_DIR / "phaselocked_item12_features.csv.manifest.json"
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 11)))
FS = 100.0  # Hz
TURN_PRE_S = 1.0
TURN_POST_S = 1.5
PRE_PRE_QUIET_S = 0.5
POST_RECOVERY_S = 1.0

LUMBAR = "LowerBack"
STERNUM = "Xiphoid"
HEAD = "Forehead"


def _resolve_col(df_cols: set, sensor: str, channel: str) -> str | None:
    for cand in (f"{sensor}_{channel}", f"{sensor}{channel}"):
        if cand in df_cols:
            return cand
    return None


def _detect_turn(lumbar_gyr_z: np.ndarray) -> int | None:
    if len(lumbar_gyr_z) < int(FS * 4):
        return None
    sig = np.abs(np.nan_to_num(lumbar_gyr_z, nan=0.0))
    half = len(sig) // 2
    return half + int(np.argmax(sig[half:]))


def phaselocked_item12_features(df: pd.DataFrame) -> dict:
    """Return ~10 phase-locked descriptors of TUG turn (postural-stability surrogate)."""
    feats: dict = {}
    cols = set(df.columns)
    gz_col = _resolve_col(cols, LUMBAR, "Gyr_Z")
    if gz_col is None or gz_col not in df.columns:
        return feats
    gz = df[gz_col].astype(np.float32).to_numpy()
    if len(gz) < int(FS * 4):
        return feats
    turn_idx = _detect_turn(gz)
    if turn_idx is None:
        return feats
    pre_n = int(TURN_PRE_S * FS)
    post_n = int(TURN_POST_S * FS)
    a, b = max(0, turn_idx - pre_n), min(len(gz), turn_idx + post_n)
    if b - a < int(FS * 1.0):
        return feats

    gz_evt = gz[a:b]
    gz_pk = float(np.nanmax(np.abs(gz_evt)))
    feats["pl12_yaw_peak"] = gz_pk
    # Turn duration (where |Gyr-Z| exceeds 0.3 * peak)
    if gz_pk > 1e-9:
        mask = np.abs(gz_evt) > 0.3 * gz_pk
        feats["pl12_turn_duration_s"] = float(mask.sum() / FS)
    # Yaw integral over turn window
    feats["pl12_yaw_integral"] = float(np.nansum(np.abs(gz_evt)) / FS)

    # Lateral sway via Roll
    roll_col = _resolve_col(cols, LUMBAR, "Roll")
    if roll_col and roll_col in df.columns:
        roll = df[roll_col].astype(np.float32).to_numpy()
        if a < len(roll) and b <= len(roll) and (b - a) > 2:
            r_evt = roll[a:b]
            feats["pl12_lumbar_roll_excur"] = float(np.nanpercentile(r_evt, 95) - np.nanpercentile(r_evt, 5))

    # Vertical jerk during turn (RMS of d/dt(Acc-Z))
    az_col = _resolve_col(cols, LUMBAR, "Acc_Z")
    if az_col and az_col in df.columns:
        az = df[az_col].astype(np.float32).to_numpy()
        if a < len(az) and b <= len(az) and (b - a) > 2:
            jz = np.diff(az[a:b]).astype(np.float64)
            feats["pl12_lumbar_acc_z_jerk_rms"] = float(np.sqrt(np.nanmean(jz**2)) * FS)

    # Pre-turn stability (Lumbar Acc-mag std in 0.5 s pre-turn)
    ax_col = _resolve_col(cols, LUMBAR, "Acc_X")
    ay_col = _resolve_col(cols, LUMBAR, "Acc_Y")
    if az_col and ax_col and ay_col:
        ax = df[ax_col].astype(np.float32).to_numpy()
        ay = df[ay_col].astype(np.float32).to_numpy()
        az = df[az_col].astype(np.float32).to_numpy()
        n_min = min(len(ax), len(ay), len(az))
        if turn_idx < n_min:
            mag = np.sqrt(ax[:n_min] ** 2 + ay[:n_min] ** 2 + az[:n_min] ** 2)
            qpre_n = int(PRE_PRE_QUIET_S * FS)
            if turn_idx - qpre_n > 0:
                feats["pl12_pre_turn_mag_std"] = float(np.nanstd(mag[turn_idx - qpre_n : turn_idx]))
            # Post-turn recovery (1 s after turn-peak)
            rec_n = int(POST_RECOVERY_S * FS)
            if turn_idx + rec_n < n_min:
                feats["pl12_post_turn_recovery_std"] = float(np.nanstd(mag[turn_idx : turn_idx + rec_n]))

    # L/R shank Gyr-Y peak during turn
    for side in ("L", "R"):
        gy_col = _resolve_col(cols, f"{side}_LatShank", "Gyr_Y")
        if gy_col and gy_col in df.columns:
            gy = df[gy_col].astype(np.float32).to_numpy()
            if a < len(gy) and b <= len(gy):
                feats[f"pl12_shank_{side}_gyr_y_peak"] = float(np.nanmax(np.abs(gy[a:b])))
    lp = feats.get("pl12_shank_L_gyr_y_peak")
    rp = feats.get("pl12_shank_R_gyr_y_peak")
    if lp is not None and rp is not None and (lp + rp) > 1e-6:
        feats["pl12_shank_LR_asym"] = float(abs(lp - rp) / (abs(lp) + abs(rp) + 1e-6))

    # Sternum Roll excursion during turn (trunk tilt during pivot)
    s_roll = _resolve_col(cols, STERNUM, "Roll")
    if s_roll and s_roll in df.columns:
        sr = df[s_roll].astype(np.float32).to_numpy()
        if a < len(sr) and b <= len(sr) and (b - a) > 2:
            feats["pl12_sternum_roll_excur"] = float(np.nanpercentile(sr[a:b], 95) - np.nanpercentile(sr[a:b], 5))

    # Forehead Yaw peak velocity (head-trunk coupling proxy).
    # Apply unwrap to handle ±180° discontinuities; clip absurdly large diffs from
    # any residual single-sample wrap that survives unwrap.
    h_yaw = _resolve_col(cols, HEAD, "Yaw")
    if h_yaw and h_yaw in df.columns:
        hy = df[h_yaw].astype(np.float32).to_numpy()
        if a < len(hy) and b <= len(hy) and (b - a) > 1:
            yaw_evt = np.unwrap(np.deg2rad(hy[a:b].astype(np.float64))) * (180.0 / np.pi)
            d_yaw = np.diff(yaw_evt) * FS
            # Clip residual wraps (rate > 720 deg/s is non-physiological for head)
            d_yaw = d_yaw[np.abs(d_yaw) < 720.0]
            if d_yaw.size:
                feats["pl12_forehead_yaw_pkvel"] = float(np.nanmax(np.abs(d_yaw)))
    return feats


def _process_one(args) -> dict | None:
    csv_path, sid = args
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception as exc:
        print(f"[skip] {csv_path}: {exc}", file=sys.stderr)
        return None
    feats = phaselocked_item12_features(df)
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
        if task == "TUG":
            jobs.append((csv, sid))
    return jobs


def aggregate_per_subject(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "sid" not in df.columns:
        raise RuntimeError("No rows produced — check parsing")
    feat_cols = [c for c in df.columns if c.startswith("pl12_")]
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
    feat_cols = [c for c in df.columns if c.startswith("pl12_")]
    manifest = {
        "schema_version": 1,
        "produced_by": "cache_phaselocked_item12.py",
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
            "Phase-locked TUG-turn features are deterministic signal-processing aggregates "
            "of raw IMU channels (Lumbar Gyr-Z trigger in second half, then Lumbar/Sternum/"
            "Forehead/Shank Acc/Gyr/Roll/Yaw around the turn peak window). UPDRS-III labels "
            "never enter the extraction. Per-subject mean across recordings is the only "
            "aggregation; no global statistics fit. Slot C of T1 ceiling push (axis 5)."
        ),
        "constants_locked": {
            "fs_hz": FS,
            "turn_pre_s": TURN_PRE_S,
            "turn_post_s": TURN_POST_S,
            "pre_quiet_s": PRE_PRE_QUIET_S,
            "post_recovery_s": POST_RECOVERY_S,
            "trigger": "Lumbar (LowerBack) Gyr-Z absolute argmax in second half of TUG",
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

    print(f"Extracting phase-locked item-12 features with {args.n_workers} workers...", flush=True)
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
