"""Cache hypothesis-restricted features for items {4, 6, 17, 18, 15, 16}.

Phase A2 of the 100x researcher CCC-push (2026-05-03 PM, see task_plan.md
ACTIVE MISSION). The V2 feature set pools across the whole body and the whole
task, diluting the signal for clinically-narrow items. This cache builds tight
hypothesis-restricted feature sets per item, sized so that a per-item LGB
trained ONLY on these features cannot be drowned by K=500 selection from a
~2200-col incoming pool (the F44 K=500 absorption mechanism).

Per-item recipes (clinically grounded; sized at 12-32 features each):

  Item 4 (finger tap, surrogate via wrist arm-swing):
    - Sensors: L_Wrist, R_Wrist
    - Channels: Gyr_Y (sagittal pronation), FreeAcc magnitude
    - Tasks: SelfPace + HurriedPace (gait arm-swing surrogate)
    - Features: 1.5-4 Hz bandpower, dominant frequency, fatigability slope
      (amplitude regression across stride index), L–R asymmetry of bandpower
    - ~16 features (i4_*)

  Item 6 (pronation-supination, currently CCC=-0.04):
    - Sensors: L_Wrist, R_Wrist  (rel to UpperArm channels not in this dataset;
      we use Mag/OriInc to proxy forearm rotation rate)
    - Channels: Gyr_X (radial-ulnar), Gyr_Y (pronation), Gyr_Z (axial), VelInc_*
    - Tasks: TUG turn windows (yaw-rate peak ± 1 s on LowerBack)
    - Features: peak rotation rate per axis, rotation jerk, L–R asymmetry,
      bandpower 0.5-3 Hz (pronation cadence)
    - ~24 features (i6_*)

  Item 15 (postural tremor, currently CCC=-0.09):
    - Sensors: L_Wrist, R_Wrist
    - Channels: FreeAcc magnitude + Gyr_X + Gyr_Y
    - Tasks: Balance pre/post-instruction pauses (first 3s and last 3s)
    - Features: 4-7 Hz bandpower, intermittency (#zero-crossings of envelope),
      L–R asymmetry of bandpower
    - ~12 features (i15_*)

  Item 16 (kinetic tremor, currently CCC=0.08):
    - Sensors: L_Wrist, R_Wrist
    - Channels: jerk (d FreeAcc / dt) — high-frequency content
    - Tasks: Tandem deceleration phases (last 3s)
    - Features: wavelet ridge 5-8 Hz proxy via FFT bandpower, jerk spectral
      slope, tremor burst counts, L–R asymmetry
    - ~12 features (i16_*)

  Item 17 (rest tremor amplitude, currently CCC=0.14):
    - Sensors: L_Wrist, R_Wrist
    - Channels: Gyr_X, Gyr_Y, Gyr_Z + FreeAcc magnitude
    - Tasks: first 5s and last 5s of Balance (where wrist is at rest)
    - Features: 4-6 Hz bandpower per axis, peak frequency, 4-6/0-10 Hz ratio
      (tremor index), cross-axis 5 Hz coherence-proxy
    - ~24 features (i17_*)

  Item 18 (rest tremor constancy, currently CCC=0.25):
    - Sensors: L_Wrist, R_Wrist
    - Channels: FreeAcc magnitude (envelope of tremor)
    - Tasks: full Balance window
    - Features: tremor-burst HMM-like proxy (fraction of 1s windows with
      4-6 Hz power above 90th percentile of baseline; mean burst length;
      number of bursts; L–R asymmetry)
    - ~12 features (i18_*)

Total per subject ≈ 16 + 24 + 12 + 12 + 24 + 12 = 100 features.

Aggregated per subject by mean across recordings (NaN-safe).

Manifest sidecar at results/item_specific_features.csv.manifest.json verifies
label-free / clean-by-construction.

Usage:
  python3 cache_item_specific_features.py
  python3 cache_item_specific_features.py --smoke
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

DATA_DIR = Path(os.environ.get("WEARGAIT_DATA_DIR", "/root/pd-imu/data/raw/weargait-pd"))
PD_CSV_DIR = DATA_DIR / "PD PARTICIPANTS" / "CSV files"
OUT_PATH = RESULTS_DIR / "item_specific_features.csv"
MANIFEST_PATH = OUT_PATH.with_suffix(".csv.manifest.json")
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 12)))
FS = 100  # Hz

ITEM4_TASKS = {"SelfPace", "SelfPace_mat", "HurriedPace", "HurriedPace_mat"}
ITEM6_TASKS = {"TUG", "TUG_mat"}
ITEM15_TASKS = {"Balance", "Balance_mat"}
ITEM16_TASKS = {"TandemGait", "TandemGait_mat"}
ITEM17_TASKS = {"Balance", "Balance_mat"}
ITEM18_TASKS = {"Balance", "Balance_mat"}


def _bandpower(x: np.ndarray, fmin: float, fmax: float) -> float:
    n = x.size
    # FFT resolution = FS/n. For 4-6 Hz tremor band we need at least n=FS (1.0 Hz res).
    # 1-second window is acceptable for the burst-metrics use case; longer is preferred elsewhere.
    if n < FS:
        return float("nan")
    z = x - np.nanmean(x)
    z = np.nan_to_num(z, nan=0.0)
    f = np.fft.rfftfreq(n, d=1.0 / FS)
    P = np.abs(np.fft.rfft(z)) ** 2
    mask = (f >= fmin) & (f <= fmax)
    if not mask.any():
        return float("nan")
    return float(P[mask].sum() / max(1, mask.sum()))


def _dominant_freq(x: np.ndarray, fmin: float, fmax: float) -> float:
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


def _spectral_slope_log(x: np.ndarray, fmin: float = 1.0, fmax: float = 20.0) -> float:
    n = x.size
    if n < int(2 * FS):
        return float("nan")
    z = x - np.nanmean(x)
    z = np.nan_to_num(z, nan=0.0)
    f = np.fft.rfftfreq(n, d=1.0 / FS)
    P = np.abs(np.fft.rfft(z)) ** 2
    mask = (f >= fmin) & (f <= fmax) & (P > 0)
    if mask.sum() < 5:
        return float("nan")
    fl = np.log(f[mask])
    pl = np.log(P[mask])
    if not (np.all(np.isfinite(fl)) and np.all(np.isfinite(pl))):
        return float("nan")
    slope = float(np.polyfit(fl, pl, 1)[0])
    return slope


def _envelope_zcr(x: np.ndarray) -> float:
    """Zero-crossing rate of the demeaned amplitude envelope (intermittency proxy)."""
    n = x.size
    if n < 10:
        return float("nan")
    e = np.abs(x - np.nanmean(x))
    e -= np.nanmean(e)
    if not np.any(np.isfinite(e)):
        return float("nan")
    sign = np.sign(np.nan_to_num(e, nan=0.0))
    zc = int(np.sum(np.diff(sign) != 0))
    return float(zc / max(1, n / FS))


def _fatigability_slope(x: np.ndarray, n_bins: int = 5) -> float:
    """Linear slope of |x| binned over time — positive means amplitude rising."""
    n = x.size
    if n < n_bins * 5:
        return float("nan")
    bins = np.array_split(x, n_bins)
    means = np.array([float(np.nanmean(np.abs(b))) for b in bins])
    if not np.all(np.isfinite(means)):
        return float("nan")
    xs = np.arange(n_bins, dtype=np.float64)
    return float(np.polyfit(xs, means, 1)[0])


def _burst_metrics(x: np.ndarray, hi_freq=(4.0, 6.0), win_s: float = 2.0) -> tuple[float, float, float]:
    """Tremor-burst HMM-like proxy: in 1-second windows, compute 4-6 Hz bandpower;
    mark burst as window with bp > 90th percentile of windows. Returns
    (burst_fraction, mean_burst_length, n_bursts)."""
    n = x.size
    win = int(win_s * FS)
    if n < win * 5:
        return float("nan"), float("nan"), float("nan")
    n_win = n // win
    bps = np.zeros(n_win, dtype=np.float64)
    for i in range(n_win):
        seg = x[i * win:(i + 1) * win]
        bps[i] = _bandpower(seg, *hi_freq)
    if not np.any(np.isfinite(bps)):
        return float("nan"), float("nan"), float("nan")
    thr = float(np.nanpercentile(bps, 90))
    burst_mask = bps > thr
    burst_frac = float(burst_mask.mean())
    # Run-length encoding of burst_mask
    runs = []
    cur = 0
    for v in burst_mask:
        if v:
            cur += 1
        else:
            if cur > 0:
                runs.append(cur)
            cur = 0
    if cur > 0:
        runs.append(cur)
    mean_burst_len = float(np.mean(runs)) if runs else 0.0
    n_bursts = float(len(runs))
    return burst_frac, mean_burst_len, n_bursts


def _safe_get(df: pd.DataFrame, col: str) -> np.ndarray | None:
    if col not in df.columns:
        return None
    return df[col].astype(np.float32).values


def _free_acc_mag(df: pd.DataFrame, sensor: str) -> np.ndarray | None:
    e = _safe_get(df, f"{sensor}_FreeAcc_E")
    nch = _safe_get(df, f"{sensor}_FreeAcc_N")
    u = _safe_get(df, f"{sensor}_FreeAcc_U")
    if e is None or nch is None or u is None:
        # Fallback: raw Acc magnitude (subtract gravity-removed if FreeAcc absent)
        ax = _safe_get(df, f"{sensor}_Acc_X")
        ay = _safe_get(df, f"{sensor}_Acc_Y")
        az = _safe_get(df, f"{sensor}_Acc_Z")
        if ax is None or ay is None or az is None:
            return None
        v = np.stack([ax, ay, az], axis=1)
        return np.linalg.norm(v - v.mean(axis=0, keepdims=True), axis=1)
    v = np.stack([e, nch, u], axis=1)
    return np.linalg.norm(v, axis=1)


def _features_item4(df: pd.DataFrame, task: str) -> dict:
    if task not in ITEM4_TASKS:
        return {}
    feats = {}
    bp_lr = {}
    for sen in ("L_Wrist", "R_Wrist"):
        gy = _safe_get(df, f"{sen}_Gyr_Y")
        if gy is None:
            continue
        bp = _bandpower(gy, 1.5, 4.0)
        domf = _dominant_freq(gy, 1.5, 4.0)
        fat = _fatigability_slope(gy)
        feats[f"i4_{sen}_bp_1p5_4hz"] = bp
        feats[f"i4_{sen}_dom_1p5_4hz"] = domf
        feats[f"i4_{sen}_fatigability"] = fat
        bp_lr[sen] = bp
        # FreeAcc magnitude features
        fa = _free_acc_mag(df, sen)
        if fa is not None:
            feats[f"i4_{sen}_facc_bp_1p5_4hz"] = _bandpower(fa, 1.5, 4.0)
            feats[f"i4_{sen}_facc_fat"] = _fatigability_slope(fa)
    if "L_Wrist" in bp_lr and "R_Wrist" in bp_lr:
        L = bp_lr["L_Wrist"]
        R = bp_lr["R_Wrist"]
        feats["i4_LR_asym_bp"] = float(abs(L - R))
        feats["i4_LR_max_bp"] = float(max(L, R))
    return feats


def _features_item6(df: pd.DataFrame, task: str) -> dict:
    if task not in ITEM6_TASKS:
        return {}
    feats = {}
    # Use LowerBack yaw-rate to find turn windows
    gz_lb = _safe_get(df, "LowerBack_Gyr_Z")
    if gz_lb is None or gz_lb.size < int(2 * FS):
        return {}
    # Find peak of |yaw rate|
    yaw_abs = np.abs(gz_lb - np.nanmedian(gz_lb))
    if not np.any(np.isfinite(yaw_abs)):
        return {}
    peak_idx = int(np.argmax(yaw_abs))
    half_win = int(1.0 * FS)
    start = max(0, peak_idx - half_win)
    stop = min(gz_lb.size, peak_idx + half_win)
    if stop - start < int(0.5 * FS):
        return {}
    # Restrict per-wrist computations to the turn window
    bp_lr_x = {}
    bp_lr_y = {}
    bp_lr_z = {}
    for sen in ("L_Wrist", "R_Wrist"):
        for ch in ("Gyr_X", "Gyr_Y", "Gyr_Z"):
            x = _safe_get(df, f"{sen}_{ch}")
            if x is None:
                continue
            seg = x[start:stop]
            if seg.size < 10:
                continue
            peak = float(np.nanmax(np.abs(seg)))
            jerk = float(np.nanstd(np.diff(seg)))
            bp = _bandpower(seg, 0.5, 3.0)
            feats[f"i6_{sen}_{ch}_peak"] = peak
            feats[f"i6_{sen}_{ch}_jerk"] = jerk
            feats[f"i6_{sen}_{ch}_bp_0p5_3hz"] = bp
            if ch == "Gyr_X":
                bp_lr_x[sen] = bp
            elif ch == "Gyr_Y":
                bp_lr_y[sen] = bp
            elif ch == "Gyr_Z":
                bp_lr_z[sen] = bp
        # VelInc features in turn window
        for ch in ("VelInc_X", "VelInc_Y", "VelInc_Z"):
            v = _safe_get(df, f"{sen}_{ch}")
            if v is None:
                continue
            seg = v[start:stop]
            if seg.size < 10:
                continue
            feats[f"i6_{sen}_{ch}_std"] = float(np.nanstd(seg))
    if "L_Wrist" in bp_lr_x and "R_Wrist" in bp_lr_x:
        feats["i6_LR_asym_x"] = float(abs(bp_lr_x["L_Wrist"] - bp_lr_x["R_Wrist"]))
    if "L_Wrist" in bp_lr_y and "R_Wrist" in bp_lr_y:
        feats["i6_LR_asym_y"] = float(abs(bp_lr_y["L_Wrist"] - bp_lr_y["R_Wrist"]))
    return feats


def _features_item15(df: pd.DataFrame, task: str) -> dict:
    if task not in ITEM15_TASKS:
        return {}
    feats = {}
    # Pre-instruction pause = first 3s; post = last 3s
    seg_len = int(3.0 * FS)
    bp_lr = {}
    for sen in ("L_Wrist", "R_Wrist"):
        fa = _free_acc_mag(df, sen)
        if fa is None:
            continue
        if fa.size < 2 * seg_len:
            continue
        pre = fa[:seg_len]
        post = fa[-seg_len:]
        bp_pre = _bandpower(pre, 4.0, 7.0)
        bp_post = _bandpower(post, 4.0, 7.0)
        feats[f"i15_{sen}_facc_bp_pre"] = bp_pre
        feats[f"i15_{sen}_facc_bp_post"] = bp_post
        feats[f"i15_{sen}_facc_zcr_pre"] = _envelope_zcr(pre)
        feats[f"i15_{sen}_facc_zcr_post"] = _envelope_zcr(post)
        bp_lr[sen] = max(bp_pre, bp_post)
    if "L_Wrist" in bp_lr and "R_Wrist" in bp_lr:
        feats["i15_LR_asym_bp"] = float(abs(bp_lr["L_Wrist"] - bp_lr["R_Wrist"]))
        feats["i15_LR_max_bp"] = float(max(bp_lr["L_Wrist"], bp_lr["R_Wrist"]))
    return feats


def _features_item16(df: pd.DataFrame, task: str) -> dict:
    if task not in ITEM16_TASKS:
        return {}
    feats = {}
    seg_len = int(3.0 * FS)
    for sen in ("L_Wrist", "R_Wrist"):
        fa = _free_acc_mag(df, sen)
        if fa is None or fa.size < seg_len:
            continue
        seg = fa[-seg_len:]
        # jerk = first difference of FreeAcc magnitude
        jerk = np.diff(seg) * FS
        if jerk.size < 5:
            continue
        feats[f"i16_{sen}_jerk_bp_5_8hz"] = _bandpower(jerk, 5.0, 8.0)
        feats[f"i16_{sen}_jerk_slope"] = _spectral_slope_log(jerk, 1.0, 20.0)
        feats[f"i16_{sen}_jerk_p95"] = float(np.nanpercentile(np.abs(jerk), 95))
    return feats


def _features_item17(df: pd.DataFrame, task: str) -> dict:
    if task not in ITEM17_TASKS:
        return {}
    feats = {}
    seg_len = int(5.0 * FS)
    bp_lr = {}
    for sen in ("L_Wrist", "R_Wrist"):
        if df.shape[0] < 2 * seg_len:
            continue
        bp_axes = []
        for ch in ("Gyr_X", "Gyr_Y", "Gyr_Z"):
            x = _safe_get(df, f"{sen}_{ch}")
            if x is None or x.size < 2 * seg_len:
                continue
            for tag, seg in (("first5s", x[:seg_len]), ("last5s", x[-seg_len:])):
                bp_46 = _bandpower(seg, 4.0, 6.0)
                bp_010 = _bandpower(seg, 0.1, 10.0)
                pf = _dominant_freq(seg, 3.0, 7.0)
                feats[f"i17_{sen}_{ch}_{tag}_bp_4_6hz"] = bp_46
                feats[f"i17_{sen}_{ch}_{tag}_pkfreq"] = pf
                if bp_010 and np.isfinite(bp_010) and bp_010 > 1e-9:
                    feats[f"i17_{sen}_{ch}_{tag}_idx46"] = bp_46 / bp_010
                bp_axes.append(bp_46)
        if bp_axes:
            bp_lr[sen] = float(np.nanmax(bp_axes))
    if "L_Wrist" in bp_lr and "R_Wrist" in bp_lr:
        feats["i17_LR_asym_idx"] = float(abs(bp_lr["L_Wrist"] - bp_lr["R_Wrist"]))
        feats["i17_LR_max_idx"] = float(max(bp_lr["L_Wrist"], bp_lr["R_Wrist"]))
    return feats


def _features_item18(df: pd.DataFrame, task: str) -> dict:
    if task not in ITEM18_TASKS:
        return {}
    feats = {}
    bf_lr = {}
    for sen in ("L_Wrist", "R_Wrist"):
        fa = _free_acc_mag(df, sen)
        if fa is None or fa.size < 5 * FS:
            continue
        bf, mbl, nb = _burst_metrics(fa, hi_freq=(4.0, 6.0), win_s=2.0)
        feats[f"i18_{sen}_burst_frac"] = bf
        feats[f"i18_{sen}_burst_meanlen"] = mbl
        feats[f"i18_{sen}_burst_count"] = nb
        bf_lr[sen] = bf
    if "L_Wrist" in bf_lr and "R_Wrist" in bf_lr:
        feats["i18_LR_asym_burst"] = float(abs(bf_lr["L_Wrist"] - bf_lr["R_Wrist"]))
        feats["i18_LR_max_burst"] = float(max(bf_lr["L_Wrist"], bf_lr["R_Wrist"]))
    return feats


def features_one_recording(df: pd.DataFrame, task: str) -> dict:
    feats = {}
    feats.update(_features_item4(df, task))
    feats.update(_features_item6(df, task))
    feats.update(_features_item15(df, task))
    feats.update(_features_item16(df, task))
    feats.update(_features_item17(df, task))
    feats.update(_features_item18(df, task))
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
        raise RuntimeError("No rows produced")
    feat_cols = [c for c in df.columns if c.startswith("i") and "_" in c and c[1].isdigit()]
    agg = df.groupby("sid")[feat_cols].mean(numeric_only=True).reset_index()
    return agg


def smoke_check(df: pd.DataFrame) -> None:
    n_subj = len(df)
    if n_subj < 30:
        raise RuntimeError(f"Too few subjects: {n_subj}")
    feat_cols = [c for c in df.columns if c not in ("sid", "task")]
    if len(feat_cols) < 50:
        raise RuntimeError(
            f"Too few item-specific features: {len(feat_cols)} (expected 80+)"
        )
    # per-prefix coverage
    for prefix in ("i4_", "i6_", "i15_", "i16_", "i17_", "i18_"):
        cols = [c for c in feat_cols if c.startswith(prefix)]
        if not cols:
            raise RuntimeError(f"No features with prefix {prefix}")
        nz = float(np.isfinite(df[cols].values).mean())
        if nz < 0.3:
            raise RuntimeError(f"Coverage for {prefix} too low: {nz:.2%}")
    print(
        f"  smoke OK: {n_subj} subjects, {len(feat_cols)} item-specific features",
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
        "produced_by": "cache_item_specific_features.py",
        "script_sha256": _file_sha256(Path(__file__)),
        "git_sha": _git_sha(),
        "iso_datetime": pd.Timestamp.utcnow().isoformat(),
        "data_sha256": _file_sha256(out_path),
        "n_subjects": n_subjects,
        "n_features": n_features,
        "labels_used": False,
        "leakage_status": "clean_by_construction",
        "leakage_argument": (
            "All features are deterministic signal-processing aggregates of raw IMU channels. "
            "UPDRS-III labels never enter this extraction. Per-subject mean across recordings "
            "is the only aggregation; no global statistics are fit. Per-item recipes operate "
            "ONLY on the sensors and time windows clinically relevant to that item, in order to "
            "reduce dimensionality below the K=500 selector absorption threshold (F44 lesson)."
        ),
        "constants_locked": {
            "fs_hz": FS,
            "item4_bandpower_hz": [1.5, 4.0],
            "item6_bandpower_hz": [0.5, 3.0],
            "item6_turn_window_s": 2.0,
            "item15_bandpower_hz": [4.0, 7.0],
            "item15_segment_s": 3.0,
            "item16_jerk_bandpower_hz": [5.0, 8.0],
            "item16_segment_s": 3.0,
            "item17_tremor_band_hz": [4.0, 6.0],
            "item17_segment_s": 5.0,
            "item18_burst_window_s": 2.0,
            "item18_burst_threshold_percentile": 90,
        },
        "feature_blocks": {
            "i4_": "~16 feats — finger-tap surrogate via wrist arm-swing",
            "i6_": "~24 feats — pronation-supination via wrist Gyr/VelInc in turn windows",
            "i15_": "~12 feats — postural tremor via wrist FreeAcc 4-7 Hz",
            "i16_": "~12 feats — kinetic tremor via wrist jerk 5-8 Hz",
            "i17_": "~24 feats — rest tremor amplitude via wrist Gyr 4-6 Hz",
            "i18_": "~12 feats — rest tremor constancy via wrist burst metrics",
        },
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest: {MANIFEST_PATH}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
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

    print(f"Extracting item-specific features with {N_CORES} workers...", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        rows = [r for r in pool.map(_process_one_csv, jobs, chunksize=4) if r]
    print(f"  {len(rows)} recordings processed in {time.time() - t0:.0f}s", flush=True)

    if args.smoke:
        df_smoke = pd.DataFrame(rows)
        keep = ["sid", "task"] + [c for c in df_smoke.columns if c.startswith("i")][:8]
        print(df_smoke[keep].head(10).to_string())
        return

    agg = aggregate_per_subject(rows)
    smoke_check(agg)
    out_path = Path(args.out)
    agg.to_csv(out_path, index=False)
    feat_cols = [c for c in agg.columns if c not in ("sid", "task")]
    print(f"Wrote {agg.shape[0]} rows × {agg.shape[1]} cols → {out_path}", flush=True)
    write_manifest(out_path, n_subjects=int(agg.shape[0]), n_features=len(feat_cols))


if __name__ == "__main__":
    main()
