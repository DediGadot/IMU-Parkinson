"""Cache TUG transition phase features for item-13 fix (idea 1).

Approach (revised after data audit — see findings F23):
- Raw 22-channel CSVs are NOT on remote, only the magnitude-cache `rocket_recordings.npz`.
- For each TUG / TUG_mat recording (10s @ 100Hz, 26 channels = 13 sensors × {Acc_mag, Gyr_mag}):
  1. Detect the sit-to-stand transition by finding the peak Lumbar Acc-mag energy spike.
  2. Slice the 10s window into 6 phases anchored at the spike:
        pre_stand  : [t_spike - 1.5s, t_spike - 0.3s]
        stand_up   : [t_spike - 0.3s, t_spike + 0.5s]   (the explosive event)
        gait_init  : [t_spike + 0.5s, t_spike + 2.0s]
        turning    : [t_spike + 2.0s, t_spike + 5.0s]
        turn_to_sit: [t_spike + 5.0s, t_spike + 8.0s]
        sit_down   : [t_spike + 8.0s, t_spike + 9.5s]
  3. For each phase, extract simple features per sensor: rms, std, range, jerk, ZCR.
  4. Aggregate per-subject as MEAN across the subject's TUG recordings.

Multi-spike fix (codex failure-mode B1): if multiple peaks are within 80% of max within
0.4s windows, keep the LATEST one (subjects with multiple sit-to-stand attempts → final attempt is the one).

Channel layout (per `_load_one_recording` in run_rocket_ablation.py):
- 26 channels interleaved per sensor: [Acc_mag_0, Gyr_mag_0, Acc_mag_1, Gyr_mag_1, ...]
- Sensor order: ["L_Wrist", "R_Wrist", "LowerBack", "L_Thigh", "R_Thigh",
                 "L_Shank", "R_Shank", "L_DorsalFoot", "R_DorsalFoot",
                 "L_Ankle", "R_Ankle", "Xiphoid", "Forehead"]
- LowerBack at sensor index 2 → channels 4 (Acc_mag) and 5 (Gyr_mag).

Output: `results/tug_transition_features.csv` (per-subject aggregated) — ~30-100 features.

Usage:
  uv run python cache_tug_transition_features.py
  python3 cache_tug_transition_features.py --smoke   # 5 subjects
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
OUT_PATH = RESULTS_DIR / "tug_transition_features.csv"

FS = 100  # Hz
SENSORS = [
    "L_Wrist", "R_Wrist", "LowerBack", "L_Thigh", "R_Thigh",
    "L_Shank", "R_Shank", "L_DorsalFoot", "R_DorsalFoot",
    "L_Ankle", "R_Ankle", "Xiphoid", "Forehead",
]
LUMBAR_IDX = SENSORS.index("LowerBack")  # 2
LUMBAR_ACC_CH = LUMBAR_IDX * 2          # 4
LUMBAR_GYR_CH = LUMBAR_IDX * 2 + 1      # 5

# TUG includes mat variants (both are sit-to-stand-walk-turn-walk-sit)
TUG_TASK_NAMES = {"TUG", "TUG_mat"}

# Phase definitions (relative to detected spike, in seconds)
PHASES: list[tuple[str, float, float]] = [
    ("pre_stand",   -1.5, -0.3),
    ("stand_up",    -0.3,  0.5),
    ("gait_init",    0.5,  2.0),
    ("turning",      2.0,  5.0),
    ("turn_to_sit",  5.0,  8.0),
    ("sit_down",     8.0,  9.5),
]

# Sensors we track (subset to keep feature count manageable; codex warned >100 phase
# features over 6×13×2 channels would explode at N=89). Focus on body-axis sensors
# that carry sit-to-stand information.
TRACKED_SENSORS = ["LowerBack", "Xiphoid", "Forehead", "L_Thigh", "R_Thigh",
                   "L_Shank", "R_Shank"]


def detect_spike_time(lumbar_acc_mag: np.ndarray, fs: int = FS) -> float:
    """Return the spike time in seconds within the 10s window.

    Strategy:
    - High-pass via removing local mean; the sit-to-stand event has the largest
      acceleration burst. Look at squared signal for energy.
    - Smooth with 200ms moving average.
    - Find peaks within the first 4 seconds (sit-to-stand should be near the start).
    - If multiple peaks ≥ 80% of max within 0.4s windows, take the LATEST (multi-attempt subjects).
    """
    n = len(lumbar_acc_mag)
    if n < fs:
        return 1.0  # fallback
    # Subtract local DC; gravity component is mostly constant in magnitude
    detrended = lumbar_acc_mag - np.median(lumbar_acc_mag)
    energy = detrended ** 2
    # 200ms moving average
    win = max(int(0.2 * fs), 5)
    kernel = np.ones(win) / win
    smoothed = np.convolve(energy, kernel, mode="same")
    # Restrict to first 4 seconds (sit-to-stand happens early in TUG)
    search_end = min(int(4.0 * fs), n)
    region = smoothed[:search_end]
    if region.size == 0 or region.max() < 1e-9:
        return 1.0
    peak_idx = int(np.argmax(region))
    peak_val = region[peak_idx]
    # Multi-attempt fix: any peak ≥ 80% within 0.4s windows; keep latest
    threshold = 0.8 * peak_val
    candidates = []
    last_above_idx = -1
    last_above_run_start = -1
    for i in range(search_end):
        if region[i] >= threshold:
            if last_above_idx == i - 1:
                last_above_idx = i
            else:
                if last_above_run_start >= 0:
                    candidates.append((last_above_run_start + last_above_idx) // 2)
                last_above_run_start = i
                last_above_idx = i
    if last_above_run_start >= 0:
        candidates.append((last_above_run_start + last_above_idx) // 2)
    if not candidates:
        candidates = [peak_idx]
    chosen_idx = candidates[-1]  # LATEST candidate
    return float(chosen_idx) / fs


def phase_slice(signal: np.ndarray, t_spike: float, t0: float, t1: float,
                fs: int = FS) -> np.ndarray:
    """Slice signal[start:end] where start, end are clamped to [0, len(signal)]."""
    start = int((t_spike + t0) * fs)
    end = int((t_spike + t1) * fs)
    start = max(0, start)
    end = min(len(signal), end)
    if end <= start:
        return np.array([], dtype=signal.dtype)
    return signal[start:end]


def phase_feats(x: np.ndarray, prefix: str) -> dict:
    """Simple phase features. Robust to short slices."""
    if x.size < 5:
        return {
            f"{prefix}_rms": 0.0, f"{prefix}_std": 0.0, f"{prefix}_range": 0.0,
            f"{prefix}_jerk": 0.0, f"{prefix}_zcr": 0.0,
        }
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
    std = float(np.std(x))
    rng = float(np.ptp(x))
    jerk = float(np.sqrt(np.mean(np.diff(x).astype(np.float64) ** 2)))
    mean = float(np.mean(x))
    zcr = float(np.sum(np.diff(np.sign(x - mean)) != 0) / max(len(x), 1))
    return {f"{prefix}_rms": rms, f"{prefix}_std": std, f"{prefix}_range": rng,
            f"{prefix}_jerk": jerk, f"{prefix}_zcr": zcr}


def features_for_recording(rec: np.ndarray) -> dict:
    """rec: shape (26, T) — extract phase features for this single TUG recording."""
    lumbar_acc = rec[LUMBAR_ACC_CH]
    t_spike = detect_spike_time(lumbar_acc)
    feats: dict = {"_spike_time_s": t_spike}
    for sensor in TRACKED_SENSORS:
        si = SENSORS.index(sensor)
        for ch_kind, ch_idx in (("acc", si * 2), ("gyr", si * 2 + 1)):
            sig = rec[ch_idx]
            for ph_name, t0, t1 in PHASES:
                seg = phase_slice(sig, t_spike, t0, t1)
                feats.update(phase_feats(seg, f"tug_{sensor}_{ch_kind}_{ph_name}"))
    return feats


def aggregate_per_subject(rec_array: np.ndarray, sids: np.ndarray,
                          tasks: np.ndarray) -> pd.DataFrame:
    is_tug = np.array([t in TUG_TASK_NAMES for t in tasks])
    tug_recs = rec_array[is_tug]
    tug_sids = sids[is_tug]

    if len(tug_recs) == 0:
        raise RuntimeError("No TUG recordings found in rocket cache")

    print(f"  {len(tug_recs)} TUG recordings across "
          f"{len(set(tug_sids))} subjects")

    # Per-recording features
    per_rec_rows: list[dict] = []
    for i in range(len(tug_recs)):
        feats = features_for_recording(tug_recs[i])
        feats["sid"] = tug_sids[i]
        per_rec_rows.append(feats)
    per_rec_df = pd.DataFrame(per_rec_rows)

    # Aggregate by mean per subject
    feat_cols = [c for c in per_rec_df.columns if c != "sid"]
    agg = per_rec_df.groupby("sid")[feat_cols].mean().reset_index()
    return agg


def run_smoke_check(df: pd.DataFrame) -> None:
    n_subj = len(df)
    if n_subj < 50:
        raise RuntimeError(f"Too few subjects: {n_subj}")
    spike_col = "_spike_time_s"
    if spike_col not in df.columns:
        raise RuntimeError("Missing spike time column")
    plausible = (df[spike_col] >= 0.2) & (df[spike_col] <= 4.0)
    plausible_frac = float(plausible.mean())
    if plausible_frac < 0.7:
        raise RuntimeError(
            f"Spike detected outside 0.2-4s in {1-plausible_frac:.2%} of subjects "
            "— sit-to-stand detection broken")
    feat_cols = [c for c in df.columns if c not in ("sid", "_spike_time_s")]
    print(f"  smoke OK: {n_subj} subjects, {len(feat_cols)} phase features, "
          f"spike-detection plausibility={plausible_frac:.2%}")


def null_sanity_check(rec_array: np.ndarray, sids: np.ndarray,
                      tasks: np.ndarray, n_perturb: int = 5) -> None:
    """Quick null: shuffle channel data within each recording — spike detection
    should still produce SOME spike but feature stats should change.
    Verifies we are not just returning constants."""
    is_tug = np.array([t in TUG_TASK_NAMES for t in tasks])
    if is_tug.sum() < 5:
        return
    rng = np.random.RandomState(0)
    sample_idx = np.where(is_tug)[0][:n_perturb]
    real_feats: list[float] = []
    shuf_feats: list[float] = []
    for i in sample_idx:
        rec = rec_array[i].copy()
        f1 = features_for_recording(rec)
        # shuffle each channel independently
        rec2 = rec.copy()
        for c in range(rec2.shape[0]):
            rng.shuffle(rec2[c])
        f2 = features_for_recording(rec2)
        # Pick one feature (Lumbar Acc rms during stand_up)
        key = "tug_LowerBack_acc_stand_up_rms"
        real_feats.append(f1.get(key, np.nan))
        shuf_feats.append(f2.get(key, np.nan))
    if np.allclose(real_feats, shuf_feats, atol=1e-6):
        raise RuntimeError(
            "Null sanity FAILED: shuffled-channel features match real features. "
            "Phase extraction is data-independent.")
    print(f"  null OK: shuffled-channel features differ from real "
          f"(real_mean={np.nanmean(real_feats):.3f}, shuf_mean={np.nanmean(shuf_feats):.3f})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="process first 5 TUG recordings only")
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
    print(f"  unique tasks: {sorted(set(tasks))}")

    if args.smoke:
        is_tug = np.array([t in TUG_TASK_NAMES for t in tasks])
        keep = np.where(is_tug)[0][:5]
        rec_array = rec_array[keep]
        sids = sids[keep]
        tasks = tasks[keep]
        print(f"  smoke mode: kept {len(keep)} recordings")
        # In smoke mode, build per-recording features (skip subject aggregation)
        rows: list[dict] = []
        for i in range(len(rec_array)):
            f = features_for_recording(rec_array[i])
            f["sid"] = sids[i]
            f["task"] = tasks[i]
            rows.append(f)
        df = pd.DataFrame(rows)
        print(df[["sid", "task", "_spike_time_s"]])
        return

    null_sanity_check(rec_array, sids, tasks)
    df = aggregate_per_subject(rec_array, sids, tasks)
    run_smoke_check(df)

    out_path = Path(args.out)
    df.to_csv(out_path, index=False)
    print(f"Wrote {df.shape[0]} rows × {df.shape[1]} cols → {out_path}")


if __name__ == "__main__":
    main()
