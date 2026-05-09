#!/usr/bin/env python3
"""T3 iter53 — Parkinson@Home external zero-shot validation.

Parkinson@Home / Radboud DOI 10.34973/fr4z-a489 is a public wrist-IMU
dataset with OFF/ON MDS-UPDRS Part III subitems. This script treats it as
external transportability evidence only. Results cannot update the internal
WearGait-PD T3 canonical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import signal as sp_signal
from scipy import stats as sp_stats
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

from inductive_lib import FoldImputer, FoldNormalizer, cal_slope, ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import DATA_DIR, REPO_ROOT, RESULTS_DIR, ensure_dir
from run_t3_iter2 import train_lgb
from run_t3_iter47_invalid_code_fix import filter_cohort


BASE_URL = "https://webdav.data.ru.nl/dcmn/DSC_pdhasq_t0000123a_971_v1"
DATASET_DOI = "10.34973/fr4z-a489"
PAH_DIR = REPO_ROOT / "data" / "raw" / "parkinsonathome"
PREPARED_DIR = PAH_DIR / "preprocessed_data" / "0.prepared_data"
FEATURE_CSV = RESULTS_DIR / "iter53_parkinsonathome_features.csv"
STABLE_PREREG = RESULTS_DIR / "preregistration_t3_iter53_parkinsonathome_zeroshot.json"
STABLE_RESULT = RESULTS_DIR / "iter53_parkinsonathome_zeroshot.json"
SEEDS = (42, 1337, 7)
WEARGAIT_TASKS = ("TUG", "SelfPace", "HurriedPace")
FS_FEATURE = 20
WINDOW_SECONDS = 30
MIN_SECONDS = 5
G_TO_MPS2 = 9.80665
CLEAN_ARM_LABEL = "Gait without other behaviours or other positions"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        return "unknown"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return jsonable(obj.tolist())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def url_for(rel: str) -> str:
    return f"{BASE_URL}/{rel.lstrip('/')}"


def download(rel: str, out: Path, force: bool = False) -> Path:
    ensure_dir(out.parent)
    if force or not out.exists():
        print(f"Downloading {rel} -> {out}", flush=True)
        urllib.request.urlretrieve(url_for(rel), out)
    return out


def formula() -> dict[str, Any]:
    return {
        "experiment": "T3 iter53 Parkinson@Home external zero-shot validation",
        "dataset": {
            "name": "Parkinson@Home IMU sensor data and video annotations for arm swing quantification in free-living gait",
            "doi": DATASET_DOI,
            "landing_page": "https://doi.org/10.34973/fr4z-a489",
            "distribution": BASE_URL,
            "license": "Repository states CC0/open access plus data-use conditions in LICENSE.txt",
            "cohort": "25 PD with motor fluctuations and 25 controls; PD recorded OFF and ON medication",
            "sensor": "bilateral wrist accelerometer and gyroscope at 200 Hz",
            "labels": "OFF/ON MDS-UPDRS Part III subitems in patient_info.csv",
        },
        "current_internal_anchor": {
            "script": "run_t3_iter47_invalid_code_fix.py --mode run",
            "cohort": "drop_allmissing_validrange",
            "loocv_ccc": 0.3784,
            "loocv_mae": 7.528,
            "n": 95,
        },
        "fixed_battery": {
            "primary_external_rows": "PD subjects with valid OFF Part III target and readable right-wrist prepared parquet",
            "primary_target": "OFF MDS-UPDRS Part III valid-range total",
            "feature_schema": (
                "frame-invariant right-wrist acceleration-magnitude summaries from clean gait-without-other-arm-activity "
                "segments in Parkinson@Home; WearGait uses right-wrist acceleration magnitude across TUG, SelfPace, and HurriedPace"
            ),
            "tracks": {
                "A_zero_shot_wrist_direct": {
                    "train": "WearGait-PD corrected valid-range T3 only",
                    "test": "Parkinson@Home OFF right-wrist clean-gait features",
                    "labels_used_for_training": False,
                    "claim": "WearGait-to-Parkinson@Home wrist transportability",
                },
                "B_clinical_plus_wrist": {
                    "status": "skip_if_public_clinical_covariates_absent",
                    "reason": "The public patient_info.csv exposed in the probe contains UPDRS subitems but no H&Y/disease-duration/sex/DBS covariates.",
                },
                "C_parkinsonathome_loocv_sanity": {
                    "train": "Parkinson@Home train folds only",
                    "test": "held-out Parkinson@Home subjects",
                    "labels_used_for_training": True,
                    "claim": "within-Parkinson@Home feasibility sanity, not transportability",
                },
                "D_off_on_response_sensitivity": {
                    "train": "same WearGait model as Track A",
                    "test": "Parkinson@Home paired OFF and ON features",
                    "labels_used_for_training": False,
                    "claim": "medication-response observability sensitivity only",
                },
            },
            "hard_stops": [
                "patient_info.csv must expose all OFF_UPDRS_3_* subitems needed for valid-range T3.",
                "At least 20 PD OFF subjects must remain after valid-target and feature-readability filtering.",
                "Prepared parquet reading must work with pyarrow or fastparquet on the execution host.",
                "External accelerometry scale must be classifiable as g or m/s^2 from magnitude distribution.",
                "No Parkinson@Home labels enter WearGait-trained Tracks A/D.",
            ],
        },
        "policy": {
            "internal_t3_canonical_update_allowed": False,
            "internal_t1_canonical_update_allowed": False,
            "ceiling_break_framing_allowed": False,
            "interpretation": "external transportability / protocol-mismatch evidence only",
        },
    }


def verify_preregistration() -> dict[str, Any]:
    expected = canonical_sha(formula())
    if not STABLE_PREREG.exists():
        raise FileNotFoundError(f"Missing {STABLE_PREREG}; run --mode write-prereg first")
    payload = json.loads(STABLE_PREREG.read_text(encoding="utf-8"))
    if payload.get("formula_sha256") != expected:
        raise RuntimeError(f"Preregistration SHA mismatch: {payload.get('formula_sha256')} != {expected}")
    return payload


def write_preregistration() -> Path:
    ensure_dir(RESULTS_DIR)
    f = formula()
    payload = {
        **f,
        "created_at_utc": now_utc(),
        "git_sha": git_sha(),
        "formula_sha256": canonical_sha(f),
    }
    STABLE_PREREG.write_text(json.dumps(jsonable(payload), indent=2) + "\n", encoding="utf-8")
    md = STABLE_PREREG.with_suffix(".md")
    md.write_text(
        "# T3 iter53 Parkinson@Home Preregistration\n\n"
        f"- Formula SHA256: `{payload['formula_sha256']}`\n"
        "- Primary claim: external zero-shot transportability only.\n"
        "- Internal WearGait-PD T3 canonical update: forbidden under all outcomes.\n"
        "- Track B is skipped unless public non-target clinical covariates are present.\n",
        encoding="utf-8",
    )
    print(f"Wrote {STABLE_PREREG}\nWrote {md}", flush=True)
    return STABLE_PREREG


def ensure_metadata(force: bool = False) -> dict[str, Path]:
    paths = {
        "patient_info": PAH_DIR / "input" / "clinical_data" / "patient_info.csv",
        "distribution": PAH_DIR / "input" / "clinical_data" / "distribution_participants.json",
        "readme": PAH_DIR / "README.md",
        "about": PAH_DIR / "ABOUT.txt",
        "manifest": PAH_DIR / "MANIFEST.txt",
        "license": PAH_DIR / "LICENSE.txt",
    }
    rels = {
        "patient_info": "input/clinical_data/patient_info.csv",
        "distribution": "input/clinical_data/distribution_participants.json",
        "readme": "README.md",
        "about": "ABOUT.txt",
        "manifest": "MANIFEST.txt",
        "license": "LICENSE.txt",
    }
    for key, rel in rels.items():
        download(rel, paths[key], force=force)
    return paths


def load_patient_info() -> pd.DataFrame:
    path = ensure_metadata(force=False)["patient_info"]
    return pd.read_csv(path, sep=";")


def part3_cols(df: pd.DataFrame, prefix: str) -> list[str]:
    cols = [c for c in df.columns if c.startswith(prefix)]
    if len(cols) != 33:
        raise RuntimeError(f"Expected 33 columns for {prefix}, found {len(cols)}")
    return cols


def validrange_sum(df: pd.DataFrame, cols: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    vals = df[cols].apply(pd.to_numeric, errors="coerce")
    invalid = (vals < 0) | (vals > 4)
    clean = vals.mask(invalid)
    return (
        clean.sum(axis=1, skipna=True).to_numpy(dtype=float),
        clean.notna().sum(axis=1).to_numpy(dtype=int),
        invalid.sum(axis=1).to_numpy(dtype=int),
    )


def clinical_targets() -> pd.DataFrame:
    df = load_patient_info().copy()
    off_cols = part3_cols(df, "OFF_UPDRS_3_")
    on_cols = part3_cols(df, "ON_UPDRS_3_")
    df["off_updrs3"], df["off_valid_subitems"], df["off_invalid_subitems"] = validrange_sum(df, off_cols)
    df["on_updrs3"], df["on_valid_subitems"], df["on_invalid_subitems"] = validrange_sum(df, on_cols)
    df["is_pd_primary"] = df["off_valid_subitems"] > 0
    return df


def load_distribution() -> dict[str, Any]:
    path = ensure_metadata(force=False)["distribution"]
    return json.loads(path.read_text(encoding="utf-8"))


def side_label_for_right(sid: str, distribution: dict[str, Any]) -> str | None:
    most_right = set(distribution.get("most_affected", {}).get("right", []))
    least_right = set(distribution.get("least_affected", {}).get("right", []))
    if sid in most_right:
        return "MAS"
    if sid in least_right:
        return "LAS"
    return None


def safe_stat(fn, x: np.ndarray) -> float:
    try:
        val = float(fn(np.asarray(x, dtype=np.float64)))
        return val if np.isfinite(val) else 0.0
    except Exception:
        return 0.0


def segment_time_features(x: np.ndarray, fs: int = FS_FEATURE) -> dict[str, float]:
    x = np.nan_to_num(np.asarray(x, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    if len(x) < fs * MIN_SECONDS:
        return {}
    seg_len = int(WINDOW_SECONDS * fs)
    if len(x) < seg_len:
        raise ValueError(
            f"insufficient samples for one {WINDOW_SECONDS}s window after downsampling: {len(x)} < {seg_len}"
        )
    n_seg = max(1, len(x) // seg_len)
    segs = x[: n_seg * seg_len].reshape(n_seg, seg_len)
    q = np.percentile(segs, [25, 50, 75], axis=1)
    diffs = np.diff(segs, axis=1) * fs
    centered = segs - segs.mean(axis=1, keepdims=True)
    base = {
        "mean": segs.mean(axis=1),
        "std": segs.std(axis=1),
        "rms": np.sqrt(np.mean(segs * segs, axis=1)),
        "iqr": q[2] - q[0],
        "p50": q[1],
        "range": np.ptp(segs, axis=1),
        "jerk_rms": np.sqrt(np.mean(diffs * diffs, axis=1)) if diffs.shape[1] else np.zeros(len(segs)),
        "zcr": np.mean(np.diff(np.signbit(centered), axis=1), axis=1) if centered.shape[1] > 1 else np.zeros(len(segs)),
    }
    out: dict[str, float] = {"n_windows": float(len(segs))}
    for name, vals in base.items():
        vals = np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)
        out[f"mag_win_{name}_mean"] = float(np.mean(vals))
        out[f"mag_win_{name}_std"] = float(np.std(vals))
    return out


def spectral_features(x: np.ndarray, fs: int = FS_FEATURE) -> dict[str, float]:
    x = np.nan_to_num(np.asarray(x, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    if len(x) < fs * MIN_SECONDS:
        return {}
    nperseg = min(2048, len(x))
    freqs, psd = sp_signal.welch(x, fs=fs, nperseg=nperseg, noverlap=nperseg // 2)
    psd = np.nan_to_num(psd, nan=0.0, posinf=0.0, neginf=0.0) + 1e-12
    total = float(np.trapezoid(psd, freqs) + 1e-12)
    out = {
        "mag_chunk_skew": safe_stat(sp_stats.skew, x),
        "mag_chunk_kurt": safe_stat(sp_stats.kurtosis, x),
        "mag_spec_dom_freq": float(freqs[int(np.argmax(psd))]),
    }
    pn = psd / np.sum(psd)
    out["mag_spec_entropy"] = float(-np.sum(pn * np.log2(pn + 1e-12)))
    for name, lo, hi in [("loco", 0.5, 3.0), ("trem", 3.0, 8.0), ("high", 8.0, 20.0)]:
        mask = (freqs >= lo) & (freqs <= hi)
        bp = float(np.trapezoid(psd[mask], freqs[mask])) if int(mask.sum()) > 1 else 1e-12
        out[f"mag_spec_{name}_logp"] = float(np.log10(max(bp, 1e-12)))
        out[f"mag_spec_{name}_ratio"] = float(bp / total)
    return out


def chunk_features_from_mag(mag_mps2: np.ndarray, native_fs: int) -> dict[str, float]:
    mag = np.asarray(mag_mps2, dtype=np.float64)
    stride = max(1, int(round(native_fs / FS_FEATURE)))
    mag = mag[::stride]
    out = segment_time_features(mag, FS_FEATURE)
    out.update(spectral_features(mag, FS_FEATURE))
    return out


def aggregate_feature_dicts(chunks: list[dict[str, float]]) -> dict[str, float]:
    if not chunks:
        return {}
    keys = sorted(k for k in {key for d in chunks for key in d} if k != "n_windows")
    out: dict[str, float] = {
        "meta_n_chunks": float(len(chunks)),
        "meta_n_windows": float(np.nansum([d.get("n_windows", 0.0) for d in chunks])),
    }
    for key in keys:
        vals = np.asarray([d.get(key, np.nan) for d in chunks], dtype=np.float64)
        vals = vals[np.isfinite(vals)]
        out[f"{key}_mean"] = float(np.mean(vals)) if len(vals) else 0.0
        out[f"{key}_std"] = float(np.std(vals)) if len(vals) else 0.0
    return out


def classify_acc_scale(arr: np.ndarray) -> tuple[np.ndarray, dict[str, float | str]]:
    mag = np.sqrt(np.sum(arr * arr, axis=1))
    med = float(np.nanmedian(mag))
    mean = float(np.nanmean(mag))
    if 0.5 <= med <= 2.0:
        return arr * G_TO_MPS2, {"unit": "g_converted_to_mps2", "median_raw_mag": med, "mean_raw_mag": mean}
    if 5.0 <= med <= 15.0:
        return arr, {"unit": "mps2_native", "median_raw_mag": med, "mean_raw_mag": mean}
    raise RuntimeError(f"Cannot classify accelerometry scale, median magnitude={med:.4f}")


def weargait_right_wrist_features(sids: np.ndarray) -> pd.DataFrame:
    pd_dir = DATA_DIR / "PD PARTICIPANTS" / "CSV files"
    cols = ["R_Wrist_Acc_X", "R_Wrist_Acc_Y", "R_Wrist_Acc_Z"]
    rows: list[dict[str, Any]] = []
    for sid in sids:
        chunks: list[dict[str, float]] = []
        raw_mags = []
        for task in WEARGAIT_TASKS:
            path = pd_dir / f"{sid}_{task}.csv"
            if not path.exists():
                continue
            try:
                df = pd.read_csv(path, usecols=cols)
            except Exception:
                continue
            if len(df) < 100 * MIN_SECONDS:
                continue
            arr = df[cols].to_numpy(dtype=np.float64)
            mag = np.sqrt(np.sum(arr * arr, axis=1))
            raw_mags.append(float(np.nanmean(mag)))
            feats = chunk_features_from_mag(mag, native_fs=100)
            if feats:
                chunks.append(feats)
        row = aggregate_feature_dicts(chunks)
        if row:
            row["sid"] = str(sid)
            row["raw_mag_mean_mps2"] = float(np.nanmean(raw_mags)) if raw_mags else np.nan
            rows.append(row)
    if not rows:
        raise RuntimeError(f"No WearGait right-wrist features extracted from {pd_dir}")
    return pd.DataFrame(rows)


def prepared_rel_path(sid: str, side_label: str) -> str:
    return f"preprocessed_data/0.prepared_data/{sid}_{side_label}.parquet"


def prepared_local_path(sid: str, side_label: str) -> Path:
    return PREPARED_DIR / f"{sid}_{side_label}.parquet"


def read_prepared_parquet(path: Path) -> pd.DataFrame:
    try:
        return pd.read_parquet(
            path,
            columns=[
                "accelerometer_x",
                "accelerometer_y",
                "accelerometer_z",
                "free_living_label",
                "arm_label",
                "pre_or_post",
            ],
        )
    except ImportError as exc:
        raise RuntimeError("Reading Parkinson@Home parquet requires pyarrow or fastparquet") from exc


def parkinsonathome_subject_features(sid: str, side_label: str, force: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    local = prepared_local_path(sid, side_label)
    download(prepared_rel_path(sid, side_label), local, force=force)
    df = read_prepared_parquet(local)
    rows = []
    meta = {
        "sid": sid,
        "side_label": side_label,
        "path": str(local),
        "size_bytes": int(local.stat().st_size),
        "sha256": sha256_file(local),
        "states": {},
    }
    for state in ["pre", "post"]:
        sub = df[df["pre_or_post"].astype(str).str.lower() == state].copy()
        clean = sub[sub["arm_label"].astype(str) == CLEAN_ARM_LABEL].copy()
        fallback_used = False
        if len(clean) < 200 * MIN_SECONDS:
            walk = sub[sub["free_living_label"].astype(str).str.contains("Walking", case=False, na=False)].copy()
            if len(walk) >= 200 * MIN_SECONDS:
                clean = walk
                fallback_used = True
        state_meta: dict[str, Any] = {
            "rows_total_state": int(len(sub)),
            "rows_clean_gait": int(len(clean)),
            "fallback_walking_label_used": bool(fallback_used),
        }
        if len(clean) < 200 * MIN_SECONDS:
            state_meta["status"] = "too_few_clean_gait_rows"
            meta["states"][state] = state_meta
            continue
        acc_raw = clean[["accelerometer_x", "accelerometer_y", "accelerometer_z"]].to_numpy(dtype=np.float64)
        acc, scale = classify_acc_scale(acc_raw)
        mag = np.sqrt(np.sum(acc * acc, axis=1))
        feats = aggregate_feature_dicts([chunk_features_from_mag(mag, native_fs=200)])
        if not feats:
            state_meta["status"] = "feature_extraction_empty"
            meta["states"][state] = state_meta
            continue
        row: dict[str, Any] = {
            "sid": sid,
            "state": state,
            "side_label": side_label,
            "rows_used": int(len(clean)),
            "raw_mag_mean_mps2": float(np.mean(mag)),
            **scale,
            **feats,
        }
        rows.append(row)
        state_meta.update({"status": "ok", **scale, "mag_mean_mps2": float(np.mean(mag))})
        meta["states"][state] = state_meta
    return rows, meta


def extract_features(force: bool = False) -> Path:
    verify_preregistration()
    targets = clinical_targets()
    dist = load_distribution()
    pd_rows = targets[targets["is_pd_primary"]].copy()
    rows = []
    file_meta = []
    skipped = []
    for rec in pd_rows.itertuples(index=False):
        sid = str(rec.record_id)
        side_label = side_label_for_right(sid, dist)
        if side_label is None:
            skipped.append({"sid": sid, "reason": "right_wrist_side_not_found_in_distribution"})
            continue
        try:
            subj_rows, meta = parkinsonathome_subject_features(sid, side_label, force=force)
        except Exception as exc:
            skipped.append({"sid": sid, "reason": str(exc), "side_label": side_label})
            continue
        for row in subj_rows:
            row["off_updrs3"] = float(rec.off_updrs3)
            row["on_updrs3"] = float(rec.on_updrs3) if np.isfinite(rec.on_updrs3) else np.nan
            row["off_valid_subitems"] = int(rec.off_valid_subitems)
            row["on_valid_subitems"] = int(rec.on_valid_subitems)
            row["off_invalid_subitems"] = int(rec.off_invalid_subitems)
            row["on_invalid_subitems"] = int(rec.on_invalid_subitems)
            row["target_updrs3"] = row["off_updrs3"] if row["state"] == "pre" else row["on_updrs3"]
            rows.append(row)
        file_meta.append(meta)
        print(f"[extract] {sid} {side_label}: retained states {[r['state'] for r in subj_rows]}", flush=True)
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No Parkinson@Home features extracted")
    df.to_csv(FEATURE_CSV, index=False)
    pre_df = df[(df["state"] == "pre") & pd.to_numeric(df["target_updrs3"], errors="coerce").notna()]
    manifest = {
        "created_at_utc": now_utc(),
        "script": Path(__file__).name,
        "mode": "extract",
        "formula_sha256": canonical_sha(formula()),
        "feature_csv": str(FEATURE_CSV),
        "feature_csv_sha256": sha256_file(FEATURE_CSV),
        "n_rows": int(len(df)),
        "n_subjects": int(df["sid"].nunique()),
        "n_pre_valid_target_subjects": int(pre_df["sid"].nunique()),
        "file_meta": file_meta,
        "skipped": skipped,
        "labels_used": "External labels used only for scoring and Track C within-Parkinson@Home LOOCV sanity.",
        "fold_scope": "Tracks A/D train on WearGait only; Track C uses Parkinson@Home LOOCV.",
        "normalization_scope": "WearGait train-only for Tracks A/D; Parkinson@Home fold-train-only for Track C.",
        "leakage_status": "external_dataset_feature_cache_not_for_internal_headline",
    }
    Path(str(FEATURE_CSV) + ".manifest.json").write_text(
        json.dumps(jsonable(manifest), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {FEATURE_CSV}", flush=True)
    return FEATURE_CSV


def metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    mask = np.isfinite(y) & np.isfinite(pred)
    yy = y[mask]
    pp = pred[mask]
    return {
        "n": int(len(yy)),
        "ccc": float(ccc_fn(yy, pp)),
        "mae": float(mae_fn(yy, pp)),
        "r": float(pearson_r(yy, pp)),
        "cal_slope": float(cal_slope(yy, pp)),
        "y_mean": float(np.mean(yy)),
        "pred_mean": float(np.mean(pp)),
        "y_sd": float(np.std(yy)),
        "pred_sd": float(np.std(pp)),
    }


def ccc_ci(y: np.ndarray, pred: np.ndarray, n_boot: int = 5000, seed: int = 20260509) -> dict[str, float]:
    rng = np.random.RandomState(seed)
    mask = np.isfinite(y) & np.isfinite(pred)
    yy = y[mask]
    pp = pred[mask]
    vals = []
    n = len(yy)
    for _ in range(n_boot):
        idx = rng.randint(0, n, size=n)
        vals.append(float(ccc_fn(yy[idx], pp[idx])))
    arr = np.asarray(vals, dtype=np.float64)
    return {
        "mean": float(np.mean(arr)),
        "ci95_low": float(np.percentile(arr, 2.5)),
        "ci95_high": float(np.percentile(arr, 97.5)),
    }


def transform_train_external(X_train: np.ndarray, X_ext: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    imp = FoldImputer.fit(X_train)
    Xtr = imp.transform(X_train)
    Xte = imp.transform(X_ext)
    norm = FoldNormalizer.fit(Xtr)
    return norm.transform(Xtr), norm.transform(Xte)


def fit_lgb_external(Xwg: np.ndarray, ywg: np.ndarray, Xext: np.ndarray) -> np.ndarray:
    Xtr, Xte = transform_train_external(Xwg, Xext)
    preds = []
    for seed in SEEDS:
        preds.append(train_lgb(Xtr, ywg, Xte, seed=seed))
    return np.mean(np.vstack(preds), axis=0)


def external_loocv_ridge(df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
    y = df["target_updrs3"].to_numpy(dtype=float)
    X = df[feature_cols].to_numpy(dtype=float)
    preds = np.zeros(len(y), dtype=float)
    loo = LeaveOneOut()
    for tr, te in loo.split(X):
        Xtr, Xte = transform_train_external(X[tr], X[te])
        model = Ridge(alpha=10.0)
        model.fit(Xtr, y[tr])
        preds[te] = model.predict(Xte)
    return preds


def run(n_boot: int = 5000) -> Path:
    verify_preregistration()
    if not FEATURE_CSV.exists():
        extract_features(force=False)
    pah = pd.read_csv(FEATURE_CSV)
    pre = pah[(pah["state"] == "pre") & pd.to_numeric(pah["target_updrs3"], errors="coerce").notna()].copy()
    if pre["sid"].nunique() < 20:
        raise RuntimeError(f"Hard stop: fewer than 20 valid OFF PD subjects ({pre['sid'].nunique()})")
    data = filter_cohort("drop_allmissing_validrange")
    wg_feat = weargait_right_wrist_features(data["sids"])
    wg = pd.DataFrame({"sid": [str(s) for s in data["sids"]], "target": data["y_t3"]}).merge(wg_feat, on="sid", how="inner")
    feature_cols = sorted(c for c in set(wg.columns) & set(pre.columns) if c.startswith("mag_") or c.startswith("meta_"))
    if len(feature_cols) < 20:
        raise RuntimeError(f"Too few common feature columns: {len(feature_cols)}")

    Xwg = wg[feature_cols].to_numpy(dtype=float)
    ywg = wg["target"].to_numpy(dtype=float)
    Xpre = pre[feature_cols].to_numpy(dtype=float)
    ypre = pre["target_updrs3"].to_numpy(dtype=float)
    track_a = fit_lgb_external(Xwg, ywg, Xpre)

    rng = np.random.RandomState(20260509)
    shuffled = np.array(ywg, copy=True)
    rng.shuffle(shuffled)
    track_a_shuffle = fit_lgb_external(Xwg, shuffled, Xpre)

    track_c = external_loocv_ridge(pre, feature_cols)

    post = pah[(pah["state"] == "post") & pd.to_numeric(pah["target_updrs3"], errors="coerce").notna()].copy()
    paired = pre[["sid", "target_updrs3"] + feature_cols].merge(
        post[["sid", "target_updrs3"] + feature_cols],
        on="sid",
        suffixes=("_pre", "_post"),
        how="inner",
    )
    if len(paired):
        Xpost = post[feature_cols].to_numpy(dtype=float)
        post_pred_map = dict(zip(post["sid"], fit_lgb_external(Xwg, ywg, Xpost)))
        pre_pred_map = dict(zip(pre["sid"], track_a))
        paired["pred_delta_post_minus_pre"] = paired["sid"].map(post_pred_map) - paired["sid"].map(pre_pred_map)
        paired["true_delta_post_minus_pre"] = paired["target_updrs3_post"] - paired["target_updrs3_pre"]
        track_d = metrics(
            paired["true_delta_post_minus_pre"].to_numpy(dtype=float),
            paired["pred_delta_post_minus_pre"].to_numpy(dtype=float),
        )
    else:
        track_d = {"n": 0, "skipped_reason": "no paired pre/post rows"}

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rows_out = pre[["sid", "target_updrs3", "side_label", "rows_used"]].copy()
    rows_out["track_a_pred"] = track_a
    rows_out["track_c_pred"] = track_c
    row_path = RESULTS_DIR / f"iter53_parkinsonathome_zeroshot_rows_{ts}.csv"
    rows_out.to_csv(row_path, index=False)

    result = {
        "experiment": "T3 iter53 Parkinson@Home external zero-shot validation",
        "created_at_utc": now_utc(),
        "git_sha": git_sha(),
        "formula_sha256": canonical_sha(formula()),
        "feature_csv": str(FEATURE_CSV),
        "row_predictions": str(row_path),
        "n_weargait_train": int(len(wg)),
        "n_parkinsonathome_pre": int(len(pre)),
        "n_common_magnitude_features": int(len(feature_cols)),
        "feature_cols": feature_cols,
        "tracks": {
            "track_a_weargait_right_wrist_to_pah_off": {
                **metrics(ypre, track_a),
                "ccc_bootstrap": ccc_ci(ypre, track_a, n_boot=n_boot),
            },
            "track_b_clinical_plus_wrist": {
                "skipped": True,
                "reason": "Public Parkinson@Home patient_info.csv has UPDRS subitems but no non-target H&Y/disease-duration/sex/DBS clinical covariates.",
            },
            "track_c_pah_only_loocv_sanity": {
                **metrics(ypre, track_c),
                "ccc_bootstrap": ccc_ci(ypre, track_c, n_boot=n_boot),
            },
            "track_d_off_on_response_sensitivity": track_d,
            "null_track_a_weargait_target_shuffle": metrics(ypre, track_a_shuffle),
        },
        "policy": {
            "internal_t3_canonical_update_allowed": False,
            "internal_t1_canonical_update_allowed": False,
            "ceiling_break_framing_allowed": False,
            "interpretation": "external transportability / protocol-mismatch evidence only",
        },
        "decision": "external_zero_shot_only_no_internal_t3_canonical_change",
    }
    out = RESULTS_DIR / f"iter53_parkinsonathome_zeroshot_{ts}.json"
    out.write_text(json.dumps(jsonable(result), indent=2) + "\n", encoding="utf-8")
    STABLE_RESULT.write_text(json.dumps(jsonable(result), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(jsonable(result["tracks"]), indent=2), flush=True)
    print(f"Wrote {out}\nWrote {STABLE_RESULT}\nWrote {row_path}", flush=True)
    return out


def probe(sample_sid: str = "hbv002") -> Path:
    ensure_dir(RESULTS_DIR)
    paths = ensure_metadata(force=False)
    targets = clinical_targets()
    dist = load_distribution()
    pd_rows = targets[targets["is_pd_primary"]].copy()
    side_label = side_label_for_right(sample_sid, dist)
    sample_meta: dict[str, Any] = {"sid": sample_sid, "side_label": side_label}
    try:
        if side_label is None:
            raise RuntimeError("sample right-wrist side not found")
        local = download(prepared_rel_path(sample_sid, side_label), prepared_local_path(sample_sid, side_label), force=False)
        df = read_prepared_parquet(local)
        acc = df[["accelerometer_x", "accelerometer_y", "accelerometer_z"]].to_numpy(dtype=float)
        _, scale = classify_acc_scale(acc)
        sample_meta.update(
            {
                "status": "ok",
                "path": str(local),
                "size_bytes": int(local.stat().st_size),
                "shape": [int(df.shape[0]), int(df.shape[1])],
                "columns": list(df.columns),
                "free_living_labels": df["free_living_label"].astype(str).value_counts().head(8).to_dict(),
                "arm_labels": df["arm_label"].astype(str).value_counts().head(8).to_dict(),
                **scale,
            }
        )
    except Exception as exc:
        sample_meta.update({"status": "failed", "error": str(exc)})
    out = {
        "created_at_utc": now_utc(),
        "script": Path(__file__).name,
        "mode": "probe",
        "dataset": "Parkinson@Home",
        "doi": DATASET_DOI,
        "metadata_files": {k: {"path": str(v), "sha256": sha256_file(v), "size_bytes": v.stat().st_size} for k, v in paths.items()},
        "n_patient_info_rows": int(len(targets)),
        "n_pd_off_valid_target_rows": int(pd_rows["record_id"].nunique()),
        "n_off_columns": len(part3_cols(targets, "OFF_UPDRS_3_")),
        "n_on_columns": len(part3_cols(targets, "ON_UPDRS_3_")),
        "off_target_summary": {
            "mean": float(pd_rows["off_updrs3"].mean()),
            "min": float(pd_rows["off_updrs3"].min()),
            "max": float(pd_rows["off_updrs3"].max()),
        },
        "clinical_covariates_public": [],
        "track_b_status": "skipped_public_non_target_clinical_covariates_absent",
        "sample_prepared_parquet": sample_meta,
        "decision": (
            "direct_public_external_t3_route_for_zero_shot_only"
            if int(pd_rows["record_id"].nunique()) >= 20 and sample_meta.get("status") == "ok"
            else "document_only_until_probe_passes"
        ),
    }
    path = RESULTS_DIR / "iter53_parkinsonathome_probe.json"
    path.write_text(json.dumps(jsonable(out), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(jsonable(out), indent=2), flush=True)
    print(f"Wrote {path}", flush=True)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["probe", "write-prereg", "extract", "run"], required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--n_boot", type=int, default=5000)
    args = parser.parse_args()
    if args.mode == "probe":
        probe()
    elif args.mode == "write-prereg":
        write_preregistration()
    elif args.mode == "extract":
        extract_features(force=args.force)
    elif args.mode == "run":
        run(n_boot=args.n_boot)
    else:
        raise AssertionError(args.mode)


if __name__ == "__main__":
    main()
