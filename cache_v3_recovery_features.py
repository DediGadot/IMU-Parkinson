"""V3 Event-Locked Recovery Dynamics features (AR(2) post-transition).

Codex's #2 pick (2026-05-12 consult, expected ΔCCC +0.010 to +0.030):
  Item 12 (postural stability) is about perturbation recovery, not average
  gait statistics. V2 has summary stats; this captures the temporal RESPONSE
  LAW (damping, natural frequency, settling time) of trunk sway after
  transitions.

Mechanism:
  Per recording: detect transitions (sit-to-stand peak, turn events, gait
  start, gait stop, balance-task start). For each transition, take the
  0-5 s post-event window of LowerBack/Xiphoid Gyr+Acc signals. Fit an
  AR(2) autoregressive model. Extract complex roots → damping ratio (ζ)
  and natural frequency (ω_n). Plus exponential half-life, residual
  variance, peak overshoot.

Aggregation: median, p10, worst-3, L-R asymmetry per subject across
transitions in walking/balance tasks.

Orthogonality to V2 and V3-GSP:
  V2 aggregates entire recordings; V3-GSP captures spatial coordination at
  any instant. Neither captures the TEMPORAL DYNAMICAL response (how the
  system returns to equilibrium after a perturbation). AR(2) coefficients
  encode this response law explicitly.

Output: results/v3_recovery_features.csv (per-subject, prefix `rec_`).
"""
from __future__ import annotations

import argparse
import glob
import json
import multiprocessing as mp
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir

ensure_dir(RESULTS_DIR)
OUT_PATH = RESULTS_DIR / "v3_recovery_features.csv"
MANIFEST_PATH = RESULTS_DIR / "v3_recovery_features.csv.manifest.json"

FS = 100  # Hz
WIN_SEC = 5.0
WIN_SAMPLES = int(WIN_SEC * FS)

TASKS_WITH_TRANSITIONS = ["TUG", "Balance", "TandemGait"]

# Trunk sensors for recovery analysis
TRUNK_SENSORS = ["LowerBack", "Xiphoid", "Forehead"]

# Channels to extract recovery features from
TRUNK_CHANNELS = ["Gyr_X", "Gyr_Y", "Acc_X", "Acc_Y"]


def _fit_ar2(y: np.ndarray) -> dict[str, float]:
    """Fit AR(2) model y(t) = a1*y(t-1) + a2*y(t-2) + e(t).

    Returns dict with damping_ratio (zeta), natural_freq (omega_n in Hz),
    half_life (sec), residual_var, peak_overshoot, settling_time (samples).

    Stable AR(2) has |a2| < 1 and a1 + a2 < 1 and a2 - a1 < 1.
    Complex roots: r1,2 = (a1 ± sqrt(a1^2 + 4*a2)) / 2
    Continuous-time mapping: r = z = exp((-zeta*omega_n ± j*omega_d) * dt)
      |r|² = exp(-2*zeta*omega_n*dt) → -2*zeta*omega_n*dt = ln(|r|²)
      angle(r) = omega_d*dt
    """
    out: dict[str, float] = {
        "damping_ratio": np.nan,
        "natural_freq_hz": np.nan,
        "half_life_sec": np.nan,
        "residual_var": np.nan,
        "peak_overshoot": np.nan,
        "settling_time_samples": np.nan,
        "ar_a1": np.nan,
        "ar_a2": np.nan,
    }
    if len(y) < 20 or np.any(~np.isfinite(y)):
        return out
    # Center y (remove mean)
    y0 = y - np.mean(y)
    # Build X, Y for OLS: Y[t] = a1*Y[t-1] + a2*Y[t-2]
    Y_lhs = y0[2:]
    X_rhs = np.column_stack([y0[1:-1], y0[:-2]])
    try:
        coefs, residuals, rank, sv = np.linalg.lstsq(X_rhs, Y_lhs, rcond=None)
    except np.linalg.LinAlgError:
        return out
    a1, a2 = coefs
    out["ar_a1"] = float(a1)
    out["ar_a2"] = float(a2)
    # Residual variance
    y_pred = X_rhs @ coefs
    res = Y_lhs - y_pred
    out["residual_var"] = float(np.var(res))
    # Complex roots: z² - a1*z - a2 = 0 → z = (a1 ± sqrt(a1² + 4·a2)) / 2
    disc = a1 ** 2 + 4 * a2
    if disc < 0:
        # Complex conjugate roots (underdamped oscillation)
        re = a1 / 2
        im = np.sqrt(-disc) / 2
        z_mag = np.sqrt(re ** 2 + im ** 2)
        z_ang = np.arctan2(im, re)
    else:
        # Real roots (overdamped or critically damped)
        r1 = (a1 + np.sqrt(disc)) / 2
        r2 = (a1 - np.sqrt(disc)) / 2
        z_mag = max(abs(r1), abs(r2))
        z_ang = 0.0
    if z_mag >= 1.0 or z_mag <= 1e-6:
        return out  # Unstable AR(2)
    dt = 1.0 / FS
    # zeta * omega_n = -ln(|z|) / dt; omega_d = |angle(z)| / dt
    zeta_omega_n = -np.log(z_mag) / dt
    omega_d = abs(z_ang) / dt
    omega_n = np.sqrt(zeta_omega_n ** 2 + omega_d ** 2)
    zeta = zeta_omega_n / max(omega_n, 1e-12)
    out["damping_ratio"] = float(zeta)
    out["natural_freq_hz"] = float(omega_n / (2 * np.pi))
    # Half-life: |z|^t = 0.5 → t = ln(0.5) / ln(|z|)
    out["half_life_sec"] = float(np.log(0.5) / np.log(z_mag) * dt)
    # Peak overshoot (simulated free response to unit initial condition)
    n_sim = min(500, len(y))
    sim = np.zeros(n_sim)
    sim[0] = 1.0
    sim[1] = a1
    for t in range(2, n_sim):
        sim[t] = a1 * sim[t-1] + a2 * sim[t-2]
    out["peak_overshoot"] = float(np.max(np.abs(sim)))
    # Settling time: first t where |sim[t]| < 0.05
    settled = np.where(np.abs(sim) < 0.05)[0]
    out["settling_time_samples"] = float(settled[0]) if len(settled) > 0 else float(n_sim)
    return out


def _detect_transitions(df: pd.DataFrame, task: str) -> list[int]:
    """Heuristic transition detection per task.

    - TUG: detect sit-to-stand peak (LowerBack Acc-Z spike) + turn events
           (LowerBack Gyr-Z above 1.5 rad/s sustained 0.5s)
    - Balance: task start (first 0.5s after recording start)
    - TandemGait: gait initiation (LowerBack Acc magnitude rise)

    Returns sample indices of detected transitions.
    """
    if "LowerBack_Acc_Z" not in df.columns:
        return []
    n = len(df)
    acc_z = df["LowerBack_Acc_Z"].to_numpy()
    gyr_z = df["LowerBack_Gyr_Z"].to_numpy() if "LowerBack_Gyr_Z" in df.columns else np.zeros(n)
    transitions: list[int] = []

    if task == "TUG":
        # Sit-to-stand: peak |acc_z| in first 3s
        end_3s = min(300, n)
        if end_3s > 50:
            sts_peak = int(np.argmax(np.abs(acc_z[:end_3s])))
            if 50 < sts_peak < end_3s - 50:
                transitions.append(sts_peak)
        # Turn: gyr_z > 1.5 rad/s sustained
        turn_mask = np.abs(gyr_z) > 1.5
        if turn_mask.any():
            # First sustained turn (>50 samples consecutive)
            run = 0
            best_start = -1
            for i, v in enumerate(turn_mask):
                if v:
                    run += 1
                    if run == 50:
                        best_start = i - 49
                        break
                else:
                    run = 0
            if best_start > 0:
                transitions.append(best_start)
    elif task == "Balance":
        # Task start: 0.5s in
        if n > 100:
            transitions.append(50)
    elif task == "TandemGait":
        # Gait initiation: first acc magnitude rise above baseline
        acc_mag = np.sqrt(
            df.get("LowerBack_Acc_X", pd.Series(np.zeros(n))).to_numpy() ** 2
            + df.get("LowerBack_Acc_Y", pd.Series(np.zeros(n))).to_numpy() ** 2
            + acc_z ** 2
        )
        if len(acc_mag) > 100:
            baseline = np.median(acc_mag[:50])
            above = np.where(acc_mag > baseline * 1.5)[0]
            if len(above) > 0:
                transitions.append(int(above[0]))
    return transitions


def _per_transition_features(
    df: pd.DataFrame, transition_idx: int
) -> dict[str, float]:
    """Extract AR(2) recovery features per sensor x channel at one transition."""
    out: dict[str, float] = {}
    n = len(df)
    start = transition_idx
    end = min(transition_idx + WIN_SAMPLES, n)
    if end - start < 50:
        return out
    for sensor in TRUNK_SENSORS:
        for ch in TRUNK_CHANNELS:
            col = f"{sensor}_{ch}"
            if col not in df.columns:
                continue
            y = df[col].iloc[start:end].to_numpy().astype(np.float64)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ar2 = _fit_ar2(y)
            for k, v in ar2.items():
                out[f"{sensor}_{ch}_{k}"] = v
    return out


def _compute_recovery_one_recording(csv_path_str: str) -> tuple[str, str, dict[str, float]] | None:
    csv_path = Path(csv_path_str)
    stem = csv_path.stem
    parts = stem.split("_", 1)
    if len(parts) != 2:
        return None
    sid, task_raw = parts
    task = task_raw.replace("_mat", "").replace("TURN", "").strip("_")
    if task not in TASKS_WITH_TRANSITIONS:
        return None
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception:
        return None
    transitions = _detect_transitions(df, task)
    if not transitions:
        return None
    # Aggregate features across detected transitions in this recording (median)
    per_trans_feats: list[dict[str, float]] = []
    for ti in transitions:
        f = _per_transition_features(df, ti)
        if f:
            per_trans_feats.append(f)
    if not per_trans_feats:
        return None
    # Median across transitions
    keys = sorted(set().union(*[set(f.keys()) for f in per_trans_feats]))
    agg: dict[str, float] = {}
    for k in keys:
        vals = [f[k] for f in per_trans_feats if k in f and np.isfinite(f.get(k, np.nan))]
        if vals:
            agg[k] = float(np.median(vals))
    agg["n_transitions_detected"] = float(len(per_trans_feats))
    return (sid, task, agg)


def _aggregate_per_subject(
    rows: list[tuple[str, str, dict]]
) -> pd.DataFrame:
    by_sid_task: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for sid, task, feats in rows:
        by_sid_task[(sid, task)].append(feats)
    feature_keys = sorted(set().union(*[set(r[2].keys()) for r in rows]))
    records: list[dict] = []
    for (sid, task), feat_list in by_sid_task.items():
        rec = {"sid": sid, "task": task}
        for k in feature_keys:
            vals = [f[k] for f in feat_list if k in f and np.isfinite(f[k])]
            rec[k] = float(np.mean(vals)) if vals else np.nan
        records.append(rec)
    return pd.DataFrame(records)


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
    if not csv_dir.exists():
        raise FileNotFoundError(csv_dir)
    csv_files = sorted(csv_dir.glob("*.csv"))
    if args.smoke:
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

    # Filter to transition tasks
    trans_csvs = []
    for p in csv_files:
        stem = p.stem
        task_raw = stem.split("_", 1)[1] if "_" in stem else ""
        task = task_raw.replace("_mat", "").replace("TURN", "").strip("_")
        if task in TASKS_WITH_TRANSITIONS:
            trans_csvs.append(p)

    print(
        f"Processing {len(trans_csvs)} transition-task CSVs (of {len(csv_files)}) "
        f"with {args.workers} workers",
        flush=True,
    )

    rows: list[tuple[str, str, dict]] = []
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers) as pool:
        for i, r in enumerate(
            pool.imap_unordered(_compute_recovery_one_recording, [str(p) for p in trans_csvs], chunksize=4)
        ):
            if r is not None:
                rows.append(r)
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(trans_csvs)} elapsed={time.time()-t0:.0f}s",
                      flush=True)
    print(f"Done in {time.time()-t0:.0f}s. Valid rows: {len(rows)}", flush=True)

    if not rows:
        print("ERROR: no rows produced", flush=True)
        return

    df_long = _aggregate_per_subject(rows)
    print(f"  long shape = {df_long.shape}", flush=True)

    feature_keys = [c for c in df_long.columns if c not in ("sid", "task")]
    # Pivot per-subject
    pivoted = (
        df_long.set_index(["sid", "task"])[feature_keys].unstack("task")
    )
    pivoted.columns = [f"rec_{feat}__{task}" for feat, task in pivoted.columns]
    pivoted = pivoted.reset_index()
    print(f"  pivoted shape = {pivoted.shape}", flush=True)

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
        "script": "cache_v3_recovery_features.py",
        "git_sha": git_sha,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "labels_used": False,
        "cohort_statistics_used": False,
        "fold_scope": "global",
        "tasks": TASKS_WITH_TRANSITIONS,
        "ar_model_order": 2,
        "window_seconds": WIN_SEC,
        "n_features_total": pivoted.shape[1] - 1,
        "n_subjects": int(pivoted["sid"].nunique()),
        "rationale": "V3 event-locked AR(2) recovery dynamics; orthogonal temporal response law to V2/V3-GSP.",
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest {MANIFEST_PATH}", flush=True)


if __name__ == "__main__":
    main()
