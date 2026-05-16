"""V3 Phase Synchronization Index (PSI) features.

Grok's #1 pick (2026-05-12 4-CLI consult, expected ΔCCC +0.009-0.017,
errcorr target <0.45):

  Hilbert analytic signal → instantaneous phase φ(t); Phase Locking Value
  PLV = |⟨e^{i(φ_i − φ_j)}⟩| over windows. Directly encodes inter-segment
  timing precision disrupted in PD axial gait — phenomena V2 discards
  (phase-blind power) and V3-GSP collapses (eigenmode amplitudes only).

Mechanism orthogonality vs V2 + V3-GSP:
  V2 = phase-blind power/spectral aggregates.
  V3-GSP = eigenmode amplitudes (also phase-blind).
  V3-PSI = inter-segment PHASE relationships — captures synchronization
           and timing precision, NOT amplitudes.

Inter-segment pairs (PD-clinical motivated):
  lumbar-sternum   : trunk axial coupling (rigidity, en-bloc turning)
  lumbar-ankle_L/R : axial-distal coordination (gait initiation, FoG)
  sternum-wrist_L/R: trunk-arm asymmetry (arm swing reduction)
  L-R bilateral pairs: thigh, shank, ankle (gait symmetry)

Channels:
  FreeAcc_U (vertical) - gait cycle dominant
  Gyr_Z (yaw)          - turning/heading
  Gyr_X (pitch)        - sagittal-plane gait

Output: results/v3_psi_features.csv (per-subject, prefix `psi_`).
"""
from __future__ import annotations

import argparse, json, multiprocessing as mp, sys, time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, hilbert

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
from project_paths import RESULTS_DIR, ensure_dir
ensure_dir(RESULTS_DIR)

OUT_PATH = RESULTS_DIR / "v3_psi_features.csv"
MANIFEST_PATH = RESULTS_DIR / "v3_psi_features.csv.manifest.json"

FS = 100

# Inter-segment pairs (sensor_a, sensor_b)
PAIRS = [
    ("LowerBack", "Xiphoid"),          # axial trunk coupling
    ("LowerBack", "L_LatShank"),       # axial-distal L
    ("LowerBack", "R_LatShank"),       # axial-distal R
    ("LowerBack", "L_Ankle"),          # axial-foot L
    ("LowerBack", "R_Ankle"),          # axial-foot R
    ("Xiphoid", "L_Wrist"),            # trunk-arm L
    ("Xiphoid", "R_Wrist"),            # trunk-arm R
    ("L_MidLatThigh", "R_MidLatThigh"),  # bilateral thigh
    ("L_LatShank", "R_LatShank"),      # bilateral shank
    ("L_Ankle", "R_Ankle"),            # bilateral ankle
    ("L_Wrist", "R_Wrist"),            # bilateral wrist
]

# Channels with PD-relevant spectral content
CHANNELS = [
    ("FreeAcc_U", 0.5, 5.0),  # vertical accel, gait band
    ("Gyr_Z", 0.5, 4.0),      # yaw rotation
    ("Gyr_X", 0.5, 5.0),      # pitch rotation
]

TASKS_GAIT = ["SelfPace", "HurriedPace", "TUG", "TandemGait", "Balance"]


def _bandpass(x: np.ndarray, low: float, high: float, fs: float = FS) -> np.ndarray:
    """4th-order zero-phase Butterworth bandpass."""
    nyq = fs / 2
    b, a = butter(4, [low / nyq, high / nyq], btype="band")
    try:
        return filtfilt(b, a, x)
    except Exception:
        return x


def _phase_features_one_pair(
    x: np.ndarray, y: np.ndarray, low: float, high: float
) -> dict[str, float]:
    """Compute PLV + phase difference stats for one pair."""
    out: dict[str, float] = {}
    if len(x) < 50 or np.any(~np.isfinite(x)) or np.any(~np.isfinite(y)):
        return out
    xb = _bandpass(x, low, high)
    yb = _bandpass(y, low, high)
    phi_x = np.angle(hilbert(xb))
    phi_y = np.angle(hilbert(yb))
    delta = phi_x - phi_y  # phase difference

    # Global PLV
    out["plv"] = float(np.abs(np.mean(np.exp(1j * delta))))
    # Phase-difference statistics
    cos_d = np.cos(delta)
    sin_d = np.sin(delta)
    mean_cos = float(np.mean(cos_d))
    mean_sin = float(np.mean(sin_d))
    out["phase_diff_mean"] = float(np.arctan2(mean_sin, mean_cos))  # mean phase lag
    # Phase difference dispersion (circular variance = 1 - PLV)
    out["phase_dispersion"] = float(1.0 - out["plv"])
    # Quartile PLVs (within-window stability of locking)
    n_chunks = 8
    chunk_size = len(delta) // n_chunks
    if chunk_size > 20:
        chunk_plvs = []
        for k in range(n_chunks):
            d_chunk = delta[k * chunk_size:(k + 1) * chunk_size]
            chunk_plvs.append(float(np.abs(np.mean(np.exp(1j * d_chunk)))))
        chunk_plvs_arr = np.array(chunk_plvs)
        out["plv_chunk_mean"] = float(chunk_plvs_arr.mean())
        out["plv_chunk_std"] = float(chunk_plvs_arr.std())
        out["plv_chunk_p10"] = float(np.percentile(chunk_plvs_arr, 10))
    return out


def _compute_psi_one_recording(csv_path_str: str) -> tuple[str, str, dict[str, float]] | None:
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
    out: dict[str, float] = {}
    for sa, sb in PAIRS:
        for ch, low, high in CHANNELS:
            col_a = f"{sa}_{ch}"
            col_b = f"{sb}_{ch}"
            if col_a not in df.columns or col_b not in df.columns:
                continue
            x = df[col_a].to_numpy(dtype=np.float64)
            y = df[col_b].to_numpy(dtype=np.float64)
            T = min(len(x), len(y))
            if T < 100:
                continue
            x = x[:T]; y = y[:T]
            feats = _phase_features_one_pair(x, y, low, high)
            for k, v in feats.items():
                out[f"psi_{sa}_to_{sb}_{ch}_{k}"] = v
    if not out:
        return None
    return (sid, task, out)


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

    print(f"Processing {len(relevant)} relevant CSVs with {args.workers} workers",
          flush=True)
    t0 = time.time()
    rows: list[tuple[str, str, dict]] = []
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers) as pool:
        for i, r in enumerate(
            pool.imap_unordered(_compute_psi_one_recording, [str(p) for p in relevant], chunksize=4)
        ):
            if r is not None:
                rows.append(r)
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(relevant)} elapsed={time.time()-t0:.0f}s", flush=True)
    print(f"Done in {time.time()-t0:.0f}s. Valid rows: {len(rows)}", flush=True)
    if not rows:
        return

    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for sid, task, feats in rows:
        by[(sid, task)].append(feats)
    feature_keys = sorted(set().union(*[set(r[2].keys()) for r in rows]))

    records = []
    for (sid, task), fl in by.items():
        rec = {"sid": sid, "task": task}
        for k in feature_keys:
            vals = [f[k] for f in fl if k in f and np.isfinite(f[k])]
            rec[k] = float(np.mean(vals)) if vals else np.nan
        records.append(rec)
    df_long = pd.DataFrame(records)
    print(f"  long shape={df_long.shape}", flush=True)

    pivoted = df_long.set_index(["sid","task"])[feature_keys].unstack("task")
    pivoted.columns = [f"{f}__{t}" for f,t in pivoted.columns]
    pivoted = pivoted.reset_index()
    print(f"  pivoted={pivoted.shape}", flush=True)
    pivoted.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH}", flush=True)

    git_sha = "unknown"
    try:
        import subprocess
        git_sha = subprocess.check_output(["git","rev-parse","HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception: pass
    manifest = {
        "script": "cache_v3_psi_features.py",
        "git_sha": git_sha,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "labels_used": False,
        "cohort_statistics_used": False,
        "fold_scope": "global",
        "pairs": PAIRS,
        "channels": [(c, l, h) for c, l, h in CHANNELS],
        "tasks": TASKS_GAIT,
        "rationale": "V3 Phase Synchronization Index (Hilbert PLV) between inter-segment pairs; phase-aware, orthogonal to V2 amplitude aggregates and V3-GSP linear projection.",
        "n_features_total": pivoted.shape[1] - 1,
        "n_subjects": int(pivoted["sid"].nunique()),
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest {MANIFEST_PATH}", flush=True)


if __name__ == "__main__":
    main()
