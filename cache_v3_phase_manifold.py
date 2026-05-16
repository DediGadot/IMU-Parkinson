"""V3 Phase Manifold (PM) features — geometric nonlinear gait-cycle manifold.

Kimi's #1 pick (2026-05-12 4-CLI consult, expected ΔCCC +0.006 to +0.022):
  V2 averages stats in 39-D sensor ambient space. V3-GSP linearly projects via
  fixed graph Laplacian. NEITHER captures the low-dimensional NONLINEAR manifold
  that the 13-sensor point cloud traverses during a gait cycle.

Mechanism (kimi):
  Per gait cycle: extract 39-D trajectory (13 sensors × 3 axes = LowerBack +
  Xiphoid + L/R wrist/thigh/shank/foot Acc XYZ). Compute per-subject covariance
  of cycle-phase samples. Features:
    (a) Participation ratio = (Σλ_i)² / Σλ_i² (effective dimensionality)
    (b) Trajectory length / displacement ratio (rigidity index)
    (c) Top-3 eigenvalue entropy
    (d) Eigenvalue ratios λ_1/λ_2, λ_2/λ_3
    (e) Spectral compression: fraction of variance in top-3 eigenvalues

PD axial rigidity collapses the manifold to fewer effective dimensions → low
participation ratio + high λ_1/λ_2.

Orthogonality vs V2 + V3-GSP:
  V2 = statistical moments in ambient space.
  V3-GSP = linear graph Fourier projection.
  Phase Manifold = geometric invariants of the nonlinear cycle manifold.

Compute: ~2 min/subject CPU.
Output: results/v3_phase_manifold_features.csv.
"""
from __future__ import annotations

import argparse
import glob
import json
import multiprocessing as mp
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir

ensure_dir(RESULTS_DIR)
OUT_PATH = RESULTS_DIR / "v3_phase_manifold_features.csv"
MANIFEST_PATH = RESULTS_DIR / "v3_phase_manifold_features.csv.manifest.json"

FS = 100  # Hz

# 13 sensors x 3 axes = 39-D state vector
SENSORS = [
    "Forehead", "Xiphoid", "LowerBack",
    "L_Wrist", "R_Wrist",
    "L_MidLatThigh", "R_MidLatThigh",
    "L_LatShank", "R_LatShank",
    "L_Ankle", "R_Ankle",
    "L_DorsalFoot", "R_DorsalFoot",
]
AXES = ["X", "Y", "Z"]
TASKS_GAIT: list[str] = ["SelfPace", "HurriedPace", "TandemGait"]
N_PHASE_SAMPLES = 50  # resample each cycle to fixed phase grid


def _detect_strikes(contact_signal: np.ndarray) -> np.ndarray:
    c = (contact_signal > 0.5).astype(np.int8)
    edges = np.where(np.diff(c) > 0)[0] + 1
    return edges


def _build_state_matrix(df: pd.DataFrame) -> np.ndarray | None:
    """Construct (T, 39) state matrix from FreeAcc ENU of 13 sensors.

    FreeAcc removes gravity, so it captures dynamic motion. ENU is gravity-aligned.
    Returns None if any sensor missing.
    """
    cols = []
    for s in SENSORS:
        for ax in ["E", "N", "U"]:
            c = f"{s}_FreeAcc_{ax}"
            if c not in df.columns:
                return None
            cols.append(c)
    return df[cols].to_numpy(dtype=np.float64)


def _resample_cycle(traj_chunk: np.ndarray, n: int = N_PHASE_SAMPLES) -> np.ndarray:
    """Resample a stride trajectory (T_stride, D) to fixed (n, D) phase grid."""
    T = len(traj_chunk)
    if T < 5:
        return None
    old_t = np.linspace(0, 1, T)
    new_t = np.linspace(0, 1, n)
    resampled = np.zeros((n, traj_chunk.shape[1]), dtype=np.float64)
    for d in range(traj_chunk.shape[1]):
        col = traj_chunk[:, d]
        if not np.all(np.isfinite(col)):
            col = np.nan_to_num(col, nan=0.0)
        resampled[:, d] = np.interp(new_t, old_t, col)
    return resampled


def _phase_manifold_features(cycles: list[np.ndarray]) -> dict[str, float]:
    """Compute manifold geometric invariants over a set of resampled cycles.

    cycles: list of (n_phase, 39) matrices.
    Returns dict of features.
    """
    out: dict[str, float] = {}
    if len(cycles) < 3:
        return out

    # Stack all cycles' phase samples: (N_cycles * n_phase, 39)
    all_samples = np.vstack(cycles)
    n_samples = all_samples.shape[0]
    if n_samples < 50:
        return out
    # Center
    mean = all_samples.mean(axis=0)
    centered = all_samples - mean
    # Covariance (39, 39)
    cov = (centered.T @ centered) / (n_samples - 1)
    # Eigenvalues (descending)
    try:
        eigvals = np.linalg.eigvalsh(cov)
    except np.linalg.LinAlgError:
        return out
    eigvals = np.sort(eigvals)[::-1]
    eigvals = np.maximum(eigvals, 1e-12)
    total = float(np.sum(eigvals))
    sq_total = float(np.sum(eigvals ** 2))

    # Participation ratio = (sum)^2 / sum_sq — effective dimensionality
    out["pm_participation_ratio"] = (total ** 2) / sq_total if sq_total > 0 else 0.0
    # Spectral compression: fraction of variance in top-K
    for k in (1, 3, 5, 10):
        out[f"pm_top{k}_var_frac"] = (
            float(eigvals[:k].sum() / total) if total > 0 else 0.0
        )
    # Top eigenvalue ratios (mode separation)
    out["pm_lambda1_over_lambda2"] = float(eigvals[0] / (eigvals[1] + 1e-12))
    out["pm_lambda2_over_lambda3"] = float(eigvals[1] / (eigvals[2] + 1e-12))
    out["pm_lambda3_over_lambda4"] = float(eigvals[2] / (eigvals[3] + 1e-12))
    # Eigenvalue entropy (normalized)
    p = eigvals / total
    p = p[p > 1e-12]
    out["pm_eigvalue_entropy"] = float(-np.sum(p * np.log(p)) / np.log(len(eigvals)))
    # Top-3 eigenvalue raw
    out["pm_lambda1"] = float(eigvals[0])
    out["pm_lambda2"] = float(eigvals[1])
    out["pm_lambda3"] = float(eigvals[2])
    # Total variance (proxy for motion intensity — will correlate with V2 but useful baseline)
    out["pm_total_variance"] = total

    # Trajectory geometry: per-cycle trajectory length / cycle-mean displacement
    traj_lengths = []
    cycle_displacements = []
    for c in cycles:
        diffs = np.diff(c, axis=0)
        traj_len = float(np.sum(np.linalg.norm(diffs, axis=1)))
        traj_lengths.append(traj_len)
        # Displacement: distance between start and end of cycle (should be ~0 for periodic)
        disp = float(np.linalg.norm(c[-1] - c[0]))
        cycle_displacements.append(disp)
    traj_lengths_arr = np.array(traj_lengths)
    cycle_displacements_arr = np.array(cycle_displacements)
    out["pm_traj_length_median"] = float(np.median(traj_lengths_arr))
    out["pm_traj_length_cv"] = float(traj_lengths_arr.std() / max(traj_lengths_arr.mean(), 1e-12))
    out["pm_cycle_disp_median"] = float(np.median(cycle_displacements_arr))
    out["pm_rigidity_idx"] = float(
        np.median(cycle_displacements_arr) / max(np.median(traj_lengths_arr), 1e-12)
    )
    out["n_cycles_used"] = float(len(cycles))
    return out


def _process_one_recording(csv_path_str: str) -> tuple[str, str, dict[str, float]] | None:
    csv_path = Path(csv_path_str)
    stem = csv_path.stem
    parts = stem.split("_", 1)
    if len(parts) != 2:
        return None
    sid, task_raw = parts
    task = task_raw.replace("_mat", "").replace("TURN", "").strip("_")
    if task not in TASKS_GAIT:
        return None
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception:
        return None

    if "L Foot Contact" not in df.columns:
        return None
    strikes_L = _detect_strikes(df["L Foot Contact"].to_numpy())
    if len(strikes_L) < 4:
        return None
    state = _build_state_matrix(df)
    if state is None:
        return None

    # Extract per-cycle (L heel-strike to next L heel-strike) chunks
    cycles: list[np.ndarray] = []
    for i in range(len(strikes_L) - 1):
        s0, s1 = strikes_L[i], strikes_L[i + 1]
        if s1 - s0 < 30 or s1 - s0 > 250:
            continue
        chunk = state[s0:s1]
        rs = _resample_cycle(chunk, N_PHASE_SAMPLES)
        if rs is not None:
            cycles.append(rs)
    if not cycles:
        return None
    feats = _phase_manifold_features(cycles)
    if not feats:
        return None
    return (sid, task, feats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv_dir",
        default="/home/fiod/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files",
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    csv_dir = Path(args.csv_dir)
    csv_files = sorted(csv_dir.glob("*.csv"))
    if args.smoke:
        seen: set[str] = set()
        keep = []
        for p in csv_files:
            sid = p.stem.split("_", 1)[0]
            if sid not in seen:
                if len(seen) >= 5:
                    break
                seen.add(sid)
            keep.append(p)
        csv_files = keep

    gait_csvs = []
    for p in csv_files:
        stem = p.stem
        task_raw = stem.split("_", 1)[1] if "_" in stem else ""
        task = task_raw.replace("_mat", "").replace("TURN", "").strip("_")
        if task in TASKS_GAIT:
            gait_csvs.append(p)

    print(f"Processing {len(gait_csvs)} gait CSVs with {args.workers} workers",
          flush=True)
    t0 = time.time()
    rows: list[tuple[str, str, dict]] = []
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers) as pool:
        for i, r in enumerate(
            pool.imap_unordered(_process_one_recording, [str(p) for p in gait_csvs], chunksize=4)
        ):
            if r is not None:
                rows.append(r)
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(gait_csvs)} elapsed={time.time()-t0:.0f}s",
                      flush=True)
    print(f"Done in {time.time()-t0:.0f}s. Valid rows: {len(rows)}", flush=True)
    if not rows:
        print("ERROR: no rows", flush=True); return

    by_sid_task: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for sid, task, feats in rows:
        by_sid_task[(sid, task)].append(feats)
    feature_keys = sorted(set().union(*[set(r[2].keys()) for r in rows]))

    records = []
    for (sid, task), feat_list in by_sid_task.items():
        rec = {"sid": sid, "task": task}
        for k in feature_keys:
            vals = [f[k] for f in feat_list if k in f and np.isfinite(f[k])]
            rec[k] = float(np.mean(vals)) if vals else np.nan
        records.append(rec)
    df_long = pd.DataFrame(records)
    print(f"  long shape = {df_long.shape}", flush=True)

    pivoted = df_long.set_index(["sid", "task"])[feature_keys].unstack("task")
    pivoted.columns = [f"{feat}__{task}" for feat, task in pivoted.columns]
    pivoted = pivoted.reset_index()
    print(f"  pivoted shape = {pivoted.shape}", flush=True)
    pivoted.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH}", flush=True)

    git_sha = "unknown"
    try:
        import subprocess
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        pass
    manifest = {
        "script": "cache_v3_phase_manifold_features.py",
        "git_sha": git_sha,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "labels_used": False,
        "cohort_statistics_used": False,
        "fold_scope": "global",
        "tasks": TASKS_GAIT,
        "n_phase_samples": N_PHASE_SAMPLES,
        "rationale": "V3 Phase Manifold: nonlinear gait-cycle manifold geometric invariants (participation ratio, rigidity idx); orthogonal to V2 statistical moments and V3-GSP linear graph Fourier.",
        "n_features_total": pivoted.shape[1] - 1,
        "n_subjects": int(pivoted["sid"].nunique()),
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest {MANIFEST_PATH}", flush=True)


if __name__ == "__main__":
    main()
