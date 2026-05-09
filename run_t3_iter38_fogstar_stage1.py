"""T3 iter38 — FoG-STAR external clinical Stage-1 augmentation screen.

FoG-STAR is a newly surfaced public dataset with 22 PD subjects, wearable IMU,
and subject-level MDS-UPDRS III (`updrs_iii`). This script tests the smallest
direct way it could move the WearGait-PD T3 ceiling without feature-schema
overreach:

  Baseline: canonical iter5 5-fold loop
    Stage 1 Ridge on WearGait H&Y + cv_yrs + cv_sex + cv_dbs
    Stage 2 LGB on WearGait V2 residual

  Probe: FoG-STAR-augmented Stage 1 only
    Stage 1 Ridge on WearGait train rows + all FoG-STAR clinical rows
      common cols = H&Y + disease duration + sex + dbs-missing-imputed
    Stage 2 LGB remains WearGait train V2 residual only

FoG-STAR rows never enter Stage 2 and never include a WearGait test subject.
This is a screen, not a lockbox. Promote only if the 5-fold gate clears.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldImputer, FoldNormalizer, ccc as ccc_fn, cal_slope, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter3 import get_hy_features, load_full_pd_data
from run_t3_iter5_clinical import load_clinical_dict


ensure_dir(RESULTS_DIR)

FOGSTAR_URLS = {
    "clinical_data.csv": "https://zenodo.org/records/17838806/files/clinical_data.csv?download=1",
    "README.txt": "https://zenodo.org/records/17838806/files/README.txt?download=1",
}
FOGSTAR_DIR = Path(os.getenv("FOGSTAR_DATA_DIR", REPO_ROOT / "data" / "raw" / "fogstar"))
SEEDS = (42, 1337, 7)
CANONICAL_T3_CCC = 0.5227


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_fogstar_clinical(force: bool = False) -> dict[str, Any]:
    ensure_dir(FOGSTAR_DIR)
    files: dict[str, dict[str, Any]] = {}
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
        "scientific_data_article": "https://www.nature.com/articles/s41597-026-06645-1",
        "license": "CC-BY 4.0",
        "files": files,
        "labels_used": ["updrs_iii"],
        "fold_scope": "external FoG-STAR rows are training-only in WearGait folds",
        "leakage_status": "screen_only_external_training_rows_no_weargait_test_labels",
    }
    (FOGSTAR_DIR / "clinical_data.csv.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_fogstar_clinical(download: bool = True) -> pd.DataFrame:
    if download:
        download_fogstar_clinical()
    path = FOGSTAR_DIR / "clinical_data.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing FoG-STAR clinical data: {path}")
    df = pd.read_csv(path)
    required = ["subjectID", "gender", "disease_duration", "h_y", "updrs_iii"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"FoG-STAR clinical file missing columns: {missing}")
    out = pd.DataFrame(
        {
            "sid": df["subjectID"].map(lambda x: f"FOGSTAR{x:02.0f}"),
            "hy": pd.to_numeric(df["h_y"], errors="coerce"),
            "cv_yrs": pd.to_numeric(df["disease_duration"], errors="coerce"),
            "cv_sex": df["gender"].fillna("").str.upper().map({"M": 0.0, "F": 1.0}),
            "cv_dbs": np.nan,
            "updrs3": pd.to_numeric(df["updrs_iii"], errors="coerce"),
        }
    )
    out = out.dropna(subset=["updrs3"]).reset_index(drop=True)
    return out


def build_stage1_matrix(hy: np.ndarray, cv_yrs: np.ndarray, cv_sex: np.ndarray, cv_dbs: np.ndarray) -> np.ndarray:
    return np.column_stack(
        [
            get_hy_features(np.asarray(hy, dtype=np.float64)),
            np.asarray(cv_yrs, dtype=np.float64),
            np.asarray(cv_sex, dtype=np.float64),
            np.asarray(cv_dbs, dtype=np.float64),
        ]
    )


def fit_stage1_fold(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    sample_weight: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    imp = FoldImputer.fit(X_train)
    Xtr_i = imp.transform(X_train)
    Xte_i = imp.transform(X_test)
    nrm = FoldNormalizer.fit(Xtr_i)
    Xtr = nrm.transform(Xtr_i)
    Xte = nrm.transform(Xte_i)
    model = Ridge(alpha=1.0, fit_intercept=True)
    model.fit(Xtr, y_train, sample_weight=sample_weight)
    return model.predict(Xtr), model.predict(Xte)


def kfold_splits(n: int, seed: int) -> list[tuple[np.ndarray, np.ndarray]]:
    return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))


def run_one_seed(seed: int, fog: pd.DataFrame, external_weight: float = 1.0) -> dict[str, Any]:
    sids, X_v2, _fc, y_t3, hy, _obs = load_full_pd_data()
    clinical = load_clinical_dict(sids)
    X_s1_wg = build_stage1_matrix(
        hy,
        clinical["cv_yrs"],
        clinical["cv_sex"],
        clinical["cv_dbs"],
    )
    X_s1_fog = build_stage1_matrix(
        fog["hy"].to_numpy(),
        fog["cv_yrs"].to_numpy(),
        fog["cv_sex"].to_numpy(),
        fog["cv_dbs"].to_numpy(),
    )
    y_fog = fog["updrs3"].to_numpy(dtype=np.float64)

    pred_base = np.zeros(len(sids), dtype=np.float64)
    pred_aug = np.zeros(len(sids), dtype=np.float64)
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(kfold_splits(len(sids), seed), start=1):
        # Baseline: WearGait-only Stage 1, canonical Stage 2.
        s1_tr, s1_te = fit_stage1_fold(X_s1_wg[tr], y_t3[tr], X_s1_wg[te])
        resid_tr = y_t3[tr] - s1_tr
        Xtr, Xte = impute_fold(X_v2[tr], X_v2[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        pred_base[te] = s1_te + train_lgb(Xtr_sel, resid_tr, Xte_sel, seed)

        # Probe: Stage 1 sees train-fold WG rows + all external FoG-STAR rows.
        X_aug_tr = np.vstack([X_s1_wg[tr], X_s1_fog])
        y_aug_tr = np.concatenate([y_t3[tr], y_fog])
        sw = np.concatenate(
            [
                np.ones(len(tr), dtype=np.float64),
                np.full(len(y_fog), float(external_weight), dtype=np.float64),
            ]
        )
        s1_aug_all, s1_aug_te = fit_stage1_fold(X_aug_tr, y_aug_tr, X_s1_wg[te], sample_weight=sw)
        s1_aug_tr_wg = s1_aug_all[: len(tr)]
        resid_aug_tr = y_t3[tr] - s1_aug_tr_wg
        Xtr_a, Xte_a = impute_fold(X_v2[tr], X_v2[te])
        Xtr_a_sel, Xte_a_sel, _ = feature_select_fold(Xtr_a, resid_aug_tr, Xte_a, k=500, seed=seed)
        pred_aug[te] = s1_aug_te + train_lgb(Xtr_a_sel, resid_aug_tr, Xte_a_sel, seed)
        print(f"  seed={seed} fold {fold_idx}/5 done", flush=True)

    return {
        "seed": seed,
        "elapsed_s": round(time.time() - t0, 1),
        "sids": list(map(str, sids)),
        "y_true": y_t3.astype(float).tolist(),
        "baseline_pred": pred_base.astype(float).tolist(),
        "augmented_pred": pred_aug.astype(float).tolist(),
        "baseline": metrics(y_t3, pred_base),
        "augmented": metrics(y_t3, pred_aug),
        "delta_ccc": float(ccc_fn(y_t3, pred_aug) - ccc_fn(y_t3, pred_base)),
    }


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "ccc": round(float(ccc_fn(y_true, y_pred)), 4),
        "mae": round(float(mae_fn(y_true, y_pred)), 4),
        "r": round(float(pearson_r(y_true, y_pred)), 4),
        "cal_slope": round(float(cal_slope(y_true, y_pred)), 4),
    }


def bootstrap_delta(y: np.ndarray, base: np.ndarray, aug: np.ndarray, n_boot: int = 5000, seed: int = 20260508) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    deltas = []
    n = len(y)
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        deltas.append(ccc_fn(y[idx], aug[idx]) - ccc_fn(y[idx], base[idx]))
    arr = np.asarray(deltas, dtype=np.float64)
    return {
        "n_boot": n_boot,
        "mean_delta": round(float(arr.mean()), 4),
        "ci95": [round(float(np.percentile(arr, 2.5)), 4), round(float(np.percentile(arr, 97.5)), 4)],
        "frac_gt_0": round(float(np.mean(arr > 0)), 4),
        "frac_gt_0025": round(float(np.mean(arr > 0.025)), 4),
    }


def run_screen(seeds: tuple[int, ...], external_weight: float) -> Path:
    fog = load_fogstar_clinical(download=True)
    print("\n=== FoG-STAR clinical summary ===", flush=True)
    print(fog[["sid", "hy", "cv_yrs", "cv_sex", "updrs3"]].to_string(index=False), flush=True)
    print(
        f"FoG-STAR n={len(fog)}, UPDRS mean={fog['updrs3'].mean():.2f}, "
        f"range=({fog['updrs3'].min():.0f}, {fog['updrs3'].max():.0f})",
        flush=True,
    )

    rows = []
    seed_payloads = []
    for seed in seeds:
        print(f"\n=== seed {seed} ===", flush=True)
        payload = run_one_seed(seed, fog, external_weight=external_weight)
        seed_payloads.append(payload)
        rows.append(
            {
                "seed": seed,
                "baseline_ccc": payload["baseline"]["ccc"],
                "augmented_ccc": payload["augmented"]["ccc"],
                "delta_ccc": round(payload["delta_ccc"], 4),
                "baseline_mae": payload["baseline"]["mae"],
                "augmented_mae": payload["augmented"]["mae"],
                "elapsed_s": payload["elapsed_s"],
            }
        )
        print(
            f"seed={seed}: baseline CCC={payload['baseline']['ccc']:.4f}, "
            f"aug CCC={payload['augmented']['ccc']:.4f}, delta={payload['delta_ccc']:+.4f}",
            flush=True,
        )

    row_df = pd.DataFrame(rows)
    y = np.asarray(seed_payloads[0]["y_true"], dtype=np.float64)
    base_mean = np.mean([np.asarray(p["baseline_pred"], dtype=np.float64) for p in seed_payloads], axis=0)
    aug_mean = np.mean([np.asarray(p["augmented_pred"], dtype=np.float64) for p in seed_payloads], axis=0)
    base_m = metrics(y, base_mean)
    aug_m = metrics(y, aug_mean)
    boot = bootstrap_delta(y, base_mean, aug_mean)
    deltas = row_df["delta_ccc"].to_numpy(dtype=np.float64)
    gate = {
        "pass": bool((deltas.mean() >= 0.025) and (deltas.std() < 0.02) and (boot["frac_gt_0"] >= 0.95)),
        "criteria": "mean seed delta >= +0.025, seed std < 0.020, paired bootstrap frac_gt_0 >= 0.95",
        "mean_seed_delta": round(float(deltas.mean()), 4),
        "seed_delta_std": round(float(deltas.std()), 4),
        "bootstrap": boot,
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTS_DIR / f"iter38_fogstar_stage1_screen_rows_{ts}.csv"
    json_path = RESULTS_DIR / f"iter38_fogstar_stage1_screen_{ts}.json"
    row_df.to_csv(csv_path, index=False)
    report = {
        "script": Path(__file__).name,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "screen",
        "dataset": {
            "name": "FoG-STAR",
            "n": int(len(fog)),
            "source": "https://zenodo.org/records/17838806",
            "clinical_manifest": str(FOGSTAR_DIR / "clinical_data.csv.manifest.json"),
            "updrs_mean": float(fog["updrs3"].mean()),
            "updrs_min": float(fog["updrs3"].min()),
            "updrs_max": float(fog["updrs3"].max()),
        },
        "external_weight": float(external_weight),
        "seeds": list(seeds),
        "rows_csv": str(csv_path),
        "per_seed": rows,
        "baseline_seed_mean": base_m,
        "augmented_seed_mean": aug_m,
        "delta_seed_mean_predictions": round(float(ccc_fn(y, aug_mean) - ccc_fn(y, base_mean)), 4),
        "gate": gate,
        "canonical_t3_ccc": CANONICAL_T3_CCC,
        "decision": (
            "eligible_for_preregistered_loocv_lockbox"
            if gate["pass"]
            else "screen_fail_no_lockbox_no_canonical_change"
        ),
        "leakage_rationale": [
            "WearGait test folds are never included in Stage-1 or Stage-2 training.",
            "FoG-STAR rows are external training rows only; they do not enter WearGait test labels.",
            "Stage-2 remains WearGait train-fold V2 residual only, preserving the canonical V2 feature contract.",
            "FoG-STAR missing DBS is imputed inside the fold by FoldImputer fit on combined training rows.",
        ],
    }
    json_path.write_text(json.dumps(report, indent=2, default=float) + "\n")
    print("\n=== ITER38 FoG-STAR Stage-1 augmentation screen ===", flush=True)
    print(row_df.to_string(index=False), flush=True)
    print(
        f"\nSeed-mean preds: baseline CCC={base_m['ccc']:.4f}, "
        f"aug CCC={aug_m['ccc']:.4f}, delta={report['delta_seed_mean_predictions']:+.4f}",
        flush=True,
    )
    print(f"Gate: {gate}", flush=True)
    print(f"Wrote {json_path}", flush=True)
    print(f"Wrote {csv_path}", flush=True)
    return json_path


def run_probe() -> Path:
    fog = load_fogstar_clinical(download=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter38_fogstar_probe_{ts}.json"
    payload = {
        "script": Path(__file__).name,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "dataset": "FoG-STAR",
        "n": int(len(fog)),
        "columns": list(fog.columns),
        "missing_by_column": fog.isna().sum().to_dict(),
        "updrs_summary": {
            "mean": float(fog["updrs3"].mean()),
            "std": float(fog["updrs3"].std()),
            "min": float(fog["updrs3"].min()),
            "max": float(fog["updrs3"].max()),
        },
        "hy_summary": {
            "mean": float(fog["hy"].mean()),
            "missing": int(fog["hy"].isna().sum()),
        },
        "decision": "schema_valid_for_iter38_stage1_screen",
    }
    out.write_text(json.dumps(payload, indent=2, default=float) + "\n")
    print(json.dumps(payload, indent=2, default=float), flush=True)
    print(f"Wrote {out}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["probe", "screen"], default="screen")
    ap.add_argument("--seeds", nargs="*", type=int, default=list(SEEDS))
    ap.add_argument("--external_weight", type=float, default=1.0)
    args = ap.parse_args()
    if args.mode == "probe":
        run_probe()
    else:
        run_screen(tuple(args.seeds), external_weight=args.external_weight)


if __name__ == "__main__":
    main()
