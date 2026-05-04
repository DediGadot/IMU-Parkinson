"""Cache rest-state features for item-11 surrogate (idea 11).

Toe-tap (item 11) is clinically evaluated AT REST. Averaging features over walking
dilutes the signal. Extract quiet-standing windows from Balance / TandemGait
recordings (first 1.5s + last 1.5s = subjects standing still before/after the
task), compute simple variability features per sensor.

Approach:
- For each Balance / TandemGait / Balance_mat / TandemGait_mat recording:
  - Front rest = first 1.5 s   (150 samples @100Hz)
  - Back rest  = last 1.5 s    (150 samples @100Hz)
- Extract per sensor (13) per channel-kind (acc/gyr): std, range, jerk, ZCR.
- Aggregate per subject as MEAN across recordings.

Why simple features only: 1.5s windows are too short for spectral or DFA features
to be reliable. Codex's failure-mode B5 explicitly warned against using narrow
windows for variance/freq estimates without ≥3 sub-window repeats.

Output: `results/rest_state_features.csv` per-subject aggregated.

Usage:
  uv run python cache_rest_state_features.py
  python3 cache_rest_state_features.py --smoke
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir

ROCKET_CACHE = RESULTS_DIR / "rocket_recordings.npz"
OUT_PATH = RESULTS_DIR / "rest_state_features.csv"

FS = 100  # Hz
REST_WINDOW_S = 1.5
REST_LEN = int(REST_WINDOW_S * FS)  # 150

SENSORS = [
    "L_Wrist", "R_Wrist", "LowerBack", "L_Thigh", "R_Thigh",
    "L_Shank", "R_Shank", "L_DorsalFoot", "R_DorsalFoot",
    "L_Ankle", "R_Ankle", "Xiphoid", "Forehead",
]
REST_TASK_NAMES = {"Balance", "Balance_mat", "TandemGait", "TandemGait_mat"}


def short_window_feats(x: np.ndarray, prefix: str) -> dict:
    if x.size < 5:
        return {
            f"{prefix}_std": 0.0, f"{prefix}_range": 0.0,
            f"{prefix}_jerk": 0.0, f"{prefix}_zcr": 0.0,
        }
    std = float(np.std(x))
    rng = float(np.ptp(x))
    jerk = float(np.sqrt(np.mean(np.diff(x).astype(np.float64) ** 2)))
    mean = float(np.mean(x))
    zcr = float(np.sum(np.diff(np.sign(x - mean)) != 0) / max(len(x), 1))
    return {f"{prefix}_std": std, f"{prefix}_range": rng,
            f"{prefix}_jerk": jerk, f"{prefix}_zcr": zcr}


def features_for_recording(rec: np.ndarray, task: str) -> dict:
    """rec: (26, T). Extract rest-window features."""
    T = rec.shape[1]
    feats: dict = {}
    if T < REST_LEN * 2:
        return feats
    for window_name, sl in (
        ("front", slice(0, REST_LEN)),
        ("back",  slice(T - REST_LEN, T)),
    ):
        for si, sensor in enumerate(SENSORS):
            for ch_kind, ch_idx in (("acc", si * 2), ("gyr", si * 2 + 1)):
                seg = rec[ch_idx][sl]
                feats.update(short_window_feats(
                    seg, f"rest_{task}_{window_name}_{sensor}_{ch_kind}"))
    return feats


def aggregate_per_subject(rec_array: np.ndarray, sids: np.ndarray,
                          tasks: np.ndarray) -> pd.DataFrame:
    is_rest = np.array([t in REST_TASK_NAMES for t in tasks])
    rest_recs = rec_array[is_rest]
    rest_sids = sids[is_rest]
    rest_tasks = tasks[is_rest]
    if len(rest_recs) == 0:
        raise RuntimeError("No Balance/TandemGait recordings found")
    print(f"  {len(rest_recs)} rest-task recordings across "
          f"{len(set(rest_sids))} subjects")

    rows: list[dict] = []
    for i in range(len(rest_recs)):
        # Group Balance and Balance_mat into "Balance"; same for Tandem
        task_norm = rest_tasks[i].replace("_mat", "")
        feats = features_for_recording(rest_recs[i], task_norm)
        if not feats:
            continue
        feats["sid"] = rest_sids[i]
        rows.append(feats)
    if not rows:
        raise RuntimeError("No rest-state features extracted (recordings too short?)")
    per_rec_df = pd.DataFrame(rows)
    feat_cols = [c for c in per_rec_df.columns if c != "sid"]
    agg = per_rec_df.groupby("sid")[feat_cols].mean(numeric_only=True).reset_index()
    return agg


def run_smoke_check(df: pd.DataFrame) -> None:
    n_subj = len(df)
    if n_subj < 50:
        raise RuntimeError(f"Too few subjects: {n_subj}")
    feat_cols = [c for c in df.columns if c.startswith("rest_")]
    if len(feat_cols) < 100:
        raise RuntimeError(f"Too few rest features: {len(feat_cols)}")
    # Variability sanity: rest std should be POSITIVE (subjects do move slightly)
    std_block = df[[c for c in feat_cols if c.endswith("_std")]].values
    nonzero_frac = float((std_block > 1e-6).mean())
    if nonzero_frac < 0.7:
        raise RuntimeError(
            f"Most rest std features are zero ({nonzero_frac:.2%}) — likely no signal")
    print(f"  smoke OK: {n_subj} subjects, {len(feat_cols)} rest features, "
          f"std non-zero fraction={nonzero_frac:.2%}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    ensure_dir(RESULTS_DIR)
    if not ROCKET_CACHE.exists():
        raise FileNotFoundError(f"Required cache missing: {ROCKET_CACHE}")
    print(f"Loading rocket cache from {ROCKET_CACHE}")
    data = np.load(ROCKET_CACHE)
    rec_array = data["recordings"]
    sids = data["sids"]
    tasks = data["tasks"]
    print(f"  rec_array={rec_array.shape}, sids={sids.shape}, tasks={tasks.shape}")

    if args.smoke:
        is_rest = np.array([t in REST_TASK_NAMES for t in tasks])
        keep = np.where(is_rest)[0][:5]
        rec_array = rec_array[keep]
        sids = sids[keep]
        tasks = tasks[keep]
        rows: list[dict] = []
        for i in range(len(rec_array)):
            task_norm = tasks[i].replace("_mat", "")
            f = features_for_recording(rec_array[i], task_norm)
            f["sid"] = sids[i]
            f["task"] = tasks[i]
            rows.append(f)
        df = pd.DataFrame(rows)
        print(df[["sid", "task"]])
        print(f"  per-recording feature count: {len(rows[0]) - 2}")
        return

    df = aggregate_per_subject(rec_array, sids, tasks)
    run_smoke_check(df)

    out_path = Path(args.out)
    df.to_csv(out_path, index=False)
    print(f"Wrote {df.shape[0]} rows × {df.shape[1]} cols → {out_path}")


if __name__ == "__main__":
    main()
