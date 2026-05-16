"""Richer PH + MFDFA cache (slot C of 2026-05-15 T1 ceiling push).

Extends the 2026-05-15 step-function cache (32 PH + 56 MFDFA cols) to:

PH:
  - 8 sensors: Xiphoid (trunk), LowerBack (sacrum), Forehead, Sternum,
    RWrist, LWrist, RAnkle, LAnkle.
  - 3 channel-types per sensor: pitch (from RPY), |gyro| magnitude, |acc| magnitude.
  - 2 Takens variants: (m=3, tau=5), (m=3, tau=10).
  - 5 stats per (sensor, channel, takens): h1_max, h1_med, h1_std, h1_count,
    h1_lifetime_entropy.
  - Total per task: ~ 8 sensors x 3 channels x 2 takens x 5 stats = 240
  - Aggregated mean across tasks: ~240 cols.

MFDFA:
  - 6 signals: stride_time, stride_amp, trunk_pitch, sacrum_ang_vel,
    foot_accel_mag, sternum_pitch.
  - q-grid: {-5, -3, -1, 1, 3, 5} (6 q values).
  - 4 stats per (signal, q): hurst_q, delta_alpha (singularity spectrum width),
    alpha_min, alpha_max.
  - Total per task: 6 signals x 6 q x 4 stats = 144
  - Aggregated mean across tasks: ~144 cols.

Target sensors and signals chosen to maximize coverage of items 13 (posture),
14 (body bradykinesia), and 10 (gait) where the original 2026-05-15 cache
showed Bonferroni-clearing per-item lifts.

Output:
  results/cache_stepfunction_v2_ph_richer_<UTC>.csv

Target-free; fold-locality applied at score time (per project rule).
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import socket
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from scipy.stats import entropy

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

RESULTS_DIR = REPO_ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# Sensor list: WearGait-PD raw column names per task CSV
# MATCHES cache_stepfunction_features.py:69-73 exactly.
SENSORS = [
    "LowerBack", "R_Wrist", "L_Wrist", "R_MidLatThigh", "L_MidLatThigh",
    "R_LatShank", "L_LatShank", "R_DorsalFoot", "L_DorsalFoot",
    "R_Ankle", "L_Ankle", "Xiphoid", "Forehead",
]

TASKS = ["TUG", "SelfPace", "HurriedPace", "TandemGait", "Balance",
         "SelfPace_mat", "HurriedPace_mat", "SelfPace_matTURN"]

TAKENS_VARIANTS = [(3, 5), (3, 10)]
Q_VALUES = [-5.0, -3.0, -1.0, 1.0, 3.0, 5.0]


def read_csv_safe(path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def magnitude(X: np.ndarray) -> np.ndarray:
    return np.sqrt((X ** 2).sum(axis=-1))


def _interp_clean(X: np.ndarray) -> np.ndarray | None:
    """NaN-interpolate per column; return None if too sparse."""
    if X.size == 0 or np.all(np.isnan(X)):
        return None
    for j in range(X.shape[1]):
        col = X[:, j]
        nans = np.isnan(col)
        if nans.any():
            valid = ~nans
            if valid.sum() < 10:
                return None
            col = pd.Series(col).interpolate(limit_direction="both").to_numpy()
            X[:, j] = col
    return X


def sensor_acc(df: pd.DataFrame, sensor: str) -> np.ndarray | None:
    cols = [f"{sensor}_Acc_X", f"{sensor}_Acc_Y", f"{sensor}_Acc_Z"]
    if not all(c in df.columns for c in cols): return None
    return _interp_clean(df[cols].to_numpy(np.float64))


def sensor_gyr(df: pd.DataFrame, sensor: str) -> np.ndarray | None:
    cols = [f"{sensor}_Gyr_X", f"{sensor}_Gyr_Y", f"{sensor}_Gyr_Z"]
    if not all(c in df.columns for c in cols): return None
    return _interp_clean(df[cols].to_numpy(np.float64))


def sensor_rpy(df: pd.DataFrame, sensor: str) -> np.ndarray | None:
    cols = [f"{sensor}_Roll", f"{sensor}_Pitch", f"{sensor}_Yaw"]
    if not all(c in df.columns for c in cols): return None
    return _interp_clean(df[cols].to_numpy(np.float64))


def _phase_space_embed(x: np.ndarray, m: int = 3, tau: int = 5, max_pts: int = 400) -> np.ndarray:
    n = len(x) - (m - 1) * tau
    if n <= 0:
        return np.empty((0, m))
    pts = np.empty((n, m))
    for i in range(m):
        pts[:, i] = x[i * tau : i * tau + n]
    if n > max_pts:
        idx = np.linspace(0, n - 1, max_pts).astype(int)
        pts = pts[idx]
    return pts


def _h1_persistence_summary_extended(pts: np.ndarray) -> dict[str, float]:
    """5-stat persistence summary."""
    try:
        from ripser import ripser
        result = ripser(pts, maxdim=1)
        diag1 = result["dgms"][1]
        if len(diag1) == 0:
            return {"h1_max": 0.0, "h1_med": 0.0, "h1_std": 0.0, "h1_count": 0.0, "h1_lifetime_entropy": 0.0}
        lifetimes = diag1[:, 1] - diag1[:, 0]
        lifetimes = lifetimes[np.isfinite(lifetimes)]
        if len(lifetimes) == 0:
            return {"h1_max": 0.0, "h1_med": 0.0, "h1_std": 0.0, "h1_count": 0.0, "h1_lifetime_entropy": 0.0}
        # Lifetime distribution entropy: histogram-based
        if len(lifetimes) > 1:
            hist, _ = np.histogram(lifetimes, bins=10, density=True)
            hist = hist[hist > 0]
            life_ent = float(entropy(hist + 1e-9))
        else:
            life_ent = 0.0
        return {
            "h1_max": float(np.max(lifetimes)),
            "h1_med": float(np.median(lifetimes)),
            "h1_std": float(np.std(lifetimes)),
            "h1_count": float(len(lifetimes)),
            "h1_lifetime_entropy": life_ent,
        }
    except Exception:
        n = len(pts)
        if n < 4:
            return {"h1_max": 0.0, "h1_med": 0.0, "h1_std": 0.0, "h1_count": 0.0, "h1_lifetime_entropy": 0.0}
        D = cdist(pts, pts)
        np.fill_diagonal(D, np.inf)
        k = min(5, n - 1)
        nn_dist = np.partition(D, k, axis=1)[:, k]
        return {
            "h1_max": float(np.max(nn_dist)),
            "h1_med": float(np.median(nn_dist)),
            "h1_std": float(np.std(nn_dist)),
            "h1_count": float(n),
            "h1_lifetime_entropy": 0.0,
        }


def ph_v2_features_per_task(df: pd.DataFrame) -> dict[str, float]:
    feat: dict[str, float] = {}
    for sensor in SENSORS:
        # Channel: pitch (axis 1 of RPY)
        rpy = sensor_rpy(df, sensor)
        if rpy is not None:
            pitch = rpy[:, 1]
            pitch = (pitch - pitch.mean()) / max(pitch.std(), 1e-6)
            for (m, tau) in TAKENS_VARIANTS:
                pts = _phase_space_embed(pitch, m=m, tau=tau, max_pts=400)
                if len(pts) > 50:
                    stats = _h1_persistence_summary_extended(pts)
                    for k, v in stats.items():
                        feat[f"ph2_{sensor}_pitch_m{m}t{tau}_{k}"] = v

        # Channel: |gyro| magnitude
        gyr = sensor_gyr(df, sensor)
        if gyr is not None:
            mag = magnitude(gyr)
            mag = (mag - mag.mean()) / max(mag.std(), 1e-6)
            for (m, tau) in TAKENS_VARIANTS:
                pts = _phase_space_embed(mag, m=m, tau=tau, max_pts=400)
                if len(pts) > 50:
                    stats = _h1_persistence_summary_extended(pts)
                    for k, v in stats.items():
                        feat[f"ph2_{sensor}_gyrmag_m{m}t{tau}_{k}"] = v

        # Channel: |acc| magnitude
        acc = sensor_acc(df, sensor)
        if acc is not None:
            mag = magnitude(acc)
            mag = (mag - mag.mean()) / max(mag.std(), 1e-6)
            for (m, tau) in TAKENS_VARIANTS:
                pts = _phase_space_embed(mag, m=m, tau=tau, max_pts=400)
                if len(pts) > 50:
                    stats = _h1_persistence_summary_extended(pts)
                    for k, v in stats.items():
                        feat[f"ph2_{sensor}_accmag_m{m}t{tau}_{k}"] = v
    return feat


def _mfdfa_q_range(signal: np.ndarray, scales: list[int], q_values: list[float], order: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Multifractal DFA. Returns (h_q, alpha_q) over q_values."""
    n = len(signal)
    if n < scales[-1] * 4:
        return np.zeros(len(q_values)), np.zeros(len(q_values))
    Y = np.cumsum(signal - signal.mean())
    F_q = np.zeros((len(q_values), len(scales)))
    for si, s in enumerate(scales):
        if s < 4: continue
        n_seg = n // s
        if n_seg < 2: continue
        Fvar = np.zeros(2 * n_seg)
        for v in range(n_seg):
            seg = Y[v * s : (v + 1) * s]
            x_fit = np.arange(s)
            try:
                pf = np.polyfit(x_fit, seg, order)
                trend = np.polyval(pf, x_fit)
                Fvar[v] = np.mean((seg - trend) ** 2)
            except Exception:
                Fvar[v] = 0
        for v in range(n_seg):
            seg = Y[n - (v + 1) * s : n - v * s]
            if len(seg) < s: continue
            x_fit = np.arange(s)
            try:
                pf = np.polyfit(x_fit, seg, order)
                trend = np.polyval(pf, x_fit)
                Fvar[n_seg + v] = np.mean((seg - trend) ** 2)
            except Exception:
                Fvar[n_seg + v] = 0
        Fvar = Fvar[Fvar > 0]
        if len(Fvar) < 4: continue
        for qi, q in enumerate(q_values):
            if abs(q) < 0.05:
                # Logarithmic limit at q=0
                F_q[qi, si] = np.exp(0.5 * np.mean(np.log(Fvar + 1e-12)))
            else:
                F_q[qi, si] = (np.mean(Fvar ** (q / 2.0))) ** (1.0 / q)
    # Generalized Hurst exponent h_q = slope of log(F_q) vs log(s)
    h_q = np.zeros(len(q_values))
    log_s = np.log(np.array(scales))
    for qi in range(len(q_values)):
        valid = F_q[qi] > 0
        if valid.sum() < 3: continue
        coef = np.polyfit(log_s[valid], np.log(F_q[qi, valid] + 1e-12), 1)
        h_q[qi] = coef[0]
    # Singularity spectrum α_q from h_q
    tau_q = np.array([q * h_q[qi] - 1 for qi, q in enumerate(q_values)])
    if len(q_values) > 2:
        alpha_q = np.gradient(tau_q, q_values)
    else:
        alpha_q = np.zeros_like(h_q)
    return h_q, alpha_q


def mfdfa_v2_features_per_task(df: pd.DataFrame) -> dict[str, float]:
    feat: dict[str, float] = {}
    scales = [8, 16, 32, 64]

    # Signal 1: trunk pitch
    rpy = sensor_rpy(df, "Xiphoid")
    if rpy is not None and len(rpy) > 200:
        sig = rpy[:, 1]
        h_q, alpha_q = _mfdfa_q_range(sig, scales=scales, q_values=Q_VALUES)
        for qi, q in enumerate(Q_VALUES):
            feat[f"mfdfa2_trunk_pitch_q{q:+.0f}_hurst"] = float(h_q[qi])
        if np.any(alpha_q != 0):
            feat["mfdfa2_trunk_pitch_delta_alpha"] = float(alpha_q.max() - alpha_q.min())
            feat["mfdfa2_trunk_pitch_alpha_min"] = float(alpha_q.min())
            feat["mfdfa2_trunk_pitch_alpha_max"] = float(alpha_q.max())

    # Signal 2: sacrum angular velocity magnitude
    gyr = sensor_gyr(df, "LowerBack")
    if gyr is not None and len(gyr) > 200:
        sig = magnitude(gyr)
        h_q, alpha_q = _mfdfa_q_range(sig, scales=scales, q_values=Q_VALUES)
        for qi, q in enumerate(Q_VALUES):
            feat[f"mfdfa2_sacrum_angmag_q{q:+.0f}_hurst"] = float(h_q[qi])
        if np.any(alpha_q != 0):
            feat["mfdfa2_sacrum_angmag_delta_alpha"] = float(alpha_q.max() - alpha_q.min())

    # Signal 3: R foot accel magnitude (R_DorsalFoot)
    acc = sensor_acc(df, "R_DorsalFoot")
    if acc is not None and len(acc) > 200:
        sig = magnitude(acc)
        h_q, alpha_q = _mfdfa_q_range(sig, scales=scales, q_values=Q_VALUES)
        for qi, q in enumerate(Q_VALUES):
            feat[f"mfdfa2_rfoot_accmag_q{q:+.0f}_hurst"] = float(h_q[qi])
        if np.any(alpha_q != 0):
            feat["mfdfa2_rfoot_accmag_delta_alpha"] = float(alpha_q.max() - alpha_q.min())

    # Signal 4: forehead pitch
    rpy_fh = sensor_rpy(df, "Forehead")
    if rpy_fh is not None and len(rpy_fh) > 200:
        sig = rpy_fh[:, 1]
        h_q, alpha_q = _mfdfa_q_range(sig, scales=scales, q_values=Q_VALUES)
        for qi, q in enumerate(Q_VALUES):
            feat[f"mfdfa2_forehead_pitch_q{q:+.0f}_hurst"] = float(h_q[qi])

    # Signal 5: thigh gyro magnitude (R_MidLatThigh) — gait stride dynamics
    gyr_th = sensor_gyr(df, "R_MidLatThigh")
    if gyr_th is not None and len(gyr_th) > 200:
        sig = magnitude(gyr_th)
        h_q, alpha_q = _mfdfa_q_range(sig, scales=scales, q_values=Q_VALUES)
        for qi, q in enumerate(Q_VALUES):
            feat[f"mfdfa2_rthigh_gyrmag_q{q:+.0f}_hurst"] = float(h_q[qi])
        if np.any(alpha_q != 0):
            feat["mfdfa2_rthigh_gyrmag_delta_alpha"] = float(alpha_q.max() - alpha_q.min())

    return feat


def process_subject(args: tuple) -> tuple[str, dict]:
    sid, data_dir, families = args
    data_dir = Path(data_dir)
    subj_feat: dict[str, list[float]] = {}
    n_tasks = 0
    for task in TASKS:
        csv_path = data_dir / f"{sid}_{task}.csv"
        if not csv_path.exists():
            continue
        df = read_csv_safe(csv_path)
        if df is None or len(df) < 100:
            continue
        n_tasks += 1
        if "ph_v2" in families:
            for k, v in ph_v2_features_per_task(df).items():
                subj_feat.setdefault(f"task_{task}_{k}", []).append(v)
        if "mfdfa_v2" in families:
            for k, v in mfdfa_v2_features_per_task(df).items():
                subj_feat.setdefault(f"task_{task}_{k}", []).append(v)
    out = {"sid": sid, "n_tasks": n_tasks}
    for k, vs in subj_feat.items():
        out[k] = float(np.mean(vs))
    return sid, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--families", default="ph_v2,mfdfa_v2")
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--subjects", default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if args.data_dir is None:
        for cand in [REPO_ROOT / "data" / "raw" / "weargait-pd" / "PD PARTICIPANTS" / "CSV files",
                     Path("/root/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files")]:
            if cand.exists():
                args.data_dir = str(cand)
                break
        else:
            print("ERROR: no data dir found", file=sys.stderr); return 1

    families = [f.strip() for f in args.families.split(",") if f.strip()]
    data_dir = Path(args.data_dir)
    all_sids = sorted({f.name.split("_")[0] for f in data_dir.glob("*.csv") if f.name.startswith(("NLS", "WPD"))})
    if args.subjects:
        wanted = {s.strip() for s in args.subjects.split(",")}
        all_sids = [s for s in all_sids if s in wanted]
    if args.limit:
        all_sids = all_sids[:args.limit]

    print(f"[cache_v2_richer] families={families} N={len(all_sids)} workers={args.workers}", flush=True)
    t0 = time.time()

    rows = []
    ctx = mp.get_context("spawn")
    os.environ["OMP_NUM_THREADS"] = "1"
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=ctx) as exec_pool:
        futs = {exec_pool.submit(process_subject, (sid, str(data_dir), families)): sid for sid in all_sids}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                sid, row = fut.result(timeout=1800)
                rows.append(row)
                if i % 5 == 0 or i == len(all_sids):
                    print(f"  [{i}/{len(all_sids)}] {sid} ({time.time()-t0:.0f}s)", flush=True)
            except Exception as e:
                sid = futs[fut]
                print(f"  [{i}/{len(all_sids)}] {sid} FAILED: {e}", flush=True)

    df = pd.DataFrame(rows).sort_values("sid").reset_index(drop=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fam_tag = "_".join(families)
    out_path = Path(args.out) if args.out else RESULTS_DIR / f"cache_stepfunction_v2_{fam_tag}_{ts}.csv"
    df.to_csv(out_path, index=False)
    manifest = {
        "script": Path(__file__).name,
        "command": " ".join(sys.argv),
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "labels_used": False, "fold_scope": "global", "cohort_statistics_used": False,
        "normalization_scope": "per_subject_per_window",
        "families": families,
        "n_subjects": len(df),
        "source_artifacts": ["data/raw/weargait-pd/PD PARTICIPANTS/CSV files/"],
        "host": socket.gethostname(),
    }
    out_path.with_suffix(out_path.suffix + ".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"\n[cache_v2_richer] wrote {out_path}  rows={len(df)} cols={df.shape[1]}", flush=True)
    print(f"[cache_v2_richer] elapsed: {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
