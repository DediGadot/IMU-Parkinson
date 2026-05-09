"""T3 iter39 — FoG-STAR zero-shot external validation.

This is paper-rigor / transportability evidence, not an internal WearGait-PD
CCC booster. It trains only on WearGait-PD and evaluates once on all FoG-STAR
subjects with `updrs_iii`, using a pre-registered wrist-only feature schema.

Tracks:
  A. WearGait wrist Acc+Gyr LGB direct UPDRS-III -> FoG-STAR CCC.
  B. iter5-style clinical Stage 1 + wrist Acc+Gyr residual Stage 2 -> FoG-STAR CCC.
  C. FoG-STAR-only LOOCV sanity ceiling with the same feature block (reported as
     within-cohort feasibility, never as transportability).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import signal as sp_signal, stats as sp_stats
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldImputer, FoldNormalizer, ccc as ccc_fn, cal_slope, mae as mae_fn, pearson_r
from project_paths import DATA_DIR, RESULTS_DIR, ensure_dir
from run_t3_iter2 import train_lgb
from run_t3_iter3 import get_hy_features, load_full_pd_data
from run_t3_iter5_clinical import load_clinical_dict


ensure_dir(RESULTS_DIR)

FOGSTAR_DIR = Path(os.getenv("FOGSTAR_DATA_DIR", REPO_ROOT / "data" / "raw" / "fogstar"))
FOGSTAR_URLS = {
    "clinical_data.csv": "https://zenodo.org/records/17838806/files/clinical_data.csv?download=1",
    "sensor_data.csv": "https://zenodo.org/records/17838806/files/sensor_data.csv?download=1",
    "README.txt": "https://zenodo.org/records/17838806/files/README.txt?download=1",
}
FOGSTAR_TASK_IDS = (1, 3)  # TUG and walk back/forth; closest to WearGait gait/TUG.
WEARGAIT_TASKS = ("TUG", "SelfPace", "HurriedPace")
SEEDS = (42, 1337, 7)
FS_FOGSTAR = 60
FS_WG = 100


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_fogstar(force: bool = False) -> dict[str, Any]:
    ensure_dir(FOGSTAR_DIR)
    files = {}
    for name, url in FOGSTAR_URLS.items():
        path = FOGSTAR_DIR / name
        if force or not path.exists():
            print(f"Downloading {name} from Zenodo...", flush=True)
            urllib.request.urlretrieve(url, path)
        files[name] = {
            "path": str(path),
            "source_url": url,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    manifest = {
        "script": Path(__file__).name,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "dataset": "FoG-STAR",
        "zenodo_record": "https://zenodo.org/records/17838806",
        "license": "CC-BY 4.0",
        "files": files,
        "labels_used": ["updrs_iii"],
        "fold_scope": "FoG-STAR labels used only for external scoring and within-FoG-STAR LOOCV sanity track",
        "leakage_status": "zero_shot_external_evaluation_no_fogstar_training_for_tracks_A_B",
    }
    (FOGSTAR_DIR / "iter39_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_fogstar_clinical() -> pd.DataFrame:
    path = FOGSTAR_DIR / "clinical_data.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    out = pd.DataFrame(
        {
            "subjectID": pd.to_numeric(df["subjectID"], errors="coerce").astype(int),
            "sid": df["subjectID"].map(lambda x: f"FOGSTAR{x:02.0f}"),
            "hy": pd.to_numeric(df["h_y"], errors="coerce"),
            "cv_yrs": pd.to_numeric(df["disease_duration"], errors="coerce"),
            "cv_sex": df["gender"].fillna("").str.upper().map({"M": 0.0, "F": 1.0}),
            "cv_dbs": np.nan,
            "updrs3": pd.to_numeric(df["updrs_iii"], errors="coerce"),
        }
    )
    return out.dropna(subset=["subjectID", "updrs3"]).reset_index(drop=True)


def _safe(fn, x: np.ndarray) -> float:
    try:
        val = float(fn(np.asarray(x, dtype=np.float64)))
        return val if np.isfinite(val) else 0.0
    except Exception:
        return 0.0


def channel_features(x: np.ndarray, prefix: str, fs: int) -> dict[str, float]:
    x = np.nan_to_num(np.asarray(x, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    out = {
        f"{prefix}_mean": _safe(np.mean, x),
        f"{prefix}_std": _safe(np.std, x),
        f"{prefix}_rms": _safe(lambda z: np.sqrt(np.mean(z * z)), x),
        f"{prefix}_iqr": _safe(lambda z: np.percentile(z, 75) - np.percentile(z, 25), x),
        f"{prefix}_range": _safe(np.ptp, x),
        f"{prefix}_skew": _safe(lambda z: sp_stats.skew(z), x),
        f"{prefix}_kurt": _safe(lambda z: sp_stats.kurtosis(z), x),
        f"{prefix}_jerk_rms": _safe(lambda z: np.sqrt(np.mean((np.diff(z) * fs) ** 2)), x),
    }
    try:
        freqs, psd = sp_signal.welch(x, fs=fs, nperseg=min(256, len(x)), noverlap=min(128, len(x) // 2))
        psd = psd + 1e-12
        total = np.trapz(psd, freqs) + 1e-12
        for name, lo, hi in [("loco", 0.5, 3.0), ("trem", 3.0, 8.0), ("high", 8.0, 20.0)]:
            mask = (freqs >= lo) & (freqs <= hi)
            bp = float(np.trapz(psd[mask], freqs[mask])) if mask.sum() > 1 else 1e-12
            out[f"{prefix}_{name}_logp"] = float(np.log10(max(bp, 1e-12)))
            out[f"{prefix}_{name}_ratio"] = float(bp / total)
        out[f"{prefix}_dom_freq"] = float(freqs[np.argmax(psd)])
        pn = psd / psd.sum()
        out[f"{prefix}_spec_entropy"] = float(-np.sum(pn * np.log2(pn + 1e-12)))
    except Exception:
        for name in ["loco", "trem", "high"]:
            out[f"{prefix}_{name}_logp"] = 0.0
            out[f"{prefix}_{name}_ratio"] = 0.0
        out[f"{prefix}_dom_freq"] = 0.0
        out[f"{prefix}_spec_entropy"] = 0.0
    return out


def wrist_features(acc_xyz: np.ndarray, gyr_xyz: np.ndarray, fs: int) -> dict[str, float]:
    out: dict[str, float] = {}
    names = ["x", "y", "z"]
    for i, axis in enumerate(names):
        out.update(channel_features(acc_xyz[:, i], f"wrist_acc_{axis}", fs))
        out.update(channel_features(gyr_xyz[:, i], f"wrist_gyr_{axis}", fs))
    acc_mag = np.sqrt(np.sum(acc_xyz * acc_xyz, axis=1))
    gyr_mag = np.sqrt(np.sum(gyr_xyz * gyr_xyz, axis=1))
    out.update(channel_features(acc_mag, "wrist_acc_mag", fs))
    out.update(channel_features(gyr_mag, "wrist_gyr_mag", fs))
    return out


def average_feature_dicts(dicts: list[dict[str, float]]) -> dict[str, float]:
    keys = sorted({k for d in dicts for k in d})
    return {k: float(np.nanmean([d.get(k, np.nan) for d in dicts])) for k in keys}


def extract_fogstar_features(task_ids: tuple[int, ...]) -> pd.DataFrame:
    sensor_path = FOGSTAR_DIR / "sensor_data.csv"
    if not sensor_path.exists():
        raise FileNotFoundError(sensor_path)
    cols = [
        "wrist_acc_x", "wrist_acc_y", "wrist_acc_z",
        "wrist_gyro_x", "wrist_gyro_y", "wrist_gyro_z",
        "subjectID", "sessionID", "taskID",
    ]
    df = pd.read_csv(sensor_path, usecols=cols)
    df = df[df["taskID"].isin(task_ids)].copy()
    rows = []
    for subject_id, sub in df.groupby("subjectID"):
        chunks: list[dict[str, float]] = []
        for (_sess, _task), g in sub.groupby(["sessionID", "taskID"]):
            if len(g) < FS_FOGSTAR * 5:
                continue
            acc = g[["wrist_acc_x", "wrist_acc_y", "wrist_acc_z"]].to_numpy(dtype=np.float64) * 9.80665
            gyr = g[["wrist_gyro_x", "wrist_gyro_y", "wrist_gyro_z"]].to_numpy(dtype=np.float64)
            chunks.append(wrist_features(acc, gyr, FS_FOGSTAR))
        if chunks:
            row = average_feature_dicts(chunks)
            row["sid"] = f"FOGSTAR{int(subject_id):02d}"
            row["subjectID"] = int(subject_id)
            row["n_task_chunks"] = len(chunks)
            rows.append(row)
    if not rows:
        raise RuntimeError("No FoG-STAR wrist feature rows extracted.")
    return pd.DataFrame(rows)


def extract_weargait_features(sids: np.ndarray, tasks: tuple[str, ...]) -> pd.DataFrame:
    pd_dir = DATA_DIR / "PD PARTICIPANTS" / "CSV files"
    rows = []
    for sid in sids:
        chunks: list[dict[str, float]] = []
        for task in tasks:
            path = pd_dir / f"{sid}_{task}.csv"
            if not path.exists():
                continue
            cols = [
                "R_Wrist_Acc_X", "R_Wrist_Acc_Y", "R_Wrist_Acc_Z",
                "R_Wrist_Gyr_X", "R_Wrist_Gyr_Y", "R_Wrist_Gyr_Z",
            ]
            try:
                df = pd.read_csv(path, usecols=cols)
            except Exception:
                continue
            if len(df) < FS_WG * 5:
                continue
            acc = df[["R_Wrist_Acc_X", "R_Wrist_Acc_Y", "R_Wrist_Acc_Z"]].to_numpy(dtype=np.float64)
            gyr = df[["R_Wrist_Gyr_X", "R_Wrist_Gyr_Y", "R_Wrist_Gyr_Z"]].to_numpy(dtype=np.float64)
            chunks.append(wrist_features(acc, gyr, FS_WG))
        if chunks:
            row = average_feature_dicts(chunks)
            row["sid"] = str(sid)
            row["n_task_chunks"] = len(chunks)
            rows.append(row)
    if not rows:
        raise RuntimeError(f"No WearGait wrist feature rows extracted from {pd_dir}")
    return pd.DataFrame(rows)


def build_stage1_matrix(hy: np.ndarray, cv_yrs: np.ndarray, cv_sex: np.ndarray, cv_dbs: np.ndarray) -> np.ndarray:
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


def bootstrap_metric(y_true: np.ndarray, y_pred: np.ndarray, n_boot: int = 10000, seed: int = 20260508) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    cccs = []
    n = len(y_true)
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        cccs.append(ccc_fn(y_true[idx], y_pred[idx]))
    arr = np.asarray(cccs, dtype=np.float64)
    return {
        "n_boot": n_boot,
        "ccc_ci95": [round(float(np.percentile(arr, 2.5)), 4), round(float(np.percentile(arr, 97.5)), 4)],
        "ccc_frac_gt_0": round(float(np.mean(arr > 0)), 4),
        "ccc_frac_gt_02": round(float(np.mean(arr > 0.2)), 4),
    }


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        return "unknown"


def _formula_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def make_prereg_payload(seeds: list[int]) -> dict[str, Any]:
    return {
        "experiment": "T3 iter39 FoG-STAR zero-shot external validation",
        "internal_train_dataset": "WearGait-PD PD subjects with canonical T3 labels",
        "external_test_dataset": "FoG-STAR Zenodo 17838806, all subjects with updrs_iii",
        "sensor": "wrist only",
        "weargait_tasks": list(WEARGAIT_TASKS),
        "fogstar_task_ids": list(FOGSTAR_TASK_IDS),
        "feature_schema": "wrist Acc XYZ + Gyr XYZ + magnitudes; td/fd summary features; FoG-STAR acc converted g to m/s^2",
        "tracks": [
            "A: WearGait wrist LGB direct UPDRS-III, zero-shot to FoG-STAR",
            "B: WearGait clinical Stage1 Ridge + wrist residual LGB, zero-shot to FoG-STAR",
            "C: FoG-STAR-only LOOCV sanity ceiling, not transportability",
        ],
        "primary_metric": "CCC on all FoG-STAR subjects",
        "seeds": list(seeds),
        "overclaim_gates": {
            "promising_external_validity": "CCC > 0.35 and bootstrap lower CI > 0",
            "transportability_cliff": "CCC <= 0.2 or CI overlaps zero",
            "no_internal_canonical_change": True,
        },
        "leakage_firewall": [
            "Tracks A/B train only on WearGait; FoG-STAR labels are not used until scoring.",
            "No FoG-STAR calibration, hyperparameter tuning, outlier removal, or task cherry-picking after prediction.",
            "Track C is explicitly within-FoG-STAR sanity and not a zero-shot claim.",
        ],
    }


def write_prereg(seeds: list[int]) -> Path:
    payload = make_prereg_payload(seeds)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        **payload,
        "formula_sha256": _formula_sha256(payload),
        "git_sha": _git_sha(),
        "timestamp": ts,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    path = RESULTS_DIR / f"preregistration_t3_iter39_fogstar_zeroshot_{ts}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"Wrote {path}", flush=True)
    print(f"formula_sha256={out['formula_sha256']}", flush=True)
    return path


def load_prereg(path: Path) -> dict[str, Any]:
    pre = json.loads(path.read_text())
    expected = make_prereg_payload(list(pre["seeds"]))
    if pre.get("formula_sha256") != _formula_sha256(expected):
        raise RuntimeError("Pre-registration formula_sha256 mismatch.")
    return pre


def run(prereg_file: Path) -> Path:
    pre = load_prereg(prereg_file)
    seeds = list(map(int, pre["seeds"]))
    ts = pre["timestamp"]
    download_fogstar()

    sids, _X_v2, _fc, y_wg, hy_wg, _obs = load_full_pd_data()
    clinical_wg = load_clinical_dict(sids)
    fog_clin = load_fogstar_clinical()

    t0 = time.time()
    wg_feat = extract_weargait_features(sids, WEARGAIT_TASKS)
    fog_feat = extract_fogstar_features(FOGSTAR_TASK_IDS)
    print(f"Extracted WG features {wg_feat.shape}, FoG-STAR features {fog_feat.shape} in {time.time()-t0:.1f}s", flush=True)

    wg = pd.DataFrame({"sid": sids, "updrs3": y_wg, "hy": hy_wg})
    wg["cv_yrs"] = clinical_wg["cv_yrs"]
    wg["cv_sex"] = clinical_wg["cv_sex"]
    wg["cv_dbs"] = clinical_wg["cv_dbs"]
    wg = wg.merge(wg_feat, on="sid", how="inner")
    fog = fog_clin.merge(fog_feat, on=["sid", "subjectID"], how="inner")
    feature_cols = sorted(set(wg_feat.columns) & set(fog_feat.columns))
    feature_cols = [c for c in feature_cols if c.startswith("wrist_")]
    if len(feature_cols) < 40:
        raise RuntimeError(f"Only {len(feature_cols)} common wrist features.")

    Xwg = wg[feature_cols].to_numpy(dtype=np.float64)
    Xfog = fog[feature_cols].to_numpy(dtype=np.float64)
    y_train = wg["updrs3"].to_numpy(dtype=np.float64)
    y_ext = fog["updrs3"].to_numpy(dtype=np.float64)
    Xwg_n, Xfog_n = clean_train_test(Xwg, Xfog)

    # Track A: direct wrist model.
    a_seed_preds = []
    for seed in seeds:
        a_seed_preds.append(train_lgb(Xwg_n, y_train, Xfog_n, seed))
    pred_a = np.mean(np.stack(a_seed_preds, axis=0), axis=0)

    # Track B: iter5-style clinical Stage 1 + wrist residual Stage 2.
    Xs1_wg = build_stage1_matrix(
        wg["hy"].to_numpy(dtype=np.float64),
        wg["cv_yrs"].to_numpy(dtype=np.float64),
        wg["cv_sex"].to_numpy(dtype=np.float64),
        wg["cv_dbs"].to_numpy(dtype=np.float64),
    )
    Xs1_fog = build_stage1_matrix(
        fog["hy"].to_numpy(dtype=np.float64),
        fog["cv_yrs"].to_numpy(dtype=np.float64),
        fog["cv_sex"].to_numpy(dtype=np.float64),
        fog["cv_dbs"].to_numpy(dtype=np.float64),
    )
    s1_wg, s1_fog = fit_stage1(Xs1_wg, y_train, Xs1_fog)
    resid = y_train - s1_wg
    b_seed_preds = []
    for seed in seeds:
        b_seed_preds.append(s1_fog + train_lgb(Xwg_n, resid, Xfog_n, seed))
    pred_b = np.mean(np.stack(b_seed_preds, axis=0), axis=0)

    # Track C: FoG-STAR-only LOOCV sanity ceiling, Ridge on features + clinical.
    Xc = fog[feature_cols].to_numpy(dtype=np.float64)
    Xc_s1 = build_stage1_matrix(
        fog["hy"].to_numpy(dtype=np.float64),
        fog["cv_yrs"].to_numpy(dtype=np.float64),
        fog["cv_sex"].to_numpy(dtype=np.float64),
        fog["cv_dbs"].to_numpy(dtype=np.float64),
    )
    Xc_all = np.column_stack([Xc, Xc_s1])
    loo = LeaveOneOut()
    pred_c = np.zeros(len(fog), dtype=np.float64)
    for tr, te in loo.split(Xc_all):
        Xtr, Xte = clean_train_test(Xc_all[tr], Xc_all[te])
        model = Ridge(alpha=10.0, fit_intercept=True)
        model.fit(Xtr, y_ext[tr])
        pred_c[te] = model.predict(Xte)

    rows = pd.DataFrame(
        {
            "sid": fog["sid"],
            "subjectID": fog["subjectID"],
            "updrs3": y_ext,
            "hy": fog["hy"],
            "cv_yrs": fog["cv_yrs"],
            "track_a_pred": pred_a,
            "track_b_pred": pred_b,
            "track_c_fogstar_loo_pred": pred_c,
        }
    )
    rows_path = RESULTS_DIR / f"iter39_fogstar_zeroshot_rows_{ts}.csv"
    rows.to_csv(rows_path, index=False)
    result = {
        "script": Path(__file__).name,
        "preregistration": str(prereg_file),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "n_weargait_train": int(len(wg)),
        "n_fogstar": int(len(fog)),
        "n_common_features": int(len(feature_cols)),
        "feature_cols": feature_cols,
        "weargait_tasks": list(WEARGAIT_TASKS),
        "fogstar_task_ids": list(FOGSTAR_TASK_IDS),
        "rows_csv": str(rows_path),
        "track_a_wg_wrist_direct": {**metrics(y_ext, pred_a), **bootstrap_metric(y_ext, pred_a)},
        "track_b_iter5_style_clinical_plus_wrist": {**metrics(y_ext, pred_b), **bootstrap_metric(y_ext, pred_b)},
        "track_c_fogstar_only_loo_sanity": {**metrics(y_ext, pred_c), **bootstrap_metric(y_ext, pred_c)},
        "decision": "zero_shot_external_validation_only_no_internal_canonical_change",
    }
    out_path = RESULTS_DIR / f"iter39_fogstar_zeroshot_{ts}.json"
    out_path.write_text(json.dumps(result, indent=2, default=float) + "\n")
    print(json.dumps({k: result[k] for k in result if k.startswith("track_") or k in ("n_fogstar", "n_common_features")}, indent=2), flush=True)
    print(f"Wrote {out_path}", flush=True)
    print(f"Wrote {rows_path}", flush=True)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["write_prereg", "run"], required=True)
    ap.add_argument("--seeds", nargs="*", type=int, default=list(SEEDS))
    ap.add_argument("--preregistration_file", type=Path)
    args = ap.parse_args()
    if args.mode == "write_prereg":
        write_prereg(list(args.seeds))
    else:
        if args.preregistration_file is None:
            raise SystemExit("--preregistration_file is required for --mode run")
        run(args.preregistration_file)


if __name__ == "__main__":
    main()
