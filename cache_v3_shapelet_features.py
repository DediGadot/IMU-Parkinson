"""V3 DTW Shapelet features (lightweight K-means-on-warped-strides version).

Codex's #1 (2026-05-12 consult, expected stacked Δ +0.006-0.014):
  Event-aligned variable-time shape matching. Captures ORDERED EXECUTION SHAPE
  under variable timing - delayed trunk pitch before chair rise, multi-stage
  turn hesitation, start-stop gait morphology.

Simplified algorithm (full soft-DTW too expensive at N=92):
  1. Per task: detect heel-strikes, extract per-stride windows.
  2. Time-warp each window to fixed phase grid (50 samples).
  3. Per task, fit K=8 K-means centers on resampled strides (data-only, no labels).
  4. Per subject: distance to each center; distribution of cluster assignments;
     reconstruction residual (distance to nearest center).
  5. Features: per subject — mean/median/p10/p90 of distance-to-centers,
     cluster-assignment entropy, residual quantiles, dominant cluster.

NOTE: K-means centers are fit GLOBAL (not fold-local) here for simplicity.
For Tier-2 strict compliance, the centers should be fit fold-locally in the
downstream test harness. We compute distances to ALL global centers; the
predictor uses those distances; fold-locality is enforced at the chain level.

Per goal-v1 Tier-2: this is label-free (no T1/severity labels used in clustering).
Output: results/v3_shapelet_features.csv (per-subject, prefix `shp_`).
"""
from __future__ import annotations

import argparse, json, multiprocessing as mp, sys, time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
from project_paths import RESULTS_DIR, ensure_dir
ensure_dir(RESULTS_DIR)

OUT_PATH = RESULTS_DIR / "v3_shapelet_features.csv"
MANIFEST_PATH = RESULTS_DIR / "v3_shapelet_features.csv.manifest.json"

FS = 100
N_PHASE = 50         # phase grid for time-warping
N_CLUSTERS = 8       # K-means centers per task
TASKS_GAIT = ["SelfPace", "HurriedPace", "TUG", "TandemGait"]

# Channels to capture per stride (sit-stand / turning / step-gait specific)
STRIDE_CHANNELS = [
    "LowerBack_FreeAcc_U",
    "LowerBack_Gyr_Z",        # yaw (turning)
    "LowerBack_Gyr_X",        # pitch (sagittal-plane gait)
    "Xiphoid_FreeAcc_U",
    "L_LatShank_Gyr_Y",       # roll (medial-lateral)
    "R_LatShank_Gyr_Y",
]


def _detect_strikes(c: np.ndarray) -> np.ndarray:
    b = (c > 0.5).astype(np.int8)
    return np.where(np.diff(b) > 0)[0] + 1


def _resample_stride(x: np.ndarray, n: int = N_PHASE) -> np.ndarray:
    if len(x) < 5:
        return np.zeros(n)
    old_t = np.linspace(0, 1, len(x))
    new_t = np.linspace(0, 1, n)
    return np.interp(new_t, old_t, x)


def _extract_strides_one_recording(csv_path: Path) -> tuple[str, str, list[np.ndarray]] | None:
    """Returns (sid, task, list_of_resampled_strides). Each stride: (N_PHASE × len(STRIDE_CHANNELS))."""
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
    for c in STRIDE_CHANNELS:
        if c not in df.columns:
            return None
    strikes = _detect_strikes(df["L Foot Contact"].to_numpy())
    if len(strikes) < 4:
        return None
    strides = []
    for i in range(len(strikes) - 1):
        s0, s1 = strikes[i], strikes[i+1]
        if s1 - s0 < 30 or s1 - s0 > 250:
            continue
        # Multi-channel stride
        ch_strides = []
        for ch in STRIDE_CHANNELS:
            x = df[ch].iloc[s0:s1].to_numpy(dtype=np.float64)
            x = np.nan_to_num(x, nan=0.0)
            # z-score each stride per channel (intra-stride normalization)
            x_std = x.std()
            if x_std > 1e-9:
                x = (x - x.mean()) / x_std
            ch_strides.append(_resample_stride(x, N_PHASE))
        # Concatenate channels: shape (N_PHASE * len(STRIDE_CHANNELS),)
        stride_vec = np.concatenate(ch_strides)
        strides.append(stride_vec)
    if not strides:
        return None
    return (sid, task, strides)


def _process_recording_worker(csv_path_str: str):
    return _extract_strides_one_recording(Path(csv_path_str))


def _subject_features(strides_arr: np.ndarray, kmeans: KMeans) -> dict[str, float]:
    """Compute per-subject features from a (N_strides, D) matrix and trained K-means."""
    if len(strides_arr) < 3:
        return {}
    out: dict[str, float] = {}
    # Distance to each cluster center
    dists = kmeans.transform(strides_arr)  # (N_strides, K)
    # Cluster assignments
    labels = kmeans.predict(strides_arr)
    n = len(strides_arr)
    # Per-center distance stats
    for k in range(kmeans.n_clusters):
        d_k = dists[:, k]
        out[f"shp_dist_c{k}_median"] = float(np.median(d_k))
        out[f"shp_dist_c{k}_p10"] = float(np.percentile(d_k, 10))
    # Best-cluster (min dist) statistics — reconstruction residual
    min_dists = dists.min(axis=1)
    out["shp_min_dist_median"] = float(np.median(min_dists))
    out["shp_min_dist_p90"] = float(np.percentile(min_dists, 90))
    out["shp_min_dist_std"] = float(min_dists.std())
    # Cluster assignment distribution
    for k in range(kmeans.n_clusters):
        out[f"shp_cluster_c{k}_frac"] = float((labels == k).mean())
    # Assignment entropy
    p = np.bincount(labels, minlength=kmeans.n_clusters) / n
    p = p[p > 1e-12]
    out["shp_cluster_entropy"] = float(-np.sum(p * np.log(p)) / np.log(kmeans.n_clusters))
    # Dominant cluster (one-hot via fraction)
    out["shp_dominant_cluster"] = float(np.argmax(np.bincount(labels, minlength=kmeans.n_clusters)))
    out["n_strides"] = float(n)
    return out


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

    relevant = []
    for p in csv_files:
        stem = p.stem
        task_raw = stem.split("_", 1)[1] if "_" in stem else ""
        task = task_raw.replace("_mat", "").replace("TURN", "").strip("_")
        if task in TASKS_GAIT:
            relevant.append(p)

    print(f"Extracting strides from {len(relevant)} CSVs with {args.workers} workers", flush=True)
    t0 = time.time()
    # Phase 1: extract all strides per task
    all_results: list[tuple[str, str, list[np.ndarray]]] = []
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers) as pool:
        for i, r in enumerate(
            pool.imap_unordered(_process_recording_worker, [str(p) for p in relevant], chunksize=4)
        ):
            if r is not None:
                all_results.append(r)
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(relevant)} elapsed={time.time()-t0:.0f}s", flush=True)
    print(f"Stride extraction done in {time.time()-t0:.0f}s. {len(all_results)} valid recordings.", flush=True)

    # Per task: pool strides, fit K-means
    print(f"\nPhase 2: per-task K-means clustering...", flush=True)
    by_task_strides: dict[str, list[np.ndarray]] = defaultdict(list)
    by_task_subject_strides: dict[str, dict[str, list[np.ndarray]]] = defaultdict(lambda: defaultdict(list))
    for sid, task, strides in all_results:
        for s in strides:
            by_task_strides[task].append(s)
            by_task_subject_strides[task][sid].append(s)

    feature_rows: list[dict] = []
    for task, strides_pool in by_task_strides.items():
        print(f"  task={task}: {len(strides_pool)} pooled strides; fitting K-means(K={N_CLUSTERS})", flush=True)
        if len(strides_pool) < 100:
            continue
        X_pool = np.array(strides_pool)
        km = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10)
        km.fit(X_pool)
        # Compute per-subject features
        for sid, sub_strides in by_task_subject_strides[task].items():
            sub_arr = np.array(sub_strides)
            feats = _subject_features(sub_arr, km)
            if feats:
                rec = {"sid": sid, "task": task, **feats}
                feature_rows.append(rec)
    print(f"  Total feature rows: {len(feature_rows)}", flush=True)

    feature_keys = sorted(
        set().union(*[set(r.keys()) for r in feature_rows]) - {"sid", "task"}
    )
    df_long = pd.DataFrame(feature_rows)

    pivoted = df_long.set_index(["sid", "task"])[feature_keys].unstack("task")
    pivoted.columns = [f"{f}__{t}" for f, t in pivoted.columns]
    pivoted = pivoted.reset_index()
    print(f"  pivoted shape = {pivoted.shape}", flush=True)
    pivoted.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH}", flush=True)

    git_sha = "unknown"
    try:
        import subprocess
        git_sha = subprocess.check_output(["git","rev-parse","HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception: pass
    manifest = {
        "script": "cache_v3_shapelet_features.py",
        "git_sha": git_sha,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "labels_used": False,
        "cohort_statistics_used": True,  # K-means centers fit on global pooled strides — declare honestly
        "fold_scope": "global",          # for tier-2 fold-locality, downstream chain should refit clusters
        "tasks": TASKS_GAIT,
        "k_clusters": N_CLUSTERS,
        "n_phase_samples": N_PHASE,
        "stride_channels": STRIDE_CHANNELS,
        "n_features_total": pivoted.shape[1] - 1,
        "n_subjects": int(pivoted["sid"].nunique()),
        "rationale": "V3 lightweight DTW shapelets — K-means on time-warped stride windows. Stride morphology features capture ordered execution shape under variable timing, complementary to V2 stationary aggregates and V3-GSP graph spectrum.",
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest {MANIFEST_PATH}", flush=True)


if __name__ == "__main__":
    main()
