"""cache_event_axial_features.py — Event-gated axial features for T3 iter6.

Per-subject features extracted from raw per-task CSVs (100 Hz, GeneralEvent column).
Inspired by codex+gemini consilience: T3 is axial-heavy; V2's magnitude-only stats
erase direction; gating to specific clinical events strips background noise.

Per subject × task:
- Axial sensors: LowerBack, Xiphoid, Forehead (3 sensors)
- Channels: Pitch, Yaw, FreeAcc_U (vertical), Acc_mag (control baseline)
- Event windows from GeneralEvent column

Tasks + events:
- TUG: Sitting, SitToStand, Walk, Turn, TurnToSit (5 events)
- SelfPace, HurriedPace: Walk, Turn (2 events each)

Stats per (sensor × channel × event × task): mean, std, range, abs_peak.
Plus: event durations per task (bradykinesia proxy).

Total: ~300 features per subject.

Per CLAUDE.md leakage firewall: features computed from raw signals only,
per-subject independent (no transductive aggregation).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

# ── Configuration ────────────────────────────────────────────────────────────

DEFAULT_RAW_DIR = Path("/root/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files")
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "results" / "event_axial_features.csv"

AXIAL_SENSORS: list[str] = ["LowerBack", "Xiphoid", "Forehead"]
DIRECTIONAL_CHANNELS: list[str] = ["Pitch", "Yaw", "FreeAcc_U"]
# Acc_mag = sqrt(Acc_X^2+Acc_Y^2+Acc_Z^2) computed on the fly as a baseline control

TASK_EVENTS: dict[str, list[str]] = {
    "TUG": ["Sitting", "SitToStand", "Walk", "Turn", "TurnToSit"],
    "SelfPace": ["Walk", "Turn"],
    "HurriedPace": ["Walk", "Turn"],
}

# Sample rate (per inspection: 100 Hz, time in "X sec" string format)
FS_HZ = 100


# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_time_seconds(time_col: pd.Series) -> np.ndarray:
    """Parse time column 'X sec' → float seconds. Robust to occasional non-numeric."""
    s = time_col.astype(str).str.replace(r"\s*sec\s*$", "", regex=True)
    return pd.to_numeric(s, errors="coerce").to_numpy()


def _channel_cols(df: pd.DataFrame, sensor: str, channel: str) -> str | None:
    """Resolve canonical sensor_channel column name; returns None if absent."""
    candidates = [
        f"{sensor}_{channel}",  # most common
        f"{sensor}{channel}",
        f"{sensor}-{channel}",
    ]
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _acc_mag_array(df: pd.DataFrame, sensor: str) -> np.ndarray | None:
    """Compute Acc magnitude on the fly. Returns NaN array if any axis missing."""
    cx = f"{sensor}_Acc_X"
    cy = f"{sensor}_Acc_Y"
    cz = f"{sensor}_Acc_Z"
    if not all(c in df.columns for c in (cx, cy, cz)):
        return None
    a = np.sqrt(df[cx].to_numpy() ** 2 + df[cy].to_numpy() ** 2 + df[cz].to_numpy() ** 2)
    return a


def _event_window_indices(events: np.ndarray, event_label: str) -> list[tuple[int, int]]:
    """Return list of (start_idx, end_idx_exclusive) for each contiguous run of event_label."""
    if len(events) == 0:
        return []
    is_target = events == event_label
    if not is_target.any():
        return []
    # Find run boundaries
    diff = np.diff(is_target.astype(np.int8), prepend=0, append=0)
    starts = np.where(diff == 1)[0]
    ends = np.where(diff == -1)[0]
    return list(zip(starts.tolist(), ends.tolist()))


def _extract_window_stats(values_full: np.ndarray, windows: list[tuple[int, int]]) -> dict[str, float]:
    """Compute (mean, std, range, abs_peak) over the concatenation of all event windows.

    If the event has multiple instances (e.g., 2 SitToStand in one TUG), pool all samples
    before computing stats. NaN-safe.
    """
    if not windows:
        return {"mean": np.nan, "std": np.nan, "range": np.nan, "abs_peak": np.nan, "n_samples": 0, "n_windows": 0}
    pooled = np.concatenate([values_full[s:e] for s, e in windows])
    pooled = pooled[~np.isnan(pooled)]
    if len(pooled) == 0:
        return {"mean": np.nan, "std": np.nan, "range": np.nan, "abs_peak": np.nan, "n_samples": 0, "n_windows": len(windows)}
    return {
        "mean": float(np.mean(pooled)),
        "std": float(np.std(pooled)) if len(pooled) > 1 else 0.0,
        "range": float(np.max(pooled) - np.min(pooled)),
        "abs_peak": float(np.max(np.abs(pooled))),
        "n_samples": int(len(pooled)),
        "n_windows": int(len(windows)),
    }


def _process_subject_task(
    raw_dir: Path, sid: str, task: str
) -> dict[str, float]:
    """Process one subject-task CSV; return flat feature dict (NaN for missing)."""
    fpath = raw_dir / f"{sid}_{task}.csv"
    out: dict[str, float] = {}
    if not fpath.exists():
        # Mark all features as NaN (downstream FoldImputer will handle)
        return out

    try:
        df = pd.read_csv(fpath, low_memory=False)
    except Exception:
        return out

    if "GeneralEvent" not in df.columns:
        return out

    events = df["GeneralEvent"].astype(str).to_numpy()
    event_labels = TASK_EVENTS[task]

    # Per-event duration (bradykinesia proxy; gemini #3)
    for ev in event_labels:
        windows = _event_window_indices(events, ev)
        total_samples = sum(e - s for s, e in windows)
        out[f"{task}_{ev}_duration_s"] = total_samples / FS_HZ
        out[f"{task}_{ev}_n_instances"] = float(len(windows))

    # Per (sensor × channel × event) stats
    for sensor in AXIAL_SENSORS:
        # Directional channels
        for ch in DIRECTIONAL_CHANNELS:
            col = _channel_cols(df, sensor, ch)
            if col is None:
                continue
            vals = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=np.float64)
            for ev in event_labels:
                windows = _event_window_indices(events, ev)
                stats = _extract_window_stats(vals, windows)
                pfx = f"{task}_{ev}_{sensor}_{ch}"
                for stat_name in ("mean", "std", "range", "abs_peak"):
                    out[f"{pfx}_{stat_name}"] = stats[stat_name]
        # Acc magnitude (control baseline — known to be in V2; included for ablation)
        acc_mag = _acc_mag_array(df, sensor)
        if acc_mag is not None:
            for ev in event_labels:
                windows = _event_window_indices(events, ev)
                stats = _extract_window_stats(acc_mag, windows)
                pfx = f"{task}_{ev}_{sensor}_AccMag"
                for stat_name in ("mean", "std", "range", "abs_peak"):
                    out[f"{pfx}_{stat_name}"] = stats[stat_name]

    return out


def _process_subject(args: tuple) -> tuple[str, dict[str, float]]:
    raw_dir, sid = args
    feats: dict[str, float] = {}
    for task in TASK_EVENTS:
        task_feats = _process_subject_task(raw_dir, sid, task)
        feats.update(task_feats)
    return sid, feats


# ── Main entry ───────────────────────────────────────────────────────────────


def _list_pd_subjects(raw_dir: Path) -> list[str]:
    """Find unique PD SIDs (NLS* or WPD*) from any *.csv in raw_dir."""
    sids: set[str] = set()
    for f in raw_dir.glob("*.csv"):
        m = re.match(r"^(NLS|WPD)\d+", f.stem)
        if m:
            sids.add(m.group(0))
    return sorted(sids)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw_dir", default=str(DEFAULT_RAW_DIR))
    p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    p.add_argument("--workers", type=int, default=12)
    args = p.parse_args()

    raw_dir = Path(args.raw_dir)
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw data dir does not exist: {raw_dir}")

    sids = _list_pd_subjects(raw_dir)
    print(f"Found {len(sids)} PD subjects in {raw_dir}", flush=True)
    if not sids:
        print("No PD SIDs found; exiting.", flush=True)
        return

    t0 = time.time()
    rows: list[dict] = []
    completed = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_process_subject, (raw_dir, sid)): sid for sid in sids}
        for fut in as_completed(futures):
            sid, feats = fut.result()
            row = {"sid": sid, **feats}
            rows.append(row)
            completed += 1
            if completed % 10 == 0 or completed == len(sids):
                elapsed = time.time() - t0
                print(f"  {completed}/{len(sids)} subjects done, elapsed {elapsed:.1f}s", flush=True)

    df = pd.DataFrame(rows).sort_values("sid").reset_index(drop=True)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    n_subj, n_feat = df.shape[0], df.shape[1] - 1  # minus 'sid'
    print(f"\nWrote {out_path}", flush=True)
    print(f"  shape = ({n_subj} subjects, {n_feat} features)", flush=True)
    # Coverage diagnostic
    nan_pct = df.drop(columns=["sid"]).isna().mean(axis=0).describe(percentiles=[0.5, 0.9])
    print(f"  per-feature NaN-fraction across subjects:\n{nan_pct.to_string()}", flush=True)


if __name__ == "__main__":
    main()
