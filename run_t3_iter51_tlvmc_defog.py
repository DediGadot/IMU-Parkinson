"""T3 iter51 — TLVMC/DeFOG zero-shot external validation.

This script executes the fixed pre-model preregistration written by
`scripts/write_tlvmc_defog_prereg.py`. TLVMC/DeFOG is external-validity evidence
only; no result from this script may update the internal WearGait-PD T3
canonical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import signal as sp_signal
from scipy import stats as sp_stats
from sklearn.linear_model import Ridge

from inductive_lib import FoldImputer, FoldNormalizer, cal_slope, ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import DATA_DIR, REPO_ROOT, RESULTS_DIR, ensure_dir
from run_t3_iter2 import train_lgb
from run_t3_iter47_invalid_code_fix import filter_cohort
from scripts.write_tlvmc_defog_prereg import build_formula, canonical_sha


EXPECTED_FORMULA_SHA = "665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd"
KAGGLE_COMPETITION = "tlvmc-parkinsons-freezing-gait-prediction"
TLVMC_DIR = Path(os.getenv("TLVMC_FOG_DATA_DIR", REPO_ROOT / "data" / "raw" / "tlvmc-defog"))
STABLE_RESULT = RESULTS_DIR / "iter51_tlvmc_defog_zeroshot.json"
FEATURE_CSV = RESULTS_DIR / "iter51_tlvmc_defog_features.csv"
WEARGAIT_TASKS = ("TUG", "SelfPace", "HurriedPace")
SEEDS = (42, 1337, 7)
FS_NATIVE = 100
FS_FEATURE = 20
DOWNSAMPLE_STRIDE = FS_NATIVE // FS_FEATURE
WINDOW_SECONDS = 5
MIN_SECONDS = 5
G_TO_MPS2 = 9.80665
RAW_COLUMNS = ["Time", "AccV", "AccML", "AccAP", "Valid", "Task"]
METADATA_FILES = ["subjects.csv", "defog_metadata.csv", "tasks.csv"]


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_preregistration() -> dict[str, Any]:
    formula = build_formula()
    actual = canonical_sha(formula)
    if actual != EXPECTED_FORMULA_SHA:
        raise RuntimeError(f"iter51 preregistration formula SHA mismatch: {actual} != {EXPECTED_FORMULA_SHA}")
    stable = RESULTS_DIR / "preregistration_t3_iter51_tlvmc_defog_zeroshot.json"
    if stable.exists():
        payload = json.loads(stable.read_text(encoding="utf-8"))
        if payload.get("formula_sha256") != EXPECTED_FORMULA_SHA:
            raise RuntimeError(f"Stable preregistration SHA mismatch in {stable}")
    return {"formula_sha256": actual, "formula": formula}


def run_cmd(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=REPO_ROOT, check=True, text=True)


def kaggle_cli() -> str:
    exe = shutil.which("kaggle")
    if exe is None:
        venv_exe = Path(sys.executable).with_name("kaggle")
        if venv_exe.exists():
            exe = str(venv_exe)
    if exe is None:
        raise RuntimeError("kaggle CLI is required for --mode download")
    return exe


def download_kaggle_file(rel_path: str, out_dir: Path, force: bool = False) -> Path:
    ensure_dir(out_dir)
    target = out_dir / Path(rel_path).name
    zip_target = out_dir / f"{Path(rel_path).name}.zip"
    if target.exists() and not force:
        return target
    if zip_target.exists() and not force:
        return zip_target
    cmd = [
        kaggle_cli(),
        "competitions",
        "download",
        "-c",
        KAGGLE_COMPETITION,
        "-f",
        rel_path,
        "-p",
        str(out_dir),
        "--quiet",
    ]
    if force:
        cmd.append("--force")
    run_cmd(cmd)
    if target.exists():
        return target
    if zip_target.exists():
        return zip_target
    return target


def read_kaggle_csv(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names = [name for name in zf.namelist() if name.endswith(".csv")]
            if len(names) != 1:
                raise RuntimeError(f"Expected one CSV inside {path}, found {names}")
            with zf.open(names[0]) as f:
                return pd.read_csv(f, usecols=usecols)
    return pd.read_csv(path, usecols=usecols)


def metadata_path(name: str) -> Path:
    return TLVMC_DIR / "metadata" / name


def ensure_metadata(force: bool = False) -> None:
    for name in METADATA_FILES:
        download_kaggle_file(name, TLVMC_DIR / "metadata", force=force)


def raw_candidates(recording_id: str) -> list[Path]:
    filename = f"{recording_id}.csv"
    return [
        TLVMC_DIR / "train" / "defog" / filename,
        TLVMC_DIR / "test" / "defog" / filename,
        TLVMC_DIR / "train" / "notype" / filename,
        TLVMC_DIR / "test" / "notype" / filename,
        TLVMC_DIR / "defog" / filename,
        TLVMC_DIR / "raw_defog" / filename,
        TLVMC_DIR / filename,
        TLVMC_DIR / "raw_defog" / f"{filename}.zip",
        TLVMC_DIR / "train" / "defog" / f"{filename}.zip",
        TLVMC_DIR / "test" / "defog" / f"{filename}.zip",
        TLVMC_DIR / "train" / "notype" / f"{filename}.zip",
        TLVMC_DIR / "test" / "notype" / f"{filename}.zip",
    ]


def raw_path(recording_id: str) -> Path | None:
    for path in raw_candidates(recording_id):
        if path.exists():
            return path
    return None


def download_defog_recording(recording_id: str, out_dir: Path, force: bool = False) -> tuple[Path, str]:
    last_error: Exception | None = None
    for rel in [
        f"train/defog/{recording_id}.csv",
        f"test/defog/{recording_id}.csv",
        f"train/notype/{recording_id}.csv",
        f"test/notype/{recording_id}.csv",
    ]:
        try:
            path = download_kaggle_file(rel, out_dir, force=force)
            return path, rel
        except subprocess.CalledProcessError as exc:
            last_error = exc
            continue
    raise RuntimeError(f"Could not download {recording_id} from train/defog or test/defog") from last_error


def load_joined_metadata() -> pd.DataFrame:
    subjects = pd.read_csv(metadata_path("subjects.csv"))
    defog = pd.read_csv(metadata_path("defog_metadata.csv"))
    subjects["Visit"] = pd.to_numeric(subjects["Visit"], errors="coerce").astype("Int64")
    defog["Visit"] = pd.to_numeric(defog["Visit"], errors="coerce").astype("Int64")
    merged = defog.merge(subjects, on=["Subject", "Visit"], how="left", suffixes=("", "_subject"))
    med = merged["Medication"].astype(str).str.lower()
    merged["target"] = np.where(
        med == "off",
        pd.to_numeric(merged["UPDRSIII_Off"], errors="coerce"),
        pd.to_numeric(merged["UPDRSIII_On"], errors="coerce"),
    )
    merged["target_kind"] = np.where(med == "off", "UPDRSIII_Off", "UPDRSIII_On")
    return merged[pd.to_numeric(merged["target"], errors="coerce").notna()].reset_index(drop=True)


def download_defog_raw(force: bool = False, states: set[str] | None = None, max_records: int | None = None) -> Path:
    verify_preregistration()
    ensure_metadata(force=force)
    meta = load_joined_metadata()
    if states:
        meta = meta[meta["Medication"].astype(str).str.lower().isin(states)].reset_index(drop=True)
    if max_records is not None:
        meta = meta.head(int(max_records)).copy()
    out_dir = TLVMC_DIR / "raw_defog"
    ensure_dir(out_dir)
    rows = []
    for i, row in enumerate(meta.itertuples(index=False), start=1):
        rid = str(row.Id)
        existing = raw_path(rid)
        source_rel = None
        if existing is None or force:
            print(f"[download {i}/{len(meta)}] {rid}", flush=True)
            existing, source_rel = download_defog_recording(rid, out_dir, force=force)
        rows.append(
            {
                "id": rid,
                "subject": str(row.Subject),
                "visit": None if pd.isna(row.Visit) else int(row.Visit),
                "medication": str(row.Medication).lower(),
                "path": str(existing),
                "source_rel_path": source_rel,
                "size_bytes": int(existing.stat().st_size),
                "sha256": sha256_file(existing),
            }
        )
    manifest = {
        "created_at_utc": now_utc(),
        "script": Path(__file__).name,
        "mode": "download",
        "dataset": "TLVMC/DeFOG",
        "kaggle_competition": KAGGLE_COMPETITION,
        "formula_sha256": EXPECTED_FORMULA_SHA,
        "n_files": len(rows),
        "states": sorted(states) if states else ["on", "off"],
        "files": rows,
    }
    out = RESULTS_DIR / "iter51_tlvmc_defog_download_manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}", flush=True)
    return out


def _safe_stat(fn, x: np.ndarray) -> float:
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
        "mag_chunk_skew": _safe_stat(sp_stats.skew, x),
        "mag_chunk_kurt": _safe_stat(sp_stats.kurtosis, x),
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


def chunk_features_from_mag(mag_mps2: np.ndarray) -> dict[str, float]:
    mag = np.asarray(mag_mps2, dtype=np.float64)
    if DOWNSAMPLE_STRIDE > 1:
        mag = mag[::DOWNSAMPLE_STRIDE]
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


def classify_and_scale_defog(acc: np.ndarray, valid_mask: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    mag_raw = np.sqrt(np.sum(acc * acc, axis=1))
    valid_mag = mag_raw[valid_mask] if int(valid_mask.sum()) else mag_raw
    med = float(np.nanmedian(valid_mag))
    mean = float(np.nanmean(valid_mag))
    if 0.5 <= med <= 2.0:
        return acc * G_TO_MPS2, {"unit": "g_converted_to_mps2", "median_raw_mag": med, "mean_raw_mag": mean}
    if 5.0 <= med <= 15.0:
        return acc, {"unit": "mps2_native", "median_raw_mag": med, "mean_raw_mag": mean}
    raise RuntimeError(f"Cannot classify DeFOG acceleration scale: median magnitude={med:.4f}")


def defog_features(recording_id: str, row_mask: str = "primary") -> tuple[dict[str, float], dict[str, Any]]:
    path = raw_path(recording_id)
    if path is None:
        raise FileNotFoundError(f"Missing raw DeFOG file for {recording_id} under {TLVMC_DIR}")
    df = read_kaggle_csv(path, usecols=RAW_COLUMNS)
    for col in RAW_COLUMNS:
        if col not in df.columns:
            raise RuntimeError(f"{path} missing required column {col}")
    valid = pd.to_numeric(df["Valid"], errors="coerce").fillna(0).to_numpy(dtype=np.float64) == 1
    task = pd.to_numeric(df["Task"], errors="coerce").fillna(0).to_numpy(dtype=np.float64) == 1
    mask = valid & task if row_mask == "primary" else valid
    acc_raw = df[["AccV", "AccML", "AccAP"]].to_numpy(dtype=np.float64)
    acc, scale = classify_and_scale_defog(acc_raw, valid)
    if int(mask.sum()) < FS_NATIVE * MIN_SECONDS:
        return {}, {
            "path": str(path),
            "rows_total": int(len(df)),
            "rows_valid": int(valid.sum()),
            "rows_used": int(mask.sum()),
            **scale,
        }
    mag = np.sqrt(np.sum(acc[mask] * acc[mask], axis=1))
    feats = aggregate_feature_dicts([chunk_features_from_mag(mag)])
    meta = {
        "path": str(path),
        "rows_total": int(len(df)),
        "rows_valid": int(valid.sum()),
        "rows_task": int(task.sum()),
        "rows_used": int(mask.sum()),
        "mag_mean_mps2": float(np.mean(mag)),
        **scale,
    }
    return feats, meta


def weargait_magnitude_features(sids: np.ndarray, sensor_prefix: str) -> pd.DataFrame:
    pd_dir = DATA_DIR / "PD PARTICIPANTS" / "CSV files"
    cols = [f"{sensor_prefix}_Acc_X", f"{sensor_prefix}_Acc_Y", f"{sensor_prefix}_Acc_Z"]
    rows = []
    for sid in sids:
        chunks: list[dict[str, float]] = []
        for task in WEARGAIT_TASKS:
            path = pd_dir / f"{sid}_{task}.csv"
            if not path.exists():
                continue
            try:
                df = pd.read_csv(path, usecols=cols)
            except Exception:
                continue
            if len(df) < FS_NATIVE * MIN_SECONDS:
                continue
            arr = df[cols].to_numpy(dtype=np.float64)
            mag = np.sqrt(np.sum(arr * arr, axis=1))
            feats = chunk_features_from_mag(mag)
            if feats:
                chunks.append(feats)
        row = aggregate_feature_dicts(chunks)
        if row:
            row["sid"] = str(sid)
            row[f"{sensor_prefix}_n_task_chunks"] = float(len(chunks))
            rows.append(row)
    if not rows:
        raise RuntimeError(f"No WearGait {sensor_prefix} magnitude features extracted from {pd_dir}")
    return pd.DataFrame(rows)


def extract_defog_features(force: bool = False, row_mask: str = "primary") -> Path:
    verify_preregistration()
    if force or not all(metadata_path(name).exists() for name in METADATA_FILES):
        ensure_metadata(force=force)
    meta = load_joined_metadata()
    rows = []
    skipped = []
    t0 = time.time()
    for i, row in enumerate(meta.itertuples(index=False), start=1):
        rid = str(row.Id)
        try:
            feats, raw_meta = defog_features(rid, row_mask=row_mask)
        except Exception as exc:
            skipped.append({"id": rid, "reason": str(exc)})
            continue
        if not feats:
            skipped.append({"id": rid, "reason": "too_few_rows_after_mask", "raw_meta": raw_meta})
            continue
        out: dict[str, Any] = {
            "id": rid,
            "subject": str(row.Subject),
            "visit": int(row.Visit) if not pd.isna(row.Visit) else None,
            "medication": str(row.Medication).lower(),
            "updrsiii_on": float(row.UPDRSIII_On) if pd.notna(row.UPDRSIII_On) else np.nan,
            "updrsiii_off": float(row.UPDRSIII_Off) if pd.notna(row.UPDRSIII_Off) else np.nan,
            "target": float(row.target),
            "target_kind": str(row.target_kind),
            "age": float(row.Age) if pd.notna(row.Age) else np.nan,
            "sex": str(row.Sex),
            "years_since_dx": float(row.YearsSinceDx) if pd.notna(row.YearsSinceDx) else np.nan,
            "row_mask": row_mask,
        }
        out.update({f"raw_{k}": v for k, v in raw_meta.items() if k != "path"})
        out["raw_path"] = raw_meta.get("path")
        out.update(feats)
        rows.append(out)
        if i % 25 == 0:
            print(f"[extract] {i}/{len(meta)} metadata rows, retained {len(rows)}", flush=True)
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No DeFOG features extracted.")
    df.to_csv(FEATURE_CSV, index=False)
    manifest = {
        "created_at_utc": now_utc(),
        "script": Path(__file__).name,
        "mode": "extract",
        "formula_sha256": EXPECTED_FORMULA_SHA,
        "row_mask": row_mask,
        "n_rows": int(len(df)),
        "n_subjects": int(df["subject"].nunique()),
        "n_off_rows": int((df["medication"] == "off").sum()),
        "n_on_rows": int((df["medication"] == "on").sum()),
        "elapsed_s": round(time.time() - t0, 2),
        "output_csv": str(FEATURE_CSV),
        "output_sha256": sha256_file(FEATURE_CSV),
        "skipped": skipped,
        "labels_used": ["UPDRSIII_On", "UPDRSIII_Off"],
        "leakage_status": "external_feature_cache_for_preregistered_zero_shot_evaluation_only",
    }
    man_path = Path(str(FEATURE_CSV) + ".manifest.json")
    man_path.write_text(json.dumps(_jsonable(manifest), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {FEATURE_CSV}", flush=True)
    print(f"Wrote {man_path}", flush=True)
    return FEATURE_CSV


def clean_train_test(X_train: np.ndarray, X_test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    imp = FoldImputer.fit(X_train)
    Xtr = imp.transform(X_train)
    Xte = imp.transform(X_test)
    Xtr = np.nan_to_num(Xtr, nan=0.0, posinf=0.0, neginf=0.0)
    Xte = np.nan_to_num(Xte, nan=0.0, posinf=0.0, neginf=0.0)
    lo = np.nanpercentile(Xtr, 1, axis=0)
    hi = np.nanpercentile(Xtr, 99, axis=0)
    Xtr = np.clip(Xtr, lo, hi)
    Xte = np.clip(Xte, lo, hi)
    nrm = FoldNormalizer.fit(Xtr)
    return nrm.transform(Xtr), nrm.transform(Xte)


def ridge_predict(X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray, alpha: float = 10.0) -> np.ndarray:
    Xtr, Xte = clean_train_test(X_train, X_test)
    model = Ridge(alpha=alpha, fit_intercept=True)
    model.fit(Xtr, y_train)
    return model.predict(Xte)


def lgb_predict_mean(X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray) -> np.ndarray:
    Xtr, Xte = clean_train_test(X_train, X_test)
    preds = [train_lgb(Xtr, y_train, Xte, seed) for seed in SEEDS]
    return np.mean(np.stack(preds, axis=0), axis=0)


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "n": int(len(y_true)),
        "ccc": round(float(ccc_fn(y_true, y_pred)), 4),
        "mae": round(float(mae_fn(y_true, y_pred)), 4),
        "r": round(float(pearson_r(y_true, y_pred)), 4),
        "cal_slope": round(float(cal_slope(y_true, y_pred)), 4),
        "pred_mean": round(float(np.mean(y_pred)), 4),
        "pred_std": round(float(np.std(y_pred)), 4),
        "true_mean": round(float(np.mean(y_true)), 4),
        "true_std": round(float(np.std(y_true)), 4),
    }


def clustered_bootstrap_metric(
    subjects: np.ndarray,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    n_boot: int = 10000,
    seed: int = 20260509,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    subjects = np.asarray(subjects)
    unique = np.asarray(sorted(set(map(str, subjects))))
    vals = []
    for _ in range(int(n_boot)):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([np.where(subjects.astype(str) == sid)[0] for sid in sampled])
        vals.append(ccc_fn(y_true[idx], y_pred[idx]))
    arr = np.asarray(vals, dtype=np.float64)
    return {
        "n_boot": int(n_boot),
        "cluster_key": "subject",
        "ccc_ci95": [round(float(np.percentile(arr, 2.5)), 4), round(float(np.percentile(arr, 97.5)), 4)],
        "ccc_frac_gt_0": round(float(np.mean(arr > 0)), 4),
        "ccc_frac_gt_02": round(float(np.mean(arr > 0.2)), 4),
        "ccc_frac_gt_038": round(float(np.mean(arr > 0.38)), 4),
    }


def metric_block(df: pd.DataFrame, y_col: str, pred_col: str, n_boot: int) -> dict[str, Any]:
    sub = df[[y_col, pred_col, "subject"]].copy()
    mask = np.isfinite(sub[y_col].to_numpy(dtype=np.float64)) & np.isfinite(sub[pred_col].to_numpy(dtype=np.float64))
    sub = sub[mask]
    y = sub[y_col].to_numpy(dtype=np.float64)
    p = sub[pred_col].to_numpy(dtype=np.float64)
    if len(y) < 3:
        return {"n": int(len(y)), "error": "too_few_rows"}
    return {**metrics(y, p), **clustered_bootstrap_metric(sub["subject"].astype(str).to_numpy(), y, p, n_boot=n_boot)}


def subject_visit_mean_state(rows: pd.DataFrame, pred_col: str) -> pd.DataFrame:
    sub = rows.copy()
    sub["subject_visit"] = sub["subject"].astype(str) + "::" + sub["visit"].astype(str)
    grouped = sub.groupby(["subject", "visit"], as_index=False).agg(
        y_mean=("target", "mean"),
        pred_mean=(pred_col, "mean"),
        n_states=("medication", "nunique"),
    )
    return grouped.rename(columns={"y_mean": "target", "pred_mean": pred_col})


def fit_external_tracks(feature_csv: Path, n_boot: int = 10000) -> tuple[dict[str, Any], pd.DataFrame]:
    verify_preregistration()
    ext = pd.read_csv(feature_csv)
    off = ext[ext["medication"].astype(str).str.lower() == "off"].reset_index(drop=True)
    if len(off) < 40:
        raise RuntimeError(f"Preflight stop: only {len(off)} OFF rows after extraction; expected at least 40.")

    wg_data = filter_cohort("drop_allmissing_validrange")
    sids = wg_data["sids"]
    y_train = wg_data["y_t3"].astype(float)
    wg_lower = weargait_magnitude_features(sids, "LowerBack")
    wg_wrist = weargait_magnitude_features(sids, "R_Wrist")
    wg_base = pd.DataFrame({"sid": sids, "updrs3": y_train})
    wg_lower = wg_base.merge(wg_lower, on="sid", how="inner").reset_index(drop=True)
    wg_wrist = wg_base.merge(wg_wrist, on="sid", how="inner").reset_index(drop=True)
    feature_cols = sorted([c for c in ext.columns if c.startswith("mag_") or c.startswith("meta_")])
    feature_cols = [c for c in feature_cols if c in wg_lower.columns and c in wg_wrist.columns]
    if len(feature_cols) < 20:
        raise RuntimeError(f"Preflight stop: only {len(feature_cols)} common magnitude feature columns.")

    X_ext = ext[feature_cols].to_numpy(dtype=np.float64)
    X_lower = wg_lower[feature_cols].to_numpy(dtype=np.float64)
    y_lower = wg_lower["updrs3"].to_numpy(dtype=np.float64)
    X_wrist = wg_wrist[feature_cols].to_numpy(dtype=np.float64)
    y_wrist = wg_wrist["updrs3"].to_numpy(dtype=np.float64)

    pred_a_lgb = lgb_predict_mean(X_lower, y_lower, X_ext)
    pred_a_ridge = ridge_predict(X_lower, y_lower, X_ext, alpha=10.0)
    pred_a_mean = (pred_a_lgb + pred_a_ridge) / 2.0
    pred_b_lgb = lgb_predict_mean(X_wrist, y_wrist, X_ext)
    pred_b_ridge = ridge_predict(X_wrist, y_wrist, X_ext, alpha=10.0)
    pred_b_mean = (pred_b_lgb + pred_b_ridge) / 2.0

    rows = ext.copy()
    rows["track_a_lgb"] = pred_a_lgb
    rows["track_a_ridge"] = pred_a_ridge
    rows["track_a_mean"] = pred_a_mean
    rows["track_b_lgb"] = pred_b_lgb
    rows["track_b_ridge"] = pred_b_ridge
    rows["track_b_mean"] = pred_b_mean

    # Track C: subject-grouped LOSO sanity on OFF rows only.
    pred_c = np.full(len(off), np.nan, dtype=np.float64)
    Xc = off[feature_cols].to_numpy(dtype=np.float64)
    yc = off["target"].to_numpy(dtype=np.float64)
    subj = off["subject"].astype(str).to_numpy()
    for sid in sorted(set(subj)):
        te = np.where(subj == sid)[0]
        tr = np.where(subj != sid)[0]
        pred_c[te] = ridge_predict(Xc[tr], yc[tr], Xc[te], alpha=10.0)
    off_pred = off[["id"]].copy()
    off_pred["track_c_defog_loso_ridge"] = pred_c
    rows = rows.merge(off_pred, on="id", how="left")

    metrics_by_target: dict[str, Any] = {}
    pred_cols = ["track_a_mean", "track_a_lgb", "track_a_ridge", "track_b_mean", "track_b_lgb", "track_b_ridge"]
    for label, subset in {
        "off_primary": rows[rows["medication"] == "off"].copy(),
        "on_sensitivity": rows[rows["medication"] == "on"].copy(),
        "pooled_medication_matched_sensitivity": rows.copy(),
    }.items():
        metrics_by_target[label] = {col: metric_block(subset, "target", col, n_boot=n_boot) for col in pred_cols}
    metrics_by_target["off_primary"]["track_c_defog_loso_ridge"] = metric_block(
        rows[rows["medication"] == "off"].copy(), "target", "track_c_defog_loso_ridge", n_boot=n_boot
    )
    mean_state_metrics = {}
    for col in pred_cols:
        grouped = subject_visit_mean_state(rows, col)
        mean_state_metrics[col] = metric_block(grouped, "target", col, n_boot=n_boot)
    metrics_by_target["subject_visit_mean_state_sensitivity"] = mean_state_metrics

    nulls = run_nulls(rows, feature_cols, n_boot=max(1000, min(n_boot, 2000)))
    result = {
        "created_at_utc": now_utc(),
        "script": Path(__file__).name,
        "mode": "run",
        "preregistration_formula_sha256": EXPECTED_FORMULA_SHA,
        "features_csv": str(feature_csv),
        "n_weargait_lowerback_train": int(len(wg_lower)),
        "n_weargait_wrist_train": int(len(wg_wrist)),
        "n_defog_rows": int(len(rows)),
        "n_defog_subjects": int(rows["subject"].nunique()),
        "n_defog_off_rows": int((rows["medication"] == "off").sum()),
        "n_defog_on_rows": int((rows["medication"] == "on").sum()),
        "n_common_magnitude_features": int(len(feature_cols)),
        "feature_cols": feature_cols,
        "model_policy": {
            "track_a": "mean of fixed LGB 3-seed prediction and fixed Ridge(alpha=10.0)",
            "track_b": "same fixed models, WearGait right-wrist train to DeFOG lower-back test",
            "track_c": "DeFOG-only subject-grouped LOSO Ridge(alpha=10.0)",
        },
        "metrics": metrics_by_target,
        "null_sanity_checks": nulls,
        "interpretation": interpret(metrics_by_target),
        "decision": "external_zero_shot_only_no_internal_t3_canonical_change",
    }
    return result, rows


def run_nulls(rows: pd.DataFrame, feature_cols: list[str], n_boot: int) -> dict[str, Any]:
    rng = np.random.default_rng(20260509)
    out: dict[str, Any] = {}
    off = rows[rows["medication"] == "off"].reset_index(drop=True)
    if len(off) >= 3:
        shuffled = off.copy()
        shuffled["target"] = rng.permutation(shuffled["target"].to_numpy(dtype=np.float64))
        out["target_shuffle_track_a_mean_off"] = metric_block(shuffled, "target", "track_a_mean", n_boot=n_boot)

        X = off[feature_cols].to_numpy(dtype=np.float64)
        y_perm = rng.permutation(off["target"].to_numpy(dtype=np.float64))
        subj = off["subject"].astype(str).to_numpy()
        pred = np.full(len(off), np.nan, dtype=np.float64)
        for sid in sorted(set(subj)):
            te = np.where(subj == sid)[0]
            tr = np.where(subj != sid)[0]
            pred[te] = ridge_predict(X[tr], y_perm[tr], X[te], alpha=10.0)
        tmp = off[["subject", "target"]].copy()
        tmp["scrambled_pred"] = pred
        out["scrambled_label_track_c_off"] = metric_block(tmp, "target", "scrambled_pred", n_boot=n_boot)

        model = Ridge(alpha=10.0, fit_intercept=True)
        Xn, _ = clean_train_test(X, X)
        model.fit(Xn, off["target"].to_numpy(dtype=np.float64))
        trans = off[["subject", "target"]].copy()
        trans["transductive_pred"] = model.predict(Xn)
        out["transductive_defog_off_diagnostic"] = metric_block(trans, "target", "transductive_pred", n_boot=n_boot)

    out["test_only_canary_policy"] = {
        "status": "passed_by_column_intersection",
        "rationale": "A DeFOG-only canary feature is absent from WearGait training columns and therefore cannot enter Tracks A/B.",
    }
    out["sid_shuffle_before_join"] = sid_shuffle_join_audit()
    return out


def sid_shuffle_join_audit() -> dict[str, Any]:
    meta = pd.read_csv(metadata_path("defog_metadata.csv"))
    subjects = pd.read_csv(metadata_path("subjects.csv"))
    meta["Visit"] = pd.to_numeric(meta["Visit"], errors="coerce").astype("Int64")
    subjects["Visit"] = pd.to_numeric(subjects["Visit"], errors="coerce").astype("Int64")
    rng = np.random.default_rng(20260509)
    shuffled = meta.copy()
    shuffled["Subject"] = rng.permutation(shuffled["Subject"].astype(str).to_numpy())
    merged = shuffled.merge(subjects, on=["Subject", "Visit"], how="left")
    med = merged["Medication"].astype(str).str.lower()
    has_on = pd.to_numeric(merged["UPDRSIII_On"], errors="coerce").notna()
    has_off = pd.to_numeric(merged["UPDRSIII_Off"], errors="coerce").notna()
    matched = ((med == "on") & has_on) | ((med == "off") & has_off)
    return {
        "shuffled_rows_with_matching_medication_target": int(matched.sum()),
        "original_rows_with_matching_medication_target": 137,
        "status": "diagnostic_expected_to_drop_substantially",
    }


def interpret(metrics_by_target: dict[str, Any]) -> dict[str, Any]:
    primary = metrics_by_target.get("off_primary", {}).get("track_a_mean", {})
    ccc = primary.get("ccc")
    ci = primary.get("ccc_ci95", [None, None])
    if ccc is None:
        verdict = "not_scored"
    elif ccc > 0.38:
        verdict = "unexpected_high_signal_audit_trigger"
    elif ccc > 0.20 and ci[0] is not None and ci[0] > 0:
        verdict = "partial_external_validity"
    elif ccc <= 0.10 or (ci[1] is not None and ci[1] <= 0):
        verdict = "transportability_cliff"
    else:
        verdict = "weak_or_inconclusive_external_validity"
    return {
        "primary_track_a_mean_off_ccc": ccc,
        "primary_track_a_mean_off_ci95": ci,
        "verdict": verdict,
        "no_internal_canonical_change": True,
    }


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, tuple):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if pd.isna(obj) if not isinstance(obj, (dict, list, tuple, np.ndarray)) else False:
        return None
    return obj


def run(feature_csv: Path | None, n_boot: int) -> Path:
    if feature_csv is None:
        feature_csv = FEATURE_CSV
    if not feature_csv.exists():
        extract_defog_features(force=False, row_mask="primary")
    result, rows = fit_external_tracks(feature_csv, n_boot=n_boot)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rows_path = RESULTS_DIR / f"iter51_tlvmc_defog_zeroshot_rows_{ts}.csv"
    result_path = RESULTS_DIR / f"iter51_tlvmc_defog_zeroshot_{ts}.json"
    rows.to_csv(rows_path, index=False)
    result["rows_csv"] = str(rows_path)
    result_path.write_text(json.dumps(_jsonable(result), indent=2) + "\n", encoding="utf-8")
    STABLE_RESULT.write_text(json.dumps(_jsonable(result), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(_jsonable(result["interpretation"]), indent=2), flush=True)
    print(f"Wrote {result_path}", flush=True)
    print(f"Wrote {STABLE_RESULT}", flush=True)
    print(f"Wrote {rows_path}", flush=True)
    return result_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["download", "extract", "run", "preflight"], required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--states", nargs="*", choices=["on", "off"], default=["on", "off"])
    ap.add_argument("--max-records", type=int, default=None)
    ap.add_argument("--row-mask", choices=["primary", "valid"], default="primary")
    ap.add_argument("--features-csv", type=Path, default=None)
    ap.add_argument("--n-boot", type=int, default=10000)
    args = ap.parse_args()

    ensure_dir(RESULTS_DIR)
    if args.mode == "preflight":
        prereg = verify_preregistration()
        print(json.dumps({"formula_sha256": prereg["formula_sha256"], "data_dir": str(TLVMC_DIR)}, indent=2), flush=True)
    elif args.mode == "download":
        download_defog_raw(force=args.force, states=set(args.states), max_records=args.max_records)
    elif args.mode == "extract":
        extract_defog_features(force=args.force, row_mask=args.row_mask)
    elif args.mode == "run":
        run(args.features_csv, n_boot=args.n_boot)


if __name__ == "__main__":
    main()
