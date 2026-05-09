#!/usr/bin/env python3
"""T3 iter52 — PDFE turning-in-place external zero-shot validation.

PDFE / Figshare 14984667 is public and contains shank IMU trials plus
session-level UPDRS-III totals for 35 PD subjects with freezing of gait. This is
external-validity evidence only: results from this script cannot update the
internal WearGait-PD T3 canonical.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

from inductive_lib import FoldImputer, FoldNormalizer, cal_slope, ccc as ccc_fn, mae as mae_fn, pearson_r
from project_paths import REPO_ROOT, RESULTS_DIR, ensure_dir
from run_t3_iter2 import train_lgb
from run_t3_iter3 import get_hy_features
from run_t3_iter47_invalid_code_fix import filter_cohort
from run_t3_iter51_tlvmc_defog import (
    G_TO_MPS2,
    aggregate_feature_dicts,
    chunk_features_from_mag,
    weargait_magnitude_features,
)


PDFE_DIR = REPO_ROOT / "data" / "raw" / "pdfe_turning"
IMU_ZIP = PDFE_DIR / "IMU.zip"
META_CSV = PDFE_DIR / "PDFEinfo.csv"
FEATURE_CSV = RESULTS_DIR / "iter52_pdfe_turning_features.csv"
STABLE_PREREG = RESULTS_DIR / "preregistration_t3_iter52_pdfe_turning_zeroshot.json"
STABLE_RESULT = RESULTS_DIR / "iter52_pdfe_turning_zeroshot.json"
FIGSHARE_ARTICLE = "14984667"
IMU_URL = "https://ndownloader.figshare.com/files/33413717"
META_URL = "https://ndownloader.figshare.com/files/31544582"
SEEDS = (42, 1337, 7)


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        return "unknown"


def canonical_sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def formula() -> dict[str, Any]:
    return {
        "experiment": "T3 iter52 PDFE turning-in-place external zero-shot validation",
        "dataset": {
            "name": "PDFE turning-in-place / Figshare 14984667",
            "article_url": "https://www.frontiersin.org/articles/10.3389/fnins.2022.832463/full",
            "figshare_url": "https://figshare.com/articles/dataset/14984667",
            "license": "CC BY 4.0 per Figshare API",
        },
        "primary_rows": "one row per PDFE subject: trial/session 1 only, target = Session 1 UPDRS-III",
        "feature_schema": (
            "frame-invariant acceleration-magnitude summary features from PDFE most-affected-side "
            "shank IMU; WearGait train features are bilateral average of L/R lateral-shank "
            "acceleration-magnitude summaries across TUG, SelfPace, and HurriedPace"
        ),
        "tracks": {
            "A_primary": "WearGait corrected T3 train only: LGB direct T3 on shank magnitude features -> PDFE session-1 UPDRS-III",
            "B_sensitivity": "WearGait corrected T3 train only: Ridge(H&Y + years + sex) + LGB shank residual -> PDFE",
            "C_sanity": "PDFE-only LOOCV Ridge on clinical + shank features, reported only as within-cohort sanity",
        },
        "seeds": list(SEEDS),
        "leakage_rules": [
            "PDFE labels never enter WearGait-trained Tracks A/B before scoring.",
            "Track C is within-PDFE sanity only and not a zero-shot transportability claim.",
            "No internal WearGait-PD T3 canonical update is allowed from any iter52 outcome.",
        ],
    }


def verify_preregistration() -> dict[str, Any]:
    f = formula()
    expected = canonical_sha(f)
    if not STABLE_PREREG.exists():
        raise FileNotFoundError(f"Missing preregistration: {STABLE_PREREG}")
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
    STABLE_PREREG.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md = STABLE_PREREG.with_suffix(".md")
    md.write_text(
        "# T3 iter52 PDFE Turning-In-Place Preregistration\n\n"
        f"- Formula SHA256: `{payload['formula_sha256']}`\n"
        "- Primary claim: external zero-shot transportability only.\n"
        "- Internal T3 canonical update: forbidden under all outcomes.\n",
        encoding="utf-8",
    )
    print(f"Wrote {STABLE_PREREG}\nWrote {md}", flush=True)
    return STABLE_PREREG


def download(force: bool = False) -> Path:
    verify_preregistration()
    PDFE_DIR.mkdir(parents=True, exist_ok=True)
    for url, path in [(META_URL, META_CSV), (IMU_URL, IMU_ZIP)]:
        if force or not path.exists():
            print(f"Downloading {url} -> {path}", flush=True)
            urllib.request.urlretrieve(url, path)
    with zipfile.ZipFile(IMU_ZIP) as zf:
        files = zf.infolist()
    manifest = {
        "created_at_utc": now_utc(),
        "script": Path(__file__).name,
        "mode": "download",
        "figshare_article": FIGSHARE_ARTICLE,
        "metadata_csv": str(META_CSV),
        "metadata_sha256": sha256_file(META_CSV),
        "imu_zip": str(IMU_ZIP),
        "imu_zip_sha256": sha256_file(IMU_ZIP),
        "n_zip_entries": len(files),
        "zip_total_uncompressed_bytes": int(sum(i.file_size for i in files)),
    }
    out = RESULTS_DIR / "iter52_pdfe_turning_download_manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}", flush=True)
    return out


def read_metadata() -> list[dict[str, str]]:
    if not META_CSV.exists():
        raise FileNotFoundError(f"Missing {META_CSV}; run --mode download first")
    with META_CSV.open(encoding="latin1", newline="") as f:
        return list(csv.DictReader(f, delimiter=";", quotechar='"'))


def _float_cell(row: dict[str, str], col: str) -> float:
    val = str(row.get(col, "")).strip().replace(",", ".")
    if not val or val == "-":
        return float("nan")
    return float(val)


def _sex_to_float(v: str) -> float:
    s = str(v).strip().upper()
    if s.startswith("M"):
        return 1.0
    if s.startswith("F"):
        return 0.0
    return float("nan")


def pdfe_trial_features(zf: zipfile.ZipFile, subject_num: int, trial: int = 1) -> tuple[dict[str, float], dict[str, Any]]:
    name = f"IMU/SUB{subject_num:02d}_{trial}.txt"
    if name not in zf.namelist():
        raise FileNotFoundError(name)
    with zf.open(name) as f:
        df = pd.read_csv(f, sep="\t")
    cols = ["ACC ML [g]", "ACC AP [g]", "ACC SI [g]"]
    arr = df[cols].to_numpy(dtype=np.float64) * G_TO_MPS2
    mag = np.sqrt(np.sum(arr * arr, axis=1))
    feats = aggregate_feature_dicts([chunk_features_from_mag(mag)])
    meta = {
        "raw_file": name,
        "rows": int(len(df)),
        "fs_hz": 128,
        "mag_mean_mps2": float(np.mean(mag)),
        "mag_median_mps2": float(np.median(mag)),
    }
    return feats, meta


def extract_features(force: bool = False) -> Path:
    verify_preregistration()
    if FEATURE_CSV.exists() and not force:
        print(f"Using existing {FEATURE_CSV}", flush=True)
        return FEATURE_CSV
    if not IMU_ZIP.exists() or not META_CSV.exists():
        download(force=False)
    rows = []
    meta_rows = read_metadata()
    with zipfile.ZipFile(IMU_ZIP) as zf:
        for row in meta_rows:
            sid = str(row["ID"]).strip()
            if not sid.startswith("PDFE"):
                continue
            subject_num = int(sid.replace("PDFE", ""))
            target = _float_cell(row, "Session 1 - UPDRS-III (score)")
            if not np.isfinite(target):
                continue
            feats, raw_meta = pdfe_trial_features(zf, subject_num, trial=1)
            out: dict[str, Any] = {
                "subject": sid,
                "trial": 1,
                "target_updrs3": target,
                "hy": _float_cell(row, "Session 1 - H&Y (score)"),
                "years_since_dx": _float_cell(row, "Disease duration (years)"),
                "sex": _sex_to_float(row.get("Gender", "")),
                "n_sessions_available": _float_cell(row, "sessions #"),
                "more_affected_side": str(row.get("More affected side", "")).strip(),
                "nfogq": _float_cell(row, "Session 1 - \nNFoG-Q (score)"),
                "n_fog_episodes": _float_cell(row, "Session 1 - numbers of FoG episodes (n)"),
            }
            out.update({f"raw_{k}": v for k, v in raw_meta.items()})
            out.update(feats)
            rows.append(out)
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No PDFE features extracted.")
    df.to_csv(FEATURE_CSV, index=False)
    manifest = {
        "script": Path(__file__).name,
        "created_at_utc": now_utc(),
        "command": "run_t3_iter52_pdfe_turning.py --mode extract",
        "data_sha256": sha256_file(FEATURE_CSV),
        "labels_used": "Session 1 UPDRS-III only for external scoring and Track C sanity",
        "fold_scope": "External zero-shot Tracks A/B train on WearGait only; Track C uses PDFE LOOCV.",
        "cohort_statistics_used": "PDFE feature aggregation per subject/trial; no target-derived statistics.",
        "normalization_scope": "WearGait train-only for Tracks A/B; PDFE fold-train-only for Track C.",
        "leakage_status": "external_dataset_feature_cache_not_for_internal_headline",
        "leakage_rationale": "External labels never enter WearGait training for zero-shot tracks.",
        "n_rows": int(len(df)),
        "n_subjects": int(df["subject"].nunique()),
        "target_summary": {
            "mean": float(df["target_updrs3"].mean()),
            "min": float(df["target_updrs3"].min()),
            "max": float(df["target_updrs3"].max()),
        },
    }
    (FEATURE_CSV.with_suffix(FEATURE_CSV.suffix + ".manifest.json")).write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {FEATURE_CSV}", flush=True)
    return FEATURE_CSV


def metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    return {
        "ccc": float(ccc_fn(y, pred)),
        "mae": float(mae_fn(y, pred)),
        "r": float(pearson_r(y, pred)),
        "cal_slope": float(cal_slope(y, pred)),
        "y_mean": float(np.mean(y)),
        "pred_mean": float(np.mean(pred)),
        "y_sd": float(np.std(y)),
        "pred_sd": float(np.std(pred)),
    }


def ccc_ci(y: np.ndarray, pred: np.ndarray, n_boot: int = 5000, seed: int = 20260509) -> dict[str, float]:
    rng = np.random.RandomState(seed)
    vals = []
    n = len(y)
    for _ in range(n_boot):
        idx = rng.randint(0, n, size=n)
        vals.append(float(ccc_fn(y[idx], pred[idx])))
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


def bilateral_shank_weargait_features(sids: np.ndarray) -> pd.DataFrame:
    left = weargait_magnitude_features(sids, "L_LatShank").set_index("sid")
    right = weargait_magnitude_features(sids, "R_LatShank").set_index("sid")
    common = sorted(set(left.columns) & set(right.columns))
    common = [c for c in common if not c.endswith("_n_task_chunks")]
    avg = (left[common].astype(float) + right[common].astype(float)) / 2.0
    avg["sid"] = avg.index
    avg["bilateral_shank_source"] = "mean_L_R_LatShank"
    return avg.reset_index(drop=True)


def clinical_matrix_weargait(data: dict[str, Any], sids_used: list[str]) -> np.ndarray:
    sid_to_pos = {str(s): i for i, s in enumerate(data["sids"])}
    pos = np.asarray([sid_to_pos[s] for s in sids_used], dtype=int)
    feat_cols = list(data["feat_cols"])
    X = data["X"]
    cv_yrs = X[pos, feat_cols.index("cv_yrs")] if "cv_yrs" in feat_cols else np.full(len(pos), np.nan)
    cv_sex = X[pos, feat_cols.index("cv_sex")] if "cv_sex" in feat_cols else np.full(len(pos), np.nan)
    return np.column_stack([get_hy_features(np.asarray(data["hy"])[pos]), cv_yrs, cv_sex])


def clinical_matrix_pdfe(df: pd.DataFrame) -> np.ndarray:
    return np.column_stack(
        [
            get_hy_features(df["hy"].to_numpy(dtype=float)),
            df["years_since_dx"].to_numpy(dtype=float),
            df["sex"].to_numpy(dtype=float),
        ]
    )


def fit_stage1_ridge(Xwg_c: np.ndarray, ywg: np.ndarray, Xpdfe_c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    Xtr, Xte = transform_train_external(Xwg_c, Xpdfe_c)
    model = Ridge(alpha=1.0)
    model.fit(Xtr, ywg)
    return model.predict(Xtr), model.predict(Xte)


def fit_lgb_external(Xwg: np.ndarray, ywg: np.ndarray, Xpdfe: np.ndarray) -> np.ndarray:
    preds = []
    Xtr, Xte = transform_train_external(Xwg, Xpdfe)
    for seed in SEEDS:
        preds.append(train_lgb(Xtr, ywg, Xte, seed=seed))
    return np.mean(np.vstack(preds), axis=0)


def pdfe_loocv_ridge(df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
    y = df["target_updrs3"].to_numpy(dtype=float)
    Xf = df[feature_cols].to_numpy(dtype=float)
    Xc = clinical_matrix_pdfe(df)
    X = np.column_stack([Xc, Xf])
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
    pdfe = pd.read_csv(FEATURE_CSV)
    data = filter_cohort("drop_allmissing_validrange")
    wg_feat = bilateral_shank_weargait_features(data["sids"])
    wg = pd.DataFrame({"sid": [str(s) for s in data["sids"]], "target": data["y_t3"]}).merge(wg_feat, on="sid", how="inner")
    sid_to_target = dict(zip([str(s) for s in data["sids"]], data["y_t3"]))
    wg["target"] = wg["sid"].map(sid_to_target).astype(float)
    feature_cols = sorted(c for c in set(wg.columns) & set(pdfe.columns) if c.startswith("mag_") or c.startswith("meta_"))
    if len(feature_cols) < 20:
        raise RuntimeError(f"Too few common feature columns: {len(feature_cols)}")

    Xwg = wg[feature_cols].to_numpy(dtype=float)
    ywg = wg["target"].to_numpy(dtype=float)
    Xpdfe = pdfe[feature_cols].to_numpy(dtype=float)
    ypdfe = pdfe["target_updrs3"].to_numpy(dtype=float)

    track_a = fit_lgb_external(Xwg, ywg, Xpdfe)

    Xwg_c = clinical_matrix_weargait(data, wg["sid"].tolist())
    Xpdfe_c = clinical_matrix_pdfe(pdfe)
    s1_wg, s1_pdfe = fit_stage1_ridge(Xwg_c, ywg, Xpdfe_c)
    residual_pred = fit_lgb_external(Xwg, ywg - s1_wg, Xpdfe)
    track_b = s1_pdfe + residual_pred

    track_c = pdfe_loocv_ridge(pdfe, feature_cols)

    rng = np.random.RandomState(20260509)
    shuffled = np.array(ywg, copy=True)
    rng.shuffle(shuffled)
    track_a_shuffle = fit_lgb_external(Xwg, shuffled, Xpdfe)

    result = {
        "experiment": "T3 iter52 PDFE turning-in-place external zero-shot validation",
        "created_at_utc": now_utc(),
        "git_sha": git_sha(),
        "formula_sha256": canonical_sha(formula()),
        "n_weargait_train": int(len(wg)),
        "n_pdfe": int(len(pdfe)),
        "n_common_magnitude_features": int(len(feature_cols)),
        "feature_cols": feature_cols,
        "feature_csv": str(FEATURE_CSV),
        "tracks": {
            "track_a_primary_wg_shank_to_pdfe": {
                **metrics(ypdfe, track_a),
                "ccc_bootstrap": ccc_ci(ypdfe, track_a, n_boot=n_boot),
            },
            "track_b_clinical_plus_shank": {
                **metrics(ypdfe, track_b),
                "ccc_bootstrap": ccc_ci(ypdfe, track_b, n_boot=n_boot),
            },
            "track_c_pdfe_only_loocv_sanity": {
                **metrics(ypdfe, track_c),
                "ccc_bootstrap": ccc_ci(ypdfe, track_c, n_boot=n_boot),
            },
            "null_track_a_wg_target_shuffle": metrics(ypdfe, track_a_shuffle),
        },
        "policy": {
            "internal_t3_canonical_update_allowed": False,
            "interpretation": "external transportability / protocol-mismatch evidence only",
        },
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter52_pdfe_turning_zeroshot_{ts}.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    STABLE_RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    rows = pd.DataFrame(
        {
            "subject": pdfe["subject"],
            "y_true": ypdfe,
            "track_a_pred": track_a,
            "track_b_pred": track_b,
            "track_c_pred": track_c,
            "null_track_a_shuffle_pred": track_a_shuffle,
        }
    )
    rows_out = RESULTS_DIR / f"iter52_pdfe_turning_zeroshot_rows_{ts}.csv"
    rows.to_csv(rows_out, index=False)
    print(json.dumps({k: v for k, v in result["tracks"].items()}, indent=2), flush=True)
    print(f"Wrote {out}\nWrote {STABLE_RESULT}\nWrote {rows_out}", flush=True)
    return out


def probe() -> Path:
    verify_preregistration()
    if not META_CSV.exists():
        PDFE_DIR.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(META_URL, META_CSV)
    rows = read_metadata()
    out = {
        "created_at_utc": now_utc(),
        "dataset": "PDFE turning-in-place / Figshare 14984667",
        "n_metadata_rows": len(rows),
        "n_session1_targets": int(sum(np.isfinite(_float_cell(r, "Session 1 - UPDRS-III (score)")) for r in rows)),
        "n_session2_targets": int(sum(np.isfinite(_float_cell(r, "Session 2 - UPDRS-III (score)")) for r in rows)),
        "n_session3_targets": int(sum(np.isfinite(_float_cell(r, "Session 3 - UPDRS-III (score)")) for r in rows)),
        "has_imu_zip": IMU_ZIP.exists(),
        "decision": "direct_public_external_t3_route_for_zero_shot_only",
    }
    path = RESULTS_DIR / "iter52_pdfe_turning_probe.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path}", flush=True)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["write-prereg", "probe", "download", "extract", "run"], required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--n_boot", type=int, default=5000)
    args = ap.parse_args()
    ensure_dir(RESULTS_DIR)
    if args.mode == "write-prereg":
        write_preregistration()
    elif args.mode == "probe":
        probe()
    elif args.mode == "download":
        download(force=args.force)
    elif args.mode == "extract":
        extract_features(force=args.force)
    elif args.mode == "run":
        run(n_boot=args.n_boot)


if __name__ == "__main__":
    main()
