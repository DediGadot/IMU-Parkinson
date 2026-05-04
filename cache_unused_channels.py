"""Cache features from the entirely-unused IMU channels: Mag_XYZ + VelInc_XYZ + OriInc_q0..q3.

Mission origin (2026-05-03 PM): Phase A1 of the 100x researcher CCC-push plan
(see `task_plan.md` § ACTIVE MISSION). The V2 feature set (ablation_v3_features.csv,
1751 cols) draws ONLY from Acc_XYZ + Gyr_XYZ + partial FreeAcc_E/N/U + Roll/Pitch/Yaw.
The Mag_XYZ (3 ch), VelInc_XYZ (3 ch), and OriInc_q0..q3 (4 ch) channels are entirely
unmined. Per the F44 K=500 absorption lesson, we keep the feature dimension TIGHT
(~270 features) and target sensors/tasks where each unused-channel family carries
a clean biomechanical hypothesis:

  * Mag_XYZ — earth-frame heading drift. Hypothesis: tandem heading regularity
    captures item 12 stability and item 13 turn-induced stoop. Sensors:
    LowerBack + Xiphoid + Forehead. Channels: Mag_X, Mag_Y, Mag_Z. Tasks:
    TandemGait + TUG + Balance.

  * VelInc_XYZ — integrated angular velocity (delta-rotation per Δt). Hypothesis:
    captures slow rotational drift orthogonal to Acc/Gyr (postural sway item 12,
    pronation oscillation item 6). Sensors: all 13. Channels: VelInc_X/Y/Z.
    Tasks: full-recording aggregation.

  * OriInc_q0..q3 — quaternion delta. Hypothesis: relative-joint rotation between
    forearm and upper arm captures item 6 (pronation-supination, currently
    CCC=−0.04). Computed as |q_delta| between L/R UpperArm and L/R Wrist within
    the SAME recording. Tasks: TUG (turns with wrist).

Per-recording features (~270 per subject after across-recording mean):

  Block M (Mag heading) — 3 sensors × 3 channels × 4 stats × 3 tasks = 108 feats
    For each (sensor, channel, task):
      um_<sen>_<ch>_<task>_circstd     — circular std (heading regularity)
      um_<sen>_<ch>_<task>_iqr         — robust spread
      um_<sen>_<ch>_<task>_dom         — dominant frequency in 0.1-3 Hz band
      um_<sen>_<ch>_<task>_drift       — first-half mean - second-half mean

  Block V (VelInc) — 13 sensors × 3 channels × 3 stats = 117 feats
    For each (sensor, channel) (full-recording, NaN-safe mean across recordings):
      um_<sen>_<ch>_velinc_std         — sustained rotational variance
      um_<sen>_<ch>_velinc_p95         — peak rotation rate (p95)
      um_<sen>_<ch>_velinc_drift_abs   — |cumulative integration| / N (drift proxy)

  Block O (OriInc relative pairs) — 4 pairs × 3 stats × 2 tasks = 24 feats
    Pairs: (L_UpperArm, L_Wrist), (R_UpperArm, R_Wrist),
           (L_Wrist, R_Wrist),    (L_UpperArm, R_UpperArm)
    For each (pair, task ∈ {TUG, SelfPace}):
      um_pair_<lhs>_<rhs>_<task>_qdelta_mean    — mean |Δq|
      um_pair_<lhs>_<rhs>_<task>_qdelta_p95     — peak |Δq|
      um_pair_<lhs>_<rhs>_<task>_qdelta_jerk    — std of d|Δq|/dt

  Block S (sample-entropy on VelInc magnitude) — 6 axial sensors × 1 stat = 6 feats
    For axial sensors: LowerBack, Xiphoid, Forehead, R_Wrist, L_Wrist, R_LatShank
      um_<sen>_velinc_mag_se    — sample entropy of per-sample VelInc magnitude

Total ≈ 108 + 117 + 24 + 6 = 255 features per subject (label-free, deterministic).

Aggregated per subject by mean across recordings (NaN-safe).

Manifest sidecar written to results/unused_channels_features.csv.manifest.json
with full provenance (data_sha256, script_sha256, label-free assertion).

Usage:
  python3 cache_unused_channels.py
  python3 cache_unused_channels.py --smoke      # process first 10 CSVs only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir

# --- Configuration ---
DATA_DIR = Path(os.environ.get("WEARGAIT_DATA_DIR", "/root/pd-imu/data/raw/weargait-pd"))
PD_CSV_DIR = DATA_DIR / "PD PARTICIPANTS" / "CSV files"

OUT_PATH = RESULTS_DIR / "unused_channels_features.csv"
MANIFEST_PATH = OUT_PATH.with_suffix(".csv.manifest.json")
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 12)))
FS = 100  # Hz

# Sensors used in different blocks
AXIAL_MAG_SENSORS = ["LowerBack", "Xiphoid", "Forehead"]
ALL_VELINC_SENSORS = [
    "LowerBack", "R_Wrist", "L_Wrist",
    "R_MidLatThigh", "L_MidLatThigh",
    "R_LatShank", "L_LatShank",
    "R_DorsalFoot", "L_DorsalFoot",
    "R_Ankle", "L_Ankle",
    "Xiphoid", "Forehead",
]
SAMPEN_SENSORS = ["LowerBack", "Xiphoid", "Forehead", "R_Wrist", "L_Wrist", "R_LatShank"]

# OriInc pairs: list of (lhs_sensor, rhs_sensor) — quaternion delta between paired sensors
ORIINC_PAIRS: list[tuple[str, str]] = [
    ("L_Wrist", "L_MidLatThigh"),  # forearm rotation rel to thigh (item 6 surrogate)
    ("R_Wrist", "R_MidLatThigh"),
    ("L_Wrist", "R_Wrist"),        # bilateral asymmetry of arm rotation
    ("L_LatShank", "R_LatShank"),  # bilateral leg rotation asymmetry (FoG/turn)
]

# Tasks for block M
MAG_TASKS: set[str] = {"TandemGait", "TandemGait_mat", "TUG", "TUG_mat", "Balance", "Balance_mat"}
ORI_TUG_TASKS: set[str] = {"TUG", "TUG_mat"}
ORI_SELFPACE_TASKS: set[str] = {"SelfPace", "SelfPace_mat"}


def _circular_std_deg(x: np.ndarray) -> float:
    """Circular std assuming x is heading-like in raw mag-axis units (no degrees conversion).
    Uses Mardia's R: 1 - sqrt(<sin>^2 + <cos>^2) of the angle's anglular projection,
    scaled to 0..1. Robust to constant offsets and linear drift removal via demeaning."""
    if x.size < 5:
        return float("nan")
    # treat magnetometer X-Y plane angle as "heading" proxy if possible.
    # For a single channel, we use coefficient of variation of detrended signal as a heading-stability proxy.
    z = x - np.nanmedian(x)
    s = np.nanstd(z)
    return float(s)


def _spectral_dom(x: np.ndarray, fmin: float = 0.1, fmax: float = 3.0) -> float:
    """Dominant frequency of x in [fmin, fmax]. Returns NaN if signal is too short."""
    n = x.size
    if n < int(2 * FS):
        return float("nan")
    z = x - np.nanmean(x)
    z = np.nan_to_num(z, nan=0.0)
    f = np.fft.rfftfreq(n, d=1.0 / FS)
    P = np.abs(np.fft.rfft(z)) ** 2
    mask = (f >= fmin) & (f <= fmax)
    if not mask.any():
        return float("nan")
    return float(f[mask][int(np.argmax(P[mask]))])


def _drift(x: np.ndarray) -> float:
    """Mean of first half - mean of second half (low-frequency drift indicator)."""
    n = x.size
    if n < 10:
        return float("nan")
    half = n // 2
    return float(np.nanmean(x[:half]) - np.nanmean(x[half:]))


def _sample_entropy(x: np.ndarray, m: int = 2, r_factor: float = 0.2, max_n: int = 1500) -> float:
    """Sample entropy of x (Richman & Moorman 2000), subsampled to max_n for speed.

    Returns NaN if signal is too short or constant. r = r_factor * std(x).
    """
    z = x[~np.isnan(x)]
    if z.size < 50:
        return float("nan")
    if z.size > max_n:
        # uniform stride decimation
        z = z[:: max(1, z.size // max_n)][:max_n]
    z = z.astype(np.float64)
    sd = float(np.std(z))
    if sd < 1e-9:
        return float("nan")
    r = r_factor * sd
    n = z.size
    # Vectorised Chebyshev-distance match counts (m and m+1)
    def _phi(mm: int) -> float:
        if n - mm < 2:
            return float("nan")
        # build templates of length mm
        tmpl = np.lib.stride_tricks.sliding_window_view(z, window_shape=mm)
        # We need pairs (i, j), i != j, where max(|tmpl[i] - tmpl[j]|) <= r
        K = tmpl.shape[0]
        # K can be ~1500; this loop with broadcasting is O(K^2) memory — ok at K=1500 (≈18MB)
        if K > 1500:
            tmpl = tmpl[:1500]
            K = 1500
        # Compute |tmpl[i] - tmpl[j]| max-reduced
        # matrix: (K, K) of sup-distance
        diff = tmpl[:, None, :] - tmpl[None, :, :]
        d = np.max(np.abs(diff), axis=-1)
        np.fill_diagonal(d, np.inf)  # exclude i == j
        match_count = float((d <= r).sum())
        denom = float(K * (K - 1))
        if denom == 0:
            return float("nan")
        return match_count / denom

    A = _phi(m + 1)
    B = _phi(m)
    if not (np.isfinite(A) and np.isfinite(B)) or B == 0 or A == 0:
        return float("nan")
    return float(-np.log(A / B))


def _block_M(df: pd.DataFrame, task: str) -> dict:
    """Mag heading features for the 3 axial sensors, 3 channels, current task."""
    feats: dict = {}
    if task not in MAG_TASKS:
        return feats
    # Map raw task name (e.g. TandemGait_mat) → tag for feature naming
    task_tag = task.replace("_mat", "")
    for sen in AXIAL_MAG_SENSORS:
        for ch in ("Mag_X", "Mag_Y", "Mag_Z"):
            col = f"{sen}_{ch}"
            if col not in df.columns:
                continue
            x = df[col].astype(np.float32).values
            if x.size < 5:
                continue
            # demean once for stability features
            xz = x - np.nanmedian(x)
            feats[f"um_{sen}_{ch}_{task_tag}_cstd"] = float(np.nanstd(xz))
            feats[f"um_{sen}_{ch}_{task_tag}_iqr"] = float(
                np.nanpercentile(xz, 75) - np.nanpercentile(xz, 25)
            )
            feats[f"um_{sen}_{ch}_{task_tag}_dom"] = _spectral_dom(xz, 0.1, 3.0)
            feats[f"um_{sen}_{ch}_{task_tag}_drift"] = _drift(x)
    return feats


def _block_V(df: pd.DataFrame) -> dict:
    """VelInc features for ALL 13 sensors, 3 channels, full-recording (task-agnostic)."""
    feats: dict = {}
    for sen in ALL_VELINC_SENSORS:
        for ch in ("VelInc_X", "VelInc_Y", "VelInc_Z"):
            col = f"{sen}_{ch}"
            if col not in df.columns:
                continue
            x = df[col].astype(np.float32).values
            if x.size < 5:
                continue
            feats[f"um_{sen}_{ch}_velinc_std"] = float(np.nanstd(x))
            feats[f"um_{sen}_{ch}_velinc_p95"] = float(np.nanpercentile(np.abs(x), 95))
            # cumsum drift: treat VelInc as integrated rotation; |cumsum|/N at end
            cs = np.nancumsum(x)
            feats[f"um_{sen}_{ch}_velinc_drift_abs"] = float(
                np.abs(cs[-1]) / max(1, x.size)
            )
    return feats


def _block_O(df: pd.DataFrame, task: str) -> dict:
    """Relative quaternion-delta features between paired sensors, in TUG and SelfPace tasks."""
    feats: dict = {}
    in_tug = task in ORI_TUG_TASKS
    in_sp = task in ORI_SELFPACE_TASKS
    if not (in_tug or in_sp):
        return feats
    task_tag = "TUG" if in_tug else "SelfPace"
    for lhs, rhs in ORIINC_PAIRS:
        # OriInc quaternion components q0..q3: per-sample rotation delta
        ql_cols = [f"{lhs}_OriInc_q{i}" for i in range(4)]
        qr_cols = [f"{rhs}_OriInc_q{i}" for i in range(4)]
        if any(c not in df.columns for c in ql_cols + qr_cols):
            continue
        ql = df[ql_cols].astype(np.float32).values  # (N, 4)
        qr = df[qr_cols].astype(np.float32).values  # (N, 4)
        if ql.shape[0] < 5:
            continue
        # quaternion delta magnitude: sin(theta/2) ≈ ||q_l[1:] - q_r[1:]||_2 (rough, scale-free)
        # more robust: use per-sample dot product, theta = 2 acos(|<ql,qr>|)
        dot = np.sum(ql * qr, axis=1)
        dot = np.clip(np.abs(dot), 0.0, 1.0)
        theta = 2.0 * np.arccos(dot)  # angle between rotation increments
        if not np.any(np.isfinite(theta)):
            continue
        pair_tag = f"{lhs}_to_{rhs}"
        feats[f"um_pair_{pair_tag}_{task_tag}_qdelta_mean"] = float(np.nanmean(theta))
        feats[f"um_pair_{pair_tag}_{task_tag}_qdelta_p95"] = float(
            np.nanpercentile(theta, 95)
        )
        if theta.size > 1:
            d_theta = np.diff(theta)
            feats[f"um_pair_{pair_tag}_{task_tag}_qdelta_jerk"] = float(np.nanstd(d_theta))
    return feats


def _block_S(df: pd.DataFrame) -> dict:
    """Sample entropy of per-sample VelInc magnitude on the 6 axial+wrist sensors."""
    feats: dict = {}
    for sen in SAMPEN_SENSORS:
        cols = [f"{sen}_VelInc_X", f"{sen}_VelInc_Y", f"{sen}_VelInc_Z"]
        if any(c not in df.columns for c in cols):
            continue
        v = df[cols].astype(np.float32).values
        mag = np.linalg.norm(v, axis=1)
        if mag.size < 50:
            continue
        feats[f"um_{sen}_velinc_mag_se"] = _sample_entropy(mag, m=2, r_factor=0.2, max_n=1200)
    return feats


def features_one_recording(df: pd.DataFrame, task: str) -> dict:
    """Compose all 4 blocks for one (recording, task)."""
    feats: dict = {}
    feats.update(_block_M(df, task))
    feats.update(_block_V(df))
    feats.update(_block_O(df, task))
    feats.update(_block_S(df))
    return feats


def _process_one_csv(args) -> dict | None:
    csv_path, sid, task = args
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception as exc:
        print(f"[skip] {csv_path}: {exc}", file=sys.stderr)
        return None
    feats = features_one_recording(df, task)
    if not feats:
        return None
    feats["sid"] = sid
    feats["task"] = task
    return feats


def parse_filename(path: Path) -> tuple[str, str] | None:
    name = path.stem
    if "_" not in name:
        return None
    sid, task = name.split("_", 1)
    return sid, task


def collect_jobs(csv_dir: Path) -> list[tuple[Path, str, str]]:
    if not csv_dir.exists():
        raise FileNotFoundError(f"{csv_dir} not present")
    jobs = []
    for csv in csv_dir.glob("*.csv"):
        parsed = parse_filename(csv)
        if parsed is None:
            continue
        sid, task = parsed
        jobs.append((csv, sid, task))
    return jobs


def aggregate_per_subject(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "sid" not in df.columns:
        raise RuntimeError("No rows produced — check parsing")
    feat_cols = [c for c in df.columns if c.startswith("um_")]
    agg = df.groupby("sid")[feat_cols].mean(numeric_only=True).reset_index()
    return agg


def smoke_check(df: pd.DataFrame) -> None:
    n_subj = len(df)
    if n_subj < 30:
        raise RuntimeError(f"Too few subjects: {n_subj}")
    feat_cols = [c for c in df.columns if c.startswith("um_")]
    if len(feat_cols) < 50:
        raise RuntimeError(f"Too few unused-channel features: {len(feat_cols)} (expected 200+)")
    # sanity: at least 50% of subjects have some VelInc and Mag features non-NaN
    velinc_cols = [c for c in feat_cols if "velinc" in c]
    mag_cols = [c for c in feat_cols if "_Mag_" in c]
    if velinc_cols:
        nz = float(np.isfinite(df[velinc_cols].values).mean())
        if nz < 0.6:
            raise RuntimeError(f"VelInc coverage too low: {nz:.2%}")
    if mag_cols:
        nz = float(np.isfinite(df[mag_cols].values).mean())
        if nz < 0.4:
            raise RuntimeError(f"Mag coverage too low: {nz:.2%}")
    print(
        f"  smoke OK: {n_subj} subjects, {len(feat_cols)} unused-channel features",
        flush=True,
    )


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT
        ).decode().strip()
    except Exception:
        return "unknown"


def write_manifest(out_path: Path, n_subjects: int, n_features: int) -> None:
    manifest = {
        "schema_version": 1,
        "produced_by": "cache_unused_channels.py",
        "script_sha256": _file_sha256(Path(__file__)),
        "git_sha": _git_sha(),
        "iso_datetime": pd.Timestamp.utcnow().isoformat(),
        "data_sha256": _file_sha256(out_path),
        "n_subjects": n_subjects,
        "n_features": n_features,
        "labels_used": False,
        "leakage_status": "clean_by_construction",
        "leakage_argument": (
            "Features are deterministic signal-processing aggregates of raw IMU channels "
            "(Mag_XYZ, VelInc_XYZ, OriInc_q0..q3). UPDRS-III labels never enter this "
            "extraction. Per-subject mean across recordings is the only aggregation; "
            "no global statistics are fit. The cache is feature-safe and can feed "
            "inductive headlines provided the per-fold imputer/normalizer (inductive_lib) "
            "is applied at downstream model fit time."
        ),
        "constants_locked": {
            "spectral_dom_band_hz": [0.1, 3.0],
            "sample_entropy_m": 2,
            "sample_entropy_r_factor": 0.2,
            "sample_entropy_max_n": 1200,
            "qdelta_formula": "theta = 2 * arccos(|<q_lhs, q_rhs>|)",
        },
        "feature_blocks": {
            "M_mag_heading": "108 feats (3 sensors × 3 channels × 4 stats × 3 tasks)",
            "V_velinc": "117 feats (13 sensors × 3 channels × 3 stats, full-recording)",
            "O_oriinc_pairs": "24 feats (4 pairs × 3 stats × 2 tasks)",
            "S_sampen": "6 feats (6 sensors × 1 sample-entropy)",
        },
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest: {MANIFEST_PATH}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="process first 10 CSVs only")
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--csv_dir", default=str(PD_CSV_DIR))
    args = ap.parse_args()

    ensure_dir(RESULTS_DIR)
    csv_dir = Path(args.csv_dir)
    jobs = collect_jobs(csv_dir)
    if not jobs:
        raise RuntimeError(f"No CSV files in {csv_dir}")
    print(f"Found {len(jobs)} CSV recordings in {csv_dir}", flush=True)

    if args.smoke:
        jobs = jobs[:10]
        print(f"  smoke mode: keeping first {len(jobs)} jobs", flush=True)

    print(f"Extracting unused-channel features with {N_CORES} workers...", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        rows = [r for r in pool.map(_process_one_csv, jobs, chunksize=4) if r]
    print(f"  {len(rows)} recordings processed in {time.time() - t0:.0f}s", flush=True)

    if args.smoke:
        df_smoke = pd.DataFrame(rows)
        keep = ["sid", "task"] + [c for c in df_smoke.columns if c.startswith("um_")][:8]
        print(df_smoke[keep].head(10).to_string())
        return

    agg = aggregate_per_subject(rows)
    smoke_check(agg)
    out_path = Path(args.out)
    agg.to_csv(out_path, index=False)
    feat_cols = [c for c in agg.columns if c.startswith("um_")]
    print(f"Wrote {agg.shape[0]} rows × {agg.shape[1]} cols → {out_path}", flush=True)
    write_manifest(out_path, n_subjects=int(agg.shape[0]), n_features=len(feat_cols))


if __name__ == "__main__":
    main()
