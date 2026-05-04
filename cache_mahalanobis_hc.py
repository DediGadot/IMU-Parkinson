"""Cache Mahalanobis-distance-to-HC-manifold features (Method 2 in fusion mission).

Approach:
- Use rocket_recordings.npz (26 magnitude channels = 13 sensors × {Acc_mag, Gyr_mag},
  100 Hz, 10s windows). Contains BOTH 80 HC and 98 PD subjects.
- For each (sensor, channel_kind, task), compute simple statistics per recording:
  mean, std, p5, p95, dom_freq, sef95.
  ⇒ 6 stats per (sensor, channel_kind, task), forming a feature vector.
- Aggregate per-subject as MEAN across recordings of the same task.
- Per task, fit a robust mean μ_HC and covariance Σ_HC of HC subjects only via
  sklearn MinCovDet (Minimum Covariance Determinant). Singular Σ → fall back to
  diagonal MCD or LedoitWolf shrinkage.
- For each PD subject (and HC, for sanity), compute Mahalanobis distance per task.
- Per sensor (and globally), aggregate distances across tasks: mean, max, sum.

Crucially: HC stats are computed ONCE from ALL HC subjects. They are NEVER touched
by PD train/test splits. This is NOT a leak because HC subjects are never present
in the PD test fold (HC are categorically excluded from the PD label space).

Output: results/mahalanobis_hc_subj.csv

Usage:
  python3 cache_mahalanobis_hc.py
  python3 cache_mahalanobis_hc.py --smoke
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import welch
from sklearn.covariance import LedoitWolf, MinCovDet

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir

ROCKET_CACHE = RESULTS_DIR / "rocket_recordings.npz"
OUT_PATH = RESULTS_DIR / "mahalanobis_hc_subj.csv"

FS = 100  # Hz
SENSORS = [
    "L_Wrist", "R_Wrist", "LowerBack", "L_Thigh", "R_Thigh",
    "L_Shank", "R_Shank", "L_DorsalFoot", "R_DorsalFoot",
    "L_Ankle", "R_Ankle", "Xiphoid", "Forehead",
]
# Tasks we care about — keep `_mat` separate (different walkway condition) but
# also pool both for a "any-gait" task to keep N_HC large per task for MCD.
TASK_GROUPS: dict[str, set[str]] = {
    "SelfPace":   {"SelfPace", "SelfPace_mat"},
    "HurriedPace": {"HurriedPace", "HurriedPace_mat"},
    "TUG":        {"TUG", "TUG_mat"},
    "Balance":    {"Balance", "Balance_mat"},
    "TandemGait": {"TandemGait", "TandemGait_mat"},
}
CHANNEL_KINDS = ("acc", "gyr")
STATS_PER_CHANNEL = ("mean", "std", "p5", "p95", "dom_freq", "sef95")


def is_hc(sid: str) -> bool:
    s = str(sid).upper()
    return s.startswith("HC") or s.startswith("WHC")


def is_pd(sid: str) -> bool:
    s = str(sid).upper()
    return s.startswith("NLS") or s.startswith("WPD")


def channel_features(x: np.ndarray, fs: int = FS) -> tuple[float, ...]:
    """Return (mean, std, p5, p95, dom_freq, sef95) for one channel time-series."""
    if x.size == 0 or np.all(~np.isfinite(x)):
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    xc = x[np.isfinite(x)].astype(np.float64)
    mean = float(np.mean(xc))
    std = float(np.std(xc))
    p5 = float(np.percentile(xc, 5))
    p95 = float(np.percentile(xc, 95))
    if len(xc) >= fs * 2:
        try:
            f, p = welch(xc - np.mean(xc), fs=fs,
                         nperseg=min(256, len(xc)), noverlap=128)
            if p.sum() < 1e-12:
                dom_freq, sef95 = 0.0, 0.0
            else:
                dom_freq = float(f[int(np.argmax(p))])
                cum = np.cumsum(p) / np.sum(p)
                idx = int(np.searchsorted(cum, 0.95))
                sef95 = float(f[min(idx, len(f) - 1)])
        except Exception:
            dom_freq, sef95 = 0.0, 0.0
    else:
        dom_freq, sef95 = 0.0, 0.0
    return mean, std, p5, p95, dom_freq, sef95


def recording_feature_vec(rec: np.ndarray) -> np.ndarray:
    """Return per-(sensor, channel_kind) feature vector — 13 sensors × 2 ch × 6 stats = 156."""
    feats: list[float] = []
    for si, _ in enumerate(SENSORS):
        for kind_idx, _ in enumerate(CHANNEL_KINDS):
            ch_idx = si * 2 + kind_idx  # acc=0, gyr=1
            feats.extend(channel_features(rec[ch_idx]))
    return np.asarray(feats, dtype=np.float64)


def fit_mcd_safe(X: np.ndarray, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Return (mu, inv_cov). Robust fit via MinCovDet → fallback to LedoitWolf."""
    n, d = X.shape
    if n < d + 2:
        # Underdetermined for full-rank covariance — use LedoitWolf shrinkage
        lw = LedoitWolf().fit(X)
        cov = lw.covariance_
    else:
        try:
            mcd = MinCovDet(random_state=seed,
                            support_fraction=max(0.5, (d + n + 1) / (2 * n)))
            mcd.fit(X)
            cov = mcd.covariance_
        except Exception:
            lw = LedoitWolf().fit(X)
            cov = lw.covariance_
    mu = np.mean(X, axis=0)
    # Regularize covariance
    cov = cov + np.eye(d) * 1e-3
    try:
        inv = np.linalg.pinv(cov)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(cov + np.eye(d) * 1e-2)
    return mu, inv


def mahalanobis(x: np.ndarray, mu: np.ndarray, inv_cov: np.ndarray) -> float:
    diff = x - mu
    val = float(diff @ inv_cov @ diff)
    if val < 0 or not np.isfinite(val):
        return 0.0
    return float(np.sqrt(val))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    ensure_dir(RESULTS_DIR)
    if not ROCKET_CACHE.exists():
        raise FileNotFoundError(f"Missing {ROCKET_CACHE}")

    print(f"[mah] Loading {ROCKET_CACHE}", flush=True)
    cache = np.load(ROCKET_CACHE, allow_pickle=True)
    recs = cache["recordings"]    # (N_rec, 26, T)
    sids = cache["sids"]          # (N_rec,)
    tasks = cache["tasks"]        # (N_rec,)
    print(f"[mah] {len(recs)} recordings, {len(np.unique(sids))} subjects, "
          f"tasks={list(np.unique(tasks))}", flush=True)

    # Compute per-recording feature vectors (sliced per task group)
    print("[mah] Computing per-recording feature vectors", flush=True)
    t0 = time.time()
    n_total_features = len(SENSORS) * len(CHANNEL_KINDS) * len(STATS_PER_CHANNEL)
    rec_X = np.zeros((len(recs), n_total_features), dtype=np.float64)
    if args.smoke:
        smoke_n = 50
        for i in range(min(smoke_n, len(recs))):
            rec_X[i] = recording_feature_vec(recs[i])
    else:
        for i in range(len(recs)):
            rec_X[i] = recording_feature_vec(recs[i])
            if (i + 1) % 200 == 0:
                print(f"[mah]  {i+1}/{len(recs)} recordings ({time.time()-t0:.0f}s)",
                      flush=True)
    print(f"[mah] feature-vec extraction done in {time.time()-t0:.1f}s", flush=True)

    # Per-task: aggregate per-subject feature vectors via mean across that subject's
    # recordings within the task group.
    feature_dim = n_total_features
    out_rows: dict[str, dict] = {}  # sid → flat features
    pd_sids: list[str] = []
    hc_sids: list[str] = []
    for s in np.unique(sids):
        if is_pd(s):
            pd_sids.append(s)
        elif is_hc(s):
            hc_sids.append(s)
    pd_sids.sort()
    hc_sids.sort()
    print(f"[mah] PD={len(pd_sids)}, HC={len(hc_sids)}", flush=True)

    summary_lines: list[str] = []
    for task_label, task_set in TASK_GROUPS.items():
        mask = np.array([t in task_set for t in tasks])
        if not mask.any():
            continue
        X_task = rec_X[mask]
        sids_task = sids[mask]
        # Per-subject feature vec = mean over recordings
        per_subj: dict[str, np.ndarray] = {}
        for sid_u in np.unique(sids_task):
            sub_X = X_task[sids_task == sid_u]
            per_subj[sid_u] = np.mean(sub_X, axis=0)
        # Build HC matrix
        hc_mat = np.array([per_subj[s] for s in hc_sids if s in per_subj])
        if hc_mat.shape[0] < 5:
            print(f"[mah]  task={task_label}: only {hc_mat.shape[0]} HC, skipping",
                  flush=True)
            continue
        # Standardize features (z-score on HC) before MCD — Mahalanobis is scale-invariant
        # but conditioning improves with z-scoring at finite samples
        mu_z = np.mean(hc_mat, axis=0)
        sd_z = np.std(hc_mat, axis=0)
        sd_z = np.where(sd_z < 1e-9, 1.0, sd_z)
        hc_z = (hc_mat - mu_z) / sd_z
        # Drop near-zero-variance columns to keep MCD well-conditioned
        keep = np.std(hc_z, axis=0) > 1e-3
        if keep.sum() < 5:
            print(f"[mah]  task={task_label}: too few non-degenerate features, skip",
                  flush=True)
            continue
        hc_z_keep = hc_z[:, keep]
        mu_hc, inv_cov = fit_mcd_safe(hc_z_keep)
        summary_lines.append(
            f"task={task_label}: HC={hc_mat.shape[0]}, dim={int(keep.sum())}/{feature_dim}, "
            f"cond={np.linalg.cond(inv_cov):.2e}"
        )
        # Pre-fit per-sensor MCD ONCE per task (not per subject) — major speedup
        per_sensor_models: list[tuple | None] = []
        for si, sname in enumerate(SENSORS):
            start = si * len(CHANNEL_KINDS) * len(STATS_PER_CHANNEL)
            end = start + len(CHANNEL_KINDS) * len(STATS_PER_CHANNEL)
            hc_s = hc_mat[:, start:end]
            mu_s = np.mean(hc_s, axis=0)
            sd_s = np.std(hc_s, axis=0)
            sd_s = np.where(sd_s < 1e-9, 1.0, sd_s)
            hc_sz = (hc_s - mu_s) / sd_s
            ks = np.std(hc_sz, axis=0) > 1e-3
            if ks.sum() < 3:
                per_sensor_models.append(None)
                continue
            hc_sz_k = hc_sz[:, ks]
            mu_block, inv_block = fit_mcd_safe(hc_sz_k)
            per_sensor_models.append((sname, mu_block, inv_block, mu_s, sd_s, ks))
        # Per-PD subject Mahalanobis distance globally + per sensor
        for sid_u in pd_sids + hc_sids:  # also compute for HC for sanity
            if sid_u not in per_subj:
                continue
            xv = per_subj[sid_u]
            xz = (xv - mu_z) / sd_z
            xz_keep = xz[keep]
            d_global = mahalanobis(xz_keep, mu_hc, inv_cov)
            row = out_rows.setdefault(sid_u, {})
            row[f"mah_{task_label}_global"] = d_global
            for si, mdl in enumerate(per_sensor_models):
                if mdl is None:
                    continue
                sname, mu_block, inv_block, mu_s, sd_s, ks = mdl
                start = si * len(CHANNEL_KINDS) * len(STATS_PER_CHANNEL)
                end = start + len(CHANNEL_KINDS) * len(STATS_PER_CHANNEL)
                xv_s = (xv[start:end] - mu_s) / sd_s
                xv_sk = xv_s[ks]
                d_s = mahalanobis(xv_sk, mu_block, inv_block)
                row[f"mah_{task_label}_{sname}"] = d_s

    if not out_rows:
        print("[mah] FAILED: no rows produced", flush=True)
        return 1

    # Build DataFrame
    all_keys = sorted({k for r in out_rows.values() for k in r})
    rows: list[dict] = []
    for sid_u, row in sorted(out_rows.items()):
        rec = {"sid": sid_u}
        for k in all_keys:
            rec[k] = row.get(k, np.nan)
        rows.append(rec)
    df = pd.DataFrame(rows)

    # Add aggregations across tasks: mean / max / sum of global Mahalanobis
    global_cols = [c for c in df.columns if c.endswith("_global")]
    df["mah_global_mean"] = df[global_cols].mean(axis=1)
    df["mah_global_max"] = df[global_cols].max(axis=1)
    df["mah_global_sum"] = df[global_cols].sum(axis=1)

    # Per-sensor across-task aggregates
    for sname in SENSORS:
        sensor_cols = [c for c in df.columns
                       if c.startswith("mah_") and c.endswith(f"_{sname}")]
        if sensor_cols:
            df[f"mah_sensor_{sname}_mean"] = df[sensor_cols].mean(axis=1)
            df[f"mah_sensor_{sname}_max"] = df[sensor_cols].max(axis=1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    feat_cols = [c for c in df.columns if c != "sid"]
    nan_ratio = df[feat_cols].isna().mean().mean()
    print(f"[mah] Wrote {args.out} — {len(df)} rows × {len(feat_cols)} features",
          flush=True)
    print(f"[mah] NaN ratio: {nan_ratio:.3f}", flush=True)
    print("[mah] HC fit summaries:", flush=True)
    for line in summary_lines:
        print(f"[mah]   {line}", flush=True)

    # Quick PD/HC distance sanity (transductive — HC should have lower median d)
    df_pd = df[df["sid"].apply(is_pd)]
    df_hc = df[df["sid"].apply(is_hc)]
    print(f"[mah] mah_global_mean: PD median={df_pd['mah_global_mean'].median():.2f}, "
          f"HC median={df_hc['mah_global_mean'].median():.2f}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
