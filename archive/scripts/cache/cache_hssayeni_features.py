"""cache_hssayeni_features.py — Wrist-IMU feature cache for the
Hssayeni MJFF Levodopa Response Trial dataset (Synapse syn20681023).

Mission (iter26): bridge cross-dataset UPDRS-III regression.
WearGait-PD predicts MDS-UPDRS Part-III from body-worn IMUs (canonical iter5
LOOCV CCC=0.5227 at N=98). iter25b cross-dataset zero-shot on PADS gave
AUROC=0.4975 (chance) — diagnosed as task-protocol mismatch (PADS records
mostly stationary upper-limb tasks; WG records gait/balance). The Hssayeni
MJFF Levodopa Response Trial Dataset is the ONLY public cohort we know of
that has BOTH wrist accelerometer recordings AND MDS-UPDRS Part-III scores,
so it is the only fair test of "does wrist+UPDRS regression work when the
task matches?"

Reference: Hssayeni et al. 2021, Symptom Severity Estimation of Parkinson's
Disease from Wrist Worn Sensor Data Using Deep Learning Methods,
Sensors 21(14):4865.

Data structure expected (per the paper; verify on DUA grant):
  - ~30 PD subjects.
  - Apple Watch + Pebble Smartwatch on the most-affected wrist.
  - 100 Hz tri-axial accelerometer.
  - Multiple motor protocols per session (Resting, Drinking, Folding,
    Sitting, Walking — VERIFY against the actual dataset README upon access).
  - UPDRS-III scored at multiple time points relative to medication intake
    (defOFF, +30, +60, +90, +120 min).

Feature schema (matches `run_t3_iter25b_pads_fixed.py`'s
`extract_wrist_block_no_gait`):
  Per signal (ax, ay, az, am=sqrt(ax²+ay²+az²)):
    Time-domain:  rms, std, range, iqr, skew, kurt, jerk, zcr   (8)
    Frequency:    loco, loco_r, trem, trem_r, high, high_r,
                  dom, se                                       (8)
  Total: 4 signals × 16 features = 64 wrist_* features per recording.
  No gait_reg (intentional — same fix as iter25b Fix B).

Unit convention (matches iter25b Fix A):
  Apple Watch / Pebble accelerometer ships in g (gravity-removed by Apple
  CoreMotion CMUserAcceleration). We multiply by 9.81 to convert to m/s²
  so feature scales match WearGait-PD's R_Wrist_FreeAcc_E/N/U
  (m/s², gravity-removed).

Output columns:
  sid, task, time_relative_to_med_min, updrs3, wrist_<...> ...

`updrs3` is the REGRESSION TARGET written into the cache for downstream
convenience. It is NOT used during feature extraction. The manifest sets
`labels_used=False` and adds `target_column="updrs3"` so downstream
lockbox scripts treat it as a fold-local label, not a feature.

Manifest sidecar:
  results/hssayeni_features.csv.manifest.json — per-cache provenance:
  script_sha256, git_sha, data_sha256, created_at_utc, labels_used=False,
  target_column="updrs3", leakage_status="clean_by_construction".

NOTE: This script is preparatory. It will not run today; the Synapse DUA is
pending. Once data lands at /root/pd-imu/data/raw/hssayeni/ this script
extracts features. Until then it fails fast with a clear error message
that points to scripts/synapse_hssayeni_setup.md.
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
import hashlib
import json
import logging
import re
import subprocess
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import signal as sp_signal, stats as sp_stats

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
LOG = logging.getLogger("cache_hssayeni")

# ── INPUT PATHS (placeholders — exact layout TBD until DUA grants access) ───
#
# After DUA grant the data is expected at HSSAYENI_DIR. Several plausible
# layouts are tolerated; the resolver below picks the first match.
#
# Layout A (per-subject, per-task subdirs):
#   {HSSAYENI_DIR}/{wrist_device}/{subject_id}/{task}/accelerometer.csv
#   e.g. /root/pd-imu/data/raw/hssayeni/AppleWatch/subj01/Walking/accelerometer.csv
#
# Layout B (flat, encoded in filename):
#   {HSSAYENI_DIR}/{wrist_device}/{subject_id}_{task}_{time_offset_min}.csv
#   e.g. /root/pd-imu/data/raw/hssayeni/AppleWatch/subj01_Walking_60.csv
#
# Layout C (Synapse-export style — entity-id directories):
#   {HSSAYENI_DIR}/{syn_id}/<filename>.{csv,txt}
#   filename encodes the (subject, task, time) tuple.
#
# Clinical scores CSV (REQUIRED): expected columns:
#   subject_id, session_id, time_relative_to_med_min, MDS-UPDRS_3_total
#   exact column names may vary; LABEL_COL_CANDIDATES below tolerates synonyms.

HSSAYENI_DIR = Path(os.environ.get("HSSAYENI_DIR", "/root/pd-imu/data/raw/hssayeni"))

# Candidate locations for the wrist accelerometer subtree.
WRIST_DEVICE_DIRS = ("AppleWatch", "apple_watch", "PebbleSmartwatch", "pebble", "wrist")

# Candidate clinical metadata locations (relative to HSSAYENI_DIR).
CLINICAL_FILE_CANDIDATES = (
    "clinical/updrs_scores.csv",
    "clinical/scores.csv",
    "updrs_scores.csv",
    "scores.csv",
    "clinical/UPDRS-III.csv",
    "clinical/MDS-UPDRS-III.csv",
)

# Tolerated column-name synonyms in the clinical metadata.
LABEL_COL_CANDIDATES = {
    "subject_id": ("subject_id", "subjectId", "subject", "sid", "id", "PatientID"),
    "session_id": ("session_id", "session", "visit", "visit_id", "VisitID"),
    "time_relative_to_med_min": (
        "time_relative_to_med_min",
        "time_min",
        "time_offset_min",
        "minutes_post_dose",
        "minutes_post_med",
        "post_med_min",
        "TimeFromDose",
        "time_from_dose_min",
    ),
    "updrs3": (
        "MDS-UPDRS_3_total",
        "MDS-UPDRS-III",
        "MDS_UPDRS_III",
        "UPDRS-III",
        "UPDRS_III",
        "UPDRS3",
        "updrs3",
        "updrs_3_total",
        "total_updrs_iii",
    ),
}

# Sampling rate per Hssayeni 2021.
FS_HSSAYENI = 100

# Apple Watch / Pebble: g → m/s² (matches iter25b Fix A).
G_TO_MS2 = 9.81

# Minimum samples per recording to compute features (matches iter25b 200-sample threshold).
MIN_SAMPLES = 200

# Default output paths.
DEFAULT_OUT = Path("results") / "hssayeni_features.csv"


# ── Feature extraction (copied from iter25b extract_wrist_block_no_gait) ────


def _safe(fn, x: np.ndarray) -> float:
    try:
        return float(fn(np.asarray(x, dtype=np.float64)))
    except Exception:
        return 0.0


def td_feats(x: np.ndarray, prefix: str, fs: int) -> dict[str, float]:
    f: dict[str, float] = {}
    f[f"{prefix}_rms"] = _safe(lambda d: np.sqrt(np.mean(d ** 2)), x)
    f[f"{prefix}_std"] = _safe(np.std, x)
    f[f"{prefix}_range"] = _safe(np.ptp, x)
    f[f"{prefix}_iqr"] = _safe(lambda d: np.percentile(d, 75) - np.percentile(d, 25), x)
    f[f"{prefix}_skew"] = _safe(lambda d: float(sp_stats.skew(d)), x)
    f[f"{prefix}_kurt"] = _safe(lambda d: float(sp_stats.kurtosis(d)), x)
    jerk = np.diff(x) * fs
    f[f"{prefix}_jerk"] = _safe(lambda d: np.sqrt(np.mean(d ** 2)), jerk)
    f[f"{prefix}_zcr"] = float(np.sum(np.diff(np.sign(x - np.mean(x))) != 0)) / max(len(x), 1)
    return f


def fd_feats(x: np.ndarray, prefix: str, fs: int) -> dict[str, float]:
    f: dict[str, float] = {}
    try:
        freqs, psd = sp_signal.welch(
            x, fs=fs, nperseg=min(256, len(x)), noverlap=min(128, len(x) // 2)
        )
        psd = psd + 1e-12
        total = np.trapz(psd, freqs) + 1e-12
        for bn, lo, hi in [("loco", 0.5, 3.0), ("trem", 3.0, 8.0), ("high", 8.0, 20.0)]:
            mask = (freqs >= lo) & (freqs <= hi)
            bp = float(np.trapz(psd[mask], freqs[mask])) if mask.sum() > 1 else 1e-12
            f[f"{prefix}_{bn}"] = float(np.log10(max(bp, 1e-12)))
            f[f"{prefix}_{bn}_r"] = float(bp / total)
        f[f"{prefix}_dom"] = float(freqs[np.argmax(psd)])
        pn = psd / psd.sum()
        f[f"{prefix}_se"] = float(-np.sum(pn * np.log2(pn + 1e-12)))
    except Exception:
        for bn in ["loco", "trem", "high"]:
            f[f"{prefix}_{bn}"] = 0.0
            f[f"{prefix}_{bn}_r"] = 0.0
        f[f"{prefix}_dom"] = 0.0
        f[f"{prefix}_se"] = 0.0
    return f


def extract_wrist_block(ax: np.ndarray, ay: np.ndarray, az: np.ndarray, fs: int) -> dict[str, float]:
    """Per-axis td/fd + magnitude td/fd. No gait_reg. Matches iter25b."""
    out: dict[str, float] = {}
    for axis_name, x in [("ax", ax), ("ay", ay), ("az", az)]:
        out.update(td_feats(x, f"wrist_{axis_name}", fs))
        out.update(fd_feats(x, f"wrist_{axis_name}", fs))
    am = np.sqrt(ax ** 2 + ay ** 2 + az ** 2)
    out.update(td_feats(am, "wrist_am", fs))
    out.update(fd_feats(am, "wrist_am", fs))
    return out


# ── Clinical metadata loading ───────────────────────────────────────────────


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map any of the synonym columns to the canonical names. Fail fast if a
    REQUIRED column is missing (subject_id, updrs3)."""
    rename: dict[str, str] = {}
    for canonical, candidates in LABEL_COL_CANDIDATES.items():
        for cand in candidates:
            if cand in df.columns:
                rename[cand] = canonical
                break
    df = df.rename(columns=rename)
    missing = [c for c in ("subject_id", "updrs3") if c not in df.columns]
    if missing:
        raise KeyError(
            f"Clinical metadata is missing required column(s) {missing!r}. "
            f"Available columns: {list(df.columns)}. "
            f"Edit LABEL_COL_CANDIDATES in cache_hssayeni_features.py to add the synonym."
        )
    if "session_id" not in df.columns:
        df["session_id"] = "session_1"
    if "time_relative_to_med_min" not in df.columns:
        df["time_relative_to_med_min"] = np.nan
    return df


def _load_clinical(hssayeni_dir: Path) -> pd.DataFrame:
    for rel in CLINICAL_FILE_CANDIDATES:
        p = hssayeni_dir / rel
        if p.is_file():
            try:
                df = pd.read_csv(p)
            except Exception as exc:
                LOG.warning("Failed to read clinical metadata %s: %s", p, exc)
                continue
            LOG.info("Loaded clinical metadata: %s (%d rows, %d cols)", p, len(df), len(df.columns))
            return _normalise_columns(df)
    # XLSX fallback.
    for rel in CLINICAL_FILE_CANDIDATES:
        p = hssayeni_dir / rel.replace(".csv", ".xlsx")
        if p.is_file():
            try:
                df = pd.read_excel(p)
            except Exception as exc:
                LOG.warning("Failed to read clinical xlsx %s: %s", p, exc)
                continue
            LOG.info("Loaded clinical xlsx: %s (%d rows, %d cols)", p, len(df), len(df.columns))
            return _normalise_columns(df)
    raise FileNotFoundError(
        f"No clinical UPDRS-III metadata found under {hssayeni_dir}. "
        f"Tried: {CLINICAL_FILE_CANDIDATES}. "
        f"See scripts/synapse_hssayeni_setup.md Step 5+6 for the expected file."
    )


# ── Recording discovery ─────────────────────────────────────────────────────


def _resolve_wrist_root(hssayeni_dir: Path) -> Path:
    for cand in WRIST_DEVICE_DIRS:
        p = hssayeni_dir / cand
        if p.is_dir():
            LOG.info("Wrist accelerometer root: %s", p)
            return p
    # Fallback: Hssayeni dir itself contains CSVs at top level.
    if any(hssayeni_dir.glob("*.csv")) or any(hssayeni_dir.glob("*.txt")):
        LOG.info("Wrist accelerometer root: %s (flat top-level)", hssayeni_dir)
        return hssayeni_dir
    raise FileNotFoundError(
        f"Could not locate a wrist accelerometer subdirectory under {hssayeni_dir}. "
        f"Tried: {WRIST_DEVICE_DIRS}. Synapse: syn20681023. "
        f"See scripts/synapse_hssayeni_setup.md."
    )


_FNAME_PATTERN = re.compile(
    r"(?P<sid>[A-Za-z0-9_-]+?)_(?P<task>[A-Za-z]+)(?:_(?P<tmin>-?\d+))?",
    re.IGNORECASE,
)


def _parse_recording_meta(path: Path, wrist_root: Path) -> Optional[dict[str, str]]:
    """Recover (sid, task, time_relative_to_med_min) from the file path.

    Tries Layout A (.../<sid>/<task>/<file>) first, then Layout B (flat name
    encoding). Returns None if it can't decide — caller logs and skips."""
    rel = path.relative_to(wrist_root)
    parts = rel.parts
    # Layout A: sid/task/file.
    if len(parts) >= 3:
        sid = parts[0]
        task = parts[1]
        return {"sid": str(sid), "task": str(task), "tmin_from_path": ""}
    # Layout B: encoded in filename stem.
    stem = path.stem
    m = _FNAME_PATTERN.match(stem)
    if m:
        sid = m.group("sid")
        task = m.group("task")
        tmin = m.group("tmin") or ""
        return {"sid": str(sid), "task": str(task), "tmin_from_path": tmin}
    return None


def _read_acc_csv(path: Path) -> Optional[np.ndarray]:
    """Read a 3-axis accelerometer file. Tolerates CSV with header, CSV without
    header, and TXT (whitespace-delimited). Returns Nx3 float array or None."""
    try:
        df = pd.read_csv(path)
    except Exception:
        df = None
    if df is None or df.shape[1] < 3:
        try:
            arr = np.loadtxt(path, delimiter=",", dtype=np.float64)
        except Exception:
            try:
                arr = np.loadtxt(path, dtype=np.float64)
            except Exception:
                return None
        if arr.ndim != 2 or arr.shape[1] < 3:
            return None
        return arr[:, :3].astype(np.float32)
    # Pick the 3 most-likely accelerometer columns.
    candidates = [
        ("Accelerometer_X", "Accelerometer_Y", "Accelerometer_Z"),
        ("acc_x", "acc_y", "acc_z"),
        ("AccX", "AccY", "AccZ"),
        ("ax", "ay", "az"),
        ("x", "y", "z"),
    ]
    for cx, cy, cz in candidates:
        if cx in df.columns and cy in df.columns and cz in df.columns:
            arr = df[[cx, cy, cz]].to_numpy(dtype=np.float32)
            return arr
    # Fallback: first 3 numeric columns.
    num = df.select_dtypes(include=[np.number])
    if num.shape[1] >= 3:
        return num.iloc[:, :3].to_numpy(dtype=np.float32)
    return None


def _gravity_removed_check(arr_g: np.ndarray) -> bool:
    """Apple Watch CMUserAcceleration is gravity-removed; mean magnitude in g
    should be << 1.0. CMAcceleration includes gravity (mean ≈ 1 g)."""
    mag = np.sqrt(np.sum(arr_g.astype(np.float64) ** 2, axis=1))
    mean_mag_g = float(np.mean(mag))
    return mean_mag_g < 0.5


# ── Main extraction ─────────────────────────────────────────────────────────


def _ensure_data_or_fail(hssayeni_dir: Path) -> None:
    if not hssayeni_dir.exists():
        raise FileNotFoundError(
            f"Hssayeni data not found at {hssayeni_dir}. "
            f"See scripts/synapse_hssayeni_setup.md for DUA + download instructions. "
            f"Synapse: syn20681023."
        )


def _resolve_label(
    clinical: pd.DataFrame, sid: str, task: str, tmin_from_path: str
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Find UPDRS-III row matching this recording. Returns (updrs3, time_min, session_id).

    Strategy: fuzzy match on subject_id, then time_relative_to_med_min (numeric
    parse from path if present), then collapse session_id."""
    subset = clinical[clinical["subject_id"].astype(str).str.lower() == str(sid).lower()]
    if subset.empty:
        return None, None, None
    if tmin_from_path:
        try:
            t_target = float(tmin_from_path)
            if subset["time_relative_to_med_min"].notna().any():
                subset["_dist"] = (subset["time_relative_to_med_min"].astype(float) - t_target).abs()
                row = subset.sort_values("_dist").iloc[0]
                return (
                    float(row["updrs3"]) if not pd.isna(row["updrs3"]) else None,
                    float(row["time_relative_to_med_min"])
                    if not pd.isna(row["time_relative_to_med_min"])
                    else None,
                    str(row.get("session_id", "")),
                )
        except ValueError:
            pass
    row = subset.iloc[0]
    return (
        float(row["updrs3"]) if not pd.isna(row["updrs3"]) else None,
        float(row["time_relative_to_med_min"])
        if not pd.isna(row["time_relative_to_med_min"])
        else None,
        str(row.get("session_id", "")),
    )


def extract_all(hssayeni_dir: Path) -> tuple[pd.DataFrame, dict]:
    _ensure_data_or_fail(hssayeni_dir)
    clinical = _load_clinical(hssayeni_dir)
    wrist_root = _resolve_wrist_root(hssayeni_dir)

    rec_paths: list[Path] = []
    for ext in ("*.csv", "*.txt"):
        rec_paths.extend(sorted(wrist_root.rglob(ext)))
    if not rec_paths:
        raise FileNotFoundError(
            f"No accelerometer CSV/TXT files found under {wrist_root}. "
            f"See scripts/synapse_hssayeni_setup.md Step 6."
        )
    LOG.info("Discovered %d candidate recording files under %s", len(rec_paths), wrist_root)

    rows: list[dict] = []
    skipped_no_meta = 0
    skipped_short = 0
    skipped_unreadable = 0
    skipped_no_label = 0
    gravity_check_done = False
    gravity_warning_emitted = False
    missing_subjects: set[str] = set()
    missing_tasks: dict[str, set[str]] = {}

    for path in rec_paths:
        meta = _parse_recording_meta(path, wrist_root)
        if meta is None:
            skipped_no_meta += 1
            continue
        arr_g = _read_acc_csv(path)
        if arr_g is None or arr_g.shape[0] < MIN_SAMPLES:
            skipped_short += 1 if (arr_g is not None) else 0
            skipped_unreadable += 1 if (arr_g is None) else 0
            continue
        if not gravity_check_done:
            ok = _gravity_removed_check(arr_g)
            gravity_check_done = True
            if not ok and not gravity_warning_emitted:
                gravity_warning_emitted = True
                LOG.warning(
                    "First recording mean acc magnitude in g >= 0.5: data may be gravity-INCLUDED. "
                    "Hssayeni paper expects CMUserAcceleration (gravity-removed). "
                    "Continuing with ×9.81 conversion; verify per-recording before publishing."
                )

        ax = arr_g[:, 0] * G_TO_MS2
        ay = arr_g[:, 1] * G_TO_MS2
        az = arr_g[:, 2] * G_TO_MS2

        feats = extract_wrist_block(ax, ay, az, FS_HSSAYENI)
        sid = meta["sid"]
        task = meta["task"]
        updrs3, t_min, sess = _resolve_label(clinical, sid, task, meta["tmin_from_path"])
        if updrs3 is None:
            skipped_no_label += 1
            missing_subjects.add(sid)
            missing_tasks.setdefault(sid, set()).add(task)
            continue
        feats["sid"] = sid
        feats["task"] = task
        feats["session_id"] = sess or ""
        feats["time_relative_to_med_min"] = (
            float(t_min) if t_min is not None else float("nan")
        )
        feats["updrs3"] = float(updrs3)
        rows.append(feats)

    if not rows:
        raise RuntimeError(
            "No Hssayeni recordings could be matched to UPDRS-III scores. "
            f"skipped: no_meta={skipped_no_meta}, short={skipped_short}, "
            f"unreadable={skipped_unreadable}, no_label={skipped_no_label}. "
            "Check scripts/synapse_hssayeni_setup.md Step 9 (sanity-check)."
        )

    df = pd.DataFrame(rows)
    feat_cols = [c for c in df.columns if c.startswith("wrist_")]
    meta_cols = ["sid", "task", "session_id", "time_relative_to_med_min", "updrs3"]
    df = df[meta_cols + sorted(feat_cols)]

    summary = {
        "n_subjects": int(df["sid"].nunique()),
        "n_recordings": int(len(df)),
        "tasks": sorted(df["task"].dropna().unique().tolist()),
        "skipped_no_meta": skipped_no_meta,
        "skipped_short_or_unreadable": skipped_short + skipped_unreadable,
        "skipped_no_label": skipped_no_label,
        "missing_label_subjects": sorted(missing_subjects),
        "updrs3_min": float(df["updrs3"].min()),
        "updrs3_max": float(df["updrs3"].max()),
        "updrs3_mean": float(df["updrs3"].mean()),
        "updrs3_std": float(df["updrs3"].std()),
    }
    return df, summary


# ── Manifest ────────────────────────────────────────────────────────────────


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
        ).decode().strip()
    except Exception:
        return "unknown"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(out_path: Path, summary: dict) -> None:
    script_path = Path(__file__).resolve()
    manifest = {
        "name": out_path.name,
        "script": script_path.name,
        "script_sha256": _file_sha256(script_path),
        "git_sha": _git_sha(),
        "command": " ".join(sys.argv),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "data_sha256": _file_sha256(out_path),
        "n_rows": int(summary["n_recordings"]),
        "n_subjects": int(summary["n_subjects"]),
        "tasks": summary["tasks"],
        "feature_schema": (
            "extract_wrist_block (matches run_t3_iter25b_pads_fixed.py): "
            "per signal {ax, ay, az, am} → time-domain "
            "{rms, std, range, iqr, skew, kurt, jerk, zcr} ⊕ "
            "frequency {loco, loco_r, trem, trem_r, high, high_r, dom, se}. "
            "4 signals × 16 features = 64 wrist_* features. No gait_reg."
        ),
        "sampling_rate_hz": int(FS_HSSAYENI),
        "unit_conversion": "Apple Watch / Pebble g → m/s² via ×9.81 (matches WG FreeAcc convention).",
        "labels_used": False,
        "label_columns": [],
        "target_column": "updrs3",
        "fold_scope": "external",
        "cohort_statistics_used": False,
        "normalization_scope": (
            "none at cache layer; downstream lockboxes apply fold-local normalization "
            "via inductive_lib.FoldNormalizer."
        ),
        "constants_used": [
            {"name": "FS_HSSAYENI", "value": FS_HSSAYENI},
            {"name": "G_TO_MS2", "value": G_TO_MS2},
            {"name": "MIN_SAMPLES", "value": MIN_SAMPLES},
        ],
        "source_artifacts": [
            {
                "path": str(HSSAYENI_DIR),
                "scope": (
                    "Hssayeni MJFF Levodopa Response Trial Dataset, Synapse syn20681023; "
                    "wrist accelerometer (Apple Watch / Pebble) + UPDRS-III clinical scores."
                ),
            },
        ],
        "leakage_status": "clean_by_construction",
        "leakage_rationale": (
            "All wrist_* features are signal-processing aggregates of the raw 3-axis "
            "accelerometer (time-domain moments + Welch-PSD band powers + spectral entropy). "
            "No UPDRS scoring information is consumed during feature extraction — UPDRS-III "
            "appears in the cache only as the regression target column (`updrs3`). Downstream "
            "lockbox scripts must treat `updrs3` as a label and apply fold-local handling per "
            "inductive_lib.py. Cache layer reports `labels_used=False` because the features "
            "themselves do not consume labels; `target_column='updrs3'` is the explicit "
            "downstream contract."
        ),
        "downstream_safe_for": ["screening", "lockbox_features"],
        "downstream_unsafe_for": [],
        "summary": summary,
        "audit_added_at_utc": datetime.utcnow().isoformat() + "Z",
        "audit_note": (
            "Manifest written by cache_hssayeni_features.py; verified leakage-clean by "
            "construction. UPDRS-III is the target, not a feature."
        ),
    }
    manifest_path = out_path.with_suffix(out_path.suffix + ".manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    LOG.info("Wrote manifest %s", manifest_path)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--hssayeni_dir",
        type=Path,
        default=HSSAYENI_DIR,
        help=f"Path to the Hssayeni dataset root (default: {HSSAYENI_DIR}).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output CSV path (default: {DEFAULT_OUT}).",
    )
    args = parser.parse_args()

    out_path: Path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    LOG.info("Hssayeni cache start. dir=%s, out=%s", args.hssayeni_dir, out_path)
    df, summary = extract_all(args.hssayeni_dir)
    df.to_csv(out_path, index=False)
    LOG.info("Wrote %s (%d rows, %d cols)", out_path, df.shape[0], df.shape[1])

    LOG.info(
        "Summary: n_subjects=%d, n_recordings=%d, tasks=%s",
        summary["n_subjects"],
        summary["n_recordings"],
        summary["tasks"],
    )
    LOG.info(
        "UPDRS-III: min=%.1f, mean=%.2f, max=%.1f, std=%.2f",
        summary["updrs3_min"],
        summary["updrs3_mean"],
        summary["updrs3_max"],
        summary["updrs3_std"],
    )
    if summary["missing_label_subjects"]:
        LOG.warning(
            "%d subject(s) had recordings with no UPDRS-III match: %s",
            len(summary["missing_label_subjects"]),
            summary["missing_label_subjects"][:10],
        )

    write_manifest(out_path, summary)


if __name__ == "__main__":
    main()
