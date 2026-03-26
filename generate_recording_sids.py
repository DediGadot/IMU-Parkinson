#!/usr/bin/env python3
"""Generate rocket_recordings.npz from raw WearGait-PD data.

Only extracts recordings and SIDs (no ROCKET features).
This is needed to map FM embeddings to subjects.

Usage: python3 -u generate_recording_sids.py
"""
import os
import sys
import time
import numpy as np
import pandas as pd
from concurrent.futures import ProcessPoolExecutor

from project_paths import REPO_ROOT, RESULTS_DIR, ensure_dir, results_artifact_path
sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, DATA_DIR, SENSORS, IMU_COLS, N_CH

ensure_dir(RESULTS_DIR)

RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))
SEQ_LEN = 1000  # 10s at 100Hz
N_CORES = min(os.cpu_count() or 4, 11)

ALL_TASKS = [
    "SelfPace", "SelfPace_mat", "SelfPace_matTURN",
    "HurriedPace", "HurriedPace_mat", "HurriedPace_matTURN",
    "TUG", "TUG_mat", "TUG_matTURN",
    "Balance", "TandemGait",
]


def _get_csv_path(sid, task, subjects):
    group = subjects[sid]["group"]
    prefix = "PD PARTICIPANTS" if group == "PD" else "CONTROL PARTICIPANTS"
    return os.path.join(str(DATA_DIR), prefix, "CSV files", f"{sid}_{task}.csv")


def _load_one_recording(args):
    path, sid, task = args
    try:
        df = pd.read_csv(path)
        cols_present = [c for c in IMU_COLS if c in df.columns]
        if len(cols_present) < N_CH:
            return None
        data = df[cols_present].values
        if len(data) < 100:
            return None
        # Truncate/pad to SEQ_LEN
        n_ch = len(cols_present)
        if len(data) > SEQ_LEN:
            start = (len(data) - SEQ_LEN) // 2
            data = data[start:start + SEQ_LEN]
        elif len(data) < SEQ_LEN:
            pad = np.zeros((SEQ_LEN - len(data), n_ch))
            data = np.vstack([data, pad])
        # Compute magnitudes for acc and gyr per sensor (26 channels)
        magnitudes = []
        for s in SENSORS:
            acc_cols = [f"{s}_Acc_X", f"{s}_Acc_Y", f"{s}_Acc_Z"]
            gyr_cols = [f"{s}_Gyr_X", f"{s}_Gyr_Y", f"{s}_Gyr_Z"]
            acc_idx = [cols_present.index(c) for c in acc_cols if c in cols_present]
            gyr_idx = [cols_present.index(c) for c in gyr_cols if c in cols_present]
            if len(acc_idx) == 3:
                magnitudes.append(np.sqrt(np.sum(data[:, acc_idx] ** 2, axis=1)))
            if len(gyr_idx) == 3:
                magnitudes.append(np.sqrt(np.sum(data[:, gyr_idx] ** 2, axis=1)))
        if len(magnitudes) != 26:
            return None
        mag_array = np.stack(magnitudes)  # (26, SEQ_LEN)
        return {"data": mag_array.astype(np.float32), "sid": sid, "task": task}
    except Exception as e:
        return None


def main():
    if os.path.exists(RECORDING_CACHE):
        print(f"Recording cache already exists: {RECORDING_CACHE}")
        data = np.load(RECORDING_CACHE)
        print(f"  {len(data['sids'])} recordings")
        return

    print("Generating recording SIDs from raw data...")
    t0 = time.time()

    subjects = parse_clinical()
    all_sids = list(subjects.keys())
    print(f"Subjects: {len(all_sids)}")

    jobs = []
    for task in ALL_TASKS:
        for sid in all_sids:
            p = _get_csv_path(sid, task, subjects)
            if os.path.exists(p):
                jobs.append((p, sid, task))
    print(f"Found {len(jobs)} recordings to process")

    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        results = list(pool.map(_load_one_recording, jobs, chunksize=8))

    valid = [r for r in results if r is not None]
    rec_array = np.stack([r["data"] for r in valid])
    rec_sids = [r["sid"] for r in valid]
    rec_tasks = [r["task"] for r in valid]

    np.savez_compressed(RECORDING_CACHE,
                        recordings=rec_array,
                        sids=np.array(rec_sids),
                        tasks=np.array(rec_tasks))
    print(f"\nSaved: {RECORDING_CACHE}")
    print(f"  {len(rec_sids)} recordings, shape {rec_array.shape}")
    print(f"  Runtime: {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
