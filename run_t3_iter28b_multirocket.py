"""T3 iter28-B — MultiROCKET random convolutional kernels on raw IMU.

Stage 1 BIT-IDENTICAL to iter5 (Ridge on H&Y + cv_yrs + cv_sex + cv_dbs).
Stage 2 = MultiROCKET features (raw IMU, 26-channel acc/gyr-magnitude, central
20s @ 100Hz, mean across 5 tasks per subject) → standardised RidgeCV or
ElasticNetCV on V2-residual target. No K-best selection (Ridge L2 handles
p≫n by design).

Backend chain: aeon.MultiRocket → aeon.MiniRocket → pyts.ROCKET (hard-fail
if none). Cached per seed at results/multirocket_features_seed{seed}_k{K}.npz.

Modes: extract | screen | write_prereg | lockbox.

Reuses run_t3_iter5_clinical (Stage 1 builders), run_t3_iter3.load_full_pd_data,
inductive_lib (FoldNormalizer + metrics).
"""
from __future__ import annotations

import os
os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
import json
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNetCV, RidgeCV
from sklearn.model_selection import KFold, LeaveOneOut

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import (
    FoldNormalizer,
    ccc as ccc_fn,
    full_metrics,
    mae as mae_fn,
    pearson_r,
)
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter3 import load_full_pd_data
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)

ensure_dir(RESULTS_DIR)

# ── Constants ────────────────────────────────────────────────────────────────

SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
DATA_DIR = Path(os.environ.get("WEARGAIT_DATA_DIR", "/root/pd-imu/data/raw/weargait-pd"))
PD_CSV_DIR = DATA_DIR / "PD PARTICIPANTS" / "CSV files"
FS = 100  # Hz
WINDOW_SAMPLES = 20 * FS  # 20 s = 2000 samples
TASKS: tuple[str, ...] = ("SelfPace", "HurriedPace", "TUG", "TandemGait", "Balance")
SENSORS: tuple[str, ...] = (
    "LowerBack", "R_Wrist", "L_Wrist",
    "R_MidLatThigh", "L_MidLatThigh",
    "R_LatShank", "L_LatShank",
    "R_DorsalFoot", "L_DorsalFoot",
    "R_Ankle", "L_Ankle",
    "Xiphoid", "Forehead",
)
ACC_COLS = ("Acc_X", "Acc_Y", "Acc_Z")
GYR_COLS = ("Gyr_X", "Gyr_Y", "Gyr_Z")
N_CHANNELS = len(SENSORS) * 2  # acc-mag + gyr-mag per sensor → 26

ALPHA_GRID: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0, 100.0)
ITER5_LOCKBOX_OOF = RESULTS_DIR / "lockbox_t3_iter5_A3_tier1_20260502_171604.oof.npy"


def _resolve_rocket_backend() -> tuple[str, type]:
    """Pick aeon.MultiRocket → aeon.MiniRocket → pyts.ROCKET (hard-fail)."""
    try:
        from aeon.transformations.collection.convolution_based import MultiRocket as _MR
        return ("aeon.MultiRocket", _MR)
    except Exception:
        pass
    try:
        from aeon.transformations.collection.convolution_based import MiniRocket as _MnR
        return ("aeon.MiniRocket", _MnR)
    except Exception:
        pass
    try:
        from pyts.transformation import ROCKET as _PR  # type: ignore
        return ("pyts.ROCKET", _PR)
    except Exception:
        pass
    raise RuntimeError(
        "No ROCKET-family transformer available. Install aeon or pyts."
    )


def _load_recording_channels(args: tuple[str, str]) -> Optional[dict]:
    """Worker: load one (sid, task) CSV → 26-channel (acc-mag + gyr-mag per sensor)
    central-window (26, WINDOW_SAMPLES). Returns None if unusable."""
    sid, task = args
    path = PD_CSV_DIR / f"{sid}_{task}.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return None
    if len(df) < WINDOW_SAMPLES:
        return None
    chans: list[np.ndarray] = []
    for sen in SENSORS:
        ac = [f"{sen}_{c}" for c in ACC_COLS]
        gc = [f"{sen}_{c}" for c in GYR_COLS]
        if all(c in df.columns for c in ac):
            v = np.nan_to_num(df[ac].values.astype(np.float32))
            chans.append(np.sqrt(np.sum(v * v, axis=1)))
        else:
            chans.append(np.zeros(len(df), dtype=np.float32))
        if all(c in df.columns for c in gc):
            v = np.nan_to_num(df[gc].values.astype(np.float32))
            chans.append(np.sqrt(np.sum(v * v, axis=1)))
        else:
            chans.append(np.zeros(len(df), dtype=np.float32))
    data = np.column_stack(chans).astype(np.float32)
    start = max(0, (data.shape[0] - WINDOW_SAMPLES) // 2)
    window = data[start : start + WINDOW_SAMPLES, :]
    if window.shape[0] != WINDOW_SAMPLES or not np.isfinite(window).any():
        return None
    return {"sid": sid, "task": task, "data": window.T}


def collect_recordings(
    sids: np.ndarray, n_workers: int
) -> tuple[np.ndarray, list[str], list[str]]:
    """Load all (sid, task) recordings → (N_rec, 26, WINDOW_SAMPLES)."""
    jobs = [(str(s), t) for s in sids for t in TASKS]
    print(f"Loading {len(jobs)} (sid,task) pairs from {PD_CSV_DIR}...", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        results = list(pool.map(_load_recording_channels, jobs, chunksize=4))
    valid = [r for r in results if r is not None]
    if not valid:
        raise RuntimeError(f"No usable recordings found in {PD_CSV_DIR}")
    arr = np.stack([r["data"] for r in valid]).astype(np.float32)
    rec_sids = [r["sid"] for r in valid]
    rec_tasks = [r["task"] for r in valid]
    print(
        f"  loaded {arr.shape[0]} recordings → {arr.shape} in {time.time()-t0:.0f}s",
        flush=True,
    )
    return arr, rec_sids, rec_tasks


def _aggregate_per_subject(
    feat_mat: np.ndarray, rec_sids: list[str], target_sids: np.ndarray
) -> np.ndarray:
    """Mean feature vector per subject; preserves target_sids order."""
    out = np.zeros((len(target_sids), feat_mat.shape[1]), dtype=np.float32)
    counts = np.zeros(len(target_sids), dtype=np.int64)
    sid_to_idx = {str(s): i for i, s in enumerate(target_sids)}
    for i, sid in enumerate(rec_sids):
        idx = sid_to_idx.get(str(sid))
        if idx is None:
            continue
        out[idx] += feat_mat[i]
        counts[idx] += 1
    nz = counts > 0
    out[nz] /= counts[nz, None].astype(np.float32)
    return out


def extract_multirocket_per_subject(
    sids: np.ndarray, num_kernels: int, seed: int, n_workers: int, cache_path: Path
) -> np.ndarray:
    """Fit ROCKET on all recordings (unsupervised — no target leakage), transform,
    average per subject. Cached at cache_path."""
    if cache_path.exists():
        print(f"  cache HIT: {cache_path}", flush=True)
        with np.load(cache_path) as z:
            feats = z["features"].astype(np.float32)
            cached_sids = [str(s) for s in z["sids"].tolist()]
        if cached_sids == [str(s) for s in sids]:
            return feats
        print("  cache SID mismatch → re-extracting", flush=True)

    backend_name, RocketCls = _resolve_rocket_backend()
    print(f"  backend={backend_name}, num_kernels={num_kernels}, seed={seed}", flush=True)
    rec_arr, rec_sids, _ = collect_recordings(sids, n_workers=n_workers)
    rec_arr = np.nan_to_num(rec_arr, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)

    transformer = RocketCls(n_kernels=num_kernels, random_state=seed)
    print(f"  fitting {backend_name} on {rec_arr.shape[0]} recordings...", flush=True)
    t0 = time.time()
    transformer.fit(rec_arr)
    feat_mat = transformer.transform(rec_arr)
    if hasattr(feat_mat, "to_numpy"):
        feat_mat = feat_mat.to_numpy()
    feat_mat = np.nan_to_num(np.asarray(feat_mat, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    print(f"  transform → {feat_mat.shape} in {time.time()-t0:.0f}s", flush=True)

    subj_feats = _aggregate_per_subject(feat_mat, rec_sids, sids)
    np.savez_compressed(
        cache_path,
        features=subj_feats,
        sids=np.array([str(s) for s in sids]),
        backend=np.array([backend_name]),
        num_kernels=np.array([num_kernels]),
        seed=np.array([seed]),
    )
    print(f"  cache WRITE: {cache_path}", flush=True)
    return subj_feats


def stage2_rocket_ridge(
    rocket_tr: np.ndarray,
    residual_tr: np.ndarray,
    rocket_te: np.ndarray,
    seed: int,
    use_elasticnet: bool = False,
    alpha_grid: tuple[float, ...] = ALPHA_GRID,
) -> tuple[np.ndarray, float]:
    """Per-fold StandardScaler + RidgeCV (or ElasticNetCV). Returns (test_pred, alpha_chosen)."""
    nrm = FoldNormalizer.fit(rocket_tr)
    Xtr, Xte = nrm.transform(rocket_tr), nrm.transform(rocket_te)
    if use_elasticnet:
        m = ElasticNetCV(
            l1_ratio=0.5, alphas=list(alpha_grid), cv=5,
            random_state=seed, max_iter=5000, n_jobs=1,
        )
    else:
        m = RidgeCV(alphas=list(alpha_grid), cv=5, fit_intercept=True)
    m.fit(Xtr, residual_tr)
    return m.predict(Xte), float(m.alpha_)


def kfold_split(n: int, n_splits: int = 5, seed: int = 42) -> list:
    return list(KFold(n_splits=n_splits, shuffle=True, random_state=seed).split(np.arange(n)))


def _stage1_setup(feature_set: str):
    sids, _X_v2, _fc, y_t3, hy, _obs = load_full_pd_data()
    clinical = load_clinical_dict(sids)
    extras = ITER5_FEATURE_SETS[feature_set]
    X_s1, _ = build_stage1_features(hy, clinical, extras)
    return sids, y_t3, X_s1


def run_one_5fold(
    seed: int, feature_set: str, rocket_feats: np.ndarray, use_elasticnet: bool = False,
) -> tuple[np.ndarray, list[float]]:
    sids, y_t3, X_s1 = _stage1_setup(feature_set)
    n = len(sids)
    preds = np.zeros(n, dtype=np.float64)
    alphas: list[float] = []
    for tr, te in kfold_split(n, n_splits=5, seed=seed):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=1.0)
        s2_te, a = stage2_rocket_ridge(
            rocket_feats[tr], y_t3[tr] - s1_tr, rocket_feats[te], seed, use_elasticnet,
        )
        preds[te] = s1_te + s2_te
        alphas.append(a)
    return preds, alphas


def run_one_loocv(
    seed: int, feature_set: str, rocket_feats: np.ndarray, use_elasticnet: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[float]]:
    sids, y_t3, X_s1 = _stage1_setup(feature_set)
    n = len(sids)
    preds = np.zeros(n, dtype=np.float64)
    alphas: list[float] = []
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(LeaveOneOut().split(np.arange(n))):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=1.0)
        s2_te, a = stage2_rocket_ridge(
            rocket_feats[tr], y_t3[tr] - s1_tr, rocket_feats[te], seed, use_elasticnet,
        )
        preds[te] = s1_te + s2_te
        alphas.append(a)
        if (fold_idx + 1) % 10 == 0:
            print(
                f"    seed={seed} fold {fold_idx+1}/{n}  elapsed={time.time()-t0:.1f}s",
                flush=True,
            )
    return sids, y_t3, preds, alphas


def _features_cache_path(seed: int, num_kernels: int) -> Path:
    return RESULTS_DIR / f"multirocket_features_seed{seed}_k{num_kernels}.npz"


def mode_extract(seeds: list[int], num_kernels: int, n_workers: int) -> None:
    sids, _X_v2, _fc, _y_t3, _hy, _obs = load_full_pd_data()
    print(f"\n=== iter28-B EXTRACT (seeds={seeds}, num_kernels={num_kernels}) ===\n", flush=True)
    for seed in seeds:
        cache = _features_cache_path(seed, num_kernels)
        feats = extract_multirocket_per_subject(
            sids=sids,
            num_kernels=num_kernels,
            seed=seed,
            n_workers=n_workers,
            cache_path=cache,
        )
        print(
            f"  seed={seed}: features shape = {feats.shape} → {cache.name}",
            flush=True,
        )


def mode_screen(
    seeds: list[int],
    num_kernels: int,
    n_workers: int,
    feature_set: str = "A3_tier1",
    use_elasticnet: bool = False,
) -> Path:
    sids, _X_v2, _fc, y_t3, _hy, _obs = load_full_pd_data()
    print(
        f"\n=== iter28-B 5-FOLD SCREEN ({len(seeds)} seeds, num_kernels={num_kernels}, "
        f"stage2={'ElasticNetCV' if use_elasticnet else 'RidgeCV'}) ===\n",
        flush=True,
    )
    rows: list[dict] = []
    for seed in seeds:
        cache = _features_cache_path(seed, num_kernels)
        feats = extract_multirocket_per_subject(
            sids=sids,
            num_kernels=num_kernels,
            seed=seed,
            n_workers=n_workers,
            cache_path=cache,
        )
        t0 = time.time()
        preds, alphas = run_one_5fold(
            seed=seed,
            feature_set=feature_set,
            rocket_feats=feats,
            use_elasticnet=use_elasticnet,
        )
        elapsed = time.time() - t0
        rows.append(
            {
                "seed": seed,
                "variant": "rocket_only",
                "feature_set": feature_set,
                "stage2": "elasticnet" if use_elasticnet else "ridge",
                "n_rocket_features": int(feats.shape[1]),
                "ccc": round(float(ccc_fn(y_t3, preds)), 4),
                "mae": round(float(mae_fn(y_t3, preds)), 3),
                "r": round(float(pearson_r(y_t3, preds)), 4),
                "alpha_mean": round(float(np.mean(alphas)), 4),
                "alpha_median": round(float(np.median(alphas)), 4),
                "wall_time_s": round(elapsed, 1),
            }
        )
        print(
            f"  seed={seed} rocket_only: CCC={rows[-1]['ccc']:.4f}, "
            f"MAE={rows[-1]['mae']:.3f}, alpha_med={rows[-1]['alpha_median']:.3g}, "
            f"time={elapsed:.1f}s",
            flush=True,
        )

    df = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = RESULTS_DIR / f"iter28b_multirocket_5fold_{ts}.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}", flush=True)
    mean_ccc = df.groupby("variant")["ccc"].mean()
    std_ccc = df.groupby("variant")["ccc"].std()
    print("\nMean across seeds:", flush=True)
    for v in mean_ccc.index:
        print(f"  {v:25s}  CCC = {mean_ccc[v]:.4f} ± {std_ccc[v]:.4f}", flush=True)
    return out_csv


def mode_write_prereg(
    feature_set: str,
    num_kernels: int,
    seeds: list[int],
    use_elasticnet: bool,
) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    extras = ITER5_FEATURE_SETS[feature_set]
    prereg = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "experiment": "T3 iter28-B — MultiROCKET random convolutional kernels on raw IMU",
        "stage1": {
            "model": "Ridge(alpha=1.0)",
            "feature_set": feature_set,
            "extras": extras,
            "n_features": 6 + len(extras),
            "is_bit_identical_to_iter5": True,
        },
        "stage2": {
            "model": "ElasticNetCV(l1_ratio=0.5)" if use_elasticnet else "RidgeCV",
            "alpha_grid": list(ALPHA_GRID),
            "selector": None,
            "rationale": (
                "ROCKET features are designed for L2-regularised regression in p>>n. "
                "K-best selection is unnecessary and would discard the very high-frequency "
                "components ROCKET is built to capture."
            ),
            "feature_source": "MultiROCKET on raw IMU (26-channel acc-mag + gyr-mag, central 20s)",
            "num_kernels": num_kernels,
            "n_subjects": 98,
            "channels": list(SENSORS),
            "channel_construction": "sqrt(Acc_X^2 + Acc_Y^2 + Acc_Z^2) and sqrt(Gyr_X^2 + ...) per sensor",
            "window_samples": WINDOW_SAMPLES,
            "tasks": list(TASKS),
            "aggregation": "mean MultiROCKET feature vector across tasks per subject",
            "fold_local_standardisation": "FoldNormalizer (fit on train fold only)",
        },
        "eval_protocol": (
            "LOOCV (n=98); 3 seeds × 98 folds; mean-of-3-seed predictions = headline. "
            "MultiROCKET features are extracted ONCE per seed on the full PD cohort "
            "(this is allowed: ROCKET is unsupervised so the kernels carry no target "
            "leakage; the only supervised step is per-fold RidgeCV on (train_residual, train_features))."
        ),
        "headline_metric": "CCC of mean-of-3-seed predictions",
        "lockbox_rules": [
            "ONE config pre-registered. ONE LOOCV run. Headline = result.",
            "Apples-to-apples baseline: iter5 LOOCV CCC = 0.5227 on the same N=98.",
            "If LOOCV CCC <= 0.5227 + 0.005, report as null and do not retry tweaks.",
            "Bootstrap (n=5000) of (iter28b_ccc - iter5_ccc) on same 98 subjects must "
            "have frac_positive > 0.7 to claim a meaningful win.",
        ],
        "seeds": seeds,
        "iter5_canonical_loocv_ccc": 0.5227,
        "iter5_lockbox_oof": str(ITER5_LOCKBOX_OOF.name),
    }
    path = RESULTS_DIR / f"preregistration_t3_iter28b_multirocket_{ts}.json"
    with open(path, "w") as f:
        json.dump(prereg, f, indent=2, default=str)
    print(f"\nPRE-REGISTRATION WRITTEN: {path}", flush=True)
    return path


def _bootstrap_delta(
    y_true: np.ndarray,
    pred_a: np.ndarray,
    pred_b: np.ndarray,
    n_boot: int = 5000,
    rng_seed: int = 42,
) -> dict:
    rng = np.random.RandomState(rng_seed)
    n = len(y_true)
    deltas = np.empty(n_boot, dtype=np.float64)
    for i in range(n_boot):
        idx = rng.randint(0, n, size=n)
        deltas[i] = ccc_fn(y_true[idx], pred_a[idx]) - ccc_fn(y_true[idx], pred_b[idx])
    return {
        "n_boot": int(n_boot),
        "delta_mean": round(float(deltas.mean()), 4),
        "delta_ci_low": round(float(np.percentile(deltas, 2.5)), 4),
        "delta_ci_high": round(float(np.percentile(deltas, 97.5)), 4),
        "frac_positive": round(float((deltas > 0).mean()), 3),
        "frac_above_0p01": round(float((deltas > 0.01).mean()), 3),
    }


def mode_lockbox(
    preregistration_file: Path,
    seeds: list[int],
    num_kernels: int,
    n_workers: int,
) -> Path:
    if not preregistration_file.exists():
        raise FileNotFoundError(f"Pre-registration not found: {preregistration_file}")
    with open(preregistration_file) as f:
        prereg = json.load(f)
    feature_set = prereg["stage1"]["feature_set"]
    use_elasticnet = "ElasticNet" in prereg["stage2"]["model"]
    pre_seeds = prereg.get("seeds") or list(seeds)
    if list(pre_seeds) != list(seeds):
        print(
            f"  WARNING: requested seeds {seeds} differ from prereg {pre_seeds}; "
            "honouring prereg.",
            flush=True,
        )
        seeds = list(pre_seeds)

    print(
        f"\n=== iter28-B LOCKBOX LOOCV ({feature_set}, num_kernels={num_kernels}, "
        f"stage2={'ElasticNetCV' if use_elasticnet else 'RidgeCV'}, seeds={seeds}) ===",
        flush=True,
    )

    sids_ref: Optional[np.ndarray] = None
    y_ref: Optional[np.ndarray] = None
    all_preds: list[tuple[int, np.ndarray]] = []
    all_alphas: list[list[float]] = []
    for seed in seeds:
        cache = _features_cache_path(seed, num_kernels)
        sids, _X_v2, _fc, _y_t3, _hy, _obs = load_full_pd_data()
        feats = extract_multirocket_per_subject(
            sids=sids,
            num_kernels=num_kernels,
            seed=seed,
            n_workers=n_workers,
            cache_path=cache,
        )
        t0 = time.time()
        sids_l, y_t3, preds, alphas = run_one_loocv(
            seed=seed,
            feature_set=feature_set,
            rocket_feats=feats,
            use_elasticnet=use_elasticnet,
        )
        elapsed = time.time() - t0
        c = float(ccc_fn(y_t3, preds))
        m = float(mae_fn(y_t3, preds))
        r = float(pearson_r(y_t3, preds))
        print(
            f"  seed={seed}: CCC={c:.4f}, MAE={m:.3f}, r={r:.3f}, "
            f"alpha_med={np.median(alphas):.3g}, time={elapsed:.1f}s",
            flush=True,
        )
        all_preds.append((seed, preds))
        all_alphas.append(alphas)
        sids_ref = sids_l
        y_ref = y_t3

    assert sids_ref is not None and y_ref is not None
    mean_preds = np.mean(np.column_stack([p for _, p in all_preds]), axis=1)
    headline = full_metrics(y_ref, mean_preds, label="t3_iter28b_multirocket")

    # Bootstrap vs iter5
    if not ITER5_LOCKBOX_OOF.exists():
        raise FileNotFoundError(
            f"iter5 lockbox OOF not found at {ITER5_LOCKBOX_OOF}; "
            "cannot compute paired bootstrap delta."
        )
    iter5_preds = np.load(ITER5_LOCKBOX_OOF).astype(np.float64)
    if len(iter5_preds) != len(y_ref):
        raise RuntimeError(
            f"iter5 OOF length {len(iter5_preds)} != current N {len(y_ref)}; "
            "cohort drift detected."
        )
    iter5_ccc_on_ref = float(ccc_fn(y_ref, iter5_preds))
    boot = _bootstrap_delta(y_ref, mean_preds, iter5_preds, n_boot=5000, rng_seed=42)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t3_iter28b_multirocket_{ts}.json"
    out_oof = RESULTS_DIR / f"lockbox_t3_iter28b_multirocket_{ts}.oof.npy"
    out_sids = RESULTS_DIR / f"lockbox_t3_iter28b_multirocket_{ts}.sids.npy"
    np.save(out_oof, mean_preds)
    np.save(out_sids, sids_ref)

    headline.update(
        {
            "feature_set": feature_set,
            "stage2_model": "ElasticNetCV" if use_elasticnet else "RidgeCV",
            "num_kernels": num_kernels,
            "eval_mode": "loocv_3seed_mean",
            "n_seeds": len(seeds),
            "seeds": list(seeds),
            "per_seed_ccc": [float(ccc_fn(y_ref, p)) for _, p in all_preds],
            "per_seed_mae": [float(mae_fn(y_ref, p)) for _, p in all_preds],
            "per_subject": {
                "sids": sids_ref.tolist(),
                "y_true": y_ref.tolist(),
                "y_pred": mean_preds.tolist(),
            },
            "alphas_per_seed_median": [float(np.median(a)) for a in all_alphas],
            "preregistration_file": preregistration_file.name,
            "is_lockbox_headline": True,
            "baseline_iter5_loocv_ccc_on_same_98": round(iter5_ccc_on_ref, 4),
            "delta_vs_iter5": round(float(headline["ccc"]) - iter5_ccc_on_ref, 4),
            "bootstrap_delta_vs_iter5": boot,
        }
    )
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)

    print(
        f"\n=== HEADLINE (lockbox): CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f}, "
        f"r={headline['r']:.4f}, slope={headline['cal_slope']:.3f} ===",
        flush=True,
    )
    print(
        f"  Δ vs iter5 on same N=98: {headline['delta_vs_iter5']:+.4f}",
        flush=True,
    )
    print(
        f"  Bootstrap (n=5000): mean Δ={boot['delta_mean']:+.4f}, "
        f"95% CI=[{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}], "
        f"frac > 0 = {boot['frac_positive']}, frac > 0.01 = {boot['frac_above_0p01']}",
        flush=True,
    )
    print(f"Wrote {out_json}\nWrote {out_oof}\nWrote {out_sids}", flush=True)
    return out_json


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode",
        choices=["extract", "screen", "write_prereg", "lockbox"],
        required=True,
    )
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--num_kernels", type=int, default=10000)
    ap.add_argument(
        "--n_workers",
        type=int,
        default=int(os.getenv("ITER28B_WORKERS", 11)),
    )
    ap.add_argument(
        "--feature_set",
        default="A3_tier1",
        help="Stage 1 feature set (must exist in run_t3_iter5_clinical.FEATURE_SETS)",
    )
    ap.add_argument(
        "--elasticnet",
        action="store_true",
        help="Use ElasticNetCV(l1_ratio=0.5) instead of RidgeCV in Stage 2",
    )
    ap.add_argument(
        "--preregistration_file",
        type=str,
        default=None,
        help="Path to pre-registration JSON (required for --mode lockbox)",
    )
    args = ap.parse_args()

    if args.feature_set not in ITER5_FEATURE_SETS:
        raise ValueError(
            f"Unknown feature_set {args.feature_set!r}; "
            f"choose from {list(ITER5_FEATURE_SETS)}"
        )

    if args.mode == "extract":
        mode_extract(
            seeds=list(args.seeds),
            num_kernels=args.num_kernels,
            n_workers=args.n_workers,
        )
    elif args.mode == "screen":
        mode_screen(
            seeds=list(args.seeds),
            num_kernels=args.num_kernels,
            n_workers=args.n_workers,
            feature_set=args.feature_set,
            use_elasticnet=args.elasticnet,
        )
    elif args.mode == "write_prereg":
        mode_write_prereg(
            feature_set=args.feature_set,
            num_kernels=args.num_kernels,
            seeds=list(args.seeds),
            use_elasticnet=args.elasticnet,
        )
    else:  # lockbox
        if args.preregistration_file is None:
            raise SystemExit(
                "--mode lockbox requires --preregistration_file <path>"
            )
        mode_lockbox(
            preregistration_file=Path(args.preregistration_file),
            seeds=list(args.seeds),
            num_kernels=args.num_kernels,
            n_workers=args.n_workers,
        )


if __name__ == "__main__":
    main()
