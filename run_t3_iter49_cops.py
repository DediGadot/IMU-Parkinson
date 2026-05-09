"""T3 iter49 — COPS external zero-shot route.

This script freezes a leakage-safe COPS evaluation design before any COPS
subject archives are downloaded, probes OSF file availability, and can run the
pre-registered external-validation battery. COPS results are transportability
evidence only; they never update the internal WearGait-PD T3 headline.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import time
import urllib.request
import zipfile
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


OSF_NODE = "5xvwn"
OSF_API = f"https://api.osf.io/v2/nodes/{OSF_NODE}/files/osfstorage/"
DATA_FOLDER_ID = "6872270ace6d2b66793282d8"
SCRIPTS_MATLAB_FOLDER_ID = "69983136d802b2b2e07aff8c"
DEMOGRAPHICS_URL = "https://osf.io/download/h6gu7/"
DEMOGRAPHICS_SHA256 = "252b0dc316a834ee450f45ee431d29e37df549444d27e04065e56d57123ea832"
COPS_DATA_DIR = Path(os.getenv("COPS_DATA_DIR", REPO_ROOT / "data" / "raw" / "cops"))
STABLE_PREREG = RESULTS_DIR / "preregistration_t3_iter49_cops.json"
SEEDS = (42, 1337, 7)
WEARGAIT_TASKS = ("TUG", "SelfPace", "HurriedPace")
FS_NATIVE = 100
FS_FEATURE = 20
DOWNSAMPLE_STRIDE = FS_NATIVE // FS_FEATURE
WINDOW_SECONDS = 30
MIN_SECONDS = 5
G_TO_MPS2 = 9.80665


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def osf_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def list_osf_folder(folder_id: str | None = None) -> list[dict[str, Any]]:
    url = OSF_API if folder_id is None else f"{OSF_API}{folder_id}/"
    rows: list[dict[str, Any]] = []
    while url:
        payload = osf_json(url)
        rows.extend(payload.get("data", []))
        url = payload.get("links", {}).get("next")
    return rows


def file_record(item: dict[str, Any]) -> dict[str, Any]:
    attrs = item.get("attributes", {})
    links = item.get("links", {})
    hashes = attrs.get("extra", {}).get("hashes", {})
    return {
        "name": attrs.get("name"),
        "kind": attrs.get("kind"),
        "materialized_path": attrs.get("materialized_path"),
        "size_bytes": attrs.get("size"),
        "sha256": hashes.get("sha256"),
        "md5": hashes.get("md5"),
        "download_url": links.get("download"),
        "date_modified": attrs.get("date_modified"),
    }


def build_formula() -> dict[str, Any]:
    return {
        "experiment": "t3_iter49_cops_external_zeroshot",
        "purpose": (
            "External transportability and paper-rigor evidence only. This does "
            "not update WearGait-PD internal T3 CCC and does not create a "
            "deployment headline."
        ),
        "current_internal_anchor": {
            "target": "T3 valid-range corrected total MDS-UPDRS Part III",
            "script": "run_t3_iter47_invalid_code_fix.py --mode run",
            "loocv_ccc": 0.3784,
            "loocv_mae": 7.528,
            "n": 95,
        },
        "external_dataset": {
            "name": "COPS: Continuous observation of Parkinsonian symptoms",
            "publication": "Scientific Data 2026, article 13:587",
            "osf_node": OSF_NODE,
            "osf_url": "https://osf.io/5xvwn/",
            "doi": "10.17605/OSF.IO/5XVWN",
            "declared_subjects": 66,
            "sensor": "bilateral wrist-worn GENEActiv accelerometers",
            "sampling_rate_hz": 100,
            "recording_context": "free-living continuous monitoring up to seven days",
            "labels": "UPDRS-III OFF/ON CSVs plus symptom diaries",
        },
        "fixed_battery": {
            "primary_target": "UPDRS-III OFF total",
            "target_sensitivities": ["UPDRS-III ON total", "mean of OFF and ON when both available"],
            "windowing": "30-second non-overlapping epochs over available wear-time",
            "feature_policy": (
                "magnitude-only, frame-invariant wrist accelerometry features; "
                "no axis-dependent features because COPS free-living wrist "
                "orientation is unconstrained."
            ),
            "sensor_policy": {
                "primary": "right wrist only, matching WearGait right-wrist primary schema",
                "sensitivity": "left wrist and bilateral mean-prediction fusion",
                "scale_assertion": "raw acceleration in g; check wear-time magnitude distribution before scoring",
            },
            "tracks": {
                "A_zero_shot_wrist_direct": {
                    "train": "WearGait-PD only",
                    "test": "COPS right-wrist features",
                    "labels_used_for_training": False,
                    "claim": "WearGait-to-COPS zero-shot transportability",
                },
                "B_zero_shot_clinical_plus_wrist": {
                    "train": "WearGait-PD only; iter47/iter5-style Stage 1 plus wrist residual",
                    "test": "COPS demographics plus right-wrist features",
                    "labels_used_for_training": False,
                    "claim": "Clinical/intake plus wrist zero-shot transportability",
                },
                "C_cops_only_loocv_sanity": {
                    "train": "COPS train folds only",
                    "test": "held-out COPS subjects",
                    "labels_used_for_training": True,
                    "claim": "within-COPS feasibility ceiling, not transportability",
                },
                "D_bilateral_sensitivity": {
                    "train": "same as Track A/B depending on branch",
                    "test": "COPS bilateral mean-prediction fusion",
                    "labels_used_for_training": False,
                    "claim": "sensor-placement sensitivity only",
                },
            },
        },
        "leakage_guards": [
            "COPS labels never enter WearGait model training or hyperparameter selection for Tracks A/B/D.",
            "No COPS fine-tuning for zero-shot tracks.",
            "No target-driven COPS window or subject filtering beyond pre-declared valid-label availability.",
            "Track C is explicitly within-COPS LOOCV sanity and must not be described as external transportability.",
            "No internal WearGait T3 canonical update is allowed from this experiment.",
        ],
        "expected_failure_mode": (
            "Protocol mismatch: WearGait structured gait/balance tasks versus COPS "
            "free-living wrist accelerometry. A weak or null zero-shot result is "
            "expected and publishable as transportability evidence."
        ),
        "decision_after_probe": (
            "Run full iter49 only if OSF target files can be parsed without manual "
            "label inference and raw accelerometry scale/orientation checks pass."
        ),
    }


def write_prereg() -> Path:
    ensure_dir(RESULTS_DIR)
    formula = build_formula()
    formula_sha = canonical_sha(formula)
    prereg = {
        "created_at_utc": now_utc(),
        "script": "run_t3_iter49_cops.py",
        "mode": "write_prereg",
        "formula_sha256": formula_sha,
        "formula": formula,
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"preregistration_t3_iter49_cops_{ts}.json"
    out.write_text(json.dumps(prereg, indent=2, default=str) + "\n", encoding="utf-8")
    STABLE_PREREG.write_text(json.dumps(prereg, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    print(f"Wrote {STABLE_PREREG}")
    print(f"formula_sha256={formula_sha}")
    return out


def load_prereg() -> dict[str, Any]:
    if not STABLE_PREREG.exists():
        raise FileNotFoundError(
            f"Missing {STABLE_PREREG}. Run `uv run python run_t3_iter49_cops.py --mode write_prereg` first."
        )
    prereg = json.loads(STABLE_PREREG.read_text(encoding="utf-8"))
    expected = prereg.get("formula_sha256")
    actual = canonical_sha(prereg.get("formula", {}))
    if expected != actual:
        raise RuntimeError(f"Formula SHA mismatch: expected {expected}, got {actual}")
    return prereg


def download(url: str, out: Path, expected_sha256: str | None = None, force: bool = False) -> dict[str, Any]:
    ensure_dir(out.parent)
    if force or not out.exists():
        print(f"Downloading {url} -> {out}", flush=True)
        urllib.request.urlretrieve(url, out)
    sha = sha256_file(out)
    if expected_sha256 and sha != expected_sha256:
        raise RuntimeError(f"SHA mismatch for {out}: expected {expected_sha256}, got {sha}")
    return {"path": str(out), "size_bytes": out.stat().st_size, "sha256": sha}


def inspect_zip(path: Path, max_members: int = 200) -> dict[str, Any]:
    def text_preview_from_zip(zf: zipfile.ZipFile, name: str, nbytes: int = 8000) -> str:
        return zf.read(name)[:nbytes].decode("utf-8", errors="replace")

    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        names = [info.filename for info in infos]
        suffix_counts: dict[str, int] = {}
        total_uncompressed = 0
        for info in infos:
            total_uncompressed += int(info.file_size)
            suffix = Path(info.filename).suffix.lower() or "<none>"
            suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
        updrs_like = [n for n in names if "updrs" in n.lower()]
        accel_like = [
            n
            for n in names
            if any(token in n.lower() for token in ("acc", "geneactiv", "acceler", "right", "left"))
        ]
        updrs_csv_previews: dict[str, dict[str, Any]] = {}
        for name in updrs_like:
            if not name.lower().endswith(".csv"):
                continue
            lines = text_preview_from_zip(zf, name).splitlines()
            updrs_csv_previews[name] = {
                "header": lines[0] if lines else "",
                "first_data_row": lines[1] if len(lines) > 1 else "",
                "n_preview_lines": len(lines),
            }
            if len(updrs_csv_previews) >= 4:
                break

        nested_accel_preview: dict[str, Any] | None = None
        right_inner = next((n for n in names if n.lower().endswith("rightwrist.zip")), None)
        if right_inner:
            with zipfile.ZipFile(io.BytesIO(zf.read(right_inner))) as inner:
                inner_names = inner.namelist()
                csv_name = next((n for n in inner_names if n.lower().endswith(".csv")), None)
                lines = text_preview_from_zip(inner, csv_name).splitlines() if csv_name else []
                nested_accel_preview = {
                    "inner_zip": right_inner,
                    "n_members": len(inner_names),
                    "inner_csv": csv_name,
                    "header": lines[0] if lines else "",
                    "first_data_rows": lines[1:6],
                }

        return {
            "n_members": len(infos),
            "total_uncompressed_bytes": total_uncompressed,
            "suffix_counts": suffix_counts,
            "first_members": names[:max_members],
            "updrs_like_members": updrs_like[:50],
            "accelerometry_like_members": accel_like[:50],
            "updrs_csv_previews": updrs_csv_previews,
            "nested_accelerometry_preview": nested_accel_preview,
        }


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return val if np.isfinite(val) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def cops_numeric_id(name: str) -> int:
    match = re.search(r"COPS-(\d+)", str(name))
    return int(match.group(1)) if match else 10**9


def sorted_data_zips() -> list[dict[str, Any]]:
    data_files = [file_record(item) for item in list_osf_folder(DATA_FOLDER_ID)]
    data_zips = [row for row in data_files if row["kind"] == "file" and str(row["name"]).endswith(".zip")]
    return sorted(data_zips, key=lambda row: cops_numeric_id(str(row["name"])))


def download_archives(max_subjects: int | None = None, force: bool = False) -> Path:
    """Download COPS subject ZIPs. With no max_subjects this is about 48 GB."""
    load_prereg()
    ensure_dir(COPS_DATA_DIR)
    records = sorted_data_zips()
    if max_subjects is not None:
        records = records[: int(max_subjects)]
    manifest_rows = []
    t0 = time.time()
    for i, record in enumerate(records, start=1):
        out = COPS_DATA_DIR / str(record["name"])
        print(f"[{i}/{len(records)}] {record['name']} ({int(record.get('size_bytes') or 0)/1e9:.2f} GB)", flush=True)
        dl = download(str(record["download_url"]), out, str(record["sha256"]), force=force)
        manifest_rows.append({**record, "local": dl})
    manifest = {
        "created_at_utc": now_utc(),
        "script": "run_t3_iter49_cops.py",
        "mode": "download",
        "max_subjects": max_subjects,
        "n_archives": len(manifest_rows),
        "elapsed_s": round(time.time() - t0, 2),
        "archives": manifest_rows,
    }
    out_path = RESULTS_DIR / "iter49_cops_download_manifest.json"
    out_path.write_text(json.dumps(_jsonable(manifest), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}", flush=True)
    return out_path


def _safe_float(value: Any) -> float:
    try:
        val = float(value)
        return val if np.isfinite(val) else np.nan
    except Exception:
        return np.nan


def _safe_stat(fn, x: np.ndarray) -> float:
    try:
        val = float(fn(np.asarray(x, dtype=np.float64)))
        return val if np.isfinite(val) else 0.0
    except Exception:
        return 0.0


def _row_numeric(row: pd.Series, column: str) -> float:
    if column not in row:
        return np.nan
    return _safe_float(row[column])


def segment_time_features(x: np.ndarray, fs: int = FS_FEATURE) -> dict[str, float]:
    x = np.nan_to_num(np.asarray(x, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    if len(x) < fs * MIN_SECONDS:
        return {}
    seg_len = int(WINDOW_SECONDS * fs)
    if len(x) < seg_len:
        segs = x.reshape(1, -1)
    else:
        n_seg = len(x) // seg_len
        segs = x[: n_seg * seg_len].reshape(n_seg, seg_len)
    q = np.percentile(segs, [5, 25, 50, 75, 95], axis=1)
    diffs = np.diff(segs, axis=1) * fs
    centered = segs - segs.mean(axis=1, keepdims=True)
    base = {
        "mean": segs.mean(axis=1),
        "std": segs.std(axis=1),
        "rms": np.sqrt(np.mean(segs * segs, axis=1)),
        "iqr": q[3] - q[1],
        "p05": q[0],
        "p50": q[2],
        "p95": q[4],
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
    for name, lo, hi in [("loco", 0.5, 3.0), ("trem", 3.0, 8.0), ("high", 8.0, 10.0)]:
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
        if len(vals) == 0:
            out[f"{key}_mean"] = 0.0
            out[f"{key}_std"] = 0.0
            continue
        out[f"{key}_mean"] = float(np.mean(vals))
        out[f"{key}_std"] = float(np.std(vals))
    return out


def _read_inner_accel_csv(zf: zipfile.ZipFile, inner_name: str) -> pd.DataFrame | None:
    try:
        with zipfile.ZipFile(io.BytesIO(zf.read(inner_name))) as inner:
            csv_name = next((n for n in inner.namelist() if n.lower().endswith(".csv")), None)
            if not csv_name:
                return None
            with inner.open(csv_name) as fh:
                return pd.read_csv(fh, sep=";", usecols=["X", "Y", "Z"])
    except Exception as exc:
        print(f"WARNING failed to read {inner_name}: {exc}", flush=True)
        return None


def extract_cops_side_features(zf: zipfile.ZipFile, side: str, max_hours: int | None = None) -> tuple[dict[str, float], dict[str, Any]]:
    token = f"{side.lower()}wrist.zip"
    names = sorted([n for n in zf.namelist() if n.lower().endswith(token)])
    if max_hours is not None:
        names = names[: int(max_hours)]
    chunks: list[dict[str, float]] = []
    raw_mag_means = []
    for inner_name in names:
        df = _read_inner_accel_csv(zf, inner_name)
        if df is None or len(df) < FS_NATIVE * MIN_SECONDS:
            continue
        arr = df[["X", "Y", "Z"]].to_numpy(dtype=np.float64)
        mag = np.sqrt(np.sum(arr * arr, axis=1)) * G_TO_MPS2
        raw_mag_means.append(float(np.mean(mag)))
        feats = chunk_features_from_mag(mag)
        if feats:
            chunks.append(feats)
    meta = {
        f"{side}_hours_seen": len(names),
        f"{side}_hours_used": len(chunks),
        f"{side}_raw_mag_mean_mps2": float(np.mean(raw_mag_means)) if raw_mag_means else None,
    }
    return aggregate_feature_dicts(chunks), meta


def load_cops_labels_from_zip(zf: zipfile.ZipFile) -> dict[str, Any]:
    names = zf.namelist()
    out: dict[str, Any] = {}
    for state in ("OFF", "ON"):
        name = next((n for n in names if f"UPDRS_{state}.csv" in n), None)
        if not name:
            continue
        with zf.open(name) as fh:
            df = pd.read_csv(fh, sep=";")
        if df.empty:
            continue
        row = df.iloc[0]
        out[f"updrs3_{state.lower()}"] = _row_numeric(row, "TotalScore")
        out[f"medication_state_{state.lower()}"] = _row_numeric(row, "MedicationState")
        out[f"dbs_state_{state.lower()}"] = _row_numeric(row, "DBSState")
        out[f"days_since_exam_{state.lower()}"] = _row_numeric(row, "DaysSinceExamination")
    if np.isfinite(out.get("updrs3_off", np.nan)) and np.isfinite(out.get("updrs3_on", np.nan)):
        out["updrs3_off_on_mean"] = float((out["updrs3_off"] + out["updrs3_on"]) / 2.0)
    else:
        out["updrs3_off_on_mean"] = np.nan
    return out


def load_cops_demographics() -> pd.DataFrame:
    path = COPS_DATA_DIR / "Demographics.csv"
    if not path.exists():
        download(DEMOGRAPHICS_URL, path, DEMOGRAPHICS_SHA256, force=False)
    df = pd.read_csv(path, sep=";")
    df["sid"] = df["ID"].astype(str)
    df["hy"] = pd.to_numeric(df["PD_HoehnAndYahr"], errors="coerce")
    df["cv_yrs"] = pd.to_numeric(df["PD_YearsSinceDiagnosis"], errors="coerce")
    # Match WearGait `cv_sex`: raw clinical inspection shows Male=1, Female=0.
    df["cv_sex"] = df["Sex"].astype(str).str.lower().map({"male": 1.0, "female": 0.0})
    df["cv_dbs"] = df["DBS"].astype(str).str.lower().map({"no": 0.0, "yes": 1.0})
    return df


def local_archive_paths(max_subjects: int | None = None) -> list[Path]:
    paths = sorted(COPS_DATA_DIR.glob("COPS-*.zip"), key=lambda p: cops_numeric_id(p.name))
    if max_subjects is not None:
        paths = paths[: int(max_subjects)]
    return paths


def extract_cops_features(max_subjects: int | None = None, max_hours_per_side: int | None = None, force: bool = False) -> Path:
    load_prereg()
    demo = load_cops_demographics()
    demo_by_sid = demo.set_index("sid")
    paths = local_archive_paths(max_subjects=max_subjects)
    if not paths:
        raise FileNotFoundError(f"No COPS subject ZIPs found in {COPS_DATA_DIR}; run --mode download first.")
    rows = []
    t0 = time.time()
    for i, path in enumerate(paths, start=1):
        sid = path.stem
        print(f"[extract {i}/{len(paths)}] {sid}", flush=True)
        with zipfile.ZipFile(path) as zf:
            labels = load_cops_labels_from_zip(zf)
            right_feats, right_meta = extract_cops_side_features(zf, "right", max_hours=max_hours_per_side)
            left_feats, left_meta = extract_cops_side_features(zf, "left", max_hours=max_hours_per_side)
        base: dict[str, Any] = {"sid": sid, "archive": str(path)}
        if sid in demo_by_sid.index:
            d = demo_by_sid.loc[sid]
            base.update(
                {
                    "hy": _safe_float(d["hy"]),
                    "cv_yrs": _safe_float(d["cv_yrs"]),
                    "cv_sex": _safe_float(d["cv_sex"]),
                    "cv_dbs": _safe_float(d["cv_dbs"]),
                    "age": _safe_float(d.get("Age", np.nan)),
                    "sex_raw": d.get("Sex"),
                    "dbs_raw": d.get("DBS"),
                }
            )
        base.update(labels)
        base.update(right_meta)
        base.update(left_meta)
        for key, val in right_feats.items():
            base[f"right_{key}"] = val
        for key, val in left_feats.items():
            base[f"left_{key}"] = val
        rows.append(base)
    df = pd.DataFrame(rows)
    suffix = "smoke" if max_subjects is not None or max_hours_per_side is not None else "full"
    out = RESULTS_DIR / f"iter49_cops_features_{suffix}.csv"
    df.to_csv(out, index=False)
    manifest = {
        "created_at_utc": now_utc(),
        "script": "run_t3_iter49_cops.py",
        "mode": "extract",
        "max_subjects": max_subjects,
        "max_hours_per_side": max_hours_per_side,
        "n_rows": int(len(df)),
        "elapsed_s": round(time.time() - t0, 2),
        "output_csv": str(out),
        "output_sha256": sha256_file(out),
        "labels_used": ["UPDRS_OFF", "UPDRS_ON"],
        "leakage_status": "external_dataset_feature_cache_not_for_internal_headline",
    }
    man_path = Path(str(out) + ".manifest.json")
    man_path.write_text(json.dumps(_jsonable(manifest), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}", flush=True)
    print(f"Wrote {man_path}", flush=True)
    return out


def extract_weargait_magnitude_features(sids: np.ndarray, side: str = "R") -> pd.DataFrame:
    pd_dir = DATA_DIR / "PD PARTICIPANTS" / "CSV files"
    rows = []
    side_prefix = "R_Wrist" if side.upper().startswith("R") else "L_Wrist"
    cols = [f"{side_prefix}_Acc_X", f"{side_prefix}_Acc_Y", f"{side_prefix}_Acc_Z"]
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
            row["weargait_n_task_chunks"] = float(len(chunks))
            rows.append(row)
    if not rows:
        raise RuntimeError(f"No WearGait magnitude features extracted from {pd_dir}")
    return pd.DataFrame(rows)


def build_stage1_matrix(hy: np.ndarray, cv_yrs: np.ndarray, cv_sex: np.ndarray, cv_dbs: np.ndarray) -> np.ndarray:
    from run_t3_iter3 import get_hy_features

    return np.column_stack([get_hy_features(hy), cv_yrs, cv_sex, cv_dbs])


def fit_stage1(X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    imp = FoldImputer.fit(X_train)
    Xtr_i = imp.transform(X_train)
    Xte_i = imp.transform(X_test)
    Xtr_i = np.nan_to_num(Xtr_i, nan=0.0, posinf=0.0, neginf=0.0)
    Xte_i = np.nan_to_num(Xte_i, nan=0.0, posinf=0.0, neginf=0.0)
    nrm = FoldNormalizer.fit(Xtr_i)
    Xtr = nrm.transform(Xtr_i)
    Xte = nrm.transform(Xte_i)
    model = Ridge(alpha=1.0, fit_intercept=True)
    model.fit(Xtr, y_train)
    return model.predict(Xtr), model.predict(Xte)


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


def bootstrap_metric(y_true: np.ndarray, y_pred: np.ndarray, n_boot: int = 5000, seed: int = 20260508) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    vals = []
    n = len(y_true)
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        vals.append(ccc_fn(y_true[idx], y_pred[idx]))
    arr = np.asarray(vals, dtype=np.float64)
    return {
        "n_boot": int(n_boot),
        "ccc_ci95": [round(float(np.percentile(arr, 2.5)), 4), round(float(np.percentile(arr, 97.5)), 4)],
        "ccc_frac_gt_0": round(float(np.mean(arr > 0)), 4),
        "ccc_frac_gt_02": round(float(np.mean(arr > 0.2)), 4),
        "ccc_frac_gt_035": round(float(np.mean(arr > 0.35)), 4),
    }


def target_metrics(y_map: dict[str, np.ndarray], pred_map: dict[str, np.ndarray], n_boot: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for target_name, y in y_map.items():
        out[target_name] = {
            pred_name: {
                **metrics(y[np.isfinite(y) & np.isfinite(pred)], pred[np.isfinite(y) & np.isfinite(pred)]),
                **bootstrap_metric(y[np.isfinite(y) & np.isfinite(pred)], pred[np.isfinite(y) & np.isfinite(pred)], n_boot=n_boot),
            }
            for pred_name, pred in pred_map.items()
            if int((np.isfinite(y) & np.isfinite(pred)).sum()) >= 3
        }
    return out


def run_zero_shot(
    features_csv: Path | None = None,
    smoke: bool = False,
    n_boot: int = 5000,
) -> Path:
    prereg = load_prereg()
    from run_t3_iter2 import train_lgb
    from run_t3_iter5_clinical import load_clinical_dict
    from run_t3_iter47_invalid_code_fix import filter_cohort

    if features_csv is None:
        features_csv = RESULTS_DIR / ("iter49_cops_features_smoke.csv" if smoke else "iter49_cops_features_full.csv")
    if not features_csv.exists():
        raise FileNotFoundError(f"Missing {features_csv}; run --mode extract first.")

    cops_all = pd.read_csv(features_csv)
    cops = cops_all.dropna(subset=["updrs3_off", "hy", "cv_yrs", "cv_sex", "cv_dbs"]).reset_index(drop=True)
    if len(cops) < 10 and not smoke:
        raise RuntimeError(f"Only {len(cops)} COPS rows with OFF labels and clinical covariates.")

    wg_data = filter_cohort("drop_allmissing_validrange")
    wg_feat = extract_weargait_magnitude_features(wg_data["sids"], side="R")
    wg = pd.DataFrame({"sid": wg_data["sids"], "updrs3": wg_data["y_t3"], "hy": wg_data["hy"]})
    clinical = load_clinical_dict(wg_data["sids"])
    wg["cv_yrs"] = clinical["cv_yrs"]
    wg["cv_sex"] = clinical["cv_sex"]
    wg["cv_dbs"] = clinical["cv_dbs"]
    wg = wg.merge(wg_feat, on="sid", how="inner").reset_index(drop=True)

    base_feature_cols = sorted([c for c in wg_feat.columns if c.startswith("mag_")])
    right_cols = [f"right_{c}" for c in base_feature_cols]
    left_cols = [f"left_{c}" for c in base_feature_cols]
    missing_right = [c for c in right_cols if c not in cops.columns]
    missing_left = [c for c in left_cols if c not in cops.columns]
    if missing_right:
        raise RuntimeError(f"Missing COPS right feature columns: {missing_right[:5]}")

    Xwg = wg[base_feature_cols].to_numpy(dtype=np.float64)
    Xright = cops[right_cols].to_numpy(dtype=np.float64)
    Xleft = cops[left_cols].to_numpy(dtype=np.float64) if not missing_left else None
    y_train = wg["updrs3"].to_numpy(dtype=np.float64)
    Xwg_n, Xright_n = clean_train_test(Xwg, Xright)
    Xleft_n = clean_train_test(Xwg, Xleft)[1] if Xleft is not None else None

    pred_a_seed = []
    pred_a_left_seed = []
    for seed in SEEDS:
        pred_a_seed.append(train_lgb(Xwg_n, y_train, Xright_n, seed))
        if Xleft_n is not None:
            pred_a_left_seed.append(train_lgb(Xwg_n, y_train, Xleft_n, seed))
    pred_a_right = np.mean(np.stack(pred_a_seed, axis=0), axis=0)
    pred_a_left = np.mean(np.stack(pred_a_left_seed, axis=0), axis=0) if pred_a_left_seed else np.full(len(cops), np.nan)
    pred_a_bilateral = np.nanmean(np.column_stack([pred_a_right, pred_a_left]), axis=1)

    Xs1_wg = build_stage1_matrix(
        wg["hy"].to_numpy(dtype=np.float64),
        wg["cv_yrs"].to_numpy(dtype=np.float64),
        wg["cv_sex"].to_numpy(dtype=np.float64),
        wg["cv_dbs"].to_numpy(dtype=np.float64),
    )
    Xs1_cops = build_stage1_matrix(
        cops["hy"].to_numpy(dtype=np.float64),
        cops["cv_yrs"].to_numpy(dtype=np.float64),
        cops["cv_sex"].to_numpy(dtype=np.float64),
        cops["cv_dbs"].to_numpy(dtype=np.float64),
    )
    s1_wg, s1_cops = fit_stage1(Xs1_wg, y_train, Xs1_cops)
    resid = y_train - s1_wg
    pred_b_seed = []
    pred_b_left_seed = []
    for seed in SEEDS:
        pred_b_seed.append(s1_cops + train_lgb(Xwg_n, resid, Xright_n, seed))
        if Xleft_n is not None:
            pred_b_left_seed.append(s1_cops + train_lgb(Xwg_n, resid, Xleft_n, seed))
    pred_b_right = np.mean(np.stack(pred_b_seed, axis=0), axis=0)
    pred_b_left = np.mean(np.stack(pred_b_left_seed, axis=0), axis=0) if pred_b_left_seed else np.full(len(cops), np.nan)
    pred_b_bilateral = np.nanmean(np.column_stack([pred_b_right, pred_b_left]), axis=1)

    # Track C: within-COPS sanity. Ridge is intentionally conservative at N≈64.
    y_off = cops["updrs3_off"].to_numpy(dtype=np.float64)
    Xc = np.column_stack([Xright, Xs1_cops])
    pred_c = np.full(len(cops), np.nan, dtype=np.float64)
    if len(cops) >= 3:
        for tr, te in LeaveOneOut().split(Xc):
            Xtr, Xte = clean_train_test(Xc[tr], Xc[te])
            model = Ridge(alpha=10.0, fit_intercept=True)
            model.fit(Xtr, y_off[tr])
            pred_c[te] = model.predict(Xte)

    y_map = {
        "off_primary": y_off,
        "on_sensitivity": cops["updrs3_on"].to_numpy(dtype=np.float64),
        "off_on_mean_sensitivity": cops["updrs3_off_on_mean"].to_numpy(dtype=np.float64),
    }
    pred_map = {
        "track_a_right_wrist_direct": pred_a_right,
        "track_a_left_wrist_sensitivity": pred_a_left,
        "track_d_bilateral_direct": pred_a_bilateral,
        "track_b_right_clinical_plus_wrist": pred_b_right,
        "track_b_left_clinical_plus_wrist_sensitivity": pred_b_left,
        "track_d_bilateral_clinical_plus_wrist": pred_b_bilateral,
        "track_c_cops_only_loo_sanity": pred_c,
    }

    rows = cops[
        [
            "sid",
            "updrs3_off",
            "updrs3_on",
            "updrs3_off_on_mean",
            "hy",
            "cv_yrs",
            "cv_sex",
            "cv_dbs",
            "right_hours_used",
            "left_hours_used",
            "right_raw_mag_mean_mps2",
            "left_raw_mag_mean_mps2",
        ]
    ].copy()
    for name, pred in pred_map.items():
        rows[name] = pred

    suffix = "smoke" if smoke else datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rows_path = RESULTS_DIR / f"iter49_cops_zeroshot_rows_{suffix}.csv"
    result_path = RESULTS_DIR / f"iter49_cops_zeroshot_{suffix}.json"
    rows.to_csv(rows_path, index=False)
    result = {
        "created_at_utc": now_utc(),
        "script": "run_t3_iter49_cops.py",
        "mode": "run_smoke" if smoke else "run",
        "preregistration_formula_sha256": prereg.get("formula_sha256"),
        "features_csv": str(features_csv),
        "rows_csv": str(rows_path),
        "n_weargait_train": int(len(wg)),
        "n_cops_rows_total": int(len(cops_all)),
        "n_cops_off_labeled": int(len(cops)),
        "n_common_magnitude_features": int(len(base_feature_cols)),
        "weargait_tasks": list(WEARGAIT_TASKS),
        "feature_policy": {
            "native_fs_hz": FS_NATIVE,
            "feature_fs_hz": FS_FEATURE,
            "downsample_stride": DOWNSAMPLE_STRIDE,
            "window_seconds": WINDOW_SECONDS,
            "weargait_sensor": "R_Wrist_Acc_X/Y/Z",
            "cops_sensor": "GENEActiv X/Y/Z converted from g to m/s^2",
            "axis_policy": "magnitude_only_frame_invariant",
        },
        "scale_checks": {
            "weargait_mag_feature_source": "raw R_Wrist_Acc magnitude",
            "cops_right_raw_mag_mean_mps2_mean": _safe_stat(np.nanmean, cops["right_raw_mag_mean_mps2"].to_numpy(dtype=np.float64)),
            "cops_left_raw_mag_mean_mps2_mean": _safe_stat(np.nanmean, cops["left_raw_mag_mean_mps2"].to_numpy(dtype=np.float64)),
            "cops_right_hours_used_mean": _safe_stat(np.nanmean, cops["right_hours_used"].to_numpy(dtype=np.float64)),
            "cops_left_hours_used_mean": _safe_stat(np.nanmean, cops["left_hours_used"].to_numpy(dtype=np.float64)),
        },
        "metrics": target_metrics(y_map, pred_map, n_boot=n_boot),
        "decision": "external_zero_shot_only_no_internal_t3_canonical_change",
    }
    result_path.write_text(json.dumps(_jsonable(result), indent=2) + "\n", encoding="utf-8")
    stable = RESULTS_DIR / "iter49_cops_zeroshot.json"
    if not smoke:
        stable.write_text(json.dumps(_jsonable(result), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(_jsonable({"n_cops": len(cops), "metrics": result["metrics"].get("off_primary", {})}), indent=2), flush=True)
    print(f"Wrote {result_path}", flush=True)
    print(f"Wrote {rows_path}", flush=True)
    return result_path


def run_probe(sample_smallest: bool = False, force: bool = False) -> Path:
    prereg = load_prereg()
    ensure_dir(RESULTS_DIR)
    ensure_dir(COPS_DATA_DIR)

    root_files = [file_record(item) for item in list_osf_folder()]
    data_files = [file_record(item) for item in list_osf_folder(DATA_FOLDER_ID)]
    script_files = [file_record(item) for item in list_osf_folder(SCRIPTS_MATLAB_FOLDER_ID)]
    data_zips = [row for row in data_files if row["kind"] == "file" and str(row["name"]).endswith(".zip")]
    data_zips_sorted = sorted(data_zips, key=lambda row: row.get("size_bytes") or 10**18)

    demographics = download(DEMOGRAPHICS_URL, COPS_DATA_DIR / "Demographics.csv", DEMOGRAPHICS_SHA256, force=force)
    demo_df = pd.read_csv(COPS_DATA_DIR / "Demographics.csv", sep=";")

    sample_zip_info: dict[str, Any] | None = None
    if sample_smallest:
        smallest = data_zips_sorted[0]
        zip_path = COPS_DATA_DIR / str(smallest["name"])
        sample_dl = download(str(smallest["download_url"]), zip_path, str(smallest["sha256"]), force=force)
        sample_zip_info = {
            "source_record": smallest,
            "download": sample_dl,
            "zip_listing": inspect_zip(zip_path),
        }

    payload = {
        "created_at_utc": now_utc(),
        "script": "run_t3_iter49_cops.py",
        "mode": "probe",
        "preregistration_formula_sha256": prereg.get("formula_sha256"),
        "web_sources": {
            "scientific_data": "https://www.nature.com/articles/s41597-026-06999-6",
            "osf": "https://osf.io/5xvwn/",
            "brainpatch_summary": "https://brainpatch.ai/blog/post/open-dataset-links-hourly-symptom-diaries-with-bilateral-e3b68cf6/237",
        },
        "root_files": root_files,
        "data_summary": {
            "n_data_files": len(data_files),
            "n_zip_files": len(data_zips),
            "total_zip_size_bytes": sum(int(row.get("size_bytes") or 0) for row in data_zips),
            "smallest_zip_files": data_zips_sorted[:5],
            "largest_zip_files": sorted(data_zips, key=lambda row: row.get("size_bytes") or 0)[-5:],
        },
        "script_files": script_files,
        "demographics": {
            "download": demographics,
            "n_rows": int(len(demo_df)),
            "columns": list(demo_df.columns),
            "pd_hoehn_yahr_counts": demo_df["PD_HoehnAndYahr"].value_counts(dropna=False).sort_index().to_dict()
            if "PD_HoehnAndYahr" in demo_df.columns
            else {},
            "dbs_counts": demo_df["DBS"].value_counts(dropna=False).to_dict() if "DBS" in demo_df.columns else {},
            "example_rows": demo_df.head(5).to_dict(orient="records"),
        },
        "sample_zip": sample_zip_info,
        "decision": {
            "cops_is_new_external_route": True,
            "recommended_next_step": (
                "Implement full iter49 zero-shot only after confirming UPDRS OFF/ON "
                "CSV names inside subject archives and raw accelerometry schema."
            ),
            "not_an_internal_t3_update": True,
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter49_cops_probe_{ts}.json"
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    stable = RESULTS_DIR / "iter49_cops_probe.json"
    stable.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    print(f"Wrote {stable}")
    print(
        "COPS data zips={n} total_gb={gb:.2f} demographics_rows={rows}".format(
            n=len(data_zips),
            gb=payload["data_summary"]["total_zip_size_bytes"] / 1e9,
            rows=len(demo_df),
        )
    )
    if sample_zip_info:
        print(
            "Sample {name}: members={members} updrs_like={updrs}".format(
                name=sample_zip_info["source_record"]["name"],
                members=sample_zip_info["zip_listing"]["n_members"],
                updrs=len(sample_zip_info["zip_listing"]["updrs_like_members"]),
            )
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["write_prereg", "probe", "download", "extract", "run"], required=True)
    parser.add_argument("--sample-smallest", action="store_true", help="Download and inspect the smallest subject ZIP.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-subjects", type=int, default=None, help="Limit subject archives for smoke tests.")
    parser.add_argument("--max-hours-per-side", type=int, default=None, help="Limit COPS hourly wrist files per side for smoke tests.")
    parser.add_argument("--features-csv", type=Path, default=None)
    parser.add_argument("--smoke", action="store_true", help="Write smoke outputs and do not update stable result.")
    parser.add_argument("--n-boot", type=int, default=5000)
    args = parser.parse_args()

    if args.mode == "write_prereg":
        write_prereg()
    elif args.mode == "probe":
        run_probe(sample_smallest=args.sample_smallest, force=args.force)
    elif args.mode == "download":
        download_archives(max_subjects=args.max_subjects, force=args.force)
    elif args.mode == "extract":
        extract_cops_features(
            max_subjects=args.max_subjects,
            max_hours_per_side=args.max_hours_per_side,
            force=args.force,
        )
    elif args.mode == "run":
        run_zero_shot(features_csv=args.features_csv, smoke=args.smoke, n_boot=args.n_boot)


if __name__ == "__main__":
    main()
