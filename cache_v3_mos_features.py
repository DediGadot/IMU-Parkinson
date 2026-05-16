"""V3 Margin-of-Stability (MoS) features at foot-strike events.

Codex's #1 pick (2026-05-12 consult, expected ΔCCC +0.015 to +0.040):
  Item 12 (postural stability) is about KEEPING extrapolated body mass inside
  the support base, not about average gait statistics. V2 has cadence, step
  length, COP path, but NOT explicit margin-of-stability quantities.

Mechanism (codex):
  Per stride (foot-strike event), compute:
    - Trunk velocity at strike (proxy for v_COM)
    - Trunk angular velocity at strike (instability indicator)
    - Trunk lean at strike (Roll/Pitch from Lumbar)
    - Step width / foot separation (from Walkway X)
    - Foot velocity ratio (foot placement gain)
  Aggregate per subject: median, p10 (worst 10%), worst-3 mean, asymmetry.

Orthogonality to V2: V2 has per-sensor aggregates over whole recording. MoS is
*event-locked* (at foot-strike only), conditional on the stride's stability
posture. Different mathematical basis. Codex specifically warned: "residualize
against DST speed/cadence/double-support inside each train fold to escape
the 'collapses to gait speed' failure mode." We compute the raw features here;
the residualization (if needed) can happen at chain training time.

Output: results/v3_mos_features.csv (per-subject, prefix `mos_`).
Manifest: label-free, fold_scope=global, per goal-v1 Tier-2.
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
OUT_PATH = RESULTS_DIR / "v3_mos_features.csv"
MANIFEST_PATH = RESULTS_DIR / "v3_mos_features.csv.manifest.json"

FS = 100  # Hz

# Tasks where foot-strike detection is meaningful (walking-like)
TASKS_GAIT: list[str] = ["SelfPace", "HurriedPace", "TUG", "TandemGait"]


def _detect_strikes(contact_signal: np.ndarray) -> np.ndarray:
    """Rising-edge of L/R Foot Contact -> sample indices of heel-strikes."""
    c = (contact_signal > 0.5).astype(np.int8)
    edges = np.where(np.diff(c) > 0)[0] + 1  # +1 to point to first contact sample
    return edges


def _per_stride_features(
    df: pd.DataFrame, foot: str
) -> list[dict[str, float]] | None:
    """foot in {'L', 'R'}. Return list of per-stride dicts."""
    contact_col = f"{foot} Foot Contact"
    if contact_col not in df.columns:
        return None
    strikes = _detect_strikes(df[contact_col].to_numpy())
    if len(strikes) < 3:
        return None

    # Sensor columns (LowerBack as COM proxy; shanks/feet for lower-limb info)
    cols_needed = [
        "LowerBack_VelInc_X", "LowerBack_VelInc_Y", "LowerBack_VelInc_Z",
        "LowerBack_Gyr_X", "LowerBack_Gyr_Y", "LowerBack_Gyr_Z",
        "LowerBack_Roll", "LowerBack_Pitch", "LowerBack_Yaw",
        f"{foot}_LatShank_VelInc_X", f"{foot}_LatShank_VelInc_Y",
        f"{foot}_LatShank_Gyr_X", f"{foot}_LatShank_Gyr_Y",
        f"{foot}_DorsalFoot_VelInc_X", f"{foot}_DorsalFoot_VelInc_Y",
    ]
    for c in cols_needed:
        if c not in df.columns:
            return None

    # Pre-compute trunk velocity (cumulative VelInc — coarse proxy)
    trunk_vel = df[["LowerBack_VelInc_X", "LowerBack_VelInc_Y", "LowerBack_VelInc_Z"]].to_numpy()
    trunk_gyr = df[["LowerBack_Gyr_X", "LowerBack_Gyr_Y", "LowerBack_Gyr_Z"]].to_numpy()
    trunk_lean = df[["LowerBack_Roll", "LowerBack_Pitch", "LowerBack_Yaw"]].to_numpy()
    shank_vel = df[[f"{foot}_LatShank_VelInc_X", f"{foot}_LatShank_VelInc_Y"]].to_numpy()
    foot_vel = df[[f"{foot}_DorsalFoot_VelInc_X", f"{foot}_DorsalFoot_VelInc_Y"]].to_numpy()

    out: list[dict[str, float]] = []
    T = len(df)
    for s_idx in strikes:
        if s_idx >= T:
            continue
        # 50ms window centered on strike — average to smooth
        a = max(0, s_idx - 5)
        b = min(T, s_idx + 5)
        f: dict[str, float] = {}

        # Trunk velocity magnitude at strike (instantaneous v_COM proxy)
        tv = trunk_vel[a:b].mean(axis=0)
        f["trunk_vel_mag_at_strike"] = float(np.linalg.norm(tv))
        f["trunk_vel_ml_at_strike"] = float(tv[0])
        f["trunk_vel_ap_at_strike"] = float(tv[1])
        f["trunk_vel_vt_at_strike"] = float(tv[2])

        # Trunk angular velocity at strike (instability indicator)
        tg = trunk_gyr[a:b].mean(axis=0)
        f["trunk_gyr_mag_at_strike"] = float(np.linalg.norm(tg))
        f["trunk_gyr_ml_at_strike"] = float(np.abs(tg[0]))
        f["trunk_gyr_ap_at_strike"] = float(np.abs(tg[1]))

        # Trunk lean at strike
        tl = trunk_lean[a:b].mean(axis=0)
        f["trunk_lean_roll_at_strike"] = float(tl[0])
        f["trunk_lean_pitch_at_strike"] = float(tl[1])

        # Shank velocity at strike (foot-placement gain)
        sv = shank_vel[a:b].mean(axis=0)
        f["shank_vel_ml_at_strike"] = float(sv[0])
        f["shank_vel_ap_at_strike"] = float(sv[1])

        # Foot velocity at strike (deceleration)
        fv = foot_vel[a:b].mean(axis=0)
        f["foot_vel_mag_at_strike"] = float(np.linalg.norm(fv))

        # Trunk velocity to foot velocity ratio (stability gain proxy)
        f["trunk_to_foot_vel_ratio_at_strike"] = (
            float(np.linalg.norm(tv) / (np.linalg.norm(fv) + 1e-6))
        )

        # Stride duration (in samples) until next strike
        idx_in_list = list(strikes).index(s_idx)
        if idx_in_list + 1 < len(strikes):
            f["stride_dur_samples"] = float(strikes[idx_in_list + 1] - s_idx)
        else:
            f["stride_dur_samples"] = np.nan

        out.append(f)
    return out


def _aggregate_per_subject(strides_L: list[dict], strides_R: list[dict]) -> dict[str, float]:
    """Aggregate per-stride features into per-subject scalars.

    For each feature: median, p10, p90, IQR, worst-3 mean (L+R combined).
    Plus L-R median asymmetry (|median_L - median_R| / (median_L + median_R)).
    """
    out: dict[str, float] = {}
    if not strides_L and not strides_R:
        return out
    all_strides = strides_L + strides_R
    feat_keys = sorted(set().union(*[set(s.keys()) for s in all_strides]))
    for k in feat_keys:
        vals = [s[k] for s in all_strides if k in s and np.isfinite(s.get(k, np.nan))]
        if len(vals) < 3:
            continue
        v = np.asarray(vals)
        out[f"{k}_median"] = float(np.median(v))
        out[f"{k}_p10"] = float(np.percentile(v, 10))
        out[f"{k}_p90"] = float(np.percentile(v, 90))
        out[f"{k}_iqr"] = float(np.percentile(v, 75) - np.percentile(v, 25))
        # Worst-3 mean (lowest 3 values)
        sorted_v = np.sort(v)
        n_worst = min(3, len(v))
        out[f"{k}_worst3_mean"] = float(np.mean(sorted_v[:n_worst]))

    # L-R asymmetry of median
    if strides_L and strides_R:
        for k in feat_keys:
            vL = [s[k] for s in strides_L if k in s and np.isfinite(s.get(k, np.nan))]
            vR = [s[k] for s in strides_R if k in s and np.isfinite(s.get(k, np.nan))]
            if len(vL) >= 3 and len(vR) >= 3:
                mL, mR = np.median(vL), np.median(vR)
                denom = abs(mL) + abs(mR) + 1e-6
                out[f"{k}_lr_asym"] = float(abs(mL - mR) / denom)

    out["n_strides_L"] = float(len(strides_L))
    out["n_strides_R"] = float(len(strides_R))
    return out


def _compute_mos_one_recording(csv_path_str: str) -> tuple[str, str, dict[str, float]] | None:
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
    strides_L = _per_stride_features(df, "L") or []
    strides_R = _per_stride_features(df, "R") or []
    if not strides_L and not strides_R:
        return None
    feats = _aggregate_per_subject(strides_L, strides_R)
    return (sid, task, feats)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv_dir",
        default="/home/fiod/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files",
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    csv_dir = Path(args.csv_dir)
    if not csv_dir.exists():
        raise FileNotFoundError(csv_dir)
    csv_files = sorted(csv_dir.glob("*.csv"))
    if args.smoke:
        # First 5 subjects' walking recordings
        seen_sids: set[str] = set()
        keep: list[Path] = []
        for p in csv_files:
            sid = p.stem.split("_", 1)[0]
            if sid not in seen_sids:
                if len(seen_sids) >= 5:
                    break
                seen_sids.add(sid)
            keep.append(p)
        csv_files = keep

    # Filter to gait tasks only
    gait_csvs = []
    for p in csv_files:
        stem = p.stem
        task_raw = stem.split("_", 1)[1] if "_" in stem else ""
        task = task_raw.replace("_mat", "").replace("TURN", "").strip("_")
        if task in TASKS_GAIT:
            gait_csvs.append(p)

    print(
        f"Processing {len(gait_csvs)} gait CSV files (out of {len(csv_files)} total) "
        f"with {args.workers} workers",
        flush=True,
    )

    rows: list[tuple[str, str, dict]] = []
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers) as pool:
        for i, r in enumerate(
            pool.imap_unordered(_compute_mos_one_recording, [str(p) for p in gait_csvs], chunksize=4)
        ):
            if r is not None:
                rows.append(r)
            if (i + 1) % 50 == 0:
                print(
                    f"  {i+1}/{len(gait_csvs)} processed "
                    f"elapsed={time.time()-t0:.0f}s",
                    flush=True,
                )
    print(f"Done in {time.time()-t0:.0f}s. Valid rows: {len(rows)}", flush=True)

    if not rows:
        print("ERROR: no rows", flush=True)
        return

    # Aggregate per (sid, task) -> mean across recordings (mat / _TURN variants)
    by_sid_task: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for sid, task, feats in rows:
        by_sid_task[(sid, task)].append(feats)

    feature_keys = sorted(set().union(*[set(r[2].keys()) for r in rows]))
    print(f"  total feature keys = {len(feature_keys)}", flush=True)

    records: list[dict] = []
    for (sid, task), feat_list in by_sid_task.items():
        rec = {"sid": sid, "task": task}
        for k in feature_keys:
            vals = [f[k] for f in feat_list if k in f and np.isfinite(f[k])]
            rec[k] = float(np.mean(vals)) if vals else np.nan
        records.append(rec)
    df_long = pd.DataFrame(records)
    print(f"  long shape = {df_long.shape}", flush=True)

    # Pivot to per-subject
    pivoted = (
        df_long.set_index(["sid", "task"])[feature_keys].unstack("task")
    )
    pivoted.columns = [f"mos_{feat}__{task}" for feat, task in pivoted.columns]
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
        "script": "cache_v3_mos_features.py",
        "git_sha": git_sha,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "labels_used": False,
        "cohort_statistics_used": False,
        "fold_scope": "global",
        "tasks": TASKS_GAIT,
        "n_features_total": pivoted.shape[1] - 1,
        "n_subjects": int(pivoted["sid"].nunique()),
        "rationale": "V3 stability-margin features at foot-strike events; orthogonal to V2 (event-locked vs whole-recording aggregates).",
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest {MANIFEST_PATH}", flush=True)


if __name__ == "__main__":
    main()
