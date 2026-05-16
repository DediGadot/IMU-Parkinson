"""V3 GSP (Graph Signal Processing) features on the anatomical body graph.

Hypothesis (codex + gemini convergent, 2026-05-12 consult):
  V2 fails to span the *multi-sensor global coordination* subspace. PD axial
  rigidity manifests as "en-bloc" motion — the body moves as a single rigid
  block, shifting mechanical energy from high spatial frequencies (articulated
  limbs) to the lowest spatial frequency (whole-body translation). V2's
  per-sensor statistics and pairwise coherence cannot quantify this because
  they decompose the body before measuring it.

Mechanism (gemini):
  1. Define a fixed anatomical adjacency graph on 13 IMU nodes.
  2. Compute Graph Laplacian L = D - A; eigendecompose L = U Λ U^T.
  3. U^T projects sensor-space to graph-spectrum space.
  4. Per task, compute temporal variance + energy of each graph-spectrum mode.
  5. Low-mode energy / total energy = en-bloc rigidity index.

Orthogonality to V2 (why this should NOT be absorbed by K=500):
  V2 features are *per-sensor* aggregates. GSP features are *coordinated*
  multi-sensor projections — they live in a different mathematical basis.
  A V2 feature like "LowerBack_am_rms" cannot reproduce "graph-mode-3 energy"
  because the latter requires simultaneous information from all 13 sensors
  with anatomical weighting.

Output: results/v3_gsp_features.csv (per-subject, per-task aggregated).
Manifest: per goal-v1 Tier-2 — label-free, fold_scope=global (computation does
not use labels). Cache_statistics_used=false.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import multiprocessing as mp
import os
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
OUT_PATH = RESULTS_DIR / "v3_gsp_features.csv"
MANIFEST_PATH = RESULTS_DIR / "v3_gsp_features.csv.manifest.json"

# 13 sensors in raw CSV column naming
SENSORS: list[str] = [
    "Forehead", "Xiphoid", "LowerBack",
    "L_Wrist", "R_Wrist",
    "L_MidLatThigh", "R_MidLatThigh",
    "L_LatShank", "R_LatShank",
    "L_Ankle", "R_Ankle",
    "L_DorsalFoot", "R_DorsalFoot",
]
N_SENSORS = len(SENSORS)
SENSOR_IDX = {s: i for i, s in enumerate(SENSORS)}

# Anatomical adjacency (skeleton-based; 12 edges, tree topology)
EDGES: list[tuple[str, str]] = [
    ("Forehead", "Xiphoid"),
    ("Xiphoid", "LowerBack"),
    ("Xiphoid", "L_Wrist"),
    ("Xiphoid", "R_Wrist"),
    ("LowerBack", "L_MidLatThigh"),
    ("LowerBack", "R_MidLatThigh"),
    ("L_MidLatThigh", "L_LatShank"),
    ("R_MidLatThigh", "R_LatShank"),
    ("L_LatShank", "L_Ankle"),
    ("R_LatShank", "R_Ankle"),
    ("L_Ankle", "L_DorsalFoot"),
    ("R_Ankle", "R_DorsalFoot"),
]

# Tasks we extract features from
TASKS: list[str] = [
    "SelfPace", "HurriedPace", "TUG", "TandemGait", "Balance",
]

# Channel kinds: accel magnitude, gyro magnitude (rotation rate)
CHANNEL_KINDS: list[str] = ["acc", "gyr"]

FS = 100  # Hz sample rate


def build_graph_laplacian() -> tuple[np.ndarray, np.ndarray]:
    """Return (eigvals, eigvecs) of the unnormalized graph Laplacian L = D - A.

    eigvals sorted ascending. eigvecs[:, k] is the k-th eigenvector.
    eigvecs is the graph-Fourier basis matrix U; the projection of a sensor-
    space signal x ∈ R^N to graph-spectrum is U^T @ x.
    """
    A = np.zeros((N_SENSORS, N_SENSORS), dtype=np.float64)
    for s1, s2 in EDGES:
        i, j = SENSOR_IDX[s1], SENSOR_IDX[s2]
        A[i, j] = 1.0
        A[j, i] = 1.0
    D = np.diag(A.sum(axis=1))
    L = D - A
    eigvals, eigvecs = np.linalg.eigh(L)
    return eigvals, eigvecs


def _sensor_magnitude(df: pd.DataFrame, sensor: str, kind: str) -> np.ndarray:
    """Return magnitude time series for sensor (acc or gyr) — shape (T,)."""
    if kind == "acc":
        cols = [f"{sensor}_Acc_X", f"{sensor}_Acc_Y", f"{sensor}_Acc_Z"]
    elif kind == "gyr":
        cols = [f"{sensor}_Gyr_X", f"{sensor}_Gyr_Y", f"{sensor}_Gyr_Z"]
    else:
        raise ValueError(f"unknown kind {kind!r}")
    for c in cols:
        if c not in df.columns:
            return None  # sensor missing
    arr = df[cols].to_numpy(dtype=np.float64)
    return np.sqrt(np.sum(arr ** 2, axis=1))


def _compute_gsp_features_one_recording(
    csv_path: Path, eigvecs: np.ndarray
) -> dict[str, float] | None:
    """Compute GSP features for one recording.

    For each channel kind (acc/gyr): build (T, N_SENSORS) signal matrix,
    project to graph spectrum (T, N_SENSORS), compute per-mode features.

    Features per kind: per mode (k=0..12): var, rms, p99(abs), energy_pct.
    Plus aggregate: low_mode_energy_pct (k<=3), high_mode_energy_pct (k>=10).
    """
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception:
        return None

    out: dict[str, float] = {}
    for kind in CHANNEL_KINDS:
        # Build sensor signal matrix (T, N_SENSORS)
        sigs = []
        valid = True
        for s in SENSORS:
            mag = _sensor_magnitude(df, s, kind)
            if mag is None or len(mag) < 50:
                valid = False
                break
            sigs.append(mag)
        if not valid:
            continue
        # Align lengths (some channels may have NaN truncation)
        T_min = min(len(s) for s in sigs)
        X = np.column_stack([s[:T_min] for s in sigs])  # (T, N_SENSORS)
        # Replace NaN with column mean
        col_mean = np.nanmean(X, axis=0)
        nan_mask = np.isnan(X)
        if nan_mask.any():
            X[nan_mask] = np.take(col_mean, np.where(nan_mask)[1])
        X = np.nan_to_num(X, nan=0.0)
        # Project to graph spectrum: X_spec = X @ U  (T, N_SENSORS)
        X_spec = X @ eigvecs
        # Per-mode features
        total_energy = float(np.sum(X_spec ** 2))
        for k in range(N_SENSORS):
            sig = X_spec[:, k]
            energy = float(np.sum(sig ** 2))
            out[f"gsp_{kind}_m{k:02d}_var"] = float(np.var(sig))
            out[f"gsp_{kind}_m{k:02d}_rms"] = float(np.sqrt(np.mean(sig ** 2)))
            out[f"gsp_{kind}_m{k:02d}_p99"] = float(
                np.percentile(np.abs(sig), 99)
            )
            out[f"gsp_{kind}_m{k:02d}_energy_pct"] = (
                energy / total_energy if total_energy > 1e-12 else 0.0
            )
        # En-bloc rigidity index: fraction of energy in low modes (k=0,1,2,3)
        low_e = float(np.sum(X_spec[:, :4] ** 2))
        high_e = float(np.sum(X_spec[:, 9:] ** 2))
        out[f"gsp_{kind}_low_mode_energy_pct"] = (
            low_e / total_energy if total_energy > 1e-12 else 0.0
        )
        out[f"gsp_{kind}_high_mode_energy_pct"] = (
            high_e / total_energy if total_energy > 1e-12 else 0.0
        )
        out[f"gsp_{kind}_en_bloc_index"] = (
            low_e / max(high_e, 1e-12)
        )  # high in PD rigidity
    return out


def _parse_sid_task(csv_path: Path) -> tuple[str, str] | None:
    """Parse filename like 'NLS142_SelfPace.csv' -> ('NLS142', 'SelfPace')."""
    stem = csv_path.stem  # e.g. 'NLS142_SelfPace'
    parts = stem.split("_", 1)
    if len(parts) != 2:
        return None
    sid, task_raw = parts[0], parts[1]
    # Normalize: drop '_mat' / '_matTURN' suffixes for task identity
    task = task_raw.replace("_mat", "").replace("TURN", "").strip("_")
    return sid, task


def _worker(args):
    csv_path_str, eigvecs_bytes = args
    eigvecs = np.frombuffer(eigvecs_bytes, dtype=np.float64).reshape(
        (N_SENSORS, N_SENSORS)
    )
    csv_path = Path(csv_path_str)
    out = _compute_gsp_features_one_recording(csv_path, eigvecs)
    if out is None:
        return None
    parsed = _parse_sid_task(csv_path)
    if parsed is None:
        return None
    sid, task = parsed
    return (sid, task, out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv_dir",
        default="/home/fiod/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files",
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--smoke", action="store_true", help="5 subjects only")
    args = ap.parse_args()

    eigvals, eigvecs = build_graph_laplacian()
    print(f"Graph Laplacian eigenvalues: {[f'{v:.4f}' for v in eigvals]}",
          flush=True)
    print(f"N edges = {len(EDGES)}, N sensors = {N_SENSORS}", flush=True)

    csv_dir = Path(args.csv_dir)
    if not csv_dir.exists():
        raise FileNotFoundError(f"CSV dir not found: {csv_dir}")
    csv_files = sorted(csv_dir.glob("*.csv"))
    if args.smoke:
        # First 5 subjects only
        seen_sids: set[str] = set()
        keep: list[Path] = []
        for p in csv_files:
            parsed = _parse_sid_task(p)
            if parsed is None:
                continue
            sid = parsed[0]
            if sid in seen_sids or len(seen_sids) < 5:
                seen_sids.add(sid)
                if len(seen_sids) <= 5:
                    keep.append(p)
            if len(seen_sids) > 5:
                break
        csv_files = keep

    print(f"Processing {len(csv_files)} CSV files with {args.workers} workers",
          flush=True)

    eigvecs_bytes = eigvecs.astype(np.float64).tobytes()
    job_args = [(str(p), eigvecs_bytes) for p in csv_files]

    t0 = time.time()
    rows: list[tuple[str, str, dict[str, float]]] = []
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers) as pool:
        for i, r in enumerate(pool.imap_unordered(_worker, job_args, chunksize=4)):
            if r is not None:
                rows.append(r)
            if (i + 1) % 50 == 0:
                print(
                    f"  {i+1}/{len(job_args)} files processed "
                    f"elapsed={time.time()-t0:.1f}s",
                    flush=True,
                )
    print(f"All files processed in {time.time()-t0:.1f}s. "
          f"Got {len(rows)} valid rows.", flush=True)

    if not rows:
        print("ERROR: no rows produced", flush=True)
        return

    # Aggregate per (sid, task) -> mean (in case mat/_TURN variants)
    by_sid_task: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for sid, task, feats in rows:
        by_sid_task[(sid, task)].append(feats)

    # Aggregate by mean
    feature_keys = sorted(set().union(*[set(feats.keys()) for feats in
                                        [r[2] for r in rows]]))
    print(f"  total feature keys = {len(feature_keys)}", flush=True)

    # Pivot to (sid, task) -> mean feature vector
    records: list[dict] = []
    for (sid, task), feat_list in by_sid_task.items():
        rec = {"sid": sid, "task": task}
        for k in feature_keys:
            vals = [f[k] for f in feat_list if k in f and np.isfinite(f[k])]
            rec[k] = float(np.mean(vals)) if vals else np.nan
        records.append(rec)

    df_long = pd.DataFrame(records)
    print(f"  long table shape = {df_long.shape}", flush=True)

    # Pivot to per-subject: each task's features become column-suffixed
    df_long_keep = df_long[df_long["task"].isin(TASKS)].copy()
    # Pivot: index=sid, columns=task, values=feature_keys
    pivoted = df_long_keep.set_index(["sid", "task"])[feature_keys].unstack("task")
    # Flatten multi-index columns: f"{feature}__{task}"
    pivoted.columns = [f"{feat}__{task}" for feat, task in pivoted.columns]
    pivoted = pivoted.reset_index()
    print(f"  pivoted (per-subject) shape = {pivoted.shape}", flush=True)

    pivoted.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH}", flush=True)

    # Manifest
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
        "script": "cache_v3_gsp_features.py",
        "git_sha": git_sha,
        "command": "uv run python cache_v3_gsp_features.py",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "labels_used": False,
        "cohort_statistics_used": False,
        "fold_scope": "global",
        "normalization_scope": "per-recording temporal variance/RMS; no cross-subject normalization",
        "graph_definition": {
            "sensors": SENSORS,
            "edges": EDGES,
            "edges_count": len(EDGES),
        },
        "laplacian_eigvals": [float(v) for v in eigvals],
        "channel_kinds": CHANNEL_KINDS,
        "tasks": TASKS,
        "n_features_total": pivoted.shape[1] - 1,  # minus sid
        "n_subjects": int(pivoted["sid"].nunique()),
        "source_artifacts": [
            f"raw CSV files in {csv_dir} (794 files at extraction time)",
        ],
        "rationale": "V3 features orthogonal to V2 — multi-sensor graph spectrum projection.",
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest {MANIFEST_PATH}", flush=True)


if __name__ == "__main__":
    main()
