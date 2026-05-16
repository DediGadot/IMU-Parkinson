"""V3 TITD (Trial-Internal Temporal Drift) features.

DeepSeek's #1 pick (2026-05-12 4-CLI consult, expected ΔCCC +0.005 to +0.020):
  Motor fatigability: PD patients' gait deteriorates WITHIN a single continuous
  walk. V2 averages across all strides → discards trend. V3-GSP captures
  instantaneous coupling. NEITHER captures the temporal evolution of stride
  parameters within a trial.

Mechanism (deepseek):
  Per task, per stride: extract (stride_time, stride_length_proxy, peak_vertical_acc).
  Per parameter: OLS slope β (drift), variance ratio (last-Q std² / first-Q std²),
  Kendall τ (monotonicity of drift).

Orthogonality argument:
  V2 = 0th moment (mean over strides).
  TITD = 1st moment (linear trend over strides).
  V3-GSP = spatial graph Fourier (no temporal trend dimension).
  Predicted error correlation: 0.25-0.45 vs V2, 0.20-0.40 vs V3-GSP.

Compute: ~2 sec/subject CPU.
Output: results/v3_titd_features.csv (per-subject, prefix `titd_`).
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
from scipy.stats import kendalltau

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir

ensure_dir(RESULTS_DIR)
OUT_PATH = RESULTS_DIR / "v3_titd_features.csv"
MANIFEST_PATH = RESULTS_DIR / "v3_titd_features.csv.manifest.json"

FS = 100  # Hz
MIN_STRIDES = 10  # minimum stride count for trend estimation

# Tasks with sufficient strides for trend analysis
TASKS_GAIT_TREND: list[str] = ["SelfPace", "HurriedPace", "TandemGait"]


def _detect_strikes(contact_signal: np.ndarray) -> np.ndarray:
    c = (contact_signal > 0.5).astype(np.int8)
    edges = np.where(np.diff(c) > 0)[0] + 1
    return edges


def _per_stride_params(
    df: pd.DataFrame, foot: str
) -> list[dict[str, float]] | None:
    """Per-stride: stride_time, stride_length_proxy, peak_vertical_acc."""
    contact_col = f"{foot} Foot Contact"
    if contact_col not in df.columns:
        return None
    strikes = _detect_strikes(df[contact_col].to_numpy())
    if len(strikes) < MIN_STRIDES:
        return None

    # Use LowerBack FreeAcc as trunk reference (gravity-removed)
    if "LowerBack_FreeAcc_U" not in df.columns:
        return None
    free_acc_u = df["LowerBack_FreeAcc_U"].to_numpy()  # vertical
    # Magnitude of full FreeAcc
    if all(c in df.columns for c in ["LowerBack_FreeAcc_E", "LowerBack_FreeAcc_N", "LowerBack_FreeAcc_U"]):
        free_acc_mag = np.sqrt(
            df["LowerBack_FreeAcc_E"].to_numpy() ** 2
            + df["LowerBack_FreeAcc_N"].to_numpy() ** 2
            + df["LowerBack_FreeAcc_U"].to_numpy() ** 2
        )
    else:
        free_acc_mag = np.abs(free_acc_u)

    out: list[dict[str, float]] = []
    for i in range(len(strikes) - 1):
        s0 = strikes[i]
        s1 = strikes[i + 1]
        if s1 - s0 < 30 or s1 - s0 > 250:  # 0.3 - 2.5 s
            continue
        # stride time (seconds)
        st = (s1 - s0) / FS
        # stride length proxy: cumulative |FreeAcc| over stride (proportional to displacement curvature)
        sl_proxy = float(np.sum(np.abs(free_acc_mag[s0:s1])))
        # peak vertical acc within stride (foot clearance proxy)
        pv = float(np.max(np.abs(free_acc_u[s0:s1])))
        out.append({
            "stride_time": float(st),
            "stride_length_proxy": sl_proxy,
            "peak_vertical_acc": pv,
        })
    return out


def _trend_features(per_stride: list[dict]) -> dict[str, float]:
    """Compute OLS slope, variance ratio, Kendall τ for each parameter.

    Drift slope is normalized by parameter mean to be dimensionless.
    """
    out: dict[str, float] = {}
    if len(per_stride) < MIN_STRIDES:
        return out

    n = len(per_stride)
    idx = np.arange(n).astype(np.float64)
    half = n // 2
    quarter = n // 4

    for key in ("stride_time", "stride_length_proxy", "peak_vertical_acc"):
        vals = np.array([s[key] for s in per_stride], dtype=np.float64)
        if not np.all(np.isfinite(vals)) or vals.std() < 1e-9:
            continue
        mean_v = float(np.mean(vals))
        # OLS slope (normalized: per-stride change as fraction of mean)
        cov_ix = float(np.cov(idx, vals, ddof=1)[0, 1])
        var_i = float(np.var(idx, ddof=1))
        beta = cov_ix / max(var_i, 1e-12)
        out[f"titd_{key}_slope"] = float(beta / max(abs(mean_v), 1e-9))
        # Variance ratio: last quartile / first quartile std
        first_q = vals[:max(quarter, 5)]
        last_q = vals[-max(quarter, 5):]
        out[f"titd_{key}_var_ratio"] = (
            float(last_q.std() / (first_q.std() + 1e-9))
        )
        # Kendall τ (monotonicity)
        if n >= MIN_STRIDES:
            try:
                tau, _ = kendalltau(idx, vals)
                out[f"titd_{key}_kendall_tau"] = float(tau) if np.isfinite(tau) else 0.0
            except Exception:
                out[f"titd_{key}_kendall_tau"] = 0.0
        # Coefficient of variation (CV) for sanity
        out[f"titd_{key}_intra_trial_cv"] = float(vals.std() / max(abs(mean_v), 1e-9))
        # Maximum-of-half-window-difference (worst stretch deterioration)
        if n >= 2 * MIN_STRIDES:
            first_half_mean = float(np.mean(vals[:half]))
            last_half_mean = float(np.mean(vals[half:]))
            out[f"titd_{key}_half_diff_pct"] = (
                (last_half_mean - first_half_mean) / max(abs(mean_v), 1e-9)
            )
    return out


def _compute_titd_one_recording(csv_path_str: str) -> tuple[str, str, dict[str, float]] | None:
    csv_path = Path(csv_path_str)
    stem = csv_path.stem
    parts = stem.split("_", 1)
    if len(parts) != 2:
        return None
    sid, task_raw = parts
    task = task_raw.replace("_mat", "").replace("TURN", "").strip("_")
    if task not in TASKS_GAIT_TREND:
        return None
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception:
        return None

    out: dict[str, float] = {}
    for foot in ["L", "R"]:
        strides = _per_stride_params(df, foot)
        if not strides or len(strides) < MIN_STRIDES:
            continue
        feats = _trend_features(strides)
        for k, v in feats.items():
            out[f"{k}_{foot}"] = v
        out[f"n_strides_{foot}"] = float(len(strides))

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

    # Filter to gait tasks
    trend_csvs = []
    for p in csv_files:
        stem = p.stem
        task_raw = stem.split("_", 1)[1] if "_" in stem else ""
        task = task_raw.replace("_mat", "").replace("TURN", "").strip("_")
        if task in TASKS_GAIT_TREND:
            trend_csvs.append(p)

    print(f"Processing {len(trend_csvs)} gait CSVs with {args.workers} workers",
          flush=True)
    t0 = time.time()
    rows: list[tuple[str, str, dict]] = []
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers) as pool:
        for i, r in enumerate(
            pool.imap_unordered(_compute_titd_one_recording, [str(p) for p in trend_csvs], chunksize=4)
        ):
            if r is not None:
                rows.append(r)
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(trend_csvs)} done elapsed={time.time()-t0:.0f}s",
                      flush=True)
    print(f"Done in {time.time()-t0:.0f}s. Valid rows: {len(rows)}", flush=True)

    if not rows:
        print("ERROR: no rows", flush=True)
        return

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
        "script": "cache_v3_titd_features.py",
        "git_sha": git_sha,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "labels_used": False,
        "cohort_statistics_used": False,
        "fold_scope": "global",
        "tasks": TASKS_GAIT_TREND,
        "min_strides": MIN_STRIDES,
        "rationale": "V3 trial-internal temporal drift features (motor fatigability); orthogonal 1st-moment dimension vs V2 (0th moment) and V3-GSP (spatial graph spectrum).",
        "n_features_total": pivoted.shape[1] - 1,
        "n_subjects": int(pivoted["sid"].nunique()),
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest {MANIFEST_PATH}", flush=True)


if __name__ == "__main__":
    main()
