#!/usr/bin/env python3
"""Extract target-free TUG phase-specific PH/MFDFA microfeatures.

This cache is a narrow follow-through on `/tmp/pro-results.txt` rank #8:
PH/MFDFA over TUG phases instead of whole-task TUG summaries.

Phases are deterministic and label-free:
  - sit_to_stand: LowerBack Acc-Z absolute peak in first third, [-0.8s, +2.0s]
  - steady_walk: after sit-to-stand recovery until before the turn peak
  - turning: LowerBack Gyr-Z absolute peak in second half, [-1.0s, +1.5s]
  - turn_to_sit: LowerBack Acc-Z absolute peak in final third, [-1.5s, +1.0s]

For each phase we reuse the existing PH/MFDFA signal-processing primitives from
`cache_stepfunction_features.py`; no target labels, cohort statistics, or fold
statistics enter extraction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from cache_stepfunction_features import mfdfa_features_per_task, ph_features_per_task
from project_paths import RESULTS_DIR, ensure_dir


ROOT = Path(__file__).resolve().parent
FS = 100.0

DEFAULT_DATA_DIRS = (
    ROOT / "data" / "raw" / "weargait-pd" / "PD PARTICIPANTS" / "CSV files",
    Path.home() / "pd-imu" / "data" / "raw" / "weargait-pd" / "PD PARTICIPANTS" / "CSV files",
    Path("/root/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files"),
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def df_sha256(df: pd.DataFrame) -> str:
    return hashlib.sha256(df.sort_values("sid").to_csv(index=False).encode()).hexdigest()


def resolve_data_dir(override: str | None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("WEARGAIT_DATA_DIR")
    if env:
        cand = Path(env) / "PD PARTICIPANTS" / "CSV files"
        if cand.exists():
            return cand
        cand = Path(env)
        if cand.exists():
            return cand
    for cand in DEFAULT_DATA_DIRS:
        if cand.exists():
            return cand
    raise FileNotFoundError("No WearGait-PD CSV directory found")


def resolve_col(columns: set[str], sensor: str, channel: str) -> str | None:
    for cand in (f"{sensor}_{channel}", f"{sensor}{channel}"):
        if cand in columns:
            return cand
    return None


def numeric_col(df: pd.DataFrame, sensor: str, channel: str) -> np.ndarray | None:
    col = resolve_col(set(df.columns), sensor, channel)
    if col is None:
        return None
    x = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
    if np.isfinite(x).sum() < 20:
        return None
    return pd.Series(x).interpolate(limit_direction="both").to_numpy(dtype=float)


def window_bounds(center: int, pre_s: float, post_s: float, n: int) -> tuple[int, int]:
    a = max(0, int(center - pre_s * FS))
    b = min(n, int(center + post_s * FS))
    return a, b


def find_phase_windows(df: pd.DataFrame) -> dict[str, tuple[int, int]]:
    n = len(df)
    if n < int(5 * FS):
        return {}
    acc_z = numeric_col(df, "LowerBack", "Acc_Z")
    gyr_z = numeric_col(df, "LowerBack", "Gyr_Z")
    if acc_z is None or gyr_z is None:
        return {}

    first_third = max(int(n / 3), int(1.0 * FS))
    final_start = min(max(int(2 * n / 3), 0), n - 1)
    half = n // 2

    stand_idx = int(np.nanargmax(np.abs(acc_z[:first_third])))
    turn_idx = half + int(np.nanargmax(np.abs(gyr_z[half:])))
    sit_idx = final_start + int(np.nanargmax(np.abs(acc_z[final_start:])))

    phases: dict[str, tuple[int, int]] = {
        "sit_to_stand": window_bounds(stand_idx, 0.8, 2.0, n),
        "turning": window_bounds(turn_idx, 1.0, 1.5, n),
        "turn_to_sit": window_bounds(sit_idx, 1.5, 1.0, n),
    }

    walk_a = min(n, int(stand_idx + 2.0 * FS))
    walk_b = max(0, int(turn_idx - 1.0 * FS))
    if walk_b - walk_a >= int(2.0 * FS):
        phases["steady_walk"] = (walk_a, walk_b)
    return phases


def phase_feature_block(df: pd.DataFrame, phase_name: str, a: int, b: int) -> dict[str, float]:
    if b - a < int(1.0 * FS):
        return {}
    seg = df.iloc[a:b].reset_index(drop=True)
    out: dict[str, float] = {
        f"phase_{phase_name}_duration_s": float((b - a) / FS),
    }
    for k, v in ph_features_per_task(seg).items():
        out[f"phase_{phase_name}_{k}"] = float(v)
    for k, v in mfdfa_features_per_task(seg).items():
        out[f"phase_{phase_name}_{k}"] = float(v)
    return out


def process_one(job: tuple[Path, str]) -> dict[str, float] | None:
    path, sid = job
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return None
    phases = find_phase_windows(df)
    if not phases:
        return None
    row: dict[str, float] = {"sid": sid}
    for phase, (a, b) in phases.items():
        row.update(phase_feature_block(df, phase, a, b))
    return row


def collect_jobs(csv_dir: Path) -> list[tuple[Path, str]]:
    if not csv_dir.exists():
        raise FileNotFoundError(f"{csv_dir} not found")
    jobs = []
    for path in sorted(csv_dir.glob("*.csv")):
        stem = path.stem
        if "_" not in stem:
            continue
        sid, task = stem.split("_", 1)
        if task == "TUG" and (sid.startswith("NLS") or sid.startswith("WPD")):
            jobs.append((path, sid))
    return jobs


def write_manifest(
    out_path: Path,
    df: pd.DataFrame,
    csv_dir: Path,
    command: str,
    n_jobs: int,
    git_sha_value: str,
) -> None:
    feature_cols = [c for c in df.columns if c != "sid"]
    manifest = {
        "script": Path(__file__).name,
        "script_sha256": file_sha256(Path(__file__)),
        "git_sha": git_sha_value,
        "command": command,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_sha256": df_sha256(df),
        "labels_used": False,
        "fold_scope": "global",
        "cohort_statistics_used": False,
        "normalization_scope": "per_subject_phase_window",
        "leakage_status": "clean_by_construction",
        "leakage_rationale": (
            "TUG phase windows are deterministic functions of raw LowerBack Acc-Z/Gyr-Z. "
            "PH/MFDFA features are extracted per subject/phase with no UPDRS labels, "
            "no cohort statistics, and no target-derived selection."
        ),
        "source_artifacts": [str(csv_dir)],
        "host": socket.gethostname(),
        "n_jobs_seen": int(n_jobs),
        "n_subjects": int(len(df)),
        "n_features": int(len(feature_cols)),
        "phase_policy": {
            "sit_to_stand": "LowerBack Acc-Z abs peak in first third, [-0.8s,+2.0s]",
            "steady_walk": "stand_peak+2.0s to turn_peak-1.0s if >=2.0s",
            "turning": "LowerBack Gyr-Z abs peak in second half, [-1.0s,+1.5s]",
            "turn_to_sit": "LowerBack Acc-Z abs peak in final third, [-1.5s,+1.0s]",
        },
    }
    out_path.with_suffix(out_path.suffix + ".manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 4, 12))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--git-sha",
        default=None,
        help="Source git SHA from the master checkout; useful because gpu.sh deploys without .git.",
    )
    args = parser.parse_args()

    ensure_dir(RESULTS_DIR)
    csv_dir = resolve_data_dir(args.data_dir)
    jobs = collect_jobs(csv_dir)
    if args.limit:
        jobs = jobs[: args.limit]
    if not jobs:
        raise RuntimeError(f"No canonical TUG CSVs found in {csv_dir}")

    out_path = Path(args.out) if args.out else RESULTS_DIR / f"cache_tug_phase_ph_mfdfa_{utc_stamp()}.csv"
    print(f"[cache_tug_phase_ph_mfdfa] jobs={len(jobs)} workers={args.workers} csv_dir={csv_dir}")
    t0 = time.time()
    rows: list[dict[str, float]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(process_one, job) for job in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            row = fut.result()
            if row:
                rows.append(row)
            if i % 20 == 0 or i == len(futs):
                print(f"  processed {i}/{len(futs)} rows_kept={len(rows)}", flush=True)

    if not rows:
        raise RuntimeError("No phase PH/MFDFA rows produced")
    df = pd.DataFrame(rows).sort_values("sid").reset_index(drop=True)
    df.to_csv(out_path, index=False)
    write_manifest(
        out_path,
        df,
        csv_dir,
        " ".join(sys.argv),
        n_jobs=len(jobs),
        git_sha_value=args.git_sha or git_sha(),
    )
    print(f"Wrote {df.shape[0]} rows x {df.shape[1]} cols -> {out_path}")
    print(f"Elapsed {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
